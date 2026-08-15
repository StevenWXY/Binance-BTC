#!/usr/bin/env python3
"""Fine-tune the adaptive strategy without exposing the post-2024 holdout."""

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
from btc_regime.data import load_market_data  # noqa: E402
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402


BOUNDARIES = {
    "train": (pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp("2023-01-01", tz="UTC")),
    "validation": (pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")),
    "pre_holdout": (pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")),
}


def evaluate(
    data: pd.DataFrame,
    params: StrategyParams,
    config: BacktestConfig,
) -> dict[str, float | int | bool]:
    signaled = generate_signals(data, params)
    period_metrics: dict[str, dict[str, float]] = {}
    for label, (start, end) in BOUNDARIES.items():
        window = signaled.loc[(signaled.index >= start) & (signaled.index < end)]
        period_metrics[label] = run_backtest(window, config).metrics

    train = period_metrics["train"]
    validation = period_metrics["validation"]
    pre_holdout = period_metrics["pre_holdout"]
    minimum_sharpe = min(train["sharpe"], validation["sharpe"])
    average_sharpe = (train["sharpe"] + validation["sharpe"]) / 2
    sharpe_gap = abs(train["sharpe"] - validation["sharpe"])
    minimum_calmar = min(
        train["cagr"] / max(abs(train["max_drawdown"]), 1e-9),
        validation["cagr"] / max(abs(validation["max_drawdown"]), 1e-9),
    )
    robust_score = (
        0.50 * minimum_sharpe
        + 0.20 * average_sharpe
        + 0.15 * min(minimum_calmar, 5.0)
        + 0.10 * min(pre_holdout["cagr"], 2.0)
        - 0.12 * sharpe_gap
        - 0.0002 * pre_holdout["turnover_multiple"]
    )
    row: dict[str, float | int | bool] = params.to_dict()
    row.update({
        "robust_score": robust_score,
        "minimum_sharpe": minimum_sharpe,
        "minimum_calmar": minimum_calmar,
        "sharpe_gap": sharpe_gap,
    })
    for prefix, metrics in period_metrics.items():
        for key, value in metrics.items():
            row[f"{prefix}_{key}"] = value
    return row


def select_candidate(table: pd.DataFrame, baseline: pd.Series) -> pd.Series:
    feasible = table.loc[
        (table["minimum_sharpe"] >= baseline["minimum_sharpe"] - 0.02)
        & (table["train_max_drawdown"] >= baseline["train_max_drawdown"] - 0.02)
        & (table["validation_max_drawdown"] >= baseline["validation_max_drawdown"] - 0.02)
    ]
    if feasible.empty:
        feasible = table
    return feasible.sort_values(
        ["robust_score", "minimum_sharpe", "pre_holdout_cagr"],
        ascending=False,
    ).iloc[0]


def select_final_candidate(table: pd.DataFrame, baseline: pd.Series) -> pd.Series:
    """Require the final refinement to preserve aggregate pre-holdout quality."""
    feasible = table.loc[
        (table["pre_holdout_sharpe"] >= baseline["pre_holdout_sharpe"])
        & (table["pre_holdout_cagr"] >= baseline["pre_holdout_cagr"] - 0.03)
        & (table["pre_holdout_max_drawdown"] >= baseline["pre_holdout_max_drawdown"] - 0.005)
        & (table["train_max_drawdown"] >= baseline["train_max_drawdown"] - 0.02)
        & (table["validation_max_drawdown"] >= baseline["validation_max_drawdown"] - 0.02)
    ]
    if feasible.empty:
        return select_candidate(table, baseline)
    return feasible.sort_values(
        ["robust_score", "minimum_sharpe", "pre_holdout_cagr"],
        ascending=False,
    ).iloc[0]


def params_from_row(row: pd.Series) -> StrategyParams:
    fields = StrategyParams.__dataclass_fields__
    defaults = StrategyParams()
    values: dict[str, float | int | bool] = {}
    for name in fields:
        default = getattr(defaults, name)
        value = row[name]
        if isinstance(default, bool):
            values[name] = bool(value)
        elif isinstance(default, int):
            values[name] = int(value)
        else:
            values[name] = float(value)
    return StrategyParams(**values)


def write_selection(
    base_path: Path,
    output_dir: Path,
    baseline_row: dict[str, float | int | bool] | pd.Series,
    selected_two_row: pd.Series,
) -> StrategyParams:
    selected_two = params_from_row(selected_two_row)
    config_path = ROOT / "configs/aggressive_adaptive_v2_params.json"
    config_path.write_text(json.dumps(selected_two.to_dict(), indent=2) + "\n")
    baseline_json = json.loads(pd.Series(baseline_row).to_json())
    selected_json = json.loads(selected_two_row.to_json())
    summary = {
        "selection_window": "2020-01-01/2025-01-01",
        "holdout_accessed": False,
        "baseline": baseline_json,
        "selected": selected_json,
    }
    (output_dir / "adaptive_v2_selection.json").write_text(
        json.dumps(summary, indent=2) + "\n",
    )
    print(json.dumps({
        "config": str(config_path),
        "selected": selected_two.to_dict(),
        "pre_holdout": {
            key: float(selected_two_row[f"pre_holdout_{key}"])
            for key in ("cagr", "sharpe", "sortino", "max_drawdown", "average_leverage")
        },
        "train_sharpe": float(selected_two_row["train_sharpe"]),
        "validation_sharpe": float(selected_two_row["validation_sharpe"]),
        "robust_score": float(selected_two_row["robust_score"]),
    }, indent=2))
    return selected_two


def finalize_existing(base_path: Path, output_dir: Path) -> StrategyParams:
    base = StrategyParams(**json.loads(base_path.read_text()))
    stage_one = pd.read_csv(output_dir / "adaptive_signal_fine_grid.csv")
    stage_two = pd.read_csv(output_dir / "adaptive_control_fine_grid.csv")
    mask = pd.Series(True, index=stage_one.index)
    for name, value in base.to_dict().items():
        mask &= stage_one[name] == value
    if not mask.any():
        raise ValueError("baseline row not found in the existing stage-one grid")
    baseline = stage_one.loc[mask].iloc[0]
    selected = select_final_candidate(stage_two, baseline)
    return write_selection(base_path, output_dir, baseline, selected)


def run_search(base_path: Path, output_dir: Path) -> StrategyParams:
    base = StrategyParams(**json.loads(base_path.read_text()))
    data = load_market_data(ROOT / "data/raw", start="2020-01-01", end="2025-01-01")
    config = BacktestConfig()
    baseline_row = evaluate(data, base, config)
    baseline = pd.Series(baseline_row)

    stage_one_params = [base]
    for adx_enter, adx_exit, separation, rebalance in product(
        [25.0, 26.0, 27.0, 28.0, 29.0],
        [16.0, 18.0, 20.0],
        [0.10, 0.15, 0.20],
        [48, 60, 72, 84, 96],
    ):
        if adx_exit >= adx_enter:
            continue
        stage_one_params.append(replace(
            base,
            adx_enter=adx_enter,
            adx_exit=adx_exit,
            trend_separation_atr=separation,
            rebalance_bars=rebalance,
        ))
    stage_one = pd.DataFrame(evaluate(data, params, config) for params in stage_one_params)
    stage_one = stage_one.sort_values(
        ["robust_score", "minimum_sharpe", "pre_holdout_cagr"], ascending=False
    ).reset_index(drop=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    stage_one.to_csv(output_dir / "adaptive_signal_fine_grid.csv", index=False)
    selected_one = params_from_row(select_candidate(stage_one, baseline))

    stage_two_params = [selected_one]
    for funding_threshold, funding_scale, stress_threshold, stress_scale in product(
        [0.00016, 0.00018, 0.00020, 0.00022, 0.00024],
        [0.40, 0.50, 0.60],
        [0.600, 0.625, 0.650],
        [0.30, 0.35, 0.40],
    ):
        stage_two_params.append(replace(
            selected_one,
            funding_high_threshold=funding_threshold,
            funding_factor_scale=funding_scale,
            downside_stress_threshold=stress_threshold,
            downside_stress_scale=stress_scale,
        ))
    stage_two = pd.DataFrame(evaluate(data, params, config) for params in stage_two_params)
    stage_two = stage_two.sort_values(
        ["robust_score", "minimum_sharpe", "pre_holdout_cagr"], ascending=False
    ).reset_index(drop=True)
    stage_two.to_csv(output_dir / "adaptive_control_fine_grid.csv", index=False)
    selected_two_row = select_final_candidate(stage_two, baseline)
    return write_selection(base_path, output_dir, baseline_row, selected_two_row)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base",
        type=Path,
        default=ROOT / "configs/aggressive_adaptive_params.json",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports")
    parser.add_argument("--finalize-only", action="store_true")
    args = parser.parse_args()
    if args.finalize_only:
        finalize_existing(args.base, args.output_dir)
    else:
        run_search(args.base, args.output_dir)


if __name__ == "__main__":
    main()
