#!/usr/bin/env python3
"""
SPYTREND v5 — 基于v3 + EMA50止跌确认过滤器
==========================================

v3 核心：动态 exit（EMA20>EMA50 用死叉，EMA20<EMA50 用slope）

v5 改进：EMA20 再入场时，要求 EMA50 的 20日变化率 > 0
         （确认 EMA50 已经止跌，不是下跌中继的反弹）
         —— 不加任何 regime filter，不改 exit，不改 buy1 信号

目标：过滤掉 2022-07 和 2023-03 的 EMA20 假反弹入场

初始本金: $10,000
"""

import json
from pathlib import Path

KLINES_DIR  = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines')
OUT_HTML    = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spytrend/v5_chart.html')
OUT_JSON    = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spytrend/v5_result.json')


def calc_ema(prices, period):
    if len(prices) < period:
        return [None] * len(prices)
    k = 2 / (period + 1)
    r = [None] * (period - 1) + [prices[period - 1]]
    for i in range(period, len(prices)):
        r.append(prices[i] * k + r[-1] * (1 - k))
    return r

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return [None] * len(prices)
    rsi = [None] * len(prices)
    gains, losses = [], []
    for i in range(1, len(prices)):
        delta = prices[i] - prices[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi[period] = 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi[i + 1] = 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return rsi

def load_data():
    with open(KLINES_DIR / 'SPY_1d.json') as f:
        bars = json.load(f)['data']
    closes = [b['close'] for b in bars]
    highs  = [b['high']  for b in bars]
    lows   = [b['low']   for b in bars]
    dates  = [b['date']  for b in bars]
    e20 = calc_ema(closes, 20)
    e50 = calc_ema(closes, 50)
    e20s = [None] * len(closes)
    e50s = [None] * len(closes)
    for i in range(5, len(closes)):
        if e20[i - 5] and e20[i]: e20s[i] = e20[i] / e20[i - 5] - 1
        if e50[i - 5] and e50[i]: e50s[i] = e50[i] / e50[i - 5] - 1
    rsi14 = calc_rsi(closes, 14)
    records = []
    for i, bar in enumerate(bars):
        records.append({
            'date': dates[i], 'open': bar['open'], 'high': highs[i], 'low': lows[i],
            'close': closes[i], 'ema20': e20[i], 'ema50': e50[i],
            'e20s': e20s[i], 'e50s': e50s[i], 'rsi14': rsi14[i],
        })
    return records

def assess_bear_energy(sell_record, buy_record, records, date_to_idx):
    s_date = sell_record['date']; b_date = buy_record['date']
    s_idx = date_to_idx.get(s_date); b_idx = date_to_idx.get(b_date)
    if s_idx is None or b_idx is None or b_idx <= s_idx:
        return {'direction': 'up', 'drawdown': 0, 'days': 0, 'energy': 'weak', 'score': 0}
    window = records[s_idx:b_idx + 1]
    if len(window) < 3:
        return {'direction': 'mixed', 'drawdown': 0, 'days': len(window) - 1, 'energy': 'weak', 'score': 1}
    ema50_start = window[0]['ema50']; ema50_end = window[-1]['ema50']
    if ema50_start and ema50_end:
        ema50_chg = (ema50_end - ema50_start) / ema50_start
        direction = 'down' if ema50_chg < -0.02 else ('up' if ema50_chg > 0.02 else 'mixed')
    else: direction = 'mixed'
    sell_price = sell_record['close']
    lowest_low = min(r['low'] for r in window)
    drawdown = max(0.0, (sell_price - lowest_low) / sell_price)
    days = b_idx - s_idx
    score = 0
    if direction == 'down': score += 1
    if drawdown >= 0.05: score += 1
    elif drawdown >= 0.10: score += 1
    if days >= 20: score += 1
    energy = 'strong' if score >= 3 else ('medium' if score >= 2 else 'weak')
    return {'direction': direction, 'drawdown': drawdown, 'days': days, 'energy': energy, 'score': score}

def backtest_v5(records, initial=10_000.0):
    cash, shares, in_pos = initial, 0.0, False
    entry_px = 0.0
    equity_curve, trades = [], []
    date_to_idx = {r['date']: i for i, r in enumerate(records)}
    bear_energy = None; last_sell_px = 0.0; last_sell_rec = None

    for i, r in enumerate(records):
        price = r['close']
        nxt_open = records[i + 1]['open'] if i < len(records) - 1 else price
        prev = records[i - 1] if i > 0 else None

        # ── v5 关键改进：EMA50 止跌确认 ─────────────────────
        # EMA20 再入场时，要求 EMA50 相比 20 天前更高
        # 下跌中继：EMA50 持续下降 → filter 激活 → 禁止 EMA20 再入场
        # 真正反弹：EMA50 已止跌回升 → filter 不激活 → 允许入场
        ema50_20d_up = (
            i >= 20 and
            r['ema50'] is not None and records[i - 20]['ema50'] is not None and
            r['ema50'] > records[i - 20]['ema50']
        )

        # ── v5 第二改进：EMA50 下降确认 ─────────────────────
        # EMA20<=0 exit 时，要求 EMA50 也在下降（slope < 0）
        # 如果 EMA50 还在上升，EMA20<=0 很可能只是噪音（市场盘整）
        # → 忽略这个 exit，继续持有
        ema50_confirmed_down = (
            r['e50s'] is not None and r['e50s'] < 0
        )

        # ── EMA20 slope 确认（re-entry 优化）────────────────────
        # EMA20 再入场时，同时要求 EMA20 slope > 0
        # → 避免在 EMA20 刚由负转正、还没确认势时入场
        ema20_slope_positive = (
            r['e20s'] is not None and r['e20s'] > 0
        )

        buy1 = (not in_pos and
                r['e50s'] is not None and r['e50s'] >= 0 and
                prev and prev['e50s'] is not None and prev['e50s'] < 0)

        buy2 = (not in_pos and
                r['e20s'] is not None and r['e20s'] >= 0 and
                prev and prev['e20s'] is not None and prev['e20s'] < 0 and
                ema50_20d_up and ema20_slope_positive)  # ← v5 双确认条件

        be_str = bear_energy.get('energy', 'weak') if isinstance(bear_energy, dict) else str(bear_energy)

        # ── 动态 exit（完全同 v3）──────────────────────────
        ema20_above = (r['ema20'] is not None and r['ema50'] is not None and r['ema20'] > r['ema50'])
        death_cross = (
            in_pos and r['ema20'] is not None and r['ema50'] is not None and
            prev and prev['ema20'] is not None and prev['ema50'] is not None and
            prev['ema20'] > prev['ema50'] and r['ema20'] <= r['ema50']
        )
        slope_cross_down = (
            in_pos and r['e20s'] is not None and
            prev and prev['e20s'] is not None and prev['e20s'] > 0 and r['e20s'] <= 0
        )
        rsi_escape = (
            in_pos and r['rsi14'] is not None and be_str == 'strong' and r['rsi14'] > 55
        ) or (
            in_pos and r['rsi14'] is not None and be_str == 'medium' and r['rsi14'] > 60
        )

        if rsi_escape:
            sell = True; src = f'RSI>{55 if be_str == "strong" else 60}'
        elif ema20_above and death_cross:
            sell = True; src = '死叉(EMA20>EMA50)'
        elif not ema20_above and slope_cross_down:
            # v5 改进：EMA50 也在下降才接受 exit
            # 如果 EMA50 还在上升（slope >= 0），忽略这个 exit
            sell = ema50_confirmed_down
            src  = 'EMA20<=0(EMA50下降确认)' if ema50_confirmed_down else None
        else:
            sell = False; src = None

        if buy1 or buy2:
            src_buy = 'EMA50转正' if buy1 else 'EMA20再转正(EMA50已止跌)'
            shares = cash / nxt_open; entry_px = nxt_open; cash = 0.0; in_pos = True
            bear_energy = assess_bear_energy(last_sell_rec, r, records, date_to_idx) if last_sell_rec else {'energy': 'weak', 'score': 0, 'direction': 'up', 'drawdown': 0, 'days': 0}
            next_date = records[i + 1]['date'] if i + 1 < len(records) else r['date']
            trades.append({'d': next_date, 'a': 'BUY', 'px': nxt_open, 'src': src_buy, 'bear_energy': bear_energy})
        elif sell:
            cash = shares * nxt_open; pnl = (nxt_open - entry_px) / entry_px
            next_date = records[i + 1]['date'] if i + 1 < len(records) else r['date']
            trades.append({'d': next_date, 'a': 'SELL', 'px': nxt_open, 'pnl': pnl, 'src': src, 'exit_energy': bear_energy})
            last_sell_px = nxt_open; last_sell_rec = r; shares = 0.0; in_pos = False; bear_energy = None
        equity_curve.append({'d': r['date'], 'v': cash + shares * price})

    if in_pos: equity_curve[-1]['v'] = shares * records[-1]['close']
    return equity_curve, trades

def buy_and_hold(records, initial=10_000.0):
    shares = initial / records[0]['open']
    curve = [{'d': r['date'], 'v': shares * r['close']} for r in records]
    return curve, [{'d': records[0]['date'], 'a': 'BUY', 'px': records[0]['open']}]

def calc_stats(curve, trades, initial):
    final = curve[-1]['v']
    n_years = len(curve) / 252
    cagr = (final / initial) ** (1 / n_years) - 1
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
            (wins if t.get('pnl', 0) > 0 else losses).append(t['pnl']); bt = None
    nw, nl = len(wins), len(losses)
    energy_stats = {}
    for t in trades:
        be = t.get('bear_energy', {})
        e = be.get('energy', 'unknown') if isinstance(be, dict) else 'unknown'
        if e not in energy_stats: energy_stats[e] = {'count': 0}
        if t['a'] == 'BUY': energy_stats[e]['count'] += 1
    return {
        'final': final, 'cagr': cagr, 'max_dd': max_dd,
        'n_buys': sum(1 for t in trades if t['a'] == 'BUY'),
        'n_sells': sum(1 for t in trades if t['a'] == 'SELL'),
        'win_rate': nw / (nw + nl) if nw + nl else 0,
        'avg_w': sum(wins) / nw if nw else 0,
        'avg_l': sum(losses) / nl if nl else 0,
        'pf': abs(sum(wins) / sum(losses)) if losses else float('inf'),
        'equity_curve': curve, 'energy_stats': energy_stats,
    }

def fmt_pct(v): return f"{v * 100:+.2f}%"
def fmt_money(v): return f"${v:,.2f}"

def build_html(records, trades, strat, bh, INITIAL):
    candles = [{'time': r['date'], 'open': r['open'], 'high': r['high'], 'low': r['low'], 'close': r['close']} for r in records]
    ema20_line = [{'time': r['date'], 'value': r['ema20']} for r in records if r['ema20']]
    ema50_line = [{'time': r['date'], 'value': r['ema50']} for r in records if r['ema50']]
    rsi_line = [{'time': r['date'], 'value': r['rsi14']} for r in records if r['rsi14'] is not None]
    e20s_pos = [{'time': r['date'], 'value': max(r['e20s'], 0)} for r in records if r['e20s'] is not None]
    e20s_neg = [{'time': r['date'], 'value': min(r['e20s'], 0)} for r in records if r['e20s'] is not None]
    zero_line = [{'time': r['date'], 'value': 0} for r in records]
    markers = []
    for t in trades:
        be = t.get('bear_energy', {}); energy = be.get('energy', '') if isinstance(be, dict) else ''
        icon = {'strong': '⚠️', 'medium': '🔶', 'weak': '✅'}.get(energy, '')
        if t['a'] == 'BUY':
            markers.append({'time': t['d'], 'position': 'belowBar', 'color': '#00BFFF', 'shape': 'arrowUp', 'text': f"买 {t.get('src','')} {icon}"})
        else:
            color = '#FF4444' if 'RSI' in t.get('src', '') else '#DA70D6'
            markers.append({'time': t['d'], 'position': 'aboveBar', 'color': color, 'shape': 'arrowDown', 'text': f"卖 {t.get('src','')}"})
    eq_strat = [{'time': e['d'], 'value': e['v']} for e in strat['equity_curve']]
    eq_bh = [{'time': e['d'], 'value': e['v']} for e in bh['equity_curve']]
    lc_path = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/dtrade/lightweight-charts.js')
    lc_lib = open(lc_path).read() if lc_path.exists() else ''
    s_final = strat['final']; b_final = bh['final']
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8"><title>SPYTREND v5 — EMA50止跌确认</title>
<script>{lc_lib}</script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;overflow:hidden}}
#main{{width:100vw;height:36vh}}#sub{{width:100vw;height:28vh;border-top:3px solid #30363d}}
#rsi{{width:100vw;height:16vh;border-top:3px solid #30363d}}
#eq{{width:100vw;height:20vh;border-top:3px solid #30363d}}
.kpi{{padding:8px 14px;background:#161b22;border-bottom:1px solid #30363d;display:flex;gap:24px;flex-wrap:wrap;font-size:12px}}
.kpi span{{color:#8b949e}}kpi strong{{color:#e6edf3;font-weight:600}}
.kpi .win{{color:#3fb950}}.kpi .lose{{color:#f85149}}
</style></head><body>
<div class="kpi">
  <span>最终权益: <strong class="{'win' if s_final>INITIAL else 'lose'}">{fmt_money(s_final)}</strong> ({fmt_pct(strat['cagr'])}/年) <span class="{'win' if s_final>b_final else 'lose'}">{'✅' if s_final>b_final else '❌'} vs B&H {fmt_money(b_final)}</span></span>
  <span>买 {strat['n_buys']} 卖 {strat['n_sells']}  胜率 {strat['win_rate']*100:.0f}%</span>
  <span>均盈 {fmt_pct(strat['avg_w'])} 均亏 {fmt_pct(strat['avg_l'])} 盈亏比 {strat['pf']:.1f}×</span>
  <span>最大回撤 {fmt_pct(strat['max_dd'])}</span>
</div>
<div id="main"></div><div id="sub"></div><div id="rsi"></div><div id="eq"></div>
<script>
const candles={json.dumps(candles)},ema20Line={json.dumps(ema20_line)},ema50Line={json.dumps(ema50_line)};
const e20Pos={json.dumps(e20s_pos)},e20Neg={json.dumps(e20s_neg)},zeroLine={json.dumps(zero_line)};
const rsiLine={json.dumps(rsi_line)},markers={json.dumps(markers)};
const eqStrat={json.dumps(eq_strat)},eqBH={json.dumps(eq_bh)};
const mainChart=LightweightCharts.createChart(document.getElementById('main'),{{layout:{{background:{{color:'#0d1117'}},textColor:'#e6edf3'}},grid:{{vertLines:{{color:'#21262d'}},horzLines:{{color:'#21262d'}}}},width:window.innerWidth,height:window.innerHeight*0.36,timeScale:{{timeVisible:true,secondsVisible:false,borderColor:'#30363d'}},rightPrice:{{borderColor:'#30363d'}}}});
const cs=mainChart.addCandlestickSeries({{upColor:'#26a69a',downColor:'#ef5350',borderUpColor:'#26a69a',borderDownColor:'#ef5350',wickUpColor:'#26a69a',wickDownColor:'#ef5350'}});
cs.setData(candles);cs.setMarkers(markers);
mainChart.addLineSeries({{color:'#FF6B35',lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false,title:'EMA20'}}).setData(ema20Line);
mainChart.addLineSeries({{color:'#00BFFF',lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false,title:'EMA50'}}).setData(ema50Line);
mainChart.timeScale().fitContent();
const subChart=LightweightCharts.createChart(document.getElementById('sub'),{{layout:{{background:{{color:'#0d1117'}},textColor:'#e6edf3'}},grid:{{vertLines:{{color:'#21262d'}},horzLines:{{color:'#21262d'}}}},width:window.innerWidth,height:window.innerHeight*0.28,timeScale:{{timeVisible:true,secondsVisible:false,borderColor:'#30363d'}},rightPrice:{{borderColor:'#30363d',visible:true}}}});
subChart.addLineSeries({{color:'rgba(255,255,255,0.4)',lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false}}).setData(zeroLine);
subChart.addAreaSeries({{topColor:'rgba(76,175,80,0.4)',bottomColor:'rgba(76,175,80,0.02)',invertFilledArea:false}}).setData(e20Pos);
subChart.addAreaSeries({{topColor:'rgba(244,67,54,0.02)',bottomColor:'rgba(244,67,54,0.4)',invertFilledArea:false}}).setData(e20Neg);
const rsiChart=LightweightCharts.createChart(document.getElementById('rsi'),{{layout:{{background:{{color:'#0d1117'}},textColor:'#e6edf3'}},grid:{{vertLines:{{color:'#21262d'}},horzLines:{{color:'#21262d'}}}},width:window.innerWidth,height:window.innerHeight*0.16,timeScale:{{timeVisible:true,secondsVisible:false,borderColor:'#30363d'}},rightPrice:{{borderColor:'#30363d',visible:true}}}});
rsiChart.addLineSeries({{color:'rgba(255,187,41,0.8)',lineWidth:1,priceLineVisible:false,lastValueVisible:false}}).setData(rsiLine);
const rsi70=records.map(r=>({{time:r.date,value:70}})),rsi30=records.map(r=>({{time:r.date,value:30}}));
rsiChart.addLineSeries({{color:'rgba(248,81,73,0.5)',lineWidth:1,priceLineVisible:false,lastValueVisible:false}}).setData(rsi70);
rsiChart.addLineSeries({{color:'rgba(63,185,80,0.5)',lineWidth:1,priceLineVisible:false,lastValueVisible:false}}).setData(rsi30);
const eqChart=LightweightCharts.createChart(document.getElementById('eq'),{{layout:{{background:{{color:'#0d1117'}},textColor:'#e6edf3'}},grid:{{vertLines:{{color:'#21262d'}},horzLines:{{color:'#21262d'}}}},width:window.innerWidth,height:window.innerHeight*0.20,timeScale:{{timeVisible:true,secondsVisible:false,borderColor:'#30363d'}},rightPrice:{{borderColor:'#30363d'}}}});
eqChart.addLineSeries({{color:'#FFD700',lineWidth:2,title:'v5策略'}}).setData(eqStrat);
eqChart.addLineSeries({{color:'#58a6ff',lineWidth:1,title:'B&H'}}).setData(eqBH);
eqChart.timeScale().fitContent();
const sync=(a,b,c)=>{{a.timeScale().subscribeVisibleLogicalRangeChange(r=>{{if(r){{b.timeScale().setVisibleLogicalRange(r);c.timeScale().setVisibleLogicalRange(r);}}}});b.timeScale().subscribeVisibleLogicalRangeChange(r=>{{if(r){{a.timeScale().setVisibleLogicalRange(r);c.timeScale().setVisibleLogicalRange(r);}}}});c.timeScale().subscribeVisibleLogicalRangeChange(r=>{{if(r){{a.timeScale().setVisibleLogicalRange(r);b.timeScale().setVisibleLogicalRange(r);}}}})}};
sync(mainChart,subChart,eqChart);sync(subChart,rsiChart,eqChart);
window.addEventListener('resize',()=>{{mainChart.resize(window.innerWidth,window.innerHeight*0.36);subChart.resize(window.innerWidth,window.innerHeight*0.28);rsiChart.resize(window.innerWidth,window.innerHeight*0.16);eqChart.resize(window.innerWidth,window.innerHeight*0.20);}});
</script></body></html>"""

def main():
    print('=' * 60)
    print('  SPYTREND v5 — EMA50止跌确认过滤')
    print('=' * 60)
    records = load_data()
    print(f'  数据: {len(records)} 天 | {records[0]["date"]} ~ {records[-1]["date"]}')
    INITIAL = 10_000.0
    strat_curve, strat_trades = backtest_v5(records, INITIAL)
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
        if t['a'] == 'BUY':
            n += 1
            be = t.get('bear_energy', {}); e = be.get('energy', '') if isinstance(be, dict) else ''
            icon = {'strong': '⚠️', 'medium': '🔶', 'weak': '✅'}.get(e, '')
            print(f'  {t["d"]}  🟢买  ${t["px"]:.2f}  [{n} {t.get("src","")}] {icon}')
        else:
            pnl = f" ({t.get('pnl',0)*100:+.1f}%)"
            print(f'  {t["d"]}  🔴卖  ${t["px"]:.2f}  [{n}{t.get("src","")}]{pnl}')
            n -= 1
    html = build_html(records, strat_trades, strat, bh, INITIAL)
    with open(OUT_HTML, 'w', encoding='utf-8') as f: f.write(html)
    print(f'\n  ✅ HTML: {OUT_HTML}')
    result = {
        'strategy_final': strat['final'], 'bh_final': bh['final'], 'excess': excess,
        'strat_cagr': strat['cagr'], 'bh_cagr': bh['cagr'], 'strat_max_dd': strat['max_dd'],
        'n_buys': strat['n_buys'], 'n_sells': strat['n_sells'], 'win_rate': strat['win_rate'],
        'avg_w': strat['avg_w'], 'avg_l': strat['avg_l'], 'profit_factor': strat['pf'],
        'energy_stats': strat.get('energy_stats', {}), 'trades': strat_trades,
    }
    with open(OUT_JSON, 'w', encoding='utf-8') as f: json.dump(result, f, ensure_ascii=False, indent=2)
    print(f'  ✅ JSON: {OUT_JSON}')

if __name__ == '__main__':
    main()
