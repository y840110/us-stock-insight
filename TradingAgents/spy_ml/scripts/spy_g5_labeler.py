#!/usr/bin/env python3
"""
spy_g5_labeler.py
=================
SPY 有监督学习标签生成器（G5 导数极值法）

打标逻辑（两种标签）：

  【标签A – 牛熊日分类】
    对 SPY 中点价做 Gaussian 平滑 (sigma=5)
    找一阶导数变号点 = 极值点（峰/谷）
    相邻极值之间：价格上涨 = 牛市(1)，价格下跌 = 熊市(0)
    间隔<5天且变化<2% = 震荡(0.5)

  【标签B – 变盘点分类（修复版）】
    未来10日内从当时高点回撤>5% → 今天标记为"变盘预警"(1)
    否则 → 非变盘点(0)
    理由：这更符合实盘需求——今天出现某种价格/量形态，
          未来10天内市场是否会变盘？

使用方法：
  python3 spy_g5_labeler.py                    # 生成所有数据
  python3 spy_g5_labeler.py --check           # 检查数据
"""

import json, csv, sys
import numpy as np
from scipy.ndimage import gaussian_filter1d
from pathlib import Path

PROJ = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析")
SPY_KLINE   = PROJ / "TradingAgents/中间过程/klines/SPY_1d.json"
OUT_SEGMENTS  = PROJ / "spy_g5_segments.json"
OUT_DAILY_CSV = PROJ / "spy_g5_daily_labels.csv"

MIN_GAP  = 5
MIN_DUR  = 5
MIN_CHG  = 2.0




def load_spy(start_date="2020-01-01"):
    bars = []
    with open(SPY_KLINE) as f:
        d = json.load(f)
        raw = d.get("data", d) if isinstance(d, dict) else d
        while isinstance(raw, dict): raw = raw.get("data", [])
        for b in raw:
            if b["date"] < start_date:
                continue
            bars.append({
                "date":   b["date"],
                "mid":    (float(b["high"]) + float(b["low"])) / 2,
                "close":  float(b["close"]),
                "high":   float(b["high"]),
                "low":    float(b["low"]),
                "volume": float(b["volume"]),
            })
    return bars


def find_extrema(curve, dates, min_gap=MIN_GAP):
    d1 = np.gradient(curve, 1.0)
    sc = np.where(np.diff(np.sign(d1)))[0]
    extrema = []
    prev_idx = -min_gap
    for idx in sc:
        if idx - prev_idx < min_gap:
            continue
        d2 = np.gradient(d1, 1.0)
        curv = d2[idx]
        extrema.append({
            "idx":   int(idx),
            "date":  dates[idx],
            "price": float(curve[idx]),
            "type":  "peak" if curv < 0 else "valley",
            "curv":  float(abs(curv)),
        })
        prev_idx = idx
    return extrema


def build_segments(mids, dates, extrema):
    N = len(mids)
    all_idx = [0] + [e["idx"] for e in extrema] + [N - 1]
    all_dts = [dates[0]] + [e["date"] for e in extrema] + [dates[-1]]
    segments = []
    for i in range(len(all_idx) - 1):
        si, ei = int(all_idx[i]), int(all_idx[i + 1])
        ps, pe = float(mids[si]), float(mids[ei])
        chg = (pe - ps) / ps * 100
        dur = ei - si
        if dur < MIN_DUR and abs(chg) < MIN_CHG:
            st = "range"
        elif chg > 0:
            st = "bull"
        else:
            st = "bear"
        segments.append({
            "start_date":  all_dts[i],
            "end_date":    all_dts[i + 1],
            "type":        st,
            "chg_pct":     round(float(chg), 4),
            "duration":     int(dur),
            "start_idx":    si,
            "end_idx":      ei,
            "start_price": round(ps, 4),
            "end_price":   round(pe, 4),
        })
    return segments


def assign_bullbear_labels(segments, dates):
    """bull=1, bear=0, range=0.5"""
    label_map = {}
    for seg in segments:
        for idx in range(seg["start_idx"], seg["end_idx"] + 1):
            d = dates[idx]
            label_map[d] = (1.0 if seg["type"] == "bull"
                             else 0.0 if seg["type"] == "bear" else 0.5)
    return label_map


def assign_shift_labels(extrema, dates):
    """
    【标签B – 变盘点】
    仅将 G5 极值点（峰/谷）当天标记为 shift=1
    不做任何窗口扩散，不使用未来回撤数据
    """
    shift_dates = {e["date"] for e in extrema}
    label_map = {d: (1.0 if d in shift_dates else 0.0) for d in dates}
    return label_map

    return label_map


def compute_features(bars):
    n = len(bars)
    dates  = [b["date"]  for b in bars]
    mids   = np.array([b["mid"]    for b in bars], dtype=float)
    closes = np.array([b["close"]  for b in bars], dtype=float)
    highs  = np.array([b["high"]   for b in bars], dtype=float)
    lows   = np.array([b["low"]    for b in bars], dtype=float)
    vols   = np.array([b["volume"] for b in bars], dtype=float)

    def ema(data, period):
        k = 2 / (period + 1)
        out = np.zeros_like(data)
        out[0] = data[0]
        for i in range(1, len(data)):
            out[i] = data[i] * k + out[i - 1] * (1 - k)
        return out

    def ma(data, period):
        return np.convolve(data, np.ones(period) / period, mode="same")

    ema5   = ema(closes, 5)
    ema20  = ema(closes, 20)
    ema50  = ema(closes, 50)

    ret_1d  = np.zeros(n)
    ret_5d  = np.zeros(n)
    ret_20d = np.zeros(n)
    for i in range(1, n):  ret_1d[i]  = (closes[i] / closes[i-1] - 1) * 100
    for i in range(5, n):  ret_5d[i]  = (closes[i] / closes[i-5] - 1) * 100
    for i in range(20, n): ret_20d[i] = (closes[i] / closes[i-20] - 1) * 100

    def rolling_std(x, window):
        out = np.zeros_like(x, dtype=float)
        for i in range(window, len(x)):
            out[i] = float(np.std(x[i-window:i]))
        return out

    vol5  = rolling_std(ret_1d, 5)
    vol20 = rolling_std(ret_1d, 20)

    # ATR
    tr = np.zeros(n - 1)
    for i in range(1, n):
        h_l = highs[i] - lows[i]
        h_c = abs(highs[i] - closes[i - 1])
        l_c = abs(lows[i]  - closes[i - 1])
        tr[i - 1] = max(h_l, h_c, l_c)
    atr = np.zeros(n)
    atr[1:] = ema(tr, 14)
    atr_pct = atr / closes * 100

    # RSI
    def calc_rsi(price, period=14):
        deltas = np.diff(price)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.zeros(len(price))
        avg_loss = np.zeros(len(price))
        avg_gain[period] = np.mean(gains[:period])
        avg_loss[period] = np.mean(losses[:period])
        for i in range(period + 1, len(price)):
            avg_gain[i] = (avg_gain[i-1] * (period-1) + gains[i-1]) / period
            avg_loss[i] = (avg_loss[i-1] * (period-1) + losses[i-1]) / period
        rs = avg_gain / (avg_loss + 1e-10)
        return 100 - 100 / (1 + rs)

    rsi    = calc_rsi(closes, 14)
    macd_l = ema(closes, 12) - ema(closes, 26)
    macd_s = ema(macd_l, 9)
    macd   = macd_l / closes * 100
    macd_h = (macd_l - macd_s) / closes * 100

    bb_mid  = ma(closes, 20)
    bb_std  = rolling_std(closes, 20)
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_pos  = (closes - bb_lower) / (bb_upper - bb_lower + 1e-10)

    ma5_dev  = (closes - ema5)  / ema5  * 100
    ma20_dev = (closes - ema20) / ema20 * 100
    ma50_dev = (closes - ema50) / ema50 * 100

    low20   = np.array([min(closes[max(0,i-20):i+1]) for i in range(n)])
    high20  = np.array([max(closes[max(0,i-20):i+1]) for i in range(n)])
    price_in_range = (closes - low20) / (high20 - low20 + 1e-10)

    momentum = np.zeros(n)
    for i in range(20, n):
        momentum[i] = (closes[i] / closes[i-20] - 1) * 100

    vol_ma20  = ma(vols, 20)
    vol_ratio = vols / (vol_ma20 + 1)
    vol_trend = np.zeros(n)
    for i in range(20, n):
        vol_trend[i] = (vol_ma20[i] / (vol_ma20[i-20] + 1) - 1) * 100

    pv_conflict = np.where((ret_5d > 0) & (vol_ratio < 0.9), 1.0, 0.0)

    decline_vol_ratio = np.zeros(n)
    for i in range(20, n):
        win_v = vols[i-20:i+1]
        win_c = closes[i-20:i+1]
        dec_v = [win_v[j] for j in range(1, 21) if win_c[j] < win_c[j-1]]
        if dec_v:
            decline_vol_ratio[i] = np.mean(dec_v) / (np.mean(win_v) + 1)

    return {
        "date": dates,
        "close": closes.tolist(),
        "mid":   mids.tolist(),
        "ret_1d":        ret_1d.tolist(),
        "ret_5d":        ret_5d.tolist(),
        "ret_20d":       ret_20d.tolist(),
        "volatility_5d":  vol5.tolist(),
        "volatility_20d": vol20.tolist(),
        "atr_pct":        atr_pct.tolist(),
        "rsi_14":         rsi.tolist(),
        "macd":           macd.tolist(),
        "macd_hist":      macd_h.tolist(),
        "ma5_dev":       ma5_dev.tolist(),
        "ma20_dev":      ma20_dev.tolist(),
        "ma50_dev":      ma50_dev.tolist(),
        "bb_position":    bb_pos.tolist(),
        "momentum":       momentum.tolist(),
        "vol_ratio":     vol_ratio.tolist(),
        "vol_trend":     vol_trend.tolist(),
        "pv_conflict":   pv_conflict.tolist(),
        "decline_vol_ratio": decline_vol_ratio.tolist(),
        "price_in_range": price_in_range.tolist(),
    }


def main():
    print("Loading SPY data...")
    bars = load_spy("2020-01-01")
    dates = [b["date"] for b in bars]
    mids  = np.array([b["mid"] for b in bars], dtype=float)
    N = len(mids)
    print(f"  {N} days: {dates[0]} → {dates[-1]}")

    print("G5 smoothing & extrema detection...")
    curve = gaussian_filter1d(mids, sigma=5)
    extrema = find_extrema(curve, dates, MIN_GAP)
    segments = build_segments(mids, dates, extrema)
    bull_n = sum(1 for s in segments if s["type"] == "bull")
    bear_n = sum(1 for s in segments if s["type"] == "bear")
    print(f"  {len(extrema)} extrema, {len(segments)} segments: {bull_n} bull, {bear_n} bear")

    print("Computing features...")
    features = compute_features(bars)

    print("Assigning labels...")
    bb_label = assign_bullbear_labels(segments, dates)
    shift_label = assign_shift_labels(extrema, dates)

    bb_bull = sum(1 for v in bb_label.values() if v == 1.0)
    bb_bear = sum(1 for v in bb_label.values() if v == 0.0)
    sh_pos  = sum(1 for v in shift_label.values() if v == 1.0)
    sh_neg  = sum(1 for v in shift_label.values() if v == 0.0)
    print(f"  Label A (bull/bear): bull={bb_bull}  bear={bb_bear}")
    print(f"  Label B (shift):    shift={sh_pos}  safe={sh_neg}  (G5 extrema only)")

    # 保存 segments
    with open(OUT_SEGMENTS, "w") as f:
        json.dump({
            "method":  "gaussian_sigma5",
            "min_gap": MIN_GAP, "min_dur": MIN_DUR, "min_chg": MIN_CHG,
            "segments": segments, "extrema": extrema,
        }, f, indent=2, ensure_ascii=False)
    print(f"Saved: {OUT_SEGMENTS}")

    # 保存 daily CSV（含两种标签）
    FEATURE_COLS = [
        "date", "close", "mid",
        "label_bb", "label_shift",
        "ret_1d", "ret_5d", "ret_20d",
        "volatility_5d", "volatility_20d", "atr_pct",
        "rsi_14", "macd", "macd_hist",
        "ma5_dev", "ma20_dev", "ma50_dev",
        "bb_position", "momentum",
        "vol_ratio", "vol_trend",
        "pv_conflict", "decline_vol_ratio",
        "price_in_range",
    ]

    with open(OUT_DAILY_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FEATURE_COLS)
        w.writeheader()
        for i, d in enumerate(features["date"]):
            row = {
                "date":       d,
                "close":      round(features["close"][i], 4),
                "mid":        round(features["mid"][i], 4),
                "label_bb":   bb_label.get(d, ""),
                "label_shift": shift_label.get(d, ""),
            }
            for key in FEATURE_COLS[5:]:
                row[key] = round(float(features[key][i]), 6)
            w.writerow(row)
    print(f"Saved: {OUT_DAILY_CSV}")
    print("\nDone!")


if __name__ == "__main__":
    if "--check" in sys.argv:
        import csv as _csv
        if Path(OUT_DAILY_CSV).exists():
            rows = list(_csv.DictReader(open(OUT_DAILY_CSV)))
            bb  = [float(r["label_bb"])   for r in rows if r["label_bb"]]
            sh  = [float(r["label_shift"]) for r in rows if r["label_shift"]]
            print(f"Rows: {len(rows)}")
            print(f"Label A (bull/bear): bull={sum(1 for v in bb if v==1)}  bear={sum(1 for v in bb if v==0)}")
            print(f"Label B (shift):    shift={sum(1 for v in sh if v==1)}  safe={sum(1 for v in sh if v==0)}")
        else:
            print("No data — run without --check first")
    else:
        main()
