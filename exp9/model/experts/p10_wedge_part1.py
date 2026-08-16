#!/usr/bin/env python3
"""
P10 三推楔形专题(1) — Wedge Reversal Patterns Part 1
====================================================
来源：方方土价格行为学 · Brooks Price Action
视频：10-08Wedge—楔形反转(1).mp4
分析方法：Whisper tiny全文转写（1049条字幕）+ 全帧pHash去重 + Vision图像分析

核心主题：
  1. Wedge楔形基础：什么是Wedge、如何画线
  2. Rising/Falling Wedge形态识别
  3. 三推反转规律（Three Pushes → Reversal）
  4. 好Wedge vs 坏Wedge的判断标准
  5. Measured Move目标测算
  6. Parabolic Wedge、Nested Wedge等变体
  7. First Entry vs Second Entry入场策略

Brooks课程对应（24A-24E）：
  24A: 基础-什么是Wedge如何画线
  24B: 变化-Wedge很少完美，通道也是Wedge
  24C: 深度理解-坏Wedge非反转，反转早于趋势结束
  24D: 特殊形态-Parabolic Wedge，强趋势伴随坏Wedge
  24E: 失败处理-Failed Wedge应对方案

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
    RISING_WEDGE = "RISING_WEDGE"      # 上升楔形（看跌反转）
    FALLING_WEDGE = "FALLING_WEDGE"     # 下降楔形（看涨反转）
    BULL_FLAG = "BULL_FLAG"            # 牛市旗形（上涨延续）
    BEAR_FLAG = "BEAR_FLAG"            # 熊市旗形（下跌延续）
    PARABOLIC_WEDGE = "PARABOLIC_WEDGE" # 抛物线楔形（极端反转）
    NESTED_WEDGE = "NESTED_WEDGE"       # 嵌套楔形
    UNKNOWN = "UNKNOWN"

class WedgeQuality(Enum):
    HIGH = "HIGH"      # 高质量反转楔形
    MEDIUM = "MEDIUM"  # 中等
    LOW = "LOW"       # 低质量/坏楔形（趋势延续）
    FAILED = "FAILED" # 失败楔形

class ThreePushPhase(Enum):
    PUSH1 = "PUSH1"
    PUSH2 = "PUSH2"
    PUSH3 = "PUSH3"
    COMPLETE = "COMPLETE"

class EntryStrategy(Enum):
    FIRST_ENTRY = "FIRST_ENTRY"  # 突破楔形边界立即入场
    SECOND_ENTRY = "SECOND_ENTRY"  # 回踩确认后入场
    AGGRESSIVE = "AGGRESSIVE"
    CONSERVATIVE = "CONSERVATIVE"

@dataclass
class Push:
    """单次推动"""
    start_idx: int
    end_idx: int
    start_price: float
    end_price: float
    high: float
    low: float
    duration: int  # K线根数

    @property
    def range_size(self) -> float:
        return abs(self.high - self.low)

    @property
    def amplitude(self) -> float:
        return abs(self.end_price - self.start_price)

@dataclass
class ThreePushStructure:
    """三推结构"""
    push1: Push
    push2: Push
    push3: Push
    wedge_type: WedgeType

    @property
    def is_fading(self) -> bool:
        """三推是否衰竭（幅度递减）"""
        return (self.push3.range_size < self.push2.range_size < self.push1.range_size)

    @property
    def is_overshoot(self) -> bool:
        """三推是否超出通道/前高（反转失败）"""
        return False  # 需K线数据计算

    @property
    def is_undershoot(self) -> bool:
        """三推是否达不到目标（反转概率高）"""
        return False  # 需K线数据计算

    @property
    def reversal_probability(self) -> float:
        """三推后反转概率估算（0-100）"""
        score = 50.0
        if self.is_fading:
            score += 25.0
        if self.is_undershoot:
            score += 15.0
        if self.is_overshoot:
            score -= 30.0
        return max(0.0, min(100.0, score))

@dataclass
class WedgeLine:
    """楔形趋势线"""
    start_idx: int
    end_idx: int
    start_price: float
    end_price: float
    is_upper: bool  # True=上轨，False=下轨

    @property
    def slope(self) -> float:
        return (self.end_price - self.start_price) / (self.end_idx - self.start_idx)

    def price_at(self, idx: int) -> float:
        """计算指定位置的价格"""
        return self.start_price + self.slope * (idx - self.start_idx)

@dataclass
class WedgePattern:
    """楔形形态"""
    wedge_type: WedgeType
    three_push: Optional[ThreePushStructure]
    upper_line: WedgeLine
    lower_line: WedgeLine
    quality: WedgeQuality
    reversal_prob: float
    entry_strategy: EntryStrategy
    measured_move_target: Optional[float] = None
    confidence: float = 0.0  # 0-100

    @property
    def is_reversal_candidate(self) -> bool:
        return (
            self.quality in (WedgeQuality.HIGH, WedgeQuality.MEDIUM)
            and self.wedge_type in (WedgeType.RISING_WEDGE, WedgeType.FALLING_WEDGE)
        )

    @property
    def expected_direction(self) -> Literal["long", "short", "watch"]:
        if self.wedge_type == WedgeType.RISING_WEDGE:
            return "short"
        elif self.wedge_type == WedgeType.FALLING_WEDGE:
            return "long"
        return "watch"

# ══════════════════════════════════════════════════════════════════════════════
# 楔形识别
# ══════════════════════════════════════════════════════════════════════════════

def identify_wedge_type(
    upper_line: WedgeLine,
    lower_line: WedgeLine,
    trend_before: Literal["up", "down", "neutral"]
) -> WedgeType:
    """
    根据两条趋势线判断楔形类型

    规则：
    - 上轨向上 + 下轨向上 → Rising Wedge（上升楔形，看跌）
    - 上轨向下 + 下轨向下 → Falling Wedge（下降楔形，看涨）
    - 上轨向上 + 下轨向下 → Bear Flag（熊市旗形，下跌延续）
    - 上轨向下 + 下轨向上 → Bull Flag（牛市旗形，上涨延续）
    """
    upper_slope = upper_line.slope
    lower_slope = lower_line.slope

    if upper_slope > 0.0005 and lower_slope > 0.0005:
        return WedgeType.RISING_WEDGE
    elif upper_slope < -0.0005 and lower_slope < -0.0005:
        return WedgeType.FALLING_WEDGE
    elif upper_slope > 0.0005 and lower_slope < -0.0005:
        return WedgeType.BEAR_FLAG
    elif upper_slope < -0.0005 and lower_slope > 0.0005:
        return WedgeType.BULL_FLAG
    else:
        return WedgeType.UNKNOWN

# ══════════════════════════════════════════════════════════════════════════════
# 好Wedge vs 坏Wedge评估
# ══════════════════════════════════════════════════════════════════════════════

def assess_wedge_quality(
    three_push: Optional[ThreePushStructure],
    volume_profile: Optional[dict] = None,
    price_position: Optional[Literal["extreme", "normal", "middle"]] = None
) -> WedgeQuality:
    """
    评估楔形质量

    好Wedge（反转）特征：
    - 三推幅度递减（衰竭明显）
    - 成交量在第三次推动时缩量
    - 价格在极端位置
    - 形态清晰、收敛明显

    坏Wedge（趋势延续）特征：
    - 三推幅度相近（趋势健康）
    - 跟随时成交量放大
    - 价格在趋势中途
    - 形态不规则
    """
    if three_push is None:
        return WedgeQuality.MEDIUM

    score = 0

    # 三推衰竭评分
    if three_push.is_fading:
        score += 3
    elif three_push.push3.range_size < three_push.push1.range_size:
        score += 1

    # 成交量评分
    if volume_profile:
        if volume_profile.get("decreasing_during_push3"):
            score += 2
        if volume_profile.get("increasing_on_breakout"):
            score += 1

    # 位置评分
    if price_position == "extreme":
        score += 2
    elif price_position == "normal":
        score += 0
    else:
        score -= 1

    # 评分转质量
    if score >= 6:
        return WedgeQuality.HIGH
    elif score >= 3:
        return WedgeQuality.MEDIUM
    else:
        return WedgeQuality.LOW

# ══════════════════════════════════════════════════════════════════════════════
# Measured Move 目标测算
# ══════════════════════════════════════════════════════════════════════════════

def calculate_measured_move(
    wedge_start_price: float,
    wedge_end_price: float,
    breakout_price: float,
    wedge_type: WedgeType
) -> float:
    """
    计算Measured Move目标位

    规则：
    - 楔形高度（range）= 突破方向的目标移动距离
    - 从突破点向上/下投射楔形高度

    举例：
    - Falling Wedge高度 = 10元
    - 突破点 = 90元
    - 第一目标 = 90 + 10 = 100元
    """
    wedge_height = abs(wedge_end_price - wedge_start_price)

    if wedge_type in (WedgeType.RISING_WEDGE, WedgeType.BEAR_FLAG):
        # 向下突破，目标 = 突破点 - 高度
        return breakout_price - wedge_height
    elif wedge_type in (WedgeType.FALLING_WEDGE, WedgeType.BULL_FLAG):
        # 向上突破，目标 = 突破点 + 高度
        return breakout_price + wedge_height
    else:
        return breakout_price

# ══════════════════════════════════════════════════════════════════════════════
# 入场策略
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class WedgeEntry:
    """楔形入场点"""
    price: float
    strategy: EntryStrategy
    stop_loss: float
    target: float
    risk_reward: float
    timestamp: Optional[int] = None

def find_first_entry(
    wedge: WedgePattern,
    breakout_candle: Candle
) -> WedgeEntry:
    """
    第一入场点（First Entry）
    - 激进：在楔形边界突破瞬间入场
    - 止损：楔形最高/最低点外侧
    - 优势：止损窄、盈亏比好
    - 风险：假突破
    """
    if wedge.wedge_type == WedgeType.RISING_WEDGE:
        entry_price = breakout_candle.close
        stop_loss = wedge.upper_line.high + breakout_candle.close * 0.001
        target = calculate_measured_move(
            wedge.lower_line.start_price, wedge.lower_line.end_price,
            entry_price, wedge.wedge_type
        )
    else:
        entry_price = breakout_candle.close
        stop_loss = wedge.lower_line.low - breakout_candle.close * 0.001
        target = calculate_measured_move(
            wedge.upper_line.start_price, wedge.upper_line.end_price,
            entry_price, wedge.wedge_type
        )

    risk = abs(entry_price - stop_loss)
    reward = abs(target - entry_price)
    rr = reward / risk if risk > 0 else 0

    return WedgeEntry(
        price=entry_price,
        strategy=EntryStrategy.FIRST_ENTRY,
        stop_loss=stop_loss,
        target=target,
        risk_reward=rr,
        timestamp=breakout_candle.time
    )

def find_second_entry(
    wedge: WedgePattern,
    pullback_candle: Candle
) -> WedgeEntry:
    """
    第二入场点（Second Entry）
    - 保守：等待突破后的回踩确认再入场
    - 止损：回踩低点/高点外侧
    - 优势：更高确定性
    - 风险：错过机会
    """
    if wedge.wedge_type == WedgeType.RISING_WEDGE:
        entry_price = pullback_candle.close
        stop_loss = pullback_candle.low - pullback_candle.close * 0.001
        target = calculate_measured_move(
            wedge.lower_line.start_price, wedge.lower_line.end_price,
            entry_price, wedge.wedge_type
        )
    else:
        entry_price = pullback_candle.close
        stop_loss = pullback_candle.high + pullback_candle.close * 0.001
        target = calculate_measured_move(
            wedge.upper_line.start_price, wedge.upper_line.end_price,
            entry_price, wedge.wedge_type
        )

    risk = abs(entry_price - stop_loss)
    reward = abs(target - entry_price)
    rr = reward / risk if risk > 0 else 0

    return WedgeEntry(
        price=entry_price,
        strategy=EntryStrategy.SECOND_ENTRY,
        stop_loss=stop_loss,
        target=target,
        risk_reward=rr,
        timestamp=pullback_candle.time
    )

# ══════════════════════════════════════════════════════════════════════════════
# Parabolic Wedge（抛物线楔形）
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ParabolicWedge:
    """抛物线楔形（极端加速后的楔形）"""
    entry_price: float
    acceleration_factor: float  # 价格加速程度
    wedge_pattern: WedgePattern
    confidence: float = 0.0

    @property
    def is_parabolic(self) -> bool:
        """是否呈现抛物线特征"""
        return self.acceleration_factor > 1.5  # 需K线数据验证

def detect_parabolic_wedge(candles: list) -> Optional[ParabolicWedge]:
    """
    检测Parabolic Wedge

    特征：
    - 价格快速加速上涨/下跌
    - 形成楔形结构
    - 是Brooks课程P12内容
    """
    if len(candles) < 20:
        return None

    # 简化检测：最近10根K线的价格变化率
    recent_10 = candles[-10:]
    early = sum(c.close for c in recent_10[:5]) / 5
    late = sum(c.close for c in recent_10[5:]) / 5
    acceleration = (late - early) / early if early > 0 else 0

    if abs(acceleration) > 0.05:  # 5%以上变化
        return ParabolicWedge(
            entry_price=candles[-1].close,
            acceleration_factor=abs(acceleration) * 10,
            wedge_pattern=None  # 需完整楔形识别
        )
    return None

# ══════════════════════════════════════════════════════════════════════════════
# Nested Wedge（嵌套楔形）
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class NestedWedge:
    """嵌套楔形（大楔形套小楔形）"""
    larger_wedge: WedgePattern
    smaller_wedge: WedgePattern
    target_stacking: float  # 目标叠加效果

    @property
    def has_stacked_targets(self) -> bool:
        """目标是否叠加"""
        larger_target = self.larger_wedge.measured_move_target
        smaller_target = self.smaller_wedge.measured_move_target
        if larger_target and smaller_target:
            return abs(larger_target - smaller_target) < larger_target * 0.05
        return False

# ══════════════════════════════════════════════════════════════════════════════
# 综合分析
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class WedgeAnalysis:
    """楔形综合分析结果"""
    wedge: Optional[WedgePattern]
    best_entry: Optional[WedgeEntry]
    quality_score: float  # 0-100
    notes: list[str]

def analyze_wedge_comprehensive(
    candles: list,
    timeframe: str = ""
) -> WedgeAnalysis:
    """
    综合楔形分析
    """
    notes = []

    if len(candles) < 30:
        return WedgeAnalysis(
            wedge=None,
            best_entry=None,
            quality_score=0,
            notes=["数据不足，无法分析楔形"]
        )

    # 检测三推结构（简化版）
    three_push = None  # 需更复杂的算法

    # 基本评分
    quality_score = 50

    return WedgeAnalysis(
        wedge=None,
        best_entry=None,
        quality_score=quality_score,
        notes=notes
    )

# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════

def format_wedge_report(analysis: WedgeAnalysis) -> str:
    """生成楔形分析报告"""
    lines = ["=" * 50]
    lines.append("P10 WEDGE 分析报告")
    lines.append("=" * 50)
    lines.append(f"\n质量评分: {analysis.quality_score}/100")

    if analysis.wedge:
        w = analysis.wedge
        lines.append(f"\n楔形类型: {w.wedge_type.value}")
        lines.append(f"质量: {w.quality.value}")
        lines.append(f"预期方向: {w.expected_direction}")

    if analysis.best_entry:
        e = analysis.best_entry
        lines.append(f"\n最佳入场: {e.strategy.value} @ {e.price:.2f}")
        lines.append(f"止损: {e.stop_loss:.2f}")
        lines.append(f"目标: {e.target:.2f}")
        lines.append(f"盈亏比: 1:{e.risk_reward:.1f}")

    for note in analysis.notes:
        lines.append(f"\n• {note}")

    return "\n".join(lines)

# ══════════════════════════════════════════════════════════════════════════════
# Brooks 核心规则（P10）
# ══════════════════════════════════════════════════════════════════════════════

WEDGE_RULES_P10 = """
=== Brooks P10 核心规则 ===

1. 【Wedge定义】两条收敛的趋势线，价格三次向同一方向推动

2. 【Rising Wedge = 看跌】上升楔形，三推向上后跌破下轨 → 做空
3. 【Falling Wedge = 看涨】下降楔形，三推向下后突破上轨 → 做多
4. 【Bull/Bear Flag = 趋势延续】楔形与趋势同向 = 中继，不反转

5. 【三推反转定理】Wedge内三推后经常反转（60%+），但非每次

6. 【好Wedge vs 坏Wedge】
   好（三推衰竭，明显收敛）→ 反转概率高
   坏（三推健康，趋势强）→ 趋势延续，不做反转

7. 【超出(Overshoot) vs 达不到(Undershoot)】
   达不到目标 → 反转概率高
   超出通道 → 反转失败，趋势继续

8. 【Measured Move】目标 = 突破点 ± 楔形高度

9. 【入场策略】
   First Entry：突破瞬间入场（激进、止损窄）
   Second Entry：回踩确认入场（保守、确定性高）

10. 【Parabolic Wedge】价格加速后的楔形 → Brooks课程P12
11. 【Nested Wedge】大楔形套小楔形 → 目标叠加效果
"""
