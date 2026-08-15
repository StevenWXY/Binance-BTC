#!/usr/bin/env python3
"""Select a coarse, stable V3 configuration without using post-2024 data."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.backtest import BacktestConfig, run_backtest  # noqa: E402
from btc_regime.data import load_market_data  # noqa: E402
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402


SELECTION_START = pd.Timestamp("2020-01-01", tz="UTC")
SELECTION_END = pd.Timestamp("2025-01-01", tz="UTC")
FOLDS = {
    "oos_2021": (pd.Timestamp("2021-02-01", tz="UTC"), pd.Timestamp("2022-01-01", tz="UTC")),
    "oos_2022": (pd.Timestamp("2022-02-01", tz="UTC"), pd.Timestamp("2023-01-01", tz="UTC")),
    "oos_2023": (pd.Timestamp("2023-02-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC")),
    "oos_2024": (pd.Timestamp("2024-02-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")),
}


def evaluate(
    data: pd.DataFrame,
    params: StrategyParams,
    config: BacktestConfig,
) -> dict[str, float | int | bool]:
    signaled = generate_signals(data, params)
    fold_metrics: dict[str, dict[str, float]] = {}
    for label, (start, end) in FOLDS.items():
        window = signaled.loc[(signaled.index >= start) & (signaled.index < end)]
        fold_metrics[label] = run_backtest(window, config).metrics
    pre = run_backtest(
        signaled.loc[(signaled.index >= SELECTION_START) & (signaled.index < SELECTION_END)],
        config,
    ).metrics

    sharpes = np.array([metrics["sharpe"] for metrics in fold_metrics.values()])
    calmars = np.array([
        metrics["cagr"] / max(abs(metrics["max_drawdown"]), 1e-9)
        for metrics in fold_metrics.values()
    ])
    drawdowns = np.array([metrics["max_drawdown"] for metrics in fold_metrics.values()])
    q25_sharpe = float(np.quantile(sharpes, 0.25))
    median_sharpe = float(np.median(sharpes))
    minimum_sharpe = float(sharpes.min())
    sharpe_dispersion = float(sharpes.std(ddof=1))
    median_calmar = float(np.median(calmars))
    worst_drawdown = float(drawdowns.min())
    raw_score = (
        0.35 * q25_sharpe
        + 0.25 * median_sharpe
        + 0.15 * minimum_sharpe
        + 0.10 * min(median_calmar, 4.0)
        + 0.10 * pre["sharpe"]
        + 0.05 * min(pre["sortino"], 4.0)
        - 0.20 * sharpe_dispersion
        - 0.00015 * pre["turnover_multiple"]
    )
    row: dict[str, float | int | bool] = params.to_dict()
    row.update({
        "raw_score": raw_score,
        "q25_fold_sharpe": q25_sharpe,
        "median_fold_sharpe": median_sharpe,
        "minimum_fold_sharpe": minimum_sharpe,
        "sharpe_dispersion": sharpe_dispersion,
        "median_fold_calmar": median_calmar,
        "worst_fold_drawdown": worst_drawdown,
    })
    for label, metrics in fold_metrics.items():
        for key, value in metrics.items():
            row[f"{label}_{key}"] = value
    for key, value in pre.items():
        row[f"pre_{key}"] = value
    return row


def add_plateau_scores(table: pd.DataFrame, dimensions: dict[str, list[float | int]]) -> pd.DataFrame:
    """Blend each score with nearby coarse-grid scores to avoid isolated optima."""
    result = table.copy()
    coordinate_maps = {
        name: {value: index for index, value in enumerate(values)}
        for name, values in dimensions.items()
    }
    coordinates = np.column_stack([
        result[name].map(coordinate_maps[name]).to_numpy(dtype=float)
        for name in dimensions
    ])
    raw_scores = result["raw_score"].to_numpy(dtype=float)
    neighbor_median: list[float] = []
    neighbor_q25: list[float] = []
    neighbor_count: list[int] = []
    for coordinate in coordinates:
        distance = np.nanmax(np.abs(coordinates - coordinate), axis=1)
        mask = np.isfinite(distance) & (distance <= 1)
        values = raw_scores[mask]
        neighbor_count.append(int(mask.sum()))
        neighbor_median.append(float(np.median(values)))
        neighbor_q25.append(float(np.quantile(values, 0.25)))
    result["neighbor_count"] = neighbor_count
    result["neighbor_median_score"] = neighbor_median
    result["neighbor_q25_score"] = neighbor_q25
    result["plateau_score"] = (
        0.50 * result["raw_score"]
        + 0.30 * result["neighbor_median_score"]
        + 0.20 * result["neighbor_q25_score"]
    )
    return result


def baseline_row(table: pd.DataFrame, base: StrategyParams) -> pd.Series:
    mask = pd.Series(True, index=table.index)
    for name, value in base.to_dict().items():
        mask &= table[name] == value
    if not mask.any():
        raise ValueError("baseline configuration is missing from the search table")
    return table.loc[mask].iloc[0]


def select_stable(table: pd.DataFrame, baseline: pd.Series) -> pd.Series:
    feasible = table.loc[
        (table["q25_fold_sharpe"] >= baseline["q25_fold_sharpe"] - 0.05)
        & (table["minimum_fold_sharpe"] >= baseline["minimum_fold_sharpe"] - 0.10)
        & (table["pre_sharpe"] >= baseline["pre_sharpe"] - 0.03)
        & (table["pre_cagr"] >= baseline["pre_cagr"] - 0.08)
        & (table["pre_max_drawdown"] >= baseline["pre_max_drawdown"] - 0.015)
        & (table["neighbor_count"] >= 8)
    ]
    if feasible.empty:
        raise RuntimeError("no candidate passed the pre-declared stability constraints")
    return feasible.sort_values(
        ["plateau_score", "neighbor_q25_score", "q25_fold_sharpe", "pre_sharpe"],
        ascending=False,
    ).iloc[0]


def params_from_row(row: pd.Series) -> StrategyParams:
    defaults = StrategyParams()
    values: dict[str, float | int | bool] = {}
    for name in StrategyParams.__dataclass_fields__:
        default = getattr(defaults, name)
        value = row[name]
        if isinstance(default, bool):
            values[name] = bool(value)
        elif isinstance(default, int):
            values[name] = int(value)
        else:
            values[name] = float(value)
    return StrategyParams(**values)


def unique_params(candidates: list[StrategyParams]) -> list[StrategyParams]:
    seen: set[tuple[tuple[str, object], ...]] = set()
    result: list[StrategyParams] = []
    for candidate in candidates:
        key = tuple(candidate.to_dict().items())
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def run_search(base_path: Path, output_dir: Path) -> StrategyParams:
    base = StrategyParams(**json.loads(base_path.read_text(encoding="utf-8")))
    data = load_market_data(ROOT / "data/raw", start="2020-01-01", end="2025-01-01")
    config = BacktestConfig()
    output_dir.mkdir(parents=True, exist_ok=True)

    structural_dimensions: dict[str, list[float | int]] = {
        "adx_enter": [25.0, 26.0, 27.0, 28.0],
        "adx_exit": [17.0, 18.0, 19.0],
        "trend_separation_atr": [0.10, 0.15, 0.20],
        "rebalance_bars": [48, 60, 72, 84],
    }
    structural = unique_params([
        base,
        *[
            replace(
                base,
                adx_enter=adx_enter,
                adx_exit=adx_exit,
                trend_separation_atr=separation,
                rebalance_bars=rebalance,
            )
            for adx_enter, adx_exit, separation, rebalance in product(
                *structural_dimensions.values()
            )
        ],
    ])
    stage_one = pd.DataFrame(evaluate(data, candidate, config) for candidate in structural)
    stage_one = add_plateau_scores(stage_one, structural_dimensions)
    stage_one_baseline = baseline_row(stage_one, base)
    selected_one_row = select_stable(stage_one, stage_one_baseline)
    selected_one = params_from_row(selected_one_row)
    stage_one = stage_one.sort_values("plateau_score", ascending=False).reset_index(drop=True)
    stage_one.to_csv(output_dir / "adaptive_v3_structural_grid.csv", index=False)

    control_dimensions: dict[str, list[float | int]] = {
        "funding_lookback": [6, 12, 18],
        "funding_factor_scale": [0.35, 0.40, 0.50],
        "downside_stress_threshold": [0.60, 0.625, 0.65],
        "downside_stress_scale": [0.25, 0.30, 0.35],
    }
    controls = unique_params([
        selected_one,
        *[
            replace(
                selected_one,
                funding_lookback=funding_lookback,
                funding_factor_scale=funding_scale,
                downside_stress_threshold=stress_threshold,
                downside_stress_scale=stress_scale,
            )
            for funding_lookback, funding_scale, stress_threshold, stress_scale in product(
                *control_dimensions.values()
            )
        ],
    ])
    stage_two = pd.DataFrame(evaluate(data, candidate, config) for candidate in controls)
    stage_two = add_plateau_scores(stage_two, control_dimensions)
    selected_one_baseline = baseline_row(stage_two, selected_one)
    selected_two_row = select_stable(stage_two, selected_one_baseline)
    selected_two = params_from_row(selected_two_row)
    stage_two = stage_two.sort_values("plateau_score", ascending=False).reset_index(drop=True)
    stage_two.to_csv(output_dir / "adaptive_v3_control_grid.csv", index=False)

    config_path = ROOT / "configs/aggressive_adaptive_v3_params.json"
    config_path.write_text(json.dumps(selected_two.to_dict(), indent=2) + "\n", encoding="utf-8")
    summary = {
        "method": "coarse_parameter_plateau_with_purged_annual_walkforward",
        "selection_window": "2020-01-01/2025-01-01",
        "post_2024_used_for_selection": False,
        "holdout_note": "2025+ was seen in prior research rounds and is reused only for reporting.",
        "folds": {
            label: {"start": str(start), "end": str(end)}
            for label, (start, end) in FOLDS.items()
        },
        "embargo_days_at_each_fold_start": 31,
        "candidate_count": {
            "structural": len(stage_one),
            "risk_control": len(stage_two),
        },
        "baseline_v2": json.loads(stage_one_baseline.to_json()),
        "selected_structural": json.loads(selected_one_row.to_json()),
        "selected_v3": json.loads(selected_two_row.to_json()),
        "selection_constraints": {
            "q25_fold_sharpe_tolerance": -0.05,
            "minimum_fold_sharpe_tolerance": -0.10,
            "pre_sharpe_tolerance": -0.03,
            "pre_cagr_tolerance": -0.08,
            "pre_max_drawdown_tolerance": -0.015,
            "minimum_neighbor_count": 8,
        },
    }
    (output_dir / "adaptive_v3_selection.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "config": str(config_path),
        "structural_candidates": len(stage_one),
        "control_candidates": len(stage_two),
        "selected": selected_two.to_dict(),
        "fold_sharpes": {
            label: float(selected_two_row[f"{label}_sharpe"])
            for label in FOLDS
        },
        "q25_fold_sharpe": float(selected_two_row["q25_fold_sharpe"]),
        "minimum_fold_sharpe": float(selected_two_row["minimum_fold_sharpe"]),
        "pre_sharpe": float(selected_two_row["pre_sharpe"]),
        "pre_cagr": float(selected_two_row["pre_cagr"]),
        "pre_max_drawdown": float(selected_two_row["pre_max_drawdown"]),
        "plateau_score": float(selected_two_row["plateau_score"]),
    }, indent=2))
    return selected_two


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base",
        type=Path,
        default=ROOT / "configs/aggressive_adaptive_v2_params.json",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args()
    run_search(args.base, args.output_dir)


if __name__ == "__main__":
    main()
