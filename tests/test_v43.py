import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v43 import V43Params, generate_v43_signals
from btc_regime.cli import _parse_args
import sys


ROOT = Path(__file__).resolve().parents[1]


def market(n: int = 520) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    close = 100 * np.exp(np.cumsum(np.full(n, 0.0004)))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": 1_000.0,
            "quote_volume": 1_000_000.0,
            "funding_rate": 0.0,
        },
        index=index,
    )


def test_v43_config_and_signal_are_causal() -> None:
    params = V43Params(**json.loads((ROOT / "configs/v4_3_params.json").read_text()))
    data = market()
    original = generate_v43_signals(data, params)
    changed = data.copy()
    changed.loc[changed.index[400] :, ["open", "high", "low", "close"]] *= 2
    modified = generate_v43_signals(changed, params)
    pd.testing.assert_series_equal(original["signal"].iloc[:400], modified["signal"].iloc[:400])
    assert original["signal"].abs().max() <= params.max_leverage + 1e-12
    assert {"stop_price", "take_profit_price", "v43_downside_trigger"}.issubset(original)


def test_v43_fast_downside_flattens_long_signal() -> None:
    params = V43Params(
        downside_return_threshold=-0.02,
        downside_lookback=2,
        downside_confirmation_bars=1,
    )
    data = market()
    # Keep a long regime, then introduce a confirmed two-bar sell-off.
    data.loc[data.index[300], ["open", "high", "low", "close"]] *= 0.96
    data.loc[data.index[301] :, ["open", "high", "low", "close"]] *= 0.92
    result = generate_v43_signals(data, params)
    triggered = result["v43_downside_trigger"]
    assert triggered.any()
    assert (result.loc[triggered, "signal"] == 0).any()


def test_maker_fill_uses_lower_fee_and_post_only_touch() -> None:
    signal_index = pd.DatetimeIndex([pd.Timestamp("2024-01-01 00:00", tz="UTC")])
    signaled = pd.DataFrame({"signal": [1.0]}, index=signal_index)
    minute_index = pd.DatetimeIndex(
        [
            pd.Timestamp("2024-01-01 04:00", tz="UTC"),
            pd.Timestamp("2024-01-01 04:01", tz="UTC"),
        ]
    )
    minute = pd.DataFrame(
        {
            "trade_open": [100.0, 100.0],
            "trade_high": [101.0, 101.0],
            "trade_low": [99.99, 99.0],  # touches a 0.5 bps buy limit
            "trade_close": [100.0, 100.0],
            "trade_volume": [100_000.0, 100_000.0],
            "trade_quote_volume": [10_000_000.0, 10_000_000.0],
            "mark_open": [100.0, 100.0],
            "mark_high": [101.0, 101.0],
            "mark_low": [99.99, 99.0],
            "mark_close": [100.0, 100.0],
        },
        index=minute_index,
    )
    funding = pd.DataFrame({"funding_rate": []}, index=pd.DatetimeIndex([], tz="UTC"))
    config = MicroBacktestConfig(
        maker_enabled=True,
        maker_fee_bps=0.2,
        maker_offset_bps=0.5,
        taker_fee_bps=4.0,
    )
    result = run_micro_backtest(signaled, [minute], funding, config)
    assert result.metrics["maker_fill_count"] >= 1
    assert (result.fills["liquidity"] == "maker").any()
    assert result.metrics["maker_fee_saved_vs_taker"] > 0


def test_v43_rejects_nonnegative_downside_threshold() -> None:
    with pytest.raises(ValueError):
        V43Params(downside_return_threshold=0.0)


def test_v43_cli_command_defaults(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["btc-regime", "micro-backtest-v43"])
    args = _parse_args()
    assert args.output == "reports/v4_3_micro"
    assert args.maker_fee_bps == pytest.approx(0.2)
