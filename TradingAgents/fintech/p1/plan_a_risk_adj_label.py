"""
plan_a_risk_adj_label.py
=========================
方案A — 风险调整收益标签 + LR仓位管理

将变盘预测从二分类（3.4%正样本）改为风险调整收益多分类（~60%正样本）。
用 LogisticRegression (multinomial) 预测未来20日 risk_adj 档位，按档位仓位管理。

标签设计：
  未来20日收益（%） / (未来20日波动率 + eps) = risk_adj
  1=差(risk_adj<-1)   → 0%
  2=偏差(-1≤r<0)      → 25%
  3=中性(0≤r<1)       → 50%
  4=偏好(1≤r<2)        → 100%
  5=优秀(r≥2)          → 100%

追踪止损：TRAIL=0.15, STOP=0.08, COOL=5
"""

import json, os, sys
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from datetime import datetime, timedelta

# ── 路径 ────────────────────────────────────────────────────────────────────
BASE   = "/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/fintech/p1"
OUTDIR = os.path.join(BASE, "spy_lr_full_backtest")
os.makedirs(OUTDIR, exist_ok=True)

# ── 超参数 ──────────────────────────────────────────────────────────────────
INIT_CASH   = 1_000_000.0
TRAIL       = 0.15
STOP_LOSS   = 0.08
COOL_DAYS   = 5
FUTURE_N    = 20          # 展望窗口
VOL_WINDOW  = 20          # 波动率窗口

TRAIN_START = "2020-01-01"
TRAIN_END   = "2024-06-01"
TEST_START  = "2024-06-01"
TEST_END    = "2026-05-13"

# ── 加载数据 ────────────────────────────────────────────────────────────────
def load_klines(path):
    with open(path) as f:
        d = json.load(f)
    rows = []
    for bar in d["data"]:
        rows.append({
            "date":   bar["date"],
            "open":   float(bar["open"]),
            "high":   float(bar["high"]),
            "low":    float(bar["low"]),
            "close":  float(bar["close"]),
            "volume": float(bar.get("vol", bar.get("volume", 0))),
        })
    return pd.DataFrame(rows).set_index("date")

print("加载 SPY K线 …")
spy  = load_klines(os.path.join(BASE, "klines", "SPY_1d.json"))
print(f"  SPY  {spy.index[0]} → {spy.index[-1]}, {len(spy)} 条")

print("加载 VIX K线 …")
vix  = load_klines(os.path.join(BASE, "klines", "VIX_1d.json"))
print(f"  VIX  {vix.index[0]} → {vix.index[-1]}, {len(vix)} 条")

# ── 合并 & 过滤日期 ─────────────────────────────────────────────────────────
spy.index = pd.to_datetime(spy.index)
vix.index = pd.to_datetime(vix.index)

df = spy.join(vix, how="left", rsuffix="_vix")
df = df[df.index >= "2020-01-01"].copy()
df["close_vix"] = df["close_vix"].ffill()

print(f"\n合并后  {df.index[0].date()} → {df.index[-1].date()}, {len(df)} 条")

# ── 计算特征 ────────────────────────────────────────────────────────────────
def calc_features(df):
    """26 个特征：SPY收益/波动/技术指标 + VIX OHLC/派生 + 市场结构"""
    closes = df["close"].values.astype(float)
    highs  = df["high"].values.astype(float)
    lows   = df["low"].values.astype(float)
    vix_c  = df["close_vix"].values.astype(float)
    vix_h  = df["high_vix"].values.astype(float)
    vix_l  = df["low_vix"].values.astype(float)
    n = len(df)

    ret_1d  = np.full(n, np.nan)
    ret_5d  = np.full(n, np.nan)
    ret_10d = np.full(n, np.nan)
    ret_20d = np.full(n, np.nan)
    vol20   = np.full(n, np.nan)

    for i in range(1, n):
        ret_1d[i]  = (closes[i] / closes[i-1] - 1) * 100
    for i in range(5, n):
        ret_5d[i]  = (closes[i] / closes[i-5] - 1) * 100
    for i in range(10, n):
        ret_10d[i] = (closes[i] / closes[i-10] - 1) * 100
    for i in range(20, n):
        ret_20d[i] = (closes[i] / closes[i-20] - 1) * 100
        vol20[i]   = np.std(ret_1d[i-VOL_WINDOW+1:i+1]) if i >= VOL_WINDOW else np.nan

    # MA / EMA
    ma5   = pd.Series(closes).rolling(5).mean().values
    ma10  = pd.Series(closes).rolling(10).mean().values
    ma20  = pd.Series(closes).rolling(20).mean().values
    ma50  = pd.Series(closes).rolling(50).mean().values
    ma200 = pd.Series(closes).rolling(200).mean().values

    def _ema(arr, w):
        alpha = 2.0 / (w + 1)
        out = np.full_like(arr, np.nan)
        out[w-1] = np.mean(arr[:w])
        for i in range(w, len(arr)):
            out[i] = alpha * arr[i] + (1 - alpha) * out[i-1]
        return out

    ema5   = _ema(closes, 5)
    ema10  = _ema(closes, 10)
    ema20  = _ema(closes, 20)
    ema50  = _ema(closes, 50)
    ema200 = _ema(closes, 200)

    # RSI-14
    rsi14 = np.full(n, 50.0)
    for i in range(14, n):
        gains = np.maximum(ret_1d[i-13:i+1], 0)
        losses = np.maximum(-ret_1d[i-13:i+1], 0)
        ag = np.mean(gains)
        al = np.mean(losses)
        if al == 0:
            rsi14[i] = 100.0
        else:
            rsi14[i] = 100 - 100 / (1 + ag / al)

    # ATR-14
    tr = np.full(n, np.nan)
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i-1])
        lc = abs(lows[i] - closes[i-1])
        tr[i] = max(hl, hc, lc)
    atr14 = pd.Series(tr).rolling(14).mean().values
    atr14_pct = atr14 / closes * 100

    # 布林带
    bb_pos  = np.full(n, 0.5)
    bb_width = np.full(n, 0.0)
    for i in range(20, n):
        m = np.mean(closes[i-19:i+1])
        s = np.std(closes[i-19:i+1], ddof=0)
        upper = m + 2 * s
        lower = m - 2 * s
        bb_pos[i]  = (closes[i] - lower) / (upper - lower) if (upper - lower) > 0 else 0.5
        bb_width[i] = (upper - lower) / m if m > 0 else 0.0

    # 成交量
    vols = df["volume"].values.astype(float)
    vol_ma20 = pd.Series(vols).rolling(20).mean().values
    vol_ratio = vols / (vol_ma20 + 1e-10)

    # MA cross
    ma5_above_ma20    = (ma5 > ma20).astype(int)
    ma20_above_ma50  = (ma20 > ma50).astype(int)
    price_above_ma200 = (closes > ma200).astype(int)

    # VIX 派生
    vix_range   = vix_h - vix_l
    vix_pct_chg = np.full(n, 0.0)
    for i in range(1, n):
        vix_pct_chg[i] = (vix_c[i] / (vix_c[i-1] + 1e-10) - 1) * 100

    # 市场结构
    market_regime = np.full(n, 1.0)   # 1=震荡
    for i in range(50, n):
        if ma200[i] > ma200[i-1] * 1.005 and ma50[i] > ma50[i-1] * 1.002:
            market_regime[i] = 3.0    # 上升
        elif ma200[i] < ma200[i-1] * 0.995 or ma50[i] < ma50[i-1] * 0.998:
            market_regime[i] = 0.0    # 下降

    feat = pd.DataFrame(index=df.index)
    feat["ret_1d"]           = ret_1d
    feat["ret_5d"]           = ret_5d
    feat["ret_10d"]          = ret_10d
    feat["ret_20d"]          = ret_20d
    feat["vol20"]            = vol20
    feat["ma5"]              = ma5
    feat["ma10"]             = ma10
    feat["ma20"]             = ma20
    feat["ma50"]             = ma50
    feat["ma200"]            = ma200
    feat["ema5"]             = ema5
    feat["ema10"]            = ema10
    feat["ema20"]            = ema20
    feat["ema50"]            = ema50
    feat["ema200"]           = ema200
    feat["ma5_above_ma20"]  = ma5_above_ma20
    feat["ma20_above_ma50"] = ma20_above_ma50
    feat["price_above_ma200"]= price_above_ma200
    feat["rsi14"]            = rsi14
    feat["atr14"]            = atr14
    feat["atr14_pct"]        = atr14_pct
    feat["bb_pos"]           = bb_pos
    feat["bb_width"]         = bb_width
    feat["vol_ma20"]         = vol_ma20
    feat["vol_ratio"]        = vol_ratio
    feat["close_vix"]        = vix_c
    feat["vix_range"]        = vix_range
    feat["vix_pct_chg"]      = vix_pct_chg
    feat["market_regime"]    = market_regime

    return feat

print("\n计算特征 …")
feat = calc_features(df)
print(f"  特征矩阵 {feat.shape}")

# ── 计算标签 ────────────────────────────────────────────────────────────────
closes = df["close"].values.astype(float)
n = len(df)

# future_return[i] = (close[i+20] / close[i] - 1) * 100   (i from 0 to n-21)
future_ret = np.full(n, np.nan)
future_vol = np.full(n, np.nan)
risk_adj   = np.full(n, np.nan)

ret_1d_all = np.full(n, np.nan)
for i in range(1, n):
    ret_1d_all[i] = (closes[i] / closes[i-1] - 1) * 100

for i in range(n - FUTURE_N):
    fr = (closes[i + FUTURE_N] / closes[i] - 1) * 100
    fv = np.std(ret_1d_all[i+1:i+FUTURE_N+1]) if i+FUTURE_N <= n else np.nan
    future_ret[i] = fr
    future_vol[i] = fv
    risk_adj[i]   = fr / (fv + 1e-10)

# 离散为5档
def risk_to_class(r):
    if np.isnan(r): return np.nan
    if r < -1:      return 1
    if r < 0:       return 2
    if r < 1:       return 3
    if r < 2:       return 4
    return 5

label_class = np.array([risk_to_class(r) for r in risk_adj])
label_class = pd.Series(label_class, index=df.index)

print("\n标签分布（全部有效样本）：")
valid_mask = ~np.isnan(label_class)
vc = pd.Series(label_class[valid_mask]).value_counts().sort_index()
for c, cnt in vc.items():
    print(f"  档位{c}: {cnt} ({cnt/valid_mask.sum()*100:.1f}%)")

# ── 训练/测试分割 ───────────────────────────────────────────────────────────
train_mask = (df.index >= TRAIN_START) & (df.index < TRAIN_END) & ~np.isnan(label_class)
test_mask  = (df.index >= TEST_START)  & (df.index <= TEST_END)  & ~np.isnan(label_class)

train_feat = feat[train_mask].copy()
train_label = label_class[train_mask].copy()
test_feat   = feat[test_mask].copy()
test_label  = label_class[test_mask].copy()
test_dates  = df.index[test_mask]

print(f"\n训练集: {train_feat.index[0].date()} → {train_feat.index[-1].date()}, n={len(train_feat)}")
print(f"测试集: {test_dates[0].date()} → {test_dates[-1].date()}, n={len(test_feat)}")
print("训练集标签分布：")
for c, cnt in train_label.value_counts().sort_index().items():
    print(f"  档位{int(c)}: {cnt} ({cnt/len(train_label)*100:.1f}%)")

# ── 标准化 & 模型 ────────────────────────────────────────────────────────────
scaler = StandardScaler()
X_train = scaler.fit_transform(train_feat.fillna(0))
X_test  = scaler.transform(test_feat.fillna(0))

model = LogisticRegression(
    solver="lbfgs",
    max_iter=2000,
    C=0.5,
    class_weight="balanced",
    random_state=42,
)
# silence penalty deprecation (sklearn 1.8+)
model.fit(X_train, train_label)

train_pred = model.predict(X_train)
test_pred  = model.predict(X_test)

train_acc = (train_pred == train_label.values).mean()
test_acc  = (test_pred  == test_label.values).mean()
print(f"\n训练集准确率: {train_acc:.3f}")
print(f"测试集准确率:  {test_acc:.3f}")

# ── 仓位函数 ────────────────────────────────────────────────────────────────
def pos_from_prediction(pred_class):
    p = int(pred_class)
    if p == 1: return 0.00
    if p == 2: return 0.25
    if p == 3: return 0.50
    return 1.00

# ── 回测 ────────────────────────────────────────────────────────────────────
def backtest(pred_classes, dates, closes_arr, init_cash=INIT_CASH,
             trail=TRAIL, stop=STOP_LOSS, cool=COOL_DAYS):
    """
    pred_classes : array of predicted class (1-5) aligned with dates
    dates        : DatetimeIndex, test period
    returns equity curve dict
    """
    cash    = init_cash
    shares  = 0.0
    equity  = []
    entry_px = 0.0
    in_pos   = False
    cool_rem = 0          # 冷却天数剩余

    # 使用 test_feat 中的 vol20 作为波动率估计
    vol_arr = feat.loc[dates, "vol20"].values

    for i, (dt, pred_c, close_px, vol_val) in enumerate(zip(dates, pred_classes, closes_arr, vol_arr)):
        if np.isnan(close_px):
            equity.append(cash + shares * closes_arr[i-1] if i > 0 else cash)
            continue

        target_pos = pos_from_prediction(pred_c)
        win_size   = init_cash * 0.02   # 2% 波动止损基准（与ATR结合）

        # 入场
        if not in_pos and target_pos > 0 and cool_rem == 0:
            shares   = (cash * target_pos) / close_px
            entry_px = close_px
            cash     = cash * (1 - target_pos)
            in_pos   = True

        # 追踪止损 / 固定止损
        if in_pos:
            ret_from_entry = (close_px / entry_px - 1)
            trail_trigger = ret_from_entry > 0 and ret_from_entry <= -trail
            stop_trigger  = ret_from_entry <= -stop
            # ATR 波动止损（超过 3xATR 则止损）
            atr_val = feat.at[dt, "atr14"]
            if not np.isnan(atr_val) and vol_val > 0:
                vol_stop_trigger = ret_from_entry <= -(stop + vol_val / close_px * 2)
            else:
                vol_stop_trigger = False

            if trail_trigger or stop_trigger or vol_stop_trigger:
                cash    += shares * close_px
                shares   = 0.0
                in_pos   = False
                cool_rem = cool
                entry_px = 0.0

        # 冷却递减
        if cool_rem > 0:
            cool_rem -= 1

        total_eq = cash + shares * close_px
        equity.append(total_eq)

    return {
        "dates":   [str(d.date()) for d in dates],
        "equity":  equity,
        "cash":    cash,   # final cash (may be 0 if still in pos)
        "final_eq": equity[-1] if equity else init_cash,
    }

# 获取测试集对应的收盘价
test_close_arr = df.loc[test_dates, "close"].values.astype(float)

# 执行回测
bt = backtest(test_pred, test_dates, test_close_arr)
equity_curve = bt["equity"]

# 买入持有基准
bh_shares = INIT_CASH / test_close_arr[0]
bh_equity = [bh_shares * c for c in test_close_arr]

# 全区间 (2020-01-02 → 2026-05-13) 的 BH
full_dates = df.index[df.index >= "2020-01-01"]
full_close = df.loc[full_dates, "close"].values.astype(float)
bh_full_shares = INIT_CASH / full_close[0]
bh_full_ret    = (full_close[-1] / full_close[0] - 1) * 100

# ── 结果统计 ─────────────────────────────────────────────────────────────────
def calc_stats(dates, equity_arr, label=""):
    if len(equity_arr) < 2:
        return {}
    eq   = np.array(equity_arr)
    rets = np.diff(eq) / eq[:-1]
    cagr = (eq[-1] / eq[0]) ** (252 / len(eq)) - 1 if eq[0] > 0 else 0.0
    # Max drawdown
    peak = eq[0]
    mdd  = 0.0
    for v in eq:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < mdd: mdd = dd
    return {
        "label":       label,
        "final_eq":    round(eq[-1], 2),
        "total_ret":   round((eq[-1] / eq[0] - 1) * 100, 2),
        "cagr":        round(cagr * 100, 2),
        "max_dd":      round(mdd * 100, 2),
        "trades":      0,   # filled below
    }

def count_trades(pred_classes, dates):
    trades = 0
    prev_pos = 0.0
    for p in pred_classes:
        cur = pos_from_prediction(p)
        if cur != prev_pos and cur > 0:
            trades += 1
        prev_pos = cur
    return trades

strat_trades = count_trades(test_pred, test_dates)
bh_trades    = 1   # buy and hold = 1 trade

# 全区间 BH
bh_full_ret_pct = round(bh_full_ret, 2)

print("\n" + "="*60)
print("回测结果（测试集 2024-06-01 → 2026-05-13）")
print("="*60)
s = calc_stats(test_dates, equity_curve, "LR仓位管理")
print(f"  总收益:    {s['total_ret']:+.2f}%")
print(f"  CAGR:      {s['cagr']:+.2f}%")
print(f"  最大回撤:  {s['max_dd']:+.2f}%")
print(f"  交易次数:  {strat_trades}")
bh_ret = round((bh_equity[-1] / bh_equity[0] - 1) * 100, 2)
print(f"\n基准 BH:    {bh_ret:+.2f}%  (同期)")
print(f"全区间 BH:  {bh_full_ret_pct:+.2f}%  (2020-01-02 → 2026-05-13)")
print(f"LR vs BH:   {s['total_ret'] - bh_ret:+.2f}%")

print("\n各档位分布（测试集预测）：")
for c in range(1, 6):
    cnt = int((test_pred == c).sum())
    pos = pos_from_prediction(c)
    print(f"  档位{c} (仓位{pos*100:.0f}%): {cnt}天 ({cnt/len(test_pred)*100:.1f}%)")

# ── 保存 equity 曲线 ────────────────────────────────────────────────────────
equity_df = pd.DataFrame({
    "date":       bt["dates"],
    "equity_lr":  equity_curve,
    "equity_bh":  bh_equity,
})
eq_path = os.path.join(OUTDIR, "plan_a_equity.csv")
equity_df.to_csv(eq_path, index=False)
print(f"\n保存 equity 曲线 → {eq_path}")

# ── 保存结果 JSON ───────────────────────────────────────────────────────────
results = {
    "strategy":           "Plan A: Risk-Adjusted LR Multi-class + Position Sizing",
    "train_period":       f"{TRAIN_START} to {TRAIN_END}",
    "test_period":        f"{TEST_START} to {TEST_END}",
    "train_n":            int(len(train_feat)),
    "test_n":             int(len(test_feat)),
    "train_accuracy":    round(train_acc, 4),
    "test_accuracy":      round(test_acc, 4),
    "label_distribution": {f"class_{c}": int(vc.get(c, 0)) for c in range(1,6)},
    "lr_total_ret":       s["total_ret"],
    "lr_cagr":            s["cagr"],
    "lr_max_dd":          s["max_dd"],
    "lr_trades":          strat_trades,
    "bh_total_ret_test":  bh_ret,
    "bh_total_ret_full":  bh_full_ret_pct,
    "lr_vs_bh":           round(s["total_ret"] - bh_ret, 2),
    "position_by_class":  {f"class_{c}": pos_from_prediction(c) for c in range(1,6)},
    "parameters": {
        "init_cash":   INIT_CASH,
        "future_n":    FUTURE_N,
        "vol_window":  VOL_WINDOW,
        "trail_stop":  TRAIL,
        "stop_loss":   STOP_LOSS,
        "cool_days":   COOL_DAYS,
    },
    "test_class_distribution": {
        f"class_{c}": int((test_pred == c).sum()) for c in range(1,6)
    },
}

res_path = os.path.join(OUTDIR, "plan_a_results.json")
with open(res_path, "w") as f:
    json.dump(results, f, indent=2)
print(f"保存结果 JSON → {res_path}")
print("\n✅ 完成")
