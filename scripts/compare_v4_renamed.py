#!/usr/bin/env python3
"""Compare the five renamed V4-family strategies under one execution model.

The historical reports are left untouched.  This script performs an additional
same-window comparison from 2020-01-01 through 2026-08-01 with a common 30%
trading-fee rebate.  V4.2 variants include the causal funding-neutral overlay;
the other variants are direction-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from btc_regime.backtest import calculate_metrics  # noqa: E402
from btc_regime.data import iter_intrabar_months, load_funding, load_market_data  # noqa: E402
from btc_regime.micro_backtest import MicroBacktestConfig, micro_period_metrics, run_micro_backtest  # noqa: E402
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402
from btc_regime.v42 import V42CapitalParams, combine_direction_and_neutral, generate_neutral_sleeve  # noqa: E402
from btc_regime.v43 import V43Params, generate_v43_signals  # noqa: E402


START = "2020-01-01"
END = "2026-08-01"
REBATE_RATE = 0.30
BASE_TAKER_FEE_BPS = 4.0
BASE_MAKER_FEE_BPS = 0.2
OUTPUT_DEFAULT = ROOT / "reports/v4_family_renamed_rebate30"


STRATEGIES = {
    "V4": {
        "kind": "direction",
        "label": "V4 基线",
        "config": ROOT / "configs/aggressive_adaptive_v3_params.json",
        "legacy_report": "reports/aggressive_adaptive_v3_micro/micro_metrics.json",
    },
    "V4.1.1": {
        "kind": "direction",
        "label": "原 V4.1（局部优化）",
        "config": ROOT / "configs/v4_1_1_params.json",
        "legacy_report": "reports/v4_refined_micro/micro_metrics.json",
    },
    "V4.1.2": {
        "kind": "direction_v43",
        "label": "新 V4.3（maker + 止损）",
        "config": ROOT / "configs/v4_1_2_params.json",
        "legacy_report": "reports/v4_3_rebate30/report.json",
    },
    "V4.2.1": {
        "kind": "v42",
        "label": "原 V4.2（方向 + 中性覆盖）",
        "config": ROOT / "configs/v4_2_1_params.json",
        "legacy_report": "reports/v4_2_2020_2026_08_25/report.json",
    },
    "V4.2.2": {
        "kind": "v42_v43",
        "label": "新 V4.2（maker + 止损 + 中性覆盖）",
        "config": ROOT / "configs/v4_2_2_params.json",
        "legacy_report": "reports/v4_2_rebate30/report.json",
    },
}


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _portfolio_periods(equity: pd.Series) -> dict[str, dict[str, float]]:
    periods = {
        "train_2020_2022": ("2020-01-01", "2023-01-01"),
        "validation_2023_2024": ("2023-01-01", "2025-01-01"),
        "holdout_2025_2026_07": ("2025-01-01", "2026-08-01"),
        "full_2020_2026_07": ("2020-01-01", "2026-08-01"),
    }
    result: dict[str, dict[str, float]] = {}
    for label, (start, end) in periods.items():
        start_ts = pd.Timestamp(start, tz="UTC")
        end_ts = pd.Timestamp(end, tz="UTC")
        window = equity.loc[(equity.index >= start_ts) & (equity.index <= end_ts)]
        if not window.empty:
            result[label] = calculate_metrics(
                window,
                window.pct_change().dropna(),
                pd.DataFrame(),
                2190,
            )
    return result


def _micro_config(*, maker: bool, maker_offset: float) -> MicroBacktestConfig:
    return MicroBacktestConfig(
        initial_cash=10_000.0,
        taker_fee_bps=BASE_TAKER_FEE_BPS * (1 - REBATE_RATE),
        maker_fee_bps=BASE_MAKER_FEE_BPS * (1 - REBATE_RATE),
        maker_offset_bps=maker_offset,
        maker_order_timeout_minutes=60,
        maker_enabled=maker,
        maker_exit_enabled=False,
        base_slippage_bps=1.0,
        impact_bps=8.0,
        max_minute_participation=0.02,
        liquidation_fee_bps=50.0,
    )


def _run_direction(
    signaled: pd.DataFrame,
    funding: pd.DataFrame,
    raw_dir: str | Path,
    config: MicroBacktestConfig,
) -> object:
    return run_micro_backtest(
        signaled,
        iter_intrabar_months(raw_dir, start=START, end=END),
        funding,
        config,
    )


def _combined(
    direction_result: object,
    neutral: pd.DataFrame,
    capital: V42CapitalParams,
    signaled: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, float]]:
    signal = signaled["signal"].copy()
    signal.index = signal.index + pd.Timedelta(hours=4)
    return combine_direction_and_neutral(direction_result.equity, neutral, capital, signal)


def _compact_params(params: StrategyParams, *, capital: V42CapitalParams | None = None) -> dict[str, object]:
    keys = [
        "ema_fast", "ema_slow", "atr_period", "adx_enter", "adx_exit",
        "trend_separation_atr", "rsi_period", "rsi_entry", "rsi_exit",
        "bb_period", "bb_std", "target_vol", "max_leverage", "trend_scale",
        "rebound_scale", "rebalance_bars", "vol_risk_enabled",
        "funding_factor_enabled", "funding_lookback", "funding_factor_scale",
        "downside_allocation_enabled", "downside_stress_scale",
        "drawdown_brake_enabled", "price_drawdown_enter", "price_drawdown_exit",
        "price_drawdown_scale", "stop_atr", "take_profit_atr", "trailing_atr",
        "downside_stop_atr", "downside_lookback", "downside_return_threshold",
        "downside_vol_ratio", "downside_confirmation_bars", "exit_cooldown_bars",
        "max_hold_bars", "maker_enabled", "maker_fee_bps", "maker_offset_bps",
        "maker_order_timeout_minutes", "maker_exit_enabled",
    ]
    output = {key: getattr(params, key, None) for key in keys}
    output["fee_rebate_rate"] = REBATE_RATE
    if capital is not None:
        output["capital_overlay"] = capital.to_dict()
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    args = parser.parse_args()

    market = load_market_data(args.raw_dir, start=START, end=END)
    funding = load_funding(args.raw_dir, start=START, end=END)
    capital_base = V42CapitalParams(**_read(ROOT / "configs/v4_2_capital_params.json"))
    capital_rebate = V42CapitalParams(
        **{
            **capital_base.to_dict(),
            "spot_fee_bps": capital_base.spot_fee_bps * (1 - REBATE_RATE),
            "futures_fee_bps": capital_base.futures_fee_bps * (1 - REBATE_RATE),
        }
    )
    neutral_rebate = generate_neutral_sleeve(funding, capital_rebate)

    summary_rows: list[dict[str, object]] = []
    parameter_rows: list[dict[str, object]] = []
    payload_strategies: dict[str, object] = {}
    curves: dict[str, pd.Series] = {}

    for code, meta in STRATEGIES.items():
        raw_params = _read(meta["config"])
        kind = meta["kind"]
        if kind in {"direction_v43", "v42_v43"}:
            params: StrategyParams = V43Params(**raw_params)
            signaled = generate_v43_signals(market, params)
            maker = True
            maker_offset = float(params.maker_offset_bps)
        else:
            params = StrategyParams(**raw_params)
            signaled = generate_signals(market, params)
            maker = False
            maker_offset = 0.5

        direction = _run_direction(
            signaled,
            funding,
            args.raw_dir,
            _micro_config(maker=maker, maker_offset=maker_offset),
        )
        if kind in {"v42", "v42_v43"}:
            capital = capital_rebate
            neutral = neutral_rebate
            combined, combined_metrics = _combined(direction, neutral, capital, signaled)
            curve = combined["combined_equity"].rename(code)
            metrics = combined_metrics
            periods = _portfolio_periods(curve)
            direction_periods = micro_period_metrics(direction)
            capital_payload = capital.to_dict()
        else:
            capital = None
            curve = direction.equity.rename(code)
            metrics = direction.metrics
            periods = micro_period_metrics(direction)
            direction_periods = periods
            capital_payload = None
        curves[code] = curve

        holdout = periods.get("holdout_2025_2026_07", {})
        row = {
            "code": code,
            "strategy": meta["label"],
            "kind": kind,
            "final_equity": metrics.get("final_equity"),
            "total_return": metrics.get("total_return"),
            "cagr": metrics.get("cagr"),
            "annualized_volatility": metrics.get("annualized_volatility"),
            "sharpe": metrics.get("sharpe"),
            "sortino": metrics.get("sortino"),
            "max_drawdown": metrics.get("max_drawdown"),
            "holdout_rebased_final_equity": 10_000 * (1 + holdout.get("total_return", 0.0)),
            "holdout_cagr": holdout.get("cagr"),
            "holdout_sharpe": holdout.get("sharpe"),
            "holdout_max_drawdown": holdout.get("max_drawdown"),
            "direction_final_equity": direction.metrics.get("final_equity"),
            "direction_fees_paid": direction.metrics.get("fees_paid"),
            "direction_funding_paid": direction.metrics.get("funding_paid"),
            "maker_fill_ratio": direction.metrics.get("maker_fill_ratio", 0.0),
            "maker_fee_saved_vs_taker": direction.metrics.get("maker_fee_saved_vs_taker", 0.0),
            "maker_fill_count": direction.metrics.get("maker_fill_count", 0.0),
            "taker_fill_count": direction.metrics.get("taker_fill_count", 0.0),
            "liquidation_count": direction.metrics.get("liquidation_count", 0.0),
        }
        summary_rows.append(row)
        parameter_rows.append(
            {
                "code": code,
                "strategy": meta["label"],
                "config": str(meta["config"].relative_to(ROOT)),
                **_compact_params(params, capital=capital),
            }
        )
        payload_strategies[code] = {
            "label": meta["label"],
            "kind": kind,
            "config": str(meta["config"].relative_to(ROOT)),
            "legacy_report_unchanged": meta["legacy_report"],
            "parameters": params.to_dict(),
            "capital_parameters": capital_payload,
            "metrics": metrics,
            "periods": periods,
            "direction_metrics": direction.metrics,
            "direction_periods": direction_periods,
        }

    curve_frame = pd.concat(curves.values(), axis=1).sort_index().ffill().dropna()
    args.output.mkdir(parents=True, exist_ok=True)
    curve_frame.to_csv(args.output / "equity_curves.csv")
    pd.DataFrame(summary_rows).to_csv(args.output / "summary_metrics.csv", index=False)
    pd.DataFrame(parameter_rows).to_csv(args.output / "parameters.csv", index=False)

    payload = {
        "version_map": {
            "V4": "V4",
            "V4.1.1": "原 V4.1",
            "V4.1.2": "新 V4.3",
            "V4.2.1": "原 V4.2",
            "V4.2.2": "新 V4.2",
        },
        "data": {
            "start": START,
            "end": END,
            "market_source": "Binance USD-M 4h archive",
            "intrabar_source": "Binance USD-M 1m archive",
            "funding_source": "Binance USD-M funding archive",
        },
        "common_execution": {
            "base_taker_fee_bps": BASE_TAKER_FEE_BPS,
            "base_maker_fee_bps": BASE_MAKER_FEE_BPS,
            "fee_rebate_rate": REBATE_RATE,
            "effective_taker_fee_bps": BASE_TAKER_FEE_BPS * (1 - REBATE_RATE),
            "effective_maker_fee_bps": BASE_MAKER_FEE_BPS * (1 - REBATE_RATE),
            "base_slippage_bps": 1.0,
            "impact_bps": 8.0,
            "max_minute_participation": 0.02,
        },
        "strategies": payload_strategies,
        "summary": summary_rows,
        "method": {
            "comparison": "same-window additional replay; original reports are preserved",
            "v42_neutral": "rebate-adjusted V4.2 funding-neutral sleeve",
            "holdout": "period return/CAGR/Sharpe are sliced from the continuous run; holdout_rebased_final_equity resets to 10,000 USDT",
            "limitations": [
                "maker fills use deterministic 1m OHLC touch and do not model order-book queue",
                "V4.2 neutral sleeve excludes spot-perpetual basis PnL and spot depth",
                "the original V4.2 report ends 2026-08-25; the comparison window is deliberately aligned to 2026-08-01",
            ],
        },
    }
    (args.output / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=float) + "\n",
        encoding="utf-8",
    )
    print(pd.DataFrame(summary_rows).to_string(index=False))


if __name__ == "__main__":
    main()
