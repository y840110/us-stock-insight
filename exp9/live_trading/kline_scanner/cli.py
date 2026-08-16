#!/usr/bin/env python3
import argparse
import sys
import json
from datetime import datetime
from pathlib import Path

SELF = Path(__file__).resolve()
sys.path.insert(0, str(SELF.parent.parent))

from kline_scanner.scanner import ScannerEngine

def main():
    parser = argparse.ArgumentParser(description="Kline Scanner")
    parser.add_argument("--ticker", required=True, help="Ticker symbol")        
    parser.add_argument("--start-date", help="Start date YYYY-MM-DD")
    args = parser.parse_args()

    scanner = ScannerEngine()
    result = scanner.scan(args.ticker, args.start_date)

    if result:
        # 使用scan方法返回的合并后交易记录保存
        merged_trades = result["trades"]  # scan方法已经合并了交易
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_dir = SELF.parent / "scan_results"
        result_dir.mkdir(exist_ok=True)
        result_file = result_dir / f"{args.ticker}_{timestamp}.json"
        
        for trade in merged_trades:
            trade['ticker'] = args.ticker
            
        save_result = {
            "ticker": args.ticker,
            "timestamp": datetime.now().isoformat(),
            "total_bars": len(result["logs"]),
            "total_trades": len(merged_trades),
            "logs": result["logs"],
            "trades": merged_trades
        }
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(save_result, f, indent=2, ensure_ascii=False)
        
        print("Scan complete:", args.ticker)
        print("Trades:", len(merged_trades))
        print("Saved:", result_file)
    else:
        print("Failed to load data", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
