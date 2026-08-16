"""
五类因子计算 v3 — 三维度综合确认模型
维度1：均线信号（EMA5/20/50 交叉状态）
维度2：波动率信号（RV + ATR + VIX 水平）
维度3：量能信号（OBV + 成交量变化率）

每个维度 → 3-state 子信号（偏多/中性/偏空）
三个子信号拼接 → HMM 学习权重 → 综合预测
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path

OUT_DIR  = Path(__file__).parent / 'data'
DATA_DIR = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines')


def load_spy():
    with open(DATA_DIR / 'SPY_1d.json') as f:
        raw = json.load(f)['data']
    return [{'date': b['date'], 'open': b['open'], 'high': b['high'],
             'low': b['low'], 'close': b['close'], 'volume': b.get('volume', 0)}
            for b in raw]


def load_vix():
    with open(DATA_DIR / 'VIX_1d.json') as f:
        raw = json.load(f)['data']
    return {b['date']: b['close'] for b in raw}


def ema(closes, span):
    return pd.Series(closes).ewm(span=span, adjust=False).mean().tolist()


# ════════════════════════════════════════════
# 维度一：均线信号（6个原始指标）
# ════════════════════════════════════════════
def ma_dimension(closes):
    """均线维度：返回 6 个原始指标（分箱前的连续值）"""
    ema5  = ema(closes, 5)
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    n = len(closes)
    # 各均线相对位置（标准化用）
    pos5  = [(c - e5) / (e5 + 1e-9)  for c, e5  in zip(closes, ema5)]
    pos20 = [(c - e20) / (e20 + 1e-9) for c, e20 in zip(closes, ema20)]
    pos50 = [(c - e50) / (e50 + 1e-9) for c, e50 in zip(closes, ema50)]

    # 均线状态：+1（多头） / 0（中性） / -1（空头）
    def cross_state(sig_abv, sig_blw):
        return [1 if a >= 2 else (-1 if b >= 2 else 0)
                for a, b in zip(sig_abv, sig_blw)]

    sig_abv = [sum([ema5[i]>ema20[i], ema20[i]>ema50[i], ema5[i]>ema50[i]]) for i in range(n)]
    sig_blw = [sum([ema5[i]<ema20[i], ema20[i]<ema50[i], ema5[i]<ema50[i]]) for i in range(n)]
    ma_state = cross_state(sig_abv, sig_blw)   # 1=牛, 0=震, -1=熊

    # 短期斜率方向
    slope5  = [0] + [1 if ema5[i]>ema5[i-1]  else -1 for i in range(1,n)]
    slope20 = [0] + [1 if ema20[i]>ema20[i-1] else -1 for i in range(1,n)]

    # 上穿/下穿事件
    gc = [1 if ema5[i]>ema20[i]>ema50[i] else 0 for i in range(n)]
    dc = [1 if ema5[i]<ema20[i]<ema50[i] else 0 for i in range(n)]

    x5_up = [0] + [1 if ema5[i-1]<=ema20[i-1] and ema5[i]>ema20[i] else 0 for i in range(1,n)]
    x5_dn = [0] + [1 if ema5[i-1]>=ema20[i-1] and ema5[i]<ema20[i] else 0 for i in range(1,n)]

    return {
        'ma_pos5':  pos5,   # 价格 vs EMA5
        'ma_pos20': pos20,  # 价格 vs EMA20
        'ma_pos50': pos50,  # 价格 vs EMA50
        'ma_state': ma_state,
        'ma_gc':    gc,     # Golden Cross
        'ma_dc':    dc,     # Death Cross
        'slope5':   slope5,
        'slope20':  slope20,
        'x5_up':    x5_up,
        'x5_dn':    x5_dn,
    }


# ════════════════════════════════════════════
# 维度二：波动率信号（3个原始指标）
# ════════════════════════════════════════════
def vol_dimension(closes, highs, lows, vix_dict, dates):
    """波动率维度：RV、ATR%、VIX"""
    log_ret = np.diff(np.log(np.array(closes) + 1e-9)).tolist()
    log_ret.insert(0, 0.0)

    # 实现波动率（年化）
    rv = pd.Series(log_ret).rolling(20).std() * np.sqrt(252)
    rv = rv.fillna(0).tolist()

    # ATR%
    n = len(closes)
    atr_list = []
    for i in range(n):
        if i == 0:
            tr = highs[0] - lows[0]
        else:
            hl  = highs[i] - lows[i]
            hpc = abs(highs[i] - closes[i-1])
            lpc = abs(lows[i]  - closes[i-1])
            tr  = max(hl, hpc, lpc)
        atr_list.append(tr)
    atr_pct = [atr_list[i] / (closes[i] + 1e-9) for i in range(n)]

    # VIX（2024-05-21 前用 RV×10 代理）
    vix_val = []
    for d in dates:
        if d in vix_dict:
            vix_val.append(vix_dict[d])
        else:
            idx = dates.index(d)
            proxy = rv[idx] * 10 if rv[idx] > 0 else (vix_val[-1] if vix_val else 20.0)
            vix_val.append(proxy)

    # VIX 分位数（近 60 天）
    vix_pct = []
    for i in range(n):
        w = vix_val[max(0,i-59):i+1]
        mn, mx = min(w), max(w)
        vix_pct.append((vix_val[i]-mn)/(mx-mn+1e-9) if mx>mn else 0.5)

    # VIX 变化率
    vix_chg = [0.0]
    for i in range(1, n):
        vix_chg.append((vix_val[i]-vix_val[i-1])/(vix_val[i-1]+1e-9))

    return {
        'rv':      rv,
        'atr_pct': atr_pct,
        'vix':     vix_val,
        'vix_pct': vix_pct,
        'vix_chg': vix_chg,
    }


# ════════════════════════════════════════════
# 维度三：量能信号（2个原始指标）
# ════════════════════════════════════════════
def vol_energy_dimension(closes, volumes):
    """量能维度：OBV 变化率 + 成交量变化率"""
    n = len(closes)

    # OBV
    obv = [0.0]
    for i in range(1, n):
        if closes[i] > closes[i-1]:   obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i-1]:  obv.append(obv[-1] - volumes[i])
        else:                          obv.append(obv[-1])

    # OBV 变化率（10日）
    obv_chg = [0.0] * 10
    for i in range(10, n):
        prev = obv[i-10]
        obv_chg.append((obv[i]-prev)/(abs(prev)+1e-9))

    # 成交量变化率（10日）
    vol_chg = [0.0] * 10
    for i in range(10, n):
        prev = volumes[i-10]
        vol_chg.append((volumes[i]-prev)/(prev+1e-9))

    # OBV 方向强度（10日累计正/负）
    obv_momentum = [0] * n
    for i in range(10, n):
        obv_momentum[i] = 1 if obv[i] > obv[i-10] else -1

    return {
        'obv_chg':     obv_chg,
        'vol_chg':     vol_chg,
        'obv_momentum': obv_momentum,
    }


# ════════════════════════════════════════════
# 三维度 → 3-state 子信号
# ════════════════════════════════════════════
def dimension_state(values, thresholds=None):
    """
    把连续值转成 3-state:  1=偏多 / 0=中性 / -1=偏空
    thresholds: (lower, upper) 分位数，默认为 33%/67% 分位
    """
    vals = np.array(values, dtype=float)
    q33 = float(np.nanpercentile(vals, 33))
    q67 = float(np.nanpercentile(vals, 67))
    state = []
    for v in vals:
        if   v <= q33: state.append(-1)   # 偏空（低值）
        elif v >= q67: state.append( 1)   # 偏多（高值）
        else:          state.append( 0)   # 中性
    return np.array(state), (q33, q67)


def build_factors(spy_bars, vix_dict):
    closes  = np.array([b['close']  for b in spy_bars], dtype=float)
    highs   = np.array([b['high']   for b in spy_bars], dtype=float)
    lows    = np.array([b['low']    for b in spy_bars], dtype=float)
    volumes = np.array([b['volume'] for b in spy_bars], dtype=float)
    dates   = [b['date'] for b in spy_bars]
    n       = len(spy_bars)

    log_ret = np.diff(np.log(closes + 1e-9)).tolist()
    log_ret.insert(0, 0.0)

    # ── 维度一：均线 ──
    ma  = ma_dimension(closes.tolist())
    # 均线状态 1=牛/0=震/-1=熊 → 转为与下一天涨跌的关联
    # 直接用 sig5_20（EMA5 vs EMA20）作为核心指标
    ema5  = ema(closes.tolist(), 5)
    ema20 = ema(closes.tolist(), 20)
    ema50 = ema(closes.tolist(), 50)
    sig5_20 = [1 if e5>e20 else (-1 if e5<e20 else 0)
                for e5, e20 in zip(ema5, ema20)]

    # ── 维度二：波动率 ──
    vol = vol_dimension(closes.tolist(), highs.tolist(), lows.tolist(), vix_dict, dates)

    # ── 维度三：量能 ──
    energy = vol_energy_dimension(closes.tolist(), volumes.tolist())

    # ── 三维度 3-state 信号（用于综合） ──
    # 均线状态：sig5_20 (+1/0/-1)
    ma_state = np.array(sig5_20)   # 直接用均线交叉状态

    # 波动率状态：VIX 高=偏空（-1），VIX 低=偏多（+1）
    # 但 VIX 跟市场反向，所以：VIX 高 → 市场偏空
    vix_state, (vix_q33, vix_q67) = dimension_state(vol['vix'])
    vol_state = -vix_state         # VIX 高=熊（市场跌→波动高），VIX 低=牛

    # 量能状态：OBV 变化率
    obv_state, _ = dimension_state(energy['obv_chg'])

    # ── 三维度拼接（连续值，供 HMM 学习） ──
    # 每个维度标准化后拼接
    df = pd.DataFrame({
        'date':       dates,
        'close':      closes.tolist(),
        'log_ret':    log_ret,

        # 维度一原始指标
        'sig5_20':   sig5_20,
        'ma_gc':     ma['ma_gc'],
        'ma_dc':     ma['ma_dc'],
        'slope5':    ma['slope5'],
        'slope20':   ma['slope20'],
        'x5_up':     ma['x5_up'],
        'x5_dn':     ma['x5_dn'],

        # 维度二原始指标
        'rv':         vol['rv'],
        'atr_pct':    vol['atr_pct'],
        'vix':        vol['vix'],
        'vix_pct':    vol['vix_pct'],
        'vix_chg':    vol['vix_chg'],

        # 维度三原始指标
        'obv_chg':    energy['obv_chg'],
        'vol_chg':    energy['vol_chg'],
        'obv_momentum': energy['obv_momentum'],

        # 三维度状态信号（核心）
        'ma_state':   ma_state.tolist(),    # +1/0/-1
        'vol_state':  vol_state.tolist(),    # +1/0/-1  (VIX低→牛)
        'energy_state': obv_state.tolist(),  # +1/0/-1  (OBV增→牛)

        # 辅助
        'ad_ratio': [sum(1 for v in log_ret[max(0,i-4):i+1] if v>0)/min(i+1,5)
                      for i in range(n)],
        'momentum': [0.0]*5 + [sum(log_ret[i-4:i+1]) for i in range(5, n)],
    })
    return df


def discretize(df):
    """等频分箱连续因子，三维度状态直接用（已是 -1/0/+1）"""
    float_cols = [
        'rv', 'atr_pct', 'vix', 'vix_pct', 'vix_chg',
        'obv_chg', 'vol_chg',
    ]
    disc = df.copy()
    for col in float_cols:
        if col in disc.columns:
            try:
                disc[col] = pd.qcut(disc[col].astype(float), q=5,
                                    labels=False, duplicates='drop')
            except Exception:
                disc[col] = pd.cut(disc[col].astype(float), q=5,
                                    labels=False, duplicates='drop')
            disc[col] = disc[col].fillna(2).astype(int)
    return disc


def prepare_X(df_disc):
    """
    特征向量：
    - 三维度状态信号（ma_state, vol_state, energy_state）— 核心
    - 各维度内的细分信号
    """
    features = [
        # 三维度状态（核心）
        'ma_state', 'vol_state', 'energy_state',
        # 均线细分
        'sig5_20', 'ma_gc', 'ma_dc', 'slope5', 'slope20', 'x5_up', 'x5_dn',
        # 波动率细分
        'rv', 'atr_pct', 'vix', 'vix_pct', 'vix_chg',
        # 量能细分
        'obv_chg', 'vol_chg', 'obv_momentum',
        # 市场结构
        'ad_ratio', 'momentum',
    ]
    X = df_disc[features].values.astype(float)
    return X, features


def main():
    print('=== 因子构建 v3 — 三维度综合确认 ===')
    spy = load_spy()
    vix = load_vix()
    print(f'SPY: {spy[0]["date"]} → {spy[-1]["date"]}, {len(spy)} 条')
    print(f'VIX: {list(vix.keys())[0]} → {list(vix.keys())[-1]}, {len(vix)} 条')

    df     = build_factors(spy, vix)
    disc   = discretize(df)
    X, fns = prepare_X(disc)

    print(f'\n特征数: {len(fns)}')
    print(f'样本:   {X.shape[0]}')

    # 三维度状态分布
    for dim, col in [('均线', 'ma_state'), ('波动率', 'vol_state'), ('量能', 'energy_state')]:
        cnt = df[col].value_counts().sort_index()
        print(f'\n{dim}状态分布:')
        for s, label in [(-1,'偏空'),(0,'中性'),(1,'偏多')]:
            print(f'  {label}: {cnt.get(s,0)}天 ({cnt.get(s,0)/len(df)*100:.0f}%)')

    # 目标变量
    log_ret = df['log_ret'].values
    y = (log_ret[1:] > 0).astype(int)
    X = X[:-1]
    dates = df['date'].iloc[:-1].tolist()

    train_mask = [d < '2026-01-01' for d in dates]
    X_train, y_train = X[train_mask], y[train_mask]
    X_test,  y_test  = X[~np.array(train_mask)], y[~np.array(train_mask)]

    print(f'\n训练: {X_train.shape[0]} | 测试: {X_test.shape[0]}')
    print(f'上涨基准: {y.mean()*100:.1f}%')

    import joblib
    joblib.dump((X_train, y_train), OUT_DIR / 'Xy_train_v3.joblib')
    joblib.dump((X_test,  y_test),  OUT_DIR / 'Xy_test_v3.joblib')
    joblib.dump((df, disc),          OUT_DIR / 'df_full_v3.joblib')
    joblib.dump(fns,                 OUT_DIR / 'feature_names_v3.joblib')
    print('\n已保存 data/')


if __name__ == '__main__':
    main()
