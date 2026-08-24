#!/usr/bin/env python3
"""
SPYTREND v6 — 最近一年回测（EMA50止跌确认 + 93天强制退出）
=============================================================

规则完全复用 v6_backtest.py：
  - 入场1：EMA50 slope 由负转正
  - 入场2：EMA20 slope 由负转正 + EMA50 止跌确认（比20天前更高）
  - 出场1：EMA20>EMA50 时死叉
  - 出场2：EMA20<=EMA50 时 EMA20 slope 由正转负
  - 出场3：93 天强制退出
仅回测区间切分为最近一年（START_DATE 起）。
指标在完整数据上计算，保证 EMA 预热正确。
"""

import json
from pathlib import Path

KLINES_DIR = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines')
START_DATE = '2025-08-21'   # 回测起始（最近一年）
OUT_JSON   = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spytrend/v6_1y_trades.json')

with open(KLINES_DIR / 'SPY_1d.json') as f:
    bars = json.load(f)['data']

dates  = [b['date']  for b in bars]
closes = [b['close'] for b in bars]
opens  = [b['open']  for b in bars]


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

# 切片：最近一年
records_1y = [r for r in records if r['date'] >= START_DATE]

INITIAL = 10_000.0
start_open = records_1y[0]['open']
bh_final = INITIAL / start_open * records_1y[-1]['close']


def backtest(records, use_ema50_20d=True, use_time93=True):
    cash = INITIAL; shares = 0.0; in_pos = False
    entry_px = 0.0; entry_idx = None
    equity_curve = []; trades = []

    for i, r in enumerate(records):
        price    = r['close']
        nxt_open = records[i + 1]['open'] if i < len(records) - 1 else price
        prev     = records[i - 1] if i > 0 else None

        ema50_20d_up = (
            i >= 20 and
            r['ema50'] is not None and records[i - 20]['ema50'] is not None and
            r['ema50'] > records[i - 20]['ema50']
        )

        buy1 = (
            not in_pos and
            r['e50s'] is not None and r['e50s'] >= 0 and
            prev is not None and prev['e50s'] is not None and prev['e50s'] < 0
        )

        buy2 = (
            not in_pos and
            r['e20s'] is not None and r['e20s'] >= 0 and
            prev is not None and prev['e20s'] is not None and prev['e20s'] < 0 and
            ema50_20d_up
        )

        ema20_above = (
            r['ema20'] is not None and r['ema50'] is not None and
            r['ema20'] > r['ema50']
        )
        death_cross = (
            in_pos and r['ema20'] is not None and r['ema50'] is not None and
            prev is not None and prev['ema20'] is not None and prev['ema50'] is not None and
            prev['ema20'] > prev['ema50'] and r['ema20'] <= r['ema50']
        )
        slope_cross_down = (
            in_pos and
            r['e20s'] is not None and prev is not None and prev['e20s'] is not None and
            prev['e20s'] > 0 and r['e20s'] <= 0
        )
        time_exit = (
            use_time93 and in_pos and entry_idx is not None and
            (i - entry_idx) >= 93
        )

        if ema20_above and death_cross:
            sell = True; src = '死叉'
        elif not ema20_above and slope_cross_down:
            sell = True; src = 'EMA20<=0'
        elif time_exit:
            sell = True; src = 'Hold>93d'
        else:
            sell = False; src = None

        if buy1 or buy2:
            src_buy = 'EMA50转正' if buy1 else 'EMA20再转正(BULL)'
            shares = cash / nxt_open
            entry_px = nxt_open
            cash = 0.0
            in_pos = True
            entry_idx = i
            next_date = (records[i + 1]['date'] if i + 1 < len(records)
                         else r['date'])
            trades.append({'d': next_date, 'a': 'BUY', 'px': nxt_open, 'src': src_buy})
        elif sell:
            cash = shares * nxt_open
            pnl  = (nxt_open - entry_px) / entry_px
            next_date = (records[i + 1]['date'] if i + 1 < len(records)
                         else r['date'])
            trades.append({'d': next_date, 'a': 'SELL', 'px': nxt_open, 'pnl': pnl, 'src': src})
            shares = 0.0; in_pos = False
            entry_idx = None

        equity_curve.append({'d': r['date'], 'v': cash + shares * price})

    if in_pos:
        equity_curve[-1]['v'] = shares * records[-1]['close']

    final = equity_curve[-1]['v']
    n_years = len(equity_curve) / 252
    cagr = (final / INITIAL) ** (1 / n_years) - 1 if final > 0 else 0.0
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


final, cagr, max_dd, equity_curve, trades, wins, losses = backtest(records_1y)

print("=" * 62)
print("  SPYTREND v6 — 最近一年回测（EMA50止跌确认 + 93天退出）")
print("=" * 62)
print(f"  数据: {len(records_1y)} 个交易日 | {records_1y[0]['date']} ~ {records_1y[-1]['date']}")
print()
print(f"  初始本金:      ${INITIAL:,.0f}")
print(f"  策略最终权益:  ${final:,.2f}  ({cagr*100:+.2f}%/年)")
print(f"  B&H 最终权益:  ${bh_final:,.2f}  (+{(bh_final/INITIAL-1)*100:.2f}%/年)")
print(f"  超额收益:      {final/bh_final*100-100:+.2f}%  ", end='')
print('✅ 跑赢' if final > bh_final else '❌ 跑输')
print(f"  最大回撤:      {max_dd*100:+.2f}%")
print(f"  胜率:          {len(wins)}/{len(wins)+len(losses)} ({len(wins)*100//(len(wins)+len(losses))}%)")
print(f"  盈亏比:        {sum(t['pnl'] for t in wins)/abs(sum(t['pnl'] for t in losses)):.2f}×" if losses else "  盈亏比:        inf")
print()
print(f"  买卖明细（共 {len(trades)} 笔）:")
print("  " + "-" * 56)
n = 0
for t in trades:
    if t['a'] == 'BUY':
        n += 1
        print(f"  #{n:<2} {t['d']}  🟢买入  ${t['px']:>8.2f}  [{t.get('src','')}]")
    else:
        pnl_str = f"({t['pnl']*100:+.1f}%)"
        print(f"      {t['d']}  🔴卖出  ${t['px']:>8.2f}  [{t.get('src','')}] {pnl_str}")
        print()
print("  " + "-" * 56)

# 未平仓提示
open_trade = [t for t in trades if t['a'] == 'BUY']
if open_trade and (not trades or trades[-1]['a'] == 'BUY'):
    print(f"  ⚠️ 当前仍有持仓（未平仓）：{open_trade[-1]['d']} 买入 ${open_trade[-1]['px']:.2f}，按最新收盘价计入权益")

with open(OUT_JSON, 'w') as f:
    json.dump({
        'version': 'v6_1y',
        'start_date': START_DATE,
        'end_date': records_1y[-1]['date'],
        'final_equity': final,
        'cagr': cagr,
        'max_drawdown': max_dd,
        'vs_bh': final/bh_final*100-100,
        'trades': trades,
    }, f, indent=2)

print(f"\n  明细已保存: {OUT_JSON}")
