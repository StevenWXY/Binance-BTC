"""Account-level risk governors for live-style strategy execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd


@dataclass
class AccountDrawdownGovernor:
    """Scale new target exposure as live equity drawdown deepens."""

    enabled: bool = False
    level_1: float = 0.08
    scale_1: float = 0.80
    level_2: float = 0.12
    scale_2: float = 0.50
    level_3: float = 0.16
    scale_3: float = 0.00
    reduce_only_level_3: bool = True
    recovery_enabled: bool = False
    recovery_flat_cooldown_minutes: int = 24 * 60
    recovery_max_signal: float = 0.25
    continuation_reentry_enabled: bool = False
    continuation_reentry_recovery_buffer: float = 0.03
    continuation_reentry_scale_1: float = 1.0
    continuation_reentry_scale_2: float = 0.75
    continuation_reentry_scale_3: float = 0.35
    _flat_since: pd.Timestamp | None = field(default=None, init=False, repr=False)
    _episode_worst_drawdown: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        if not 0 <= self.level_1 < self.level_2 < self.level_3 < 1:
            raise ValueError("drawdown levels must be ordered within [0, 1)")
        if not 0 <= self.scale_3 <= self.scale_2 <= self.scale_1 <= 1:
            raise ValueError("drawdown scales must be ordered within [0, 1]")
        if self.recovery_flat_cooldown_minutes < 1:
            raise ValueError("recovery_flat_cooldown_minutes must be positive")
        if not 0 < self.recovery_max_signal <= 1:
            raise ValueError("recovery_max_signal must be in (0, 1]")
        if not 0 <= self.continuation_reentry_recovery_buffer < 1:
            raise ValueError("continuation_reentry_recovery_buffer must be in [0, 1)")
        if not 0 <= self.continuation_reentry_scale_3 <= self.continuation_reentry_scale_2 <= self.continuation_reentry_scale_1 <= 1:
            raise ValueError("continuation reentry scales must be ordered within [0, 1]")

    def to_dict(self) -> dict[str, float | bool]:
        return asdict(self)

    def scale_for_drawdown(self, drawdown: float) -> float:
        if not self.enabled:
            return 1.0
        if drawdown >= self.level_3:
            return self.scale_3
        if drawdown >= self.level_2:
            return self.scale_2
        if drawdown >= self.level_1:
            return self.scale_1
        return 1.0

    def target_scale_for_signal(
        self,
        desired_signal: float,
        current_signal: float,
        drawdown: float,
    ) -> float:
        base_scale = self.scale_for_drawdown(drawdown)
        continuation_scale = self._continuation_scale(
            desired_signal=desired_signal,
            current_signal=current_signal,
            drawdown=drawdown,
        )
        return max(base_scale, continuation_scale)

    def apply_signal(
        self,
        desired_signal: float,
        current_signal: float,
        drawdown: float,
        timestamp: pd.Timestamp | None = None,
    ) -> float:
        """Apply the governor to a leverage-like target signal."""
        current_abs = abs(current_signal)
        self._update_episode_drawdown(drawdown)
        if current_abs < 1e-12:
            if timestamp is not None and self._flat_since is None:
                self._flat_since = timestamp
        else:
            self._flat_since = None

        scale = self.target_scale_for_signal(desired_signal, current_signal, drawdown)
        governed = desired_signal * scale
        if not self.enabled or not self.reduce_only_level_3 or drawdown < self.level_3:
            return governed

        if self._recovery_allowed(timestamp, current_signal):
            if desired_signal == 0:
                return 0.0
            if current_abs > 1e-12 and desired_signal * current_signal < 0:
                return 0.0
            return float(max(-self.recovery_max_signal, min(self.recovery_max_signal, desired_signal)))

        if current_abs < 1e-12:
            return 0.0
        if desired_signal == 0:
            return 0.0
        if desired_signal * current_signal < 0:
            return 0.0
        if self._continuation_scale(desired_signal, current_signal, drawdown) > 0:
            allowed_abs = max(current_abs, min(abs(desired_signal), abs(governed)))
            return float(allowed_abs * (1 if desired_signal > 0 else -1))
        capped_abs = min(abs(desired_signal), current_abs)
        return float(capped_abs * (1 if desired_signal > 0 else -1))

    def _recovery_allowed(
        self,
        timestamp: pd.Timestamp | None,
        current_signal: float,
    ) -> bool:
        if not self.recovery_enabled:
            return False
        current_abs = abs(current_signal)
        if current_abs > 1e-12 and current_abs <= self.recovery_max_signal + 1e-12:
            return True
        if current_abs > 1e-12:
            return False
        if timestamp is None or self._flat_since is None:
            return False
        elapsed_minutes = (timestamp - self._flat_since).total_seconds() / 60.0
        return elapsed_minutes >= self.recovery_flat_cooldown_minutes

    def _update_episode_drawdown(self, drawdown: float) -> None:
        if not self.enabled:
            self._episode_worst_drawdown = 0.0
            return
        if drawdown < self.level_1:
            self._episode_worst_drawdown = 0.0
            return
        self._episode_worst_drawdown = max(self._episode_worst_drawdown, drawdown)

    def _continuation_scale(
        self,
        desired_signal: float,
        current_signal: float,
        drawdown: float,
    ) -> float:
        if not self.enabled or not self.continuation_reentry_enabled:
            return 0.0
        current_abs = abs(current_signal)
        desired_abs = abs(desired_signal)
        if current_abs < 1e-12 or desired_abs <= current_abs + 1e-12:
            return 0.0
        if desired_signal * current_signal <= 0:
            return 0.0
        recovered = self._episode_worst_drawdown - drawdown
        if recovered + 1e-12 < self.continuation_reentry_recovery_buffer:
            return 0.0
        if drawdown >= self.level_3:
            return self.continuation_reentry_scale_3
        if drawdown >= self.level_2:
            return self.continuation_reentry_scale_2
        if drawdown >= self.level_1:
            return self.continuation_reentry_scale_1
        return 0.0


def drawdown_from_equity(current_equity: float, peak_equity: float) -> float:
    if peak_equity <= 0:
        return 0.0
    return max(0.0, 1.0 - current_equity / peak_equity)
