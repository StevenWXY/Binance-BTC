#!/usr/bin/env python3
"""Generate a trend quality diagnosis report for the current V71-live candidate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.data import load_market_data  # noqa: E402
from btc_regime.v71_live import V71LiveParams, generate_v71_live_signals  # noqa: E402


DEFAULT_PARAMS = ROOT / "configs/v71_final_candidate_params.json"
DEFAULT_LIVE_LIKE_DIR = ROOT / "reports/final_candidate_recovery_live_like_2020_2026_08_01"
DEFAULT_OUTPUT = ROOT / "reports/trend_quality_diagnosis_2020_2026_08_01"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _state_entry_events(frame: pd.DataFrame) -> pd.DataFrame:
    states = frame["v71_market_state"].astype(str)
    previous = states.shift(1).fillna("none")
    entries = frame.loc[states.ne(previous)].copy()
    entries["previous_state"] = previous.loc[entries.index].astype(str)
    entries["state"] = states.loc[entries.index].astype(str)
    entries["year"] = entries.index.year
    return entries[entries["state"].isin(["trend_up", "trend_down", "range"])].copy()


def _forward_metrics(entries: pd.DataFrame, frame: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    close = frame["close"]
    state = frame["v71_market_state"].astype(str)
    for ts, row in entries.iterrows():
        loc = frame.index.get_loc(ts)
        if isinstance(loc, slice):
            continue
        record: dict[str, object] = {
            "timestamp": ts.isoformat(),
            "year": int(row["year"]),
            "state": str(row["state"]),
            "previous_state": str(row["previous_state"]),
            "daily_bias": str(row.get("v71_daily_bias", "")),
            "tradability_state": str(row.get("v71_tradability_state", "")),
            "direction_context": str(row.get("v71_direction_context", "")),
            "close": float(row["close"]),
            "atr": float(row["atr"]) if np.isfinite(row["atr"]) else np.nan,
            "breakout_buffer_atr": float(row.get("v71_donchian_high", np.nan)),
        }
        for h in horizons:
            if loc + h >= len(frame):
                record[f"return_{h}"] = np.nan
                record[f"same_state_after_{h}"] = np.nan
                record[f"state_after_{h}"] = None
                record[f"max_abs_return_{h}"] = np.nan
                record[f"false_breakout_{h}"] = np.nan
                continue
            end_close = float(close.iloc[loc + h])
            forward_slice = close.iloc[loc + 1 : loc + h + 1]
            state_after = str(state.iloc[loc + h])
            simple_return = end_close / float(row["close"]) - 1.0
            max_abs = float((forward_slice / float(row["close"]) - 1.0).abs().max()) if not forward_slice.empty else 0.0
            same_state = state_after == str(row["state"])
            false_breakout = np.nan
            if row["state"] == "trend_up":
                barrier = max(float(row["v71_donchian_high"]), float(row["v71_close_breakout_high"])) + float(row["atr"]) * params.breakout_buffer_atr
                false_breakout = bool((forward_slice <= barrier).any()) or simple_return <= 0
            elif row["state"] == "trend_down":
                barrier = min(float(row["v71_donchian_low"]), float(row["v71_close_breakout_low"])) - float(row["atr"]) * params.breakout_buffer_atr
                false_breakout = bool((forward_slice >= barrier).any()) or simple_return >= 0
            record[f"return_{h}"] = simple_return
            record[f"same_state_after_{h}"] = same_state
            record[f"state_after_{h}"] = state_after
            record[f"max_abs_return_{h}"] = max_abs
            record[f"false_breakout_{h}"] = false_breakout
        rows.append(record)
    return pd.DataFrame(rows)


def _summarize_by_state(forward: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for state_name, sub in forward.groupby("state"):
        row: dict[str, object] = {"state": state_name, "entry_count": int(len(sub))}
        for h in horizons:
            returns = pd.to_numeric(sub[f"return_{h}"], errors="coerce").dropna()
            row[f"avg_return_{h}"] = float(returns.mean()) if not returns.empty else np.nan
            row[f"median_return_{h}"] = float(returns.median()) if not returns.empty else np.nan
            if state_name == "trend_up":
                hit = (returns > 0).mean() if not returns.empty else np.nan
            elif state_name == "trend_down":
                hit = (returns < 0).mean() if not returns.empty else np.nan
            else:
                hit = (returns.abs() <= 0.03).mean() if not returns.empty else np.nan
            row[f"quality_hit_rate_{h}"] = float(hit) if not pd.isna(hit) else np.nan
            same_state = pd.Series(sub[f"same_state_after_{h}"]).dropna()
            row[f"same_state_rate_{h}"] = float(same_state.mean()) if not same_state.empty else np.nan
            if state_name in {"trend_up", "trend_down"}:
                false_breakout = pd.Series(sub[f"false_breakout_{h}"]).dropna()
                row[f"false_breakout_rate_{h}"] = float(false_breakout.mean()) if not false_breakout.empty else np.nan
        rows.append(row)
    return pd.DataFrame(rows).sort_values("state")


def _yearly_state_quality(forward: pd.DataFrame, horizon: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (year, state_name), sub in forward.groupby(["year", "state"]):
        returns = pd.to_numeric(sub[f"return_{horizon}"], errors="coerce").dropna()
        if returns.empty:
            continue
        if state_name == "trend_up":
            hit = (returns > 0).mean()
        elif state_name == "trend_down":
            hit = (returns < 0).mean()
        else:
            hit = (returns.abs() <= 0.03).mean()
        rows.append(
            {
                "year": int(year),
                "state": state_name,
                "entry_count": int(len(sub)),
                f"avg_return_{horizon}": float(returns.mean()),
                f"quality_hit_rate_{horizon}": float(hit),
            }
        )
    return pd.DataFrame(rows).sort_values(["year", "state"])


def _state_distribution(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    series = frame["v71_market_state"].astype(str)
    for year, sub in series.groupby(series.index.year):
        total = len(sub)
        counts = sub.value_counts()
        for state_name, count in counts.items():
            rows.append(
                {
                    "year": int(year),
                    "state": state_name,
                    "bar_count": int(count),
                    "share": float(count / total) if total else 0.0,
                }
            )
    return pd.DataFrame(rows).sort_values(["year", "state"])


def _trade_entry_context(trades: pd.DataFrame, frame: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    merged = trades.copy()
    merged["entry_time"] = pd.to_datetime(merged["entry_time"], utc=True)
    merged = merged.sort_values("entry_time").reset_index(drop=True)
    merged["entry_key"] = merged["entry_time"].dt.tz_convert(None).astype("datetime64[ns]")
    signal_cols = frame[[
        "v71_market_state",
        "v71_daily_state",
        "v71_daily_bias",
        "v71_tradability_state",
        "v71_direction_context",
        "v71_permission_scale",
        "v71_permission_reason",
        "regime",
        "v71_speed_mode",
        "v71_speed_reason",
        "v71_live_reason",
    ]].copy()
    signal_cols.index.name = "signal_time"
    signal_cols = signal_cols.reset_index().sort_values("signal_time")
    signal_cols["signal_time"] = pd.to_datetime(signal_cols["signal_time"], utc=True)
    signal_cols["signal_key"] = signal_cols["signal_time"].dt.tz_convert(None).astype("datetime64[ns]")
    # Micro entries can happen between 4h signal bars, so attach the latest known
    # state instead of requiring exact timestamp equality.
    merged = pd.merge_asof(
        merged,
        signal_cols,
        left_on="entry_key",
        right_on="signal_key",
        direction="backward",
    )
    merged = merged.drop(columns=["signal_time", "entry_key", "signal_key"])
    merged["entry_year"] = merged["entry_time"].dt.year
    return merged


def _trade_quality_by_side(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    grouped = trades.groupby("side")["pnl"].agg(
        trade_count="count",
        win_rate=lambda s: float((s > 0).mean()),
        total_pnl="sum",
        avg_pnl="mean",
        median_pnl="median",
    )
    return grouped.reset_index()


def _trade_quality_by_side_year(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    grouped = trades.groupby(["entry_year", "side"])["pnl"].agg(
        trade_count="count",
        win_rate=lambda s: float((s > 0).mean()),
        total_pnl="sum",
        avg_pnl="mean",
    )
    return grouped.reset_index().sort_values(["entry_year", "side"])


def _trade_quality_by_entry_state(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    grouped = trades.groupby(["v71_market_state", "side"])["pnl"].agg(
        trade_count="count",
        win_rate=lambda s: float((s > 0).mean()),
        total_pnl="sum",
        avg_pnl="mean",
    )
    return grouped.reset_index().sort_values(["v71_market_state", "side"])


def _trade_quality_by_column(trades: pd.DataFrame, column: str) -> pd.DataFrame:
    if trades.empty or column not in trades.columns:
        return pd.DataFrame()
    grouped = trades.groupby([column, "side"])["pnl"].agg(
        trade_count="count",
        win_rate=lambda s: float((s > 0).mean()),
        total_pnl="sum",
        avg_pnl="mean",
    )
    return grouped.reset_index().sort_values([column, "side"])


def _table_text(df: pd.DataFrame, cols: list[str] | None = None, max_rows: int = 20) -> str:
    if df.empty:
        return "_no rows_"
    subset = df if cols is None else df[cols]
    return subset.head(max_rows).to_string(index=False)


def _write_markdown(
    output: Path,
    state_summary: pd.DataFrame,
    yearly_state_quality: pd.DataFrame,
    state_distribution: pd.DataFrame,
    trade_side: pd.DataFrame,
    trade_side_year: pd.DataFrame,
    trade_entry_state: pd.DataFrame,
    trade_tradability: pd.DataFrame,
    trade_direction_context: pd.DataFrame,
) -> None:
    trend_up = state_summary[state_summary["state"] == "trend_up"]
    trend_down = state_summary[state_summary["state"] == "trend_down"]
    range_state = state_summary[state_summary["state"] == "range"]
    bullets = []
    if not trend_up.empty and not trend_down.empty:
        bullets.append(
            f"- `trend_up` 6-bar 平均收益 `{trend_up.iloc[0]['avg_return_6']:.2%}`，命中率 `{trend_up.iloc[0]['quality_hit_rate_6']:.2%}`；`trend_down` 6-bar 平均收益 `{trend_down.iloc[0]['avg_return_6']:.2%}`，命中率 `{trend_down.iloc[0]['quality_hit_rate_6']:.2%}`。"
        )
    if not range_state.empty:
        bullets.append(
            f"- `range` 6-bar 的“低波动命中率”是 `{range_state.iloc[0]['quality_hit_rate_6']:.2%}`，可以看出震荡识别是否真的在把低方向性区间分出来。"
        )
    if not trend_up.empty:
        bullets.append(
            f"- `trend_up` 的 6-bar 假突破率约 `{trend_up.iloc[0].get('false_breakout_rate_6', np.nan):.2%}`；`trend_down` 对应值约 `{trend_down.iloc[0].get('false_breakout_rate_6', np.nan):.2%}`。"
        )
    md = f"""# 趋势判断质量报告

## 结论摘要

{chr(10).join(bullets)}

## State Entry 质量汇总

{_table_text(state_summary, [
    'state','entry_count',
    'avg_return_3','quality_hit_rate_3',
    'avg_return_6','quality_hit_rate_6','same_state_rate_6',
    'avg_return_12','quality_hit_rate_12','same_state_rate_12'
])}

## 年度 State Entry 质量（6-bar）

{_table_text(yearly_state_quality, ['year','state','entry_count','avg_return_6','quality_hit_rate_6'], 50)}

## 年度 State 分布

{_table_text(state_distribution, ['year','state','bar_count','share'], 50)}

## 多空交易质量

{_table_text(trade_side)}

## 年度多空交易质量

{_table_text(trade_side_year, ['entry_year','side','trade_count','win_rate','total_pnl','avg_pnl'], 50)}

## 按入场 State 的交易质量

{_table_text(trade_entry_state, ['v71_market_state','side','trade_count','win_rate','total_pnl','avg_pnl'], 20)}

## 按 Tradability State 的交易质量

{_table_text(trade_tradability, ['v71_tradability_state','side','trade_count','win_rate','total_pnl','avg_pnl'], 20)}

## 按 Direction Context 的交易质量

{_table_text(trade_direction_context, ['v71_direction_context','side','trade_count','win_rate','total_pnl','avg_pnl'], 30)}
"""
    (output / "trend_quality_report.md").write_text(md + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument("--params", type=Path, default=DEFAULT_PARAMS)
    parser.add_argument("--live-like-dir", type=Path, default=DEFAULT_LIVE_LIKE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    params = V71LiveParams(**_read_json(args.params))
    market = load_market_data(args.raw_dir, start=args.start, end=args.end)
    frame = generate_v71_live_signals(market, params)
    frame = frame.loc[frame.index < pd.Timestamp(args.end, tz="UTC")].copy()
    entries = _state_entry_events(frame)
    horizons = [3, 6, 12]
    forward = _forward_metrics(entries, frame, horizons)
    state_summary = _summarize_by_state(forward, horizons)
    yearly_state_quality = _yearly_state_quality(forward, 6)
    state_distribution = _state_distribution(frame)

    trades = pd.read_csv(args.live_like_dir / "micro_trades.csv") if (args.live_like_dir / "micro_trades.csv").exists() else pd.DataFrame()
    trade_context = _trade_entry_context(trades, frame)
    trade_side = _trade_quality_by_side(trade_context)
    trade_side_year = _trade_quality_by_side_year(trade_context)
    trade_entry_state = _trade_quality_by_entry_state(trade_context)
    trade_tradability = _trade_quality_by_column(trade_context, "v71_tradability_state")
    trade_direction_context = _trade_quality_by_column(trade_context, "v71_direction_context")

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    forward.to_csv(output / "state_entry_forward_metrics.csv", index=False)
    state_summary.to_csv(output / "state_entry_quality_summary.csv", index=False)
    yearly_state_quality.to_csv(output / "yearly_state_entry_quality.csv", index=False)
    state_distribution.to_csv(output / "yearly_state_distribution.csv", index=False)
    trade_context.to_csv(output / "trade_entry_context.csv", index=False)
    trade_side.to_csv(output / "trade_quality_by_side.csv", index=False)
    trade_side_year.to_csv(output / "trade_quality_by_side_year.csv", index=False)
    trade_entry_state.to_csv(output / "trade_quality_by_entry_state.csv", index=False)
    trade_tradability.to_csv(output / "trade_quality_by_tradability_state.csv", index=False)
    trade_direction_context.to_csv(output / "trade_quality_by_direction_context.csv", index=False)
    report_payload = {
        "params_file": str(args.params),
        "live_like_dir": str(args.live_like_dir),
        "state_summary": state_summary.to_dict(orient="records"),
        "yearly_state_quality": yearly_state_quality.to_dict(orient="records"),
        "trade_quality_by_side": trade_side.to_dict(orient="records"),
        "trade_quality_by_entry_state": trade_entry_state.to_dict(orient="records"),
        "trade_quality_by_tradability_state": trade_tradability.to_dict(orient="records"),
        "trade_quality_by_direction_context": trade_direction_context.to_dict(orient="records"),
    }
    (output / "trend_quality_report.json").write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_markdown(
        output,
        state_summary,
        yearly_state_quality,
        state_distribution,
        trade_side,
        trade_side_year,
        trade_entry_state,
        trade_tradability,
        trade_direction_context,
    )
    print(json.dumps({
        "output": str(output),
        "state_rows": len(state_summary),
        "trade_rows": len(trade_context),
    }, ensure_ascii=False, indent=2))
