#!/usr/bin/env python3
"""Compare V4 and V7 using official Binance 1m ZIPs without persisting archives.

The local archive files can be wrapped by the host filesystem, so this script
streams official ZIP bytes into memory, parses the CSV payload, and feeds the
existing minute execution simulator directly.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from dataclasses import asdict
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd
import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter, StrMethodFormatter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.data import KLINE_COLUMNS  # noqa: E402
from btc_regime.micro_backtest import (  # noqa: E402
    MicroBacktestConfig,
    micro_period_metrics,
    run_micro_backtest,
    write_micro_report,
)
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402
from btc_regime.v7 import V7Params, generate_v7_signals  # noqa: E402


BASE_URL = "https://data.binance.vision/data/futures/um/monthly"
MARKET_PATH = ROOT / "reports/annual_2020_2026_08_25/market_4h_full.csv"
FUNDING_PATH = ROOT / "reports/annual_2020_2026_08_25/funding_full.csv"
V4_PARAMS = ROOT / "configs/aggressive_adaptive_v3_params.json"
V7_PARAMS = ROOT / "configs/v7_params.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Official-source 1m micro comparison for V4 and V7."
    )
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-08-01")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports/v4_v7_micro_official_2020_2026_07",
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--stream-twice",
        action="store_true",
        help="Use less memory by downloading 1m batches once per strategy.",
    )
    return parser.parse_args()


def months(start: str, end: str) -> list[str]:
    start_period = pd.Period(start, freq="M")
    end_ts = pd.Timestamp(end, tz="UTC")
    # The simulator uses a half-open end; do not include the next month when end
    # is exactly at 00:00 on the first day.
    end_period = pd.Period((end_ts - pd.Timedelta(nanoseconds=1)).date(), freq="M")
    return [str(period) for period in pd.period_range(start_period, end_period, freq="M")]


def read_official_zip(url: str, timeout: int) -> pd.DataFrame:
    request = Request(url, headers={"User-Agent": "btc-regime-research/0.1"})
    with urlopen(request, timeout=timeout) as response:
        payload = response.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError(f"no CSV payload found in {url}")
        with archive.open(csv_names[0]) as handle:
            frame = pd.read_csv(handle)
        if not set(KLINE_COLUMNS).intersection(frame.columns):
            with archive.open(csv_names[0]) as handle:
                frame = pd.read_csv(handle, header=None, names=KLINE_COLUMNS)
    if list(frame.columns) != KLINE_COLUMNS:
        frame.columns = KLINE_COLUMNS[: len(frame.columns)]
    keep = ["open_time", "open", "high", "low", "close", "volume", "quote_volume"]
    frame = frame[keep].copy()
    frame["timestamp"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    for column in ["open", "high", "low", "close", "volume", "quote_volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return (
        frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
        .sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .set_index("timestamp")[["open", "high", "low", "close", "volume", "quote_volume"]]
    )


def official_intrabar_batches(
    *,
    symbol: str,
    start: str,
    end: str,
    timeout: int,
) -> list[pd.DataFrame]:
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    batches: list[pd.DataFrame] = []
    for month in months(start, end):
        name = f"{symbol}-1m-{month}.zip"
        trade_url = f"{BASE_URL}/klines/{symbol}/1m/{name}"
        mark_url = f"{BASE_URL}/markPriceKlines/{symbol}/1m/{name}"
        print(f"Downloading official 1m {month}...", flush=True)
        trade = read_official_zip(trade_url, timeout).add_prefix("trade_")
        mark = read_official_zip(mark_url, timeout)[["open", "high", "low", "close"]].add_prefix(
            "mark_"
        )
        batch = trade.join(mark, how="inner")
        batch = batch.loc[(batch.index >= start_ts) & (batch.index < end_ts)]
        if not batch.empty:
            batches.append(batch)
    return batches


def load_market_and_funding(start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    market = pd.read_csv(MARKET_PATH, index_col=0, parse_dates=True)
    market.index = pd.to_datetime(market.index, utc=True, format="mixed")
    market = market.loc[(market.index >= start_ts) & (market.index < end_ts)].sort_index()
    funding = pd.read_csv(FUNDING_PATH, index_col=0, parse_dates=True)
    funding.index = pd.to_datetime(funding.index, utc=True, format="mixed")
    funding = funding.loc[(funding.index >= start_ts) & (funding.index < end_ts)].sort_index()
    funding_4h = funding["funding_rate"].groupby(funding.index.floor("4h")).sum()
    market["funding_rate"] = funding_4h.reindex(market.index, fill_value=0.0)
    return market, funding


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


def render_curves(equity: pd.DataFrame, output: Path) -> None:
    drawdown = equity / equity.cummax() - 1.0
    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(14, 9),
        dpi=160,
        sharex=True,
        height_ratios=[2, 1],
    )
    colors = {"V4": "#0891b2", "V7": "#f59e0b"}
    for code in ["V4", "V7"]:
        ax1.plot(equity.index, equity[code], label=code, color=colors[code], lw=2.2)
        ax2.plot(drawdown.index, drawdown[code], label=code, color=colors[code], lw=1.8)
    ax1.set_title("BTCUSDT Official 1m Micro Backtest: V4 vs V7")
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


def run_strategy(
    code: str,
    market: pd.DataFrame,
    funding: pd.DataFrame,
    batches: list[pd.DataFrame],
    config: MicroBacktestConfig,
):
    if code == "V4":
        params = StrategyParams(**json.loads(V4_PARAMS.read_text(encoding="utf-8")))
        signals = generate_signals(market, params)
    elif code == "V7":
        params = V7Params(**json.loads(V7_PARAMS.read_text(encoding="utf-8")))
        signals = generate_v7_signals(market, params)
    else:
        raise ValueError(code)
    result = run_micro_backtest(signals, batches, funding, config)
    return params, signals, result


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    market, funding = load_market_and_funding(args.start, args.end)
    config = MicroBacktestConfig(
        initial_cash=10_000.0,
        taker_fee_bps=4.0,
        base_slippage_bps=1.0,
        impact_bps=8.0,
        max_minute_participation=0.02,
        liquidation_fee_bps=50.0,
    )

    if args.stream_twice:
        batch_source = None
    else:
        batch_source = official_intrabar_batches(
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            timeout=args.timeout,
        )

    summary: dict[str, object] = {
        "data": {
            "symbol": args.symbol,
            "start": args.start,
            "end": args.end,
            "market_source": str(MARKET_PATH.relative_to(ROOT)),
            "funding_source": str(FUNDING_PATH.relative_to(ROOT)),
            "intrabar_source": f"{BASE_URL}/klines and markPriceKlines",
            "intrabar_archives_persisted": False,
        },
        "execution": asdict(config),
        "strategies": {},
    }

    curves: list[pd.Series] = []
    for code in ["V4", "V7"]:
        print(f"Running {code} official-source micro backtest...", flush=True)
        batches = batch_source
        if batches is None:
            batches = official_intrabar_batches(
                symbol=args.symbol,
                start=args.start,
                end=args.end,
                timeout=args.timeout,
            )
        params, signals, result = run_strategy(code, market, funding, batches, config)
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
                "short_signal_bars": int((signals["signal"] < 0).sum()),
                "long_signal_bars": int((signals["signal"] > 0).sum()),
            }
        summary["strategies"][code] = payload

    equity = pd.concat(curves, axis=1).sort_index().ffill()
    equity.to_csv(args.output / "equity_v4_v7.csv")
    (equity / equity.cummax() - 1.0).to_csv(args.output / "drawdown_v4_v7.csv")
    render_curves(equity, args.output / "equity_drawdown_v4_v7.png")
    (args.output / "metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    table = pd.DataFrame(
        [
            {"code": code, **summary["strategies"][code]["metrics"]}
            for code in ["V4", "V7"]
        ]
    )
    table.to_csv(args.output / "summary_metrics.csv", index=False)
    print(table[[
        "code",
        "final_equity",
        "cagr",
        "sharpe",
        "sortino",
        "max_drawdown",
        "trade_count",
        "fill_count",
        "fees_paid",
        "funding_paid",
        "liquidation_count",
    ]].to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
