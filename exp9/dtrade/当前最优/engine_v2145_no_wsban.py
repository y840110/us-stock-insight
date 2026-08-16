#!/usr/bin/env python3
"""
engine_v2143_branch_a.py — Branch A 参数变体引擎
==================================================
支持命令行参数快速切换配置：
  --atr      ATR trailing multiplier (default 4.0)
  --cooldown 重入场冷却天数 (default 5)
  --max-re   同一股票最大重入次数 (default 2)
  --rf       风险资金比例 (default 0.90)
  --max-pos  最大持仓数 (default 5)
"""

import sys, argparse, time as _time, json
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'model' / 'experts'))
from engine_base import BaseBacktester, load_klines, _atr
from p_buy_filter_v2 import BuyFilterEngine


class BranchAVariant(BaseBacktester):
    """Branch A 变体引擎（参数化版本）"""

    def __init__(self, atr=4.0, cooldown=5, max_re=2, rf=0.90, max_pos=5, min_pos_size=0):
        self.ATR_TRAIL_MULT = atr
        self.REENTRY_COOLDOWN = cooldown
        self.MAX_REENTRY = max_re
        self.RISK_FRAC = rf
        self.MAX_POS = max_pos
        self.MIN_POS_SIZE = min_pos_size
        self._setup()
        super().__init__()

    def _setup(self):
        self._ticker_exit_info = {}
        self._ticker_reentry_count = defaultdict(int)

    def _get_entry_signal(self, ticker, bars_d, idx, spy, spy_idx, eng, sig,
                          stage, action, grade, l3, l5, rr):
        # cooldown 检查
        if ticker in self._ticker_exit_info:
            info = self._ticker_exit_info[ticker]
            if info['cooldown'] > 0:
                return None
            if info['reentry_count'] >= self.MAX_REENTRY:
                return None
        # Stage_4
        if stage == 'STAGE_4' and action == 'NOW':
            return 'STAGE4'
        # Engulfing
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
        start_idx = next((i for i, b in enumerate(spy) if in_year(b, start_year, end_year)), None)
        end_idx   = next((i for i in range(len(spy)-1, -1, -1) if in_year(spy[i], start_year, end_year)), None)
        if start_idx is None:
            return {}

        total_days = end_idx - start_idx + 1
        print(f'  atr={self.ATR_TRAIL_MULT} cool={self.REENTRY_COOLDOWN} max_re={self.MAX_REENTRY} rf={self.RISK_FRAC} pos={self.MAX_POS}')

        # SPY EMA 预计算
        spy_ema200 = {}; spy_ema50 = {}
        for i in range(len(spy)):
            c = float(spy[i]['close'])
            if i >= 200:
                cs = [float(spy[i-200+j]['close']) for j in range(200)]
                a = 2/201; e = cs[0]
                for v in cs[1:]: e = a * v + (1-a) * e
                spy_ema200[i] = e
            else: spy_ema200[i] = None
            if i >= 50:
                cs = [float(spy[i-50+j]['close']) for j in range(50)]
                a = 2/51; e = cs[0]
                for v in cs[1:]: e = a * v + (1-a) * e
                spy_ema50[i] = e
            else: spy_ema50[i] = None

        # 主循环
        for idx in range(start_idx, end_idx + 1):
            spy_close = float(spy[idx]['close'])
            s200 = spy_ema200.get(idx); s50 = spy_ema50.get(idx)
            spy_bull = (s200 and spy_close > s200 and s50 and spy_close > s50)
            spy_bear = (s200 and spy_close < s200)

            # cooldown 更新
            for t in list(self._ticker_exit_info):
                self._ticker_exit_info[t]['cooldown'] -= 1
                if self._ticker_exit_info[t]['cooldown'] <= 0:
                    del self._ticker_exit_info[t]

            # 持仓更新
            for t, pos in list(self.positions.items()):
                bd = all_bars.get(t, [])
                pos['current_close'] = float(bd[idx]['close']) if idx < len(bd) else pos['entry_price']

            closed_today = set()
            # 出场
            for ticker in list(self.positions):
                bd = all_bars.get(ticker, [])
                if idx >= len(bd): continue
                bar = bd[idx]; pos = self.positions[ticker]
                hd = idx - pos['bars_at_entry']
                cur_h = float(bar['high']); cur_c = float(bar['close'])
                if cur_h > pos.get('atr_peak', pos['entry_price']):
                    pos['atr_peak'] = cur_h
                atr = pos['atr']; peak = pos.get('atr_peak', pos['entry_price'])
                trail = peak - self.ATR_TRAIL_MULT * atr
                trig = False; ep = cur_c; er = ''; eru = ''

                if not trig and hd >= self.MIN_HOLD_DAYS:
                    if cur_c < trail:
                        trig = True; ep = min(trail, cur_c); er = f'ATR({trail:.2f})'; eru = 'ATR_TRAILING'
                    elif spy_bear:
                        trig = True; er = f'SPY熊'; eru = 'SPY_BEAR_EXIT'
                    elif cur_c < pos['entry_price'] * 0.995:
                        trig = True; er = 'Breakeven'; eru = 'BREAKEVEN'
                elif not trig:
                    es = pos['entry_price'] - 3.0 * atr
                    if cur_c < es:
                        trig = True; ep = min(es, cur_c); er = f'宽止({es:.2f})'; eru = 'WIDE_STOP'

                if trig:
                    pnl_pct = (ep - pos['entry_price']) / pos['entry_price'] * 100
                    self._record_tx(bar['date'], 'SELL', ticker, pos['shares'], ep,
                                   pos['trade_id'], eru, pos['shares']*(ep-pos['entry_price']), pnl_pct, hd)
                    self._record_summary(ticker, pos, bar, ep, pnl_pct, 'EXIT', er, eru,
                                        self._post_exit_judge(bd, idx, pos['entry_price']), idx)
                    closed_today.add(ticker)
                    del self.positions[ticker]
                    if eru == 'WIDE_STOP':
                        self._ticker_exit_info[ticker] = {'cooldown': 5, 'reentry_count': self.MAX_REENTRY}
                    else:
                        self._ticker_exit_info[ticker] = {
                            'cooldown': self.REENTRY_COOLDOWN,
                            'reentry_count': self._ticker_exit_info.get(ticker, {}).get('reentry_count', 0) + 1,
                        }

            for t in closed_today:
                if t in self.positions: del self.positions[t]

            # 入场：先收集候选信号，再逐个处理（确保现金不重叠）
            if spy_bull and len(self.positions) < self.MAX_POS:
                candidates = []
                for ticker in tickers:
                    if ticker in self.positions or ticker in closed_today: continue
                    if ticker in self._ticker_exit_info:
                        inf = self._ticker_exit_info[ticker]
                        if inf['cooldown'] > 0 or inf['reentry_count'] >= self.MAX_REENTRY: continue
                    bd = all_bars.get(ticker, [])
                    if idx >= len(bd) - 1: continue
                    eng = BuyFilterEngine(ticker, bd[:idx+1], spy_bars=spy[:idx+1])
                    sig = eng.run(bars_1h=None, daily_entry_price=None)
                    stage = sig.get('stage', 'STAGE_F')
                    si = sig.get('stage_info', {})
                    action = si.get('action', 'NO_ACTION')
                    grade = sig.get('grade', '?')
                    l3 = sig['layers'].get('L3', {})
                    l5 = sig['layers'].get('L5', {})
                    rr = l5.get('details', {})
                    es = self._get_entry_signal(ticker, bd, idx, spy, idx, eng, sig,
                                                stage, action, grade, l3, l5, rr)
                    if es is None: continue
                    if idx + 1 >= len(bd): continue
                    ep2 = float(bd[idx + 1]['open'])
                    if ep2 <= 0: continue
                    av = rr.get('atr', 0) or _atr(bd[:idx+1])
                    if av <= 0: av = _atr(bd[:idx+1])
                    candidates.append({
                        'ticker': ticker, 'entry_date': bd[idx+1]['date'],
                        'entry_price': ep2, 'atr': av, 'stage': stage,
                        'grade': grade, 'bars_at_entry': idx,
                        'signal': es, 'l3': l3,
                    })

                # 逐个处理候选信号：现金足够则买入，不够则跳过
                for c in candidates:
                    if len(self.positions) >= self.MAX_POS: break
                    ep2 = c['entry_price']
                    av = c['atr']
                    cp = self.cash * self.RISK_FRAC
                    sh = int(cp / ep2)
                    if sh <= 0: continue
                    cost = sh * ep2
                    if cost > self.cash:
                        sh = max(1, int(self.cash / ep2))
                        cost = sh * ep2
                        if sh <= 0 or cost > self.cash: continue
                    fn = {'BREAD_BUTTER': 'BB', 'TRENDLINE_SUPPORT': '趋势', 'PULLBACK_50': '50%回',
                          'NEAR_EMA20': 'NearEMA', 'TIBOW_LONG': 'TIBOW', 'BULL_FLAG': 'BullFlag'}
                    self.trade_id += 1
                    self._record_tx(c['entry_date'], 'BUY', c['ticker'], sh, ep2, self.trade_id)
                    self.positions[c['ticker']] = {
                        'entry_date': c['entry_date'], 'entry_price': ep2,
                        'stop_loss': ep2 - 1.5 * av, 'atr': av, 'atr_peak': ep2,
                        'stage': c['stage'], 'grade': c['grade'], 'bars_at_entry': c['bars_at_entry'],
                        'capital_per_pos': cp, 'shares': sh, 'trade_id': self.trade_id,
                        'entry_reason': fn.get(c['l3'].get('form_type','?'), '?'),
                        'ticker': c['ticker'], 'current_close': ep2, 'entry_signal': c['signal'],
                    }

            if idx % 200 == 0:
                pct = (idx - start_idx) / total_days * 100
                print(f'  {spy[idx]["date"]} [{pct:.0f}%] {_time.time()-t0:.0f}s cash=${self.cash:,.0f} pos={len(self.positions)} tr={self.trade_id}')

        # 平仓
        for ticker in list(self.positions):
            bd = all_bars.get(ticker, [])
            if not bd: continue
            li = len(bd) - 1; bar = bd[li]; pos = self.positions[ticker]
            ep2 = float(bar['close'])
            pp = (ep2 - pos['entry_price']) / pos['entry_price'] * 100
            self._record_tx(bar['date'], 'SELL', ticker, pos['shares'], ep2, pos['trade_id'],
                           'END', pos['shares']*(ep2-pos['entry_price']), pp, li-pos['bars_at_entry'])
            self._record_summary(ticker, pos, bar, ep2, pp, 'END', '期末平仓', 'END',
                                self._post_exit_judge(bd, li, pos['entry_price']), li)
            del self.positions[ticker]

        print(f'  完成: {_time.time()-t0:.1f}s')
        return self


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--atr', type=float, default=4.0)
    p.add_argument('--cooldown', type=int, default=5)
    p.add_argument('--max-re', type=int, default=2)
    p.add_argument('--rf', type=float, default=0.90)
    p.add_argument('--max-pos', type=int, default=5)
    p.add_argument('--min-pos-size', type=float, default=0, help='最小仓位门槛（美元），低于此值不入场')
    p.add_argument('--start', type=int, default=2020)
    p.add_argument('--end', type=int, default=2026)
    p.add_argument('--label', type=str, default='')
    args = p.parse_args()

    base = Path(__file__).resolve().parent.parent
    pf = base.parent / 'TradingAgents/fintech/stock_pool.json'
    with open(pf) as f:
        pool = json.load(f)
    tickers = [s['code'] for s in pool.get('stocks', []) if s['code'] not in {'TNX','DXY','^VIX'}]

    bt = BranchAVariant(atr=args.atr, cooldown=args.cooldown, max_re=args.max_re,
                        rf=args.rf, max_pos=args.max_pos, min_pos_size=args.min_pos_size)
    bt.run(tickers, start_year=args.start, end_year=args.end)
    r = bt.print_summary()
    if args.label:
        print(f'  [Label] {args.label}')
