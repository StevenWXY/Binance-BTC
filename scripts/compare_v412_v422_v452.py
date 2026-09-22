"""Compare V4.1.2, V4.2.2 and V4.5.2 under one dated, causal audit.

The comparison uses the existing 40%-rebate V4.1.2 minute audit, a freshly
replayed 40%-rebate V4.2.2 run, and the frozen V4.5.2 run sliced at the same
2026-08-01 boundary. It also records entry/fill frequency and performs real
data prefix checks plus a static future-value scan.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

from btc_regime.v42 import generate_neutral_sleeve
from btc_regime.v43 import V43Params, generate_v43_signals
from btc_regime.v441_research import daily_equity
from btc_regime.v452 import V452Params
from evaluate_v441_round2 import extension_inputs
from evaluate_v452 import ROOT as V452_ROOT
from research_v452 import profile_signal


ROOT = Path(__file__).resolve().parents[1]
START = pd.Timestamp("2020-01-01", tz="UTC")
END = pd.Timestamp("2026-08-01", tz="UTC")
RECENT = pd.Timestamp("2024-01-01", tz="UTC")
AUDIT = pd.Timestamp("2026-01-15", tz="UTC")


def equity_from_csv(path: Path, column: str | None = None) -> pd.Series:
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True)
    if column is None:
        column = frame.columns[0]
    return frame[column].astype(float).sort_index()


def metric(equity: pd.Series, start: pd.Timestamp = START, end: pd.Timestamp = END) -> dict[str, float]:
    e = equity.loc[(equity.index >= start) & (equity.index <= end)]
    d = daily_equity(e)
    ret = d.pct_change().dropna()
    years = max((e.index[-1] - e.index[0]).total_seconds() / (365.25 * 86400), 1 / 365.25)
    sd = ret.std(ddof=1)
    return {
        "total_return": float(e.iloc[-1] / e.iloc[0] - 1),
        "cagr": float((e.iloc[-1] / e.iloc[0]) ** (1 / years) - 1),
        "sharpe": float(ret.mean() / sd * np.sqrt(365.25)) if sd > 0 else 0.0,
        "annualized_volatility": float(sd * np.sqrt(365.25)),
        "max_drawdown": float((e / e.cummax() - 1).min()),
        "days": int(len(ret)),
    }


def load_trades(path: Path) -> pd.DataFrame:
    t = pd.read_csv(path)
    for col in ["entry_time", "exit_time"]:
        if col in t:
            t[col] = pd.to_datetime(t[col], utc=True)
    if "entry_time" in t and "exit_time" in t:
        t["holding_hours"] = (t.exit_time - t.entry_time).dt.total_seconds() / 3600
    return t


def frequency(trades: pd.DataFrame, fills_path: Path | None, start=START, end=END) -> dict[str, float]:
    t = trades.loc[(trades.exit_time >= start) & (trades.exit_time < end)].copy() if len(trades) else trades
    years = (end - start).total_seconds() / (365.25 * 86400)
    entries = t.loc[(t.entry_time >= start) & (t.entry_time < end)] if len(t) else t
    fills = pd.DataFrame()
    if fills_path and fills_path.exists():
        fills = pd.read_csv(fills_path)
        if len(fills) and "timestamp" in fills:
            fills["timestamp"] = pd.to_datetime(fills.timestamp, utc=True)
            fills = fills.loc[(fills.timestamp >= start) & (fills.timestamp < end)]
    gap = entries.entry_time.sort_values().diff().dt.total_seconds() / 86400 if len(entries) else pd.Series(dtype=float)
    return {
        "cycles": int(len(t)),
        "cycles_per_year": float(len(t) / years),
        "entries_per_month": float(len(entries) / (years * 12)),
        "fills": int(len(fills)),
        "fills_per_year": float(len(fills) / years),
        "median_holding_hours": float(t.holding_hours.median()) if len(t) else 0.0,
        "median_entry_gap_days": float(gap.dropna().median()) if len(gap.dropna()) else 0.0,
        "short_cycles": int((t.side == "short").sum()) if "side" in t else 0,
        "long_cycles": int((t.side == "long").sum()) if "side" in t else 0,
    }


def window_payload(equity: pd.Series, trades: pd.DataFrame, fills: Path | None) -> dict[str, object]:
    return {
        "full": {"metrics": metric(equity), "frequency": frequency(trades, fills)},
        "post2024": {"metrics": metric(equity, RECENT), "frequency": frequency(trades, fills, RECENT)},
        "post2026_01_15": {"metrics": metric(equity, AUDIT), "frequency": frequency(trades, fills, AUDIT)},
    }


def static_future_scan() -> dict[str, object]:
    files = [ROOT / "src/btc_regime/strategy.py", ROOT / "src/btc_regime/v42.py",
             ROOT / "src/btc_regime/v43.py", ROOT / "src/btc_regime/v452.py",
             ROOT / "src/btc_regime/v453.py"]
    patterns = {
        "negative_shift": r"\.shift\(\s*-",
        "backfill": r"\.(?:bfill|backfill)\s*\(",
        "centered_rolling": r"rolling\([^\n]*center\s*=\s*True",
        "negative_pct_change": r"pct_change\(\s*-",
    }
    hits = []
    for path in files:
        text = path.read_text()
        for name, pattern in patterns.items():
            for match in re.finditer(pattern, text):
                line = text.count("\n", 0, match.start()) + 1
                hits.append({"file": str(path.relative_to(ROOT)), "line": line, "pattern": name})
    return {"files": [str(p.relative_to(ROOT)) for p in files], "forbidden_future_patterns": hits,
            "status": "pass" if not hits else "review_required"}


def aggregate_4h(data: pd.DataFrame) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last",
           "volume": "sum", "quote_volume": "sum", "funding_rate": "sum", "funding_event": "any"}
    out = data.resample("4h", label="left", closed="left").agg(agg)
    counts = data.close.resample("4h", label="left", closed="left").count()
    return out.loc[counts.eq(4)].copy()


def real_prefix_audit() -> dict[str, object]:
    data, funding_aug, _ = extension_inputs()
    cuts = [pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC"),
            pd.Timestamp("2025-07-01", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC")]
    results = []
    v452_params = V452Params()
    v452_full = profile_signal(data, {"kind": "v452", "params": v452_params.to_dict()})
    four_full = aggregate_4h(data)
    v43_1 = generate_v43_signals(four_full, V43Params(**json.loads((ROOT / "configs/v4_1_2_params.json").read_text())))
    v43_2 = generate_v43_signals(four_full, V43Params(**json.loads((ROOT / "configs/v4_2_2_params.json").read_text())))
    funding_full = pd.concat([pd.read_pickle(ROOT / "data/v441/funding.pkl"), funding_aug]).sort_index()
    neutral_full = generate_neutral_sleeve(funding_full)
    for cut in cuts:
        def same(a, b, cols):
            aa, bb = a.loc[a.index < cut, cols], b.loc[b.index < cut, cols]
            if aa.shape != bb.shape or not aa.index.equals(bb.index):
                return False
            return bool(np.allclose(aa.select_dtypes(include=["number"]).fillna(0),
                                    bb.select_dtypes(include=["number"]).fillna(0), atol=1e-10) and
                        all(aa[c].astype(str).equals(bb[c].astype(str)) for c in aa.columns if c not in aa.select_dtypes(include=["number"]).columns))
        prefix_hour = data.loc[data.index < cut]
        p452 = profile_signal(prefix_hour, {"kind": "v452", "params": v452_params.to_dict()})
        prefix_four = aggregate_4h(prefix_hour)
        p41 = generate_v43_signals(prefix_four, V43Params(**json.loads((ROOT / "configs/v4_1_2_params.json").read_text())))
        p42 = generate_v43_signals(prefix_four, V43Params(**json.loads((ROOT / "configs/v4_2_2_params.json").read_text())))
        pfund = funding_full.loc[funding_full.index < cut]
        pneutral = generate_neutral_sleeve(pfund)
        results.append({"cut": cut.isoformat(),
                        "v4_5_2_signal_prefix_equal": same(p452, v452_full, ["signal", "stop_price", "take_profit_price", "cycle_id"]),
                        "v4_1_2_signal_prefix_equal": same(p41, v43_1, ["signal", "stop_price", "take_profit_price"]),
                        "v4_2_2_signal_prefix_equal": same(p42, v43_2, ["signal", "stop_price", "take_profit_price"]),
                        "v4_2_neutral_prefix_equal": same(pneutral, neutral_full, ["active", "neutral_return", "neutral_equity"])} )
    return {"cuts": results, "status": "pass" if all(all(v for k, v in r.items() if k != "cut") for r in results) else "review_required"}


def overfit_audit() -> dict[str, object]:
    selection = json.loads((V452_ROOT / "minute_selection.json").read_text())
    ordered = sorted([r for r in selection if r["profile"]["selectable"]], key=lambda r: -r["score"])
    chosen = next(r for r in ordered if r["profile"]["id"] == "b022")
    score_gap = float(chosen["score"] - ordered[1]["score"])
    b022 = json.loads((V452_ROOT / "continuous/b022__base/report.json").read_text())
    years = {y: {k: v[k] for k in ["total_return", "sharpe", "max_drawdown", "cycles", "short_cycles"]}
             for y, v in b022["yearly"].items()}
    return {
        "selection_rows": len(selection),
        "selectable_rows": len(ordered),
        "winner": "b022",
        "winner_score": chosen["score"],
        "next_score": ordered[1]["score"],
        "winner_score_gap": score_gap,
        "top_profiles": [{"id": r["profile"]["id"], "score": r["score"],
                          "recent_return": r["windows"]["recent"]["total_return"],
                          "recent_sharpe": r["windows"]["recent"]["sharpe"]} for r in ordered[:8]],
        "yearly_fixed_parameter_audit": years,
        "warnings": [
            "All August 2026 data and earlier V4.5 rounds were previously viewed; this is not blind OOS.",
            "The winner score gap is small relative to the number of tried profiles; no multiple-testing correction was applied.",
            "Recent gains are concentrated in 2024-2026; 2020-2023 short sleeve contribution is negative.",
        ],
        "status": "selection_bias_possible",
    }


def main() -> None:
    v41_root = ROOT / "reports/v4_1_3_40/V4_1_2_baseline"
    v42_root = ROOT / "reports/v4_2_rebate40"
    v452_root = V452_ROOT / "continuous/b022__base"
    v453_root = ROOT / "reports/v4_5_3"
    strategies = {
        "V4.1.2": (equity_from_csv(v41_root / "micro_equity.csv"), load_trades(v41_root / "micro_trades.csv"), v41_root / "micro_fills.csv"),
        "V4.2.2": (equity_from_csv(v42_root / "combined_maker_equity.csv", "combined_equity"), load_trades(v42_root / "direction_maker_trades.csv"), v42_root / "direction_maker_fills.csv"),
        "V4.5.2": (equity_from_csv(v452_root / "equity.csv", "equity"), load_trades(v452_root / "trades.csv"), v452_root / "fills.csv"),
        "V4.5.3": (equity_from_csv(v453_root / "b022_maker/equity.csv"), load_trades(v453_root / "b022_maker/trades.csv"), v453_root / "V4.5.3__base/fills.csv"),
    }
    payload = {"window": [START.isoformat(), END.isoformat()], "recent_window": [RECENT.isoformat(), END.isoformat()],
               "execution": {"published_taker_bps": 4., "rebate_fraction": .4, "effective_taker_bps": 2.4,
                             "published_maker_bps": .2, "effective_maker_bps": .12,
                             "base_slippage_bps": 1., "impact_bps": 8., "max_minute_participation": .02},
               "strategies": {}, "future_function_audit": {"static": static_future_scan(), "real_data_prefix": real_prefix_audit()},
               "overfit_audit": overfit_audit(),
               "limitations": ["V4.1.2 and V4.2.2 use the archived 2020-01 to 2026-07 1m coverage; V4.5.2 is sliced at the same boundary.",
                               "V4.2.2 frequency counts direction cycles; its funding-neutral sleeve has separate state changes, not exchange trade cycles.",
                               "Maker fills are deterministic OHLC-touch proxies and do not model queue position."]}
    for name, (equity, trades, fills) in strategies.items():
        payload["strategies"][name] = window_payload(equity, trades, fills)
    # V4.2 neutral sleeve frequency is an account-level activity diagnostic.
    neutral = pd.read_csv(ROOT / "reports/v4_2_rebate40/neutral_schedule.csv")
    neutral["timestamp"] = pd.to_datetime(neutral.timestamp, utc=True, format="mixed")
    neutral = neutral.loc[(neutral.timestamp >= START) & (neutral.timestamp < END)]
    payload["strategies"]["V4.2.2"]["full"]["frequency"]["neutral_state_changes"] = int(neutral.state_changed.sum())
    payload["strategies"]["V4.2.2"]["post2024"]["frequency"]["neutral_state_changes"] = int(neutral.loc[neutral.timestamp >= RECENT].state_changed.sum())
    out = ROOT / "reports/v4_5_2_v412_v422_comparison"
    out.mkdir(exist_ok=True)
    (out / "report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=float) + "\n")
    rows = []
    for name, windows in payload["strategies"].items():
        for window, values in windows.items():
            rows.append({"strategy": name, "window": window, **values["metrics"], **values["frequency"]})
    pd.DataFrame(rows).to_csv(out / "comparison.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
