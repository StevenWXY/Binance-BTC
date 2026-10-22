"""Paired 40%/60% fee replay of the five recently compared V4 strategies.

No parameter search. Replay both fees on the same repaired minute cache.
Preserve each frozen direction execution policy. Correct overlay completion
timestamps in this new report and keep archived-method diagnostics separate.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
from itertools import chain
import json
from pathlib import Path

import pandas as pd

from btc_regime.data import load_market_data
from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.rebate_audit import combine_completed_equity
from btc_regime.v42 import V42CapitalParams, combine_direction_and_neutral, generate_neutral_sleeve
from btc_regime.v43 import V43Params, generate_v43_signals
from btc_regime.v453 import V453Params, generate_v453_signals
from btc_regime.v454 import generate_v454_signals
from backtest_v413 import _direction_cycles
from compare_v412_v422_v452 import metric
from evaluate_v441 import minute_batches
from evaluate_v444 import inputs


OUT = Path("reports/v4_rebate60")
CACHE = Path("data/v441/rebate60")
STRATEGIES = ["V4.1.2", "V4.2.2", "V4.5.2", "V4.5.3", "V4.5.4"]
END = pd.Timestamp("2026-08-01", tz="UTC")
WINDOWS = {"full": "2020-01-01", "post2024": "2024-01-01", "later": "2026-01-15"}


def read_json(path):
    return json.loads(Path(path).read_text())


def digest(frame):
    return hashlib.sha256(pd.util.hash_pandas_object(frame, index=True).values.tobytes()).hexdigest()


def prepare():
    CACHE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    hourly, funding, _ = inputs()
    assert not funding.index.has_duplicates
    funding.to_pickle(CACHE / "funding.pkl")
    four = load_market_data("data/raw", start="2020-01-01", end="2026-08-01")
    four = four.loc[four.index < END]
    signals = {
        "V4.1.2": _direction_cycles(generate_v43_signals(four, V43Params(**read_json("configs/v4_1_2_params.json")))),
        "V4.2.2": generate_v43_signals(four, V43Params(**read_json("configs/v4_2_2_params.json"))),
    }
    p = V453Params(**read_json("configs/v4_5_3_params.json")["signal_params"])
    base = generate_v453_signals(hourly, p)
    signals["V4.5.2"] = base
    signals["V4.5.3"] = base
    signals["V4.5.4"] = generate_v454_signals(hourly, p, direction_allocation=.75)
    # The archived evaluator regenerates shorts over a frame already containing
    # shorts. Confirm the direct frozen API gives the same executable targets.
    archived = generate_v454_signals(hourly, p, direction_allocation=.75, long_signals=base)
    cols = ["signal", "stop_price", "take_profit_price", "cycle_id"]
    pd.testing.assert_frame_equal(signals["V4.5.4"][cols], archived[cols])
    signatures = {}
    for name, frame in signals.items():
        frame.to_pickle(CACHE / f"{name}.pkl")
        signatures[name] = digest(frame[cols]) if "cycle_id" in frame else digest(frame[cols[:-1]])
    expected = int((END - pd.Timestamp("2020-01-01", tz="UTC")).total_seconds() / 60)
    observed = 0
    previous_end = None
    minutes_hash = hashlib.sha256()
    for batch in minute_batches(Path("data/v441"), "2020-01-01", "2026-08-01"):
        assert batch.index.is_monotonic_increasing and not batch.index.has_duplicates
        assert previous_end is None or previous_end < batch.index[0]
        previous_end = batch.index[-1]
        observed += len(batch)
        minutes_hash.update(digest(batch).encode())
    protocol = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "strategies": STRATEGIES, "rebates": [.4, .6],
        "window": ["2020-01-01", "2026-08-01"], "parameter_search": False,
        "initial_cash": 10000, "signal_signatures": signatures,
        "minute_data_sha256": minutes_hash.hexdigest(), "funding_sha256": digest(funding),
        "coverage": {"expected_minutes": expected, "observed_minutes": observed, "missing_minutes": expected - observed},
        "fee_policy": {"published_taker_bps": 4., "published_maker_bps": .2,
                       "rebate_applies_to": "trading fees only; neutral spot/futures transition fees follow legacy policy",
                       "slippage_funding_liquidation_rebated": False},
        "accounting": "Completion timestamps preserved; neutral settlements booked at the next equity observation, allocation lagged one observation.",
        "limits": ["Historical research data, not blind OOS", "Maker OHLC-touch proxy lacks order queues",
                   "Neutral proxy omits basis PnL and recall/redeployment trading costs; idle APY 4% is assumed",
                   "V4.2.2 preserves its archived non-conservative protective fill configuration; compare fee pairs, not execution realism across strategies"],
    }
    (OUT / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")


def statistics(equity, result, neutral, start, end=END):
    start = pd.Timestamp(start, tz="UTC")
    trades = result.trades.loc[(result.trades.exit_time >= start) & (result.trades.exit_time < end)]
    fills = result.fills.loc[(result.fills.timestamp >= start) & (result.fills.timestamp < end)]
    years = (end - start).total_seconds() / (365.25 * 86400)
    fee = float(fills.fee.sum())
    maker = fills.liquidity.eq("maker")
    values = {
        **metric(equity, start, end),
        "cycles": len(trades), "short_cycles": int(trades.side.eq("short").sum()),
        "cycles_per_year": len(trades) / years, "fills": len(fills), "fills_per_year": len(fills) / years,
        "median_holding_hours": float((trades.exit_time - trades.entry_time).dt.total_seconds().median() / 3600),
        "direction_trading_fees_usdt": fee,
        "direction_turnover_usdt": float(fills.notional.sum()),
        "maker_notional_share": float(fills.loc[maker, "notional"].sum() / fills.notional.sum()),
    }
    if neutral is not None:
        n = neutral.loc[(neutral.index >= start) & (neutral.index < end)]
        values.update(neutral_state_changes=int(n.state_changed.sum()), neutral_active_fraction=float(n.active.mean()))
    return values


def run_case(job):
    name, rebate = job
    signal = pd.read_pickle(CACHE / f"{name}.pkl")
    funding = pd.read_pickle(CACHE / "funding.pkl")
    old = name in {"V4.1.2", "V4.2.2"}
    config = MicroBacktestConfig(
        signal_interval_minutes=240 if old else 60,
        equity_interval_minutes=240 if old else 60,
        periods_per_year=2190 if old else 8760,
        conservative_protection=name != "V4.2.2",
        taker_fee_bps=4 * (1 - rebate), maker_fee_bps=.2 * (1 - rebate),
        maker_enabled=name != "V4.5.2", maker_offset_bps=0.,
        maker_order_timeout_minutes=60, maker_exit_enabled=False,
        base_slippage_bps=1., impact_bps=8., max_minute_participation=.02,
    )
    batches = minute_batches(Path("data/v441"), "2020-01-01", "2026-08-01")
    if not old:
        batches = chain(batches, [pd.read_pickle("data/v441/round2/extension_minutes.pkl")])
    result = run_micro_backtest(signal, batches, funding, config)
    dest = OUT / f"{name}__rebate{int(rebate * 100)}"
    dest.mkdir(exist_ok=True)
    result.equity.to_csv(dest / "direction_equity.csv")
    result.fills.to_csv(dest / "fills.csv", index=False)
    result.trades.to_csv(dest / "trades.csv", index=False)
    equity = result.equity
    neutral = None
    old_equity = equity
    audit = None
    if name in {"V4.2.2", "V4.5.4"}:
        capital = V42CapitalParams(**(read_json("configs/v4_5_4_params.json")["capital_overlay"]
                                     if name == "V4.5.4" else read_json("configs/v4_2_capital_params.json")))
        fees = replace(capital, spot_fee_bps=capital.spot_fee_bps * (1 - rebate),
                       futures_fee_bps=capital.futures_fee_bps * (1 - rebate))
        active_funding = funding.loc[funding.index < END] if old else funding
        neutral = generate_neutral_sleeve(active_funding, fees)
        neutral.to_csv(dest / "neutral_schedule.csv")
        available = signal.signal.copy()
        available.index += pd.Timedelta(minutes=config.signal_interval_minutes)
        frame = combine_completed_equity(equity, neutral, fees, available)
        equity = frame.combined_equity
        frame.to_csv(dest / "combined_equity.csv")
        # Reproduce the previous timestamp convention as a labelled diagnostic.
        if name == "V4.5.4":
            old_direction = result.equity.resample("4h", label="left", closed="left").last().dropna()
            old_signal = signal.signal.resample("4h", label="left", closed="left").last().reindex(old_direction.index).ffill().fillna(0.)
        else:
            old_direction, old_signal = result.equity, available
        old_frame, _ = combine_direction_and_neutral(old_direction, neutral, fees, old_signal)
        old_equity = old_frame.combined_equity
        old_frame.to_csv(dest / "legacy_timestamp_equity.csv")
        checks = []
        for cut in ["2024-01-01", "2025-07-01", "2026-01-01"]:
            t = pd.Timestamp(cut, tz="UTC")
            prefix = combine_completed_equity(result.equity.loc[:t], neutral.loc[neutral.index < t], fees, available.loc[:t])
            pd.testing.assert_frame_equal(prefix, frame.loc[:t])
            checks.append({"cut": cut, "passed": True})
        audit = checks
    equity.to_csv(dest / "equity.csv")
    windows = {key: statistics(equity, result, neutral, start) for key, start in WINDOWS.items()}
    yearly = {str(year): statistics(equity, result, neutral, f"{year}-01-01",
                                    min(END, pd.Timestamp(f"{year + 1}-01-01", tz="UTC"))) for year in range(2020, 2027)}
    row = {"strategy": name, "rebate": rebate, "execution": asdict(config),
           "windows": windows, "yearly": yearly, "overlay_prefix_checks": audit,
           "archived_timestamp_method": {key: metric(old_equity, pd.Timestamp(start, tz="UTC"), END) for key, start in WINDOWS.items()},
           "execution_metrics_through_simulation_end": result.metrics,
           "simulation_end_exclusive": "2026-08-01" if old else "2026-09-01"}
    (dest / "report.json").write_text(json.dumps(row, indent=2, allow_nan=False) + "\n")
    r = windows["post2024"]
    print(name, rebate, f"post2024 R={r['total_return']:.6f} S={r['sharpe']:.6f} DD={r['max_drawdown']:.6f}", flush=True)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--reuse", action="store_true", help="Only rebuild aggregate JSON/CSV from completed case reports")
    args = parser.parse_args()
    jobs = [(name, rebate) for name in STRATEGIES for rebate in [.4, .6]]
    if args.reuse:
        rows = [read_json(OUT / f"{name}__rebate{int(rebate * 100)}/report.json") for name, rebate in jobs]
    else:
        prepare()
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            rows = list(pool.map(run_case, jobs))
    checks = []
    for name in STRATEGIES:
        pair = [r for r in rows if r["strategy"] == name]
        old_cfg, new_cfg = (r["execution"] for r in pair)
        changed = [k for k in old_cfg if old_cfg[k] != new_cfg[k]]
        assert set(changed) == {"taker_fee_bps", "maker_fee_bps"}
        checks.append({"strategy": name, "changed_execution_fields": changed})
    payload = {"protocol": read_json(OUT / "protocol.json"), "fee_pair_checks": checks, "cases": rows}
    (OUT / "report.json").write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    flat = [{"strategy": r["strategy"], "rebate": r["rebate"], "window": w, **m}
            for r in rows for w, m in r["windows"].items()]
    pd.DataFrame(flat).to_csv(OUT / "comparison.csv", index=False)
    years = [{"strategy": r["strategy"], "rebate": r["rebate"], "year": y, **m}
             for r in rows for y, m in r["yearly"].items()]
    pd.DataFrame(years).to_csv(OUT / "yearly.csv", index=False)


if __name__ == "__main__":
    main()
