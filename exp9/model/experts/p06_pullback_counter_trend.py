#!/usr/bin/env python3
"""
P06 回调&数K线(2)-逆势交易者离场 — 专家决策规则库
================================================
来源：方方土价格行为学 · 逆势交易者离场
视频：06-04回调&数K线(2)-逆势交易者离场
分析方法：Whisper字幕(20min) + Vision分析(5场景)

核心主题：
  1. 逆势交易者离场时机：市场第二次反对时
  2. 历史教育者原则：允许市场反对一次，但第二次必须离场
  3. H1信号：逆势交易者的"逃命信号"
  4. 失败的双顶/双底反转：短止损被挤压
  5. 缺口：既是目标位也是支撑
  6. 数K线在高位的应用：第二次尝试延续趋势
  7. 止损位置的选择：空头在34上方一个TICK离场
  8. 市场惯性：延续已有趋势
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum
import math

# ══════════════════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════════════════

class Direction(Enum):
    LONG  = "LONG"
    SHORT = "SHORT"
    WATCH = "WATCH"
    NONE  = "NONE"

class Signal(Enum):
    # 基础信号
    H1 = "H1买入信号"        # 第一次高点抬高
    H2 = "H2买入信号"        # 第二次高点抬高
    H3 = "H3反转信号"        # 第三次失败
    L1 = "L1卖出信号"        # 第一次低点降低
    L2 = "L2卖出信号"        # 第二次低点降低
    L3 = "L3反转信号"        # 第三次失败
    # 逆势离场信号
    COUNTER_TREND_WARN_1 = "第一次警告（允许继续持有）"
    COUNTER_TREND_WARN_2 = "第二次警告（必须离场）"
    DOUBLE_TOP_FAIL      = "双顶失败（空头被挤压）"
    DOUBLE_BOTTOM_FAIL   = "双底失败（多头被挤压）"
    # 缺口信号
    GAP_AS_TARGET       = "缺口目标位"
    GAP_AS_SUPPORT       = "缺口支撑位"
    GAP_REJECTION        = "缺口处反转"
    # 其他
    TREND_EXHAUSTION     = "趋势衰竭"
    SECOND_PUSH_FAIL     = "第二推失败"
    NONE                 = "无信号"

@dataclass
class PullbackResult:
    signal: Signal = Signal.NONE
    direction: Direction = Direction.WATCH
    confidence: str = "低"
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    reasons: list[str] = field(default_factory=list)

@dataclass
class Bar:
    """单根K线数据结构"""
    time: str           # 时间戳（ISO格式，用于定位最新价格）
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

# ══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════════════

def get_latest_bar(bars: List[Bar]) -> Bar:
    """以time字段找到最新一根K线（禁止用data[-1]）"""
    if not bars:
        raise ValueError("bars列表为空")
    return max(bars, key=lambda b: b.time)

def get_latest_price(bars: List[Bar]) -> float:
    """以time字段获取最新价格"""
    return get_latest_bar(bars).close

def get_latest_high(bars: List[Bar]) -> float:
    """以time字段获取最新高点"""
    return get_latest_bar(bars).high

def get_latest_low(bars: List[Bar]) -> float:
    """以time字段获取最新低点"""
    return get_latest_bar(bars).low

def is_bullish_bar(bar: Bar) -> bool:
    return bar.close > bar.open

def is_bearish_bar(bar: Bar) -> bool:
    return bar.close < bar.open

def is_gap_bar(bar1: Bar, bar2: Bar, direction: str = "up") -> bool:
    """
    判断是否形成缺口
    direction='up': bar2低点是bar1高点的上方（向上跳空）
    direction='down': bar2高点是bar1低点的下方（向下跳空）
    """
    if direction == "up":
        return bar2.low > bar1.high
    else:
        return bar2.high < bar1.low

# ══════════════════════════════════════════════════════════════════════════════
# 核心规则库
# ══════════════════════════════════════════════════════════════════════════════

# ── 规则1：历史教育者原则 ────────────────────────────────────────
RULE_HISTORICAL_EducATOR = {
    "name": "历史教育者原则",
    "description": (
        "逆势交易者（历史教育者）可以允许市场反对他们一次，"
        "但当市场第二次对他们发出警告时，他们必须离场保护自己。"
    ),
    "first_warning": {
        "description": "第一次尝试延续趋势（H1/L1）",
        "action": "逆势交易者可以继续持有，观察",
    },
    "second_warning": {
        "description": "第二次尝试延续趋势（H2/L2）",
        "action": "逆势交易者必须离场",
        "signal": "市场对逆势交易者的第二次警告",
    },
}

# ── 规则2：H1信号作为逆势离场点 ────────────────────────────────
RULE_H1_EXIT = {
    "name": "H1/L1作为逆势交易者离场信号",
    "bull_context": {
        "description": "在下跌趋势中，逆势做多的交易者",
        "exit_signal": "出现H1（第一次高点抬高）= 多头必须离场",
    },
    "bear_context": {
        "description": "在上涨趋势中，逆势做空的交易者",
        "exit_signal": "出现L1（第一次低点降低）= 空头必须离场",
    },
    "h1_entry": "H1入场 = Buy Stop在信号K线高点上方1 tick",
    "counter_trend_stop": "止损 = 离场点（H1被突破时）",
}

# ── 规则3：失败的双顶/双底 ──────────────────────────────────────
RULE_FAILED_DOUBLE_TOP_BOTTOM = {
    "name": "失败的双顶/双底",
    "double_top_fail": {
        "description": "双顶形态未能向下突破，反而向上突破",
        "mechanism": "空头在双顶下方挂止损做空，被止损挤压后推动价格上涨",
        "signal": "DOUBLE_TOP_FAIL → 极强买入信号",
        "gap_note": "缺口既是目标位也是支撑（Gap as target & support）",
    },
    "double_bottom_fail": {
        "description": "双底形态未能向上突破，反而向下突破",
        "mechanism": "多头在双底上方挂止损做多，被止损挤压后推动价格下跌",
        "signal": "DOUBLE_BOTTOM_FAIL → 极强卖出信号",
    },
}

# ── 规则4：缺口的双重角色 ────────────────────────────────────────
RULE_GAP_DUAL_ROLE = {
    "name": "缺口的双重角色",
    "as_target": {
        "description": "价格向缺口方向运动时，缺口成为目标位",
        "gap_down": "向下缺口 → 目标位 = 缺口下沿",
    },
    "as_support": {
        "description": "价格到达缺口后，缺口成为支撑/阻力",
        "gap_up": "向上缺口 → 支撑 = 缺口上沿",
    },
    "gap_rejection": {
        "description": "价格在缺口处出现反转K线",
        "signal": "缺口拒绝 = 强支撑/阻力确认",
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# 决策引擎
# ══════════════════════════════════════════════════════════════════════════════

def detect_pullback_type(
    bars: List[Bar],
    swing_high: float,
    swing_low: float,
) -> PullbackResult:
    """
    识别回调类型（基于P05的detect_pullback_type扩展）

    参数：
        bars: K线列表
        swing_high: 最近高点
        swing_low: 最近低点

    返回：
        PullbackResult: 包含回调类型和信号
    """
    if len(bars) < 5:
        return PullbackResult(
            signal=Signal.NONE,
            direction=Direction.WATCH,
            confidence="低",
            reasons=["K线数量不足"],
        )

    latest = get_latest_bar(bars)
    latest_close = latest.close
    latest_high = latest.high
    latest_low = latest.low

    swing_range = swing_high - swing_low
    if swing_range <= 0:
        return PullbackResult(
            signal=Signal.NONE,
            direction=Direction.WATCH,
            confidence="低",
            reasons=["Swing范围无效"],
        )

    # 计算当前回调幅度
    pullback_from_high = (swing_high - latest_close) / swing_range
    pullback_from_low = (latest_close - swing_low) / swing_range

    # 判断趋势方向（基于最近N根K线的高低点）
    recent_bars = bars[-10:]
    recent_highs = [b.high for b in recent_bars]
    recent_lows = [b.low for b in recent_bars]
    current_high = max(recent_highs)
    current_low = min(recent_lows)

    # 趋势判断
    is_uptrend = all(
        recent_bars[i].high < recent_bars[i+1].high
        and recent_bars[i].low < recent_bars[i+1].low
        for i in range(len(recent_bars)-1)
    )
    is_downtrend = all(
        recent_bars[i].high > recent_bars[i+1].high
        and recent_bars[i].low > recent_bars[i+1].low
        for i in range(len(recent_bars)-1)
    )

    # 回调幅度判断
    if pullback_from_high >= 0.5:
        if pullback_from_high >= 0.66:
            return PullbackResult(
                signal=Signal.TREND_EXHAUSTION,
                direction=Direction.WATCH,
                confidence="中",
                reasons=[f"深度回调({pullback_from_high:.0%})，趋势可能变弱"],
            )
        else:
            return PullbackResult(
                signal=Signal.COUNTER_TREND_WARN_1,
                direction=Direction.LONG,
                confidence="高",
                reasons=[f"50%+回调({pullback_from_high:.0%})，关注H1买入机会"],
            )
    else:
        return PullbackResult(
            signal=Signal.NONE,
            direction=Direction.LONG if is_uptrend else Direction.SHORT,
            confidence="高",
            reasons=[f"浅回调({pullback_from_high:.0%})，趋势健康"],
        )


def is_counter_trend_exhaustion(
    bars: List[Bar],
    market_direction: str,  # "上涨" / "下跌"
    attempt_count: int = 0,  # 当前是第几次尝试延续趋势
    first_push_failed: bool = False,  # 第一推是否失败过
) -> PullbackResult:
    """
    判断逆势交易者离场信号

    核心逻辑（来自L Brooks 09C）：
    - 历史教育者（逆势交易者）可以允许市场反对他们一次
    - 当市场第二次发出警告时，必须离场

    参数：
        bars: K线列表
        market_direction: 当前趋势方向
        attempt_count: 第几次尝试延续趋势（1=H1，2=H2）
        first_push_failed: 第一推（H1/L1）是否失败

    返回：
        PullbackResult: 包含离场信号
    """
    if len(bars) < 3:
        return PullbackResult(
            signal=Signal.NONE,
            direction=Direction.WATCH,
            confidence="低",
            reasons=["K线数量不足"],
        )

    latest = get_latest_bar(bars)
    latest_time = latest.time

    # 找到前一根K线
    sorted_bars = sorted(bars, key=lambda b: b.time)
    idx = next((i for i, b in enumerate(sorted_bars) if b.time == latest_time), -1)
    if idx <= 0:
        return PullbackResult(
            signal=Signal.NONE,
            direction=Direction.WATCH,
            confidence="低",
            reasons=["无法找到前一根K线"],
        )

    prev_bar = sorted_bars[idx - 1]

    # 判断是否是H1信号（第一次高点抬高）
    is_h1 = (latest.high > prev_bar.high and
             latest.close > latest.open and  # 阳线
             market_direction == "下跌")  # 在下跌趋势中

    # 判断是否是L1信号（第一次低点降低）
    is_l1 = (latest.low < prev_bar.low and
             latest.close < latest.open and  # 阴线
             market_direction == "上涨")  # 在上涨趋势中

    if market_direction == "下跌":
        if attempt_count == 1 and is_h1:
            return PullbackResult(
                signal=Signal.H1,
                direction=Direction.LONG,
                confidence="高",
                entry_price=latest.high + 0.01,  # 高一上方1 tick入场
                stop_loss=latest.low - 0.01,
                reasons=["H1 = 第一次高点抬高 = 多头信号"],
            )
        if attempt_count == 2:
            return PullbackResult(
                signal=Signal.COUNTER_TREND_WARN_2,
                direction=Direction.LONG,
                confidence="极高",
                entry_price=latest.high + 0.01,
                stop_loss=latest.low - 0.01,
                reasons=[
                    "第二次尝试延续趋势 = 市场第二次警告逆势交易者",
                    "历史教育者必须离场",
                    "空头止损推动价格继续上涨",
                ],
            )

    if market_direction == "上涨":
        if attempt_count == 1 and is_l1:
            return PullbackResult(
                signal=Signal.L1,
                direction=Direction.SHORT,
                confidence="高",
                entry_price=latest.low - 0.01,  # 低一下方1 tick入场
                stop_loss=latest.high + 0.01,
                reasons=["L1 = 第一次低点降低 = 空头信号"],
            )
        if attempt_count == 2:
            return PullbackResult(
                signal=Signal.COUNTER_TREND_WARN_2,
                direction=Direction.SHORT,
                confidence="极高",
                entry_price=latest.low - 0.01,
                stop_loss=latest.high + 0.01,
                reasons=[
                    "第二次尝试延续趋势 = 市场第二次警告逆势交易者",
                    "历史教育者必须离场",
                    "多头止损推动价格继续下跌",
                ],
            )

    return PullbackResult(
        signal=Signal.NONE,
        direction=Direction.WATCH,
        confidence="低",
        reasons=["无逆势离场信号"],
    )


def find_entry_after_pullback(
    bars: List[Bar],
    market_direction: str,  # "上涨" / "下跌"
    pullback_depth: float = 0.0,  # 回调幅度（0.0-1.0）
    counter_trend_stop_level: Optional[float] = None,  # 逆势交易者止损位置
) -> PullbackResult:
    """
    回调后入场点识别（结合P05的find_entry_after_pullback扩展）

    参数：
        bars: K线列表
        market_direction: 趋势方向
        pullback_depth: 回调深度（0.0-1.0）
        counter_trend_stop_level: 逆势交易者的止损位（用于判断是否被触发）

    返回：
        PullbackResult: 包含入场价格、止损、目标
    """
    if len(bars) < 3:
        return PullbackResult(
            signal=Signal.NONE,
            direction=Direction.WATCH,
            confidence="低",
            reasons=["K线数量不足"],
        )

    sorted_bars = sorted(bars, key=lambda b: b.time)
    latest = get_latest_bar(bars)
    latest_time = latest.time

    # 找到信号K线的前一根K线
    idx = next((i for i, b in enumerate(sorted_bars) if b.time == latest_time), -1)
    if idx < 1:
        return PullbackResult(
            signal=Signal.NONE,
            direction=Direction.WATCH,
            confidence="低",
            reasons=["无法定位信号K线"],
        )

    signal_bar = sorted_bars[idx]
    prev_bar = sorted_bars[idx - 1]

    # ── 上涨趋势回调后 ──
    if market_direction == "上涨":
        # H1：第一次高点抬高
        h1_broken = signal_bar.high > prev_bar.high

        if h1_broken and signal_bar.close > signal_bar.open:
            entry = signal_bar.high + 0.01
            stop = signal_bar.low - 0.01

            # 检查是否是坏H1（大阴线在最低）
            is_weak_h1 = (
                is_bearish_bar(signal_bar) and
                signal_bar.low < prev_bar.low
            )

            if is_weak_h1:
                # 坏H1 = 逆势交易者（空头）会在这里入场
                # 好H1 = 顺势多头会等待更好的信号
                return PullbackResult(
                    signal=Signal.H1,
                    direction=Direction.LONG,
                    confidence="中",
                    entry_price=entry,
                    stop_loss=stop,
                    reasons=[
                        "弱H1 = 信号K线是大阴线在最低",
                        "愿意在上方买入的多头少",
                        "反而是逆势空头会在此做空",
                        "这反而给顺势交易者更好的机会",
                    ],
                )
            else:
                return PullbackResult(
                    signal=Signal.H1,
                    direction=Direction.LONG,
                    confidence="高",
                    entry_price=entry,
                    stop_loss=stop,
                    reasons=["H1突破 = 多头重新控制，回调结束"],
                )

        # H2：第二次高点抬高（回调未跌破H1低点）
        if idx >= 2:
            h1_bar = sorted_bars[idx - 1]
            h2_broken = signal_bar.high > h1_bar.high

            if h2_broken and signal_bar.close > signal_bar.open:
                return PullbackResult(
                    signal=Signal.H2,
                    direction=Direction.LONG,
                    confidence="高",
                    entry_price=signal_bar.high + 0.01,
                    stop_loss=signal_bar.low - 0.01,
                    reasons=["H2 = 顺势第二波，继续持有多头"],
                )

    # ── 下跌趋势回调后 ──
    if market_direction == "下跌":
        # L1：第一次低点降低
        l1_broken = signal_bar.low < prev_bar.low

        if l1_broken and signal_bar.close < signal_bar.open:
            entry = signal_bar.low - 0.01
            stop = signal_bar.high + 0.01

            is_weak_l1 = (
                is_bullish_bar(signal_bar) and
                signal_bar.high > prev_bar.high
            )

            if is_weak_l1:
                return PullbackResult(
                    signal=Signal.L1,
                    direction=Direction.SHORT,
                    confidence="中",
                    entry_price=entry,
                    stop_loss=stop,
                    reasons=[
                        "弱L1 = 信号K线是大阳线在最高",
                        "逆势多头会在此做多",
                        "顺势空头获得更好的做空机会",
                    ],
                )
            else:
                return PullbackResult(
                    signal=Signal.L1,
                    direction=Direction.SHORT,
                    confidence="高",
                    entry_price=entry,
                    stop_loss=stop,
                    reasons=["L1跌破 = 空头重新控制，反弹结束"],
                )

    return PullbackResult(
        signal=Signal.NONE,
        direction=Direction.WATCH,
        confidence="低",
        reasons=["无入场信号"],
    )


def detect_failed_double_pattern(
    bars: List[Bar],
    first_swing_high: float,
    second_swing_high: float,  # 双顶的第二高
    neck_line: float,  # 颈线位置（双顶的支撑/双底的阻力）
    pattern_type: str = "double_top",  # "double_top" / "double_bottom"
) -> PullbackResult:
    """
    检测失败的双顶/双底形态

    失败的双顶：价格未能跌破颈线，反而向上突破
    失败的双底：价格未能突破颈线，反而向下突破

    参数：
        bars: K线列表
        first_swing_high: 第一个高点
        second_swing_high: 第二个高点
        neck_line: 颈线位置
        pattern_type: "double_top" 或 "double_bottom"

    返回：
        PullbackResult: 包含失败形态信号
    """
    if len(bars) < 3:
        return PullbackResult(
            signal=Signal.NONE,
            direction=Direction.WATCH,
            confidence="低",
            reasons=["K线数量不足"],
        )

    latest = get_latest_bar(bars)
    latest_close = latest.close

    if pattern_type == "double_top":
        # 失败的双顶：应该下跌但反而上涨
        # 颈线被向上突破
        if latest_close > neck_line:
            # 价格突破颈线 = 双顶失败 = 空头被止损挤压
            return PullbackResult(
                signal=Signal.DOUBLE_TOP_FAIL,
                direction=Direction.LONG,
                confidence="极高",
                reasons=[
                    "双顶失败 = 价格未能跌破颈线",
                    "空头止损被触发 → 推动价格上涨",
                    "这是极强的买入信号",
                ],
            )
        else:
            return PullbackResult(
                signal=Signal.NONE,
                direction=Direction.WATCH,
                confidence="中",
                reasons=["双顶形态仍在发展中，未确认失败"],
            )

    else:  # double_bottom
        # 失败的双底：应该上涨但反而下跌
        # 颈线被向下突破
        if latest_close < neck_line:
            return PullbackResult(
                signal=Signal.DOUBLE_BOTTOM_FAIL,
                direction=Direction.SHORT,
                confidence="极高",
                reasons=[
                    "双底失败 = 价格未能突破颈线",
                    "多头止损被触发 → 推动价格下跌",
                    "这是极强的卖出信号",
                ],
            )
        else:
            return PullbackResult(
                signal=Signal.NONE,
                direction=Direction.WATCH,
                confidence="中",
                reasons=["双底形态仍在发展中，未确认失败"],
            )


def detect_gap_as_target_and_support(
    bars: List[Bar],
    gap_bar_time: str,  # 缺口K线的时间戳
    gap_bar_high: float,
    gap_bar_low: float,
) -> PullbackResult:
    """
    检测缺口的双重角色：既是目标位，也是支撑

    逻辑：
    1. 当价格向缺口方向运动时，缺口成为目标位
    2. 当价格到达缺口后，缺口成为支撑/阻力

    参数：
        bars: K线列表
        gap_bar_time: 缺口K线的时间戳
        gap_bar_high: 缺口K线的高点
        gap_bar_low: 缺口K线的低点

    返回：
        PullbackResult: 包含缺口信号
    """
    if len(bars) < 2:
        return PullbackResult(
            signal=Signal.NONE,
            direction=Direction.WATCH,
            confidence="低",
            reasons=["K线数量不足"],
        )

    sorted_bars = sorted(bars, key=lambda b: b.time)
    latest = get_latest_bar(bars)
    latest_close = latest.close

    # 向上缺口：gap_bar_low是支撑
    if gap_bar_low > gap_bar_high:
        # 向上跳空
        if latest_close < gap_bar_low:
            return PullbackResult(
                signal=Signal.GAP_AS_SUPPORT,
                direction=Direction.LONG,
                confidence="高",
                reasons=["价格回落到向上缺口 = 支撑位 = 买入机会"],
            )
        elif latest_close > gap_bar_low:
            return PullbackResult(
                signal=Signal.GAP_AS_TARGET,
                direction=Direction.WATCH,
                confidence="高",
                reasons=["价格已突破缺口支撑 = 缺口成为目标位"],
            )

    # 向下缺口：gap_bar_high是阻力
    else:
        # 向下跳空
        if latest_close > gap_bar_high:
            return PullbackResult(
                signal=Signal.GAP_AS_SUPPORT,
                direction=Direction.SHORT,
                confidence="高",
                reasons=["价格反弹到向下缺口 = 阻力位 = 卖出机会"],
            )
        elif latest_close < gap_bar_high:
            return PullbackResult(
                signal=Signal.GAP_AS_TARGET,
                direction=Direction.WATCH,
                confidence="高",
                reasons=["价格已跌破缺口阻力 = 缺口成为目标位"],
            )

    return PullbackResult(
        signal=Signal.NONE,
        direction=Direction.WATCH,
        confidence="低",
        reasons=["缺口形态不明确"],
    )


# ══════════════════════════════════════════════════════════════════════════════
# 测试
# ══════════════════════════════════════════════════════════════════════════════

def _make_bar(t: str, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(time=t, open=o, high=h, low=l, close=c)

if __name__ == "__main__":
    print("P06 回调&数K线(2)-逆势交易者离场 决策引擎测试")
    print("=" * 60)

    # 测试1：H1作为逆势离场信号
    print("\n【测试1】下跌趋势中出现H1（逆势空头应离场）")
    test_bars = [
        _make_bar("10:00", 100, 102, 99, 100),   # bar1
        _make_bar("10:05", 100, 101, 98, 99),    # bar2 (下跌)
        _make_bar("10:10", 99, 100, 97, 98),    # bar3 (继续下跌)
        _make_bar("10:15", 98, 99, 97, 98),     # bar4 (盘整)
        _make_bar("10:20", 98, 101, 97, 100),   # bar5 (H1！突破前高)
    ]
    r = is_counter_trend_exhaustion(
        test_bars,
        market_direction="下跌",
        attempt_count=1,
    )
    print(f"  信号: {r.signal.value} | 方向: {r.direction.value} | 置信度: {r.confidence}")
    print(f"  入场: {r.entry_price} | 止损: {r.stop_loss}")
    print(f"  理由: {r.reasons}")

    # 测试2：第二次警告 = 必须离场
    print("\n【测试2】第二次尝试延续趋势（逆势交易者必须离场）")
    r2 = is_counter_trend_exhaustion(
        test_bars,
        market_direction="下跌",
        attempt_count=2,
    )
    print(f"  信号: {r2.signal.value} | 方向: {r2.direction.value} | 置信度: {r2.confidence}")
    print(f"  理由: {r2.reasons}")

    # 测试3：回调类型识别
    print("\n【测试3】回调类型识别")
    r3 = detect_pullback_type(test_bars, swing_high=102.0, swing_low=97.0)
    print(f"  信号: {r3.signal.value} | 方向: {r3.direction.value}")
    print(f"  理由: {r3.reasons}")

    # 测试4：失败的双顶
    print("\n【测试4】失败的双顶（空头被挤压）")
    r4 = detect_failed_double_pattern(
        bars=test_bars,
        first_swing_high=102.0,
        second_swing_high=101.5,
        neck_line=98.5,
        pattern_type="double_top",
    )
    print(f"  信号: {r4.signal.value} | 方向: {r4.direction.value}")
    print(f"  理由: {r4.reasons}")

    # 测试5：缺口双重角色
    print("\n【测试5】缺口作为目标位和支撑位")
    gap_bars = [
        _make_bar("09:30", 105, 107, 105, 106),   # 向上跳空
        _make_bar("09:35", 106, 106.5, 105.5, 105.8),  # 回撤到支撑
    ]
    r5 = detect_gap_as_target_and_support(
        gap_bars,
        gap_bar_time="09:30",
        gap_bar_high=107.0,
        gap_bar_low=105.0,
    )
    print(f"  信号: {r5.signal.value} | 方向: {r5.direction.value}")
    print(f"  理由: {r5.reasons}")

    print("\n" + "=" * 60)
    print("所有测试完成 ✓")
