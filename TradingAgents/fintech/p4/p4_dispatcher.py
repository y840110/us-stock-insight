#!/usr/bin/env python3
"""
P4 总调度脚本
=============
统一调度 G1/G2/G3 三个独立策略，执行综合评判。
支持：
    python3 fintech/p4/p4_dispatcher.py                    # 扫描全市场
    python3 fintech/p4/p4_dispatcher.py --g1-only          # 只跑 G1
    python3 fintech/p4/p4_dispatcher.py --g2-only          # 只跑 G2
    python3 fintech/p4/p4_dispatcher.py --g3-only          # 只跑 G3
    python3 fintech/p4/p4_dispatcher.py --strategies g1 g2  # 跑 G1+G2
    python3 fintech/p4/p4_dispatcher.py --ticker AAPL       # 单股评估（G1+G2+G3）
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
KLINES_DIR  = PROJECT_ROOT / "中间过程" / "klines"
STATE_DIR   = PROJECT_ROOT / "fintech" / "state"
REPORT_DIR  = PROJECT_ROOT / "fintech" / "p4" / "layout"

STATE_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT_ROOT / "fintech" / "p4"))

# ─── 调度各策略 ──────────────────────────────────────────────────────────────

def run_g1(regime: str, regime_score: float):
    """运行 G1 趋势跟随策略"""
    from g1_screener import scan_g1
    _, _, candidates = scan_g1(regime, regime_score)
    return candidates

def run_g2(regime: str, regime_score: float):
    """运行 G2 低吸/回踩策略"""
    from g2_screener import scan_g2
    _, _, candidates = scan_g2(regime, regime_score)
    return candidates

def run_g3(regime: str, regime_score: float):
    """运行 G3 ML 概率预测策略"""
    from g3_screener import scan_g3
    _, _, candidates = scan_g3(regime, regime_score)
    return candidates

# ─── 合并候选池 ──────────────────────────────────────────────────────────────

def merge_candidates(g1_cands: dict, g2_cands: dict, g3_cands: dict) -> list:
    """
    将 G1/G2/G3 候选结果合并为统一列表。
    每只股票记录三个策略各自的评分（tier/score/reasons）。
    """
    # ticker → merged entry
    merged = {}

    for tier_name, items in [("L1", g1_cands.get("L1", [])),
                               ("L2", g1_cands.get("L2", [])),
                               ("L3", g1_cands.get("L3", [])),
                               ("L4", g1_cands.get("L4", []))]:
        for item in items:
            t = item["ticker"]
            if t not in merged:
                merged[t] = {
                    "ticker":    t,
                    "close":     item.get("close", 0),
                    "rsi":       item.get("rsi", 50),
                    "rsi_zone":  item.get("rsi_zone", ""),
                    "trend":     item.get("trend", "→"),
                    "mom20":     item.get("mom20", 0),
                    "dist_ema20": item.get("dist_ema20", 0),
                    "atr14":     item.get("atr14", 0),
                    "bb_pct":    item.get("bb_pct", 50),
                    "vol_ratio": item.get("vol_ratio", 1),
                    "p_up":      None,
                    # G1
                    "tier_g1": item.get("tier_g1", "NONE"),
                    "score_g1": item.get("score_g1", 0),
                    "reasons_g1": item.get("reasons_g1", []),
                    # G2（初始 NONE）
                    "tier_g2": "NONE", "score_g2": 0, "reasons_g2": [],
                    # G3（初始 NONE）
                    "tier_g3": "NONE", "score_g3": 0, "reasons_g3": [],
                }

    for tier_name, items in [("L1", g2_cands.get("L1", [])),
                               ("L2", g2_cands.get("L2", [])),
                               ("L3", g2_cands.get("L3", [])),
                               ("L4", g2_cands.get("L4", []))]:
        for item in items:
            t = item["ticker"]
            if t not in merged:
                merged[t] = {
                    "ticker": t, "close": item.get("close", 0),
                    "rsi": item.get("rsi", 50), "rsi_zone": item.get("rsi_zone", ""),
                    "trend": item.get("trend", "→"), "mom20": item.get("mom20", 0),
                    "dist_ema20": item.get("dist_ema20", 0), "atr14": item.get("atr14", 0),
                    "bb_pct": item.get("bb_pct", 50), "vol_ratio": item.get("vol_ratio", 1),
                    "p_up": None,
                    "tier_g1": "NONE", "score_g1": 0, "reasons_g1": [],
                    "tier_g2": item.get("tier_g2", "NONE"),
                    "score_g2": item.get("score_g2", 0),
                    "reasons_g2": item.get("reasons_g2", []),
                    "tier_g3": "NONE", "score_g3": 0, "reasons_g3": [],
                }
            else:
                merged[t]["tier_g2"]   = item.get("tier_g2", "NONE")
                merged[t]["score_g2"]  = item.get("score_g2", 0)
                merged[t]["reasons_g2"] = item.get("reasons_g2", [])

    for tier_name, items in [("L1", g3_cands.get("L1", [])),
                               ("L2", g3_cands.get("L2", [])),
                               ("L3", g3_cands.get("L3", [])),
                               ("L4", g3_cands.get("L4", []))]:
        for item in items:
            t = item["ticker"]
            if t not in merged:
                merged[t] = {
                    "ticker": t, "close": item.get("close", 0),
                    "rsi": item.get("rsi", 50), "rsi_zone": item.get("rsi_zone", ""),
                    "trend": item.get("trend", "→"), "mom20": item.get("mom20", 0),
                    "dist_ema20": item.get("dist_ema20", 0), "atr14": item.get("atr14", 0),
                    "bb_pct": item.get("bb_pct", 50), "vol_ratio": item.get("vol_ratio", 1),
                    "p_up": item.get("p_up"),
                    "tier_g1": "NONE", "score_g1": 0, "reasons_g1": [],
                    "tier_g2": "NONE", "score_g2": 0, "reasons_g2": [],
                    "tier_g3": item.get("tier_g3", "NONE"),
                    "score_g3": item.get("score_g3", 0),
                    "reasons_g3": item.get("reasons_g3", []),
                }
            else:
                merged[t]["tier_g3"]    = item.get("tier_g3", "NONE")
                merged[t]["score_g3"]   = item.get("score_g3", 0)
                merged[t]["reasons_g3"]  = item.get("reasons_g3", [])
                merged[t]["p_up"]       = item.get("p_up")

    return list(merged.values())


# ─── 综合评判（调用 synthesize） ──────────────────────────────────────────────

def synthesize_all(candidates: list, p2_regime: dict, p3_sectors: dict) -> list:
    """对合并后的候选池执行综合评判"""
    from synthesize import synthesize

    scored = []
    for stock in candidates:
        result = synthesize(stock, p2_regime, p3_sectors)
        scored.append(result)
    scored.sort(key=lambda x: x["final_score"], reverse=True)
    return scored


# ─── 权重计算 ───────────────────────────────────────────────────────────────

def get_weights(regime_score: float) -> tuple:
    if regime_score >= 8:   return 0.80, 0.10, 0.10
    elif regime_score >= 6: return 0.60, 0.20, 0.20
    elif regime_score >= 4: return 0.30, 0.50, 0.20
    else:                   return 0.10, 0.40, 0.50


# ─── 主调度函数 ──────────────────────────────────────────────────────────────

def run_p4(p2_regime: dict, p3_sectors: dict,
           strategies: list = None) -> dict:
    """
    P4 总调度入口。

    参数：
        p2_regime:    P2 Regime 分析结果 dict
        p3_sectors:   P3 板块分析结果 dict
        strategies:    运行哪些策略，默认 ["g1", "g2", "g3"]

    返回：
        {
            "regime": str,
            "candidates": [...],   # 原始合并候选
            "ranked": [...],       # 综合评判+排序结果
            "l1/l2/l3/l4": [...],
            "stats": {...}
        }
    """
    if strategies is None:
        strategies = ["g1", "g2", "g3"]

    regime       = p2_regime.get("regime", "UNKNOWN")
    regime_score = p2_regime.get("score", 5.0)
    g1_w, g2_w, g3_w = get_weights(regime_score)

    print(f"\n{'='*60}")
    print(f"P4 · 择股层  G1/G2/G3 策略调度")
    print(f"{'='*60}")
    print(f"  Regime: {regime} (score={regime_score})")
    print(f"  权重:   G1={g1_w:.0%}  G2={g2_w:.0%}  G3={g3_w:.0%}")
    print(f"  策略:   {strategies}")

    g1_cands = {"L1": [], "L2": [], "L3": [], "L4": []}
    g2_cands = {"L1": [], "L2": [], "L3": [], "L4": []}
    g3_cands = {"L1": [], "L2": [], "L3": [], "L4": []}

    if "g1" in strategies:
        g1_cands = run_g1(regime, regime_score)
    if "g2" in strategies:
        g2_cands = run_g2(regime, regime_score)
    if "g3" in strategies:
        g3_cands = run_g3(regime, regime_score)

    # 统计各策略通过数量
    g1_pass = sum(len(v) for v in g1_cands.values())
    g2_pass = sum(len(v) for v in g2_cands.values())
    g3_pass = sum(len(v) for v in g3_cands.values())
    print(f"\n  各策略通过数量: G1={g1_pass}  G2={g2_pass}  G3={g3_pass}")

    # 合并 + 综合评判
    merged = merge_candidates(g1_cands, g2_cands, g3_cands)
    ranked = synthesize_all(merged, p2_regime, p3_sectors)

    l1 = [r for r in ranked if r["final_tier"] == "L1"]
    l2 = [r for r in ranked if r["final_tier"] == "L2"]
    l3 = [r for r in ranked if r["final_tier"] == "L3"]
    l4 = [r for r in ranked if r["final_tier"] == "L4"]

    result = {
        "regime":       regime,
        "regime_score": regime_score,
        "strategies":   strategies,
        "candidates":   merged,
        "ranked":       ranked,
        "l1": l1, "l2": l2, "l3": l3, "l4": l4,
        "stats": {
            "total":     len(merged),
            "g1_pass":   g1_pass,
            "g2_pass":   g2_pass,
            "g3_pass":   g3_pass,
            "l1_count":  len(l1),
            "l2_count":  len(l2),
            "l3_count":  len(l3),
            "l4_count":  len(l4),
        },
    }
    return result


# ─── CLI 入口 ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="P4 择股层总调度 | 支持 --g1-only / --g2-only / --g3-only"
    )
    parser.add_argument("--g1-only",   action="store_true", help="只跑 G1 策略")
    parser.add_argument("--g2-only",   action="store_true", help="只跑 G2 策略")
    parser.add_argument("--g3-only",   action="store_true", help="只跑 G3 策略")
    parser.add_argument("--strategies", nargs="+",
                        choices=["g1", "g2", "g3"],
                        help="指定运行哪些策略，例: --strategies g1 g2")
    parser.add_argument("--ticker",    type=str, default=None,
                        help="单股评估（输出各策略独立评分）")
    parser.add_argument("--regime",    type=str, default="超强牛市")
    parser.add_argument("--score",    type=float, default=8.0,
                        help="Regime score (default: 8.0)")
    args = parser.parse_args()

    if args.g1_only:   strategies = ["g1"]
    elif args.g2_only:  strategies = ["g2"]
    elif args.g3_only:  strategies = ["g3"]
    elif args.strategies: strategies = args.strategies
    else:               strategies = ["g1", "g2", "g3"]

    p2_regime  = {"regime": args.regime, "score": args.score}
    p3_sectors = {"sectors": [], "hot_sectors": [], "cold_sectors": []}

    # ── 单股模式 ──────────────────────────────────────────────────
    if args.ticker:
        ticker = args.ticker.upper()
        print(f"\n[单股评估] {ticker}")
        print(f"  Regime: {args.regime} (score={args.score})")
        print(f"  策略: {strategies}")

        results = {}
        if "g1" in strategies:
            from g1_screener import _compute_indicators as g1_ind, score_g1
            ind = g1_ind(ticker)
            if ind:
                t, s, r = score_g1(ind, args.regime)
                print(f"  G1: tier={t} score={s}")
                for x in r: print(f"    - {x}")
                results["g1"] = (t, s, r)
            else:
                print(f"  G1: 无法获取数据")

        if "g2" in strategies:
            from g2_screener import _compute_indicators as g2_ind, score_g2
            ind = g2_ind(ticker)
            if ind:
                t, s, r = score_g2(ind, args.regime)
                print(f"  G2: tier={t} score={s}")
                for x in r: print(f"    - {x}")
                results["g2"] = (t, s, r)
            else:
                print(f"  G2: 无法获取数据")

        if "g3" in strategies:
            from g3_screener import _compute_indicators as g3_ind, score_g3, predict_pup
            ind = g3_ind(ticker)
            if ind:
                p_up = predict_pup(ticker)
                t, s, r = score_g3(ind, args.regime, p_up)
                pstr = f"p_up={p_up:.1%}" if p_up else "p_up=N/A"
                print(f"  G3: tier={t} score={s} {pstr}")
                for x in r: print(f"    - {x}")
                results["g3"] = (t, s, r)
            else:
                print(f"  G3: 无法获取数据")
        return

    # ── 全市场扫描模式 ────────────────────────────────────────────
    result = run_p4(p2_regime, p3_sectors, strategies)

    print(f"\n  【综合推荐】")
    print(f"  L1(强烈推荐): {len(result['l1'])} 只")
    print(f"  L2(推荐):     {len(result['l2'])} 只")
    print(f"  L3(观察):    {len(result['l3'])} 只")

    if result["l1"]:
        print(f"\n  Top L1:")
        print(f"  {'标的':<10} {'综合分':>7}  {'G1':>6}  {'G2':>6}  {'G3':>6}  理由")
        print("  " + "-"*80)
        for r in result["l1"][:10]:
            w = r["weights_used"]
            print(f"  {r['ticker']:<10} {r['final_score']:>6.1f}  "
                  f"{r['g1_contrib']:>6.1f}  {r['g2_contrib']:>6.1f}  "
                  f"{r['g3_contrib']:>6.1f}  {r['reason'][:50]}")


if __name__ == "__main__":
    main()
