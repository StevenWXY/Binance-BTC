"""V4.4.3: higher-frequency continuation entries with explicit causal guards.

The 4h regime remains the risk anchor.  Hourly reclaim/breakout events may
open a new cycle after a protective exit, with a short but explicit cooldown.
All protection levels are based on information available at the hourly close.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product

import numpy as np
import pandas as pd

from .strategy import generate_signals
from .v441_r2 import _available, _bars, core_params, features


@dataclass(frozen=True)
class V443Params:
    speed: str = "medium"
    stop_atr: float = 2.0
    trail_atr: float = 2.0
    hold_hours: int = 48
    cooldown_hours: int = 3
    entry_mode: str = "all"
    breakout_hours: int = 6
    max_leverage: float = 4.0

    def __post_init__(self):
        if self.speed not in {"medium", "fast"}:
            raise ValueError("speed must be medium or fast")
        if self.entry_mode not in {"all", "reclaim", "breakout"}:
            raise ValueError("invalid entry mode")
        if self.stop_atr <= 0 or self.trail_atr <= 0 or self.hold_hours < 6:
            raise ValueError("invalid protection")
        if self.cooldown_hours < 0 or self.breakout_hours < 2:
            raise ValueError("invalid frequency control")
        if not 0 < self.max_leverage <= 4:
            raise ValueError("max leverage must be in (0, 4]")

    def to_dict(self):
        return asdict(self)


def candidates():
    """Registered frequency/protection grid, including the V4.4.2 control."""
    return [V443Params(speed=speed, stop_atr=stop, trail_atr=trail,
                       hold_hours=hold, entry_mode=entry, breakout_hours=6)
            for speed, stop, trail, hold, entry in product(
                ["medium", "fast"], [1.5, 2.0, 3.0], [1.5, 2.5, 3.0],
                [24, 48, 72], ["all", "reclaim", "breakout"])]


def generate_v443_signals(data: pd.DataFrame, p: V443Params = V443Params(), *, prepared=None):
    f = features(data) if prepared is None else prepared.copy()
    speed = {"medium": (20, 80, 24., 17.), "fast": (12, 48, 22., 16.)}[p.speed]
    base = core_params()
    base = base.__class__(**{**base.__dict__, "ema_fast": speed[0], "ema_slow": speed[1],
                             "adx_enter": speed[2], "adx_exit": speed[3],
                             "max_leverage": p.max_leverage})
    four = _bars(data, "4h", 4)
    for col in ("volume", "quote_volume", "funding_rate"):
        four[col] = data[col].resample("4h").sum()
    raw = generate_signals(four, base)
    desired = _available(raw[["signal"]], pd.Timedelta(hours=4), data.index).signal.fillna(0.).to_numpy()
    reclaim = (f.close > f.entry_ema) & (f.close.shift() <= f.entry_ema.shift())
    breakout = f.close > f.high.shift().rolling(p.breakout_hours).max()
    active = False
    stop = peak = size = 0.
    entered = cooldown = cycle = 0
    target = np.zeros(len(f))
    stops = np.full(len(f), np.nan)
    ids = np.zeros(len(f), dtype=int)
    prev_desired = 0.
    for i, row in enumerate(f.itertuples()):
        if not np.isfinite(row.atr4) or not np.isfinite(row.vol):
            continue
        exited = False
        if active:
            low = getattr(row, "mark_low", row.low)
            if low <= stop or desired[i] <= 0 or i - entered >= p.hold_hours:
                active = False
                cooldown = i + p.cooldown_hours
                exited = True
        fresh = desired[i] > 0 and prev_desired <= 0
        event = fresh or (reclaim.iloc[i] if p.entry_mode in {"all", "reclaim"} else False)
        if p.entry_mode in {"all", "breakout"}:
            event = event or breakout.iloc[i]
        if not active and not exited and i >= cooldown and desired[i] > 0 and event:
            active = True
            stop = row.close - p.stop_atr * row.atr4
            peak = row.close
            entered = i
            size = desired[i]
            cycle += 1
        if active:
            peak = max(peak, row.close)
            stop = max(stop, peak - p.trail_atr * row.atr4)
            size = min(desired[i], p.max_leverage)
            target[i], stops[i] = size, stop
        ids[i] = cycle
        prev_desired = desired[i]
    f["signal"], f["stop_price"], f["take_profit_price"] = target, stops, np.nan
    f["cycle_id"] = "v443_" + pd.Series(ids, index=f.index).astype(str)
    f["source"] = "v443_high_frequency"
    return f


__all__ = ["V443Params", "candidates", "generate_v443_signals"]
