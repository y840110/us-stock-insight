#!/usr/bin/env python3
"""
P08 信号K线&入场(2) — 专家决策规则库
================================================
来源：方方土价格行为学 · 顺势交易
视频：08-06信号K线&入场(2)
分析方法：视频帧分析（Vision API）

核心主题：
  1. 信号K线（Signal Bar）质量评估
  2. 两K反转（2-Bar Reversal）
  3. Stop Entry vs Limit Entry 入场方式
  4. 被动止损 vs 主动止损
  5. 止损设置策略
  6. 三推反转（H3/L3）
  7. 极值K线与反转判断
  8. 区间/通道中的Passive Entry

铁律：K线数据必须以 `time` 字段判断最新价格，禁止用 `data[-1]`
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import math

# ══════════════════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════════════════

class Direction(Enum):
    LONG   = "LONG"
    SHORT  = "SHORT"
    WATCH  = "WATCH"
    NONE   = "NONE"

class SignalBarQuality(Enum):
    HIGH   = "HIGH"    # 高质量信号K线
    MEDIUM = "MEDIUM"  # 中等质量
    LOW    = "LOW"     # 低质量/无效

class EntryType(Enum):
    STOP_BUY  = "STOP_BUY"   # 突破入场（做多）
    STOP_SELL = "STOP_SELL"  # 突破入场（做空）
    LIMIT_BUY = "LIMIT_BUY"  # 限价入场（做多）
    LIMIT_SELL = "LIMIT_SELL" # 限价入场（做空）
    NONE = "NONE"

@dataclass
class Candle:
    """K线数据结构"""
    time: int          # 时间戳（Unix秒）- 判断最新价格的唯一依据
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def upper_shadow(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_shadow(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def body_ratio(self) -> float:
        """实体占整根K线的比例（0.0-1.0）"""
        r = self.range
        if r == 0:
            return 0.0
        return self.body / r

    @property
    def is_doji(self) -> bool:
        """十字星：实体占整根K线 < 10%"""
        return self.body_ratio < 0.10

    @property
    def is_gap(self) -> bool:
        """跳空K线"""
        return False  # 需配合前一根K线判断

@dataclass
class SignalBarResult:
    signal: str = "无信号"
    quality: SignalBarQuality = SignalBarQuality.LOW
    direction: Direction = Direction.WATCH
    confidence: str = "低"
    entry_price: Optional[float] = None
    entry_type: EntryType = EntryType.NONE
    stop_loss: Optional[float] = None
    reasons: list[str] = field(default_factory=list)

@dataclass
class EntryPoint:
    """入场点"""
    direction: Direction
    entry_type: EntryType
    entry_price: float
    stop_loss: float
    target: Optional[float] = None
    risk_ticks: float = 0.0
    confidence: str = "低"
    reasons: list[str] = field(default_factory=list)

# ══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════════════

def get_latest_candle(data: list[Candle]) -> Candle:
    """
    【铁律】获取最新一根K线
    禁止使用 data[-1]，必须用 time 字段判断
    """
    if not data:
        raise ValueError("K线数据为空")
    return max(data, key=lambda c: c.time)

def get_candle_by_time(data: list[Candle], target_time: int) -> Optional[Candle]:
    """根据时间戳查找K线"""
    for c in reversed(data):
        if c.time == target_time:
            return c
    return None

def get_recent_bars(data: list[Candle], count: int = 5) -> list[Candle]:
    """获取最近N根K线（按时间倒序）"""
    if not data:
        return []
    sorted_data = sorted(data, key=lambda c: c.time, reverse=True)
    return sorted_data[:count]

# ══════════════════════════════════════════════════════════════════════════════
# 规则库
# ══════════════════════════════════════════════════════════════════════════════

# ── 规则1：信号K线质量评估 ─────────────────────────────────────────
RULE_SIGNAL_BAR_QUALITY = {
    "name": "信号K线质量评估",
    "high_quality_criteria": {
        "body_ratio": 0.80,      # 实体占整根K线 ≥ 80%
        "shadow_ratio": 0.20,    # 影线 ≤ 20%
        "min_size_ticks": 5,     # 最小实体大小（相对）
        "location": ["支撑", "阻力", "趋势线", "通道边", "整数关口"],
    },
    "medium_quality": {
        "body_ratio": 0.60,      # 实体占 60-80%
        "shadow_ratio": 0.40,    # 影线 20-40%
    },
    "low_quality": {
        "body_ratio": "< 60%",   # 实体太小
        "is_doji": True,         # 十字星
        "shadow_ratio": "> 40%", # 影线太长
    },
}

def assess_signal_bar_quality(candle: Candle) -> SignalBarQuality:
    """
    评估信号K线质量
    """
    body_ratio = candle.body_ratio

    # 十字星 = 低质量
    if candle.is_doji:
        return SignalBarQuality.LOW

    # 实体 ≥ 80% = 高质量
    if body_ratio >= 0.80:
        upper_ratio = candle.upper_shadow / candle.range if candle.range > 0 else 0
        lower_ratio = candle.lower_shadow / candle.range if candle.range > 0 else 0
        if upper_ratio <= 0.20 and lower_ratio <= 0.20:
            return SignalBarQuality.HIGH

    # 实体 60-80% = 中等质量
    if body_ratio >= 0.60:
        return SignalBarQuality.MEDIUM

    return SignalBarQuality.LOW


# ── 规则2：两K反转（2-Bar Reversal）──────────────────────────────────
RULE_TWO_BAR_REVERSAL = {
    "name": "两K反转（2-Bar Reversal）",
    "bullish_2br": {
        "description": "大阴线后紧跟大阳线",
        "pattern": "第一根：大阴线（空头情绪极端）| 第二根：大阳线（反转）",
        "entry": "Buy Stop在第二根K线高点上方1 tick",
        "stop": "止损在第二根K线低点下方1 tick",
        "confidence": "高",
    },
    "bearish_2br": {
        "description": "大阳线后紧跟大阴线",
        "pattern": "第一根：大阳线（多头情绪极端）| 第二根：大阴线（反转）",
        "entry": "Sell Stop在第二根K线低点下方1 tick",
        "stop": "止损在第二根K线高点上方1 tick",
        "confidence": "高",
    },
    "key_principle": "第二根K线（信号K线）的收盘价是关键，不在乎影线刺透多少",
}

def detect_two_bar_reversal(data: list[Candle]) -> Optional[SignalBarResult]:
    """
    检测两K反转形态
    data: K线数据列表（按时间正序）
    """
    if len(data) < 2:
        return None

    # 取最后两根K线
    bar1 = data[-2]  # 前一根
    bar2 = data[-1]  # 当前K线（信号K线）

    # 计算实体大小（归一化）
    avg_range = sum(b.range for b in data[-5:]) / min(5, len(data))
    bar1_size = bar1.range / avg_range if avg_range > 0 else 0
    bar2_size = bar2.range / avg_range if avg_range > 0 else 0

    # 大于平均1.5倍 = 大K线
    is_large1 = bar1_size > 1.5
    is_large2 = bar2_size > 1.5

    reasons = []

    # 牛市两K反转：大阴线 + 大阳线
    if (bar1.is_bearish and bar2.is_bullish and is_large1 and is_large2):
        quality = assess_signal_bar_quality(bar2)
        entry_price = bar2.high + 0.00001  # 1 tick above
        stop_loss = bar2.low - 0.00001
        return SignalBarResult(
            signal="牛市两K反转",
            quality=quality,
            direction=Direction.LONG,
            confidence="高" if quality == SignalBarQuality.HIGH else "中",
            entry_price=entry_price,
            entry_type=EntryType.STOP_BUY,
            stop_loss=stop_loss,
            reasons=[
                f"第一根大阴线（空头情绪极端）",
                f"第二根大阳线（反转确认）",
                f"信号K线质量：{quality.value}",
            ]
        )

    # 熊市两K反转：大阳线 + 大阴线
    if (bar1.is_bullish and bar2.is_bearish and is_large1 and is_large2):
        quality = assess_signal_bar_quality(bar2)
        entry_price = bar2.low - 0.00001  # 1 tick below
        stop_loss = bar2.high + 0.00001
        return SignalBarResult(
            signal="熊市两K反转",
            quality=quality,
            direction=Direction.SHORT,
            confidence="高" if quality == SignalBarQuality.HIGH else "中",
            entry_price=entry_price,
            entry_type=EntryType.STOP_SELL,
            stop_loss=stop_loss,
            reasons=[
                f"第一根大阳线（多头情绪极端）",
                f"第二根大阴线（反转确认）",
                f"信号K线质量：{quality.value}",
            ]
        )

    return None


# ── 规则3：Stop Entry vs Limit Entry ─────────────────────────────────
RULE_ENTRY_TYPE = {
    "name": "入场类型选择",
    "stop_entry": {
        "description": "等待价格突破信号K线后入场",
        "when": "在趋势明确、信号K线出现在'正确的地方'时使用",
        "pros": "确认性强，减少假信号",
        "cons": "可能错过开盘价",
    },
    "limit_entry": {
        "description": "在信号K线极值位置挂单等待",
        "when": "在区间/通道边界、支撑阻力位使用Passive Entry",
        "pros": "更好的价格，不容易被扫止损",
        "cons": "可能不成交",
    },
    "brooks_advice": "Brooks偏好Passive/Limit Entry：在边界挂单等待 > 追价格",
}

def choose_entry_type(
    signal_bar: Candle,
    market_context: str = "",  # 趋势/区间/通道
    location: str = "",         # 支撑/阻力/通道边
) -> EntryType:
    """
    选择入场类型
    """
    # 趋势中的突破 → Stop Entry
    if "趋势" in market_context or "trend" in market_context.lower():
        if signal_bar.is_bullish:
            return EntryType.STOP_BUY
        else:
            return EntryType.STOP_SELL

    # 区间/通道边界 → Limit Entry
    if "区间" in market_context or "通道" in market_context:
        if signal_bar.is_bullish:
            return EntryType.LIMIT_BUY
        else:
            return EntryType.LIMIT_SELL

    # 默认用Stop Entry（更保守）
    if signal_bar.is_bullish:
        return EntryType.STOP_BUY
    else:
        return EntryType.STOP_SELL


# ── 规则4：止损设置 ───────────────────────────────────────────────
RULE_STOP_LOSS = {
    "name": "止损设置规则",
    "signal_bar_stop": {
        "bull": "信号K线低点下方1 tick",
        "bear": "信号K线高点上方1 tick",
    },
    "aggressive_stop": {
        "bull": "信号K线低点下方（窄止损，高风险）",
        "bear": "信号K线高点上方（窄止损，高风险）",
    },
    "passive_stop": {
        "bull": "前一波段低点下方（宽止损，低风险）",
        "bear": "前一波段高点上方（宽止损，低风险）",
    },
    "atr_stop": {
        "description": "ATR的1.5-2倍作为止损距离",
        "suitable": "波动较大的市场",
    },
    "time_stop": {
        "description": "2-4根K线内无预期发展 → 主动离场",
        "principle": "市场没有'尊重'信号K线",
    },
}

def calculate_stop_loss(
    signal_bar: Candle,
    method: str = "signal_bar",  # signal_bar | aggressive | passive | atr
    prev_swing_low: Optional[float] = None,
    prev_swing_high: Optional[float] = None,
    atr: Optional[float] = None,
    tick_size: float = 0.00001,
) -> float:
    """
    计算止损位置
    """
    if method == "signal_bar":
        if signal_bar.is_bullish:
            return signal_bar.low - tick_size
        else:
            return signal_bar.high + tick_size

    elif method == "aggressive":
        if signal_bar.is_bullish:
            return signal_bar.low - tick_size
        else:
            return signal_bar.high + tick_size

    elif method == "passive":
        if signal_bar.is_bullish and prev_swing_low is not None:
            return prev_swing_low - tick_size
        elif signal_bar.is_bearish and prev_swing_high is not None:
            return prev_swing_high + tick_size
        else:
            # 默认用signal_bar方法
            return signal_bar.low - tick_size if signal_bar.is_bullish else signal_bar.high + tick_size

    elif method == "atr" and atr is not None:
        if signal_bar.is_bullish:
            return signal_bar.low - (atr * 1.5)
        else:
            return signal_bar.high + (atr * 1.5)

    # 默认
    return signal_bar.low - tick_size if signal_bar.is_bullish else signal_bar.high + tick_size


# ── 规则5：三推反转（H3/L3）────────────────────────────────────────
RULE_THREE_PUSH = {
    "name": "三推反转（H3/L3）",
    "h3_bearish": {
        "description": "三次上推都失败 → 强烈做空信号",
        "pattern": "H1失败 → H2失败 → H3失败",
        "signal": "H3反转 → 做空",
        "confidence": "高",
        "reason": "三次推升失败 = 机构不再买入 = 卖压将主导",
    },
    "l3_bullish": {
        "description": "三次下推都失败 → 强烈做多信号",
        "pattern": "L1失败 → L2失败 → L3失败",
        "signal": "L3反转 → 做多",
        "confidence": "高",
        "reason": "三次下跌失败 = 机构不再卖出 = 买压将主导",
    },
    "wedge_failure": {
        "description": "楔形三次推升全部失败 = Failed Wedge",
        "signal": "极强反转信号",
    },
}

def detect_three_push(
    h_signals: list[str],  # ["成功","失败","失败"] 等
    l_signals: list[str],
    direction: str = "",
) -> SignalBarResult:
    """
    检测三推反转信号
    """
    if len(h_signals) >= 3:
        last_three = h_signals[-3:]
        all_failed = all(s in ("失败", "fail") for s in last_three)
        if all_failed and "上" in direction:
            return SignalBarResult(
                signal="H3反转",
                quality=SignalBarQuality.HIGH,
                direction=Direction.SHORT,
                confidence="高",
                reasons=["三次上推全部失败 → 强烈做空信号"],
            )

    if len(l_signals) >= 3:
        last_three = l_signals[-3:]
        all_failed = all(s in ("失败", "fail") for s in last_three)
        if all_failed and "下" in direction:
            return SignalBarResult(
                signal="L3反转",
                quality=SignalBarQuality.HIGH,
                direction=Direction.LONG,
                confidence="高",
                reasons=["三次下推全部失败 → 强烈做多信号"],
            )

    return SignalBarResult(
        signal="无三推信号",
        quality=SignalBarQuality.LOW,
        direction=Direction.WATCH,
        confidence="低",
        reasons=["推升次数不足或未全部失败"],
    )


# ── 规则6：极值K线（Extreme Bar）────────────────────────────────────
RULE_EXTREME_BAR = {
    "name": "极值K线",
    "description": "在趋势末端出现的超长K线",
    "bull_extreme": {
        "pattern": "超长大阳线出现在上涨末端",
        "implication": "可能是最后一涨，之后横盘或反转",
        "action": "多头减仓，不追高，等待反转信号",
    },
    "bear_extreme": {
        "pattern": "超长大阴线出现在下跌末端",
        "implication": "可能是最后一跌，之后横盘或反转",
        "action": "空头减仓，不追空，等待反弹信号",
    },
    "detection": {
        "threshold": 2.0,  # 大于平均range的2倍
        "lookback": 20,    # 参考过去20根K线
    },
}

def detect_extreme_bar(data: list[Candle]) -> Optional[SignalBarResult]:
    """
    检测极值K线（趋势末端的超长K线）
    """
    if len(data) < 20:
        return None

    recent = data[-20:]
    avg_range = sum(b.range for b in recent) / len(recent)
    latest = get_latest_candle(data)

    ratio = latest.range / avg_range if avg_range > 0 else 0

    if ratio < 2.0:
        return None

    if latest.is_bullish:
        return SignalBarResult(
            signal="极值K线（看涨极端）",
            quality=SignalBarQuality.MEDIUM,
            direction=Direction.WATCH,  # 不追，等待反转
            confidence="中",
            reasons=[
                f"超长大阳线（range={ratio:.1f}x平均）",
                "可能是最后一涨 → 多头减仓",
                "等待反转信号再入场",
            ]
        )
    else:
        return SignalBarResult(
            signal="极值K线（看跌极端）",
            quality=SignalBarQuality.MEDIUM,
            direction=Direction.WATCH,  # 不追，等待反弹
            confidence="中",
            reasons=[
                f"超长大阴线（range={ratio:.1f}x平均）",
                "可能是最后一跌 → 空头减仓",
                "等待反弹信号再入场",
            ]
        )


# ══════════════════════════════════════════════════════════════════════════════
# 核心函数
# ══════════════════════════════════════════════════════════════════════════════

def is_signal_bar(
    candle: Candle,
    avg_range: Optional[float] = None,
    reference_range: float = 1.5,
) -> SignalBarResult:
    """
    判断一根K线是否为信号K线（Signal Bar）

    【铁律】：使用 candle.time 判断最新价格，禁止用 data[-1]

    参数：
        candle: 待评估的K线
        avg_range: 平均K线幅度（用于判断是否为大K线）
        reference_range: 相对于平均幅度的倍数（默认1.5x）

    返回：
        SignalBarResult: 包含信号方向、质量、置信度和理由
    """
    reasons = []
    quality = assess_signal_bar_quality(candle)

    # 判断是否为大K线
    if avg_range is not None and avg_range > 0:
        is_large = candle.range >= (avg_range * reference_range)
        if not is_large:
            return SignalBarResult(
                signal="无信号",
                quality=SignalBarQuality.LOW,
                direction=Direction.WATCH,
                confidence="低",
                reasons=["K线幅度不够大，不是有效信号K线"],
            )

    # 看涨信号K线
    if candle.is_bullish:
        reasons.append(f"看涨K线（实体{quality.value}质量）")
        return SignalBarResult(
            signal="看涨信号K线",
            quality=quality,
            direction=Direction.LONG,
            confidence="高" if quality == SignalBarQuality.HIGH else "中",
            reasons=reasons,
        )

    # 看跌信号K线
    if candle.is_bearish:
        reasons.append(f"看跌K线（实体{quality.value}质量）")
        return SignalBarResult(
            signal="看跌信号K线",
            quality=quality,
            direction=Direction.SHORT,
            confidence="高" if quality == SignalBarQuality.HIGH else "中",
            reasons=reasons,
        )

    return SignalBarResult(
        signal="无信号",
        quality=SignalBarQuality.LOW,
        direction=Direction.WATCH,
        confidence="低",
        reasons=["十字星K线，无方向信号"],
    )


def find_signal_bar_entry(
    data: list[Candle],
    direction: str = "",       # "long" 或 "short"
    market_context: str = "",  # "趋势" / "区间" / "通道"
    tick_size: float = 0.00001,
) -> Optional[EntryPoint]:
    """
    寻找信号K线入场点

    【铁律】：K线数据必须以 time 字段判断最新价格，禁止用 data[-1]

    参数：
        data: K线数据列表（按时间正序）
        direction: 预期方向 "long" 或 "short"
        market_context: 市场背景 "趋势" / "区间" / "通道"
        tick_size: 最小价格变动

    返回：
        EntryPoint 或 None
    """
    if len(data) < 3:
        return None

    latest = get_latest_candle(data)

    # 检测两K反转
    two_br = detect_two_bar_reversal(data)
    if two_br and two_br.direction.value.upper() == direction.upper():
        return EntryPoint(
            direction=two_br.direction,
            entry_type=two_br.entry_type,
            entry_price=two_br.entry_price,
            stop_loss=two_br.stop_loss,
            confidence=two_br.confidence,
            reasons=two_br.reasons + ["两K反转入场"],
        )

    # 单根信号K线分析
    recent = get_recent_bars(data, 20)
    avg_range = sum(b.range for b in recent) / len(recent) if recent else 0

    result = is_signal_bar(latest, avg_range)

    if result.direction == Direction.WATCH:
        return None

    if direction.lower() == "long" and result.direction == Direction.LONG:
        entry_type = choose_entry_type(latest, market_context, "支撑")
        if entry_type == EntryType.STOP_BUY:
            entry_price = latest.high + tick_size
        else:
            entry_price = latest.low - tick_size  # Limit Buy
        stop_loss = calculate_stop_loss(latest, "signal_bar", tick_size=tick_size)
        return EntryPoint(
            direction=Direction.LONG,
            entry_type=entry_type,
            entry_price=entry_price,
            stop_loss=stop_loss,
            confidence=result.confidence,
            reasons=result.reasons + [f"入场类型：{entry_type.value}"],
        )

    if direction.lower() == "short" and result.direction == Direction.SHORT:
        entry_type = choose_entry_type(latest, market_context, "阻力")
        if entry_type == EntryType.STOP_SELL:
            entry_price = latest.low - tick_size
        else:
            entry_price = latest.high + tick_size  # Limit Sell
        stop_loss = calculate_stop_loss(latest, "signal_bar", tick_size=tick_size)
        return EntryPoint(
            direction=Direction.SHORT,
            entry_type=entry_type,
            entry_price=entry_price,
            stop_loss=stop_loss,
            confidence=result.confidence,
            reasons=result.reasons + [f"入场类型：{entry_type.value}"],
        )

    return None


def validate_entry_stop(
    entry_price: float,
    stop_loss: float,
    signal_bar: Candle,
    direction: str = "",
    max_risk_ticks: float = 20.0,
    tick_size: float = 0.00001,
) -> dict:
    """
    验证止损位置是否合理

    【铁律】：必须以 signal_bar.time 判断最新K线数据

    返回：
        dict: {
            "valid": bool,
            "risk_ticks": float,
            "warnings": list[str],
            "suggestions": list[str],
        }
    """
    warnings = []
    suggestions = []
    valid = True

    # 计算风险（以tick计）
    risk_ticks = abs(entry_price - stop_loss) / tick_size

    # 止损过宽检查
    if risk_ticks > max_risk_ticks:
        warnings.append(f"止损过宽：{risk_ticks:.0f} ticks（建议 < {max_risk_ticks:.0f}）")
        suggestions.append("考虑缩小止损或减少仓位")
        valid = False

    # 止损在信号K线内检查
    if direction.lower() == "long":
        if stop_loss < signal_bar.low:
            warnings.append("止损低于信号K线低点：可能被噪音扫止损")
            suggestions.append("考虑将止损放在信号K线低点下方1 tick")
        if entry_price <= signal_bar.low:
            warnings.append("入场价 ≤ 信号K线低点：价格关系不正确")
            valid = False

    if direction.lower() == "short":
        if stop_loss > signal_bar.high:
            warnings.append("止损高于信号K线高点：可能被噪音扫止损")
            suggestions.append("考虑将止损放在信号K线高点上方1 tick")
        if entry_price >= signal_bar.high:
            warnings.append("入场价 ≥ 信号K线高点：价格关系不正确")
            valid = False

    # 盈亏比检查（需要目标价才能计算，这里只检查止损合理性）
    if risk_ticks < 2:
        warnings.append(f"止损极窄：{risk_ticks:.0f} ticks（可能被立即扫出）")
        suggestions.append("考虑适当放宽止损以容纳正常波动")

    return {
        "valid": valid,
        "risk_ticks": risk_ticks,
        "warnings": warnings,
        "suggestions": suggestions,
        "signal_bar_time": signal_bar.time,  # 记录K线时间戳（铁律）
    }


# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════

def calculate_target(
    entry_price: float,
    stop_loss: float,
    signal_bar: Candle,
    method: str = "measured_move",
    prev_swing: Optional[float] = None,
) -> Optional[float]:
    """
    计算止盈目标位
    """
    risk = abs(entry_price - stop_loss)

    if method == "measured_move":
        # 等距测量目标：入场价 + 风险
        return entry_price + risk if signal_bar.is_bullish else entry_price - risk

    if method == "swing_ext":
        # 波段延伸：前一波段的等距延伸
        if prev_swing is not None:
            return entry_price + prev_swing if signal_bar.is_bullish else entry_price - prev_swing

    # 默认1:1盈亏比
    return entry_price + risk if signal_bar.is_bullish else entry_price - risk


# ══════════════════════════════════════════════════════════════════════════════
# 测试
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import time

    # 构造测试K线数据（模拟两K反转）
    now = int(time.time())
    base_price = 1.10000

    test_data = [
        Candle(time=now - 3600 * 3, open=base_price,      high=base_price + 0.00050, low=base_price - 0.00030, close=base_price - 0.00040, volume=1000),
        Candle(time=now - 3600 * 2, open=base_price - 0.00040, high=base_price + 0.00010, low=base_price - 0.00020, close=base_price + 0.00010, volume=1200),
        # 大阴线（第一根）
        Candle(time=now - 3600,     open=base_price + 0.00010, high=base_price + 0.00080, low=base_price - 0.00120, close=base_price - 0.00100, volume=2000),
        # 大阳线（第二根 = 信号K线 = 两K反转）
        Candle(time=now,           open=base_price - 0.00100, high=base_price + 0.00020, low=base_price - 0.00080, close=base_price + 0.00010, volume=2200),
    ]

    print("P08 信号K线&入场(2) 决策引擎测试")
    print("=" * 60)
    print(f"最新K线时间：{test_data[-1].time}")

    # 测试 is_signal_bar
    latest = get_latest_candle(test_data)
    print(f"\n最新K线（时间={latest.time}）：")
    print(f"  O:{latest.open:.5f} H:{latest.high:.5f} L:{latest.low:.5f} C:{latest.close:.5f}")
    print(f"  类型：{'阳线' if latest.is_bullish else '阴线'} | 实体比：{latest.body_ratio:.1%}")

    result = is_signal_bar(latest, avg_range=0.00100)
    print(f"\nis_signal_bar → {result.signal}")
    print(f"  方向：{result.direction.value} | 质量：{result.quality.value} | 置信度：{result.confidence}")
    print(f"  理由：{result.reasons}")

    # 测试两K反转检测
    two_br = detect_two_bar_reversal(test_data)
    if two_br:
        print(f"\n两K反转检测 → {two_br.signal}")
        print(f"  方向：{two_br.direction.value} | 置信度：{two_br.confidence}")
        print(f"  入场价：{two_br.entry_price:.5f} | 止损：{two_br.stop_loss:.5f}")
        print(f"  入场类型：{two_br.entry_type.value}")

    # 测试 find_signal_bar_entry
    entry = find_signal_bar_entry(test_data, direction="long", market_context="趋势")
    if entry:
        print(f"\n信号K线入场点 → {entry.direction.value}")
        print(f"  入场价：{entry.entry_price:.5f} | 止损：{entry.stop_loss:.5f}")
        print(f"  入场类型：{entry.entry_type.value} | 置信度：{entry.confidence}")
        print(f"  理由：{entry.reasons}")

        # 测试止损验证
        validation = validate_entry_stop(
            entry.entry_price,
            entry.stop_loss,
            latest,
            direction="long",
        )
        print(f"\n止损验证：{'✓ 有效' if validation['valid'] else '✗ 无效'}")
        print(f"  风险：{validation['risk_ticks']:.0f} ticks")
        if validation['warnings']:
            print(f"  警告：{validation['warnings']}")
        if validation['suggestions']:
            print(f"  建议：{validation['suggestions']}")

    # 测试极值K线检测
    print("\n极值K线检测：")
    extreme = detect_extreme_bar(test_data)
    if extreme:
        print(f"  {extreme.signal} | {extreme.direction.value} | {extreme.confidence}")
    else:
        print("  未检测到极值K线")

    print("\n" + "=" * 60)
    print("测试完成")
