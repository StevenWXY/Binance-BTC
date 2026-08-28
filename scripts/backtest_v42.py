#!/usr/bin/env python3
"""Run the V4.2 direction, neutral sleeve, and combined portfolio validation."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from itertools import product
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.data import iter_intrabar_months  # noqa: E402
from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest  # noqa: E402
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402
from btc_regime.v42 import (  # noqa: E402
    V42CapitalParams,
    annual_return_table,
    combine_direction_and_neutral,
    generate_neutral_sleeve,
    neutral_metrics,
)


DEFAULT_MARKET = ROOT / "reports/annual_2020_2026_08_25/market_4h_full.csv"
DEFAULT_FUNDING = ROOT / "reports/annual_2020_2026_08_25/funding_full.csv"
DEFAULT_DIRECTION_PARAMS = ROOT / "configs/v4_2_params.json"
DEFAULT_CAPITAL_PARAMS = ROOT / "configs/v4_2_capital_params.json"
DEFAULT_OUTPUT = ROOT / "reports/v4_2_2020_2026_08_25"


def _read_timeseries(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True, format="mixed")
    return frame.sort_index()


def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
    return json.loads(frame.to_json(orient="records"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", type=Path, default=DEFAULT_MARKET)
    parser.add_argument("--funding", type=Path, default=DEFAULT_FUNDING)
    parser.add_argument("--direction-params", type=Path, default=DEFAULT_DIRECTION_PARAMS)
    parser.add_argument("--capital-params", type=Path, default=DEFAULT_CAPITAL_PARAMS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-25 08:00")
    args = parser.parse_args()

    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    market = _read_timeseries(args.market).loc[lambda x: (x.index >= start) & (x.index < end)]
    funding = _read_timeseries(args.funding).loc[lambda x: (x.index >= start) & (x.index < end)]
    direction_params = StrategyParams(
        **json.loads(args.direction_params.read_text(encoding="utf-8"))
    )
    capital_params = V42CapitalParams(
        **json.loads(args.capital_params.read_text(encoding="utf-8"))
    )

    implied_direction_allocation = direction_params.max_leverage / capital_params.exchange_leverage
    if not abs(implied_direction_allocation - capital_params.direction_allocation) < 1e-12:
        raise ValueError(
            "direction max leverage and exchange leverage do not match the capital allocation"
        )

    signaled = generate_signals(market, direction_params)
    micro_config = MicroBacktestConfig(
        initial_cash=10_000.0,
        taker_fee_bps=2.8,
        base_slippage_bps=1.0,
        impact_bps=8.0,
        max_minute_participation=0.02,
        liquidation_fee_bps=50.0,
    )
    direction_result = run_micro_backtest(
        signaled,
        iter_intrabar_months(ROOT / "data/raw", start=args.start, end=args.end),
        funding,
        micro_config,
    )

    neutral = generate_neutral_sleeve(funding, capital_params)
    effective_signal = signaled["signal"].copy()
    effective_signal.index = effective_signal.index + pd.Timedelta(hours=4)
    combined, combined_metrics = combine_direction_and_neutral(
        direction_result.equity,
        neutral,
        capital_params,
        effective_signal,
    )
    sleeve_metrics = neutral_metrics(neutral)

    combined_annual = annual_return_table(combined["combined_return"])
    direction_annual = annual_return_table(combined["direction_return"])
    neutral_annual = annual_return_table(
        neutral["neutral_return"],
        active=neutral["active"],
        state_changed=neutral["state_changed"],
    )
    sensitivity_rows: list[dict[str, float]] = []
    for entry_7d, entry_30d, exit_7d in product(
        [0.10, 0.12, 0.15],
        [0.04, 0.06, 0.08],
        [0.00, 0.03, 0.05],
    ):
        candidate = replace(
            capital_params,
            entry_7d_annualized=entry_7d,
            entry_30d_annualized=entry_30d,
            exit_7d_annualized=exit_7d,
        )
        candidate_metrics = neutral_metrics(generate_neutral_sleeve(funding, candidate))
        sensitivity_rows.append(
            {
                "entry_7d_annualized": entry_7d,
                "entry_30d_annualized": entry_30d,
                "exit_7d_annualized": exit_7d,
                **candidate_metrics,
            }
        )
    sensitivity = pd.DataFrame(sensitivity_rows)

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    direction_result.equity.rename("direction_equity").to_csv(
        output / "direction_equity.csv", header=True
    )
    neutral.to_csv(output / "neutral_schedule.csv")
    neutral.loc[neutral["state_changed"]].to_csv(output / "neutral_state_changes.csv")
    combined.to_csv(output / "combined_equity.csv")
    direction_annual.to_csv(output / "direction_annual.csv", index=False)
    neutral_annual.to_csv(output / "neutral_annual.csv", index=False)
    combined_annual.to_csv(output / "combined_annual.csv", index=False)
    sensitivity.to_csv(output / "neutral_sensitivity.csv", index=False)

    summary_rows = [
        {"component": "direction", **direction_result.metrics},
        {"component": "neutral_sleeve", **sleeve_metrics},
        {"component": "combined", **combined_metrics},
    ]
    pd.DataFrame(summary_rows).to_csv(output / "summary_metrics.csv", index=False)

    recall_counts = combined["neutral_recall_state"].value_counts()
    configured_minimum_free_margin = (
        1
        - capital_params.neutral_allocation
        - direction_params.max_leverage / capital_params.exchange_leverage
    )
    observed_leverage_free_margin = (
        1
        - capital_params.neutral_allocation
        - direction_result.metrics["max_leverage_observed"]
        / capital_params.exchange_leverage
    )
    payload = {
        "data": {
            "start": direction_result.equity.index[0].isoformat(),
            "end": direction_result.equity.index[-1].isoformat(),
            "market": str(args.market.relative_to(ROOT)),
            "funding": str(args.funding.relative_to(ROOT)),
        },
        "direction": {
            "config": str(args.direction_params.relative_to(ROOT)),
            "parameters": direction_params.to_dict(),
            "execution": micro_config.__dict__,
            "metrics": direction_result.metrics,
        },
        "capital_overlay": {
            "config": str(args.capital_params.relative_to(ROOT)),
            "parameters": capital_params.to_dict(),
            "neutral_metrics": sleeve_metrics,
            "combined_metrics": combined_metrics,
            "minimum_signal_estimated_free_margin": float(
                combined["estimated_free_margin_next"].min()
            ),
            "configured_minimum_free_margin": float(configured_minimum_free_margin),
            "observed_leverage_free_margin": float(observed_leverage_free_margin),
            "average_neutral_allocation": float(combined["neutral_allocation"].mean()),
            "neutral_sensitivity": {
                "candidate_count": int(len(sensitivity)),
                "minimum_cagr": float(sensitivity["cagr"].min()),
                "median_cagr": float(sensitivity["cagr"].median()),
                "maximum_cagr": float(sensitivity["cagr"].max()),
                "worst_max_drawdown": float(sensitivity["max_drawdown"].min()),
            },
            "recall_state_counts": {
                str(label): int(count) for label, count in recall_counts.items()
            },
        },
        "annual": {
            "direction": _records(direction_annual),
            "neutral_sleeve": _records(neutral_annual),
            "combined": _records(combined_annual),
        },
        "method": {
            "direction": "minute execution with mark-price margin checks and funding",
            "neutral": (
                "causal settled-funding proxy; 80% spot-long/perpetual-short notional; "
                "4% idle yield; transition costs included"
            ),
            "combined": (
                "4h return overlay with dynamic neutral allocation decided at the prior boundary"
            ),
            "neutral_exclusions": [
                "spot-perpetual basis PnL",
                "spot order-book depth and partial fills",
                "account transfer latency",
                "tax and product eligibility",
            ],
        },
    }
    (output / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "direction": direction_result.metrics,
                "neutral_sleeve": sleeve_metrics,
                "combined": combined_metrics,
                "configured_minimum_free_margin": configured_minimum_free_margin,
                "observed_leverage_free_margin": observed_leverage_free_margin,
                "average_neutral_allocation": payload["capital_overlay"][
                    "average_neutral_allocation"
                ],
                "recall_state_counts": payload["capital_overlay"]["recall_state_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
