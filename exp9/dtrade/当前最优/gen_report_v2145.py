#!/usr/bin/env python3
"""
生成 v2.1.43 完整交割单报告
ATR=3.25, rf=0.90, max_pos=5, cooldown=5, max_reentry=2
按日期顺序，逐条更新账户余额
"""

import sys, json, argparse
from pathlib import Path
from collections import defaultdict
import time as _time

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'model' / 'experts'))
from engine_base import BaseBacktester, load_klines, _atr
from p_buy_filter_v2 import BuyFilterEngine
from engine_v2145_no_wsban import BranchAVariant


class V2143Engine(BranchAVariant):
    ATR_TRAIL_MULT = 3.25
    MIN_HOLD_DAYS = 5
    RISK_FRAC = 0.90
    MAX_POS = 5
    REENTRY_COOLDOWN = 5
    MAX_REENTRY = 2

    def __init__(self):
        # Explicitly pass correct params to match class attributes
        BranchAVariant.__init__(self, atr=3.25, cooldown=5, max_re=2, rf=0.90, max_pos=5)

    def _setup(self):
        self._ticker_exit_info = {}
        self._ticker_reentry_count = defaultdict(int)

    def _get_entry_signal(self, ticker, bars_d, idx, spy, spy_idx, eng, sig,
                          stage, action, grade, l3, l5, rr):
        if ticker in self._ticker_exit_info:
            inf = self._ticker_exit_info[ticker]
            if inf['cooldown'] > 0 or inf['reentry_count'] >= self.MAX_REENTRY:
                return None
        if stage == 'STAGE_4' and action == 'NOW':
            return 'STAGE4'
        if stage in ('STAGE_3', 'STAGE_1') and action in ('NOW', 'WATCH'):
            if self._is_bullish_engulfing(bars_d, idx):
                return 'ENGULFING'
        return None

    def run(self, tickers, start_year=2020, end_year=2026):
        t0 = _time.time()
        all_bars = {}
        for t in tickers:
            bars = load_klines(t, lookback=0)
            if bars:
                all_bars[t] = bars
        if 'SPY' not in all_bars:
            return {}
        spy = all_bars['SPY']

        def in_year(b, y0, y1):
            return str(y0) <= b["date"][:4] <= str(y1)
        sidx = next((i for i, b in enumerate(spy) if in_year(b, start_year, end_year)), None)
        eidx = next((i for i in range(len(spy)-1, -1, -1) if in_year(spy[i], start_year, end_year)), None)
        total = eidx - sidx + 1

        # SPY EMA 预计算
        se200 = {}; se50 = {}
        for i in range(len(spy)):
            c = float(spy[i]['close'])
            if i >= 200:
                cs = [float(spy[i-200+j]['close']) for j in range(200)]
                a = 2/201; e = cs[0]
                for v in cs[1:]: e = a * v + (1-a) * e
                se200[i] = e
            else:
                se200[i] = None
            if i >= 50:
                cs = [float(spy[i-50+j]['close']) for j in range(50)]
                a = 2/51; e = cs[0]
                for v in cs[1:]: e = a * v + (1-a) * e
                se50[i] = e
            else:
                se50[i] = None

        # 主循环
        for idx in range(sidx, eidx + 1):
            sc = float(spy[idx]['close'])
            s200 = se200.get(idx); s50 = se50.get(idx)
            bull = s200 and sc > s200 and s50 and sc > s50
            bear = s200 and sc < s200

            # cooldown 更新
            for t in list(self._ticker_exit_info):
                self._ticker_exit_info[t]['cooldown'] -= 1
                if self._ticker_exit_info[t]['cooldown'] <= 0:
                    del self._ticker_exit_info[t]

            # 持仓更新
            for t, pos in list(self.positions.items()):
                bd = all_bars.get(t, [])
                pos['current_close'] = float(bd[idx]['close']) if idx < len(bd) else pos['entry_price']

            closed = set()
            # 出场检查
            for ticker in list(self.positions):
                bd = all_bars.get(ticker, [])
                if idx >= len(bd):
                    continue
                bar = bd[idx]; pos = self.positions[ticker]
                hd = idx - pos['bars_at_entry']
                ch = float(bar['high']); cc = float(bar['close'])
                if ch > pos.get('atr_peak', pos['entry_price']):
                    pos['atr_peak'] = ch
                atr = pos['atr']; peak = pos.get('atr_peak', pos['entry_price'])
                trail = peak - self.ATR_TRAIL_MULT * atr
                trig = False; ep = cc; er = ''; eru = ''

                if not trig and hd >= self.MIN_HOLD_DAYS:
                    if cc < trail:
                        trig = True; ep = min(trail, cc); er = f'ATR({trail:.2f})'; eru = 'ATR_TRAILING'
                    elif bear:
                        trig = True; er = 'SPY熊'; eru = 'SPY_BEAR_EXIT'
                    elif cc < pos['entry_price'] * 0.995:
                        trig = True; er = 'Breakeven'; eru = 'BREAKEVEN'
                elif not trig:
                    es2 = pos['entry_price'] - 3.0 * atr
                    if cc < es2:
                        trig = True; ep = min(es2, cc); er = f'宽止({es2:.2f})'; eru = 'WIDE_STOP'

                if trig:
                    pp = (ep - pos['entry_price']) / pos['entry_price'] * 100
                    self._record_tx(bar['date'], 'SELL', ticker, pos['shares'], ep, pos['trade_id'],
                                   eru, pos['shares'] * (ep - pos['entry_price']), pp, hd)
                    self._record_summary(ticker, pos, bar, ep, pp, 'EXIT', er, eru,
                                        self._post_exit_judge(bd, idx, pos['entry_price']), idx)
                    closed.add(ticker); del self.positions[ticker]
                    if eru == 'WIDE_STOP':
                        self._ticker_exit_info[ticker] = {'cooldown': 5, 'reentry_count': self.MAX_REENTRY}
                    else:
                        self._ticker_exit_info[ticker] = {
                            'cooldown': self.REENTRY_COOLDOWN,
                            'reentry_count': self._ticker_exit_info.get(ticker, {}).get('reentry_count', 0) + 1,
                        }

            for t in closed:
                if t in self.positions:
                    del self.positions[t]

            # 入场检查
            if bull and len(self.positions) < self.MAX_POS:
                for ticker in tickers:
                    if ticker in self.positions or ticker in closed:
                        continue
                    if ticker in self._ticker_exit_info:
                        inf = self._ticker_exit_info[ticker]
                        if inf['cooldown'] > 0 or inf['reentry_count'] >= self.MAX_REENTRY:
                            continue
                    bd = all_bars.get(ticker, [])
                    if idx >= len(bd) - 1:
                        continue

                    eng2 = BuyFilterEngine(ticker, bd[:idx+1], spy_bars=spy[:idx+1])
                    sig2 = eng2.run(bars_1h=None, daily_entry_price=None)
                    st = sig2.get('stage', 'STAGE_F')
                    si = sig2.get('stage_info', {})
                    ac = si.get('action', 'NO_ACTION')
                    gr = sig2.get('grade', '?')
                    l3 = sig2['layers'].get('L3', {})
                    l5 = sig2['layers'].get('L5', {})
                    rr = l5.get('details', {})

                    es = self._get_entry_signal(ticker, bd, idx, spy, idx, eng2, sig2, st, ac, gr, l3, l5, rr)
                    if es is None:
                        continue
                    if idx + 1 >= len(bd):
                        continue
                    ep2 = float(bd[idx + 1]['open'])
                    if ep2 <= 0:
                        continue
                    av = rr.get('atr', 0) or _atr(bd[:idx+1])
                    if av <= 0:
                        av = _atr(bd[:idx+1])
                    cp = self.cash * self.RISK_FRAC
                    sh = int(cp / ep2)
                    if sh <= 0:
                        continue
                    fn = {'BREAD_BUTTER': 'BB', 'TRENDLINE_SUPPORT': '趋势', 'PULLBACK_50': '50%回',
                          'NEAR_EMA20': 'NearEMA', 'TIBOW_LONG': 'TIBOW', 'BULL_FLAG': 'BullFlag'}
                    self.trade_id += 1
                    self._record_tx(bd[idx + 1]['date'], 'BUY', ticker, sh, ep2, self.trade_id)
                    self.positions[ticker] = {
                        'entry_date': bd[idx + 1]['date'], 'entry_price': ep2,
                        'stop_loss': ep2 - 1.5 * av, 'atr': av, 'atr_peak': ep2,
                        'stage': st, 'grade': gr, 'bars_at_entry': idx,
                        'capital_per_pos': cp, 'shares': sh, 'trade_id': self.trade_id,
                        'entry_reason': fn.get(l3.get('form_type', '?'), '?'),
                        'ticker': ticker, 'current_close': ep2, 'entry_signal': es,
                    }

            if idx % 200 == 0:
                pct = (idx - sidx) / total * 100
                print(f'  {spy[idx]["date"]} [{pct:.0f}%] {_time.time()-t0:.0f}s ${self.cash:,.0f} pos={len(self.positions)} tr={self.trade_id}')

        # 期末平仓
        for ticker in list(self.positions):
            bd = all_bars.get(ticker, [])
            if not bd:
                continue
            li = len(bd) - 1; bar = bd[li]; pos = self.positions[ticker]
            ep2 = float(bar['close']); pp = (ep2 - pos['entry_price']) / pos['entry_price'] * 100
            self._record_tx(bar['date'], 'SELL', ticker, pos['shares'], ep2, pos['trade_id'],
                           'END', pos['shares'] * (ep2 - pos['entry_price']), pp, li - pos['bars_at_entry'])
            self._record_summary(ticker, pos, bar, ep2, pp, 'END', '期末平仓', 'END',
                                self._post_exit_judge(bd, li, pos['entry_price']), li)
            del self.positions[ticker]
        print(f'完成: {_time.time()-t0:.1f}s')
        return self

    def print_summary(self):
        trades = [h for h in self.history if h.get('result') in ('EXIT', 'END')]
        wins = [t for t in trades if t['pnl_pct'] > 0]
        losses = [t for t in trades if t['pnl_pct'] <= 0]
        exit_stats = defaultdict(int)
        entry_stats = defaultdict(int)
        for t in trades:
            exit_stats[t['exit_rule']] += 1
            entry_stats[t.get('entry_signal', '?')] += 1

        final_equity = self.cash + sum(
            p['shares'] * p.get('current_close', p['entry_price'])
            for p in self.positions.values()
        )
        ann = (final_equity / self.INITIAL_CAPITAL) ** (1 / 6.4) - 1

        events = sorted([(t['exit_date'], t['pnl_pct'], t['capital_per_pos']) for t in trades])
        ec = self.INITIAL_CAPITAL; peak = ec; mdd = 0
        for d, pnl, cp in events:
            ec += cp * pnl / 100; peak = max(peak, ec)
            mdd = max(mdd, (peak - ec) / peak * 100 if peak > 0 else 0)

        print(f'\n========== v2.1.43 最终绩效 ==========')
        print(f'最终权益: ${final_equity:,.2f} ({final_equity/self.INITIAL_CAPITAL-1:+.0%})')
        print(f'年化收益: {ann:.1%}')
        print(f'最大回撤(MDD): {mdd:.1f}%')
        print(f'总入场交易: {len(trades)} 笔')
        print(f'胜率: {len(wins)/max(1,len(trades))*100:.1f}% ({len(wins)}胜 {len(losses)}负)')
        if wins:
            print(f'平均盈利: +{sum(t["pnl_pct"] for t in wins)/max(1,len(wins)):.2f}%')
        if losses:
            print(f'平均亏损: {sum(t["pnl_pct"] for t in losses)/max(1,len(losses)):.2f}%')
        print(f'\n出场方式:')
        for rule, cnt in sorted(exit_stats.items(), key=lambda x: -x[1]):
            print(f'  {rule}: {cnt}笔')
        print(f'\n入场信号:')
        for sig, cnt in sorted(entry_stats.items(), key=lambda x: -x[1]):
            print(f'  {sig}: {cnt}笔')

        return {
            'final_equity': final_equity,
            'ann': ann, 'mdd': mdd,
            'trades': len(trades),
            'wins': len(wins), 'losses': len(losses),
            'exit_stats': dict(exit_stats),
            'entry_stats': dict(entry_stats),
        }

    def generate_html_report(self, output_path):
        """生成按日期顺序的完整交割单 HTML 报告"""
        trades = [h for h in self.history if h.get('result') in ('EXIT', 'END')]
        wins = [t for t in trades if t['pnl_pct'] > 0]
        losses = [t for t in trades if t['pnl_pct'] <= 0]
        exit_stats = defaultdict(int)
        entry_stats = defaultdict(int)
        for t in trades:
            exit_stats[t['exit_rule']] += 1
            entry_stats[t.get('entry_signal', '?')] += 1

        final_equity = self.cash + sum(
            p['shares'] * p.get('current_close', p['entry_price'])
            for p in self.positions.values()
        )
        ann = (final_equity / self.INITIAL_CAPITAL) ** (1 / 6.4) - 1

        # 最大回撤（按时间序列逐笔计算）
        events = sorted([(t['exit_date'], t['pnl_pct'], t['capital_per_pos']) for t in trades])
        ec = self.INITIAL_CAPITAL; peak = ec; mdd = 0
        for d, pnl, cp in events:
            ec += cp * pnl / 100; peak = max(peak, ec)
            mdd = max(mdd, (peak - ec) / peak * 100 if peak > 0 else 0)

        # 年度统计
        yearly = defaultdict(lambda: {'count': 0, 'pnl_sum': 0, 'capital': 0, 'wins': 0, 'losses': 0})
        for t in trades:
            yr = t['exit_date'][:4]
            yearly[yr]['count'] += 1
            yearly[yr]['capital'] = t['capital_per_pos']
            yearly[yr]['pnl_sum'] += t['pnl_pct'] * t['capital_per_pos'] / 100
            if t['pnl_pct'] > 0:
                yearly[yr]['wins'] += 1
            else:
                yearly[yr]['losses'] += 1

        # ── 重建完整交易记录（每笔交易一行，入场→出场）─────────────────
        # 从 tx_log 提取每笔交易的入场记录，用 history 补充完整信息
        # 按入场时间严格排序
        trade_map = {}  # trade_id -> {entry_tx, exit_tx}
        for tx in self.tx_log:
            tid = tx['trade_id']
            if tx['action'] == 'BUY':
                trade_map.setdefault(tid, {})['entry_tx'] = tx
            elif tx['action'] == 'SELL':
                trade_map.setdefault(tid, {})['exit_tx'] = tx

        # 合并 history 中的摘要信息
        hist_map = {t['trade_id']: t for t in self.history if t.get('result') in ('EXIT', 'END')}

        # 构建完整交易列表，按入场日期排序
        complete_trades = []
        for tid, data in trade_map.items():
            if 'entry_tx' not in data or 'exit_tx' not in data:
                continue  # 跳过不完整的交易
            entry_tx = data['entry_tx']
            exit_tx = data['exit_tx']
            hist = hist_map.get(tid, {})
            complete_trades.append({
                'trade_id': tid,
                'entry_date': entry_tx['date'],
                'exit_date': exit_tx['date'],
                'ticker': entry_tx['ticker'],
                'shares': entry_tx['shares'],
                'entry_price': entry_tx['price'],
                'exit_price': exit_tx['price'],
                'entry_amount': entry_tx['amount'],
                'exit_amount': exit_tx['amount'],
                'balance': exit_tx['balance'],
                'pnl_dollar': exit_tx.get('pnl_dollar'),
                'pnl_pct': exit_tx.get('pnl_pct'),
                'hold_days': exit_tx.get('hold_days'),
                'exit_rule': exit_tx.get('exit_rule', ''),
                'stage': hist.get('stage', ''),
                'grade': hist.get('grade', ''),
                'atr': hist.get('atr', 0),
                'atr_peak': hist.get('atr_peak', 0),
                'atr_mult': abs(exit_tx['price'] - entry_tx['price']) / hist.get('atr', 1) if hist.get('atr', 0) > 0 else 0,
            })

        # 按入场时间严格排序
        complete_trades.sort(key=lambda x: x['entry_date'])

        # ── 构建时序交割单（所有行按日期排序）─────────────────────
        # BUY行 → SELL行 → PnL说明行，严格按日期+余额排序
        # 余额来源：tx_log['balance'] 是操作后的余额；买前余额需反推
        trade_map2 = {}  # trade_id -> entry info
        all_rows = []
        for tx in self.tx_log:
            tid = tx['trade_id']
            if tx['action'] == 'BUY':
                trade_map2[tid] = {
                    'entry_date': tx['date'],
                    'entry_price': tx['price'],
                    'shares': tx['shares'],
                }
                row = dict(tx)
                row['_type'] = 'BUY'
                # cash_before 是引擎记录的交易前真实现金
                row['_balance_before'] = tx['cash_before']
                all_rows.append(row)
            elif tx['action'] == 'SELL':
                entry_info = trade_map2.pop(tid, {})
                row = dict(tx)
                row['_type'] = 'SELL'
                row['_entry_date'] = entry_info.get('entry_date', '')
                row['_entry_price'] = entry_info.get('entry_price', 0)
                # cash_before 是引擎记录的交易前真实现金
                row['_balance_before'] = tx['cash_before']
                all_rows.append(row)
                # 附加 PnL 说明行（不参与余额排序，仅展示）
                pnl_row = {
                    'date': tx['date'],
                    '_type': 'PNL_INFO',
                    '_balance_before': tx['cash_before'],
                    '_ticker': tx['ticker'],
                    '_entry_date': entry_info.get('entry_date', ''),
                    '_entry_price': entry_info.get('entry_price', 0),
                    '_exit_date': tx['date'],
                    '_exit_price': tx['price'],
                    '_pnl_dollar': tx.get('pnl_dollar'),
                    '_pnl_pct': tx.get('pnl_pct'),
                    '_hold_days': tx.get('hold_days'),
                    '_exit_rule': tx.get('exit_rule', ''),
                    'shares': tx['shares'],
                }
                all_rows.append(pnl_row)

        # 不排序：tx_log 本身已经是 tx_id 顺序（引擎真实执行顺序）
        # 排序会破坏同日期内平仓→开仓的现金流转连续性

        # ── HTML 生成 ─────────────────────────────────────────
        rule_css = {
            'ATR_TRAILING': ('#00ff8820', '#00ff88'),
            'SPY_BEAR_EXIT': ('#ff446620', '#ff4466'),
            'BREAKEVEN': ('#8888820', '#888888'),
            'WIDE_STOP': ('#ff000020', '#ff4444'),
            'END': ('#00d4ff20', '#00d4ff'),
            'ATR_WIDE_TRAIL': ('#ff880020', '#ff8800'),
        }

        html = f'''<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8">
<title>v2.1.45 完整交割单 — ATR=3.25 + WIDE_STOP正常冷却 +710% · 余额前后对照</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'SF Mono','Fira Code',Monaco,'Courier New',monospace;font-size:13px;background:#0a0a0f;color:#d0d0d0;padding:20px}}
h1{{font-size:1.2em;color:#00d4ff;margin-bottom:4px}}
.sub{{color:#666;font-size:0.85em;margin-bottom:20px}}
.metrics{{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}}
.m{{background:#111118;border:1px solid #1e1e2e;border-radius:8px;padding:12px 20px}}
.m .v{{font-size:1.5em;font-weight:700;color:#00ff88}}
.m .l{{font-size:0.75em;color:#666;margin-top:2px}}
.section{{margin-bottom:28px}}
h2{{font-size:1em;color:#00d4ff;border-bottom:1px solid #1e1e2e;padding-bottom:6px;margin-bottom:10px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:#111118;text-align:left;padding:7px 10px;color:#666;font-weight:400;border-bottom:1px solid #1e1e2e}}
td{{padding:6px 10px;border-bottom:1px solid #0f0f18}}
tr:hover{{background:#0f0f16}}
.pos{{color:#00ff88}}.neg{{color:#ff4455}}.neu{{color:#888}}
.badge{{display:inline-block;padding:1px 5px;border-radius:3px;font-size:0.8em;margin-right:3px}}
.tx-header{{display:grid;grid:repeat(2,auto)/60px 90px 55px 65px 90px 110px 125px 110px;gap:0;padding:6px 10px;background:#0d0d14;border-bottom:2px solid #1e1e2e;font-size:11px;color:#555;position:sticky;top:0}}
.tx-row{{display:grid;grid:repeat(2,auto)/60px 90px 55px 65px 90px 110px 125px 110px;gap:0;padding:5px 10px;border-bottom:1px solid #0c0c14;font-size:12px}}
.tx-row:hover{{background:#0f0f18}}
.tx-row .id{{color:#444}}
.tx-row .date{{color:#888}}
.tx-row .action-buy{{color:#00ff88}}.tx-row .action-sell{{color:#ff4455}}
.tx-row .ticker{{color:#c0c0c0;font-weight:600}}
.tx-row .price{{color:#888}}
.tx-row .amount{{color:#888}}
.tx-row .balance{{color:#d0d0d0;font-weight:600}}
.tx-row .note{{font-size:11px}}
.tx-row .pnl-pos{{color:#00ff88;font-size:11px}}.tx-row .pnl-neg{{color:#ff4455;font-size:11px}}
.grid-cell{{padding:1px 3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
</style></head><body>
<h1>📊 v2.1.45 完整交割单 — WIDE_STOP正常冷却</h1>
<div class="sub">ATR=3.25 · WIDE_STOP cooldown=5天 · rf=0.90 · max_pos=5 · 初始资金 $100,000 · 2020-2026 · 最大回撤 24.6% · 余额=买/卖前余额</div>

<div class="metrics">
<div class="m"><div class="v">${final_equity:,.2f}</div><div class="l">最终权益</div></div>
<div class="m"><div class="v">+{((final_equity/self.INITIAL_CAPITAL)-1)*100:.0f}%</div><div class="l">总收益</div></div>
<div class="m"><div class="v">{ann*100:.1f}%</div><div class="l">年化收益</div></div>
<div class="m"><div class="v">{len(trades)}笔</div><div class="l">入场交易</div></div>
<div class="m"><div class="v">{len(wins)}/{len(losses)}</div><div class="l">胜/负</div></div>
<div class="m"><div class="v">{len(wins)/max(1,len(trades))*100:.1f}%</div><div class="l">胜率</div></div>
<div class="m"><div class="v">{sum(t['pnl_pct'] for t in wins)/max(1,len(wins)):.1f}%</div><div class="l">平均盈利%</div></div>
<div class="m"><div class="v">{sum(t['pnl_pct'] for t in losses)/max(1,len(losses)):.1f}%</div><div class="l">平均亏损%</div></div>
<div class="m"><div class="v">{mdd:.1f}%</div><div class="l">最大回撤</div></div>
</div>

<div class="section">
<h2>📈 年度绩效</h2>
<table><tr><th>年份</th><th>入场交易</th><th>胜</th><th>负</th><th>胜率</th><th>期末权益</th></tr>'''
        running_cap = self.INITIAL_CAPITAL
        for yr in sorted(yearly.keys()):
            y = yearly[yr]
            running_cap += y['pnl_sum']
            wr = y['wins'] / max(1, y['count']) * 100
            html += f'<tr><td>{yr}</td><td>{y["count"]}</td><td class="pos">{y["wins"]}</td><td class="neg">{y["losses"]}</td><td>{wr:.0f}%</td><td class="pos">${running_cap:,.0f}</td></tr>'
        html += '</table></div>'

        html += f'''
<div class="section">
<h2>🚪 出场方式分布</h2>
<table><tr><th>出场方式</th><th>笔数</th><th>占比</th></tr>'''
        for rule, cnt in sorted(exit_stats.items(), key=lambda x: -x[1]):
            html += f'<tr><td>{rule}</td><td>{cnt}</td><td>{cnt/len(trades)*100:.0f}%</td></tr>'
        html += '</table></div>'

        html += f'''
<div class="section">
<h2>📥 入场信号类型</h2>
<table><tr><th>信号</th><th>笔数</th><th>占比</th></tr>'''
        for sig, cnt in sorted(entry_stats.items(), key=lambda x: -x[1]):
            html += f'<tr><td>{sig}</td><td>{cnt}</td><td>{cnt/len(trades)*100:.0f}%</td></tr>'
        html += '</table></div>'

        # ── 交割单明细（严格按入场时间排序，一行=完整一轮交易）────
        html += f'''
<div class="section">
<h2>📋 完整交割单 ({len(all_rows)} 行，按时间顺序排列)</h2>
<div style="display:grid;grid-template-columns:50px 95px 60px 85px 90px 80px 115px 115px 110px;gap:0;padding:7px 10px;background:#0d0d14;border-bottom:2px solid #1e1e2e;font-size:11px;color:#555;position:sticky;top:0">
<div>#</div>
<div>日期</div>
<div>操作</div>
<div>股票</div>
<div>价格</div>
<div>股数</div>
<div>金额</div>
<div>余额(买/卖前)</div>
<div>余额(买/卖后)</div>
<div>备注</div>
</div>'''

        row_num = 0
        for row in all_rows:
            rtype = row['_type']
            bal_before = row.get('_balance_before', 0)
            bal_after = row.get('balance', 0)

            if rtype == 'BUY':
                row_num += 1
                html += f'''<div style="display:grid;grid-template-columns:50px 95px 60px 85px 90px 80px 115px 115px 115px;gap:0;padding:5px 10px;border-bottom:1px solid #0c0c14;font-size:12px;background:#0a0a10">
<div style="color:#333">{row_num}</div>
<div style="color:#888">{row['date']}</div>
<div style="color:#00ff88;font-weight:700">BUY</div>
<div style="color:#c0c0c0;font-weight:600">{row['ticker']}</div>
<div style="color:#888">${row['price']:.4f}</div>
<div style="color:#aaa">{row['shares']:,}</div>
<div style="color:#888">${bal_before:,.2f}</div>
<div style="color:#666">${row['amount']:,.2f}</div>
<div style="color:#d0d0d0;font-weight:600">${bal_after:,.2f}</div>
</div>'''
            elif rtype == 'SELL':
                row_num += 1
                rule = row.get('exit_rule', '')
                bg, fg = rule_css.get(rule, ('#888820', '#888'))
                rule_html = f'<span style="background:{bg};color:{fg};padding:1px 5px;border-radius:3px;font-size:10px">{rule}</span>'
                html += f'''<div style="display:grid;grid-template-columns:50px 95px 60px 85px 90px 80px 115px 115px 115px 110px;gap:0;padding:5px 10px;border-bottom:1px solid #0c0c14;font-size:12px;background:#0a0a10">
<div style="color:#333">{row_num}</div>
<div style="color:#888">{row['date']}</div>
<div style="color:#ff4455;font-weight:700">SELL</div>
<div style="color:#c0c0c0;font-weight:600">{row['ticker']}</div>
<div style="color:#888">${row['price']:.4f}</div>
<div style="color:#aaa">{row['shares']:,}</div>
<div style="color:#888">${bal_before:,.2f}</div>
<div style="color:#666">${row['amount']:,.2f}</div>
<div style="color:#d0d0d0;font-weight:600">${bal_after:,.2f}</div>
<div>{rule_html}</div>
</div>'''
            elif rtype == 'PNL_INFO':
                pnl = row['_pnl_dollar']
                pct = row['_pnl_pct']
                sign = '+' if (pnl or 0) >= 0 else ''
                color = '#00ff88' if (pnl or 0) >= 0 else '#ff4455'
                hold = row['_hold_days'] if row['_hold_days'] is not None else '-'
                ep = row['_entry_price']
                xp = row['_exit_price']
                # 用 SELL 行的 shares（需从 row 获取）
                shares = row.get('shares', 0)
                entry_cost = ep * shares
                exit_val = xp * shares
                html += f'''<div style="display:grid;grid-template-columns:50px 95px 60px 85px 90px 80px 115px 115px 115px 110px;gap:0;padding:4px 10px 4px 20px;border-bottom:1px solid #0c0c14;font-size:11px;background:#0d0d16;color:#555;font-style:italic">
<div></div>
<div></div>
<div style="color:#333">→ PnL</div>
<div style="color:#666">成本${entry_cost:,.2f} → 收入${exit_val:,.2f}</div>
<div></div>
<div style="color:#888">{shares:,}股</div>
<div></div>
<div></div>
<div style="color:{color};font-weight:700;font-style:normal">{sign}${pnl:,.2f} ({pct:+.2f}%) | {hold}天</div>
<div></div>
</div>'''

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'报告已保存: {output_path}')
        print(f'文件大小: {len(html)/1024:.0f} KB')
        print(f'总行数: {len(all_rows)} 条（含 {len(self.tx_log)} 条交易 + PnL说明行）')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=int, default=2020)
    parser.add_argument('--end', type=int, default=2026)
    parser.add_argument('--output', type=str,
                       default='/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/backtest_v2143_delivery.html')
    args = parser.parse_args()

    base = Path(__file__).resolve().parent.parent
    pf = base.parent / 'TradingAgents/fintech/stock_pool.json'
    with open(pf) as f:
        pool = json.load(f)
    tickers = [s['code'] for s in pool.get('stocks', []) if s['code'] not in {'TNX', 'DXY', '^VIX'}]

    print(f'加载数据: {len(tickers)} 只...')
    bt = V2143Engine()
    bt.run(tickers, start_year=args.start, end_year=args.end)
    summary = bt.print_summary()
    bt.generate_html_report(args.output)
