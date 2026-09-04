#!/usr/bin/env python3
"""Validate a V7 candidate on parameter neighbors and separate time periods."""

from __future__ import annotations

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


def main() -> None:
    base_path = Path(sys.argv[1])
    market_path = Path(sys.argv[2])
    output = Path(sys.argv[3])
    market = pd.read_csv(market_path, index_col=0, parse_dates=True)
    market.index = pd.to_datetime(market.index, utc=True, format="mixed")
    base = V7Params(**json.loads(base_path.read_text(encoding="utf-8-sig")))
    config = BacktestConfig(initial_cash=10_000.0, fee_bps=4.0, slippage_bps=1.0)
    candidates = product(
        [0.92, 0.97, 1.02],
        [0.10, 0.15, 0.20],
        [1.8, 2.0, 2.2],
        [0.15, 0.20, 0.25],
    )
    rows = []
    periods = {
        "train_2020_2022": ("2020-01-01", "2023-01-01"),
        "validation_2023_2024": ("2023-01-01", "2025-01-01"),
        "holdout_2025_2026_07": ("2025-01-01", "2026-08-01"),
        "full": ("2020-01-01", "2026-08-01"),
    }
    for target_vol, short_scale, stop_atr, buffer_atr in candidates:
        params = replace(
            base,
            target_vol=target_vol,
            short_scale=short_scale,
            trend_trailing_stop_atr=stop_atr,
            breakout_buffer_atr=buffer_atr,
        )
        frame = generate_v7_signals(market, params)
        frame.index = frame.index + pd.Timedelta(hours=4)
        for label, (start, end) in periods.items():
            sample = frame.loc[(frame.index >= pd.Timestamp(start, tz="UTC")) & (frame.index < pd.Timestamp(end, tz="UTC"))]
            result = run_backtest(sample, config)
            rows.append({
                "target_vol": target_vol,
                "short_scale": short_scale,
                "trend_trailing_stop_atr": stop_atr,
                "breakout_buffer_atr": buffer_atr,
                "period": label,
                **result.metrics,
            })
    table = pd.DataFrame(rows)
    full = table.loc[table["period"] == "full"].copy()
    pivot = table.pivot(index=["target_vol", "short_scale", "trend_trailing_stop_atr", "breakout_buffer_atr"], columns="period", values="sharpe")
    full = full.set_index(["target_vol", "short_scale", "trend_trailing_stop_atr", "breakout_buffer_atr"])
    full["minimum_period_sharpe"] = pivot[["train_2020_2022", "validation_2023_2024", "holdout_2025_2026_07"]].min(axis=1)
    full["calmar"] = full["cagr"] / full["max_drawdown"].abs()
    full = full.sort_values(["minimum_period_sharpe", "calmar", "final_equity"], ascending=False).reset_index()
    output.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(output.with_name(output.stem + "_periods.csv"), index=False)
    full.to_csv(output, index=False)
    print(full.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
