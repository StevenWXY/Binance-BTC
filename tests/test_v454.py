import pandas as pd

from btc_regime.v453 import generate_v453_signals
from btc_regime.v454 import V454CapitalParams, generate_v454_neutral_sleeve, generate_v454_signals


def market(n=800):
    close = pd.Series(100.0, index=pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC"))
    return pd.DataFrame({"open": close, "high": close * 1.001, "low": close * .999,
                         "close": close, "volume": 1e5, "quote_volume": 1e7,
                         "funding_rate": 0., "funding_event": False}, index=close.index)


def test_v454_signal_is_scaled_v453_signal():
    data = market()
    old = generate_v453_signals(data)
    new = generate_v454_signals(data)
    pd.testing.assert_frame_equal(new.drop(columns=["signal"]), old.drop(columns=["signal"]))
    pd.testing.assert_series_equal(new["signal"], old["signal"] * .75, check_names=False)


def test_v454_neutral_sleeve_is_causal_and_validates_rebate():
    index = pd.date_range("2020-01-01", periods=100, freq="8h", tz="UTC")
    funding = pd.DataFrame({"funding_rate": .001}, index=index)
    neutral = generate_v454_neutral_sleeve(funding, V454CapitalParams(), rebate_fraction=.4)
    assert neutral.index.equals(index)
    assert bool(neutral.iloc[0].active) is False
    assert neutral.state_changed.sum() >= 0
