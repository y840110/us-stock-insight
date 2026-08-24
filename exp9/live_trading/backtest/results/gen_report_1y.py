#!/usr/bin/env python3
"""生成小时级回测 HTML 报告"""
import json
from collections import defaultdict

RESULT = '/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/live_trading/backtest/results/results_h3_4_1_1y_full.json'
OUT_HTML = '/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/live_trading/backtest/results/h341_backtest_1y_report.html'

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
    def fmt_leg(leg):
        if not leg:
            return '-'
        return f"{leg['exit_date'][:10]} ${leg['exit_price']:.2f}<br><small>{leg['pnl_pct']:+.1f}% {leg['exit_rule']}</small>"
    rows.append({
        'ticker': g['ticker'], 'grade': g.get('grade', '?'),
        'entry_date': g['entry_date'], 'entry_price': g['entry_price'],
        'avg_pnl': avg_pnl,
        'lot1': fmt_leg(l1), 'lot2': fmt_leg(l2),
    })

rows_sorted = sorted(rows, key=lambda r: -r['avg_pnl'])
wins = sum(1 for r in rows if r['avg_pnl'] > 0)
losses = len(rows) - wins

body_rows = []
for i, r in enumerate(rows_sorted, 1):
    color = '#d4edda' if r['avg_pnl'] > 0 else '#f8d7da'
    pnl_color = '#155724' if r['avg_pnl'] > 0 else '#721c24'
    body_rows.append(f"""
    <tr style="background:{color}">
      <td>{i}</td><td><b>{r['ticker']}</b></td><td>{r['grade']}</td>
      <td>{r['entry_date']}</td><td>${r['entry_price']:.2f}</td>
      <td>{r['lot1']}</td><td>{r['lot2']}</td>
      <td style="color:{pnl_color};font-weight:bold">{r['avg_pnl']:+.1f}%</td>
    </tr>""")

html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>小时级策略 h3-4-1 回测报告</title>
<style>
body{{font-family:-apple-system,'PingFang SC',sans-serif;margin:24px;color:#222}}
h1{{font-size:22px}} h2{{font-size:18px;margin-top:28px}}
.stats{{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0}}
.card{{border:1px solid #e0e0e0;border-radius:8px;padding:14px 18px;min-width:140px}}
.card b{{font-size:20px;display:block}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid #ddd;padding:6px 8px;text-align:left}}
th{{background:#f0f0f0;position:sticky;top:0}}
small{{color:#888}}
</style></head><body>
<h1>小时级策略 h3-4-1 回测报告（全市场）</h1>
<p>回测区间：<b>2025-06-03 ~ 2026-08-21</b>（约 14.5 个月，数据上限）｜ 初始资金 $100,000 ｜ 最大持仓 5 只</p>
<div class="stats">
  <div class="card">期末权益<b>${d['final_cash']:,.2f}</b></div>
  <div class="card">收益率<b style="color:green">+{d['return_pct']:.1f}%</b></div>
  <div class="card">胜率<b>{d['win_rate']:.1f}%</b></div>
  <div class="card">盈亏比 RR<b>{d['win_loss_ratio']:.2f}</b></div>
  <div class="card">最大回撤<b>-{d['max_drawdown']:.1f}%</b></div>
  <div class="card">总买入<b>{d['total']}</b></div>
</div>
<p>平均盈利 <b>+{d['avg_win']:.2f}%</b> ｜ 平均亏损 <b>{d['avg_loss']:.2f}%</b> ｜ 盈利 {wins} 笔 / 亏损 {losses} 笔</p>
<h2>每笔买卖明细（按综合盈亏降序，Lot1/Lot2 为两段出场）</h2>
<table>
<thead><tr><th>#</th><th>股票</th><th>评级</th><th>买入日</th><th>买入价</th><th>Lot1 出场</th><th>Lot2 出场</th><th>综合盈亏</th></tr></thead>
<tbody>{''.join(body_rows)}</tbody>
</table>
</body></html>"""

open(OUT_HTML, 'w').write(html)
print(f'HTML 报告已生成: {OUT_HTML}')
