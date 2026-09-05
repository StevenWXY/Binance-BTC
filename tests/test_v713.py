import numpy as np
import pandas as pd

from btc_regime.v713 import V713Params, generate_v713_signals


def synthetic_market(close: np.ndarray) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=len(close), freq="4h", tz="UTC")
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.006,
            "low": close * 0.994,
            "close": close,
            "volume": 1.0,
            "quote_volume": 100_000.0,
            "funding_rate": 0.0,
        },
        index=index,
    )


def test_v713_uses_v421_style_lower_risk_budget() -> None:
    params = V713Params()
    assert params.target_vol == 0.97 * 0.75
    assert params.max_leverage == 6.5 * 0.75


def test_v713_is_causal_and_bounded() -> None:
    close = 100 * np.exp(np.cumsum(np.full(900, 0.001)))
    data = synthetic_market(close)
    params = V713Params(max_leverage=4.875)
    original = generate_v713_signals(data, params)
    changed = data.copy()
    changed.loc[changed.index[700]:, ["open", "high", "low", "close"]] *= 2
    modified = generate_v713_signals(changed, params)
    pd.testing.assert_series_equal(original["signal"].iloc[:700], modified["signal"].iloc[:700])
    assert original["signal"].abs().max() <= params.max_leverage + 1e-12
    assert {"stop_price", "take_profit_price", "v712_downside_trigger"}.issubset(original)
