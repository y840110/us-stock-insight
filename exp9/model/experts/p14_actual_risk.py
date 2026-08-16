"""
P14: Actual Risk & 实际盈亏比
=====================================
Brooks价格行为学 - 止盈目标位第(2)部

核心主题：Actual Risk（实际风险）
- 与 Initial Stop（初始止损）的区别
- 如何用 Actual Risk 距离设定止盈目标（1R、2R）
- 为什么"实际风险太小"反而不是最好的交易
- Money Stop（金额止损）vs Price Action Stop（结构止损）

数据源：Whisper转写（P14_whisper/p14_sample.srt + p14_ts180.txt/p14_ts360.txt/p14_ts540.txt）
      Vision帧分析（P14_whisper/p14_vision_analysis.txt）
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class StopType(Enum):
    INITIAL_STOP = "initial_stop"       # 初始止损（入场前预设）
    ACTUAL_RISK = "actual_risk"        # 实际风险（入场后实际面临的最大风险）
    MONEY_STOP = "money_stop"          # 金额止损（固定百分比/金额）
    STRUCTURAL_STOP = "structural_stop" # 结构止损（基于图表结构）


@dataclass
class EntrySetup:
    """
    交易入场设置
    
    Attributes:
        entry_price: 入场价格
        initial_stop: 初始止损价格
        actual_risk: 实际风险距离（入场到止损的真实距离）
        actual_risk_pct: 实际风险百分比
    """
    entry_price: float
    initial_stop: float
    actual_risk: float = 0.0
    actual_risk_pct: float = 0.0
    
    def __post_init__(self):
        if self.actual_risk == 0.0 and self.entry_price > 0:
            self.actual_risk = self.entry_price - self.initial_stop
        if self.actual_risk_pct == 0.0 and self.entry_price > 0:
            self.actual_risk_pct = (self.actual_risk / self.entry_price) * 100
    
    def target_1r(self) -> float:
        """1R 目标 = 入场 + 实际风险距离"""
        return self.entry_price + self.actual_risk
    
    def target_2r(self) -> float:
        """2R 目标 = 入场 + 2倍实际风险距离"""
        return self.entry_price + (self.actual_risk * 2)
    
    def risk_reward_ratio(self, target: float) -> float:
        """计算风险回报比"""
        potential_reward = target - self.entry_price
        return potential_reward / self.actual_risk if self.actual_risk > 0 else 0


def calc_actual_risk(entry_price: float, pullback_low: float) -> dict:
    """
    计算实际风险
    
    Args:
        entry_price: 入场价格
        pullback_low: 回调最低点（入场后价格反向运行的最远处）
    
    Returns:
        dict包含：actual_risk距离、1R目标、2R目标、风险百分比
    """
    actual_risk = entry_price - pullback_low
    actual_risk_pct = (actual_risk / entry_price) * 100 if entry_price > 0 else 0
    
    return {
        "actual_risk": actual_risk,
        "actual_risk_pct": actual_risk_pct,
        "target_1r": entry_price + actual_risk,
        "target_2r": entry_price + (actual_risk * 2),
        "rr_1r": 1.0,      # 1R的风险回报比永远是1
        "rr_2r": 2.0,      # 2R的风险回报比永远是2
    }


def assess_stop_quality(setup: EntrySetup) -> dict:
    """
    评估止损质量
    
    Returns:
        dict包含：评估结果、建议、优化方向
    """
    results = {
        "actual_risk_pct": setup.actual_risk_pct,
        "assessment": "",
        "is_too_small": False,
        "suggestion": "",
    }
    
    # Brooks原则：实际风险太小 → 盈利潜力也小
    if setup.actual_risk_pct < 1.0:
        results["assessment"] = "实际风险极小（<1%）"
        results["is_too_small"] = True
        results["suggestion"] = (
            "实际风险太小意味着潜在盈利空间也受限。"
            "Brooks: '小实际风险无用（Small Actual Risk is useless）'。"
            "这种设置虽然看起来'安全'，但数学期望不是最优。"
        )
    elif setup.actual_risk_pct < 3.0:
        results["assessment"] = "实际风险较小（1-3%）"
        results["is_too_small"] = False
        results["suggestion"] = (
            "实际风险较小，适合高胜率策略。"
            "1R止盈目标可达，2R需要强势趋势。"
        )
    elif setup.actual_risk_pct < 8.0:
        results["assessment"] = "实际风险适中（3-8%）"
        results["is_too_small"] = False
        results["suggestion"] = "平衡型设置，兼顾安全垫和盈利空间。"
    else:
        results["assessment"] = "实际风险较大（>8%）"
        results["is_too_small"] = False
        results["suggestion"] = (
            "止损宽松，单笔风险大。"
            "需要更高的盈亏比来维持正期望。"
        )
    
    return results


def math_expectation(win_rate: float, risk_reward: float) -> float:
    """
    计算交易数学期望
    
    公式: E = WinRate * R - (1 - WinRate) * 1
         其中 R = avg_win / avg_loss (风险回报比)
    
    Args:
        win_rate: 胜率 (0.0 - 1.0)
        risk_reward: 风险回报比 (R)
    
    Returns:
        正期望 > 0，负期望 < 0
    
    Brooks关键观点:
    - 60%+胜率 + 1R止盈 = 正期望
    - 40%+胜率 + 2R止盈 = 正期望
    - "交易赚钱靠数学，不是靠准确预测"
    """
    return win_rate * risk_reward - (1 - win_rate)


def required_winrate_for_rr(risk_reward: float) -> float:
    """
    计算特定R值需要的最低胜率（盈亏平衡点）
    
    公式推导: WinRate * R = (1 - WinRate) * 1
              WinRate * R + WinRate = 1
              WinRate * (R + 1) = 1
              WinRate = 1 / (R + 1)
    """
    return 1.0 / (risk_reward + 1.0)


def analyze_trade_example(
    entry: float,
    initial_stop: float,
    pullback_low: float,
    win_rate: float,
    target_1r_only: bool = False
) -> dict:
    """
    综合分析交易示例（Brooks AMZN日线案例）
    
    Brooks案例背景（AMZN日线，2023年）：
    - 入场价格：100（突破买入）
    - 初始止损选择：87（宽松）或 80（更宽松）
    - 实际风险：取决于入场后回调深度
    
    Returns:
        完整交易分析字典
    """
    result = {
        "entry": entry,
        "initial_stop": initial_stop,
        "pullback_low": pullback_low,
        "win_rate": win_rate,
    }
    
    # 核心计算
    ar = calc_actual_risk(entry, pullback_low)
    setup = EntrySetup(entry, initial_stop)
    
    result.update(ar)
    result["assessment"] = assess_stop_quality(setup)
    
    # 数学期望分析
    # Brooks: "60%以上胜率 + 1R" 或 "40%以上胜率 + 2R"
    e_1r = math_expectation(win_rate, 1.0)
    e_2r = math_expectation(win_rate, 2.0)
    
    result["expectation"] = {
        "1r_expectation": e_1r,
        "2r_expectation": e_2r,
        "breakeven_1r": required_winrate_for_rr(1.0),  # 50%
        "breakeven_2r": required_winrate_for_rr(2.0),  # 33%
        "profitable_1r": win_rate > required_winrate_for_rr(1.0),
        "profitable_2r": win_rate > required_winrate_for_rr(2.0),
    }
    
    # Brooks核心语录
    result["brooks_quote"] = (
        "交易赚钱的策略背后是数学、是概率。"
        "用实际风险距离作为止盈目标位在数学期望上是合理的。"
        "60%以上胜率配1R，或者40%以上胜率配2R。"
    )
    
    return result


# =============================================================================
# Brooks价格行为学 Actual Risk 核心原则
# =============================================================================

PRINCIPLES = """
=== Brooks Actual Risk 核心原则 ===

1. Actual Risk vs Initial Stop
   - Initial Stop：入场前预设的止损位（基于图表结构）
   - Actual Risk：入场后实际面临的最大风险（通常比Initial Stop小）
   - Brooks："Initial Stop有很多种选择"

2. Actual Risk 测量方法
   - 入场点到回调最低点的距离
   - 这个距离决定了1R止盈目标
   
3. Money Stop（金额止损）
   - 固定金额或百分比止损
   - 不考虑图表结构
   - Brooks举例：10%止损、15%止损

4. 为什么"小实际风险"无用
   - 实际风险太小 → 潜在盈利空间也小
   - 数学期望不优
   - "合理不代表最好"

5. 数学期望是核心
   - 交易赚钱靠数学，不是靠准确预测
   - 60%+胜率 + 1R = 正期望
   - 40%+胜率 + 2R = 正期望

6. 用Actual Risk找目标位
   - 1R = 入场 + 实际风险距离
   - 2R = 入场 + 2倍实际风险距离
   - "在数学期望上是合理的"
"""

if __name__ == "__main__":
    # Brooks AMZN 案例重现
    # 入场100，初始止损87（保守）或80（更保守）
    # 假设实际回调到87，实际风险 = 100 - 87 = 13 (13%)
    
    print("=== Brooks P14: Actual Risk 分析 ===\n")
    
    # 案例1：实际风险13%（回调到87）
    analysis = analyze_trade_example(
        entry=100.0,
        initial_stop=87.0,  # 宽松止损
        pullback_low=87.0,   # 实际回调到87
        win_rate=0.55,      # 假设55%胜率
    )
    
    print(f"入场: ${analysis['entry']}")
    print(f"初始止损: ${analysis['initial_stop']}")
    print(f"实际风险: ${analysis['actual_risk']:.2f} ({analysis['actual_risk_pct']:.1f}%)")
    print(f"1R目标: ${analysis['target_1r']:.2f}")
    print(f"2R目标: ${analysis['target_2r']:.2f}")
    print(f"\n止损评估: {analysis['assessment']['assessment']}")
    print(f"建议: {analysis['assessment']['suggestion']}")
    print(f"\n胜率要求:")
    print(f"  1R盈亏平衡: {analysis['expectation']['breakeven_1r']:.0%}")
    print(f"  2R盈亏平衡: {analysis['expectation']['breakeven_2r']:.0%}")
    print(f"\n数学期望 (55%胜率):")
    print(f"  1R: {analysis['expectation']['1r_expectation']:.3f} {'✅' if analysis['expectation']['profitable_1r'] else '❌'}")
    print(f"  2R: {analysis['expectation']['2r_expectation']:.3f} {'✅' if analysis['expectation']['profitable_2r'] else '❌'}")
    print(f"\nBrooks: {analysis['brooks_quote']}")
    print("\n" + PRINCIPLES)
