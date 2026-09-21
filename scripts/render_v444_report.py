"""Render V4.4.4 from frozen continuous-account and robustness results."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from btc_regime.v441_research import daily_equity, paired_block_bootstrap
from evaluate_v444 import lock_validate, read_equity

ROOT = Path("reports/v4_4_4")


def read(path):
    return json.loads((ROOT / path).read_text())


def metric_row(label, m):
    return (f"| {label} | {m['total_return']:.2%} | {m['cagr']:.2%} | "
            f"{m['sharpe']:.3f} | {m['max_drawdown']:.2%} | {m['cycles']} |")


def chart(curves):
    fig, axes = plt.subplots(2, 2, figsize=(14, 8), layout="constrained",
                             gridspec_kw={"height_ratios": [2, 1]})
    colors = {"V4.4.3": "#8a929c", "V4.4.4": "#087f8c"}
    for col, start in enumerate(["2020-01-01", "2024-01-01"]):
        for label, curve in curves.items():
            e = curve.loc[start:]
            d = daily_equity(e)
            axes[0, col].plot(d.index, d / e.iloc[0], label=label, color=colors[label], lw=1.8)
            dd = e / e.cummax() - 1
            dd = dd.resample("1D").min()
            axes[1, col].plot(dd.index, dd * 100, color=colors[label], lw=1.3)
        axes[0, col].set_title("2020-01 to 2026-08 (log scale)" if col == 0 else
                               "2024-01 to 2026-08 (rebased, same continuous account)")
        axes[0, col].set_ylabel("Net equity / window start equity")
        axes[1, col].set_ylabel("Drawdown (%)")
        axes[0, col].legend(frameon=False)
        for ax in axes[:, col]:
            ax.grid(alpha=.18)
            ax.xaxis.set_major_locator(mdates.YearLocator() if col == 0 else
                                       mdates.MonthLocator(bymonth=[1, 7]))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y" if col == 0 else "%Y-%m"))
    axes[0, 0].set_yscale("log")
    fig.suptitle("V4.4.4 | Defensive risk sizing, 40% taker-fee rebate", fontsize=17, weight="bold")
    fig.savefig(ROOT / "equity_drawdown.png", dpi=170)
    fig.savefig(ROOT / "equity_drawdown.svg")
    plt.close(fig)


def main():
    lock = lock_validate()
    selected = lock["profile"]["id"]
    base = read("continuous/V443__base/report.json")
    chosen = read(f"continuous/{selected}__base/report.json")
    curves = {"V4.4.3": read_equity(ROOT / "continuous/V443__base/equity.csv"),
              "V4.4.4": read_equity(ROOT / f"continuous/{selected}__base/equity.csv")}
    boots = {name: paired_block_bootstrap(curves["V4.4.4"].loc[a:b], curves["V4.4.3"].loc[a:b])
             for name, a, b in [("full", "2020-01-01", "2026-09-01"),
                                ("recent", "2024-01-01", "2026-09-01"),
                                ("recent_jul", "2024-01-01", "2026-08-01")]}
    stress = {case: {"V4.4.3": read(f"stress/V443__{case}/report.json"),
                     "V4.4.4": read(f"stress/{selected}__{case}/report.json")}
              for case in ["double_cost", "no_rebate", "delay_1h"]}
    rolling = []
    for choice in read("rolling_choices.json"):
        fold, profile = choice["fold"], choice["profile"]["id"]
        rolling.append({**choice, "chosen": read(f"rolling/fold{fold}/{profile}__base/report.json"),
                        "baseline": read(f"rolling/fold{fold}/V443__base/report.json")})
    reset = {"V4.4.3": read("V4.4.3__recent__minute/metrics.json"),
             "V4.4.4": read(f"{selected}__recent__minute/metrics.json")}
    audit = read("data_audit.json")
    primary_pass = all(chosen["windows"][w]["sharpe"] > base["windows"][w]["sharpe"]
                       for w in ["full", "recent", "recent_jul"])
    stress_pass = all(pair["V4.4.4"]["windows"][w]["sharpe"] > pair["V4.4.3"]["windows"][w]["sharpe"]
                      for pair in stress.values() for w in ["full", "recent", "recent_jul"])
    acceptance = {"version": "V4.4.4", "selected": selected,
                  "status": "frozen_research_candidate_historical_sharpe_improvement",
                  "primary_sharpe_objectives_pass": primary_pass,
                  "paired_stress_sharpe_objectives_pass": stress_pass,
                  "full_return_improved": chosen["metrics"]["total_return"] > base["metrics"]["total_return"],
                  "blind_oos_validated": False, "multiple_testing_adjusted": False,
                  "promote_to_default": False, "rebate_fraction": .4}
    report = {"version": "V4.4.4", "lock": lock, "acceptance": acceptance,
              "continuous": {"V4.4.3": base, "V4.4.4": chosen}, "stress": stress,
              "procedural_rolling": rolling, "bootstrap": boots, "reset_recent": reset,
              "data_audit": audit, "primary_metric": "daily arithmetic return Sharpe, rf=0, sqrt(365.25)",
              "drawdown_sampling": "hourly equity snapshots; execution and protection checked each available minute"}
    (ROOT / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (ROOT / "acceptance.json").write_text(json.dumps(acceptance, indent=2) + "\n")
    chart(curves)

    full_table = "\n".join(metric_row(label, r["metrics"]) for label, r in [("V4.4.3", base), ("V4.4.4", chosen)])
    recent_table = "\n".join(metric_row(label, r["windows"]["recent"]) for label, r in [("V4.4.3", base), ("V4.4.4", chosen)])
    july_table = "\n".join(metric_row(label, r["windows"]["recent_jul"]) for label, r in [("V4.4.3", base), ("V4.4.4", chosen)])
    yearly_table = "\n".join(
        f"| {year if year != '2026' else '2026（1–8月）'} | {old['total_return']:.2%} | {new['total_return']:.2%} | "
        f"{old['sharpe']:.3f} | {new['sharpe']:.3f} | {old['max_drawdown']:.2%} | {new['max_drawdown']:.2%} |"
        for year, old in base["yearly"].items() for new in [chosen["yearly"][year]])
    stress_table = "\n".join(
        f"| {name} | {pair['V4.4.3']['metrics']['sharpe']:.3f} → {pair['V4.4.4']['metrics']['sharpe']:.3f} | "
        f"{pair['V4.4.3']['windows']['recent']['sharpe']:.3f} → {pair['V4.4.4']['windows']['recent']['sharpe']:.3f} | "
        f"{pair['V4.4.3']['windows']['recent_jul']['sharpe']:.3f} → {pair['V4.4.4']['windows']['recent_jul']['sharpe']:.3f} |"
        for case, name in [("double_cost", "成本冲击"), ("no_rebate", "取消返佣"), ("delay_1h", "延迟 1 小时")]
        for pair in [stress[case]])
    rolling_table = "\n".join(
        f"| {r['evaluation'][0]} 至 {r['evaluation'][1]} 前 | {r['profile']['id']} | "
        f"{r['baseline']['metrics']['sharpe']:.3f} | {r['chosen']['metrics']['sharpe']:.3f} | "
        f"{r['baseline']['metrics']['total_return']:.2%} | {r['chosen']['metrics']['total_return']:.2%} |"
        for r in rolling)
    bootstrap_table = "\n".join(
        f"| {name} | [{b['sharpe_difference_95pct'][0]:.4f}, {b['sharpe_difference_95pct'][1]:.4f}] |"
        for key, name in [("full", "全样本"), ("recent", "2024 年后"), ("recent_jul", "2024 年后、不含 2026-08")]
        for b in [boots[key]])
    candidate_table = "\n".join(
        f"| {r['id']} | {r['profile']['params']['risk']} | {r['metrics']['sharpe']:.3f} | "
        f"{r['windows']['recent']['sharpe']:.3f} | {r['windows']['recent_jul']['sharpe']:.3f} | "
        f"{'是' if r['eligible'] else '否'} |" for r in read("continuous_selection.json"))
    reset_table = "\n".join(metric_row(name, m) for name, m in reset.items())
    header = "| 策略 | 累计净收益 | CAGR | 日收益夏普 | 最大回撤 | 完整周期 |\n|---|---:|---:|---:|---:|---:|"
    em = chosen["execution_metrics"]
    text = f"""# V4.4.4：全量回测后的防御型风险调节

V4.4.4 已冻结为 **`{selected}`**。相对 V4.4.3，全样本和 2024 年后日收益夏普均提高，回撤降低；累计收益有所下降。因此本版实现的是用户本轮优先目标——提高整体、尤其近期夏普，尚未实现收益与夏普同时提高。

## 统一口径的结果

本轮从 **2020-01-01 00:00 UTC 到 2026-09-01 00:00 UTC（不含）**运行连续账户，覆盖至本地完整缓存的 2026 年 8 月末。初始权益 10,000 USDT，复利，无年度或 2024 边界重置，仅在终点强制平仓。两版均采用 40% Taker 返佣：4 bps × (1−40%) = **单边净手续费 2.4 bps**。

全样本：

{header}
{full_table}

2024-01 至 2026-08（从上述同一账户切片）：

{header}
{recent_table}

排除 2026 年 8 月后的近期结果，避免一个强势月份掩盖此前表现：

{header}
{july_table}

夏普使用 UTC 日末权益的简单日收益、无风险收益率为零、年化系数 √365.25。回撤来自每小时权益快照；成交、保护退出和保证金检查使用实际可用分钟。`execution_metrics` 中另有按小时收益计算的夏普，**本文统一使用日收益夏普**，不混用。

![连续账户净值与回撤](equity_drawdown.png)

## 全量数据揭示的问题

| 年度 | V4.4.3 收益 | V4.4.4 收益 | V4.4.3 夏普 | V4.4.4 夏普 | V4.4.3 回撤 | V4.4.4 回撤 |
|---|---:|---:|---:|---:|---:|---:|
{yearly_table}

V4.4.3 的薄弱点不仅出现在 ETF 之后：2022 年持续亏损，2024 年的风险效率也偏低。新的组合风险设置主要改善 2023、2025 和 2026 年的风险效率，2024 年夏普几乎持平。2022 年亏损缩小，但夏普反而更负，熊市防护仍不充分。

SEC 于 2024-01-10 批准现货比特币 ETP 上市交易，见[官方声明](https://www.sec.gov/newsroom/speeches-statements/gensler-statement-spot-bitcoin-011023)。ETF 改变参与者结构是研究假设；本回测没有建立“ETF 导致策略退化”的因果证据。因此用 2024 年后的更高评价权重引导选参，不在交易逻辑中写入按年份切换规则。

## 最终策略

4h EMA(20/80)、ADX 进入/退出阈值 24/17 产生核心多头目标；核心还继承原有震荡反弹模块。小时收盘出现核心恢复为正、重新站上 EMA(20)、突破此前 6 小时高点任一事件时，才允许新开周期。初始止损 1.5 ATR(4h)，跟踪止损 3 ATR(4h)，最多持仓 72 小时，退出冷却 3 小时。目标杠杆上限 4 倍，只做多或空仓。

本版在 V4.4.3 入场框架上采用如下完整风险方案：

| 风险设置 | V4.4.3 | V4.4.4 |
|---|---:|---:|
| ATR 年化波动代理的目标波动率 | 107.5% | 95% |
| 波动冲击进入/退出比值 | 1.25 / 1.10 | 1.15 / 1.05 |
| 波动冲击期仓位倍率 | 25% | 15% |
| 下行波动压力仓位倍率 | 30% | 20% |
| 滚动价格回撤刹车仓位倍率 | 30% | 20% |

波动冲击需同时满足负动量，采用不同进入/退出阈值防止反复切换；下行压力阈值仍为下行波动占比 0.625。价格刹车仍在距过去 360 根 4h 收盘高点回撤 15% 时启动，回到 7.5% 以内解除。各风险倍率相乘，并保留资金费拥挤降仓和低下行波动时的配置。它们共同实现更早、更强的风险收缩；当前实验没有单独证明每个改动各自的贡献。

最终没有选中更快 EMA、更短持仓或额外日线门槛。全样本完整交易周期由 401 变为 398，近期由 150 变为 148。频率不是本版增益来源；同一段行情中的更多交易也不能视为更多独立市场样本。空头仍未加入，前序版本的空头探索没有提供足够依据，本轮重点验证风险缩放。

配置：[冻结参数](../../configs/v4_4_4_params.json)；实现：[v444.py](../../src/btc_regime/v444.py)。默认 `V444Params()` 与冻结配置一致。交易信号使用已完成的小时、4h 和日线信息，最早在对应小时收盘后的分钟成交；不存在当天未收盘日线提前可见的安排。

## 筛选、锁定与样本边界

最终候选空间为 192 组：两种速度、三种初始止损、两种跟踪止损、两种持仓期限、两种入场模式、两种日线门槛和两种风险方案。小时代理筛选采用 35% 的 2020–2023 效用与 65% 的 2024 年后五个时间段平均效用，并惩罚分段夏普离散；效用 = 夏普 + 0.5×年化对数增长 + 2×最大回撤（负值）。八个候选随后进行了真实分钟复核及全历史连续账户比较。

最终锁定要求：全样本、2024 年后含 8 月、2024 年后截至 7 月三种夏普都高于 V4.4.3；全样本/近期回撤不超过 45%/35%；全样本和近期累计收益至少保留基线的 70%。合格者按 35% 全样本夏普 + 65% 近期截至 7 月夏普 + 0.5×全样本最大回撤排序。只有 `{selected}` 同时满足条件。

| 候选 | 风险 | 全样本夏普 | 近期含 8 月夏普 | 近期截至 7 月夏普 | 满足最终条件 |
|---|---|---:|---:|---:|---|
{candidate_table}

这是对已知历史的开发：2026 年 8 月在前序研究中已经查看，本轮最终资格检查也使用了它，**不是盲样本外测试**。研究经历过初版 96 组中的 reclaim 入场缺陷、修复重跑以及扩展至 192 组，属于自适应重复搜索；192 是最终候选空间大小，不是所有历史尝试的总数。旧结果在 `superseded_exploration/`，不作为本版证据。最终选择、源码及实际使用的数据缓存 SHA-256 记录在 [final_selection_lock.json](final_selection_lock.json)。

## 冻结后的压力测试

所有压力设置同时应用于两版，以下箭头均为 V4.4.3 → V4.4.4：

| 场景 | 全样本夏普 | 2024 年后夏普 | 2024 年后截至 7 月夏普 |
|---|---:|---:|---:|
{stress_table}

成本冲击使用净 Taker 4.8 bps、基础滑点 3 bps、冲击系数 16 bps；取消返佣使用 Taker 4 bps，其余按基础设置；延迟测试把全部信号及保护更新推迟一小时。三项压力下三个主要夏普口径均仍优于基线，说明历史改善不只依赖 40% 返佣或最及时执行。

程序化滚动选参在每个边界仅使用此前收益，对八个候选按 35% 全部历史夏普 + 65% 最近两年夏普 + 回撤项评分；之后空仓隔离 14 天，再独立以 10,000 USDT 评估下一段：

| 评估区间（UTC） | 当时选中 | 基线夏普 | 所选夏普 | 基线收益 | 所选收益 |
|---|---|---:|---:|---:|---:|
{rolling_table}

五段中四段夏普领先，但 2025 年上半年选中的 `r029` 明显落后。这张表评价的是滚动选择程序，不是固定 `r025` 的样本外成绩。八个候选的设计及入围使用过后续历史，存在候选集合层面的前视选择，不能因按时间滚动就声称严格样本外。

14 天配对区块 bootstrap、2,000 次抽样，V4.4.4 减 V4.4.3 的夏普差 95% 区间：

| 区间 | 夏普差 95% 区间 |
|---|---:|
{bootstrap_table}

全样本和截至 7 月的近期区间包含零；含 8 月的近期区间为正，但它是选参后的条件统计，未做多重试验校正。应将本版视为历史夏普改善的冻结研究候选；不能据此宣称已证明未来泛化优势。

## 执行、数据和口径核对

基础执行为单边净 Taker 2.4 bps、滑点 1 bps + 8 bps×√分钟参与率、真实历史资金费、0.001 BTC 数量步长、5 USDT 最小名义额。常规成交参与率上限 2%/分钟；保守保护单和强平单另计冲击与跳空，不保证在触发价成交。返佣按成交时净额记账，不降低资金费、滑点和强平费；未模拟返佣到账延迟。

本版全样本最终权益 {em['final_equity']:,.2f} USDT，成交 {int(em['fill_count'])} 笔，完整周期 {int(em['trade_count'])} 个，模拟强平 {int(em['liquidation_count'])} 次。4 倍是目标杠杆上限，持仓后权益变化导致实际观测峰值 {em['max_leverage_observed']:.3f} 倍。合约规则与维持保证金使用执行模型中的固定假设，并非完整历史交易所档位快照。

共 {audit['expected_minutes']:,} 个理论分钟，配对成交价/标记价记录 {audit['paired_minutes']:,} 个，缺少 {audit['missing_minutes']} 个（2020-01：29，2020-12：24，2024-08：2），无重复时间戳或空值。缺口没有用未来值补齐，缺口内不能完整模拟成交/保护触发；明细见 [data_audit.json](data_audit.json)。2026 年 9 月未纳入，本报告中的“全量”指上述起止范围。

为对齐 V4.4.3 前一版报告，另做了 **2024-01 重新以 10,000 USDT 起步、截至 2026-07** 的分钟回测：

{header}
{reset_table}

这个重新起步口径与前文连续账户切片不同：2024 边界持仓、账户规模、数量取整和流动性冲击路径均可能不同。主要结论使用连续账户切片，不把两个口径的收益率交叉比较。

## 复现与交付

正式汇总：[report.json](report.json)；机器可读验收：[acceptance.json](acceptance.json)。完整净值、成交、周期、资金费和强平记录在 `continuous/{selected}__base/`，基线在 `continuous/V443__base/`；逐场景结果在 `stress/`、`rolling/`。初始 V4.4.3 基线全量输出也保留在 `baseline_v443_full/`，最终对比采用 `continuous/` 统一边界口径。

安装 `pyproject.toml` 中的依赖（绘图需 matplotlib）后，在仓库根目录使用已有缓存重现冻结版本：

```bash
PYTHONPATH=src:scripts python3 scripts/full_backtest_v444.py
PYTHONPATH=src:scripts python3 scripts/evaluate_v444.py stress --workers 3
PYTHONPATH=src:scripts python3 scripts/evaluate_v444.py rolling --workers 3
PYTHONPATH=src:scripts python3 scripts/render_v444_report.py
PYTHONPATH=src python3 -m pytest -q
```

`scripts/research_v444.py screen/minute` 对应开发阶段，`scripts/evaluate_v444.py candidates/freeze` 对应连续账户选择。锁定后禁止覆盖筛选和重新选择；审计保留 `phase1/` 快照。研究版未修改项目的默认实盘配置。

代码验证：全套 84 项测试通过，包括防御型信号的前缀因果性、目标杠杆边界及基础风险对照与 V4.4.3 同参数一致性；本轮 Python 文件通过 Ruff 检查。
"""
    (ROOT / "README.md").write_text(text)
    print(json.dumps({"selected": selected, "acceptance": acceptance, "bootstrap": boots}, indent=2))


if __name__ == "__main__":
    main()
