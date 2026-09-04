import json

import numpy as np
import pandas as pd

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.stress import (
    generate_stress_intrabar,
    generate_stress_market,
    list_stress_scenarios,
    run_stress_suite,
    write_stress_report,
)
from btc_regime.v6 import V6Params, generate_v6_signals


def test_stress_market_is_reproducible_and_extreme() -> None:
    first = generate_stress_market("flash_crash", bars=80, seed=11)
    second = generate_stress_market("flash_crash", bars=80, seed=11)
    pd.testing.assert_frame_equal(first, second)
    assert first.index.tz is not None
    assert first["low"].min() < first["open"].iloc[40] * 0.7


def test_intrabar_expansion_preserves_boundaries() -> None:
    market = generate_stress_market("gap_down", bars=36, seed=3)
    minute = generate_stress_intrabar(market, "gap_down", seed=3, minutes_per_bar=12)
    assert len(minute) == len(market) * 12
    assert minute.index.is_monotonic_increasing
    np.testing.assert_allclose(minute["trade_open"].iloc[0], market["open"].iloc[0])
    np.testing.assert_allclose(minute["trade_close"].iloc[11], market["close"].iloc[0])
    assert (minute["mark_low"] <= minute["mark_high"]).all()


def test_stress_suite_reports_protection_and_liquidation_fields() -> None:
    result = run_stress_suite(
        V6Params(max_leverage=2.0, target_vol=0.5),
        scenarios=["flash_crash", "stop_take"],
        bars=420,
        seed=5,
    )
    assert set(result.summary["scenario"]) == {"flash_crash", "stop_take"}
    expected = {
        "liquidation_count",
        "unprotected_liquidation_count",
        "max_margin_ratio",
        "minimum_margin_buffer",
        "position_observed",
        "tested_with_position",
        "stop_loss_count",
        "take_profit_count",
        "stop_loss_realized_pnl",
        "take_profit_realized_pnl",
        "drawdown_improvement",
        "survives",
    }
    assert expected.issubset(result.summary.columns)
    assert result.metadata["scenario_count"] == 2
    assert result.metadata["run_count"] == 2
    assert result.metadata["aggregate"]["scenario_survival_rate"] == 1.0
    assert "total_return_std" in result.metadata["aggregate"]
    assert (result.summary["protection_exit_count"] > 0).all()


def test_stress_suite_accepts_legacy_strategy_engine(tmp_path) -> None:
    result = run_stress_suite(
        {"max_leverage": 1.5, "target_vol": 0.2},
        engine="strategy",
        scenarios=["funding_spike"],
        bars=80,
        seed=2,
    )
    assert result.summary.iloc[0]["engine"] == "strategy"
    output = tmp_path / "stress"
    write_stress_report(result, output)
    payload = json.loads((output / "stress_report.json").read_text(encoding="utf-8"))
    assert payload["metadata"]["scenario_count"] == 1
    assert (output / "stress_summary.csv").exists()
    assert (output / "funding_spike__run1_market.csv").exists()


def test_generated_mark_path_can_trigger_existing_liquidation_engine() -> None:
    market = generate_stress_market("flash_crash", bars=64, seed=1)
    signaled = generate_v6_signals(
        market,
        V6Params(max_leverage=6.5, target_vol=1.8, risk_per_trade=0.09),
    )
    minute = generate_stress_intrabar(market, "flash_crash", seed=1, minutes_per_bar=20)
    funding = market[["funding_rate"]]
    result = run_micro_backtest(
        signaled,
        [minute],
        funding,
        MicroBacktestConfig(max_minute_participation=1.0),
    )
    assert "liquidation_count" in result.metrics
    assert result.metrics["final_equity"] >= 0


def test_scenario_catalog_is_stable() -> None:
    assert list_stress_scenarios() == (
        "flash_crash",
        "gap_down",
        "gap_up",
        "volatility_cluster",
        "trend_reversal",
        "funding_spike",
        "liquidity_crunch",
        "stop_take",
    )


def test_repeated_runs_measure_path_stability() -> None:
    result = run_stress_suite(
        V6Params(max_leverage=1.5, target_vol=0.4),
        scenarios=["flash_crash"],
        bars=420,
        seed=9,
        repeats=2,
    )
    assert result.metadata["run_count"] == 2
    assert len(result.summary) == 2
    assert set(result.details) == {"flash_crash__run1", "flash_crash__run2"}
    assert result.metadata["aggregate"]["robust_score_std"] >= 0
