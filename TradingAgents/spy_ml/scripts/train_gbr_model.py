#!/usr/bin/env python3
"""
训练脚本 1：GradientBoosting 变盘预测模型
==============================================================
标签：未来20日最大回撤>8% → shift=1
特征：22个技术指标（ATR/MA偏离/波动率/RSI/MACD/成交量）
模型：GradientBoostingClassifier
数据：SPY 2020-01-02 → 2026-05-12
训练：2020-01-02 ~ 2025-06-30
测试：2025-07-01 ~ 2026-05-12

输出：
  models/gbr_shift_model.json     — 模型参数
  data/gbr_prob_timeseries.csv  — 全量概率时间序列
  data/gbr_backtest.csv         — 回测结果
"""
import json, sys, warnings
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score

warnings.filterwarnings('ignore')
PROJ = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析")

# ── 数据路径 ─────────────────────────────────────────────────────
SPY_FILE = PROJ / "TradingAgents/中间过程/klines/SPY_1d.json"
OUT_DIR = PROJ / "TradingAgents/spy_ml"
OUT_DIR.mkdir(exist_ok=True)

# ── 超参数 ───────────────────────────────────────────────────────
TRAIN_END = "2025-06-30"
TEST_START = "2025-07-01"
DRAWDOWN_THRESHOLD = 0.08   # 8%
LOOK_AHEAD = 20             # 20个交易日
PROB_EXIT = 0.7
PROB_ENTRY = 0.3
TRAIL_PCT = 0.20

# ── 加载数据 ─────────────────────────────────────────────────────
print("加载 SPY 数据...")
with open(SPY_FILE) as f:
    raw = json.load(f)
bars_raw = raw.get("data", raw) if isinstance(raw, dict) else raw
df = pd.DataFrame(bars_raw)
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)
# 合并 vol/volume 列（两列互补）
if "vol" in df.columns:
    df["volume"] = df["vol"].fillna(df["volume"])
    df.drop(columns=["vol"], inplace=True, errors="ignore")
print(f"  SPY: {len(df)} 条, {df['date'].min().date()} → {df['date'].max().date()}")

# ── 特征工程 ─────────────────────────────────────────────────────
print("构建特征...")
def build_features(df):
    df = df.copy()
    df["ret_1d"]   = df["close"].pct_change(1)
    df["ret_5d"]   = df["close"].pct_change(5)
    df["ret_20d"]  = df["close"].pct_change(20)
    df["volatility_5d"]  = df["ret_1d"].rolling(5).std()
    df["volatility_20d"] = df["ret_1d"].rolling(20).std()
    df["high_low_ratio"] = (df["high"] - df["low"]) / df["close"]
    df["high20"] = df["high"].rolling(20).max()
    df["low20"]  = df["low"].rolling(20).min()
    df["close_position"] = (df["close"] - df["low20"]) / (df["high20"] - df["low20"] + 1e-10)
    df["ma5"]   = df["close"].rolling(5).mean()
    df["ma20"]  = df["close"].rolling(20).mean()
    df["ma50"]  = df["close"].rolling(50).mean()
    df["ma5_dev"]  = (df["close"] - df["ma5"])  / df["ma5"]
    df["ma20_dev"] = (df["close"] - df["ma20"]) / df["ma20"]
    df["ma50_dev"] = (df["close"] - df["ma50"]) / df["ma50"]
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    df["rsi_14"] = 100 - (100 / (1 + gain / (loss + 1e-10)))
    df["momentum"] = df["close"] / df["close"].shift(20) - 1
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma20"]
    df["vol_ma5"]  = df["volume"].rolling(5).mean()
    df["vol_trend"] = df["vol_ma5"] / (df["vol_ma20"] + 1e-10)
    df["price_up"] = (df["close"] > df["close"].shift(1)).astype(int)
    df["vol_up"]   = (df["volume"] > df["volume"].shift(1)).astype(int)
    df["vol_price_div"] = ((df["price_up"] == 1) & (df["vol_up"] == 0)).astype(int)
    df["price_down"] = (df["close"] < df["close"].shift(1)).astype(int)
    df["price_drop_vol_spike"] = (df["price_down"] & (df["vol_ratio"] > 1.5)).astype(int)
    df["price_volume_conflict"] = (df["price_up"] != df["vol_up"]).astype(int)
    df["abnormal_volume"] = (df["vol_ratio"] > 2.0).astype(int)
    bb_mid = df["close"].rolling(20).mean()
    bb_std = df["close"].rolling(20).std()
    df["bb_position"] = (df["close"] - bb_mid) / (2 * bb_std + 1e-10)
    tr1 = df["high"] - df["low"]
    tr2 = abs(df["high"] - df["close"].shift(1))
    tr3 = abs(df["low"]  - df["close"].shift(1))
    df["atr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()
    df["atr_pct"] = df["atr"] / df["close"]
    ema12 = df["close"].ewm(span=12).mean()
    ema26 = df["close"].ewm(span=26).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    return df

df = build_features(df)

# ── 标签生成 ─────────────────────────────────────────────────────
print("生成标签...")
def make_label(i, prices, threshold, look_ahead):
    if i + look_ahead >= len(prices):
        return np.nan
    current = prices[i]
    future = prices[i+1 : i+look_ahead+1]
    trough = np.min(future)
    drawdown = (trough - current) / current
    return 1 if drawdown < -threshold else 0

prices = df["close"].values
labels = [make_label(i, prices, DRAWDOWN_THRESHOLD, LOOK_AHEAD) for i in range(len(df))]
df["label"] = labels

# ── 训练/测试分割 ─────────────────────────────────────────────────
FEATURE_COLS = [
    "ret_1d", "ret_5d", "ret_20d",
    "volatility_5d", "volatility_20d",
    "high_low_ratio", "close_position",
    "ma5_dev", "ma20_dev", "ma50_dev",
    "rsi_14", "momentum",
    "vol_ratio", "vol_trend",
    "vol_price_div", "price_drop_vol_spike",
    "price_volume_conflict", "abnormal_volume",
    "bb_position", "atr_pct",
    "macd_hist", "macd"
]

df_model = df.dropna(subset=FEATURE_COLS + ["label"]).copy()
df_model = df_model.iloc[:-LOOK_AHEAD]

train_mask = df_model["date"] <= TRAIN_END
test_mask  = df_model["date"] >= TEST_START

X_train = df_model.loc[train_mask, FEATURE_COLS].values
y_train = df_model.loc[train_mask, "label"].values
X_test  = df_model.loc[test_mask,  FEATURE_COLS].values
y_test  = df_model.loc[test_mask,  "label"].values
test_dates  = df_model.loc[test_mask, "date"].values
test_prices = df_model.loc[test_mask, "close"].values
test_probs_out = df_model.loc[test_mask, FEATURE_COLS].values

print(f"  训练: {len(X_train)} 样本, 正例率 {y_train.mean():.3f}")
print(f"  测试: {len(X_test)} 样本, 正例率 {y_test.mean():.3f}")

# ── 训练模型 ─────────────────────────────────────────────────────
print("训练 GradientBoosting...")
clf = GradientBoostingClassifier(
    n_estimators=200, max_depth=4,
    min_samples_split=20, min_samples_leaf=10,
    learning_rate=0.05, subsample=0.8,
    random_state=42, verbose=0
)
clf.fit(X_train, y_train)

# 评估
if len(np.unique(y_test)) > 1:
    y_proba = clf.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_proba)
    print(f"  测试 AUC: {auc:.4f}")

# 特征重要性
importances = pd.Series(clf.feature_importances_, index=FEATURE_COLS).sort_values(ascending=False)
print("\n特征重要性 Top-10:")
for feat, imp in importances.head(10).items():
    print(f"  {feat:30s} {imp:.4f}")

# ── 全量概率序列 ─────────────────────────────────────────────────
all_X = df_model[FEATURE_COLS].values
all_proba = clf.predict_proba(all_X)[:, 1]
df_model["shift_prob"] = all_proba

# ── 回测 ─────────────────────────────────────────────────────────
print("\n运行回测...")
bt = df_model.loc[test_mask, ["date","close","shift_prob","label"]].reset_index(drop=True)

# 买入持有基准
bh_ret = bt["close"].iloc[-1] / bt["close"].iloc[0] - 1
print(f"  买入持有收益率: {bh_ret:.2%}")

# 策略回测
in_market = False
shares = 0; cash = 100000; entry_price = 0; peak_price = 0
equity_curve = [100000]; trades = []

for i, row in bt.iterrows():
    price = row["close"]
    prob = row["shift_prob"]
    if i == 0:
        equity_curve.append(equity_curve[-1]); continue
    prev_price = bt.loc[i-1, "close"]
    if not in_market and prob < PROB_ENTRY:
        shares = int(cash / price)
        cash = cash - shares * price
        entry_price = price; peak_price = price
        in_market = True
        trades.append({"date": str(row["date"])[:10], "action": "BUY",
                       "price": price, "prob": prob})
    elif in_market:
        if price > peak_price: peak_price = price
        trail_exit = (peak_price - price) / peak_price >= TRAIL_PCT
        danger_exit = prob > PROB_EXIT
        if trail_exit or danger_exit:
            cash = cash + shares * price
            ret = (price - entry_price) / entry_price
            trades.append({"date": str(row["date"])[:10], "action": "SELL",
                           "price": price, "prob": prob,
                           "ret": ret,
                           "reason": "trailing_stop" if trail_exit else "danger"})
            shares = 0; in_market = False
    equity = cash + shares * price if in_market else cash
    equity_curve.append(equity)

bt["equity"] = equity_curve[1:]
final_equity = equity_curve[-1]
total_ret = (final_equity - 100000) / 100000

# 最大回撤
peak = 0; max_dd = 0
for e in equity_curve:
    if e > peak: peak = e
    dd = (e - peak) / peak
    if dd < max_dd: max_dd = dd

win_trades = [t for t in trades if t["action"] == "SELL" and t.get("ret", 0) > 0]
num_trades = len([t for t in trades if t["action"] == "BUY"])
win_rate = len(win_trades) / max(len([t for t in trades if t["action"] == "SELL"]), 1)

print(f"  最终权益: {final_equity:,.2f}")
print(f"  总收益率: {total_ret:.2%}")
print(f"  最大回撤: {max_dd:.2%}")
print(f"  交易次数: {num_trades}")
print(f"  胜率:     {win_rate:.1%}")

# ── 保存概率序列 ─────────────────────────────────────────────────
prob_df = df_model[["date", "close", "shift_prob", "label"]].copy()
prob_df["date"] = prob_df["date"].astype(str)
prob_out = PROJ / "TradingAgents/spy_ml/data/gbr_prob_timeseries.csv"
prob_df.to_csv(prob_out, index=False)
print(f"\n概率序列已保存: {prob_out}")

# ── 保存模型元信息 ───────────────────────────────────────────────
model_meta = {
    "model_type": "GradientBoostingClassifier",
    "train_period": f"{df_model.loc[train_mask,'date'].min().date()} ~ {df_model.loc[train_mask,'date'].max().date()}",
    "test_period": f"{bt['date'].min()} ~ {bt['date'].max()}",
    "lookahead_days": LOOK_AHEAD,
    "drawdown_threshold": DRAWDOWN_THRESHOLD,
    "n_features": len(FEATURE_COLS),
    "feature_cols": FEATURE_COLS,
    "feature_importance": {f: round(float(imp), 6) for f, imp in importances.items()},
    "test_auc": float(roc_auc_score(y_test, clf.predict_proba(X_test)[:, 1])) if len(np.unique(y_test)) > 1 else None,
    "backtest": {
        "total_return": round(total_ret, 6),
        "max_drawdown": round(max_dd, 6),
        "num_trades": num_trades,
        "win_rate": round(win_rate, 4),
        "final_equity": round(final_equity, 2),
        "baseline_return": round(bh_ret, 6),
    },
    "hyperparameters": {
        "n_estimators": 200, "max_depth": 4,
        "min_samples_split": 20, "min_samples_leaf": 10,
        "learning_rate": 0.05, "subsample": 0.8,
    },
    "train_date": "2026-05-16",
}
meta_out = PROJ / "TradingAgents/spy_ml/models/gbr_model_meta.json"
with open(meta_out, "w") as f:
    json.dump(model_meta, f, ensure_ascii=False, indent=2)
print(f"模型元信息已保存: {meta_out}")

print("\n✅ GBR 模型训练完成！")
