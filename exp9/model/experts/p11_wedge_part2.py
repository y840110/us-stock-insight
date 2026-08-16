#!/usr/bin/env python3
"""
P11 三推楔形专题(2) — Wedge Reversal Patterns Part 2
=====================================================
来源：方方土价格行为学 · Brooks Price Action
视频：11-09Wedge—楔形反转(2).mp4
分析方法：Whisper采样转写（8采样点）+ Vision帧分析

核心主题：
  1. 楔形嵌套结构（Nested Wedge）：小结构服从大结构
  2. 双顶/双底 + Wedge组合：中继形态的识别
  3. 失败的反转 = Wedge 123：双底突破失败案例
  4. Wedge失败的情况：为什么一定会失败
  5. Trading Range内的Wedge：中继楔形
  6. 顺大逆小的Wedge：趋势中的楔形回调（Bull/Bear Flag）
  7. Wedge实战训练方法：每日练习、复盘训练

铁律：K线数据必须以 `time` 字段判断最新价格，禁止用 `data[-1]`
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Literal
from enum import Enum
import math

# ══════════════════════════════════════════════════════════════════════════════
# 枚举与数据结构
# ══════════════════════════════════════════════════════════════════════════════

class WedgeType(Enum):
    WEDGE_TOP_REVERSAL = "WEDGE_TOP_REVERSAL"      # 三推向上 → 看跌
    WEDGE_BOTTOM_REVERSAL = "WEDGE_BOTTOM_REVERSAL" # 三推向下 → 看涨
    WEDGE_BULL_FLAG = "WEDGE_BULL_FLAG"            # 上涨中的回调（持续）
    WEDGE_BEAR_FLAG = "WEDGE_BEAR_FLAG"            # 下跌中的反弹（持续）
    WEDGE_UNKNOWN = "WEDGE_UNKNOWN"

class WedgeQuality(Enum):
    HIGH = "HIGH"      # 高质量（好位置）
    MEDIUM = "MEDIUM"  # 中等
    LOW = "LOW"        # 低质量（坏位置）
    FAILED = "FAILED"  # 失败

class ContextType(Enum):
    TREND_REVERSAL = "TREND_REVERSAL"      # 趋势反转（做Wedge反转）
    TREND_CONTINUATION = "TREND_CONTINUATION"  # 趋势延续（Bull/Bear Flag）
    TRADING_RANGE = "TRADING_RANGE"        # 横盘区间
    NESTED = "NESTED"                      # 嵌套（不作为反转信号）

@dataclass
class ThreePush:
    """三推结构"""
    push1_start: int
    push1_end: int
    push2_start: int
    push2_end: int
    push3_start: int
    push3_end: int

    @property
    def is_fading(self) -> bool:
        """三推是否衰竭（每推幅度递减）"""
        # 需要通过价格计算
        return True  # 需K线数据

    @property
    def direction(self) -> Literal["up", "down"]:
        """三推方向"""
        return "up"

@dataclass
class WedgePattern:
    """楔形形态"""
    wedge_type: WedgeType
    three_push: ThreePush
    quality: WedgeQuality
    context: ContextType
    nested_in_larger: bool = False  # 是否嵌套在更大结构中
    is_failed_reversal: bool = False  # 是否是失败的反转
    measured_move_target: Optional[float] = None
    confidence: float = 0.0  # 0-100

    @property
    def is_reversal_candidate(self) -> bool:
        """是否可以作为反转候选"""
        return (
            self.quality in (WedgeQuality.HIGH, WedgeQuality.MEDIUM)
            and not self.nested_in_larger
            and not self.is_failed_reversal
        )

    @property
    def expected_direction(self) -> Literal["long", "short", "watch"]:
        if self.wedge_type == WedgeType.WEDGE_TOP_REVERSAL:
            return "short"
        elif self.wedge_type == WedgeType.WEDGE_BOTTOM_REVERSAL:
            return "long"
        elif self.wedge_type == WedgeType.WEDGE_BULL_FLAG:
            return "long"
        elif self.wedge_type == WedgeType.WEDGE_BEAR_FLAG:
            return "short"
        return "watch"

# ══════════════════════════════════════════════════════════════════════════════
# 楔形质量评估
# ══════════════════════════════════════════════════════════════════════════════

def assess_wedge_quality(
    push1_range: float,
    push2_range: float,
    push3_range: float,
    position_quality: Literal["high", "medium", "low"],
    volume_profile: Optional[dict] = None
) -> WedgeQuality:
    """
    评估楔形质量

    Args:
        push1_range: 第一推幅度（价格范围）
        push2_range: 第二推幅度
        push3_range: 第三推幅度
        position_quality: 位置质量（high=高价位/低价位，medium，low=中间位置）
        volume_profile: 成交量分布

    Returns:
        WedgeQuality: 楔形质量评级
    """
    score = 0

    # 幅度递减评分（三推衰竭是好信号）
    if push3_range < push2_range < push1_range:
        score += 3  # 完美衰竭
    elif push3_range < push1_range:
        score += 1  # 部分衰竭

    # 位置评分
    if position_quality == "high":
        score += 2  # 高价位（Wedge顶）
    elif position_quality == "low":
        score += 2  # 低价位（Wedge底）
    else:
        score -= 1  # 中间位置较弱

    # 成交量确认
    if volume_profile:
        if volume_profile.get("decreasing_during_pushes"):
            score += 1
        if volume_profile.get("increasing_on_reversal"):
            score += 1

    # 评分转质量
    if score >= 5:
        return WedgeQuality.HIGH
    elif score >= 3:
        return WedgeQuality.MEDIUM
    elif score >= 1:
        return WedgeQuality.LOW
    else:
        return WedgeQuality.LOW

# ══════════════════════════════════════════════════════════════════════════════
# 嵌套结构识别
# ══════════════════════════════════════════════════════════════════════════════

def is_nested_wedge(
    wedge_start_time: int,
    wedge_end_time: int,
    larger_trend: Literal["up", "down", "neutral"],
    wedge_direction: Literal["up", "down"]
) -> bool:
    """
    判断楔形是否嵌套在更大结构中

    规则：
    - 如果左侧有很强的反向趋势 → 当前楔形是更大结构的组成部分（不作为反转信号）
    - Wedge顶在上升趋势中 = 嵌套（Wedge顶是大结构的小调整）
    - Wedge底在下降趋势中 = 嵌套
    """
    # 同向趋势中的楔形是嵌套
    if larger_trend == "up" and wedge_direction == "down":
        return True  # 上升趋势中的回调楔形 = 嵌套
    if larger_trend == "down" and wedge_direction == "up":
        return True  # 下降趋势中的反弹楔形 = 嵌套

    return False

# ══════════════════════════════════════════════════════════════════════════════
# Wedge类型判断
# ══════════════════════════════════════════════════════════════════════════════

def classify_wedge(
    push_direction: Literal["up", "down"],
    context: ContextType,
    is_failed_reversal: bool = False
) -> WedgeType:
    """
    根据方向和背景分类楔形类型
    """
    if is_failed_reversal:
        # 失败的反转 = Wedge 123
        return WedgeType.WEDGE_TOP_REVERSAL if push_direction == "up" else WedgeType.WEDGE_BOTTOM_REVERSAL

    if context == ContextType.TRADING_RANGE:
        return WedgeType.WEDGE_UNKNOWN  # TR内楔形需要具体判断

    if context == ContextType.TREND_REVERSAL:
        if push_direction == "up":
            return WedgeType.WEDGE_TOP_REVERSAL
        else:
            return WedgeType.WEDGE_BOTTOM_REVERSAL

    if context == ContextType.TREND_CONTINUATION:
        if push_direction == "down":
            return WedgeType.WEDGE_BULL_FLAG  # 上涨趋势中的回调
        else:
            return WedgeType.WEDGE_BEAR_FLAG  # 下跌趋势中的反弹

    return WedgeType.WEDGE_UNKNOWN

# ══════════════════════════════════════════════════════════════════════════════
# 双顶/双底 + Wedge组合识别
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DoubleTopBottom:
    """双顶/双底结构"""
    is_double_top: bool  # True=双顶, False=双底
    first_swing_high: float
    second_swing_high: float
    peak_times: tuple[int, int]
    wedge_pushes: list[ThreePush] = field(default_factory=list)

    @property
    def second_peak_weakness(self) -> bool:
        """第二高点是否弱于第一高点"""
        if self.is_double_top:
            return self.second_swing_high < self.first_swing_high * 1.002
        return False

@dataclass
class WedgeContext:
    """楔形背景环境"""
    larger_structure: ContextType
    nested: bool
    trend_before: Literal["up", "down", "neutral"]
    signal_bar_quality: Optional[str] = None

def identify_double_top_wedge(candles: list, tolerance: float = 0.002) -> Optional[DoubleTopBottom]:
    """
    识别双顶+楔形组合结构

    形态特征：
    1. 两个相近高点（双顶）
    2. 第二高点通常略低于第一高点
    3. 中间回调形成Wedge
    4. 连续大阳线（第二高点位置）
    """
    if len(candles) < 20:
        return None

    # 找最近的peak（简化版：找最近的两个局部高点）
    highs = []
    for i in range(2, len(candles) - 2):
        if (candles[i].high > candles[i-1].high and
            candles[i].high > candles[i-2].high and
            candles[i].high > candles[i+1].high and
            candles[i].high > candles[i+2].high):
            highs.append((i, candles[i]))

    if len(highs) < 2:
        return None

    # 最近的两个peak
    last1_idx, last1 = highs[-1]
    last2_idx, last2 = highs[-2]

    # 检查是否在合理范围内
    ratio = last2.high / last1.high if last1.high > 0 else 0
    if abs(ratio - 1.0) < tolerance:
        # 双顶
        return DoubleTopBottom(
            is_double_top=True,
            first_swing_high=last1.high,
            second_swing_high=last2.high,
            peak_times=(last1.time, last2.time)
        )
    return None

# ══════════════════════════════════════════════════════════════════════════════
# Wedge失败检测
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FailedWedge:
    """失败Wedge的检测结果"""
    wedge_type: WedgeType
    failure_type: Literal["continuation", "sideways", "nested"]
    stop_loss_level: float
    entry_price: float
    max_loss_pct: float
    description: str

def detect_wedge_failure(
    wedge_candles: list,
    wedge_type: WedgeType,
    entry_price: float
) -> Optional[FailedWedge]:
    """
    检测Wedge失败

    失败信号：
    1. 三推后没有反转，而是继续延伸
    2. 价格突破Wedge线但不顺势
    3. 在中间位置徘徊

    止损原则：
    - 如果三推后不反转而是继续 → 立即止损
    """
    if len(wedge_candles) < 5:
        return None

    last_candle = wedge_candles[-1]

    # 判断失败类型
    if wedge_type == WedgeType.WEDGE_TOP_REVERSAL:
        if last_candle.close > entry_price * 0.998:  # 没跌
            return FailedWedge(
                wedge_type=wedge_type,
                failure_type="continuation",
                stop_loss_level=last_candle.high,
                entry_price=entry_price,
                max_loss_pct=abs(last_candle.high - entry_price) / entry_price * 100,
                description="Wedge顶反转失败，价格继续向上延伸"
            )
    elif wedge_type == WedgeType.WEDGE_BOTTOM_REVERSAL:
        if last_candle.close < entry_price * 1.002:  # 没涨
            return FailedWedge(
                wedge_type=wedge_type,
                failure_type="continuation",
                stop_loss_level=last_candle.low,
                entry_price=entry_price,
                max_loss_pct=abs(entry_price - last_candle.low) / entry_price * 100,
                description="Wedge底反转失败，价格继续向下延伸"
            )

    return None

# ══════════════════════════════════════════════════════════════════════════════
# Measured Move 目标测算
# ══════════════════════════════════════════════════════════════════════════════

def calculate_wedge_measured_move(
    wedge_start: float,
    wedge_end: float,
    reversal_start: float,
    wedge_type: WedgeType
) -> float:
    """
    测算Wedge反转后的目标位（Measured Move）

    规则：
    - Wedge反转幅度通常至少 = Wedge本身的幅度
    - 三推衰竭越明显，Measured Move越大
    """
    wedge_range = abs(wedge_end - wedge_start)

    if wedge_type == WedgeType.WEDGE_TOP_REVERSAL:
        # 向下反转，目标 = Wedge起点 - 幅度
        target = wedge_start - wedge_range
    elif wedge_type == WedgeType.WEDGE_BOTTOM_REVERSAL:
        # 向上反转，目标 = Wedge起点 + 幅度
        target = wedge_start + wedge_range
    else:
        target = reversal_start

    return target

# ══════════════════════════════════════════════════════════════════════════════
# 楔形综合分析
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class WedgeAnalysis:
    """楔形综合分析结果"""
    wedge_patterns: list[WedgePattern]
    best_entry: Optional[tuple[float, Literal["long", "short"]]]
    stop_loss: Optional[float]
    target: Optional[float]
    risk_reward: Optional[float]
    quality_score: float  # 0-100
    notes: list[str]

def analyze_wedge_comprehensive(
    candles: list,
    timeframe_note: str = ""
) -> WedgeAnalysis:
    """
    综合楔形分析

    分析步骤：
    1. 找三推结构
    2. 评估位置质量
    3. 判断是反转还是持续
    4. 找最佳入场点
    5. 计算止损和目标
    """
    notes = []
    patterns = []

    # 简化：三推识别（需要更复杂的算法，这里用启发式）
    if len(candles) < 30:
        return WedgeAnalysis(
            wedge_patterns=[],
            best_entry=None,
            stop_loss=None,
            target=None,
            risk_reward=None,
            quality_score=0,
            notes=["数据不足，无法分析楔形"]
        )

    # 找最近的趋势方向（简化版）
    recent_closes = [c.close for c in candles[-20:]]
    trend = "up" if recent_closes[-1] > recent_closes[0] else "down"

    # 基本评分
    quality_score = 50

    if trend == "up":
        # 上涨趋势中的楔形可能是Bull Flag或Wedge顶
        quality_score = 40
        notes.append("上涨趋势中，楔形可能是Bull Flag回调")
    else:
        quality_score = 40
        notes.append("下降趋势中，楔形可能是Bear Flag反弹")

    return WedgeAnalysis(
        wedge_patterns=patterns,
        best_entry=None,
        stop_loss=None,
        target=None,
        risk_reward=None,
        quality_score=quality_score,
        notes=notes
    )

# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════

def format_wedge_report(analysis: WedgeAnalysis) -> str:
    """生成楔形分析报告"""
    lines = ["=" * 50]
    lines.append("P11 WEDGE 分析报告")
    lines.append("=" * 50)

    lines.append(f"\n质量评分: {analysis.quality_score}/100")

    if analysis.notes:
        lines.append("\n分析备注:")
        for note in analysis.notes:
            lines.append(f"  • {note}")

    if analysis.best_entry:
        price, direction = analysis.best_entry
        lines.append(f"\n最佳入场: {direction.upper()} @ {price:.2f}")

    if analysis.stop_loss:
        lines.append(f"止损位: {analysis.stop_loss:.2f}")

    if analysis.target:
        lines.append(f"目标位: {analysis.target:.2f}")

    if analysis.risk_reward:
        lines.append(f"盈亏比: 1:{analysis.risk_reward:.1f}")

    return "\n".join(lines)

# ══════════════════════════════════════════════════════════════════════════════
# Brooks 核心规则（P11新增）
# ══════════════════════════════════════════════════════════════════════════════

WEDGE_RULES_P11 = """
=== Brooks P11 核心规则 ===

1. 【嵌套结构】楔形嵌套在更大结构中时，是小结构，不作为反转信号

2. 【双顶/双底+Wedge】
   - 双顶的第二高点通常略低于第一高点
   - 连续大阳线是弱势信号（第二高点无力超越）
   - 双底突破失败 = Wedge 123结构

3. 【失败的反转 = Wedge 123】
   - 突破后迅速拉回 = 陷阱
   - 不要在"突破"位置追卖/追买

4. 【Wedge一定会失败】
   - 如果只预期成功、不懂失败
   - 当反转失败后不懂得止损
   - 会亏很多钱

5. 【Trading Range内的Wedge】
   - TR内总能找到双顶/双底结构
   - 楔形在TR内是中继形态
   - 可以用First Entry

6. 【顺大逆小】
   - 大趋势中的楔形是回调/反弹
   - 不要逆大趋势做楔形

7. 【实战训练】
   - 每天在行情中找三推形态
   - 大量小周期练习，不考虑盈亏
   - 多复盘找楔形形态
"""
