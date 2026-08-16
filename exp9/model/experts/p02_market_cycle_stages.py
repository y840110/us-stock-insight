#!/usr/bin/env python3
"""
P02 市场周期的4个阶段 — 专家决策规则库（完整版）
================================================
来源：方方土价格行为学 · 市场周期4阶段
视频：02-01市场周期的4个阶段，Q&A
字幕：Whisper全字幕（1898条，100%覆盖68分钟）

核心主题：
  1. 牛市四个阶段：突破/窄通道/宽通道/震荡区间
  2. 各阶段入场策略
  3. 50%回撤原则
  4. 早盘交易规律（第7根K线方向、开盘震荡日）
  5. 第三推概念
  6. 止损设置：永远放起涨点/起跌点
  7. 多周期嵌套
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

# ══════════════════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════════════════

class BullCycleStage(Enum):
    BULL_BREAKOUT       = "多头突破"       # 连续大阳线，无回调
    BULL_TIGHT_CHANNEL  = "多头窄通道"     # 紧贴趋势线，回调1-3根K线
    BULL_WIDE_CHANNEL   = "多头宽通道"     # 回撤大（5-20+根K线）
    TRADING_RANGE       = "震荡区间"       # 横盘，高低点不再抬升
    BEAR_BREAKOUT      = "空头突破"       # 连续大阴线，无反弹
    BEAR_TIGHT_CHANNEL  = "空头窄通道"     # 紧贴下降趋势线，反弹1-3根
    BEAR_WIDE_CHANNEL   = "空头宽通道"     # 反弹大，5-20+根K线
    UNKNOWN             = "不确定"

class Direction(Enum):
    LONG   = "LONG"
    SHORT  = "SHORT"
    WATCH  = "WATCH"
    NONE   = "NONE"

@dataclass
class StageResult:
    stage: BullCycleStage = BullCycleStage.UNKNOWN
    direction: Direction = Direction.NONE
    confidence: str = "低"
    entry_strategy: str = ""
    stop_loss: str = ""
    exit_strategy: str = ""
    notes: list[str] = field(default_factory=list)

# ══════════════════════════════════════════════════════════════════════════════
# 核心规则库
# ══════════════════════════════════════════════════════════════════════════════

# ── 规则1：牛市四个阶段 ─────────────────────────────────────────────
RULE_STAGES = {
    BullCycleStage.BULL_BREAKOUT: {
        "patterns": ["突破", "无回调", "连续大阳线", "实体大", "Breakout"],
        "channel_klines": 0,           # 无回调
        "description": "连续大阳线，几乎无回调，Always In Long",
        "confidence": "极高",
        "entry": "任何理由入场（顺势），追涨",
        "stop": "起涨点（最低点）下方",
        "exit": "波段持有，直到趋势不再成立",
    },
    BullCycleStage.BULL_TIGHT_CHANNEL: {
        "patterns": ["窄通道", "紧贴趋势线", "1-3根K线", "回调很浅"],
        "channel_klines": (1, 3),
        "description": "紧贴上升趋势线，每次回调1-3根K线",
        "confidence": "高",
        "entry": "回调到趋势线附近买入（支撑买入）",
        "stop": "起涨点（最低点）下方",
        "exit": "波段持有",
    },
    BullCycleStage.BULL_WIDE_CHANNEL: {
        "patterns": ["宽通道", "回撤大", "深幅", "5根以上", "10根以上"],
        "channel_klines": (5, 100),
        "description": "回撤明显（5-20+根K线），但高低点仍在上移",
        "confidence": "中",
        "entry": "支撑位买入（波段）+ 上沿做空（剥头皮）",
        "stop": "起涨点下方",
        "exit": "波段持有，或高抛低吸",
    },
    BullCycleStage.TRADING_RANGE: {
        "patterns": ["震荡", "横盘", "无趋势", "不高点创新高", "不高不低"],
        "channel_klines": None,
        "description": "高低点不再抬升，横盘整理",
        "confidence": "中",
        "entry": "BLSH（Buy Low Sell High Scalp）：下沿买入，上沿卖出",
        "stop": "区间外侧",
        "exit": "止损触发或等真突破",
    },
}

# ── 规则2：50%回撤原则 ───────────────────────────────────────────
RULE_50_PCT = {
    "name": "50%回撤原则",
    "description": "价格回撤到Swing幅度的50%时，是重要支撑位",
    "above_50_pct": {
        "signal": "支撑有效，趋势延续概率大",
        "action": "可在50%回撤区域买入",
        "confidence": "高",
    },
    "at_50_pct": {
        "signal": "正好在50%回撤位",
        "action": "关键入场点，不需要抄到最低",
        "confidence": "高",
    },
    "below_50_pct": {
        "signal": "跌破50%，趋势可能反转或变震荡",
        "action": "等待更低确认或改变策略",
        "confidence": "中",
    },
}

# ── 规则3：早盘交易 ───────────────────────────────────────────────
RULE_EARLY_MORNING = {
    "name": "早盘交易规律",
    "bar_7": "第7根K线容易出现方向（开盘后第7根）",
    "opening_chop": "开盘大涨/大跌后横盘 → 全天可能震荡 → BLSH全天",
    "opening_strong": "开盘稳步上涨 → 趋势日 → 顺势交易",
}

# ── 规则4：止损设置 ───────────────────────────────────────────────
RULE_STOP_LOSS = {
    "追涨买入": "止损放在前期低点（起涨点）下方",
    "回调买入": "止损放在起涨点（最低点）下方",
    "区间下沿买入": "止损放在区间下方（区间外侧）",
    "突破买入": "止损放在突破K线低点下方",
    "核心原则": "止损永远放在起涨点/起跌点，不是随便放的",
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

def classify_bull_cycle(
    trend: str = "",
    pullback_depth: str = "",
    pullback_klines: int = 0,
    channel_type: str = "",
    has_higher_high: bool = True,
    has_higher_low: bool = True,
) -> StageResult:
    """
    判断市场所处阶段

    参数:
        trend: 上涨/下跌
        pullback_depth: 无/浅/深
        pullback_klines: 回调K线数量
        channel_type: 突破/窄通道/宽通道/震荡
        has_higher_high: 高点是否创新高
        has_higher_low: 低点是否创新高
    """
    keywords = [trend, pullback_depth, channel_type]

    # ── 横盘/震荡 ────────────────────────────────────────────
    if not has_higher_high or not has_higher_low:
        return StageResult(
            stage=BullCycleStage.TRADING_RANGE,
            direction=Direction.WATCH,
            confidence="中",
            entry_strategy="BLSH高抛低吸",
            stop_loss="区间外侧",
            exit_strategy="止损触发或等真突破",
            notes=["横盘整理 → 无明显趋势 → 高抛低吸"],
        )

    # ── 多头突破（无回调）────────────────────────────────────
    if "上涨" in trend:
        if pullback_klines == 0 or "无" in pullback_depth:
            return StageResult(
                stage=BullCycleStage.BULL_BREAKOUT,
                direction=Direction.LONG,
                confidence="极高",
                entry_strategy="追涨，任何顺势入场点都可以",
                stop_loss="起涨点（最低点）下方",
                exit_strategy="波段持有，直到趋势不再成立",
                notes=["连续大阳线无回调 → Always In Long"],
            )

        # ── 窄通道（1-3根K线）──────────────────────────────
        if 1 <= pullback_klines <= 3 or "窄" in channel_type:
            return StageResult(
                stage=BullCycleStage.BULL_TIGHT_CHANNEL,
                direction=Direction.LONG,
                confidence="高",
                entry_strategy="回调到趋势线附近买入",
                stop_loss="起涨点（最低点）下方",
                exit_strategy="波段持有",
                notes=["紧贴趋势线 + 回调1-3根 → 强趋势"],
            )

        # ── 宽通道（5+根K线）───────────────────────────────
        if pullback_klines >= 5 or "深" in pullback_depth or "宽" in channel_type:
            return StageResult(
                stage=BullCycleStage.BULL_WIDE_CHANNEL,
                direction=Direction.LONG,
                confidence="中",
                entry_strategy="支撑买入（波段）+ 上沿做空（剥头皮）",
                stop_loss="起涨点下方",
                exit_strategy="波段持有或高抛低吸",
                notes=["回撤5-20+根K线 → 趋势在变弱"],
            )

    # ── 空头判断 ────────────────────────────────────────────
    if "下跌" in trend:
        if pullback_klines == 0 or "无" in pullback_depth:
            return StageResult(
                stage=BullCycleStage.BEAR_BREAKOUT,
                direction=Direction.SHORT,
                confidence="极高",
                entry_strategy="追空，任何顺势入场点",
                stop_loss="起跌点（最高点）上方",
                exit_strategy="波段持有",
                notes=["连续大阴线无反弹 → Always In Short"],
            )
        if 1 <= pullback_klines <= 3:
            return StageResult(
                stage=BullCycleStage.BEAR_TIGHT_CHANNEL,
                direction=Direction.SHORT,
                confidence="高",
                entry_strategy="反弹到趋势线附近做空",
                stop_loss="起跌点上方",
                exit_strategy="波段持有",
            )
        if pullback_klines >= 5:
            return StageResult(
                stage=BullCycleStage.BEAR_WIDE_CHANNEL,
                direction=Direction.SHORT,
                confidence="中",
                entry_strategy="反弹做空（剥头皮）+ 趋势波段",
                stop_loss="起跌点上方",
                exit_strategy="波段持有",
            )

    return StageResult(
        stage=BullCycleStage.UNKNOWN,
        direction=Direction.WATCH,
        confidence="低",
        notes=["无法确定市场阶段"],
    )


def check_50_pct_retracement(
    swing_low: float,
    swing_high: float,
    current_low: float,
) -> dict:
    """
    检查50%回撤支撑位
    swing_low: 起涨点低点
    swing_high: 阶段高点
    current_low: 当前回撤低点
    返回: {status, signal, action}
    """
    swing_range = swing_high - swing_low
    pct_50 = swing_low + swing_range * 0.50
    deviation = abs(current_low - pct_50) / swing_range

    if deviation < 0.02:  # 误差2%以内视为在50%位
        return {
            "status": "at_50_pct",
            "signal": f"正好在50%回撤位({pct_50:.2f})",
            "action": "关键入场点，可在50%回撤区域买入，止损放50%下方",
            "confidence": "高",
            "pct_level": pct_50,
        }
    elif current_low > pct_50:
        return {
            "status": "above_50_pct",
            "signal": f"在50%上方({current_low:.2f} > {pct_50:.2f})",
            "action": "支撑有效，趋势延续概率大",
            "confidence": "高",
            "pct_level": pct_50,
        }
    else:
        return {
            "status": "below_50_pct",
            "signal": f"跌破50%({current_low:.2f} < {pct_50:.2f})",
            "action": "趋势可能反转或变震荡，等待确认",
            "confidence": "中",
            "pct_level": pct_50,
        }


def is_early_morning_chop(
    first_7_bars_direction: str = "",   # 震荡/上涨/下跌
    opening_move: bool = False,           # 开盘是否有明显方向
    opening_move_type: str = "",          # 大涨/大跌/横盘
) -> bool:
    """
    判断早盘是否是震荡日
    规则：开盘大涨/大跌后横盘 → 全天震荡 → BLSH全天
    """
    if opening_move and opening_move_type in ["大涨", "大跌"]:
        return True  # 开盘有明显方向后横盘 = 震荡日
    if first_7_bars_direction == "震荡":
        return True
    return False


def get_stop_loss_rule(
    entry_type: str,
    prior_swing_low: Optional[float] = None,
    range_low: Optional[float] = None,
) -> str:
    """根据入场类型返回止损规则"""
    rules = {
        "追涨买入": f"止损放在前期低点（{prior_swing_low}）下方",
        "回调买入": f"止损放在起涨点（{prior_swing_low}）下方",
        "区间下沿买入": f"止损放在区间下方（{range_low}外侧）",
        "突破买入": "止损放在突破K线低点下方",
        "做空": f"止损放在起跌点上方",
    }
    return rules.get(entry_type, "止损放在起涨点/起跌点下方/上方")


if __name__ == "__main__":
    tests = [
        ("上涨", "无", 0, "突破"),
        ("上涨", "浅", 2, "窄通道"),
        ("上涨", "深", 10, "宽通道"),
        ("横盘", "有", 5, "震荡"),
        ("下跌", "无", 0, "突破"),
    ]

    print("P02 市场周期四阶段 决策引擎测试")
    print("=" * 60)
    for trend, depth, klines, ch in tests:
        r = classify_bull_cycle(trend=trend, pullback_depth=depth,
                                 pullback_klines=klines, channel_type=ch)
        print(f"\n{trend} | 回撤:{depth}({klines}根) | {ch}")
        print(f"  阶段: {r.stage.value} | 信号: {r.direction.value} | {r.confidence}")
        print(f"  入场: {r.entry_strategy}")
        print(f"  止损: {r.stop_loss}")

    print("\n50%回撤测试:")
    r = check_50_pct_retracement(100.0, 110.0, 105.0)
    print(f"  swing_low=100, swing_high=110, current=105 → {r['status']}: {r['signal']}")

    print("\n早盘震荡判断:")
    r = is_early_morning_chop(opening_move=True, opening_move_type="大涨")
    print(f"  开盘大涨后横盘 → 震荡日: {r}")
