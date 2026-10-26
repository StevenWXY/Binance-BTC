"""V4.5.3: frozen V4.5.2 signal with conservative routine Maker execution.

Signal generation is intentionally identical to V4.5.2. The refinement changes
only execution: new exposure and ordinary rebalances may rest post-only limits;
protective exits remain taker orders. The minute simulator records this policy.
"""
from __future__ import annotations

from .v452 import V452Params as V453Params
from .v452 import generate_v452_signals


def generate_v453_signals(data, params: V453Params = V453Params(), **kwargs):
    """Return exactly the V4.5.2 signal frame used by V4.5.3 execution."""
    return generate_v452_signals(data, params, **kwargs)


__all__ = ["V453Params", "generate_v453_signals"]
