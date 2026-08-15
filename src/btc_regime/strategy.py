"""Causal regime-switching signal generation for BTCUSDT perpetual."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .indicators import add_indicators, realized_volatility


@dataclass(frozen=True)
class StrategyParams:
    ema_fast: int = 30
    ema_slow: int = 120
    atr_period: int = 20
    adx_period: int = 14
    adx_enter: float = 27.0
    adx_exit: float = 18.0
    trend_separation_atr: float = 0.15
    rsi_period: int = 14
    rsi_entry: float = 27.0
    rsi_exit: float = 52.0
    bb_period: int = 24
    bb_std: float = 2.0
    mr_stop_atr: float = 2.2
    mr_max_bars: int = 18
    target_vol: float = 0.35
    max_leverage: float = 3.0
    trend_scale: float = 1.0
    rebound_scale: float = 0.65
    allow_short: bool = False
    # 72 x 4h = 12 days; direction changes still apply immediately.
    rebalance_bars: int = 72
    vol_risk_enabled: bool = False
    realized_vol_period: int = 24
    vol_baseline_period: int = 180
    vol_shock_enter: float = 1.5
    vol_shock_exit: float = 1.1
    vol_shock_scale: float = 0.5
    vol_momentum_period: int = 18
    momentum_factor_enabled: bool = False
    momentum_factor_period: int = 24
    momentum_factor_threshold: float = 0.0
    momentum_factor_scale: float = 0.5
    funding_factor_enabled: bool = False
    funding_lookback: int = 18
    funding_high_threshold: float = 0.0002
    funding_factor_scale: float = 0.5
    downside_allocation_enabled: bool = False
    downside_vol_period: int = 24
    downside_calm_threshold: float = 0.4
    downside_stress_threshold: float = 0.6
    downside_calm_boost: float = 1.25
    downside_stress_scale: float = 0.5
    drawdown_brake_enabled: bool = False
    price_drawdown_lookback: int = 360
    price_drawdown_enter: float = 0.2
    price_drawdown_exit: float = 0.1
    price_drawdown_scale: float = 0.5

    def __post_init__(self) -> None:
        if not 0 <= self.max_leverage <= 10:
            raise ValueError("max_leverage must be between 0 and 10")
        if self.rebalance_bars < 1:
            raise ValueError("rebalance_bars must be positive")
        if self.realized_vol_period < 2 or self.vol_baseline_period < 2:
            raise ValueError("volatility periods must be at least 2")
        if self.vol_momentum_period < 1:
            raise ValueError("vol_momentum_period must be positive")
        if not 0 <= self.vol_shock_scale <= 1:
            raise ValueError("vol_shock_scale must be between 0 and 1")
        if self.vol_shock_enter <= self.vol_shock_exit or self.vol_shock_exit <= 0:
            raise ValueError("vol_shock_enter must exceed a positive vol_shock_exit")
        if self.momentum_factor_period < 1 or self.funding_lookback < 1:
            raise ValueError("factor lookback periods must be positive")
        if not 0 <= self.momentum_factor_scale <= 1:
            raise ValueError("momentum_factor_scale must be between 0 and 1")
        if not 0 <= self.funding_factor_scale <= 1:
            raise ValueError("funding_factor_scale must be between 0 and 1")
        if self.funding_high_threshold < 0:
            raise ValueError("funding_high_threshold must be non-negative")
        if self.downside_vol_period < 2 or self.price_drawdown_lookback < 2:
            raise ValueError("allocation lookback periods must be at least 2")
        if not 0 <= self.downside_calm_threshold < self.downside_stress_threshold <= 1:
            raise ValueError("downside thresholds must be ordered within [0, 1]")
        if not 1 <= self.downside_calm_boost <= 2:
            raise ValueError("downside_calm_boost must be between 1 and 2")
        if not 0 <= self.downside_stress_scale <= 1:
            raise ValueError("downside_stress_scale must be between 0 and 1")
        if not 0 < self.price_drawdown_exit < self.price_drawdown_enter < 1:
            raise ValueError("price drawdown thresholds must be ordered within (0, 1)")
        if not 0 <= self.price_drawdown_scale <= 1:
            raise ValueError("price_drawdown_scale must be between 0 and 1")

    def to_dict(self) -> dict[str, float | int | bool]:
        return asdict(self)


def _volatility_risk_layer(frame: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    """Add causal volatility diagnostics and a hysteretic risk multiplier."""
    p = params
    periods_per_year = 365 * 24 // 4
    frame["realized_vol"] = realized_volatility(
        frame["close"], p.realized_vol_period, periods_per_year
    )
    frame["vol_baseline"] = frame["realized_vol"].ewm(
        span=p.vol_baseline_period,
        adjust=False,
        min_periods=p.vol_baseline_period,
    ).mean()
    frame["vol_ratio"] = frame["realized_vol"] / frame["vol_baseline"].replace(0, np.nan)
    frame["vol_momentum"] = frame["close"].pct_change(p.vol_momentum_period)

    risk_scale = np.ones(len(frame), dtype=float)
    risk_off = False
    if p.vol_risk_enabled:
        for i, row in enumerate(frame[["vol_ratio", "vol_momentum"]].itertuples(index=False)):
            if not np.isfinite(row.vol_ratio) or not np.isfinite(row.vol_momentum):
                continue
            if risk_off:
                if row.vol_ratio <= p.vol_shock_exit or row.vol_momentum >= 0:
                    risk_off = False
            elif row.vol_ratio >= p.vol_shock_enter and row.vol_momentum < 0:
                risk_off = True
            if risk_off:
                risk_scale[i] = p.vol_shock_scale
    frame["vol_risk_scale"] = risk_scale
    return frame


def _factor_diagnostics(frame: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    """Add causal momentum and funding-crowding measurements."""
    frame["trend_momentum"] = frame["close"].pct_change(params.momentum_factor_period)
    funding = frame.get("funding_rate", pd.Series(0.0, index=frame.index)).fillna(0.0)
    frame["funding_ema"] = funding.ewm(
        span=params.funding_lookback,
        adjust=False,
        min_periods=params.funding_lookback,
    ).mean()
    return frame


def _factor_scale(row: object, direction: float, params: StrategyParams) -> float:
    """Return a directional cost/momentum penalty for the current signal."""
    scale = 1.0
    if params.momentum_factor_enabled and np.isfinite(row.trend_momentum):
        if direction * float(row.trend_momentum) < params.momentum_factor_threshold:
            scale *= params.momentum_factor_scale
    if params.funding_factor_enabled and np.isfinite(row.funding_ema):
        # Positive directed funding means this position pays crowded carry.
        if direction * float(row.funding_ema) > params.funding_high_threshold:
            scale *= params.funding_factor_scale
    return scale


def _allocation_layer(frame: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    """Allocate more risk to calm trends and brake prolonged price drawdowns."""
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
    frame["downside_share"] = np.sqrt(
        downside_variance / total_variance.replace(0, np.nan)
    )

    allocation_scale = np.ones(len(frame), dtype=float)
    if params.downside_allocation_enabled:
        calm = frame["downside_share"] <= params.downside_calm_threshold
        stress = frame["downside_share"] >= params.downside_stress_threshold
        allocation_scale[calm.fillna(False).to_numpy()] = params.downside_calm_boost
        allocation_scale[stress.fillna(False).to_numpy()] = params.downside_stress_scale

    rolling_peak = frame["close"].rolling(
        params.price_drawdown_lookback,
        min_periods=params.price_drawdown_lookback,
    ).max()
    frame["price_drawdown"] = frame["close"] / rolling_peak - 1
    drawdown_scale = np.ones(len(frame), dtype=float)
    brake_active = False
    if params.drawdown_brake_enabled:
        for i, value in enumerate(frame["price_drawdown"]):
            if not np.isfinite(value):
                continue
            if brake_active:
                if value >= -params.price_drawdown_exit:
                    brake_active = False
            elif value <= -params.price_drawdown_enter:
                brake_active = True
            if brake_active:
                drawdown_scale[i] = params.price_drawdown_scale
    frame["drawdown_risk_scale"] = drawdown_scale
    frame["allocation_scale"] = allocation_scale * drawdown_scale
    return frame


def generate_signals(data: pd.DataFrame, params: StrategyParams = StrategyParams()) -> pd.DataFrame:
    """Return indicators, regime labels and desired signed exposure.

    Signals are calculated only from the current completed candle. The backtester
    applies the signal to the following candle, so no close-to-close lookahead is used.
    """
    p = params
    frame = add_indicators(
        data,
        ema_fast=p.ema_fast,
        ema_slow=p.ema_slow,
        atr_period=p.atr_period,
        rsi_period=p.rsi_period,
        bb_period=p.bb_period,
        bb_std=p.bb_std,
        adx_period=p.adx_period,
    )
    frame = _volatility_risk_layer(frame, p)
    frame = _factor_diagnostics(frame, p)
    frame = _allocation_layer(frame, p)
    periods_per_year = 365 * 24 / 4
    annualized_vol = (frame["atr_pct"] * np.sqrt(periods_per_year)).replace(0, np.nan)
    base_size = (p.target_vol / annualized_vol).clip(lower=0, upper=p.max_leverage).fillna(0.0)
    def sized(value: float, scale: float) -> float:
        return min(float(value) * scale, p.max_leverage, 10.0)
    signals = np.zeros(len(frame), dtype=float)
    regime = np.full(len(frame), "warmup", dtype=object)
    trend_active = False
    mr_active = False
    mr_entry = np.nan
    mr_age = 0
    held_signal = 0.0
    previous_control_scale = 1.0

    for i, row in enumerate(frame.itertuples()):
        values_ready = np.isfinite(row.ema_fast) and np.isfinite(row.ema_slow) and np.isfinite(row.atr)
        if not values_ready:
            continue
        if trend_active:
            if row.adx <= p.adx_exit:
                trend_active = False
        elif row.adx >= p.adx_enter:
            trend_active = True

        if trend_active:
            mr_active = False
            mr_age = 0
            separation = abs(row.ema_fast - row.ema_slow) / row.atr if row.atr else 0
            if separation >= p.trend_separation_atr:
                direction = 1.0 if row.ema_fast > row.ema_slow and row.plus_di >= row.minus_di else -1.0
                control_scale = (
                    float(row.vol_risk_scale)
                    * _factor_scale(row, direction, p)
                    * float(row.allocation_scale)
                )
                raw_size = min(
                    sized(base_size.iloc[i], p.trend_scale) * control_scale,
                    p.max_leverage,
                    10.0,
                )
                raw_signal = direction * raw_size
                if direction < 0 and not p.allow_short:
                    raw_signal = 0.0
                control_changed = control_scale != previous_control_scale
                if i % p.rebalance_bars == 0 or np.sign(raw_signal) != np.sign(held_signal) or control_changed:
                    held_signal = raw_signal
                signals[i] = held_signal
                previous_control_scale = control_scale
                regime[i] = "trend_long" if direction > 0 else "trend_short"
            else:
                regime[i] = "trend_flat"
            continue

        regime[i] = "range"
        if mr_active:
            mr_age += 1
            stop_hit = np.isfinite(mr_entry) and row.close <= mr_entry - p.mr_stop_atr * row.atr
            if row.rsi >= p.rsi_exit or row.close >= row.bb_mid or stop_hit or mr_age >= p.mr_max_bars:
                mr_active = False
                mr_entry = np.nan
                mr_age = 0
        elif row.rsi <= p.rsi_entry and row.close <= row.bb_lower:
            mr_active = True
            mr_entry = row.close
            mr_age = 0
        if mr_active:
            control_scale = (
                float(row.vol_risk_scale)
                * _factor_scale(row, 1.0, p)
                * float(row.allocation_scale)
            )
            raw_signal = min(
                sized(base_size.iloc[i], p.rebound_scale) * control_scale,
                p.max_leverage,
                10.0,
            )
            control_changed = control_scale != previous_control_scale
            if i % p.rebalance_bars == 0 or np.sign(raw_signal) != np.sign(held_signal) or control_changed:
                held_signal = raw_signal
            signals[i] = held_signal
            previous_control_scale = control_scale
            regime[i] = "rebound_long"
        elif i % p.rebalance_bars == 0:
            held_signal = 0.0
            signals[i] = 0.0

    frame["signal"] = signals
    frame["regime"] = regime
    frame["leverage"] = np.abs(signals)
    return frame
