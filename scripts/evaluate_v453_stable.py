"""Evaluate the lower-risk V4.5.3 factor sleeve on the latest Bitget cache.

The primary result uses all-Taker execution.  This avoids treating the
repository's OHLC Maker-touch model as a production fill guarantee while the
research question is monthly return stability.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest  # noqa: E402
from btc_regime.v453 import V453Params, generate_v453_signals  # noqa: E402
from btc_regime.v453_stable import V453StableParams, generate_v453_stable_signals  # noqa: E402
import run_bitget_three_latest as latest  # noqa: E402


DEFAULT_DATA = ROOT / "data" / "bitget_20261011"
DEFAULT_OUTPUT = ROOT / "reports" / "v4_5_3_stable"
START = pd.Timestamp("2020-01-01", tz="UTC")


def _load_stable_params() -> V453StableParams:
    payload = json.loads((ROOT / "configs" / "v4_5_3_stable_params.json").read_text())
    base = V453Params(**payload["base_signal_params"])
    return V453StableParams(base=base, **payload["risk_overlay"])


def _last_complete_month(end: pd.Timestamp) -> pd.Timestamp:
    month = (end.tz_localize(None).to_period("M") - 1).to_timestamp(how="end")
    return month.tz_localize("UTC")


def _monthly_returns(equity: pd.Series, end: pd.Timestamp) -> pd.Series:
    daily = equity.sort_index().resample("1D", closed="right", label="right").last().dropna()
    month_end = daily.resample("ME").last().dropna()
    returns = month_end.pct_change().dropna()
    return returns.loc[returns.index <= _last_complete_month(end)]


def _max_negative_streak(values: pd.Series) -> int:
    longest = current = 0
    for value in values:
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _monthly_stats(values: pd.Series) -> dict[str, float | int]:
    if values.empty:
        return {
            "months": 0,
            "mean": 0.0,
            "std": 0.0,
            "monthly_sharpe": 0.0,
            "positive_fraction": 0.0,
            "worst": 0.0,
            "best": 0.0,
            "negative_months": 0,
            "max_negative_streak": 0,
        }
    std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
    return {
        "months": int(len(values)),
        "mean": float(values.mean()),
        "std": std,
        "monthly_sharpe": float(values.mean() / std * np.sqrt(12)) if std > 0 else 0.0,
        "positive_fraction": float((values > 0).mean()),
        "worst": float(values.min()),
        "best": float(values.max()),
        "negative_months": int((values < 0).sum()),
        "max_negative_streak": _max_negative_streak(values),
    }


def _window_metrics(equity: pd.Series, result, monthly: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, float | int]:
    frame = equity.loc[(equity.index >= start) & (equity.index < end)].dropna()
    if frame.empty:
        return {"total_return": 0.0, "cagr": 0.0, "max_drawdown": 0.0, **_monthly_stats(monthly.iloc[0:0])}
    years = max((frame.index[-1] - frame.index[0]).total_seconds() / (365.25 * 86400), 1 / 365.25)
    month_slice = monthly.loc[(monthly.index >= start) & (monthly.index < end)]
    return {
        "total_return": float(frame.iloc[-1] / frame.iloc[0] - 1),
        "cagr": float((frame.iloc[-1] / frame.iloc[0]) ** (1 / years) - 1),
        "max_drawdown": float((frame / frame.cummax() - 1).min()),
        **_monthly_stats(month_slice),
    }


def _result_row(name: str, result, end: pd.Timestamp) -> tuple[dict, pd.Series]:
    monthly = _monthly_returns(result.equity, end)
    windows = {
        "full": START,
        "post2024": pd.Timestamp("2024-01-01", tz="UTC"),
        "post2025": pd.Timestamp("2025-01-01", tz="UTC"),
        "post2026": pd.Timestamp("2026-01-01", tz="UTC"),
    }
    if result.trades.empty:
        median_holding_hours = 0.0
    else:
        entry = pd.to_datetime(result.trades["entry_time"], utc=True)
        exit_ = pd.to_datetime(result.trades["exit_time"], utc=True)
        median_holding_hours = float(((exit_ - entry).dt.total_seconds() / 3600.0).median())
    equity_span_years = max(
        (result.equity.index[-1] - result.equity.index[0]).total_seconds() / (365.25 * 86400),
        1 / 365.25,
    )
    row = {
        "strategy": name,
        "execution": result.metrics,
        "trades": int(len(result.trades)),
        "long_trades": int((result.trades.side == "long").sum()) if not result.trades.empty else 0,
        "short_trades": int((result.trades.side == "short").sum()) if not result.trades.empty else 0,
        "median_holding_hours": median_holding_hours,
        "cycles_per_year": float(len(result.trades) / equity_span_years),
        "windows": {
            key: _window_metrics(result.equity, result, monthly, start, end)
            for key, start in windows.items()
        },
    }
    return row, monthly


def run(data_dir: Path, output_dir: Path) -> dict:
    cached = pd.read_pickle(data_dir / "candles_5m.pkl")
    cached.index = pd.to_datetime(cached.index, utc=True)
    end = cached.index.max() + pd.Timedelta(minutes=5)
    latest.START = START
    latest.END = end
    raw, hourly, _, funding = latest.load_data(data_dir)

    stable_params = _load_stable_params()
    base_params = stable_params.base
    base_signals = generate_v453_signals(hourly, base_params)
    stable_signals = generate_v453_stable_signals(hourly, stable_params)
    config = MicroBacktestConfig(
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

    results = {
        "V4.5.3_all_taker": run_micro_backtest(base_signals, latest.batches(raw), funding, config),
        "V4.5.3_stable_all_taker": run_micro_backtest(stable_signals, latest.batches(raw), funding, config),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    monthly_frames = []
    for name, result in results.items():
        row, monthly = _result_row(name, result, end)
        rows.append(row)
        monthly_frames.append(monthly.rename(name))
        safe = name.replace(".", "_")
        result.equity.to_csv(output_dir / f"{safe}_equity.csv", header=True)
        result.trades.to_csv(output_dir / f"{safe}_trades.csv", index=False)
        result.fills.to_csv(output_dir / f"{safe}_fills.csv", index=False)
    monthly_frame = pd.concat(monthly_frames, axis=1)
    monthly_frame.to_csv(output_dir / "monthly_returns.csv", header=True)

    payload = {
        "strategy": "V4.5.3-stable",
        "requested_start": START.isoformat(),
        "observed_end_exclusive": end.isoformat(),
        "observed_last_candle": raw.index.max().isoformat(),
        "signal_params": stable_params.to_dict(),
        "execution": asdict(config),
        "data_limits": [
            "Bitget public funding history in this cache starts on 2026-06-27; older funding is not fabricated.",
            "The primary comparison uses all-Taker execution; no Maker queue advantage is assumed.",
            "Only complete calendar months are included in monthly statistics; the final partial month is excluded.",
        ],
        "results": rows,
    }
    (output_dir / "report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=float) + "\n")
    lines = [
        "# V4.5.3-stable 月收益稳定性研究",
        "",
        "主结果使用全 Taker 执行、5 分钟成交检查、1 小时信号；月度统计只包含完整自然月。",
        "",
        "| 策略 | 区间 | 累计收益 | CAGR | 最大回撤 | 月均收益 | 月收益标准差 | 月度 Sharpe | 正收益月占比 | 最差月 | 最长连续负月 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {"full": "全样本", "post2024": "2024 后", "post2025": "2025 后", "post2026": "2026 后"}
    for row in rows:
        for key, metrics in row["windows"].items():
            lines.append(
                f"| {row['strategy']} | {labels[key]} | {metrics['total_return']:.2%} | {metrics['cagr']:.2%} | "
                f"{metrics['max_drawdown']:.2%} | {metrics['mean']:.2%} | {metrics['std']:.2%} | "
                f"{metrics['monthly_sharpe']:.2f} | {metrics['positive_fraction']:.1%} | "
                f"{metrics['worst']:.2%} | {metrics['max_negative_streak']} |"
            )
    lines += [
        "",
        "全样本交易频率：V4.5.3_all_taker 为 "
        f"{rows[0]['trades']} 次、{rows[0]['cycles_per_year']:.1f} 次/年、中位持仓 {rows[0]['median_holding_hours']:.1f} 小时；"
        "稳定候选为 "
        f"{rows[1]['trades']} 次、{rows[1]['cycles_per_year']:.1f} 次/年、中位持仓 {rows[1]['median_holding_hours']:.1f} 小时。",
        "稳定候选的信号因子：4 小时趋势 EMA/ADX/DI、小时突破/重夺、结构性空头、成交活跃度、已结算资金费过滤，以及 ATR/波动率仓位。",
        "风险层先将 V4.5.3 目标暴露缩放至 25%；月内 BTC 收盘价相对月初下跌 5%/10% 时缩放至 50%/20%，月内上涨 6% 后缩放至 25%。",
        "这是一项因果风险预算：当前完成小时计算，下一小时执行。月度稳定性来自风险控制和暴露收缩，不应解释成新增 alpha。",
        "",
        "数据限制：Bitget 公共资金费缓存只覆盖 2026-06-27 之后；Maker 没有用于主结果；历史数据此前已经参与研究，结果属于研究候选，不是盲样本外证明。",
    ]
    (output_dir / "README.md").write_text("\n".join(lines) + "\n")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = run(args.data, args.output)
    for row in payload["results"]:
        print(row["strategy"])
        print(json.dumps(row["windows"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
