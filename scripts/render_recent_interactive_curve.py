#!/usr/bin/env python3
"""Create the thread-scoped interactive recent-period curve fragment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "reports/recent_2026_07_01_2026_08_25/equity_and_btc.csv"
DEFAULT_OUTPUT = ROOT / "reports/recent_2026_07_01_2026_08_25/recent-btc-curves.html"


def load_rows(path: Path) -> list[list[float | int]]:
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True)
    legacy = {"A": "V1", "B": "V2", "C": "V3", "D": "V4", "E": "V5"}
    frame = frame.rename(columns={key: value for key, value in legacy.items() if key in frame.columns})
    frame = frame.dropna(subset=["P"])
    return [
        [int(ts.timestamp() * 1000), *[round(float(row[key]), 4) for key in ["V1", "V2", "V3", "V4", "V5", "P"]]]
        for ts, row in frame.iterrows()
    ]


def render(rows: list[list[float | int]]) -> str:
    raw = json.dumps(rows, separators=(",", ":"))
    start = pd.to_datetime(rows[0][0], unit="ms", utc=True)
    end = pd.to_datetime(rows[-1][0], unit="ms", utc=True)
    date_label = f"{start:%Y-%m-%d} 至 {end:%Y-%m-%d}"
    return f'''<div id="btc-recent-curves">
  <style>
    #btc-recent-curves {{ position: relative; width: 100%; color: var(--foreground); font-family: ui-sans-serif, system-ui, sans-serif; }}
    #btc-recent-curves h2 {{ margin: 0 0 8px; font-weight: 500; }}
    #btc-recent-curves .legend {{ display: flex; flex-wrap: wrap; gap: 4px 18px; margin: 0 0 10px; }}
    #btc-recent-curves .legend button {{ display: inline-flex; align-items: center; gap: 7px; padding: 3px 0; border: 0; background: transparent; color: var(--foreground); font: inherit; cursor: pointer; }}
    #btc-recent-curves .legend button[aria-pressed="false"] {{ opacity: .42; }}
    #btc-recent-curves .swatch {{ width: 18px; height: 2px; }}
    #btc-recent-curves .plot {{ width: 100%; }}
    #btc-recent-curves svg {{ display: block; width: 100%; overflow: visible; }}
    #btc-recent-curves .axis text, #btc-recent-curves .axis-title {{ fill: var(--foreground); font-size: 12px; }}
    #btc-recent-curves .axis path, #btc-recent-curves .axis line {{ stroke: var(--border); }}
    #btc-recent-curves .grid line {{ stroke: var(--border); stroke-opacity: .45; }}
    #btc-recent-curves .grid path {{ display: none; }}
    #btc-recent-curves [data-chart-frame] {{ fill: transparent; stroke: var(--border); }}
    #btc-recent-curves .series-line, #btc-recent-curves .price-line, #btc-recent-curves .drawdown-line {{ fill: none; stroke-width: 1.2; }}
    #btc-recent-curves [data-chart-hover-guide] {{ stroke: var(--foreground); stroke-opacity: .35; stroke-dasharray: 3 3; pointer-events: none; }}
    #btc-recent-curves [data-chart-hover-marker] {{ stroke: var(--popover); stroke-width: 1.5; pointer-events: none; }}
    #btc-recent-curves .tooltip {{ position: absolute; z-index: 10; display: none; min-width: 176px; padding: 8px 10px; border: 1px solid var(--border); background: var(--popover); color: var(--popover-foreground); font-size: 12px; pointer-events: none; }}
    #btc-recent-curves .tooltip-row {{ display: flex; justify-content: space-between; gap: 16px; }}
    #btc-recent-curves .tooltip-name {{ display: inline-flex; align-items: center; gap: 6px; }}
    #btc-recent-curves .tooltip-dot {{ width: 8px; height: 8px; border-radius: 50%; }}
  </style>
  <h2>BTCUSDT 近期回测（{date_label}）：V1–V5 策略与 P 价格</h2>
  <div class="legend" aria-label="曲线图例"></div>
  <div class="plot" data-plot="equity"></div>
  <div class="plot" data-plot="drawdown"></div>
  <div class="tooltip" role="tooltip"></div>
  <script src="https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"></script>
  <script>
  (() => {{
    const root = document.getElementById('btc-recent-curves');
    const raw = {raw};
    const equitySeries = [
      {{ key: 'V1', name: 'V1 基础趋势跟随与 ATR 仓位', color: 'var(--viz-series-1)', axis: 'equity' }},
      {{ key: 'V2', name: 'V2 资金费率拥挤过滤趋势', color: 'var(--viz-series-2)', axis: 'equity' }},
      {{ key: 'V3', name: 'V3 波动率与下行风险自适应', color: 'var(--viz-series-3)', axis: 'equity' }},
      {{ key: 'V4', name: 'V4 稳健长多趋势-反弹混合', color: 'var(--viz-series-4)', axis: 'equity' }},
      {{ key: 'V5', name: 'V5 谨慎对称趋势与空头确认', color: 'var(--viz-series-5)', axis: 'equity' }}
    ];
    const priceSeries = {{ key: 'P', name: 'P BTCUSDT 价格', color: 'var(--viz-series-6)', axis: 'price' }};
    const allSeries = [...equitySeries, priceSeries];
    const visible = new Set(allSeries.map(d => d.key));
    const data = raw.map(d => ({{ date: new Date(d[0]), V1: d[1], V2: d[2], V3: d[3], V4: d[4], V5: d[5], P: d[6] }}));
    const peaks = Object.fromEntries(equitySeries.map(s => [s.key, -Infinity]));
    data.forEach(row => {{ row.dd = {{}}; equitySeries.forEach(s => {{ peaks[s.key] = Math.max(peaks[s.key], row[s.key]); row.dd[s.key] = row[s.key] / peaks[s.key] - 1; }}); }});
    const legend = d3.select(root).select('.legend');
    legend.selectAll('button').data(allSeries).join('button')
      .attr('type', 'button').attr('aria-pressed', 'true')
      .html(d => `<span class="swatch" style="background:${{d.color}}"></span><span>${{d.name}}</span>`)
      .on('click', function(event, d) {{
        if (d.axis === 'equity' && visible.has(d.key) && equitySeries.filter(s => visible.has(s.key)).length === 1) return;
        if (visible.has(d.key)) visible.delete(d.key); else visible.add(d.key);
        d3.select(this).attr('aria-pressed', visible.has(d.key) ? 'true' : 'false');
        drawAll();
      }});
    const tooltip = d3.select(root).select('.tooltip');
    const fmtDate = d3.timeFormat('%Y-%m-%d %H:%M');
    const fmtMoney = d3.format(',.0f');
    const fmtPrice = d3.format(',.0f');
    const fmtPct = d3.format('.1%');
    function interpolate(date, key, drawdown) {{
      const index = d3.bisector(d => d.date).center(data, date);
      const i0 = Math.max(0, Math.min(data.length - 2, index));
      const a = data[i0], b = data[i0 + 1];
      const t = Math.max(0, Math.min(1, (date - a.date) / Math.max(b.date - a.date, 1)));
      const av = drawdown ? a.dd[key] : a[key], bv = drawdown ? b.dd[key] : b[key];
      return av + (bv - av) * t;
    }}
    function drawChart(container, drawdown) {{
      const width = Math.max(container.getBoundingClientRect().width, 320);
      const compact = width < 520;
      const height = drawdown ? (compact ? 205 : 230) : (compact ? 285 : 350);
      const margin = {{ top: 20, right: drawdown ? 16 : (compact ? 58 : 70), bottom: 50, left: 68 }};
      const innerWidth = width - margin.left - margin.right, innerHeight = height - margin.top - margin.bottom;
      const activeEquities = equitySeries.filter(s => visible.has(s.key));
      const active = drawdown ? activeEquities : [...activeEquities, ...(visible.has('P') ? [priceSeries] : [])];
      const svg = d3.select(container).selectAll('svg').data([null]).join('svg')
        .attr('viewBox', `0 0 ${{width}} ${{height}}`).attr('height', height).attr('role', 'img')
        .attr('aria-label', drawdown ? 'V1 至 V5 策略回撤曲线' : 'V1 至 V5 策略资金曲线及 BTCUSDT 价格');
      svg.selectAll('*').remove();
      svg.append('title').text(drawdown ? '策略回撤' : '策略权益与 BTCUSDT 价格');
      const g = svg.append('g').attr('transform', `translate(${{margin.left}},${{margin.top}})`);
      const xExtent = d3.extent(data, d => d.date);
      const xPad = Math.max((xExtent[1] - xExtent[0]) * .01, 1);
      const x = d3.scaleTime().domain([new Date(+xExtent[0] - xPad), new Date(+xExtent[1] + xPad)]).range([0, innerWidth]);
      const equityValues = activeEquities.flatMap(s => data.map(d => drawdown ? d.dd[s.key] : d[s.key]));
      const eExtent = d3.extent(equityValues);
      const y = drawdown
        ? d3.scaleLinear().domain([Math.min(eExtent[0] * 1.08, -.01), .01]).nice().range([innerHeight, 0])
        : d3.scaleLinear().domain([Math.max(0, eExtent[0] * .98), eExtent[1] * 1.02]).nice().range([innerHeight, 0]);
      const pExtent = d3.extent(data, d => d.P);
      const priceY = d3.scaleLinear().domain([pExtent[0] * .98, pExtent[1] * 1.02]).nice().range([innerHeight, 0]);
      const xTickValues = compact
        ? [0, Math.floor((data.length - 1) / 3), Math.floor(2 * (data.length - 1) / 3), data.length - 1].map(i => data[i].date)
        : null;
      g.append('rect').attr('data-chart-frame', '').attr('width', innerWidth).attr('height', innerHeight);
      const clipId = `recent-${{drawdown ? 'dd' : 'eq'}}-${{Math.round(width)}}`;
      svg.append('defs').append('clipPath').attr('id', clipId).append('rect').attr('width', innerWidth).attr('height', innerHeight);
      const grid = d3.axisLeft(y).ticks(compact ? 4 : 6).tickSize(-innerWidth).tickFormat('');
      g.append('g').attr('class', 'grid').call(grid);
      const xAxis = d3.axisBottom(x).tickFormat(d3.timeFormat('%m-%d'));
      if (xTickValues) xAxis.tickValues(xTickValues); else xAxis.ticks(7);
      g.append('g').attr('class', 'axis').attr('transform', `translate(0,${{innerHeight}})`).call(xAxis);
      g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(compact ? 4 : 6).tickFormat(drawdown ? d3.format('.0%') : d3.format(',.0f')));
      if (!drawdown && visible.has('P')) g.append('g').attr('class', 'axis').attr('transform', `translate(${{innerWidth}},0)`).call(d3.axisRight(priceY).ticks(compact ? 4 : 6).tickFormat(d3.format(',.0f')));
      g.append('text').attr('class', 'axis-title').attr('data-axis', 'x').attr('x', innerWidth / 2).attr('y', innerHeight + 42).attr('text-anchor', 'middle').text('日期（UTC）');
      g.append('text').attr('class', 'axis-title').attr('data-axis', 'y').attr('transform', 'rotate(-90)').attr('x', -innerHeight / 2).attr('y', -51).attr('text-anchor', 'middle').text(drawdown ? '回撤（%）' : '账户权益（USDT）');
      if (!drawdown && visible.has('P')) g.append('text').attr('class', 'axis-title').attr('data-axis', 'y-price').attr('x', innerWidth).attr('y', -6).attr('text-anchor', 'end').text('P 价格（USDT）');
      const yValue = (row, series) => series.axis === 'price' ? priceY(row.P) : y(drawdown ? row.dd[series.key] : row[series.key]);
      const line = series => d3.line().x(d => x(d.date)).y(d => yValue(d, series))(data);
      const layer = g.append('g').attr('clip-path', `url(#${{clipId}})`);
      active.forEach(series => layer.append('path').attr('class', drawdown ? 'drawdown-line' : (series.axis === 'price' ? 'price-line' : 'series-line')).attr('stroke', series.color).attr('d', line(series)));
      const guide = g.append('line').attr('data-chart-hover-guide', '').attr('y1', 0).attr('y2', innerHeight).style('display', 'none');
      const markers = g.append('g');
      const overlay = g.append('rect').attr('data-chart-hit', '').attr('data-chart-hover-overlay', 'cross-series').attr('width', innerWidth).attr('height', innerHeight).attr('fill', 'transparent').style('cursor', 'crosshair');
      const showHover = event => {{
        const [px] = d3.pointer(event, overlay.node()); const date = x.invert(px);
        guide.attr('x1', px).attr('x2', px).style('display', null);
        markers.selectAll('[data-chart-hover-marker]').data(active, d => d.key).join('circle').attr('data-chart-hover-marker', '').attr('r', 4).attr('fill', d => d.color).attr('cx', px).attr('cy', d => yValue({{P: interpolate(date, 'P', false), dd: Object.fromEntries(equitySeries.map(s => [s.key, interpolate(date, s.key, true)])), ...Object.fromEntries(equitySeries.map(s => [s.key, interpolate(date, s.key, false)]))}}, d));
        const rows = active.map(s => {{ const value = interpolate(date, s.key, drawdown); const text = drawdown ? fmtPct(value) : (s.axis === 'price' ? fmtPrice(value) + ' USDT' : fmtMoney(value) + ' USDT'); return `<div class="tooltip-row"><span class="tooltip-name"><span class="tooltip-dot" style="background:${{s.color}}"></span>${{s.name}}</span><strong>${{text}}</strong></div>`; }}).join('');
        tooltip.html(`<div>${{fmtDate(date)}} UTC</div>${{rows}}`).style('display', 'block');
        const rr = root.getBoundingClientRect(), tr = tooltip.node().getBoundingClientRect();
        tooltip.style('left', `${{Math.min(Math.max(event.clientX - rr.left + 12, 4), rr.width - tr.width - 4)}}px`).style('top', `${{Math.max(event.clientY - rr.top - tr.height - 12, 4)}}px`);
      }};
      overlay.on('pointermove mousemove click', showHover).on('pointerleave mouseleave', () => {{ guide.style('display', 'none'); markers.selectAll('*').remove(); tooltip.style('display', 'none'); }});
    }}
    function drawAll() {{ drawChart(root.querySelector('[data-plot="equity"]'), false); drawChart(root.querySelector('[data-plot="drawdown"]'), true); }}
    drawAll();
    new ResizeObserver(drawAll).observe(root);
  }})();
  </script>
</div>
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # A BOM lets browsers decode this standalone fragment as UTF-8 when served
    # without an HTTP charset header.
    args.output.write_text(render(load_rows(args.input)), encoding="utf-8-sig")
    print(args.output)


if __name__ == "__main__":
    main()
