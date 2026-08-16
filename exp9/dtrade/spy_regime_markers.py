#!/usr/bin/env python3
"""
SPY 均线斜率区间标注
====================

标记两种空头/偏空区间（背景阴影）：
  1. EMA200 斜率 < 0.01   （EMA200走平/下行 → 长期趋势偏空）
  2. EMA50  斜率 < 0       （EMA50下行 → 中期趋势走弱）

区间内的起止点用三角箭头标注。
"""

import json
import math
from pathlib import Path

KLINES_DIR = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines')
OUTPUT_HTML = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spy_regime_markers.html')


# ═══════════════════════════════════════
#  数据 & 指标
# ═══════════════════════════════════════

def calc_ema(prices, period):
    if len(prices) < period:
        return [None] * len(prices)
    k = 2 / (period + 1)
    result = [None] * (period - 1)
    result.append(prices[period - 1])
    for i in range(period, len(prices)):
        result.append(prices[i] * k + result[-1] * (1 - k))
    return result


def load_data():
    with open(KLINES_DIR / 'SPY_1d.json') as f:
        bars = json.load(f)['data']
    return bars


def build_records(bars):
    closes = [b['close'] for b in bars]
    dates  = [b['date'] for b in bars]

    e20  = calc_ema(closes, 20)
    e50  = calc_ema(closes, 50)
    e200 = calc_ema(closes, 200)

    # 5日斜率（同 e20_slope 逻辑）
    def slope(ema_arr, lookback=5):
        s = [None] * len(prices)
        for i in range(lookback, len(prices)):
            if ema_arr[i - lookback] and ema_arr[i] and ema_arr[i - lookback] > 0:
                s[i] = ema_arr[i] / ema_arr[i - lookback] - 1
        return s

    prices = closes
    e50_slope  = slope(e50)
    e200_slope = slope(e200)

    records = []
    for i, bar in enumerate(bars):
        records.append({
            'date':       dates[i],
            'open':       bar.get('open', bar['close']),
            'high':       bar['high'],
            'low':        bar['low'],
            'close':      closes[i],
            'ema20':      e20[i],
            'ema50':      e50[i],
            'ema200':     e200[i],
            'e20_slope':  0.0,  # placeholder
            'e50_slope':  e50_slope[i],
            'e200_slope': e200_slope[i],
        })
    return records


# ═══════════════════════════════════════
#  区间检测
# ═══════════════════════════════════════

def detect_periods(records, condition_fn, label_prefix):
    """
    找出所有连续满足 condition_fn 的区间。
    返回: [{'start': date, 'end': date, 'label': str}, ...]
    """
    periods = []
    in_period = False
    start_date = None

    for r in records:
        if condition_fn(r):
            if not in_period:
                in_period = True
                start_date = r['date']
        else:
            if in_period:
                periods.append({'start': start_date, 'end': r['date']})
                in_period = False
                start_date = None

    if in_period and records:
        periods.append({'start': start_date, 'end': records[-1]['date']})

    return periods


def e200_flat(r):
    """EMA200 斜率 < 0.01  → 长期趋势偏空/走平（排除 None）"""
    s = r['e200_slope']
    return s is not None and s < 0.01


def e50_down(r):
    """EMA50 斜率 < 0  → 中期趋势下行（排除 None）"""
    s = r['e50_slope']
    return s is not None and s < 0


# ═══════════════════════════════════════
#  构建 HTML markers & 区间
# ═══════════════════════════════════════

def build_markers_and_regions(records):
    periods_e200 = detect_periods(records, e200_flat, 'EMA200走平')
    periods_e50  = detect_periods(records, e50_down,  'EMA50下行')

    markers = []
    regions = []

    for p in periods_e200:
        # 区间起止 arrows
        markers.append({
            'time':     p['start'],
            'position': 'aboveBar',
            'color':    '#DA70D6',
            'shape':    'arrowDown',
            'text':     f"📉 EMA200走平 → {p['start']}",
        })
        markers.append({
            'time':     p['end'],
            'position': 'belowBar',
            'color':    '#DA70D6',
            'shape':    'arrowUp',
            'text':     f"↗ EMA200恢复 → {p['end']}",
        })
        regions.append({
            'start': p['start'],
            'end':   p['end'],
            'color': 'rgba(214,112,214,0.08)',
            'label': 'EMA200<0.01',
        })

    for p in periods_e50:
        markers.append({
            'time':     p['start'],
            'position': 'aboveBar',
            'color':    '#00BFFF',
            'shape':    'arrowDown',
            'text':     f"📉 EMA50下行 → {p['start']}",
        })
        markers.append({
            'time':     p['end'],
            'position': 'belowBar',
            'color':    '#00BFFF',
            'shape':    'arrowUp',
            'text':     f"↗ EMA50恢复 → {p['end']}",
        })
        regions.append({
            'start': p['start'],
            'end':   p['end'],
            'color': 'rgba(0,191,255,0.08)',
            'label': 'EMA50<0',
        })

    return markers, regions, periods_e200, periods_e50


# ═══════════════════════════════════════
#  HTML
# ═══════════════════════════════════════

def build_html(records, markers, regions, p_e200, p_e50):
    candles = [{'time': r['date'], 'open': r['open'], 'high': r['high'],
                'low': r['low'], 'close': r['close']} for r in records]

    def ema_line(field):
        return [{'time': records[i]['date'], 'value': records[i][field]}
                for i in range(len(records)) if records[i][field] is not None]

    # 背景区间 → 用 PriceRange + LineSeries 实现
    # 为每个区间创建两条线（上轨=区间最高，下轨=区间最低），fillBetweenTiles=true
    region_lines = []
    for idx, reg in enumerate(regions):
        hi_line = [{'time': reg['start'], 'value': None}, {'time': reg['end'], 'value': None}]
        lo_line = [{'time': reg['start'], 'value': None}, {'time': reg['end'], 'value': None}]
        # 稍后用 setData 在 chart 上叠加；这里先记录起止时间
        region_lines.append({'start': reg['start'], 'end': reg['end'], 'color': reg['color']})

    lc_path = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/dtrade/lightweight-charts.js')
    lc_lib  = open(lc_path).read() if lc_path.exists() else ''

    def fmt_p(v): return f"{v*100:.2f}%" if v is not None else "N/A"

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>SPY 均线斜率区间标注</title>
<script>{lc_lib}</script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;overflow:hidden}}
.header{{padding:10px 16px;background:#161b22;border-bottom:1px solid #30363d;display:flex;align-items:center;gap:20px;flex-wrap:wrap}}
.title{{font-size:20px;font-weight:700;color:#58a6ff}}
.meta{{color:#8b949e;font-size:12px}}
.legend{{display:flex;gap:12px;font-size:11px;flex-wrap:wrap}}
.legend span{{display:flex;align-items:center;gap:5px}}
.dot{{width:12px;height:3px;border-radius:2px;display:inline-block}}
#chart{{width:100vw;height:calc(100vh - 60px)}}
.counts{{color:#8b949e;font-size:11px}}
</style>
</head>
<body>
<div class="header">
  <span class="title">SPY 均线斜率区间标注</span>
  <span class="meta">{records[0]['date']} ~ {records[-1]['date']} · {len(records)}天</span>
  <div class="legend">
    <span><span class="dot" style="background:#DA70D6"></span> EMA200斜率&lt;0.01（{len(p_e200)}段）</span>
    <span><span class="dot" style="background:#00BFFF"></span> EMA50斜率&lt;0（{len(p_e50)}段）</span>
  </div>
</div>
<div id="chart"></div>

<script>
const candles = {json.dumps(candles)};
const ema20  = {json.dumps(ema_line('ema20'))};
const ema50  = {json.dumps(ema_line('ema50'))};
const ema200 = {json.dumps(ema_line('ema200'))};
const markers = {json.dumps(markers)};
const regionLines = {json.dumps(region_lines)};

const chart = LightweightCharts.createChart(document.getElementById('chart'),{{
  layout:{{background:{{color:'#0d1117'}},textColor:'#e6edf3'}},
  grid:{{vertLines:{{color:'#21262d'}},horzLines:{{color:'#21262d'}}}},
  width: window.innerWidth,
  height: window.innerHeight - 60,
  timeScale:{{timeVisible:true,secondsVisible:false,borderColor:'#30363d'}},
  rightPrice:{{borderColor:'#30363d'}},
}});

const cs = chart.addCandlestickSeries({{
  upColor:'#26a69a',downColor:'#ef5350',
  borderUpColor:'#26a69a',borderDownColor:'#ef5350',
  wickUpColor:'#26a69a',wickDownColor:'#ef5350',
}});
cs.setData(candles);
cs.setMarkers(markers);

// ── 背景区间（用横线段模拟）──
regionLines.forEach((reg, idx) => {{
  // 找到区间内所有 bar 的 high 和 low 范围
  const hiData = candles
    .filter(c => c.time >= reg.start && c.time <= reg.end)
    .map(c => ({{time: c.time, value: c.high + 2}}));
  const loData = candles
    .filter(c => c.time >= reg.start && c.time <= reg.end)
    .map(c => ({{time: c.time, value: c.low - 2}}));

  if (hiData.length === 0) return;

  const upperSeries = chart.addLineSeries({{
    color: reg.color.replace('0.07', '0.15'),
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
    fillBetweenAreas: true,
    areaStyle: {{ topColor: reg.color.replace('0.07', '0.12'), bottomColor: reg.color, lineWidth: 0 }},
  }});

  const lowerSeries = chart.addLineSeries({{
    color: 'transparent',
    lineWidth: 0,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
    fillBetweenAreas: false,
  }});

  // 用 upper 的 area fill 来模拟区间背景
  // 由于 fillBetweenAreas 需要两条线，我们直接用一条线的 areaStyle
  chart.addAreaSeries({{
    color: reg.color,
    lineWidth: 0,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
    topColor: reg.color,
    bottomColor: reg.color,
  }}).setData(hiData.map(d => ({{time: d.time, value: d.value}})));
}});

// ── EMA 线 ──
const L = (color) => ({{color, lineWidth:1, priceLineVisible:false, lastValueVisible:false, crosshairMarkerVisible:false}});
chart.addLineSeries({{...L('#FF6B35'),title:'EMA20'}}).setData(ema20.filter(d=>d.value!==null));
chart.addLineSeries({{...L('#00BFFF'),title:'EMA50'}}).setData(ema50.filter(d=>d.value!==null));
chart.addLineSeries({{...L('#DA70D6'),title:'EMA200'}}).setData(ema200.filter(d=>d.value!==null));

chart.timeScale().fitContent();
window.addEventListener('resize',()=>{{ chart.resize(window.innerWidth, window.innerHeight - 60); }});
</script>
</body>
</html>"""


# ═══════════════════════════════════════
#  主程序
# ═══════════════════════════════════════

def main():
    print('=' * 60)
    print('  SPY 均线斜率区间标注')
    print('=' * 60)

    bars    = load_data()
    records = build_records(bars)
    print(f'  数据: {len(records)} 天 | {records[0]["date"]} ~ {records[-1]["date"]}')

    markers, regions, p_e200, p_e50 = build_markers_and_regions(records)

    print(f'\n  EMA200 斜率 < 0.01: {len(p_e200)} 个区间')
    for p in p_e200:
        print(f'    {p["start"]} ~ {p["end"]}')

    print(f'\n  EMA50 斜率 < 0: {len(p_e50)} 个区间')
    for p in p_e50:
        print(f'    {p["start"]} ~ {p["end"]}')

    print(f'\n  总 markers: {len(markers)} 个')
    print(f'  总 regions: {len(regions)} 个')

    html = build_html(records, markers, regions, p_e200, p_e50)
    with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'\n  ✅ HTML: {OUTPUT_HTML}')

    # 保存区间 JSON
    out_json = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spy_regime_periods.json')
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump({'e200_flat': p_e200, 'e50_down': p_e50, 'records_count': len(records)}, f, ensure_ascii=False, indent=2)
    print(f'  ✅ JSON: {out_json}')


if __name__ == '__main__':
    main()
