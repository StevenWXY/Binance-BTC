"""Continuous full-history V4.4.3 baseline from 2020 through the latest cache."""
from __future__ import annotations

import json
from dataclasses import asdict
from itertools import chain
from pathlib import Path

import pandas as pd

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v443 import V443Params, generate_v443_signals
from btc_regime.v441_research import metrics
from evaluate_v441 import minute_batches
from evaluate_v441_round2 import extension_inputs

OUT = Path("reports/v4_4_4/baseline_v443_full")


def main():
    data, funding_aug, extension = extension_inputs()
    funding = pd.concat([pd.read_pickle("data/v441/funding.pkl"), funding_aug]).sort_index()
    params = json.loads(Path("configs/v4_4_3_params.json").read_text())["params"]
    signal = generate_v443_signals(data, V443Params(**params))
    config = MicroBacktestConfig(signal_interval_minutes=60, equity_interval_minutes=60,
                                 execution_bar_minutes=1, periods_per_year=8760,
                                 conservative_protection=True, taker_fee_bps=2.4,
                                 base_slippage_bps=1, impact_bps=8)
    signal = signal.loc[signal.index >= pd.Timestamp("2020-01-01", tz="UTC") - pd.Timedelta(hours=1)]
    batches = minute_batches(Path("data/v441"), "2020-01-01", "2026-08-01")
    batches = chain(batches, [extension])
    result = run_micro_backtest(signal, batches, funding, config)
    OUT.mkdir(parents=True, exist_ok=True)
    result.equity.to_csv(OUT / "equity.csv")
    result.trades.to_csv(OUT / "trades.csv", index=False)
    result.fills.to_csv(OUT / "fills.csv", index=False)
    result.funding.to_csv(OUT / "funding.csv", index=False)
    result.liquidations.to_csv(OUT / "liquidations.csv", index=False)
    yearly = {}
    for year in range(2020, 2027):
        a = pd.Timestamp(f"{year}-01-01", tz="UTC")
        b = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        e = result.equity.loc[(result.equity.index >= a) & (result.equity.index < b)]
        t = result.trades.loc[(result.trades.exit_time >= a) & (result.trades.exit_time < b)]
        if len(e) > 24:
            yearly[str(year)] = metrics(e, t)
    report = {"version": "V4.4.4", "baseline": "V4.4.3", "window": ["2020-01-01", "2026-09-01"],
              "params": params, "rebate": {"published_taker_bps": 4., "rebate_fraction": .4,
                                               "effective_taker_bps": 2.4},
              "metrics": metrics(result.equity, result.trades), "yearly": yearly,
              "execution": asdict(config), "execution_metrics": result.metrics,
              "data_note": "Continuous account; August 2026 extension appended after July cache."}
    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["metrics"], flush=True)
    for year, row in yearly.items():
        print(year, row["total_return"], row["sharpe"], row["max_drawdown"], row["cycles"], flush=True)


if __name__ == "__main__":
    main()
