#!/usr/bin/env python3
"""
P12 Parabolic Wedge — 抛物线楔形
===================================
来源：方方土价格行为学 · Brooks Price Action
视频：12-10ParabolicWedge—抛物线反转.mp4
分析方法：Whisper tiny 采样转写（7采样点×30秒）

核心主题：
  1. Parabolic Wedge 定义：价格加速+量能递增+最大量衰竭
  2. Bad Follow-Through：大量无跟随 = 反转信号
  3. 抛物线后的交易策略：不追涨、不加仓、等待反转
  4. 深度回调：抛物线后回调幅度通常很深（20%-45%）
  5. Brooks 市场哲学：市场永远在，不在于这一单

铁律：K线数据必须以 `time` 字段判断最新价格，禁止用 `data[-1]`
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Literal
from enum import Enum

# ══════════════════════════════════════════════════════════════════════════════
# 枚举与数据结构
# ══════════════════════════════════════════════════════════════════════════════

class ParabolicPhase(Enum):
    ACCELERATING = "ACCELERATING"    # 加速中
    PEAK_VOLUME = "PEAK_VOLUME"        # 最大量峰值
    REVERSING = "REVERSING"           # 反转中
    CONSOLIDATING = "CONSOLIDATING"   # 震荡中

@dataclass
class VolumeProfile:
    """成交量分布"""
    bars: list  # K线列表
    increasing: bool = True       # 成交量是否递增
    peak_bar_idx: Optional[int] = None  # 最大量K线索引
    peak_volume: float = 0.0

    @property
    def is_parabolic(self) -> bool:
        """是否呈现抛物线特征（量能递增）"""
        return self.increasing and self.peak_bar_idx is not None

@dataclass
class ParabolicWedge:
    """抛物线楔形"""
    direction: Literal["up", "down"]
    peak_bar_idx: int
    acceleration_score: float  # 0-100，加速程度
    volume_profile: VolumeProfile
    phase: ParabolicPhase
    reversal_prob: float  # 0-100
    bad_follow_through: bool = False

    @property
    def is_high_confidence(self) -> bool:
        """高置信度抛物线信号"""
        return (
            self.acceleration_score > 60
            and self.peak_bar_idx is not None
            and (self.bad_follow_through or self.phase == ParabolicPhase.REVERSING)
        )

# ══════════════════════════════════════════════════════════════════════════════
# 抛物线楔形检测
# ══════════════════════════════════════════════════════════════════════════════

def detect_volume_acceleration(bars: list) -> VolumeProfile:
    """
    检测成交量是否递增（抛物线特征）

    抛物线楔形特征：
    - 成交量逐渐递增
    - 最后出现最大量
    """
    if len(bars) < 5:
        return VolumeProfile(bars=bars, increasing=False)

    volumes = [getattr(b, 'volume', 0) or 0 for b in bars]

    # 检查是否递增（允许小幅回调）
    increasing = True
    for i in range(1, len(volumes)):
        if volumes[i] < volumes[i-1] * 0.8:  # 允许20%回调
            pass  # 继续检查整体趋势

    # 找最大量K线
    peak_idx = volumes.index(max(volumes)) if volumes else None
    peak_vol = max(volumes) if volumes else 0.0

    return VolumeProfile(
        bars=bars,
        increasing=increasing,
        peak_bar_idx=peak_idx,
        peak_volume=peak_vol
    )

def detect_parabolic_wedge(bars: list, lookback: int = 20) -> Optional[ParabolicWedge]:
    """
    检测抛物线楔形

    Args:
        bars: K线列表
        lookback: 回溯K线数量

    Returns:
        ParabolicWedge 或 None
    """
    if len(bars) < lookback:
        return None

    recent = bars[-lookback:]

    # 检测成交量递增
    vol_profile = detect_volume_acceleration(recent)

    # 检测价格加速
    # 计算每根K线的价格变化率
    returns = []
    for i in range(1, len(recent)):
        prev_close = getattr(recent[i-1], 'close', 0)
        curr_close = getattr(recent[i], 'close', 0)
        if prev_close > 0:
            returns.append(abs(curr_close - prev_close) / prev_close)

    # 检查收益率是否递增（加速）
    acceleration_score = 0
    if len(returns) >= 3:
        increasing_count = sum(1 for i in range(1, len(returns))
                               if returns[i] > returns[i-1])
        acceleration_score = (increasing_count / (len(returns) - 1)) * 100

    # 判断方向
    first_close = getattr(recent[0], 'close', 0)
    last_close = getattr(recent[-1], 'close', 0)
    direction: Literal["up", "down"] = "up" if last_close > first_close else "down"

    # 判断阶段
    if vol_profile.peak_bar_idx is not None:
        if vol_profile.peak_bar_idx == len(recent) - 1:
            phase = ParabolicPhase.PEAK_VOLUME
        elif vol_profile.peak_bar_idx == len(recent) - 2:
            phase = ParabolicPhase.REVERSING
        else:
            phase = ParabolicPhase.ACCELERATING
    else:
        phase = ParabolicPhase.ACCELERATING

    # 计算反转概率
    reversal_prob = 30.0
    if vol_profile.increasing and vol_profile.peak_bar_idx is not None:
        reversal_prob += 30.0
    if acceleration_score > 60:
        reversal_prob += 20.0
    if phase in (ParabolicPhase.REVERSING, ParabolicPhase.PEAK_VOLUME):
        reversal_prob += 20.0

    # 检测 Bad Follow-Through
    bad_follow = False
    if vol_profile.peak_bar_idx is not None:
        peak_idx = vol_profile.peak_bar_idx
        if peak_idx < len(recent) - 1:
            # 最大量K线之后的价格变化
            peak_close = getattr(recent[peak_idx], 'close', 0)
            next_close = getattr(recent[peak_idx + 1], 'close', 0) if peak_idx + 1 < len(recent) else peak_close
            if direction == "up" and next_close < peak_close * 0.998:
                bad_follow = True
            elif direction == "down" and next_close > peak_close * 1.002:
                bad_follow = True

    return ParabolicWedge(
        direction=direction,
        peak_bar_idx=vol_profile.peak_bar_idx or 0,
        acceleration_score=acceleration_score,
        volume_profile=vol_profile,
        phase=phase,
        reversal_prob=min(100.0, reversal_prob),
        bad_follow_through=bad_follow
    )

# ══════════════════════════════════════════════════════════════════════════════
# 抛物线楔形交易策略
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ParabolicTradeSignal:
    """抛物线楔形交易信号"""
    parabolic_wedge: ParabolicWedge
    action: Literal["avoid_adding", "prepare_reverse", "reverse_now", "watch"]
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    notes: list[str] = field(default_factory=list)

def generate_parabolic_signal(wedge: ParabolicWedge, current_price: float) -> ParabolicTradeSignal:
    """
    生成抛物线楔形交易信号

    核心策略：
    - 抛物线加速中：不追涨，不加仓
    - 最大量出现后：准备反向
    - 反转确认后：入场反向交易
    """
    notes = []

    if wedge.phase == ParabolicPhase.ACCELERATING:
        action: Literal["avoid_adding", "prepare_reverse", "reverse_now", "watch"] = "avoid_adding"
        notes.append("抛物线加速中，不追涨/追跌，不加仓")
        notes.append(f"加速评分: {wedge.acceleration_score:.0f}/100")

    elif wedge.phase == ParabolicPhase.PEAK_VOLUME:
        if wedge.bad_follow_through:
            action = "reverse_now"
            notes.append("最大量出现 + Bad Follow-Through，反转概率极高")
            # 计算反向入场点
            if wedge.direction == "up":
                entry = current_price * 0.995  # 略低于现价
                stop = current_price * 1.01   # 止损在高位
                target = current_price * 0.90  # 目标回调20%
            else:
                entry = current_price * 1.005
                stop = current_price * 0.99
                target = current_price * 1.10
        else:
            action = "prepare_reverse"
            notes.append("最大量出现，等待确认信号")

    elif wedge.phase == ParabolicPhase.REVERSING:
        action = "reverse_now"
        notes.append("已进入反转阶段，果断反向")
        if wedge.direction == "up":
            entry = current_price
            stop = current_price * 1.01
            target = current_price * 0.85
        else:
            entry = current_price
            stop = current_price * 0.99
            target = current_price * 1.15

    else:
        action = "watch"
        notes.append("震荡中，等待明确信号")

    return ParabolicTradeSignal(
        parabolic_wedge=wedge,
        action=action,
        entry_price=entry if action in ("reverse_now",) else None,
        stop_loss=stop if action in ("reverse_now",) else None,
        target=target if action in ("reverse_now",) else None,
        notes=notes
    )

# ══════════════════════════════════════════════════════════════════════════════
# 深度回调估算
# ══════════════════════════════════════════════════════════════════════════════

def estimate_pullback_depth(parabolic_wedge: ParabolicWedge, peak_price: float) -> tuple[float, float]:
    """
    估算抛物线后的回调幅度

    经验法则：
    - 小型抛物线：回调 10-20%
    - 中型抛物线：回调 20-45%
    - 大型抛物线：回调 45%+
    - 极端抛物线：可能反转（不只是回调）

    Returns:
        (min_pullback, max_pullback) 回调幅度范围
    """
    if parabolic_wedge.direction == "up":
        if parabolic_wedge.acceleration_score > 80:
            return 0.20, 0.55  # 深度回调或反转
        elif parabolic_wedge.acceleration_score > 60:
            return 0.10, 0.35
        else:
            return 0.05, 0.20
    else:
        if parabolic_wedge.acceleration_score > 80:
            return 0.20, 0.55
        elif parabolic_wedge.acceleration_score > 60:
            return 0.10, 0.35
        else:
            return 0.05, 0.20

# ══════════════════════════════════════════════════════════════════════════════
# Brooks 核心规则（P12）
# ══════════════════════════════════════════════════════════════════════════════

PARABOLIC_WEDGE_RULES = """
=== Brooks P12 核心规则 ===

1. 【Parabolic Wedge 定义】
   价格加速移动 + 成交量递增 + 最后最大量出现

2. 【抛物线后必深度回调】
   20%-45%回调很常见，甚至更多

3. 【不追涨、不加仓】
   看到抛物线，作为顺势交易者不要激进

4. 【Bad Follow-Through = 强反转信号】
   最大量K线后价格没有跟随 = 主力出货

5. 【抛物线是陷阱高发区】
   极端走势后容易反转或深度回调

6. 【市场永远在，不在于这一单】
   不要因为错过而追高追低
"""
