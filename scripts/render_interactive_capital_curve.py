#!/usr/bin/env python3
"""Generate the thread-scoped interactive capital-curve HTML fragment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btc_regime.data import load_klines  # noqa: E402


DEFAULT_OUTPUT = Path(
    "/Users/weixinyu/.codex/visualizations/2026/08/14/"
    "01a0016b-55c6-7bf0-9d2c-1373fb789e81/global-capital-curve.html"
)


def load_equity(path: Path, name: str) -> pd.Series:
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame["equity"].resample("1D").last().ffill().rename(name)


def chart_rows() -> list[list[float | int]]:
    data = pd.concat(
        [
            load_equity(ROOT / "reports/aggressive_micro/micro_equity.csv", "a"),
            load_equity(ROOT / "reports/aggressive_vol_carry_micro/micro_equity.csv", "b"),
            load_equity(ROOT / "reports/aggressive_adaptive_micro/micro_equity.csv", "c"),
            load_equity(ROOT / "reports/aggressive_adaptive_v3_micro/micro_equity.csv", "d"),
            load_equity(ROOT / "reports/aggressive_adaptive_v4_short_micro/micro_equity.csv", "e"),
        ],
        axis=1,
    ).dropna()
    btc = load_klines(
        ROOT / "data/raw",
        start="2020-01-01",
        end="2026-08-01 00:00:00+00:00",
    )["close"].resample("1D").last().ffill().rename("p")
    data = data.join(btc, how="left")
    data["p"] = data["p"].ffill().bfill()
    return [
        [
            int(timestamp.timestamp() * 1000),
            *[round(float(row[key]), 2) for key in ["a", "b", "c", "d", "e", "p"]],
        ]
        for timestamp, row in data.iterrows()
    ]


def render_fragment(rows: list[list[float | int]]) -> str:
    raw = json.dumps(rows, separators=(",", ":"))
    return f'''<div id="btc-global-capital-curve-v4">
  <style>
    #btc-global-capital-curve-v4 {{ position: relative; width: 100%; color: var(--foreground); font-family: ui-sans-serif, system-ui, sans-serif; }}
    #btc-global-capital-curve-v4 h2 {{ margin: 0 0 8px; font-weight: 500; letter-spacing: 0; }}
    #btc-global-capital-curve-v4 .legend {{ display: flex; flex-wrap: wrap; gap: 6px 18px; margin: 0 0 10px; }}
    #btc-global-capital-curve-v4 .legend button {{ display: inline-flex; align-items: center; gap: 7px; padding: 3px 0; border: 0; background: transparent; color: var(--foreground); font: inherit; cursor: pointer; }}
    #btc-global-capital-curve-v4 .legend button[aria-pressed="false"] {{ opacity: .42; }}
    #btc-global-capital-curve-v4 .swatch {{ width: 18px; height: 2px; }}
    #btc-global-capital-curve-v4 .plot {{ width: 100%; }}
    #btc-global-capital-curve-v4 svg {{ display: block; width: 100%; overflow: visible; }}
    #btc-global-capital-curve-v4 .axis text,
    #btc-global-capital-curve-v4 .axis-title {{ fill: var(--foreground); font-size: 12px; }}
    #btc-global-capital-curve-v4 .axis path,
    #btc-global-capital-curve-v4 .axis line {{ stroke: var(--border); }}
    #btc-global-capital-curve-v4 .grid line {{ stroke: var(--border); stroke-opacity: .45; }}
    #btc-global-capital-curve-v4 .grid path {{ display: none; }}
    #btc-global-capital-curve-v4 [data-chart-frame] {{ fill: transparent; stroke: var(--border); }}
    #btc-global-capital-curve-v4 .series-line {{ fill: none; stroke-width: 1.25; }}
    #btc-global-capital-curve-v4 .price-line {{ fill: none; stroke-width: 1.1; }}
    #btc-global-capital-curve-v4 .drawdown-line {{ fill: none; stroke-width: 1; }}
    #btc-global-capital-curve-v4 [data-chart-hover-guide] {{ stroke: var(--foreground); stroke-opacity: .35; stroke-dasharray: 3 3; pointer-events: none; }}
    #btc-global-capital-curve-v4 [data-chart-hover-marker] {{ stroke: var(--popover); stroke-width: 1.5; pointer-events: none; }}
    #btc-global-capital-curve-v4 .tooltip {{ position: absolute; z-index: 10; display: none; min-width: 170px; padding: 8px 10px; border: 1px solid var(--border); background: var(--popover); color: var(--popover-foreground); font-size: 12px; pointer-events: none; }}
    #btc-global-capital-curve-v4 .tooltip-row {{ display: flex; justify-content: space-between; gap: 18px; }}
    #btc-global-capital-curve-v4 .tooltip-name {{ display: inline-flex; align-items: center; gap: 6px; }}
    #btc-global-capital-curve-v4 .tooltip-dot {{ width: 8px; height: 8px; border-radius: 50%; }}
  </style>
  <h2>BTCUSDT 全局资金曲线（A–E + P，2020–2026）</h2>
  <div class="legend" aria-label="曲线图例"></div>
  <div class="plot" data-plot="equity"></div>
  <div class="plot" data-plot="drawdown"></div>
  <div class="tooltip" role="tooltip"></div>
  <script src="https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"></script>
  <script>
  (() => {{
    const root = document.getElementById('btc-global-capital-curve-v4');
    const raw = {raw};
    const equitySeries = [
      {{ key: 'a', name: 'A 原 Aggressive', color: 'var(--viz-series-1)', axis: 'equity' }},
      {{ key: 'b', name: 'B 资金费因子', color: 'var(--viz-series-2)', axis: 'equity' }},
      {{ key: 'c', name: 'C 自适应 V1', color: 'var(--viz-series-3)', axis: 'equity' }},
      {{ key: 'd', name: 'D 稳健 V3（仅多）', color: 'var(--viz-series-4)', axis: 'equity' }},
      {{ key: 'e', name: 'E 谨慎对称空头 V4', color: 'var(--viz-series-5)', axis: 'equity' }}
    ];
    const priceSeries = {{ key: 'p', name: 'P BTCUSDT 价格', color: 'var(--viz-series-6)', axis: 'price' }};
    const series = [...equitySeries, priceSeries];
    const visible = new Set(series.map(d => d.key));
    const data = raw.map(d => ({{ date: new Date(d[0]), a: d[1], b: d[2], c: d[3], d: d[4], e: d[5], p: d[6] }}));
    const peaks = Object.fromEntries(equitySeries.map(s => [s.key, -Infinity]));
    data.forEach(row => {{
      row.dd = {{}};
      equitySeries.forEach(s => {{
        peaks[s.key] = Math.max(peaks[s.key], row[s.key]);
        row.dd[s.key] = row[s.key] / peaks[s.key] - 1;
      }});
    }});

    const legend = d3.select(root).select('.legend');
    legend.selectAll('button').data(series).join('button')
      .attr('type', 'button').attr('aria-pressed', 'true')
      .html(d => `<span class="swatch" style="background:${{d.color}}"></span><span>${{d.name}}</span>`)
      .on('click', function(event, d) {{
        const activeEquities = equitySeries.filter(s => visible.has(s.key));
        if (d.axis === 'equity' && visible.has(d.key) && activeEquities.length === 1) return;
        if (visible.has(d.key)) visible.delete(d.key); else visible.add(d.key);
        d3.select(this).attr('aria-pressed', visible.has(d.key) ? 'true' : 'false');
        draw();
      }});

    const tooltip = d3.select(root).select('.tooltip');
    const formatDate = d3.timeFormat('%Y-%m-%d');
    const formatMoney = d3.format(',.0f');
    const formatPct = d3.format('.1%');

    function interpolate(date, key, drawdown) {{
      const right = d3.bisector(d => d.date).right(data, date);
      const i1 = Math.min(Math.max(right, 1), data.length - 1);
      const a = data[i1 - 1], b = data[i1];
      const t = Math.max(0, Math.min(1, (date - a.date) / Math.max(b.date - a.date, 1)));
      const av = drawdown ? a.dd[key] : a[key];
      const bv = drawdown ? b.dd[key] : b[key];
      return av + (bv - av) * t;
    }}

    function chart(container, drawdown) {{
      const width = Math.max(container.getBoundingClientRect().width, 320);
      const compact = width < 520;
      const height = drawdown ? (compact ? 210 : 230) : (compact ? 300 : 390);
      const margin = {{ top: 20, right: drawdown ? (compact ? 16 : 28) : (compact ? 58 : 70), bottom: 48, left: 68 }};
      const innerWidth = width - margin.left - margin.right;
      const innerHeight = height - margin.top - margin.bottom;
      const activeEquities = equitySeries.filter(s => visible.has(s.key));
      const active = drawdown
        ? activeEquities
        : [...activeEquities, ...(visible.has(priceSeries.key) ? [priceSeries] : [])];
      const svg = d3.select(container).selectAll('svg').data([null]).join('svg')
        .attr('viewBox', `0 0 ${{width}} ${{height}}`).attr('height', height).attr('role', 'img')
        .attr('aria-label', drawdown ? 'A 至 E 策略回撤曲线' : 'A 至 E 策略资金曲线与 P 价格曲线');
      svg.selectAll('*').remove();
      svg.append('title').text(drawdown ? '策略回撤' : '策略权益与 BTCUSDT 价格');
      const g = svg.append('g').attr('transform', `translate(${{margin.left}},${{margin.top}})`);
      const xExtent = d3.extent(data, d => d.date);
      const xPad = (xExtent[1] - xExtent[0]) * 0.01;
      const x = d3.scaleTime().domain([new Date(+xExtent[0] - xPad), new Date(+xExtent[1] + xPad)]).range([0, innerWidth]);
      const values = activeEquities.flatMap(s => data.map(d => drawdown ? d.dd[s.key] : d[s.key]));
      const extent = d3.extent(values);
      const y = drawdown
        ? d3.scaleLinear().domain([Math.min(extent[0] * 1.08, -0.02), 0.015]).nice().range([innerHeight, 0])
        : d3.scaleLog().domain([Math.max(extent[0] * 0.88, 1), extent[1] * 1.12]).range([innerHeight, 0]);
      const priceExtent = d3.extent(data, d => d.p);
      const priceY = d3.scaleLog().domain([priceExtent[0] * 0.88, priceExtent[1] * 1.12]).range([innerHeight, 0]);
      const equityTicks = [10000, 20000, 50000, 100000, 200000, 500000]
        .filter(value => value >= y.domain()[0] && value <= y.domain()[1]);
      const priceTicks = [5000, 10000, 20000, 50000, 100000, 200000]
        .filter(value => value >= priceY.domain()[0] && value <= priceY.domain()[1]);

      g.append('rect').attr('data-chart-frame', '').attr('width', innerWidth).attr('height', innerHeight);
      const clipId = `${{drawdown ? 'dd' : 'eq'}}-clip-${{Math.round(width)}}`;
      svg.append('defs').append('clipPath').attr('id', clipId).append('rect').attr('width', innerWidth).attr('height', innerHeight);
      const gridAxis = d3.axisLeft(y).tickSize(-innerWidth).tickFormat('');
      if (drawdown) gridAxis.ticks(compact ? 4 : 6); else gridAxis.tickValues(equityTicks);
      g.append('g').attr('class', 'grid').call(gridAxis);
      g.append('g').attr('class', 'axis').attr('transform', `translate(0,${{innerHeight}})`)
        .call(d3.axisBottom(x).ticks(compact ? 4 : 7).tickFormat(d3.timeFormat('%Y')));
      const leftAxis = d3.axisLeft(y).tickFormat(drawdown ? d3.format('.0%') : d => d3.format('~s')(d));
      if (drawdown) leftAxis.ticks(compact ? 4 : 6); else leftAxis.tickValues(equityTicks);
      g.append('g').attr('class', 'axis').call(leftAxis);
      if (!drawdown && visible.has(priceSeries.key)) {{
        g.append('g').attr('class', 'axis').attr('transform', `translate(${{innerWidth}},0)`)
          .call(d3.axisRight(priceY).tickValues(priceTicks).tickFormat(d => d3.format('~s')(d)));
      }}
      g.append('text').attr('class', 'axis-title').attr('data-axis', 'x').attr('x', innerWidth / 2).attr('y', innerHeight + 40).attr('text-anchor', 'middle').text('日期（UTC）');
      g.append('text').attr('class', 'axis-title').attr('data-axis', 'y').attr('transform', 'rotate(-90)').attr('x', -innerHeight / 2).attr('y', -52).attr('text-anchor', 'middle').text(drawdown ? '回撤（%）' : '账户权益（USDT，对数）');
      if (!drawdown && visible.has(priceSeries.key)) {{
        g.append('text').attr('class', 'axis-title').attr('data-axis', 'y-price')
          .attr('x', innerWidth).attr('y', -7).attr('text-anchor', 'end').text('P（USDT，对数）');
      }}

      const yValue = (row, s) => s.axis === 'price' ? priceY(row[s.key]) : y(drawdown ? row.dd[s.key] : row[s.key]);
      const line = s => d3.line().x(d => x(d.date)).y(d => yValue(d, s))(data);
      const paths = g.append('g').attr('clip-path', `url(#${{clipId}})`);
      active.forEach(s => paths.append('path').attr('class', drawdown ? 'drawdown-line' : (s.axis === 'price' ? 'price-line' : 'series-line')).attr('stroke', s.color).attr('d', line(s)));

      const guide = g.append('line').attr('data-chart-hover-guide', '').attr('y1', 0).attr('y2', innerHeight).style('display', 'none');
      const markerLayer = g.append('g');
      const overlay = g.append('rect').attr('data-chart-hit', '').attr('data-chart-hover-overlay', 'cross-series')
        .attr('width', innerWidth).attr('height', innerHeight).attr('fill', 'transparent').style('cursor', 'crosshair');
      const showHover = event => {{
        const [px] = d3.pointer(event, overlay.node());
        const date = x.invert(px);
        guide.attr('x1', px).attr('x2', px).style('display', null);
        markerLayer.selectAll('[data-chart-hover-marker]').data(active, d => d.key).join('circle')
          .attr('data-chart-hover-marker', '').attr('r', 4).attr('fill', d => d.color)
          .attr('cx', px).attr('cy', d => d.axis === 'price' ? priceY(interpolate(date, d.key, false)) : y(interpolate(date, d.key, drawdown)));
        const rows = active.map(s => {{
          const value = interpolate(date, s.key, drawdown);
          return `<div class="tooltip-row"><span class="tooltip-name"><span class="tooltip-dot" style="background:${{s.color}}"></span>${{s.name}}</span><strong>${{drawdown ? formatPct(value) : formatMoney(value) + ' USDT'}}</strong></div>`;
        }}).join('');
        tooltip.html(`<div>${{formatDate(date)}}</div>${{rows}}`).style('display', 'block');
        const rootRect = root.getBoundingClientRect();
        const tip = tooltip.node().getBoundingClientRect();
        const left = Math.min(Math.max(event.clientX - rootRect.left + 12, 4), rootRect.width - tip.width - 4);
        const top = event.clientY - rootRect.top - tip.height - 12;
        tooltip.style('left', `${{left}}px`).style('top', `${{Math.max(top, 4)}}px`);
      }};
      overlay.on('pointermove mousemove click', showHover).on('pointerleave mouseleave', () => {{
        guide.style('display', 'none');
        markerLayer.selectAll('*').remove();
        tooltip.style('display', 'none');
      }});
    }}

    function draw() {{
      chart(root.querySelector('[data-plot="equity"]'), false);
      chart(root.querySelector('[data-plot="drawdown"]'), true);
    }}
    draw();
    new ResizeObserver(draw).observe(root);
  }})();
  </script>
</div>
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--preview-theme", choices=["auto", "light", "dark"], default="auto")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fragment = render_fragment(chart_rows())
    args.output.write_text(fragment, encoding="utf-8")
    if args.preview:
        dark_tokens = (
            "--background: #171a21; --foreground: #f4f4f5; --popover: #20242d; "
            "--popover-foreground: #f4f4f5; --border: #555b66;"
        )
        root_tokens = dark_tokens if args.preview_theme == "dark" else (
            "--background: #ffffff; --foreground: #171a21; --popover: #ffffff; "
            "--popover-foreground: #171a21; --border: #c9ced8;"
        )
        automatic_dark = "" if args.preview_theme != "auto" else f'''
@media (prefers-color-scheme: dark) {{
  :root {{ {dark_tokens} }}
}}'''
        preview = f'''<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {{
  {root_tokens}
  --viz-series-1: #3b82c4; --viz-series-2: #e58a3b;
  --viz-series-3: #3ca66b; --viz-series-4: #d45b57; --viz-series-5: #0f766e; --viz-series-6: #7b61b8;
}}
{automatic_dark}
body {{ margin: 20px; background: var(--background); }}
</style>
{fragment}'''
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        args.preview.write_text(preview, encoding="utf-8")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
