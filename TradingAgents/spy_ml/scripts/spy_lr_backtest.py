#!/usr/bin/env python3
"""
spy_lr_full_backtest.py — LR仓位管理全量回测（2020-2026）

仓位函数签名：entry_fn(prob, in_pos) → target_ratio (0~1)
"""

import json, csv, time
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score

PROJ = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析")
OUT  = PROJ / "spy_lr_full_backtest"
OUT.mkdir(exist_ok=True)
INITIAL = 1_000_000.0


def ema(data, p):
    k = 2/(p+1); out = np.zeros_like(data); out[0]=data[0]
    for i in range(1, len(data)): out[i] = data[i]*k + out[i-1]*(1-k)
    return out


def ma(data, p):
    return np.convolve(data, np.ones(p)/p, mode="same")


def rstd(x, w):
    out = np.zeros_like(x, dtype=float)
    for i in range(w, len(x)): out[i] = float(np.std(x[i-w:i]))
    return out


# ── 特征工程 ────────────────────────────────────────────────────────────────
def build_features(spy_bars, vix_bars):
    n = len(spy_bars)
    dates   = [b["date"]  for b in spy_bars]
    closes  = np.array([b["close"] for b in spy_bars], dtype=float)
    highs   = np.array([b["high"]  for b in spy_bars], dtype=float)
    lows    = np.array([b["low"]   for b in spy_bars], dtype=float)
    vols    = np.array([float(b["volume"]) if "volume" in b else float(b.get("vol", 0)) for b in spy_bars], dtype=float)

    vix_map = {b["date"]: b for b in vix_bars}
    vix_c = np.array([vix_map.get(d, {}).get("close", 20.0) for d in dates], dtype=float)
    vix_h = np.array([vix_map.get(d, {}).get("high", 20.0)  for d in dates], dtype=float)
    vix_l = np.array([vix_map.get(d, {}).get("low",  20.0)  for d in dates], dtype=float)

    e5  = ema(closes, 5);  e20 = ema(closes, 20); e50 = ema(closes, 50)
    r1  = np.zeros(n); r1[1:]  = (closes[1:]/closes[:-1]-1)*100
    r5  = np.zeros(n)
    r20 = np.zeros(n)
    for i in range(5, n):  r5[i]  = (closes[i]/closes[i-5]-1)*100
    for i in range(20, n): r20[i] = (closes[i]/closes[i-20]-1)*100
    v5  = rstd(r1, 5);  v20 = rstd(r1, 20)
    tr  = np.zeros(n-1)
    for i in range(1, n):
        tr[i-1] = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
    atr = np.zeros(n); atr[1:] = ema(tr, 14); atr_pct = atr/closes*100

    # RSI-14
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    ag = np.zeros(n); al = np.zeros(n)
    ag[14] = np.mean(gains[:14]); al[14] = np.mean(losses[:14])
    for i in range(15, n):
        ag[i] = (ag[i-1]*13 + gains[i-1])/14
        al[i] = (al[i-1]*13 + losses[i-1])/14
    rsi = 100 - 100/(1 + ag/(al+1e-10))

    m12 = ema(closes, 12); m26 = ema(closes, 26)
    macd_l = m12 - m26; macd_s = ema(macd_l, 9)
    macd    = macd_l/closes*100
    macd_h  = (macd_l - macd_s)/closes*100

    bb_mid = ma(closes, 20); bb_s = rstd(closes, 20)
    bb_pos  = (closes - (bb_mid-2*bb_s))/(4*bb_s+1e-10)

    m5d  = (closes-e5)/e5*100;  m20d = (closes-e20)/e20*100; m50d = (closes-e50)/e50*100

    l20  = np.array([min(closes[max(0,i-20):i+1]) for i in range(n)])
    h20  = np.array([max(closes[max(0,i-20):i+1]) for i in range(n)])
    pir  = (closes - l20)/(h20 - l20 + 1e-10)
    mom  = np.zeros(n)
    for i in range(20, n): mom[i] = (closes[i]/closes[i-20]-1)*100

    vma  = ma(vols, 20)
    vr   = vols/(vma+1)
    vt   = np.zeros(n)
    for i in range(20, n): vt[i] = (vma[i]/max(vma[i-20],1)-1)*100

    vx5  = ema(vix_c, 5);  vx20 = ema(vix_c, 20)
    vxr  = np.zeros(n); vxr[1:]  = (vix_c[1:]/vix_c[:-1]-1)*100
    vxip = (vix_c - vix_l)/(vix_h - vix_l + 1e-10)
    vxd  = (vix_c - vx20)/vx20*100

    above20  = np.minimum(0.99, np.maximum(0.01, (closes/e20 - 0.95)*20))
    avwap_d   = (closes - e20*1.02)/(e20*1.02)*100
    nh        = np.where(closes >= h20*0.99, 1.0, 0.0)
    nl        = np.where(closes <= l20*1.01, 1.0, 0.0)
    upr       = np.zeros(n)
    for i in range(20, n): upr[i] = sum(r1[max(0,i-20):i]>0)/20

    FEATS = [
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
    return FEATS, X, dates, closes


def make_labels(dates, closes, window=2):
    from scipy.ndimage import gaussian_filter1d
    curve = gaussian_filter1d(closes.astype(float), sigma=5)
    d1    = np.gradient(curve, 1.0)
    sc    = np.where(np.diff(np.sign(d1)))[0]
    extrema = []; prev = -5
    for idx in sc:
        if idx - prev < 5: continue
        d2 = np.gradient(d1, 1.0); curv = d2[idx]
        extrema.append({"idx": int(idx), "date": dates[idx],
                       "type": "peak" if curv < 0 else "valley"})
        prev = idx
    shift_set = set()
    for e in extrema:
        e_idx = dates.index(e["date"])
        for j in range(max(0, e_idx-window), min(len(dates), e_idx+window+1)):
            shift_set.add(dates[j])
    y = np.array([1.0 if d in shift_set else 0.0 for d in dates], dtype=float)
    return y, extrema


# ── 回测引擎 ────────────────────────────────────────────────────────────────
def backtest(name, dates, closes, prob_lr, entry_fn,
            initial=1_000_000.0,
            TRAIL=0.15, STOP=0.08, COOL=5):
    """
    entry_fn(prob, in_pos) -> target_ratio (0~1)
    shares: 股数（固定）
    cash: 现金
    equity = cash + shares * close
    """
    capital = initial; cash = initial; shares = 0.0; peak = initial
    equity = []; trades = []; cooldown = 0

    for i, d in enumerate(dates):
        close = closes[i]
        prob  = prob_lr[i]
        in_pos = shares > 0
        target_ratio = entry_fn(prob, in_pos)

        if in_pos:
            prev_close = closes[i-1] if i > 0 else close
            trail_stop = prev_close * (1 - TRAIL)

            # 追踪止损
            if close < trail_stop:
                pnl = shares * (close - prev_close)
                cash += shares * close
                trades.append({"date": d, "exit": round(close, 2),
                             "pnl": round(float(pnl), 2),
                             "reason": "trailing_stop"})
                shares = 0.0; cooldown = COOL

            # 仓位调整
            elif target_ratio < 1.0:
                # 清仓或减仓
                target_val = capital * target_ratio
                current_val = cash + shares * close
                if current_val > target_val + 1.0:  # 有多余
                    sell_val = current_val - target_val
                    sell_shares = sell_val / close
                    shares -= sell_shares
                    cash += sell_val
                    if shares < 1.0:
                        cash += shares * close
                        shares = 0.0
                        cooldown = COOL
                        trades.append({"date": d, "exit": round(close, 2),
                                     "pnl": round(float(sell_shares*(close-prev_close)), 2),
                                     "reason": "signal_exit"})

        elif cooldown > 0:
            cooldown -= 1

        else:
            # 入场
            if target_ratio >= 1.0:
                invest = capital * target_ratio
                if cash >= invest * 0.9:  # 允许少量透支
                    buy_shares = invest / close
                    shares = buy_shares
                    cash -= buy_shares * close

        # 更新权益
        eq = cash + shares * close
        peak = max(peak, eq)
        equity.append({
            "date": d, "close": round(close, 2),
            "equity": round(float(eq), 2),
            "prob": round(float(prob), 4),
            "cash": round(float(cash), 2),
        })

    # 结算
    final_eq  = equity[-1]["equity"]
    total_ret = (final_eq - initial) / initial * 100
    years     = len(dates) / 252
    cagr      = ((final_eq/initial)**(1/max(years,0.01)) - 1)
    bh_ret    = (closes[-1]/closes[0] - 1)*100

    dd_peak = initial; max_dd = 0.0
    for e in equity:
        dd_peak = max(dd_peak, e["equity"])
        max_dd = max(max_dd, (dd_peak - e["equity"])/dd_peak*100)

    wins  = [t for t in trades if t["pnl"] > 0]
    loss  = [t for t in trades if t["pnl"] <= 0]
    wr    = len(wins)/max(1, len(trades))*100

    return {
        "name":            name,
        "final_equity":     round(final_eq, 2),
        "total_return":    round(total_ret, 2),
        "cagr":            round(cagr*100, 2),
        "max_drawdown":    round(max_dd, 2),
        "num_trades":      len(trades),
        "win_rate":        round(wr, 2),
        "buy_hold_return": round(bh_ret, 2),
        "outperformance":  round(total_ret - bh_ret, 2),
        "avg_win":  round(float(sum(t["pnl"] for t in wins)/max(1,len(wins))), 0) if wins else 0,
        "avg_loss": round(float(sum(t["pnl"] for t in loss)/max(1,len(loss))), 0) if loss else 0,
        "trades":  trades,
        "equity":   equity,
    }


# ── 仓位函数 ──────────────────────────────────────────────────────────────
def pos_bh(prob, in_pos):          return 1.0
# S1: prob < 0.20 才满仓，否则按比例递减（prob>=0.30 清仓）
def pos_continuous(prob, in_pos):
    if prob < 0.20: return 1.0
    elif prob < 0.30: return 0.5
    elif prob < 0.40: return 0.25
    return 0.0
# S2: 三档仓位
def pos_discrete(prob, in_pos):
    if prob < 0.15: return 1.0
    elif prob < 0.25: return 0.5
    return 0.0
# S3: 阈值择时（仅在离场信号出现时操作）
def pos_threshold(prob, in_pos):
    if not in_pos and prob < 0.12: return 1.0
    elif not in_pos and prob < 0.20: return 0.5
    elif prob > 0.35: return 0.0  # 明确离场信号
    return 1.0  # 持有
# S4: 激进版
def pos_aggressive(prob, in_pos):
    if prob < 0.08: return 1.0
    elif prob < 0.15: return 0.75
    elif prob < 0.25: return 0.50
    elif prob < 0.35: return 0.25
    return 0.0


# ── 主程序 ────────────────────────────────────────────────────────────────
print("="*65)
print("SPY LR Full Backtest 2020–2026")
print("="*65)

# 加载数据
spy_bars, vix_bars = [], []
with open(PROJ/"中间过程/klines/SPY_1d.json") as f:
    d = json.load(f); raw=d.get("data",d) if isinstance(d,dict) else d
    while isinstance(raw,dict): raw=raw.get("data",[])
    for b in raw:
        if b["date"] < "2020-01-01": continue
        spy_bars.append({"date":b["date"], "close":float(b["close"]),
                        "high":float(b["high"]), "low":float(b["low"]),
                        "volume":float(b.get("volume") or b.get("vol") or 0)})
with open(PROJ/"中间过程/klines/VIX_1d.json") as f:
    d = json.load(f); raw=d.get("data",d) if isinstance(d,dict) else d
    while isinstance(raw,dict): raw=raw.get("data",[])
    for b in raw:
        if b["date"] < "2020-01-01": continue
        vix_bars.append({"date":b["date"], "close":float(b["close"]),
                        "high":float(b.get("high",b["close"])),
                        "low":float(b.get("low",b["close"]))})

FEATS, X_raw, dates, closes = build_features(spy_bars, vix_bars)
N = len(dates)
print(f"\n[{N} days: {dates[0]} → {dates[-1]}]")

y_shift, extrema = make_labels(dates, closes, window=2)
n_s = int(sum(y_shift))
print(f"Labels: shift=1 {n_s} days ({n_s/N*100:.1f}%)")

# NaN过滤
valid = ~np.isnan(X_raw).any(axis=1)
X = X_raw[valid]; y = y_shift[valid]
dates_v = [dates[i] for i in range(len(dates)) if valid[i]]
closes_v = closes[valid]; N_v = len(X)

# 训练
TRAIN_END = "2024-06-01"
tr_idx = [i for i,d in enumerate(dates_v) if d < TRAIN_END]
tr_X, tr_y = X[tr_idx], y[tr_idx]
print(f"\nTraining LR on {len(tr_X)} samples (before {TRAIN_END})...")

scaler = StandardScaler()
tr_X_s = scaler.fit_transform(tr_X)
lr = LogisticRegression(C=1.0, solver='lbfgs', max_iter=1000, random_state=42)
lr.fit(tr_X_s, tr_y)
X_s = scaler.transform(X)
prob_lr = lr.predict_proba(X_s)[:, 1].tolist()

try:
    tr_auc = roc_auc_score(tr_y, lr.predict_proba(tr_X_s)[:,1])
    print(f"Train AUC: {tr_auc:.4f}")
except: pass

# 回测
strategies = [
    ("S0 Buy-Hold",          pos_bh),
    ("S1 LR Continuous",     pos_continuous),
    ("S2 LR Discrete",       pos_discrete),
    ("S3 LR Threshold",      pos_threshold),
    ("S4 LR Aggressive",    pos_aggressive),
]

print("\n" + "="*65)
print("Results  (2020-01 → 2026-05, Initial ¥1,000,000)")
print("="*65)
print(f"{'Strategy':25s}  {'Return':8s}  {'CAGR':7s}  {'MaxDD':7s}  {'Trades':6s}  {'Win%':6s}  {'vsBH':8s}")
print("-"*75)

results = {}
for name, fn in strategies:
    r = backtest(name, dates_v, closes_v, prob_lr, fn)
    results[name] = r
    print(f"{name:25s}  {r['total_return']:+7.2f}%  {r['cagr']:+6.2f}%  "
          f"{r['max_drawdown']:6.2f}%  {r['num_trades']:5d}  "
          f"{r['win_rate']:5.1f}%  {r['outperformance']:+7.2f}%")

# 保存
eq_csv = OUT / "all_strategies_equity.csv"
all_eq = {}
for name, r in results.items():
    for e in r["equity"]:
        all_eq.setdefault(e["date"], {})[name] = e["equity"]
eq_dates = sorted(all_eq.keys())
with open(eq_csv, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["date"] + list(results.keys()))
    w.writeheader()
    for d in eq_dates:
        row = {"date": d}
        row.update({name: round(all_eq[d].get(name, 0), 2) for name in results})
        w.writerow(row)
print(f"\nSaved equity: {eq_csv}")

prob_csv = OUT / "lr_daily_prob.csv"
with open(prob_csv, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["date","close","prob","label"])
    w.writeheader()
    for i, d in enumerate(dates_v):
        w.writerow({"date":d,"close":round(closes_v[i],2),
                   "prob":round(float(prob_lr[i]),6),"label":int(y[i])})
print(f"Saved prob:  {prob_csv}")

out_json = OUT / "lr_backtest_results.json"
with open(out_json, "w") as f:
    json.dump({name: {k: v for k, v in r.items() if k not in ("equity",)}
              for name, r in results.items()}, f, indent=2)
print(f"Saved JSON:  {out_json}")

print("\nDone!")
