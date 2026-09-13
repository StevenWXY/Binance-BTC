from __future__ import annotations

from decimal import Decimal
import sys

sys.path.insert(0, "deploy")
import demo_runner


def test_floor_step_never_rounds_up() -> None:
    assert demo_runner.floor_step(Decimal("0.0199"), Decimal("0.001")) == Decimal("0.019")


def test_v72_governor_is_not_applied_to_other_strategies() -> None:
    state: dict[str, float] = {}
    assert demo_runner.governor_scale("v43", 80.0, state, demo_runner.SPECS["v43"]) == 1.0


def test_v72_governor_uses_its_own_execution_profile() -> None:
    state: dict[str, float] = {"peak_equity": 100.0}
    assert demo_runner.governor_scale("v72", 88.0, state, demo_runner.SPECS["v72"]) == 0.5
    assert demo_runner.governor_scale("v72", 80.0, state, demo_runner.SPECS["v72"]) == 0.0
