#!/usr/bin/env python3
"""Causal V4.3 parameter search with a locked 2025-2026 holdout.

The optimizer only ranks candidates on 2020-2024.  The selected row is then
evaluated once on 2025-2026 and written to a separate report so the holdout
does not influence the chosen configuration. ``--fee-rebate-rate`` changes
only the fee used by the ranking/holdout calculation.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.backtest import BacktestConfig, run_backtest  # noqa: E402
from btc_regime.data import load_market_data  # noqa: E402
from btc_regime.v43 import V43Params, generate_v43_signals  # noqa: E402


def period_metrics(
    signaled: pd.DataFrame,
    start: str,
    end: str,
    *,
    fee_bps: float,
) -> dict[str, float]:
    window = signaled.loc[
        (signaled.index >= pd.Timestamp(start, tz="UTC"))
        & (signaled.index < pd.Timestamp(end, tz="UTC"))
    ]
    return run_backtest(window, BacktestConfig(fee_bps=fee_bps, slippage_bps=1.0)).metrics


def score(train: dict[str, float], validation: dict[str, float]) -> float:
    # The weakest-period Sharpe and CAGR matter most; the drawdown term favors
    # candidates that do not obtain a score from one unusually good period.
    return (
        min(train["sharpe"], validation["sharpe"])
        + 0.20 * min(train["cagr"], validation["cagr"])
        + 0.50 * max(train["max_drawdown"], validation["max_drawdown"])
    )


def evaluate_candidate(
    base: V43Params,
    market: pd.DataFrame,
    values: dict[str, object],
    *,
    fee_bps: float,
) -> dict[str, object]:
    params = replace(base, **values)
    signaled = generate_v43_signals(market, params)
    train = period_metrics(signaled, "2020-01-01", "2023-01-01", fee_bps=fee_bps)
    validation = period_metrics(signaled, "2023-01-01", "2025-01-01", fee_bps=fee_bps)
    return {
        **values,
        "train_cagr": train["cagr"],
        "train_sharpe": train["sharpe"],
        "train_max_drawdown": train["max_drawdown"],
        "train_total_return": train["total_return"],
        "validation_cagr": validation["cagr"],
        "validation_sharpe": validation["sharpe"],
        "validation_max_drawdown": validation["max_drawdown"],
        "validation_total_return": validation["total_return"],
        "robust_score": score(train, validation),
        "train_trade_count": train["trade_count"],
        "validation_trade_count": validation["trade_count"],
        "downside_trigger_count": int(signaled["v43_downside_trigger"].sum()),
        "fast_downside_exit_count": int(
            (signaled["v43_stop_reason"] == "fast_downside_stop").sum()
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", type=Path, default=ROOT / "configs/v4_3_params.json")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--taker-fee-bps", type=float, default=4.0)
    parser.add_argument("--fee-rebate-rate", type=float, default=0.0)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/v4_3_optimization.csv")
    parser.add_argument("--report", type=Path, default=ROOT / "reports/v4_3_optimization.json")
    args = parser.parse_args()
    if not 0.0 <= args.fee_rebate_rate < 1.0:
        parser.error("--fee-rebate-rate must be in [0, 1)")
    effective_fee_bps = args.taker_fee_bps * (1.0 - args.fee_rebate_rate)

    base = V43Params(**json.loads(args.params.read_text(encoding="utf-8")))
    # Full history is loaded so the selected configuration can be evaluated on
    # the untouched holdout; all indicators remain causal by construction.
    market = load_market_data(args.raw_dir, start="2020-01-01", end="2026-08-01")

    rows: list[dict[str, object]] = []
    # Stage 1: optimize the protective distances and fast-downside threshold.
    stage1 = itertools.product(
        [2.5, 3.0, 3.5],  # stop_atr (rarely binding, but kept explicit)
        [8.0, 10.0, 12.0],  # take_profit_atr
        [2.5, 3.0, 3.5],  # trailing_atr
        [0.04, 0.05, 0.06],  # absolute downside return threshold
    )
    stage1_rows = []
    for stop, take, trailing, downside in stage1:
        stage1_rows.append(
            evaluate_candidate(
                base,
                market,
                {
                    "stop_atr": stop,
                    "take_profit_atr": take,
                    "trailing_atr": trailing,
                    "downside_return_threshold": -downside,
                    "downside_vol_ratio": base.downside_vol_ratio,
                    "exit_cooldown_bars": base.exit_cooldown_bars,
                    "drawdown_brake_enabled": base.drawdown_brake_enabled,
                    "price_drawdown_enter": base.price_drawdown_enter,
                    "price_drawdown_exit": base.price_drawdown_exit,
                    "price_drawdown_scale": base.price_drawdown_scale,
                },
                fee_bps=effective_fee_bps,
            )
        )
    stage1_rows.sort(key=lambda row: float(row["robust_score"]), reverse=True)

    # Stage 2: refine execution of downside controls around the best stage-1
    # combinations.  The holdout is not consulted here.
    profiles = [
        ("current", True, 0.15, 0.075, 0.30),
        ("disabled", False, 0.15, 0.075, 0.30),
        ("mild", True, 0.20, 0.10, 0.50),
        ("tight", True, 0.10, 0.05, 0.30),
    ]
    for seed in stage1_rows[:8]:
        for profile, enabled, enter, exit_, scale in profiles:
            for vol_ratio, cooldown in itertools.product([1.1, 1.2, 1.3], [0, 3]):
                values = {
                    "stop_atr": seed["stop_atr"],
                    "take_profit_atr": seed["take_profit_atr"],
                    "trailing_atr": seed["trailing_atr"],
                    "downside_return_threshold": seed["downside_return_threshold"],
                    "downside_vol_ratio": vol_ratio,
                    "exit_cooldown_bars": cooldown,
                    "drawdown_brake_enabled": enabled,
                    "price_drawdown_enter": enter,
                    "price_drawdown_exit": exit_,
                    "price_drawdown_scale": scale,
                }
                row = evaluate_candidate(base, market, values, fee_bps=effective_fee_bps)
                row["drawdown_profile"] = profile
                rows.append(row)
    rows.extend(stage1_rows)
    table = pd.DataFrame(rows).sort_values("robust_score", ascending=False).reset_index(drop=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.output, index=False)

    selected = table.iloc[0].to_dict()
    selected_values = {
        key: selected[key]
        for key in [
            "stop_atr", "take_profit_atr", "trailing_atr", "downside_return_threshold",
            "downside_vol_ratio", "exit_cooldown_bars", "drawdown_brake_enabled",
            "price_drawdown_enter", "price_drawdown_exit", "price_drawdown_scale",
        ]
    }
    # Recast JSON scalar values to avoid numpy scalar serialization surprises.
    selected_values["exit_cooldown_bars"] = int(selected_values["exit_cooldown_bars"])
    selected_values["drawdown_brake_enabled"] = bool(selected_values["drawdown_brake_enabled"])
    selected_params = replace(base, **selected_values)
    selected_signaled = generate_v43_signals(market, selected_params)
    holdout = period_metrics(
        selected_signaled, "2025-01-01", "2026-08-01", fee_bps=effective_fee_bps
    )
    current_signaled = generate_v43_signals(market, base)
    current_holdout = period_metrics(
        current_signaled, "2025-01-01", "2026-08-01", fee_bps=effective_fee_bps
    )

    payload = {
        "method": {
            "selection": "max weakest-period Sharpe + 0.20*weakest CAGR + 0.50*best drawdown",
            "optimization_window": "2020-01-01 to 2025-01-01",
            "holdout_window": "2025-01-01 to 2026-08-01",
            "candidate_count": int(len(table)),
            "base_taker_fee_bps": args.taker_fee_bps,
            "fee_rebate_rate": args.fee_rebate_rate,
            "effective_taker_fee_bps": effective_fee_bps,
        },
        "base_params": base.to_dict(),
        "selected_parameters": selected_params.to_dict(),
        "selected_train_validation": selected,
        "selected_holdout": holdout,
        "base_holdout": current_holdout,
        "holdout_delta": {
            key: float(holdout[key] - current_holdout[key])
            for key in ["total_return", "cagr", "sharpe", "max_drawdown", "trade_count"]
        },
        "top_candidates": table.head(20).to_dict(orient="records"),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"selected": selected_params.to_dict(), "selected_holdout": holdout, "base_holdout": current_holdout}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
