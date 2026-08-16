#!/usr/bin/env python3
"""
SPY EMA50入场 + EMA20出场 + EMA20再次转正重新入场
=====================================================

规则：
  买入：空仓时，EMA50斜率由负转正
  卖出：持仓时，EMA20斜率由正转≤0
  重新入场：卖出后，EMA20斜率再次由负转正

初始本金: $10,000
"""

import json
from pathlib import Path
from datetime import datetime, timedelta

KLINES_DIR = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines')
OUT_HTML   = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spy_ema50_ema20_reextry_chart.html')
OUT_JSON   = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spy_ema50_ema20_reextry_result.json')


# ═══════════════════════════════════════
#  数据 & 指标
# ═══════════════════════════════════════

def calc_ema(prices, period):
    if len(prices) < period: return [None]*len(prices)
    k = 2/(period+1)
    r = [None]*(period-1) + [prices[period-1]]
    for i in range(period, len(prices)): r.append(prices[i]*k + r[-1]*(1-k))
    return r


def load_data():
    with open(KLINES_DIR/'SPY_1d.json') as f:
        bars = json.load(f)['data']
    closes = [b['close'] for b in bars]
    dates  = [b['date']  for b in bars]
    e20 = calc_ema(closes, 20)
    e50 = calc_ema(closes, 50)
    e20s = [None]*len(closes)
    e50s = [None]*len(closes)
    for i in range(5, len(closes)):
        if e20[i-5] and e20[i]: e20s[i] = e20[i]/e20[i-5]-1
        if e50[i-5] and e50[i]: e50s[i] = e50[i]/e50[i-5]-1
    records = []
    for i, bar in enumerate(bars):
        records.append({
            'date':  dates[i], 'open': bar['open'], 'high': bar['high'],
            'low':   bar['low'],  'close': closes[i],
            'ema20': e20[i], 'ema50': e50[i],
            'e20s': e20s[i], 'e50s': e50s[i],
        })
    return records


# ═══════════════════════════════════════
#  回测
# ═══════════════════════════════════════

def backtest(records, initial=10_000.0):
    """
    状态机：
      IDLE:  等待 EMA50斜率<0→≥0  → BUY
      LONG:  等待 EMA20斜率>0→≤0   → SELL
      IDLE后: 等待 EMA20斜率<0→≥0   → BUY（再入场）
    """
    cash, shares, in_pos, entry = initial, 0.0, False, 0.0
    equity_curve, trades = [], []

    for i, r in enumerate(records):
        price = r['close']
        nxt   = records[i+1]['open'] if i < len(records)-1 else price
        prev  = records[i-1] if i > 0 else None

        # 入场1：空仓 + EMA50由负转正
        buy1 = (not in_pos and
                r['e50s'] is not None and r['e50s'] >= 0 and
                prev and prev['e50s'] is not None and prev['e50s'] < 0)

        # 入场2：空仓 + EMA20由负转正（再入场）
        buy2 = (not in_pos and
                r['e20s'] is not None and r['e20s'] >= 0 and
                prev and prev['e20s'] is not None and prev['e20s'] < 0)

        # 出场：持仓 + EMA20由正转≤0
        sell = (in_pos and
                r['e20s'] is not None and
                prev and prev['e20s'] is not None and
                prev['e20s'] > 0 and r['e20s'] <= 0)

        if buy1:
            shares = cash / nxt; entry = nxt; cash = 0.0; in_pos = True
            trades.append({'d': records[i+1]['date'] if i+1 < len(records) else r['date'],
                           'a': 'BUY', 'px': nxt, 'src': 'EMA50转正'})
        elif buy2:
            shares = cash / nxt; entry = nxt; cash = 0.0; in_pos = True
            trades.append({'d': records[i+1]['date'] if i+1 < len(records) else r['date'],
                           'a': 'BUY', 'px': nxt, 'src': 'EMA20再转正'})
        elif sell:
            cash = shares * nxt
            trades.append({'d': records[i+1]['date'] if i+1 < len(records) else r['date'],
                           'a': 'SELL', 'px': nxt,
                           'pnl': (nxt - entry)/entry, 'src': 'EMA20<=0'})
            shares = 0.0; in_pos = False

        equity_curve.append({'d': r['date'], 'v': cash + shares * price})

    if in_pos: equity_curve[-1]['v'] = shares * records[-1]['close']
    return equity_curve, trades


def buy_and_hold(records, initial=10_000.0):
    shares = initial / records[0]['open']
    curve = [{'d': r['date'], 'v': shares * r['close']} for r in records]
    return curve, [{'d': records[0]['date'], 'a': 'BUY', 'px': records[0]['open']}]


# ═══════════════════════════════════════
#  绩效
# ═══════════════════════════════════════

def calc_stats(curve, trades, initial):
    final = curve[-1]['v']
    n_years = len(curve) / 252
    cagr = (final/initial)**(1/n_years) - 1
    peak, max_dd = initial, 0.0
    for e in curve:
        if e['v'] > peak: peak = e['v']
        dd = (peak - e['v']) / peak
        if dd > max_dd: max_dd = dd
    wins, losses = [], []
    bt = None
    for t in trades:
        if t['a'] == 'BUY': bt = t
        elif t['a'] == 'SELL' and bt:
            (wins if t['pnl'] > 0 else losses).append(t['pnl']); bt = None
    nw, nl = len(wins), len(losses)
    return {
        'final': final, 'cagr': cagr, 'max_dd': max_dd,
        'n_buys': sum(1 for t in trades if t['a'] == 'BUY'),
        'n_sells': sum(1 for t in trades if t['a'] == 'SELL'),
        'win_rate': nw/(nw+nl) if nw+nl else 0,
        'avg_w': sum(wins)/nw if nw else 0,
        'avg_l': sum(losses)/nl if nl else 0,
        'pf': abs(sum(wins)/sum(losses)) if losses else float('inf'),
        'equity_curve': curve,
    }


def fmt_pct(v):   return f"{v*100:+.2f}%"
def fmt_money(v): return f"${v:,.2f}"


# ═══════════════════════════════════════
#  HTML
# ═══════════════════════════════════════

def build_html(records, trades, strat, bh, INITIAL):
    candles = [{'time': r['date'], 'open': r['open'], 'high': r['high'],
                'low': r['low'], 'close': r['close']} for r in records]
    ema20_line = [{'time': r['date'], 'value': r['ema20']} for r in records if r['ema20']]
    ema50_line = [{'time': r['date'], 'value': r['ema50']} for r in records if r['ema50']]

    # EMA20/50 斜率面积数据
    e20s_pos = [{'time': r['date'], 'value': max(r['e20s'], 0)} for r in records if r['e20s'] is not None]
    e20s_neg = [{'time': r['date'], 'value': min(r['e20s'], 0)} for r in records if r['e20s'] is not None]
    e50s_pos = [{'time': r['date'], 'value': max(r['e50s'], 0)} for r in records if r['e50s'] is not None]
    e50s_neg = [{'time': r['date'], 'value': min(r['e50s'], 0)} for r in records if r['e50s'] is not None]
    zero_line = [{'time': r['date'], 'value': 0} for r in records]

    # markers
    markers = []
    for t in trades:
        if t['a'] == 'BUY':
            markers.append({'time': t['d'], 'position': 'belowBar',
                           'color': '#00BFFF', 'shape': 'arrowUp',
                           'text': f"买 {t.get('src','')}"})
        else:
            markers.append({'time': t['d'], 'position': 'aboveBar',
                           'color': '#DA70D6', 'shape': 'arrowDown',
                           'text': f"卖 {t.get('src','')}"})

    # 持仓区间
    in_pos, reg_start, regions = False, None, []
    for r in records:
        has_buy  = any(t['a']=='BUY'  and t['d']==r['date'] for t in trades)
        has_sell = any(t['a']=='SELL' and t['d']==r['date'] for t in trades)
        if has_buy and not in_pos:      in_pos = True; reg_start = r['date']
        elif has_sell and in_pos:        in_pos = False; regions.append({'start': reg_start, 'end': r['date']})
    if in_pos: regions.append({'start': reg_start, 'end': records[-1]['date']})

    # equity curve
    eq_strat = [{'time': e['d'], 'value': e['v']} for e in strat['equity_curve']]
    eq_bh    = [{'time': e['d'], 'value': e['v']} for e in bh['equity_curve']]

    lc_path = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/dtrade/lightweight-charts.js')
    lc_lib  = open(lc_path).read() if lc_path.exists() else ''

    s_final = strat['final']
    b_final = bh['final']
    win_v3  = s_final > b_final

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>EMA50入场+EMA20出场+EMA20再入 v3</title>
<script>
{lc_lib}
</script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;overflow:hidden}}
#main{{width:100vw;height:36vh}}
#sub{{width:100vw;height:32vh;border-top:3px solid #30363d}}
#eq{{width:100vw;height:22vh;border-top:3px solid #30363d}}
.kpi{{padding:8px 14px;background:#161b22;border-bottom:1px solid #30363d;display:flex;gap:24px;flex-wrap:wrap;font-size:12px}}
.kpi span{{color:#8b949e}}
.kpi strong{{color:#e6edf3;font-weight:600}}
.kpi .sel{{color:#00BFFF;font-weight:700}}
.kpi .bh{{color:#58a6ff}}
.kpi .win{{color:#3fb950}}
.kpi .lose{{color:#f85149}}
</style>
</head>
<body>
<div class="kpi">
  <span>最终权益: <strong class="{'win' if s_final>INITIAL else 'lose'}">{fmt_money(s_final)}</strong> ({fmt_pct(strat['cagr'])})  <span class="{'win' if win_v3 else 'lose'}">{'✅' if win_v3 else '❌'} vs B&H {fmt_money(b_final)}</span></span>
  <span>买 {strat['n_buys']} 卖 {strat['n_sells']} 波段 {strat['n_buys']-strat['n_sells']} 胜率 {strat['win_rate']*100:.0f}%</span>
  <span>均盈 {fmt_pct(strat['avg_w'])} 均亏 {fmt_pct(strat['avg_l'])} 盈亏比 {strat['pf']:.1f}×</span>
</div>
<div id="main"></div>
<div id="sub"></div>
<div id="eq"></div>
<script>
const candles = {json.dumps(candles)};
const ema20Line = {json.dumps(ema20_line)};
const ema50Line = {json.dumps(ema50_line)};
const e20Pos = {json.dumps(e20s_pos)};
const e20Neg = {json.dumps(e20s_neg)};
const e50Pos = {json.dumps(e50s_pos)};
const e50Neg = {json.dumps(e50s_neg)};
const zeroLine = {json.dumps(zero_line)};
const markers = {json.dumps(markers)};
const regions = {json.dumps(regions)};
const eqStrat = {json.dumps(eq_strat)};
const eqBH   = {json.dumps(eq_bh)};

// ── 主图：K线 + EMA + 买卖点 ──
const mainChart = LightweightCharts.createChart(document.getElementById('main'),{{
  layout:{{background:{{color:'#0d1117'}},textColor:'#e6edf3'}},
  grid:{{vertLines:{{color:'#21262d'}},horzLines:{{color:'#21262d'}}}},
  width:window.innerWidth,height:window.innerHeight*0.36,
  timeScale:{{timeVisible:true,secondsVisible:false,borderColor:'#30363d'}},
  rightPrice:{{borderColor:'#30363d'}},
}});

regions.forEach(reg => {{
  const hi = candles.filter(c => c.time >= reg.start && c.time <= reg.end)
    .map(c => ({{time:c.time,value:c.high+2}}));
  if (!hi.length) return;
  mainChart.addAreaSeries({{
    color:'rgba(0,191,255,0.06)',lineWidth:0,priceLineVisible:false,
    lastValueVisible:false,crosshairMarkerVisible:false,
    topColor:'rgba(0,191,255,0.10)',bottomColor:'rgba(0,191,255,0.02)',
  }}).setData(hi);
}});

const cs = mainChart.addCandlestickSeries({{
  upColor:'#26a69a',downColor:'#ef5350',
  borderUpColor:'#26a69a',borderDownColor:'#ef5350',
  wickUpColor:'#26a69a',wickDownColor:'#ef5350',
}});
cs.setData(candles);
cs.setMarkers(markers);

const L = (color) => ({{color,lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false}});
mainChart.addLineSeries({{...L('#FF6B35'),title:'EMA20'}}).setData(ema20Line);
mainChart.addLineSeries({{...L('#00BFFF'),title:'EMA50'}}).setData(ema50Line);
mainChart.timeScale().fitContent();

// ── 副图：斜率面积图 ──
const subChart = LightweightCharts.createChart(document.getElementById('sub'),{{
  layout:{{background:{{color:'#0d1117'}},textColor:'#e6edf3'}},
  grid:{{vertLines:{{color:'#21262d'}},horzLines:{{color:'#21262d'}}}},
  width:window.innerWidth,height:window.innerHeight*0.32,
  timeScale:{{timeVisible:true,secondsVisible:false,borderColor:'#30363d',visible:true}},
  rightPrice:{{borderColor:'#30363d',visible:true}},
  crosshair:{{mode:LightweightCharts.CrosshairMode.Normal}},
}});

subChart.addLineSeries({{color:'rgba(255,255,255,0.6)',lineWidth:2,priceLineVisible:true,lastValueVisible:false,crosshairMarkerVisible:false}}).setData(zeroLine);

subChart.addAreaSeries({{lineWidth:1,priceLineVisible:false,lastValueVisible:true,crosshairMarkerVisible:true,topColor:'rgba(76,175,80,0.4)',bottomColor:'rgba(76,175,80,0.02)',invertFilledArea:false}}).setData(e20Pos);
subChart.addAreaSeries({{lineWidth:1,priceLineVisible:false,lastValueVisible:true,crosshairMarkerVisible:true,topColor:'rgba(244,67,54,0.02)',bottomColor:'rgba(244,67,54,0.4)',invertFilledArea:false}}).setData(e20Neg);
subChart.addAreaSeries({{lineWidth:1,priceLineVisible:false,lastValueVisible:true,crosshairMarkerVisible:true,topColor:'rgba(33,150,243,0.3)',bottomColor:'rgba(33,150,243,0.02)',invertFilledArea:false}}).setData(e50Pos);
subChart.addAreaSeries({{lineWidth:1,priceLineVisible:false,lastValueVisible:true,crosshairMarkerVisible:true,topColor:'rgba(255,235,59,0.02)',bottomColor:'rgba(255,235,59,0.3)',invertFilledArea:false}}).setData(e50Neg);

// ── 权益对比图 ──
const eqChart = LightweightCharts.createChart(document.getElementById('eq'),{{
  layout:{{background:{{color:'#0d1117'}},textColor:'#e6edf3'}},
  grid:{{vertLines:{{color:'#21262d'}},horzLines:{{color:'#21262d'}}}},
  width:window.innerWidth,height:window.innerHeight*0.22,
  timeScale:{{timeVisible:true,secondsVisible:false,borderColor:'#30363d'}},
  rightPrice:{{borderColor:'#30363d'}},
}});
eqChart.addLineSeries({{color:'#FFD700',lineWidth:2,title:'本策略'}}).setData(eqStrat);
eqChart.addLineSeries({{color:'#58a6ff',lineWidth:1,title:'B&H'}}).setData(eqBH);
eqChart.timeScale().fitContent();

// 同步
mainChart.timeScale().subscribeVisibleLogicalRangeChange(r => {{ if (r) {{ subChart.timeScale().setVisibleLogicalRange(r); eqChart.timeScale().setVisibleLogicalRange(r); }} }});
subChart.timeScale().subscribeVisibleLogicalRangeChange(r => {{ if (r) {{ mainChart.timeScale().setVisibleLogicalRange(r); eqChart.timeScale().setVisibleLogicalRange(r); }} }});
eqChart.timeScale().subscribeVisibleLogicalRangeChange(r => {{ if (r) {{ mainChart.timeScale().setVisibleLogicalRange(r); subChart.timeScale().setVisibleLogicalRange(r); }} }});

window.addEventListener('resize',() => {{
  mainChart.resize(window.innerWidth, window.innerHeight*0.36);
  subChart.resize(window.innerWidth, window.innerHeight*0.32);
  eqChart.resize(window.innerWidth, window.innerHeight*0.22);
}});
</script>
</body>
</html>"""


# ═══════════════════════════════════════
#  主程序
# ═══════════════════════════════════════

def main():
    print('=' * 60)
    print('  EMA50入场 + EMA20出场 + EMA20再入 策略')
    print('=' * 60)

    records = load_data()
    print(f'  数据: {len(records)} 天 | {records[0]["date"]} ~ {records[-1]["date"]}')

    INITIAL = 10_000.0
    strat_curve, strat_trades = backtest(records, INITIAL)
    bh_curve,    bh_trades    = buy_and_hold(records, INITIAL)

    strat = calc_stats(strat_curve, strat_trades, INITIAL)
    bh    = calc_stats(bh_curve,    bh_trades,    INITIAL)

    excess = (strat['final'] - bh['final']) / bh['final']

    print(f'\n  策略最终权益: {fmt_money(strat["final"])}  ({fmt_pct(strat["cagr"])}/年)')
    print(f'  B&H 最终权益:  {fmt_money(bh["final"])}  ({fmt_pct(bh["cagr"])}/年)')
    print(f'  超额收益:      {fmt_pct(excess)}  {"✅ 跑赢" if excess > 0 else "❌ 跑输"}')
    print(f'  最大回撤:      {fmt_pct(strat["max_dd"])}  |  胜率 {strat["win_rate"]*100:.0f}%  |  盈亏比 {strat["pf"]:.2f}×')
    print(f'  买 {strat["n_buys"]} 卖 {strat["n_sells"]}')

    print(f'\n  买卖明细:')
    n = 0
    for t in strat_trades:
        if t['a'] == 'BUY': n += 1
        icon = '🟢买' if t['a'] == 'BUY' else '🔴卖'
        src  = t.get('src','')
        pnl  = f" ({t.get('pnl',0)*100:+.1f}%)" if t['a'] == 'SELL' else ''
        print(f'  {t["d"]}  {icon} ${t["px"]:.2f}  [{n if t["a"]=="BUY" else n}{"#" if t["a"]=="BUY" else ""} {src}]{pnl}')
        if t['a'] == 'SELL': n -= 1

    # HTML
    html = build_html(records, strat_trades, strat, bh, INITIAL)
    with open(OUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'\n  ✅ HTML: {OUT_HTML}')

    # JSON
    result = {
        'strategy_final': strat['final'],
        'bh_final':       bh['final'],
        'excess':        excess,
        'strat_cagr':    strat['cagr'],
        'bh_cagr':       bh['cagr'],
        'strat_max_dd':  strat['max_dd'],
        'bh_max_dd':     bh['max_dd'],
        'n_buys':        strat['n_buys'],
        'n_sells':       strat['n_sells'],
        'win_rate':      strat['win_rate'],
        'avg_w':         strat['avg_w'],
        'avg_l':         strat['avg_l'],
        'profit_factor': strat['pf'],
        'trades':        strat_trades,
    }
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f'  ✅ JSON: {OUT_JSON}')


if __name__ == '__main__':
    main()
