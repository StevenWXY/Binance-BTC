#!/usr/bin/env python3
"""Small structural calibration scan for the V71 final candidate."""

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


DEFAULT_PARAMS = ROOT / "configs/v71_final_candidate_params.json"
DEFAULT_EXECUTION = ROOT / "configs/v71_final_candidate_execution.json"
DEFAULT_OUTPUT = ROOT / "reports/module7_structure_calibration_2020_2026_08_01"


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


def _score(metrics: dict[str, float], baseline: dict[str, float]) -> dict[str, float]:
    sharpe_gain = metrics["sharpe"] - baseline["sharpe"]
    calmar_gain = metrics["calmar"] - baseline["calmar"]
    dd_change = abs(metrics["max_drawdown"]) - abs(baseline["max_drawdown"])
    final_equity_gain = metrics["final_equity"] - baseline["final_equity"]
    maker_gain = metrics.get("maker_fill_ratio", 0.0) - baseline.get("maker_fill_ratio", 0.0)
    dd_penalty = 0.0
    if dd_change > 0:
        dd_penalty += 8.0 * dd_change
    score = 1.25 * sharpe_gain + 0.90 * calmar_gain + 0.0002 * final_equity_gain + 0.10 * maker_gain - dd_penalty
    return {
        "score": float(score),
        "sharpe_gain": float(sharpe_gain),
        "calmar_gain": float(calmar_gain),
        "final_equity_gain": float(final_equity_gain),
        "max_drawdown_change": float(dd_change),
        "maker_fill_ratio_gain": float(maker_gain),
        "drawdown_penalty": float(dd_penalty),
    }


def _candidate_specs() -> list[dict[str, object]]:
    return [
        {"name": "baseline", "note": "当前结构化基线", "param": {}, "execution": {}},
        {
            "name": "relax_probes",
            "note": "放宽 long/short probe 最低许可阈值",
            "param": {
                "long_quality_floor": 0.26,
                "short_quality_floor": 0.40,
                "short_min_permission": 0.14,
            },
            "execution": {},
        },
        {
            "name": "softer_short_block",
            "note": "降低 short_release 阻断强度",
            "param": {
                "short_neutral_bias_scale": 0.60,
                "short_permission_scale": 0.95,
                "short_weak_permission_multiplier": 0.65,
                "short_min_permission": 0.14,
                "short_release_threshold": 0.50,
            },
            "execution": {},
        },
        {
            "name": "freer_range_rebound",
            "note": "放宽 range permission，保留低波动反弹",
            "param": {
                "range_block_tradability_threshold": 0.75,
                "range_block_trend_quality_threshold": 0.62,
                "range_base_permission_floor": 0.18,
                "range_min_permission": 0.14,
            },
            "execution": {},
        },
        {
            "name": "balanced_relax",
            "note": "同时适度放宽 probe、short、range",
            "param": {
                "long_quality_floor": 0.26,
                "long_neutral_bias_scale": 0.85,
                "short_quality_floor": 0.40,
                "short_neutral_bias_scale": 0.58,
                "short_permission_scale": 0.92,
                "short_weak_permission_multiplier": 0.60,
                "short_min_permission": 0.14,
                "short_release_threshold": 0.52,
                "range_block_tradability_threshold": 0.72,
                "range_block_trend_quality_threshold": 0.60,
                "range_base_permission_floor": 0.18,
                "range_min_permission": 0.14,
            },
            "execution": {},
        },
        {
            "name": "balanced_relax_plus",
            "note": "进一步放宽 neutral bias 和 short probe",
            "param": {
                "long_quality_floor": 0.24,
                "long_neutral_bias_scale": 0.90,
                "short_quality_floor": 0.38,
                "short_neutral_bias_scale": 0.65,
                "short_permission_scale": 0.98,
                "short_weak_permission_multiplier": 0.70,
                "short_min_permission": 0.12,
                "short_release_threshold": 0.50,
                "range_block_tradability_threshold": 0.75,
                "range_block_trend_quality_threshold": 0.62,
                "range_base_permission_floor": 0.18,
                "range_min_permission": 0.12,
            },
            "execution": {},
        },
        {
            "name": "probe_range_relax_only",
            "note": "只动 probe 和 range，不额外放宽 short 方向偏置",
            "param": {
                "long_quality_floor": 0.24,
                "short_quality_floor": 0.42,
                "short_min_permission": 0.15,
                "range_block_tradability_threshold": 0.75,
                "range_block_trend_quality_threshold": 0.62,
                "range_base_permission_floor": 0.18,
                "range_min_permission": 0.14,
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

    details: dict[str, object] = {
        "data": {"start": args.start, "end": args.end, "raw_dir": str(args.raw_dir)},
        "base_params": base_params,
        "base_execution": base_execution,
        "candidates": {},
    }
    rows: list[dict[str, object]] = []
    equity_curves: dict[str, pd.Series] = {}

    baseline_result = _run_candidate(base_params, base_execution, market, funding, minute_batches, args.end)
    baseline_metrics = baseline_result.metrics

    for spec in _candidate_specs():
        params = deepcopy(base_params)
        params.update(spec["param"])
        execution = deepcopy(base_execution)
        execution.update(spec["execution"])
        result = _run_candidate(params, execution, market, funding, minute_batches, args.end)
        metrics = result.metrics
        score = _score(metrics, baseline_metrics)
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
                "maker_fill_ratio": metrics.get("maker_fill_ratio", 0.0),
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
