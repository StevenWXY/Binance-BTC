#!/usr/bin/env python3
"""Render the latest completed-bar V1-V5/BTC curve to PNG."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 2000, 1250
BACKGROUND, FOREGROUND, MUTED = "#FFFFFF", "#171A21", "#68707D"
GRID, FRAME = "#E5E7EB", "#C9CED8"
COLORS = {"V1": "#3B82C4", "V2": "#E58A3B", "V3": "#3CA66B", "V4": "#D45B57", "V5": "#0F766E", "P": "#7B61B8"}
LABELS = {
    "V1": "V1 基础趋势跟随与 ATR 仓位",
    "V2": "V2 资金费率拥挤过滤趋势",
    "V3": "V3 波动率与下行风险自适应",
    "V4": "V4 稳健长多趋势-反弹混合",
    "V5": "V5 谨慎对称趋势与空头确认",
    "P": "P BTCUSDT 价格",
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(
        "/System/Library/Fonts/Hiragino Sans GB.ttc", size=size, index=1 if bold else 0
    )


def x_scale(ts: pd.Timestamp, start: pd.Timestamp, end: pd.Timestamp, left: int, right: int) -> float:
    return left + (ts.value - start.value) / (end.value - start.value) * (right - left)


def y_scale(value: float, low: float, high: float, top: int, bottom: int) -> float:
    return bottom - (value - low) / (high - low) * (bottom - top)


def draw_legend(draw: ImageDraw.ImageDraw, y: int) -> None:
    x = 150
    for key in ["V1", "V2", "V3", "V4", "V5", "P"]:
        draw.line((x, y + 14, x + 38, y + 14), fill=COLORS[key], width=2)
        x += 49
        draw.text((x, y), LABELS[key], font=font(22), fill=FOREGROUND)
        x = draw.textbbox((x, y), LABELS[key], font=font(22))[2] + 35


def panel_frame(draw: ImageDraw.ImageDraw, left: int, top: int, right: int, bottom: int) -> None:
    draw.rectangle((left, top, right, bottom), outline=FRAME, width=1)


def date_ticks(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    ticks = pd.date_range(start.normalize(), end.normalize(), freq="7D", tz="UTC").tolist()
    return [pd.Timestamp(t) for t in ticks if start <= pd.Timestamp(t) <= end]


def render(input_path: Path, output_path: Path) -> None:
    data = pd.read_csv(input_path, index_col=0, parse_dates=True)
    data.index = pd.to_datetime(data.index, utc=True)
    legacy = {"A": "V1", "B": "V2", "C": "V3", "D": "V4", "E": "V5"}
    data = data.rename(columns={key: value for key, value in legacy.items() if key in data.columns})
    data = data.dropna(subset=["P"])
    start, end = data.index[0], data.index[-1]
    date_label = f"{start:%Y-%m-%d} 至 {end:%Y-%m-%d}"
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((115, 34), f"BTCUSDT 近期回测资金曲线（{date_label}）", font=font(40, True), fill=FOREGROUND)
    draw.text((118, 91), "V1–V5 五个冻结策略与 P BTCUSDT 价格；4 小时收盘到收盘，线宽 1 px", font=font(22), fill=MUTED)
    draw_legend(draw, 138)

    left, right = 145, 1850
    top, bottom = 205, 710
    equity_keys = ["V1", "V2", "V3", "V4", "V5"]
    equity_low = min(7000.0, float(data[equity_keys].min().min()) * 0.98)
    equity_high = max(10200.0, float(data[equity_keys].max().max()) * 1.02)
    btc_low = float(data["P"].min()) * 0.98
    btc_high = float(data["P"].max()) * 1.02
    for value in [7000, 8000, 9000, 10000]:
        if equity_low <= value <= equity_high:
            y = y_scale(value, equity_low, equity_high, top, bottom)
            draw.line((left, y, right, y), fill=GRID, width=1)
            draw.text((left - 83, y - 11), f"{value:,.0f}", font=font(19), fill=MUTED)
    for value in [58000, 60000, 62000, 64000, 66000]:
        if btc_low <= value <= btc_high:
            y = y_scale(value, btc_low, btc_high, top, bottom)
            draw.text((right + 14, y - 11), f"{value:,.0f}", font=font(19), fill=MUTED)
    for ts in date_ticks(start, end):
        x = x_scale(ts, start, end, left, right)
        draw.line((x, top, x, bottom), fill=GRID, width=1)
        draw.text((x - 37, bottom + 12), ts.strftime("%m-%d"), font=font(19), fill=MUTED)
    for key in equity_keys:
        points = [(x_scale(ts, start, end, left, right), y_scale(float(value), equity_low, equity_high, top, bottom)) for ts, value in data[key].items()]
        draw.line(points, fill=COLORS[key], width=1, joint="curve")
    points = [(x_scale(ts, start, end, left, right), y_scale(float(value), btc_low, btc_high, top, bottom)) for ts, value in data["P"].items()]
    draw.line(points, fill=COLORS["P"], width=1, joint="curve")
    panel_frame(draw, left, top, right, bottom)
    draw.text((left, top - 37), "账户权益（USDT）与 BTC 价格（USDT，双 Y 轴）", font=font(25, True), fill=FOREGROUND)
    draw.text((32, (top + bottom) // 2), "权益", font=font(22), fill=FOREGROUND)
    draw.text((right + 14, top - 32), "P 价格", font=font(21), fill=COLORS["P"])

    dd_top, dd_bottom = 835, 1125
    drawdowns = data[equity_keys].div(data[equity_keys].cummax()) - 1
    dd_low = min(-0.22, float(drawdowns.min().min()) * 1.08)
    dd_high = 0.01
    for value in [0.0, -0.05, -0.10, -0.15, -0.20]:
        if dd_low <= value <= dd_high:
            y = y_scale(value, dd_low, dd_high, dd_top, dd_bottom)
            draw.line((left, y, right, y), fill=GRID, width=1)
            draw.text((left - 75, y - 11), f"{value:.0%}", font=font(19), fill=MUTED)
    for ts in date_ticks(start, end):
        x = x_scale(ts, start, end, left, right)
        draw.line((x, dd_top, x, dd_bottom), fill=GRID, width=1)
        draw.text((x - 37, dd_bottom + 12), ts.strftime("%m-%d"), font=font(19), fill=MUTED)
    for key in equity_keys:
        points = [(x_scale(ts, start, end, left, right), y_scale(float(value), dd_low, dd_high, dd_top, dd_bottom)) for ts, value in drawdowns[key].items()]
        draw.line(points, fill=COLORS[key], width=1, joint="curve")
    panel_frame(draw, left, dd_top, right, dd_bottom)
    draw.text((left, dd_top - 37), "策略回撤", font=font(25, True), fill=FOREGROUND)
    draw.text((43, (dd_top + dd_bottom) // 2), "回撤", font=font(22), fill=FOREGROUND)
    draw.text((left + 690, 1172), "日期（UTC）", font=font(21), fill=FOREGROUND)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=ROOT / "reports/recent_2026_07_01_2026_08_25/equity_and_btc.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/recent_2026_07_01_2026_08_25/recent_capital_curve.png")
    args = parser.parse_args()
    render(args.input, args.output)


if __name__ == "__main__":
    main()
