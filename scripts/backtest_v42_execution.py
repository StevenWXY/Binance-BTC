#!/usr/bin/env python3
"""Backtest V4.2 with V4.3-style execution and risk controls.

The direction sleeve keeps V4.2's lower target volatility and leverage cap, then
adds the causal V4.3 protective layer and maker-only routine rebalancing.  The
funding-neutral sleeve remains V4.2's causal settled-funding proxy; its spot and
futures transition fees are reduced by the requested rebate.  Existing V4.2
reports are never overwritten.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.backtest import calculate_metrics  # noqa: E402
from btc_regime.data import iter_intrabar_months, load_funding, load_market_data  # noqa: E402
from btc_regime.micro_backtest import (  # noqa: E402
    MicroBacktestConfig,
    micro_period_metrics,
    run_micro_backtest,
)
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402
from btc_regime.v42 import (  # noqa: E402
    V42CapitalParams,
    combine_direction_and_neutral,
    generate_neutral_sleeve,
    neutral_metrics,
)
from btc_regime.v43 import V43Params, generate_v43_signals  # noqa: E402


DEFAULT_PARAMS = ROOT / "configs/v4_2_rebate30_params.json"
DEFAULT_CAPITAL_PARAMS = ROOT / "configs/v4_2_capital_params.json"
DEFAULT_OUTPUT = ROOT / "reports/v4_2_rebate30"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _period_metrics(equity: pd.Series, start: str, end: str) -> dict[str, float]:
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    window = equity.loc[(equity.index >= start_ts) & (equity.index <= end_ts)]
    if window.empty:
        return {}
    return calculate_metrics(window, window.pct_change().dropna(), pd.DataFrame(), 2190)


def portfolio_period_metrics(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    periods = {
        "train_2020_2022": ("2020-01-01", "2023-01-01"),
        "validation_2023_2024": ("2023-01-01", "2025-01-01"),
        "holdout_2025_2026_07": ("2025-01-01", "2026-08-01"),
        "full_2020_2026_07": ("2020-01-01", "2026-08-01"),
    }
    return {
        label: metrics
        for label, (start, end) in periods.items()
        if (metrics := _period_metrics(frame["combined_equity"], start, end))
    }


def _direction_config(
    *,
    maker: bool,
    taker_fee_bps: float,
    maker_fee_bps: float,
    maker_offset_bps: float,
    maker_timeout_minutes: int,
) -> MicroBacktestConfig:
    return MicroBacktestConfig(
        initial_cash=10_000.0,
        taker_fee_bps=taker_fee_bps,
        maker_fee_bps=maker_fee_bps,
        maker_offset_bps=maker_offset_bps,
        maker_order_timeout_minutes=maker_timeout_minutes,
        maker_enabled=maker,
        maker_exit_enabled=False,
        base_slippage_bps=1.0,
        impact_bps=8.0,
        max_minute_participation=0.02,
        liquidation_fee_bps=50.0,
    )


def _run_direction(
    signaled: pd.DataFrame,
    funding: pd.DataFrame,
    raw_dir: str | Path,
    start: str,
    end: str,
    config: MicroBacktestConfig,
) -> object:
    return run_micro_backtest(
        signaled,
        iter_intrabar_months(raw_dir, start=start, end=end),
        funding,
        config,
    )


def _combined(
    direction_result: object,
    neutral: pd.DataFrame,
    capital_params: V42CapitalParams,
    signaled: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, float]]:
    effective_signal = signaled["signal"].copy()
    effective_signal.index = effective_signal.index + pd.Timedelta(hours=4)
    return combine_direction_and_neutral(
        direction_result.equity,
        neutral,
        capital_params,
        effective_signal,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", type=Path, default=DEFAULT_PARAMS)
    parser.add_argument("--capital-params", type=Path, default=DEFAULT_CAPITAL_PARAMS)
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--taker-fee-bps", type=float, default=4.0)
    parser.add_argument("--maker-fee-bps", type=float, default=0.2)
    parser.add_argument("--fee-rebate-rate", type=float, default=0.30)
    parser.add_argument("--maker-offset-bps", type=float, default=None)
    parser.add_argument("--maker-timeout-minutes", type=int, default=None)
    args = parser.parse_args()
    if not 0.0 <= args.fee_rebate_rate < 1.0:
        parser.error("--fee-rebate-rate must be in [0, 1)")

    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    load_start = "2020-01-01" if start > pd.Timestamp("2020-01-01", tz="UTC") else args.start
    market = load_market_data(args.raw_dir, start=load_start, end=args.end)
    # Full funding history supplies the 30-day/settlement warm-up for a
    # requested holdout while run_micro_backtest consumes only its active range.
    funding = load_funding(args.raw_dir, start="2020-01-01", end=args.end)
    params = V43Params(**_read_json(args.params))
    maker_offset = params.maker_offset_bps if args.maker_offset_bps is None else args.maker_offset_bps
    maker_timeout = (
        params.maker_order_timeout_minutes
        if args.maker_timeout_minutes is None
        else args.maker_timeout_minutes
    )
    effective_taker = args.taker_fee_bps * (1.0 - args.fee_rebate_rate)
    effective_maker = args.maker_fee_bps * (1.0 - args.fee_rebate_rate)

    signaled = generate_v43_signals(market, params)
    neutral_capital = V42CapitalParams(**_read_json(args.capital_params))
    neutral_capital = replace(
        neutral_capital,
        spot_fee_bps=neutral_capital.spot_fee_bps * (1.0 - args.fee_rebate_rate),
        futures_fee_bps=neutral_capital.futures_fee_bps * (1.0 - args.fee_rebate_rate),
    )
    neutral = generate_neutral_sleeve(funding, neutral_capital)

    maker_config = _direction_config(
        maker=True,
        taker_fee_bps=effective_taker,
        maker_fee_bps=effective_maker,
        maker_offset_bps=maker_offset,
        maker_timeout_minutes=maker_timeout,
    )
    taker_config = _direction_config(
        maker=False,
        taker_fee_bps=effective_taker,
        maker_fee_bps=effective_maker,
        maker_offset_bps=maker_offset,
        maker_timeout_minutes=maker_timeout,
    )
    maker_direction = _run_direction(
        signaled, funding, args.raw_dir, args.start, args.end, maker_config
    )
    taker_direction = _run_direction(
        signaled, funding, args.raw_dir, args.start, args.end, taker_config
    )
    maker_combined, maker_combined_metrics = _combined(
        maker_direction, neutral, neutral_capital, signaled
    )
    taker_combined, taker_combined_metrics = _combined(
        taker_direction, neutral, neutral_capital, signaled
    )

    # Same-window legacy V4.2 reference: original direction signal, taker
    # execution at the historical 2.8 bps setting, and unreduced overlay fees.
    legacy_params = StrategyParams(**_read_json(ROOT / "configs/v4_2_params.json"))
    legacy_signaled = generate_signals(market, legacy_params)
    legacy_capital = V42CapitalParams(**_read_json(args.capital_params))
    legacy_config = _direction_config(
        maker=False,
        taker_fee_bps=2.8,
        maker_fee_bps=0.2,
        maker_offset_bps=0.5,
        maker_timeout_minutes=60,
    )
    legacy_direction = _run_direction(
        legacy_signaled, funding, args.raw_dir, args.start, args.end, legacy_config
    )
    legacy_neutral = generate_neutral_sleeve(funding, legacy_capital)
    legacy_combined, legacy_combined_metrics = _combined(
        legacy_direction, legacy_neutral, legacy_capital, legacy_signaled
    )

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    maker_direction.equity.rename("direction_equity").to_csv(
        output / "direction_maker_equity.csv", header=True
    )
    maker_direction.fills.to_csv(output / "direction_maker_fills.csv", index=False)
    maker_direction.trades.to_csv(output / "direction_maker_trades.csv", index=False)
    taker_direction.equity.rename("direction_equity").to_csv(
        output / "direction_taker_equity.csv", header=True
    )
    taker_direction.fills.to_csv(output / "direction_taker_fills.csv", index=False)
    maker_combined.to_csv(output / "combined_maker_equity.csv")
    taker_combined.to_csv(output / "combined_taker_equity.csv")
    neutral.to_csv(output / "neutral_schedule.csv")
    legacy_combined.to_csv(output / "legacy_v42_combined_equity.csv")

    requested_signaled = signaled.loc[(signaled.index >= start) & (signaled.index < end)]
    payload = {
        "version": "V4.2-execution-rebate30",
        "data": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "market_source": "Binance USD-M 4h archive",
            "intrabar_source": "Binance USD-M 1m archive",
            "funding_source": "Binance USD-M funding archive",
        },
        "strategy": params.to_dict(),
        "capital_overlay": {
            "parameters": neutral_capital.to_dict(),
            "neutral_metrics": neutral_metrics(neutral),
        },
        "execution": {
            "base_taker_fee_bps": args.taker_fee_bps,
            "base_maker_fee_bps": args.maker_fee_bps,
            "fee_rebate_rate": args.fee_rebate_rate,
            "effective_taker_fee_bps": effective_taker,
            "effective_maker_fee_bps": effective_maker,
            "maker_offset_bps": maker_offset,
            "maker_order_timeout_minutes": maker_timeout,
            "maker_exit_enabled": False,
            "base_slippage_bps": 1.0,
            "impact_bps": 8.0,
            "max_minute_participation": 0.02,
        },
        "signal_diagnostics": {
            "downside_trigger_count": int(requested_signaled["v43_downside_trigger"].sum()),
            "fast_downside_exit_count": int(
                (requested_signaled["v43_stop_reason"] == "fast_downside_stop").sum()
            ),
            "protective_exit_count": int(
                (requested_signaled["v43_stop_reason"] == "protective_exit").sum()
            ),
        },
        "direction": {
            "maker": {
                "metrics": maker_direction.metrics,
                "periods": micro_period_metrics(maker_direction),
            },
            "same_signal_taker": {
                "metrics": taker_direction.metrics,
                "periods": micro_period_metrics(taker_direction),
            },
            "legacy_v42_same_window": {
                "parameters": legacy_params.to_dict(),
                "metrics": legacy_direction.metrics,
                "periods": micro_period_metrics(legacy_direction),
            },
        },
        "combined": {
            "maker": {
                "metrics": maker_combined_metrics,
                "periods": portfolio_period_metrics(maker_combined),
            },
            "same_signal_taker": {
                "metrics": taker_combined_metrics,
                "periods": portfolio_period_metrics(taker_combined),
            },
            "legacy_v42_same_window": {
                "metrics": legacy_combined_metrics,
                "periods": portfolio_period_metrics(legacy_combined),
            },
        },
        "method": {
            "maker": "routine direction exposure changes use post-only limits; risk exits remain taker",
            "risk": "V4.3 causal ATR stop, trailing stop, take-profit and fast downside flattening",
            "neutral": "V4.2 settled-funding sleeve with rebate-adjusted spot/futures transition fees",
            "causality": "completed 4h signals apply at the next boundary; full funding history supplies warm-up",
            "limitations": [
                "historical order-book queue and maker fill probability are unavailable",
                "OHLC touch is a deterministic maker-fill proxy",
                "neutral sleeve excludes spot-perpetual basis PnL and spot order-book depth",
            ],
            "original_v42_report_unchanged": "reports/v4_2_2020_2026_08_25/report.json",
        },
    }
    (output / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=float) + "\n",
        encoding="utf-8",
    )
    (output / "micro_metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=float) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "combined_maker": maker_combined_metrics,
                "combined_same_signal_taker": taker_combined_metrics,
                "combined_legacy_v42": legacy_combined_metrics,
            },
            ensure_ascii=False,
            indent=2,
            default=float,
        )
    )


if __name__ == "__main__":
    main()
