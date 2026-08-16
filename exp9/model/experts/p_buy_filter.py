#!/usr/bin/env python3
"""
p_buy_filter.py — Brooks 五层买入过滤系统
==========================================

基于方方土价格行为学 P02-P16 字幕原文设计
五层过滤：市场环境 → 趋势方向 → 入场形态 → K线信号 → 风险收益

用法：
    python3 p_buy_filter.py AAPL          # 单股分析
    python3 p_buy_filter.py --all         # 全股票池扫描（输出所有评级）
    python3 p_buy_filter.py --top N       # 输出前N个A级候选

依赖：
    数据：中间过程/klines/{TICKER}_1d.json
    指标：fintech/p1/features/（可独立运行，无外部依赖）

 Brooks 字幕原文索引：
    P07：信号K线定义 / Buy Stop入场 / 趋势K线 vs 震荡K线
    P09：82%规则 / 背景>>信号 / Bread & Butter
    P05：H1/L1数K线 / 回调买入 / 50%回撤
    P10：好Wedge vs 坏Wedge / 三推反转
    P11：顺大逆小 / 嵌套Wedge / Wedge失败=123
    P12：Parabolic Wedge / Bad Follow-Through
    P13：Measured Move / 止盈目标
    P02：牛市四阶段 / 50%回撤原则 / 止损位置
    P14/P16：Actual Risk / 盈亏比 / 1%仓位
"""

import json, sys, math
from pathlib import Path
from datetime import datetime, date
from typing import Optional

# ── 路径配置 ──────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent.parent.parent
KLINES_DIR = BASE / "TradingAgents" / "中间过程" / "klines"


# ═══════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════

def _ema(values: list, span: int) -> list:
    if not values:
        return []
    alpha = 2.0 / (span + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * alpha + ema[-1] * (1 - alpha))
    return ema


def _atr(bars: list, period: int = 14) -> float:
    """计算 ATR（Average True Range），兼容 volume/vol 字段名"""
    if len(bars) < period + 1:
        return 0.0
    trs = []
    for i in range(1, min(len(bars), period + 20)):
        h = float(bars[i]["high"])
        l = float(bars[i]["low"])
        pc = float(bars[i-1]["close"])
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    if len(trs) < period:
        return 0.0
    return sum(trs[-period:]) / period


def load_klines(ticker: str, lookback: int = 300) -> Optional[list]:
    """加载K线数据，返回有序bars列表（升序）"""
    fp = KLINES_DIR / f"{ticker}_1d.json"
    if not fp.exists():
        return None
    with open(fp) as f:
        d = json.load(f)
    bars = d.get("data", d)
    if not bars:
        return None
    # 确保按日期升序
    bars = sorted(bars, key=lambda x: x["date"])
    return bars[-lookback:]


def load_1h_klines(ticker: str, lookback: int = 80) -> Optional[list]:
    """
    加载1小时K线数据（用于多时间框架确认）
    - 只取最近 lookback 根有效 bars（过滤 volume=0）
    - 日期降序：最近的在最后
    """
    fp = KLINES_DIR / f"{ticker}_1h.json"
    if not fp.exists():
        return None
    with open(fp) as f:
        d = json.load(f)
    bars = d.get("data", d)
    if not bars:
        return None
    # 过滤零量 + 按 datetime 升序
    valid = [b for b in bars if b.get("volume", 0) > 0]
    valid = sorted(valid, key=lambda x: x["datetime"])
    return valid[-lookback:]


def rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d for d in deltas[-period:] if d > 0]
    losses = [-d for d in deltas[-period:] if d < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def candle_quality(open_, close, high, low) -> dict:
    """
    P07 原文：趋势K线 vs 震荡K线
    趋势K线：实体占比 ≥ 60%，影线短
    震荡K线：实体占比小，影线长
    """
    day_range = high - low
    if day_range == 0:
        return {"body_ratio": 0, "upper_wick_ratio": 0, "lower_wick_ratio": 0,
                "is_trend_bar": False, "is_bullish": False}
    body = abs(close - open_)
    body_ratio = body / day_range  # 实体占比
    upper_wick = max(0, high - max(close, open_))
    lower_wick = max(0, min(close, open_) - low)
    upper_wick_ratio = upper_wick / day_range
    lower_wick_ratio = lower_wick / day_range
    is_trend_bar = body_ratio >= 0.60  # P07: 实体占比≥60%
    is_bullish = close > open_
    return {
        "body_ratio": round(body_ratio, 3),
        "upper_wick_ratio": round(upper_wick_ratio, 3),
        "lower_wick_ratio": round(lower_wick_ratio, 3),
        "is_trend_bar": is_trend_bar,
        "is_bullish": is_bullish,
    }


def detect_h1_signal(bars: list) -> dict:
    """
    P05 原文：H1 = 回调后第一根突破前一根K线高点的阳线
    L1 = 反弹后第一根跌破前一根K线低点的阴线

    关键改进：
    - H1_invalidate_PCT：如果当前收盘 < H1信号K低点，说明趋势未如预期发展
      → 之前用H1判断趋势方向的逻辑不再有效
    - 当前可能是在走更深层的回调（或新的入场形态）
    """
    if len(bars) < 5:
        return {"has_h1": False, "has_l1": False, "h1_bar": None, "l1_bar": None,
                "h1_invalidated": False, "invalidation_date": None}
    recent = bars[-5:]
    results = []
    for i in range(1, len(recent)):
        prev = recent[i-1]
        curr = recent[i]
        p_high = float(prev["high"])
        p_low = float(prev["low"])
        c_close = float(curr["close"])
        c_open = float(curr["open"])
        # H1: 阳线 + 突破前高
        if c_close > c_open and c_close > p_high:
            results.append(("H1", curr))
        # L1: 阴线 + 跌破前低
        if c_close < c_open and c_close < p_low:
            results.append(("L1", curr))
    h1 = [r for r in results if r[0] == "H1"]
    l1 = [r for r in results if r[0] == "L1"]

    # 检查H1是否已被后续K线收盘跌破（H1失效）
    h1_invalidated = False
    invalidation_date = None
    h1_stale = False  # H1是否过期（距今>20根K线）
    if h1:
        h1_low = float(h1[-1][1]["low"])
        latest_close = float(bars[-1]["close"])
        h1_date_str = h1[-1][1]["date"]
        # 检查H1是否过期：H1之后是否有足够多的K线（>20根说明H1太旧）
        h1_idx = None
        for idx, bar in enumerate(bars):
            if bar["date"] == h1_date_str:
                h1_idx = idx
                break
        if h1_idx is not None:
            bars_since_h1 = len(bars) - 1 - h1_idx
            if bars_since_h1 > 20:
                h1_stale = True  # 超过20根K线，H1已过期
        # 查找哪根K线收盘跌破了H1低点
        for bar in bars[-1::-1]:
            c = float(bar["close"])
            if c < h1_low:
                h1_invalidated = True
                invalidation_date = bar["date"]
                break
            if bar["date"] == h1_date_str:
                break

    return {
        "has_h1": len(h1) > 0,
        "has_l1": len(l1) > 0,
        "h1_bar": h1[-1][1] if h1 else None,
        "l1_bar": l1[-1][1] if l1 else None,
        "h1_invalidated": h1_invalidated,
        "invalidation_date": invalidation_date,
        "h1_stale": h1_stale,   # 新增：H1过期标记
    }


def detect_h1_signal_1h(bars_1h: list) -> dict:
    """
    P05 1h版本：扫描1小时K线的H1/L1信号
    H1 = 回调后第一根突破前一根K线高点的阳线
    L1 = 反弹后第一根跌破前一根K线低点的阴线

    同时检测流动性猎杀事件：
    - bearish_liquidation：大量阴线砸盘（机构派发嫌疑）
    - buy_stop_triggered：日内价格是否曾上穿日线信号K高点
    """
    if len(bars_1h) < 5:
        return {"has_h1": False, "has_l1": False, "h1_bar": None, "l1_bar": None,
                "bearish_liquidation": None, "buy_stop_triggered": False,
                "buy_stop_price": None, "buy_stop_datetime": None}

    # H1/L1 扫描
    recent = bars_1h[-5:]
    h1, l1 = [], []
    for i in range(1, len(recent)):
        pc = float(recent[i-1]["close"])
        ph = float(recent[i-1]["high"])
        pl = float(recent[i-1]["low"])
        cc = float(recent[i]["close"])
        co = float(recent[i]["open"])
        if cc > co and cc > ph:
            h1.append(recent[i])
        if cc < co and cc < pl:
            l1.append(recent[i])

    # 流动性猎杀检测：近10根中找大量阴线（跌幅大 + 量显著放大）
    avg_vol = sum(b.get("volume", 0) for b in bars_1h[-20:]) / 20
    liquidation = None
    for b in bars_1h[-10:]:
        o, h, l, c = float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"])
        v = b.get("volume", 0)
        if v > avg_vol * 1.5 and c < o:  # 高量阴线
            drop_pct = (o - c) / o * 100
            if drop_pct > 1.5:  # 跌幅超1.5%
                liquidation = {
                    "datetime": b["datetime"],
                    "open": o, "high": h, "low": l, "close": c,
                    "volume": v, "drop_pct": round(drop_pct, 1),
                    "vol_ratio": round(v / avg_vol, 1),
                    "is_bearish": True,
                }
                break  # 只取最近的一次

    # Buy Stop 触发检测（由调用方传入日线信号K高点）
    # 此函数不持有日线数据，由外层传入 buy_stop_price
    return {
        "has_h1": len(h1) > 0,
        "has_l1": len(l1) > 0,
        "h1_bar": h1[-1] if h1 else None,
        "l1_bar": l1[-1] if l1 else None,
        "bearish_liquidation": liquidation,
    }


def detect_falling_wedge(bars: list, lookback: int = 60) -> dict:
    """
    P10 原文：下降楔形 = 三次向下试探后突破上轨趋势线
    P11 原文：Falling Wedge 突破上轨 = 入场做多
    简化版：检测近60天内是否有三推向下衰竭形态
    """
    if len(bars) < 20:
        return {"detected": False, "type": None, "message": ""}
    recent = bars[-lookback:]
    # 找最近的低点序列（局部最低点）
    lows = []
    for i in range(1, len(recent)-1):
        if (float(recent[i]["low"]) < float(recent[i-1]["low"]) and
            float(recent[i]["low"]) < float(recent[i+1]["low"])):
            lows.append((i, float(recent[i]["low"])))
    if len(lows) < 3:
        return {"detected": False, "type": None, "message": "不足3个低点"}
    # 检查三次下探是否幅度递减（衰竭）
    diffs = [lows[i+1][1] - lows[i][1] for i in range(len(lows)-1)]
    if len(diffs) >= 2:
        is_shrinking = all(abs(diffs[i]) < abs(diffs[i-1]) for i in range(1, len(diffs)))
    else:
        is_shrinking = True
    # 检查最新价格是否突破最近3个低点上方的趋势线（简化）
    if len(lows) >= 3:
        last_three_lows = [l[1] for l in lows[-3:]]
        latest_close = float(recent[-1]["close"])
        trendline_level = max(last_three_lows)
        if latest_close > trendline_level and is_shrinking:
            return {
                "detected": True,
                "type": "FALLING_WEDGE",
                "message": f"下降楔形检测到：三推向下衰竭，最新价{latest_close:.2f}突破趋势线{trendline_level:.2f}",
            }
    return {"detected": False, "type": None, "message": "无楔形形态"}


def detect_parabolic_wedge(bars: list, lookback: int = 20) -> dict:
    """
    P12 原文：Parabolic Wedge = 价格加速上涨 + 成交量递增 + 最大量出现
    Bad Follow-Through = 大量后无跟随 = 反转信号
    """
    if len(bars) < 10:
        return {"detected": False, "type": None}
    recent = bars[-lookback:]
    # 价格加速度：最近涨幅是否递增
    returns = []
    for i in range(1, len(recent)):
        r = (float(recent[i]["close"]) - float(recent[i-1]["close"])) / float(recent[i-1]["close"])
        returns.append(r)
    if len(returns) < 3:
        return {"detected": False, "type": None}
    # 检查最近3根是否加速上涨
    accelerating = returns[-1] > returns[-2] > returns[-3] if len(returns) >= 3 else False
    # 检查成交量是否递增
    vols = [float(b.get("volume", 0)) for b in recent]
    vol_increasing = len(vols) >= 3 and vols[-1] > vols[-2] > vols[-3]
    # 最大量K线（近5天内）
    if vols:
        max_vol_idx = vols.index(max(vols))
        max_vol_bar = recent[max_vol_idx]
        latest_close = float(recent[-1]["close"])
        # 最大量后价格无跟随（下跌或震荡）
        after_max = vols[max_vol_idx+1:]
        after_closes = [float(recent[max_vol_idx+1+i]["close"]) for i in range(len(after_max))] if max_vol_idx+1 < len(recent) else []
        bad_follow = len(after_closes) > 0 and all(c <= float(max_vol_bar["close"]) for c in after_closes)
        if accelerating and vol_increasing and bad_follow:
            return {"detected": True, "type": "PARABOLIC_WEDGE_BEARISH",
                    "message": f"Parabolic Wedge检测到：价格加速+量增+最大量后无跟随({max_vol_bar['date']})"}
    return {"detected": False, "type": None}


# ══════════════════════════════════════════════════════════════════════════════
# P1 新增：趋势线支撑检测（P02/P05 核心支撑位）
# ══════════════════════════════════════════════════════════════════════════════
def detect_trendline_support(bars: list, lookback: int = 60) -> dict:
    """
    P02/P05 原文：价格回踩上升趋势线 = 最佳买入机会之一
    P11 原文：顺大逆小，上升趋势中的楔形是 Bull Flag（持续形态）

    检测逻辑：
    1. 用最近 lookback Bars 的局部低点，拟合一条上升趋势线
    2. 检查最新价格是否在趋势线支撑±3%范围内
    3. 若价格回踩趋势线且企稳 → 买入信号
    4. 若价格跌破趋势线 → 趋势可能改变

    返回字段：
      detected     : bool  是否回踩趋势线
      trendline_price : float  趋势线当前价位
      distance_pct  : float  最新价距趋势线%
      broken        : bool  趋势线是否已破
      slope         : float  趋势线斜率（% per bar）
      touch_count   : int   趋势线触及次数
      quote         : str   Brooks 原文
    """
    if len(bars) < 15:
        return {"detected": False, "trendline_price": None,
                "distance_pct": None, "broken": False,
                "slope": None, "touch_count": 0,
                "quote": ""}

    recent = bars[-lookback:]
    closes = [float(b["close"]) for b in recent]
    lows   = [float(b["low"])  for b in recent]
    dates  = [b["date"]        for b in recent]
    latest_close = closes[-1]

    # ── Step 1: 找局部低点（至少被左右各1根更低 lows 确认）────────
    swing_lows = []
    for i in range(1, len(recent) - 1):
        l = float(recent[i]["low"])
        if l < float(recent[i-1]["low"]) and l < float(recent[i+1]["low"]):
            swing_lows.append((i, l, dates[i]))

    if len(swing_lows) < 3:
        return {"detected": False, "trendline_price": None,
                "distance_pct": None, "broken": False,
                "slope": None, "touch_count": 0,
                "quote": ""}

    # 取最近3-5个低点拟合趋势线
    pts = swing_lows[-5:]
    n = len(pts)
    # 线性回归 y = a*x + b（x = 索引）
    sum_x  = sum(p[0] for p in pts)
    sum_y  = sum(p[1] for p in pts)
    sum_xy = sum(p[0] * p[1] for p in pts)
    sum_x2 = sum(p[0]**2 for p in pts)
    denom  = n * sum_x2 - sum_x**2
    if abs(denom) < 1e-10:
        return {"detected": False, "trendline_price": None,
                "distance_pct": None, "broken": False,
                "slope": None, "touch_count": 0,
                "quote": ""}

    slope     = (n * sum_xy - sum_x * sum_y) / denom          # 每索引单位价格变化
    intercept = (sum_y - slope * sum_x) / n                    # 截距

    # 趋势线斜率（每根K线上涨%，衡量趋势强弱）
    slope_pct = slope / (sum_y / n) * 100 if (sum_y / n) > 0 else 0

    # 趋势线在最新位置的值
    last_idx  = pts[-1][0]
    trendline_price = slope * last_idx + intercept

    # ── Step 2: 计算距离 ────────────────────────────────────────
    distance_pct = (latest_close - trendline_price) / trendline_price * 100

    # ── Step 3: 检查支撑有效性 ─────────────────────────────────
    # 趋势线被测试次数（价格接近趋势线±2%算一次触及）
    touch_count = 0
    for i, low, _ in swing_lows[:-1]:  # 不含最新的（正在测试中）
        tl_val = slope * i + intercept
        if abs(low - tl_val) / tl_val < 0.02:
            touch_count += 1

    # 趋势线是否已破（当前收盘 < 趋势线价格，且跌幅 > 1%）
    broken = latest_close < trendline_price * 0.99

    # 回踩信号：价格在趋势线上方3%以内，且未破
    near_trendline = abs(distance_pct) < 3.0

    result = {
        "detected": near_trendline and not broken,
        "trendline_price": round(trendline_price, 2),
        "distance_pct": round(distance_pct, 2),
        "broken": broken,
        "slope": round(slope, 4),
        "slope_pct_per_bar": round(slope_pct / 100, 6),
        "touch_count": touch_count,
        "quote": (
            "P02\u300c\u4e0a\u5347\u8d8b\u52bf\u7ebf\u4e0a\u7684\u56de\u8e0b\u662f\u6700\u4f73\u4e70\u5165\u673a\u4f1a\u4e4b\u4e00\u300eBrooks\u300f\uff1b"
            "P05\u300c\u7d27\u8d34EMA20\u7684\u56de\u8c03\u662f\u6700\u5f3a\u4e00\u7b49\u5f85\u300b"
        ),
    }
    return result


# ══════════════════════════════════════════════════════════════════════════════
# P2 新增：Bull Flag / Bear Flag 趋势中继楔形 vs 反转楔形区分
# ══════════════════════════════════════════════════════════════════════════════
def detect_bull_bear_flag(bars: list, lookback: int = 60) -> dict:
    """
    P11 原文：顺大逆小
    - 大趋势向上，小楔形向下 = Bull Flag（持续形态，不反转，顺大趋势买）
    - 大趋势向下，小楔形向上 = Bear Flag（持续形态，不反转，顺大趋势卖）
    - 无明显大趋势时的楔形 = 反转形态（Falling/Rising Wedge）

    判断步骤：
    1. 判断大趋势方向（用 EMA20 斜率 or 20日高点/低点方向）
    2. 找楔形结构（三推 + 趋势线收敛）
    3. 结合大趋势，判断是 Flag（顺）还是 Wedge（逆）

    返回：
      type        : BULL_FLAG | BEAR_FLAG | FALLING_WEDGE | RISING_WEDGE | NONE
      context     : 趋势中（顺）还是反转（逆）
      confidence  : high/medium/low
      message     : Brooks 描述
      quote       : 原文引用
    """
    if len(bars) < 20:
        return {"type": "NONE", "context": None,
                "confidence": "low", "message": "数据不足", "quote": ""}

    recent = bars[-lookback:]
    closes = [float(b["close"]) for b in recent]
    highs  = [float(b["high"])  for b in recent]
    lows   = [float(b["low"])   for b in recent]

    # ── Step 1: 大趋势方向（20日 EMA 斜率）────────────────────
    ema20 = _ema(closes, 20)
    if len(ema20) < 10:
        return {"type": "NONE", "context": None,
                "confidence": "low", "message": "数据不足", "quote": ""}

    ema_slope = (ema20[-1] - ema20[-10]) / ema20[-10] * 100  # 10天EMA变化%

    if ema_slope > 1.0:
        big_trend = "UP"
    elif ema_slope < -1.0:
        big_trend = "DOWN"
    else:
        big_trend = "NEUTRAL"

    # ── Step 2: 找三推结构 ────────────────────────────────────
    def _find_swing_points(data, is_lows=True):
        pts = []
        for i in range(1, len(data) - 1):
            curr = data[i]
            ok = (curr < data[i-1] and curr < data[i+1]) if is_lows else (curr > data[i-1] and curr > data[i+1])
            if ok:
                pts.append((i, curr))
        return pts

    lows_pts  = _find_swing_points(lows,  is_lows=True)
    highs_pts = _find_swing_points(highs, is_lows=False)

    # ── Step 3: 检测收敛楔形 ───────────────────────────────
    # 三推幅度递减 = 楔形特征
    def _check_shrinking_pushes(pts):
        if len(pts) < 3:
            return None, None
        # 取最近3个点
        last3 = pts[-3:]
        ranges = [abs(last3[i+1][1] - last3[i][1]) for i in range(len(last3)-1)]
        if len(ranges) == 2:
            shrinking = ranges[1] < ranges[0]  # 第二推比第一推小
            return shrinking, last3
        return None, None

    # 向下三推（潜在 Bull Flag 或 Falling Wedge）
    shrink_d, pts_d = _check_shrinking_pushes(lows_pts)
    # 向上三推（潜在 Bear Flag 或 Rising Wedge）
    shrink_u, pts_u = _check_shrinking_pushes(highs_pts)

    result = {
        "type": "NONE",
        "context": None,
        "confidence": "low",
        "big_trend": big_trend,
        "ema_slope_pct": round(ema_slope, 2),
        "message": "无楔形/旗形结构",
        "quote": "P11\u300c\u987a\u5927\u9006\u5c0f\uff0c\u695a\u5f62\u5728\u8d8b\u52bf\u4e2d=\u7ee7\u7eed\u5f62\u6001\uff0c\u4e0d\u9817\u53cd\u8f6c\u300eBrooks\u300f",
    }

    # ── Bull Flag：大趋势向上 + 向下三推衰竭 ───────────────
    if big_trend == "UP" and shrink_d and pts_d:
        result["type"]      = "BULL_FLAG"
        result["context"]   = "TREND_CONTINUATION"
        result["confidence"] = "high" if shrink_d else "medium"
        result["message"]   = (
            f"Bull Flag 检测到：EMA10日+{ema_slope:.1f}%强势上涨中，"
            f"三推向下幅度递减（衰竭信号），"
            f"趋势延续概率大，回调结束可买入"
        )
        result["quote"] = (
            "P11\u300c\u5c0f\u695a\u5f62\u5411\u4e0b\u662fBull Flag\uff0c\u987a\u5927\u8d8b\u52bf\u65e5\u7ebf\u4e70\u5165\uff0c\u4e0d\u9006\u5927\u65b9\u5411\u300eBrooks\u300f"
        )
        return result

    # ── Bear Flag：大趋势向下 + 向上三推衰竭 ───────────────
    if big_trend == "DOWN" and shrink_u and pts_u:
        result["type"]      = "BEAR_FLAG"
        result["context"]   = "TREND_CONTINUATION"
        result["confidence"] = "high" if shrink_u else "medium"
        result["message"]   = (
            f"Bear Flag 检测到： EMA10日{ema_slope:.1f}%下跌中，"
            f"三推向上衰竭，"
            f"趋势延续概率大，反弹后可做空"
        )
        result["quote"] = (
            "P11\u300c\u5c0f\u695a\u5f62\u5411\u4e0a\u662fBear Flag\uff0c\u987a\u5927\u8d8b\u52bf\u65e5\u7ebf\u5356\u51fa\uff0c\u4e0d\u9006\u5927\u65b9\u5411\u300eBrooks\u300f"
        )
        return result

    # ── Falling Wedge（下降楔形 = 潜在反转向上）──────────────
    if big_trend == "NEUTRAL" and shrink_d and pts_d:
        result["type"]      = "FALLING_WEDGE"
        result["context"]   = "REVERSAL"
        result["confidence"] = "medium"
        result["message"]   = (
            "Falling Wedge 检测到：三推向下幅度递减，"
            "无明显大趋势，楔形为反转形态，突破上轨可买入"
        )
        result["quote"] = (
            "P10\u300cFalling Wedge\uff1a\u4e09\u6b21\u5f80\u4e0b\u63a2\u6b20\u6b21\u6570\u9002\uff0c\u7b79\u5f62\u4e0a\u80c1\u7a81\u7834\u5165\u573a\u505a\u591a\u300eBrooks\u300f"
        )
        return result

    # ── Rising Wedge（上升楔形 = 潜在反转向下）──────────────
    if big_trend == "NEUTRAL" and shrink_u and pts_u:
        result["type"]      = "RISING_WEDGE"
        result["context"]   = "REVERSAL"
        result["confidence"] = "medium"
        result["message"]   = (
            "Rising Wedge 检测到：三推向上幅度递减，"
            "无明显大趋势，楔形为反转形态，突破下轨可做空"
        )
        result["quote"] = (
            "P10\u300cRising Wedge\uff1a\u4e09\u6b21\u5f80\u4e0a\u63a2\u6b20\u6b21\u6570\u9002\uff0c\u7b79\u5f62\u4e0b\u80c1\u7a81\u7834\u505a\u7a7a\u300eBrooks\u300f"
        )
        return result

    # ── 大趋势中的楔形 = Flag（即使趋势中性，方向仍顺最后一次波段的趋势）──
    if big_trend == "NEUTRAL":
        result["message"] = "趋势中性，无明确方向"

    return result


# ══════════════════════════════════════════════════════════════════════════════
# P3 新增：Failed Wedge = 1-2-3 结构（P11 核心）
# ══════════════════════════════════════════════════════════════════════════════
def detect_failed_wedge_123(bars: list, lookback: int = 60) -> dict:
    """
    P11 原文：双底/双顶突破失败 = Wedge 123结构
    - L1/L2/L3 全部失败 → 市场将强势反转
    - 不要在双底突破位置追卖——那里是陷阱

    123 结构：
    1 = 第一个低点/高点
    2 = 突破1后的反弹/回调
    3 = 再次测试1的失败 = 陷阱
    → 之后市场强势反转

    返回：
      detected     : bool
      type         : BULL_123 | BEAR_123 | NONE
      message      : Brooks 描述
      setup_price  : 陷阱位（123结构的高/低点）
      reversal_target : 反转目标位
      quote        : 原文引用
    """
    if len(bars) < 30:
        return {"detected": False, "type": None,
                "message": "", "setup_price": None, "reversal_target": None, "quote": ""}

    recent = bars[-lookback:]
    highs  = [float(b["high"])  for b in recent]
    lows   = [float(b["low"])   for b in recent]
    closes = [float(b["close"]) for b in recent]
    dates  = [b["date"]        for b in recent]

    # ── 找局部波段高低点 ────────────────────────────────────
    swing_highs, swing_lows = [], []
    for i in range(1, len(recent) - 1):
        if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
            swing_highs.append((i, highs[i], dates[i]))
        if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
            swing_lows.append((i, lows[i], dates[i]))

    if len(swing_lows) < 3 or len(swing_highs) < 3:
        return {"detected": False, "type": None,
                "message": "波段点不足", "setup_price": None,
                "reversal_target": None, "quote": ""}

    # 取最近4个 swing points
    sl = swing_lows[-4:]
    sh = swing_highs[-4:]

    result_base = {
        "quote": (
            "P11\u300c\u4e0d\u8981\u5728\u53cc\u5e95\u7a81\u7834\u4f4d\u7f6e\u8ffd\u5356\u2014\u2014\u90a3\u91cc\u662f\u9677\u9631\u300eBrooks\u300f\uff1b"
            "P11\u300cL1/L2/L3\u5168\u90e8\u5931\u6548\u2192\u5e02\u573a\u5c06\u5f3a\u52bf\u53cd\u8f6c\u300eBrooks\u300f"
        ),
    }

    # ── Bull 123：低点1 → 反弹2 → 再次测试低点3失败 ──────────
    # 条件：最近3个低点一波比一波高，但第3个低点没创新低（失败）
    if len(sl) >= 3:
        l1_idx, l1_p, l1_d = sl[-3]
        l2_idx, l2_p, l2_d = sl[-2]  # 反弹高点（相对）
        l3_idx, l3_p, l3_d = sl[-1]  # 再次测试

        # 检查是否是123结构：l1和l3接近（测试同一支撑），l2是反弹
        same_level = abs(l1_p - l3_p) / l1_p < 0.02   # 两低点在同一水平±2%
        rebound_amp = l2_p - l1_p
        retest_ok = l3_p >= l1_p * 0.98  # l3没破l1（新低失败）

        if same_level and retest_ok and rebound_amp > 0:
            latest_close = closes[-1]
            latest_high  = highs[-1]
            # 向上突破 l2 高点 = 确认123失败 = 反转向上
            confirmed = latest_close > l2_p
            reversal_target = l2_p + (l2_p - l1_p)  # 等距投射

            return {
                "detected": True,
                "type": "BULL_123",
                "message": (
                    f"Bull 123 结构检测到："
                    f"低点1({l1_d})={l1_p:.2f} → 反弹({l2_d})={l2_p:.2f} → "
                    f"再次测试({l3_d})={l3_p:.2f}（未破=陷阱）→ "
                    + ("已确认→平台将强势反转" if confirmed
                       else f"等待确认（需突破{l2_p:.2f}）")
                ),
                "setup_price": round(l1_p, 2),
                "reversal_target": round(reversal_target, 2),
                "confirmed": confirmed,
                **result_base,
            }

    # ── Bear 123：高点了 → 回调2 → 再次测试高点3失败 ──────────
    if len(sh) >= 3:
        h1_idx, h1_p, h1_d = sh[-3]
        h2_idx, h2_p, h2_d = sh[-2]  # 回调低点
        h3_idx, h3_p, h3_d = sh[-1]  # 再次测试

        same_level = abs(h1_p - h3_p) / h1_p < 0.02   # 两高点在同一水平±2%
        pullback_amp = h1_p - h2_p
        retest_ok = h3_p <= h1_p * 1.02  # h3没破h1（新高失败）

        if same_level and retest_ok and pullback_amp > 0:
            latest_close = closes[-1]
            # 向下突破 h2 低点 = 确认123失败 = 反转向下
            confirmed_b = latest_close < h2_p
            reversal_target = h2_p - (h1_p - h2_p)  # 等距投射

            return {
                "detected": True,
                "type": "BEAR_123",
                "message": (
                    f"Bear 123 结构检测到："
                    f"高点1({h1_d})={h1_p:.2f} → 回调({h2_d})={h2_p:.2f} → "
                    f"再次测试({h3_d})={h3_p:.2f}（未破=陷阱）→ "
                    + ("已确认→平台将强势反转" if confirmed_b
                       else f"等待确认（需跌破{h2_p:.2f}）")
                ),
                "setup_price": round(h1_p, 2),
                "reversal_target": round(reversal_target, 2),
                "confirmed": confirmed_b,
                **result_base,
            }

    return {"detected": False, "type": None,
            "message": "无123结构", "setup_price": None,
            "reversal_target": None, "confirmed": False, **result_base}


# ══════════════════════════════════════════════════════════════════════════════
# P4 新增：H3（第三推）检测（P05 核心）
# ══════════════════════════════════════════════════════════════════════════════
def detect_h3_signal(bars: list) -> dict:
    """
    P05 原文：H3 = 第三推，通常是趋势末尾，弱信号
    L3 = 第三推空头版本

    三推判断：连续出现3个依次升高/降低的点，
    第3个之后趋势可能衰竭（即使没立即反转，也代表空间有限）

    返回：
      has_h3   : bool   是否出现H3
      has_l3   : bool   是否出现L3
      h3_bar   : dict   H3那根K线
      l3_bar   : dict   L3那根K线
      push_count: int   连续推次数（用于判断是否第三推+）
      note     : str    描述
    """
    if len(bars) < 8:
        return {"has_h3": False, "has_l3": False,
                "h3_bar": None, "l3_bar": None,
                "push_count": 0, "note": "数据不足"}

    recent = bars[-8:]

    # 扫描H系列（上涨中的推）：连续阳线且每个高点创新高
    h_pushes = []
    for i in range(len(recent)):
        close = float(recent[i]["close"])
        open_  = float(recent[i]["open"])
        high  = float(recent[i]["high"])
        is_bull = close > open_
        if is_bull:
            if not h_pushes or high > float(h_pushes[-1]["high"]):
                h_pushes.append(recent[i])
            else:
                # 高点没创新高，当前推结束，开始新一轮
                h_pushes = [recent[i]] if is_bull else []
        else:
            h_pushes = []

    # 扫描L系列（下跌中的推）
    l_pushes = []
    for i in range(len(recent)):
        close = float(recent[i]["close"])
        open_  = float(recent[i]["open"])
        low   = float(recent[i]["low"])
        is_bear = close < open_
        if is_bear:
            if not l_pushes or low < float(l_pushes[-1]["low"]):
                l_pushes.append(recent[i])
            else:
                l_pushes = [recent[i]] if is_bear else []
        else:
            l_pushes = []

    note_text = (
        f"连续推升{len(h_pushes)}次" if len(h_pushes) >= 3
        else f"连续下探{len(l_pushes)}次" if len(l_pushes) >= 3
        else "无连续推"
    )
    return {
        "has_h3": len(h_pushes) >= 3,
        "has_l3": len(l_pushes) >= 3,
        "h3_bar": h_pushes[-1] if len(h_pushes) >= 3 else None,
        "l3_bar": l_pushes[-1] if len(l_pushes) >= 3 else None,
        "push_count": max(len(h_pushes), len(l_pushes)),
        "note": note_text,
    }


# ══════════════════════════════════════════════════════════════════════════════
# P6 新增：TIBOW Reverse 两根K线反转（P08 核心）
# ══════════════════════════════════════════════════════════════════════════════
def detect_tibow_reverse(bars: list, lookback: int = 10) -> dict:
    """
    P08 原文：TIBOW Reverse = 后面K线吞没前面K线
    - 第1根：阴线（回调信号）
    - 第2根：大阳线（吞没前一根）= 反转向上信号

    做多 TIBOW Reverse：第1根阴线 + 第2根大阳线完全吞没
    做空 TIBOW Reverse：第1根阳线 + 第2根大阴线完全吞没

    返回：
      detected      : bool
      direction     : LONG | SHORT | NONE
      bar1 / bar2  : 两根K线数据
      engulf_ratio  : 吞没程度（第2根实体 / 第1根实体）
      message       : 描述
      quote         : Brooks 原文
    """
    if len(bars) < 3:
        return {"detected": False, "direction": "NONE",
                "bar1": None, "bar2": None,
                "engulf_ratio": None, "message": "", "quote": ""}

    recent = bars[-lookback:]

    for i in range(len(recent) - 1):
        b1 = recent[i]
        b2 = recent[i + 1]

        o1 = float(b1["open"]); c1 = float(b1["close"])
        o2 = float(b2["open"]); c2 = float(b2["close"])
        h1 = float(b1["high"]);  l1 = float(b1["low"])
        h2 = float(b2["high"]);  l2 = float(b2["low"])

        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)

        if body1 == 0 or body2 == 0:
            continue

        # ── 做多 TIBOW：第1根阴线，第2根阳线完全吞没 ──────────
        b1_bearish = c1 < o1
        b2_bullish = c2 > o2
        fully_engulfed = (
            b2_bullish and b1_bearish and
            o2 <= c1 and c2 >= o1 and  # 阳线低点≤阴线收盘，阳线高点≥阴线开盘
            body2 > body1               # 第2根实体大于第1根
        )

        if fully_engulfed:
            return {
                "detected": True,
                "direction": "LONG",
                "bar1": b1, "bar2": b2,
                "engulf_ratio": round(body2 / body1, 2),
                "message": (
                    f"TIBOW Reverse(LONG)检测到："
                    f"阴线({b1['date']})被阳线({b2['date']})完全吞没"
                    f"，反转向上信号"
                ),
                "quote": (
                    "P08\u300cTIBOW Reverse\uff1a\u4e24\u6839K\u7ebf\u53cd\u8f6c\uff0c\u540e\u9762\u6b63\u7ebf\u5b8c\u5168\u541e\u6ca1\u524d\u9762\u9634\u7ebf\uff0c\u8fd9\u662f\u91cd\u8981\u7684\u5165\u573a\u4fe1\u53f7\u300eBrooks\u300f"
                ),
            }

        # ── 做空 TIBOW：第1根阳线，第2根阴线完全吞没 ──────────
        b1_bullish = c1 > o1
        b2_bearish = c2 < o2
        fully_engulfed_short = (
            b2_bearish and b1_bullish and
            o2 >= c1 and c2 <= o1 and  # 阴线开盘≥阳线收盘，阴线低点≤阳线开盘
            body2 > body1
        )

        if fully_engulfed_short:
            return {
                "detected": True,
                "direction": "SHORT",
                "bar1": b1, "bar2": b2,
                "engulf_ratio": round(body2 / body1, 2),
                "message": (
                    f"TIBOW Reverse(SHORT)检测到："
                    f"阳线({b1['date']})被阴线({b2['date']})完全吞没"
                    f"，反转向下信号"
                ),
                "quote": (
                    "P08\u300cTIBOW Reverse\uff1a\u4e24\u6839K\u7ebf\u53cd\u8f6c\uff0c\u540e\u9762\u9634\u7ebf\u5b8c\u5168\u541e\u6ca1\u524d\u9762\u9633\u7ebf\uff0c\u8fd9\u662f\u91cd\u8981\u7684\u5165\u573a\u4fe1\u53f7\u300eBrooks\u300f"
                ),
            }

    return {"detected": False, "direction": "NONE",
            "bar1": None, "bar2": None,
            "engulf_ratio": None, "message": "无TIBOW形态",
            "quote": ""}


def calc_retracement(bars: list) -> dict:
    """
    P02 原文：50%回撤原则
    从近期高点回撤了多少？回撤到50%位是否有支撑？
    """
    if len(bars) < 20:
        return {"retracement_pct": None, "near_50_pct": False}
    recent = bars[-60:]
    highs = [float(b["high"]) for b in recent]
    lows = [float(b["low"]) for b in recent]
    max_high = max(highs)
    min_low = min(lows)
    latest_close = float(recent[-1]["close"])
    swing_range = max_high - min_low
    if swing_range == 0:
        return {"retracement_pct": None, "near_50_pct": False}
    # 当前从高点的回撤比例
    retracement_from_high = (max_high - latest_close) / swing_range * 100
    # 50%回撤位
    pct_50_level = max_high - swing_range * 0.50
    near_50 = abs(latest_close - pct_50_level) / pct_50_level < 0.02  # 2%误差内
    return {
        "retracement_pct": round(retracement_from_high, 1),
        "near_50_pct": near_50,
        "pct_50_level": round(pct_50_level, 2),
        "max_high": round(max_high, 2),
        "current_close": round(latest_close, 2),
    }


def calc_trend_structure(bars: list, spy_bars: list = None) -> dict:
    """
    P02/P05：市场趋势结构
    - EMA20/50/200 位置关系
    - 价格是否在EMA20之上
    - 趋势强弱
    - XLE vs SPY 相对强弱（20日）
    """
    min_bars = 200 if not spy_bars else max(200, len(spy_bars))
    if len(bars) < 50:
        return {}
    closes = [float(b["close"]) for b in bars]
    ema20 = _ema(closes, 20) if len(closes) >= 20 else [closes[0]] * len(closes)
    ema50 = _ema(closes, 50) if len(closes) >= 50 else [closes[0]] * len(closes)
    ema200 = _ema(closes, 200) if len(closes) >= 200 else [closes[0]] * len(closes)
    latest_close = closes[-1]

    result = {
        "above_ema20": latest_close > ema20[-1],
        "above_ema50": latest_close > ema50[-1],
        "ema20_above_ema50": ema20[-1] > ema50[-1],
        "ema50_above_ema200": ema50[-1] > ema200[-1],
        "ema20": round(ema20[-1], 2),
        "ema50": round(ema50[-1], 2),
        "ema200": round(ema200[-1], 2),
        "latest_close": latest_close,
    }

    # ── 相对强弱：个股 vs SPY 20日收益对比 ───────────────────
    if spy_bars and len(spy_bars) >= 21 and len(bars) >= 21:
        # 对齐K线数量（取较小者）
        n = min(20, len(spy_bars), len(bars))
        stock_ret_20d = (float(bars[-1]["close"]) - float(bars[-n-1]["close"])) / float(bars[-n-1]["close"]) * 100
        spy_ret_20d = (float(spy_bars[-1]["close"]) - float(spy_bars[-n-1]["close"])) / float(spy_bars[-n-1]["close"]) * 100
        rel_strength = stock_ret_20d - spy_ret_20d
        result["rel_strength_20d"] = round(rel_strength, 2)
        result["stock_ret_20d"] = round(stock_ret_20d, 2)
        result["spy_ret_20d"] = round(spy_ret_20d, 2)
        if rel_strength > 2:
            result["rel_strength_signal"] = "强势（相对大盘走强）"
        elif rel_strength < -2:
            result["rel_strength_signal"] = "弱势（相对大盘走弱）⚠️"
        else:
            result["rel_strength_signal"] = "中性（与大盘同步）"
    else:
        result["rel_strength_20d"] = None

    return result


def detect_signal_bar(bars: list) -> dict:
    """
    P07 原文：信号K线 = 趋势K线 + 收在极端位
    P09 原文：放量趋势K线可信度更高

    评估最近K线的信号质量，加入成交量对比
    """
    if len(bars) < 2:
        return {"quality": "NONE", "score": 0, "reasons": [], "candle_data": {}}
    latest = bars[-1]
    cq = candle_quality(float(latest["open"]), float(latest["close"]),
                         float(latest["high"]), float(latest["low"]))
    reasons = []
    score = 0
    if cq["is_trend_bar"]:
        score += 1
        reasons.append(f"趋势K线(实体{cq['body_ratio']:.0%})")
    else:
        reasons.append(f"震荡K线(实体{cq['body_ratio']:.0%})")
    # 收盘位置极端性
    day_range = float(latest["high"]) - float(latest["low"])
    close_pos = 0.0
    if day_range > 0:
        close_pos = (float(latest["close"]) - float(latest["low"])) / day_range
        if cq["is_bullish"] and close_pos >= 0.80:
            score += 2
            reasons.append(f"收盘在高位({close_pos:.0%})")
        elif cq["is_bullish"] and close_pos >= 0.60:
            score += 1
            reasons.append(f"收盘在中上位({close_pos:.0%})")
        elif not cq["is_bullish"] and close_pos <= 0.20:
            score += 2
            reasons.append(f"收盘在低位({close_pos:.0%})")
    # 成交量分析：与20日均量对比
    vol = float(latest.get("volume", 0))
    vol_ratio = 0.0
    if vol > 0 and len(bars) >= 20:
        recent_vols = [float(b.get("volume", 0)) for b in bars[-21:-1]]
        avg_vol = sum(recent_vols) / len(recent_vols) if recent_vols else 1
        vol_ratio = vol / avg_vol if avg_vol > 0 else 0.0
        if vol_ratio >= 1.5:
            score += 1
            reasons.append(f"量能放大({vol_ratio:.1f}x20日均量)")
        elif vol_ratio >= 1.0:
            reasons.append(f"量能正常({vol_ratio:.1f}x均量)")
        elif vol_ratio < 0.7:
            score -= 1
            reasons.append(f"⚠️缩量({vol_ratio:.1f}x均量)")
    quality = "STRONG" if score >= 3 else ("MEDIUM" if score >= 2 else "WEAK")
    return {"quality": quality, "score": score, "reasons": reasons,
            "candle_data": cq, "vol_ratio": round(vol_ratio, 2) if vol > 0 else None,
            "date": latest.get("date", ""), "vol": vol,
            "close_position_pct": round(close_pos, 3) if day_range > 0 else None}


def calc_risk_reward(bars: list, entry_price: float = None,
                        h1_info: dict = None) -> dict:
    """
    P13/P14/P16：Measured Move 目标 + ATR止损 + 盈亏比
    P02 原文：止损永远放在起涨点下方
    P16 原文：1%账户风险管理，≥3:1盈亏比

    关键改进：MM目标必须透明写出A→B→C三个点位：
    - A点：近期波段高点（MM起始）
    - B点：回调低点（MM终点）
    - C点：入场价 + (A-B) = MM目标

    逻辑：
    - 如果H1已失效（当前价 < H1低点），说明在走更深层回调
      → 止损放在更深层支撑（近期波段低点下方）
      → MM从更深层低点投射
    - 如果H1仍有效，止损在H1低点下方，目标用Measured Move
    """
    if len(bars) < 30 or entry_price is None:
        return {}
    recent = bars[-60:]
    closes = [float(b["close"]) for b in recent]
    highs = [float(b["high"]) for b in recent]
    lows = [float(b["low"]) for b in recent]
    atr = _atr(recent[-30:])
    latest_close = closes[-1]
    entry = entry_price or latest_close

    # ── 找近期波段高点A（在最后回调之前的高点）────────────────
    # 找最近20天内最后一个"局部高点"（高于前后邻的高点）
    look_back = min(20, len(recent) - 1)
    window_highs = [(float(recent[i]["high"]), recent[i]["date"], i)
                     for i in range(len(recent) - look_back, len(recent))]
    window_lows = [(float(recent[i]["low"]), recent[i]["date"], i)
                    for i in range(len(recent) - look_back, len(recent))]
    # 找最后一个局部高点（从旧到新扫描，找最后一个峰值）
    swing_high = max(h for h, _, _ in window_highs)
    swing_high_idx = None
    swing_high_date = None
    for h, d, idx in reversed(window_highs):
        if h == swing_high:
            swing_high_idx = idx
            swing_high_date = d
            break

    # ── 止损：放在近期波段低点下方（起涨点/回调低点）───────────
    # 找swing_high之后的最低点（真正的回调到达点）
    if swing_high_idx is not None:
        lows_after_high = [(float(recent[i]["low"]), recent[i]["date"], i)
                          for i in range(swing_high_idx, len(recent))]
        swing_low = min(l for l, _, _ in lows_after_high)
        swing_low_date = next(d for l, d, _ in lows_after_high if l == swing_low)
    else:
        swing_low = min(l for l, _, _ in window_lows)
        swing_low_date = next(d for l, d, _ in window_lows if l == swing_low)

    # 如果H1仍有效，用H1低点作为潜在止损参考
    h1_ref_text = ""
    stop_candidates = []
    if h1_info and h1_info.get("h1_bar"):
        h1_low = float(h1_info["h1_bar"]["low"])
        h1_date = h1_info["h1_bar"]["date"]
        h1_inv = h1_info.get("h1_invalidated", False)
        h1_ref_text = f"H1低点{h1_low:.2f}({h1_date})"
        if not h1_inv:
            # H1未失效：止损放在H1低点下方一个安全距离
            stop_candidates.append(("H1低点下方", h1_low - 0.05))
        else:
            # H1已失效：使用更深层支撑
            h1_ref_text += " ⚠️已失效"

    # 止损选择：波段低点下方
    stop_loss = swing_low * 0.995  # 波段低点下方
    stop_loss_date = swing_low_date

    risk_per_share = entry - stop_loss
    if risk_per_share <= 0:
        stop_loss = entry * 0.98
        risk_per_share = entry - stop_loss

    # ── Measured Move 计算（透明写出A→B→C）──────────────────────
    # MM = 入场价 + (A点高度 - B点深度)
    # A点 = 近期波段高点（最近一次上冲的高点）
    # B点 = 近期波段低点（回调到达的最低点）
    mm_range = swing_high - swing_low  # A - B
    mm_target = entry + mm_range        # C = Entry + (A-B)

    # 备选目标：突破前高 + Measured Move
    prev_high_target = swing_high + mm_range * 0.5  # 突破前高后量幅投射
    target = max(mm_target, prev_high_target)

    # 也考虑3R目标
    target_3r = entry + risk_per_share * 3
    target_4r = entry + risk_per_share * 4

    reward = target - entry
    rr_ratio = reward / risk_per_share if risk_per_share > 0 else 0
    rr_ratio_3r = (target_3r - entry) / risk_per_share if risk_per_share > 0 else 0
    rr_ratio_4r = (target_4r - entry) / risk_per_share if risk_per_share > 0 else 0

    return {
        "entry": round(entry, 2),
        "stop_loss": round(stop_loss, 2),
        "stop_loss_date": stop_loss_date,
        "target": round(target, 2),
        "target_3r": round(target_3r, 2),
        "target_4r": round(target_4r, 2),
        "risk_per_share": round(risk_per_share, 2),
        "reward": round(reward, 2),
        "rr_ratio": round(rr_ratio, 2),
        "atr": round(atr, 2),
        # MM透明三要素
        "mm_swing_high": round(swing_high, 2),
        "mm_swing_high_date": swing_high_date,
        "mm_swing_low": round(swing_low, 2),
        "mm_swing_low_date": swing_low_date,
        "mm_range": round(mm_range, 2),
        "mm_target": round(mm_target, 2),
        "h1_ref": h1_ref_text,
    }


# ═══════════════════════════════════════════════════════════════════
# L_BPS: 突破-回踩-站稳 细粒度量化分析
# ═══════════════════════════════════════════════════════════════════

def _bps_find_swing_points(bars: list, lookback: int = 60) -> dict:
    """
    找局部波段高低点（用于识别突破类型和支撑位）
    """
    if len(bars) < 5:
        return {"swing_highs": [], "swing_lows": []}

    recent = bars[-lookback:]
    swing_highs = []
    swing_lows = []

    for i in range(1, len(recent) - 1):
        curr_h = float(recent[i]["high"])
        prev_h = float(recent[i - 1]["high"])
        next_h = float(recent[i + 1]["high"])
        curr_l = float(recent[i]["low"])
        prev_l = float(recent[i - 1]["low"])
        next_l = float(recent[i + 1]["low"])

        if curr_h > prev_h and curr_h > next_h:
            swing_highs.append((i, curr_h, recent[i]["date"]))
        if curr_l < prev_l and curr_l < next_l:
            swing_lows.append((i, curr_l, recent[i]["date"]))

    return {"swing_highs": swing_highs, "swing_lows": swing_lows}


def _bps_detect_breakout(bars: list, sig_bar_high: float = None,
                           sig_bar_date: str = None) -> dict:
    """
    突破类型细分 + 量化指标

    Brooks 原文出处：
      P05 原文："只要他突破了前一根K线的高点，你去做多，这是一个入场点。"
      P09 原文："横盘整理后放量突破，这是入场机会。"
      P11 原文："顺大逆小：在大趋势中的突破更可靠。"

    输出字段：
      type        : 前高突破 | EMA20突破 | EMA50突破 | 横盘突破 | 趋势线突破
      price       : 突破价位
      date        : 突破日期
      vol_ratio   : 突破量 / 20日均量（>1.5x=放量突破）
      quality     : STRONG / MEDIUM / WEAK
      quote       : Brooks 原话
      range_pct   : 近20日振幅%（判断横盘 vs 趋势）
    """
    if len(bars) < 20:
        return {"type": "UNKNOWN", "price": None, "date": None,
                "vol_ratio": None, "quality": "WEAK", "quote": "",
                "prev_high_price": None, "ema20": None, "ema50": None,
                "range_pct": 0, "is_consolidating": False}

    closes = [float(b["close"]) for b in bars]
    highs  = [float(b["high"])  for b in bars]
    lows   = [float(b["low"])   for b in bars]
    vols   = [float(b.get("volume", 0)) for b in bars]
    dates  = [b["date"] for b in bars]

    ema20 = _ema(closes, 20)[-1] if len(closes) >= 20 else closes[-1]
    ema50 = _ema(closes, 50)[-1] if len(closes) >= 50 else closes[-1]

    # 近20日区间
    look_20 = min(20, len(highs))
    range_high = max(highs[-look_20:])
    range_low  = min(lows[-look_20:])
    range_pct  = (range_high - range_low) / range_low * 100 if range_low > 0 else 0
    is_consolidating = range_pct < 15.0  # 振幅<15%=横盘

    # 近20日次高点（排除最后一根，视为"前高"）
    sorted_highs = sorted(set([round(h, 2) for h in highs[-look_20:-1]]), reverse=True)
    prev_high_price = sorted_highs[0] if sorted_highs else range_high
    prev_high_idx   = highs.index(prev_high_price) if prev_high_price in highs else len(highs) - 2
    prev_high_date  = dates[prev_high_idx] if prev_high_idx < len(dates) else dates[-2]

    # 近20日均量
    vol_avg20 = sum(vols[-20:]) / 20 if len(vols) >= 20 else sum(vols) / max(1, len(vols))

    latest_close = closes[-1]
    prev_close   = closes[-2] if len(closes) >= 2 else closes[-1]

    # ── 突破类型判断 ────────────────────────────────────────
    break_type  = "UNKNOWN"
    break_price = prev_high_price
    break_date  = prev_high_date
    break_vol_ratio = None
    break_quality = "WEAK"

    # 类型1：前高突破（若 sig_bar_high > 近20日次高 = 突破确认）
    if sig_bar_high and sig_bar_high >= prev_high_price:
        break_type   = "前高突破"
        break_price  = sig_bar_high
        break_date   = sig_bar_date or dates[-1]
        break_quality = "STRONG"
    # 类型2：横盘突破（振幅<15% + 放量突破区间高点）
    elif is_consolidating and latest_close > range_high:
        break_type   = "横盘突破"
        break_price  = range_high
        break_date   = dates[-1]
        break_quality = "STRONG"
    # 类型3：EMA20突破（此前在EMA20下，收盘站上）
    elif (len(closes) >= 21 and prev_close < ema20 and latest_close > ema20):
        break_type   = "EMA20突破"
        break_price  = ema20
        break_date   = dates[-1]
        break_quality = "MEDIUM"
    # 类型4：EMA50突破
    elif (len(closes) >= 51 and prev_close < ema50 and latest_close > ema50):
        break_type   = "EMA50突破"
        break_price  = ema50
        break_date   = dates[-1]
        break_quality = "MEDIUM"
    # 类型5：趋势延续（顺势突破近期波段高点）
    elif latest_close > prev_high_price and not is_consolidating:
        break_type   = "趋势延续突破"
        break_price  = prev_high_price
        break_date   = prev_high_date
        break_quality = "MEDIUM"

    # 找突破日的成交量（突破日 = break_date 对应的 bar）
    try:
        break_idx = dates.index(break_date) if break_date in dates else -1
        if break_idx >= 0:
            break_vol_ratio = vols[break_idx] / vol_avg20 if vol_avg20 > 0 else None
    except (ValueError, IndexError):
        break_vol_ratio = None

    # Brooks 原文引用
    quote_map = {
        "前高突破": 'P05 \u300c\u4e00\u822c\u4ed6\u7a81\u7834\u4e86\u524d\u4e00\u6839K\u7ebf\u7684\u9ad8\u70b9\uff0c\u4f60\u53bb\u505a\u591a\uff0c\u8fd9\u662f\u4e00\u4e2a\u5165\u573a\u70b9\u300eBrooks\u300f',
        "\u6a2a\u76d8\u7a81\u7834": 'P09 \u300c\u5f53\u5e02\u573a\u6a2a\u76d8\u6574\u7406\u540e\u653e\u91cf\u7a81\u7834\uff0c\u8fd9\u5c31\u662f\u4e00\u4e2a\u5165\u573a\u7684\u673a\u4f1a\u300eBrooks\u300f',
        "EMA20\u7a81\u7834": 'P05 \u300c\u4ef7\u683c\u5982\u679c\u4e00\u76f4\u5728EMA20\u4e4b\u4e0a\uff0c\u8fd9\u662f\u5f3a\u52bf\u7279\u5f81\u300eBrooks\u300f',
        "EMA50\u7a81\u7834": 'P02 \u300cEMA50\u662f\u4e2d\u671f\u8d8b\u52bf\u7ebf\uff0c\u7a81\u7834EMA50\u4ee3\u8868\u4e2d\u671f\u8d8b\u52bf\u8f6c\u591a\u300eBrooks\u300f',
        "\u987a\u52bf\u5ef6\u7eed\u7a81\u7834": 'P11 \u300c\u987a\u5927\u9006\u5c0f\uff1a\u5728\u5927\u8d8b\u52bf\u4e2d\u7684\u7a81\u7834\u66f4\u53ef\u9760\u300eBrooks\u300f',
    }
    quote = quote_map.get(break_type, 'P05 \u300c\u5f3a\u52bf\u80a1\u603b\u662f\u7a81\u7834\u524d\u9ad8/\u5747\u7ebf\u65f6\u5165\u573a\u300eBrooks\u300f')

    return {
        "type": break_type,
        "price": round(break_price, 2),
        "date": break_date,
        "vol_ratio": round(break_vol_ratio, 2) if break_vol_ratio else None,
        "quality": break_quality,
        "quote": quote,
        "prev_high_price": round(prev_high_price, 2),
        "prev_high_date": prev_high_date,
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "range_pct": round(range_pct, 1),
        "is_consolidating": is_consolidating,
        "latest_close": round(latest_close, 2),
        "vol_avg20": round(vol_avg20, 0),
    }


def _bps_detect_pullback(bars: list, breakout_info: dict) -> dict:
    """
    回踩类型细分 + 支撑强度 + 跌破概率

    Brooks 原文出处：
      P02 原文："50%回撤是一个关键位置，市场在此处停顿是正常的。"
      P05 原文："强势股会回踩EMA20，这是最佳买入机会（Bread & Butter）。"
      P09 原文："回踩前期支撑/均线时等待反转K线，不预测何时结束。"
      P11 原文："Wedge失败=123失败，不追卖/买。"

    输出字段：
      type              : EMA20回踩 | 斐波50% | 斐波38.2% | 前期低点支撑 | 趋势线支撑
      support_price     : 支撑价位
      pullback_pct      : 从突破高点已回落%（最大回撤深度）
      break_prob        : HIGH / MEDIUM / LOW（跌破概率）
      distance_to_break : 距跌破位还有多少%（支撑到下一级支撑的距离）
      next_support_price: 下一级支撑位（跌破后的目标位）
      fib_50 / 382 / 618: 斐波那契回撤位
      quote             : Brooks 原话
    """
    if len(bars) < 30:
        return {"type": "NONE", "support_price": None,
                "pullback_pct": None, "break_prob": None,
                "distance_to_break": None, "quote": "",
                "fib_50": None, "fib_382": None, "fib_618": None}

    closes = [float(b["close"]) for b in bars]
    lows   = [float(b["low"])   for b in bars]
    highs  = [float(b["high"])  for b in bars]
    vols   = [float(b.get("volume", 0)) for b in bars]
    dates  = [b["date"] for b in bars]

    latest_close = closes[-1]
    ema20 = _ema(closes, 20)[-1] if len(closes) >= 20 else closes[-1]
    ema50 = _ema(closes, 50)[-1] if len(closes) >= 50 else closes[-1]

    # ── 斐波那契回撤位（近60日波段） ─────────────────────────
    look_60 = min(60, len(highs))
    seg_high = max(highs[-look_60:])
    seg_low  = min(lows[-look_60:])
    seg_range = seg_high - seg_low
    fib_50 = seg_low + seg_range * 0.50 if seg_range > 0 else None
    fib_382 = seg_low + seg_range * 0.382 if seg_range > 0 else None
    fib_618 = seg_low + seg_range * 0.618 if seg_range > 0 else None

    # ── 前期低点（近20日次低点作为支撑） ─────────────────────
    look_20 = min(20, len(lows))
    sorted_lows = sorted(set([round(l, 2) for l in lows[-look_20:-1]]))
    prev_support_price = sorted_lows[0] if sorted_lows else min(lows[-look_20:])
    prev_support_idx   = lows.index(prev_support_price) if prev_support_price in lows else len(lows) - 2
    prev_support_date  = dates[prev_support_idx]

    # ── 回踩类型判断（优先顺序：EMA20 > 斐波50% > 斐波61.8% > 前期低点） ─
    pullback_type  = "NONE"
    support_price  = None
    support_name   = ""

    # EMA20 回踩
    if abs(latest_close - ema20) / ema20 < 0.03:
        pullback_type = "EMA20回踩"
        support_price = ema20
        support_name  = f"EMA20({ema20:.2f})"
    # 斐波那契50% 回踩
    elif fib_50 and abs(latest_close - fib_50) / fib_50 < 0.025:
        pullback_type = "斐波50%回踩"
        support_price = fib_50
        support_name  = f"50%({fib_50:.2f})"
    # 斐波那契61.8% 回踩（更深的回踩）
    elif fib_618 and abs(latest_close - fib_618) / fib_618 < 0.025:
        pullback_type = "斐波61.8%回踩"
        support_price = fib_618
        support_name  = f"61.8%({fib_618:.2f})"
    # 前期低点支撑
    elif abs(latest_close - prev_support_price) / prev_support_price < 0.025:
        pullback_type = "前期低点支撑"
        support_price = prev_support_price
        support_name  = f"前期低点({prev_support_price:.2f})"

    # ── 最大回撤深度 ─────────────────────────────────────────
    breakout_price = breakout_info.get("price", seg_high)
    pullback_pct = 0.0
    if breakout_price > 0:
        pullback_pct = max(0.0, (breakout_price - latest_close) / breakout_price * 100)

    # ── 跌破概率计算 ─────────────────────────────────────────
    # 思路：找下一个更低支撑位，计算当前支撑到它的距离
    # 距离 < 1% = HIGH，< 3% = MEDIUM，>= 3% = LOW
    break_prob        = None
    distance_to_break = None
    next_support_price = None

    if pullback_type != "NONE" and support_price:
        # 从历史低点中找比当前支撑更低的点
        lower_points = [l for l in lows[-look_60:-1] if l < support_price * 0.99]
        if lower_points:
            next_support_price = min(lower_points)
            distance_to_break = (support_price - next_support_price) / support_price * 100
            if distance_to_break < 1.0:
                break_prob = "HIGH"
            elif distance_to_break < 3.0:
                break_prob = "MEDIUM"
            else:
                break_prob = "LOW"

    # ── Brooks 原文引用 ───────────────────────────────────────
    quote_map = {
        "EMA20回踩": ('P05 \u300c\u5f3a\u52bf\u80a1\u4f1a\u56de\u8e0bEMA20\uff0c\u8fd9\u662f\u6700\u4f73\u4e70\u5165\u673a\u4f1a\u300eBrooks\u300f'),
        "\u6590\u6ce25.0%\u56de\u8e0b": ('P02 \u300c50%\u56de\u6483\u662f\u4e00\u4e2a\u5173\u952e\u4f4d\u7f6e\uff0c\u5982\u679c\u5e02\u573a\u5728\u6b64\u5904\u51fa\u73b0\u53cd\u8f6cK\u7ebf\uff0c\u8fd9\u662f\u4e00\u4e2a\u91cd\u8981\u7684\u4e70\u5165\u673a\u4f1a\u300eBrooks\u300f'),
        "\u6590\u6ce261.8%\u56de\u8e0b": ('P02 \u300c61.8%\u662f\u66f4\u5f3a\u652f\u6491\u4f4d\uff0c\u5e02\u573a\u5728\u6b64\u5904\u505c\u7559\u540e\u6062\u590d\u8d8b\u52bf\u7684\u6982\u7387\u5927\u300eBrooks\u300f'),
        "\u524d\u671f\u4f4e\u70b9\u652f\u6491": ('P09 \u300c\u5982\u679c\u56de\u8e0b\u524d\u671f\u652f\u6491\u4f4d\u5e76\u51fa\u73b0\u9527\u5b50\u7ebf\u6216\u541e\u566cK\u7ebf\uff0c\u8fd9\u662f\u7b2c\u4e8c\u6b21\u4e70\u5165\u673a\u4f1a\u300eBrooks\u300f'),
    }
    quote = quote_map.get(pullback_type, 'P05 \u300c\u5065\u5eb7\u7684\u56de\u8e0b\u5e94\u8be5\u7f29\u91cf\uff0c\u4e14\u4e0d\u7834\u8d25\u91cd\u8981\u652f\u6491\u300eBrooks\u300f')

    return {
        "type": pullback_type,
        "support_price": round(support_price, 2) if support_price else None,
        "support_name": support_name,
        "pullback_pct": round(pullback_pct, 2),
        "break_prob": break_prob,
        "distance_to_break_pct": round(distance_to_break, 2) if distance_to_break else None,
        "next_support_price": round(next_support_price, 2) if next_support_price else None,
        "quote": quote,
        "fib_50": round(fib_50, 2) if fib_50 else None,
        "fib_382": round(fib_382, 2) if fib_382 else None,
        "fib_618": round(fib_618, 2) if fib_618 else None,
        "prev_support_date": prev_support_date,
    }


def _bps_detect_stand_firm(bars: list, breakout_info: dict,
                             pullback_info: dict) -> dict:
    """
    站稳量化判断

    Brooks 原文出处：
      P05 原文："H1 = 回调后第一根突破前高的阳线，多头重新夺回控制权。"
      P09 原文："Bread & Butter set-up = 强势股回踩后再次上涨。"
      P11 原文："Wedge失败=123，看止损位是否被守住。"

    站稳五条件（全部满足 = confirmed）：
      1. 出现 H1（回调后第一根阳线突破前高）
      2. 收盘重新站上回踩支撑位
      3. 回踩量 < 突破量 × 0.6（优质缩量）
      4. 最大回踩深度 < 突破振幅 × 0.5
      5. 回踩时长 ≤ 8 根K线
    """
    if len(bars) < 10:
        return {"confirmed": False, "h1_found": False,
                "volume_ratio": None, "depth_ratio": None,
                "duration_bars": None, "quote": "",
                "vol_ratio_ok": None, "depth_ratio_ok": None,
                "stand_above_support": False}

    closes = [float(b["close"]) for b in bars]
    highs  = [float(b["high"])  for b in bars]
    lows   = [float(b["low"])   for b in bars]
    vols   = [float(b.get("volume", 0)) for b in bars]
    dates  = [b["date"] for b in bars]

    latest_close = closes[-1]
    latest_date  = dates[-1]

    vol_avg20 = sum(vols[-20:]) / 20 if len(vols) >= 20 else sum(vols) / max(1, len(vols))

    # ── 1. H1 检测（近5根K线内，且未过期：距今≤20根K线） ─────────────
    # 从最新bar往回数（倒序），检查每个bar是否突破前一根K线高点
    h1_found  = False
    h1_bar    = None
    h1_date   = None
    h1_stale  = False
    # i = 从 bars[-2] 到 bars[-6]（即倒数第2根到倒数第6根，共5根）
    for offset in range(1, min(6, len(bars))):  # offset=1→bars[-2], offset=2→bars[-3], ...
        i = len(bars) - 1 - offset  # 绝对索引
        if i < 1:
            break
        prev_high  = float(bars[i - 1]["high"])
        curr_close = float(bars[i]["close"])
        curr_open  = float(bars[i]["open"])
        if curr_close > curr_open and curr_close > prev_high:
            bars_since_h1 = offset  # offset=1 means 1 bar ago
            if bars_since_h1 > 20:
                h1_stale = True
                h1_found = False
                break
            h1_found = True
            h1_bar    = bars[i]
            h1_date   = bars[i]["date"]
            break

    # ── 2. 收盘是否站上回踩支撑位 ─────────────────────────────
    support_price  = pullback_info.get("support_price")
    stand_above_support = True
    if support_price:
        stand_above_support = latest_close > support_price

    # ── 3. 回踩量 vs 突破量（优质缩量标准） ───────────────────
    # 回踩区间均量 vs 突破日量
    breakout_vol_ratio = breakout_info.get("vol_ratio")
    # 回踩期间（最近5日）均量
    pullback_vol_avg = sum(vols[-5:]) / 5 if len(vols) >= 5 else sum(vols) / max(1, len(vols))
    vol_ratio_actual = pullback_vol_avg / vol_avg20 if vol_avg20 > 0 else None

    vol_ratio_ok = None
    vol_comment  = ""
    if vol_ratio_actual is not None:
        vol_ratio_ok = vol_ratio_actual < 0.6
        vol_comment  = f"回踩均量={vol_ratio_actual:.0%}×20日均量"

    # ── 4. 最大回踩深度 vs 突破振幅 ───────────────────────────
    # 突破振幅 = 近20日高点 - 低点
    look_20 = min(20, len(bars))
    range_high_20 = max(highs[-look_20:])
    range_low_20  = min(lows[-look_20:])
    range_20_pct  = (range_high_20 - range_low_20) / range_low_20 * 100 if range_low_20 > 0 else 0

    pullback_pct = pullback_info.get("pullback_pct", 0) or 0
    # 最大回踩深度应 < 突破振幅 × 0.5（最多跌回去一半）
    depth_ratio_ok  = pullback_pct < range_20_pct * 0.5
    depth_ratio     = round(pullback_pct / range_20_pct, 2) if range_20_pct > 0 else None

    # ── 5. 回踩时长（回踩高点到H1的K线根数） ─────────────────
    # 找到回踩开始的位置（突破后的高点区间）
    _bo_price = breakout_info.get("price")
    breakout_price = _bo_price if _bo_price is not None else highs[-1]
    pullback_start_idx = None
    for i in range(len(bars) - 2, max(0, len(bars) - 15), -1):
        if float(bars[i]["high"]) >= breakout_price * 0.99:
            pullback_start_idx = i
            break

    duration_bars = None
    duration_ok    = None
    if pullback_start_idx is not None and h1_bar:
        try:
            h1_idx = bars.index(h1_bar)
            if h1_idx > pullback_start_idx:
                duration_bars = h1_idx - pullback_start_idx
                duration_ok    = duration_bars <= 8
        except ValueError:
            pass

    # ── 6. 综合判断 ──────────────────────────────────────────
    h1_status = "h1_found"
    if h1_stale:
        h1_status = "h1_stale"
    checks = {
        "h1": h1_found if not h1_stale else False,
        "stand_above_support": stand_above_support,
        "vol_ratio_ok": vol_ratio_ok,
        "depth_ratio_ok": depth_ratio_ok,
        "duration_ok": duration_ok,
    }
    confirmed = all(v is True for v in checks.values())

    # Brooks 引用
    if confirmed:
        quote = ('P05 \u300cH1\u51fa\u73b0\u4ee3\u8868\u56de\u8c03\u7ed3\u675f\uff0c\u591a\u5934\u91cd\u65b0\u5962\u56de\u63a7\u5236\u6743\uff0c\u8fd9\u662f\u6700\u4f73\u4e70\u5165\u65f6\u673a\u300eBrooks\u300f')
    else:
        failed = [k for k, v in checks.items() if v is False]
        stale_note = "（H1已过期>20根K线）" if h1_stale else ""
        quote = (f'P09 \u300c\u5f3a\u52bf\u80a1\u56de\u8e0b\u540e\u5e94\u8fc5\u901f\u4f01\u7a33\uff0c\u5426\u5219\u53ef\u80fd\u662f\u9677\u9631\u300eBrooks\u300f\uff1b\u672a\u901a\u8fc7\u9879\uff1a{stale_note}{", ".join(failed)}')

    return {
        "confirmed": confirmed,
        "h1_found": h1_found if not h1_stale else False,
        "h1_date": h1_date,
        "h1_stale": h1_stale,
        "stand_above_support": stand_above_support,
        "support_price": round(support_price, 2) if support_price else None,
        "volume_ratio": round(vol_ratio_actual, 2) if vol_ratio_actual else None,
        "vol_ratio_ok": vol_ratio_ok,
        "vol_comment": vol_comment,
        "max_pullback_pct": round(pullback_pct, 2),
        "depth_ratio": depth_ratio,
        "depth_ratio_ok": depth_ratio_ok,
        "range_20_pct": round(range_20_pct, 1),
        "duration_bars": duration_bars,
        "duration_ok": duration_ok,
        "quote": quote,
        "checks": checks,
    }


# ═══════════════════════════════════════════════════════════════════
# 五层过滤引擎
# ═══════════════════════════════════════════════════════════════════

class BuyFilterEngine:
    """
    Brooks 五层买入过滤系统

    字幕原文依据：
    L1 - P02牛市四阶段 / P09 82%规则 / P04 大盘分类
    L2 - P05 H1/L1数K线 / P10 好Wedge vs 坏Wedge / P11 顺大逆小
    L3 - P02 50%回撤 / P05 EMA20回踩 / P09 Bread & Butter
    L4 - P07 信号K线 / P09 背景×信号矩阵
    L5 - P13 Measured Move / P02 止损位置 / P16 盈亏比
    """

    def __init__(self, ticker: str, bars: list, spy_bars: list = None):
        self.ticker = ticker
        self.bars = bars
        self.spy_bars = spy_bars or bars  # 无SPY数据时用个股数据
        self.results = {}

    # ── L0: 多时间框架确认（1h + 日线联动） ─────────────────────
    def layer0_intraday_check(self, bars_1h: list = None,
                                daily_entry_price: float = None) -> dict:
        """
        P05 顺势交易 + P09 市场环境：多时间框架确认

        1h K线分析（Brooks核心思想）：
        - 1h EMA20/50 趋势方向（短期均线的位置关系）
        - 1h H1/L1 信号（与日线H1共振 = 更强信号）
        - 流动性猎杀检测（bearish liquidation bar = 机构派发）
        - Buy Stop 触发状态（日线入场价是否被日内触及）

        评分（满分4分）：
        +1  1h EMA20 在 EMA50 上方（多头排列）
        +1  价格在 1h EMA20 之上
        +1  1h 有新的 H1 信号（与日线方向共振）
        +1  无流动性猎杀（无大量阴线砸盘）
        ─────────────────────────────────
        Buy Stop 未触发 → 观望信号
        Buy Stop 已触发 → 积极关注
        流动性猎杀存在 → 短期弱势，下降趋势中
        """
        result = {
            "has_1h_data": bars_1h is not None and len(bars_1h) > 0,
            "ema20_1h": None, "ema50_1h": None,
            "price_vs_ema20_1h": None, "ema_bull_1h": None,
            "h1_1h": None, "l1_1h": None,
            "bearish_liquidation": None,
            "buy_stop_triggered": False,
            "buy_stop_price": daily_entry_price,
            "buy_stop_triggered_datetime": None,
            "buy_stop_triggered_high": None,
            "score": 0, "reasons": [],
            "action": "NO_SIGNAL",  # NO_SIGNAL / WATCH / READY
        }

        # ── 1h 数据存在时才做 EMA / H1 / 流动性分析 ────────────────────
        if bars_1h and len(bars_1h) >= 20:
            closes_1h = [float(b["close"]) for b in bars_1h]
            e20_1h = _ema(closes_1h, 20)[-1]
            e50_1h = _ema(closes_1h, 50)[-1]
            last_close_1h = closes_1h[-1]
            above_e20_1h = last_close_1h > e20_1h
            above_e50_1h = last_close_1h > e50_1h
            ema_bull_1h = e20_1h > e50_1h
            result["ema20_1h"] = round(e20_1h, 2)
            result["ema50_1h"] = round(e50_1h, 2)
            result["price_vs_ema20_1h"] = above_e20_1h
            result["ema_bull_1h"] = ema_bull_1h
            result["last_close_1h"] = round(last_close_1h, 2)
            sig_1h = detect_h1_signal_1h(bars_1h)
            result["h1_1h"] = sig_1h.get("has_h1", False)
            result["l1_1h"] = sig_1h.get("has_l1", False)
            result["h1_1h_bar"] = sig_1h.get("h1_bar")
            result["bearish_liquidation"] = sig_1h.get("bearish_liquidation")
            liq = sig_1h.get("bearish_liquidation")
            score = 0
            reasons = []
            if ema_bull_1h:
                score += 1
                reasons.append(f"1h EMA多头排列(EMA20={e20_1h:.2f}>EMA50={e50_1h:.2f})")
            else:
                reasons.append(f"1h EMA空头排列(EMA20={e20_1h:.2f}<EMA50={e50_1h:.2f})")
            if above_e20_1h:
                score += 1
                reasons.append(f"价格({last_close_1h:.2f})>1h EMA20({e20_1h:.2f})")
            else:
                reasons.append(f"价格({last_close_1h:.2f})<1h EMA20({e20_1h:.2f})⚠️")
            if sig_1h.get("has_h1"):
                score += 1
                h1_dt = sig_1h["h1_bar"]["datetime"]
                reasons.append(f"1h H1({h1_dt})")
            else:
                reasons.append("1h 无新H1信号")
            if not liq:
                score += 1
                reasons.append("无流动性猎杀✅")
            else:
                reasons.append(f"⚠️流动性猎杀:{liq['datetime']}跌{liq['drop_pct']}%量{liq['vol_ratio']}x")
            result["score"] = score
            result["reasons"] = reasons
            if liq:
                result["action"] = "LIQUIDATION"
            elif daily_entry_price and result["buy_stop_triggered"]:
                result["action"] = "TRIGGERED"
            elif sig_1h.get("has_h1") and above_e20_1h:
                result["action"] = "READY"
            elif sig_1h.get("has_h1") or above_e20_1h:
                result["action"] = "WATCH"
            else:
                result["action"] = "NO_SIGNAL"
            result["reason_text"] = "; ".join(reasons)
        else:
            # 无1h数据：只检查 Buy Stop，不评分
            result["reason_text"] = "无1h数据（回测模式），仅用日线Buy Stop检测"

        # ── Buy Stop 触发检测（无1h数据时仍需执行）─────────────────────
        if daily_entry_price:
            if bars_1h and len(bars_1h) >= 20:
                # 扫1h bars捕捉触发时间
                for b in bars_1h[-16:]:
                    if float(b["high"]) >= daily_entry_price:
                        result["buy_stop_triggered"] = True
                        result["buy_stop_triggered_datetime"] = b["datetime"]
                        result["buy_stop_triggered_high"] = round(float(b["high"]), 2)
                        break
            # 日线high兜底（覆盖after-hours）
            if not result["buy_stop_triggered"] and self.bars:
                last_high = float(self.bars[-1]["high"])
                last_date  = self.bars[-1].get("date", "?")
                if last_high >= daily_entry_price:
                    result["buy_stop_triggered"] = True
                    result["buy_stop_triggered_datetime"] = f"{last_date}(日线after-hours)"
                    result["buy_stop_triggered_high"] = round(last_high, 2)

        self.results["L0"] = result
        return result

    # ── L1: 市场环境 ─────────────────────────────────────────────
    def layer1_market_environment(self) -> dict:
        """
        P02 原文：牛市四阶段决定能做哪种操作
        P09 原文：82%规则，强趋势80%延续

        评分标准（满分3分，每满足一项得1分）：
        +1 SPY 在 EMA20 之上
        +1 SPY 在 EMA50 之上（EMA50 > EMA200 表明长期多头）
        +1 SPY 在 EMA200 之上
        ─────────────────────────────────────────
        0分：SPY 在 EMA20 之下 → BEAR，禁止买入
        1分：SPY 在 EMA20 之上但 < EMA50 → BULL_WEAK，谨慎
        2分：SPY 在 EMA20 + EMA50 之上但 < EMA200 →
        3分：SPY 在 EMA20 + EMA50 + EMA200 之上 → BULL 最佳环境
        """
        ts = calc_trend_structure(self.spy_bars)
        if not ts:
            return {"pass": False, "regime": "UNKNOWN", "score": 0,
                    "reason": "数据不足"}
        spy_close = ts["latest_close"]
        ema20 = ts["ema20"]
        ema50 = ts["ema50"]
        ema200 = ts.get("ema200", ema50)

        # 逐项打分
        cond_above_ema20 = spy_close > ema20
        cond_above_ema50 = spy_close > ema50
        cond_ema50_above_ema200 = ts.get("ema50_above_ema200", ema50 > ema200)
        cond_above_ema200 = spy_close > ema200

        score = 0
        score_items = []
        if cond_above_ema20:
            score += 1; score_items.append(f"SPY>{ema20:.2f}(EMA20) ✅")
        else:
            score_items.append(f"SPY<{ema20:.2f}(EMA20) ❌")
        if cond_above_ema50:
            score += 1; score_items.append(f"SPY>{ema50:.2f}(EMA50) ✅")
        else:
            score_items.append(f"SPY<{ema50:.2f}(EMA50) ❌")
        if cond_above_ema200:
            score += 1; score_items.append(f"SPY>{ema200:.2f}(EMA200) ✅")
        else:
            score_items.append(f"SPY<{ema200:.2f}(EMA200) ❌")

        if spy_close > ema20 and spy_close > ema50 and spy_close > ema200:
            regime = "BULL"
        elif spy_close > ema20 and spy_close > ema50:
            regime = "BULL_WEAK"
        elif spy_close < ema20:
            regime = "BEAR"
            score = 0
        else:
            regime = "NEUTRAL"

        pass_ = score >= 2
        reason = f"SPY({spy_close:.2f}) vs EMA20({ema20:.2f})/EMA50({ema50:.2f})/EMA200({ema200:.2f}) → {regime}"
        score_detail = " | ".join(score_items)
        self.results["L1"] = {
            "pass": pass_, "regime": regime, "score": score,
            "reason": reason, "score_detail": score_detail,
            "score_items": score_items,
            "details": ts}
        return self.results["L1"]

    # ── L2: 趋势方向 ─────────────────────────────────────────────
    def layer2_trend_direction(self) -> dict:
        """
        P05 原文：H1 = 回调后第一根突破前高的阳线，多头重新夺回控制
        P11 原文：顺大逆小，趋势中的Wedge是Bull Flag不预期反转

        核心逻辑：
        - H1信号存在 → 趋势方向看涨（H1是一个调整结束的标志）
        - 但如果H1已被后续K线收盘跌破低点 → H1失效
          → 趋势方向仍为上涨，但深度调整中，不宜追买
          → 需要等待新的入场信号（可能在L3/Bread & Butter中）

        评分：
        - 有H1 + H1仍有效 → +3分（趋势明确）
        - 有H1 + H1已失效 → +1分（趋势方向仍有效，但需等待新信号）
        - Falling Wedge → +2分
        - 价格在EMA20之上 → +1分
        - EMA多头排列 → +1分
        """
        ts = calc_trend_structure(self.bars, self.spy_bars)
        h1 = detect_h1_signal(self.bars)
        h3 = detect_h3_signal(self.bars)             # P4: H3第三推检测
        flag = detect_bull_bear_flag(self.bars)     # P2: Bull/Bear Flag区分
        wedge = detect_falling_wedge(self.bars)
        if not ts:
            return {"pass": False, "score": 0, "reason": "数据不足"}

        score = 0
        reasons = []
        h3_penalty = False

        # ── H3 第三推：趋势末尾警告 ───────────────────────────
        if h3["has_h3"]:
            reasons.append(f"⚠️ H3检测：{h3['note']}，趋势可能接近尾声")
            h3_penalty = True  # H3出现时后续H1权重降低

        # ── Bull/Bear Flag 检测（P11 顺大逆小核心）─────────────
        if flag["type"] in ("BULL_FLAG", "BEAR_FLAG"):
            score += 2
            ctx = "趋势延续" if flag["context"] == "TREND_CONTINUATION" else "反转信号"
            reasons.append(f"{flag['type']} [{ctx}]: {flag['message'][:70]}")

        # H1信号
        if h1["has_h1"]:
            if h1["h1_invalidated"]:
                score += 1
                inv_date = h1.get("invalidation_date", "?")
                h1_low = float(h1["h1_bar"]["low"])
                reasons.append(
                    f"H1({h1['h1_bar']['date']})已失效⚠️ 跌破H1低点{h1_low:.2f}于{inv_date}，"
                    f"趋势向上但在深层回调中"
                )
            elif h3_penalty:
                score += 1  # H3出现时H1权重降低
                reasons.append(f"H1({h1['h1_bar']['date']})存在但⚠️ H3共振（空间有限）")
            else:
                score += 3
                reasons.append(f"H1({h1['h1_bar']['date']})仍有效 ✅")

        # Falling Wedge（独立检测）
        if wedge["detected"]:
            score += 2
            reasons.append(f"Falling Wedge: {wedge['message'][:60]}")

        # 价格在EMA20之上
        if ts["above_ema20"]:
            score += 1
            reasons.append("价格在EMA20之上")

        # EMA多头排列
        if ts["ema20_above_ema50"] and ts["ema50_above_ema200"]:
            score += 1
            reasons.append("EMA多头排列")

        # 有L1无H1 → 下跌趋势
        if h1["has_l1"] and not h1["has_h1"]:
            score = max(0, score - 2)
            reasons.append("L1信号: 趋势向下")

        pass_ = score >= 2
        self.results["L2"] = {"pass": pass_, "score": score,
                               "reason": "; ".join(reasons) if reasons else "无明确信号",
                               "h1": h1, "h3": h3, "flag": flag,
                               "wedge": wedge, "trend": ts}
        return self.results["L2"]

    # ── L3: 入场形态 ─────────────────────────────────────────────
    def layer3_entry_form(self) -> dict:
        """
        P02 原文：50%回撤=关键支撑，趋势延续概率大
        P05 原文：强势趋势紧贴EMA20，深度回调可能是陷阱
        P09 原文：Bread & Butter = 强势中等回踩支撑位

        形态优先级（从高到低）：
        ① Bread & Butter：回踩EMA20/趋势线 + 50%位企稳
        ② First Entry：区间突破后回调不破区间顶
        ③ Pullback in Trend：回踩50%位
        """
        retr = calc_retracement(self.bars)
        ts = calc_trend_structure(self.bars, self.spy_bars)
        trendline = detect_trendline_support(self.bars)  # P1: 趋势线支撑检测
        tibow = detect_tibow_reverse(self.bars)           # P6: TIBOW 两根K线反转
        if not ts:
            return {"pass": False, "score": 0, "reason": "数据不足"}

        score = 0
        reasons = []
        form_type = None

        # ── 趋势线回踩支撑（P02/P05 核心支撑位）────────────────
        if trendline["detected"]:
            score += 3
            form_type = "TRENDLINE_SUPPORT"
            reasons.append(
                f"趋势线支撑: 价格回踩趋势线({trendline['trendline_price']:.2f})"
                f"±{trendline['distance_pct']:.1f}%，触及{trendline['touch_count']}次"
            )
        elif trendline["broken"]:
            score -= 2
            reasons.append(
                f"⚠️ 趋势线已破({trendline['trendline_price']:.2f})，形态转弱"
            )

        # ── TIBOW Reverse ────────────────────────────────────
        if tibow["detected"]:
            score += 2
            reasons.append(
                f"TIBOW Reverse({tibow['direction']}): "
                f"{tibow['bar1']['date']}→{tibow['bar2']['date']} "
                f"吞没比{tibow['engulf_ratio']:.1f}x"
            )
            if form_type is None:
                form_type = f"TIBOW_{tibow['direction']}"

        # Bread & Butter：回踩EMA20附近
        if ts["above_ema20"]:
            ema20 = ts["ema20"]
            latest_close = ts["latest_close"]
            dist_to_ema = abs(latest_close - ema20) / ema20
            if dist_to_ema < 0.03:  # 3%内
                if form_type is None:
                    form_type = "BREAD_BUTTER"
                if trendline["detected"]:
                    score += 1  # 趋势线+EMA20 双支撑额外加分
                    reasons.append(f"趋势线+EMA20双重支撑 ✅")
                else:
                    score = max(score, 3)
                    reasons.append(f"Bread & Butter: 距EMA20({ema20:.2f})仅{dist_to_ema*100:.1f}%")

        # 回踩50%位
        if retr["near_50_pct"]:
            score += 2
            reasons.append(f"50%回撤位({retr['pct_50_level']:.2f})附近")

        # 回撤幅度合理（20%-50%）
        if retr["retracement_pct"] is not None:
            rp = retr["retracement_pct"]
            if 20 <= rp <= 50:
                score += 2
                reasons.append(f"回撤幅度合理({rp:.1f}%)")
            elif rp > 50:
                score -= 1
                reasons.append(f"⚠️深度回撤({rp:.1f}%)可能破坏趋势")

        pass_ = score >= 2
        self.results["L3"] = {"pass": pass_, "score": score,
                               "reason": "; ".join(reasons) if reasons else "无明确形态",
                               "form_type": form_type,
                               "retracement": retr,
                               "trendline": trendline,
                               "tibow": tibow}
        return self.results["L3"]

    # ── L4: K线信号 ─────────────────────────────────────────────
    def layer4_kline_signal(self) -> dict:
        """
        P07 原文：信号K线 = 趋势K线(实体≥60%) + 收在极端位
        P09 原文：背景>>信号，差背景+好信号=禁止

        过滤规则：
        - 好信号K（趋势K线+收在极端位）→ +2分
        - 中等信号 → +1分
        - Buy Stop入场位明确 → +1分
        """
        sig = detect_signal_bar(self.bars)
        ts = calc_trend_structure(self.bars, self.spy_bars)
        if not ts:
            return {"pass": False, "score": 0}
        score = sig["score"]
        reasons = sig["reasons"]
        # 背景判断
        if ts["above_ema20"] and ts["ema20_above_ema50"]:
            score += 1
            reasons.append("好背景(多头排列)")
        else:
            score -= 1
            reasons.append("⚠️差背景")
        pass_ = score >= 3
        self.results["L4"] = {"pass": pass_, "score": score,
                               "reason": "; ".join(reasons),
                               "signal": sig}
        return self.results["L4"]

    # ── L5: 风险收益 ─────────────────────────────────────────────
    def layer5_risk_reward(self, h1_info: dict = None) -> dict:
        """
        P13 原文：Measured Move = 结构高度 → 目标位 = 突破点±结构高度
        P02 原文：止损永远放在起涨点下方
        P16 原文：盈亏比≥3:1，1%仓位管理

        过滤规则：
        - 盈亏比 ≥ 3:1 → +2分
        - 盈亏比 ≥ 5:1 → +1分额外
        - 止损清晰（ATR内）→ +1分
        - 盈亏比 < 2:1 → 一票否决
        """
        latest_close = float(self.bars[-1]["close"])
        rr = calc_risk_reward(self.bars, entry_price=latest_close, h1_info=h1_info)
        if not rr:
            return {"pass": False, "score": 0, "reason": "数据不足"}
        score = 0
        reasons = []
        veto = False
        rr_ratio = rr["rr_ratio"]
        if rr_ratio >= 5:
            score += 3
            reasons.append(f"优秀盈亏比({rr_ratio}:1)")
        elif rr_ratio >= 3:
            score += 2
            reasons.append(f"达标盈亏比({rr_ratio}:1)")
        elif rr_ratio >= 2:
            score += 1
            reasons.append(f"盈亏比偏低({rr_ratio}:1)")
        else:
            veto = True
            reasons.append(f"❌盈亏比不足({rr_ratio}:1) < 2:1 一票否决")
        # 止损距离 ATR 内
        atr = rr["atr"]
        risk = rr["risk_per_share"]
        if atr > 0 and risk <= atr * 2:
            score += 1
            reasons.append(f"止损在ATR内({atr:.2f})")
        entry = rr["entry"]
        stop = rr["stop_loss"]
        target = rr["target"]
        reasons.append(f"入场{entry}→止损{stop}(-{risk:.2f})→目标{target}(+{rr['reward']:.2f})")
        pass_ = score >= 2 and not veto
        self.results["L5"] = {"pass": pass_, "score": score,
                               "reason": "; ".join(reasons),
                               "details": rr, "veto": veto}
        return self.results["L5"]

    # ── 综合评级 ─────────────────────────────────────────────
    def run(self, bars_1h: list = None, daily_entry_price: float = None) -> dict:
        # L0: 多时间框架（1h + 日线联动）
        l0 = self.layer0_intraday_check(bars_1h=bars_1h,
                                          daily_entry_price=daily_entry_price)
        l1 = self.layer1_market_environment()
        l2 = self.layer2_trend_direction()
        l3 = self.layer3_entry_form()
        l4 = self.layer4_kline_signal()
        # 将L2的H1信息传给L5（用于MM止损计算）
        h1_info = l2.get("h1", {})
        l5 = self.layer5_risk_reward(h1_info=h1_info)

        # L_BPS: 突破-回踩-站稳 细粒度量化（在 STAGE 判断前计算）
        bps = self.layer_bps()

        # 通过的层数（L1-L5）
        passed = sum([l1["pass"], l2["pass"], l3["pass"], l4["pass"], l5["pass"]])
        scores = {
            "L0_intraday": l0.get("score", 0),
            "L1_market": l1.get("score", 0),
            "L2_trend": l2.get("score", 0),
            "L3_form": l3.get("score", 0),
            "L4_signal": l4.get("score", 0),
            "L5_risk": l5.get("score", 0),
        }
        total_score = sum(scores.values())

        # 评级
        if l1["regime"] == "BEAR":
            grade = "F"
            advice = "❌ 大盘处于空头市场，禁止买入"
        elif l5.get("veto"):
            grade = "F"
            advice = "❌ 盈亏比不足，一票否决"
        elif passed >= 5 and total_score >= 12:
            grade = "A"
            advice = self._build_advice("A")
        elif passed >= 4 and total_score >= 9:
            grade = "B"
            advice = self._build_advice("B")
        elif passed >= 3:
            grade = "C"
            advice = self._build_advice("C")
        else:
            grade = "D"
            advice = self._build_advice("D")

        return {
            "ticker": self.ticker,
            "grade": grade,
            "passed_layers": passed,
            "total_score": total_score,
            "scores": scores,
            "advice": advice,
            "layers": self.results,
            "stage_info": self._classify_stage(),
            "stage": self._classify_stage()["stage"],
        }

    # ── L_BPS: 突破-回踩-站稳 细粒度量化 ─────────────────────────
    def layer_bps(self) -> dict:
        """
        突破-回踩-站稳 细粒度量化分析

        独立计算三个子状态的详细指标，结果注入 self.results["L_BPS"]
        供 _classify_stage() 在描述时引用具体数值

        调用时机：在 L4（信号K线）之后，因为需要 sig_bar_high 作为突破价位
        """
        # 读取 L4 信号K线信息（若尚未运行，先计算）
        if "L4" not in self.results:
            self.layer4_kline_signal()
        l4 = self.results.get("L4", {})
        sig = l4.get("signal", {})
        # sig_bar_high fallback：若L4无信号K，取近20日波段高点（不含当前K线）
        if sig.get("bar_high"):
            sig_bar_high = float(sig["bar_high"])
            sig_bar_date = sig.get("date") or self.bars[-1]["date"]
        else:
            # 近20日次高点（排除今日，避免用当前价作为突破参考）
            recent_highs = sorted(set(float(b["high"]) for b in self.bars[-21:-1]), reverse=True)
            sig_bar_high = recent_highs[0] if recent_highs else (
                float(self.bars[-2]["high"]) if len(self.bars) >= 2
                else float(self.bars[-1]["high"]) if self.bars else 0)
            # 找到该高点对应的日期
            sig_bar_date = next((b["date"] for b in self.bars[-21:-1]
                                  if abs(float(b["high"]) - sig_bar_high) < 0.01), None)

        # ── 突破分析 ─────────────────────────────────────────
        breakout = _bps_detect_breakout(self.bars, sig_bar_high, sig_bar_date)

        # ── 回踩分析 ─────────────────────────────────────────
        pullback = _bps_detect_pullback(self.bars, breakout)

        # ── 站稳分析 ─────────────────────────────────────────
        stand = _bps_detect_stand_firm(self.bars, breakout, pullback)

        result = {
            "breakout": breakout,
            "pullback": pullback,
            "stand": stand,
            "date": str(date.today()),
        }
        self.results["L_BPS"] = result
        return result

    def _classify_stage(self) -> dict:
        """
        Brooks 位置阶段分类（P05/P09/P07 核心）
        增加 L_BPS 细粒度数据引用

        Brooks 的思维：
        - 不要"找买入信号"，要理解"现在处于趋势的哪个阶段"
        - "即将上涨" = 价格正在积蓄能量，等待那个"最难被打败"的瞬间
        - 每个阶段都有明确的"确认条件"，满足才行动

        六阶段分类：
        STAGE_0_NO_SIGNAL    → 无信号，观望
        STAGE_1_PRE_SIGNAL   → 有信号K，Buy Stop未触发，等突破
        STAGE_2_SETUP_OK     → Buy Stop已触发，等回踩
        STAGE_3_PULLBACK     → 正在回调，积蓄能量的过程
        STAGE_4_READY        → 回调结束，新一轮上涨即将启动（最佳位置）
        STAGE_5_EXPOSED      → 已涨出空间，追高风险大
        STAGE_F_FAILED       → 条件不满足
        """
        l0 = self.results.get("L0", {})
        l1 = self.results.get("L1", {})
        l2 = self.results.get("L2", {})
        l3 = self.results.get("L3", {})
        l4 = self.results.get("L4", {})
        l5 = self.results.get("L5", {})
        bps = self.results.get("L_BPS", {})
        bo = bps.get("breakout", {})
        pb = bps.get("pullback", {})
        sf = bps.get("stand", {})
        rr = l5.get("details", {})
        ts = l2.get("trend", {})
        h1 = l2.get("h1", {})
        sig = l4.get("signal", {})

        current = ts.get("latest_close", 0)
        ema20 = ts.get("ema20", 0)
        ema50 = ts.get("ema50", 0)
        entry_price = rr.get("entry", current)
        stop_price = rr.get("stop_loss", entry_price * 0.97)
        sig_bar_high = float(self.bars[-1]["high"]) if self.bars else 0
        sig_bar_date = self.bars[-1]["date"] if self.bars else "?"
        l4_quality = sig.get("quality", "WEAK")
        l4_pass = l4.get("pass", False)
        l5_veto = l5.get("veto", False)
        l1_pass = l1.get("pass", False)
        buy_stop_triggered = l0.get("buy_stop_triggered", False)
        liq = l0.get("bearish_liquidation")
        form_type = l3.get("form_type", "NONE")
        h1_invalidated = h1.get("h1_invalidated", False)
        h1_date = h1.get("h1_bar", {}).get("date", "?") if h1.get("h1_bar") else "?"
        vol_ratio = sig.get("vol_ratio", 0)
        body_ratio = sig.get("candle_data", {}).get("body_ratio", 0)
        regime = l1.get("regime", "?")
        rr_ratio = rr.get("rr_ratio", 0)
        mm_swing_high = rr.get("mm_swing_high", 0)
        mm_swing_low = rr.get("mm_swing_low", 0)
        mm_range = rr.get("mm_range", 0)
        mm_target = rr.get("mm_target", 0)
        atr = rr.get("atr", 0)
        tgt_3r = rr.get("target_3r", 0)

        # ── 阶段判断 ─────────────────────────────────────────
        # STAGE 0: 无信号
        if not l4_pass and l4_quality == "NONE":
            return {
                "stage": "STAGE_0", "name": "无信号区",
                "key_level": f"现价 {current:.2f}",
                "confirm": "等待出现趋势K线 + 收在极端位",
                "brooks": "P07：信号K = 趋势K线 + 收在极端位。信号出现前不操作。",
                "action": "NO_ACTION", "color": "gray",
                "summary": f"当前无信号K，等待形态确认（收盘{current:.2f}）",
            }

        # STAGE 5: 追高风险（已涨出空间）
        if entry_price > 0 and current > entry_price * 1.03:
            pct = (current - entry_price) / entry_price * 100
            return {
                "stage": "STAGE_5", "name": "追高风险区",
                "key_level": f"已涨 {pct:.1f}%（入场价 {entry_price:.2f} → 现价 {current:.2f}）",
                "confirm": "不追高，等回调。P09：永远不追涨。",
                "brooks": "P09 Bread & Butter：强势股会中等回踩，不追是底线。",
                "action": "NO_ACTION", "color": "red",
                "summary": f"已涨出 {pct:.1f}% 空间，追入风险大，等待回踩",
            }

        # STAGE 4: 即将启动（Buy Stop已触发且价格仍在入场位上方，未回落）
        # 条件：Buy Stop已触发 + 价格仍≥入场位 + H1有效 + EMA20之上 + 未追高
        buy_stop_price = rr.get("entry", current)  # Buy Stop 触发价
        in_entry_zone = current >= buy_stop_price
        if (buy_stop_triggered and in_entry_zone
                and h1.get("has_h1") and not h1_invalidated
                and ts.get("above_ema20") and not l5_veto
                and not (entry_price > 0 and current > entry_price * 1.03)):
            h1_low = float(h1["h1_bar"]["low"])
            in_pos = current >= buy_stop_price
            confirm_txt = (
                f"若 {current:.2f} ≥ {buy_stop_price:.2f}（Buy Stop触发位）→ "
                f"{"已入场" if in_pos else "等待突破"}，"
                f"止损 {stop_price:.2f}，目标 {mm_target:.2f}（RR={rr_ratio:.1f}:1）"
            )
            # ── BPS 站稳量化 ─────────────────────────────────────────
            bps_lines = []
            if bo.get("type"):
                bps_lines.append(f"突破:{bo['type']}@{bo['price']}({bo['date']})"
                                 f" 量={bo['vol_ratio']}x" if bo.get("vol_ratio") else "")
            if pb.get("type"):
                bps_lines.append(f"回踩:{pb['type']}→{pb['support_name']}"
                                 f" 跌深{pb['pullback_pct']:.1f}%"
                                 f" 跌破概率:{pb['break_prob']}")
            if sf.get("h1_found"):
                sf_detail = (f"站稳✅ H1({sf['h1_date']})|量比={sf['volume_ratio']}"
                             f" 深度={sf['max_pullback_pct']:.1f}%"
                             f" 历时={sf['duration_bars']}根" if sf.get("duration_bars") else "")
                bps_lines.append(sf_detail)

            return {
                "stage": "STAGE_4", "name": "即将启动 🎯",
                "key_level": (f"H1低点={h1_low:.2f} | Buy Stop={buy_stop_price:.2f} | "
                               f"止损={stop_price:.2f} | 目标={mm_target:.2f}(MM)"),
                "confirm": confirm_txt,
                "bps_breakout": bo,
                "bps_pullback": pb,
                "bps_stand": sf,
                "bps_summary": " | ".join(bps_lines) if bps_lines else "BPS数据待计算",
                "brooks": "P05 H1 = 回调后第一根突破前高的阳线，Brooks：回调结束后第一个H1是最强信号。",
                "action": "NOW" if in_pos else "WATCH",
                "color": "green",
                "summary": (f"H1信号（{h1_date}）刚形成，多头重新掌控。"
                            f"MM目标={mm_target:.2f}（A={mm_swing_high:.2f}→B={mm_swing_low:.2f}，高={mm_range:.2f}）。"),
            }

        # STAGE 3: 回调整理中（Buy Stop已触发，价格已从入场位回落）
        if buy_stop_triggered and l4_pass and not l5_veto:
            drop_pct = (entry_price - current) / entry_price * 100
            # ── BPS 回踩量化 ──────────────────────────────────────
            pb_detail = ""
            if pb.get("type", "NONE") != "NONE":
                break_danger = "🔴" if pb.get("break_prob") == "HIGH" else (
                               "🟡" if pb.get("break_prob") == "MEDIUM" else "🟢")
                pb_detail = (
                    f"回踩类型:{pb['type']} | 支撑={pb['support_name']} | "
                    f"跌深={pb['pullback_pct']:.1f}% | "
                    f"跌破概率:{break_danger}{pb['break_prob']}"
                    f"（距下个支撑{pb['distance_to_break_pct']:.1f}%）"
                )
            else:
                pb_detail = f"当前跌幅={drop_pct:.1f}%，等待回踩确认"

            return {
                "stage": "STAGE_3", "name": "回调整理中",
                "key_level": (f"EMA20={ema20:.2f} | 入场位={entry_price:.2f} | "
                               f"现价={current:.2f}（已回落{drop_pct:.1f}%）"),
                "confirm": (f"等待回调结束信号：1) 价格不再创新低 2) 出现新H1 → STAGE_4\n"
                            f"  {pb_detail}"),
                "bps_breakout": bo,
                "bps_pullback": pb,
                "bps_stand": sf,
                "bps_summary": pb_detail,
                "brooks": "P09 Bread & Butter：强势股回踩EMA20/趋势线时等待企稳。不预测何时结束。",
                "action": "WATCH",
                "color": "yellow",
                "summary": (f"Buy Stop {entry_price:.2f} 曾触发后回落 {drop_pct:.1f}%，"
                            f"现处于回调积蓄中。L3形态={form_type}，等待结束信号。"),
            }

        # STAGE 2: 入场位已确认（Buy Stop 触发），等待回踩
        # 价格已站上信号K高点，等待第一次回踩（Bread & Butter）
        if buy_stop_triggered and l4_pass and not l5_veto:
            # ── BPS 突破量化 ──────────────────────────────────────
            bo_detail = ""
            if bo.get("type"):
                bo_detail = (
                    f"突破类型:{bo['type']} | 突破价={bo['price']}({bo['date']}) | "
                    f"突破量比={bo['vol_ratio']}x20日均量"
                    if bo.get("vol_ratio") else
                    f"突破类型:{bo['type']} | 突破价={bo['price']}({bo['date']})"
                )

            return {
                "stage": "STAGE_2", "name": "入场位确认",
                "key_level": f"Buy Stop触发位={entry_price:.2f}（信号K高点{sig_bar_high:.2f}）",
                "confirm": (f"等回踩到EMA20({ema20:.2f})附近出现企稳K线 → Bread & Butter 买入机会\n"
                             f"  {bo_detail}"),
                "bps_breakout": bo,
                "bps_pullback": pb,
                "bps_stand": sf,
                "bps_summary": bo_detail,
                "brooks": "P09：强势股回踩EMA20是最佳买入机会，Brooks叫它Bread & Butter set-up。",
                "action": "WATCH",
                "color": "blue",
                "summary": (f"价格已站上信号K高点 {entry_price:.2f}，等待回踩。"
                            f"一旦回踩EMA20附近企稳 → 将是Bread & Butter买入机会。"),
            }

        # STAGE 1: 信号K存在，Buy Stop 未触发（最佳观察位）
        # 方向明确，蓄势待发，这是"即将上涨"最典型的前兆
        if l4_pass and not buy_stop_triggered and not l5_veto:
            buy_stop_price = sig_bar_high + 0.01   # Buy Stop 挂单价格
            gap = buy_stop_price - current
            gap_pct = gap / current * 100
            # ── BPS 突破量化 ──────────────────────────────────────
            bo_detail = ""
            if bo.get("type"):
                bo_detail = (
                    f"当前突破类型:{bo['type']} | 目标位={bo['price']} | "
                    f"放量={bo['vol_ratio']}x" if bo.get("vol_ratio") else
                    f"当前突破类型:{bo['type']} | 目标位={bo['price']}"
                )

            return {
                "stage": "STAGE_1", "name": "信号蓄势 ⏳",
                "key_level": (f"信号K高点={sig_bar_high:.2f}（{sig_bar_date}）| "
                               f"Buy Stop挂单={buy_stop_price:.2f} | "
                               f"现价={current:.2f}（还差{gap:.2f}/{gap_pct:.1f}%）"),
                "confirm": (f"当 {current:.2f} ≥ {buy_stop_price:.2f} → Buy Stop触发，"
                           f"观察是否出现回踩（STAGE_2→STAGE_3→STAGE_4）\n"
                           f"  {bo_detail}"),
                "bps_breakout": bo,
                "bps_pullback": pb,
                "bps_stand": sf,
                "bps_summary": bo_detail,
                "brooks": "P07：信号K出现后，挂Buy Stop在信号K高点上方1 tick。"
                           "Brooks：这种突破后回调的set-up是最佳机会。",
                "action": "WATCH",
                "color": "cyan",
                "summary": (f"信号K（{sig_bar_date}）实体{body_ratio:.0%}已确认，质量={l4_quality}，量能={vol_ratio}x。"
                            f"挂{buy_stop_price:.2f} Buy Stop，等待突破。这是\"即将上涨\"的前兆。"),
            }

        # STAGE FAILED
        blockers = []
        if l5_veto: blockers.append("盈亏比不足")
        if liq: blockers.append("流动性猎杀进行中")
        if not l1_pass: blockers.append(f"大盘{regime}")
        return {
            "stage": "STAGE_F", "name": "暂不符合",
            "key_level": f"现价 {current:.2f}",
            "confirm": "等待障碍消除：" + ", ".join(blockers) if blockers else "—",
            "brooks": "Brooks：一票否决的情况不下单。保护本金优先。",
            "action": "NO_ACTION", "color": "gray",
            "summary": "当前不符合入场条件。" + ", ".join(blockers) if blockers else "需更多条件确认。",
        }

    def _build_advice(self, grade: str) -> str:
        """
        完全重写：用 Brooks 位置阶段分析替代简单的 ABC 评级
        不说"买"，而是描述"现在处于哪个阶段，下一步需要什么"
        """
        stage_info = self._classify_stage()
        l0 = self.results.get("L0", {})
        l1 = self.results.get("L1", {})
        l2 = self.results.get("L2", {})
        l3 = self.results.get("L3", {})
        l4 = self.results.get("L4", {})
        l5 = self.results.get("L5", {})
        rr = l5.get("details", {})
        ts = l2.get("trend", {})
        sig = l4.get("signal", {})
        h1 = l2.get("h1", {})

        stage = stage_info["stage"]
        stage_icon = {
            "STAGE_0": "⚪", "STAGE_1": "🔵", "STAGE_2": "🟢",
            "STAGE_3": "🟡", "STAGE_4": "🟠", "STAGE_5": "🔴",
            "STAGE_F": "⚫",
        }
        icon = stage_icon.get(stage, "⚪")
        current = ts.get("latest_close", 0)
        ema20 = ts.get("ema20", 0)
        ema50 = ts.get("ema50", 0)
        regime = l1.get("regime", "?")
        vol_ratio = sig.get("vol_ratio", 0)
        rr_ratio = rr.get("rr_ratio", 0)
        tgt_3r = rr.get("target_3r", 0)
        atr = rr.get("atr", 0)
        mm_target = rr.get("mm_target", 0)
        entry = rr.get("entry", current)
        stop = rr.get("stop_loss", entry * 0.97)

        # 1h 信息行
        l0_line = ""
        if l0.get("has_1h_data"):
            liq = l0.get("bearish_liquidation")
            l0_line = (
                f"  1h EMA20={l0.get('ema20_1h')} / EMA50={l0.get('ema50_1h')} | "
                f"1h收盘={l0.get('last_close_1h')}"
                f"{'↑' if l0.get('price_vs_ema20_1h') else '↓'} | "
                f"BuyStop={'✅已触发' if l0.get('buy_stop_triggered') else '⏸️未触发'} | "
                f"流动性={'⚠️猎杀' if liq else '✅正常'}"
            )

        lines = [
            f"{icon} {stage_info['name']}  [{stage}]",
            f"",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📍 关键价位",
            f"  {stage_info['key_level']}",
            f"",
            f"✅ 确认条件（满足才行动）",
            f"  {stage_info['confirm']}",
            f"",
            f"📐 风险参数（参考）",
            f"  入场参考={entry:.2f} | 止损={stop:.2f}（ATR={atr:.2f}）| "
            f"MM目标={mm_target:.2f} | 目标3R={tgt_3r:.2f}",
            f"  盈亏比: {rr_ratio:.1f}:1",
            f"",
            f"📌 Brooks 操作原则",
            f"  {stage_info['brooks']}",
            f"",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📊 五层状态速览",
            f"  L1大盘: {'✅ ' + regime if l1.get('pass') else '❌ ' + regime}",
            f"  L2趋势: {l2.get('reason', '')[:90]}",
            f"  L3形态: {l3.get('form_type', '-')} {l3.get('reason', '')[:60]}",
            f"  L4信号: {sig.get('quality', '?')} | 量={vol_ratio}x | "
            f"实体={sig.get('candle_data', {}).get('body_ratio', 0):.0%}",
            f"  L5风控: RR={rr_ratio:.1f}:1 {'✅' if not l5.get('veto') else '❌ 一票否决'}",
            l0_line,
            f"",
            f"💡 {stage_info['summary']}",
        ]
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# 输出格式化
# ═══════════════════════════════════════════════════════════════════

def print_report(r: dict):
    """Brooks 风格报告：输出位置阶段 + 确认条件"""
    stage_info = r.get("stage_info", {})
    stage = stage_info.get("stage", "?")
    stage_icon = {
        "STAGE_0": "⚪", "STAGE_1": "🔵", "STAGE_2": "🟢",
        "STAGE_3": "🟡", "STAGE_4": "🟠", "STAGE_5": "🔴",
        "STAGE_F": "⚫",
    }
    icon = stage_icon.get(stage, "⚪")
    g = r["grade"]
    grade_icon = {"A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴", "F": "🚫"}
    gicon = grade_icon.get(g, "⚪")

    print(f"\n{'='*62}")
    print(f"  {icon} {r['ticker']} — {stage_info.get('name','?')} | "
          f"Brooks级:{g} | 总分:{r['total_score']}")
    print(f"{'='*62}")
    print(r["advice"])
    print(f"{'='*62}\n")



STAGE_PRIORITY = {
    "STAGE_4": 0,   # 即将启动 — 最佳
    "STAGE_2": 1,   # 入场位确认
    "STAGE_3": 2,   # 回调整理中
    "STAGE_1": 3,   # 信号蓄势
    "STAGE_0": 4,   # 无信号
    "STAGE_5": 5,   # 追高风险
    "STAGE_F": 6,   # 失败
}

def scan_pool(tickers: list, spy_bars: list, top_n: int = 20,
             with_intraday: bool = True) -> list:
    """
    扫描股票池，返回按Brooks阶段优先级排序的候选列表

    排序逻辑：STAGE_4（即将启动）> STAGE_2（入场位确认）> STAGE_3（回调整理）
             > STAGE_1（信号蓄势）> 其他
    排除：STAGE_F（条件不满足）、STAGE_5（追高风险）
    """
    results = []
    for t in tickers:
        bars = load_klines(t, lookback=120)  # 日线最多120根
        if not bars:
            continue
        # 计算日线入场价（信号K高点 + 0.01）
        sig = detect_signal_bar(bars)
        daily_entry = None
        if sig.get("quality", "NONE") != "NONE":
            sig_high = float(bars[-1]["high"])
            daily_entry = sig_high + 0.01
        # 加载1h数据
        bars_1h = None
        if with_intraday:
            bars_1h = load_1h_klines(t, lookback=80)
        eng = BuyFilterEngine(t, bars, spy_bars)
        r = eng.run(bars_1h=bars_1h, daily_entry_price=daily_entry)
        results.append(r)

    # 排除 STAGE_F 和 STAGE_5
    filtered = [r for r in results if r["stage"] not in ("STAGE_F", "STAGE_5")]

    def sort_key(r):
        stage_prio = STAGE_PRIORITY.get(r["stage"], 99)
        score = r["total_score"]
        return (stage_prio, -score)

    filtered.sort(key=sort_key)
    return filtered[:top_n]


# ═══════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Brooks 五层买入过滤系统")
    parser.add_argument("ticker", nargs="?", help="股票代码，如 AAPL")
    parser.add_argument("--all", action="store_true", help="扫描全股票池")
    parser.add_argument("--top", type=int, default=10, help="输出前N名")
    parser.add_argument("--spy", default="SPY", help="大盘基准代码")
    args = parser.parse_args()

    spy_bars = load_klines(args.spy)

    if args.all:
        # 加载股票池
        pool_file = BASE / "TradingAgents" / "fintech" / "stock_pool.json"
        with open(pool_file) as f:
            pool = json.load(f)
        tickers = [s["code"] for s in pool["stocks"] if s["code"] != args.spy]
        print(f"🔍 扫描 {len(tickers)} 只股票...")
        top = scan_pool(tickers, spy_bars, args.top)
        print(f"\n{'='*60}")
        print(f"  🏆 TOP {len(top)} 买入候选")
        print(f"{'='*60}")
        for i, r in enumerate(top, 1):
            g = r["grade"]
            icon = {"A": "🟢", "B": "🟡", "C": "🟠"}.get(g, "⚪")
            print(f"  {i}. {icon} {r['ticker']} | {g} | {r['passed_layers']}/5 | 分数:{r['total_score']}")
            print(f"      {r['advice'].strip()}")
        print(f"{'='*60}\n")
    elif args.ticker:
        bars = load_klines(args.ticker, lookback=120)
        if not bars:
            print(f"❌ 未找到 {args.ticker} 的数据")
            sys.exit(1)
        # 加载1h数据（最多80根）
        bars_1h = load_1h_klines(args.ticker, lookback=80)
        # 计算日线入场价（当日信号K高点 + 0.01）
        from p_buy_filter import detect_signal_bar
        sig = detect_signal_bar(bars)
        daily_entry = float(bars[-1]["high"]) + 0.01 if sig.get("quality", "NONE") != "NONE" else None
        eng = BuyFilterEngine(args.ticker, bars, spy_bars)
        r = eng.run(bars_1h=bars_1h, daily_entry_price=daily_entry)
        print_report(r)
    else:
        parser.print_help()
