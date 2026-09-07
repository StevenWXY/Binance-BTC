#!/usr/bin/env python3
"""Produce a more live-like validation package for ref_plus_live."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.data import iter_intrabar_months, load_funding, load_market_data  # noqa: E402
from btc_regime.micro_backtest import MicroBacktestConfig, micro_period_metrics, run_micro_backtest  # noqa: E402
from btc_regime.v71_live import V71LiveParams, generate_v71_live_signals  # noqa: E402


DEFAULT_PARAMS = ROOT / "configs/v71_final_candidate_params.json"
DEFAULT_EXECUTION = ROOT / "configs/v71_final_candidate_execution.json"
DEFAULT_OUTPUT = ROOT / "reports/ref_plus_live_live_like_validation_2020_2026_08_01"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_market(raw_dir: Path, start: str, end: str) -> pd.DataFrame:
    requested_start = pd.Timestamp(start, tz="UTC")
    load_start = "2020-01-01" if requested_start > pd.Timestamp("2020-01-01", tz="UTC") else start
    return load_market_data(raw_dir, start=load_start, end=end)


def _annual_metrics(result) -> pd.DataFrame:
    rows = []
    years = sorted({ts.year for ts in result.equity.index})
    for year in years:
        start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        end = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        equity = result.equity.loc[(result.equity.index >= start) & (result.equity.index <= end)]
        if len(equity) < 2:
            continue
        returns = equity.pct_change().dropna()
        total_return = equity.iloc[-1] / equity.iloc[0] - 1
        max_dd = (equity / equity.cummax() - 1).min()
        rows.append(
            {
                "year": year,
                "start_equity": float(equity.iloc[0]),
                "end_equity": float(equity.iloc[-1]),
                "total_return": float(total_return),
                "annualized_volatility": float(returns.std(ddof=1) * (2190 ** 0.5)) if len(returns) > 1 else 0.0,
                "sharpe": float(returns.mean() / returns.std(ddof=1) * (2190 ** 0.5)) if len(returns) > 1 and returns.std(ddof=1) > 0 else 0.0,
                "max_drawdown": float(max_dd),
            }
        )
    return pd.DataFrame(rows)


def _recent_windows(result) -> pd.DataFrame:
    windows = {
        "recent_2024_2026_08": ("2024-01-01", "2026-08-01"),
        "recent_2025_2026_08": ("2025-01-01", "2026-08-01"),
        "recent_2026_ytd": ("2026-01-01", "2026-08-01"),
    }
    rows = []
    for label, (start, end) in windows.items():
        start_ts = pd.Timestamp(start, tz="UTC")
        end_ts = pd.Timestamp(end, tz="UTC")
        equity = result.equity.loc[(result.equity.index >= start_ts) & (result.equity.index <= end_ts)]
        if len(equity) < 2:
            continue
        returns = equity.pct_change().dropna()
        rows.append(
            {
                "window": label,
                "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1),
                "sharpe": float(returns.mean() / returns.std(ddof=1) * (2190 ** 0.5)) if len(returns) > 1 and returns.std(ddof=1) > 0 else 0.0,
                "max_drawdown": float((equity / equity.cummax() - 1).min()),
            }
        )
    return pd.DataFrame(rows)


def _side_breakdown(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["side", "trade_count", "win_rate", "total_pnl", "avg_pnl"])
    frame = trades.copy()
    if "side" in frame.columns:
        frame["side"] = frame["side"].fillna("unknown")
    else:
        frame["side"] = "unknown"
    grouped = frame.groupby("side", dropna=False)
    return grouped["pnl"].agg(
        trade_count="count",
        win_rate=lambda s: float((s > 0).mean()),
        total_pnl="sum",
        avg_pnl="mean",
    ).reset_index()


def _exit_reason_breakdown(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty or "exit_reason" not in trades:
        return pd.DataFrame(columns=["exit_reason", "trade_count", "total_pnl", "avg_pnl"])
    grouped = trades.groupby("exit_reason", dropna=False)["pnl"].agg(
        trade_count="count",
        total_pnl="sum",
        avg_pnl="mean",
    )
    return grouped.reset_index().sort_values("trade_count", ascending=False)


def _fill_liquidity_breakdown(fills: pd.DataFrame) -> pd.DataFrame:
    if fills.empty or "liquidity" not in fills:
        return pd.DataFrame(columns=["liquidity", "fill_count", "notional", "fees", "realized_pnl"])
    grouped = fills.groupby("liquidity", dropna=False).agg(
        fill_count=("liquidity", "count"),
        notional=("notional", "sum"),
        fees=("fee", "sum"),
        realized_pnl=("realized_pnl", "sum"),
    )
    return grouped.reset_index()


def _activity_by_year(fills: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    fill_years = set(fills["timestamp"].dt.year.tolist()) if not fills.empty else set()
    trade_years = set(trades["exit_time"].dt.year.tolist()) if not trades.empty and "exit_time" in trades else set()
    years = fill_years | trade_years
    if not years:
        return pd.DataFrame(columns=["year", "fill_count", "trade_count"])
    rows = []
    for year in sorted(set(years)):
        fill_count = 0 if fills.empty else int((fills["timestamp"].dt.year == year).sum())
        trade_count = 0 if trades.empty or "exit_time" not in trades else int((trades["exit_time"].dt.year == year).sum())
        rows.append({"year": int(year), "fill_count": fill_count, "trade_count": trade_count})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument("--params", type=Path, default=DEFAULT_PARAMS)
    parser.add_argument("--execution", type=Path, default=DEFAULT_EXECUTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    params_dict = _read_json(args.params)
    execution_dict = _read_json(args.execution)
    params = V71LiveParams(**params_dict)
    execution = MicroBacktestConfig(**execution_dict)

    market = _load_market(args.raw_dir, args.start, args.end)
    funding = load_funding(args.raw_dir, start=args.start, end=args.end)
    signaled = generate_v71_live_signals(market, params)
    result = run_micro_backtest(
        signaled.loc[signaled.index < pd.Timestamp(args.end, tz="UTC")],
        list(iter_intrabar_months(args.raw_dir, start=args.start, end=args.end)),
        funding,
        execution,
    )

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    annual = _annual_metrics(result)
    recent = _recent_windows(result)
    side = _side_breakdown(result.trades)
    exit_reason = _exit_reason_breakdown(result.trades)
    fill_liquidity = _fill_liquidity_breakdown(result.fills)
    activity_year = _activity_by_year(result.fills, result.trades)
    periods = micro_period_metrics(result)

    annual.to_csv(output / "annual_metrics.csv", index=False)
    recent.to_csv(output / "recent_metrics.csv", index=False)
    side.to_csv(output / "trade_side_breakdown.csv", index=False)
    exit_reason.to_csv(output / "trade_exit_reason_breakdown.csv", index=False)
    fill_liquidity.to_csv(output / "fill_liquidity_breakdown.csv", index=False)
    activity_year.to_csv(output / "activity_by_year.csv", index=False)
    result.equity.to_csv(output / "micro_equity.csv", header=True)
    result.fills.to_csv(output / "micro_fills.csv", index=False)
    result.trades.to_csv(output / "micro_trades.csv", index=False)
    result.funding.to_csv(output / "micro_funding.csv", index=False)
    result.liquidations.to_csv(output / "micro_liquidations.csv", index=False)

    payload = {
        "strategy": params_dict,
        "execution": execution_dict,
        "metrics": result.metrics,
        "periods": periods,
        "annual_metrics": annual.to_dict(orient="records"),
        "recent_metrics": recent.to_dict(orient="records"),
        "trade_side_breakdown": side.to_dict(orient="records"),
        "trade_exit_reason_breakdown": exit_reason.to_dict(orient="records"),
        "fill_liquidity_breakdown": fill_liquidity.to_dict(orient="records"),
        "activity_by_year": activity_year.to_dict(orient="records"),
    }
    (output / "live_like_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
