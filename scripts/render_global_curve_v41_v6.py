#!/usr/bin/env python3
"""Render the seven-line 4h curve: V1, V2, V3, V4.1, V5, V6 and BTC."""

from __future__ import annotations

import json
import math
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
OUT_DIR = ROOT / "reports/global_curve_v41_v6_2020_2026_08_27"

STRATEGIES = {
    "V1": ("基础趋势跟随与 ATR 仓位", ROOT / "configs/aggressive_params.json"),
    "V2": ("资金费率拥挤过滤趋势", ROOT / "configs/aggressive_vol_carry_params.json"),
    "V3": ("波动率与下行风险自适应", ROOT / "configs/aggressive_adaptive_params.json"),
    "V4.1": ("稳健长多趋势-反弹混合", ROOT / "configs/v4_refined_params.json"),
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
SERIES = ["V1", "V2", "V3", "V4.1", "V5", "V6", "BTC"]
NAMES = {
    "V1": "V1 趋势跟随",
    "V2": "V2 资金费过滤",
    "V3": "V3 波动下行自适应",
    "V4.1": "V4.1 长多趋势反弹",
    "V5": "V5 对称趋势空头",
    "V6": "V6 置信度动态风险",
    "BTC": "BTC 价格",
}
HIGHLIGHTED = {"V4.1", "V6", "BTC"}


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
    btc_equity = curves["BTC"]
    years = (btc_equity.index[-1] - btc_equity.index[0]).total_seconds() / (365.25 * 24 * 3600)
    btc_returns = btc_equity.pct_change().dropna()
    metrics["BTC"] = {
        "strategy": "BTCUSDT 价格基准",
        "start_price": float(price.iloc[0]),
        "end_price": float(price.iloc[-1]),
        "total_return": float(btc_equity.iloc[-1] / btc_equity.iloc[0] - 1),
        "cagr": float((btc_equity.iloc[-1] / btc_equity.iloc[0]) ** (1 / years) - 1),
        "annualized_volatility": float(btc_returns.std(ddof=1) * (365 * 6) ** 0.5),
        "sharpe": float(btc_returns.mean() / btc_returns.std(ddof=1) * (365 * 6) ** 0.5),
        "max_drawdown": float((btc_equity / btc_equity.cummax() - 1).min()),
        "final_equity": float(btc_equity.iloc[-1]),
    }
    curve = pd.concat(curves.values(), axis=1).sort_index().ffill().dropna()
    return curve, metrics


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(
        "/System/Library/Fonts/Hiragino Sans GB.ttc", size=size, index=1 if bold else 0
    )


def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _draw_legend(
    draw: ImageDraw.ImageDraw,
    left: int,
    right: int,
    y: int,
    *,
    series: list[str] | None = None,
    names: dict[str, str] | None = None,
    colors: dict[str, str] | None = None,
    highlighted: set[str] | None = None,
) -> int:
    """Draw compact, wrapping strategy labels and return the final baseline."""
    series = series or SERIES
    names = names or NAMES
    colors = colors or COLORS
    highlighted = highlighted or HIGHLIGHTED
    x = left
    for code in series:
        label = names[code]
        label_width = draw.textbbox((0, 0), label, font=_font(19))[2]
        needed = label_width + 88
        if x != left and x + needed > right:
            x = left
            y += 34
        line_width = 2 if code in highlighted else 1
        draw.line((x, y + 13, x + 34, y + 13), fill=_rgb(colors[code]), width=line_width)
        draw.text((x + 44, y), label, font=_font(19), fill=(55, 55, 55))
        x += needed
    return y


def _draw_year_lines(
    draw: ImageDraw.ImageDraw,
    curve: pd.DataFrame,
    left: int,
    right: int,
    top: int,
    bottom: int,
) -> None:
    start, end = curve.index[0], curve.index[-1]
    for year in range(start.year, end.year + 1):
        stamp = pd.Timestamp(f"{year}-01-01", tz="UTC")
        if stamp < start or stamp > end:
            continue
        x = left + (stamp.value - start.value) / max(end.value - start.value, 1) * (right - left)
        draw.line((x, top, x, bottom), fill=(235, 237, 240), width=1)
        draw.text((x - 22, bottom + 16), str(year), font=_font(20), fill=(90, 90, 90))


def render_single(
    curve: pd.DataFrame,
    output: Path,
    kind: str,
    *,
    subtitle: str | None = None,
    note: str | None = None,
    series: list[str] | None = None,
    names: dict[str, str] | None = None,
    colors: dict[str, str] | None = None,
    highlighted: set[str] | None = None,
    title: str | None = None,
    plot_title: str | None = None,
) -> None:
    """Render standalone equity or drawdown charts for reports and sharing."""
    series = series or SERIES
    names = names or NAMES
    colors = colors or COLORS
    highlighted = highlighted or HIGHLIGHTED
    width, height = 2200, 1220
    left, right, top, bottom = 170, 2080, 330, 1080
    image = Image.new("RGB", (width, height), (252, 252, 252))
    draw = ImageDraw.Draw(image)
    values = curve[series].astype(float)
    is_equity = kind == "equity"
    title = title or ("BTCUSDT 策略累计收益曲线" if is_equity else "BTCUSDT 策略峰值回撤曲线")
    plot_title = plot_title or ("累计权益（USDT，对数纵轴）" if is_equity else "回撤（相对历史峰值）")

    draw.text((left, 36), title, font=_font(34, True), fill=(25, 25, 25))
    subtitle = subtitle or "V1–V6（含 V4.1）与 BTC · 2020-01-01 至 2026-08-25 08:00 UTC · 4小时"
    note = note or "2018–2019 无可比的 Binance BTCUSDT 永续合约样本，未用现货数据替代"
    draw.text((left, 87), subtitle, font=_font(22), fill=(90, 90, 90))
    draw.text((left, 122), note, font=_font(20), fill=(115, 70, 45))
    _draw_legend(
        draw,
        left,
        right,
        165,
        series=series,
        names=names,
        colors=colors,
        highlighted=highlighted,
    )
    draw.text((left, top - 42), plot_title, font=_font(24, True), fill=(45, 45, 45))
    draw.rectangle((left, top, right, bottom), outline=(170, 175, 185), width=2)
    _draw_year_lines(draw, curve, left, right, top, bottom)

    start, end = curve.index[0], curve.index[-1]
    step = max(1, len(curve) // 5000)
    if is_equity:
        low = max(float(values.min().min()) * 0.82, 1000.0)
        high = float(values.max().max()) * 1.12
        log_low, log_high = math.log(low), math.log(high)
        for tick in [1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000, 2000000]:
            if not low <= tick <= high:
                continue
            y = bottom - (math.log(tick) - log_low) / (log_high - log_low) * (bottom - top)
            draw.line((left, y, right, y), fill=(225, 228, 233), width=1)
            draw.text((left - 86, y - 12), f"{tick / 1000:g}k", font=_font(20), fill=(90, 90, 90))
        series_values = values

        def y_for(value: float) -> float:
            return bottom - (math.log(value) - log_low) / (log_high - log_low) * (bottom - top)
    else:
        series_values = values / values.cummax() - 1.0
        low = min(float(series_values.min().min()) * 1.08, -0.1)
        high = 0.02
        for tick in [0.0, -0.1, -0.2, -0.3, -0.4, -0.5, -0.6, -0.7, -0.8]:
            if tick < low:
                continue
            y = bottom - (tick - low) / (high - low) * (bottom - top)
            draw.line((left, y, right, y), fill=(225, 228, 233), width=1)
            draw.text((left - 70, y - 12), f"{tick:.0%}", font=_font(20), fill=(90, 90, 90))

        def y_for(value: float) -> float:
            return bottom - (value - low) / (high - low) * (bottom - top)

    for code in series:
        points = []
        for timestamp, value in series_values[code].iloc[::step].items():
            x = left + (timestamp.value - start.value) / max(end.value - start.value, 1) * (right - left)
            points.append((x, y_for(float(value))))
        if len(points) > 1:
            draw.line(points, fill=_rgb(colors[code]), width=2 if code in highlighted else 1, joint="curve")
    draw.text((left, bottom + 62), "日期（UTC）", font=_font(22), fill=(45, 45, 45))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def render(
    curve: pd.DataFrame,
    output: Path,
    *,
    series: list[str] | None = None,
    names: dict[str, str] | None = None,
    colors: dict[str, str] | None = None,
    highlighted: set[str] | None = None,
    title: str | None = None,
    subtitle: str | None = None,
    note: str | None = None,
) -> None:
    series = series or SERIES
    names = names or NAMES
    colors = colors or COLORS
    highlighted = highlighted or HIGHLIGHTED
    width, height = 2200, 1700
    left, right = 170, 2080
    equity_top, equity_bottom = 250, 960
    drawdown_top, drawdown_bottom = 1120, 1530
    image = Image.new("RGB", (width, height), (252, 252, 252))
    draw = ImageDraw.Draw(image)
    draw.text((left, 38), title or "BTCUSDT 策略收益与回撤", font=_font(34, True), fill=(25, 25, 25))
    draw.text((left, 89), subtitle or "有效数据 2020-01-01 至 2026-08-25 08:00 UTC · 初始权益 10,000 USDT", font=_font(22), fill=(90, 90, 90))
    draw.text((left, 125), note or "2018–2019 无可比的 Binance BTCUSDT 永续合约样本，未用现货数据替代", font=_font(20), fill=(115, 70, 45))
    draw.rectangle((left, equity_top, right, equity_bottom), outline=(170, 175, 185), width=2)
    values = curve[series].astype(float)
    low = max(float(values.min().min()) * 0.82, 1000.0)
    high = float(values.max().max()) * 1.12
    log_low, log_high = math.log(low), math.log(high)
    for tick in [1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000]:
        if not low <= tick <= high:
            continue
        y = equity_bottom - (math.log(tick) - log_low) / (log_high - log_low) * (equity_bottom - equity_top)
        draw.line((left, y, right, y), fill=(225, 228, 233), width=1)
        label = f"{tick / 1000:g}k" if tick >= 1000 else str(tick)
        draw.text((left - 86, y - 12), label, font=_font(20), fill=(90, 90, 90))
    start, end = curve.index[0], curve.index[-1]
    for year in range(start.year, end.year + 1):
        stamp = pd.Timestamp(f"{year}-01-01", tz="UTC")
        if stamp < start or stamp > end:
            continue
        x = left + (stamp.value - start.value) / max(end.value - start.value, 1) * (right - left)
        draw.line((x, equity_top, x, equity_bottom), fill=(235, 237, 240), width=1)
        draw.line((x, drawdown_top, x, drawdown_bottom), fill=(235, 237, 240), width=1)
        draw.text((x - 22, drawdown_bottom + 16), str(year), font=_font(20), fill=(90, 90, 90))
    step = max(1, len(curve) // 5000)
    for code in series:
        points = []
        for timestamp, value in values[code].iloc[::step].items():
            x = left + (timestamp.value - start.value) / max(end.value - start.value, 1) * (right - left)
            y = equity_bottom - (math.log(float(value)) - log_low) / (log_high - log_low) * (equity_bottom - equity_top)
            points.append((x, y))
        if len(points) > 1:
            draw.line(points, fill=_rgb(colors[code]), width=2 if code in highlighted else 1, joint="curve")
    _draw_legend(
        draw,
        left,
        right,
        155,
        series=series,
        names=names,
        colors=colors,
        highlighted=highlighted,
    )
    draw.text((left, equity_top - 36), "累计收益曲线（对数纵轴）", font=_font(24, True), fill=(45, 45, 45))
    draw.text((25, (equity_top + equity_bottom) // 2), "账户权益（USDT）", font=_font(22), fill=(45, 45, 45))

    drawdowns = values / values.cummax() - 1.0
    draw.rectangle((left, drawdown_top, right, drawdown_bottom), outline=(170, 175, 185), width=2)
    dd_low = min(float(drawdowns.min().min()) * 1.08, -0.1)
    dd_high = 0.02
    for tick in [0.0, -0.1, -0.2, -0.3, -0.4, -0.5, -0.6]:
        if tick < dd_low:
            continue
        y = drawdown_bottom - (tick - dd_low) / (dd_high - dd_low) * (drawdown_bottom - drawdown_top)
        draw.line((left, y, right, y), fill=(225, 228, 233), width=1)
        draw.text((left - 70, y - 12), f"{tick:.0%}", font=_font(20), fill=(90, 90, 90))
    for code in series:
        points = []
        for timestamp, value in drawdowns[code].iloc[::step].items():
            x = left + (timestamp.value - start.value) / max(end.value - start.value, 1) * (right - left)
            y = drawdown_bottom - (float(value) - dd_low) / (dd_high - dd_low) * (drawdown_bottom - drawdown_top)
            points.append((x, y))
        if len(points) > 1:
            draw.line(points, fill=_rgb(colors[code]), width=2 if code in highlighted else 1, joint="curve")
    draw.text((left, drawdown_top - 42), "峰值回撤曲线", font=_font(24, True), fill=(45, 45, 45))
    draw.text((60, (drawdown_top + drawdown_bottom) // 2), "回撤", font=_font(22), fill=(45, 45, 45))
    draw.text((left, drawdown_bottom + 62), "日期（UTC）", font=_font(22), fill=(45, 45, 45))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def main() -> None:
    market = load_market()
    curve, metrics = backtest_curve(market)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    curve.to_csv(OUT_DIR / "equity_curves.csv")
    drawdowns = curve / curve.cummax() - 1.0
    drawdowns.to_csv(OUT_DIR / "drawdown_curves.csv")
    summary_rows = []
    for code, strategy_metrics in metrics.items():
        summary_rows.append({
            "code": code,
            "strategy": strategy_metrics["strategy"],
            "final_equity": strategy_metrics["final_equity"],
            "total_return": strategy_metrics["total_return"],
            "cagr": strategy_metrics["cagr"],
            "sharpe": strategy_metrics["sharpe"],
            "max_drawdown": strategy_metrics["max_drawdown"],
        })
    pd.DataFrame(summary_rows).to_csv(OUT_DIR / "summary_metrics.csv", index=False)
    annual_rows = []
    for year, annual_curve in curve.groupby(curve.index.year):
        annual_dd = annual_curve / annual_curve.cummax() - 1.0
        for code in curve.columns:
            annual_rows.append({
                "year": int(year),
                "code": code,
                "return": float(annual_curve[code].iloc[-1] / annual_curve[code].iloc[0] - 1),
                "max_drawdown": float(annual_dd[code].min()),
            })
    pd.DataFrame(annual_rows).to_csv(OUT_DIR / "annual_returns_drawdowns.csv", index=False)
    payload = {
        "data_start": curve.index[0].isoformat(),
        "latest_curve_point": curve.index[-1].isoformat(),
        "requested_start": "2018-01-01",
        "availability_note": "BTCUSDT perpetual data is not available for 2018-2019; no spot proxy was substituted.",
        "bar_interval": "4h",
        "signal_timing": "completed candle; position applies to next 4h bar",
        "strategies": metrics,
    }
    (OUT_DIR / "metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    render_single(curve, OUT_DIR / "equity_curve_7lines.png", "equity")
    render_single(curve, OUT_DIR / "drawdown_curve_7lines.png", "drawdown")
    render(curve, OUT_DIR / "equity_drawdown_7lines.png")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
