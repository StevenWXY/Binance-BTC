"""V4.4.1 round 2: bounded core variants and asymmetric tactical families.

All frames use hourly open timestamps; targets become executable one hour later.
No calendar-dependent trading logic. Completed 4h/daily bars are joined by close.
Round-1 modules and parameter locks are deliberately kept reproducible.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from itertools import product

import numpy as np
import pandas as pd

from .indicators import atr, rsi
from .v43 import generate_v43_signals
from .v441 import V441Params, _available, _bars, core_params, v441_features


@dataclass(frozen=True)
class R2Params:
    family: str = "core"
    speed: str = "original"
    risk: str = "original"
    protection: str = "original"
    gate: str = "none"
    entry: float = 15.0
    stop_atr: float = 2.0
    hold_hours: int = 48
    short: bool = False
    target_vol: float = .9  # Tactical families only; core inherits the frozen 1.075 target.
    max_leverage: float = 4.0

    def __post_init__(self):
        choices = {"family": {"core", "pullback", "breakout", "continuation"},
                   "speed": {"original", "medium", "fast"},
                   "risk": {"original", "moderate", "simple"},
                   "protection": {"original", "tight", "swing", "fast"},
                   "gate": {"none", "daily", "slope"}}
        for key, values in choices.items():
            if getattr(self, key) not in values:
                raise ValueError(f"Invalid {key}")
        if not 0 < self.max_leverage <= 6.5 or not 0 < self.target_vol <= 1.5:
            raise ValueError("invalid risk limit")
        if not 0 < self.entry <= 100 or not .5 <= self.stop_atr <= 6 or not 1 <= self.hold_hours <= 240:
            raise ValueError("invalid tactical parameters")

    def to_dict(self):
        return asdict(self)


def candidates():
    result = []
    # 72 coherent core profiles; no free leverage search.
    for speed, risk, protection, gate in product(
        ["original", "medium", "fast"], ["original", "moderate", "simple"],
        ["original", "tight", "swing", "fast"], ["none", "daily"]
    ):
        result.append(R2Params(speed=speed, risk=risk, protection=protection, gate=gate))
    for entry, stop, hold, gate in product([10., 20.], [1.5, 2.5], [24, 48], ["daily", "slope"]):
        result.append(R2Params(family="pullback", entry=entry, stop_atr=stop, hold_hours=hold,
                               gate=gate, max_leverage=1.5, target_vol=.60))
    for speed, stop, short in product(["fast", "medium"], [2., 3.], [False, True]):
        result.append(R2Params(family="breakout", speed=speed, stop_atr=stop, short=short,
                               hold_hours=120, max_leverage=3., target_vol=.75))
    return result


def features(data):
    f = v441_features(data, V441Params())
    f["atr1"] = atr(data, 20)
    f["rsi2"] = rsi(data.close, 2)
    f["long_daily"] = (f.daily_close > f.daily_slow) & (f.daily_slope > 0)
    return f


def generate_r2_signals(data: pd.DataFrame, p: R2Params, *, prepared=None):
    f = features(data) if prepared is None else prepared.copy()
    if p.family == "continuation":
        return _continuation(data, f, p)
    if p.family == "core":
        base = core_params()
        speed = {"original": (30, 120, 26., 18.), "medium": (20, 80, 24., 17.), "fast": (12, 48, 22., 16.)}[p.speed]
        base = replace(base, ema_fast=speed[0], ema_slow=speed[1], adx_enter=speed[2], adx_exit=speed[3],
                       max_leverage=p.max_leverage)
        if p.risk == "moderate":
            base = replace(base, downside_stress_scale=.6, vol_shock_scale=.5, price_drawdown_scale=.6,
                           downside_calm_boost=1., rebalance_bars=12)
        elif p.risk == "simple":
            base = replace(base, downside_allocation_enabled=False, drawdown_brake_enabled=False,
                           vol_shock_scale=.5, rebalance_bars=6, target_vol=.75, trend_scale=1.)
        profiles = {"original": (2.5, 3., 12., 72, 0), "tight": (1.5, 1.5, 4., 36, 3),
                    "swing": (2., 2., 6., 48, 1), "fast": (1.5, 2., 3., 18, 1)}
        stop, trail, take, hold, cool = profiles[p.protection]
        base = replace(base, stop_atr=stop, trailing_atr=trail, take_profit_atr=take,
                       max_hold_bars=hold, exit_cooldown_bars=cool)
        four = _bars(data, "4h", 4)
        for key in ("volume", "quote_volume", "funding_rate"):
            four[key] = data[key].resample("4h").sum()
        s = generate_v43_signals(four, base)
        side = np.sign(s.signal)
        s["cycle_id"] = "core_" + (side.ne(0) & side.ne(side.shift(fill_value=0))).cumsum().astype(str)
        cols = ["signal", "stop_price", "take_profit_price", "cycle_id"]
        ready = _available(s[cols], pd.Timedelta(hours=4), data.index)
        for col in cols:
            f[col] = ready[col]
        f["signal"] = f.signal.fillna(0.)
        if p.gate == "daily":
            f.loc[~f.long_daily, "signal"] = 0.
        f.loc[f.signal.eq(0), ["stop_price", "take_profit_price"]] = np.nan
        f["source"] = "core"
        return f

    close = f.close
    if p.family == "pullback":
        allowed = f.long_daily if p.gate == "daily" else (f.fast > f.slow) & (f.slope > 0)
        long_entry = allowed & (f.rsi2 <= p.entry) & (close < f.entry_ema) & (f.vol_ratio < 2)
        short_entry = pd.Series(False, index=f.index)
    else:
        length = 24 if p.speed == "fast" else 72
        upper = f.high.shift().rolling(length).max()
        lower = f.low.shift().rolling(length).min()
        long_entry = (close > upper) & (f.fast > f.slow) & (f.adx4 > 20)
        short_entry = (close < lower) & f.bear & (f.known_funding > -.0002) & (f.rsi > 20)
    n = len(f)
    signals, stops, takes = np.zeros(n), np.full(n, np.nan), np.full(n, np.nan)
    ids = np.zeros(n, dtype=int)
    direction = 0
    size = stop = take = peak = 0.
    entered = cooldown = cycle = 0
    for i, row in enumerate(f.itertuples()):
        if not np.isfinite(row.atr4) or not np.isfinite(row.vol):
            continue
        exit_now = False
        if direction:
            hit_stop = row.low <= stop if direction > 0 else row.high >= stop
            hit_take = np.isfinite(take) and (row.high >= take if direction > 0 else row.low <= take)
            trend_lost = row.fast < row.slow if direction > 0 else row.fast > row.slow
            if p.family == "pullback":
                trend_lost = row.close >= row.entry_ema or row.rsi2 >= 70
            exit_now = hit_stop or hit_take or trend_lost or i - entered >= p.hold_hours
            if exit_now:
                direction = 0
                cooldown = i + 6
        if not direction and not exit_now and i >= cooldown:
            direction = 1 if long_entry.iloc[i] else -1 if p.short and short_entry.iloc[i] else 0
            if direction:
                distance = p.stop_atr * (row.atr1 if p.family == "pullback" else row.atr4)
                risk = .0125 if p.family == "pullback" or direction < 0 else .04
                cap = .5 if direction < 0 else p.max_leverage
                size = min(cap, risk / (distance / row.close), p.target_vol / max(row.vol, .20))
                stop = row.close - direction * distance
                take = row.entry_ema if p.family == "pullback" else np.nan
                if direction > 0 and row.known_funding > .0002:
                    size *= .5
                peak, entered = row.close, i
                cycle += 1
        if direction:
            if p.family == "breakout":
                peak = max(peak, row.close) if direction > 0 else min(peak, row.close)
                nxt = peak - direction * p.stop_atr * row.atr4
                stop = max(stop, nxt) if direction > 0 else min(stop, nxt)
            signals[i], stops[i], takes[i] = direction * size, stop, take
        ids[i] = cycle
    f["signal"], f["stop_price"], f["take_profit_price"] = signals, stops, takes
    f["cycle_id"] = p.family + "_" + pd.Series(ids, index=f.index).astype(str)
    f["source"] = p.family
    return f


def route_r2(core, satellite, allocation=.5):
    """One net account; accept only a newly started satellite cycle while flat."""
    result = core.copy()
    admitted = None
    previous_cycle = None
    rows = []
    for c, s in zip(core.itertuples(), satellite.itertuples()):
        fresh = s.signal != 0 and s.cycle_id != previous_cycle
        previous_cycle = s.cycle_id
        if c.signal != 0:
            admitted = None
            rows.append((c.signal, c.stop_price, c.take_profit_price, c.cycle_id, "core"))
        else:
            if fresh:
                admitted = s.cycle_id
            active = s.signal != 0 and admitted == s.cycle_id
            rows.append((s.signal * allocation if active else 0., s.stop_price if active else np.nan,
                         s.take_profit_price if active else np.nan, s.cycle_id if active else "flat",
                         "satellite" if active else "flat"))
    for col, values in zip(["signal", "stop_price", "take_profit_price", "cycle_id", "source"], zip(*rows)):
        result[col] = values
    return result


def continuation_candidates():
    return [R2Params(family="continuation", speed=speed, stop_atr=stop,
                     protection=trail, hold_hours=hold)
            for speed, stop, trail, hold in product(
                ["original", "medium", "fast"], [2., 3.], ["tight", "original"], [72, 168])]


def _continuation(data, f, p):
    from .strategy import generate_signals
    speed = {"original": (30, 120, 26., 18.), "medium": (20, 80, 24., 17.),
             "fast": (12, 48, 22., 16.)}[p.speed]
    base = replace(core_params(), ema_fast=speed[0], ema_slow=speed[1], adx_enter=speed[2],
                   adx_exit=speed[3], max_leverage=p.max_leverage)
    four = _bars(data, "4h", 4)
    for col in ("volume", "quote_volume", "funding_rate"):
        four[col] = data[col].resample("4h").sum()
    raw = generate_signals(four, base)
    desired = _available(raw[["signal"]], pd.Timedelta(hours=4), data.index).signal.fillna(0.).to_numpy()
    active = False
    stop = peak = size = 0.
    entered = cooldown = cycle = 0
    trail = 2. if p.protection == "tight" else 3.
    target = np.zeros(len(f))
    stops = np.full(len(f), np.nan)
    ids = np.zeros(len(f), dtype=int)
    # New event after a stop: reclaim hourly EMA or close above prior six-hour high.
    confirm = ((f.close > f.entry_ema) & (f.close.shift() <= f.entry_ema.shift())) | (
        f.close > f.high.shift().rolling(6).max())
    prev_desired = 0.
    for i, row in enumerate(f.itertuples()):
        if not np.isfinite(row.atr4):
            continue
        exited = False
        if active:
            # The live stop is assumed to trigger on mark prices. Use the completed
            # hourly mark low when available to reconcile with the execution model.
            low = getattr(row, "mark_low", row.low)
            if low <= stop or desired[i] <= 0 or i - entered >= p.hold_hours:
                active = False
                cooldown = i + 6
                exited = True
        fresh_regime = desired[i] > 0 and prev_desired <= 0
        if not active and not exited and i >= cooldown and desired[i] > 0 and (fresh_regime or confirm.iloc[i]):
            active = True
            stop = row.close - p.stop_atr * row.atr4
            peak = row.close
            entered = i
            size = desired[i]
            cycle += 1
        if active:
            peak = max(peak, row.close)
            stop = max(stop, peak - trail * row.atr4)
            # Respect the existing risk layer immediately; do not keep stale leverage.
            size = desired[i]
            target[i] = min(size, p.max_leverage)
            stops[i] = stop
        ids[i] = cycle
        prev_desired = desired[i]
    f["signal"], f["stop_price"], f["take_profit_price"] = target, stops, np.nan
    f["cycle_id"] = "continuation_" + pd.Series(ids, index=f.index).astype(str)
    f["source"] = "continuation"
    return f
