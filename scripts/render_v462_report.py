"""Render final V4.6.2 evidence without selecting or replaying more candidates."""
from __future__ import annotations

import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from research_v462 import OUTPUT, ROOT, clean, complete_months, digest, dump, metrics, read_result


def pct(value):
    return f'{value * 100:.2f}%'


def table(frame, columns, percent=()):
    lines = ['| ' + ' | '.join(label for _, label in columns) + ' |',
             '|' + '|'.join('---' for _ in columns) + '|']
    for _, row in frame.iterrows():
        cells = []
        for key, _ in columns:
            value = row[key]
            if key in percent:
                value = pct(value)
            elif isinstance(value, (float, np.floating)):
                value = f'{value:.3f}'
            cells.append(str(value))
        lines.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join(lines)


def main():
    report = json.loads((OUTPUT / 'report.json').read_text())
    screen = pd.read_csv(OUTPUT / 'candidate_screen.csv')
    stress = pd.read_csv(OUTPUT / 'execution_stress.csv')
    neighbors = pd.read_csv(OUTPUT / 'parameter_neighbors.csv')
    baseline = read_result(OUTPUT / 'full', 'control_taker')
    maker = read_result(OUTPUT / 'full', 'control_maker')
    selective = read_result(OUTPUT / 'exploratory', 'taker_entry_maker_add')
    models = {'V4.6.1': baseline, 'V4.6.2 Maker': maker, 'Selective Maker (exploratory)': selective}
    frame = pd.DataFrame([{'strategy': name, **metrics(result)} for name, result in models.items()])
    frame.to_csv(OUTPUT / 'final_comparison.csv', index=False)
    annual = pd.read_csv(OUTPUT / 'annual_comparison.csv')
    comparison = pd.read_csv(OUTPUT / 'comparison.csv')
    month = pd.concat({name: complete_months(result.equity) for name, result in models.items()}, axis=1)
    colors = {'V4.6.1': '#263854', 'V4.6.2 Maker': '#008f95', 'Selective Maker (exploratory)': '#df8b32'}
    fig, axes = plt.subplots(3, 1, figsize=(13, 11), constrained_layout=True)
    for name, result in models.items():
        daily = result.equity.resample('1D').last()
        axes[0].plot(daily.index, daily / result.equity.iloc[0], label=name, color=colors[name], lw=1.6)
        dd = result.equity / result.equity.cummax() - 1
        axes[1].plot(dd.resample('1D').min().index, dd.resample('1D').min() * 100, color=colors[name], lw=1.1)
    axes[0].set_yscale('log')
    axes[0].set_ylabel('Equity multiple (log)')
    axes[0].legend(loc='upper left', frameon=False)
    axes[0].set_title('V4.6.2 execution research: cheaper fills did not improve net performance', loc='left', fontsize=14)
    axes[1].axhline(-20, color='#b14444', ls='--', lw=1, label='-20% reference')
    axes[1].set_ylabel('Drawdown (%)')
    axes[1].legend(loc='lower left', frameon=False)
    x = np.arange(len(month))
    axes[2].bar(x-.2, month['V4.6.1']*100, width=.4, color=colors['V4.6.1'], label='V4.6.1')
    axes[2].bar(x+.2, month['V4.6.2 Maker']*100, width=.4, color=colors['V4.6.2 Maker'], label='V4.6.2 Maker')
    axes[2].set_xticks(x[::6], month.index.strftime('%Y-%m')[::6], rotation=45, ha='right')
    axes[2].axhline(0, color='#666666', lw=.7)
    axes[2].set_ylabel('Complete-month return (%)')
    axes[2].legend(loc='upper right', frameon=False)
    for ax in axes:
        ax.grid(alpha=.2, axis='y')
        ax.spines[['top','right']].set_visible(False)
    fig.savefig(OUTPUT / 'comparison.png', dpi=150)
    plt.close(fig)

    main_cols = [('strategy','方案'), ('cagr','年化收益'), ('daily_sharpe','日收益夏普'),
                 ('max_drawdown','最大回撤'), ('monthly_mean','平均月收益'), ('monthly_std','月收益标准差'),
                 ('positive_month_fraction','正收益月比例'), ('cycles_per_year','完整交易/年'),
                 ('maker_notional_fraction','Maker成交额占比'), ('effective_fee_bps','加权净费率bps')]
    percentages = ['cagr','max_drawdown','monthly_mean','monthly_std','positive_month_fraction','maker_notional_fraction']
    b, m = metrics(baseline), metrics(maker)
    cooldown = screen.loc[screen.candidate.eq('cooldown1_risk85')].iloc[0]
    hold48 = screen.loc[screen.candidate.eq('hold48_risk85')].iloc[0]
    dev_base = screen.loc[screen.candidate.eq('control_taker')].iloc[0]
    fee_reduction = 1 - m['effective_fee_bps']/b['effective_fee_bps']
    screen_cols = [('candidate','候选'), ('development_cagr','年化收益'), ('development_daily_sharpe','日收益夏普'),
                   ('development_max_drawdown','最大回撤'), ('development_positive_month_fraction','正收益月比例'),
                   ('development_cycles','完整交易数'), ('eligible','通过全部条件')]
    text = f'''# V4.6.2：点位、Maker 与频率优化研究（未通过升级验收）

截至 2026-10-20。使用已有 Bitget BTCUSDT 5 分钟缓存：2020-01-01 00:00 至 2026-10-11 08:00 UTC。

**结论：没有找到同时提高收益、夏普、正收益月份比例且最大回撤约 20% 的可靠升级。保留 V4.6.1；V4.6.2 仅作为研究版本，不替换默认策略。**

先测试 8 个固定候选（含原版对照），锁定失败结果后完成压力测试；随后追加 1 个公开标记为“看过结果后提出”的执行假设。总计 9 个主方案、6 个压力情景（其中资金费为路径敏感性）、4 个邻域诊断。没有通过不断扩展网格寻找达标参数。

## 全样本对比

{table(frame, main_cols, percentages)}

原版正收益月份为 {b['positive_months']}/{b['complete_months']}，Maker 候选为 {m['positive_months']}/{m['complete_months']}；两者都有一个零收益月份。最差月原版 {pct(b['worst_month'])}，Maker {pct(m['worst_month'])}。最长连续亏损均为 3 个月。
Maker 占总成交额 {pct(m['maker_notional_fraction'])}，加权净费率下降 {pct(fee_reduction)}，但年化收益降低 {(b['cagr']-m['cagr'])*100:.2f} 个百分点，夏普下降 {b['daily_sharpe']-m['daily_sharpe']:.3f}。省费未覆盖等待成交的机会成本。手续费总额随账户增长和成交额一起变化，不能直接把两账户总费用差认作纯节省。

![权益、回撤与完整月收益](comparison.png)

## 本轮实现

- V4.6.1 因子、0.90 暴露和多空规则作为控制。新增 V4.6.2 参数封装，支持调整多头突破长度、冷却、持有期、跟踪止损和回踩条件。
- Maker 买单固定在提交时开盘价下方 1 bps，卖单相反；挂单价格与目标数量不随下一根 K 线重新计算。至少等待一根 5 分钟 K 线，价格还需穿过限价 1 bps 才认定成交。
- Maker 最多占 K 线成交额的 0.5%（原有 2% 容量上限乘 25%）；允许部分成交。15 分钟未完成，剩余转 Taker。减仓、反向、保护性退出和期末平仓使用 Taker。
- 追加探索：首次建仓整条指令使用 Taker，仅已有同方向头寸的加仓使用 Maker。结果仍弱于原版，未采用。
- 修复无成交量时 Maker 超时回退被旧分支丢弃的边界问题。原版 Taker 权益与成交未改变；Maker 结果有小幅变化，因此按完全相同参数重跑候选、压力和邻域。修复前证据存入 pre_execution_fix/，不与新结果混用。

## 手续费与返佣

沿用项目费率假设：Maker 2 bps（0.02%）、Taker 6 bps（0.06%），返佣 60%，净费率分别 **0.8 bps / 2.4 bps（0.008% / 0.024%）**。所有成交都计成本；返佣按当次手续费直接抵扣，未模拟到账延迟。这是账户模型输入，不代表已核实当前账户等级或返佣合同。

## 固定候选：2020–2025 开发样本

{table(screen, screen_cols, ['development_cagr','development_max_drawdown','development_positive_month_fraction'])}

两个子段为 2020–2023 与 2024–2025，连续账户在边界切片；2025 年末开发回放有期末平仓，完整回放继续持仓，因此边界收益可能略有差别。选择要求两段盈利，开发 CAGR≥50%，日夏普与正月比例不低于原版，回撤≤22%，交易数为原版的 1–1.6 倍。22% 是本轮对“约 20%”的研究容差，**不是 20% 硬上限**。

全部候选至少一项不达标。按原规则锁定 control_maker 仅用于后续失败诊断，不是选出了获胜策略。
更短冷却把交易数由 {int(dev_base['development_cycles'])} 提高至 {int(cooldown['development_cycles'])}，但年化降至 {pct(cooldown['development_cagr'])}、回撤为 {pct(cooldown['development_max_drawdown'])}；48 小时持有上限把交易数提高至 {int(hold48['development_cycles'])}，但年化降至 {pct(hold48['development_cagr'])}。成交笔数因拆单增加也不等于新的独立信号增加。

## 分段与 2026 诊断

{table(comparison, [('strategy','方案'), ('period','区间'), ('cagr','年化收益'), ('daily_sharpe','日收益夏普'), ('max_drawdown','回撤'), ('positive_month_fraction','正月比例')], ['cagr','max_drawdown','positive_month_fraction'])}

2026 不是从未看过的留出数据：本项目此前已有研究使用这些历史。它仅为按时间顺序分段的诊断，不能证明真实样本外有效。追加的选择性 Maker 假设在看过上述结果后提出，也不得包装成预注册或盲测。

## 压力与邻域

{table(stress, [('scenario','场景'), ('cagr','年化收益'), ('daily_sharpe','日收益夏普'), ('max_drawdown','回撤'), ('positive_month_fraction','正月比例')], ['cagr','max_drawdown','positive_month_fraction'])}

资金费路径敏感性仅在真实资金费缺失阶段，对每个 8 小时结算点前实际头寸按绝对名义金额收取 1 bp，不区分多空。使用冻结成交路径和权益比例复合扣减，不重新模拟仓位反馈，**不是补齐的真实资金费，也不是完整微观回放**。其它压力情景均重新回放。取消返佣、滑点翻倍、增加一小时延迟时均不能稳健保持年化 50%。

{table(neighbors, [('neighbor','邻域'), ('cagr','年化收益'), ('daily_sharpe','日收益夏普'), ('max_drawdown','回撤'), ('positive_month_fraction','正月比例')], ['cagr','max_drawdown','positive_month_fraction'])}

暴露 0.85/0.95 与报价 0.5/2 bps 只作敏感性，不据此重新选参。增加杠杆能提高绝对收益，但这些结果没有显示夏普或正月比例改善。

## 统计口径修正

- 本轮日收益夏普：UTC 午夜权益到次日午夜的收益、无风险利率设为 0、按 √365.25 年化。旧报告部分展示的是小时收益夏普，不能直接混比。
- 完整月收益由精确月初权益到下一月月初计算，包含此前遗漏的 2020 年 1 月，排除未完成的 2026 年 10 月，共 81 个月。旧版月度 resample 将边界错移，故原版正月比例现为 61.73%，不是旧报告的 58.75%。原版 CAGR 保持 57.41%，交易规则未变。
- 最大回撤改用 5 分钟收盘权益，原版从小时统计的约 21.20% 改为 21.62%。仍可能漏掉 K 线内部的更深回撤。
- 月度风险缩放依赖 BTC 当月首根已完成小时收盘价以来的价格变化，**不是账户月内盈亏止损或不可逆锁盈**。
- 年化 50% 对应复合月收益约 3.44%，每月复合 4% 对应年化约 60.10%；算术平均月收益 4% 与这两者也不同。本报告分别列明。

## 适用边界与下一步

1. 现有数据是 5 分钟 OHLC，没有逐笔成交、盘口队列和真实 post-only 拒单。至少等待 5 分钟是保守代理，不能代表秒级 Maker 执行的真实收益。应先采集订单生命周期和真实成交再校准，不能把同根 K 线必成交当作优化。
2. 缓存真实资金费从 2026-06-27 起；此前在基准中按零处理是数据缺失。标记价格来自成交价代理；维持保证金阶梯继承 Binance 假设，尚未验证 Bitget 历史阶梯。零模拟强平不等于实盘不会强平。
3. 本轮测试的可执行改动都未同时改善三个目标，月收益波动仍约 10.6%–10.8%。目前不能称为“每月稳定盈利”，也不是秒级高频策略；原版中位持仓约 24 小时。
4. 暂保留 V4.6.1，归档 V4.6.2 失败候选与完整明细。更有价值的下一轮是先补齐执行/资金费数据并固定前向观察窗，之后再讨论更高频或新因子；不继续在同一历史上扩大搜索。

## 文件与复现

- 配置：../../configs/v4_6_2_params.json（status=not_accepted_research_only，未替换默认策略）
- 固定协议：PROTOCOL.md；追加探索声明：EXPLORATORY_ADDENDUM.md；原始选择锁：selection_lock.json
- 候选与结果：candidate_screen.csv、final_comparison.csv、monthly_comparison.csv、annual_comparison.csv、execution_stress.csv、parameter_neighbors.csv
- 成交与权益：v462_fills.csv、v462_trades.csv、v462_equity.csv；追加探索位于 exploratory/
- 实现：../../src/btc_regime/v462.py、../../src/btc_regime/micro_backtest.py
- 命令：PYTHONPATH=src python3 scripts/research_v462.py --stage screen / diagnostic / report；追加探索：scripts/research_v462_selective.py；报告：scripts/render_v462_report.py。
- screen 在 selection_lock.json 已存在时拒绝覆盖；重新研究应使用新的输出目录，不覆盖已冻结证据。

验证结果见 verification/final_checks.json；数据、协议、初始代码哈希见 manifest.json，最终代码哈希见 verification/final_checks.json。
'''
    (OUTPUT / 'README.md').write_text(text)
    report['exploratory'] = json.loads((OUTPUT / 'exploratory' / 'conclusion.json').read_text())
    report['research_summary'] = {'unique_primary_configurations': 9, 'frozen_screen_count': 8,
                                  'post_screen_exploratory_count': 1, 'stress_count': 6, 'neighbor_count': 4,
                                  'promoted': False, 'recommended_reference': 'V4.6.1',
                                  'fee_rate_reduction_fraction': fee_reduction}
    dump(OUTPUT / 'report.json', report)
    print('Rendered V4.6.2 report and comparison.png; status remains not accepted.')


if __name__ == '__main__':
    main()
