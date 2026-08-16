"""
P2 策略C：ML概率引擎（ML Probability Engine）
──────────────────────────────────────────────────────────────────
核心理念：用机器学习预测 SPY 变盘概率，直接量化风险
组成：
  模型1: GradientBoosting（spy_shift_ml.py）
         标签：未来20日最大回撤>8% → shift=1
         特征：ATR%、MA偏离、波动率、RSI、MACD、成交量
  模型2: Neural Network（spy_nn_enhanced_model.py）
         标签：未来10日回撤>3% → shift=1
         特征：加入VIX数据+SPY广度估算
  模型3: Logistic Regression（spy_lr_backtest.py）
         更丰富的特征集，滚动预测

信号逻辑：
  shift_prob > 0.7 → DANGER（离场/防御）
  shift_prob < 0.3 → SAFE（入场时机）
  0.3 ≤ prob ≤ 0.7 → NEUTRAL

典型特征：
  - 定量概率输出，不依赖主观阈值判断
  - 与策略A/B形成互补（量化 vs 主观规则）
  - 可作为仓位 multiplier 直接使用
"""
from __future__ import annotations
import json
import csv
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime

# ═══════════════════════════════════════════════════════════════
# 数据路径
# ═══════════════════════════════════════════════════════════════

# 工作空间根目录
PROJ = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析")
# spy_ml 数据文件
SPY_ML_DIR = PROJ / "TradingAgents" / "spy_ml" / "data"

# 概率时间序列文件（由各ML模型输出）
_PROB_FILES = {
    "gbr": SPY_ML_DIR / "gbr_prob_timeseries.csv",     # GradientBoosting (新)
    # "nn":  SPY_ML_DIR / "nn_prob_timeseries_v2.csv",  # 暂时移除（v1/v2 AUC均≈随机，无参考价值）
    "lr":  SPY_ML_DIR / "lr_prob_timeseries.csv",       # Logistic Regression (新)
}

# ═══════════════════════════════════════════════════════════════
# 概率数据加载器
# ═══════════════════════════════════════════════════════════════

def _load_prob_csv(csv_path: Path, trade_date: str) -> Optional[float]:
    """
    加载指定模型的概率时间序列
    返回 trade_date 对应的 shift_prob，无数据时返回 None
    """
    if not csv_path.exists():
        return None
    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if not rows:
            return None
        # 二分查找（日期已排序）
        lo, hi = 0, len(rows) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            d = rows[mid].get("date", "")
            if d < trade_date:
                lo = mid + 1
            elif d > trade_date:
                hi = mid - 1
            else:
                prob = rows[mid].get("shift_prob") or rows[mid].get("prob_shift")
                return float(prob) if prob is not None and prob != "" else None
        # 找不到精确日期，返回最近的前一天
        for i in range(lo - 1, -1, -1):
            prob = rows[i].get("shift_prob") or rows[i].get("prob_shift")
            if prob is not None and prob != "":
                return float(prob)
        return None
    except Exception:
        return None


def _load_all_probs(trade_date: str) -> Dict[str, Optional[float]]:
    """加载所有模型的概率"""
    probs = {}
    for name, path in _PROB_FILES.items():
        probs[name] = _load_prob_csv(path, trade_date)
    return probs


def get_latest_prob_date(csv_path: Path) -> Optional[str]:
    """获取概率序列最新日期"""
    if not csv_path.exists():
        return None
    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if rows:
            return rows[-1].get("date")
    except Exception:
        pass
    return None


def is_prob_data_fresh(trade_date: str, max_staleness_days: int = 7) -> bool:
    """
    检查概率数据是否新鲜
    以最新模型数据的日期为准（GBR/LR 2026-05-13）
    """
    latest_dates = []
    for path in _PROB_FILES.values():
        d = get_latest_prob_date(path)
        if d:
            latest_dates.append(d)
    if not latest_dates:
        return False
    latest = max(latest_dates)  # 用最新的模型日期
    try:
        from datetime import timedelta
        d1 = datetime.strptime(latest[:10], "%Y-%m-%d")
        d2 = datetime.strptime(trade_date[:10], "%Y-%m-%d")
        return (d2 - d1).days <= max_staleness_days
    except Exception:
        return False


def get_data_staleness_days(trade_date: str) -> int:
    """返回数据过期天数（供诊断用）"""
    latest_dates = []
    for path in _PROB_FILES.values():
        d = get_latest_prob_date(path)
        if d:
            latest_dates.append(d)
    if not latest_dates:
        return 999
    latest = max(latest_dates)
    try:
        d1 = datetime.strptime(latest[:10], "%Y-%m-%d")
        d2 = datetime.strptime(trade_date[:10], "%Y-%m-%d")
        return max(0, (d2 - d1).days)
    except Exception:
        return 999


# ═══════════════════════════════════════════════════════════════
# Regime & Timing 计算
# ═══════════════════════════════════════════════════════════════

def compute_regime(prob: float) -> Tuple[str, int]:
    """
    基于变盘概率的 Regime
    prob > 0.7 → HIGH_RISK（score -3）
    prob > 0.5 → CAUTION   （score -1）
    prob < 0.3 → LOW_RISK   （score +2）
    prob 0.3~0.5 → NEUTRAL （score 0）
    """
    if prob > 0.7:
        return "HIGH_RISK", -3
    elif prob > 0.5:
        return "CAUTION", -1
    elif prob < 0.3:
        return "LOW_RISK", 2
    else:
        return "NEUTRAL", 0


def compute_timing(prob: float, lookback_days: int = 5) -> Tuple[str, int, str]:
    """
    基于概率变化率的 Timing
    prob急剧上升 → 变盘预警（OVERHEATED）
    prob从高位快速下降 → 布局时机（GOOD_ENTRY）
    prob在低位稳定 → 持有（NEUTRAL_TIMING）
    返回: (signal, score, trend_note)
    """
    probs = _load_prob_series(lookback_days + 2)
    if len(probs) < 3:
        return "NEUTRAL_TIMING", 0, "数据不足"

    recent = probs[-lookback_days:]
    avg_recent = sum(recent) / len(recent)
    avg_prev = sum(probs[:-lookback_days]) / max(len(probs) - lookback_days, 1)
    change = avg_recent - avg_prev  # >0 = prob上升（风险积聚）

    score = 0
    signal = "NEUTRAL_TIMING"
    note = f"prob变化={change:+.3f}"

    if prob > 0.7:
        signal = "DANGER"
        score = -3
    elif prob < 0.3 and change > 0.1:
        signal = "GOOD_ENTRY"
        score = 2
        note = f"超卖+概率收敛，逆向布局窗口"
    elif prob < 0.3:
        signal = "SAFE_ENTRY"
        score = 1
    elif change > 0.15 and avg_recent > 0.5:
        signal = "OVERHEATED"
        score = -2
        note = f"概率快速上升({change:+.3f})，注意变盘风险"

    return signal, score, note


def _load_prob_series(lookback: int = 20) -> List[float]:
    """加载最近N天的概率序列（用于计算趋势）"""
    csv_path = _PROB_FILES["gbr"]
    if not csv_path.exists():
        return []
    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        result = []
        for row in reversed(rows):
            prob = row.get("shift_prob") or row.get("prob_shift")
            if prob:
                try:
                    result.append(float(prob))
                except (ValueError, TypeError):
                    pass
            if len(result) >= lookback:
                break
        return list(reversed(result))
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════
# Risk 计算
# ═══════════════════════════════════════════════════════════════

def compute_risk(prob: float, regime: str) -> int:
    """ML风险评分"""
    score = 0
    if prob > 0.7:
        score += 4
    elif prob > 0.5:
        score += 2
    if regime == "HIGH_RISK":
        score += 2
    return min(score, 10)


# ═══════════════════════════════════════════════════════════════
# 目标仓位
# ═══════════════════════════════════════════════════════════════

def compute_exposure(prob: float, regime: str, timing: str,
                    risk_score: int) -> float:
    """
    基于ML概率的目标仓位
    直接用概率作为仓位乘数：
      - prob < 0.2: 低变盘风险，仓位 ×1.0
      - prob 0.2~0.5: 中等，仓位 ×0.7
      - prob 0.5~0.7: 偏高，仓位 ×0.4
      - prob > 0.7: 高风险，仓位 ×0.15
    """
    if regime == "HIGH_RISK":
        base = 0.10
    elif timing in ("GOOD_ENTRY", "SAFE_ENTRY"):
        base = 0.80
    elif regime == "CAUTION":
        base = 0.40
    elif regime == "LOW_RISK":
        base = 0.70
    else:
        base = 0.50

    # 概率作为动态乘数
    if prob < 0.2:
        mult = 1.0
    elif prob < 0.4:
        mult = 0.85
    elif prob < 0.6:
        mult = 0.60
    elif prob < 0.7:
        mult = 0.35
    else:
        mult = 0.15

    # 风险进一步压低
    exposure = base * mult * max(0.20, 1 - risk_score * 0.10)
    return round(exposure * 100, 1)  # 百分比


# ═══════════════════════════════════════════════════════════════
# 策略入口
# ═══════════════════════════════════════════════════════════════

def analyze_ml_probability(trade_date: str, v: Dict[str, Any]) -> Dict[str, Any]:
    """
    策略C完整分析：ML概率引擎
    """
    # ── Step 1: 加载概率 ────────────────────────────────
    probs = _load_all_probs(trade_date)
    prob_gbr = probs.get("gbr")   # 主模型：GradientBoosting
    prob_lr  = probs.get("lr")

    # 双模型平均（ensemble）
    valid_probs = [p for p in [prob_gbr, prob_lr] if p is not None]
    prob = sum(valid_probs) / len(valid_probs) if valid_probs else None

    if prob is None:
        # 无概率数据 → 回退到 P2 shared 变量
        rsi = v.get("SPY_RSI14", 50) or 50
        prob = min((rsi - 50) / 50, 1.0) if rsi else 0.5

    # ── Step 2: Regime / Timing / Risk ─────────────────
    regime, regime_score = compute_regime(prob)
    timing, timing_score, timing_note = compute_timing(prob)
    risk_score = compute_risk(prob, regime)
    exposure = compute_exposure(prob, regime, timing, risk_score)

    # ── Step 3: 概率历史分位数 ─────────────────────────
    prob_history = _load_prob_series(300)
    prob_pct = (
        sum(1 for p in prob_history if p < prob) / len(prob_history) * 100
        if prob_history else 50.0
    )

    # ── Step 4: 数据新鲜度 ────────────────────────────
    is_fresh = is_prob_data_fresh(trade_date)

    # ── Step 5: 信号汇总 ──────────────────────────────
    signal_tags = [
        f"变盘概率: {prob:.1%}" + ("⚠️" if prob > 0.5 else "✅"),
        f"概率分位数: {prob_pct:.0f}% (历史300日)",
        f"Regime: {regime}(score={regime_score:+d})",
        f"Timing: {timing}(score={timing_score:+d}) {timing_note}",
    ]

    if not is_fresh:
        signal_tags.append("⚠️ 概率数据已过期，请重新训练模型")

    if len(valid_probs) > 1:
        signal_tags.append(f"Ensemble: {len(valid_probs)}模型平均")
    elif len(valid_probs) == 1:
        signal_tags.append("⚠️ 仅单一模型，无ensemble")

    return {
        "strategy":          "ML_PROB",
        "trade_date":        trade_date,
        "prob_gbr":          round(prob_gbr, 4) if prob_gbr is not None else None,
        "prob_nn":           None,  # 已移除
        "prob_lr":           round(prob_lr, 4) if prob_lr is not None else None,
        "prob_ensemble":     round(prob, 4),
        "prob_percentile":   round(prob_pct, 1),
        "market_regime":     regime,
        "regime_score":      regime_score,
        "timing_state":      timing,
        "timing_score":      timing_score,
        "timing_note":       timing_note,
        "risk_score":        risk_score,
        "target_exposure":   exposure,
        "data_fresh":        is_fresh,
        "interpretation":    _interpret(prob, regime, timing, timing_note, risk_score, prob_pct),
        "signals":           signal_tags,
        "confidence":        _confidence(prob, regime, len(valid_probs)),
    }


def _confidence(prob: float, regime: str, n_models: int) -> float:
    """信号置信度"""
    base = 0.5
    # 概率极端值置信度更高
    if prob < 0.15 or prob > 0.80:
        base += 0.20
    elif prob < 0.30 or prob > 0.60:
        base += 0.10
    # 多模型 ensemble 更可靠
    if n_models >= 3:
        base += 0.10
    elif n_models >= 2:
        base += 0.05
    return round(min(base, 0.95), 2)


def _interpret(prob: float, regime: str, timing: str,
             timing_note: str, risk_score: int, prob_pct: float) -> str:
    lines = []

    if prob > 0.7:
        lines.append(f"ML模型发出危险信号：变盘概率{prob:.0%}（历史第{prob_pct:.0f}百分位）")
        lines.append("未来20日最大回撤风险极高，建议大幅降仓或离场")
    elif prob > 0.5:
        lines.append(f"ML概率偏高（{prob:.0%}），市场累计风险，注意仓位控制")
    elif prob < 0.3:
        lines.append(f"ML模型确认安全：变盘概率{prob:.0%}（历史低位），适合布局")
    else:
        lines.append(f"ML概率中性（{prob:.0%}），市场平稳，维持当前仓位")

    if regime == "HIGH_RISK":
        lines.append("模型判断：高风险变盘区")
    if timing in ("GOOD_ENTRY", "SAFE_ENTRY"):
        lines.append(f"入场信号：{timing_note}")
    if timing == "DANGER":
        lines.append("⚠️ 建议离场观望")

    if risk_score >= 5:
        lines.append(f"综合ML风险评分：{risk_score}/10")

    return "；".join(lines)


# ═══════════════════════════════════════════════════════════════
# 便捷函数：单独获取概率值
# ═══════════════════════════════════════════════════════════════

def get_shift_prob(trade_date: str) -> Optional[float]:
    """直接获取当日变盘概率"""
    probs = _load_all_probs(trade_date)
    valid = [p for p in probs.values() if p is not None]
    return sum(valid) / len(valid) if valid else None
