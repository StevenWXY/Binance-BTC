#!/usr/bin/env python3
"""Run V1-V6 with minute execution through 2026-08-25 and write curve data."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.data import iter_intrabar_months  # noqa: E402
from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest  # noqa: E402
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402
from btc_regime.v6 import V6Params, generate_v6_signals  # noqa: E402


START = "2020-01-01"
END = "2026-08-25 08:00"
OUT_DIR = ROOT / "reports/micro_curve_v41_v6_2020_2026_08_25"
MARKET_PATH = ROOT / "reports/annual_2020_2026_08_25/market_4h_full.csv"
FUNDING_PATH = ROOT / "reports/annual_2020_2026_08_25/funding_full.csv"

STRATEGIES = {
    "V1": ("基础趋势跟随与 ATR 仓位", ROOT / "configs/aggressive_params.json"),
    "V2": ("资金费率拥挤过滤趋势", ROOT / "configs/aggressive_vol_carry_params.json"),
    "V3": ("波动率与下行风险自适应", ROOT / "configs/aggressive_adaptive_params.json"),
    "V4.1": ("稳健长多趋势-反弹混合", ROOT / "configs/v4_refined_params.json"),
    "V5": ("谨慎对称趋势与空头确认", ROOT / "configs/aggressive_adaptive_v4_short_params.json"),
}


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    market = pd.read_csv(MARKET_PATH, index_col=0, parse_dates=True)
    market.index = pd.to_datetime(market.index, utc=True, format="mixed")
    market = market.loc[(market.index >= START) & (market.index < pd.Timestamp(END, tz="UTC"))]
    funding = pd.read_csv(FUNDING_PATH, index_col=0, parse_dates=True)
    funding.index = pd.to_datetime(funding.index, utc=True, format="mixed")
    funding = funding.loc[
        (funding.index >= pd.Timestamp(START, tz="UTC"))
        & (funding.index < pd.Timestamp(END, tz="UTC"))
    ]
    return market, funding


def benchmark_metrics(price: pd.Series) -> dict[str, float]:
    returns = price.pct_change().dropna()
    years = (price.index[-1] - price.index[0]).total_seconds() / (365.25 * 86400)
    drawdown = price / price.cummax() - 1.0
    volatility = returns.std(ddof=1) * np.sqrt(365 * 6)
    return {
        "total_return": float(price.iloc[-1] / price.iloc[0] - 1.0),
        "cagr": float((price.iloc[-1] / price.iloc[0]) ** (1 / years) - 1.0),
        "annualized_volatility": float(volatility),
        "sharpe": float(returns.mean() / returns.std(ddof=1) * np.sqrt(365 * 6)),
        "max_drawdown": float(drawdown.min()),
        "final_equity": float(price.iloc[-1]),
    }


def main() -> None:
    market, funding = load_inputs()
    config = MicroBacktestConfig(
        initial_cash=10_000.0,
        taker_fee_bps=4.0,
        base_slippage_bps=1.0,
        impact_bps=8.0,
        max_minute_participation=0.02,
        liquidation_fee_bps=50.0,
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    curves: dict[str, pd.Series] = {}
    metrics: dict[str, dict[str, object]] = {}

    for code, (name, path) in STRATEGIES.items():
        print(f"Running {code}...", flush=True)
        params = StrategyParams(**json.loads(path.read_text(encoding="utf-8")))
        result = run_micro_backtest(
            generate_signals(market, params),
            iter_intrabar_months(ROOT / "data/raw", start=START, end=END),
            funding,
            config,
        )
        curves[code] = result.equity.rename(code)
        metrics[code] = {"strategy": name, **result.metrics}
        result.equity.to_csv(OUT_DIR / f"{code.lower().replace('.', '_')}_micro_equity.csv")

    print("Running V6...", flush=True)
    v6_params = V6Params(**json.loads((ROOT / "configs/v6_params.json").read_text(encoding="utf-8")))
    v6_result = run_micro_backtest(
        generate_v6_signals(market, v6_params),
        iter_intrabar_months(ROOT / "data/raw", start=START, end=END),
        funding,
        config,
    )
    curves["V6"] = v6_result.equity.rename("V6")
    metrics["V6"] = {"strategy": "置信度驱动多周期动态风险", **v6_result.metrics}
    v6_result.equity.to_csv(OUT_DIR / "v6_micro_equity.csv")

    curve = pd.concat(curves.values(), axis=1).sort_index().ffill().dropna()
    close_at_boundary = market["close"].copy()
    close_at_boundary.index = close_at_boundary.index + pd.Timedelta(hours=4)
    btc = close_at_boundary.reindex(curve.index).ffill().dropna()
    curve = curve.reindex(btc.index)
    curve["BTC"] = btc / btc.iloc[0] * 10_000.0
    metrics["BTC"] = {"strategy": "BTCUSDT 价格基准", **benchmark_metrics(curve["BTC"])}

    curve.to_csv(OUT_DIR / "equity_curves.csv")
    (curve / curve.cummax() - 1.0).to_csv(OUT_DIR / "drawdown_curves.csv")
    summary = pd.DataFrame([
        {
            "code": code,
            "strategy": row["strategy"],
            "final_equity": row["final_equity"],
            "total_return": row["total_return"],
            "cagr": row["cagr"],
            "sharpe": row["sharpe"],
            "sortino": row.get("sortino"),
            "max_drawdown": row["max_drawdown"],
            "fill_count": row.get("fill_count"),
            "liquidation_count": row.get("liquidation_count"),
        }
        for code, row in metrics.items()
    ])
    summary.to_csv(OUT_DIR / "summary_metrics.csv", index=False)
    payload = {
        "data_start": curve.index[0].isoformat(),
        "data_end": curve.index[-1].isoformat(),
        "method": "minute execution and mark-price margin simulation",
        "execution": config.__dict__,
        "funding_source": str(FUNDING_PATH.relative_to(ROOT)),
        "strategies": metrics,
    }
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(summary.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
