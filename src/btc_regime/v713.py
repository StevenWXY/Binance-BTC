"""V7.1.3: V7.1.2 with the V4.2.1-style 25% leverage budget reduction."""

from __future__ import annotations

from dataclasses import dataclass

from .v712 import V712Params, generate_v712_signals


@dataclass(frozen=True)
class V713Params(V712Params):
    """V7.1.2 with target volatility and leverage cap scaled to 75%."""

    target_vol: float = 0.7275  # 0.97 * 0.75, matching V4.1.1 -> V4.2.1
    max_leverage: float = 4.875  # 6.5 * 0.75


def generate_v713_signals(data, params: V713Params = V713Params()):
    """Generate V7.1.3 signals using the V7.1.2 protection layer."""

    return generate_v712_signals(data, params)


__all__ = ["V713Params", "generate_v713_signals"]
