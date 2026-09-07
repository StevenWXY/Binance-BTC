#!/usr/bin/env python3
"""Narrow structural calibration around the current best module7 candidate."""

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


DEFAULT_PARAMS = ROOT / "configs/v71_final_candidate_struct_calibrated_params.json"
DEFAULT_EXECUTION = ROOT / "configs/v71_final_candidate_execution.json"
DEFAULT_OUTPUT = ROOT / "reports/module7_structure_calibration_narrow_2020_2026_08_01"


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


def _year_value(annual: pd.DataFrame, year: int, column: str) -> float:
    matched = annual.loc[annual["year"] == year, column]
    return float(matched.iloc[0]) if not matched.empty else 0.0


def _score(metrics: dict[str, float], baseline: dict[str, float], annual: pd.DataFrame, baseline_annual: pd.DataFrame) -> dict[str, float]:
    sharpe_gain = metrics["sharpe"] - baseline["sharpe"]
    calmar_gain = metrics["calmar"] - baseline["calmar"]
    final_equity_gain = metrics["final_equity"] - baseline["final_equity"]
    dd_change = abs(metrics["max_drawdown"]) - abs(baseline["max_drawdown"])
    annual_2021_gain = _year_value(annual, 2021, "total_return") - _year_value(baseline_annual, 2021, "total_return")
    annual_2022_gain = _year_value(annual, 2022, "total_return") - _year_value(baseline_annual, 2022, "total_return")
    annual_2024_gain = _year_value(annual, 2024, "total_return") - _year_value(baseline_annual, 2024, "total_return")
    annual_2025_gain = _year_value(annual, 2025, "total_return") - _year_value(baseline_annual, 2025, "total_return")
    dd_penalty = 0.0
    if dd_change > 0:
        dd_penalty += 8.0 * dd_change
    score = (
        1.10 * sharpe_gain
        + 0.80 * calmar_gain
        + 4.0 * annual_2021_gain
        + 5.0 * annual_2022_gain
        + 2.5 * annual_2024_gain
        + 2.5 * annual_2025_gain
        + 0.00015 * final_equity_gain
        - dd_penalty
    )
    return {
        "score": float(score),
        "sharpe_gain": float(sharpe_gain),
        "calmar_gain": float(calmar_gain),
        "final_equity_gain": float(final_equity_gain),
        "annual_2021_gain": float(annual_2021_gain),
        "annual_2022_gain": float(annual_2022_gain),
        "annual_2024_gain": float(annual_2024_gain),
        "annual_2025_gain": float(annual_2025_gain),
        "max_drawdown_change": float(dd_change),
        "drawdown_penalty": float(dd_penalty),
    }


def _candidate_specs() -> list[dict[str, object]]:
    return [
        {"name": "baseline_balanced_relax_plus", "note": "当前窄口径基线", "param": {}, "execution": {}},
        {
            "name": "dd_tighter",
            "note": "略收中性偏置与 short 放行，优先压回撤",
            "param": {
                "long_neutral_bias_scale": 0.88,
                "short_neutral_bias_scale": 0.62,
                "short_permission_scale": 0.95,
                "short_weak_permission_multiplier": 0.66,
                "short_min_permission": 0.13,
                "range_min_permission": 0.13,
            },
            "execution": {},
        },
        {
            "name": "short_slightly_freer",
            "note": "轻微放宽 short release，观察 2021/2022",
            "param": {
                "short_quality_floor": 0.37,
                "short_neutral_bias_scale": 0.67,
                "short_permission_scale": 1.0,
                "short_weak_permission_multiplier": 0.72,
                "short_min_permission": 0.11,
                "short_release_threshold": 0.49,
            },
            "execution": {},
        },
        {
            "name": "range_careful",
            "note": "保留 probe 放宽，但把 range 稍微收一点",
            "param": {
                "range_block_tradability_threshold": 0.73,
                "range_block_trend_quality_threshold": 0.61,
                "range_base_permission_floor": 0.16,
                "range_min_permission": 0.13,
            },
            "execution": {},
        },
        {
            "name": "carry_balance",
            "note": "小幅照顾 2024/2025，long neutral 更宽、range 适中",
            "param": {
                "long_neutral_bias_scale": 0.92,
                "long_quality_floor": 0.23,
                "short_neutral_bias_scale": 0.64,
                "short_permission_scale": 0.97,
                "short_min_permission": 0.12,
                "range_block_tradability_threshold": 0.74,
                "range_block_trend_quality_threshold": 0.61,
                "range_base_permission_floor": 0.17,
            },
            "execution": {},
        },
        {
            "name": "balanced_mid",
            "note": "位于 dd_tighter 与 freer short 之间的中间解",
            "param": {
                "long_neutral_bias_scale": 0.90,
                "long_quality_floor": 0.245,
                "short_quality_floor": 0.375,
                "short_neutral_bias_scale": 0.64,
                "short_permission_scale": 0.97,
                "short_weak_permission_multiplier": 0.69,
                "short_min_permission": 0.12,
                "short_release_threshold": 0.50,
                "range_block_tradability_threshold": 0.74,
                "range_block_trend_quality_threshold": 0.61,
                "range_base_permission_floor": 0.17,
                "range_min_permission": 0.12,
            },
            "execution": {},
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

    base_params = _read_json(args.params)
    base_execution = _read_json(args.execution)
    market = _load_market(args.raw_dir, args.start, args.end)
    funding = load_funding(args.raw_dir, start=args.start, end=args.end)
    minute_batches = list(iter_intrabar_months(args.raw_dir, start=args.start, end=args.end))

    baseline_result = _run_candidate(base_params, base_execution, market, funding, minute_batches, args.end)
    baseline_metrics = baseline_result.metrics
    baseline_annual = _annual_metrics(baseline_result)

    rows: list[dict[str, object]] = []
    details: dict[str, object] = {
        "data": {"start": args.start, "end": args.end, "raw_dir": str(args.raw_dir)},
        "base_params": base_params,
        "base_execution": base_execution,
        "baseline_metrics": baseline_metrics,
        "baseline_annual": baseline_annual.to_dict(orient="records"),
        "candidates": {},
    }
    equity_curves: dict[str, pd.Series] = {}

    for spec in _candidate_specs():
        params = deepcopy(base_params)
        params.update(spec["param"])
        execution = deepcopy(base_execution)
        execution.update(spec["execution"])
        result = _run_candidate(params, execution, market, funding, minute_batches, args.end)
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
                **score,
            }
        )
        details["candidates"][spec["name"]] = {
            "note": spec["note"],
            "param_overrides": spec["param"],
            "execution_overrides": spec["execution"],
            "params": params,
            "execution": execution,
            "metrics": metrics,
            "annual": annual.to_dict(orient="records"),
            "score": score,
        }
        equity_curves[spec["name"]] = result.equity.rename(spec["name"])

    summary = pd.DataFrame(rows).sort_values(["score", "sharpe", "calmar"], ascending=[False, False, False])
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output / "summary_metrics.csv", index=False)
    pd.concat(equity_curves.values(), axis=1).to_csv(output / "equity_curves.csv")
    best_name = str(summary.iloc[0]["candidate"])
    (output / "best_candidate_params.json").write_text(
        json.dumps(details["candidates"][best_name]["params"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "best_candidate_execution.json").write_text(
        json.dumps(details["candidates"][best_name]["execution"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "report.json").write_text(json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
