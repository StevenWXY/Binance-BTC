"""V7.3 higher-turnover intraday strategy.

This module adapts the idea of short-horizon, high-turnover trading into the
existing 4h research framework.  It does not attempt to replicate external
binary-market execution; instead it expresses the same spirit through:

* faster trend-following entries after short-horizon momentum bursts,
* short-lived mean-reversion fades in compressed/range conditions, and
* explicit stop, take-profit and holding-time controls so the micro engine can
  evaluate the strategy causally.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .indicators import add_indicators, realized_volatility


@dataclass(frozen=True)
class V73HFParams:
    """Parameters for the higher-turnover V7.3 strategy."""

    ema_fast: int = 8
    ema_slow: int = 21
    atr_period: int = 10
    adx_period: int = 10
    rsi_period: int = 7
    bb_period: int = 20
    bb_std: float = 2.0
    target_vol: float = 0.55
    max_leverage: float = 2.75
    allow_short: bool = True
    short_scale: float = 0.9

    realized_vol_period: int = 12
    vol_baseline_period: int = 72
    volatility_cap_ratio: float = 2.4

    trend_adx_enter: float = 18.0
    trend_adx_exit: float = 13.0
    trend_separation_atr: float = 0.05
    breakout_return_period: int = 2
    breakout_return_threshold: float = 0.008
    breakout_volume_period: int = 18
    breakout_volume_threshold: float = 1.2
    trend_scale: float = 1.1
    max_trend_bars: int = 3

    reversion_entry_zscore: float = 1.1
    reversion_exit_zscore: float = 0.25
    reversion_rsi_buffer: float = 8.0
    reversion_scale: float = 0.8
    max_reversion_bars: int = 2

    stop_atr: float = 1.15
    take_profit_atr: float = 1.6
    trailing_atr: float = 0.9
    cooldown_bars: int = 1

    def __post_init__(self) -> None:
        if not 0 < self.max_leverage <= 10:
            raise ValueError("max_leverage must be between 0 and 10")
        if not 0 <= self.short_scale <= 1:
            raise ValueError("short_scale must be between 0 and 1")
        if self.ema_fast < 2 or self.ema_slow <= self.ema_fast:
            raise ValueError("ema periods must be ordered and at least 2")
        if min(self.atr_period, self.adx_period, self.rsi_period, self.bb_period) < 2:
            raise ValueError("indicator periods must be at least 2")
        if min(self.realized_vol_period, self.vol_baseline_period) < 2:
            raise ValueError("volatility periods must be at least 2")
        if self.trend_adx_enter <= self.trend_adx_exit:
            raise ValueError("trend_adx_enter must exceed trend_adx_exit")
        if self.breakout_return_period < 1 or self.breakout_volume_period < 2:
            raise ValueError("breakout lookbacks must be valid")
        if self.breakout_return_threshold <= 0 or self.breakout_volume_threshold <= 0:
            raise ValueError("breakout thresholds must be positive")
        if self.trend_scale <= 0 or self.reversion_scale <= 0:
            raise ValueError("mode scales must be positive")
        if self.reversion_entry_zscore <= self.reversion_exit_zscore:
            raise ValueError("reversion_entry_zscore must exceed reversion_exit_zscore")
        if self.max_trend_bars < 1 or self.max_reversion_bars < 1:
            raise ValueError("maximum holding windows must be positive")
        if min(self.stop_atr, self.take_profit_atr, self.trailing_atr) <= 0:
            raise ValueError("ATR-based protective distances must be positive")
        if self.cooldown_bars < 0:
            raise ValueError("cooldown_bars must be non-negative")
        if self.volatility_cap_ratio <= 0:
            raise ValueError("volatility_cap_ratio must be positive")

    def to_dict(self) -> dict[str, float | int | bool]:
        return {
            key: getattr(self, key)
            for key in self.__dataclass_fields__  # type: ignore[attr-defined]
        }


def generate_v73_hf_signals(
    data: pd.DataFrame,
    params: V73HFParams = V73HFParams(),
) -> pd.DataFrame:
    """Generate higher-turnover causal signals and explicit protective levels."""

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
    ).copy()

    periods_per_year = 365 * 24 // 4
    frame["v73_realized_vol"] = realized_volatility(
        frame["close"],
        p.realized_vol_period,
        periods_per_year,
    )
    frame["v73_vol_baseline"] = frame["v73_realized_vol"].ewm(
        span=p.vol_baseline_period,
        adjust=False,
        min_periods=p.vol_baseline_period,
    ).mean()
    frame["v73_vol_ratio"] = (
        frame["v73_realized_vol"] / frame["v73_vol_baseline"].replace(0, np.nan)
    )
    frame["v73_breakout_return"] = frame["close"].pct_change(p.breakout_return_period)
    volume_baseline = frame["quote_volume"].ewm(
        span=p.breakout_volume_period,
        adjust=False,
        min_periods=p.breakout_volume_period,
    ).mean()
    frame["v73_volume_impulse"] = frame["quote_volume"] / volume_baseline.replace(0, np.nan)
    rolling_std = frame["close"].rolling(p.bb_period, min_periods=p.bb_period).std(ddof=0)
    frame["v73_price_zscore"] = (frame["close"] - frame["bb_mid"]) / rolling_std.replace(0, np.nan)
    frame["v73_ema_spread_atr"] = (
        (frame["ema_fast"] - frame["ema_slow"]) / frame["atr"].replace(0, np.nan)
    )

    annualized_vol = (frame["atr_pct"] * np.sqrt(periods_per_year)).replace(0, np.nan)
    base_size = (
        p.target_vol / annualized_vol
    ).clip(lower=0.0, upper=p.max_leverage).fillna(0.0)
    vol_cap = (frame["v73_vol_ratio"] <= p.volatility_cap_ratio).fillna(False).to_numpy()

    signal = np.zeros(len(frame), dtype=float)
    stop_price = np.full(len(frame), np.nan)
    take_profit = np.full(len(frame), np.nan)
    entry_price = np.full(len(frame), np.nan)
    regime = np.full(len(frame), "v73_hf_warmup", dtype=object)
    mode = np.full(len(frame), "", dtype=object)

    active_direction = 0.0
    active_entry = np.nan
    active_stop = np.nan
    active_take = np.nan
    active_peak = np.nan
    active_mode = ""
    age = 0
    cooldown = 0
    trend_active = False

    for i, row in enumerate(frame.itertuples()):
        ready = (
            np.isfinite(row.ema_fast)
            and np.isfinite(row.ema_slow)
            and np.isfinite(row.atr)
            and np.isfinite(row.v73_price_zscore)
            and np.isfinite(row.v73_breakout_return)
            and np.isfinite(row.v73_volume_impulse)
        )
        if not ready:
            continue

        if trend_active:
            if row.adx <= p.trend_adx_exit:
                trend_active = False
        elif row.adx >= p.trend_adx_enter:
            trend_active = True

        desired = 0.0
        current_regime = "v73_hf_wait"
        current_mode = ""

        spread_atr = float(row.v73_ema_spread_atr)
        trend_direction = 0.0
        if abs(spread_atr) >= p.trend_separation_atr:
            if row.ema_fast > row.ema_slow and row.plus_di >= row.minus_di:
                trend_direction = 1.0
            elif row.ema_fast < row.ema_slow and row.minus_di >= row.plus_di:
                trend_direction = -1.0

        breakout_ready = (
            trend_active
            and trend_direction != 0
            and vol_cap[i]
            and (
                trend_direction * float(row.v73_breakout_return) >= p.breakout_return_threshold
                or float(row.v73_volume_impulse) >= p.breakout_volume_threshold
            )
        )
        if breakout_ready:
            direction_scale = p.trend_scale * (p.short_scale if trend_direction < 0 else 1.0)
            desired = min(float(base_size.iloc[i]) * direction_scale, p.max_leverage)
            desired *= trend_direction
            current_regime = (
                "v73_hf_breakout_long" if trend_direction > 0 else "v73_hf_breakout_short"
            )
            current_mode = "breakout"
        elif not trend_active and vol_cap[i]:
            long_revert = (
                float(row.v73_price_zscore) <= -p.reversion_entry_zscore
                and float(row.rsi) <= 50.0 - p.reversion_rsi_buffer
            )
            short_revert = (
                p.allow_short
                and float(row.v73_price_zscore) >= p.reversion_entry_zscore
                and float(row.rsi) >= 50.0 + p.reversion_rsi_buffer
            )
            if long_revert or short_revert:
                direction = 1.0 if long_revert else -1.0
                direction_scale = p.reversion_scale * (p.short_scale if direction < 0 else 1.0)
                desired = min(float(base_size.iloc[i]) * direction_scale, p.max_leverage)
                desired *= direction
                current_regime = (
                    "v73_hf_reversion_long" if direction > 0 else "v73_hf_reversion_short"
                )
                current_mode = "reversion"

        if cooldown > 0:
            cooldown -= 1
            desired = 0.0
            current_regime = "v73_hf_cooldown"
            current_mode = ""

        desired_side = float(np.sign(desired))
        if desired_side != 0 and desired_side != active_direction:
            active_direction = desired_side
            active_entry = float(row.close)
            active_peak = active_entry
            active_stop = active_entry - p.stop_atr * float(row.atr) * active_direction
            active_take = active_entry + p.take_profit_atr * float(row.atr) * active_direction
            active_mode = current_mode
            age = 0
        elif desired_side == 0 and active_direction != 0:
            active_direction = 0.0
            active_entry = np.nan
            active_stop = np.nan
            active_take = np.nan
            active_peak = np.nan
            active_mode = ""
            age = 0

        protective_exit = False
        if active_direction != 0 and np.isfinite(active_entry):
            age += 1
            if active_direction > 0:
                active_peak = max(float(active_peak), float(row.close))
                active_stop = max(
                    float(active_stop),
                    float(active_peak) - p.trailing_atr * float(row.atr),
                )
                protective_exit = (
                    float(row.close) <= float(active_stop)
                    or float(row.close) >= float(active_take)
                )
            else:
                active_peak = min(float(active_peak), float(row.close))
                active_stop = min(
                    float(active_stop),
                    float(active_peak) + p.trailing_atr * float(row.atr),
                )
                protective_exit = (
                    float(row.close) >= float(active_stop)
                    or float(row.close) <= float(active_take)
                )

            if active_mode == "breakout" and age >= p.max_trend_bars:
                protective_exit = True
            if active_mode == "reversion":
                if abs(float(row.v73_price_zscore)) <= p.reversion_exit_zscore:
                    protective_exit = True
                if age >= p.max_reversion_bars:
                    protective_exit = True

        if protective_exit:
            desired = 0.0
            current_regime = "v73_hf_protective_exit"
            current_mode = ""
            cooldown = p.cooldown_bars

        signal[i] = desired
        regime[i] = current_regime
        mode[i] = current_mode

        if abs(desired) < 1e-12:
            active_direction = 0.0
            active_entry = np.nan
            active_stop = np.nan
            active_take = np.nan
            active_peak = np.nan
            active_mode = ""
            age = 0

        entry_price[i] = active_entry
        stop_price[i] = active_stop
        take_profit[i] = active_take

    frame["signal"] = signal
    frame["leverage"] = np.abs(signal)
    frame["entry_price"] = entry_price
    frame["stop_price"] = stop_price
    frame["take_profit_price"] = take_profit
    frame["regime"] = regime
    frame["v73_hf_mode"] = mode
    return frame


__all__ = ["V73HFParams", "generate_v73_hf_signals"]
