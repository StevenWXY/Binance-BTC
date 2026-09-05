#!/usr/bin/env python3
"""Full minute backtest for V7.1.3 with the V4.2.1 neutral sleeve."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from btc_regime.backtest import calculate_metrics  # noqa: E402
from btc_regime.data import load_funding, load_market_data  # noqa: E402
from btc_regime.micro_backtest import (  # noqa: E402
    MicroBacktestConfig,
    micro_period_metrics,
    run_micro_backtest,
    write_micro_report,
)
from btc_regime.v42 import (  # noqa: E402
    V42CapitalParams,
    combine_direction_and_neutral,
    generate_neutral_sleeve,
    neutral_metrics,
)
from btc_regime.v712 import V712Params, generate_v712_signals  # noqa: E402
from btc_regime.v713 import V713Params, generate_v713_signals  # noqa: E402
from backtest_v712 import iter_local_batches  # noqa: E402

PERIODS = {
    "train_2020_2022": ("2020-01-01", "2023-01-01"),
    "validation_2023_2024": ("2023-01-01", "2025-01-01"),
    "holdout_2025_2026_07": ("2025-01-01", "2026-08-01"),
    "full_2020_2026_07": ("2020-01-01", "2026-08-01"),
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2020-01-01")
    p.add_argument("--end", default="2026-08-01")
    p.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    p.add_argument("--v712-params", type=Path, default=ROOT / "configs/v712_params.json")
    p.add_argument("--v713-params", type=Path, default=ROOT / "configs/v713_params.json")
    p.add_argument("--capital-params", type=Path, default=ROOT / "configs/v713_capital_params.json")
    p.add_argument("--execution", type=Path, default=ROOT / "configs/v713_execution.json")
    p.add_argument("--output", type=Path, default=ROOT / "reports/v713_micro_2020_2026_07")
    return p.parse_args()


def config_from(execution: dict[str, object], maker: bool) -> MicroBacktestConfig:
    rebate = float(execution.get("fee_rebate_rate", 0.30))
    return MicroBacktestConfig(
        initial_cash=float(execution.get("initial_cash", 10_000.0)),
        taker_fee_bps=float(execution.get("base_taker_fee_bps", 4.0)) * (1 - rebate),
        maker_fee_bps=float(execution.get("base_maker_fee_bps", 0.2)) * (1 - rebate),
        maker_enabled=maker,
        maker_offset_bps=float(execution.get("maker_offset_bps", 0.0)),
        maker_order_timeout_minutes=int(execution.get("maker_order_timeout_minutes", 60)),
        maker_exit_enabled=bool(execution.get("maker_exit_enabled", False)),
        base_slippage_bps=float(execution.get("base_slippage_bps", 1.0)),
        impact_bps=float(execution.get("impact_bps", 8.0)),
        max_minute_participation=float(execution.get("max_minute_participation", 0.02)),
        liquidation_fee_bps=float(execution.get("liquidation_fee_bps", 50.0)),
        strategy_drawdown_enabled=bool(execution.get("strategy_drawdown_enabled", True)),
        strategy_drawdown_level_1=float(execution.get("strategy_drawdown_level_1", 0.20)),
        strategy_drawdown_scale_1=float(execution.get("strategy_drawdown_scale_1", 0.95)),
        strategy_drawdown_level_2=float(execution.get("strategy_drawdown_level_2", 0.30)),
        strategy_drawdown_scale_2=float(execution.get("strategy_drawdown_scale_2", 0.85)),
        strategy_drawdown_level_3=float(execution.get("strategy_drawdown_level_3", 0.40)),
        strategy_drawdown_scale_3=float(execution.get("strategy_drawdown_scale_3", 0.70)),
    )


def period_metrics(equity: pd.Series) -> dict[str, dict[str, float]]:
    output = {}
    for label, (start, end) in PERIODS.items():
        start_ts = pd.Timestamp(start, tz="UTC")
        end_ts = pd.Timestamp(end, tz="UTC")
        window = equity.loc[(equity.index >= start_ts) & (equity.index <= end_ts)]
        if not window.empty:
            output[label] = calculate_metrics(window, window.pct_change().dropna(), pd.DataFrame(), 2190)
    return output


def run_one(signals, args, funding, execution, maker):
    config = config_from(execution, maker)
    result = run_micro_backtest(
        signals,
        iter_local_batches(args.raw_dir, args.start, args.end),
        funding,
        config,
    )
    return result, config


def main():
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    execution = json.loads(args.execution.read_text(encoding="utf-8"))
    # Load enough history for indicators and for the neutral sleeve's 30-day warm-up.
    market = load_market_data(args.raw_dir, start="2020-01-01", end=args.end, interval="4h")
    funding = load_funding(args.raw_dir, start="2020-01-01", end=args.end)
    reports = {
        "version": "V7.1.3-with-V4.2.1-neutral",
        "data": {"start": args.start, "end": args.end, "raw_dir": str(args.raw_dir)},
        "execution": execution,
        "strategies": {},
        "combined": {},
    }

    # Keep V7.1.2 as a direction-only reference for the same execution model.
    v712 = V712Params(**json.loads(args.v712_params.read_text(encoding="utf-8-sig")))
    s712 = generate_v712_signals(market, v712)
    r712, c712 = run_one(s712, args, funding, execution, True)
    write_micro_report(r712, v712, c712, args.output / "v7.1.2_maker_rebate30")
    reports["strategies"]["V7.1.2_maker_rebate30"] = {
        "metrics": r712.metrics,
        "periods": micro_period_metrics(r712),
    }
    print("V7.1.2 maker", r712.metrics, flush=True)

    v713 = V713Params(**json.loads(args.v713_params.read_text(encoding="utf-8-sig")))
    s713 = generate_v713_signals(market, v713)
    direction_results = {}
    for label, maker in (("V7.1.3_maker_rebate30", True), ("V7.1.3_taker_rebate30", False)):
        result, config = run_one(s713, args, funding, execution, maker)
        write_micro_report(result, v713, config, args.output / label.lower())
        reports["strategies"][label] = {
            "metrics": result.metrics,
            "periods": micro_period_metrics(result),
        }
        direction_results[label] = result
        print(label, result.metrics, flush=True)

    # Exact V4.2.1 neutral sleeve, with the same 30% trading-fee rebate.
    capital = V42CapitalParams(**json.loads(args.capital_params.read_text(encoding="utf-8")))
    rebate = float(execution.get("fee_rebate_rate", 0.30))
    capital = replace(
        capital,
        spot_fee_bps=capital.spot_fee_bps * (1.0 - rebate),
        futures_fee_bps=capital.futures_fee_bps * (1.0 - rebate),
    )
    neutral = generate_neutral_sleeve(funding, capital)
    neutral.to_csv(args.output / "neutral_schedule.csv")
    reports["neutral"] = {"parameters": capital.to_dict(), "metrics": neutral_metrics(neutral)}

    effective_signal = s713["signal"].copy()
    effective_signal.index = effective_signal.index + pd.Timedelta(hours=4)
    for label, result in direction_results.items():
        combined, combined_metrics = combine_direction_and_neutral(
            result.equity, neutral, capital, effective_signal
        )
        combined.to_csv(args.output / (label.lower() + "_combined_equity.csv"))
        reports["combined"][label] = {
            "metrics": combined_metrics,
            "periods": period_metrics(combined["combined_equity"]),
        }
        print(label + " + neutral", combined_metrics, flush=True)

    (args.output / "report.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2, default=float) + "\n",
        encoding="utf-8",
    )
    rows = [{"strategy": n, **x["metrics"]} for n, x in reports["strategies"].items()]
    rows += [{"strategy": n + "_combined_neutral", **x["metrics"]} for n, x in reports["combined"].items()]
    table = pd.DataFrame(rows)
    table.to_csv(args.output / "summary_metrics.csv", index=False)
    print(table.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
