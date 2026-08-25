#!/usr/bin/env python3
"""Render recent and minute-level V1-V6/BTC equity and drawdown curves."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
COLORS = {
    "V1": "#2563eb",
    "V2": "#ea580c",
    "V3": "#16a34a",
    "V4": "#dc2626",
    "V5": "#0f766e",
    "V6": "#111827",
    "P": "#7c3aed",
}
NAMES = {
    "V1": "V1 基础趋势跟随",
    "V2": "V2 资金费率过滤",
    "V3": "V3 波动率自适应",
    "V4": "V4 长多趋势-反弹",
    "V5": "V5 对称趋势空头",
    "V6": "V6 置信度动态风险",
    "P": "BTC 价格",
}


def _series(path: Path, name: str) -> pd.Series:
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True, format="mixed")
    series = frame.iloc[:, 0].astype(float)
    series.name = name
    return series


def _recent() -> pd.DataFrame:
    base = pd.read_csv(ROOT / "reports/recent_2026_07_01_2026_08_25/equity_and_btc.csv", index_col=0)
    base.index = pd.to_datetime(base.index, utc=True, format="mixed")
    v6 = _series(ROOT / "reports/v6_2026_08_25/v6_recent_equity.csv", "V6")
    frame = base.rename(columns={"P": "P"})
    frame["V6"] = v6.reindex(frame.index)
    return frame[["V1", "V2", "V3", "V4", "V5", "V6", "P"]].dropna()


def _micro() -> pd.DataFrame:
    paths = {
        "V1": ROOT / "reports/aggressive_micro/micro_equity.csv",
        "V2": ROOT / "reports/aggressive_vol_carry_micro/micro_equity.csv",
        "V3": ROOT / "reports/aggressive_adaptive_micro/micro_equity.csv",
        "V4": ROOT / "reports/aggressive_adaptive_v3_micro/micro_equity.csv",
        "V5": ROOT / "reports/aggressive_adaptive_v4_short_micro/micro_equity.csv",
        "V6": ROOT / "reports/v6_micro_2020_2026_07_31/micro_equity.csv",
    }
    frame = pd.concat([_series(path, name) for name, path in paths.items()], axis=1)
    market = pd.read_csv(ROOT / "reports/annual_2020_2026_08_25/market_4h_full.csv", index_col=0)
    market.index = pd.to_datetime(market.index, utc=True, format="mixed") + pd.Timedelta(hours=4)
    frame["P"] = market["close"].reindex(frame.index)
    return frame.dropna()


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(
        "/System/Library/Fonts/Hiragino Sans GB.ttc", size=size, index=1 if bold else 0
    )


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _draw_panel(
    draw: ImageDraw.ImageDraw,
    data: pd.DataFrame,
    top: int,
    title: str,
    ylabel: str,
    drawdown: bool = False,
) -> None:
    left, right, bottom = 150, 1740, top + 260
    keys = [key for key in ["V1", "V2", "V3", "V4", "V5", "V6", "P"] if key in data]
    transformed: dict[str, pd.Series] = {}
    for key in keys:
        series = data[key].astype(float)
        transformed[key] = series / series.cummax() - 1.0 if drawdown else series / series.iloc[0] * 10_000.0
    all_values = pd.concat(transformed.values())
    low = float(all_values.min())
    high = float(all_values.max())
    if drawdown:
        low = min(low * 1.08, -0.01)
        high = 0.01
    else:
        span = max(high - low, 1.0)
        low -= span * 0.04
        high += span * 0.04
    draw.text((left, top - 34), title, font=_font(27, True), fill=(30, 30, 30))
    draw.rectangle((left, top, right, bottom), outline=(175, 175, 175), width=1)
    for j in range(1, 5):
        y = top + (bottom - top) * j / 5
        draw.line((left, y, right, y), fill=(225, 225, 225), width=1)
        value = high - (high - low) * j / 5
        label = f"{value:.0%}" if drawdown else f"{value:,.0f}"
        draw.text((left - 120, y - 11), label, font=_font(18), fill=(90, 90, 90))
    start, end = data.index[0], data.index[-1]
    for key in keys:
        series = transformed[key]
        step = max(1, len(series) // 4500)
        points = []
        for timestamp, value in series.iloc[::step].items():
            x = left + (timestamp.value - start.value) / max(end.value - start.value, 1) * (right - left)
            y = bottom - (float(value) - low) / max(high - low, 1e-12) * (bottom - top)
            points.append((x, y))
        if len(points) > 1:
            draw.line(points, fill=_rgb(COLORS[key]), width=3 if key == "V6" else 1, joint="curve")
    draw.text((left, bottom + 12), f"{start:%Y-%m-%d}", font=_font(18), fill=(90, 90, 90))
    end_label = f"{end:%Y-%m-%d} UTC"
    end_width = draw.textbbox((0, 0), end_label, font=_font(18))[2]
    draw.text((right - end_width, bottom + 12), end_label, font=_font(18), fill=(90, 90, 90))
    legend_x, legend_y = left, top - 3
    for key in keys:
        swatch = _rgb(COLORS[key])
        draw.line((legend_x, legend_y + 13, legend_x + 30, legend_y + 13), fill=swatch, width=3 if key == "V6" else 1)
        draw.text((legend_x + 38, legend_y), NAMES[key], font=_font(18), fill=(55, 55, 55))
        legend_x += 205 if key != "P" else 150
        if legend_x > 1500:
            legend_x, legend_y = left, legend_y + 26


def render(output: Path) -> None:
    recent = _recent()
    micro = _micro()
    image = Image.new("RGB", (1800, 1500), (252, 252, 252))
    draw = ImageDraw.Draw(image)
    draw.text((150, 22), "BTCUSDT V1–V6 回测资金曲线与回撤", font=_font(34, True), fill=(25, 25, 25))
    _draw_panel(draw, recent, 95, "近期 4 小时收盘到收盘：V1–V6 与 BTC", "归一化权益（USDT）")
    _draw_panel(draw, recent.drop(columns=["P"]), 430, "近期策略回撤", "回撤", drawdown=True)
    _draw_panel(draw, micro, 765, "2020-01 至 2026-07 逐分钟成交：V1–V6 与 BTC", "归一化权益（USDT）")
    _draw_panel(draw, micro.drop(columns=["P"]), 1100, "逐分钟成交策略回撤", "回撤", drawdown=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


if __name__ == "__main__":
    render(ROOT / "reports/v6_2026_08_25/v6_curves.png")
