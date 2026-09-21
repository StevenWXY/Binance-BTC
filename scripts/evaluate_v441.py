"""Frozen V4.4.1 minute audit. This script never selects or modifies parameters."""
from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.strategy import StrategyParams, generate_signals
from btc_regime.v413 import V413Params, generate_v413_signals
from btc_regime.v441 import V441Params, core_signals, generate_v441_signals
from btc_regime.v441_research import PERIODS, metrics, paired_block_bootstrap


def minute_batches(cache, start, end):
    first, last = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    for month in pd.period_range(first.tz_localize(None).to_period("M"),
                                 (last - pd.Timedelta(minutes=1)).tz_localize(None).to_period("M"), freq="M"):
        data = pd.read_pickle(cache / "minutes" / f"{month}.pkl")
        yield data.loc[(data.index >= first) & (data.index < last)]


def build_signals(data, params, case, start):
    if case.startswith("V441"):
        if case == "V441_short":
            params = replace(params, short_enabled=True)
        if case == "V441_tactical_only":
            params = replace(params, core_scale=0, satellite_scale=1)
        s = generate_v441_signals(data, params, trade_start=start)
        if case == "V441_core_only":
            flat = s.v441_source.ne("core")
            s.loc[flat, "signal"] = 0.
            s.loc[flat, ["stop_price", "take_profit_price"]] = np.nan
        return s, 60
    core = core_signals(data)
    if case == "V4_1_3":
        p = V413Params.from_dict(json.loads(Path("configs/v4_1_3_params.json").read_text()))
        return generate_v413_signals(core, p), 240
    if case == "V4":
        p = StrategyParams(**json.loads(Path("configs/aggressive_adaptive_v3_params.json").read_text()))
        s = generate_signals(core, p)
        side = np.sign(s.signal)
        s["cycle_id"] = "v4_" + (side.ne(0) & side.ne(side.shift(fill_value=0))).cumsum().astype(str)
        # generate_signals preserves input columns; V4 has no protective levels.
        s = s.drop(columns=["stop_price", "take_profit_price"], errors="ignore")
        return s, 240
    return core, 240


def run_case(job):
    case, period, stress, cache, output, raw_params = job
    start, end = PERIODS[period]
    params = V441Params(**raw_params)
    data = pd.read_pickle(cache / "hourly.pkl")
    data = data.loc[data.index < pd.Timestamp(end, tz="UTC")]
    funding = pd.read_pickle(cache / "funding.pkl")
    signals, interval = build_signals(data, params, case, start)
    config = MicroBacktestConfig(signal_interval_minutes=interval, equity_interval_minutes=60,
                                 periods_per_year=8760, conservative_protection=True,
                                 taker_fee_bps=4, base_slippage_bps=1, impact_bps=8)
    if stress == "double_cost":
        config = replace(config, taker_fee_bps=8, base_slippage_bps=3, impact_bps=16)
    elif stress == "delay_1h":
        signals = signals.copy()
        signals.index += pd.Timedelta(hours=1)
    signals = signals.loc[signals.index >= pd.Timestamp(start, tz="UTC") - pd.Timedelta(minutes=interval)]
    result = run_micro_backtest(signals, minute_batches(cache, start, end), funding, config)
    label = f"{case}__{period}__{stress}"
    dest = output / label
    dest.mkdir(parents=True, exist_ok=True)
    result.equity.to_csv(dest / "equity.csv")
    result.fills.to_csv(dest / "fills.csv", index=False)
    result.trades.to_csv(dest / "trades.csv", index=False)
    result.funding.to_csv(dest / "funding.csv", index=False)
    result.liquidations.to_csv(dest / "liquidations.csv", index=False)
    summary = {"case": case, "period": period, "stress": stress, "start": start, "end_exclusive": end,
               **metrics(result.equity, result.trades), "execution": asdict(config),
               "execution_metrics": result.metrics}
    if "v441_source" in signals and len(result.trades):
        available = signals.v441_source.copy()
        available.index += pd.Timedelta(minutes=interval)
        trades = result.trades.copy()
        trades["source"] = available.reindex(pd.DatetimeIndex(trades.entry_time), method="ffill").to_numpy()
        summary["attribution"] = {source: {"cycles": len(t), "sum_cycle_return": float((t.pnl / t.equity_before).sum()),
                                             "pnl_usdt": float(t.pnl.sum())} for source, t in trades.groupby("source")}
        trades.to_csv(dest / "trades.csv", index=False)
    yearly = {}
    for year in sorted(set(result.equity.index.year)):
        a, b = pd.Timestamp(f"{year}-01-01", tz="UTC"), pd.Timestamp(f"{year+1}-01-01", tz="UTC")
        e = result.equity.loc[(result.equity.index >= a) & (result.equity.index <= b)]
        if len(e) > 24:
            t = result.trades.loc[(result.trades.entry_time >= a) & (result.trades.entry_time < b)]
            yearly[str(year)] = metrics(e, t)
    summary["yearly"] = yearly
    (dest / "metrics.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(label, "return", round(summary["total_return"], 3), "Sharpe", round(summary["sharpe"], 3),
          "DD", round(summary["max_drawdown"], 3), "cycles", summary["cycles"], flush=True)
    return label, summary


def read_equity(path):
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame.iloc[:, 0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("data/v441"))
    parser.add_argument("--output", type=Path, default=Path("reports/v4_4_1"))
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    lock = json.loads((args.output / "final_selection_lock.json").read_text())
    for filename, digest in lock["source_sha256"].items():
        if hashlib.sha256(Path(filename).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Frozen source has changed: {filename}")
    params = json.loads(Path("configs/v4_4_1_params.json").read_text())
    if params != lock["params"]:
        raise ValueError("Parameters differ from development selection lock")
    jobs = [(c, p, "base", args.cache, args.output, params)
            for p in ["post2024", "holdout"]
            for c in ["V441", "V4", "V4_1_2", "V4_1_3", "V441_core_only", "V441_short", "V441_tactical_only"]]
    jobs += [(c, "holdout", stress, args.cache, args.output, params)
             for c in ["V441", "V4_1_2"] for stress in ["double_cost", "delay_1h"]]
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        cases = dict(executor.map(run_case, jobs))
    boot = {}
    for period in ["post2024", "holdout"]:
        selected = read_equity(args.output / f"V441__{period}__base/equity.csv")
        for baseline in ["V4", "V4_1_2", "V4_1_3", "V441_core_only"]:
            original = read_equity(args.output / f"{baseline}__{period}__base/equity.csv")
            boot[f"{period}_vs_{baseline}"] = paired_block_bootstrap(selected, original)
    report = {"version": "V4.4.1", "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
              "selection_lock": lock, "params": params, "cases": cases, "bootstrap": boot,
              "cost_policy": "All taker, no rebate: 4bps + 1bps base slippage + 8bps*sqrt(participation).",
              "sharpe_policy": "Daily UTC equity returns, sqrt(365.25), zero risk-free rate.",
              "holdout_disclosure": "Frozen within this search; 2025-2026 was seen by earlier repository research.",
              "data_audit": json.loads((args.output / "data_audit.json").read_text())}
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    pd.DataFrame([{k: v for k, v in row.items() if not isinstance(v, dict)} for row in cases.values()]).to_csv(
        args.output / "summary.csv", index=False)


if __name__ == "__main__":
    main()
