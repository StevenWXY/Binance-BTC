import json
import sys
from pathlib import Path

import pytest

from btc_regime.cli import _load_strategy_params, _parse_args


ROOT = Path(__file__).resolve().parents[1]


def test_default_config_matches_priority_strategy_d():
    default = json.loads((ROOT / "configs/default_params.json").read_text(encoding="utf-8"))
    priority = json.loads(
        (ROOT / "configs/aggressive_adaptive_v3_params.json").read_text(encoding="utf-8")
    )
    assert default == priority
    params = _load_strategy_params()
    assert params.allow_short is False
    assert params.max_leverage == pytest.approx(6.5)
    assert params.target_vol == pytest.approx(1.075)


@pytest.mark.parametrize(
    ("command", "expected_output"),
    [
        ("backtest", "reports/aggressive_adaptive_v3"),
        ("walkforward", "reports/aggressive_adaptive_v3_walkforward.json"),
        ("micro-backtest", "reports/aggressive_adaptive_v3_micro"),
    ],
)
def test_cli_defaults_target_priority_strategy_d(monkeypatch, command, expected_output):
    monkeypatch.setattr(sys, "argv", ["btc-regime", command])
    args = _parse_args()
    assert args.params is None
    assert args.output == expected_output


def test_cli_stress_defaults_and_scenario_choices(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["btc-regime", "stress-test"])
    args = _parse_args()
    assert args.engine == "v6"
    assert args.output == "reports/stress_test"
    assert args.bars == 420
    assert args.repeats == 1
    assert args.minutes_per_bar == 240
    assert args.scenarios is None
