"""Continuous-account selection and auditable, frozen V4.4.4 comparisons."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
from itertools import chain
import json
from pathlib import Path

import pandas as pd

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v441_research import metrics
from btc_regime.v443 import V443Params, generate_v443_signals
from btc_regime.v444 import V444Params, generate_v444_signals
from evaluate_v441 import minute_batches
from evaluate_v441_round2 import extension_inputs

ROOT = Path("reports/v4_4_4")
BASELINE = {"id": "V443", "params": json.loads(Path("configs/v4_4_3_params.json").read_text())["params"]}
PERIODS = {"full": ("2020-01-01", "2026-09-01"),
           "legacy": ("2020-01-01", "2024-01-01"),
           "recent": ("2024-01-01", "2026-09-01"),
           "recent_jul": ("2024-01-01", "2026-08-01"),
           "august": ("2026-08-01", "2026-09-01")}


def inputs():
    data, august_funding, extension = extension_inputs()
    funding = pd.concat([pd.read_pickle("data/v441/funding.pkl"), august_funding]).sort_index()
    if funding.index.has_duplicates or data.index.has_duplicates:
        raise ValueError("Duplicate input timestamp")
    return data, funding, extension


def read_equity(path):
    e = pd.read_csv(path, index_col=0).iloc[:, 0]
    e.index = pd.to_datetime(e.index, utc=True)
    return e


def window_metrics(equity, trades, start, end):
    a, b = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    e = equity.loc[(equity.index >= a) & (equity.index <= b)]
    t = trades.loc[(trades.exit_time >= a) & (trades.exit_time < b)] if len(trades) else trades
    if len(e) < 2:
        raise ValueError("Insufficient observations")
    return metrics(e, t)


def summarize(result, profile, config, start, end, stress):
    recent = {k: window_metrics(result.equity, result.trades, a, b)
              for k, (a, b) in PERIODS.items() if pd.Timestamp(a) >= pd.Timestamp(start)
              and pd.Timestamp(b) <= pd.Timestamp(end)}
    yearly = {}
    for year in range(pd.Timestamp(start).year, pd.Timestamp(end).year + 1):
        a = max(pd.Timestamp(start), pd.Timestamp(f"{year}-01-01"))
        b = min(pd.Timestamp(end), pd.Timestamp(f"{year+1}-01-01"))
        if b <= a:
            continue
        yearly[str(year)] = window_metrics(result.equity, result.trades, str(a), str(b))
    return {"id": profile["id"], "profile": profile, "window": [start, end], "stress": stress,
            "metrics": metrics(result.equity, result.trades), "windows": recent, "yearly": yearly,
            "execution": asdict(config), "execution_metrics": result.metrics,
            "fee_policy": "4bps * (1-40% rebate) = 2.4bps net; rebate credited at fill, no discount on funding/slippage/liquidation"}


def run_case(job):
    profile, stress, start, end, group = job
    data, funding, extension = inputs()
    data = data.loc[data.index < pd.Timestamp(end, tz="UTC")]
    if profile["id"] == "V443":
        signal = generate_v443_signals(data, V443Params(**profile["params"]))
    else:
        signal = generate_v444_signals(data, V444Params(**profile["params"]))
    cfg = MicroBacktestConfig(signal_interval_minutes=60, equity_interval_minutes=60,
                             periods_per_year=8760, conservative_protection=True,
                             taker_fee_bps=2.4, base_slippage_bps=1, impact_bps=8)
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
    dest = ROOT / group / f"{profile['id']}__{stress}"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ["equity", "trades", "fills", "funding", "liquidations"]:
        getattr(result, name).to_csv(dest / f"{name}.csv", index=name == "equity")
    row = summarize(result, profile, cfg, start, end, stress)
    (dest / "report.json").write_text(json.dumps(row, indent=2) + "\n")
    print(group, profile["id"], stress, "full S/R/DD", round(row['metrics']['sharpe'], 4),
          round(row['metrics']['total_return'], 3), round(row['metrics']['max_drawdown'], 3),
          "recent", {k: round(v['sharpe'], 4) for k, v in row['windows'].items() if k.startswith('recent')}, flush=True)
    return row


def candidate_profiles():
    return [{"id": r["id"], "params": r["params"]}
            for r in json.loads((ROOT / "phase1/minute_finalists.json").read_text())]


def lock_validate():
    lock = json.loads((ROOT / "final_selection_lock.json").read_text())
    for name, expected in lock["source_sha256"].items():
        if file_hash(name) != expected:
            raise ValueError(f"Frozen source/input changed: {name}")
    config = json.loads(Path("configs/v4_4_4_params.json").read_text())
    if config["params"] != lock["profile"]["params"]:
        raise ValueError("Frozen params changed")
    return lock


def file_hash(name):
    digest = hashlib.sha256()
    with Path(name).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def freeze():
    if (ROOT / "final_selection_lock.json").exists():
        return lock_validate()
    baseline = json.loads((ROOT / "continuous/V443__base/report.json").read_text())
    rows = []
    for p in candidate_profiles():
        row = json.loads((ROOT / f"continuous/{p['id']}__base/report.json").read_text())
        w = row["windows"]
        better = all(w[k]["sharpe"] > baseline["windows"][k]["sharpe"] + 1e-6
                     for k in ["full", "recent", "recent_jul"])
        safe = w["full"]["max_drawdown"] >= -.45 and w["recent"]["max_drawdown"] >= -.35
        keeps_return = all(w[k]["total_return"] >= .7 * baseline["windows"][k]["total_return"]
                           for k in ["full", "recent"])
        row["eligible"] = better and safe and keeps_return
        row["score"] = .35 * w["full"]["sharpe"] + .65 * w["recent_jul"]["sharpe"] + .5 * w["full"]["max_drawdown"]
        rows.append(row)
    (ROOT / "continuous_selection.json").write_text(json.dumps(rows, indent=2) + "\n")
    eligible = [r for r in rows if r["eligible"]]
    if not eligible:
        raise ValueError("No candidate improves all primary Sharpe objectives")
    chosen = max(eligible, key=lambda r: r["score"])
    profile = chosen["profile"]
    files = [str(p) for p in Path("src/btc_regime").glob("*.py")]
    files += ["scripts/evaluate_v444.py", "scripts/research_v444.py", "scripts/evaluate_v441.py",
              "scripts/evaluate_v441_round2.py", "reports/v4_4_4/continuous_protocol.json",
              "reports/v4_4_4/phase1/screen.json", "reports/v4_4_4/phase1/minute_finalists.json",
              "data/v441/hourly.pkl", "data/v441/funding.pkl", "data/v441/round2/extension_minutes.pkl",
              "data/raw/funding/BTCUSDT-fundingRate-2026-08.zip", "configs/v4_4_3_params.json"]
    files += [str(p) for p in sorted(Path("data/v441/minutes").glob("*.pkl"))]
    config = {"version": "V4.4.4", "id": profile["id"], "params": profile["params"],
              "fee": {"published_taker_bps": 4., "rebate_fraction": .4, "effective_taker_bps": 2.4}}
    Path("configs/v4_4_4_params.json").write_text(json.dumps(config, indent=2) + "\n")
    lock = {"version": "V4.4.4", "profile": profile, "score": chosen["score"],
            "frozen_at_utc": datetime.now(timezone.utc).isoformat(), "blind_holdout": False,
            "source_sha256": {p: file_hash(p) for p in files}}
    (ROOT / "final_selection_lock.json").write_text(json.dumps(lock, indent=2) + "\n")
    print("FROZEN", profile, flush=True)
    return lock


def rolling_jobs():
    profiles = candidate_profiles()
    curves = {p["id"]: read_equity(ROOT / f"continuous/{p['id']}__base/equity.csv") for p in profiles}
    periods = [("2024-01-01", "2024-07-01"), ("2024-07-01", "2025-01-01"),
               ("2025-01-01", "2025-07-01"), ("2025-07-01", "2026-01-01"), ("2026-01-01", "2026-09-01")]
    choices, jobs = [], []
    for k, (a, b) in enumerate(periods):
        scores = {}
        for p in profiles:
            e = curves[p["id"]].loc[:pd.Timestamp(a, tz="UTC")]
            all_prior = metrics(e, pd.DataFrame())
            start = max(pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp(a, tz="UTC") - pd.Timedelta(days=730))
            recent_prior = metrics(e.loc[start:], pd.DataFrame())
            scores[p["id"]] = .35*all_prior["sharpe"] + .65*recent_prior["sharpe"] + .5*all_prior["max_drawdown"]
        chosen = max(profiles, key=lambda p: scores[p["id"]])
        start = (pd.Timestamp(a) + pd.Timedelta(days=14)).strftime("%Y-%m-%d")
        choices.append({"fold": k, "training_end": a, "evaluation": [start, b], "profile": chosen, "prior_scores": scores})
        jobs.extend([(chosen, "base", start, b, f"rolling/fold{k}"), (BASELINE, "base", start, b, f"rolling/fold{k}")])
    (ROOT / "rolling_choices.json").write_text(json.dumps(choices, indent=2) + "\n")
    return jobs


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("phase", choices=["candidates", "freeze", "stress", "rolling"])
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()
    if args.phase == "candidates":
        if (ROOT / "final_selection_lock.json").exists():
            raise ValueError("Selection already frozen")
        jobs = [(p, "base", "2020-01-01", "2026-09-01", "continuous") for p in [BASELINE] + candidate_profiles()]
    elif args.phase == "freeze":
        freeze()
        return
    elif args.phase == "stress":
        chosen = lock_validate()["profile"]
        jobs = [(p, stress, "2020-01-01", "2026-09-01", "stress")
                for p in [BASELINE, chosen] for stress in ["double_cost", "no_rebate", "delay_1h"]]
    else:
        lock_validate()
        jobs = rolling_jobs()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run_case, jobs))


if __name__ == "__main__":
    main()
