#!/usr/bin/env python3
"""
engine_daily.py — h3-4-1 策略日线版本
========================================
将小时级 h3-4-1 策略逻辑移植到日线级别，并内置风险保护：

入场: BuyFilterEngine STAGE_4 NOW（同 h3-4-1）
出场:
  - 初始止损: 信号 stop_loss 或 entry - atr_mult × ATR
  - Lot1 target: entry + target_mult × ATR → 止损上移至保本
  - Lot2: ATR trailing peak - trail_mult × ATR(14) OR 跌回入场价
保护机制:
  - 账户级熔断: 从峰值回撤 >15% → 停止新开仓
  - SPY 趋势过滤: SPY.close < EMA50 → 不交易
  - 信号分级: 支持 --min-grade 过滤

用法:
    python3 engine_daily.py --years 2020 2026 --capital 20000 --risk-frac 0.30
"""
import json, sys, argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

BASE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE / 'model' / 'experts'))
from p_buy_filter_v2 import BuyFilterEngine, load_klines, _ema

PROJ_DIR = BASE / '..' / 'TradingAgents'
KLINES_DIR = PROJ_DIR / '中间过程' / 'klines'


# ── 工具函数 ────────────────────────────────────────────
def _atr_daily(bars, period=14):
    """日线 ATR"""
    if len(bars) < period + 1:
        return 0.0
    trs = []
    for i in range(max(1, len(bars) - period - 10), len(bars)):
        h = float(bars[i]["high"]); l = float(bars[i]["low"])
        pc = float(bars[i-1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period


def load_daily_klines(ticker, lookback=0):
    f = KLINES_DIR / f'{ticker}_1d.json'
    if not f.exists():
        return []
    with open(f) as fp:
        d = json.load(fp)
    bars = d.get('data', [])
    return bars[-lookback:] if lookback else bars


# ── 回测引擎 ────────────────────────────────────────────
class DailyBacktester:
    def __init__(self, initial_capital=20000, max_pos=8,
                 atr_mult=1.5, trail_mult=4.0, min_hold_days=3,
                 target_mult=3.0, risk_frac=0.30,
                 dd_limit=0.15, spy_trend=True, min_grade=None):
        self.cash = float(initial_capital)
        self.initial = float(initial_capital)
        self.max_pos = max_pos
        self.atr_mult = atr_mult
        self.trail_mult = trail_mult
        self.min_hold = min_hold_days
        self.target_mult = target_mult
        self.risk_frac = risk_frac
        self.dd_limit = dd_limit
        self.spy_trend = spy_trend
        self.min_grade = min_grade
        self.positions = {}
        self.trades = []
        self.tx_log = []
        self.trade_id = 0
        self._peak_cash = float(initial_capital)
        self._dd_active = False

    # ── 账户熔断检查 ──────────────────────────────────
    def _check_dd(self, spy_bars, idx):
        if self.dd_limit is None:
            return True
        # 总权益 = 现金 + 持仓市值
        equity = self.cash
        for ticker, pos in self.positions.items():
            entry = pos['entry_price']
            shares = pos['shares']
            # 用 SPY 近似替代个股当日价格变动
            if spy_bars and idx < len(spy_bars):
                spy_cur = float(spy_bars[idx]['close'])
                spy_entry_idx = None
                for j, b in enumerate(spy_bars):
                    if b['date'] == pos['entry_date']:
                        spy_entry_idx = j
                        break
                if spy_entry_idx is not None:
                    spy_entry = float(spy_bars[spy_entry_idx]['close'])
                    est_price = entry * (spy_cur / spy_entry)
                    equity += shares * est_price
                else:
                    equity += shares * entry
            else:
                equity += shares * entry
        peak = max(self._peak_cash, equity)
        if equity > self._peak_cash:
            self._peak_cash = equity
        dd = (self._peak_cash - equity) / self._peak_cash if self._peak_cash > 0 else 0
        if dd > self.dd_limit:
            if not self._dd_active:
                self._dd_active = True
                print(f'  ⚠️ 熔断! 权益回撤 {dd*100:.1f}% > {self.dd_limit*100:.0f}% | 停止新开仓')
            return False
        if self._dd_active and dd < self.dd_limit * 0.5:
            self._dd_active = False
            print(f'  ✅ 熔断解除 | 回撤 {dd*100:.1f}%')
        return not self._dd_active

    # ── SPY 趋势检查 ──────────────────────────────────
    def _spy_ok(self, spy_bars, idx):
        if not self.spy_trend or idx < 50:
            return True
        spy_c = float(spy_bars[idx]['close'])
        spy_e50 = _ema([float(b['close']) for b in spy_bars[:idx+1]], 50)[-1]
        return spy_c > spy_e50

    # ── 记录交易 ──────────────────────────────────────
    def _record(self, date, ticker, action, shares, price, pnl_dollar, rule):
        amount = shares * price
        if action == 'BUY':
            self.cash -= amount
        else:
            self.cash += amount
        self.tx_log.append({
            'date': date, 'action': action, 'ticker': ticker,
            'shares': round(shares, 4), 'price': round(price, 2),
            'amount': round(amount, 2), 'cash': round(self.cash, 2),
            'pnl_dollar': round(pnl_dollar, 2) if pnl_dollar else 0,
            'exit_rule': rule,
        })

    # ── 获取信号 ───────────────────────────────────────
    def _get_signal(self, ticker, bars_d, spy_bars, idx, prev_entry_price=None):
        eng = BuyFilterEngine(ticker, bars_d[:idx+1], spy_bars=spy_bars[:idx+1])
        return eng.run(bars_1h=None, daily_entry_price=prev_entry_price)

    # ── 主回测 ────────────────────────────────────────
    def run(self, tickers, start_year=2020, end_year=2026):
        # 加载数据
        all_daily = {}
        for t in tickers:
            bars = load_daily_klines(t)
            if bars:
                all_daily[t] = bars
        if 'SPY' not in all_daily:
            print('ERROR: SPY 数据缺失'); return {}
        spy = all_daily['SPY']

        def in_year(b, y0, y1):
            yr = b['date'][:4]; return str(y0) <= yr <= str(y1)

        si = next((i for i, b in enumerate(spy) if in_year(b, start_year, end_year)), None)
        ei = next((i for i in range(len(spy)-1, -1, -1) if in_year(spy[i], start_year, end_year)), None)
        if si is None:
            print(f'未找到 {start_year}-{end_year} 数据'); return {}

        spy_days = len(spy)
        print(f'日线引擎: {len(tickers)} 只 | {spy[si]["date"]} → {spy[ei]["date"]} | '
              f'{ei-si+1} 交易日')
        print(f'aTR×={self.atr_mult} | Trail={self.trail_mult}×ATR | '
              f'Hold={self.min_hold}d | Tgt={self.target_mult}×ATR | '
              f'RF={self.risk_frac} | MaxPos={self.max_pos}')
        dd_label = f'熔断={self.dd_limit*100:.0f}%' if self.dd_limit else '熔断=关闭'
        print(f'防护: {dd_label} | SPY趋势={self.spy_trend}')

        # 预计算 SPY EMA50
        spy_close = [float(b['close']) for b in spy]
        spy_e50 = _ema(spy_close, 50)

        new_pending = {}  # 跨日 STAGE_1 追踪

        for i in range(si, ei + 1):
            spy_i = i

            # ── 检查现有持仓 ─────────────────────────
            for ticker in list(self.positions):
                daily = all_daily.get(ticker, [])
                if not daily or i >= len(daily):
                    continue
                pos = self.positions[ticker]
                daily_i = i
                # 找到入场日
                entry_date = pos['entry_date']
                entry_idx = None
                for j, b in enumerate(daily):
                    if b['date'] == entry_date:
                        entry_idx = j
                        break
                if entry_idx is None:
                    continue

                bar = daily[daily_i]
                c = float(bar['close']); h = float(bar['high']); l = float(bar['low'])
                entry = pos['entry_price']
                hold_days = daily_i - entry_idx

                # ── 止损检查 ──────────────────────────
                stop = pos['stop_loss']
                if l <= stop:
                    pnl = (stop - entry) / entry
                    shares = pos['shares']
                    self._record(bar['date'], ticker, 'SELL', shares, stop, shares * (stop - entry), 'STOP_LOSS')
                    self.trades.append({
                        'ticker': ticker, 'entry_date': entry_date, 'exit_date': bar['date'],
                        'entry_price': entry, 'exit_price': stop, 'pnl_pct': round(pnl * 100, 2),
                        'exit_rule': 'STOP_LOSS', 'hold_days': hold_days,
                        'grade': pos.get('grade', '?'),
                    })
                    del self.positions[ticker]
                    continue

                # ── Lot1 target 触达 ──────────────────
                if not pos.get('lot1_done', False):
                    target = pos['target']
                    if h >= target and hold_days >= 1:
                        pos['lot1_done'] = True
                        pos['stop_loss'] = entry  # 保本
                        pos['peak_price'] = max(entry, c)
                        # 记录 lot1 sell
                        l1_pnl = (target - entry) / entry
                        l1_shares = pos['shares'] / 2
                        self._record(bar['date'], ticker, 'lot1_SELL', l1_shares, target,
                                    l1_shares * (target - entry), 'LOT1_TARGET')
                        self.trades.append({
                            'ticker': ticker, 'entry_date': entry_date, 'exit_date': bar['date'],
                            'entry_price': entry, 'exit_price': target, 'pnl_pct': round(l1_pnl * 100, 2),
                            'exit_rule': 'LOT1_TARGET', 'hold_days': hold_days, 'lot1': True,
                            'grade': pos.get('grade', '?'),
                        })
                        continue  # lot1 done, check lot2 next bar

                # ── Lot2: ATR trailing ────────────────
                if pos.get('lot1_done') and hold_days >= self.min_hold:
                    peak = pos.get('peak_price', entry)
                    if h > peak:
                        peak = h
                        pos['peak_price'] = peak
                    atr = _atr_daily(daily[:daily_i+1])
                    if atr <= 0:
                        atr = 0.01 * entry
                    trail = peak - self.trail_mult * atr

                    # 跌回入场价 OR ATR trailing
                    if l <= entry:
                        exit_px = entry
                        rule = 'BACK_TO_ENTRY'
                    elif c < trail:
                        exit_px = trail
                        rule = 'ATR_TRAILING'
                    else:
                        exit_px = None
                        rule = None

                    if exit_px is not None:
                        pnl = (exit_px - entry) / entry
                        l2_shares = pos['shares'] / 2
                        self._record(bar['date'], ticker, 'lot2_SELL', l2_shares, exit_px,
                                    l2_shares * (exit_px - entry), rule)
                        self.trades.append({
                            'ticker': ticker, 'entry_date': entry_date, 'exit_date': bar['date'],
                            'entry_price': entry, 'exit_price': exit_px, 'pnl_pct': round(pnl * 100, 2),
                            'exit_rule': rule, 'hold_days': hold_days, 'lot2': True,
                            'grade': pos.get('grade', '?'),
                        })
                        del self.positions[ticker]

            # ── 新入场 ────────────────────────────────
            if len(self.positions) >= self.max_pos:
                continue
            if not self._check_dd(spy, spy_i):
                continue
            if not self._spy_ok(spy, spy_i):
                continue
            if i + 1 >= len(spy):
                continue

            for ticker in tickers:
                if ticker == 'SPY':
                    continue
                if ticker in self.positions:
                    continue
                if len(self.positions) >= self.max_pos:
                    break
                daily = all_daily.get(ticker, [])
                if not daily or i >= len(daily) - 1:
                    continue

                sig = self._get_signal(ticker, daily, spy, i, prev_entry_price=new_pending.get(ticker))
                stage = sig.get('stage', 'STAGE_F')
                si_info = sig.get('stage_info', {})
                action = si_info.get('action', 'NO_ACTION')
                l1_reg = sig['layers'].get('L1', {}).get('regime', 'BEAR')
                l5_veto = sig['layers'].get('L5', {}).get('veto', False)
                grade = sig.get('grade', '?')
                l5 = sig['layers'].get('L5', {})
                rr = l5.get('details', {})

                if l1_reg == 'BEAR' or l5_veto:
                    continue

                # ── 入场质量过滤 ──────────────────────
                if self.min_grade is not None:
                    grade_rank = {'A': 1, 'B': 2, 'C': 3, 'D': 4}
                    if grade_rank.get(grade, 99) > grade_rank.get(self.min_grade, 99):
                        continue

                if stage == 'STAGE_4' and action == 'NOW':
                    entry_price = float(daily[i + 1]['open'])
                    if entry_price <= 0:
                        continue
                    atr = rr.get('atr', 0) or _atr_daily(daily[:i+1])
                    if atr <= 0:
                        continue
                    stop_loss = rr.get('stop_loss') or (entry_price - self.atr_mult * atr)
                    target = rr.get('mm_target') or (entry_price + self.target_mult * atr)

                    if self.cash <= 0:
                        continue
                    per_pos = self.cash * self.risk_frac
                    shares = int(per_pos / entry_price)
                    cost = shares * entry_price
                    if self.cash < cost or (self.cash - cost) < 500:
                        continue

                    self.trade_id += 1
                    entry_date = daily[i + 1]['date']
                    self._record(entry_date, ticker, 'BUY', shares, entry_price, 0, 'ENTRY')
                    self.positions[ticker] = {
                        'entry_date': entry_date,
                        'entry_price': entry_price,
                        'stop_loss': stop_loss,
                        'target': target,
                        'atr': atr,
                        'shares': shares,
                        'lot1_done': False,
                        'grade': grade,
                        'trade_id': self.trade_id,
                    }

                elif stage == 'STAGE_1' and not l5_veto:
                    # 记录待突破价格（次日突破则为 STAGE_4 NOW）
                    new_pending[ticker] = float(daily[i]['high'])
        for ticker in list(self.positions):
            daily = all_daily.get(ticker, [])
            pos = self.positions[ticker]
            if daily:
                exit_price = float(daily[-1]['close'])
            else:
                exit_price = pos['entry_price']
            entry_date = pos['entry_date']
            entry = pos['entry_price']
            pnl_pct = (exit_price - entry) / entry * 100
            shares = pos['shares']
            # 如果 lot1 已触达，lot2 部分用剩余股份
            if pos.get('lot1_done'):
                shares = shares / 2
            self._record(daily[-1]['date'] if daily else '?', ticker, 'SELL',
                        shares, exit_price, shares * (exit_price - entry), 'END_BACKTEST')
            self.trades.append({
                'ticker': ticker, 'entry_date': entry_date, 'exit_date': daily[-1]['date'] if daily else '?',
                'entry_price': entry, 'exit_price': exit_price, 'pnl_pct': round(pnl_pct, 2),
                'exit_rule': 'END_BACKTEST', 'grade': pos.get('grade', '?'),
            })
            del self.positions[ticker]

        return self._summary()

    # ── 统计输出 ──────────────────────────────────────
    def _summary(self):
        lot2_trades = [t for t in self.trades if t.get('lot2') or (not t.get('lot1') and not t.get('lot2'))]
        lot1_trades = [t for t in self.trades if t.get('lot1')]
        all_exits = lot2_trades + [t for t in lot1_trades if t['pnl_pct'] > 0]

        wins = [t for t in lot2_trades if t['pnl_pct'] > 0]
        losses = [t for t in lot2_trades if t['pnl_pct'] <= 0]
        total = len(wins) + len(losses)
        wr = len(wins) / total * 100 if total else 0
        avg_w = sum(t['pnl_pct'] for t in wins) / max(1, len(wins))
        avg_l = sum(t['pnl_pct'] for t in losses) / max(1, len(losses))
        rr = abs(avg_w / avg_l) if avg_l != 0 else 0

        grade_stats = defaultdict(lambda: {'count': 0, 'wins': 0, 'pnl_sum': 0.0})
        for t in all_exits:
            g = t.get('grade', '?')
            grade_stats[g]['count'] += 1
            if t['pnl_pct'] > 0:
                grade_stats[g]['wins'] += 1
            grade_stats[g]['pnl_sum'] += t['pnl_pct']
        for g in grade_stats:
            s = grade_stats[g]
            s['win_rate'] = s['wins'] / s['count'] * 100 if s['count'] else 0
            s['avg_pnl'] = s['pnl_sum'] / s['count'] if s['count'] else 0

        exit_stats = defaultdict(int)
        for t in lot2_trades:
            exit_stats[t.get('exit_rule', '?')] += 1

        final_cash = round(self.cash, 2)
        pnl = round(self.cash - self.initial, 2)
        peak_cash = self._peak_cash
        max_dd = (peak_cash - min(tx['cash'] for tx in self.tx_log)) / peak_cash * 100 if self.tx_log else 0

        print(f'\n{"="*60}')
        print(f'  日线引擎 回测结果')
        print(f'{"="*60}')
        print(f'总入场: {len(lot2_trades)} 笔 | Lot1触达: {len(lot1_trades)} 笔')
        print(f'胜率: {wr:.1f}% | avg win: {avg_w:+.2f}% | avg loss: {avg_l:+.2f}% | RR: {rr:.2f}')
        print(f'初始: ${self.initial:,.0f} → 期末: ${final_cash:,.2f} | 净盈亏: ${pnl:+,.2f} ({pnl/self.initial*100:+.1f}%)')
        print(f'最大回撤: {max_dd:.1f}% | 熔断触发: {self._dd_active}')

        print(f'\n按评级:')
        for g in sorted(grade_stats.keys()):
            s = grade_stats[g]
            print(f'  {g}: {s["count"]}笔 win={s["win_rate"]:.0f}% avg={s["avg_pnl"]:+.2f}%')
        print(f'\n出场方式:')
        for rule, cnt in sorted(exit_stats.items(), key=lambda x: -x[1]):
            print(f'  {rule}: {cnt}笔')

        # 计算峰值回撤序列
        eq = [(t['date'], t['cash']) for t in self.tx_log]
        peaks = []; dds = []
        running_peak = self.initial
        for date, cash in eq:
            if cash > running_peak:
                running_peak = cash
            dd = (running_peak - cash) / running_peak * 100 if running_peak > 0 else 0
            peaks.append(running_peak)
            dds.append(dd)
        avg_dd = sum(dds) / len(dds) if dds else 0

        return {
            'initial_capital': self.initial,
            'final_cash': final_cash,
            'total_pnl_dollar': pnl,
            'peak_cash': round(peak_cash, 2),
            'max_drawdown_pct': round(max(dds) if dds else 0, 2),
            'avg_drawdown_pct': round(avg_dd, 2),
            'total': total,
            'win_rate': round(wr, 2),
            'avg_win': round(avg_w, 2),
            'avg_loss': round(avg_l, 2),
            'win_loss_ratio': round(rr, 2),
            'lot1_count': len(lot1_trades),
            'dd_triggered': self._dd_active,
            'grade_stats': {str(k): v for k, v in grade_stats.items()},
            'exit_stats': dict(exit_stats),
            'trades': self.trades,
        }


# ── CLI ───────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description='h3-4-1 日线版引擎')
    ap.add_argument('--tickers', nargs='*')
    ap.add_argument('--years', nargs=2, default=['2025', '2026'])
    ap.add_argument('--capital', type=float, default=20000)
    ap.add_argument('--max-pos', type=int, default=8)
    ap.add_argument('--atr-mult', type=float, default=1.5)
    ap.add_argument('--trail-mult', type=float, default=4.0)
    ap.add_argument('--min-hold', type=int, default=3, help='最小持仓天数')
    ap.add_argument('--target-mult', type=float, default=3.0)
    ap.add_argument('--risk-frac', type=float, default=0.30)
    ap.add_argument('--dd-limit', type=float, default=None, help='账户熔断回撤阈值 (eg 0.15)，默认关闭')
    ap.add_argument('--no-spy-trend', action='store_true', help='禁用SPY趋势过滤')
    ap.add_argument('--min-grade', type=str, default=None, help='最低入场评级')
    ap.add_argument('--debug', action='store_true')
    ap.add_argument('--tag', type=str, default=None)
    ap.add_argument('--output', type=str, default=None)
    args = ap.parse_args()

    # 加载股票池
    pool_file = PROJ_DIR / 'fintech' / 'stock_pool.json'
    if pool_file.exists():
        with open(pool_file) as f:
            pool = json.load(f)
        tickers = [s['code'] for s in pool.get('stocks', [])]
    else:
        tickers = []
    if args.tickers:
        tickers = [t for t in args.tickers if t in tickers]
    if 'SPY' not in tickers:
        tickers.insert(0, 'SPY')

    sy, ey = int(args.years[0]), int(args.years[1])

    bt = DailyBacktester(
        initial_capital=args.capital,
        max_pos=args.max_pos,
        atr_mult=args.atr_mult,
        trail_mult=args.trail_mult,
        min_hold_days=args.min_hold,
        target_mult=args.target_mult,
        risk_frac=args.risk_frac,
        dd_limit=args.dd_limit,
        spy_trend=not args.no_spy_trend,
        min_grade=args.min_grade,
    )
    result = bt.run(tickers, start_year=sy, end_year=ey)

    if result:
        out_dir = BASE / 'backtest' / 'results'
        out_dir.mkdir(parents=True, exist_ok=True)
        tag = args.tag or f'daily_{sy}_{ey}'
        out = args.output if args.output else out_dir / f'results_daily_{tag}.json'
        with open(out, 'w') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f'\n结果已保存: {out}')


if __name__ == '__main__':
    main()
