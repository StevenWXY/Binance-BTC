"""V4.5.1 development restricted to data strictly before July 2025."""
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
from btc_regime.v441_r2 import features
from btc_regime.v444 import V444Params, generate_v444_signals
from btc_regime.v451 import V451Params, candidates, generate_v451_signals
from evaluate_v441 import minute_batches
from evaluate_v444 import window_metrics

ROOT = Path("reports/v4_5_1")
CACHE = Path("data/v451")
END = "2025-07-01"
WINDOWS = {"legacy": ("2020-01-01", "2024-01-01"),
           "train_recent": ("2024-01-01", "2025-01-01"),
           "validation": ("2025-01-15", END),
           "recent": ("2024-01-01", END)}
FOLDS = [("2024-01-01", "2024-07-01"), ("2024-07-01", "2025-01-01"),
         ("2025-01-15", END)]


def prepare():
    CACHE.mkdir(parents=True, exist_ok=True)
    data = pd.read_pickle("data/v441/hourly.pkl").loc[:pd.Timestamp(END, tz="UTC") - pd.Timedelta(hours=1)]
    f = features(data)
    params = json.loads(Path("configs/v4_4_4_params.json").read_text())["params"]
    core = generate_v444_signals(data, V444Params(**params), prepared=f)
    data.to_pickle(CACHE / "development_hourly.pkl")
    f.to_pickle(CACHE / "development_features.pkl")
    core.to_pickle(CACHE / "development_core.pkl")


def config(minute):
    return MicroBacktestConfig(signal_interval_minutes=60, equity_interval_minutes=60,
                               execution_bar_minutes=1 if minute else 60, periods_per_year=8760,
                               conservative_protection=True, taker_fee_bps=2.4,
                               base_slippage_bps=1 if minute else 2, impact_bps=8 if minute else 0)


def short_stats(trades):
    t = trades.loc[trades.side.eq("short")] if len(trades) else trades
    returns = t.pnl / t.equity_before if len(t) else pd.Series(dtype=float)
    return {"cycles": len(t), "sum_cycle_returns": float(returns.sum()),
            "mean_cycle_return": float(returns.mean()) if len(t) else 0.,
            "win_rate": float((returns > 0).mean()) if len(t) else 0.}


def summarize(result, profile, cfg):
    windows = {k: window_metrics(result.equity, result.trades, a, b) for k, (a, b) in WINDOWS.items()}
    shorts = {}
    for k, (a, b) in WINDOWS.items():
        t = result.trades
        t = t.loc[(t.exit_time >= pd.Timestamp(a, tz="UTC")) & (t.exit_time < pd.Timestamp(b, tz="UTC"))]
        shorts[k] = short_stats(t)
    folds = [window_metrics(result.equity, result.trades, a, b) for a, b in FOLDS]
    def utility(m):
        return m["sharpe"] + .5 * m["annual_log_growth"] + m["max_drawdown"]
    score = sum(w * utility(windows[k]) for k, w in [("legacy", .2), ("train_recent", .4), ("validation", .4)])
    score -= .2 * np.std([r["sharpe"] for r in folds])
    return {"profile": profile, "metrics": metrics(result.equity, result.trades), "windows": windows,
            "folds": folds, "shorts": shorts, "score": float(score), "execution": asdict(cfg)}


def run_case(job):
    profile, minute = job
    data = pd.read_pickle(CACHE / "development_hourly.pkl")
    f = pd.read_pickle(CACHE / "development_features.pkl")
    core = pd.read_pickle(CACHE / "development_core.pkl")
    signal = generate_v451_signals(data, V451Params(**profile["params"]), prepared=f, long_signals=core)
    funding = pd.read_pickle("data/v441/funding.pkl")
    batches = minute_batches(Path("data/v441"), "2020-01-01", END) if minute else [hourly_execution(data)]
    cfg = config(minute)
    result = run_micro_backtest(signal, batches, funding, cfg)
    row = summarize(result, profile, cfg)
    dest = ROOT / ("development_minute" if minute else "screen") / profile["id"]
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "report.json").write_text(json.dumps(row, indent=2) + "\n")
    if minute:
        for name in ["equity", "trades", "fills", "funding", "liquidations"]:
            getattr(result, name).to_csv(dest / f"{name}.csv", index=name == "equity")
    print("minute" if minute else "proxy", profile["id"], "recent R/S", round(row["windows"]["recent"]["total_return"], 3),
          round(row["windows"]["recent"]["sharpe"], 3), "shorts 2024/H1", row["shorts"]["train_recent"],
          row["shorts"]["validation"], "score", round(row["score"], 4), flush=True)
    return row


def qualify(row, baseline):
    w, b, s = row["windows"], baseline["windows"], row["shorts"]
    return bool(w["recent"]["sharpe"] > b["recent"]["sharpe"] and
                w["recent"]["total_return"] > b["recent"]["total_return"] and
                s["train_recent"]["sum_cycle_returns"] > 0 and s["validation"]["sum_cycle_returns"] > 0 and
                s["train_recent"]["cycles"] >= 5 and s["validation"]["cycles"] >= 3 and
                w["legacy"]["sharpe"] >= b["legacy"]["sharpe"] - .15 and
                row["metrics"]["max_drawdown"] >= -.4 and w["recent"]["max_drawdown"] >= -.35)


def baseline_profile():
    return {"id": "V444", "params": V451Params(short_enabled=False).to_dict()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["screen", "minute"])
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if (ROOT / "selection_lock.json").exists():
        raise ValueError("V4.5.1 already frozen; do not repeat selection")
    minute = args.phase == "minute"
    if not minute:
        prepare()
        profiles = [baseline_profile()] + [{"id": f"s{i:03d}", "params": p.to_dict()} for i, p in enumerate(candidates())]
    else:
        profiles = [baseline_profile()] + [r["profile"] for r in json.loads((ROOT / "finalists.json").read_text())]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(run_case, [(p, minute) for p in profiles]))
    baseline = rows[0]
    for row in rows:
        row["eligible"] = qualify(row, baseline)
    (ROOT / ("minute_selection.json" if minute else "screen.json")).write_text(json.dumps(rows, indent=2) + "\n")
    if not minute:
        eligible = [r for r in rows[1:] if r["eligible"]]
        # Preserve best research alternatives if strict promotion conditions fail.
        top = sorted(eligible or rows[1:], key=lambda r: -r["score"])[:6]
        (ROOT / "finalists.json").write_text(json.dumps(top, indent=2) + "\n")
        print("eligible", len(eligible), "finalists", [r["profile"]["id"] for r in top], flush=True)


if __name__ == "__main__":
    main()
