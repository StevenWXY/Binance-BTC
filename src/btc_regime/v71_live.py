"""V7.1-live: two-stage trend classification with live-oriented protections."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from types import SimpleNamespace

import numpy as np
import pandas as pd

from .indicators import add_indicators, aroon, choppiness_index, realized_volatility
from .strategy import _factor_diagnostics, _factor_scale


_MARKET_RANGE = "range"
_MARKET_UP = "trend_up"
_MARKET_DOWN = "trend_down"
_SPEED_NONE = "none"
_SPEED_NORMAL = "normal"
_SPEED_RAPID = "rapid"
_TRADABILITY_UNTRADABLE = "untradable"
_TRADABILITY_WEAK = "tradable_weak"
_TRADABILITY_STRONG = "tradable_strong"


@dataclass(frozen=True)
class V71LiveParams:
    """Parameters for the live-focused V7.1 strategy."""

    ema_fast: int = 30
    ema_slow: int = 120
    daily_ema_fast: int = 10
    daily_ema_slow: int = 30
    atr_period: int = 20
    adx_period: int = 14
    adx_enter: float = 27.0
    adx_exit: float = 18.0
    trend_separation_atr: float = 0.12
    chop_period: int = 14
    chop_trend_threshold: float = 40.0
    chop_range_threshold: float = 60.0
    daily_chop_period: int = 14
    daily_chop_trend_threshold: float = 55.0
    daily_adx_enter: float = 18.0
    daily_confirm_days: int = 2
    daily_exit_confirm_days: int = 3
    aroon_period: int = 25
    aroon_trend_threshold: float = 70.0
    aroon_spread_threshold: float = 15.0
    efficiency_period: int = 12
    efficiency_trend_threshold: float = 0.20
    efficiency_range_threshold: float = 0.08
    rsi_period: int = 14
    rsi_entry: float = 28.0
    rsi_exit: float = 50.0
    bb_period: int = 24
    bb_std: float = 2.0
    target_vol: float = 0.97
    max_leverage: float = 6.5
    trend_scale: float = 1.7
    rebound_scale: float = 0.12
    allow_short: bool = True
    short_scale: float = 0.10
    rebalance_bars: int = 120
    trend_confirm_bars: int = 3
    reversal_confirm_bars: int = 4
    trend_exit_confirm_bars: int = 3
    post_trend_probe_bars: int = 1
    min_rebalance_delta: float = 0.35
    realized_vol_period: int = 12
    vol_baseline_period: int = 90
    vol_shock_enter: float = 1.25
    vol_shock_exit: float = 1.1
    vol_shock_scale: float = 0.25
    vol_momentum_period: int = 36
    funding_lookback: int = 6
    funding_high_threshold: float = 0.0002
    funding_factor_scale: float = 0.35
    downside_vol_period: int = 24
    downside_calm_threshold: float = 0.4
    downside_stress_threshold: float = 0.625
    downside_calm_boost: float = 1.325
    downside_stress_scale: float = 0.25
    price_drawdown_lookback: int = 240
    price_drawdown_enter: float = 0.14
    price_drawdown_exit: float = 0.1
    price_drawdown_scale: float = 0.2
    trend_trailing_stop_atr: float = 2.0
    range_lookback: int = 90
    range_entry_percentile: float = 0.08
    range_exit_percentile: float = 0.78
    range_stop_atr: float = 2.0
    range_max_bars: int = 18
    donchian_lookback: int = 18
    breakout_buffer_atr: float = 0.25
    speed_fast_period: int = 1
    speed_medium_period: int = 3
    speed_slow_period: int = 6
    rapid_return_threshold: float = 0.05
    rapid_medium_return_threshold: float = 0.08
    rapid_rsi_high: float = 68.0
    rapid_rsi_low: float = 32.0
    rapid_range_high: float = 0.8
    rapid_range_low: float = 0.2
    rapid_deceleration_min: float = 0.008
    rapid_deceleration_scale: float = 0.45
    adverse_return_threshold: float = 0.07
    adverse_medium_return_threshold: float = 0.10
    adverse_shock_scale: float = 0.25
    adverse_exit_enabled: bool = False
    adverse_exit_confirm_bars: int = 2
    volume_deceleration_scale: float = 0.70
    long_neutral_bias_scale: float = 0.75
    long_quality_floor: float = 0.30
    long_permission_scale: float = 1.00
    long_weak_permission_multiplier: float = 0.85
    long_min_permission: float = 0.18
    long_continuation_threshold: float = 0.65
    long_entry_probe_bars: int = 0
    long_entry_probe_scale: float = 1.0
    long_initial_confirm_bars: int = 0
    long_initial_confirm_scale: float = 1.0
    long_initial_confirm_quality_max: float = 0.0
    long_initial_confirm_first_fill_only: bool = False
    long_continuation_add_on_min_bars: int = 0
    long_continuation_add_on_confirm_bars: int = 1
    long_continuation_add_on_scale: float = 1.0
    long_continuation_add_on_quality_min: float = 0.0
    long_continuation_add_on_tradability_min: float = 0.0
    long_strong_protection_atr_bonus: float = 0.0
    long_strong_protection_quality_min: float = 0.0
    long_strong_protection_tradability_min: float = 0.0
    long_strong_take_profit_atr_bonus: float = 0.0
    long_strong_take_profit_quality_min: float = 0.0
    long_strong_take_profit_tradability_min: float = 0.0
    long_take_profit_extension_min_bars: int = 0
    long_take_profit_extension_atr: float = 0.0
    long_take_profit_extension_quality_min: float = 0.0
    long_take_profit_extension_tradability_min: float = 0.0
    long_fast_fail_bars: int = 0
    long_fast_fail_cooldown_bars: int = 0
    long_fast_fail_probe_scale: float = 1.0
    long_fast_fail_quality_max: float = 0.0
    short_initial_confirm_bars: int = 0
    short_initial_confirm_scale: float = 1.0
    short_neutral_bias_scale: float = 0.45
    short_quality_floor: float = 0.45
    short_permission_scale: float = 0.85
    short_weak_permission_multiplier: float = 0.50
    short_min_permission: float = 0.20
    short_release_threshold: float = 0.55
    range_block_tradability_threshold: float = 0.65
    range_block_trend_quality_threshold: float = 0.55
    range_base_permission_floor: float = 0.15
    range_min_permission: float = 0.20

    # Live-oriented protective overlay; disabling both fields reproduces the
    # unprotected xuyujian-style reference state machine for same-basis tests.
    live_protection_enabled: bool = True
    downside_protection_enabled: bool = True
    stop_atr: float = 1.8
    take_profit_atr: float = 3.2
    trailing_stop_atr: float = 1.7
    downside_stop_atr: float = 0.70
    downside_lookback: int = 3
    downside_return_threshold: float = -0.025
    downside_vol_ratio: float = 1.20
    downside_confirmation_bars: int = 2
    exit_cooldown_bars: int = 3
    max_hold_bars: int = 96

    def __post_init__(self) -> None:
        if not 0 < self.max_leverage <= 10:
            raise ValueError("max_leverage must be in (0, 10]")
        if self.ema_fast < 2 or self.ema_slow <= self.ema_fast:
            raise ValueError("ema_slow must exceed ema_fast >= 2")
        if self.daily_ema_fast < 2 or self.daily_ema_slow <= self.daily_ema_fast:
            raise ValueError("daily_ema_slow must exceed daily_ema_fast >= 2")
        if self.adx_exit <= 0 or self.adx_enter <= self.adx_exit:
            raise ValueError("adx_enter must exceed a positive adx_exit")
        if not 0 < self.short_scale <= 1:
            raise ValueError("short_scale must be in (0, 1]")
        if min(
            self.trend_confirm_bars,
            self.reversal_confirm_bars,
            self.trend_exit_confirm_bars,
            self.post_trend_probe_bars,
            self.downside_confirmation_bars,
            self.max_hold_bars,
        ) < 1:
            raise ValueError("confirmation and hold bars must be positive")
        if self.long_entry_probe_bars < 0:
            raise ValueError("long_entry_probe_bars must be non-negative")
        if self.long_initial_confirm_bars < 0:
            raise ValueError("long_initial_confirm_bars must be non-negative")
        if self.short_initial_confirm_bars < 0:
            raise ValueError("short_initial_confirm_bars must be non-negative")
        if self.long_continuation_add_on_min_bars < 0 or self.long_continuation_add_on_confirm_bars < 1:
            raise ValueError("long continuation add-on bars must be valid")
        if self.long_take_profit_extension_min_bars < 0:
            raise ValueError("long take-profit extension bars must be non-negative")
        if self.long_fast_fail_bars < 0 or self.long_fast_fail_cooldown_bars < 0:
            raise ValueError("long fast-fail settings must be non-negative")
        if self.min_rebalance_delta < 0:
            raise ValueError("min_rebalance_delta must be non-negative")
        if self.chop_period < 2 or not 0 < self.chop_trend_threshold < self.chop_range_threshold < 100:
            raise ValueError("choppiness thresholds must be ordered")
        if self.daily_chop_period < 2 or not 0 < self.daily_chop_trend_threshold < 100:
            raise ValueError("daily chop threshold must be in (0, 100)")
        if self.daily_confirm_days < 1 or self.daily_exit_confirm_days < 1:
            raise ValueError("daily confirmation bars must be positive")
        if self.aroon_period < 2 or not 0 < self.aroon_trend_threshold <= 100:
            raise ValueError("aroon settings must be valid")
        if self.aroon_spread_threshold < 0:
            raise ValueError("aroon_spread_threshold must be non-negative")
        if self.efficiency_period < 2:
            raise ValueError("efficiency_period must be positive")
        if not 0 <= self.efficiency_range_threshold < self.efficiency_trend_threshold <= 1:
            raise ValueError("efficiency thresholds must be ordered")
        if self.rebalance_bars < 1 or self.range_lookback < 2 or self.range_max_bars < 1:
            raise ValueError("rebalance and range settings must be positive")
        if self.donchian_lookback < 2 or self.breakout_buffer_atr < 0:
            raise ValueError("breakout settings must be valid")
        if not 0 < self.range_entry_percentile < self.range_exit_percentile < 1:
            raise ValueError("range entry percentile must be below range exit percentile")
        if self.speed_fast_period < 1 or self.speed_medium_period <= self.speed_fast_period:
            raise ValueError("speed periods must be ordered")
        if self.speed_slow_period <= self.speed_medium_period:
            raise ValueError("speed_slow_period must exceed speed_medium_period")
        if not 0 < self.rapid_return_threshold < self.rapid_medium_return_threshold:
            raise ValueError("rapid thresholds must be ordered")
        if not 0 < self.rapid_range_low < self.rapid_range_high < 1:
            raise ValueError("rapid range thresholds must be ordered")
        if not 0 < self.rapid_deceleration_scale <= 1:
            raise ValueError("rapid_deceleration_scale must be in (0, 1]")
        if not 0 < self.adverse_shock_scale <= 1 or self.adverse_exit_confirm_bars < 1:
            raise ValueError("adverse controls must be valid")
        if not 0 < self.volume_deceleration_scale <= 1:
            raise ValueError("volume_deceleration_scale must be in (0, 1]")
        for value in (
            self.long_neutral_bias_scale,
            self.long_quality_floor,
            self.long_weak_permission_multiplier,
            self.long_min_permission,
            self.long_continuation_threshold,
            self.long_entry_probe_scale,
            self.long_initial_confirm_scale,
            self.long_initial_confirm_quality_max,
            self.long_fast_fail_probe_scale,
            self.long_fast_fail_quality_max,
            self.short_initial_confirm_scale,
            self.short_neutral_bias_scale,
            self.short_quality_floor,
            self.short_weak_permission_multiplier,
            self.short_min_permission,
            self.short_release_threshold,
            self.range_block_tradability_threshold,
            self.range_block_trend_quality_threshold,
            self.range_base_permission_floor,
            self.range_min_permission,
            self.long_continuation_add_on_quality_min,
            self.long_continuation_add_on_tradability_min,
            self.long_strong_protection_quality_min,
            self.long_strong_protection_tradability_min,
            self.long_strong_take_profit_quality_min,
            self.long_strong_take_profit_tradability_min,
            self.long_take_profit_extension_quality_min,
            self.long_take_profit_extension_tradability_min,
        ):
            if not 0 <= value <= 1:
                raise ValueError("permission thresholds and scales must be in [0, 1]")
        for value in (
            self.long_permission_scale,
            self.short_permission_scale,
            self.long_continuation_add_on_scale,
        ):
            if not 0 < value <= 2:
                raise ValueError("permission scale multipliers must be in (0, 2]")
        if not 0 <= self.long_take_profit_extension_atr <= 10:
            raise ValueError("long_take_profit_extension_atr must be in [0, 10]")
        if not 0 <= self.long_strong_protection_atr_bonus <= 10:
            raise ValueError("long_strong_protection_atr_bonus must be in [0, 10]")
        if not 0 <= self.long_strong_take_profit_atr_bonus <= 10:
            raise ValueError("long_strong_take_profit_atr_bonus must be in [0, 10]")
        if not 0 <= self.downside_calm_threshold < self.downside_stress_threshold <= 1:
            raise ValueError("downside thresholds must be ordered")
        if not 0 < self.vol_shock_scale <= 1:
            raise ValueError("volatility shock scale must be in (0, 1]")
        if self.vol_shock_enter <= self.vol_shock_exit or self.vol_shock_exit <= 0:
            raise ValueError("volatility shock thresholds must be ordered")
        if self.price_drawdown_lookback < 2:
            raise ValueError("price_drawdown_lookback must be positive")
        if not 0 < self.price_drawdown_exit < self.price_drawdown_enter < 1:
            raise ValueError("price drawdown thresholds must be ordered")
        if not 0 < self.price_drawdown_scale <= 1:
            raise ValueError("price_drawdown_scale must be in (0, 1]")
        if self.trend_trailing_stop_atr <= 0:
            raise ValueError("trend_trailing_stop_atr must be positive")
        if self.stop_atr <= 0 or self.take_profit_atr <= 0 or self.trailing_stop_atr <= 0:
            raise ValueError("live ATR distances must be positive")
        if self.downside_stop_atr <= 0 or self.downside_return_threshold >= 0:
            raise ValueError("downside live protection parameters must be valid")
        for value in (
            self.funding_factor_scale,
            self.downside_calm_boost,
            self.downside_stress_scale,
        ):
            if not 0 < value <= 2:
                raise ValueError("allocation scales must be in (0, 2]")
        if self.downside_calm_boost < 1:
            raise ValueError("downside_calm_boost must be at least 1")

    def to_dict(self) -> dict[str, float | int | bool]:
        return asdict(self)


def _volatility_risk_scale(frame: pd.DataFrame, params: V71LiveParams) -> pd.Series:
    periods_per_year = 365 * 24 // 4
    frame["v71_realized_vol"] = realized_volatility(
        frame["close"], params.realized_vol_period, periods_per_year
    )
    frame["v71_vol_baseline"] = frame["v71_realized_vol"].ewm(
        span=params.vol_baseline_period,
        adjust=False,
        min_periods=params.vol_baseline_period,
    ).mean()
    frame["v71_vol_ratio"] = frame["v71_realized_vol"] / frame["v71_vol_baseline"].replace(0, np.nan)
    frame["v71_vol_momentum"] = frame["close"].pct_change(params.vol_momentum_period)

    risk_scale = np.ones(len(frame), dtype=float)
    risk_off = False
    for i, row in enumerate(frame[["v71_vol_ratio", "v71_vol_momentum"]].itertuples(index=False)):
        if not np.isfinite(row.v71_vol_ratio) or not np.isfinite(row.v71_vol_momentum):
            continue
        if risk_off:
            if row.v71_vol_ratio <= params.vol_shock_exit or row.v71_vol_momentum >= 0:
                risk_off = False
        elif row.v71_vol_ratio >= params.vol_shock_enter and row.v71_vol_momentum < 0:
            risk_off = True
        if risk_off:
            risk_scale[i] = params.vol_shock_scale
    return pd.Series(risk_scale, index=frame.index)


def _allocation_scale(frame: pd.DataFrame, params: V71LiveParams) -> pd.Series:
    log_return = np.log(frame["close"] / frame["close"].shift(1))
    total_variance = log_return.pow(2).ewm(
        span=params.downside_vol_period,
        adjust=False,
        min_periods=params.downside_vol_period,
    ).mean()
    downside_variance = log_return.clip(upper=0).pow(2).ewm(
        span=params.downside_vol_period,
        adjust=False,
        min_periods=params.downside_vol_period,
    ).mean()
    upside_variance = log_return.clip(lower=0).pow(2).ewm(
        span=params.downside_vol_period,
        adjust=False,
        min_periods=params.downside_vol_period,
    ).mean()
    frame["v71_downside_share"] = np.sqrt(downside_variance / total_variance.replace(0, np.nan))
    frame["v71_upside_share"] = np.sqrt(upside_variance / total_variance.replace(0, np.nan))

    def scale_from_adverse_share(adverse_share: pd.Series) -> pd.Series:
        scale = np.ones(len(frame), dtype=float)
        calm = adverse_share <= params.downside_calm_threshold
        stress = adverse_share >= params.downside_stress_threshold
        scale[calm.fillna(False).to_numpy()] = params.downside_calm_boost
        scale[stress.fillna(False).to_numpy()] = params.downside_stress_scale
        return pd.Series(scale, index=frame.index)

    long_scale = scale_from_adverse_share(frame["v71_downside_share"])
    short_scale = scale_from_adverse_share(frame["v71_upside_share"])
    frame["v71_long_allocation_scale"] = long_scale
    frame["v71_short_allocation_scale"] = short_scale
    return long_scale


def _price_drawdown_scale(frame: pd.DataFrame, params: V71LiveParams) -> pd.Series:
    rolling_peak = frame["close"].rolling(
        params.price_drawdown_lookback,
        min_periods=params.price_drawdown_lookback,
    ).max()
    frame["v71_price_drawdown"] = frame["close"] / rolling_peak - 1
    scale = np.ones(len(frame), dtype=float)
    brake_active = False
    for i, value in enumerate(frame["v71_price_drawdown"]):
        if not np.isfinite(value):
            continue
        if brake_active:
            if value >= -params.price_drawdown_exit:
                brake_active = False
        elif value <= -params.price_drawdown_enter:
            brake_active = True
        if brake_active:
            scale[i] = params.price_drawdown_scale
    frame["v71_drawdown_risk_scale"] = scale
    return pd.Series(scale, index=frame.index)


def _range_percentile(close: pd.Series, lookback: int) -> pd.Series:
    def percentile(values: np.ndarray) -> float:
        current = values[-1]
        if not np.isfinite(current):
            return np.nan
        valid = values[np.isfinite(values)]
        if len(valid) == 0:
            return np.nan
        return float((valid <= current).mean())

    return close.rolling(lookback, min_periods=lookback).apply(percentile, raw=True)


def _clamp01(value: float) -> float:
    return float(min(1.0, max(0.0, value)))


def _score_between(value: float, lower: float, upper: float) -> float:
    if not np.isfinite(value):
        return 0.0
    if upper <= lower:
        return 1.0 if value >= upper else 0.0
    return _clamp01((value - lower) / (upper - lower))


def _daily_bias_label(daily_state: int) -> str:
    if daily_state > 0:
        return "bias_up"
    if daily_state < 0:
        return "bias_down"
    return "neutral"


def _breakout_direction(row: object, params: V71LiveParams) -> int:
    required = (
        "close",
        "atr",
        "v71_donchian_high",
        "v71_donchian_low",
        "v71_close_breakout_high",
        "v71_close_breakout_low",
    )
    if not all(np.isfinite(getattr(row, key)) for key in required):
        return 0
    breakout_buffer = float(row.atr) * params.breakout_buffer_atr
    if (
        float(row.close) > float(row.v71_donchian_high) + breakout_buffer
        or float(row.close) > float(row.v71_close_breakout_high) + breakout_buffer
    ):
        return 1
    if (
        float(row.close) < float(row.v71_donchian_low) - breakout_buffer
        or float(row.close) < float(row.v71_close_breakout_low) - breakout_buffer
    ):
        return -1
    return 0


def _trend_quality_score(row: object, direction: int, params: V71LiveParams) -> float:
    if direction == 0:
        return 0.0
    if not all(
        np.isfinite(getattr(row, key))
        for key in ("adx", "v71_chop", "v71_efficiency_ratio", "v71_aroon_up", "v71_aroon_down")
    ):
        return 0.0

    adx_score = _score_between(float(row.adx), params.adx_exit, params.adx_enter)
    chop_score = _score_between(
        params.chop_range_threshold - float(row.v71_chop),
        0.0,
        params.chop_range_threshold - params.chop_trend_threshold,
    )
    efficiency_score = _score_between(
        float(row.v71_efficiency_ratio),
        params.efficiency_range_threshold,
        params.efficiency_trend_threshold,
    )
    if direction > 0:
        aroon_level = float(row.v71_aroon_up)
        aroon_spread = float(row.v71_aroon_up) - float(row.v71_aroon_down)
    else:
        aroon_level = float(row.v71_aroon_down)
        aroon_spread = float(row.v71_aroon_down) - float(row.v71_aroon_up)
    aroon_score = 0.5 * _score_between(aroon_level, 50.0, params.aroon_trend_threshold) + 0.5 * _score_between(
        aroon_spread, 0.0, params.aroon_spread_threshold * 2
    )
    breakout_score = 1.0 if _breakout_direction(row, params) == direction else 0.0
    return _clamp01(np.mean([adx_score, chop_score, efficiency_score, aroon_score, breakout_score]))


def _tradability_score(row: object, params: V71LiveParams, direction_hint: int, trend_quality_score: float) -> float:
    required = ("adx", "v71_chop", "v71_efficiency_ratio", "ema_fast", "ema_slow", "atr", "v71_aroon_up", "v71_aroon_down")
    if not all(np.isfinite(getattr(row, key)) for key in required):
        return 0.0

    adx_score = _score_between(float(row.adx), params.adx_exit, params.adx_enter)
    chop_score = _score_between(
        params.chop_range_threshold - float(row.v71_chop),
        0.0,
        params.chop_range_threshold - params.chop_trend_threshold,
    )
    efficiency_score = _score_between(
        float(row.v71_efficiency_ratio),
        params.efficiency_range_threshold,
        params.efficiency_trend_threshold,
    )
    separation = abs(float(row.ema_fast) - float(row.ema_slow)) / float(row.atr)
    separation_score = _score_between(separation, params.trend_separation_atr, params.trend_separation_atr * 3)
    aroon_spread = abs(float(row.v71_aroon_up) - float(row.v71_aroon_down))
    aroon_spread_score = _score_between(aroon_spread, params.aroon_spread_threshold / 2, params.aroon_spread_threshold * 2)
    score = float(np.mean([adx_score, chop_score, efficiency_score, separation_score, aroon_spread_score]))
    if direction_hint != 0:
        score = max(score, trend_quality_score)
    return _clamp01(score)


def _tradability_state(score: float) -> str:
    if score >= 0.65:
        return _TRADABILITY_STRONG
    if score >= 0.35:
        return _TRADABILITY_WEAK
    return _TRADABILITY_UNTRADABLE


def _direction_context(
    direction: int,
    daily_state: int,
    tradability_state: str,
    trend_quality_score: float,
    params: V71LiveParams,
) -> str:
    if direction == 0:
        return "neutral_wait"
    if direction > 0:
        if daily_state < 0:
            return "long_blocked_daily_bias"
        if tradability_state == _TRADABILITY_UNTRADABLE:
            return "long_blocked_untradable"
        if tradability_state == _TRADABILITY_WEAK or trend_quality_score < params.long_continuation_threshold:
            return "long_probe"
        return "long_continuation"
    if daily_state > 0:
        return "short_blocked_daily_bias"
    if tradability_state == _TRADABILITY_UNTRADABLE:
        return "short_blocked_untradable"
    if tradability_state == _TRADABILITY_WEAK or trend_quality_score < params.short_release_threshold:
        return "short_probe"
    return "short_release"


def _trend_permission(
    direction: int,
    row: object,
    tradability_score: float,
    trend_quality_score: float,
    params: V71LiveParams,
    *,
    long_cooldown_active: bool = False,
) -> tuple[float, str, str]:
    daily_state = int(row.v71_daily_state)
    tradability_state = _tradability_state(tradability_score)
    context = _direction_context(direction, daily_state, tradability_state, trend_quality_score, params)
    base_score = _clamp01(0.5 * tradability_score + 0.5 * trend_quality_score)

    if direction > 0:
        if daily_state < 0:
            return 0.0, "daily_bias_conflict", context
        bias_scale = 1.0 if daily_state > 0 else params.long_neutral_bias_scale
        if tradability_state == _TRADABILITY_UNTRADABLE or base_score < params.long_quality_floor:
            return 0.0, "weak_long_quality", context
        permission_scale = _clamp01(base_score * bias_scale * params.long_permission_scale)
        if tradability_state == _TRADABILITY_WEAK:
            permission_scale *= params.long_weak_permission_multiplier
        if permission_scale < params.long_min_permission:
            return 0.0, "long_probe_too_small", context
        if long_cooldown_active:
            probe_cap = max(params.long_min_permission, params.long_continuation_threshold - 1e-6)
            permission_scale = min(permission_scale, probe_cap)
            return permission_scale, "cooldown_probe_long", "long_cooldown_probe"
        reason = "confirmed_long" if permission_scale >= params.long_continuation_threshold else "probe_long"
        return permission_scale, reason, context

    if not params.allow_short:
        return 0.0, "short_disabled", context
    if daily_state > 0:
        return 0.0, "short_daily_bias", context
    bias_scale = 1.0 if daily_state < 0 else params.short_neutral_bias_scale
    if tradability_state == _TRADABILITY_UNTRADABLE or base_score < params.short_quality_floor:
        return 0.0, "weak_short_quality", context
    permission_scale = _clamp01(base_score * bias_scale * params.short_permission_scale)
    if tradability_state == _TRADABILITY_WEAK:
        permission_scale *= params.short_weak_permission_multiplier
    if permission_scale < params.short_min_permission:
        return 0.0, "short_probe_too_small", context
    reason = "confirmed_short" if permission_scale >= params.short_release_threshold else "probe_short"
    return permission_scale, reason, context


def _should_arm_long_fast_fail_cooldown(
    trend_age: int,
    initial_permission_reason: str,
    initial_trend_quality: float,
    params: V71LiveParams,
) -> bool:
    if params.long_fast_fail_bars <= 0 or trend_age <= 0 or trend_age > params.long_fast_fail_bars:
        return False
    if params.long_fast_fail_quality_max > 0:
        return (
            initial_permission_reason == "confirmed_long"
            and np.isfinite(initial_trend_quality)
            and initial_trend_quality <= params.long_fast_fail_quality_max
        )
    return True


def _initial_confirmed_long_scale_multiplier(
    trend_age: int,
    permission_reason: str,
    trend_quality_score: float,
    params: V71LiveParams,
    *,
    first_fill_transition: bool = True,
) -> float:
    if params.long_initial_confirm_bars <= 0:
        return 1.0
    if permission_reason != "confirmed_long" or trend_age <= 0 or trend_age > params.long_initial_confirm_bars:
        return 1.0
    if params.long_initial_confirm_first_fill_only and not first_fill_transition:
        return 1.0
    if params.long_initial_confirm_quality_max <= 0:
        return params.long_initial_confirm_scale
    if not np.isfinite(trend_quality_score):
        return 1.0
    if trend_quality_score >= params.long_initial_confirm_quality_max:
        return 1.0
    quality_ratio = _clamp01(trend_quality_score / params.long_initial_confirm_quality_max)
    return float(
        params.long_initial_confirm_scale
        + (1.0 - params.long_initial_confirm_scale) * quality_ratio
    )


def _long_continuation_add_on_multiplier(
    trend_age: int,
    permission_reason: str,
    tradability_score: float,
    trend_quality_score: float,
    evidence_streak: int,
    params: V71LiveParams,
) -> float:
    if params.long_continuation_add_on_min_bars <= 0 or params.long_continuation_add_on_scale <= 1.0:
        return 1.0
    if permission_reason != "confirmed_long" or trend_age < params.long_continuation_add_on_min_bars:
        return 1.0
    if evidence_streak < params.long_continuation_add_on_confirm_bars:
        return 1.0
    if params.long_continuation_add_on_quality_min > 0:
        if not np.isfinite(trend_quality_score) or trend_quality_score < params.long_continuation_add_on_quality_min:
            return 1.0
    if params.long_continuation_add_on_tradability_min > 0:
        if not np.isfinite(tradability_score) or tradability_score < params.long_continuation_add_on_tradability_min:
            return 1.0
    return params.long_continuation_add_on_scale


def _short_initial_confirm_multiplier(
    trend_age: int,
    permission_reason: str,
    params: V71LiveParams,
) -> float:
    if params.short_initial_confirm_bars <= 0:
        return 1.0
    if permission_reason != "confirmed_short" or trend_age <= 0 or trend_age > params.short_initial_confirm_bars:
        return 1.0
    return params.short_initial_confirm_scale


def _long_take_profit_extension_active(
    trend_age: int,
    permission_reason: str,
    tradability_score: float,
    trend_quality_score: float,
    params: V71LiveParams,
) -> bool:
    if params.long_take_profit_extension_min_bars <= 0 or params.long_take_profit_extension_atr <= 0:
        return False
    if permission_reason != "confirmed_long" or trend_age < params.long_take_profit_extension_min_bars:
        return False
    if params.long_take_profit_extension_quality_min > 0:
        if not np.isfinite(trend_quality_score) or trend_quality_score < params.long_take_profit_extension_quality_min:
            return False
    if params.long_take_profit_extension_tradability_min > 0:
        if not np.isfinite(tradability_score) or tradability_score < params.long_take_profit_extension_tradability_min:
            return False
    return True


def _long_strong_protection_active(
    permission_reason: str,
    tradability_score: float,
    trend_quality_score: float,
    params: V71LiveParams,
) -> bool:
    if params.long_strong_protection_atr_bonus <= 0:
        return False
    if permission_reason != "confirmed_long":
        return False
    if params.long_strong_protection_quality_min > 0:
        if not np.isfinite(trend_quality_score) or trend_quality_score < params.long_strong_protection_quality_min:
            return False
    if params.long_strong_protection_tradability_min > 0:
        if not np.isfinite(tradability_score) or tradability_score < params.long_strong_protection_tradability_min:
            return False
    return True


def _long_strong_take_profit_active(
    permission_reason: str,
    tradability_score: float,
    trend_quality_score: float,
    params: V71LiveParams,
) -> bool:
    if params.long_strong_take_profit_atr_bonus <= 0:
        return False
    if permission_reason != "confirmed_long":
        return False
    if params.long_strong_take_profit_quality_min > 0:
        if not np.isfinite(trend_quality_score) or trend_quality_score < params.long_strong_take_profit_quality_min:
            return False
    if params.long_strong_take_profit_tradability_min > 0:
        if not np.isfinite(tradability_score) or tradability_score < params.long_strong_take_profit_tradability_min:
            return False
    return True


def _range_permission(
    row: object,
    tradability_score: float,
    trend_quality_score: float,
    params: V71LiveParams,
) -> tuple[float, str, str]:
    daily_state = int(row.v71_daily_state)
    if daily_state < 0:
        return 0.0, "range_daily_bias", "range_blocked_daily_bias"
    if (
        tradability_score >= params.range_block_tradability_threshold
        or trend_quality_score >= params.range_block_trend_quality_threshold
    ):
        return 0.0, "range_trend_pressure", "range_blocked_trend_pressure"
    base = _clamp01(1.0 - max(tradability_score, trend_quality_score))
    permission_scale = _clamp01(max(params.range_base_permission_floor, base))
    if permission_scale < params.range_min_permission:
        return 0.0, "range_permission_too_small", "range_blocked_permission"
    return permission_scale, "range_rebound", "range_rebound"


def _efficiency_ratio(close: pd.Series, lookback: int) -> pd.Series:
    net_change = (close - close.shift(lookback)).abs()
    path = close.diff().abs().rolling(lookback, min_periods=lookback).sum()
    return net_change / path.replace(0, np.nan)


def _donchian_channels(frame: pd.DataFrame, lookback: int) -> tuple[pd.Series, pd.Series]:
    upper = frame["high"].rolling(lookback, min_periods=lookback).max().shift(1)
    lower = frame["low"].rolling(lookback, min_periods=lookback).min().shift(1)
    return upper, lower


def _close_channels(frame: pd.DataFrame, lookback: int) -> tuple[pd.Series, pd.Series]:
    upper = frame["close"].rolling(lookback, min_periods=lookback).max().shift(1)
    lower = frame["close"].rolling(lookback, min_periods=lookback).min().shift(1)
    return upper, lower


def _daily_market_state(data: pd.DataFrame, params: V71LiveParams) -> pd.Series:
    daily = data.resample("1D").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "quote_volume": "sum",
        }
    ).dropna(subset=["open", "high", "low", "close"])
    if daily.empty:
        return pd.Series(0, index=data.index, dtype=int)

    daily_ind = add_indicators(
        daily,
        ema_fast=max(params.daily_ema_fast, 2),
        ema_slow=max(params.daily_ema_slow, params.daily_ema_fast + 1),
        atr_period=params.atr_period,
        rsi_period=params.rsi_period,
        bb_period=params.bb_period,
        bb_std=params.bb_std,
        adx_period=params.adx_period,
    )
    daily_ind["daily_chop"] = choppiness_index(daily_ind, params.daily_chop_period)
    raw = np.zeros(len(daily_ind), dtype=int)
    trend_up = (
        (daily_ind["ema_fast"] > daily_ind["ema_slow"])
        & (daily_ind["adx"] >= params.daily_adx_enter)
        & (daily_ind["daily_chop"] <= params.daily_chop_trend_threshold)
    )
    trend_down = (
        (daily_ind["ema_fast"] < daily_ind["ema_slow"])
        & (daily_ind["adx"] >= params.daily_adx_enter)
        & (daily_ind["daily_chop"] <= params.daily_chop_trend_threshold)
    )
    raw[trend_up.fillna(False).to_numpy()] = 1
    raw[trend_down.fillna(False).to_numpy()] = -1

    confirmed = np.zeros(len(raw), dtype=int)
    active = candidate = candidate_count = exit_count = 0
    for i, value in enumerate(raw):
        value = int(value)
        if active == 0:
            if value == 0:
                candidate = 0
                candidate_count = 0
            elif value == candidate:
                candidate_count += 1
            else:
                candidate = value
                candidate_count = 1
            if candidate != 0 and candidate_count >= params.daily_confirm_days:
                active = candidate
                candidate = 0
                candidate_count = 0
                exit_count = 0
        else:
            if value == active:
                exit_count = 0
            else:
                exit_count += 1
                if exit_count >= params.daily_exit_confirm_days:
                    active = 0
                    exit_count = 0
                    candidate = value if value != 0 else 0
                    candidate_count = 1 if value != 0 else 0
        confirmed[i] = active

    series = pd.Series(confirmed, index=daily_ind.index)
    series.index = series.index + pd.Timedelta(days=1)
    return series.reindex(data.index, method="ffill").fillna(0).astype(int)


def _speed_diagnostics(frame: pd.DataFrame, params: V71LiveParams) -> None:
    close = frame["close"]
    frame["v71_fast_return"] = close.pct_change(params.speed_fast_period)
    frame["v71_medium_return"] = close.pct_change(params.speed_medium_period)
    frame["v71_slow_return"] = close.pct_change(params.speed_slow_period)
    frame["v71_fast_return_prev"] = frame["v71_fast_return"].shift(1)
    quote_volume = frame.get("quote_volume", pd.Series(1.0, index=frame.index)).replace(0, np.nan)
    baseline = quote_volume.ewm(span=max(params.speed_slow_period * 6, 12), adjust=False).mean()
    frame["v71_volume_speed"] = quote_volume / baseline.replace(0, np.nan)
    frame["v71_volume_speed_prev"] = frame["v71_volume_speed"].shift(1)


def _market_direction(row: object, params: V71LiveParams) -> int:
    required = (
        "v71_daily_state",
        "ema_fast",
        "ema_slow",
        "atr",
        "plus_di",
        "minus_di",
        "v71_chop",
        "v71_aroon_up",
        "v71_aroon_down",
        "v71_efficiency_ratio",
        "v71_donchian_high",
        "v71_donchian_low",
        "v71_close_breakout_high",
        "v71_close_breakout_low",
    )
    if not all(np.isfinite(getattr(row, key)) for key in required):
        return 0
    chop = float(row.v71_chop)
    aroon_up = float(row.v71_aroon_up)
    aroon_down = float(row.v71_aroon_down)
    efficiency = float(row.v71_efficiency_ratio)
    breakout_direction = _breakout_direction(row, params)
    breakout_up = breakout_direction > 0
    breakout_down = breakout_direction < 0
    aroon_up_trend = (
        aroon_up >= params.aroon_trend_threshold
        and (aroon_up - aroon_down) >= params.aroon_spread_threshold
    )
    aroon_down_trend = (
        aroon_down >= params.aroon_trend_threshold
        and (aroon_down - aroon_up) >= params.aroon_spread_threshold
    )
    if breakout_up and aroon_up_trend:
        return 1
    if breakout_down and aroon_down_trend:
        return -1
    if (
        chop >= params.chop_range_threshold
        and abs(aroon_up - aroon_down) <= params.aroon_spread_threshold
        and efficiency <= params.efficiency_range_threshold
    ):
        return 0
    separation = abs(float(row.ema_fast) - float(row.ema_slow)) / float(row.atr)
    if separation < params.trend_separation_atr:
        return 0
    if float(row.ema_fast) > float(row.ema_slow) and float(row.plus_di) >= float(row.minus_di) and aroon_up >= aroon_down:
        return 1
    if float(row.ema_fast) < float(row.ema_slow) and float(row.minus_di) > float(row.plus_di) and aroon_down >= aroon_up:
        return -1
    return 0


def _trend_entry_ready(direction: int, row: object, params: V71LiveParams) -> bool:
    return direction != 0 and (
        float(row.adx) >= params.adx_enter
        or float(row.v71_chop) <= params.chop_trend_threshold
    )


def _trend_exit_ready(active_direction: int, direction: int, row: object, params: V71LiveParams) -> bool:
    daily_state = int(row.v71_daily_state)
    local_weak = (
        float(row.adx) <= params.adx_exit
        or float(row.v71_chop) >= params.chop_range_threshold
        or float(row.v71_efficiency_ratio) <= params.efficiency_range_threshold
    )
    if daily_state != active_direction and direction == daily_state:
        return True
    if direction == -active_direction or direction == 0:
        return local_weak or direction == -active_direction
    return local_weak and daily_state != active_direction


def _confirmed_state_transition(
    previous: str,
    direction: int,
    row: object,
    params: V71LiveParams,
    counters: dict[str, int],
    tradability_score: float,
) -> str:
    if not np.isfinite(row.adx) or not np.isfinite(row.v71_chop):
        return previous
    if previous not in (_MARKET_UP, _MARKET_DOWN):
        long_cooldown = int(counters.get("long_cooldown", 0))
        if long_cooldown > 0:
            counters["long_cooldown"] = long_cooldown - 1
        tradability_state = _tradability_state(tradability_score)
        if counters.get("probe_remaining", 0) > 0:
            counters["probe_remaining"] -= 1
            counters["trend"] = 0
            counters["trend_direction"] = 0
            return _MARKET_RANGE
        if tradability_state == _TRADABILITY_UNTRADABLE:
            counters["trend"] = 0
            counters["trend_direction"] = 0
            return _MARKET_RANGE
        if _trend_entry_ready(direction, row, params):
            confirm_bars = params.trend_confirm_bars
            last_trend_direction = int(counters.get("last_trend_direction", 0))
            weak_tradability = tradability_state == _TRADABILITY_WEAK
            if weak_tradability:
                confirm_bars += 1
                if int(row.v71_daily_state) != 0 and direction != int(row.v71_daily_state):
                    counters["trend"] = 0
                    counters["trend_direction"] = 0
                    return _MARKET_RANGE
            if last_trend_direction != 0 and direction != last_trend_direction:
                confirm_bars = max(confirm_bars, params.reversal_confirm_bars)
                if weak_tradability:
                    confirm_bars += 1
            if direction == counters["trend_direction"]:
                counters["trend"] += 1
            else:
                counters["trend_direction"] = direction
                counters["trend"] = 1
            if counters["trend"] >= confirm_bars:
                counters["trend"] = 0
                counters["last_trend_direction"] = direction
                return _MARKET_UP if direction > 0 else _MARKET_DOWN
        else:
            counters["trend_direction"] = 0
            counters["trend"] = 0
        return _MARKET_RANGE

    active_direction = 1 if previous == _MARKET_UP else -1
    counters["trend_direction"] = active_direction
    counters["trend"] = 0
    if _trend_exit_ready(active_direction, direction, row, params):
        counters["range"] += 1
        if counters["range"] >= params.trend_exit_confirm_bars:
            counters["range"] = 0
            counters["probe_remaining"] = params.post_trend_probe_bars
            counters["last_trend_direction"] = active_direction
            return _MARKET_RANGE
        return previous

    counters["range"] = 0
    return previous


def _should_rebalance(
    index: int,
    raw_signal: float,
    held_signal: float,
    params: V71LiveParams,
    *,
    force: bool = False,
) -> bool:
    if force or index % params.rebalance_bars == 0:
        return True
    if np.sign(raw_signal) != np.sign(held_signal):
        return True
    return abs(raw_signal - held_signal) >= params.min_rebalance_delta


def _speed_scale(row: object, direction: int, params: V71LiveParams) -> tuple[str, float, str]:
    if direction == 0:
        return _SPEED_NONE, 1.0, "none"

    fast = float(row.v71_fast_return) if np.isfinite(row.v71_fast_return) else 0.0
    medium = float(row.v71_medium_return) if np.isfinite(row.v71_medium_return) else 0.0
    previous_fast = float(row.v71_fast_return_prev) if np.isfinite(row.v71_fast_return_prev) else fast
    range_pct = float(row.v71_range_percentile) if np.isfinite(row.v71_range_percentile) else 0.5
    volume_speed = float(row.v71_volume_speed) if np.isfinite(row.v71_volume_speed) else 1.0
    previous_volume_speed = (
        float(row.v71_volume_speed_prev) if np.isfinite(row.v71_volume_speed_prev) else volume_speed
    )

    if direction > 0:
        rapid = fast >= params.rapid_return_threshold or medium >= params.rapid_medium_return_threshold
        stretched = row.rsi >= params.rapid_rsi_high or range_pct >= params.rapid_range_high
        price_decelerating = fast <= previous_fast - params.rapid_deceleration_min
        volume_decelerating = volume_speed <= previous_volume_speed * params.volume_deceleration_scale
        adverse = fast <= -params.adverse_return_threshold or medium <= -params.adverse_medium_return_threshold
    else:
        rapid = fast <= -params.rapid_return_threshold or medium <= -params.rapid_medium_return_threshold
        stretched = row.rsi <= params.rapid_rsi_low or range_pct <= params.rapid_range_low
        price_decelerating = fast >= previous_fast + params.rapid_deceleration_min
        volume_decelerating = volume_speed <= previous_volume_speed * params.volume_deceleration_scale
        adverse = fast >= params.adverse_return_threshold or medium >= params.adverse_medium_return_threshold
    decelerating = price_decelerating and volume_decelerating

    mode = _SPEED_RAPID if rapid and stretched else _SPEED_NORMAL
    scale = 1.0
    reasons: list[str] = []
    if mode == _SPEED_RAPID and decelerating:
        scale *= params.rapid_deceleration_scale
        reasons.append("deceleration")
    if adverse:
        scale *= params.adverse_shock_scale
        reasons.append("adverse")
    if mode == _SPEED_RAPID:
        reasons.insert(0, "rapid")
    return mode, scale, "+".join(reasons) if reasons else "none"


def _factor_params(params: V71LiveParams) -> SimpleNamespace:
    return SimpleNamespace(
        momentum_factor_enabled=False,
        momentum_factor_threshold=0.0,
        momentum_factor_scale=1.0,
        funding_factor_enabled=True,
        funding_lookback=params.funding_lookback,
        funding_high_threshold=params.funding_high_threshold,
        funding_factor_scale=params.funding_factor_scale,
        momentum_factor_period=params.speed_medium_period,
    )


def _downside_trigger(frame: pd.DataFrame, params: V71LiveParams) -> pd.Series:
    lookback_return = frame["close"].pct_change(params.downside_lookback)
    one_bar_return = frame["close"].pct_change()
    price_confirmation = frame["close"] < frame["ema_fast"]
    negative_confirmation = (
        (one_bar_return < 0)
        .rolling(params.downside_confirmation_bars, min_periods=params.downside_confirmation_bars)
        .sum()
        >= params.downside_confirmation_bars
    )
    return_signal = (
        (lookback_return <= params.downside_return_threshold)
        | (one_bar_return <= params.downside_return_threshold / 2)
    ) & (price_confirmation | negative_confirmation)
    vol_signal = (
        frame["v71_vol_ratio"] >= params.downside_vol_ratio
    ) & (frame["v71_vol_momentum"] < 0)
    return (return_signal | (vol_signal & (one_bar_return < 0))).fillna(False)


def generate_v71_live_signals(
    data: pd.DataFrame,
    params: V71LiveParams = V71LiveParams(),
) -> pd.DataFrame:
    """Generate live-oriented V7.1 signals and explicit protective levels."""

    frame = add_indicators(
        data,
        ema_fast=params.ema_fast,
        ema_slow=params.ema_slow,
        atr_period=params.atr_period,
        rsi_period=params.rsi_period,
        bb_period=params.bb_period,
        bb_std=params.bb_std,
        adx_period=params.adx_period,
    )
    frame["v71_daily_state"] = _daily_market_state(frame, params)
    frame["v71_chop"] = choppiness_index(frame, params.chop_period)
    frame["v71_aroon_up"], frame["v71_aroon_down"] = aroon(frame, params.aroon_period)
    frame["v71_efficiency_ratio"] = _efficiency_ratio(frame["close"], params.efficiency_period)
    frame["v71_donchian_high"], frame["v71_donchian_low"] = _donchian_channels(frame, params.donchian_lookback)
    frame["v71_close_breakout_high"], frame["v71_close_breakout_low"] = _close_channels(
        frame, params.donchian_lookback
    )
    factor_params = _factor_params(params)
    _factor_diagnostics(frame, factor_params)
    frame["v71_vol_risk_scale"] = _volatility_risk_scale(frame, params)
    _allocation_scale(frame, params)
    _price_drawdown_scale(frame, params)
    frame["v71_range_percentile"] = _range_percentile(frame["close"], params.range_lookback)
    _speed_diagnostics(frame, params)
    frame["v71_downside_trigger"] = _downside_trigger(frame, params)

    periods_per_year = 365 * 24 / 4
    annualized_vol = (frame["atr_pct"] * np.sqrt(periods_per_year)).replace(0, np.nan)
    base_size = (params.target_vol / annualized_vol).clip(lower=0, upper=params.max_leverage).fillna(0.0)

    raw_signals = np.zeros(len(frame), dtype=float)
    speed_scales = np.ones(len(frame), dtype=float)
    speed_modes = np.full(len(frame), _SPEED_NONE, dtype=object)
    speed_reasons = np.full(len(frame), "none", dtype=object)
    market_states = np.full(len(frame), "warmup", dtype=object)
    regimes = np.full(len(frame), "warmup", dtype=object)
    daily_biases = np.full(len(frame), "warmup", dtype=object)
    trigger_directions = np.zeros(len(frame), dtype=int)
    trend_quality_scores = np.zeros(len(frame), dtype=float)
    tradability_scores = np.zeros(len(frame), dtype=float)
    tradability_states = np.full(len(frame), "warmup", dtype=object)
    direction_contexts = np.full(len(frame), "warmup", dtype=object)
    permission_scales = np.zeros(len(frame), dtype=float)
    permission_reasons = np.full(len(frame), "warmup", dtype=object)
    initial_confirm_multipliers = np.ones(len(frame), dtype=float)
    continuation_add_on_multipliers = np.ones(len(frame), dtype=float)
    short_initial_confirm_multipliers = np.ones(len(frame), dtype=float)

    market_state = "warmup"
    held_signal = 0.0
    range_position_active = False
    range_entry = np.nan
    range_age = 0
    trend_extreme = np.nan
    trend_age = 0
    trend_start_permission_reason = "warmup"
    trend_start_quality = float("nan")
    state_counters = {
        "trend": 0,
        "trend_direction": 0,
        "last_trend_direction": 0,
        "range": 0,
        "probe_remaining": 0,
        "adverse": 0,
        "long_cooldown": 0,
        "long_continuation_evidence": 0,
    }

    for i, row in enumerate(frame.itertuples()):
        ready = all(
            np.isfinite(getattr(row, key))
            for key in (
                "ema_fast",
                "ema_slow",
                "atr",
                "adx",
                "v71_daily_state",
                "v71_range_percentile",
                "v71_efficiency_ratio",
                "v71_chop",
                "v71_aroon_up",
                "v71_aroon_down",
            )
        )
        if not ready:
            continue

        daily_biases[i] = _daily_bias_label(int(row.v71_daily_state))
        previous_market_state = market_state
        direction_hint = _market_direction(row, params)
        trigger_directions[i] = direction_hint
        trend_quality_scores[i] = _trend_quality_score(row, direction_hint, params)
        tradability_scores[i] = _tradability_score(row, params, direction_hint, trend_quality_scores[i])
        tradability_states[i] = _tradability_state(tradability_scores[i])
        long_cooldown_active = int(state_counters.get("long_cooldown", 0)) > 0
        if long_cooldown_active and params.long_fast_fail_quality_max > 0:
            long_cooldown_active = (
                direction_hint > 0 and trend_quality_scores[i] <= params.long_fast_fail_quality_max
            )
        direction_contexts[i] = _direction_context(
            direction_hint,
            int(row.v71_daily_state),
            tradability_states[i],
            trend_quality_scores[i],
            params,
        )
        market_state = _confirmed_state_transition(
            market_state,
            direction_hint,
            row,
            params,
            state_counters,
            tradability_scores[i],
        )
        if previous_market_state == _MARKET_UP and market_state == _MARKET_RANGE and _should_arm_long_fast_fail_cooldown(
            trend_age,
            trend_start_permission_reason,
            trend_start_quality,
            params,
        ):
            state_counters["long_cooldown"] = max(
                int(state_counters.get("long_cooldown", 0)),
                params.long_fast_fail_cooldown_bars,
            )
        market_states[i] = market_state

        if market_state in (_MARKET_UP, _MARKET_DOWN):
            range_position_active = False
            range_entry = np.nan
            range_age = 0
            direction = 1.0 if market_state == _MARKET_UP else -1.0
            permission_scale, permission_reason, direction_context = _trend_permission(
                int(direction),
                row,
                tradability_scores[i],
                trend_quality_scores[i],
                params,
            long_cooldown_active=long_cooldown_active,
            )
            permission_scales[i] = permission_scale
            permission_reasons[i] = permission_reason
            direction_contexts[i] = direction_context
            if market_state != previous_market_state and direction > 0:
                trend_start_permission_reason = permission_reason
                trend_start_quality = trend_quality_scores[i]
            fast_return = float(row.v71_fast_return) if np.isfinite(row.v71_fast_return) else 0.0
            medium_return = float(row.v71_medium_return) if np.isfinite(row.v71_medium_return) else 0.0
            adverse_move = (
                fast_return <= -params.adverse_return_threshold
                or medium_return <= -params.adverse_medium_return_threshold
                if direction > 0
                else fast_return >= params.adverse_return_threshold
                or medium_return >= params.adverse_medium_return_threshold
            )
            if params.adverse_exit_enabled and adverse_move:
                state_counters["adverse"] += 1
            else:
                state_counters["adverse"] = 0
            if params.adverse_exit_enabled and state_counters["adverse"] >= params.adverse_exit_confirm_bars:
                market_state = _MARKET_RANGE
                market_states[i] = market_state
                state_counters["adverse"] = 0
                state_counters["long_continuation_evidence"] = 0
                state_counters["probe_remaining"] = params.post_trend_probe_bars
                state_counters["last_trend_direction"] = int(direction)
                if direction > 0 and _should_arm_long_fast_fail_cooldown(
                    trend_age,
                    trend_start_permission_reason,
                    trend_start_quality,
                    params,
                ):
                    state_counters["long_cooldown"] = max(
                        int(state_counters.get("long_cooldown", 0)),
                        params.long_fast_fail_cooldown_bars,
                    )
                trend_age = 0
                trend_start_permission_reason = "warmup"
                trend_start_quality = float("nan")
                held_signal = 0.0
                raw_signals[i] = 0.0
                speed_modes[i] = _SPEED_NONE
                speed_reasons[i] = "adverse_exit"
                regimes[i] = "adverse_exit"
                trend_extreme = np.nan
                continue
            if market_state != previous_market_state:
                trend_extreme = row.close
                trend_age = 1
            elif np.isfinite(trend_extreme):
                trend_extreme = max(trend_extreme, row.close) if direction > 0 else min(trend_extreme, row.close)
                trend_age += 1
            else:
                trend_extreme = row.close
                trend_age = 1
            trailing_stop_hit = False
            if direction > 0 and np.isfinite(trend_extreme):
                trailing_stop_hit = row.close <= trend_extreme - params.trend_trailing_stop_atr * row.atr
            elif direction < 0 and np.isfinite(trend_extreme):
                trailing_stop_hit = row.close >= trend_extreme + params.trend_trailing_stop_atr * row.atr
            if trailing_stop_hit:
                market_state = _MARKET_RANGE
                market_states[i] = market_state
                state_counters["range"] = 0
                state_counters["long_continuation_evidence"] = 0
                state_counters["probe_remaining"] = params.post_trend_probe_bars
                state_counters["last_trend_direction"] = int(direction)
                if direction > 0 and _should_arm_long_fast_fail_cooldown(
                    trend_age,
                    trend_start_permission_reason,
                    trend_start_quality,
                    params,
                ):
                    state_counters["long_cooldown"] = max(
                        int(state_counters.get("long_cooldown", 0)),
                        params.long_fast_fail_cooldown_bars,
                    )
                trend_age = 0
                trend_start_permission_reason = "warmup"
                trend_start_quality = float("nan")
                held_signal = 0.0
                raw_signals[i] = 0.0
                speed_modes[i] = _SPEED_NONE
                speed_reasons[i] = "trend_trailing_stop"
                regimes[i] = "trend_stop"
                trend_extreme = np.nan
                continue
            if permission_scale <= 0:
                state_counters["long_continuation_evidence"] = 0
                held_signal = 0.0
                raw_signals[i] = 0.0
                speed_modes[i] = _SPEED_NONE
                speed_reasons[i] = permission_reason
                regimes[i] = "trend_long_wait" if direction > 0 else "trend_short_wait"
                continue

            speed_mode, speed_scale, reason = _speed_scale(row, int(direction), params)
            control_scale = (
                float(row.v71_vol_risk_scale)
                * _factor_scale(row, direction, factor_params)
                * (
                    float(row.v71_long_allocation_scale)
                    if direction > 0
                    else float(row.v71_short_allocation_scale)
                )
                * speed_scale
            )
            if direction > 0:
                control_scale *= float(row.v71_drawdown_risk_scale)
            raw_signal = direction * min(
                float(base_size.iloc[i])
                * params.trend_scale
                * (params.short_scale if direction < 0 else 1.0)
                * control_scale,
                params.max_leverage * permission_scale,
                params.max_leverage,
                10.0,
            )
            probe_active = (
                direction > 0
                and params.long_entry_probe_bars > 0
                and trend_age <= params.long_entry_probe_bars
            )
            if probe_active:
                raw_signal *= params.long_entry_probe_scale
            initial_confirm_multiplier = 1.0
            previous_initial_confirm_multiplier = initial_confirm_multipliers[i - 1] if i > 0 else 1.0
            if direction > 0:
                initial_confirm_transition = i == 0 or permission_reasons[i - 1] != "confirmed_long"
                initial_confirm_multiplier = _initial_confirmed_long_scale_multiplier(
                    trend_age,
                    permission_reason,
                    trend_quality_scores[i],
                    params,
                    first_fill_transition=initial_confirm_transition,
                )
                raw_signal *= initial_confirm_multiplier
            initial_confirm_multipliers[i] = initial_confirm_multiplier
            initial_confirm_active = direction > 0 and initial_confirm_multiplier < 1.0 - 1e-12
            previous_short_initial_confirm_multiplier = short_initial_confirm_multipliers[i - 1] if i > 0 else 1.0
            short_initial_confirm_multiplier = 1.0
            if direction < 0:
                short_initial_confirm_multiplier = _short_initial_confirm_multiplier(
                    trend_age,
                    permission_reason,
                    params,
                )
                raw_signal *= short_initial_confirm_multiplier
            short_initial_confirm_multipliers[i] = short_initial_confirm_multiplier
            short_initial_confirm_active = direction < 0 and short_initial_confirm_multiplier < 1.0 - 1e-12
            if (
                direction > 0
                and permission_reason == "confirmed_long"
                and trend_age >= params.long_continuation_add_on_min_bars
                and (
                    params.long_continuation_add_on_quality_min <= 0
                    or trend_quality_scores[i] >= params.long_continuation_add_on_quality_min
                )
                and (
                    params.long_continuation_add_on_tradability_min <= 0
                    or tradability_scores[i] >= params.long_continuation_add_on_tradability_min
                )
            ):
                state_counters["long_continuation_evidence"] += 1
            else:
                state_counters["long_continuation_evidence"] = 0
            previous_continuation_add_on_multiplier = continuation_add_on_multipliers[i - 1] if i > 0 else 1.0
            continuation_add_on_multiplier = _long_continuation_add_on_multiplier(
                trend_age,
                permission_reason,
                tradability_scores[i],
                trend_quality_scores[i],
                state_counters["long_continuation_evidence"],
                params,
            )
            continuation_add_on_multipliers[i] = continuation_add_on_multiplier
            if direction > 0 and continuation_add_on_multiplier > 1.0 + 1e-12:
                raw_signal = direction * min(abs(raw_signal) * continuation_add_on_multiplier, params.max_leverage, 10.0)
            continuation_add_on_active = direction > 0 and continuation_add_on_multiplier > 1.0 + 1e-12
            cooldown_probe_active = direction > 0 and permission_reason == "cooldown_probe_long"
            if cooldown_probe_active:
                raw_signal *= params.long_fast_fail_probe_scale
            state_changed = market_state != previous_market_state
            probe_promotion = (
                direction > 0
                and params.long_entry_probe_bars > 0
                and trend_age == params.long_entry_probe_bars + 1
            )
            cooldown_probe_promotion = cooldown_probe_active and (
                i == 0 or permission_reasons[i - 1] != "cooldown_probe_long"
            )
            initial_confirm_promotion = initial_confirm_active and previous_initial_confirm_multiplier >= 1.0 - 1e-12
            initial_confirm_release = (
                direction > 0
                and initial_confirm_multiplier >= 1.0 - 1e-12
                and previous_initial_confirm_multiplier < 1.0 - 1e-12
            )
            short_initial_confirm_promotion = (
                short_initial_confirm_active and previous_short_initial_confirm_multiplier >= 1.0 - 1e-12
            )
            short_initial_confirm_release = (
                direction < 0
                and short_initial_confirm_multiplier >= 1.0 - 1e-12
                and previous_short_initial_confirm_multiplier < 1.0 - 1e-12
            )
            continuation_add_on_promotion = (
                continuation_add_on_active and previous_continuation_add_on_multiplier <= 1.0 + 1e-12
            )
            continuation_add_on_release = (
                direction > 0
                and continuation_add_on_multiplier <= 1.0 + 1e-12
                and previous_continuation_add_on_multiplier > 1.0 + 1e-12
            )
            if _should_rebalance(
                i,
                raw_signal,
                held_signal,
                params,
                force=(
                    state_changed
                    or probe_promotion
                    or cooldown_probe_promotion
                    or initial_confirm_promotion
                    or initial_confirm_release
                    or short_initial_confirm_promotion
                    or short_initial_confirm_release
                    or continuation_add_on_promotion
                    or continuation_add_on_release
                ),
            ):
                held_signal = raw_signal
            raw_signals[i] = held_signal
            permission_scales[i] = permission_scale
            speed_scales[i] = speed_scale
            speed_modes[i] = speed_mode
            speed_reasons[i] = permission_reason if reason == "none" else f"{permission_reason}+{reason}"
            if probe_active:
                speed_reasons[i] = f"{speed_reasons[i]}+entry_probe"
            if initial_confirm_active:
                speed_reasons[i] = f"{speed_reasons[i]}+initial_confirm"
            if short_initial_confirm_active:
                speed_reasons[i] = f"{speed_reasons[i]}+short_initial_confirm"
            if continuation_add_on_active:
                speed_reasons[i] = f"{speed_reasons[i]}+continuation_add_on"
            regimes[i] = "trend_long" if direction > 0 else "trend_short"
            continue

        if state_counters["probe_remaining"] > 0:
            state_counters["long_continuation_evidence"] = 0
            trend_extreme = np.nan
            trend_age = 0
            trend_start_permission_reason = "warmup"
            trend_start_quality = float("nan")
            held_signal = 0.0
            raw_signals[i] = 0.0
            speed_modes[i] = _SPEED_NONE
            speed_reasons[i] = "trend_probe"
            regimes[i] = "range_wait"
            continue

        exit_range = False
        if range_position_active:
            range_age += 1
            stop_hit = np.isfinite(range_entry) and row.close <= range_entry - params.range_stop_atr * row.atr
            breakout_exit = direction_hint != 0 and (
                float(row.adx) >= params.adx_enter
                or float(row.v71_chop) <= params.chop_trend_threshold
            )
            aroon_breakout = (
                direction_hint != 0
                and abs(float(row.v71_aroon_up) - float(row.v71_aroon_down))
                >= 2 * params.aroon_spread_threshold
            )
            exit_range = (
                row.v71_range_percentile >= params.range_exit_percentile
                or stop_hit
                or breakout_exit
                or aroon_breakout
                or row.v71_daily_state < 0
                or row.v71_efficiency_ratio >= params.efficiency_trend_threshold
                or range_age >= params.range_max_bars
            )
            if exit_range:
                range_position_active = False
                range_entry = np.nan
                range_age = 0
                trend_extreme = np.nan
                trend_age = 0
        elif (
            row.v71_range_percentile <= params.range_entry_percentile
            and row.v71_chop >= params.chop_range_threshold
            and row.v71_daily_state >= 0
            and row.v71_efficiency_ratio <= params.efficiency_range_threshold
        ):
            range_position_active = True
            range_entry = row.close
            range_age = 0
            trend_extreme = np.nan

        if range_position_active:
            range_permission_scale, range_permission_reason, range_context = _range_permission(
                row,
                tradability_scores[i],
                trend_quality_scores[i],
                params,
            )
            permission_scales[i] = range_permission_scale
            permission_reasons[i] = range_permission_reason
            direction_contexts[i] = range_context
            if range_permission_scale <= 0:
                state_counters["long_continuation_evidence"] = 0
                range_position_active = False
                range_entry = np.nan
                range_age = 0
                held_signal = 0.0
                raw_signals[i] = 0.0
                speed_modes[i] = _SPEED_NONE
                speed_reasons[i] = range_permission_reason
                regimes[i] = "range_wait"
                trend_extreme = np.nan
                trend_age = 0
                continue
            control_scale = (
                float(row.v71_vol_risk_scale)
                * _factor_scale(row, 1.0, factor_params)
                * float(row.v71_long_allocation_scale)
                * float(row.v71_drawdown_risk_scale)
            )
            raw_signal = min(
                float(base_size.iloc[i]) * params.rebound_scale * control_scale * range_permission_scale,
                params.max_leverage * range_permission_scale,
                params.max_leverage,
                10.0,
            )
            if _should_rebalance(i, raw_signal, held_signal, params):
                held_signal = raw_signal
            raw_signals[i] = held_signal
            speed_modes[i] = _SPEED_NONE
            speed_reasons[i] = range_permission_reason
            regimes[i] = "range_long"
        else:
            permission_scales[i] = 0.0
            permission_reasons[i] = "range_wait"
            if direction_contexts[i] == "neutral_wait":
                direction_contexts[i] = "range_wait"
            held_signal = 0.0
            raw_signals[i] = 0.0
            speed_modes[i] = _SPEED_NONE
            speed_reasons[i] = "range_exit" if exit_range else "range_wait"
            regimes[i] = "range_exit" if exit_range else "range_flat"
            trend_extreme = np.nan
            trend_age = 0

    signal = np.array(raw_signals, copy=True)
    stop_price = np.full(len(frame), np.nan)
    take_profit = np.full(len(frame), np.nan)
    entry_price = np.full(len(frame), np.nan)
    live_reason = np.full(len(frame), "", dtype=object)
    if params.live_protection_enabled:
        active_direction = 0.0
        active_entry = np.nan
        active_stop = np.nan
        active_take = np.nan
        active_peak = np.nan
        age = 0
        cooldown = 0
        previous_raw_side = 0.0

        for i, row in enumerate(frame.itertuples()):
            desired = float(raw_signals[i])
            desired_side = float(np.sign(desired))
            if cooldown > 0:
                cooldown -= 1
                if desired_side == previous_raw_side:
                    desired = 0.0
                    desired_side = 0.0

            if desired_side != 0 and desired_side != active_direction:
                active_direction = desired_side
                active_entry = float(row.close)
                active_peak = active_entry
                stop_atr = params.stop_atr
                if active_direction > 0 and _long_strong_protection_active(
                    permission_reasons[i],
                    tradability_scores[i],
                    trend_quality_scores[i],
                    params,
                ):
                    stop_atr += params.long_strong_protection_atr_bonus
                active_stop = active_entry - stop_atr * float(row.atr) * active_direction
                take_profit_atr = params.take_profit_atr
                if active_direction > 0 and _long_strong_take_profit_active(
                    permission_reasons[i],
                    tradability_scores[i],
                    trend_quality_scores[i],
                    params,
                ):
                    take_profit_atr += params.long_strong_take_profit_atr_bonus
                active_take = active_entry + take_profit_atr * float(row.atr) * active_direction
                age = 0
                live_reason[i] = "new_entry"
            elif desired_side == 0 and active_direction != 0:
                active_direction = 0.0
                active_entry = np.nan
                active_stop = np.nan
                active_take = np.nan
                active_peak = np.nan
                age = 0

            protective_exit = False
            if active_direction != 0 and np.isfinite(active_entry) and np.isfinite(row.atr):
                age += 1
                if active_direction > 0:
                    active_peak = max(float(active_peak), float(row.close))
                    trailing_stop_atr = params.trailing_stop_atr
                    if _long_strong_protection_active(
                        permission_reasons[i],
                        tradability_scores[i],
                        trend_quality_scores[i],
                        params,
                    ):
                        trailing_stop_atr += params.long_strong_protection_atr_bonus
                    active_stop = max(
                        float(active_stop),
                        float(active_peak) - trailing_stop_atr * float(row.atr),
                    )
                    if _long_take_profit_extension_active(
                        trend_age,
                        permission_reasons[i],
                        tradability_scores[i],
                        trend_quality_scores[i],
                        params,
                    ):
                        active_take = max(
                            float(active_take),
                            float(active_peak) + params.long_take_profit_extension_atr * float(row.atr),
                        )
                    fast_trigger = bool(row.v71_downside_trigger) if params.downside_protection_enabled else False
                    if fast_trigger:
                        active_stop = max(
                            float(active_stop),
                            float(row.close) - params.downside_stop_atr * float(row.atr),
                        )
                        live_reason[i] = "fast_downside_stop"
                    protective_exit = (
                        float(row.close) <= float(active_stop)
                        or float(row.close) >= float(active_take)
                        or age >= params.max_hold_bars
                        or fast_trigger
                    )
                else:
                    active_peak = min(float(active_peak), float(row.close))
                    active_stop = min(
                        float(active_stop),
                        float(active_peak) + params.trailing_stop_atr * float(row.atr),
                    )
                    protective_exit = (
                        float(row.close) >= float(active_stop)
                        or float(row.close) <= float(active_take)
                        or age >= params.max_hold_bars
                    )

            if protective_exit:
                desired = 0.0
                desired_side = 0.0
                cooldown = params.exit_cooldown_bars
                if not live_reason[i]:
                    live_reason[i] = "protective_exit"

            signal[i] = desired
            if abs(desired) < 1e-12:
                active_direction = 0.0
                active_entry = np.nan
                active_stop = np.nan
                active_take = np.nan
                active_peak = np.nan
                age = 0
            entry_price[i] = active_entry
            stop_price[i] = active_stop
            take_profit[i] = active_take
            previous_raw_side = float(np.sign(raw_signals[i]))

    frame["raw_signal"] = raw_signals
    frame["signal"] = signal
    frame["leverage"] = np.abs(signal)
    frame["regime"] = regimes
    frame["v71_market_state"] = market_states
    frame["v71_daily_bias"] = daily_biases
    frame["v71_trigger_direction"] = trigger_directions
    frame["v71_trend_quality_score"] = trend_quality_scores
    frame["v71_tradability_score"] = tradability_scores
    frame["v71_tradability_state"] = tradability_states
    frame["v71_direction_context"] = direction_contexts
    frame["v71_permission_scale"] = permission_scales
    frame["v71_permission_reason"] = permission_reasons
    frame["v71_speed_mode"] = speed_modes
    frame["v71_speed_scale"] = speed_scales
    frame["v71_speed_reason"] = speed_reasons
    frame["entry_price"] = entry_price
    frame["stop_price"] = stop_price
    frame["take_profit_price"] = take_profit
    frame["v71_live_reason"] = live_reason
    return frame


__all__ = ["V71LiveParams", "generate_v71_live_signals"]
