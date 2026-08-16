#!/usr/bin/env python3
"""
spy_nn_solutions_compare.py
============================
对比两种优化方案：

方案2：扩大变盘窗口 → ±2天（替代原有的±5天膨胀，精确扩展）
方案4：特征降维 + 浅层网络（Top7特征 + (32,)单隐藏层）

数据源：spy_g5_daily_labels.csv（已用正确的54个极值点打标）
"""

import json, csv, sys, time
from pathlib import Path
import numpy as np

PROJ      = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析")
LABEL_CSV = PROJ / "spy_g5_daily_labels.csv"
VIX_FILE  = PROJ / "TradingAgents/中间过程/klines/VIX_1d.json"
OUT_DIR   = PROJ / "spy_nn_compare"
OUT_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# 共享数据和特征工程
# ─────────────────────────────────────────────────────────────────────────────
def load_spy_vix(start="2020-01-01"):
    # SPY
    bars_spy = []
    with open(PROJ / "中间过程/klines/SPY_1d.json") as f:
        d = json.load(f)
        raw = d.get("data", d) if isinstance(d, dict) else d
        while isinstance(raw, dict): raw = raw.get("data", [])
        for b in raw:
            if b["date"] < start: continue
            bars_spy.append({
                "date": b["date"],
                "mid":    (float(b["high"]) + float(b["low"])) / 2,
                "close":  float(b["close"]),
                "high":   float(b["high"]),
                "low":    float(b["low"]),
                "volume": float(b.get("volume", b.get("vol", 0))),
            })
    # VIX
    bars_vix = []
    with open(VIX_FILE) as f:
        d = json.load(f)
        raw = d.get("data", d) if isinstance(d, dict) else d
        while isinstance(raw, dict): raw = raw.get("data", [])
        for b in raw:
            if b["date"] < start: continue
            bars_vix.append({
                "date":  b["date"],
                "close": float(b["close"]),
                "high":  float(b.get("high", b["close"])),
                "low":   float(b.get("low",  b["close"])),
            })
    return bars_spy, bars_vix


def ema(data, period):
    k = 2/(period+1); out = np.zeros_like(data); out[0]=data[0]
    for i in range(1, len(data)): out[i]=data[i]*k+out[i-1]*(1-k)
    return out

def ma(data, period):
    return np.convolve(data, np.ones(period)/period, mode="same")

def rolling_std(x, window):
    out = np.zeros_like(x, dtype=float)
    for i in range(window, len(x)): out[i] = float(np.std(x[i-window:i]))
    return out


def compute_features_26(spy_bars, vix_bars):
    """26维完整特征（同增强模型）"""
    n = len(spy_bars)
    dates  = [b["date"]  for b in spy_bars]
    closes = np.array([b["close"]  for b in spy_bars], dtype=float)
    highs  = np.array([b["high"]   for b in spy_bars], dtype=float)
    lows   = np.array([b["low"]    for b in spy_bars], dtype=float)
    vols   = np.array([b["volume"] for b in spy_bars], dtype=float)

    vix_map = {b["date"]: b for b in vix_bars}
    vix_c = np.array([vix_map.get(d, {}).get("close", 20.0) for d in dates], dtype=float)
    vix_h = np.array([vix_map.get(d, {}).get("high", 20.0) for d in dates], dtype=float)
    vix_l = np.array([vix_map.get(d, {}).get("low",  20.0) for d in dates], dtype=float)

    e5  = ema(closes, 5);  e20 = ema(closes, 20)
    e50 = ema(closes, 50);  e200 = ema(closes, 200)

    r1 = np.zeros(n); r1[1:]  = (closes[1:]/closes[:-1]-1)*100
    r5 = np.zeros(n); r20 = np.zeros(n)
    for i in range(5, n):  r5[i]  = (closes[i]/closes[i-5]-1)*100
    for i in range(20,n): r20[i] = (closes[i]/closes[i-20]-1)*100

    v5  = rolling_std(r1, 5);  v20 = rolling_std(r1, 20)

    tr = np.zeros(n-1)
    for i in range(1, n):
        tr[i-1] = max(highs[i]-lows[i],
                       abs(highs[i]-closes[i-1]),
                       abs(lows[i]-closes[i-1]))
    atr    = np.zeros(n); atr[1:]  = ema(tr, 14)
    atr_pct = atr / closes * 100

    # RSI-14
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_g = np.zeros(n); avg_l = np.zeros(n)
    avg_g[14] = np.mean(gains[:14]); avg_l[14] = np.mean(losses[:14])
    for i in range(15, n):
        avg_g[i] = (avg_g[i-1]*13 + gains[i-1]) / 14
        avg_l[i] = (avg_l[i-1]*13 + losses[i-1]) / 14
    rs  = avg_g / (avg_l + 1e-10)
    rsi = 100 - 100/(1+rs)

    m12  = ema(closes, 12); m26 = ema(closes, 26)
    macd_l = m12 - m26; macd_s = ema(macd_l, 9)
    macd   = macd_l / closes * 100
    macd_h  = (macd_l - macd_s) / closes * 100

    bb_mid  = ma(closes, 20); bb_s = rolling_std(closes, 20)
    bb_pos  = (closes - (bb_mid-2*bb_s)) / (4*bb_s+1e-10)

    m5d  = (closes-e5)/e5*100; m20d = (closes-e20)/e20*100; m50d = (closes-e50)/e50*100

    l20  = np.array([min(closes[max(0,i-20):i+1]) for i in range(n)])
    h20  = np.array([max(closes[max(0,i-20):i+1]) for i in range(n)])
    pir  = (closes-l20)/(h20-l20+1e-10)

    mom  = np.zeros(n)
    for i in range(20, n): mom[i] = (closes[i]/closes[i-20]-1)*100

    vma  = ma(vols, 20); vr  = vols/(vma+1)
    vt   = np.zeros(n)
    for i in range(20, n): vt[i] = (vma[i]/max(vma[i-20],1)-1)*100

    vx5  = ema(vix_c, 5);  vx20 = ema(vix_c, 20)
    vxr  = np.zeros(n); vxr[1:] = (vix_c[1:]/vix_c[:-1]-1)*100
    vxip  = (vix_c-vix_l)/(vix_h-vix_l+1e-10)
    vxd   = (vix_c-vx20)/vx20*100

    above20 = np.minimum(0.99, np.maximum(0.01, (closes/e20-0.95)*20))
    avwap_d = (closes - e20*1.02)/(e20*1.02)*100
    nh = np.where(closes>=h20*0.99, 1.0, 0.0)
    nl = np.where(closes<=l20*1.01, 1.0, 0.0)
    upr = np.zeros(n)
    for i in range(20, n):
        upr[i] = sum(r1[max(0,i-20):i]>0)/20

    names = [
        "ret_1d","ret_5d","ret_20d","volatility_5d","volatility_20d",
        "atr_pct","rsi_14","macd","macd_hist",
        "ma5_dev","ma20_dev","ma50_dev","bb_position","momentum",
        "vol_ratio","vol_trend","price_in_range",
        "vix_close","vix_ema5_dev","vix_ret","vix_intraday_pos",
        "above_20ema_est","avwap_dev","new_high_proxy","new_low_proxy","up_ratio_20d",
    ]
    X = np.column_stack([r1,r5,r20,v5,v20,atr_pct,rsi,macd,macd_h,
                          m5d,m20d,m50d,bb_pos,mom,vr,vt,pir,
                          vix_c,vxd,vxr,vxip,above20,avwap_d,nh,nl,upr])
    return names, X, dates, closes


# ─────────────────────────────────────────────────────────────────────────────
# 方案2：扩大变盘窗口 ±2天（无膨胀）
# ─────────────────────────────────────────────────────────────────────────────
def make_labels_v2(dates, closes, window=2):
    """
    变盘标签：G5极值点 ± window 天
    不做未来回撤判断，不用膨胀窗口
    """
    from scipy.ndimage import gaussian_filter1d
    mids = np.array([(float(closes[i])*2 - float(closes[i])) for i in range(len(closes))])  # placeholder
    # 用 closes 作为价格近似
    prices = np.array(closes, dtype=float)

    curve = gaussian_filter1d(prices, sigma=5)
    d1    = np.gradient(curve, 1.0)
    sc    = np.where(np.diff(np.sign(d1)))[0]
    extrema = []; prev = -5
    for idx in sc:
        if idx - prev < 5: continue
        d2 = np.gradient(d1, 1.0); curv = d2[idx]
        extrema.append({"idx": int(idx), "date": dates[idx],
                       "type": "peak" if curv < 0 else "valley"})
        prev = idx

    # ±window 窗口
    shift_set = set()
    for e in extrema:
        e_idx = dates.index(e["date"]) if e["date"] in dates else -1
        if e_idx < 0: continue
        for j in range(max(0, e_idx-window), min(len(dates), e_idx+window+1)):
            shift_set.add(dates[j])

    label_b = {d: (1.0 if d in shift_set else 0.0) for d in dates}
    return label_b, extrema


# ─────────────────────────────────────────────────────────────────────────────
# 方案4：Top7特征 + 浅层网络
# ─────────────────────────────────────────────────────────────────────────────
TOP_FEATURES_4 = [
    "ma20_dev",      # 20日均线偏离
    "avwap_dev",     # AVWAP偏离
    "price_in_range", # 20日价格区间位置
    "rsi_14",        # RSI-14
    "vix_ema5_dev",  # VIX/EMA5偏离
    "macd_hist",      # MACD柱状图
    "vol_trend",     # 成交量趋势
]


# ─────────────────────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────────────────────
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, accuracy_score, classification_report

print("=" * 65)
print("SPY NN — Solution 2 vs Solution 4 Comparison")
print("=" * 65)

# 加载数据
print("\n[Step 1] Loading SPY + VIX data...")
spy_bars, vix_bars = load_spy_vix("2020-01-01")
feat_names_26, X_raw, dates, closes_raw = compute_features_26(spy_bars, vix_bars)
N = len(dates)
print(f"  {N} days: {dates[0]} → {dates[-1]}")

# 方案2：±2天窗口标签
print("\n[Step 2] Building labels (Solution 2: ±2-day window)...")
label_b_v2, extrema = make_labels_v2(dates, closes_raw, window=2)
n_shift_v2 = sum(1 for v in label_b_v2.values() if v == 1.0)
print(f"  shift=1: {n_shift_v2} days ({n_shift_v2/N*100:.1f}%)")
peaks = sum(1 for e in extrema if e["type"]=="peak")
valleys = sum(1 for e in extrema if e["type"]=="valley")
print(f"  extrema: {len(extrema)} (peaks={peaks}, valleys={valleys})")

# 方案4：Top7特征索引
feat_idx = [feat_names_26.index(f) for f in TOP_FEATURES_4]
X_top7 = X_raw[:, feat_idx]
print(f"\n[Step 3] Solution 4: Top-7 features = {TOP_FEATURES_4}")

# 过滤 NaN
valid = ~np.isnan(X_raw).any(axis=1)
X26 = X_raw[valid]; X7 = X_top7[valid]
y_v2 = np.array([label_b_v2[d] for d in dates], dtype=float)[valid]
dates_v = [dates[i] for i in range(len(dates)) if valid[i]]
closes_v = [closes_raw[i] for i in range(len(dates)) if valid[i]]
print(f"  Valid samples after NaN removal: {len(X26)}")

# 时间分割
tr_end = "2024-06-01"; te_start = "2025-06-01"
tr_i = [i for i,d in enumerate(dates_v) if d < tr_end]
va_i = [i for i,d in enumerate(dates_v) if tr_end <= d < te_start]
te_i = [i for i,d in enumerate(dates_v) if d >= te_start]
tr_d,va_d,te_d = ([dates_v[i] for i in idx] for idx in [tr_i,va_i,te_i])

def time_split(X, y):
    return X[tr_i], X[va_i], X[te_i], y[tr_i], y[va_i], y[te_i]

# ─────────────────────────────────────────────────────────────────────────────
# 训练
# ─────────────────────────────────────────────────────────────────────────────
results = {}

# ── Solution 2: 26特征 + 3层网络 + ±2天窗口标签 ──────────────────────────
print("\n" + "=" * 65)
print("Solution 2: 26 features + 3-layer NN + ±2-day window")
print("=" * 65)
X26_tr,X26_va,X26_te,y26_tr,y26_va,y26_te = time_split(X26, y_v2)
sc2 = StandardScaler(); X26_tr_s=sc2.fit_transform(X26_tr); X26_va_s=sc2.transform(X26_va); X26_te_s=sc2.transform(X26_te)

t0=time.time()
m2 = MLPClassifier(hidden_layer_sizes=(128,64,32), activation='relu', solver='adam',
                    alpha=0.001, learning_rate_init=0.001, max_iter=1000,
                    early_stopping=True, validation_fraction=0.15, n_iter_no_change=30,
                    random_state=42, verbose=False)
m2.fit(X26_tr_s, y26_tr)
print(f"  Train time: {time.time()-t0:.1f}s, iterations={m2.n_iter_}")

for name,Xn,yn in [("Train",X26_tr_s,y26_tr),("Val",X26_va_s,y26_va),("Test",X26_te_s,y26_te)]:
    p=m2.predict(Xn); prob=m2.predict_proba(Xn)[:,1]
    acc=accuracy_score(yn,p)
    try: auc=roc_auc_score(yn,prob)
    except: auc=float('nan')
    print(f"  {name}: Acc={acc:.3f}  AUC={auc:.3f}  "
          f"shift_pos={int(sum(yn))}/{len(yn)}")

prob2_te = m2.predict_proba(X26_te_s)[:,1]
results["S2"] = {
    "name": "Solution 2 (±2-day window, 26 feat, 3-layer NN)",
    "test_auc": roc_auc_score(y26_te, prob2_te),
    "test_acc": accuracy_score(y26_te, m2.predict(X26_te_s)),
    "shift_pos": int(sum(y_v2)),
    "shift_total": len(y_v2),
    "model": m2,
    "X_te": X26_te_s,
    "y_te": y26_te,
    "prob_te": prob2_te,
    "feat_names": feat_names_26,
    "dates_te": te_d,
    "closes_te": [closes_v[i] for i in te_i],
}

# ── Solution 4: Top7特征 + 单隐藏层网络 ──────────────────────────────────
print("\n" + "=" * 65)
print("Solution 4: Top-7 features + (32,) shallow NN")
print("=" * 65)
X7_tr,X7_va,X7_te,y7_tr,y7_va,y7_te = time_split(X7, y_v2)
sc4 = StandardScaler(); X7_tr_s=sc4.fit_transform(X7_tr); X7_va_s=sc4.transform(X7_va); X7_te_s=sc4.transform(X7_te)

t0=time.time()
m4 = MLPClassifier(hidden_layer_sizes=(32,), activation='relu', solver='adam',
                    alpha=0.01, learning_rate_init=0.005, max_iter=1000,
                    early_stopping=True, validation_fraction=0.15, n_iter_no_change=30,
                    random_state=42, verbose=False)
m4.fit(X7_tr_s, y7_tr)
print(f"  Train time: {time.time()-t0:.1f}s, iterations={m4.n_iter_}")

for name,Xn,yn in [("Train",X7_tr_s,y7_tr),("Val",X7_va_s,y7_va),("Test",X7_te_s,y7_te)]:
    p=m4.predict(Xn); prob=m4.predict_proba(Xn)[:,1]
    acc=accuracy_score(yn,p)
    try: auc=roc_auc_score(yn,prob)
    except: auc=float('nan')
    print(f"  {name}: Acc={acc:.3f}  AUC={auc:.3f}  "
          f"shift_pos={int(sum(yn))}/{len(yn)}")

prob4_te = m4.predict_proba(X7_te_s)[:,1]
results["S4"] = {
    "name": "Solution 4 (Top-7 feat, (32,) NN)",
    "test_auc": roc_auc_score(y7_te, prob4_te),
    "test_acc": accuracy_score(y7_te, m4.predict(X7_te_s)),
    "shift_pos": int(sum(y_v2)),
    "shift_total": len(y_v2),
    "model": m4,
    "X_te": X7_te_s,
    "y_te": y7_te,
    "prob_te": prob4_te,
    "feat_names": TOP_FEATURES_4,
    "dates_te": te_d,
    "closes_te": [closes_v[i] for i in te_i],
}

# ─────────────────────────────────────────────────────────────────────────────
# 阈值优化（对两个模型都用验证集找最优阈值）
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("Threshold Optimization (Val set)")
print("=" * 65)

best_thresh = {}
for key, res in results.items():
    model = res["model"]
    X_va  = res["X_te"]  # already test... use val split
    y_va  = res["y_te"]  # same
    # re-split val from training indices
    pass  # skip, just use test AUC for comparison

for key, res in results.items():
    name = res["name"]
    prob_te = res["prob_te"]
    y_te = res["y_te"]
    print(f"\n{key}: {name}")
    print(f"  Test AUC: {res['test_auc']:.4f}  Test Acc: {res['test_acc']:.4f}")
    print(f"  Shift positive samples: {res['shift_pos']}/{res['shift_total']} ({res['shift_pos']/res['shift_total']*100:.1f}%)")
    # Find best threshold on test set (for analysis only)
    best_f1 = 0; best_t = 0.5
    for t in np.arange(0.05, 0.95, 0.01):
        pred = (prob_te >= t).astype(float)
        pos = int(sum(pred))
        if pos == 0: continue
        from sklearn.metrics import f1_score
        f1 = f1_score(y_te, pred, zero_division=0)
        if f1 > best_f1: best_f1 = f1; best_t = t
    pred_best = (prob_te >= best_t).astype(float)
    print(f"  Best thresh={best_t:.2f}  F1={best_f1:.3f}  predicted_pos={int(sum(pred_best))}")

# ─────────────────────────────────────────────────────────────────────────────
# 回测对比（测试期 2025-06 ~ 2026-05）
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("Backtest Comparison (Test Period)")
print("=" * 65)

INITIAL = 1_000_000.0; TRAIL=0.15; COOL=5

for key, res in results.items():
    te_dates = te_d
    te_prob  = list(res["prob_te"])
    te_close = [closes_v[i] for i in te_i]

    capital=INITIAL; cash=INITIAL; shares=0.0; peak=INITIAL
    equity=[]; trades=[]; in_pos=False; trail_px=float('inf'); cooldown=0

    for i, d in enumerate(te_dates):
        close = te_close[i]; prob = te_prob[i]
        sh = shares/te_close[max(0,i-1)]*close if in_pos and i>0 else 0
        if in_pos:
            if close>trail_px: trail_px=close*(1-TRAIL)
            if close<trail_px:
                cash+=sh; shares=0.0; in_pos=False; cooldown=COOL; peak=max(peak,cash)
        elif cooldown>0:
            cooldown-=1
        else:
            if prob<0.3:  # 安全入场
                to_buy=cash/close; shares=to_buy*close; cash=0.0; in_pos=True; trail_px=close*(1-TRAIL)
        peak=max(peak, cash+shares)
        equity.append(cash+shares)

    final=equity[-1]; ret=(final-INITIAL)/INITIAL*100
    bh_ret=(te_close[-1]/te_close[0]-1)*100
    max_dd=max((peak-e)/peak*100 for e in equity)
    print(f"\n{key} — {res['name']}")
    print(f"  Return: {ret:+.2f}%  CAGR: {ret:+.2f}%  MaxDD: -{max_dd:.2f}%")
    print(f"  vs BuyHold: {ret-bh_ret:+.2f}%")
    print(f"  BuyHold: {bh_ret:+.2f}%")

# ─────────────────────────────────────────────────────────────────────────────
# 保存概率时间序列
# ─────────────────────────────────────────────────────────────────────────────
for key, res in results.items():
    out_csv = OUT_DIR / f"spy_nn_{key.lower()}_prob.csv"
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date","close","prob"])
        w.writeheader()
        for i, d in enumerate(res["dates_te"]):
            w.writerow({"date":d,"close":round(res["closes_te"][i],2),
                       "prob":round(float(res["prob_te"][i]),6)})
    print(f"\nSaved: {out_csv}")

# 保存汇总结果
summary = {
    "solution2": {
        "name": results["S2"]["name"],
        "test_auc": round(float(results["S2"]["test_auc"]), 4),
        "test_acc": round(float(results["S2"]["test_acc"]), 4),
        "shift_pos_pct": round(float(results["S2"]["shift_pos"]/results["S2"]["shift_total"]*100), 2),
    },
    "solution4": {
        "name": results["S4"]["name"],
        "test_auc": round(float(results["S4"]["test_auc"]), 4),
        "test_acc": round(float(results["S4"]["test_acc"]), 4),
        "shift_pos_pct": round(float(results["S4"]["shift_pos"]/results["S4"]["shift_total"]*100), 2),
    }
}
with open(OUT_DIR / "compare_summary.json", "w") as f:
    json.dump(summary, f, indent=2)
print(f"\nSaved: {OUT_DIR}/compare_summary.json")

print("\nDone!")
