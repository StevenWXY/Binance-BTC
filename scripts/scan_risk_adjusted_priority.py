#!/usr/bin/env python3
"""Search for a more risk-efficient V7.1 live candidate.

This scan intentionally prioritizes Sharpe / Calmar over raw return.
It explores a small, hand-curated grid around the current 2023-targeted
candidate so we can keep the search local and interpretable.
"""

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


DEFAULT_PARAMS = ROOT / "configs/v71_final_candidate_2023_targeted_params.json"
DEFAULT_EXECUTION = ROOT / "configs/v71_final_candidate_2023_targeted_execution.json"
DEFAULT_X_PARAMS = ROOT / "configs/v71_reference_params.json"
DEFAULT_OUTPUT = ROOT / "reports/risk_adjusted_priority_scan_2020_2026_08_01"


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
                "sharpe": float(returns.mean() / returns.std(ddof=1) * (2190**0.5))
                if len(returns) > 1 and returns.std(ddof=1) > 0
                else 0.0,
                "max_drawdown": float((equity / equity.cummax() - 1).min()),
            }
        )
    return pd.DataFrame(rows)


def _year_value(frame: pd.DataFrame, year: int, column: str) -> float:
    matched = frame.loc[frame["year"] == year, column]
    return float(matched.iloc[0]) if not matched.empty else 0.0


def _candidate_specs() -> list[dict[str, object]]:
    short_modes = {
        "current_short": {},
        "light_short": {
            "allow_short": True,
            "short_scale": 0.06,
            "short_permission_scale": 0.84,
            "short_quality_floor": 0.40,
            "short_release_threshold": 0.52,
        },
        "almost_off_short": {
            "allow_short": True,
            "short_scale": 0.04,
            "short_permission_scale": 0.76,
            "short_quality_floor": 0.43,
            "short_release_threshold": 0.55,
            "short_min_permission": 0.13,
        },
        "off_short": {
            "allow_short": False,
            "short_scale": 0.01,
        },
    }
    risk_modes = {
        "risk_base": {},
        "risk_trim": {
            "target_vol": 0.84,
            "trend_scale": 1.38,
            "long_permission_scale": 1.08,
            "long_continuation_threshold": 0.60,
        },
        "risk_trim_more": {
            "target_vol": 0.76,
            "trend_scale": 1.24,
            "long_permission_scale": 1.02,
            "long_continuation_threshold": 0.62,
        },
    }
    governor_modes = {
        "gov_base": {},
        "gov_early": {
            "strategy_drawdown_level_1": 0.07,
            "strategy_drawdown_scale_1": 0.72,
            "strategy_drawdown_level_2": 0.10,
            "strategy_drawdown_scale_2": 0.42,
            "strategy_drawdown_level_3": 0.14,
            "strategy_drawdown_scale_3": 0.0,
            "strategy_drawdown_continuation_reentry_scale_2": 0.55,
        },
    }

    specs: list[dict[str, object]] = [
        {"name": "baseline_2023_targeted", "note": "current latest candidate", "params": {}, "execution": {}}
    ]
    for short_name, short_params in short_modes.items():
        for risk_name, risk_params in risk_modes.items():
            for gov_name, gov_execution in governor_modes.items():
                name = f"{short_name}__{risk_name}__{gov_name}"
                note = (
                    f"{short_name}, {risk_name}, {gov_name}; "
                    "prioritize Sharpe/Calmar over absolute return"
                )
                params = deepcopy(short_params)
                params.update(risk_params)
                specs.append(
                    {
                        "name": name,
                        "note": note,
                        "params": params,
                        "execution": deepcopy(gov_execution),
                    }
                )
    return specs


def _score(
    metrics: dict[str, float],
    baseline: dict[str, float],
    x_ref: dict[str, float],
    annual: pd.DataFrame,
) -> dict[str, float]:
    sharpe_gain = metrics["sharpe"] - baseline["sharpe"]
    calmar_gain = metrics["calmar"] - baseline["calmar"]
    sharpe_vs_x = metrics["sharpe"] - x_ref["sharpe"]
    calmar_vs_x = metrics["calmar"] - x_ref["calmar"]
    dd_improvement = abs(baseline["max_drawdown"]) - abs(metrics["max_drawdown"])
    ret_2021 = _year_value(annual, 2021, "total_return")
    ret_2022 = _year_value(annual, 2022, "total_return")
    ret_2023 = _year_value(annual, 2023, "total_return")
    ret_2024 = _year_value(annual, 2024, "total_return")

    trade_penalty = 0.0
    if metrics["trade_count"] < 120:
        trade_penalty += 0.0015 * (120 - metrics["trade_count"])

    return_penalty = 0.0
    if metrics["total_return"] < 0.12:
        return_penalty += 1.5 * (0.12 - metrics["total_return"])

    dead_year_penalty = 0.0
    if max(ret_2021, ret_2022, ret_2023, ret_2024) < 0.02:
        dead_year_penalty += 0.08

    score = (
        3.6 * sharpe_gain
        + 3.0 * calmar_gain
        + 4.0 * max(sharpe_vs_x, 0.0)
        + 3.5 * max(calmar_vs_x, 0.0)
        + 1.2 * dd_improvement
        + 0.30 * metrics["total_return"]
        - trade_penalty
        - return_penalty
        - dead_year_penalty
    )
    return {
        "score": float(score),
        "sharpe_gain_vs_baseline": float(sharpe_gain),
        "calmar_gain_vs_baseline": float(calmar_gain),
        "sharpe_gap_vs_x": float(sharpe_vs_x),
        "calmar_gap_vs_x": float(calmar_vs_x),
        "max_drawdown_improvement": float(dd_improvement),
        "trade_penalty": float(trade_penalty),
        "return_penalty": float(return_penalty),
        "dead_year_penalty": float(dead_year_penalty),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument("--params", type=Path, default=DEFAULT_PARAMS)
    parser.add_argument("--execution", type=Path, default=DEFAULT_EXECUTION)
    parser.add_argument("--x-params", type=Path, default=DEFAULT_X_PARAMS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    base_params = _read_json(args.params)
    base_execution = _read_json(args.execution)
    x_params = _read_json(args.x_params)

    market = _load_market(args.raw_dir, args.start, args.end)
    funding = load_funding(args.raw_dir, start=args.start, end=args.end)
    minute_batches = list(iter_intrabar_months(args.raw_dir, start=args.start, end=args.end))

    baseline_result = _run_candidate(base_params, base_execution, market, funding, minute_batches, args.end)
    baseline_metrics = baseline_result.metrics
    x_result = _run_candidate(x_params, base_execution, market, funding, minute_batches, args.end)
    x_metrics = x_result.metrics

    rows: list[dict[str, object]] = []
    details: dict[str, object] = {
        "data": {"start": args.start, "end": args.end, "raw_dir": str(args.raw_dir)},
        "baseline_params": base_params,
        "baseline_execution": base_execution,
        "baseline_metrics": baseline_metrics,
        "x_reference_params": x_params,
        "x_reference_metrics": x_metrics,
        "candidates": {},
    }

    for spec in _candidate_specs():
        params = deepcopy(base_params)
        params.update(spec["params"])
        execution = deepcopy(base_execution)
        execution.update(spec["execution"])
        result = _run_candidate(params, execution, market, funding, minute_batches, args.end)
        metrics = result.metrics
        annual = _annual_metrics(result)
        score = _score(metrics, baseline_metrics, x_metrics, annual)
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
                "return_2021": _year_value(annual, 2021, "total_return"),
                "return_2022": _year_value(annual, 2022, "total_return"),
                "return_2023": _year_value(annual, 2023, "total_return"),
                "return_2024": _year_value(annual, 2024, "total_return"),
                **score,
            }
        )
        details["candidates"][spec["name"]] = {
            "note": spec["note"],
            "params": params,
            "execution": execution,
            "metrics": metrics,
            "annual": annual.to_dict(orient="records"),
            "score": score,
        }

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    best_name = str(summary.iloc[0]["candidate"])
    summary.to_csv(output / "summary_metrics.csv", index=False)
    (output / "best_candidate_params.json").write_text(
        json.dumps(details["candidates"][best_name]["params"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "best_candidate_execution.json").write_text(
        json.dumps(details["candidates"][best_name]["execution"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "report.json").write_text(
        json.dumps(
            {
                "best_candidate": best_name,
                "baseline_metrics": baseline_metrics,
                "x_reference_metrics": x_metrics,
                "summary": rows,
                **details,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
