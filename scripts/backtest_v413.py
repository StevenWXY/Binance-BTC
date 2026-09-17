"""Strict V4.1.3 report: merged V4.1.2 priority plus enhanced V8.

All cases use the same repaired local data, one net account, 4h signal timing,
1m execution, real funding events, and 40% trading-fee rebate. The report
keeps a standalone V4.1.2 and V8 comparison so the incremental effect of the
merge is auditable.
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

from btc_regime.backtest import BacktestConfig, run_backtest
from btc_regime.data import iter_intrabar_months, load_funding, load_market_data
from btc_regime.micro_backtest import (
    MicroBacktestConfig,
    micro_period_metrics,
    run_micro_backtest,
    write_micro_report,
)
from btc_regime.v413 import V413Params, generate_v413_signals
from btc_regime.v43 import V43Params, generate_v43_signals
from btc_regime.v8 import V8Params, generate_v8_signals, route_v4_v8_signals


START = "2020-01-01"
END = "2026-08-01"
PERIODS = {
    "train_2020_2022": ("2020-01-01", "2023-01-01"),
    "validation_2023_2024": ("2023-01-01", "2025-01-01"),
    "holdout_2025_2026_07": ("2025-01-01", "2026-08-01"),
    "full_2020_2026_07": ("2020-01-01", "2026-08-01"),
}


def _direction_cycles(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach stable cycle IDs for the stop-after-exit execution lock."""
    result = frame.copy()
    side = np.sign(result["signal"].fillna(0.0))
    active = side.ne(0)
    starts = active & side.ne(side.shift(1, fill_value=0.0))
    result["cycle_id"] = "direction_" + starts.cumsum().astype(str)
    return result


def _frequency(trades: pd.DataFrame) -> dict[str, float | int]:
    if trades.empty:
        return {"entries_per_month": 0.0, "max_days_between_entries": 0.0, "median_days_between_entries": 0.0}
    entries = pd.to_datetime(trades["entry_time"], utc=True).sort_values()
    boundaries = pd.DatetimeIndex(
        [pd.Timestamp(START, tz="UTC"), *entries, pd.Timestamp(END, tz="UTC")]
    )
    gaps = np.diff(boundaries.asi8) / 86_400e9
    years = (pd.Timestamp(END) - pd.Timestamp(START)).total_seconds() / 86_400 / 365.25
    return {
        "entries_per_month": float(len(entries) / (years * 12)),
        "max_days_between_entries": float(gaps.max()),
        "median_days_between_entries": float(np.median(gaps)),
    }


def _coverage(raw_dir: str) -> dict[str, object]:
    expected = int((pd.Timestamp(END) - pd.Timestamp(START)).total_seconds() / 60)
    batches = list(iter_intrabar_months(raw_dir, start=START, end=END))
    observed = sum(len(batch) for batch in batches)
    for previous, current in zip(batches, batches[1:]):
        if current.index[0] <= previous.index[-1]:
            raise ValueError("overlapping 1m archives would double-count execution")
    return {
        "expected_minutes": expected,
        "observed_minutes": observed,
        "missing_minutes": expected - observed,
        "coverage": observed / expected,
        "archive_batches": len(batches),
        "batches": batches,
    }


def _run_case(
    label: str,
    params: object,
    signals: pd.DataFrame,
    market: pd.DataFrame,
    funding: pd.DataFrame,
    batches: list[pd.DataFrame],
    output: Path,
    config: MicroBacktestConfig,
) -> dict[str, object]:
    result = run_micro_backtest(signals, batches, funding, config)
    case_dir = output / label
    write_micro_report(result, params, config, case_dir)  # type: ignore[arg-type]
    # Keep a separate 4h signal-level audit.  It is intentionally not used for
    # the headline result: the minute engine is the execution result, while
    # this audit isolates signal timing and compounding from fill mechanics.
    regular = run_backtest(
        signals,
        BacktestConfig(
            initial_cash=config.initial_cash,
            fee_bps=config.taker_fee_bps,
            slippage_bps=config.base_slippage_bps,
            funding_enabled=True,
        ),
    )
    regular.equity.to_csv(case_dir / "four_hour_equity.csv", header=True)
    regular.trades.to_csv(case_dir / "four_hour_trades.csv", index=False)
    periods = micro_period_metrics(result)
    metrics = {**result.metrics, **_frequency(result.trades)}
    for name, values in periods.items():
        if name.startswith("full"):
            continue
        for key in ("total_return", "cagr", "max_drawdown", "sharpe", "trade_count", "final_equity"):
            metrics[f"{name}_{key}"] = values[key]
    return {
        "metrics": metrics,
        "periods": periods,
        "four_hour_signal_audit": regular.metrics,
        "parameters": params.to_dict(),  # type: ignore[attr-defined]
        "execution": asdict(config),
    }


def _write_markdown(report: dict[str, object], output: Path) -> None:
    cases = report["cases"]
    assert isinstance(cases, dict)
    labels = {
        "V4_1_3": "V4.1.3 合并",
        "V4_1_2_baseline": "V4.1.2 基线",
        "V8_enhanced_standalone": "V8 增强（独立）",
        "V4_1_3_taker_only": "V4.1.3（全 Taker）",
    }
    rows = []
    for label, value in cases.items():
        metrics = value["metrics"]
        rows.append(
            f"| {labels.get(label, label)} | {metrics['total_return']:.2%} | {metrics['cagr']:.2%} | "
            f"{metrics['max_drawdown']:.2%} | {metrics['sharpe']:.3f} | "
            f"{int(metrics['trade_count'])} | {int(metrics['fill_count'])} | "
            f"{int(metrics['liquidation_count'])} | {metrics['max_leverage_observed']:.3f} |"
        )
    segment_rows = []
    segment_names = {
        "train_2020_2022": "训练 2020–2022",
        "validation_2023_2024": "验证 2023–2024",
        "holdout_2025_2026_07": "评估 2025-01–2026-07",
    }
    for label in ("V4_1_3", "V4_1_2_baseline", "V8_enhanced_standalone"):
        periods = cases[label]["periods"]
        for period, period_name in segment_names.items():
            metrics = periods[period]
            segment_rows.append(
                f"| {labels[label]} | {period_name} | {metrics['total_return']:.2%} | "
                f"{metrics['cagr']:.2%} | {metrics['max_drawdown']:.2%} | "
                f"{metrics['sharpe']:.3f} | {int(metrics['trade_count'])} |"
            )
    audit = cases["V4_1_3"]["four_hour_signal_audit"]
    data = report["data"]
    fees = report["fees"]
    text = f"""# V4.1.3 严格回测报告

V4.1.3 是 V4.1.2 方向引擎与增强 V8 震荡引擎的单账户合并。V4.1.2 目标仓位非零时优先使用方向仓；只有方向仓为空时，V8 才能建立仓位。两者不叠加为两个账户，不复制保证金，也不复用另一策略的止损价。

## 数据、时间和费用

- 数据区间：{data['start_inclusive_utc']} 至 {data['end_exclusive_utc']} UTC，右端不含，等价于到 2026-07-31 完整收盘。
- 信号使用已完成 4h K 线，下一 4h 边界生效；执行使用配对的 1m 成交价和标记价，结算真实资金费。
- 训练 2020–2022，验证 2023–2024，留出评估 2025-01–2026-07。早期 V8 探索曾查看留出期，因此这里的留出区间不是严格盲测。
- 返佣前 Taker 费率按 4 bps、Maker 按 0.2 bps；40% 返佣后分别为 {fees['effective_taker_bps']:.2f} bps（0.024%）和 {fees['effective_maker_bps']:.2f} bps（0.0012%）。返佣按即时净成本代理。
- 1 bps 基础滑点；成交冲击为 8 bps × sqrt(分钟参与率)，参与率上限 2%；保护退出遇跳空按不利开盘价并计冲击。
- 标记价覆盖 {data['coverage']:.6%}（{data['observed_minutes']:,}/{data['expected_minutes']:,} 分钟），剩余 {data['missing_minutes']} 分钟没有插值；原始归档未修改。

## 全样本分钟级结果

初始权益为 10,000 USDT，所有结果均已扣手续费、滑点、资金费。

| 策略 | 累计收益 | CAGR | 最大回撤 | 夏普 | 完整周期 | 填单 | 强平 | 最高杠杆 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

V4.1.3 的增强 V8 风险目标为 0.9、整轮计划风险预算 1.125%、V8 上限 3 倍；全账户仍限制 6.5 倍。V4.1.2 保留原参数和下行保护。V8 最多三层等额加仓，禁止 1/2/4 倍马丁；固定入场 ATR，止损 1.65 ATR，突破、波动冲击、超时或止损均退出，止损后同一周期不重新开仓。

V8 的可复核规则是：ADX ≤ 24、CHOP ≥ 55、效率比 ≤ 0.24 且无通道突破，连续 1 根确认震荡；ADX ≥ 27、CHOP ≤ 47、效率比明显升高或突破，连续 2 根确认离开震荡。24 根通道位置 ≤ 22% 且收盘反转、RSI ≤ 48 做多；位置 ≥ 78% 且反转、RSI ≥ 52 做空；止盈取通道中点（位置 52%），最多持有 18 根 4h K 线。每层等额、间隔 0.55 ATR，最多 3 层；波动比 ≥ 1.25 或趋势保护触发即退出，止损后冷却 6 根 K 线。

## 分段结果与解释

V4.1.3 的 4h 信号级审计为累计 {audit['total_return']:.2%}、CAGR {audit['cagr']:.2%}、最大回撤 {audit['max_drawdown']:.2%}、夏普 {audit['sharpe']:.3f}；分钟级结果额外计入逐笔成交、冲击、保护价和保证金检查。

分段分钟级结果如下：

| 策略 | 区间 | 累计收益 | CAGR | 最大回撤 | 夏普 | 完整周期 |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(segment_rows)}

详细指标位于每个子目录的 `micro_metrics.json`，`report.json` 中也保留完整参数、执行配置、资金费和维修保证金假设。组合的关键判断是：V8 增加空仓阶段的交易机会，改善成交间隔；它不参与 V4 趋势持仓期间的叠加杠杆。

每个子目录还保存 `four_hour_equity.csv` 和 `four_hour_trades.csv`。其中 4h 信号级审计只用于核对信号和复利逻辑；手续费、滑点、资金费均按同一有效费率计算，但不替代 1m 成交、冲击、保护退出和保证金检查的分钟级结果。

本报告同时给出 V4.1.2 与 V8 单独对照。V4.1.2 基线使用相同的止损后周期锁、数据和费率；因此 V4.1.3 与基线的差异可归因于 V8 接管逻辑。V8 单独结果不能直接与组合收益相加。

## 严格性和限制

- 本地 1m 归档来自 Binance USD-M 月度文件；少数官方标记价缺失已用官方日文件修复，并记录 SHA256。缺失分钟不伪造。
- Maker 是“分钟价格触及报价即成交”的可复现代理，不包含订单簿队列、延迟、拒单或真实盘口深度；报告同时保留高 Maker 费用和 Taker 对照。
- 保证金按固定历史分档假设逐分钟检查；本次无模拟强平不代表未来不会强平。
- 6.5 倍是目标信号的硬截断；表中的最高杠杆按分钟标记价除以实时权益计算，价格跳动、费用和数量取整可能使观测值短暂达到约 6.55 倍。
- 净值和回撤按 4h 边界记录，分钟标记价用于成交和保证金检查；不能把 CAGR 当作承诺收益。
- 2025 年后区间已被此前探索查看，后续应使用新的时间段作为真正盲测。

## 复现

```bash
PYTHONPATH=src python3 scripts/prepare_v8_data.py
PYTHONPATH=src python3 scripts/backtest_v413.py --raw-dir data/v8_verified --output reports/v4_1_3_40
PYTHONPATH=src python3 -m btc_regime.cli micro-backtest-v413 --raw-dir data/v8_verified --output reports/v4_1_3_40_cli
PYTHONPATH=src pytest -q
```
"""
    (output / "README.md").write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default="data/v8_verified")
    parser.add_argument("--params", type=Path, default=Path("configs/v4_1_3_params.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/v4_1_3_40"))
    args = parser.parse_args()

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    payload = json.loads(args.params.read_text(encoding="utf-8"))
    params = V413Params.from_dict(payload)
    market = load_market_data(args.raw_dir, start=START, end=END)
    market = market.loc[market.index < pd.Timestamp(END, tz="UTC")]
    funding = load_funding(args.raw_dir, start=START, end=END)
    funding = funding.loc[funding.index < pd.Timestamp(END, tz="UTC")]
    coverage = _coverage(args.raw_dir)
    batches = coverage.pop("batches")
    v413 = generate_v413_signals(market, params)
    v4 = _direction_cycles(generate_v43_signals(market, params.direction))
    v8 = generate_v8_signals(market, params.range)
    config = MicroBacktestConfig(
        taker_fee_bps=2.4,
        maker_fee_bps=0.12,
        maker_offset_bps=0.0,
        maker_order_timeout_minutes=60,
        maker_enabled=True,
        maker_exit_enabled=False,
        conservative_protection=True,
        base_slippage_bps=1.0,
        impact_bps=8.0,
        max_minute_participation=0.02,
        liquidation_fee_bps=50.0,
    )
    cases = {
        "V4_1_3": (params, v413),
        "V4_1_2_baseline": (params.direction, v4),
        "V8_enhanced_standalone": (params.range, v8),
        "V4_1_3_taker_only": (params, v413),
    }
    details: dict[str, object] = {}
    for label, (case_params, signals) in cases.items():
        case_config = replace(config, maker_enabled=label != "V4_1_3_taker_only")
        details[label] = _run_case(label, case_params, signals, market, funding, batches, output, case_config)
    report = {
        "strategy": "V4.1.3",
        "definition": "V4.1.2 direction priority; enhanced V8 takes over only while V4.1.2 is flat; one net account",
        "data": {
            "start_inclusive_utc": START,
            "end_exclusive_utc": END,
            "signal_interval": "4h",
            "execution_interval": "1m",
            **coverage,
        },
        "fees": {
            "base_taker_bps": 4.0,
            "base_maker_bps": 0.2,
            "rebate_rate": 0.40,
            "effective_taker_bps": 2.4,
            "effective_maker_bps": 0.12,
        },
        "development_split": {
            "train": PERIODS["train_2020_2022"],
            "validation": PERIODS["validation_2023_2024"],
            "evaluation": PERIODS["holdout_2025_2026_07"],
            "holdout_status": "evaluated, not pristine blind test because earlier exploration inspected this interval",
        },
        "parameters": params.to_dict(),
        "cases": details,
        "limitations": [
            "55 official mark-price minutes remain unavailable; no fabricated prices were used.",
            "Maker touch fills omit order-book queue, latency and rejection.",
            "Historical maintenance brackets are explicit model assumptions.",
            "V4.1.3 and its baselines use one net position and do not stack two accounts.",
            "No V7.1 engine is present in this checkout; this report does not claim a V7.1 merge.",
        ],
    }
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    pd.DataFrame([v["metrics"] | {"strategy": k} for k, v in details.items()]).to_csv(
        output / "comparison.csv", index=False
    )
    _write_markdown(report, output)
    print(json.dumps({k: v["metrics"] for k, v in details.items()}, indent=2))


if __name__ == "__main__":
    main()
