"""Evaluate the V4.6.1 higher-return monthly-stability candidate.

The signal family stays frozen at V4.5.3/b022.  A small, predeclared overlay
screen is reported using fast hourly accounting; the selected overlay is then
validated with the full five-minute all-Taker execution replay.  The recent
diagnostic window is reported but does not choose the overlay.
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

from btc_regime.backtest import BacktestConfig, run_backtest  # noqa: E402
from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest  # noqa: E402
from btc_regime.v453 import V453Params, generate_v453_signals  # noqa: E402
from btc_regime.v453_stable import V453StableParams, generate_v453_stable_signals  # noqa: E402
from btc_regime.v461 import V461Params, generate_v461_signals  # noqa: E402
import run_bitget_three_latest as latest  # noqa: E402


DEFAULT_DATA = ROOT / "data" / "bitget_20261011"
DEFAULT_OUTPUT = ROOT / "reports" / "v4_6_1"
START = pd.Timestamp("2020-01-01", tz="UTC")
DIAGNOSTIC_START = pd.Timestamp("2026-09-01", tz="UTC")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _params() -> tuple[V453Params, V453StableParams, V461Params, dict]:
    payload = _load_json(ROOT / "configs" / "v4_6_1_params.json")
    base = V453Params(**payload["base_signal_params"])
    stable_payload = _load_json(ROOT / "configs" / "v4_5_3_stable_params.json")
    stable = V453StableParams(
        base=V453Params(**stable_payload["base_signal_params"]),
        **stable_payload["risk_overlay"],
    )
    v461 = V461Params(base=base, **payload["risk_overlay"])
    return base, stable, v461, payload


OVERLAYS: dict[str, tuple[float, float, float, float, float, float, float]] = {
    "A": (0.80, -0.05, -0.10, 0.06, 0.75, 0.50, 0.50),
    "B": (0.80, -0.05, -0.10, 0.08, 0.75, 0.50, 0.50),
    "C": (0.80, -0.08, -0.15, 0.08, 0.75, 0.50, 0.50),
    "D": (0.80, -0.05, -0.10, 0.06, 0.50, 0.25, 0.50),
    "E": (0.70, -0.05, -0.10, 0.06, 0.75, 0.50, 0.50),
    "F": (0.90, -0.05, -0.10, 0.06, 0.75, 0.50, 0.50),
    "G": (0.80, -0.05, -0.10, 0.06, 0.75, 0.50, 0.25),
    "H": (0.80, -0.08, -0.12, 0.10, 0.50, 0.25, 0.50),
}


def _last_complete_month(end: pd.Timestamp) -> pd.Timestamp:
    month = (end.tz_localize(None).to_period("M") - 1).to_timestamp(how="end")
    return month.tz_localize("UTC")


def _monthly_returns(equity: pd.Series, end: pd.Timestamp) -> pd.Series:
    daily = equity.sort_index().resample("1D", closed="right", label="right").last().dropna()
    month_end = daily.resample("ME").last().dropna()
    returns = month_end.pct_change().dropna()
    return returns.loc[returns.index <= _last_complete_month(end)]


def _negative_streak(values: pd.Series) -> int:
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
        "max_negative_streak": _negative_streak(values),
    }


def _window_metrics(equity: pd.Series, monthly: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> dict:
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


def _overlay_signal(base: pd.DataFrame, close: pd.Series, values: tuple) -> pd.DataFrame:
    scale, soft, hard, profit, soft_scale, hard_scale, profit_scale = values
    month_key = close.index.strftime("%Y-%m")
    month_return = close / close.groupby(month_key, sort=False).transform("first") - 1.0
    multiplier = pd.Series(1.0, index=base.index)
    multiplier.loc[month_return <= soft] = soft_scale
    multiplier.loc[month_return <= hard] = hard_scale
    multiplier.loc[month_return >= profit] = profit_scale
    result = base.copy()
    result["signal"] = base["signal"].astype(float) * scale * multiplier
    result["leverage"] = result["signal"].abs()
    return result


def _candidate_screen(base_signal: pd.DataFrame, hourly: pd.DataFrame, end: pd.Timestamp, output_dir: Path) -> pd.DataFrame:
    rows = []
    close = hourly["close"].astype(float)
    windows = {
        "train": (START, pd.Timestamp("2024-01-01", tz="UTC")),
        "validation": (pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC")),
        "pre_holdout": (pd.Timestamp("2026-01-01", tz="UTC"), DIAGNOSTIC_START),
        "diagnostic": (DIAGNOSTIC_START, end),
    }
    for candidate, values in OVERLAYS.items():
        signal = _overlay_signal(base_signal, close, values)
        result = run_backtest(
            signal,
            BacktestConfig(initial_cash=10_000.0, fee_bps=2.4, slippage_bps=1.0, periods_per_year=8760),
        )
        monthly = _monthly_returns(result.equity, end)
        row = {"candidate": candidate, "selected": candidate == "F", "diagnostic_used_for_selection": False}
        for label, (start, window_end) in windows.items():
            metrics = _window_metrics(result.equity, monthly, start, window_end)
            for key in ("cagr", "mean", "std", "max_drawdown", "positive_fraction"):
                row[f"{label}_{key}"] = metrics[key]
        historical = [row[f"{fold}_cagr"] for fold in ("train", "validation", "pre_holdout")]
        row["historical_score"] = float(np.median(historical) - 0.45 * np.std(historical))
        rows.append(row)
    frame = pd.DataFrame(rows).sort_values("historical_score", ascending=False)
    frame.to_csv(output_dir / "candidate_screen.csv", index=False)
    return frame


def _result_row(name: str, result, end: pd.Timestamp) -> tuple[dict, pd.Series]:
    monthly = _monthly_returns(result.equity, end)
    windows = {
        "full": START,
        "post2024": pd.Timestamp("2024-01-01", tz="UTC"),
        "post2025": pd.Timestamp("2025-01-01", tz="UTC"),
        "post2026": pd.Timestamp("2026-01-01", tz="UTC"),
        "diagnostic_2026_09": DIAGNOSTIC_START,
    }
    if result.trades.empty:
        median_holding_hours = 0.0
    else:
        entry = pd.to_datetime(result.trades["entry_time"], utc=True)
        exit_ = pd.to_datetime(result.trades["exit_time"], utc=True)
        median_holding_hours = float(((exit_ - entry).dt.total_seconds() / 3600.0).median())
    years = max((result.equity.index[-1] - result.equity.index[0]).total_seconds() / (365.25 * 86400), 1 / 365.25)
    row = {
        "strategy": name,
        "execution": result.metrics,
        "trades": int(len(result.trades)),
        "long_trades": int((result.trades.side == "long").sum()) if not result.trades.empty else 0,
        "short_trades": int((result.trades.side == "short").sum()) if not result.trades.empty else 0,
        "median_holding_hours": median_holding_hours,
        "cycles_per_year": float(len(result.trades) / years),
        "windows": {
            key: _window_metrics(result.equity, monthly, start, end)
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
    base_params, stable_params, v461_params, config_payload = _params()
    base_signal = generate_v453_signals(hourly, base_params)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_screen = _candidate_screen(base_signal, hourly, end, output_dir)
    selected = config_payload["selection_policy"]["selected_overlay"]
    if selected not in OVERLAYS:
        raise ValueError(f"selected overlay {selected!r} is not in the frozen candidate set")

    stable_signal = generate_v453_stable_signals(hourly, stable_params)
    v461_signal = generate_v461_signals(hourly, v461_params)
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
        "V4.5.3_all_taker": run_micro_backtest(base_signal, latest.batches(raw), funding, config),
        "V4.5.3_stable_all_taker": run_micro_backtest(stable_signal, latest.batches(raw), funding, config),
        "V4.6.1_all_taker": run_micro_backtest(v461_signal, latest.batches(raw), funding, config),
    }
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
        "strategy": "V4.6.1",
        "requested_start": START.isoformat(),
        "observed_end_exclusive": end.isoformat(),
        "observed_last_candle": raw.index.max().isoformat(),
        "signal_params": v461_params.to_dict(),
        "execution": asdict(config),
        "selected_overlay": selected,
        "candidate_screen": candidate_screen.to_dict(orient="records"),
        "data_limits": [
            "Bitget public funding history in this cache starts on 2026-06-27; older funding is not fabricated.",
            "The primary comparison uses all-Taker execution; no Maker queue advantage is assumed.",
            "Only complete calendar months are included in monthly statistics; the final partial month is excluded.",
            "The 2026-09 onward window is a diagnostic holdout and is not used to select the overlay.",
        ],
        "results": rows,
    }
    (output_dir / "report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=float) + "\n")

    lines = [
        "# V4.6.1 月收益稳定性与收益目标研究",
        "",
        "主结果使用全 Taker 执行、5 分钟成交检查、1 小时信号；月度统计只包含完整自然月。",
        "V4.6.1 冻结 V4.5.3/b022 信号参数，只提高暴露预算并保留月内风险缩放；筛选候选为 8 个预先声明的覆盖层，2026-09 以后仅作诊断。",
        "因子族和覆盖层形状没有使用诊断窗口调参；F 是达到两个目标所需的最小粗粒度暴露步长：全样本分钟回放 CAGR 超过 50% 且平均月收益超过 4%。候选 H 的历史评分更高，但月收益离散度更大。",
        "",
        "| 策略 | 区间 | CAGR | 最大回撤 | 月均收益 | 月收益标准差 | 月度 Sharpe | 正收益月占比 | 最差月 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "full": "全样本",
        "post2024": "2024 后",
        "post2025": "2025 后",
        "post2026": "2026 后",
        "diagnostic_2026_09": "2026-09 诊断（含不完整末月）",
    }
    for row in rows:
        for key, metrics in row["windows"].items():
            lines.append(
                f"| {row['strategy']} | {labels[key]} | {metrics['cagr']:.2%} | {metrics['max_drawdown']:.2%} | "
                f"{metrics['mean']:.2%} | {metrics['std']:.2%} | {metrics['monthly_sharpe']:.2f} | "
                f"{metrics['positive_fraction']:.1%} | {metrics['worst']:.2%} |"
            )
    v461_row = next(row for row in rows if row["strategy"] == "V4.6.1_all_taker")
    lines += [
        "",
        f"V4.6.1 全样本交易频率：{v461_row['trades']} 次、{v461_row['cycles_per_year']:.1f} 次/年、中位持仓 {v461_row['median_holding_hours']:.1f} 小时；其中多头 {v461_row['long_trades']} 次、空头 {v461_row['short_trades']} 次。",
        "因子仍为 4 小时趋势 EMA/ADX/DI、小时突破/重夺、结构性空头、成交活跃度、已结算资金费过滤以及 ATR/波动率仓位。没有把最近诊断窗口表现不稳定的新入口因子并入主版本。",
        "V4.6.1 风险层：正常暴露为 V4.5.3 的 90%；月内 BTC 收益达到 -5%/-10% 时缩放至 75%/50%；月内上涨达到 +6% 后缩放至 50%。",
        "月内控制使用完成小时收盘价计算，并在下一小时执行；它是风险预算，不是新增 alpha。",
        "费用、滑点和资金费压力测试见 execution_stress.csv；这些测试不改变主结果的全 Taker 参数。",
        "",
        "数据限制：Bitget 公共资金费缓存只覆盖 2026-06-27 之后；Maker 没有用于主结果；历史数据此前已经参与研究，诊断窗口不构成盲样本外证明。",
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
