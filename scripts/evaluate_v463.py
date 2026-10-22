"""Evaluate the V4.6.3 bounded risk-budget refinement.

The candidate screen is fixed in this file before the recent diagnostic
window is read.  Historical folds choose the candidate; 2026-09 onward is
reported only as a diagnostic.  The selected signal is then replayed through
the five-minute all-Taker execution model and a small execution stress suite.
"""
from __future__ import annotations

from dataclasses import asdict, replace
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
from btc_regime.v461 import V461Params, generate_v461_signals  # noqa: E402
from btc_regime.v463 import V463Params, generate_v463_signals  # noqa: E402
import run_bitget_three_latest as latest  # noqa: E402


DEFAULT_DATA = ROOT / "data" / "bitget_20261011"
DEFAULT_OUTPUT = ROOT / "reports" / "v4_6_3"
START = pd.Timestamp("2020-01-01", tz="UTC")
TRAIN_END = pd.Timestamp("2024-01-01", tz="UTC")
VALID_END = pd.Timestamp("2026-01-01", tz="UTC")
DIAGNOSTIC_START = pd.Timestamp("2026-09-01", tz="UTC")


def _last_complete_month(end: pd.Timestamp) -> pd.Timestamp:
    month = (end.tz_localize(None).to_period("M") - 1).to_timestamp(how="end")
    return month.tz_localize("UTC")


def monthly_returns(equity: pd.Series, end: pd.Timestamp) -> pd.Series:
    daily = equity.sort_index().resample("1D", closed="right", label="right").last().dropna()
    month_end = daily.resample("ME").last().dropna()
    returns = month_end.pct_change().dropna()
    return returns.loc[returns.index <= _last_complete_month(end)]


def _daily_sharpe(equity: pd.Series) -> float:
    daily = equity.resample("1D", closed="right", label="right").last().dropna()
    returns = daily.pct_change().dropna()
    std = returns.std(ddof=1)
    return float(returns.mean() / std * np.sqrt(365.25)) if std > 0 else 0.0


def _monthly_stats(values: pd.Series) -> dict[str, float | int]:
    if values.empty:
        return {"months": 0, "mean": 0.0, "std": 0.0, "monthly_sharpe": 0.0,
                "positive_fraction": 0.0, "worst": 0.0, "best": 0.0}
    std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
    return {
        "months": int(len(values)),
        "mean": float(values.mean()),
        "std": std,
        "monthly_sharpe": float(values.mean() / std * np.sqrt(12)) if std > 0 else 0.0,
        "positive_fraction": float((values > 0).mean()),
        "worst": float(values.min()),
        "best": float(values.max()),
    }


def window_metrics(equity: pd.Series, monthly: pd.Series,
                   start: pd.Timestamp, end: pd.Timestamp) -> dict[str, float | int]:
    frame = equity.loc[(equity.index >= start) & (equity.index < end)].dropna()
    if len(frame) < 2:
        return {"total_return": 0.0, "cagr": 0.0, "max_drawdown": 0.0,
                "daily_sharpe": 0.0, **_monthly_stats(monthly.iloc[0:0])}
    years = max((frame.index[-1] - frame.index[0]).total_seconds() / (365.25 * 86400), 1 / 365.25)
    month_slice = monthly.loc[(monthly.index >= start) & (monthly.index < end)]
    return {
        "total_return": float(frame.iloc[-1] / frame.iloc[0] - 1),
        "cagr": float((frame.iloc[-1] / frame.iloc[0]) ** (1 / years) - 1),
        "max_drawdown": float((frame / frame.cummax() - 1).min()),
        "daily_sharpe": _daily_sharpe(frame),
        **_monthly_stats(month_slice),
    }


def _baseline_params() -> V461Params:
    payload = json.loads((ROOT / "configs" / "v4_6_1_params.json").read_text())
    base = V453Params(**payload["base_signal_params"])
    return V461Params(base=base, **payload["risk_overlay"])


def _candidate_params() -> dict[str, V461Params]:
    """Predeclared candidate neighborhood; no recent-window tuning occurs here."""
    baseline = _baseline_params()
    chosen = V463Params(base=baseline.base)
    return {
        "control_v461": baseline,
        "overlay_v463": chosen,
        "profit_lock_050": replace(chosen, profit_lock_scale=0.50),
        "profit_lock_025": replace(chosen, profit_lock_scale=0.25),
        "cooldown6_overlay": replace(chosen, base=replace(chosen.base, cooldown_hours=6)),
        "break12_overlay": replace(chosen, base=replace(chosen.base, entry="break12")),
        "break12_cd6_overlay": replace(chosen, base=replace(chosen.base, entry="break12", cooldown_hours=6)),
        "risk_elevated_overlay": replace(chosen, base=replace(chosen.base, risk="elevated")),
    }


def _signal(name: str, params: V461Params, hourly: pd.DataFrame) -> pd.DataFrame:
    if name == "control_v461":
        return generate_v461_signals(hourly, params)
    return generate_v463_signals(hourly, params)  # V4.6.3 candidate family


def _execution_config(**changes) -> MicroBacktestConfig:
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
    return replace(base, **changes)


def _replay(signal: pd.DataFrame, raw: pd.DataFrame, funding: pd.DataFrame,
            config: MicroBacktestConfig):
    return run_micro_backtest(signal, latest.batches(raw), funding, config)


def _score(windows: dict[str, dict]) -> float:
    folds = [windows[k] for k in ("train_2020_2023", "validation_2024_2025", "pre_holdout_2026_01_08")]
    sharpes = np.array([row["daily_sharpe"] for row in folds], dtype=float)
    cagr = np.array([row["cagr"] for row in folds], dtype=float)
    monthly_std = np.array([row["std"] for row in folds], dtype=float)
    return float(np.median(sharpes) - 0.35 * np.std(sharpes)
                 + 0.25 * np.median(cagr) - 0.75 * np.median(monthly_std))


def _screen(candidates: dict[str, V461Params], hourly: pd.DataFrame, raw: pd.DataFrame,
            funding: pd.DataFrame, end: pd.Timestamp, out: Path) -> tuple[pd.DataFrame, str]:
    rows = []
    config = _execution_config()
    windows = {
        "train_2020_2023": (START, TRAIN_END),
        "validation_2024_2025": (TRAIN_END, VALID_END),
        "pre_holdout_2026_01_08": (VALID_END, DIAGNOSTIC_START),
        "diagnostic_2026_09_10": (DIAGNOSTIC_START, end),
    }
    for name, params in candidates.items():
        signal = _signal(name, params, hourly)
        # Hourly accounting is used for the predeclared screen.  The selected
        # candidate is replayed again below with the exact five-minute model.
        hourly_result = run_backtest(
            signal,
            BacktestConfig(initial_cash=10_000.0, fee_bps=2.4, slippage_bps=1.0,
                           periods_per_year=8760),
        )
        monthly = monthly_returns(hourly_result.equity, end)
        row = {"candidate": name, "diagnostic_used_for_selection": False}
        fold_metrics = {}
        for label, (start, stop) in windows.items():
            metrics = window_metrics(hourly_result.equity, monthly, start, stop)
            fold_metrics[label] = metrics
            for key in ("cagr", "daily_sharpe", "std", "mean", "max_drawdown", "positive_fraction"):
                row[f"{label}_{key}"] = metrics[key]
        historical = [fold_metrics[k] for k in ("train_2020_2023", "validation_2024_2025", "pre_holdout_2026_01_08")]
        row["all_historical_folds_positive"] = all(m["cagr"] > 0 for m in historical)
        row["score"] = _score(fold_metrics)
        rows.append(row)

    frame = pd.DataFrame(rows)
    baseline = frame.loc[frame.candidate.eq("control_v461")].iloc[0]
    historical_labels = ("train_2020_2023", "validation_2024_2025", "pre_holdout_2026_01_08")
    for row in rows:
        row["historical_drawdown_within_control_plus_1pct"] = all(
            row[f"{label}_max_drawdown"] >= baseline[f"{label}_max_drawdown"] - 0.01
            for label in historical_labels
        )
    frame["historical_drawdown_within_control_plus_1pct"] = [
        row["historical_drawdown_within_control_plus_1pct"] for row in rows
    ]
    eligible = frame.loc[
        frame.all_historical_folds_positive
        & frame.historical_drawdown_within_control_plus_1pct
    ].copy()
    if eligible.empty:
        selected = "control_v461"
    else:
        # Keep the simpler overlay candidate when it is close to the best
        # score.  This makes selection insensitive to tiny historical noise.
        top = float(eligible.score.max())
        near = eligible.loc[eligible.score >= top - 0.15]
        selected = sorted(near.candidate.tolist(), key=lambda x: (x != "overlay_v463", x))[0]
    frame["selected"] = frame.candidate.eq(selected)
    frame.to_csv(out / "candidate_screen.csv", index=False)
    frame.attrs["baseline"] = baseline.to_dict()
    return frame, selected


def _result_summary(name: str, result, end: pd.Timestamp) -> dict:
    monthly = monthly_returns(result.equity, end)
    windows = {
        "full": (START, end),
        "train_2020_2023": (START, TRAIN_END),
        "validation_2024_2025": (TRAIN_END, VALID_END),
        "pre_holdout_2026_01_08": (VALID_END, DIAGNOSTIC_START),
        "diagnostic_2026_09_10": (DIAGNOSTIC_START, end),
    }
    summary = {
        "strategy": name,
        "engine_metrics": result.metrics,
        "windows": {label: window_metrics(result.equity, monthly, start, stop)
                     for label, (start, stop) in windows.items()},
        "trade_count": int(len(result.trades)),
        "fill_count": int(len(result.fills)),
        "liquidations": int(len(result.liquidations)),
    }
    return summary


def run(data_dir: Path, output_dir: Path) -> dict:
    cached = pd.read_pickle(data_dir / "candles_5m.pkl")
    cached.index = pd.to_datetime(cached.index, utc=True)
    end = cached.index.max() + pd.Timedelta(minutes=5)
    latest.START, latest.END = START, end
    raw, hourly, _, funding = latest.load_data(data_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = _candidate_params()
    screen, selected_name = _screen(candidates, hourly, raw, funding, end, output_dir)
    baseline_signal = _signal("control_v461", candidates["control_v461"], hourly)
    selected_signal = _signal(selected_name, candidates[selected_name], hourly)
    config = _execution_config()
    baseline_result = _replay(baseline_signal, raw, funding, config)
    selected_result = _replay(selected_signal, raw, funding, config)

    results = {
        "V4.6.1_control_all_taker": _result_summary("V4.6.1_control_all_taker", baseline_result, end),
        "V4.6.3_selected_all_taker": _result_summary("V4.6.3_selected_all_taker", selected_result, end),
    }
    baseline_result.equity.to_csv(output_dir / "V4_6_1_control_equity.csv")
    selected_result.equity.to_csv(output_dir / "V4_6_3_selected_equity.csv")
    selected_result.trades.to_csv(output_dir / "V4_6_3_selected_trades.csv", index=False)
    selected_result.fills.to_csv(output_dir / "V4_6_3_selected_fills.csv", index=False)
    selected_result.funding.to_csv(output_dir / "V4_6_3_selected_funding.csv", index=False)
    selected_result.liquidations.to_csv(output_dir / "V4_6_3_selected_liquidations.csv", index=False)
    monthly = pd.concat({
        "V4.6.1": monthly_returns(baseline_result.equity, end),
        "V4.6.3": monthly_returns(selected_result.equity, end),
    }, axis=1)
    monthly.to_csv(output_dir / "monthly_returns.csv")

    stress_cases = {
        "base_all_taker": config,
        "fees_plus_50pct": replace(config, taker_fee_bps=3.6),
        "double_slippage": replace(config, base_slippage_bps=2.0, impact_bps=16.0),
        "funding_2x": config,
        "latency_1h": config,
    }
    stress_rows = []
    for scenario, stress_config in stress_cases.items():
        signal = selected_signal.copy()
        scenario_funding = funding.copy()
        if scenario == "funding_2x":
            scenario_funding["funding_rate"] = scenario_funding["funding_rate"] * 2.0
        if scenario == "latency_1h":
            signal.index = signal.index + pd.Timedelta(hours=1)
        stress = _replay(signal, raw, scenario_funding, stress_config)
        row = {"scenario": scenario, **_result_summary(scenario, stress, end)["windows"]["full"]}
        row["liquidations"] = int(len(stress.liquidations))
        stress_rows.append(row)
    pd.DataFrame(stress_rows).to_csv(output_dir / "execution_stress.csv", index=False)

    payload = {
        "strategy": "V4.6.3",
        "selected_candidate": selected_name,
        "requested_start": START.isoformat(),
        "observed_end_exclusive": end.isoformat(),
        "signal_params": candidates[selected_name].to_dict(),
        "execution": asdict(config),
        "candidate_screen": screen.to_dict(orient="records"),
        "results": results,
        "stress": stress_rows,
        "selection_policy": json.loads((ROOT / "configs" / "v4_6_3_params.json").read_text())["selection_policy"],
    }
    (output_dir / "report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=float) + "\n")

    selected_row = results["V4.6.3_selected_all_taker"]
    control_row = results["V4.6.1_control_all_taker"]
    lines = [
        "# V4.6.3 风险预算优化报告",
        "",
        "V4.6.3 保留 V4.6.1 的 V4.5.3/b022 入场与退出逻辑，只调整月内风险预算。候选集合在读取 2026-09 诊断窗前固定；诊断窗不参与选择。",
        "",
        f"选择结果：`{selected_name}`。主结果使用全 Taker、5 分钟成交检查、1 小时信号；月度统计只纳入完整自然月。",
        "",
        "| 策略 | CAGR | 日频 Sharpe | 月均收益 | 月收益标准差 | 月度 Sharpe | 最大回撤 | 正收益月占比 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, row in [("V4.6.1 控制", control_row["windows"]["full"]), ("V4.6.3 选择", selected_row["windows"]["full"])]:
        lines.append(f"| {label} | {row['cagr']:.2%} | {row['daily_sharpe']:.3f} | {row['mean']:.2%} | {row['std']:.2%} | {row['monthly_sharpe']:.2f} | {row['max_drawdown']:.2%} | {row['positive_fraction']:.1%} |")
    lines += [
        "",
        "历史选择折叠为 2020–2023、2024–2025 和 2026-01–2026-08；要求每折 CAGR 为正，且最大回撤相对 V4.6.1 控制最多恶化 1 个百分点，再用折叠 Sharpe、折叠离散度和月收益标准差的稳健评分排序；分数接近时优先简单覆盖层。",
        "V4.6.3 风险预算：正常暴露 1.00；月内 BTC 收益达到 -10%/-15% 时缩放至 0.50；达到 +6% 后缩放至 0.35。所有判断使用完成小时收盘价，并作用于下一小时。",
        "",
        "数据限制：历史数据在研究期间已可见；2026-09 以后只是诊断窗口。Bitget 公共资金费缓存从 2026-06-27 开始；执行为 5 分钟 OHLC 代理，没有队列位置或真实盘口。",
    ]
    (output_dir / "README.md").write_text("\n".join(lines) + "\n")
    return payload


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = run(args.data, args.output)
    print("selected", payload["selected_candidate"])
    for name, row in payload["results"].items():
        print(name, json.dumps(row["windows"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
