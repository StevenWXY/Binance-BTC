"""Re-run the frozen three-strategy Bitget replay through 2026-10-06.

This is intentionally separate from the original 2026-08-01 replay script so
the historical artifact remains reproducible.  It keeps the same 5-minute
OHLC execution model and fee policy, adds the newly downloaded Bitget bars, and
records sliced annual metrics without leaking full-sample funding totals into
each annual row.
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


REBATE = 0.60
BASE_TAKER = 6.0
BASE_MAKER = 2.0
START = pd.Timestamp("2020-01-01", tz="UTC")
END = pd.Timestamp("2026-10-07", tz="UTC")
NAMES = ["V4.1.2", "V4.5.3", "V7.1.2"]


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
        part = raw.loc[month == key].rename(columns={"trade_base_volume": "trade_volume"})
        yield part[["trade_open", "trade_high", "trade_low", "trade_close", "trade_volume",
                    "trade_quote_volume", "mark_open", "mark_high", "mark_low", "mark_close"]]


def build_signals(hourly: pd.DataFrame, four: pd.DataFrame):
    p412 = V43Params(**json.loads((ROOT / "configs/v4_1_2_params.json").read_text()))
    p453 = V453Params(**json.loads((ROOT / "configs/v4_5_3_params.json").read_text())["signal_params"])
    p712 = V712Params(**json.loads((ROOT / "configs/v712_params.json").read_text()))
    return {
        "V4.1.2": _direction_cycles(generate_v43_signals(four, p412)),
        "V4.5.3": generate_v453_signals(hourly, p453),
        "V7.1.2": generate_v712_signals(four, p712),
    }


def config(name: str, taker_mult: float = 1.0, maker_mult: float = 1.0, slip_mult: float = 1.0) -> MicroBacktestConfig:
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


def _slice_frame(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, time_col: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    ts = pd.to_datetime(frame[time_col], utc=True)
    return frame.loc[(ts >= start) & (ts < end)]


def metrics(equity: pd.Series, result, start=START, end=END):
    e = equity.loc[(equity.index >= start) & (equity.index < end)].dropna()
    daily = e.resample("1D", closed="right", label="right").last().dropna()
    ret = daily.pct_change().dropna()
    years = max((e.index[-1] - e.index[0]).total_seconds() / (365.25 * 86400), 1 / 365.25)
    sd = ret.std(ddof=1)
    trades = _slice_frame(result.trades, start, end, "exit_time")
    fills = _slice_frame(result.fills, start, end, "timestamp")
    funding = _slice_frame(result.funding, start, end, "timestamp")
    wins = trades.pnl > 0 if not trades.empty else pd.Series(dtype=bool)
    return {
        "initial_equity": float(e.iloc[0]), "final_equity": float(e.iloc[-1]),
        "total_return": float(e.iloc[-1] / e.iloc[0] - 1),
        "cagr": float((e.iloc[-1] / e.iloc[0]) ** (1 / years) - 1),
        "sharpe": float(ret.mean() / sd * np.sqrt(365.25)) if sd > 0 else 0.0,
        "sortino": float(ret.mean() / ret[ret < 0].std(ddof=1) * np.sqrt(365.25)) if (ret < 0).sum() > 2 and ret[ret < 0].std(ddof=1) > 0 else 0.0,
        "annualized_volatility": float(sd * np.sqrt(365.25)) if pd.notna(sd) else 0.0,
        "max_drawdown": float((e / e.cummax() - 1).min()),
        "days": int(len(ret)), "trades": int(len(trades)),
        "long_trades": int((trades.side == "long").sum()) if not trades.empty else 0,
        "short_trades": int((trades.side == "short").sum()) if not trades.empty else 0,
        "win_rate": float(wins.mean()) if len(wins) else 0.0,
        "median_holding_hours": float((trades.exit_time - trades.entry_time).dt.total_seconds().median() / 3600) if len(trades) else 0.0,
        "fills": int(len(fills)), "maker_fills": int((fills.liquidity == "maker").sum()) if len(fills) else 0,
        "taker_fills": int((fills.liquidity == "taker").sum()) if len(fills) else 0,
        "maker_fill_share": float((fills.liquidity == "maker").mean()) if len(fills) else 0.0,
        "turnover_usdt": float(fills.notional.sum()) if len(fills) else 0.0,
        "fees_usdt": float(fills.fee.sum()) if len(fills) else 0.0,
        "funding_paid_usdt": float(funding.payment.sum()) if len(funding) and "payment" in funding else 0.0,
        "liquidations": int(len(_slice_frame(result.liquidations, start, end, "timestamp"))),
    }


def run_case(name, signals, raw, funding, out_dir, scenario="base", taker_mult=1.0, maker_mult=1.0, slip_mult=1.0, funding_mult=1.0):
    cfg = config(name, taker_mult, maker_mult, slip_mult)
    case_funding = funding.copy()
    if funding_mult != 1.0 and not case_funding.empty:
        case_funding["funding_rate"] = case_funding["funding_rate"] * funding_mult
    result = run_micro_backtest(signals[name], batches(raw), case_funding, cfg)
    dest = out_dir / name / scenario
    dest.mkdir(parents=True, exist_ok=True)
    result.equity.to_csv(dest / "equity.csv", header=True)
    result.fills.to_csv(dest / "fills.csv", index=False)
    result.trades.to_csv(dest / "trades.csv", index=False)
    result.funding.to_csv(dest / "funding.csv", index=False)
    result.liquidations.to_csv(dest / "liquidations.csv", index=False)
    periods = {}
    for label, start in [("full", START), ("post2024", pd.Timestamp("2024-01-01", tz="UTC")), ("post2025", pd.Timestamp("2025-01-01", tz="UTC")), ("2026_to_cutoff", pd.Timestamp("2026-01-01", tz="UTC"))]:
        periods[label] = metrics(result.equity, result, start, END)
    payload = {"strategy": name, "scenario": scenario, "execution": asdict(cfg), "metrics": periods["full"], "periods": periods}
    (dest / "report.json").write_text(json.dumps(payload, indent=2, default=float))
    return payload, result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=ROOT / "data/bitget_20261006")
    ap.add_argument("--output", type=Path, default=ROOT / "reports/bitget_three_latest_60")
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    raw, hourly, four, funding = load_data(args.data)
    signals = build_signals(hourly, four)
    rows = []
    results = {}
    cases = [("base", 1.0, 1.0, 1.0, 1.0), ("fees_plus_50pct", 1.5, 1.5, 1.0, 1.0), ("slippage_double", 1.0, 1.0, 2.0, 1.0), ("funding_2x", 1.0, 1.0, 1.0, 2.0), ("no_funding", 1.0, 1.0, 1.0, 0.0)]
    for name in NAMES:
        for scenario, tm, mm, sm, fm in cases:
            payload, result = run_case(name, signals, raw, funding, args.output, scenario, tm, mm, sm, fm)
            rows.append(payload)
            if scenario == "base":
                results[name] = result
    eq = pd.DataFrame({name: result.equity for name, result in results.items()})
    eq.to_csv(args.output / "equity_curves.csv")
    daily = eq.resample("1D").last().dropna(how="all")
    (daily / daily.cummax() - 1).to_csv(args.output / "drawdowns.csv")
    summary = pd.DataFrame([{**r["metrics"], "strategy": r["strategy"], "scenario": r["scenario"]} for r in rows])
    summary.to_csv(args.output / "summary_metrics.csv", index=False)
    period_rows = [{"strategy": r["strategy"], "scenario": r["scenario"], "period": k, **v} for r in rows for k, v in r["periods"].items()]
    pd.DataFrame(period_rows).to_csv(args.output / "period_metrics.csv", index=False)
    manifest = json.loads((args.data / "manifest.json").read_text())
    raw_digest = hashlib.sha256(pd.util.hash_pandas_object(raw, index=True).values.tobytes()).hexdigest()
    protocol = {
        "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "report_scope": {"requested_start": START.isoformat(), "requested_end_exclusive": END.isoformat(), "as_of_date": "2026-10-06", "observed_last_candle": raw.index.max().isoformat()},
        "data_manifest": manifest, "strategies": NAMES,
        "fee_policy": {"published_taker_bps": BASE_TAKER, "published_maker_bps": BASE_MAKER, "rebate_fraction": REBATE, "effective_taker_bps": BASE_TAKER * (1 - REBATE), "effective_maker_bps": BASE_MAKER * (1 - REBATE)},
        "execution": "5m OHLC execution and mark-price proxy; routine exposure may use maker-touch model; protective exits use taker; deterministic impact/slippage; 2% per-bar participation cap.",
        "funding": "Only public Bitget funding records in local cache are applied; earlier missing settlements are not fabricated.",
        "parameter_search": False, "data_sha256": raw_digest,
        "coverage": {"five_minute_rows": len(raw), "missing_rows": 0, "funding_rows": len(funding), "funding_start": funding.index.min().isoformat() if len(funding) else None, "funding_end": funding.index.max().isoformat() if len(funding) else None},
        "limits": ["Public funding endpoint does not provide the full 2020-2026 funding history; the backtest uses only the observed 2026-06-27 to 2026-10-06 settlements.", "Five-minute OHLC is coarser than tick/order-book replay; maker queue priority is unobserved.", "Maintenance-margin brackets and impact are deterministic assumptions; no liquidation occurred in the base runs.", "The data were available during research and are not a blind out-of-sample test."],
    }
    (args.output / "protocol.json").write_text(json.dumps(protocol, indent=2, ensure_ascii=False))
    print(summary.loc[summary.scenario.eq("base"), ["strategy", "total_return", "cagr", "sharpe", "max_drawdown", "trades", "fills", "liquidations"]].to_string(index=False))


if __name__ == "__main__":
    main()
