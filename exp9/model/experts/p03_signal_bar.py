#!/usr/bin/env python3
"""
P03 信号K线 & 入场(1) — 专家决策规则库
================================================
来源：方方土价格行为学 · 信号K线
视频：03-1.2.信号K线 & 入场(1)
已分析场景：4/16个关键场景成功（基于Whisper转写+字幕对齐）

核心主题：
  1. 信号K线（Signal Bar）定义与分类
  2. 趋势K线 vs 震荡K线的区分
  3. 入场方法：Buy Stop / Market Order / Sell Stop
  4. 信号K线的触发（Trigger）概念
  5. 背景（Context）重于信号（Signal）原则
  6. 强趋势中的 Always In 规则
  7. 分批建仓（Scaling In）
  8. 低点入场 vs 高点入场
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
    name: str
    direction: Direction
    confidence: str
    signal: str
    entry_condition: list[str] = field(default_factory=list)
    stop_loss: Optional[str] = None
    target: Optional[str] = None
    risk: list[str] = field(default_factory=list)

@dataclass
class DecisionResult:
    video: str = ""
    primary_signal: Direction = Direction.NONE
    confidence: str = "低"
    matched_patterns: list[PatternMatch] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    risk_warnings: list[str] = field(default_factory=list)
    summary: str = ""

# ══════════════════════════════════════════════════════════════════════════════
# P03 核心规则库
# ══════════════════════════════════════════════════════════════════════════════

# ── 规则1：信号K线（Signal Bar）定义 ────────────────────────────────
RULE_SIGNAL_BAR = {
    "name": "信号K线（Signal Bar）",
    "definition": "能够触发交易入场的K线，必须满足：实体大+收盘在极端位",
    "good_buy_signal": {
        "description": "好的做多信号K线",
        "patterns": [
            "大阳线", "收盘在最高", "无上影线", "实体大",
            "大阳线收在最高", "收盘在相对最高位置",
        ],
        "signal": "等待回调买入或突破入场",
        "direction": "LONG",
        "confidence": "高",
    },
    "good_sell_signal": {
        "description": "好的做空信号K线",
        "patterns": [
            "大阴线", "收盘在最低", "无下影线", "实体大",
            "大阴线收在最低", "收盘在相对最低位置",
        ],
        "signal": "等待反弹做空或突破入场",
        "direction": "SHORT",
        "confidence": "高",
    },
    "bad_signal": {
        "patterns": ["实体很小", "十字星", "影线很长", "收在中间位置"],
        "signal": "信号质量差，等待更好的信号",
        "direction": "WATCH",
        "confidence": "低",
    },
}

# ── 规则2：入场方法 ───────────────────────────────────────────────
RULE_ENTRY_METHOD = {
    "name": "入场方法选择",
    "buy_stop": {
        "description": "Buy Stop（买入止损单）：在信号K线高点上方1 tick挂单",
        "condition": "等信号K线确认后入场",
        "advantage": "避免假突破，给K线形成留出空间",
    },
    "market_order": {
        "description": "Market Order（市价单）：信号K线收盘时直接入场",
        "condition": "执行力强的交易员，信号质量极高时",
        "risk": "需要更大的止损空间",
    },
    "sell_stop": {
        "description": "Sell Stop（卖出止损单）：在信号K线低点下方1 tick挂单",
        "condition": "做空时在信号K线低点下方挂单",
    },
    "key_rule": "新手建议用Stop Order，等待触发，不在信号K形成时追入",
}

# ── 规则3：背景重于信号 ──────────────────────────────────────────
RULE_CONTEXT_OVER_SIGNAL = {
    "name": "背景（Context）重于信号（Signal）",
    "description": "市场环境/位置比信号K线本身更重要",
    "strong_trend_bull": {
        "description": "强上升趋势/上升通道",
        "patterns": ["强上升趋势", "上升通道", "只能做多", "Always In Long"],
        "signal": "任何回调都是买入机会，不追求完美信号",
        "direction": "LONG",
        "confidence": "高",
    },
    "strong_trend_bear": {
        "description": "强下降趋势/下降通道",
        "patterns": ["强下降趋势", "下降通道", "只能做空", "Always In Short"],
        "signal": "任何反弹都是做空机会，不抄底",
        "direction": "SHORT",
        "confidence": "高",
    },
    "weak_context": {
        "patterns": ["震荡区间", "横盘", "震荡"],
        "signal": "等待突破，不轻易追信号",
        "direction": "WATCH",
        "confidence": "中",
    },
}

# ── 规则4：信号K线的触发（Trigger）────────────────────────────────
RULE_SIGNAL_TRIGGER = {
    "name": "信号K线触发（Trigger）",
    "description": "信号K线本身不是入场指令，需要等待触发",
    "buy_trigger": {
        "patterns": ["信号K线", "等待触发", "Buy Stop"],
        "signal": "在信号K线高点上方1 tick挂Buy Stop，等待触发",
        "entry": "信号K线高点 + 1 tick",
        "stop": "信号K线低点下方1 tick",
    },
    "sell_trigger": {
        "patterns": ["信号K线", "等待触发", "Sell Stop"],
        "signal": "在信号K线低点下方1 tick挂Sell Stop，等待触发",
        "entry": "信号K线低点 - 1 tick",
        "stop": "信号K线高点上方1 tick",
    },
    "why_wait": "不在信号K线收盘时追入，因为突破可能失败，需要等待确认",
}

# ── 规则5：强趋势中的入场策略 ─────────────────────────────────────
RULE_STRONG_TREND_ENTRY = {
    "name": "强趋势中的入场策略",
    "description": "强趋势中不要等待完美信号，背景已提供足够优势",
    "bull_trend": {
        "patterns": ["强上升趋势", "Always In Long", "上升通道", "窄通道"],
        "signal": "任何入场点都可以做多",
        "direction": "LONG",
        "confidence": "高",
        "methods": [
            "Buy Stop（突破信号K线高点）",
            "Market Order（现价买入）",
            "Buy Limit（回踩支撑买入）",
            "Scaling In（分批建仓）",
        ],
    },
    "bear_trend": {
        "patterns": ["强下降趋势", "Always In Short", "下降通道"],
        "signal": "任何反弹都是做空机会",
        "direction": "SHORT",
        "confidence": "高",
    },
}

# ── 规则6：分批建仓（Scaling In）───────────────────────────────────
RULE_SCALING_IN = {
    "name": "分批建仓（Scaling In）",
    "description": "不确定时先小仓位，验证后加仓",
    "bull": {
        "patterns": ["小仓位", "分批建仓", "Scaling In", "逐步加仓"],
        "signal": "先用小仓位试探，确认后加仓",
        "direction": "LONG",
        "confidence": "中",
    },
    "key_advantage": "降低风险，提高容错率",
}

# ── 规则7：低点入场 vs 高点入场 ──────────────────────────────────
RULE_ENTRY_LEVEL = {
    "name": "低点入场 vs 高点入场",
    "description": "低点入场胜率更高，但盈亏比可能较差",
    "low_entry": {
        "description": "在震荡区间下沿或支撑位入场",
        "patterns": ["低点入场", "支撑位买入", "回踩买入"],
        "signal": "低点入场胜率高，止损小",
        "direction": "LONG",
        "confidence": "高",
        "tradeoff": "盈亏比可能较差",
    },
    "high_entry": {
        "description": "突破后追入",
        "patterns": ["突破买入", "追涨", "突破后买入"],
        "signal": "高点入场盈亏比好，但胜率低",
        "direction": "WATCH",
        "confidence": "低",
        "tradeoff": "胜率低，假突破多",
    },
    "rule": "新手优先选择低点入场（胜率高）",
}

# ══════════════════════════════════════════════════════════════════════════════
# 决策引擎
# ══════════════════════════════════════════════════════════════════════════════

def match_pattern(keywords: list[str], rule_keywords: list[str]) -> int:
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
    kline_signals = kline_signals or []
    all_inputs = [chart_description, market_environment] + patterns_found + kline_signals

    matched: list[PatternMatch] = []
    reasons: list[str] = []
    risk_warnings: list[str] = []

    # ── 1. 强趋势Always In ─────────────────────────────────────
    if match_pattern(all_inputs, RULE_CONTEXT_OVER_SIGNAL["strong_trend_bull"]["patterns"]) >= 2:
        matched.append(PatternMatch(
            name="强上升趋势（Always In Long）",
            direction=Direction.LONG,
            confidence="高",
            signal="强趋势中任何回调都是买入机会",
            entry_condition=["Buy Stop突破信号K线", "Market Order现价入场", "回踩支撑买入"],
        ))
        reasons.append("强上升趋势：只能做多不抄底")

    if match_pattern(all_inputs, RULE_CONTEXT_OVER_SIGNAL["strong_trend_bear"]["patterns"]) >= 2:
        matched.append(PatternMatch(
            name="强下降趋势（Always In Short）",
            direction=Direction.SHORT,
            confidence="高",
            signal="强下降趋势中任何反弹都是做空机会",
            entry_condition=["Sell Stop突破信号K线低点", "反弹至阻力位做空"],
        ))
        reasons.append("强下降趋势：只能做空不追空")

    # ── 2. 好信号K线 ─────────────────────────────────────────
    if match_pattern(all_inputs, RULE_SIGNAL_BAR["good_buy_signal"]["patterns"]) >= 1:
        if "上升趋势" in market_environment or "强" in chart_description:
            matched.append(PatternMatch(
                name="好的做多信号K线",
                direction=Direction.LONG,
                confidence="高",
                signal="大阳线收在最高 → 等待Buy Stop触发",
                entry_condition=["Buy Stop在信号K线高点上方1 tick", "止损在信号K线低点下方"],
            ))
            reasons.append("大阳线收在最高是好做多信号")

    if match_pattern(all_inputs, RULE_SIGNAL_BAR["good_sell_signal"]["patterns"]) >= 1:
        if "下降趋势" in market_environment:
            matched.append(PatternMatch(
                name="好的做空信号K线",
                direction=Direction.SHORT,
                confidence="高",
                signal="大阴线收在最低 → 等待Sell Stop触发",
                entry_condition=["Sell Stop在信号K线低点下方1 tick", "止损在信号K线高点上方"],
            ))
            reasons.append("大阴线收在最低是好做空信号")

    # ── 3. 坏信号K线 ─────────────────────────────────────────
    if match_pattern(all_inputs, RULE_SIGNAL_BAR["bad_signal"]["patterns"]) >= 2:
        matched.append(PatternMatch(
            name="信号质量差",
            direction=Direction.WATCH,
            confidence="低",
            signal="信号K线质量差，等待更好的机会",
        ))
        reasons.append("信号质量差（十字星/实体小）：不入场")

    # ── 4. Buy Stop入场 ───────────────────────────────────────
    if match_pattern(all_inputs, ["Buy Stop", "buy stop", "信号K线高点上方"]) >= 1:
        reasons.append("Buy Stop入场：在信号K线高点上方1 tick挂单等待触发")

    # ── 5. Scaling In ────────────────────────────────────────
    if match_pattern(all_inputs, RULE_SCALING_IN["bull"]["patterns"]) >= 1:
        reasons.append("Scaling In：先用小仓位试探，确认后加仓")

    # ── 6. 震荡区间 ────────────────────────────────────────
    if match_pattern(all_inputs, ["震荡", "横盘", "区间"]) >= 2:
        matched.append(PatternMatch(
            name="震荡区间",
            direction=Direction.WATCH,
            confidence="中",
            signal="震荡区间：等待突破，不轻易追信号",
        ))
        reasons.append("震荡区间：观望为主，高抛低吸或等突破")

    # ── 综合决策 ──────────────────────────────────────────────
    conf_map = {"极高": 4, "高": 3, "中": 2, "低": 1}
    priority = {Direction.SHORT: 2, Direction.LONG: 1, Direction.WATCH: 0, Direction.NONE: -1}

    if any(m.name in ("强上升趋势（Always In Long）", "强下降趋势（Always In Short）") for m in matched):
        primary = next(m.direction for m in matched if m.name in ("强上升趋势（Always In Long）", "强下降趋势（Always In Short）"))
    else:
        all_dirs = [m.direction for m in matched]
        primary = max(all_dirs, key=lambda d: priority.get(d, -1), default=Direction.WATCH)

    best = max([conf_map.get(m.confidence, 0) for m in matched], default=0)
    confidence = next((k for k, v in conf_map.items() if v == best), "低")

    return DecisionResult(
        video="P03_信号K线与入场",
        primary_signal=primary,
        confidence=confidence,
        matched_patterns=matched,
        reasons=reasons,
        risk_warnings=risk_warnings,
        summary=f"信号：{primary.value}（置信度：{confidence}）",
    )


def quick_signal(env: str, patterns: list[str]) -> DecisionResult:
    return analyze_pattern(
        chart_description="",
        market_environment=env,
        patterns_found=patterns,
        kline_signals=[],
    )


if __name__ == "__main__":
    tests = [
        ("强上升趋势", ["Buy Stop", "Always In Long", "上升通道"]),
        ("强下降趋势", ["Always In Short", "下降通道"]),
        ("震荡市场", ["震荡区间", "十字星"]),
        ("上升趋势回调", ["大阳线", "回踩买入"]),
    ]
    print("P03 决策引擎测试")
    print("=" * 50)
    for env, patterns in tests:
        r = quick_signal(env, patterns)
        print(f"\n环境: {env}")
        print(f"信号: {r.primary_signal.value} | {r.confidence}")
        print(f"理由: {r.reasons}")
        if r.matched_patterns:
            for p in r.matched_patterns:
                print(f"  → {p.name}: {p.signal}")
