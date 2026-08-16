#!/usr/bin/env python3
"""
P1 · 趋势健康度评分系统（Trend Health Scoring System）
======================================================
核心理念：变盘不是"价格跌了"，而是「市场内部一致性崩塌」。

输出：0-100 趋势健康度评分 + 5因子分解 + 状态划分

评分维度（权重）：
  Breadth         30%  — 市场参与广度
  龙头健康度       25%  — NVDA/MSFT/AAPL 结构是否完整
  波动率结构       20%  — VIX 状态 + 波宽收缩/扩张
  流动性          15%  — QQQ/SPY 比率（资金流向）
  价格结构        10%  — ADX 趋势强度 + MA 排列

状态划分：
  >80  强趋势（Strong Trend）
  65-80  健康调整（Healthy Correction）
  50-65  高波动分歧（High Vol Divergence）
  <50   趋势恶化（Trend Deterioration）
  <35   高概率变盘（High Probability Shift）

数据来源：
  - K线：中间过程/klines/{CODE}_1d.json
  - VIX：中间过程/klines/VIX_1d.json
  - 广度：sp500_breadth_finviz.json / breadth_history.json
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

# ── 路径配置 ───────────────────────────────────────────────────────────────
PROJ_DIR   = Path(__file__).parent.parent.parent.parent
KLINES_DIR = PROJ_DIR / "中间过程" / "klines"
STATE_DIR  = PROJ_DIR / "fintech" / "p1" / "state"

# ── 工具函数 ──────────────────────────────────────────────────────────────

def load_klines(code: str) -> Optional[dict]:
    """加载日K，兼容 vol/volume"""
    for suffix in ("_1d.json", ".json"):
        fpath = KLINES_DIR / f"{code}{suffix}"
        if fpath.exists():
            try:
                with open(fpath) as f:
                    d = json.load(f)
                bars = d.get("data", []) if isinstance(d, dict) else (d or [])
                if not bars:
                    return None
                return {
                    "dates":   [b["date"] for b in bars],
                    "closes":  [b["close"] for b in bars],
                    "highs":   [b["high"] for b in bars],
                    "lows":    [b["low"]  for b in bars],
                    "volumes": [b.get("volume") or b.get("vol", 0) for b in bars],
                    "last_date": bars[-1]["date"],
                }
            except Exception:
                return None
    return None


def ema_(closes: list, period: int) -> list:
    if len(closes) < period:
        return [sum(closes)/len(closes)] * len(closes) if closes else []
    k = 2.0 / (period + 1)
    result = [None] * (period - 1)
    result.append(sum(closes[:period]) / period)
    for i in range(period, len(closes)):
        result.append(closes[i] * k + result[-1] * (1 - k))
    return result


def rsi_(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d for d in deltas[-period:] if d > 0]
    losses = [-d for d in deltas[-period:] if d < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def dmi_adx(highs: list, lows: list, closes: list, period: int = 14) -> tuple:
    """返回 (adx, plus_dm, minus_dm) 简化版"""
    if len(closes) < period + 1:
        return 0.0, 0.0, 0.0
    trs = []
    p_dm = []
    m_dm = []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i],
                 abs(highs[i]-closes[i-1]),
                 abs(lows[i]-closes[i-1]))
        plus_dm = max(highs[i]-highs[i-1], 0) if i > 0 else 0
        minus_dm = max(lows[i-1]-lows[i], 0) if i > 0 else 0
        trs.append(tr)
        p_dm.append(plus_dm)
        m_dm.append(minus_dm)
    if len(trs) < period:
        return 0.0, 0.0, 0.0
    tr_avg = sum(trs[-period:]) / period
    p_avg  = sum(p_dm[-period:]) / period
    m_avg  = sum(m_dm[-period:]) / period
    if tr_avg == 0:
        return 0.0, 0.0, 0.0
    p_di = (p_avg / tr_avg) * 100
    m_di = (m_avg / tr_avg) * 100
    dx = abs(p_di - m_di) / (p_di + m_di) * 100 if (p_di + m_di) > 0 else 0
    # 简化 ADX
    adx = dx
    return adx, p_di, m_di


def bollinger_width(closes: list, period: int = 20) -> Optional[float]:
    if len(closes) < period:
        return None
    recent = closes[-period:]
    ma = sum(recent) / period
    std = (sum((c - ma)**2 for c in recent) / period) ** 0.5
    return std / ma if ma > 0 else None


# ── 数据加载 ────────────────────────────────────────────────────────────────

def load_vix() -> Optional[float]:
    fpath = KLINES_DIR / "VIX_1d.json"
    if not fpath.exists():
        return None
    try:
        bars = json.load(open(fpath)).get("data", [])
        return bars[-1]["close"] if bars else None
    except Exception:
        return None


def load_vix_bars(n: int = 20) -> list:
    fpath = KLINES_DIR / "VIX_1d.json"
    if not fpath.exists():
        return []
    try:
        bars = json.load(open(fpath)).get("data", [])
        return bars[-n:] if bars else []
    except Exception:
        return []


def load_breadth() -> dict:
    fpath = KLINES_DIR / "sp500_breadth_finviz.json"
    if not fpath.exists():
        return {"above_sma20": 0.5, "above_sma50": 0.5, "above_sma200": 0.5}
    try:
        raw = json.load(open(fpath))
        above_50 = raw.get("above_sma50", 0.5)
        above_20 = 1.0 - ((1.0 - above_50) ** 1.3)
        return {
            "above_sma20":  round(above_20, 4),
            "above_sma50":  raw.get("above_sma50"),
            "above_sma200": raw.get("above_sma200"),
            "date":         raw.get("date"),
        }
    except Exception:
        return {"above_sma20": 0.5}


def load_breadth_history(n: int = 60) -> list:
    fpath = KLINES_DIR / "breadth_history.json"
    if not fpath.exists():
        return []
    try:
        history = json.load(open(fpath))
        return history[-n:] if isinstance(history, list) else []
    except Exception:
        return []


# ── 因子1：Breadth（30分）───────────────────────────────────────────────

def calc_breadth_factor(breadth_data: dict) -> dict:
    """
    Above20EMA → 0-30 分
      >70%  → 30
      55-70% → 20
      40-55% → 10
      <40%  → -20（严重警告）
    """
    above = breadth_data.get("above_sma20", 0.5)
    if above > 0.70:
        score = 30
        label = "超强参与"
    elif above > 0.55:
        score = 20
        label = "健康参与"
    elif above > 0.40:
        score = 10
        label = "分化"
    else:
        score = -20
        label = "⚠️ 崩塌"

    return {
        "factor": "Breadth",
        "weight": 30,
        "raw_value": round(above, 4),
        "score": score,
        "max": 30,
        "label": label,
        "above_sma20": round(above, 4),
        "above_sma50": breadth_data.get("above_sma50"),
        "above_sma200": breadth_data.get("above_sma200"),
    }


# ── 因子2：龙头健康度（25分）─────────────────────────────────────────

def calc_leadership_factor() -> dict:
    """
    NVDA / MSFT / AAPL 结构健康评估
    全部健康 → +25
    1只破位 → +10
    2只+破位 → -5
    3只全破位 → -15
    """
    leaders = ["NVDA", "MSFT", "AAPL"]
    results = {}
    broken = 0

    for code in leaders:
        klines = load_klines(code)
        if not klines or len(klines["closes"]) < 25:
            results[code] = {"status": "no_data", "score_contrib": 0}
            continue

        closes  = klines["closes"]
        volumes = klines["volumes"]
        highs   = klines["highs"]
        lows    = klines["lows"]
        ema20   = ema_(closes, 20)
        last_ema20 = ema20[-1] if ema20 and ema20[-1] is not None else 0

        if not last_ema20 or len(closes) < 22:
            results[code] = {"status": "no_data", "score_contrib": 0}
            continue

        last_close = closes[-1]
        last_vol   = volumes[-1]
        vol_avg20  = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes)/len(volumes)
        vol_ratio  = last_vol / vol_avg20 if vol_avg20 > 0 else 1.0

        broken_flag = False
        reason = "健康"

        # 信号1：放量破 EMA20
        if last_vol > vol_avg20 * 2.0 and last_close < last_ema20:
            broken_flag = True
            reason = "放量破EMA20"

        # 信号2：放量破20日新低
        if not broken_flag:
            low_20 = min(lows[-20:]) if len(lows) >= 20 else min(lows)
            if last_close <= low_20 and last_vol > vol_avg20 * 1.5:
                broken_flag = True
                reason = "放量破20日低"

        # 信号3：急跌>5% + 放量
        if not broken_flag and len(closes) >= 2:
            chg = (closes[-1] / closes[-2] - 1) * 100
            if chg < -5 and last_vol > vol_avg20 * 2.0:
                broken_flag = True
                reason = f"急跌{chg:.1f}%+放量"

        results[code] = {
            "status": "broken" if broken_flag else "healthy",
            "reason": reason,
            "last_close": round(last_close, 2),
            "ema20": round(last_ema20, 2),
            "vol_ratio": round(vol_ratio, 1),
            "last_date": klines.get("last_date"),
        }
        if broken_flag:
            broken += 1

    # 计分
    if broken == 0:
        factor_score = 25
        label = "全部健康"
    elif broken == 1:
        factor_score = 10
        label = "1只破位"
    elif broken == 2:
        factor_score = -5
        label = "2只破位"
    else:
        factor_score = -15
        label = "⚠️ 3只全破位"

    return {
        "factor": "Leadership",
        "weight": 25,
        "score": factor_score,
        "max": 25,
        "label": label,
        "leaders": results,
    }


# ── 因子3：波动率结构（20分）──────────────────────────────────────────

def calc_volatility_factor() -> dict:
    """
    VIX（10分）+ BB波宽（10分）
    VIX:
      <15 → 10（低波动，看涨）
      15-20 → 8
      20-25 → 6
      25-30 → 3
      >30 → 0
    BB波宽（SPY）:
      <0.05（极度收缩）→ 10（蓄势）
      0.05-0.08 → 7
      0.08-0.12 → 5
      >0.12（扩张）→ 3
    """
    vix = load_vix()
    bbw = None

    spy = load_klines("SPY")
    if spy and len(spy["closes"]) >= 20:
        bbw = bollinger_width(spy["closes"], 20)

    # VIX 评分
    if vix is None:
        vix_score, vix_label = 5, "无数据"
    elif vix < 15:
        vix_score, vix_label = 10, "低波动"
    elif vix < 20:
        vix_score, vix_label = 8, "正常偏低"
    elif vix < 25:
        vix_score, vix_label = 6, "正常"
    elif vix < 30:
        vix_score, vix_label = 3, "偏高"
    else:
        vix_score, vix_label = 0, "⚠️ 高波动"

    # 波宽评分
    if bbw is None:
        bb_score, bb_label = 5, "无数据"
    elif bbw < 0.05:
        bb_score, bb_label = 10, "极度收缩（蓄势）"
    elif bbw < 0.08:
        bb_score, bb_label = 7, "正常收缩"
    elif bbw < 0.12:
        bb_score, bb_label = 5, "正常扩张"
    else:
        bb_score, bb_label = 3, "大幅扩张"

    total = vix_score + bb_score

    return {
        "factor": "Volatility",
        "weight": 20,
        "score": total,
        "max": 20,
        "vix_score": vix_score,
        "vix": round(vix, 2) if vix else None,
        "vix_label": vix_label,
        "bb_score": bb_score,
        "bb_width": round(bbw, 4) if bbw else None,
        "bb_label": bb_label,
        "label": f"VIX={vix_label}, BB={bb_label}",
    }


# ── 因子4：流动性（15分）────────────────────────────────────────────────

def calc_liquidity_factor() -> dict:
    """
    QQQ/SPY 比率变化（资金流向科技/成长）
    20日比率变化：
      >+3% → 15（资金积极涌入科技）
      >+1.5% → 12
      >0% → 9
      >-1.5% → 6
      <-1.5% → 3
    """
    spy = load_klines("SPY")
    qqq = load_klines("QQQ")

    if not spy or not qqq or len(spy["closes"]) < 21:
        return {
            "factor": "Liquidity", "weight": 15,
            "score": 7, "max": 15, "label": "数据不足",
            "ratio_now": None, "ratio_20d_ago": None, "ratio_chg": None,
        }

    closes_s = spy["closes"]
    closes_q = qqq["closes"]

    ratio_now  = closes_q[-1] / closes_s[-1]
    ratio_20d  = closes_q[-20] / closes_s[-20] if len(closes_s) >= 20 else ratio_now
    chg_pct = (ratio_now / ratio_20d - 1) * 100 if ratio_20d > 0 else 0.0

    if chg_pct > 3:
        score = 15; label = "资金涌入科技"
    elif chg_pct > 1.5:
        score = 12; label = "科技偏好"
    elif chg_pct > 0:
        score = 9;  label = "略偏科技"
    elif chg_pct > -1.5:
        score = 6;  label = "略偏防御"
    else:
        score = 3;  label = "⚠️ 资金撤出科技"

    return {
        "factor": "Liquidity",
        "weight": 15,
        "score": score,
        "max": 15,
        "ratio_now": round(ratio_now, 4),
        "ratio_20d_ago": round(ratio_20d, 4),
        "ratio_chg": round(chg_pct, 2),
        "label": label,
    }


# ── 因子5：价格结构（10分）────────────────────────────────────────────

def calc_price_structure_factor() -> dict:
    """
    ADX（趋势强度）6分 + MA排列（4分）
    ADX:
      >30 → 6
      25-30 → 5
      20-25 → 4
      15-20 → 2
      <15 → 0
    MA排列：
      MA20>MA50>MA200 → 4（完美多头）
      MA20>MA50 → 3
      MA20在MA50附近 → 2
      MA20<MA50 → 0
    """
    spy = load_klines("SPY")
    if not spy or len(spy["closes"]) < 60:
        return {
            "factor": "PriceStructure", "weight": 10,
            "score": 5, "max": 10, "label": "数据不足",
            "adx": None, "ma_score": None, "ma_label": None,
        }

    closes = spy["closes"]
    highs  = spy["highs"]
    lows   = spy["lows"]

    adx, _, _ = dmi_adx(highs, lows, closes, 14)

    # ADX 评分
    if adx > 30:
        adx_score = 6; adx_label = "强趋势"
    elif adx > 25:
        adx_score = 5; adx_label = "趋势形成"
    elif adx > 20:
        adx_score = 4; adx_label = "趋势确认"
    elif adx > 15:
        adx_score = 2; adx_label = "弱趋势"
    else:
        adx_score = 0; adx_label = "⚠️ 无趋势"

    # MA 排列
    ma20 = ema_(closes, 20)
    ma50 = ema_(closes, 50)
    ma200 = ema_(closes, 200)

    last_20 = ma20[-1] if ma20 and ma20[-1] else 0
    last_50 = ma50[-1] if len(ma50) >= 50 and ma50[-1] else 0
    last_200 = ma200[-1] if len(ma200) >= 200 and ma200[-1] else 0

    if last_20 > last_50 > last_200:
        ma_score = 4; ma_label = "完美多头排列"
    elif last_20 > last_50:
        ma_score = 3; ma_label = "在MA50上方"
    elif last_20 > last_200:
        ma_score = 2; ma_label = "在MA200上方"
    else:
        ma_score = 0; ma_label = "⚠️ 空头排列"

    total = adx_score + ma_score

    return {
        "factor": "PriceStructure",
        "weight": 10,
        "score": total,
        "max": 10,
        "adx": round(adx, 1),
        "adx_score": adx_score,
        "adx_label": adx_label,
        "ma_score": ma_score,
        "ma_label": ma_label,
        "ma20": round(last_20, 2),
        "ma50": round(last_50, 2),
        "ma200": round(last_200, 2),
        "label": f"ADX={adx_label}, MA={ma_label}",
    }


# ── 主函数 ────────────────────────────────────────────────────────────────

def calc_trend_health() -> dict:
    """
    计算趋势健康度评分（0-100）
    返回完整结果 + 状态划分
    """
    breadth_data = load_breadth()

    f1 = calc_breadth_factor(breadth_data)
    f2 = calc_leadership_factor()
    f3 = calc_volatility_factor()
    f4 = calc_liquidity_factor()
    f5 = calc_price_structure_factor()

    factors = [f1, f2, f3, f4, f5]
    total = sum(f["score"] for f in factors)
    max_total = sum(f["max"] for f in factors)

    # 归一化到 0-100
    score_pct = (total / max_total) * 100 if max_total > 0 else 0

    # 状态划分
    if score_pct > 80:
        state = "强趋势"
        state_icon = "🚀"
    elif score_pct >= 65:
        state = "健康调整"
        state_icon = "🐂"
    elif score_pct >= 50:
        state = "高波动分歧"
        state_icon = "⚠️"
    elif score_pct >= 35:
        state = "趋势恶化"
        state_icon = "🐻"
    else:
        state = "高概率变盘"
        state_icon = "🚨"

    # 内部一致性判断（核心：是否一致看涨/看跌）
    bullish_factors  = sum(1 for f in factors if f["score"] >= f["max"] * 0.6)
    bearish_factors = sum(1 for f in factors if f["score"] <= 0)

    # 一致性信号
    if bullish_factors >= 4 and bearish_factors == 0:
        consensus = "高度一致看涨"
    elif bullish_factors >= 3 and bearish_factors <= 1:
        consensus = "偏多一致"
    elif bullish_factors >= 2 and bearish_factors >= 2:
        consensus = "分歧"
    elif bullish_factors <= 1 and bearish_factors >= 3:
        consensus = "⚠️ 高度一致看跌"
    else:
        consensus = "轻微分歧"

    return {
        "date": str(date.today()),
        "total_score": round(score_pct, 1),
        "raw_total": total,
        "max_total": max_total,
        "state": state,
        "state_icon": state_icon,
        "consensus": consensus,
        "bullish_factors": bullish_factors,
        "bearish_factors": bearish_factors,
        "factors": {
            f["factor"]: {
                "score": f["score"],
                "max": f["max"],
                "pct": round(f["score"] / f["max"] * 100) if f["max"] > 0 else 0,
                "label": f.get("label", ""),
                "raw_value": f.get("raw_value") or f.get("vix") or f.get("ratio_chg") or f.get("adx") or None,
            }
            for f in factors
        },
        # 原始因子详情（供调试）
        "_raw": factors,
    }


def save_trend_health(result: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fpath = STATE_DIR / "trend_health.json"
    with open(fpath, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)


def get_trend_health() -> dict | None:
    fpath = STATE_DIR / "trend_health.json"
    if not fpath.exists():
        return None
    try:
        d = json.load(open(fpath))
        return d if d.get("date") == str(date.today()) else None
    except Exception:
        return None


# ── 入口 ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = calc_trend_health()
    save_trend_health(result)

    s  = result["state_icon"]
    sc = result["total_score"]
    st = result["state"]
    cs = result["consensus"]

    print(f"\n[趋势健康度] {s} {st} ({sc}/100) | {cs}")
    for fname, f in result["factors"].items():
        pct = f["pct"]
        bar = "█" * int(pct/10) + "░" * (10 - int(pct/10))
        print(f"  {fname:<20} {f['score']:>3}/{f['max']:<3} {bar} {f['label']}")

    print()
    print(json.dumps(result, indent=2, ensure_ascii=False))
