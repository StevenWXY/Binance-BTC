#!/usr/bin/env python3
"""Evaluate a pre-declared, low-dimensional symmetric short overlay.

The table is diagnostic only.  The E configuration is fixed before inspecting
the scores, so this script cannot select a post-hoc winner from the holdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
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


def evaluate(data: pd.DataFrame, params: StrategyParams, config: BacktestConfig) -> dict[str, float | str | bool]:
    signaled = generate_signals(data, params)
    row: dict[str, float | str | bool] = {
        "short_scale": params.short_scale,
        "short_momentum_gate_enabled": params.short_momentum_gate_enabled,
    }
    fold_sharpes: list[float] = []
    for label, (start, end) in FOLDS.items():
        window = signaled.loc[(signaled.index >= start) & (signaled.index < end)]
        metrics = run_backtest(window, config).metrics
        row[f"{label}_sharpe"] = metrics["sharpe"]
        row[f"{label}_cagr"] = metrics["cagr"]
        row[f"{label}_max_drawdown"] = metrics["max_drawdown"]
        fold_sharpes.append(float(metrics["sharpe"]))
    pre = run_backtest(
        signaled.loc[(signaled.index >= SELECTION_START) & (signaled.index < SELECTION_END)],
        config,
    ).metrics
    row.update({
        "q25_fold_sharpe": float(np.quantile(fold_sharpes, 0.25)),
        "minimum_fold_sharpe": float(np.min(fold_sharpes)),
        "pre_sharpe": pre["sharpe"],
        "pre_sortino": pre["sortino"],
        "pre_cagr": pre["cagr"],
        "pre_max_drawdown": pre["max_drawdown"],
        "pre_average_leverage": pre["average_leverage"],
        "pre_turnover_multiple": pre["turnover_multiple"],
        "pre_final_equity": pre["final_equity"],
    })
    return row


def run(base_path: Path, output_dir: Path) -> pd.DataFrame:
    base = StrategyParams(**json.loads(base_path.read_text(encoding="utf-8")))
    data = load_market_data(ROOT / "data/raw", start="2020-01-01", end="2025-01-01")
    config = BacktestConfig()
    # The first row is the existing long-only baseline. The remaining rows are
    # a deliberately tiny sensitivity check around the pre-declared E settings.
    candidates = [
        ("D_long_only_baseline", base),
        ("E_short_025_gate_on", replace(base, allow_short=True, short_scale=0.25, short_momentum_gate_enabled=True)),
        ("short_025_gate_off", replace(base, allow_short=True, short_scale=0.25, short_momentum_gate_enabled=False)),
        ("short_035_gate_on", replace(base, allow_short=True, short_scale=0.35, short_momentum_gate_enabled=True)),
        ("short_035_gate_off", replace(base, allow_short=True, short_scale=0.35, short_momentum_gate_enabled=False)),
        ("short_050_gate_on", replace(base, allow_short=True, short_scale=0.50, short_momentum_gate_enabled=True)),
        ("short_050_gate_off", replace(base, allow_short=True, short_scale=0.50, short_momentum_gate_enabled=False)),
    ]
    rows = []
    for name, params in candidates:
        result = evaluate(data, params, config)
        result["candidate"] = name
        rows.append(result)
    table = pd.DataFrame(rows)
    table = table[["candidate"] + [column for column in table.columns if column != "candidate"]]
    output_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(output_dir / "aggressive_adaptive_v4_short_sensitivity.csv", index=False)
    summary = {
        "method": "fixed_short_overlay_sensitivity",
        "selection_window": "2020-01-01/2025-01-01",
        "post_2024_used_for_selection": False,
        "holdout_note": "2025+ was seen in prior research rounds and is reused only for reporting.",
        "folds": {label: {"start": str(start), "end": str(end)} for label, (start, end) in FOLDS.items()},
        "selection_policy": "E is pre-declared as short_scale=0.25 with bearish price/momentum confirmation; sensitivity rows are diagnostic and never used to select E.",
        "baseline": "D_long_only_baseline",
        "fixed_e": "E_short_025_gate_on",
        "rows": json.loads(table.to_json(orient="records")),
    }
    (output_dir / "aggressive_adaptive_v4_short_sensitivity.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(table.to_string(index=False))
    return table


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=ROOT / "configs/aggressive_adaptive_v3_params.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args()
    run(args.base, args.output_dir)


if __name__ == "__main__":
    main()
