#!/usr/bin/env python3
"""Render unified equity and drawdown curves into one PNG figure."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "reports/unified_v4_v7_btc_2020_2026_08_01"
COLORS = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#475569"]


def font(size: int, bold: bool = False):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/ArialHB.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def scale(values: np.ndarray, lo: float, hi: float, start: float, length: float) -> np.ndarray:
    return start + length * (values - lo) / (hi - lo if hi > lo else 1.0)


def render(input_dir: Path, output: Path, width: int = 2200, height: int = 1300) -> None:
    equity = pd.read_csv(input_dir / "equity_curves.csv", index_col=0, parse_dates=True)
    drawdown = pd.read_csv(input_dir / "drawdown_curves.csv", index_col=0, parse_dates=True)
    columns = list(equity.columns)
    equity = equity[columns].astype(float)
    drawdown = drawdown[columns].astype(float)

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = font(34, True)
    section_font = font(25, True)
    label_font = font(18)
    small_font = font(16)

    left, right = 145, 55
    plot_right = width - right
    top1, bottom1 = 145, 700
    top2, bottom2 = 830, 1160
    plot_width = plot_right - left

    draw.text((left, 28), "Unified BTCUSDT Strategy Equity and Drawdown", fill="#111827", font=title_font)
    draw.text((left, 68), "2020-01-01 to 2026-08-01 UTC · initial equity $10,000", fill="#475569", font=small_font)
    draw.text((left, top1 - 43), "Equity (USDT)", fill="#111827", font=section_font)
    draw.text((left, top2 - 43), "Drawdown", fill="#111827", font=section_font)

    eq_min = 0.0
    eq_max = float(np.nanmax(equity.to_numpy()))
    eq_max *= 1.04
    dd_min = float(np.nanmin(drawdown.to_numpy()))
    dd_min = min(dd_min * 1.08, -0.02)
    dd_max = 0.0

    for panel_top, panel_bottom, lo, hi, is_dd in [
        (top1, bottom1, eq_min, eq_max, False),
        (top2, bottom2, dd_min, dd_max, True),
    ]:
        draw.rectangle((left, panel_top, plot_right, panel_bottom), outline="#94a3b8", width=2)
        for tick in range(6):
            value = lo + (hi - lo) * tick / 5
            y = panel_bottom - (panel_bottom - panel_top) * tick / 5
            draw.line((left, y, plot_right, y), fill="#e5e7eb", width=1)
            text = f"{value:.0%}" if is_dd else f"${value:,.0f}"
            bbox = draw.textbbox((0, 0), text, font=label_font)
            draw.text((left - (bbox[2] - bbox[0]) - 12, y - (bbox[3] - bbox[1]) / 2), text, fill="#475569", font=label_font)
        for fraction in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
            x = left + plot_width * fraction
            draw.line((x, panel_top, x, panel_bottom), fill="#f1f5f9", width=1)

    n = len(equity)
    x = np.linspace(left, plot_right, n)
    for i, column in enumerate(columns):
        color = COLORS[i % len(COLORS)]
        y_eq = bottom1 - (bottom1 - top1) * (equity[column].to_numpy() - eq_min) / (eq_max - eq_min)
        y_dd = bottom2 - (bottom2 - top2) * (drawdown[column].to_numpy() - dd_min) / (dd_max - dd_min)
        draw.line(list(zip(x.tolist(), y_eq.tolist())), fill=color, width=3)
        draw.line(list(zip(x.tolist(), y_dd.tolist())), fill=color, width=3)

    # Date labels and a shared legend.
    for fraction, label in zip((0.0, 0.2, 0.4, 0.6, 0.8, 1.0), ("2020", "2021", "2022", "2023", "2024", "2025–26")):
        xpos = left + plot_width * fraction
        bbox = draw.textbbox((0, 0), label, font=small_font)
        draw.text((xpos - (bbox[2] - bbox[0]) / 2, bottom2 + 18), label, fill="#475569", font=small_font)
    legend_x = left + 730
    legend_y = 1220
    for i, column in enumerate(columns):
        color = COLORS[i % len(COLORS)]
        col_width = 190 if column != "V4.1.2" else 205
        draw.line((legend_x, legend_y + 9, legend_x + 30, legend_y + 9), fill=color, width=4)
        draw.text((legend_x + 40, legend_y), column, fill="#111827", font=small_font)
        legend_x += col_width
        if legend_x > width - 230:
            legend_x = left + 730
            legend_y += 30

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_DIR / "equity_drawdown_curves.png")
    args = parser.parse_args()
    render(args.input_dir, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
