"""Causal technical indicators used by the strategy."""

from __future__ import annotations

import numpy as np
import pandas as pd


def atr(data: pd.DataFrame, period: int = 20) -> pd.Series:
    prev_close = data["close"].shift(1)
    true_range = pd.concat(
        [data["high"] - data["low"], (data["high"] - prev_close).abs(), (data["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    change = close.diff()
    up = change.clip(lower=0)
    down = -change.clip(upper=0)
    avg_up = up.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_down = down.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_up / avg_down.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    return result.where(avg_down != 0, 100.0).fillna(50.0)


def adx(data: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    up_move = data["high"].diff()
    down_move = -data["low"].diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    tr = pd.concat(
        [data["high"] - data["low"], (data["high"] - data["close"].shift()).abs(),
         (data["low"] - data["close"].shift()).abs()], axis=1,
    ).max(axis=1)
    atr_value = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_value
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_value
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_value = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return adx_value, plus_di, minus_di


def realized_volatility(
    close: pd.Series,
    period: int,
    periods_per_year: int = 365 * 24 // 4,
) -> pd.Series:
    """Annualized close-to-close volatility using only completed bars."""
    log_return = np.log(close / close.shift(1))
    return log_return.ewm(
        span=period,
        adjust=False,
        min_periods=period,
    ).std(bias=False) * np.sqrt(periods_per_year)


def add_indicators(data: pd.DataFrame, *, ema_fast: int, ema_slow: int, atr_period: int,
                   rsi_period: int, bb_period: int, bb_std: float, adx_period: int) -> pd.DataFrame:
    result = data.copy()
    result["ema_fast"] = result["close"].ewm(span=ema_fast, adjust=False, min_periods=ema_fast).mean()
    result["ema_slow"] = result["close"].ewm(span=ema_slow, adjust=False, min_periods=ema_slow).mean()
    result["atr"] = atr(result, atr_period)
    result["atr_pct"] = result["atr"] / result["close"]
    result["rsi"] = rsi(result["close"], rsi_period)
    result["bb_mid"] = result["close"].rolling(bb_period, min_periods=bb_period).mean()
    std = result["close"].rolling(bb_period, min_periods=bb_period).std(ddof=0)
    result["bb_upper"] = result["bb_mid"] + bb_std * std
    result["bb_lower"] = result["bb_mid"] - bb_std * std
    adx_value, plus_di, minus_di = adx(result, adx_period)
    result["adx"] = adx_value
    result["plus_di"] = plus_di
    result["minus_di"] = minus_di
    return result
