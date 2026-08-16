#!/usr/bin/env python3
"""
G3 策略 — ML 概率预测
=====================
XGBoost 模型预测 5 日后上涨概率 P_up
用法：
    python3 fintech/p4/g3_screener.py              # 扫描全市场
    python3 fintech/p4/g3_screener.py --ticker AAPL  # 单股评估
    python3 fintech/p4/g3_screener.py --regime "超强牛市" --score 9.5
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
KLINES_DIR  = PROJECT_ROOT / "中间过程" / "klines"

# 需要 PROJECT_ROOT（而非 fintech/ 子目录）才能 import fintech.p4.ml.xxx
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "fintech"))  # 也保留，兼容其他导入
from p1.features import calc_all_factors

# ─── 共享工具（与 G1/G2 保持一致）───────────────────────────────────────────

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

# ─── ML 模型加载与预测（使用已训练的 winrate_predictor）────────────────────

_wrp = None   # WinratePredictor instance

def _load_ml_model():
    """
    懒加载 WinratePredictor（sklearn 胜率预测模型）。
    使用 WinratePredictor.load() 而非 joblib.load，
    因为 save() 保存的是 dict 而非对象本身。
    """
    global _wrp
    if _wrp is not None:
        return _wrp
    try:
        from fintech.p4.ml.winrate_predictor import WinratePredictor
        model_path = PROJECT_ROOT / "fintech" / "p4" / "ml" / "models" / "winrate_model.pkl"
        wr = WinratePredictor()
        wr.load(str(model_path))
        _wrp = wr
        print(f"  [G3] ML胜率模型加载成功")
        return wr
    except Exception as e:
        print(f"  [G3] ML模型加载失败: {e}")
        _wrp = None
        return None

def predict_pup(ticker: str) -> float | None:
    """
    对单只股票执行 ML P_up 预测（使用 WinratePredictor）。
    返回 P_up（上涨概率），或 None（无法预测）。
    """
    wr = _load_ml_model()
    if wr is None:
        return None

    ticker_path = KLINES_DIR / f"{ticker}_1d.json"
    if not ticker_path.exists():
        return None
    with open(ticker_path) as f:
        raw = json.load(f)
    klines = raw.get("data", raw)
    if len(klines) < 60:
        return None

    # 加载 SPY（用于相对强度等因子）
    spy_kl, vix_kl = _load_spy_vix()
    klines_dict = {"data": klines}
    for bar in klines_dict["data"]:
        if "date" in bar and "ymd" not in bar:
            bar["ymd"] = bar.pop("date")
        if "volume" in bar and "vol" not in bar:
            bar["vol"] = bar.pop("volume")

    spy_dict = None
    if spy_kl:
        spy_dict = {"data": spy_kl}
        for bar in spy_dict["data"]:
            if "date" in bar and "ymd" not in bar:
                bar["ymd"] = bar.pop("date")
            if "volume" in bar and "vol" not in bar:
                bar["vol"] = bar.pop("volume")

    try:
        factors = calc_all_factors(ticker, klines_dict, spy_dict, vix_kl)
        proba = wr.predict_proba(factors)
        return float(proba.get("P_up", 0.0))
    except Exception:
        return None

# ─── G3 核心评分逻辑 ────────────────────────────────────────────────────────

def score_g3(ind: dict, regime: str, p_up: float = None) -> tuple:
    """
    G3 ML 概率预测评分。
    返回 (tier, score, reasons)
    tier: 'L1'/'L2'/'L3'/'L4'/'NONE'
    """
    rsi      = ind["rsi14"]
    rsi_zone = ind["rsi_zone"]

    is_bull  = "牛市" in regime or "超强牛市" in regime or "一般牛市" in regime
    is_range = "震荡" in regime
    is_bear  = "熊市" in regime or "走弱" in regime or "回调" in regime

    if p_up is None:
        return "NONE", 0.0, []

    # ── 牛市：P_up >= 0.45 即通过 ──────────────────────────────────
    if is_bull:
        if p_up >= 0.45:
            tier = "L3"
            score = p_up * 100
            reasons = [f"ML P_up={p_up:.1%}"]
        else:
            tier = "NONE"; score = 0.0; reasons = []

    # ── 震荡市：P_up >= 0.45 ────────────────────────────────────────
    elif is_range:
        if p_up >= 0.45:
            tier = "L3"
            score = p_up * 100
            reasons = [f"ML P_up={p_up:.1%}"]
        else:
            tier = "NONE"; score = 0.0; reasons = []

    # ── 熊市：P_up >= 0.55（更高阈值）───────────────────────────────
    elif is_bear:
        if p_up >= 0.55:
            tier = "L3"
            score = p_up * 100
            reasons = [f"ML P_up={p_up:.1%}"]
        elif p_up >= 0.45:
            # 熊市降级为观察
            tier = "L4"
            score = p_up * 80
            reasons = [f"ML信号弱 P_up={p_up:.1%}(熊市阈值不足)"]
        else:
            tier = "NONE"; score = 0.0; reasons = []
    else:
        tier = "NONE"; score = 0.0; reasons = []

    return tier, round(score, 1), reasons


# ─── G3 扫描器 ──────────────────────────────────────────────────────────────

def scan_g3(regime: str = "超强牛市", regime_score: float = 8.0) -> tuple:
    """
    扫描全市场 G3 标的。

    返回 (regime, regime_score, candidates)
    candidates: {"L1": [...], "L2": [...], "L3": [...], "L4": [...]}
    （注：G3 输出以 L3/L4 为主）
    """
    exclude = {"SPY","QQQ","SOXX","VIX","DXY","TNX","GLD","GDX",
               "IBIT","COIN","BLOK","USD","EUR","BTC","ETH"}
    files = [f.stem.split("_")[0] for f in KLINES_DIR.glob("*_1d.json")
             if f.stem.split("_")[0] not in exclude]

    candidates = {"L1": [], "L2": [], "L3": [], "L4": []}

    print(f"  [G3] Regime: {regime} (score={regime_score})")
    print(f"  [G3] 扫描 {len(files)} 只股票...")

    # 预热 ML 模型
    _load_ml_model()

    for i, ticker in enumerate(files):
        ind = _compute_indicators(ticker)
        if not ind or ind["close"] < 5:
            continue

        p_up = None
        try:
            p_up = predict_pup(ticker)
        except Exception:
            pass

        tier, score, reasons = score_g3(ind, regime, p_up)
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
                "p_up":       p_up,
                "tier_g3":    tier,
                "score_g3":   score,
                "reasons_g3": reasons,
            }
            candidates[tier].append(entry)

        if (i + 1) % 30 == 0:
            print(f"    {i+1}/{len(files)} ...")

    for tier in candidates:
        candidates[tier].sort(key=lambda x: x["score_g3"], reverse=True)

    print(f"  [G3] 完成: L1={len(candidates['L1'])} L2={len(candidates['L2'])} "
          f"L3={len(candidates['L3'])} L4={len(candidates['L4'])}")
    return regime, regime_score, candidates


# ─── CLI 入口 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="G3 ML 概率预测策略")
    parser.add_argument("--ticker", type=str, default=None, help="单股代码")
    parser.add_argument("--regime", type=str, default="超强牛市")
    parser.add_argument("--score", type=float, default=8.0)
    args = parser.parse_args()

    if args.ticker:
        ind = _compute_indicators(args.ticker.upper())
        if not ind:
            print(f"[G3] 未找到 {args.ticker}")
            sys.exit(1)
        p_up = predict_pup(args.ticker.upper())
        tier, score, reasons = score_g3(ind, args.regime, p_up)
        print(f"[G3] {args.ticker} | tier={tier} score={score} p_up={p_up:.1%}" if p_up else
              f"[G3] {args.ticker} | tier={tier} score={score} p_up=N/A")
        for r in reasons:
            print(f"  - {r}")
    else:
        regime, regime_score, candidates = scan_g3(args.regime, args.score)
        print(f"\n  G3 结果: L3={len(candidates['L3'])} L4={len(candidates['L4'])}")
        if candidates["L3"]:
            print("\n  Top L3 (ML信号):")
            for x in candidates["L3"][:5]:
                pup_str = f"p_up={x.get('p_up', 0):.1%}" if x.get("p_up") else "p_up=N/A"
                print(f"    {x['ticker']} ${x['close']} RSI={x['rsi']} "
                      f"{pup_str} score={x['score_g3']}")
