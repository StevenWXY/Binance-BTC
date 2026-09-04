#!/usr/bin/env python3
"""Validate V4, V4.1 and V4.2 under common execution and stress assumptions."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.backtest import BacktestConfig, run_backtest  # noqa: E402
from btc_regime.data import iter_intrabar_months  # noqa: E402
from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest  # noqa: E402
from btc_regime.stress import run_stress_suite, write_stress_report  # noqa: E402
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402
from btc_regime.v42 import (  # noqa: E402
    V42CapitalParams,
    combine_direction_and_neutral,
    generate_neutral_sleeve,
)


MARKET_PATH = ROOT / "reports/annual_2020_2026_08_25/market_4h_full.csv"
FUNDING_PATH = ROOT / "reports/annual_2020_2026_08_25/funding_full.csv"
STRATEGIES = {
    "V4": ROOT / "configs/aggressive_adaptive_v3_params.json",
    "V4.1": ROOT / "configs/v4_refined_params.json",
    "V4.2": ROOT / "configs/v4_2_params.json",
}


def _read(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index, utc=True, format="mixed")
    return frame.sort_index()


def _metric(metrics: dict[str, float], key: str) -> float | None:
    value = metrics.get(key)
    return float(value) if value is not None else None


def _summary_row(code: str, layer: str, metrics: dict[str, float]) -> dict[str, object]:
    fields = [
        "final_equity",
        "total_return",
        "cagr",
        "sharpe",
        "sortino",
        "max_drawdown",
        "trade_count",
        "fill_count",
        "fees_paid",
        "funding_paid",
        "liquidation_count",
        "max_leverage_observed",
        "max_margin_ratio",
        "minimum_margin_buffer",
    ]
    return {
        "code": code,
        "layer": layer,
        **{field: _metric(metrics, field) for field in fields},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-25 08:00")
    parser.add_argument("--fee-bps", type=float, default=4.0)
    parser.add_argument("--slippage-bps", type=float, default=1.0)
    parser.add_argument("--impact-bps", type=float, default=8.0)
    parser.add_argument("--participation", type=float, default=0.02)
    parser.add_argument("--stress-repeats", type=int, default=2)
    parser.add_argument("--stress-seed", type=int, default=100)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "reports/v4_family_validation_2026_09_02"
    )
    args = parser.parse_args()

    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    market = _read(MARKET_PATH).loc[
        lambda frame: (frame.index >= start) & (frame.index < end)
    ]
    funding = _read(FUNDING_PATH).loc[
        lambda frame: (frame.index >= start) & (frame.index < end)
    ]
    funding_4h = funding["funding_rate"].groupby(funding.index.floor("4h")).sum()
    market["funding_rate"] = funding_4h.reindex(market.index, fill_value=0.0)

    backtest_config = BacktestConfig(
        initial_cash=10_000.0,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
    )
    micro_config = MicroBacktestConfig(
        initial_cash=10_000.0,
        taker_fee_bps=args.fee_bps,
        base_slippage_bps=args.slippage_bps,
        impact_bps=args.impact_bps,
        max_minute_participation=args.participation,
        liquidation_fee_bps=50.0,
    )
    summary_rows: list[dict[str, object]] = []
    report: dict[str, object] = {
        "data": {"start": start.isoformat(), "end": end.isoformat()},
        "execution": asdict(micro_config),
        "strategies": {},
    }

    direction_results: dict[str, tuple[pd.DataFrame, object]] = {}
    for code, params_path in STRATEGIES.items():
        params = StrategyParams(**json.loads(params_path.read_text(encoding="utf-8")))
        signaled = generate_signals(market, params)
        shifted = signaled.copy()
        shifted.index = shifted.index + pd.Timedelta(hours=4)
        four_hour = run_backtest(shifted, backtest_config)
        # Each run gets a fresh archive iterator; the iterator is consumed in-place.
        minute = run_micro_backtest(
            signaled,
            iter_intrabar_months(ROOT / "data/raw", start=args.start, end=args.end),
            funding,
            micro_config,
        )
        direction_results[code] = (signaled, minute)
        summary_rows.extend(
            [
                _summary_row(code, "4h_direction", four_hour.metrics),
                _summary_row(code, "1m_direction", minute.metrics),
            ]
        )
        report["strategies"][code] = {
            "params": params.to_dict(),
            "four_hour": four_hour.metrics,
            "micro": minute.metrics,
        }

    v42_signaled, v42_minute = direction_results["V4.2"]
    capital_params = V42CapitalParams()
    neutral = generate_neutral_sleeve(funding, capital_params)
    direction_signal = v42_signaled["signal"].copy()
    direction_signal.index = direction_signal.index + pd.Timedelta(hours=4)
    combined, combined_metrics = combine_direction_and_neutral(
        v42_minute.equity, neutral, capital_params, direction_signal
    )
    summary_rows.append(_summary_row("V4.2", "1m_combined_neutral", combined_metrics))
    report["v4_2_capital_overlay"] = {
        "params": capital_params.to_dict(),
        "neutral_metrics": {
            "final_multiple": float(neutral["neutral_equity"].iloc[-1]),
            "total_return": float(neutral["neutral_equity"].iloc[-1] - 1.0),
            "max_drawdown": float(neutral["drawdown"].min()),
            "active_fraction": float(neutral["active"].mean()),
            "state_change_count": int(neutral["state_changed"].sum()),
        },
        "combined_metrics": combined_metrics,
        "minimum_estimated_free_margin": float(
            combined["estimated_free_margin_next"].min()
        ),
        "average_neutral_allocation": float(combined["neutral_allocation"].mean()),
        "recall_state_counts": {
            str(key): int(value)
            for key, value in combined["neutral_recall_state"].value_counts().items()
        },
    }

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame.from_records(summary_rows)
    summary.to_csv(output / "summary.csv", index=False)
    combined.to_csv(output / "v4_2_combined_equity.csv")
    stress_reports: dict[str, object] = {}
    for code, params_path in STRATEGIES.items():
        stress = run_stress_suite(
            json.loads(params_path.read_text(encoding="utf-8")),
            engine="strategy",
            repeats=args.stress_repeats,
            seed=args.stress_seed,
        )
        stress_dir = output / f"stress_{code.lower().replace('.', '')}"
        write_stress_report(stress, stress_dir)
        stress_reports[code] = {
            "aggregate": stress.metadata["aggregate"],
            "summary": stress.summary.to_dict(orient="records"),
        }
    report["stress"] = stress_reports
    report["summary"] = summary.to_dict(orient="records")
    report["method"] = {
        "direction": "common 4 bps taker fee, 1 bps base slippage, 8 bps impact, 2% minute participation",
        "v4_2_neutral": "causal settled-funding overlay with dynamic recall/redeployment",
        "stress": "deterministic synthetic 4h scenarios expanded into 1m paths; strategy engine has no explicit stop/take columns",
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(summary.to_string(index=False))
    print(
        json.dumps(
            {"output": str(output), "stress": stress_reports},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
