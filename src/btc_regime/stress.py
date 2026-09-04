"""Deterministic synthetic-market stress testing for BTC strategies.

The stress runner intentionally uses the same strategy and execution engines as
the historical backtests.  Synthetic candles are generated without any future
information, then expanded into one-minute trade/mark paths so liquidation and
protective exits are exercised at the same causal boundaries as live trading.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from .backtest import BacktestConfig, run_backtest
from .micro_backtest import MicroBacktestConfig, run_micro_backtest
from .strategy import StrategyParams, generate_signals
from .v6 import V6Params, generate_v6_signals


@dataclass(frozen=True)
class StressScenario:
    """Description of one reproducible market shock family."""

    name: str
    description: str
    drift: float
    volatility: float
    funding_rate: float = 0.0


SCENARIOS: tuple[StressScenario, ...] = (
    StressScenario(
        "flash_crash",
        "single 35% mark-price crash followed by a rebound",
        0.0004,
        0.012,
    ),
    StressScenario(
        "gap_down", "overnight 28% gap down with continued weakness", -0.001, 0.010
    ),
    StressScenario(
        "gap_up", "overnight 28% gap up followed by a sharp reversal", 0.0005, 0.010
    ),
    StressScenario(
        "volatility_cluster",
        "fat-tailed volatility cluster and alternating jumps",
        0.0,
        0.045,
    ),
    StressScenario(
        "trend_reversal",
        "persistent rally that reverses into a bear trend",
        0.0008,
        0.010,
    ),
    StressScenario(
        "funding_spike",
        "crowded-long funding spike during a sell-off",
        -0.0008,
        0.015,
        0.0025,
    ),
    StressScenario(
        "liquidity_crunch", "thin quote volume and wider intrabar wicks", -0.0003, 0.020
    ),
    StressScenario(
        "stop_take",
        "directional path that deliberately visits stop and take levels",
        0.0007,
        0.008,
    ),
)
SCENARIO_BY_NAME = {scenario.name: scenario for scenario in SCENARIOS}


@dataclass
class StressSuiteResult:
    """Summary and detailed records produced by :func:`run_stress_suite`."""

    summary: pd.DataFrame
    details: dict[str, dict[str, object]]
    metadata: dict[str, object]


def list_stress_scenarios() -> tuple[str, ...]:
    """Return supported scenario names in their stable execution order."""

    return tuple(scenario.name for scenario in SCENARIOS)


def _scenario_returns(name: str, bars: int, rng: np.random.Generator) -> np.ndarray:
    scenario = SCENARIO_BY_NAME[name]
    returns = rng.normal(scenario.drift, scenario.volatility, bars)
    pivot = max(2, int(bars * 0.55))
    if name == "flash_crash":
        returns[pivot] = -0.38
        if pivot + 1 < bars:
            returns[pivot + 1] = -0.10
        returns[pivot + 2 : min(bars, pivot + 12)] = 0.025
    elif name == "gap_down":
        returns[pivot] = -0.30
        returns[pivot + 1 : min(bars, pivot + 16)] -= 0.004
    elif name == "gap_up":
        returns[pivot] = 0.30
        returns[pivot + 1 : min(bars, pivot + 10)] = -0.025
    elif name == "volatility_cluster":
        end = min(bars, pivot + max(12, bars // 6))
        returns[pivot:end] = rng.standard_t(df=3, size=end - pivot) * 0.055
        if pivot + 4 < bars:
            returns[pivot + 4] = -0.22
    elif name == "trend_reversal":
        split = max(2, bars // 2)
        returns[:split] = rng.normal(0.0025, 0.006, split)
        returns[split:] = rng.normal(-0.0035, 0.012, bars - split)
        returns[split] -= 0.16
    elif name == "funding_spike":
        returns[pivot : min(bars, pivot + 12)] -= 0.012
    elif name == "liquidity_crunch":
        end = min(bars, pivot + max(8, bars // 10))
        returns[pivot:end] = rng.normal(-0.006, 0.04, end - pivot)
    elif name == "stop_take":
        # A clean initial rise, then a stop visit, then a take-profit visit.
        returns[:pivot] = rng.normal(0.0022, 0.004, pivot)
        if pivot < bars:
            returns[pivot] = -0.075
        if pivot + 1 < bars:
            returns[pivot + 1 : min(bars, pivot + 8)] = 0.012
        if pivot + 8 < bars:
            returns[pivot + 8] = 0.085
    return returns


def generate_stress_market(
    scenario: str | StressScenario,
    *,
    bars: int = 420,
    seed: int = 7,
    initial_price: float = 100_000.0,
    start: str | pd.Timestamp = "2020-01-01",
) -> pd.DataFrame:
    """Generate deterministic 4-hour OHLCV data for an extreme scenario.

    The returned frame has the same columns as :func:`load_market_data`, plus a
    synthetic funding rate.  Repeating a seed produces byte-for-byte identical
    candles, which makes CI regression tests and incident replay practical.
    """

    if isinstance(scenario, StressScenario):
        name = scenario.name
    else:
        name = str(scenario)
    if name not in SCENARIO_BY_NAME:
        raise ValueError(
            f"unknown stress scenario {name!r}; choose from {list_stress_scenarios()}"
        )
    if bars < 32:
        raise ValueError("bars must be at least 32")
    if initial_price <= 0:
        raise ValueError("initial_price must be positive")
    spec = SCENARIO_BY_NAME[name]
    rng = np.random.default_rng(seed)
    log_returns = _scenario_returns(name, bars, rng)
    close = initial_price * np.exp(np.cumsum(log_returns))
    open_price = np.empty(bars, dtype=float)
    open_price[0] = initial_price
    open_price[1:] = close[:-1]
    pivot = int(bars * 0.55)
    if name in {"gap_down", "gap_up"}:
        jump = -0.28 if name == "gap_down" else 0.28
        open_price[pivot] = close[pivot - 1] * (1.0 + jump)
        close[pivot] = open_price[pivot] * np.exp(
            rng.normal(spec.drift, spec.volatility)
        )
        if pivot + 1 < bars:
            close[pivot + 1 :] = close[pivot] * np.exp(
                np.cumsum(log_returns[pivot + 1 :])
            )
            open_price[pivot + 1 :] = close[pivot:-1]
    wick = np.abs(rng.normal(0.0035, 0.0015, bars)).clip(0.001, 0.025)
    high = np.maximum(open_price, close) * (1.0 + wick)
    low = np.minimum(open_price, close) * (1.0 - wick)
    if name == "flash_crash":
        low[pivot] = min(low[pivot], open_price[pivot] * 0.60)
    elif name == "gap_down":
        low[pivot] = min(low[pivot], open_price[pivot] * 0.68)
    elif name == "gap_up":
        high[pivot] = max(high[pivot], open_price[pivot] * 1.03)
    elif name == "liquidity_crunch":
        low[pivot : min(bars, pivot + 8)] *= 0.94
        high[pivot : min(bars, pivot + 8)] *= 1.04
    volume = np.exp(rng.normal(np.log(8e4), 0.25, bars))
    if name == "liquidity_crunch":
        volume[pivot : min(bars, pivot + 16)] *= 0.01
    quote_volume = volume * ((open_price + close) / 2.0)
    # Binance funding settles every 8h; the synthetic 4h frame therefore emits
    # a rate on alternating bars and zeros on the intervening candles.
    funding_rate = np.zeros(bars, dtype=float)
    if name != "funding_spike":
        funding_rate[::2] = spec.funding_rate
    if name == "funding_spike":
        funding_rate[pivot : min(bars, pivot + 24)] = 0.0
        funding_rate[pivot + (pivot % 2) : min(bars, pivot + 24) : 2] = 0.006
        funding_rate[pivot + 24 :] = 0.0
        funding_rate[pivot + 24 + ((pivot + 24) % 2) :: 2] = 0.001
    index = pd.date_range(start, periods=bars, freq="4h", tz="UTC")
    index.name = "timestamp"
    return pd.DataFrame(
        {
            "open": open_price,
            "high": np.maximum(high, np.maximum(open_price, close)),
            "low": np.minimum(low, np.minimum(open_price, close)),
            "close": close,
            "volume": volume,
            "quote_volume": quote_volume,
            "funding_rate": funding_rate,
        },
        index=index,
    )


def generate_stress_intrabar(
    market: pd.DataFrame,
    scenario: str | StressScenario,
    *,
    seed: int = 7,
    minutes_per_bar: int = 240,
) -> pd.DataFrame:
    """Expand 4-hour stress candles into executable one-minute trade/mark rows."""

    if minutes_per_bar < 2:
        raise ValueError("minutes_per_bar must be at least 2")
    name = scenario.name if isinstance(scenario, StressScenario) else str(scenario)
    if name not in SCENARIO_BY_NAME:
        raise ValueError(f"unknown stress scenario {name!r}")
    required = {"open", "high", "low", "close", "quote_volume"}
    missing = required - set(market.columns)
    if missing:
        raise ValueError(f"market missing columns: {sorted(missing)}")
    rng = np.random.default_rng(seed + 10_000)
    records: list[dict[str, object]] = []
    for timestamp, row in market.sort_index().iterrows():
        bar_open = float(row.open)
        bar_close = float(row.close)
        # Log interpolation avoids negative prices while preserving the bar close.
        path = np.exp(np.linspace(np.log(bar_open), np.log(bar_close), minutes_per_bar))
        noise = rng.normal(
            0.0, 0.0008 if name != "liquidity_crunch" else 0.003, minutes_per_bar
        )
        path *= np.exp(noise)
        path[0] = bar_open
        path[-1] = bar_close
        mid = minutes_per_bar // 2
        for minute in range(minutes_per_bar):
            current = float(path[minute])
            previous = bar_open if minute == 0 else float(path[minute - 1])
            high = max(previous, current)
            low = min(previous, current)
            if minute == mid:
                high = max(high, float(row.high))
                low = min(low, float(row.low))
            timestamp_minute = pd.Timestamp(timestamp) + pd.Timedelta(minutes=minute)
            quote = max(float(row.quote_volume) / minutes_per_bar, 1.0)
            if name == "liquidity_crunch":
                quote *= 0.01
            records.append(
                {
                    "timestamp": timestamp_minute,
                    "trade_open": previous,
                    "trade_high": high,
                    "trade_low": low,
                    "trade_close": current,
                    "trade_volume": quote / max(current, 1e-12),
                    "trade_quote_volume": quote,
                    "mark_open": previous,
                    "mark_high": high,
                    "mark_low": low,
                    "mark_close": current,
                }
            )
    return pd.DataFrame.from_records(records).set_index("timestamp").sort_index()


def _params_for_engine(
    params: StrategyParams | V6Params | dict[str, object] | None, engine: str
):
    if engine == "v6":
        if params is None:
            return V6Params()
        if isinstance(params, V6Params):
            return params
        if isinstance(params, dict):
            return V6Params(**params)
        raise TypeError("engine='v6' requires V6Params or a parameter dictionary")
    if engine == "strategy":
        if params is None:
            return StrategyParams()
        if isinstance(params, StrategyParams):
            return params
        if isinstance(params, dict):
            return StrategyParams(**params)
        raise TypeError(
            "engine='strategy' requires StrategyParams or a parameter dictionary"
        )
    raise ValueError("engine must be 'strategy' or 'v6'")


def _generate_signals(
    market: pd.DataFrame, params: StrategyParams | V6Params, engine: str
) -> pd.DataFrame:
    return (
        generate_v6_signals(market, params)
        if engine == "v6"
        else generate_signals(market, params)
    )


def _metric_value(metrics: dict[str, float], key: str, default: float = 0.0) -> float:
    value = metrics.get(key, default)
    return float(value) if np.isfinite(value) else default


def run_stress_suite(
    params: StrategyParams | V6Params | dict[str, object] | None = None,
    *,
    engine: str = "v6",
    scenarios: Sequence[str] | None = None,
    bars: int = 420,
    seed: int = 7,
    repeats: int = 1,
    minutes_per_bar: int = 240,
    initial_price: float = 100_000.0,
    backtest_config: BacktestConfig | None = None,
    micro_config: MicroBacktestConfig | None = None,
) -> StressSuiteResult:
    """Run all requested stress scenarios and return machine-readable results.

    Each scenario is run ``repeats`` times through the minute engine: once with
    the strategy's supplied protection levels and once with those columns removed.
    This makes stop/take-profit effectiveness and path stability measurable
    instead of relying on a trade count.
    """

    selected = list(scenarios) if scenarios is not None else list_stress_scenarios()
    unknown = sorted(set(selected) - set(SCENARIO_BY_NAME))
    if unknown:
        raise ValueError(f"unknown stress scenarios: {unknown}")
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    if minutes_per_bar < 2:
        raise ValueError("minutes_per_bar must be at least 2")
    strategy_params = _params_for_engine(params, engine)
    bt_config = backtest_config or BacktestConfig(initial_cash=10_000.0)
    micro_bt_config = micro_config or MicroBacktestConfig(
        initial_cash=bt_config.initial_cash
    )
    rows: list[dict[str, object]] = []
    details: dict[str, dict[str, object]] = {}
    run_number = 0
    for offset, name in enumerate(selected):
        for repeat in range(repeats):
            run_number += 1
            # Keep the first run of a scenario stable when ``repeats`` changes.
            run_seed = seed + offset * 1_009 + repeat
            market = generate_stress_market(
                name, bars=bars, seed=run_seed, initial_price=initial_price
            )
            signaled = _generate_signals(market, strategy_params, engine)
            coarse = run_backtest(signaled, bt_config)
            intrabar = generate_stress_intrabar(
                market, name, seed=run_seed, minutes_per_bar=minutes_per_bar
            )
            protected = run_micro_backtest(
                signaled, [intrabar], market[["funding_rate"]], micro_bt_config
            )
            unprotected_signals = signaled.drop(
                columns=["stop_price", "take_profit_price"], errors="ignore"
            )
            unprotected = run_micro_backtest(
                unprotected_signals,
                [intrabar],
                market[["funding_rate"]],
                micro_bt_config,
            )
            fills = protected.fills
            stop_count = (
                int((fills["reason"] == "stop_loss").sum()) if "reason" in fills else 0
            )
            take_count = (
                int((fills["reason"] == "take_profit").sum())
                if "reason" in fills
                else 0
            )
            protection_count = stop_count + take_count
            stop_pnl = (
                float(fills.loc[fills["reason"] == "stop_loss", "realized_pnl"].sum())
                if {"reason", "realized_pnl"}.issubset(fills.columns)
                else 0.0
            )
            take_pnl = (
                float(fills.loc[fills["reason"] == "take_profit", "realized_pnl"].sum())
                if {"reason", "realized_pnl"}.issubset(fills.columns)
                else 0.0
            )
            prot_dd = _metric_value(protected.metrics, "max_drawdown")
            raw_dd = _metric_value(unprotected.metrics, "max_drawdown")
            margin_buffer = _metric_value(protected.metrics, "minimum_margin_buffer")
            liquidation_count = int(
                _metric_value(protected.metrics, "liquidation_count")
            )
            max_leverage = _metric_value(protected.metrics, "max_leverage_observed")
            position_observed = max_leverage > 1e-9
            # Positive score means the account remained solvent with controlled drawdown.
            robust_score = (
                1.0
                + _metric_value(protected.metrics, "total_return")
                + prot_dd
                + (0.25 if liquidation_count == 0 else -1.0)
                + (0.10 if margin_buffer >= 0 else -0.25)
            )
            row = {
                "scenario": name,
                "run": repeat + 1,
                "seed": run_seed,
                "description": SCENARIO_BY_NAME[name].description,
                "engine": engine,
                "bars": bars,
                "coarse_total_return": _metric_value(coarse.metrics, "total_return"),
                "coarse_max_drawdown": _metric_value(coarse.metrics, "max_drawdown"),
                "final_equity": _metric_value(protected.metrics, "final_equity"),
                "total_return": _metric_value(protected.metrics, "total_return"),
                "max_drawdown": prot_dd,
                "max_leverage_observed": _metric_value(
                    protected.metrics, "max_leverage_observed"
                ),
                "trade_count": int(_metric_value(protected.metrics, "trade_count")),
                "fill_count": int(_metric_value(protected.metrics, "fill_count")),
                "position_observed": position_observed,
                "max_margin_ratio": _metric_value(
                    protected.metrics, "max_margin_ratio"
                ),
                "minimum_margin_buffer": margin_buffer,
                "liquidation_count": liquidation_count,
                "liquidation_free": liquidation_count == 0,
                "stop_loss_count": stop_count,
                "take_profit_count": take_count,
                "stop_loss_realized_pnl": stop_pnl,
                "take_profit_realized_pnl": take_pnl,
                "protection_exit_count": protection_count,
                "protection_available": protection_count > 0
                or {"stop_price", "take_profit_price"}.issubset(signaled.columns),
                "unprotected_max_drawdown": raw_dd,
                # Less-negative protected drawdown is a positive improvement.
                "drawdown_improvement": prot_dd - raw_dd,
                "unprotected_liquidation_count": int(
                    _metric_value(unprotected.metrics, "liquidation_count")
                ),
                "protected_vs_unprotected_return_delta": _metric_value(
                    protected.metrics, "total_return"
                )
                - _metric_value(unprotected.metrics, "total_return"),
                "robust_score": float(robust_score),
                "survives": bool(
                    liquidation_count == 0
                    and _metric_value(protected.metrics, "final_equity") > 0
                ),
                "tested_with_position": bool(position_observed),
            }
            rows.append(row)
            details[f"{name}__run{repeat + 1}"] = {
                "scenario": asdict(SCENARIO_BY_NAME[name]),
                "run": repeat + 1,
                "seed": run_seed,
                "market": market.reset_index().to_dict(orient="records"),
                "strategy_metrics": coarse.metrics,
                "protected_metrics": protected.metrics,
                "unprotected_metrics": unprotected.metrics,
                "fills": fills.to_dict(orient="records"),
                "liquidations": protected.liquidations.to_dict(orient="records"),
                "funding": protected.funding.to_dict(orient="records"),
            }
    summary = pd.DataFrame.from_records(rows)
    if not summary.empty:
        summary = summary.sort_values("robust_score", ascending=False).reset_index(
            drop=True
        )
    if summary.empty:
        aggregate = {
            "scenario_survival_rate": 0.0,
            "position_coverage_rate": 0.0,
            "active_run_count": 0,
            "liquidation_scenario_count": 0,
            "liquidation_run_count": 0,
            "worst_max_drawdown": 0.0,
            "worst_total_return": 0.0,
            "median_total_return": 0.0,
            "total_return_std": 0.0,
            "max_drawdown_std": 0.0,
            "robust_score_std": 0.0,
            "protection_improved_scenario_count": 0,
            "protection_improved_run_count": 0,
            "mean_drawdown_improvement": 0.0,
        }
    else:
        liquidation_runs = int((summary["liquidation_count"] > 0).sum())
        improved_runs = int((summary["drawdown_improvement"] > 0).sum())
        liquidation_scenarios = int(
            summary.loc[summary["liquidation_count"] > 0, "scenario"].nunique()
        )
        improved_scenarios = int(
            summary.loc[summary["drawdown_improvement"] > 0, "scenario"].nunique()
        )
        aggregate = {
            "scenario_survival_rate": float(summary["survives"].mean()),
            "position_coverage_rate": float(summary["position_observed"].mean()),
            "active_run_count": int(summary["position_observed"].sum()),
            "liquidation_scenario_count": liquidation_scenarios,
            "liquidation_run_count": liquidation_runs,
            "worst_max_drawdown": float(summary["max_drawdown"].min()),
            "worst_total_return": float(summary["total_return"].min()),
            "median_total_return": float(summary["total_return"].median()),
            "total_return_std": float(summary["total_return"].std(ddof=0)),
            "max_drawdown_std": float(summary["max_drawdown"].std(ddof=0)),
            "robust_score_std": float(summary["robust_score"].std(ddof=0)),
            "protection_improved_scenario_count": improved_scenarios,
            "protection_improved_run_count": improved_runs,
            "mean_drawdown_improvement": float(summary["drawdown_improvement"].mean()),
        }
    metadata = {
        "engine": engine,
        "seed": seed,
        "repeats": repeats,
        "minutes_per_bar": minutes_per_bar,
        "bars": bars,
        "initial_price": initial_price,
        "scenario_count": len(selected),
        "run_count": run_number,
        "strategy": strategy_params.to_dict(),
        "backtest": asdict(bt_config),
        "micro_backtest": asdict(micro_bt_config),
        "aggregate": aggregate,
    }
    return StressSuiteResult(summary=summary, details=details, metadata=metadata)


def write_stress_report(result: StressSuiteResult, output_dir: str | Path) -> None:
    """Write summary CSV plus a JSON report and per-scenario execution logs."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    result.summary.to_csv(output / "stress_summary.csv", index=False)
    payload = {
        "metadata": result.metadata,
        "summary": result.summary.to_dict(orient="records"),
        "details": result.details,
    }
    (output / "stress_report.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    for name, detail in result.details.items():
        (output / f"{name}_metrics.json").write_text(
            json.dumps(detail, indent=2, default=str), encoding="utf-8"
        )
        market_records = detail.get("market")
        if isinstance(market_records, list) and market_records:
            pd.DataFrame.from_records(market_records).to_csv(
                output / f"{name}_market.csv", index=False
            )
