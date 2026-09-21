"""Render the frozen V4.4.3 report and chart."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from btc_regime.v441_research import daily_equity, paired_block_bootstrap

ROOT = Path("reports/v4_4_3")


def m(path):
    return json.loads((ROOT / path / "metrics.json").read_text())


def eq(path):
    frame = pd.read_csv(ROOT / path / "equity.csv", index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame.iloc[:, 0]


def row(name, x):
    return f"| {name} | {x['total_return']:.2%} | {x['cagr']:.2%} | {x['sharpe']:.3f} | {x['max_drawdown']:.2%} | {x['cycles']} |"


def main():
    selected = json.loads((ROOT / "freeze.json").read_text())["selected"]
    r = m("r024__recent__minute")
    legacy = m("r024__legacy__minute")
    v442 = m("V442__recent__minute")
    v413 = m("V4_1_3__recent__minute")
    ext = {"V4.4.3": m("V443__extension__base"), "V4.4.2": m("V442__extension__base"),
           "V4.1.3": m("V4_1_3__extension__base")}
    late = {"V4.4.3": m("V443__known_late__base"), "V4.4.2": m("V442__known_late__base"),
            "V4.1.3": m("V4_1_3__known_late__base")}
    stress = {"V4.4.3": m("V443__recent__double_cost"), "V4.4.2": m("V442__recent__double_cost"),
              "V4.1.3": m("V4_1_3__recent__double_cost")}
    boot442 = paired_block_bootstrap(eq("r024__recent__minute"), eq("V442__recent__minute"))
    boot413 = paired_block_bootstrap(eq("r024__recent__minute"), eq("V4_1_3__recent__minute"))
    report = json.loads((ROOT / "report.json").read_text())
    report.update({"selected_profile": selected, "development": {"V4.4.3": r, "legacy": legacy,
                    "V4.4.2": v442, "V4.1.3": v413}, "bootstrap_vs_V4.4.2": boot442,
                   "bootstrap_vs_V4.1.3": boot413, "extension_metrics": ext,
                   "known_late_metrics": late, "double_cost_metrics": stress})
    (ROOT / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    colors = {"V4.4.3": "#1269ad", "V4.4.2": "#db9e23", "V4.1.3": "#258878"}
    locations = {"V4.4.3": "r024__recent__minute", "V4.4.2": "V442__recent__minute",
                 "V4.1.3": "V4_1_3__recent__minute"}
    fig, ax = plt.subplots(2, 2, figsize=(14, 8), layout="constrained", gridspec_kw={"height_ratios": [2, 1]})
    for col, period in enumerate(["recent", "extension"]):
        for name, color in colors.items():
            path = locations[name] if period == "recent" else {"V4.4.3": "V443__extension__base",
                "V4.4.2": "V442__extension__base", "V4.1.3": "V4_1_3__extension__base"}[name]
            e = eq(path)
            d = daily_equity(e)
            ax[0, col].plot(d.index, d / e.iloc[0], color=color, label=name, lw=2 if name == "V4.4.3" else 1.5)
            dd = e / e.cummax() - 1
            ax[1, col].plot(dd.resample("1D").min().index, dd.resample("1D").min() * 100, color=color, lw=1.3)
        for a in ax[:, col]:
            a.grid(alpha=.2)
            a.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]) if period == "recent"
                                      else mdates.DayLocator(bymonthday=[1, 8, 15, 22]))
            a.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m" if period == "recent" else "%m-%d"))
        ax[0, col].set_title("2024-01 to 2026-07, known development data" if period == "recent"
                             else "August 2026, one-month extension")
        ax[0, col].set_ylabel("Net equity / initial equity")
        ax[1, col].set_ylabel("Drawdown (%)")
        ax[0, col].legend(frameon=False)
    fig.suptitle("V4.4.3 | Higher frequency with 40% taker-fee rebate", fontsize=16, weight="bold")
    fig.savefig(ROOT / "equity_drawdown.png", dpi=170)
    fig.savefig(ROOT / "equity_drawdown.svg")
    plt.close(fig)

    text = f"""# V4.4.3：返佣与适度提频优化

**V4.4.3 已冻结为研究候选；不自动替换默认策略。**

本轮先将原 V4.4.1-R2 正式更名为 **V4.4.2**，再固定采用 40% Taker 返佣：公布费率 4 bps、返佣 40%，回测中的有效费率为 **2.4 bps**。V4.4.3 在此成本假设下增加小时级趋势恢复、EMA 重夺和短周期突破入场，并测试 162 组止损、跟踪、持仓和入场组合。

2024-01-01 至 2026-07-31 的 1 分钟成交回测结果：

| 策略 | 累计净收益 | CAGR | 日收益夏普 | 最大回撤 | 完整周期 |
|---|---:|---:|---:|---:|---:|
{row('V4.4.3', r)}
{row('V4.4.2', v442)}
{row('V4.1.3', v413)}

V4.4.3 比返佣后的 V4.4.2 多约 **10.2 个百分点**净收益，夏普高 **0.040**，完整周期由 130 增至 145；最大回撤增加约 4.8 个百分点。与 V4.1.3 相比，净收益多约 25.7 个百分点，夏普高 0.085。

## 冻结规则

- 4h EMA(20/80) 和 ADX(24/17) 作为趋势锚点；目标杠杆上限 4 倍，风险层沿用 V4.4.2 的波动冲击、资金费拥挤、下行风险和回撤控制。
- 在主趋势仍为多头时，小时收盘可以触发三类新事件：核心刚重新变为多头、价格重新站上 EMA(20)、或突破此前 6 小时高点。
- 初始止损为 **1.5 ATR(4h)**，跟踪止损为 **3 ATR(4h)**，最长持仓 72 小时，保护退出后冷却 3 小时。止损仅向盈利方向收紧，必须出现新事件才可重新入场。
- 只做多。下跌趋势空仓；此前测试的谨慎空头没有在统一成本下提供稳定增益。
- 1 分钟成交模型使用 4 bps Taker、40% 返佣、1 bps 基础滑点、8 bps×sqrt(参与率) 冲击、真实资金费、0.001 BTC 取整和 2%/分钟参与率上限。返佣不适用于滑点、资金费或强平费用。

配置见 [`configs/v4_4_3_params.json`](../../configs/v4_4_3_params.json)，V4.4.2 配置见 [`configs/v4_4_2_params.json`](../../configs/v4_4_2_params.json)。

## 频率和防过拟合

V4.4.3 注册了 162 组配置：中速/快速 EMA、1.5/2/3 ATR 初始止损、1.5/2.5/3 ATR 跟踪止损、24/48/72 小时最长持仓、三种小时入场模式。旧数据权重 15%，2024 年后五个时间段合计 85%；近期最大回撤不超过 35%，旧段不超过 55%，近期至少 30 个周期。代理筛选后取 8 个候选做完整分钟复测，再冻结 `r024`。

交易频率从 V4.4.2 的 130 个完整周期提高到 145 个，增幅约 11.5%。没有采用 24 小时持仓的最高频配置，因为它的交易次数虽接近 300 次，分钟夏普和收益均较低。提频没有被当成独立样本数量；所有候选仍共享 BTC 的相同市场环境。

## 结果边界

2026 年 8 月在冻结之后才开启评估，完整配对分钟 44,640 个，但 V4.4.3 仅有 6 个周期：

| 策略 | 8 月收益 | 夏普 | 最大回撤 | 周期 |
|---|---:|---:|---:|---:|
| V4.4.3 | {ext['V4.4.3']['total_return']:.2%} | {ext['V4.4.3']['sharpe']:.3f} | {ext['V4.4.3']['max_drawdown']:.2%} | {ext['V4.4.3']['cycles']} |
| V4.4.2 | {ext['V4.4.2']['total_return']:.2%} | {ext['V4.4.2']['sharpe']:.3f} | {ext['V4.4.2']['max_drawdown']:.2%} | {ext['V4.4.2']['cycles']} |
| V4.1.3 | {ext['V4.1.3']['total_return']:.2%} | {ext['V4.1.3']['sharpe']:.3f} | {ext['V4.1.3']['max_drawdown']:.2%} | {ext['V4.1.3']['cycles']} |

8 月 V4.4.3 落后于 V4.4.2；样本太短，不据此调参或宣称长期结论。2025-07-15 至 2026-07-31 的已知后段，V4.4.3 收益 {late['V4.4.3']['total_return']:.2%}、夏普 {late['V4.4.3']['sharpe']:.3f}，V4.4.2 为 {late['V4.4.2']['total_return']:.2%} / {late['V4.4.2']['sharpe']:.3f}。

将 Taker、滑点和冲击全部加倍后，2024-01 至 2026-07 的结果为：V4.4.3 {stress['V4.4.3']['total_return']:.2%} / {stress['V4.4.3']['sharpe']:.3f}，V4.4.2 {stress['V4.4.2']['total_return']:.2%} / {stress['V4.4.2']['sharpe']:.3f}，V4.1.3 {stress['V4.1.3']['total_return']:.2%} / {stress['V4.1.3']['sharpe']:.3f}。V4.4.3仍领先，但优势缩小。

14 天配对区块 bootstrap（2,000 次）中，V4.4.3 相对 V4.4.2 的夏普差 95% 区间为 [{boot442['sharpe_difference_95pct'][0]:.3f}, {boot442['sharpe_difference_95pct'][1]:.3f}]；相对 V4.1.3 为 [{boot413['sharpe_difference_95pct'][0]:.3f}, {boot413['sharpe_difference_95pct'][1]:.3f}]。区间包含零，且未对 162 次试验做多重检验校正。

![净值与回撤](equity_drawdown.png)

**状态：历史样本在返佣假设下有改善，稳健性仍待未来数据确认。** 截至 2026-08 的数据均应视为已知；该策略没有连接交易账户，也没有执行实盘下单。若实际返佣不是稳定的 40%，应将有效费率改回账户真实费率后重新评估。

复现：

```bash
PYTHONPATH=src:scripts python3 scripts/research_v443.py screen --workers 3
PYTHONPATH=src:scripts python3 scripts/research_v443.py minute --workers 3
PYTHONPATH=src:scripts python3 scripts/research_v443.py freeze
PYTHONPATH=src:scripts python3 scripts/evaluate_v443.py
PYTHONPATH=src:scripts python3 scripts/render_v443_report.py
PYTHONPATH=src python3 -m pytest -q
```
"""
    (ROOT / "README.md").write_text(text)
    (ROOT / "acceptance.json").write_text(json.dumps({"version": "V4.4.3", "status": "frozen_candidate",
        "promote_to_default": False, "selected": selected["id"], "rebate_fraction": .4,
        "post2024_return": r["total_return"], "post2024_sharpe": r["sharpe"],
        "extension_cycles": ext["V4.4.3"]["cycles"], "robustness_unproven": True}, indent=2) + "\n")


if __name__ == "__main__":
    main()
