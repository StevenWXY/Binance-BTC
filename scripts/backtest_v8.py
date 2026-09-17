"""Run the V8 bounded range strategy with 40% fee-rebate defaults."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import pandas as pd

from btc_regime.backtest import BacktestConfig, run_backtest
from btc_regime.data import load_market_data
from btc_regime.v8 import V8Params, generate_v8_signals


def main() -> None:
    parser = argparse.ArgumentParser(description="V8 BTCUSDT range strategy backtest")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--params", default="configs/v8_params.json")
    parser.add_argument("--output", default="reports/v8")
    parser.add_argument("--fee-bps", type=float, default=2.4)
    parser.add_argument("--slippage-bps", type=float, default=1.0)
    args = parser.parse_args()

    params = V8Params(**json.loads(Path(args.params).read_text(encoding="utf-8")))
    data = load_market_data(args.raw_dir, start=args.start, end=args.end)
    signaled = generate_v8_signals(data, params)
    signaled = signaled.loc[signaled.index < pd.Timestamp(args.end, tz="UTC")]
    result = run_backtest(
        signaled,
        BacktestConfig(fee_bps=args.fee_bps, slippage_bps=args.slippage_bps),
    )
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(
        json.dumps(
            {
                "strategy": "V8",
                "parameters": params.to_dict(),
                "data": {"start": args.start, "end": args.end, "bar": "4h"},
                "execution": {
                    "effective_taker_fee_bps": args.fee_bps,
                    "slippage_bps": args.slippage_bps,
                    "fee_rebate_rate": 0.40,
                },
                "metrics": result.metrics,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    result.equity.to_csv(output / "equity.csv", header=True)
    result.trades.to_csv(output / "trades.csv", index=False)
    signaled.to_csv(output / "signals.csv")
    print(json.dumps(result.metrics, indent=2))


if __name__ == "__main__":
    main()
