"""Detailed calendar-year 2026 report for the frozen V4.5.3 replay."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from btc_regime.v453 import V453Params, generate_v453_signals
from btc_regime.micro_backtest import run_micro_backtest
import run_bitget_three_latest as latest


DATA = ROOT / "data/bitget_20261011"
OUT = ROOT / "reports/v4_5_3_2026"
YEAR_START = pd.Timestamp("2026-01-01", tz="UTC")


def signal_target_at(signals: pd.DataFrame, timestamp: pd.Timestamp, interval_minutes: int) -> float:
    source_time = timestamp - pd.Timedelta(minutes=interval_minutes)
    if source_time in signals.index:
        return float(abs(signals.loc[source_time, "signal"]))
    prior = signals.loc[signals.index <= source_time, "signal"]
    return float(abs(prior.iloc[-1])) if len(prior) else 0.0


def enrich_trades(result, signals, cfg, cutoff: pd.Timestamp) -> pd.DataFrame:
    trades = result.trades.copy()
    fills = result.fills.copy()
    funding = result.funding.copy()
    if trades.empty:
        return pd.DataFrame()
    for frame, col in ((trades, "entry_time"), (trades, "exit_time"), (fills, "timestamp"), (funding, "timestamp")):
        if col in frame:
            frame[col] = pd.to_datetime(frame[col], utc=True)
    eq = result.equity.sort_index()
    rows = []
    for trade_id, trade in trades.reset_index(drop=True).iterrows():
        entry = pd.Timestamp(trade.entry_time)
        exit_ = pd.Timestamp(trade.exit_time)
        tf = fills.loc[(fills.timestamp >= entry) & (fills.timestamp <= exit_)].copy()
        entry_fills = tf.loc[tf.timestamp == entry]
        if entry_fills.empty:
            entry_fills = tf.head(1)
        exit_fills = tf.loc[tf.timestamp == exit_]
        if exit_fills.empty:
            exit_fills = tf.tail(1)
        entry_notional = float(entry_fills.notional.abs().sum()) if len(entry_fills) else np.nan
        exit_notional = float(exit_fills.notional.abs().sum()) if len(exit_fills) else np.nan
        entry_qty = float(entry_fills.quantity.abs().sum()) if len(entry_fills) else np.nan
        exit_qty = float(exit_fills.quantity.abs().sum()) if len(exit_fills) else np.nan
        entry_price = float((entry_fills.price * entry_fills.quantity.abs()).sum() / entry_qty) if entry_qty else np.nan
        exit_price = float((exit_fills.price * exit_fills.quantity.abs()).sum() / exit_qty) if exit_qty else np.nan
        costs = tf.loc[tf.reason.isin(["signal", "stop_loss", "take_profit", "final_close", "liquidation"])]
        fees = float(costs.fee.sum()) if len(costs) else 0.0
        ffunding = funding.loc[(funding.timestamp >= entry) & (funding.timestamp <= exit_)]
        funding_paid = float(ffunding.payment.sum()) if len(ffunding) else 0.0
        # Use the latest recorded equity point at each fill to estimate realized
        # notional/equity leverage. The target multiple is exact from the signal.
        if len(tf):
            # Reporting only: use the last equity observation already known at
            # each fill.  Do not backfill from a later equity point, even for
            # the first record, so the audit metadata cannot introduce a
            # future-value dependency.
            at = eq.reindex(tf.timestamp, method="ffill").to_numpy()
            lev = (tf.position_after.abs() * tf.price / np.maximum(at, 1e-12)).replace([np.inf, -np.inf], np.nan)
            max_lev = float(np.nanmax(lev)) if len(lev) else np.nan
        else:
            max_lev = np.nan
        entry_actual_lev = entry_notional / float(trade.equity_before) if entry_notional else np.nan
        rows.append({
            "trade_id": trade_id + 1,
            "entry_time_utc": entry,
            "exit_time_utc": exit_,
            "entry_time_bjt": entry.tz_convert("Asia/Shanghai"),
            "exit_time_bjt": exit_.tz_convert("Asia/Shanghai"),
            "direction": trade.side,
            "holding_hours": (exit_ - entry).total_seconds() / 3600,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "entry_quantity_btc": entry_qty,
            "exit_quantity_btc": exit_qty,
            "entry_notional_usdt": entry_notional,
            "exit_notional_usdt": exit_notional,
            "equity_before_usdt": float(trade.equity_before),
            "initial_fill_multiple_x": entry_actual_lev,
            "target_contract_multiple_x": signal_target_at(signals, entry, cfg.signal_interval_minutes),
            "max_observed_multiple_x": max_lev,
            "pnl_usdt": float(trade.pnl),
            "return_pct": float(trade.pnl / float(trade.equity_before) * 100),
            "fees_usdt": fees,
            "funding_usdt": funding_paid,
            "exit_reason": str(trade.exit_reason),
            "result": "win" if trade.pnl > 0 else "loss",
        })
    out = pd.DataFrame(rows)
    return out.loc[out.entry_time_utc >= YEAR_START].sort_values("entry_time_utc").reset_index(drop=True)


def main() -> None:
    # The local cache is complete through its last 5-minute candle. Use that
    # exact boundary so no future candle is invented.
    cached = pd.read_pickle(DATA / "candles_5m.pkl")
    cached.index = pd.to_datetime(cached.index, utc=True)
    cutoff = cached.index.max() + pd.Timedelta(minutes=5)
    latest.END = cutoff
    raw, hourly, _, funding = latest.load_data(DATA)
    signals = generate_v453_signals(hourly, V453Params(**json.loads((ROOT / "configs/v4_5_3_params.json").read_text())["signal_params"]))
    cfg = latest.config("V4.5.3")
    year_raw = raw.loc[raw.index >= YEAR_START]
    year_funding = funding.loc[funding.index >= YEAR_START]
    result = run_micro_backtest(signals, latest.batches(year_raw), year_funding, cfg)
    trades = enrich_trades(result, signals, cfg, cutoff)
    OUT.mkdir(parents=True, exist_ok=True)
    trades.to_csv(OUT / "trades_2026_detailed.csv", index=False)
    result.fills.assign(timestamp_bjt=pd.to_datetime(result.fills.timestamp, utc=True).dt.tz_convert("Asia/Shanghai")).to_csv(OUT / "fills_2026.csv", index=False)
    result.funding.assign(timestamp_bjt=pd.to_datetime(result.funding.timestamp, utc=True).dt.tz_convert("Asia/Shanghai")).to_csv(OUT / "funding_2026.csv", index=False)
    result.equity.to_csv(OUT / "equity_2026.csv", header=True)
    daily = result.equity.resample("1D").last().dropna()
    daily.to_csv(OUT / "daily_equity_2026.csv", header=True)
    monthly = pd.DataFrame({"equity": daily}).resample("MS").agg(["first", "last"])
    monthly["return"] = monthly[("equity", "last")] / monthly[("equity", "first")] - 1
    monthly.to_csv(OUT / "monthly_equity_2026.csv")
    by_direction = trades.groupby("direction", dropna=False).agg(
        trades=("trade_id", "count"), wins=("result", lambda x: int((x == "win").sum())),
        pnl_usdt=("pnl_usdt", "sum"), avg_return_pct=("return_pct", "mean"),
        fees_usdt=("fees_usdt", "sum"), funding_usdt=("funding_usdt", "sum"),
        avg_holding_hours=("holding_hours", "mean"), max_multiple_x=("max_observed_multiple_x", "max"),
    ).reset_index()
    by_direction.to_csv(OUT / "direction_summary_2026.csv", index=False)
    payload = {
        "strategy": "V4.5.3",
        "initial_cash_usdt": cfg.initial_cash,
        "requested_start": YEAR_START.isoformat(),
        "observed_end_exclusive": cutoff.isoformat(),
        "observed_last_candle": raw.index.max().isoformat(),
        "timezone_display": "Asia/Shanghai; raw timestamps also retained in UTC",
        "signal_params": json.loads((ROOT / "configs/v4_5_3_params.json").read_text())["signal_params"],
        "execution": asdict(cfg),
        "metrics": result.metrics,
        "trade_count": int(len(trades)),
        "win_count": int((trades.result == "win").sum()),
        "loss_count": int((trades.result == "loss").sum()),
        "total_pnl_usdt": float(trades.pnl_usdt.sum()) if len(trades) else 0.0,
        "total_fees_usdt": float(result.fills.fee.sum()) if len(result.fills) else 0.0,
        "total_funding_usdt": float(result.funding.payment.sum()) if len(result.funding) else 0.0,
        "liquidations": int(len(result.liquidations)),
        "notes": [
            "Account is flat and reset to 10,000 USDT at 2026-01-01.",
            "Signals use prior hourly history for indicator warm-up; no pre-2026 position is carried into the account.",
            "The last available candle is 2026-10-11 07:55 UTC / 15:55 Asia/Shanghai; no later data are fabricated.",
            "Funding before 2026-06-27 is absent from the local public-cache data and is not fabricated.",
            "Maker fills are a 5-minute OHLC-touch proxy and do not model queue priority.",
        ],
    }
    (OUT / "metrics_2026.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")
    print(json.dumps({k: payload[k] for k in ["observed_last_candle", "metrics", "trade_count", "win_count", "loss_count", "total_pnl_usdt", "total_fees_usdt", "total_funding_usdt", "liquidations"]}, indent=2, default=str))
    print(trades.to_string(index=False))


if __name__ == "__main__":
    main()
