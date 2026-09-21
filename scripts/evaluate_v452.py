"""Lock development selection, then evaluate V4.5.2 and its risk/signal controls."""
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
from btc_regime.v452 import V452Params, v451_control
from evaluate_v441 import minute_batches
from evaluate_v444 import file_hash, inputs, window_metrics
from research_v451 import config, short_stats
from research_v452 import ROOT, baseline_profile, profile, profile_signal

WINDOWS = {"full": ("2020-01-01", "2026-09-01"), "legacy": ("2020-01-01", "2024-01-01"),
           "recent": ("2024-01-01", "2026-09-01"), "recent_jul": ("2024-01-01", "2026-08-01"),
           "later_audit": ("2026-01-15", "2026-09-01")}


def validate_lock():
    lock = json.loads((ROOT / "selection_lock.json").read_text())
    for name, expected in lock["source_sha256"].items():
        if file_hash(name) != expected:
            raise ValueError(f"Frozen source/input changed: {name}")
    cfg = json.loads(Path("configs/v4_5_2_params.json").read_text())
    if cfg["short_params"] != lock["profile"]["params"]:
        raise ValueError("Frozen short parameters changed")
    return lock


def freeze():
    if (ROOT / "selection_lock.json").exists():
        return validate_lock()
    rows = json.loads((ROOT / "minute_selection.json").read_text())
    selectable = [r for r in rows if r["profile"]["selectable"]]
    eligible = [r for r in selectable if r["eligible"]]
    chosen = max(eligible or selectable, key=lambda r: r["score"])
    item = chosen["profile"]
    previous = json.loads(Path("configs/v4_5_1_params.json").read_text())
    cfg = {"version": "V4.5.2", "id": item["id"], "long_version": "V4.4.4",
           "long_params": previous["long_params"], "short_params": item["params"], "fee": previous["fee"],
           "post2024_max_drawdown_limit": .30}
    Path("configs/v4_5_2_params.json").write_text(json.dumps(cfg, indent=2) + "\n")
    files = [str(p) for p in Path("src/btc_regime").glob("*.py")]
    files += ["scripts/research_v452.py", "scripts/evaluate_v452.py", "scripts/research_v451.py",
              "scripts/evaluate_v444.py", "scripts/evaluate_v441.py", "scripts/evaluate_v441_round2.py",
              "reports/v4_5_2/protocol.json", "reports/v4_5_2/signals_selection.json",
              "reports/v4_5_2/refine_selection.json", "reports/v4_5_2/minute_selection.json",
              "configs/v4_4_4_params.json", "configs/v4_5_1_params.json", "configs/v4_4_3_params.json",
              "data/v441/hourly.pkl", "data/v441/funding.pkl", "data/v441/round2/extension_minutes.pkl",
              "data/raw/funding/BTCUSDT-fundingRate-2026-08.zip"]
    files += [str(p) for p in sorted(Path("data/v441/minutes").glob("*.pkl"))]
    lock = {"version": "V4.5.2", "profile": item, "development_eligible": bool(eligible), "score": chosen["score"],
            "selection_data_end_exclusive": "2026-01-01", "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
            "historically_blind_oos": False, "source_sha256": {p: file_hash(p) for p in files}}
    (ROOT / "selection_lock.json").write_text(json.dumps(lock, indent=2) + "\n")
    print("FROZEN", item, "eligible", bool(eligible), flush=True)
    return lock


def run_case(job):
    item, stress, start, end, group = job
    data, funding, extension = inputs()
    data = data.loc[data.index < pd.Timestamp(end, tz="UTC")]
    signal = profile_signal(data, item)
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
    elif stress == "minute_drawdown":
        cfg = replace(cfg, equity_interval_minutes=1, periods_per_year=525600)
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
    entry = signal.loc[signal.signal.lt(0)].groupby("cycle_id", sort=False).head(1)
    row = {"profile": item, "stress": stress, "window": [start, end],
           "metrics": metrics(result.equity, result.trades), "windows": windows, "yearly": yearly,
           "shorts": shorts, "execution": asdict(cfg), "execution_metrics": result.metrics,
           "short_entry_leverage": {"all": entry.signal.abs().describe().to_dict(),
                                    "recent": entry.loc["2024":].signal.abs().describe().to_dict()},
           "saved_equity_sampling_minutes": 60}
    dest = ROOT / group / f"{item['id']}__{stress}"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ["equity", "trades", "fills", "funding", "liquidations"]:
        value = getattr(result, name)
        if name == "equity" and stress == "minute_drawdown":
            value = value.resample("1h", closed="right", label="right").last().dropna()
        value.to_csv(dest / f"{name}.csv", index=name == "equity")
    (dest / "report.json").write_text(json.dumps(row, indent=2) + "\n")
    print(group, item["id"], stress, "full", row["metrics"], "recent", windows.get("recent"), flush=True)
    return row


def attribution_profiles(selected):
    p = V452Params(**selected["params"])
    return [profile("risk_only", replace(v451_control(), risk=p.risk), False),
            profile("signal_only", replace(p, risk="base"), False)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["freeze", "audit", "stress", "drawdown"])
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze()
        return
    item = validate_lock()["profile"]
    baseline = baseline_profile()
    if args.phase == "audit":
        longs = profile("V444", replace(v451_control(), short_enabled=False), False)
        jobs = [(p, "base", "2020-01-01", "2026-09-01", "continuous") for p in [baseline, item, longs]]
        jobs += [(p, "base", "2020-01-01", "2026-09-01", "attribution") for p in attribution_profiles(item)]
        jobs += [(item, "short_only", "2020-01-01", "2026-09-01", "attribution")]
        jobs += [(p, "base", "2026-01-15", "2026-09-01", "holdout_reset") for p in [baseline, item]]
    elif args.phase == "stress":
        jobs = [(p, stress, "2020-01-01", "2026-09-01", "stress")
                for p in [baseline, item] for stress in ["double_cost", "no_rebate", "delay_1h"]]
    else:
        jobs = [(p, "minute_drawdown", "2020-01-01", "2026-09-01", "drawdown") for p in [baseline, item]]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run_case, jobs))


if __name__ == "__main__":
    main()
