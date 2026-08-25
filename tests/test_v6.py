import numpy as np
import pandas as pd

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v6 import V6Params, generate_v6_signals


def synthetic_market(n: int = 600) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=n, freq="4h", tz="UTC")
    close = 100 * np.exp(np.cumsum(np.full(n, 0.0004)))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.006,
            "low": close * 0.994,
            "close": close,
            "volume": 1.0,
            "quote_volume": 100.0,
            "funding_rate": 0.0,
        },
        index=index,
    )


def test_v6_is_bounded_and_causal() -> None:
    data = synthetic_market()
    params = V6Params(max_leverage=3.0)
    original = generate_v6_signals(data, params)
    changed = data.copy()
    changed.loc[changed.index[450]:, ["open", "high", "low", "close"]] *= 3
    modified = generate_v6_signals(changed, params)
    assert original["signal"].abs().max() <= 3.0 + 1e-12
    assert original.index.equals(data.index)
    pd.testing.assert_series_equal(original["signal"].iloc[:450], modified["signal"].iloc[:450])
    assert {"entry_price", "stop_price", "take_profit_price", "signal_confidence"}.issubset(original)


def test_micro_engine_honors_v6_stop_price() -> None:
    signal_index = pd.DatetimeIndex([pd.Timestamp("2024-01-01 00:00", tz="UTC")])
    signaled = pd.DataFrame(
        {"signal": [1.0], "stop_price": [95.0], "take_profit_price": [110.0]},
        index=signal_index,
    )
    minute_index = pd.DatetimeIndex(
        [
            pd.Timestamp("2024-01-01 04:00", tz="UTC"),
            pd.Timestamp("2024-01-01 04:01", tz="UTC"),
            pd.Timestamp("2024-01-01 07:59", tz="UTC"),
        ]
    )
    minute = pd.DataFrame(
        {
            "trade_open": [100.0, 100.0, 95.0],
            "trade_high": [101.0, 100.0, 96.0],
            "trade_low": [99.0, 90.0, 94.0],
            "trade_close": [100.0, 95.0, 95.0],
            "trade_volume": [100_000.0] * 3,
            "trade_quote_volume": [10_000_000.0] * 3,
            "mark_open": [100.0, 100.0, 95.0],
            "mark_high": [101.0, 100.0, 96.0],
            "mark_low": [99.0, 90.0, 94.0],
            "mark_close": [100.0, 95.0, 95.0],
        },
        index=minute_index,
    )
    funding = pd.DataFrame({"funding_rate": pd.Series(dtype=float)}, index=pd.DatetimeIndex([], tz="UTC"))
    result = run_micro_backtest(signaled, [minute], funding, MicroBacktestConfig())
    assert result.metrics["liquidation_count"] == 0
    assert (result.fills["reason"] == "stop_loss").any()
