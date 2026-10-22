"""Completion-time accounting for rebate sensitivity reports.

Keeps the archived V4.2 sleeve proxy but books a settlement strictly after
its timestamp, on a sampled equity close. Never moves equity back in time.
This remains a return overlay, not a joint spot/perpetual execution engine.
"""
from __future__ import annotations

import pandas as pd

from .v42 import V42CapitalParams, dynamic_neutral_allocation


def combine_completed_equity(
    equity: pd.Series,
    neutral: pd.DataFrame,
    params: V42CapitalParams,
    available_signal: pd.Series,
) -> pd.DataFrame:
    if not equity.index.is_monotonic_increasing or equity.index.has_duplicates:
        raise ValueError("Equity completion timestamps must be unique and ordered")
    direction_return = equity.pct_change().fillna(0.0)
    events = neutral.loc[neutral.index >= equity.index[0], "neutral_return"]
    positions = equity.index.searchsorted(events.index, side="right")
    valid = positions < len(equity)
    mapped = pd.Series(events.to_numpy()[valid], index=equity.index[positions[valid]])
    booked = (1 + mapped).groupby(level=0).prod().sub(1).reindex(equity.index, fill_value=0.0)
    signal = available_signal.reindex(equity.index, method="ffill").fillna(0.0)
    allocation = dynamic_neutral_allocation(equity, signal, params)
    applied = allocation.neutral_allocation.shift(1).fillna(0.0)
    contribution = applied * booked
    combined_return = direction_return + contribution
    frame = pd.DataFrame({
        "direction_equity": equity,
        "direction_return": direction_return,
        "neutral_sleeve_return": booked,
        "neutral_allocation": applied,
        "neutral_allocation_next": allocation.neutral_allocation,
        "neutral_portfolio_contribution": contribution,
        "neutral_recall_state": allocation.recall_state,
        "estimated_free_margin_next": allocation.estimated_free_margin,
        "combined_return": combined_return,
        "combined_equity": equity.iloc[0] * (1 + combined_return).cumprod(),
    })
    return frame
