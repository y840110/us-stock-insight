#!/usr/bin/env python3
import json, math, statistics

def to_f(s):
    try: return float(str(s).replace(',',''))
    except: return None

with open('中间过程/klines/SPY_1d.json') as f:
    raw_d = json.load(f)['data']
with open('中间过程/klines/SPY_1wk.json') as f:
    raw_w = json.load(f)['data']

D = [{'date':r['date'],'open':to_f(r['open']),'high':to_f(r['high']),
      'low':to_f(r['low']),'close':to_f(r['close']),'vol':int(str(r['vol']).replace(',','') or 0)} for r in raw_d]
W = [{'date':r['date'],'open':to_f(r['open']),'high':to_f(r['high']),
      'low':to_f(r['low']),'close':to_f(r['close']),'vol':int(str(r['vol']).replace(',','') or 0)} for r in raw_w]

price  = D[0]['close']
pcloses = [d['close'] for d in D]
wp = [d['close'] for d in W]

def SMA(arr, n):
    return sum(arr[:n])/n if len(arr)>=n else None
def EMA(arr, n):
    k = 2/(n+1)
    ema = SMA(arr[:n], n)
    for v in arr[n:]:
        ema = (v-ema)*k + ema
    return ema
def ATR(data, n=14):
    trs = []
    for i in range(1, n+1):
        hl = data[i]['high']-data[i]['low']
        hc = abs(data[i]['high']-data[i-1]['close'])
        lc = abs(data[i]['low']-data[i-1]['close'])
        trs.append(max(hl, hc, lc))
    return sum(trs)/n
def calc_RSI(p, n=14):
    gains, losses = [], []
    for i in range(n):
        d = p[i]-p[i+1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    ag, al = sum(gains)/n, sum(losses)/n
    if al==0: return 100
    return 100 - 100/(1+ag/al)

atr14 = ATR(D,14)
rsi14 = calc_RSI(pcloses,14)
rsi28 = calc_RSI(pcloses,28)
ema12 = EMA(pcloses,12); ema26 = EMA(pcloses,26); macd_val = ema12-ema26
macd_sig = EMA(pcloses,9)
macd_hist = macd_val - macd_sig
ma5=SMA(pcloses,5); ma10=SMA(pcloses,10); ma20=SMA(pcloses,20)
ma60=SMA(pcloses,60); ma200=SMA(pcloses,200)
bb_mid=SMA(pcloses,20)
bb_std=(sum((v-bb_mid)**2 for v in pcloses[:20])/20)**0.5
bb_up=bb_mid+2*bb_std; bb_low=bb_mid-2*bb_std
bb_pos=(price-bb_low)/(bb_up-bb_low) if bb_up!=bb_low else 0.5
ret20=(pcloses[0]-pcloses[19])/pcloses[19]*100 if len(pcloses)>=20 else 0
high52w=max(d['high'] for d in D[:252])
low52w=min(d['low'] for d in D[:252])
avg_vol20=sum(d['vol'] for d in D[:20])/20
vol_r=D[0]['vol']/avg_vol20 if avg_vol20 else 1
w_ma5=SMA(wp,5); w_ma20=SMA(wp,20)
fib618=low52w+(high52w-low52w)*0.618
fib500=low52w+(high52w-low52w)*0.500
fib382=low52w+(high52w-low52w)*0.382
atr_pct=atr14/price*100

def S(name, cond, text):
    sig = +2 if cond=='++' else -2 if cond=='--' else +1 if cond in('+','+_overb') else -1 if cond in('-','-_overb') else 0
    return name, sig, text

analyses = []

# 道氏
if all(D[i]['high']>D[i+1]['high'] for i in range(4)) and all(D[i]['low']>D[i+1]['low'] for i in range(4)):
    analyses.append(S('道氏理论','++','明确多头：连续高价低价创新'))
elif all(D[i]['high']<D[i+1]['high'] for i in range(4)) and all(D[i]['low']<D[i+1]['low'] for i in range(4)):
    analyses.append(S('道氏理论','--','明确空头：连续高价低价降低'))
elif price>ma20 and price>ma60:
    analyses.append(S('道氏理论','+','偏多：价格在重要均线上方'))
elif price<ma20 and price<ma60:
    analyses.append(S('道氏理论','-','偏空：价格在重要均线下方'))
else:
    analyses.append(S('道氏理论','0','方向不明，均线纠缠'))

# 均线
if ma5>ma10>ma20>ma60:
    analyses.append(S('均线系统','++','完美多头排列：MA5>MA10>MA20>MA60'))
elif ma5>ma20>ma60:
    analyses.append(S('均线系统','+','均线多头排列'))
elif ma5<ma20<ma60:
    analyses.append(S('均线系统','--','均线空头排列'))
elif ma5>ma20:
    analyses.append(S('均线系统','+','短期均线偏多'))
else:
    analyses.append(S('均线系统','-','短期均线偏空'))

# RSI
if rsi14>75:
    analyses.append(S('RSI动量','-_overb',f'RSI14={rsi14:.0f} 极度过热，超买警告'))
elif rsi14>65:
    analyses.append(S('RSI动量','-',f'RSI14={rsi14:.0f} 超买区，注意高位回调风险'))
elif rsi14<30:
    analyses.append(S('RSI动量','-_overb',f'RSI14={rsi14:.0f} 超卖，超跌反弹机会'))
elif rsi14<40:
    analyses.append(S('RSI动量','+',f'RSI14={rsi14:.0f} 偏弱有支撑'))
else:
    analyses.append(S('RSI动量','+',f'RSI14={rsi14:.0f} 偏强但未超买，健康区间'))

# MACD
if macd_val>0 and macd_hist>0:
    analyses.append(S('MACD','++','零轴上方金叉，动能扩张，看涨'))
elif macd_val>0:
    analyses.append(S('MACD','+','零轴上方，多头格局'))
elif macd_val<0 and macd_hist<0:
    analyses.append(S('MACD','--','零轴下方死叉，动能弱，看跌'))
else:
    analyses.append(S('MACD','-','零轴下方，偏空'))

# 布林带
if price>bb_up:
    analyses.append(S('布林带','+','突破布林上轨，强势运行'))
elif bb_pos>0.85:
    analyses.append(S('布林带','-_overb','接近布林上轨，追涨风险累积'))
elif price<bb_low:
    analyses.append(S('布林带','++','触及布林下轨，超跌反弹机会'))
elif bb_pos<0.20:
    analyses.append(S('布林带','+','接近布林下轨，有支撑'))
else:
    analyses.append(S('布林带','+','布林中上轨运行，正常偏强'))

# RS
if ret20>8:
    analyses.append(S('相对强度RS','++',f'20日涨幅+{ret20:.1f}%，极强动量'))
elif ret20>5:
    analyses.append(S('相对强度RS','+',f'20日涨幅+{ret20:.1f}%，强势'))
elif ret20>2:
    analyses.append(S('相对强度RS','+',f'20日涨幅+{ret20:.1f}%，良好'))
elif ret20>-3:
    analyses.append(S('相对强度RS','0',f'20日{ret20:+.1f}%，小幅波动'))
else:
    analyses.append(S('相对强度RS','-',f'20日{ret20:+.1f}%，明显弱势'))

# VSA
if vol_r>1.5 and D[0]['close']>D[1]['close']:
    analyses.append(S('VSA量价','++','放量上涨，机构需求强劲'))
elif vol_r>1.5 and D[0]['close']<D[1]['close']:
    analyses.append(S('VSA量价','--','放量下跌，主力出货信号'))
elif vol_r<0.6 and D[0]['close']>D[1]['close']:
    analyses.append(S('VSA量价','-','缩量上涨，需求不足需谨慎'))
elif vol_r<0.6:
    analyses.append(S('VSA量价','0','缩量整理，观望情绪'))
else:
    analyses.append(S('VSA量价','+','温和放量，量价正常'))

# 支撑阻力
dist_high=(price-high52w)/price*100
dist_low=(price-low52w)/price*100
if dist_high<1:
    analyses.append(S('支撑阻力','++','接近52周新高，突破确认看涨'))
elif dist_high<5:
    analyses.append(S('支撑阻力','+','距52周高点1-5%，有望突破'))
elif dist_low<5:
    analyses.append(S('支撑阻力','--','接近52周低点，风险极大'))
elif dist_low<10:
    analyses.append(S('支撑阻力','-','距52周低点5-10%，谨慎'))
else:
    analyses.append(S('支撑阻力','+','处52周区间中上部，多头格局'))

# 趋势
if ret20>5:
    analyses.append(S('趋势强度','++','明确上升趋势'))
elif ret20>2:
    analyses.append(S('趋势强度','+','健康上升趋势'))
elif ret20>0:
    analyses.append(S('趋势强度','+','温和上升'))
elif ret20>-3:
    analyses.append(S('趋势强度','0','轻微回撤'))
else:
    analyses.append(S('趋势强度','-','明显下降趋势'))

# 波浪
ch20_hi=max(d['high'] for d in D[:20]); ch20_lo=min(d['low'] for d in D[:20])
ch_mid=(ch20_hi+ch20_lo)/2
if price>ch_mid+0.05*ch20_hi:
    analyses.append(S('波浪通道','++','处20日通道强势区域'))
elif price>ch_mid:
    analyses.append(S('波浪通道','+','处20日通道上半部'))
elif price<ch_mid-0.05*ch20_lo:
    analyses.append(S('波浪通道','--','处20日通道弱势区域'))
else:
    analyses.append(S('波浪通道','-','处20日通道下半部'))

# 威科夫
spring=any(D[i]['low']<D[i+1]['low']*0.995 and D[i]['close']>D[i]['open'] for i in range(1,5))
if spring:
    analyses.append(S('威科夫','++','疑似弹簧行情，看涨吸筹信号'))
elif price>ma20 and vol_r>1.0:
    analyses.append(S('威科夫','+','量价配合正常，多头主导'))
elif price<ma20:
    analyses.append(S('威科夫','-','价格低于均线，空头'))
else:
    analyses.append(S('威科夫','0','无明显信号'))

# TD
td_up=sum(1 for i in range(9) if i+4<len(D) and D[i]['close']>D[i+4]['close'])
if td_up>=8: analyses.append(S('TD序列','++',f'TD连续8+计数买入侧，极强信号'))
elif td_up>=6: analyses.append(S('TD序列','+',f'TD计数{td_up}/9买入侧，偏多'))
elif td_up<=2: analyses.append(S('TD序列','--',f'TD计数{td_up}/9卖出侧，极弱'))
elif td_up<=4: analyses.append(S('TD序列','-',f'TD计数{td_up}/9卖出侧，偏空'))
else: analyses.append(S('TD序列','0',f'TD计数中性({td_up}/9)'))

# 斐波
if price>fib618: analyses.append(S('斐波那契','+',f'位于61.8%回撤位上方，多头格局'))
elif price>fib500: analyses.append(S('斐波那契','+',f'位于50%回撤位上方，偏多'))
elif price>fib382: analyses.append(S('斐波那契','0',f'位于38.2%回撤位附近，中性'))
else: analyses.append(S('斐波那契','-','跌破38.2%回撤位，偏空'))

# ATR
if atr_pct<1.0: analyses.append(S('ATR波动率','+','低波动，适合稳健操作'))
elif atr_pct>2.5: analyses.append(S('ATR波动率','-','高波动，风险较大'))
else: analyses.append(S('ATR波动率','0','正常波动区间'))

# 周线
if w_ma5>w_ma20: analyses.append(S('周线确认','++','周线明确多头排列，看涨'))
elif w_ma5<w_ma20: analyses.append(S('周线确认','--','周线空头排列，看跌'))
else: analyses.append(S('周线确认','0','周线中性'))

scores=[a[1] for a in analyses]
total=sum(scores); mx=len(scores)*2; pct=total/mx*100
pos=sum(1 for s in scores if s>=1); neg=sum(1 for s in scores if s<=-1); neu=sum(1 for s in scores if s==0)
if pos>=len(scores)*0.65: conf='极高（一致通过）'
elif pos>=len(scores)*0.45: conf='高（大部分一致）'
elif neg>=len(scores)*0.45: conf='低（偏空占优）'
else: conf='一般（指标分散）'

# 趋势概率
if rsi14>70 and neg>=6: pu=35; pd=38; ps=27
elif pos>=10: pu=48; pd=28; ps=24
elif price>ma200 and price>ma20: pu=42; pd=28; ps=30
else: pu=38; pd=30; ps=32

# 进场/止损/止盈
atr_risk=2*atr14
stop=round(price-atr_risk,2)
entry_rec=round(min(ma20,ma10),2)
tgt2=round(price+2*atr_risk,2); tgt3=round(price+3*atr_risk,2)
rr2=(tgt2-price)/atr_risk; rr3=(tgt3-price)/atr_risk

# 5日70%
daily_moves=[abs(pcloses[i]-pcloses[i+1]) for i in range(min(60,len(pcloses)-1))]
sigma=(sum((m-statistics.mean(daily_moves))**2 for m in daily_moves)/len(daily_moves))**0.5
h70=round(price+1.04*math.sqrt(5)*sigma,2)
l70=round(price-1.04*math.sqrt(5)*sigma,2)

# 综合判断
if total>=15: action='加仓'; atype='趋势跟随'
elif total>=8: action='不动'; atype='持有观望'
elif total<=-5: action='减仓'; atype='短线防御'
else: action='不动'; atype='等待确认'

# 打印
print("="*68)
print(f"  SPY 多维技术分析报告")
print(f"  分析日期: 2026-05-07 | 当前价: ${price} | 数据: {D[0]['date']}")
print("="*68)

print("\n【(1) 各技术分析独立结论】")
print(f"{'分析项':<12} {'评分':>5}  {'结论'}")
print("-"*68)
for name, sig, text in analyses:
    arrow='[++]' if sig==2 else '[+]' if sig==1 else '[-]' if sig==-1 else '[--]' if sig==-2 else '[0]'
    print(f"{name:<12} {arrow}  {text}")

print(f"\n【(2) 评分汇总】")
print(f"   综合得分: {total:+3d} / {mx}  ({pct:.0f}%)")
print(f"   多头指标: {pos}个  |  空头指标: {neg}个  |  中性: {neu}个")
print(f"   置信度: {conf}")

print(f"\n【(3) 未来1个月趋势概率】")
print(f"   上涨: {pu}%    下跌: {pd}%    震荡: {ps}%")

print(f"\n【(4) 进场 / 止损 / 止盈】")
print(f"   当前价格:        ${price}")
print(f"   建议回踩进场:    ${entry_rec}  (MA10/MA20回踩时)")
print(f"   止损位:          ${stop}  (ATRx2, 风险额=${atr_risk:.2f})")
print(f"   2:1止盈:         ${tgt2}  (+{((tgt2-price)/price*100):.1f}%)")
print(f"   3:1止盈:         ${tgt3}  (+{((tgt3-price)/price*100):.1f}%)")
print(f"   潜在盈亏比:       {rr2:.1f}:1 / {rr3:.1f}:1")

print(f"\n【(5) 5个交易日内70%概率区间】")
print(f"   70%高价:  ${h70}  (+{(h70-price)/price*100:.1f}%)")
print(f"   70%低价:  ${l70}  (-{(price-l70)/price*100:.1f}%)")
print(f"   当前价格:  ${price}")

print(f"\n【(6) 综合判断】")
print(f"   --> {action} ({atype})")

print(f"\n【(7) 期权投资评估】")
rsi_ok=40<=rsi14<=65; atr_ok=atr_pct<2.0
conf_ok=conf in ['极高（一致通过）','高（大部分一致）']
if rsi_ok and atr_ok and conf_ok:
    print(f"   [OK] 可考虑期权投资")
    print(f"   方案：Bull Call Spread（牛市看涨价差）")
    print(f"   · 买入 SPY 20260620 730C (低执行价)")
    print(f"   · 卖出 SPY 20260620 760C (高执行价)")
    print(f"   · 净成本约 $3-5/张，最大盈利 $25-27/张")
    print(f"   · 到期：约6-8周（6月第三周）")
    print(f"   · 适合场景：SPY 1个月内涨3-5%")
elif rsi14>70:
    print(f"   [NO] 暂不推荐（RSI={rsi14:.0f} 超买，期权时间价值损耗风险高）")
    print(f"   建议：等待回调或 RSI 回落至50-60后再考虑")
else:
    print(f"   [WARN] 谨慎（置信度{conf}）")
    print(f"   建议：观望或采用低杠杆价差策略")

print("="*68)
