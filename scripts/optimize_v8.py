"""Chronological V8 search ranked only on development periods.

The search only ranks the train (2020--2022) and validation (2023--2024)
periods. The 2025--2026-07 segment is calculated once for the selected
candidate and is written as an evaluation result. This keeps a later
parameter choice from silently using the future segment.
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import pandas as pd

from btc_regime.backtest import BacktestConfig, run_backtest
from btc_regime.data import load_market_data
from btc_regime.range_grid import RangeGridParams, generate_range_grid_signals


PERIODS = {
    "train_2020_2022": ("2020-01-01", "2023-01-01"),
    "validation_2023_2024": ("2023-01-01", "2025-01-01"),
    "holdout_2025_2026_07": ("2025-01-01", "2026-08-01"),
}


def period_metrics(result, start: str, end: str) -> tuple[float, float, float, int]:
    """Return period return, max drawdown, Sharpe and closed trade count."""
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    equity = result.equity.loc[(result.equity.index >= start_ts) & (result.equity.index < end_ts)]
    if len(equity) < 2:
        return 0.0, 0.0, 0.0, 0
    returns = equity.pct_change().dropna()
    drawdown = float((equity / equity.cummax() - 1).min())
    sharpe = float(returns.mean() / returns.std() * 2190**0.5) if returns.std() > 0 else 0.0
    trades = result.trades
    if len(trades):
        entries = pd.to_datetime(trades["entry_time"], utc=True)
        trade_count = int(((entries >= start_ts) & (entries < end_ts)).sum())
    else:
        trade_count = 0
    return float(equity.iloc[-1] / equity.iloc[0] - 1), drawdown, sharpe, trade_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimize bounded V8 range strategy without holdout leakage")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--output", default="reports/v8_optimization_proper")
    parser.add_argument("--fee-bps", type=float, default=2.4)
    parser.add_argument("--slippage-bps", type=float, default=1.0)
    args = parser.parse_args()

    base = json.loads(Path("configs/v8_params.json").read_text(encoding="utf-8"))
    data = load_market_data(args.raw_dir, start="2020-01-01", end="2025-01-01")
    data = data.loc[data.index < pd.Timestamp("2025-01-01", tz="UTC")]
    rows: list[dict[str, float | int]] = []

    # A modest, declared grid. Sizing is held at the V8 default (0.60 target
    # volatility, 2x cap) while the range detector and entry frequency vary.
    grid = itertools.product(
        [22.0, 24.0],       # range_adx_enter
        [50.0, 52.0, 55.0], # chop_enter
        [0.24, 0.32],       # efficiency_max
        [1, 2],             # range_confirm_bars
        [1, 2],             # range_exit_confirm_bars
        [18, 24],           # channel_period
        [0.18, 0.20, 0.22], # entry_percentile
    )
    for adx_enter, chop_enter, efficiency_max, confirm, exit_confirm, channel, entry in grid:
        payload = {
            **base,
            "range_adx_enter": adx_enter,
            "chop_enter": chop_enter,
            "efficiency_max": efficiency_max,
            "range_confirm_bars": confirm,
            "range_exit_confirm_bars": exit_confirm,
            "channel_period": channel,
            "entry_percentile": entry,
            "target_vol": 0.60,
            "max_leverage": 2.0,
            "range_scale": 1.0,
            "short_scale": 1.0,
        }
        params = RangeGridParams(**payload)
        signaled = generate_range_grid_signals(data, params)
        result = run_backtest(
            signaled,
            BacktestConfig(fee_bps=args.fee_bps, slippage_bps=args.slippage_bps),
        )
        row: dict[str, float | int] = {
            "range_adx_enter": adx_enter,
            "chop_enter": chop_enter,
            "efficiency_max": efficiency_max,
            "range_confirm_bars": confirm,
            "range_exit_confirm_bars": exit_confirm,
            "channel_period": channel,
            "entry_percentile": entry,
            "target_vol": 0.60,
            "max_leverage": 2.0,
            "range_scale": 1.0,
            "short_scale": 1.0,
            **result.metrics,
        }
        period_values: dict[str, tuple[float, float, float, int]] = {}
        for label, (start, end) in list(PERIODS.items())[:2]:
            values = period_metrics(result, start, end)
            period_values[label] = values
            row[f"{label}_return"] = values[0]
            row[f"{label}_drawdown"] = values[1]
            row[f"{label}_sharpe"] = values[2]
            row[f"{label}_trades"] = values[3]

        train_ret, train_dd, _, train_trades = period_values["train_2020_2022"]
        val_ret, val_dd, _, val_trades = period_values["validation_2023_2024"]
        worst_dd = abs(min(train_dd, val_dd))
        # Equal weight development periods. A small frequency bonus prevents a
        # six-trade candidate from winning solely by luck.
        frequency_bonus = min(train_trades, val_trades, 100) * 0.00005
        row["selection_score"] = (train_ret + val_ret) / 2 - 0.35 * worst_dd + frequency_bonus
        row["holdout_used_for_selection"] = 0
        rows.append(row)

    table = pd.DataFrame(rows).sort_values("selection_score", ascending=False).reset_index(drop=True)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    table.to_csv(output / "grid.csv", index=False)
    selected = table.iloc[0].to_dict()
    selected_params = {
        **base,
        "range_adx_enter": float(selected["range_adx_enter"]),
        "chop_enter": float(selected["chop_enter"]),
        "efficiency_max": float(selected["efficiency_max"]),
        "range_confirm_bars": int(selected["range_confirm_bars"]),
        "range_exit_confirm_bars": int(selected["range_exit_confirm_bars"]),
        "channel_period": int(selected["channel_period"]),
        "entry_percentile": float(selected["entry_percentile"]),
        "target_vol": 0.60,
        "max_leverage": 2.0,
        "range_scale": 1.0,
        "short_scale": 1.0,
    }
    all_data = load_market_data(args.raw_dir, start="2020-01-01", end="2026-08-01")
    all_data = all_data.loc[all_data.index < pd.Timestamp("2026-08-01", tz="UTC")]
    evaluation = run_backtest(generate_range_grid_signals(all_data, RangeGridParams(**selected_params)),
                              BacktestConfig(fee_bps=args.fee_bps, slippage_bps=args.slippage_bps))
    selected_evaluation = {label: period_metrics(evaluation, start, end)
                           for label, (start, end) in PERIODS.items()}
    (output / "selected_params.json").write_text(json.dumps(selected_params, indent=2), encoding="utf-8")
    (output / "report.json").write_text(
        json.dumps(
            {
                "strategy": "V8",
                "selection_method": "train_2020_2022 + validation_2023_2024 only",
                "holdout_policy": "Not used in ranking. Earlier exploratory runs inspected this interval, so it is not a pristine blind test.",
                "selected_evaluation": selected_evaluation,
                "data": {
                    "start": "2020-01-01",
                    "end": "2026-08-01",
                    "bar": "4h",
                    "train": PERIODS["train_2020_2022"],
                    "validation": PERIODS["validation_2023_2024"],
                    "holdout": PERIODS["holdout_2025_2026_07"],
                },
                "execution": {
                    "effective_taker_fee_bps": args.fee_bps,
                    "base_taker_fee_bps": 4.0,
                    "fee_rebate_rate": 0.40,
                    "slippage_bps": args.slippage_bps,
                },
                "selected": selected,
                "selected_params": selected_params,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(table.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
