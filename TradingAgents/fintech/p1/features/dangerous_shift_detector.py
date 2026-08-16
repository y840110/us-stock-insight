#!/usr/bin/env python3
"""
P1 · 危险变盘检测器（Dangerous Shift Detector）
==============================================
检测规则：5个条件越多满足越危险，用于识别真正的市场变盘点。

危险等级：
  SEVERE  — 4~5个条件满足（立即清仓意识）
  WARNING — 2~3个条件满足（高度警惕）
  WATCH   — 1个条件满足（观察）
  SAFE    — 0个条件满足

5个条件：
  1. Breadth崩塌：Above20EMA < 40%
  2. VIX持续抬升：VIX > 25 且5日内无明显回落
  3. 高Beta先崩：N日内高Beta股跌幅 > 低Beta股
  4. 反弹无量：下跌波段成交量 > 反弹波段成交量（主力出货特征）
  5. 跌破AVWAP：收盘价 < AVWAP（尤其财报后）

数据来源：
  - K线：中间过程/klines/{CODE}_1d.json
  - VIX：VIX_1d.json
  - 广度：sp500_breadth_finviz.json / breadth_history.json
  - 高Beta股池：fintech/stock_pool.json（按Beta排序取头部/尾部）
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

# ── 路径配置 ───────────────────────────────────────────────────────────────
PROJ_DIR   = Path(__file__).parent.parent.parent.parent
KLINES_DIR = PROJ_DIR / "中间过程" / "klines"
STATE_DIR  = PROJ_DIR / "fintech" / "p1" / "state"
POOL_FILE  = PROJ_DIR / "fintech" / "stock_pool.json"

# ── K线加载 ────────────────────────────────────────────────────────────────

def load_klines(code: str) -> Optional[dict]:
    """加载日K数据，兼容 vol/volume 字段名"""
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
                    "lows":    [b["low"] for b in bars],
                    "volumes": [b.get("volume") or b.get("vol", 0) for b in bars],
                    "last_date": bars[-1]["date"],
                }
            except Exception:
                return None
    return None


def ema_(closes: list, period: int) -> list:
    """简单 EMA"""
    if len(closes) < period:
        return [sum(closes)/len(closes)] * len(closes) if closes else []
    sma = sum(closes[:period]) / period
    k = 2.0 / (period + 1)
    result = [None] * (period - 1)
    result.append(sma)
    for i in range(period, len(closes)):
        result.append(closes[i] * k + result[-1] * (1 - k))
    return result


def load_vix() -> Optional[float]:
    """最新 VIX 收盘价"""
    fpath = KLINES_DIR / "VIX_1d.json"
    if not fpath.exists():
        return None
    try:
        bars = json.load(open(fpath)).get("data", [])
        return bars[-1]["close"] if bars else None
    except Exception:
        return None


def load_breadth() -> dict:
    """加载广度数据 + 估算 Above20EMA"""
    fpath = KLINES_DIR / "sp500_breadth_finviz.json"
    if not fpath.exists():
        return {"above_sma20": 0.5, "above_sma50": 0.5}
    try:
        raw = json.load(open(fpath))
        above_50 = raw.get("above_sma50", 0.5)
        above_20 = 1.0 - ((1.0 - above_50) ** 1.3)
        return {
            "above_sma20": round(above_20, 4),
            "above_sma50": raw.get("above_sma50"),
            "above_sma200": raw.get("above_sma200"),
            "date": raw.get("date"),
        }
    except Exception:
        return {"above_sma20": 0.5}


# ── 条件1：Breadth 崩塌 ─────────────────────────────────────────────────

def check_c1_breadth_collapse(breadth_data: dict, threshold: float = 0.40) -> dict:
    """
    Above20EMA < 40% = Breadth 崩塌
    """
    above_20 = breadth_data.get("above_sma20", 0.5)
    ok = above_20 < threshold
    return {
        "ok": ok,
        "above_sma20": round(above_20, 4),
        "threshold": threshold,
        "reason": f"Above20EMA {above_20:.1%} < {threshold:.1%} 崩塌"
                  if ok else f"Above20EMA {above_20:.1%} ≥ {threshold:.1%}",
    }


# ── 条件2：VIX 持续抬升 ────────────────────────────────────────────────

def check_c2_vix_sustained_rise(vix_data: list, threshold: float = 25.0,
                                 lookback: int = 10) -> dict:
    """
    VIX > 25 且 5日内无明显回落（当前VIX > 5日前VIX）
    """
    if not vix_data or len(vix_data) < 5:
        return {"ok": False, "vix_current": None,
                "vix_5d_ago": None, "reason": "数据不足"}

    current = vix_data[-1]["close"]
    ago_5   = vix_data[-min(5, len(vix_data))]["close"]
    ago_10  = vix_data[-min(lookback, len(vix_data))]["close"] if len(vix_data) >= lookback else None

    above_threshold = current > threshold
    not_retreating  = current >= ago_5   # 未回落
    rising_trend    = (ago_10 and current > ago_10) if ago_10 else False

    ok = above_threshold and not_retreating

    return {
        "ok": ok,
        "vix_current": round(current, 2),
        "vix_5d_ago": round(ago_5, 2),
        "vix_10d_ago": round(ago_10, 2) if ago_10 else None,
        "above_threshold": above_threshold,
        "not_retreating": not_retreating,
        "rising_trend": rising_trend,
        "threshold": threshold,
        "reason": (f"VIX={current:.1f}>{threshold} 且未回落（5日前{ago_5:.1f}）"
                   if ok else f"VIX={current:.1f} {'≤'+str(threshold) if not above_threshold else '已回落'}"),
    }


# ── 条件3：高Beta先崩 ─────────────────────────────────────────────────

def load_stock_pool() -> list[dict]:
    """加载股票池"""
    if not POOL_FILE.exists():
        return []
    try:
        d = json.load(open(POOL_FILE))
        return d.get("stocks", [])
    except Exception:
        return []


def calc_stock_beta(closes: list) -> Optional[float]:
    """用日收益率计算简单Beta（市场 Beta=1）"""
    if len(closes) < 30:
        return None
    # 用spy做市场代理
    spy = load_klines("SPY")
    if not spy or len(spy["closes"]) < 30:
        return None
    # 对齐长度
    min_len = min(len(closes), len(spy["closes"]))
    c = closes[-min_len:]
    s = spy["closes"][-min_len:]
    # 日收益率
    rets_c = [(c[i]/c[i-1]-1) for i in range(1, min_len)]
    rets_s = [(s[i]/s[i-1]-1) for i in range(1, min_len)]
    if len(rets_c) < 20:
        return None
    mean_c = sum(rets_c) / len(rets_c)
    mean_s = sum(rets_s) / len(rets_s)
    cov = sum((rets_c[i]-mean_c)*(rets_s[i]-mean_s) for i in range(len(rets_c))) / len(rets_c)
    var_s = sum((r-mean_s)**2 for r in rets_s) / len(rets_s)
    if var_s == 0:
        return None
    return cov / var_s


def check_c3_highbeta_crash(lookback: int = 20) -> dict:
    """
    高Beta股（Beta>1.2）N日累计跌幅 > 低Beta股（Beta<0.8）累计跌幅。
    从股票池取有数据的股票，实时计算Beta后排序比较。
    """
    pool = load_stock_pool()
    if not pool:
        return {"ok": False, "reason": "无股票池数据"}

    # 实时计算每只股票的Beta
    stocks_with_beta = []
    for stk in pool[:80]:   # 最多检查前80只（避免太慢）
        klines = load_klines(stk["code"])
        if not klines or len(klines["closes"]) < lookback + 5:
            continue
        beta = calc_stock_beta(klines["closes"])
        if beta is None:
            continue
        price_chg = (klines["closes"][-1] / klines["closes"][-lookback] - 1) * 100
        stocks_with_beta.append({
            "code": stk["code"],
            "beta": round(beta, 2),
            "chg": round(price_chg, 2),
        })

    if len(stocks_with_beta) < 10:
        return {"ok": False, "reason": f"有效股票不足（{len(stocks_with_beta)}只，需要≥10）"}

    # 按Beta排序
    sorted_by_beta = sorted(stocks_with_beta, key=lambda x: x["beta"], reverse=True)
    high_beta = sorted_by_beta[:5]   # Beta最高的5只
    low_beta  = sorted_by_beta[-5:]  # Beta最低的5只

    avg_high_chg = sum(s["chg"] for s in high_beta) / len(high_beta)
    avg_low_chg  = sum(s["chg"] for s in low_beta) / len(low_beta)

    # 高Beta股跌幅更大（更负）= 危险
    # 前提：市场本身在跌（SPY近N日走弱），高Beta才真正"领跌"
    # 如果市场本身在涨，低Beta补涨是正常轮动，不算危险
    spy = load_klines("SPY")
    spy_chg = 0.0
    if spy and len(spy["closes"]) >= lookback:
        spy_chg = (spy["closes"][-1] / spy["closes"][-lookback] - 1) * 100

    high_worse = avg_high_chg < avg_low_chg
    gap = avg_low_chg - avg_high_chg
    # 危险信号：SPY在跌（或涨幅很小）+ 高Beta涨幅 < 低Beta涨幅
    ok = (spy_chg < 3.0) and high_worse and gap > 3.0

    return {
        "ok": ok,
        "high_beta_stocks": high_beta,
        "low_beta_stocks": low_beta,
        "avg_high_beta_chg": round(avg_high_chg, 2),
        "avg_low_beta_chg": round(avg_low_chg, 2),
        "gap": round(gap, 2),
        "reason": (f"高Beta均{avg_high_chg:+.1f}% vs 低Beta均{avg_low_chg:+.1f}%，差{gap:.1f}%，高Beta领跌"
                   if ok else f"高Beta均{avg_high_chg:+.1f}% vs 低Beta均{avg_low_chg:+.1f}%，差距不足{gap:.1f}%")
    }


# ── 条件4：反弹无量（最关键）────────────────────────────────────────────

def find_rebound_period(closes: list, volumes: list, lookback: int = 60) -> Optional[dict]:
    """
    识别最近一次"下跌+反弹"波段。
    找N日内的局部高点→局部低点（下跌），然后反弹。
    返回下跌段和反弹段。
    """
    if len(closes) < 30:
        return None

    # 简单方法：找最近一次显著下跌后的反弹
    # 从lookback天内：
    # 1. 找到全局高点（作为下跌起点）
    # 2. 找到高点之后的最低点（作为反弹起点）
    # 3. 反弹 = 最低点到当前

    recent_closes = closes[-lookback:]
    recent_vols   = volumes[-lookback:]

    # 全局高点索引
    peak_idx = recent_closes.index(max(recent_closes))

    if peak_idx >= len(recent_closes) - 5:
        # 高点在末尾附近，还没跌完或没反弹
        return None

    # 高点之后的部分
    post_peak_c = recent_closes[peak_idx:]
    post_peak_v = recent_vols[peak_idx:]

    # 局部最低点（反弹起点）
    trough_idx_in_pp = post_peak_c.index(min(post_peak_c))
    trough_abs_idx   = peak_idx + trough_idx_in_pp

    # 反弹段（从最低点到末尾）
    rebound_c = closes[trough_abs_idx:]
    rebound_v = volumes[trough_abs_idx:]

    # 下跌段（从高点到最低点）
    decline_c = closes[peak_idx:trough_abs_idx+1]
    decline_v = volumes[peak_idx:trough_abs_idx+1]

    if len(decline_c) < 5 or len(rebound_c) < 3:
        return None

    decline_pct = (min(decline_c)/max(decline_c) - 1) * 100 if max(decline_c) > 0 else 0
    rebound_pct  = (rebound_c[-1]/min(rebound_c) - 1) * 100 if min(rebound_c) > 0 else 0

    return {
        "peak_date_idx":   len(closes) - len(recent_closes) + peak_idx,
        "trough_date_idx": len(closes) - len(recent_closes) + trough_abs_idx,
        "decline_days":    len(decline_c),
        "decline_pct":     round(decline_pct, 2),
        "decline_vol_avg": round(sum(decline_v)/len(decline_v)),
        "rebound_days":    len(rebound_c),
        "rebound_pct":     round(rebound_pct, 2),
        "rebound_vol_avg": round(sum(rebound_v)/len(rebound_v)),
    }


def check_c4_weak_rebound(code: str = "SPY") -> dict:
    """
    反弹无量：下跌段均量 > 反弹段均量（主力出货特征）
    """
    klines = load_klines(code)
    if not klines or len(klines["closes"]) < 30:
        return {"ok": False, "reason": f"无{code}数据"}

    rb = find_rebound_period(klines["closes"], klines["volumes"])
    if not rb:
        return {"ok": False, "reason": "未识别到明显下跌+反弹波段", "data": None}

    dv = rb["decline_vol_avg"]
    rv = rb["rebound_vol_avg"]

    # 危险信号：下跌量 > 反弹量
    ok = dv > rv * 1.2   # 下跌量比反弹量多20%以上

    return {
        "ok": ok,
        "code": code,
        "decline_vol_avg": dv,
        "rebound_vol_avg": rv,
        "vol_ratio": round(dv/rv, 2) if rv > 0 else None,
        "decline_days": rb["decline_days"],
        "rebound_days": rb["rebound_days"],
        "decline_pct": rb["decline_pct"],
        "rebound_pct": rb["rebound_pct"],
        "reason": (f"下跌均量{dv:,} > 反弹均量{rv:,}（{dv/rv:.1f}x，主力出货）"
                   if ok else f"下跌均量{dv:,} {'≤' if dv<=rv else '>'}反弹均量{rv:,}，量价正常"),
        "data": rb,
    }


# ── 条件5：跌破AVWAP ──────────────────────────────────────────────────

def calc_avwap(closes: list, volumes: list, anchor_idx: int = 0) -> Optional[float]:
    """
    Anchored VWAP：从 anchor_idx 起到最新，所有交易日的价格×成交量累加 / 成交量累加。
    anchor_idx=0 = 从头算起；anchor_idx=N = 从第N天开始算。
    """
    if anchor_idx >= len(closes) or len(closes) != len(volumes):
        return None
    total_pv = sum(closes[i] * volumes[i] for i in range(anchor_idx, len(closes)) if volumes[i] > 0)
    total_vol = sum(volumes[i] for i in range(anchor_idx, len(closes)) if volumes[i] > 0)
    if total_vol == 0:
        return None
    return total_pv / total_vol


def check_c5_avwap_break(code: str = "SPY", lookback: int = 60) -> dict:
    """
    价格跌破 AVWAP（尤其财报后）。
    简化：取 anchor_idx = lookback起点，看当前价格是否 < 该AVWAP。
    如果当前价 < AVWAP = 在平均成本以下运行 = 弱。
    """
    klines = load_klines(code)
    if not klines or len(klines["closes"]) < 10:
        return {"ok": False, "reason": f"无{code}数据"}

    closes  = klines["closes"]
    volumes = klines["volumes"]

    # AVWAP 锚点：lookback天前
    anchor_idx = max(0, len(closes) - lookback)
    avwap = calc_avwap(closes, volumes, anchor_idx)
    if avwap is None:
        return {"ok": False, "reason": "AVWAP计算失败"}

    current = closes[-1]
    avwap_5d_ago = calc_avwap(closes[:-5], [v for v in volumes[:-5]], anchor_idx) if len(closes) > 5 else avwap

    below = current < avwap
    # 确认跌破且没有快速收复
    confirmed = below and (avwap_5d_ago is None or current < avwap_5d_ago * 0.98)

    return {
        "ok": confirmed,
        "code": code,
        "current": round(current, 2),
        "avwap": round(avwap, 2),
        "avwap_anchor": f"{lookback}日前",
        "distance_pct": round((current/avwap - 1)*100, 2) if avwap > 0 else 0,
        "below_avwap": below,
        "reason": (f"{code}={current:.1f} < AVWAP={avwap:.1f}（-{abs((current/avwap-1)*100):.1f}%）"
                   if below else f"{code}={current:.1f} ≥ AVWAP={avwap:.1f}"),
    }


# ── 主检测函数 ─────────────────────────────────────────────────────────────

def detect_dangerous_shift() -> dict:
    """
    综合检测：当前市场是否处于危险变盘状态。
    返回：危险等级 + 各条件详情
    """
    breadth = load_breadth()
    vix_bars = []
    fpath = KLINES_DIR / "VIX_1d.json"
    if fpath.exists():
        try:
            vix_bars = json.load(open(fpath)).get("data", [])
        except Exception:
            pass

    # 条件1
    c1 = check_c1_breadth_collapse(breadth)

    # 条件2
    c2 = check_c2_vix_sustained_rise(vix_bars)

    # 条件3
    c3 = check_c3_highbeta_crash()

    # 条件4
    c4_spy = check_c4_weak_rebound("SPY")
    c4_qqq = check_c4_weak_rebound("QQQ")
    c4 = c4_spy   # 主要看SPY

    # 条件5
    c5_spy = check_c5_avwap_break("SPY")
    c5_qqq = check_c5_avwap_break("QQQ")
    c5 = c5_spy

    checks = {
        "c1_breadth_collapse": c1,
        "c2_vix_sustained_rise": c2,
        "c3_highbeta_crash": c3,
        "c4_weak_rebound": c4,
        "c5_avwap_break": c5,
    }

    # 危险计数
    danger_count = sum(1 for c in [c1, c2, c3, c4, c5] if c.get("ok"))

    if danger_count >= 4:
        signal = "SEVERE"
    elif danger_count >= 2:
        signal = "WARNING"
    elif danger_count >= 1:
        signal = "WATCH"
    else:
        signal = "SAFE"

    return {
        "date": str(date.today()),
        "signal": signal,
        "danger_count": danger_count,
        "checks": checks,
        "breadth_data": breadth,
        "vix_current": vix_bars[-1]["close"] if vix_bars else None,
    }


def save_dangerous_shift_state(result: dict) -> None:
    """保存结果到 state 目录"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fpath = STATE_DIR / "dangerous_shift_state.json"
    with open(fpath, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)


def get_dangerous_shift_state() -> dict | None:
    """读取最新状态（当日有效）"""
    fpath = STATE_DIR / "dangerous_shift_state.json"
    if not fpath.exists():
        return None
    try:
        d = json.load(open(fpath))
        return d if d.get("date") == str(date.today()) else None
    except Exception:
        return None


# ── 入口 ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = detect_dangerous_shift()
    save_dangerous_shift_state(result)

    sig  = result["signal"]
    dc   = result["danger_count"]
    ch   = result["checks"]

    sig_icon = {"SAFE": "✅", "WATCH": "👁", "WARNING": "⚠️", "SEVERE": "🚨"}[sig]
    print(f"\n[危险变盘] 信号: {sig_icon} {sig} ({dc}/5个条件)")
    print(f"  条件1 Breadth崩塌:   {'🚨' if ch['c1_breadth_collapse']['ok'] else '✅'} "
          f"{ch['c1_breadth_collapse'].get('reason','')}")
    print(f"  条件2 VIX持续抬升:   {'🚨' if ch['c2_vix_sustained_rise']['ok'] else '✅'} "
          f"{ch['c2_vix_sustained_rise'].get('reason','')}")
    print(f"  条件3 高Beta先崩:   {'🚨' if ch['c3_highbeta_crash']['ok'] else '✅'} "
          f"{ch['c3_highbeta_crash'].get('reason','')}")
    print(f"  条件4 反弹无量:       {'🚨' if ch['c4_weak_rebound']['ok'] else '✅'} "
          f"{ch['c4_weak_rebound'].get('reason','')}")
    print(f"  条件5 跌破AVWAP:     {'🚨' if ch['c5_avwap_break']['ok'] else '✅'} "
          f"{ch['c5_avwap_break'].get('reason','')}")
    print()
    print(json.dumps(result, indent=2, ensure_ascii=False))
