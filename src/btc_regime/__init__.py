"""BTCUSDT USD-M perpetual regime-switching research package."""

from .backtest import BacktestConfig, BacktestResult, run_backtest
from .micro_backtest import MicroBacktestConfig, MicroBacktestResult, run_micro_backtest
from .live_execution import ExecutionPlan, LiveExecutionPolicy, MarketSpec, PlannedOrder, plan_target_orders
from .v6 import V6Params, generate_v6_signals
from .strategy import StrategyParams, generate_signals
from .v43 import V43Params, generate_v43_signals
from .range_grid import RangeGridParams, combine_range_overlay, generate_range_grid_signals
from .v8 import V8Params, blend_v4_v8_signals, generate_v8_signals, route_v4_v8_signals
from .v413 import V413Params, generate_v413_signals
from .v453_stable import V453StableParams, generate_v453_stable_signals
from .v461 import V461Params, generate_v461_signals
from .v463 import V463Params, generate_v463_signals
from .v462 import V462Params, generate_v462_signals
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
    "StrategyParams",
    "generate_signals",
    "V43Params",
    "generate_v43_signals",
    "RangeGridParams",
    "generate_range_grid_signals",
    "combine_range_overlay",
    "V8Params",
    "generate_v8_signals",
    "blend_v4_v8_signals",
    "route_v4_v8_signals",
    "V413Params",
    "generate_v413_signals",
    "V453StableParams",
    "generate_v453_stable_signals",
    "V461Params",
    "generate_v461_signals",
    "V463Params",
    "generate_v463_signals",
    "V462Params",
    "generate_v462_signals",
    "run_backtest",
    "run_micro_backtest",
    "ExecutionPlan",
    "LiveExecutionPolicy",
    "MarketSpec",
    "PlannedOrder",
    "plan_target_orders",
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
