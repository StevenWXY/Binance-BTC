import pytest
import pandas as pd

from btc_regime.live_risk import AccountDrawdownGovernor, drawdown_from_equity


def test_drawdown_governor_scales_are_ordered() -> None:
    governor = AccountDrawdownGovernor(
        enabled=True,
        level_1=0.08,
        scale_1=0.8,
        level_2=0.12,
        scale_2=0.5,
        level_3=0.16,
        scale_3=0.0,
    )
    assert governor.scale_for_drawdown(0.05) == pytest.approx(1.0)
    assert governor.scale_for_drawdown(0.10) == pytest.approx(0.8)
    assert governor.scale_for_drawdown(0.13) == pytest.approx(0.5)
    assert governor.scale_for_drawdown(0.20) == pytest.approx(0.0)


def test_drawdown_governor_reduce_only_blocks_new_risk() -> None:
    governor = AccountDrawdownGovernor(enabled=True, reduce_only_level_3=True)
    assert governor.apply_signal(1.0, 0.0, 0.18) == pytest.approx(0.0)
    assert governor.apply_signal(-1.0, 0.5, 0.18) == pytest.approx(0.0)
    assert governor.apply_signal(1.0, 0.5, 0.18) == pytest.approx(0.5)
    assert governor.apply_signal(0.2, 0.5, 0.18) == pytest.approx(0.2)


def test_drawdown_governor_recovery_probe_unfreezes_after_flat_cooldown() -> None:
    governor = AccountDrawdownGovernor(
        enabled=True,
        reduce_only_level_3=True,
        recovery_enabled=True,
        recovery_flat_cooldown_minutes=60,
        recovery_max_signal=0.25,
    )
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    assert governor.apply_signal(1.0, 0.0, 0.18, timestamp=start) == pytest.approx(0.0)
    assert governor.apply_signal(1.0, 0.0, 0.18, timestamp=start + pd.Timedelta(minutes=30)) == pytest.approx(0.0)
    assert governor.apply_signal(1.0, 0.0, 0.18, timestamp=start + pd.Timedelta(minutes=60)) == pytest.approx(0.25)


def test_drawdown_governor_recovery_probe_stays_same_side_only() -> None:
    governor = AccountDrawdownGovernor(
        enabled=True,
        reduce_only_level_3=True,
        recovery_enabled=True,
        recovery_flat_cooldown_minutes=60,
        recovery_max_signal=0.25,
    )
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    assert governor.apply_signal(1.0, 0.0, 0.18, timestamp=start) == pytest.approx(0.0)
    assert governor.apply_signal(1.0, 0.0, 0.18, timestamp=start + pd.Timedelta(minutes=60)) == pytest.approx(0.25)
    assert governor.apply_signal(1.0, 0.25, 0.18, timestamp=start + pd.Timedelta(minutes=61)) == pytest.approx(0.25)
    assert governor.apply_signal(-1.0, 0.25, 0.18, timestamp=start + pd.Timedelta(minutes=62)) == pytest.approx(0.0)


def test_drawdown_governor_continuation_reentry_allows_same_side_add_after_recovery() -> None:
    governor = AccountDrawdownGovernor(
        enabled=True,
        reduce_only_level_3=True,
        continuation_reentry_enabled=True,
        continuation_reentry_recovery_buffer=0.03,
        continuation_reentry_scale_3=0.35,
    )
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    assert governor.apply_signal(1.0, 0.2, 0.22, timestamp=start) == pytest.approx(0.2)
    assert governor.apply_signal(1.0, 0.2, 0.18, timestamp=start + pd.Timedelta(minutes=1)) == pytest.approx(0.35)


def test_drawdown_governor_continuation_reentry_stays_same_side_only() -> None:
    governor = AccountDrawdownGovernor(
        enabled=True,
        reduce_only_level_3=True,
        continuation_reentry_enabled=True,
        continuation_reentry_recovery_buffer=0.03,
        continuation_reentry_scale_3=0.35,
    )
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    assert governor.apply_signal(1.0, 0.2, 0.22, timestamp=start) == pytest.approx(0.2)
    assert governor.apply_signal(-1.0, 0.2, 0.18, timestamp=start + pd.Timedelta(minutes=1)) == pytest.approx(0.0)


def test_drawdown_from_equity_uses_peak() -> None:
    assert drawdown_from_equity(84.0, 100.0) == pytest.approx(0.16)
