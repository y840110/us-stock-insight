"""
SPY HMM 模型 v3 — 三维度综合确认
维度1：均线状态  (+1/0/-1)
维度2：波动率状态(+1/0/-1)  VIX低→偏多
维度3：量能状态  (+1/0/-1)  OBV增→偏多

三维度加权综合 → 模型自动学习权重
评估：P(上涨|做多信号), P(下跌|做空信号)
"""
import numpy as np
import joblib
from pathlib import Path
from hmmlearn import hmm
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix, classification_report

OUT_DIR   = Path(__file__).parent / 'data'
MODEL_DIR = Path(__file__).parent / 'models'
MODEL_DIR.mkdir(exist_ok=True)


def load_data():
    X_train, y_train = joblib.load(OUT_DIR / 'Xy_train_v3.joblib')
    X_test,  y_test  = joblib.load(OUT_DIR / 'Xy_test_v3.joblib')
    df, disc          = joblib.load(OUT_DIR / 'df_full_v3.joblib')
    fns               = joblib.load(OUT_DIR / 'feature_names_v3.joblib')
    return X_train, y_train, X_test, y_test, df, disc, fns


# ────────────────────────────────────────
# 三维度加权综合信号
# ────────────────────────────────────────
def compute_composite_score(X, feat_idx):
    """
    X 的前三列分别是 ma_state, vol_state, energy_state（已经是 +1/0/-1）
    feat_idx: {name: column_index}
    计算加权综合得分
    """
    ma_s    = X[:, feat_idx['ma_state']]
    vol_s   = X[:, feat_idx['vol_state']]
    energy_s= X[:, feat_idx['energy_state']]

    # 等权重综合（初始）
    composite = ma_s + vol_s + energy_s   # -3 ~ +3
    return composite


def fit_learned_weights(X_train, y_train, X_test, y_test, feat_idx):
    """
    方法一：用 LogisticRegression 在三维度状态上学习最优权重
    三维度状态是 (-1,0,+1)，直接作为特征输入 LR，让模型学习权重
    """
    # 只用三维度状态作为 LR 的输入
    dim_cols = [feat_idx['ma_state'], feat_idx['vol_state'], feat_idx['energy_state']]
    X3_train = X_train[:, dim_cols]
    X3_test  = X_test[:,  dim_cols]

    lr = LogisticRegression(C=1.0, max_iter=500, random_state=42)
    lr.fit(X3_train, y_train)

    # LR 系数 → 学习到的权重
    weights = lr.coef_[0]
    bias    = lr.intercept_[0]

    print('\n─── LR 学习到的三维度权重 ───')
    dim_names = ['均线维度', '波动率维度', '量能维度']
    for name, w in zip(dim_names, weights):
        direction = '→ 偏多' if w > 0 else '→ 偏空'
        print(f'  {name}: {w:+.3f} {direction}')
    print(f'  截距: {bias:+.3f}')

    y_prob = lr.predict_proba(X3_test)[:, 1]
    acc    = (lr.predict(X3_test) == y_test).mean()
    print(f'  3维LR 准确率: {acc:.1%}')

    return lr, weights, bias


def train_hmm_weighted(X_train, y_train, X_test, y_test, feat_idx):
    """
    方法二：GaussianHMM 学状态，但加入三维度加权作为特征
    用完整特征训练 HMM，然后单独用三维度状态训练 LR 做预测
    """
    scaler = StandardScaler()
    Xs_train = scaler.fit_transform(X_train)

    print('\n训练 GaussianHMM...')
    best_model, best_bic, best_n = None, np.inf, 3
    for n in range(2, 7):
        try:
            m = hmm.GaussianHMM(n_components=n, covariance_type='full',
                                 n_iter=300, tol=1e-5, random_state=42)
            m.fit(Xs_train)
            bic = m.bic(Xs_train)
            print(f'  {n}-state  BIC={bic:.0f}')
            if bic < best_bic:
                best_bic, best_model, best_n = bic, m, n
        except Exception as e:
            print(f'  {n}-state failed: {e}')
    print(f'  → 最优: {best_n} states  BIC={best_bic:.0f}')

    # HMM 状态作为特征加给 LR
    states_train = best_model.predict(Xs_train)
    X_with_state = np.column_stack([X_train, states_train.astype(float)])

    Xs_test  = scaler.transform(X_test)
    states_test = best_model.predict(Xs_test)
    X_with_state_test = np.column_stack([X_test, states_test.astype(float)])

    # LR on 完整特征（含隐藏状态）
    lr = LogisticRegression(C=0.5, max_iter=500, random_state=42)
    lr.fit(X_with_state, y_train)
    acc = (lr.predict(X_with_state_test) == y_test).mean()
    print(f'  HMM+LR 准确率: {acc:.1%}')

    return best_model, scaler, lr, X_with_state, X_with_state_test


def analyze_dimension_confluence(df, y_all):
    """
    分析三维度共振对上涨概率的影响
    """
    n = len(df)
    dates = df['date'].tolist()

    # 三维度同向（+1 或 -1 共同）
    # 综合得分 = ma + vol + energy ∈ [-3, +3]
    composite = np.array(df['ma_state']) + np.array(df['vol_state']) + np.array(df['energy_state'])

    print('\n─── 三维度共振分析 ───')
    print(f'综合得分 vs 次日上涨概率:')
    for score in range(-3, 4):
        mask = (composite == score)
        if mask.sum() > 0:
            win = y_all[mask].mean()
            n_days = mask.sum()
            label = f'+{score}' if score >= 0 else str(score)
            bar = '█' * int(win * 30)
            print(f'  得分{label:>3}: {win:5.1%} ({n_days:>3}天) {bar}')


def evaluate_signals(y_true, y_prob, label='',
                     thresholds=[(0.56,0.44),(0.58,0.42),(0.60,0.40)]):
    print(f'\n{'='*50}')
    print(f'  {label}')
    print(f'{'='*50}')
    base_up = y_true.mean()
    base_dn = 1 - base_up
    print(f'基准（永远预测涨）: {base_up:.1%}')
    print(f'基准（永远预测跌）: {base_dn:.1%}')

    for th_up, th_dn in thresholds:
        pred_up = (y_prob >= th_up).astype(int)
        pred_dn = (y_prob <= th_dn).astype(int)
        n_up = int(pred_up.sum())
        n_dn = int(pred_dn.sum())

        print(f'\n阈值: ≥{th_up:.2f} 做多 / ≤{th_dn:.2f} 做空')
        if n_up > 0:
            p_up = y_true[pred_up==1].mean()
            print(f'  做多: {n_up:>4}次  P(涨|做多)={p_up:.1%}  ', end='')
            print('✅' if p_up > base_up+0.05 else '⚠️')
        if n_dn > 0:
            p_dn = 1 - y_true[pred_dn==1].mean()
            print(f'  做空: {n_dn:>4}次  P(跌|做空)={p_dn:.1%}  ', end='')
            print('✅' if p_dn > base_dn+0.05 else '⚠️')

    pred_all = (y_prob >= 0.5).astype(int)
    acc = (pred_all == y_true).mean()
    print(f'\n整体准确率: {acc:.1%}')


def main():
    print('='*55)
    print('  SPY HMM 三维度综合确认模型 v3')
    print('='*55)

    X_train, y_train, X_test, y_test, df, disc, fns = load_data()
    n_f = X_train.shape[1]
    feat_idx = {f: i for i, f in enumerate(fns)}

    print(f'\n特征: {n_f} 个')
    print(f'训练: {len(y_train)} | 测试: {len(y_test)}')
    print(f'上涨基准: {y_train.mean()*100:.1f}%')

    # ── 分析三维度共振 ──
    log_ret = df['log_ret'].values
    y_all   = (log_ret[1:] > 0).astype(int)
    df_for_analysis = df.iloc[:-1].reset_index(drop=True)
    analyze_dimension_confluence(df_for_analysis, y_all)

    # ── 方法一：三维度 LR（学习权重） ──
    print('\n─── 方法一：三维度 LR（自动学习权重）───')
    lr_3d, weights, bias = fit_learned_weights(
        X_train, y_train, X_test, y_test, feat_idx
    )

    # ── 方法二：HMM + LR ──
    print('\n─── 方法二：GaussianHMM + LR ───')
    model, scaler, lr_hmm, Xs_train, Xs_test = train_hmm_weighted(
        X_train, y_train, X_test, y_test, feat_idx
    )

    # ── 对比评估 ──
    y_prob_lr3d  = lr_3d.predict_proba(X_test[:, [feat_idx['ma_state'],
                                                   feat_idx['vol_state'],
                                                   feat_idx['energy_state']]])[:, 1]
    y_prob_hmm   = lr_hmm.predict_proba(Xs_test)[:, 1]
    y_prob_ens   = 0.5 * y_prob_lr3d + 0.5 * y_prob_hmm  # 集成

    print('\n【训练集】')
    y_pt_train = lr_3d.predict_proba(X_train[:, [feat_idx['ma_state'],
                                                  feat_idx['vol_state'],
                                                  feat_idx['energy_state']]])[:, 1]
    evaluate_signals(y_train, y_pt_train, '训练集 2020-2025')

    print('\n【测试集 — 三维度 LR】')
    evaluate_signals(y_test, y_prob_lr3d, '测试集 2026 — 3维LR')

    print('\n【测试集 — HMM+LR】')
    evaluate_signals(y_test, y_prob_hmm, '测试集 2026 — HMM+LR')

    print('\n【测试集 — 集成】')
    evaluate_signals(y_test, y_prob_ens, '测试集 2026 — 集成')

    # ── 保存最佳模型 ──
    joblib.dump((lr_3d, model, scaler, lr_hmm, weights, bias, feat_idx),
                MODEL_DIR / 'hmm_spy_v3d.joblib')
    joblib.dump(fns, MODEL_DIR / 'feature_names_v3.joblib')
    print(f'\n模型已保存: {MODEL_DIR / "hmm_spy_v3d.joblib"}')


if __name__ == '__main__':
    main()
