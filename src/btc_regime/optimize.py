"""Small, transparent in-sample grid search for the regime strategy."""

from __future__ import annotations

from dataclasses import replace
from itertools import product

import pandas as pd

from .backtest import BacktestConfig, run_backtest
from .strategy import StrategyParams, generate_signals


def parameter_grid() -> list[StrategyParams]:
    grid: list[StrategyParams] = []
    for fast, slow, enter, bb_std, rsi_entry in product(
        [18, 24, 30], [72, 96, 120], [21.0, 24.0, 27.0], [1.8, 2.0, 2.2], [27.0, 30.0],
    ):
        if fast >= slow:
            continue
        grid.append(StrategyParams(
            ema_fast=fast, ema_slow=slow, adx_enter=enter, adx_exit=max(16.0, enter - 5.0),
            bb_std=bb_std, rsi_entry=rsi_entry,
        ))
    return grid


def search(data: pd.DataFrame, config: BacktestConfig = BacktestConfig(), limit: int | None = None) -> pd.DataFrame:
    rows = []
    candidates = parameter_grid()[:limit] if limit else parameter_grid()
    for params in candidates:
        result = run_backtest(generate_signals(data, params), config)
        rows.append({**params.to_dict(), **result.metrics})
    return pd.DataFrame(rows).sort_values(["sharpe", "cagr"], ascending=False).reset_index(drop=True)


def volatility_risk_grid(base: StrategyParams) -> list[StrategyParams]:
    """Risk-layer candidates; the underlying entry/exit logic stays fixed."""
    grid: list[StrategyParams] = []
    for rv_period, baseline_period, enter, exit_, scale, momentum_period in product(
        [12, 24, 48],
        [90, 180, 360],
        [1.25, 1.5, 1.75],
        [0.9, 1.1],
        [0.0, 0.25, 0.5, 0.75],
        [6, 18, 36],
    ):
        if enter <= exit_:
            continue
        grid.append(replace(
            base,
            vol_risk_enabled=True,
            realized_vol_period=rv_period,
            vol_baseline_period=baseline_period,
            vol_shock_enter=enter,
            vol_shock_exit=exit_,
            vol_shock_scale=scale,
            vol_momentum_period=momentum_period,
        ))
    return grid


def search_volatility_risk(
    data: pd.DataFrame,
    base: StrategyParams,
    config: BacktestConfig = BacktestConfig(),
    limit: int | None = None,
) -> pd.DataFrame:
    """Rank volatility overlays without reading the post-2024 holdout period."""
    train_start = pd.Timestamp("2020-01-01", tz="UTC")
    validation_start = pd.Timestamp("2023-01-01", tz="UTC")
    validation_end = pd.Timestamp("2025-01-01", tz="UTC")
    candidates = [replace(base, vol_risk_enabled=False), *volatility_risk_grid(base)]
    if limit:
        candidates = candidates[:limit]
    rows: list[dict[str, float | int | bool]] = []
    for params in candidates:
        signaled = generate_signals(data, params)
        train = run_backtest(
            signaled.loc[(signaled.index >= train_start) & (signaled.index < validation_start)],
            config,
        ).metrics
        validation = run_backtest(
            signaled.loc[
                (signaled.index >= validation_start) & (signaled.index < validation_end)
            ],
            config,
        ).metrics
        pre_holdout = run_backtest(
            signaled.loc[(signaled.index >= train_start) & (signaled.index < validation_end)],
            config,
        ).metrics
        train_calmar = train["cagr"] / max(abs(train["max_drawdown"]), 1e-9)
        validation_calmar = validation["cagr"] / max(abs(validation["max_drawdown"]), 1e-9)
        minimum_sharpe = min(train["sharpe"], validation["sharpe"])
        minimum_calmar = min(train_calmar, validation_calmar)
        sharpe_stability = abs(train["sharpe"] - validation["sharpe"])
        robust_score = (
            0.55 * minimum_sharpe
            + 0.15 * (train["sharpe"] + validation["sharpe"]) / 2
            + 0.20 * min(minimum_calmar, 5.0)
            + 0.10 * min((train_calmar + validation_calmar) / 2, 5.0)
            - 0.15 * sharpe_stability
            - 0.0002 * pre_holdout["turnover_multiple"]
        )
        row = params.to_dict()
        row.update({
            "robust_score": robust_score,
            "minimum_sharpe": minimum_sharpe,
            "minimum_calmar": minimum_calmar,
            "sharpe_stability": sharpe_stability,
        })
        for prefix, metrics in (
            ("train", train),
            ("validation", validation),
            ("pre_holdout", pre_holdout),
        ):
            for key, value in metrics.items():
                row[f"{prefix}_{key}"] = value
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["robust_score", "pre_holdout_cagr"], ascending=False
    ).reset_index(drop=True)


def factor_grid(base: StrategyParams) -> list[StrategyParams]:
    """Momentum/carry factor candidates around a frozen volatility configuration."""
    grid: list[StrategyParams] = []
    for momentum_period, momentum_threshold, momentum_scale in product(
        [12, 24, 48], [0.0, -0.01], [0.25, 0.5]
    ):
        grid.append(replace(
            base,
            momentum_factor_enabled=True,
            momentum_factor_period=momentum_period,
            momentum_factor_threshold=momentum_threshold,
            momentum_factor_scale=momentum_scale,
            funding_factor_enabled=False,
        ))
    for funding_lookback, funding_threshold, funding_scale in product(
        [6, 18, 36], [0.00012, 0.0002, 0.0003], [0.5, 0.75]
    ):
        grid.append(replace(
            base,
            momentum_factor_enabled=False,
            funding_factor_enabled=True,
            funding_lookback=funding_lookback,
            funding_high_threshold=funding_threshold,
            funding_factor_scale=funding_scale,
        ))
    for momentum_period, momentum_threshold, momentum_scale, funding_lookback, funding_threshold, funding_scale in product(
        [12, 24, 48], [0.0, -0.01], [0.25, 0.5],
        [6, 18, 36], [0.00012, 0.0002, 0.0003], [0.5, 0.75],
    ):
        grid.append(replace(
            base,
            momentum_factor_enabled=True,
            momentum_factor_period=momentum_period,
            momentum_factor_threshold=momentum_threshold,
            momentum_factor_scale=momentum_scale,
            funding_factor_enabled=True,
            funding_lookback=funding_lookback,
            funding_high_threshold=funding_threshold,
            funding_factor_scale=funding_scale,
        ))
    return grid


def search_factors(
    data: pd.DataFrame,
    base: StrategyParams,
    config: BacktestConfig = BacktestConfig(),
    limit: int | None = None,
) -> pd.DataFrame:
    """Rank momentum/carry overlays without reading the post-2024 holdout."""
    train_start = pd.Timestamp("2020-01-01", tz="UTC")
    validation_start = pd.Timestamp("2023-01-01", tz="UTC")
    validation_end = pd.Timestamp("2025-01-01", tz="UTC")
    candidates = [
        replace(base, momentum_factor_enabled=False, funding_factor_enabled=False),
        *factor_grid(base),
    ]
    if limit:
        candidates = candidates[:limit]
    rows: list[dict[str, float | int | bool]] = []
    for params in candidates:
        signaled = generate_signals(data, params)
        metrics_by_period: dict[str, dict[str, float]] = {}
        for label, start, end in (
            ("train", train_start, validation_start),
            ("validation", validation_start, validation_end),
            ("pre_holdout", train_start, validation_end),
        ):
            window = signaled.loc[(signaled.index >= start) & (signaled.index < end)]
            metrics_by_period[label] = run_backtest(window, config).metrics
        train = metrics_by_period["train"]
        validation = metrics_by_period["validation"]
        pre_holdout = metrics_by_period["pre_holdout"]
        train_calmar = train["cagr"] / max(abs(train["max_drawdown"]), 1e-9)
        validation_calmar = validation["cagr"] / max(abs(validation["max_drawdown"]), 1e-9)
        minimum_sharpe = min(train["sharpe"], validation["sharpe"])
        sharpe_stability = abs(train["sharpe"] - validation["sharpe"])
        robust_score = (
            0.60 * minimum_sharpe
            + 0.20 * (train["sharpe"] + validation["sharpe"]) / 2
            + 0.10 * min(train_calmar, validation_calmar, 5.0)
            + 0.10 * min((train_calmar + validation_calmar) / 2, 5.0)
            - 0.15 * sharpe_stability
            - 0.0002 * pre_holdout["turnover_multiple"]
        )
        row = params.to_dict()
        row.update({"robust_score": robust_score, "minimum_sharpe": minimum_sharpe,
                    "sharpe_stability": sharpe_stability})
        for prefix, metrics in metrics_by_period.items():
            for key, value in metrics.items():
                row[f"{prefix}_{key}"] = value
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["robust_score", "pre_holdout_sharpe"], ascending=False
    ).reset_index(drop=True)


def allocation_grid(base: StrategyParams) -> list[StrategyParams]:
    """Downside-risk allocation candidates around a frozen factor strategy."""
    return [
        replace(
            base,
            downside_allocation_enabled=True,
            downside_vol_period=period,
            downside_calm_threshold=calm_threshold,
            downside_stress_threshold=stress_threshold,
            downside_calm_boost=calm_boost,
            downside_stress_scale=stress_scale,
            drawdown_brake_enabled=False,
        )
        for period, calm_threshold, stress_threshold, calm_boost, stress_scale in product(
            [12, 24, 48], [0.35, 0.4], [0.55, 0.65], [1.1, 1.25, 1.4], [0.4, 0.6, 0.8]
        )
    ]


def search_allocation(
    data: pd.DataFrame,
    base: StrategyParams,
    config: BacktestConfig = BacktestConfig(),
    limit: int | None = None,
) -> pd.DataFrame:
    """Rank downside-risk allocation overlays on the pre-2025 sample."""
    boundaries = {
        "train": (pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp("2023-01-01", tz="UTC")),
        "validation": (pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")),
        "pre_holdout": (pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")),
    }
    candidates = [
        replace(base, downside_allocation_enabled=False, drawdown_brake_enabled=False),
        *allocation_grid(base),
    ]
    if limit:
        candidates = candidates[:limit]
    rows: list[dict[str, float | int | bool]] = []
    for params in candidates:
        signaled = generate_signals(data, params)
        metrics_by_period: dict[str, dict[str, float]] = {}
        for label, (start, end) in boundaries.items():
            window = signaled.loc[(signaled.index >= start) & (signaled.index < end)]
            metrics_by_period[label] = run_backtest(window, config).metrics
        train = metrics_by_period["train"]
        validation = metrics_by_period["validation"]
        pre_holdout = metrics_by_period["pre_holdout"]
        minimum_sharpe = min(train["sharpe"], validation["sharpe"])
        sharpe_stability = abs(train["sharpe"] - validation["sharpe"])
        minimum_calmar = min(
            train["cagr"] / max(abs(train["max_drawdown"]), 1e-9),
            validation["cagr"] / max(abs(validation["max_drawdown"]), 1e-9),
        )
        robust_score = (
            0.55 * minimum_sharpe
            + 0.20 * (train["sharpe"] + validation["sharpe"]) / 2
            + 0.10 * min(minimum_calmar, 5.0)
            + 0.08 * min(pre_holdout["cagr"], 2.0)
            + 0.07 * min(pre_holdout["average_leverage"], 2.0)
            - 0.12 * sharpe_stability
            - 0.0002 * pre_holdout["turnover_multiple"]
        )
        row = params.to_dict()
        row.update({"robust_score": robust_score, "minimum_sharpe": minimum_sharpe,
                    "minimum_calmar": minimum_calmar, "sharpe_stability": sharpe_stability})
        for prefix, metrics in metrics_by_period.items():
            for key, value in metrics.items():
                row[f"{prefix}_{key}"] = value
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["robust_score", "pre_holdout_sharpe"], ascending=False
    ).reset_index(drop=True)
