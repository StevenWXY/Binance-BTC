#!/usr/bin/env python3
"""Write a V2/V3 comparison with paired block-bootstrap uncertainty."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
PERIODS_PER_YEAR = 2190
BLOCK_BARS = 84  # 14 days of 4h returns.
BOOTSTRAP_SAMPLES = 2_000
SEED = 20260815


def load_equity(path: Path) -> pd.Series:
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame["equity"].astype(float)


def annualized_sharpe(returns: np.ndarray) -> float:
    standard_deviation = float(returns.std(ddof=1))
    if standard_deviation <= 0:
        return 0.0
    return float(returns.mean() / standard_deviation * np.sqrt(PERIODS_PER_YEAR))


def paired_block_bootstrap(
    left: pd.Series,
    right: pd.Series,
    start: str,
    end: str,
) -> dict[str, float | int]:
    aligned = pd.concat([left.rename("v2"), right.rename("v3")], axis=1).dropna()
    aligned = aligned.loc[
        (aligned.index >= pd.Timestamp(start, tz="UTC"))
        & (aligned.index < pd.Timestamp(end, tz="UTC"))
    ]
    returns = aligned.pct_change().dropna().to_numpy(dtype=float)
    n = len(returns)
    rng = np.random.default_rng(SEED)
    differences = np.empty(BOOTSTRAP_SAMPLES, dtype=float)
    v3_sharpes = np.empty(BOOTSTRAP_SAMPLES, dtype=float)
    block_count = int(np.ceil(n / BLOCK_BARS))
    offsets = np.arange(BLOCK_BARS)
    for sample in range(BOOTSTRAP_SAMPLES):
        starts = rng.integers(0, n, size=block_count)
        indices = ((starts[:, None] + offsets) % n).reshape(-1)[:n]
        boot = returns[indices]
        v2_sharpe = annualized_sharpe(boot[:, 0])
        v3_sharpe = annualized_sharpe(boot[:, 1])
        differences[sample] = v3_sharpe - v2_sharpe
        v3_sharpes[sample] = v3_sharpe
    return {
        "bars": n,
        "block_bars": BLOCK_BARS,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "observed_v2_sharpe": annualized_sharpe(returns[:, 0]),
        "observed_v3_sharpe": annualized_sharpe(returns[:, 1]),
        "observed_sharpe_delta": annualized_sharpe(returns[:, 1])
        - annualized_sharpe(returns[:, 0]),
        "v3_sharpe_ci_95_low": float(np.quantile(v3_sharpes, 0.025)),
        "v3_sharpe_ci_95_high": float(np.quantile(v3_sharpes, 0.975)),
        "delta_ci_95_low": float(np.quantile(differences, 0.025)),
        "delta_ci_95_high": float(np.quantile(differences, 0.975)),
        "probability_v3_delta_positive": float((differences > 0).mean()),
    }


def metrics_subset(report: dict[str, object], period: str) -> dict[str, float]:
    source = report["metrics"] if period == "full" else report["periods"][period]
    keys = [
        "final_equity",
        "cagr",
        "sharpe",
        "sortino",
        "max_drawdown",
        "trade_count",
        "fill_count",
        "fees_paid",
        "funding_paid",
        "liquidation_count",
    ]
    return {key: float(source[key]) for key in keys if key in source}


def main() -> None:
    v2_path = REPORTS / "aggressive_adaptive_v2_micro"
    v3_path = REPORTS / "aggressive_adaptive_v3_micro"
    v2_report = json.loads((v2_path / "micro_metrics.json").read_text(encoding="utf-8"))
    v3_report = json.loads((v3_path / "micro_metrics.json").read_text(encoding="utf-8"))
    v2_equity = load_equity(v2_path / "micro_equity.csv")
    v3_equity = load_equity(v3_path / "micro_equity.csv")

    period_names = [
        "train_2020_2022",
        "validation_2023_2024",
        "holdout_2025_2026_07",
        "full",
    ]
    comparison: dict[str, object] = {}
    for period in period_names:
        v2 = metrics_subset(v2_report, period)
        v3 = metrics_subset(v3_report, period)
        comparison[period] = {
            "v2": v2,
            "v3": v3,
            "delta_v3_minus_v2": {key: v3[key] - v2[key] for key in v2.keys() & v3.keys()},
        }

    selection = json.loads((REPORTS / "adaptive_v3_selection.json").read_text(encoding="utf-8"))
    report = {
        "selection_protocol": {
            "post_2024_used_for_selection": False,
            "selection_window": selection["selection_window"],
            "folds": selection["folds"],
            "embargo_days_at_each_fold_start": selection["embargo_days_at_each_fold_start"],
            "candidate_count": selection["candidate_count"],
            "plateau_selection": True,
            "holdout_warning": selection["holdout_note"],
        },
        "comparison": comparison,
        "paired_block_bootstrap": {
            "pre_2025_selection_period": paired_block_bootstrap(
                v2_equity, v3_equity, "2020-01-01", "2025-01-01"
            ),
            "reused_2025_2026_reporting_period": paired_block_bootstrap(
                v2_equity, v3_equity, "2025-01-01", "2026-08-01"
            ),
            "full_period": paired_block_bootstrap(
                v2_equity, v3_equity, "2020-01-01", "2026-08-01"
            ),
        },
        "interpretation": (
            "Bootstrap intervals measure return-path uncertainty, not all forms of model or "
            "selection risk. The post-2024 period is not a pristine holdout because earlier "
            "research rounds already inspected it."
        ),
    }
    output = REPORTS / "aggressive_adaptive_v3_robustness.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
