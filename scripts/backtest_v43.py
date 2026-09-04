#!/usr/bin/env python3
"""Run the V4.3 maker-limit and fast-downside validation.

The report includes a same-signal taker-cost counterfactual so the maker fee
benefit is separated from changes in the trading signal itself.  A full run is
causal and uses the same 1m liquidity, funding and margin assumptions as the
V4.1 reports. ``--fee-rebate-rate`` applies a trading-fee rebate without
changing the original no-rebate reports.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.data import iter_intrabar_months, load_funding, load_market_data  # noqa: E402
from btc_regime.micro_backtest import (  # noqa: E402
    MicroBacktestConfig,
    micro_period_metrics,
    run_micro_backtest,
)
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402
from btc_regime.v43 import V43Params, generate_v43_signals  # noqa: E402


DEFAULT_PARAMS = ROOT / "configs/v4_3_params.json"
DEFAULT_V41_PARAMS = ROOT / "configs/v4_refined_params.json"
DEFAULT_OUTPUT = ROOT / "reports/v4_3_micro"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _run(
    signaled: pd.DataFrame,
    args: argparse.Namespace,
    funding: pd.DataFrame,
    *,
    maker: bool,
) -> object:
    effective_taker_fee_bps = args.taker_fee_bps * (1.0 - args.fee_rebate_rate)
    effective_maker_fee_bps = args.maker_fee_bps * (1.0 - args.fee_rebate_rate)
    config = MicroBacktestConfig(
        taker_fee_bps=effective_taker_fee_bps,
        maker_fee_bps=effective_maker_fee_bps,
        maker_offset_bps=args.maker_offset_bps,
        maker_order_timeout_minutes=args.maker_timeout_minutes,
        maker_enabled=maker,
        maker_exit_enabled=False,
        base_slippage_bps=args.slippage_bps,
        impact_bps=args.impact_bps,
        max_minute_participation=args.participation,
        liquidation_fee_bps=args.liquidation_fee_bps,
    )
    return run_micro_backtest(
        signaled,
        iter_intrabar_months(args.raw_dir, start=args.start, end=args.end),
        funding,
        config,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", type=Path, default=DEFAULT_PARAMS)
    parser.add_argument("--v41-params", type=Path, default=DEFAULT_V41_PARAMS)
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--taker-fee-bps", type=float, default=4.0)
    parser.add_argument("--maker-fee-bps", type=float, default=0.2)
    parser.add_argument(
        "--maker-offset-bps",
        type=float,
        default=None,
        help="post-only quote offset; defaults to maker_offset_bps in the parameter file",
    )
    parser.add_argument("--maker-timeout-minutes", type=int, default=60)
    parser.add_argument(
        "--fee-rebate-rate",
        type=float,
        default=0.0,
        help="trading-fee rebate applied to both maker and taker rates (0-1)",
    )
    parser.add_argument("--slippage-bps", type=float, default=1.0)
    parser.add_argument("--impact-bps", type=float, default=8.0)
    parser.add_argument("--participation", type=float, default=0.02)
    parser.add_argument("--liquidation-fee-bps", type=float, default=50.0)
    parser.add_argument(
        "--skip-counterfactual",
        action="store_true",
        help="only run V4.3 maker execution (useful for a quick long sample)",
    )
    args = parser.parse_args()
    if not 0.0 <= args.fee_rebate_rate < 1.0:
        parser.error("--fee-rebate-rate must be in [0, 1)")

    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    # Always include the available 2020 history as indicator warm-up when a
    # sub-period is requested.  Otherwise EMA/ADX/ATR values at the start of a
    # 2025 holdout would be based on an artificially short sample.
    requested_start = pd.Timestamp(args.start, tz="UTC")
    load_start = "2020-01-01" if requested_start > pd.Timestamp("2020-01-01", tz="UTC") else args.start
    market = load_market_data(args.raw_dir, start=load_start, end=args.end)
    funding = load_funding(args.raw_dir, start=args.start, end=args.end)
    params = V43Params(**_read_json(args.params))
    if args.maker_offset_bps is None:
        args.maker_offset_bps = params.maker_offset_bps
    signaled = generate_v43_signals(market, params)
    requested_signaled = signaled.loc[
        (signaled.index >= start) & (signaled.index < end)
    ]
    maker_result = _run(signaled, args, funding, maker=True)

    counterfactual = None
    v41_baseline = None
    if not args.skip_counterfactual:
        taker_result = _run(signaled, args, funding, maker=False)
        counterfactual = {
            "metrics": taker_result.metrics,
            "periods": micro_period_metrics(taker_result),
        }
        v41_params = StrategyParams(**_read_json(args.v41_params))
        v41_signaled = generate_signals(market, v41_params)
        v41_result = _run(v41_signaled, args, funding, maker=False)
        v41_baseline = {
            "params": v41_params.to_dict(),
            "metrics": v41_result.metrics,
            "periods": micro_period_metrics(v41_result),
        }

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    maker_result.equity.to_csv(output / "micro_equity.csv", header=True)
    maker_result.fills.to_csv(output / "micro_fills.csv", index=False)
    maker_result.trades.to_csv(output / "micro_trades.csv", index=False)
    maker_result.liquidations.to_csv(output / "micro_liquidations.csv", index=False)
    maker_result.funding.to_csv(output / "micro_funding.csv", index=False)

    payload: dict[str, object] = {
        "version": "V4.3",
        "data": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "market_source": "Binance USD-M 4h archive",
            "intrabar_source": "Binance USD-M 1m archive",
        },
        "strategy": params.to_dict(),
        "signal_diagnostics": {
            "downside_trigger_count": int(requested_signaled["v43_downside_trigger"].sum()),
            "fast_downside_exit_count": int(
                (requested_signaled["v43_stop_reason"] == "fast_downside_stop").sum()
            ),
            "protective_exit_count": int(
                (requested_signaled["v43_stop_reason"] == "protective_exit").sum()
            ),
        },
        "execution": {
            **asdict(
                MicroBacktestConfig(
                    taker_fee_bps=args.taker_fee_bps * (1.0 - args.fee_rebate_rate),
                    maker_fee_bps=args.maker_fee_bps * (1.0 - args.fee_rebate_rate),
                    maker_offset_bps=args.maker_offset_bps,
                    maker_order_timeout_minutes=args.maker_timeout_minutes,
                    maker_enabled=True,
                    base_slippage_bps=args.slippage_bps,
                    impact_bps=args.impact_bps,
                    max_minute_participation=args.participation,
                    liquidation_fee_bps=args.liquidation_fee_bps,
                )
            ),
            "base_taker_fee_bps": args.taker_fee_bps,
            "base_maker_fee_bps": args.maker_fee_bps,
            "fee_rebate_rate": args.fee_rebate_rate,
            "effective_taker_fee_bps": args.taker_fee_bps * (1.0 - args.fee_rebate_rate),
            "effective_maker_fee_bps": args.maker_fee_bps * (1.0 - args.fee_rebate_rate),
        },
        "metrics": maker_result.metrics,
        "periods": micro_period_metrics(maker_result),
        "taker_counterfactual": counterfactual,
        "v41_taker_baseline": v41_baseline,
        "method": {
            "maker": (
                "post-only limit at open +/- maker_offset_bps; fill only when the "
                "minute trade range touches the quote; partial fills are capped "
                "by max_minute_participation"
            ),
            "risk": "stop, take-profit and liquidation exits are taker for latency",
            "causality": "signals and levels from a completed 4h candle apply at the next boundary",
            "fee_rebate_rate": args.fee_rebate_rate,
            "fee_method": "effective fee = configured fee * (1 - rebate rate); rebate is applied to trading fees only",
            "limitations": [
                "historical order-book queue and maker fill probability are unavailable",
                "OHLC touch is a deterministic fill proxy and should be stress-tested",
            ],
        },
    }
    (output / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # Keep the conventional filename used by the older micro-backtest reports
    # while retaining the richer V4.3 comparison in report.json.
    (output / "micro_metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"V4.3_maker": maker_result.metrics, "taker_counterfactual": counterfactual}, indent=2))


if __name__ == "__main__":
    main()
