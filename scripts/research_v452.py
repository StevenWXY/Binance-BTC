"""Two-stage signal/risk development, using only data before January 2026."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from btc_regime.micro_backtest import run_micro_backtest
from btc_regime.v441_research import hourly_execution, metrics
from btc_regime.v441_r2 import features
from btc_regime.v444 import V444Params, generate_v444_signals
from btc_regime.v451 import V451Params, generate_v451_signals
from btc_regime.v452 import V452Params, generate_v452_signals, refinement_candidates, signal_candidates, v451_control
from evaluate_v441 import minute_batches
from evaluate_v444 import window_metrics
from research_v451 import config, short_stats

ROOT = Path("reports/v4_5_2")
CACHE = Path("data/v452")
END = "2026-01-01"
WINDOWS = {"legacy": ("2020-01-01", "2024-01-01"),
           "train_recent": ("2024-01-01", "2025-01-01"),
           "validation": ("2025-01-15", END), "recent": ("2024-01-01", END)}
FOLDS = [("2024-01-01", "2024-07-01"), ("2024-07-01", "2025-01-01"),
         ("2025-01-15", "2025-07-01"), ("2025-07-01", END)]


def prepare():
    CACHE.mkdir(parents=True, exist_ok=True)
    data = pd.read_pickle("data/v441/hourly.pkl").loc[:pd.Timestamp(END, tz="UTC") - pd.Timedelta(hours=1)]
    f = features(data)
    params = json.loads(Path("configs/v4_4_4_params.json").read_text())["params"]
    core = generate_v444_signals(data, V444Params(**params), prepared=f)
    data.to_pickle(CACHE / "development_hourly.pkl")
    f.to_pickle(CACHE / "development_features.pkl")
    core.to_pickle(CACHE / "development_core.pkl")


def baseline_profile():
    params = json.loads(Path("configs/v4_5_1_params.json").read_text())["short_params"]
    return {"id": "V451", "kind": "v451", "params": params, "selectable": False}


def profile(label, p, selectable=True):
    return {"id": label, "kind": "v452", "params": p.to_dict(), "selectable": selectable}


def profile_signal(data, item, *, f=None, core=None):
    if item["kind"] == "v451":
        return generate_v451_signals(data, V451Params(**item["params"]), prepared=f, long_signals=core)
    return generate_v452_signals(data, V452Params(**item["params"]), prepared=f, long_signals=core)


def summarize(result, item, cfg):
    windows = {k: window_metrics(result.equity, result.trades, a, b) for k, (a, b) in WINDOWS.items()}
    shorts = {}
    for k, (a, b) in WINDOWS.items():
        t = result.trades
        t = t.loc[(t.exit_time >= pd.Timestamp(a, tz="UTC")) & (t.exit_time < pd.Timestamp(b, tz="UTC"))]
        shorts[k] = short_stats(t)
    folds = [window_metrics(result.equity, result.trades, a, b) for a, b in FOLDS]
    def utility(m):
        return m["sharpe"] + .65 * m["annual_log_growth"] + .5 * m["max_drawdown"]
    score = sum(w * utility(windows[k]) for k, w in [("legacy", .15), ("train_recent", .35), ("validation", .50)])
    score -= .2 * np.std([r["sharpe"] for r in folds])
    return {"profile": item, "metrics": metrics(result.equity, result.trades), "windows": windows,
            "folds": folds, "shorts": shorts, "score": float(score), "execution": asdict(cfg)}


def run_case(job):
    item, phase = job
    minute = phase == "minute"
    data = pd.read_pickle(CACHE / "development_hourly.pkl")
    f = pd.read_pickle(CACHE / "development_features.pkl")
    core = pd.read_pickle(CACHE / "development_core.pkl")
    signal = profile_signal(data, item, f=f, core=core)
    funding = pd.read_pickle("data/v441/funding.pkl")
    batches = minute_batches(Path("data/v441"), "2020-01-01", END) if minute else [hourly_execution(data)]
    cfg = config(minute)
    result = run_micro_backtest(signal, batches, funding, cfg)
    row = summarize(result, item, cfg)
    values = pd.util.hash_pandas_object(signal[["signal", "stop_price", "take_profit_price"]], index=True)
    row["signal_signature"] = hashlib.sha256(values.to_numpy().tobytes()).hexdigest()
    entries = signal.loc[signal.signal.lt(0)].groupby("cycle_id", sort=False).head(1)
    row["short_entry_leverage"] = {"all": entries.signal.abs().describe().to_dict(),
                                   "recent": entries.loc["2024":].signal.abs().describe().to_dict()}
    dest = ROOT / phase / item["id"]
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "report.json").write_text(json.dumps(row, indent=2) + "\n")
    if minute:
        for name in ["equity", "trades", "fills", "funding", "liquidations"]:
            getattr(result, name).to_csv(dest / f"{name}.csv", index=name == "equity")
    w = row["windows"]["recent"]
    print(phase, item["id"], "R/S/DD", round(w["total_return"], 4), round(w["sharpe"], 4),
          round(w["max_drawdown"], 4), "short 2024/2025", round(row["shorts"]["train_recent"]["sum_cycle_returns"], 4),
          round(row["shorts"]["validation"]["sum_cycle_returns"], 4), "score", round(row["score"], 4), flush=True)
    return row


def qualify(row, baseline):
    w, b, s = row["windows"], baseline["windows"], row["shorts"]
    return bool(w["recent"]["sharpe"] > b["recent"]["sharpe"] + 1e-8 and
                w["recent"]["total_return"] > b["recent"]["total_return"] + 1e-8 and
                s["train_recent"]["sum_cycle_returns"] > 0 and s["validation"]["sum_cycle_returns"] > 0 and
                min(s["train_recent"]["cycles"], s["validation"]["cycles"]) >= 5 and
                w["legacy"]["sharpe"] >= b["legacy"]["sharpe"] - .20 and
                row["metrics"]["max_drawdown"] >= -.45 and w["recent"]["max_drawdown"] >= -.30)


def select_seeds(rows):
    control = v451_control()
    seeds = [profile("v451_control", control)]
    seen = {rows[0]["signal_signature"]}
    candidates = rows[1:]
    ordered = sorted(candidates, key=lambda r: (not r["eligible"], -r["score"]))
    for row in ordered:
        if row["signal_signature"] in seen:
            continue
        seen.add(row["signal_signature"])
        seeds.append(row["profile"])
        if len(seeds) == 4:
            break
    if len(seeds) != 4:
        raise ValueError("Not enough distinct signal seeds")
    return seeds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["signals", "refine", "minute"])
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if (ROOT / "selection_lock.json").exists():
        raise ValueError("Frozen selection; development reruns are disabled")
    if args.phase == "signals":
        prepare()
        profiles = [profile(f"a{i:03d}", p) for i, p in enumerate(signal_candidates())]
    elif args.phase == "refine":
        seeds = json.loads((ROOT / "signal_seeds.json").read_text())
        params = refinement_candidates([V452Params(**r["params"]) for r in seeds])
        profiles = [profile(f"b{i:03d}", p) for i, p in enumerate(params)]
    else:
        profiles = [r["profile"] for r in json.loads((ROOT / "finalists.json").read_text())]
        for risk in ["elevated", "higher"]:
            p = replace(v451_control(), risk=risk)
            if not any(x["params"] == p.to_dict() for x in profiles):
                profiles.append(profile(f"risk_{risk}", p, selectable=False))
    jobs = [(p, args.phase) for p in [baseline_profile()] + profiles]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(run_case, jobs))
    for row in rows:
        row["eligible"] = qualify(row, rows[0])
    (ROOT / f"{args.phase}_selection.json").write_text(json.dumps(rows, indent=2) + "\n")
    if args.phase == "signals":
        seeds = select_seeds(rows)
        (ROOT / "signal_seeds.json").write_text(json.dumps(seeds, indent=2) + "\n")
        print("SEEDS", seeds, flush=True)
    elif args.phase == "refine":
        eligible = [r for r in rows[1:] if r["eligible"]]
        top = sorted(eligible or rows[1:], key=lambda r: -r["score"])[:8]
        (ROOT / "finalists.json").write_text(json.dumps(top, indent=2) + "\n")
        print("ELIGIBLE", len(eligible), "FINALISTS", [r["profile"]["id"] for r in top], flush=True)


if __name__ == "__main__":
    main()
