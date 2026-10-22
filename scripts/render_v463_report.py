"""Render the complete V4.6.3 strategy report and research figures."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.ticker import PercentFormatter
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "v4_6_3"


def load_equity(name: str) -> pd.Series:
    frame = pd.read_csv(REPORT / name, index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame.iloc[:, 0].astype(float).rename(frame.columns[0])


def daily_equity(equity: pd.Series) -> pd.Series:
    return equity.resample("1D", closed="right", label="right").last().dropna()


def render_equity(control: pd.Series, selected: pd.Series) -> None:
    curves = {
        "V4.6.1 control": daily_equity(control),
        "V4.6.3 selected": daily_equity(selected),
    }
    fig, (ax_equity, ax_dd) = plt.subplots(
        2, 1, figsize=(13.5, 8.5), sharex=True,
        gridspec_kw={"height_ratios": [2.2, 1]},
    )
    colors = {"V4.6.1 control": "#64748b", "V4.6.3 selected": "#0f766e"}
    for label, curve in curves.items():
        ax_equity.plot(curve.index, curve, label=label, lw=1.5, color=colors[label])
        drawdown = curve / curve.cummax() - 1.0
        ax_dd.plot(curve.index, drawdown * 100, label=label, lw=1.15, color=colors[label])
    ax_equity.set_yscale("log")
    ax_equity.set_ylabel("Equity (USDT, log scale)")
    ax_equity.set_title("BTCUSDT V4.6.1 vs V4.6.3 — all-Taker 5-minute replay")
    ax_equity.grid(True, which="both", alpha=0.2)
    ax_equity.legend(loc="upper left", frameon=False)
    ax_equity.annotate(
        f"V4.6.3 final: {selected.iloc[-1]:,.0f} USDT",
        xy=(selected.index[-1], selected.iloc[-1]),
        xytext=(-130, 12), textcoords="offset points", fontsize=9,
        arrowprops={"arrowstyle": "-", "color": "#0f766e", "lw": 0.8},
        color="#0f766e",
    )
    ax_dd.axhline(0, color="#475569", lw=0.7)
    ax_dd.set_ylabel("Drawdown (%)")
    ax_dd.set_xlabel("UTC date")
    ax_dd.grid(True, alpha=0.2)
    ax_dd.legend(loc="lower left", frameon=False, ncol=2)
    fig.tight_layout()
    fig.savefig(REPORT / "equity_curve.png", dpi=180, bbox_inches="tight")
    fig.savefig(REPORT / "equity_curve.svg", bbox_inches="tight")
    plt.close(fig)


def _heat_frame(values: pd.Series) -> pd.DataFrame:
    frame = values.copy()
    frame.index = pd.to_datetime(frame.index, utc=True)
    table = frame.to_frame("return")
    table["year"] = table.index.year
    table["month"] = table.index.month
    pivot = table.pivot(index="year", columns="month", values="return")
    return pivot.reindex(columns=range(1, 13))


def _draw_heatmap(ax, table: pd.DataFrame, title: str, vmin: float, vmax: float,
                  annotate: bool = True) -> None:
    data = table.to_numpy(dtype=float)
    norm = TwoSlopeNorm(vmin=vmin, vcenter=0.0, vmax=vmax)
    image = ax.imshow(data, cmap="RdYlGn", norm=norm, aspect="auto")
    ax.set_title(title, loc="left", fontsize=11, pad=8)
    ax.set_xticks(range(12), ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    ax.set_yticks(range(len(table.index)), [str(year) for year in table.index])
    ax.set_xlabel("Calendar month")
    ax.set_ylabel("Year")
    ax.set_xticks(np.arange(-.5, 12, 1), minor=True)
    ax.set_yticks(np.arange(-.5, len(table.index), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.1)
    ax.tick_params(which="minor", bottom=False, left=False)
    if annotate:
        for row in range(data.shape[0]):
            for col in range(data.shape[1]):
                value = data[row, col]
                if np.isfinite(value):
                    color = "#173042" if abs(value) < 0.18 else "white"
                    ax.text(col, row, f"{value:.1%}", ha="center", va="center",
                            fontsize=8, color=color)
    return image


def render_heatmap(monthly: pd.DataFrame) -> None:
    selected = _heat_frame(monthly["V4.6.3"])
    delta = _heat_frame(monthly["V4.6.3"] - monthly["V4.6.1"])
    years = sorted(set(selected.index).union(delta.index))
    selected = selected.reindex(years)
    delta = delta.reindex(years)
    fig, axes = plt.subplots(2, 1, figsize=(13.5, 7.8), sharex=True)
    im1 = _draw_heatmap(axes[0], selected, "V4.6.3 monthly returns", -0.12, 0.55)
    im2 = _draw_heatmap(axes[1], delta, "V4.6.3 minus V4.6.1 monthly return", -0.08, 0.08)
    pct_fmt = PercentFormatter(1.0, decimals=0)
    fig.colorbar(im1, ax=axes[0], fraction=0.025, pad=0.02, format=pct_fmt)
    fig.colorbar(im2, ax=axes[1], fraction=0.025, pad=0.02, format=pct_fmt)
    fig.suptitle("V4.6.3 monthly return heatmap — complete UTC calendar months",
                 x=0.08, ha="left", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(REPORT / "monthly_return_heatmap.png", dpi=180, bbox_inches="tight")
    fig.savefig(REPORT / "monthly_return_heatmap.svg", bbox_inches="tight")
    plt.close(fig)


def _annual_metrics(curves: dict[str, pd.Series]) -> pd.DataFrame:
    rows = []
    for strategy, equity in curves.items():
        daily = daily_equity(equity)
        for year, group in daily.groupby(daily.index.year):
            returns = group.pct_change().dropna()
            start, end = float(group.iloc[0]), float(group.iloc[-1])
            years = max((group.index[-1] - group.index[0]).total_seconds() / (365.25 * 86400), 1 / 365.25)
            sd = returns.std(ddof=1)
            rows.append({
                "strategy": strategy,
                "year": int(year),
                "start_equity": start,
                "end_equity": end,
                "return": end / start - 1,
                "cagr": (end / start) ** (1 / years) - 1,
                "daily_sharpe": returns.mean() / sd * np.sqrt(365.25) if sd > 0 else 0.0,
                "max_drawdown": float((group / group.cummax() - 1).min()),
                "days": int(len(returns)),
            })
    return pd.DataFrame(rows)


def _pct(value: float) -> str:
    return f"{value:.2%}"


def write_report(control: pd.Series, selected: pd.Series, monthly: pd.DataFrame,
                 annual: pd.DataFrame, payload: dict, stress: pd.DataFrame) -> None:
    selected_result = payload["results"]["V4.6.3_selected_all_taker"]
    control_result = payload["results"]["V4.6.1_control_all_taker"]
    full_s = selected_result["windows"]["full"]
    full_c = control_result["windows"]["full"]
    rows = []
    for label, item in [("V4.6.1 control", control_result), ("V4.6.3 selected", selected_result)]:
        for period, metrics in item["windows"].items():
            rows.append(
                f"| {label} | {period} | {_pct(metrics['cagr'])} | {metrics['daily_sharpe']:.3f} | "
                f"{_pct(metrics['mean'])} | {_pct(metrics['std'])} | {metrics['monthly_sharpe']:.2f} | "
                f"{_pct(metrics['max_drawdown'])} | {metrics['positive_fraction']:.1%} |"
            )
    annual_rows = []
    for _, row in annual.iterrows():
        annual_rows.append(
            f"| {row['strategy']} | {int(row['year'])} | {_pct(row['return'])} | "
            f"{row['daily_sharpe']:.3f} | {_pct(row['max_drawdown'])} |"
        )
    candidate = pd.DataFrame(payload["candidate_screen"])
    candidate_rows = []
    for _, row in candidate.iterrows():
        candidate_rows.append(
            f"| {row['candidate']} | {row['score']:.3f} | {_pct(row['train_2020_2023_cagr'])} | "
            f"{row['train_2020_2023_daily_sharpe']:.3f} | {_pct(row['validation_2024_2025_cagr'])} | "
            f"{row['validation_2024_2025_daily_sharpe']:.3f} | {_pct(row['pre_holdout_2026_01_08_cagr'])} | "
            f"{row['pre_holdout_2026_01_08_daily_sharpe']:.3f} | "
            f"{'是' if row['selected'] else '否'} |"
        )
    stress_rows = []
    for _, row in stress.iterrows():
        stress_rows.append(
            f"| {row['scenario']} | {_pct(row['cagr'])} | {row['daily_sharpe']:.3f} | "
            f"{_pct(row['max_drawdown'])} | {int(row['liquidations'])} |"
        )
    p = payload["signal_params"]
    e = payload["execution"]
    text = f"""# V4.6.3 BTCUSDT 永续策略完整报告

## 结论

V4.6.3 保留 V4.6.1 的 V4.5.3/b022 多空信号，只调整月内风险预算。全样本 5 分钟 OHLC 执行回放从 2020-01-01 覆盖至 2026-10-11 07:55 UTC，主结果使用全 Taker 成交、60% 手续费返佣后的有效 Taker 费率 2.4 bps。

| 指标 | V4.6.1 控制 | V4.6.3 选择 | 变化 |
|---|---:|---:|---:|
| 累计收益 | {_pct(full_c['total_return'])} | {_pct(full_s['total_return'])} | {_pct(full_s['total_return'] - full_c['total_return'])} |
| 期末权益（初始 10,000 USDT） | {control.iloc[-1]:,.0f} USDT | {selected.iloc[-1]:,.0f} USDT | {selected.iloc[-1] - control.iloc[-1]:+,.0f} USDT |
| CAGR | {_pct(full_c['cagr'])} | {_pct(full_s['cagr'])} | {_pct(full_s['cagr'] - full_c['cagr'])} |
| 日频 Sharpe | {full_c['daily_sharpe']:.3f} | {full_s['daily_sharpe']:.3f} | {full_s['daily_sharpe'] - full_c['daily_sharpe']:+.3f} |
| 月均收益 | {_pct(full_c['mean'])} | {_pct(full_s['mean'])} | {_pct(full_s['mean'] - full_c['mean'])} |
| 月收益标准差 | {_pct(full_c['std'])} | {_pct(full_s['std'])} | {_pct(full_s['std'] - full_c['std'])} |
| 月度 Sharpe | {full_c['monthly_sharpe']:.2f} | {full_s['monthly_sharpe']:.2f} | {full_s['monthly_sharpe'] - full_c['monthly_sharpe']:+.2f} |
| 最大回撤 | {_pct(full_c['max_drawdown'])} | {_pct(full_s['max_drawdown'])} | {_pct(full_s['max_drawdown'] - full_c['max_drawdown'])} |
| 正收益月份 | {full_c['positive_fraction']:.1%} | {full_s['positive_fraction']:.1%} | {full_s['positive_fraction'] - full_c['positive_fraction']:+.1%} |

![V4.6.1 与 V4.6.3 权益曲线及回撤](equity_curve.png)

![V4.6.3 月收益热力图](monthly_return_heatmap.png)

## 策略规则

### 信号层

- 4 小时趋势 EMA/ADX/DI 状态、小时突破/重夺、结构性空头过滤。
- 空头要求结构性下行、ADX 达标、成交活跃度确认、资金费率不过度拥挤。
- ATR、波动率和风险预算共同决定目标杠杆；目标信号每小时更新，下一小时执行。
- 参数沿用 V4.6.1：`entry={p['base']['entry']}`、`confirmation={p['base']['confirmation']}`、`ADX >= {p['base']['adx_min']:.0f}`、冷却 `{p['base']['cooldown_hours']}h`、风险档位 `{p['base']['risk']}`。

### V4.6.3 风险预算

| 条件 | 暴露系数 |
|---|---:|
| 正常月份 | `{p['exposure_scale']:.2f}` |
| 月内 BTC 收益 ≤ `{p['monthly_soft_loss']:.0%}` | `{p['soft_loss_scale']:.2f}` |
| 月内 BTC 收益 ≤ `{p['monthly_hard_loss']:.0%}` | `{p['hard_loss_scale']:.2f}` |
| 月内 BTC 收益 ≥ `+{p['monthly_profit_lock']:.0%}` | `{p['profit_lock_scale']:.2f}` |

月内收益使用完成小时收盘价计算，规则作用于下一小时，因此不读取未来价格或账户未来权益。

## 分阶段结果

| 策略 | 区间 | CAGR | 日频 Sharpe | 月均收益 | 月收益标准差 | 月度 Sharpe | 最大回撤 | 正收益月份 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

诊断区间为 2026-09-01 以后，仅有一个完整月，未参与候选选择。它的结果用于揭示近期敏感性，不作为样本外证明。

## 年度结果

| 策略 | 年份 | 年收益 | 日频 Sharpe | 最大回撤 |
|---|---:|---:|---:|---:|
{chr(10).join(annual_rows)}

2026 年为截至 2026-10-11 07:55 UTC 的年内结果，并非完整自然年。

## 候选筛选与过拟合控制

候选集合共 8 个，在读取 2026-09 诊断窗前固定。历史选择折叠为 2020–2023、2024–2025、2026-01–2026-08。候选必须在三折中 CAGR 为正，且折叠回撤相对 V4.6.1 控制最多恶化 1 个百分点；评分使用折叠 Sharpe 中位数、Sharpe 离散度、CAGR 和月收益标准差，接近时优先简单覆盖层。

| 候选 | 稳健评分 | 2020–2023 CAGR | 2020–2023 Sharpe | 2024–2025 CAGR | 2024–2025 Sharpe | 2026-01–08 CAGR | 2026-01–08 Sharpe | 选中 |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|
{chr(10).join(candidate_rows)}

## 执行与压力测试

执行假设：5 分钟 OHLC 成交检查、基础滑点 1 bps、冲击滑点 8 bps、单根最大参与率 2%、保护性退出使用 Taker；主结果不假设 Maker 排队优势。

| 场景 | CAGR | 日频 Sharpe | 最大回撤 | 强平次数 |
|---|---:|---:|---:|---:|
{chr(10).join(stress_rows)}

## 复现与文件

```bash
python3 scripts/evaluate_v463.py --data data/bitget_20261011 --output reports/v4_6_3
python3 scripts/render_v463_report.py
```

- 权益与成交：`V4_6_1_control_equity.csv`、`V4_6_3_selected_equity.csv`、`V4_6_3_selected_trades.csv`、`V4_6_3_selected_fills.csv`
- 月收益：`monthly_returns.csv`
- 候选与压力测试：`candidate_screen.csv`、`execution_stress.csv`
- 年度结果：`annual_metrics.csv`
- 图表：`equity_curve.png`、`monthly_return_heatmap.png`

## 限制

- 历史数据在研究期间已可见，不能称为完全盲样本外验证。
- 2026-09 诊断窗口很短，不能单独用于判断长期有效性。
- Bitget 公共资金费缓存只覆盖 2026-06-27 以后，早期资金费未伪造。
- 5 分钟 OHLC 是成交代理，没有真实盘口、队列位置、盘口价差和逐笔撮合。
- 维护保证金档位沿用回测假设，实际交易所参数和资金费结算仍需前向核验。
"""
    (REPORT / "README.md").write_text(text)


def main() -> None:
    control = load_equity("V4_6_1_control_equity.csv")
    selected = load_equity("V4_6_3_selected_equity.csv")
    monthly = pd.read_csv(REPORT / "monthly_returns.csv", index_col=0, parse_dates=True)
    monthly.index = pd.to_datetime(monthly.index, utc=True)
    annual = _annual_metrics({"V4.6.1 control": control, "V4.6.3 selected": selected})
    annual.to_csv(REPORT / "annual_metrics.csv", index=False)
    payload = json.loads((REPORT / "report.json").read_text())
    stress = pd.read_csv(REPORT / "execution_stress.csv")
    render_equity(control, selected)
    render_heatmap(monthly)
    write_report(control, selected, monthly, annual, payload, stress)
    print("Rendered", REPORT)


if __name__ == "__main__":
    main()
