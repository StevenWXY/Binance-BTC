"""Test a fixed, causal robustness overlay on the frozen V4.5.2 signal.

This is an audit, not a new search over dates: b022 signal timing, stops,
entries and exits stay unchanged. The only candidates are predeclared sizing
overlays that use completed-candle ADX and turnover.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from itertools import chain
import json
from pathlib import Path

import pandas as pd

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v441_research import metrics
from btc_regime.v441_r2 import features
from btc_regime.v452 import V452Params, generate_v452_signals
from evaluate_v441 import minute_batches
from evaluate_v441_round2 import extension_inputs
from evaluate_v444 import window_metrics
from research_v452 import ROOT


OUT = ROOT.parent / "v4_5_3"
PARAMS = V452Params()
END = pd.Timestamp("2026-09-01", tz="UTC")


def candidates():
    return [
        {"id": "b022_control", "mode": "control"},
        {"id": "b022_maker", "mode": "maker", "offset": 0.0},
        {"id": "b022_maker025", "mode": "maker", "offset": 0.25},
        {"id": "b022_maker05", "mode": "maker", "offset": 0.5},
        {"id": "adaptive_adx36", "mode": "adx", "threshold": 36.0},
        {"id": "adaptive_adx40", "mode": "adx", "threshold": 40.0},
        {"id": "adaptive_turnover13", "mode": "turnover", "threshold": 1.3},
        {"id": "adaptive_both", "mode": "both", "adx": 36.0, "turnover": 1.3},
    ]


def signal_for(data, item):
    signal = generate_v452_signals(data, PARAMS)
    if item["mode"] == "maker":
        return signal
    if item["mode"] == "control":
        return signal
    f = features(data)
    turnover = f.quote_volume / f.quote_volume.shift().rolling(24, min_periods=24).median()
    strong = pd.Series(True, index=data.index)
    if item["mode"] in {"adx", "both"}:
        strong &= f.adx4 >= item.get("threshold", item.get("adx", 36.0))
    if item["mode"] in {"turnover", "both"}:
        strong &= turnover >= item.get("threshold", item.get("turnover", 1.3))
    short = signal.signal.lt(0)
    # Higher size only in the stronger completed-candle state; all other
    # b022 short targets are reduced by 1.75 / 2.0, with stops unchanged.
    scale = pd.Series(1.75 / 2.0, index=data.index)
    scale.loc[strong] = 1.0
    signal.loc[short, "signal"] *= scale.loc[short]
    return signal


def run(item):
    data, funding_aug, extension = extension_inputs()
    funding = pd.concat([pd.read_pickle("data/v441/funding.pkl"), funding_aug]).sort_index()
    signal = signal_for(data, item)
    cfg = MicroBacktestConfig(signal_interval_minutes=60, equity_interval_minutes=60,
                              periods_per_year=8760, conservative_protection=True,
                              taker_fee_bps=2.4, base_slippage_bps=1, impact_bps=8,
                              maker_enabled=item["mode"] == "maker", maker_fee_bps=.12,
                              maker_offset_bps=item.get("offset", 0.0), maker_order_timeout_minutes=60,
                              maker_exit_enabled=False)
    batches = chain(minute_batches(Path("data/v441"), "2020-01-01", "2026-08-01"), [extension])
    result = run_micro_backtest(signal, batches, funding, cfg)
    windows = {name: window_metrics(result.equity, result.trades, a, b)
               for name, (a, b) in {"full": ("2020-01-01", "2026-09-01"),
                                    "recent": ("2024-01-01", "2026-09-01"),
                                    "recent_jul": ("2024-01-01", "2026-08-01"),
                                    "later": ("2026-01-15", "2026-09-01")}.items()}
    row = {"item": item, "metrics": metrics(result.equity, result.trades), "windows": windows,
           "trades": int(len(result.trades)), "shorts": int((result.trades.side == "short").sum())}
    dest = OUT / item["id"]
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "report.json").write_text(json.dumps(row, indent=2) + "\n")
    result.equity.to_csv(dest / "equity.csv")
    result.trades.to_csv(dest / "trades.csv", index=False)
    print(item["id"], {k: {m: round(v[m], 5) for m in ["total_return", "sharpe", "max_drawdown"]}
                        for k, v in windows.items()}, flush=True)
    return row


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(run, candidates()))
    (OUT / "selection.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
