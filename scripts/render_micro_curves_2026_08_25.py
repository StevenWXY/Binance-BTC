#!/usr/bin/env python3
"""Render minute-execution equity and drawdown charts as PNG and inline HTML."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from render_global_curve_v41_v6 import render_single  # noqa: E402


OUT_DIR = ROOT / "reports/micro_curve_v41_v6_2020_2026_08_25"
VIS_DIR = Path(
    "/Users/weixinyu/.codex/visualizations/2026/08/21/"
    "01a0224f-3da3-79b1-a0a4-fd5a11e9be6c"
)
SOURCE_HTML = VIS_DIR / "btc-backtest-returns-drawdown.html"
OUTPUT_HTML = VIS_DIR / "btc-micro-backtest-returns-drawdown.html"


def build_html(curve: pd.DataFrame, summary: pd.DataFrame) -> None:
    daily = curve.groupby(curve.index.floor("1D")).tail(1).dropna()
    rows = []
    for timestamp, row in daily.iterrows():
        values = {"date": timestamp.strftime("%Y-%m-%d %H:%M")}
        values.update({code: round(float(row[code]), 2) for code in curve.columns})
        rows.append(values)
    metric_rows = [
        {
            "code": row.code,
            "final_equity": round(float(row.final_equity), 2),
            "total_return": round(float(row.total_return), 6),
            "cagr": round(float(row.cagr), 6),
            "sharpe": round(float(row.sharpe), 6),
            "max_drawdown": round(float(row.max_drawdown), 6),
        }
        for row in summary.itertuples()
    ]
    payload = json.dumps(
        {
            "start": curve.index[0].strftime("%Y-%m-%d %H:%M"),
            "end": curve.index[-1].strftime("%Y-%m-%d %H:%M"),
            "rows": rows,
            "summary": metric_rows,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    html = SOURCE_HTML.read_text(encoding="utf-8")
    html = html.replace("btc-backtest-returns-drawdown", "btc-micro-backtest-returns-drawdown")
    html = html.replace("BTCUSDT 策略收益与回撤", "BTCUSDT 逐分钟成交复测：收益与回撤", 1)
    data_start = '<script type="application/json" id="btc-micro-backtest-returns-drawdown-data">'
    before, remainder = html.split(data_start, 1)
    _, after = remainder.split("</script>", 1)
    html = before + data_start + "\n" + payload + "\n</script>" + after
    html = html.replace("const parseDate = d3.utcParse('%Y-%m-%d');", "const parseDate = d3.utcParse('%Y-%m-%d %H:%M');")
    html = html.replace(
        "`${payload.start} 至 ${payload.end} UTC · 4 小时信号 · 初始权益 10,000 USDT`",
        "`${payload.start} 至 ${payload.end} UTC · 逐分钟成交复测 · 初始权益 10,000 USDT`",
    )
    html = html.replace(
        "'2018–2019 无可比的 Binance BTCUSDT 永续合约样本；未使用现货数据替代。'",
        "'1 分钟成交与标记价格；含手续费、基础与冲击滑点、资金费、成交量约束及盘中保证金检查。'",
    )
    OUTPUT_HTML.write_text(html, encoding="utf-8")


def main() -> None:
    curve = pd.read_csv(OUT_DIR / "equity_curves.csv", index_col=0, parse_dates=True)
    curve.index = pd.to_datetime(curve.index, utc=True, format="mixed")
    summary = pd.read_csv(OUT_DIR / "summary_metrics.csv")
    subtitle = "V1–V6（含 V4.1）与 BTC · 2020-01-01 至 2026-08-25 08:00 UTC · 逐分钟成交复测"
    note = "含手续费、基础与冲击滑点、资金费、成交量约束及盘中保证金检查"
    render_single(
        curve,
        OUT_DIR / "equity_curve_7lines_micro.png",
        "equity",
        subtitle=subtitle,
        note=note,
    )
    render_single(
        curve,
        OUT_DIR / "drawdown_curve_7lines_micro.png",
        "drawdown",
        subtitle=subtitle,
        note=note,
    )
    build_html(curve, summary)


if __name__ == "__main__":
    main()
