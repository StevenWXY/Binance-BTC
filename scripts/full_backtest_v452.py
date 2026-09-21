"""Reproduce the frozen V4.5.2 continuous-account minute backtest."""
from evaluate_v452 import run_case, validate_lock


if __name__ == "__main__":
    profile = validate_lock()["profile"]
    run_case((profile, "base", "2020-01-01", "2026-09-01", "continuous"))
