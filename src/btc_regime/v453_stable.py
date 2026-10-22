"""A lower-risk, month-stability sleeve built from the frozen V4.5.3 signal.

The alpha signal remains V4.5.3/V4.5.2: multi-timeframe trend, breakout and
selective short confirmation.  This module adds a deliberately small risk
overlay.  Exposure is reduced at the start of the strategy and then adjusted
causally from the current calendar month's completed-hour BTC return.  The
overlay is intended to reduce monthly dispersion; it is not an alpha factor.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .v453 import V453Params, generate_v453_signals


@dataclass(frozen=True)
class V453StableParams:
    """Parameters for the lower-risk V4.5.3 factor sleeve."""

    base: V453Params = V453Params()
    exposure_scale: float = 0.25
    monthly_soft_loss: float = -0.05
    monthly_hard_loss: float = -0.10
    monthly_profit_lock: float = 0.06
    soft_loss_scale: float = 0.50
    hard_loss_scale: float = 0.20
    profit_lock_scale: float = 0.25

    def __post_init__(self) -> None:
        if not 0 < self.exposure_scale <= 1:
            raise ValueError("exposure_scale must be in (0, 1]")
        if not self.monthly_hard_loss < self.monthly_soft_loss < 0:
            raise ValueError("monthly loss thresholds must be ordered below zero")
        if self.monthly_profit_lock <= 0:
            raise ValueError("monthly_profit_lock must be positive")
        for name in ("soft_loss_scale", "hard_loss_scale", "profit_lock_scale"):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between zero and one")

    def to_dict(self) -> dict[str, object]:
        return {
            "base": self.base.to_dict(),
            "exposure_scale": self.exposure_scale,
            "monthly_soft_loss": self.monthly_soft_loss,
            "monthly_hard_loss": self.monthly_hard_loss,
            "monthly_profit_lock": self.monthly_profit_lock,
            "soft_loss_scale": self.soft_loss_scale,
            "hard_loss_scale": self.hard_loss_scale,
            "profit_lock_scale": self.profit_lock_scale,
        }


def _month_to_date_return(close: pd.Series) -> pd.Series:
    """Return the current month's price return using completed bars only."""
    if not isinstance(close.index, pd.DatetimeIndex) or close.index.tz is None:
        raise ValueError("close must have a UTC-aware DatetimeIndex")
    month_key = close.index.strftime("%Y-%m")
    first_close = close.groupby(month_key, sort=False).transform("first")
    return close / first_close - 1.0


def generate_v453_stable_signals(
    data: pd.DataFrame,
    params: V453StableParams = V453StableParams(),
    **kwargs,
) -> pd.DataFrame:
    """Generate V4.5.3 signals with a causal monthly risk-budget overlay.

    The current completed hourly bar determines the multiplier applied to the
    target exposure consumed by the next hourly execution boundary.  Stops and
    take-profit levels remain those of the underlying signal and are always
    handled by the execution engine as protective exits.
    """
    base = generate_v453_signals(data, params.base, **kwargs).copy()
    month_return = _month_to_date_return(data["close"].astype(float))
    multiplier = pd.Series(1.0, index=data.index, dtype=float)
    multiplier.loc[month_return <= params.monthly_soft_loss] = params.soft_loss_scale
    multiplier.loc[month_return <= params.monthly_hard_loss] = params.hard_loss_scale
    multiplier.loc[month_return >= params.monthly_profit_lock] = params.profit_lock_scale

    applied = params.exposure_scale * multiplier
    base["signal"] = base["signal"].astype(float) * applied.to_numpy()
    base["leverage"] = base["signal"].abs()
    base["stable_month_to_date_return"] = month_return
    base["stable_risk_multiplier"] = multiplier
    base["stable_exposure_scale"] = applied
    base["stable_source"] = np.where(base["signal"].ne(0), "v453_stable", "flat")
    return base


__all__ = ["V453StableParams", "generate_v453_stable_signals"]
