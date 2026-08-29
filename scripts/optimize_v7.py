#!/usr/bin/env python3
"""Focused constrained search for V7 risk and range parameters."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from itertools import product
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from btc_regime.backtest import BacktestConfig, run_backtest  # noqa: E402
from btc_regime.v7 import V7Params, generate_v7_signals  # noqa: E402
from render_global_curve_v1_v7 import load_market  # noqa: E402


OUT = ROOT / "reports/global_curve_v1_v7_2020_2026_08_25/v7_optimization.csv"


def score(metrics: dict[str, float]) -> float:
    drawdown = abs(metrics["max_drawdown"])
    if drawdown > 0.36:
        return -999.0 + metrics["sharpe"]
    return metrics["sharpe"] + 0.25 * metrics["cagr"] - 0.75 * drawdown


def main() -> None:
    market = load_market()
    base = V7Params(**json.loads((ROOT / "configs/v7_params.json").read_text(encoding="utf-8")))
    config = BacktestConfig(initial_cash=10_000.0, fee_bps=4.0, slippage_bps=1.0)
    rows: list[dict[str, float | int | bool]] = []
    grid = product(
        [0.15, 0.25, 0.35],
        [0.15, 0.20, 0.25],
        [0.75, 0.78, 0.84],
        [0.45, 0.55],
        [0.25, 0.35],
    )
    for (
        rebound_scale,
        range_entry,
        range_exit,
        rapid_scale,
        adverse_scale,
    ) in grid:
        if range_entry >= range_exit:
            continue
        params = replace(
            base,
            target_vol=1.075,
            max_leverage=6.5,
            trend_scale=1.25,
            allow_short=True,
            rebound_scale=rebound_scale,
            range_entry_percentile=range_entry,
            range_exit_percentile=range_exit,
            rapid_deceleration_scale=rapid_scale,
            adverse_shock_scale=adverse_scale,
        )
        frame = generate_v7_signals(market, params)
        frame.index = frame.index + pd.Timedelta(hours=4)
        result = run_backtest(frame, config)
        rows.append({
            "score": score(result.metrics),
            "target_vol": 1.075,
            "max_leverage": 6.5,
            "trend_scale": 1.25,
            "allow_short": True,
            "rebound_scale": rebound_scale,
            "range_entry_percentile": range_entry,
            "range_exit_percentile": range_exit,
            "rapid_deceleration_scale": rapid_scale,
            "adverse_shock_scale": adverse_scale,
            **result.metrics,
        })
    table = pd.DataFrame(rows).sort_values(
        ["score", "sharpe", "cagr"],
        ascending=[False, False, False],
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT, index=False)
    print(table.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
