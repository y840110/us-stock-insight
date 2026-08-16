#!/usr/bin/env python3
"""
P09 信号K线&入场(3) — 系统交易 vs 主观交易
================================================
来源：方方土价格行为学 · 顺势交易
视频：09-07信号K线&入场(3) — seg_0
分析方法：字幕分析 + 帧组元数据

核心主题：
  1. 坏背景 + 坏信号K的识别与处理
  2. 系统交易 vs 主观交易的本质区别
  3. 背景（Context）与信号K线（Signal Bar）的优先级
  4. 双顶形态的做空案例与盈亏比计算
  5. Bull Flag（牛市旗形）的被动入场策略
  6. A股周线案例：强趋势中的反弹与做空机会

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

class Direction(Enum):
    LONG   = "LONG"
    SHORT  = "SHORT"
    WATCH  = "WATCH"   # 观望
    NONE   = "NONE"

class SignalBarQuality(Enum):
    HIGH   = "HIGH"    # 高质量
    MEDIUM = "MEDIUM"  # 中等
    LOW    = "LOW"     # 低质量/无效

class BackgroundQuality(Enum):
    GOOD   = "GOOD"    # 有利于反转/趋势延续
    NEUTRAL= "NEUTRAL" # 中性
    BAD    = "BAD"     # 不利于交易（趋势过强/过弱）

class TradingStyle(Enum):
    SYSTEMATIC = "SYSTEMATIC"  # 系统交易（规则驱动）
    DISCRETIONARY = "DISCRETIONARY"  # 主观交易（直觉判断）

class EntryType(Enum):
    STOP_BUY  = "STOP_BUY"
    STOP_SELL = "STOP_SELL"
    LIMIT_BUY = "LIMIT_BUY"   # 限价买单（被动）
    LIMIT_SELL = "LIMIT_SELL" # 限价卖单（被动）
    NONE = "NONE"

@dataclass
class Candle:
    """K线数据结构"""
    time: int          # Unix秒时间戳【铁律：判断最新价格的唯一依据】
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
    def upper_shadow_ratio(self) -> float:
        """上影线占整根K线的比例"""
        r = self.range
        if r == 0:
            return 0.0
        return (self.high - max(self.open, self.close)) / r

    @property
    def lower_shadow_ratio(self) -> float:
        """下影线占整根K线的比例"""
        r = self.range
        if r == 0:
            return 0.0
        return (min(self.open, self.close) - self.low) / r

    @property
    def body_ratio(self) -> float:
        """实体占整根K线的比例（0.0-1.0）"""
        r = self.range
        if r == 0:
            return 0.0
        return self.body / r

    @property
    def is_doji(self) -> bool:
        """十字星：实体 < 10%"""
        return self.body_ratio < 0.10

    @property
    def is_hammer(self) -> bool:
        """锤子线：下影线≥60%，实体≤20%，上影线≤10%"""
        return (self.lower_shadow_ratio >= 0.60 and
                self.body_ratio <= 0.20 and
                self.upper_shadow_ratio <= 0.10)

    @property
    def is_shooting_star(self) -> bool:
        """流星线：上影线≥60%，实体≤20%，下影线≤10%"""
        return (self.upper_shadow_ratio >= 0.60 and
                self.body_ratio <= 0.20 and
                self.lower_shadow_ratio <= 0.10)


@dataclass
class MarketContext:
    """市场背景评估"""
    trend: Literal["up", "down", "range"] = "range"
    trend_strength: float = 0.5   # 0.0-1.0，1.0=极强
    follow_through: float = 0.5   # 0.0-1.0，跟随度（高=趋势健康）
    consecutive_bars: int = 0      # 同向连续K线数量
    is_extreme: bool = False      # 是否在极值位置
    background_quality: BackgroundQuality = BackgroundQuality.NEUTRAL

    def __post_init__(self):
        # 评估综合背景质量
        if self.trend_strength > 0.7 and self.consecutive_bars >= 4:
            self.background_quality = BackgroundQuality.BAD  # 强趋势 = 反转背景差
        elif self.trend_strength < 0.3 and self.follow_through < 0.4:
            self.background_quality = BackgroundQuality.GOOD  # 差跟随 = 可能反转


@dataclass
class SignalBarResult:
    signal: str = "无信号"
    quality: SignalBarQuality = SignalBarQuality.LOW
    direction: Direction = Direction.WATCH
    confidence: str = "低"
    entry_price: Optional[float] = None
    entry_type: EntryType = EntryType.NONE
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    reward_risk_ratio: Optional[float] = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class TradeDecision:
    """交易决策"""
    action: Literal["EXECUTE", "SKIP", "WATCH"] = "WATCH"
    direction: Direction = Direction.WATCH
    entry_type: Optional[EntryType] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    confidence: str = "低"
    style: TradingStyle = TradingStyle.SYSTEMATIC
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# 辅助函数（铁律：必须用 time 字段）
# ══════════════════════════════════════════════════════════════════════════════

def get_latest_candle(data: list[Candle]) -> Candle:
    """
    【铁律】获取最新一根K线
    禁止使用 data[-1]，必须用 time 字段判断
    """
    if not data:
        raise ValueError("K线数据为空")
    return max(data, key=lambda c: c.time)

def get_recent_bars(data: list[Candle], count: int = 5) -> list[Candle]:
    """获取最近N根K线（按时间倒序）"""
    if not data:
        return []
    return sorted(data, key=lambda c: c.time, reverse=True)[:count]

def get_avg_range(data: list[Candle], lookback: int = 20) -> float:
    """计算平均K线幅度"""
    if len(data) < 2:
        return 0.0
    recent = sorted(data, key=lambda c: c.time, reverse=True)[:lookback]
    return sum(b.range for b in recent) / len(recent)

def is_at_support_resistance(candle: Candle, data: list[Candle], tolerance: float = 0.02) -> str:
    """判断K线是否在支撑/阻力位附近"""
    if len(data) < 5:
        return "N/A"
    recent = sorted(data, key=lambda c: c.time)[:min(50, len(data))]
    highs = [b.high for b in recent]
    lows = [b.low for b in recent]

    current = candle.close
    # 检查是否接近近期高点
    max_high = max(highs)
    if abs(current - max_high) / current < tolerance:
        return "阻力"
    # 检查是否接近近期低点
    min_low = min(lows)
    if abs(current - min_low) / current < tolerance:
        return "支撑"
    return "中性"


# ══════════════════════════════════════════════════════════════════════════════
# 规则库
# ══════════════════════════════════════════════════════════════════════════════

# ── 规则1：背景质量评估 ─────────────────────────────────────────────
RULE_BACKGROUND_ASSESSMENT = {
    "name": "背景质量评估",
    "description": "评估当前市场背景对反向交易（反转）的有利程度",
    "good_background": [
        "趋势已经运行很久、很充分",
        "出现连续反向K线但跟随很差",
        "价格多次测试支撑/阻力失败",
        "波动率收缩（整理区间）",
        "有很长的下影线（多头逢低买）",
    ],
    "bad_background": [
        "强趋势中（80%概率延续）",
        "连续同向K线，收盘都在极值位置",
        "没有测试过前期高/低点",
        "趋势刚启动不久",
        "价格紧凑、紧贴均线",
    ],
    "key_principle": "Brooks 82%规则：强趋势80%概率继续延续，只有20%概率反转",
}

def assess_background(data: list[Candle]) -> MarketContext:
    """
    评估市场背景质量
    【铁律】：必须用 time 字段判断最新价格
    """
    if len(data) < 5:
        return MarketContext()

    sorted_data = sorted(data, key=lambda c: c.time)
    recent = sorted_data[-min(20, len(data)):]

    # 计算趋势强度：最近K线的收盘位置
    latest = get_latest_candle(data)

    # 统计连续同向K线
    consecutive = 1
    for i in range(len(recent) - 2, -1, -1):
        if (recent[i+1].is_bullish and recent[i].is_bullish) or \
           (recent[i+1].is_bearish and recent[i].is_bearish):
            consecutive += 1
        else:
            break

    # 计算跟随度（平均幅度 vs 回调幅度）
    ranges = [b.range for b in recent]
    avg_range = sum(ranges) / len(ranges) if ranges else 0

    # 检查收盘是否在极值位置（高/低价附近）
    closes_near_high = sum(1 for b in recent if b.is_bullish and
                           (b.high - b.close) / b.range < 0.2)
    closes_near_low = sum(1 for b in recent if b.is_bearish and
                          (b.close - b.low) / b.range < 0.2)

    # 趋势方向
    if closes_near_high >= len(recent) * 0.6:
        trend = "up"
        trend_strength = closes_near_high / len(recent)
    elif closes_near_low >= len(recent) * 0.6:
        trend = "down"
        trend_strength = closes_near_low / len(recent)
    else:
        trend = "range"
        trend_strength = 0.5

    # 跟随度
    follow_through = min(1.0, avg_range / (sum(ranges) / len(ranges) + 0.0001))

    return MarketContext(
        trend=trend,
        trend_strength=trend_strength,
        follow_through=follow_through,
        consecutive_bars=consecutive,
        is_extreme=(consecutive >= 4),
    )


# ── 规则2：信号K线质量评估 ─────────────────────────────────────────
RULE_SIGNAL_QUALITY = {
    "name": "信号K线质量评估",
    "high_quality_criteria": {
        "body_ratio": 0.80,      # 实体占整根K线 ≥ 80%
        "shadow_ratio": 0.20,    # 影线 ≤ 20%
        "location": "支撑/阻力/趋势线/通道边/整数关口",
    },
    "medium_quality": {
        "body_ratio": (0.60, 0.80),
        "shadow_ratio": (0.20, 0.40),
    },
    "low_quality": [
        "十字星（doji）：实体 < 10%",
        "上下影线都长：多空犹豫",
        "收盘不在极值位置",
        "实体极小、影线超长",
    ],
    "key_principle": "信号K线的收盘价是关键，不在乎影线刺透多少",
}

def assess_signal_quality(candle: Candle) -> SignalBarQuality:
    """评估信号K线质量"""
    # 十字星 = 低质量
    if candle.is_doji:
        return SignalBarQuality.LOW

    body_ratio = candle.body_ratio
    upper = candle.upper_shadow_ratio
    lower = candle.lower_shadow_ratio
    total_shadow = upper + lower

    # 高质量：实体≥80%，总影线≤20%
    if body_ratio >= 0.80 and total_shadow <= 0.20:
        return SignalBarQuality.HIGH

    # 中等：实体60-80%，影线20-40%
    if body_ratio >= 0.60 and total_shadow <= 0.40:
        return SignalBarQuality.MEDIUM

    return SignalBarQuality.LOW


# ── 规则3：背景 vs 信号K线优先级 ───────────────────────────────────
RULE_PRIORITY = {
    "name": "背景与信号K线的优先级",
    "core_principle": "背景（Context）远比信号K线本身重要",
    "priority_table": {
        "好背景 + 好信号K": "最佳做反转时机，果断执行",
        "好背景 + 差信号K": "可接受，勉强可以尝试",
        "差背景 + 好信号K": "危险！即使信号漂亮也要避免",
        "差背景 + 差信号K": "绝对禁止！最低胜算",
    },
    "numerical": {
        "好背景_好信号K": "胜率70-80%，盈亏比2:1+",
        "好背景_差信号K": "胜率50-60%，盈亏比1.5:1",
        "差背景_好信号K": "胜率20-30%，盈亏比0.5:1",
        "差背景_差信号K": "胜率<10%，数学期望为负",
    },
    "brooks_quote": "在一个糟糕的背景下面，就算你的信号K线再漂亮，它反转的概率依旧是非常低的",
}

def evaluate_reversal_opportunity(
    background: MarketContext,
    signal_candle: Candle,
) -> TradeDecision:
    """
    综合评估反转交易机会
    这是P09的核心规则：背景 > 信号K线
    """
    signal_quality = assess_signal_quality(signal_candle)

    reasons = []
    warnings = []
    confidence = "低"
    action = "WATCH"
    direction = Direction.WATCH

    # 评估背景
    bg_good = background.background_quality == BackgroundQuality.GOOD
    bg_bad = background.background_quality == BackgroundQuality.BAD

    # 评估信号K
    signal_good = signal_quality in (SignalBarQuality.HIGH, SignalBarQuality.MEDIUM)
    signal_bad = signal_quality == SignalBarQuality.LOW

    # 决策矩阵
    if bg_good and signal_good:
        action = "EXECUTE"
        confidence = "高"
        direction = Direction.SHORT if background.trend == "up" else Direction.LONG
        reasons.append("好背景 + 好信号K：最佳反转时机")

    elif bg_good and signal_bad:
        action = "EXECUTE"
        confidence = "中"
        direction = Direction.SHORT if background.trend == "up" else Direction.LONG
        reasons.append("好背景 + 差信号K：勉强可以尝试")
        warnings.append("信号K质量较差，入场需谨慎")

    elif bg_bad and signal_good:
        action = "SKIP"
        confidence = "低"
        direction = Direction.WATCH
        reasons.append("差背景 + 好信号K：危险！即使信号漂亮也要避免")
        warnings.append("强趋势中信号K线容易失败，82%规则：趋势大概率延续")

    else:  # bg_bad and signal_bad
        action = "SKIP"
        confidence = "极低"
        direction = Direction.WATCH
        reasons.append("差背景 + 差信号K：绝对禁止！最低胜算")
        warnings.append("数学期望为负，不参与")

    return TradeDecision(
        action=action,
        direction=direction,
        confidence=confidence,
        reasons=reasons,
        warnings=warnings,
        style=TradingStyle.SYSTEMATIC,
    )


# ── 规则4：Bull Flag 被动入场 ──────────────────────────────────────
RULE_BULL_FLAG = {
    "name": "Bull Flag（牛市旗形）被动入场",
    "description": "在强上涨趋势中，如果想做多但不想追高，可以等回调后在旗形下沿挂LIMIT BUY",
    "when_to_use": [
        "强上涨趋势，但已经涨了很多不想追",
        "看到信号K，但背景不利于做反转（想做顺势但怕追高）",
        "想以更好的价格入场",
    ],
    "entry_method": "在回调低点下方挂LIMIT BUY（限价买单）",
    "pros": "更好的价格，减少被止损的概率",
    "cons": "可能不回调到位，错过机会",
    "key_principle": "很多有经验的交易员会这样做：不是追着买，而是在下方挂限价买单",
}

def bull_flag_entry(
    latest_candle: Candle,
    context: MarketContext,
    tick_size: float = 0.00001,
) -> Optional[TradeDecision]:
    """
    Bull Flag 被动入场策略
    在强趋势中，不是追着买/卖，而是在回调极值挂LIMIT订单
    """
    if context.trend != "up" or context.trend_strength < 0.6:
        return None

    # 检查信号K是否值得买入
    if latest_candle.is_bearish and latest_candle.is_doji:
        # 十字星 + 强趋势 = 不适合做空，但可以做Bull Flag多
        return TradeDecision(
            action="WATCH",
            direction=Direction.WATCH,
            entry_type=EntryType.LIMIT_BUY,
            entry_price=latest_candle.low - tick_size,
            confidence="中",
            style=TradingStyle.SYSTEMATIC,
            reasons=[
                "强上涨趋势中出现十字星",
                "不适合追空（差背景+差信号）",
                "可以等回调后在下方挂LIMIT BUY做Bull Flag",
            ],
            warnings=["需要等待回调确认"],
        )

    return None


# ── 规则5：82%规则 — 强趋势反转条件 ─────────────────────────────
RULE_82_PERCENT = {
    "name": "Brooks 82%规则（Elbrux 82%定理）",
    "description": "市场具有惯性，一个趋势80%的概率会随着惯性继续延续",
    "implications": [
        "强趋势中的反转尝试80%以失败告终",
        "即使看到反转信号K，胜算也只有20%左右",
        "只有非常强的设置（好背景+好信号K）才能将胜算提升到可接受水平",
    ],
    "when_to_fade_trend": [
        "趋势已经非常充分（运行很久）",
        "出现明显的疲惫信号（极值K线、波动率收缩）",
        "价格到达强支撑/阻力",
        "有连续的反向K线但跟随很差",
    ],
    "key_quote": "尽管一直在尝试反转一直在尝试向下突破，但是80%的时候这样的尝试是以失败而告终的",
}


# ── 规则6：双顶/双底形态评估 ─────────────────────────────────────
RULE_DOUBLE_TOP_BOTTOM = {
    "name": "双顶/双底形态",
    "bullish_pattern": "双底 = 两次测试支撑后向上反弹",
    "bearish_pattern": "双顶 = 两次测试阻力后向下反转",
    "signal_k_requirement": "第二顶/底的信号K线必须是高质量的",
    "neckline": "颈线（紧线）是关键入场参考",
    "entry": "在颈线下方（双顶）或上方（双底）挂STOP单",
    "stop_loss": "放在双顶/双底上方一点",
    "target": "测量运动目标：颈线到双顶/双底的距离",
    "reward_risk": "好的双顶/双底应有3:1以上的盈亏比",
    "key_case": "P09 seg0案例：双顶 + 好信号K → 3-4倍盈亏比 → 数学期望不错",
}

def detect_double_top_bottom(
    data: list[Candle],
    lookback: int = 50,
) -> Optional[SignalBarResult]:
    """
    检测双顶/双底形态
    【铁律】：必须用 time 字段判断最新价格
    """
    if len(data) < 10:
        return None

    sorted_data = sorted(data, key=lambda c: c.time)
    recent = sorted_data[-lookback:]

    # 找最近的高点（假设当前在第二个顶的位置）
    highs = [(i, b.high, b) for i, b in enumerate(recent) if b.is_bearish or i == 0]
    if len(highs) < 2:
        return None

    # 找最高的两个高点
    sorted_highs = sorted(highs, key=lambda x: x[1], reverse=True)
    if len(sorted_highs) < 2:
        return None

    top1_idx, top1_price, top1_bar = sorted_highs[0]
    top2_idx, top2_price, top2_bar = sorted_highs[1]

    # 两个顶价格接近（5%以内）
    price_diff = abs(top1_price - top2_price) / top1_price
    if price_diff > 0.05:
        return None

    # 颈线：两个顶之间的低点
    between = recent[min(top1_idx, top2_idx):max(top1_idx, top2_idx)+1]
    neckline = min(b.low for b in between)

    # 最新K线在第二个顶附近
    latest = get_latest_candle(data)
    near_top2 = abs(latest.close - top2_price) / top2_price < 0.02

    if near_top2 and top2_bar.time != latest.time:
        # 信号K线
        signal = assess_signal_quality(latest)

        # 盈亏比估算
        risk = top2_price - neckline
        reward = top2_price - latest.close  # 预估从颈线起算的目标
        if risk > 0:
            rr = reward / risk
        else:
            rr = 0

        return SignalBarResult(
            signal="双顶形态",
            quality=signal,
            direction=Direction.SHORT,
            confidence="高" if signal == SignalBarQuality.HIGH and rr >= 2 else "中",
            entry_price=neckline - 0.00001,
            entry_type=EntryType.STOP_SELL,
            stop_loss=top2_price + 0.00001,
            target=neckline - (top2_price - neckline),
            reward_risk_ratio=rr,
            reasons=[
                f"双顶形成（两顶价格差{price_diff:.1%}）",
                f"颈线支撑位：{neckline}",
                f"信号K线质量：{signal.value}",
                f"预估盈亏比：{rr:.1f}:1",
            ]
        )

    return None


# ── 规则7：系统交易 vs 主观交易 ────────────────────────────────────
RULE_SYSTEMATIC_VS_DISCRETIONARY = {
    "name": "系统交易 vs 主观交易",
    "systematic": {
        "description": "严格按照规则交易，不受情绪干扰",
        "rules": [
            "背景差 + 信号K差 → 不交易",
            "背景差 + 信号K好 → 不交易（82%规则）",
            "背景好 + 信号K差 → 可交易",
            "背景好 + 信号K好 → 果断交易",
        ],
        "pros": "一致性，可量化，可回测",
        "cons": "可能错过主观判断能捕捉的机会",
    },
    "discretionary": {
        "description": "依赖交易员的主观判断和经验",
        "pros": "灵活，能适应市场变化",
        "cons": "易受情绪影响，一致性差",
    },
    "brooks_view": "Brooks是系统交易者，但他也说：好的主观交易员其实是把规则内化了，本质上还是系统交易",
    "key_advice": "不要问'我想做多还是做空'，而要问'背景和信号K是否符合我的交易规则'",
}


# ══════════════════════════════════════════════════════════════════════════════
# 核心函数
# ══════════════════════════════════════════════════════════════════════════════

def analyze_reversal(
    data: list[Candle],
    signal_bar: Optional[Candle] = None,
    tick_size: float = 0.00001,
) -> TradeDecision:
    """
    综合分析反转交易机会

    【铁律】：K线数据必须以 time 字段判断最新价格，禁止用 data[-1]

    参数：
        data: K线数据列表（按时间正序）
        signal_bar: 信号K线（默认为最新K线）
        tick_size: 最小价格变动

    返回：
        TradeDecision: 包含交易决策和完整理由
    """
    if len(data) < 3:
        return TradeDecision(action="WATCH", reasons=["数据不足"])

    latest = get_latest_candle(data)
    signal_bar = signal_bar or latest

    # 评估背景
    context = assess_background(data)

    # 评估信号K
    signal_quality = assess_signal_quality(signal_bar)

    # 综合决策
    decision = evaluate_reversal_opportunity(context, signal_bar)

    # 如果可以执行，计算入场细节
    if decision.action == "EXECUTE":
        if decision.direction == Direction.SHORT:
            decision.entry_type = EntryType.STOP_SELL
            decision.entry_price = signal_bar.low - tick_size
            decision.stop_loss = signal_bar.high + tick_size
        else:
            decision.entry_type = EntryType.STOP_BUY
            decision.entry_price = signal_bar.high + tick_size
            decision.stop_loss = signal_bar.low - tick_size

        # 计算盈亏比
        if decision.entry_price and decision.stop_loss:
            risk = abs(decision.entry_price - decision.stop_loss)
            if risk > 0 and decision.target:
                decision.reasons.append(f"预估盈亏比：{abs(decision.target - decision.entry_price) / risk:.1f}:1")

    # 添加背景信息到理由
    bg_desc = {
        "up": f"上涨趋势（强度{context.trend_strength:.0%}，连续{context.consecutive_bars}根）",
        "down": f"下跌趋势（强度{context.trend_strength:.0%}，连续{context.consecutive_bars}根）",
        "range": "区间震荡",
    }.get(context.trend, "未知")
    decision.reasons.insert(0, f"背景：{bg_desc}")
    decision.reasons.insert(1, f"信号K质量：{signal_quality.value}")

    return decision


def should_skip_trade(
    data: list[Candle],
    direction: str = "",
    tick_size: float = 0.00001,
) -> tuple[bool, str]:
    """
    判断是否应该跳过交易（避免在差背景下交易）

    【铁律】：必须用 time 字段判断最新价格

    返回：
        (should_skip, reason)
    """
    if len(data) < 3:
        return True, "数据不足"

    latest = get_latest_candle(data)
    context = assess_background(data)
    signal_quality = assess_signal_quality(latest)

    # 规则：差背景 + 任何信号K → 跳过
    if context.background_quality == BackgroundQuality.BAD:
        return True, f"背景糟糕（强{context.trend}趋势，连续{context.consecutive_bars}根K线），82%规则：趋势大概率延续，应跳过反向交易"

    # 规则：十字星信号K + 强趋势 → 跳过（除非做Bull Flag）
    if latest.is_doji and context.consecutive_bars >= 3:
        return True, f"十字星K线 + 强趋势（{context.consecutive_bars}根连续{context.trend}K线）= 低胜算反向交易"

    # 规则：差跟随（长下影线）+ 强趋势 → 视为趋势中的正常回调，不反转
    if context.follow_through < 0.4 and context.consecutive_bars >= 3:
        return True, f"跟随差（{context.follow_through:.0%}）+ 长下影线 = 更可能是趋势中的正常回调而非反转"

    return False, "通过检查，可以交易"


# ══════════════════════════════════════════════════════════════════════════════
# 测试
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import time

    now = int(time.time())
    base_price = 1.10000

    # 模拟强上涨趋势（连续阳线收盘在高位）
    test_data = [
        # 强上涨中，每次回调都很浅（多头逢低买）
        Candle(time=now - 3600*10, open=base_price - 0.00010, high=base_price + 0.00080, low=base_price - 0.00010, close=base_price + 0.00070, volume=1500),
        Candle(time=now - 3600*9,  open=base_price + 0.00070, high=base_price + 0.00120, low=base_price + 0.00050, close=base_price + 0.00110, volume=1600),
        Candle(time=now - 3600*8,  open=base_price + 0.00110, high=base_price + 0.00160, low=base_price + 0.00090, close=base_price + 0.00150, volume=1400),
        Candle(time=now - 3600*7,  open=base_price + 0.00150, high=base_price + 0.00200, low=base_price + 0.00140, close=base_price + 0.00190, volume=1700),
        Candle(time=now - 3600*6,  open=base_price + 0.00190, high=base_price + 0.00240, low=base_price + 0.00180, close=base_price + 0.00230, volume=1550),
        # 回调（小实体K线，下影线长 = 多头逢低买）
        Candle(time=now - 3600*5,  open=base_price + 0.00230, high=base_price + 0.00250, low=base_price + 0.00180, close=base_price + 0.00185, volume=1200),
        Candle(time=now - 3600*4,  open=base_price + 0.00185, high=base_price + 0.00210, low=base_price + 0.00180, close=base_price + 0.00190, volume=1100),
        # 继续上涨
        Candle(time=now - 3600*3,  open=base_price + 0.00190, high=base_price + 0.00260, low=base_price + 0.00180, close=base_price + 0.00250, volume=1650),
        Candle(time=now - 3600*2,  open=base_price + 0.00250, high=base_price + 0.00300, low=base_price + 0.00240, close=base_price + 0.00290, volume=1750),
        # 接近前高，开始犹豫（十字星）
        Candle(time=now - 3600,   open=base_price + 0.00290, high=base_price + 0.00310, low=base_price + 0.00270, close=base_price + 0.00285, volume=1300),
        # 最新K线：差信号K（在强趋势中想反转型十字星）
        Candle(time=now,          open=base_price + 0.00285, high=base_price + 0.00300, low=base_price + 0.00260, close=base_price + 0.00275, volume=1400),
    ]

    print("P09 系统交易 vs 主观交易 — 决策引擎测试")
    print("=" * 70)
    print(f"最新K线时间：{get_latest_candle(test_data).time}")

    latest = get_latest_candle(test_data)
    print(f"\n最新K线（时间={latest.time}）：")
    print(f"  O:{latest.open:.5f} H:{latest.high:.5f} L:{latest.low:.5f} C:{latest.close:.5f}")
    print(f"  类型：{'阳线' if latest.is_bullish else '阴线'} | 实体比：{latest.body_ratio:.1%} | 下影线比：{latest.lower_shadow_ratio:.1%}")

    # 测试背景评估
    print("\n【背景评估】")
    context = assess_background(test_data)
    print(f"  趋势：{context.trend} | 强度：{context.trend_strength:.0%}")
    print(f"  连续K线：{context.consecutive_bars}根 | 背景质量：{context.background_quality.value}")

    # 测试信号K评估
    print("\n【信号K线评估】")
    sq = assess_signal_quality(latest)
    print(f"  质量：{sq.value} | 十字星：{latest.is_doji}")

    # 测试是否应跳过
    print("\n【跳过检查】")
    skip, reason = should_skip_trade(test_data)
    print(f"  应跳过：{skip} | 原因：{reason}")

    # 测试综合分析
    print("\n【反转分析】")
    decision = analyze_reversal(test_data)
    print(f"  决策：{decision.action} | 方向：{decision.direction.value} | 置信度：{decision.confidence}")
    for r in decision.reasons:
        print(f"    - {r}")
    if decision.warnings:
        print(f"  ⚠ 警告：{decision.warnings}")

    # 测试Bull Flag
    print("\n【Bull Flag 检查】")
    bf = bull_flag_entry(latest, context)
    if bf:
        print(f"  建议：{bf.reasons}")
    else:
        print("  无Bull Flag信号")

    # 测试双顶检测（构造一个双顶场景）
    print("\n【双顶检测（构造场景）】")
    double_top_data = [
        Candle(time=now - 3600*8, open=1.09500, high=1.10500, low=1.09400, close=1.10400, volume=2000),
        Candle(time=now - 3600*7, open=1.10400, high=1.11400, low=1.10300, close=1.11300, volume=2100),
        Candle(time=now - 3600*6, open=1.11300, high=1.12300, low=1.11200, close=1.12200, volume=2200),
        # 第一顶
        Candle(time=now - 3600*5, open=1.12200, high=1.12500, low=1.11800, close=1.11850, volume=1900),
        # 回调
        Candle(time=now - 3600*4, open=1.11850, high=1.12100, low=1.11200, close=1.11300, volume=1800),
        Candle(time=now - 3600*3, open=1.11300, high=1.12000, low=1.11200, close=1.11900, volume=1700),
        # 第二顶（接近第一顶）
        Candle(time=now - 3600*2, open=1.11900, high=1.12480, low=1.11800, close=1.11850, volume=2000),
        # 信号K：大阴线跌破颈线
        Candle(time=now - 3600,   open=1.11850, high=1.11950, low=1.11300, close=1.11200, volume=2300),
        # 最新：等待确认
        Candle(time=now,          open=1.11200, high=1.11400, low=1.11100, close=1.11150, volume=2400),
    ]
    dt = detect_double_top_bottom(double_top_data)
    if dt:
        print(f"  信号：{dt.signal} | 方向：{dt.direction.value}")
        print(f"  入场价：{dt.entry_price:.5f} | 止损：{dt.stop_loss:.5f} | 目标：{dt.target:.5f}")
        print(f"  盈亏比：{dt.reward_risk_ratio:.1f}:1 | 置信度：{dt.confidence}")
        for r in dt.reasons:
            print(f"    - {r}")
    else:
        print("  未检测到双顶")

    print("\n" + "=" * 70)
    print("测试完成")
