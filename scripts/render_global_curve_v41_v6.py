#!/usr/bin/env python3
"""Render the seven-line 4h curve: V1, V2, V3, V4.1, V5, V6 and BTC."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.backtest import BacktestConfig, run_backtest  # noqa: E402
from btc_regime.strategy import StrategyParams, generate_signals  # noqa: E402
from btc_regime.v6 import V6Params, generate_v6_signals  # noqa: E402


MARKET = ROOT / "reports/annual_2020_2026_08_25/market_4h_full.csv"
FUNDING = ROOT / "reports/annual_2020_2026_08_25/funding_full.csv"
OUT_DIR = ROOT / "reports/global_curve_v41_v6_2020_2026_08_26"

STRATEGIES = {
    "V1": ("基础趋势跟随与 ATR 仓位", ROOT / "configs/aggressive_params.json"),
    "V2": ("资金费率拥挤过滤趋势", ROOT / "configs/aggressive_vol_carry_params.json"),
    "V3": ("波动率与下行风险自适应", ROOT / "configs/aggressive_adaptive_params.json"),
    "V4.1": ("稳健长多趋势-反弹混合（优化）", ROOT / "configs/v4_refined_params.json"),
    "V5": ("谨慎对称趋势与空头确认", ROOT / "configs/aggressive_adaptive_v4_short_params.json"),
}
COLORS = {
    "V1": "#2563eb",
    "V2": "#ea580c",
    "V3": "#16a34a",
    "V4.1": "#dc2626",
    "V5": "#0f766e",
    "V6": "#111827",
    "BTC": "#7c3aed",
}


def load_market() -> pd.DataFrame:
    market = pd.read_csv(MARKET, index_col=0, parse_dates=True)
    market.index = pd.to_datetime(market.index, utc=True, format="mixed")
    funding = pd.read_csv(FUNDING, index_col=0, parse_dates=True)
    funding.index = pd.to_datetime(funding.index, utc=True, format="mixed")
    funding_4h = funding["funding_rate"].groupby(funding.index.floor("4h")).sum()
    market["funding_rate"] = funding_4h.reindex(market.index, fill_value=0.0)
    return market.sort_index()


def backtest_curve(market: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    config = BacktestConfig(initial_cash=10_000.0, fee_bps=4.0, slippage_bps=1.0)
    curves: dict[str, pd.Series] = {}
    metrics: dict[str, object] = {}
    for code, (name, path) in STRATEGIES.items():
        params = StrategyParams(**json.loads(path.read_text(encoding="utf-8")))
        frame = generate_signals(market, params)
        frame.index = frame.index + pd.Timedelta(hours=4)
        result = run_backtest(frame, config)
        curves[code] = result.equity.rename(code)
        metrics[code] = {"strategy": name, **result.metrics}

    v6_params = V6Params(**json.loads((ROOT / "configs/v6_params.json").read_text(encoding="utf-8")))
    v6_frame = generate_v6_signals(market, v6_params)
    v6_frame.index = v6_frame.index + pd.Timedelta(hours=4)
    v6_result = run_backtest(v6_frame, config)
    curves["V6"] = v6_result.equity.rename("V6")
    metrics["V6"] = {"strategy": "置信度驱动多周期动态风险", **v6_result.metrics}

    price = market["close"].copy()
    price.index = price.index + pd.Timedelta(hours=4)
    curves["BTC"] = (price / price.iloc[0] * 10_000.0).rename("BTC")
    metrics["BTC"] = {"strategy": "BTCUSDT 价格基准", "start_price": float(price.iloc[0]), "end_price": float(price.iloc[-1])}
    curve = pd.concat(curves.values(), axis=1).sort_index().ffill().dropna()
    return curve, metrics


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(
        "/System/Library/Fonts/Hiragino Sans GB.ttc", size=size, index=1 if bold else 0
    )


def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def render(curve: pd.DataFrame, output: Path) -> None:
    width, height = 2200, 1250
    left, right, top, bottom = 170, 2080, 190, 1030
    image = Image.new("RGB", (width, height), (252, 252, 252))
    draw = ImageDraw.Draw(image)
    draw.text((left, 42), "BTCUSDT 4 小时回测资金曲线：V1–V3、V4.1、V5、V6 与 BTC", font=_font(34, True), fill=(25, 25, 25))
    draw.text((left, 95), "2020-01-01 至 2026-08-25 08:00 UTC · 初始权益 10,000 USDT · 对数纵轴", font=_font(22), fill=(90, 90, 90))
    draw.rectangle((left, top, right, bottom), outline=(170, 175, 185), width=2)
    values = curve[["V1", "V2", "V3", "V4.1", "V5", "V6", "BTC"]].astype(float)
    low = max(float(values.min().min()) * 0.82, 1000.0)
    high = float(values.max().max()) * 1.12
    log_low, log_high = __import__("math").log(low), __import__("math").log(high)
    for tick in [1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000]:
        if not low <= tick <= high:
            continue
        y = bottom - (__import__("math").log(tick) - log_low) / (log_high - log_low) * (bottom - top)
        draw.line((left, y, right, y), fill=(225, 228, 233), width=1)
        label = f"{tick / 1000:g}k" if tick >= 1000 else str(tick)
        draw.text((left - 86, y - 12), label, font=_font(20), fill=(90, 90, 90))
    start, end = curve.index[0], curve.index[-1]
    for year in range(start.year, end.year + 1):
        stamp = pd.Timestamp(f"{year}-01-01", tz="UTC")
        if stamp < start or stamp > end:
            continue
        x = left + (stamp.value - start.value) / max(end.value - start.value, 1) * (right - left)
        draw.line((x, top, x, bottom), fill=(235, 237, 240), width=1)
        draw.text((x - 22, bottom + 16), str(year), font=_font(20), fill=(90, 90, 90))
    step = max(1, len(curve) // 5000)
    for code in ["V1", "V2", "V3", "V4.1", "V5", "V6", "BTC"]:
        points = []
        for timestamp, value in values[code].iloc[::step].items():
            x = left + (timestamp.value - start.value) / max(end.value - start.value, 1) * (right - left)
            y = bottom - (__import__("math").log(float(value)) - log_low) / (log_high - log_low) * (bottom - top)
            points.append((x, y))
        if len(points) > 1:
            draw.line(points, fill=_rgb(COLORS[code]), width=4 if code in {"V4.1", "V6", "BTC"} else 2, joint="curve")
    legend_x, legend_y = left, 135
    names = {"V1": "V1", "V2": "V2", "V3": "V3", "V4.1": "V4.1 优化", "V5": "V5", "V6": "V6", "BTC": "BTC"}
    for code in ["V1", "V2", "V3", "V4.1", "V5", "V6", "BTC"]:
        draw.line((legend_x, legend_y + 13, legend_x + 34, legend_y + 13), fill=_rgb(COLORS[code]), width=4 if code in {"V4.1", "V6", "BTC"} else 2)
        draw.text((legend_x + 44, legend_y), names[code], font=_font(20), fill=(55, 55, 55))
        legend_x += 210 if code == "V4.1" else 155
    draw.text((left, bottom + 62), "日期（UTC）", font=_font(22), fill=(45, 45, 45))
    draw.text((25, (top + bottom) // 2), "账户权益（USDT，对数）", font=_font(22), fill=(45, 45, 45))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def main() -> None:
    market = load_market()
    curve, metrics = backtest_curve(market)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    curve.to_csv(OUT_DIR / "equity_curves.csv")
    payload = {
        "data_start": curve.index[0].isoformat(),
        "latest_curve_point": curve.index[-1].isoformat(),
        "bar_interval": "4h",
        "signal_timing": "completed candle; position applies to next 4h bar",
        "strategies": metrics,
    }
    (OUT_DIR / "metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    render(curve, OUT_DIR / "equity_curve_7lines.png")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
