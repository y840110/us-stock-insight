#!/usr/bin/env python3
import json
from pathlib import Path

KLINES_DIR = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines')
OUT = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spy_100w_equity_chart.html')
lc_path = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/dtrade/lightweight-charts.js')

def calc_ema(prices, period):
    if len(prices) < period: return [None]*len(prices)
    k = 2/(period+1)
    r = [None]*(period-1) + [prices[period-1]]
    for i in range(period, len(prices)): r.append(prices[i]*k + r[-1]*(1-k))
    return r

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

records = [{'date':dates[i],'open':bars[i]['open'],'close':closes[i],
            'e20s':e20s[i],'e50s':e50s[i]} for i in range(len(bars))]

# 第一个买入信号
first_idx = None
for i in range(1, len(records)):
    if (records[i]['e50s'] is not None and records[i]['e50s']>=0 and
        records[i-1]['e50s'] is not None and records[i-1]['e50s']<0):
        first_idx = i; break

first_open = records[first_idx]['open']
INITIAL = 100_000.0

# 策略
cash,shares,in_pos,entry = INITIAL,0.0,False,0.0
strat_eq=[]; strat_trades=[]
for i in range(first_idx, len(records)):
    r=records[i]
    nxt=records[i+1]['open'] if i<len(records)-1 else r['close']
    prev=records[i-1]
    buy1=(not in_pos and r['e50s'] is not None and r['e50s']>=0 and prev['e50s'] is not None and prev['e50s']<0)
    buy2=(not in_pos and r['e20s'] is not None and r['e20s']>=0 and prev['e20s'] is not None and prev['e20s']<0)
    sell=(in_pos and r['e20s'] is not None and prev['e20s'] is not None and prev['e20s']>0 and r['e20s']<=0)
    if buy1:
        shares=cash/nxt;entry=nxt;cash=0.0;in_pos=True
        strat_trades.append({'date':records[i+1]['date'] if i+1<len(records) else r['date'],'a':'BUY','price':nxt})
    elif buy2:
        shares=cash/nxt;entry=nxt;cash=0.0;in_pos=True
        strat_trades.append({'date':records[i+1]['date'] if i+1<len(records) else r['date'],'a':'BUY','price':nxt})
    elif sell:
        cash=shares*nxt
        strat_trades.append({'date':records[i+1]['date'] if i+1<len(records) else r['date'],'a':'SELL','price':nxt,'pnl':(nxt-entry)/entry})
        shares=0.0;in_pos=False
    strat_eq.append({'time':r['date'],'value':cash+shares*nxt})

final_price=records[-1]['close']
final_date=records[-1]['date']
if in_pos:
    fc=shares*final_price
    strat_eq[-1]['value']=fc
    strat_trades.append({'date':final_date,'a':'SELL','price':final_price,'pnl':(final_price-entry)/entry})
    total_final=fc
else:
    total_final=cash

bh_shares=INITIAL/first_open
bh_eq=[{'time':r['date'],'value':bh_shares*r['close']} for r in records[first_idx:]]
total_bh=bh_shares*final_price

max_diff=0;max_diff_date=''
for se,be in zip(strat_eq,bh_eq):
    d=be['value']-se['value']
    if d>max_diff: max_diff=d;max_diff_date=se['time']

bh_ahead_date=None
for se,be in zip(strat_eq,bh_eq):
    if be['value']>se['value'] and bh_ahead_date is None: bh_ahead_date=se['time']

in_pos=False;reg_start=None;regions=[]
for r in records[first_idx:]:
    hb=any(t['a']=='BUY' and t['date']==r['date'] for t in strat_trades)
    hs=any(t['a']=='SELL' and t['date']==r['date'] for t in strat_trades)
    if hb and not in_pos: in_pos=True;reg_start=r['date']
    elif hs and in_pos: in_pos=False;regions.append({'start':reg_start,'end':r['date']})
if in_pos: regions.append({'start':reg_start,'end':records[-1]['date']})

spy_candles=[{'time':r['date'],'open':r['open'],'high':r['open'],'low':r['open'],'close':r['close']}
             for r in records[first_idx:]]

markers=[]
for t in strat_trades:
    if t['a']=='BUY':
        markers.append({'time':t['date'],'position':'belowBar','color':'#00BFFF','shape':'arrowUp','text':'买'})
    else:
        markers.append({'time':t['date'],'position':'aboveBar','color':'#DA70D6','shape':'arrowDown','text':'卖'})

lc_lib = open(lc_path).read() if lc_path.exists() else ''

diff_pct=(total_final-total_bh)/total_bh*100
diff_str = "%+.1f%%" % diff_pct
max_diff_str = "%.0f" % max_diff

bh_eq_json = json.dumps(bh_eq)
strat_eq_json = json.dumps(strat_eq)
markers_json = json.dumps(markers)
regions_json = json.dumps(regions)
candles_json = json.dumps(spy_candles)

html = (
'<!DOCTYPE html>\n<html lang="zh">\n<head>\n<meta charset="UTF-8">\n'
'<title>策略 vs B&H 资金曲线</title>\n<script>\n' + lc_lib + '\n</script>\n'
'<style>\n*{margin:0;padding:0;box-sizing:border-box}\n'
'body{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow:hidden}\n'
'.kpi{padding:10px 16px;background:#161b22;border-bottom:1px solid #30363d;display:flex;gap:20px;flex-wrap:wrap;font-size:12px}\n'
'.kpi span{color:#8b949e}\n'
'.kpi strong{color:#e6edf3;font-weight:600}\n'
'#main{width:100vw;height:62vh}\n'
'#eq{width:100vw;height:28vh;border-top:3px solid #30363d}\n'
'</style>\n</head>\n<body>\n'
'<div class="kpi">\n'
'<span>策略: <strong style="color:#FFD700">$%s</strong></span>\n' % ("{:,.0f}".format(total_final)) +
'<span>B&amp;H: <strong style="color:#58a6ff">$%s</strong></span>\n' % ("{:,.0f}".format(total_bh)) +
'<span>差异: <strong style="color:#f85149">$%s (%s)</strong></span>\n' % ("{:+,.0f}".format(total_final-total_bh), diff_str) +
'<span>最大差异: <strong style="color:#FF6D00">$%s (%s)</strong></span>\n' % (max_diff_str, max_diff_date) +
'<span>B&amp;H首次超越: <strong style="color:#58a6ff">%s</strong></span>\n' % bh_ahead_date +
'</div>\n'
'<div id="main"></div>\n<div id="eq"></div>\n'
'<script>\n'
'const stratEq = ' + strat_eq_json + ';\n'
'const bhEq = ' + bh_eq_json + ';\n'
'const markers = ' + markers_json + ';\n'
'const regions = ' + regions_json + ';\n'
'const candles = ' + candles_json + ';\n'
'\n'
'const mainChart = LightweightCharts.createChart(document.getElementById("main"),{\n'
'  layout:{background:{color:"#0d1117"},textColor:"#e6edf3"},\n'
'  grid:{vertLines:{color:"#21262d"},horzLines:{color:"#21262d"}},\n'
'  width:window.innerWidth,height:window.innerHeight*0.62,\n'
'  timeScale:{timeVisible:true,secondsVisible:false,borderColor:"#30363d"},\n'
'  rightPrice:{borderColor:"#30363d"},\n'
'});\n'
'\n'
'regions.forEach(reg => {\n'
'  const hiData = candles.filter(c => c.time >= reg.start && c.time <= reg.end)\n'
'    .map(c => ({time:c.time,value:c.high+2}));\n'
'  if (!hiData.length) return;\n'
'  mainChart.addAreaSeries({\n'
'    color:"rgba(0,191,255,0.06)",lineWidth:0,priceLineVisible:false,\n'
'    lastValueVisible:false,crosshairMarkerVisible:false,\n'
'    topColor:"rgba(0,191,255,0.10)",bottomColor:"rgba(0,191,255,0.02)",\n'
'  }).setData(hiData);\n'
'});\n'
'\n'
'const cs = mainChart.addCandlestickSeries({\n'
'  upColor:"#26a69a",downColor:"#ef5350",\n'
'  borderUpColor:"#26a69a",borderDownColor:"#ef5350",\n'
'  wickUpColor:"#26a69a",wickDownColor:"#ef5350",\n'
'});\n'
'cs.setData(candles);\n'
'cs.setMarkers(markers);\n'
'mainChart.timeScale().fitContent();\n'
'\n'
'const eqChart = LightweightCharts.createChart(document.getElementById("eq"),{\n'
'  layout:{background:{color:"#0d1117"},textColor:"#e6edf3"},\n'
'  grid:{vertLines:{color:"#21262d"},horzLines:{color:"#21262d"}},\n'
'  width:window.innerWidth,height:window.innerHeight*0.28,\n'
'  timeScale:{timeVisible:true,secondsVisible:false,borderColor:"#30363d"},\n'
'  rightPrice:{borderColor:"#30363d"},\n'
'});\n'
'\n'
'bhEq.forEach(d => { d.value = d.value; });\n'
'\n'
'const bhSeries = eqChart.addLineSeries({\n'
'  color:"#58a6ff",lineWidth:2,title:"B&H",\n'
'  priceLineVisible:true,lastValueVisible:true,crosshairMarkerVisible:true,\n'
'});\n'
'bhSeries.setData(bhEq.map(d => ({time:d.time,value:d.value})));\n'
'\n'
'const stratSeries = eqChart.addLineSeries({\n'
'  color:"#FFD700",lineWidth:2,title:"策略",\n'
'  priceLineVisible:true,lastValueVisible:true,crosshairMarkerVisible:true,\n'
'});\n'
'stratSeries.setData(stratEq.map(d => ({time:d.time,value:d.value})));\n'
'\n'
'mainChart.timeScale().subscribeVisibleLogicalRangeChange(range => {\n'
'  if (range) eqChart.timeScale().setVisibleLogicalRange(range);\n'
'});\n'
'eqChart.timeScale().subscribeVisibleLogicalRangeChange(range => {\n'
'  if (range) mainChart.timeScale().setVisibleLogicalRange(range);\n'
'});\n'
'\n'
'window.addEventListener("resize",() => {\n'
'  mainChart.resize(window.innerWidth, window.innerHeight*0.62);\n'
'  eqChart.resize(window.innerWidth, window.innerHeight*0.28);\n'
'});\n'
'</script>\n</body>\n</html>'
)

with open(OUT, 'w', encoding='utf-8') as f:
    f.write(html)
print("OK:", OUT)
print("策略:", ("$%.0f" % total_final), "B&H:", ("$%.0f" % total_bh))
print("最大差异: $%.0f (%s)" % (max_diff, max_diff_date))
print("B&H首次超越:", bh_ahead_date)
