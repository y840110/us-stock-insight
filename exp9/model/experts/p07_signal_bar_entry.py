"""
P07 信号K线与入场 (Signal Bar & Entry)
方方土价格行为学 · 专家脚本

核心概念：
1. 趋势K线 vs 震荡K线
2. 信号K线的定义与分类
3. 入场时机：等待信号K线突破（Buy Stop / Stop Order）
4. 环境背景 > 信号本身（核心原则）

作者：Jax (AI Agent)
学习来源：方方土价格行为学 P07
"""

from __future__ import annotations
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class TrendType(Enum):
    TREND_BAR = "trend_bar"       # 趋势K线：有方向性，实体大
    RANGE_BAR = "range_bar"      # 震荡K线：无方向性，实体小影线长


@dataclass
class SignalBar:
    """信号K线数据结构"""
    time: int          # Unix时间戳（禁止用 data[-1] 取最新价）
    direction: str     # "bullish" | "bearish"
    bar_type: TrendType
    body_ratio: float  # 实体/总长度 比率（>0.6 为趋势K线）
    close_position: float  # 收盘位置：close 在 H-L 的相对位置（0~1）
    is_signal: bool   # 是否为有效信号K线
    signal_strength: str  # "strong" | "medium" | "weak"


def is_trend_bar(bar: Dict, min_body_ratio: float = 0.6) -> bool:
    """
    判断是否为趋势K线（非震荡K线）

    趋势K线特征：
    - 实体部分占比大（body_ratio >= min_body_ratio）
    - 影线相对较小
    - 本身具有方向性

    Args:
        bar: K线数据字典，包含 open/high/low/close 字段
        min_body_ratio: 最小实体比率，默认0.6

    Returns:
        True = 趋势K线，False = 震荡K线

    注意：必须以 bar['time'] 定位最新价格，禁止用 bar[-1]
    """
    high = bar['high']
    low = bar['low']
    open_ = bar['open']
    close = bar['close']

    total_range = high - low
    if total_range == 0:
        return False

    body = abs(close - open_)
    body_ratio = body / total_range

    return body_ratio >= min_body_ratio


def is_signal_bar_formed(
    bar: Dict,
    prev_bars: List[Dict],
    direction: str = "bullish",
    min_body_ratio: float = 0.5
) -> Tuple[bool, SignalBar]:
    """
    判断信号K线是否形成

    信号K线条件：
    1. 本身是趋势K线（实体占比 >= min_body_ratio）
    2. 收在极端位置（收盘在 K 线区间的 60% 以上位置）
       - 做多信号：收盘在 K 线高端（close 靠近 high）
       - 做空信号：收盘在 K 线低端（close 靠近 low）

    Args:
        bar: 当前K线（必须是含 time 字段的字典）
        prev_bars: 前几根K线（用于判断背景）
        direction: "bullish"（做多信号）| "bearish"（做空信号）
        min_body_ratio: 最小实体比率

    Returns:
        (is_formed, SignalBar对象)
    """
    high = bar['high']
    low = bar['low']
    open_ = bar['open']
    close = bar['close']

    total_range = high - low
    if total_range == 0:
        return False, SignalBar(
            time=bar['time'], direction=direction,
            bar_type=TrendType.RANGE_BAR,
            body_ratio=0.0, close_position=0.0,
            is_signal=False, signal_strength="weak"
        )

    body = abs(close - open_)
    body_ratio = body / total_range

    # 收盘位置：0=最低，1=最高
    close_position = (close - low) / total_range if direction == "bullish" else (high - close) / total_range

    # 判断是否为趋势K线
    trend = is_trend_bar(bar, min_body_ratio=min_body_ratio)

    # 信号K线判断：
    # 做多：收盘位置 >= 60%，实体占比 >= 50%
    # 做空：收盘位置 >= 60%，实体占比 >= 50%
    is_signal = trend and body_ratio >= min_body_ratio and close_position >= 0.60

    # 信号强度
    if body_ratio >= 0.7 and close_position >= 0.80:
        strength = "strong"
    elif body_ratio >= 0.6 and close_position >= 0.70:
        strength = "medium"
    else:
        strength = "weak"

    signal_bar = SignalBar(
        time=bar['time'],
        direction=direction,
        bar_type=TrendType.TREND_BAR if trend else TrendType.RANGE_BAR,
        body_ratio=body_ratio,
        close_position=close_position,
        is_signal=is_signal,
        signal_strength=strength
    )

    return is_signal, signal_bar


def find_entry_after_signal(
    bars: List[Dict],
    signal_bar_index: int,
    direction: str = "bullish",
    tick_size: float = 1.0
) -> Optional[Dict]:
    """
    找信号K线后的入场点（Buy Stop / Sell Stop）

    核心逻辑：
    - 信号K线形成后，不要立即在收盘价入场
    - 做多：等待信号K线最高点被突破（Buy Stop 在 high 上方 1 tick）
    - 做空：等待信号K线最低点被突破（Sell Stop 在 low 下方 1 tick）

    Args:
        bars: 所有K线数据（必须含 time 字段，按时间排序）
        signal_bar_index: 信号K线的索引
        direction: "bullish" | "bearish"
        tick_size: 最小价格波动单位

    Returns:
        入场点字典（包含 entry_price, stop_loss 等），如果未触发返回 None

    注意：必须以 time 字段定位价格，禁止用 bars[-1]
    """
    if signal_bar_index < 0 or signal_bar_index >= len(bars) - 1:
        return None

    signal_bar = bars[signal_bar_index]
    high = signal_bar['high']
    low = signal_bar['low']

    if direction == "bullish":
        # 做多入场点：信号K线最高点上方 1 tick
        entry_price = high + tick_size

        # 止损：信号K线最低点下方
        stop_loss = low - tick_size

    else:  # bearish
        # 做空入场点：信号K线最低点下方 1 tick
        entry_price = low - tick_size

        # 止损：信号K线最高点上方
        stop_loss = high + tick_size

    # 计算盈亏比（需要目标价，这里简化处理）
    risk = abs(entry_price - stop_loss)

    return {
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "signal_bar_time": signal_bar['time'],
        "direction": direction,
        "risk_per_tick": risk / tick_size if tick_size > 0 else 0
    }


def analyze_context(bars: List[Dict], current_index: int) -> Dict:
    """
    分析当前K线所处的环境背景

    核心原则：环境背景 > 信号K线本身

    检查项：
    1. 是否在强趋势中（上升/下降通道）
    2. 是否在震荡区间中
    3. 是否在重要支撑/阻力位（50%回撤、前高低等）

    Args:
        bars: K线数据（必须含 time 字段）
        current_index: 当前K线索引

    Returns:
        环境分析字典
    """
    if current_index < 5:
        return {"regime": "unknown", "context": "insufficient_data"}

    recent = bars[max(0, current_index - 20):current_index + 1]

    # 计算最近高低点
    highs = [b['high'] for b in recent]
    lows = [b['low'] for b in recent]

    current_close = recent[-1]['close']
    current_high = max(highs)
    current_low = min(lows)

    # 判断区间宽度
    range_width = current_high - current_low
    avg_range = range_width / len(recent) if len(recent) > 0 else 0

    # 判断是否窄幅震荡
    is_narrow_range = avg_range > 0 and range_width / avg_range < 10

    # 判断趋势方向（简单用最近5根K线的线性回归斜率）
    if len(recent) >= 5:
        closes = [b['close'] for b in recent[-5:]]
        # 简化判断：涨了多少根 vs 跌了多少根
        ups = sum(1 for i in range(1, 5) if closes[i] > closes[i-1])
        downs = sum(1 for i in range(1, 5) if closes[i] < closes[i-1])
        if ups >= 4:
            trend_direction = "strong_uptrend"
        elif downs >= 4:
            trend_direction = "strong_downtrend"
        elif ups >= 3:
            trend_direction = "uptrend"
        elif downs >= 3:
            trend_direction = "downtrend"
        else:
            trend_direction = "neutral"
    else:
        trend_direction = "neutral"

    return {
        "regime": "narrow_range" if is_narrow_range else trend_direction,
        "trend_direction": trend_direction,
        "recent_high": current_high,
        "recent_low": current_low,
        "context_strength": "strong" if not is_narrow_range else "weak"
    }


def screen_signal_bars(
    bars: List[Dict],
    direction: str = "bullish",
    min_body_ratio: float = 0.5
) -> List[Dict]:
    """
    扫描所有K线，找出符合条件的信号K线

    Args:
        bars: K线数据（必须含 time 字段，按时间升序排列）
        direction: "bullish" | "bearish"
        min_body_ratio: 最小实体比率

    Returns:
        信号K线列表，每项包含 K线数据 + 信号分析
    """
    signals = []

    for i, bar in enumerate(bars):
        is_formed, signal_bar = is_signal_bar_formed(
            bar=bar,
            prev_bars=bars[max(0, i-5):i],
            direction=direction,
            min_body_ratio=min_body_ratio
        )

        if is_formed:
            # 分析背景环境
            context = analyze_context(bars, i)

            entry = find_entry_after_signal(
                bars=bars,
                signal_bar_index=i,
                direction=direction
            )

            signals.append({
                "bar": bar,
                "signal_bar": signal_bar,
                "context": context,
                "entry": entry,
                "index": i
            })

    return signals


# ============================================================
# 测试代码（用模拟数据）
# ============================================================
if __name__ == "__main__":
    # 模拟K线数据（包含 time 字段，禁止用 data[-1] 取最新价）
    import time

    now = int(time.time())

    # 模拟：下跌后反弹，形成信号K线
    mock_bars = [
        {"time": now - 600 + i * 60, "open": 100, "high": 102, "low": 99, "close": 100 + (i % 3) - 1}
        for i in range(30)
    ]

    # 最后几根模拟趋势K线（做多信号）
    mock_bars.extend([
        {"time": now - 600 + 30 * 60, "open": 100, "high": 105, "low": 99, "close": 104},  # 趋势K线
        {"time": now - 600 + 31 * 60, "open": 104, "high": 106, "low": 103, "close": 105},  # 突破K线
    ])

    print("=== P07 信号K线测试 ===")
    print(f"K线数量: {len(mock_bars)}")

    # 测试趋势K线判断
    trend = is_trend_bar(mock_bars[-2])
    print(f"倒数第2根是否为趋势K线: {trend}")

    # 测试信号K线判断
    is_signal, sb = is_signal_bar_formed(
        bar=mock_bars[-2],
        prev_bars=mock_bars[-5:-2],
        direction="bullish"
    )
    print(f"信号K线是否形成: {is_signal}")
    print(f"信号强度: {sb.signal_strength}")

    # 测试入场点
    entry = find_entry_after_signal(mock_bars, len(mock_bars) - 2, "bullish")
    print(f"入场点: {entry}")

    # 扫描所有信号
    signals = screen_signal_bars(mock_bars, "bullish")
    print(f"找到信号K线数量: {len(signals)}")
