#!/usr/bin/env python3
"""
P05 顺势交易-回调&数K线 — 专家决策规则库
================================================
来源：方方土价格行为学 · 顺势交易
视频：05-04顺势交易-回调&数k线
分析方法：Whisper字幕 + Vision分析

核心主题：
  1. 数K线：H1/L1/H2/L2/H3/L3 概念
  2. 回调的本质：机构行为（减仓）
  3. 多周期嵌套：隐藏的回调（Implied Pullback）
  4. 深度回调判断
  5. 趋势线与EMA应用
  6. 三推概念：L3/H3反转
  7. Failed Wedge（失败楔形）
  8. Measured Move（等距测量）
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

# ══════════════════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════════════════

class Direction(Enum):
    LONG   = "LONG"
    SHORT  = "SHORT"
    WATCH  = "WATCH"
    NONE   = "NONE"

class Signal(Enum):
    H1 = "H1买入信号"
    H2 = "H2买入信号"
    H3 = "H3反转信号"
    L1 = "L1卖出信号"
    L2 = "L2卖出信号"
    L3 = "L3反转信号"
    PULLBACK_DEEP = "深度回调"
    TRENDLINE_BREAK = "趋势线跌破"
    FAILED_WEDGE = "失败楔形"
    MEASURED_MOVE = "等距测量目标"
    NONE = "无信号"

@dataclass
class PullbackResult:
    signal: Signal = Signal.NONE
    direction: Direction = Direction.WATCH
    confidence: str = "低"
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    reasons: list[str] = field(default_factory=list)

# ══════════════════════════════════════════════════════════════════════════════
# 核心规则库
# ══════════════════════════════════════════════════════════════════════════════

# ── 规则1：H1/L1信号 ─────────────────────────────────────────────
RULE_H1_L1 = {
    "name": "H1/L1数K线信号",
    "H1": {
        "description": "上涨趋势回调后，第一根突破前一根K线高点的阳线",
        "entry": "Buy Stop在信号K线高点上方1 tick",
        "stop": "止损在信号K线低点下方1 tick",
        "confidence": "高",
        "pattern_keywords": ["H1", "high 1", "第一根突破", "突破前高"],
    },
    "H2": {
        "description": "H1之后再次突破前高",
        "entry": "顺势加仓或持有",
        "confidence": "中",
    },
    "H3": {
        "description": "H2之后第三次突破（第三推）",
        "signal": "通常是趋势末尾，弱信号或反转信号",
        "confidence": "低",
    },
    "L1": {
        "description": "下跌趋势反弹后，第一根跌破前一根K线低点的阴线",
        "entry": "Sell Stop在信号K线低点下方1 tick",
        "stop": "止损在信号K线高点上方1 tick",
        "confidence": "高",
    },
    "L2/L3": "类似H2/H3，空头版本",
}

# ── 规则2：回调的本质 ───────────────────────────────────────────
RULE_PULLBACK_NATURE = {
    "name": "回调的本质：机构行为",
    "description": "价格上涨 → 机构面临更大风险 → 机构减仓（获利了结）→ 产生卖压 → 价格回调",
    "implication": "回调是机构主动行为，不等于趋势反转",
    "pattern": "机构减仓产生的卖压导致回调",
}

# ── 规则3：深度回调判断 ─────────────────────────────────────────
RULE_DEEP_PULLBACK = {
    "name": "深度回调判断",
    "pullback_50": {
        "threshold": 0.50,
        "description": "回撤达到Swing幅度的50%",
        "signal": "关键支撑区域，可能止跌",
        "action": "可以关注H1买入机会",
    },
    "pullback_66": {
        "threshold": 0.66,
        "description": "回撤达到Swing幅度的2/3",
        "signal": "趋势可能变弱，关注是否破位",
        "action": "降低仓位或等待确认",
    },
    "pullback_100": {
        "threshold": 1.0,
        "description": "完全回撤到起点",
        "signal": "趋势可能反转",
        "action": "离场或准备做反转",
    },
}

# ── 规则4：多周期嵌套 ───────────────────────────────────────────
RULE_MULTI_TIMEFRAME = {
    "name": "多周期嵌套",
    "rule": "大周期一根K线 = 小周期一段完整回调",
    "implied_pullback": {
        "description": "隐藏的回调：在大周期只是一根小K线，在小周期是一段完整调整",
        "trade_application": "在大趋势回调中寻找小周期的H1入场信号",
    },
    "timeframe_table": {
        "大周期一根K线": "小周期5-20根K线的调整",
        "大周期十字星": "小周期可能是一个横盘结构",
        "大周期上影线": "小周期可能是两次推升之间的停顿",
    },
}

# ── 规则5：三推反转 ────────────────────────────────────────────
RULE_THREE_PUSHES = {
    "name": "三推反转（H3/L3）",
    "bull_three_push": {
        "description": "三次上推都失败 → 高概率下跌反转",
        "pattern": "H1失败, H2失败, H3失败",
        "signal": "H3反转 → 做空",
        "confidence": "高",
    },
    "bear_three_push": {
        "description": "三次下推都失败 → 高概率上涨反转",
        "pattern": "L1失败, L2失败, L3失败",
        "signal": "L3反转 → 做多",
        "confidence": "高",
    },
    "wedge_bull": {
        "description": "楔形顶 = 三次推升失败的反转",
        "signal": "H3反转",
    },
    "wedge_bear": {
        "description": "楔形底 = 三次下跌失败的反转",
        "signal": "L3反转",
    },
}

# ── 规则6：Failed Wedge ──────────────────────────────────────────
RULE_FAILED_WEDGE = {
    "name": "Failed Wedge（失败楔形）",
    "description": "看起来是做空机会的楔形，但全部三次推升都失败",
    "signal": "极强的反转信号",
    "implication": "L1/L2/L3全部失败 → 市场将强势反转",
    "trade": "等待确认后做多（对于熊市楔形）",
}

# ══════════════════════════════════════════════════════════════════════════════
# 决策引擎
# ══════════════════════════════════════════════════════════════════════════════

def classify_h_signal(
    market: str = "",          # 上涨趋势/下跌趋势
    pullback_bars: int = 0,    # 回调走了多少根K线
    h1_break: bool = False,     # 是否出现H1突破
    h2_break: bool = False,
    h3_break: bool = False,
    signal_bar_quality: str = "",  # 大阳线/十字星/小阳线
) -> PullbackResult:
    """
    判断H系列信号
    """
    if "上涨" in market or "多头" in market:
        if h3_break:
            return PullbackResult(
                signal=Signal.H3,
                direction=Direction.WATCH,
                confidence="低",
                reasons=["H3 = 第三推，通常是趋势末尾"],
            )
        if h2_break:
            return PullbackResult(
                signal=Signal.H2,
                direction=Direction.LONG,
                confidence="中",
                reasons=["H2 = 顺势第二波"],
            )
        if h1_break:
            confidence = "高" if "大阳线" in signal_bar_quality else "中"
            return PullbackResult(
                signal=Signal.H1,
                direction=Direction.LONG,
                confidence=confidence,
                entry_price=None,  # 由调用方提供
                stop_loss=None,
                reasons=["H1突破 = 多头重新夺回控制"],
            )

    if "下跌" in market or "空头" in market:
        if h3_break:  # 这里复用h3表示L3
            return PullbackResult(
                signal=Signal.L3,
                direction=Direction.WATCH,
                confidence="低",
                reasons=["L3 = 第三推，通常是趋势末尾"],
            )
        if h2_break:
            return PullbackResult(
                signal=Signal.L2,
                direction=Direction.SHORT,
                confidence="中",
                reasons=["L2 = 顺势第二波"],
            )
        if h1_break:
            confidence = "高" if "大阴线" in signal_bar_quality else "中"
            return PullbackResult(
                signal=Signal.L1,
                direction=Direction.SHORT,
                confidence=confidence,
                reasons=["L1跌破 = 空头重新夺回控制"],
            )

    return PullbackResult(
        signal=Signal.NONE,
        direction=Direction.WATCH,
        confidence="低",
        reasons=["无明确信号"],
    )


def is_deep_pullback(
    pullback_ratio: float,
    trend_strength: str = "",  # 强趋势/弱趋势
) -> PullbackResult:
    """
    判断是否深度回调
    pullback_ratio: 回撤幅度 / Swing总幅度（0.0-1.0）
    """
    if pullback_ratio >= 0.66:
        if "强趋势" in trend_strength:
            return PullbackResult(
                signal=Signal.PULLBACK_DEEP,
                direction=Direction.LONG,  # 强趋势中深度回调可能是陷阱
                confidence="中",
                reasons=["强趋势中深度回调可能是入场机会（陷阱）"],
            )
        else:
            return PullbackResult(
                signal=Signal.PULLBACK_DEEP,
                direction=Direction.WATCH,
                confidence="中",
                reasons=["深度回调 > 2/3，趋势可能变弱"],
            )
    elif pullback_ratio >= 0.50:
        return PullbackResult(
            signal=Signal.PULLBACK_DEEP,
            direction=Direction.LONG,
            confidence="高",
            reasons=["50%回撤 = 关键支撑，可关注H1买入"],
        )
    else:
        return PullbackResult(
            signal=Signal.NONE,
            direction=Direction.LONG,
            confidence="高",
            reasons=[f"浅回调({pullback_ratio:.0%})，趋势健康"],
        )


def check_three_pushes(
    push_results: list[str],  # ["失败","成功","失败"] 之类的
    direction: str = "",        # 上涨/下跌
) -> PullbackResult:
    """
    检查三推是否失败（产生反转信号）
    push_results: 每次推升的结果
    """
    if len(push_results) < 3:
        return PullbackResult(
            signal=Signal.NONE,
            direction=Direction.WATCH,
            confidence="低",
            reasons=["推升次数不足3次"],
        )

    last_three = push_results[-3:]
    all_failed = all("失败" in r or "fail" in r.lower() for r in last_three)

    if all_failed:
        if "上涨" in direction:
            return PullbackResult(
                signal=Signal.H3,
                direction=Direction.SHORT,
                confidence="高",
                reasons=["三次上推全部失败 → H3反转 → 做空"],
            )
        else:
            return PullbackResult(
                signal=Signal.L3,
                direction=Direction.LONG,
                confidence="高",
                reasons=["三次下推全部失败 → L3反转 → 做多"],
            )

    return PullbackResult(
        signal=Signal.NONE,
        direction=Direction.WATCH,
        confidence="低",
        reasons=["三推未全部失败，无反转信号"],
    )


def check_failed_wedge(
    wedge_type: str = "",     # 熊市楔形/牛市楔形
    l_signals_failed: bool = False,  # L1/L2/L3是否全部失败
    h_signals_failed: bool = False,  # H1/H2/H3是否全部失败
) -> PullbackResult:
    """
    检查Failed Wedge（失败楔形）
    """
    if l_signals_failed and "熊市" in wedge_type:
        return PullbackResult(
            signal=Signal.FAILED_WEDGE,
            direction=Direction.LONG,
            confidence="极高",
            reasons=["失败楔形 = 极强反转信号 → 做多"],
        )
    if h_signals_failed and "牛市" in wedge_type:
        return PullbackResult(
            signal=Signal.FAILED_WEDGE,
            direction=Direction.SHORT,
            confidence="极高",
            reasons=["失败楔形 = 极强反转信号 → 做空"],
        )
    return PullbackResult(
        signal=Signal.NONE,
        direction=Direction.WATCH,
        confidence="低",
        reasons=["无失败楔形信号"],
    )


def calculate_measured_move(
    first_swing: float,   # 第一段涨幅
    pullback_low: float, # 回调低点
) -> float:
    """
    计算Measured Move目标位
    目标 = 回调低点 + 第一段涨幅
    """
    return pullback_low + first_swing


if __name__ == "__main__":
    tests = [
        ("上涨趋势", 3, True, False, False, "大阳线"),
        ("上涨趋势", 5, True, True, False, "大阳线"),
        ("下跌趋势", 2, True, False, False, "大阴线"),
        ("上涨趋势", 10, True, True, True, "小阳线"),
    ]

    print("P05 顺势交易-回调&数K线 决策引擎测试")
    print("=" * 60)
    for market, bars, h1, h2, h3, quality in tests:
        r = classify_h_signal(market, bars, h1, h2, h3, quality)
        print(f"\n市场:{market} 回调{bars}根 H1:{h1} H2:{h2} H3:{h3}")
        print(f"  信号:{r.signal.value} | {r.direction.value} | {r.confidence}")
        print(f"  理由:{r.reasons}")

    print("\n深度回调测试:")
    r = is_deep_pullback(0.5, "强趋势")
    print(f"  50%回撤+强趋势 → {r.signal.value}: {r.direction.value} ({r.confidence})")
    r = is_deep_pullback(0.7, "弱趋势")
    print(f"  70%回撤+弱趋势 → {r.signal.value}: {r.direction.value} ({r.confidence})")

    print("\n三推测试:")
    r = check_three_pushes(["失败","失败","失败"], "上涨")
    print(f"  三次上推失败 → {r.signal.value}: {r.direction.value} ({r.confidence})")

    print("\n失败楔形测试:")
    r = check_failed_wedge("熊市楔形", l_signals_failed=True)
    print(f"  熊市楔形L1/L2/L3全失败 → {r.signal.value}: {r.direction.value}")
