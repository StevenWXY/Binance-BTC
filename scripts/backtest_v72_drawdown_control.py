#!/usr/bin/env python3
"""Backtest WZY V7.2 with global liquidity and optional drawdown control."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.data import load_ohlc_archive_bytes  # noqa: E402
from btc_regime.micro_backtest import MicroBacktestConfig, micro_period_metrics, run_micro_backtest  # noqa: E402
from btc_regime.v71_live import V71LiveParams, generate_v71_live_signals  # noqa: E402
from compare_v4_v7_micro_local import iter_local_batches, load_local_market  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--source-zip", type=Path, default=Path(r"D:\文档\桌面\data.zip"))
    parser.add_argument("--params", type=Path, default=ROOT / "configs/wzy_v72_tp_refined_params.json")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/v72_drawdown_control_2020_2026_08_01")
    args = parser.parse_args()

    market = load_local_market(args.raw_dir, args.start, args.end, args.source_zip)
    with __import__('zipfile').ZipFile(args.source_zip) as source:
        funding_parts = []
        for name in source.namelist():
            if not name.startswith('data/raw/funding/') or not name.endswith('.zip'):
                continue
            with __import__('zipfile').ZipFile(__import__('io').BytesIO(source.read(name))) as nested:
                payload = nested.read(nested.namelist()[0])
            frame = pd.read_csv(__import__('io').BytesIO(payload))
            frame['timestamp'] = pd.to_datetime(frame['calc_time'], unit='ms', utc=True)
            frame['funding_rate'] = pd.to_numeric(frame['last_funding_rate'], errors='coerce')
            funding_parts.append(frame.set_index('timestamp')[['funding_rate']])
    funding = pd.concat(funding_parts).sort_index()
    funding = funding.loc[(funding.index >= pd.Timestamp(args.start, tz='UTC')) & (funding.index < pd.Timestamp(args.end, tz='UTC'))]
    params = V71LiveParams(**json.loads(args.params.read_text(encoding="utf-8")))
    signals = generate_v71_live_signals(market, params)
    signals = signals.loc[signals.index < pd.Timestamp(args.end, tz="UTC")]

    common = dict(
        initial_cash=10_000.0,
        taker_fee_bps=4.0,
        base_slippage_bps=1.0,
        impact_bps=8.0,
        max_minute_participation=0.02,
        liquidation_fee_bps=50.0,
    )
    controls = {
        "v72_no_drawdown_control": dict(strategy_drawdown_enabled=False),
        "v72_drawdown_control": dict(
            strategy_drawdown_enabled=True,
            strategy_drawdown_level_1=0.08,
            strategy_drawdown_scale_1=0.80,
            strategy_drawdown_level_2=0.12,
            strategy_drawdown_scale_2=0.50,
            strategy_drawdown_level_3=0.16,
            strategy_drawdown_scale_3=0.0,
        ),
    }
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    curves = []
    report = {
        "data": {"source": str(args.raw_dir), "start": args.start, "end": args.end},
        "strategy": {"name": "wzy V7.2 TP refined", "params_file": str(args.params), "params": params.to_dict()},
        "global_execution": common,
        "runs": {},
    }
    for code, control in controls.items():
        config = MicroBacktestConfig(**common, **control)
        # Stream one run at a time; the full 1m archive is too large to retain twice.
        # The supplied archive's 1m members are wrapped when extracted; use the
        # repository's readable plain_raw cache for minute execution. The 4h
        # signal/funding data above still comes directly from source_zip.
        if args.source_zip.exists():
            batches = iter_local_batches(args.raw_dir, args.start, args.end, args.source_zip)
        else:
            batch_raw_dir = args.raw_dir
            if list((ROOT / "data/friend_clean/raw/klines").glob("BTCUSDT-1m-*.zip")):
                batch_raw_dir = ROOT / "data/friend_clean/raw"
            batches = iter_local_batches(batch_raw_dir, args.start, args.end, None)
        result = run_micro_backtest(signals, batches, funding, config)
        metrics = result.metrics
        row = {
            "run": code,
            "drawdown_control": config.strategy_drawdown_enabled,
            "final_equity": metrics["final_equity"],
            "total_return": metrics["total_return"],
            "cagr": metrics["cagr"],
            "annualized_volatility": metrics["annualized_volatility"],
            "sharpe": metrics["sharpe"],
            "sortino": metrics["sortino"],
            "calmar": metrics.get("calmar", float("nan")),
            "max_drawdown": metrics["max_drawdown"],
            "fees_paid": metrics["fees_paid"],
            "funding_paid": metrics["funding_paid"],
            "max_leverage_observed": metrics.get("max_leverage_observed", 0.0),
            "max_participation_observed": metrics.get("max_minute_participation_observed", 0.0),
            "liquidation_count": metrics["liquidation_count"],
        }
        rows.append(row)
        curves.append(result.equity.rename(code))
        report["runs"][code] = {"execution": asdict(config), "metrics": metrics, "periods": micro_period_metrics(result)}

    summary = pd.DataFrame(rows)
    summary.to_csv(output / "summary_metrics.csv", index=False)
    pd.concat(curves, axis=1).to_csv(output / "equity_curves.csv")
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
