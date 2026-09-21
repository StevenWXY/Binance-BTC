from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from btc_regime.v441_r2 import R2Params, candidates, continuation_candidates, generate_r2_signals, route_r2


def market(n=3000):
    rng = np.random.default_rng(442)
    close = 100 * np.exp(np.cumsum(rng.normal(.0002, .007, n)))
    op = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"open": op, "close": close, "high": np.maximum(close, op) * 1.002,
                         "low": np.minimum(close, op) * .998, "volume": 1e5,
                         "quote_volume": 1e7, "funding_rate": 0., "funding_event": False},
                        index=pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC"))


@pytest.mark.parametrize("p", [R2Params(), R2Params(family="pullback", gate="slope"),
                                  R2Params(family="breakout", short=True), R2Params(family="continuation")])
def test_r2_all_families_causal_and_bounded(p):
    data = market()
    whole = generate_r2_signals(data, p)
    prefix = generate_r2_signals(data.iloc[:2802], p)
    pd.testing.assert_frame_equal(prefix, whole.iloc[:2802])
    assert whole.signal.abs().max() <= p.max_leverage
    if p.family != "core":
        assert whole.signal.min() >= -.5
    for _, g in whole.loc[whole.signal.ne(0)].groupby("cycle_id"):
        if p.family != "core":
            direction = np.sign(g.signal.iloc[0])
            assert (g.stop_price.diff().dropna() * direction >= -1e-10).all()


def test_router_discards_stale_satellite_after_core():
    index = pd.date_range("2024-01-01", periods=6, freq="h", tz="UTC")
    core = pd.DataFrame({"signal": [0., 1., 1., 0., 0., 0.], "stop_price": 90.,
                         "take_profit_price": 110., "cycle_id": ["0", "c1", "c1", "0", "0", "0"]}, index=index)
    sat = pd.DataFrame({"signal": [1., 1., 1., 1., 0., 1.], "stop_price": 95.,
                        "take_profit_price": 105., "cycle_id": ["s1", "s1", "s1", "s1", "s1", "s2"]}, index=index)
    combined = route_r2(core, sat, .5)
    assert combined.signal.tolist() == [.5, 1., 1., 0., 0., .5]
    assert combined.stop_price.iloc[1] == 90.
    assert combined.stop_price.iloc[5] == 95.


def test_registered_grid_and_invalid_risk():
    grid = candidates()
    assert len(grid) == 96
    assert len({tuple(p.to_dict().items()) for p in grid}) == 96
    assert len(continuation_candidates()) == 24
    with pytest.raises(ValueError):
        replace(grid[0], max_leverage=10)
    with pytest.raises(ValueError):
        R2Params(family="unknown")


def test_continuation_mark_stop_cooldown_and_fresh_reentry(monkeypatch):
    from btc_regime.v441_r2 import _continuation

    data = market(40)
    f = data.copy()
    f["atr4"], f["entry_ema"] = 1., 100.
    f["close"], f["high"], f["low"], f["mark_low"] = 100., 101., 99., 99.
    f.iloc[10, f.columns.get_loc("mark_low")] = 97.
    f.loc[f.index[11:16], ["close", "high", "mark_low"]] = [102., 103., 101.]
    f.loc[f.index[16:], ["close", "high", "mark_low"]] = [105., 106., 104.]

    def constant_long(four, params):
        return pd.DataFrame({"signal": .5}, index=four.index)

    monkeypatch.setattr("btc_regime.strategy.generate_signals", constant_long)
    out = _continuation(data, f, R2Params(family="continuation"))
    assert out.signal.iloc[3] == .5
    # Trade low did not touch 98, but mark low did. No immediate repeat entry.
    assert out.signal.iloc[10:16].eq(0).all()
    assert out.signal.iloc[16] == .5
    assert out.cycle_id.iloc[16] != out.cycle_id.iloc[9]
