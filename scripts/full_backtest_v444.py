"""Reproduce the frozen V4.4.4 continuous-account minute backtest."""
from evaluate_v444 import lock_validate, run_case


def main():
    profile = lock_validate()["profile"]
    run_case((profile, "base", "2020-01-01", "2026-09-01", "continuous"))


if __name__ == "__main__":
    main()
