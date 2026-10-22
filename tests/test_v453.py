import pandas as pd

from btc_regime.v452 import V452Params, generate_v452_signals
from btc_regime.v453 import V453Params, generate_v453_signals


def market(n=800):
    close = pd.Series(100.0, index=pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC"))
    frame = pd.DataFrame({"open": close, "high": close * 1.001, "low": close * .999,
                          "close": close, "volume": 1e5, "quote_volume": 1e7,
                          "funding_rate": 0., "funding_event": False}, index=close.index)
    return frame


def test_v453_signal_is_exact_v452_signal():
    data = market()
    old = generate_v452_signals(data, V452Params())
    new = generate_v453_signals(data, V453Params())
    pd.testing.assert_frame_equal(old, new)


def test_v453_future_price_mutation_does_not_change_prefix():
    data = market(1_000)
    cut = 700
    original = generate_v453_signals(data, V453Params())
    changed = data.copy()
    changed.loc[changed.index[cut]:, ["open", "high", "low", "close"]] *= 3.0
    changed.loc[changed.index[cut]:, ["volume", "quote_volume"]] = 1.0
    changed.loc[changed.index[cut]:, "funding_rate"] = 0.0
    modified = generate_v453_signals(changed, V453Params())
    pd.testing.assert_frame_equal(
        original.iloc[:cut][["signal", "stop_price", "take_profit_price", "cycle_id"]],
        modified.iloc[:cut][["signal", "stop_price", "take_profit_price", "cycle_id"]],
    )
