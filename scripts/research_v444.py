"""V4.4.4 full-history candidate screen and minute verification."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import json
from pathlib import Path

import numpy as np
import pandas as pd

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v441_research import hourly_execution, metrics
from btc_regime.v442 import V442Params, generate_v442_signals
from btc_regime.v443 import V443Params, generate_v443_signals
from btc_regime.v444 import V444Params, candidates, generate_v444_signals
from btc_regime.v441 import V441Params
from evaluate_v441 import build_signals, minute_batches

OUT = Path("reports/v4_4_4")
REBATE = {"published_taker_bps": 4.0, "rebate_fraction": .4, "effective_taker_bps": 2.4}
FOLDS = [("2024-01-01", "2024-07-01"), ("2024-07-01", "2025-01-01"),
         ("2025-01-01", "2025-07-01"), ("2025-07-01", "2026-01-01"),
         ("2026-01-01", "2026-08-01")]


def config(*, minute=False, interval=60):
    return MicroBacktestConfig(signal_interval_minutes=interval, equity_interval_minutes=60,
                               execution_bar_minutes=1 if minute else 60, periods_per_year=8760,
                               conservative_protection=True, taker_fee_bps=2.4,
                               base_slippage_bps=1 if minute else 2, impact_bps=8 if minute else 0)


def utility(row):
    return row["sharpe"] + .5 * row["annual_log_growth"] + 2 * row["max_drawdown"]


def score(row):
    return float(.35 * utility(row["legacy"]) + .65 * np.mean([utility(x) for x in row["folds"]])
                 - .30 * np.std([x["sharpe"] for x in row["folds"]]))


def evaluate_proxy(p, label):
    data = pd.read_pickle("data/v441/hourly.pkl")
    funding = pd.read_pickle("data/v441/funding.pkl")
    prepared = pd.read_pickle("data/v441/round2/features.pkl")
    signal = generate_v444_signals(data, p, prepared=prepared)
    outputs = {}
    for name, start, end in [("legacy", "2020-01-01", "2024-01-01"),
                             ("recent", "2024-01-01", "2026-08-01")]:
        a, b = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
        s = signal.loc[(signal.index >= a - pd.Timedelta(hours=1)) & (signal.index < b)]
        e = hourly_execution(data.loc[(data.index >= a) & (data.index < b)])
        outputs[name] = run_micro_backtest(s, [e], funding, config())
    recent = outputs["recent"]
    row = {"id": label, "params": p.to_dict(),
           "legacy": metrics(outputs["legacy"].equity, outputs["legacy"].trades),
           "recent": metrics(recent.equity, recent.trades)}
    row["folds"] = []
    for start, end in FOLDS:
        a, b = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
        row["folds"].append(metrics(
            recent.equity.loc[(recent.equity.index >= a) & (recent.equity.index <= b)],
            recent.trades.loc[(recent.trades.exit_time >= a) & (recent.trades.exit_time < b)]))
    row["score"] = score(row)
    row["eligible"] = (row["legacy"]["max_drawdown"] >= -.55 and row["recent"]["max_drawdown"] >= -.35
                        and row["recent"]["cycles"] >= 30)
    print(label, round(row["recent"]["total_return"], 3), round(row["recent"]["sharpe"], 3),
          round(row["legacy"]["sharpe"], 3), round(row["score"], 3), flush=True)
    return row


def screen_job(job):
    i, p = job
    return evaluate_proxy(p, f"r{i:03d}")


def save_rows(rows):
    (OUT / "screen.json").write_text(json.dumps(rows, indent=2) + "\n")
    pd.DataFrame([{ "id": r["id"], "score": r["score"], "eligible": r["eligible"],
                    **{f"recent_{k}": v for k, v in r["recent"].items()},
                    **{f"legacy_{k}": v for k, v in r["legacy"].items()},
                    **{f"fold{i}_sharpe": f["sharpe"] for i, f in enumerate(r["folds"])} }
                   for r in rows]).sort_values("score", ascending=False).to_csv(OUT / "screen.csv", index=False)


def profile_signal(profile, data, start):
    label = profile["id"]
    if label.startswith("r"):
        return generate_v444_signals(data, V444Params(**profile["params"])), 60
    if label == "V4.4.3":
        return generate_v443_signals(data, V443Params(**profile["params"])), 60
    if label == "V4.4.2":
        return generate_v442_signals(data, V442Params(**profile["params"])), 60
    return build_signals(data, V441Params(), "V4_1_3", start)


def minute_case(job):
    profile, period = job
    start, end = {"legacy": ("2020-01-01", "2024-01-01"),
                  "recent": ("2024-01-01", "2026-08-01")}[period]
    data = pd.read_pickle("data/v441/hourly.pkl")
    funding = pd.read_pickle("data/v441/funding.pkl")
    signal, interval = profile_signal(profile, data, start)
    a = pd.Timestamp(start, tz="UTC")
    signal = signal.loc[signal.index >= a - pd.Timedelta(minutes=interval)]
    result = run_micro_backtest(signal, minute_batches(Path("data/v441"), start, end), funding,
                                config(minute=True, interval=interval))
    row = {"id": profile["id"], "period": period, **metrics(result.equity, result.trades),
           "execution": asdict(config(minute=True, interval=interval)), "rebate": REBATE}
    if period == "recent":
        row["folds"] = []
        for start_fold, end_fold in FOLDS:
            first, last = pd.Timestamp(start_fold, tz="UTC"), pd.Timestamp(end_fold, tz="UTC")
            e = result.equity.loc[(result.equity.index >= first) & (result.equity.index <= last)]
            t = result.trades.loc[(result.trades.exit_time >= first) & (result.trades.exit_time < last)]
            row["folds"].append(metrics(e, t))
    dest = OUT / f"{profile['id']}__{period}__minute"
    dest.mkdir(parents=True, exist_ok=True)
    result.equity.to_csv(dest / "equity.csv")
    result.trades.to_csv(dest / "trades.csv", index=False)
    result.fills.to_csv(dest / "fills.csv", index=False)
    result.funding.to_csv(dest / "funding.csv", index=False)
    result.liquidations.to_csv(dest / "liquidations.csv", index=False)
    (dest / "metrics.json").write_text(json.dumps(row, indent=2) + "\n")
    print("minute", profile["id"], period, round(row["total_return"], 3), round(row["sharpe"], 3), row["cycles"], flush=True)
    return row


def profile_for(label, params=None):
    if label == "V4.4.3":
        return {"id": label, "params": json.loads(Path("configs/v4_4_3_params.json").read_text())["params"]}
    if label == "V4.4.2":
        return {"id": label, "params": json.loads(Path("configs/v4_4_2_params.json").read_text())["params"]}
    if label == "V4_1_3":
        return {"id": label, "params": {}}
    return {"id": label, "params": params}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["screen", "minute", "freeze"])
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    if args.phase == "screen":
        if (OUT / "freeze.json").exists() or (OUT / "final_selection_lock.json").exists():
            raise ValueError("V4.4.4 already frozen")
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            rows = list(executor.map(screen_job, enumerate(candidates())))
        save_rows(rows)
        finalists = sorted([r for r in rows if r["eligible"]], key=lambda r: -r["score"])[:8]
        (OUT / "minute_finalists.json").write_text(json.dumps(finalists, indent=2) + "\n")
        print("finalists", [r["id"] for r in finalists])
    elif args.phase == "minute":
        top = json.loads((OUT / "minute_finalists.json").read_text())
        profiles = top + [profile_for("V4.4.3"), profile_for("V4.4.2"), profile_for("V4_1_3")]
        jobs = [(p, period) for period in ["legacy", "recent"] for p in profiles]
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            list(executor.map(minute_case, jobs))
    else:
        # The continuous account is the canonical final selection procedure.
        from evaluate_v444 import freeze
        freeze()


if __name__ == "__main__":
    main()
