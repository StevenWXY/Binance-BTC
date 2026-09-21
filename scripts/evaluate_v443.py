"""Post-freeze V4.4.3 extension, stress, and baseline comparison."""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

import pandas as pd

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v441 import V441Params
from btc_regime.v442 import V442Params, generate_v442_signals
from btc_regime.v443 import V443Params, generate_v443_signals
from btc_regime.v441_research import metrics
from evaluate_v441 import build_signals, minute_batches
from evaluate_v441_round2 import extension_inputs

OUT = Path("reports/v4_4_3")
REBATE = {"published_taker_bps": 4.0, "rebate_fraction": .4, "effective_taker_bps": 2.4}


def lock():
    item = json.loads((OUT / "freeze.json").read_text())
    for name, digest in item["source_sha256"].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Frozen source changed: {name}")
    return item


def cfg(stress=None, interval=60):
    base = MicroBacktestConfig(signal_interval_minutes=interval, equity_interval_minutes=60,
                               execution_bar_minutes=1, periods_per_year=8760,
                               conservative_protection=True, taker_fee_bps=2.4,
                               base_slippage_bps=1, impact_bps=8)
    if stress == "double_cost":
        return replace(base, taker_fee_bps=4.8, base_slippage_bps=3, impact_bps=16)
    return base


def profile_signal(label, data, start):
    if label == "V4.4.3":
        p = json.loads(Path("configs/v4_4_3_params.json").read_text())["params"]
        return generate_v443_signals(data, V443Params(**p)), 60
    if label == "V4.4.2":
        p = json.loads(Path("configs/v4_4_2_params.json").read_text())["params"]
        return generate_v442_signals(data, V442Params(**p)), 60
    return build_signals(data, V441Params(), "V4_1_3", start)


def run(label, period, stress=None):
    start, end = {"extension": ("2026-08-01", "2026-09-01"),
                  "recent": ("2024-01-01", "2026-08-01"),
                  "known_late": ("2025-07-15", "2026-08-01")}[period]
    if period == "extension":
        data, funding, minute = extension_inputs()
        batches = [minute]
    else:
        data = pd.read_pickle("data/v441/hourly.pkl")
        funding = pd.read_pickle("data/v441/funding.pkl")
        batches = minute_batches(Path("data/v441"), start, end)
    signal, interval = profile_signal(label, data, start)
    a = pd.Timestamp(start, tz="UTC")
    signal = signal.loc[signal.index >= a - pd.Timedelta(minutes=interval)]
    result = run_micro_backtest(signal, batches, funding, cfg(stress, interval))
    row = {"version": "V4.4.3", "strategy": label, "period": period,
           "stress": stress or "base", **metrics(result.equity, result.trades),
           "execution": asdict(cfg(stress, interval)), "rebate": REBATE,
           "execution_metrics": result.metrics}
    dest = OUT / f"{label.replace('.', '')}__{period}__{stress or 'base'}"
    dest.mkdir(parents=True, exist_ok=True)
    result.equity.to_csv(dest / "equity.csv")
    result.trades.to_csv(dest / "trades.csv", index=False)
    result.fills.to_csv(dest / "fills.csv", index=False)
    result.funding.to_csv(dest / "funding.csv", index=False)
    result.liquidations.to_csv(dest / "liquidations.csv", index=False)
    (dest / "metrics.json").write_text(json.dumps(row, indent=2) + "\n")
    print(label, period, stress or "base", round(row["total_return"], 4), round(row["sharpe"], 4), row["cycles"], flush=True)
    return row


def main():
    lock()
    cases = []
    for label in ["V4.4.3", "V4.4.2", "V4_1_3"]:
        cases.append(run(label, "extension"))
    for label in ["V4.4.3", "V4.4.2", "V4_1_3"]:
        cases.append(run(label, "known_late"))
    for label in ["V4.4.3", "V4.4.2", "V4_1_3"]:
        cases.append(run(label, "recent", "double_cost"))
    report = {"version": "V4.4.3", "baseline": "V4.4.2", "rebate": REBATE,
              "freeze": json.loads((OUT / "freeze.json").read_text()), "cases": cases,
              "extension_coverage": json.loads((Path("reports/v4_4_1_round2") / "extension_coverage.json").read_text()),
              "status": "frozen_candidate", "promote_to_default": False,
              "note": "August is one month and five selected-strategy cycles; it is not sufficient for robust inference."}
    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    pd.DataFrame(cases).to_csv(OUT / "summary.csv", index=False)


if __name__ == "__main__":
    main()
