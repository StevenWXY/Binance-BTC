import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from btc_regime.backtest import run_backtest
from btc_regime.cli import _parse_args
from btc_regime.strategy import StrategyParams, generate_signals
from btc_regime.v73_hf import V73HFParams, generate_v73_hf_signals


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


def test_v73_hf_config_and_signal_are_causal() -> None:
    params = V73HFParams(**json.loads((ROOT / "configs/v73_hf_params.json").read_text()))
    data = oscillating_market()
    original = generate_v73_hf_signals(data, params)
    changed = data.copy()
    changed.loc[changed.index[350]:, ["open", "high", "low", "close"]] *= 1.15
    modified = generate_v73_hf_signals(changed, params)
    pd.testing.assert_series_equal(original["signal"].iloc[:350], modified["signal"].iloc[:350])
    assert original["signal"].abs().max() <= params.max_leverage + 1e-12
    assert {"stop_price", "take_profit_price", "v73_hf_mode"}.issubset(original.columns)


def test_v73_hf_trades_more_often_than_base_strategy_on_chop() -> None:
    data = oscillating_market()
    baseline = run_backtest(generate_signals(data, StrategyParams()))
    signaled = generate_v73_hf_signals(data, V73HFParams())
    hf = run_backtest(signaled)
    assert (signaled["signal"] > 0).any()
    assert (signaled["signal"] < 0).any()
    assert hf.metrics["rebalance_events"] > baseline.metrics["rebalance_events"]
    assert hf.metrics["turnover_multiple"] > baseline.metrics["turnover_multiple"]


def test_v73_hf_cli_command_defaults(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["btc-regime", "micro-backtest-v73-hf"])
    args = _parse_args()
    assert args.output == "reports/v7_3_hf_micro"
    assert args.params == "configs/v73_hf_params.json"
    assert args.participation == pytest.approx(0.02)
