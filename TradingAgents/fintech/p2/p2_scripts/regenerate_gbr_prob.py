#!/usr/bin/env python3
"""
用新训练的 GBR 模型重新生成概率时间序列
GBR 模型：22 特征，训练日期 2026-05-16
"""
import json, warnings
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier

warnings.filterwarnings('ignore')
PROJ = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析")
OUT_DIR = PROJ / "TradingAgents/spy_ml"

SPY_FILE = PROJ / "TradingAgents/中间过程/klines/SPY_1d.json"

# ── 加载 GBR 模型 ────────────────────────────────────────────────
print("加载 GBR 模型元信息...")
with open(OUT_DIR / "models/gbr_model_meta.json") as f:
    meta = json.load(f)
FEATURES = meta["feature_cols"]
print(f"  特征数: {len(FEATURES)}")

# ── 加载 SPY 数据 ───────────────────────────────────────────────
print("加载 SPY...")
with open(SPY_FILE) as f:
    raw = json.load(f)
bars = raw.get("data", raw)
df = pd.DataFrame(bars)
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)
if "vol" in df.columns:
    df["volume"] = df["vol"].fillna(df["volume"])
    df.drop(columns=["vol"], inplace=True, errors="ignore")
print(f"  SPY: {len(df)} 条, {df['date'].min().date()} → {df['date'].max().date()}")

# ── 特征工程（与 train_gbr_model.py 完全一致）──────────────────
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
closes = df["close"].values.astype(float)
highs  = df["high"].values.astype(float)
lows   = df["low"].values.astype(float)
vols   = df["volume"].values.astype(float)

e5  = ema_np(closes, 5)
e20 = ema_np(closes, 20)
e50 = ema_np(closes, 50)

r1  = np.zeros(n); r1[1:]  = (closes[1:]/closes[:-1]-1)*100
r5  = np.zeros(n)
r20 = np.zeros(n)
for i in range(5, n):  r5[i]  = (closes[i]/closes[i-5]-1)*100
for i in range(20, n): r20[i] = (closes[i]/closes[i-20]-1)*100
v5  = rstd_np(r1, 5)
v20 = rstd_np(r1, 20)

m5d  = (closes-e5)/e5*100
m20d = (closes-e20)/e20*100
m50d = (closes-e50)/e50*100

l20  = np.array([min(closes[max(0,i-20):i+1]) for i in range(n)])
h20  = np.array([max(closes[max(0,i-20):i+1]) for i in range(n)])
pir  = (closes - l20)/(h20 - l20 + 1e-10)

mom = np.zeros(n)
for i in range(20, n): mom[i] = (closes[i]/closes[i-20]-1)*100

vma = ma_np(vols, 20); vr = vols/(vma+1)
vt = np.zeros(n)
for i in range(20, n): vt[i] = (vma[i]/max(vma[i-20],1)-1)*100

# GBR 独有特征
tr = np.zeros(n-1)
for i in range(1, n):
    tr[i-1] = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
atr14 = np.zeros(n); atr14[1:] = ema_np(tr, 14)
atr_pct = atr14/closes*100

bb_mid = ma_np(closes, 20); bb_std = rstd_np(closes, 20)
bb_pos = (closes - (bb_mid-2*bb_std))/(4*bb_std+1e-10)

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
macd = macd_l/closes*100
macd_h = (macd_l - macd_s)/closes*100

hl_ratio = highs/lows
vp_div = (closes - e20)/(vols+1)
dpk_spike = np.where((r1 < -1) & (vr > 1.5), 1.0, 0.0)
pv_conf = np.where(((r1 > 0) & (vr < 0.8)) | ((r1 < 0) & (vr > 1.2)), 1.0, 0.0)
ab_vol = np.where(vr > 2.0, 1.0, 0.0)

feat_df = pd.DataFrame({
    "ret_1d": r1, "ret_5d": r5, "ret_20d": r20,
    "volatility_5d": v5, "volatility_20d": v20,
    "high_low_ratio": hl_ratio, "close_position": pir,
    "ma5_dev": m5d, "ma20_dev": m20d, "ma50_dev": m50d,
    "rsi_14": rsi, "momentum": mom,
    "vol_ratio": vr, "vol_trend": vt,
    "vol_price_div": vp_div, "price_drop_vol_spike": dpk_spike,
    "price_volume_conflict": pv_conf, "abnormal_volume": ab_vol,
    "bb_position": bb_pos, "atr_pct": atr_pct,
    "macd_hist": macd_h, "macd": macd,
})
feat_df = feat_df[FEATURES].dropna().reset_index(drop=True)
feat_df = feat_df.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)

dates_gbr = df["date"].values[:len(feat_df)]
closes_gbr = closes[:len(feat_df)]
n_gbr = len(feat_df)
print(f"  GBR 有效数据: {n_gbr} 条, {dates_gbr[0]} → {dates_gbr[-1]}")

# ── 训练 GBR 模型（用全部数据）──────────────────────────────────
from scipy.ndimage import gaussian_filter1d
curve = gaussian_filter1d(closes_gbr.astype(float), sigma=5)
d1 = np.gradient(curve, 1.0)
sc = np.where(np.diff(np.sign(d1)))[0]
shift_set = set()
prev = -5
LA = 10  # lookahead
for idx in sc:
    if idx - prev < 5: continue
    for j in range(max(0, idx-LA), min(n_gbr, idx+LA+1)):
        shift_set.add(j)
    prev = idx
y_gbr = np.array([1.0 if i in shift_set else 0.0 for i in range(n_gbr)], dtype=float)

X_gbr = feat_df.values
print(f"  正例率: {y_gbr.mean():.3f}")

print("训练 GBR...")
gbr = GradientBoostingClassifier(
    n_estimators=200, max_depth=4, learning_rate=0.05,
    min_samples_leaf=5, subsample=0.8, random_state=42
)
gbr.fit(X_gbr, y_gbr)

# ── 全量概率 ─────────────────────────────────────────────────────
prob_all = gbr.predict_proba(X_gbr)[:, 1]

df_out = pd.DataFrame({
    "date": dates_gbr,
    "close": closes_gbr,
    "prob_shift": prob_all,
    "label": y_gbr,
})
df_out["date"] = df_out["date"].astype(str)

prob_out = OUT_DIR / "data/gbr_prob_timeseries.csv"
df_out.to_csv(prob_out, index=False)
print(f"\n概率序列已保存: {prob_out}")
print(f"  最后日期: {df_out['date'].iloc[-1]}, prob={df_out['prob_shift'].iloc[-1]:.4f}")
print(f"  总行数: {len(df_out)}")
print("\n✅ GBR 概率序列已更新！")
