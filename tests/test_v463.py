import pandas as pd

from btc_regime.v453 import V453Params
from btc_regime.v463 import V463Params, generate_v463_signals


def market(n=1_500):
    close = pd.Series(100.0, index=pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC"))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "close": close,
            "volume": 1e5,
            "quote_volume": 1e7,
            "funding_rate": 0.0,
            "funding_event": False,
        },
        index=close.index,
    )


def test_v463_defaults_are_bounded_overlay_changes():
    params = V463Params(base=V453Params())
    assert params.exposure_scale == 1.0
    assert params.monthly_soft_loss == -0.10
    assert params.monthly_hard_loss == -0.15
    assert params.soft_loss_scale == 0.50
    assert params.hard_loss_scale == 0.50
    assert params.profit_lock_scale == 0.35


def test_v463_is_causal_and_keeps_flat_market_flat():
    data = market()
    data.loc[data.index[1_000]:, ["open", "high", "low", "close"]] *= 0.85
    params = V463Params(base=V453Params())
    original = generate_v463_signals(data, params)
    changed = data.copy()
    changed.loc[changed.index[1_200]:, ["open", "high", "low", "close"]] *= 2
    modified = generate_v463_signals(changed, params)
    pd.testing.assert_series_equal(
        original.stable_risk_multiplier.iloc[:1_200],
        modified.stable_risk_multiplier.iloc[:1_200],
        check_names=False,
    )
    flat = generate_v463_signals(market(), params)
    assert flat.signal.eq(0).all()
    assert flat.v463_source.eq("flat").all()
