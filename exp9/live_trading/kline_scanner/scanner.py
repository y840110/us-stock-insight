#!/usr/bin/env python3
from .position_manager import PositionManager
from .engine_wrapper import EngineWrapper
from .data_loader import DataLoader
from .logger import ScannerLogger


class ScannerEngine:
    def __init__(self):
        self.position_manager = PositionManager()
        self.engine = EngineWrapper()
        self.data_loader = DataLoader()
        self.logger = ScannerLogger()

    def scan(self, ticker, start_date=None):
        self.logger.clear()
        daily_bars = self.data_loader.load_daily_bars(ticker)
        h1_bars = self.data_loader.load_h1_bars(ticker)
        spy_bars = self.data_loader.load_spy_bars()

        if not daily_bars:
            return None

        start_idx = self.data_loader.find_start_index(daily_bars, start_date)   
        self.position_manager = PositionManager()
        self.engine.reset_pending()  # 重置pending状态

        for bar_idx in range(start_idx, len(daily_bars)):
            bar = daily_bars[bar_idx]
            bar_time = bar.get('date', '')
            bar_price = float(bar.get('close', 0))

            if self.position_manager.is_in_position():
                self._process_in_position(ticker, bar_idx, bar_time, bar_price, daily_bars, h1_bars)
            else:
                self._process_no_position(ticker, bar_idx, bar_time, bar_price, daily_bars, spy_bars, h1_bars)

        # 合并交易记录
        merged_trades = self._merge_trades()
        return {'ticker': ticker, 'logs': self.logger.logs, 'trades': merged_trades}

    def _merge_trades(self):
        trades = self.logger.trades
        if not trades:
            return trades
        
        print(f"DEBUG: _merge_trades called, original trades: {len(trades)}")
        
        groups = {}
        for trade in trades:
            key = (trade['entry_date'], round(trade['entry_price'], 2))
            if key not in groups:
                groups[key] = []
            groups[key].append(trade)
        
        print(f"DEBUG: groups: {len(groups)}")
        
        merged = []
        trade_id = 1
        for key, group_trades in groups.items():
            if len(group_trades) == 1:
                trade = group_trades[0].copy()
                trade['trade_id'] = trade_id
                merged.append(trade)
                trade_id += 1
            else:
                entry_date, entry_price = key
                total_pnl = sum(t['pnl_pct'] for t in group_trades) / 2
                exit_date = max(t['exit_date'] for t in group_trades)
                exit_price = group_trades[-1]['exit_price']
                
                reasons = [t['exit_reason'] for t in group_trades]
                if 'LOT2_ATR_TRAILING' in reasons:
                    exit_reason = 'LOT2_ATR_TRAILING'
                elif 'LOT1_TARGET' in reasons:
                    exit_reason = 'LOT1_TARGET'
                else:
                    exit_reason = reasons[-1]
                
                result = 'WIN' if total_pnl > 0 else 'LOSS' if total_pnl < 0 else 'BREAK_EVEN'
                
                merged.append({
                    "trade_id": trade_id,
                    "ticker": "",
                    "entry_date": entry_date,
                    "exit_date": exit_date,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_pct": round(total_pnl, 2),
                    "result": result,
                    "exit_reason": exit_reason,
                    "stage": "STAGE_4",
                    "grade": "A"
                })
                trade_id += 1
        
        print(f"DEBUG: merged trades: {len(merged)}")
        return merged

    def _process_in_position(self, ticker, bar_idx, bar_time, bar_price, daily_bars, h1_bars):
        """完全复刻回测引擎的持仓追踪逻辑"""
        position_info = self.position_manager.get_position_info()
        position_info['ticker'] = ticker

        # 找到今日对应的小时K范围（完全复刻回测逻辑）
        today_date = daily_bars[bar_idx]['date']
        today_h1_end = None
        for i in range(len(h1_bars) - 1, -1, -1):
            if h1_bars[i].get('datetime', '')[:10] == today_date[:10]:
                today_h1_end = i
                break
        if today_h1_end is None:
            self.logger.log_bar(bar_time, bar_idx, 'HOLD', 'HOLD_NO_H1', bar_price)
            return

        entry_h1_idx = self.position_manager.h1_entry_idx
        entry_h1_idx = max(0, min(entry_h1_idx, len(h1_bars)-1))

        # 找到今日小时K的起始位置
        today_h1_start = None
        for i in range(entry_h1_idx + 1, today_h1_end + 1):
            if h1_bars[i].get('datetime', '')[:10] == today_date[:10]:
                today_h1_start = i
                break
        if today_h1_start is None:
            today_h1_start = entry_h1_idx + 1

        # 逐小时K追踪（完全复刻回测逻辑）
        lot1_recorded = False  # 防止重复记录LOT1_TARGET
        for h1_idx in range(today_h1_start, today_h1_end + 1):
            try:
                result = self.engine.evaluate_position(position_info, h1_bars, entry_h1_idx, h1_idx)
                action = result.get('action', 'HOLD')

                if action == 'LOT1_HIT':
                    # h3-4-1核心：Lot1目标触达，不卖出，止损上移至入场价        
                    self.position_manager.update_stop_loss(result.get('new_stop', position_info['entry_price']))
                    # 关键：强制设置peak_price为当前高点（与回测引擎一致）
                    self.position_manager.set_peak_price(result.get('peak_price', bar_price))
                    self.position_manager.mark_lot1_done()
                    
                    # 关键：更新h1_entry_idx（与回测引擎一致）
                    self.position_manager.h1_entry_idx = h1_idx
                    
                    # 只记录一次LOT1_TARGET
                    if not lot1_recorded:
                        lot1_recorded = True
                        h1_bar = h1_bars[h1_idx]
                        exit_time = h1_bar.get('datetime', bar_time)
                        
                        # 记录Lot1目标触达（不退出）
                        self.logger.log_trade(
                            entry_time=position_info.get('entry_time', ''),
                            entry_price=position_info.get('entry_price', 0),        
                            exit_time=exit_time,
                            exit_price=result.get('exit_price', 0),
                            profit_pct=((result.get('exit_price', 0) - position_info.get('entry_price', 1)) / position_info.get('entry_price', 1)) * 100,
                            reason='LOT1_TARGET'
                        )
                        self.logger.log_bar(bar_time, bar_idx, 'LOT1_HIT', 'LOT1_TARGET', bar_price)
                    # 不return，继续追踪Lot2

                elif action in ['STOP_OUT', 'EXIT']:
                    # 真正退出
                    h1_bar = h1_bars[h1_idx]
                    exit_time = h1_bar.get('datetime', bar_time)
                    exit_price = result.get('exit_price', bar_price)

                    pnl_pct = ((exit_price - position_info.get('entry_price', 1)) / position_info.get('entry_price', 1)) * 100

                    self.logger.log_trade(
                        entry_time=position_info.get('entry_time', ''),
                        entry_price=position_info.get('entry_price', 0),        
                        exit_time=exit_time,
                        exit_price=exit_price,
                        profit_pct=pnl_pct,
                        reason=result.get('reason', 'UNKNOWN')
                    )
                    self.position_manager.exit(exit_price, action, exit_time)   
                    self.logger.log_bar(bar_time, bar_idx, action, result.get('reason', 'EXIT'), bar_price)
                    return  # 退出后返回

                elif action == 'HOLD':
                    # 更新峰值
                    self.position_manager.update_max_price(result.get('peak_price', bar_price))
                    # 更新止损
                    if result.get('current_stop'):
                        self.position_manager.update_stop_loss(result.get('current_stop'))

            except Exception as e:
                self.logger.log_bar(bar_time, bar_idx, 'ERROR', str(e), bar_price)

        self.logger.log_bar(bar_time, bar_idx, 'HOLD', 'HOLD', bar_price)       

    def _process_no_position(self, ticker, bar_idx, bar_time, bar_price, daily_bars, spy_bars, h1_bars):
        """完全复刻回测引擎的入场逻辑"""
        try:
            # 传入daily_idx参数（关键！）
            result = self.engine.evaluate(ticker, daily_bars, spy_bars, h1_bars, bar_idx)
            signal = result.get('signal', 'NO_SIGNAL')

            if signal == 'BUY_NOW':
                # 使用次日开盘价作为入场价（回测核心逻辑）
                entry_price = result.get('entry', bar_price)

                entry_date = result.get('entry_date', bar_time)
                h1_entry_idx = 0
                for i in range(len(h1_bars)):
                    if h1_bars[i].get('datetime', '')[:10] == entry_date[:10]:  
                        h1_entry_idx = i
                        break

                self.position_manager.enter(
                    entry_price,
                    result.get('stop'),
                    result.get('target'),
                    entry_date,
                    bar_idx,
                    atr=result.get('atr'),
                    stage=result.get('stage'),
                    grade=result.get('grade'),
                    h1_entry_idx=h1_entry_idx
                )
                self.logger.log_bar(entry_date, bar_idx, 'BUY_NOW', 'BUY', entry_price)
            else:
                self.logger.log_bar(bar_time, bar_idx, signal, None, bar_price) 
        except Exception as e:
            self.logger.log_bar(bar_time, bar_idx, 'ERROR', str(e), bar_price)  

    def save_results(self, ticker):
        return self.logger.save_results(ticker)