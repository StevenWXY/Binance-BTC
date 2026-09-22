"""Evaluate the V4.5.3 Maker execution refinement and fixed controls."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from itertools import chain
import json
from pathlib import Path

import pandas as pd

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v441_research import metrics
from evaluate_v441 import minute_batches
from evaluate_v444 import inputs, window_metrics
from research_v452 import profile_signal


ROOT = Path("reports/v4_5_3")
ITEM = {"id": "b022", "kind": "v452", "params": json.loads(Path("configs/v4_5_3_params.json").read_text())["signal_params"]}
CONTROL = {"id": "V4.5.2", "kind": "v452", "params": ITEM["params"]}
WINDOWS = {"full": ("2020-01-01", "2026-09-01"), "recent": ("2024-01-01", "2026-09-01"),
           "recent_jul": ("2024-01-01", "2026-08-01"), "later": ("2026-01-15", "2026-09-01")}


def frequency(result, start, end):
    t = result.trades
    a, b = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    t = t.loc[(t.exit_time >= a) & (t.exit_time < b)] if len(t) else t
    years = (b - a).total_seconds() / (365.25 * 86400)
    return {"cycles": int(len(t)), "cycles_per_year": float(len(t) / years),
            "short_cycles": int((t.side == "short").sum()) if len(t) else 0,
            "long_cycles": int((t.side == "long").sum()) if len(t) else 0,
            "median_holding_hours": float(((t.exit_time - t.entry_time).dt.total_seconds() / 3600).median()) if len(t) else 0.}


def run_case(job):
    name, stress = job
    data, funding, extension = inputs()
    item = ITEM
    signal = profile_signal(data, item)
    cfg = MicroBacktestConfig(signal_interval_minutes=60, equity_interval_minutes=60,
                              periods_per_year=8760, conservative_protection=True,
                              taker_fee_bps=2.4, base_slippage_bps=1, impact_bps=8,
                              maker_enabled=name == "V4.5.3", maker_fee_bps=.12,
                              maker_offset_bps=0.0, maker_order_timeout_minutes=60,
                              maker_exit_enabled=False)
    if stress == "offset025":
        cfg = replace(cfg, maker_offset_bps=.25)
    elif stress == "offset05":
        cfg = replace(cfg, maker_offset_bps=.5)
    elif stress == "double_cost":
        cfg = replace(cfg, taker_fee_bps=4.8, maker_fee_bps=.24, base_slippage_bps=3, impact_bps=16)
    elif stress == "no_rebate":
        cfg = replace(cfg, taker_fee_bps=4., maker_fee_bps=.2)
    elif stress == "delay_1h":
        signal = signal.copy()
        signal.index += pd.Timedelta(hours=1)
    batches = chain(minute_batches(Path("data/v441"), "2020-01-01", "2026-08-01"), [extension])
    result = run_micro_backtest(signal, batches, funding, cfg)
    windows = {}
    for key, (start, end) in WINDOWS.items():
        windows[key] = {"metrics": window_metrics(result.equity, result.trades, start, end),
                        "frequency": frequency(result, start, end)}
    row = {"strategy": name, "stress": stress, "metrics": metrics(result.equity, result.trades),
           "windows": windows, "execution": asdict(cfg), "execution_metrics": result.metrics}
    dest = ROOT / f"{name}__{stress}"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "report.json").write_text(json.dumps(row, indent=2) + "\n")
    result.trades.to_csv(dest / "trades.csv", index=False)
    result.fills.to_csv(dest / "fills.csv", index=False)
    print(name, stress, windows["recent"]["metrics"], result.metrics, flush=True)
    return row


def main():
    jobs = [("V4.5.2", "base"), ("V4.5.3", "base"),
            ("V4.5.3", "offset025"), ("V4.5.3", "offset05"),
            ("V4.5.3", "double_cost"), ("V4.5.3", "no_rebate"), ("V4.5.3", "delay_1h")]
    with ProcessPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(run_case, jobs))
    (ROOT / "evaluation.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
