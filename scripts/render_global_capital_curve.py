#!/usr/bin/env python3
"""Render the global strategy equity, BTC price, and drawdown curves to PNG."""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.data import load_klines  # noqa: E402


WIDTH = 2000
HEIGHT = 1250
BACKGROUND = "#FFFFFF"
FOREGROUND = "#171A21"
MUTED = "#6B7280"
GRID = "#E5E7EB"
FRAME = "#C9CED8"
COLORS = {
    "a": "#3B82C4",
    "b": "#E58A3B",
    "c": "#3CA66B",
    "d": "#D45B57",
    "e": "#0F766E",
    "p": "#7B61B8",
}


@dataclass(frozen=True)
class PlotArea:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    font_path = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
    index = 1 if bold else 0
    return ImageFont.truetype(str(font_path), size=size, index=index)


def load_equity(path: Path, name: str) -> pd.Series:
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame["equity"].resample("1D").last().ffill().rename(name)


def load_chart_data() -> pd.DataFrame:
    equities = [
        load_equity(ROOT / "reports/aggressive_micro/micro_equity.csv", "a"),
        load_equity(ROOT / "reports/aggressive_vol_carry_micro/micro_equity.csv", "b"),
        load_equity(ROOT / "reports/aggressive_adaptive_micro/micro_equity.csv", "c"),
        load_equity(ROOT / "reports/aggressive_adaptive_v3_micro/micro_equity.csv", "d"),
        load_equity(ROOT / "reports/aggressive_adaptive_v4_short_micro/micro_equity.csv", "e"),
    ]
    data = pd.concat(equities, axis=1).dropna()
    klines = load_klines(ROOT / "data/raw", start="2020-01-01", end="2026-08-01 00:00:00+00:00")
    btc = klines["close"].resample("1D").last().ffill().rename("p")
    data = data.join(btc, how="left")
    data["p"] = data["p"].ffill().bfill()
    return data


def log_scale(value: float, low: float, high: float, bottom: int, top: int) -> float:
    ratio = (math.log(value) - math.log(low)) / (math.log(high) - math.log(low))
    return bottom - ratio * (bottom - top)


def linear_scale(value: float, low: float, high: float, bottom: int, top: int) -> float:
    ratio = (value - low) / (high - low)
    return bottom - ratio * (bottom - top)


def x_scale(timestamp: pd.Timestamp, start: pd.Timestamp, end: pd.Timestamp, area: PlotArea) -> float:
    ratio = (timestamp.value - start.value) / (end.value - start.value)
    return area.left + ratio * area.width


def format_compact(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:g}m"
    if value >= 1_000:
        return f"{value / 1_000:g}k"
    return f"{value:g}"


def draw_legend(draw: ImageDraw.ImageDraw, items: list[tuple[str, str]], y: int) -> None:
    x = 155
    label_font = font(24)
    for label, color in items:
        draw.line((x, y + 14, x + 42, y + 14), fill=color, width=3)
        x += 54
        draw.text((x, y), label, font=label_font, fill=FOREGROUND)
        bbox = draw.textbbox((x, y), label, font=label_font)
        x = bbox[2] + 46


def draw_frame(draw: ImageDraw.ImageDraw, area: PlotArea) -> None:
    draw.rectangle((area.left, area.top, area.right, area.bottom), outline=FRAME, width=2)


def draw_year_axis(
    draw: ImageDraw.ImageDraw,
    area: PlotArea,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    label_y: int,
) -> None:
    tick_font = font(21)
    for year in range(start.year, end.year + 1):
        stamp = pd.Timestamp(f"{year}-01-01", tz="UTC")
        if stamp < start or stamp > end:
            continue
        x = x_scale(stamp, start, end, area)
        draw.line((x, area.top, x, area.bottom), fill=GRID, width=1)
        label = str(year)
        bbox = draw.textbbox((0, 0), label, font=tick_font)
        draw.text((x - (bbox[2] - bbox[0]) / 2, label_y), label, font=tick_font, fill=MUTED)


def draw_rotated_label(image: Image.Image, text: str, x: int, center_y: int) -> None:
    label_font = font(23)
    bbox = label_font.getbbox(text)
    layer = Image.new("RGBA", (bbox[2] - bbox[0] + 16, bbox[3] - bbox[1] + 16), (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)
    layer_draw.text((8, 8 - bbox[1]), text, font=label_font, fill=FOREGROUND)
    rotated = layer.rotate(90, expand=True)
    image.alpha_composite(rotated, (x, int(center_y - rotated.height / 2)))


def draw_log_panel(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    data: pd.DataFrame,
    area: PlotArea,
) -> None:
    start, end = data.index[0], data.index[-1]
    equity_low = 8_000.0
    equity_keys = ["a", "b", "c", "d", "e"]
    equity_high = max(700_000.0, float(data[equity_keys].max().max()) * 1.08)
    btc_low = max(1_000.0, float(data["p"].min()) * 0.82)
    btc_high = float(data["p"].max()) * 1.18
    equity_ticks = [10_000, 20_000, 50_000, 100_000, 200_000, 500_000]
    btc_ticks = [5_000, 10_000, 20_000, 50_000, 100_000, 200_000]
    tick_font = font(21)

    draw_year_axis(draw, area, start, end, label_y=area.bottom + 13)
    for value in equity_ticks:
        if not equity_low <= value <= equity_high:
            continue
        y = log_scale(value, equity_low, equity_high, area.bottom, area.top)
        draw.line((area.left, y, area.right, y), fill=GRID, width=1)
        label = format_compact(value)
        bbox = draw.textbbox((0, 0), label, font=tick_font)
        draw.text((area.left - 18 - (bbox[2] - bbox[0]), y - 11), label, font=tick_font, fill=MUTED)
    for value in btc_ticks:
        if not btc_low <= value <= btc_high:
            continue
        y = log_scale(value, btc_low, btc_high, area.bottom, area.top)
        draw.text((area.right + 18, y - 11), format_compact(value), font=tick_font, fill=MUTED)

    for key in equity_keys:
        points = [
            (
                x_scale(ts, start, end, area),
                log_scale(float(value), equity_low, equity_high, area.bottom, area.top),
            )
            for ts, value in data[key].items()
        ]
        draw.line(points, fill=COLORS[key], width=2, joint="curve")

    btc_points = [
        (
            x_scale(ts, start, end, area),
            log_scale(float(value), btc_low, btc_high, area.bottom, area.top),
        )
        for ts, value in data["p"].items()
    ]
    draw.line(btc_points, fill=COLORS["p"], width=2, joint="curve")
    draw_frame(draw, area)
    draw_rotated_label(image, "策略账户权益（USDT，对数）", 28, (area.top + area.bottom) // 2)
    draw_rotated_label(image, "BTCUSDT 价格（USDT，对数）", WIDTH - 68, (area.top + area.bottom) // 2)
    draw.text((area.left, area.top - 43), "策略权益与 BTC 价格", font=font(27, bold=True), fill=FOREGROUND)


def draw_drawdown_panel(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    data: pd.DataFrame,
    area: PlotArea,
) -> None:
    start, end = data.index[0], data.index[-1]
    equity_keys = ["a", "b", "c", "d", "e"]
    drawdowns = data[equity_keys].div(data[equity_keys].cummax()) - 1.0
    low = min(-0.4, float(drawdowns.min().min()) * 1.08)
    high = 0.02
    tick_font = font(21)

    draw_year_axis(draw, area, start, end, label_y=area.bottom + 13)
    for value in [0.0, -0.1, -0.2, -0.3, -0.4]:
        if value < low:
            continue
        y = linear_scale(value, low, high, area.bottom, area.top)
        draw.line((area.left, y, area.right, y), fill=GRID, width=1)
        label = f"{value:.0%}"
        bbox = draw.textbbox((0, 0), label, font=tick_font)
        draw.text((area.left - 18 - (bbox[2] - bbox[0]), y - 11), label, font=tick_font, fill=MUTED)

    for key in equity_keys:
        points = [
            (
                x_scale(ts, start, end, area),
                linear_scale(float(value), low, high, area.bottom, area.top),
            )
            for ts, value in drawdowns[key].items()
        ]
        draw.line(points, fill=COLORS[key], width=2, joint="curve")
    draw_frame(draw, area)
    draw_rotated_label(image, "回撤", 60, (area.top + area.bottom) // 2)
    draw.text((area.left, area.top - 43), "策略回撤", font=font(27, bold=True), fill=FOREGROUND)
    axis_label = "日期（UTC）"
    bbox = draw.textbbox((0, 0), axis_label, font=font(22))
    draw.text(((area.left + area.right - bbox[2] + bbox[0]) / 2, area.bottom + 50), axis_label, font=font(22), fill=FOREGROUND)


def render(output: Path) -> None:
    data = load_chart_data()
    image = Image.new("RGBA", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((120, 42), "BTCUSDT 策略全局资金曲线（2020–2026）", font=font(42, bold=True), fill=FOREGROUND)
    draw.text((122, 100), "逐笔成交权益、BTC 永续合约价格与策略回撤", font=font(23), fill=MUTED)
    draw_legend(
        draw,
        [
            ("V1 基础趋势跟随与 ATR 仓位", COLORS["a"]),
            ("V2 资金费率拥挤过滤趋势", COLORS["b"]),
            ("V3 波动率与下行风险自适应", COLORS["c"]),
            ("V4 稳健长多趋势-反弹混合", COLORS["d"]),
            ("V5 谨慎对称趋势与空头确认", COLORS["e"]),
            ("P BTCUSDT 价格", COLORS["p"]),
        ],
        y=148,
    )
    draw_log_panel(image, draw, data, PlotArea(150, 245, 1830, 755))
    draw_drawdown_panel(image, draw, data, PlotArea(150, 870, 1830, 1125))
    draw.text(
        (150, 1205),
        "数据：Binance USD-M BTCUSDT；权益为分钟级逐笔成交、资金费和维持保证金模型结果。",
        font=font(19),
        fill=MUTED,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports/global_capital_curve_v4_with_btc.png",
    )
    args = parser.parse_args()
    render(args.output)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
