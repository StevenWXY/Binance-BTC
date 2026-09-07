#!/usr/bin/env python3
"""Targeted long participation scan against BTC-relative annual returns."""

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


DEFAULT_PARAMS = ROOT / "configs/v71_final_candidate_struct_calibrated_narrow_params.json"
DEFAULT_EXECUTION = ROOT / "configs/v71_final_candidate_execution.json"
DEFAULT_OUTPUT = ROOT / "reports/module7_long_participation_2020_2026_08_01"


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


def _btc_annual_returns(market: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    close = market["close"].loc[(market.index >= pd.Timestamp(start, tz="UTC")) & (market.index < pd.Timestamp(end, tz="UTC"))]
    rows = []
    years = sorted({ts.year for ts in close.index})
    for year in years:
        start_ts = pd.Timestamp(f"{year}-01-01", tz="UTC")
        end_ts = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        year_close = close.loc[(close.index >= start_ts) & (close.index < end_ts)]
        if len(year_close) < 2:
            continue
        rows.append({"year": year, "btc_total_return": float(year_close.iloc[-1] / year_close.iloc[0] - 1)})
    return pd.DataFrame(rows)


def _year_value(frame: pd.DataFrame, year: int, column: str) -> float:
    matched = frame.loc[frame["year"] == year, column]
    return float(matched.iloc[0]) if not matched.empty else 0.0


def _score(
    metrics: dict[str, float],
    baseline: dict[str, float],
    annual: pd.DataFrame,
    baseline_annual: pd.DataFrame,
    btc_annual: pd.DataFrame,
) -> dict[str, float]:
    annual = annual.merge(btc_annual, on="year", how="left")
    baseline_annual = baseline_annual.merge(btc_annual, on="year", how="left")
    annual["excess_return"] = annual["total_return"] - annual["btc_total_return"]
    baseline_annual["excess_return"] = baseline_annual["total_return"] - baseline_annual["btc_total_return"]

    sharpe_gain = metrics["sharpe"] - baseline["sharpe"]
    calmar_gain = metrics["calmar"] - baseline["calmar"]
    final_equity_gain = metrics["final_equity"] - baseline["final_equity"]
    dd_change = abs(metrics["max_drawdown"]) - abs(baseline["max_drawdown"])
    excess_2020_gain = _year_value(annual, 2020, "excess_return") - _year_value(baseline_annual, 2020, "excess_return")
    excess_2023_gain = _year_value(annual, 2023, "excess_return") - _year_value(baseline_annual, 2023, "excess_return")
    excess_2025_gain = _year_value(annual, 2025, "excess_return") - _year_value(baseline_annual, 2025, "excess_return")
    return_2022_gain = _year_value(annual, 2022, "total_return") - _year_value(baseline_annual, 2022, "total_return")
    return_2024_gain = _year_value(annual, 2024, "total_return") - _year_value(baseline_annual, 2024, "total_return")

    dd_penalty = 0.0
    if dd_change > 0.01:
        dd_penalty += 10.0 * (dd_change - 0.01)

    score = (
        10.0 * excess_2020_gain
        + 12.0 * excess_2023_gain
        + 4.0 * excess_2025_gain
        + 5.0 * return_2022_gain
        + 3.0 * return_2024_gain
        + 1.10 * sharpe_gain
        + 0.80 * calmar_gain
        + 0.0002 * final_equity_gain
        - dd_penalty
    )
    return {
        "score": float(score),
        "sharpe_gain": float(sharpe_gain),
        "calmar_gain": float(calmar_gain),
        "final_equity_gain": float(final_equity_gain),
        "excess_2020_gain": float(excess_2020_gain),
        "excess_2023_gain": float(excess_2023_gain),
        "excess_2025_gain": float(excess_2025_gain),
        "return_2022_gain": float(return_2022_gain),
        "return_2024_gain": float(return_2024_gain),
        "max_drawdown_change": float(dd_change),
        "drawdown_penalty": float(dd_penalty),
    }


def _candidate_specs() -> list[dict[str, object]]:
    return [
        {"name": "baseline_short_slightly_freer", "note": "当前窄校准基线", "param": {}, "execution": {}},
        {
            "name": "long_freer_probe",
            "note": "降低 long floor 并放宽 weak long 权限",
            "param": {
                "long_quality_floor": 0.21,
                "long_permission_scale": 1.10,
                "long_weak_permission_multiplier": 0.92,
                "long_min_permission": 0.14,
                "long_continuation_threshold": 0.61,
            },
            "execution": {},
        },
        {
            "name": "long_neutral_push",
            "note": "中性日线下提高 long 参与度",
            "param": {
                "long_neutral_bias_scale": 0.98,
                "long_permission_scale": 1.08,
                "long_weak_permission_multiplier": 0.90,
                "long_min_permission": 0.14,
                "long_continuation_threshold": 0.60,
            },
            "execution": {},
        },
        {
            "name": "long_continuation_push",
            "note": "更容易从 probe 升到 confirmed long",
            "param": {
                "long_quality_floor": 0.22,
                "long_permission_scale": 1.16,
                "long_weak_permission_multiplier": 0.94,
                "long_min_permission": 0.13,
                "long_continuation_threshold": 0.58,
            },
            "execution": {},
        },
        {
            "name": "long_trend_capture",
            "note": "整体抬高 long 趋势参与，但保留 short 现状",
            "param": {
                "long_neutral_bias_scale": 1.00,
                "long_quality_floor": 0.20,
                "long_permission_scale": 1.18,
                "long_weak_permission_multiplier": 0.96,
                "long_min_permission": 0.12,
                "long_continuation_threshold": 0.57,
            },
            "execution": {},
        },
        {
            "name": "long_balanced_capture",
            "note": "long 放宽同时略收 range，防止收益被噪音吃掉",
            "param": {
                "long_neutral_bias_scale": 0.98,
                "long_quality_floor": 0.21,
                "long_permission_scale": 1.14,
                "long_weak_permission_multiplier": 0.94,
                "long_min_permission": 0.13,
                "long_continuation_threshold": 0.59,
                "range_block_tradability_threshold": 0.73,
                "range_block_trend_quality_threshold": 0.60,
                "range_base_permission_floor": 0.17,
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
    btc_annual = _btc_annual_returns(market, args.start, args.end)

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
        "btc_annual": btc_annual.to_dict(orient="records"),
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
        score = _score(metrics, baseline_metrics, annual, baseline_annual, btc_annual)
        annual_with_btc = annual.merge(btc_annual, on="year", how="left")
        annual_with_btc["excess_return"] = annual_with_btc["total_return"] - annual_with_btc["btc_total_return"]
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
                "excess_2020": _year_value(annual_with_btc, 2020, "excess_return"),
                "excess_2023": _year_value(annual_with_btc, 2023, "excess_return"),
                "excess_2025": _year_value(annual_with_btc, 2025, "excess_return"),
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
            "annual_with_btc": annual_with_btc.to_dict(orient="records"),
            "score": score,
        }
        equity_curves[spec["name"]] = result.equity.rename(spec["name"])

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    summary.to_csv(output / "summary_metrics.csv", index=False)
    pd.concat(equity_curves.values(), axis=1).to_csv(output / "equity_curves.csv")

    best = summary.iloc[0]
    best_name = str(best["candidate"])
    (output / "best_candidate_params.json").write_text(
        json.dumps(details["candidates"][best_name]["params"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
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
