"""V4.5.1: frozen V4.4.4 longs plus event-driven, bounded tactical shorts.

Hourly open timestamps are used. Every target/stop is executable at index + 1h.
Longs have priority; interrupted shorts cannot resume without a fresh entry.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product

import numpy as np
import pandas as pd

from .v441_r2 import features
from .v444 import V444Params, generate_v444_signals


@dataclass(frozen=True)
class V451Params:
    short_enabled: bool = True
    gate: str = "structural"
    entry: str = "break12"
    protection: str = "quick"
    adx_min: float = 28.
    risk: str = "medium"

    def __post_init__(self):
        if self.gate not in {"trend", "tactical", "structural"}:
            raise ValueError("invalid short gate")
        if self.entry not in {"break12", "break24", "reject"}:
            raise ValueError("invalid short entry")
        if self.protection not in {"quick", "swing"}:
            raise ValueError("invalid short protection")
        if self.adx_min not in {20., 24., 28.}:
            raise ValueError("invalid ADX threshold")
        if self.risk not in {"small", "medium"}:
            raise ValueError("invalid short risk")

    def to_dict(self):
        return asdict(self)


def candidates():
    return [V451Params(gate=g, entry=e, protection=p, adx_min=a, risk=r)
            for g, e, p, a, r in product(
                ["trend", "tactical", "structural"], ["break12", "break24", "reject"],
                ["quick", "swing"], [20., 28.], ["small", "medium"])]


def generate_v451_signals(data: pd.DataFrame, p: V451Params = V451Params(), *,
                         prepared=None, long_signals=None):
    f = features(data) if prepared is None else prepared.copy()
    core = generate_v444_signals(data, V444Params(), prepared=f) if long_signals is None else long_signals
    if not f.index.equals(core.index):
        raise ValueError("prepared features and long signals must share the hourly index")
    if not p.short_enabled:
        return core.copy()
    allowed = (f.fast < f.slow) & (f.slope < 0) & (f.minus > f.plus) & (f.adx4 >= p.adx_min)
    if p.gate == "tactical":
        allowed &= f.daily_close < f.daily_fast
    elif p.gate == "structural":
        allowed &= (f.daily_close < f.daily_slow) & (f.daily_slope < 0)
    # Avoid exhausted selloffs and expensive/crowded shorts. Settled funding only.
    allowed &= ((f.rsi > 25) & (f.fast - f.close < 2.5 * f.atr4) &
                (f.known_funding > -.0002) & (f.vol_ratio < 2.0))
    if p.entry.startswith("break"):
        length = int(p.entry.removeprefix("break"))
        event = f.close < f.low.shift().rolling(length).min()
    else:
        cross = (f.close < f.entry_ema) & (f.close.shift() >= f.entry_ema.shift())
        rejection = ((f.high >= f.entry_ema.shift()) & (f.close < f.entry_ema) &
                     (f.close < f.open) & (f.close < f.close.shift()))
        event = cross | rejection
    enter = (allowed & event).fillna(False).to_numpy()
    stop_atr, trail_atr, take_atr, hold = {
        "quick": (1.25, 1.75, 2.5, 24), "swing": (1.75, 2.5, 4., 48)
    }[p.protection]
    cap, risk_budget, target_vol = {"small": (.75, .01, .40), "medium": (1.25, .015, .55)}[p.risk]
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
                cooldown = i + 6
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
            if entry_price - trough >= 1.5 * entry_atr:
                stop = min(stop, entry_price - .1 * entry_atr)
            target[i], stops[i], takes[i] = -size, stop, take
            ids[i] = f"v451_short_{cycle}"
            sources[i] = "v451_short"
    out = core.copy()
    out["signal"], out["stop_price"], out["take_profit_price"] = target, stops, takes
    out["cycle_id"], out["source"] = ids, sources
    return out


__all__ = ["V451Params", "candidates", "generate_v451_signals"]
