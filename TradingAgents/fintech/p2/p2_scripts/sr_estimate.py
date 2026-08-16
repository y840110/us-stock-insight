#!/usr/bin/env python3
"""
SPY 支撑/压力位独立估算脚本
──────────────────────────────────────────────────────────────────
结合：标准技术分析 + 历史测试统计 + 逻辑回归概率

用法：
  python3 sr_estimate.py [trade_date]
  python3 sr_estimate.py 2026-05-15

输出：
  1. 各技术分析方法估算的支撑/压力位
  2. 历史测试命中率统计
  3. 逻辑回归加权概率
  4. 综合估算（带概率标注）
──────────────────────────────────────────────────────────────────
"""
import sys, json, math
from pathlib import Path
from datetime import datetime, timedelta

# ── 路径设置 ──────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
from p2_shared.utils import P1_KLINES

# ── 数据加载 ────────────────────────────────────────────────

def load_klines(ticker, trade_date, lookback=250):
    path = P1_KLINES / (ticker + "_1d.json")
    if not path.exists():
        print("[ERROR] 数据文件不存在:", path); return []
    with open(path) as f:
        raw = json.load(f)
    bars = raw.get("data", raw) if isinstance(raw, dict) else raw
    cutoff = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=lookback + 20)).strftime("%Y-%m-%d")
    return [b for b in bars if cutoff <= b.get("date", "") <= trade_date]

# ── 技术分析函数 ────────────────────────────────────────────

def calc_pivot(bars):
    """标准Pivot Points (Classic)"""
    if len(bars) < 2: return None
    H, L, C = float(bars[-2]["high"]), float(bars[-2]["low"]), float(bars[-2]["close"])
    pp = (H + L + C) / 3
    r1, r2, r3 = 2*pp - L, pp + (H - L), H + 2*(pp - L)
    s1, s2, s3 = 2*pp - H, pp - (H - L), L - 2*(H - pp)
    return {"pp": pp, "r1": r1, "r2": r2, "r3": r3, "s1": s1, "s2": s2, "s3": s3}

def calc_fibonacci(bars):
    """Fibonacci回撤 (20日区间)"""
    if len(bars) < 20: return None
    lows  = [float(b["low"])  for b in bars[-20:]]
    highs = [float(b["high"]) for b in bars[-20:]]
    low_20  = min(lows);  high_20 = max(highs)
    rng = high_20 - low_20
    return {
        "low": low_20, "high": high_20, "range": rng,
        "fib_236": high_20 - rng * 0.236,
        "fib_382": high_20 - rng * 0.382,
        "fib_500": high_20 - rng * 0.500,
        "fib_618": high_20 - rng * 0.618,
        "fib_786": high_20 - rng * 0.786,
    }

def calc_bollinger(bars, period=20):
    """Bollinger Bands"""
    if len(bars) < period: return None
    closes = [float(b["close"]) for b in bars[-period:]]
    mean = sum(closes) / period
    std  = math.sqrt(sum((c - mean) ** 2 for c in closes) / period)
    return {"upper": mean + 2*std, "middle": mean, "lower": mean - 2*std}

def calc_vwap(bars):
    """VWAP"""
    if len(bars) < 2: return None
    cum_vol, cum_pv = 0.0, 0.0
    for b in bars:
        h, l, c, v = float(b["high"]), float(b["low"]), float(b["close"]), float(b.get("volume", 0))
        typical = (h + l + c) / 3
        cum_vol += v; cum_pv += typical * v
    return {"vwap": cum_pv / cum_vol if cum_vol > 0 else 0}

def calc_ema(closes, period=20):
    if len(closes) < period: return None
    k = 2.0 / (period + 1)
    ema = closes[0]
    for c in closes[1:]:
        ema = c * k + ema * (1 - k)
    return ema

def atr(bars, period=14):
    if len(bars) < period + 1: return None
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = float(bars[i]["high"]), float(bars[i]["low"]), float(bars[i-1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period

# ── 历史测试统计 ──────────────────────────────────────────

def count_level_hits(bars, level, tolerance=0.012):
    """
    统计历史价格触及某价位的次数。
    tolerance: 容差（相对价格），默认1.2%
    返回: (上涨势保持次数, 下跌势保持次数, 总触及次数)
    """
    if not bars: return (0, 0, 0)
    sup_holds, res_holds, total = 0, 0, 0
    for b in bars:
        lo, hi, cl = float(b["low"]), float(b["high"]), float(b["close"])
        if lo <= level <= hi:
            total += 1
            # 支撑：价格测试后收在level之上（未有效下破）
            if cl >= level * (1 - tolerance): sup_holds += 1
            # 压力：价格测试后收在level之下（未有效上破）
            if cl <= level * (1 + tolerance): res_holds += 1
    return (sup_holds, res_holds, total)

def historical_hit_rate(bars, level, lookback=60):
    """计算历史命中率（最近N根K线）"""
    if len(bars) < 5: return None
    subset = bars[-lookback:] if len(bars) >= lookback else bars
    sup_h, res_h, total = count_level_hits(subset, level)
    if total == 0: return None
    return {"sup_hold_rate": sup_h / total, "res_hold_rate": res_h / total, "total_tests": total}

# ── 逻辑回归概率估算 ────────────────────────────────────────

def logistic_regression_prob(level, close, atr_val, dist_pct, hit_rate, vol_adj):
    """
    基于逻辑回归特征的支撑/压力位维持概率估算。

    特征：
    - x1: 距现价距离（%），越近越容易触及但也越重要
    - x2: 历史测试命中率
    - x3: ATR波动率调整（波动越大，可靠性越低）
    - x4: 支撑/压力类型权重（Pivot常见，Fib精准）

    回归模型（基于历史规律的经验系数）：
    P = 1 / (1 + exp(-z))
    z = w0 + w1*x1 + w2*x2 + w3*x3 + w4*x4

    典型系数：
    w0 = 1.5（基础概率偏移）
    w1 = -8.0（距离越远概率越低）
    w2 = 3.0（命中率越高越好）
    w3 = -0.5（波动率越高越低）
    w4 = 0.3（特定类型加成）
    """
    if dist_pct is None or dist_pct <= 0: return 50.0

    # 标准化
    x1 = min(dist_pct / 10.0, 1.0)   # 距离（>10%饱和）
    x2 = min((hit_rate or 0.5), 1.0)  # 命中率
    x3 = min(max((vol_adj or 1.0) - 0.8, 0) / 1.5, 1.0)  # 波动调整
    x4 = 0.5  # 基础类型权重

    # 逻辑回归
    z = 1.5 - 8.0 * x1 + 3.0 * x2 - 0.5 * x3 + 0.3 * x4
    prob = 1.0 / (1.0 + math.exp(-z))
    return round(prob * 100, 1)

# ── 主估算流程 ─────────────────────────────────────────────

def estimate_sr(ticker, trade_date):
    bars = load_klines(ticker, trade_date)
    if not bars:
        print("[ERROR] 无数据"); return

    closes = [float(b["close"]) for b in bars]
    highs  = [float(b["high"])  for b in bars]
    lows   = [float(b["low"])   for b in bars]
    vols   = [float(b.get("volume", 0)) for b in bars]
    close  = closes[-1]
    atr14  = atr(bars)
    atr_pct = (atr14 / close * 100) if atr14 else 1.5
    vol_adj  = 1.0 if atr_pct < 1.5 else (0.92 if atr_pct < 2.5 else 0.80)

    pivot = calc_pivot(bars)
    fib   = calc_fibonacci(bars)
    bb    = calc_bollinger(bars)
    vwap  = calc_vwap(bars)
    ema20 = calc_ema(closes, 20)
    sma50 = calc_ema(closes, 50) if len(closes) >= 50 else None
    sma200 = calc_ema(closes, 200) if len(closes) >= 200 else None

    print("=" * 65)
    print(f"SPY 支撑/压力位估算 — {trade_date}  收盘价: {close:.2f}")
    print("=" * 65)
    print(f"ATR={atr14:.2f}({atr_pct:.2f}%)  波动调整={vol_adj:.2f}  K线数={len(bars)}")

    # ── 方法1: Pivot ──
    if pivot:
        print("\n【方法1】标准Pivot Points (Classic)")
        for name, val in [("S3", pivot["s3"]), ("S2", pivot["s2"]), ("S1", pivot["s1"]),
                           ("PP",  pivot["pp"]), ("R1", pivot["r1"]), ("R2", pivot["r2"]), ("R3", pivot["r3"])]:
            dist_pct = abs(close - val) / close * 100
            is_sup = val < close - 0.3
            is_res = val > close + 0.3
            if not is_sup and not is_res and abs(val - close) < 0.3:
                kind = "中(PP)"
            elif is_sup:
                kind = "支撑"
            elif is_res:
                kind = "压力"
            else:
                kind = "双向" if abs(val - close) < 2.0 else "—"

            hit = historical_hit_rate(bars, val)
            hr  = (hit["sup_hold_rate"] if is_sup else (hit["res_hold_rate"] if hit else 0.5)) if hit else 0.5 if is_res else 0.5
            prob = logistic_regression_prob(val, close, atr14, dist_pct, hr, vol_adj)
            flag = " ← ⚠️方向有误" if (is_sup and val > close) or (is_res and val < close) else ""
            if kind != "—":
                print(f"  {name}: {val:.2f} ({kind}) 距现价{dist_pct:.2f}%  "
                      f"历史命中率={hr:.0%}  LR概率={prob}%{flag}")

    # ── 方法2: Fibonacci ──
    if fib:
        print("\n【方法2】Fibonacci回撤 (20日区间: {:.2f}~{:.2f})".format(fib["low"], fib["high"]))
        for name in ["fib_236", "fib_382", "fib_500", "fib_618", "fib_786"]:
            val = fib[name]
            dist_pct = abs(close - val) / close * 100
            is_sup = val < close - 0.3
            is_res = val > close + 0.3
            if not is_sup and not is_res: continue  # 只显示相关
            hit = historical_hit_rate(bars, val)
            hr  = (hit["sup_hold_rate"] if is_sup else (hit["res_hold_rate"] if hit else 0.5)) if hit else 0.5
            prob = logistic_regression_prob(val, close, atr14, dist_pct, hr, vol_adj)
            kind = "支撑" if is_sup else "压力"
            print(f"  {name}: {val:.2f} ({kind}) 距现价{dist_pct:.2f}%  "
                  f"历史命中率={hr:.0%}  LR概率={prob}%")

    # ── 方法3: Bollinger Bands ──
    if bb:
        print("\n【方法3】Bollinger Bands (20日)")
        for name, val in [("BB下轨", bb["lower"]), ("BB中轨", bb["middle"]), ("BB上轨", bb["upper"])]:
            dist_pct = abs(close - val) / close * 100
            is_sup = val < close - 0.3
            is_res = val > close + 0.3
            kind = "支撑" if is_sup else ("压力" if is_res else "—")
            if kind == "—": continue
            hit = historical_hit_rate(bars, val)
            hr  = (hit["sup_hold_rate"] if is_sup else (hit["res_hold_rate"] if hit else 0.5)) if hit else 0.5
            prob = logistic_regression_prob(val, close, atr14, dist_pct, hr, vol_adj)
            print(f"  {name}: {val:.2f} ({kind}) 距现价{dist_pct:.2f}%  "
                  f"历史命中率={hr:.0%}  LR概率={prob}%")

    # ── 方法4: VWAP ──
    if vwap:
        val = vwap["vwap"]
        dist_pct = abs(close - val) / close * 100
        is_sup = val < close - 0.3
        is_res = val > close + 0.3
        kind = "支撑" if is_sup else ("压力" if is_res else "双向")
        hit = historical_hit_rate(bars, val)
        hr  = hit["sup_hold_rate"] if is_sup else (hit["res_hold_rate"] if is_res else 0.5)
        prob = logistic_regression_prob(val, close, atr14, dist_pct, hr, vol_adj)
        print(f"\n【方法4】VWAP: {val:.2f} ({kind}) 距现价{dist_pct:.2f}%  "
              f"历史命中率={hr:.0%}  LR概率={prob}%")

    # ── 方法5: 均线系统 ──
    print("\n【方法5】均线系统")
    for name, val, period in [
        ("EMA20",  ema20,  20),
        ("SMA50",  sma50,  50),
        ("SMA200", sma200, 200),
    ]:
        if val is None: continue
        dist_pct = abs(close - val) / close * 100
        is_sup = val < close - 0.3
        is_res = val > close + 0.3
        kind = "支撑" if is_sup else ("压力" if is_res else "—")
        if kind == "—": continue
        hit = historical_hit_rate(bars, val)
        hr  = (hit["sup_hold_rate"] if is_sup else (hit["res_hold_rate"] if hit else 0.5)) if hit else 0.5
        prob = logistic_regression_prob(val, close, atr14, dist_pct, hr, vol_adj)
        print(f"  {name}: {val:.2f} ({kind}) 距现价{dist_pct:.2f}%  "
              f"历史命中率={hr:.0%}  LR概率={prob}%")

    # ── 综合结论 ──
    print("\n" + "=" * 65)
    print("【综合结论】")
    # 收集所有候选
    candidates = []
    methods_map = {}
    if pivot:
        for name, val in [("S3", pivot["s3"]), ("S2", pivot["s2"]), ("S1", pivot["s1"]),
                           ("R1", pivot["r1"]), ("R2", pivot["r2"]), ("R3", pivot["r3"])]:
            dist_pct = abs(close - val) / close * 100
            is_sup = val < close - 0.3
            is_res = val > close + 0.3
            kind = "sup" if is_sup else ("res" if is_res else None)
            if not kind: continue
            hit = historical_hit_rate(bars, val)
            hr = (hit["sup_hold_rate"] if is_sup else (hit["res_hold_rate"] if hit else 0.5)) if hit else 0.5
            prob = logistic_regression_prob(val, close, atr14, dist_pct, hr, vol_adj)
            candidates.append((val, name, kind, dist_pct, hr, prob, "Pivot"))
    if fib:
        for name in ["fib_236", "fib_382", "fib_500", "fib_618"]:
            val = fib[name]
            dist_pct = abs(close - val) / close * 100
            is_sup = val < close - 0.3
            is_res = val > close + 0.3
            if not is_sup and not is_res: continue
            hit = historical_hit_rate(bars, val)
            hr = (hit["sup_hold_rate"] if is_sup else (hit["res_hold_rate"] if hit else 0.5)) if hit else 0.5
            prob = logistic_regression_prob(val, close, atr14, dist_pct, hr, vol_adj)
            candidates.append((val, name.upper(), "sup" if is_sup else "res", dist_pct, hr, prob, "Fibonacci"))
    if bb:
        for name, val in [("BB下轨", bb["lower"]), ("BB上轨", bb["upper"])]:
            is_sup = val < close - 0.3
            is_res = val > close + 0.3
            if not is_sup and not is_res: continue
            dist_pct = abs(close - val) / close * 100
            hit = historical_hit_rate(bars, val)
            hr = (hit["sup_hold_rate"] if is_sup else (hit["res_hold_rate"] if hit else 0.5)) if hit else 0.5
            prob = logistic_regression_prob(val, close, atr14, dist_pct, hr, vol_adj)
            candidates.append((val, name, "sup" if is_sup else "res", dist_pct, hr, prob, "BBands"))
    if vwap:
        val = vwap["vwap"]
        dist_pct = abs(close - val) / close * 100
        is_sup = val < close - 0.3
        is_res = val > close + 0.3
        if is_sup or is_res:
            hit = historical_hit_rate(bars, val)
            hr = (hit["sup_hold_rate"] if is_sup else (hit["res_hold_rate"] if hit else 0.5)) if hit else 0.5
            prob = logistic_regression_prob(val, close, atr14, dist_pct, hr, vol_adj)
            candidates.append((val, "VWAP", "sup" if is_sup else "res", dist_pct, hr, prob, "VWAP"))
    if ema20:
        val = ema20; dist_pct = abs(close - val) / close * 100
        is_sup = val < close - 0.3; is_res = val > close + 0.3
        if is_sup or is_res:
            hit = historical_hit_rate(bars, val)
            hr = (hit["sup_hold_rate"] if is_sup else (hit["res_hold_rate"] if hit else 0.5)) if hit else 0.5
            prob = logistic_regression_prob(val, close, atr14, dist_pct, hr, vol_adj)
            candidates.append((val, "EMA20", "sup" if is_sup else "res", dist_pct, hr, prob, "EMA"))

    # 分离支撑/压力
    sup_cands = sorted([c for c in candidates if c[2] == "sup"], key=lambda x: x[3])[:4]
    res_cands = sorted([c for c in candidates if c[2] == "res"], key=lambda x: x[3])[:4]

    print(f"\n  SPY收盘价: {close:.2f}")
    print(f"\n  ▼ 支撑位（现价下方，按距离排序）：")
    for val, name, kind, dist, hr, prob, method in sup_cands:
        bar_len = int(prob / 5)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        print(f"    {name:12s} {val:8.2f}  距{dist:5.2f}%  命中率{hr:.0%}  "
              f"LR概率{prob:5.1f}% [{bar}] {method}")

    print(f"\n  ▲ 压力位（现价上方，按距离排序）：")
    for val, name, kind, dist, hr, prob, method in res_cands:
        bar_len = int(prob / 5)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        print(f"    {name:12s} {val:8.2f}  距{dist:5.2f}%  命中率{hr:.0%}  "
              f"LR概率{prob:5.1f}% [{bar}] {method}")

    # 综合概率（加权平均）
    if sup_cands:
        avg_sup_prob = sum(c[5] for c in sup_cands) / len(sup_cands)
        print(f"\n  支撑综合概率（加权）: {avg_sup_prob:.1f}%")
    if res_cands:
        avg_res_prob = sum(c[5] for c in res_cands) / len(res_cands)
        print(f"  压力综合概率（加权）: {avg_res_prob:.1f}%")

    print("\n" + "=" * 65)
    print(f"注: LR概率 = 逻辑回归估算，考虑距离+命中率+波动率调整")
    print(f"    命中率 = 近60日价格测试该位后收复的比例")
    print(f"    ⚠️  方向有误 = 计算值与支撑/压力定义不符（已过滤）")
    print(f"    数据来源: P1 K线 (Yahoo Finance + 富途 OpenD)")
    print("=" * 65)

    # 返回结构化结果
    return {
        "date": trade_date,
        "close": close,
        "atr_pct": round(atr_pct, 2),
        "vol_adj": round(vol_adj, 2),
        "supports": [{"level": round(c[0],2), "name": c[1], "dist_pct": round(c[3],2),
                     "hit_rate": round(c[4],3), "lr_prob": c[5], "method": c[6]} for c in sup_cands],
        "resistances": [{"level": round(c[0],2), "name": c[1], "dist_pct": round(c[3],2),
                         "hit_rate": round(c[4],3), "lr_prob": c[5], "method": c[6]} for c in res_cands],
    }


if __name__ == "__main__":
    import os as _os
    td = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    result = estimate_sr("SPY", td)
    if result:
        out_dir = Path(__file__).parent
        out_path = out_dir / ("sr_estimate_" + td + ".json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print("\n[JSON已保存]", out_path)
