"""V8 complementary range strategy.

V8 is the public name for the bounded range-inventory engine.  The implementation
is kept in :mod:`btc_regime.range_grid` so old research reports remain
reproducible; this module provides the stable V8 API and a capital-weighted
blend helper for V4/V7 direction signals.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass

from .range_grid import RangeGridParams, generate_range_grid_signals


@dataclass(frozen=True)
class V8Params(RangeGridParams):
    """V8 parameters, retaining the bounded range-grid validation rules."""
    fixed_entry_risk: bool = True
    risk_per_cycle: float = 0.0075
    symmetric_vol_shock: bool = True


def generate_v8_signals(
    data: pd.DataFrame,
    params: V8Params = V8Params(),
) -> pd.DataFrame:
    """Generate causal V8 exposure and protective levels."""
    frame = generate_range_grid_signals(data, params)
    frame["cycle_id"] = "v8_" + frame["rg_entry_event"].cumsum().astype(str)
    return frame


def blend_v4_v8_signals(
    direction_signals: pd.DataFrame,
    v8_signals: pd.DataFrame,
    *,
    direction_allocation: float = 0.80,
    v8_allocation: float = 0.20,
    max_leverage: float = 6.5,
) -> pd.DataFrame:
    """Blend direction and V8 sleeves using explicit capital weights.

    Each input signal is a leverage target for a sleeve.  Capital weights are
    applied before clipping the portfolio target, so V8 cannot silently add
    leverage when the direction sleeve is already at its limit.
    """
    if direction_allocation < 0 or v8_allocation < 0:
        raise ValueError("allocations must be non-negative")
    if direction_allocation + v8_allocation > 1 + 1e-12:
        raise ValueError("allocations cannot exceed one")
    if max_leverage <= 0:
        raise ValueError("max_leverage must be positive")
    if not direction_signals.index.equals(v8_signals.index):
        raise ValueError("direction and V8 frames must share the same index")
    result = direction_signals.copy()
    # A weighted sum has no single valid stop/take level; this helper is only
    # for close-to-close research. Use route_v4_v8_signals for minute execution.
    result = result.drop(columns=["entry_price", "stop_price", "take_profit_price"], errors="ignore")
    direction = direction_signals["signal"].fillna(0.0).to_numpy(dtype=float)
    v8 = v8_signals["signal"].fillna(0.0).to_numpy(dtype=float)
    result["signal"] = (direction_allocation * direction + v8_allocation * v8).clip(
        -max_leverage, max_leverage
    )
    result["leverage"] = result["signal"].abs()
    result["v8_signal"] = v8
    result["v8_allocation"] = v8_allocation
    result["direction_allocation"] = direction_allocation
    return result


def route_v4_v8_signals(
    direction_signals: pd.DataFrame,
    v8_signals: pd.DataFrame,
    *,
    v8_allocation: float = 1.0,
    max_leverage: float = 6.5,
    require_fresh_v8_entry: bool = False,
) -> pd.DataFrame:
    """Give V4/V7 priority and let V8 use idle exposure, on one net account.

    Transfer the selected strategy's protective prices along with its target.
    No simultaneous opposing sleeves or reuse of another strategy's stops.
    The allocation scales V8's target only; V4/V7 keeps its existing sizing.
    """
    if not np.isfinite(v8_allocation) or not 0 <= v8_allocation <= 1:
        raise ValueError("v8_allocation must be between zero and one")
    if not np.isfinite(max_leverage) or not 0 < max_leverage <= 10:
        raise ValueError("max_leverage must be in (0, 10]")
    if not direction_signals.index.equals(v8_signals.index):
        raise ValueError("strategy frames must share the same index")
    result = direction_signals.copy()
    use_direction = direction_signals["signal"].fillna(0).abs() > 1e-12
    v8_target = v8_signals["signal"].fillna(0.0).to_numpy(dtype=float)
    if require_fresh_v8_entry:
        if "rg_entry_event" not in v8_signals:
            raise ValueError("fresh V8 routing requires rg_entry_event")
        blocked = False
        allowed = np.zeros(len(v8_signals), dtype=bool)
        for i, direction_active in enumerate(use_direction.to_numpy()):
            if direction_active:
                blocked = True
            elif bool(v8_signals["rg_entry_event"].iloc[i]):
                blocked = False
            allowed[i] = not blocked
        v8_target = np.where(allowed, v8_target, 0.0)
    result["signal"] = direction_signals["signal"].where(
        use_direction, pd.Series(v8_target, index=result.index) * v8_allocation
    ).fillna(0).clip(-max_leverage, max_leverage)
    result["leverage"] = result["signal"].abs()
    result["strategy_source"] = np.where(use_direction, "direction", "V8")
    side = np.sign(direction_signals["signal"].fillna(0))
    direction_cycles = (use_direction & side.ne(side.shift(1, fill_value=0))).cumsum()
    result["cycle_id"] = ("direction_" + direction_cycles.astype(str)).where(
        use_direction, v8_signals["cycle_id"].where(pd.Series(v8_target != 0, index=result.index))
    )
    result["regime"] = direction_signals["regime"].where(use_direction, v8_signals["regime"])
    for column in ("entry_price", "stop_price", "take_profit_price"):
        result[column] = direction_signals.get(column, pd.Series(np.nan, index=result.index)).where(
            use_direction, v8_signals.get(column, pd.Series(np.nan, index=result.index)).where(
                pd.Series(v8_target != 0, index=result.index)
            )
        ).where(result["signal"].ne(0))
    return result


__all__ = ["V8Params", "generate_v8_signals", "blend_v4_v8_signals", "route_v4_v8_signals"]
