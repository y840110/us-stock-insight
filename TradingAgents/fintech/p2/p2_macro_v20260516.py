"""
P2 策略B：宏观择时 + 均值回归引擎（Macro + Mean Reversion）
──────────────────────────────────────────────────────────────────
核心理念：宏观周期驱动资产配置，RSI/VIX极端值提供逆向入场机会
组成：
  1. Macro Regime（宏观择时）
     - Fed政策方向（通过FCI/收益率曲线/流动性代理）
     - 信用利差（HY Spread）作为经济健康度温度计
     - 美元走势作为风险偏好指标
     - 通胀预期（通过HY利差 + 实际利率代理）

  2. Mean Reversion（均值回归）
     - RSI超卖 → 买入机会（<30）
     - RSI超买 → 卖出机会（>75）
     - VIX极端高 → 恐慌见顶，逆向买入
     - BB%极端低（<0.1）→ 超卖买入机会
     - BB%极端高（>0.95）→ 超买卖出机会

典型特征：
  - 宏观政策周期拐点
  - 利率/利差极端值
  - 恐慌情绪极致化
  - 与策略A形成对冲/补充
"""
from __future__ import annotations
from typing import Dict, Any, Tuple, List


# ═══════════════════════════════════════════════════════════════
# 宏观 Regime
# ═══════════════════════════════════════════════════════════════

def compute_macro_regime(v: Dict[str, Any]) -> Tuple[str, int]:
    """
    宏观 Regime
    5级: RECOVERY / EXPANSION / OVERHEAT / CURDLE / STRESS
         映射到 BULL_TREND / NEUTRAL / RISK_OFF
    """
    score = 0
    fci = v.get("FCI", 0) or 0
    hy = v.get("HY_SPREAD", 4.0) or 4.0
    dxy = v.get("DXY", 100) or 100
    liq = v.get("LIQUIDITY_SCORE", 0) or 0
    us10y = v.get("US10Y", 4.0) or 4.0
    vix = v.get("VIX", 18) or 18

    # FCI 紧缩/宽松（核心）
    if fci < -0.2:
        score += 2   # 宽松环境 → Recovery/Expansion
    elif fci > 0.2:
        score -= 2   # 紧缩 → Overheat/Curdle

    # 信用利差（经济健康度）
    if hy < 3.5:
        score += 2   # 极低利差 → 经济热，过热风险
    elif hy < 4.2:
        score += 1   # 健康扩张
    elif hy > 6.0:
        score -= 2   # 高利差 → 信用风险/经济收缩
    elif hy > 5.0:
        score -= 1   # 利差偏高

    # 流动性
    if liq > 0.5:
        score += 1   # 流动性充裕
    elif liq < -0.5:
        score -= 1   # 流动性紧张

    # VIX（市场恐慌度）
    if vix < 14:
        score += 1   # 极度乐观 → 过热信号
    elif vix > 28:
        score -= 2   # 恐慌 → 应力状态
    elif vix > 22:
        score -= 1

    # 美元（风险偏好代理）
    # 弱美元（<95）→ 风险偏好，成长股有利
    # 强美元（>105）→ 风险规避
    if dxy < 95:
        score += 1
    elif dxy > 105:
        score -= 1

    # 利率环境
    # 低利率（<3.5%）→ 金融条件宽松，股债双牛
    # 高利率（>5%）→ 金融条件紧缩
    if us10y < 3.5:
        score += 1
    elif us10y > 5.0:
        score -= 1

    # ── 分类 ────────────────────────────────────────────────
    if score >= 4:
        macro = "EXPANSION"      # 经济增长，适度紧缩 = 股市有利
    elif score >= 1:
        macro = "RECOVERY"       # 宽松政策，成长股领涨
    elif score >= -1:
        macro = "NEUTRAL"        # 观望
    elif score >= -3:
        macro = "CURDLE"         # 紧缩后期，关注防御
    else:
        macro = "STRESS"         # 危机/高波动，降低仓位

    return macro, score


# ═══════════════════════════════════════════════════════════════
# 均值回归 Timing
# ═══════════════════════════════════════════════════════════════

def compute_mean_reversion(v: Dict[str, Any]) -> Tuple[str, int, List[str]]:
    """
    均值回归信号
    返回: (signal, score, [detail_tags])
    signal: OVERBOUGHT / OVERSOLD / NEUTRAL_REVERSION
    """
    score = 0
    tags: List[str] = []
    rsi = v.get("SPY_RSI14", 50) or 50
    vix_val = v.get("VIX", 18) or 18
    bb_pct = v.get("BB_PERCENT", 0.5) or 0.5
    realized_vol = v.get("REALIZED_VOL", 15) or 15
    realized_vol_high = realized_vol > 20  # >20%年化波动

    # ── RSI ────────────────────────────────────────────────
    if rsi < 25:
        score += 3
        tags.append(f"RSI极度超卖({rsi:.0f})")
    elif rsi < 35:
        score += 2
        tags.append(f"RSI超卖({rsi:.0f})")
    elif rsi > 80:
        score -= 3
        tags.append(f"RSI极度超买({rsi:.0f})")
    elif rsi > 72:
        score -= 2
        tags.append(f"RSI超买({rsi:.0f})")

    # ── VIX ───────────────────────────────────────────────
    if vix_val > 30:
        score += 2
        tags.append(f"VIX恐慌({vix_val:.0f})→逆向买入机会")
    elif vix_val > 25:
        score += 1
        tags.append(f"VIX偏高({vix_val:.0f})")
    elif vix_val < 12:
        score -= 1
        tags.append("VIX极度亢奋(<12)→乐极生悲")

    # ── BB% ────────────────────────────────────────────────
    if bb_pct < 0.1:
        score += 2
        tags.append(f"BB%极度超卖({bb_pct:.2f})")
    elif bb_pct < 0.2:
        score += 1
        tags.append(f"BB%超卖({bb_pct:.2f})")
    elif bb_pct > 0.95:
        score -= 2
        tags.append(f"BB%极度超买({bb_pct:.2f})")

    # ── 波动率环境 ──────────────────────────────────────────
    if realized_vol_high:
        tags.append(f"高波动环境({realized_vol:.0f}%)")

    # ── 分类 ────────────────────────────────────────────────
    if score >= 3:
        signal = "OVERSOLD"          # 逆向买入机会
    elif score <= -3:
        signal = "OVERBOUGHT"        # 逆向卖出
    else:
        signal = "NEUTRAL_REVERSION"

    return signal, score, tags


# ═══════════════════════════════════════════════════════════════
# 宏观 + 均值回归 → 综合 Timing
# ═══════════════════════════════════════════════════════════════

def compute_timing(v: Dict[str, Any]) -> Tuple[str, int]:
    """
    综合入场时机（宏观 + 均值回归）
    """
    mr_signal, mr_score, _ = compute_mean_reversion(v)

    # 宏观波动率调整
    vix_val = v.get("VIX", 18) or 18
    base_score = 0

    # VIX对时机的影响
    if vix_val > 30:
        base_score += 1   # 恐慌见顶，反而是逆向买入时机
    elif vix_val > 25:
        pass              # 中性，不加分
    elif vix_val < 12:
        base_score -= 1   # 极度亢奋，乐极生悲

    # BB收缩（行情蓄势）
    bb_bw = v.get("BB_BANDWIDTH", 0.08) or 0.08
    if bb_bw < 0.05:
        base_score -= 1   # 压缩后面临突破，方向未明

    # 综合评分
    total = base_score + mr_score

    # 当宏观是STRESS/CURDLE时，即使VIX高也不逆向做多
    macro, _ = compute_macro_regime(v)
    if macro in ("STRESS", "CURDLE") and mr_signal == "OVERSOLD":
        # 宏观恶劣时不轻易逆向抄底
        total -= 1

    if total >= 2:
        return "GOOD_ENTRY", total
    elif total <= -2:
        return "AVOID", total
    else:
        return "NEUTRAL_TIMING", total


# ═══════════════════════════════════════════════════════════════
# Risk
# ═══════════════════════════════════════════════════════════════

def compute_risk(v: Dict[str, Any]) -> int:
    """宏观风险评分"""
    score = 0
    macro, _ = compute_macro_regime(v)
    mr_signal, mr_score, _ = compute_mean_reversion(v)

    # 宏观风险
    if macro == "STRESS":
        score += 4
    elif macro == "CURDLE":
        score += 2
    elif macro == "EXPANSION":
        score += 1   # 过热风险

    # 均值回归极端风险
    if mr_signal == "OVERBOUGHT" and mr_score <= -3:
        score += 2
    if mr_signal == "OVERSOLD" and v.get("VIX", 18) > 30:
        score += 1   # 恐慌底部的快速止损风险

    # 信用风险
    hy = v.get("HY_SPREAD", 4.0) or 4.0
    if hy > 6.0:
        score += 3
    elif hy > 5.0:
        score += 1

    # 流动性
    liq = v.get("LIQUIDITY_SCORE", 0) or 0
    if liq < -1.0:
        score += 2
    elif liq < -0.5:
        score += 1

    return score


# ═══════════════════════════════════════════════════════════════
# 目标仓位
# ═══════════════════════════════════════════════════════════════

def compute_exposure(regime: str, timing: str, risk_score: int,
                    mr_signal: str = None, mr_score: int = 0) -> float:
    """
    宏观策略仓位计算
    与动量策略不同：宏观策略更注重风险对冲
    """
    # 宏观仓位基础
    if regime in ("RECOVERY", "EXPANSION"):
        base = 0.75
    elif regime == "NEUTRAL":
        base = 0.40
    else:  # CURDLE, STRESS
        base = 0.15

    # 时机调整
    if timing == "GOOD_ENTRY":
        base = min(base * 1.2, 1.0)
    elif timing == "AVOID":
        base *= 0.25

    # 均值回归逆向信号加成
    if mr_signal == "OVERSOLD" and mr_score >= 3:
        base = min(base * 1.1, 1.0)  # 逆向机会小幅加仓

    # 风险调整
    exposure = base * max(0.15, 1 - risk_score * 0.12)
    return round(exposure * 100, 1)  # 百分比


# ═══════════════════════════════════════════════════════════════
# 策略入口
# ═══════════════════════════════════════════════════════════════

def analyze_macro(trade_date: str, v: Dict[str, Any]) -> Dict[str, Any]:
    """
    策略B完整分析
    """
    macro, macro_score = compute_macro_regime(v)
    mr_signal, mr_score, mr_tags = compute_mean_reversion(v)
    timing, timing_score = compute_timing(v)
    risk_score = compute_risk(v)
    exposure = compute_exposure(macro, timing, risk_score, mr_signal, mr_score)

    # 策略B的regime → 标准regime映射
    regime_map = {
        "RECOVERY": "BULL_TREND",
        "EXPANSION": "BULL_TREND",
        "NEUTRAL": "NEUTRAL",
        "CURDLE": "RISK_OFF",
        "STRESS": "RISK_OFF",
    }
    standard_regime = regime_map.get(macro, "NEUTRAL")

    # 信号标签
    signal_tags = [
        f"宏观{_macro_label(macro)}(score={macro_score:+d})",
        f"均值回归: {mr_signal}(score={mr_score:+d})",
    ]
    signal_tags.extend(mr_tags)

    return {
        "strategy":           "MACRO",
        "trade_date":         trade_date,
        "market_regime":      macro,          # 原始宏观regime
        "standard_regime":    standard_regime, # 映射到标准regime
        "regime_score":       macro_score,
        "timing_state":       timing,
        "timing_score":       timing_score,
        "risk_score":         risk_score,
        "target_exposure":    exposure,
        "interpretation":     _interpret(macro, macro_score, mr_signal, mr_score,
                                          timing, timing_score, risk_score, mr_tags, v),
        "signals":            signal_tags,
        "confidence":         _confidence(macro, macro_score, mr_signal, mr_score),
        # 细节
        "mean_reversion_signal": mr_signal,
        "mean_reversion_score":  mr_score,
    }


def _macro_label(macro: str) -> str:
    labels = {
        "RECOVERY": "复苏",
        "EXPANSION": "扩张",
        "NEUTRAL": "中性",
        "CURDLE": "紧缩",
        "STRESS": "压力",
    }
    return labels.get(macro, macro)


def _confidence(macro: str, macro_score: int,
                mr_signal: str, mr_score: int) -> float:
    mag = min(abs(macro_score) / 6.0, 1.0)
    mr_mag = min(abs(mr_score) / 4.0, 1.0)
    if macro in ("STRESS", "RECOVERY") or mr_signal in ("OVERBOUGHT", "OVERSOLD"):
        return round(min(0.5 + mag * 0.35 + mr_mag * 0.25, 0.90), 2)
    return round(0.30 + mag * 0.4 + mr_mag * 0.3, 2)


def _interpret(macro: str, macro_score: int,
               mr_signal: str, mr_score: int,
               timing: str, timing_score: int,
               risk_score: int, mr_tags: List[str], v: Dict[str, Any]) -> str:
    lines = []

    # 宏观状态描述
    if macro == "RECOVERY":
        lines.append("宏观复苏：FCI宽松+流动性好+弱美元→成长股/风险资产有利")
    elif macro == "EXPANSION":
        lines.append("宏观扩张：经济活跃+低VIX→顺趋势持仓为主")
    elif macro == "NEUTRAL":
        lines.append("宏观中性：等待方向，灵活切换")
    elif macro == "CURDLE":
        lines.append("宏观紧缩后期：流动性收紧+高利率→防御+降低仓位")
    elif macro == "STRESS":
        lines.append("宏观压力/危机：规避风险，保留现金")

    # 均值回归
    if mr_signal == "OVERSOLD" and mr_score >= 2:
        lines.append(f"均值回归超卖机会：{'/'.join(mr_tags[:2])}")
    elif mr_signal == "OVERBOUGHT" and mr_score >= 2:
        lines.append(f"均值回归超买警示：{'/'.join(mr_tags[:2])}")

    # 风险提示
    if risk_score >= 5:
        lines.append(f"⚠️ 宏观风险偏高（{risk_score}/10）")

    hy = v.get("HY_SPREAD")
    if hy and hy > 6.0:
        lines.append(f"⚠️ HY利差极高({hy}%)→经济预警信号")

    dxy = v.get("DXY")
    if dxy and dxy > 108:
        lines.append(f"⚠️ 美元超强({dxy})→新兴市场/全球风险资产压力")

    return "；".join(lines)
