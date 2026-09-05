import numpy as np
import pandas as pd

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v712 import V712Params, generate_v712_signals


def synthetic_market(close: np.ndarray) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=len(close), freq="4h", tz="UTC")
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.006,
            "low": close * 0.994,
            "close": close,
            "volume": 1.0,
            "quote_volume": 100_000.0,
            "funding_rate": 0.0,
        },
        index=index,
    )


def test_v712_adds_causal_protection_levels() -> None:
    close = 100 * np.exp(np.cumsum(np.full(900, 0.001)))
    data = synthetic_market(close)
    original = generate_v712_signals(data, V712Params(max_leverage=3.0))
    changed = data.copy()
    changed.loc[changed.index[700]:, ["open", "high", "low", "close"]] *= 2
    modified = generate_v712_signals(changed, V712Params(max_leverage=3.0))
    pd.testing.assert_series_equal(original["signal"].iloc[:700], modified["signal"].iloc[:700])
    assert {"entry_price", "stop_price", "take_profit_price", "v712_stop_reason"}.issubset(original)
    assert original["signal"].abs().max() <= 3.0 + 1e-12


def test_micro_maker_execution_marks_routine_fill() -> None:
    signal_index = pd.DatetimeIndex([pd.Timestamp("2024-01-01 00:00", tz="UTC")])
    signaled = pd.DataFrame({"signal": [1.0]}, index=signal_index)
    minute_index = pd.DatetimeIndex(
        [pd.Timestamp("2024-01-01 04:00", tz="UTC"), pd.Timestamp("2024-01-01 07:59", tz="UTC")]
    )
    minute = pd.DataFrame(
        {
            "trade_open": [100.0, 100.0], "trade_high": [101.0, 101.0], "trade_low": [99.0, 99.0],
            "trade_close": [100.0, 100.0], "trade_volume": [100_000.0] * 2, "trade_quote_volume": [10_000_000.0] * 2,
            "mark_open": [100.0, 100.0], "mark_high": [101.0, 101.0], "mark_low": [99.0, 99.0], "mark_close": [100.0, 100.0],
        }, index=minute_index,
    )
    funding = pd.DataFrame({"funding_rate": pd.Series(dtype=float)}, index=pd.DatetimeIndex([], tz="UTC"))
    result = run_micro_backtest(
        signaled,
        [minute],
        funding,
        MicroBacktestConfig(maker_enabled=True, maker_fee_bps=0.2, maker_offset_bps=0.0),
    )
    assert (result.fills["liquidity"] == "maker").any()
    assert result.metrics["maker_fill_count"] >= 1
