"""Auditable research helpers; date weights affect selection, never trading."""
from __future__ import annotations

from dataclasses import replace
from itertools import product

import numpy as np
import pandas as pd

from .micro_backtest import MicroBacktestConfig, run_micro_backtest
from .v441 import V441Params, generate_v441_signals

PERIODS = {
    "legacy": ("2020-01-01", "2024-01-01"),
    "recent_train": ("2024-01-15", "2025-01-01"),
    "recent_validation": ("2025-01-15", "2025-07-01"),
    "holdout": ("2025-07-15", "2026-08-01"),
    "post2024": ("2024-01-01", "2026-08-01"),
}


def candidate_grid() -> list[V441Params]:
    return [V441Params(regime_fast=f, regime_slow=s, long_trailing_atr=t,
                       entry_mode=e, short_enabled=sh)
            for (f, s), t, e, sh in product([(8, 32), (12, 48), (20, 80)],
                                          [3.0, 4.0], ["trend", "reclaim"], [False, True])]


def hourly_execution(data: pd.DataFrame) -> pd.DataFrame:
    out = data.rename(columns={c: "trade_" + c for c in
                              ["open", "high", "low", "close", "volume", "quote_volume"]})
    return out[[c for c in out if c.startswith(("trade_", "mark_"))]]


def daily_equity(equity: pd.Series) -> pd.Series:
    # Values carry completion timestamps; midnight belongs to the day just ended.
    return equity.resample("1D", closed="right", label="right").last().dropna()


def metrics(equity: pd.Series, trades: pd.DataFrame) -> dict:
    daily = daily_equity(equity)
    returns = daily.pct_change().dropna()
    years = (equity.index[-1] - equity.index[0]).total_seconds() / (365.25 * 86400)
    growth = float(np.log(equity.iloc[-1] / equity.iloc[0]) / years)
    sd = returns.std(ddof=1)
    shorts = trades.loc[trades.side.eq("short")] if len(trades) else trades
    short_returns = shorts.pnl / shorts.equity_before if len(shorts) else pd.Series(dtype=float)
    return {"total_return": float(equity.iloc[-1] / equity.iloc[0] - 1),
            "cagr": float(np.expm1(growth)), "annual_log_growth": growth,
            "sharpe": float(returns.mean() / sd * np.sqrt(365.25)) if sd > 0 else 0.0,
            "annual_volatility": float(sd * np.sqrt(365.25)),
            "max_drawdown": float((equity / equity.cummax() - 1).min()),
            "cycles": len(trades), "short_cycles": len(shorts),
            "short_sum_trade_returns": float(short_returns.sum()),
            "cycles_per_year": float(len(trades) / years), "days": len(returns)}


def proxy_config() -> MicroBacktestConfig:
    return MicroBacktestConfig(signal_interval_minutes=60, equity_interval_minutes=60,
                               execution_bar_minutes=60, periods_per_year=8760,
                               taker_fee_bps=4, base_slippage_bps=2, impact_bps=0,
                               conservative_protection=True)


def proxy_run(data: pd.DataFrame, funding: pd.DataFrame, p: V441Params,
              start: str, end: str):
    stop = pd.Timestamp(end, tz="UTC")
    first = pd.Timestamp(start, tz="UTC")
    history = data.loc[data.index < stop]
    signal = generate_v441_signals(history, p, trade_start=start)
    # Keep the last completed candle, so the first trade may execute at start.
    signal = signal.loc[signal.index >= first - pd.Timedelta(hours=1)]
    execution = hourly_execution(history.loc[history.index >= first])
    return run_micro_backtest(signal, [execution], funding, proxy_config())


def selection_score(parts: dict, weights: dict | None = None) -> float:
    weights = weights or {"legacy": .2, "recent_train": .4, "recent_validation": .4}
    weighted = sum(weights[k] * (parts[k]["sharpe"] + .25 * parts[k]["annual_log_growth"])
                   for k in weights)
    dispersion = np.std([parts["recent_train"]["sharpe"], parts["recent_validation"]["sharpe"]])
    worst_dd = max(-parts[k]["max_drawdown"] for k in weights)
    return float(weighted - .5 * dispersion - 2 * worst_dd)


def admissible(rows: list[dict]) -> list[dict]:
    profiles = {tuple(sorted({k: v for k, v in r["params"].items() if k != "short_enabled"}.items())): r
                for r in rows if not r["params"]["short_enabled"]}
    for row in rows:
        parts = row["periods"]
        enough = parts["recent_train"]["cycles"] >= 20 and parts["recent_validation"]["cycles"] >= 8
        safe = all(p["max_drawdown"] >= -.45 for p in parts.values())
        short_ok = True
        if row["params"]["short_enabled"]:
            key = tuple(sorted({k: v for k, v in row["params"].items() if k != "short_enabled"}.items()))
            base = profiles[key]["periods"]["recent_validation"]
            recent = [parts["recent_train"], parts["recent_validation"]]
            val = parts["recent_validation"]
            short_ok = (sum(p["short_cycles"] for p in recent) >= 8
                        and sum(p["short_sum_trade_returns"] for p in recent) > 0
                        and val["total_return"] >= base["total_return"]
                        and val["sharpe"] >= base["sharpe"])
        row["admission"] = {"enough_cycles": enough, "drawdown_ok": safe, "short_ok": short_ok}
        row["eligible"] = enough and safe and short_ok
    return [r for r in rows if r["eligible"]]


def select(rows: list[dict], weights: dict | None = None) -> dict:
    eligible = admissible(rows)
    if not eligible:
        raise ValueError("No candidate passed the predeclared admission rules")
    score = lambda r: selection_score(r["periods"], weights)
    best_score = max(map(score, eligible))
    near = [r for r in eligible if score(r) >= best_score - .05]
    return sorted(near, key=lambda r: (r["params"]["short_enabled"], -r["params"]["regime_slow"],
                                     -score(r), r["id"]))[0]


def paired_block_bootstrap(a: pd.Series, b: pd.Series, *, block: int = 14,
                           repeats: int = 2000, seed: int = 441) -> dict:
    returns = pd.concat([daily_equity(a).pct_change(), daily_equity(b).pct_change()], axis=1).dropna().to_numpy()
    n = len(returns)
    rng = np.random.default_rng(seed)
    stats = []
    for _ in range(repeats):
        starts = rng.integers(0, n, size=int(np.ceil(n / block)))
        indices = ((starts[:, None] + np.arange(block)) % n).ravel()[:n]
        sample = returns[indices]
        sharpe = sample.mean(axis=0) / np.maximum(sample.std(axis=0, ddof=1), 1e-12) * np.sqrt(365.25)
        loggrowth = np.log1p(sample).mean(axis=0) * 365.25
        stats.append([sharpe[0] - sharpe[1], loggrowth[0] - loggrowth[1]])
    stat = np.asarray(stats)
    return {"block_days": block, "repeats": repeats, "seed": seed,
            "sharpe_difference_95pct": np.quantile(stat[:, 0], [.025, .975]).tolist(),
            "annual_log_growth_difference_95pct": np.quantile(stat[:, 1], [.025, .975]).tolist(),
            "bootstrap_fraction_sharpe_improved": float((stat[:, 0] > 0).mean()),
            "interpretation": "Conditional uncertainty after selection; not a multiple-testing-adjusted p-value."}
