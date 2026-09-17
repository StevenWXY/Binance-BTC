"""Bounded range-inventory strategy for BTCUSDT perpetuals.

This module is intentionally separate from the directional V4/V7 engines.  It
uses the same completed 4h candle convention, but trades only when the market
looks range-bound.  The inventory ladder is capped and linear: adverse moves
can add one equal-sized layer, never a doubling layer.  A volatility shock,
Donchian break or hard ATR stop flattens the position and starts a short
cooldown.  These controls are the part that makes this a bounded grid rather
than an unbounded martingale.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .indicators import add_indicators, realized_volatility


@dataclass(frozen=True)
class RangeGridParams:
    """Parameters for the bounded, volatility-scaled range strategy."""

    ema_fast: int = 30
    ema_slow: int = 120
    atr_period: int = 20
    adx_period: int = 14
    rsi_period: int = 14
    bb_period: int = 24
    bb_std: float = 2.0

    # A range needs confirmation from more than one indicator.  Hysteresis
    # prevents an ADX/choppiness boundary from churning the strategy.
    range_adx_enter: float = 21.0
    range_adx_exit: float = 27.0
    chop_period: int = 14
    chop_enter: float = 57.0
    chop_exit: float = 47.0
    efficiency_period: int = 24
    efficiency_max: float = 0.24
    range_confirm_bars: int = 3
    range_exit_confirm_bars: int = 2

    # Entry/exit use the current completed candle's location in a rolling
    # channel.  The centre exit is intentionally much closer than the entry.
    channel_period: int = 24
    entry_percentile: float = 0.18
    exit_percentile: float = 0.52
    entry_reversal_required: bool = True
    entry_rsi_long_max: float = 48.0
    entry_rsi_short_min: float = 52.0
    breakout_buffer_atr: float = 0.30
    trend_guard_separation_atr: float = 0.45
    trend_guard_return: float = 0.035

    # Bounded inventory ladder.  Every layer is equal size; layers are reduced
    # as price recovers instead of being held until a full round trip.
    max_layers: int = 3
    layer_step_atr: float = 0.55
    max_hold_bars: int = 18
    stop_atr: float = 1.65
    cooldown_bars: int = 6

    target_vol: float = 0.35
    max_leverage: float = 1.50
    range_scale: float = 1.0
    short_scale: float = 0.85
    allow_short: bool = True
    fixed_entry_risk: bool = False
    risk_per_cycle: float = 0.0
    symmetric_vol_shock: bool = False

    # Volatility and carry gates protect the range sleeve from a regime break.
    realized_vol_period: int = 12
    vol_baseline_period: int = 90
    vol_shock_enter: float = 1.25
    vol_shock_exit: float = 1.10
    vol_shock_scale: float = 0.15
    vol_momentum_period: int = 12
    funding_lookback: int = 6
    funding_high_threshold: float = 0.00025
    funding_scale: float = 0.50

    def __post_init__(self) -> None:
        if self.ema_fast < 2 or self.ema_slow <= self.ema_fast:
            raise ValueError("ema_slow must exceed ema_fast >= 2")
        if self.atr_period < 2 or self.adx_period < 2:
            raise ValueError("indicator periods must be at least 2")
        if self.range_adx_exit <= self.range_adx_enter or self.range_adx_enter <= 0:
            raise ValueError("range ADX thresholds must be ordered")
        if not 0 < self.chop_exit < self.chop_enter < 100:
            raise ValueError("choppiness thresholds must be ordered")
        if self.efficiency_period < 2 or not 0 < self.efficiency_max <= 1:
            raise ValueError("efficiency settings are invalid")
        if min(self.range_confirm_bars, self.range_exit_confirm_bars) < 1:
            raise ValueError("range confirmation bars must be positive")
        if self.channel_period < 3:
            raise ValueError("channel_period must be at least 3")
        if not 0 < self.entry_percentile < self.exit_percentile < 1:
            raise ValueError("entry_percentile must be below exit_percentile")
        if not 0 < self.entry_rsi_long_max < self.entry_rsi_short_min < 100:
            raise ValueError("entry RSI thresholds must be ordered")
        if self.max_layers < 1 or self.layer_step_atr <= 0 or self.max_hold_bars < 1:
            raise ValueError("ladder settings must be positive")
        if self.stop_atr <= 0 or self.cooldown_bars < 0:
            raise ValueError("stop and cooldown settings are invalid")
        if not 0 < self.max_leverage <= 10 or self.target_vol <= 0:
            raise ValueError("target_vol and max_leverage must be positive")
        if not 0 <= self.short_scale <= 1 or not 0 < self.range_scale <= 2:
            raise ValueError("position scales are invalid")
        if not 0 <= self.risk_per_cycle <= 0.05:
            raise ValueError("risk_per_cycle must be between zero and 5%")
        if self.realized_vol_period < 2 or self.vol_baseline_period < 2:
            raise ValueError("volatility periods must be at least 2")
        if self.vol_shock_enter <= self.vol_shock_exit or self.vol_shock_exit <= 0:
            raise ValueError("volatility shock thresholds must be ordered")
        if not 0 < self.vol_shock_scale <= 1:
            raise ValueError("vol_shock_scale must be in (0, 1]")
        if self.vol_momentum_period < 1 or self.funding_lookback < 1:
            raise ValueError("factor periods must be positive")
        if self.funding_high_threshold < 0 or not 0 < self.funding_scale <= 1:
            raise ValueError("funding settings are invalid")

    def to_dict(self) -> dict[str, float | int | bool]:
        return asdict(self)


def _choppiness(frame: pd.DataFrame, period: int) -> pd.Series:
    previous = frame["close"].shift(1)
    true_range = pd.concat(
        [frame["high"] - frame["low"],
         (frame["high"] - previous).abs(),
         (frame["low"] - previous).abs()],
        axis=1,
    ).max(axis=1)
    path = true_range.rolling(period, min_periods=period).sum()
    high = frame["high"].rolling(period, min_periods=period).max()
    low = frame["low"].rolling(period, min_periods=period).min()
    span = (high - low).replace(0, np.nan)
    return 100 * np.log10(path / span) / np.log10(period)


def _efficiency_ratio(close: pd.Series, period: int) -> pd.Series:
    net = (close - close.shift(period)).abs()
    path = close.diff().abs().rolling(period, min_periods=period).sum()
    return net / path.replace(0, np.nan)


def _hysteretic_range_state(frame: pd.DataFrame, params: RangeGridParams) -> pd.Series:
    """Return a causal range state with confirmation and breakout veto."""
    state = np.zeros(len(frame), dtype=bool)
    active = False
    enter_count = 0
    exit_count = 0
    for i, row in enumerate(frame.itertuples()):
        values = (row.adx, row.rg_chop, row.rg_efficiency, row.atr)
        if not all(np.isfinite(value) for value in values):
            continue
        breakout = bool(row.rg_breakout_up or row.rg_breakout_down)
        raw_range = (
            row.adx <= params.range_adx_enter
            and row.rg_chop >= params.chop_enter
            and row.rg_efficiency <= params.efficiency_max
            and not breakout
        )
        raw_trend = (
            row.adx >= params.range_adx_exit
            or row.rg_chop <= params.chop_exit
            or row.rg_efficiency > params.efficiency_max * 1.35
            or breakout
        )
        if active:
            if raw_trend:
                exit_count += 1
                if exit_count >= params.range_exit_confirm_bars or breakout:
                    active = False
                    exit_count = 0
            else:
                exit_count = 0
        elif raw_range and not raw_trend:
            enter_count += 1
            if enter_count >= params.range_confirm_bars:
                active = True
                enter_count = 0
        else:
            enter_count = 0
        state[i] = active
    return pd.Series(state, index=frame.index, name="rg_range_active")


def _funding_scale(funding: float, direction: float, params: RangeGridParams) -> float:
    if not np.isfinite(funding) or direction == 0:
        return 1.0
    # A long pays positive funding; a short pays negative funding.
    if direction * funding > params.funding_high_threshold:
        return params.funding_scale
    return 1.0


def generate_range_grid_signals(
    data: pd.DataFrame,
    params: RangeGridParams = RangeGridParams(),
) -> pd.DataFrame:
    """Generate bounded range exposure and protective price diagnostics.

    Signals use the current completed candle and are intended for the next
    candle, matching :func:`btc_regime.strategy.generate_signals`.
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
    frame["rg_chop"] = _choppiness(frame, params.chop_period)
    frame["rg_efficiency"] = _efficiency_ratio(frame["close"], params.efficiency_period)
    channel_high = frame["high"].rolling(params.channel_period, min_periods=params.channel_period).max()
    channel_low = frame["low"].rolling(params.channel_period, min_periods=params.channel_period).min()
    frame["rg_channel_high"] = channel_high
    frame["rg_channel_low"] = channel_low
    frame["prev_close"] = frame["close"].shift(1)
    width = (channel_high - channel_low).replace(0, np.nan)
    frame["rg_location"] = ((frame["close"] - channel_low) / width).clip(0, 1)
    prior_high = frame["high"].rolling(params.channel_period, min_periods=params.channel_period).max().shift(1)
    prior_low = frame["low"].rolling(params.channel_period, min_periods=params.channel_period).min().shift(1)
    frame["rg_breakout_up"] = frame["close"] > prior_high + params.breakout_buffer_atr * frame["atr"]
    frame["rg_breakout_down"] = frame["close"] < prior_low - params.breakout_buffer_atr * frame["atr"]
    frame["rg_efficiency"] = frame["rg_efficiency"].clip(0, 1)

    periods_per_year = 365 * 24 / 4
    frame["rg_realized_vol"] = realized_volatility(
        frame["close"], params.realized_vol_period, int(periods_per_year)
    )
    frame["rg_vol_baseline"] = frame["rg_realized_vol"].ewm(
        span=params.vol_baseline_period,
        adjust=False,
        min_periods=params.vol_baseline_period,
    ).mean()
    frame["rg_vol_ratio"] = frame["rg_realized_vol"] / frame["rg_vol_baseline"].replace(0, np.nan)
    frame["rg_vol_momentum"] = frame["close"].pct_change(params.vol_momentum_period)
    frame["rg_funding_ema"] = frame.get(
        "funding_rate", pd.Series(0.0, index=frame.index)
    ).fillna(0.0).ewm(
        span=params.funding_lookback,
        adjust=False,
        min_periods=params.funding_lookback,
    ).mean()
    frame["rg_range_active"] = _hysteretic_range_state(frame, params)

    annualized_vol = (frame["atr_pct"] * np.sqrt(periods_per_year)).replace(0, np.nan)
    base_size = (params.target_vol / annualized_vol).clip(0, params.max_leverage).fillna(0.0)
    signals = np.zeros(len(frame), dtype=float)
    regimes = np.full(len(frame), "warmup", dtype=object)
    stop_prices = np.full(len(frame), np.nan)
    take_prices = np.full(len(frame), np.nan)
    entry_prices = np.full(len(frame), np.nan)
    layers = np.zeros(len(frame), dtype=int)
    cooldown_values = np.zeros(len(frame), dtype=int)
    entry_events = np.zeros(len(frame), dtype=bool)
    exit_events = np.zeros(len(frame), dtype=bool)
    cooldown = 0
    side = 0.0
    entry = np.nan
    age = 0
    entry_atr = np.nan
    entry_size = 0.0

    for i, row in enumerate(frame.itertuples()):
        ready = all(np.isfinite(getattr(row, key)) for key in (
            "ema_fast", "ema_slow", "atr", "adx", "rg_chop", "rg_efficiency",
            "rg_location", "rg_vol_ratio", "rg_funding_ema",
        ))
        if not ready:
            continue
        if cooldown > 0:
            cooldown -= 1
        active_range = bool(row.rg_range_active)
        location = float(row.rg_location)
        breakout = bool(row.rg_breakout_up or row.rg_breakout_down)
        momentum = abs(float(row.rg_vol_momentum)) if np.isfinite(row.rg_vol_momentum) else 0.0
        separation = abs(float(row.ema_fast) - float(row.ema_slow)) / max(float(row.atr), 1e-12)
        # EMA separation alone is not a trend signal: a range can sit above or
        # below its slow average for weeks.  Require directional strength as
        # well, otherwise the range sleeve would never get to trade.
        trend_guard = (
            separation >= max(1.20, params.trend_guard_separation_atr)
            and float(row.adx) >= params.range_adx_exit
        ) or momentum >= params.trend_guard_return
        vol_shock = (
            np.isfinite(row.rg_vol_ratio)
            and float(row.rg_vol_ratio) >= params.vol_shock_enter
            and np.isfinite(row.rg_vol_momentum)
            and (params.symmetric_vol_shock or float(row.rg_vol_momentum) < 0)
        )

        if side != 0:
            age += 1
            risk_atr = entry_atr if params.fixed_entry_risk else float(row.atr)
            adverse = side * (float(entry) - float(row.close)) / max(risk_atr, 1e-12)
            stop_hit = adverse >= params.stop_atr
            take_hit = (
                location >= params.exit_percentile if side > 0
                else location <= 1.0 - params.exit_percentile
            )
            force_exit = (
                not active_range or breakout or trend_guard or vol_shock
                or stop_hit or take_hit or age >= params.max_hold_bars
            )
            if force_exit:
                reason = "range_take" if take_hit else "range_risk_off"
                if breakout:
                    reason = "range_breakout"
                elif stop_hit:
                    reason = "range_stop"
                elif vol_shock:
                    reason = "range_vol_shock"
                regimes[i] = reason
                side = 0.0
                entry = np.nan
                age = 0
                layers[i] = 0
                exit_events[i] = True
                cooldown = params.cooldown_bars if reason != "range_take" else 1
        if side == 0 and active_range and cooldown == 0 and not breakout and not trend_guard and not vol_shock:
            long_reversal = (not params.entry_reversal_required) or (
                float(row.close) > float(row.prev_close) and float(row.rsi) <= params.entry_rsi_long_max
            )
            short_reversal = (not params.entry_reversal_required) or (
                float(row.close) < float(row.prev_close) and float(row.rsi) >= params.entry_rsi_short_min
            )
            if location <= params.entry_percentile and long_reversal:
                side = 1.0
                entry = float(row.close)
                entry_atr = float(row.atr)
                entry_size = float(base_size.iloc[i])
                age = 0
                layers[i] = 1
                entry_events[i] = True
                regimes[i] = "range_long"
            elif location >= 1.0 - params.entry_percentile and params.allow_short and short_reversal:
                side = -1.0
                entry = float(row.close)
                entry_atr = float(row.atr)
                entry_size = float(base_size.iloc[i])
                age = 0
                layers[i] = 1
                entry_events[i] = True
                regimes[i] = "range_short"

        if side != 0:
            risk_atr = entry_atr if params.fixed_entry_risk else float(row.atr)
            adverse = max(0.0, side * (float(entry) - float(row.close)) / max(risk_atr, 1e-12))
            # Equal layers, capped at max_layers.  There is no 1/2/4/... sizing.
            current_layers = min(params.max_layers, 1 + int(adverse / params.layer_step_atr))
            current_layers = max(1, current_layers)
            layers[i] = current_layers
            vol_scale = params.vol_shock_scale if vol_shock else 1.0
            funding_scale = _funding_scale(float(row.rg_funding_ema), side, params)
            ladder_scale = current_layers / params.max_layers
            direction_scale = 1.0 if side > 0 else params.short_scale
            desired = min(
                (entry_size if params.fixed_entry_risk else float(base_size.iloc[i]))
                * params.range_scale
                * ladder_scale
                * direction_scale
                * vol_scale
                * funding_scale,
                params.max_leverage,
                10.0,
            )
            if params.risk_per_cycle:
                # Full-basket risk budget under a fill at the specified stop.
                # Gaps, slippage and funding can make actual loss exceed it.
                risk_cap = params.risk_per_cycle / (params.stop_atr * risk_atr / float(entry))
                desired = min(desired, risk_cap * ladder_scale)
            signals[i] = side * desired
            regimes[i] = regimes[i] if regimes[i] != "warmup" else (
                "range_long" if side > 0 else "range_short"
            )
            stop_prices[i] = float(entry) - side * params.stop_atr * risk_atr
            # Mean reversion target is the channel's midpoint rather than a
            # distant take-profit, so inventory is recycled frequently.
            take_prices[i] = (float(row.rg_channel_high) + float(row.rg_channel_low)) / 2.0
            entry_prices[i] = float(entry)
        elif regimes[i] == "warmup":
            regimes[i] = "range_wait" if active_range else "trend_guard"
        cooldown_values[i] = cooldown

    frame["signal"] = signals
    frame["leverage"] = np.abs(signals)
    frame["regime"] = regimes
    frame["rg_layers"] = layers
    frame["entry_price"] = entry_prices
    frame["stop_price"] = stop_prices
    frame["take_profit_price"] = take_prices
    frame["rg_cooldown"] = cooldown_values
    frame["rg_entry_event"] = entry_events
    frame["rg_exit_event"] = exit_events
    return frame


def combine_range_overlay(
    trend_signals: pd.DataFrame,
    range_signals: pd.DataFrame,
    *,
    allocation: float = 0.25,
    max_leverage: float = 6.5,
) -> pd.DataFrame:
    """Add a small, bounded range sleeve to an existing directional signal.

    The range sleeve is already zero outside confirmed ranges.  The helper
    keeps both diagnostics and clips the combined target to the exchange-side
    leverage budget, making an explicit allocation split easy to audit.
    """
    if not 0 <= allocation <= 1:
        raise ValueError("allocation must be between zero and one")
    if not trend_signals.index.equals(range_signals.index):
        raise ValueError("trend and range frames must share the same index")
    result = trend_signals.copy()
    trend = result["signal"].fillna(0.0).to_numpy(dtype=float)
    range_signal = range_signals["signal"].fillna(0.0).to_numpy(dtype=float)
    result["signal"] = np.clip(trend + allocation * range_signal, -max_leverage, max_leverage)
    result["leverage"] = result["signal"].abs()
    result["range_overlay_signal"] = range_signal
    return result


__all__ = ["RangeGridParams", "generate_range_grid_signals", "combine_range_overlay"]
