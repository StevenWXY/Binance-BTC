import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from btc_regime.backtest import run_backtest
from btc_regime.cli import _parse_args
from btc_regime.strategy import StrategyParams, generate_signals
from btc_regime.v8_hf import V8HFParams, generate_v8_hf_signals


ROOT = Path(__file__).resolve().parents[1]


def oscillating_market(n: int = 520) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    phase = np.arange(n, dtype=float)
    log_returns = 0.0042 * np.sin(phase / 3.0) + 0.0021 * np.sin(phase / 1.5)
    close_values = 100.0 * np.exp(np.cumsum(log_returns))
    volume_wave = np.clip(1.0 + 0.55 * np.sin(phase / 2.7), a_min=0.2, a_max=None)
    quote_volume = 1_000_000.0 * volume_wave
    range_values = 0.009 + 0.003 * np.cos(phase / 4.5)
    return pd.DataFrame(
        {
            "open": close_values,
            "high": close_values * (1.0 + range_values),
            "low": close_values * (1.0 - range_values),
            "close": close_values,
            "volume": quote_volume / close_values,
            "quote_volume": quote_volume,
            "funding_rate": 0.0,
        },
        index=index,
    )


def burst_market() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=520, freq="4h", tz="UTC")
    log_returns = np.full(520, 0.00015)
    log_returns[120:145] = 0.013
    log_returns[145:165] = 0.003
    log_returns[240:300] = -0.0002
    log_returns[320:345] = -0.013
    log_returns[345:365] = -0.003
    close_values = 100.0 * np.exp(np.cumsum(log_returns))
    quote_volume = np.full(520, 1_000_000.0)
    quote_volume[120:165] = 2_600_000.0
    quote_volume[320:365] = 2_800_000.0
    range_values = np.full(520, 0.008)
    range_values[120:165] = 0.016
    range_values[320:365] = 0.017
    return pd.DataFrame(
        {
            "open": close_values,
            "high": close_values * (1.0 + range_values),
            "low": close_values * (1.0 - range_values),
            "close": close_values,
            "volume": quote_volume / close_values,
            "quote_volume": quote_volume,
            "funding_rate": 0.0,
        },
        index=index,
    )


def test_v8_hf_config_and_signal_are_causal() -> None:
    params = V8HFParams(**json.loads((ROOT / "configs/v8_hf_params.json").read_text()))
    data = oscillating_market()
    original = generate_v8_hf_signals(data, params)
    changed = data.copy()
    changed.loc[changed.index[350]:, ["open", "high", "low", "close"]] *= 1.15
    modified = generate_v8_hf_signals(changed, params)
    pd.testing.assert_series_equal(original["signal"].iloc[:350], modified["signal"].iloc[:350])
    assert original["signal"].abs().max() <= params.max_leverage + 1e-12
    assert {
        "stop_price",
        "take_profit_price",
        "v8_hf_mode",
        "v8_permission_reason",
        "v8_trend_quality_score",
        "v8_direction_context",
    }.issubset(original.columns)


def test_v8_hf_trades_more_often_than_base_strategy_on_chop() -> None:
    data = burst_market()
    baseline = run_backtest(generate_signals(data, StrategyParams()))
    params = V8HFParams(
        trend_adx_enter=14.0,
        trend_adx_exit=10.0,
        breakout_volume_threshold=1.1,
        breakout_quality_min=0.30,
        volatility_cap_ratio=3.0,
    )
    signaled = generate_v8_hf_signals(data, params)
    hf = run_backtest(signaled)
    assert (signaled["signal"] > 0).any()
    assert (signaled["signal"] < 0).any()
    assert hf.metrics["rebalance_events"] >= baseline.metrics["rebalance_events"]
    assert hf.metrics["turnover_multiple"] > baseline.metrics["turnover_multiple"] * 0.5
    assert signaled["v8_hf_mode"].eq("breakout").any()


def test_v8_hf_cli_command_defaults(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["btc-regime", "micro-backtest-v8-hf"])
    args = _parse_args()
    assert args.output == "reports/v8_hf_micro"
    assert args.params == "configs/v8_hf_params.json"
    assert args.participation == pytest.approx(0.02)
    assert args.maker_fee_bps == pytest.approx(0.2)
    assert args.maker_timeout_minutes == 45
