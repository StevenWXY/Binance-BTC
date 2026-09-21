"""V4.4.3 development screen and minute verification with 40% fee rebate."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v441_research import hourly_execution, metrics
from btc_regime.v443 import V443Params, candidates, generate_v443_signals
from btc_regime.v442 import V442Params, generate_v442_signals
from evaluate_v441 import build_signals, minute_batches
from btc_regime.v441 import V441Params

OUT = Path("reports/v4_4_3")
CACHE = Path("data/v441/round2")
FOLDS = [("2024-01-01", "2024-07-01"), ("2024-07-01", "2025-01-01"),
         ("2025-01-01", "2025-07-01"), ("2025-07-01", "2026-01-01"),
         ("2026-01-01", "2026-08-01")]
REBATE = {"published_taker_bps": 4.0, "rebate_fraction": .4, "effective_taker_bps": 2.4}


def config(*, minute=False, signal_interval=60):
    return MicroBacktestConfig(signal_interval_minutes=signal_interval, equity_interval_minutes=60,
                               execution_bar_minutes=1 if minute else 60, periods_per_year=8760,
                               conservative_protection=True, taker_fee_bps=2.4,
                               base_slippage_bps=1 if minute else 2,
                               impact_bps=8 if minute else 0)


def utility(m):
    return m["sharpe"] + .5 * m["annual_log_growth"] + 2 * m["max_drawdown"]


def score(row):
    folds = row["folds"]
    return float(.15 * utility(row["legacy"]) + .85 * np.mean([utility(x) for x in folds])
                 - .30 * np.std([x["sharpe"] for x in folds]))


def evaluate_proxy(p, label):
    data = pd.read_pickle("data/v441/hourly.pkl")
    funding = pd.read_pickle("data/v441/funding.pkl")
    prepared = pd.read_pickle("data/v441/round2/features.pkl")
    signal = generate_v443_signals(data, p, prepared=prepared)
    results = {}
    for name, start, end in [("legacy", "2020-01-01", "2024-01-01"),
                             ("recent", "2024-01-01", "2026-08-01")]:
        a, b = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
        s = signal.loc[(signal.index >= a - pd.Timedelta(hours=1)) & (signal.index < b)]
        e = hourly_execution(data.loc[(data.index >= a) & (data.index < b)])
        results[name] = run_micro_backtest(s, [e], funding, config())
    row = {"id": label, "params": p.to_dict(),
           "legacy": metrics(results["legacy"].equity, results["legacy"].trades),
           "recent": metrics(results["recent"].equity, results["recent"].trades)}
    row["folds"] = [metrics(results["recent"].equity.loc[(results["recent"].equity.index >= pd.Timestamp(a, tz="UTC")) &
                                                          (results["recent"].equity.index <= pd.Timestamp(b, tz="UTC"))],
                              results["recent"].trades.loc[(results["recent"].trades.exit_time >= pd.Timestamp(a, tz="UTC")) &
                                                           (results["recent"].trades.exit_time < pd.Timestamp(b, tz="UTC"))])
                    for a, b in FOLDS]
    row["score"] = score(row)
    row["eligible"] = (row["recent"]["max_drawdown"] >= -.35 and row["legacy"]["max_drawdown"] >= -.55
                        and row["recent"]["cycles"] >= 30)
    print(label, round(row["recent"]["total_return"], 3), round(row["recent"]["sharpe"], 3),
          round(row["score"], 3), row["recent"]["cycles"], flush=True)
    return row


def screen_job(job):
    i, p = job
    return evaluate_proxy(p, f"r{i:03d}")


def save_screen(rows):
    (OUT / "screen.json").write_text(json.dumps(rows, indent=2) + "\n")
    pd.DataFrame([{ "id": r["id"], "score": r["score"], "eligible": r["eligible"],
                    **{f"recent_{k}": v for k, v in r["recent"].items()},
                    **{f"fold{i}_sharpe": f["sharpe"] for i, f in enumerate(r["folds"])} }
                   for r in rows]).sort_values("score", ascending=False).to_csv(OUT / "screen.csv", index=False)


def batches(start, end):
    yield from minute_batches(Path("data/v441"), start, end)


def minute_job(job):
    return minute_case(*job)


def minute_case(profile, period):
    start, end = {"legacy": ("2020-01-01", "2024-01-01"),
                  "recent": ("2024-01-01", "2026-08-01")}[period]
    data = pd.read_pickle("data/v441/hourly.pkl")
    funding = pd.read_pickle("data/v441/funding.pkl")
    label = profile["id"]
    interval = 60
    if label.startswith("r"):
        signal = generate_v443_signals(data, V443Params(**profile["params"]))
    elif label == "V442":
        signal = generate_v442_signals(data, V442Params(**profile["params"]))
    else:
        signal, interval = build_signals(data, V441Params(), label, start)
    a = pd.Timestamp(start, tz="UTC")
    signal = signal.loc[signal.index >= a - pd.Timedelta(minutes=interval)]
    result = run_micro_backtest(signal, batches(start, end), funding,
                                config(minute=True, signal_interval=interval))
    row = {"id": label, "period": period, **metrics(result.equity, result.trades),
           "execution": asdict(config(minute=True, signal_interval=interval)), "rebate": REBATE}
    dest = OUT / f"{label}__{period}__minute"
    dest.mkdir(parents=True, exist_ok=True)
    result.equity.to_csv(dest / "equity.csv")
    result.trades.to_csv(dest / "trades.csv", index=False)
    result.fills.to_csv(dest / "fills.csv", index=False)
    result.funding.to_csv(dest / "funding.csv", index=False)
    result.liquidations.to_csv(dest / "liquidations.csv", index=False)
    (dest / "metrics.json").write_text(json.dumps(row, indent=2) + "\n")
    print("minute", label, period, round(row["total_return"], 3), round(row["sharpe"], 3), row["cycles"], flush=True)
    return row


def profile_for(label, params=None):
    if label == "V442":
        return {"id": label, "params": json.loads(Path("configs/v4_4_1_round2_params.json").read_text())["params"]}
    if label == "V4_1_3":
        return {"id": label, "params": {}}
    return {"id": label, "params": params}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["screen", "minute", "freeze"])
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    if args.phase == "screen":
        if (OUT / "freeze.json").exists():
            raise ValueError("V4.4.3 is frozen")
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            rows = list(ex.map(screen_job, enumerate(candidates())))
        save_screen(rows)
        top = sorted([r for r in rows if r["eligible"]], key=lambda x: -x["score"])[:8]
        (OUT / "minute_finalists.json").write_text(json.dumps(top, indent=2) + "\n")
        print("finalists", [r["id"] for r in top])
    elif args.phase == "minute":
        top = json.loads((OUT / "minute_finalists.json").read_text())
        profiles = top + [profile_for("V442"), profile_for("V4_1_3")]
        jobs = [(p, period) for period in ["legacy", "recent"] for p in profiles]
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            list(ex.map(minute_job, jobs))
    else:
        rows = json.loads((OUT / "minute_finalists.json").read_text())
        scored = []
        for r in rows:
            leg = json.loads((OUT / f"{r['id']}__legacy__minute/metrics.json").read_text())
            rec = json.loads((OUT / f"{r['id']}__recent__minute/metrics.json").read_text())
            folds = [rec]
            item = {"id": r["id"], "params": r["params"], "legacy": leg, "recent": rec, "folds": folds}
            item["score"] = score(item)
            item["eligible"] = (rec["max_drawdown"] >= -.35 and leg["max_drawdown"] >= -.55
                                and rec["cycles"] >= 30)
            scored.append(item)
        chosen = max([r for r in scored if r["eligible"]], key=lambda x: x["score"])
        config = {"version": "V4.4.3", "id": chosen["id"], "params": chosen["params"], "fee": REBATE}
        Path("configs/v4_4_3_params.json").write_text(json.dumps(config, indent=2) + "\n")
        source_files = ["src/btc_regime/v443.py", "src/btc_regime/v442.py", "src/btc_regime/v441_r2.py",
                        "src/btc_regime/micro_backtest.py", "scripts/research_v443.py", "reports/v4_4_3/protocol.json",
                        "reports/v4_4_3/screen.json", "reports/v4_4_3/minute_finalists.json", "data/v441/hourly.pkl", "data/v441/funding.pkl"]
        lock = {"version": "V4.4.3", "selected": chosen, "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_sha256": {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in source_files}}
        (OUT / "freeze.json").write_text(json.dumps(lock, indent=2) + "\n")
        (OUT / "minute_selection.json").write_text(json.dumps(scored, indent=2) + "\n")
        print("frozen", chosen["id"], chosen["score"])


if __name__ == "__main__":
    main()
