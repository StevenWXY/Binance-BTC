"""V4.4.1: hourly entries with completed 4h regimes and asymmetric shorts.

Indices are candle OPEN times. Every output is available only at index + 1h.
Resampled features are joined by their completion time, never their open time.
No calendar/ETF date is used as a trading signal; dates only affect research.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .indicators import adx, atr, rsi


@dataclass(frozen=True)
class V441Params:
    regime_fast: int = 12
    regime_slow: int = 48
    entry_mode: str = "reclaim"
    long_trailing_atr: float = 3.0
    long_stop_atr: float = 2.5
    long_target_vol: float = 0.90
    long_risk_budget: float = 0.05
    max_leverage: float = 3.0
    long_max_hours: int = 240
    cooldown_hours: int = 6
    rebalance_hours: int = 24
    rebalance_band: float = 0.25
    short_enabled: bool = True
    short_max_leverage: float = 0.60
    short_risk_budget: float = 0.0125
    short_stop_atr: float = 1.8
    short_trailing_atr: float = 2.0
    short_take_atr: float = 4.0
    short_max_hours: int = 48
    funding_crowded: float = 0.0002
    core_scale: float = 0.0
    satellite_scale: float = 1.0

    def __post_init__(self) -> None:
        if not 1 < self.regime_fast < self.regime_slow:
            raise ValueError("regime periods must satisfy 1 < fast < slow")
        if self.entry_mode not in {"trend", "reclaim"}:
            raise ValueError("entry_mode must be trend or reclaim")
        positive = [self.long_trailing_atr, self.long_stop_atr, self.long_target_vol,
                    self.long_risk_budget, self.short_risk_budget, self.short_stop_atr,
                    self.short_trailing_atr, self.short_take_atr, self.funding_crowded]
        if any(not np.isfinite(v) or v <= 0 for v in positive):
            raise ValueError("risk and distance parameters must be finite and positive")
        if not 0 < self.max_leverage <= 10 or not 0 < self.short_max_leverage <= self.max_leverage:
            raise ValueError("invalid leverage caps")
        if not 0 < self.long_risk_budget <= .10 or not 0 < self.short_risk_budget <= .05:
            raise ValueError("risk budgets are fractions of equity")
        if min(self.long_max_hours, self.short_max_hours, self.rebalance_hours) < 1 or self.cooldown_hours < 1:
            raise ValueError("holding, rebalance and cooldown hours must be positive")
        if not 0 < self.rebalance_band <= 1:
            raise ValueError("rebalance_band must be in (0,1]")
        if not 0 <= self.core_scale <= 1 or not 0 < self.satellite_scale <= 1:
            raise ValueError("core/satellite scales must be fractions in [0,1]")

    def to_dict(self) -> dict:
        return asdict(self)


def _bars(data: pd.DataFrame, frequency: str, expected: int) -> pd.DataFrame:
    out = data.resample(frequency, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"})
    count = data.close.resample(frequency).count()
    # Incomplete terminal candles are never made available as completed bars.
    return out.loc[count.eq(expected)].copy()


def _available(features: pd.DataFrame, duration: pd.Timedelta, index: pd.DatetimeIndex) -> pd.DataFrame:
    features = features.copy()
    features.index += duration
    joined = features.reindex(index + pd.Timedelta(hours=1), method="ffill")
    joined.index = index
    return joined


def v441_features(data: pd.DataFrame, p: V441Params) -> pd.DataFrame:
    if not isinstance(data.index, pd.DatetimeIndex) or data.index.tz is None:
        raise ValueError("UTC-aware hourly candle opens are required")
    if data.index.has_duplicates or not data.index.is_monotonic_increasing:
        raise ValueError("hourly candles must be sorted and unique")
    if len(data) > 1 and not data.index.to_series().diff().dropna().eq(pd.Timedelta(hours=1)).all():
        raise ValueError("hourly candles must be continuous; do not forward fill missing prices")
    f = data.copy()
    four = _bars(data, "4h", 4)
    four["fast"] = four.close.ewm(span=p.regime_fast, adjust=False, min_periods=p.regime_fast).mean()
    four["slow"] = four.close.ewm(span=p.regime_slow, adjust=False, min_periods=p.regime_slow).mean()
    four["atr4"] = atr(four, 20)
    four["adx4"], four["plus"], four["minus"] = adx(four, 14)
    four["slope"] = four.slow.pct_change(3)
    four["momentum"] = four.close.pct_change(6)
    cols = ["fast", "slow", "atr4", "adx4", "plus", "minus", "slope", "momentum"]
    f = f.join(_available(four[cols], pd.Timedelta(hours=4), f.index))
    daily = _bars(data, "1D", 24)
    daily["daily_fast"] = daily.close.ewm(span=20, adjust=False, min_periods=20).mean()
    daily["daily_slow"] = daily.close.ewm(span=90, adjust=False, min_periods=90).mean()
    daily["daily_slope"] = daily.daily_slow.pct_change(5, fill_method=None)
    daily["daily_close"] = daily.close
    f = f.join(_available(daily[["daily_fast", "daily_slow", "daily_slope", "daily_close"]],
                          pd.Timedelta(days=1), f.index))
    f["entry_ema"] = f.close.ewm(span=20, adjust=False, min_periods=20).mean()
    f["rsi"] = rsi(f.close)
    f["breakout_high"] = f.high.shift().rolling(24).max()
    f["breakout_low"] = f.low.shift().rolling(24).min()
    logret = np.log(f.close / f.close.shift())
    f["vol"] = logret.ewm(span=168, adjust=False, min_periods=168).std() * np.sqrt(8760)
    f["vol_ratio"] = logret.ewm(span=24, adjust=False, min_periods=24).std() / logret.ewm(span=720, adjust=False, min_periods=168).std()
    # Only actual settled funding events inform crowding, not an announced/future rate.
    rates = f.get("funding_rate", pd.Series(0.0, index=f.index))
    events = f.get("funding_event", rates.ne(0))
    f["known_funding"] = rates.where(events).ffill().fillna(0)
    f["bull"] = (f.fast > f.slow) & (f.slope > 0) & (f.plus >= f.minus) & (f.adx4 >= 18)
    f["bear"] = ((f.fast < f.slow) & (f.slope < 0) & (f.minus > f.plus) & (f.adx4 >= 24)
                 & (f.daily_close < f.daily_slow) & (f.daily_fast < f.daily_slow) & (f.daily_slope < 0))
    reclaim = (f.close > f.entry_ema) & (f.close.shift() <= f.entry_ema.shift())
    reject = (f.close < f.entry_ema) & (f.close.shift() >= f.entry_ema.shift())
    f["long_entry"] = f.bull & ((f.close > f.breakout_high) | reclaim | (~f.bull.shift(fill_value=False)))
    if p.entry_mode == "trend":
        f["long_entry"] = f.bull & (f.close > f.entry_ema)
    # No chasing an exhausted leg; a fresh event will be required after a cooldown.
    f["long_entry"] &= (f.close - f.fast < 3 * f.atr4) & (f.rsi < 78)
    f["short_entry"] = (f.bear & ((f.close < f.breakout_low) | reject) & (f.rsi > 22)
                        & (f.fast - f.close < 2.5 * f.atr4)
                        & (f.known_funding > -p.funding_crowded) & (f.vol_ratio < 2))
    return f


def generate_v441_signals(
    data: pd.DataFrame, params: V441Params = V441Params(), *, trade_start: str | None = None,
) -> pd.DataFrame:
    f = v441_features(data, params)
    n = len(f)
    signal = np.zeros(n)
    stops = np.full(n, np.nan)
    takes = np.full(n, np.nan)
    cycles = np.zeros(n, dtype=int)
    reasons = np.full(n, "", dtype=object)
    side = 0
    size = 0.0
    entry = stop = take = extreme = 0.0
    entered = last_rebalance = cooldown_until = cycle = 0
    p = params
    start = pd.Timestamp(trade_start, tz="UTC") if trade_start else None
    for i, row in enumerate(f.itertuples()):
        if start is not None and row.Index + pd.Timedelta(hours=1) < start:
            continue
        if not np.isfinite(row.atr4) or not np.isfinite(row.vol):
            continue
        exited = False
        if side:
            # These are the PREVIOUS completed candle's executable protection levels.
            stopped = row.low <= stop if side > 0 else row.high >= stop
            taken = np.isfinite(take) and (row.high >= take if side > 0 else row.low <= take)
            stale = i - entered >= (p.long_max_hours if side > 0 else p.short_max_hours)
            lost_trend = (row.fast < row.slow and row.close < row.entry_ema) if side > 0 else (not row.bear or row.close > row.fast)
            shock = row.vol_ratio >= 2 and ((row.close < row.entry_ema) if side > 0 else row.close > row.entry_ema)
            if stopped or taken or stale or lost_trend or shock:
                reasons[i] = "stop" if stopped else "take" if taken else "timeout" if stale else "regime_exit"
                side = 0
                size = 0
                cooldown_until = i + p.cooldown_hours
                exited = True
        if not side and not exited and i >= cooldown_until:
            direction = 1 if row.long_entry else -1 if p.short_enabled and row.short_entry else 0
            if direction:
                side = direction
                entry = extreme = row.close
                distance = (p.long_stop_atr if side > 0 else p.short_stop_atr) * row.atr4
                stop = entry - side * distance
                take = np.nan if side > 0 else entry - p.short_take_atr * row.atr4
                risk = p.long_risk_budget if side > 0 else p.short_risk_budget
                cap = p.max_leverage if side > 0 else p.short_max_leverage
                size = min(cap, risk / (distance / row.close), p.long_target_vol / max(row.vol, .20))
                if side > 0 and row.known_funding > p.funding_crowded:
                    size *= .5
                entered = last_rebalance = i
                cycle += 1
                reasons[i] = "long_entry" if side > 0 else "short_entry"
        if side:
            extreme = max(extreme, row.close) if side > 0 else min(extreme, row.close)
            # Trailing levels move only toward profit, using completed closes.
            new_stop = extreme - side * (p.long_trailing_atr if side > 0 else p.short_trailing_atr) * row.atr4
            stop = max(stop, new_stop) if side > 0 else min(stop, new_stop)
            if side > 0 and i - last_rebalance >= p.rebalance_hours:
                desired = min(p.max_leverage, p.long_target_vol / max(row.vol, .20),
                              p.long_risk_budget / (p.long_stop_atr * row.atr4 / row.close))
                if row.known_funding > p.funding_crowded:
                    desired *= .5
                if abs(desired / max(size, 1e-12) - 1) >= p.rebalance_band:
                    size = desired
                last_rebalance = i
            signal[i] = side * size
            stops[i] = stop
            takes[i] = take
        cycles[i] = cycle
    f["signal"] = signal
    f["leverage"] = np.abs(signal)
    f["stop_price"] = stops
    f["take_profit_price"] = takes
    f["cycle_id"] = "v441_" + pd.Series(cycles, index=f.index).astype(str)
    f["v441_event"] = reasons
    f["regime"] = np.where(signal > 0, "v441_long", np.where(signal < 0, "v441_short", "flat"))
    return _route_core(data, f, p, trade_start) if p.core_scale else f


def core_params():
    """Frozen V4.1.2 signal profile; execution assumptions are set by the caller."""
    from .v43 import V43Params
    return V43Params(
        adx_enter=26., target_vol=1.075, max_leverage=6.5, trend_scale=1.25,
        rebalance_bars=60, vol_risk_enabled=True, realized_vol_period=12,
        vol_baseline_period=90, vol_shock_enter=1.25, vol_shock_exit=1.1,
        vol_shock_scale=.25, vol_momentum_period=36, funding_factor_enabled=True,
        funding_lookback=6, funding_factor_scale=.3, downside_allocation_enabled=True,
        downside_stress_threshold=.625, downside_calm_boost=1.325,
        downside_stress_scale=.3, drawdown_brake_enabled=True, price_drawdown_enter=.15,
        price_drawdown_exit=.075, price_drawdown_scale=.3, stop_atr=2.5,
        take_profit_atr=12., trailing_atr=3., downside_return_threshold=-.06,
        downside_vol_ratio=1.3, exit_cooldown_bars=0, maker_offset_bps=0.)


def core_signals(data: pd.DataFrame) -> pd.DataFrame:
    from .v43 import generate_v43_signals
    four = _bars(data, "4h", 4)
    four["volume"] = data.volume.resample("4h").sum()
    four["quote_volume"] = data.quote_volume.resample("4h").sum()
    four["funding_rate"] = data.funding_rate.resample("4h").sum()
    core = generate_v43_signals(four, core_params())
    side = np.sign(core.signal)
    core["cycle_id"] = "core_" + (side.ne(0) & side.ne(side.shift(fill_value=0))).cumsum().astype(str)
    return core


def _route_core(data: pd.DataFrame, tactical: pd.DataFrame, p: V441Params,
                trade_start: str | None) -> pd.DataFrame:
    core = core_signals(data)
    columns = ["signal", "stop_price", "take_profit_price", "cycle_id"]
    ready = _available(core[columns], pd.Timedelta(hours=4), data.index)
    result = tactical.copy()
    admitted_cycle = None
    first = pd.Timestamp(trade_start, tz="UTC") if trade_start else data.index[0]
    selected = []
    for t, c, h in zip(data.index, ready.itertuples(), tactical.itertuples()):
        if t + pd.Timedelta(hours=1) < first:
            selected.append((0., np.nan, np.nan, "flat", "flat"))
        elif pd.notna(c.signal) and c.signal != 0:
            admitted_cycle = None
            selected.append((np.clip(c.signal * p.core_scale, -p.short_max_leverage, p.max_leverage),
                             c.stop_price, c.take_profit_price, c.cycle_id, "core"))
        else:
            # A fresh hourly entry is required AFTER the core releases the account.
            if h.v441_event in {"long_entry", "short_entry"}:
                admitted_cycle = h.cycle_id
            active = admitted_cycle == h.cycle_id and h.signal != 0
            selected.append((h.signal * p.satellite_scale if active else 0.,
                             h.stop_price if active else np.nan, h.take_profit_price if active else np.nan,
                             h.cycle_id if active else "flat", "satellite" if active else "flat"))
    routed = pd.DataFrame(selected, index=result.index,
                          columns=["signal", "stop_price", "take_profit_price", "cycle_id", "v441_source"])
    for column in routed:
        result[column] = routed[column]
    result["leverage"] = result.signal.abs()
    result["regime"] = result.v441_source
    return result
