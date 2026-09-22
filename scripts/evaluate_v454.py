"""Evaluate the V4.5.4 V4.2-style capital overlay on the frozen V4.5.3 signal."""
from __future__ import annotations

from dataclasses import asdict, replace
from itertools import chain
import json
from pathlib import Path

import pandas as pd

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from btc_regime.v42 import V42CapitalParams
from btc_regime.v441_research import daily_equity
from btc_regime.v453 import V453Params
from btc_regime.v454 import combine_v454_direction_and_neutral, generate_v454_neutral_sleeve, generate_v454_signals
from evaluate_v441 import minute_batches
from evaluate_v444 import inputs
from research_v452 import profile_signal


ROOT = Path("reports/v4_5_4")
CONFIG = json.loads(Path("configs/v4_5_4_params.json").read_text())
SIGNAL_ITEM = {"id": "b022", "kind": "v452", "params": CONFIG["signal_params"]}
WINDOWS = {
    "full": ("2020-01-01", "2026-08-01"),
    "post2024": ("2024-01-01", "2026-08-01"),
    "later": ("2026-01-15", "2026-08-01"),
}


def window_metrics(equity: pd.Series, start: str, end: str) -> dict[str, float]:
    a, b = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    e = equity.loc[(equity.index >= a) & (equity.index <= b)]
    daily = daily_equity(e)
    returns = daily.pct_change().dropna()
    years = max((e.index[-1] - e.index[0]).total_seconds() / (365.25 * 86400), 1 / 365.25)
    sd = returns.std(ddof=1)
    return {
        "total_return": float(e.iloc[-1] / e.iloc[0] - 1),
        "cagr": float((e.iloc[-1] / e.iloc[0]) ** (1 / years) - 1),
        "sharpe": float(returns.mean() / sd * 365.25**0.5) if sd > 0 else 0.0,
        "annualized_volatility": float(sd * 365.25**0.5),
        "max_drawdown": float((e / e.cummax() - 1).min()),
        "days": int(len(returns)),
    }


def frequency(result, start: str, end: str) -> dict[str, float]:
    a, b = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    trades = result.trades.loc[(result.trades.exit_time >= a) & (result.trades.exit_time < b)]
    fills = result.fills.copy()
    fills["timestamp"] = pd.to_datetime(fills["timestamp"], utc=True)
    fills = fills.loc[(fills.timestamp >= a) & (fills.timestamp < b)]
    years = (b - a).total_seconds() / (365.25 * 86400)
    return {
        "cycles": int(len(trades)),
        "cycles_per_year": float(len(trades) / years),
        "fills": int(len(fills)),
        "fills_per_year": float(len(fills) / years),
        "short_cycles": int((trades.side == "short").sum()),
        "long_cycles": int((trades.side == "long").sum()),
        "median_holding_hours": float(
            ((trades.exit_time - trades.entry_time).dt.total_seconds() / 3600).median()
        ) if len(trades) else 0.0,
    }


def portfolio_windows(equity: pd.Series, result, neutral: pd.DataFrame) -> dict[str, dict[str, object]]:
    output = {}
    for key, (start, end) in WINDOWS.items():
        window_neutral = neutral.loc[
            (neutral.index >= pd.Timestamp(start, tz="UTC"))
            & (neutral.index < pd.Timestamp(end, tz="UTC"))
        ]
        output[key] = {
            "metrics": window_metrics(equity, start, end),
            "frequency": frequency(result, start, end),
            "neutral_active_fraction": float(window_neutral.active.mean()) if len(window_neutral) else 0.0,
            "neutral_state_changes": int(window_neutral.state_changed.sum()) if len(window_neutral) else 0,
        }
    return output


def run_case(name: str, stress: str) -> dict[str, object]:
    data, funding, extension = inputs()
    raw_signal = profile_signal(data, SIGNAL_ITEM)
    signal = generate_v454_signals(
        data,
        V453Params(**CONFIG["signal_params"]),
        direction_allocation=CONFIG["capital_overlay"]["direction_allocation"],
        long_signals=raw_signal,
    )
    capital = V42CapitalParams(**CONFIG["capital_overlay"])
    rebate = CONFIG["execution"]["rebate_fraction"]
    maker_fee = CONFIG["execution"]["effective_maker_bps"]
    taker_fee = CONFIG["execution"]["effective_taker_bps"]
    cost_multiplier = 1.0
    if stress == "double_cost":
        taker_fee *= 2
        maker_fee *= 2
        cost_multiplier = 2.0
        signal = signal.copy()
    elif stress == "no_rebate":
        rebate = 0.0
        maker_fee = CONFIG["execution"]["published_maker_bps"]
        taker_fee = CONFIG["execution"]["published_taker_bps"]
    elif stress == "delay_1h":
        signal = signal.copy()
        signal.index += pd.Timedelta(hours=1)
    capital = replace(capital, spot_fee_bps=capital.spot_fee_bps * cost_multiplier,
                      futures_fee_bps=capital.futures_fee_bps * cost_multiplier,
                      slippage_per_leg_bps=capital.slippage_per_leg_bps * cost_multiplier)
    neutral = generate_v454_neutral_sleeve(funding, capital, rebate_fraction=rebate)
    config = MicroBacktestConfig(
        signal_interval_minutes=60,
        equity_interval_minutes=60,
        periods_per_year=8760,
        conservative_protection=True,
        taker_fee_bps=taker_fee,
        maker_fee_bps=maker_fee,
        maker_enabled=True,
        maker_offset_bps=CONFIG["execution"]["maker_offset_bps"],
        maker_order_timeout_minutes=CONFIG["execution"]["maker_order_timeout_minutes"],
        maker_exit_enabled=False,
        base_slippage_bps=1 * cost_multiplier,
        impact_bps=8 * cost_multiplier,
    )
    batches = chain(minute_batches(Path("data/v441"), "2020-01-01", "2026-08-01"), [extension])
    result = run_micro_backtest(signal, batches, funding, config)
    direction_4h = result.equity.resample("4h", label="left", closed="left").last().dropna()
    signal_4h = signal.signal.resample("4h", label="left", closed="left").last()
    signal_4h = signal_4h.reindex(direction_4h.index).ffill().fillna(0.0)
    combined, _ = combine_v454_direction_and_neutral(direction_4h, neutral, capital, signal_4h)
    windows = portfolio_windows(combined.combined_equity, result, neutral)
    execution = asdict(config)
    execution.update({"rebate_fraction": rebate, "neutral_cost_multiplier": cost_multiplier})
    row = {
        "strategy": name,
        "stress": stress,
        "windows": windows,
        "execution": execution,
        "neutral_parameters": capital.to_dict(),
        "neutral_metrics": {
            "total_return": float(neutral.neutral_equity.iloc[-1] - 1),
            "active_fraction": float(neutral.active.mean()),
            "state_changes": int(neutral.state_changed.sum()),
        },
        "execution_metrics": result.metrics,
    }
    destination = ROOT / f"{name}__{stress}"
    destination.mkdir(parents=True, exist_ok=True)
    combined.to_csv(destination / "combined_equity.csv")
    result.equity.to_csv(destination / "direction_equity.csv", header=True)
    result.trades.to_csv(destination / "trades.csv", index=False)
    result.fills.to_csv(destination / "fills.csv", index=False)
    neutral.to_csv(destination / "neutral_schedule.csv")
    (destination / "report.json").write_text(json.dumps(row, indent=2, default=float) + "\n")
    print(name, stress, windows["post2024"]["metrics"], flush=True)
    return row


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    rows = [run_case("V4.5.4", stress) for stress in ["base", "double_cost", "no_rebate", "delay_1h"]]
    (ROOT / "evaluation.json").write_text(json.dumps(rows, indent=2, default=float) + "\n")


if __name__ == "__main__":
    main()
