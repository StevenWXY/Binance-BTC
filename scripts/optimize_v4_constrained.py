#!/usr/bin/env python3
"""Constrained local refinement of V4 around the frozen baseline."""

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
from btc_regime.data import load_market_data  # noqa: E402
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402


BASE_PATH = ROOT / "configs/aggressive_adaptive_v3_params.json"
OUT = ROOT / "reports/v4_constrained_optimization.csv"
SUMMARY = ROOT / "reports/v4_constrained_optimization.json"


def metrics(signaled: pd.DataFrame, start: str, end: str) -> dict[str, float]:
    window = signaled.loc[
        (signaled.index >= pd.Timestamp(start, tz="UTC"))
        & (signaled.index < pd.Timestamp(end, tz="UTC"))
    ]
    return run_backtest(window, BacktestConfig()).metrics


def evaluate(data: pd.DataFrame, p: StrategyParams) -> dict[str, float | int | bool]:
    signaled = generate_signals(data, p)
    train = metrics(signaled, "2020-01-01", "2023-01-01")
    validation = metrics(signaled, "2023-01-01", "2025-01-01")
    pre = metrics(signaled, "2020-01-01", "2025-01-01")
    holdout = metrics(signaled, "2025-01-01", "2026-08-01")
    # Reward the weaker pre-holdout half, with a mild turnover penalty.
    robust = (
        0.45 * min(train["sharpe"], validation["sharpe"])
        + 0.25 * ((train["sharpe"] + validation["sharpe"]) / 2)
        + 0.20 * min(pre["cagr"], 2.0)
        + 0.10 * min(pre["sortino"], 4.0)
        - 0.0002 * pre["turnover_multiple"]
    )
    row = p.to_dict()
    row.update({"robust_score": robust})
    for label, values in (("train", train), ("validation", validation), ("pre", pre), ("holdout", holdout)):
        for key, value in values.items():
            row[f"{label}_{key}"] = value
    return row


def main() -> None:
    base = StrategyParams(**json.loads(BASE_PATH.read_text(encoding="utf-8")))
    data = load_market_data(ROOT / "data/raw", start="2020-01-01", end="2026-08-01")
    dimensions = {
        "adx_enter": [26.0, 27.0, 28.0],
        "trend_separation_atr": [0.05, 0.10, 0.15],
        "rebalance_bars": [48, 60, 72],
        "funding_factor_scale": [0.30, 0.35, 0.40],
        "downside_stress_scale": [0.20, 0.25, 0.30],
    }
    candidates = [base]
    for values in product(*dimensions.values()):
        candidates.append(replace(base, **dict(zip(dimensions, values))))
    # Deduplicate because baseline is included in the grid.
    unique = {tuple(p.to_dict().items()): p for p in candidates}
    rows = [evaluate(data, p) for p in unique.values()]
    table = pd.DataFrame(rows)
    base_row = table.loc[
        (table["adx_enter"] == base.adx_enter)
        & (table["trend_separation_atr"] == base.trend_separation_atr)
        & (table["rebalance_bars"] == base.rebalance_bars)
        & (table["funding_factor_scale"] == base.funding_factor_scale)
        & (table["downside_stress_scale"] == base.downside_stress_scale)
    ].iloc[0]
    # These constraints encode "slightly better, same drawdown": no more than
    # one percentage point worse pre-holdout drawdown and no weaker pre Sharpe.
    feasible = table.loc[
        (table["pre_sharpe"] >= base_row["pre_sharpe"])
        & (table["pre_cagr"] >= base_row["pre_cagr"])
        & (table["pre_max_drawdown"] >= base_row["pre_max_drawdown"] - 0.01)
        & (table["train_sharpe"] >= base_row["train_sharpe"] - 0.03)
        & (table["validation_sharpe"] >= base_row["validation_sharpe"] - 0.03)
    ]
    selected = feasible.sort_values(
        ["robust_score", "pre_sharpe", "pre_cagr"], ascending=False
    ).iloc[0] if not feasible.empty else table.sort_values("robust_score", ascending=False).iloc[0]
    table = table.sort_values("robust_score", ascending=False).reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT, index=False)
    summary = {
        "baseline": {k: float(base_row[k]) for k in ("pre_cagr", "pre_sharpe", "pre_sortino", "pre_max_drawdown", "holdout_cagr", "holdout_sharpe", "holdout_max_drawdown")},
        "selected": {k: float(selected[k]) for k in ("pre_cagr", "pre_sharpe", "pre_sortino", "pre_max_drawdown", "holdout_cagr", "holdout_sharpe", "holdout_max_drawdown", "robust_score")},
        "selected_parameters": {
            name: (int(selected[name]) if name == "rebalance_bars" else float(selected[name]))
            for name in dimensions
        },
        "candidate_count": len(table),
        "feasible_count": len(feasible),
        "constraints": {"pre_drawdown_tolerance": 0.01, "pre_sharpe_floor": "baseline", "pre_cagr_floor": "baseline"},
    }
    SUMMARY.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
