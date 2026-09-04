#!/usr/bin/env python3
"""Run and render minute-level V4, V4.1, V4.2, and BTC curves."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from btc_regime.data import iter_intrabar_months  # noqa: E402
from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest  # noqa: E402
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402
from btc_regime.v42 import (  # noqa: E402
    V42CapitalParams,
    combine_direction_and_neutral,
    generate_neutral_sleeve,
)
from render_global_curve_v41_v6 import render, render_single  # noqa: E402


START = "2020-01-01"
END = "2026-08-25 08:00"
REBATE_RATE = 0.30
OUT_DIR = ROOT / "reports/micro_curve_v4_v41_v42_rebate30_2020_2026_08_25"
MARKET_PATH = ROOT / "reports/annual_2020_2026_08_25/market_4h_full.csv"
FUNDING_PATH = ROOT / "reports/annual_2020_2026_08_25/funding_full.csv"

STRATEGIES = {
    "V4": ("V4 稳健长多趋势-反弹混合", ROOT / "configs/aggressive_adaptive_v3_params.json"),
    "V4.1": ("V4.1 稳健长多趋势-反弹混合优化", ROOT / "configs/v4_refined_params.json"),
    "V4.2": ("V4.2 方向策略+资金费中性覆盖", ROOT / "configs/v4_2_params.json"),
    "BTC": ("BTCUSDT 价格基准", None),
}
SERIES = ["V4", "V4.1", "V4.2", "BTC"]
COLORS = {"V4": "#D45B57", "V4.1": "#DC2626", "V4.2": "#0F766E", "BTC": "#7B61B8"}
NAMES = {code: name for code, (name, _) in STRATEGIES.items()}
HIGHLIGHTED = {"V4.1", "V4.2", "BTC"}


def _read_timeseries(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True, format="mixed")
    return frame.sort_index()


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    start = pd.Timestamp(START, tz="UTC")
    end = pd.Timestamp(END, tz="UTC")
    market = _read_timeseries(MARKET_PATH).loc[lambda x: (x.index >= start) & (x.index < end)]
    funding = _read_timeseries(FUNDING_PATH).loc[lambda x: (x.index >= start) & (x.index < end)]
    return market, funding


def micro_config(fee_bps: float) -> MicroBacktestConfig:
    return MicroBacktestConfig(
        initial_cash=10_000.0,
        taker_fee_bps=fee_bps,
        base_slippage_bps=1.0,
        impact_bps=8.0,
        max_minute_participation=0.02,
        liquidation_fee_bps=50.0,
    )


def run_direction(
    market: pd.DataFrame,
    fee_bps: float,
    params_path: Path,
) -> tuple[pd.Series, dict[str, float], object]:
    params = StrategyParams(**json.loads(params_path.read_text(encoding="utf-8")))
    result = run_micro_backtest(
        generate_signals(market, params),
        iter_intrabar_months(ROOT / "data/raw", start=START, end=END),
        _read_timeseries(FUNDING_PATH),
        micro_config(fee_bps),
    )
    return result.equity.rename("equity"), result.metrics, result


def benchmark_metrics(price: pd.Series) -> dict[str, float]:
    returns = price.pct_change().dropna()
    years = max((price.index[-1] - price.index[0]).total_seconds() / (365.25 * 86400), 1 / 365.25)
    volatility = returns.std(ddof=1) * np.sqrt(2190)
    return {
        "total_return": float(price.iloc[-1] / price.iloc[0] - 1.0),
        "cagr": float((price.iloc[-1] / price.iloc[0]) ** (1 / years) - 1.0),
        "annualized_volatility": float(volatility),
        "sharpe": float(returns.mean() / returns.std(ddof=1) * np.sqrt(2190)),
        "sortino": 0.0,
        "max_drawdown": float((price / price.cummax() - 1.0).min()),
        "final_equity": float(price.iloc[-1]),
    }


def load_btc_curve(market: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    close_at_boundary = market["close"].copy()
    close_at_boundary.index = close_at_boundary.index + pd.Timedelta(hours=4)
    btc = close_at_boundary.reindex(index).ffill().bfill().dropna()
    return (btc / btc.iloc[0] * 10_000.0).rename("BTC")


def metrics_row(code: str, name: str, metrics: dict[str, float], fee_bps: float | None) -> dict[str, object]:
    return {
        "code": code,
        "strategy": name,
        "effective_taker_fee_bps": fee_bps,
        "fee_rebate_rate": REBATE_RATE,
        "final_equity": metrics.get("final_equity"),
        "total_return": metrics.get("total_return"),
        "cagr": metrics.get("cagr"),
        "sharpe": metrics.get("sharpe"),
        "sortino": metrics.get("sortino"),
        "max_drawdown": metrics.get("max_drawdown"),
        "fill_count": metrics.get("fill_count"),
        "fees_paid": metrics.get("fees_paid"),
        "funding_paid": metrics.get("funding_paid"),
    }


def annual_table(curve: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for year, period in curve.groupby(curve.index.year):
        drawdown = period / period.cummax() - 1.0
        for code in curve.columns:
            rows.append({
                "year": int(year),
                "code": code,
                "return": float(period[code].iloc[-1] / period[code].iloc[0] - 1.0),
                "max_drawdown": float(drawdown[code].min()),
            })
    return pd.DataFrame(rows)


def main() -> None:
    market, funding = load_inputs()
    base_fee_bps = 4.0
    v42_base_fee_bps = 2.8
    v4_fee_bps = base_fee_bps * (1 - REBATE_RATE)
    v42_fee_bps = v42_base_fee_bps * (1 - REBATE_RATE)

    curves: dict[str, pd.Series] = {}
    report_metrics: dict[str, dict[str, object]] = {}

    print(f"Running V4 at {v4_fee_bps:.2f} bps effective fee...", flush=True)
    v4_curve, v4_metrics, v4_result = run_direction(market, v4_fee_bps, STRATEGIES["V4"][1])
    curves["V4"] = v4_curve.rename("V4")
    report_metrics["V4"] = {
        **v4_metrics,
        "strategy": STRATEGIES["V4"][0],
        "base_taker_fee_bps": base_fee_bps,
        "effective_taker_fee_bps": v4_fee_bps,
    }

    print(f"Running V4.1 at {v4_fee_bps:.2f} bps effective fee...", flush=True)
    v41_curve, v41_metrics, v41_result = run_direction(market, v4_fee_bps, STRATEGIES["V4.1"][1])
    curves["V4.1"] = v41_curve.rename("V4.1")
    report_metrics["V4.1"] = {
        **v41_metrics,
        "strategy": STRATEGIES["V4.1"][0],
        "base_taker_fee_bps": base_fee_bps,
        "effective_taker_fee_bps": v4_fee_bps,
    }

    print(f"Running V4.2 direction at {v42_fee_bps:.2f} bps effective fee...", flush=True)
    v42_direction, v42_direction_metrics, v42_result = run_direction(
        market, v42_fee_bps, STRATEGIES["V4.2"][1]
    )
    capital_params = V42CapitalParams(
        **json.loads((ROOT / "configs/v4_2_capital_params.json").read_text(encoding="utf-8"))
    )
    capital_params = replace(
        capital_params,
        spot_fee_bps=capital_params.spot_fee_bps * (1 - REBATE_RATE),
        futures_fee_bps=capital_params.futures_fee_bps * (1 - REBATE_RATE),
    )
    neutral = generate_neutral_sleeve(funding, capital_params)
    direction_signal = generate_signals(
        market, StrategyParams(**json.loads(STRATEGIES["V4.2"][1].read_text(encoding="utf-8")))
    )["signal"]
    direction_signal.index = direction_signal.index + pd.Timedelta(hours=4)
    combined, combined_metrics = combine_direction_and_neutral(
        v42_direction, neutral, capital_params, direction_signal
    )
    curves["V4.2"] = combined["combined_equity"].rename("V4.2")
    report_metrics["V4.2"] = {
        **combined_metrics,
        "strategy": STRATEGIES["V4.2"][0],
        "direction_metrics": v42_direction_metrics,
        "base_direction_taker_fee_bps": v42_base_fee_bps,
        "effective_direction_taker_fee_bps": v42_fee_bps,
        "base_spot_fee_bps": 7.0,
        "effective_spot_fee_bps": capital_params.spot_fee_bps,
        "base_futures_fee_bps": 2.8,
        "effective_futures_fee_bps": capital_params.futures_fee_bps,
        "neutral_transition_cost_rate": capital_params.transition_cost_rate,
    }

    curve = pd.concat(curves.values(), axis=1).sort_index().ffill().dropna()
    btc_curve = load_btc_curve(market, curve.index)
    curve = curve.reindex(btc_curve.index)
    curve["BTC"] = btc_curve
    report_metrics["BTC"] = {
        "strategy": STRATEGIES["BTC"][0],
        **benchmark_metrics(curve["BTC"]),
        "fee_rebate_rate": REBATE_RATE,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    curve.to_csv(OUT_DIR / "equity_curves.csv")
    drawdowns = curve / curve.cummax() - 1.0
    drawdowns.to_csv(OUT_DIR / "drawdown_curves.csv")
    for code, result in {"V4": v4_result, "V4.1": v41_result, "V4.2_direction": v42_result}.items():
        result.equity.rename("equity").to_csv(OUT_DIR / f"{code.lower().replace('.', '_')}_micro_equity.csv")
        result.fills.to_csv(OUT_DIR / f"{code.lower().replace('.', '_')}_micro_fills.csv", index=False)
    combined.to_csv(OUT_DIR / "v4_2_combined_equity.csv")

    summary = pd.DataFrame([
        metrics_row(
            code,
            STRATEGIES[code][0],
            report_metrics[code],
            report_metrics[code].get("effective_taker_fee_bps")
            or report_metrics[code].get("effective_direction_taker_fee_bps"),
        )
        for code in SERIES
    ])
    summary.to_csv(OUT_DIR / "summary_metrics.csv", index=False)
    annual_table(curve).to_csv(OUT_DIR / "annual_returns_drawdowns.csv", index=False)
    payload = {
        "data_start": curve.index[0].isoformat(),
        "data_end": curve.index[-1].isoformat(),
        "method": "minute execution with mark-price margin checks and funding; V4.2 adds causal neutral sleeve",
        "fee_rebate_rate": REBATE_RATE,
        "fee_method": "effective fee = configured fee * (1 - rebate rate); rebate is applied to trading fees only",
        "execution": {
            "V4_V4.1_base_taker_fee_bps": base_fee_bps,
            "V4_V4.1_effective_taker_fee_bps": v4_fee_bps,
            "V4.2_base_direction_taker_fee_bps": v42_base_fee_bps,
            "V4.2_effective_direction_taker_fee_bps": v42_fee_bps,
            "V4.2_base_spot_fee_bps": 7.0,
            "V4.2_effective_spot_fee_bps": capital_params.spot_fee_bps,
            "V4.2_base_futures_fee_bps": 2.8,
            "V4.2_effective_futures_fee_bps": capital_params.futures_fee_bps,
        },
        "strategies": report_metrics,
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=float) + "\n",
        encoding="utf-8",
    )

    subtitle = "V4、V4.1、V4.2 与 BTC · 2020-01-01 至 2026-08-25 08:00 UTC · 逐分钟成交复测 · 手续费返佣30%"
    note = "含手续费、30%返佣、基础与冲击滑点、资金费、成交量约束及盘中保证金检查；V4.2含资金费中性覆盖"
    render_options = {
        "series": SERIES,
        "names": NAMES,
        "colors": COLORS,
        "highlighted": HIGHLIGHTED,
        "subtitle": subtitle,
        "note": note,
        "title": "BTCUSDT V4 系列累计收益曲线",
    }
    render_single(curve, OUT_DIR / "equity_curve_v4_family_micro.png", "equity", **render_options)
    render_single(
        curve,
        OUT_DIR / "drawdown_curve_v4_family_micro.png",
        "drawdown",
        **{**render_options, "title": "BTCUSDT V4 系列峰值回撤曲线"},
    )
    render(
        curve,
        OUT_DIR / "equity_drawdown_v4_family_micro.png",
        series=SERIES,
        names=NAMES,
        colors=COLORS,
        highlighted=HIGHLIGHTED,
        title="BTCUSDT V4 系列收益与回撤",
        subtitle=subtitle,
        note=note,
    )
    print(summary.to_string(index=False), flush=True)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=float), flush=True)


if __name__ == "__main__":
    main()
