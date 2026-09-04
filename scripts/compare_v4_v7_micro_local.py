#!/usr/bin/env python3
"""Compare V4 and V7 using local Binance 1m archives."""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from dataclasses import asdict
from dataclasses import replace
from pathlib import Path

import pandas as pd
import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter, StrMethodFormatter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.data import (  # noqa: E402
    load_funding,
    load_market_data,
    load_ohlc_archive,
    load_ohlc_archive_bytes,
    resolve_intrabar_raw_dir,
)
from btc_regime.micro_backtest import (  # noqa: E402
    MicroBacktestConfig,
    micro_period_metrics,
    run_micro_backtest,
    write_micro_report,
)
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402
from btc_regime.v7 import V7Params, generate_v7_signals  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local micro comparison for V4 and V7.")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument("--raw-dir", default=ROOT / "data/plain_raw", type=Path)
    parser.add_argument("--source-zip", type=Path, help="Read nested Binance archives directly from data.zip")
    parser.add_argument(
        "--v7-params",
        type=Path,
        default=ROOT / "configs/v7_params.json",
        help="V7 parameter JSON path (defaults to the working-tree configuration)",
    )
    parser.add_argument(
        "--v7-overrides",
        default="{}",
        help="JSON object merged into the selected V7 parameter file for experiments",
    )
    parser.add_argument("--v7-target-vol", type=float)
    parser.add_argument("--v7-short-scale", type=float)
    parser.add_argument("--v7-stop-atr", type=float)
    parser.add_argument("--v7-exit-confirm", type=int)
    parser.add_argument("--v7-breakout-buffer", type=float)
    parser.add_argument("--strategy-drawdown", action="store_true")
    parser.add_argument("--dd-level-1", type=float, default=0.15)
    parser.add_argument("--dd-scale-1", type=float, default=0.90)
    parser.add_argument("--dd-level-2", type=float, default=0.25)
    parser.add_argument("--dd-scale-2", type=float, default=0.75)
    parser.add_argument("--dd-level-3", type=float, default=0.35)
    parser.add_argument("--dd-scale-3", type=float, default=0.50)
    parser.add_argument("--v41-params", type=Path, default=ROOT / "configs/v4_refined_params.json")
    parser.add_argument("--v42-params", type=Path, required=True)
    parser.add_argument(
        "--output",
        default=ROOT / "reports/v4_v7_micro_local_2020_2026_07",
        type=Path,
    )
    return parser.parse_args()


def render_curves(equity: pd.DataFrame, output: Path) -> None:
    drawdown = equity / equity.cummax() - 1.0
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), dpi=160, sharex=True, height_ratios=[2, 1])
    colors = {"V4": "#0891b2", "V7": "#f59e0b", "BTC": "#334155"}
    for code in equity.columns:
        ax1.plot(equity.index, equity[code], label=code, color=colors.get(code, None), lw=2.0)
        ax2.plot(drawdown.index, drawdown[code], label=code, color=colors.get(code, None), lw=1.5)
    ax1.set_title("BTCUSDT Local 1m Micro Backtest: V4 vs V7")
    ax1.set_ylabel("Equity (USDT)")
    ax2.set_ylabel("Drawdown")
    ax2.set_xlabel("Date (UTC)")
    ax1.yaxis.set_major_formatter(StrMethodFormatter("${x:,.0f}"))
    ax2.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax2.xaxis.set_major_locator(mdates.YearLocator())
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax1.grid(True, alpha=0.25)
    ax2.grid(True, alpha=0.25)
    ax1.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def load_local_market(raw_dir: Path, start: str, end: str, source_zip: Path | None = None) -> pd.DataFrame:
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    if source_zip is not None:
        with zipfile.ZipFile(source_zip) as source:
            market_parts = [
                load_ohlc_archive_bytes(source.read(name))
                for name in source.namelist()
                if re.fullmatch(r"data/raw/klines/BTCUSDT-4h-\d{4}-\d{2}\.zip", name)
            ]
            funding_parts = []
            for name in source.namelist():
                if not re.fullmatch(r"data/raw/funding/BTCUSDT-fundingRate-\d{4}-\d{2}\.zip", name):
                    continue
                nested = zipfile.ZipFile(io.BytesIO(source.read(name)))
                payload = nested.read(nested.namelist()[0])
                part = pd.read_csv(io.BytesIO(payload))
                part["timestamp"] = pd.to_datetime(part["calc_time"], unit="ms", utc=True)
                part["funding_rate"] = pd.to_numeric(part["last_funding_rate"], errors="coerce")
                funding_parts.append(part.set_index("timestamp")[["funding_rate"]])
        market = pd.concat(market_parts).sort_index()
        funding = pd.concat(funding_parts).sort_index()
        market = market.loc[(market.index >= start_ts) & (market.index < end_ts)].copy()
        funding = funding.loc[(funding.index >= start_ts) & (funding.index < end_ts)]
        funding_4h = funding["funding_rate"].groupby(funding.index.floor("4h")).sum()
        market["funding_rate"] = funding_4h.reindex(market.index, fill_value=0.0)
        return market
    market = load_market_data(raw_dir, start=start, end=end, interval="4h")
    funding = load_funding(raw_dir, start=start, end=end)
    market = market.loc[(market.index >= start_ts) & (market.index < end_ts)].sort_index()
    funding = funding.loc[(funding.index >= start_ts) & (funding.index < end_ts)].sort_index()
    funding_4h = funding["funding_rate"].groupby(funding.index.floor("4h")).sum()
    market["funding_rate"] = funding_4h.reindex(market.index, fill_value=0.0)
    return market


def iter_local_batches(raw_dir: Path, start: str, end: str, source_zip: Path | None = None):
    if source_zip is not None:
        with zipfile.ZipFile(source_zip) as source:
            trade_files = {
                name.removeprefix("data/raw/klines/BTCUSDT-1m-").removesuffix(".zip"): name
                for name in source.namelist()
                if re.fullmatch(r"data/raw/klines/BTCUSDT-1m-\d{4}-\d{2}\.zip", name)
            }
            mark_files = {
                name.removeprefix("data/raw/mark_price/BTCUSDT-1m-").removesuffix(".zip"): name
                for name in source.namelist()
                if re.fullmatch(r"data/raw/mark_price/BTCUSDT-1m-\d{4}-\d{2}\.zip", name)
            }
            for period in sorted(set(trade_files) & set(mark_files)):
                trade = load_ohlc_archive_bytes(source.read(trade_files[period])).add_prefix("trade_")
                mark = load_ohlc_archive_bytes(source.read(mark_files[period]))[["open", "high", "low", "close"]].add_prefix("mark_")
                batch = trade.join(mark, how="inner")
                batch = batch.loc[(batch.index >= pd.Timestamp(start, tz="UTC")) & (batch.index < pd.Timestamp(end, tz="UTC"))]
                if not batch.empty:
                    yield batch
        return
    raw_path = resolve_intrabar_raw_dir(raw_dir)
    prefix = "BTCUSDT-1m-"
    trade_files = {
        path.stem.removeprefix(prefix): path
        for path in raw_path.joinpath("klines").glob(f"{prefix}*.zip")
    }
    mark_files = {
        path.stem.removeprefix(prefix): path
        for path in raw_path.joinpath("mark_price").glob(f"{prefix}*.zip")
    }
    for period in sorted(set(trade_files) & set(mark_files)):
        if not re.fullmatch(r"\d{4}-\d{2}", period):
            continue
        try:
            trade = load_ohlc_archive(trade_files[period]).add_prefix("trade_")
            mark = load_ohlc_archive(mark_files[period])[["open", "high", "low", "close"]].add_prefix("mark_")
        except (OSError, ValueError, EOFError, zipfile.BadZipFile) as exc:
            print(f"Skipping unreadable local archive {period}: {exc}", flush=True)
            continue
        batch = trade.join(mark, how="inner")
        batch = batch.loc[(batch.index >= pd.Timestamp(start, tz="UTC")) & (batch.index < pd.Timestamp(end, tz="UTC"))]
        if not batch.empty:
            yield batch


def benchmark_metrics(price: pd.Series) -> dict[str, float]:
    returns = price.pct_change().dropna()
    years = (price.index[-1] - price.index[0]).total_seconds() / (365.25 * 86400)
    drawdown = price / price.cummax() - 1.0
    volatility = returns.std(ddof=1) * (365 * 6) ** 0.5
    return {
        "total_return": float(price.iloc[-1] / price.iloc[0] - 1.0),
        "cagr": float((price.iloc[-1] / price.iloc[0]) ** (1 / years) - 1.0),
        "annualized_volatility": float(volatility),
        "sharpe": float(returns.mean() / returns.std(ddof=1) * (365 * 6) ** 0.5),
        "max_drawdown": float(drawdown.min()),
        "final_equity": float(price.iloc[-1]),
    }


def side_summary(trades: pd.DataFrame) -> dict[str, dict[str, float]]:
    if trades.empty or "side" not in trades:
        return {}
    output: dict[str, dict[str, float]] = {}
    for side, group in trades.groupby("side"):
        output[str(side)] = {
            "trade_count": float(len(group)),
            "pnl_sum": float(group["pnl"].sum()) if "pnl" in group else 0.0,
            "win_rate": float((group["pnl"] > 0).mean()) if "pnl" in group else 0.0,
            "avg_pnl": float(group["pnl"].mean()) if "pnl" in group else 0.0,
        }
    return output


def period_side_summary(trades: pd.DataFrame) -> dict[str, dict[str, dict[str, float]]]:
    periods = {
        "train_2020_2022": ("2020-01-01", "2023-01-01"),
        "validation_2023_2024": ("2023-01-01", "2025-01-01"),
        "holdout_2025_2026_07": ("2025-01-01", "2026-08-01"),
    }
    if trades.empty or "side" not in trades:
        return {}
    exit_time = pd.to_datetime(trades["exit_time"], utc=True)
    output: dict[str, dict[str, dict[str, float]]] = {}
    for label, (start, end) in periods.items():
        start_ts = pd.Timestamp(start, tz="UTC")
        end_ts = pd.Timestamp(end, tz="UTC")
        subset = trades.loc[(exit_time >= start_ts) & (exit_time < end_ts)]
        output[label] = side_summary(subset)
    return output


def run_strategy(
    code: str,
    market: pd.DataFrame,
    batches,
    funding: pd.DataFrame,
    config: MicroBacktestConfig,
    v7_params_path: Path,
    v41_params_path: Path,
    v42_params_path: Path,
    v7_overrides: dict[str, object],
):
    if code == "V4":
        params = StrategyParams(**json.loads((ROOT / "configs/aggressive_adaptive_v3_params.json").read_text(encoding="utf-8")))
        signals = generate_signals(market, params)
    elif code == "V4.1":
        params = StrategyParams(**json.loads(v41_params_path.read_text(encoding="utf-8-sig")))
        signals = generate_signals(market, params)
    elif code == "V4.2":
        params = StrategyParams(**json.loads(v42_params_path.read_text(encoding="utf-8-sig")))
        signals = generate_signals(market, params)
    elif code == "V7":
        values = json.loads(v7_params_path.read_text(encoding="utf-8-sig"))
        values.update(v7_overrides)
        params = V7Params(**values)
        signals = generate_v7_signals(market, params)
    else:
        raise ValueError(code)
    result = run_micro_backtest(signals, batches, funding, config)
    return params, signals, result


def main() -> None:
    args = parse_args()
    v7_overrides = json.loads(args.v7_overrides)
    for key, value in {
        "target_vol": args.v7_target_vol,
        "short_scale": args.v7_short_scale,
        "trend_trailing_stop_atr": args.v7_stop_atr,
        "trend_exit_confirm_bars": args.v7_exit_confirm,
        "breakout_buffer_atr": args.v7_breakout_buffer,
    }.items():
        if value is not None:
            v7_overrides[key] = value
    args.output.mkdir(parents=True, exist_ok=True)
    market = load_local_market(args.raw_dir, args.start, args.end, args.source_zip)
    config = MicroBacktestConfig(
        initial_cash=10_000.0,
        taker_fee_bps=4.0,
        base_slippage_bps=1.0,
        impact_bps=8.0,
        max_minute_participation=0.02,
        liquidation_fee_bps=50.0,
        strategy_drawdown_enabled=args.strategy_drawdown,
        strategy_drawdown_level_1=args.dd_level_1,
        strategy_drawdown_scale_1=args.dd_scale_1,
        strategy_drawdown_level_2=args.dd_level_2,
        strategy_drawdown_scale_2=args.dd_scale_2,
        strategy_drawdown_level_3=args.dd_level_3,
        strategy_drawdown_scale_3=args.dd_scale_3,
    )

    summary: dict[str, object] = {
        "data": {
            "start": args.start,
            "end": args.end,
            "raw_dir": str(args.raw_dir),
            "method": "local 1m execution and mark-price margin simulation",
        },
        "execution": asdict(config),
        "strategies": {},
    }

    curves: list[pd.Series] = []
    for code in ["V4", "V4.1", "V4.2", "V7"]:
        print(f"Running {code} local micro backtest...", flush=True)
        batches = iter_local_batches(args.raw_dir, args.start, args.end, args.source_zip)
        strategy_config = replace(
            config,
            strategy_drawdown_enabled=args.strategy_drawdown if code == "V7" else False,
            strategy_drawdown_level_1=args.dd_level_1,
            strategy_drawdown_scale_1=args.dd_scale_1,
            strategy_drawdown_level_2=args.dd_level_2,
            strategy_drawdown_scale_2=args.dd_scale_2,
            strategy_drawdown_level_3=args.dd_level_3,
            strategy_drawdown_scale_3=args.dd_scale_3,
        )
        params, signals, result = run_strategy(
            code,
            market,
            batches,
            market[["funding_rate"]],
            strategy_config,
            args.v7_params,
            args.v41_params,
            args.v42_params,
            v7_overrides,
        )
        strategy_dir = args.output / code.lower()
        write_micro_report(result, params, config, strategy_dir)
        curves.append(result.equity.rename(code))
        payload = {
            "metrics": result.metrics,
            "periods": micro_period_metrics(result),
            "side_summary": side_summary(result.trades),
            "period_side_summary": period_side_summary(result.trades),
        }
        if code == "V7":
            payload["v7_signal_distribution"] = {
                "market_states": signals["v7_market_state"].value_counts(dropna=False).to_dict(),
                "regimes": signals["regime"].value_counts(dropna=False).to_dict(),
                "speed_modes": signals["v7_speed_mode"].value_counts(dropna=False).to_dict(),
            }
        summary["strategies"][code] = payload

    equity = pd.concat(curves, axis=1).sort_index().ffill()
    close_at_boundary = market["close"].copy()
    close_at_boundary.index = close_at_boundary.index + pd.Timedelta(hours=4)
    btc = close_at_boundary.reindex(equity.index).ffill().dropna()
    equity = equity.reindex(btc.index)
    equity["BTC"] = btc / btc.iloc[0] * 10_000.0
    equity.to_csv(args.output / "equity_v4_v7.csv")
    (equity / equity.cummax() - 1.0).to_csv(args.output / "drawdown_v4_v7.csv")
    render_curves(equity, args.output / "equity_drawdown_v4_v7.png")
    summary["strategies"]["BTC"] = {
        "metrics": benchmark_metrics(equity["BTC"]),
    }
    (args.output / "metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    table = pd.DataFrame(
        [
            {"code": code, **summary["strategies"][code]["metrics"]}
            for code in ["V4", "V4.1", "V4.2", "V7"]
        ]
    )
    table.to_csv(args.output / "summary_metrics.csv", index=False)
    print(table.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
