"""Run public Bitget 5m replay for V4.1.2, V4.5.3 and V7.1.2.

This is a frozen replay: no parameter search.  It writes machine-readable
results and figures used by the external Chinese strategy report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v43 import V43Params, generate_v43_signals
from btc_regime.v453 import V453Params, generate_v453_signals
from btc_regime.v712 import V712Params, generate_v712_signals
from backtest_v413 import _direction_cycles

START = pd.Timestamp("2020-01-01", tz="UTC")
END = pd.Timestamp("2026-08-01", tz="UTC")
REBATE = 0.60
BASE_TAKER = 6.0
BASE_MAKER = 2.0


def aggregate(raw: pd.DataFrame, freq: str, expected: int) -> pd.DataFrame:
    cols = {
        "trade_open": "first", "trade_high": "max", "trade_low": "min", "trade_close": "last",
        "trade_base_volume": "sum", "trade_quote_volume": "sum",
    }
    out = raw.resample(freq, label="left", closed="left").agg(cols)
    out = out.rename(columns={
        "trade_open": "open", "trade_high": "high", "trade_low": "low", "trade_close": "close",
        "trade_base_volume": "volume", "trade_quote_volume": "quote_volume",
    })
    count = raw.trade_close.resample(freq, label="left", closed="left").count()
    return out.loc[count.eq(expected)].dropna(subset=["open", "high", "low", "close"])


def load_data(data_dir: Path):
    raw = pd.read_pickle(data_dir / "candles_5m.pkl").sort_index()
    raw.index = pd.to_datetime(raw.index, utc=True)
    raw = raw.loc[(raw.index >= START) & (raw.index < END)]
    expected_idx = pd.date_range(START, END - pd.Timedelta(minutes=5), freq="5min", tz="UTC")
    missing = expected_idx.difference(raw.index)
    if len(missing):
        raise ValueError(f"missing {len(missing)} five-minute rows")
    hourly = aggregate(raw, "1h", 12)
    hourly["funding_rate"] = 0.0
    hourly["funding_event"] = False
    funding = pd.read_pickle(data_dir / "funding.pkl")
    funding.index = pd.to_datetime(funding.index, utc=True)
    funding = funding.sort_index()
    for ts, row in funding.iterrows():
        bucket = ts.floor("1h")
        if bucket in hourly.index:
            hourly.loc[bucket, "funding_rate"] += float(row.funding_rate)
            hourly.loc[bucket, "funding_event"] = True
    four = aggregate(raw, "4h", 48)
    four["funding_rate"] = 0.0
    four["funding_event"] = False
    for ts, row in funding.iterrows():
        bucket = ts.floor("4h")
        if bucket in four.index:
            four.loc[bucket, "funding_rate"] += float(row.funding_rate)
            four.loc[bucket, "funding_event"] = True
    return raw, hourly, four, funding


def batches(raw: pd.DataFrame):
    month = raw.index.strftime("%Y-%m")
    for key in month.unique():
        part = raw.loc[month == key].rename(columns={
            "trade_base_volume": "trade_volume",
        })
        yield part[["trade_open", "trade_high", "trade_low", "trade_close", "trade_volume",
                    "trade_quote_volume", "mark_open", "mark_high", "mark_low", "mark_close"]]


def build_signals(hourly, four):
    p412 = V43Params(**json.loads((ROOT / "configs/v4_1_2_params.json").read_text()))
    p453 = V453Params(**json.loads((ROOT / "configs/v4_5_3_params.json").read_text())["signal_params"])
    p712 = V712Params(**json.loads((ROOT / "configs/v712_params.json").read_text()))
    return {
        "V4.1.2": _direction_cycles(generate_v43_signals(four, p412)),
        "V4.5.3": generate_v453_signals(hourly, p453),
        "V7.1.2": generate_v712_signals(four, p712),
    }, {"V4.1.2": p412, "V4.5.3": p453, "V7.1.2": p712}


def config(name, *, taker_mult=1.0, maker_mult=1.0, slip_mult=1.0):
    old = name in {"V4.1.2", "V7.1.2"}
    return MicroBacktestConfig(
        initial_cash=10_000.0,
        taker_fee_bps=BASE_TAKER * (1 - REBATE) * taker_mult,
        maker_fee_bps=BASE_MAKER * (1 - REBATE) * maker_mult,
        maker_enabled=name != "V4.1.2" or name == "V7.1.2",
        maker_offset_bps=0.0,
        maker_order_timeout_minutes=60,
        maker_exit_enabled=False,
        conservative_protection=name != "V7.1.2",
        signal_interval_minutes=240 if old else 60,
        equity_interval_minutes=240 if old else 60,
        execution_bar_minutes=5,
        periods_per_year=2190 if old else 8760,
        base_slippage_bps=1.0 * slip_mult,
        impact_bps=8.0 * slip_mult,
        max_minute_participation=0.02,
        liquidation_fee_bps=50.0,
    )


def metrics(equity: pd.Series, result, start=START, end=END):
    e = equity.loc[(equity.index >= start) & (equity.index < end)].dropna()
    daily = e.resample("1D", closed="right", label="right").last().dropna()
    ret = daily.pct_change().dropna()
    years = max((e.index[-1] - e.index[0]).total_seconds() / (365.25 * 86400), 1 / 365.25)
    sd = ret.std(ddof=1)
    draw = e / e.cummax() - 1
    trades = result.trades.loc[(result.trades.exit_time >= start) & (result.trades.exit_time < end)]
    fills = result.fills.loc[(result.fills.timestamp >= start) & (result.fills.timestamp < end)]
    wins = trades.pnl > 0
    return {
        "initial_equity": float(e.iloc[0]), "final_equity": float(e.iloc[-1]),
        "total_return": float(e.iloc[-1] / e.iloc[0] - 1),
        "cagr": float((e.iloc[-1] / e.iloc[0]) ** (1 / years) - 1),
        "sharpe": float(ret.mean() / sd * np.sqrt(365.25)) if sd > 0 else 0.0,
        "sortino": float(ret.mean() / ret[ret < 0].std(ddof=1) * np.sqrt(365.25)) if (ret < 0).sum() > 2 and ret[ret < 0].std(ddof=1) > 0 else 0.0,
        "annualized_volatility": float(sd * np.sqrt(365.25)) if pd.notna(sd) else 0.0,
        "max_drawdown": float(draw.min()),
        "days": int(len(ret)), "trades": int(len(trades)),
        "long_trades": int((trades.side == "long").sum()), "short_trades": int((trades.side == "short").sum()),
        "win_rate": float(wins.mean()) if len(wins) else 0.0,
        "median_holding_hours": float((trades.exit_time - trades.entry_time).dt.total_seconds().median() / 3600) if len(trades) else 0.0,
        "fills": int(len(fills)), "maker_fills": int((fills.liquidity == "maker").sum()), "taker_fills": int((fills.liquidity == "taker").sum()),
        "maker_fill_share": float((fills.liquidity == "maker").mean()) if len(fills) else 0.0,
        "turnover_usdt": float(fills.notional.sum()) if len(fills) else 0.0,
        "fees_usdt": float(fills.fee.sum()) if len(fills) else 0.0,
        "funding_paid_usdt": float(result.funding.payment.sum()) if len(result.funding) and "payment" in result.funding else 0.0,
        "liquidations": int(len(result.liquidations)),
    }


def annual_metrics(equity: pd.Series, result):
    out = []
    for year in range(2020, 2027):
        a = pd.Timestamp(f"{year}-01-01", tz="UTC")
        b = min(END, pd.Timestamp(f"{year+1}-01-01", tz="UTC"))
        if a >= b: continue
        m = metrics(equity, result, a, b)
        out.append({"year": year, **m})
    return out


def run_case(name, signals, raw, funding, out_dir, scenario="base", taker_mult=1.0, maker_mult=1.0, slip_mult=1.0):
    cfg = config(name, taker_mult=taker_mult, maker_mult=maker_mult, slip_mult=slip_mult)
    result = run_micro_backtest(signals[name], batches(raw), funding, cfg)
    dest = out_dir / name / scenario
    dest.mkdir(parents=True, exist_ok=True)
    result.equity.to_csv(dest / "equity.csv", header=True)
    result.fills.to_csv(dest / "fills.csv", index=False)
    result.trades.to_csv(dest / "trades.csv", index=False)
    result.funding.to_csv(dest / "funding.csv", index=False)
    result.liquidations.to_csv(dest / "liquidations.csv", index=False)
    m = metrics(result.equity, result)
    payload = {"strategy": name, "scenario": scenario, "execution": asdict(cfg), "metrics": m, "annual": annual_metrics(result.equity, result)}
    (dest / "report.json").write_text(json.dumps(payload, indent=2, default=float))
    return payload, result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=ROOT / "data/bitget_v4")
    ap.add_argument("--output", type=Path, default=ROOT / "reports/bitget_three_60")
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    raw, hourly, four, funding = load_data(args.data)
    signals, params = build_signals(hourly, four)
    rows = []
    results = {}
    for name in ["V4.1.2", "V4.5.3", "V7.1.2"]:
        payload, result = run_case(name, signals, raw, funding, args.output)
        rows.append(payload); results[name] = result
        # Cost and execution sensitivity: transparent deterministic proxies.
        for scenario, tm, mm, sm in [("fees_plus_50pct", 1.5, 1.5, 1.0), ("slippage_double", 1.0, 1.0, 2.0)]:
            p, _ = run_case(name, signals, raw, funding, args.output, scenario, tm, mm, sm)
            rows.append(p)
    # Unified equity panel and key tables.
    eq = pd.DataFrame({name: result.equity for name, result in results.items()})
    eq.to_csv(args.output / "equity_curves.csv")
    daily = eq.resample("1D").last().dropna(how="all")
    dd = daily / daily.cummax() - 1
    dd.to_csv(args.output / "drawdowns.csv")
    summary = pd.DataFrame([{**r["metrics"], "strategy": r["strategy"], "scenario": r["scenario"]} for r in rows])
    summary.to_csv(args.output / "summary_metrics.csv", index=False)
    annual = pd.DataFrame([{**x, "strategy": r["strategy"], "scenario": r["scenario"]} for r in rows for x in r["annual"]])
    annual.to_csv(args.output / "annual_metrics.csv", index=False)
    manifest = json.loads((args.data / "manifest.json").read_text())
    protocol = {
        "report_scope": {"requested_end": "2026-10-06", "observed_end_exclusive": END.isoformat(), "observed_last_candle": raw.index.max().isoformat()},
        "data_manifest": manifest, "strategies": ["V4.1.2", "V4.5.3", "V7.1.2"],
        "fee_policy": {"published_taker_bps": BASE_TAKER, "published_maker_bps": BASE_MAKER, "rebate_fraction": REBATE, "effective_taker_bps": BASE_TAKER*(1-REBATE), "effective_maker_bps": BASE_MAKER*(1-REBATE)},
        "execution": "5m OHLC execution and mark-price proxy; maker touch model; protective exits taker; participation cap 2%; deterministic impact/slippage",
        "funding": "Only public Bitget funding records in local cache are applied; earlier missing settlements are not fabricated.",
        "parameter_search": False,
        "limits": ["Local Bitget candle cache ends 2026-07-31 23:55 UTC; 2026-08-01 to 2026-10-06 is not represented in the replay.", "Public data-download UI can expose 1m files, but browser policy blocked automated retrieval in this run.", "Five-minute OHLC execution is a coarser proxy than tick/order-book replay; maker queue priority is not observed.", "Historical maintenance-margin brackets and funding coverage are explicit model assumptions."],
        "data_sha256": hashlib.sha256(pd.util.hash_pandas_object(raw, index=True).values.tobytes()).hexdigest(),
    }
    (args.output / "protocol.json").write_text(json.dumps(protocol, indent=2, ensure_ascii=False))
    print(summary.loc[summary.scenario.eq("base"), ["strategy", "total_return", "cagr", "sharpe", "max_drawdown", "trades", "fills", "liquidations"]].to_string(index=False))

if __name__ == "__main__":
    main()
