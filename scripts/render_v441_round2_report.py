"""Build a complete round-2 report without any new parameter selection."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from btc_regime.v441_research import daily_equity, metrics, paired_block_bootstrap
from evaluate_v441 import read_equity
from evaluate_v441_round2 import validate_lock

ROOT = Path("reports/v4_4_1_round2")
OLD = Path("reports/v4_4_1")
NAMES = {"r110": "V4.4.1-R2", "r106": "R2：初始止损 2 ATR", "r024": "中速核心、原保护规则",
         "r000": "原速度核心、4 倍上限", "mix_r024_r091_25": "中速核心＋小仓位突破多空",
         "mix_r000_r091_25": "原速度核心＋小仓位突破多空", "V441": "V4.4.1-R1",
         "V4_1_2": "V4.1.2", "V4_1_3": "V4.1.3", "V4": "V4"}


def load(case, period="recent", stress="base"):
    old_period = {"recent": "post2024", "known_late": "holdout"}
    parent = ROOT / f"{case}__{period}__{stress}"
    if not parent.exists():
        parent = OLD / f"{case}__{old_period.get(period, period)}__{stress}"
    return json.loads((parent / "metrics.json").read_text()), read_equity(parent / "equity.csv")


def table(cases, period="recent", stress="base", annual=True):
    if annual:
        text = ["| 策略 | 累计净收益 | CAGR | 日收益夏普 | 最大回撤 | 完整交易周期 |",
                "|---|---:|---:|---:|---:|---:|"]
    else:
        text = ["| 策略 | 月度净收益 | 最大回撤 | 完整交易周期 |", "|---|---:|---:|---:|"]
    for case in cases:
        m, _ = load(case, period, stress)
        if annual:
            text.append(f"| {NAMES[case]} | {m['total_return']:.2%} | {m['cagr']:.2%} | {m['sharpe']:.3f} | {m['max_drawdown']:.2%} | {m['cycles']} |")
        else:
            text.append(f"| {NAMES[case]} | {m['total_return']:.2%} | {m['max_drawdown']:.2%} | {m['cycles']} |")
    return "\n".join(text)


def rolling():
    choices = json.loads((ROOT / "rolling_choices.json").read_text())
    summary, lines = {}, ["| 下一期评估（UTC，右端不含） | 仅按此前收益选中 | 组合净收益 | 组合夏普 | V4.1.3 净收益 | V4.1.3 夏普 |",
                          "|---|---|---:|---:|---:|---:|"]
    curves = {"selected": [], "V4_1_3": []}
    cycles = {"selected": [], "V4_1_3": []}
    value = {"selected": 1., "V4_1_3": 1.}
    for choice in choices:
        k, case = choice["fold"], choice["profile"]["id"]
        a, _ = load(case, f"rolling{k}")
        b, _ = load("V4_1_3", f"rolling{k}")
        lines.append(f"| {' → '.join(choice['period'])} | {case} | {a['total_return']:.2%} | {a['sharpe']:.3f} | {b['total_return']:.2%} | {b['sharpe']:.3f} |")
        for label, target in [("selected", case), ("V4_1_3", "V4_1_3")]:
            _, e = load(target, f"rolling{k}")
            e = e / e.iloc[0] * value[label]
            value[label] = float(e.iloc[-1])
            curves[label].append(e)
            cycles[label].append(pd.read_csv(ROOT / f"{target}__rolling{k}__base/trades.csv"))
    for label, series in curves.items():
        e = pd.concat(series).asfreq("h").ffill()  # 14-day boundary embargo stays in cash.
        e.to_csv(ROOT / f"rolling_{label}_equity.csv")
        summary[label] = metrics(e, pd.concat(cycles[label], ignore_index=True))
    return summary, "\n".join(lines)


def chart():
    colors = {"r110": "#1269ad", "V441": "#a0a9b4", "V4_1_2": "#db9e23", "V4_1_3": "#258878"}
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(2, 2, figsize=(14, 8), layout="constrained", gridspec_kw={"height_ratios": [2, 1]})
    for col, period in enumerate(["recent", "extension"]):
        for case, color in colors.items():
            _, e = load(case, period)
            d = daily_equity(e)
            ax[0, col].plot(d.index, d / e.iloc[0], color=color, label=NAMES[case], lw=2 if case == "r110" else 1.4)
            dd = e / e.cummax() - 1
            ax[1, col].plot(dd.resample("1D").min().index, dd.resample("1D").min() * 100, color=color, lw=1.3)
        for axis in ax[:, col]:
            axis.grid(alpha=.2)
            axis.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]) if period == "recent"
                                        else mdates.DayLocator(bymonthday=[1, 8, 15, 22]))
            axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m" if period == "recent" else "%m-%d"))
        ax[0, col].set_ylabel("Net equity / starting equity")
        ax[1, col].set_ylabel("Drawdown (%)")
        ax[0, col].legend(frameon=False)
        ax[0, col].set_title("Known development history: 2024-01 to 2026-07" if col == 0
                             else "Reserved for this round: Aug 2026 (31 days only)")
    fig.suptitle("V4.4.1-R2 | Historical improvement; robustness remains unproven", fontsize=16, weight="bold")
    fig.savefig(ROOT / "equity_drawdown.png", dpi=170)
    fig.savefig(ROOT / "equity_drawdown.svg")
    plt.close(fig)


def main():
    profile = validate_lock()
    # Reused baselines are valid only against the unchanged round-1 execution code.
    old_lock = json.loads((OLD / "final_selection_lock.json").read_text())
    for path, digest in old_lock["source_sha256"].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Round-1 baseline provenance changed: {path}")
    cases = {p.parent.name: json.loads(p.read_text()) for p in ROOT.glob("*/metrics.json")}
    for case in ["V441", "V4", "V4_1_2", "V4_1_3"]:
        for period in ["recent", "known_late"]:
            cases[f"{case}__{period}__base"] = load(case, period)[0]
    chosen = load(profile["id"])[0]
    boot = {b: paired_block_bootstrap(load(profile["id"])[1], load(b)[1])
            for b in ["V441", "V4_1_2", "V4_1_3"]}
    roll, roll_table = rolling()
    screen = json.loads((ROOT / "screen.json").read_text())
    minute = json.loads((ROOT / "minute_selection.json").read_text())
    # Descriptive weight sensitivity only; never changes the frozen choice.
    sensitivity = {}
    from research_v441_round2 import utility
    import numpy as np
    for old_weight in [.15, .4, .6]:
        scores = {r["profile"]["id"]: (old_weight * utility(r["legacy"]) + (1 - old_weight)
                  * np.mean([utility(f) for f in r["folds"]]) - .3 * np.std([f["sharpe"] for f in r["folds"]]))
                  for r in minute if r["eligible"]}
        sensitivity[str(old_weight)] = {"best": max(scores, key=scores.get), "scores": scores}
    report = {"version": "V4.4.1-R2", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "profile": profile, "lock": json.loads((ROOT / "final_selection_lock.json").read_text()),
              "cases": cases, "bootstrap": boot, "rolling": roll, "weight_sensitivity": sensitivity,
              "trial_count": len(screen), "extension": json.loads((ROOT / "extension_coverage.json").read_text()),
              "sharpe_definition": "UTC daily net equity returns, sqrt(365.25), zero risk-free rate",
              "drawdown_definition": "Hourly saved net equity, not intraminute worst equity",
              "status": "historical_improvement_robustness_unproven", "promote_to_default": False}
    (ROOT / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    pd.DataFrame([{**{k: v for k, v in m.items() if not isinstance(v, (dict, list))}, "label": label}
                  for label, m in cases.items()]).to_csv(ROOT / "summary.csv", index=False)
    ci = boot["V4_1_3"]["sharpe_difference_95pct"]
    folds = ["| 分段（UTC，右端不含） | R2 收益 | R2 夏普 | R2 最大回撤 |", "|---|---:|---:|---:|"]
    periods = json.loads((ROOT / "protocol.json").read_text())["recent_folds"]
    for dates, m in zip(periods, chosen["folds"]):
        folds.append(f"| {' → '.join(dates)} | {m['total_return']:.2%} | {m['sharpe']:.3f} | {m['max_drawdown']:.2%} |")
    artifact = f"""# V4.4.1-R2：中速识别与趋势恢复入场

**已取得已知历史上的收益、夏普改善；稳健升级尚未通过，不替换默认策略。**

2024-01-01 至 2026-07-31，冻结方案净收益 **{chosen['total_return']:.2%}**，CAGR **{chosen['cagr']:.2%}**，日收益夏普 **{chosen['sharpe']:.3f}**。相较 R1 的 78.27% / 0.875 明显改善，相较 V4.1.3 的 127.74% / 0.979 是小幅改善。成本及延迟压力下优势消失，逐期选参也未超过基准。完整保留 132 个参数配置试验、六个分钟候选及未通过的方案。

## 具体策略

1. **4h 中速核心**：EMA(20/80)，ADX(14) 24 进入 / 17 退出的滞回；保留原核心的 DI 方向、均线间距条件以及非趋势超跌反弹。只有原始核心目标为多头，小时入场才可能启动。没有强加日线方向过滤。
2. **新事件入场**：核心刚从空仓变为做多，或小时收盘重新站上 EMA(20)，或小时收盘突破此前 6 小时最高价。4h 特征等到完整收盘后才可见；小时收盘发信号，下一小时起执行。
3. **保护和恢复**：以已完成 4h ATR(20) 设置 3 ATR 初始止损；最高小时收盘价减 3 ATR 跟踪，止损只收紧。取消原 12 ATR 固定止盈和 V4.1.2 的专用快速下跌保护层；仍保留原始核心的风险减仓。分钟标记价触发保护后平仓；小时逻辑用已经发生的标记低价确认退出。退出后冷却 6 小时，且需要新事件才能再次入场；最长 72 小时，原始核心变为空仓也退出。不是同一个旧信号被止损后不断重开。
4. **仓位**：继承原核心 ATR 波动率目标 107.5%、趋势乘数 1.25、反弹乘数 0.65，以及波动冲击、资金费拥挤、下行波动和价格回撤风险层。下单目标上限 4 倍；本段实际观察峰值为 {chosen['execution_metrics']['max_leverage_observed']:.2f} 倍，权益变化会使盘中实际杠杆暂时高于目标。原核心 60 根 4h 常规调仓和风险变化即时减仓规则不变。
5. **默认关闭空头**：测试的谨慎空头没有形成可靠净增益。与主策略路由组合时仅接受新周期，单账户不叠加保证金；最终候选不包含此组合。

参数文件 `configs/v4_4_1_round2_params.json` 中 `target_vol=0.9`、`entry=15` 是统一候选结构留存的战术族字段，**本 continuation 候选不使用**；其实际目标波动率由 `core_params()` 的 1.075 给出。`hold_hours=72`、`stop_atr=3`、`speed=medium`、`protection=original`（3 ATR 跟踪）和 `max_leverage=4` 才是本族有效差异。配置不应直接传给旧版 CLI 的 `StrategyParams`。

## 数据权重与选择

旧数据 2020–2023 权重 **15%**；2024–2026-07 五个连续时间段合计 **85%**，每段 17%。按时间段平均，避免较长旧历史淹没新环境。效用 = 日收益夏普 + 0.5×年化对数增长 − 2×最大回撤绝对值；总分再扣近期各段夏普标准差的 0.3 倍。最近全段回撤不得超过 35%，旧段不得超过 55%，近期至少 30 个完整交易周期。

先注册 72 个核心、16 个回撤买入、8 个突破多空配置，再把入选核心和战术方案做 12 个固定小仓位路由组合；观察到旧周期止损锁定后，查看保留月之前追加注册 24 个恢复入场配置。共 **132 次配置试验（含经济行为可能相同的组合）**。小时低成本筛选后，六个候选统一在 2020–2023 和 2024–2026-07 做完整分钟验证，按同一评分冻结 `r110`，没有按 8 月结果改参数。

权重敏感性只作诊断：六个分钟候选中，旧数据权重 15% 选 {sensitivity['0.15']['best']}；40% 选 {sensitivity['0.4']['best']}；60% 选 {sensitivity['0.6']['best']}。它不能独立证明 ETF 引发收益结构变化。SEC 于 2024-01-10 批准现货比特币 ETP，见 [SEC 公告](https://www.sec.gov/newsroom/speeches-statements/gensler-statement-spot-bitcoin-011023)；将该时间点视为研究分界是一项假设，未使用 ETF 净流入或其他宏观因子来做因果识别。

**样本披露**：2026 年 7 月及以前已经在第一轮及其他研究中看过，本轮全部属于已知开发历史，不能重新宣称盲测。2026 年 8 月在本轮仅先检查覆盖和文件哈希，冻结后才计算策略收益；仓库其他研究可能已经看过，因此只是本轮保留月。没有使用不完整的 9 月。

## 同成本分钟回测

所有账户从 10,000 USDT 起步，计入 4 bps Taker、无返佣、基础滑点 1 bps、8 bps×sqrt(参与率) 冲击、实际资金费、0.001 BTC 取整、每分钟 2% 常规成交参与率及保证金检查。紧急保护退出沿用原引擎整笔成交加冲击近似，不是订单簿重放。历史保证金档位为模型假设。各评估窗口独立账户，指标和策略状态用此前历史预热；末端强制平仓并计费。

夏普统一使用 UTC **日收益**、sqrt(365.25)、零无风险利率；`execution_metrics.sharpe` 是引擎小时统计，不用于本报告排名。最大回撤来自每小时保存权益，不是分钟内最坏权益。交易数为从零仓位至平仓的完整周期。

### 2024-01-01 至 2026-07-31（已知开发历史）

{table(['r110', 'V441', 'V4_1_2', 'V4_1_3', 'V4'])}

R1 上限为 3 倍，R2 上限为 4 倍，R2 相比 R1 的改善不能全部归因于信号结构。与 6.5 倍上限的 V4.1.3 比较，R2 收益高 10.88 个百分点、夏普仅高 0.032，最大回撤反而多约 0.39 个百分点。

### 同为 4 倍上限的结构对照

{table(['r000', 'r024', 'r110', 'r106', 'mix_r024_r091_25'])}

原速度换为中速核心的增益较明显。恢复入场把完整周期从 100 提高到 130，夏普从约 0.987 提高到 1.012，但收益略低于中速原保护核心，不能称为收益全面支配。相对 V4.1.2 的 96 个周期增加约 35%；相对 V4.1.3 的 130 个周期没有增加。最终方案的持仓中位数约 47 小时，属于中低频交易。

短线回撤买入 16 个配置在扣费后全部亏损；额外 500 左右交易没有制造有效独立样本。中速核心加 25% 战术突破多空后，收益和夏普略降。减少风险保护、单纯缩紧止损或更快均线也未在加权评分中胜出。它们保留在 `screen.csv`，不隐藏失败结果。

### 分段检查（同一账户连续运行后的切片）

{chr(10).join(folds)}

2026 年 1–7 月仍亏损，尚未解决所有近期环境。以下较晚子段重新从现金开始，日期对应 R1 的旧留出，但它已参与本轮开发：

{table(['r110', 'V441', 'V4_1_2', 'V4_1_3'], 'known_late')}

### 冻结后开启：2026 年 8 月

{table(['r110', 'V441', 'V4_1_2', 'V4_1_3'], 'extension', annual=False)}

完整 44,640 个配对分钟。仅 31 天、R2 5 个交易周期，8 月 19–22 日单笔交易净赚约 8,800 USDT，超过全月净利润约 8,680 USDT；月度优势高度集中于一段上涨。不强调这一短窗口的年化夏普，也不将其外推为长期收益。新月份没有继续参与选参。原始成交价与标记价归档未改动；此前 2024 年后仍有 2 个缺失配对分钟，未插值。报告中 37 个新旧案例均未发生模型强平，这不代表不存在实际强平风险。

![权益与回撤](equity_drawdown.png)

## 时间顺序验证和压力检查

在四个边界，仅用该边界以前的收益在 120 个独立配置中选参（排除利用全开发期选出的路由）。下期前 14 天保持现金，超过各配置最长计划持仓 12 天；实际分钟回测从现金开始，扣除进入和末端退出成本。候选族的研究设计本身看过完整历史，因此这是**回顾性的顺序验证**，不是从未见过的数据实验。

{roll_table}

四段收益顺序相乘并将边界隔离期计为现金，选参组合净收益 **{roll['selected']['total_return']:.2%}**、夏普 **{roll['selected']['sharpe']:.3f}**；同窗口 V4.1.3 净收益 **{roll['V4_1_3']['total_return']:.2%}**、夏普 **{roll['V4_1_3']['sharpe']:.3f}**。不能用最后胜出的 r110 反填早期选择。这项验证没有证明选参流程稳定优于旧版。

费用压力：Taker 8 bps、基础滑点 3 bps、冲击系数 16 bps；整个 2024–2026-07 窗口重新成交：

{table(['r110', 'V4_1_3'], stress='double_cost')}

将目标与保护更新统一延迟 1 小时：

{table(['r110', 'V4_1_3'], stress='delay_1h')}

两类压力下 R2 都落后于 V4.1.3，说明基础条件下的小优势容易被执行成本侵蚀。延迟压力保留已经生效的止损，不等价于交易所完全断连。

14 天配对连续区块重抽样 2,000 次，R2 相对 V4.1.3 的夏普差 95% 区间 **[{ci[0]:.3f}, {ci[1]:.3f}]**，包含零。它是选参后的条件区间，未修正 132 次试验，不能作为显著性证明。反复尝试会增加回测过拟合风险，相关方法论见 [Bailey 等原始论文](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)。交易数量增加不能创造新的独立市场环境。

## 交付和复现

状态为 **历史改善、稳健性待证**。R2 保留为当前 V4.4.1 的改进候选；R1 的代码、配置和冻结记录完整保留。仓库处于 `main`，未替换默认配置，也未连接交易账户下单。

- `configs/v4_4_1_round2_params.json`：冻结参数；`src/btc_regime/v441_r2.py`：信号实现。
- `protocol.json`、`continuation_protocol.json`、`screen.json/csv`：全部候选与研究过程。
- `minute_selection.json`：六个候选的真实分钟评分；`final_selection_lock.json`：参数、代码、输入和候选哈希。
- `report.json`、`summary.csv`：结构化结果；每个案例目录有权益、填单、资金费、交易和强平记录。
- `rolling_choices.json` 和 `rolling_*_equity.csv`：真实逐期选择及现金隔离期权益。
- `tests/test_v441_r2.py`：各策略族前缀因果、仓位限制、止损单向收紧、标记价触发、冷却、新事件入场和路由。

```bash
# 冻结版本审计；要求已有 data/v441 原始研究缓存。
PYTHONPATH=src python3 scripts/prepare_v441_round2_extension.py
PYTHONPATH=src python3 scripts/evaluate_v441_round2.py audit
PYTHONPATH=src python3 scripts/evaluate_v441_round2.py rolling
PYTHONPATH=src python3 scripts/render_v441_round2_report.py
PYTHONPATH=src python3 -m pytest -q
```

绘图需要 Matplotlib。开发筛选入口 `scripts/research_v441_round2.py`、`--continuation` 及 `evaluate_v441_round2.py development` 在存在最终锁时拒绝覆盖；研究记录已输出，不需要解锁来复测。`screen_manifest.json` 是首批 108 次小时试验的历史快照，最终审计以 `final_selection_lock.json` 为准。下一轮应保留本轮结论，并将截至 2026-08 的数据全部视为已知历史。
"""
    (ROOT / "README.md").write_text(artifact)
    (ROOT / "acceptance.json").write_text(json.dumps({
        "status": report["status"], "promote_to_default": False, "selected": profile["id"],
        "development_return_and_sharpe_improved": True,
        "stress_dominance": False, "rolling_dominance": False,
        "unseen_market_regimes_sufficient": False, "parameter_trials": len(screen)}, indent=2) + "\n")
    chart()
    print("Wrote", ROOT / "README.md", "and report.json; rolling:", roll)


if __name__ == "__main__":
    main()
