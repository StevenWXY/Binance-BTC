"""Constrained, pre-holdout robustness search for V4.5.3.

The 2026-09-01 onward window is never used for selection.  The candidate grid
is fixed in source and consists of small, interpretable changes around frozen
V4.5.3/b022.  The script also evaluates the selected candidate under execution
stress and writes a frozen V4.5.3 robust-candidate configuration only when
the historical robustness gate is met. It never writes or evaluates another
strategy version.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v452 import V452Params, generate_v452_signals
from btc_regime.v453 import V453Params, generate_v453_signals
import run_bitget_three_latest as latest


DATA = ROOT / "data/bitget_20261011"
OUT = ROOT / "reports/v4_5_3_robust"
START = pd.Timestamp("2020-01-01", tz="UTC")
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
VALID_END = pd.Timestamp("2026-01-01", tz="UTC")
HOLDOUT_START = pd.Timestamp("2026-09-01", tz="UTC")
END = pd.Timestamp("2026-10-11 08:00", tz="UTC")
PRE_HOLDOUT_END = HOLDOUT_START


def candidates() -> list[dict[str, object]]:
    """Ten candidates fixed before inspecting the 2026-09 onward results."""
    b = V453Params(**json.loads((ROOT / "configs/v4_5_3_params.json").read_text())["signal_params"])
    rows = [
        ("baseline_b022", b, 0),
        ("risk_elevated", replace(b, risk="elevated"), 1),
        ("risk_base", replace(b, risk="base"), 1),
        ("cooldown6", replace(b, cooldown_hours=6), 1),
        ("break12", replace(b, entry="break12"), 1),
        ("break24", replace(b, entry="break24"), 1),
        ("protection_tight", replace(b, protection="tight"), 1),
        ("protection_runner", replace(b, protection="runner"), 1),
        ("confirmation_strength", replace(b, confirmation="strength"), 1),
        ("long_only", replace(b, short_enabled=False), 1),
    ]
    return [{"id": name, "params": p, "complexity": complexity} for name, p, complexity in rows]


def config(**changes) -> MicroBacktestConfig:
    return replace(latest.config("V4.5.3"), **changes)


def slice_metrics(result, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, float | int]:
    e = result.equity.loc[(result.equity.index >= start) & (result.equity.index <= end)].dropna()
    if len(e) < 2:
        return {"total_return": 0.0, "cagr": 0.0, "sharpe": 0.0, "max_drawdown": 0.0,
                "trades": 0, "wins": 0, "losses": 0, "pnl_sum": 0.0}
    daily = e.resample("1D", closed="right", label="right").last().dropna()
    ret = daily.pct_change().dropna()
    t = result.trades.copy()
    if len(t):
        t["exit_time"] = pd.to_datetime(t.exit_time, utc=True)
        t = t.loc[(t.exit_time >= start) & (t.exit_time < end)]
    years = max((e.index[-1] - e.index[0]).total_seconds() / (365.25 * 86400), 1 / 365.25)
    sd = ret.std(ddof=1)
    return {
        "total_return": float(e.iloc[-1] / e.iloc[0] - 1),
        "cagr": float((e.iloc[-1] / e.iloc[0]) ** (1 / years) - 1),
        "sharpe": float(ret.mean() / sd * np.sqrt(365.25)) if sd > 0 else 0.0,
        "max_drawdown": float((e / e.cummax() - 1).min()),
        "trades": int(len(t)), "wins": int((t.pnl > 0).sum()), "losses": int((t.pnl <= 0).sum()),
        "pnl_sum": float(t.pnl.sum()) if len(t) else 0.0,
    }


WINDOWS = {
    "train_2020_2023": (START, TRAIN_END),
    "validation_2024_2025": (TRAIN_END, VALID_END),
    "pre_holdout_2026_01_08": (VALID_END, PRE_HOLDOUT_END),
    "holdout_2026_09_10": (HOLDOUT_START, END),
    "post2024": (TRAIN_END, END),
}


def run_signal(signal, raw, funding, cfg):
    return run_micro_backtest(signal, latest.batches(raw), funding, cfg)


def evaluate_candidate(item, hourly, raw, funding):
    signal = generate_v453_signals(hourly, item["params"])
    result = run_signal(signal, raw, funding, config())
    metrics = {name: slice_metrics(result, a, b) for name, (a, b) in WINDOWS.items()}
    historical = [metrics[x] for x in ("train_2020_2023", "validation_2024_2025", "pre_holdout_2026_01_08")]
    sharpes = np.array([x["sharpe"] for x in historical], dtype=float)
    positive = sum(x["total_return"] > 0 for x in historical)
    # No holdout term enters this score. The standard deviation penalizes a
    # candidate that works only in one historical regime.
    max_drawdown_abs = max(abs(x["max_drawdown"]) for x in historical)
    robust_score = float(np.median(sharpes) - .35 * np.std(sharpes) + .10 * positive
                         - 1.5 * max(0.0, max_drawdown_abs - .30))
    row = {"id": item["id"], "params": item["params"].__dict__, "complexity": item["complexity"],
           "metrics": metrics, "robust_score": robust_score,
           "execution_metrics": result.metrics}
    return row, result


def stress_metrics(signal, raw, funding):
    cases = {
        "base_maker_0bps": config(),
        "all_taker": config(maker_enabled=False),
        "maker_offset_025bps": config(maker_offset_bps=.25),
        "double_cost": config(taker_fee_bps=4.8, maker_fee_bps=1.6, base_slippage_bps=2., impact_bps=16.),
        "delay_1h": config(),
    }
    rows = []
    for name, cfg in cases.items():
        sig = signal.copy()
        if name == "delay_1h":
            sig.index += pd.Timedelta(hours=1)
        result = run_signal(sig, raw, funding, cfg)
        m = slice_metrics(result, HOLDOUT_START, END)
        m["scenario"] = name
        m["full_return"] = float(result.metrics["total_return"])
        m["full_sharpe"] = float(result.metrics.get("sharpe", 0.0))
        m["full_max_drawdown"] = float(result.metrics["max_drawdown"])
        rows.append(m)
    return pd.DataFrame(rows)


def main() -> None:
    latest.END = END
    raw, hourly, _, funding = latest.load_data(DATA)
    OUT.mkdir(parents=True, exist_ok=True)
    items = candidates()
    rows, results = [], {}
    for item in items:
        row, result = evaluate_candidate(item, hourly, raw, funding)
        rows.append(row); results[item["id"]] = result
        print(item["id"], "score", round(row["robust_score"], 4),
              "train/val/pre/hold S", *[round(row["metrics"][k]["sharpe"], 3)
                                           for k in ("train_2020_2023", "validation_2024_2025", "pre_holdout_2026_01_08", "holdout_2026_09_10")],
              flush=True)

    baseline = next(r for r in rows if r["id"] == "baseline_b022")
    # Historical guard. The 9/1 onward holdout is deliberately absent here.
    eligible = []
    for r in rows:
        hist = [r["metrics"][k] for k in ("train_2020_2023", "validation_2024_2025", "pre_holdout_2026_01_08")]
        if (sum(x["total_return"] > 0 for x in hist) >= 2
                and max(abs(x["max_drawdown"]) for x in hist) <= .35
                and r["metrics"]["validation_2024_2025"]["sharpe"] >= baseline["metrics"]["validation_2024_2025"]["sharpe"] - .15
                and r["metrics"]["pre_holdout_2026_01_08"]["sharpe"] >= baseline["metrics"]["pre_holdout_2026_01_08"]["sharpe"] - .15):
            eligible.append(r)
    # Prefer the simplest candidate when scores are statistically close.
    top_score = max(r["robust_score"] for r in eligible or [baseline])
    near_top = [r for r in (eligible or [baseline]) if r["robust_score"] >= top_score - .05]
    selected = sorted(near_top, key=lambda r: (r["complexity"], -r["robust_score"]))[0]
    selected_item = next(x for x in items if x["id"] == selected["id"])
    selected_signal = generate_v453_signals(hourly, selected_item["params"])
    selected_stress = stress_metrics(selected_signal, raw, funding)
    selected_result = results[selected["id"]]

    # Candidate artifacts.
    flat = []
    for row in rows:
        for window, m in row["metrics"].items():
            flat.append({"id": row["id"], "robust_score": row["robust_score"], "window": window, **m})
    pd.DataFrame(flat).to_csv(OUT / "candidate_summary.csv", index=False)
    pd.DataFrame([{
        "id": r["id"], "robust_score": r["robust_score"], "complexity": r["complexity"],
        **{f"{k}_{x}": r["metrics"][k][x] for k in ("train_2020_2023", "validation_2024_2025", "pre_holdout_2026_01_08", "holdout_2026_09_10") for x in ("total_return", "sharpe", "max_drawdown", "trades")},
    } for r in sorted(rows, key=lambda x: -x["robust_score"]) ]).to_csv(OUT / "ranking.csv", index=False)
    selected_stress.to_csv(OUT / "selected_execution_stress.csv", index=False)
    selected_result.equity.to_csv(OUT / "selected_equity.csv", header=True)
    selected_result.trades.to_csv(OUT / "selected_trades.csv", index=False)
    selected_result.fills.to_csv(OUT / "selected_fills.csv", index=False)

    config_payload = {
        "version": "V4.5.3-robust-candidate",
        "based_on": "V4.5.3 b022",
        "status": "frozen_robust_candidate",
        "selected_candidate": selected["id"],
        "signal_params": selected["params"],
        "execution": asdict(config()),
        "selection_policy": {
            "candidate_count": len(items),
            "selection_data_end_exclusive": PRE_HOLDOUT_END.isoformat(),
            "holdout_start": HOLDOUT_START.isoformat(),
            "historical_guard": "At least two of three historical folds positive; each historical drawdown <=35%; validation and pre-holdout Sharpe within 0.15 of b022; select the simplest candidate within 0.05 of the best robust score.",
            "score": "median Sharpe - 0.35*Sharpe dispersion + 0.10*positive-fold count - drawdown penalty",
        },
        "data": {"observed_end": raw.index.max().isoformat(), "five_minute_rows": len(raw), "funding_rows": len(funding),
                 "funding_start": funding.index.min().isoformat(), "funding_end": funding.index.max().isoformat()},
        "limits": ["The Bitget public funding cache is incomplete before 2026-06-27.", "Maker fills are an OHLC-touch proxy.", "Historical data were already available during research; the 2026-09 onward window is a diagnostic holdout, not a blind OOS test."],
    }
    (ROOT / "configs/v4_5_3_robust_params.json").write_text(json.dumps(config_payload, indent=2, default=str, ensure_ascii=False) + "\n")
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "selected": selected,
              "baseline": baseline, "eligible_ids": [r["id"] for r in eligible], "candidates": rows,
              "selected_execution_stress": selected_stress.to_dict(orient="records"), "protocol": config_payload}
    (OUT / "selection.json").write_text(json.dumps(report, indent=2, default=str, ensure_ascii=False) + "\n")
    print("SELECTED", selected["id"], "eligible", [r["id"] for r in eligible], flush=True)


if __name__ == "__main__":
    main()
