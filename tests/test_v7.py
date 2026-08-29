import numpy as np
import pandas as pd

from btc_regime.v7 import V7Params, generate_v7_signals


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


def test_v7_is_bounded_and_causal() -> None:
    close = 100 * np.exp(np.cumsum(np.full(700, 0.001)))
    data = synthetic_market(close)
    params = V7Params(max_leverage=3.0)
    original = generate_v7_signals(data, params)
    changed = data.copy()
    changed.loc[changed.index[500]:, ["open", "high", "low", "close"]] *= 2
    modified = generate_v7_signals(changed, params)
    assert original["signal"].abs().max() <= 3.0 + 1e-12
    assert original.index.equals(data.index)
    pd.testing.assert_series_equal(original["signal"].iloc[:500], modified["signal"].iloc[:500])
    assert {
        "v7_market_state",
        "v7_range_percentile",
        "v7_long_allocation_scale",
        "v7_short_allocation_scale",
        "v7_speed_mode",
        "v7_speed_scale",
        "v7_speed_reason",
    }.issubset(original)
    assert set(original["v7_market_state"].dropna().unique()).issubset(
        {"warmup", "range", "trend_up", "trend_down"}
    )


def test_v7_opens_symmetric_short_in_downtrend() -> None:
    close = 200 * np.exp(np.cumsum(np.full(700, -0.0015)))
    data = synthetic_market(close)
    result = generate_v7_signals(data, V7Params(max_leverage=4.0))
    assert (result["signal"] < 0).any()
    assert result.loc[result["signal"] < 0, "regime"].eq("trend_short").all()
    assert result.loc[result["signal"] < 0, "v7_market_state"].eq("trend_down").all()


def test_v7_trend_states_are_directionally_exclusive() -> None:
    up = synthetic_market(100 * np.exp(np.cumsum(np.full(700, 0.0015))))
    down = synthetic_market(200 * np.exp(np.cumsum(np.full(700, -0.0015))))
    up_result = generate_v7_signals(up, V7Params(max_leverage=3.0))
    down_result = generate_v7_signals(down, V7Params(max_leverage=3.0))
    assert (up_result.loc[up_result["v7_market_state"] == "trend_up", "signal"] >= 0).all()
    assert (up_result.loc[up_result["v7_market_state"] == "trend_up", "regime"] != "range_long").all()
    assert (down_result.loc[down_result["v7_market_state"] == "trend_down", "signal"] <= 0).all()
    assert (down_result.loc[down_result["v7_market_state"] == "trend_down", "regime"] != "range_long").all()


def test_v7_short_allocation_uses_upside_as_adverse_volatility() -> None:
    close = 200 * np.exp(np.cumsum(np.full(700, -0.0015)))
    result = generate_v7_signals(synthetic_market(close), V7Params(max_leverage=4.0))
    short_rows = result[result["signal"] < 0]
    assert not short_rows.empty
    assert short_rows["v7_short_allocation_scale"].median() >= short_rows["v7_long_allocation_scale"].median()


def test_v7_range_percentile_entry_and_exit_are_ordered() -> None:
    params = V7Params(adx_enter=80.0, adx_exit=70.0, range_entry_percentile=0.2, range_exit_percentile=0.78)
    assert params.range_entry_percentile < params.range_exit_percentile
    close = 100 + 3 * np.sin(np.linspace(0, 30 * np.pi, 900))
    data = synthetic_market(close)
    result = generate_v7_signals(data, params)
    assert result["v7_range_percentile"].dropna().between(0, 1).all()
    assert (result["regime"] == "range_long").any()
    assert result.loc[result["regime"] == "range_long", "v7_market_state"].eq("range").all()


def test_v7_separates_rapid_and_normal_trend_modes() -> None:
    normal = 100 * np.exp(np.cumsum(np.full(700, 0.0015)))
    rapid = normal.copy()
    rapid[500:] *= 1.08
    params = V7Params(
        max_leverage=3.0,
        rapid_return_threshold=0.03,
        rapid_medium_return_threshold=0.05,
        rapid_rsi_high=60.0,
    )
    normal_result = generate_v7_signals(synthetic_market(normal), params)
    rapid_result = generate_v7_signals(synthetic_market(rapid), params)
    assert (normal_result["v7_speed_mode"] == "normal").any()
    assert (rapid_result["v7_speed_mode"] == "rapid").any()
