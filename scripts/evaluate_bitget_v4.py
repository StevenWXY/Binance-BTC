"""Replay the frozen V4 strategy set on Bitget BTCUSDT perpetual data.

The Bitget public market API is downloaded at five-minute resolution.  Five
minute candles are passed to the existing execution engine as the execution
bar, while strategy signals are generated from complete hourly/4-hour bars.
This keeps fills and mark-to-market on separate market/mark series and makes
the lower resolution explicit in the report.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest  # noqa: E402
from btc_regime.rebate_audit import combine_completed_equity  # noqa: E402
from btc_regime.v42 import V42CapitalParams, generate_neutral_sleeve  # noqa: E402
from btc_regime.v43 import V43Params, generate_v43_signals  # noqa: E402
from btc_regime.v453 import V453Params, generate_v453_signals  # noqa: E402
from btc_regime.v454 import generate_v454_signals  # noqa: E402
from backtest_v413 import _direction_cycles  # noqa: E402


DATA = ROOT / "data" / "bitget_v4"
OUT = ROOT / "reports" / "v4_bitget60"
START = pd.Timestamp("2020-01-01", tz="UTC")
END = pd.Timestamp("2026-08-01", tz="UTC")
STRATEGIES = ["V4.1.2", "V4.2.2", "V4.5.2", "V4.5.3", "V4.5.4"]
WINDOWS = {"full": START, "post2024": pd.Timestamp("2024-01-01", tz="UTC"),
           "post2025": pd.Timestamp("2025-01-01", tz="UTC")}


def load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def aggregate(frame: pd.DataFrame, frequency: str, expected: int | None = None) -> pd.DataFrame:
    agg = {
        "trade_open": "first", "trade_high": "max", "trade_low": "min", "trade_close": "last",
        "trade_base_volume": "sum", "trade_quote_volume": "sum",
        "mark_open": "first", "mark_high": "max", "mark_low": "min", "mark_close": "last",
    }
    result = frame.resample(frequency, label="left", closed="left").agg(agg)
    result = result.rename(columns={
        "trade_open": "open", "trade_high": "high", "trade_low": "low", "trade_close": "close",
        "trade_base_volume": "volume", "trade_quote_volume": "quote_volume",
    })
    if expected is not None:
        counts = frame.trade_close.resample(frequency, label="left", closed="left").count()
        result = result.loc[counts.eq(expected)]
    return result


def prepare_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw = pd.read_pickle(DATA / "candles_5m.pkl").sort_index()
    raw.index = pd.to_datetime(raw.index, utc=True)
    raw = raw.loc[(raw.index >= START) & (raw.index < END)]
    expected = pd.date_range(START, END - pd.Timedelta(minutes=5), freq="5min", tz="UTC")
    missing = expected.difference(raw.index)
    if len(missing):
        raise ValueError(f"Bitget candle series has {len(missing)} missing 5m rows; refusing to fill prices")
    hourly = aggregate(raw, "1h", 12)
    # Signal generation uses the market close/volume and the actual settled
    # funding event columns.  Mark prices remain available for short protection.
    hourly["funding_rate"] = 0.0
    hourly["funding_event"] = False
    funding = pd.read_pickle(DATA / "funding.pkl")
    funding.index = pd.to_datetime(funding.index, utc=True)
    funding = funding.sort_index()
    if not funding.empty:
        for timestamp, row in funding.iterrows():
            bucket = timestamp.floor("1h")
            if bucket in hourly.index:
                hourly.loc[bucket, "funding_rate"] += float(row.funding_rate)
                hourly.loc[bucket, "funding_event"] = True
    return raw, hourly, funding


def aggregate_4h(hourly: pd.DataFrame) -> pd.DataFrame:
    cols = {"open": "first", "high": "max", "low": "min", "close": "last",
            "volume": "sum", "quote_volume": "sum", "funding_rate": "sum", "funding_event": "any"}
    four = hourly.resample("4h", label="left", closed="left").agg(cols)
    count = hourly.close.resample("4h", label="left", closed="left").count()
    return four.loc[count.eq(4)]


def digest(frame: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(frame, index=True).values.tobytes()).hexdigest()


def signal_set(hourly: pd.DataFrame) -> dict[str, pd.DataFrame]:
    four = aggregate_4h(hourly)
    p41 = V43Params(**load_json(ROOT / "configs/v4_1_2_params.json"))
    p42 = V43Params(**load_json(ROOT / "configs/v4_2_2_params.json"))
    signals = {
        "V4.1.2": _direction_cycles(generate_v43_signals(four, p41)),
        "V4.2.2": generate_v43_signals(four, p42),
    }
    p453 = V453Params(**load_json(ROOT / "configs/v4_5_3_params.json")["signal_params"])
    base = generate_v453_signals(hourly, p453)
    signals["V4.5.2"] = base
    signals["V4.5.3"] = base.copy()
    signals["V4.5.4"] = generate_v454_signals(hourly, p453, direction_allocation=.75)
    return signals


def batches(raw: pd.DataFrame):
    # Monthly chunks bound memory and preserve a strict global order.
    month = raw.index.strftime("%Y-%m")
    for key in month.unique():
        part = raw.loc[month == key].copy()
        part = part.rename(columns={
            "trade_open": "trade_open", "trade_high": "trade_high", "trade_low": "trade_low",
            "trade_close": "trade_close", "trade_base_volume": "trade_volume",
            "trade_quote_volume": "trade_quote_volume", "mark_open": "mark_open",
            "mark_high": "mark_high", "mark_low": "mark_low", "mark_close": "mark_close",
        })
        yield part[["trade_open", "trade_high", "trade_low", "trade_close", "trade_volume",
                    "trade_quote_volume", "mark_open", "mark_high", "mark_low", "mark_close"]]


def daily_metrics(equity: pd.Series, start: pd.Timestamp) -> dict[str, float]:
    e = equity.loc[(equity.index >= start) & (equity.index < END)]
    if len(e) < 2:
        return {"total_return": 0.0, "cagr": 0.0, "sharpe": 0.0, "annualized_volatility": 0.0,
                "max_drawdown": 0.0, "days": 0}
    daily = e.resample("1D", closed="right", label="right").last().dropna()
    returns = daily.pct_change().dropna()
    years = max((e.index[-1] - e.index[0]).total_seconds() / (365.25 * 86400), 1 / 365.25)
    sd = returns.std(ddof=1)
    return {
        "total_return": float(e.iloc[-1] / e.iloc[0] - 1),
        "cagr": float((e.iloc[-1] / e.iloc[0]) ** (1 / years) - 1),
        "sharpe": float(returns.mean() / sd * np.sqrt(365.25)) if sd > 0 else 0.0,
        "annualized_volatility": float(sd * np.sqrt(365.25)),
        "max_drawdown": float((e / e.cummax() - 1).min()),
        "days": int(len(returns)),
    }


def stats(equity: pd.Series, result, neutral: pd.DataFrame | None, start: pd.Timestamp) -> dict[str, float]:
    trades = result.trades.loc[(result.trades.exit_time >= start) & (result.trades.exit_time < END)]
    fills = result.fills.loc[(result.fills.timestamp >= start) & (result.fills.timestamp < END)]
    years = (END - start).total_seconds() / (365.25 * 86400)
    payload = daily_metrics(equity, start)
    payload.update({
        "cycles": int(len(trades)), "short_cycles": int(trades.side.eq("short").sum()),
        "long_cycles": int(trades.side.eq("long").sum()), "cycles_per_year": len(trades) / years,
        "fills": int(len(fills)), "fills_per_year": len(fills) / years,
        "taker_fills": int(fills.liquidity.eq("taker").sum()),
        "maker_fills": int(fills.liquidity.eq("maker").sum()),
        "turnover_usdt": float(fills.notional.sum()), "fees_usdt": float(fills.fee.sum()),
        "median_holding_hours": float(((trades.exit_time - trades.entry_time).dt.total_seconds() / 3600).median()) if len(trades) else 0.0,
    })
    if neutral is not None:
        n = neutral.loc[(neutral.index >= start) & (neutral.index < END)]
        payload.update({"neutral_state_changes": int(n.state_changed.sum()),
                        "neutral_active_fraction": float(n.active.mean()) if len(n) else 0.0})
    return payload


def run_one(name: str, signal: pd.DataFrame, raw: pd.DataFrame, funding: pd.DataFrame) -> dict:
    old = name in {"V4.1.2", "V4.2.2"}
    config = MicroBacktestConfig(
        signal_interval_minutes=240 if old else 60,
        equity_interval_minutes=240 if old else 60,
        execution_bar_minutes=5,
        periods_per_year=2190 if old else 8760,
        conservative_protection=name != "V4.2.2",
        # Bitget standard fees: 6 bps taker / 2 bps maker, after 60% rebate.
        taker_fee_bps=2.4, maker_fee_bps=.8,
        maker_enabled=name != "V4.5.2", maker_offset_bps=0.,
        maker_order_timeout_minutes=60, maker_exit_enabled=False,
        base_slippage_bps=1., impact_bps=8., max_minute_participation=.02,
    )
    result = run_micro_backtest(signal, batches(raw), funding, config)
    equity = result.equity
    neutral = None
    if name in {"V4.2.2", "V4.5.4"} and not funding.empty:
        capital = V42CapitalParams(**(load_json(ROOT / "configs/v4_5_4_params.json")["capital_overlay"]
                                     if name == "V4.5.4" else load_json(ROOT / "configs/v4_2_capital_params.json")))
        # The legacy neutral sleeve models a spot/perpetual transition. Apply
        # the same 60% fee factor and disclose it separately from Bitget fills.
        neutral_fees = replace(capital, spot_fee_bps=capital.spot_fee_bps * .4,
                               futures_fee_bps=capital.futures_fee_bps * .4)
        neutral = generate_neutral_sleeve(funding, neutral_fees)
        available = signal.signal.copy()
        available.index += pd.Timedelta(minutes=config.signal_interval_minutes)
        frame = combine_completed_equity(equity, neutral, neutral_fees, available)
        equity = frame.combined_equity
        frame.to_csv(OUT / f"{name}_combined_equity.csv")
        neutral.to_csv(OUT / f"{name}_neutral_schedule.csv")
    dest = OUT / name
    dest.mkdir(parents=True, exist_ok=True)
    result.equity.to_csv(dest / "direction_equity.csv", header=True)
    result.fills.to_csv(dest / "fills.csv", index=False)
    result.trades.to_csv(dest / "trades.csv", index=False)
    result.funding.to_csv(dest / "funding_paid.csv", index=False)
    equity.to_csv(dest / "equity.csv", header=True)
    windows = {key: stats(equity, result, neutral, start) for key, start in WINDOWS.items() if start < END}
    row = {"strategy": name, "windows": windows, "execution": asdict(config),
           "execution_metrics": result.metrics,
           "funding_data": {"rows": int(len(funding)), "start": funding.index.min().isoformat() if len(funding) else None,
                            "end": funding.index.max().isoformat() if len(funding) else None},
           "neutral_data_available": bool(neutral is not None)}
    (dest / "report.json").write_text(json.dumps(row, indent=2, default=float) + "\n")
    return row


def main() -> None:
    global DATA
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DATA)
    args = parser.parse_args()
    DATA = args.data
    OUT.mkdir(parents=True, exist_ok=True)
    raw, hourly, funding = prepare_data()
    signals = signal_set(hourly)
    rows = [run_one(name, signals[name], raw, funding) for name in STRATEGIES]
    manifest = load_json(DATA / "manifest.json")
    protocol = {
        "created_at": datetime.now(timezone.utc).isoformat(), "data_manifest": manifest,
        "strategies": STRATEGIES, "window": [START.isoformat(), END.isoformat()],
        "bar_resolution": "5m execution; hourly V4.5 signals; 4h V4.1/V4.2 signals",
        "fee_policy": {"bitget_published_taker_bps": 6., "bitget_published_maker_bps": 2.,
                       "rebate_fraction": .60, "effective_taker_bps": 2.4, "effective_maker_bps": .8},
        "funding_policy": "Only funding settlements returned by the public Bitget endpoint are used; missing earlier rates are zero for direction signals and absent from the neutral sleeve.",
        "data_hash": digest(raw),
        "limits": ["Bitget public v3 funding history is last 90 days; this run does not fabricate older funding.",
                   "Five-minute OHLC execution is a coarser proxy than the repository's original one-minute Binance replay.",
                   "Maker fills, impact and liquidation brackets remain deterministic research assumptions."],
    }
    (OUT / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    (OUT / "comparison.json").write_text(json.dumps(rows, indent=2, default=float) + "\n")
    flat = [{"strategy": row["strategy"], "window": key, **metrics}
            for row in rows for key, metrics in row["windows"].items()]
    pd.DataFrame(flat).to_csv(OUT / "comparison.csv", index=False)
    lines = [
        "# Bitget V4 strategy replay (60% rebate)", "",
        "Data: BTCUSDT USDT-FUTURES, 5-minute market and mark candles, "
        "2020-01-01 through 2026-07-31 UTC.", "",
        "Fees: Bitget standard 6 bps taker / 2 bps maker, after 60% rebate "
        "= 2.4 / 0.8 bps. Funding uses only the public endpoint coverage.", "",
        "| Strategy | Window | Return | CAGR | Sharpe | Max DD | Cycles | Cycles/yr | Fills | Fills/yr | Shorts |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in flat:
        lines.append("| {strategy} | {window} | {total_return:.2%} | {cagr:.2%} | {sharpe:.3f} | {max_drawdown:.2%} | {cycles} | {cycles_per_year:.1f} | {fills} | {fills_per_year:.1f} | {short_cycles} |".format(**row))
    lines += ["", "See `protocol.json` for data hashes, funding coverage and research limitations."]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")
    print(pd.DataFrame(flat).to_string(index=False))


if __name__ == "__main__":
    main()
