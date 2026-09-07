import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from btc_regime.v71_live import (
    V71LiveParams,
    _initial_confirmed_long_scale_multiplier,
    _long_continuation_add_on_multiplier,
    _long_strong_protection_active,
    _long_strong_take_profit_active,
    _long_take_profit_extension_active,
    _short_initial_confirm_multiplier,
    _trend_permission,
    generate_v71_live_signals,
)
from btc_regime.v71_live import _should_arm_long_fast_fail_cooldown


ROOT = Path(__file__).resolve().parents[1]


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


def test_v71_live_is_causal_and_bounded() -> None:
    close = 100 * np.exp(np.cumsum(np.full(800, 0.001)))
    data = synthetic_market(close)
    params = V71LiveParams(**json.loads((ROOT / "configs/v71_live_params.json").read_text()))
    original = generate_v71_live_signals(data, params)
    changed = data.copy()
    changed.loc[changed.index[550]:, ["open", "high", "low", "close"]] *= 1.8
    modified = generate_v71_live_signals(changed, params)
    pd.testing.assert_series_equal(original["signal"].iloc[:550], modified["signal"].iloc[:550])
    assert original["signal"].abs().max() <= params.max_leverage + 1e-12
    assert {
        "raw_signal",
        "stop_price",
        "take_profit_price",
        "v71_market_state",
        "v71_downside_trigger",
        "v71_daily_bias",
        "v71_trigger_direction",
        "v71_trend_quality_score",
        "v71_tradability_score",
        "v71_tradability_state",
        "v71_direction_context",
        "v71_permission_scale",
        "v71_permission_reason",
    }.issubset(original.columns)


def test_v71_reference_mode_can_open_shorts() -> None:
    close = 200 * np.exp(np.cumsum(np.full(800, -0.0015)))
    data = synthetic_market(close)
    params = V71LiveParams(**json.loads((ROOT / "configs/v71_reference_params.json").read_text()))
    result = generate_v71_live_signals(data, params)
    assert (result["signal"] < 0).any()
    assert result.loc[result["signal"] < 0, "v71_market_state"].eq("trend_down").all()


def test_v71_live_fast_downside_can_flatten_long_signal() -> None:
    close = 100 * np.exp(np.cumsum(np.full(900, 0.0009)))
    close[620] *= 0.94
    close[621:] *= 0.90
    data = synthetic_market(close)
    params = V71LiveParams(
        trend_confirm_bars=1,
        downside_lookback=2,
        downside_confirmation_bars=1,
        downside_return_threshold=-0.02,
        breakout_buffer_atr=0.0,
    )
    result = generate_v71_live_signals(data, params)
    triggered = result["v71_downside_trigger"]
    assert triggered.any()
    assert (result.loc[triggered, "signal"] == 0).any()


def test_v71_live_outputs_protective_levels_when_enabled() -> None:
    close = 100 * np.exp(np.cumsum(np.full(850, 0.0012)))
    result = generate_v71_live_signals(synthetic_market(close), V71LiveParams(trend_confirm_bars=1))
    active = result["signal"] != 0
    assert active.any()
    assert result.loc[active, "stop_price"].notna().any()
    assert result.loc[active, "take_profit_price"].notna().any()


def test_v71_live_state_output_scores_are_bounded() -> None:
    close = 100 * np.exp(np.cumsum(np.full(900, 0.0011)))
    result = generate_v71_live_signals(synthetic_market(close), V71LiveParams(trend_confirm_bars=1))
    ready = result["v71_tradability_state"] != "warmup"
    assert ready.any()
    assert result.loc[ready, "v71_trend_quality_score"].between(0.0, 1.0).all()
    assert result.loc[ready, "v71_tradability_score"].between(0.0, 1.0).all()
    assert result.loc[ready, "v71_permission_scale"].between(0.0, 1.0).all()
    assert set(result.loc[ready, "v71_daily_bias"].unique()) <= {"bias_up", "bias_down", "neutral"}
    assert set(result.loc[ready, "v71_tradability_state"].unique()) <= {
        "untradable",
        "tradable_weak",
        "tradable_strong",
    }


def test_v71_live_trend_state_requires_tradable_filter() -> None:
    close = 100 * np.exp(np.cumsum(np.full(900, 0.0011)))
    result = generate_v71_live_signals(synthetic_market(close), V71LiveParams(trend_confirm_bars=1))
    trend_rows = result["v71_market_state"].isin(["trend_up", "trend_down"])
    assert trend_rows.any()
    assert result.loc[trend_rows, "v71_tradability_state"].isin(["tradable_weak", "tradable_strong"]).all()


def test_v71_live_untradable_rows_do_not_enter_trend_state() -> None:
    close = 100 + np.sin(np.linspace(0, 80, 900)) * 0.1
    data = synthetic_market(close)
    params = V71LiveParams(
        trend_confirm_bars=1,
        breakout_buffer_atr=0.0,
        adx_enter=60.0,
        adx_exit=45.0,
        chop_trend_threshold=20.0,
        chop_range_threshold=30.0,
        efficiency_range_threshold=0.30,
        efficiency_trend_threshold=0.55,
        trend_separation_atr=1.0,
        aroon_spread_threshold=60.0,
    )
    result = generate_v71_live_signals(data, params)
    untradable = result["v71_tradability_state"] == "untradable"
    assert untradable.any()
    assert result.loc[untradable, "v71_market_state"].isin(["range", "warmup"]).all()


def test_v71_live_blocked_context_has_zero_permission_and_signal() -> None:
    close = 100 * np.exp(np.cumsum(np.full(900, -0.0007)))
    data = synthetic_market(close)
    params = V71LiveParams(
        trend_confirm_bars=1,
        breakout_buffer_atr=0.0,
        daily_confirm_days=1,
        daily_exit_confirm_days=1,
        allow_short=True,
    )
    result = generate_v71_live_signals(data, params)
    blocked = result["v71_direction_context"].isin(["long_blocked_daily_bias", "short_blocked_daily_bias"])
    if blocked.any():
        assert result.loc[blocked, "v71_permission_scale"].eq(0.0).all()
        assert result.loc[blocked, "signal"].eq(0.0).all()


def test_v71_live_weak_long_permission_can_be_blocked_when_too_small() -> None:
    close = 100 * np.exp(np.cumsum(np.full(900, 0.001)))
    data = synthetic_market(close)
    base = generate_v71_live_signals(data, V71LiveParams(trend_confirm_bars=1, breakout_buffer_atr=0.0))
    weak_rows = base["v71_permission_reason"] == "probe_long"
    assert weak_rows.any()

    result = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
            long_min_permission=0.95,
        ),
    )
    blocked = result["v71_permission_reason"] == "long_probe_too_small"
    assert blocked.any()
    assert result.loc[blocked, "v71_permission_scale"].eq(0.0).all()
    assert result.loc[blocked, "signal"].eq(0.0).all()


def test_v71_live_long_permission_scale_can_promote_continuation() -> None:
    close = 100 * np.exp(np.cumsum(np.full(900, 0.001)))
    data = synthetic_market(close)
    base = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
            long_permission_scale=0.9,
            long_weak_permission_multiplier=0.85,
            long_continuation_threshold=0.65,
        ),
    )
    boosted = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
            long_permission_scale=1.0,
            long_weak_permission_multiplier=1.0,
            long_continuation_threshold=0.58,
        ),
    )
    base_count = int((base["v71_permission_reason"] == "confirmed_long").sum())
    boosted_count = int((boosted["v71_permission_reason"] == "confirmed_long").sum())
    assert boosted_count >= base_count


def test_v71_live_long_entry_probe_scales_early_trend_bars_then_recovers() -> None:
    close = 100 * np.exp(np.cumsum(np.full(900, 0.002)))
    data = synthetic_market(close)
    base = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
        ),
    )
    probed = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
            long_entry_probe_bars=3,
            long_entry_probe_scale=0.4,
        ),
    )
    active_index = probed.index[probed["v71_market_state"] == "trend_up"]
    assert len(active_index) > 6
    early = active_index[:3]
    later = active_index[4:8]
    early_ratio = (
        probed.loc[early, "signal"].abs().to_numpy() / base.loc[early, "signal"].abs().to_numpy()
    )
    later_ratio = (
        probed.loc[later, "signal"].abs().to_numpy() / base.loc[later, "signal"].abs().to_numpy()
    )
    assert np.all(early_ratio <= 0.41)
    assert np.all(later_ratio >= 0.95)
    assert probed.loc[early, "v71_speed_reason"].str.contains("entry_probe").all()


def test_v71_live_initial_confirm_scale_uses_continuous_quality_multiplier() -> None:
    params = V71LiveParams(
        long_initial_confirm_bars=3,
        long_initial_confirm_scale=0.75,
        long_initial_confirm_quality_max=0.7,
    )
    assert _initial_confirmed_long_scale_multiplier(1, "confirmed_long", 0.0, params) == pytest.approx(0.75)
    assert _initial_confirmed_long_scale_multiplier(2, "confirmed_long", 0.35, params) == pytest.approx(0.875)
    assert _initial_confirmed_long_scale_multiplier(3, "confirmed_long", 0.70, params) == pytest.approx(1.0)
    assert _initial_confirmed_long_scale_multiplier(4, "confirmed_long", 0.35, params) == pytest.approx(1.0)
    assert _initial_confirmed_long_scale_multiplier(2, "probe_long", 0.35, params) == pytest.approx(1.0)


def test_v71_live_initial_confirm_can_target_only_first_confirmed_fill() -> None:
    params = V71LiveParams(
        long_initial_confirm_bars=3,
        long_initial_confirm_scale=0.75,
        long_initial_confirm_quality_max=0.7,
        long_initial_confirm_first_fill_only=True,
    )
    assert _initial_confirmed_long_scale_multiplier(
        1,
        "confirmed_long",
        0.35,
        params,
        first_fill_transition=True,
    ) == pytest.approx(0.875)
    assert _initial_confirmed_long_scale_multiplier(
        2,
        "confirmed_long",
        0.35,
        params,
        first_fill_transition=False,
    ) == pytest.approx(1.0)


def test_v71_live_initial_confirm_first_fill_only_releases_on_second_confirmed_bar() -> None:
    close = 100 * np.exp(np.cumsum(np.full(900, 0.002)))
    data = synthetic_market(close)
    base = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
            long_continuation_threshold=0.1,
        ),
    )
    full_window = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
            long_continuation_threshold=0.1,
            long_initial_confirm_bars=3,
            long_initial_confirm_scale=0.5,
            long_initial_confirm_quality_max=0.0,
        ),
    )
    first_fill_only = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
            long_continuation_threshold=0.1,
            long_initial_confirm_bars=3,
            long_initial_confirm_scale=0.5,
            long_initial_confirm_quality_max=0.0,
            long_initial_confirm_first_fill_only=True,
        ),
    )
    confirmed = first_fill_only.index[first_fill_only["v71_permission_reason"] == "confirmed_long"]
    assert len(confirmed) > 4
    early = confirmed[:3]
    first_fill_ratio = (
        first_fill_only.loc[early, "signal"].abs().to_numpy() / base.loc[early, "signal"].abs().to_numpy()
    )
    full_window_ratio = (
        full_window.loc[early, "signal"].abs().to_numpy() / base.loc[early, "signal"].abs().to_numpy()
    )
    assert full_window_ratio[0] <= 0.51
    assert full_window_ratio[1] <= 0.51
    assert full_window_ratio[2] <= 0.51
    assert first_fill_ratio[0] <= 0.51
    assert first_fill_ratio[1] >= 0.95
    assert first_fill_ratio[2] >= 0.95
    assert first_fill_only.loc[early[:1], "v71_speed_reason"].str.contains("initial_confirm").all()
    assert not first_fill_only.loc[early[1:], "v71_speed_reason"].str.contains("initial_confirm").any()


def test_v71_live_long_continuation_add_on_requires_evidence_and_thresholds() -> None:
    params = V71LiveParams(
        long_continuation_add_on_min_bars=4,
        long_continuation_add_on_confirm_bars=2,
        long_continuation_add_on_scale=1.08,
        long_continuation_add_on_quality_min=0.75,
        long_continuation_add_on_tradability_min=0.80,
    )
    assert _long_continuation_add_on_multiplier(4, "confirmed_long", 0.81, 0.76, 1, params) == pytest.approx(1.0)
    assert _long_continuation_add_on_multiplier(4, "confirmed_long", 0.81, 0.76, 2, params) == pytest.approx(1.08)
    assert _long_continuation_add_on_multiplier(4, "confirmed_long", 0.79, 0.76, 2, params) == pytest.approx(1.0)
    assert _long_continuation_add_on_multiplier(4, "probe_long", 0.81, 0.76, 2, params) == pytest.approx(1.0)


def test_v71_live_long_continuation_add_on_boosts_only_later_confirmed_bars() -> None:
    close = 100 * np.exp(np.cumsum(np.full(900, 0.002)))
    data = synthetic_market(close)
    base = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
            long_continuation_threshold=0.1,
        ),
    )
    boosted = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
            long_continuation_threshold=0.1,
            long_continuation_add_on_min_bars=4,
            long_continuation_add_on_confirm_bars=2,
            long_continuation_add_on_scale=1.08,
        ),
    )
    confirmed = boosted.index[boosted["v71_permission_reason"] == "confirmed_long"]
    assert len(confirmed) > 8
    early = confirmed[:4]
    later = confirmed[4:8]
    early_ratio = boosted.loc[early, "signal"].abs().to_numpy() / base.loc[early, "signal"].abs().to_numpy()
    later_ratio = boosted.loc[later, "signal"].abs().to_numpy() / base.loc[later, "signal"].abs().to_numpy()
    assert np.all(early_ratio[:3] <= 1.01)
    assert np.all(later_ratio >= 1.07)
    assert not boosted.loc[early, "v71_speed_reason"].str.contains("continuation_add_on").any()
    assert boosted.loc[later, "v71_speed_reason"].str.contains("continuation_add_on").all()


def test_v71_live_long_take_profit_extension_requires_late_high_quality_confirmed_long() -> None:
    params = V71LiveParams(
        long_take_profit_extension_min_bars=6,
        long_take_profit_extension_atr=1.0,
        long_take_profit_extension_quality_min=0.84,
        long_take_profit_extension_tradability_min=0.84,
    )
    assert not _long_take_profit_extension_active(5, "confirmed_long", 0.9, 0.9, params)
    assert not _long_take_profit_extension_active(6, "probe_long", 0.9, 0.9, params)
    assert not _long_take_profit_extension_active(6, "confirmed_long", 0.83, 0.9, params)
    assert _long_take_profit_extension_active(6, "confirmed_long", 0.9, 0.9, params)


def test_v71_live_long_take_profit_extension_raises_take_profit_in_late_continuation() -> None:
    close = 100 * np.exp(np.cumsum(np.full(900, 0.0025)))
    data = synthetic_market(close)
    base = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
            long_continuation_threshold=0.1,
        ),
    )
    extended = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
            long_continuation_threshold=0.1,
            long_take_profit_extension_min_bars=6,
            long_take_profit_extension_atr=4.0,
        ),
    )
    confirmed = extended.index[extended["v71_permission_reason"] == "confirmed_long"]
    assert len(confirmed) > 10
    later = confirmed[8]
    assert extended.loc[later, "take_profit_price"] > base.loc[later, "take_profit_price"]


def test_v71_live_long_strong_protection_targets_high_quality_confirmed_long() -> None:
    params = V71LiveParams(
        long_strong_protection_atr_bonus=0.5,
        long_strong_protection_quality_min=0.84,
        long_strong_protection_tradability_min=0.84,
    )
    assert not _long_strong_protection_active("probe_long", 0.9, 0.9, params)
    assert not _long_strong_protection_active("confirmed_long", 0.83, 0.9, params)
    assert _long_strong_protection_active("confirmed_long", 0.9, 0.9, params)


def test_v71_live_long_strong_protection_widens_stop_for_high_quality_confirmed_long() -> None:
    close = 100 * np.exp(np.cumsum(np.full(900, 0.0025)))
    data = synthetic_market(close)
    base = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
            long_continuation_threshold=0.1,
        ),
    )
    widened = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
            long_continuation_threshold=0.1,
            long_strong_protection_atr_bonus=0.5,
        ),
    )
    confirmed = widened.index[widened["v71_permission_reason"] == "confirmed_long"]
    assert len(confirmed) > 5
    later = confirmed[4]
    assert widened.loc[later, "stop_price"] < base.loc[later, "stop_price"]


def test_v71_live_long_strong_take_profit_targets_high_quality_confirmed_long() -> None:
    params = V71LiveParams(
        long_strong_take_profit_atr_bonus=1.0,
        long_strong_take_profit_quality_min=0.88,
        long_strong_take_profit_tradability_min=0.88,
    )
    assert not _long_strong_take_profit_active("probe_long", 0.9, 0.9, params)
    assert not _long_strong_take_profit_active("confirmed_long", 0.87, 0.9, params)
    assert _long_strong_take_profit_active("confirmed_long", 0.9, 0.9, params)


def test_v71_live_long_strong_take_profit_widens_take_profit_for_high_quality_confirmed_long() -> None:
    close = 100 * np.exp(np.cumsum(np.full(900, 0.0025)))
    data = synthetic_market(close)
    base = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
            long_continuation_threshold=0.1,
        ),
    )
    widened = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
            long_continuation_threshold=0.1,
            long_strong_take_profit_atr_bonus=1.0,
        ),
    )
    confirmed = widened.index[widened["v71_permission_reason"] == "confirmed_long"]
    assert len(confirmed) > 5
    later = confirmed[4]
    assert widened.loc[later, "take_profit_price"] > base.loc[later, "take_profit_price"]


def test_v71_live_short_initial_confirm_multiplier_targets_early_confirmed_short() -> None:
    params = V71LiveParams(
        short_initial_confirm_bars=3,
        short_initial_confirm_scale=0.85,
    )
    assert _short_initial_confirm_multiplier(1, "confirmed_short", params) == pytest.approx(0.85)
    assert _short_initial_confirm_multiplier(3, "confirmed_short", params) == pytest.approx(0.85)
    assert _short_initial_confirm_multiplier(4, "confirmed_short", params) == pytest.approx(1.0)
    assert _short_initial_confirm_multiplier(2, "probe_short", params) == pytest.approx(1.0)


def test_v71_live_short_initial_confirm_scales_early_confirmed_short_bars_then_recovers() -> None:
    close = 100 * np.exp(np.cumsum(np.full(900, -0.002)))
    data = synthetic_market(close)
    base = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
            short_release_threshold=0.1,
            short_quality_floor=0.0,
            short_permission_scale=1.0,
            short_weak_permission_multiplier=1.0,
            short_min_permission=0.0,
        ),
    )
    tightened = generate_v71_live_signals(
        data,
        V71LiveParams(
            trend_confirm_bars=1,
            breakout_buffer_atr=0.0,
            short_release_threshold=0.1,
            short_quality_floor=0.0,
            short_permission_scale=1.0,
            short_weak_permission_multiplier=1.0,
            short_min_permission=0.0,
            short_initial_confirm_bars=3,
            short_initial_confirm_scale=0.85,
        ),
    )
    confirmed = tightened.index[tightened["v71_permission_reason"] == "confirmed_short"]
    assert len(confirmed) > 5
    early = confirmed[:3]
    later = confirmed[4:8]
    early_ratio = tightened.loc[early, "signal"].abs().to_numpy() / base.loc[early, "signal"].abs().to_numpy()
    later_ratio = tightened.loc[later, "signal"].abs().to_numpy() / base.loc[later, "signal"].abs().to_numpy()
    assert np.all(early_ratio <= 0.86)
    assert np.all(later_ratio >= 0.95)
    assert tightened.loc[early, "v71_speed_reason"].str.contains("short_initial_confirm").all()
    assert not tightened.loc[later, "v71_speed_reason"].str.contains("short_initial_confirm").any()


def test_v71_live_fast_fail_cooldown_downgrades_long_to_probe() -> None:
    params = V71LiveParams(long_continuation_threshold=0.6, long_min_permission=0.1)
    row = SimpleNamespace(v71_daily_state=1)
    permission_scale, permission_reason, direction_context = _trend_permission(
        1,
        row,
        tradability_score=0.9,
        trend_quality_score=0.9,
        params=params,
        long_cooldown_active=True,
    )
    assert permission_reason == "cooldown_probe_long"
    assert direction_context == "long_cooldown_probe"
    assert params.long_min_permission <= permission_scale < params.long_continuation_threshold


def test_v71_live_fast_fail_cooldown_can_target_only_low_quality_confirmed_long() -> None:
    params = V71LiveParams(
        long_fast_fail_bars=12,
        long_fast_fail_quality_max=0.7,
    )
    assert _should_arm_long_fast_fail_cooldown(8, "confirmed_long", 0.65, params)
    assert not _should_arm_long_fast_fail_cooldown(8, "confirmed_long", 0.75, params)
    assert not _should_arm_long_fast_fail_cooldown(8, "probe_long", 0.65, params)
