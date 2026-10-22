"""V4.6.2 research: bounded entry/protection changes to frozen V4.6.1."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

from .v441_r2 import features
from .v444 import V444Params, generate_v444_signals
from .v453 import V453Params
from .v461 import V461Params, generate_v461_signals


@dataclass(frozen=True)
class V462Params:
    # Defaults are the unchanged signal control, not a claimed selected winner.
    risk: V461Params = field(default_factory=V461Params)
    long: V444Params = field(default_factory=V444Params)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "V462Params":
        risk = dict(payload["risk"])
        risk["base"] = V453Params(**risk["base"])
        return cls(risk=V461Params(**risk), long=V444Params(**payload["long"]))


def generate_v462_signals(data: pd.DataFrame, params: V462Params = V462Params(), *, prepared=None):
    f = features(data) if prepared is None else prepared.copy()
    longs = generate_v444_signals(data, params.long, prepared=f)
    out = generate_v461_signals(data, params.risk, prepared=f, long_signals=longs)
    out["v462_source"] = out["source"]
    return out


__all__ = ["V462Params", "generate_v462_signals"]
