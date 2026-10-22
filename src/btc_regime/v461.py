"""V4.6.1: higher-return monthly-stability sleeve.

V4.6.1 keeps the frozen V4.5.3/b022 signal family and changes only the
exposure budget used by the V4.5.3-stable overlay.  The selection deliberately
does not add a new alpha factor after inspecting the full history: the small
factor variants tested around the frozen signal were less consistent in the
recent diagnostic window.  This version therefore raises the normal exposure
to pursue the requested return target while retaining causal month-to-date
loss and profit-lock controls.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .v453_stable import V453StableParams, generate_v453_stable_signals


@dataclass(frozen=True)
class V461Params(V453StableParams):
    """Parameters for the V4.6.1 higher-return stable sleeve."""

    exposure_scale: float = 0.90
    monthly_soft_loss: float = -0.05
    monthly_hard_loss: float = -0.10
    monthly_profit_lock: float = 0.06
    soft_loss_scale: float = 0.75
    hard_loss_scale: float = 0.50
    profit_lock_scale: float = 0.50


def generate_v461_signals(
    data: pd.DataFrame,
    params: V461Params = V461Params(),
    **kwargs,
) -> pd.DataFrame:
    """Generate the V4.6.1 signed exposure from completed hourly bars."""

    result = generate_v453_stable_signals(data, params, **kwargs).copy()
    result["stable_source"] = np.where(result["signal"].ne(0), "v461", "flat")
    result["v461_source"] = result["stable_source"]
    return result


__all__ = ["V461Params", "generate_v461_signals"]
