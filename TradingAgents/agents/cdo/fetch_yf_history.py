#!/usr/bin/env python3
"""
CDO 美股数据获取 - Yahoo Finance 历史数据抓取
通过 Chrome CDP 浏览器访问 Yahoo Finance，获取 QQQ/SPY 的 K 线数据
"""

import os
import json
import time
from datetime import datetime
from playwright.sync_api import sync_playwright

CHROME_DEBUG_URL = "http://172.25.192.1:19222"
PROJECT_ROOT = "/home/yudengfeng/.openclaw/workspace/美股投资洞察分析"
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "中间过程", "klines")
os.makedirs(OUTPUT_DIR, exist_ok=True)

TICKERS = ["QQQ", "SPY"]

# Yahoo Finance 历史数据页面 URL 模板
HISTORY_URL = "https://finance.yahoo.com/quote/{ticker}/history/"


def parse_history_table(page) -> list:
    """解析 Yahoo Finance 历史数据表格"""
    rows = []
    try:
        # 尝试找到表格
        table = page.locator("table")
        if table.count() == 0:
            # 尝试其他选择器
            table = page.locator("[data-test='historical-prices']")
        
        # 获取所有行
        tbody = table.locator("tbody tr") if table.count() > 0 else page.locator("tr")
        
        for row in tbody.all():
            cells = row.locator("td")
            if cells.count() >= 6:
                date_text = cells.nth(0).inner_text().strip()
                open_val = cells.nth(1).inner_text().strip()
                high_val = cells.nth(2).inner_text().strip()
                low_val = cells.nth(3).inner_text().strip()
                close_val = cells.nth(4).inner_text().strip()
                volume_val = cells.nth(5).inner_text().strip()
                
                # 跳过非数据行（分红、拆股等事件）
                if not date_text or date_text.startswith("Date"):
                    continue
                if "Dividend" in date_text or "Stock Split" in date_text:
                    continue
                
                rows.append({
                    "date": date_text,
                    "open": open_val,
                    "high": high_val,
                    "low": low_val,
                    "close": close_val,
                    "volume": volume_val
                })
    except Exception as e:
        print(f"    解析表格出错: {e}")
    return rows


def fetch_ticker_history_cdp(ticker: str, period: str = "3y") -> list:
    """
    通过 CDP 浏览器获取 Yahoo Finance 历史数据
    period: 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max
    """
    url = f"https://finance.yahoo.com/quote/{ticker}/history/?period1=1167609600&period2={int(datetime.now().timestamp())}"
    
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CHROME_DEBUG_URL)
        ctx = browser.contexts[0]
        page = ctx.new_page()
        
        print(f"  访问 {url}")
        page.goto(url, wait_until="load", timeout=30000)
        time.sleep(5)
        
        # 尝试点击下载按钮获取完整数据
        # Yahoo Finance 有下载CSV功能
        try:
            download_btn = page.locator("a[data-test='download-link']")
            if download_btn.count() > 0:
                print(f"  找到下载链接")
        except:
            pass
        
        # 解析表格
        rows = parse_history_table(page)
        
        print(f"  获取到 {len(rows)} 条数据")
        
        browser.close()
        return rows


def save_json(ticker: str, interval: str, data: list):
    """保存为 JSON"""
    if not data:
        return
    
    filepath = os.path.join(OUTPUT_DIR, f"{ticker}_{interval}.json")
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump({
            "ticker": ticker,
            "interval": interval,
            "count": len(data),
            "data": data
        }, f, ensure_ascii=False, indent=2)
    print(f"  💾 已保存: {filepath}")


def run():
    print("=" * 60)
    print(f"📊 CDO Yahoo Finance 数据获取")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    for ticker in TICKERS:
        print(f"\n▶️ 处理 {ticker}:")
        
        # 获取日K（3年）
        print(f"  获取日K (3年)...")
        daily_data = fetch_ticker_history_cdp(ticker, period="3y")
        save_json(ticker, "1d", daily_data)
        
        time.sleep(2)
    
    print("\n" + "=" * 60)
    print("✅ 获取完成！")
    print("=" * 60)


if __name__ == "__main__":
    run()
