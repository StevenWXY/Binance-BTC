"""Audit V4.5.3 on the current Bitget cache through 2026-10-11.

The script keeps the frozen V4.5.3 signal and varies only execution assumptions
or one-at-a-time nearby V4.5.2 signal choices.  It writes auditable CSV/JSON
artifacts under reports/v4_5_3_current_audit.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v452 import V452Params, generate_v452_signals
from btc_regime.v453 import V453Params, generate_v453_signals
import run_bitget_three_latest as latest


DATA = ROOT / "data/bitget_20261011"
OUT = ROOT / "reports/v4_5_3_current_audit"
START = pd.Timestamp("2026-09-01", tz="UTC")
END = pd.Timestamp("2026-10-11 08:00", tz="UTC")


def period_metrics(result) -> dict[str, float | int]:
    e = result.equity.loc[(result.equity.index >= START) & (result.equity.index <= END)].dropna()
    daily = e.resample("1D", closed="right", label="right").last().dropna()
    ret = daily.pct_change().dropna()
    trades = result.trades.copy()
    if not trades.empty:
        trades["entry_time"] = pd.to_datetime(trades.entry_time, utc=True)
        trades["exit_time"] = pd.to_datetime(trades.exit_time, utc=True)
        trades = trades.loc[(trades.exit_time >= START) & (trades.exit_time < END)]
    fills = result.fills.copy()
    if not fills.empty:
        fills["timestamp"] = pd.to_datetime(fills.timestamp, utc=True)
        fills = fills.loc[(fills.timestamp >= START) & (fills.timestamp < END)]
    years = max((e.index[-1] - e.index[0]).total_seconds() / (365.25 * 86400), 1 / 365.25)
    sd = ret.std(ddof=1)
    hold = ((trades.exit_time - trades.entry_time).dt.total_seconds() / 3600) if len(trades) else pd.Series(dtype=float)
    return {
        "period_start_equity": float(e.iloc[0]), "period_end_equity": float(e.iloc[-1]),
        "total_return": float(e.iloc[-1] / e.iloc[0] - 1),
        "cagr": float((e.iloc[-1] / e.iloc[0]) ** (1 / years) - 1),
        "sharpe": float(ret.mean() / sd * np.sqrt(365.25)) if sd > 0 else 0.0,
        "max_drawdown": float((e / e.cummax() - 1).min()),
        "trades": int(len(trades)), "wins": int((trades.pnl > 0).sum()),
        "losses": int((trades.pnl <= 0).sum()), "pnl_sum": float(trades.pnl.sum()) if len(trades) else 0.0,
        "win_rate": float((trades.pnl > 0).mean()) if len(trades) else 0.0,
        "median_holding_hours": float(hold.median()) if len(hold) else 0.0,
        "fills": int(len(fills)), "maker_fills": int((fills.liquidity == "maker").sum()) if len(fills) else 0,
        "taker_fills": int((fills.liquidity == "taker").sum()) if len(fills) else 0,
        "fees": float(fills.fee.sum()) if len(fills) else 0.0,
        "funding": float(result.funding.loc[(pd.to_datetime(result.funding.timestamp, utc=True) >= START) & (pd.to_datetime(result.funding.timestamp, utc=True) < END), "payment"].sum()) if not result.funding.empty else 0.0,
    }


def base_config() -> MicroBacktestConfig:
    return latest.config("V4.5.3")


def run_one(name, signal, raw, funding, cfg):
    result = run_micro_backtest(signal, latest.batches(raw), funding, cfg)
    out = period_metrics(result)
    out.update({"scenario": name, "final_equity_full": float(result.equity.iloc[-1]),
                "full_return": float(result.metrics["total_return"]),
                "full_sharpe": float(result.metrics.get("sharpe", 0.0)),
                "full_max_drawdown": float(result.metrics["max_drawdown"])})
    return out, result


def cycle_table(result) -> pd.DataFrame:
    t = result.trades.copy()
    t["entry_time"] = pd.to_datetime(t.entry_time, utc=True)
    t["exit_time"] = pd.to_datetime(t.exit_time, utc=True)
    t = t.loc[(t.exit_time >= START) & (t.exit_time < END)].copy()
    t["holding_hours"] = (t.exit_time - t.entry_time).dt.total_seconds() / 3600
    t["trade_return"] = t.pnl / t.equity_before
    return t[["entry_time", "side", "exit_time", "holding_hours", "equity_before", "pnl", "trade_return", "exit_reason", "equity_at_trigger"]]


def main() -> None:
    latest.END = END
    raw, hourly, _, funding = latest.load_data(DATA)
    params = V453Params(**json.loads((ROOT / "configs/v4_5_3_params.json").read_text())["signal_params"])
    signal = generate_v453_signals(hourly, params)
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = base_config()
    cases = [
        ("base_maker_0bps", signal, cfg),
        ("all_taker", signal, replace(cfg, maker_enabled=False)),
        ("maker_offset_025bps", signal, replace(cfg, maker_offset_bps=.25)),
        ("maker_offset_05bps", signal, replace(cfg, maker_offset_bps=.5)),
        ("fees_plus_50pct", signal, replace(cfg, taker_fee_bps=cfg.taker_fee_bps * 1.5, maker_fee_bps=cfg.maker_fee_bps * 1.5)),
        ("slippage_double", signal, replace(cfg, base_slippage_bps=2., impact_bps=16.)),
        ("signal_delay_1h", signal.copy(), cfg),
    ]
    cases[-1][1].index = cases[-1][1].index + pd.Timedelta(hours=1)
    rows, results = [], {}
    for name, sig, case_cfg in cases:
        row, result = run_one(name, sig, raw, funding, case_cfg)
        rows.append(row); results[name] = result
    pd.DataFrame(rows).to_csv(OUT / "execution_sensitivity.csv", index=False)
    cycle_table(results["base_maker_0bps"]).to_csv(OUT / "trades_2026-09-01_2026-10-11.csv", index=False)

    profile_params = {
        "b022": params,
        "b023_cooldown6": replace(params, cooldown_hours=6),
        "break12": replace(params, entry="break12"),
        "break24": replace(params, entry="break24"),
        "adx28": replace(params, adx_min=28.),
        "confirmation_none": replace(params, confirmation="none"),
        "confirmation_strength": replace(params, confirmation="strength"),
        "gate_hybrid": replace(params, gate="hybrid"),
        "protection_tight": replace(params, protection="tight"),
        "risk_base": replace(params, risk="base"),
    }
    profile_rows = []
    for name, p in profile_params.items():
        sig = generate_v453_signals(hourly, p)
        row, _ = run_one(name, sig, raw, funding, cfg)
        profile_rows.append(row)
    pd.DataFrame(profile_rows).to_csv(OUT / "signal_neighborhood.csv", index=False)
    payload = {
        "data": {"directory": str(DATA), "observed_end": raw.index.max().isoformat(), "five_minute_rows": len(raw),
                 "funding_start": funding.index.min().isoformat(), "funding_end": funding.index.max().isoformat(), "funding_rows": len(funding)},
        "window": [START.isoformat(), END.isoformat()], "signal_params": params.__dict__,
        "selection_evidence": {"winner": "b022", "selectable_profiles": 8, "next_score_gap": 0.0254163517,
                                "selection_file": "reports/v4_5_2/minute_selection.json"},
        "notes": ["V4.5.3 signal is exactly V4.5.2 b022; only routine execution adds Maker.",
                  "Maker fills are an OHLC touch proxy and cannot model queue priority.",
                  "The complete historical cache was available during research; the current window is not a blind OOS test.",
                  "The last available candle is 2026-10-11 07:55 UTC (15:55 Asia/Shanghai); no later candles are fabricated."],
    }
    (OUT / "audit.json").write_text(json.dumps(payload, indent=2, default=str, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
