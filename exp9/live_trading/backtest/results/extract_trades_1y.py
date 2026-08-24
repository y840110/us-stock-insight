#!/usr/bin/env python3
"""提取小时级回测明细，生成清晰的每笔买卖清单"""
import json
from collections import defaultdict

RESULT = '/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/live_trading/backtest/results/results_h3_4_1_1y_full.json'
OUT_MD  = '/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/live_trading/backtest/results/trades_detail_1y.md'

d = json.load(open(RESULT))
trades = d['trades']

groups = defaultdict(dict)
for t in trades:
    tid = t.get('_trade_id', t.get('trade_id'))
    g = groups[tid]
    if t.get('leg') == 'lot1_sell':
        g['lot1'] = t
    else:
        g['lot2'] = t
    for k in ('ticker', 'entry_date', 'entry_price', 'grade'):
        if t.get(k) is not None:
            g.setdefault(k, t.get(k))

rows = []
for tid in sorted(groups):
    g = groups[tid]
    l1, l2 = g.get('lot1'), g.get('lot2')
    pnls = [t['pnl_pct'] for t in (l1, l2) if t and t.get('pnl_pct') is not None]
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0
    sell_parts = []
    if l1:
        sell_parts.append(f"{l1['exit_date'][:10]} ${l1['exit_price']:.2f} ({l1['pnl_pct']:+.1f}%, {l1['exit_rule']})")
    if l2:
        sell_parts.append(f"{l2['exit_date'][:10]} ${l2['exit_price']:.2f} ({l2['pnl_pct']:+.1f}%, {l2['exit_rule']})")
    rows.append({
        'tid': tid, 'ticker': g['ticker'], 'grade': g.get('grade', '?'),
        'entry_date': g['entry_date'], 'entry_price': g['entry_price'],
        'avg_pnl': avg_pnl, 'sell': ' | '.join(sell_parts),
    })

rows_sorted = sorted(rows, key=lambda r: -r['avg_pnl'])

lines = []
lines.append('# 小时级策略 h3-4-1 回测明细（全市场）\n')
lines.append(f'- 回测区间：2025-06-03 ~ 2026-08-21（约 14.5 个月，数据上限）')
lines.append(f'- 总买入：{len(rows)} 笔 | 盈利：{sum(1 for r in rows if r["avg_pnl"] > 0)} | 亏损：{sum(1 for r in rows if r["avg_pnl"] <= 0)}\n')
lines.append('## 每笔买卖明细（按盈亏降序）\n')
lines.append('| # | 股票 | 评级 | 买入日 | 买入价 | 卖出明细(Lot1 \u2016 Lot2) | 综合盈亏 |')
lines.append('|---|------|------|--------|--------|--------------------------|----------|')
for i, r in enumerate(rows_sorted, 1):
    flag = '🟢' if r['avg_pnl'] > 0 else '🔴'
    lines.append(f"| {i} | {r['ticker']} | {r['grade']} | {r['entry_date']} | ${r['entry_price']:.2f} | {r['sell']} | {flag} {r['avg_pnl']:+.1f}% |")

open(OUT_MD, 'w').write('\n'.join(lines))
print(f'明细已保存: {OUT_MD}')

# 打印摘要
print('\n=== TOP 20 盈利 ===')
for r in rows_sorted[:20]:
    print(f"{r['ticker']:<7} {r['grade']} {r['entry_date']} ${r['entry_price']:.2f} -> {r['avg_pnl']:+.1f}%")
print('\n=== 最差 20 亏损 ===')
for r in rows_sorted[-20:]:
    print(f"{r['ticker']:<7} {r['grade']} {r['entry_date']} ${r['entry_price']:.2f} -> {r['avg_pnl']:+.1f}%")
print(f'\n总笔数: {len(rows)} | 盈利: {sum(1 for r in rows if r["avg_pnl"]>0)} | 亏损: {sum(1 for r in rows if r["avg_pnl"]<=0)} | 胜率: {sum(1 for r in rows if r["avg_pnl"]>0)/len(rows)*100:.1f}%')
