#!/usr/bin/env python3
import pandas as pd
import json
from pathlib import Path

backtest_file = "trade_log_h341_live.xlsx"
print("=== 回测交易记录 ===")
print("=" * 80)

df = pd.read_excel(backtest_file)
df_nvda = df[df["ticker"] == "NVDA"].copy()
df_aapl = df[df["ticker"] == "AAPL"].copy()

print(f"NVDA 回测: {len(df_nvda)}笔")
for _, row in df_nvda.iterrows():
    entry_time = str(row["entry_time"])[:10]
    exit_time = str(row["exit_time"])[:10]
    print(f"  {entry_time} | 入:{row["entry_price"]:.2f} | 出:{row["exit_price"]:.2f} | {row["reason"]} | {row["pnl_pct"]:.2f}%")

print(f"
AAPL 回测: {len(df_aapl)}笔")
for _, row in df_aapl.iterrows():
    entry_time = str(row["entry_time"])[:10]
    exit_time = str(row["exit_time"])[:10]
    print(f"  {entry_time} | 入:{row["entry_price"]:.2f} | 出:{row["exit_price"]:.2f} | {row["reason"]} | {row["pnl_pct"]:.2f}%")

scan_dir = Path("kline_scanner/scan_results")
for ticker in ["NVDA", "AAPL"]:
    scan_files = sorted(scan_dir.glob(f"{ticker}_*.json"))
    if scan_files:
        latest = scan_files[-1]
        with open(latest) as f:
            data = json.load(f)
        trades = data.get("trades", [])
        print(f"
{ticker} 逐K分析: {len(trades)}笔")
        for t in trades:
            entry_time = t.get("entry_time", "N/A")[:10]
            exit_time = t.get("exit_time", "N/A")[:10]
            print(f"  {entry_time} | 入:{t.get("entry_price", 0):.2f} | 出:{t.get("exit_price", 0):.2f} | {t.get("reason", "N/A")} | {t.get("profit_pct", 0):.2f}%")
