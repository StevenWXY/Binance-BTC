#!/usr/bin/env python3
"""Compare frozen V4 with the constrained V4.1 refinement on 4h and 1m data."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.backtest import BacktestConfig, run_backtest  # noqa: E402
from btc_regime.data import iter_intrabar_months, load_funding  # noqa: E402
from btc_regime.micro_backtest import (  # noqa: E402
    MicroBacktestConfig,
    micro_period_metrics,
    run_micro_backtest,
    write_micro_report,
)
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402


MARKET_PATH = ROOT / "reports/annual_2020_2026_08_25/market_4h_full.csv"
FUNDING_SNAPSHOT = ROOT / "reports/annual_2020_2026_08_25/funding_full.csv"
BASE_PATH = ROOT / "configs/aggressive_adaptive_v3_params.json"
REFINED_PATH = ROOT / "configs/v4_refined_params.json"
OUTPUT = ROOT / "reports/v4_refined_comparison.json"


def read_market() -> pd.DataFrame:
    market = pd.read_csv(MARKET_PATH, index_col=0, parse_dates=True)
    market.index = pd.to_datetime(market.index, utc=True, format="mixed")
    funding = pd.read_csv(FUNDING_SNAPSHOT, index_col=0)
    funding.index = pd.to_datetime(funding.index, utc=True, format="mixed")
    market["funding_rate"] = funding["funding_rate"].groupby(
        funding.index.floor("4h")
    ).sum().reindex(market.index, fill_value=0.0)
    return market.sort_index()


def four_hour_metrics(params: StrategyParams, market: pd.DataFrame) -> dict[str, dict[str, float]]:
    raw = generate_signals(market, params)
    shifted = raw.copy()
    shifted.index = shifted.index + pd.Timedelta(hours=4)
    config = BacktestConfig(initial_cash=10_000.0, fee_bps=4.0, slippage_bps=1.0)
    periods = {
        "full_2020_2026_07": ("2020-01-01", "2026-08-01"),
        "recent_2026_07_01_2026_08_25": ("2026-07-01", "2026-08-25 08:00"),
    }
    result: dict[str, dict[str, float]] = {}
    for label, (start, end) in periods.items():
        frame = shifted.loc[
            (shifted.index >= pd.Timestamp(start, tz="UTC"))
            & (shifted.index <= pd.Timestamp(end, tz="UTC"))
        ]
        result[label] = run_backtest(frame, config).metrics
    return result


def run_micro(params: StrategyParams, output_dir: Path) -> dict[str, object]:
    raw = generate_signals(
        read_market().loc[lambda x: x.index < pd.Timestamp("2026-08-01", tz="UTC")],
        params,
    )
    funding = load_funding(ROOT / "data/raw", start="2020-01-01", end="2026-08-01")
    config = MicroBacktestConfig(
        initial_cash=10_000.0,
        taker_fee_bps=4.0,
        base_slippage_bps=1.0,
        impact_bps=8.0,
        max_minute_participation=0.02,
        liquidation_fee_bps=50.0,
    )
    result = run_micro_backtest(
        raw,
        iter_intrabar_months(ROOT / "data/raw", start="2020-01-01", end="2026-08-01"),
        funding,
        config,
    )
    write_micro_report(result, params, config, output_dir)
    return {"metrics": result.metrics, "periods": micro_period_metrics(result)}


def main() -> None:
    baseline = StrategyParams(**json.loads(BASE_PATH.read_text(encoding="utf-8")))
    refined = StrategyParams(
        **{
            **baseline.to_dict(),
            "trend_separation_atr": 0.15,
            "funding_factor_scale": 0.30,
            "downside_stress_scale": 0.30,
        }
    )
    REFINED_PATH.write_text(json.dumps(refined.to_dict(), indent=2) + "\n", encoding="utf-8")
    market = read_market()
    summary = {
        "method": "constrained_local_refinement_around_frozen_v4",
        "baseline_config": str(BASE_PATH.relative_to(ROOT)),
        "refined_config": str(REFINED_PATH.relative_to(ROOT)),
        "parameters_changed": {
            "trend_separation_atr": [baseline.trend_separation_atr, refined.trend_separation_atr],
            "funding_factor_scale": [baseline.funding_factor_scale, refined.funding_factor_scale],
            "downside_stress_scale": [baseline.downside_stress_scale, refined.downside_stress_scale],
        },
        "four_hour": {
            "V4": four_hour_metrics(baseline, market),
            "V4.1": four_hour_metrics(refined, market),
        },
        "micro": {
            "V4": run_micro(baseline, ROOT / "reports/v4_refined_micro_baseline"),
            "V4.1": run_micro(refined, ROOT / "reports/v4_refined_micro"),
        },
    }
    OUTPUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
