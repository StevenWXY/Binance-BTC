"""Round-2 registered families, chronological scoring and frozen finalists."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from btc_regime.micro_backtest import run_micro_backtest
from btc_regime.v441_r2 import candidates, continuation_candidates, features, generate_r2_signals, route_r2
from btc_regime.v441_research import hourly_execution, metrics, proxy_config

OUT = Path("reports/v4_4_1_round2")
CACHE = Path("data/v441/round2")
FOLDS = [("2024-01-01", "2024-07-01"), ("2024-07-01", "2025-01-01"),
         ("2025-01-01", "2025-07-01"), ("2025-07-01", "2026-01-01"),
         ("2026-01-01", "2026-08-01")]


def parts(equity, trades, start, end):
    a, b = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    e = equity.loc[(equity.index >= a) & (equity.index <= b)]
    t = trades.loc[(trades.exit_time >= a) & (trades.exit_time < b)] if len(trades) else trades
    return metrics(e, t)


def utility(m):
    return m["sharpe"] + .5 * m["annual_log_growth"] + 2 * m["max_drawdown"]


def rank_score(row, fold_count=5):
    folds = row["folds"][:fold_count]
    return (.15 * utility(row["legacy"]) + .85 * np.mean([utility(x) for x in folds])
            - .30 * np.std([x["sharpe"] for x in folds]))


def evaluate_signal(label, signal, data, funding):
    cfg = proxy_config()
    results = {}
    for name, start, end in [("legacy", "2020-01-01", "2024-01-01"), ("recent", "2024-01-01", "2026-08-01")]:
        a, b = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
        s = signal.loc[(signal.index >= a - pd.Timedelta(hours=1)) & (signal.index < b)]
        exe = hourly_execution(data.loc[(data.index >= a) & (data.index < b)])
        result = run_micro_backtest(s, [exe], funding, cfg)
        results[name] = result
    recent = results["recent"]
    row = {"id": label, "legacy": metrics(results["legacy"].equity, results["legacy"].trades),
           "recent": metrics(recent.equity, recent.trades),
           "folds": [parts(recent.equity, recent.trades, a, b) for a, b in FOLDS]}
    row["score"] = float(rank_score(row))
    row["eligible"] = (row["recent"]["max_drawdown"] >= -.35
                       and row["legacy"]["max_drawdown"] >= -.55 and row["recent"]["cycles"] >= 30)
    recent.equity.to_pickle(CACHE / f"{label}_equity.pkl")
    signal[["signal", "stop_price", "take_profit_price", "cycle_id"]].to_pickle(CACHE / f"{label}_signal.pkl")
    return row


def screen_one(job):
    i, p = job
    data = pd.read_pickle("data/v441/hourly.pkl")
    funding = pd.read_pickle("data/v441/funding.pkl")
    f = pd.read_pickle(CACHE / "features.pkl")
    signal = generate_r2_signals(data, p, prepared=f)
    row = evaluate_signal(f"r{i:03d}", signal, data, funding)
    row["params"] = p.to_dict()
    print(row["id"], p.family, p.speed, p.risk, p.protection, p.gate,
          "R/S/DD", round(row["recent"]["total_return"], 2), round(row["recent"]["sharpe"], 2),
          round(row["recent"]["max_drawdown"], 2), "score", round(row["score"], 2), flush=True)
    return row


def save_tables(rows):
    (OUT / "screen.json").write_text(json.dumps(rows, indent=2) + "\n")
    flat = [{"id": r["id"], "family": r.get("params", {}).get("family", "router"),
             "score": r["score"], "eligible": r["eligible"],
             **{f"recent_{k}": v for k, v in r["recent"].items()},
             **{f"fold{i}_sharpe": f["sharpe"] for i, f in enumerate(r["folds"])}}
            for r in rows]
    pd.DataFrame(flat).sort_values("score", ascending=False).to_csv(OUT / "screen.csv", index=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--continuation", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    if (OUT / "final_selection_lock.json").exists():
        raise ValueError("Round-2 selection is frozen; create a new research round")
    CACHE.mkdir(parents=True, exist_ok=True)
    data = pd.read_pickle("data/v441/hourly.pkl")
    if data.index.max() >= pd.Timestamp("2026-08-01", tz="UTC"):
        raise ValueError("Development input includes reserved extension")
    features(data).to_pickle(CACHE / "features.pkl")
    if args.continuation:
        # Preserve all previous trials; extension remains unopened for selection.
        rows = json.loads((OUT / "screen.json").read_text())
        if any(r.get("params", {}).get("family") == "continuation" for r in rows):
            raise ValueError("Continuation screen already exists; preserve prior trials")
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            rows += list(executor.map(screen_one, enumerate(continuation_candidates(), start=96)))
        save_tables(rows)
        finalists = sorted([r for r in rows if r["eligible"]], key=lambda r: -r["score"])[:6]
        (OUT / "minute_finalists.json").write_text(json.dumps(finalists, indent=2) + "\n")
        print("FINALISTS", [r["id"] for r in finalists], flush=True)
        return
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        rows = list(executor.map(screen_one, enumerate(candidates())))
    save_tables(rows)
    ordered = sorted([r for r in rows if r["eligible"]], key=lambda r: -r["score"])
    cores = [r for r in ordered if r["params"]["family"] == "core"][:2]
    tactical = [r for r in ordered if r["params"]["family"] != "core" and r["recent"]["annual_log_growth"] > 0][:2]
    funding = pd.read_pickle("data/v441/funding.pkl")
    for c in cores:
        for s in tactical:
            for allocation in [.25, .5, 1.]:
                first = pd.read_pickle(CACHE / f"{c['id']}_signal.pkl")
                second = pd.read_pickle(CACHE / f"{s['id']}_signal.pkl")
                signal = route_r2(first, second, allocation)
                label = f"mix_{c['id']}_{s['id']}_{int(allocation*100)}"
                row = evaluate_signal(label, signal, data, funding)
                row["router"] = {"core": c["params"], "satellite": s["params"], "allocation": allocation}
                rows.append(row)
                print(label, row["score"], row["recent"], flush=True)
    save_tables(rows)
    finalists = sorted([r for r in rows if r["eligible"]], key=lambda r: -r["score"])[:6]
    (OUT / "minute_finalists.json").write_text(json.dumps(finalists, indent=2) + "\n")
    # Procedural rolling selections: do not let future eligibility exclude earlier picks.
    walk = []
    for k in range(1, 5):
        prior = [r for r in rows[:96] if r["legacy"]["max_drawdown"] >= -.55
                 and all(f["max_drawdown"] >= -.35 for f in r["folds"][:k])
                 and sum(f["cycles"] for f in r["folds"][:k]) >= 10]
        chosen = max(prior, key=lambda r: rank_score(r, k))
        a, b = FOLDS[k]
        embargo = (pd.Timestamp(a) + pd.Timedelta(days=14)).strftime("%Y-%m-%d")
        e = pd.read_pickle(CACHE / f"{chosen['id']}_equity.pkl")
        window = e.loc[(e.index >= pd.Timestamp(embargo, tz="UTC")) & (e.index <= pd.Timestamp(b, tz="UTC"))]
        walk.append({"chosen": chosen["id"], "selected_using_folds": k,
                     "evaluation_start": embargo, "evaluation_end": b, "metrics": metrics(window, pd.DataFrame())})
    (OUT / "walkforward_proxy.json").write_text(json.dumps(walk, indent=2) + "\n")
    (OUT / "screen_manifest.json").write_text(json.dumps({
        "candidates_evaluated": len(rows), "source_sha256": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path("src/btc_regime/v441_r2.py"), Path(__file__), OUT / "protocol.json"]}}, indent=2) + "\n")
    print("FINALISTS", [r["id"] for r in finalists], flush=True)


if __name__ == "__main__":
    main()
