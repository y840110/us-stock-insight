#!/usr/bin/env python3
"""
P04 Market Cycle 市场周期 — 专家决策规则库
================================================
来源：方方土价格行为学 · Market Cycle
视频：04-03MarketCycle市场周期
已分析场景：8/25个关键场景（基于Whisper字幕+Vision分析）

核心主题：
  1. 市场四种周期结构（突破/窄通道/宽通道/震荡区间）
  2. 趋势从强到弱的演变规律
  3. Always In Long/Short 原则
  4. 止损设置：永远放在起涨/起跌点
  5. 仓位管理：止损距离决定仓位大小
  6. 80%规律：惯性定律
  7. 震荡区间的交易策略
  8. 多时间框架的周期共振
  9. 二元决策框架
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

# ══════════════════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════════════════

class MarketCycle(Enum):
    BULL_BREAKOUT      = "多头突破"
    BULL_TIGHT_CHANNEL  = "多头窄通道"
    BULL_WIDE_CHANNEL   = "多头宽通道"
    BEAR_BREAKOUT       = "空头突破"
    BEAR_TIGHT_CHANNEL  = "空头窄通道"
    BEAR_WIDE_CHANNEL   = "空头宽通道"
    TRADING_RANGE_WIDE  = "震荡宽区间"
    TRADING_RANGE_TIGHT = "震荡窄区间"
    UNKNOWN             = "不确定"

class Direction(Enum):
    LONG   = "LONG"
    SHORT  = "SHORT"
    WATCH  = "WATCH"
    NONE   = "NONE"

@dataclass
class CycleMatch:
    name: str
    cycle: MarketCycle
    direction: Direction
    confidence: str
    signal: str
    entry_condition: list[str] = field(default_factory=list)
    stop_loss: Optional[str] = None
    position_note: Optional[str] = None

@dataclass
class DecisionResult:
    video: str = ""
    primary_cycle: MarketCycle = MarketCycle.UNKNOWN
    primary_signal: Direction = Direction.NONE
    confidence: str = "低"
    matched_patterns: list[CycleMatch] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    risk_warnings: list[str] = field(default_factory=list)
    stop_loss_rule: str = ""
    position_rule: str = ""
    summary: str = ""

# ══════════════════════════════════════════════════════════════════════════════
# 核心规则库
# ══════════════════════════════════════════════════════════════════════════════

# ── 规则1：市场周期分类 ──────────────────────────────────────────────
RULE_CYCLE_CLASSIFY = {
    "bull_breakout": {
        "patterns": ["连续大阳线", "无回调", "几乎无回调", "Always In Long", "多头突破", "起涨点"],
        "cycle": MarketCycle.BULL_BREAKOUT,
        "direction": Direction.LONG,
        "confidence": "极高",
    },
    "bull_tight_channel": {
        "patterns": ["窄通道", "紧贴趋势线", "回调1-3根", "1到3根", "回调很短", "回调幅度小"],
        "cycle": MarketCycle.BULL_TIGHT_CHANNEL,
        "direction": Direction.LONG,
        "confidence": "高",
    },
    "bull_wide_channel": {
        "patterns": ["宽通道", "回调幅度大", "高低点抬高", "多空都有机会", "回调整合"],
        "cycle": MarketCycle.BULL_WIDE_CHANNEL,
        "direction": Direction.LONG,
        "confidence": "中",
    },
    "bear_breakout": {
        "patterns": ["连续大阴线", "无反弹", "几乎无反弹", "Always In Short", "空头突破", "起跌点"],
        "cycle": MarketCycle.BEAR_BREAKOUT,
        "direction": Direction.SHORT,
        "confidence": "极高",
    },
    "bear_tight_channel": {
        "patterns": ["空头窄通道", "紧贴下降趋势线", "反弹很少", "1到3根K线"],
        "cycle": MarketCycle.BEAR_TIGHT_CHANNEL,
        "direction": Direction.SHORT,
        "confidence": "高",
    },
    "bear_wide_channel": {
        "patterns": ["空头宽通道", "反弹幅度大", "高低点降低"],
        "cycle": MarketCycle.BEAR_WIDE_CHANNEL,
        "direction": Direction.SHORT,
        "confidence": "中",
    },
    "trading_range_wide": {
        "patterns": ["震荡区间", "横盘", "高抛低吸", "buy low sell high", "BLSHS"],
        "cycle": MarketCycle.TRADING_RANGE_WIDE,
        "direction": Direction.WATCH,
        "confidence": "中",
    },
    "trading_range_tight": {
        "patterns": ["窄区间", "区间很窄", "没什么利润"],
        "cycle": MarketCycle.TRADING_RANGE_TIGHT,
        "direction": Direction.WATCH,
        "confidence": "低",
    },
}

# ── 规则2：止损设置 ─────────────────────────────────────────────────
RULE_STOP_LOSS = {
    "name": "止损设置原则",
    "起涨点": {
        "description": "多头趋势中，止损永远放在突破的起涨点（最低点）下方",
        "logic": "只有最低点被跌破，才能说上涨趋势结束",
        "for_new": "新开仓直接放在起涨点下方",
        "for_held": "已持仓可将止损移动到新的起涨点上方（追踪止损）",
    },
    "起跌点": {
        "description": "空头趋势中，止损永远放在突破的起跌点（最高点）上方",
        "logic": "只有最高点被突破，才能说下跌趋势结束",
    },
    "仓位原则": {
        "止损5元": "可买100股（最大亏损500元）",
        "止损10元": "只能买50股",
        "止损20元": "只能买25股",
        "原则": "止损距离越大，仓位必须越轻；不愿减仓则等待更好的机会",
    },
}

# ── 规则3：惯性定律（80%规律）────────────────────────────────────────
RULE_INERTIA = {
    "name": "惯性定律（80%规律）",
    "description": "市场具有惯性，80%尝试打破当前格局的行为会失败",
    "bull_trend": "80%的回调尝试会失败，上涨趋势继续",
    "bear_trend": "80%的反弹尝试会失败，下跌趋势继续",
    "trading_range": "80%的突破尝试是假突破",
    "trade_implication": "顺势交易相信惯性，逆势交易需等待明确信号",
}

# ── 规则4：周期演变规律 ─────────────────────────────────────────────
RULE_CYCLE_EVOLUTION = {
    "sequence": ["多头突破 → 多头窄通道 → 多头宽通道 → 震荡区间 → 新趋势"],
    "from_strong_to_weak": "趋势从强变弱，必然最终结束",
    "spike_channel": "强趋势以突破开始，会转变成通道",
    "sell_climax": "连续大阳线后往往是sell climax（卖出高潮），趋势不可持续",
    "buy_climax": "连续大阴线后往往是buy climax（买入高潮），趋势不可持续",
}

# ── 规则5：震荡区间策略 ─────────────────────────────────────────────
RULE_TRADING_RANGE = {
    "name": "震荡区间交易",
    "buy_low_sell_high": {
        "description": "区间下沿做多，上沿做空",
        "win": "盈亏比好（止损小，目标大）",
        "risk": "有很多假突破，需要把止损放大一点",
    },
    "range_width": {
        "窄区间": "剥头皮利润少，宁愿等突破做波段",
        "宽区间": "高抛低吸利润大，可以做",
    },
    "range_duration": {
        "刚开始": "高抛低吸",
        "持续很久（>20根K线）": "被突破概率增大，等待突破做趋势",
    },
    "measured_move": "真突破后，目标=区间幅度翻倍",
}

# ── 规则6：多时间框架 ───────────────────────────────────────────────
RULE_MULTI_TIMEFRAME = {
    "name": "周期共振",
    "rule": "大级别的突破 → 小级别是窄通道 → 更小级别是宽通道",
    "reverse": "小级别的宽通道 → 大级别是窄通道 → 更大级别是突破",
    "trade_level": "主要交易级别需要参考大一个级别的结构",
}

# ══════════════════════════════════════════════════════════════════════════════
# 决策引擎
# ══════════════════════════════════════════════════════════════════════════════

def match_score(keywords: list[str], rule_keywords: list[str]) -> int:
    score = 0
    for kw in keywords:
        for rk in rule_keywords:
            if kw.lower() in rk.lower() or rk.lower() in kw.lower():
                score += 1
                break
    return score

def classify_market_cycle(
    trend: str = "",        # 上涨/下跌/横盘
    channel_type: str = "", # 突破/窄通道/宽通道/震荡
    has_deep_pullback: bool = False,
    pullback_klines: int = 0,
    is_new_high: bool = False,
) -> DecisionResult:
    """
    快速分类市场周期
    """
    keywords = [trend, channel_type]
    if has_deep_pullback:
        keywords.append("深幅回调")
    if pullback_klines > 0:
        if pullback_klines <= 3:
            keywords.append("回调1-3根")
        else:
            keywords.append("回调幅度大")
    if is_new_high:
        keywords.append("创新高")

    matched: list[CycleMatch] = []
    reasons: list[str] = []

    # ── 1. 多头突破 ─────────────────────────────────────────
    if "上涨" in trend and match_score(keywords, RULE_CYCLE_CLASSIFY["bull_breakout"]["patterns"]) >= 1:
        if "无回调" in trend or "无" in " ".join(keywords):
            matched.append(CycleMatch(
                name="多头突破",
                cycle=MarketCycle.BULL_BREAKOUT,
                direction=Direction.LONG,
                confidence="极高",
                signal="Always In Long，突破入场",
                entry_condition=["波段持有", "止损在起涨点下方"],
                stop_loss="起涨点（最低点）下方",
                position_note="不止损太远，追高要减仓",
            ))
            reasons.append("连续大阳线无回调 → 多头突破 → Always In Long")

    # ── 2. 多头窄通道 ────────────────────────────────────────
    if "上涨" in trend and match_score(keywords, RULE_CYCLE_CLASSIFY["bull_tight_channel"]["patterns"]) >= 1:
        if pullback_klines <= 3 or "窄" in channel_type:
            matched.append(CycleMatch(
                name="多头窄通道",
                cycle=MarketCycle.BULL_TIGHT_CHANNEL,
                direction=Direction.LONG,
                confidence="高",
                signal="紧贴上升趋势线，回调买入",
                entry_condition=["回调低点买入", "波段持有"],
                stop_loss="起涨点下方",
            ))
            reasons.append("紧贴趋势线 + 回调1-3根K线 → 多头窄通道 → 只能做多")

    # ── 3. 多头宽通道 ────────────────────────────────────────
    if "上涨" in trend and has_deep_pullback:
        matched.append(CycleMatch(
            name="多头宽通道",
            cycle=MarketCycle.BULL_WIDE_CHANNEL,
            direction=Direction.LONG,
            confidence="中",
            signal="回调幅度大，多空都有机会，顺势波段最好",
            entry_condition=["回踩支撑买入", "止损在起涨点"],
            position_note="高位入场要减仓",
        ))
        reasons.append("回调幅度大 → 多头宽通道 → 高低点仍在上移")

    # ── 4. 空头突破 ─────────────────────────────────────────
    if "下跌" in trend and match_score(keywords, RULE_CYCLE_CLASSIFY["bear_breakout"]["patterns"]) >= 1:
        matched.append(CycleMatch(
            name="空头突破",
            cycle=MarketCycle.BEAR_BREAKOUT,
            direction=Direction.SHORT,
            confidence="极高",
            signal="Always In Short，突破入场",
            entry_condition=["波段持有", "止损在起跌点上方"],
            stop_loss="起跌点（最高点）上方",
        ))
        reasons.append("连续大阴线无反弹 → 空头突破 → Always In Short")

    # ── 5. 空头窄通道 ────────────────────────────────────────
    if "下跌" in trend and match_score(keywords, RULE_CYCLE_CLASSIFY["bear_tight_channel"]["patterns"]) >= 1:
        matched.append(CycleMatch(
            name="空头窄通道",
            cycle=MarketCycle.BEAR_TIGHT_CHANNEL,
            direction=Direction.SHORT,
            confidence="高",
            signal="紧贴下降趋势线，反弹做空",
            entry_condition=["反弹高点做空", "波段持有"],
            stop_loss="起跌点上方",
        ))
        reasons.append("紧贴趋势线 + 反弹很少 → 空头窄通道 → 只能做空")

    # ── 6. 震荡区间 ──────────────────────────────────────────
    if "横盘" in trend or "震荡" in trend:
        if has_deep_pullback or "宽" in channel_type:
            matched.append(CycleMatch(
                name="震荡宽区间",
                cycle=MarketCycle.TRADING_RANGE_WIDE,
                direction=Direction.WATCH,
                confidence="中",
                signal="高抛低吸（BLSHS），区间操作",
                entry_condition=["下沿买入，上沿卖出"],
            ))
            reasons.append("横盘 + 宽幅波动 → 震荡宽区间 → 高抛低吸")
        else:
            matched.append(CycleMatch(
                name="震荡窄区间",
                cycle=MarketCycle.TRADING_RANGE_TIGHT,
                direction=Direction.WATCH,
                confidence="低",
                signal="区间太窄，等突破",
            ))
            reasons.append("横盘 + 窄幅波动 → 震荡窄区间 → 等突破")

    # ── 综合决策 ────────────────────────────────────────────────
    priority = {Direction.SHORT: 2, Direction.LONG: 1, Direction.WATCH: 0, Direction.NONE: -1}
    if matched:
        best = max(matched, key=lambda m: priority.get(m.direction, -1))
        # 置信度
        conf_map = {"极高": 4, "高": 3, "中": 2, "低": 1}
        confidence = next((k for k, v in conf_map.items() if v == max(conf_map.get(m.confidence, 0) for m in matched)), "中")
        return DecisionResult(
            video="P04_Market_Cycle",
            primary_cycle=best.cycle,
            primary_signal=best.direction,
            confidence=best.confidence,
            matched_patterns=matched,
            reasons=reasons,
            stop_loss_rule=best.stop_loss or "放在起涨/起跌点",
            position_rule=best.position_note or "根据止损距离确定仓位",
            summary=f"周期：{best.cycle.value} | 信号：{best.direction.value}（置信度：{best.confidence}）",
        )

    return DecisionResult(
        video="P04_Market_Cycle",
        primary_signal=Direction.WATCH,
        confidence="低",
        reasons=["无法确定市场周期，需要更多信息"],
        summary="信号：WATCH（不确定）",
    )


def analyze_cycle_phase(
    market_environment: str,
    pullback_depth: str = "",
    time_in_cycle: str = "",
    patterns: list[str] | None = None,
) -> DecisionResult:
    """
    完整分析周期阶段（含止损和仓位建议）
    """
    patterns = patterns or []
    all_inputs = [market_environment, pullback_depth, time_in_cycle] + patterns

    matched: list[CycleMatch] = []
    reasons: list[str] = []
    risk_warnings: list[str] = []

    # ── 趋势方向判断 ────────────────────────────────────────
    is_bull = any(kw in market_environment for kw in ["上涨", "多头", "上升", "long"])
    is_bear = any(kw in market_environment for kw in ["下跌", "空头", "下降", "short"])
    is_range = any(kw in market_environment for kw in ["震荡", "横盘", "区间", "range"])

    # ── 周期强度判断 ────────────────────────────────────────
    is_breakout = any(kw in market_environment for kw in ["突破", "breakout", "无回调"])
    is_tight = any(kw in market_environment for kw in ["窄通道", "tight", "1-3根", "回调很浅"])
    is_wide = any(kw in market_environment for kw in ["宽通道", "wide", "回调幅度大"])

    # ── 多头周期 ──────────────────────────────────────────
    if is_bull:
        if is_breakout:
            matched.append(CycleMatch(
                name="多头突破",
                cycle=MarketCycle.BULL_BREAKOUT,
                direction=Direction.LONG,
                confidence="极高",
                signal="波段持有，不追高",
                entry_condition=["Buy Stop在信号K线高点", "止损在起涨点下方"],
                stop_loss="起涨点（最低点）下方",
                position_note="止损距离大时要减仓",
            ))
            reasons.append("连续大阳线无回调 → 多头突破")

        if is_tight or "窄" in market_environment:
            matched.append(CycleMatch(
                name="多头窄通道",
                cycle=MarketCycle.BULL_TIGHT_CHANNEL,
                direction=Direction.LONG,
                confidence="高",
                signal="回踩支撑买入，波段持有",
                entry_condition=["回调低点买入", "止损在起涨点"],
                stop_loss="起涨点下方",
            ))
            reasons.append("紧贴趋势线 + 浅回调 → 多头窄通道")

        if is_wide or "宽" in market_environment:
            matched.append(CycleMatch(
                name="多头宽通道",
                cycle=MarketCycle.BULL_WIDE_CHANNEL,
                direction=Direction.LONG,
                confidence="中",
                signal="顺势波段为主，也可回踩买入",
                entry_condition=["支撑位买入", "高位减仓"],
                position_note="高位入场要减仓",
            ))
            reasons.append("回调幅度大 → 多头宽通道，多空都有机会")

    # ── 空头周期 ──────────────────────────────────────────
    if is_bear:
        if is_breakout:
            matched.append(CycleMatch(
                name="空头突破",
                cycle=MarketCycle.BEAR_BREAKOUT,
                direction=Direction.SHORT,
                confidence="极高",
                signal="波段持有，不追空",
                entry_condition=["Sell Stop在信号K线低点", "止损在起跌点上方"],
                stop_loss="起跌点（最高点）上方",
            ))
            reasons.append("连续大阴线无反弹 → 空头突破")

        if is_tight or "窄" in market_environment:
            matched.append(CycleMatch(
                name="空头窄通道",
                cycle=MarketCycle.BEAR_TIGHT_CHANNEL,
                direction=Direction.SHORT,
                confidence="高",
                signal="反弹高点做空，波段持有",
                entry_condition=["反弹高点做空", "止损在起跌点"],
                stop_loss="起跌点上方",
            ))
            reasons.append("紧贴趋势线 + 浅反弹 → 空头窄通道")

        if is_wide or "宽" in market_environment:
            matched.append(CycleMatch(
                name="空头宽通道",
                cycle=MarketCycle.BEAR_WIDE_CHANNEL,
                direction=Direction.SHORT,
                confidence="中",
                signal="顺势波段为主，也可反弹做空",
                entry_condition=["反弹高点做空", "低位减仓"],
                position_note="低位入场要减仓",
            ))
            reasons.append("反弹幅度大 → 空头宽通道，多空都有机会")

    # ── 震荡区间 ──────────────────────────────────────────
    if is_range:
        if is_wide or "宽" in market_environment:
            matched.append(CycleMatch(
                name="震荡宽区间",
                cycle=MarketCycle.TRADING_RANGE_WIDE,
                direction=Direction.WATCH,
                confidence="中",
                signal="高抛低吸（BLSHS）",
                entry_condition=["下沿买入，上沿卖出"],
            ))
            reasons.append("宽幅震荡 → 高抛低吸")
            risk_warnings.append("有很多假突破，止损要放大")
        else:
            matched.append(CycleMatch(
                name="震荡窄区间",
                cycle=MarketCycle.TRADING_RANGE_TIGHT,
                direction=Direction.WATCH,
                confidence="低",
                signal="区间太窄，等突破",
            ))
            reasons.append("窄幅震荡 → 等突破")

    # ── 惯性信号 ───────────────────────────────────────────
    if match_score(all_inputs, ["80%", "惯性", "惯性定律", "大概率失败", "持续"]) >= 1:
        risk_warnings.append("市场有惯性，80%的逆势尝试会失败")

    # ── 综合决策 ────────────────────────────────────────────
    priority = {Direction.SHORT: 2, Direction.LONG: 1, Direction.WATCH: 0, Direction.NONE: -1}
    if matched:
        best_dir = max(matched, key=lambda m: priority.get(m.direction, -1))
        best_cycle = next((m for m in matched if m.direction == best_dir.direction), matched[0])
        return DecisionResult(
            video="P04_Market_Cycle",
            primary_cycle=best_cycle.cycle,
            primary_signal=best_dir.direction,
            confidence=best_dir.confidence,
            matched_patterns=matched,
            reasons=reasons,
            risk_warnings=risk_warnings,
            stop_loss_rule=best_dir.stop_loss or "起涨点/起跌点",
            position_rule=best_dir.position_note or "根据止损距离确定仓位",
            summary=f"周期：{best_cycle.cycle.value} | 信号：{best_dir.direction.value}",
        )

    return DecisionResult(
        video="P04_Market_Cycle",
        primary_signal=Direction.WATCH,
        confidence="低",
        reasons=["无法确定市场周期"],
        summary="信号：WATCH（不确定）",
    )


if __name__ == "__main__":
    tests = [
        ("上涨趋势无回调", "突破", False, 0),
        ("上涨趋势紧贴趋势线", "窄通道", False, 2),
        ("上涨趋势有深幅回调", "宽通道", True, 10),
        ("下跌趋势无反弹", "突破", False, 0),
        ("横盘宽幅震荡", "震荡区间", True, 20),
        ("横盘窄幅震荡", "震荡区间", False, 3),
    ]

    print("P04 Market Cycle 决策引擎测试")
    print("=" * 60)
    for env, ch, deep, klines in tests:
        r = classify_market_cycle(
            trend=env,
            channel_type=ch,
            has_deep_pullback=deep,
            pullback_klines=klines,
        )
        print(f"\n环境: {env} | 通道: {ch}")
        print(f"  周期: {r.primary_cycle.value}")
        print(f"  信号: {r.primary_signal.value} | {r.confidence}")
        print(f"  止损: {r.stop_loss_rule}")
        if r.reasons:
            print(f"  理由: {r.reasons[0]}")
