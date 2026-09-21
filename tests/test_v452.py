from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from btc_regime.v444 import generate_v444_signals
from btc_regime.v451 import generate_v451_signals
from btc_regime.v452 import RISK_PROFILES, V452Params, generate_v452_signals, signal_candidates, v451_control


def market(n=6000):
    rng = np.random.default_rng(452)
    close = 100 * np.exp(np.cumsum(rng.normal(-.0002, .008, n)))
    op = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"open": op, "close": close, "high": np.maximum(close, op) * 1.003,
                         "low": np.minimum(close, op) * .997, "volume": 1e5,
                         "quote_volume": 1e7 * np.exp(rng.normal(0, .7, n)),
                         "funding_rate": 0., "funding_event": False},
                        index=pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC"))


def test_v451_control_exact_trade_targets():
    data = market()
    previous = generate_v451_signals(data)
    control = generate_v452_signals(data, v451_control())
    for col in ["signal", "stop_price", "take_profit_price"]:
        pd.testing.assert_series_equal(previous[col], control[col])
    assert (previous.cycle_id.str.replace("v451_short", "v452_short") == control.cycle_id).all()


@pytest.mark.parametrize("p", [V452Params(), V452Params(gate="hybrid", entry="mixed", confirmation="strength", risk="higher"),
                                V452Params(entry="break8", confirmation="activity", protection="tight", risk="elevated")])
def test_causal_long_priority_short_caps_and_protection(p):
    data = market()
    whole = generate_v452_signals(data, p)
    prefix = generate_v452_signals(data.iloc[:5802], p)
    pd.testing.assert_frame_equal(prefix, whole.iloc[:5802])
    core = generate_v444_signals(data)
    cols = ["signal", "stop_price", "take_profit_price", "cycle_id"]
    pd.testing.assert_frame_equal(whole.loc[core.signal.gt(0), cols], core.loc[core.signal.gt(0), cols])
    shorts = whole.loc[whole.signal.lt(0)]
    assert len(shorts) > 0
    assert whole.signal.max() <= 4
    assert shorts.signal.min() >= -RISK_PROFILES[p.risk][0]
    for _, group in shorts.groupby("cycle_id"):
        assert group.stop_price.diff().dropna().le(1e-10).all()
        assert group.signal.nunique() == 1


def test_risk_budget_changes_size_without_changing_signals():
    data = market()
    base = generate_v452_signals(data, v451_control())
    bigger = generate_v452_signals(data, replace(v451_control(), risk="higher"))
    pd.testing.assert_series_equal(base.cycle_id, bigger.cycle_id)
    pd.testing.assert_series_equal(base.stop_price, bigger.stop_price)
    assert base.signal.lt(0).equals(bigger.signal.lt(0))
    short = base.signal.lt(0)
    assert (bigger.signal[short].abs() >= base.signal[short].abs()).all()
    assert bigger.signal[short].abs().mean() > base.signal[short].abs().mean() * 1.4


def test_grid_and_validation():
    grid = signal_candidates()
    assert len(grid) == len({tuple(p.to_dict().items()) for p in grid}) == 72
    with pytest.raises(ValueError):
        V452Params(risk="unbounded")
