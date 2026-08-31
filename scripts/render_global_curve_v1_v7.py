#!/usr/bin/env python3
"""Backtest and render V1-V7 plus BTC on the shared 4h market snapshot."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import PercentFormatter, StrMethodFormatter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.backtest import BacktestConfig, run_backtest  # noqa: E402
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402
from btc_regime.v6 import V6Params, generate_v6_signals  # noqa: E402
from btc_regime.v7 import V7Params, generate_v7_signals  # noqa: E402


MARKET = ROOT / "reports/annual_2020_2026_08_25/market_4h_full.csv"
FUNDING = ROOT / "reports/annual_2020_2026_08_25/funding_full.csv"
OUT_DIR = ROOT / "reports/global_curve_v1_v7_2020_2026_08_25"

V1_V5 = {
    "V1": ("Base trend + ATR sizing", ROOT / "configs/aggressive_params.json"),
    "V2": ("Funding crowdedness filter", ROOT / "configs/aggressive_vol_carry_params.json"),
    "V3": ("Volatility and downside adaptive allocation", ROOT / "configs/aggressive_adaptive_params.json"),
    "V4": ("Robust long-only trend/rebound baseline", ROOT / "configs/aggressive_adaptive_v3_params.json"),
    "V4.1": ("Local V4 refinement", ROOT / "configs/v4_refined_params.json"),
    "V5": ("Cautious symmetric short experiment", ROOT / "configs/aggressive_adaptive_v4_short_params.json"),
}
SERIES = ["V1", "V2", "V3", "V4", "V4.1", "V5", "V6", "V7", "BTC"]
COLORS = {
    "V1": "#2563eb",
    "V2": "#ea580c",
    "V3": "#16a34a",
    "V4": "#0891b2",
    "V4.1": "#dc2626",
    "V5": "#0f766e",
    "V6": "#111827",
    "V7": "#f59e0b",
    "BTC": "#7c3aed",
}


def load_market() -> pd.DataFrame:
    market = pd.read_csv(MARKET, index_col=0, parse_dates=True)
    market.index = pd.to_datetime(market.index, utc=True, format="mixed")
    funding = pd.read_csv(FUNDING, index_col=0, parse_dates=True)
    funding.index = pd.to_datetime(funding.index, utc=True, format="mixed")
    funding_4h = funding["funding_rate"].groupby(funding.index.floor("4h")).sum()
    market["funding_rate"] = funding_4h.reindex(market.index, fill_value=0.0)
    return market.sort_index()


def _btc_metrics(equity: pd.Series) -> dict[str, float]:
    years = (equity.index[-1] - equity.index[0]).total_seconds() / (365.25 * 24 * 3600)
    returns = equity.pct_change().dropna()
    drawdown = equity / equity.cummax() - 1.0
    return {
        "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1.0),
        "cagr": float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1.0),
        "annualized_volatility": float(returns.std(ddof=1) * np.sqrt(365 * 6)),
        "sharpe": float(returns.mean() / returns.std(ddof=1) * np.sqrt(365 * 6)),
        "max_drawdown": float(drawdown.min()),
        "final_equity": float(equity.iloc[-1]),
    }


def backtest_curve(market: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object], pd.DataFrame]:
    config = BacktestConfig(initial_cash=10_000.0, fee_bps=4.0, slippage_bps=1.0)
    curves: dict[str, pd.Series] = {}
    metrics: dict[str, object] = {}
    v7_signals = pd.DataFrame(index=market.index)

    for code, (name, path) in V1_V5.items():
        params = StrategyParams(**json.loads(path.read_text(encoding="utf-8")))
        frame = generate_signals(market, params)
        frame.index = frame.index + pd.Timedelta(hours=4)
        result = run_backtest(frame, config)
        curves[code] = result.equity.rename(code)
        metrics[code] = {"strategy": name, **result.metrics}

    v6_params = V6Params(**json.loads((ROOT / "configs/v6_params.json").read_text(encoding="utf-8")))
    v6_frame = generate_v6_signals(market, v6_params)
    v6_frame.index = v6_frame.index + pd.Timedelta(hours=4)
    v6_result = run_backtest(v6_frame, config)
    curves["V6"] = v6_result.equity.rename("V6")
    metrics["V6"] = {"strategy": "Confidence-driven multi-timeframe dynamic risk", **v6_result.metrics}

    v7_params = V7Params(**json.loads((ROOT / "configs/v7_params.json").read_text(encoding="utf-8")))
    raw_v7 = generate_v7_signals(market, v7_params)
    v7_signals = raw_v7[[
        "signal",
        "regime",
        "v7_market_state",
        "v7_range_percentile",
        "v7_long_allocation_scale",
        "v7_short_allocation_scale",
        "v7_speed_mode",
        "v7_speed_scale",
        "v7_speed_reason",
        "v7_fast_return",
        "v7_medium_return",
        "v7_volume_speed",
    ]].copy()
    v7_frame = raw_v7.copy()
    v7_frame.index = v7_frame.index + pd.Timedelta(hours=4)
    v7_result = run_backtest(v7_frame, config)
    curves["V7"] = v7_result.equity.rename("V7")
    metrics["V7"] = {"strategy": "Mutually exclusive trend/range V7 with rapid-move controls", **v7_result.metrics}

    price = market["close"].copy()
    price.index = price.index + pd.Timedelta(hours=4)
    curves["BTC"] = (price / price.iloc[0] * 10_000.0).rename("BTC")
    metrics["BTC"] = {"strategy": "BTC buy and hold", **_btc_metrics(curves["BTC"])}

    curve = pd.concat(curves.values(), axis=1).sort_index().ffill().dropna()
    return curve, metrics, v7_signals


def _format_axes(ax, *, percent: bool = False, dollars: bool = False) -> None:
    ax.grid(True, alpha=0.25)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    if percent:
        ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    if dollars:
        ax.yaxis.set_major_formatter(StrMethodFormatter("${x:,.0f}"))


def render_equity(curve: pd.DataFrame, output: Path, *, log_scale: bool) -> None:
    fig, ax = plt.subplots(figsize=(16, 8), dpi=160)
    for code in SERIES:
        ax.plot(curve.index, curve[code], label=code, color=COLORS[code], lw=2.4 if code == "V7" else 1.5)
    ax.set_title(f"BTCUSDT 4h Backtest: V1-V7 + BTC ({'log' if log_scale else 'linear'} equity)")
    ax.set_ylabel("Equity (USDT)")
    ax.set_xlabel("Date (UTC)")
    if log_scale:
        ax.set_yscale("log")
    else:
        ax.set_ylim(0, float(curve.max().max()) * 1.08)
    _format_axes(ax, dollars=True)
    ax.legend(ncol=5, loc="upper left")
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def render_equity_drawdown(curve: pd.DataFrame, output: Path) -> None:
    drawdown = curve / curve.cummax() - 1.0
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 11), dpi=160, sharex=True, height_ratios=[2, 1])
    for code in SERIES:
        width = 2.4 if code == "V7" else 1.4
        ax1.plot(curve.index, curve[code], label=code, color=COLORS[code], lw=width)
        ax2.plot(drawdown.index, drawdown[code], label=code, color=COLORS[code], lw=width)
    ax1.set_title("BTCUSDT 4h Backtest: V1-V7 + BTC")
    ax1.set_ylabel("Equity (USDT, log scale)")
    ax1.set_yscale("log")
    ax2.set_ylabel("Drawdown")
    ax2.set_xlabel("Date (UTC)")
    _format_axes(ax1, dollars=True)
    _format_axes(ax2, percent=True)
    ax1.legend(ncol=5, loc="upper left")
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def write_outputs(curve: pd.DataFrame, metrics: dict[str, object], v7_signals: pd.DataFrame) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    curve.to_csv(OUT_DIR / "equity_curves.csv")
    (curve / curve.cummax() - 1.0).to_csv(OUT_DIR / "drawdown_curves.csv")
    v7_signals.to_csv(OUT_DIR / "v7_signals.csv")
    summary = pd.DataFrame(
        [
            {
                "code": code,
                "strategy": metrics[code]["strategy"],
                "final_equity": metrics[code]["final_equity"],
                "total_return": metrics[code]["total_return"],
                "cagr": metrics[code]["cagr"],
                "sharpe": metrics[code]["sharpe"],
                "max_drawdown": metrics[code]["max_drawdown"],
                "trade_count": metrics[code].get("trade_count"),
            }
            for code in SERIES
        ]
    )
    summary.to_csv(OUT_DIR / "summary_metrics.csv", index=False)
    payload = {
        "data_start": curve.index[0].isoformat(),
        "data_end": curve.index[-1].isoformat(),
        "bar_interval": "4h",
        "signal_timing": "completed candle; position applies to next 4h bar",
        "backtest": {
            "initial_cash": 10_000.0,
            "fee_bps": 4.0,
            "slippage_bps": 1.0,
        },
        "v7_design_checks": {
            "primary_market_states_are_mutually_exclusive": True,
            "market_states": ["range", "trend_up", "trend_down"],
            "trend_states_split_normal_and_rapid": True,
            "short_direction_logic_symmetric_with_longs": True,
            "short_risk_budget_symmetric_with_longs": False,
            "short_scale": 0.08,
            "range_uses_percentile_entry_exit": True,
            "range_entry_percentile": 0.25,
            "range_exit_percentile": 0.84,
            "max_leverage_cap": 6.5,
        },
        "strategies": metrics,
    }
    (OUT_DIR / "metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    render_equity(curve, OUT_DIR / "equity_curve_v1_v7_log.png", log_scale=True)
    render_equity(curve, OUT_DIR / "equity_curve_v1_v7_linear.png", log_scale=False)
    render_equity(curve, OUT_DIR / "equity_curve_v1_v7_linear.svg", log_scale=False)
    render_equity_drawdown(curve, OUT_DIR / "equity_drawdown_v1_v7.png")
    print(summary.to_string(index=False))


def main() -> None:
    market = load_market()
    curve, metrics, v7_signals = backtest_curve(market)
    write_outputs(curve, metrics, v7_signals)


if __name__ == "__main__":
    main()
