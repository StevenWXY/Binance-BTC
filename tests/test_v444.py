import numpy as np
import pandas as pd
import pytest

from btc_regime.v444 import V444Params, candidates, generate_v444_signals
from btc_regime.v443 import V443Params, generate_v443_signals


def market(n=3000):
    rng = np.random.default_rng(444)
    close = 100 * np.exp(np.cumsum(rng.normal(.0002, .007, n)))
    op = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"open": op, "close": close, "high": np.maximum(close, op) * 1.002,
                         "low": np.minimum(close, op) * .998, "volume": 1e5,
                         "quote_volume": 1e7, "funding_rate": 0., "funding_event": False},
                        index=pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC"))


@pytest.mark.parametrize("p", [V444Params(), V444Params(speed="fast", gate="daily_bull"),
                                V444Params(stop_atr=3., entry_mode="reclaim"),
                                V444Params(risk="base")])
def test_v444_causal_and_bounded(p):
    data = market()
    whole = generate_v444_signals(data, p)
    prefix = generate_v444_signals(data.iloc[:2802], p)
    pd.testing.assert_frame_equal(prefix, whole.iloc[:2802])
    assert whole.signal.min() >= 0
    assert whole.signal.max() <= p.max_leverage


def test_registered_grid():
    grid = candidates()
    assert len(grid) == 192
    assert len({tuple(p.to_dict().items()) for p in grid}) == 192


def test_invalid_gate():
    with pytest.raises(ValueError):
        V444Params(gate="calendar")


def test_base_control_matches_v443():
    data = market()
    params = V444Params(risk="base")
    shared = {k: v for k, v in params.to_dict().items() if k not in {"risk", "gate"}}
    old = generate_v443_signals(data, V443Params(**shared))
    control = generate_v444_signals(data, params)
    for column in ["signal", "stop_price", "take_profit_price"]:
        pd.testing.assert_series_equal(old[column], control[column])
