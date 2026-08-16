#!/usr/bin/env python3
"""
P02 蜡烛图基础 — 专家决策规则库
================================================
来源：方方土价格行为学 · 蜡烛图
视频：02-1.1.蜡烛图- 每天都在看，却忽视了K线传达的真正信息
已分析场景：10个关键场景

核心主题：
  1. K线四要素：开盘价、收盘价、最高价、最低价
  2. 趋势K线（Trend Bar）vs 震荡K线（Trading Range Bar）
  3. 十字星（Doji）的判断方法
  4. 大周期K线 → 小周期走势的推断
  5. 开盘价磁铁理论
  6. 多周期共振：上升/下降/震荡背景下的不同策略
  7. 早盘反转的概率判断
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
# P02 核心规则库
# ══════════════════════════════════════════════════════════════════════════════

# ── 规则1：趋势K线 vs 震荡K线 ─────────────────────────────────────────
RULE_TREND_VS_TRADING = {
    "name": "趋势K线 vs 震荡K线",
    "trend_bar": {
        "description": "实体大，影线短 → 趋势动能强",
        "bullish": {
            "patterns": ["大阳线", "实体大", "影线短", "Trend Bar", "Bull Trend"],
            "signal": "顺势做多",
            "direction": "LONG",
            "confidence": "中",
        },
        "bearish": {
            "patterns": ["大阴线", "实体大", "影线短", "Trend Bar", "Bear Trend"],
            "signal": "顺势做空",
            "direction": "SHORT",
            "confidence": "中",
        },
    },
    "trading_range_bar": {
        "description": "实体小，影线长 → 动能枯竭，趋势暂停",
        "patterns": ["十字星", "实体小", "影线长", "Doji", "上下影线很长"],
        "signal": "观望，等待突破确认",
        "direction": "WATCH",
        "confidence": "高",
        "rule": "十字星本身不产生信号，需要结合背景判断方向",
    },
}

# ── 规则2：早盘反转概率 ──────────────────────────────────────────────
RULE_MORNING_REVERSAL = {
    "name": "早盘反转判断",
    "description": "大阳线/大阴线出现后，关注收盘位置判断反转概率",
    "bullish_greed": {
        "patterns": ["早盘大涨", "大阳线后收阴", "冲高回落", "长上影线"],
        "signal": "早盘大涨后收阴 → 卖出/做空",
        "direction": "SHORT",
        "confidence": "高",
        "entry": "反转K线高点上方1 tick止损单",
        "rule": "开盘价上方1%的高点形成当日阻力",
    },
    "bearish_fear": {
        "patterns": ["早盘大跌", "大阴线后收阳", "探底回升", "长下影线"],
        "signal": "早盘大跌后收阳 → 买入/做多",
        "direction": "LONG",
        "confidence": "高",
        "entry": "反转K线低点下方1 tick止损单",
    },
    "statistics": {
        "reversal_prob": "早盘趋势够强时，反转概率约90%",
        "hold_prob": "保持趋势概率约10%",
    },
}

# ── 规则3：开盘价磁铁 ────────────────────────────────────────────────
RULE_OPEN_MAGNET = {
    "name": "开盘价磁铁 / Open as Magnet",
    "description": "开盘价是一个目标位，价格有回归开盘价的倾向",
    "bullish_magnet": {
        "patterns": ["开盘价", "磁铁", "magnet", "回归开盘价"],
        "signal": "当日价格倾向于回归开盘价",
        "direction": "WATCH",
        "confidence": "高",
        "application": [
            "开盘大跌后收阳 → 目标是开盘价",
            "开盘大涨后收阴 → 目标是开盘价",
            "震荡行情中，价格围绕开盘价上下波动",
        ],
    },
}

# ── 规则4：十字星判断 ────────────────────────────────────────────────
RULE_DOJI = {
    "name": "十字星 / Doji",
    "description": "实体极小，高低点差距大的K线",
    "patterns": ["十字星", "Doji", "实体很小", "高低点差距大"],
    "signal": "本身不产生信号，需结合背景判断",
    "direction": "WATCH",
    "confidence": "高",
    "rule": "十字星高低点至少有一根影线特别长",
    "context_rules": {
        "上升趋势中": "十字星可能是反转信号（多头动能衰竭）",
        "下降趋势中": "十字星可能是反弹结束信号（空头动能衰竭）",
        "震荡区间中": "十字星是正常现象，不改变区间性质",
    },
}

# ── 规则5：多周期分析 ───────────────────────────────────────────────
RULE_MULTI_TIMEFRAME = {
    "name": "多周期共振分析",
    "description": "大周期定趋势，小周期找入场点",
    "steps": [
        "1. 大周期（日线/4小时）：判断整体趋势方向",
        "2. 小周期（5分钟/15分钟）：在趋势方向上找入场点",
    ],
    "scenarios": {
        "上升趋势": "大阳线回调低点 / 回踩趋势线买入",
        "下降趋势": "大阴线反弹高点 / 反弹至阻力位做空",
        "震荡区间": "高抛低吸，等待突破确认",
    },
}

# ── 规则6：Bull Trap（多头陷阱）─────────────────────────────────────
RULE_BULL_TRAP = {
    "name": "多头陷阱 / Bull Trap",
    "description": "早盘大涨吸引散户追入，随后反转下跌",
    "patterns": [
        "早盘大涨", "超过日均波动", "1%涨幅",
        "收成大阴线", "长上影线", "收盘在最低附近",
    ],
    "signal": "做空（空头陷阱成功）",
    "direction": "SHORT",
    "confidence": "高",
    "entry": "收盘价下方1 tick 或 突破早盘低点时入场",
    "stop_loss": "早盘高点上方",
    "rule": "早盘涨幅超过日均波动（ATR）→ 高概率反转",
}

# ── 规则7：K线内部结构（大周期推断小周期）───────────────────────────
RULE_CANDLE_INTERNAL = {
    "name": "K线内部结构 / Candle Microstructure",
    "description": "日K线的形成过程 → 推断当日走势",
    "applications": [
        ("大阳线（收盘在最高）", "早盘回调 → 尾盘上涨，全程多方占优"),
        ("大阴线（收盘在最低）", "早盘冲高诱多 → 尾盘下跌，全程空方占优"),
        ("带长下影线的K线", "早盘下跌 → 多头抵抗 → 收盘反弹"),
        ("带长上影线的K线", "早盘上涨 → 空头抵抗 → 收盘回落"),
    ],
}

# ── 规则8：信号K线优先级 ─────────────────────────────────────────────
RULE_SIGNAL_HIERARCHY = {
    "name": "信号K线优先级（背景>信号）",
    "description": "背景（Context）重于信号（Signal）。弱信号在强背景中往往失败。",
    "bullish": {
        "description": "强信号K线：实体大、收盘在极端位、有背景支撑",
        "patterns": ["大实体阳线", "收盘在最高", "背景强支撑"],
    },
    "bearish": {
        "description": "弱信号K线：实体小、影线长、背景不支持",
        "patterns": ["实体很小", "上下影线很长", "背景不支持", "十字星"],
    },
    "rule": "先判断背景（趋势/位置），再看信号质量。弱信号+强背景 = 等待反向机会。",
}

# ── 规则9：空头陷阱（早盘小跌）─────────────────────────────────────
# 来源：P02 Scene 04 对齐分析
RULE_BEAR_TRAP_MORNING = {
    "name": "早盘空头陷阱",
    "description": "强趋势中早盘的小幅下跌，是机构压价吸筹的空头陷阱",
    "patterns": [
        "早盘小跌", "开盘下跌", "下影线",
        "空头陷阱", "强趋势中的小回调", "假突破",
    ],
    "signal": "逢低买入（不要做空）",
    "direction": "LONG",
    "confidence": "高",
    "entry": "等反转信号K出现，在其高点上方1 tick挂Buy Stop",
    "background": "日线/大周期强上涨趋势",
    "key_rule": "开盘一个小下跌都是空头陷阱，只是很多人不知道",
}

# ── 规则10：ATR量化反转判断 ───────────────────────────────────────
# 来源：P02 Scene 11 对齐分析
RULE_ATR反转 = {
    "name": "ATR量化反转判断",
    "description": "早盘波动超过日均ATR越多，完全反转概率越低",
    "thresholds": {
        "超过ATR_100%": "难以完全反转，更可能收十字星",
        "超过ATR_200%": "大概率V型反转",
        "小幅波动": "反转概率更高，可以跌更多",
    },
    "reference": "标普500日均波动约0.8%，早盘涨1%即超过ATR",
    "signal": "WATCH",
    "confidence": "中",
}

# ── 规则11：多周期阻力共振 ──────────────────────────────────────
# 来源：P02 Scene 16 对齐分析
RULE_MTF_RESISTANCE = {
    "name": "多周期阻力共振",
    "description": "小周期反弹触及大周期EMA20，是强阻力区",
    "patterns": [
        "EMA20", "20周期均线", "均线阻力",
        "60分钟", "反弹受阻", "多周期",
    ],
    "signal": "大周期下跌趋势中，价格反弹至EMA20受阻 → 做空",
    "direction": "SHORT",
    "confidence": "高",
    "entry": "等待价格反弹至EMA20附近出现空头信号K",
    "stop_loss": "EMA20上方",
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
    """
    P02 决策引擎主函数

    参数:
        chart_description: 图表文字描述
        market_environment: 市场环境（上升趋势/下降趋势/震荡）
        patterns_found: 发现的技术形态列表
        kline_signals: K线信号列表
    """
    kline_signals = kline_signals or []
    all_inputs = [chart_description, market_environment] + patterns_found + kline_signals

    matched: list[PatternMatch] = []
    reasons: list[str] = []
    risk_warnings: list[str] = []

    # ── 1. 早盘空头陷阱（强趋势中的小跌）────────────────────────
    if match_pattern(all_inputs, RULE_BEAR_TRAP_MORNING["patterns"]) >= 2:
        if "上升趋势" in market_environment or "强" in chart_description:
            matched.append(PatternMatch(
                name="早盘空头陷阱",
                direction=Direction.LONG,
                confidence="高",
                signal="逢低买入，不做空（空头陷阱）",
                entry_condition=["等反转信号K", "信号K高点上方1 tick Buy Stop"],
                risk=["若趋势真的反转，需止损"],
            ))
            reasons.append("早盘小跌是空头陷阱，机构压价吸筹")

    # ── 2. Bull Trap（多头陷阱）────────────────────────────────
    if match_pattern(all_inputs, RULE_BULL_TRAP["patterns"]) >= 2:
        matched.append(PatternMatch(
            name="多头陷阱（Bull Trap）",
            direction=Direction.SHORT,
            confidence="高",
            signal="早盘大涨后反转 → 做空",
            entry_condition=["收盘在最低附近", "长上影线"],
            stop_loss="早盘高点上方",
        ))
        reasons.append("Bull Trap：早盘涨幅超过ATR，高概率反转")

    # ── 3. 背景优先于信号（核心新规则）──────────────────────────
    weak_signal = match_pattern(all_inputs, ["实体很小", "上下影线很长", "十字星", "小阴线", "小阳线"])
    strong_context = match_pattern(all_inputs, ["强上升趋势", "连续阳线", "上涨背景", "强趋势", "连续上涨"])
    if weak_signal >= 1 and strong_context >= 1:
        matched.append(PatternMatch(
            name="背景优先于信号",
            direction=Direction.LONG,
            confidence="高",
            signal="弱信号+强背景 → 不做空，等回调买入",
            entry_condition=["等待回调低点买入"],
        ))
        reasons.append("背景>信号：弱反转信号在强趋势中往往失败，反向机会更好")

    # ── 4. 趋势K线 ───────────────────────────────────────────
    if match_pattern(all_inputs, ["大阳线", "实体大 阳线", "Bull Trend"]) >= 1:
        if "上升趋势" in market_environment or "上涨" in chart_description:
            matched.append(PatternMatch(
                name="趋势K线（大阳线）",
                direction=Direction.LONG,
                confidence="中",
                signal="顺势做多，等待回调入场",
            ))
            reasons.append("大阳线确认多头趋势")

    if match_pattern(all_inputs, ["大阴线", "实体大 阴线", "Bear Trend"]) >= 1:
        if "下降趋势" in market_environment:
            matched.append(PatternMatch(
                name="趋势K线（大阴线）",
                direction=Direction.SHORT,
                confidence="中",
                signal="顺势做空，等待反弹入场",
            ))
            reasons.append("大阴线确认空头趋势")

    # ── 5. 十字星 ──────────────────────────────────────────────
    if match_pattern(all_inputs, RULE_DOJI["patterns"]) >= 1:
        matched.append(PatternMatch(
            name="十字星（Doji）",
            direction=Direction.WATCH,
            confidence="高",
            signal="本身不产生信号，需结合背景判断方向",
        ))
        reasons.append("十字星 → 观望，等待背景指引方向")

    # ── 6. 开盘价磁铁 ──────────────────────────────────────────
    if match_pattern(all_inputs, ["开盘价", "磁铁", "magnet", "回归开盘"]) >= 1:
        reasons.append("开盘价磁铁：价格有回归开盘价倾向（震荡区间中尤为明显）")

    # ── 7. ATR量化反转 ────────────────────────────────────────
    if match_pattern(all_inputs, ["超过ATR", "超过日均波动", "0.8%", "1%", "早盘波动"]) >= 1:
        reasons.append("ATR量化：早盘超过ATR 100%→更难完全反转，更可能收十字星")

    # ── 8. 多周期EMA阻力共振 ───────────────────────────────────
    if match_pattern(all_inputs, RULE_MTF_RESISTANCE["patterns"]) >= 1:
        matched.append(PatternMatch(
            name="多周期阻力共振（EMA20）",
            direction=Direction.SHORT,
            confidence="高",
            signal="价格反弹至EMA20受阻 → 做空",
            entry_condition=["价格反弹至EMA20附近出现空头信号"],
            stop_loss="EMA20上方",
        ))
        reasons.append("多周期共振：大周期EMA20是强阻力，小周期反弹至此受阻做空")

    # ── 9. 多周期背景判断 ───────────────────────────────────────
    if "上升趋势" in market_environment:
        reasons.append("上升趋势背景 → 逢低买入，不追高")
    elif "下降趋势" in market_environment:
        reasons.append("下降趋势背景 → 逢高做空，不抄底")
    elif "震荡" in market_environment:
        reasons.append("震荡背景 → 高抛低吸，关注开盘价磁铁效应")

    # ── 综合决策 ────────────────────────────────────────────────
    conf_map = {"极高": 4, "高": 3, "中": 2, "低": 1}
    # 特殊：早盘空头陷阱 → 强制LONG，不被SHORT覆盖
    if any(m.name == "早盘空头陷阱" for m in matched):
        primary = Direction.LONG
        best = max([conf_map.get(m.confidence, 0) for m in matched], default=0)
        confidence = next((k for k, v in conf_map.items() if v == best), "中")
    else:
        priority = {Direction.SHORT: 2, Direction.LONG: 1, Direction.WATCH: 0, Direction.NONE: -1}
        all_dirs = [m.direction for m in matched]
        primary = max(all_dirs, key=lambda d: priority.get(d, -1), default=Direction.WATCH)
        best = max([conf_map.get(m.confidence, 0) for m in matched], default=0)
        confidence = next((k for k, v in conf_map.items() if v == best), "低")

    summary_map = {
        Direction.SHORT: f"做空信号（置信度:{confidence}），匹配{len(matched)}条规则",
        Direction.LONG: f"做多信号（置信度:{confidence}），匹配{len(matched)}条规则",
        Direction.WATCH: "观望为主，等待确认信号",
    }

    return DecisionResult(
        video="P02_蜡烛图基础",
        primary_signal=primary,
        confidence=confidence,
        matched_patterns=matched,
        reasons=reasons,
        risk_warnings=risk_warnings,
        summary=summary_map.get(primary, ""),
    )


def quick_signal(env: str, patterns: list[str]) -> DecisionResult:
    """快速信号判断"""
    return analyze_pattern(
        chart_description="",
        market_environment=env,
        patterns_found=patterns,
        kline_signals=[],
    )


if __name__ == "__main__":
    test_cases = [
        ("上升趋势", ["大阳线", "趋势K线"]),
        ("下降趋势", ["大阴线", "趋势K线"]),
        ("早盘大涨后反转", ["早盘大涨", "收成大阴线", "长上影线"]),
        ("震荡市场", ["十字星", "实体小"]),
    ]
    print("P02 决策引擎测试")
    print("=" * 50)
    for env, patterns in test_cases:
        r = quick_signal(env, patterns)
        print(f"\n环境: {env}")
        print(f"形态: {patterns}")
        print(f"信号: {r.primary_signal.value} | {r.confidence}")
        print(f"理由: {r.reasons}")
        if r.matched_patterns:
            for p in r.matched_patterns:
                print(f"  → {p.name}: {p.signal}")
