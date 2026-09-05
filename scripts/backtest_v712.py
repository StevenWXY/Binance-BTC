#!/usr/bin/env python3
"""Run the V7.1/V7.1.2 minute execution comparison.

V7.1.2 keeps V7.1's regime classifier and drawdown sizing overlay, adds causal
ATR protection, and compares post-only maker execution (30% fee rebate) with
the same signal executed as taker.  Protective exits and liquidation remain
taker orders.
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
sys.path.insert(0, str(ROOT / "scripts"))

from btc_regime.data import load_funding, load_market_data, load_ohlc_archive  # noqa: E402
from btc_regime.micro_backtest import (  # noqa: E402
    MicroBacktestConfig,
    micro_period_metrics,
    run_micro_backtest,
    write_micro_report,
)
from btc_regime.v7 import V7Params, generate_v7_signals  # noqa: E402
from btc_regime.v712 import V712Params, generate_v712_signals  # noqa: E402


def iter_local_batches(raw_dir: Path, start: str, end: str):
    raw_path = raw_dir
    prefix = "BTCUSDT-1m-"
    trade_files = {path.stem.removeprefix(prefix): path for path in raw_path.joinpath("klines").glob(f"{prefix}*.zip")}
    mark_files = {path.stem.removeprefix(prefix): path for path in raw_path.joinpath("mark_price").glob(f"{prefix}*.zip")}
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    for period in sorted(set(trade_files) & set(mark_files)):
        if not period[:4].isdigit() or len(period) != 7:
            continue
        try:
            trade = load_ohlc_archive(trade_files[period]).add_prefix("trade_")
            mark = load_ohlc_archive(mark_files[period])[["open", "high", "low", "close"]].add_prefix("mark_")
        except (OSError, ValueError, EOFError) as exc:
            print(f"Skipping unreadable local archive {period}: {exc}", flush=True)
            continue
        batch = trade.join(mark, how="inner")
        batch = batch.loc[(batch.index >= start_ts) & (batch.index < end_ts)]
        if not batch.empty:
            yield batch


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2020-01-01")
    p.add_argument("--end", default="2026-08-01")
    p.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    p.add_argument("--v71-params", type=Path, default=ROOT / "configs/v71_params.json")
    p.add_argument("--v712-params", type=Path, default=ROOT / "configs/v712_params.json")
    p.add_argument("--execution", type=Path, default=ROOT / "configs/v712_execution.json")
    p.add_argument("--output", type=Path, default=ROOT / "reports/v712_micro_2020_2026_07")
    p.add_argument("--fee-rebate-rate", type=float, default=None)
    p.add_argument("--skip-v71", action="store_true")
    return p.parse_args()


def _config(execution: dict[str, object], *, maker: bool, rebate: float, taker_fee: float = 4.0) -> MicroBacktestConfig:
    return MicroBacktestConfig(
        initial_cash=float(execution.get("initial_cash", 10_000.0)),
        taker_fee_bps=taker_fee * (1.0 - rebate),
        maker_fee_bps=float(execution.get("base_maker_fee_bps", 0.2)) * (1.0 - rebate),
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


def _run(signals: pd.DataFrame, args: argparse.Namespace, funding: pd.DataFrame, execution: dict[str, object], *, maker: bool, rebate: float):
    config = _config(execution, maker=maker, rebate=rebate)
    batches = iter_local_batches(args.raw_dir, args.start, args.end)
    result = run_micro_backtest(signals, batches, funding, config)
    return result, config


def _signal_diagnostics(signals: pd.DataFrame) -> dict[str, object]:
    out: dict[str, object] = {}
    for col in ["v7_market_state", "regime", "v7_speed_mode", "v712_stop_reason"]:
        if col in signals:
            out[col] = {str(k): int(v) for k, v in signals[col].value_counts(dropna=False).items()}
    for col in ["v712_downside_trigger"]:
        if col in signals:
            out[col] = int(signals[col].sum())
    return out


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    execution = json.loads(args.execution.read_text(encoding="utf-8"))
    rebate = float(execution.get("fee_rebate_rate", 0.30) if args.fee_rebate_rate is None else args.fee_rebate_rate)
    if not 0 <= rebate < 1:
        raise SystemExit("fee rebate rate must be in [0, 1)")

    market = load_market_data(args.raw_dir, start="2020-01-01", end=args.end, interval="4h")
    funding = load_funding(args.raw_dir, start=args.start, end=args.end)

    reports: dict[str, object] = {
        "version": "V7.1.2",
        "data": {"start": args.start, "end": args.end, "raw_dir": str(args.raw_dir)},
        "execution": {**execution, "effective_taker_fee_bps": 4.0 * (1.0 - rebate), "effective_maker_fee_bps": float(execution.get("base_maker_fee_bps", 0.2)) * (1.0 - rebate)},
        "strategies": {},
    }

    if not args.skip_v71:
        v71_values = json.loads(args.v71_params.read_text(encoding="utf-8-sig"))
        v71_params = V7Params(**v71_values)
        v71_signals = generate_v7_signals(market, v71_params)
        result, config = _run(v71_signals, args, funding, execution, maker=False, rebate=0.0)
        directory = args.output / "v71_taker_no_rebate"
        write_micro_report(result, v71_params, config, directory)
        reports["strategies"]["V7.1_taker_no_rebate"] = {
            "metrics": result.metrics,
            "periods": micro_period_metrics(result),
            "signal_diagnostics": _signal_diagnostics(v71_signals),
        }
        print("V7.1 baseline", result.metrics, flush=True)

    v712_values = json.loads(args.v712_params.read_text(encoding="utf-8-sig"))
    v712_params = V712Params(**v712_values)
    v712_signals = generate_v712_signals(market, v712_params)
    for label, maker in (("V7.1.2_maker_rebate30", True), ("V7.1.2_taker_rebate30", False)):
        result, config = _run(v712_signals, args, funding, execution, maker=maker, rebate=rebate)
        directory = args.output / label.lower()
        write_micro_report(result, v712_params, config, directory)
        reports["strategies"][label] = {
            "metrics": result.metrics,
            "periods": micro_period_metrics(result),
            "signal_diagnostics": _signal_diagnostics(v712_signals),
        }
        print(label, result.metrics, flush=True)

    (args.output / "report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2, default=float) + "\n", encoding="utf-8")
    table = []
    for name, payload in reports["strategies"].items():
        table.append({"strategy": name, **payload["metrics"]})
    pd.DataFrame(table).to_csv(args.output / "summary_metrics.csv", index=False)
    print(pd.DataFrame(table).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
