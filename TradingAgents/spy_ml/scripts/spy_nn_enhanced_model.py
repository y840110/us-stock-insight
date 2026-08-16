#!/usr/bin/env python3
"""
spy_nn_enhanced_model.py
=========================
SPY 增强版神经网络模型 —— 市场趋势 + 变盘点 联合预测

【改进点】
1. 新增 VIX 数据（OHLCV + 波动率指标）
2. 新增 SPY 自身广度估算（above_20ema_est, breadth_up_ratio）
3. 新增市场结构特征（新高新低比例估算、AVWAP偏离）
4. 保留全部技术指标（均线偏离、MACD、RSI、动量、ATR等）
5. 双标签训练：
   - 标签A（趋势）：bull=1 / bear=0 / range=0.5（G5段分类）
   - 标签B（变盘）：未来10日回撤>3% → shift=1（G5极值点附近±5天）

【网络架构】
Input(27) → Dense(128) → Dense(64) → Dense(32) → Output(2, sigmoid)
                ↓
         两个输出头：
         head_regime: 趋势分类（bull/bear/range）
         head_shift:  变盘概率（0~1）

【使用方法】
  python3 spy_nn_enhanced_model.py              # 训练 + 回测
  python3 spy_nn_enhanced_model.py --check      # 检查数据
"""

import json, csv, sys, time
from pathlib import Path
import numpy as np

PROJ      = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析")
LABEL_CSV = PROJ / "spy_g5_daily_labels.csv"
VIX_FILE  = PROJ / "TradingAgents/中间过程/klines/VIX_1d.json"
OUT_RESULT = PROJ / "spy_nn_enhanced_result.json"
OUT_PROB   = PROJ / "spy_nn_enhanced_prob.csv"
OUT_MODEL  = PROJ / "spy_nn_enhanced_model.json"

# ── 超参数 ────────────────────────────────────────────────────────────────
HIDDEN      = (128, 64, 32)
ALPHA       = 0.001
LR_INIT     = 0.001
MAX_ITER    = 1500
RANDOM_STATE= 42
LOOKAHEAD   = 10
SHIFT_PCT   = 3.0   # 变盘阈值：未来10日回撤>3%
MIN_GAP     = 5      # G5极值点最小间隔

# ── 加载 SPY + VIX ──────────────────────────────────────────────────────
def load_spy(start="2020-01-01"):
    bars = []
    with open(PROJ / "中间过程/klines/SPY_1d.json") as f:
        d = json.load(f)
        raw = d.get("data", d) if isinstance(d, dict) else d
        while isinstance(raw, dict): raw = raw.get("data", [])
        for b in raw:
            if b["date"] < start: continue
            bars.append({k: float(b[k]) if k != "date" else b[k]
                          for k in ["date","high","low","close"]})
    return bars

def load_vix(start="2020-01-01"):
    bars = []
    with open(VIX_FILE) as f:
        d = json.load(f)
        raw = d.get("data", d) if isinstance(d, dict) else d
        while isinstance(raw, dict): raw = raw.get("data", [])
        for b in raw:
            if b["date"] < start: continue
            bars.append({k: float(b[k]) if k != "date" else b[k]
                          for k in ["date","high","low","close"]})
    return bars

def make_ema(data, period):
    k = 2/(period+1); out = np.zeros_like(data); out[0]=data[0]
    for i in range(1, len(data)): out[i]=data[i]*k+out[i-1]*(1-k)
    return out

def make_ma(data, period):
    return np.convolve(data, np.ones(period)/period, mode="same")

def rolling_std(x, window):
    out = np.zeros_like(x, dtype=float)
    for i in range(window, len(x)):
        out[i] = float(np.std(x[i-window:i]))
    return out

def calc_rsi(price, period=14):
    deltas = np.diff(price)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_g = np.zeros(len(price)); avg_l = np.zeros(len(price))
    avg_g[period] = np.mean(gains[:period])
    avg_l[period] = np.mean(losses[:period])
    for i in range(period+1, len(price)):
        avg_g[i] = (avg_g[i-1]*(period-1) + gains[i-1]) / period
        avg_l[i] = (avg_l[i-1]*(period-1) + losses[i-1]) / period
    rs = avg_g / (avg_l + 1e-10)
    return 100 - 100/(1+rs)

# ── 特征工程（增强版）────────────────────────────────────────────────────
def compute_features(spy_bars, vix_bars):
    """生成27维特征向量"""
    n = len(spy_bars)
    spy_dates  = [b["date"]  for b in spy_bars]
    spy_closes = np.array([b["close"]  for b in spy_bars], dtype=float)
    spy_highs  = np.array([b["high"]   for b in spy_bars], dtype=float)
    spy_lows   = np.array([b["low"]    for b in spy_bars], dtype=float)
    spy_vols   = np.array([b.get("volume", b.get("vol", 0)) for b in spy_bars], dtype=float)

    vix_map = {b["date"]: b for b in vix_bars}
    vix_c = np.array([vix_map.get(d, {}).get("close", 20.0) for d in spy_dates], dtype=float)
    vix_h = np.array([vix_map.get(d, {}).get("high", 20.0) for d in spy_dates], dtype=float)
    vix_l = np.array([vix_map.get(d, {}).get("low",  20.0) for d in spy_dates], dtype=float)

    # SPY EMA
    ema5  = make_ema(spy_closes, 5)
    ema20 = make_ema(spy_closes, 20)
    ema50 = make_ema(spy_closes, 50)
    ema200= make_ema(spy_closes, 200)

    # Returns
    ret1  = np.zeros(n); ret1[1:]   = (spy_closes[1:]/spy_closes[:-1]-1)*100
    ret5  = np.zeros(n)
    ret20 = np.zeros(n)
    for i in range(5, n):  ret5[i]  = (spy_closes[i]/spy_closes[i-5]-1)*100
    for i in range(20,n): ret20[i] = (spy_closes[i]/spy_closes[i-20]-1)*100

    # Volatility
    vol5  = rolling_std(ret1, 5)
    vol20 = rolling_std(ret1, 20)

    # ATR
    tr = np.zeros(n-1)
    for i in range(1, n):
        tr[i-1] = max(spy_highs[i]-spy_lows[i],
                       abs(spy_highs[i]-spy_closes[i-1]),
                       abs(spy_lows[i]-spy_closes[i-1]))
    atr    = np.zeros(n); atr[1:]  = make_ema(tr, 14)
    atr_pct= atr / spy_closes * 100

    # RSI
    rsi = calc_rsi(spy_closes, 14)

    # MACD
    ema12 = make_ema(spy_closes, 12)
    ema26 = make_ema(spy_closes, 26)
    macd_l = ema12 - ema26
    macd_s = make_ema(macd_l, 9)
    macd    = macd_l / spy_closes * 100
    macd_h  = (macd_l - macd_s) / spy_closes * 100

    # Bollinger
    ma20    = make_ma(spy_closes, 20)
    bb_std  = rolling_std(spy_closes, 20)
    bb_pos  = (spy_closes - (ma20 - 2*bb_std)) / (4*bb_std + 1e-10)

    # MA deviations
    ma5_dev  = (spy_closes - ema5)  / ema5  * 100
    ma20_dev = (spy_closes - ema20) / ema20 * 100
    ma50_dev = (spy_closes - ema50) / ema50 * 100

    # Price in 20-day range
    low20  = np.array([min(spy_closes[max(0,i-20):i+1]) for i in range(n)])
    high20 = np.array([max(spy_closes[max(0,i-20):i+1]) for i in range(n)])
    price_in_range = (spy_closes - low20) / (high20 - low20 + 1e-10)

    # Momentum
    momentum = np.zeros(n)
    for i in range(20, n):
        momentum[i] = (spy_closes[i]/spy_closes[i-20]-1)*100

    # Volume
    vol_ma20 = make_ma(spy_vols, 20)
    vol_ratio = spy_vols / (vol_ma20 + 1)
    vol_trend = np.zeros(n)
    for i in range(20, n):
        vol_trend[i] = (vol_ma20[i]/max(vol_ma20[i-20],1)-1)*100

    # ── 新增：VIX 特征 ──────────────────────────────────────────────
    vix_ema5  = make_ema(vix_c, 5)
    vix_ema20 = make_ema(vix_c, 20)
    vix_ret   = np.zeros(n); vix_ret[1:] = (vix_c[1:]/vix_c[:-1]-1)*100
    vix_pos   = (vix_c - vix_l) / (vix_h - vix_l + 1e-10)  # VIX日内位置
    vix_dev20 = (vix_c - vix_ema20) / vix_ema20 * 100        # VIX偏离20日均线

    # ── 新增：SPY 自身广度估算 ────────────────────────────────────
    # Above 20EMA 的 SPY 自身代理：SPY 在 20 日区间的位置
    above_20ema_est = np.minimum(0.99, np.maximum(0.01,
        (spy_closes / (ema20 + 1e-10) - 0.97) * 20 + 0.5))
    above_20ema_est = np.where(ema20 > 0,
        np.minimum(0.99, np.maximum(0.01, (spy_closes/ema20 - 0.95)*20)),
        0.5 * np.ones(n))

    # AVWAP 偏离（收盘 / EMA20*1.02 - 1）
    avwap = ema20 * 1.02
    avwap_dev = (spy_closes - avwap) / avwap * 100

    # 新高/新低代理（20日高低点突破）
    new_high_proxy = np.where(spy_closes >= high20 * 0.99, 1.0, 0.0)
    new_low_proxy  = np.where(spy_closes <= low20  * 1.01, 1.0, 0.0)

    # 20日内上涨日 / 下跌日比例
    up_ratio = np.zeros(n)
    for i in range(20, n):
        window_ret = ret1[max(0,i-20):i]
        up_ratio[i] = sum(window_ret > 0) / len(window_ret)

    # ── 组装特征数组 ───────────────────────────────────────────────
    feat_names = [
        # SPY 价格/量 (5)
        "ret_1d", "ret_5d", "ret_20d",
        "volatility_5d", "volatility_20d",
        # 技术指标 (10)
        "atr_pct", "rsi_14", "macd", "macd_hist",
        "ma5_dev", "ma20_dev", "ma50_dev",
        "bb_position", "momentum",
        # 成交量 (3)
        "vol_ratio", "vol_trend", "price_in_range",
        # VIX 特征 (4)
        "vix_close", "vix_ema5_dev", "vix_ret", "vix_intraday_pos",
        # 市场结构 (5)
        "above_20ema_est", "avwap_dev", "new_high_proxy",
        "new_low_proxy", "up_ratio_20d",
    ]
    # 共27维特征
    X = np.column_stack([
        ret1, ret5, ret20,
        vol5, vol20,
        atr_pct, rsi, macd, macd_h,
        ma5_dev, ma20_dev, ma50_dev,
        bb_pos, momentum,
        vol_ratio, vol_trend, price_in_range,
        vix_c, vix_dev20, vix_ret, vix_pos,
        above_20ema_est, avwap_dev, new_high_proxy,
        new_low_proxy, up_ratio,
    ])
    return feat_names, X, spy_dates, spy_closes


# ── 打标函数 ──────────────────────────────────────────────────────────────
def make_labels(dates, closes, mids):
    """Label A: G5段分类 | Label B: 极值点附近"""
    from scipy.ndimage import gaussian_filter1d

    curve = gaussian_filter1d(mids, sigma=5)
    d1 = np.gradient(curve, 1.0)
    sc = np.where(np.diff(np.sign(d1)))[0]
    extrema = []; prev = -MIN_GAP
    for idx in sc:
        if idx - prev < MIN_GAP: continue
        d2 = np.gradient(d1, 1.0); curv = d2[idx]
        extrema.append({"idx":int(idx),"date":dates[idx],
                        "type":"peak" if curv<0 else "valley"})
        prev = idx

    # Label A: bull/bear/range
    all_idx = [0] + [e["idx"] for e in extrema] + [len(dates)-1]
    all_dts = [dates[0]] + [e["date"] for e in extrema] + [dates[-1]]
    label_a = {}
    for i in range(len(all_idx)-1):
        si,ei = all_idx[i],all_idx[i+1]
        chg = (closes[ei]-closes[si])/closes[si]*100
        dur = ei-si
        if dur<5 and abs(chg)<2: v=0.5
        elif chg>0: v=1.0
        else: v=0.0
        for j in range(si, ei+1):
            label_a[dates[j]] = v

    # Label B: 变盘点 = 仅限 G5 极值点本身（峰/谷），无窗口扩散
    shift_set = {e["date"] for e in extrema}

    label_b = {}
    for i, d in enumerate(dates):
        label_b[d] = 1.0 if d in shift_set else 0.0

    return label_a, label_b, extrema


# ── 训练 + 回测 ──────────────────────────────────────────────────────────
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, accuracy_score, classification_report


def train_and_backtest():
    print("=" * 65)
    print("SPY Enhanced NN Model — Regime + Shift Prediction")
    print("=" * 65)

    # 加载数据
    spy_bars = load_spy("2020-01-01")
    vix_bars = load_vix("2020-01-01")
    feat_names, X_raw, spy_dates, spy_closes_raw = compute_features(spy_bars, vix_bars)
    spy_mids = np.array([(b["high"]+b["low"])/2 for b in spy_bars], dtype=float)
    print(f"Features: {len(feat_names)} dims")
    print(f"SPY: {spy_dates[0]} → {spy_dates[-1]}  ({len(spy_dates)} days)")

    # 打标
    label_a, label_b, extrema = make_labels(spy_dates, spy_closes_raw, spy_mids)
    n_a = sum(1 for v in label_a.values() if v is not None)
    n_b = sum(1 for v in label_b.values() if v == 1.0)
    print(f"Label A: bull={sum(1 for v in label_a.values() if v==1)} "
          f"bear={sum(1 for v in label_a.values() if v==0)} "
          f"range={sum(1 for v in label_a.values() if v==0.5)}")
    print(f"Label B: shift={n_b}  (threshold={SHIFT_PCT}%, lookahead={LOOKAHEAD}d)")

    # 过滤有效样本
    valid = ~np.isnan(X_raw).any(axis=1)
    for i, d in enumerate(spy_dates):
        if label_b.get(d) is None: valid[i] = False

    X     = X_raw[valid]
    dates = [spy_dates[i] for i in range(len(spy_dates)) if valid[i]]
    closes= [spy_closes_raw[i] for i in range(len(spy_dates)) if valid[i]]
    la    = np.array([label_a[d] for d in dates], dtype=float)
    lb    = np.array([label_b[d] for d in dates], dtype=float)
    print(f"Valid samples: {len(X)}")

    # 时间分割
    tr_end = "2024-06-01"; te_start = "2025-06-01"
    tr_idx = [i for i,d in enumerate(dates) if d < tr_end]
    va_idx = [i for i,d in enumerate(dates) if tr_end <= d < te_start]
    te_idx = [i for i,d in enumerate(dates) if d >= te_start]
    tr_dates,va_dates,te_dates = ([dates[i] for i in idx] for idx in [tr_idx,va_idx,te_idx])

    X_tr,X_va,X_te = X[tr_idx],X[va_idx],X[te_idx]
    yA_tr,yA_va,yA_te = la[tr_idx],la[va_idx],la[te_idx]
    yB_tr,yB_va,yB_te = lb[tr_idx],lb[va_idx],lb[te_idx]

    # 标准化
    scaler = StandardScaler()
    X_tr_s = scaler.fit_transform(X_tr)
    X_va_s = scaler.transform(X_va)
    X_te_s = scaler.transform(X_te)
    X_all_s = scaler.transform(X)

    # ── 训练两个 NN 模型 ─────────────────────────────────────────────
    print(f"\nTraining Regime NN (bull/bear)...")
    t0 = time.time()
    nn_regime = MLPClassifier(
        hidden_layer_sizes=HIDDEN, activation='relu', solver='adam',
        alpha=ALPHA, learning_rate_init=LR_INIT,
        max_iter=MAX_ITER, early_stopping=True,
        validation_fraction=0.15, n_iter_no_change=30,
        random_state=RANDOM_STATE, verbose=False)
    nn_regime.fit(X_tr_s, yA_tr)
    print(f"  Done in {time.time()-t0:.1f}s, iter={nn_regime.n_iter_}")

    print(f"Training Shift NN...")
    t0 = time.time()
    nn_shift = MLPClassifier(
        hidden_layer_sizes=HIDDEN, activation='relu', solver='adam',
        alpha=ALPHA, learning_rate_init=LR_INIT,
        max_iter=MAX_ITER, early_stopping=True,
        validation_fraction=0.15, n_iter_no_change=30,
        random_state=RANDOM_STATE+1, verbose=False)
    nn_shift.fit(X_tr_s, yB_tr)
    print(f"  Done in {time.time()-t0:.1f}s, iter={nn_shift.n_iter_}")

    # ── 评估 ────────────────────────────────────────────────────────
    for name, Xn, yAn, yBn in [
        ("Train", X_tr_s, yA_tr, yB_tr),
        ("Val",   X_va_s, yA_va, yB_va),
        ("Test",  X_te_s, yA_te, yB_te)]:
        predA = nn_regime.predict(Xn)
        probA = nn_regime.predict_proba(Xn)  # shape (n, 3)
        # 3-class: index0=bear, index1=range, index2=bull
        classes = nn_regime.classes_
        accA = accuracy_score(yAn, predA)
        # AUC for regime: treat range as separate class
        print(f"\n{name} Regime (3-class): Acc={accA:.3f}")
        probB = nn_shift.predict_proba(Xn)[:,1]
        predB = nn_shift.predict(Xn)
        accB = accuracy_score(yBn, predB)
        try: aucB = roc_auc_score(yBn, probB)
        except: aucB = float('nan')
        print(f"{name} Shift (binary):  Acc={accB:.3f}  AUC={aucB:.3f}")

    # ── 全量概率序列 ────────────────────────────────────────────────
    probA_all = nn_regime.predict_proba(X_all_s)   # (n, 3)
    probB_all = nn_shift.predict_proba(X_all_s)[:, 1]

    with open(OUT_PROB, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date","close","prob_regime_bull","prob_regime_bear","prob_shift"])
        w.writeheader()
        for i, d in enumerate(dates):
            w.writerow({
                "date": d,
                "close": round(closes[i], 2),
                "prob_regime_bull": round(float(probA_all[i, list(nn_regime.classes_).index(1.0)] if 1.0 in nn_regime.classes_ else 0), 4),
                "prob_regime_bear": round(float(probA_all[i, 0]), 4),
                "prob_shift": round(float(probB_all[i]), 4),
            })
    print(f"\nSaved: {OUT_PROB}")

    # 特征重要性（通过单特征AUC近似）
    feat_imp = {}
    for i, fn in enumerate(feat_names):
        try:
            auc = roc_auc_score(yB_tr, X_tr_s[:, i])
            feat_imp[fn] = round(float(abs(auc-0.5)*2), 4)
        except:
            feat_imp[fn] = 0.0
    print("\nTop-10 Feature importance (shift prediction):")
    for fn, imp in sorted(feat_imp.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {fn:25s}: {imp:.4f}")

    # ── 回测（综合 Regime + Shift 的复合策略）─────────────────────────
    print("\n" + "=" * 65)
    print("Backtest: Regime × Shift Composite Strategy")
    print("=" * 65)

    te_probA = [probA_all[dates.index(d), :] for d in te_dates]
    te_probB = [float(probB_all[dates.index(d)]) for d in te_dates]
    te_close = [closes[dates.index(d)] for d in te_dates]

    INITIAL  = 1_000_000.0
    STOP_PCT = 0.10
    TRAIL_PCT= 0.15
    COOLDOWN = 5
    ENTRY_BULL_PROB = 0.50   # 牛市概率 > 50% 才考虑入场
    EXIT_SHIFT_PROB = 0.60   # 变盘概率 > 60% 则离场

    capital = INITIAL; position = 0.0; cash = INITIAL; peak = INITIAL
    equity = []; trades = []
    in_pos = False; entry_px = 0.0; trail_px = float('inf'); cooldown = 0

    for i, (d, close, probA, probB) in enumerate(zip(te_dates, te_close, te_probA, te_probB)):
        # probA: [bear_prob, range_prob, bull_prob]
        bull_prob = float(probA[2]) if len(probA) > 2 else float(probA[-1])
        bear_prob = float(probA[0])
        shares = position / close if in_pos else 0.0

        if in_pos:
            # 更新追踪止损
            if close > trail_px:
                trail_px = close * (1 - TRAIL_PCT)
            # 止损检查
            if close < trail_px:
                pnl = (close - entry_px) * shares
                cash += position + pnl
                trades.append({"date":d,"exit":round(close,2),"pnl":round(float(pnl),2),
                               "reason":"trailing_stop","holding":i})
                position = 0.0; in_pos = False; cooldown = COOLDOWN; peak = max(peak, cash)
            # Shift 退出
            elif probB > EXIT_SHIFT_PROB:
                pnl = (close - entry_px) * shares
                cash += position + pnl
                trades.append({"date":d,"exit":round(close,2),"pnl":round(float(pnl),2),
                               "reason":"shift_exit","holding":i})
                position = 0.0; in_pos = False; cooldown = COOLDOWN; peak = max(peak, cash)
        elif cooldown > 0:
            cooldown -= 1
        else:
            # 入场：牛市概率高 + 变盘概率低
            if bull_prob > ENTRY_BULL_PROB and probB < 0.3:
                shares_to_buy = cash / close
                position = shares_to_buy * close
                cash = 0.0
                entry_px = close
                trail_px = close * (1 - TRAIL_PCT)
                in_pos = True

        eq = cash + position
        peak = max(peak, eq)
        equity.append({"date":d,"equity":round(eq,2),"prob_bull":round(bull_prob,4),
                       "prob_shift":round(float(probB),4),"in_pos":in_pos})

    final_eq = equity[-1]["equity"]
    total_ret = (final_eq - INITIAL) / INITIAL * 100
    yrs = len(te_dates) / 252
    cagr = ((final_eq/INITIAL)**(1/max(yrs,0.01))-1)*100
    max_dd = max((peak-e["equity"])/peak*100 for e in equity)
    wins = [t for t in trades if t["pnl"]>0]
    losses = [t for t in trades if t["pnl"]<=0]
    wr = len(wins)/max(1,len(trades))*100
    bh_ret = (te_close[-1]/te_close[0]-1)*100

    print(f"\nPeriod: {te_dates[0]} → {te_dates[-1]}  ({len(te_dates)} days)")
    print(f"Initial: ${INITIAL:,.0f}  Final: ${final_eq:,.0f}")
    print(f"Return: {total_ret:+.2f}%  CAGR: {cagr:+.2f}%")
    print(f"MaxDD: -{max_dd:.2f}%")
    print(f"Trades: {len(trades)}  Win rate: {wr:.1f}%")
    if wins:   print(f"  Avg win:  ${sum(t['pnl'] for t in wins)/len(wins):,.0f}")
    if losses: print(f"  Avg loss: ${sum(t['pnl'] for t in losses)/len(losses):,.0f}")
    print(f"\nBuyHold: {bh_ret:+.2f}%  Outperformance: {total_ret-bh_ret:+.2f}%")

    # ── 保存 ────────────────────────────────────────────────────────
    result = {
        "features": feat_names,
        "n_features": len(feat_names),
        "architecture": f"Input({len(feat_names)})→{'→'.join(map(str,HIDDEN))}→Output(2)",
        "train_period": f"{tr_dates[0]}→{tr_dates[-1]}",
        "test_period":  f"{te_dates[0]}→{te_dates[-1]}",
        "shift_threshold": SHIFT_PCT,
        "shift_lookahead": LOOKAHEAD,
        "backtest": {
            "initial": INITIAL, "final_equity": round(float(final_eq),2),
            "total_return": round(float(total_ret),2), "cagr": round(float(cagr),2),
            "max_drawdown": round(float(max_dd),2), "num_trades": len(trades),
            "win_rate": round(float(wr),2), "buy_hold_return": round(float(bh_ret),2),
            "outperformance": round(float(total_ret-bh_ret),2),
        },
        "feature_importance": feat_imp,
        "trades": trades,
    }
    with open(OUT_RESULT, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    with open(OUT_MODEL, "w") as f:
        json.dump({"scaler_mean": scaler.mean_.tolist(),
                   "scaler_std": scaler.scale_.tolist(),
                   "hidden_sizes": HIDDEN,
                   "classes": ["bear","range","bull"],
                   "feature_names": feat_names}, f, indent=2)
    print(f"\nSaved: {OUT_RESULT}")
    print(f"Saved: {OUT_MODEL}")
    print("\nDone!")


if __name__ == "__main__":
    if "--check" in sys.argv:
        import os
        for f in [LABEL_CSV, VIX_FILE]:
            print(f"{f.name}: exists={os.path.exists(f)}")
    else:
        train_and_backtest()
