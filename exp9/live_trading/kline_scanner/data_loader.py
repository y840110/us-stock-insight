#!/usr/bin/env python3
import json
from pathlib import Path


class DataLoader:
    def __init__(self):
        self.base_path = Path(__file__).resolve().parent.parent.parent.parent
        self.klines_dir = self.base_path / "TradingAgents" / "中间过程" / "klines"

    def load_daily_bars(self, ticker):
        return self._load_bars(ticker, "1d")

    def load_h1_bars(self, ticker):
        return self._load_bars(ticker, "1h")

    def load_spy_bars(self):
        return self.load_daily_bars("SPY")

    def _load_bars(self, ticker, freq):
        file_path = self.klines_dir / f"{ticker}_{freq}.json"
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 支持多种数据格式
            if isinstance(data, list):
                return data
            return data.get("data", data.get("bars", data))
        except Exception as e:
            print(f"Error loading {ticker}_{freq}: {e}")
            return None

    def find_start_index(self, bars, start_date):
        if not bars:
            return 0
        if not start_date:
            return 0
        for i, bar in enumerate(bars):
            if isinstance(bar, dict):
                date_val = bar.get("date")
                if date_val and isinstance(date_val, str) and date_val.startswith(start_date):
                    return i
        return 0
