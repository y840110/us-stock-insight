#!/usr/bin/env python3
import json
from datetime import datetime
from pathlib import Path


class ScannerLogger:
    def __init__(self):
        self.logs = []
        self.trades = []
        self.base_path = Path(__file__).resolve().parent
        self.trade_id_counter = 0

    def clear(self):
        self.logs = []
        self.trades = []
        self.trade_id_counter = 0

    def log_bar(self, bar_time, bar_index, signal, action=None, price=None):    
        self.logs.append({
            "time": bar_time,
            "bar_index": bar_index,
            "signal": signal,
            "action": action,
            "price": price
        })

    def log_trade(self, entry_time, entry_price, exit_time, exit_price, profit_pct, reason):
        self.trade_id_counter += 1
        # 使用与回测一致的字段命名
        result = 'WIN' if profit_pct > 0 else 'LOSS' if profit_pct < 0 else 'BREAK_EVEN'
        
        self.trades.append({
            "trade_id": self.trade_id_counter,
            "ticker": "",  # 将在save_results时填充
            "entry_date": entry_time,
            "exit_date": exit_time,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl_pct": profit_pct,
            "result": result,
            "exit_reason": reason,
            "stage": "STAGE_4",
            "grade": "A"
        })

    def save_results(self, ticker):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_dir = self.base_path / "scan_results"
        result_dir.mkdir(exist_ok=True)
        result_file = result_dir / f"{ticker}_{timestamp}.json"
        
        # 为每个交易填充ticker
        for trade in self.trades:
            trade['ticker'] = ticker
            
        result = {
            "ticker": ticker,
            "timestamp": datetime.now().isoformat(),
            "total_bars": len(self.logs),
            "total_trades": len(self.trades),
            "logs": self.logs,
            "trades": self.trades
        }
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        return str(result_file)
