#!/usr/bin/env python3
"""Evaluate a small, pre-declared V6 leverage ladder without tuning V1-V5."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.backtest import BacktestConfig, run_backtest  # noqa: E402
from btc_regime.v6 import V6Params, generate_v6_signals  # noqa: E402


MARKET = ROOT / "reports/annual_2020_2026_08_25/market_4h_full.csv"
FUNDING = ROOT / "reports/annual_2020_2026_08_25/funding_full.csv"
PARAMS = ROOT / "configs/v6_params.json"
OUTPUT = ROOT / "reports/v6_leverage_grid.csv"

CANDIDATES = (
    {"name": "v6_base", "target_vol": 1.075, "risk_per_trade": 0.03, "max_leverage": 4.5, "stop_atr": 2.0, "take_profit_atr": 3.0, "trailing_atr": 3.0},
    {"name": "lev_45_balanced", "target_vol": 1.4, "risk_per_trade": 0.04, "max_leverage": 4.5, "stop_atr": 2.0, "take_profit_atr": 3.0, "trailing_atr": 3.0},
    {"name": "lev_45_wide", "target_vol": 1.4, "risk_per_trade": 0.04, "max_leverage": 4.5, "stop_atr": 2.5, "take_profit_atr": 4.0, "trailing_atr": 3.5},
    {"name": "v6_leverage", "target_vol": 1.8, "risk_per_trade": 0.05, "max_leverage": 6.5, "stop_atr": 2.0, "take_profit_atr": 3.0, "trailing_atr": 3.0},
    {"name": "lev_65_wide", "target_vol": 1.8, "risk_per_trade": 0.05, "max_leverage": 6.5, "stop_atr": 2.5, "take_profit_atr": 4.0, "trailing_atr": 3.5},
    {"name": "lev_65_tight", "target_vol": 2.2, "risk_per_trade": 0.06, "max_leverage": 6.5, "stop_atr": 1.5, "take_profit_atr": 2.5, "trailing_atr": 2.5},
    {"name": "lev_65_widerisk", "target_vol": 2.2, "risk_per_trade": 0.06, "max_leverage": 6.5, "stop_atr": 2.5, "take_profit_atr": 4.0, "trailing_atr": 3.5},
)


def load_market() -> pd.DataFrame:
    market = pd.read_csv(MARKET, index_col=0, parse_dates=True)
    market.index = pd.to_datetime(market.index, utc=True, format="mixed")
    funding = pd.read_csv(FUNDING, index_col=0)
    funding.index = pd.to_datetime(funding.index, utc=True, format="mixed")
    market["funding_rate"] = funding["funding_rate"].groupby(funding.index.floor("4h")).sum().reindex(
        market.index, fill_value=0.0
    )
    return market


def main() -> None:
    base = json.loads(PARAMS.read_text(encoding="utf-8"))
    market = load_market()
    config = BacktestConfig(initial_cash=10_000.0, fee_bps=4.0, slippage_bps=1.0)
    rows: list[dict[str, object]] = []
    for candidate in CANDIDATES:
        overrides = {key: value for key, value in candidate.items() if key != "name"}
        params = V6Params(**{**base, **overrides})
        signaled = generate_v6_signals(market, params)
        signaled.index = signaled.index + pd.Timedelta(hours=4)
        row: dict[str, object] = dict(candidate)
        for label, start, end in (
            ("dev", "2020-01-01", "2025-01-01"),
            ("hold", "2025-01-01", "2026-08-25 08:00"),
            ("recent", "2026-07-01", "2026-08-25 08:00"),
        ):
            frame = signaled.loc[(signaled.index >= start) & (signaled.index <= end)]
            metrics = run_backtest(frame, config).metrics
            for key in ("total_return", "cagr", "sharpe", "max_drawdown", "max_leverage_observed", "turnover_multiple"):
                row[f"{label}_{key}"] = metrics[key]
        rows.append(row)
    table = pd.DataFrame(rows)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUTPUT, index=False)
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
