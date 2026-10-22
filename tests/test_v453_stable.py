import pandas as pd

from btc_regime.v453 import V453Params
from btc_regime.v453_stable import V453StableParams, generate_v453_stable_signals


def market(n=1_200):
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


def test_stable_overlay_preserves_zero_signal_and_columns():
    result = generate_v453_stable_signals(
        market(), V453StableParams(base=V453Params(), exposure_scale=0.25)
    )
    assert result.signal.eq(0).all()
    assert result.leverage.eq(0).all()
    assert {"stable_month_to_date_return", "stable_risk_multiplier", "stable_exposure_scale"} <= set(result)


def test_monthly_risk_multiplier_is_causal_and_bounded():
    data = market(1_500)
    data.loc[data.index[1_000]:, ["open", "high", "low", "close"]] *= 0.85
    params = V453StableParams(
        base=V453Params(),
        exposure_scale=0.25,
        monthly_soft_loss=-0.05,
        monthly_hard_loss=-0.10,
        monthly_profit_lock=0.06,
    )
    original = generate_v453_stable_signals(data, params)
    changed = data.copy()
    changed.loc[changed.index[1_200]:, ["open", "high", "low", "close"]] *= 2
    modified = generate_v453_stable_signals(changed, params)
    pd.testing.assert_series_equal(
        original.stable_risk_multiplier.iloc[:1_200],
        modified.stable_risk_multiplier.iloc[:1_200],
        check_names=False,
    )
    assert original.stable_risk_multiplier.between(0, 1).all()
