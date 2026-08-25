#!/usr/bin/env python3
"""Backtest frozen V1-V5 strategies on the latest completed Binance 4h bars."""

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
    load_klines,
    merge_funding,
)
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402


WINDOW_START = pd.Timestamp("2026-07-01 00:00:00", tz="UTC")
WARMUP_START = pd.Timestamp("2026-01-01 00:00:00", tz="UTC")
STRATEGIES = {
    "V1": ("基础趋势跟随与 ATR 仓位", ROOT / "configs/aggressive_params.json"),
    "V2": ("资金费率拥挤过滤趋势", ROOT / "configs/aggressive_vol_carry_params.json"),
    "V3": ("波动率与下行风险自适应", ROOT / "configs/aggressive_adaptive_params.json"),
    "V4": ("稳健长多趋势-反弹混合", ROOT / "configs/aggressive_adaptive_v3_params.json"),
    "V5": ("谨慎对称趋势与空头确认", ROOT / "configs/aggressive_adaptive_v4_short_params.json"),
}


def utc_text(value: pd.Timestamp) -> str:
    return value.isoformat().replace("+00:00", "Z")


def archive_validation(rest_klines: pd.DataFrame) -> dict[str, float | int | str]:
    archive = load_klines(ROOT / "data/raw", start="2026-01-01", end="2026-08-01")
    common = archive.index.intersection(rest_klines.index)
    if common.empty:
        return {"overlap_rows": 0, "status": "no overlap"}
    differences = (archive.loc[common, ["open", "high", "low", "close"]]
                   - rest_klines.loc[common, ["open", "high", "low", "close"]]).abs()
    return {
        "overlap_rows": int(len(common)),
        "first_open_time": utc_text(common[0]),
        "last_open_time": utc_text(common[-1]),
        "max_ohlc_absolute_difference": float(differences.max().max()),
        "status": "match" if float(differences.max().max()) == 0 else "mismatch",
    }


def benchmark_metrics(price: pd.Series, periods_per_year: int) -> dict[str, float]:
    returns = price.pct_change().dropna()
    volatility = float(returns.std(ddof=1) * np.sqrt(periods_per_year))
    sharpe = (
        float(returns.mean() / returns.std(ddof=1) * np.sqrt(periods_per_year))
        if returns.std(ddof=1) > 0 else 0.0
    )
    drawdown = price / price.cummax() - 1
    return {
        "start_price": float(price.iloc[0]),
        "end_price": float(price.iloc[-1]),
        "total_return": float(price.iloc[-1] / price.iloc[0] - 1),
        "annualized_volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports/recent_2026_07_01_2026_08_25",
    )
    args = parser.parse_args()

    server_time = fetch_binance_server_time()
    klines = fetch_recent_klines(WARMUP_START, server_time)
    funding = fetch_recent_funding(WARMUP_START, server_time)
    market = merge_funding(klines, funding)
    last_completed_close = klines.index[-1] + pd.Timedelta(hours=4)
    if last_completed_close > server_time:
        raise ValueError("incomplete 4h candle was not removed")

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    klines.to_csv(output / "market_4h_warmup_snapshot.csv")
    funding.to_csv(output / "funding_snapshot.csv")

    config = BacktestConfig(initial_cash=10_000.0, fee_bps=4.0, slippage_bps=1.0)
    equities: dict[str, pd.Series] = {}
    signals: dict[str, pd.Series] = {}
    strategy_report: dict[str, object] = {}
    metric_rows: list[dict[str, object]] = []

    settlement_funding = funding["funding_rate"].groupby(funding.index.floor("4h")).sum()
    for code, (name, params_path) in STRATEGIES.items():
        params = StrategyParams(**json.loads(params_path.read_text(encoding="utf-8")))
        decision_frame = generate_signals(market, params)
        decision_frame.index = decision_frame.index + pd.Timedelta(hours=4)
        # Position signal at t is held over (t, t+4h]. Charge only events at the
        # interval end; an event exactly at t belongs to the preceding position.
        decision_frame["funding_rate"] = settlement_funding.reindex(
            decision_frame.index, fill_value=0.0
        )
        window = decision_frame.loc[
            (decision_frame.index >= WINDOW_START)
            & (decision_frame.index <= last_completed_close)
        ].copy()
        result = run_backtest(window, config)
        exposure = window["signal"].abs() > 1e-12
        extra = {
            "exposure_time": float(exposure.mean()),
            "long_exposure_time": float((window["signal"] > 1e-12).mean()),
            "short_exposure_time": float((window["signal"] < -1e-12).mean()),
        }
        metrics = {**result.metrics, **extra}
        strategy_report[code] = {
            "name": name,
            "params_file": str(params_path.relative_to(ROOT)),
            "metrics": metrics,
        }
        metric_rows.append({"code": code, "strategy": name, **metrics})
        equities[code] = result.equity.rename(code)
        signals[code] = window["signal"].rename(code)
        result.trades.to_csv(output / f"trades_{code.lower()}.csv", index=False)

    equity_frame = pd.concat(equities.values(), axis=1)
    signal_frame = pd.concat(signals.values(), axis=1)
    price = market["close"].copy()
    price.index = price.index + pd.Timedelta(hours=4)
    price = price.reindex(equity_frame.index).rename("P")
    curves = equity_frame.join(price)
    curves.to_csv(output / "equity_and_btc.csv")
    signal_frame.to_csv(output / "signals.csv")
    pd.DataFrame(metric_rows).to_csv(output / "metrics.csv", index=False)

    report = {
        "generated_at_binance_server_time": utc_text(server_time),
        "window": {
            "start": utc_text(WINDOW_START),
            "end": utc_text(last_completed_close),
            "timezone": "UTC",
            "completed_4h_intervals": int(len(equity_frame) - 1),
        },
        "data": {
            "source": "Binance USD-M Futures public REST API",
            "symbol": "BTCUSDT",
            "contract": "USDT-margined perpetual",
            "kline_endpoint": "/fapi/v1/klines",
            "funding_endpoint": "/fapi/v1/fundingRate",
            "warmup_start": utc_text(WARMUP_START),
            "completed_kline_rows": int(len(klines)),
            "funding_events": int(len(funding)),
            "archive_cross_check": archive_validation(klines),
        },
        "method": {
            "bar_interval": "4h",
            "signal_timing": "completed candle at t; position applies over (t, t+4h]",
            "funding_timing": "real event rate in (t, t+4h], settled at interval end",
            "execution_model": "close-to-close; no intrabar liquidation simulation",
            "parameters": "frozen existing V1-V5 configurations; no tuning on this window",
        },
        "backtest": asdict(config),
        "strategies": strategy_report,
        "benchmark": {"code": "P", "name": "BTCUSDT price", **benchmark_metrics(price.reindex(equity_frame.index), config.periods_per_year)},
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
