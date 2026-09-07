#!/usr/bin/env python3
"""Second-round local tuning around ref_plus_live."""

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


DEFAULT_PARAMS = ROOT / "configs/v71_ref_plus_live_params.json"
DEFAULT_EXECUTION = ROOT / "configs/v71_ref_plus_live_execution.json"
DEFAULT_OUTPUT = ROOT / "reports/ref_plus_live_round2_scan_2020_2026_08_01"


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
    maker_gain = metrics.get("maker_fill_ratio", 0.0) - baseline.get("maker_fill_ratio", 0.0)
    governor_change = (
        metrics.get("governor_max_drawdown_observed", 0.0)
        - baseline.get("governor_max_drawdown_observed", 0.0)
    )
    dd_penalty = 0.0
    if dd_change > 0:
        dd_penalty += 8.0 * dd_change
    if abs(metrics["max_drawdown"]) > abs(baseline["max_drawdown"]) + 0.01:
        dd_penalty += 4.0 * (abs(metrics["max_drawdown"]) - abs(baseline["max_drawdown"]) - 0.01)
    score = (
        1.20 * sharpe_gain
        + 0.90 * calmar_gain
        + 0.15 * maker_gain
        - dd_penalty
        - 0.10 * max(governor_change, 0.0)
    )
    return {
        "score": float(score),
        "sharpe_gain": float(sharpe_gain),
        "calmar_gain": float(calmar_gain),
        "max_drawdown_change": float(dd_change),
        "maker_fill_ratio_gain": float(maker_gain),
        "governor_drawdown_change": float(governor_change),
        "drawdown_penalty": float(dd_penalty),
    }


def _candidate_specs() -> list[dict[str, object]]:
    return [
        {"name": "baseline", "note": "当前 ref_plus_live 基线", "param": {}, "execution": {}},
        {
            "name": "lighter_short_010",
            "note": "进一步压低做空预算",
            "param": {"short_scale": 0.10},
            "execution": {},
        },
        {
            "name": "trend_scale_155",
            "note": "略收趋势杠杆，观察回撤与质量",
            "param": {"trend_scale": 1.55},
            "execution": {},
        },
        {
            "name": "breakout_022_exit3",
            "note": "突破缓冲略收，趋势退出更快",
            "param": {"breakout_buffer_atr": 0.22, "trend_exit_confirm_bars": 3},
            "execution": {},
        },
        {
            "name": "confirm3_trail16",
            "note": "趋势确认更严格，移动止损更紧",
            "param": {"trend_confirm_bars": 3, "trailing_stop_atr": 1.6},
            "execution": {},
        },
        {
            "name": "trail16_short010",
            "note": "更紧的 trailing stop 配合更轻做空",
            "param": {"trailing_stop_atr": 1.6, "short_scale": 0.10},
            "execution": {},
        },
        {
            "name": "breakout018_trend165",
            "note": "更积极的突破确认与趋势仓位",
            "param": {"breakout_buffer_atr": 0.18, "trend_scale": 1.65},
            "execution": {},
        },
        {
            "name": "governor_earlier_short010",
            "note": "governor 更早介入，同时降低做空",
            "param": {"short_scale": 0.10},
            "execution": {
                "strategy_drawdown_level_1": 0.07,
                "strategy_drawdown_scale_1": 0.75,
                "strategy_drawdown_level_2": 0.11,
                "strategy_drawdown_scale_2": 0.45,
                "strategy_drawdown_level_3": 0.15,
                "strategy_drawdown_scale_3": 0.0,
            },
        },
        {
            "name": "balanced_local_best",
            "note": "局部综合：轻做空、略紧 trailing、略快退出",
            "param": {
                "short_scale": 0.10,
                "trailing_stop_atr": 1.6,
                "trend_exit_confirm_bars": 3,
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

    rows: list[dict[str, object]] = []
    details: dict[str, object] = {
        "data": {"start": args.start, "end": args.end, "raw_dir": str(args.raw_dir)},
        "base_params": base_params,
        "base_execution": base_execution,
        "candidates": {},
    }
    equity_curves: dict[str, pd.Series] = {}

    baseline_result = _run_candidate(
        base_params,
        base_execution,
        market,
        funding,
        minute_batches,
        args.end,
    )
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
                "sharpe": metrics["sharpe"],
                "calmar": metrics["calmar"],
                "max_drawdown": metrics["max_drawdown"],
                "maker_fill_ratio": metrics.get("maker_fill_ratio", 0.0),
                "governor_max_drawdown_observed": metrics.get("governor_max_drawdown_observed", 0.0),
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

    summary = pd.DataFrame(rows).sort_values(
        ["score", "sharpe", "calmar"],
        ascending=[False, False, False],
    )
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
    (output / "report.json").write_text(
        json.dumps(details, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
