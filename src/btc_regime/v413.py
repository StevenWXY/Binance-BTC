"""V4.1.3: V4.1.2 directional engine with the enhanced V8 range sleeve.

The two engines do not run as two independent accounts. V4.1.2 has priority;
V8 may open a position only while V4.1.2 is flat. The resulting frame contains
one signed target, one set of protective levels, and one cycle id for the
minute execution simulator.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .v43 import V43Params, generate_v43_signals
from .v8 import V8Params, generate_v8_signals, route_v4_v8_signals


@dataclass(frozen=True)
class V413Params:
    """Fully specified V4.1.3 parameters.

    ``direction`` is the frozen V4.1.2/V4.3 engine. ``range`` is the enhanced
    V8 profile selected in the development search. ``v8_allocation`` is a
    sleeve multiplier applied only while the directional target is zero.
    """

    direction: V43Params = field(default_factory=V43Params)
    range: V8Params = field(default_factory=V8Params)
    v8_allocation: float = 1.0
    max_leverage: float = 6.5

    def __post_init__(self) -> None:
        if not 0.0 <= self.v8_allocation <= 1.0:
            raise ValueError("v8_allocation must be between zero and one")
        if not 0.0 < self.max_leverage <= 10.0:
            raise ValueError("max_leverage must be in (0, 10]")

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "V413Params":
        direction_payload = payload.get("direction_params", payload.get("direction", {}))
        range_payload = payload.get("v8_params", payload.get("range", {}))
        if not isinstance(direction_payload, dict) or not isinstance(range_payload, dict):
            raise ValueError("V4.1.3 config must contain direction_params and v8_params objects")
        return cls(
            direction=V43Params(**direction_payload),
            range=V8Params(**range_payload),
            v8_allocation=float(payload.get("v8_allocation", 1.0)),
            max_leverage=float(payload.get("max_leverage", 6.5)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "version": "V4.1.3",
            "direction_params": self.direction.to_dict(),
            "v8_params": self.range.to_dict(),
            "v8_allocation": self.v8_allocation,
            "max_leverage": self.max_leverage,
        }


def generate_v413_signals(
    data: pd.DataFrame,
    params: V413Params | None = None,
) -> pd.DataFrame:
    """Generate causal V4.1.3 signals and executable protective levels."""

    selected = params or V413Params()
    direction = generate_v43_signals(data, selected.direction)
    range_frame = generate_v8_signals(data, selected.range)
    result = route_v4_v8_signals(
        direction,
        range_frame,
        v8_allocation=selected.v8_allocation,
        max_leverage=selected.max_leverage,
        require_fresh_v8_entry=True,
    )
    result["v413_direction_signal"] = direction["signal"]
    result["v413_v8_signal"] = range_frame["signal"]
    result["v413_v8_active"] = result["strategy_source"].eq("V8")
    result["v413_version"] = "V4.1.3"
    return result


__all__ = ["V413Params", "generate_v413_signals"]
