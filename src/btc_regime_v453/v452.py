"""V4.5.2 short signal combinations and bounded risk-budget refinement.

Longs remain the frozen V4.4.4 module. Candle-open indices execute at +1 hour.
No date-dependent trading rule or future funding observation is used.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from itertools import product

import numpy as np
import pandas as pd

from .v441_r2 import features
from .v444 import V444Params, generate_v444_signals


@dataclass(frozen=True)
class V452Params:
    short_enabled: bool = True
    gate: str = "structural"
    entry: str = "break8"
    confirmation: str = "activity"
    adx_min: float = 32.
    protection: str = "base"
    cooldown_hours: int = 3
    risk: str = "higher"

    def __post_init__(self):
        choices = {"gate": {"structural", "hybrid"},
                   "entry": {"break8", "break12", "break24", "mixed"},
                   "confirmation": {"none", "strength", "activity"},
                   "protection": {"base", "tight", "runner"},
                   "risk": {"base", "elevated", "higher"}}
        for key, valid in choices.items():
            if getattr(self, key) not in valid:
                raise ValueError(f"invalid {key}")
        if self.adx_min not in {24., 28., 32.} or self.cooldown_hours not in {3, 6}:
            raise ValueError("invalid trend or cooldown parameter")

    def to_dict(self):
        return asdict(self)


RISK_PROFILES = {"base": (1.25, .015, .55), "elevated": (1.75, .020, .75), "higher": (2., .025, .90)}
PROTECTIONS = {"base": (1.25, 1.75, 2.5, 24, 1.5),
               "tight": (1., 1.5, 2.5, 18, 1.25),
               "runner": (1.5, 2., 3.5, 36, 1.5)}


def signal_candidates():
    return [V452Params(gate=g, entry=e, confirmation=c, adx_min=a,
                       protection="base", cooldown_hours=6, risk="base")
            for g, e, c, a in product(["structural", "hybrid"],
                                     ["break8", "break12", "break24", "mixed"],
                                     ["none", "strength", "activity"], [24., 28., 32.])]


def refinement_candidates(seeds):
    return [replace(p, protection=protection, risk=risk, cooldown_hours=cool)
            for p in seeds for protection, risk, cool in product(
                ["base", "tight", "runner"], ["base", "elevated", "higher"], [3, 6])]


def v451_control():
    return V452Params(short_enabled=True, gate="structural", entry="break12", confirmation="none",
                       adx_min=28., protection="base", cooldown_hours=6, risk="base")


def generate_v452_signals(data: pd.DataFrame, p: V452Params = V452Params(), *,
                         prepared=None, long_signals=None):
    f = features(data) if prepared is None else prepared.copy()
    core = generate_v444_signals(data, V444Params(), prepared=f) if long_signals is None else long_signals
    if not f.index.equals(core.index):
        raise ValueError("features and long signals must share the hourly index")
    if not p.short_enabled:
        return core.copy()
    structural = (f.daily_close < f.daily_slow) & (f.daily_slope < 0)
    allowed = (f.fast < f.slow) & (f.slope < 0) & (f.minus > f.plus) & (f.adx4 >= p.adx_min)
    if p.gate == "hybrid":
        shock = (f.daily_close < f.daily_fast) & (f.momentum < -.025) & (f.adx4 >= 32.)
        allowed &= structural | shock
    else:
        allowed &= structural
    allowed &= ((f.rsi > 25) & (f.fast - f.close < 2.5 * f.atr4) &
                (f.known_funding > -.0002) & (f.vol_ratio < 2.))
    if p.confirmation == "strength":
        allowed &= (f.minus - f.plus >= 8) & (f.adx4 >= f.adx4.shift(4)) & (f.momentum < 0)
    elif p.confirmation == "activity":
        # Compare completed current-hour turnover to prior hours, excluding itself.
        turnover = f.quote_volume / f.quote_volume.shift().rolling(24, min_periods=24).median()
        allowed &= (turnover >= 1.1) & (f.known_funding > -.0001)
    length = 12 if p.entry == "mixed" else int(p.entry.removeprefix("break"))
    event = f.close < f.low.shift().rolling(length).min()
    if p.entry == "mixed":
        cross = (f.close < f.entry_ema) & (f.close.shift() >= f.entry_ema.shift())
        rejection = ((f.high >= f.entry_ema.shift()) & (f.close < f.entry_ema) &
                     (f.close < f.open) & (f.close < f.close.shift()))
        event |= (cross | rejection) & (f.close < f.fast)
    enter = (allowed & event).fillna(False).to_numpy()
    stop_atr, trail_atr, take_atr, hold, protect_profit = PROTECTIONS[p.protection]
    cap, risk_budget, target_vol = RISK_PROFILES[p.risk]
    target = core.signal.to_numpy(copy=True)
    stops = core.stop_price.to_numpy(copy=True)
    takes = core.take_profit_price.to_numpy(copy=True)
    ids = core.cycle_id.astype(str).to_numpy(copy=True)
    sources = np.where(target > 0, "v444_long", "flat").astype(object)
    active = False
    stop = take = trough = size = entry_price = entry_atr = 0.
    entered = cooldown = cycle = 0
    for i, row in enumerate(f.itertuples()):
        exited = False
        if active:
            stopped = getattr(row, "mark_high", row.high) >= stop
            taken = getattr(row, "mark_low", row.low) <= take
            lost_trend = row.fast >= row.slow or row.close > row.slow
            if (target[i] > 0 or stopped or taken or lost_trend or i - entered >= hold
                    or row.known_funding <= -.0004):
                active = False
                cooldown = i + p.cooldown_hours
                exited = True
        if target[i] > 0:
            continue
        if (not active and not exited and i >= cooldown and enter[i] and
                np.isfinite(row.atr4) and row.atr4 > 0 and np.isfinite(row.vol)):
            entry_price = trough = row.close
            entry_atr = row.atr4
            stop = entry_price + stop_atr * entry_atr
            take = entry_price - take_atr * entry_atr
            size = min(cap, risk_budget / (stop_atr * entry_atr / entry_price),
                       target_vol / max(row.vol, .20))
            active = True
            entered = i
            cycle += 1
        if active:
            trough = min(trough, row.close)
            stop = min(stop, trough + trail_atr * row.atr4)
            if entry_price - trough >= protect_profit * entry_atr:
                stop = min(stop, entry_price - .1 * entry_atr)
            target[i], stops[i], takes[i] = -size, stop, take
            ids[i] = f"v452_short_{cycle}"
            sources[i] = "v452_short"
    out = core.copy()
    out["signal"], out["stop_price"], out["take_profit_price"] = target, stops, takes
    out["cycle_id"], out["source"] = ids, sources
    return out


__all__ = ["V452Params", "RISK_PROFILES", "PROTECTIONS", "signal_candidates", "refinement_candidates",
           "v451_control", "generate_v452_signals"]
