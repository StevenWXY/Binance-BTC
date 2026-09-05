"""V7.1.2: V7.1 with causal protection and execution-aware costs.

The market-state and sizing logic remain V7.1.  This module adds the execution
and risk layer used by the main branch's V4.1.2 iteration: causal ATR
stop/take-profit/trailing levels, a fast downside exit, and parameters for
post-only maker execution with fee rebates.  Protective exits are consumed by
the minute simulator as taker orders for latency.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .v7 import V7Params, generate_v7_signals


@dataclass(frozen=True)
class V712Params(V7Params):
    """V7.1 parameters plus V7.1.2 protection and execution assumptions."""

    stop_atr: float = 2.5
    take_profit_atr: float = 12.0
    trailing_atr: float = 3.0
    downside_stop_atr: float = 0.7
    downside_lookback: int = 3
    downside_return_threshold: float = -0.06
    downside_vol_ratio: float = 1.3
    downside_confirmation_bars: int = 2
    max_hold_bars: int = 72
    maker_enabled: bool = True
    maker_fee_bps: float = 0.2
    maker_offset_bps: float = 0.0
    maker_order_timeout_minutes: int = 60
    maker_exit_enabled: bool = False
    fee_rebate_rate: float = 0.30

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.stop_atr <= 0 or self.take_profit_atr <= 0 or self.trailing_atr <= 0:
            raise ValueError("ATR protection distances must be positive")
        if self.downside_stop_atr <= 0 or self.downside_lookback < 1:
            raise ValueError("downside stop and lookback must be positive")
        if self.downside_return_threshold >= 0:
            raise ValueError("downside_return_threshold must be negative")
        if self.downside_vol_ratio <= 0 or self.downside_confirmation_bars < 1:
            raise ValueError("downside confirmation parameters must be positive")
        if self.max_hold_bars < 1:
            raise ValueError("max_hold_bars must be positive")
        if self.maker_fee_bps < 0 or self.maker_offset_bps < 0:
            raise ValueError("maker fee and offset must be non-negative")
        if self.maker_order_timeout_minutes < 1:
            raise ValueError("maker_order_timeout_minutes must be positive")
        if not 0 <= self.fee_rebate_rate < 1:
            raise ValueError("fee_rebate_rate must be in [0, 1)")


def _base_params(params: V712Params) -> V7Params:
    names = set(V7Params.__dataclass_fields__)
    return V7Params(**{name: value for name, value in params.to_dict().items() if name in names})


def _downside_trigger(frame: pd.DataFrame, params: V712Params) -> pd.Series:
    lookback_return = frame["close"].pct_change(params.downside_lookback)
    one_bar_return = frame["close"].pct_change()
    negative_confirmation = (
        (one_bar_return < 0)
        .rolling(params.downside_confirmation_bars, min_periods=params.downside_confirmation_bars)
        .sum()
        >= params.downside_confirmation_bars
    )
    price_confirmation = frame["close"] < frame["ema_fast"]
    return_signal = (
        (lookback_return <= params.downside_return_threshold)
        | (one_bar_return <= params.downside_return_threshold / 2)
    ) & (price_confirmation | negative_confirmation)
    vol_signal = (
        frame.get("v7_vol_ratio", pd.Series(np.nan, index=frame.index)) >= params.downside_vol_ratio
    ) & (frame.get("v7_vol_momentum", pd.Series(0.0, index=frame.index)) < 0)
    return (return_signal | (vol_signal & (one_bar_return < 0))).fillna(False)


def generate_v712_signals(
    data: pd.DataFrame,
    params: V712Params = V712Params(),
) -> pd.DataFrame:
    """Generate V7.1.2 target exposure and causal protective price levels."""

    frame = generate_v7_signals(data, _base_params(params)).copy()
    trigger = _downside_trigger(frame, params)
    base_signal = frame["signal"].fillna(0.0).to_numpy(dtype=float)

    signal = np.zeros(len(frame), dtype=float)
    stop_price = np.full(len(frame), np.nan)
    take_profit_price = np.full(len(frame), np.nan)
    entry_price = np.full(len(frame), np.nan)
    stop_reason = np.full(len(frame), "", dtype=object)
    active_direction = 0.0
    active_entry = np.nan
    active_stop = np.nan
    active_take = np.nan
    active_extreme = np.nan
    age = 0

    for i, row in enumerate(frame.itertuples()):
        desired = float(base_signal[i])
        desired_side = float(np.sign(desired))

        if desired_side != 0 and desired_side != active_direction:
            active_direction = desired_side
            active_entry = float(row.close)
            active_extreme = active_entry
            active_stop = active_entry - params.stop_atr * float(row.atr) * active_direction
            active_take = active_entry + params.take_profit_atr * float(row.atr) * active_direction
            age = 0
            stop_reason[i] = "new_entry"
        elif desired_side == 0:
            active_direction = 0.0
            active_entry = np.nan
            active_stop = np.nan
            active_take = np.nan
            active_extreme = np.nan
            age = 0

        protective_exit = False
        if active_direction != 0 and np.isfinite(active_entry) and np.isfinite(row.atr):
            age += 1
            if active_direction > 0:
                active_extreme = max(float(active_extreme), float(row.close))
                active_stop = max(float(active_stop), float(active_extreme) - params.trailing_atr * float(row.atr))
                fast_trigger = bool(trigger.iloc[i])
                if fast_trigger:
                    active_stop = max(float(active_stop), float(row.close) - params.downside_stop_atr * float(row.atr))
                protective_exit = (
                    float(row.close) <= float(active_stop)
                    or float(row.close) >= float(active_take)
                    or age >= params.max_hold_bars
                    or fast_trigger
                )
            else:
                active_extreme = min(float(active_extreme), float(row.close))
                active_stop = min(float(active_stop), float(active_extreme) + params.trailing_atr * float(row.atr))
                protective_exit = (
                    float(row.close) >= float(active_stop)
                    or float(row.close) <= float(active_take)
                    or age >= params.max_hold_bars
                )

        if protective_exit:
            desired = 0.0
            desired_side = 0.0
            if not stop_reason[i]:
                stop_reason[i] = "fast_downside_stop" if bool(trigger.iloc[i]) else "protective_exit"
            active_direction = 0.0
            active_entry = np.nan
            active_stop = np.nan
            active_take = np.nan
            active_extreme = np.nan
            age = 0

        signal[i] = desired
        if abs(desired) > 1e-12:
            entry_price[i] = active_entry
            stop_price[i] = active_stop
            take_profit_price[i] = active_take

    frame["signal"] = signal
    frame["leverage"] = np.abs(signal)
    frame["entry_price"] = entry_price
    frame["stop_price"] = stop_price
    frame["take_profit_price"] = take_profit_price
    frame["v712_downside_trigger"] = trigger.astype(bool)
    frame["v712_stop_reason"] = stop_reason
    frame["v712_stop_distance_atr"] = (
        (frame["close"] - frame["stop_price"]).abs() / frame["atr"].replace(0, np.nan)
    )
    frame["regime"] = np.where(
        frame["v712_stop_reason"].isin(["fast_downside_stop", "protective_exit"]),
        "v712_protective_exit",
        frame["regime"],
    )
    return frame


__all__ = ["V712Params", "generate_v712_signals"]
