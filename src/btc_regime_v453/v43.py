"""V4.3 execution-aware strategy.

V4.3 keeps the V4.1 regime and sizing rules, then adds two deliberately
separate controls:

* routine exposure changes can be posted as maker-only limits (the minute
  simulator models a fill only after the trade range touches the quote), and
* long risk is cut on a completed 4h downside shock with a tighter, monotonic
  ATR trailing stop.  Stop, take-profit and liquidation exits remain taker
  orders so a fee saving never delays risk reduction.

All levels are calculated from the current completed candle and are consumed by
the following 4h boundary, preserving the causal convention of V4.1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .strategy import StrategyParams, generate_signals


@dataclass(frozen=True)
class V43Params(StrategyParams):
    """V4.3 parameters, including execution assumptions for the micro engine."""

    # Explicit protective levels (ATR units) and a faster downside overlay.
    stop_atr: float = 1.8
    take_profit_atr: float = 3.0
    trailing_atr: float = 1.35
    downside_stop_atr: float = 0.70
    downside_lookback: int = 3
    downside_return_threshold: float = -0.025
    downside_vol_ratio: float = 1.20
    downside_confirmation_bars: int = 2
    exit_cooldown_bars: int = 3
    max_hold_bars: int = 72

    # Post-only signal execution.  Exits are taker by default for latency.
    maker_enabled: bool = True
    maker_fee_bps: float = 0.2
    maker_offset_bps: float = 0.5
    maker_order_timeout_minutes: int = 60
    maker_exit_enabled: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.stop_atr <= 0 or self.take_profit_atr <= 0 or self.trailing_atr <= 0:
            raise ValueError("V4.3 ATR distances must be positive")
        if self.downside_stop_atr <= 0:
            raise ValueError("downside_stop_atr must be positive")
        if self.downside_lookback < 1 or self.downside_confirmation_bars < 1:
            raise ValueError("downside lookbacks must be positive")
        if self.downside_return_threshold >= 0:
            raise ValueError("downside_return_threshold must be negative")
        if self.downside_vol_ratio <= 0:
            raise ValueError("downside_vol_ratio must be positive")
        if self.exit_cooldown_bars < 0 or self.max_hold_bars < 1:
            raise ValueError("exit and hold bar limits must be valid")
        if self.maker_fee_bps < 0 or self.maker_offset_bps < 0:
            raise ValueError("maker fee and quote offset must be non-negative")
        if self.maker_order_timeout_minutes < 1:
            raise ValueError("maker_order_timeout_minutes must be positive")


def _downside_trigger(frame: pd.DataFrame, params: V43Params) -> pd.Series:
    """Return a causal fast-downside trigger for a completed 4h bar."""

    lookback_return = frame["close"].pct_change(params.downside_lookback)
    one_bar_return = frame["close"].pct_change()
    # A multi-bar loss catches a stair-step decline, while a single large bar
    # catches the first leg of a sell-off.  Requiring price below the fast EMA
    # prevents ordinary noisy pullbacks from becoming forced exits.
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
        frame.get("vol_ratio", pd.Series(np.nan, index=frame.index))
        >= params.downside_vol_ratio
    ) & (frame.get("vol_momentum", pd.Series(0.0, index=frame.index)) < 0)
    # Volatility confirmation is only used with a negative return; high vol by
    # itself should not flatten a profitable trend.
    return (return_signal | (vol_signal & (one_bar_return < 0))).fillna(False)


def generate_v43_signals(
    data: pd.DataFrame,
    params: V43Params = V43Params(),
) -> pd.DataFrame:
    """Generate V4.3 exposure, causal stop/take levels and diagnostics."""

    frame = generate_signals(data, params).copy()
    trigger = _downside_trigger(frame, params)
    frame["v43_downside_trigger"] = trigger.astype(bool)
    frame["v43_downside_return"] = frame["close"].pct_change(params.downside_lookback)

    base_signal = frame["signal"].fillna(0.0).to_numpy(dtype=float)
    signal = np.zeros(len(frame), dtype=float)
    stop_price = np.full(len(frame), np.nan)
    take_profit = np.full(len(frame), np.nan)
    entry_price = np.full(len(frame), np.nan)
    stop_reason = np.full(len(frame), "", dtype=object)

    active_direction = 0.0
    active_entry = np.nan
    active_stop = np.nan
    active_take = np.nan
    active_peak = np.nan
    age = 0
    cooldown = 0
    previous_base_side = 0.0

    for i, row in enumerate(frame.itertuples()):
        desired = float(base_signal[i])
        desired_side = float(np.sign(desired))
        if cooldown > 0:
            cooldown -= 1
            # A new base direction is allowed to re-enter after the cooldown;
            # the same stale signal is not.
            if desired_side == previous_base_side:
                desired = 0.0
                desired_side = 0.0

        if desired_side != 0 and desired_side != active_direction:
            active_direction = desired_side
            active_entry = float(row.close)
            active_peak = active_entry
            active_stop = active_entry - params.stop_atr * float(row.atr) * active_direction
            active_take = active_entry + params.take_profit_atr * float(row.atr) * active_direction
            age = 0
            stop_reason[i] = "new_entry"
        elif desired_side == 0 and active_direction != 0:
            # Regime-generated exits reset the protective state immediately.
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
                active_stop = max(
                    float(active_stop),
                    float(active_peak) - params.trailing_atr * float(row.atr),
                )
                fast_trigger = bool(trigger.iloc[i])
                if fast_trigger:
                    # Never widen the stop during a sell-off.
                    active_stop = max(
                        float(active_stop),
                        float(row.close) - params.downside_stop_atr * float(row.atr),
                    )
                    stop_reason[i] = "fast_downside_stop"
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
                    float(active_peak) + params.trailing_atr * float(row.atr),
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
            if not stop_reason[i]:
                stop_reason[i] = "protective_exit"

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
        previous_base_side = float(np.sign(base_signal[i]))

    frame["signal"] = signal
    frame["leverage"] = np.abs(signal)
    frame["entry_price"] = entry_price
    frame["stop_price"] = stop_price
    frame["take_profit_price"] = take_profit
    frame["v43_stop_reason"] = stop_reason
    frame["v43_stop_distance_atr"] = (
        (frame["close"] - frame["stop_price"]).abs() / frame["atr"].replace(0, np.nan)
    )
    frame["regime"] = np.where(
        frame["v43_stop_reason"].eq("fast_downside_stop"),
        "v43_fast_downside_exit",
        frame["regime"],
    )
    return frame


__all__ = ["V43Params", "generate_v43_signals"]
