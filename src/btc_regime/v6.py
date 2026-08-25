"""V6 confidence-driven multi-timeframe BTCUSDT strategy.

The V6 layer is deliberately separate from :mod:`btc_regime.strategy` so the
frozen V1-V5 implementations remain unchanged.  Signals are causal: the daily
regime is shifted to the next UTC day, and all 4h indicators use the current
completed candle only.  The returned frame includes executable risk levels for
the minute-level simulator.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .indicators import add_indicators, realized_volatility


@dataclass(frozen=True)
class V6Params:
    """Bounded V6 parameters used by the fixed leverage-optimized profile."""

    ema_fast: int = 24
    ema_slow: int = 120
    atr_period: int = 20
    adx_period: int = 14
    adx_enter: float = 24.0
    adx_exit: float = 17.0
    trend_separation_atr: float = 0.08
    rsi_period: int = 14
    rsi_entry: float = 29.0
    rsi_exit: float = 52.0
    bb_period: int = 24
    bb_std: float = 2.0
    target_vol: float = 1.8
    max_leverage: float = 6.5
    short_scale: float = 0.35
    rebalance_bars: int = 12
    confidence_probe: float = 0.52
    confidence_full: float = 0.68
    confidence_exit: float = 0.43
    momentum_period: int = 18
    momentum_scale_pct: float = 0.08
    funding_lookback: int = 6
    funding_penalty_threshold: float = 0.00012
    funding_penalty_scale: float = 0.45
    realized_vol_period: int = 24
    vol_baseline_period: int = 180
    vol_shock_enter: float = 1.35
    vol_shock_exit: float = 1.10
    vol_shock_scale: float = 0.35
    drawdown_lookback: int = 360
    drawdown_enter: float = 0.12
    drawdown_exit: float = 0.06
    drawdown_scale: float = 0.45
    risk_per_trade: float = 0.05
    stop_atr: float = 2.0
    take_profit_atr: float = 3.0
    trailing_atr: float = 2.2
    max_hold_bars: int = 72
    probe_scale: float = 0.40
    rebound_scale: float = 0.35
    allow_short: bool = True

    def __post_init__(self) -> None:
        if self.ema_fast < 2 or self.ema_slow <= self.ema_fast:
            raise ValueError("ema_slow must exceed ema_fast >= 2")
        if self.max_leverage <= 0 or self.max_leverage > 10:
            raise ValueError("max_leverage must be in (0, 10]")
        if not 0 < self.short_scale <= 1:
            raise ValueError("short_scale must be in (0, 1]")
        if self.rebalance_bars < 1 or self.max_hold_bars < 1:
            raise ValueError("bar limits must be positive")
        if not 0 < self.confidence_exit < self.confidence_probe < self.confidence_full <= 1:
            raise ValueError("confidence thresholds must be ordered in (0, 1]")
        if self.stop_atr <= 0 or self.take_profit_atr <= 0 or self.trailing_atr <= 0:
            raise ValueError("ATR risk distances must be positive")
        if not 0 < self.risk_per_trade < 0.1:
            raise ValueError("risk_per_trade must be in (0, 0.1)")
        if not 0 < self.drawdown_exit < self.drawdown_enter < 1:
            raise ValueError("drawdown thresholds must be ordered")

    def to_dict(self) -> dict[str, float | int | bool]:
        return asdict(self)


def _daily_regime(close: pd.Series, fast: int, slow: int) -> pd.Series:
    """Return the last completed UTC day's trend regime at each 4h bar."""
    daily = close.resample("1D").last().dropna()
    fast_ema = daily.ewm(span=fast, adjust=False, min_periods=fast).mean()
    slow_ema = daily.ewm(span=slow, adjust=False, min_periods=slow).mean()
    state = pd.Series(0.0, index=daily.index)
    state[(fast_ema > slow_ema) & (daily > slow_ema)] = 1.0
    state[(fast_ema < slow_ema) & (daily < slow_ema)] = -1.0
    # The value labelled at midnight is only available after that day closes.
    state.index = state.index + pd.Timedelta(days=1)
    return state.reindex(close.index, method="ffill").fillna(0.0)


def _scale_from_drawdown(price_drawdown: pd.Series, params: V6Params) -> pd.Series:
    scale = np.ones(len(price_drawdown), dtype=float)
    active = False
    for i, value in enumerate(price_drawdown):
        if not np.isfinite(value):
            continue
        if active:
            if value >= -params.drawdown_exit:
                active = False
        elif value <= -params.drawdown_enter:
            active = True
        if active:
            scale[i] = params.drawdown_scale
    return pd.Series(scale, index=price_drawdown.index)


def _confidence(frame: pd.DataFrame, params: V6Params) -> pd.DataFrame:
    direction = np.where(
        (frame["ema_fast"] > frame["ema_slow"]) & (frame["plus_di"] >= frame["minus_di"]),
        1.0,
        np.where(
            (frame["ema_fast"] < frame["ema_slow"])
            & (frame["minus_di"] > frame["plus_di"]),
            -1.0,
            0.0,
        ),
    )
    frame["v6_direction"] = direction
    separation = (frame["ema_fast"] - frame["ema_slow"]).abs() / frame["atr"].replace(0, np.nan)
    frame["v6_separation"] = separation
    trend_score = (separation / 0.30).clip(0.0, 1.0)
    adx_score = ((frame["adx"] - params.adx_exit) / (params.adx_enter + 10 - params.adx_exit)).clip(0.0, 1.0)
    di_score = ((frame["plus_di"] - frame["minus_di"]).abs() / 35.0).clip(0.0, 1.0)
    momentum = frame["close"].pct_change(params.momentum_period)
    directed_momentum = frame["v6_direction"] * momentum
    momentum_score = (0.5 + directed_momentum / (2 * params.momentum_scale_pct)).clip(0.0, 1.0)

    funding = frame.get("funding_rate", pd.Series(0.0, index=frame.index)).fillna(0.0)
    funding_ema = funding.ewm(
        span=params.funding_lookback, adjust=False, min_periods=params.funding_lookback
    ).mean()
    frame["v6_funding_ema"] = funding_ema
    directed_funding = frame["v6_direction"] * funding_ema
    funding_cost = ((directed_funding - params.funding_penalty_threshold) / 0.00025).clip(0.0, 1.0)
    funding_score = 1.0 - params.funding_penalty_scale * funding_cost

    daily = _daily_regime(frame["close"], params.ema_fast // 2, max(params.ema_slow // 4, 30))
    frame["v6_daily_regime"] = daily
    daily_alignment = pd.Series(0.65, index=frame.index)
    daily_alignment[frame["v6_direction"] * daily > 0] = 1.0
    daily_alignment[frame["v6_direction"] * daily < 0] = 0.30

    confidence = (
        0.30 * trend_score
        + 0.25 * adx_score
        + 0.18 * di_score
        + 0.17 * momentum_score
        + 0.10 * funding_score
    ) * daily_alignment
    frame["v6_confidence"] = confidence.clip(0.0, 1.0).fillna(0.0)
    frame["v6_momentum"] = momentum
    return frame


def generate_v6_signals(data: pd.DataFrame, params: V6Params = V6Params()) -> pd.DataFrame:
    """Generate causal V6 exposure plus stop/take-profit price levels."""
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
    periods_per_year = 365 * 24 / 4
    frame["v6_realized_vol"] = realized_volatility(
        frame["close"], params.realized_vol_period, int(periods_per_year)
    )
    frame["v6_vol_baseline"] = frame["v6_realized_vol"].ewm(
        span=params.vol_baseline_period, adjust=False, min_periods=params.vol_baseline_period
    ).mean()
    vol_ratio = frame["v6_realized_vol"] / frame["v6_vol_baseline"].replace(0, np.nan)
    vol_scale = pd.Series(1.0, index=frame.index)
    vol_scale[(vol_ratio >= params.vol_shock_enter) & (frame["close"].pct_change(36) < 0)] = params.vol_shock_scale
    frame["v6_vol_scale"] = vol_scale
    rolling_peak = frame["close"].rolling(params.drawdown_lookback, min_periods=params.drawdown_lookback).max()
    price_drawdown = frame["close"] / rolling_peak - 1.0
    frame["v6_price_drawdown"] = price_drawdown
    frame["v6_drawdown_scale"] = _scale_from_drawdown(price_drawdown, params)
    frame = _confidence(frame, params)

    annualized_vol = (frame["atr_pct"] * np.sqrt(periods_per_year)).replace(0, np.nan)
    vol_size = (params.target_vol / annualized_vol).clip(lower=0, upper=params.max_leverage).fillna(0.0)
    risk_size = (params.risk_per_trade / (params.stop_atr * frame["atr_pct"])).clip(
        lower=0, upper=params.max_leverage
    ).fillna(0.0)
    base_size = pd.concat([vol_size, risk_size], axis=1).min(axis=1)

    signal = np.zeros(len(frame), dtype=float)
    stop_price = np.full(len(frame), np.nan)
    take_profit = np.full(len(frame), np.nan)
    entry_price = np.full(len(frame), np.nan)
    confidence_state = np.zeros(len(frame), dtype=float)
    states = np.full(len(frame), "warmup", dtype=object)
    held_signal = 0.0
    active_state = "flat"
    active_direction = 0.0
    active_entry = np.nan
    active_stop = np.nan
    active_take = np.nan
    active_peak = np.nan
    age = 0
    trend_active = False
    drawdown_scale = 1.0

    for i, row in enumerate(frame.itertuples()):
        ready = all(np.isfinite(getattr(row, key)) for key in ("ema_fast", "ema_slow", "atr", "adx"))
        if not ready:
            continue
        if trend_active:
            if row.adx <= params.adx_exit:
                trend_active = False
        elif row.adx >= params.adx_enter:
            trend_active = True

        direction = float(row.v6_direction)
        confidence = float(row.v6_confidence)
        confidence_state[i] = confidence
        new_state = "flat"
        target = 0.0
        if (
            trend_active
            and direction != 0
            and row.v6_separation >= params.trend_separation_atr
            and confidence >= params.confidence_probe
        ):
            if direction < 0 and not params.allow_short:
                direction = 0.0
            if direction != 0:
                new_state = "full" if confidence >= params.confidence_full else "probe"
                scale = 1.0 if new_state == "full" else params.probe_scale
                if direction < 0:
                    scale *= params.short_scale
                scale *= float(row.v6_vol_scale) * float(row.v6_drawdown_scale)
                target = direction * min(float(base_size.iloc[i]) * scale, params.max_leverage)
        elif (
            not trend_active
            and row.rsi <= params.rsi_entry
            and row.close <= row.bb_lower
            and float(row.v6_daily_regime) >= 0
        ):
            new_state = "rebound"
            target = min(float(base_size.iloc[i]) * params.rebound_scale * float(row.v6_drawdown_scale), params.max_leverage)

        protective_exit = False
        if active_state != "flat" and np.isfinite(active_entry):
            age += 1
            if active_direction > 0:
                active_peak = max(float(active_peak), float(row.close))
                trailing = float(active_peak) - params.trailing_atr * float(row.atr)
                active_stop = max(float(active_stop), trailing)
                protective_exit = (
                    row.close <= active_stop
                    or row.close >= active_take
                    or age >= params.max_hold_bars
                )
            else:
                active_peak = min(float(active_peak), float(row.close))
                trailing = float(active_peak) + params.trailing_atr * float(row.atr)
                active_stop = min(float(active_stop), trailing)
                protective_exit = (
                    row.close >= active_stop
                    or row.close <= active_take
                    or age >= params.max_hold_bars
                )
        if protective_exit or (active_state != "flat" and confidence < params.confidence_exit):
            new_state = "flat"
            target = 0.0

        control_changed = abs(target - held_signal) > 0.12 or np.sign(target) != np.sign(held_signal)
        if i % params.rebalance_bars == 0 or control_changed or new_state == "flat" or new_state != active_state:
            held_signal = target
        else:
            target = held_signal
        signal[i] = held_signal
        states[i] = new_state if held_signal == target else active_state

        if abs(held_signal) > 1e-12 and (active_state == "flat" or np.sign(held_signal) != active_direction):
            active_direction = float(np.sign(held_signal))
            active_entry = float(row.close)
            distance = params.stop_atr * float(row.atr)
            reward = params.take_profit_atr * float(row.atr)
            active_stop = active_entry - distance if active_direction > 0 else active_entry + distance
            active_take = active_entry + reward if active_direction > 0 else active_entry - reward
            active_peak = active_entry
            age = 0
        elif abs(held_signal) < 1e-12:
            active_direction = 0.0
            active_entry = np.nan
            active_stop = np.nan
            active_take = np.nan
            active_peak = np.nan
            age = 0
        active_state = "flat" if abs(held_signal) < 1e-12 else new_state
        entry_price[i] = active_entry
        stop_price[i] = active_stop
        take_profit[i] = active_take

    frame["signal"] = signal
    frame["leverage"] = np.abs(signal)
    frame["entry_price"] = entry_price
    frame["stop_price"] = stop_price
    frame["take_profit_price"] = take_profit
    frame["signal_confidence"] = confidence_state
    frame["regime"] = states
    return frame
