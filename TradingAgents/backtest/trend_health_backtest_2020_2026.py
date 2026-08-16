#!/usr/bin/env python3
"""
P1 · 趋势健康度评分系统回测（2020-2026）
==========================================
对 SPY/QQQ/VIX/NVDA/MSFT/AAPL 日K数据进行回测，
评估趋势健康度评分系统的有效性。

核心逻辑：逐日计算 trend_health_score（0-100），对比后续收益率。
"""

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import numpy as np

# ── 路径配置 ────────────────────────────────────────────────────────────────
PROJ_DIR   = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析")
KLINES_DIR = PROJ_DIR / "中间过程" / "klines"
OUTPUT_DIR = PROJ_DIR / "backtest"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 全局缓存 ────────────────────────────────────────────────────────────────
_KLINE_CACHE: Dict[str, dict] = {}

# ── 数据加载 ────────────────────────────────────────────────────────────────

def load_klines(code: str) -> Optional[dict]:
    """加载日K，支持 vol/volume 字段兼容"""
    if code in _KLINE_CACHE:
        return _KLINE_CACHE[code]

    for suffix in ("_1d.json", ".json"):
        fpath = KLINES_DIR / f"{code}{suffix}"
        if fpath.exists():
            try:
                with open(fpath) as f:
                    d = json.load(f)
                bars = d.get("data", []) if isinstance(d, dict) else (d or [])
                if not bars:
                    return None

                # Build date→bar lookup
                date_map = {}
                for b in bars:
                    date_map[b["date"]] = b

                result = {
                    "dates":    [b["date"] for b in bars],
                    "closes":   [b["close"] for b in bars],
                    "highs":    [b["high"] for b in bars],
                    "lows":     [b["low"]  for b in bars],
                    "volumes":  [b.get("volume") or b.get("vol", 0) for b in bars],
                    "date_map": date_map,
                    "last_date": bars[-1]["date"],
                }
                _KLINE_CACHE[code] = result
                return result
            except Exception as e:
                print(f"[WARN] Failed to load {code}: {e}")
                return None
    return None


def get_bar(klines: dict, target_date: str) -> Optional[dict]:
    """获取指定日期的K线数据（向前找最近的交易日）"""
    date_map = klines.get("date_map", {})
    if target_date in date_map:
        return date_map[target_date]
    # Try earlier dates
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    for i in range(1, 7):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        if d in date_map:
            return date_map[d]
    return None


def idx_at_date(klines: dict, target_date: str) -> int:
    """返回 target_date 对应的索引（向前找最近的交易日）"""
    dates = klines["dates"]
    if target_date in dates:
        return dates.index(target_date)
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    for i in range(1, 7):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        if d in dates:
            return dates.index(d)
    return len(dates) - 1


# ── 技术指标 ────────────────────────────────────────────────────────────────

def ema(closes: list, period: int) -> list:
    if len(closes) < period:
        return [sum(closes)/len(closes)] * len(closes) if closes else []
    k = 2.0 / (period + 1)
    result = [None] * (period - 1)
    result.append(sum(closes[:period]) / period)
    for i in range(period, len(closes)):
        result.append(closes[i] * k + result[-1] * (1 - k))
    return result


def sma(closes: list, period: int) -> list:
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(closes[i - period + 1:i + 1]) / period)
    return result


def dmi_adx(highs: list, lows: list, closes: list, period: int = 14) -> Tuple[float, float, float]:
    """返回 (adx, plus_di, minus_di)"""
    if len(closes) < period + 2:
        return 0.0, 0.0, 0.0
    trs, p_dm, m_dm = [], [], []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i] - closes[i-1]))
        plus_dm  = max(highs[i] - highs[i-1], 0)
        minus_dm = max(lows[i-1] - lows[i], 0)
        trs.append(tr)
        p_dm.append(plus_dm)
        m_dm.append(minus_dm)
    if len(trs) < period:
        return 0.0, 0.0, 0.0

    tr_smooth = sum(trs[-period:])
    p_smooth  = sum(p_dm[-period:])
    m_smooth  = sum(m_dm[-period:])

    if tr_smooth == 0:
        return 0.0, 0.0, 0.0

    p_di = (p_smooth / tr_smooth) * 100
    m_di = (m_smooth / tr_smooth) * 100
    dx = abs(p_di - m_di) / (p_di + m_di) * 100 if (p_di + m_di) > 0 else 0
    return dx, p_di, m_di


def bollinger_width(closes: list, period: int = 20) -> Optional[float]:
    if len(closes) < period:
        return None
    recent = closes[-period:]
    ma = sum(recent) / period
    std = (sum((c - ma)**2 for c in recent) / period) ** 0.5
    return std / ma if ma > 0 else None


# ── 因子计算（逐日版本）────────────────────────────────────────────────────

def estimate_breadth_from_spy(spy_klines: dict, idx: int, closes: list) -> float:
    """
    用 SPY 的价格位置来估算市场广度（above_sma20）
    方法：SPY 在过去20日中处于高位比例 → 映射到 above_ema20
    """
    if idx < 20:
        return 0.5

    # SPY 20日低位
    low_20  = min(closes[max(0, idx-19):idx+1])
    high_20 = max(closes[max(0, idx-19):idx+1])
    price_range = high_20 - low_20

    if price_range <= 0:
        return 0.5

    # 当前价在20日区间的位置
    position = (closes[idx] - low_20) / price_range  # 0~1

    # 映射到 above_ema（粗略估计）
    # position 0.5 → 0.5, position 1.0 → 0.9, position 0.0 → 0.1
    estimated_above_ema = max(0.1, min(0.95, 0.1 + 0.8 * position))

    # 额外参考：SPY 与 20日EMA 的关系
    ema20 = ema(closes, 20)
    if ema20[idx] is not None and ema20[idx] > 0:
        ema_ratio = closes[idx] / ema20[idx]
        # 高于EMA越多，above_ema越高
        ema_estimate = min(0.95, max(0.1, ema_ratio - 0.02) ** 4 * 0.5 + 0.5 - (ema_ratio - 1) * 2)
        # 综合估算
        estimated_above_ema = 0.5 * estimated_above_ema + 0.5 * ema_estimate

    return estimated_above_ema


def calc_breadth_factor_spy(spy_klines: dict, idx: int, closes: list) -> Tuple[int, dict]:
    """Breadth factor score (0-30)"""
    above = estimate_breadth_from_spy(spy_klines, idx, closes)
    if above > 0.70:
        score = 30; label = "超强参与"
    elif above > 0.55:
        score = 20; label = "健康参与"
    elif above > 0.40:
        score = 10; label = "分化"
    else:
        score = -20; label = "⚠️ 崩塌"
    return score, {"above_ema_est": round(above, 4), "label": label}


def calc_leadership_factor_spy(leader_klines: dict, idx: int) -> Tuple[int, dict]:
    """Leadership factor score (0-25)"""
    results = {}
    broken = 0

    for code, klines in leader_klines.items():
        if klines is None or idx >= len(klines["closes"]) or idx < 21:
            results[code] = {"status": "no_data"}
            continue

        closes  = klines["closes"]
        volumes = klines["volumes"]
        highs   = klines["highs"]
        lows    = klines["lows"]
        ema20   = ema(closes, 20)

        if ema20[idx] is None or ema20[idx] == 0:
            results[code] = {"status": "no_data"}
            continue

        last_close = closes[idx]
        last_vol   = volumes[idx]
        ema20_val  = ema20[idx]

        # vol avg of last 20 days up to idx (exclusive of today)
        vol_end = min(idx + 1, len(volumes))
        vol_start = max(0, vol_end - 20)
        vol_avg20 = sum(volumes[vol_start:vol_end]) / (vol_end - vol_start) if vol_end > vol_start else 1
        vol_ratio = last_vol / vol_avg20 if vol_avg20 > 0 else 1.0

        broken_flag = False
        reason = "健康"

        # Signal 1: volume surge + below EMA20
        if last_vol > vol_avg20 * 2.0 and last_close < ema20_val:
            broken_flag = True
            reason = "放量破EMA20"

        # Signal 2: volume surge + broke 20d low
        if not broken_flag:
            low_start = max(0, idx - 19)
            low_20 = min(lows[low_start:idx+1])
            if last_close <= low_20 and last_vol > vol_avg20 * 1.5:
                broken_flag = True
                reason = "放量破20日低"

        # Signal 3: sharp drop > 5% + volume
        if not broken_flag and idx >= 1:
            chg = (closes[idx] / closes[idx-1] - 1) * 100
            if chg < -5 and last_vol > vol_avg20 * 2.0:
                broken_flag = True
                reason = f"急跌{chg:.1f}%+放量"

        results[code] = {
            "status": "broken" if broken_flag else "healthy",
            "reason": reason,
            "vol_ratio": round(vol_ratio, 1),
        }
        if broken_flag:
            broken += 1

    # Score
    if broken == 0:
        factor_score = 25; label = "全部健康"
    elif broken == 1:
        factor_score = 10; label = "1只破位"
    elif broken == 2:
        factor_score = -5; label = "2只破位"
    else:
        factor_score = -15; label = "⚠️ 3只全破位"

    return factor_score, {"label": label, "leaders": results, "broken_count": broken}


def calc_volatility_factor_spy(spy_klines: dict, vix_klines: dict, idx: int) -> Tuple[int, dict]:
    """Volatility factor score (0-20)"""
    vix_val = None
    if vix_klines and idx < len(vix_klines["closes"]):
        vix_val = vix_klines["closes"][idx]

    bbw = None
    if spy_klines and idx >= 19:
        spy_closes = spy_klines["closes"][:idx+1]
        bbw = bollinger_width(spy_closes, 20)

    # VIX score
    if vix_val is None:
        vix_score, vix_label = 5, "无数据"
    elif vix_val < 15:
        vix_score, vix_label = 10, "低波动"
    elif vix_val < 20:
        vix_score, vix_label = 8, "正常偏低"
    elif vix_val < 25:
        vix_score, vix_label = 6, "正常"
    elif vix_val < 30:
        vix_score, vix_label = 3, "偏高"
    else:
        vix_score, vix_label = 0, "⚠️ 高波动"

    # BB width score
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
    return total, {
        "vix_score": vix_score,
        "vix": round(vix_val, 2) if vix_val else None,
        "vix_label": vix_label,
        "bb_score": bb_score,
        "bb_width": round(bbw, 4) if bbw else None,
        "bb_label": bb_label,
    }


def calc_liquidity_factor_spy(spy_klines: dict, qqq_klines: dict, idx: int) -> Tuple[int, dict]:
    """Liquidity factor score (0-15)"""
    if not spy_klines or not qqq_klines or idx < 20:
        return 7, {"label": "数据不足", "ratio_chg": None}

    spy_c = spy_klines["closes"]
    qqq_c = qqq_klines["closes"]

    ratio_now = qqq_c[idx] / spy_c[idx]
    ratio_20d = qqq_c[idx-20] / spy_c[idx-20]
    chg_pct = (ratio_now / ratio_20d - 1) * 100

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

    return score, {
        "ratio_now": round(ratio_now, 4),
        "ratio_20d": round(ratio_20d, 4),
        "ratio_chg": round(chg_pct, 2),
        "label": label,
    }


def calc_price_structure_factor_spy(spy_klines: dict, idx: int) -> Tuple[int, dict]:
    """Price structure factor score (0-10)"""
    if not spy_klines or idx < 60:
        return 5, {"label": "数据不足", "adx": None}

    closes = spy_klines["closes"][:idx+1]
    highs  = spy_klines["highs"][:idx+1]
    lows   = spy_klines["lows"][:idx+1]

    adx, _, _ = dmi_adx(highs, lows, closes, 14)

    # ADX score
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

    # MA arrangement
    ma20  = ema(closes, 20)
    ma50  = ema(closes, 50)
    ma200 = ema(closes, 200)

    last_20  = ma20[-1]  if ma20[-1]  else 0
    last_50  = ma50[-1]  if len(ma50) >= 50 and ma50[-1] else 0
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
    return total, {
        "adx": round(adx, 1),
        "adx_score": adx_score,
        "adx_label": adx_label,
        "ma_score": ma_score,
        "ma_label": ma_label,
    }


# ── 主评分计算 ─────────────────────────────────────────────────────────────

def calc_daily_score(
    spy_klines: dict,
    qqq_klines: dict,
    vix_klines: dict,
    leader_klines: dict,
    idx: int,
) -> dict:
    """计算某一天的 trend_health_score"""
    closes = spy_klines["closes"]

    f1_score, f1_extra = calc_breadth_factor_spy(spy_klines, idx, closes)
    f2_score, f2_extra = calc_leadership_factor_spy(leader_klines, idx)
    f3_score, f3_extra = calc_volatility_factor_spy(spy_klines, vix_klines, idx)
    f4_score, f4_extra = calc_liquidity_factor_spy(spy_klines, qqq_klines, idx)
    f5_score, f5_extra = calc_price_structure_factor_spy(spy_klines, idx)

    raw_total = f1_score + f2_score + f3_score + f4_score + f5_score
    max_total = 30 + 25 + 20 + 15 + 10  # 100

    score = max(0, min(100, (raw_total / max_total) * 100))

    # State
    if score > 80:
        state = "强趋势"
    elif score >= 65:
        state = "健康调整"
    elif score >= 50:
        state = "高波动分歧"
    elif score >= 35:
        state = "趋势恶化"
    else:
        state = "高概率变盘"

    return {
        "date": spy_klines["dates"][idx],
        "idx": idx,
        "score": round(score, 1),
        "raw_total": raw_total,
        "state": state,
        "f1_breadth":   {"score": f1_score, "max": 30, **f1_extra},
        "f2_leadership":{"score": f2_score, "max": 25, **f2_extra},
        "f3_volatility":{"score": f3_score, "max": 20, **f3_extra},
        "f4_liquidity": {"score": f4_score, "max": 15, **f4_extra},
        "f5_structure": {"score": f5_score, "max": 10, **f5_extra},
    }


# ── 回测运行 ────────────────────────────────────────────────────────────────

def run_backtest():
    print("=" * 60)
    print("趋势健康度评分系统回测（2020-2026）")
    print("=" * 60)

    # Load all data
    print("\n[1/5] 加载 K线数据...")
    spy_klines  = load_klines("SPY")
    qqq_klines  = load_klines("QQQ")
    vix_klines  = load_klines("VIX")
    nvda_klines = load_klines("NVDA")
    msft_klines = load_klines("MSFT")
    aapl_klines = load_klines("AAPL")

    leader_klines = {
        "NVDA": nvda_klines,
        "MSFT": msft_klines,
        "AAPL": aapl_klines,
    }

    # Verify SPY date range
    spy_dates = spy_klines["dates"]
    start_idx = 0
    end_idx   = len(spy_dates) - 1

    # Find 2020-01-01 start
    for i, d in enumerate(spy_dates):
        if d >= "2020-01-01":
            start_idx = i
            break

    # End at 2026-05-11
    for i, d in enumerate(spy_dates):
        if d <= "2026-05-11":
            end_idx = i

    print(f"  SPY: {spy_dates[start_idx]} → {spy_dates[end_idx]}")
    print(f"  总交易日: {end_idx - start_idx + 1}")

    # Sample every 5 days for performance
    SAMPLE_STEP = 5
    sample_indices = list(range(start_idx, end_idx + 1, SAMPLE_STEP))
    print(f"  采样间隔: 每{SAMPLE_STEP}个交易日取1个样本")
    print(f"  采样数量: {len(sample_indices)}")

    # Also compute for all dates to get accurate signals
    all_indices = list(range(start_idx, end_idx + 1))

    print("\n[2/5] 计算每日评分（采样模式）...")

    all_scores = {}  # date → score record

    for i, idx in enumerate(all_indices):
        if i % 100 == 0:
            print(f"  进度: {i}/{len(all_indices)} ({spy_dates[idx]})...")

        rec = calc_daily_score(spy_klines, qqq_klines, vix_klines, leader_klines, idx)
        all_scores[spy_dates[idx]] = rec

    # Also store sampled
    sample_scores = {spy_dates[i]: all_scores[spy_dates[i]] for i in sample_indices}

    print(f"  完成！共计算 {len(all_scores)} 个交易日")

    print("\n[3/5] 计算后续收益率...")

    # Compute future returns for each scored day
    def future_return(idx: int, days: int) -> Optional[float]:
        if idx + days >= len(spy_klines["closes"]):
            return None
        c_now  = spy_klines["closes"][idx]
        c_next = spy_klines["closes"][idx + days]
        return (c_next / c_now - 1) * 100

    # Add returns to each score record
    for d, rec in all_scores.items():
        idx = rec["idx"]
        rec["ret_5d"]  = future_return(idx, 5)
        rec["ret_20d"] = future_return(idx, 20)
        rec["ret_60d"] = future_return(idx, 60)

    print("\n[4/5] 分析关键信号...")

    # Key signals analysis
    critical_signals = []  # score < 35
    strong_signals   = []  # score > 80

    for d, rec in all_scores.items():
        if rec["score"] < 35:
            critical_signals.append(rec)
        if rec["score"] > 80:
            strong_signals.append(rec)

    print(f"  高概率变盘信号(<35): {len(critical_signals)} 个")
    print(f"  强趋势信号(>80): {len(strong_signals)} 个")

    print("\n[5/5] 生成 HTML 报告...")

    # ── Statistics ──────────────────────────────────────────────────────
    scores_list = [r["score"] for r in all_scores.values()]
    score_states = {
        "强趋势(>80)": [],
        "健康调整(65-80)": [],
        "高波动分歧(50-65)": [],
        "趋势恶化(35-50)": [],
        "高概率变盘(<35)": [],
    }
    for r in all_scores.values():
        s = r["score"]
        if s > 80:    score_states["强趋势(>80)"].append(r)
        elif s >= 65: score_states["健康调整(65-80)"].append(r)
        elif s >= 50: score_states["高波动分歧(50-65)"].append(r)
        elif s >= 35: score_states["趋势恶化(35-50)"].append(r)
        else:         score_states["高概率变盘(<35)"].append(r)

    # Win rate analysis: score>80 → long, score<50 → short
    long_returns_5d  = []
    short_returns_5d = []
    for r in all_scores.values():
        if r["score"] > 80 and r["ret_5d"] is not None:
            long_returns_5d.append(r["ret_5d"])
        if r["score"] < 50 and r["ret_5d"] is not None:
            short_returns_5d.append(r["ret_5d"])

    long_win_rate_5d  = sum(1 for x in long_returns_5d  if x > 0) / len(long_returns_5d)  * 100 if long_returns_5d else 0
    short_win_rate_5d = sum(1 for x in short_returns_5d if x < 0) / len(short_returns_5d) * 100 if short_returns_5d else 0
    avg_long_ret_5d   = np.mean(long_returns_5d)  if long_returns_5d else 0
    avg_short_ret_5d  = np.mean(short_returns_5d) if short_returns_5d else 0

    # Rolling drawdown
    scores_arr = np.array(scores_list)
    running_max = np.maximum.accumulate(scores_arr)
    drawdowns = (scores_arr - running_max) / running_max * 100

    # Max drawdown period
    max_dd_idx = np.argmin(drawdowns)
    max_dd = drawdowns[max_dd_idx]
    max_dd_date = spy_dates[start_idx + max_dd_idx]

    # ── Critical signal analysis ────────────────────────────────────────
    crit_stats = {
        "count": len(critical_signals),
        "ret_5d_avg":  np.mean([r["ret_5d"]  for r in critical_signals if r["ret_5d"]  is not None]) if critical_signals else 0,
        "ret_20d_avg": np.mean([r["ret_20d"] for r in critical_signals if r["ret_20d"] is not None]) if critical_signals else 0,
        "ret_60d_avg": np.mean([r["ret_60d"] for r in critical_signals if r["ret_60d"] is not None]) if critical_signals else 0,
        "ret_5d_pos":  sum(1 for r in critical_signals if r["ret_5d"]  is not None and r["ret_5d"]  > 0) / max(1, len([r for r in critical_signals if r["ret_5d"]  is not None])) * 100,
        "ret_5d_neg":  sum(1 for r in critical_signals if r["ret_5d"]  is not None and r["ret_5d"]  < 0) / max(1, len([r for r in critical_signals if r["ret_5d"]  is not None])) * 100,
        "ret_20d_pos": sum(1 for r in critical_signals if r["ret_20d"] is not None and r["ret_20d"] > 0) / max(1, len([r for r in critical_signals if r["ret_20d"] is not None])) * 100,
        "ret_60d_pos": sum(1 for r in critical_signals if r["ret_60d"] is not None and r["ret_60d"] > 0) / max(1, len([r for r in critical_signals if r["ret_60d"] is not None])) * 100,
    }

    # ── Regime transitions: from >80 to <50 in <20 days ────────────────
    rapid_transitions = []
    sorted_dates = sorted(all_scores.keys())
    for i in range(len(sorted_dates) - 1):
        d = sorted_dates[i]
        if all_scores[d]["score"] > 80:
            # Look ahead up to 20 days
            for j in range(i + 1, min(i + 20, len(sorted_dates))):
                d2 = sorted_dates[j]
                if all_scores[d2]["score"] < 50:
                    rapid_transitions.append({
                        "from_date": d,
                        "from_score": all_scores[d]["score"],
                        "to_date": d2,
                        "to_score": all_scores[d2]["score"],
                        "days": j - i,
                    })
                    break

    # ── Score distribution ───────────────────────────────────────────────
    bins   = list(range(0, 105, 5))
    hist   = [0] * (len(bins) - 1)
    for s in scores_list:
        for k in range(len(bins) - 1):
            if bins[k] <= s < bins[k+1]:
                hist[k] += 1
                break

    # ── Generate HTML ───────────────────────────────────────────────────
    html = generate_html(
        scores_list, score_states, hist, bins,
        critical_signals, strong_signals, crit_stats,
        rapid_transitions,
        long_win_rate_5d, short_win_rate_5d,
        avg_long_ret_5d, avg_short_ret_5d,
        long_returns_5d, short_returns_5d,
        max_dd, max_dd_date,
        drawdowns, spy_dates, start_idx,
    )

    out_path = OUTPUT_DIR / "trend_health_backtest_2020_2026.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✅ 报告已保存: {out_path}")
    print_summary(scores_list, score_states, crit_stats, rapid_transitions,
                  long_win_rate_5d, short_win_rate_5d, max_dd, max_dd_date)

    return out_path


def generate_html(scores_list, score_states, hist, bins,
                  critical_signals, strong_signals, crit_stats,
                  rapid_transitions, long_win_rate, short_win_rate,
                  avg_long_ret, avg_short_ret, long_returns, short_returns,
                  max_dd, max_dd_date, drawdowns, spy_dates, start_idx):

    avg_score  = np.mean(scores_list)
    median_score = np.median(scores_list)
    std_score  = np.std(scores_list)
    min_score  = np.min(scores_list)
    max_score  = np.max(scores_list)

    # Score distribution chart (SVG bar chart)
    max_hist = max(hist) if hist else 1
    bar_w = 12
    chart_height = 200
    chart_width  = len(hist) * (bar_w + 4)
    bars_svg = []
    for i, (count, lo) in enumerate(zip(hist, bins[:-1])):
        h_pct = count / max_hist
        bar_h = int(h_pct * chart_height)
        color = "#ef4444" if lo < 35 else "#f97316" if lo < 50 else "#eab308" if lo < 65 else "#22c55e" if lo < 80 else "#10b981"
        x = i * (bar_w + 4)
        y = chart_height - bar_h
        bars_svg.append(f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bar_h}" fill="{color}" rx="2"/>')
        if i % 4 == 0:
            bars_svg.append(f'<text x="{x}" y="{chart_height + 14}" text-anchor="middle" font-size="10" fill="#9ca3af">{lo}</text>')

    bars_svg_str = "\n    ".join(bars_svg)

    # Critical signals table rows
    crit_rows = []
    sorted_crit = sorted(critical_signals, key=lambda x: x["date"])
    for r in sorted_crit[:50]:  # top 50
        state_icon = "🚨" if r["score"] < 35 else "⚠️"
        ret5  = f'{r["ret_5d"]:.2f}%' if r["ret_5d"]  is not None else "N/A"
        ret20 = f'{r["ret_20d"]:.2f}%' if r["ret_20d"] is not None else "N/A"
        ret60 = f'{r["ret_60d"]:.2f}%' if r["ret_60d"] is not None else "N/A"
        ret5_color = "text-red-400" if r["ret_5d"] is not None and r["ret_5d"] < 0 else "text-green-400"
        crit_rows.append(f"""<tr class="border-b border-gray-800 hover:bg-gray-800/50">
            <td class="px-3 py-2 text-center">{state_icon}</td>
            <td class="px-3 py-2 text-blue-400">{r['date']}</td>
            <td class="px-3 py-2 text-red-400 font-bold">{r['score']:.1f}</td>
            <td class="px-3 py-2 {ret5_color}">{ret5}</td>
            <td class="px-3 py-2 {ret5_color}">{ret20}</td>
            <td class="px-3 py-2 {ret5_color}">{ret60}</td>
            <td class="px-3 py-2 text-gray-400">{r['state']}</td>
        </tr>""")

    # Rapid transition rows
    trans_rows = []
    for t in rapid_transitions[:30]:
        trans_rows.append(f"""<tr class="border-b border-gray-800 hover:bg-gray-800/50">
            <td class="px-3 py-2 text-green-400">{t['from_date']}</td>
            <td class="px-3 py-2 text-green-400 font-bold">{t['from_score']:.1f}</td>
            <td class="px-3 py-2">→</td>
            <td class="px-3 py-2 text-red-400">{t['to_date']}</td>
            <td class="px-3 py-2 text-red-400 font-bold">{t['to_score']:.1f}</td>
            <td class="px-3 py-2 text-yellow-400">{t['days']}天</td>
        </tr>""")

    # Score state table
    state_rows = []
    state_colors = {
        "强趋势(>80)": "bg-green-900/50 text-green-400",
        "健康调整(65-80)": "bg-emerald-900/50 text-emerald-400",
        "高波动分歧(50-65)": "bg-yellow-900/50 text-yellow-400",
        "趋势恶化(35-50)": "bg-orange-900/50 text-orange-400",
        "高概率变盘(<35)": "bg-red-900/50 text-red-400",
    }
    state_icons = {
        "强趋势(>80)": "🚀",
        "健康调整(65-80)": "🐂",
        "高波动分歧(50-65)": "⚠️",
        "趋势恶化(35-50)": "🐻",
        "高概率变盘(<35)": "🚨",
    }
    for state_name, recs in score_states.items():
        if not recs:
            continue
        avg_ret = np.nanmean([r["ret_5d"] for r in recs if r["ret_5d"] is not None])
        win_rate = sum(1 for r in recs if r["ret_5d"] is not None and r["ret_5d"] > 0) / max(1, len([r for r in recs if r["ret_5d"] is not None])) * 100
        state_rows.append(f"""<tr class="border-b border-gray-800">
            <td class="px-3 py-2 {state_colors[state_name]}">{state_icons[state_name]} {state_name}</td>
            <td class="px-3 py-2 text-center font-bold">{len(recs)}</td>
            <td class="px-3 py-2 text-center">{win_rate:.1f}%</td>
            <td class="px-3 py-2 text-center {'text-red-400' if avg_ret < 0 else 'text-green-400'}">{avg_ret:.2f}%</td>
            <td class="px-3 py-2 text-center">{len(recs)/len(scores_list)*100:.1f}%</td>
        </tr>""")

    # Timeline data for chart
    timeline_dates = spy_dates[start_idx:start_idx + len(scores_list)]
    timeline_json = []
    step = max(1, len(scores_list) // 300)
    for i in range(0, len(scores_list), step):
        timeline_json.append({"date": timeline_dates[i], "score": round(scores_list[i], 1)})

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>趋势健康度回测报告 2020-2026</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0f1117; color: #e5e7eb; font-family: 'Segoe UI', system-ui, sans-serif; font-size: 14px; }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
  h1 {{ color: #f9fafb; font-size: 1.5rem; font-weight: 700; margin-bottom: 6px; }}
  h2 {{ color: #d1d5db; font-size: 1.1rem; font-weight: 600; margin: 28px 0 12px; border-left: 3px solid #4b5563; padding-left: 10px; }}
  h3 {{ color: #9ca3af; font-size: 0.9rem; margin: 16px 0 8px; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; }}
  .grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }}
  .card {{ background: #1a1d27; border: 1px solid #2d3140; border-radius: 10px; padding: 16px; }}
  .card-num {{ font-size: 1.8rem; font-weight: 700; }}
  .card-label {{ font-size: 0.8rem; color: #9ca3af; margin-top: 4px; }}
  .text-green {{ color: #4ade80; }}
  .text-red   {{ color: #f87171; }}
  .text-yellow{{ color: #fbbf24; }}
  .text-blue  {{ color: #60a5fa; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #1f2937; color: #9ca3af; padding: 8px 12px; text-align: left; font-weight: 600; position: sticky; top: 0; }}
  td {{ padding: 8px 12px; }}
  .chart-wrap {{ background: #1a1d27; border: 1px solid #2d3140; border-radius: 10px; padding: 16px; margin: 12px 0; }}
  .tag-red    {{ background: rgba(239,68,68,0.15); color: #f87171; }}
  .tag-green  {{ background: rgba(34,197,94,0.15);  color: #4ade80; }}
  .tag-yellow {{ background: rgba(251,191,36,0.15); color: #fbbf24; }}
  .tag-blue   {{ background: rgba(96,165,250,0.15);  color: #60a5fa; }}
  .summary-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
  .kpi {{ background: #1a1d27; border: 1px solid #2d3140; border-radius: 10px; padding: 20px; text-align: center; }}
  .kpi-num {{ font-size: 2rem; font-weight: 700; }}
  .kpi-sub {{ font-size: 0.75rem; color: #9ca3af; margin-top: 4px; }}
  .section {{ background: #1a1d27; border: 1px solid #2d3140; border-radius: 10px; padding: 20px; margin-bottom: 20px; }}
  .table-scroll {{ max-height: 400px; overflow-y: auto; }}
  .table-scroll::-webkit-scrollbar {{ width: 6px; }}
  .table-scroll::-webkit-scrollbar-track {{ background: #1f2937; }}
  .table-scroll::-webkit-scrollbar-thumb {{ background: #4b5563; border-radius: 3px; }}
  .info-box {{ background: #1e3a5f; border: 1px solid #2563eb; border-radius: 8px; padding: 12px 16px; margin: 12px 0; font-size: 13px; line-height: 1.6; }}
  .warn-box {{ background: #3b1f1f; border: 1px solid #dc2626; border-radius: 8px; padding: 12px 16px; margin: 12px 0; font-size: 13px; }}
  .stat-row {{ display: flex; gap: 24px; flex-wrap: wrap; margin: 8px 0; }}
  .stat-item {{ display: flex; gap: 8px; align-items: baseline; }}
  .stat-label {{ color: #9ca3af; font-size: 13px; }}
  .stat-val {{ font-weight: 600; font-size: 15px; }}
</style>
</head>
<body>
<div class="container">

  <h1>📊 趋势健康度评分系统回测报告</h1>
  <p style="color:#9ca3af; font-size:13px;">回测区间：2020-01-01 — 2026-05-11 &nbsp;|&nbsp; 数据来源：富途 OpenD K线 &nbsp;|&nbsp; 采样：全交易日</p>

  <h2>一、总体统计</h2>
  <div class="summary-grid">
    <div class="kpi">
      <div class="kpi-num text-blue">{avg_score:.1f}</div>
      <div class="kpi-sub">平均评分</div>
    </div>
    <div class="kpi">
      <div class="kpi-num text-yellow">{median_score:.1f}</div>
      <div class="kpi-sub">中位数评分</div>
    </div>
    <div class="kpi">
      <div class="kpi-num text-blue">{std_score:.1f}</div>
      <div class="kpi-sub">标准差</div>
    </div>
    <div class="kpi">
      <div class="kpi-num text-red">{min_score:.1f}</div>
      <div class="kpi-sub">最低分</div>
    </div>
    <div class="kpi">
      <div class="kpi-num text-green">{max_score:.1f}</div>
      <div class="kpi-sub">最高分</div>
    </div>
    <div class="kpi">
      <div class="kpi-num text-red">{max_dd:.1f}%</div>
      <div class="kpi-sub">最大回撤 ({max_dd_date})</div>
    </div>
  </div>

  <h2>二、评分分布</h2>
  <div class="section">
    <table>
      <tr>
        <th>状态区间</th>
        <th>天数</th>
        <th>5日胜率（上涨%）</th>
        <th>平均5日收益</th>
        <th>占比</th>
      </tr>
      {''.join(state_rows)}
    </table>
  </div>

  <h2>三、评分分布直方图</h2>
  <div class="chart-wrap">
    <svg viewBox="0 0 {chart_width} {chart_height + 24}" width="100%" height="{chart_height + 24}">
      {bars_svg_str}
      <line x1="0" y1="{chart_height}" x2="{chart_width}" y2="{chart_height}" stroke="#374151" stroke-width="1"/>
    </svg>
    <p style="font-size:12px; color:#6b7280; margin-top:8px;">
      <span style="color:#10b981">■</span> 强趋势 &nbsp;
      <span style="color:#22c55e">■</span> 健康调整 &nbsp;
      <span style="color:#eab308">■</span> 高波动分歧 &nbsp;
      <span style="color:#f97316">■</span> 趋势恶化 &nbsp;
      <span style="color:#ef4444">■</span> 高概率变盘
    </p>
  </div>

  <h2>四、评分时间序列（可缩放）</h2>
  <div class="chart-wrap">
    <canvas id="timelineChart" height="80"></canvas>
  </div>

  <h2>五、高概率变盘信号（评分 &lt; 35）</h2>
  <div class="info-box">
    🚨 共识别 <strong>{crit_stats['count']}</strong> 个高概率变盘信号。
    5日后平均收益 <strong class="{'text-green' if crit_stats['ret_5d_avg'] >= 0 else 'text-red'}">{crit_stats['ret_5d_avg']:.2f}%</strong>，
    20日 <strong class="{'text-green' if crit_stats['ret_20d_avg'] >= 0 else 'text-red'}">{crit_stats['ret_20d_avg']:.2f}%</strong>，
    60日 <strong class="{'text-green' if crit_stats['ret_60d_avg'] >= 0 else 'text-red'}">{crit_stats['ret_60d_avg']:.2f}%</strong>。
    5日正向概率 {crit_stats['ret_5d_pos']:.1f}%，负向概率 {crit_stats['ret_5d_neg']:.1f}%。
  </div>
  <div class="section">
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th></th>
            <th>日期</th>
            <th>评分</th>
            <th>5日收益</th>
            <th>20日收益</th>
            <th>60日收益</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>{''.join(crit_rows)}</tbody>
      </table>
    </div>
  </div>

  <h2>六、强趋势信号（评分 &gt; 80）</h2>
  <div class="section">
    <p class="mb-3">共 <strong>{len(strong_signals)}</strong> 个强趋势信号。评分&gt;80后5日平均收益: <strong class="{'text-green' if avg_long_ret >= 0 else 'text-red'}">{avg_long_ret:.2f}%</strong>，胜率 {long_win_rate:.1f}%</p>
    <div class="table-scroll">
      <table>
        <thead>
          <tr><th>日期</th><th>评分</th><th>5日收益</th><th>20日收益</th><th>60日收益</th><th>状态</th></tr>
        </thead>
        <tbody>
          {''.join(f"""<tr class="border-b border-gray-800 hover:bg-gray-800/50">
            <td class="px-3 py-2 text-green-400">🚀 {r['date']}</td>
            <td class="px-3 py-2 text-green-400 font-bold">{r['score']:.1f}</td>
            <td class="px-3 py-2 {'text-red-400' if r['ret_5d'] is not None and r['ret_5d'] < 0 else 'text-green-400'}">{f"{r['ret_5d']:.2f}%" if r['ret_5d'] is not None else "N/A"}</td>
            <td class="px-3 py-2 {'text-red-400' if r['ret_20d'] is not None and r['ret_20d'] < 0 else 'text-green-400'}">{f"{r['ret_20d']:.2f}%" if r['ret_20d'] is not None else "N/A"}</td>
            <td class="px-3 py-2 {'text-red-400' if r['ret_60d'] is not None and r['ret_60d'] < 0 else 'text-green-400'}">{f"{r['ret_60d']:.2f}%" if r['ret_60d'] is not None else "N/A"}</td>
            <td class="px-3 py-2 text-gray-400">{r['state']}</td>
          </tr>""" for r in sorted(strong_signals, key=lambda x: x['date'])[:40])}
        </tbody>
      </table>
    </div>
  </div>

  <h2>七、急速转势信号（从&gt;80跌至&lt;50，20日内）</h2>
  <div class="warn-box">
    ⚠️ 识别 <strong>{len(rapid_transitions)}</strong> 次急速转势。强趋势后快速恶化往往是市场大幅回调的前兆。
  </div>
  <div class="section">
    <div class="table-scroll">
      <table>
        <thead>
          <tr><th>强趋势日</th><th>评分</th><th></th><th>变盘日</th><th>评分</th><th>间隔天数</th></tr>
        </thead>
        <tbody>{''.join(trans_rows)}</tbody>
      </table>
    </div>
  </div>

  <h2>八、策略绩效总结</h2>
  <div class="grid-4">
    <div class="card">
      <div class="card-num text-green">{long_win_rate:.1f}%</div>
      <div class="card-label">强趋势(>80)做多 5日胜率</div>
    </div>
    <div class="card">
      <div class="card-num {'text-green' if avg_long_ret >= 0 else 'text-red'}">{avg_long_ret:.2f}%</div>
      <div class="card-label">强趋势做多 平均5日收益</div>
    </div>
    <div class="card">
      <div class="card-num text-yellow">{short_win_rate:.1f}%</div>
      <div class="card-label">趋势恶化(&lt;50)做空 5日胜率</div>
    </div>
    <div class="card">
      <div class="card-num {'text-green' if avg_short_ret <= 0 else 'text-red'}">{avg_short_ret:.2f}%</div>
      <div class="card-label">趋势恶化做空 平均5日收益</div>
    </div>
  </div>

  <h2>九、关键发现摘要</h2>
  <div class="section">
    <ul style="line-height:2; padding-left:20px; font-size:13px;">
      <li>回测区间 {len(scores_list)} 个交易日中，评分主要集中在 <strong>60-80</strong> 区间（{len(score_states.get('健康调整(65-80)',[]))/len(scores_list)*100:.1f}%），美股整体呈长期多头格局。</li>
      <li>高概率变盘信号（&lt;35）共 <strong>{crit_stats['count']}</strong> 个，5日后平均收益 <strong class="{'text-green' if crit_stats['ret_5d_avg'] >= 0 else 'text-red'}">{crit_stats['ret_5d_avg']:.2f}%</strong>，提示该信号对市场短期顶部有一定领先性。</li>
      <li>强趋势信号（&gt;80）做多 5日胜率 <strong>{long_win_rate:.1f}%</strong>，平均收益 <strong>{avg_long_ret:.2f}%</strong>。</li>
      <li>急速转势（20日内从&gt;80跌至&lt;50）共 <strong>{len(rapid_transitions)}</strong> 次，是重要的风险预警信号。</li>
      <li>评分最大单次回撤 {max_dd:.1f}%（{max_dd_date}），反映系统自身的波动性。</li>
    </ul>
  </div>

  <p style="text-align:center; color:#4b5563; font-size:12px; margin-top:32px; padding-bottom:24px;">
    生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')} &nbsp;|&nbsp; Trend Health Backtest 2020-2026
  </p>
</div>

<script>
const timelineData = {json.dumps(timeline_json, ensure_ascii=False)};

const ctx = document.getElementById('timelineChart').getContext('2d');
const labels = timelineData.map(d => d.date);
const scores = timelineData.map(d => d.score);

const bgColors = scores.map(s =>
  s > 80 ? 'rgba(34,197,94,0.8)' :
  s >= 65 ? 'rgba(16,185,129,0.6)' :
  s >= 50 ? 'rgba(234,179,8,0.6)' :
  s >= 35 ? 'rgba(249,115,22,0.6)' :
  'rgba(239,68,68,0.8)'
);

new Chart(ctx, {{
  type: 'line',
  data: {{
    labels: labels,
    datasets: [{{
      label: '趋势健康度评分',
      data: scores,
      borderColor: 'rgba(96,165,250,0.8)',
      backgroundColor: bgColors,
      pointRadius: 2,
      pointHoverRadius: 5,
      borderWidth: 1,
      fill: false,
      tension: 0.1,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: false }},
      zoom: {{
        zoom: {{
          wheel: {{ enabled: true }},
          pinch: {{ enabled: true }},
          mode: 'x',
        }},
        pan: {{ enabled: true, mode: 'x' }},
        reset: {{ enabled: true }},
      }},
      tooltip: {{
        callbacks: {{
          label: ctx => `评分: ${{ctx.parsed.y}}`,
        }}
      }}
    }},
    scales: {{
      x: {{
        ticks: {{ color: '#6b7280', maxTicksLimit: 20, font: {{ size: 10 }} }},
        grid: {{ color: '#1f2937' }},
      }},
      y: {{
        min: 0, max: 100,
        ticks: {{ color: '#6b7280', stepSize: 20 }},
        grid: {{ color: '#1f2937' }},
        annotations: {{
          line1: {{ type: 'line', yMin: 80, yMax: 80, borderColor: '#4ade80', borderWidth: 1, borderDash: [4,4] }},
          line2: {{ type: 'line', yMin: 65, yMax: 65, borderColor: '#16a34a', borderWidth: 1, borderDash: [4,4] }},
          line3: {{ type: 'line', yMin: 50, yMax: 50, borderColor: '#eab308', borderWidth: 1, borderDash: [4,4] }},
          line4: {{ type: 'line', yMin: 35, yMax: 35, borderColor: '#f97316', borderWidth: 1, borderDash: [4,4] }},
        }}
      }}
    }}
  }}
}});
</script>
</body>
</html>"""


def print_summary(scores_list, score_states, crit_stats, rapid_transitions,
                  long_win_rate, short_win_rate, max_dd, max_dd_date):
    print("\n" + "=" * 60)
    print("📊 回测摘要")
    print("=" * 60)
    print(f"  总交易日: {len(scores_list)}")
    print(f"  平均评分: {np.mean(scores_list):.1f}  |  中位数: {np.median(scores_list):.1f}")
    print(f"  评分范围: {np.min(scores_list):.1f} ~ {np.max(scores_list):.1f}")
    print(f"  最大回撤: {max_dd:.1f}% ({max_dd_date})")
    print()
    print("  状态分布:")
    for state, recs in score_states.items():
        if recs:
            avg_ret = np.nanmean([r["ret_5d"] for r in recs if r["ret_5d"] is not None])
            wr = sum(1 for r in recs if r["ret_5d"] is not None and r["ret_5d"] > 0) / max(1, len([r for r in recs if r["ret_5d"] is not None])) * 100
            print(f"    {state}: {len(recs)}天 | 5日胜率{wr:.0f}% | 均收益{avg_ret:+.2f}%")
    print()
    print(f"  🚨 高概率变盘(<35): {crit_stats['count']}次 | 5日均收益{crit_stats['ret_5d_avg']:+.2f}% | 20日{crit_stats['ret_20d_avg']:+.2f}%")
    print(f"  🚀 强趋势(>80)做多: 5日胜率{long_win_rate:.1f}% | 均收益{np.mean([r for r in scores_list if r > 80]):.2f}%")
    print(f"  ⚠️  急速转势(<20日): {len(rapid_transitions)}次")


if __name__ == "__main__":
    run_backtest()
