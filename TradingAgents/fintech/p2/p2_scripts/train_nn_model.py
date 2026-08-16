#!/usr/bin/env python3
"""
训练脚本 2：Neural Network 增强版模型
==============================================================
标签B（变盘）：未来10日回撤>3% → shift=1（G5极值点附近±5天）
网络：Input(26) → Dense(128) → Dense(64) → Dense(32) → Output(2)
数据：SPY 2020-01-02 → 2026-05-12 + VIX 2024-05-15开始
训练：2020-01-02 ~ 2025-06-30
测试：2025-07-01 ~ 2026-05-12

输出：
  models/nn_model_meta.json    — 模型参数
  data/nn_prob_timeseries.csv — 全量概率时间序列
"""
import json, warnings
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import roc_auc_score
from scipy.ndimage import gaussian_filter1d

warnings.filterwarnings('ignore')
PROJ = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析")

SPY_FILE = PROJ / "TradingAgents/中间过程/klines/SPY_1d.json"
VIX_FILE = PROJ / "TradingAgents/中间过程/klines/VIX_1d.json"
OUT_DIR  = PROJ / "TradingAgents/spy_ml"

TRAIN_END      = "2025-06-30"
TEST_START     = "2025-07-01"
SHIFT_LOOKAHEAD = 10

# ── 加载数据 ─────────────────────────────────────────────────────
print("加载 SPY 数据...")
with open(SPY_FILE) as f:
    spy_raw = json.load(f)
spy_bars = spy_raw.get("data", spy_raw)
df_spy = pd.DataFrame(spy_bars)
df_spy["date"] = pd.to_datetime(df_spy["date"])
df_spy = df_spy.sort_values("date").reset_index(drop=True)
if "vol" in df_spy.columns:
    df_spy["volume"] = df_spy["vol"].fillna(df_spy["volume"])
    df_spy.drop(columns=["vol"], inplace=True, errors="ignore")
print(f"  SPY: {len(df_spy)} 条, {df_spy['date'].min().date()} → {df_spy['date'].max().date()}")

print("加载 VIX 数据...")
with open(VIX_FILE) as f:
    vix_raw = json.load(f)
vix_bars = vix_raw.get("data", vix_raw) if isinstance(vix_raw, dict) else vix_raw
df_vix = pd.DataFrame(vix_bars)
df_vix["date"] = pd.to_datetime(df_vix["date"])
df_vix = df_vix.sort_values("date").reset_index(drop=True)
df_vix = df_vix.rename(columns={"open":"vix_open","high":"vix_high","low":"vix_low","close":"vix_close"})
print(f"  VIX: {len(df_vix)} 条, {df_vix['date'].min().date()} → {df_vix['date'].max().date()}")

df = df_spy.merge(df_vix[["date","vix_open","vix_high","vix_low","vix_close"]], on="date", how="left")
for c in ["vix_open","vix_high","vix_low","vix_close"]:
    df[c] = df[c].ffill()
df = df.dropna(subset=["vix_close"]).reset_index(drop=True)
print(f"  合并后: {len(df)} 条")

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
closes = df["close"].values.astype(float)
highs  = df["high"].values.astype(float)
lows   = df["low"].values.astype(float)
vix_c  = df["vix_close"].values.astype(float)
vix_h  = df["vix_high"].values.astype(float)
vix_l  = df["vix_low"].values.astype(float)
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

tr = np.zeros(n-1)
for i in range(1, n):
    tr[i-1] = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
atr14 = np.zeros(n); atr14[1:] = ema_np(tr, 14)
atr_pct = atr14/closes*100

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

vxe5 = ema_np(vix_c, 5); vxe20 = ema_np(vix_c, 20)
vxr = np.zeros(n); vxr[1:] = (vix_c[1:]/vix_c[:-1]-1)*100
vxip = (vix_c - vix_l)/(vix_h - vix_l + 1e-10)
vxd = (vix_c - vxe20)/vxe20*100

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
]
feat_arr = np.column_stack([
    r1, r5, r20, v5, v20,
    atr_pct, rsi, macd, macd_h,
    m5d, m20d, m50d, bb_pos, mom,
    vr, vt, pir,
    vix_c, vxd, vxr, vxip,
    above20ema, avwap_d, nh, nl, upr,
])
print(f"  特征矩阵: {feat_arr.shape}")

# ── 标签生成（极值点±SHIFT_LOOKAHEAD天）──────────────────────────
print("生成变盘标签...")
curve = gaussian_filter1d(closes.astype(float), sigma=5)
d1 = np.gradient(curve, 1.0)
sc = np.where(np.diff(np.sign(d1)))[0]
shift_set = set()
prev = -5
for idx in sc:
    if idx - prev < 5: continue
    for j in range(max(0, idx-SHIFT_LOOKAHEAD), min(len(df), idx+SHIFT_LOOKAHEAD+1)):
        shift_set.add(j)
    prev = idx

label_b = np.array([1.0 if i in shift_set else 0.0 for i in range(n)], dtype=float)

# ── 训练/测试分割 ─────────────────────────────────────────────────
df_feat = pd.DataFrame(feat_arr, columns=FEATURES)
df_feat["date"] = df["date"].values
df_feat["label_b"] = label_b
df_feat = df_feat.dropna().reset_index(drop=True)

train_mask = df_feat["date"] <= TRAIN_END
test_mask  = df_feat["date"] >= TEST_START
X_train = df_feat.loc[train_mask, FEATURES].values
X_test  = df_feat.loc[test_mask,  FEATURES].values
yB_train = df_feat.loc[train_mask, "label_b"].values
yB_test  = df_feat.loc[test_mask,  "label_b"].values

yB_train_binary = (yB_train >= 0.5).astype(int)
yB_test_binary  = (yB_test >= 0.5).astype(int)

print(f"  训练: {len(X_train)} 样本, 正例率 {yB_train_binary.mean():.3f}")
print(f"  测试: {len(X_test)} 样本, 正例率 {yB_test_binary.mean():.3f}")

# ── 标准化 ────────────────────────────────────────────────────────
mean = X_train.mean(axis=0)
std  = X_train.std(axis=0) + 1e-10
X_train_n = (X_train - mean) / std
X_test_n  = (X_test  - mean) / std

# ── 训练 sklearn MLP ──────────────────────────────────────────────
print("训练 sklearn MLPClassifier (128→64→32)...")
mlp = MLPClassifier(
    hidden_layer_sizes=(128, 64, 32),
    activation='relu',
    solver='adam',
    alpha=0.001,
    max_iter=1500,
    batch_size=64,
    random_state=42,
    verbose=False,
)
mlp.fit(X_train_n, yB_train_binary)

# 预测
proba_test = mlp.predict_proba(X_test_n)[:, 1]
if len(np.unique(yB_test_binary)) > 1:
    auc = roc_auc_score(yB_test_binary, proba_test)
    print(f"  变盘预测 AUC: {auc:.4f}")

# ── 全量概率 ─────────────────────────────────────────────────────
X_all_n = (feat_arr - mean) / std
prob_all = mlp.predict_proba(X_all_n)[:, 1]

n_out = len(df_feat)
df_out = pd.DataFrame({
    "date": df_feat["date"].values[:n_out].astype(str),
    "close": closes[:n_out],
    "prob_shift": prob_all[:n_out],
    "label": label_b[:n_out],
})
# 立即验证
assert df_out["close"].iloc[0] > 100, f"close 异常: {df_out['close'].iloc[0]}"
assert df_out["close"].iloc[-1] > 100, f"close 异常: {df_out['close'].iloc[-1]}"

prob_out = OUT_DIR / "data/nn_prob_timeseries.csv"
df_out.to_csv(prob_out, index=False)
print(f"\n概率序列已保存: {prob_out}")

# ── 回测 ─────────────────────────────────────────────────────────
bt = df_out[df_out["date"] >= TEST_START].reset_index(drop=True)
bh_ret = (bt["close"].iloc[-1] / bt["close"].iloc[0] - 1) if len(bt) > 1 else 0

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
            trades.append({"date": row["date"], "action": "SELL", "price": p, "prob": prob, "ret": ret})
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

# ── 保存模型元信息 ───────────────────────────────────────────────
meta = {
    "model_type": "sklearn_MLPClassifier",
    "architecture": f"Input({len(FEATURES)})→128→64→32→2",
    "hyperparameters": {"activation":"relu","solver":"adam","alpha":0.001,"max_iter":1500,"batch_size":64},
    "train_period": f"{df_feat.loc[train_mask,'date'].min().date()} ~ {df_feat.loc[train_mask,'date'].max().date()}",
    "test_period": f"{TEST_START} ~ {bt['date'].max()}",
    "n_features": len(FEATURES),
    "feature_cols": FEATURES,
    "test_auc": float(roc_auc_score(yB_test_binary, proba_test)) if len(np.unique(yB_test_binary))>1 else None,
    "backtest": {
        "total_return": round(total_ret, 6),
        "max_drawdown": round(max_dd, 6),
        "num_trades": num_trades,
        "win_rate": round(win_rate, 4),
        "baseline_return": round(bh_ret, 6),
    },
    "train_date": "2026-05-16",
    "standardization": {"mean": mean.tolist(), "std": std.tolist()},
}
meta_out = OUT_DIR / "models/nn_model_meta.json"
with open(meta_out, "w") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
print(f"\n模型元信息已保存: {meta_out}")
print("\n✅ NN 模型训练完成！")
