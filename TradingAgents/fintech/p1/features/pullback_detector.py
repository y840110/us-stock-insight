#!/usr/bin/env python3
"""
P1 · 健康回踩检测器（Healthy Pullback Detector）
================================================
检测规则：上涨趋势中的健康回踩（5个条件必须同时满足）

条件：
  1. 回调缩量：下跌成交量 < 上涨成交量
  2. Breadth没崩：Above20EMA > 55%
  3. VIX上升有限：VIX < 25
  4. 龙头没崩：NVDA/META/MSFT 没有放量破结构
  5. 资金回流快：回踩后1-3日内重新站回关键EMA

数据来源：
  - K线：中间过程/klines/
  - VIX：^VIX 日K
  - 广度：breadth_history.json
  - 龙头股：NVDA / META / MSFT 日K

输出：
  - is_healthy_pullback: bool
  - 信号等级：HEALTHY / WARNING / NO_PULLBACK
  - 各条件明细
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

LEADERS = ["NVDA", "MSFT", "AAPL"]   # 龙头股名单（数据池中有）

# ── K线加载 ────────────────────────────────────────────────────────────────

def load_stock_klines(code: str) -> Optional[dict]:
    """加载单只股票日K，code 不带后缀如 'NVDA'"""
    for suffix in ("_1d.json", ".json"):
        fpath = KLINES_DIR / f"{code}{suffix}"
        if fpath.exists():
            try:
                with open(fpath) as f:
                    d = json.load(f)
                if "data" in d:
                    bars = d["data"]
                elif isinstance(d, list):
                    bars = d
                else:
                    bars = d.get("data", [])
                if not bars:
                    return None
                closes  = [b["close"] for b in bars]
                volumes = [b.get("volume") or b.get("vol", 0) for b in bars]
                highs   = [b["high"]  for b in bars]
                lows    = [b["low"]   for b in bars]
                dates   = [b["date"]  for b in bars]
                return {"dates": dates, "closes": closes, "volumes": volumes,
                        "highs": highs, "lows": lows, "last_date": dates[-1]}
            except Exception:
                return None
    return None


def load_vix() -> Optional[float]:
    """加载最新 VIX 收盘价"""
    fpath = KLINES_DIR / "VIX_1d.json"
    if not fpath.exists():
        return None
    try:
        with open(fpath) as f:
            d = json.load(f)
        bars = d.get("data", [])
        if not bars:
            return None
        return bars[-1]["close"]
    except Exception:
        return None


def load_breadth() -> dict:
    """加载最新广度 Above20EMA 估算值"""
    try:
        fpath = KLINES_DIR / "sp500_breadth_finviz.json"
        if fpath.exists():
            with open(fpath) as f:
                raw = json.load(f)
            above_50 = raw.get("above_sma50", 0.5)
            # 估算 Above20EMA
            above_20 = 1.0 - ((1.0 - above_50) ** 1.3)
            return {
                "above_sma20": round(above_20, 4),
                "above_sma50": raw.get("above_sma50"),
                "above_sma200": raw.get("above_sma200"),
                "date": raw.get("date"),
            }
    except Exception:
        pass
    return {"above_sma20": 0.5}


def ema_(closes: list, period: int) -> list:
    """简单 EMA（SMA 起点 + 指数平滑）"""
    if len(closes) < period:
        return [sum(closes)/len(closes)] * len(closes) if closes else []
    sma = sum(closes[:period]) / period
    k = 2.0 / (period + 1)
    result = [None] * (period - 1)
    result.append(sma)
    for i in range(period, len(closes)):
        ema = closes[i] * k + result[-1] * (1 - k)
        result.append(ema)
    return result


# ── 条件1：回调缩量 ────────────────────────────────────────────────────────

def check_volume_pullback(closes: list, volumes: list) -> dict:
    """
    判断近期是否为缩量回调。
    逻辑：最近5日 vs 前5日，看成交量是否收缩。
    同时判断价格：回调幅度有限（<15%以内）
    """
    if len(closes) < 10 or len(volumes) < 10:
        return {"ok": False, "reason": "数据不足", "recent_vol_avg": None,
                "prior_vol_avg": None, "price_pullback": None}

    # 缩量：最近5日均量 < 前5日均量
    recent_vol = sum(volumes[-5:]) / 5
    prior_vol  = sum(volumes[-10:-5]) / 5
    vol_ratio  = recent_vol / prior_vol if prior_vol > 0 else 1.0

    # 价格回撤幅度（从近期高点计算）
    recent_closes = closes[-5:]
    peak = max(recent_closes)
    current = closes[-1]
    pullback_pct = (peak - current) / peak * 100 if peak > 0 else 0.0

    ok = vol_ratio < 0.85 and pullback_pct < 15.0

    return {
        "ok": ok,
        "recent_vol_avg": round(recent_vol),
        "prior_vol_avg":  round(prior_vol),
        "vol_ratio": round(vol_ratio, 2),
        "price_pullback": round(pullback_pct, 1),
        "reason": "缩量回调" if ok else f"量能{vol_ratio:.0%}>前量 或 回撤{pullback_pct:.1f}%>15%"
    }


# ── 条件2：Above20EMA > 55% ───────────────────────────────────────────────

def check_breadth_ok(breadth_data: dict, threshold: float = 0.55) -> dict:
    """Breadth没有崩：Above20EMA > 55%"""
    above_20 = breadth_data.get("above_sma20", 0.5)
    ok = above_20 > threshold
    return {
        "ok": ok,
        "above_sma20": round(above_20, 4),
        "threshold": threshold,
        "reason": "Breadth健康" if ok else f"Above20EMA {above_20:.1%} ≤ {threshold:.1%}"
    }


# ── 条件3：VIX < 25 ───────────────────────────────────────────────────────

def check_vix_ok(vix_val: Optional[float], threshold: float = 25.0) -> dict:
    """VIX 上升有限"""
    if vix_val is None:
        return {"ok": True, "vix": None, "reason": "无VIX数据"}
    ok = vix_val < threshold
    return {
        "ok": ok,
        "vix": round(vix_val, 2),
        "threshold": threshold,
        "reason": f"VIX={vix_val:.1f} < {threshold}" if ok else f"VIX={vix_val:.1f} ≥ {threshold}"
    }


# ── 条件4：龙头没崩 ────────────────────────────────────────────────────────

def check_leaders_ok() -> dict:
    """
    龙头（NVDA/META/MSFT）没有放量破结构。

    结构定义：
      - 放量破 EMA20（当日成交量 > 20日均量2倍 AND 收盘 < EMA20）
      - 或放量破前低（成交量异常放大 + 收盘创N日新低）
    """
    results = {}
    all_ok = True

    for code in LEADERS:
        klines = load_stock_klines(code)
        if not klines:
            results[code] = {"ok": True, "reason": "无数据"}
            continue

        closes  = klines["closes"]
        volumes = klines["volumes"]
        highs   = klines["highs"]
        lows    = klines["lows"]
        dates   = klines["dates"]

        if len(closes) < 21:
            results[code] = {"ok": True, "reason": "数据不足"}
            continue

        # EMA20
        ema20 = ema_(closes, 20)
        last_ema20 = ema20[-1]
        last_close = closes[-1]
        last_vol   = volumes[-1]

        # 20日均量
        vol_avg20 = sum(volumes[-20:]) / 20

        # 结构破坏信号
        broken = False
        reason = "结构健康"

        # 信号1：放量破 EMA20
        if last_vol > vol_avg20 * 2.0 and last_close < last_ema20:
            broken = True
            reason = f"放量破EMA20（vol={last_vol/vol_avg20:.1f}x avg, close={last_close:.1f}<EMA20={last_ema20:.1f}）"

        # 信号2：放量创N日新低（N=20）
        if not broken:
            low_20d = min(lows[-20:])
            if last_close <= low_20d and last_vol > vol_avg20 * 1.5:
                broken = True
                reason = f"放量破20日低点（vol={last_vol/vol_avg20:.1f}x avg）"

        # 信号3：急跌（单日跌幅>5% + 放量）
        if not broken:
            if len(closes) >= 2:
                daily_chg = (closes[-1] / closes[-2] - 1) * 100
                if daily_chg < -5 and last_vol > vol_avg20 * 2.0:
                    broken = True
                    reason = f"急跌{daily_chg:.1f}%+放量（vol={last_vol/vol_avg20:.1f}x）"

        results[code] = {"ok": not broken, "reason": reason, "last_close": last_close,
                         "ema20": round(last_ema20, 2) if last_ema20 else None,
                         "vol_ratio": round(last_vol / vol_avg20, 1) if vol_avg20 > 0 else None,
                         "last_date": dates[-1] if dates else None}
        if broken:
            all_ok = False

    return {"ok": all_ok, "leaders": results}


# ── 条件5：资金回流快 ───────────────────────────────────────────────────────

def check_money_return(code: str = "SPY") -> dict:
    """
    回踩后1-3日内重新站回关键EMA。

    逻辑：
      1. 找到最近一次"回踩低点"（价格 < EMA20 的局部最低点）
      2. 确认回踩后3日内价格是否重新站上 EMA20
      3. 同时要求回踩本身不深（<10%）
    """
    klines = load_stock_klines(code)
    if not klines or len(klines["closes"]) < 25:
        return {"ok": False, "reason": "数据不足", "ema20_current": None,
                "price_current": None, "days_to_return": None, "pullback_depth": None}

    closes = klines["closes"]
    ema20  = ema_(closes, 20)
    dates  = klines["dates"]

    if ema20[-1] is None or len([x for x in ema20 if x is not None]) < 20:
        return {"ok": False, "reason": "EMA计算不足", "ema20_current": None,
                "price_current": None, "days_to_return": None, "pullback_depth": None}

    # 找最近5日内是否有回踩（价格 < EMA20）
    pullback_idx = None
    for i in range(len(closes) - 1, max(0, len(closes) - 6), -1):
        if closes[i] < ema20[i]:
            pullback_idx = i
            break

    if pullback_idx is None:
        return {
            "ok": True, "reason": "未发生回踩（持续在EMA20上方）",
            "ema20_current": round(ema20[-1], 2), "price_current": closes[-1],
            "days_to_return": 0, "pullback_depth": 0.0,
            "current_above_ema": closes[-1] > ema20[-1]
        }

    # 回踩低点
    pullback_low = closes[pullback_idx]
    pullback_ema = ema20[pullback_idx]
    depth_pct = (pullback_ema - pullback_low) / pullback_ema * 100

    # 回踩后是否重新站回EMA20
    days_to_return = None
    for i in range(pullback_idx + 1, min(len(closes), pullback_idx + 4)):
        if closes[i] >= ema20[i]:
            days_to_return = i - pullback_idx
            break

    if days_to_return is not None and days_to_return <= 3:
        ok = True
        reason = f"回踩后{days_to_return}日站回EMA20"
    else:
        ok = False
        reason = f"回踩后未在3日内站回（已{days_to_return or '未'}站回）"

    return {
        "ok": ok,
        "reason": reason,
        "ema20_current": round(ema20[-1], 2),
        "price_current": closes[-1],
        "days_to_return": days_to_return,
        "pullback_depth": round(depth_pct, 1),
        "current_above_ema": closes[-1] > ema20[-1],
        "pullback_date": dates[pullback_idx] if pullback_idx else None
    }


# ── 主检测函数 ─────────────────────────────────────────────────────────────

def detect_healthy_pullback() -> dict:
    """
    综合检测：当前是否为健康回踩。

    返回：
      is_healthy: bool
      signal:     HEALTHY / WARNING / NO_PULLBACK
      checks:     各条件详情
    """
    # 加载基础数据
    breadth = load_breadth()
    vix_val = load_vix()

    # 条件1：回调缩量（用 SPY）
    spy_klines = load_stock_klines("SPY")
    if spy_klines:
        c1 = check_volume_pullback(spy_klines["closes"], spy_klines["volumes"])
    else:
        c1 = {"ok": False, "reason": "无SPY数据"}

    # 条件2：Above20EMA > 55%
    c2 = check_breadth_ok(breadth)

    # 条件3：VIX < 25
    c3 = check_vix_ok(vix_val)

    # 条件4：龙头没崩
    c4 = check_leaders_ok()

    # 条件5：资金回流快（SPY + QQQ）
    c5_spy = check_money_return("SPY")
    c5_qqq = check_money_return("QQQ")
    c5 = {
        "ok": c5_spy["ok"] or c5_qqq["ok"],
        "spys": c5_spy,
        "qqqs": c5_qqq,
        "reason": "SPY+QQQ至少一个回流成功" if c5_spy["ok"] or c5_qqq["ok"] else "两者均未回流"
    }

    checks = {"volume_pullback": c1, "breadth_ok": c2, "vix_ok": c3,
             "leaders_ok": c4, "money_return": c5}

    # 5个条件全部满足 = 健康回踩
    all_ok = c1["ok"] and c2["ok"] and c3["ok"] and c4["ok"] and c5["ok"]

    # 部分满足但无明确回踩 = WARNING
    any_ok = c1["ok"] or c2["ok"] or c3["ok"] or c4["ok"] or c5["ok"]
    signal = "HEALTHY" if all_ok else ("WARNING" if any_ok else "NO_PULLBACK")

    return {
        "date": str(date.today()),
        "is_healthy": all_ok,
        "signal": signal,
        "checks": checks,
        "leaders": c4.get("leaders"),
    }


def save_pullback_state(result: dict) -> None:
    """保存检测结果到 state 目录"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fpath = STATE_DIR / "pullback_state.json"
    with open(fpath, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)


def get_pullback_state() -> dict | None:
    """读取最新检测结果"""
    fpath = STATE_DIR / "pullback_state.json"
    if not fpath.exists():
        return None
    try:
        with open(fpath) as f:
            d = json.load(f)
        if d.get("date") == str(date.today()):
            return d
        return None   # 数据过期
    except Exception:
        return None


# ── 入口 ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = detect_healthy_pullback()
    save_pullback_state(result)

    sig = result["signal"]
    healthy = result["is_healthy"]
    ch = result["checks"]

    print(f"[Pullback] 信号: {sig}")
    print(f"  条件1 缩量回调: {'✅' if ch['volume_pullback']['ok'] else '❌'} "
          f"({ch['volume_pullback'].get('reason', '')})")
    print(f"  条件2 Breadth>55%: {'✅' if ch['breadth_ok']['ok'] else '❌'} "
          f"({ch['breadth_ok'].get('reason', '')})")
    print(f"  条件3 VIX<25: {'✅' if ch['vix_ok']['ok'] else '❌'} "
          f"({ch['vix_ok'].get('reason', '')})")
    print(f"  条件4 龙头稳定: {'✅' if ch['leaders_ok']['ok'] else '❌'} "
          f"({result['leaders']})")
    print(f"  条件5 资金回流: {'✅' if ch['money_return']['ok'] else '❌'} "
          f"({ch['money_return'].get('reason', '')})")

    print()
    print(json.dumps(result, indent=2, ensure_ascii=False))
