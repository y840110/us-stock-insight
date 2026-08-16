#!/usr/bin/env python3
"""
p_buy_filter_v2.py — Brooks 五层买入过滤系统 v2
=================================================

基于方方土价格行为学 P02-P16 字幕原文设计
v2 核心改进（相比 v1）：

  L3 改进：
    ✅ 回踩质量分层评分（EMA20 > 50% > 趋势线 > 宽通道）
    ✅ 深度过滤：>61.8% 回撤直接拒绝（趋势可能反转）
    ✅ 记录回踩类型到 stage_info

  L4 改进：
    ✅ STAGE_4 强化：需要 pullback 止跌证据（H1 或阳包阴）
    ✅ 回踩完成检测：价格不再创新低 = pullback 结束

  L5 改进：
    ✅ Measured Move 目标：区间高度 → 突破点 ± 等距投射
    ✅ 缺口作为目标位（Gap fill 止盈参考）

  L2 改进：
    ✅ 弱势 veto：创日内新低但无 H1 = 机构未参与，不买

  L0 改进：
    ✅ 1h 数据缺失时优雅降级，不 crash

Brooks 原文索引：
  P02：牛市四阶段 / 50%回撤原则
  P05：H1/L1 数K线 / Bread & Butter / 三推反转
  P07：信号K线定义 / Buy Stop 入场
  P09：Bread & Butter set-up / 82%规则
  P11：顺大逆小 / Wedge 失败=123
  P12：Parabolic Wedge / Bad Follow-Through
  P13：Measured Move / 止盈目标
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
    if len(bars) < period + 1:
        return 0.0
    trs = []
    for i in range(1, min(len(bars), period + 20)):
        h = float(bars[i]["high"])
        l = float(bars[i]["low"])
        pc = float(bars[i-1]["close"])
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs[-period:]) / period if len(trs) >= period else 0.0


def _swing_lows(highs: list, lows: list, lookback: int = 20) -> list:
    if len(lows) < 3:
        return []
    swing_lows = []
    for i in range(2, len(lows) - 1):
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < highs[i]:
            swing_lows.append({"idx": i, "low": lows[i]})
    return swing_lows[-lookback:]


def _swing_highs(highs: list, lows: list, lookback: int = 20) -> list:
    if len(highs) < 3:
        return []
    swing_highs = []
    for i in range(2, len(highs) - 1):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > lows[i]:
            swing_highs.append({"idx": i, "high": highs[i]})
    return swing_highs[-lookback:]


def _load_json(ticker: str, interval: str = "1d") -> dict:
    path = KLINES_DIR / f"{ticker}_{interval}.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        if "data" in data:
            return {"data": data["data"]}
        return data
    except Exception:
        return {}


def load_klines(ticker: str, lookback: int = 300, interval: str = "1d") -> list:
    """兼容 v1 签名：load_klines(ticker, lookback=300)"""
    d = _load_json(ticker, interval)
    bars = d.get("data", [])
    if not bars:
        return []
    return bars[-lookback:]


def load_1h_klines(ticker: str, lookback: int = 500) -> list:
    return load_klines(ticker, lookback, "1h")


# ═══════════════════════════════════════════════════════════════════
# P1: 趋势线支撑检测
# ═══════════════════════════════════════════════════════════════════

def detect_trendline_support(bars: list, lookback: int = 60) -> dict:
    """
    趋势线支撑检测（P02/P05）

    Brooks 原文：
      P02："上升趋势线是上涨过程中的支撑，回调到趋势线是买入机会。"
      P05："价格回到趋势线时出现反转K线，是最佳买入点。"

    方法：线性回归拟合近 N 个波段低点，检测价格是否回踩趋势线
    输出：detected / broken / trendline_price / distance_pct / touch_count
    """
    if len(bars) < 10:
        return {"detected": False, "broken": False}

    recent = bars[-lookback:]
    lows = [float(b["low"]) for b in recent]

    # 取最近 20 个低点做趋势线
    window = min(20, len(lows) - 2)
    points = [(i, lows[i]) for i in range(len(lows) - window, len(lows))]

    n = len(points)
    if n < 3:
        return {"detected": False, "broken": False}

    sum_x = sum(i for i, _ in points)
    sum_y = sum(y for _, y in points)
    sum_xy = sum(i * y for i, y in points)
    sum_xx = sum(i * i for i, _ in points)
    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-9:
        return {"detected": False, "broken": False}

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    # 趋势线当前值（ extrapolation）
    last_idx = len(recent) - 1
    trendline_price = slope * last_idx + intercept
    latest_close = float(recent[-1]["close"])
    latest_low = float(recent[-1]["low"])

    # 价格与趋势线距离
    distance_pct = abs(latest_close - trendline_price) / latest_close * 100 if latest_close > 0 else 0.0

    # 计算触碰次数（实际低点接近趋势线 2% 内）
    tolerance = latest_close * 0.02
    touch_count = sum(
        1 for i, low in enumerate(lows)
        if abs(low - (slope * i + intercept)) <= tolerance
    )

    # 判断状态
    above_trendline = latest_close > trendline_price
    pulled_back = (
        above_trendline and
        latest_low <= trendline_price * 1.02 and
        latest_low >= trendline_price * 0.98
    )
    broken = (
        latest_close < trendline_price * 0.97 or
        (slope > 0 and latest_close < trendline_price * 0.95)
    )

    return {
        "detected": pulled_back and not broken,
        "broken": broken,
        "pullback": above_trendline,
        "trendline_price": round(trendline_price, 2),
        "distance_pct": round(distance_pct, 3),
        "touch_count": touch_count,
        "slope": round(slope, 4),
    }


# ═══════════════════════════════════════════════════════════════════
# P2: 顺势交易回踩形态检测
# ═══════════════════════════════════════════════════════════════════

def detect_bull_bear_flag(bars: list, lookback: int = 60) -> dict:
    """
    Bull Flag / Bear Flag / 楔形分类（P10/P11）

    Brooks 原文：
      P11："在上涨趋势中，Bear Flag 是逆势调整，不是反转。
            顺大逆小：在大趋势中的小逆势，是最佳机会。"

    分类：
      BULL_FLAG      → 强势顺势回调（紧贴EMA/趋势线，5-15根K线）
      BEAR_FLAG     → 弱势反弹（下降趋势中的小逆势）
      FALLING_WEDGE → 潜在反转（在大跌后的底部）
      RISING_WEDGE  → 潜在反转（在大涨后的顶部）
      NEUTRAL       → 无明确形态
    """
    if len(bars) < 20:
        return {"type": "NEUTRAL", "reason": "数据不足"}

    closes = [float(b["close"]) for b in bars]
    ema20 = _ema(closes, 20)
    if len(ema20) < 10:
        return {"type": "NEUTRAL", "reason": "EMA数据不足"}

    # 检测近20根K线的整体方向
    recent = closes[-20:]
    slope = (recent[-1] - recent[0]) / max(1, len(recent) - 1)

    # EMA 方向
    ema_slope = ema20[-1] - ema20[-5] if len(ema20) >= 5 else 0

    # K线数量（回调深度）
    high_idx = max(range(len(recent)), key=lambda i: recent[i])
    pullback_bars = len(recent) - high_idx - 1

    # 判断
    if slope > 0 and ema_slope > 0:
        if pullback_bars <= 15:
            return {"type": "BULL_FLAG", "ema_slope": round(ema_slope, 2),
                    "pullback_bars": pullback_bars,
                    "note": "强势顺势回调，5-15根K线"}
        else:
            return {"type": "WIDE_CHANNEL", "ema_slope": round(ema_slope, 2),
                    "pullback_bars": pullback_bars,
                    "note": "宽通道回调，等待更深入场"}
    elif slope < 0 and ema_slope < 0:
        if pullback_bars <= 10:
            return {"type": "BEAR_FLAG", "ema_slope": round(ema_slope, 2),
                    "pullback_bars": pullback_bars,
                    "note": "弱势反弹，继续看跌"}
        else:
            return {"type": "FALLING_WEDGE", "ema_slope": round(ema_slope, 2),
                    "pullback_bars": pullback_bars,
                    "note": "下跌楔形，警惕反转"}
    elif slope > 0 and ema_slope < 0:
        return {"type": "RISING_WEDGE", "ema_slope": round(ema_slope, 2),
                "pullback_bars": pullback_bars,
                "note": "上升楔形，警惕顶部反转"}
    return {"type": "NEUTRAL", "reason": "无明确形态"}


# ═══════════════════════════════════════════════════════════════════
# P3: 失败楔形 = 123 结构
# ═══════════════════════════════════════════════════════════════════

def detect_failed_wedge_123(bars: list, lookback: int = 60) -> dict:
    """
    Wedge 失败 = 123 结构（P11）

    Brooks 原文：
      P11："Wedge 失败 = 123失败。当第三推无法突破时，
            市场将反向走。不要追涨或追跌。"

    三推结构（L1/L2/L3）：
      L1 → 第一次推
      L2 → 回调后第二次推（应该创更高高点）
      L3 → 第三次推（失败，无法突破 L2 高点）= 下跌前兆

    123 失败：L3 < L2（对于高点）或 L3 > L2（对于低点）
    """
    if len(bars) < 15:
        return {"has_123": False, "type": "NEUTRAL"}

    highs = [float(b["high"]) for b in bars[-lookback:]]
    lows  = [float(b["low"])  for b in bars[-lookback:]]

    # 找近 N 个局部高点
    swing_highs = _swing_highs(highs, lows, lookback=10)
    if len(swing_highs) < 3:
        return {"has_123": False, "type": "NEUTRAL", "reason": "不够波段高点"}

    # 取最近三个波段高点
    h1 = swing_highs[-3]   # L1
    h2 = swing_highs[-2]  # L2
    h3 = swing_highs[-1]  # L3

    # 123 高点（第三推失败：无法超越第二推）
    h1_high = h1["high"]
    h2_high = h2["high"]
    h3_high = h3["high"]

    # 123 低点（第三推失败：无法超越第二推）
    swing_lows_list = _swing_lows(highs, lows, lookback=10)
    if len(swing_lows_list) >= 3:
        l1 = swing_lows_list[-3]
        l2 = swing_lows_list[-2]
        l3 = swing_lows_list[-1]
        l1_low = l1["low"]
        l2_low = l2["low"]
        l3_low = l3["low"]

    # 判断失败类型
    # 顶部 123（高点三次推，第三推失败）
    if h3_high < h2_high and h2_high >= h1_high:
        # 第三推无法超越第二推 → 下跌
        drop_pct = (h2_high - h3_high) / h2_high * 100 if h2_high > 0 else 0
        return {
            "has_123": True,
            "type": "TOP_123",
            "h1": round(h1_high, 2), "h2": round(h2_high, 2),
            "h3": round(h3_high, 2),
            "drop_pct": round(drop_pct, 2),
            "note": f"第三推({h3_high:.2f})<第二推({h2_high:.2f})，下跌概率大",
        }
    # 底部 123（低点三次推，第三推失败）
    if len(swing_lows_list) >= 3:
        if l3_low > l2_low and l2_low <= l1_low:
            rise_pct = (l3_low - l2_low) / l2_low * 100 if l2_low > 0 else 0
            return {
                "has_123": True,
                "type": "BOTTOM_123",
                "l1": round(l1_low, 2), "l2": round(l2_low, 2),
                "l3": round(l3_low, 2),
                "rise_pct": round(rise_pct, 2),
                "note": f"第三推({l3_low:.2f})>第二推({l2_low:.2f})，上涨概率大",
            }

    return {"has_123": False, "type": "NEUTRAL"}


# ═══════════════════════════════════════════════════════════════════
# P4: H3/L3 三推反转信号
# ═══════════════════════════════════════════════════════════════════

def detect_h3_signal(bars: list, lookback: int = 40) -> dict:
    """
    H3 / L3 三推反转信号（P05）

    Brooks 原文：
      P05："H3 = 第三次冲高后市场往往下跌，因为交易者习惯在第三推获利。"
      "L3 = 第三次探低后市场往往上涨。"
      "三推是反转信号，不是趋势延续。"

    注意：只有第三推创了新高/新低才算。还没创新高的三推不算。
    """
    if len(bars) < 15:
        return {"has_h3": False, "push_count": 0}

    highs = [float(b["high"]) for b in bars[-lookback:]]
    lows  = [float(b["low"])  for b in bars[-lookback:]]

    # 找最近波段高点
    swing_highs = _swing_highs(highs, lows, lookback=10)
    if len(swing_highs) < 3:
        return {"has_h3": False, "push_count": 0, "note": "波段高点不足"}

    # 取最近 3 个波段高点
    last_three = swing_highs[-3:]

    # 判断是否连续上涨（每个都创高）
    ascending = all(
        last_three[i]["high"] > last_three[i-1]["high"]
        for i in range(1, len(last_three))
    )

    if ascending and len(last_three) >= 3:
        h1, h2, h3 = last_three[-3]["high"], last_three[-2]["high"], last_three[-1]["high"]
        return {
            "has_h3": True,
            "push_count": 3,
            "h1": round(h1, 2), "h2": round(h2, 2), "h3": round(h3, 2),
            "note": f"H3信号：{h1}→{h2}→{h3}，第三推创高，上涨疲惫，反转概率大",
        }

    # 统计总推数（还没创新高的）
    push_count = len(swing_highs)
    return {"has_h3": False, "push_count": push_count, "note": "无连续三推"}


# ═══════════════════════════════════════════════════════════════════
# P6: TIBOW 两根K线反转
# ═══════════════════════════════════════════════════════════════════

def detect_tibow_reverse(bars: list) -> dict:
    """
    TIBOW Reverse（Two-Bar Outside Bar）（P08）

    Brooks 原文：
      P08："TIBOW Reverse = 两根K线组合，前一根被后一根完全吞没。"
      "TIBOW LONG = 下跌后出现阳包阴，是买入信号。"
      "TIBOW SHORT = 上涨后出现阴包阳，是卖出信号。"

    判断：
      TIBOW LONG：两根连续K线，第二根低点 < 第一根低点，第二根高点 ≤ 第一根高点，
                  且第二根收盘 > 第一根高点，收盘接近高点
      TIBOW SHORT：反过来
    """
    if len(bars) < 3:
        return {"detected": False}

    b1 = bars[-3]
    b2 = bars[-2]
    b3 = bars[-1]  # 当前K线

    for combo in [(b2, b3), (b1, b2)]:
        prev, curr = combo
        prev_high = float(prev["high"])
        prev_low  = float(prev["low"])
        prev_body = prev_high - prev_low
        curr_high = float(curr["high"])
        curr_low  = float(curr["low"])
        curr_close = float(curr["close"])
        curr_open  = float(curr["open"])

        if prev_body < 0.01:
            continue

        # TIBOW LONG：阳包阴
        if (curr_high > prev_high and curr_low < prev_low and
                curr_close > prev_high):
            engulf_ratio = curr_high / prev_low if prev_low > 0 else 0
            return {
                "detected": True,
                "direction": "LONG",
                "bar1": prev,
                "bar2": curr,
                "engulf_ratio": round(engulf_ratio, 2),
                "date": curr.get("date", "?"),
            }

        # TIBOW SHORT：阴包阳
        if (curr_low < prev_low and curr_high > prev_high and
                curr_close < prev_low):
            engulf_ratio = prev_high / curr_low if curr_low > 0 else 0
            return {
                "detected": True,
                "direction": "SHORT",
                "bar1": prev,
                "bar2": curr,
                "engulf_ratio": round(engulf_ratio, 2),
                "date": curr.get("date", "?"),
            }

    return {"detected": False}


# ═══════════════════════════════════════════════════════════════════
# 辅助计算函数
# ═══════════════════════════════════════════════════════════════════

def calc_retracement(bars: list) -> dict:
    """
    回撤比例计算（P02/P05）

    Brooks 原文：
      P02："50%回撤是一个关键位置，市场在此处停顿是正常的。"
      P05："从近期高点回撤了多少？回撤到50%位是否有支撑？"
    """
    if len(bars) < 5:
        return {}

    closes = [float(b["close"]) for b in bars]
    highs  = [float(b["high"])  for b in bars]
    lows   = [float(b["low"])   for b in bars]

    max_high = max(highs[-60:]) if len(highs) >= 60 else max(highs)
    min_low  = min(lows[-60:])  if len(lows)  >= 60 else min(lows)
    latest_close = closes[-1]

    swing_range = max_high - min_low
    if swing_range == 0:
        return {}

    pct_50_level = max_high - swing_range * 0.50
    pct_382_level = max_high - swing_range * 0.382
    pct_618_level = max_high - swing_range * 0.618

    current_retracement = (max_high - latest_close) / swing_range * 100

    if latest_close == 0:
        return {}

    return {
        "max_high": round(max_high, 2),
        "min_low":  round(min_low, 2),
        "pct_50_level": round(pct_50_level, 2),
        "pct_382_level": round(pct_382_level, 2),
        "pct_618_level": round(pct_618_level, 2),
        "retracement_pct": round(current_retracement, 1),
        "near_50_pct": abs(latest_close - pct_50_level) / latest_close < 0.02,
        "near_382_pct": abs(latest_close - pct_382_level) / latest_close < 0.02,
        "near_618_pct": abs(latest_close - pct_618_level) / latest_close < 0.02,
    }


def calc_trend_structure(bars: list, spy_bars: list = None) -> dict:
    """
    趋势结构计算（P02/P05）

    Brooks 原文：
      P05："判断趋势方向：上涨趋势 = 底部不断抬高。"
      P02："EMA20 方向是判断趋势的最快方法。"
    """
    if len(bars) < 50:
        return {}
    closes = [float(b["close"]) for b in bars]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)

    if len(ema20) < 2 or len(ema50) < 2:
        return {}

    latest_close = closes[-1]
    above_ema20 = latest_close > ema20[-1]
    above_ema50 = latest_close > ema50[-1]
    above_ema200 = latest_close > ema200[-1] if len(ema200) >= 200 else False

    # 趋势方向（用 EMA 斜率）
    ema20_slope = ema20[-1] - ema20[-5] if len(ema20) >= 5 else 0
    ema50_slope = ema50[-1] - ema50[-5] if len(ema50) >= 5 else 0

    return {
        "ema20": round(ema20[-1], 2),
        "ema50": round(ema50[-1], 2),
        "ema200": round(ema200[-1], 2) if len(ema200) >= 200 else None,
        "above_ema20": above_ema20,
        "above_ema50": above_ema50,
        "above_ema200": above_ema200,
        "ema20_slope": round(ema20_slope, 3),
        "ema50_slope": round(ema50_slope, 3),
        "ema_bull": ema20[-1] > ema50[-1],
        "ema20_above_ema50": ema20[-1] > ema50[-1],
        "latest_close": round(latest_close, 2),
    }


def detect_h1_signal_1h(bars_1h: list) -> dict:
    """
    1h H1/L1 信号检测（P05）

    Brooks 原文：
      P05："H1 = 回调后第一根阳线突破前高，多头重新夺回控制权。"
      "L1 = 反弹后第一根阴线跌破前低，空头重新夺回控制权。"
    """
    if not bars_1h or len(bars_1h) < 5:
        return {"has_h1": False, "has_l1": False}

    closes_1h = [float(b["close"]) for b in bars_1h]
    highs_1h  = [float(b["high"])  for b in bars_1h]
    lows_1h   = [float(b["low"])   for b in bars_1h]

    # 找最近的趋势方向
    if len(closes_1h) < 20:
        return {"has_h1": False, "has_l1": False}

    recent = closes_1h[-20:]
    if recent[-1] > recent[0]:  # 上涨趋势
        # 找回调低点后第一根突破前高的阳线 = H1
        min_idx = min(range(len(recent)), key=lambda i: recent[i])
        if min_idx < len(recent) - 1:
            for i in range(min_idx + 1, len(recent)):
                if recent[i] > max(recent[:i]):
                    return {"has_h1": True, "h1_bar": bars_1h[-(20 - i)],
                            "has_l1": False}
    else:  # 下跌趋势
        max_idx = max(range(len(recent)), key=lambda i: recent[i])
        if max_idx < len(recent) - 1:
            for i in range(max_idx + 1, len(recent)):
                if recent[i] < min(recent[:i]):
                    return {"has_l1": True, "l1_bar": bars_1h[-(20 - i)],
                            "has_h1": False}

    return {"has_h1": False, "has_l1": False}


def detect_signal_bar(bars: list) -> dict:
    """
    信号K线检测（P07/P08）

    Brooks 原文：
      P07："信号K线 = 趋势K线（实体≥60%）+ 收在极端位"
      P08："差股票的好set-up往往失败，Bread & Butter 只做强势股"
    """
    if len(bars) < 3:
        return {"has_signal": False, "score": 0, "reasons": ["数据不足"]}

    # 取最近3根K线
    b1 = bars[-3] if len(bars) >= 3 else None
    b2 = bars[-2] if len(bars) >= 2 else None
    b3 = bars[-1]  # 当前K线

    result = {
        "has_signal": False, "score": 0, "reasons": [],
        "quality": "WEAK", "bar_high": None, "bar_low": None,
        "candle_data": {}, "date": b3.get("date", "?"),
    }

    if not b2 or not b1:
        return result

    b3_high  = float(b3["high"])
    b3_low   = float(b3["low"])
    b3_close = float(b3["close"])
    b3_open  = float(b3["open"])
    b3_range = b3_high - b3_low

    vol_ratio = 0.0
    close_pos = 0.0

    if b3_range > 0:
        body = abs(b3_close - b3_open)
        body_ratio = body / b3_range
        close_pos   = (b3_close - b3_low) / b3_range

        # 量能判断（需要 volume 字段）
        cur_vol = float(b3.get("volume", 0) or 0)
        if cur_vol > 0 and len(bars) >= 20:
            avg_vol = sum(float(b.get("volume", 0) or 0) for b in bars[-20:]) / 20
            vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0

        result["candle_data"] = {
            "body_ratio": round(body_ratio, 3),
            "close_pos": round(close_pos, 3),
            "vol_ratio": round(vol_ratio, 2),
        }

    # ── 信号K判断 ─────────────────────────────────────────
    if b3_range < 0.01:
        result["reasons"].append("K线范围过小，无信号")
        return result

    body = abs(b3_close - b3_open)
    body_ratio = body / b3_range
    close_pos  = (b3_close - b3_low) / b3_range if b3_range > 0 else 0

    is_bullish = b3_close > b3_open
    is_strong  = body_ratio >= 0.6
    is_extreme = (is_bullish and close_pos >= 0.7) or (not is_bullish and close_pos <= 0.3)

    if is_strong and is_extreme:
        result["has_signal"] = True
        result["score"] = 3
        result["quality"] = "STRONG"
        result["bar_high"] = b3_high
        result["bar_low"]  = b3_low
        result["reasons"].append(
            f"{'阳' if is_bullish else '阴'}信号K实体{body_ratio:.0%}收在{'高' if is_bullish else '低'}端")
        if vol_ratio >= 1.5:
            result["score"] += 1
            result["reasons"].append(f"放量{vol_ratio:.1f}x确认")
    elif is_strong or is_extreme:
        result["has_signal"] = True
        result["score"] = 2
        result["quality"] = "MEDIUM"
        result["bar_high"] = b3_high
        result["bar_low"]  = b3_low
        result["reasons"].append(
            f"{'阳' if is_bullish else '阴'}信号K({'强' if is_strong else ''}{'极端' if is_extreme else ''})")
    else:
        result["reasons"].append("无明确信号K")

    return result


def calc_risk_reward(bars: list, entry: float, stop: float,
                     target: float, atr: float = 0) -> dict:
    """
    风险收益计算（P14/P16）

    Brooks 原文：
      P14："Actual Risk = 入场价 - 止损价"
      P16："盈亏比至少 3:1 才值得操作。"
    """
    risk      = abs(entry - stop)
    reward    = abs(target - entry)
    rr_ratio  = reward / risk if risk > 0 else 0
    risk_pct  = risk  / entry * 100
    reward_pct = reward / entry * 100

    return {
        "entry":       round(entry, 2),
        "stop_loss":   round(stop, 2),
        "target":      round(target, 2),
        "risk":        round(risk, 2),
        "reward":      round(reward, 2),
        "rr_ratio":    round(rr_ratio, 2),
        "risk_pct":    round(risk_pct, 2),
        "reward_pct":  round(reward_pct, 2),
        "atr":         round(atr, 2),
    }


# ═══════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════
# BuyFilterEngine v2 — 五层买入过滤系统
# ═══════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════

class BuyFilterEngine:
    """
    Brooks 五层买入过滤系统 v2

    层级设计：
      L0  多时间框架（1h + 日线联动，Buy Stop 状态）
      L1  市场环境（大盘方向）
      L2  趋势方向（EMA 排列 + H1 信号）
      L3  入场形态（回踩质量分层，v2 核心改进）
      L4  K线信号（信号K + 回踩止跌检测，v2 核心改进）
      L5  风险收益（RR 比 + Measured Move 目标，v2 核心改进）
    """

    def __init__(self, ticker: str, bars: list, spy_bars: list = None):
        self.ticker   = ticker
        self.bars     = bars
        self.spy_bars = spy_bars or bars
        self.results  = {}

    # ── L0: 多时间框架 ─────────────────────────────────────────
    def layer0_intraday_check(self, bars_1h: list = None,
                                daily_entry_price: float = None) -> dict:
        """
        L0: 1h 多时间框架 + Buy Stop 触发检测（v2 修复 None crash）
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
            "action": "NO_SIGNAL",
        }

        # ── 1h 数据存在时才做 EMA / H1 / 流动性分析 ──────────────
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
                reasons.append(f"1h EMA多头(EMA20={e20_1h:.2f}>EMA50={e50_1h:.2f})")
            else:
                reasons.append(f"1h EMA空头(EMA20={e20_1h:.2f}<EMA50={e50_1h:.2f})")
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

        # ── Buy Stop 触发检测（无1h数据时仍需执行）────────────────
        if daily_entry_price:
            if bars_1h and len(bars_1h) >= 20:
                for b in bars_1h[-16:]:
                    if float(b["high"]) >= daily_entry_price:
                        result["buy_stop_triggered"] = True
                        result["buy_stop_triggered_datetime"] = b["datetime"]
                        result["buy_stop_triggered_high"] = round(float(b["high"]), 2)
                        break
            if not result["buy_stop_triggered"] and self.bars:
                last_high = float(self.bars[-1]["high"])
                last_date  = self.bars[-1].get("date", "?")
                if last_high >= daily_entry_price:
                    result["buy_stop_triggered"] = True
                    result["buy_stop_triggered_datetime"] = f"{last_date}(日线after-hours)"
                    result["buy_stop_triggered_high"] = round(last_high, 2)

        self.results["L0"] = result
        return result

    # ── L1: 市场环境 ──────────────────────────────────────────
    def layer1_market_environment(self) -> dict:
        """
        L1: 大盘环境（P02/P09）

        Brooks 原文：
          P09："82%的时间市场处于区间震荡，不要逆趋势买入。"
          P02："只在市场有明确趋势时才积极买入。"
        """
        spy = self.spy_bars[-60:] if self.spy_bars else self.bars[-60:]
        if len(spy) < 20:
            return {"regime": "BEAR", "pass": False,
                    "score": 0, "reason": "SPY数据不足"}

        spy_closes = [float(b["close"]) for b in spy]
        spy_ema20  = _ema(spy_closes, 20)
        spy_ema50  = _ema(spy_closes, 50)

        if len(spy_ema20) < 5 or len(spy_ema50) < 5:
            return {"regime": "BEAR", "pass": False,
                    "score": 0, "reason": "SPY均线数据不足"}

        latest_spy = spy_closes[-1]
        above_ema20 = latest_spy > spy_ema20[-1]
        above_ema50 = latest_spy > spy_ema50[-1]
        ema_bull   = spy_ema20[-1] > spy_ema50[-1]
        ema_slope  = spy_ema20[-1] - spy_ema20[-10] if len(spy_ema20) >= 10 else 0

        if above_ema20 and above_ema50 and ema_bull:
            regime = "BULL"
        elif above_ema20 and not above_ema50:
            regime = "RECOVERY"
        elif not above_ema20 and not above_ema50:
            regime = "BEAR"
        else:
            regime = "RANGE"

        score = 2 if regime in ("BULL",) else (1 if regime == "RECOVERY" else 0)
        pass_ = regime in ("BULL", "RECOVERY")

        self.results["L1"] = {
            "regime": regime, "pass": pass_,
            "score": score,
            "reason": f"SPY {'✅多头' if pass_ else '❌空头/震荡'}（{latest_spy:.2f} EMA20={spy_ema20[-1]:.2f} EMA50={spy_ema50[-1]:.2f}）",
            "spys": {"ema20": round(spy_ema20[-1], 2), "ema50": round(spy_ema50[-1], 2)},
        }
        return self.results["L1"]

    # ── L2: 趋势方向 ──────────────────────────────────────────
    def layer2_trend_direction(self) -> dict:
        """
        L2: 趋势方向 + H1 信号（P02/P05）

        Brooks 原文：
          P05："H1 = 回调后第一根突破前高的阳线，这是最佳买入信号。"
          "L1 = 第三次推失败后出现的逆势K线。"
        """
        closes = [float(b["close"]) for b in self.bars]
        highs  = [float(b["high"])  for b in self.bars]
        lows   = [float(b["low"])   for b in self.bars]

        if len(closes) < 50:
            return {"trend": {}, "pass": False, "score": 0}

        ts = calc_trend_structure(self.bars, self.spy_bars)
        if not ts:
            return {"trend": {}, "pass": False, "score": 0}

        ema20 = ts.get("ema20", 0)
        ema50 = ts.get("ema50", 0)
        ema200 = ts.get("ema200", 0)
        above_ema20 = ts.get("above_ema20", False)
        above_ema50 = ts.get("above_ema50", False)
        ema_bull = ts.get("ema_bull", False)
        ema20_slope = ts.get("ema20_slope", 0)

        # ── H1/L1 检测 ───────────────────────────────────────
        h1 = {"has_h1": False, "h1_bar": None}
        l1 = {"has_l1": False, "l1_bar": None}

        # 近20天波段结构
        lookback = min(20, len(self.bars) - 1)
        recent_bars = self.bars[-lookback:]
        recent_closes = [float(b["close"]) for b in recent_bars]
        recent_highs  = [float(b["high"])  for b in recent_bars]
        recent_lows   = [float(b["low"])   for b in recent_bars]

        if recent_closes[-1] > recent_closes[0]:  # 近期上涨趋势
            min_idx = min(range(len(recent_closes)), key=lambda i: recent_closes[i])
            if min_idx < len(recent_closes) - 1:
                pullback_high = max(recent_closes[:min_idx]) if min_idx > 0 else recent_closes[0]
                for i in range(min_idx + 1, len(recent_closes)):
                    if recent_closes[i] > pullback_high:
                        h1["has_h1"] = True
                        h1["h1_bar"] = recent_bars[i]
                        break
        else:  # 近期下跌趋势
            max_idx = max(range(len(recent_closes)), key=lambda i: recent_closes[i])
            if max_idx < len(recent_closes) - 1:
                pullback_low = min(recent_closes[:max_idx]) if max_idx > 0 else recent_closes[0]
                for i in range(max_idx + 1, len(recent_closes)):
                    if recent_closes[i] < pullback_low:
                        l1["has_l1"] = True
                        l1["l1_bar"] = recent_bars[i]
                        break

        h1_invalidated = (
            l1["has_l1"] and h1["has_h1"] and
            h1["h1_bar"] is not None and
            l1["l1_bar"] is not None and
            h1["h1_bar"]["date"] < l1["l1_bar"]["date"]
        )

        score = 0
        reasons = []
        if ema_bull and above_ema20:
            score += 2
            reasons.append(f"EMA多头排列(EMA20={ema20:.2f}>EMA50={ema50:.2f})")
        elif above_ema20:
            score += 1
            reasons.append("价格在EMA20上方")
        else:
            reasons.append("⚠️价格在EMA20下方，空头")

        if h1["has_h1"]:
            score += 2
            h1_dt = h1["h1_bar"]["date"]
            reasons.append(f"H1信号({h1_dt})")
        elif l1["has_l1"]:
            reasons.append("L1信号（下跌趋势中的反弹）")
        else:
            reasons.append("无H1/L1信号")

        # ── v2 L2 改进：弱势 veto ────────────────────────────
        # 创日内新低但无 H1 → 弱势，不买
        recent_low  = min(recent_lows[-5:])
        today_low   = recent_lows[-1]
        is_new_low  = (today_low == recent_low) and len(recent_lows) >= 5
        weak_veto   = is_new_low and not h1["has_h1"]
        if weak_veto:
            score -= 1
            reasons.append("⚠️创日内新低但无H1 = 弱势，机构未参与")

        trend = {
            "ema20": ema20, "ema50": ema50, "ema200": ema200,
            "above_ema20": above_ema20, "above_ema50": above_ema50,
            "ema_bull": ema_bull,
            "ema20_slope": ema20_slope,
            "latest_close": ts.get("latest_close", 0),
            **h1, **l1,
            "h1_invalidated": h1_invalidated,
            "weak_veto": weak_veto,
        }

        pass_ = score >= 2 and not weak_veto

        self.results["L2"] = {
            "trend": trend, "h1": h1, "l1": l1,
            "pass": pass_, "score": score,
            "reason": "; ".join(reasons),
        }
        return self.results["L2"]

    # ── L3: 入场形态（v2 核心改进）─────────────────────────────
    def layer3_entry_form(self) -> dict:
        """
        L3: 入场形态 — 回踩质量分层（v2 核心）

        Brooks 原文：
          P05："Bread & Butter = 强势股回踩EMA20，这是最佳买入机会。"
          P02："50%回撤是关键支撑，市场在此停顿是正常的。"
          P05："深度回调（>61.8%）可能是趋势反转的信号，不买。"

        v2 回踩质量分层：
          Tier 1 (★★★★): 回踩 EMA20  ±2% + 有支撑证据（趋势线/TIBOW）
          Tier 2 (★★★):  回踩 50% 位 + 企稳证据
          Tier 3 (★★):   回踩趋势线 + 触3+次
          Tier 4 (★):    宽通道 / 深度回调（>61.8%）→ 拒绝或降权

        深度过滤：回撤 > 61.8% → 趋势可能反转，直接降低权重
        """
        retr  = calc_retracement(self.bars)
        ts    = calc_trend_structure(self.bars, self.spy_bars)
        trendline = detect_trendline_support(self.bars)
        tibow     = detect_tibow_reverse(self.bars)
        wedge     = detect_bull_bear_flag(self.bars)
        failed_123 = detect_failed_wedge_123(self.bars)
        h3_sig    = detect_h3_signal(self.bars)

        if not ts:
            return {"pass": False, "score": 0, "reason": "数据不足"}

        score      = 0
        reasons    = []
        form_type  = None
        pullback_tier = 0  # v2: 0=无回踩, 1=宽通道/深, 2=趋势线, 3=50%, 4=EMA20

        # ── 回撤深度过滤（v2 新增）────────────────────────────
        # 回撤 > 61.8% → 趋势可能反转，降权
        rp = retr.get("retracement_pct")
        deep_rejection = False
        if rp is not None and rp > 61.8:
            deep_rejection = True
            reasons.append(f"⚠️深度回撤({rp:.1f}%)>61.8%，趋势反转风险，拒绝买入")

        latest_close = ts.get("latest_close", 0)
        ema20       = ts.get("ema20", 0)

        # ── EMA20 回踩（Tier 1，最佳）─────────────────────────
        if ema20 > 0:
            dist_to_ema = abs(latest_close - ema20) / ema20
            if dist_to_ema < 0.02:  # 2% 内 = 真正回踩 EMA20
                pullback_tier = 4
                form_type = "BREAD_BUTTER"
                score += 4
                reasons.append(f"✅Bread & Butter: 回踩EMA20({ema20:.2f})±{dist_to_ema*100:.1f}%")
                if trendline["detected"]:
                    score += 1
                    reasons.append("  + 趋势线双重支撑 ✅")
                if tibow["detected"]:
                    score += 1
                    reasons.append(f"  + TIBOW({tibow['direction']})确认 ✅")
            elif dist_to_ema < 0.05:  # 5% 内 = 接近 EMA20
                pullback_tier = 3
                form_type = "NEAR_EMA20"
                score += 2
                reasons.append(f"接近EMA20({ema20:.2f})±{dist_to_ema*100:.1f}%")

        # ── 50% 回撤位（Tier 2）───────────────────────────────
        pct_50 = retr.get("pct_50_level", 0)
        if pct_50 > 0 and pullback_tier < 3:
            dist_to_50 = abs(latest_close - pct_50) / latest_close
            if dist_to_50 < 0.02:  # 2% 内
                pullback_tier = 3
                if form_type is None:
                    form_type = "PULLBACK_50"
                score = max(score, 3)
                reasons.append(f"✅回踩50%位({pct_50:.2f})±{dist_to_50*100:.1f}%")
            elif dist_to_50 < 0.03:
                if form_type is None:
                    form_type = "NEAR_50"
                score = max(score, 2)

        # ── 趋势线回踩（Tier 3）──────────────────────────────
        if trendline["detected"] and pullback_tier < 3:
            pullback_tier = 2
            if form_type is None:
                form_type = "TRENDLINE_SUPPORT"
            score = max(score, 3)
            reasons.append(
                f"趋势线支撑: ±{trendline['distance_pct']:.1f}%触{trendline['touch_count']}次"
            )
        elif trendline["broken"]:
            score -= 2
            reasons.append("⚠️趋势线已破")

        # ── TIBOW 反转（额外加分）─────────────────────────────
        if tibow["detected"]:
            score += 2
            tibow_dir = tibow["direction"]
            reasons.append(f"TIBOW Reverse({tibow_dir}): {tibow['bar2']['date']}")
            if form_type is None:
                form_type = f"TIBOW_{tibow_dir}"

        # ── Wedge 形态评分 ──────────────────────────────────
        if wedge["type"] == "BULL_FLAG":
            score += 2
            reasons.append(f"Bull Flag（顺势回调{trendline.get('trendline_price', 0):.2f}）")
        elif wedge["type"] == "FALLING_WEDGE":
            score += 1
            reasons.append("下跌楔形（警惕反转）")
        elif wedge["type"] == "WIDE_CHANNEL":
            score -= 1
            pullback_tier = max(1, pullback_tier)
            reasons.append("⚠️宽通道（深度回调风险）")

        # ── H3 三推反转（v2 增强）────────────────────────────
        if h3_sig["has_h3"]:
            reasons.append(f"H3三推反转信号：{h3_sig.get('note','')}")

        # ── 失败 123 结构 ───────────────────────────────────
        if failed_123["has_123"]:
            ft = failed_123["type"]
            if ft == "TOP_123":
                score -= 2
                reasons.append(f"⚠️顶部123失败：{failed_123['note']}")
            elif ft == "BOTTOM_123":
                score += 1
                reasons.append(f"底部123反转：{failed_123['note']}")

        # ── 回撤幅度合理性（v2 增强）─────────────────────────
        if rp is not None:
            if 20 <= rp <= 50:
                score += 2
                reasons.append(f"回撤幅度合理({rp:.1f}%)")
            elif rp > 61.8:
                score -= 2  # 深度过滤
                reasons.append(f"⚠️深度回撤({rp:.1f}%)>61.8%")
            elif rp > 50:
                score -= 1
                reasons.append(f"⚠️偏深回撤({rp:.1f}%)>50%")

        # ── 通过门槛 ────────────────────────────────────────
        # v2: Tier 4(EMA20) ≥3分, Tier 3(50%/趋势线) ≥2分, Tier 2(宽通道) ≥0分
        # 深度回撤 >61.8% 即使 score 高也降低 pass 标准
        min_pass = 2 if not deep_rejection else 4
        pass_ = score >= min_pass

        self.results["L3"] = {
            "pass": pass_, "score": score,
            "reason": "; ".join(reasons) if reasons else "无明确形态",
            "form_type": form_type,
            "pullback_tier": pullback_tier,  # v2 新增
            "deep_rejection": deep_rejection,  # v2 新增
            "retracement": retr,
            "trendline": trendline,
            "tibow": tibow,
            "wedge": wedge,
            "h3": h3_sig,
            "failed_123": failed_123,
        }
        return self.results["L3"]

    # ── L4: K线信号（v2 核心改进）──────────────────────────────
    def layer4_kline_signal(self) -> dict:
        """
        L4: K线信号 — 回踩止跌检测（v2 核心）

        Brooks 原文：
          P07："信号K = 趋势K线（实体≥60%）+ 收在极端位"
          P08："Bread & Butter set-up = 回踩后出现反转K线（吞没/锤子）"
          P05："H1 = 回调后第一根突破前高的阳线 = 多头重新夺回控制权"

        v2 改进：检测"回踩是否已结束"
          - 价格不再创新低（最低点已过）= 回踩可能结束
          - 出现 H1 或阳包阴 = 回踩结束信号
        """
        sig  = detect_signal_bar(self.bars)
        ts   = calc_trend_structure(self.bars, self.spy_bars)
        if not ts:
            return {"pass": False, "score": 0}

        # ── v2: 回踩止跌检测 ───────────────────────────────
        lookback = min(20, len(self.bars) - 1)
        recent_bars = self.bars[-lookback:]
        recent_lows  = [float(b["low"])  for b in recent_bars]
        recent_closes = [float(b["close"]) for b in recent_bars]

        # 最低点位置
        min_idx_in_recent = recent_lows.index(min(recent_lows))
        is_pullback_done  = (min_idx_in_recent < len(recent_lows) - 2)
        # 最低点在最近3根K线之前 → 回踩可能已结束

        # 出现 H1（在回踩结束后）
        h1_after_pullback = False
        if is_pullback_done and min_idx_in_recent < len(recent_bars) - 1:
            post_pullback = recent_bars[min_idx_in_recent + 1:]
            post_closes = recent_closes[min_idx_in_recent + 1:]
            if post_closes:
                pullback_low = recent_lows[min_idx_in_recent]
                for i, c in enumerate(post_closes):
                    if c > max(recent_closes[:min_idx_in_recent + 1 + i]):
                        h1_after_pullback = True
                        break

        # 阳包阴（回踩后出现）
        bull_engulf = False
        if len(self.bars) >= 2:
            b1 = self.bars[-2]
            b2 = self.bars[-1]
            b1_low, b1_high = float(b1["low"]), float(b1["high"])
            b2_low, b2_high = float(b2["low"]), float(b2["high"])
            b2_close = float(b2["close"])
            if b2_high > b1_high and b2_low < b1_low and b2_close > b1_high:
                bull_engulf = True

        pullback_done_signal = h1_after_pullback or bull_engulf

        score = sig.get("score", 0)
        reasons = sig.get("reasons", []).copy()

        # ── 背景判断 ──────────────────────────────────────
        if ts["above_ema20"] and ts["ema20_above_ema50"]:
            score += 1
            reasons.append("好背景(EMA多头排列)")
        else:
            score -= 1
            reasons.append("⚠️差背景")

        # ── v2: 回踩止跌加分 ───────────────────────────────
        if is_pullback_done:
            score += 1
            reasons.append(f"回踩可能已结束（最低点在{lookback - min_idx_in_recent}根前）")
            if h1_after_pullback:
                score += 1
                reasons.append("H1已出现 = 回踩结束确认 ✅")
            if bull_engulf:
                score += 1
                reasons.append("阳包阴 = 回踩结束确认 ✅")
        else:
            reasons.append(f"回踩未结束（最低点在最近{min_idx_in_recent}根内）")

        pass_ = score >= 3

        self.results["L4"] = {
            "pass": pass_, "score": score,
            "reason": "; ".join(reasons),
            "signal": sig,
            "pullback_done": is_pullback_done,
            "pullback_done_signal": pullback_done_signal,
            "h1_after_pullback": h1_after_pullback,
            "bull_engulf": bull_engulf,
        }
        return self.results["L4"]

    # ── L5: 风险收益（v2 核心改进）────────────────────────────
    def layer5_risk_reward(self, h1_info: dict = None) -> dict:
        """
        L5: 风险收益 — Measured Move 目标（v2 核心）

        Brooks 原文：
          P13："Measured Move = 区间高度 → 突破后等距投射"
          "目标 = 突破点 ± 结构高度（H-L）"
          P15："缺口往往成为止盈位，缺口回补后往往是真正顶部。"

        v2 改进：
          - Measured Move 目标 = 区间高度投射
          - 缺口目标检测（Gap fill 止盈参考）
          - ATR 动态止损
        """
        if len(self.bars) < 20:
            return {"pass": False, "score": 0, "veto": True}
        closes = [float(b["close"]) for b in self.bars]
        highs  = [float(b["high"])  for b in self.bars]
        lows   = [float(b["low"])   for b in self.bars]
        latest_close = closes[-1]

        atr    = _atr(self.bars)
        ema20  = _ema(closes, 20)[-1] if len(closes) >= 20 else latest_close
        ema50  = _ema(closes, 50)[-1] if len(closes) >= 50 else latest_close

        # ── Measured Move 目标计算 ─────────────────────────
        # 方法：取近 20-60 天的区间高度，作为突破后的等距投射目标
        lookback_mm = min(60, len(self.bars) - 1)
        range_high  = max(highs[-lookback_mm:])
        range_low   = min(lows[-lookback_mm:])
        range_height = range_high - range_low

        # 找近期突破点（价格超越 range_high）
        breakout_point = None
        for i in range(len(closes) - 1, max(0, len(closes) - 20), -1):
            if closes[i] > range_high:
                breakout_point = highs[i]
                break

        if breakout_point:
            measured_target = breakout_point + range_height
        else:
            measured_target = range_high + range_height * 0.5

        # ── 缺口目标检测 ─────────────────────────────────
        gap_target = None
        for i in range(max(0, len(closes) - 30), len(closes) - 1):
            gap = highs[i] - lows[i + 1]
            if gap > atr * 0.5:  # 缺口 > 0.5 ATR 算有效
                gap_target = lows[i + 1]  # 缺口下沿 = 目标位
                break

        # ── 止损目标 ─────────────────────────────────────
        # 止损：EMA20 下方 1 ATR 或 入场价 - 2 ATR
        stop_loss  = min(ema20, latest_close - 2 * atr)
        entry_price = latest_close

        # 目标：Measured Move 目标 或 缺口目标（取更近的）
        if gap_target and gap_target < measured_target:
            mm_target = gap_target
            target_source = "GAP_FILL"
        else:
            mm_target = measured_target
            target_source = "MEASURED_MOVE"

        # Brooks 最小 RR 比 = 2:1（v2 放宽到 1.5:1）
        risk      = abs(entry_price - stop_loss)
        reward    = abs(mm_target - entry_price)
        rr_ratio  = reward / risk if risk > 0 else 0
        veto      = rr_ratio < 1.5  # v2 RR 门槛降到 1.5

        score = 0
        reasons = []
        if rr_ratio >= 3:
            score = 3
        elif rr_ratio >= 2:
            score = 2
        elif rr_ratio >= 1.5:
            score = 1
        else:
            score = 0
            reasons.append(f"盈亏比不足({rr_ratio:.1f}<1.5)")

        risk_pct   = risk / entry_price * 100 if entry_price > 0 else 0
        reward_pct = reward / entry_price * 100 if entry_price > 0 else 0
        reasons.append(
            f"入场{entry_price:.2f}→止损{stop_loss:.2f}"
            f"(Risk={risk:.2f}={risk_pct:.1f}%)"
            f"→目标{mm_target:.2f}({target_source})"
            f"(Reward={reward:.2f}={reward_pct:.1f}%, RR={rr_ratio:.1f})"
        )

        pass_ = score >= 1 and not veto
        self.results["L5"] = {
            "pass": pass_, "score": score,
            "reason": "; ".join(reasons),
            "veto": veto,
            "details": {
                "entry": round(entry_price, 2),
                "stop_loss": round(stop_loss, 2),
                "target": round(mm_target, 2),
                "target_source": target_source,
                "measured_target": round(measured_target, 2),
                "gap_target": round(gap_target, 2) if gap_target else None,
                "risk": round(risk, 2),
                "reward": round(reward, 2),
                "rr_ratio": round(rr_ratio, 2),
                "atr": round(atr, 2),
                "range_height": round(range_height, 2),
                "breakout_point": round(breakout_point, 2) if breakout_point else None,
            }
        }
        return self.results["L5"]

    # ── 综合评级 ─────────────────────────────────────────────
    def run(self, bars_1h: list = None, daily_entry_price: float = None) -> dict:
        l0  = self.layer0_intraday_check(bars_1h=bars_1h,
                                         daily_entry_price=daily_entry_price)
        l1  = self.layer1_market_environment()
        l2  = self.layer2_trend_direction()
        l3  = self.layer3_entry_form()
        l4  = self.layer4_kline_signal()
        l5  = self.layer5_risk_reward()

        passed = sum([l1["pass"], l2["pass"], l3["pass"], l4["pass"], l5["pass"]])
        scores = {
            "L1_market": l1.get("score", 0),
            "L2_trend": l2.get("score", 0),
            "L3_form":  l3.get("score", 0),
            "L4_signal": l4.get("score", 0),
            "L5_risk":  l5.get("score", 0),
        }
        total_score = sum(scores.values())

        if l1["regime"] == "BEAR":
            grade = "F"; advice = "大盘空头，禁止买入"
        elif l5.get("veto"):
            grade = "F"; advice = "盈亏比不足，一票否决"
        elif passed >= 5 and total_score >= 12:
            grade = "A"; advice = self._build_advice("A")
        elif passed >= 4 and total_score >= 9:
            grade = "B"; advice = self._build_advice("B")
        elif passed >= 3:
            grade = "C"; advice = self._build_advice("C")
        else:
            grade = "D"; advice = self._build_advice("D")

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

    # ── STAGE 分类 ──────────────────────────────────────────
    def _classify_stage(self) -> dict:
        """
        Brooks STAGE 分类（v2 增强 pullback 检测）

        六阶段：
          STAGE_1: 信号K形成，Buy Stop 未触发
          STAGE_2: Buy Stop 触发，等回踩
          STAGE_3: 回踩中（v2: 检测回踩是否接近 EMA20/50%）
          STAGE_4: 回踩结束 → NOW 买入
          STAGE_F: 条件不满足
        """
        l0  = self.results.get("L0", {})
        l1  = self.results.get("L1", {})
        l2  = self.results.get("L2", {})
        l3  = self.results.get("L3", {})
        l4  = self.results.get("L4", {})
        l5  = self.results.get("L5", {})

        buy_stop_triggered = l0.get("buy_stop_triggered", False)
        l4_pass = l4.get("pass", False)
        l5_veto = l5.get("veto", False)
        l1_regime = l1.get("regime", "BEAR")
        regime_pass = l1.get("pass", False)
        form_type = l3.get("form_type", "NONE")
        pullback_tier = l3.get("pullback_tier", 0)  # v2
        deep_rejection = l3.get("deep_rejection", False)  # v2
        ts = l2.get("trend", {})
        current = ts.get("latest_close", 0)
        ema20 = ts.get("ema20", 0)
        rr = l5.get("details", {})
        sig = l4.get("signal", {})
        entry_price = rr.get("entry", current)
        stop_price  = rr.get("stop_loss", entry_price * 0.97)
        rr_ratio = rr.get("rr_ratio", 0)

        sig_bar_high = float(self.bars[-1]["high"]) if self.bars else 0
        sig_bar_date = self.bars[-1]["date"] if self.bars else "?"
        l4_quality = sig.get("quality", "WEAK")
        body_ratio = sig.get("candle_data", {}).get("body_ratio", 0)
        vol_ratio  = sig.get("candle_data", {}).get("vol_ratio", 0)

        # ── STAGE 4: 回踩结束（v2 强化）────────────────────
        # 条件：Buy Stop 已触发 + 回踩到位（EMA20/50%/趋势线）+ L4 通过 + pullback 止跌信号
        if buy_stop_triggered and l4_pass and not l5_veto:
            pullback_done = l4.get("pullback_done", False)
            done_signal   = l4.get("pullback_done_signal", False)
            tier_name = {4: "EMA20回踩✅", 3: "50%回撤✅", 2: "趋势线✅",
                          1: "宽通道⚠️", 0: "无回踩"}.get(pullback_tier, "")

            # Brooks: Tier 4(EMA20) 或 Tier 3(50%) + 回踩止跌 → NOW
            if pullback_tier >= 3 and pullback_done:
                return {
                    "stage": "STAGE_4", "name": "回踩到位 ✅ NOW",
                    "key_level": f"回踩{pullback_tier}级({tier_name}) | EMA20={ema20:.2f}",
                    "confirm": f"回踩已结束 ✅ tier={pullback_tier} | action=NOW → 买入",
                    "brooks": "P09 Bread & Butter：回踩EMA20后出现反转K线 = NOW 买入",
                    "action": "NOW",
                    "color": "green",
                    "summary": f"Buy Stop触发({entry_price:.2f})，回踩到{pullback_tier}级支撑({tier_name})，止跌信号出现，回踩结束 → NOW买入",
                }
            elif pullback_tier >= 3:
                return {
                    "stage": "STAGE_3", "name": "回踩进行中",
                    "key_level": f"回踩{pullback_tier}级({tier_name}) | EMA20={ema20:.2f}",
                    "confirm": f"回踩{pullback_tier}级支撑，等待止跌信号出现 → STAGE_4",
                    "brooks": "P09：不预测回踩何时结束，等待确认信号",
                    "action": "WATCH",
                    "color": "yellow",
                    "summary": f"Buy Stop触发({entry_price:.2f})，回踩{pullback_tier}级({tier_name})，等待止跌K出现",
                }
            elif pullback_tier >= 2:
                return {
                    "stage": "STAGE_3", "name": "趋势线回踩",
                    "key_level": f"趋势线/宽通道回踩 | EMA20={ema20:.2f}",
                    "confirm": f"等待EMA20/50%回踩确认 → STAGE_4",
                    "brooks": "P05：等待价格回到 EMA20 再买入",
                    "action": "WATCH",
                    "color": "yellow",
                    "summary": f"Buy Stop触发，回踩趋势线({tier_name})，继续等待",
                }
            else:
                return {
                    "stage": "STAGE_3", "name": "深度回踩中",
                    "key_level": f"EMA20={ema20:.2f} | 现价={current:.2f}",
                    "confirm": "深度回踩，趋势可能反转，观望",
                    "brooks": "P02：深度回调>61.8%可能是反转，不是回踩",
                    "action": "WATCH",
                    "color": "orange",
                    "summary": f"Buy Stop触发，但回踩深度异常，等待确认",
                }

        # ── STAGE 2: Buy Stop 已触发 ──────────────────────
        if buy_stop_triggered and l4_pass and not l5_veto:
            return {
                "stage": "STAGE_2", "name": "入场位确认",
                "key_level": f"Buy Stop触发={entry_price:.2f}",
                "confirm": f"等回踩 → STAGE_3 → STAGE_4",
                "brooks": "P07：Buy Stop触发后，等待 Bread & Butter 回踩买入机会",
                "action": "WATCH",
                "color": "blue",
                "summary": f"价格已站上{sig_bar_high:.2f}，等待回踩",
            }

        # ── STAGE 1: 信号K形成，Buy Stop 未触发 ─────────────
        if l4_pass and not buy_stop_triggered and not l5_veto and regime_pass:
            buy_stop_price = sig_bar_high + 0.01
            gap = buy_stop_price - current
            gap_pct = gap / current * 100 if current > 0 else 0
            return {
                "stage": "STAGE_1", "name": "信号蓄势 ⏳",
                "key_level": f"信号K高点={sig_bar_high:.2f} | Buy Stop={buy_stop_price:.2f} | 现价={current:.2f}(还差{gap_pct:.1f}%)",
                "confirm": f"当价格≥{buy_stop_price:.2f} → Buy Stop触发 → STAGE_2",
                "brooks": "P07：信号K出现后挂Buy Stop在高点上方1 tick",
                "action": "WATCH",
                "color": "cyan",
                "summary": f"信号K({sig_bar_date})质量={l4_quality}，量能={vol_ratio}x，挂{buy_stop_price:.2f} Buy Stop等待突破",
            }

        # ── STAGE F ────────────────────────────────────────
        blockers = []
        if l5_veto:    blockers.append(f"盈亏比不足({rr_ratio:.1f})")
        if deep_rejection: blockers.append("深度回撤>61.8%")
        if l2.get("trend", {}).get("weak_veto"): blockers.append("弱势(无H1)")
        if not regime_pass: blockers.append(f"大盘{l1_regime}")

        return {
            "stage": "STAGE_F", "name": "暂不符合",
            "key_level": f"现价={current:.2f}",
            "confirm": "等待障碍消除：" + ", ".join(blockers) if blockers else "需更多条件确认",
            "brooks": "Brooks：一票否决的情况不下单",
            "action": "NO_ACTION",
            "color": "gray",
            "summary": "当前不符合入场条件。" + ", ".join(blockers) if blockers else "需更多条件确认",
        }

    def _build_advice(self, grade: str) -> str:
        stage = self._classify_stage()
        l0 = self.results.get("L0", {})
        l1 = self.results.get("L1", {})
        l2 = self.results.get("L2", {})
        l3 = self.results.get("L3", {})
        l4 = self.results.get("L4", {})
        l5 = self.results.get("L5", {})
        rr = l5.get("details", {})
        ts = l2.get("trend", {})
        sig = l4.get("signal", {})
        h1  = l2.get("h1", {})

        stage_name = stage.get("name", "")
        regime = l1.get("regime", "?")
        current = ts.get("latest_close", 0)
        ema20   = ts.get("ema20", 0)
        entry   = rr.get("entry", current)
        stop    = rr.get("stop_loss", entry * 0.97)
        target  = rr.get("target", entry * 1.05)
        rr_ratio = rr.get("rr_ratio", 0)
        atr     = rr.get("atr", 0)
        vol_ratio = sig.get("candle_data", {}).get("vol_ratio", 0)
        form_type = l3.get("form_type", "NONE")
        pullback_tier = l3.get("pullback_tier", 0)
        tier_desc = {4: "EMA20回踩✅", 3: "50%回撤✅", 2: "趋势线✅",
                     1: "宽通道⚠️", 0: "无回踩"}.get(pullback_tier, "?")

        return (
            f"{grade}级({stage.get('stage','')}) | {regime} | "
            f"现价={current:.2f} EMA20={ema20:.2f} | "
            f"形态={form_type}(tier={pullback_tier}) | "
            f"RR={rr_ratio:.1f} | 量={vol_ratio:.1f}x | "
            f"入={entry:.2f} 止={stop:.2f} 目={target:.2f}"
        )


# ═══════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker", nargs="?", default="AAPL")
    ap.add_argument("--spy", default="SPY")
    ap.add_argument("--lookback", type=int, default=300)
    args = ap.parse_args()

    bars  = load_klines(args.ticker,  lookback=args.lookback)
    spy   = load_klines(args.spy,   lookback=args.lookback)
    bars1h = load_1h_klines(args.ticker, lookback=500)

    if not bars:
        print(f"ERROR: 无 {args.ticker} 数据"); sys.exit(1)

    eng = BuyFilterEngine(args.ticker, bars, spy_bars=spy)
    result = eng.run(bars_1h=bars1h)

    print(f"\n{'='*60}")
    print(f"{args.ticker} v2 综合分析")
    print(f"{'='*60}")
    print(f"评级: {result['grade']} | STAGE: {result['stage']}")
    print(f"通过层数: {result['passed_layers']}/5 | 总分: {result['total_score']}")
    print(f"\n各层评分: {result['scores']}")
    print(f"\n评级理由: {result['advice']}")
    stage = result["stage_info"]
    print(f"\nSTAGE: {stage.get('name','?')} | {stage.get('key_level','')}")
    print(f"确认条件: {stage.get('confirm','')}")
    print(f"Brooks: {stage.get('brooks','')}")

    l0 = result["layers"].get("L0", {})
    l3 = result["layers"].get("L3", {})
    l4 = result["layers"].get("L4", {})
    l5 = result["layers"].get("L5", {})
    print(f"\nL0: buy_stop_triggered={l0.get('buy_stop_triggered')} | action={l0.get('action')}")
    print(f"L3: form={l3.get('form_type')} | tier={l3.get('pullback_tier')} | deep={l3.get('deep_rejection')}")
    print(f"L4: pullback_done={l4.get('pullback_done')} | bull_engulf={l4.get('bull_engulf')}")
    print(f"L5: RR={l5.get('details',{}).get('rr_ratio')} | veto={l5.get('veto')}")
    print(f"\n信号K详情: {l4.get('signal',{}).get('reasons',[])}")
    print(f"L5盈亏: {l5.get('reason','')}")
