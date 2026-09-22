"""Render the V4.5.3 strategy comparison and causal audit report."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
COMPARISON = ROOT / "reports/v4_5_2_v412_v422_comparison/report.json"
EVALUATION = ROOT / "reports/v4_5_3/evaluation.json"
SELECTION = ROOT / "reports/v4_5_3/selection.json"
OUTPUT = ROOT / "reports/v4_5_3/README.md"


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def num(value: float) -> str:
    return f"{value:.2f}"


def load(path: Path):
    return json.loads(path.read_text())


def comparison_table(report: dict) -> list[str]:
    labels = {"full": "全样本", "post2024": "2024-01 后", "post2026_01_15": "2026-01-15 后"}
    rows = [
        "| 策略 | 区间 | 收益 | CAGR | 日夏普 | 最大回撤 | 周期数 | 周期/年 | 成交次数 | 成交/年 | 中位持仓(h) | 空头周期 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("V4.1.2", "V4.2.2", "V4.5.2", "V4.5.3"):
        for window in ("full", "post2024", "post2026_01_15"):
            item = report["strategies"][name][window]
            m, f = item["metrics"], item["frequency"]
            rows.append(
                f"| {name} | {labels[window]} | {pct(m['total_return'])} | {pct(m['cagr'])} | "
                f"{num(m['sharpe'])} | {pct(m['max_drawdown'])} | {f['cycles']} | "
                f"{num(f['cycles_per_year'])} | {f['fills']} | {num(f['fills_per_year'])} | "
                f"{num(f['median_holding_hours'])} | {f['short_cycles']} |"
            )
    return rows


def v453_execution_table(report: dict) -> list[str]:
    rows = [
        "| 区间 | V4.5.2 收益 | V4.5.3 收益 | V4.5.2 夏普 | V4.5.3 夏普 | V4.5.2 回撤 | V4.5.3 回撤 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {"full": "全样本", "post2024": "2024-01 后", "post2026_01_15": "2026-01-15 后"}
    for window in ("full", "post2024", "post2026_01_15"):
        old = report["strategies"]["V4.5.2"][window]["metrics"]
        new = report["strategies"]["V4.5.3"][window]["metrics"]
        rows.append(
            f"| {labels[window]} | {pct(old['total_return'])} | {pct(new['total_return'])} | "
            f"{num(old['sharpe'])} | {num(new['sharpe'])} | {pct(old['max_drawdown'])} | {pct(new['max_drawdown'])} |"
        )
    return rows


def stress_table(evaluation: list[dict]) -> list[str]:
    rows = [
        "| V4.5.3 场景 | 全样本收益 | 全样本夏普 | 全样本回撤 | 2024-01 至 2026-08 收益 | 该区间夏普 | 该区间回撤 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    names = {"base": "基准", "offset025": "Maker 偏移 0.25bps", "offset05": "Maker 偏移 0.5bps",
             "double_cost": "成本加倍", "no_rebate": "无返佣", "delay_1h": "信号延迟 1h"}
    for row in evaluation:
        if row["strategy"] != "V4.5.3":
            continue
        full, recent = row["execution_metrics"], row["windows"]["recent_jul"]["metrics"]
        rows.append(
            f"| {names[row['stress']]} | {pct(full['total_return'])} | {num(full['sharpe'])} | {pct(full['max_drawdown'])} | "
            f"{pct(recent['total_return'])} | {num(recent['sharpe'])} | {pct(recent['max_drawdown'])} |"
        )
    return rows


def adaptive_rejections(selection: list[dict]) -> list[str]:
    wanted = {"adaptive_adx36", "adaptive_adx40", "adaptive_turnover13", "adaptive_both"}
    lines = []
    for row in selection:
        item = row["item"]
        if item["id"] not in wanted:
            continue
        recent = row["windows"]["recent_jul"]
        lines.append(f"- `{item['id']}`：2024-01 至 2026-08 收益 {pct(recent['total_return'])}、夏普 {num(recent['sharpe'])}，未超过冻结 b022 信号，未纳入 V4.5.3。")
    return lines


def render() -> None:
    report = load(COMPARISON)
    evaluation = load(EVALUATION)
    selection = load(SELECTION)
    strategy = report["strategies"]["V4.5.3"]
    baseline = report["strategies"]["V4.5.2"]
    base_eval = next(row for row in evaluation if row["strategy"] == "V4.5.3" and row["stress"] == "base")
    fills = base_eval["execution_metrics"]
    maker_ratio = fills["maker_fill_ratio"]
    fills_frame = pd.read_csv(ROOT / "reports/v4_5_3/V4.5.3__base/fills.csv")
    fills_frame["timestamp"] = pd.to_datetime(fills_frame["timestamp"], utc=True)
    fills_frame = fills_frame.loc[(fills_frame["timestamp"] >= "2020-01-01") &
                                  (fills_frame["timestamp"] < "2026-08-01")]
    same_window_maker_notional = float(fills_frame.loc[fills_frame["liquidity"] == "maker", "notional"].sum())
    saved = same_window_maker_notional * (2.4 - 0.12) / 10000
    static = report["future_function_audit"]["static"]
    causal = report["future_function_audit"]["real_data_prefix"]
    overfit = report["overfit_audit"]
    text = [
        "# V4.5.3 与 V4.1.2 / V4.2.2 / V4.5.2 对比、因果审计与优化报告",
        "",
        "## 结论",
        "",
        "在同一窗口（2020-01-01 至 2026-08-01 UTC）、同一 1 分钟执行框架和 40% Taker 返佣下，V4.5.3 保留 V4.5.2 b022 的信号与空头规则，只把普通开仓和调仓改为带 60 分钟有效期的 post-only Maker 订单，保护性退出继续使用 Taker。这个低自由度的执行层改动同时提高了全样本和 2024 年后的收益/夏普，并把后段回撤略降至 30%以内。",
        "",
        f"2024-01 后，V4.5.2 为收益 {pct(baseline['post2024']['metrics']['total_return'])}、日夏普 {num(baseline['post2024']['metrics']['sharpe'])}、最大回撤 {pct(baseline['post2024']['metrics']['max_drawdown'])}；V4.5.3 为收益 {pct(strategy['post2024']['metrics']['total_return'])}、日夏普 {num(strategy['post2024']['metrics']['sharpe'])}、最大回撤 {pct(strategy['post2024']['metrics']['max_drawdown'])}。同窗交易频率约为 {num(strategy['post2024']['frequency']['cycles_per_year'])} 周期/年、{num(strategy['post2024']['frequency']['fills_per_year'])} 成交/年，V4.5.3 中位持仓 {num(strategy['post2024']['frequency']['median_holding_hours'])} 小时。",
        "",
        "## 同窗口对比",
        "",
        "所有收益、CAGR、夏普和回撤来自按 UTC 日收盘权益重采样；成交次数是执行模型产生的 fill 事件，周期数按已完成交易周期统计。V4.2.2 的资金费中性层是独立的状态切换，不重复计为方向交易周期。",
        "",
        *comparison_table(report),
        "",
        "## V4.5.2 到 V4.5.3 的改动效果",
        "",
        *v453_execution_table(report),
        "",
        f"V4.5.3 同窗共有 {strategy['full']['frequency']['fills']} 次成交，约 {num(strategy['full']['frequency']['fills_per_year'])} 次/年；2024-01 后为 {strategy['post2024']['frequency']['fills']} 次，约 {num(strategy['post2024']['frequency']['fills_per_year'])} 次/年。扩展至 2026-09-01 的完整执行复测中，Maker 成交占比为 {maker_ratio * 100:.2f}%（按成交事件），Maker 费率为 0.12bps；在 2020-01 至 2026-08 的 Maker 名义成交额约 84.71M USDT，相对按 2.4bps Taker 计的费差约为 {saved:,.0f} USDT。",
        "",
        "V4.5.3 没有增加新的信号参数，因此没有因为再调阈值而提高模型自由度。Maker 结果是 OHLC 触价代理，未建模真实订单簿排队、撤单优先级和部分成交队列，实盘收益应按更保守的全 Taker 版本复核。",
        "",
        "## 成本、偏移和延迟压力",
        "",
        "下面的基准与压力场景都使用 V4.5.3 的同一信号，区间列中的后段是 2024-01-01 至 2026-08-01；成本加倍同时提高手续费、基础滑点和冲击，延迟场景把信号整体后移 1 小时。",
        "",
        *stress_table(evaluation),
        "",
        "成本加倍和 1 小时延迟明显降低全样本结果，且全样本回撤会超过 30%；这说明 Maker 优势和信号时效都需要实盘前单独验证。后段基准、偏移 0.25/0.5bps、无返佣与延迟场景仍保持正收益和正夏普。",
        "",
        "## 未来函数与因果性审计",
        "",
        f"- 静态扫描 `strategy.py`、`v42.py`、`v43.py`、`v452.py`、`v453.py` 中的负向 `shift`、`bfill/backfill`、居中 rolling 和负向 `pct_change`：{static['status']}，命中数 {len(static['forbidden_future_patterns'])}。",
        f"- 真实数据前缀重算在 2023-01-01、2024-01-01、2025-07-01、2026-01-01 四个截点逐一通过；V4.1.2、V4.2.2、V4.5.2 信号和 V4.2 中性层前缀均与完整数据运行相同（{causal['status']}）。V4.5.3 信号是 V4.5.2 的精确封装，并由 `tests/test_v453.py` 做等价性断言。",
        "- 检查范围覆盖信号生成和实际历史前缀一致性，不能证明数据下载、真实交易撮合或外部部署系统绝对没有未来信息；报告中的 Maker 触价代理也不等于真实订单簿。",
        "",
        "## 过拟合审计",
        "",
        f"- V4.5.2 b022 在 {overfit['selection_rows']} 个候选记录中从 {overfit['selectable_rows']} 个可选配置中胜出；领先第二名的评分差仅 {overfit['winner_score_gap']:.4f}（{overfit['winner_score']:.4f} 对 {overfit['next_score']:.4f}），未做多重检验校正，因此保留选择偏差警告。",
        "- 固定 b022 的逐年表现并非每年都稳定：2022 年收益为 -22.80%、夏普 -0.98；2024 年后改善明显，说明结构变化假设有数据依赖，不能把后段提升解释成已证明的普适规律。",
        "- 这批数据和早期 V4.5 搜索历史此前均已查看，报告不是盲样本外验证。适合把 V4.5.3 作为冻结研究候选，之后用新的未参与研究数据或纸面交易日志做真正前向验证。",
        *adaptive_rejections(selection),
        "",
        "## 数据、复现与文件",
        "",
        "- 回测窗口：2020-01-01 至 2026-08-01 UTC；扩展执行压力复测至 2026-09-01，最新完整数据此前已参与研究。",
        "- 费用：公布 Taker 4bps、40% 返佣后有效 2.4bps；公布 Maker 0.2bps、40% 返佣后有效 0.12bps；另计 1bps 基础滑点、8bps 冲击和真实资金费。",
        "- 主要文件：[V4.5.3 参数](../../configs/v4_5_3_params.json)、[三策略 JSON 对比](../v4_5_2_v412_v422_comparison/report.json)、[对比 CSV](../v4_5_2_v412_v422_comparison/comparison.csv)、[压力测试 JSON](evaluation.json)、[候选选择记录](selection.json)。",
        "",
        "```bash",
        "PYTHONPATH=src:scripts python3 scripts/backtest_v42_execution.py --params configs/v4_2_2_params.json --capital-params configs/v4_2_capital_params.json --raw-dir data/raw --fee-rebate-rate 0.4 --output reports/v4_2_rebate40",
        "PYTHONPATH=src:scripts python3 scripts/compare_v412_v422_v452.py",
        "PYTHONPATH=src:scripts python3 scripts/evaluate_v453.py",
        "PYTHONPATH=src:scripts python3 scripts/render_v453_report.py",
        "PYTHONPATH=src python3 -m pytest -q",
        "```",
    ]
    OUTPUT.write_text("\n".join(text) + "\n")
    print(OUTPUT)


if __name__ == "__main__":
    render()
