#!/usr/bin/env python3
"""Compare main, xuyujian, and wzy strategies under one execution basis."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.data import iter_intrabar_months, load_funding, load_market_data  # noqa: E402
from btc_regime.micro_backtest import (  # noqa: E402
    MicroBacktestConfig,
    micro_period_metrics,
    run_micro_backtest,
)
from btc_regime.v43 import V43Params, generate_v43_signals  # noqa: E402
from btc_regime.v71_live import V71LiveParams, generate_v71_live_signals  # noqa: E402


DEFAULT_OUTPUT = ROOT / "reports/three_branch_same_basis"
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


def _result_payload(
    code: str,
    name: str,
    result: object,
    params: object,
) -> dict[str, object]:
    return {
        "code": code,
        "strategy": name,
        "params": params.to_dict(),
        "metrics": result.metrics,
        "periods": micro_period_metrics(result),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument("--execution", type=Path, default=DEFAULT_EXECUTION)
    parser.add_argument("--main-params", type=Path, default=DEFAULT_MAIN_PARAMS)
    parser.add_argument("--x-params", type=Path, default=DEFAULT_X_PARAMS)
    parser.add_argument("--wzy-params", type=Path, default=DEFAULT_WZY_PARAMS)
    parser.add_argument("--wzy-code", default="wzy_v71_live")
    parser.add_argument("--wzy-name", default="wzy: V7.1 live conservative")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    execution = MicroBacktestConfig(**_read_json(args.execution))
    market = _load_market(args.raw_dir, args.start, args.end)
    funding = load_funding(args.raw_dir, start=args.start, end=args.end)

    main_params = V43Params(**_read_json(args.main_params))
    x_params = V71LiveParams(**_read_json(args.x_params))
    wzy_params = V71LiveParams(**_read_json(args.wzy_params))

    runs = [
        ("main_v43", "main: V4.3 maker/protection", generate_v43_signals(market, main_params), main_params),
        (
            "xuyujian_v71_ref",
            "xuyujian: V7.1 reference",
            generate_v71_live_signals(market, x_params),
            x_params,
        ),
        (
            args.wzy_code,
            args.wzy_name,
            generate_v71_live_signals(market, wzy_params),
            wzy_params,
        ),
    ]

    summary_rows: list[dict[str, object]] = []
    report: dict[str, object] = {
        "data": {
            "start": pd.Timestamp(args.start, tz="UTC").isoformat(),
            "end": pd.Timestamp(args.end, tz="UTC").isoformat(),
            "raw_dir": str(args.raw_dir),
        },
        "execution": asdict(execution),
        "strategies": {},
    }
    equity_curves: dict[str, pd.Series] = {}

    for code, name, signaled, params in runs:
        result = run_micro_backtest(
            signaled.loc[signaled.index < pd.Timestamp(args.end, tz="UTC")],
            iter_intrabar_months(args.raw_dir, start=args.start, end=args.end),
            funding,
            execution,
        )
        equity_curves[code] = result.equity.rename(code)
        metrics = result.metrics
        summary_rows.append(
            {
                "code": code,
                "strategy": name,
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
            }
        )
        report["strategies"][code] = _result_payload(code, name, result, params)

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame(summary_rows).sort_values("sharpe", ascending=False)
    summary.to_csv(output / "summary_metrics.csv", index=False)
    pd.concat(equity_curves.values(), axis=1).to_csv(output / "equity_curves.csv")
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
