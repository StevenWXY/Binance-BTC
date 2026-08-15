#!/usr/bin/env python3
"""Compare minute-execution fine-tune finalists on the pre-2025 sample."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.backtest import calculate_metrics  # noqa: E402


CANDIDATES = {
    "adaptive_v1": ROOT / "reports/fine_micro_candidates/baseline",
    "adaptive_v2_stress_040": ROOT / "reports/fine_micro_candidates/stress_040",
    "adaptive_v2_stress_035": ROOT / "reports/fine_micro_candidates/stress_035",
    "adaptive_v2_stress_030": ROOT / "reports/fine_micro_candidates/stress_030",
}


def period_cost(path: Path, filename: str, value_column: str, end: pd.Timestamp) -> float:
    file_path = path / filename
    if not file_path.exists() or file_path.stat().st_size == 0:
        return 0.0
    frame = pd.read_csv(file_path)
    if frame.empty:
        return 0.0
    timestamp = pd.to_datetime(frame["timestamp"], utc=True)
    return float(frame.loc[timestamp < end, value_column].sum())


def pre_holdout_metrics(path: Path) -> dict[str, float]:
    end = pd.Timestamp("2025-01-01", tz="UTC")
    equity = pd.read_csv(path / "micro_equity.csv", index_col=0)
    equity.index = pd.to_datetime(equity.index, utc=True)
    equity_series = equity.loc[equity.index <= end, "equity"]
    trades = pd.read_csv(path / "micro_trades.csv")
    if not trades.empty:
        exit_time = pd.to_datetime(trades["exit_time"], utc=True)
        trades = trades.loc[exit_time < end]
    metrics = calculate_metrics(
        equity_series,
        equity_series.pct_change().dropna(),
        trades,
        2190,
    )
    metrics.update({
        "fees_paid": period_cost(path, "micro_fills.csv", "fee", end),
        "funding_paid": period_cost(path, "micro_funding.csv", "payment", end),
    })
    return metrics


def main() -> None:
    rows = []
    for label, path in CANDIDATES.items():
        report = json.loads((path / "micro_metrics.json").read_text())
        pre = pre_holdout_metrics(path)
        train = report["periods"]["train_2020_2022"]
        validation = report["periods"]["validation_2023_2024"]
        rows.append({
            "candidate": label,
            "adx_enter": report["strategy"]["adx_enter"],
            "rebalance_bars": report["strategy"]["rebalance_bars"],
            "funding_factor_scale": report["strategy"]["funding_factor_scale"],
            "downside_stress_threshold": report["strategy"]["downside_stress_threshold"],
            "downside_stress_scale": report["strategy"]["downside_stress_scale"],
            "train_sharpe": train["sharpe"],
            "validation_sharpe": validation["sharpe"],
            "minimum_period_sharpe": min(train["sharpe"], validation["sharpe"]),
            **{f"pre_{key}": value for key, value in pre.items()},
        })
    table = pd.DataFrame(rows)
    table["micro_robust_score"] = (
        0.45 * table["minimum_period_sharpe"]
        + 0.25 * table["pre_sharpe"]
        + 0.15 * (table["pre_cagr"] / table["pre_max_drawdown"].abs()).clip(upper=5)
        + 0.10 * table["pre_sortino"]
        - 0.05 * (table["train_sharpe"] - table["validation_sharpe"]).abs()
    )
    table = table.sort_values(
        ["micro_robust_score", "pre_sharpe", "pre_cagr"], ascending=False
    ).reset_index(drop=True)
    output = ROOT / "reports/adaptive_v2_micro_selection.csv"
    table.to_csv(output, index=False)
    winner_label = str(table.iloc[0]["candidate"])
    winner_report = json.loads((CANDIDATES[winner_label] / "micro_metrics.json").read_text())
    config_path = ROOT / "configs/aggressive_adaptive_v2_params.json"
    config_path.write_text(json.dumps(winner_report["strategy"], indent=2) + "\n")
    selection_path = ROOT / "reports/adaptive_v2_selection.json"
    selection = json.loads(selection_path.read_text())
    selection["micro_refinement"] = {
        "selection_window": "2020-01-01/2025-01-01",
        "holdout_accessed": False,
        "candidate_count": len(table),
        "selected_candidate": winner_label,
        "selected_strategy": winner_report["strategy"],
        "selected_metrics": json.loads(table.iloc[0].to_json()),
        "ranking_file": str(output.relative_to(ROOT)),
    }
    selection_path.write_text(json.dumps(selection, indent=2) + "\n")
    full_v1 = json.loads((ROOT / "reports/aggressive_adaptive_micro/micro_metrics.json").read_text())
    full_v2 = json.loads((ROOT / "reports/aggressive_adaptive_v2_micro/micro_metrics.json").read_text())
    full_keys = [
        "final_equity", "cagr", "sharpe", "sortino", "max_drawdown", "fill_count",
        "fees_paid", "funding_paid", "max_leverage_observed", "liquidation_count",
    ]
    holdout_keys = ["final_equity", "cagr", "sharpe", "sortino", "max_drawdown"]
    comparison = {
        "adaptive_v1": {key: full_v1["metrics"][key] for key in full_keys},
        "adaptive_v2": {key: full_v2["metrics"][key] for key in full_keys},
        "delta_v2_minus_v1": {
            key: full_v2["metrics"][key] - full_v1["metrics"][key] for key in full_keys
        },
        "holdout_2025_2026_07": {
            "adaptive_v1": {
                key: full_v1["periods"]["holdout_2025_2026_07"][key] for key in holdout_keys
            },
            "adaptive_v2": {
                key: full_v2["periods"]["holdout_2025_2026_07"][key] for key in holdout_keys
            },
            "delta_v2_minus_v1": {
                key: full_v2["periods"]["holdout_2025_2026_07"][key]
                - full_v1["periods"]["holdout_2025_2026_07"][key]
                for key in holdout_keys
            },
        },
    }
    (ROOT / "reports/aggressive_adaptive_v2_comparison.json").write_text(
        json.dumps(comparison, indent=2) + "\n"
    )
    columns = [
        "candidate", "micro_robust_score", "train_sharpe", "validation_sharpe",
        "pre_cagr", "pre_sharpe", "pre_sortino", "pre_max_drawdown",
        "pre_final_equity", "pre_fees_paid", "pre_funding_paid",
    ]
    print(table.loc[:, columns].to_string(index=False))
    print(f"\nselected={winner_label}\nconfig={config_path}")


if __name__ == "__main__":
    main()
