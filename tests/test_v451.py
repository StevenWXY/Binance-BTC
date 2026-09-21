from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from btc_regime.v444 import generate_v444_signals
from btc_regime.v451 import V451Params, candidates, generate_v451_signals


def market(n=6000):
    rng = np.random.default_rng(451)
    close = 100 * np.exp(np.cumsum(rng.normal(-.0002, .007, n)))
    op = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"open": op, "close": close, "high": np.maximum(close, op) * 1.002,
                         "low": np.minimum(close, op) * .998, "volume": 1e5,
                         "quote_volume": 1e7, "funding_rate": 0., "funding_event": False},
                        index=pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC"))


@pytest.mark.parametrize("p", [V451Params(), V451Params(gate="structural", entry="break24", protection="swing"),
                                V451Params(gate="trend", entry="break12", risk="medium")])
def test_causal_bounded_long_priority(p):
    data = market()
    whole = generate_v451_signals(data, p)
    prefix = generate_v451_signals(data.iloc[:5802], p)
    pd.testing.assert_frame_equal(prefix, whole.iloc[:5802])
    core = generate_v444_signals(data)
    columns = ["signal", "stop_price", "take_profit_price", "cycle_id"]
    pd.testing.assert_frame_equal(whole.loc[core.signal.gt(0), columns], core.loc[core.signal.gt(0), columns])
    shorts = whole.loc[whole.signal.lt(0)]
    assert len(shorts) > 0
    assert whole.signal.max() <= 4
    assert shorts.signal.min() >= (-.75 if p.risk == "small" else -1.25)
    for _, cycle in shorts.groupby("cycle_id"):
        assert cycle.stop_price.diff().dropna().le(1e-10).all()
        assert cycle.signal.nunique() == 1


def test_short_disabled_exact_long_baseline():
    data = market()
    pd.testing.assert_frame_equal(generate_v451_signals(data, V451Params(short_enabled=False)),
                                  generate_v444_signals(data))


def test_grid_and_invalid_params():
    grid = candidates()
    assert len(grid) == 72
    assert len({tuple(p.to_dict().items()) for p in grid}) == 72
    with pytest.raises(ValueError):
        replace(grid[0], risk="leveraged")


def test_mark_stop_cooldown_long_preemption_and_funding_guard():
    data = market(40)
    f = data.copy()
    for key, value in {"open": 99., "close": 99., "high": 99.5, "low": 98.5,
                       "mark_high": 99.5, "mark_low": 98.5, "atr4": 1., "vol": .5,
                       "fast": 101., "slow": 104., "slope": -.01, "minus": 30.,
                       "plus": 10., "adx4": 30., "daily_close": 90., "daily_fast": 95.,
                       "daily_slow": 100., "daily_slope": -.01, "rsi": 40.,
                       "known_funding": 0., "vol_ratio": 1.2, "entry_ema": 100.}.items():
        f[key] = value
    for i in [10, 12, 20, 29]:
        f.loc[f.index[i-1], ["open", "close", "high", "mark_high"]] = [101., 101., 101.5, 101.5]
        f.loc[f.index[i], ["open", "high", "mark_high"]] = [100., 100.5, 100.5]
    f.loc[f.index[11], "mark_high"] = 102.
    f.loc[f.index[29], "known_funding"] = -.0003
    core = pd.DataFrame({"signal": 0., "stop_price": np.nan, "take_profit_price": np.nan,
                         "cycle_id": "v444_0"}, index=f.index)
    core.loc[f.index[21], ["signal", "stop_price", "cycle_id"]] = [1., 95., "v444_1"]
    params = V451Params(gate="tactical", entry="reject", risk="small", adx_min=24.)
    out = generate_v451_signals(data, params, prepared=f, long_signals=core)
    assert out.signal.iloc[10] < 0
    assert out.signal.iloc[11:20].eq(0).all()
    assert out.signal.iloc[20] < 0
    assert out.cycle_id.iloc[20] != out.cycle_id.iloc[10]
    assert out.signal.iloc[21] == 1.
    assert out.signal.iloc[22:].eq(0).all()
