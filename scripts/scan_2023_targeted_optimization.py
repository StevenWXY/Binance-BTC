#!/usr/bin/env python3
"""Targeted optimization around the current 2023 weakness."""

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
DEFAULT_EXECUTION = ROOT / "configs/v71_final_candidate_governor_reentry_execution.json"
DEFAULT_OUTPUT = ROOT / "reports/targeted_2023_optimization_2020_2026_08_01"


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


def _side_pnl_by_year(result) -> pd.DataFrame:
    trades = result.trades.copy()
    if trades.empty:
        return pd.DataFrame(columns=["year", "side", "trade_count", "total_pnl"])
    trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True)
    trades["year"] = trades["entry_time"].dt.year
    grouped = trades.groupby(["year", "side"])["pnl"].agg(trade_count="count", total_pnl="sum").reset_index()
    return grouped


def _year_value(frame: pd.DataFrame, year: int, column: str, side: str | None = None) -> float:
    sub = frame[frame["year"] == year]
    if side is not None and "side" in frame.columns:
        sub = sub[sub["side"] == side]
    matched = sub[column]
    return float(matched.iloc[0]) if not matched.empty else 0.0


def _score(
    metrics: dict[str, float],
    baseline: dict[str, float],
    annual: pd.DataFrame,
    baseline_annual: pd.DataFrame,
    side_year: pd.DataFrame,
    baseline_side_year: pd.DataFrame,
) -> dict[str, float]:
    sharpe_gain = metrics["sharpe"] - baseline["sharpe"]
    calmar_gain = metrics["calmar"] - baseline["calmar"]
    final_equity_gain = metrics["final_equity"] - baseline["final_equity"]
    dd_change = abs(metrics["max_drawdown"]) - abs(baseline["max_drawdown"])
    ret_2023_gain = _year_value(annual, 2023, "total_return") - _year_value(baseline_annual, 2023, "total_return")
    ret_2020_gain = _year_value(annual, 2020, "total_return") - _year_value(baseline_annual, 2020, "total_return")
    ret_2022_gain = _year_value(annual, 2022, "total_return") - _year_value(baseline_annual, 2022, "total_return")
    ret_2024_gain = _year_value(annual, 2024, "total_return") - _year_value(baseline_annual, 2024, "total_return")
    long_2023_gain = _year_value(side_year, 2023, "total_pnl", "long") - _year_value(baseline_side_year, 2023, "total_pnl", "long")
    short_2023_gain = _year_value(side_year, 2023, "total_pnl", "short") - _year_value(baseline_side_year, 2023, "total_pnl", "short")

    dd_penalty = 0.0
    if dd_change > 0.01:
        dd_penalty += 12.0 * (dd_change - 0.01)

    score = (
        16.0 * ret_2023_gain
        + 8.0 * ret_2020_gain
        + 6.0 * ret_2024_gain
        + 5.0 * ret_2022_gain
        + 0.0020 * long_2023_gain
        + 0.0025 * short_2023_gain
        + 1.4 * sharpe_gain
        + 1.2 * calmar_gain
        + 0.0002 * final_equity_gain
        - dd_penalty
    )
    return {
        "score": float(score),
        "sharpe_gain": float(sharpe_gain),
        "calmar_gain": float(calmar_gain),
        "final_equity_gain": float(final_equity_gain),
        "return_2023_gain": float(ret_2023_gain),
        "return_2020_gain": float(ret_2020_gain),
        "return_2022_gain": float(ret_2022_gain),
        "return_2024_gain": float(ret_2024_gain),
        "long_2023_pnl_gain": float(long_2023_gain),
        "short_2023_pnl_gain": float(short_2023_gain),
        "max_drawdown_change": float(dd_change),
        "drawdown_penalty": float(dd_penalty),
    }


def _candidate_specs() -> list[dict[str, object]]:
    return [
        {"name": "baseline_governor_reentry", "note": "当前推荐候选", "params": {}, "execution": {}},
        {
            "name": "short_tighter_release",
            "note": "收紧 short release，减少 2023 错误做空",
            "params": {
                "short_quality_floor": 0.41,
                "short_neutral_bias_scale": 0.60,
                "short_release_threshold": 0.54,
                "short_min_permission": 0.13,
            },
            "execution": {},
        },
        {
            "name": "short_lighter_scale",
            "note": "保留 short 结构，但下调 short 名义暴露",
            "params": {
                "short_scale": 0.08,
                "short_permission_scale": 0.92,
            },
            "execution": {},
        },
        {
            "name": "long_looser_stops",
            "note": "略放 long stop 与 trailing，争取 2023 延续段",
            "params": {
                "stop_atr": 2.0,
                "trailing_stop_atr": 1.9,
                "take_profit_atr": 3.4,
            },
            "execution": {},
        },
        {
            "name": "balanced_2023_combo",
            "note": "短空更谨慎，同时略放 long 持有",
            "params": {
                "short_quality_floor": 0.40,
                "short_neutral_bias_scale": 0.60,
                "short_release_threshold": 0.53,
                "short_scale": 0.09,
                "stop_atr": 1.95,
                "trailing_stop_atr": 1.85,
                "take_profit_atr": 3.4,
            },
            "execution": {},
        },
        {
            "name": "diagnostic_no_short",
            "note": "诊断上界：关闭 short 看 2023 主要缺口有多大",
            "params": {
                "allow_short": False,
                "short_scale": 0.01,
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
    baseline_side_year = _side_pnl_by_year(baseline_result)

    rows: list[dict[str, object]] = []
    details: dict[str, object] = {
        "data": {"start": args.start, "end": args.end, "raw_dir": str(args.raw_dir)},
        "baseline_params": base_params,
        "baseline_execution": base_execution,
        "baseline_metrics": baseline_metrics,
        "baseline_annual": baseline_annual.to_dict(orient="records"),
        "baseline_side_year": baseline_side_year.to_dict(orient="records"),
        "candidates": {},
    }

    for spec in _candidate_specs():
        params = deepcopy(base_params)
        params.update(spec["params"])
        execution = deepcopy(base_execution)
        execution.update(spec["execution"])
        result = _run_candidate(params, execution, market, funding, minute_batches, args.end)
        annual = _annual_metrics(result)
        side_year = _side_pnl_by_year(result)
        metrics = result.metrics
        score = _score(metrics, baseline_metrics, annual, baseline_annual, side_year, baseline_side_year)
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
                "return_2022": _year_value(annual, 2022, "total_return"),
                "return_2023": _year_value(annual, 2023, "total_return"),
                "return_2024": _year_value(annual, 2024, "total_return"),
                "long_2023_pnl": _year_value(side_year, 2023, "total_pnl", "long"),
                "short_2023_pnl": _year_value(side_year, 2023, "total_pnl", "short"),
                **score,
            }
        )
        details["candidates"][spec["name"]] = {
            "note": spec["note"],
            "params": params,
            "execution": execution,
            "metrics": metrics,
            "annual": annual.to_dict(orient="records"),
            "side_year": side_year.to_dict(orient="records"),
            "score": score,
        }

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    summary.to_csv(output / "summary_metrics.csv", index=False)
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
        json.dumps({"best_candidate": best_name, "summary": rows, **details}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
