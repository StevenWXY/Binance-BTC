"""BTCUSDT USD-M perpetual regime-switching research package."""

from .backtest import BacktestConfig, BacktestResult, run_backtest
from .micro_backtest import MicroBacktestConfig, MicroBacktestResult, run_micro_backtest
from .live_risk import AccountDrawdownGovernor
from .v6 import V6Params, generate_v6_signals
from .strategy import StrategyParams, generate_signals
from .v43 import V43Params, generate_v43_signals
from .v8_hf import V8HFParams, generate_v8_hf_signals
from .v71_live import V71LiveParams, generate_v71_live_signals
from .stress import (
    SCENARIOS,
    StressScenario,
    StressSuiteResult,
    generate_stress_intrabar,
    generate_stress_market,
    list_stress_scenarios,
    run_stress_suite,
    write_stress_report,
)

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "MicroBacktestConfig",
    "MicroBacktestResult",
    "AccountDrawdownGovernor",
    "StrategyParams",
    "generate_signals",
    "V43Params",
    "generate_v43_signals",
    "V8HFParams",
    "generate_v8_hf_signals",
    "V71LiveParams",
    "generate_v71_live_signals",
    "run_backtest",
    "run_micro_backtest",
    "V6Params",
    "generate_v6_signals",
    "SCENARIOS",
    "StressScenario",
    "StressSuiteResult",
    "generate_stress_market",
    "generate_stress_intrabar",
    "list_stress_scenarios",
    "run_stress_suite",
    "write_stress_report",
]
