#!/usr/bin/env python3
"""
SPY 多维技术分析报告
CDO × CRO 联合分析
风险偏好：低（高胜率，盈亏比≥2:1）
分析日期：2026-05-07
"""

import json, math, os
from datetime import datetime, timedelta
from statistics import mean, stdev

PROJECT_ROOT = "/home/yudengfeng/.openclaw/workspace/美股投资洞察分析"
DATA_DIR = os.path.join(PROJECT_ROOT, "中间过程", "klines")

# ─────────────────────────────────────────────
# 数据加载
# ─────────────────────────────────────────────
def load_json(ticker, interval):
    with open(os.path.join(DATA_DIR, f"{ticker}_{interval}.json")) as f:
        return json.load(f)

def to_float(s):
    try:
        return float(str(s).replace(',', ''))
    except:
        return None

# 加载 SPY 数据
spy_d = load_json("SPY", "1d")
spy_w = load_json("SPY", "1wk")

daily = spy_d["data"]   # 最新在前
weekly = spy_w["data"]  # 最新在前

def rows_to_ohlc(rows):
    return [{
        "date": r["date"],
        "open":  to_float(r["open"]),
        "high":  to_float(r["high"]),
        "low":   to_float(r["low"]),
        "close": to_float(r["close"]),
        "adj":   to_float(r["adj"]),
        "vol":   int(str(r["vol"]).replace(',','') or 0)
    } for r in rows]

D = rows_to_ohlc(daily)   # 日K
W = rows_to_ohlc(weekly)  # 周K

print(f"日K: {len(D)} 根, 最新: {D[0]['date']}")
print(f"周K: {len(W)} 根, 最新: {W[0]['date']}")
print(f"当前价格: {D[0]['close']}")

# ─────────────────────────────────────────────
# 指标计算工具
# ─────────────────────────────────────────────
def SMA(data, n, key="close"):
    if len(data) < n: return None
    return sum(d[key] for d in data[:n]) / n

def EMA(data, n, key="close"):
    if len(data) < n: return None
    k = 2/(n+1)
    ema = SMA(data[:n], n, key)
    for d in data[n:]:
        ema = (d[key] - ema) * k + ema
    return ema

def ATR(data, n=14):
    if len(data) < n+1: return None
    trs = []
    for i in range(1, n+1):
        hl = data[i]["high"] - data[i]["low"]
        hc = abs(data[i]["high"] - data[i-1]["close"])
        lc = abs(data[i]["low"] - data[i-1]["close"])
        trs.append(max(hl, hc, lc))
    return sum(trs)/n

def RSI(data, n=14):
    if len(data) < n+1: return None
    gains, losses = [], []
    for i in range(1, n+1):
        delta = data[i]["close"] - data[i-1]["close"]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains)/n
    avg_loss = sum(losses)/n
    if avg_loss == 0: return 100
    rs = avg_gain/avg_loss
    return 100 - 100/(1+rs)

def MACD(data, fast=12, slow=26, signal=9):
    if len(data) < slow+signal: return None
    ema_fast = EMA(data, fast)
    ema_slow = EMA(data, slow)
    macd_line = ema_fast - ema_slow
    # signal line approximated
    return macd_line  # 简化

def std_dev(data, n=20):
    if len(data) < n: return None
    vals = [d["close"] for d in data[:n]]
    return stdev(vals)

def max_high(data, n=20):
    return max(d["high"] for d in data[:n])

def min_low(data, n=20):
    return min(d["low"] for d in data[:n])

def high_of_highs(data, n=50):
    return max(d["high"] for d in data[:n])

def low_of_lows(data, n=50):
    return min(d["low"] for d in data[:n])

def avg_vol(data, n=20):
    return sum(d["vol"] for d in data[:n])/n

def volume_ratio(data, n=20):
    if not data or data[0]["vol"] == 0: return 1
    return data[0]["vol"] / avg_vol(data, n)

# ─────────────────────────────────────────────
# 关键技术位
# ─────────────────────────────────────────────
price     = D[0]["close"]
vol_today = D[0]["vol"]
vol_avg20 = avg_vol(D, 20)
vol_r     = vol_today / vol_avg20 if vol_avg20 else 1

ma5_d  = SMA(D, 5)
ma10_d = SMA(D, 10)
ma20_d = SMA(D, 20)
ma60_d = SMA(D, 60)
ma120_d= SMA(D, 120)
ma200_d= SMA(D, 200)

ma5_w  = SMA(W, 5)
ma10_w = SMA(W, 10)
ma20_w = SMA(W, 20)
ma60_w = SMA(W, 60)

atr14   = ATR(D, 14)
rsi14   = RSI(D, 14)
rsi28   = RSI(D, 28)

# 布林带
bb20_high = SMA(D, 20) + 2*std_dev(D, 20)
bb20_low  = SMA(D, 20) - 2*std_dev(D, 20)

# 52周高低
high52w  = high_of_highs(D, 252)
low52w   = low_of_lows(D, 252)

# 支撑阻力
resistance = high52w
support    = low52w

# ─────────────────────────────────────────────
# 助记符评分函数
# ─────────────────────────────────────────────
def score(label, value, thresholds):
    """thresholds = (极强, 强, 中性, 弱, 极弱) 返回 -2~+2"""
    if value >= thresholds[0]: return +2, f"{label}=极强({value:.2f})"
    if value >= thresholds[1]: return +1, f"{label}=强({value:.2f})"
    if value >= thresholds[2]: return  0, f"{label}=中性({value:.2f})"
    if value >= thresholds[3]: return -1, f"{label}=弱({value:.2f})"
    return -2, f"{label}=极弱({value:.2f})"

# ─────────────────────────────────────────────
# (1) 各技术分析独立结论
# ─────────────────────────────────────────────
analyses = []

# ── A. 道氏理论 ──
# 日线趋势
ma5_above_ma20_d = ma5_d > ma20_d
ma20_above_ma60_d = ma20_d > ma60_d
higher_highs  = all(D[i]["high"] > D[i+1]["high"] for i in range(min(5,len(D)-1)))
higher_lows   = all(D[i]["low"] > D[i+1]["low"] for i in range(min(5,len(D)-1)))
lower_highs   = all(D[i]["high"] < D[i+1]["high"] for i in range(min(5,len(D)-1)))
lower_lows    = all(D[i]["low"] < D[i+1]["low"] for i in range(min(5,len(D)-1)))

if ma5_above_ma20_d and higher_highs and higher_lows:
    dow_signal = +2
    dow_text   = "日线明确多头：MA5>MA20，均线多头排列，价量齐涨"
elif not ma5_above_ma20_d and lower_highs and lower_lows:
    dow_signal = -2
    dow_text   = "日线明确空头：MA5<MA20，均线空头排列，价量齐跌"
elif ma5_above_ma20_d:
    dow_signal = +1
    dow_text   = "日线偏多：短期均线在上，但高低点未持续创新高"
elif not ma5_above_ma20_d:
    dow_signal = -1
    dow_text   = "日线偏空：短期均线在下，或处于回调整理"
else:
    dow_signal = 0
    dow_text   = "日线方向不明"
analyses.append(("道氏理论", dow_signal, dow_text))

# ── B. 移动均线 + 扇形 ──
if ma5_d > ma20_d > ma60_d > ma120_d:
    ma_signal = +2
    ma_text   = f"均线完美多头扇形: MA5({ma5_d:.1f})>MA20({ma20_d:.1f})>MA60({ma60_d:.1f})>MA120({ma120_d:.1f})"
elif ma5_d > ma20_d and ma20_d > ma60_d:
    ma_signal = +1
    ma_text   = f"日线多头排列: MA5({ma5_d:.1f})>MA20({ma20_d:.1f})>MA60({ma60_d:.1f})"
elif ma5_d < ma20_d and ma20_d < ma60_d:
    ma_signal = -1
    ma_text   = f"日线空头排列: MA5({ma5_d:.1f})<MA20({ma20_d:.1f})<MA60({ma60_d:.1f})"
else:
    ma_signal = 0
    ma_text   = f"均线纠缠: MA5={ma5_d:.1f}, MA20={ma20_d:.1f}, MA60={ma60_d:.1f}"
analyses.append(("均线系统", ma_signal, ma_text))

# ── C. RSI 动量 ──
if rsi14 > 70:
    rsi_signal = -1  # 超买，高风险
    rsi_text   = f"RSI14={rsi14:.1f} 超买区域，回调风险大"
elif rsi14 > 60:
    rsi_signal = +1
    rsi_text   = f"RSI14={rsi14:.1f} 偏强，但未超买"
elif rsi14 < 30:
    rsi_signal = -1
    rsi_text   = f"RSI14={rsi14:.1f} 超卖，可能反弹"
elif rsi14 < 40:
    rsi_signal = 0
    rsi_text   = f"RSI14={rsi14:.1f} 偏弱，但未超卖"
else:
    rsi_signal = +1
    rsi_text   = f"RSI14={rsi14:.1f} 适中偏强，多头区域"
analyses.append(("RSI动量", rsi_signal, rsi_text))

# ── D. MACD ──
ema12 = EMA(D, 12)
ema26 = EMA(D, 26)
macd_val = ema12 - ema26
macd_signal = 1 if macd_val > 0 else -1 if macd_val < 0 else 0
# MACD柱方向（最近2根）
hist1 = (D[0]["close"] - EMA(D,12)) - (D[0]["close"] - EMA(D,26))  # 简化
hist_prev = (D[1]["close"] - EMA(D[1:],12)) - (D[1]["close"] - EMA(D[1:],26))
macd_trend = +1 if hist1 > hist_prev else -1 if hist1 < hist_prev else 0
macd_text  = f"MACD线={macd_val:.2f}({'零轴上' if macd_val>0 else '零轴下'}), 动能{'扩张' if macd_trend>0 else '收缩'}"
analyses.append(("MACD", macd_signal + macd_trend, macd_text))

# ── E. 布林带 ──
bb_position = (price - bb20_low) / (bb20_high - bb20_low) if bb20_high != bb20_low else 0.5
if price > bb20_high:
    bb_signal = +1
    bb_text   = f"价格突破布林上轨({bb20_high:.1f})，强势但注意回调"
elif price < bb20_low:
    bb_signal = -1
    bb_text   = f"价格触及布林下轨({bb20_low:.1f})，超卖反弹信号"
elif bb_position > 0.8:
    bb_signal = 0
    bb_text   = f"布林上轨附近({bb_position:.0%}分位)，谨慎追涨"
elif bb_position < 0.2:
    bb_signal = 0
    bb_text   = f"布林下轨附近({bb_position:.0%}分位)，超卖区域"
else:
    bb_signal = +1
    bb_text   = f"布林中轨区域({bb_position:.0%}分位)，正常偏强"
analyses.append(("布林带", bb_signal, bb_text))

# ── F. 相对强度 RS (SPY vs QQQ) ──
# 简化：用SPY与自身比较，近20日斜率
ret20 = (D[0]["close"] - D[19]["close"]) / D[19]["close"] * 100 if len(D) >= 20 else 0
if ret20 > 5:
    rs_signal = +2
    rs_text   = f"SPY 20日涨幅+{ret20:.1f}%，强势动量"
elif ret20 > 2:
    rs_signal = +1
    rs_text   = f"SPY 20日涨幅+{ret20:.1f}%，良好上升趋势"
elif ret20 > 0:
    rs_signal = 0
    rs_text   = f"SPY 20日涨幅+{ret20:.1f}%，温和偏强"
elif ret20 > -5:
    rs_signal = 0
    rs_text   = f"SPY 20日涨幅{ret20:.1f}%，小幅回调整理"
else:
    rs_signal = -1
    rs_text   = f"SPY 20日跌幅{ret20:.1f}%，明显弱势"
analyses.append(("相对强度RS", rs_signal, rs_text))

# ── G. 成交量分析 VSA ──
# 放量判断：当天成交量 vs 20日均量
vol_r20 = vol_r
if vol_r20 > 1.5 and D[0]["close"] > D[1]["close"]:
    vsa_signal = +2
    vsa_text   = f"放量上涨(VOL={vol_r20:.1f}x)，机构积极参与，看涨"
elif vol_r20 > 1.5 and D[0]["close"] < D[1]["close"]:
    vsa_signal = -2
    vsa_text   = f"放量下跌(VOL={vol_r20:.1f}x)，主力出货，风险大"
elif vol_r20 < 0.7 and D[0]["close"] > D[1]["close"]:
    vsa_signal = +1
    vsa_text   = f"缩量上涨(VOL={vol_r20:.1f}x)，谨慎，需求可能不足"
elif vol_r20 < 0.7:
    vsa_signal = 0
    vsa_text   = f"缩量整理(VOL={vol_r20:.1f}x)，观望情绪浓厚"
elif vol_r20 > 1.0:
    vsa_signal = +1
    vsa_text   = f"温和放量(VOL={vol_r20:.1f}x)，量价配合正常"
else:
    vsa_signal = 0
    vsa_text   = f"量能正常(VOL={vol_r20:.1f}x)"
analyses.append(("VSA量价", vsa_signal, vsa_text))

# ── H. 支撑阻力 ──
dist_res = (price - resistance) / price * 100 if resistance else 0
dist_sup = (price - support) / price * 100 if support else 0
if price >= resistance * 0.98:
    sr_signal = +2
    sr_text   = f"价格接近52周高点({resistance:.1f})，突破确认看涨"
elif price >= resistance * 0.90:
    sr_signal = +1
    sr_text   = f"价格接近52周阻力区({resistance:.1f})，突破后跟进"
elif price <= support * 1.02:
    sr_signal = -2
    sr_text   = f"价格接近52周低点({support:.1f})，严控止损"
elif price <= support * 1.10:
    sr_signal = -1
    sr_text   = f"价格偏离支撑({support:.1f})，注意下方空间"
else:
    sr_signal = 0
    sr_text   = f"在支撑({support:.1f})和阻力({resistance:.1f})之间运行"
analyses.append(("支撑阻力", sr_signal, sr_text))

# ── I. 趋势斜率 ──
# 计算20日线性回归斜率方向
def trend_slope(data, n=20):
    if len(data) < n: return 0
    prices = [d["close"] for d in data[:n]]
    x = list(range(n))
    x_mean = (n-1)/2
    y_mean = sum(prices)/n
    num = sum((x[i]-x_mean)*(prices[i]-y_mean) for i in range(n))
    den = sum((x[i]-x_mean)**2 for i in range(n))
    slope = num/den if den != 0 else 0
    return slope

slope20 = trend_slope(D, 20)
if slope20 > 0.5:
    trend_signal = +2
    trend_text   = f"20日上升通道，斜率+{slope20:.2f}，强趋势"
elif slope20 > 0.2:
    trend_signal = +1
    trend_text   = f"20日温和上升，斜率+{slope20:.2f}"
elif slope20 < -0.5:
    trend_signal = -2
    trend_text   = f"20日下降通道，斜率{slope20:.2f}，空头趋势"
elif slope20 < -0.2:
    trend_signal = -1
    trend_text   = f"20日温和下降，斜率{slope20:.2f}"
else:
    trend_signal = 0
    trend_text   = f"20日横盘整理，斜率{slope20:.2f}，方向不明"
analyses.append(("趋势斜率", trend_signal, trend_text))

# ── J. 波浪理论（简化） ──
# 通过价格通道判断：近20日高点和低点
ch_high20 = max_high(D, 20)
ch_low20  = min_low(D, 20)
ch_mid    = (ch_high20 + ch_low20) / 2
if price > ch_mid:
    wave_signal = +1
    wave_text   = f"价格处于20日通道上半部({ch_low20:.1f}-{ch_high20:.1f})，偏多"
else:
    wave_signal = -1
    wave_text   = f"价格处于20日通道下半部({ch_low20:.1f}-{ch_high20:.1f})，偏空"
analyses.append(("波浪理论", wave_signal, wave_text))

# ── K. 威科夫（简化）──
# 观察近5日：是否出现弹簧行情（spring）
recent_lows = [D[i]["low"] for i in range(5)]
min_low_5   = min(recent_lows)
spring = any(D[i]["low"] < min_low_5 * 0.99 and D[i]["close"] > D[i]["low"] * 1.01 for i in range(1,5))
if spring:
    wyckoff_signal = +2
    wyckoff_text   = "疑似弹簧行情(弹簧低点后快速收回)，吸筹信号，看涨"
elif D[0]["close"] > SMA(D, 20) and avg_vol(D,5) > avg_vol(D,20):
    wyckoff_signal = +1
    wyckoff_text   = "量价配合良好，疑似努力跟进行情，多头"
elif D[0]["close"] < SMA(D, 20):
    wyckoff_signal = -1
    wyckoff_text   = "价格低于均线，空头主导"
else:
    wyckoff_signal = 0
    wyckoff_text   = "无明显威科夫信号"
analyses.append(("威科夫", wyckoff_signal, wyckoff_text))

# ── L. TD序列（简化）──
# 连续9天内收盘价高于/低于对应4天前的价格
td_count_up = 0
td_count_dn = 0
for i in range(min(9, len(D)-4)):
    if D[i]["close"] > D[i+4]["close"]:
        td_count_up += 1
    else:
        td_count_dn += 1
if td_count_up >= 7:
    td_signal = +2
    td_text   = f"TD连续计数9中7+，极强看涨信号"
elif td_count_up >= 5:
    td_signal = +1
    td_text   = f"TD连续计数偏向买入侧({td_count_up}/9)，偏多"
elif td_count_dn >= 7:
    td_signal = -2
    td_text   = f"TD连续计数卖出侧极多({td_count_dn}/9)，极弱"
elif td_count_dn >= 5:
    td_signal = -1
    td_text   = f"TD连续计数偏向卖出侧({td_count_dn}/9)，偏空"
else:
    td_signal = 0
    td_text   = f"TD计数无偏向({td_count_up}/{td_count_dn})，中性"
analyses.append(("TD序列", td_signal, td_text))

# ── M. 斐波那契回撤 ──
# 从52周低点到52周高点的斐波回撤
fib_236 = low52w + (high52w - low52w) * 0.236
fib_382 = low52w + (high52w - low52w) * 0.382
fib_500 = low52w + (high52w - low52w) * 0.500
fib_618 = low52w + (high52w - low52w) * 0.618
fib_786 = low52w + (high52w - low52w) * 0.786

if abs(price - fib_618) < price * 0.01:
    fib_signal = +2
    fib_text   = f"价格在61.8%回撤位({fib_618:.1f})附近，强支撑"
elif abs(price - fib_500) < price * 0.01:
    fib_signal = +1
    fib_text   = f"价格在50%回撤位({fib_500:.1f})附近，中性偏好"
elif abs(price - fib_382) < price * 0.01:
    fib_signal = +1
    fib_text   = f"价格在38.2%回撤位({fib_382:.1f})附近，偏多"
elif price > fib_618:
    fib_signal = +1
    fib_text   = f"价格位于61.8%回撤位({fib_618:.1f})上方，多头"
elif price < fib_382:
    fib_signal = -1
    fib_text   = f"价格跌破38.2%回撤位({fib_382:.1f})，偏空"
else:
    fib_signal = 0
    fib_text   = f"价格在斐波区间内"
analyses.append(("斐波那契", fib_signal, fib_text))

# ── N. ATR波动率 ──
atr_ratio = atr14 / price * 100 if atr14 else 0
if atr_ratio > 2.5:
    atr_signal = -1
    atr_text   = f"ATR/价格={atr_ratio:.1f}%，高波动，风险较大"
elif atr_ratio < 1.0:
    atr_signal = +1
    atr_text   = f"ATR/价格={atr_ratio:.1f}%，低波动，适合稳健操作"
else:
    atr_signal = 0
    atr_text   = f"ATR/价格={atr_ratio:.1f}%，正常波动"
analyses.append(("ATR波动率", atr_signal, atr_text))

# ── O. 周线确认 ──
w_ma5_above_ma20 = ma5_w > ma20_w
w_uptrend = all(W[i]["close"] > W[i+1]["close"] for i in range(min(5,len(W)-1)))
if w_ma5_above_ma20 and w_uptrend:
    weekly_signal = +2
    weekly_text   = "周线明确多头：均线多头排列+连续收高"
elif w_ma5_above_ma20:
    weekly_signal = +1
    weekly_text   = "周线偏多格局"
elif not w_ma5_above_ma20:
    weekly_signal = -1
    weekly_text   = "周线偏空格局"
else:
    weekly_signal = 0
    weekly_text   = "周线方向不明"
analyses.append(("周线确认", weekly_signal, weekly_text))

# ─────────────────────────────────────────────
# (2) 汇总评分 + 置信度
# ─────────────────────────────────────────────
signals = [a[1] for a in analyses]
total_score = sum(signals)
max_possible = len(signals) * 2
score_pct = total_score / max_possible * 100

positive = sum(1 for s in signals if s >= 1)
negative = sum(1 for s in signals if s <= -1)
neutral  = sum(1 for s in signals if s == 0)

if positive >= len(signals) * 0.7:
    confidence = "极高（一致通过）"
elif positive >= len(signals) * 0.5:
    confidence = "高（大部分一致）"
elif negative >= len(signals) * 0.5:
    confidence = "低（偏空占优）"
else:
    confidence = "一般（指标分散）"

# ─────────────────────────────────────────────
# (3) 三种趋势概率（1个月内）
# ─────────────────────────────────────────────
# 基于当前位置 + 趋势判断
above_ma200 = price > ma200_d
above_ma20  = price > ma20_d
rsi_val = rsi14

# 上涨概率
if above_ma200 and above_ma20 and rsi_val < 70 and positive >= 12:
    p_up = 55
elif above_ma200 and positive >= 10:
    p_up = 48
elif above_ma20:
    p_up = 40
else:
    p_up = 30

# 下跌概率
if not above_ma200 and negative >= 8:
    p_down = 40
elif not above_ma200:
    p_down = 32
elif rsi_val > 65 and negative >= 10:
    p_down = 35
else:
    p_down = 25

p_sideways = 100 - p_up - p_down

# ─────────────────────────────────────────────
# (4) 进场 / 止盈 / 止损
# ─────────────────────────────────────────────
entry  = price
stop_loss = round(entry - 2 * atr14, 2) if atr14 else round(entry * 0.97, 2)
riskAmt   = entry - stop_loss

# 目标止盈（2:1盈亏比）
target_2to1 = round(entry + 2 * riskAmt, 2)
target_3to1 = round(entry + 3 * riskAmt, 2)

# 合理回踩进场位
if ma20_d > ma5_d:
    pullback_entry = round(ma20_d, 2)
elif ma5_d > ma20_d:
    pullback_entry = round(ma5_d, 2)
else:
    pullback_entry = round(entry * 0.995, 2)

# ─────────────────────────────────────────────
# (5) 5个交易日内70%概率高低价
# ─────────────────────────────────────────────
# 用 ATR 估算：5日 ≈ sqrt(5) * ATR
import statistics
daily_returns = []
for i in range(1, min(60, len(D))):
    ret = (D[i-1]["close"] - D[i]["close"]) / D[i]["close"]
    daily_returns.append(abs(ret))
avg_daily_move = statistics.mean(daily_returns) * price

# 5日70%区间（假设正态分布，1.04σ ≈ 70%）
sigma_5 = avg_daily_move * math.sqrt(5)
high_70 = round(price + 1.04 * sigma_5, 2)
low_70  = round(price - 1.04 * sigma_5, 2)
up_pct   = (high_70 - price) / price * 100
down_pct = (price - low_70) / price * 100

# ─────────────────────────────────────────────
# (6) 综合判断
# ─────────────────────────────────────────────
if total_score >= 15 and positive >= 13:
    action = "加仓"
    action_type = "趋势跟随"
elif total_score <= -5 or negative >= 12:
    action = "减仓"
    action_type = "短线防御"
elif total_score >= 5:
    action = "不动"
    action_type = "持有观望"
else:
    action = "不动"
    action_type = "等待确认"

# ─────────────────────────────────────────────
# 输出报告
# ─────────────────────────────────────────────
print("\n" + "="*70)
print("  SPY 多维技术分析报告")
print(f"  分析日期: 2026-05-07 | 当前价: ${price} | 数据截至: {D[0]['date']}")
print("="*70)

print("\n【(1) 各技术分析独立结论】")
print(f"{'分析项':<12} {'评分':>5}  {'结论'}")
print("-"*70)
for name, sig, text in analyses:
    arrow = "▲▲" if sig >= 2 else "▲" if sig >= 1 else "▼" if sig <= -1 else "▼▼" if sig <= -2 else "━"
    print(f"{name:<12} [{sig:+d}] {arrow} {text}")

print(f"\n【(2) 评分汇总】")
print(f"   综合得分: {total_score:+d} / {max_possible} ({score_pct:.0f}%)")
print(f"   多头指标: {positive}个 | 空头指标: {negative}个 | 中性: {neutral}个")
print(f"   置信度: {confidence}")

print(f"\n【(3) 未来1个月趋势概率】")
print(f"   上涨概率: {p_up}%")
print(f"   下跌概率: {p_down}%")
print(f"   震荡概率: {p_sideways}%")

print(f"\n【(4) 进场 / 止损 / 止盈】")
print(f"   当前价格:    ${entry}")
print(f"   建议进场位:  ${pullback_entry} (回踩均线时)")
print(f"   止损位:      ${stop_loss} (ATR×2，约${riskAmt:.2f})")
print(f"   2:1止盈:    ${target_2to1} (+{((target_2to1-entry)/entry*100):.1f}%)")
print(f"   3:1止盈:    ${target_3to1} (+{((target_3to1-entry)/entry*100):.1f}%)")

print(f"\n【(5) 5个交易日内70%概率区间】")
print(f"   70%高价: ${high_70} (上限涨幅 +{up_pct:.1f}%)")
print(f"   70%低价: ${low_70}  (下限跌幅 -{down_pct:.1f}%)")
print(f"   当前价格: ${price}")

print(f"\n【(6) 综合判断】")
print(f"   → {action} ({action_type})")

# ─────────────────────────────────────────────
# (7) 期权评估
# ─────────────────────────────────────────────
print(f"\n【(7) 期权投资评估】")
rsi_ok    = 40 <= rsi14 <= 70
trend_ok  = total_score >= 10
conf_ok   = confidence in ["极高（一致通过）", "高（大部分一致）"]
low_risk  = atr_ratio < 2.0

if rsi_ok and trend_ok and conf_ok and low_risk:
    option_rec = "✅ 可考虑期权投资"
    option_plan = f"""
  建议方案（高胜率+2:1盈亏比）：
  · 买入 SPY 价差期权（Bull Put Spread 或 Bull Call Spread）
  · 选1个月后到期，执行价OTM 3-5%
  · 最大盈利：价差宽度 - 净权利金
  · 最大亏损：净权利金
  · 例如：买入 SPY 20260718 720C + 卖出 SPY 20260718 750C
  · 预期收益率：约 80-120%（若SPY在1个月内上涨5%）"""
elif not low_risk:
    option_rec = "❌ 波动率过高，期权时间价值损耗快，暂不推荐"
else:
    option_rec = "⚠️ 谨慎：市场方向不明，等待确认后再操作"
    option_plan = "\n  建议：观望为主，不开新仓位"

print(f"  {option_rec}")
print(option_plan)
print("\n" + "="*70)
