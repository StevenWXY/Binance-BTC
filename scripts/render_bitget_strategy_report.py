"""Render the external-facing Chinese Bitget strategy report as a PDF."""
from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "reports/bitget_three_latest_60"
OUT_DIR = ROOT / "output/pdf"
FIG_DIR = ROOT / "tmp/pdfs/bitget_three_report"
PDF_PATH = OUT_DIR / "bitget_three_strategy_report_20261006.pdf"
FONT = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")

COLORS = {"V4.1.2": "#2563EB", "V4.5.3": "#059669", "V7.1.2": "#D97706"}
CN = "ArialUnicode"


def setup_fonts() -> None:
    if not FONT.exists():
        raise FileNotFoundError(f"Chinese font not found: {FONT}")
    pdfmetrics.registerFont(TTFont(CN, str(FONT)))
    plt.rcParams["font.family"] = "Arial Unicode MS"
    plt.rcParams["axes.unicode_minus"] = False


def load_data():
    summary = pd.read_csv(RESULTS / "summary_metrics.csv")
    periods = pd.read_csv(RESULTS / "period_metrics.csv")
    eq = pd.read_csv(RESULTS / "equity_curves.csv", index_col=0, parse_dates=True)
    eq.index = pd.to_datetime(eq.index, utc=True)
    protocol = json.loads((RESULTS / "protocol.json").read_text())
    trades = {name: pd.read_csv(RESULTS / name / "base/trades.csv", parse_dates=["entry_time", "exit_time"]) for name in COLORS}
    fills = {name: pd.read_csv(RESULTS / name / "base/fills.csv", parse_dates=["timestamp"]) for name in COLORS}
    return summary, periods, eq, protocol, trades, fills


def fmt_pct(v, digits=1):
    return f"{v:.{digits}%}"


def fmt_num(v, digits=1):
    return f"{v:,.{digits}f}"


def daily_series(eq: pd.DataFrame) -> pd.DataFrame:
    return eq.apply(lambda s: s.dropna().resample("1D").last()).dropna(how="all")


def figure_equity(eq: pd.DataFrame) -> Path:
    daily = daily_series(eq)
    path = FIG_DIR / "equity_log.png"
    fig, ax = plt.subplots(figsize=(10.8, 4.7), dpi=180)
    for name, color in COLORS.items():
        s = daily[name].dropna()
        ax.plot(s.index, s, label=name, lw=1.6, color=color)
    ax.set_yscale("log")
    ax.set_title("三策略累计权益（对数坐标，初始权益 10,000 USDT）", fontsize=13, pad=10)
    ax.set_ylabel("权益（USDT，对数坐标）")
    ax.grid(True, alpha=.22)
    ax.legend(ncol=3, frameon=False, loc="upper left")
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def figure_drawdown(eq: pd.DataFrame) -> Path:
    daily = daily_series(eq)
    path = FIG_DIR / "drawdown.png"
    fig, ax = plt.subplots(figsize=(10.8, 4.3), dpi=180)
    for name, color in COLORS.items():
        s = daily[name].dropna()
        dd = s / s.cummax() - 1
        ax.plot(dd.index, dd * 100, label=name, lw=1.3, color=color)
    ax.fill_between(daily.index, 0, -55, color="#F8FAFC", alpha=.7)
    ax.set_title("历史回撤曲线", fontsize=13, pad=10)
    ax.set_ylabel("回撤（%）")
    ax.set_ylim(-55, 2)
    ax.grid(True, alpha=.22)
    ax.legend(ncol=3, frameon=False, loc="lower left")
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def annual_table(eq: pd.DataFrame) -> pd.DataFrame:
    daily = daily_series(eq)
    rows = []
    for year in range(2020, 2027):
        a = pd.Timestamp(f"{year}-01-01", tz="UTC")
        b = pd.Timestamp(f"{year+1}-01-01", tz="UTC")
        for name in COLORS:
            s = daily[name].dropna()
            period = s[(s.index >= a) & (s.index < b)]
            if period.empty:
                continue
            prev = s[s.index < a]
            start = prev.iloc[-1] if len(prev) else period.iloc[0]
            rows.append({"year": year, "strategy": name, "return": period.iloc[-1] / start - 1})
    return pd.DataFrame(rows)


def figure_annual(eq: pd.DataFrame) -> Path:
    ann = annual_table(eq)
    path = FIG_DIR / "annual_returns.png"
    years = sorted(ann.year.unique())
    x = np.arange(len(years))
    width = .24
    fig, ax = plt.subplots(figsize=(10.8, 4.5), dpi=180)
    for i, name in enumerate(COLORS):
        vals = [ann.loc[(ann.year == y) & (ann.strategy == name), "return"].iloc[0] * 100 for y in years]
        ax.bar(x + (i - 1) * width, vals, width, label=name, color=COLORS[name])
    ax.axhline(0, color="#334155", lw=.7)
    ax.set_xticks(x, [str(y) for y in years])
    ax.set_ylabel("年度收益（%）")
    ax.set_title("年度收益表现", fontsize=13, pad=10)
    ax.grid(axis="y", alpha=.22)
    ax.legend(ncol=3, frameon=False)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def figure_stress(summary: pd.DataFrame) -> Path:
    base = summary[summary.scenario == "base"].set_index("strategy")
    scen = ["fees_plus_50pct", "slippage_double", "funding_2x", "no_funding"]
    labels = ["手续费 +50%", "滑点 ×2", "资金费 ×2", "不计资金费"]
    path = FIG_DIR / "stress.png"
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.6), dpi=180)
    x = np.arange(len(COLORS))
    width = .19
    for j, (scenario, label) in enumerate(zip(scen, labels)):
        vals = [summary.loc[(summary.scenario == scenario) & (summary.strategy == n), "total_return"].iloc[0] * 100 for n in COLORS]
        axes[0].bar(x + (j - 1.5) * width, vals, width, label=label)
    axes[0].set_xticks(x, list(COLORS))
    axes[0].set_ylabel("全样本收益（%）")
    axes[0].set_title("压力情景下的收益")
    axes[0].grid(axis="y", alpha=.2)
    axes[0].legend(fontsize=8, frameon=False)
    for name, color in COLORS.items():
        vals = [base.loc[name, "max_drawdown"] * 100] + [summary.loc[(summary.scenario == s) & (summary.strategy == name), "max_drawdown"].iloc[0] * 100 for s in scen]
        axes[1].plot(range(5), vals, marker="o", lw=1.5, color=color, label=name)
    axes[1].set_xticks(range(5), ["基准", *labels], rotation=24, ha="right")
    axes[1].set_ylabel("最大回撤（%）")
    axes[1].set_title("压力情景下的最大回撤")
    axes[1].grid(axis="y", alpha=.2)
    axes[1].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def figure_recent(eq: pd.DataFrame) -> Path:
    daily = daily_series(eq)
    path = FIG_DIR / "recent.png"
    fig, ax = plt.subplots(figsize=(10.8, 4.3), dpi=180)
    start = pd.Timestamp("2025-01-01", tz="UTC")
    for name, color in COLORS.items():
        s = daily[name].dropna()
        s = s[s.index >= start]
        ax.plot(s.index, s / s.iloc[0] * 100, label=name, color=color, lw=1.6)
    ax.axvline(pd.Timestamp("2026-08-01", tz="UTC"), color="#64748B", ls="--", lw=1, label="新增数据起点")
    ax.set_title("近期权益（2025-01-01 起，起点归一化为 100）", fontsize=13, pad=10)
    ax.set_ylabel("归一化权益")
    ax.grid(True, alpha=.22)
    ax.legend(ncol=2, frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def risk_stats(eq: pd.DataFrame, trades: dict[str, pd.DataFrame]) -> pd.DataFrame:
    daily = daily_series(eq)
    rows = []
    for name in COLORS:
        s = daily[name].dropna()
        dd = s / s.cummax() - 1
        under = int((dd < 0).sum())
        one_day = float(s.pct_change().min())
        five_day = float(s.pct_change(5).min())
        t = trades[name]
        trade_loss = float((t.pnl / t.equity_before).min()) if "equity_before" in t.columns and not t.empty else np.nan
        rows.append({"strategy": name, "worst_1d": one_day, "worst_5d": five_day, "time_under_water": under / len(s), "largest_trade_loss": trade_loss})
    return pd.DataFrame(rows)


def make_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CoverTitle", fontName=CN, fontSize=25, leading=33, textColor=colors.HexColor("#0F172A"), alignment=TA_CENTER, spaceAfter=9 * mm))
    styles.add(ParagraphStyle(name="CoverSub", fontName=CN, fontSize=12, leading=19, textColor=colors.HexColor("#475569"), alignment=TA_CENTER, spaceAfter=5 * mm))
    styles.add(ParagraphStyle(name="H1CN", fontName=CN, fontSize=17, leading=23, textColor=colors.HexColor("#0F172A"), spaceBefore=3 * mm, spaceAfter=3 * mm))
    styles.add(ParagraphStyle(name="H2CN", fontName=CN, fontSize=12.5, leading=18, textColor=colors.HexColor("#0F766E"), spaceBefore=3 * mm, spaceAfter=2 * mm))
    styles.add(ParagraphStyle(name="BodyCN", fontName=CN, fontSize=9.3, leading=15.2, textColor=colors.HexColor("#1F2937"), spaceAfter=2.5 * mm))
    styles.add(ParagraphStyle(name="SmallCN", fontName=CN, fontSize=7.4, leading=10.4, textColor=colors.HexColor("#475569"), spaceAfter=1.5 * mm))
    styles.add(ParagraphStyle(name="TableCN", fontName=CN, fontSize=7.3, leading=9.2, textColor=colors.HexColor("#111827")))
    styles.add(ParagraphStyle(name="TableHeadCN", fontName=CN, fontSize=7.4, leading=9.2, textColor=colors.white, alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="CalloutCN", fontName=CN, fontSize=10.2, leading=16, textColor=colors.HexColor("#0F172A"), backColor=colors.HexColor("#ECFDF5"), borderColor=colors.HexColor("#A7F3D0"), borderWidth=.7, borderPadding=8, spaceBefore=2 * mm, spaceAfter=3 * mm))
    return styles


def P(text, style):
    return Paragraph(text, style)


def make_table(data, widths, styles, header=True, alignments=None):
    converted = []
    for r, row in enumerate(data):
        converted.append([P(str(v), styles["TableHeadCN" if header and r == 0 else "TableCN"]) for v in row])
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F766E")) if header else ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("GRID", (0, 0), (-1, -1), .28, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        for i in range(1, len(data)):
            if i % 2 == 0:
                ts.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F8FAFC")))
        ts.append(("REPEATROWS", (0, 0), (-1, 0)))
    if alignments:
        for col, alignment in alignments.items():
            ts.append(("ALIGN", (col, 1 if header else 0), (col, -1), alignment))
    return Table(converted, colWidths=widths, repeatRows=1 if header else 0, style=TableStyle(ts))


def build_pdf(summary, periods, eq, protocol, trades, fills):
    styles = make_styles()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    figs = [figure_equity(eq), figure_drawdown(eq), figure_annual(eq), figure_stress(summary), figure_recent(eq)]

    base = summary[summary.scenario == "base"].set_index("strategy")
    post = periods[(periods.scenario == "base") & (periods.period == "post2025")].set_index("strategy")
    recent = periods[(periods.scenario == "base") & (periods.period == "2026_to_cutoff")].set_index("strategy")
    risk = risk_stats(eq, trades).set_index("strategy")
    annual = annual_table(eq)
    funding_start = protocol["coverage"]["funding_start"][:10]
    funding_end = protocol["coverage"]["funding_end"][:10]

    doc = SimpleDocTemplate(str(PDF_PATH), pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm, topMargin=17 * mm, bottomMargin=16 * mm, title="三策略 Bitget 回测报告（截至 2026-10-06）", author="Research")
    story = []
    # Cover
    story += [Spacer(1, 20 * mm), P("BTCUSDT 永续策略研究报告", styles["CoverTitle"]), P("V4.1.2 / V4.5.3 / V7.1.2", styles["CoverSub"]), Spacer(1, 3 * mm), P("基于最新 Bitget 公共历史行情的统一回放", styles["CoverSub"]), Spacer(1, 16 * mm)]
    cover_data = [["报告基准日", "2026-10-06"], ["回测区间", "2020-01-01 至 2026-10-06（UTC）"], ["品种", "BTCUSDT USDT 永续合约"], ["手续费口径", "60% 返佣；按公开基础费率折算"], ["初始权益", "10,000 USDT（复利回放）"], ["数据覆盖", "711,648 条 5 分钟行情，连续无缺口"]]
    story.append(make_table(cover_data, [35 * mm, 110 * mm], styles, header=False))
    story += [Spacer(1, 12 * mm), P("对外版本说明：本报告展示策略定位、表现、风险与压力测试结论，不披露具体指标周期、阈值或仓位参数。参数在本次回放中保持冻结，未进行针对新增数据的重新优化。", styles["CalloutCN"]), Spacer(1, 10 * mm), P("研究用途 | 非投资建议 | 历史回测不代表未来收益", styles["CoverSub"]), PageBreak()]

    # Executive summary
    story.append(P("执行摘要", styles["H1CN"]))
    story.append(P("本次工作将三套冻结策略放在同一套 Bitget BTCUSDT 永续数据、同一资金曲线口径和同一执行模拟器中重新回放，时间覆盖到 2026-10-06。统一结果显示：V7.1.2 的全样本收益最高，但最大回撤也达到 43.2%；V4.5.3 的全样本收益为 9,131.1%，最大回撤 30.4%，2025 年以来的日收益夏普为 1.857，风险收益更均衡；V4.1.2 的回撤与波动低于 V7.1.2，但收益和近期动量明显较弱。", styles["BodyCN"]))
    exec_data = [["策略", "全样本收益", "CAGR", "日夏普", "最大回撤", "2025 后收益", "2026 至截止日收益"]]
    for name in COLORS:
        exec_data.append([name, fmt_pct(base.loc[name, "total_return"]), fmt_pct(base.loc[name, "cagr"]), f"{base.loc[name, 'sharpe']:.3f}", fmt_pct(base.loc[name, "max_drawdown"]), fmt_pct(post.loc[name, "total_return"]), fmt_pct(recent.loc[name, "total_return"])])
    story.append(make_table(exec_data, [19 * mm, 24 * mm, 19 * mm, 18 * mm, 24 * mm, 24 * mm, 27 * mm], styles, alignments={1:"RIGHT",2:"RIGHT",3:"RIGHT",4:"RIGHT",5:"RIGHT",6:"RIGHT"}))
    story.append(Spacer(1, 3 * mm))
    story.append(P("建议的对外定位是：V4.5.3 作为主展示策略，兼顾成交频率、近期收益和回撤；V4.1.2 作为偏保守的单向趋势/反弹基线；V7.1.2 作为高波动、高回撤的进取版本。上述定位是风险预算意义上的相对排序，不构成收益承诺。", styles["CalloutCN"]))
    story.append(Image(str(figs[0]), width=176 * mm, height=77 * mm))

    # Background/data
    story.append(P("一、研究背景与数据", styles["H1CN"]))
    story.append(P("本报告用于评估三套已经冻结的 BTCUSDT 永续策略，在交易所切换为 Bitget、手续费包含 60% 返佣、并补齐最新数据后，历史表现是否仍具有可解释性。策略本身不在本次工作中重新选参；新增数据只用于延长观察窗口。", styles["BodyCN"]))
    story.append(P("行情来自 Bitget 公共历史 K 线接口，包含成交价 K 线和标记价 K 线；策略信号分别在小时或四小时完成，执行层统一使用五分钟数据。2026-08-01 至 2026-10-06 的新增行情通过公开接口下载并与原缓存拼接，拼接后从 2020-01-01 00:00 UTC 到 2026-10-06 23:55 UTC 连续无缺口。", styles["BodyCN"]))
    data_table = [["项目", "本次口径", "解释"] , ["行情分辨率", "5 分钟", "用于成交、标记价、保护触发和权益更新"], ["信号节奏", "按策略冻结定义", "V4.1.2/V7.1.2 为低频状态切换，V4.5.3 为小时级方向信号"], ["资金费", f"{funding_start} 至 {funding_end} 有公开记录", "更早资金费缺失，不使用插值或伪造历史"], ["执行价格", "成交价 + 标记价代理", "不是逐笔成交或盘口队列回放"], ["数据完整性", "711,648 条，缺失 0", "时间索引连续，价格字段无空值"]]
    story.append(make_table(data_table, [31 * mm, 47 * mm, 81 * mm], styles))
    story.append(P("Bitget 官方文档说明，历史行情接口提供历史成交价与标记价 K 线，资金费接口返回资金费结算记录；公开费率示例为 Maker 0.02%、Taker 0.06%，实际账户费率取决于等级。报告按用户指定的 60% 返佣折算到回放成本。", styles["SmallCN"]))
    story.append(PageBreak())

    # Strategy descriptions
    story.append(P("二、策略定位与共同假设", styles["H1CN"]))
    strategy_text = [
        ("V4.1.2", "低频、偏多的趋势与反弹基线。它在方向判断上更克制，保护层优先于收益扩张，适合作为组合中的稳定基准。"),
        ("V4.5.3", "在方向信号上引入更积极的短周期执行与 Maker 参与，保护性退出仍按 Taker 处理。它的目标是提升资金使用效率，同时控制执行成本。"),
        ("V7.1.2", "更主动的趋势/震荡切换和双向暴露，配合波动状态、快速下行保护与追踪退出。它承担更高的收益弹性，也承担更高的回撤和资金费敏感度。"),
    ]
    for name, text in strategy_text:
        story.append(P(f"<b>{name}</b>　{text}", styles["BodyCN"]))
    story.append(P("共同假设：初始权益为 10,000 USDT，权益复利；策略目标仓位由冻结信号给出；普通调仓可使用触价式 Maker 代理，保护性退出、最终平仓和强平按 Taker 代理；成交受单根 K 线参与率上限约束；标记价用于浮盈亏、保护触发和强平检查。报告不公开具体指标周期、阈值、杠杆目标或退出距离。", styles["BodyCN"]))
    story.append(P("返佣口径：公开基础费率按 60% 返佣折算，Taker 与 Maker 分别得到相应的净成本；返佣被视为能够持续兑现的研究假设，未将账户等级、返佣上限、返佣结算延迟或资格变化纳入模型。", styles["BodyCN"]))
    story.append(Image(str(figs[4]), width=176 * mm, height=70 * mm))

    # Results
    story.append(P("三、核心回测结果", styles["H1CN"]))
    result_table = [["策略", "期末权益", "全样本收益", "CAGR", "日夏普", "Sortino", "年化波动", "最大回撤", "交易周期", "Maker 成交占比"]]
    for name in COLORS:
        result_table.append([name, f"{base.loc[name, 'final_equity']:,.0f}", fmt_pct(base.loc[name, "total_return"]), fmt_pct(base.loc[name, "cagr"]), f"{base.loc[name, 'sharpe']:.3f}", f"{base.loc[name, 'sortino']:.3f}", fmt_pct(base.loc[name, "annualized_volatility"]), fmt_pct(base.loc[name, "max_drawdown"]), f"{int(base.loc[name, 'trades'])}", fmt_pct(base.loc[name, "maker_fill_share"])])
    story.append(make_table(result_table, [18 * mm, 25 * mm, 22 * mm, 18 * mm, 18 * mm, 18 * mm, 22 * mm, 22 * mm, 19 * mm, 25 * mm], styles, alignments={1:"RIGHT",2:"RIGHT",3:"RIGHT",4:"RIGHT",5:"RIGHT",6:"RIGHT",7:"RIGHT",8:"RIGHT",9:"RIGHT"}))
    story.append(Spacer(1, 3 * mm))
    story.append(Image(str(figs[1]), width=176 * mm, height=70 * mm))
    story.append(P("回撤含义：V7.1.2 的收益曲线具有更强的复利斜率，但回撤深度明显高于另外两套策略；回撤不是单一极端日造成，而是多个阶段的累计风险暴露。V4.5.3 的历史回撤仍超过 30%，因此不能被描述为低风险策略。", styles["BodyCN"]))

    # Periods/annual
    story.append(P("四、分阶段表现与稳定性", styles["H1CN"]))
    period_table = [["策略", "阶段", "收益", "CAGR", "日夏普", "最大回撤", "周期数"]]
    for period_label, label in [("post2024", "2024-01-01 起"), ("post2025", "2025-01-01 起"), ("2026_to_cutoff", "2026-01-01 至截止日")]:
        for name in COLORS:
            row = periods[(periods.strategy == name) & (periods.scenario == "base") & (periods.period == period_label)].iloc[0]
            period_table.append([name, label, fmt_pct(row.total_return), fmt_pct(row.cagr), f"{row.sharpe:.3f}", fmt_pct(row.max_drawdown), f"{int(row.trades)}"])
    story.append(make_table(period_table, [18 * mm, 35 * mm, 22 * mm, 18 * mm, 18 * mm, 24 * mm, 18 * mm], styles, alignments={2:"RIGHT",3:"RIGHT",4:"RIGHT",5:"RIGHT",6:"RIGHT"}))
    story.append(Spacer(1, 3 * mm))
    annual_view = [["年份", *COLORS.keys()]]
    for year in sorted(annual.year.unique()):
        annual_view.append([str(year), *[fmt_pct(annual.loc[(annual.year == year) & (annual.strategy == n), "return"].iloc[0]) for n in COLORS]])
    story.append(make_table(annual_view, [25 * mm, 43 * mm, 43 * mm, 43 * mm], styles, alignments={1:"RIGHT",2:"RIGHT",3:"RIGHT"}))
    story.append(Image(str(figs[2]), width=176 * mm, height=72 * mm))
    story.append(P("新增 2026-08-01 至 2026-10-06 数据后，V4.5.3 的权益延续性较好；V4.1.2 与 V7.1.2 在 2026 年的表现取决于保护层触发和方向暴露，不能用全样本高收益直接推断近期优势。年度收益表中 2022 年三套策略均为负，说明结果并非每个市场阶段都有效。", styles["BodyCN"]))

    # Risk and costs
    story.append(PageBreak())
    story.append(P("五、风险、成本与成交结构", styles["H1CN"]))
    risk_table = [["策略", "最差单日", "最差五日", "水下时间占比", "手续费", "资金费（已观测）", "强平次数"]]
    for name in COLORS:
        r = risk.loc[name]
        risk_table.append([name, fmt_pct(r.worst_1d), fmt_pct(r.worst_5d), fmt_pct(r.time_under_water), f"{base.loc[name, 'fees_usdt']:,.0f}", f"{base.loc[name, 'funding_paid_usdt']:,.0f}", f"{int(base.loc[name, 'liquidations'])}"])
    story.append(make_table(risk_table, [20 * mm, 25 * mm, 25 * mm, 29 * mm, 25 * mm, 33 * mm, 20 * mm], styles, alignments={1:"RIGHT",2:"RIGHT",3:"RIGHT",4:"RIGHT",5:"RIGHT",6:"RIGHT"}))
    story.append(P("手续费与资金费均从成交/结算事件逐笔累计。由于公开资金费历史只覆盖最近约数月，表中的资金费不是完整历史持仓成本，只能作为近期观测项；不计资金费情景用于衡量这项缺失对结论的影响。", styles["BodyCN"]))
    cost_table = [["策略", "成交额", "费率成本 / 成交额", "Maker 成交占比", "平均持仓时长"]]
    for name in COLORS:
        cost_table.append([name, f"{base.loc[name, 'turnover_usdt']/1e6:,.1f}m", fmt_pct(base.loc[name, "fees_usdt"] / base.loc[name, "turnover_usdt"], 3), fmt_pct(base.loc[name, "maker_fill_share"]), f"{base.loc[name, 'median_holding_hours']:.1f} 小时"])
    story.append(make_table(cost_table, [21 * mm, 33 * mm, 37 * mm, 34 * mm, 35 * mm], styles, alignments={1:"RIGHT",2:"RIGHT",3:"RIGHT",4:"RIGHT"}))
    story.append(P("Maker 成交占比是 OHLC 触价代理的输出，不代表实际盘口排队成交率。真实账户可能因为排队、撤单、价格跳跃和保护性退出而出现更高 Taker 比例；因此 V4.5.3 与 V7.1.2 的费用优势需要实盘小额或纸面交易验证。", styles["BodyCN"]))

    # Stress
    story.append(P("六、压力测试", styles["H1CN"]))
    story.append(P("压力测试不重新优化信号，只改变执行或资金费假设。手续费 +50% 用于检验返佣兑现不足；滑点 ×2 用于检验成交冲击；资金费 ×2 用于检验已观测资金费的幅度放大；不计资金费用于隔离资金费项。四个情景都沿用同一行情和信号。", styles["BodyCN"]))
    stress_table = [["情景", *COLORS.keys()]]
    for scenario, label in [("base", "基准"), ("fees_plus_50pct", "手续费 +50%"), ("slippage_double", "滑点 ×2"), ("funding_2x", "资金费 ×2"), ("no_funding", "不计资金费")]:
        stress_table.append([label, *[f"收益 {fmt_pct(summary.loc[(summary.scenario == scenario) & (summary.strategy == n), 'total_return'].iloc[0])}<br/>回撤 {fmt_pct(summary.loc[(summary.scenario == scenario) & (summary.strategy == n), 'max_drawdown'].iloc[0])}" for n in COLORS]])
    story.append(make_table(stress_table, [32 * mm, 48 * mm, 48 * mm, 48 * mm], styles))
    story.append(Image(str(figs[3]), width=176 * mm, height=73 * mm))
    story.append(P("结果说明：费用和滑点加压会压低终值，但三策略的收益排序没有改变；V7.1.2 的回撤对执行加压更敏感。资金费 ×2 的边际影响小于费用与滑点压力，不能据此得出资金费风险可以忽略的结论，因为公开历史覆盖不完整。", styles["BodyCN"]))

    # Risk controls / assumptions / limitations
    story.append(PageBreak())
    story.append(P("七、风控框架与运行要求", styles["H1CN"]))
    controls = [
        ("仓位与保证金", "策略输出的是目标暴露，执行层按账户权益动态换算仓位；系统持续检查标记价权益、维持保证金和参与率，基准回放未发生强平。"),
        ("保护性退出", "止损、止盈、追踪和快速下行保护由已完成的信号 K 线生成，下一执行边界生效；保护性退出按 Taker 处理，不依赖 Maker 成交。"),
        ("流动性约束", "每根执行 K 线设置参与率上限，成交价包含基础滑点与与参与率相关的冲击项；真实账户需要根据盘口深度、订单量和时段进一步收紧。"),
        ("回撤治理", "V7.1.2 具有更高回撤预算需求，建议单独设置组合级风险预算、权益峰值告警和降杠杆开关，不能直接按 V4.5.3 的风险预算上线。"),
        ("返佣治理", "返佣不是无条件收益来源；上线前需要核对账户等级、返佣比例、结算延迟、返佣上限和异常扣回条款，并将净费率写入交易监控。"),
    ]
    for title, text in controls:
        story.append(P(f"<b>{title}</b>　{text}", styles["BodyCN"]))
    story.append(P("八、限制、可复现性与上线前检查", styles["H1CN"]))
    limits = [
        "资金费公共历史不完整；2020-01-01 至 2026-06-26 的结算费率未被伪造，基准结果相当于只计入可观测资金费。",
        "5 分钟 OHLC 无法重建逐笔成交、盘口队列、撤单、部分成交和同 K 线内成交先后；Maker 成交率因此是研究代理，不是可承诺的成交概率。",
        "历史维护保证金分档和冲击函数为确定性研究假设；无强平只说明在该假设下未触发，不代表极端行情不会触发。",
        "本报告属于历史回放，不是盲样本外测试；新增数据是在研究期内可获得的公开数据，策略参数没有因新增数据重新优化。",
        "正式上线前应做至少一段纸面交易，逐笔记录信号延迟、成交类型、实际手续费、返佣到账、资金费和滑点，并以净收益而不是毛收益复核。",
    ]
    for x in limits:
        story.append(P("• " + x, styles["BodyCN"]))
    story.append(P("九、结论", styles["H1CN"]))
    story.append(P("在统一 Bitget 数据和 60% 返佣口径下，V4.5.3 给出了最适合对外展示的风险收益平衡，V7.1.2 提供最高的历史收益弹性但需要更严格的回撤预算，V4.1.2 适合作为相对克制的基准策略。所有结论都受资金费覆盖和执行代理限制约束；报告不支持将历史 CAGR 直接外推为未来收益。", styles["CalloutCN"]))
    story.append(Spacer(1, 3 * mm))
    story.append(P("数据与方法参考", styles["H2CN"]))
    story.append(P("Bitget API 文档：历史成交价 K 线、历史标记价 K 线、历史资金费率。Bitget 支持文档：合约 Maker/Taker 手续费与资金费计算说明。内部回放协议、数据清单、哈希和逐策略机器可读结果保存在同一项目的 reports/bitget_three_latest_60/ 目录。", styles["SmallCN"]))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
        canvas.line(17 * mm, 12 * mm, 193 * mm, 12 * mm)
        canvas.setFont(CN, 7.5)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(17 * mm, 7 * mm, "BTCUSDT 永续策略研究 | 对外版本 | 截止 2026-10-06")
        canvas.drawRightString(193 * mm, 7 * mm, f"{doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(PDF_PATH)


def main():
    setup_fonts()
    data = load_data()
    build_pdf(*data)


if __name__ == "__main__":
    main()
