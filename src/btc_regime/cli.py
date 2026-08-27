"""Command line entrypoints."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .backtest import BacktestConfig, run_backtest
from .data import (
    download_binance_data,
    download_daily_intrabar_data,
    download_intrabar_data,
    iter_intrabar_months,
    load_funding,
    load_market_data,
)
from .micro_backtest import MicroBacktestConfig, run_micro_backtest, write_micro_report
from .optimize import search, search_allocation, search_factors, search_volatility_risk
from .report import write_report
from .strategy import StrategyParams, generate_signals


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PARAMS_PATH = PROJECT_ROOT / "configs/default_params.json"


def _load_strategy_params(path: str | Path | None = None) -> StrategyParams:
    config_path = Path(path) if path else DEFAULT_PARAMS_PATH
    return StrategyParams(**json.loads(config_path.read_text(encoding="utf-8")))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BTCUSDT USD-M regime-switching backtest")
    sub = parser.add_subparsers(dest="command", required=True)
    download = sub.add_parser("download", help="download official Binance archives")
    download.add_argument("--start", default="2020-01")
    download.add_argument("--end", default="2026-07")
    download.add_argument("--raw-dir", default="data/raw")
    intrabar = sub.add_parser("download-intrabar", help="download 1m contract and mark-price archives")
    intrabar.add_argument("--start", default="2020-01")
    intrabar.add_argument("--end", default="2026-07")
    intrabar.add_argument("--raw-dir", default="data/raw")
    intrabar.add_argument("--workers", type=int, default=8)
    daily_intrabar = sub.add_parser(
        "download-daily-intrabar",
        help="download daily 1m contract and mark-price archives",
    )
    daily_intrabar.add_argument("--start", required=True)
    daily_intrabar.add_argument("--end", required=True)
    daily_intrabar.add_argument("--raw-dir", default="data/raw")
    daily_intrabar.add_argument("--workers", type=int, default=8)
    run = sub.add_parser("backtest", help="run a fixed-parameter backtest")
    run.add_argument("--start", default="2020-01-01")
    run.add_argument("--end", default="2026-08-01")
    run.add_argument("--raw-dir", default="data/raw")
    run.add_argument("--output", default="reports/aggressive_adaptive_v3")
    run.add_argument(
        "--params",
        help="JSON file containing StrategyParams fields; defaults to priority strategy D/V3",
    )
    run.add_argument("--fee-bps", type=float, default=4.0)
    run.add_argument("--slippage-bps", type=float, default=1.0)
    optimize = sub.add_parser("optimize", help="rank a small in-sample parameter grid")
    optimize.add_argument("--start", default="2020-01-01")
    optimize.add_argument("--end", default="2024-01-01")
    optimize.add_argument("--raw-dir", default="data/raw")
    optimize.add_argument("--output", default="reports/grid.csv")
    optimize.add_argument("--fee-bps", type=float, default=4.0)
    optimize.add_argument("--slippage-bps", type=float, default=1.0)
    vol_optimize = sub.add_parser(
        "optimize-vol-risk",
        help="rank volatility risk overlays using only 2020-2024",
    )
    vol_optimize.add_argument("--raw-dir", default="data/raw")
    vol_optimize.add_argument("--output", default="reports/volatility_risk_grid.csv")
    vol_optimize.add_argument("--params", required=True, help="base StrategyParams JSON")
    vol_optimize.add_argument("--fee-bps", type=float, default=4.0)
    vol_optimize.add_argument("--slippage-bps", type=float, default=1.0)
    vol_optimize.add_argument("--limit", type=int)
    factor_optimize = sub.add_parser(
        "optimize-factors",
        help="rank trend momentum and funding-crowding factors using only 2020-2024",
    )
    factor_optimize.add_argument("--raw-dir", default="data/raw")
    factor_optimize.add_argument("--output", default="reports/factor_grid.csv")
    factor_optimize.add_argument("--params", required=True, help="base StrategyParams JSON")
    factor_optimize.add_argument("--fee-bps", type=float, default=4.0)
    factor_optimize.add_argument("--slippage-bps", type=float, default=1.0)
    factor_optimize.add_argument("--limit", type=int)
    allocation_optimize = sub.add_parser(
        "optimize-allocation",
        help="rank downside-risk allocation overlays using only 2020-2024",
    )
    allocation_optimize.add_argument("--raw-dir", default="data/raw")
    allocation_optimize.add_argument("--output", default="reports/allocation_grid.csv")
    allocation_optimize.add_argument("--params", required=True, help="base StrategyParams JSON")
    allocation_optimize.add_argument("--fee-bps", type=float, default=4.0)
    allocation_optimize.add_argument("--slippage-bps", type=float, default=1.0)
    allocation_optimize.add_argument("--limit", type=int)
    walk = sub.add_parser("walkforward", help="write train/validation/holdout metrics")
    walk.add_argument("--raw-dir", default="data/raw")
    walk.add_argument("--output", default="reports/aggressive_adaptive_v3_walkforward.json")
    walk.add_argument(
        "--params",
        help="JSON file containing StrategyParams fields; defaults to priority strategy D/V3",
    )
    walk.add_argument("--fee-bps", type=float, default=4.0)
    walk.add_argument("--slippage-bps", type=float, default=1.0)
    micro = sub.add_parser("micro-backtest", help="run 1m execution and liquidation simulation")
    micro.add_argument("--start", default="2020-01-01")
    micro.add_argument("--end", default="2026-08-01")
    micro.add_argument("--raw-dir", default="data/raw")
    micro.add_argument("--output", default="reports/aggressive_adaptive_v3_micro")
    micro.add_argument(
        "--params",
        help="JSON file containing StrategyParams fields; defaults to priority strategy D/V3",
    )
    micro.add_argument("--fee-bps", type=float, default=4.0)
    micro.add_argument("--slippage-bps", type=float, default=1.0)
    micro.add_argument("--impact-bps", type=float, default=8.0)
    micro.add_argument("--participation", type=float, default=0.02)
    micro.add_argument("--liquidation-fee-bps", type=float, default=50.0)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.command == "download":
        print(json.dumps(download_binance_data(args.start, args.end, raw_dir=args.raw_dir), indent=2))
        return
    if args.command == "download-intrabar":
        print(json.dumps(download_intrabar_data(
            args.start, args.end, raw_dir=args.raw_dir, max_workers=args.workers
        ), indent=2))
        return
    if args.command == "download-daily-intrabar":
        print(json.dumps(download_daily_intrabar_data(
            args.start,
            args.end,
            raw_dir=args.raw_dir,
            max_workers=args.workers,
        ), indent=2))
        return
    if args.command == "micro-backtest":
        params = _load_strategy_params(args.params)
        market = load_market_data(args.raw_dir, start=args.start, end=args.end)
        signaled = generate_signals(market, params)
        funding = load_funding(args.raw_dir, start=args.start, end=args.end)
        micro_config = MicroBacktestConfig(
            taker_fee_bps=args.fee_bps,
            base_slippage_bps=args.slippage_bps,
            impact_bps=args.impact_bps,
            max_minute_participation=args.participation,
            liquidation_fee_bps=args.liquidation_fee_bps,
        )
        result = run_micro_backtest(
            signaled,
            iter_intrabar_months(args.raw_dir, start=args.start, end=args.end),
            funding,
            micro_config,
        )
        write_micro_report(result, params, micro_config, args.output)
        print(json.dumps(result.metrics, indent=2))
        return
    config = BacktestConfig(fee_bps=args.fee_bps, slippage_bps=args.slippage_bps)
    if args.command == "optimize-vol-risk":
        base = _load_strategy_params(args.params)
        # The optimizer deliberately cannot access the 2025+ holdout segment.
        data = load_market_data(args.raw_dir, start="2020-01-01", end="2025-01-01")
        table = search_volatility_risk(data, base, config, args.limit)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(args.output, index=False)
        columns = [
            "robust_score", "realized_vol_period", "vol_baseline_period",
            "vol_shock_enter", "vol_shock_exit", "vol_shock_scale",
            "vol_momentum_period", "train_cagr", "train_sharpe", "train_max_drawdown",
            "validation_cagr", "validation_sharpe", "validation_max_drawdown",
            "pre_holdout_cagr", "pre_holdout_sharpe", "pre_holdout_max_drawdown",
        ]
        print(table.loc[:, columns].head(20).to_string(index=False))
        return
    if args.command == "optimize-factors":
        base = _load_strategy_params(args.params)
        data = load_market_data(args.raw_dir, start="2020-01-01", end="2025-01-01")
        table = search_factors(data, base, config, args.limit)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(args.output, index=False)
        columns = [
            "robust_score", "momentum_factor_enabled", "momentum_factor_period",
            "momentum_factor_threshold", "momentum_factor_scale", "funding_factor_enabled",
            "funding_lookback", "funding_high_threshold", "funding_factor_scale",
            "train_sharpe", "validation_sharpe", "pre_holdout_sharpe",
            "train_cagr", "validation_cagr", "pre_holdout_cagr",
            "train_max_drawdown", "validation_max_drawdown", "pre_holdout_max_drawdown",
        ]
        print(table.loc[:, columns].head(20).to_string(index=False))
        return
    if args.command == "optimize-allocation":
        base = _load_strategy_params(args.params)
        data = load_market_data(args.raw_dir, start="2020-01-01", end="2025-01-01")
        table = search_allocation(data, base, config, args.limit)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(args.output, index=False)
        columns = [
            "robust_score", "downside_vol_period", "downside_calm_threshold",
            "downside_stress_threshold", "downside_calm_boost", "downside_stress_scale",
            "train_sharpe", "validation_sharpe", "pre_holdout_sharpe",
            "train_cagr", "validation_cagr", "pre_holdout_cagr",
            "pre_holdout_max_drawdown", "pre_holdout_average_leverage",
            "pre_holdout_turnover_multiple",
        ]
        print(table.loc[:, columns].head(20).to_string(index=False))
        return
    if args.command == "optimize":
        data = load_market_data(args.raw_dir, start=args.start, end=args.end)
        table = search(data, config)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(args.output, index=False)
        print(table.head(10).to_string(index=False))
        return
    if args.command == "walkforward":
        data = load_market_data(args.raw_dir, start="2020-01-01", end="2026-08-01")
        params = _load_strategy_params(args.params)
        signaled = generate_signals(data, params)
        periods = {
            "train_2020_2022": ("2020-01-01", "2023-01-01"),
            "validation_2023_2024": ("2023-01-01", "2025-01-01"),
            "holdout_2025_2026_07": ("2025-01-01", "2026-08-01"),
            "full_2020_2026_07": ("2020-01-01", "2026-08-01"),
        }
        report = {"strategy": params.to_dict(), "backtest": asdict(config), "periods": {}}
        for label, (start, end) in periods.items():
            # Explicit Timestamp comparisons keep the signal state continuous from the full history.
            window = signaled.loc[
                (signaled.index >= pd.Timestamp(start, tz="UTC"))
                & (signaled.index < pd.Timestamp(end, tz="UTC"))
            ]
            report["periods"][label] = run_backtest(window, config).metrics
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return
    data = load_market_data(args.raw_dir, start=args.start, end=args.end)
    params = _load_strategy_params(args.params)
    result = run_backtest(generate_signals(data, params), config)
    write_report(result, params, args.output, "full")
    print(json.dumps(result.metrics, indent=2))


if __name__ == "__main__":
    main()
