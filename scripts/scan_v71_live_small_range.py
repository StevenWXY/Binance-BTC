#!/usr/bin/env python3
"""Run a curated small-range parameter scan for wzy V7.1-live."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.data import iter_intrabar_months, load_funding, load_market_data  # noqa: E402
from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest  # noqa: E402
from btc_regime.v43 import V43Params, generate_v43_signals  # noqa: E402
from btc_regime.v71_live import V71LiveParams, generate_v71_live_signals  # noqa: E402


DEFAULT_OUTPUT = ROOT / "reports/v71_live_small_scan_2020_2026_08_01"
DEFAULT_EXECUTION = ROOT / "configs/v71_live_execution.json"
DEFAULT_MAIN_PARAMS = ROOT / "configs/v4_3_params.json"
DEFAULT_X_PARAMS = ROOT / "configs/v71_reference_params.json"
DEFAULT_WZY_PARAMS = ROOT / "configs/v71_live_params.json"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_market(raw_dir: Path, start: str, end: str) -> pd.DataFrame:
    requested_start = pd.Timestamp(start, tz="UTC")
    load_start = "2020-01-01" if requested_start > pd.Timestamp("2020-01-01", tz="UTC") else start
    return load_market_data(raw_dir, start=load_start, end=end)


def _run_strategy(
    params_dict: dict[str, object],
    execution_dict: dict[str, object],
    market: pd.DataFrame,
    funding: pd.DataFrame,
    minute_batches: list[pd.DataFrame],
    end: str,
) -> tuple[dict[str, float], pd.Series]:
    params = V71LiveParams(**params_dict)
    execution = MicroBacktestConfig(**execution_dict)
    signaled = generate_v71_live_signals(market, params)
    result = run_micro_backtest(
        signaled.loc[signaled.index < pd.Timestamp(end, tz="UTC")],
        minute_batches,
        funding,
        execution,
    )
    return result.metrics, result.equity


def _baseline_references(
    market: pd.DataFrame,
    funding: pd.DataFrame,
    end: str,
    minute_batches: list[pd.DataFrame],
    execution_dict: dict[str, object],
    main_params_dict: dict[str, object],
    x_params_dict: dict[str, object],
    wzy_params_dict: dict[str, object],
) -> dict[str, dict[str, float]]:
    runs = {}
    main_params = V43Params(**main_params_dict)
    execution = MicroBacktestConfig(**execution_dict)
    main_result = run_micro_backtest(
        generate_v43_signals(market, main_params).loc[
            lambda df: df.index < pd.Timestamp(end, tz="UTC")
        ],
        minute_batches,
        funding,
        execution,
    )
    runs["main_v43"] = main_result.metrics
    for code, params_dict in {
        "xuyujian_v71_ref": x_params_dict,
        "wzy_v71_live": wzy_params_dict,
    }.items():
        metrics, _ = _run_strategy(
            params_dict,
            execution_dict,
            market,
            funding,
            minute_batches,
            end,
        )
        runs[code] = metrics
    return runs


def _score_candidate(metrics: dict[str, float], refs: dict[str, dict[str, float]]) -> dict[str, float]:
    baseline = refs["wzy_v71_live"]
    x_ref = refs["xuyujian_v71_ref"]
    main = refs["main_v43"]

    baseline_sharpe = baseline["sharpe"]
    baseline_calmar = baseline["calmar"]
    target_sharpe = max(x_ref["sharpe"], baseline_sharpe)
    target_calmar = max(x_ref["calmar"], baseline_calmar)
    stretch_sharpe = max(main["sharpe"], target_sharpe)
    stretch_calmar = max(main["calmar"], target_calmar)

    sharpe_gap = max(target_sharpe - baseline_sharpe, 1e-9)
    calmar_gap = max(target_calmar - baseline_calmar, 1e-9)
    sharpe_progress = (metrics["sharpe"] - baseline_sharpe) / sharpe_gap
    calmar_progress = (metrics["calmar"] - baseline_calmar) / calmar_gap

    if stretch_sharpe > target_sharpe + 1e-9:
        sharpe_stretch = max(
            0.0,
            (metrics["sharpe"] - target_sharpe) / (stretch_sharpe - target_sharpe),
        )
    else:
        sharpe_stretch = 0.0
    if stretch_calmar > target_calmar + 1e-9:
        calmar_stretch = max(
            0.0,
            (metrics["calmar"] - target_calmar) / (stretch_calmar - target_calmar),
        )
    else:
        calmar_stretch = 0.0

    baseline_dd = abs(baseline["max_drawdown"])
    x_ref_dd = abs(x_ref["max_drawdown"])
    candidate_dd = abs(metrics["max_drawdown"])

    baseline_drawdown_advantage = (baseline_dd - candidate_dd) / max(baseline_dd, 1e-9)
    x_ref_margin = (x_ref_dd - candidate_dd) / max(x_ref_dd, 1e-9)
    drawdown_penalty = 0.0
    if candidate_dd > baseline_dd:
        drawdown_penalty += 2.5 * (candidate_dd - baseline_dd) / max(baseline_dd, 1e-9)
    if candidate_dd > x_ref_dd:
        drawdown_penalty += 4.0 * (candidate_dd - x_ref_dd) / max(x_ref_dd, 1e-9)

    score = (
        0.50 * sharpe_progress
        + 0.35 * calmar_progress
        + 0.10 * sharpe_stretch
        + 0.05 * calmar_stretch
        + 0.20 * max(0.0, x_ref_margin)
        - drawdown_penalty
    )
    return {
        "score": float(score),
        "sharpe_progress_to_x_ref": float(sharpe_progress),
        "calmar_progress_to_x_ref": float(calmar_progress),
        "sharpe_stretch_to_main": float(sharpe_stretch),
        "calmar_stretch_to_main": float(calmar_stretch),
        "baseline_drawdown_advantage": float(baseline_drawdown_advantage),
        "x_ref_drawdown_margin": float(x_ref_margin),
        "drawdown_penalty": float(drawdown_penalty),
    }


def _candidate_specs(
    base_params: dict[str, object],
    base_execution: dict[str, object],
    x_ref_params: dict[str, object],
) -> list[dict[str, object]]:
    tighter_governor = {
        "strategy_drawdown_level_1": 0.07,
        "strategy_drawdown_scale_1": 0.75,
        "strategy_drawdown_level_2": 0.11,
        "strategy_drawdown_scale_2": 0.45,
        "strategy_drawdown_level_3": 0.15,
        "strategy_drawdown_scale_3": 0.0,
    }
    return [
        {
            "name": "baseline",
            "note": "当前 wzy V7.1-live 基线",
            "param_overrides": {},
            "execution_overrides": {},
        },
        {
            "name": "lighter_short",
            "note": "进一步压低做空预算，先守回撤",
            "param_overrides": {"short_scale": 0.08},
            "execution_overrides": {},
        },
        {
            "name": "faster_trend_capture",
            "note": "略放宽突破与趋势确认，尝试提高 Sharpe",
            "param_overrides": {
                "breakout_buffer_atr": 0.20,
                "trend_confirm_bars": 2,
            },
            "execution_overrides": {},
        },
        {
            "name": "tighter_breakout_filter",
            "note": "更保守地确认突破，优先守假突破回撤",
            "param_overrides": {
                "breakout_buffer_atr": 0.30,
                "trend_confirm_bars": 3,
            },
            "execution_overrides": {},
        },
        {
            "name": "quicker_exit",
            "note": "更快退出弱趋势，减少利润回吐",
            "param_overrides": {
                "trend_exit_confirm_bars": 2,
                "trailing_stop_atr": 1.60,
            },
            "execution_overrides": {},
        },
        {
            "name": "rapid_lock_profit",
            "note": "快速趋势一旦减速，更积极地缩仓",
            "param_overrides": {
                "rapid_deceleration_scale": 0.35,
            },
            "execution_overrides": {},
        },
        {
            "name": "tighter_governor",
            "note": "账户级 governor 更早介入",
            "param_overrides": {},
            "execution_overrides": tighter_governor,
        },
        {
            "name": "balanced_recovery",
            "note": "在保回撤的前提下，稍微向 xuyujian_ref 靠拢",
            "param_overrides": {
                "breakout_buffer_atr": 0.20,
                "trend_confirm_bars": 2,
                "short_scale": 0.08,
                "rapid_deceleration_scale": 0.35,
            },
            "execution_overrides": tighter_governor,
        },
        {
            "name": "ref_plus_live",
            "note": "用 xuyujian_ref 的骨架叠加 live protection 与 governor",
            "param_overrides": {
                **{
                    key: value
                    for key, value in x_ref_params.items()
                    if key not in {
                        "live_protection_enabled",
                        "downside_protection_enabled",
                    }
                },
                "live_protection_enabled": True,
                "downside_protection_enabled": True,
                "short_scale": 0.12,
                "max_leverage": 6.0,
                "trend_scale": 1.60,
                "rebound_scale": 0.11,
                "stop_atr": 1.8,
                "take_profit_atr": 3.2,
                "trailing_stop_atr": 1.7,
                "downside_stop_atr": 0.7,
                "downside_lookback": 3,
                "downside_return_threshold": -0.025,
                "downside_vol_ratio": 1.2,
                "downside_confirmation_bars": 2,
                "exit_cooldown_bars": 3,
                "max_hold_bars": 96,
            },
            "execution_overrides": base_execution,
        },
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument("--execution", type=Path, default=DEFAULT_EXECUTION)
    parser.add_argument("--main-params", type=Path, default=DEFAULT_MAIN_PARAMS)
    parser.add_argument("--x-params", type=Path, default=DEFAULT_X_PARAMS)
    parser.add_argument("--wzy-params", type=Path, default=DEFAULT_WZY_PARAMS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    execution_dict = _read_json(args.execution)
    main_params_dict = _read_json(args.main_params)
    x_params_dict = _read_json(args.x_params)
    wzy_params_dict = _read_json(args.wzy_params)

    market = _load_market(args.raw_dir, args.start, args.end)
    funding = load_funding(args.raw_dir, start=args.start, end=args.end)
    minute_batches = list(iter_intrabar_months(args.raw_dir, start=args.start, end=args.end))
    refs = _baseline_references(
        market,
        funding,
        args.end,
        minute_batches,
        execution_dict,
        main_params_dict,
        x_params_dict,
        wzy_params_dict,
    )

    candidates = _candidate_specs(wzy_params_dict, execution_dict, x_params_dict)
    rows: list[dict[str, object]] = []
    details: dict[str, object] = {
        "data": {
            "start": pd.Timestamp(args.start, tz="UTC").isoformat(),
            "end": pd.Timestamp(args.end, tz="UTC").isoformat(),
            "raw_dir": str(args.raw_dir),
        },
        "score_method": {
            "goal": "尽量保持 max_drawdown 优势，同时把 Sharpe 和 Calmar 往 xuyujian_ref 甚至 main_v43 靠",
            "drawdown_guardrails": {
                "baseline_wzy_live_max_drawdown": refs["wzy_v71_live"]["max_drawdown"],
                "xuyujian_ref_max_drawdown": refs["xuyujian_v71_ref"]["max_drawdown"],
            },
            "notes": [
                "Sharpe 和 Calmar 相对 baseline 与 xuyujian_ref 的改善是主要加分项",
                "超过当前 wzy baseline 的回撤会被惩罚",
                "超过 xuyujian_ref 的回撤会受到更重惩罚",
                "若 Sharpe/Calmar 超过 xuyujian_ref，继续向 main_v43 靠近会获得额外奖励",
            ],
        },
        "references": refs,
        "candidates": {},
    }
    equity_curves: dict[str, pd.Series] = {}

    for spec in candidates:
        params_dict = deepcopy(wzy_params_dict)
        params_dict.update(spec["param_overrides"])
        execution_candidate = deepcopy(execution_dict)
        execution_candidate.update(spec["execution_overrides"])
        print(f"Running candidate: {spec['name']}")
        metrics, equity = _run_strategy(
            params_dict,
            execution_candidate,
            market,
            funding,
            minute_batches,
            args.end,
        )
        score_details = _score_candidate(metrics, refs)
        row = {
            "candidate": spec["name"],
            "note": spec["note"],
            "score": score_details["score"],
            "final_equity": metrics["final_equity"],
            "total_return": metrics["total_return"],
            "cagr": metrics["cagr"],
            "annualized_volatility": metrics["annualized_volatility"],
            "sharpe": metrics["sharpe"],
            "sortino": metrics["sortino"],
            "calmar": metrics["calmar"],
            "max_drawdown": metrics["max_drawdown"],
            "fees_paid": metrics["fees_paid"],
            "funding_paid": metrics["funding_paid"],
            "maker_fill_ratio": metrics.get("maker_fill_ratio", 0.0),
            "liquidation_count": metrics["liquidation_count"],
            "governor_max_drawdown_observed": metrics.get("governor_max_drawdown_observed", 0.0),
            **score_details,
        }
        rows.append(row)
        equity_curves[spec["name"]] = equity.rename(spec["name"])
        details["candidates"][spec["name"]] = {
            "note": spec["note"],
            "param_overrides": spec["param_overrides"],
            "execution_overrides": spec["execution_overrides"],
            "params": params_dict,
            "execution": execution_candidate,
            "metrics": metrics,
            "score": score_details,
        }

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame(rows).sort_values(
        ["score", "sharpe", "calmar"],
        ascending=[False, False, False],
    )
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
