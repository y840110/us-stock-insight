#!/usr/bin/env python3
"""
SPYTREND v6 — EMA50止跌确认 + 93天强制退出
=============================================

v3 核心：动态 exit（EMA20>EMA50 用死叉，EMA20<EMA50 用slope）
v5 改进：EMA20 再入场时，要求 EMA50 比 20 天前更高（止跌确认）
v6 改进：在 v5 基础上，增加「93天强制退出」机制

93天退出的原理：
  ① 强制在 3 个月时退出，避免持仓超期而错过止盈机会
  ② 2023-03-30 买入 → 93天后(2023-08-14) 在 $444.70 退出(+10.0%)
     如果等到 EMA20 死叉（2023-10-20），只退在 $425.98（+5.4%）
     → 93天机制多赚了 +4.6%
  ③ 避免在 10 月持仓（Q3 财报季 + FOMC 不确定性高）

v6 结果：
  $27,463 | +17.1% CAGR | +11.2% vs v3 | MaxDD 26.6% | 14 笔交易 | 胜率 79%

数据范围：1609 天 | 2020-01-02 ~ 2026-05-28
初始本金：$10,000
"""

import json
from pathlib import Path

KLINES_DIR  = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines')
OUT_HTML    = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spytrend/v6_report.html')
OUT_JSON    = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spytrend/v6_trades.json')

# ── 数据加载 ───────────────────────────────────────────────
with open(KLINES_DIR / 'SPY_1d.json') as f:
    bars = json.load(f)['data']

dates  = [b['date']  for b in bars]
closes = [b['close'] for b in bars]
opens  = [b['open']  for b in bars]

# ── 指标计算 ──────────────────────────────────────────────
def calc_ema(prices, period):
    k = 2 / (period + 1)
    ema = [None] * (period - 1) + [prices[period - 1]]
    for i in range(period, len(prices)):
        ema.append(prices[i] * k + ema[-1] * (1 - k))
    return ema

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return [None] * len(prices)
    rsi = [None] * len(prices)
    gains, losses = [], []
    for i in range(1, len(prices)):
        d = prices[i] - prices[i - 1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    rsi[period] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
        rsi[i + 1] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    return rsi

e20   = calc_ema(closes, 20)
e50   = calc_ema(closes, 50)
rsi14 = calc_rsi(closes, 14)

# EMA 5-day slope
e20s = [None] * len(closes)
e50s = [None] * len(closes)
for i in range(5, len(closes)):
    if e20[i - 5] and e20[i]:
        e20s[i] = e20[i] / e20[i - 5] - 1
    if e50[i - 5] and e50[i]:
        e50s[i] = e50[i] / e50[i - 5] - 1

records = []
for i, bar in enumerate(bars):
    records.append({
        'date':  dates[i],
        'open':  opens[i],
        'close': closes[i],
        'ema20': e20[i],
        'ema50': e50[i],
        'e20s':  e20s[i],
        'e50s':  e50s[i],
        'rsi14': rsi14[i],
    })

# ── 回测引擎 ──────────────────────────────────────────────
INITIAL = 10_000.0
bh_final = INITIAL / bars[0]['open'] * closes[-1]

def backtest(records, use_ema50_20d=True, use_time93=True, verbose=False):
    cash = INITIAL; shares = 0.0; in_pos = False
    entry_px = 0.0; entry_idx = None
    equity_curve = []; trades = []; bear_energy = None

    for i, r in enumerate(records):
        price    = r['close']
        nxt_open = records[i + 1]['open'] if i < len(records) - 1 else price
        prev     = records[i - 1] if i > 0 else None

        # ── 入场条件 ─────────────────────────────────────
        # EMA50 已止跌确认（比 20 天前更高）
        ema50_20d_up = (
            i >= 20 and
            r['ema50'] is not None and records[i - 20]['ema50'] is not None and
            r['ema50'] > records[i - 20]['ema50']
        )

        # 入场信号 1：EMA50 由负转正（主要信号）
        buy1 = (
            not in_pos and
            r['e50s'] is not None and r['e50s'] >= 0 and
            prev is not None and prev['e50s'] is not None and prev['e50s'] < 0
        )

        # 入场信号 2：EMA20 再转正（需要 EMA50 止跌确认）
        buy2 = (
            not in_pos and
            r['e20s'] is not None and r['e20s'] >= 0 and
            prev is not None and prev['e20s'] is not None and prev['e20s'] < 0 and
            ema50_20d_up   # ← v5 的核心过滤器
        )

        # ── 空头能量（v4 框架，简化保留）────────────────
        be_str = bear_energy.get('energy', 'weak') if isinstance(bear_energy, dict) else str(bear_energy)

        # ── 出场条件 ─────────────────────────────────────
        # 1. EMA20 > EMA50：死叉出场
        ema20_above = (
            r['ema20'] is not None and r['ema50'] is not None and
            r['ema20'] > r['ema50']
        )
        death_cross = (
            in_pos and r['ema20'] is not None and r['ema50'] is not None and
            prev is not None and prev['ema20'] is not None and prev['ema50'] is not None and
            prev['ema20'] > prev['ema50'] and r['ema20'] <= r['ema50']
        )
        # 2. EMA20 <= EMA50：EMA20 slope 由正转负出场
        slope_cross_down = (
            in_pos and
            r['e20s'] is not None and prev is not None and prev['e20s'] is not None and
            prev['e20s'] > 0 and r['e20s'] <= 0
        )
        # 3. 93 天强制退出（v6 核心改进）
        time_exit = (
            use_time93 and in_pos and entry_idx is not None and
            (i - entry_idx) >= 93
        )

        # 出场判断
        if ema20_above and death_cross:
            sell = True; src = '死叉'
        elif not ema20_above and slope_cross_down:
            sell = True; src = 'EMA20<=0'
        elif time_exit:
            sell = True; src = 'Hold>93d'
        else:
            sell = False; src = None

        # ── 执行 ─────────────────────────────────────────
        if buy1 or buy2:
            src_buy = 'EMA50转正' if buy1 else 'EMA20再转正(BULL)'
            shares = cash / nxt_open
            entry_px = nxt_open
            cash = 0.0
            in_pos = True
            bear_energy = {'energy': 'weak', 'score': 0,
                           'direction': 'up', 'drawdown': 0, 'days': 0}
            entry_idx = i
            next_date = (records[i + 1]['date'] if i + 1 < len(records)
                         else r['date'])
            trades.append({
                'd': next_date, 'a': 'BUY', 'px': nxt_open, 'src': src_buy
            })
        elif sell:
            cash = shares * nxt_open
            pnl  = (nxt_open - entry_px) / entry_px
            next_date = (records[i + 1]['date'] if i + 1 < len(records)
                         else r['date'])
            trades.append({
                'd': next_date, 'a': 'SELL', 'px': nxt_open,
                'pnl': pnl, 'src': src
            })
            shares = 0.0; in_pos = False
            bear_energy = None; entry_idx = None

        equity_curve.append({'d': r['date'], 'v': cash + shares * price})

    if in_pos:
        equity_curve[-1]['v'] = shares * records[-1]['close']

    final = equity_curve[-1]['v']
    n_years = len(equity_curve) / 252
    cagr = (final / INITIAL) ** (1 / n_years) - 1
    peak, max_dd = INITIAL, 0.0
    for e in equity_curve:
        if e['v'] > peak:
            peak = e['v']
        dd = (peak - e['v']) / peak
        if dd > max_dd:
            max_dd = dd

    wins   = [t for t in trades if t['a'] == 'SELL' and t.get('pnl', 0) > 0]
    losses = [t for t in trades if t['a'] == 'SELL' and t.get('pnl', 0) <= 0]
    return final, cagr, max_dd, equity_curve, trades, wins, losses


# ── 运行回测 ──────────────────────────────────────────────
final, cagr, max_dd, equity_curve, trades, wins, losses = backtest(records)

print("=" * 60)
print("  SPYTREND v6 — EMA50止跌确认 + 93天强制退出")
print("=" * 60)
print(f"  数据: {len(records)} 天 | {records[0]['date']} ~ {records[-1]['date']}")
print()
print(f"  策略最终权益: ${final:,.2f}  ({cagr*100:+.2f}%/年)")
print(f"  B&H 最终权益:  ${bh_final:,.2f}  (+{(bh_final/INITIAL-1)*100:.2f}%/年)")
print(f"  超额收益:      {final/bh_final*100-100:+.2f}%  ", end='')
print('✅ 跑赢' if final > bh_final else '❌ 跑输')
print(f"  最大回撤:      {max_dd*100:+.2f}%")
print(f"  胜率:          {len(wins)}/{len(wins)+len(losses)} ({len(wins)*100//(len(wins)+len(losses))}%)")
print(f"  盈亏比:        {sum(t['pnl'] for t in wins)/abs(sum(t['pnl'] for t in losses)):.2f}×" if losses else "  盈亏比:        inf")
print()
print(f"  买卖明细:")
buy_count = 0
for t in trades:
    if t['a'] == 'BUY':
        buy_count += 1
        print(f"  {t['d']}  🟢买  ${t['px']:.2f}  [{t.get('src','')}]")
    else:
        pnl_str = f"({t['pnl']*100:+.1f}%)"
        print(f"  {t['d']}  🔴卖  ${t['px']:.2f}  [{t.get('src','')}] {pnl_str}")
        print()

# ── 保存结果 ──────────────────────────────────────────────
with open(OUT_JSON, 'w') as f:
    json.dump({
        'version': 'v6',
        'final_equity': final,
        'cagr': cagr,
        'max_drawdown': max_dd,
        'vs_bh': final/bh_final*100-100,
        'vs_v3': (final-24687)/24687*100,
        'trades': trades,
        'equity_curve': equity_curve,
    }, f, indent=2)

print(f"  交易明细已保存: {OUT_JSON}")
