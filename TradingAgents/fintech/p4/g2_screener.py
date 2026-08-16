#!/usr/bin/env python3
"""
G2 策略 — 低吸 / 回踩买入
==========================
强势股 RSI 回踩到 PULLBACK/OVERSOLD 区间时介入
用法：
    python3 fintech/p4/g2_screener.py              # 扫描全市场
    python3 fintech/p4/g2_screener.py --ticker AAPL  # 单股评估
    python3 fintech/p4/g2_screener.py --regime "超强牛市" --score 9.5
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
KLINES_DIR  = PROJECT_ROOT / "中间过程" / "klines"

sys.path.insert(0, str(PROJECT_ROOT / "fintech"))
from p1.features import calc_all_factors

# ─── 共享工具（与 G1 保持一致）───────────────────────────────────────────────

_spy_klines = None
_vix_klines = None

def _load_spy_vix():
    global _spy_klines, _vix_klines
    if _spy_klines is None:
        p = KLINES_DIR / "SPY_1d.json"
        if p.exists():
            with open(p) as f:
                raw = json.load(f)
            _spy_klines = raw.get("data", raw)
    if _vix_klines is None:
        p = KLINES_DIR / "VIX_1d.json"
        if p.exists():
            with open(p) as f:
                raw = json.load(f)
            _vix_klines = {"data": raw.get("data", raw)}
    return _spy_klines, _vix_klines

def _p1_to_g123(p1_factors: dict) -> dict:
    ma5_val = float(p1_factors.get("ma5") or 0)
    close   = float(p1_factors.get("close") or ma5_val)
    ema20   = float(p1_factors.get("ema20") or 0)
    rsi     = float(p1_factors.get("rsi14", 50.0))
    dist_ema20 = (close / ema20 - 1) * 100 if ema20 else 0.0

    if rsi > 75:       rsi_zone = "OVERBOUGHT"
    elif rsi > 65:     rsi_zone = "BULL_CONFIRM"
    elif rsi >= 45:    rsi_zone = "OPTIMAL"
    elif rsi >= 30:    rsi_zone = "PULLBACK"
    else:               rsi_zone = "OVERSOLD"

    trend_raw = float(p1_factors.get("trend_score", 0))
    trend = 1 if trend_raw >= 12 else -1 if trend_raw <= 5 else 0

    ret20 = p1_factors.get("return_20d")
    mom20 = round(float(ret20) * 100, 1) if ret20 else 0.0

    bb_pos = float(p1_factors.get("bb_pos", 0.5))
    bb_pct = round(bb_pos * 100, 1)

    ma20_val   = float(p1_factors.get("ma20") or 0)
    vol20_std  = float(p1_factors.get("vol20_std") or 0)
    bb_upper_v = ma20_val + 2 * vol20_std if vol20_std else None
    bb_lower_v = ma20_val - 2 * vol20_std if vol20_std else None

    vol_ratio = float(p1_factors.get("vol_ratio", 1.0))
    if vol_ratio > 10:
        vol_ratio /= 100.0

    atr14 = float(p1_factors.get("atr14") or 0)

    return {
        "ticker":     p1_factors.get("ticker", ""),
        "close":      round(close, 2),
        "ema20":      round(ema20, 2),
        "rsi14":      round(rsi, 1),
        "atr14":      round(atr14, 2),
        "bb_pct":     bb_pct,
        "mom20":      mom20,
        "dist_ema20": round(dist_ema20, 2),
        "trend":      trend,
        "rsi_zone":   rsi_zone,
        "vol_ratio":  round(vol_ratio, 2),
        "bb_upper":   round(bb_upper_v, 2) if bb_upper_v else None,
        "bb_lower":   round(bb_lower_v, 2) if bb_lower_v else None,
    }

def _compute_indicators(ticker: str) -> dict | None:
    spy_kl, vix_kl = _load_spy_vix()
    if spy_kl is None:
        return None
    ticker_path = KLINES_DIR / f"{ticker}_1d.json"
    if not ticker_path.exists():
        return None
    with open(ticker_path) as f:
        raw = json.load(f)
    klines = {"data": raw.get("data", raw)}
    for bar in klines.get("data", []):
        if "date" in bar and "ymd" not in bar:
            bar["ymd"] = bar.pop("date")
        if "volume" in bar and "vol" not in bar:
            bar["vol"] = bar.pop("volume")

    spy_dict = {"data": spy_kl}
    for bar in spy_dict.get("data", []):
        if "date" in bar and "ymd" not in bar:
            bar["ymd"] = bar.pop("date")
        if "volume" in bar and "vol" not in bar:
            bar["vol"] = bar.pop("volume")

    try:
        factors = calc_all_factors(ticker, klines, spy_dict, vix_kl)
        return _p1_to_g123(factors)
    except Exception:
        return None

# ─── G2 核心评分逻辑 ────────────────────────────────────────────────────────

def score_g2(ind: dict, regime: str, p_up: float = None) -> tuple:
    """
    G2 低吸/回踩买入评分。
    返回 (tier, score, reasons)
    tier: 'L1'/'L2'/'L3'/'L4'/'NONE'
    """
    rsi      = ind["rsi14"]
    trend    = ind["trend"]
    mom20    = ind["mom20"]
    dist20   = ind["dist_ema20"]
    rsi_zone = ind["rsi_zone"]

    is_bull  = "牛市" in regime or "超强牛市" in regime or "一般牛市" in regime
    is_range = "震荡" in regime
    is_bear  = "熊市" in regime or "走弱" in regime or "回调" in regime

    # ── 牛市：回踩低吸 ─────────────────────────────────────────────
    if is_bull:
        # 核心：趋势股回踩到 PULLBACK/OVERSOLD
        if trend == 1 and rsi_zone in ("PULLBACK", "OVERSOLD") and dist20 > -15:
            tier = "L2"
            score = min(100, 40 + abs(rsi - 35) + dist20 * -1)
            reasons = [f"趋势回踩 RSI={rsi}(低吸区间)", f"距EMA20: {dist20:+.1f}%"]
        # 延伸：强势股追涨（RSI 理想区间也接受）
        elif trend == 1 and rsi_zone in ("OPTIMAL", "BULL_CONFIRM") and mom20 > 0:
            tier = "L2"
            score = min(100, 30 + mom20 * 1.5)
            reasons = [f"强势趋势延续 RSI={rsi}", f"20日动量+{mom20:.1f}%"]
        elif trend == 1 and rsi_zone == "OVERSOLD" and dist20 <= -15:
            # 跌太深，降为 L3 观察
            tier = "L3"
            score = min(100, 30 + abs(rsi - 30))
            reasons = [f"超卖但偏离过大 RSI={rsi}", f"距EMA20: {dist20:+.1f}%"]
        else:
            tier = "NONE"; score = 0.0; reasons = []

    # ── 震荡市：支撑位低吸 ─────────────────────────────────────────
    elif is_range:
        if rsi_zone == "OVERSOLD" and trend >= 0:
            tier = "L2"
            score = min(100, 60 + (30 - rsi) * 2)
            reasons = [f"RSI={rsi}(超卖低吸)"]
        elif rsi_zone == "PULLBACK" and dist20 > -10:
            tier = "L2"
            score = min(100, 45 + (45 - rsi))
            reasons = [f"回调支撑 RSI={rsi}"]
        else:
            tier = "NONE"; score = 0.0; reasons = []

    # ── 熊市：超跌抢反弹 ───────────────────────────────────────────
    elif is_bear:
        if rsi_zone == "OVERSOLD" and p_up is not None and p_up >= 0.55:
            tier = "L2"
            score = p_up * 100
            reasons = [f"熊市超跌反弹 P_up={p_up:.1%}"]
        elif rsi_zone == "OVERSOLD":
            tier = "L3"
            score = min(100, 30 + (40 - rsi))
            reasons = [f"RSI={rsi}(超卖观察)"]
        else:
            tier = "NONE"; score = 0.0; reasons = []
    else:
        tier = "NONE"; score = 0.0; reasons = []

    return tier, round(score, 1), reasons


# ─── G2 扫描器 ──────────────────────────────────────────────────────────────

def scan_g2(regime: str = "超强牛市", regime_score: float = 8.0) -> tuple:
    """
    扫描全市场 G2 标的。

    返回 (regime, regime_score, candidates)
    candidates: {"L1": [...], "L2": [...], "L3": [...], "L4": [...]}
    （注：G2 输出以 L2/L3 为主，L1 在 G2 语境下为 L2）
    """
    exclude = {"SPY","QQQ","SOXX","VIX","DXY","TNX","GLD","GDX",
               "IBIT","COIN","BLOK","USD","EUR","BTC","ETH"}
    files = [f.stem.split("_")[0] for f in KLINES_DIR.glob("*_1d.json")
             if f.stem.split("_")[0] not in exclude]

    candidates = {"L1": [], "L2": [], "L3": [], "L4": []}

    print(f"  [G2] Regime: {regime} (score={regime_score})")
    print(f"  [G2] 扫描 {len(files)} 只股票...")

    for i, ticker in enumerate(files):
        ind = _compute_indicators(ticker)
        if not ind or ind["close"] < 5:
            continue

        tier, score, reasons = score_g2(ind, regime)
        if tier != "NONE" and score > 0:
            entry = {
                "ticker":     ticker,
                "close":      ind["close"],
                "rsi":        ind["rsi14"],
                "rsi_zone":   ind["rsi_zone"],
                "trend":      "↑" if ind["trend"] == 1 else "↓" if ind["trend"] == -1 else "→",
                "mom20":      ind["mom20"],
                "dist_ema20": ind["dist_ema20"],
                "atr14":      ind["atr14"],
                "bb_pct":     ind["bb_pct"],
                "vol_ratio":  ind["vol_ratio"],
                "tier_g2":    tier,
                "score_g2":   score,
                "reasons_g2": reasons,
            }
            candidates[tier].append(entry)

        if (i + 1) % 30 == 0:
            print(f"    {i+1}/{len(files)} ...")

    for tier in candidates:
        candidates[tier].sort(key=lambda x: x["score_g2"], reverse=True)

    print(f"  [G2] 完成: L1={len(candidates['L1'])} L2={len(candidates['L2'])} "
          f"L3={len(candidates['L3'])} L4={len(candidates['L4'])}")
    return regime, regime_score, candidates


# ─── CLI 入口 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="G2 低吸/回踩策略")
    parser.add_argument("--ticker", type=str, default=None, help="单股代码")
    parser.add_argument("--regime", type=str, default="超强牛市")
    parser.add_argument("--score", type=float, default=8.0)
    args = parser.parse_args()

    if args.ticker:
        ind = _compute_indicators(args.ticker.upper())
        if not ind:
            print(f"[G2] 未找到 {args.ticker}")
            sys.exit(1)
        tier, score, reasons = score_g2(ind, args.regime)
        print(f"[G2] {args.ticker} | tier={tier} score={score}")
        for r in reasons:
            print(f"  - {r}")
    else:
        regime, regime_score, candidates = scan_g2(args.regime, args.score)
        print(f"\n  G2 结果: L2={len(candidates['L2'])} L3={len(candidates['L3'])} "
              f"L4={len(candidates['L4'])}")
        if candidates["L2"]:
            print("\n  Top L2 (低吸机会):")
            for x in candidates["L2"][:5]:
                print(f"    {x['ticker']} ${x['close']} RSI={x['rsi']} "
                      f"dist_ema20={x['dist_ema20']:+.1f}% score={x['score_g2']}")
