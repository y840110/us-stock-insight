#!/usr/bin/env python3
"""
SPY 深度学习变盘预测模型
- 特征工程 + 标签生成 + GradientBoosting分类器训练 + 回测
"""

import json
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score, classification_report
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 1. 加载数据
# ============================================================
with open('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines/SPY_1d.json') as f:
    raw = json.load(f)

df = pd.DataFrame(raw['data'])
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)
print(f"数据范围: {df['date'].min().date()} → {df['date'].max().date()}, 共 {len(df)} 条")

# ============================================================
# 2. 特征工程
# ============================================================
def build_features(df):
    """基于 SPY OHLCV 构建技术特征"""
    df = df.copy()
    
    # ---- 价格特征 ----
    df['ret_1d']   = df['close'].pct_change(1)
    df['ret_5d']   = df['close'].pct_change(5)
    df['ret_20d']  = df['close'].pct_change(20)
    
    # 波动率
    df['volatility_5d']  = df['ret_1d'].rolling(5).std()
    df['volatility_20d'] = df['ret_1d'].rolling(20).std()
    
    # 日内波幅
    df['high_low_ratio'] = (df['high'] - df['low']) / df['close']
    
    # 20日高低点
    df['high20'] = df['high'].rolling(20).max()
    df['low20']  = df['low'].rolling(20).min()
    df['close_position'] = (df['close'] - df['low20']) / (df['high20'] - df['low20'] + 1e-10)
    
    # 均线偏离度
    df['ma5']   = df['close'].rolling(5).mean()
    df['ma20']  = df['close'].rolling(20).mean()
    df['ma50']  = df['close'].rolling(50).mean()
    df['ma5_dev']  =  (df['close'] - df['ma5'])  / df['ma5']
    df['ma20_dev'] =  (df['close'] - df['ma20']) / df['ma20']
    df['ma50_dev'] =  (df['close'] - df['ma50']) / df['ma50']
    
    # RSI-14
    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-10)
    df['rsi_14'] = 100 - (100 / (1 + rs))
    
    # 动量
    df['momentum'] = df['close'] / df['close'].shift(20) - 1
    
    # ---- 成交量特征 ----
    df['vol_ma20'] = df['vol'].rolling(20).mean()
    df['vol_ratio'] = df['vol'] / df['vol_ma20']
    
    df['vol_ma5']  = df['vol'].rolling(5).mean()
    df['vol_trend'] = df['vol_ma5'] / (df['vol_ma20'] + 1e-10)
    
    # 量价背离: 价格涨但量萎缩
    df['price_up'] = (df['close'] > df['close'].shift(1)).astype(int)
    df['vol_up']   = (df['vol']   > df['vol'].shift(1)).astype(int)
    df['vol_price_div'] = ((df['price_up'] == 1) & (df['vol_up'] == 0)).astype(int)
    
    # 下跌日放量
    df['price_down'] = (df['close'] < df['close'].shift(1)).astype(int)
    df['price_drop_vol_spike'] = (df['price_down'] & (df['vol_ratio'] > 1.5)).astype(int)
    
    # ---- 组合特征 ----
    df['price_volume_conflict'] = (df['price_up'] != df['vol_up']).astype(int)
    df['abnormal_volume'] = (df['vol_ratio'] > 2.0).astype(int)
    
    # 布林带位置
    bb_mid = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_position'] = (df['close'] - bb_mid) / (2 * bb_std + 1e-10)
    
    # ATR 相对波动
    tr1 = df['high'] - df['low']
    tr2 = abs(df['high'] - df['close'].shift(1))
    tr3 = abs(df['low']  - df['close'].shift(1))
    df['atr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()
    df['atr_pct'] = df['atr'] / df['close']
    
    # MACD
    ema12 = df['close'].ewm(span=12).mean()
    ema26 = df['close'].ewm(span=26).mean()
    df['macd'] = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    
    return df

df = build_features(df)

# ============================================================
# 3. 标签生成 (基于历史数据, 无未来函数)
#    标签=1: 未来20个交易日内, 从当时高点最大回撤超过8%
#    标签=0: 反之
# ============================================================
DRAWDOWN_THRESHOLD = 0.08
LOOK_AHEAD = 20

def make_label(row_idx, prices, threshold, look_ahead):
    """判断从 row_idx 起的未来 look_ahead 天内, SPY 是否从当时高点回撤超过 threshold
    
    正确理解: 当前价格能看到的'当时高点'就是当前价格本身,
    未来最大回撤 = (未来最低点 - 当前价格) / 当前价格
    若 < -threshold (即跌幅超过threshold), 则标签=1 (变盘)
    """
    if row_idx + look_ahead >= len(prices):
        return np.nan
    current_price = prices[row_idx]
    future_prices = prices[row_idx+1 : row_idx+look_ahead+1]
    trough = np.min(future_prices)
    drawdown = (trough - current_price) / current_price
    return 1 if drawdown < -threshold else 0

prices = df['close'].values
labels = []
for i in range(len(df)):
    lbl = make_label(i, prices, DRAWDOWN_THRESHOLD, LOOK_AHEAD)
    labels.append(lbl)

df['label'] = labels

# ============================================================
# 4. 特征列表 & 数据清洗
# ============================================================
feature_cols = [
    'ret_1d', 'ret_5d', 'ret_20d',
    'volatility_5d', 'volatility_20d',
    'high_low_ratio', 'close_position',
    'ma5_dev', 'ma20_dev', 'ma50_dev',
    'rsi_14', 'momentum',
    'vol_ratio', 'vol_trend',
    'vol_price_div', 'price_drop_vol_spike',
    'price_volume_conflict', 'abnormal_volume',
    'bb_position', 'atr_pct',
    'macd_hist', 'macd'
]

# 去除前50行(特征不完整) 和 最后20行(标签不确定)
df_model = df.dropna(subset=feature_cols + ['label']).copy()
df_model = df_model.iloc[:-LOOK_AHEAD]  # 去掉最后LOOK_AHEAD行

print(f"\n有效样本: {len(df_model)} 条")
print(f"正例(变盘)比例: {df_model['label'].mean():.3f}")

# ============================================================
# 5. 训练/测试分割
# ============================================================
# 任务要求: 2020年前训练, 2020后回测
# 由于数据从2020-01-02开始, 使用 2020-01-02~2025-06-30 训练, 2025-07-01~2026-05-12 回测
TRAIN_END   = '2025-06-30'
TEST_START  = '2025-07-01'

train_mask = df_model['date'] <= TRAIN_END
test_mask  = df_model['date'] >= TEST_START

X_train = df_model.loc[train_mask, feature_cols].values
y_train = df_model.loc[train_mask, 'label'].values
X_test  = df_model.loc[test_mask,  feature_cols].values
y_test  = df_model.loc[test_mask,  'label'].values
test_dates = df_model.loc[test_mask, 'date'].values
test_prices = df_model.loc[test_mask, 'close'].values

print(f"\n训练集: {df_model.loc[train_mask, 'date'].min().date()} ~ {df_model.loc[train_mask, 'date'].max().date()}, {len(X_train)} 样本, 正例率 {y_train.mean():.3f}")
print(f"测试集: {df_model.loc[test_mask,  'date'].min().date()} ~ {df_model.loc[test_mask,  'date'].max().date()}, {len(X_test)} 样本, 正例率 {y_test.mean():.3f}")

# ============================================================
# 6. 训练模型 (使用全部训练集, 不用time-series CV因为数据量有限)
# ============================================================
print("\n训练 GradientBoostingClassifier ...")
clf = GradientBoostingClassifier(
    n_estimators=200,
    max_depth=4,
    min_samples_split=20,
    min_samples_leaf=10,
    learning_rate=0.05,
    subsample=0.8,
    random_state=42,
    verbose=0
)
clf.fit(X_train, y_train)

# 评估
if len(np.unique(y_test)) > 1:
    y_proba = clf.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_proba)
    print(f"测试集 AUC: {auc:.4f}")
else:
    print("测试集只有单一类别")

# ============================================================
# 7. 特征重要性
# ============================================================
importances = pd.Series(clf.feature_importances_, index=feature_cols).sort_values(ascending=False)
print("\n特征重要性 Top-10:")
for feat, imp in importances.head(10).items():
    print(f"  {feat:30s} {imp:.4f}")

# ============================================================
# 8. 逐日变盘概率时间序列
# ============================================================
# 在全数据集上生成概率(训练+测试), 用于展示
all_X = df_model[feature_cols].values
all_proba = clf.predict_proba(all_X)[:, 1]
df_model['shift_prob'] = all_proba

# ============================================================
# 9. 回测: 基于ML信号的择时策略
#    - 概率 > 0.7 → 离场(变盘预警)
#    - 概率 < 0.3 → 入场(安全)
#    - 追踪止盈 20%
# ============================================================
PROB_EXIT  = 0.7   # 离场阈值
PROB_ENTRY = 0.3   # 入场阈值
TRAIL_PCT  = 0.20  # 追踪止盈

# 在测试集上回测
bt_df = df_model.loc[test_mask, ['date','close','shift_prob','label']].copy()
bt_df = bt_df.reset_index(drop=True)

# 简单买入持有基准
buy_hold_return = bt_df['close'].iloc[-1] / bt_df['close'].iloc[0] - 1
print(f"\n买入持有收益率(测试期): {buy_hold_return:.2%}")

# ---- 策略回测 ----
position = 0        # 0=空仓, 1=持仓
entry_price = 0
peak_price = 0
trades = []
equity_curve = [100000]
equity = 100000
cash = 100000
shares = 0
in_market = False

for i, row in bt_df.iterrows():
    price = row['close']
    prob  = row['shift_prob']
    
    if i == 0:
        equity_curve.append(equity)
        continue
    
    prev_price = bt_df.loc[i-1, 'close']
    
    # ---- 入场逻辑 ----
    if not in_market and prob < PROB_ENTRY:
        shares = int(cash / price)
        cash = cash - shares * price
        entry_price = price
        peak_price = price
        in_market = True
        trades.append({'date': str(row['date'])[:10], 'action': 'BUY', 'price': price, 'prob': prob})
    
    # ---- 持仓逻辑 ----
    elif in_market:
        # 更新峰值
        if price > peak_price:
            peak_price = price
        
        # 追踪止盈: 从峰值回撤超过20%
        trailing_stop_triggered = (peak_price - price) / peak_price >= TRAIL_PCT
        
        # 变盘预警离场
        danger_exit = prob > PROB_EXIT
        
        if trailing_stop_triggered or danger_exit:
            cash = cash + shares * price
            ret = (price - entry_price) / entry_price
            trades.append({'date': str(row['date'])[:10], 'action': 'SELL', 'price': price, 
                           'prob': prob, 'ret': ret, 'reason': 'trailing_stop' if trailing_stop_triggered else 'danger'})
            shares = 0
            in_market = False
            entry_price = 0
            peak_price = 0
    
    # 计算当日权益
    if in_market:
        equity = cash + shares * price
    else:
        equity = cash
    
    equity_curve.append(equity)

bt_df['equity'] = equity_curve[1:]

# 计算绩效
final_equity = equity_curve[-1]
total_ret = (final_equity - 100000) / 100000
num_trades = len([t for t in trades if t['action'] == 'BUY'])

# 最大回撤
peak = 0
max_dd = 0
for e in equity_curve:
    if e > peak:
        peak = e
    dd = (e - peak) / peak
    if dd < max_dd:
        max_dd = dd

win_trades = [t for t in trades if t['action'] == 'SELL' and t.get('ret', 0) > 0]
win_rate = len(win_trades) / max(len([t for t in trades if t['action'] == 'SELL']), 1)

print(f"\n{'='*60}")
print(f"ML策略回测结果 (测试期: {TEST_START} ~ {bt_df['date'].max()})")
print(f"{'='*60}")
print(f"初始资金: 100,000")
print(f"最终权益: {final_equity:,.2f}")
print(f"总收益率: {total_ret:.2%}")
print(f"最大回撤: {max_dd:.2%}")
print(f"交易次数: {num_trades}")
print(f"胜率:     {win_rate:.1%}")

# ============================================================
# 10. 关键变盘点识别
# ============================================================
shift_dates = bt_df[bt_df['shift_prob'] > PROB_EXIT][['date', 'close', 'shift_prob']].copy()
shift_dates['date'] = shift_dates['date'].astype(str)

print(f"\n高变盘概率日期 (prob > {PROB_EXIT}):")
for _, r in shift_dates.head(15).iterrows():
    print(f"  {r['date'][:10]}  prob={r['shift_prob']:.3f}  price={r['close']:.2f}")

# ============================================================
# 11. 输出结果
# ============================================================
result = {
    "total_return": round(total_ret, 4),
    "max_drawdown": round(max_dd, 4),
    "num_trades": num_trades,
    "win_rate": round(win_rate, 4),
    "final_equity": round(final_equity, 2),
    "baseline_return": round(buy_hold_return, 4),
    "feature_importance": [{"feature": f, "importance": round(imp, 4)} for f, imp in importances.head(10).items()],
    "shift_dates": [{"date": r['date'][:10], "prob": round(r['shift_prob'], 4), "close": round(r['close'], 2)} 
                     for _, r in shift_dates.head(20).iterrows()],
    "vs_baseline": {
        "baseline": "buy_hold",
        "baseline_return": round(buy_hold_return, 4),
        "ml_return": round(total_ret, 4),
        "outperformance": round(total_ret - buy_hold_return, 4)
    }
}

with open('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/spy_shift_ml_result.json', 'w') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

# 保存逐日概率序列
prob_df = df_model[['date', 'close', 'shift_prob', 'label']].copy()
prob_df['date'] = prob_df['date'].astype(str)
prob_df.to_csv('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/spy_shift_prob_timeseries.csv', index=False)

# 保存equity curve
eq_df = pd.DataFrame({'date': bt_df['date'].values, 'equity': equity_curve[1:]})
eq_df['date'] = eq_df['date'].astype(str)
eq_df.to_csv('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/spy_ml_equity_curve.csv', index=False)

print("\n结果已保存:")
print("  - spy_shift_ml_result.json")
print("  - spy_shift_prob_timeseries.csv")
print("  - spy_ml_equity_curve.csv")

# ============================================================
# 12. 与已有最优策略(T15%)对比
# ============================================================
print(f"\n{'='*60}")
print("策略对比")
print(f"{'='*60}")

# S0 基准
s0_initial = 100000.0
s0_final   = 228154.08  # combined_backtest_summary.json
s0_ret     = 128.15 / 100
s0_cagr    = 13.88 / 100
s0_mdd     = -34.02 / 100

print(f"{'策略':<25} {'总收益':>10} {'年化':>8} {'最大回撤':>10} {'交易次数':>8}")
print(f"{'S0 买入持有':<25} {'+128.2%':>10} {'13.88%':>8} {'-34.02%':>10} {'1':>8}")
print(f"{'ML策略(测试期)':<25} {f'{total_ret:.2%}':>10} {'-':>8} {f'{max_dd:.2%}':>10} {num_trades:>8}")

# 注意: 测试期较短(CAGR意义不大)
print(f"\n注: ML策略测试期为 2025-07-01~2026-05-12, 不与全周期S0直接可比")
print(f"买入持有(同期): {buy_hold_return:.2%}")
print(f"ML策略(同期):   {total_ret:.2%}")

# ============================================================
# 13. 可视化: 概率时间序列图
# ============================================================
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    
    fig, axes = plt.subplots(3, 1, figsize=(16, 12), sharex=True)
    
    # 图1: SPY价格 + 均线
    ax = axes[0]
    ax.plot(pd.to_datetime(df_model['date']), df_model['close'], 'k-', lw=1, label='SPY')
    ax.plot(pd.to_datetime(df_model['date']), df_model['ma20'], 'b--', lw=0.8, label='MA20')
    ax.plot(pd.to_datetime(df_model['date']), df_model['ma50'], 'g--', lw=0.8, label='MA50')
    ax.set_ylabel('Price ($)')
    ax.legend(loc='upper left')
    ax.set_title('SPY Price + Moving Averages')
    ax.axvline(pd.to_datetime(TEST_START), color='red', linestyle='--', label='Test Start')
    
    # 图2: 变盘概率
    ax2 = axes[1]
    ax2.fill_between(pd.to_datetime(df_model['date']), df_model['shift_prob'], 
                     alpha=0.4, color='orange', label='Shift Prob')
    ax2.axhline(PROB_EXIT, color='red', linestyle='--', lw=1, label=f'Exit ({PROB_EXIT})')
    ax2.axhline(PROB_ENTRY, color='green', linestyle='--', lw=1, label=f'Entry ({PROB_ENTRY})')
    ax2.set_ylabel('Probability')
    ax2.set_ylim(0, 1)
    ax2.legend(loc='upper left')
    ax2.set_title('Daily Shift Probability (ML Model)')
    ax2.axvline(pd.to_datetime(TEST_START), color='red', linestyle='--')
    
    # 图3: 实际标签 vs 预测概率
    ax3 = axes[2]
    ax3.scatter(pd.to_datetime(df_model.loc[df_model['label']==1, 'date']),
                 df_model.loc[df_model['label']==1, 'shift_prob'],
                 color='red', s=5, alpha=0.5, label='Actual Shift=1')
    ax3.axhline(PROB_EXIT, color='red', linestyle='--', lw=1)
    ax3.set_ylabel('Prob (actual=1)')
    ax3.set_xlabel('Date')
    ax3.legend(loc='upper left')
    ax3.set_title('Actual Shift Events (red=shift) vs ML Probability')
    ax3.axvline(pd.to_datetime(TEST_START), color='red', linestyle='--')
    
    plt.tight_layout()
    out_path = '/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/spy_shift_ml_chart.png'
    plt.savefig(out_path, dpi=120)
    print(f"\n图表已保存: {out_path}")
except Exception as e:
    print(f"\nMatplotlib 图表生成失败: {e}")

print("\n完成!")
