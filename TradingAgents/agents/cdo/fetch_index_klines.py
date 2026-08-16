#!/usr/bin/env python3
"""
CDO 数据获取：QQQ & SPY 日K（3年）+ 周K（10年）
数据来源：Yahoo Finance (yfinance)
保存路径：中间过程/klines/
"""

import yfinance as yf
import pandas as pd
import json
import os
from datetime import datetime, timedelta

PROJECT_ROOT = "/home/yudengfeng/.openclaw/workspace/美股投资洞察分析"
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "TradingAgents", "中间过程", "klines")
os.makedirs(OUTPUT_DIR, exist_ok=True)

TICKERS = ["QQQ", "SPY"]
NOW = datetime.now()


def fetch_klines(ticker: str, period: str, interval: str) -> pd.DataFrame:
    """获取 K 线数据"""
    print(f"  正在获取 {ticker} {interval} K线 ({period})...")
    try:
        data = yf.download(ticker, period=period, interval=interval, progress=False)
        if data.empty:
            print(f"  ⚠️ {ticker} {interval} 无数据")
            return pd.DataFrame()
        print(f"  ✅ 获取成功: {len(data)} 根K线")
        return data
    except Exception as e:
        print(f"  ❌ 错误: {e}")
        return pd.DataFrame()


def save_klines(ticker: str, interval: str, df: pd.DataFrame):
    """保存 K 线数据为 JSON（带 time 字段）"""
    if df.empty:
        return

    # 重置索引，将 Date 转为 time 字段
    df = df.reset_index()
    if 'Date' in df.columns:
        df.rename(columns={'Date': 'time'}, inplace=True)
    elif 'Datetime' in df.columns:
        df.rename(columns={'Datetime': 'time'}, inplace=True)

    # time 转为字符串
    df['time'] = df['time'].astype(str)

    # 多层列名展平（yfinance 返回 MultiIndex）
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    records = df.to_dict(orient='records')

    filename = f"{ticker}_{interval}.json"
    filepath = os.path.join(OUTPUT_DIR, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump({
            "ticker": ticker,
            "interval": interval,
            "count": len(records),
            "data": records
        }, f, ensure_ascii=False, indent=2)

    print(f"  💾 已保存: {filepath}")


def run():
    print("=" * 60)
    print(f"📊 CDO 数据获取任务 - {NOW.strftime('%Y-%m-%d %H:%M')}")
    print(f"   输出目录: {OUTPUT_DIR}")
    print("=" * 60)

    results = {}

    for ticker in TICKERS:
        print(f"\n▶️ 处理 {ticker}:")

        # 日K：近3年
        df_daily = fetch_klines(ticker, period="3y", interval="1d")
        save_klines(ticker, "1d", df_daily)

        # 周K：近10年
        df_weekly = fetch_klines(ticker, period="10y", interval="1wk")
        save_klines(ticker, "1wk", df_weekly)

        results[ticker] = {
            "daily_count": len(df_daily),
            "weekly_count": len(df_weekly)
        }

    print("\n" + "=" * 60)
    print("✅ 获取完成！")
    for ticker, info in results.items():
        print(f"  {ticker}: 日K {info['daily_count']}根, 周K {info['weekly_count']}根")
    print("=" * 60)


if __name__ == "__main__":
    run()
