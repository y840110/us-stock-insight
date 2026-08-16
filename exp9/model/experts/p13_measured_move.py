#!/usr/bin/env python3
"""
P13 止盈目标位(1) — Measured Move
===================================
来源：方方土价格行为学 · Brooks Price Action
视频：13-11止盈目标位(1)-MeasuredMove.mp4
分析方法：字幕直接使用（P13.srt匹配） + Vision帧分析（6帧）

核心主题：
  1. Measured Move 原理：结构高度 → 止盈目标
  2. 区间突破 Measured Move
  3. 双顶/双底 Measured Move
  4. 缺口作为目标位
  5. 第一趋势幅度（日内）
  6. 止损与止盈策略
  7. Brooks 关键语录："自我感觉良好没有用，关键是要能赚到钱"

铁律：K线数据必须以 `time` 字段判断最新价格，禁止用 `data[-1]`
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Literal
from enum import Enum

# ══════════════════════════════════════════════════════════════════════════════
# 枚举与数据结构
# ══════════════════════════════════════════════════════════════════════════════

class MeasuredMoveType(Enum):
    RANGE_BREAKOUT = "RANGE_BREAKOUT"        # 区间突破
    DOUBLE_TOP_BOTTOM = "DOUBLE_TOP_BOTTOM"    # 双顶/双底
    WEDGE_BREAKOUT = "WEDGE_BREAKOUT"        # 楔形突破
    GAP_TARGET = "GAP_TARGET"                 # 缺口目标
    FLAG_TARGET = "FLAG_TARGET"               # 旗形目标

@dataclass
class PriceStructure:
    """价格结构"""
    structure_type: MeasuredMoveType
    high: float
    low: float
    height: float
    breakout_price: float
    breakout_direction: Literal["up", "down"]

    @property
    def measured_move_target(self) -> float:
        """Measured Move 目标位"""
        if self.breakout_direction == "up":
            return self.breakout_price + self.height
        else:
            return self.breakout_price - self.height

    @property
    def risk_reward_ratio(self) -> float:
        """基于 Measured Move 的盈亏比"""
        return self.height / (self.breakout_price * 0.002)  # 简化版

@dataclass
class DayAmplitude:
    """日内波动幅度"""
    first_trend_amplitude: float
    first_trend_direction: Literal["up", "down"]
    day_range_estimate: float
    remaining_amplitude: Optional[float] = None

    @property
    def is_large_first_trend(self) -> bool:
        """第一趋势幅度是否偏大"""
        return self.first_trend_amplitude > self.day_range_estimate * 0.5

# ══════════════════════════════════════════════════════════════════════════════
# Measured Move 计算
# ══════════════════════════════════════════════════════════════════════════════

def identify_price_structure(
    bars: list,
    lookback: int = 50
) -> Optional[PriceStructure]:
    """
    识别价格结构并计算 Measured Move 目标

    步骤：
    1. 识别震荡区间（range highs/lows）
    2. 计算区间高度
    3. 确定突破方向和突破点
    4. 计算 Measured Move 目标
    """
    if len(bars) < lookback:
        return None

    recent = bars[-lookback:]

    # 找区间高点/低点（简化版）
    highs = [getattr(b, 'high', 0) for b in recent]
    lows = [getattr(b, 'low', 0) for b in recent]

    range_high = max(highs)
    range_low = min(lows)
    range_height = range_high - range_low

    # 判断是否在区间内（简化：当前价格在高低点中间40-60%范围）
    current = getattr(bars[-1], 'close', 0)
    mid = (range_high + range_low) / 2
    if abs(current - mid) > range_height * 0.3:
        return None  # 不在区间内

    # 判断突破方向（简化版）
    last_high = highs[-1]
    last_low = lows[-1]

    if last_high > range_high * 0.98:
        # 向上突破
        return PriceStructure(
            structure_type=MeasuredMoveType.RANGE_BREAKOUT,
            high=range_high,
            low=range_low,
            height=range_height,
            breakout_price=range_high,
            breakout_direction="up"
        )
    elif last_low < range_low * 1.02:
        # 向下突破
        return PriceStructure(
            structure_type=MeasuredMoveType.RANGE_BREAKOUT,
            high=range_high,
            low=range_low,
            height=range_height,
            breakout_price=range_low,
            breakout_direction="down"
        )

    return None

def calculate_measured_move(
    structure_high: float,
    structure_low: float,
    breakout_price: float,
    direction: Literal["up", "down"]
) -> float:
    """
    计算 Measured Move 目标位

    规则：
    - 目标 = 突破点 ± 结构高度
    - 结构高度 = H - L
    """
    height = structure_high - structure_low
    if direction == "up":
        return breakout_price + height
    else:
        return breakout_price - height

# ══════════════════════════════════════════════════════════════════════════════
# 双顶/双底 Measured Move
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DoubleTopBottom:
    """双顶/双底"""
    is_top: bool  # True=双顶，False=双底
    neckline_price: float      # 颈线价格
    peak_trough_price: float   # 峰/谷价格
    reversal_price: float      # 反转点价格

    @property
    def measured_target(self) -> float:
        """双顶/双底 Measured Move 目标"""
        height = abs(self.peak_trough_price - self.neckline_price)
        if self.is_top:
            return self.neckline_price - height
        else:
            return self.neckline_price + height

    @property
    def is_failed_reversal(self) -> bool:
        """是否失败的反转（突破颈线后失败 = Wedge 123）"""
        return False  # 需K线数据

def identify_double_top_bottom(bars: list) -> Optional[DoubleTopBottom]:
    """识别双顶/双底结构"""
    if len(bars) < 20:
        return None

    # 简化：找最近的两个局部高/低点
    highs = []
    for i in range(2, len(bars) - 2):
        b = bars[i]
        if (getattr(b, 'high', 0) > getattr(bars[i-1], 'high', 0) and
            getattr(b, 'high', 0) > getattr(bars[i-2], 'high', 0) and
            getattr(b, 'high', 0) > getattr(bars[i+1], 'high', 0) and
            getattr(b, 'high', 0) > getattr(bars[i+2], 'high', 0)):
            highs.append((i, getattr(b, 'high', 0), getattr(b, 'time', 0)))

    if len(highs) >= 2:
        h1_idx, h1_price, _ = highs[-2]
        h2_idx, h2_price, _ = highs[-1]
        # 双顶：两个高点相近
        if abs(h1_price - h2_price) / h1_price < 0.005:
            # 找颈线（中间低点）
            neckline = min(getattr(bars[j], 'low', 0)
                          for j in range(h1_idx, h2_idx + 1))
            return DoubleTopBottom(
                is_top=True,
                neckline_price=neckline,
                peak_trough_price=min(h1_price, h2_price),
                reversal_price=neckline
            )

    return None

# ══════════════════════════════════════════════════════════════════════════════
# 日内第一趋势幅度
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DayFirstTrend:
    """日内第一趋势"""
    start_time: int
    end_time: int
    amplitude: float
    direction: Literal["up", "down"]
    start_price: float
    end_price: float

def identify_first_trend(bars: list) -> Optional[DayFirstTrend]:
    """
    识别日内第一趋势及其幅度

    规则：
    - 开盘后第一个明显的趋势波段
    - 记录其幅度作为全天参考
    """
    if len(bars) < 10:
        return None

    # 简化：找第一根趋势K线
    first_bar = bars[0]
    start_price = getattr(first_bar, 'close', 0)
    start_time = getattr(first_bar, 'time', 0)

    # 找趋势方向（简化）
    up_count = sum(1 for b in bars[:min(5, len(bars))]
                   if getattr(b, 'close', 0) > getattr(b, 'open', 0))
    direction: Literal["up", "down"] = "up" if up_count >= 3 else "down"

    if direction == "up":
        end_price = max(getattr(b, 'close', 0) for b in bars[:min(5, len(bars))])
    else:
        end_price = min(getattr(b, 'close', 0) for b in bars[:min(5, len(bars))])

    amplitude = abs(end_price - start_price)

    last_bar = bars[min(4, len(bars)-1)]
    end_time = getattr(last_bar, 'time', 0)

    return DayFirstTrend(
        start_time=start_time,
        end_time=end_time,
        amplitude=amplitude,
        direction=direction,
        start_price=start_price,
        end_price=end_price
    )

def estimate_day_range(
    first_trend: DayFirstTrend,
    typical_range: float
) -> float:
    """
    估算全天波动范围

    经验法则：
    - 如果第一趋势幅度很大 → 全天可能高位震荡，范围偏大
    - 如果第一趋势幅度很小 → 全天延续小范围
    """
    # 简化：全天范围 ≈ 第一趋势幅度 × 1.5-2
    return first_trend.amplitude * 1.8

# ══════════════════════════════════════════════════════════════════════════════
# 止盈策略
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TakeProfitLevel:
    """止盈位"""
    price: float
    source: str  # "measured_move" / "gap" / "previous_structure"
    strength: Literal["strong", "medium", "weak"]  # 支撑/阻力强度

def calculate_take_profit_levels(
    structure: PriceStructure,
    gaps: list = None
) -> list[TakeProfitLevel]:
    """
    计算止盈位列表

    优先级：
    1. Measured Move 目标（最强）
    2. 缺口（如果存在）
    3. 前一个结构
    """
    levels = []

    # Measured Move 目标
    mm_price = structure.measured_move_target
    levels.append(TakeProfitLevel(
        price=mm_price,
        source="measured_move",
        strength="strong"
    ))

    # 缺口作为目标
    if gaps:
        for gap in gaps:
            if structure.breakout_direction == "up":
                if gap.low > structure.breakout_price:
                    levels.append(TakeProfitLevel(
                        price=gap.low,
                        source="gap",
                        strength="medium"
                    ))
            else:
                if gap.high < structure.breakout_price:
                    levels.append(TakeProfitLevel(
                        price=gap.high,
                        source="gap",
                        strength="medium"
                    ))

    # 按价格排序
    if structure.breakout_direction == "up":
        levels.sort(key=lambda x: x.price, reverse=True)
    else:
        levels.sort(key=lambda x: x.price)

    return levels

# ══════════════════════════════════════════════════════════════════════════════
# Brooks 核心规则（P13）
# ══════════════════════════════════════════════════════════════════════════════

MEASURED_MOVE_RULES = """
=== Brooks P13 核心规则 ===

1. 【Measured Move 原理】
   目标 = 突破点 ± 结构高度（H-L）
   当价格有效突破后，往往走出与结构等距的第二波

2. 【区间突破 Measured Move】
   区间高度 = 最高价 - 最低价
   突破后目标 = 突破点 ± 区间高度

3. 【双顶/双底 Measured Move】
   颈线到峰/谷的距离 = 目标幅度
   目标 = 颈线 ± 幅度

4. 【缺口作为目标】
   缺口往往成为后续行情的目标
   填补缺口 = 目标达成

5. 【第一趋势幅度】
   开盘后第一波趋势幅度 → 全天参考范围

6. 【止损原则】
   止损放在结构之外（不能被轻易触及）
   多头止损：波段最低点下方
   空头止损：波段最高点上方

7. 【Brooks 语录】
   "自我感觉良好没有用，关键是要能赚到钱！"
   → 到达 Measured Move 目标 → 止盈，不要固执

8. 【大资金在目标位挂限价单】
   当价格到达目标 → 大量卖单堆积 → 价格精准回落
"""
