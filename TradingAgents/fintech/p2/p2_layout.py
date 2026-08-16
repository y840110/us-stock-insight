from __future__ import annotations
import sys, json, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime, timedelta
from typing import Dict, Any

# ───────────────────────────────────────────────────────────────
# 常量
# ───────────────────────────────────────────────────────────────

BULL_REGIMES    = {"BULL_TREND", "EXPANSION", "RECOVERY", "LOW_RISK"}
BEAR_REGIMES    = {"RISK_OFF", "CURDLE", "STRESS", "HIGH_RISK", "BEARISH"}
NEUTRAL_REGIMES = {"NEUTRAL", "CAUTION"}

REGIME_FAMILY = {
    "BULL_TREND":  {"family":"偏多","desc":"上升趋势，趋势跟随为主","action":"多头或加仓"},
    "EXPANSION":   {"family":"偏多","desc":"经济扩张期，成长股领涨","action":"多头为主"},
    "RECOVERY":    {"family":"偏多","desc":"复苏期，宽松政策利好成长","action":"多头配置"},
    "LOW_RISK":    {"family":"偏多","desc":"风险低，环境有利多头","action":"正常多头"},
    "RISK_OFF":    {"family":"防御","desc":"风险资产抛售，现金为王","action":"清仓或对冲"},
    "CURDLE":      {"family":"防御","desc":"紧缩后期，信用风险上升","action":"降低仓位"},
    "STRESS":      {"family":"防御","desc":"市场压力极大，系统性风险","action":"离场"},
    "HIGH_RISK":   {"family":"防御","desc":"高风险环境","action":"清仓"},
    "BEARISH":     {"family":"偏空","desc":"下跌趋势，顺势做空或空仓","action":"空头或空仓"},
    "NEUTRAL":     {"family":"中性","desc":"方向不明，震荡整理","action":"观望或区间操作"},
    "CAUTION":     {"family":"中性","desc":"谨慎对待，防控风险为主","action":"轻仓试探"},
}

# 指标解释字典：(名称, 说明, 阈值区间, 单位)
# 阈值格式: (lo_bad, lo_warn, hi_warn, hi_bad, direction)
# lo_bad~lo_warn = 差(红), lo_warn~hi_warn = 正常/黄, hi_warn~hi_bad = 好(绿)
# direction: "auto"=两侧判断, "low"=越低越好, "high"=越高越好, "above"=>0好, "below"=<0好
# 对于非对称指标，直接写字符串如 ">0偏多" 或 "百分比/倍数"
INDICATOR_BANDS = {
    "SPY_CLOSE":          ("SPY收盘价",          "绝对价格",                                            None),
    "SPY_EMA20":          ("EMA20",              "价格在EMA20上方=偏多",                                  None),
    "SPY_SMA50":          ("SMA50",              "价格在SMA50上方=偏多",                                  None),
    "SPY_SMA200":         ("SMA200",             "价格在SMA200上方=长多",                                None),
    "SPY_RSI14":          ("RSI(14)",            "超买>70 | 超卖<30；高位钝化需结合背离判断",            (25,35,70,80,"auto")),
    "MACD_HISTOGRAM":     ("MACD直方图",         "由负转正=多头信号；持续放大=趋势加速",               None),
    "BB_PERCENT":         ("BB%位置",             ">0.95超买 | <0.05超卖",                                (0.05,0.20,0.80,0.95,"auto")),
    "BB_BANDWIDTH":        ("BB带宽",              "收口=盘整即将突破，张口=趋势加速",                    None),
    "ATR14":              ("ATR(14)",             "实际波动幅度，用于止损止盈计算",                      None),
    "VIX":               ("VIX",                 ">25高波动 | <15低波动自满",                            (10,15,25,35,"auto")),
    "VVIX":              ("VVIX",                "VIX预期波动率；极端值预警",                              (50,70,120,150,"auto")),
    "VIX9D":             ("VIX 9D",              "短期VIX变化率",                                        None),
    "VIX1M":             ("VIX 1M",              "中期VIX变化率",                                        None),
    "NYAD_SLOPE":        ("NYAD斜率",            ">0上涨趋势 | <0下跌；与SPY背离=关键信号",             (-30,-15,15,30,"auto")),
    "SPY_NEW_HIGH":       ("SPY创20日新高",       "是=确认上升趋势；否=警惕顶部结构",                 None),
    "SP500_ABOVE_50MA":  ("SP500>50MA%",         ">60%强势广度 | <40%弱势广度",                         (0.30,0.40,0.60,0.70,"auto")),
    "SP500_ABOVE_200MA": ("SP500>200MA%",        ">50%长期健康 | <30%长期弱势",                         (0.20,0.30,0.50,0.60,"auto")),
    "NEW_HIGH_LOW_RATIO": ("新高/新低比",          ">1.0多头格局 | <0.5空头格局",                          (0.3,0.5,1.5,2.0,"auto")),
    "HY_SPREAD":          ("HY利差(%)",           ">5%预警 | >7%危机 | <3.5%风险偏好",                 (3.0,3.5,5.5,7.0,"auto")),
    "FCI":               ("FCI",                 ">0紧缩 | <0宽松",                                      (-0.5,-0.2,0.8,1.5,"auto")),
    "GEX":               ("GEX",                 ">0缓冲支撑 | <0空头对冲助跌",                          None),
    "PUT_CALL_RATIO":    ("Put/Call比",           ">1.0恐慌抄底 | <0.5乐观",                             (0.4,0.5,1.0,1.2,"auto")),
    "CTA_POSITIONING":   ("CTA仓位%ile",          "<15极度做空(逼空风险) | >85极度做多(回调风险)",       (0,10,85,95,"auto")),
    "REALIZED_VOL":      ("已实现波动率(%)",        "年化实际波动幅度",                                      (10,12,20,25,"auto")),
    "SPY_20D_RETURN":   ("SPY 20日收益",         ">5%强势 | <-5%弱势",                                   (-8,-5,5,8,"auto")),
    "SPY_5D_RETURN":    ("SPY 5日收益",           "短期动量",                                              None),
    "SPY_DISTANCE_EMA20":("SPY距EMA20%",           "价格在EMA20上方=强势",                                   None),
}

# ─────────────────────────────────────────────────────────────
# 工具函数
# ───────────────────────────────────────────────────────────────

def _esc(s):
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;").replace("'","&#39;")

def _regime_color(regime):
    colors = {
        "BULL_TREND":  ("#00c853","rgba(0,200,83,0.15)"),
        "RISK_OFF":    ("#ff1744","rgba(255,23,68,0.15)"),
        "CURDLE":      ("#ff6d00","rgba(255,109,0,0.15)"),
        "STRESS":      ("#ff1744","rgba(255,23,68,0.15)"),
        "HIGH_RISK":   ("#ff5252","rgba(255,82,82,0.15)"),
        "NEUTRAL":     ("#ffc107","rgba(255,193,7,0.15)"),
        "CAUTION":     ("#ff9800","rgba(255,152,0,0.15)"),
        "LOW_RISK":    ("#00e676","rgba(0,230,118,0.15)"),
        "RECOVERY":    ("#64dd17","rgba(100,221,23,0.15)"),
        "BEARISH":     ("#ff5252","rgba(255,82,82,0.15)"),
        "EXPANSION":   ("#00c853","rgba(0,200,83,0.15)"),
    }
    return colors.get(regime, ("#9e9e9e","rgba(158,158,158,0.15)"))

def _exp_color(pct):
    if pct >= 60: return "#00c853"
    if pct >= 30: return "#64dd17"
    if pct >= 10: return "#ffc107"
    return "#ff1744"

def _conf_color(c):
    if c >= 0.7: return "#00c853"
    if c >= 0.5: return "#ffc107"
    return "#ff5252"

def _change_color(val):
    if val is None or val == 0: return "#9e9e9e"
    return "#00c853" if val > 0 else "#ff5252"

def _arrow(val):
    if val is None or val == 0: return "→"
    return "↑" if val > 0 else "↓"

def _simple_state(regime):
    if regime in BULL_REGIMES:   return "牛"
    if regime in BEAR_REGIMES:   return "熊"
    if regime in NEUTRAL_REGIMES: return "震"
    return "震"

def _state_color(state):
    return {
        "牛": ("#00c853","rgba(0,200,83,0.15)"),
        "熊": ("#ff1744","rgba(255,23,68,0.15)"),
        "震": ("#ffc107","rgba(255,193,7,0.15)"),
    }.get(state, ("#9e9e9e","rgba(158,158,158,0.15)"))

# ───────────────────────────────────────────────────────────────
# 数据加载
# ───────────────────────────────────────────────────────────────

def _load_klines(ticker, trade_date, lookback=120):
    from p2_shared.utils import P1_KLINES, MID_KLINES
    # SPY/指数类数据存在中间过程目录
    if ticker.upper() == "SPY":
        path = MID_KLINES / (ticker.upper() + "_1d.json")
    else:
        path = P1_KLINES / (ticker.upper() + "_1d.json")
    if not path.exists(): return []
    try:
        with open(path) as f:
            raw = json.load(f)
        bars = raw.get("data", raw) if isinstance(raw, dict) else raw
        cutoff = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=lookback + 15)).strftime("%Y-%m-%d")
        return [b for b in bars if cutoff <= b.get("date","") <= trade_date]
    except Exception:
        return []

def _load_spy_bars(trade_date, lookback=30):
    return _load_klines("SPY", trade_date, lookback)

def _ema(closes, period):
    if len(closes) < period: return float("nan")
    k = 2.0 / (period + 1)
    ema_val = float(closes[0])
    for c in closes[1:]:
        ema_val = float(c) * k + ema_val * (1 - k)
    return ema_val

def _rsi(closes, period=14):
    if len(closes) < period + 2: return float("nan")
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = float(closes[i]) - float(closes[i-1])
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0: return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

def _atr(bars, period=14):
    if len(bars) < period + 1: return None
    trs = []
    for i in range(1, len(bars)):
        h = float(bars[i]["high"]); l = float(bars[i]["low"])
        pc = float(bars[i-1]["close"])
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs[-period:]) / period

# ───────────────────────────────────────────────────────────────
# 计算 SPY 支撑/压力位
# ───────────────────────────────────────────────────────────────

def compute_support_resistance(trade_date, v):
    bars = _load_klines("SPY", trade_date, 120)
    close  = v.get("SPY_CLOSE")
    ema20  = v.get("SPY_EMA20")
    sma50  = v.get("SPY_SMA50")
    sma200 = v.get("SPY_SMA200")
    rsi14  = v.get("SPY_RSI14")

    if not bars or close is None: return {}

    closes = [float(b["close"]) for b in bars]
    highs  = [float(b["high"])  for b in bars]
    lows   = [float(b["low"])   for b in bars]
    vols   = [float(b.get("volume", 0)) for b in bars]

    y_h = highs[-2]; y_l = lows[-2]; y_c = closes[-2]
    pp  = (y_h + y_l + y_c) / 3
    r1  = 2 * pp - y_l;  r2 = pp + (y_h - y_l);    r3 = y_h + 2 * (pp - y_l)
    s1  = 2 * pp - y_h;  s2 = pp - (y_h - y_l);    s3 = y_l - 2 * (y_h - pp)

    low_20  = min(lows[-20:]); high_20 = max(highs[-20:]); rng = high_20 - low_20
    mean20  = sum(closes[-20:]) / 20
    std20   = math.sqrt(sum((c - mean20) ** 2 for c in closes[-20:]) / 20)
    bb_up   = mean20 + 2 * std20; bb_low = mean20 - 2 * std20

    typical = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    cum_vol, cum_pv = 0.0, 0.0
    for p, vol in zip(typical, vols):
        cum_vol += vol; cum_pv += p * vol
    vwap = cum_pv / cum_vol if cum_vol > 0 else close

    atr14  = _atr(bars[-15:]) if len(bars) >= 15 else None
    atr_pct = (atr14 / close * 100) if atr14 else 1.5
    vol_adj = 1.0 if atr_pct < 1.5 else (0.92 if atr_pct < 2.5 else 0.82)

    # 构建候选：支撑（<现价-0.3），压力（>现价+0.3）
    cands = []
    if s3  < close - 0.5: cands.append(("S3_Pivot",  round(s3, 2),  "sup"))
    if s2  < close - 0.5: cands.append(("S2_Pivot",  round(s2, 2),  "sup"))
    if s1  < close - 0.5: cands.append(("S1_Pivot",  round(s1, 2),  "sup"))
    if bb_low < close - 0.3: cands.append(("BB下轨",   round(bb_low, 2), "sup"))
    if ema20  and ema20  < close - 0.5: cands.append(("EMA20",    round(ema20, 2),  "sup"))
    if sma50  and sma50  < close - 0.5: cands.append(("SMA50",    round(sma50, 2),  "sup"))
    if sma200 and sma200 < close - 0.5: cands.append(("SMA200",   round(sma200, 2), "sup"))
    cands.append(("20日最低", round(low_20, 2), "sup"))
    cands.append(("Pivot_PP", round(pp, 2),    "both"))
    cands.append(("VWAP",     round(vwap, 2),   "both"))
    if ema20  and ema20  > close + 0.5: cands.append(("EMA20",    round(ema20, 2),  "res"))
    if sma50  and sma50  > close + 0.5: cands.append(("SMA50",    round(sma50, 2),  "res"))
    if sma200 and sma200 > close + 0.5: cands.append(("SMA200",   round(sma200, 2), "res"))
    if high_20 > close + 0.3: cands.append(("20日最高",  round(high_20, 2), "res"))
    if bb_up   > close + 0.3: cands.append(("BB上轨",    round(bb_up, 2),   "res"))
    if rng > 1.0:
        for fp, lbl in [(0.236,"Fib_236"),(0.382,"Fib_382"),(0.500,"Fib_500"),(0.618,"Fib_618")]:
            lvl = high_20 - rng * fp
            if lvl > close + 0.5: cands.append((lbl, round(lvl, 2), "res"))
    if r1 > close + 0.5: cands.append(("R1_Pivot", round(r1, 2), "res"))
    if r2 > close + 0.5: cands.append(("R2_Pivot", round(r2, 2), "res"))
    if r3 > close + 0.5: cands.append(("R3_Pivot", round(r3, 2), "res"))

    sup_levels, res_levels = [], []
    for name, level, kind in cands:
        if kind in ("sup", "both") and level < close - 0.3:
            sup_levels.append((name, level, abs(close - level) / close * 100))
        if kind in ("res", "both") and level > close + 0.3:
            res_levels.append((name, level, abs(level - close) / close * 100))

    sup_levels.sort(key=lambda x: x[2])
    res_levels.sort(key=lambda x: x[2])
    top_sup = sup_levels[:3]
    top_res = res_levels[:3]

    def hold_prob(level, direction):
        tests, tol = 0, 0.012
        for lo, hi, cl in zip(lows, highs, closes):
            if lo <= level <= hi:
                if direction == "sup" and cl >= level * (1 - tol): tests += 1
                if direction == "res" and cl <= level * (1 + tol): tests += 1
        base = min(62 + tests * 2.5, 91) if tests > 0 else 62.0
        dist = abs(close - level) / close  # 距离越近，可靠性越高
        # 线性递减：0%距离=+9, 10%距离=-5，中间线性插值
        dist_bonus = 9.0 - dist * 140  # 0%→+9, 10%→-5
        dist_bonus = max(-6, min(9, dist_bonus))
        base += dist_bonus
        return round(min(base * vol_adj, 95), 1)

    def dist_str(lv):
        return "{:+.2f}%".format((close - lv) / lv * 100)

    result = {
        "close":    round(close, 2),
        "ema20":    round(ema20, 2)  if ema20  else None,
        "sma50":    round(sma50, 2)  if sma50  else None,
        "sma200":   round(sma200, 2) if sma200 else None,
        "atr_pct":  round(atr_pct, 2),
        "vol_adj":   round(vol_adj, 2),
        "rsi":      round(rsi14, 1) if rsi14 else None,
    }
    for i, (nm, lv, dist) in enumerate(top_sup, 1):
        result["sup{}_name".format(i)] = nm
        result["sup{}".format(i)]      = lv
        result["sup{}_dist".format(i)] = dist_str(lv)
        result["sup{}_prob".format(i)] = hold_prob(lv, "sup")
    for i, (nm, lv, dist) in enumerate(top_res, 1):
        result["res{}_name".format(i)] = nm
        result["res{}".format(i)]      = lv
        result["res{}_dist".format(i)] = dist_str(lv)
        result["res{}_prob".format(i)] = hold_prob(lv, "res")
    result["above_ema20"]  = (close > ema20)  if ema20  else None
    result["above_sma50"]  = (close > sma50)  if sma50  else None
    result["above_sma200"] = (close > sma200) if sma200 else None
    return result

# ───────────────────────────────────────────────────────────────
# 计算指标变化
# ───────────────────────────────────────────────────────────────

def compute_indicator_changes(trade_date, v):
    bars = _load_spy_bars(trade_date, 35)
    result = {}
    if bars and len(bars) >= 6:
        cs = [float(b["close"]) for b in bars]
        result["SPY_CLOSE"]   = round(cs[-1], 2)
        result["SPY_5D_AGO"]  = round(cs[-6], 2)   if len(cs) >= 6  else None
        result["SPY_20D_AGO"] = round(cs[-21], 2)  if len(cs) >= 21 else None
        result["SPY_5D_CHG"]  = round((cs[-1] - cs[-6]) / cs[-6] * 100, 2) if len(cs) >= 6 else None
        result["SPY_20D_CHG"] = round((cs[-1] - cs[-21]) / cs[-21] * 100, 2) if len(cs) >= 21 else None
        result["RSI_5D_AGO"]  = round(_rsi(cs[:-5] if len(cs) > 5 else cs, 14), 1) if len(cs) >= 6 else None
        result["RSI_5D_CHG"]  = round(_rsi(cs, 14) - _rsi(cs[:-5] if len(cs) > 5 else cs, 14), 1) if len(cs) >= 6 else None
        result["RSI_20D_AGO"] = round(_rsi(cs[:-20] if len(cs) > 20 else cs, 14), 1) if len(cs) >= 21 else None
        result["RSI_20D_CHG"] = round(_rsi(cs, 14) - _rsi(cs[:-20] if len(cs) > 20 else cs, 14), 1) if len(cs) >= 21 else None
        result["ATR_NOW"]     = round(_atr(bars, 14), 3) if len(bars) >= 15 else None
        result["ATR_5D_AGO"]  = round(_atr(bars[:-5] if len(bars) > 5 else bars, 14), 3) if len(bars) >= 6 else None
        result["ATR_5D_CHG"]  = None
        if len(bars) >= 6 and _atr(bars[:-5], 14):
            a_now = _atr(bars, 14); a_old = _atr(bars[:-5], 14)
            if a_old > 0: result["ATR_5D_CHG"] = round((a_now - a_old) / a_old * 100, 1)
    return result

# ───────────────────────────────────────────────────────────────
# 市场状态 + 变盘信号
# ───────────────────────────────────────────────────────────────

def _judge_market_state(v):
    vix = v.get("VIX") or 20
    nyad = v.get("NYAD_SLOPE") or 0
    cta = v.get("CTA_POSITIONING") or 50
    bb = v.get("BB_PERCENT") or 0.5
    fci = v.get("FCI") or 0
    hy = v.get("HY_SPREAD") or 4
    risk = 0
    # 收紧阈值：VIX须明显偏高才算风险
    if vix > 35:  risk += 3
    elif vix > 28: risk += 2
    elif vix > 22: risk += 1
    # NYAD须明显恶化
    if nyad < -40: risk += 2
    elif nyad < -15: risk += 1
    # CTA须极度做空（<10%分位）才算风险
    if cta < 10:  risk += 2
    elif cta < 20: risk += 1
    # BB须在极端区域
    if bb > 0.93: risk += 1
    elif bb > 0.88: risk += 0.5
    # HY利差须明显走阔
    if hy > 7:   risk += 2
    elif hy > 5.5: risk += 1
    # FCI须明显紧缩
    if fci > 1.5: risk += 1
    elif fci > 0.8: risk += 0.5
    bull = 0
    # VIX须明显低才算安全
    if vix < 12: bull += 2
    elif vix < 15: bull += 1
    # NYAD须明显强势
    if nyad > 25: bull += 2
    elif nyad > 12: bull += 1
    # CTA须极度做多
    if cta > 80: bull += 2
    elif cta > 65: bull += 1
    # BB须在极端区域
    if bb < 0.08: bull += 1
    elif bb < 0.2: bull += 0.5
    net = bull - risk
    if net >= 3:
        return ("🐂 牛市", "#00c853", "多方主导：VIX低位 + NYAD强势 + 广度健康 + CTA未极度做空")
    if net >= 1.5:
        return ("📈 偏多", "#64dd17", "偏多格局：部分风险指标改善，需警惕VIX和NYAD背离")
    if net <= -3:
        return ("🐻 熊市", "#ff1744", "空方主导：VIX高企 + NYAD下跌 + 宏观紧缩延续")
    if net <= -1.5:
        return ("⚠️ 偏空", "#ff6d00", "偏空格局：风险资产承压，保持防御，控制仓位")
    return ("⚖️ 震荡", "#ffc107", "多空博弈：方向不明，震荡整理")


def _judge_shift_signal(v):
    signals = []
    rsi  = v.get("SPY_RSI14") or 50
    vix  = v.get("VIX") or 20
    nyad = v.get("NYAD_SLOPE") or 0
    bb   = v.get("BB_PERCENT") or 0.5
    cta  = v.get("CTA_POSITIONING") or 50
    macdh = v.get("MACD_HISTOGRAM") or 0
    atr   = v.get("ATR14") or 1
    atr_pk = v.get("ATR14_PEAK") or 0

    if rsi > 80:
        signals.append(("🔴 RSI极度超买", "RSI(14)={:.0f}，历史极值区域，警惕短期回调".format(rsi)))
    elif rsi > 70:
        signals.append(("🟠 RSI超买", "RSI(14)={:.0f}，高位钝化中，均值回归风险累积".format(rsi)))
    elif rsi < 25:
        signals.append(("🟢 RSI超卖", "RSI(14)={:.0f}，历史超卖区域，反弹概率较高".format(rsi)))
    elif rsi < 35:
        signals.append(("🟡 RSI偏低", "RSI(14)={:.0f}，偏低位，均值回归机会".format(rsi)))
    if vix > 30:
        signals.append(("🔴 VIX极度恐慌", "VIX={:.0f}，历史恐慌区，危机定价中".format(vix)))
    elif vix > 25:
        signals.append(("🟠 VIX高位", "VIX={:.0f}，市场紧张，高波动常态".format(vix)))
    elif vix < 13:
        signals.append(("🟢 VIX低位", "VIX={:.0f}，自满区间，低波动预警".format(vix)))
    if nyad < -30 and v.get("SPY_NEW_HIGH"):
        signals.append(("🔴 NYAD严重背离", "NYAD斜率={:.0f}，SPY却创新高，顶背离警示".format(nyad)))
    elif nyad < -15:
        signals.append(("🟠 NYAD下行", "NYAD斜率={:.0f}，市场广度走弱，注意风险".format(nyad)))
    if bb > 0.95:
        signals.append(("🔴 BB%极度超买", "BB%={:.3f}，几乎触及上轨，极端区域".format(bb)))
    elif bb < 0.1:
        signals.append(("🟢 BB%极度超卖", "BB%={:.3f}，触及下轨，反弹机会".format(bb)))
    if cta < 12:
        signals.append(("🔴 CTA极度做空", "CTA={:.0f}%历史百分位，逼空风险极高".format(cta)))
    elif cta > 88:
        signals.append(("🔴 CTA极度做多", "CTA={:.0f}%历史百分位，回调风险累积".format(cta)))
    if macdh is not None and abs(macdh) < 0.5 and atr and atr > 0:
        signals.append(("🟡 MACD收缩", "MACD直方图接近零，势能减弱，震荡整理"))
    if atr_pk and atr and atr > 0 and atr / atr_pk < 0.3:
        signals.append(("🟡 ATR收敛", "ATR/ATR峰值={:.1%}，波动率极度收缩，突破在即".format(atr / atr_pk)))
    if not signals:
        signals.append(("⚪ 无极端信号", "各指标未触发极端阈值，市场相对均衡"))
    return signals


def _compute_5d_state(trade_date, v_today):
    """根据本地 SPY K线数据计算近5日市场状态，不调用 run() 避免重复分析。"""
    bars = _load_spy_bars(trade_date, 15)
    if len(bars) < 2:
        regime = v_today.get("SPY_MARKET_REGIME", "NEUTRAL")
        return [(trade_date[-5:], _simple_state(regime), regime)]
    closes = [float(b["close"]) for b in bars]
    if len(closes) < 6:
        regime = v_today.get("SPY_MARKET_REGIME", "NEUTRAL")
        dates_5d = [b["date"] for b in bars][-5:]
        return [(d[-5:], _simple_state(regime), regime) for d in reversed(dates_5d)]
    rsi = _rsi(closes)
    ret_5d = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else 0
    ret_20d = (closes[-1] / closes[-21] - 1) * 100 if len(closes) >= 21 else 0
    # 简单状态判断
    if rsi > 65 and ret_5d > 1:
        regime = "BULL_TREND"
    elif rsi < 40 or ret_5d < -2:
        regime = "RISK_OFF"
    elif abs(ret_20d) < 2 and 40 <= rsi <= 60:
        regime = "NEUTRAL"
    else:
        regime = v_today.get("SPY_MARKET_REGIME", "NEUTRAL")
    dates_5d = [b["date"] for b in bars][-5:]
    return [(d[-5:], _simple_state(regime), regime) for d in reversed(dates_5d)]

# ───────────────────────────────────────────────────────────────
# HTML 片段构建
# ───────────────────────────────────────────────────────────────



def _build_strategy_params(label, emoji, v, result) -> str:
    """构建策略参数详情区块"""
    regime   = result.get("market_regime", "N/A")
    reg_score= result.get("regime_score", 0)
    timing   = result.get("timing_state", "N/A")
    tim_score= result.get("timing_score", 0)
    risk     = result.get("risk_score", 5)

    if "策略A" in label or "动量" in label:
        return _momentum_params(v, result, regime, reg_score, timing, tim_score, risk)
    elif "策略B" in label or "宏观" in label:
        return _macro_params(v, result, regime, reg_score, timing, tim_score, risk)
    elif "策略C" in label or "ML" in label:
        return _ml_params(v, result, regime, reg_score, timing, tim_score, risk)
    elif "策略D" in label or "Agents" in label:
        return _agents_params(v, result, regime, reg_score, timing, tim_score, risk)
    return ""


def _score_bar(score, lo=-10, hi=10) -> str:
    """绘制分数条"""
    norm = (score - lo) / (hi - lo)
    w = max(5, min(95, norm * 100))
    color = "#00c853" if score > 0 else ("#ff1744" if score < 0 else "#ffc107")
    return "<div class='score-bar-wrap'><div class='score-bar-fill' style='width:{}%;background:{};position:absolute;height:6px;border-radius:3px'></div><div style='position:relative;height:6px;background:#21262d;border-radius:3px'></div></div>".format(w, color)


def _param_row(name, value, threshold="", note="", good_bad="", th_pos="value"):
    """生成参数行"""
    vb = ""
    if good_bad == "good" and value != "N/A":
        vb = "color:#00c853"
    elif good_bad == "bad" and value != "N/A":
        vb = "color:#ff1744"
    elif good_bad == "warn" and value != "N/A":
        vb = "color:#ffc107"
    vstr = "{}" if isinstance(value, (int, float)) and value != int(value) else "{}"
    val_html = ("<span style='" + vb + ";font-weight:700'>" + vstr + "</span>").format(value)
    th_html = ("<span class='thresh-note'>{}</span>").format(threshold) if threshold else "<span class='thresh-note'>—</span>"
    note_html = ("<span class='param-note'>{}</span>").format(note) if note else ""
    return (
        "<tr class='param-row'>"
        "<td class='param-name'>{}</td>"
        "<td class='param-value'>" + val_html + "</td>"
        "<td class='param-thresh'>" + th_html + "</td>"
        "<td class='param-note-cell'>" + note_html + "</td>"
        "</tr>"
    ).format(name)


# ─────────────────────────────────────────────────────────────────
# 策略A：动量趋势参数详情
# ─────────────────────────────────────────────────────────────────

def _momentum_params(v, result, regime, reg_score, timing, tim_score, risk) -> str:
    # 提取关键参数
    spy_close = v.get("SPY_CLOSE"); ema20 = v.get("SPY_EMA20"); sma50 = v.get("SPY_SMA50")
    sma200 = v.get("SPY_SMA200"); rsi = v.get("SPY_RSI14"); macdh = v.get("MACD_HISTOGRAM")
    macd_pk = v.get("MACD_HISTOGRAM_PEAK"); bb_pct = v.get("BB_PERCENT"); bb_bw = v.get("BB_BANDWIDTH")
    nyad_slp = v.get("NYAD_SLOPE"); above50 = v.get("SP500_ABOVE_50MA"); nh_nl = v.get("NEW_HIGH_LOW_RATIO")
    vix = v.get("VIX"); vix_ts = v.get("VIX_TERM_STRUCTURE"); vvix = v.get("VVIX")
    hy = v.get("HY_SPREAD"); liq = v.get("LIQUIDITY_SCORE"); gex = v.get("GEX")
    iwm_rs = v.get("IWM_RS_SLOPE"); vol_ratio = v.get("VOLUME_RATIO"); atr_comp = v.get("ATR_COMPRESSION")

    def fv(val, fmt="{:.2f}", na="—"):
        if val is None: return na
        try: return fmt.format(val)
        except: return str(val)

    # 计算各维度得分
    trend_score = 0; breadth_score = 0; vol_score = 0; credit_score = 0; option_score = 0

    # 趋势结构
    if spy_close and ema20 and spy_close > ema20: trend_score += 1
    if ema20 and sma50 and ema20 > sma50: trend_score += 1
    if sma50 and sma200 and sma50 > sma200: trend_score += 1
    if (v.get("SPY_EMA20_SLOPE") or 0 or 0) > 0: trend_score += 1

    # 广度
    if (nyad_slp or 0) > 0: breadth_score += 2
    if (above50 or 0) > 0.60: breadth_score += 1
    if (nh_nl or 0) > 1.5: breadth_score += 1
    if v.get("BREADTH_DIVERGENCE"): breadth_score -= 3
    if (iwm_rs or 0) < 0: breadth_score -= 1

    # 波动率
    if (vix or 99) < 20: vol_score += 1
    if (vix_ts or 0) > 0: vol_score += 1
    else: vol_score -= 2
    if (vvix or 0) > 110: vol_score -= 2

    # 信用+流动性
    if (hy or 999) < 4.2: credit_score += 1
    elif (hy or 0) >= 4.2: credit_score -= 2
    if (liq or 0) > 0: credit_score += 1
    else: credit_score -= 1

    # 期权
    if (gex or 0) > 0: option_score += 1
    else: option_score -= 2

    total = trend_score + breadth_score + vol_score + credit_score + option_score

    rows = ""
    rows += "<tr><td colspan='4' class='param-group-title'>📈 趋势结构</td></tr>"
    rows += _param_row("SPY_CLOSE", fv(spy_close), "> EMA20", "判断价格方向", "good" if (spy_close and ema20 and spy_close > ema20) else "bad")
    rows += _param_row("EMA20", fv(ema20), "> SMA50", "短期上升趋势", "good" if (ema20 and sma50 and ema20 > sma50) else "bad")
    rows += _param_row("SMA50", fv(sma50), "> SMA200", "中期上升趋势", "good" if (sma50 and sma200 and sma50 > sma200) else "bad")
    rows += _param_row("EMA20_SLOPE", fv(v.get("SPY_EMA20_SLOPE"), "{:+.4f}"), "> 0", "短期趋势方向")
    rows += "<tr><td colspan='4' class='param-group-title'>📊 广度分析</td></tr>"
    rows += _param_row("NYAD_SLOPE", fv(nyad_slp, "{:.1f}"), "> 0 (+2) / < 0 (-0)", "市场广度趋势", "good" if (nyad_slp or 0) > 0 else "bad")
    rows += _param_row("SP500>50MA%", fv(above50, "{:.1%}"), "> 60% (+1)", "标普广度")
    rows += _param_row("新高/新低比", fv(nh_nl, "{:.2f}"), "> 1.5 (+1)", "市场强弱")
    rows += _param_row("BREADTH_DIVERGENCE", v.get("BREADTH_DIVERGENCE", False), "存在 → -3", "顶背离警告", "bad" if v.get("BREADTH_DIVERGENCE") else "")
    rows += _param_row("IWM_RS_SLOPE", fv(iwm_rs, "{:+.4f}"), "< 0 → -1", "小盘股相对走弱")
    rows += "<tr><td colspan='4' class='param-group-title'>🌡️ 波动率</td></tr>"
    rows += _param_row("VIX", fv(vix, "{:.1f}"), "< 20 (+1) / > 22 (-1)", "市场恐慌度", "good" if (vix or 99) < 20 else ("bad" if (vix or 0) > 22 else ""))
    rows += _param_row("VIX_TERM_STRUCTURE", fv(vix_ts, "{:+.2f}"), "> 0 (+1) / < 0 (-2)", "VIX期限结构")
    rows += _param_row("VVIX", fv(vvix, "{:.1f}"), "> 110 → -2", "波动率波动率")
    rows += "<tr><td colspan='4' class='param-group-title'>💳 信用+流动性</td></tr>"
    rows += _param_row("HY_SPREAD", fv(hy, "{:.2f}%"), "< 4.2 (+1) / ≥ 4.2 (-2)", "高收益债利差", "good" if (hy or 999) < 4.2 else ("bad" if (hy or 0) >= 4.2 else ""))
    rows += _param_row("LIQUIDITY_SCORE", fv(liq, "{:.3f}"), "> 0 (+1) / < 0 (-1)", "流动性状态")
    rows += "<tr><td colspan='4' class='param-group-title'>📊 期权仓位</td></tr>"
    rows += _param_row("GEX", fv(gex, "{:.0f}"), "> 0 (+1) / < 0 (-2)", "Gamma指数", "good" if (gex or 0) > 0 else "bad")

    regime_table = (
        "<table class='regime-table'>"
        "<tr><th>Regime</th><th>条件</th><th>动作</th></tr>"
        "<tr><td style='color:#00c853'>BULL_TREND</td><td>score ≥ 8</td><td>趋势跟随，多头为主</td></tr>"
        "<tr><td style='color:#ffc107'>NEUTRAL</td><td>score ≥ 4</td><td>区间操作，仓位减半</td></tr>"
        "<tr><td style='color:#ff1744'>RISK_OFF</td><td>score &lt; 4</td><td>清仓/空仓</td></tr>"
        "</table>"
    )

    timing_table = (
        "<table class='regime-table'>"
        "<tr><th>Timing</th><th>条件</th></tr>"
        "<tr><td style='color:#00c853'>GOOD_ENTRY</td><td>score ≥ 2（RSI&lt;35/MACD&gt;0/BB扩张）</td></tr>"
        "<tr><td style='color:#ffc107'>NEUTRAL_TIMING</td><td>-3 &lt; score &lt; 2</td></tr>"
        "<tr><td style='color:#ff1744'>OVERHEATED</td><td>score ≤ -3（RSI&gt;75/BB极端）</td></tr>"
        "</table>"
    )

    return (
        "<div class='params-section'>"
        "<div class='params-title'>🔍 参数详情</div>"
        "<div class='score-summary'>"
        "<div class='score-row'>"
        "<span class='score-label'>Regime Score: <b style='color:{}'>{:+.0f}</b></span>"
        "<span class='score-sub'>(趋势{} + 广度{} + 波动{} + 信用{} + 期权{})</span>"
        "</div>"
        "<div class='score-detail-row'>"
        "<div class='score-item'>趋势结构: {:+d}</div>"
        "<div class='score-item'>广度: {:+d}</div>"
        "<div class='score-item'>波动率: {:+d}</div>"
        "<div class='score-item'>信用+流动性: {:+d}</div>"
        "<div class='score-item'>期权: {:+d}</div>"
        "</div>"
        "<div class='regime-table-wrap'>{}</div>"
        "<div class='timing-table-wrap'><div class='params-sub-title'>⏱️ Timing 判定规则</div>{}</div>"
        "</div>"
        "<div class='param-table-wrap'>"
        "<table class='param-table'>"
        "<thead><tr><th>参数</th><th>当前值</th><th>阈值 / 加分规则</th><th>说明</th></tr></thead>"
        "<tbody>{}</tbody>"
        "</table></div>"
        "<div class='param-footer-note'>"
        "⚠️ Regime判定: score≥8→BULL_TREND, ≥4→NEUTRAL, &lt;4→RISK_OFF<br>"
        "⚠️ 仓位 = 基础仓位 × max(0.2, 1 - risk_score×0.15)"
        "</div>"
        "</div>"
    ).format(
        "#00c853" if total >= 8 else ("#ffc107" if total >= 4 else "#ff1744"), total,
        trend_score, breadth_score, vol_score, credit_score, option_score,
        trend_score, breadth_score, vol_score, credit_score, option_score,
        regime_table, timing_table, rows
    )


# ─────────────────────────────────────────────────────────────────
# 策略B：宏观择时参数详情
# ─────────────────────────────────────────────────────────────────

def _macro_params(v, result, regime, reg_score, timing, tim_score, risk) -> str:
    fci = v.get("FCI"); hy = v.get("HY_SPREAD"); dxy = v.get("DXY")
    liq = v.get("LIQUIDITY_SCORE"); us10y = v.get("US10Y"); vix = v.get("VIX")
    rsi = v.get("SPY_RSI14"); bb_pct = v.get("BB_PERCENT")
    realized_vol = v.get("REALIZED_VOL")

    def fv(val, fmt="{:.2f}", na="—"):
        if val is None: return na
        try: return fmt.format(val)
        except: return str(val)

    score = 0
    # FCI
    if (fci or 0) < -0.2: score += 2
    elif (fci or 0) > 0.2: score -= 2
    # HY
    if (hy or 999) < 3.5: score += 2
    elif (hy or 999) < 4.2: score += 1
    elif (hy or 0) > 6.0: score -= 2
    elif (hy or 0) > 5.0: score -= 1
    # LIQ
    if (liq or 0) > 0.5: score += 1
    elif (liq or 0) < -0.5: score -= 1
    # VIX
    if (vix or 99) < 14: score += 1
    elif (vix or 0) > 28: score -= 2
    elif (vix or 0) > 22: score -= 1
    # DXY
    if (dxy or 100) < 95: score += 1
    elif (dxy or 0) > 105: score -= 1
    # US10Y
    if (us10y or 4.0) < 3.5: score += 1
    elif (us10y or 0) > 5.0: score -= 1

    mr_score = 0; mr_tags = []
    if (rsi or 50) < 25: mr_score += 3; mr_tags.append("RSI<25")
    elif (rsi or 50) < 35: mr_score += 2; mr_tags.append("RSI<35")
    elif (rsi or 50) > 80: mr_score -= 3; mr_tags.append("RSI>80")
    if (bb_pct or 0.5) > 0.90: mr_score -= 2; mr_tags.append("BB%极端")
    if (vix or 18) > 30: mr_score += 1; mr_tags.append("VIX>30逆向")

    mr_signal = "OVERSOLD" if mr_score >= 3 else ("OVERBOUGHT" if mr_score <= -2 else "NEUTRAL_REVERSION")

    rows = ""
    rows += "<tr><td colspan='4' class='param-group-title'>🏦 货币政策（FCI）</td></tr>"
    rows += _param_row("FCI", fv(fci, "{:.4f}"), "< -0.2 (+2) / > 0.2 (-2)", "金融状况指数", "good" if (fci or 0) < -0.2 else ("bad" if (fci or 0) > 0.2 else ""))
    rows += "<tr><td colspan='4' class='param-group-title'>💳 信用利差（HY）</td></tr>"
    rows += _param_row("HY_SPREAD", fv(hy, "{:.2f}%"), "< 3.5 (+2) / 3.5~4.2 (+1) / >5.0 (-1) / >6.0 (-2)", "经济健康度", "good" if (hy or 999) < 3.5 else ("bad" if (hy or 0) > 6.0 else ""))
    rows += "<tr><td colspan='4' class='param-group-title'>💧 流动性</td></tr>"
    rows += _param_row("LIQUIDITY_SCORE", fv(liq, "{:.3f}"), "> 0.5 (+1) / < -0.5 (-1)", "市场流动性", "good" if (liq or 0) > 0.5 else ("bad" if (liq or 0) < -0.5 else ""))
    rows += "<tr><td colspan='4' class='param-group-title'>🌡️ 市场恐慌（VIX）</td></tr>"
    rows += _param_row("VIX", fv(vix, "{:.1f}"), "< 14 (+1) / > 28 (-2) / > 22 (-1)", "恐慌指数", "good" if (vix or 99) < 14 else ("bad" if (vix or 0) > 28 else ""))
    rows += "<tr><td colspan='4' class='param-group-title'>💵 美元 + 利率</td></tr>"
    rows += _param_row("DXY", fv(dxy, "{:.2f}"), "< 95 (+1) / > 105 (-1)", "美元指数风险偏好")
    rows += _param_row("US10Y", fv(us10y, "{:.2f}%"), "< 3.5 (+1) / > 5.0 (-1)", "10年期国债收益率")
    rows += "<tr><td colspan='4' class='param-group-title'>📉 均值回归信号（Timing）</td></tr>"
    rows += _param_row("RSI(14)", fv(rsi, "{:.1f}"), "<25(+3) / <35(+2) / >80(-3)", "RSI超买超卖", "good" if (rsi or 50) < 35 else ("bad" if (rsi or 50) > 80 else ""))
    rows += _param_row("BB_PERCENT", fv(bb_pct, "{:.3f}"), "> 0.90 (-2)", "布林带位置", "bad" if (bb_pct or 0.5) > 0.90 else "")
    rows += _param_row("VIX", fv(vix, "{:.1f}"), "> 30 → +1逆向买入", "VIX极端逆向", "good" if (vix or 18) > 30 else "")
    rows += _param_row("均值回归信号", mr_signal + (" (" + ",".join(mr_tags) + ")" if mr_tags else ""), "≥3→OVERSOLD / ≤-2→OVERBOUGHT", "最终均值回归判定")

    regime_table = (
        "<table class='regime-table'>"
        "<tr><th>宏观Regime</th><th>标准Regime</th><th>条件(score)</th><th>建议</th></tr>"
        "<tr><td style='color:#00c853'>EXPANSION</td><td>BULL</td><td>≥ 4</td><td>经济增长，多头</td></tr>"
        "<tr><td style='color:#64dd17'>RECOVERY</td><td>BULL</td><td>1~3</td><td>宽松延续，成长</td></tr>"
        "<tr><td style='color:#ffc107'>NEUTRAL</td><td>NEUTRAL</td><td>-1~0</td><td>观望</td></tr>"
        "<tr><td style='color:#ff6d00'>CURDLE</td><td>RISK_OFF</td><td>-3~-1</td><td>防御降低仓位</td></tr>"
        "<tr><td style='color:#ff1744'>STRESS</td><td>RISK_OFF</td><td>&lt; -3</td><td>离场</td></tr>"
        "</table>"
    )

    return (
        "<div class='params-section'>"
        "<div class='params-title'>🔍 参数详情</div>"
        "<div class='score-summary'>"
        "<div class='score-row'>"
        "<span class='score-label'>宏观Score: <b style='color:{};font-size:16px'>{:+.0f}</b></span>"
        "<span class='score-sub'>→ {} → {}</span>"
        "</div>"
        "<div class='regime-table-wrap'>{}</div>"
        "</div>"
        "<div class='param-table-wrap'>"
        "<table class='param-table'>"
        "<thead><tr><th>参数</th><th>当前值</th><th>阈值</th><th>说明</th></tr></thead>"
        "<tbody>{}</tbody>"
        "</table></div>"
        "<div class='param-footer-note'>"
        "⚠️ 仓位 = 基础仓位 × max(0.15, 1 - risk_score×0.12)<br>"
        "⚠️ 均值回归信号: CURDLE/STRESS下VIX>30的OVERSOLD不作逆向买入"
        "</div>"
        "</div>"
    ).format(
        "#00c853" if score >= 4 else ("#64dd17" if score >= 1 else ("#ffc107" if score >= -1 else ("#ff6d00" if score >= -3 else "#ff1744"))),
        score,
        {">=4":"EXPANSION","1~3":"RECOVERY","-1~0":"NEUTRAL","-3~-1":"CURDLE","<-3":"STRESS"}.get(
            ">=4" if score >= 4 else "1~3" if score >= 1 else "-1~0" if score >= -1 else "-3~-1" if score >= -3 else "<-3", "—"
        ),
        regime,
        regime_table, rows
    )


# ─────────────────────────────────────────────────────────────────
# 策略C：ML概率参数详情
# ─────────────────────────────────────────────────────────────────

def _ml_params(v, result, regime, reg_score, timing, tim_score, risk) -> str:
    prob_gbr = result.get("prob_gbr"); prob_lr = result.get("prob_lr")
    prob_ens = result.get("prob_ensemble"); pct = result.get("prob_percentile", 0)
    stale = result.get("data_staleness_days") if result.get("data_staleness_days") is not None else (0 if result.get("data_fresh") else 999)

    def fp(val, na="—"): return "N/A" if val is None else "{:.2%}".format(val)

    rows = ""
    rows += "<tr><td colspan='4' class='param-group-title'>🤖 双模型概率</td></tr>"
    rows += _param_row("GBR (GradientBoosting)", fp(prob_gbr), "> 50% → CAUTION / < 30% → LOW_RISK", "主模型，26特征", "warn" if prob_gbr and prob_gbr > 0.5 else "good" if prob_gbr and prob_gbr < 0.3 else "")
    rows += _param_row("LR (Logistic Regression)", fp(prob_lr), "28特征含VIX+DXY，AUC=0.721", "回测+18.95%", "good" if prob_lr and prob_lr < 0.3 else "bad" if prob_lr and prob_lr > 0.5 else "")
    rows += _param_row("Ensemble均值", fp(prob_ens), "GBR+LR等权平均", "综合概率")
    rows += "<tr><td colspan='4' class='param-group-title'>📊 历史分位</td></tr>"
    rows += _param_row("历史百分位", "{:.0f}%".format(pct) if pct else "—", "> 70% → 高概率警惕 / < 30% → 低概率安全", "近300日历史分位", "bad" if pct and pct > 70 else "good" if pct and pct < 30 else "")
    rows += _param_row("数据新鲜度", "{}天".format(stale) if stale else "最新", "> 0 → ⚠️数据过期", "最后有效数据日期", "bad" if stale and stale > 0 else "good")

    regime_table = (
        "<table class='regime-table'>"
        "<tr><th>Regime</th><th>条件</th><th>基础仓位</th></tr>"
        "<tr><td style='color:#00e676'>LOW_RISK</td><td>prob &lt; 0.3 (score+2)</td><td>80%</td></tr>"
        "<tr><td style='color:#ff9800'>CAUTION</td><td>0.3 ≤ prob ≤ 0.5 (score-1)</td><td>40%</td></tr>"
        "<tr><td style='color:#ff1744'>RISK_OFF</td><td>prob &gt; 0.5 (score-2)</td><td>10%</td></tr>"
        "</table>"
    )

    risk_rows = ""
    if result.get("prob_gbr") is not None:
        risk_rows += _param_row("风险评分", str(risk) + "/10", "1~10，越高越降低仓位", "综合风险")
        risk_rows += _param_row("风险衰减系数", "{:.2f}".format(max(0.20, 1 - risk * 0.10)), "max(0.20, 1 - risk×0.10)", "仓位衰减")

    return (
        "<div class='params-section'>"
        "<div class='params-title'>🔍 参数详情</div>"
        "<div class='score-summary'>"
        "<div class='score-row'>"
        "<span class='score-label'>Ensemble概率: <b style='color:{};font-size:16px'>{}</b></span>"
        "<span class='score-sub'>历史分位: {:.0f}% | 数据: {}</span>"
        "</div>"
        "<div class='regime-table-wrap'>{}</div>"
        "</div>"
        "<div class='param-table-wrap'>"
        "<table class='param-table'>"
        "<thead><tr><th>参数</th><th>当前值</th><th>阈值规则</th><th>说明</th></tr></thead>"
        "<tbody>{}</tbody>"
        "</table></div>"
        "<div class='param-footer-note'>"
        "⚠️ 最终仓位 = 基础仓位 × 风险衰减系数 × max(0.20, 1 - risk×0.10)"
        "</div>"
        "</div>"
    ).format(
        "#ff9800" if prob_ens and 0.3 <= prob_ens <= 0.5 else ("#ff1744" if prob_ens and prob_ens > 0.5 else "#00e676"),
        fp(prob_ens), pct, "✅最新" if stale == 0 else "⚠️过期{}天".format(stale),
        regime_table, rows
    )


# ─────────────────────────────────────────────────────────────────
# 策略D：Agents辩论参数详情
# ─────────────────────────────────────────────────────────────────

def _agents_params(v, result, regime, reg_score, timing, tim_score, risk) -> str:
    bull_count = result.get("bull_count", 0); bear_count = result.get("bear_count", 0)
    bb_score = result.get("bull_bear_score", 0)
    decision = result.get("decision", "")
    debate_text = result.get("debate_text", "")
    signals = result.get("signals", [])

    agents_map = {
        "MarketAnalyst": "市场分析师",
        "FundamentalsAnalyst": "基本面分析师",
        "BullResearcher": "多头研究员",
        "BearResearcher": "空头研究员",
        "RiskDebater": "风险辩论者",
        "ResearchManager": "研究经理",
        "Trader": "交易员",
    }
    debate_map = {
        "BULL": "🐂 多头",
        "BEAR": "🐻 空头",
        "HOLD": "⏸️ 观望",
    }

    regime_table = (
        "<table class='regime-table'>"
        "<tr><th>决策</th><th>条件</th><th>仓位</th></tr>"
        "<tr><td style='color:#00c853'>BULL</td><td>bull_bear_score &gt; +0.1</td><td>70%</td></tr>"
        "<tr><td style='color:#ff1744'>BEAR</td><td>bull_bear_score &lt; -0.1</td><td>10%</td></tr>"
        "<tr><td style='color:#ffc107'>HOLD</td><td>-0.1 ≤ score ≤ +0.1</td><td>30%</td></tr>"
        "</table>"
    )

    rows = ""
    rows += "<tr><td colspan='4' class='param-group-title'>🗳️ 多空辩论统计</td></tr>"
    rows += _param_row("多空净分(标准化)", "{:+.3f}".format(bb_score) if bb_score is not None else "N/A", "> +0.1 → BULL / < -0.1 → BEAR / 否则 → HOLD", "多空博弈净分")
    rows += _param_row("最终决策", decision, "由ResearchManager裁定", "辩论最终结论")
    rows += "<tr><td colspan='4' class='param-group-title'>📝 辩论摘要</td></tr>"
    rows += "<tr><td colspan='4' class='debate-text-cell'>{}</td></tr>".format(_esc(debate_text[:300]) if debate_text else "（无）")

    bb_disp = "{:+.3f}".format(bb_score) if bb_score is not None else "N/A"
    return (
        "<div class='params-section'>"
        "<div class='params-title'>🔍 参数详情</div>"
        "<div class='score-summary'>"
        "<div class='score-row'>"
        "<span class='score-label'>辩论结果: <b style='color:{};font-size:16px'>{}</b></span>"
        "<span class='score-sub'>多空净分 {}</span>"
        "</div>"
        "<div class='regime-table-wrap'>{}</div>"
        "</div>"
        "<div class='param-table-wrap'>"
        "<table class='param-table'>"
        "<thead><tr><th>参数</th><th>当前值</th><th>判定规则</th><th>说明</th></tr></thead>"
        "<tbody>{}</tbody>"
        "</table></div>"
        "<div class='param-footer-note'>⚠️ Agents辩论通过6层Agent多角度博弈，最终由Research Manager综合裁定决策</div>"
        "</div>"
    ).format(
        "#00c853" if decision == "BULL" else ("#ff1744" if decision == "BEAR" else "#ffc107"),
        decision, bb_disp,
        regime_table, rows
    )


def _build_strategy_card(label, emoji, result, color, bg, v=None):
    regime    = result.get("market_regime", "N/A")
    reg_score = result.get("regime_score", 0)
    timing    = result.get("timing_state", "N/A")
    tim_score = result.get("timing_score", 0)
    risk      = result.get("risk_score", 5)
    exposure  = result.get("target_exposure", 0)
    confidence= result.get("confidence", 0.5)
    signals   = result.get("signals", [])
    interp    = result.get("interpretation", "")

    r_color, r_bg = _regime_color(regime)
    e_color = _exp_color(exposure)
    c_color = _conf_color(confidence)
    risk_c  = "#ff1744" if risk >= 7 else ("#ffc107" if risk >= 4 else "#00c853")

    # ── 策略参数详情 ──
    params_html = ""
    if v is not None:
        params_html = _build_strategy_params(label, emoji, v, result)

    extra_parts = []
    if "prob_ensemble" in result:
        p = result["prob_ensemble"]; pct = result.get("prob_percentile", 0)
        p_color = "#ff9800" if p > 0.4 else "#00e676"
        extra_parts.append("<div class='sig-row'><span class='sig-label'>Ensemble概率</span><span class='sig-value' style='color:{}'>{:.1%}</span></div>".format(p_color, p))
        extra_parts.append("<div class='sig-row'><span class='sig-label'>历史分位</span><span class='sig-value'>{:.0f}%</span></div>".format(pct))
    if result.get("prob_gbr") is not None:
        gbr_p = result.get("prob_gbr") or 0
        lr_p  = result.get("prob_lr") or 0
        gbr_c = "#d63939" if gbr_p < 0.3 else ("#ff9800" if gbr_p < 0.5 else "#00e676")
        lr_c  = "#d63939" if lr_p  < 0.3 else ("#ff9800" if lr_p  < 0.5 else "#00e676")
        gbr_bar = min(gbr_p * 100, 100)
        lr_bar  = min(lr_p  * 100, 100)
        extra_parts.append(
            "<div style='display:flex;flex-direction:column;gap:6px;margin-bottom:8px'>" +
            "<div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:2px'>" +
            "<div style='font-size:.78rem;font-weight:700;color:#d63939'>GBR</div>" +
            "<div style='font-size:1rem;font-weight:800;color:#d63939'>{:.1%}</div></div>".format(gbr_p) +
            "<div style='height:5px;background:#21262d;border-radius:3px;overflow:hidden'>" +
            "<div style='height:100%;width:{:.0f}%;background:#d63939;border-radius:3px'></div></div>".format(gbr_bar) +
            "<div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:2px'>" +
            "<div style='font-size:.78rem;font-weight:700;color:#ff9800'>LR</div>" +
            "<div style='font-size:1rem;font-weight:800;color:#ff9800'>{:.1%}</div></div>".format(lr_p) +
            "<div style='height:5px;background:#21262d;border-radius:3px;overflow:hidden'>" +
            "<div style='height:100%;width:{:.0f}%;background:#ff9800;border-radius:3px'></div></div>".format(lr_bar) +
            "</div>"
        )
    if result.get("decision"):
        extra_parts.append("<div class='sig-row'><span class='sig-label'>辩论决策</span><span class='sig-value' style='font-weight:700;color:#ffc150'>{}</span></div>".format(_esc(result["decision"])))
    bb_score = result.get("bull_bear_score")
    if bb_score is not None:
        bb_color = "#00c853" if bb_score > 0.1 else ("#ff1744" if bb_score < -0.1 else "#ffc107")
        bb_label = "偏多" if bb_score > 0.1 else ("偏空" if bb_score < -0.1 else "均衡")
        extra_parts.append("<div class='sig-row'><span class='sig-label'>多空净分</span><span class='sig-value' style='color:{}'>{} {:+.3f}</span></div>".format(bb_color, bb_label, bb_score))
    extra_html = "".join(extra_parts)
    sig_tags = "".join("<span class='sig-tag'>{}</span>".format(_esc(s)) for s in signals[:8])

    # ── Dominant-factor box for Momentum strategy (explains regime override) ──
    dominant_factors_html = ""
    if v is not None and label and "动量" in str(label):
        nyad = v.get("NYAD_SLOPE") or 0 or 0
        vts  = v.get("VIX_TERM_STRUCTURE") or 0 or 0
        hy   = v.get("HY_SPREAD") or 0 or 0
        gex  = v.get("GEX") or 0 or 0
        if nyad < 0 or vts <= 0 or hy >= 4.2 or gex <= 0:
            factors = []
            if nyad < 0:
                factors.append(("NYAD斜率", "{:.0f}".format(nyad), "负值，广度恶化"))
            if vts <= 0:
                factors.append(("VIX期限结构", "{:.0f}".format(vts), "严重倒挂，看空预警"))
            if hy >= 4.2:
                factors.append(("HY利差", "{:.1f}%".format(hy), "偏高，信用紧缩"))
            if gex <= 0:
                factors.append(("GEX", "{:.0f}".format(gex), "负GAMMA，机构做空"))
            if factors:
                rows_html = "".join(
                    "<div style='display:flex;align-items:center;margin-bottom:4px;font-size:.78rem'>"
                    "<div style='width:90px;color:#d63939;font-weight:700'>{}</div>"
                    "<div style='width:55px;color:#d63939;font-weight:700'>{}</div>"
                    "<div style='color:#9e9e9e'>{}</div></div>".format(n, v, r)
                    for n, v, r in factors)
                dominant_factors_html = (
                    "<div style='border-left:3px solid #d63939;background:rgba(214,57,57,0.08);"
                    "border-radius:6px;padding:8px 10px;margin-bottom:10px'>"
                    "<div style='font-size:.72rem;font-weight:700;color:#d63939;margin-bottom:5px'>"
                    "🚨 主导看空因子（覆盖价格均线多头信号）</div>"
                    + rows_html +
                    "<div style='font-size:.7rem;color:#9e9e9e;margin-top:4px;"
                    "border-top:1px solid rgba(214,57,57,0.2);padding-top:4px'>"
                    "→ 趋势结构满足（SPY>EMA20>SMA50>SMA200），"
                    "但宏观/信用/期权维度拖累 → Regime=🐻 风险规避</div></div>")

    deriv_parts = []
    deriv_parts.append("<div class='deriv-item'>▸ Regime判定: <b style='color:#58a6ff'>{}</b> (score={:+.0f}) → 决定基础仓位方向</div>".format(regime, reg_score))
    if timing:
        deriv_parts.append("<div class='deriv-item'>▸ Timing判定: <b>{}</b> (score={:+.0f}) → 影响入场时机和仓位调整</div>".format(_esc(timing), tim_score))
    risk_txt = "高风险，降低仓位" if risk >= 7 else ("中等风险" if risk >= 4 else "低风险，可适当加仓")
    deriv_parts.append("<div class='deriv-item'>▸ 风险评分: {:d}/10 → {}".format(risk, risk_txt))
    if "prob_ensemble" in result:
        p = result["prob_ensemble"]; pct = result.get("prob_percentile", 0)
        prob_txt = "低概率，安全" if p < 0.3 else ("中等概率，谨慎" if p < 0.5 else "高概率，警惕")
        deriv_parts.append("<div class='deriv-item'>▸ Ensemble概率: {:.1%}（历史{:.0f}%分位）→ {}".format(p, pct, prob_txt))
        stale = result.get("data_staleness_days", 0)
        fresh = "✅ 最新" if stale == 0 else "⚠️ 过期{}天".format(stale)
        deriv_parts.append("<div class='deriv-item'>▸ 数据新鲜度: {}".format(fresh))
    if result.get("decision"):
        bb_score = result.get("bull_bear_score", 0)
        debate_txt = "多头占优" if bb_score > 0.1 else ("空头占优" if bb_score < -0.1 else "多空均衡")
        deriv_parts.append("<div class='deriv-item'>▸ 多空辩论: score={:+.3f} → {}".format(bb_score, debate_txt))
        deriv_parts.append("<div class='deriv-item'>▸ 最终决策: <b style='color:#ffc150'>{}</b></div>".format(_esc(result["decision"])))
        dt = result.get("debate_text", "")
        if dt:
            deriv_parts.append("<div class='deriv-item'>▸ 裁判摘要: <span style='color:#9e9e9e'>{}...</span></div>".format(_esc(dt[:200])))
    deriv_html = "".join("<div class='deriv-block'>{}</div>".format(p) for p in deriv_parts)

    tim_str = ("+" if tim_score > 0 else "") + str(tim_score)

    return (
        "<div class='strat-card'>"
        "<div class='sc-header' style='border-left:4px solid {};background:{}'>"
        "<div class='sc-title-row'>"
        "<span class='sc-emoji'>{}</span>"
        "<span class='sc-name'>{}</span>"
        "<span class='sc-regime' style='color:{};background:{}'>{}</span>"
        "</div>"
        "<div class='sc-meta-row'>"
        "<div class='sc-meta'><div class='sc-meta-label'>Regime</div><div class='sc-meta-val' style='color:{}'>{:+.0f}</div></div>"
        "<div class='sc-meta'><div class='sc-meta-label'>Timing</div><div class='sc-meta-val'>{}</div></div>"
        "<div class='sc-meta'><div class='sc-meta-label'>TimingScore</div><div class='sc-meta-val'>{}</div></div>"
        "<div class='sc-meta'><div class='sc-meta-label'>Risk</div><div class='sc-meta-val' style='color:{}'>{}/10</div></div>"
        "<div class='sc-meta'><div class='sc-meta-label'>仓位</div><div class='sc-meta-val' style='color:{};font-weight:700'>{:.0f}%</div></div>"
        "<div class='sc-meta'><div class='sc-meta-label'>置信度</div><div class='sc-meta-val' style='color:{}'>{:.0%}</div></div>"
        "</div></div>"
        "<div class='sc-body'>"
        "<div class='sc-signals'>{}</div>"
        "{}"
        "{}"
        "{}"
        "<div class='deriv-section'>"
        "<div class='deriv-title'>📐 推导逻辑</div>"
        "{}"
        "</div>"
        "<div class='sc-interpretation'>"
        "<span class='intp-label'>💬 解读</span>"
        "<span class='intp-text'>{}</span>"
        "</div>"
        "</div></div>"
    ).format(
        color, bg,
        emoji, _esc(label), r_color, r_bg, regime,
        r_color, reg_score, _esc(timing), tim_str, risk_c, risk, e_color, exposure, c_color, confidence,
        sig_tags, extra_html, dominant_factors_html, deriv_html, _esc(interp), params_html
    )


def _build_combined_card(comb, rA, rB, rC, rD):
    regime     = comb["market_regime"]
    exposure   = comb["target_exposure"]
    confidence = comb["confidence"]
    divergence = comb["divergence"]
    raw       = comb["raw_weighted_exposure"]
    c_sup     = comb.get("C_suppressed", False)
    interp    = comb.get("interpretation", "")

    r_color, r_bg = _regime_color(regime)
    e_color = _exp_color(exposure)
    c_color = _conf_color(confidence)
    div_txt = "⚠️ 是" if divergence else "✅ 否"
    sup_txt = "⚠️ 是" if c_sup else "✅ 否"
    regime_text = {"BULL_TREND":"📈 总体偏多","RISK_OFF":"🔴 总体防御","NEUTRAL":"⚪ 方向待确认","CURDLE":"⚠️ 宏观紧缩"}.get(regime, regime)
    sup_note = ""
    if c_sup:
        sup_note = "<div class='suppression-note'>⚠️ ML_PROB被压制（与A+B+D冲突），仓位降至最终{:.1f}%（原始{:.1f}%）</div>".format(exposure, raw)

    weights_rows = ""
    for name, col, exp in [
        ("A Momentum","#58a6ff",rA["target_exposure"]),
        ("B Macro","#ab47bc",rB["target_exposure"]),
        ("C ML_Prob","#26c6da",rC["target_exposure"]),
        ("D Agents","#ffa726",rD["target_exposure"]),
    ]:
        weights_rows += (
            "<div class='exp-bar-row'>"
            "<span class='exp-bar-label'>{}</span>"
            "<div class='exp-bar-track'><div class='exp-bar-fill' style='width:{:.0f}%;background:{}'></div></div>"
            "<span class='exp-bar-pct'>{:.0f}%</span>"
            "</div>"
        ).format(name, exp, col, exp)

    return (
        "<div class='combined-card'>"
        "<div class='cc-header'>"
        "<div class='cc-title'>🎯 综合结论</div>"
        "<div class='cc-regime-badge' style='color:{};background:{}'>{}</div>"
        "</div>"
        "<div class='cc-body'>"
        "<div class='cc-kpi-row'>"
        "<div class='cc-kpi'><div class='cc-kpi-label'>最终仓位</div><div class='cc-kpi-val' style='color:{}'>{:.1f}%</div></div>"
        "<div class='cc-kpi'><div class='cc-kpi-label'>置信度</div><div class='cc-kpi-val' style='color:{}'>{:.0%}</div></div>"
        "<div class='cc-kpi'><div class='cc-kpi-label'>原始仓位</div><div class='cc-kpi-val'>{:.1f}%</div></div>"
        "<div class='cc-kpi'><div class='cc-kpi-label'>分歧</div><div class='cc-kpi-val' style='color:{}'>{}</div></div>"
        "<div class='cc-kpi'><div class='cc-kpi-label'>C被压制</div><div class='cc-kpi-val' style='color:{}'>{}</div></div>"
        "</div>"
        "<div class='cc-exp-bars'>"
        "<div class='cc-weights-title'>策略仓位分布</div>"
        "{}"
        "</div>"
        "{}"
        "<div class='cc-interpretation'>"
        "<div class='cc-intp-title'>📋 综合解读</div>"
        "<div class='cc-intp-text'>{}</div>"
        "</div></div></div>"
    ).format(
        r_color, r_bg, regime_text,
        e_color, exposure, c_color, confidence, raw,
        "#ff1744" if divergence else "#00c853", div_txt,
        "#ff1744" if c_sup else "#00c853", sup_txt,
        weights_rows,
        sup_note, _esc(interp)
    )


def _build_indicators_table(v, changes):
    rows_def = [
        ("SPY_CLOSE","SPY收盘价","{:.2f}"),("SPY_EMA20","EMA20","{:.2f}"),
        ("SPY_SMA50","SMA50","{:.2f}"),("SPY_SMA200","SMA200","{:.2f}"),
        ("SPY_20D_RETURN","SPY 20日收益","{:+.2%}"),("SPY_5D_RETURN","SPY 5日收益","{:+.2%}"),
        ("SPY_RSI14","RSI(14)","{:.1f}"),("MACD_HISTOGRAM","MACD直方图","{:.4f}"),
        ("BB_PERCENT","BB%位置","{:.3f}"),("BB_BANDWIDTH","BB带宽","{:.4f}"),
        ("ATR14","ATR(14)","{:.3f}"),("VIX","VIX","{:.2f}"),
        ("VVIX","VVIX","{:.2f}"),("VIX9D","VIX 9D","{:.1f}"),
        ("VIX1M","VIX 1M","{:.1f}"),("NYAD","NYAD","{:.0f}"),
        ("NYAD_SLOPE","NYAD斜率","{:.1f}"),("SPY_NEW_HIGH","SPY创20日新高","{}"),
        ("SP500_ABOVE_50MA","SP500>50MA%","{:.1%}"),("SP500_ABOVE_200MA","SP500>200MA%","{:.1%}"),
        ("NEW_HIGH_LOW_RATIO","新高/新低比","{:.3f}"),
        ("HY_SPREAD","HY利差(%)","{:.2f}%"),("FCI","FCI","{:.4f}"),
        ("GEX","GEX","{}"),("PUT_CALL_RATIO","Put/Call比","{:.2f}"),
        ("CTA_POSITIONING","CTA仓位%ile","{:.1f}"),("REALIZED_VOL","已实现波动率","{:.2f}%"),
    ]

    def fmt_val(val, tmpl):
        if val is None: return "N/A"
        try: return tmpl.format(val)
        except: return str(val)

    def val_band(key, val):
        """返回 (颜色, 状态文字) 当前值在哪个区间"""
        if val is None: return ("#9e9e9e", "—")
        band = INDICATOR_BANDS.get(key)
        if not band or band[2] is None: return ("#9e9e9e", "—")
        thresholds = band[2]
        if not thresholds: return ("#9e9e9e", "—")
        lo_bad, lo_warn, hi_warn, hi_bad, direction = thresholds
        if val < lo_bad:   return ("#ff1744", "很差")
        if val < lo_warn:  return ("#ff6d00", "偏差")
        if val < hi_warn:  return ("#00c853", "正常")
        if val < hi_bad:   return ("#ffc107", "偏高")
        return ("#ff1744", "很高")

    def interp_text(k):
        band = INDICATOR_BANDS.get(k)
        if not band: return ""
        return "<span class='ind-interp'>{}</span>".format(band[1])

    def chg_text(k):
        if k == "SPY_CLOSE":    c5 = changes.get("SPY_5D_CHG");  c20 = changes.get("SPY_20D_CHG")
        elif k == "SPY_RSI14":  c5 = changes.get("RSI_5D_CHG");  c20 = changes.get("RSI_20D_CHG")
        elif k == "VIX":         c5 = None; c20 = None
        elif k == "ATR14":       c5 = changes.get("ATR_5D_CHG");  c20 = None
        else:                    c5 = None; c20 = None
        parts = []
        if c5 is not None: parts.append("<span style='color:{}'>{}{:.1f}%</span>".format(_change_color(c5), _arrow(c5), abs(c5)))
        if c20 is not None: parts.append("<span style='color:{}'>{}{:.1f}%</span>".format(_change_color(c20), _arrow(c20), abs(c20)))
        return " ".join(parts) if parts else "—"

    def band_bar(key, val):
        """生成当前值在区间中的位置条"""
        band = INDICATOR_BANDS.get(key)
        if val is None or not band or band[2] is None: return ""
        thresholds = band[2]
        if not thresholds: return ""
        lo_bad, lo_warn, hi_warn, hi_bad, direction = thresholds
        # 计算val在区间的相对位置（百分比）
        total_range = hi_bad - lo_bad
        if total_range <= 0: return ""
        # 计算val落在哪个段
        if val < lo_warn:
            seg = "lo_bad" if val < lo_bad else "lo_warn"
        elif val < hi_warn:
            seg = "normal"
        else:
            seg = "hi_warn" if val < hi_bad else "hi_bad"
        # 计算百分比位置
        pct = max(2, min(98, (val - lo_bad) / total_range * 100))
        # 颜色
        color = "#ff1744" if seg in ("lo_bad","hi_bad") else ("#ff6d00" if seg in ("lo_warn","hi_warn") else "#00c853")
        return (
            "<div class='band-bar-wrap'>"
            "<div class='band-bar-track'>"
            "<div class='band-bar-zone band-lo-bad' style='width:25%'></div>"
            "<div class='band-bar-zone band-lo-warn' style='width:25%'></div>"
            "<div class='band-bar-zone band-normal' style='width:25%'></div>"
            "<div class='band-bar-zone band-hi-warn' style='width:25%'></div>"
            "<div class='band-bar-marker' style='left:{}%;background:{}'></div>"
            "</div>"
            "<div class='band-bar-labels'>"
            "<span class='bl-bad'>差</span>"
            "<span class='bl-warn'>偏差</span>"
            "<span class='bl-normal'>正常</span>"
            "<span class='bl-hi'>偏高/很低</span>"
            "</div></div>"
        ).format(pct, color)

    rows_html = ""
    for key, label, tmpl in rows_def:
        val = v.get(key)
        color, state_txt = val_band(key, val)
        alert_cls = "alert-text-red" if "很差" in state_txt or "很高" in state_txt else ("alert-text-orange" if "偏差" in state_txt or "偏高" in state_txt else "")
        rows_html += (
            "<tr>"
            "<td>"
            "<div class='ind-name'>{}</div>"
            "{}"
            "<div class='ind-band'>{}</div>"
            "</td>"
            "<td class='num {}' style='color:{}'>{}</td>"
            "<td class='num chg-cell'>{}</td>"
            "</tr>"
        ).format(
            _esc(label),
            interp_text(key),
            band_bar(key, val),
            alert_cls, color,
            fmt_val(val, tmpl),
            chg_text(key)
        )

    return (
        "<div class='section'>"
        "<div class='section-header'>📊 关键指标（含状态区间参考）</div>"
        "<div class='section-body'>"
        "<table class='data-table'>"
        "<thead><tr>"
        "<th>指标 / 说明 / 参考区间</th>"
        "<th class='num'>当前值</th>"
        "<th class='num'>5日/20日变化</th>"
        "</tr></thead>"
        "<tbody>{}</tbody>"
        "</table></div></div>"
    ).format(rows_html)


# ───────────────────────────────────────────────────────────────
# ── 辩论全文区块 ────────────────────────────────────────────────────
def _build_debate_process_section(rD) -> str:
    """读取辩论过程文件，渲染为可展开的完整辩论内容区块。"""
    debate_file = rD.get("debate_file", "")
    if not debate_file or not Path(debate_file).exists():
        return ""
    try:
        content = Path(debate_file).read_text(encoding="utf-8")
    except Exception:
        return ""

    # 文件名展示用
    fname = Path(debate_file).name
    # 前2000字作为直接可见预览（不需要点开）
    preview = _esc(content[:2000])
    preview_html = "<br>".join(preview.split("\n"))
    # 完整内容（8000字，可展开）
    display = _esc(content[2000:8000])
    full_lines_html = "<br>".join(display.split("\n"))

    return (
        "<div style='margin-top:16px'>"
        "<div style='display:flex;align-items:center;gap:8px;margin-bottom:8px'>"
        "<span style='font-size:13px;font-weight:700;color:#ffa726'>🧠 策略D · 完整辩论过程</span>"
        "<span style='font-size:11px;color:#9e9e9e;background:#21262d;padding:2px 8px;border-radius:4px'>" + fname + "</span>"
        "</div>"
        # 直接可见预览区
        "<div style='background:#1a1f27;border-radius:8px;border:1px solid #2d333b;padding:12px 16px;margin-bottom:8px'>"
        "<div style='font-size:11px;color:#ffc107;margin-bottom:8px'>▶ 辩论要点预览（前2000字）</div>"
        "<pre style='font-size:12px;line-height:1.7;color:#c9d1d9;white-space:pre-wrap;word-break:break-all;font-family:inherit;margin:0'>" + preview_html + "</pre>"
        "</div>"
        # 完整展开区
        "<details style='background:#1a1f27;border-radius:8px;border:1px solid #2d333b;overflow:hidden'>"
        "<summary style='padding:10px 14px;cursor:pointer;font-weight:600;color:#ffa726;font-size:13px;background:#21262d'>"
        "▶ 点击展开 / 收起 完整辩论过程（{}字符）".format(len(content)) +
        "</summary>"
        "<div style='padding:12px 16px;font-size:12px;line-height:1.8;color:#c9d1d9;max-height:500px;overflow-y:auto'>"
        "<pre style='white-space:pre-wrap;word-break:break-all;font-family:inherit;margin:0'>" + full_lines_html + "</pre>"
        "</div></details></div>"
    )


# 生成完整 HTML
# ───────────────────────────────────────────────────────────────

def generate_html(result):
    trade_date = result["trade_date"]
    rA = result["strategy_A"]; rB = result["strategy_B"]
    rC = result["strategy_C"]; rD = result["strategy_D"]
    comb = result["combined"]; v = result["variables"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    sr      = compute_support_resistance(trade_date, v)
    changes = compute_indicator_changes(trade_date, v)
    state_label, state_color, state_desc = _judge_market_state(v)
    shift_signals = _judge_shift_signal(v)

    # 近5日状态
    state5d = _compute_5d_state(trade_date, v)
    state5d_html = "".join(
        "<div class='state5d-item'>"
        "<div class='state5d-date'>{}</div>"
        "<div class='state5d-dot' style='background:{}'></div>"
        "<div class='state5d-label' style='color:{}'>{}</div>"
        "<div class='state5d-regime'>{}</div>"
        "</div>".format(d, _state_color(s)[0], _state_color(s)[0], s, regime)
        for d, s, regime in state5d
    )

    # 变盘信号
    shift_html = ""
    for tag, desc in shift_signals:
        is_alert = bool(tag and tag[0] in "🔴🟠🟢")
        blink = " blink-text" if is_alert else ""
        shift_html += (
            "<div class='shift-item'>"
            "<span class='shift-tag{}'>{}</span>"
            "<span class='shift-desc'>{}</span>"
            "</div>"
        ).format(blink, _esc(tag), _esc(desc))

    # SPY 关键价
    spy_close  = v.get("SPY_CLOSE");   spy_close_f  = "{:.2f}".format(spy_close) if spy_close else "N/A"
    spy_ema20  = v.get("SPY_EMA20");   spy_ema20_f  = "{:.2f}".format(spy_ema20) if spy_ema20 else "—"
    spy_sma50  = v.get("SPY_SMA50");  spy_sma50_f  = "{:.2f}".format(spy_sma50) if spy_sma50 else "—"
    spy_sma200 = v.get("SPY_SMA200"); spy_sma200_f = "{:.2f}".format(spy_sma200) if spy_sma200 else "—"
    spy_rsi    = v.get("SPY_RSI14")
    spy_rsi_f  = "{:.1f}".format(spy_rsi) if spy_rsi else "—"
    spy_rsi_color = "#ff1744" if spy_rsi and spy_rsi > 70 else ("#00c853" if spy_rsi and spy_rsi < 30 else "inherit")
    hero_bg = ("rgba(0,200,83,0.12)" if "牛" in state_label or "多" in state_label else
               "rgba(255,23,68,0.12)" if "熊" in state_label else "rgba(255,193,7,0.12)")

    hero_html = (
        "<div class='hero-section'>"
        "<div class='hero-state' style='border-color:{}'>"
        "<div class='hero-state-badge' style='color:{};background:{}'>{}</div>"
        "<div class='hero-desc'>{}</div>"
        "</div>"
        "<div class='state5d-row'>"
        "<div class='state5d-title'>近5日市场状态（红绿黄=熊牛震）</div>"
        "<div class='state5d-track'>{}</div>"
        "</div>"
        "<div class='hero-price-row'>"
        "<div class='hero-price-main'>"
        "<div class='hero-price-label'>SPY 收盘</div>"
        "<div class='hero-price-val'>{}</div>"
        "</div>"
        "<div class='hero-price-sub'>"
        "<div class='hero-p-item'><span class='hero-p-label'>EMA20</span><span class='hero-p-val'>{}</span></div>"
        "<div class='hero-p-item'><span class='hero-p-label'>SMA50</span><span class='hero-p-val'>{}</span></div>"
        "<div class='hero-p-item'><span class='hero-p-label'>SMA200</span><span class='hero-p-val'>{}</span></div>"
        "<div class='hero-p-item'><span class='hero-p-label'>RSI(14)</span><span class='hero-p-val' style='color:{}'>{}</span></div>"
        "</div></div>"
        "<div class='shift-section'>"
        "<div class='shift-title'>🚨 变盘信号 ({:d}项)</div>"
        "{}"
        "</div>"
        "</div>"
    ).format(
        state_color, state_label, hero_bg, state_label, state_desc,
        state5d_html,
        spy_close_f,
        spy_ema20_f, spy_sma50_f, spy_sma200_f,
        spy_rsi_color, spy_rsi_f,
        len(shift_signals), shift_html
    )

    # ── SR 区 ──
    def pct_bar(level):
        if not level or not spy_close: return "15"
        dist = abs(spy_close - level) / spy_close * 100
        return str(max(10, min(95, 100 - dist * 3.5)))

    close_v = sr.get("close", "—")
    sup_items, res_items = "", ""
    for i in range(1, 4):
        lv = sr.get("sup{}".format(i)); nm = sr.get("sup{}_name".format(i)); dp = sr.get("sup{}_dist".format(i)); pb = sr.get("sup{}_prob".format(i))
        rv = sr.get("res{}".format(i)); rnm = sr.get("res{}_name".format(i)); rdp = sr.get("res{}_dist".format(i)); rpb = sr.get("res{}_prob".format(i))
        if lv:
            sup_items += (
                "<div class='sr-item'>"
                "<div class='sr-item-label'>支撑{} · {}</div>"
                "<div class='sr-item-level sup-level'>{:.2f}</div>"
                "<div class='sr-item-dist'>距当前 {}</div>"
                "<div class='sr-prob-bar-wrap'>"
                "<div class='sr-prob-label'>维持概率</div>"
                "<div class='sr-prob-track'><div class='sr-prob-fill sup-prob-fill' style='width:{}%'></div></div>"
                "<div class='sr-prob-val'>{:.1f}%</div>"
                "</div></div>"
            ).format(i, nm, lv, dp, float(pct_bar(lv)), pb if pb else 0)
        if rv:
            res_items += (
                "<div class='sr-item'>"
                "<div class='sr-item-label'>压力{} · {}</div>"
                "<div class='sr-item-level res-level'>{:.2f}</div>"
                "<div class='sr-item-dist'>距当前 {}</div>"
                "<div class='sr-prob-bar-wrap'>"
                "<div class='sr-prob-label'>突破概率</div>"
                "<div class='sr-prob-track'><div class='sr-prob-fill res-prob-fill' style='width:{}%'></div></div>"
                "<div class='sr-prob-val'>{:.1f}%</div>"
                "</div></div>"
            ).format(i, rnm, rv, rdp, float(pct_bar(rv)), rpb if rpb else 0)

    vol_note = "低波动" if sr.get("atr_pct", 99) < 1.5 else ("中波动" if sr.get("atr_pct", 99) < 2.5 else "高波动，可靠性下降")
    sr_html = (
        "<div class='section'>"
        "<div class='section-header'>📍 SPY 支撑位 / 压力位（支撑=现价之下，压力=现价之上）</div>"
        "<div class='section-body'>"
        "<div class='sr-grid'>"
        "<div class='sr-col'><div class='sr-col-title sup-col-title'>▼ 支撑位（现价下方）</div>{}</div>"
        "<div class='sr-col sr-current'>"
        "<div class='sr-current-price'>{}</div>"
        "<div class='sr-current-label'>SPY 当前价</div>"
        "<div class='sr-current-note'>ATR/价格: {}%</div>"
        "<div class='sr-current-note'>波动调整: {:.2f}</div>"
        "</div>"
        "<div class='sr-col'><div class='sr-col-title res-col-title'>▲ 压力位（现价上方）</div>{}</div>"
        "</div>"
        "<div class='sr-note'>方法：标准Pivot · Fibonacci回撤 · Bollinger Bands · VWAP · 20日高低 &nbsp;|&nbsp; 波动率调整: {}</div>"
        "</div></div>"
    ).format(
        sup_items if sup_items else "<div class='sr-item'><div class='sr-item-label'>— 暂无有效支撑</div></div>",
        close_v, sr.get("atr_pct","—"), sr.get("vol_adj", 1.0),
        res_items if res_items else "<div class='sr-item'><div class='sr-item-label'>— 暂无有效压力</div></div>",
        vol_note
    )

    # ── Regime 体系表 ──
    rf = REGIME_FAMILY
    bull_list = " · ".join(k for k, v in rf.items() if v["family"] == "偏多")
    bear_list = " · ".join(k for k, v in rf.items() if v["family"] == "防御")
    neut_list = " · ".join(k for k, v in rf.items() if v["family"] == "中性")
    regime_rows = "".join(
        "<tr><td style='color:{}'>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            _regime_color(r)[0], _esc(r), info["family"], _esc(info["desc"]), _esc(info["action"])
        )
        for r, info in rf.items()
    )
    regime_table_html = (
        "<div class='section'>"
        "<div class='section-header'>📖 Regime 判定类型体系（{:d}种）</div>"
        "<div class='section-body'>"
        "<div class='regime-legend'>"
        "<span class='rl-bull'>偏多系：</span>{} · "
        "<span class='rl-bear'>防御系：</span>{} · "
        "<span class='rl-neutral'>中性系：</span>{}"
        "</div>"
        "<table class='data-table'>"
        "<thead><tr><th>Regime</th><th>分类</th><th>含义</th><th>建议动作</th></tr></thead>"
        "<tbody>{}</tbody>"
        "</table></div></div>"
    ).format(len(rf), bull_list, bear_list, neut_list, regime_rows)

    # ── 分歧 ──
    diag = result.get("diagnostic", {})
    div_html = ""
    if diag.get("divergence"):
        reasons_html = "".join("<div class='div-reason'>• {}</div>".format(_esc(r)) for r in diag.get("reasons", []))
        div_html = (
            "<div class='divergence-banner'>"
            "<div class='div-title'>⚠️ 策略分歧</div>"
            "<div class='div-reasons'>{}</div>"
            "<div class='div-suggestion'>→ {}</div>"
            "</div>"
        ).format(reasons_html, _esc(diag.get("suggestion", "")))

    # ── 策略卡片 ──
    strategy_cards = (
        _build_strategy_card("策略A · 动量趋势",  "📈", rA, "#58a6ff", "rgba(88,166,255,0.08)", v) + "\n" +
        _build_strategy_card("策略B · 宏观择时",  "🌐", rB, "#ab47bc", "rgba(171,71,188,0.08)", v) + "\n" +
        _build_strategy_card("策略C · ML概率",    "🤖", rC, "#26c6da", "rgba(38,198,218,0.08)", v) + "\n" +
        _build_strategy_card("策略D · Agents辩论","🧠", rD, "#ffa726", "rgba(255,167,38,0.08)", v)
    )

    # 策略D辩论全文（可折叠）
    debate_process_html = _build_debate_process_section(rD)

    indicators_html = _build_indicators_table(v, changes)
    combined_html = _build_combined_card(comb, rA, rB, rC, rD)

    # ── 完整 HTML ──
    html = (
        "<!DOCTYPE html>\n"
        "<html lang='zh-CN'>\n"
        "<head>\n"
        "<meta charset='UTF-8'>\n"
        "<meta name='viewport' content='width=device-width,initial-scale=1.0'>\n"
        "<title>P2 择时层 · " + trade_date + "</title>\n"
        "<style>\n"
        "* {box-sizing:border-box;margin:0;padding:0}\n"
        "body {background:#0d1117;color:#e0e0e0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;line-height:1.6}\n"
        "a {color:#58a6ff;text-decoration:none}\n"
        ".report-header {background:linear-gradient(135deg,#1a1a2e,#16213e);border-bottom:2px solid #e94560;padding:24px 32px}\n"
        ".phase-tag {display:inline-block;background:#e94560;color:#fff;font-size:11px;font-weight:700;padding:3px 12px;border-radius:12px;margin-bottom:8px;letter-spacing:1px}\n"
        ".report-title {font-size:24px;font-weight:700;color:#fff;margin-bottom:4px}\n"
        ".report-subtitle {color:#9e9e9e;font-size:13px}\n"
        ".report-meta {margin-top:10px;display:flex;gap:12px;flex-wrap:wrap}\n"
        ".meta-badge {display:inline-flex;align-items:center;gap:4px;background:rgba(255,255,255,0.07);padding:4px 10px;border-radius:6px;font-size:12px}\n"
        ".report-body {padding:24px 32px}\n"
        ".hero-section {background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px 24px;margin-bottom:24px}\n"
        ".hero-state {border-left:5px solid #ffc107;padding:12px 16px;background:rgba(255,193,7,0.06);border-radius:8px;margin-bottom:16px}\n"
        ".hero-state-badge {font-size:18px;font-weight:800;margin-bottom:4px}\n"
        ".hero-desc {font-size:13px;color:#b0b0b0}\n"
        ".hero-price-row {display:flex;gap:20px;align-items:center;margin-bottom:16px}\n"
        ".hero-price-main {flex:1}\n"
        ".hero-price-label {font-size:11px;color:#9e9e9e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:2px}\n"
        ".hero-price-val {font-size:36px;font-weight:800;color:#fff}\n"
        ".hero-price-sub {display:flex;gap:16px}\n"
        ".hero-p-item {text-align:center}\n"
        ".hero-p-label {display:block;font-size:10px;color:#9e9e9e;margin-bottom:2px}\n"
        ".hero-p-val {font-size:14px;font-weight:700}\n"
        ".shift-section {border-top:1px solid #30363d;padding-top:12px}\n"
        ".shift-title {font-size:12px;font-weight:600;color:#9e9e9e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px}\n"
        ".shift-item {display:flex;gap:12px;align-items:flex-start;margin-bottom:8px}\n"
        ".shift-tag {background:#1c2128;border:1px solid #30363d;color:#e0e0e0;padding:2px 8px;border-radius:4px;font-size:12px;white-space:nowrap;flex-shrink:0;min-width:100px;text-align:center}\n"
        ".shift-desc {font-size:13px;color:#b0b0b0;padding-top:2px}\n"
        "@keyframes blink-alert {0%,100%{opacity:1}50%{opacity:0.3}}\n"
        ".blink-text {animation:blink-alert 1.2s ease-in-out infinite}\n"
        ".state5d-row {margin-bottom:16px;padding:12px 16px;background:#1c2128;border-radius:8px}\n"
        ".state5d-title {font-size:10px;color:#9e9e9e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px}\n"
        ".state5d-track {display:flex;gap:0;align-items:flex-start}\n"
        ".state5d-item {flex:1;text-align:center;position:relative}\n"
        ".state5d-dot {width:14px;height:14px;border-radius:50%;margin:6px auto;position:relative;z-index:1;border:2px solid #0d1117}\n"
        ".state5d-date {font-size:10px;color:#9e9e9e;margin-bottom:2px}\n"
        ".state5d-label {font-size:13px;font-weight:800;margin-bottom:2px}\n"
        ".state5d-regime {font-size:10px;color:#9e9e9e}\n"
        ".sr-grid {display:grid;grid-template-columns:1fr auto 1fr;gap:16px;align-items:start}\n"
        ".sr-col {}\n"
        ".sr-col-title {font-size:12px;font-weight:700;margin-bottom:10px;text-align:center}\n"
        ".sup-col-title {color:#00c853}\n"
        ".res-col-title {color:#ff5252}\n"
        ".sr-item {background:#1c2128;border-radius:8px;padding:12px;margin-bottom:8px}\n"
        ".sr-item-label {font-size:11px;color:#9e9e9e;margin-bottom:4px}\n"
        ".sr-item-level {font-size:20px;font-weight:800;margin-bottom:2px}\n"
        ".sup-level {color:#00c853}\n"
        ".res-level {color:#ff5252}\n"
        ".sr-item-dist {font-size:11px;color:#9e9e9e;margin-bottom:8px}\n"
        ".sr-prob-bar-wrap {display:flex;align-items:center;gap:8px}\n"
        ".sr-prob-label {font-size:10px;color:#9e9e9e;white-space:nowrap;width:56px}\n"
        ".sr-prob-track {flex:1;height:6px;background:#21262d;border-radius:3px;overflow:hidden}\n"
        ".sr-prob-fill {height:100%;border-radius:3px;transition:width 0.5s}\n"
        ".sup-prob-fill {background:#00c853}\n"
        ".res-prob-fill {background:#ff5252}\n"
        ".sr-prob-val {font-size:12px;font-weight:700;width:36px;text-align:right}\n"
        ".sr-current {text-align:center;padding:20px 16px;border-left:1px solid #30363d;border-right:1px solid #30363d}\n"
        ".sr-current-price {font-size:28px;font-weight:800;color:#fff}\n"
        ".sr-current-label {font-size:11px;color:#9e9e9e;margin-top:4px}\n"
        ".sr-current-note {font-size:10px;color:#9e9e9e;margin-top:3px}\n"
        ".sr-note {margin-top:12px;font-size:11px;color:#9e9e9e;text-align:center}\n"
        ".regime-legend {font-size:12px;color:#9e9e9e;margin-bottom:12px;line-height:2}\n"
        ".rl-bull {color:#00c853;font-weight:700}\n"
        ".rl-bear {color:#ff5252;font-weight:700}\n"
        ".rl-neutral {color:#ffc107;font-weight:700}\n"
        ".combined-card {background:#161b22;border:1px solid #30363d;border-radius:12px;margin-bottom:24px;overflow:hidden}\n"
        ".cc-header {background:#1c2128;padding:14px 24px;border-bottom:1px solid #30363d;display:flex;align-items:center;gap:16px}\n"
        ".cc-title {font-size:15px;font-weight:700;color:#fff;flex:1}\n"
        ".cc-regime-badge {padding:4px 14px;border-radius:8px;font-size:13px;font-weight:700}\n"
        ".cc-body {padding:20px 24px}\n"
        ".cc-kpi-row {display:flex;gap:0;margin-bottom:16px}\n"
        ".cc-kpi {flex:1;padding:12px;border-right:1px solid #21262d;text-align:center}\n"
        ".cc-kpi:last-child {border-right:none}\n"
        ".cc-kpi-label {font-size:10px;color:#9e9e9e;margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px}\n"
        ".cc-kpi-val {font-size:22px;font-weight:800}\n"
        ".cc-exp-bars {background:#1c2128;border-radius:8px;padding:12px 14px;margin-bottom:12px}\n"
        ".cc-weights-title {font-size:10px;color:#9e9e9e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px}\n"
        ".exp-bar-row {display:flex;align-items:center;gap:10px;margin-bottom:6px}\n"
        ".exp-bar-label {width:80px;font-size:12px;color:#9e9e9e;flex-shrink:0}\n"
        ".exp-bar-track {flex:1;height:6px;background:#21262d;border-radius:3px;overflow:hidden}\n"
        ".exp-bar-fill {height:100%;border-radius:3px;transition:width 0.6s}\n"
        ".exp-bar-pct {width:32px;text-align:right;font-size:12px;font-variant-numeric:tabular-nums}\n"
        ".suppression-note {margin-top:10px;padding:10px 14px;background:rgba(255,193,7,0.10);border-left:3px solid #ffc107;border-radius:6px;font-size:13px;color:#ffc107}\n"
        ".cc-interpretation {margin-top:12px;background:#1c2128;border-radius:8px;padding:12px 16px}\n"
        ".cc-intp-title {font-size:10px;color:#9e9e9e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px}\n"
        ".cc-intp-text {font-size:13px;color:#e0e0e0;line-height:1.7}\n"
        ".divergence-banner {background:rgba(255,193,7,0.10);border:1px solid rgba(255,193,7,0.3);border-radius:10px;padding:16px 20px;margin-bottom:20px}\n"
        ".div-title {font-size:14px;font-weight:700;color:#ffc107;margin-bottom:8px}\n"
        ".div-reason {font-size:13px;color:#e0e0e0;margin-bottom:4px;padding-left:8px}\n"
        ".div-suggestion {margin-top:8px;font-size:13px;color:#ffc107;font-weight:600}\n"
        ".strategy-stack {display:flex;flex-direction:column;gap:12px;margin-bottom:24px}\n"
        ".strat-card {background:#161b22;border:1px solid #21262d;border-radius:10px;overflow:hidden}\n"
        ".params-section {background:#1a1f27;border-radius:8px;padding:14px 16px;margin-bottom:12px}\n.params-title {font-size:13px;font-weight:700;color:#58a6ff;margin-bottom:10px}\n.score-summary {background:#0d1117;border-radius:6px;padding:10px 14px;margin-bottom:10px}\n.score-row {display:flex;align-items:center;gap:12px;margin-bottom:6px}\n.score-label {font-size:14px}\n.score-sub {font-size:12px;color:#9e9e9e}\n.score-detail-row {display:flex;gap:10px;flex-wrap:wrap}\n.score-item {font-size:12px;color:#b0b0b0;background:#161b22;padding:3px 8px;border-radius:4px}\n.param-table-wrap {overflow-x:auto;margin-bottom:8px}\n.param-table {width:100%;border-collapse:collapse;font-size:12px}\n.param-table th {background:#21262d;color:#9e9e9e;text-align:left;padding:6px 10px;font-size:10px;text-transform:uppercase}\n.param-table td {padding:6px 10px;border-bottom:1px solid #1c2128}\n.param-name {color:#e0e0e0;font-weight:600}\n.param-value {font-variant-numeric:tabular-nums}\n.param-thresh {color:#9e9e9e;font-size:11px}\n.param-note-cell {color:#9e9e9e;font-size:11px}\n.param-note {color:#9e9e9e;font-style:italic}\n.thresh-note {color:#ffc107;font-size:11px}\n.param-group-title {background:#21262d!important;color:#58a6ff!important;font-size:11px;font-weight:700;padding:5px 10px!important}\n.regime-table-wrap {margin-top:8px}\n.timing-table-wrap {margin-top:8px}\n.regime-table {width:100%;border-collapse:collapse;font-size:12px;margin-top:6px}\n.regime-table th {background:#21262d;color:#9e9e9e;text-align:left;padding:5px 8px;font-size:10px;text-transform:uppercase}\n.regime-table td {padding:5px 8px;border-bottom:1px solid #1c2128}\n.debate-text-cell {color:#9e9e9e;font-size:12px;line-height:1.5;padding:8px 10px!important;font-style:italic}\n.param-footer-note {font-size:11px;color:#ffc107;background:rgba(255,193,7,0.08);padding:8px 12px;border-radius:6px;border-left:3px solid #ffc107;line-height:1.7}\n.params-sub-title {font-size:11px;color:#9e9e9e;font-weight:600;margin:6px 0 4px}\n.sc-header {padding:14px 18px;border-bottom:1px solid #21262d}\n"
        ".sc-title-row {display:flex;align-items:center;gap:10px;margin-bottom:10px}\n"
        ".sc-emoji {font-size:20px}\n"
        ".sc-name {font-size:14px;font-weight:700;color:#fff;flex:1}\n"
        ".sc-regime {padding:3px 10px;border-radius:6px;font-size:12px;font-weight:700}\n"
        ".sc-meta-row {display:flex;gap:14px;flex-wrap:wrap}\n"
        ".sc-meta-label {font-size:10px;color:#9e9e9e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:2px}\n"
        ".sc-meta-val {font-size:14px;font-weight:700}\n"
        ".sc-body {padding:16px 18px}\n"
        ".sc-signals {display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}\n"
        ".sig-tag {background:#1c2128;border:1px solid #30363d;color:#9e9e9e;padding:2px 8px;border-radius:4px;font-size:11px}\n"
        ".sig-row {display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #21262d;font-size:13px}\n"
        ".sig-row:last-child {border-bottom:none}\n"
        ".sig-label {color:#9e9e9e}\n"
        ".sig-value {font-weight:600}\n"
        ".deriv-section {margin-top:12px;padding-top:12px;border-top:1px solid #21262d}\n"
        ".deriv-title {font-size:11px;color:#9e9e9e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px}\n"
        ".deriv-block {margin-bottom:6px}\n"
        ".deriv-item {font-size:12px;color:#b0b0b0;line-height:1.6}\n"
        ".sc-interpretation {margin-top:12px;padding:10px 12px;background:#1c2128;border-radius:6px;display:flex;gap:8px;align-items:flex-start}\n"
        ".intp-label {font-size:11px;color:#9e9e9e;flex-shrink:0;margin-top:2px}\n"
        ".intp-text {font-size:12px;color:#b0b0b0;line-height:1.6}\n"
        ".section {background:#161b22;border:1px solid #21262d;border-radius:10px;margin-bottom:20px;overflow:hidden}\n"
        ".section-header {background:#1c2128;padding:10px 20px;border-bottom:1px solid #21262d;font-size:13px;font-weight:600;color:#e0e0e0}\n"
        ".section-body {padding:16px 20px}\n"
        ".data-table {width:100%;border-collapse:collapse;font-size:13px}\n"
        ".data-table th {background:#1c2128;color:#9e9e9e;text-align:left;padding:8px 12px;border-bottom:1px solid #30363d;font-size:11px;text-transform:uppercase;letter-spacing:0.5px}\n"
        ".data-table th.num {text-align:right}\n"
        ".data-table td {padding:8px 12px;border-bottom:1px solid #21262d;vertical-align:top}\n"
        ".data-table tr:last-child td {border-bottom:none}\n"
        ".data-table tr:hover td {background:#1c2128}\n"
        ".num {text-align:right;font-variant-numeric:tabular-nums}\n"
        ".ind-name {font-weight:600;color:#e0e0e0;margin-bottom:2px}\n"
        ".band-bar-wrap {margin-top:5px}\n"
        ".band-bar-track {position:relative;height:8px;background:#21262d;border-radius:4px;overflow:hidden;margin-bottom:3px}\n"
        ".band-bar-zone {position:absolute;top:0;height:100%;opacity:0.2;border-radius:2px}\n"
        ".band-lo-bad {left:0%;width:20%;background:#ff1744}\n"
        ".band-lo-warn {left:20%;width:20%;background:#ff6d00}\n"
        ".band-normal {left:40%;width:30%;background:#00c853}\n"
        ".band-hi-warn {left:70%;width:15%;background:#ffc107}\n"
        ".band-hi-bad {left:85%;width:15%;background:#ff1744}\n"
        ".band-bar-marker {position:absolute;top:-3px;width:5px;height:14px;border-radius:2px;transform:translateX(-50%)}\n"
        ".band-bar-labels {display:flex;justify-content:space-between;font-size:9px;color:#9e9e9e}\n"
        ".ind-band {margin-top:4px}\n"

        ".ind-interp {font-size:11px;color:#9e9e9e;line-height:1.4;display:block}\n"
        ".chg-cell {font-size:12px;white-space:nowrap}\n"
        ".alert-red td {background:rgba(255,23,68,0.08)!important}\n"
        ".alert-orange td {background:rgba(255,109,0,0.08)!important}\n"
        ".alert-yellow td {background:rgba(255,193,7,0.06)!important}\n"
        ".alert-green td {background:rgba(0,200,83,0.06)!important}\n"
        ".alert-text-red {color:#ff1744!important;font-weight:700}\n"
        ".alert-text-orange {color:#ff6d00!important}\n"
        ".report-footer {padding:16px 32px;border-top:1px solid #30363d;color:#9e9e9e;font-size:11px;display:flex;justify-content:space-between;align-items:center}\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        "<div class='report-header'>"
        "<div class='phase-tag'>P2 · 择时层</div>"
        "<div class='report-title'>美股投资择时分析 · " + trade_date + "</div>"
        "<div class='report-subtitle'>Momentum · Macro · ML概率 · Agents辩论 四策略并行</div>"
        "<div class='report-meta'>"
        "<span class='meta-badge'>📅 " + trade_date + "</span>"
        "<span class='meta-badge'>🕐 " + now + "</span>"
        "<span class='meta-badge'>🤖 P2 择时层</span>"
        "</div></div>\n"
        "<div class='report-body'>\n" +
        hero_html + "\n" +
        sr_html + "\n" +
        combined_html + "\n" +
        div_html + "\n" +
        "<div class='strategy-stack'>\n" + strategy_cards + "\n</div>\n" +
        debate_process_html + "\n" +
        indicators_html + "\n" +
        regime_table_html + "\n"
        "</div>\n"
        "<div class='report-footer'>"
        "<span>美股投资洞察分析 · P2 择时层 · " + trade_date + "</span>"
        "<span>Generated " + now + "</span>"
        "</div>\n"
        "</body>\n"
        "</html>\n"
    )

    out_dir = Path(__file__).parent / "layout"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / ("p2_" + trade_date + ".html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print("HTML generated: " + str(out_path))
    return out_path


if __name__ == "__main__":
    from p2_master_dispatcher import run
    import sys
    td = sys.argv[1] if len(sys.argv) > 1 else "2026-05-15"
    result = run(td, output_html=False, verbose=False)
    path = generate_html(result)
    print("HTML: " + str(path))