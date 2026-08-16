#!/usr/bin/env python3
"""
spy_nn_model.py
===============
SPY 神经网络变盘预测模型（3层隐藏层）

标签：前瞻性变盘标签（Label B）
  未来10日内从当时高点回撤>5% → 今天=变盘(1)
  否则 → 安全(0)

架构：Input(19) → Hidden1(128) → Hidden2(64) → Hidden3(32) → Output(1, sigmoid)
激活：relu | 优化器：adam | 正则化：L2(alpha=0.001)

使用方法：
  python3 spy_nn_model.py                 # 训练 + 回测
  python3 spy_nn_model.py --check         # 检查数据
"""

import json, csv, sys, time
from pathlib import Path
import numpy as np

PROJ = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析")
LABEL_CSV   = PROJ / "spy_g5_daily_labels.csv"
OUT_RESULT  = PROJ / "spy_nn_result.json"
OUT_PROB_CSV= PROJ / "spy_nn_prob_timeseries.csv"
OUT_MODEL   = PROJ / "spy_nn_model.json"

FEATURE_COLS = [
    "ret_1d", "ret_5d", "ret_20d",
    "volatility_5d", "volatility_20d",
    "atr_pct",
    "rsi_14",
    "macd", "macd_hist",
    "ma5_dev", "ma20_dev", "ma50_dev",
    "bb_position",
    "momentum",
    "vol_ratio", "vol_trend",
    "pv_conflict", "decline_vol_ratio",
    "price_in_range",
]
N_FEATURES = len(FEATURE_COLS)

HIDDEN_LAYER_SIZES = (128, 64, 32)
ALPHA        = 0.001
LR_INIT      = 0.001
MAX_ITER     = 1000
RANDOM_STATE = 42

from sklearn.neural_network import MLPClassifier
from sklearn.metrics import roc_auc_score, accuracy_score, classification_report


def load_data(label_type="label_shift"):
    """加载数据，支持 label_bb（牛熊）或 label_shift（变盘）"""
    rows = []
    with open(LABEL_CSV) as f:
        for row in csv.DictReader(f):
            rows.append(row)

    dates   = []
    closes  = []
    labels  = []
    features = {k: [] for k in FEATURE_COLS}

    for row in rows:
        lbl = row.get(label_type, "")
        if lbl == "" or lbl is None:
            continue
        labels.append(float(lbl))
        dates.append(row["date"])
        closes.append(float(row["close"]))
        for feat in FEATURE_COLS:
            v = row.get(feat, "0") or "0"
            features[feat].append(float(v))

    X = np.array([features[feat] for feat in FEATURE_COLS], dtype=float).T
    y = np.array(labels, dtype=float)
    return dates, closes, X, y


def time_split(X, y, dates, val_start="2024-06-01", test_start="2025-06-01"):
    tr_idx = [i for i, d in enumerate(dates) if d < val_start]
    va_idx = [i for i, d in enumerate(dates) if val_start <= d < test_start]
    te_idx = [i for i, d in enumerate(dates) if d >= test_start]

    X_tr = X[tr_idx]; y_tr = y[tr_idx]
    X_va = X[va_idx]; y_va = y[va_idx]
    X_te = X[te_idx]; y_te = y[te_idx]
    return (X_tr, y_tr), (X_va, y_va), (X_te, y_te), \
           ([dates[i] for i in tr_idx],
            [dates[i] for i in va_idx],
            [dates[i] for i in te_idx])


def normalize(X_tr, X_va, X_te):
    mean = X_tr.mean(axis=0)
    std  = X_tr.std(axis=0) + 1e-8
    return (X_tr - mean) / std, (X_va - mean) / std, (X_te - mean) / std, mean, std


def main():
    LABEL_TYPE = "label_shift"
    print("=" * 65)
    print(f"SPY Neural Network — Label: {LABEL_TYPE}")
    print(f"Architecture: Input({N_FEATURES}) → {'→'.join(map(str, HIDDEN_LAYER_SIZES))} → Output(1)")
    print("=" * 65)

    dates, closes, X, y = load_data(LABEL_TYPE)
    valid = ~np.isnan(X).any(axis=1) & ~np.isnan(y)
    X = X[valid]; y = y[valid]
    dates_v = [d for d, m in zip(dates, valid) if m]
    closes_v = [c for c, m in zip(closes, valid) if m]
    print(f"Valid samples: {len(X)}")
    print(f"Class dist: shift={sum(y==1)}  safe={sum(y==0)}  ({sum(y==1)/len(y)*100:.1f}% positive)")

    (X_tr, y_tr), (X_va, y_va), (X_te, y_te), (dt, dv, ds) = time_split(X, y, dates_v)
    print(f"Train: {dt[0]} → {dt[-1]}  ({len(dt)}d)")
    print(f"Val:   {dv[0]} → {dv[-1]}  ({len(dv)}d)")
    print(f"Test:  {ds[0]} → {ds[-1]}  ({len(ds)}d)")

    X_tr_n, X_va_n, X_te_n, mean, std = normalize(X_tr, X_va, X_te)

    print(f"\nTraining MLP {HIDDEN_LAYER_SIZES}...")
    t0 = time.time()
    model = MLPClassifier(
        hidden_layer_sizes=HIDDEN_LAYER_SIZES,
        activation='relu', solver='adam',
        alpha=ALPHA, learning_rate_init=LR_INIT,
        max_iter=MAX_ITER, early_stopping=True,
        validation_fraction=0.15, n_iter_no_change=30,
        random_state=RANDOM_STATE, verbose=False,
    )
    model.fit(X_tr_n, y_tr)
    print(f"  Done in {time.time()-t0:.1f}s, iterations={model.n_iter_}")

    # 评估
    for name, Xn, yn in [("Train", X_tr_n, y_tr), ("Val",   X_va_n, y_va), ("Test",  X_te_n, y_te)]:
        pred = model.predict(Xn)
        prob = model.predict_proba(Xn)[:, 1]
        acc  = accuracy_score(yn, pred)
        try:   auc = roc_auc_score(yn, prob)
        except: auc = float("nan")
        print(f"\n{name}: Accuracy={acc:.3f}  AUC={auc:.3f}")
        print(classification_report(yn, pred, target_names=["safe","shift"], digits=3))

    # 全量概率序列
    X_all_n = (X - mean) / std
    all_prob = model.predict_proba(X_all_n)[:, 1]
    all_dates = dt + dv + ds
    all_close = [closes_v[dates_v.index(d)] for d in all_dates]

    with open(OUT_PROB_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date","close","nn_prob"])
        w.writeheader()
        for d, c, p in zip(all_dates, all_close, all_prob):
            w.writerow({"date":d,"close":round(c,2),"nn_prob":round(float(p),6)})
    print(f"Saved: {OUT_PROB_CSV}")

    # 特征重要性
    feat_imp = {}
    for i, feat in enumerate(FEATURE_COLS):
        try:
            auc_f = roc_auc_score(y_tr, X_tr_n[:, i])
            feat_imp[feat] = round(float(abs(auc_f - 0.5) * 2), 4)
        except:
            feat_imp[feat] = 0.0
    print("\nTop-10 Feature importance (single-feature AUC):")
    for feat, imp in sorted(feat_imp.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {feat:25s}: {imp:.4f}")

    # 变盘日期（prob > 0.7）
    shift_pts = [(d, all_close[i], float(all_prob[i]))
                 for i, d in enumerate(all_dates) if all_prob[i] > 0.7]
    print(f"\nShift dates (prob>0.7): {len(shift_pts)}")
    for d, c, p in shift_pts[:15]:
        print(f"  {d}  close={c:.2f}  prob={p:.3f}")

    # ── 回测 ──────────────────────────────────────────────────────────────
    INITIAL  = 1_000_000.0
    STOP_PCT = 0.10    # 10% 固定止损
    TRAIL_PCT= 0.15    # 15% 追踪止损
    COOLDOWN = 5        # 5日冷静期
    ENTRY_PROB_THRESH = 0.3  # prob<0.3 → 入场

    print("\n" + "=" * 65)
    print("Backtest (prob<0.3 entry, prob>0.7 or trailing stop exit)")
    print("=" * 65)

    backtest_dates = ds
    backtest_prob  = [float(all_prob[all_dates.index(d)]) for d in backtest_dates]
    backtest_close = [float(all_close[all_dates.index(d)]) for d in backtest_dates]

    capital  = INITIAL
    position = 0.0
    cash     = INITIAL
    peak     = INITIAL
    equity   = []
    trades   = []
    in_pos   = False
    entry_px = 0.0
    entry_d  = ""
    trail_px = float("inf")
    cooldown = 0

    for i, (d, close, prob) in enumerate(zip(backtest_dates, backtest_close, backtest_prob)):
        shares = position / close if in_pos and close > 0 else 0

        if in_pos:
            # 更新追踪止损
            if close > trail_px:
                trail_px = close * (1 - TRAIL_PCT)

            # 检查止损
            if close < trail_px:
                pnl = (close - entry_px) * shares
                cash += position + pnl
                trades.append({"date":d,"exit":round(close,2),"pnl":round(float(pnl),2),
                               "reason":"trailing_stop","holding":i})
                position = 0.0; in_pos = False; cooldown = COOLDOWN
                peak = max(peak, cash)
            elif prob > 0.85:
                # NN高变盘预警 → 提前离场
                pnl = (close - entry_px) * shares
                cash += position + pnl
                trades.append({"date":d,"exit":round(close,2),"pnl":round(float(pnl),2),
                               "reason":"nn_shift_exit","holding":i})
                position = 0.0; in_pos = False; cooldown = COOLDOWN
                peak = max(peak, cash)
        elif cooldown > 0:
            cooldown -= 1
        else:
            if prob < ENTRY_PROB_THRESH:
                shares_to_buy = cash / close
                position = shares_to_buy * close
                cash = 0.0
                entry_px = close
                entry_d  = d
                trail_px = close * (1 - TRAIL_PCT)
                in_pos = True

        eq = cash + position
        peak = max(peak, eq)
        equity.append({"date":d,"equity":round(eq,2),"prob":round(float(prob),4),
                       "in_pos":in_pos})

    final_eq = equity[-1]["equity"]
    total_ret = (final_eq - INITIAL) / INITIAL * 100
    yrs = len(backtest_dates) / 252
    cagr = ((final_eq / INITIAL) ** (1 / max(yrs, 0.01)) - 1) * 100
    max_dd = max((peak - e["equity"]) / peak * 100 for e in equity)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    wr = len(wins) / max(1, len(trades)) * 100

    bh_ret = (backtest_close[-1] / backtest_close[0] - 1) * 100

    print(f"\nPeriod: {backtest_dates[0]} → {backtest_dates[-1]}  ({len(backtest_dates)} trading days)")
    print(f"Initial: ${INITIAL:,.0f}  Final: ${final_eq:,.0f}")
    print(f"Total Return: {total_ret:+.2f}%  CAGR: {cagr:+.2f}%")
    print(f"Max Drawdown: -{max_dd:.2f}%")
    print(f"Trades: {len(trades)}  Win rate: {wr:.1f}%")
    if wins:   print(f"  Avg win:  ${sum(t['pnl'] for t in wins)/len(wins):,.0f}")
    if losses: print(f"  Avg loss: ${sum(t['pnl'] for t in losses)/len(losses):,.0f}")
    print(f"\nBuy-hold: {bh_ret:+.2f}%  NN outperformance: {total_ret - bh_ret:+.2f}%")

    # 保存结果
    result = {
        "label_type":    LABEL_TYPE,
        "lookahead":     10,
        "drawup_pct":    5.0,
        "architecture":  f"Input({N_FEATURES})→{'→'.join(map(str,HIDDEN_LAYER_SIZES))}→Output(1)",
        "feature_names": FEATURE_COLS,
        "train_period":  f"{dt[0]}→{dt[-1]}",
        "test_period":   f"{ds[0]}→{ds[-1]}",
        "val_auc":       float(roc_auc_score(y_va, model.predict_proba(X_va_n)[:,1])),
        "test_auc":      float(roc_auc_score(y_te, model.predict_proba(X_te_n)[:,1])),
        "backtest": {
            "initial":        INITIAL,
            "final_equity":   round(float(final_eq), 2),
            "total_return":   round(float(total_ret), 2),
            "cagr":           round(float(cagr), 2),
            "max_drawdown":   round(float(max_dd), 2),
            "num_trades":     len(trades),
            "win_rate":       round(float(wr), 2),
            "buy_hold_return":round(float(bh_ret), 2),
            "outperformance": round(float(total_ret - bh_ret), 2),
        },
        "shift_dates": [{"date":d,"close":c,"prob":p} for d,c,p in shift_pts[:30]],
        "feature_importance": feat_imp,
        "trades": trades,
    }
    with open(OUT_RESULT, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {OUT_RESULT}")
    print("Done!")


if __name__ == "__main__":
    if "--check" in sys.argv:
        if LABEL_CSV.exists():
            rows = list(csv.DictReader(open(LABEL_CSV)))
            sh = [float(r["label_shift"]) for r in rows if r.get("label_shift")]
            print(f"Total rows: {len(rows)}")
            print(f"Shift: {sum(1 for v in sh if v==1)}  Safe: {sum(1 for v in sh if v==0)}  ({sum(sh)/max(1,len(sh))*100:.1f}% positive)")
        else:
            print("Run: python3 spy_g5_labeler.py first")
    else:
        main()
