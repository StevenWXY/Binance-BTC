#!/usr/bin/env python3
"""Compare the long-only D baseline with fixed cautious long/short E."""

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
    return float(returns.mean() / standard_deviation * np.sqrt(PERIODS_PER_YEAR)) if standard_deviation else 0.0


def paired_block_bootstrap(left: pd.Series, right: pd.Series, start: str, end: str) -> dict[str, float | int]:
    aligned = pd.concat([left.rename("d"), right.rename("e")], axis=1).dropna()
    aligned = aligned.loc[
        (aligned.index >= pd.Timestamp(start, tz="UTC"))
        & (aligned.index < pd.Timestamp(end, tz="UTC"))
    ]
    returns = aligned.pct_change().dropna().to_numpy(dtype=float)
    n = len(returns)
    rng = np.random.default_rng(SEED)
    differences = np.empty(BOOTSTRAP_SAMPLES, dtype=float)
    block_count = int(np.ceil(n / BLOCK_BARS))
    offsets = np.arange(BLOCK_BARS)
    for sample in range(BOOTSTRAP_SAMPLES):
        starts = rng.integers(0, n, size=block_count)
        indices = ((starts[:, None] + offsets) % n).reshape(-1)[:n]
        boot = returns[indices]
        differences[sample] = annualized_sharpe(boot[:, 1]) - annualized_sharpe(boot[:, 0])
    return {
        "bars": n,
        "block_bars": BLOCK_BARS,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "observed_d_sharpe": annualized_sharpe(returns[:, 0]),
        "observed_e_sharpe": annualized_sharpe(returns[:, 1]),
        "observed_sharpe_delta_e_minus_d": annualized_sharpe(returns[:, 1])
        - annualized_sharpe(returns[:, 0]),
        "delta_ci_95_low": float(np.quantile(differences, 0.025)),
        "delta_ci_95_high": float(np.quantile(differences, 0.975)),
        "probability_e_delta_positive": float((differences > 0).mean()),
    }


def metrics_subset(report: dict[str, object], period: str) -> dict[str, float]:
    source = report["metrics"] if period == "full" else report["periods"][period]
    keys = [
        "final_equity", "cagr", "sharpe", "sortino", "max_drawdown",
        "trade_count", "fill_count", "fees_paid", "funding_paid", "liquidation_count",
    ]
    return {key: float(source[key]) for key in keys if key in source}


def main() -> None:
    d_path = REPORTS / "aggressive_adaptive_v3_micro"
    e_path = REPORTS / "aggressive_adaptive_v4_short_micro"
    d_report = json.loads((d_path / "micro_metrics.json").read_text(encoding="utf-8"))
    e_report = json.loads((e_path / "micro_metrics.json").read_text(encoding="utf-8"))
    d_equity = load_equity(d_path / "micro_equity.csv")
    e_equity = load_equity(e_path / "micro_equity.csv")

    period_names = ["train_2020_2022", "validation_2023_2024", "holdout_2025_2026_07", "full"]
    comparison: dict[str, object] = {}
    for period in period_names:
        d = metrics_subset(d_report, period)
        e = metrics_subset(e_report, period)
        comparison[period] = {
            "d_long_only": d,
            "e_cautious_symmetric_short": e,
            "delta_e_minus_d": {key: e[key] - d[key] for key in d.keys() & e.keys()},
        }

    report = {
        "strategy_e": {
            "config": "configs/aggressive_adaptive_v4_short_params.json",
            "signal_symmetry": "EMA/DI trend direction is symmetric; long rebound remains long-only.",
            "short_risk_budget": "short_scale=0.25, max leverage=6.5x",
            "short_confirmation": "close below EMA120 and 24-bar momentum below zero",
            "selection_protocol": "fixed before inspection; 2020-2024 four-fold sensitivity is diagnostic only",
            "holdout_warning": "2025+ was seen in prior research rounds and is reused only for reporting.",
        },
        "comparison": comparison,
        "paired_block_bootstrap": {
            "pre_2025_selection_period": paired_block_bootstrap(d_equity, e_equity, "2020-01-01", "2025-01-01"),
            "reused_2025_2026_reporting_period": paired_block_bootstrap(d_equity, e_equity, "2025-01-01", "2026-08-01"),
            "full_period": paired_block_bootstrap(d_equity, e_equity, "2020-01-01", "2026-08-01"),
        },
        "interpretation": (
            "E is a controlled experiment, not a claim that shorting improves the strategy. "
            "It slightly reduces full-period drawdown but also reduces full-period Sharpe and "
            "net equity after realistic fills, fees, funding, and liquidation checks."
        ),
    }
    output = REPORTS / "aggressive_adaptive_v4_short_comparison.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
