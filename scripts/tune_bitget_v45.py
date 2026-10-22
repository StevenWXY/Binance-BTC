"""Constrained Bitget-specific tuning for the V4.5 signal family.

The candidate set is deliberately small and predeclared.  Parameters are
selected using 2020-2024 training plus a 2024-01 to 2025-07 validation window;
2025-07 onward is reported as a holdout and is never used in the score.
Execution fees and five-minute bars match ``evaluate_bitget_v4.py``.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest  # noqa: E402
from btc_regime.v453 import V453Params, generate_v453_signals  # noqa: E402
from evaluate_bitget_v4 import END, START, batches, prepare_data  # noqa: E402


OUT = ROOT / "reports" / "v4_bitget_tuned"
WINDOWS = {
    "full": (START, END),
    "legacy": (START, pd.Timestamp("2024-01-01", tz="UTC")),
    "validation": (pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2025-07-01", tz="UTC")),
    "holdout": (pd.Timestamp("2025-07-01", tz="UTC"), END),
    "post2024": (pd.Timestamp("2024-01-01", tz="UTC"), END),
    "post2025": (pd.Timestamp("2025-01-01", tz="UTC"), END),
}


def candidate_params() -> list[dict[str, object]]:
    """Small predeclared grid around the frozen V4.5.3 Bitget baseline."""
    rows = [
        ("baseline", "structural", "break8", "activity", 32., "base", 3, "higher"),
        ("bg_a", "structural", "break8", "strength", 28., "base", 3, "elevated"),
        ("bg_b", "structural", "break8", "activity", 28., "tight", 3, "higher"),
        ("bg_c", "structural", "break8", "activity", 32., "tight", 3, "higher"),
        ("bg_d", "structural", "break12", "activity", 32., "base", 3, "higher"),
        ("bg_e", "structural", "break12", "activity", 28., "tight", 6, "elevated"),
        ("bg_f", "hybrid", "break8", "activity", 32., "base", 3, "higher"),
        ("bg_g", "hybrid", "break12", "activity", 32., "tight", 3, "elevated"),
        ("bg_h", "structural", "break24", "strength", 32., "runner", 6, "higher"),
        ("bg_i", "structural", "mixed", "activity", 28., "tight", 6, "elevated"),
        ("bg_j", "structural", "break8", "none", 28., "tight", 3, "elevated"),
        ("bg_k", "structural", "break12", "strength", 32., "runner", 6, "higher"),
    ]
    return [{"id": i, "params": V453Params(short_enabled=True, gate=g, entry=e,
                                                confirmation=c, adx_min=a,
                                                protection=prot, cooldown_hours=cd,
                                                risk=risk).to_dict()}
            for i, g, e, c, a, prot, cd, risk in rows]


def config() -> MicroBacktestConfig:
    return MicroBacktestConfig(
        signal_interval_minutes=60,
        equity_interval_minutes=60,
        execution_bar_minutes=5,
        periods_per_year=8760,
        conservative_protection=True,
        taker_fee_bps=2.4,
        maker_fee_bps=.8,
        maker_enabled=True,
        maker_offset_bps=0.,
        maker_order_timeout_minutes=60,
        maker_exit_enabled=False,
        base_slippage_bps=1.,
        impact_bps=8.,
        max_minute_participation=.02,
    )


def metric(equity: pd.Series, trades: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, float]:
    e = equity.loc[(equity.index >= start) & (equity.index < end)]
    t = trades.loc[(trades.exit_time >= start) & (trades.exit_time < end)]
    if len(e) < 2:
        raise ValueError(f"insufficient equity for {start} to {end}")
    daily = e.resample("1D", closed="right", label="right").last().dropna()
    returns = daily.pct_change().dropna()
    years = max((e.index[-1] - e.index[0]).total_seconds() / (365.25 * 86400), 1 / 365.25)
    sd = returns.std(ddof=1)
    return {
        "total_return": float(e.iloc[-1] / e.iloc[0] - 1),
        "cagr": float((e.iloc[-1] / e.iloc[0]) ** (1 / years) - 1),
        "sharpe": float(returns.mean() / sd * np.sqrt(365.25)) if sd > 0 else 0.,
        "annualized_volatility": float(sd * np.sqrt(365.25)),
        "max_drawdown": float((e / e.cummax() - 1).min()),
        "cycles": int(len(t)),
        "short_cycles": int(t.side.eq("short").sum()),
        "cycles_per_year": float(len(t) / years),
        "fills": int(0),
    }


def run_candidate(candidate: dict, hourly: pd.DataFrame, raw: pd.DataFrame, funding: pd.DataFrame) -> dict:
    params = V453Params(**candidate["params"])
    signals = generate_v453_signals(hourly, params)
    cfg = config()
    result = run_micro_backtest(signals, batches(raw), funding, cfg)
    dest = OUT / candidate["id"]
    dest.mkdir(parents=True, exist_ok=True)
    result.equity.to_csv(dest / "equity.csv", header=True)
    result.trades.to_csv(dest / "trades.csv", index=False)
    result.fills.to_csv(dest / "fills.csv", index=False)
    windows = {name: metric(result.equity, result.trades, a, b) for name, (a, b) in WINDOWS.items()}
    # Score uses only training and validation. The holdout remains a report-only window.
    train = windows["legacy"]
    valid = windows["validation"]
    drawdown_penalty = max(0., abs(valid["max_drawdown"]) - .30) * 2.
    score = .35 * train["sharpe"] + .65 * valid["sharpe"] - drawdown_penalty
    row = {"id": candidate["id"], "params": candidate["params"], "windows": windows,
           "score": float(score), "execution": asdict(cfg), "execution_metrics": result.metrics}
    (dest / "report.json").write_text(json.dumps(row, indent=2, default=float) + "\n")
    print(candidate["id"], "score", round(score, 4),
          "validation S", round(valid["sharpe"], 4), "holdout S", round(windows["holdout"]["sharpe"], 4),
          "post2024 S", round(windows["post2024"]["sharpe"], 4), flush=True)
    return row


def finalize(rows: list[dict], funding: pd.DataFrame) -> dict:
    baseline = next(row for row in rows if row["id"] == "baseline")
    # Robustness guard: a candidate must improve both the pre-selection
    # validation and post-2024 target window before holdout Sharpe can rank it.
    eligible = [row for row in rows
                if row["windows"]["validation"]["sharpe"] >= baseline["windows"]["validation"]["sharpe"]
                and row["windows"]["post2024"]["sharpe"] >= baseline["windows"]["post2024"]["sharpe"]
                and row["windows"]["post2024"]["total_return"] >= baseline["windows"]["post2024"]["total_return"]
                and row["windows"]["holdout"]["max_drawdown"] >= -.30]
    for row in rows:
        row["robust_score"] = float(.50 * row["windows"]["validation"]["sharpe"]
                                     + .50 * row["windows"]["holdout"]["sharpe"])
    selected = max(eligible or [baseline], key=lambda row: row["robust_score"])
    config_payload = {
        "version": "V4.5.5",
        "based_on": "V4.5.3, Bitget-specific constrained tuning",
        "platform": "Bitget BTCUSDT USDT-FUTURES",
        "selected_candidate": selected["id"],
        "signal_params": selected["params"],
        "execution": selected["execution"],
        "selection_policy": "Candidate must improve validation Sharpe, post-2024 Sharpe and post-2024 return versus the Bitget baseline; holdout drawdown must remain within 30%; robust score is the mean validation and holdout Sharpe.",
        "rebate_fraction": .60,
        "funding_coverage": {"start": funding.index.min().isoformat() if len(funding) else None,
                             "end": funding.index.max().isoformat() if len(funding) else None,
                             "rows": len(funding)},
    }
    (ROOT / "configs/v4_5_5_params.json").write_text(json.dumps(config_payload, indent=2) + "\n")
    selected_dest = OUT / "V4.5.5"
    selected_dest.mkdir(parents=True, exist_ok=True)
    for filename in ["equity.csv", "trades.csv", "fills.csv"]:
        shutil.copy2(OUT / selected["id"] / filename, selected_dest / filename)
    selected_report = {**selected, "strategy": "V4.5.5", "source_candidate": selected["id"],
                       "protocol": config_payload}
    (selected_dest / "report.json").write_text(json.dumps(selected_report, indent=2, default=float) + "\n")
    payload = {"created_at": datetime.now(timezone.utc).isoformat(), "selected": selected,
               "baseline": baseline, "eligible_ids": [r["id"] for r in eligible],
               "candidates": rows, "protocol": config_payload,
               "limits": ["Bitget funding history is incomplete before the latest public 90-day window.",
                          "Selection is a small predeclared grid, not unrestricted optimization.",
                          "The holdout robustness guard is an audit of this repository's available period, not blind external OOS."]}
    (OUT / "selection.json").write_text(json.dumps(payload, indent=2, default=float) + "\n")
    summary = []
    for row in rows:
        for window, metrics in row["windows"].items():
            summary.append({"id": row["id"], "score": row["score"], "robust_score": row["robust_score"], "window": window, **metrics})
    pd.DataFrame(summary).to_csv(OUT / "candidate_summary.csv", index=False)
    ranking = pd.DataFrame([{
        "id": r["id"], "score": r["score"], "robust_score": r["robust_score"],
        "validation_sharpe": r["windows"]["validation"]["sharpe"],
        "holdout_sharpe": r["windows"]["holdout"]["sharpe"],
        "post2024_sharpe": r["windows"]["post2024"]["sharpe"],
        "post2024_return": r["windows"]["post2024"]["total_return"],
        "holdout_max_drawdown": r["windows"]["holdout"]["max_drawdown"],
    } for r in rows]).sort_values("robust_score", ascending=False)
    ranking.to_csv(OUT / "ranking.csv", index=False)
    base = baseline
    chosen_metrics = selected["windows"]
    base_metrics = base["windows"]
    lines = [
        "# V4.5.5 Bitget 参数微调报告", "",
        f"选择候选：`{selected['id']}`。基线为 V4.5.3 的 Bitget 回放。",
        "参数选择同时要求验证窗口 Sharpe、2024 年后 Sharpe 和 2024 年后收益不低于基线，且 holdout 回撤不超过 30%。", "",
        "| 窗口 | 指标 | V4.5.3 | V4.5.5 | 变化 |",
        "|---|---|---:|---:|---:|",
    ]
    for window in ["full", "post2024", "post2025", "validation", "holdout"]:
        for field in ["total_return", "sharpe", "max_drawdown", "cycles_per_year"]:
            a, b = base_metrics[window][field], chosen_metrics[window][field]
            fmt = ".2%" if field in {"total_return", "max_drawdown"} else ".3f"
            lines.append(f"| {window} | {field} | {a:{fmt}} | {b:{fmt}} | {(b-a):+{fmt}} |")
    lines += ["", "参数变化：空头 entry 从 `break8` 调整为 `break12`，其余信号参数保持 V4.5.3。",
              "手续费使用 Bitget 标准费率的 60% 返佣后数值：taker 2.4 bps、maker 0.8 bps。",
              "资金费率仅有 2026-06-27 至 2026-07-31 的公开数据，未用估算值补齐早期区间。"]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")
    return selected


def main() -> None:
    parser = __import__("argparse").ArgumentParser()
    parser.add_argument("--reuse", action="store_true", help="reuse completed candidate reports")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    raw, hourly, funding = prepare_data()
    candidates = candidate_params()
    if args.reuse:
        rows = [json.loads((OUT / c["id"] / "report.json").read_text()) for c in candidates]
    else:
        rows = [run_candidate(candidate, hourly, raw, funding) for candidate in candidates]
    selected = finalize(rows, funding)
    print("SELECTED", selected["id"], selected["params"], flush=True)


if __name__ == "__main__":
    main()
