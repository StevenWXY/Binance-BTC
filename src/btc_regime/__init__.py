"""BTCUSDT USD-M perpetual regime-switching research package."""

from .backtest import BacktestConfig, BacktestResult, run_backtest
from .micro_backtest import MicroBacktestConfig, MicroBacktestResult, run_micro_backtest
from .v6 import V6Params, generate_v6_signals
from .strategy import StrategyParams, generate_signals
from .v7 import V7Params, generate_v7_signals

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "MicroBacktestConfig",
    "MicroBacktestResult",
    "StrategyParams",
    "generate_signals",
    "run_backtest",
    "run_micro_backtest",
    "V6Params",
    "generate_v6_signals",
    "V7Params",
    "generate_v7_signals",
]
