"""V4.6.3: a bounded risk-budget refinement of V4.6.1.

The entry and exit family remains the frozen V4.5.3/b022 signal.  V4.6.3
only changes the exposure budget: it keeps the full normal budget, reduces
exposure after a material month-to-date drawdown, and tightens the profit
lock.  All controls use completed hourly bars and are therefore causal.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass

from .v461 import V461Params, generate_v461_signals


@dataclass(frozen=True)
class V463Params(V461Params):
    """Parameters for the V4.6.3 robust risk-budget candidate."""

    exposure_scale: float = 1.00
    monthly_soft_loss: float = -0.10
    monthly_hard_loss: float = -0.15
    monthly_profit_lock: float = 0.06
    soft_loss_scale: float = 0.50
    hard_loss_scale: float = 0.50
    profit_lock_scale: float = 0.35


def generate_v463_signals(
    data: pd.DataFrame,
    params: V463Params = V463Params(),
    **kwargs,
) -> pd.DataFrame:
    """Generate the V4.6.3 signed exposure from completed hourly bars."""

    result = generate_v461_signals(data, params, **kwargs).copy()
    result["v463_source"] = np.where(result["signal"].ne(0), "v463", "flat")
    return result


__all__ = ["V463Params", "generate_v463_signals"]
