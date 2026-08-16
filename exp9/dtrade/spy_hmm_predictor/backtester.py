"""
SPY HMM 策略回测
评价标准：
  P(上涨|做多信号)  — 买入后次日真的涨了
  P(下跌|做空信号)  — 卖出后次日真的跌了
"""
import numpy as np
import joblib
import pandas as pd
from pathlib import Path

OUT_DIR   = Path(__file__).parent / 'data'
MODEL_DIR = Path(__file__).parent / 'models'
RESULTS   = Path(__file__).parent / 'results'
RESULTS.mkdir(exist_ok=True)


def load_all():
    model, scaler, clf = joblib.load(MODEL_DIR / 'hmm_spy_v3.joblib')
    X_train, y_train   = joblib.load(OUT_DIR / 'Xy_train.joblib')
    X_test,  y_test   = joblib.load(OUT_DIR / 'Xy_test.joblib')
    df, disc           = joblib.load(OUT_DIR / 'df_full.joblib')
    return model, scaler, clf, X_train, y_train, X_test, y_test, df


def add_states(X, model, scaler):
    Xs     = scaler.transform(X)
    states = model.predict(Xs)
    return np.column_stack([X, states.astype(float)])


def run_signal_eval(y_true, y_prob,
                    threshold_up=0.56, threshold_dn=0.44,
                    label=''):
    """
    在给定 y_true / y_prob 上计算信号质量
    """
    pred_up = (y_prob >= threshold_up).astype(int)
    pred_dn = (y_prob <= threshold_dn).astype(int)

    n_up = int(pred_up.sum())
    n_dn = int(pred_dn.sum())
    n_total = len(y_true)

    print(f'\n{'='*40}')
    print(f'  {label}')
    print(f'{'='*40}')

    # P(上涨|做多)
    if n_up > 0:
        mask_up = pred_up == 1
        p_up = y_true[mask_up].mean()
        hit_up = int(y_true[mask_up].sum())
        print(f'做多信号: {n_up} 次 ({n_up/n_total:.0%})')
        print(f'  P(上涨|做多) = {hit_up}/{n_up} = {p_up:.1%}')
        if p_up >= 0.55:
            print(f'  ✅ 有效信号（>{p_up:.0%}）')
        else:
            print(f'  ⚠️ 信号偏弱（<55%）')

    # P(下跌|做空)
    if n_dn > 0:
        mask_dn = pred_dn == 1
        p_down = 1 - y_true[mask_dn].mean()
        hit_dn = int((1 - y_true[mask_dn]).sum())
        print(f'\n做空信号: {n_dn} 次 ({n_dn/n_total:.0%})')
        print(f'  P(下跌|做空) = {hit_dn}/{n_dn} = {p_down:.1%}')
        if p_down >= 0.55:
            print(f'  ✅ 有效信号')
        else:
            print(f'  ⚠️ 信号偏弱')

    # 基准
    base_up = y_true.mean()
    base_dn = 1 - base_up
    print(f'\n基准（永远预测涨）: {base_up:.1%}')
    print(f'基准（永远预测跌）: {base_dn:.1%}')

    # 综合准确率
    pred_all = np.where(y_prob >= 0.5, 1, 0)
    acc = (pred_all == y_true).mean()
    print(f'\n整体准确率: {acc:.1%}')

    # 只做多/只做空策略
    if n_up > 0:
        # 模拟：做多信号出现时全仓买入，次日收盘卖出
        long_return = y_true[mask_up]  # 次日收益率（+1或0）
        avg_long = long_return.mean()
        print(f'\n做多次数: {n_up} | 平均收益: {avg_long:+.2%}')

    if n_dn > 0:
        short_return = 1 - y_true[mask_dn]  # 做空收益：次日跌则赚
        avg_short = short_return.mean()
        print(f'做空次数: {n_dn} | 平均收益: {avg_short:+.2%}')

    return {
        'label': label,
        'n_up': n_up, 'p_up': float(p_up) if n_up > 0 else None,
        'n_dn': n_dn, 'p_down': float(p_down) if n_dn > 0 else None,
        'acc': float(acc),
        'base_up': float(base_up),
    }


def threshold_sweep(y_true, y_prob, label):
    """扫描不同阈值的信号质量"""
    print(f'\n--- 阈值扫描: {label} ---')
    print(f'{'阈值':>8}  {'做多次数':>8}  {'P(涨|做多)':>10}  {'做空次数':>8}  {'P(跌|做空)':>10}')
    print('-'*55)
    for t in [0.50, 0.52, 0.54, 0.56, 0.58, 0.60]:
        p_up_n = ((y_prob >= t) & (y_true == 1)).sum()
        n_up   = (y_prob >= t).sum()
        p_up   = p_up_n / n_up if n_up > 0 else 0

        p_dn_n = ((y_prob <= 1-t) & (y_true == 0)).sum()
        n_dn   = (y_prob <= 1-t).sum()
        p_dn   = p_dn_n / n_dn if n_dn > 0 else 0

        print(f'  {t:.2f}   {n_up:>8}  {p_up:>10.1%}  {n_dn:>8}  {p_dn:>10.1%}')


def main():
    print('=== SPY HMM 信号质量评估 ===\n')

    model, scaler, clf, X_train, y_train, X_test, y_test, df = load_all()

    # 添加隐藏状态
    X_train_s = add_states(X_train, model, scaler)
    X_test_s  = add_states(X_test,  model, scaler)

    # 概率预测
    y_prob_train = clf.predict_proba(X_train_s)[:, 1]
    y_prob_test  = clf.predict_proba(X_test_s)[:, 1]

    # ── 训练集评估 ──
    print('\n【训练集: 2020-2025】')
    res_train = run_signal_eval(y_train, y_prob_train,
                                threshold_up=0.56, threshold_dn=0.44,
                                label='训练集 2020-2025')

    # ── 测试集评估 ──
    print('\n【测试集: 2026】')
    res_test = run_signal_eval(y_test, y_prob_test,
                               threshold_up=0.56, threshold_dn=0.44,
                               label='测试集 2026')

    # ── 阈值扫描 ──
    threshold_sweep(y_train, y_prob_train, '训练集')
    threshold_sweep(y_test,  y_prob_test,  '测试集')

    # ── 保存结果 ──
    df_res = pd.DataFrame([res_train, res_test])
    df_res.to_csv(RESULTS / 'signal_quality.csv', index=False)
    print(f'\n信号质量已保存: {RESULTS / "signal_quality.csv"}')

    # ── 按年度评估 ──
    print('\n【按年度拆分评估（测试集）】')
    # 从 df 取测试集日期
    n_train = len(y_train)
    n_total = len(y_train) + len(y_test)
    test_dates = df['date'].iloc[n_train:n_total].tolist()[:-1]  # y_test 对齐

    years = sorted(set(d[:4] for d in test_dates))
    for yr in years:
        yr_mask = [i for i, d in enumerate(test_dates) if d.startswith(yr)]
        if len(yr_mask) < 5:
            continue
        y_yr = y_test[yr_mask]
        p_yr = y_prob_test[yr_mask]
        n_up = int((p_yr >= 0.56).sum())
        p_up = y_yr[p_yr >= 0.56].mean() if n_up > 0 else 0
        print(f'  {yr}: {len(yr_mask)}天 | 做多信号{n_up}次 P(涨)={p_up:.1%} | 上涨基准={y_yr.mean():.1%}')


if __name__ == '__main__':
    main()
