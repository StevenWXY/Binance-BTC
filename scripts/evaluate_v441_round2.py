"""Minute verification, then immutable selection, then reserved-month audit."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from btc_regime.data import load_funding
from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v441 import V441Params
from btc_regime.v441_r2 import R2Params, generate_r2_signals, route_r2
from btc_regime.v441_research import metrics
from evaluate_v441 import build_signals, minute_batches
from research_v441_round2 import FOLDS, parts, rank_score

OUT = Path("reports/v4_4_1_round2")
CACHE = Path("data/v441/round2")
PERIODS = {"legacy": ("2020-01-01", "2024-01-01"),
           "recent": ("2024-01-01", "2026-08-01"),
           "known_late": ("2025-07-15", "2026-08-01"),
           "extension": ("2026-08-01", "2026-09-01")}
for k in range(1, 5):
    a, b = FOLDS[k]
    PERIODS[f"rolling{k}"] = ((pd.Timestamp(a) + pd.Timedelta(days=14)).strftime("%Y-%m-%d"), b)


def generate_profile(data, profile):
    if "router" in profile:
        p = profile["router"]
        return route_r2(generate_r2_signals(data, R2Params(**p["core"])),
                        generate_r2_signals(data, R2Params(**p["satellite"])), p["allocation"])
    return generate_r2_signals(data, R2Params(**profile["params"]))


def extension_inputs():
    # Called only after validate_lock(). Development never reads these prices.
    minute = pd.read_pickle(CACHE / "extension_minutes.pkl")
    agg = {"open": "first", "high": "max", "low": "min", "close": "last",
           "volume": "sum", "quote_volume": "sum"}
    trade = minute.rename(columns={"trade_" + k: k for k in agg})
    hourly = trade[list(agg)].resample("1h").agg(agg)
    hourly["minute_count"] = trade.close.resample("1h").count()
    hourly = hourly.join(minute[["mark_" + k for k in list(agg)[:4]]].resample("1h").agg(
        {"mark_" + k: v for k, v in list(agg.items())[:4]}))
    funding = load_funding(Path("data/raw"), start="2026-08-01T00:00:00+00:00",
                           end="2026-09-01T00:00:00+00:00")
    rates = funding.funding_rate.groupby(funding.index.floor("1h")).sum()
    hourly["funding_rate"] = rates.reindex(hourly.index, fill_value=0.)
    hourly["funding_event"] = hourly.index.isin(rates.index)
    data = pd.concat([pd.read_pickle("data/v441/hourly.pkl"), hourly])
    return data, funding, minute


def run_case(job):
    profile, period, stress = job
    label = profile["id"]
    start, end = PERIODS[period]
    if period == "extension":
        validate_lock()
        data, funding, minute = extension_inputs()
        batches = [minute]
    else:
        data = pd.read_pickle("data/v441/hourly.pkl")
        data = data.loc[data.index < pd.Timestamp(end, tz="UTC")]
        funding = pd.read_pickle("data/v441/funding.pkl")
        batches = minute_batches(Path("data/v441"), start, end)
    if label.startswith("V4"):
        p = V441Params(**json.loads(Path("configs/v4_4_1_params.json").read_text()))
        signal, interval = build_signals(data, p, label, start)
    else:
        signal = generate_profile(data, profile)
        interval = 60
    cfg = MicroBacktestConfig(signal_interval_minutes=interval, equity_interval_minutes=60,
                             periods_per_year=8760, conservative_protection=True,
                             taker_fee_bps=4, base_slippage_bps=1, impact_bps=8)
    if stress == "double_cost":
        cfg = replace(cfg, taker_fee_bps=8, base_slippage_bps=3, impact_bps=16)
    elif stress == "delay_1h":
        signal.index += pd.Timedelta(hours=1)
    signal = signal.loc[signal.index >= pd.Timestamp(start, tz="UTC") - pd.Timedelta(minutes=interval)]
    result = run_micro_backtest(signal, batches, funding, cfg)
    row = {"id": label, "period": period, "stress": stress, **metrics(result.equity, result.trades),
           "execution": asdict(cfg), "execution_metrics": result.metrics}
    if period == "recent":
        row["folds"] = [parts(result.equity, result.trades, a, b) for a, b in FOLDS]
    dest = OUT / f"{label}__{period}__{stress}"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ["equity", "trades", "fills", "funding", "liquidations"]:
        value = getattr(result, name)
        value.to_csv(dest / f"{name}.csv", index=name == "equity")
    (dest / "metrics.json").write_text(json.dumps(row, indent=2) + "\n")
    print(dest.name, "return", round(row["total_return"], 4), "Sharpe", round(row["sharpe"], 4),
          "DD", round(row["max_drawdown"], 4), "cycles", row["cycles"], flush=True)
    return row


def validate_lock():
    lock = json.loads((OUT / "final_selection_lock.json").read_text())
    for name, digest in lock["source_sha256"].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Frozen source changed: {name}")
    config = json.loads(Path("configs/v4_4_1_round2_params.json").read_text())
    if config != lock["profile"]:
        raise ValueError("Frozen profile changed")
    return config


def freeze():
    lock_path = OUT / "final_selection_lock.json"
    if lock_path.exists():
        return validate_lock()
    rows = []
    for p in json.loads((OUT / "minute_finalists.json").read_text()):
        recent = json.loads((OUT / f"{p['id']}__recent__base/metrics.json").read_text())
        legacy = json.loads((OUT / f"{p['id']}__legacy__base/metrics.json").read_text())
        row = {"profile": {k: p[k] for k in ["id", "params", "router"] if k in p},
               "legacy": legacy, "recent": recent, "folds": recent["folds"]}
        row["score"] = float(rank_score(row))
        row["eligible"] = (recent["max_drawdown"] >= -.35 and legacy["max_drawdown"] >= -.55
                           and recent["cycles"] >= 30)
        rows.append(row)
    eligible = [r for r in rows if r["eligible"]]
    if not eligible:
        raise ValueError("No candidate meets minute constraints")
    chosen = max(eligible, key=lambda r: r["score"])
    profile = chosen["profile"]
    sources = ["src/btc_regime/v441_r2.py", "src/btc_regime/v441.py",
               "src/btc_regime/micro_backtest.py", "src/btc_regime/strategy.py", "src/btc_regime/v43.py",
               "src/btc_regime/v441_research.py", "scripts/evaluate_v441_round2.py",
               "scripts/research_v441_round2.py", "reports/v4_4_1_round2/protocol.json",
               "reports/v4_4_1_round2/continuation_protocol.json", "scripts/evaluate_v441.py",
               "src/btc_regime/indicators.py", "src/btc_regime/data.py", "src/btc_regime/v413.py",
               "reports/v4_4_1_round2/minute_finalists.json", "reports/v4_4_1_round2/screen.json",
               "data/v441/hourly.pkl", "data/v441/funding.pkl", "data/v441/round2/extension_minutes.pkl"]
    lock = {"profile": profile, "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
            "reserved_extension_returns_seen": False, "minute_selection_score": chosen["score"],
            "source_sha256": {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sources}}
    (OUT / "minute_selection.json").write_text(json.dumps(rows, indent=2) + "\n")
    Path("configs/v4_4_1_round2_params.json").write_text(json.dumps(profile, indent=2) + "\n")
    lock_path.write_text(json.dumps(lock, indent=2) + "\n")
    print("FROZEN", profile, flush=True)
    return profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["development", "freeze", "audit", "rolling"])
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.phase == "development":
        if (OUT / "final_selection_lock.json").exists():
            raise ValueError("Development selection is frozen")
        profiles = json.loads((OUT / "minute_finalists.json").read_text())
        jobs = [(p, period, "base") for period in ["recent", "legacy"] for p in profiles]
    elif args.phase == "freeze":
        freeze()
        return
    elif args.phase == "rolling":
        validate_lock()
        # Retrospective procedural audit; research-family design itself has seen
        # the full development history. Exclude routers chosen with future scores.
        rows = [r for r in json.loads((OUT / "screen.json").read_text()) if "params" in r]
        choices, jobs = [], []
        for k in range(1, 5):
            prior = [r for r in rows if r["legacy"]["max_drawdown"] >= -.55
                     and all(f["max_drawdown"] >= -.35 for f in r["folds"][:k])
                     and sum(f["cycles"] for f in r["folds"][:k]) >= 10]
            p = max(prior, key=lambda r: rank_score(r, k))
            profile = {"id": p["id"], "params": p["params"]}
            choices.append({"fold": k, "profile": profile, "period": PERIODS[f"rolling{k}"],
                            "prior_score": float(rank_score(p, k))})
            jobs += [(profile, f"rolling{k}", "base"), ({"id": "V4_1_3"}, f"rolling{k}", "base")]
        (OUT / "rolling_choices.json").write_text(json.dumps(choices, indent=2) + "\n")
    else:
        chosen = validate_lock()
        profiles = [chosen, {"id": "V441"}, {"id": "V4_1_2"}, {"id": "V4_1_3"}]
        jobs = [(p, "extension", "base") for p in profiles]
        jobs += [(chosen, "known_late", "base")]
        jobs += [(p, "recent", stress) for p in [chosen, {"id": "V4_1_3"}]
                 for stress in ["double_cost", "delay_1h"]]
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        list(executor.map(run_case, jobs))


if __name__ == "__main__":
    main()
