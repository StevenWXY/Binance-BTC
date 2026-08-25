#!/usr/bin/env python3
"""Run V6 regular, annual, and optional minute-level backtests from local snapshots."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.backtest import BacktestConfig, run_backtest  # noqa: E402
from btc_regime.data import iter_intrabar_months  # noqa: E402
from btc_regime.micro_backtest import (  # noqa: E402
    MicroBacktestConfig,
    run_micro_backtest,
    write_micro_report,
)
from btc_regime.v6 import V6Params, generate_v6_signals  # noqa: E402


DEFAULT_MARKET = ROOT / "reports/annual_2020_2026_08_25/market_4h_full.csv"
DEFAULT_FUNDING = ROOT / "reports/annual_2020_2026_08_25/funding_full.csv"
DEFAULT_PARAMS = ROOT / "configs/v6_params.json"


def read_market(path: Path, funding_path: Path) -> pd.DataFrame:
    market = pd.read_csv(path, index_col=0, parse_dates=True)
    market.index = pd.to_datetime(market.index, utc=True, format="mixed")
    funding = pd.read_csv(funding_path, index_col=0)
    funding.index = pd.to_datetime(funding.index, utc=True, format="mixed")
    funding_4h = funding["funding_rate"].groupby(funding.index.floor("4h")).sum()
    market["funding_rate"] = funding_4h.reindex(market.index, fill_value=0.0)
    return market.sort_index()


def metrics_row(code: str, name: str, result: object) -> dict[str, object]:
    return {"code": code, "strategy": name, **result.metrics}


def benchmark_metrics(price: pd.Series, periods_per_year: int) -> dict[str, float]:
    returns = price.pct_change().dropna()
    volatility = returns.std(ddof=1) * np.sqrt(periods_per_year)
    sharpe = returns.mean() / returns.std(ddof=1) * np.sqrt(periods_per_year) if returns.std(ddof=1) > 0 else 0.0
    drawdown = price / price.cummax() - 1.0
    return {
        "total_return": float(price.iloc[-1] / price.iloc[0] - 1.0),
        "annualized_volatility": float(volatility),
        "sharpe": float(sharpe),
        "max_drawdown": float(drawdown.min()),
        "start_price": float(price.iloc[0]),
        "end_price": float(price.iloc[-1]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", type=Path, default=DEFAULT_MARKET)
    parser.add_argument("--funding", type=Path, default=DEFAULT_FUNDING)
    parser.add_argument("--params", type=Path, default=DEFAULT_PARAMS)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/v6_2026_08_25")
    parser.add_argument("--recent-start", default="2026-07-01")
    parser.add_argument("--recent-end", default="2026-08-25 08:00")
    parser.add_argument("--run-micro", action="store_true")
    parser.add_argument("--micro-start", default="2020-01-01")
    parser.add_argument("--micro-end", default="2026-08-01")
    parser.add_argument("--micro-output", type=Path, default=ROOT / "reports/v6_micro_2020_2026_07_31")
    args = parser.parse_args()

    params = V6Params(**json.loads(args.params.read_text(encoding="utf-8")))
    market = read_market(args.market, args.funding)
    raw_signaled = generate_v6_signals(market, params)
    signaled = raw_signaled.copy()
    signaled.index = signaled.index + pd.Timedelta(hours=4)
    config = BacktestConfig(initial_cash=10_000.0, fee_bps=4.0, slippage_bps=1.0)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    signaled.to_csv(output / "v6_signals_full.csv")

    recent_start = pd.Timestamp(args.recent_start, tz="UTC")
    recent_end = pd.Timestamp(args.recent_end, tz="UTC")
    recent = signaled.loc[(signaled.index >= recent_start) & (signaled.index <= recent_end)].copy()
    recent_result = run_backtest(recent, config)
    recent_result.equity.to_csv(output / "v6_recent_equity.csv", header=True)
    recent_result.trades.to_csv(output / "v6_recent_trades.csv", index=False)
    recent_metrics = metrics_row("V6", "置信度驱动多周期动态风险", recent_result)
    market_price = market["close"].copy()
    market_price.index = market_price.index + pd.Timedelta(hours=4)
    recent_price = market_price.reindex(recent.index).dropna()
    recent_metrics["benchmark"] = benchmark_metrics(recent_price, config.periods_per_year)
    (output / "v6_recent_metrics.json").write_text(
        json.dumps(recent_metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    annual_rows: list[dict[str, object]] = []
    annual_reports: dict[str, object] = {}
    latest_year = int(recent_end.year)
    for year in range(2020, latest_year + 1):
        start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        end = recent_end if year == latest_year else pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        frame = signaled.loc[(signaled.index >= start) & (signaled.index <= end)].copy()
        result = run_backtest(frame, config)
        label = f"{year} YTD" if year == latest_year else str(year)
        row = {"period": label, "year": year, **metrics_row("V6", "置信度驱动多周期动态风险", result)}
        annual_rows.append(row)
        price = market_price.loc[(market_price.index >= start) & (market_price.index <= end)]
        annual_reports[label] = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "strategy": row,
            "benchmark": benchmark_metrics(price, config.periods_per_year),
        }
    annual = pd.DataFrame(annual_rows)
    annual.to_csv(output / "v6_annual_metrics.csv", index=False)
    (output / "v6_annual_report.json").write_text(
        json.dumps(
            {
                "strategy": params.to_dict(),
                "data": {
                    "market_file": str(args.market.relative_to(ROOT)),
                    "funding_file": str(args.funding.relative_to(ROOT)),
                    "latest_completed_bar": recent_end.isoformat(),
                },
                "method": {
                    "bar_interval": "4h",
                    "fees": "4 bps fee + 1 bps slippage",
                    "signal_timing": "completed 4h bar; position applies to next bar",
                    "parameter_protocol": "fixed V6 config; no tuning on the recent window",
                },
                "periods": annual_reports,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if args.run_micro:
        micro_signaled = raw_signaled.loc[raw_signaled.index < pd.Timestamp(args.micro_end, tz="UTC")].copy()
        funding = pd.read_csv(args.funding, index_col=0)
        funding.index = pd.to_datetime(funding.index, utc=True, format="mixed")
        funding = funding.loc[
            (funding.index >= pd.Timestamp(args.micro_start, tz="UTC"))
            & (funding.index < pd.Timestamp(args.micro_end, tz="UTC"))
        ]
        micro_config = MicroBacktestConfig(
            initial_cash=10_000.0,
            taker_fee_bps=4.0,
            base_slippage_bps=1.0,
            impact_bps=8.0,
            max_minute_participation=0.02,
            liquidation_fee_bps=50.0,
        )
        result = run_micro_backtest(
            micro_signaled,
            iter_intrabar_months(
                ROOT / "data/raw",
                start=args.micro_start,
                end=args.micro_end,
            ),
            funding,
            micro_config,
        )
        write_micro_report(result, params, micro_config, args.micro_output)
        print(json.dumps({"recent": recent_metrics, "micro": result.metrics}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(recent_metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
