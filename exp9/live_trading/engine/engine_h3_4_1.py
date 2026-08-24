#!/usr/bin/env python3
"""
exp9 小时K回测引擎 h3-4 — Lot1 目标触达时不卖出，止损上移至入场价
====================================================================

h3-4-1：基于 h3-4，Lot2 止盈从 20% 固定回撤改为 ATR 自适应 trailing stop
      trailing_stop = peak - k × ATR_1h（k=2.0）

改动 vs h3-3：
  h3-3：Lot1 目标触达 → 卖出 lot1，lot2_stop 移到目标价，lot2 用 20% 回撤止盈
  h3-4：Lot1 目标触达 → 不卖出，止损上移至 entry_price（保本），
        lot2 继续持仓，利润回撤 20% OR 价格跌回 entry_price → 全出

入场（完全沿用 v2-1）：
  BuyFilterEngine STAGE_4 NOW → 次日开盘入场
  止损：日线 ATR × 1.5
  目标：日线 Measured Move

出场（改造）：
  Lot 1（50%）：触达日线目标 → 不卖出，止损上移至 entry_price（保本）
  Lot 2（50%）：保本后，继续持仓
                条件A：利润从峰值回撤 20% 止盈（trailing stop）
                条件B：价格跌回 entry_price（全出）
                两个条件 OR 关系，先触达者成交

数据：
  日线：入场/止损/目标（不变）
  小时K（RTH 9:30-15:30 ET）：持仓追踪/出场判断

参数：
  atr_mult: 1.5（初始止损，沿用 v2-1）
  atr_trailing_mult: 2.0（ATR trailing 倍数）
  min_hold: 5（最少持仓 5 根小时K 才检查出场）

用法：
    python3 engine_h3_4_1.py --tickers AAPL MSFT GOOGL AMZN --years 2025 2026
    python3 engine_h3_4.py --from-log logs/xxx.jsonl   # 从日志重跑统计
"""

import json, sys, argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

BASE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE / 'model' / 'experts'))

from p_buy_filter_v2 import BuyFilterEngine, load_klines, _ema


def _atr(bars, period=14):
    if len(bars) < period + 1:
        return 0.0
    trs = []
    for i in range(1, min(len(bars), period + 20)):
        h = float(bars[i]["high"]); l = float(bars[i]["low"])
        pc = float(bars[i-1]["close"])
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs[-period:]) / period if len(trs) >= period else 0.0


def load_klines_1h(ticker, lookback=2000):
    f = (BASE / ".." / "TradingAgents" / "中间过程" / "klines" /
         f"{ticker}_1h.json")
    if not f.exists():
        return []
    with open(f) as fp:
        d = json.load(fp)
    bars = d.get("data", [])
    if not bars:
        return []
    bars = bars[-lookback:]
    # 只保留美股 RTH（9:30-15:30 ET）
    filtered = []
    for b in bars:
        dt = b.get("datetime", "")
        if len(dt) >= 18:
            hour = int(dt[11:13]); minute = int(dt[14:16])
            if (hour == 9 and minute >= 30) or (10 <= hour <= 14) or (hour == 15 and minute <= 30):
                filtered.append(b)
    return filtered


class Backtester1hV5:
    def __init__(self, initial_capital=20_000.0, max_positions=5,
                 atr_mult=1.5, atr_trailing_mult=4.0, min_hold=5,
                 risk_frac=0.20, pos_cap=20_000.0, target_mult=3.0,
                 min_grade=None):
        self.capital       = initial_capital
        self.initial       = initial_capital
        self.max_pos      = max_positions
        self.atr_mult     = atr_mult
        self.atr_trailing_mult = atr_trailing_mult
        self.min_hold     = min_hold
        self.min_grade    = min_grade
        self.target_mult  = target_mult
        self.risk_frac    = risk_frac
        self.pos_cap      = pos_cap
        self.positions    = {}
        self.history      = []
        self.trade_id     = 0
        self._journal_path = None
        # 现金日志（实盘回测核心）
        self.cash         = float(initial_capital)
        self.INITIAL_CAPITAL = float(initial_capital)
        self.tx_log       = []   # 每笔买/卖一行

        # ── 三变量仓位管理体系（独立于引擎原有 positions）────────────
        # 持仓 map：ticker → 剩余股数（每次买/卖后实时更新）
        self._trade_positions = {}   # ticker → 剩余股数（独立）
        # 交易记录数组：每次买/卖后追加
        self.trade_log   = []
        # 操作序号（数组下标）
        self._trade_seq  = 0
        # JSONL 文件路径（_debug 模式时有效）
        self._trade_jsonl_path = None
        self.equity_curve = []  # 逐交易日权益快照（现金+持仓市值），用于权益口径回撤

    def _record_equity(self, all_daily, spy_d, i):
        """权益快照：现金 + 各持仓剩余股数×日线收盘价（含浮亏浮盈）"""
        eq = self.cash
        for ticker, shares in self._trade_positions.items():
            if shares <= 0:
                continue
            daily = all_daily.get(ticker, [])
            if daily and i < len(daily):
                px = float(daily[i]['close'])
            else:
                px = float(self.positions.get(ticker, {}).get('entry_price', 0) or 0)
            eq += shares * px
        self.equity_curve.append({'date': spy_d[i]['date'], 'equity': round(eq, 2)})

    def _record_tx(self, date, action, ticker, shares, price, trade_id,
                   exit_rule=None, pnl_dollar=None, hold_days=None,
                   total_pnl=None):
        """记录买/卖现金流水（实盘回测核心）"""
        amount = shares * price
        cash_before = self.cash
        if action == 'BUY':
            self.cash -= amount
        else:
            self.cash += amount
        rec = {
            'date': date,
            'action': action,
            'ticker': ticker,
            'shares': round(shares, 4),
            'price': round(price, 4),
            'amount': round(amount, 2),
            'cash_before': round(cash_before, 2),
            'cash_after': round(self.cash, 2),
            'trade_id': trade_id,
            'exit_rule': exit_rule,
            'pnl_dollar': round(pnl_dollar, 2) if pnl_dollar is not None else None,
            'hold_days': hold_days,
            'total_pnl': round(total_pnl, 2) if total_pnl is not None else None,
        }
        self.tx_log.append(rec)
        # ── 三变量实时更新（跳过 0 股交易）───────────────────
        if shares > 0:
            self._trade_seq += 1
            self._update_positions_and_write(date, action, ticker, shares, amount, self._trade_seq)
        return rec


    def _update_positions_and_write(self, date, action, ticker, shares, amount, trade_seq):
        """
        维护 _trade_positions map、trade_log 数组，写入 JSONL 文件。
        """
        # 1. 更新持仓 map
        current = self._trade_positions.get(ticker, 0)
        if not isinstance(current, (int, float)):
            current = 0
        if action == 'BUY':
            self._trade_positions[ticker] = current + shares
        else:
            self._trade_positions[ticker] = current - shares
            if self._trade_positions[ticker] <= 0:
                self._trade_positions.pop(ticker, None)

        # 2. 写入交易记录
        log_entry = {
            'seq':        trade_seq,
            'datetime':   date,
            'action':     action,
            'ticker':     ticker,
            'shares':     round(shares, 4),
            'amount':     round(amount, 2),
            'cash':       round(self.cash, 2),
        }
        self.trade_log.append(log_entry)

        # 3. 实时落盘
        if self._trade_jsonl_path:
            with open(self._trade_jsonl_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')

    def _flush_trade_log(self, path=None):
        """回测结束时统一落盘"""
        if not path:
            path = self._trade_jsonl_path
        if not path or not self.trade_log:
            return
        with open(path, 'w', encoding='utf-8') as f:
            for entry in self.trade_log:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def save(self, path=None):
        """导出实盘交割单 Excel（按日期排序）"""
        try:
            import openpyxl
        except ImportError:
            try:
                import subprocess, sys
                subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'openpyxl', '-q'])
                import openpyxl
            except Exception:
                print('请安装 openpyxl: pip install openpyxl')
                return

        # 按原始执行顺序输出（cash_before/cash_after 在记录时已对应执行顺序）
        # 如需按日期看，可全量重算 cash_before（见下），这里保持原始顺序以便验证资金流
        exec_seq = 0
        for tx in self.tx_log:
            tx['_seq'] = exec_seq
            exec_seq += 1
        tx_log = sorted(self.tx_log, key=lambda x: x['_seq'])

        # 重算每行 cash_before（保持日期排序时资金流正确）
        running_cash = float(self.INITIAL_CAPITAL)
        for tx in tx_log:
            tx['_cash_before'] = round(running_cash, 2)
            if tx['action'] == 'BUY':
                running_cash -= tx['amount']
            else:
                running_cash += tx['amount']
            tx['_cash_after'] = round(running_cash, 2)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = '交割单'

        # 表头
        headers = ['操作日期', '交易编号', '操作类型', '股票代码',
                   '操作股数', '股价', '操作金额', '剩余现金',
                   '累计盈亏', '持仓天数', '出场规则', '备注']
        ws.append(headers)

        for i, tx in enumerate(tx_log):
            prev = tx_log[i - 1] if i > 0 else None
            # 备注用重算后的 cash_before/after
            if tx['action'] == 'BUY':
                note = f"{tx['_cash_before']:,.2f} - {tx['amount']:,.2f} = {tx['_cash_after']:,.2f}"
            else:
                note = f"{tx['_cash_before']:,.2f} + {tx['amount']:,.2f} = {tx['_cash_after']:,.2f}"
            ws.append([
                tx['date'],
                i + 1,  # 顺序操作编号
                tx['action'],
                tx['ticker'],
                tx['shares'],
                tx['price'],
                tx['amount'],
                tx['_cash_after'],
                tx.get('total_pnl', ''),
                tx.get('hold_days', ''),
                tx.get('exit_rule', ''),
                note,
            ])

        # 合计行
        total_deposits = sum(t['amount'] for t in tx_log if t['action'] == 'BUY')
        total_withdraws = sum(t['amount'] for t in tx_log if t['action'] == 'SELL')
        ws.append([])
        ws.append(['合计', '', '', '', '', '',
                   f'买入总额: {total_deposits:,.2f}',
                   '', f'卖出总额: {total_withdraws:,.2f}', '', '', ''])
        ws.append(['最终现金', '', '', '', '', '', '',
                   round(self.cash, 2), '', '',
                   f'初始: {self.INITIAL_CAPITAL:,.2f} → 期末: {round(self.cash, 2):,.2f}'])

        # 负现金标红
        for row in ws.iter_rows(min_row=2):
            cash_cell = row[7]  # 剩余现金列
            if isinstance(cash_cell.value, (int, float)) and cash_cell.value < 0:
                cash_cell.font = openpyxl.styles.Font(color='FF0000', bold=True)

        if path is None:
            path = Path(__file__).resolve().parent / 'trade_log_h341_live.xlsx'
        wb.save(path)
        print(f'交割单已保存: {path}')
        return path

    def _debug_record(self, rec):
        self.history.append(rec)
        if self._journal_path:
            with open(self._journal_path, 'a') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    # ── 小时K追踪（h3-4：Lot1 目标触达不卖，止损上移保本）────────────
    def _track_1h(self, ticker, pos, h1_bars, entry_h1_idx, current_h1_idx):
        """
        h3-4 出场逻辑：
          Lot 1：日线目标触达 → 不卖出，止损上移至 entry_price（保本）
          Lot 2：持仓 >= min_hold 后，
                 条件A：利润从峰值回撤 20% → 止盈
                 条件B：价格跌回 entry_price → 全出
                 两个条件 OR，先触达者成交
        """
        if current_h1_idx <= entry_h1_idx:
            return False, None, None, None

        cur_open  = float(h1_bars[current_h1_idx]["open"])
        cur_close = float(h1_bars[current_h1_idx]["close"])
        cur_high  = float(h1_bars[current_h1_idx]["high"])
        cur_low   = float(h1_bars[current_h1_idx]["low"])
        hold_h1   = current_h1_idx - entry_h1_idx

        entry_price  = pos['entry_price']
        atr          = pos['atr']
        daily_target = pos.get('target', entry_price + self.target_mult * atr)
        lot1_done    = pos.get('lot1_done', False)
        lot2_stop    = pos.get('lot2_stop', pos['stop_loss'])

        # ── 止损（固定止损价，隔夜 gap 按止损价结算）────────────────
        # 如果下一根 K 线开盘价 < 止损价 → 止损单触发，以止损价结算
        if cur_open < lot2_stop:
            return True, round(lot2_stop, 2), f'止损触发({lot2_stop:.2f}≤开{cur_open:.2f})', 'STOP_LOSS'
        # 盘中价格跌破止损
        if cur_low <= lot2_stop:
            return True, round(lot2_stop, 2), f'止损({lot2_stop:.2f})', 'STOP_LOSS'

        # ── Lot 1：日线目标触达 → 不卖，止损上移至 entry_price（保本）──
        if not lot1_done:
            hit_target = any(
                float(h1_bars[j]["high"]) >= daily_target
                for j in range(entry_h1_idx + 1, current_h1_idx + 1)
            )
            if hit_target and hold_h1 >= 2:
                # h3-4 核心改动：不卖出 lot1，只把止损上移至 entry_price（保本）
                pos['lot1_done'] = True
                pos['lot1_price'] = daily_target
                pos['lot2_stop'] = entry_price  # 保本止损
                pos['peak_price'] = cur_high    # 从当前高点开始追踪利润回撤
                pos['h1_entry_idx'] = current_h1_idx
                # 返回特殊信号 LOT1_HIT，让 _on_day 写 lot1_sell 但继续追踪 lot2
                return True, round(daily_target, 2), f'Lot1目标触达({daily_target:.2f})→保本止损', 'LOT1_HIT'

        # ── Lot 2：ATR自适应trailing OR 价格跌回 entry_price → 全出 ──
        if lot1_done and hold_h1 >= self.min_hold:
            # 计算ATR_1h（从入场到当前的1h真实波幅）
            atr_1h = pos.get('atr_1h')
            if atr_1h is None:
                trs = []
                for i in range(entry_h1_idx, min(current_h1_idx + 1, len(h1_bars))):
                    if i == 0: continue
                    h = float(h1_bars[i]["high"]); l = float(h1_bars[i]["low"])
                    pc = float(h1_bars[i-1]["close"])
                    trs.append(max(h-l, abs(h-pc), abs(l-pc)))
                atr_1h = sum(trs[-14:]) / min(14, len(trs)) if trs else 0.0
                pos['atr_1h'] = atr_1h

            peak = pos.get('peak_price', entry_price)
            # 追踪峰值（只上移不下移）
            if cur_high > peak:
                peak = cur_high
                pos['peak_price'] = peak

            entry = entry_price

            # 条件A：ATR trailing 止盈
            trailing_stop = peak - self.atr_trailing_mult * atr_1h

            # 条件B：价格跌回 entry_price（全出，保本）
            exit_price = None
            exit_reason = None
            exit_rule = None

            # 检查条件B（价格跌回 entry_price）
            if cur_low <= entry:
                exit_price = entry
                exit_reason = f'Lot2跌回入场价(h={peak:.2f},atr={atr_1h:.4f},entry={entry:.2f},low={cur_low:.2f})'
                exit_rule = 'LOT2_BACK_TO_ENTRY'
            # 检查条件A（ATR trailing）
            elif cur_close < trailing_stop:
                exit_price = trailing_stop
                exit_reason = f'Lot2_ATR_trailing止盈(h={peak:.2f},atr={atr_1h:.4f},stop={trailing_stop:.2f},close={cur_close:.2f})'
                exit_rule = 'LOT2_ATR_TRAILING'

            if exit_price is not None:
                return True, round(exit_price, 2), exit_reason, exit_rule

        return False, None, None, None

    # ── 日线遍历（入场） ────────────────────────────────────
    def _on_day(self, ticker, daily_bars, spy_bars, h1_bars_all,
                daily_idx, tickers, new_pending):
        """完全沿用 v2-1 入场逻辑"""
        if ticker in self.positions:
            pos = self.positions[ticker]
            today_date = daily_bars[daily_idx]['date']
            if not h1_bars_all:
                return

            # 找到今日（daily_idx）对应的 h1 范围
            today_h1_end = None
            for i in range(len(h1_bars_all) - 1, -1, -1):
                if h1_bars_all[i]['datetime'][:10] == today_date[:10]:
                    today_h1_end = i
                    break
            if today_h1_end is None:
                return

            entry_h1_idx = pos.get('h1_entry_idx', 0)
            today_h1_start = None
            for i in range(entry_h1_idx + 1, today_h1_end + 1):
                if h1_bars_all[i]['datetime'][:10] == today_date[:10]:
                    today_h1_start = i
                    break
            if today_h1_start is None:
                today_h1_start = entry_h1_idx + 1

            for h1_idx in range(today_h1_start, today_h1_end + 1):
                should_exit, exit_price, exit_reason, exit_rule = \
                    self._track_1h(ticker, pos, h1_bars_all, entry_h1_idx, h1_idx)

                # ── lot1 目标触达（h3-4 特有：写 lot1_sell，继续追踪 lot2）──
                # _track_1h 触达目标时返回 (False,None,None,None) 让我们继续追踪
                # 所以用独立条件检测 lot1_done 但还未写记录的情况
                if (exit_rule is None and pos.get('lot1_done') and
                        not pos.get('_lot1_recorded')):
                    h1_bar  = h1_bars_all[h1_idx]
                    capital_per_pos = min(self.capital * self.risk_frac, self.pos_cap)
                    lot1_shares = int(capital_per_pos / 2 / pos['entry_price'])
                    lot1_profit = lot1_shares * (pos['target'] - pos['entry_price'])
                    pos['realized_profit'] = lot1_profit
                    pos['lot2_shares'] = lot1_shares  # LOT2 剩余股数 = LOT1 股数
                    pos['_lot1_recorded'] = True
                    self._record_tx(h1_bar.get("datetime", "?"), 'SELL', ticker,
                                   lot1_shares, pos['target'], pos.get('trade_id', 0),
                                   'LOT1_TARGET', lot1_profit)
                    self._debug_record({
                        'trade_id':   pos.get('trade_id', 0),
                        'leg':        'lot1_sell',
                        'ticker':     ticker,
                        'lot1':       True,
                        'lot2':       False,
                        'entry_date': pos.get('entry_date', '?'),
                        'exit_date':  h1_bar.get('datetime', '?')[:10],
                        'entry_price': round(pos['entry_price'], 2),
                        'exit_price':  round(pos['target'], 2),
                        'shares':      round(lot1_shares, 4),
                        'capital_per_pos': round(capital_per_pos / 2, 2),
                        'total_pnl':  round(lot1_profit, 2),
                        'realized_profit': round(lot1_profit, 2),
                        'stop_loss':  round(pos['stop_loss'], 2),
                        'target':     round(pos.get('target', 0), 2),
                        'atr':        round(pos.get('atr', 0), 2),
                        'rr_ratio':   pos.get('rr_ratio', 0),
                        'pnl_pct':    round((pos['target'] - pos['entry_price']) / pos['entry_price'] * 100, 2),
                        'result':     'LOT1_TARGET',
                        'exit_reason': f'Lot1目标止盈({pos["target"]:.2f})',
                        'exit_rule':  'LOT1_TARGET',
                        'stage':      pos.get('stage', '?'),
                        'grade':      pos.get('grade', '?'),
                        'engine_version': 'h3-4-1',
                    })
                    # 不 return，继续追踪 lot2

                if should_exit and exit_price is not None:
                    h1_bar  = h1_bars_all[h1_idx]

                    # h3-4 特殊：LOT1_HIT → 写 lot1_sell，继续追踪 lot2（不清仓）
                    if exit_rule == 'LOT1_HIT':
                        capital_per_pos = min(self.capital * self.risk_frac, self.pos_cap)
                        lot1_shares = int(capital_per_pos / 2 / pos['entry_price'])
                        lot1_profit = lot1_shares * (pos['target'] - pos['entry_price'])
                        pos['realized_profit'] = lot1_profit
                        pos['lot2_shares'] = lot1_shares  # LOT2 剩余股数 = LOT1 股数
                        pos['_lot1_recorded'] = True
                        self._record_tx(h1_bar.get("datetime", "?"), 'SELL', ticker,
                                       lot1_shares, pos['target'], pos.get('trade_id', 0),
                                       'LOT1_TARGET', lot1_profit,
                                       total_pnl=lot1_profit)
                        self._debug_record({
                            'trade_id':   pos.get('trade_id', 0),
                            'leg':        'lot1_sell',
                            'ticker':     ticker,
                            'lot1':       True,
                            'lot2':       False,
                            'entry_date': pos.get('entry_date', '?'),
                            'exit_date':  h1_bar.get('datetime', '?')[:10],
                            'entry_price': round(pos['entry_price'], 2),
                            'exit_price':  round(pos['target'], 2),
                            'shares':      round(lot1_shares, 4),
                            'capital_per_pos': round(capital_per_pos / 2, 2),
                            'total_pnl':  round(lot1_profit, 2),
                            'realized_profit': round(lot1_profit, 2),
                            'stop_loss':  round(pos['stop_loss'], 2),
                            'target':     round(pos.get('target', 0), 2),
                            'atr':        round(pos.get('atr', 0), 2),
                            'rr_ratio':   pos.get('rr_ratio', 0),
                            'pnl_pct':    round((pos['target'] - pos['entry_price']) / pos['entry_price'] * 100, 2),
                            'result':     'LOT1_TARGET',
                            'exit_reason': exit_reason,
                            'exit_rule':  'LOT1_TARGET',
                            'stage':      pos.get('stage', '?'),
                            'grade':      pos.get('grade', '?'),
                            'engine_version': 'h3-4-1',
                        })
                        # 不 return，继续追踪 lot2
                        continue

                    # 正常出场：止损 / LOT2止盈 / 期末
                    pnl_pct = (exit_price - pos['entry_price']) / pos['entry_price'] * 100
                    post    = self._post_exit_judge(h1_bars_all, h1_idx, pos['entry_price'])
                    ld1 = pos.get('lot1_done', False)
                    ld2 = ('up' if exit_rule in ('LOT2_DRAWDOWN_20', 'LOT2_BACK_TO_ENTRY', 'LOT2_ATR_TRAILING')
                           else ('down' if exit_rule == 'STOP_LOSS' else False))
                    lot2_rec = self._trade_record(
                        ticker, pos, h1_bar, exit_price, pnl_pct,
                        'EXIT', exit_reason, post, h1_idx, exit_rule, 'lot2_sell',
                        lot1=ld1, lot2=ld2)
                    # 实盘现金日志：lot2_pnl 只算 lot2 部分的盈亏（不重复含 lot1）
                    capital_per_pos = min(self.capital * self.risk_frac, self.pos_cap)
                    total_shares = int(capital_per_pos / pos['entry_price'])
                    # 取缓存的 lot2 股数：LOT1 触发后写入（=lot1_shares），未命中则未写入
                    # 若缓存未命中（lot1 从未触发），lot2 卖出全部股数
                    lot2_only_shares = pos.get('lot2_shares', total_shares)
                    lot2_pnl = lot2_only_shares * (exit_price - pos['entry_price'])
                    self._record_tx(h1_bar.get("datetime", "?"), 'SELL', ticker,
                                   lot2_only_shares, exit_price, pos.get('trade_id', 0),
                                   exit_rule, round(lot2_pnl, 2),
                                   total_pnl=round(lot2_pnl + pos.get('realized_profit', 0.0), 2))
                    if ld1 and pos.get('realized_profit'):
                        lot2_rec['realized_profit'] = round(pos.get('realized_profit', 0.0), 2)
                        # total_pnl 调整为 lot1 + lot2（用于 debug_record，不影响现金）
                        lot2_rec['total_pnl'] = round(
                            lot2_pnl + pos.get('realized_profit', 0.0), 2)
                        lot2_rec['pnl_pct'] = round(
                            lot2_rec['total_pnl'] / capital_per_pos * 100, 2)
                    self._debug_record(lot2_rec)
                    del self.positions[ticker]
                    new_pending.pop(ticker, None)
                    return

        else:
            if ticker == 'SPY':
                return
            if len(self.positions) >= self.max_pos:
                return
            if daily_idx + 1 >= len(daily_bars):
                return

            prev_entry = new_pending.get(ticker)
            sig = self._get_signal(ticker, daily_bars, spy_bars, daily_idx,
                                   prev_entry_price=prev_entry)

            stage   = sig.get('stage', 'STAGE_F')
            si      = sig.get('stage_info', {})
            action  = si.get('action', 'NO_ACTION')
            l1_reg  = sig['layers'].get('L1', {}).get('regime', 'BEAR')
            l5_veto = sig['layers'].get('L5', {}).get('veto', False)
            grade   = sig.get('grade', '?')
            l3      = sig['layers'].get('L3', {})
            l4      = sig['layers'].get('L4', {})
            l5      = sig['layers'].get('L5', {})
            rr      = l5.get('details', {})
            tier    = l3.get('pullback_tier', 0)

            if l1_reg == 'BEAR' or l5_veto:
                return

            if stage == 'STAGE_4' and action == 'NOW':
                # ── 入场质量过滤（新增）──
                if self.min_grade is not None:
                    grade_rank = {'A': 1, 'B': 2, 'C': 3, 'D': 4}
                    if grade_rank.get(grade, 99) > grade_rank.get(self.min_grade, 99):
                        return  # 低于最低评级要求，跳过
                entry_price = float(daily_bars[daily_idx + 1]['open'])
                if entry_price <= 0:
                    return
                atr = rr.get('atr', 0) or _atr(daily_bars[:daily_idx+1])
                if atr <= 0:
                    return
                atr = rr.get('atr', 0) or _atr(daily_bars[:daily_idx+1])
                stop_loss = rr.get('stop_loss') or (entry_price - self.atr_mult * atr)
                target    = rr.get('mm_target') or (entry_price + self.target_mult * atr)

                # 找到 entry 日期对应的 h1 索引
                entry_date = daily_bars[daily_idx + 1]['date']
                h1_entry_idx = None
                for i in range(len(h1_bars_all)):
                    if h1_bars_all[i]['datetime'][:10] == entry_date[:10]:
                        h1_entry_idx = i
                        break
                if h1_entry_idx is None:
                    h1_entry_idx = 0

                tier_names = {4:'EMA20', 3:'50%', 2:'趋势线', 1:'宽通道', 0:'无'}
                form_names = {'BREAD_BUTTER':'BreadButter','TRENDLINE_SUPPORT':'趋势线',
                              'PULLBACK_50':'50%回撤','NEAR_EMA20':'NearEMA20',
                              'TIBOW_LONG':'TIBOW','BULL_FLAG':'BullFlag'}
                form = l3.get('form_type', '?')
                entry_reason = (f'STAGE_4 NOW | {grade}级 | '
                               f'tier={tier}({tier_names.get(tier,"?")}) | '
                               f'{form_names.get(form,form)} | '
                               f'RR={rr.get("rr_ratio","?")} | '
                               f'回踩完成={l4.get("pullback_done")}')

                self.positions[ticker] = {
                    'entry_date':    entry_date,
                    'entry_price':   entry_price,
                    'stop_loss':     stop_loss,
                    'target':        target,
                    'atr':           atr,
                    'rr_ratio':      rr.get('rr_ratio', 3.0),
                    'stage':         stage,
                    'grade':         grade,
                    'bars_at_entry': daily_idx,
                    'h1_entry_idx':  h1_entry_idx,
                    'entry_l3_form': form or '?',
                    'entry_l3_tier': tier,
                    'entry_l3_deep': l3.get('deep_rejection', False),
                    'entry_l4_pullback_done': l4.get('pullback_done', False),
                    'entry_l4_bull_engulf': l4.get('bull_engulf', False),
                    'entry_l5_rr': rr.get('rr_ratio', 0),
                    'entry_l5_target_src': rr.get('target_source', '?'),
                    'entry_l1_regime': l1_reg,
                    'lot1_done':   False,
                    'lot1_price':  target,
                    'lot2_stop':   stop_loss,
                    'entry_reason': entry_reason,
                }
                capital_per_pos = min(self.capital * self.risk_frac, self.pos_cap)
                shares = int(capital_per_pos / entry_price)
                cost = shares * entry_price
                # 实盘现金检查：买入金额不能超过当前现金，且买完剩余不能低于 $1000
                if self.cash < cost or (self.cash - cost) < 1000:
                    # 放弃交易，不占持仓位
                    new_pending.pop(ticker, None)
                    return
                self.trade_id += 1
                self.positions[ticker]['trade_id'] = self.trade_id
                self.positions[ticker]['shares'] = shares  # 记录实际买入股数，供期末强平使用
                # 实盘现金日志
                self._record_tx(entry_date + " 09:30:00", 'BUY', ticker, shares, entry_price,
                               self.trade_id, hold_days=0, total_pnl=0)
                self._debug_record({
                    'trade_id':   self.trade_id,
                    'leg':        'lot1_buy',
                    'ticker':     ticker,
                    'lot1':       False,
                    'lot2':       False,
                    'entry_date': entry_date,
                    'entry_price': round(entry_price, 2),
                    'exit_date':  None,
                    'exit_price': None,
                    'shares':     round(shares, 4),
                    'capital_per_pos': round(capital_per_pos, 2),
                    'total_pnl':  None,
                    'stop_loss':  round(stop_loss, 2),
                    'target':     round(target, 2),
                    'atr':        round(atr, 2),
                    'stage':      stage,
                    'grade':      grade,
                    'rr_ratio':   rr.get('rr_ratio', 3.0),
                })
                new_pending[ticker] = None

            elif stage == 'STAGE_1' and not l5_veto:
                new_pending[ticker] = float(daily_bars[daily_idx]['high'])

    def _get_signal(self, ticker, bars_d, spy_bars, idx, prev_entry_price=None):
        eng = BuyFilterEngine(ticker, bars_d[:idx+1], spy_bars=spy_bars[:idx+1])
        return eng.run(bars_1h=None, daily_entry_price=prev_entry_price)

    def _post_exit_judge(self, h1_bars, exit_h1_idx, entry_price):
        future = h1_bars[exit_h1_idx+1:exit_h1_idx+25]
        closes = [float(b["close"]) for b in future if float(b["close"]) > 0]
        if not closes:
            return {'judge': 'N/A', 'note': '数据不足',
                    'post_5d_high': None, 'post_5d_low': None}
        max_c = max(closes); min_c = min(closes)
        judge = 'NORMAL'; note = ''
        if max_c > entry_price * 1.02:
            judge = 'SOLD_EARLY'; note = f'出场后25h最高+{((max_c/entry_price)-1)*100:.1f}%'
        elif min_c < entry_price * 0.98:
            judge = 'CORRECT_STOP'; note = f'出场后继续跌，最低{min_c:.2f}'
        return {'judge': judge, 'note': note,
                'post_5d_high': round(max_c, 2), 'post_5d_low': round(min_c, 2)}

    def _trade_record(self, ticker, pos, bar, exit_price, pnl_pct,
                      result, exit_reason, post, h1_idx, exit_rule=None, leg='lot2_sell',
                      lot1=False, lot2=False):
        meta = getattr(self, '_meta', {})
        capital_per_pos = min(self.capital * self.risk_frac, self.pos_cap)
        ep = pos['entry_price']
        shares = int(capital_per_pos / ep)
        total_pnl = shares * (exit_price - ep)
        return {
            'trade_id':    pos.get('trade_id', 0),
            'leg':         leg,
            'ticker':      ticker,
            'entry_date':  pos.get('entry_date', '?'),
            'exit_date':   bar.get("datetime", "?"),
            'entry_price': round(ep, 2),
            'exit_price':  round(exit_price, 2),
            'shares':       round(shares, 4),
            'capital_per_pos': round(capital_per_pos, 2),
            'total_pnl':    round(total_pnl, 2),
            'realized_profit': round(pos.get('realized_profit', 0.0), 2),
            'stop_loss':   round(pos['stop_loss'], 2),
            'target':      round(pos.get('target', 0), 2),
            'atr':         round(pos.get('atr', 0), 2),
            'rr_ratio':    pos.get('rr_ratio', 0),
            'pnl_pct':     round(pnl_pct, 2),
            'hold_h1':     h1_idx - pos.get('h1_entry_idx', h1_idx),
            'result':      result,
            'stage':       pos.get('stage', '?'),
            'grade':       pos.get('grade', '?'),
            'entry_l3_form': pos.get('entry_l3_form', '?'),
            'entry_l3_tier': pos.get('entry_l3_tier', 0),
            'entry_l4_pullback_done': pos.get('entry_l4_pullback_done', False),
            'entry_l5_rr': pos.get('entry_l5_rr', 0),
            'entry_l1_regime': pos.get('entry_l1_regime', '?'),
            'entry_reason': pos.get('entry_reason', ''),
            'lot1_done':   pos.get('lot1_done', False),
            'exit_reason': exit_reason,
            'exit_rule':   exit_rule,
            'lot1':        lot1,
            'lot2':        lot2,
            'post_judge':  post['judge'],
            'post_note':   post['note'],
            'post_5d_high': post.get('post_5d_high'),
            'post_5d_low':  post.get('post_5d_low'),
            'backtest_start': meta.get('start_year', '?'),
            'backtest_end':   meta.get('end_year', '?'),
            'stock_pool_size': meta.get('stock_pool_size', 0),
            'timeframe':     meta.get('timeframe', '1h'),
            'engine_version': 'h3-4-1',
        }

    def run(self, tickers, start_year=2025, end_year=2026, lookback=0):
        self._meta = {
            'start_year': start_year,
            'end_year': end_year,
            'stock_pool_size': len([t for t in tickers if t != 'SPY']),
            'timeframe': '1h',
            'engine_version': 'h3-4-1',
        }
        print(f'加载数据: {len(tickers)} 只...')

        all_daily = {}
        for t in tickers:
            bars = load_klines(t, lookback=lookback)
            if bars:
                all_daily[t] = bars

        all_h1 = {}
        for t in tickers:
            bars = load_klines_1h(t)
            if bars:
                all_h1[t] = bars

        if 'SPY' not in all_daily or 'SPY' not in all_h1:
            print('ERROR: SPY 数据不存在'); return {}

        spy_d  = all_daily['SPY']
        spy_h1 = all_h1['SPY']

        def in_year(b, y0, y1):
            yr = b["date"][:4]; return str(y0) <= yr <= str(y1)

        start_idx = next((i for i, b in enumerate(spy_d) if in_year(b, start_year, end_year)), None)
        end_idx   = next((i for i in range(len(spy_d)-1, -1, -1) if in_year(spy_d[i], start_year, end_year)), None)
        if start_idx is None or end_idx is None:
            print(f'未找到 {start_year}-{end_year} 日线数据'); return {}

        print(f'回测区间（日线）: {spy_d[start_idx]["date"]} → {spy_d[end_idx]["date"]}')
        print(f'SPY 日线: {len(spy_d)} bars | 小时K（RTH）: {len(spy_h1)} bars')
        print(f'入场: v2-1 STAGE_4 NOW（日线信号）')
        print(f'h3-4 出场: Lot1目标触达不卖出，止损上移至入场价保本')
        print(f'        Lot2: ATR_trailing OR 跌回入场价 → 全出')
        print(f'  ATR×={self.atr_mult} | ATR_trailing={self.atr_trailing_mult}×ATR | 最小持仓={self.min_hold}h')

        new_pending = {}
        for i in range(start_idx, end_idx + 1):
            for ticker in tickers:
                daily_bars = all_daily.get(ticker, [])
                h1_bars    = all_h1.get(ticker, [])
                if not daily_bars or not h1_bars:
                    continue
                if i >= len(daily_bars):
                    continue
                self._on_day(ticker, daily_bars, spy_d, h1_bars,
                             i, tickers, new_pending)

            # 权益快照（现金 + 持仓市值，含浮亏浮盈）
            self._record_equity(all_daily, spy_d, i)

        # 期末处理
        for ticker in list(self.positions):
            h1_bars = all_h1.get(ticker, [])
            pos = self.positions.get(ticker)
            if not pos:
                continue
            # 实际剩余持仓股数（lot1 卖出后只剩余 lot2_shares）
            if pos.get('lot1_done'):
                shares = pos.get('lot2_shares', pos.get('shares', 0))
                # lot1_done=True → lot1_sell 已在 _on_day 触发（由 _track_1h 补发），
                # END_BACKTEST 只补发 lot2_sell（若 h1_bars 耗尽导致 _track_1h 未跑完）
            else:
                shares = pos.get('shares', 0)
                # lot1_done=False → LOT1_TARGET 从未触发，lot1_sell 未发送，
                # END_BACKTEST 发送 lot2_sell（含完整仓位的保本/止损逻辑）

            if h1_bars:
                last_idx = len(h1_bars) - 1
                exit_price = float(h1_bars[last_idx]["close"])
                last_date = h1_bars[last_idx].get('datetime', '?')
                pnl_pct = (exit_price - pos['entry_price']) / pos['entry_price'] * 100
                post = self._post_exit_judge(h1_bars, last_idx, pos['entry_price'])
                # lot1_done=True → lot1_sell 已由 _track_1h 发出，不重复写
                if not pos.get('lot1_done'):
                    self._debug_record(self._trade_record(
                        ticker, pos, h1_bars[last_idx], exit_price, pnl_pct,
                        'END_BACKTEST', '回测结束平仓', post, last_idx,
                        exit_rule='END_BACKTEST', leg='lot2_sell',
                        lot1=False, lot2=False))
            else:
                # 无 h1_bars：用日线兜底
                daily_bars = all_daily.get(ticker, [])
                if daily_bars:
                    exit_price = float(daily_bars[-1]["close"])
                    last_date = daily_bars[-1].get('date', '?')
                    pnl_pct = (exit_price - pos['entry_price']) / pos['entry_price'] * 100
                else:
                    exit_price = pos['entry_price']
                    last_date = '?'
                    pnl_pct = 0.0
                # lot1_done=True → lot1_sell 已由 _on_day + _track_1h 发出，不重复写
                if not pos.get('lot1_done'):
                    self._debug_record(self._trade_record(
                        ticker, pos, daily_bars[-1] if daily_bars else None,
                        exit_price, pnl_pct,
                        'END_BACKTEST', '回测结束平仓', {}, 0,
                        exit_rule='END_BACKTEST', leg='lot2_sell',
                        lot1=False, lot2=False))

            pnl_dollar = shares * (exit_price - pos['entry_price'])
            # 现金日志：lot2_sell 金额（lot1_done=True 时只算剩余 lot2_shares 的部分）
            self._record_tx(
                last_date,
                'SELL', ticker, shares, exit_price,
                pos.get('trade_id', 0), 'END_BACKTEST',
                pnl_dollar,
                total_pnl=round(pnl_dollar + pos.get('realized_profit', 0.0), 2))

        self.positions.clear()

        result = self._summary()
        self.save()
        self._flush_trade_log()
        return result

    def _summary(self):
        if not self.history:
            print('无交易记录'); return {}
        # 过滤 lot1_buy 和非最终 exit
        lot2_records = [h for h in self.history
                        if h.get('leg') in ('lot2_sell', 'lot1_sell')]
        # 两条独立记录：lot1_sell（含LOT1_TARGET）和 lot2_sell 都保留
        final = {}
        for h in lot2_records:
            tid = h.get('trade_id', 0)
            if tid not in final:
                final[tid] = {}
            if h.get('leg') == 'lot1_sell':
                final[tid]['lot1'] = h
            else:
                final[tid]['lot2'] = h

        trades = []
        for tid, rec in final.items():
            if 'lot1' in rec:
                t1 = rec['lot1'].copy()
                t1['lot1_hit'] = True
                t1['_trade_id'] = tid
                trades.append(t1)
            if 'lot2' in rec:
                t2 = rec['lot2'].copy()
                t2['_trade_id'] = tid
                trades.append(t2)

        lot1_hit = len([h for h in self.history if h.get('leg') == 'lot1_buy'])
        total = lot1_hit
        # 按唯一 trade_id 计算 wins/loses（每笔入场只算一次）
        # lot1_hit 的交易：lot1_sell pnl_pct > 0 = win，lot2_sell 参考但不重复计算
        # lot1_miss 的交易：lot2_sell pnl_pct > 0 = win，否则 = loss
        tid_win = set()
        tid_lose = set()
        tid_lot1_hit = set()
        for h in trades:
            tid = h.get('_trade_id', h.get('trade_id', 0))
            if h.get('leg') == 'lot1_sell' and h.get('pnl_pct', 0) > 0:
                tid_lot1_hit.add(tid)
                tid_win.add(tid)  # lot1目标触达必然盈利
            elif h.get('leg') == 'lot2_sell':
                if tid in tid_lot1_hit:
                    # lot1已盈利，lot2随它——不重复计算
                    pass
                elif h.get('pnl_pct', 0) > 0:
                    tid_win.add(tid)
                else:
                    tid_lose.add(tid)
        wins_total = len(tid_win)
        loses_total = len(tid_lose)
        total_trades = len(tid_win) + len(tid_lose)
        wr = wins_total / total_trades * 100 if total_trades else 0
        # avg_win / avg_loss 从各 record 集合计算
        all_wins = [h for h in trades if h.get('_trade_id', h.get('trade_id', 0)) in tid_win]
        all_loses = [h for h in trades if h.get('_trade_id', h.get('trade_id', 0)) in tid_lose]
        avg_win = sum(h['pnl_pct'] for h in all_wins) / max(1, len(all_wins))
        avg_loss = sum(h['pnl_pct'] for h in all_loses) / max(1, len(all_loses))
        rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0

        grade_stats = defaultdict(lambda: {'count':0,'wins':0,'pnl_sum':0.0})
        for h in trades:
            g = h.get('grade', '?')
            grade_stats[g]['count'] += 1
            if h.get('pnl_pct', 0) > 0: grade_stats[g]['wins'] += 1
            grade_stats[g]['pnl_sum'] += h.get('pnl_pct', 0)
        for g in grade_stats:
            s = grade_stats[g]
            s['win_rate'] = s['wins'] / s['count'] * 100
            s['avg_pnl']  = s['pnl_sum'] / s['count']

        exit_stats = defaultdict(int)
        for h in trades:
            er = h.get('exit_rule', h.get('result', '?'))
            exit_stats[er] += 1

        lot1_count = len([h for h in trades if h.get('lot1_done', False)])

        print(f'\n========== h3-4 回测结果 ==========')
        final_cash = round(self.cash, 2)
        pnl_dollar = round(self.cash - self.initial, 2)
        return_pct = round(pnl_dollar / self.initial * 100, 2)

        # 权益口径回撤（含浮亏浮盈）：peak-to-trough on equity_curve
        eq_max_dd = 0.0
        eq_peak = self.initial
        for _snap in self.equity_curve:
            _eq = _snap['equity']
            if _eq > eq_peak:
                eq_peak = _eq
            if eq_peak > 0:
                eq_max_dd = max(eq_max_dd, (eq_peak - _eq) / eq_peak)

        print(f'总入场: {lot1_hit} 笔 | Lot1目标触达: {lot1_count} 笔 | 最终出场: {total} 笔')
        print(f'胜率: {wr:.1f}% | avg win: {avg_win:+.2f}% | avg loss: {avg_loss:+.2f}% | RR: {rr:.2f}')
        print(f'初始资金: ${self.initial:,.0f} → 期末现金: ${final_cash:,.2f} | 净盈亏: ${pnl_dollar:+,.2f} ({return_pct:+.1f}%) | 最大回撤(权益口径): {eq_max_dd*100:.1f}%')
        print(f'\n按评级:')
        for g in sorted(grade_stats.keys()):
            s = grade_stats[g]
            print(f'  {g}: {s["count"]}笔 win={s["win_rate"]:.0f}% avg={s["avg_pnl"]:+.2f}%')
        print(f'\n出场方式:')
        for rule, cnt in sorted(exit_stats.items(), key=lambda x: -x[1]):
            print(f'  {rule}: {cnt}笔')

        return {
            'initial_capital': self.initial,
            'final_cash': round(self.cash, 2),
            'total_pnl_dollar': round(self.cash - self.initial, 2),
            'return_pct': return_pct,
            'max_drawdown': round(eq_max_dd * 100, 2),
            'total': total, 'win_rate': round(wr, 2),
            'avg_win': round(avg_win, 2), 'avg_loss': round(avg_loss, 2),
            'win_loss_ratio': round(rr, 2),
            'lot1_hit': lot1_hit,
            'lot1_count': lot1_count,
            'grade_stats': {str(k): v for k, v in grade_stats.items()},
            'exit_stats': dict(exit_stats),
            'trades': trades,
        }


def _summarize_from_log(trades, engine_version='h3-4'):
    """从交易列表（含 from-log 读取的）生成统计报告"""
    if not trades:
        print('无交易记录'); return {}

    # 构建最终出场（每笔取最后一笔）
    final = {}
    for h in trades:
        tid = h.get('trade_id', 0)
        final[tid] = h
    trades = list(final.values())

    wins = [h for h in trades if h.get('pnl_pct', 0) > 0]
    total = len(trades)
    wr = len(wins) / total * 100 if total else 0
    avg_win  = sum(h.get('pnl_pct', 0) for h in wins) / max(1, len(wins))
    loses = [h for h in trades if h.get('pnl_pct', 0) <= 0]
    avg_loss = sum(h.get('pnl_pct', 0) for h in loses) / max(1, len(loses))
    rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    grade_stats = defaultdict(lambda: {'count': 0, 'wins': 0, 'pnl_sum': 0.0})
    for h in trades:
        g = str(h.get('grade', '?'))
        grade_stats[g]['count'] += 1
        if h.get('pnl_pct', 0) > 0:
            grade_stats[g]['wins'] += 1
        grade_stats[g]['pnl_sum'] += h.get('pnl_pct', 0)
    for g in grade_stats:
        s = grade_stats[g]
        s['win_rate'] = s['wins'] / s['count'] * 100
        s['avg_pnl']  = s['pnl_sum'] / s['count']

    exit_stats = defaultdict(int)
    for h in trades:
        exit_stats[h.get('exit_rule', h.get('result', '?'))] += 1

    lot1_hit = len([h for h in trades if h.get('leg') == 'lot1_buy'])
    lot1_count = len([h for h in trades if h.get('lot1_done', False)])

    print(f'\n========== {engine_version} 回测结果 ==========')
    print(f'总入场: {lot1_hit} 笔 | Lot1目标触达: {lot1_count} 笔 | 最终出场: {total} 笔')
    print(f'胜率: {wr:.1f}% | avg win: {avg_win:+.2f}% | avg loss: {avg_loss:+.2f}% | RR: {rr:.2f}')
    print(f'\n按评级:')
    for g in sorted(grade_stats.keys()):
        s = grade_stats[g]
        print(f'  {g}: {s["count"]}笔 win={s["win_rate"]:.0f}% avg={s["avg_pnl"]:+.2f}%')
    print(f'\n出场方式:')
    for rule, cnt in sorted(exit_stats.items(), key=lambda x: -x[1]):
        print(f'  {rule}: {cnt}笔')

    return {
        'total': total, 'win_rate': round(wr, 2),
        'avg_win': round(avg_win, 2), 'avg_loss': round(avg_loss, 2),
        'win_loss_ratio': round(rr, 2),
        'lot1_hit': lot1_hit,
        'lot1_count': lot1_count,
        'grade_stats': {str(k): v for k, v in grade_stats.items()},
        'exit_stats': dict(exit_stats),
        'trades': trades,
    }


def main():
    ap = argparse.ArgumentParser()
    ap = argparse.ArgumentParser()
    ap.add_argument('--tickers', nargs='*')
    ap.add_argument('--years', nargs=2, default=['2025', '2026'])
    ap.add_argument('--lookback', type=int, default=0)
    ap.add_argument('--max-pos', type=int, default=5)
    ap.add_argument('--capital', type=float, default=100_000)
    ap.add_argument('--from-2025', action='store_true')
    ap.add_argument('--atr-mult', type=float, default=1.5)
    ap.add_argument('--atr-trailing-mult', type=float, default=2.0)
    ap.add_argument('--min-hold', type=int, default=5)
    ap.add_argument('--target-mult', type=float, default=3.0)
    ap.add_argument('--risk-frac', type=float, default=0.20,
                   help='单仓位资金占比 (default 0.20)')
    ap.add_argument('--debug', action='store_true')
    ap.add_argument('--min-grade', type=str, default=None,
                   help='最低入场评级: A/B/C/D (None=不限制)')
    ap.add_argument('--from-log', type=str, default=None)
    ap.add_argument('--output', type=str, default=None)
    ap.add_argument('--tag', type=str, default=None,
                   help='输出文件标签，如 v1_trail3.0，不填则用时间戳')
    args = ap.parse_args()

    # ── 从日志读取模式 ─────────────────────────────────────────
    if args.from_log:
        log_path = Path(args.from_log)
        if not log_path.exists():
            print(f'ERROR: 日志文件不存在: {log_path}'); sys.exit(1)
        trades = []
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError:
                    print(f'WARN: 跳过非法JSON行: {line[:60]}')
                    continue
        if not trades:
            print('ERROR: 日志文件为空'); sys.exit(1)
        version = 'h3-4'
        if 'engine_version' in trades[0]:
            version = trades[0].get('engine_version', 'h3-4')
        print(f'从日志加载 {len(trades)} 笔交易: {log_path.name}')
        _summarize_from_log(trades, engine_version=version)
        sys.exit(0)

    pool_file = BASE / '..' / 'TradingAgents' / 'fintech' / 'stock_pool.json'
    if pool_file.exists():
        with open(pool_file) as f:
            pool = json.load(f)
        tickers = [s['code'] for s in pool.get('stocks', [])]
        for sym in pool.get('_special_symbols', {}):
            if sym not in tickers:
                tickers.append(sym)
    else:
        tickers = []
    tickers = [t for t in tickers if t not in {'TNX', 'DXY', '^VIX'}]

    if getattr(args, 'from_2025', False):
        from p_buy_filter_v2 import load_klines as lk
        filtered = []
        for t in tickers:
            h1 = lk(t, interval='1h', lookback=2000)
            if h1 and len(h1) >= 100:
                filtered.append(t)
        print(f'有小时K数据的股票: {len(filtered)} 只')
        tickers = filtered

    if args.tickers:
        tickers = [t for t in args.tickers if t in tickers]
        if not tickers:
            print('ERROR: 无有效股票'); sys.exit(1)

    if 'SPY' not in tickers:
        tickers.insert(0, 'SPY')

    sy, ey = int(args.years[0]), int(args.years[1])
    print(f'h3-4 回测: {tickers[:5]}{"..." if len(tickers)>5 else ""} | {sy}-{ey}')
    print(f'ATR×={args.atr_mult} | ATR_trailing={args.atr_trailing_mult}×ATR | 最小持仓={args.min_hold}h | 目标={args.target_mult}×ATR\n')

    bt = Backtester1hV5(
        initial_capital=args.capital,
        max_positions=args.max_pos,
        atr_mult=args.atr_mult,
        atr_trailing_mult=args.atr_trailing_mult,
        min_hold=args.min_hold,
        target_mult=args.target_mult,
        min_grade=args.min_grade,
        risk_frac=args.risk_frac,
    )

    # debug 模式：写 JSONL
    if args.debug:
        log_dir = BASE / 'htrade' / 'logs'
        log_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        lp = log_dir / f'trades_h3_4_1_{ts}.jsonl'
        bt._journal_path = str(lp)
        bt._trade_jsonl_path = str(log_dir / f'trades_h3_4_1_{ts}.trade.jsonl')

    result = bt.run(tickers, start_year=sy, end_year=ey, lookback=args.lookback)

    if args.debug and result:
        print(f'  [debug] 写入 {len(bt.history)} 笔日志: {lp.name}')

    if result:
        if args.tag:
            out = BASE / 'backtest' / 'results' / f'results_h3_4_1_{args.tag}.json'
            excel_src = Path(__file__).resolve().parent / 'trade_log_h341_live.xlsx'
            excel_dst = BASE / 'backtest' / 'results' / f'trade_log_h341_{args.tag}.xlsx'
            import os, shutil
            os.makedirs(BASE / 'backtest' / 'results', exist_ok=True)
            if excel_src.exists():
                shutil.copy2(excel_src, excel_dst)
                print(f'交割单已保存: {excel_dst}')
        else:
            out = Path(args.output) if args.output else (BASE / 'htrade' / f'results_h3_4_1_{sy}_{ey}.json')
        with open(out, 'w') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f'\n结果已保存: {out}')


if __name__ == '__main__':
    main()
