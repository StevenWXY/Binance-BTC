#!/usr/bin/env python3
"""Local scan to improve weak-year behavior of the risk-adjusted candidate."""

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


DEFAULT_PARAMS = ROOT / "configs/v71_final_candidate_risk_adjusted_params.json"
DEFAULT_EXECUTION = ROOT / "configs/v71_final_candidate_risk_adjusted_execution.json"
DEFAULT_OUTPUT = ROOT / "reports/risk_adjusted_weak_year_scan_2020_2026_08_01"


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


def _side_year(result) -> pd.DataFrame:
    trades = result.trades.copy()
    if trades.empty:
        return pd.DataFrame(columns=["year", "side", "trade_count", "total_pnl"])
    trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True)
    trades["year"] = trades["entry_time"].dt.year
    return trades.groupby(["year", "side"])["pnl"].agg(trade_count="count", total_pnl="sum").reset_index()


def _year_value(frame: pd.DataFrame, year: int, column: str, side: str | None = None) -> float:
    sub = frame[frame["year"] == year]
    if side is not None and "side" in frame.columns:
        sub = sub[sub["side"] == side]
    matched = sub[column]
    return float(matched.iloc[0]) if not matched.empty else 0.0


def _candidate_specs() -> list[dict[str, object]]:
    return [
        {"name": "baseline_risk_adjusted", "note": "current risk-adjusted baseline", "params": {}, "execution": {}},
        {
            "name": "cautious_entry",
            "note": "slightly stricter breakout entry for weak years",
            "params": {
                "breakout_buffer_atr": 0.22,
                "trend_confirm_bars": 3,
            },
            "execution": {},
        },
        {
            "name": "cautious_entry_plus_long_quality",
            "note": "stricter entry plus modest long quality gating",
            "params": {
                "breakout_buffer_atr": 0.22,
                "trend_confirm_bars": 3,
                "long_quality_floor": 0.23,
                "long_continuation_threshold": 0.61,
            },
            "execution": {},
        },
        {
            "name": "cautious_entry_quicker_exit",
            "note": "stricter entry with slightly faster long exit",
            "params": {
                "breakout_buffer_atr": 0.22,
                "trend_confirm_bars": 3,
                "trend_exit_confirm_bars": 3,
                "trailing_stop_atr": 1.6,
            },
            "execution": {},
        },
        {
            "name": "long_quality_only",
            "note": "keep entry structure, raise long quality only",
            "params": {
                "long_quality_floor": 0.24,
                "long_continuation_threshold": 0.62,
            },
            "execution": {},
        },
        {
            "name": "range_block_tighter",
            "note": "block more weak range-to-trend transitions",
            "params": {
                "range_block_tradability_threshold": 0.75,
                "range_block_trend_quality_threshold": 0.63,
                "range_min_permission": 0.14,
            },
            "execution": {},
        },
        {
            "name": "weak_year_balance",
            "note": "balanced weak-year patch without changing total risk budget",
            "params": {
                "breakout_buffer_atr": 0.22,
                "trend_confirm_bars": 3,
                "long_quality_floor": 0.23,
                "long_continuation_threshold": 0.61,
                "range_block_tradability_threshold": 0.75,
                "range_block_trend_quality_threshold": 0.63,
            },
            "execution": {},
        },
    ]


def _score(
    metrics: dict[str, float],
    baseline: dict[str, float],
    annual: pd.DataFrame,
    baseline_annual: pd.DataFrame,
    side: pd.DataFrame,
    baseline_side: pd.DataFrame,
) -> dict[str, float]:
    sharpe_gain = metrics["sharpe"] - baseline["sharpe"]
    calmar_gain = metrics["calmar"] - baseline["calmar"]
    dd_change = abs(metrics["max_drawdown"]) - abs(baseline["max_drawdown"])
    ret_2021_gain = _year_value(annual, 2021, "total_return") - _year_value(baseline_annual, 2021, "total_return")
    ret_2024_gain = _year_value(annual, 2024, "total_return") - _year_value(baseline_annual, 2024, "total_return")
    ret_2026_gain = _year_value(annual, 2026, "total_return") - _year_value(baseline_annual, 2026, "total_return")
    ret_2023_gain = _year_value(annual, 2023, "total_return") - _year_value(baseline_annual, 2023, "total_return")
    long_2021_gain = _year_value(side, 2021, "total_pnl", "long") - _year_value(baseline_side, 2021, "total_pnl", "long")
    long_2024_gain = _year_value(side, 2024, "total_pnl", "long") - _year_value(baseline_side, 2024, "total_pnl", "long")
    long_2026_gain = _year_value(side, 2026, "total_pnl", "long") - _year_value(baseline_side, 2026, "total_pnl", "long")

    dd_penalty = 0.0
    if dd_change > 0.005:
        dd_penalty += 10.0 * (dd_change - 0.005)

    trend_penalty = 0.0
    if ret_2023_gain < -0.08:
        trend_penalty += 1.5 * abs(ret_2023_gain + 0.08)

    score = (
        3.0 * sharpe_gain
        + 3.0 * calmar_gain
        + 8.0 * ret_2021_gain
        + 8.0 * ret_2024_gain
        + 10.0 * ret_2026_gain
        + 0.00015 * long_2021_gain
        + 0.00015 * long_2024_gain
        + 0.00015 * long_2026_gain
        - dd_penalty
        - trend_penalty
    )
    return {
        "score": float(score),
        "sharpe_gain": float(sharpe_gain),
        "calmar_gain": float(calmar_gain),
        "return_2021_gain": float(ret_2021_gain),
        "return_2024_gain": float(ret_2024_gain),
        "return_2026_gain": float(ret_2026_gain),
        "return_2023_gain": float(ret_2023_gain),
        "long_2021_pnl_gain": float(long_2021_gain),
        "long_2024_pnl_gain": float(long_2024_gain),
        "long_2026_pnl_gain": float(long_2026_gain),
        "max_drawdown_change": float(dd_change),
        "drawdown_penalty": float(dd_penalty),
        "trend_penalty": float(trend_penalty),
    }


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
    baseline_side = _side_year(baseline_result)

    rows: list[dict[str, object]] = []
    details: dict[str, object] = {
        "data": {"start": args.start, "end": args.end, "raw_dir": str(args.raw_dir)},
        "baseline_params": base_params,
        "baseline_execution": base_execution,
        "baseline_metrics": baseline_metrics,
        "baseline_annual": baseline_annual.to_dict(orient="records"),
        "baseline_side": baseline_side.to_dict(orient="records"),
        "candidates": {},
    }

    for spec in _candidate_specs():
        params = deepcopy(base_params)
        params.update(spec["params"])
        execution = deepcopy(base_execution)
        execution.update(spec["execution"])
        result = _run_candidate(params, execution, market, funding, minute_batches, args.end)
        annual = _annual_metrics(result)
        side = _side_year(result)
        metrics = result.metrics
        score = _score(metrics, baseline_metrics, annual, baseline_annual, side, baseline_side)
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
                "return_2023": _year_value(annual, 2023, "total_return"),
                "return_2024": _year_value(annual, 2024, "total_return"),
                "return_2026": _year_value(annual, 2026, "total_return"),
                "long_2021_pnl": _year_value(side, 2021, "total_pnl", "long"),
                "long_2024_pnl": _year_value(side, 2024, "total_pnl", "long"),
                "long_2026_pnl": _year_value(side, 2026, "total_pnl", "long"),
                **score,
            }
        )
        details["candidates"][spec["name"]] = {
            "note": spec["note"],
            "params": params,
            "execution": execution,
            "metrics": metrics,
            "annual": annual.to_dict(orient="records"),
            "side": side.to_dict(orient="records"),
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
    (output / "report.json").write_text(
        json.dumps(
            {"best_candidate": best_name, "summary": rows, **details},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
