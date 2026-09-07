#!/usr/bin/env python3
"""Diagnose whether drawdown overlays suppress long participation in bull years."""

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
DEFAULT_OUTPUT = ROOT / "reports/long_bull_suppression_diagnosis_2020_2026_08_01"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_market(raw_dir: Path, start: str, end: str) -> pd.DataFrame:
    requested_start = pd.Timestamp(start, tz="UTC")
    load_start = "2020-01-01" if requested_start > pd.Timestamp("2020-01-01", tz="UTC") else start
    return load_market_data(raw_dir, start=load_start, end=end)


def _signal_long_metrics(signaled: pd.DataFrame) -> pd.DataFrame:
    frame = signaled.copy()
    frame["year"] = frame.index.year
    frame["positive_signal"] = frame["signal"].clip(lower=0)
    rows = []
    for year in (2020, 2023):
        sample = frame.loc[frame["year"] == year]
        if sample.empty:
            continue
        long_rows = sample["signal"] > 0
        rows.append(
            {
                "year": year,
                "long_bar_ratio": float(long_rows.mean()),
                "avg_long_signal": float(sample.loc[long_rows, "signal"].mean()) if long_rows.any() else 0.0,
                "max_long_signal": float(sample.loc[long_rows, "signal"].max()) if long_rows.any() else 0.0,
                "drawdown_brake_bar_ratio": float((sample["v71_drawdown_risk_scale"] < 1.0).mean()),
                "drawdown_brake_long_ratio": float(sample.loc[long_rows, "v71_drawdown_risk_scale"].lt(1.0).mean()) if long_rows.any() else 0.0,
                "avg_drawdown_scale_on_long": float(sample.loc[long_rows, "v71_drawdown_risk_scale"].mean()) if long_rows.any() else 1.0,
            }
        )
    return pd.DataFrame(rows)


def _annual_metrics(result) -> pd.DataFrame:
    rows = []
    years = sorted({ts.year for ts in result.equity.index})
    for year in years:
        start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        end = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        equity = result.equity.loc[(result.equity.index >= start) & (result.equity.index <= end)]
        if len(equity) < 2:
            continue
        rows.append({"year": year, "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1)})
    return pd.DataFrame(rows)


def _run_variant(
    params_dict: dict[str, object],
    execution_dict: dict[str, object],
    market: pd.DataFrame,
    funding: pd.DataFrame,
    minute_batches: list[pd.DataFrame],
    end: str,
) -> tuple[dict[str, float], pd.DataFrame, pd.DataFrame]:
    params = V71LiveParams(**params_dict)
    execution = MicroBacktestConfig(**execution_dict)
    signaled = generate_v71_live_signals(market, params)
    result = run_micro_backtest(
        signaled.loc[signaled.index < pd.Timestamp(end, tz="UTC")],
        minute_batches,
        funding,
        execution,
    )
    return result.metrics, _annual_metrics(result), _signal_long_metrics(signaled.loc[signaled.index < pd.Timestamp(end, tz="UTC")])


def _variants(base_params: dict[str, object], base_execution: dict[str, object]) -> list[dict[str, object]]:
    return [
        {"name": "baseline", "note": "当前 long participation 最优候选", "params": deepcopy(base_params), "execution": deepcopy(base_execution)},
        {
            "name": "no_governor",
            "note": "关闭账户级 governor",
            "params": deepcopy(base_params),
            "execution": {**deepcopy(base_execution), "strategy_drawdown_enabled": False, "strategy_drawdown_recovery_enabled": False},
        },
        {
            "name": "no_price_drawdown",
            "note": "关闭价格回撤刹车",
            "params": {**deepcopy(base_params), "price_drawdown_scale": 1.0},
            "execution": deepcopy(base_execution),
        },
        {
            "name": "no_governor_no_price_drawdown",
            "note": "同时关闭 governor 与价格回撤刹车",
            "params": {**deepcopy(base_params), "price_drawdown_scale": 1.0},
            "execution": {**deepcopy(base_execution), "strategy_drawdown_enabled": False, "strategy_drawdown_recovery_enabled": False},
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

    rows = []
    annual_rows = []
    signal_rows = []
    for variant in _variants(base_params, base_execution):
        metrics, annual, signal_metrics = _run_variant(
            variant["params"],
            variant["execution"],
            market,
            funding,
            minute_batches,
            args.end,
        )
        rows.append(
            {
                "variant": variant["name"],
                "note": variant["note"],
                "final_equity": metrics["final_equity"],
                "total_return": metrics["total_return"],
                "sharpe": metrics["sharpe"],
                "calmar": metrics["calmar"],
                "max_drawdown": metrics["max_drawdown"],
                "trade_count": metrics["trade_count"],
                "governor_max_drawdown_observed": metrics.get("governor_max_drawdown_observed", 0.0),
                "governor_min_scale_observed": metrics.get("governor_min_scale_observed", 1.0),
            }
        )
        annual["variant"] = variant["name"]
        signal_metrics["variant"] = variant["name"]
        annual_rows.append(annual)
        signal_rows.append(signal_metrics)

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame(rows)
    annual_table = pd.concat(annual_rows, ignore_index=True)
    signal_table = pd.concat(signal_rows, ignore_index=True)
    summary.to_csv(output / "summary_metrics.csv", index=False)
    annual_table.to_csv(output / "annual_returns.csv", index=False)
    signal_table.to_csv(output / "signal_long_metrics.csv", index=False)
    payload = {
        "summary": summary.to_dict(orient="records"),
        "annual_returns": annual_table.to_dict(orient="records"),
        "signal_long_metrics": signal_table.to_dict(orient="records"),
    }
    (output / "report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
