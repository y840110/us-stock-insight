#!/usr/bin/env python3
"""
CDO 美股数据获取 - Yahoo Finance 历史数据抓取（完整版）
通过 Chrome CDP 浏览器访问 Yahoo Finance 页面，解析 K 线数据
"""

import os
import json
import time
import re
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

CHROME_DEBUG_URL = "http://172.25.192.1:19222"
PROJECT_ROOT = "/home/yudengfeng/.openclaw/workspace/美股投资洞察分析"
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "中间过程", "klines")
os.makedirs(OUTPUT_DIR, exist_ok=True)

TICKERS = ["QQQ", "SPY"]


def parse_page_text(text: str) -> list:
    """
    解析 Yahoo Finance 历史页面文本
    数据格式: Date\tOpen\tHigh\tLow\tClose\tAdj Close\tVolume
    分隔符是 \t（Tab）
    """
    data_rows = []
    lines = text.split('\n')
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        
        # 尝试 Tab 分隔
        parts = line.split('\t')
        
        # 标准数据行: Date Open High Low Close AdjClose Volume (7列)
        # 或 (6列，无AdjClose)
        if len(parts) >= 6:
            date_str = parts[0].strip()
            
            # 跳过标题行
            if date_str.lower() in ['date', '']:
                continue
            
            # 跳过事件行（分红、拆股）
            if 'Dividend' in line or 'Stock Split' in line or 'Split' in line:
                continue
            
            # 验证日期格式: "May 6, 2026"
            if not re.match(r'[A-Z][a-z]{2} \d{1,2}, \d{4}', date_str):
                continue
            
            # 解析数值
            try:
                open_v = parts[1].strip()
                high_v = parts[2].strip()
                low_v = parts[3].strip()
                close_v = parts[4].strip()
                adj_close_v = parts[5].strip() if len(parts) > 5 else close_v
                volume_v = parts[6].strip() if len(parts) > 6 else '0'
                
                # 验证数值有效性
                float(open_v.replace(',', ''))
                float(close_v.replace(',', ''))
                
                data_rows.append({
                    "date": date_str,
                    "open": open_v,
                    "high": high_v,
                    "low": low_v,
                    "close": close_v,
                    "adj_close": adj_close_v,
                    "volume": volume_v
                })
            except (ValueError, IndexError):
                continue
    
    return data_rows


def fetch_ticker_history(ticker: str, days_back: int = 1095) -> list:
    """
    通过 CDP 获取 Yahoo Finance 历史数据
    days_back: 回溯天数（1095 ≈ 3年）
    """
    period1 = int((datetime.now() - timedelta(days=days_back)).timestamp())
    period2 = int(datetime.now().timestamp())
    
    url = f"https://finance.yahoo.com/quote/{ticker}/history/?period1={period1}&period2={period2}"
    
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CHROME_DEBUG_URL)
        ctx = browser.contexts[0]
        page = ctx.new_page()
        
        print(f"  访问: {url}")
        page.goto(url, wait_until="load", timeout=30000)
        time.sleep(5)
        
        # 多次滚动加载所有数据
        for _ in range(10):
            page.keyboard.press('End')
            time.sleep(1)
        
        text = page.locator('body').inner_text()
        rows = parse_page_text(text)
        
        print(f"  解析到 {len(rows)} 条数据")
        
        browser.close()
        return rows


def fetch_weekly_history(ticker: str, years_back: int = 10) -> list:
    """
    获取周K数据（10年）
    Yahoo Finance 周K需要在 URL 中设置 frequency 参数
    """
    period1 = int((datetime.now() - timedelta(days=years_back * 365)).timestamp())
    period2 = int(datetime.now().timestamp())
    
    # frequency=weekly
    url = (f"https://finance.yahoo.com/quote/{ticker}/history/"
           f"?period1={period1}&period2={period2}&frequency=weekly")
    
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CHROME_DEBUG_URL)
        ctx = browser.contexts[0]
        page = ctx.new_page()
        
        print(f"  访问: {url}")
        page.goto(url, wait_until="load", timeout=30000)
        time.sleep(5)
        
        for _ in range(10):
            page.keyboard.press('End')
            time.sleep(1)
        
        text = page.locator('body').inner_text()
        rows = parse_page_text(text)
        
        print(f"  解析到 {len(rows)} 条周K数据")
        
        browser.close()
        return rows


def save_json(ticker: str, interval: str, data: list):
    if not data:
        print(f"  ⚠️ 无数据，跳过保存")
        return
    
    filepath = os.path.join(OUTPUT_DIR, f"{ticker}_{interval}.json")
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump({
            "ticker": ticker,
            "interval": interval,
            "count": len(data),
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data": data
        }, f, ensure_ascii=False, indent=2)
    print(f"  💾 已保存: {filepath}")
    print(f"     最新: {data[0]['date']} close={data[0]['close']}")
    print(f"     最老: {data[-1]['date']} close={data[-1]['close']}")


def run():
    print("=" * 60)
    print(f"📊 CDO 美股数据获取 - Yahoo Finance (CDP)")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"   输出: {OUTPUT_DIR}")
    print("=" * 60)
    
    for ticker in TICKERS:
        print(f"\n▶️ {ticker}:")
        
        # 日K（3年）
        print(f"  获取日K (近3年)...")
        daily_data = fetch_ticker_history(ticker, days_back=1095)
        save_json(ticker, "1d", daily_data)
        
        time.sleep(3)
        
        # 周K（10年）
        print(f"  获取周K (近10年)...")
        weekly_data = fetch_weekly_history(ticker, years_back=10)
        save_json(ticker, "1wk", weekly_data)
        
        time.sleep(3)
    
    print("\n" + "=" * 60)
    print("✅ 获取完成！")
    print("=" * 60)


if __name__ == "__main__":
    run()
