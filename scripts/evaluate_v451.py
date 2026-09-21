"""Freeze V4.5.1 on development data, then audit later data without retuning."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timezone
from itertools import chain
import json
from pathlib import Path

import pandas as pd

from btc_regime.micro_backtest import run_micro_backtest
from btc_regime.v441_research import metrics
from btc_regime.v443 import V443Params, generate_v443_signals
from btc_regime.v451 import V451Params, generate_v451_signals
from evaluate_v441 import minute_batches
from evaluate_v444 import file_hash, inputs, window_metrics
from research_v451 import ROOT, baseline_profile, config, short_stats

WINDOWS = {"full": ("2020-01-01", "2026-09-01"),
           "legacy": ("2020-01-01", "2024-01-01"),
           "recent": ("2024-01-01", "2026-09-01"),
           "recent_jul": ("2024-01-01", "2026-08-01"),
           "post_freeze_audit": ("2025-07-15", "2026-09-01")}


def validate_lock():
    lock = json.loads((ROOT / "selection_lock.json").read_text())
    for name, expected in lock["source_sha256"].items():
        if file_hash(name) != expected:
            raise ValueError(f"Frozen source/input changed: {name}")
    selected = json.loads(Path("configs/v4_5_1_params.json").read_text())
    if selected["short_params"] != lock["profile"]["params"]:
        raise ValueError("Frozen short parameters changed")
    return lock


def freeze():
    if (ROOT / "selection_lock.json").exists():
        return validate_lock()
    rows = json.loads((ROOT / "minute_selection.json").read_text())
    eligible = [r for r in rows[1:] if r["eligible"]]
    chosen = max(eligible or rows[1:], key=lambda r: r["score"])
    profile = chosen["profile"]
    baseline = json.loads(Path("configs/v4_4_4_params.json").read_text())
    cfg = {"version": "V4.5.1", "id": profile["id"], "long_version": "V4.4.4",
           "long_params": baseline["params"], "short_params": profile["params"], "fee": baseline["fee"]}
    Path("configs/v4_5_1_params.json").write_text(json.dumps(cfg, indent=2) + "\n")
    files = [str(p) for p in Path("src/btc_regime").glob("*.py")]
    files += ["scripts/research_v451.py", "scripts/evaluate_v451.py", "scripts/evaluate_v444.py",
              "scripts/evaluate_v441.py", "scripts/evaluate_v441_round2.py",
              "reports/v4_5_1/protocol.json", "reports/v4_5_1/screen.json", "reports/v4_5_1/minute_selection.json",
              "configs/v4_4_4_params.json", "configs/v4_4_3_params.json",
              "data/v441/hourly.pkl", "data/v441/funding.pkl", "data/v441/round2/extension_minutes.pkl",
              "data/raw/funding/BTCUSDT-fundingRate-2026-08.zip"]
    files += [str(p) for p in sorted(Path("data/v441/minutes").glob("*.pkl"))]
    lock = {"version": "V4.5.1", "profile": profile, "score": chosen["score"],
            "development_eligible": bool(eligible), "selection_data_end_exclusive": "2025-07-01",
            "frozen_at_utc": datetime.now(timezone.utc).isoformat(), "blind_holdout": False,
            "source_sha256": {p: file_hash(p) for p in files}}
    (ROOT / "selection_lock.json").write_text(json.dumps(lock, indent=2) + "\n")
    print("FROZEN", profile, "development_eligible", bool(eligible), flush=True)
    return lock


def run_case(job):
    profile, stress, start, end, group = job
    data, funding, extension = inputs()
    data = data.loc[data.index < pd.Timestamp(end, tz="UTC")]
    if profile["id"] == "V443":
        signal = generate_v443_signals(data, V443Params(**profile["params"]))
    else:
        signal = generate_v451_signals(data, V451Params(**profile["params"]))
    if stress == "short_only":
        signal.loc[signal.signal.ge(0), "signal"] = 0.
        signal.loc[signal.signal.eq(0), ["stop_price", "take_profit_price"]] = float("nan")
    cfg = config(True)
    if stress == "double_cost":
        cfg = replace(cfg, taker_fee_bps=4.8, base_slippage_bps=3, impact_bps=16)
    elif stress == "no_rebate":
        cfg = replace(cfg, taker_fee_bps=4.)
    elif stress == "delay_1h":
        signal.index += pd.Timedelta(hours=1)
    signal = signal.loc[signal.index >= pd.Timestamp(start, tz="UTC") - pd.Timedelta(hours=1)]
    cached_end = min(pd.Timestamp(end), pd.Timestamp("2026-08-01")).strftime("%Y-%m-%d")
    prior = minute_batches(Path("data/v441"), start, cached_end) if pd.Timestamp(start) < pd.Timestamp(cached_end) else []
    extension = extension.loc[(extension.index >= pd.Timestamp(start, tz="UTC")) &
                              (extension.index < pd.Timestamp(end, tz="UTC"))]
    result = run_micro_backtest(signal, chain(prior, [extension]), funding, cfg)
    windows, shorts, yearly = {}, {}, {}
    for key, (a, b) in WINDOWS.items():
        if pd.Timestamp(a) < pd.Timestamp(start) or pd.Timestamp(b) > pd.Timestamp(end):
            continue
        windows[key] = window_metrics(result.equity, result.trades, a, b)
        t = result.trades
        t = t.loc[(t.exit_time >= pd.Timestamp(a, tz="UTC")) & (t.exit_time < pd.Timestamp(b, tz="UTC"))] if len(t) else t
        shorts[key] = short_stats(t)
    for year in range(pd.Timestamp(start).year, pd.Timestamp(end).year + 1):
        a = max(pd.Timestamp(start), pd.Timestamp(f"{year}-01-01"))
        b = min(pd.Timestamp(end), pd.Timestamp(f"{year+1}-01-01"))
        if b > a:
            yearly[str(year)] = window_metrics(result.equity, result.trades, str(a), str(b))
    row = {"profile": profile, "stress": stress, "window": [start, end],
           "metrics": metrics(result.equity, result.trades), "windows": windows,
           "yearly": yearly, "shorts": shorts, "execution": asdict(cfg), "execution_metrics": result.metrics}
    dest = ROOT / group / f"{profile['id']}__{stress}"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ["equity", "trades", "fills", "funding", "liquidations"]:
        getattr(result, name).to_csv(dest / f"{name}.csv", index=name == "equity")
    (dest / "report.json").write_text(json.dumps(row, indent=2) + "\n")
    print(group, profile["id"], stress, "metrics", row["metrics"], "recent", windows.get("recent"), flush=True)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["freeze", "audit", "stress"])
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze()
        return
    profile = validate_lock()["profile"]
    baseline = baseline_profile()
    if args.phase == "audit":
        v443 = {"id": "V443", "params": json.loads(Path("configs/v4_4_3_params.json").read_text())["params"]}
        jobs = [(p, "base", "2020-01-01", "2026-09-01", "continuous") for p in [baseline, profile, v443]]
        jobs += [(profile, "short_only", "2020-01-01", "2026-09-01", "continuous")]
        jobs += [(p, "base", "2025-07-15", "2026-09-01", "holdout_reset") for p in [baseline, profile]]
    else:
        jobs = [(p, stress, "2020-01-01", "2026-09-01", "stress")
                for p in [baseline, profile] for stress in ["double_cost", "no_rebate", "delay_1h"]]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run_case, jobs))


if __name__ == "__main__":
    main()
