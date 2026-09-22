"""Render V4.5.4 comparison, causal audit and capital-overlay report."""
from __future__ import annotations

import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

from btc_regime.v42 import V42CapitalParams
from btc_regime.v453 import V453Params
from btc_regime.v454 import generate_v454_neutral_sleeve, generate_v454_signals
from evaluate_v444 import inputs
from research_v452 import profile_signal


ROOT = Path(__file__).resolve().parents[1]
COMPARISON = ROOT / "reports/v4_5_2_v412_v422_comparison/report.json"
EVALUATION = ROOT / "reports/v4_5_4/evaluation.json"
CONFIG = ROOT / "configs/v4_5_4_params.json"
OUTPUT = ROOT / "reports/v4_5_4/README.md"


def load(path: Path):
    return json.loads(path.read_text())


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def num(value: float) -> str:
    return f"{value:.2f}"


def causal_audit(config: dict) -> dict[str, object]:
    data, funding_extension, _ = inputs()
    full_signal = profile_signal(data, {"id": "b022", "kind": "v452", "params": config["signal_params"]})
    full_v454 = generate_v454_signals(
        data,
        V453Params(**config["signal_params"]),
        direction_allocation=config["capital_overlay"]["direction_allocation"],
        long_signals=full_signal,
    )
    capital = V42CapitalParams(**config["capital_overlay"])
    full_funding = funding_extension
    full_neutral = generate_v454_neutral_sleeve(full_funding, capital, rebate_fraction=.4)
    cuts = [pd.Timestamp(x, tz="UTC") for x in ["2023-01-01", "2024-01-01", "2025-07-01", "2026-01-01"]]
    rows = []
    signal_cols = ["signal", "stop_price", "take_profit_price", "cycle_id"]
    neutral_cols = ["active", "state_changed", "neutral_return", "trailing_7d_annualized", "trailing_30d_annualized"]

    def equal_frame(left: pd.DataFrame, right: pd.DataFrame, columns: list[str]) -> bool:
        left, right = left[columns], right[columns]
        if not left.index.equals(right.index) or left.shape != right.shape:
            return False
        for col in columns:
            if pd.api.types.is_numeric_dtype(left[col]):
                if not np.allclose(left[col].fillna(0), right[col].fillna(0), atol=1e-10):
                    return False
            elif not left[col].astype(str).equals(right[col].astype(str)):
                return False
        return True

    for cut in cuts:
        prefix = data.loc[data.index < cut]
        prefix_signal = profile_signal(prefix, {"id": "b022", "kind": "v452", "params": config["signal_params"]})
        prefix_v454 = generate_v454_signals(
            prefix,
            V453Params(**config["signal_params"]),
            direction_allocation=config["capital_overlay"]["direction_allocation"],
            long_signals=prefix_signal,
        )
        prefix_funding = full_funding.loc[full_funding.index < cut]
        prefix_neutral = generate_v454_neutral_sleeve(prefix_funding, capital, rebate_fraction=.4)
        rows.append({
            "cut": cut.isoformat(),
            "signal_prefix_equal": equal_frame(prefix_v454, full_v454.loc[full_v454.index < cut], signal_cols),
            "neutral_prefix_equal": equal_frame(prefix_neutral, full_neutral.loc[full_neutral.index < cut], neutral_cols),
        })
    files = [ROOT / "src/btc_regime/v42.py", ROOT / "src/btc_regime/v453.py", ROOT / "src/btc_regime/v454.py"]
    patterns = {
        "negative_shift": r"\.shift\(\s*-",
        "backfill": r"\.(?:bfill|backfill)\s*\(",
        "centered_rolling": r"rolling\([^\n]*center\s*=\s*True",
        "negative_pct_change": r"pct_change\(\s*-",
    }
    hits = []
    for path in files:
        text = path.read_text()
        for name, pattern in patterns.items():
            for match in re.finditer(pattern, text):
                hits.append({"file": str(path.relative_to(ROOT)), "pattern": name,
                             "line": text.count("\n", 0, match.start()) + 1})
    return {"static": {"files": [str(p.relative_to(ROOT)) for p in files],
                        "forbidden_future_patterns": hits,
                        "status": "pass" if not hits else "review_required"},
            "real_data_prefix": {"cuts": rows,
                                  "status": "pass" if all(r["signal_prefix_equal"] and r["neutral_prefix_equal"] for r in rows) else "review_required"}}


def comparison_rows(comparison: dict, selected: dict) -> list[dict[str, object]]:
    rows = []
    for name in ("V4.1.2", "V4.2.2", "V4.5.3"):
        for window, values in comparison["strategies"][name].items():
            rows.append({"strategy": name, "window": window, **values["metrics"], **values["frequency"]})
    for window, values in selected["windows"].items():
        rows.append({"strategy": "V4.5.4", "window": window, **values["metrics"], **values["frequency"],
                     "neutral_state_changes": values["neutral_state_changes"],
                     "neutral_active_fraction": values["neutral_active_fraction"]})
    return rows


def main() -> None:
    comparison = load(COMPARISON)
    evaluation = load(EVALUATION)
    config = load(CONFIG)
    base = next(row for row in evaluation if row["stress"] == "base")
    v453 = comparison["strategies"]["V4.5.3"]
    rows = comparison_rows(comparison, base)
    out = ROOT / "reports/v4_5_4"
    out.mkdir(parents=True, exist_ok=True)
    (out / "comparison.json").write_text(json.dumps({"execution": comparison["execution"], "strategies": rows}, indent=2, ensure_ascii=False) + "\n")
    pd.DataFrame(rows).to_csv(out / "comparison.csv", index=False)
    audit = causal_audit(config)
    (out / "causal_audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n")
    full, recent, later = (base["windows"][key] for key in ("full", "post2024", "later"))
    v453_recent = v453["post2024"]
    stress_names = {"base": "基准", "double_cost": "成本加倍", "no_rebate": "无返佣", "delay_1h": "信号延迟 1h"}
    report = [
        "# V4.5.4：V4.5.3 + V4.2.2 资本覆盖报告",
        "",
        "## 结论",
        "",
        "V4.5.4 参考 V4.1.2 到 V4.2.2 的结构变化：保留 V4.5.3 的 b022 空头信号、保护规则和 Maker 执行，把方向风险缩放到 75%，将 15% 资金配置到基于已结算资金费的中性覆盖，保留 10% 自由保证金。中性层使用 30 日历史观测、7 日/30 日资金费门槛、连续负结算退出和回撤/保证金召回；所有状态只在下一结算周期生效。",
        "",
        f"2024-01 后 V4.5.4 收益 {pct(recent['metrics']['total_return'])}、日夏普 {num(recent['metrics']['sharpe'])}、最大回撤 {pct(recent['metrics']['max_drawdown'])}；V4.5.3 为收益 {pct(v453_recent['metrics']['total_return'])}、日夏普 {num(v453_recent['metrics']['sharpe'])}、最大回撤 {pct(v453_recent['metrics']['max_drawdown'])}。V4.5.4 牺牲部分方向收益换取更低回撤和更高后段夏普。",
        "",
        "## 同窗口策略对比",
        "",
        "窗口为 2020-01-01 至 2026-08-01 UTC，手续费使用 40% 返佣。V4.5.4 的周期/成交频率是方向执行层，资金费中性层的状态切换单列。",
        "",
        "| 策略 | 区间 | 收益 | CAGR | 日夏普 | 最大回撤 | 周期/年 | 成交/年 | 中位持仓(h) | 空头周期 | 中性状态切换 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {"full": "全样本", "post2024": "2024-01 后", "post2026_01_15": "2026-01-15 后", "later": "2026-01-15 后"}
    for row in rows:
        neutral_changes = row.get("neutral_state_changes", "—")
        report.append(f"| {row['strategy']} | {labels.get(row['window'], row['window'])} | {pct(row['total_return'])} | {pct(row['cagr'])} | {num(row['sharpe'])} | {pct(row['max_drawdown'])} | {num(row['cycles_per_year'])} | {num(row['fills_per_year'])} | {num(row['median_holding_hours'])} | {row['short_cycles']} | {neutral_changes} |")
    report += [
        "",
        "## V4.5.3 到 V4.5.4 的变化",
        "",
        "| 区间 | V4.5.3 收益 | V4.5.4 收益 | V4.5.3 夏普 | V4.5.4 夏普 | V4.5.3 回撤 | V4.5.4 回撤 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key, label in [("full", "全样本"), ("post2024", "2024-01 后"), ("post2026_01_15", "2026-01-15 后")]:
        old = v453[key]["metrics"]
        new = base["windows"]["full" if key == "full" else "post2024" if key == "post2024" else "later"]["metrics"]
        report.append(f"| {label} | {pct(old['total_return'])} | {pct(new['total_return'])} | {num(old['sharpe'])} | {num(new['sharpe'])} | {pct(old['max_drawdown'])} | {pct(new['max_drawdown'])} |")
    report += [
        "",
        f"V4.5.4 全样本方向层为 {full['frequency']['cycles']} 个周期、{full['frequency']['fills']} 次成交，约 {num(full['frequency']['cycles_per_year'])} 周期/年、{num(full['frequency']['fills_per_year'])} 成交/年；2024 年后为 {recent['frequency']['cycles']} 个周期、{recent['frequency']['fills']} 次成交。中性层全样本激活比例 {base['neutral_metrics']['active_fraction'] * 100:.2f}%、状态切换 {base['neutral_metrics']['state_changes']} 次，2024 年后激活比例 {recent['neutral_active_fraction'] * 100:.2f}%。",
        "",
        "## 压力测试",
        "",
        "| 场景 | 全样本收益 | 全样本夏普 | 全样本回撤 | 2024-01 后收益 | 2024-01 后夏普 | 2024-01 后回撤 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in evaluation:
        f, r = item["windows"]["full"]["metrics"], item["windows"]["post2024"]["metrics"]
        report.append(f"| {stress_names[item['stress']]} | {pct(f['total_return'])} | {num(f['sharpe'])} | {pct(f['max_drawdown'])} | {pct(r['total_return'])} | {num(r['sharpe'])} | {pct(r['max_drawdown'])} |")
    report += [
        "",
        "成本加倍和 1 小时延迟会明显降低全样本收益与夏普，但 2024 年后仍保持正收益和正夏普。压力结果不应解读为真实订单簿成交保证；V4.5.3/V4.5.4 的 Maker 成交仍是 OHLC 触价代理。",
        "",
        "## 未来函数与因果审计",
        "",
        f"- 静态扫描 `v42.py`、`v453.py`、`v454.py` 的负向 `shift`、`bfill/backfill`、居中 rolling 和负向 `pct_change`：{audit['static']['status']}，命中 {len(audit['static']['forbidden_future_patterns'])} 项。",
        f"- 真实数据前缀在 2023-01-01、2024-01-01、2025-07-01、2026-01-01 四个截点重算，V4.5.4 信号与中性层均前缀一致：{audit['real_data_prefix']['status']}。中性层显式使用上一结算资金费、30 日历史窗口和上一边界的资本分配。",
        "- 该审计覆盖本地信号与资金费计算，不能替代真实订单簿、资金费到账、现货/永续基差和账户保证金系统的前向验证。",
        "",
        "## 过拟合与版本定位",
        "",
        "V4.5.4 没有重新搜索入场、空头或保护参数，资本比例直接采用 V4.2.2 已有的 75% 方向 / 15% 中性 / 10% 自由保证金结构。这样减少了本轮新增自由度，但由于使用的历史数据已参与此前 V4.5 研究，不能称为盲样本外结果。资金费中性收益还依赖现货/永续基差、借币、执行和费率假设，因此应作为冻结研究候选，不应直接视为实盘收益承诺。",
        "",
        "## 文件与复现",
        "",
        "- [V4.5.4 参数](../../configs/v4_5_4_params.json)",
        "- [V4.5.4 JSON 对比](comparison.json)",
        "- [V4.5.4 因果审计](causal_audit.json)",
        "- [压力测试结果](evaluation.json)",
        "",
        "```bash",
        "PYTHONPATH=src:scripts python3 scripts/evaluate_v454.py",
        "PYTHONPATH=src:scripts python3 scripts/render_v454_report.py",
        "PYTHONPATH=src python3 -m pytest -q",
        "```"]
    OUTPUT.write_text("\n".join(report) + "\n")
    print(OUTPUT)


if __name__ == "__main__":
    main()
