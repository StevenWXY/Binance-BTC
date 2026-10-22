"""Execution and carry stress replay for the frozen V4.6.1 candidate."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest  # noqa: E402
from btc_regime.v461 import V461Params, generate_v461_signals  # noqa: E402
import run_bitget_three_latest as latest  # noqa: E402


DATA = ROOT / "data" / "bitget_20261011"
OUTPUT = ROOT / "reports" / "v4_6_1" / "execution_stress.csv"
START = pd.Timestamp("2020-01-01", tz="UTC")


def monthly_stats(equity: pd.Series, end: pd.Timestamp) -> dict[str, float]:
    daily = equity.resample("1D", closed="right", label="right").last().dropna()
    month_end = daily.resample("ME").last().dropna()
    monthly = month_end.pct_change().dropna()
    last = ((end.tz_localize(None).to_period("M") - 1).to_timestamp(how="end").tz_localize("UTC"))
    monthly = monthly.loc[monthly.index <= last]
    return {
        "monthly_mean": float(monthly.mean()),
        "monthly_std": float(monthly.std(ddof=1)),
        "positive_month_fraction": float((monthly > 0).mean()),
        "worst_month": float(monthly.min()),
    }


def main() -> None:
    cached = pd.read_pickle(DATA / "candles_5m.pkl")
    cached.index = pd.to_datetime(cached.index, utc=True)
    end = cached.index.max() + pd.Timedelta(minutes=5)
    latest.START = START
    latest.END = end
    raw, hourly, _, funding = latest.load_data(DATA)
    params = V461Params()
    signals = generate_v461_signals(hourly, params)
    base = MicroBacktestConfig(
        initial_cash=10_000.0,
        taker_fee_bps=2.4,
        maker_fee_bps=0.8,
        maker_enabled=False,
        maker_exit_enabled=False,
        conservative_protection=True,
        signal_interval_minutes=60,
        equity_interval_minutes=60,
        execution_bar_minutes=5,
        periods_per_year=8760,
        base_slippage_bps=1.0,
        impact_bps=8.0,
        max_minute_participation=0.02,
    )
    scenarios = {
        "base_all_taker": (base, 1.0),
        "fees_plus_50pct": (replace(base, taker_fee_bps=3.6), 1.0),
        "slippage_double": (replace(base, base_slippage_bps=2.0, impact_bps=16.0), 1.0),
        "funding_2x": (base, 2.0),
    }
    rows = []
    for name, (config, funding_scale) in scenarios.items():
        scenario_funding = funding.copy()
        scenario_funding["funding_rate"] = scenario_funding["funding_rate"] * funding_scale
        result = run_micro_backtest(signals, latest.batches(raw), scenario_funding, config)
        years = max((result.equity.index[-1] - result.equity.index[0]).total_seconds() / (365.25 * 86400), 1 / 365.25)
        row = {
            "scenario": name,
            "total_return": float(result.equity.iloc[-1] / result.equity.iloc[0] - 1),
            "cagr": float((result.equity.iloc[-1] / result.equity.iloc[0]) ** (1 / years) - 1),
            "annualized_volatility": result.metrics.get("annualized_volatility", np.nan),
            "max_drawdown": result.metrics.get("max_drawdown", np.nan),
            "sharpe": result.metrics.get("sharpe", np.nan),
            "fees_paid": result.metrics.get("fees_paid", np.nan),
            "liquidations": result.metrics.get("liquidation_count", np.nan),
        }
        row.update(monthly_stats(result.equity, end))
        rows.append(row)
    frame = pd.DataFrame(rows)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUTPUT, index=False)
    print(frame.to_string(index=False))


if __name__ == "__main__":
    main()
