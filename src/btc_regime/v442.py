"""V4.4.2 compatibility name for the frozen V4.4.1-R2 strategy."""

from .v441_r2 import (
    R2Params as V442Params,
    candidates,
    continuation_candidates,
    features,
    generate_r2_signals as generate_v442_signals,
    route_r2 as route_v442,
)

__all__ = ["V442Params", "candidates", "continuation_candidates", "features",
           "generate_v442_signals", "route_v442"]
