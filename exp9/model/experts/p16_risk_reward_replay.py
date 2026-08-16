"""
P16: 两倍盈亏比？九倍！— 3月19号ES股指期货详细复盘
================================================================
Brooks价格行为学 - 实战复盘专题

核心主题：高盈亏比交易的数学期望
- 40%胜率 + 2倍盈亏比 → 正期望
- 严格风险管理：每笔不超账户1%
- 目标：不是每笔都赚，而是数学期望为正
- 复盘案例：ES 3月19日缺口交易日

数据源：Whisper采样（P16_whisper/p16_sample.mp3, p16_ts600.mp3）
      Vision帧分析（P16_whisper/p16_vision_analysis.txt，2/272组）
视频：16-14两倍盈亏比？九倍！3月19号ES股指期货详细复盘.mp4（35.9分钟）
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class TradingAccount:
    """
    交易账户模型
    
    Brooks案例参数（假设"小明"账户）：
    - 初始资金：$50,000
    - 单笔风险：$500（1%）
    - 每周交易次数：10笔
    """
    balance: float = 50000.0
    risk_per_trade_pct: float = 0.01  # 1%
    risk_per_trade: float = 500.0  # $500
    trades_per_week: int = 10
    
    def max_loss_per_trade(self) -> float:
        return self.balance * self.risk_per_trade_pct
    
    def win_rate_needed(self, target_rr: float) -> float:
        """
        计算特定盈亏比需要的最低胜率（盈亏平衡点）
        
        公式: WinRate = 1 / (R + 1)
        """
        return 1.0 / (target_rr + 1.0)


@dataclass
class TradeResult:
    """单笔交易结果"""
    entry: float
    stop: float
    target: float
    won: bool
    risk_amount: float  # 实际亏损或盈利的金额
    
    def reward(self) -> float:
        return self.target - self.entry
    
    def risk_reward(self) -> float:
        r = self.reward()
        return r / self.risk_amount if self.risk_amount > 0 else 0


def simulate_trading_session(
    account: TradingAccount,
    win_rate: float,
    risk_reward: float,
    num_trades: int,
    target_2r_plus: bool = False  # 是否有部分交易达到更高盈亏比
) -> dict:
    """
    模拟交易会话
    
    Brooks核心观点：
    - 40%胜率 + 2倍盈亏比 = 正期望
    - "不是每笔都要两倍，要看市场给不给你"
    - "九倍盈亏比"说明市场有时会给超大机会
    """
    import random
    random.seed(42)
    
    results = []
    wins = 0
    losses = 0
    total_pnl = 0.0
    
    for i in range(num_trades):
        won = random.random() < win_rate
        
        if won:
            wins += 1
            # 有些交易可以达到更高盈亏比
            if target_2r_plus and random.random() < 0.3:
                actual_rr = risk_reward + random.uniform(1, 4)  # 九倍等情况
            else:
                actual_rr = risk_reward
            pnl = account.risk_per_trade * actual_rr
        else:
            losses += 1
            pnl = -account.risk_per_trade
        
        total_pnl += pnl
        results.append({
            'trade': i + 1,
            'won': won,
            'rr': actual_rr if won else risk_reward,
            'pnl': pnl
        })
    
    actual_win_rate = wins / num_trades
    avg_win = sum(r['pnl'] for r in results if r['won']) / wins if wins > 0 else 0
    avg_loss = abs(sum(r['pnl'] for r in results if not r['won']) / losses) if losses > 0 else 0
    
    return {
        'total_trades': num_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': actual_win_rate,
        'total_pnl': total_pnl,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        ' expectancy_per_trade': total_pnl / num_trades,
        ' expectancy_pct': (total_pnl / account.balance) * 100,
        'results': results
    }


def calculate_math_expectation(win_rate: float, risk_reward: float) -> dict:
    """
    计算交易的数学期望
    
    公式: E = WinRate * R - (1 - WinRate) * 1
         其中 R = avg_win / avg_loss
    
    Brooks关键阈值：
    - 40%胜率 + 2R = 正期望 (E = 0.4*2 - 0.6*1 = 0.2 > 0)
    - 50%胜率 + 1R = 盈亏平衡 (E = 0.5*1 - 0.5*1 = 0)
    """
    e = win_rate * risk_reward - (1 - win_rate)
    
    return {
        'win_rate': win_rate,
        'risk_reward': risk_reward,
        'expectation': e,
        'is_profitable': e > 0,
        'breakeven_winrate': 1.0 / (risk_reward + 1.0),
        'winrate_40_2r': 0.4 * 2 - 0.6 * 1,  # = 0.2
        'comment': '正期望' if e > 0 else ('盈亏平衡' if e == 0 else '负期望')
    }


def review_es_gap_trade(
    entry_price: float,
    stop_price: float,
    target_price: float,
    actual_exit_price: float,
    position_size: float
) -> dict:
    """
    ES 3月19日缺口交易日复盘分析
    
    Brooks案例背景：
    - 3月19日 ES 开盘出现跳空缺口
    - 交易者寻找高盈亏比入场机会
    - 严格止损（1%账户）
    """
    risk = entry_price - stop_price
    reward = target_price - entry_price
    rr = reward / risk if risk > 0 else 0
    
    # 实际结果
    if actual_exit_price >= target_price:
        actual_rr = (target_price - entry_price) / risk
        won = True
        pnl = risk * actual_rr
    elif actual_exit_price <= stop_price:
        won = False
        actual_rr = 0
        pnl = -risk
    else:
        # 提前离场
        partial_rr = (actual_exit_price - entry_price) / risk
        won = None
        actual_rr = partial_rr
        pnl = risk * partial_rr
    
    return {
        'entry': entry_price,
        'stop': stop_price,
        'target': target_price,
        'actual_exit': actual_exit_price,
        'risk': risk,
        'reward': reward,
        'planned_rr': rr,
        'actual_rr': actual_rr,
        'won': won,
        'pnl': pnl,
        'pnl_pct': (pnl / entry_price) * 100
    }


# =============================================================================
# Brooks Risk/Reward 核心原则
# =============================================================================

PRINCIPLES = """
=== Brooks 盈亏比与数学期望核心原则 ===

1. 盈亏比（Risk/Reward）基础
   - 盈亏比 = 潜在盈利 / 潜在亏损
   - Brooks不追求"每笔都赚钱"，追求正期望

2. 关键盈亏比阈值
   - 1R = 1倍风险（盈亏平衡需要50%胜率）
   - 2R = 2倍风险（40%胜率即可正期望）
   - 3R = 3倍风险（33%胜率即可正期望）

3. 40%胜率 + 2倍盈亏比 = 正期望
   - 期望值 E = 0.4 × 2 - 0.6 × 1 = 0.2 > 0
   - 这就是"两倍盈亏比？九倍！"的含义
   - 市场有时会给九倍甚至更高的机会

4. 风险管理是基石
   - 每笔交易不超过账户1%
   - "$50,000账户 → $500/笔"
   - 每周10笔交易
   - 连续亏损不会摧毁账户

5. 不是每笔都要两倍
   - Brooks: "不是每笔都给你两倍，要看市场给不给你"
   - 当市场给九倍机会时敢于持仓
   - 当市场只给1.5倍时也要接受

6. 复盘的重要性
   - 通过复盘训练识别高盈亏比机会
   - 复盘帮助理解缺口日的行为模式
   - "如何通过复盘训练提高实盘能力"

7. 交易的数学本质
   - 交易是概率游戏，不是预测游戏
   - 期望值为正 → 长期必然盈利
   - 期望值为负 → 长期必然亏损
"""

if __name__ == "__main__":
    print("=== Brooks P16: 盈亏比与数学期望 ===\n")
    
    # 数学期望演示
    print("--- 数学期望计算 ---")
    cases = [
        (0.40, 2.0, "40%胜率 + 2R"),
        (0.50, 1.0, "50%胜率 + 1R"),
        (0.33, 3.0, "33%胜率 + 3R"),
        (0.30, 3.0, "30%胜率 + 3R"),
    ]
    for wr, rr, desc in cases:
        e = calculate_math_expectation(wr, rr)
        print(f"  {desc}: E = {e['expectation']:.3f} ({e['comment']})")
    
    print("\n--- 盈亏平衡胜率 ---")
    for rr in [1, 2, 3, 5, 9]:
        br = 1.0 / (rr + 1)
        print(f"  {rr}R → 需要 {br:.1%} 胜率")
    
    print("\n--- 交易模拟 ($50k账户, 1%风险, 10笔/周) ---")
    account = TradingAccount()
    sim = simulate_trading_session(account, win_rate=0.4, risk_reward=2.0, num_trades=10)
    print(f"  总交易: {sim['total_trades']}")
    print(f"  胜率: {sim['win_rate']:.0%}")
    print(f"  总盈亏: ${sim['total_pnl']:.2f}")
    print(f"  单笔期望: ${sim[' expectancy_per_trade']:.2f}")
    print(f"  账户收益率: {sim[' expectancy_pct']:.2f}%")
    
    print("\n" + PRINCIPLES)
"""
