"""V7 mutually exclusive trend/range strategy with rapid-move control."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from types import SimpleNamespace

import numpy as np
import pandas as pd

from .indicators import add_indicators, realized_volatility
from .strategy import _factor_diagnostics, _factor_scale


_MARKET_RANGE = "range"
_MARKET_UP = "trend_up"
_MARKET_DOWN = "trend_down"
_SPEED_NONE = "none"
_SPEED_NORMAL = "normal"
_SPEED_RAPID = "rapid"


@dataclass(frozen=True)
class V7Params:
    """Parameters for the V7 mutually exclusive market-state strategy."""

    ema_fast: int = 30
    ema_slow: int = 120
    atr_period: int = 20
    adx_period: int = 14
    adx_enter: float = 26.0
    adx_exit: float = 18.0
    trend_separation_atr: float = 0.1
    rsi_period: int = 14
    rsi_entry: float = 27.0
    rsi_exit: float = 52.0
    bb_period: int = 24
    bb_std: float = 2.0
    target_vol: float = 1.075
    max_leverage: float = 6.5
    trend_scale: float = 1.25
    rebound_scale: float = 0.65
    allow_short: bool = True
    rebalance_bars: int = 48
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
    range_lookback: int = 90
    range_entry_percentile: float = 0.2
    range_exit_percentile: float = 0.78
    range_stop_atr: float = 2.2
    range_max_bars: int = 18
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
    rapid_deceleration_scale: float = 0.55
    adverse_return_threshold: float = 0.07
    adverse_medium_return_threshold: float = 0.1
    adverse_shock_scale: float = 0.35
    volume_deceleration_scale: float = 0.75

    def __post_init__(self) -> None:
        if not 0 < self.max_leverage <= 10:
            raise ValueError("max_leverage must be in (0, 10]")
        if self.ema_fast < 2 or self.ema_slow <= self.ema_fast:
            raise ValueError("ema_slow must exceed ema_fast >= 2")
        if self.adx_exit <= 0 or self.adx_enter <= self.adx_exit:
            raise ValueError("adx_enter must exceed a positive adx_exit")
        if self.rebalance_bars < 1:
            raise ValueError("rebalance_bars must be positive")
        if self.range_lookback < 2 or self.range_max_bars < 1:
            raise ValueError("range lookback and max bars must be positive")
        if not 0 < self.range_entry_percentile < self.range_exit_percentile < 1:
            raise ValueError("range entry percentile must be below range exit percentile")
        if self.speed_fast_period < 1 or self.speed_medium_period <= self.speed_fast_period:
            raise ValueError("speed periods must be strictly ordered")
        if self.speed_slow_period <= self.speed_medium_period:
            raise ValueError("speed_slow_period must exceed speed_medium_period")
        if not 0 < self.rapid_return_threshold < self.rapid_medium_return_threshold:
            raise ValueError("rapid thresholds must be strictly ordered")
        if not 0 < self.rapid_range_low < self.rapid_range_high < 1:
            raise ValueError("rapid range thresholds must be ordered within (0, 1)")
        if not 0 < self.rapid_deceleration_scale <= 1:
            raise ValueError("rapid_deceleration_scale must be in (0, 1]")
        if not 0 < self.adverse_shock_scale <= 1:
            raise ValueError("adverse_shock_scale must be in (0, 1]")
        if not 0 < self.volume_deceleration_scale <= 1:
            raise ValueError("volume_deceleration_scale must be in (0, 1]")
        if not 0 <= self.downside_calm_threshold < self.downside_stress_threshold <= 1:
            raise ValueError("downside thresholds must be ordered")
        if not 0 < self.vol_shock_scale <= 1:
            raise ValueError("vol_shock_scale must be in (0, 1]")
        if self.vol_shock_enter <= self.vol_shock_exit or self.vol_shock_exit <= 0:
            raise ValueError("volatility shock thresholds must be ordered")
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


def _volatility_risk_scale(frame: pd.DataFrame, params: V7Params) -> pd.Series:
    periods_per_year = 365 * 24 // 4
    frame["v7_realized_vol"] = realized_volatility(
        frame["close"], params.realized_vol_period, periods_per_year
    )
    frame["v7_vol_baseline"] = frame["v7_realized_vol"].ewm(
        span=params.vol_baseline_period,
        adjust=False,
        min_periods=params.vol_baseline_period,
    ).mean()
    frame["v7_vol_ratio"] = frame["v7_realized_vol"] / frame["v7_vol_baseline"].replace(0, np.nan)
    frame["v7_vol_momentum"] = frame["close"].pct_change(params.vol_momentum_period)

    risk_scale = np.ones(len(frame), dtype=float)
    risk_off = False
    for i, row in enumerate(frame[["v7_vol_ratio", "v7_vol_momentum"]].itertuples(index=False)):
        if not np.isfinite(row.v7_vol_ratio) or not np.isfinite(row.v7_vol_momentum):
            continue
        if risk_off:
            if row.v7_vol_ratio <= params.vol_shock_exit or row.v7_vol_momentum >= 0:
                risk_off = False
        elif row.v7_vol_ratio >= params.vol_shock_enter and row.v7_vol_momentum < 0:
            risk_off = True
        if risk_off:
            risk_scale[i] = params.vol_shock_scale
    return pd.Series(risk_scale, index=frame.index)


def _allocation_scale(frame: pd.DataFrame, params: V7Params) -> pd.Series:
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
    frame["v7_downside_share"] = np.sqrt(downside_variance / total_variance.replace(0, np.nan))
    frame["v7_upside_share"] = np.sqrt(upside_variance / total_variance.replace(0, np.nan))

    def scale_from_adverse_share(adverse_share: pd.Series) -> pd.Series:
        scale = np.ones(len(frame), dtype=float)
        calm = adverse_share <= params.downside_calm_threshold
        stress = adverse_share >= params.downside_stress_threshold
        scale[calm.fillna(False).to_numpy()] = params.downside_calm_boost
        scale[stress.fillna(False).to_numpy()] = params.downside_stress_scale
        return pd.Series(scale, index=frame.index)

    long_scale = scale_from_adverse_share(frame["v7_downside_share"])
    short_scale = scale_from_adverse_share(frame["v7_upside_share"])
    frame["v7_long_allocation_scale"] = long_scale
    frame["v7_short_allocation_scale"] = short_scale
    return long_scale


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


def _speed_diagnostics(frame: pd.DataFrame, params: V7Params) -> None:
    close = frame["close"]
    frame["v7_fast_return"] = close.pct_change(params.speed_fast_period)
    frame["v7_medium_return"] = close.pct_change(params.speed_medium_period)
    frame["v7_slow_return"] = close.pct_change(params.speed_slow_period)
    frame["v7_fast_return_prev"] = frame["v7_fast_return"].shift(1)
    quote_volume = frame.get("quote_volume", pd.Series(1.0, index=frame.index)).replace(0, np.nan)
    baseline = quote_volume.ewm(span=max(params.speed_slow_period * 6, 12), adjust=False).mean()
    frame["v7_volume_speed"] = quote_volume / baseline.replace(0, np.nan)
    frame["v7_volume_speed_prev"] = frame["v7_volume_speed"].shift(1)


def _market_direction(row: object, params: V7Params) -> int:
    if not all(np.isfinite(getattr(row, key)) for key in ("ema_fast", "ema_slow", "atr", "plus_di", "minus_di")):
        return 0
    separation = abs(float(row.ema_fast) - float(row.ema_slow)) / float(row.atr)
    if separation < params.trend_separation_atr:
        return 0
    if float(row.ema_fast) > float(row.ema_slow) and float(row.plus_di) >= float(row.minus_di):
        return 1
    if float(row.ema_fast) < float(row.ema_slow) and float(row.minus_di) > float(row.plus_di):
        return -1
    return 0


def _state_transition(previous: str, direction: int, row: object, params: V7Params) -> str:
    if not np.isfinite(row.adx):
        return previous
    if previous == _MARKET_UP:
        if row.adx <= params.adx_exit or direction == 0:
            return _MARKET_RANGE
        if direction < 0 and row.adx >= params.adx_enter:
            return _MARKET_DOWN
        return _MARKET_UP
    if previous == _MARKET_DOWN:
        if row.adx <= params.adx_exit or direction == 0:
            return _MARKET_RANGE
        if direction > 0 and row.adx >= params.adx_enter:
            return _MARKET_UP
        return _MARKET_DOWN
    if row.adx >= params.adx_enter and direction != 0:
        return _MARKET_UP if direction > 0 else _MARKET_DOWN
    return _MARKET_RANGE


def _speed_scale(row: object, direction: int, params: V7Params) -> tuple[str, float, str]:
    if direction == 0:
        return _SPEED_NONE, 1.0, "none"

    fast = float(row.v7_fast_return) if np.isfinite(row.v7_fast_return) else 0.0
    medium = float(row.v7_medium_return) if np.isfinite(row.v7_medium_return) else 0.0
    previous_fast = float(row.v7_fast_return_prev) if np.isfinite(row.v7_fast_return_prev) else fast
    range_pct = float(row.v7_range_percentile) if np.isfinite(row.v7_range_percentile) else 0.5
    volume_speed = float(row.v7_volume_speed) if np.isfinite(row.v7_volume_speed) else 1.0
    previous_volume_speed = (
        float(row.v7_volume_speed_prev) if np.isfinite(row.v7_volume_speed_prev) else volume_speed
    )

    if direction > 0:
        rapid = fast >= params.rapid_return_threshold or medium >= params.rapid_medium_return_threshold
        stretched = row.rsi >= params.rapid_rsi_high or range_pct >= params.rapid_range_high
        decelerating = (
            fast <= previous_fast - params.rapid_deceleration_min
            or volume_speed <= previous_volume_speed * params.volume_deceleration_scale
        )
        adverse = fast <= -params.adverse_return_threshold or medium <= -params.adverse_medium_return_threshold
    else:
        rapid = fast <= -params.rapid_return_threshold or medium <= -params.rapid_medium_return_threshold
        stretched = row.rsi <= params.rapid_rsi_low or range_pct <= params.rapid_range_low
        decelerating = (
            fast >= previous_fast + params.rapid_deceleration_min
            or volume_speed <= previous_volume_speed * params.volume_deceleration_scale
        )
        adverse = fast >= params.adverse_return_threshold or medium >= params.adverse_medium_return_threshold

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


def _v7_factor_params(params: V7Params):
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


def generate_v7_signals(data: pd.DataFrame, params: V7Params = V7Params()) -> pd.DataFrame:
    """Generate causal V7 target exposure.

    The primary market state is mutually exclusive: ``range``, ``trend_up`` or
    ``trend_down``.  Trend states are further split into ``normal`` and
    ``rapid`` speed modes.  Range entries and exits use rolling percentiles.
    """

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
    factor_params = _v7_factor_params(params)
    _factor_diagnostics(frame, factor_params)
    frame["v7_vol_risk_scale"] = _volatility_risk_scale(frame, params)
    frame["v7_allocation_scale"] = _allocation_scale(frame, params)
    frame["v7_range_percentile"] = _range_percentile(frame["close"], params.range_lookback)
    _speed_diagnostics(frame, params)

    periods_per_year = 365 * 24 / 4
    annualized_vol = (frame["atr_pct"] * np.sqrt(periods_per_year)).replace(0, np.nan)
    base_size = (params.target_vol / annualized_vol).clip(lower=0, upper=params.max_leverage).fillna(0.0)

    signals = np.zeros(len(frame), dtype=float)
    speed_scales = np.ones(len(frame), dtype=float)
    speed_modes = np.full(len(frame), _SPEED_NONE, dtype=object)
    speed_reasons = np.full(len(frame), "none", dtype=object)
    market_states = np.full(len(frame), "warmup", dtype=object)
    regimes = np.full(len(frame), "warmup", dtype=object)

    market_state = "warmup"
    held_signal = 0.0
    previous_control_scale = 1.0
    range_position_active = False
    range_entry = np.nan
    range_age = 0

    for i, row in enumerate(frame.itertuples()):
        ready = all(
            np.isfinite(getattr(row, key))
            for key in ("ema_fast", "ema_slow", "atr", "adx", "v7_range_percentile")
        )
        if not ready:
            continue

        previous_market_state = market_state
        direction_hint = _market_direction(row, params)
        market_state = _state_transition(market_state, direction_hint, row, params)
        market_states[i] = market_state

        if market_state in (_MARKET_UP, _MARKET_DOWN):
            range_position_active = False
            range_entry = np.nan
            range_age = 0

            direction = 1.0 if market_state == _MARKET_UP else -1.0
            if direction < 0 and not params.allow_short:
                held_signal = 0.0
                signals[i] = 0.0
                speed_modes[i] = _SPEED_NONE
                speed_reasons[i] = "short_disabled"
                regimes[i] = "trend_short"
                previous_control_scale = 1.0
                continue

            speed_mode, speed_scale, reason = _speed_scale(row, int(direction), params)
            control_scale = (
                float(row.v7_vol_risk_scale)
                * _factor_scale(row, direction, factor_params)
                * (
                    float(row.v7_long_allocation_scale)
                    if direction > 0
                    else float(row.v7_short_allocation_scale)
                )
                * speed_scale
            )
            raw_signal = direction * min(
                float(base_size.iloc[i]) * params.trend_scale * control_scale,
                params.max_leverage,
                10.0,
            )
            control_changed = abs(control_scale - previous_control_scale) > 1e-12
            state_changed = market_state != previous_market_state
            if (
                i % params.rebalance_bars == 0
                or np.sign(raw_signal) != np.sign(held_signal)
                or control_changed
                or state_changed
            ):
                held_signal = raw_signal
            signals[i] = held_signal
            speed_scales[i] = speed_scale
            speed_modes[i] = speed_mode
            speed_reasons[i] = reason
            regimes[i] = "trend_long" if direction > 0 else "trend_short"
            previous_control_scale = control_scale
            continue

        # Range state: percentile-based accumulation and exit.
        exit_range = False
        if range_position_active:
            range_age += 1
            stop_hit = np.isfinite(range_entry) and row.close <= range_entry - params.range_stop_atr * row.atr
            exit_range = (
                row.v7_range_percentile >= params.range_exit_percentile
                or stop_hit
                or range_age >= params.range_max_bars
            )
            if exit_range:
                range_position_active = False
                range_entry = np.nan
                range_age = 0
        elif row.v7_range_percentile <= params.range_entry_percentile:
            range_position_active = True
            range_entry = row.close
            range_age = 0

        if range_position_active:
            control_scale = (
                float(row.v7_vol_risk_scale)
                * _factor_scale(row, 1.0, factor_params)
                * float(row.v7_long_allocation_scale)
            )
            raw_signal = min(
                float(base_size.iloc[i]) * params.rebound_scale * control_scale,
                params.max_leverage,
                10.0,
            )
            control_changed = abs(control_scale - previous_control_scale) > 1e-12
            if i % params.rebalance_bars == 0 or np.sign(raw_signal) != np.sign(held_signal) or control_changed:
                held_signal = raw_signal
            signals[i] = held_signal
            speed_scales[i] = 1.0
            speed_modes[i] = _SPEED_NONE
            speed_reasons[i] = "range_percentile"
            regimes[i] = "range_long"
            previous_control_scale = control_scale
        else:
            held_signal = 0.0
            signals[i] = 0.0
            speed_scales[i] = 1.0
            speed_modes[i] = _SPEED_NONE
            speed_reasons[i] = "range_exit" if exit_range else "range_wait"
            regimes[i] = "range_exit" if exit_range else "range_flat"
            previous_control_scale = 1.0

    frame["signal"] = signals
    frame["leverage"] = np.abs(signals)
    frame["regime"] = regimes
    frame["v7_market_state"] = market_states
    frame["v7_speed_mode"] = speed_modes
    frame["v7_speed_scale"] = speed_scales
    frame["v7_speed_reason"] = speed_reasons
    return frame
