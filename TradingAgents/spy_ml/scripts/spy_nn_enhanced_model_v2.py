#!/usr/bin/env python3
"""
spy_nn_enhanced_model_v2.py
==============================
SPY 增强版神经网络模型 V2 —— 针对 V1 问题全面优化

【V1 核心问题】
1. Label B 只有极值点当天（17/1601 = 1.1% 正例）—— 致命稀疏
2. Regime + Shift 双头共享特征提取器，任务冲突
3. 无类别不平衡处理
4. 特征只有当前快照，无历史上下文

【V2 优化方案】
1. Label B 窗口扩展：极值点 ±10 天标记为 shift=1（正例提升至 ~50%）
2. Regime / Shift 完全独立训练，消除任务冲突
3. Shift 模型使用样本权重手动平衡（sklearn MLP 不支持 class_weight）
4. 时序上下文特征：加入关键特征的 5日/20日 滚动均值和变化率
5. 自适应 split：70% train / 10% val / 20% test（充分利用 502 天数据）
6. 早停 + 验证集监控，防止过拟合

【使用方法】
  python3 spy_nn_enhanced_model_v2.py          # 训练 + 回测
  python3 spy_nn_enhanced_model_v2.py --check  # 检查数据
"""

import json, csv, sys, os
from pathlib import Path
import numpy as np

PROJ        = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents')
OUT_RESULT  = PROJ / 'spy_ml/data/nn_enhanced_v2_result.json'
OUT_PROB    = PROJ / 'spy_ml/data/nn_prob_timeseries_v2.csv'
OUT_MODEL   = PROJ / 'spy_ml/data/nn_enhanced_v2_model.json'

# ═══════════════════════════════════════════════════════════════
# 超参数
# ═══════════════════════════════════════════════════════════════
HIDDEN          = (128, 64, 32)
ALPHA           = 0.001
LR_INIT         = 0.001
MAX_ITER        = 2000
RANDOM_STATE    = 42
MIN_GAP         = 5

# ── Label B V2: 窗口扩展 ───────────────────────────────────
SHIFT_WINDOW    = 10

# ── 回测参数 ──────────────────────────────────────────────
INITIAL         = 1_000_000.0
TRAIL_PCT       = 0.15
COOLDOWN        = 5
ENTRY_BULL_PROB = 0.50
EXIT_SHIFT_PROB = 0.50

# ═══════════════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════════════
def load_spy(start='2020-01-01'):
    bars = []
    with open(PROJ / '中间过程/klines/SPY_1d.json') as f:
        d = json.load(f)
        raw = d.get('data', d) if isinstance(d, dict) else d
        while isinstance(raw, dict): raw = raw.get('data', [])
        for b in raw:
            if b['date'] < start: continue
            bars.append({
                'date':   b['date'],
                'open':   float(b.get('open',   b.get('open_price', 0))),
                'high':   float(b['high']),
                'low':    float(b['low']),
                'close':  float(b['close']),
                'volume': float(b.get('volume', 0)),
            })
    return bars

def load_vix(start='2020-01-01'):
    bars = []
    vix_path = PROJ / '中间过程/klines/VIX_1d.json'
    if not os.path.exists(vix_path):
        print(f'WARNING: VIX not found at {vix_path}, using dummy VIX=20')
        return []
    with open(vix_path) as f:
        d = json.load(f)
        raw = d.get('data', d) if isinstance(d, dict) else d
        while isinstance(raw, dict): raw = raw.get('data', [])
        for b in raw:
            if b['date'] < start: continue
            bars.append({
                'date':  b['date'],
                'high':  float(b.get('vix_high', b.get('high', 20.0))),
                'low':   float(b.get('vix_low',  b.get('low',  20.0))),
                'close': float(b.get('vix_close', b.get('close', 20.0))),
            })
    return bars

# ═══════════════════════════════════════════════════════════════
# 技术指标工具
# ═══════════════════════════════════════════════════════════════
def make_ema(data, period):
    k = 2 / (period + 1)
    out = np.zeros_like(data, dtype=float)
    out[0] = data[0]
    for i in range(1, len(data)):
        out[i] = data[i] * k + out[i - 1] * (1 - k)
    return out

def make_ma(data, period):
    out = np.zeros_like(data, dtype=float)
    for i in range(period - 1, len(data)):
        out[i] = np.mean(data[i - period + 1:i + 1])
    return out

def rolling_std(x, window):
    out = np.zeros_like(x, dtype=float)
    for i in range(window, len(x)):
        out[i] = float(np.std(x[i - window:i]))
    return out

def rolling_mean(x, window):
    out = np.zeros_like(x, dtype=float)
    for i in range(window - 1, len(x)):
        out[i] = float(np.mean(x[i - window + 1:i + 1]))
    return out

def calc_rsi(price, period=14):
    deltas = np.diff(price)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_g = np.zeros(len(price)); avg_l = np.zeros(len(price))
    avg_g[period] = np.mean(gains[:period])
    avg_l[period] = np.mean(losses[:period])
    for i in range(period + 1, len(price)):
        avg_g[i] = (avg_g[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_l[i] = (avg_l[i - 1] * (period - 1) + losses[i - 1]) / period
    rs = avg_g / (avg_l + 1e-10)
    return 100 - 100 / (1 + rs)

# ═══════════════════════════════════════════════════════════════
# 特征工程 V2（27 维原始 + 8 维时序上下文 = 35 维）
# ═══════════════════════════════════════════════════════════════
def compute_features(spy_bars, vix_bars):
    n = len(spy_bars)
    spy_dates  = [b['date']   for b in spy_bars]
    spy_closes = np.array([b['close']  for b in spy_bars], dtype=float)
    spy_highs  = np.array([b['high']   for b in spy_bars], dtype=float)
    spy_lows   = np.array([b['low']    for b in spy_bars], dtype=float)
    spy_vols   = np.array([b['volume'] for b in spy_bars], dtype=float)

    vix_map = {b['date']: b for b in vix_bars}
    vix_c = np.array([vix_map.get(d, {}).get('close', 20.0) for d in spy_dates], dtype=float)
    vix_h = np.array([vix_map.get(d, {}).get('high', 20.0) for d in spy_dates], dtype=float)
    vix_l = np.array([vix_map.get(d, {}).get('low',  20.0) for d in spy_dates], dtype=float)

    # ── SPY EMA ───────────────────────────────────────────
    ema5   = make_ema(spy_closes, 5)
    ema20  = make_ema(spy_closes, 20)
    ema50  = make_ema(spy_closes, 50)
    ema200 = make_ema(spy_closes, 200)

    # ── 收益率 ────────────────────────────────────────────
    ret1   = np.zeros(n)
    ret5   = np.zeros(n)
    ret20  = np.zeros(n)
    ret1[1:]   = (spy_closes[1:]  / spy_closes[:-1]  - 1) * 100
    ret5[5:]   = (spy_closes[5:]  / spy_closes[:-5]   - 1) * 100
    ret20[20:] = (spy_closes[20:]/ spy_closes[:-20]   - 1) * 100

    # ── 波动率 ─────────────────────────────────────────────
    vol5   = rolling_std(ret1, 5)
    vol20  = rolling_std(ret1, 20)

    # ── ATR ───────────────────────────────────────────────
    tr = np.zeros(n - 1)
    for i in range(1, n):
        tr[i - 1] = max(
            spy_highs[i] - spy_lows[i],
            abs(spy_highs[i] - spy_closes[i - 1]),
            abs(spy_lows[i]  - spy_closes[i - 1]),
        )
    atr     = np.zeros(n)
    atr[1:] = make_ema(tr, 14)
    atr_pct = atr / spy_closes * 100

    # ── RSI ───────────────────────────────────────────────
    rsi = calc_rsi(spy_closes, 14)

    # ── MACD ───────────────────────────────────────────────
    ema12  = make_ema(spy_closes, 12)
    ema26  = make_ema(spy_closes, 26)
    macd_l = ema12 - ema26
    macd_s = make_ema(macd_l, 9)
    macd   = macd_l / spy_closes * 100
    macd_h = (macd_l - macd_s) / spy_closes * 100

    # ── 布林带 ────────────────────────────────────────────
    ma20   = make_ma(spy_closes, 20)
    bb_std = rolling_std(spy_closes, 20)
    bb_pos = (spy_closes - (ma20 - 2 * bb_std)) / (4 * bb_std + 1e-10)

    # ── 均线偏离 ──────────────────────────────────────────
    ma5_dev   = (spy_closes - ema5)  / ema5  * 100
    ma20_dev  = (spy_closes - ema20) / ema20 * 100
    ma50_dev  = (spy_closes - ema50) / ema50 * 100

    # ── 价格位置 ──────────────────────────────────────────
    low20   = np.array([min(spy_closes[max(0, i - 20):i + 1]) for i in range(n)])
    high20  = np.array([max(spy_closes[max(0, i - 20):i + 1]) for i in range(n)])
    price_in_range = (spy_closes - low20) / (high20 - low20 + 1e-10)

    # ── 动量 ───────────────────────────────────────────────
    momentum = np.zeros(n)
    for i in range(20, n):
        momentum[i] = (spy_closes[i] / spy_closes[i - 20] - 1) * 100

    # ── 成交量 ─────────────────────────────────────────────
    vol_ma20  = make_ma(spy_vols, 20)
    vol_ratio = spy_vols / (vol_ma20 + 1)
    vol_trend = np.zeros(n)
    for i in range(20, n):
        vol_trend[i] = (vol_ma20[i] / max(vol_ma20[i - 20], 1) - 1) * 100

    # ── VIX ────────────────────────────────────────────────
    vix_ema20 = make_ema(vix_c, 20)
    vix_ret   = np.zeros(n)
    vix_ret[1:] = (vix_c[1:] / vix_c[:-1] - 1) * 100
    vix_pos   = (vix_c - vix_l) / (vix_h - vix_l + 1e-10)
    vix_dev20 = (vix_c - vix_ema20) / vix_ema20 * 100

    # ── 市场结构 ──────────────────────────────────────────
    above_20ema_est = np.where(
        ema20 > 0,
        np.minimum(0.99, np.maximum(0.01, (spy_closes / ema20 - 0.95) * 20)),
        0.5 * np.ones(n),
    )
    avwap      = ema20 * 1.02
    avwap_dev  = (spy_closes - avwap) / avwap * 100
    new_high_proxy = np.where(spy_closes >= high20 * 0.99, 1.0, 0.0)
    new_low_proxy  = np.where(spy_closes <= low20  * 1.01, 1.0, 0.0)

    up_ratio = np.zeros(n)
    for i in range(20, n):
        window_ret = ret1[max(0, i - 20):i]
        up_ratio[i] = sum(window_ret > 0) / max(len(window_ret), 1)

    # ═══════════════════════════════════════════════════════════
    # V2 新增：时序上下文特征
    # ═══════════════════════════════════════════════════════════
    rsi_ma5   = np.zeros(n)
    rsi_ma20  = np.zeros(n)
    vol_ma5   = np.zeros(n)
    vol_ma20  = np.zeros(n)
    macd_ma5  = np.zeros(n)
    macd_ma20 = np.zeros(n)
    rsi_delta = np.zeros(n)
    vix_ret_ma5 = np.zeros(n)
    mom_change  = np.zeros(n)

    for i in range(4, n):
        rsi_ma5[i]   = np.mean(rsi[i-4:i+1])
    for i in range(19, n):
        rsi_ma20[i]  = np.mean(rsi[i-19:i+1])
    for i in range(4, n):
        vol_ma5[i]   = np.mean(vol5[i-4:i+1])
    for i in range(19, n):
        vol_ma20[i]  = np.mean(vol20[i-19:i+1])
    for i in range(4, n):
        macd_ma5[i]  = np.mean(macd[i-4:i+1])
    for i in range(19, n):
        macd_ma20[i] = np.mean(macd[i-19:i+1])
    for i in range(5, n):
        rsi_delta[i]  = rsi[i] - rsi_ma5[i]
        mom_change[i] = momentum[i] - momentum[i-5]
    for i in range(4, n):
        vix_ret_ma5[i] = np.mean(vix_ret[i-4:i+1])

    feat_names = [
        # SPY 价格/量 (5)
        'ret_1d', 'ret_5d', 'ret_20d', 'volatility_5d', 'volatility_20d',
        # 技术指标 (10)
        'atr_pct', 'rsi_14', 'macd', 'macd_hist',
        'ma5_dev', 'ma20_dev', 'ma50_dev',
        'bb_position', 'momentum',
        # 成交量 (3)
        'vol_ratio', 'vol_trend', 'price_in_range',
        # VIX (4)
        'vix_close', 'vix_ema20_dev', 'vix_ret', 'vix_intraday_pos',
        # 市场结构 (5)
        'above_20ema_est', 'avwap_dev', 'new_high_proxy',
        'new_low_proxy', 'up_ratio_20d',
        # V2 时序上下文 (8)
        'rsi_ma5', 'vol_ma5', 'macd_ma5',
        'rsi_ma20', 'vol_ma20', 'macd_ma20',
        'rsi_delta', 'mom_change',
    ]

    X = np.column_stack([
        ret1, ret5, ret20, vol5, vol20,
        atr_pct, rsi, macd, macd_h,
        ma5_dev, ma20_dev, ma50_dev,
        bb_pos, momentum,
        vol_ratio, vol_trend, price_in_range,
        vix_c, vix_dev20, vix_ret, vix_pos,
        above_20ema_est, avwap_dev, new_high_proxy,
        new_low_proxy, up_ratio,
        rsi_ma5, vol_ma5, macd_ma5,
        rsi_ma20, vol_ma20, macd_ma20,
        rsi_delta, mom_change,
    ])
    return feat_names, X, spy_dates, spy_closes


# ═══════════════════════════════════════════════════════════════
# 标签生成 V2
# ═══════════════════════════════════════════════════════════════
def make_labels_v2(dates, closes, mids):
    """
    Label A（Regime）：G5 段分类（bull=1 / bear=0 / range=0.5）
    Label B（Shift）V2：窗口扩展法——极值点 ±SHIFT_WINDOW 天为正例
    """
    from scipy.ndimage import gaussian_filter1d

    curve = gaussian_filter1d(mids, sigma=5)
    d1 = np.gradient(curve, 1.0)
    sc = np.where(np.diff(np.sign(d1)))[0]

    extrema = []
    prev = -MIN_GAP
    for idx in sc:
        if idx - prev < MIN_GAP:
            continue
        d2 = np.gradient(d1, 1.0)
        curv = d2[idx]
        extrema.append({'idx': int(idx), 'date': dates[idx],
                        'type': 'peak' if curv < 0 else 'valley'})
        prev = idx

    # Label A: G5 段
    all_idx = [0] + [e['idx'] for e in extrema] + [len(dates) - 1]
    label_a = {}
    for i in range(len(all_idx) - 1):
        si, ei = all_idx[i], all_idx[i + 1]
        chg = (closes[ei] - closes[si]) / closes[si] * 100
        dur = ei - si
        v = 0.5 if (dur < 5 and abs(chg) < 2) else (1.0 if chg > 0 else 0.0)
        for j in range(si, ei + 1):
            label_a[dates[j]] = v

    # Label B V2: 窗口扩展
    shift_set = set()
    n_dates = len(dates)
    for e in extrema:
        for offset in range(-SHIFT_WINDOW, SHIFT_WINDOW + 1):
            idx = e['idx'] + offset
            if 0 <= idx < n_dates:
                shift_set.add(dates[idx])

    label_b = {d: (1.0 if d in shift_set else 0.0) for d in dates}
    return label_a, label_b, extrema


# ═══════════════════════════════════════════════════════════════
# 计算样本权重（替代 class_weight）
# ═══════════════════════════════════════════════════════════════
def compute_sample_weights(y):
    """
    自动计算平衡样本权重：
    n_pos / n_total  和  n_neg / n_total
    正例权重 = n_neg / n_total，负例权重 = n_pos / n_total
    结果：正负例对总损失的贡献相等
    """
    n = len(y)
    n_pos = int(np.sum(y == 1))
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return np.ones(n)
    w_pos = n_neg / n   # 正例权重
    w_neg = n_pos / n   # 负例权重
    weights = np.where(y == 1, w_pos, w_neg)
    return weights


# ═══════════════════════════════════════════════════════════════
# 训练 + 回测
# ═══════════════════════════════════════════════════════════════
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, accuracy_score


def train_and_backtest():
    print('=' * 70)
    print('SPY Enhanced NN Model V2 — Regime + Shift (Optimized)')
    print('=' * 70)

    # ── 加载数据 ────────────────────────────────────────────
    spy_bars = load_spy('2020-01-01')
    vix_bars = load_vix('2020-01-01')
    feat_names, X_raw, spy_dates, spy_closes_raw = compute_features(spy_bars, vix_bars)
    spy_mids  = np.array([(b['high'] + b['low']) / 2 for b in spy_bars], dtype=float)

    print(f'Features: {len(feat_names)} dims')
    print(f'SPY: {spy_dates[0]} → {spy_dates[-1]}  ({len(spy_dates)} days)')
    print(f'VIX bars: {len(vix_bars)}')

    # ── V2 打标 ─────────────────────────────────────────────
    label_a, label_b, extrema = make_labels_v2(spy_dates, spy_closes_raw, spy_mids)
    n_shift = sum(1 for v in label_b.values() if v == 1.0)
    print(f'\nLabel B (Shift): shift={n_shift} ({n_shift/len(label_b)*100:.1f}%), '
          f'safe={len(label_b)-n_shift} ({(len(label_b)-n_shift)/len(label_b)*100:.1f}%)'
          f'  [V1: 17(1.1%)  →  V2: {n_shift}({n_shift/len(label_b)*100:.1f}%)]')

    # ── 过滤 NaN ────────────────────────────────────────────
    valid = ~np.isnan(X_raw).any(axis=1)
    for i, d in enumerate(spy_dates):
        if label_b.get(d) is None:
            valid[i] = False

    X     = X_raw[valid]
    dates = [spy_dates[i] for i in range(len(spy_dates)) if valid[i]]
    closes= [spy_closes_raw[i] for i in range(len(spy_closes_raw)) if valid[i]]
    la    = np.array([label_a[d] for d in dates], dtype=float)
    lb    = np.array([label_b[d] for d in dates], dtype=float)

    n_total = len(X)
    print(f'Valid samples: {n_total}')

    # ── 自适应时间分割（70/10/20）───────────────────────────
    tr_end_idx = int(n_total * 0.70)
    va_end_idx = int(n_total * 0.80)
    # 确保每个集合至少有一些样本
    tr_end_idx = max(50, min(tr_end_idx, n_total - 50))
    va_end_idx = max(tr_end_idx + 20, va_end_idx)

    tr_idx = list(range(0, tr_end_idx))
    va_idx = list(range(tr_end_idx, va_end_idx))
    te_idx = list(range(va_end_idx, n_total))

    X_tr, X_va, X_te = X[tr_idx], X[va_idx], X[te_idx]
    la_tr, la_va, la_te = la[tr_idx], la[va_idx], la[te_idx]
    lb_tr, lb_va, lb_te = lb[tr_idx], lb[va_idx], lb[te_idx]
    tr_dates = [dates[i] for i in tr_idx]
    va_dates = [dates[i] for i in va_idx]
    te_dates = [dates[i] for i in te_idx]

    print(f'\nSplit (adaptive 70/10/20):')
    print(f'  Train:   {len(X_tr)} days  ({tr_dates[0]} → {tr_dates[-1]})')
    print(f'  Val:     {len(X_va)} days  ({va_dates[0]} → {va_dates[-1]})')
    print(f'  Test:    {len(X_te)} days  ({te_dates[0]} → {te_dates[-1]})')

    # Regime 二分类：bull/range(>=0.5) = 1, bear = 0
    la_tr_bin = (la_tr >= 0.5).astype(int)
    la_va_bin = (la_va >= 0.5).astype(int)
    la_te_bin = (la_te >= 0.5).astype(int)

    print(f'\nTrain label A: bull/range={sum(la_tr_bin)}, bear={len(la_tr_bin)-sum(la_tr_bin)}')
    print(f'Train label B: shift={sum(lb_tr==1)}, safe={sum(lb_tr==0)}')

    # ── 标准化 ───────────────────────────────────────────────
    scaler = StandardScaler()
    X_tr_s = scaler.fit_transform(X_tr)
    X_va_s = scaler.transform(X_va)
    X_te_s = scaler.transform(X_te)

    # ═══════════════════════════════════════════════════════════
    # 模型 1：Regime Classifier
    # ═══════════════════════════════════════════════════════════
    print('\n── Training Regime Model ──')
    nn_regime = MLPClassifier(
        hidden_layer_sizes=HIDDEN,
        activation='relu',
        solver='adam',
        alpha=ALPHA,
        learning_rate_init=LR_INIT,
        max_iter=MAX_ITER,
        early_stopping=True,
        validation_fraction=0.2,
        n_iter_no_change=30,
        random_state=RANDOM_STATE,
        batch_size=min(128, len(X_tr)),
        verbose=False,
    )
    nn_regime.fit(X_tr_s, la_tr_bin)

    reg_va_prob = nn_regime.predict_proba(X_va_s)[:, 1]
    reg_te_prob = nn_regime.predict_proba(X_te_s)[:, 1]
    reg_va_acc  = accuracy_score(la_va_bin, (reg_va_prob > 0.5).astype(int))
    reg_te_acc  = accuracy_score(la_te_bin, (reg_te_prob > 0.5).astype(int))
    reg_te_auc  = roc_auc_score(la_te_bin, reg_te_prob) if len(set(la_te_bin)) > 1 else 0.0

    print(f'Regime Val Accuracy: {reg_va_acc:.3f}  |  Test Accuracy: {reg_te_acc:.3f}  |  AUC: {reg_te_auc:.3f}')
    print(f'Regime iters: {nn_regime.n_iter_}')

    # ═══════════════════════════════════════════════════════════
    # 模型 2：Shift Classifier（手动样本权重平衡）
    # ═══════════════════════════════════════════════════════════
    print('\n── Training Shift Model (balanced sample weights) ──')
    sw_tr = compute_sample_weights(lb_tr)   # 正例权重 n_neg/n, 负例权重 n_pos/n

    nn_shift = MLPClassifier(
        hidden_layer_sizes=HIDDEN,
        activation='relu',
        solver='adam',
        alpha=ALPHA,
        learning_rate_init=LR_INIT,
        max_iter=MAX_ITER,
        early_stopping=True,
        validation_fraction=0.2,
        n_iter_no_change=30,
        random_state=RANDOM_STATE,
        batch_size=min(128, len(X_tr)),
        verbose=False,
    )
    # 手动传入样本权重（sklearn 不支持 class_weight 参数）
    nn_shift.fit(X_tr_s, lb_tr, sample_weight=sw_tr)

    shift_va_prob = nn_shift.predict_proba(X_va_s)[:, 1]
    shift_te_prob = nn_shift.predict_proba(X_te_s)[:, 1]
    shift_va_acc  = accuracy_score(lb_va, (shift_va_prob > 0.5).astype(int))
    shift_te_acc  = accuracy_score(lb_te, (shift_te_prob > 0.5).astype(int))
    shift_te_auc  = roc_auc_score(lb_te, shift_te_prob) if len(set(lb_te)) > 1 else 0.0

    print(f'Shift Val Accuracy: {shift_va_acc:.3f}  |  Test Accuracy: {shift_te_acc:.3f}  |  AUC: {shift_te_auc:.3f}')
    print(f'Shift iters: {nn_shift.n_iter_}')

    # ── 保存概率时间序列 ────────────────────────────────────
    os.makedirs(os.path.dirname(OUT_PROB), exist_ok=True)
    te_close = closes[va_end_idx:]

    with open(OUT_PROB, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'close', 'regime_prob', 'shift_prob', 'label_regime', 'label_shift'])
        for i, d in enumerate(te_dates):
            writer.writerow([
                d,
                round(te_close[i], 2),
                round(float(reg_te_prob[i]), 4),
                round(float(shift_te_prob[i]), 4),
                int(la_te_bin[i]),
                int(lb_te[i]),
            ])
    print(f'\nSaved: {OUT_PROB}')

    # ── 回测（Walk-Forward）─────────────────────────────────
    print('\n── Walk-Forward Backtest ──')
    capital = INITIAL; position = 0.0; cash = INITIAL; peak = INITIAL
    in_pos = False; cooldown = 0; entry_px = 0.0; trail_px = 0.0
    trades = []; equity = []
    shares = 0.0

    for i, d in enumerate(te_dates):
        close    = te_close[i]
        bull_prob = float(reg_te_prob[i])
        probB     = float(shift_te_prob[i])

        if in_pos:
            trail_px = max(trail_px, close * (1 - TRAIL_PCT))
            if close < trail_px:
                pnl      = (close - entry_px) * shares
                cash    += position + pnl
                trades.append({'date': d, 'exit': round(close, 2), 'pnl': round(float(pnl), 2),
                               'reason': 'trailing_stop', 'holding': i})
                position = 0.0; in_pos = False; cooldown = COOLDOWN; peak = max(peak, cash)
            elif probB > EXIT_SHIFT_PROB:
                pnl      = (close - entry_px) * shares
                cash    += position + pnl
                trades.append({'date': d, 'exit': round(close, 2), 'pnl': round(float(pnl), 2),
                               'reason': 'shift_exit', 'holding': i})
                position = 0.0; in_pos = False; cooldown = COOLDOWN; peak = max(peak, cash)
        elif cooldown > 0:
            cooldown -= 1
        else:
            if bull_prob > ENTRY_BULL_PROB and probB < 0.35:
                shares = cash / close
                position = shares * close
                cash     = 0.0
                entry_px = close
                trail_px = close * (1 - TRAIL_PCT)
                in_pos   = True

        eq = cash + position
        peak = max(peak, eq)
        equity.append({'date': d, 'equity': round(eq, 2),
                       'prob_bull': round(bull_prob, 4),
                       'prob_shift': round(probB, 4), 'in_pos': in_pos})

    final_eq  = equity[-1]['equity']
    total_ret = (final_eq - INITIAL) / INITIAL * 100
    yrs       = len(te_dates) / 252
    cagr      = ((final_eq / INITIAL) ** (1 / max(yrs, 0.01)) - 1) * 100
    max_dd    = max((peak - e['equity']) / peak * 100 for e in equity)
    wins      = [t for t in trades if t['pnl'] > 0]
    losses    = [t for t in trades if t['pnl'] <= 0]
    wr        = len(wins) / max(1, len(trades)) * 100
    bh_ret    = (te_close[-1] / te_close[0] - 1) * 100

    print(f'\nPeriod: {te_dates[0]} → {te_dates[-1]}  ({len(te_dates)} days)')
    print(f'Initial: ${INITIAL:,.0f}  Final: ${final_eq:,.0f}')
    print(f'Return: {total_ret:+.2f}%  CAGR: {cagr:+.2f}%')
    print(f'MaxDD: -{max_dd:.2f}%')
    print(f'Trades: {len(trades)}  Win rate: {wr:.1f}%')
    if wins:   print(f'  Avg win:  ${sum(t["pnl"] for t in wins)   / len(wins):,.0f}')
    if losses: print(f'  Avg loss: ${sum(t["pnl"] for t in losses) / len(losses):,.0f}')
    print(f'BuyHold: {bh_ret:+.2f}%  Outperformance: {total_ret - bh_ret:+.2f}%')

    # ── 保存 ────────────────────────────────────────────────
    result = {
        'version': 'v2',
        'features': feat_names,
        'n_features': len(feat_names),
        'architecture': f'Input({len(feat_names)})→{"→".join(map(str, HIDDEN))}→Output(2, separate)',
        'train_period': f'{tr_dates[0]}→{tr_dates[-1]}',
        'val_period':   f'{va_dates[0]}→{va_dates[-1]}',
        'test_period':  f'{te_dates[0]}→{te_dates[-1]}',
        'label_b_shift_window': SHIFT_WINDOW,
        'models': {
            'regime': {
                'type': 'MLP binary (bull/range vs bear)',
                'val_accuracy': round(reg_va_acc, 4),
                'test_accuracy': round(reg_te_acc, 4),
                'test_auc': round(reg_te_auc, 4),
                'n_iter': nn_regime.n_iter_,
            },
            'shift': {
                'type': 'MLP binary (balanced sample weights)',
                'val_accuracy': round(shift_va_acc, 4),
                'test_accuracy': round(shift_te_acc, 4),
                'test_auc': round(shift_te_auc, 4),
                'n_iter': nn_shift.n_iter_,
                'positive_rate_train': round(float(lb_tr.mean()), 4),
                'weights': 'balanced (n_neg/n_pos)',
            },
        },
        'backtest': {
            'initial': INITIAL, 'final_equity': round(float(final_eq), 2),
            'total_return': round(float(total_ret), 2),
            'cagr': round(float(cagr), 2),
            'max_drawdown': round(float(max_dd), 2),
            'num_trades': len(trades),
            'win_rate': round(float(wr), 2),
            'buy_hold_return': round(float(bh_ret), 2),
            'outperformance': round(float(total_ret - bh_ret), 2),
        },
        'trades': trades,
    }

    os.makedirs(os.path.dirname(OUT_RESULT), exist_ok=True)
    with open(OUT_RESULT, 'w') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    model_params = {
        'scaler_mean': scaler.mean_.tolist(),
        'scaler_std': scaler.scale_.tolist(),
        'hidden_sizes': HIDDEN,
        'feature_names': feat_names,
        'regime_classes': ['bear', 'bull_range'],
    }
    with open(OUT_MODEL, 'w') as f:
        json.dump(model_params, f, indent=2)

    print(f'\nSaved: {OUT_RESULT}')
    print(f'Saved: {OUT_MODEL}')
    print('\n✅ V2 training complete!')


if __name__ == '__main__':
    if '--check' in sys.argv:
        for f in [
            PROJ / '中间过程/klines/SPY_1d.json',
            PROJ / '中间过程/klines/VIX_1d.json',
        ]:
            exists = '✅' if f.exists() else '❌'
            print(f'{exists} {f}')
    else:
        train_and_backtest()
