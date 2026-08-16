#!/usr/bin/env python3
"""
SPY 波段顶底信号扫描器 v3
========================

基于真实历史数据特征设计的阈值：

TOP（火顶）信号条件（OR逻辑，满足任一即触发）：
  A. D20 > 4%  AND RSI > 65
  B. D20 > 3%  AND RSI > 72
  C. D20 > 6%

BOTTOM（恐慌底）信号条件（AND逻辑）：
  A. RSI < 32
  B. D200 < -8%  OR D50 < -5%
  C. 实体阳线（is_bullish=true）且下影线 > 0.5 * body

波段操作信号：
  BUY（回踩买入）：收盘从 EMA20 下方站上 AND 前一天RSI<45 AND 阳线
  SELL（乖离卖出）：D20 > 5% AND RSI > 68
  GC：EMA20 上穿 EMA50
  GD：EMA20 下穿 EMA50
"""

import json
import math
from pathlib import Path

PROJECT_ROOT = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9')
KLINES_DIR   = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines')
OUTPUT_HTML  = PROJECT_ROOT / 'spy_swing_analysis_v3.html'


# ═══════════════════════════════════════
#  指标计算
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


def calc_sma(values, period):
    if len(values) < period:
        return [None] * len(values)
    result = [None] * (period - 1)
    for i in range(period - 1, len(values)):
        result.append(sum(values[i - period + 1:i + 1]) / period)
    return result


def calc_atr(highs, lows, closes, period=20):
    trs = [None]
    for i in range(1, len(highs)):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        trs.append(max(hl, hc, lc))
    sma = calc_sma([t for t in trs if t is not None], period)
    out = [None] * len(trs)
    offset = len(trs) - len(sma)
    for i, v in enumerate(sma):
        out[i + offset] = v
    return out


def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return [None] * len(prices)
    gains = [0.0]
    losses = [0.0]
    for i in range(1, len(prices)):
        delta = prices[i] - prices[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    rsis = [None] * (period + 1)
    if avg_loss == 0:
        rsis.append(100)
    else:
        rsis.append(100 - 100 / (1 + avg_gain / avg_loss))
    for i in range(period + 1, len(prices)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsis.append(100)
        else:
            rsis.append(100 - 100 / (1 + avg_gain / avg_loss))
    return rsis


def calc_bbands(prices, period=20, std_dev=2):
    sma = calc_sma(prices, period)
    std = [None] * (period - 1)
    for i in range(period - 1, len(prices)):
        slice_p = prices[i - period + 1:i + 1]
        m = sma[i]
        variance = sum((p - m) ** 2 for p in slice_p) / period
        std.append(math.sqrt(variance))
    upper = [None if sma[i] is None else sma[i] + std_dev * std[i] for i in range(len(prices))]
    lower = [None if sma[i] is None else sma[i] - std_dev * std[i] for i in range(len(prices))]
    return upper, sma, lower


# ═══════════════════════════════════════
#  数据加载 & 指标构建
# ═══════════════════════════════════════

def load_and_build():
    with open(KLINES_DIR / 'SPY_1d.json') as f:
        bars = json.load(f)['data']

    highs   = [b['high'] for b in bars]
    lows    = [b['low'] for b in bars]
    closes  = [b['close'] for b in bars]
    dates   = [b['date'] for b in bars]
    # 字段名是 vol 不是 volume
    vols    = [b.get('vol', 0) for b in bars]

    e5   = calc_ema(closes, 5)
    e20  = calc_ema(closes, 20)
    e50  = calc_ema(closes, 50)
    e100 = calc_ema(closes, 100)
    e200 = calc_ema(closes, 200)

    atr20 = calc_atr(highs, lows, closes, 20)
    rsi14 = calc_rsi(closes, 14)
    bb_upper, bb_mid, bb_lower = calc_bbands(closes, 20, 2)

    # EMA20 5天前斜率
    e20_slope = [0.0] * len(closes)
    for i in range(5, len(closes)):
        if e20[i - 5] and e20[i] and e20[i - 5] > 0:
            e20_slope[i] = e20[i] / e20[i - 5] - 1

    # 成交量MA20
    vol_ma20 = calc_sma(vols, 20)

    records = []
    for i, bar in enumerate(bars):
        c, o, l, h = closes[i], bar.get('open', bar['close']), lows[i], highs[i]
        v = vols[i]

        d20  = (c - e20[i])  / e20[i]  if e20[i]  and e20[i]  != 0 else 0.0
        d50  = (c - e50[i])  / e50[i]  if e50[i]  and e50[i]  != 0 else 0.0
        d200 = (c - e200[i]) / e200[i] if e200[i] and e200[i] != 0 else 0.0

        body     = abs(c - o)
        # 上影线：high - max(close, open)
        upper_sh = h - max(c, o)
        # 下影线：min(close, open) - low
        lower_sh = min(c, o) - l
        lower_sh = max(lower_sh, 0)  # 确保非负

        bbp = 0.5
        if bb_lower[i] is not None and bb_upper[i] is not None:
            band_range = bb_upper[i] - bb_lower[i]
            if band_range > 0:
                bbp = (c - bb_lower[i]) / band_range

        vm20 = vol_ma20[i] if vol_ma20[i] is not None and vol_ma20[i] > 0 else 1.0
        vol_ratio = v / vm20 if v > 0 else 0.0

        records.append({
            'date':        dates[i],
            'open':        o,
            'high':        h,
            'low':         l,
            'close':       c,
            'vol':         v,
            'ema5':        e5[i],
            'ema20':       e20[i],
            'ema50':       e50[i],
            'ema100':      e100[i],
            'ema200':      e200[i],
            'e20_slope':   e20_slope[i],
            'd20':         d20,
            'd50':         d50,
            'd200':        d200,
            'atr20':       atr20[i] if atr20[i] else (h - l),
            'rsi14':       rsi14[i] if i < len(rsi14) else None,
            'bbp':         bbp,
            'vol_ratio':   vol_ratio,
            'body':        body,
            'upper_shadow': upper_sh,
            'lower_shadow': lower_sh,
            'is_bullish':  c > o,
        })
    return records


# ═══════════════════════════════════════
#  信号检测 v3
# ═══════════════════════════════════════

def detect_signals(records):
    signals = []
    prev = records[0]

    for i, r in enumerate(records):
        if i == 0:
            prev = r
            continue

        s_type = None
        label  = ''
        details = {}

        # ── TOP: 过热顶部（OR逻辑）────────────────────
        # A: D20>4% AND RSI>65
        # B: D20>3% AND RSI>72
        # C: D20>6%
        is_top_A = r['d20'] > 0.04 and (r['rsi14'] or 0) > 65
        is_top_B = r['d20'] > 0.03 and (r['rsi14'] or 0) > 72
        is_top_C = r['d20'] > 0.06

        if is_top_A or is_top_B or is_top_C:
            s_type = 'TOP'
            reasons = []
            if is_top_A: reasons.append(f"D20={r['d20']*100:.1f}%")
            if is_top_B: reasons.append(f"RSI={r['rsi14']:.0f}")
            if is_top_C: reasons.append(f"D20={r['d20']*100:.1f}%超涨")
            label = f"🔥 过热顶部 {'+'.join(reasons)}"

        # ── BOTTOM: 恐慌底部（AND逻辑）──────────────
        # RSI<32 AND (D200<-8% OR D50<-5%) AND 阳线 AND 下影线存在
        if ((r['rsi14'] or 100) < 32 and
              (r['d200'] < -0.08 or r['d50'] < -0.05) and
              r['is_bullish'] and
              r['lower_shadow'] > 0.5 * max(r['body'], 0.01)):
            s_type = 'BOTTOM'
            reasons = []
            if r['rsi14']: reasons.append(f"RSI={r['rsi14']:.0f}")
            if r['d200'] < -0.08: reasons.append(f"D200={r['d200']*100:.1f}%")
            if r['d50'] < -0.05: reasons.append(f"D50={r['d50']*100:.1f}%")
            label = f"🕳️ 恐慌底部 {'+'.join(reasons)}"

        # ── BOTTOM2: 极度超卖（不要求阳线，RSI<25极度超卖）────────
        # 核心是 RSI 极度超卖，用于捕捉阴线恐慌底
        elif ((r['rsi14'] or 100) < 25 and
              (r['d200'] < -0.05 or r['d50'] < -0.05)):
            s_type = 'BOTTOM'
            reasons = []
            if r['rsi14']: reasons.append(f"RSI={r['rsi14']:.0f}")
            if r['d200'] < -0.05: reasons.append(f"D200={r['d200']*100:.1f}%")
            if r['d50'] < -0.05: reasons.append(f"D50={r['d50']*100:.1f}%")
            label = f"🕳️ 极度超卖 {'+'.join(reasons)}"

        # ── BUY: 波段买入（从EMA20下收复）────────────
        # 前一天收盘<EMA20 AND 今天收盘>EMA20 AND 阳线 AND RSI>40
        elif (prev.get('ema20') and prev['close'] < prev['ema20'] and
              r['ema20'] and r['close'] > r['ema20'] and
              r['is_bullish'] and
              (r['rsi14'] or 0) > 40):
            s_type = 'BUY'
            label = f"✅ 波段买入 收复EMA20 RSI={r['rsi14']:.0f}"

        # ── SELL: 乖离过大卖出 ──────────────────────
        elif r['d20'] > 0.05 and (r['rsi14'] or 0) > 68:
            s_type = 'SELL'
            label = f"⚠️ 卖出信号 D20={r['d20']*100:.1f}% RSI={r['rsi14']:.0f}"

        # ── GC: 金叉 EMA20上穿EMA50 ─────────────────
        elif (prev.get('ema20') and prev.get('ema50') and
              prev['ema20'] < prev['ema50'] and
              r['ema20'] and r['ema50'] and
              r['ema20'] > r['ema50']):
            s_type = 'BUY'
            label = f"🌟 金叉 EMA20上穿EMA50"

        # ── GD: 死叉 EMA20下穿EMA50 ─────────────────
        elif (prev.get('ema20') and prev.get('ema50') and
              prev['ema20'] > prev['ema50'] and
              r['ema20'] and r['ema50'] and
              r['ema20'] < r['ema50']):
            s_type = 'STOP'
            label = f"💀 死叉 EMA20下穿EMA50"

        if s_type:
            signals.append({
                'date':   r['date'],
                'type':   s_type,
                'label':  label,
                'close':  r['close'],
                'ema20':  r['ema20'],
                'ema50':  r['ema50'],
                'ema200': r['ema200'],
                'rsi14':  r['rsi14'],
                'bbp':    r['bbp'],
                'd20':    r['d20'],
                'd200':   r['d200'],
                'vol_ratio': r['vol_ratio'],
            })

        prev = r

    return signals


# ═══════════════════════════════════════
#  报告 & HTML
# ═══════════════════════════════════════

def print_report(signals, records):
    from collections import Counter
    counts = Counter(s['type'] for s in signals)

    print(f"\n{'='*60}")
    print(f"  SPY 波段顶底信号扫描报告 v3")
    print(f"{'='*60}")
    print(f"  数据: {records[0]['date']} ~ {records[-1]['date']}")
    print(f"  总信号: {len(signals)} 个")
    print(f"\n  信号分布:")
    icons = {'TOP':'🔥','BOTTOM':'🕳️','BUY':'✅','SELL':'⚠️','STOP':'🛑','GC':'🌟','GD':'💀'}
    for t, cnt in sorted(counts.items()):
        print(f"    {icons.get(t,'')} {t}: {cnt} 个")

    print(f"\n{'─'*60}")
    key_types = ('TOP', 'BOTTOM', 'BUY', 'SELL')
    for s in signals:
        if s['type'] in key_types:
            rsi_str = f"RSI={s['rsi14']:.0f}" if s.get('rsi14') else ""
            d_str   = f"D20={s['d20']*100:.1f}%" if s.get('d20') else ""
            print(f"  {s['date']}  {icons.get(s['type'],'')} {s['type']}  {s['label']}  {rsi_str}")
    print()


def build_html(records, signals):
    candles = [{'time': r['date'], 'open': r['open'], 'high': r['high'],
               'low': r['low'], 'close': r['close']} for r in records]

    def ema_line(field):
        return [{'time': records[i]['date'], 'value': records[i][field]}
                for i in range(len(records)) if records[i][field] is not None]

    markers = []
    for s in signals:
        cmap = {'TOP':'#FF1744','BOTTOM':'#00E676','BUY':'#00C853',
                'SELL':'#FF9100','STOP':'#FF6D00','GC':'#00B0FF','GD':'#FF1744'}
        markers.append({
            'time':     s['date'],
            'position': 'aboveBar' if s['type'] in ('TOP','SELL','STOP','GD') else 'belowBar',
            'color':    cmap.get(s['type'], '#FFD700'),
            'shape':    'arrowDown' if s['type'] in ('TOP','SELL','STOP','GD') else 'arrowUp',
            'text':     s['label'][:28],
        })

    lc_path = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/dtrade/lightweight-charts.js')
    lc_lib = open(lc_path).read() if lc_path.exists() else ''

    from collections import Counter
    counts = Counter(s['type'] for s in signals)
    tlabels = {'TOP':'🔥火顶','BOTTOM':'🕳️恐慌底','BUY':'✅买入','SELL':'⚠️卖出','STOP':'🛑止损/死叉','GC':'🌟金叉','GD':'💀死叉'}
    tcolors = {'TOP':'#FF1744','BOTTOM':'#00E676','BUY':'#00C853','SELL':'#FF9100','STOP':'#FF6D00','GC':'#00B0FF','GD':'#FF1744'}
    legend = '\n'.join(
        f'    <span><span class="dot" style="background:{tcolors[t]}"></span> {tlabels[t]} ({c})</span>'
        for t, c in sorted(counts.items())
    )

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>SPY 波段顶底信号 v3</title>
<script>{lc_lib}</script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;overflow:hidden}}
.header{{padding:10px 16px;background:#161b22;border-bottom:1px solid #30363d;display:flex;align-items:center;gap:20px;flex-wrap:wrap}}
.title{{font-size:20px;font-weight:700;color:#58a6ff;font-family:monospace}}
.meta{{color:#8b949e;font-size:12px}}
.legend{{display:flex;gap:12px;font-size:11px;color:#8b949e;flex-wrap:wrap}}
.legend span{{display:flex;align-items:center;gap:4px}}
.dot{{width:10px;height:10px;border-radius:50%;display:inline-block}}
#chart{{width:100vw;height:calc(100vh - 60px)}}
</style>
</head>
<body>
<div class="header">
  <span class="title">SPY 波段顶底信号 v3</span>
  <span class="meta">{records[0]['date']} ~ {records[-1]['date']} · {len(records)}天 · {len(signals)}信号</span>
  <div class="legend">{legend}</div>
</div>
<div id="chart"></div>
<script>
const candles = {json.dumps(candles)};
const ema5  = {json.dumps(ema_line('ema5'))};
const ema20 = {json.dumps(ema_line('ema20'))};
const ema50 = {json.dumps(ema_line('ema50'))};
const ema200= {json.dumps(ema_line('ema200'))};
const markers = {json.dumps(markers)};

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

const L = (color) => ({{color,lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false}});
chart.addLineSeries({{...L('#FFD700'),title:'EMA5'}}).setData(ema5.filter(d=>d.value!==null));
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
    print('  SPY 波段顶底信号扫描器 v3')
    print('=' * 60)

    records = load_and_build()
    print(f'  数据: {len(records)} 条 | {records[0]["date"]} ~ {records[-1]["date"]}')

    signals = detect_signals(records)
    print(f'  信号: {len(signals)} 个')

    print_report(signals, records)

    # HTML
    html = build_html(records, signals)
    with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'  ✅ HTML: {OUTPUT_HTML}')

    # JSON
    json_out = PROJECT_ROOT / 'spy_signals_v3.json'
    with open(json_out, 'w', encoding='utf-8') as f:
        json.dump({'records': records, 'signals': signals}, f, ensure_ascii=False, indent=2)
    print(f'  ✅ JSON: {json_out}')


if __name__ == '__main__':
    main()
