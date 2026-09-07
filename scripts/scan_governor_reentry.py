#!/usr/bin/env python3
"""Small execution-only scan for redesigned governor reentry settings."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.data import iter_intrabar_months, load_funding, load_market_data  # noqa: E402
from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest  # noqa: E402
from btc_regime.v71_live import V71LiveParams, generate_v71_live_signals  # noqa: E402


DEFAULT_PARAMS = ROOT / "configs/v71_final_candidate_long_participation_params.json"
DEFAULT_EXECUTION = ROOT / "configs/v71_final_candidate_long_participation_execution.json"
DEFAULT_OUTPUT = ROOT / "reports/governor_reentry_scan_2020_2026_08_01"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_market(raw_dir: Path, start: str, end: str) -> pd.DataFrame:
    requested_start = pd.Timestamp(start, tz="UTC")
    load_start = "2020-01-01" if requested_start > pd.Timestamp("2020-01-01", tz="UTC") else start
    return load_market_data(raw_dir, start=load_start, end=end)


def _run_candidate(
    params_dict: dict[str, object],
    execution_dict: dict[str, object],
    market: pd.DataFrame,
    funding: pd.DataFrame,
    minute_batches: list[pd.DataFrame],
    end: str,
):
    params = V71LiveParams(**params_dict)
    execution = MicroBacktestConfig(**execution_dict)
    signaled = generate_v71_live_signals(market, params)
    return run_micro_backtest(
        signaled.loc[signaled.index < pd.Timestamp(end, tz="UTC")],
        minute_batches,
        funding,
        execution,
    )


def _annual_metrics(result) -> pd.DataFrame:
    rows = []
    years = sorted({ts.year for ts in result.equity.index})
    for year in years:
        start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        end = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        equity = result.equity.loc[(result.equity.index >= start) & (result.equity.index <= end)]
        if len(equity) < 2:
            continue
        returns = equity.pct_change().dropna()
        rows.append(
            {
                "year": year,
                "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1),
                "sharpe": float(returns.mean() / returns.std(ddof=1) * (2190 ** 0.5))
                if len(returns) > 1 and returns.std(ddof=1) > 0
                else 0.0,
                "max_drawdown": float((equity / equity.cummax() - 1).min()),
            }
        )
    return pd.DataFrame(rows)


def _year_value(frame: pd.DataFrame, year: int, column: str) -> float:
    matched = frame.loc[frame["year"] == year, column]
    return float(matched.iloc[0]) if not matched.empty else 0.0


def _score(metrics: dict[str, float], baseline: dict[str, float], annual: pd.DataFrame, baseline_annual: pd.DataFrame) -> dict[str, float]:
    sharpe_gain = metrics["sharpe"] - baseline["sharpe"]
    calmar_gain = metrics["calmar"] - baseline["calmar"]
    final_equity_gain = metrics["final_equity"] - baseline["final_equity"]
    dd_change = abs(metrics["max_drawdown"]) - abs(baseline["max_drawdown"])
    return_2020_gain = _year_value(annual, 2020, "total_return") - _year_value(baseline_annual, 2020, "total_return")
    return_2023_gain = _year_value(annual, 2023, "total_return") - _year_value(baseline_annual, 2023, "total_return")
    return_2025_gain = _year_value(annual, 2025, "total_return") - _year_value(baseline_annual, 2025, "total_return")
    return_2026_gain = _year_value(annual, 2026, "total_return") - _year_value(baseline_annual, 2026, "total_return")
    dd_penalty = 0.0
    if dd_change > 0.01:
        dd_penalty += 10.0 * (dd_change - 0.01)
    score = (
        1.4 * sharpe_gain
        + 1.0 * calmar_gain
        + 0.0002 * final_equity_gain
        + 8.0 * return_2020_gain
        + 8.0 * return_2023_gain
        + 6.0 * return_2025_gain
        + 12.0 * return_2026_gain
        - dd_penalty
    )
    return {
        "score": float(score),
        "sharpe_gain": float(sharpe_gain),
        "calmar_gain": float(calmar_gain),
        "final_equity_gain": float(final_equity_gain),
        "return_2020_gain": float(return_2020_gain),
        "return_2023_gain": float(return_2023_gain),
        "return_2025_gain": float(return_2025_gain),
        "return_2026_gain": float(return_2026_gain),
        "max_drawdown_change": float(dd_change),
        "drawdown_penalty": float(dd_penalty),
    }


def _candidate_specs() -> list[dict[str, object]]:
    return [
        {"name": "baseline_semantic_fix", "note": "只保留 reduce-only 语义修正", "execution": {}},
        {
            "name": "reentry_level2_only",
            "note": "只在 level2/1 恢复段放开，不在 level3 再加仓",
            "execution": {
                "strategy_drawdown_continuation_reentry_enabled": True,
                "strategy_drawdown_continuation_reentry_recovery_buffer": 0.04,
                "strategy_drawdown_continuation_reentry_scale_1": 1.0,
                "strategy_drawdown_continuation_reentry_scale_2": 0.70,
                "strategy_drawdown_continuation_reentry_scale_3": 0.0,
            },
        },
        {
            "name": "reentry_conservative",
            "note": "更晚恢复，且 level3 仅极小幅放开",
            "execution": {
                "strategy_drawdown_continuation_reentry_enabled": True,
                "strategy_drawdown_continuation_reentry_recovery_buffer": 0.05,
                "strategy_drawdown_continuation_reentry_scale_1": 1.0,
                "strategy_drawdown_continuation_reentry_scale_2": 0.65,
                "strategy_drawdown_continuation_reentry_scale_3": 0.15,
            },
        },
        {
            "name": "reentry_mild",
            "note": "温和恢复，同步兼顾 2025/2026",
            "execution": {
                "strategy_drawdown_continuation_reentry_enabled": True,
                "strategy_drawdown_continuation_reentry_recovery_buffer": 0.045,
                "strategy_drawdown_continuation_reentry_scale_1": 1.0,
                "strategy_drawdown_continuation_reentry_scale_2": 0.68,
                "strategy_drawdown_continuation_reentry_scale_3": 0.10,
            },
        },
        {
            "name": "reentry_balanced",
            "note": "兼顾恢复与不过早重开 level3 风险",
            "execution": {
                "strategy_drawdown_continuation_reentry_enabled": True,
                "strategy_drawdown_continuation_reentry_recovery_buffer": 0.05,
                "strategy_drawdown_continuation_reentry_scale_1": 0.95,
                "strategy_drawdown_continuation_reentry_scale_2": 0.62,
                "strategy_drawdown_continuation_reentry_scale_3": 0.0,
            },
        },
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument("--params", type=Path, default=DEFAULT_PARAMS)
    parser.add_argument("--execution", type=Path, default=DEFAULT_EXECUTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    params_dict = _read_json(args.params)
    base_execution = _read_json(args.execution)
    market = _load_market(args.raw_dir, args.start, args.end)
    funding = load_funding(args.raw_dir, start=args.start, end=args.end)
    minute_batches = list(iter_intrabar_months(args.raw_dir, start=args.start, end=args.end))

    baseline_result = _run_candidate(params_dict, base_execution, market, funding, minute_batches, args.end)
    baseline_metrics = baseline_result.metrics
    baseline_annual = _annual_metrics(baseline_result)

    rows: list[dict[str, object]] = []
    details: dict[str, object] = {
        "data": {"start": args.start, "end": args.end, "raw_dir": str(args.raw_dir)},
        "baseline_execution": base_execution,
        "baseline_metrics": baseline_metrics,
        "baseline_annual": baseline_annual.to_dict(orient="records"),
        "candidates": {},
    }
    for spec in _candidate_specs():
        execution = deepcopy(base_execution)
        execution.update(spec["execution"])
        result = _run_candidate(params_dict, execution, market, funding, minute_batches, args.end)
        annual = _annual_metrics(result)
        metrics = result.metrics
        score = _score(metrics, baseline_metrics, annual, baseline_annual)
        rows.append(
            {
                "candidate": spec["name"],
                "note": spec["note"],
                "final_equity": metrics["final_equity"],
                "total_return": metrics["total_return"],
                "sharpe": metrics["sharpe"],
                "calmar": metrics["calmar"],
                "max_drawdown": metrics["max_drawdown"],
                "trade_count": metrics["trade_count"],
                "return_2020": _year_value(annual, 2020, "total_return"),
                "return_2023": _year_value(annual, 2023, "total_return"),
                "return_2025": _year_value(annual, 2025, "total_return"),
                "return_2026": _year_value(annual, 2026, "total_return"),
                **score,
            }
        )
        details["candidates"][spec["name"]] = {
            "note": spec["note"],
            "execution": execution,
            "metrics": metrics,
            "annual": annual.to_dict(orient="records"),
            "score": score,
        }

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    summary.to_csv(output / "summary_metrics.csv", index=False)
    best_name = str(summary.iloc[0]["candidate"])
    (output / "best_candidate_execution.json").write_text(
        json.dumps(details["candidates"][best_name]["execution"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "report.json").write_text(
        json.dumps({"best_candidate": best_name, "summary": rows, **details}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
