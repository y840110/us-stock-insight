"""
P15: Gap 缺口 — 中高级课程 (1)
=====================================
Brooks价格行为学 - 价格行为基础

核心主题：缺口（Gaps）的定义、分类与交易应用
- Brooks对缺口的广义定义：价格之间不重叠的部分
- 三种主要缺口类型：突破型/测量型/竭尽型
- Body Gap（实体缺口）vs High/Low Gap（高低缺口）
- EMA Gap / MAG（均线缺口）= 极强趋势信号
- 缺口作为目标位和支撑/阻力

数据源：Whisper采样验证（P15_whisper/p15_sample.mp3, p15_ts600.mp3）
      Vision帧分析（P15_whisper/p15_vision_analysis.txt，8/23组）
视频：15-13中高级课程-缺口(1).mp4（32.5分钟，1954帧→23场景组）
课程大纲：11A什么是缺口 / 11B均线缺口棒/衰竭缺口 / 11C微型缺口/开盘缺口棒/11D阶梯
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List


class GapType(Enum):
    """Brooks缺口分类"""
    BREAKOUT = "breakout"           # 突破型缺口：趋势开始时
    MEASURING = "measuring"         # 测量型缺口：趋势中继
    EXHAUSTION = "exhaustion"        # 竭尽型缺口：趋势末端
    BODY = "body"                   # 实体缺口：收盘价之间的缺口
    HIGH_LOW = "high_low"           # 高低缺口：最高/最低价之间的缺口
    EMA = "ema_gap"                # EMA缺口/MAG：价格与EMA之间的空白
    MICRO = "micro"                # 微型缺口


class TrendStrength(Enum):
    """趋势强度评估"""
    VERY_STRONG = "very_strong"   # MAG连续50+根K线未触及EMA
    STRONG = "strong"             # 趋势明确
    MODERATE = "moderate"         # 震荡
    WEAK = "weak"                # 宽通道/弱趋势


@dataclass
class Gap:
    """
    缺口数据
    
    Attributes:
        gap_type: 缺口类型
        start_bar: 起始K线编号
        end_bar: 结束K线编号
        size: 缺口大小（价格单位）
        significance: 重要程度（high/medium/low）
        direction: 方向（up/down）
    """
    gap_type: GapType
    start_bar: int
    end_bar: int
    size: float
    significance: str = "medium"
    direction: str = "up"  # up or down


@dataclass
class MAGContext:
    """
    EMA缺口（MAG）上下文
    
    Brooks核心观点：
    - 连续50+根K线未触及EMA20 = 极强趋势
    - 这种情况下会在EMA形成大量挂单
    - 第一次触及EMA是高胜率买入机会
    """
    bars_without_touching_ema: int
    ema_slope: str  # "above" or "below"
    trend_strength: TrendStrength
    likely_entry_on_ema_retest: bool


def identify_gap_type(
    gap_size: float,
    position_in_trend: str,  # "early", "middle", "late"
    volume: float,
    preceding_trend: str     # "up", "down", "ranging"
) -> GapType:
    """
    根据位置、大小、成交量识别缺口类型
    
    Brooks缺口类型判断逻辑：
    - 突破型缺口：出现在趋势初期，伴随大成交量
    - 测量型缺口：出现在趋势中期，表示趋势延续
    - 竭尽型缺口：出现在趋势末端，常有反转信号
    """
    if position_in_trend == "early" and volume > 1.5:
        return GapType.BREAKOUT
    elif position_in_trend == "middle":
        return GapType.MEASURING
    elif position_in_trend == "late":
        return GapType.EXHAUSTION
    else:
        return GapType.MEASURING


def assess_trend_strength_from_mag(bars_count: int) -> dict:
    """
    根据MAG（均线缺口）评估趋势强度
    
    Brooks观察：
    - 连续50+根K线未触及EMA = 非常强的趋势
    - 这种环境中会在EMA形成大量止损单和限价单
    - 趋势交易者会在EMA反弹时买入
    """
    result = {
        "bars_without_touching": bars_count,
        "strength": "",
        "interpretation": "",
        "entry_quality": "",
    }
    
    if bars_count >= 50:
        result["strength"] = "极强 (Very Strong)"
        result["interpretation"] = (
            "连续50+根K线未触及EMA20，表明趋势极为强劲。"
            "Brooks: '会有很多人在EMA挂单买入'。"
            "这种环境下趋势延续概率极高。"
        )
        result["entry_quality"] = "第一次EMA回踩 = 高胜率买入机会"
    elif bars_count >= 20:
        result["strength"] = "强 (Strong)"
        result["interpretation"] = "趋势明确，EMA可作为支撑参考"
        result["entry_quality"] = "EMA回踩 = 顺势买入机会"
    elif bars_count >= 5:
        result["strength"] = "中等 (Moderate)"
        result["interpretation"] = "趋势中有正常回调"
        result["entry_quality"] = "EMA回踩需谨慎评估"
    else:
        result["strength"] = "弱 (Weak)"
        result["interpretation"] = "频繁穿越EMA，趋势不明确"
        result["entry_quality"] = "不建议顺势交易"
    
    return result


def gap_as_target_and_support(
    gap_type: GapType,
    gap_size: float,
    direction: str,
    current_price: float
) -> dict:
    """
    缺口作为目标位和支撑/阻力
    
    Brooks核心观点：
    - 缺口既是目标位，也是潜在的支撑/阻力区域
    - 缺口通常成为价格止步的位置
    - 理解缺口有助于设置止盈
    """
    result = {
        "gap_type": gap_type.value,
        "size": gap_size,
        "direction": direction,
    }
    
    if direction == "up":
        result["resistance_zone"] = current_price + gap_size
        result["support_zone"] = current_price  # 缺口底部成为支撑
    else:
        result["support_zone"] = current_price - gap_size
        result["resistance_zone"] = current_price  # 缺口顶部成为阻力
    
    # 缺口类型决定目标意义
    if gap_type == GapType.MEASURING:
        result["target_significance"] = "高"
        result["reason"] = "测量型缺口通常意味着趋势延续"
    elif gap_type == GapType.EXHAUSTION:
        result["target_significance"] = "反转信号"
        result["reason"] = "竭尽型缺口常预示趋势即将结束"
    elif gap_type == GapType.BREAKOUT:
        result["target_significance"] = "确认趋势"
        result["reason"] = "突破型缺口确认趋势方向"
    
    return result


def analyze_gap_tradeSetup(
    gap_type: GapType,
    ema_position: str,  # "above_ema" or "below_ema"
    mag_context: MAGContext,
    entry_price: float,
    stop_price: float
) -> dict:
    """
    缺口交易设置分析
    
    Returns:
        完整的交易设置评估
    """
    setup = {
        "gap_type": gap_type.value,
        "ema_position": ema_position,
        "entry": entry_price,
        "stop": stop_price,
        "risk": abs(entry_price - stop_price),
    }
    
    # 评估入场质量
    if ema_position == "above_ema" and gap_type in [GapType.BREAKOUT, GapType.MEASURING]:
        setup["quality"] = "高"
        setup["reason"] = "顺势 + 强趋势 + 缺口确认"
    elif ema_position == "below_ema":
        setup["quality"] = "低"
        setup["reason"] = "逆势操作，风险较大"
    else:
        setup["quality"] = "中"
        setup["reason"] = "需等待更多确认"
    
    # Brooks语录
    setup["brooks_quote"] = (
        "缺口意味着强度（Gaps mean strength）。"
        "连续大实体K线少重叠 = 极强趋势。"
        "均线缺口（MAG）是Brooks识别极强趋势的核心工具。"
    )
    
    return setup


# =============================================================================
# Brooks Gap 核心原则
# =============================================================================

PRINCIPLES = """
=== Brooks Gap 核心原则 ===

1. Brooks对缺口的广义定义
   "价格之间不重叠的部分就是缺口"
   - 不仅指传统跳空，还包括实体之间、高低之间的空白

2. 三种主要缺口类型
   - 突破型缺口（Breakout Gap）：趋势开始，力度最强
   - 测量型缺口（Measuring Gap）：趋势中继，1:1目标测量
   - 竭尽型缺口（Exhaustion Gap）：趋势末端，预示反转

3. 缺口既做目标位，也做支撑/阻力
   - 缺口区域常成为价格止步的位置
   - 理解缺口有助于设置止盈

4. EMA Gap / MAG（均线缺口）
   - 连续K线未触及EMA = 极强趋势信号
   - "连续50+根K线没碰到过EMA20 = 非常强的趋势"
   - 这种环境中会在EMA形成大量挂单

5. 缺口意味着强度
   - 有缺口的趋势通常更强
   - 不要在趋势初期就预期反转

6. 宽通道弱趋势
   - 宽通道 = 75%概率被反向突破
   - 重叠多 = 逆势一方能赚钱
"""

if __name__ == "__main__":
    print("=== Brooks P15: Gap 缺口分析 ===\n")
    
    # 示例：EUR/USD 5min 缺口分析
    print("--- 三种缺口类型 ---")
    for gtype in [GapType.BREAKOUT, GapType.MEASURING, GapType.EXHAUSTION]:
        print(f"  {gtype.value}")
    
    print("\n--- MAG趋势强度评估 ---")
    mag = assess_trend_strength_from_mag(52)
    print(f"  连续{mag['bars_without_touching']}根K线未触及EMA")
    print(f"  强度: {mag['strength']}")
    print(f"  解读: {mag['interpretation']}")
    print(f"  入场: {mag['entry_quality']}")
    
    print("\n--- 缺口作为目标位 ---")
    target = gap_as_target_and_support(GapType.MEASURING, 50.0, "up", 1.0850)
    print(f"  缺口类型: {target['gap_type']}")
    print(f"  支撑区域: {target['support_zone']}")
    print(f"  阻力区域: {target['resistance_zone']}")
    
    print("\n" + PRINCIPLES)
"""
