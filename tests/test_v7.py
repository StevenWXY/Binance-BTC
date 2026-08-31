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
        "v7_daily_state",
        "v7_range_percentile",
        "v7_efficiency_ratio",
        "v7_chop",
        "v7_aroon_up",
        "v7_aroon_down",
        "v7_donchian_high",
        "v7_donchian_low",
        "v7_long_allocation_scale",
        "v7_short_allocation_scale",
        "v7_speed_mode",
        "v7_speed_scale",
        "v7_speed_reason",
    }.issubset(original)
    assert set(original["v7_market_state"].dropna().unique()).issubset(
        {"warmup", "range", "trend_up", "trend_down"}
    )
    assert original["v7_efficiency_ratio"].dropna().between(0, 1).all()


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
    params = V7Params(
        adx_enter=80.0,
        adx_exit=70.0,
        range_entry_percentile=0.2,
        range_exit_percentile=0.78,
        efficiency_trend_threshold=0.95,
        efficiency_range_threshold=0.9,
    )
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


def test_v7_breakout_can_flip_out_of_range_promptly() -> None:
    base = 100 + 0.02 * np.sin(np.linspace(0, 18 * np.pi, 900))
    breakout = base.copy()
    breakout[700:] += np.linspace(0, 16, len(breakout) - 700)
    params = V7Params(
        adx_enter=22.0,
        adx_exit=16.0,
        chop_range_threshold=60.0,
        chop_trend_threshold=42.0,
        range_entry_percentile=0.25,
        range_exit_percentile=0.75,
        donchian_lookback=12,
    )
    result = generate_v7_signals(synthetic_market(breakout), params)
    assert (result["v7_market_state"] == "trend_up").any()
    trend_start = result.index[result["v7_market_state"] == "trend_up"][0]
    assert result.loc[trend_start, "close"] > result.loc[trend_start, "v7_close_breakout_high"]
    assert result.loc[trend_start, "v7_chop"] > params.chop_trend_threshold


def test_v7_daily_state_separates_downtrend_and_range() -> None:
    down = 200 * np.exp(np.cumsum(np.full(1200, -0.0012)))
    range_close = 100 + 2 * np.sin(np.linspace(0, 20 * np.pi, 1200))
    down_result = generate_v7_signals(synthetic_market(down), V7Params())
    range_result = generate_v7_signals(synthetic_market(range_close), V7Params())
    assert (down_result["v7_daily_state"] == -1).any()
    assert (range_result["v7_daily_state"] == 0).any()


def test_v7_trailing_stop_can_exit_a_fading_trend() -> None:
    base = 100 * np.exp(np.cumsum(np.full(1000, 0.0012)))
    base[650:] *= np.linspace(1.0, 0.4, len(base) - 650)
    params = V7Params(
        adx_enter=20.0,
        adx_exit=1.0,
        trend_confirm_bars=1,
        trend_exit_confirm_bars=20,
        trend_trailing_stop_atr=1.5,
        range_entry_percentile=0.1,
        range_exit_percentile=0.78,
        allow_short=False,
        efficiency_trend_threshold=0.2,
        efficiency_range_threshold=0.1,
    )
    result = generate_v7_signals(synthetic_market(base), params)
    assert (result["regime"] == "trend_stop").any()
    stop_idx = result.index[result["regime"] == "trend_stop"][0]
    assert result.loc[stop_idx, "v7_market_state"] == "range"
