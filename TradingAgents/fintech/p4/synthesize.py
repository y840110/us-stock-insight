#!/usr/bin/env python3
"""
P4 综合评判层 — synthesize.py
================================
根据 P2 (Regime) + P3 (Sector) 的输入，
动态调整 G1/G2/G3 的策略权重，
综合打分后输出分层的候选股票池。

Regime → 策略权重映射：

  超强牛市 (8-10分):
    G1=80% (趋势跟随)  G2=10% (低吸)  G3=10% (ML)
  牛市 (6-7.9分):
    G1=60%  G2=20%  G3=20%
  震荡 (4-5.9分):
    G1=30%  G2=50%  G3=20%
  熊市 (2-3.9分):
    G1=10%  G2=40%  G3=50%
  大熊市 (0-1.9分):
    G1=5%   G2=30%  G3=65%

Sector → 板块过滤：
  强势板块(RS>+5%) → G1标的优先保留
  中性板块 → G1/G3 均衡
  弱势板块(RS<-5%) → 降权或淘汰

综合打分：
  final_score = g1_score * w1 + g2_score * w2 + g3_score * w3
  板块加成：强势板块标的额外 +10分
  弱势板块标的额外 -10分

输出：L1(强烈推荐) / L2(推荐) / L3(观察) / L4(放弃)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# 策略权重映射（根据 Regime Score）
# ══════════════════════════════════════════════════════════════════════════════

# (lo_score, hi_score, (g1, g2, g3))，按 lo_score 降序排列
REGIME_WEIGHTS = [
    (8.0,  11.0, (0.80, 0.10, 0.10)),  # 超强牛市（覆盖 8.1~10.5+）
    (6.0,   8.0, (0.60, 0.20, 0.20)),  # 牛市
    (4.0,   6.0, (0.30, 0.50, 0.20)),  # 震荡
    (2.0,   4.0, (0.10, 0.40, 0.50)),  # 熊市
    (0.0,   2.0, (0.05, 0.30, 0.65)),  # 大熊市
]


def get_weights(regime_score: float) -> tuple[float, float, float]:
    """根据 regime score 返回 (g1, g2, g3) 权重"""
    for lo, hi, w in REGIME_WEIGHTS:
        if lo <= regime_score < hi:
            return w
    return (0.30, 0.40, 0.30)  # 默认


# ══════════════════════════════════════════════════════════════════════════════
# 板块配置
# ══════════════════════════════════════════════════════════════════════════════
# P3 v2 已提供 hot_sectors / cold_sectors / sectors（含 tier/final_score/warnings）
# 这里作为 fallback，当 P3 数据缺失时使用
HOT_SECTORS_FALLBACK = {"SOXX", "SMH", "XLK", "QQQ", "IBIT", "FBTC", "SOXL", "DRAM"}
COLD_SECTORS_FALLBACK = {"XLF", "XLE", "XLV", "XLY", "ITA", "GLD", "VFH", "VHT"}


# ══════════════════════════════════════════════════════════════════════════════
# 综合评判
# ══════════════════════════════════════════════════════════════════════════════

def synthesize(
    stock: dict,
    p2_regime: dict,
    p3_sectors: dict,
) -> dict:
    """
    对单只股票执行综合评判。

    参数：
        stock: {
            "ticker": str,
            "tier_g1": "L1"/"NONE",
            "score_g1": float,
            "tier_g2": "L2"/"NONE",
            "score_g2": float,
            "tier_g3": "L3"/"NONE",
            "score_g3": float,
            "p_up": float (可选),
            "sector": str,   # 如 "SOXX", "XLF"
            ...其他字段
        }
        p2_regime: P2 输出 dict（包含 score, regime）
        p3_sectors: P3 输出 dict（包含 sectors list）

    返回综合评判结果：
        {
            "ticker": str,
            "final_score": float,
            "final_tier": "L1"/"L2"/"L3"/"L4",
            "signal": "BUY"/"WATCH"/"AVOID",
            "weights_used": (g1, g2, g3),
            "sector_adjustment": int,
            "g1_contrib": float,
            "g2_contrib": float,
            "g3_contrib": float,
            "reason": str,
        }
    """
    regime_score = p2_regime.get("score", 5.0)
    g1_w, g2_w, g3_w = get_weights(regime_score)

    # ── 各策略得分（归一化到 0-100）───────────────────────────
    s1 = stock.get("score_g1", 0)   # G1 已是 0-100
    s2 = stock.get("score_g2", 0)   # G2 已是 0-100
    s3 = stock.get("score_g3", 0)   # G3 已是 0-100

    # ── 板块调整分（P3 v2 数据） ─────────────────────────────
    sector_ticker = stock.get("sector", "").upper()

    # P3 v2 直接提供 hot_sectors / cold_sectors 列表
    hot_sectors   = {t.upper() for t in p3_sectors.get("hot_sectors", [])}
    cold_sectors  = {t.upper() for t in p3_sectors.get("cold_sectors", [])}
    # fallback（当 P3 数据缺失时用硬编码）
    if not hot_sectors:
        hot_sectors = HOT_SECTORS_FALLBACK
    if not cold_sectors:
        cold_sectors = COLD_SECTORS_FALLBACK

    # 从 P3 sectors 构建 ticker → tier 映射（用于获取板块 P3 tier）
    sector_tier_map = {r["ticker"].upper(): r.get("tier", "L3")
                       for r in p3_sectors.get("sectors", [])}
    # 从 P3 sectors 构建 ticker → warnings 映射
    sector_warnings_map = {r["ticker"].upper(): r.get("warnings", [])
                           for r in p3_sectors.get("sectors", [])}

    sector_adj = 0
    sector_label = "neutral"
    if sector_ticker in hot_sectors:
        sector_adj = +10
        sector_label = "hot"
    elif sector_ticker in cold_sectors:
        sector_adj = -10
        sector_label = "cold"

    # 获取该股票对应板块的 P3 tier（如有）
    sector_p3_tier = sector_tier_map.get(sector_ticker, "L3")
    sector_warnings = sector_warnings_map.get(sector_ticker, [])

    # ── 综合打分 ───────────────────────────────────────────
    raw = s1 * g1_w + s2 * g2_w + s3 * g3_w
    final = max(0.0, min(100.0, raw + sector_adj))

    # ── 分层 ───────────────────────────────────────────────
    # 有多个 tier 同时通过时，用 final_score 分层
    g1_pass = stock.get("tier_g1") == "L1"
    g2_pass = stock.get("tier_g2") == "L2"
    g3_pass = stock.get("tier_g3") == "L3"
    pass_count = sum([g1_pass, g2_pass, g3_pass])

    if final >= 75 and pass_count >= 2:
        final_tier = "L1"
        signal = "BUY"
    elif final >= 60 and pass_count >= 1:
        final_tier = "L2"
        signal = "BUY"
    elif final >= 45:
        final_tier = "L3"
        signal = "WATCH"
    else:
        final_tier = "L4"
        signal = "AVOID"

    # 板块极端弱势 → 梯度降权（P3 tier 越低降得越多）
    if sector_label == "cold" and final_tier in ("L1", "L2"):
        if sector_p3_tier == "L4":
            final_tier = "L3"
            signal = "WATCH"
        elif sector_p3_tier == "L3":
            if final_tier == "L1":
                final_tier = "L2"
                signal = "BUY"

    # ── 理由 ───────────────────────────────────────────────
    reasons = []
    if g1_pass:
        reasons.append(f"G1✅(score={s1:.0f})")
    if g2_pass:
        reasons.append(f"G2✅(score={s2:.0f})")
    if g3_pass:
        reasons.append(f"G3✅(score={s3:.0f}, p_up={stock.get('p_up', 'N/A')})")
    if sector_label == "hot":
        reasons.append(f"🔥{sector_ticker}强势(P3 {sector_p3_tier})+{sector_adj}分")
    elif sector_label == "cold":
        reasons.append(f"❄️{sector_ticker}弱势(P3 {sector_p3_tier}){sector_adj}分")

    # P3 预警透传到股票
    if sector_warnings:
        for w in sector_warnings[:1]:  # 只取第一条
            reasons.append(f"⚠️板块预警: {w[2:] if w[2:] in w else w}")

    reason_str = " | ".join(reasons) if reasons else "无明确信号"

    return {
        "ticker":           stock.get("ticker", ""),
        "close":            stock.get("close", 0),
        "final_score":     round(final, 1),
        "final_tier":      final_tier,
        "signal":          signal,
        "weights_used":     {"g1": g1_w, "g2": g2_w, "g3": g3_w},
        "g1_contrib":      round(s1 * g1_w, 1),
        "g2_contrib":      round(s2 * g2_w, 1),
        "g3_contrib":      round(s3 * g3_w, 1),
        "sector":          sector_ticker,
        "sector_label":    sector_label,
        "sector_adjustment": sector_adj,
        "regime_score":    regime_score,
        "regime":          p2_regime.get("regime", "UNKNOWN"),
        "sector_p3_tier":  sector_p3_tier,
        "sector_warnings":  sector_warnings,
        "reason":          reason_str,
        # 透传各策略结果
        "g1": {"tier": stock.get("tier_g1"), "score": s1},
        "g2": {"tier": stock.get("tier_g2"), "score": s2},
        "g3": {"tier": stock.get("tier_g3"), "score": s3, "p_up": stock.get("p_up")},
    }


def rank_pool(candidates: list[dict], p2_regime: dict, p3_sectors: dict) -> list[dict]:
    """
    对候选池所有股票执行综合评判，返回排序后的列表。

    返回按 final_score 降序排列。
    """
    results = []
    for stock in candidates:
        scored = synthesize(stock, p2_regime, p3_sectors)
        results.append(scored)

    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results


def print_recommendations(ranked: list[dict], top_n: int = 20):
    """打印推荐结果"""
    l1 = [r for r in ranked if r["final_tier"] == "L1"]
    l2 = [r for r in ranked if r["final_tier"] == "L2"]
    l3 = [r for r in ranked if r["final_tier"] == "L3"]

    print(f"\n  【综合推荐】")
    print(f"  L1(强烈推荐): {len(l1)} 只")
    print(f"  L2(推荐):     {len(l2)} 只")
    print(f"  L3(观察):    {len(l3)} 只")
    print()

    if l1:
        print(f"  {'标的':<10} {'综合分':>7}  {'G1':>6}  {'G2':>6}  {'G3':>6}  {'板块':>6}  权重(G1/G2/G3)  理由")
        print("  " + "-"*90)
        for r in l1[:top_n]:
            w = r["weights_used"]
            print(f"  {r['ticker']:<10} {r['final_score']:>6.1f}  "
                  f"{r['g1']['score']:>6.1f}  {r['g2']['score']:>6.1f}  "
                  f"{r['g3']['score']:>6.1f}  "
                  f"{r['sector']:>6}  "
                  f"({w['g1']:.0%}/{w['g2']:.0%}/{w['g3']:.0%})")


def save_html_report(ranked: list[dict], p2_regime: dict, p3_sectors: dict,
                     date: str | None = None, output_dir=None) -> Path:
    """
    将 P4 综合评判结果保存为 HTML 报告。
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent.parent))
    from layout_shared.template import save_report

    regime = p2_regime.get("regime", "UNKNOWN")
    regime_score = p2_regime.get("score", 0)
    regime_str = f"{regime} ({regime_score}/10)"

    l1 = [r for r in ranked if r["final_tier"] == "L1"]
    l2 = [r for r in ranked if r["final_tier"] == "L2"]
    l3 = [r for r in ranked if r["final_tier"] == "L3"]
    l4 = [r for r in ranked if r["final_tier"] == "L4"]

    # 全部推荐合并（top_n per tier）
    all_rows = []
    for tier_name, tier_list in [("L1", l1), ("L2", l2), ("L3", l3)]:
        for r in tier_list[:20]:
            w = r.get("weights_used", {})
            g1_score = r.get("g1", {}).get("score", 0)
            g2_score = r.get("g2", {}).get("score", 0)
            g3_score = r.get("g3", {}).get("score", 0)
            all_rows.append([
                f'<strong style="color:#58a6ff">{r["ticker"]}</strong>',
                tier_name,
                f'<strong>{r["final_score"]:.1f}</strong>',
                f'{g1_score:.0f}' if g1_score > 0 else "-",
                f'{g2_score:.0f}' if g2_score > 0 else "-",
                f'{g3_score:.0f}' if g3_score > 0 else "-",
                r.get("sector", ""),
                f'{w.get("g1",0):.0%}/{w.get("g2",0):.0%}/{w.get("g3",0):.0%}',
                r.get("reason", "")[:50],
            ])

    sections = [
        {
            "title": f"📋 综合推荐池（全部 {len(ranked)} 只）",
            "type": "table",
            "headers": ["标的", "Tier", "综合分", "G1", "G2", "G3", "板块", "权重", "理由"],
            "rows": all_rows,
        },
    ]

    meta = {
        "Regime": regime_str,
        "L1(强烈推荐)": f"{len(l1)} 只",
        "L2(推荐)": f"{len(l2)} 只",
        "L3(观察)": f"{len(l3)} 只",
        "L4(回避)": f"{len(l4)} 只",
    }

    summary = (
        f"Regime「{regime}」，推荐 L1 {len(l1)} 只 / L2 {len(l2)} 只 / L3 {len(l3)} 只。"
        f"完整推荐池共 {len(ranked)} 只。"
    )

    return save_report(
        phase="P4",
        date=date or "",
        title="P4 · 择股层",
        subtitle="G1/G2/G3 综合评判",
        sections=sections,
        meta=meta,
        summary=summary,
        output_dir=output_dir,
    )
