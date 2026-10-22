"""Render the paired 40%/60% rebate sensitivity report."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/v4_rebate60/report.json"
OUT = ROOT / "reports/v4_rebate60/README.md"


def pct(x):
    return f"{x * 100:.2f}%"


def n(x):
    return f"{x:.3f}"


def main():
    payload = json.loads(REPORT.read_text())
    rows = payload["cases"]
    by = {(r["strategy"], r["rebate"]): r for r in rows}
    labels = {"full": "全样本", "post2024": "2024-01 后", "later": "2026-01-15 后"}
    names = ["V4.1.2", "V4.2.2", "V4.5.2", "V4.5.3", "V4.5.4"]
    text = [
        "# 交易手续费返佣 60% 敏感性报告",
        "",
        "## 口径",
        "",
        "在相同参数、信号、行情、资金费、滑点和成交量限制下，分别重跑 40% 与 60% 返佣。公布 Taker 4bps / Maker 0.2bps，因此有效费率分别为：40% 返佣时 2.4 / 0.12bps，60% 返佣时 1.6 / 0.08bps。返佣只作用于交易手续费，不作用于资金费、滑点、强平费；中性层的现货/永续切换费用按同一返佣比例调整。",
        "",
        "回测窗口为 2020-01-01 至 2026-08-01 UTC，方向权益按实际执行时间戳记录。V4.2.2 和 V4.5.4 的中性结算收益只在结算之后的下一条权益观测入账，资本分配再滞后一条观测，避免把资金费提前记入账户。",
        "",
        "## 主要结果",
        "",
        "| 策略 | 返佣 | 区间 | 收益 | CAGR | 日夏普 | 最大回撤 | 周期/年 | 成交/年 | 空头周期 |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in names:
        for rebate in (.4, .6):
            r = by[(name, rebate)]
            for window in ("full", "post2024", "later"):
                m = r["windows"][window]
                text.append(f"| {name} | {rebate:.0%} | {labels[window]} | {pct(m['total_return'])} | {pct(m['cagr'])} | {n(m['sharpe'])} | {pct(m['max_drawdown'])} | {n(m['cycles_per_year'])} | {n(m['fills_per_year'])} | {m['short_cycles']} |")
    text += ["", "## 60% 相对 40% 的变化", "", "| 策略 | 全样本收益变化 | 全样本夏普变化 | 后段收益变化 | 后段夏普变化 | 后段回撤变化 |", "|---|---:|---:|---:|---:|---:|"]
    for name in names:
        old = by[(name, .4)]
        new = by[(name, .6)]
        a, b = old["windows"], new["windows"]
        text.append(f"| {name} | {pct(b['full']['total_return'] - a['full']['total_return'])} | {n(b['full']['sharpe'] - a['full']['sharpe'])} | {pct(b['post2024']['total_return'] - a['post2024']['total_return'])} | {n(b['post2024']['sharpe'] - a['post2024']['sharpe'])} | {pct(b['post2024']['max_drawdown'] - a['post2024']['max_drawdown'])} |")
    text += [
        "",
        "60% 返佣下，V4.5.3 2024 年后收益由 394.85% 提升至 405.74%？", # replaced below from data
        "",
    ]
    # Replace the prose with values generated from the actual rows.
    v453_old, v453_new = by[("V4.5.3", .4)], by[("V4.5.3", .6)]
    v454_old, v454_new = by[("V4.5.4", .4)], by[("V4.5.4", .6)]
    text[-2] = (f"以 V4.5.3 为例，2024 年后收益由 {pct(v453_old['windows']['post2024']['total_return'])} "
                f"变为 {pct(v453_new['windows']['post2024']['total_return'])}，日夏普由 "
                f"{n(v453_old['windows']['post2024']['sharpe'])} 变为 {n(v453_new['windows']['post2024']['sharpe'])}；"
                f"V4.5.4 则由 {pct(v454_old['windows']['post2024']['total_return'])} 变为 "
                f"{pct(v454_new['windows']['post2024']['total_return'])}，夏普由 "
                f"{n(v454_old['windows']['post2024']['sharpe'])} 变为 {n(v454_new['windows']['post2024']['sharpe'])}。")
    text += [
        "手续费下降还会通过复利、仓位数量取整和保证金变化影响后续成交，因此这些值来自完整重跑，不是简单把历史手续费差额加到最终权益。",
        "",
        "## 交易频率与中性层",
        "",
        "返佣改变的是成交后的权益，不改变预先冻结的信号规则，因此周期频率总体接近；轻微差异来自权益变化触发的目标数量取整和执行路径。V4.2.2 与 V4.5.4 的中性层全样本资金费状态切换均为 26 次，2024 年后均为 5 次。V4.5.4 2024 年后的方向周期约 72.04 次/年，成交约 250 次/年。",
        "",
        "## 数据修正与限制",
        "",
        "此前 V4.5.4 报告的组合权益拼接曾把部分中性收益标在结算发生前；本报告按完成时间重新计算，因此 V4.5.4 的 40% 基准会与旧报告略有差异。这是时间戳修正，不是返佣效应。",
        "",
        f"分钟数据覆盖期望 {payload['protocol']['coverage']['expected_minutes']} 分钟，实际 {payload['protocol']['coverage']['observed_minutes']} 分钟，缺失 {payload['protocol']['coverage']['missing_minutes']} 分钟。V4.5.3/V4.5.4 Maker 成交是 OHLC 触价代理，不包含真实订单簿排队；中性层不模拟现货/永续基差 PnL、借币和完整切换成交。历史数据此前已参与研究，不能称为盲样本外。",
        "",
        "## 文件与复现",
        "",
        "- [完整 JSON 报告](report.json)",
        "- [指标对比 CSV](comparison.csv)",
        "- [逐年结果 CSV](yearly.csv)",
        "- [回测协议](protocol.json)",
        "",
        "```bash",
        "PYTHONPATH=src:scripts python3 scripts/evaluate_v4_rebate60.py",
        "PYTHONPATH=src:scripts python3 scripts/render_rebate60_report.py",
        "PYTHONPATH=src python3 -m pytest -q",
        "```"]
    OUT.write_text("\n".join(text) + "\n")
    print(OUT)


if __name__ == "__main__":
    main()
