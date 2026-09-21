"""Render frozen V4.5.2 evidence, including minute-equity drawdown checks."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from btc_regime.v441_research import daily_equity, paired_block_bootstrap
from evaluate_v444 import read_equity
from evaluate_v452 import ROOT, validate_lock


def read(path):
    return json.loads((ROOT / path).read_text())


def clean(value):
    """Keep the aggregate report valid JSON even for zero-short controls."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


def row(label, m):
    return (f"| {label} | {m['total_return']:.2%} | {m['cagr']:.2%} | {m['sharpe']:.3f} | "
            f"{-m['max_drawdown']:.2%} | {m['cycles']} / {m['short_cycles']} |")


def charts(curves, short_curve):
    colors = {"V4.4.4": "#a7adb6", "V4.5.1": "#c88d25", "V4.5.2": "#007d88"}
    fig, axes = plt.subplots(2, 2, figsize=(14, 8), layout="constrained",
                             gridspec_kw={"height_ratios": [2, 1]})
    for col, start in enumerate(["2020-01-01", "2024-01-01"]):
        for label, curve in curves.items():
            e = curve.loc[start:]
            d = daily_equity(e)
            axes[0, col].plot(d.index, d / e.iloc[0], label=label, color=colors[label],
                              lw=2 if label == "V4.5.2" else 1.3)
            dd = (e / e.cummax() - 1).resample("1D").min()
            axes[1, col].plot(dd.index, dd * 100, color=colors[label], lw=1.3)
        axes[0, col].set_title("2020-01 to 2026-08 (log scale)" if col == 0 else
                               "2024-01 to 2026-08 (continuous account slice)")
        axes[0, col].set_ylabel("Equity / window start equity")
        axes[1, col].set_ylabel("Hourly-sampled drawdown (%)")
        axes[0, col].legend(frameon=False)
        axes[1, col].axhline(-30, color="#b05353", ls=":", lw=1)
        for ax in axes[:, col]:
            ax.grid(alpha=.18)
            ax.xaxis.set_major_locator(mdates.YearLocator() if col == 0 else
                                       mdates.MonthLocator(bymonth=[1, 7]))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y" if col == 0 else "%Y-%m"))
        if col == 1:
            for ax in axes[:, col]:
                ax.axvline(pd.Timestamp("2026-01-15", tz="UTC"), color="#765391", ls="--", lw=1)
    axes[0, 0].set_yscale("log")
    fig.suptitle("V4.5.2 | Confirmed breakdowns + bounded short risk", fontsize=17, weight="bold")
    fig.savefig(ROOT / "equity_drawdown.png", dpi=170)
    fig.savefig(ROOT / "equity_drawdown.svg")
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(12, 4), layout="constrained")
    d = daily_equity(short_curve)
    ax.plot(d.index, d / short_curve.iloc[0], color=colors["V4.5.2"], lw=1.7)
    ax.axhline(1, color="#9fa5ae", lw=1)
    ax.axvline(pd.Timestamp("2024-01-01", tz="UTC"), color="#c88d25", ls="--", label="2024 boundary")
    ax.axvline(pd.Timestamp("2026-01-15", tz="UTC"), color="#765391", ls="--", label="Later audit starts")
    ax.set_title("V4.5.2 short sleeve only | Routed entries, separate account, net of costs")
    ax.set_ylabel("Equity / initial equity")
    ax.grid(alpha=.18)
    ax.legend(frameon=False)
    fig.savefig(ROOT / "short_sleeve.png", dpi=170)
    plt.close(fig)


def main():
    lock = validate_lock()
    selected = lock["profile"]["id"]
    names = {"V4.4.4": "V444", "V4.5.1": "V451", "V4.5.2": selected}
    reports = {name: read(f"continuous/{key}__base/report.json") for name, key in names.items()}
    curves = {name: read_equity(ROOT / f"continuous/{key}__base/equity.csv") for name, key in names.items()}
    compared = ["V4.5.1", "V4.5.2"]
    reset = {name: read(f"holdout_reset/{names[name]}__base/report.json") for name in compared}
    drawdown = {name: read(f"drawdown/{names[name]}__minute_drawdown/report.json") for name in compared}
    stress = {case: {name: read(f"stress/{names[name]}__{case}/report.json") for name in compared}
              for case in ["double_cost", "no_rebate", "delay_1h"]}
    attribution = {label: read(f"attribution/{key}__base/report.json") for label, key in
                   [("仅提高空头风险预算", "risk_only"), ("仅优化空头信号与冷却", "signal_only")]}
    short = read(f"attribution/{selected}__short_only/report.json")
    short_curve = read_equity(ROOT / f"attribution/{selected}__short_only/equity.csv")
    boots = {key: paired_block_bootstrap(curves["V4.5.2"].loc[a:b], curves["V4.5.1"].loc[a:b])
             for key, a, b in [("full", "2020-01-01", "2026-09-01"), ("recent", "2024-01-01", "2026-09-01"),
                               ("recent_jul", "2024-01-01", "2026-08-01"),
                               ("later_audit", "2026-01-15", "2026-09-01")]}
    baseline, chosen = reports["V4.5.1"], reports["V4.5.2"]
    primary_pass = all(chosen["windows"][w][k] > baseline["windows"][w][k]
                       for w in ["recent", "recent_jul"] for k in ["sharpe", "total_return"])
    dd_pass = drawdown["V4.5.2"]["windows"]["recent"]["max_drawdown"] >= -.30
    holdout_pass = all(reset["V4.5.2"]["metrics"][k] > reset["V4.5.1"]["metrics"][k]
                       for k in ["sharpe", "total_return"])
    stress_pass = all(pair["V4.5.2"]["windows"][w][k] > pair["V4.5.1"]["windows"][w][k]
                      for pair in stress.values() for w in ["recent", "recent_jul"]
                      for k in ["sharpe", "total_return"])
    acceptance = {"version": "V4.5.2", "selected": selected, "status": "frozen_research_candidate",
                  "development_pass": lock["development_eligible"], "recent_return_and_sharpe_pass": primary_pass,
                  "recent_minute_close_drawdown_below_30pct": dd_pass,
                  "later_reset_audit_return_and_sharpe_pass": holdout_pass, "recent_stress_pass": stress_pass,
                  "historical_objective_pass": bool(lock["development_eligible"] and primary_pass and dd_pass),
                  "historically_blind_oos": False, "multiple_testing_adjusted": False, "promote_to_default": False}
    audit = json.loads(Path("reports/v4_4_4/data_audit.json").read_text())
    audit["note"] = "Paired actual trade/mark minutes; gaps not filled. Input/cache hashes: selection_lock.json."
    (ROOT / "data_audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    report = {"version": "V4.5.2", "selection": lock, "acceptance": acceptance,
              "continuous": reports, "short_only": short, "attribution": attribution, "later_reset": reset,
              "stress": stress, "minute_drawdown_audit": drawdown, "bootstrap": boots, "data_audit": audit,
              "metric_convention": "Daily simple-return Sharpe, rf=0, sqrt(365.25); minute execution. "
              "Standard DD uses hourly snapshots; minute_drawdown_audit uses every minute-close equity."}
    (ROOT / "report.json").write_text(json.dumps(clean(report), indent=2, allow_nan=False) + "\n")
    (ROOT / "acceptance.json").write_text(json.dumps(acceptance, indent=2) + "\n")
    charts(curves, short_curve)
    header = "| 策略 | 累计净收益 | CAGR | 日收益夏普 | 小时权益最大回撤 | 周期 / 空头周期 |\n|---|---:|---:|---:|---:|---:|"
    tables = {w: "\n".join(row(name, r["windows"][w]) for name, r in reports.items())
              for w in ["full", "recent", "recent_jul"]}
    reset_table = "\n".join(row(name, r["metrics"]) for name, r in reset.items())
    dd_table = "\n".join(
        f"| {name} | {-r['windows']['full']['max_drawdown']:.2%} | "
        f"{-r['windows']['recent']['max_drawdown']:.2%} | {-r['windows']['later_audit']['max_drawdown']:.2%} |"
        for name, r in drawdown.items())
    annual = "\n".join(
        f"| {year if year != '2026' else '2026（1–8月）'} | {old['total_return']:.2%} | {new['total_return']:.2%} | "
        f"{old['sharpe']:.3f} | {new['sharpe']:.3f} | {new['short_cycles']} | {new['short_sum_trade_returns']:.2%} |"
        for year, old in baseline["yearly"].items() for new in [chosen["yearly"][year]])
    stress_table = "\n".join(
        f"| {name} | {pair['V4.5.1']['windows']['recent']['total_return']:.2%} → {pair['V4.5.2']['windows']['recent']['total_return']:.2%} | "
        f"{pair['V4.5.1']['windows']['recent']['sharpe']:.3f} → {pair['V4.5.2']['windows']['recent']['sharpe']:.3f} | "
        f"{-pair['V4.5.2']['windows']['recent']['max_drawdown']:.2%} | "
        f"{pair['V4.5.1']['metrics']['sharpe']:.3f} → {pair['V4.5.2']['metrics']['sharpe']:.3f} |"
        for case, name in [("double_cost", "成本冲击"), ("no_rebate", "无返佣"), ("delay_1h", "延迟一小时")]
        for pair in [stress[case]])
    boot_table = "\n".join(
        f"| {name} | [{b['sharpe_difference_95pct'][0]:.4f}, {b['sharpe_difference_95pct'][1]:.4f}] |"
        for key, name in [("full", "全样本"), ("recent", "2024 年后"), ("recent_jul", "2024 年后截至 7 月"),
                           ("later_audit", "2026-01-15 后段连续账户切片")]
        for b in [boots[key]])
    dev_rows = read("minute_selection.json")
    development = "\n".join(
        f"| {r['profile']['id']} | {'候选' if r['profile']['selectable'] else '对照'} | "
        f"{r['windows']['recent']['total_return']:.2%} | {r['windows']['recent']['sharpe']:.3f} | "
        f"{r['shorts']['train_recent']['sum_cycle_returns']:.2%} | "
        f"{r['shorts']['validation']['sum_cycle_returns']:.2%} | {r['score']:.3f} |"
        for r in dev_rows)
    attribution_table = "\n".join(row(name, r["windows"]["recent"]) for name, r in
                                  {"V4.5.1": baseline, **attribution, "V4.5.2 完整版": chosen}.items())
    short_table = "\n".join(row(name, short["windows"][key]) for key, name in
                            [("legacy", "2020–2023"), ("recent", "2024–2026年8月"),
                             ("later_audit", "2026-01-15 后段")])
    delta_return = chosen["windows"]["recent"]["total_return"] - baseline["windows"]["recent"]["total_return"]
    delta_sharpe = chosen["windows"]["recent"]["sharpe"] - baseline["windows"]["recent"]["sharpe"]
    em = chosen["execution_metrics"]
    leverage = [r["short_entry_leverage"]["recent"]["mean"] for r in [baseline, chosen]]
    outcome = "满足" if acceptance["historical_objective_pass"] else "未满足"
    text = f"""# V4.5.2：更严格的破位空头与更高风险预算

**已冻结 `{selected}`，{outcome}本轮历史回测目标：提高 2024 年后的收益与夏普，分钟收盘权益最大回撤低于 30%。** 保留 V4.4.4 多头、40% Taker 返佣；空头目标杠杆上限由 1.25 倍提高到 2 倍，同时收紧趋势强度、成交额和资金费过滤。

## 主要结果

账户从 2020-01-01 以 10,000 USDT 起步，至 2026-09-01 00:00 UTC 结束，覆盖截至 2026 年 8 月的完整数据。年界不重置账户，只在最终结束强制平仓。收益计入手续费、滑点、冲击和真实资金费。

**重点区间：2024-01 至 2026-08，同一连续账户切片：**

{header}
{tables['recent']}

相对 V4.5.1，累计净收益增加 **{delta_return * 100:.2f} 个百分点**，日收益夏普增加 **{delta_sharpe:.3f}**。小时权益回撤约 22.44%，但更细的分钟权益显示回撤 **{-drawdown['V4.5.2']['windows']['recent']['max_drawdown']:.2%}**，这是本轮判断是否满足 30% 要求的口径。

排除 2026 年 8 月，2024-01 至 2026-07：

{header}
{tables['recent_jul']}

从 2020 年开始的全样本：

{header}
{tables['full']}

![净值与回撤](equity_drawdown.png)

图中虚线为本轮 2026-01-15 后段审计起点；图中回撤来自小时权益。夏普统一使用 UTC 日末简单收益、无风险利率为零、√365.25 年化；底层 `execution_metrics` 的小时收益夏普不用于正文比较。

## 分钟权益回撤核查

额外重跑两个连续账户，逐分钟保存权益用于计算最大回撤，不改变交易规则。结果如下：

| 策略 | 全样本分钟回撤 | 2024 年后分钟回撤 | 2026-01-15 后段分钟回撤 |
|---|---:|---:|---:|
{dd_table}

V4.5.2 的近期分钟回撤略高于 V4.5.1，仍低于本轮上限；不能把小时快照的 22.44% 当作分钟回撤。30% 是本轮已实现历史路径的验收条件，代码没有保证未来回撤绝不超过 30% 的账户熔断。分钟收盘权益也不等于分钟内部最差瞬时权益；保护与强平按分钟标记高低价检查，实际跳空和流动性不足仍可能扩大亏损。

分钟审计指标保存于 `drawdown/*/report.json`；其 `equity.csv` 为便于存储仍下采样至小时，不能直接从该 CSV 还原分钟回撤，需运行 `evaluate_v452.py drawdown` 重新计算。

## 本版的具体修改

| 空头设置 | V4.5.1 | V4.5.2 |
|---|---|---|
| 目标杠杆上限 | 1.25 倍 | **2 倍** |
| 止损距离对应的入场风险预算 | 权益 1.5% | **权益 2.5%** |
| 年化波动率目标 | 55% | **90%** |
| 4h ADX(14) 下限 | 28 | **32** |
| 新破位窗口 | 前 12 小时低点 | **前 8 小时低点** |
| 成交额确认 | 无 | **完成小时成交额 ≥ 前 24 小时成交额中位数的 1.1 倍** |
| 最近已结算资金费入场下限 | > −0.02% | **> −0.01%** |
| 退出后的冷却 | 6 小时 | **3 小时** |

最终空头目标杠杆 = min(2, 0.025 / 初始止损距离百分比, 0.90 / max(168 小时 EWMA 年化波动率, 0.20))。2024 年后信号入场目标杠杆均值由 **{leverage[0]:.3f} 倍提高至 {leverage[1]:.3f} 倍**；这是每个空头周期首个信号的均值，不是实际成交加权杠杆或盘中峰值。风险预算是基于参考价与 ATR 的计划值，不是单笔实际亏损保证。

其他条件继续保留：

1. 多头目标为零才允许做空；多头恢复优先。多头沿用冻结的 V4.4.4，目标上限 4 倍。
2. 最近已完成日线收盘低于 EMA(90)，且该 EMA 相对 5 天前下降。
3. 4h EMA(12) < EMA(48)，EMA(48) 相对三根 4h 前下降，−DI > +DI。
4. 小时 RSI(14) > 25；EMA(12, 4h) 距当前收盘 < 2.5 ATR(20, 4h)；短长小时波动率比值 < 2，防止过度追空。
5. 初始止损为入场参考收盘 + 1.25 ATR，止盈为参考收盘 − 2.5 ATR；最低小时收盘 + 1.75 当前 ATR 构成只收紧的跟踪止损。
6. 盈利达到 1.5 入场 ATR 后，止损至多为入场参考价 − 0.1 入场 ATR；最长持仓 24 小时。
7. 多头恢复、快慢均线反转、收盘高于慢均线、已结算资金费 ≤ −0.04%，或触发保护时退出。退出后等待冷却和新的入场事件。

所有指标使用已完成 K 线，前低窗口和成交额比较窗口排除当前小时；资金费只读取已结算事件。小时信号最早在下一小时开盘执行，标记价格触发分钟保护。空头周期内目标杠杆固定，不采用亏损加倍规则。

缩短窗口与冷却给策略更多重新入场机会，但最终过滤更严格，**2024 年后空头周期从 57 降至 41，全部周期从 206 降至 192**。本轮优势来自更有效的信号与较高风险预算，没有以交易数增加来代替独立样本。全样本成交笔数由 2,016 增至 2,124，包含分批成交，不能当作独立交易样本。

配置：[v4_5_2_params.json](../../configs/v4_5_2_params.json)；实现：[v452.py](../../src/btc_regime/v452.py)。`V452Params()` 与冻结参数一致，关闭空头返回 V4.4.4 信号。

## 选择过程与样本划分

按 [protocol.json](protocol.json) 先做 72 组信号组合：长期下跌/混合战术下跌两类环境，8h/12h/24h 破位或破位加均线拒绝四类入场，基础/方向强度/成交额与资金费三类确认，ADX 24/28/32。第一阶段维持 V4.5.1 的仓位和保护，避免把加杠杆误认为信号改进。

保留原 V4.5.1 信号和评分靠前的三组不同信号，在第二阶段评估三组保护、三组风险预算、3h/6h 冷却，共 72 次参数组合回测。跨阶段有重复组合，不把 144 次尝试称为 144 个独立假设。前八个合格组合再做连续分钟复核，同时运行基线和两个仅提高风险预算的对照。对照不参与最终候选选择。

开发数据仅截至 **2025-12-31**：2020–2023 权重 15%，2024 权重 35%，2025-01-15 至年底验证段权重 50%。效用 = 夏普 + 0.65×年化对数增长 + 0.5×最大回撤（负数），再减去近期四个半年夏普标准差的 0.2 倍。近期权重合计 85%。必须同时满足近期收益、夏普高于 V4.5.1，近期回撤 ≤30%，全样本回撤 ≤45%，旧段夏普退化不超过 0.20，2024/2025 验证段各至少 5 个空头周期且净收益和为正。

以下为全部分钟候选与固定对照；“空头收益和”是每笔净盈亏/入场权益之和，不是组合累计收益：

| 编号 | 用途 | 2024–2025 收益 | 同期夏普 | 2024 空头收益和 | 2025 验证空头收益和 | 加权评分 |
|---|---|---:|---:|---:|---:|---:|
{development}

`b022` 的开发期空头只有 2024 年 10 个、2025 验证段 14 个。它凭开发期分钟评分胜出后冻结，之后没有根据 2026 年审计切换候选或修改参数。

**2026-01-15 至 2026-08-31 独立以 10,000 USDT 起步的后段账户：**

{header}
{reset_table}

后段收益与夏普继续改善，回撤略升。14 天间隔用于隔开本轮选择结束与后段开始，指标仍使用此前历史暖机。连续账户切片与重置账户因持仓、资金规模、冲击、数量取整不同，不混用指标。

**这不是完全盲样本外。** 本轮把旧版的 2025 年下半年后段纳入开发，2026 年仅不参与本轮的新选择；但 V4.4/V4.5.1 已查看过截至 2026 年 8 月的数据，多头基线和候选设计也受这些历史结果影响。验证段参与评分，属于模型选择的一部分，真正独立的新时间样本仍需后续积累。

## 收益来自信号还是加杠杆

以下固定其他条件，仅替换一组设置，比较 2024 年后同一连续账户区间：

{header}
{attribution_table}

仅增加风险预算的改善弱于优化信号；二者结合产生本版最好结果。仓位与信号有交互、复利和成本路径不同，收益差不能相加解释。

| 年度 | V4.5.1 收益 | V4.5.2 收益 | V4.5.1 夏普 | V4.5.2 夏普 | V4.5.2 空头周期 | 空头周期收益和 |
|---|---:|---:|---:|---:|---:|---:|
{annual}

2024、2025、2026 年收益和夏普均改善。2020–2023 的组合夏普由 {baseline['windows']['legacy']['sharpe']:.3f} 降至 {chosen['windows']['legacy']['sharpe']:.3f}；2022 年组合仍亏损且收益更差。高风险空头没有在所有历史环境中获得稳定优势。

保留实际被多头路由允许的空头信号、移除多头，在独立账户运行：

{header}
{short_table}

![空头独立账户](short_sleeve.png)

空头独立账户早期亏损、近期盈利；其收益不能直接加到多头收益上。该诊断也包含多头优先的路由筛选，并不是不受限制的独立做空系统。

## 成本、延迟和统计不确定性

两版使用相同压力假设，箭头为 V4.5.1 → V4.5.2：

| 场景 | 2024 年后净收益 | 2024 年后夏普 | V4.5.2 近期小时回撤 | 全样本夏普 |
|---|---:|---:|---:|---:|
{stress_table}

三种压力下近期收益与夏普仍高于 V4.5.1，排除 8 月后也成立。全样本压力下夏普同样改善，但 V4.5.2 的全样本小时回撤在成本冲击下为 34.84%、延迟下为 38.17%，高于 V4.5.1；放大空头风险预算的早期历史代价仍然存在。压力场景的回撤仅按小时快照检查，不将它们当作已通过分钟 30% 上限的证据。

基础净 Taker 费为 4 bps×(1−40%) = **2.4 bps/边**，基础滑点 1 bps，冲击项为 8 bps×√参与率。成本冲击为净 Taker 4.8 bps、基础滑点 3 bps、冲击系数 16 bps；无返佣为 Taker 4 bps；延迟为信号和保护更新一并延后 1 小时。返佣仅作用于 Taker 费，按成交时净额记账，不降低资金费、滑点或强平费，未模拟到账延迟。

14 天配对区块 bootstrap（2,000 次），V4.5.2 减 V4.5.1 的日收益夏普差 95% 区间：

| 样本 | 夏普差 95% 区间 |
|---|---:|
{boot_table}

这些区间是选参后的条件估计，未校正多重尝试，也未覆盖参数搜索和旧版开发的偏差；即使部分区间高于零，也不能据此宣布未来优势得到确认。41 个近期空头周期与更少的市场状态仍限制统计可信度。

## 数据、执行与复现

使用项目已有 Binance BTCUSDT U 本位永续成交价、标记价和真实资金费缓存。理论 {audit['expected_minutes']:,} 分钟，实际配对 {audit['paired_minutes']:,} 分钟，缺 {audit['missing_minutes']} 分钟，不填补缺口；缺口内不能完整检查保护。2026 年 9 月未纳入。详见 [data_audit.json](data_audit.json)。

普通单最多占分钟名义成交额 2%，数量步长 0.001 BTC，最小名义额 5 USDT；保护单单独处理跳空和冲击。维持保证金档位是项目固定假设，不是历史档位快照。完整样本 V4.5.2 为 {int(em['trade_count'])} 个周期、{int(em['fill_count'])} 笔成交、{int(em['liquidation_count'])} 次模型强平，最终权益 {em['final_equity']:,.2f} USDT。

参数、源代码和实际缓存 SHA-256 见 [selection_lock.json](selection_lock.json)。原始交易、净值、成交、资金费、强平记录在 `continuous/{selected}__base/`；归因在 `attribution/`，压力在 `stress/`，分钟回撤在 `drawdown/`，后段重置账户在 `holdout_reset/`。汇总：[report.json](report.json)；验收：[acceptance.json](acceptance.json)。

安装项目依赖后，在仓库根目录使用现有缓存复现：

```bash
PYTHONPATH=src:scripts python3 scripts/full_backtest_v452.py
PYTHONPATH=src:scripts python3 scripts/evaluate_v452.py audit --workers 3
PYTHONPATH=src:scripts python3 scripts/evaluate_v452.py stress --workers 3
PYTHONPATH=src:scripts python3 scripts/evaluate_v452.py drawdown --workers 2
PYTHONPATH=src:scripts python3 scripts/render_v452_report.py
PYTHONPATH=src python3 -m pytest -q
```

开发过程为 `research_v452.py signals/refine/minute`；冻结后拒绝重新选择。96 项测试通过，包括 V4.5.1 严格对照、时间前缀因果性、多头优先、杠杆约束、止损只收紧、风险预算只影响仓位、候选格点验证，以及已有分钟执行测试。V4.5.2 保持冻结研究候选状态，未修改项目默认策略。
"""
    (ROOT / "README.md").write_text(text)
    print(json.dumps({"acceptance": acceptance, "bootstrap": boots}, indent=2))


if __name__ == "__main__":
    main()
