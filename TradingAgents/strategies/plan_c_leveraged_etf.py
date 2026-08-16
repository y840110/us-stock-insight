#!/usr/bin/env python3
"""
方案C — Leveraged ETF 超级牛市增强策略
回测时间: 2020-01-02 → 2026-05-13
初始资金: ¥1,000,000 | 止损: TRAIL=0.15, STOP=0.08, COOL=5天
"""

import json, os, math, warnings
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

BASE = '/home/yudengfeng/.openclaw/workspace/美股投资洞察分析'

# ════════════════════════════════════════════════════════════════════════
# 1. 加载 SPY K线
# ════════════════════════════════════════════════════════════════════════
with open(f'{BASE}/TradingAgents/中间过程/klines/SPY_1d.json') as f:
    raw = json.load(f)
spy = pd.DataFrame(raw['data'])
spy['date'] = pd.to_datetime(spy['date'])
spy = spy.sort_values('date').reset_index(drop=True)
spy = spy.set_index('date')
spy = spy.loc['2020-01-02':'2026-05-13'].copy()
spy['ret']   = spy['close'].pct_change()
spy['ret20'] = spy['close'].pct_change(20)

# ════════════════════════════════════════════════════════════════════════
# 2. 模拟 SSO / UPRO（日收益 = SPY日收益 × 2/3）
# ════════════════════════════════════════════════════════════════════════
n       = len(spy)
sim_ret = spy['ret'].fillna(0).values

sso_arr  = np.full(n, np.nan)
upro_arr = np.full(n, np.nan)
sso_arr[0]  = spy['close'].iloc[0] * 0.50
upro_arr[0] = spy['close'].iloc[0] * 0.30

for i in range(1, n):
    if not np.isnan(sim_ret[i]):
        sso_arr[i]  = sso_arr[i-1]  * (1 + sim_ret[i] * 2)
        upro_arr[i] = upro_arr[i-1] * (1 + sim_ret[i] * 3)

spy['sso_close']  = pd.Series(sso_arr,  index=spy.index)
spy['upro_close'] = pd.Series(upro_arr, index=spy.index)
spy['sso_ret']  = spy['sso_close'].pct_change()
spy['upro_ret'] = spy['upro_close'].pct_change()

print(f'回测区间: {spy.index[0].date()} → {spy.index[-1].date()} ({n} 交易日)')
print(f'SPY: ¥{spy["close"].iloc[0]:.2f}→¥{spy["close"].iloc[-1]:.2f} | '
      f'SSO: ¥{spy["sso_close"].iloc[0]:.2f}→¥{spy["sso_close"].iloc[-1]:.2f} | '
      f'UPRO: ¥{spy["upro_close"].iloc[0]:.2f}→¥{spy["upro_close"].iloc[-1]:.2f}')

# ════════════════════════════════════════════════════════════════════════
# 3. Regime Score
# ════════════════════════════════════════════════════════════════════════
spy['ma20']  = spy['close'].rolling(20).mean()
spy['ma50']  = spy['close'].rolling(50).mean()
spy['ma200'] = spy['close'].rolling(200).mean()
spy['ema50'] = spy['close'].ewm(span=50, adjust=False).mean()  # EMA平滑
spy['vol20'] = spy['ret'].rolling(20).std() * math.sqrt(252)
spy['trend'] = spy['close'] / spy['ma50'] - 1

def regime_score(row):
    """
    双轨Regime：优先用EMA平滑，在MA200不可用时使用稳健简化版
    """
    c   = row['close']
    vol = row['vol20']
    r20 = row['ret20']

    # ── EMA平滑（始终可用，从第50天起有效）────────────────────────
    ema50 = row.get('ema50', c)  # 如果没有就用close
    if pd.isna(ema50):
        ema50 = c

    # ── MA200（数据 >= 200天） ────────────────────────────────
    m200 = row['ma200']
    if pd.isna(m200):
        # 数据不足200天：用更稳健的简化Regime（基于EMA50和动量）
        # 不使用会导致频繁振荡的短期均线交叉
        score = 5.0
        # 价格相对EMA50的位置
        ema_above = 1 if c > ema50 else -1
        score += ema_above * 2.0  # ±2分
        # 20日动量
        if not pd.isna(r20):
            if r20 > 0.05:   score += 2.5
            elif r20 > 0.02:  score += 1.5
            elif r20 > 0:     score += 0.5
            elif r20 < -0.05:  score -= 2.5
            elif r20 < -0.02:  score -= 1.5
            elif r20 < 0:     score -= 0.5
        # 波动率
        if not pd.isna(vol):
            if vol < 0.15:  score += 0.5
            elif vol > 0.40: score -= 0.5
        return max(0.0, min(10.0, score))

    # ── 正常Regime ──────────────────────────────────────────
    m20 = row['ma20']
    score = 5.0
    if c > m20:  score += 2.5
    if m20 > m200: score += 2.5
    if c > m200: score += 1.0
    if not pd.isna(r20):
        if r20 > 0.05:   score += 2.0
        elif r20 > 0.02:  score += 1.0
        elif r20 < -0.05: score -= 2.0
        elif r20 < -0.02: score -= 1.0
    if not pd.isna(vol):
        if vol < 0.15:   score += 0.5
        elif vol > 0.40: score -= 1.0
    return max(0.0, min(10.0, score))

spy['regime'] = spy.apply(regime_score, axis=1)

# ════════════════════════════════════════════════════════════════════════
# 4. 策略信号（需要连续N天满足阈值才切换）
# ════════════════════════════════════════════════════════════════════════
CONSEC = 3  # 连续3天才确认信号切换（防振荡）

def _base_c1(r, r20):
    if pd.isna(r20): r20 = 0
    if r >= 8.0 and r20 > 0:  return 'SSO', 1.0
    if r >= 6.0:                  return 'SPY', 1.0
    if r >= 4.0:                  return 'SPY', 0.5
    return None, 0.0

def _base_c2(r, r20):
    if pd.isna(r20): r20 = 0
    if r >= 9.0 and r20 > 0.05: return 'UPRO', 1.0
    if r >= 7.0:                    return 'SSO', 1.0
    if r >= 5.0:                    return 'SPY', 0.8
    if r >= 3.0:                    return 'SPY', 0.3
    return None, 0.0

# 信号函数（sig_fn接受可选的consec_days参数）
def sig_c1(r, ret20, consec_days=0):
    etf, ratio = _base_c1(r, ret20)
    # 需要CONSEC天连续才升档（SPY→SSO, SPY50→SPY100）
    if ratio == 1.0 and etf == 'SPY' and consec_days < CONSEC:
        # 不升档，维持50%
        return 'SPY', 0.5
    return etf, ratio

def sig_c2(r, ret20, consec_days=0):
    etf, ratio = _base_c2(r, ret20)
    if ratio >= 1.0 and consec_days < CONSEC:
        # 不升档，维持较低档
        if ratio == 1.0 and etf == 'SSO':
            return 'SPY', 0.8
        if ratio == 0.8 and etf == 'SPY':
            return 'SPY', 0.3
    return etf, ratio

# ════════════════════════════════════════════════════════════════════════
# 5. 核心回测引擎
# ════════════════════════════════════════════════════════════════════════
INIT  = 1_000_000.0
TRAIL = 0.20   # 放宽到20%追踪止损（SSO波动更大）
STOP  = 0.10   # 放宽到10%固定止损
COOL  = 5

PRC_COL = {'SPY': 'close',   'SSO': 'sso_close',  'UPRO': 'upro_close'}

def get_px(df_row, etf):
    col = PRC_COL.get(etf, 'close')
    v = df_row.get(col, np.nan)
    if pd.isna(v) or v <= 0:
        return float(df_row['close'])
    return float(v)

def run_bt(df, sig_fn, label):
    cash     = INIT
    shares   = 0.0
    cur_etf  = None
    tgt_r    = 0.0
    in_pos   = False
    entry_p  = 0.0
    peak_p   = 0.0
    cool     = 0
    consec   = 0
    prev_sig = None

    records  = []

    for dt, row in df.iterrows():
        regime = row['regime']
        ret20  = row['ret20']

        # 计算信号和连续天数
        raw_etf, raw_ratio = sig_fn(regime, ret20)
        raw_sig = (raw_etf, raw_ratio)
        if raw_sig == prev_sig:
            consec += 1
        else:
            consec = 1
            prev_sig = raw_sig

        # 带consec的最终信号
        tgt_etf, tgt_ratio = sig_fn(regime, ret20, consec_days=consec)

        cur_px = get_px(row, cur_etf) if in_pos else np.nan

        # ── 止损 ────────────────────────────────────────────────
        stop_hit = False
        if in_pos and entry_p > 0 and not np.isnan(cur_px):
            trail_dd = (peak_p - cur_px) / peak_p if peak_p > 0 else 0.0
            entry_dd = (entry_p - cur_px) / entry_p
            if trail_dd > TRAIL or entry_dd > STOP:
                cash   = shares * cur_px
                shares = 0.0
                in_pos = False
                cur_etf = None
                tgt_r  = 0.0
                cool   = COOL
                stop_hit = True
                records.append({'date': dt, 'equity': float(cash),
                               'etf': None, 'regime': regime, 'action': 'STOP'})
                continue

        # ── 冷却 ──────────────────────────────────────────────
        if cool > 0:
            cool -= 1
            eq = float(cash) if not in_pos else float(cash + shares * cur_px)
            records.append({'date': dt, 'equity': eq,
                           'etf': cur_etf, 'regime': regime, 'action': 'COOL'})
            continue

        # ── 切换 ─────────────────────────────────────────────
        changed = (tgt_etf != cur_etf or abs(tgt_ratio - tgt_r) > 1e-9)

        if changed:
            # 清仓
            if in_pos and not np.isnan(cur_px):
                cash = shares * cur_px
            shares = 0.0
            in_pos = False

            # 开仓
            if tgt_etf is not None and tgt_ratio > 0:
                new_px = get_px(row, tgt_etf)
                invest = cash * tgt_ratio
                if invest > 0 and new_px > 0:
                    shares  = invest / new_px
                    cash   -= invest
                    entry_p = new_px
                    peak_p  = new_px
                    in_pos  = True
                    cur_etf  = tgt_etf
                    tgt_r    = tgt_ratio

        # ── 更新 peak ──────────────────────────────────────────
        if in_pos and not np.isnan(cur_px) and cur_px > peak_p:
            peak_p = cur_px

        # ── equity ───────────────────────────────────────────
        if in_pos and not np.isnan(cur_px) and shares > 0:
            eq = cash + shares * cur_px
        else:
            eq = cash

        records.append({'date': dt, 'equity': float(eq),
                       'etf': cur_etf, 'regime': regime,
                       'action': 'POS' if in_pos else ('SW' if changed else 'CASH')})

    res = pd.DataFrame(records).set_index('date')
    fe   = float(res['equity'].iloc[-1])
    tr   = (fe / INIT - 1) * 100
    yrs  = (df.index[-1] - df.index[0]).days / 365.25
    ar   = ((fe / INIT) ** (1 / yrs) - 1) * 100 if yrs > 0 else 0.0
    pk   = res['equity'].cummax()
    md   = float(((res['equity'] - pk) / pk * 100).min())
    ns   = int((res['action'] == 'STOP').sum())
    return dict(name=label, final_equity=fe, total_return_pct=tr,
                ann_return_pct=ar, max_drawdown_pct=md,
                n_stops=ns, equity_df=res)

# ════════════════════════════════════════════════════════════════════════
# 6. 买入持有基准
# ════════════════════════════════════════════════════════════════════════
def bh(price_col, name):
    p  = spy[price_col].values
    sh = INIT / p[0]
    eq = pd.Series(p * sh, index=spy.index, name='equity')
    res = pd.DataFrame({'equity': eq, 'etf': name.split('_')[0],
                         'regime': 5.0, 'action': 'BH'}, index=spy.index)
    fe  = float(eq.iloc[-1])
    tr  = (fe / INIT - 1) * 100
    yrs = (spy.index[-1] - spy.index[0]).days / 365.25
    ar  = ((fe / INIT) ** (1 / yrs) - 1) * 100 if yrs > 0 else 0.0
    pk  = eq.cummax()
    md  = float(((eq - pk) / pk * 100).min())
    return dict(name=name, final_equity=fe, total_return_pct=tr,
                ann_return_pct=ar, max_drawdown_pct=md,
                n_stops=1, equity_df=res)

results = {}

print('\n═══ SPY 买入持有 ═══')
r = bh('close', 'SPY_买入持有')
results['SPY_买入持有'] = r
print(f'  ¥{r["final_equity"]:>12,.0f} | 总 {r["total_return_pct"]:>7.2f}% | '
      f'年化 {r["ann_return_pct"]:>6.2f}% | 回撤 {r["max_drawdown_pct"]:>7.2f}%')

print('\n═══ SSO 买入持有 ═══')
r = bh('sso_close', 'SSO_买入持有')
results['SSO_买入持有'] = r
print(f'  ¥{r["final_equity"]:>12,.0f} | 总 {r["total_return_pct"]:>7.2f}% | '
      f'年化 {r["ann_return_pct"]:>6.2f}% | 回撤 {r["max_drawdown_pct"]:>7.2f}%')

print('\n═══ UPRO 买入持有 ═══')
r = bh('upro_close', 'UPRO_买入持有')
results['UPRO_买入持有'] = r
print(f'  ¥{r["final_equity"]:>12,.0f} | 总 {r["total_return_pct"]:>7.2f}% | '
      f'年化 {r["ann_return_pct"]:>6.2f}% | 回撤 {r["max_drawdown_pct"]:>7.2f}%')

print('\n═══ 策略 C1（激进 2x SSO，连3天确认）═══')
c1 = run_bt(spy, sig_c1, '策略C1_SSO')
results['策略C1_SSO'] = c1
print(f'  ¥{c1["final_equity"]:>12,.0f} | 总 {c1["total_return_pct"]:>7.2f}% | '
      f'年化 {c1["ann_return_pct"]:>6.2f}% | 回撤 {c1["max_drawdown_pct"]:>7.2f}% | 止损 {c1["n_stops"]}次')

print('\n═══ 策略 C2（保守 3x UPRO，连3天确认）═══')
c2 = run_bt(spy, sig_c2, '策略C2_UPRO')
results['策略C2_UPRO'] = c2
print(f'  ¥{c2["final_equity"]:>12,.0f} | 总 {c2["total_return_pct"]:>7.2f}% | '
      f'年化 {c2["ann_return_pct"]:>6.2f}% | 回撤 {c2["max_drawdown_pct"]:>7.2f}% | 止损 {c2["n_stops"]}次')

# ════════════════════════════════════════════════════════════════════════
# 7. 汇总
# ════════════════════════════════════════════════════════════════════════
print('\n' + '═' * 74)
print('【方案C 综合对比 — Leveraged ETF 超级牛市增强策略 2020-01-02 → 2026-05-13】')
print(f"{'策略':<22} {'最终资金':>14} {'总收益':>10} {'年化':>10} {'最大回撤':>10} {'止损':>6}")
print('-' * 74)
for v in results.values():
    print(f"{v['name']:<22} ¥{v['final_equity']:>12,.0f} "
          f"{v['total_return_pct']:>9.2f}% {v['ann_return_pct']:>9.2f}% "
          f"{v['max_drawdown_pct']:>9.2f}% {v['n_stops']:>5}")
print('═' * 74)

# ════════════════════════════════════════════════════════════════════════
# 8. 保存
# ════════════════════════════════════════════════════════════════════════
out = f'{BASE}/spy_lr_full_backtest'
os.makedirs(out, exist_ok=True)

merged = None
for k, v in results.items():
    eq = v['equity_df'][['equity']].copy()
    eq.columns = [k]
    merged = eq if merged is None else merged.join(eq, how='outer')
merged.to_csv(f'{out}/plan_c_equity.csv')
print(f'\n✅ equity → {out}/plan_c_equity.csv')

summary = {k: {
    'name':              v['name'],
    'final_equity':     round(v['final_equity'], 2),
    'total_return_pct': round(float(v['total_return_pct']), 2),
    'ann_return_pct':   round(float(v['ann_return_pct']), 2),
    'max_drawdown_pct': round(float(v['max_drawdown_pct']), 2),
    'n_stops':         int(v['n_stops'])
} for k, v in results.items()}

with open(f'{out}/plan_c_results.json', 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print(f'✅ JSON   → {out}/plan_c_results.json')

# ════════════════════════════════════════════════════════════════════════
# 9. 绘图
# ════════════════════════════════════════════════════════════════════════
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), sharex=True,
                                    gridspec_kw={'height_ratios': [3, 1]})
    colors = ['#1976D2', '#E64A19', '#388E3C', '#F57C00', '#7B1FA2']

    for i, (k, v) in enumerate(results.values()):
        ax1.plot(v['equity_df'].index, v['equity_df']['equity'] / 1e6,
                  label=v['name'], color=colors[i % len(colors)], linewidth=1.5)

    ax1.axhline(INIT / 1e6, color='gray', ls='--', alpha=0.5, lw=0.8)
    ax1.set_ylabel('资金 (百万元)', fontsize=11)
    ax1.set_title('Plan C — Leveraged ETF 策略对比\n'
                  '(止损 TRAIL=20% STOP=10% COOL=5天，连3天确认信号 | 初始 ¥1,000,000)', fontsize=12)
    ax1.legend(loc='upper left', fontsize=9)
    ax1.grid(True, alpha=0.3)
    ax1.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f'¥{x:.1f}M'))

    ax2.fill_between(spy.index, spy['regime'], 0,
                     where=(spy['regime'] >= 7), color='green', alpha=0.4, label='Super Bull ≥7')
    ax2.fill_between(spy.index, spy['regime'], 0,
                     where=(spy['regime'] < 4), color='red', alpha=0.3, label='Bear <4')
    ax2.plot(spy.index, spy['regime'], color='navy', lw=0.8)
    for thr, clr in [(8, 'green'), (6, 'orange'), (4, 'red')]:
        ax2.axhline(thr, color=clr, ls='--', lw=0.7, alpha=0.6)
    ax2.set_ylabel('Regime Score', fontsize=10)
    ax2.set_xlabel('Date', fontsize=10)
    ax2.set_ylim(0, 10)
    ax2.legend(loc='upper right', fontsize=8)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(f'{out}/plan_c_equity_chart.png', dpi=150, bbox_inches='tight')
    print(f'✅ 图表   → {out}/plan_c_equity_chart.png')
except Exception as e:
    print(f'⚠️ 绘图失败: {e}')

print('\n🎉 Plan C 回测完成！')
