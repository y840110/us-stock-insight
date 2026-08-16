#!/usr/bin/env python3
"""
P18 第二段陷阱 — 专家决策规则库
================================================
来源：方方土价格行为学 · 突破专题(3) · 2nd Leg Trap
视频：18-5.突破专题(3)_ 第二段陷阱 2nd Leg Trap.mp4
场景数：37个 | 有决策信号：17个

本模块将 P18 学到的决策规则编码为可复用的模式匹配函数，
用于未来对新K线截图/行情的辅助决策判断。

调用方式：
    from p18_second_leg_trap import analyze_pattern
    result = analyze_pattern(chart_description, market_env, patterns_found)
    print(result["signal"], result["confidence"], result["reasons"])
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

# ══════════════════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════════════════

class Direction(Enum):
    LONG  = "LONG"
    SHORT = "SHORT"
    WATCH = "WATCH"
    NONE  = "NONE"

@dataclass
class PatternMatch:
    """单个模式匹配结果"""
    name: str           # 模式名称
    direction: Direction
    confidence: str      # "高" / "中" / "低"
    signal: str         # 具体信号描述
    entry_condition: list[str] = field(default_factory=list)
    stop_loss: Optional[str] = None
    target: Optional[str] = None
    risk: list[str] = field(default_factory=list)

@dataclass
class DecisionResult:
    """综合决策结果"""
    video: str = "P18_第二段陷阱"
    primary_signal: Direction = Direction.NONE
    confidence: str = "低"
    matched_patterns: list[PatternMatch] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    risk_warnings: list[str] = field(default_factory=list)
    summary: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# P18 核心规则库
# ══════════════════════════════════════════════════════════════════════════════

# ── 规则1：第二段陷阱（2nd Leg Trap）────────────────────────────────────
# 背景：80%的突破初次尝试会失败，第二段（follow-through）才是真信号
# 条件：第一次突破后回调 → 再次突破时跟进

RULE_2ND_LEG_TRAP = {
    "name": "第二段陷阱 / 2nd Leg Trap",
    "description": "首次突破常失败，等待第二段确认",
    "patterns": ["第二段陷阱", "2nd Leg Trap", "2nd leg", "Follow-through", "跟进K线"],
    "required_conditions": [
        "价格突破前期高点/低点",
        "出现回撤/回调",
        "再次向突破方向移动",
    ],
    "signal": "等待第二段确认后跟进",
    "direction": "WATCH",  # 观望，等待确认
    "confidence": "高",
    "key_rule": "第二段不一定有，有了第二段才能确认趋势",
}

# ── 规则2：惊喜K线（Surprise Bar）─────────────────────────────────────
# 定义：实体很大、伴随成交量的K线，通常是趋势启动/反转信号

RULE_SURPRISE_BAR = {
    "name": "惊喜K线 / Surprise Bar",
    "bullish": {
        "description": "强力阳线突破，常出现在底部或回调后",
        "patterns": ["Bull Surprise", "惊喜K线", "大阳线突破", "实体很大"],
        "signal": "观望回调买入机会，不追高",
        "direction": "LONG",
        "confidence": "中",
        "entry": ["等待价格回踩突破点", "缩量回调不破前低"],
        "stop_loss": "惊喜K线低点下方1-2 tick",
        "avoid": "不在惊喜K线形成时直接追入",
    },
    "bearish": {
        "description": "强力阴线，常出现在顶部或反弹后",
        "patterns": ["Bear Surprise", "大阴线", "收在最低", "实体很大"],
        "signal": "可在阴线低点下方1 tick挂止损做空",
        "direction": "SHORT",
        "confidence": "高",
        "entry": ["阴线收盘确认后", "阴线低点下方1 tick止损单"],
        "stop_loss": "阴线高点上方1-2 tick",
    },
}

# ── 规则3：旗形（Flag）───────────────────────────────────────────────
# 上涨中继： Bear Flag（上升后的小幅下跌通道）
# 下跌中继： Bull Flag（下跌后的小幅上涨通道）

RULE_BEAR_FLAG = {
    "name": "熊旗 / Bear Flag",
    "description": "上升趋势中的小幅下跌通道，通常继续看涨",
    "bullish_break": {
        "patterns": ["熊旗上轨", "突破熊旗", "Bull Surprise"],
        "signal": "突破熊旗上轨 → 买入（做多）",
        "direction": "LONG",
        "confidence": "中",
        "entry": "突破后K线收盘站稳上轨",
        "stop_loss": "旗形通道下轨下方",
        "note": "逆势操作，胜率较低，需大止损",
    },
    "bearish_continuation": {
        "patterns": ["顺势做空", "反弹受阻"],
        "signal": "旗形内反弹受阻做空",
        "direction": "SHORT",
        "confidence": "高",
        "entry": "价格反弹至旗形上轨附近受阻",
    },
}

RULE_BULL_FLAG = {
    "name": "牛旗 / Bull Flag",
    "description": "下跌趋势中的小幅上涨通道，通常继续看跌",
}

# ── 规则4：窄通道 vs 宽通道 ─────────────────────────────────────────
# 窄通道（Narrow Channel）：趋势极强，胜率高
# 宽通道（Broad Channel）：趋势弱，可能演变为震荡

RULE_NARROW_CHANNEL = {
    "name": "窄通道 / Narrow Channel",
    "description": "趋势极强，紧贴趋势线，回撤极浅",
    "bullish": {
        "patterns": ["窄通道上涨", "Narrow Channel", "回撤极浅"],
        "signal": "顺势做多，等待回踩趋势线买入",
        "direction": "LONG",
        "confidence": "极高",
        "stats": "约75%概率继续趋势",
        "entry": "价格回踩上涨趋势线",
        "stop_loss": "通道下轨下方",
        "warning": "警惕 Climax（抛售高潮），到达目标位减仓",
    },
    "bearish": {
        "patterns": ["窄通道下跌", "回撤极浅"],
        "signal": "顺势做空，反弹至趋势线受阻做空",
        "direction": "SHORT",
        "confidence": "极高",
    },
}

RULE_BROAD_CHANNEL = {
    "name": "宽通道 / Broad Channel",
    "description": "趋势弱，可能演变为震荡区间，胜率低",
    "advice": "宽通道中趋势交易胜率低，避免追涨杀跌",
}

# ── 规则5：Pain Trade（痛苦交易）────────────────────────────────────
# 定义：空头被套（做空后上涨）或多头被套（做多后下跌）
# 规律：被套者的平仓会加速趋势，形成第二段

RULE_PAIN_TRADE = {
    "name": "痛苦交易 / Pain Trade",
    "description": "机构利用散户被套后的止损/平仓推动第二段",
    "patterns": [
        "Pain Trade", "痛苦交易", "空头被套", "多头被套",
        "Trapped In", "Trapped Out", "被套", "止损连环触发"
    ],
    "logic": {
        "做空后上涨": "空头止损 → 价格加速上涨 → 做空者被迫平仓 → 进一步上涨",
        "做多后下跌": "多头止损 → 价格加速下跌 → 做多者被迫平仓 → 进一步下跌",
    },
    "signal": "观察被套群体（K线形态/成交量）→ 等待第二段机会",
    "direction": "WATCH",
    "confidence": "高",
}

# ── 规则6：Always In（趋势惯性）───────────────────────────────────────
# Always In Long：价格创新高，趋势向上
# Always In Short：价格创新低，趋势向下
# 转折点：价格未能突破前期高点/低点

RULE_ALWAYS_IN = {
    "name": "始终在场 / Always In",
    "always_in_long": {
        "patterns": ["Always In Long", "创新高", "低点上移"],
        "signal": "只做多/持有，严禁做空",
        "direction": "LONG",
        "confidence": "高",
        "reversal": "价格未能创新高且收于前期高点下方 → 可能转空",
    },
    "always_in_short": {
        "patterns": ["Always In Short", "创新低", "高点下移"],
        "signal": "只做空/持有，严禁做多",
        "direction": "SHORT",
        "confidence": "高",
        "reversal": "价格未能创新低且收于前期低点上方 → 可能转多",
    },
}

# ── 规则7：内切棒（Inside Bar）────────────────────────────────────────
# 定义：当前K线完全在前期K线范围内

RULE_INSIDE_BAR = {
    "name": "内切棒 / Inside Bar",
    "description": "盘整/蓄力信号，等待突破",
    "bullish_break": {
        "patterns": ["Inside Bar", "内切棒", "大阳线突破"],
        "signal": "大阳线上破 Inside Bar 上轨 → 买入",
        "direction": "LONG",
        "confidence": "中",
        "entry": "Inside Bar 高点上方1 tick 挂买单",
        "stop_loss": "Inside Bar 低点下方",
    },
    "bearish_break": {
        "patterns": ["Inside Bar", "内切棒", "大阴线跌破"],
        "signal": "大阴线下破 Inside Bar 下轨 → 卖出/做空",
        "direction": "SHORT",
        "confidence": "高",
        "entry": "Inside Bar 低点下方1 tick 挂止损卖单",
        "stop_loss": "Inside Bar 高点上方",
    },
}

# ── 规则8：Breakout Mode（开盘突破模式）──────────────────────────────
# 背景：开盘30分钟内高波动，常形成当日趋势

RULE_BREAKOUT_MODE = {
    "name": "开盘突破模式 / Breakout Mode",
    "description": "早盘高波动性，方向不明确，首根K线高低点为参考",
    "patterns": ["Breakout Mode", "开盘", "首根K线", "高波动"],
    "rules": {
        "首根K线": "当日所有波动的测量基准",
        "向上突破": "突破首根K线高点 → 顺势做多",
        "向下突破": "跌破首根K线低点 → 顺势做空",
        "突破失败": "大止损，突破失败后反向加仓解套",
    },
    "signal": "观察首根K线方向，等待突破确认",
    "direction": "WATCH",
    "confidence": "中",
    "warning": "高波动环境下止损巨大，谨慎仓位",
}

# ── 规则9：止损单挂法 ────────────────────────────────────────────────
# 核心：不在信号K线形成时入场，而是在确认后挂突破单

RULE_ORDER_ENTRY = {
    "name": "止损单入场法 / Stop Order Entry",
    "description": "不在信号K线时入场，在其外1 tick挂突破单",
    "bullish": {
        "entry": "信号K线高点上方1 tick → 买入止损单",
        "stop_loss": "信号K线低点下方1 tick",
    },
    "bearish": {
        "entry": "信号K线低点下方1 tick → 卖出止损单",
        "stop_loss": "信号K线高点上方1 tick",
    },
    "rationale": "给K线形成留出空间，避免被假突破扫止损",
}

# ── 规则10：80%法则 ────────────────────────────────────────────────
# 80%的初次突破会失败，只有20%会走出第二段

RULE_80_PERCENT = {
    "name": "80%法则 / 80% Rule",
    "description": "80%的突破初次尝试会失败",
    "implications": [
        "初次突破不追，等第二段确认",
        "如果第一段很弱（斜率平、成交量低），第二段概率更低",
        "真正的趋势需要第二段来确认",
    ],
    "pattern": "初次突破失败 → 等待 → 成功突破 → 第二段",
    "counter_intuitive": "突破时没有成交量 → 高概率反转",
}


# ══════════════════════════════════════════════════════════════════════════════
# 决策引擎
# ══════════════════════════════════════════════════════════════════════════════

def match_pattern(keywords: list[str], rule_keywords: list[str]) -> int:
    """计算关键词匹配数量"""
    matched = 0
    for kw in keywords:
        for rk in rule_keywords:
            if kw.lower() in rk.lower() or rk.lower() in kw.lower():
                matched += 1
                break
    return matched

def analyze_pattern(
    chart_description: str,
    market_environment: str,
    patterns_found: list[str],
    kline_signals: list[str] | None = None,
) -> DecisionResult:
    """
    P18 决策引擎主函数

    参数:
        chart_description: 图表文字描述（如Vision模型输出）
        market_environment: 市场环境（如"窄通道上涨"、"强空头趋势"）
        patterns_found: 发现的技术形态列表
        kline_signals: K线信号列表（如"大阳线"、"内切棒"）

    返回:
        DecisionResult: 综合决策结果
    """
    kline_signals = kline_signals or []
    all_inputs = [chart_description, market_environment] + patterns_found + kline_signals

    matched: list[PatternMatch] = []
    reasons: list[str] = []
    risk_warnings: list[str] = []

    # ── 1. Always In 判断（优先级最高）─────────────────────────────
    always_in_long_kw = RULE_ALWAYS_IN["always_in_long"]["patterns"]
    always_in_short_kw = RULE_ALWAYS_IN["always_in_short"]["patterns"]

    if match_pattern(all_inputs, always_in_short_kw) >= 2:
        matched.append(PatternMatch(
            name="Always In Short（始终看空）",
            direction=Direction.SHORT,
            confidence="高",
            signal="只能做空，严禁做多（Always In Short）",
            risk=["注意空头回补反弹"],
        ))
        reasons.append("Always In Short 规则：禁止逆势做多")
        risk_warnings.append("警惕空头回补导致的快速反弹")

    elif match_pattern(all_inputs, always_in_long_kw) >= 2:
        matched.append(PatternMatch(
            name="Always In Long（始终看多）",
            direction=Direction.LONG,
            confidence="高",
            signal="只做多/持有（Always In Long）",
        ))

    # ── 2. 窄通道（高置信度）────────────────────────────────────
    if match_pattern(all_inputs, RULE_NARROW_CHANNEL["bullish"]["patterns"]) >= 1:
        if "窄通道" in market_environment or "回撤极浅" in chart_description:
            matched.append(PatternMatch(
                name="窄通道顺势做多",
                direction=Direction.LONG,
                confidence="极高",
                signal="顺势做多，回踩趋势线买入",
                entry_condition=["价格回踩上涨趋势线", "缩量回调"],
                stop_loss="通道下轨下方",
            ))
            reasons.append("窄通道（胜率约75%，趋势极强）")
            risk_warnings.append("警惕 Climax 抛售高潮，到达目标位减仓")

    # ── 3. 惊喜K线 ─────────────────────────────────────────────
    surprise_bull = ["Bull Surprise", "惊喜阳线", "大阳线", "实体很大阳"]
    surprise_bear = ["Bear Surprise", "惊喜阴线", "大阴线", "收在最低"]

    if match_pattern(all_inputs, surprise_bull) >= 1:
        matched.append(PatternMatch(
            name="惊喜K线（Bull Surprise）",
            direction=Direction.LONG,
            confidence="中",
            signal="观望回调买入机会，不追高",
            entry_condition=["等待价格回踩突破点", "缩量回调不破前低"],
            stop_loss="惊喜K线低点下方",
        ))
        reasons.append("Bull Surprise → 等待回踩入场")

    if match_pattern(all_inputs, surprise_bear) >= 1:
        if "收在最低" in chart_description:
            matched.append(PatternMatch(
                name="惊喜K线（Bear Surprise）",
                direction=Direction.SHORT,
                confidence="高",
                signal="阴线低点下方1 tick 挂止损做空",
                entry_condition=["阴线收盘确认", "阴线低点下方1 tick 止损单"],
                stop_loss="阴线高点上方1 tick",
            ))
            reasons.append("Bear Surprise → 阴线低点下方止损做空")

    # ── 4. Inside Bar ───────────────────────────────────────────
    if "Inside Bar" in " ".join(all_inputs) or "内切棒" in " ".join(all_inputs):
        if "大阴线" in chart_description or "收在最低" in chart_description:
            matched.append(PatternMatch(
                name="内切棒（Inside Bar）",
                direction=Direction.SHORT,
                confidence="高",
                signal="Inside Bar 低点下方1 tick 挂卖出止损单",
                entry_condition=["Bar被完全包含", "收盘强势"],
                stop_loss="Inside Bar 高点上方",
            ))
            reasons.append("Inside Bar → 等待下破确认")

    # ── 5. Pain Trade ────────────────────────────────────────────
    if match_pattern(all_inputs, RULE_PAIN_TRADE["patterns"]) >= 1:
        reasons.append("Pain Trade 逻辑：被套者平仓会加速趋势，等待第二段")

    # ── 6. 80% 法则 ────────────────────────────────────────────
    if "80%" in " ".join(all_inputs) or "80%" in chart_description:
        reasons.append("80%法则：初次突破大概率失败，等待第二段确认")
        risk_warnings.append("第一段突破≠趋势确立，耐心等第二段")

    # ── 7. 止损单挂法 ──────────────────────────────────────────
    if "止损单" in " ".join(all_inputs):
        reasons.append("使用止损单入场：在信号K线外1 tick挂单，不在形成时追入")

    # ── 8. 突破失败 ────────────────────────────────────────────
    if "突破失败" in chart_description or "假突破" in chart_description:
        matched.append(PatternMatch(
            name="突破失败",
            direction=Direction.SHORT,
            confidence="高",
            signal="突破失败 → 方向反向",
            entry_condition=["等待确认柱收盘", "突破失败后二次确认"],
            risk=["假突破后快速反转"],
        ))
        reasons.append("突破失败 → 可能反向操作")

    # ── 综合决策 ──────────────────────────────────────────────
    # 优先级：SHORT > LONG > WATCH
    directions = [m.direction for m in matched]
    # 优先级：SHORT > LONG > WATCH
    priority = {Direction.SHORT: 2, Direction.LONG: 1, Direction.WATCH: 0, Direction.NONE: -1}
    primary = max(directions, key=lambda d: priority.get(d, -1), default=Direction.WATCH)

    # 置信度取最高
    conf_map = {"极高": 4, "高": 3, "中": 2, "低": 1}
    best_conf = max([conf_map.get(m.confidence, 0) for m in matched], default=0)
    confidence = "低"
    for k, v in conf_map.items():
        if v == best_conf:
            confidence = k
            break

    summary = ""
    if primary == Direction.SHORT:
        summary = f"做空信号（置信度:{confidence}），匹配{len(matched)}条规则"
    elif primary == Direction.LONG:
        summary = f"做多信号（置信度:{confidence}），匹配{len(matched)}条规则"
    else:
        summary = "观望为主，80%法则：等待第二段确认"

    return DecisionResult(
        video="P18_第二段陷阱",
        primary_signal=primary,
        confidence=confidence,
        matched_patterns=matched,
        reasons=reasons,
        risk_warnings=risk_warnings,
        summary=summary,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 快捷函数
# ══════════════════════════════════════════════════════════════════════════════

def quick_signal(env: str, patterns: list[str]) -> DecisionResult:
    """快速信号判断（仅传入市场环境和形态列表）"""
    return analyze_pattern(
        chart_description="",
        market_environment=env,
        patterns_found=patterns,
        kline_signals=[],
    )


# ══════════════════════════════════════════════════════════════════════════════
# 测试
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 测试用例
    test_cases = [
        ("强空头趋势，均线空头排列", ["Inside Bar", "大阴线收在最低"]),
        ("上升趋势，回撤极浅紧贴趋势线", ["窄通道", "回撤极浅"]),
        ("价格创新低，K线重叠无反弹", ["Always In Short"]),
        ("突破后再次回落", ["2nd Leg", "80%法则"]),
    ]

    print("P18 决策引擎测试")
    print("=" * 60)
    for env, patterns in test_cases:
        r = quick_signal(env, patterns)
        print(f"\n输入环境: {env}")
        print(f"发现形态: {patterns}")
        print(f"信号: {r.primary_signal.value} | 置信度: {r.confidence}")
        print(f"理由: {r.reasons}")
        if r.risk_warnings:
            print(f"风险提示: {r.risk_warnings}")
        if r.matched_patterns:
            for p in r.matched_patterns:
                print(f"  → {p.name}: {p.signal}")
