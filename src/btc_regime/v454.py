"""V4.5.4: V4.5.3 direction sleeve with a causal V4.2-style overlay.

The directional signal and Maker execution remain V4.5.3.  V4.5.4 reserves
75% of directional risk, 15% for the settled-funding neutral sleeve and 10%
as free margin, matching the structural change introduced by V4.2.2.
"""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

from .v42 import V42CapitalParams, combine_direction_and_neutral, generate_neutral_sleeve
from .v453 import V453Params, generate_v453_signals


V454CapitalParams = V42CapitalParams


def generate_v454_signals(
    data: pd.DataFrame,
    params: V453Params = V453Params(),
    *,
    direction_allocation: float = 0.75,
    **kwargs,
) -> pd.DataFrame:
    """Return the causal V4.5.3 signal scaled to the V4.2 direction sleeve."""
    if not 0 < direction_allocation <= 1:
        raise ValueError("direction_allocation must be in (0, 1]")
    signal = generate_v453_signals(data, params, **kwargs).copy()
    signal["signal"] *= direction_allocation
    return signal


def generate_v454_neutral_sleeve(
    funding: pd.DataFrame | pd.Series,
    params: V454CapitalParams = V454CapitalParams(),
    *,
    rebate_fraction: float = 0.4,
) -> pd.DataFrame:
    """Generate the V4.2 settled-funding sleeve with the requested rebate."""
    if not 0 <= rebate_fraction < 1:
        raise ValueError("rebate_fraction must be in [0, 1)")
    adjusted = replace(
        params,
        spot_fee_bps=params.spot_fee_bps * (1 - rebate_fraction),
        futures_fee_bps=params.futures_fee_bps * (1 - rebate_fraction),
    )
    return generate_neutral_sleeve(funding, adjusted)


def combine_v454_direction_and_neutral(
    direction_equity: pd.Series,
    neutral: pd.DataFrame,
    params: V454CapitalParams = V454CapitalParams(),
    direction_signal: pd.Series | None = None,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Combine direction and neutral returns using prior-boundary allocation."""
    return combine_direction_and_neutral(direction_equity, neutral, params, direction_signal)


__all__ = [
    "V453Params",
    "V454CapitalParams",
    "combine_v454_direction_and_neutral",
    "generate_v454_neutral_sleeve",
    "generate_v454_signals",
]
