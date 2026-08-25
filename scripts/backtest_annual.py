#!/usr/bin/env python3
"""Run frozen V1-V5 strategies separately for each calendar year."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.backtest import BacktestConfig, run_backtest  # noqa: E402
from btc_regime.data import (  # noqa: E402
    fetch_binance_server_time,
    fetch_recent_funding,
    fetch_recent_klines,
    load_funding,
    load_klines,
    merge_funding,
)
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402


STRATEGIES = {
    "V1": ("基础趋势跟随与 ATR 仓位", ROOT / "configs/aggressive_params.json"),
    "V2": ("资金费率拥挤过滤趋势", ROOT / "configs/aggressive_vol_carry_params.json"),
    "V3": ("波动率与下行风险自适应", ROOT / "configs/aggressive_adaptive_params.json"),
    "V4": ("稳健长多趋势-反弹混合", ROOT / "configs/aggressive_adaptive_v3_params.json"),
    "V5": ("谨慎对称趋势与空头确认", ROOT / "configs/aggressive_adaptive_v4_short_params.json"),
}
WARMUP_START = pd.Timestamp("2026-01-01", tz="UTC")


def utc_text(value: pd.Timestamp) -> str:
    return value.isoformat().replace("+00:00", "Z")


def combine_history(server_time: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Combine official archives with current REST rows, preferring REST on overlap."""
    archive_klines = load_klines(ROOT / "data/raw", start="2020-01-01", end="2026-08-01")
    recent_klines = fetch_recent_klines(WARMUP_START, server_time)
    klines = pd.concat([archive_klines, recent_klines]).sort_index()
    klines = klines.loc[~klines.index.duplicated(keep="last")]

    archive_funding = load_funding(ROOT / "data/raw", start="2020-01-01", end="2026-08-01")
    recent_funding = fetch_recent_funding(WARMUP_START, server_time)
    funding = pd.concat([archive_funding, recent_funding]).sort_index()
    funding = funding.loc[~funding.index.duplicated(keep="last")]
    return klines, funding


def benchmark_metrics(price: pd.Series, periods_per_year: int) -> dict[str, float]:
    returns = price.pct_change().dropna()
    volatility = returns.std(ddof=1) * np.sqrt(periods_per_year)
    sharpe = returns.mean() / returns.std(ddof=1) * np.sqrt(periods_per_year) if returns.std(ddof=1) > 0 else 0.0
    drawdown = price / price.cummax() - 1
    return {
        "start_price": float(price.iloc[0]),
        "end_price": float(price.iloc[-1]),
        "total_return": float(price.iloc[-1] / price.iloc[0] - 1),
        "annualized_volatility": float(volatility),
        "sharpe": float(sharpe),
        "max_drawdown": float(drawdown.min()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports/annual_2020_2026_08_25",
    )
    args = parser.parse_args()

    server_time = fetch_binance_server_time()
    klines, funding = combine_history(server_time)
    market = merge_funding(klines, funding)
    latest_close = klines.index[-1] + pd.Timedelta(hours=4)
    settlement_funding = funding["funding_rate"].groupby(funding.index.floor("4h")).sum()
    config = BacktestConfig(initial_cash=10_000.0, fee_bps=4.0, slippage_bps=1.0)

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    klines.to_csv(output / "market_4h_full.csv")
    funding.to_csv(output / "funding_full.csv")

    signaled: dict[str, pd.DataFrame] = {}
    for code, (_, params_path) in STRATEGIES.items():
        params = StrategyParams(**json.loads(params_path.read_text(encoding="utf-8")))
        frame = generate_signals(market, params)
        frame.index = frame.index + pd.Timedelta(hours=4)
        frame["funding_rate"] = settlement_funding.reindex(frame.index, fill_value=0.0)
        signaled[code] = frame

    years = list(range(2020, latest_close.year + 1))
    rows: list[dict[str, object]] = []
    report_periods: dict[str, object] = {}
    for year in years:
        start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        is_latest = year == latest_close.year
        end = latest_close if is_latest else pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        label = f"{year} YTD" if is_latest else str(year)
        year_report: dict[str, object] = {"start": utc_text(start), "end": utc_text(end), "strategies": {}}
        for code, (name, _) in STRATEGIES.items():
            frame = signaled[code].loc[(signaled[code].index >= start) & (signaled[code].index <= end)].copy()
            result = run_backtest(frame, config)
            metrics = result.metrics
            row = {"period": label, "year": year, "code": code, "strategy": name, **metrics}
            rows.append(row)
            year_report["strategies"][code] = {"name": name, "metrics": metrics}
        price = market["close"].copy()
        price.index = price.index + pd.Timedelta(hours=4)
        price = price.loc[(price.index >= start) & (price.index <= end)]
        benchmark = benchmark_metrics(price, config.periods_per_year)
        rows.append({"period": label, "year": year, "code": "P", "strategy": "BTCUSDT 价格", **benchmark})
        year_report["benchmark"] = {"code": "P", "name": "BTCUSDT 价格", **benchmark}
        report_periods[label] = year_report

    annual = pd.DataFrame(rows)
    annual.to_csv(output / "annual_metrics.csv", index=False)
    report = {
        "generated_at_binance_server_time": utc_text(server_time),
        "data": {
            "source": "Binance USD-M Futures official archives plus public REST API",
            "symbol": "BTCUSDT",
            "contract": "USDT-margined perpetual",
            "warmup_start": "2020-01-01T00:00:00Z",
            "latest_completed_close": utc_text(latest_close),
            "kline_rows": int(len(klines)),
            "funding_events": int(len(funding)),
        },
        "method": {
            "bar_interval": "4h",
            "annual_window": "calendar year; 2026 is year-to-date through latest completed bar",
            "signal_timing": "completed candle at t; position applies over (t, t+4h]",
            "execution_model": "close-to-close; fees 4 bps + slippage 1 bps; no intrabar liquidation",
            "annualization": "each year is evaluated independently from 10,000 USDT, while indicators use continuous full-history warm-up",
            "parameters": "frozen existing V1-V5 configurations; no tuning on annual windows",
        },
        "backtest": asdict(config),
        "periods": report_periods,
    }
    (output / "annual_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(annual.to_string(index=False))


if __name__ == "__main__":
    main()
