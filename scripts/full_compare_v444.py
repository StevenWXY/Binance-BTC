"""Run a continuous full-history comparison for registered V4.4.4 candidates."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from itertools import chain
from pathlib import Path

import pandas as pd

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v444 import V444Params, generate_v444_signals
from btc_regime.v441_research import metrics
from evaluate_v441 import minute_batches
from evaluate_v441_round2 import extension_inputs


def run(candidate):
    rows = json.loads(Path("reports/v4_4_4/screen.json").read_text())
    p = next(r["params"] for r in rows if r["id"] == candidate)
    data, funding_aug, extension = extension_inputs()
    funding = pd.concat([pd.read_pickle("data/v441/funding.pkl"), funding_aug]).sort_index()
    signal = generate_v444_signals(data, V444Params(**p))
    config = MicroBacktestConfig(signal_interval_minutes=60, equity_interval_minutes=60,
                                 execution_bar_minutes=1, periods_per_year=8760,
                                 conservative_protection=True, taker_fee_bps=2.4,
                                 base_slippage_bps=1, impact_bps=8)
    result = run_micro_backtest(signal, chain(minute_batches(Path("data/v441"), "2020-01-01", "2026-08-01"), [extension]), funding, config)
    out = Path("reports/v4_4_4") / f"{candidate}__full"
    out.mkdir(parents=True, exist_ok=True)
    result.equity.to_csv(out / "equity.csv")
    result.trades.to_csv(out / "trades.csv", index=False)
    yearly = {}
    for year in range(2020, 2027):
        a, b = pd.Timestamp(f"{year}-01-01", tz="UTC"), pd.Timestamp(f"{year+1}-01-01", tz="UTC")
        e = result.equity.loc[(result.equity.index >= a) & (result.equity.index < b)]
        t = result.trades.loc[(result.trades.exit_time >= a) & (result.trades.exit_time < b)]
        if len(e) > 24:
            yearly[str(year)] = metrics(e, t)
    report = {"candidate": candidate, "params": p, "metrics": metrics(result.equity, result.trades), "yearly": yearly, "execution": asdict(config)}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(candidate, report["metrics"], flush=True)
    for y, m in yearly.items():
        print(y, m["sharpe"], m["total_return"], m["max_drawdown"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", nargs="+", default=["r025"])
    args = parser.parse_args()
    for candidate in args.candidate:
        run(candidate)
