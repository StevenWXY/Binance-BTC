"""Backtest the bounded range-inventory sleeve on local 4h data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from btc_regime.backtest import BacktestConfig, run_backtest
from btc_regime.data import load_market_data
from btc_regime.range_grid import RangeGridParams, generate_range_grid_signals


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded range-grid BTCUSDT backtest")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--params", default="configs/range_grid_params.json")
    parser.add_argument("--output", default="reports/range_grid")
    parser.add_argument("--fee-bps", type=float, default=4.0)
    parser.add_argument("--slippage-bps", type=float, default=1.0)
    args = parser.parse_args()

    params = RangeGridParams(**json.loads(Path(args.params).read_text(encoding="utf-8")))
    market = load_market_data(args.raw_dir, start=args.start, end=args.end)
    signaled = generate_range_grid_signals(market, params)
    result = run_backtest(
        signaled,
        BacktestConfig(fee_bps=args.fee_bps, slippage_bps=args.slippage_bps),
    )
    periods = {
        "train_2020_2022": ("2020-01-01", "2023-01-01"),
        "validation_2023_2024": ("2023-01-01", "2025-01-01"),
        "holdout_2025_2026_07": ("2025-01-01", "2026-08-01"),
        "full_2020_2026_07": ("2020-01-01", "2026-08-01"),
    }
    report: dict[str, object] = {
        "strategy": params.to_dict(),
        "backtest": {
            "fee_bps": args.fee_bps,
            "slippage_bps": args.slippage_bps,
            "start": args.start,
            "end": args.end,
        },
        "metrics": result.metrics,
        "periods": {},
    }
    for label, (start, end) in periods.items():
        window = result.equity.loc[
            (result.equity.index >= pd.Timestamp(start, tz="UTC"))
            & (result.equity.index <= pd.Timestamp(end, tz="UTC"))
        ]
        if len(window) < 2:
            continue
        exit_time = pd.to_datetime(result.trades["exit_time"], utc=True) if not result.trades.empty else pd.Series(dtype="datetime64[ns, UTC]")
        trades = result.trades.loc[
            (exit_time >= pd.Timestamp(start, tz="UTC"))
            & (exit_time < pd.Timestamp(end, tz="UTC"))
        ] if not result.trades.empty else result.trades
        period_result = run_backtest(
            signaled.loc[(signaled.index >= pd.Timestamp(start, tz="UTC")) & (signaled.index < pd.Timestamp(end, tz="UTC"))],
            BacktestConfig(fee_bps=args.fee_bps, slippage_bps=args.slippage_bps),
        )
        report["periods"][label] = {
            **period_result.metrics,
            "trade_count": float(len(trades)),
            "signal_bars": int((signaled.loc[window.index, "signal"].abs() > 1e-12).sum()),
        }

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    result.equity.to_csv(output / "equity.csv", header=True)
    result.trades.to_csv(output / "trades.csv", index=False)
    signaled.to_csv(output / "signals.csv")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
