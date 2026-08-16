"""
P2 策略A：动量趋势引擎（Momentum Engine）
──────────────────────────────────────────────────────────────────
核心理念：趋势是你的朋友，跟随趋势直到逆转
判断依据：
  - 价格结构（EMA多头排列）
  - 广度（NYAD上涨家数+趋势）
  - 波动率结构（VIX低位+term structure正常）
  - 期权持仓（CTA净多/GEX正）
  - 量价配合

典型特征：
  - 趋势确认信号强
  - 市场参与度广（>60%股票在均线上方）
  - 机构持仓偏多
"""
from __future__ import annotations
from typing import Dict, Any, Tuple


# ═══════════════════════════════════════════════════════════════
# 内部计算指标（补充到v字典）
# ═══════════════════════════════════════════════════════════════

def _derive_composite(v: Dict[str, Any]) -> None:
    """补充复合指标到v字典（原地修改）"""
    # Breadth Divergence
    spy_new_high = v.get("SPY_NEW_HIGH", False)
    nyad_confirm = v.get("NYAD_CONFIRM")
    v["BREADTH_DIVERGENCE"] = bool(spy_new_high and nyad_confirm is False)

    # MACD收缩率
    macd_hist = v.get("MACD_HISTOGRAM", 0) or 0
    macd_peak = v.get("MACD_HISTOGRAM_PEAK", 1) or 1
    if macd_peak and macd_peak > 0:
        v["MACD_CONTRACTION"] = (macd_peak - macd_hist) / macd_peak
    else:
        v["MACD_CONTRACTION"] = 0

    # ATR压缩率
    atr14 = v.get("ATR14", 1) or 1
    atr_peak = v.get("ATR14_PEAK", 1) or 1
    if atr_peak and atr_peak > 0:
        v["ATR_COMPRESSION"] = (atr_peak - atr14) / atr_peak
    else:
        v["ATR_COMPRESSION"] = 0

    # VIX期限结构
    v["VIX_TERM_STRUCTURE"] = (v.get("VIX3M") or 0) - (v.get("VIX9D") or 0)


# ═══════════════════════════════════════════════════════════════
# Regime 计算
# ═══════════════════════════════════════════════════════════════

def compute_regime(v: Dict[str, Any]) -> Tuple[str, int]:
    """
    动量趋势 Regime
    3级: BULL_TREND(score≥8) / NEUTRAL(score≥4) / RISK_OFF
    """
    score = 0

    # ── 趋势结构 ────────────────────────────────────────────
    if v.get("SPY_CLOSE") and v.get("SPY_EMA20"):
        if v["SPY_CLOSE"] > v["SPY_EMA20"]:
            score += 1
    if v.get("SPY_EMA20") and v.get("SPY_SMA50"):
        if v["SPY_EMA20"] > v["SPY_SMA50"]:
            score += 1
    if v.get("SPY_SMA50") and v.get("SPY_SMA200"):
        if v["SPY_SMA50"] > v["SPY_SMA200"]:
            score += 1
    if (v.get("SPY_EMA20_SLOPE", 0) or 0) > 0:
        score += 1

    # ── 广度 ────────────────────────────────────────────────
    if (v.get("NYAD_SLOPE", 0) or 0) > 0:
        score += 2
    if (v.get("SP500_ABOVE_50MA", 0) or 0) > 0.60:
        score += 1
    if (v.get("NEW_HIGH_LOW_RATIO", 0) or 0) > 1.5:
        score += 1
    if v.get("BREADTH_DIVERGENCE"):
        score -= 3
    if (v.get("IWM_RS_SLOPE", 0) or 0) < 0:
        score -= 1

    # ── 波动率 ──────────────────────────────────────────────
    if (v.get("VIX", 99) or 99) < 20:
        score += 1
    if (v.get("VIX_TERM_STRUCTURE", 0) or 0) > 0:
        score += 1
    else:
        score -= 2
    if (v.get("VVIX", 0) or 0) > 110:
        score -= 2

    # ── 信用+流动性 ─────────────────────────────────────────
    if (v.get("HY_SPREAD", 999) or 999) < 4.2:
        score += 1
    elif (v.get("HY_SPREAD", 0) or 0) >= 4.2:
        score -= 2
    if (v.get("LIQUIDITY_SCORE", 0) or 0) > 0:
        score += 1
    else:
        score -= 1

    # ── 期权持仓 ────────────────────────────────────────────
    if (v.get("GEX", 0) or 0) > 0:
        score += 1
    else:
        score -= 2

    # ── 分类 ────────────────────────────────────────────────
    if score >= 8:
        regime = "BULL_TREND"
    elif score >= 4:
        regime = "NEUTRAL"
    else:
        regime = "RISK_OFF"

    return regime, score


# ═══════════════════════════════════════════════════════════════
# Timing 计算
# ═══════════════════════════════════════════════════════════════

def compute_timing(v: Dict[str, Any]) -> Tuple[str, int]:
    """
    动量趋势入场时机
    GOOD_ENTRY / NEUTRAL_TIMING / OVERHEATED
    """
    score = 0

    rsi = v.get("SPY_RSI14", 50) or 50
    if rsi < 35:
        score += 2
    elif rsi > 75:
        score -= 2

    if (v.get("MACD_HISTOGRAM", 0) or 0) > 0:
        score += 1

    macd_peak = v.get("MACD_HISTOGRAM_PEAK", 1) or 1
    if macd_peak and macd_peak > 0:
        contraction = (macd_peak - (v.get("MACD_HISTOGRAM", 0) or 0)) / macd_peak
        if contraction > 0.6:
            score -= 2

    if (v.get("BB_PERCENT", 0.5) or 0.5) > 0.90:
        score -= 1
    if (v.get("BB_BANDWIDTH", 0.1) or 0.1) < 0.05:
        score -= 1
    if (v.get("VOLUME_RATIO", 1) or 1) > 1.2:
        score += 1
    if (v.get("ATR_COMPRESSION", 0) or 0) > 0.15:
        score -= 1

    if score >= 2:
        return "GOOD_ENTRY", score
    elif score <= -3:
        return "OVERHEATED", score
    else:
        return "NEUTRAL_TIMING", score


# ═══════════════════════════════════════════════════════════════
# Risk 计算
# ═══════════════════════════════════════════════════════════════

def compute_risk(v: Dict[str, Any]) -> int:
    """风险评分（1-10）"""
    score = 0
    if (v.get("REALIZED_VOL", 0) or 0) > (v.get("TARGET_VOL", 0.15) or 0.15):
        score += 2
    if (v.get("CURRENT_DRAWDOWN", 0) or 0) < (v.get("MAX_DRAWDOWN_LIMIT", -0.12) or -0.12):
        score += 3
    if (v.get("VIX", 0) or 0) > 22:
        score += 2
    if (v.get("HY_SPREAD", 0) or 0) > 5:
        score += 3
    return score


# ═══════════════════════════════════════════════════════════════
# 目标仓位
# ═══════════════════════════════════════════════════════════════

def compute_exposure(regime: str, timing: str, risk_score: int) -> float:
    """目标仓位（0-1）"""
    if regime == "BULL_TREND":
        exposure = 1.0 if timing == "GOOD_ENTRY" else (0.60 if timing == "OVERHEATED" else 0.80)
    elif regime == "NEUTRAL":
        exposure = 0.40
    else:
        exposure = 0.10

    return exposure * max(0.2, 1 - risk_score * 0.15)


# ═══════════════════════════════════════════════════════════════
# 策略入口
# ═══════════════════════════════════════════════════════════════

def analyze_momentum(trade_date: str, v: Dict[str, Any]) -> Dict[str, Any]:
    """
    策略A完整分析
    返回结果字典包含: strategy, regime, regime_score, timing, timing_score,
                     risk_score, target_exposure, interpretation
    """
    # 补充内部复合指标
    _derive_composite(v)

    regime, regime_score = compute_regime(v)
    timing, timing_score = compute_timing(v)
    risk_score = compute_risk(v)
    exposure = compute_exposure(regime, timing, risk_score)

    # 信号标签
    signal_tags = []
    if regime == "BULL_TREND":
        signal_tags.append("📈趋势多头")
    elif regime == "RISK_OFF":
        signal_tags.append("🔴防御")
    else:
        signal_tags.append("⚪中性")

    if timing == "GOOD_ENTRY":
        signal_tags.append("✅入场时机好")
    elif timing == "OVERHEATED":
        signal_tags.append("🔥局部过热")

    interpretation = _interpret(regime, regime_score, timing, timing_score, risk_score, v)

    return {
        "strategy":         "MOMENTUM",    # 策略标识
        "trade_date":       trade_date,
        "market_regime":    regime,
        "regime_score":     regime_score,
        "timing_state":     timing,
        "timing_score":     timing_score,
        "risk_score":       risk_score,
        "target_exposure":  round(exposure * 100, 1),  # 转为百分比
        "interpretation":   interpretation,
        "signals":          signal_tags,
        "confidence":        _confidence(regime, regime_score, timing, timing_score),
    }


def _confidence(regime: str, regime_score: int, timing: str, timing_score: int) -> float:
    """信号置信度（0-1）"""
    mag = min(abs(regime_score) / 10.0, 1.0)
    tim_mag = min(abs(timing_score) / 4.0, 1.0)
    if regime in ("BULL_TREND", "RISK_OFF"):
        return round(min(0.5 + mag * 0.3 + tim_mag * 0.2, 0.95), 2)
    return round(0.3 + mag * 0.4 + tim_mag * 0.3, 2)


def _interpret(regime: str, regime_score: int, timing: str, timing_score: int,
               risk_score: int, v: Dict[str, Any]) -> str:
    lines = []

    if regime == "BULL_TREND":
        lines.append("动量趋势向上：EMA多头排列，广度健康，机构净多持仓")
        if timing == "GOOD_ENTRY":
            lines.append("入场时机良好：RSI适中+MACD柱状图扩张")
        elif timing == "OVERHEATED":
            lines.append("注意局部过热：RSI>75或BB%极端，追高风险大")
    elif regime == "RISK_OFF":
        lines.append("市场防御模式：NYAD背离/波动率高/流动性收缩")
        lines.append("建议大幅降低风险敞口，保留现金或配置防御性资产")
    else:
        lines.append("市场中性：趋势不明确，等待方向确认")
        if timing == "GOOD_ENTRY":
            lines.append("但RSI接近超卖，均值回归机会初现")

    if risk_score >= 5:
        lines.append(f"⚠️ 综合风险偏高（{risk_score}/10），注意仓位控制")

    if (v.get("CTA_POSITIONING", 50) or 50) < 20:
        lines.append(f"CTA极度做空({v.get('CTA_POSITIONING'):.0f}%历史百分位)，警惕逼空风险")

    return "；".join(lines)
