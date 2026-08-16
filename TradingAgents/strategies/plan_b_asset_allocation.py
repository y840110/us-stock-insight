#!/usr/bin/env python3
"""
方案B — SPY ↔ IEF 跨资产配置切换策略
SPY（股票）和 IEF（中期美国国债 ETF）之间切换
"""

import json
import os
import math
from datetime import datetime

import yfinance as yf
import pandas as pd
import numpy as np

# ── 路径 ──────────────────────────────────────────────────────────────────────
BASE_DIR  = "/home/yudengfeng/.openclaw/workspace/美股投资洞察分析"
SPY_PATH  = os.path.join(BASE_DIR, "TradingAgents/中间过程/klines/SPY_1d.json")
IEF_PATH  = os.path.join(BASE_DIR, "TradingAgents/中间过程/klines/IEF_1d.json")
OUT_DIR   = os.path.join(BASE_DIR, "spy_lr_full_backtest")
os.makedirs(OUT_DIR, exist_ok=True)

# ── 加载 SPY ───────────────────────────────────────────────────────────────────
def load_spy():
    with open(SPY_PATH) as f:
        raw = json.load(f)
    bars = raw["data"]
    df   = pd.DataFrame(bars)[["date", "close"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df        = df.sort_values("date").reset_index(drop=True)
    df["spy"] = df["close"].astype(float)
    return df[["date", "spy"]]

# ── 加载 / 获取 IEF（失败则用 SPY+Cash）───────────────────────────────────────
def load_ief():
    if os.path.exists(IEF_PATH):
        try:
            with open(IEF_PATH) as f:
                raw = json.load(f)
            bars = raw["data"]
            if not bars:
                raise ValueError("IEF file empty")
            df = pd.DataFrame(bars)[["date", "close"]].copy()
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            df["ief"] = df["close"].astype(float)
            return df[["date", "ief"]]
        except Exception as e:
            print(f"IEF local read failed ({e}), retrying fetch")

    print("Fetching IEF/TLT from Yahoo Finance …")
    for ticker in ["IEF", "TLT"]:
        try:
            ief = yf.download(ticker, start="2019-01-02", end="2026-05-14",
                              progress=False)
            if ief.empty:
                continue
            ief = ief.reset_index()
            if isinstance(ief.columns, pd.MultiIndex):
                ief.columns = [c[0] if c[1] == "" else c[0] for c in ief.columns]
            ief.columns = [c.lower() for c in ief.columns]
            ief = ief.rename(columns={"date": "date", "close": "ief"})[["date", "ief"]]
            ief["date"] = pd.to_datetime(ief["date"])
            ief = ief.dropna().sort_values("date").reset_index(drop=True)
            if len(ief) < 100:
                continue
            print(f"  {ticker}: {len(ief)} rows fetched")
            out = {"data": ief.to_dict(orient="records")}
            with open(IEF_PATH, "w") as f:
                json.dump(out, f)
            return ief[["date", "ief"]]
        except Exception as e:
            print(f"  {ticker} failed: {e}")
            continue

    print("IEF/TLT unavailable — using SPY + Cash (4% rf) fallback")
    return None

# ── Regime Score（纯 SPY 自身，无需外部数据）────────────────────────────────
def calc_regime(row, hist):
    spy = row["spy"]
    h   = hist[hist["date"] <= row["date"]]
    if len(h) < 60:
        return 5.0

    ma20  = h["spy"].iloc[-20:].mean()
    ma200 = h["spy"].iloc[-200:].mean() if len(h) >= 200 else h["spy"].mean()
    ret20 = (spy / h["spy"].iloc[-21] - 1) * 100 if len(h) >= 21 else 0.0

    score = 1.0
    if spy > ma20:   score += 3.0
    if spy > ma200:  score += 2.0
    if ret20 > 5:    score += 2.0
    elif ret20 < -5: score -= 2.0

    if len(h) >= 20:
        rets = h["spy"].iloc[-20:].pct_change().dropna()
        vol  = rets.std() * 100
        if vol < 10:   score += 2.0
        elif vol > 25: score -= 2.0

    return max(0.0, min(10.0, score))

# ── 配置映射 ───────────────────────────────────────────────────────────────────
def allocation(regime):
    if regime >= 7.0: return 1.0, 0.0
    if regime >= 5.5: return 0.8, 0.2
    if regime >= 4.0: return 0.5, 0.5
    if regime >= 3.0: return 0.3, 0.7
    return 0.0, 1.0

# ── 主回测 ─────────────────────────────────────────────────────────────────────
def backtest(start_cash=1_000_000,
             bt_start="2020-01-02",
             bt_end="2026-05-13",
             trail=0.15,
             cool=5,
             cash_rate=0.04):

    spy_df = load_spy()
    ief_df = load_ief()

    # 合并数据
    if ief_df is None:
        use_bond = False
        df = spy_df.copy()
        df["ief"] = 0.0
    else:
        use_bond = True
        df = spy_df.merge(ief_df, on="date", how="inner")
        if len(df) < 100:
            print("IEF merge < 100 rows — using SPY + Cash")
            use_bond = False
            df = spy_df.copy()
            df["ief"] = 0.0

    df = df.sort_values("date").reset_index(drop=True)
    df["ief"] = df["ief"].fillna(0.0)
    print(f"数据: {df['date'].min().date()} → {df['date'].max().date()}, {len(df)} 行")
    print(f"Bond: {'IEF/TLT' if use_bond else 'Cash (4% rf)'}\n")

    # Regime Score
    print("计算 Regime Score …")
    regime_list = [calc_regime(df.iloc[i], df.iloc[:i+1]) for i in range(len(df))]
    df["regime"] = regime_list

    # 回测区间
    bt = df[(df["date"] >= bt_start) & (df["date"] <= bt_end)].copy().reset_index(drop=True)
    print(f"回测区间: {bt['date'].min().date()} → {bt['date'].max().date()}, {len(bt)} 行\n")

    # ── 状态变量 ─────────────────────────────────────────────────────────────
    cash      = start_cash
    spy_u     = 0.0
    ief_u     = 0.0
    hw_spy    = start_cash   # SPY 部分高水位
    cool_days = 0

    # 初始配置：100% SPY
    spy_u  = start_cash / bt["spy"].iloc[0]
    ief_u  = 0.0
    cash   = 0.0
    hw_spy = spy_u * bt["spy"].iloc[0]

    daily_rf    = cash_rate / 252
    equity_curve = []
    alloc_curve  = []

    for i, row in bt.iterrows():
        date   = row["date"]
        spy_px = row["spy"]
        ief_px = row["ief"] if use_bond else 0.0
        rs     = row["regime"]

        tgt_spy, tgt_ief = allocation(rs)
        total_eq = spy_u * spy_px + ief_u * ief_px + cash

        # ── 再平衡 ────────────────────────────────────────────────────────
        # 当目标配置变化时触发
        if (abs(tgt_spy - (spy_u * spy_px) / total_eq) > 0.01 or
            abs(tgt_ief - (ief_u * ief_px) / total_eq) > 0.01):

            spy_u  = total_eq * tgt_spy / spy_px
            if use_bond and ief_px > 0:
                ief_u = total_eq * tgt_ief / ief_px
                cash  = 0.0
            else:
                # 无债券数据：IEF 目标仓位转为现金持有（关键修复！）
                ief_u = 0.0
                cash  = total_eq * (1.0 - tgt_spy)   # 保持现金
                # 只把 tgt_spy 部分投入 SPY，其余保留为现金
                spy_u = total_eq * tgt_spy / spy_px
            cool_days = cool
            # 再平衡后重置 SPY 高水位
            if spy_u > 0:
                hw_spy = spy_u * spy_px

        # ── 无风险收益 ────────────────────────────────────────────────────
        cash += cash * daily_rf

        # ── 追踪止损（仅 SPY 部分）─────────────────────────────────────────
        spy_eq = spy_u * spy_px
        if cool_days <= 0 and spy_u > 0:
            if spy_eq < hw_spy:
                dd = (hw_spy - spy_eq) / hw_spy
                if dd >= trail:
                    # 止损出局：SPY → 现金
                    cash  = spy_eq
                    spy_u = 0.0
                    ief_u = 0.0
                    cool_days = cool

        if cool_days > 0:
            cool_days -= 1

        # 更新 SPY 高水位
        if spy_u > 0 and (spy_u * spy_px) > hw_spy:
            hw_spy = spy_u * spy_px

        # 总权益
        total_now = spy_u * spy_px + ief_u * ief_px + cash
        equity_curve.append({"date": str(date.date()), "equity": total_now})
        alloc_curve.append({
            "date":     str(date.date()),
            "spy_pct":  (spy_u * spy_px) / total_now if total_now > 0 else 0.0,
            "ief_pct":  (ief_u * ief_px) / total_now if total_now > 0 else 0.0,
            "cash_pct": cash / total_now if total_now > 0 else 0.0,
            "regime":   rs,
        })

    # ── 保存 ────────────────────────────────────────────────────────────────
    eq_df = pd.DataFrame(equity_curve)
    eq_df.to_csv(os.path.join(OUT_DIR, "plan_b_equity.csv"), index=False)

    alloc_df = pd.DataFrame(alloc_curve)
    alloc_df.to_csv(os.path.join(OUT_DIR, "plan_b_allocation.csv"), index=False)

    # ── 基准：SPY 买入持有 ─────────────────────────────────────────────────
    spy_start_px = bt["spy"].iloc[0]
    spy_end_px   = bt["spy"].iloc[-1]
    bench_ret    = (spy_end_px / spy_start_px - 1) * 100

    # 策略指标
    strat_start_eq = equity_curve[0]["equity"]
    strat_end_eq   = equity_curve[-1]["equity"]
    strat_ret      = (strat_end_eq / strat_start_eq - 1) * 100

    n_years = (bt["date"].iloc[-1] - bt["date"].iloc[0]).days / 365.25
    cagr_bench = ((spy_end_px / spy_start_px) ** (1 / n_years) - 1) * 100
    cagr_strat = ((strat_end_eq / strat_start_eq) ** (1 / n_years) - 1) * 100

    # 最大回撤
    eq_series = eq_df["equity"]
    peak      = eq_series.expanding().max()
    dd_series = (eq_series - peak) / peak * 100
    max_dd    = dd_series.min()

    # 夏普（简化）
    rets   = eq_series.pct_change().dropna()
    sharpe = (rets.mean() / rets.std()) * math.sqrt(252) if rets.std() > 0 else 0.0

    # Regime 分布
    reg_bins = {str(i): 0 for i in range(11)}
    for rs_val in bt["regime"]:
        b = max(0, min(10, int(round(rs_val))))
        reg_bins[str(b)] += 1

    # 各区间表现
    alloc_df["date_idx"] = pd.to_datetime(alloc_df["date"])
    regime_perf = {}
    for lo, hi, label in [
        (7, 11,   "Super Bull [7,10]"),
        (5.5, 7,  "Normal Bull [5.5,7)"),
        (4.0, 5.5,"Neutral [4,5.5)"),
        (3.0, 4.0,"Bearish [3,4)"),
        (0, 3.0,  "Bear [0,3)"),
    ]:
        mask = (alloc_df["regime"] >= lo) & (alloc_df["regime"] < hi)
        if mask.sum() > 0:
            regime_perf[label] = {
                "days":        int(mask.sum()),
                "avg_spy_pct": round(float(alloc_df.loc[mask, "spy_pct"].mean()), 3),
            }

    results = {
        "backtest_start": bt_start,
        "backtest_end":   bt_end,
        "initial_capital": start_cash,
        "benchmark_spy_buy_hold": {
            "return_pct":  round(bench_ret, 2),
            "cagr_pct":    round(cagr_bench, 2),
            "start_price": round(spy_start_px, 2),
            "end_price":   round(spy_end_px, 2),
        },
        "strategy_plan_b": {
            "return_pct":       round(strat_ret, 2),
            "cagr_pct":         round(cagr_strat, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio":     round(sharpe, 3),
            "final_equity":     round(strat_end_eq, 2),
            "bond_used":        "IEF/TLT" if use_bond else "Cash (4% rf)",
        },
        "regime_score_distribution": reg_bins,
        "regime_performance":        regime_perf,
        "trailing_stop_pct": trail,
        "cool_days":          cool,
    }

    with open(os.path.join(OUT_DIR, "plan_b_results.json"), "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # ── 打印 ────────────────────────────────────────────────────────────────
    sep = "=" * 65
    print(sep)
    print("  方案B — SPY ↔ IEF 跨资产配置切换策略  |  回测结果")
    print(sep)
    print(f"  回测区间    : {bt_start} → {bt_end}")
    print(f"  初始资金    : ¥{start_cash:,.0f}")
    print(f"  债券替代    : {'IEF/TLT' if use_bond else 'Cash (4% 年化无风险利率)'}")
    print()
    print(f"  {'指标':<22} {'基准 SPY 买入持有':>18}  {'方案B 策略':>18}")
    print("  " + "-" * 60)
    print(f"  {'总收益率':.<22} {bench_ret:>+17.2f}%  {strat_ret:>+17.2f}%")
    print(f"  {'年化收益率 (CAGR)':.<18} {cagr_bench:>+17.2f}%  {cagr_strat:>+17.2f}%")
    print(f"  {'最大回撤':.<22} {'—':>18}  {max_dd:>+17.2f}%")
    print(f"  {'夏普比率 (简化)':.<22} {'—':>18}  {sharpe:>+17.3f}")
    print(f"  {'期末资金':.<22} {'—':>18}  ¥{strat_end_eq:>16,.0f}")
    print()
    print("  Regime Score 分布（天数）:")
    for k in range(11):
        v   = reg_bins[str(k)]
        pct = v / len(bt) * 100
        bar = "█" * int(pct / 2)
        print(f"    [{k:2d},{k+1:2d}): {v:4d} 天 ({pct:5.1f}%) {bar}")
    print()
    print(f"  输出文件:")
    print(f"    {OUT_DIR}/plan_b_equity.csv")
    print(f"    {OUT_DIR}/plan_b_allocation.csv")
    print(f"    {OUT_DIR}/plan_b_results.json")
    print(sep)

    return results

if __name__ == "__main__":
    backtest()
