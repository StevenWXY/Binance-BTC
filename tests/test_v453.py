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
