#!/usr/bin/env python3
"""
P03 蜡烛图 — 专家决策规则库
================================================
来源：方方土价格行为学 · 蜡烛图
视频：03-02蜡烛图-每天都在看，却忽视了K线传达的真正信息
分析方法：Whisper字幕（356行）+ Vision截图分析（5帧）

核心主题：
  1. 蜡烛图四价位（O/H/L/C）的形成逻辑
  2. 大阳线/大阴线的日内形成轨迹
  3. 早盘反转：H/L 在早盘形成，实体在尾盘完成
  4. 日线平均波动（Average Daily Range）约束反转幅度
  5. 十字星特征与开盘价磁铁效应
  6. 震荡区间中的十字星均值回归机会
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

class CandleType(Enum):
    BULL_ENGULFING = "大阳线（看多）"
    BEAR_ENGULFING = "大阴线（看空）"
    DOJI           = "十字星"
    SMALL_BODY     = "小实体K线"
    NORMAL         = "普通K线"
    UNKNOWN        = "无法判断"

class FormationTime(Enum):
    EARLY_SESSION  = "早盘形成（前半段）"
    LATE_SESSION   = "尾盘形成（后半段）"
    MIXED          = "高低点分散"
    UNKNOWN        = "无法判断"

@dataclass
class CandleInfo:
    """单根K线的完整信息"""
    open: float
    high: float
    low: float
    close: float
    time: str  # 时间戳，用于定位最新K线

    @property
    def body(self) -> float:
        """实体大小（绝对值）"""
        return abs(self.close - self.open)

    @property
    def body_direction(self) -> Direction:
        """实体方向"""
        if self.close > self.open:
            return Direction.LONG
        elif self.close < self.open:
            return Direction.SHORT
        return Direction.NONE

    @property
    def total_range(self) -> float:
        """全周期振幅（H-L）"""
        return self.high - self.low

    @property
    def upper_shadow(self) -> float:
        """上影线长度"""
        if self.close >= self.open:
            return self.high - self.close
        else:
            return self.high - self.open

    @property
    def lower_shadow(self) -> float:
        """下影线长度"""
        if self.close >= self.open:
            return self.open - self.low
        else:
            return self.close - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclass
class CandlestickResult:
    candle_type: CandleType = CandleType.UNKNOWN
    formation_time: FormationTime = FormationTime.UNKNOWN
    direction: Direction = Direction.WATCH
    confidence: str = "低"
    high_prob低点: Optional[float] = None   # 高概率低点位置（用于 Buy Limit）
    high_prob高点: Optional[float] = None   # 高概率高点位置（用于 Sell Stop）
    reasons: list[str] = field(default_factory=list)


@dataclass
class EarlySessionReversalResult:
    """早盘反转检测结果"""
    detected: bool = False
    direction: Direction = Direction.WATCH
    reversal_point: Optional[float] = None  # 反转点（如最低点/最高点）
    entry_zone: Optional[float] = None      # 入场区域
    confidence: str = "低"
    avg_daily_range: Optional[float] = None
    early_move_pct: Optional[float] = None   # 早盘移动百分比
    reasons: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# 核心规则库
# ══════════════════════════════════════════════════════════════════════════════

# 日线平均波动参考值（SPY 约为 0.8%，可按标的调整）
DEFAULT_AVG_DAILY_RANGE_PCT = 0.008


def get_candle_type(candle: CandleInfo,
                    body_ratio_threshold: float = 0.7,
                    shadow_ratio_threshold: float = 0.6) -> CandleType:
    """
    判断K线类型（大阳/大阴/十字星/正常）

    判断逻辑（参考 Brooks 教学）：
      - 十字星：实体极小（< 总幅度的 10%），上下影线至少有一个较长
      - 大阳线：实体很大（> 总幅度的 body_ratio_threshold），且收盘 > 开盘
      - 大阴线：实体很大（> 总幅度的 body_ratio_threshold），且收盘 < 开盘
      - 小实体K线：实体偏小，在总幅度 10%~70% 之间
      - 普通K线：实体比例适中

    Args:
        candle: K线数据（必须含 O/H/L/C）
        body_ratio_threshold: 实体占全幅（高-低）的比例阈值，默认 0.7
        shadow_ratio_threshold: 影线占全幅的比例阈值，默认 0.6

    Returns:
        CandleType 枚举值
    """
    total_range = candle.total_range
    if total_range == 0:
        return CandleType.UNKNOWN

    body_ratio = candle.body / total_range
    upper_ratio = candle.upper_shadow / total_range
    lower_ratio = candle.lower_shadow / total_range
    max_shadow_ratio = max(upper_ratio, lower_ratio)

    # 十字星：实体极小
    if body_ratio < 0.10:
        return CandleType.DOJI

    # 大阳线
    if candle.is_bullish and body_ratio >= body_ratio_threshold:
        return CandleType.BULL_ENGULFING

    # 大阴线
    if candle.is_bearish and body_ratio >= body_ratio_threshold:
        return CandleType.BEAR_ENGULFING

    # 小实体K线（震荡型）
    if body_ratio < 0.40:
        return CandleType.SMALL_BODY

    return CandleType.NORMAL


def _infer_formation_time_by_shadows(candle: CandleInfo,
                                      min_shadow_ratio: float = 0.5) -> FormationTime:
    """
    通过影线比例推断 H/L 的形成时间（早盘 vs 尾盘）

    Brooks 核心观点：
      - 趋势K线（Trending Bar）：H/L 在早盘形成，影线是尾盘反转
      - 震荡K线（Ranging Bar）：H/L 分散，影线可能贯穿全天

    推断逻辑（基于影线相对长度）：
      - 下影线 >> 上影线（如 2:1）：L 是主要极值，大概率早盘形成 → 强势上涨
      - 上影线 >> 下影线（如 2:1）：H 是主要极值，大概率早盘形成 → 强势下跌
      - 上下影线接近：多空拉锯，可能是震荡

    Returns:
        FormationTime 枚举
    """
    total_range = candle.total_range
    if total_range == 0:
        return FormationTime.UNKNOWN

    upper = candle.upper_shadow / total_range
    lower = candle.lower_shadow / total_range

    # 明显偏向下影线（长下影）
    if lower > upper * 1.5 and lower > 0.3:
        return FormationTime.EARLY_SESSION  # 低点早盘形成

    # 明显偏向上影线（长上影）
    if upper > lower * 1.5 and upper > 0.3:
        return FormationTime.EARLY_SESSION  # 高点早盘形成

    # 上下影线都很长（震荡特征）
    if upper > 0.3 and lower > 0.3:
        return FormationTime.MIXED

    return FormationTime.UNKNOWN


def detect_early_session_reversal(bars: list[CandleInfo],
                                  avg_daily_range_pct: float = DEFAULT_AVG_DAILY_RANGE_PCT,
                                  reversal_threshold: float = 0.005) -> EarlySessionReversalResult:
    """
    检测早盘反转信号（核心入场规则）

    Brooks 核心逻辑：
      - 在 Uptrend 中，早盘下跌形成低点（L），随后反转向上
      - 在 Downtrend 中，早盘上涨形成高点（H），随后反转向下
      - 早盘趋势幅度越大（接近日均波动），反转后形成十字星的概率越高（>90%）

    检测规则：
      1. 取最近一根日K线（或日内关键K线）
      2. 判断是否为大实体K线（body_ratio > 0.6）
      3. 计算早盘移动幅度（开盘到极值的距离）
      4. 若早盘幅度 > reversal_threshold 且方向与收盘方向相反 → 早盘反转信号

    Args:
        bars: K线数据列表（必须包含 time/date 字段，用于定位最新K线）
        avg_daily_range_pct: 日线平均波动（默认 0.8%）
        reversal_threshold: 反转检测阈值（默认 0.5%）

    Returns:
        EarlySessionReversalResult
    """
    if not bars:
        return EarlySessionReversalResult()

    # 使用 time 字段定位最新K线（严格遵守数据定位规则）
    latest = max(bars, key=lambda x: x.time)
    prior = None
    if len(bars) >= 2:
        # 排除最新K线，找前一根
        sorted_bars = sorted(bars, key=lambda x: x.time)
        idx = sorted_bars.index(latest)
        if idx > 0:
            prior = sorted_bars[idx - 1]

    candle_type = get_candle_type(latest)
    formation_time = _infer_formation_time_by_shadows(latest)

    # 计算早盘移动幅度（相对于收盘价的百分比）
    if latest.is_bullish:
        early_move_pct = (latest.open - latest.low) / latest.close if latest.close != 0 else 0
    else:
        early_move_pct = (latest.high - latest.open) / latest.close if latest.close != 0 else 0

    result = EarlySessionReversalResult()
    result.avg_daily_range = avg_daily_range_pct
    result.early_move_pct = early_move_pct

    # 规则 1：K线类型判断
    if candle_type == CandleType.BULL_ENGULFING:
        # 大阳线 → 检测早盘是否有下跌反转
        if latest.lower_shadow > latest.upper_shadow * 1.5:
            result.detected = True
            result.direction = Direction.LONG
            result.reversal_point = latest.low
            result.entry_zone = latest.low  # 低点下方入场
            result.confidence = "高"
            result.reasons.append("大阳线 + 长下影线 → 早盘低点反转信号")
            result.reasons.append(f"早盘下跌幅度 {early_move_pct:.2%}（日均波动 {avg_daily_range_pct:.2%}）")

    elif candle_type == CandleType.BEAR_ENGULFING:
        # 大阴线 → 检测早盘是否有上涨反转
        if latest.upper_shadow > latest.lower_shadow * 1.5:
            result.detected = True
            result.direction = Direction.SHORT
            result.reversal_point = latest.high
            result.entry_zone = latest.high  # 高点上方做空
            result.confidence = "高"
            result.reasons.append("大阴线 + 长上影线 → 早盘高点反转信号")

    elif candle_type == CandleType.DOJI:
        # 十字星 → 开盘价磁铁效应
        result.detected = True
        result.direction = Direction.WATCH
        result.confidence = "中"
        result.reasons.append("十字星 → 开盘价是磁铁，关注收盘后回归开盘价的机会")
        result.high_prob低点 = latest.low
        result.high_prob高点 = latest.high

    # 规则 2：早盘幅度 vs 日均波动
    if early_move_pct > avg_daily_range_pct * 0.8:
        result.reasons.append(
            f"早盘幅度 {early_move_pct:.2%} 超过日均波动的 80%，"
            "即使反转大概率仍收成十字星，下方空间有限"
        )
        # 提高置信度
        if result.confidence == "中":
            result.confidence = "高"

    if prior:
        result.reasons.append(f"前一根K线：{prior.time}，收盘 {prior.close:.4f}")

    return result


def analyze_candle_formation(candle: CandleInfo) -> CandlestickResult:
    """
    分析单根K线的形成过程（核心洞察输出）

    Brooks 核心观点（从视频截图 p03_04 提取）：
      - 大阴线形成轨迹：开盘 → 先小涨形成 H → 大幅下跌形成 L → 略反弹收在 C
      - 最高点（H）通常在早盘形成
      - 最低点（L）通常在尾盘形成
      - 上影线是早盘多方尝试，下影线是尾盘空头反扑

    Returns:
        CandlestickResult 含完整分析
    """
    result = CandlestickResult()
    candle_type = get_candle_type(candle)
    formation_time = _infer_formation_time_by_shadows(candle)
    result.candle_type = candle_type
    result.formation_time = formation_time

    total_range = candle.total_range
    body_ratio = candle.body / total_range if total_range > 0 else 0

    # 主要分析逻辑
    if candle_type == CandleType.BEAR_ENGULFING:
        result.direction = Direction.SHORT
        result.confidence = "高"

        if candle.upper_shadow > candle.lower_shadow:
            # 长上影 → H 在早盘形成
            result.high_prob高点 = candle.high
            result.reasons.append(
                f"大阴线：开盘{candle.open:.4f} → 早盘冲高至H {candle.high:.4f} → "
                f"空方主导下跌至L {candle.low:.4f} → 尾盘反弹收于C {candle.close:.4f}"
            )
            result.reasons.append("H（最高价）在早盘形成，是空头高位做空的机会点")
        else:
            result.reasons.append("大阴线形成，下影线较长，关注低点是否被下破")

    elif candle_type == CandleType.BULL_ENGULFING:
        result.direction = Direction.LONG
        result.confidence = "高"

        if candle.lower_shadow > candle.upper_shadow:
            # 长下影 → L 在早盘形成
            result.high_prob低点 = candle.low
            result.reasons.append(
                f"大阳线：开盘{candle.open:.4f} → 早盘下探至L {candle.low:.4f} → "
                f"多方主导上涨至H {candle.high:.4f} → 尾盘收于C {candle.close:.4f}"
            )
            result.reasons.append("L（最低价）在早盘形成，是多头低位买入的机会点")
        else:
            result.reasons.append("大阳线形成，关注回调至支撑位的买入机会")

    elif candle_type == CandleType.DOJI:
        result.direction = Direction.WATCH
        result.confidence = "中"
        result.high_prob低点 = candle.low
        result.high_prob高点 = candle.high

        if candle.upper_shadow > candle.lower_shadow * 2:
            result.reasons.append(
                f"十字星（长上影）：O {candle.open:.4f} ≈ C {candle.close:.4f}，"
                f"H {candle.high:.4f}，L {candle.low:.4f}"
            )
            result.reasons.append("高点在早盘形成 → 尾盘无力维持，反转向下概率高")
        elif candle.lower_shadow > candle.upper_shadow * 2:
            result.reasons.append(
                f"十字星（长下影）：O {candle.open:.4f} ≈ C {candle.close:.4f}，"
                f"H {candle.high:.4f}，L {candle.low:.4f}"
            )
            result.reasons.append("低点在早盘形成 → 尾盘企稳，反转向上概率高")
        else:
            result.reasons.append(
                f"十字星实体极小（{body_ratio:.1%}），H/L 可能分散在全天，通常有事件驱动"
            )

    elif candle_type == CandleType.SMALL_BODY:
        result.direction = Direction.WATCH
        result.confidence = "低"
        result.reasons.append(f"小实体K线（实体占比 {body_ratio:.1%}），震荡特征明显")
        result.reasons.append("若在震荡区间中，关注开盘价磁铁效应（回归开盘价）")

    else:
        result.confidence = "低"
        result.reasons.append(f"普通K线，实体占比 {body_ratio:.1%}，无特殊信号")

    return result


def detect_opening_price_magnet(bars: list[CandleInfo],
                                lookback: int = 5) -> dict:
    """
    检测开盘价磁铁效应（Opening Price Magnet）

    Brooks 核心观点：
      - 开盘价是一个磁铁（Opening Price is a Magnet）
      - 十字星/小实体K线后，价格会向开盘价回归
      - 在震荡区间中，这个效应更明显

    Args:
        bars: K线数据列表
        lookback: 回溯K线数量

    Returns:
        dict，含磁铁强度、入场方向建议
    """
    if len(bars) < 2:
        return {"detected": False, "reasons": ["数据不足"]}

    sorted_bars = sorted(bars, key=lambda x: x.time)
    recent = sorted_bars[-lookback:]

    # 找最近十字星或小实体
    doji_or_small = []
    for bar in recent:
        ct = get_candle_type(bar)
        if ct in (CandleType.DOJI, CandleType.SMALL_BODY):
            doji_or_small.append(bar)

    if not doji_or_small:
        return {"detected": False, "reasons": ["最近无十字星/小实体K线"]}

    latest_doji = doji_or_small[-1]
    open_price = latest_doji.open
    current_close = sorted_bars[-1].close

    deviation_pct = abs(current_close - open_price) / open_price if open_price != 0 else 0

    result = {
        "detected": True,
        "doji_bar": {
            "time": latest_doji.time,
            "open": open_price,
            "close": latest_doji.close,
            "high": latest_doji.high,
            "low": latest_doji.low,
        },
        "current_close": current_close,
        "deviation_pct": deviation_pct,
        "direction": "LONG" if current_close < open_price else "SHORT",
        "reasons": []
    }

    if deviation_pct > 0.005:  # 偏离超过 0.5%
        result["reasons"].append(
            f"当前价格偏离开盘价 {deviation_pct:.2%}，有向开盘价回归的动力"
        )
        result["entry_zone"] = open_price
        result["confidence"] = "高" if deviation_pct > 0.01 else "中"
    else:
        result["reasons"].append("价格已接近开盘价，磁铁效应已兑现")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════

def make_candle_from_dict(d: dict) -> CandleInfo:
    """
    从字典创建 CandleInfo（安全构造器）
    严格使用 time/date 字段定位数据
    """
    # 优先使用 time，其次 date
    ts = d.get("time") or d.get("date")
    if ts is None:
        raise ValueError("K线数据必须包含 time 或 date 字段")
    return CandleInfo(
        open=float(d["open"]),
        high=float(d["high"]),
        low=float(d["low"]),
        close=float(d["close"]),
        time=str(ts),
    )


# ══════════════════════════════════════════════════════════════════════════════
# 测试用例
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json

    # 模拟数据：视频中描述的大阴线形成场景
    test_bars = [
        {
            "time": "2024-01-02 09:30",
            "open": 100.00,
            "high": 100.50,  # 早盘形成
            "low": 98.00,
            "close": 98.50   # 尾盘收低
        },
        {
            "time": "2024-01-02 10:30",
            "open": 98.50,
            "high": 99.20,
            "low": 97.80,
            "close": 98.20
        }
    ]

    bars = [make_candle_from_dict(d) for d in test_bars]

    print("=" * 60)
    print("P03 蜡烛图专家规则库 — 测试")
    print("=" * 60)

    for bar in bars:
        result = analyze_candle_formation(bar)
        print(f"\nK线 {bar.time}: {bar.open:.2f}/{bar.high:.2f}/{bar.low:.2f}/{bar.close:.2f}")
        print(f"  类型: {result.candle_type.value}")
        print(f"  方向: {result.direction.value}")
        print(f"  置信度: {result.confidence}")
        print(f"  理由: {'; '.join(result.reasons)}")

    print("\n" + "=" * 60)
    print("早盘反转检测:")
    reversal = detect_early_session_reversal(bars, avg_daily_range_pct=0.008)
    print(f"  检测到: {reversal.detected}")
    print(f"  方向: {reversal.direction.value}")
    print(f"  反转点: {reversal.reversal_point}")
    print(f"  入场区: {reversal.entry_zone}")
    print(f"  理由: {'; '.join(reversal.reasons)}")

    print("\n" + "=" * 60)
    print("开盘价磁铁检测:")
    magnet = detect_opening_price_magnet(bars)
    print(json.dumps(magnet, indent=2, ensure_ascii=False))
