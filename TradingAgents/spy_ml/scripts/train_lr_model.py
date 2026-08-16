#!/usr/bin/env python3
"""
训练脚本 3：Logistic Regression 滚动概率模型
==============================================================
标签：极值点附近 ±window 天 → shift=1
特征：27个技术指标（含VIX/DXY）
模型：Logistic Regression + StandardScaler
数据：SPY 2020-01-02 → 2026-05-12
训练：2020-01-02 ~ 2025-06-30
测试：2025-07-01 ~ 2026-05-12

输出：
  models/lr_model_meta.json    — 模型参数+标准化器
  data/lr_prob_timeseries.csv — 全量概率时间序列
  data/lr_backtest.csv        — 回测结果
"""
import json, warnings
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score
from scipy.ndimage import gaussian_filter1d

warnings.filterwarnings('ignore')
PROJ = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析")

SPY_FILE = PROJ / "TradingAgents/中间过程/klines/SPY_1d.json"
VIX_FILE = PROJ / "TradingAgents/中间过程/klines/VIX_1d.json"
DXY_FILE = PROJ / "TradingAgents/中间过程/klines/DXY_1d.json"
OUT_DIR = PROJ / "TradingAgents/spy_ml"

TRAIN_END  = "2025-06-30"
TEST_START = "2025-07-01"
SHIFT_WINDOW = 2  # 极值点 ±2 天

# ── 数据加载 ─────────────────────────────────────────────────────
print("加载 SPY...")
with open(SPY_FILE) as f:
    spy_raw = json.load(f)
spy_bars = spy_raw.get("data", spy_raw)
df_spy = pd.DataFrame(spy_bars)
df_spy["date"] = pd.to_datetime(df_spy["date"])
df_spy = df_spy.sort_values("date").reset_index(drop=True)
# 合并 vol/volume 列
if "vol" in df_spy.columns:
    df_spy["volume"] = df_spy["vol"].fillna(df_spy["volume"])
    df_spy.drop(columns=["vol"], inplace=True, errors="ignore")
print(f"  SPY: {len(df_spy)} 条, {df_spy['date'].min().date()} → {df_spy['date'].max().date()}")

print("加载 VIX...")
with open(VIX_FILE) as f:
    vix_raw = json.load(f)
vix_bars = vix_raw.get("data", vix_raw) if isinstance(vix_raw, dict) else vix_raw
df_vix = pd.DataFrame(vix_bars)[["date","vix_open","vix_high","vix_low","vix_close"]].copy()
df_vix["date"] = pd.to_datetime(df_vix["date"])
df_vix = df_vix.sort_values("date").reset_index(drop=True)
print(f"  VIX: {len(df_vix)} 条")

print("加载 DXY...")
with open(DXY_FILE) as f:
    dxy_raw = json.load(f)
dxy_bars = dxy_raw.get("data", dxy_raw) if isinstance(dxy_raw, dict) else dxy_raw
df_dxy = pd.DataFrame(dxy_bars)
df_dxy["date"] = pd.to_datetime(df_dxy["date"])
df_dxy = df_dxy.sort_values("date").reset_index(drop=True)
df_dxy = df_dxy[["date","close"]].rename(columns={"close":"dxy_close"})
print(f"  DXY: {len(df_dxy)} 条")

# ── 合并 ───────────────────────────────────────────────────────
df = df_spy.copy()
df = df.merge(df_vix, on="date", how="left")
df = df.merge(df_dxy, on="date", how="left")
for col in ["vix_open","vix_high","vix_low","vix_close","dxy_close"]:
    df[col] = df[col].ffill().bfill()
df = df.dropna(subset=["vix_close","dxy_close"]).reset_index(drop=True)
print(f"  合并后: {len(df)} 条, {df['date'].min().date()} → {df['date'].max().date()}")

# ── 特征工程 ─────────────────────────────────────────────────────
print("构建特征...")

def ema_np(data, p):
    k = 2/(p+1); out = np.zeros_like(data, dtype=float)
    out[0] = data[0]
    for i in range(1, len(data)): out[i] = data[i]*k + out[i-1]*(1-k)
    return out

def ma_np(data, p):
    out = np.zeros_like(data, dtype=float)
    for i in range(p-1, len(data)): out[i] = np.mean(data[i-p+1:i+1])
    return out

def rstd_np(x, w):
    out = np.zeros_like(x, dtype=float)
    for i in range(w, len(x)): out[i] = np.std(x[i-w:i])
    return out

n = len(df)
dates   = df["date"].values
closes  = df["close"].values.astype(float)
highs   = df["high"].values.astype(float)
lows    = df["low"].values.astype(float)
vols    = df["volume"].values.astype(float)
vix_c   = df["vix_close"].values.astype(float)
vix_h   = df["vix_high"].values.astype(float)
vix_l   = df["vix_low"].values.astype(float)
dxy_c   = df["dxy_close"].values.astype(float)

e5  = ema_np(closes, 5); e20 = ema_np(closes, 20); e50 = ema_np(closes, 50)

r1  = np.zeros(n); r1[1:]  = (closes[1:]/closes[:-1]-1)*100
r5  = np.zeros(n)
r20 = np.zeros(n)
for i in range(5, n):  r5[i]  = (closes[i]/closes[i-5]-1)*100
for i in range(20, n): r20[i] = (closes[i]/closes[i-20]-1)*100
v5  = rstd_np(r1, 5); v20 = rstd_np(r1, 20)

tr = np.zeros(n-1)
for i in range(1, n):
    tr[i-1] = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
atr = np.zeros(n); atr[1:] = ema_np(tr, 14); atr_pct = atr/closes*100

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

m12 = ema_np(closes, 12); m26 = ema_np(closes, 26)
macd_l = m12 - m26; macd_s = ema_np(macd_l, 9)
macd    = macd_l/closes*100
macd_h  = (macd_l - macd_s)/closes*100

bb_mid = ma_np(closes, 20); bb_s = rstd_np(closes, 20)
bb_pos = (closes - (bb_mid-2*bb_s))/(4*bb_s+1e-10)

m5d  = (closes-e5)/e5*100; m20d = (closes-e20)/e20*100; m50d = (closes-e50)/e50*100

l20  = np.array([min(closes[max(0,i-20):i+1]) for i in range(n)])
h20  = np.array([max(closes[max(0,i-20):i+1]) for i in range(n)])
pir  = (closes - l20)/(h20 - l20 + 1e-10)

mom = np.zeros(n)
for i in range(20, n): mom[i] = (closes[i]/closes[i-20]-1)*100

vma = ma_np(vols, 20); vr = vols/(vma+1)
vt = np.zeros(n)
for i in range(20, n): vt[i] = (vma[i]/max(vma[i-20],1)-1)*100

# VIX features
vxe5 = ema_np(vix_c, 5); vxe20 = ema_np(vix_c, 20)
vxr = np.zeros(n); vxr[1:] = (vix_c[1:]/vix_c[:-1]-1)*100
vxip = (vix_c - vix_l)/(vix_h - vix_l + 1e-10)
vxd = (vix_c - vxe20)/vxe20*100

# DXY
dxy_ma20 = ma_np(dxy_c, 20)
dxy_dev = (dxy_c - dxy_ma20)/dxy_ma20*100

# SPY breadth proxy
above20ema = np.minimum(0.99, np.maximum(0.01, (closes/e20 - 0.95)*20))
avwap_d = (closes - e20*1.02)/(e20*1.02)*100
nh = np.where(closes >= h20*0.99, 1.0, 0.0)
nl = np.where(closes <= l20*1.01, 1.0, 0.0)
upr = np.zeros(n)
for i in range(20, n): upr[i] = sum(r1[max(0,i-20):i]>0)/20

FEATURES = [
    "ret_1d","ret_5d","ret_20d",
    "volatility_5d","volatility_20d",
    "atr_pct","rsi_14","macd","macd_hist",
    "ma5_dev","ma20_dev","ma50_dev","bb_position","momentum",
    "vol_ratio","vol_trend","price_in_range",
    "vix_close","vix_ema5_dev","vix_ret","vix_intraday_pos",
    "above_20ema_est","avwap_dev","new_high_proxy","new_low_proxy","up_ratio_20d",
    "dxy_close","dxy_dev",
]

# 替换 inf（出现在 rolling 起始位置）
def clean_arr(arr):
    arr = np.where(np.isnan(arr), 0.0, arr)
    arr = np.where(np.isinf(arr), 0.0, arr)
    return arr

feat_arr = np.column_stack([
    r1, r5, r20, v5, v20,
    atr_pct, rsi, macd, macd_h,
    m5d, m20d, m50d, bb_pos, mom,
    vr, vt, pir,
    vix_c, vxd, vxr, vxip,
    above20ema, avwap_d, nh, nl, upr,
    dxy_c, dxy_dev,
])
feat_arr = clean_arr(feat_arr)
print(f"  特征矩阵: {feat_arr.shape}")

# ── 标签生成（极值点）───────────────────────────────────────────
print("生成极值点标签...")
curve = gaussian_filter1d(closes.astype(float), sigma=5)
d1 = np.gradient(curve, 1.0)
sc = np.where(np.diff(np.sign(d1)))[0]
shift_set = set()
prev = -5
for idx in sc:
    if idx - prev < 5: continue
    d2 = np.gradient(d1, 1.0)
    curv = d2[idx]
    for j in range(max(0, idx-SHIFT_WINDOW), min(len(df), idx+SHIFT_WINDOW+1)):
        shift_set.add(j)
    prev = idx

y = np.array([1.0 if i in shift_set else 0.0 for i in range(n)], dtype=float)

# ── 训练/测试分割 ─────────────────────────────────────────────────
df_feat = pd.DataFrame(feat_arr, columns=FEATURES)
df_feat["date"] = dates
df_feat["label"] = y

df_feat = df_feat.dropna().reset_index(drop=True)
# 替换 inf 值
df_feat = df_feat.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)
n_clean = len(df_feat)
dates = df_feat["date"].values

train_mask = df_feat["date"] <= TRAIN_END
test_mask  = df_feat["date"] >= TEST_START

X_train = df_feat.loc[train_mask, FEATURES].values
y_train = df_feat.loc[train_mask, "label"].values
X_test  = df_feat.loc[test_mask,  FEATURES].values
y_test  = df_feat.loc[test_mask,  "label"].values

print(f"  训练: {len(X_train)} 样本, 正例率 {y_train.mean():.3f}")
print(f"  测试: {len(X_test)} 样本, 正例率 {y_test.mean():.3f}")

# ── 标准化 + 训练 ────────────────────────────────────────────────
print("训练 Logistic Regression...")
scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_test_s  = scaler.transform(X_test)

clf = LogisticRegression(
    C=0.1, penalty="l2", solver="lbfgs",
    max_iter=1000, random_state=42, class_weight="balanced"
)
clf.fit(X_train_s, y_train)

if len(np.unique(y_test)) > 1:
    proba = clf.predict_proba(X_test_s)[:, 1]
    auc = roc_auc_score(y_test, proba)
    print(f"  测试 AUC: {auc:.4f}")

# 特征重要性（系数绝对值）
coefs = np.abs(clf.coef_[0])
feat_imp = pd.Series(coefs, index=FEATURES).sort_values(ascending=False)
print("\n特征重要性 Top-10:")
for f, imp in feat_imp.head(10).items():
    print(f"  {f:30s} {imp:.4f}")

# ── 全量概率 ─────────────────────────────────────────────────────
X_all_s = scaler.transform(feat_arr)
prob_all = clf.predict_proba(X_all_s)[:, 1]

# ── 全量概率 ─────────────────────────────────────────────────────
X_all_s = scaler.transform(feat_arr)
prob_all = clf.predict_proba(X_all_s)[:, 1]

n_out = len(df_feat)
df_out = pd.DataFrame({
    "date": df_feat["date"].values[:n_out].astype(str),
    "close": closes[:n_out],
    "prob_shift": prob_all[:n_out],
    "label": df_feat["label"].values[:n_out],
})

prob_out = OUT_DIR / "data/lr_prob_timeseries.csv"
df_out.to_csv(prob_out, index=False)
print(f"\n概率序列已保存: {prob_out}")

# ── 回测 ─────────────────────────────────────────────────────────
bt = df_out[df_out["date"] >= TEST_START].reset_index(drop=True)
bh_ret = (bt["close"].iloc[-1] / bt["close"].iloc[0] - 1) if len(bt)>1 else 0

in_market = False; shares = 0; cash = 100000
entry = 0; peak = 0; equity_curve = [100000]; trades = []

for i, row in bt.iterrows():
    p = row["close"]; prob = row["prob_shift"]
    if i == 0:
        equity_curve.append(equity_curve[-1]); continue
    if not in_market and prob < 0.35:
        shares = int(cash/p); cash = cash - shares*p
        entry = p; peak = p; in_market = True
        trades.append({"date": row["date"], "action": "BUY", "price": p, "prob": prob})
    elif in_market:
        if p > peak: peak = p
        if (peak-p)/peak >= 0.15 or prob > 0.65:
            cash = cash + shares*p
            ret = (p-entry)/entry
            trades.append({"date": row["date"], "action": "SELL",
                           "price": p, "prob": prob, "ret": ret})
            shares = 0; in_market = False
    equity = cash + shares*p if in_market else cash
    equity_curve.append(equity)

final_equity = equity_curve[-1]
total_ret = (final_equity - 100000)/100000
peak_e = 0; max_dd = 0
for e in equity_curve:
    if e > peak_e: peak_e = e
    dd = (e-peak_e)/peak_e
    if dd < max_dd: max_dd = dd

num_trades = len([t for t in trades if t["action"]=="BUY"])
win_trades = [t for t in trades if t["action"]=="SELL" and t.get("ret",0)>0]
win_rate = len(win_trades)/max(len([t for t in trades if t["action"]=="SELL"]),1)

print(f"\n回测结果:")
print(f"  买入持有: {bh_ret:.2%}")
print(f"  策略收益: {total_ret:.2%}")
print(f"  最终权益: {final_equity:,.2f}")
print(f"  最大回撤: {max_dd:.2%}")
print(f"  交易次数: {num_trades}")
print(f"  胜率: {win_rate:.1%}")

# ── 保存模型 ─────────────────────────────────────────────────────
meta = {
    "model_type": "LogisticRegression",
    "hyperparameters": {"C": 0.1, "penalty": "l2", "class_weight": "balanced"},
    "train_period": f"{df_feat.loc[train_mask,'date'].min()} ~ {df_feat.loc[train_mask,'date'].max()}",
    "test_period": f"{TEST_START} ~ {bt['date'].max()}",
    "n_features": len(FEATURES),
    "feature_cols": FEATURES,
    "feature_importance": {f: round(float(coefs[i]), 6) for i, f in enumerate(FEATURES)},
    "test_auc": float(roc_auc_score(y_test, clf.predict_proba(X_test_s)[:,1])) if len(np.unique(y_test))>1 else None,
    "backtest": {
        "total_return": round(total_ret, 6),
        "max_drawdown": round(max_dd, 6),
        "num_trades": num_trades,
        "win_rate": round(win_rate, 4),
        "baseline_return": round(bh_ret, 6),
    },
    "train_date": "2026-05-16",
    "scaler_mean": scaler.mean_.tolist(),
    "scaler_scale": scaler.scale_.tolist(),
}
meta_out = OUT_DIR / "models/lr_model_meta.json"
with open(meta_out, "w") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
print(f"\n模型元信息已保存: {meta_out}")
print("\n✅ LR 模型训练完成！")
