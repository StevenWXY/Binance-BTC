import numpy as np
import pandas as pd
import pytest

from btc_regime.v443 import V443Params, candidates, generate_v443_signals


def market(n=3000):
    rng = np.random.default_rng(443)
    close = 100 * np.exp(np.cumsum(rng.normal(.0002, .007, n)))
    op = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"open": op, "close": close, "high": np.maximum(close, op) * 1.002,
                         "low": np.minimum(close, op) * .998, "volume": 1e5,
                         "quote_volume": 1e7, "funding_rate": 0., "funding_event": False},
                        index=pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC"))


@pytest.mark.parametrize("p", [V443Params(), V443Params(speed="fast", entry_mode="breakout", hold_hours=24),
                                V443Params(stop_atr=1.5, trail_atr=2.5, entry_mode="reclaim")])
def test_v443_causal_and_bounded(p):
    data = market()
    whole = generate_v443_signals(data, p)
    prefix = generate_v443_signals(data.iloc[:2802], p)
    pd.testing.assert_frame_equal(prefix, whole.iloc[:2802])
    assert whole.signal.min() >= 0
    assert whole.signal.max() <= p.max_leverage


def test_registered_frequency_grid():
    grid = candidates()
    assert len(grid) == 162
    assert len({tuple(p.to_dict().items()) for p in grid}) == 162


def test_invalid_frequency_controls():
    with pytest.raises(ValueError):
        V443Params(cooldown_hours=-1)
    with pytest.raises(ValueError):
        V443Params(max_leverage=4.1)
