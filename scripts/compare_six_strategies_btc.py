#!/usr/bin/env python3
"""Unified V4/V7 strategy replay with BTC benchmark and curve exports."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from btc_regime.backtest import calculate_metrics  # noqa: E402
from btc_regime.data import load_funding, load_market_data  # noqa: E402
from btc_regime.micro_backtest import MicroBacktestConfig, micro_period_metrics, run_micro_backtest, write_micro_report  # noqa: E402
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402
from btc_regime.v42 import V42CapitalParams, combine_direction_and_neutral, generate_neutral_sleeve, neutral_metrics  # noqa: E402
from btc_regime.v43 import V43Params, generate_v43_signals  # noqa: E402
from btc_regime.v7 import V7Params, generate_v7_signals  # noqa: E402
from btc_regime.v712 import V712Params, generate_v712_signals  # noqa: E402
from btc_regime.v713 import V713Params, generate_v713_signals  # noqa: E402
from backtest_v712 import iter_local_batches  # noqa: E402

START = "2020-01-01"
END = "2026-08-01"
INITIAL_CASH = 10_000.0
REBATE = 0.30
BASE_TAKER_FEE_BPS = 4.0
BASE_MAKER_FEE_BPS = 0.2
PERIODS = {
    "train_2020_2022": ("2020-01-01", "2023-01-01"),
    "validation_2023_2024": ("2023-01-01", "2025-01-01"),
    "holdout_2025_2026_07": ("2025-01-01", "2026-08-01"),
    "full_2020_2026_07": ("2020-01-01", "2026-08-01"),
}


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def micro_config(*, maker: bool, execution: dict[str, object], drawdown: bool) -> MicroBacktestConfig:
    return MicroBacktestConfig(
        initial_cash=INITIAL_CASH,
        taker_fee_bps=BASE_TAKER_FEE_BPS * (1 - REBATE),
        maker_fee_bps=BASE_MAKER_FEE_BPS * (1 - REBATE),
        maker_enabled=maker,
        maker_offset_bps=float(execution.get("maker_offset_bps", 0.0)),
        maker_order_timeout_minutes=int(execution.get("maker_order_timeout_minutes", 60)),
        maker_exit_enabled=False,
        base_slippage_bps=1.0,
        impact_bps=8.0,
        max_minute_participation=0.02,
        liquidation_fee_bps=50.0,
        strategy_drawdown_enabled=drawdown,
        strategy_drawdown_level_1=float(execution.get("strategy_drawdown_level_1", 0.20)),
        strategy_drawdown_scale_1=float(execution.get("strategy_drawdown_scale_1", 0.95)),
        strategy_drawdown_level_2=float(execution.get("strategy_drawdown_level_2", 0.30)),
        strategy_drawdown_scale_2=float(execution.get("strategy_drawdown_scale_2", 0.85)),
        strategy_drawdown_level_3=float(execution.get("strategy_drawdown_level_3", 0.40)),
        strategy_drawdown_scale_3=float(execution.get("strategy_drawdown_scale_3", 0.70)),
    )


def sliced_metrics(equity: pd.Series) -> dict[str, dict[str, float]]:
    result = {}
    for label, (start, end) in PERIODS.items():
        window = equity.loc[(equity.index >= pd.Timestamp(start, tz="UTC")) & (equity.index <= pd.Timestamp(end, tz="UTC"))]
        if not window.empty:
            result[label] = calculate_metrics(window, window.pct_change().dropna(), pd.DataFrame(), 2190)
    return result


def run_direction(signals: pd.DataFrame, args, execution: dict[str, object], *, maker: bool, drawdown: bool):
    cfg = micro_config(maker=maker, execution=execution, drawdown=drawdown)
    result = run_micro_backtest(signals, iter_local_batches(args.raw_dir, START, END), args.funding, cfg)
    return result, cfg


def normalize_curves(curves: dict[str, pd.Series]) -> pd.DataFrame:
    frame = pd.concat(curves.values(), axis=1).sort_index().ffill().dropna()
    frame.columns = list(curves)
    return frame


def _svg_curve(frame: pd.DataFrame, path: Path, *, drawdown: bool, title: str) -> None:
    width, height = 1600, 850
    left, right, top, bottom = 90, 30, 70, 70
    plot_w, plot_h = width - left - right, height - top - bottom
    values = frame.copy()
    if drawdown:
        values = values / values.cummax() - 1.0
        ymin, ymax = float(values.min().min()), 0.0
        pad = max((ymax - ymin) * 0.08, 0.02)
        ymin -= pad
    else:
        ymin, ymax = float(values.min().min()), float(values.max().max())
        ymin = min(0.0, ymin)
        pad = max((ymax - ymin) * 0.08, ymax * 0.02)
        ymax += pad
    n = max(len(values) - 1, 1)
    colors = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#475569"]
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             f'<rect width="100%" height="100%" fill="white"/>',
             f'<text x="{left}" y="38" font-family="Arial" font-size="24" font-weight="bold">{escape(title)}</text>']
    for tick in range(6):
        yv = ymin + (ymax - ymin) * tick / 5
        y = top + plot_h * (1 - (yv - ymin) / (ymax - ymin or 1))
        label = f"{yv:.0%}" if drawdown else f"${yv:,.0f}"
        lines.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        lines.append(f'<text x="8" y="{y+5:.1f}" font-family="Arial" font-size="13" fill="#475569">{label}</text>')
    for col_i, col in enumerate(values.columns):
        points = []
        series = values[col].astype(float)
        for i, value in enumerate(series):
            x = left + plot_w * i / n
            y = top + plot_h * (1 - (float(value) - ymin) / (ymax - ymin or 1))
            points.append(f"{x:.1f},{y:.1f}")
        lines.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{colors[col_i % len(colors)]}" stroke-width="2" opacity="0.9"/>')
        ly = top + 22 + 20 * col_i
        lines.append(f'<line x1="{width-300}" y1="{ly-5}" x2="{width-275}" y2="{ly-5}" stroke="{colors[col_i % len(colors)]}" stroke-width="3"/>')
        lines.append(f'<text x="{width-268}" y="{ly}" font-family="Arial" font-size="14">{escape(col)}</text>')
    lines.append(f'<text x="{left}" y="{height-20}" font-family="Arial" font-size="13">{frame.index[0].date()} UTC</text>')
    lines.append(f'<text x="{width-right-100}" y="{height-20}" font-family="Arial" font-size="13">{frame.index[-1].date()} UTC</text>')
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/unified_v4_v7_btc_2020_2026_08_01")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.funding = load_funding(args.raw_dir, start=START, end=END)
    market = load_market_data(args.raw_dir, start=START, end=END, interval="4h")

    v42_capital_base = V42CapitalParams(**read_json(ROOT / "configs/v4_2_capital_params.json"))
    v42_capital = replace(v42_capital_base, spot_fee_bps=v42_capital_base.spot_fee_bps * (1 - REBATE), futures_fee_bps=v42_capital_base.futures_fee_bps * (1 - REBATE))
    neutral = generate_neutral_sleeve(args.funding, v42_capital)
    neutral.to_csv(args.output / "neutral_schedule_v42_v713.csv")

    specs = [
        ("V4", ROOT / "configs/aggressive_adaptive_v3_params.json", "strategy", False, False, None),
        ("V4.1.2", ROOT / "configs/v4_1_2_params.json", "v43", True, False, None),
        ("V4.2.2", ROOT / "configs/v4_2_2_params.json", "v43", True, False, v42_capital),
        ("V7.1", ROOT / "configs/v71_params.json", "v7", False, True, None),
        ("V7.1.2", ROOT / "configs/v712_params.json", "v712", True, True, None),
        ("V7.1.3", ROOT / "configs/v713_params.json", "v713", True, True, v42_capital),
    ]
    curves: dict[str, pd.Series] = {}
    summary: list[dict[str, object]] = []
    payload: dict[str, object] = {}

    for code, config_path, kind, maker, drawdown, capital in specs:
        print(f"Running {code}...", flush=True)
        values = read_json(config_path)
        if kind == "strategy":
            params = StrategyParams(**values)
            signals = generate_signals(market, params)
        elif kind == "v43":
            params = V43Params(**values)
            signals = generate_v43_signals(market, params)
        elif kind == "v7":
            params = V7Params(**values)
            signals = generate_v7_signals(market, params)
        elif kind == "v712":
            params = V712Params(**values)
            signals = generate_v712_signals(market, params)
        else:
            params = V713Params(**values)
            signals = generate_v713_signals(market, params)
        execution = read_json(ROOT / ({"V7.1": "configs/v71_execution.json", "V7.1.2": "configs/v712_execution.json", "V7.1.3": "configs/v713_execution.json"}.get(code, "configs/v713_execution.json")))
        direction, cfg = run_direction(signals, args, execution, maker=maker, drawdown=drawdown)
        write_micro_report(direction, params, cfg, args.output / code.lower())
        if capital is not None:
            effective_signal = signals["signal"].copy()
            effective_signal.index = effective_signal.index + pd.Timedelta(hours=4)
            combined, metrics = combine_direction_and_neutral(direction.equity, neutral, capital, effective_signal)
            combined.to_csv(args.output / f"{code.lower()}_combined_equity.csv")
            curve = combined["combined_equity"].rename(code)
            periods = sliced_metrics(curve)
        else:
            metrics = direction.metrics
            curve = direction.equity.rename(code)
            periods = micro_period_metrics(direction)
        curves[code] = curve
        holdout = periods.get("holdout_2025_2026_07", {})
        summary.append({"code": code, "final_equity": metrics.get("final_equity"), "total_return": metrics.get("total_return"), "cagr": metrics.get("cagr"), "annualized_volatility": metrics.get("annualized_volatility"), "sharpe": metrics.get("sharpe"), "sortino": metrics.get("sortino"), "max_drawdown": metrics.get("max_drawdown"), "holdout_final_equity_rebased": INITIAL_CASH * (1 + holdout.get("total_return", 0)), "holdout_cagr": holdout.get("cagr"), "holdout_sharpe": holdout.get("sharpe"), "holdout_max_drawdown": holdout.get("max_drawdown"), "direction_final_equity": direction.metrics.get("final_equity"), "fees_paid": direction.metrics.get("fees_paid"), "funding_paid": direction.metrics.get("funding_paid"), "maker_fill_ratio": direction.metrics.get("maker_fill_ratio", 0.0), "liquidation_count": direction.metrics.get("liquidation_count", 0.0)})
        payload[code] = {"config": str(config_path.relative_to(ROOT)), "kind": kind, "maker": maker, "drawdown_overlay": drawdown, "parameters": params.to_dict(), "direction_metrics": direction.metrics, "metrics": metrics, "periods": periods, "capital_overlay": capital.to_dict() if capital else None}

    close = market["close"].copy()
    close.index = close.index + pd.Timedelta(hours=4)
    curve_frame = normalize_curves(curves)
    btc = close.reindex(curve_frame.index).ffill().dropna()
    curve_frame = curve_frame.reindex(btc.index)
    curve_frame["BTC"] = btc / btc.iloc[0] * INITIAL_CASH
    curve_frame.to_csv(args.output / "equity_curves.csv")
    drawdowns = curve_frame / curve_frame.cummax() - 1.0
    drawdowns.to_csv(args.output / "drawdown_curves.csv")
    _svg_curve(curve_frame, args.output / "equity_curves.svg", drawdown=False, title="Unified BTCUSDT Strategy Equity Curves")
    _svg_curve(curve_frame, args.output / "drawdown_curves.svg", drawdown=True, title="Unified BTCUSDT Strategy Drawdown Curves")

    btc_metrics = calculate_metrics(curve_frame["BTC"], curve_frame["BTC"].pct_change().dropna(), pd.DataFrame(), 2190)
    summary.append({"code": "BTC", **{key: btc_metrics.get(key) for key in ["final_equity", "total_return", "cagr", "annualized_volatility", "sharpe", "sortino", "max_drawdown"]}, "holdout_final_equity_rebased": None, "holdout_cagr": None, "holdout_sharpe": None, "holdout_max_drawdown": None, "direction_final_equity": None, "fees_paid": 0.0, "funding_paid": 0.0, "maker_fill_ratio": 0.0, "liquidation_count": 0.0})
    report = {"version": "unified-v4-v7-btc", "data": {"start": START, "end": END, "initial_cash": INITIAL_CASH, "market_source": "local Binance USD-M 4h archive", "intrabar_source": "local Binance USD-M 1m trade/mark archives", "funding_source": "local Binance USD-M funding archive"}, "common_execution": {"base_taker_fee_bps": BASE_TAKER_FEE_BPS, "base_maker_fee_bps": BASE_MAKER_FEE_BPS, "fee_rebate_rate": REBATE, "effective_taker_fee_bps": BASE_TAKER_FEE_BPS * (1 - REBATE), "effective_maker_fee_bps": BASE_MAKER_FEE_BPS * (1 - REBATE), "base_slippage_bps": 1.0, "impact_bps": 8.0, "max_minute_participation": 0.02}, "strategies": payload, "neutral_sleeve": neutral_metrics(neutral), "summary": summary, "method": {"btc": "buy-and-hold BTC close, rebased to 10,000 USDT at the first strategy boundary", "maker": "1m OHLC touch proxy; protective exits remain taker", "neutral": "V4.2.1 settled-funding/idle-yield proxy with causal recall", "limitations": ["maker queue and adverse selection are not available in historical OHLC", "neutral sleeve excludes spot-perpetual basis PnL, borrowing cost and order-book depth"]}}
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=float) + "\n", encoding="utf-8")
    pd.DataFrame(summary).to_csv(args.output / "summary_metrics.csv", index=False)
    print(pd.DataFrame(summary).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
