#!/usr/bin/env python3
"""Constrained V7 risk search based on the historical profit-focused baseline."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from itertools import product
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.backtest import BacktestConfig, run_backtest  # noqa: E402
from btc_regime.v7 import V7Params, generate_v7_signals  # noqa: E402


def load_market(path: Path, start: str, end: str) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index, utc=True, format="mixed")
    return frame.loc[(frame.index >= pd.Timestamp(start, tz="UTC")) & (frame.index < pd.Timestamp(end, tz="UTC"))]


def score(metrics: dict[str, float], baseline: dict[str, float]) -> float:
    dd = abs(metrics["max_drawdown"])
    improvement = abs(baseline["max_drawdown"]) - dd
    retention = metrics["final_equity"] / baseline["final_equity"]
    if dd > 0.36 or retention < 0.80:
        return -100.0
    return 2.0 * improvement + 0.35 * metrics["sharpe"] + 0.20 * retention


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--market", type=Path, default=ROOT / "reports/annual_2020_2026_08_25/market_4h_full.csv")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/v7_risk_round4_4h.csv")
    args = parser.parse_args()

    market = load_market(args.market, args.start, args.end)
    base = V7Params(**json.loads(args.base.read_text(encoding="utf-8-sig")))
    config = BacktestConfig(initial_cash=10_000.0, fee_bps=4.0, slippage_bps=1.0)
    baseline_result = run_backtest(generate_v7_signals(market, base), config)
    baseline = baseline_result.metrics
    rows: list[dict[str, object]] = []
    grid = product(
        [0.87, 0.92, 0.97],
        [0.15, 0.20, 0.30],
        [2.0, 2.4, 2.8],
        [4, 5, 6],
        [0.0, 0.1, 0.2],
        [False, True],
    )
    for target_vol, short_scale, stop_atr, exit_confirm, breakout_buffer_atr, adverse_exit_enabled in grid:
        params = replace(
            base,
            target_vol=target_vol,
            short_scale=short_scale,
            trend_trailing_stop_atr=stop_atr,
            trend_confirm_bars=base.trend_confirm_bars,
            trend_exit_confirm_bars=exit_confirm,
            breakout_buffer_atr=breakout_buffer_atr,
            adverse_exit_enabled=adverse_exit_enabled,
            price_drawdown_enter=base.price_drawdown_enter,
            price_drawdown_scale=base.price_drawdown_scale,
        )
        result = run_backtest(generate_v7_signals(market, params), config)
        rows.append({
            "score": score(result.metrics, baseline),
            "target_vol": target_vol,
            "short_scale": short_scale,
            "trend_trailing_stop_atr": stop_atr,
            "trend_confirm_bars": base.trend_confirm_bars,
            "trend_exit_confirm_bars": exit_confirm,
            "breakout_buffer_atr": breakout_buffer_atr,
            "adverse_exit_enabled": adverse_exit_enabled,
            "price_drawdown_enter": base.price_drawdown_enter,
            "price_drawdown_scale": base.price_drawdown_scale,
            **result.metrics,
        })
    table = pd.DataFrame(rows).sort_values(["score", "final_equity"], ascending=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.output, index=False)
    print("baseline", json.dumps(baseline, ensure_ascii=False))
    print(table.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
