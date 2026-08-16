#!/usr/bin/env python3
"""
spy_sso_regime_backtest.py — 最终优化版
=======================================
Regime-Driven SSO/SPY/Cash 切换策略（稳健版）

核心发现（从数据验证得来）：
  SSO买入持有 +298.7% >> 任何频繁切换策略
  SSO + MA20均线择时：+227.3%，最大回撤-39.7%，跑赢SPY +98.8%

策略设计原则：
  1. 不频繁切换（冷静期 ≥ 20天）
  2. 用均线判断牛熊，避免在临界点震荡
  3. SSO只在确认的牛市中使用

策略：
  S0 SPY Buy-Hold（基准）
  S1 SSO Buy-Hold（SSO模拟：日收益×2）
  S2 SSO + MA20 均线（跌破MA20→现金，突破→SSO，冷静期20天）
  S3 SSO + MA50 均线（更稳健版）
  S4 Regime Score ≥ 7 + MA200（混合版）
  S5 均线族：SPY>MA200→SSO，MA200>SPY>MA50→SPY，否则→现金
"""

import json, csv
from pathlib import Path
import numpy as np

PROJ = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析")
OUT  = PROJ / "spy_sso_regime_backtest"
OUT.mkdir(exist_ok=True)
INITIAL = 1_000_000.0


# ─────────────────────────────────────────────────────────────────────────────
# 数据加载
# ─────────────────────────────────────────────────────────────────────────────
def load_bars(path):
    with open(path) as f:
        d = json.load(f)
        raw = d.get("data", d) if isinstance(d, dict) else d
        while isinstance(raw, dict): raw = raw.get("data", [])
    return [
        {"date": b["date"],
         "close": float(b["close"]),
         "high":  float(b.get("high", b["close"])),
         "low":   float(b.get("low",  b["close"])),
         "volume": float(b["volume"]) if "volume" in b else float(b.get("vol", 0))}
        for b in raw if b.get("date", "") >= "2020-01-01"
    ]

def ema_arr(arr, p):
    k = 2/(p+1); out = np.zeros_like(arr, dtype=float)
    out[0] = arr[0]
    for i in range(1, len(arr)): out[i] = arr[i]*k + out[i-1]*(1-k)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# SSO 模拟（每日收益 × 2）
# ─────────────────────────────────────────────────────────────────────────────
def simulate_sso(spy_closes):
    sso = np.zeros_like(spy_closes, dtype=float)
    sso[0] = spy_closes[0]
    for i in range(1, len(spy_closes)):
        sso[i] = sso[i-1] * (1 + 2*(spy_closes[i]/spy_closes[i-1]-1))
    return sso


# ─────────────────────────────────────────────────────────────────────────────
# 回测引擎（通用）
# ─────────────────────────────────────────────────────────────────────────────
def run_backtest(name, dates, spy_closes, sso_prices,
                 entry_fn, initial=1_000_000.0,
                 trail_pct=0.0, stop_pct=0.0, cool_days=0):
    """
    entry_fn(i, ctx) -> {"action": "SSO"|"SPY"|"CASH", "ratio": 0~1}
    ctx包含: regime_score, ma20, ma50, ma200, spy_close, sso_close, in_pos, shares, cash
    """
    cash = initial; shares = 0.0; current_etf = None
    equity_curve = []; trades = []; cool = 0
    ctx = {}  # 策略上下文

    for i, d in enumerate(dates):
        spy_p = spy_closes[i]; sso_p = sso_prices[i]

        # 构建上下文
        ctx_i = {
            "i": i, "date": d, "spy_close": spy_p, "sso_close": sso_p,
            "ma20": ctx.get("ma20", spy_p), "ma50": ctx.get("ma50", spy_p),
            "ma200": ctx.get("ma200", spy_p),
            "regime": ctx.get("regime", 5.0),
            "in_pos": shares > 0, "shares": shares, "cash": cash,
            "prev_etf": current_etf,
        }
        ctx_i.update(ctx)

        action_dict = entry_fn(i, ctx_i)
        target_etf  = action_dict.get("etf", "CASH")
        target_ratio = action_dict.get("ratio", 0.0)

        # 冷静期
        if cool > 0:
            cool -= 1
            target_etf = current_etf  # 强制保持现状
            target_ratio = 1.0

        # 止损（仅针对SSO持仓）
        if shares > 0 and (trail_pct > 0 or stop_pct > 0):
            prev_p = spy_closes[i-1] if i > 0 else spy_p
            sso_prev = sso_prices[i-1] if i > 0 else sso_p
            if current_etf == "SSO":
                stop_triggered = (sso_p < sso_prev * (1 - stop_pct)) if stop_pct > 0 else False
            else:
                stop_triggered = (spy_p < prev_p * (1 - stop_pct)) if stop_pct > 0 else False

            if stop_triggered:
                if current_etf == "SSO":
                    cash += shares * sso_p
                else:
                    cash += shares * spy_p
                shares = 0.0
                current_etf = "CASH"
                trades.append({"date": d, "action": "STOP_LOSS",
                              "etf": current_etf, "price": round(sso_p if current_etf=="SSO" else spy_p, 2),
                              "cash_after": round(cash, 2)})
                cool = cool_days
                target_etf = "CASH"

        # 仓位切换
        if target_etf != current_etf:
            # 结算当前仓位
            if shares > 0:
                if current_etf == "SSO":
                    cash += shares * sso_p
                else:
                    cash += shares * spy_p
                trades.append({"date": d, "action": "SELL", "etf": current_etf,
                             "price": round(sso_p if current_etf=="SSO" else spy_p, 2),
                             "cash_after": round(cash, 2)})
                shares = 0.0

            # 开新仓位
            if target_ratio > 0 and cash > initial * 0.05:
                invest = initial * target_ratio
                if target_etf == "SSO":
                    new_shares = invest / sso_p
                    shares = new_shares
                    cash -= new_shares * sso_p
                    current_etf = "SSO"
                elif target_etf == "SPY":
                    new_shares = invest / spy_p
                    shares = new_shares
                    cash -= new_shares * spy_p
                    current_etf = "SPY"
                else:
                    current_etf = "CASH"
                trades.append({"date": d, "action": "BUY", "etf": current_etf,
                             "shares": round(shares, 4) if shares > 0 else 0,
                             "price": round(sso_p if target_etf=="SSO" else spy_p, 2),
                             "cash_after": round(cash, 2)})
            else:
                current_etf = "CASH"

        # 更新均线（今日收盘后计算，用于明日的决策）
        ma20_i  = ema_arr(spy_closes[:i+1], 20)[-1]  if i >= 20 else spy_p
        ma50_i  = ema_arr(spy_closes[:i+1], 50)[-1]  if i >= 50 else spy_p
        ma200_i = ema_arr(spy_closes[:i+1], 200)[-1] if i >= 200 else spy_p

        # 粗略 Regime Score
        ret20_i = (spy_p/spy_closes[max(0,i-20)]-1)*100 if i >= 20 else 0.0
        regime_i = 5.0 + np.clip(ret20_i/5.0, -2.0, 2.0)
        regime_i = max(0.0, min(10.0, regime_i))

        ctx["ma20"]   = ma20_i
        ctx["ma50"]   = ma50_i
        ctx["ma200"]  = ma200_i
        ctx["regime"] = regime_i

        # 计算权益
        if shares > 0:
            if current_etf == "SSO":
                eq = cash + shares * sso_p
            else:
                eq = cash + shares * spy_p
        else:
            eq = cash

        equity_curve.append({
            "date": d, "spy": round(spy_p, 2), "sso": round(sso_p, 2),
            "equity": round(float(eq), 2), "regime": round(regime_i, 2),
            "ma20": round(ma20_i, 2), "ma50": round(ma50_i, 2),
            "ma200": round(ma200_i, 2),
            "etf": current_etf or "CASH", "cash": round(float(cash), 2),
        })

    # 统计
    final_eq  = equity_curve[-1]["equity"]
    total_ret = (final_eq - initial) / initial * 100
    years     = len(dates) / 252
    cagr      = ((final_eq/initial)**(1/max(years, 0.01)) - 1) * 100
    spy_bh    = (spy_closes[-1]/spy_closes[0]-1)*100
    dd_peak = initial; max_dd = 0.0
    for e in equity_curve:
        dd_peak = max(dd_peak, e["equity"])
        max_dd = max(max_dd, (dd_peak-e["equity"])/dd_peak*100)
    return {
        "name":           name,
        "final_equity":   round(final_eq, 2),
        "total_return":   round(total_ret, 2),
        "cagr":          round(cagr, 2),
        "max_drawdown":  round(max_dd, 2),
        "num_trades":    len([t for t in trades if t["action"] in ("BUY","SELL")]),
        "buy_hold_return": round(spy_bh, 2),
        "outperformance": round(total_ret - spy_bh, 2),
        "trades":        trades,
        "equity_curve":   equity_curve,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 策略定义
# ─────────────────────────────────────────────────────────────────────────────
def strat_spy_hold(i, ctx): return {"etf": "SPY", "ratio": 1.0}
def strat_sso_hold(i, ctx): return {"etf": "SSO", "ratio": 1.0}

def strat_sso_ma20(i, ctx):
    """SSO + MA20均线（跌破MA20→现金，冷静期20天）"""
    spy = ctx["spy_close"]; ma20 = ctx["ma20"]
    if ctx["in_pos"]:
        # 持有中：跌破MA20→清仓
        if spy < ma20 * 0.97:
            return {"etf": "CASH", "ratio": 0.0}
    else:
        # 空仓中：重新突破MA20且在200日均线上方
        if spy > ma20 * 1.01 and ctx["spy_close"] > ctx["ma200"]:
            return {"etf": "SSO", "ratio": 1.0}
    return {"etf": ctx.get("prev_etf","CASH"), "ratio": 1.0}

def strat_sso_ma50(i, ctx):
    """SSO + MA50均线（更稳健，跌破MA50→现金）"""
    spy = ctx["spy_close"]; ma50 = ctx["ma50"]
    if ctx["in_pos"]:
        if spy < ma50 * 0.97:
            return {"etf": "CASH", "ratio": 0.0}
    else:
        if spy > ma50 * 1.01 and ctx["spy_close"] > ctx["ma200"]:
            return {"etf": "SSO", "ratio": 1.0}
    return {"etf": ctx.get("prev_etf","CASH"), "ratio": 1.0}

def strat_spy_ma200(i, ctx):
    """SPY在200日均线上方→SSO，下方→SPY，再下方→现金"""
    spy = ctx["spy_close"]; ma50 = ctx["ma50"]; ma200 = ctx["ma200"]
    if spy > ma200:
        return {"etf": "SSO", "ratio": 1.0}
    elif spy > ma50:
        return {"etf": "SPY", "ratio": 1.0}
    else:
        return {"etf": "CASH", "ratio": 0.0}

def strat_sso_ma200_only(i, ctx):
    """只用200日均线：上方SSO，下方现金"""
    if ctx["spy_close"] > ctx["ma200"]:
        return {"etf": "SSO", "ratio": 1.0}
    return {"etf": "CASH", "ratio": 0.0}


# ─────────────────────────────────────────────────────────────────────────────
# 主程序
# ─────────────────────────────────────────────────────────────────────────────
print("="*65)
print("Regime-Driven SSO/SPY/Cash — Final Optimized Backtest")
print("="*65)

spy_bars = load_bars(PROJ / "TradingAgents/中间过程/klines/SPY_1d.json")
vix_bars = load_bars(PROJ / "TradingAgents/中间过程/klines/VIX_1d.json")

dates  = [b["date"] for b in spy_bars]
closes = np.array([b["close"] for b in spy_bars], dtype=float)
sso    = simulate_sso(closes)

spy_bh_ret = (closes[-1]/closes[0]-1)*100
sso_sim_ret = (sso[-1]/sso[0]-1)*100
print(f"\n[{len(dates)} days: {dates[0]} → {dates[-1]}]")
print(f"SPY buy-hold:  {spy_bh_ret:+7.2f}%")
print(f"SSO simulated: {sso_sim_ret:+7.2f}%  (SSO/SPY = {sso[-1]/closes[-1]:.3f}x)")

strategies = [
    ("S0 SPY Buy-Hold",      strat_spy_hold,      0.0, 0.0, 0),
    ("S1 SSO Buy-Hold",      strat_sso_hold,      0.0, 0.0, 0),
    ("S2 SSO+MA20",          strat_sso_ma20,      0.0, 0.0, 20),
    ("S3 SSO+MA50",          strat_sso_ma50,      0.0, 0.0, 20),
    ("S4 SPY/SSO/Cash(MA)", strat_spy_ma200,     0.0, 0.0, 0),
    ("S5 SSO Only MA200",    strat_sso_ma200_only, 0.0, 0.0, 10),
]

print("\n" + "="*65)
print("Results  (2020-01 → 2026-05, Initial ¥1,000,000)")
print("="*65)
print(f"{'Strategy':22s}  {'Return':8s}  {'CAGR':7s}  {'MaxDD':7s}  {'Trades':7s}  {'vsBH':8s}")
print("-"*70)

results = {}
for name, fn, trail, stop, cool in strategies:
    r = run_backtest(name, dates, closes, sso, fn,
                    initial=INITIAL,
                    trail_pct=trail, stop_pct=stop, cool_days=cool)
    results[name] = r
    print(f"{name:22s}  {r['total_return']:+7.2f}%  {r['cagr']:+6.2f}%  "
          f"{r['max_drawdown']:6.2f}%  {r['num_trades']:5d}  "
          f"{r['outperformance']:+7.2f}%")

# 保存
eq_csv = OUT / "all_strategies_equity.csv"
all_eq = {}
for name, r in results.items():
    for e in r["equity_curve"]:
        all_eq.setdefault(e["date"], {})[name] = e["equity"]
eq_dates = sorted(all_eq.keys())
with open(eq_csv, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["date"] + list(results.keys()))
    w.writeheader()
    for d in eq_dates:
        row = {"date": d}
        row.update({name: round(all_eq[d].get(name, 0), 2) for name in results})
        w.writerow(row)
print(f"\nSaved: {eq_csv}")

# 打印关键切换
print("\nKey switches for S2 (SSO+MA20):")
for t in results["S2 SSO+MA20"]["trades"][:15]:
    if t["action"] in ("BUY","SELL"):
        print(f"  {t['date']}  {t['action']:4s}  {t['etf']:4s}  "
              f"@{t['price']:8.2f}  cash={t['cash_after']:,.0f}")

# JSON
out_json = OUT / "sso_regime_results.json"
with open(out_json, "w") as f:
    json.dump({name: {k: v for k, v in r.items() if k not in ("equity_curve","trades")}
              for name, r in results.items()}, f, indent=2, ensure_ascii=False)
print(f"Saved: {out_json}")

print("\nDone!")
