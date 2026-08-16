#!/usr/bin/env python3
"""
CDO K-line Downloader - Uses Playwright CDP to Chrome for Yahoo Finance data
Downloads 1d, 1wk, 1mo intervals for given tickers
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright
from datetime import datetime

# Config
CDP_URL = "http://172.25.192.1:19222"
OUTPUT_DIR = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/中间过程/klines")

# Full ticker list (deduped)
ALL_TICKERS = sorted(set([
    # TOP5
    "ANET", "PLTR", "IONQ", "MU", "COHR",
    # 趋势跟随
    "MCHP", "SWKS", "NET", "DDOG", "SMCI",
    # 超跌反弹
    "SNOW", "WDC",
    # 波段突破
    "QUBT", "RGTI", "PANW", "CRWD", "ZS",
    # ETF
    "SOXX", "ROBO", "QT",
]))

# Yahoo Finance URL templates
INTERVALS = {
    "1d": ("1d", "365d"),
    "1wk": ("1wk", "365d"),
    "1mo": ("1mo", "730d"),
}


def parse_yahoo_chart(response_text: str, ticker: str, interval: str) -> dict:
    """Parse Yahoo Finance chart API response"""
    try:
        data = json.loads(response_text)
        chart = data.get("chart", {}).get("result", [None])[0]
        if not chart:
            return None
        
        timestamps = chart.get("timestamp", [])
        indicators = chart.get("indicators", {}).get("quote", [{}])[0]
        
        quotes = chart.get("indicators", {}).get("quote", [{}])
        quote = quotes[0] if quotes else {}
        
        opens = quote.get("open", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        closes = quote.get("close", [])
        volumes = quote.get("volume", [])
        
        # Adj close
        adj_close = chart.get("indicators", {}).get("adjclose", [{}])
        adj_closes = adj_close[0].get("adjclose", []) if adj_close else []
        
        rows = []
        for i, ts in enumerate(timestamps):
            dt = datetime.fromtimestamp(ts)
            date_str = dt.strftime("%b %d, %Y")
            ymd_str = dt.strftime("%Y-%m-%d")
            
            rows.append({
                "date": date_str,
                "ymd": ymd_str,
                "open": f"{opens[i]:.2f}" if opens[i] is not None else None,
                "high": f"{highs[i]:.2f}" if highs[i] is not None else None,
                "low": f"{lows[i]:.2f}" if lows[i] is not None else None,
                "close": f"{closes[i]:.2f}" if closes[i] is not None else None,
                "adjclose": f"{adj_closes[i]:.2f}" if i < len(adj_closes) and adj_closes[i] is not None else None,
                "vol": int(volumes[i]) if volumes[i] is not None else 0,
            })
        
        return {
            "ticker": ticker,
            "interval": interval,
            "count": len(rows),
            "data": rows,
        }
    except Exception as e:
        print(f"    [PARSE ERROR] {ticker} {interval}: {e}")
        return None


async def download_ticker(ws_url: str, ticker: str, sem: asyncio.Semaphore) -> tuple:
    """Download all 3 intervals for one ticker via CDP fetch"""
    async with sem:
        results = {}
        
        async with async_playwright() as p:
            try:
                browser = await p.chromium.connect_over_cdp(ws_url)
                page = await browser.new_page()
                
                for interval_key, (interval, range_param) in INTERVALS.items():
                    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={range_param}"
                    
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            fetch_script = f"""
                            async () => {{
                                try {{
                                    const response = await fetch("{url}", {{
                                        headers: {{
                                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                                            'Accept': 'application/json',
                                        }}
                                    }});
                                    if (!response.ok) {{
                                        return {{ status: response.status, error: 'HTTP ' + response.status }};
                                    }}
                                    const text = await response.text();
                                    return {{ status: 200, body: text }};
                                }} catch(e) {{
                                    return {{ status: 0, error: e.message }};
                                }}
                            }}
                            """
                            
                            result = await page.evaluate(fetch_script)
                            
                            if result.get("status") == 200 and result.get("body"):
                                parsed = parse_yahoo_chart(result["body"], ticker, interval)
                                if parsed:
                                    results[interval_key] = parsed
                                    print(f"  ✓ {ticker} {interval_key} ({parsed['count']} bars)")
                                    break
                                else:
                                    print(f"  ✗ {ticker} {interval_key}: parse failed")
                            else:
                                print(f"  ! {ticker} {interval_key}: HTTP {result.get('status')} - {result.get('error')}")
                                
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2 * (attempt + 1))
                        except Exception as e:
                            print(f"  ! {ticker} {interval_key} attempt {attempt+1} error: {e}")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2)
                
                await browser.close()
                
            except Exception as e:
                print(f"  !! {ticker} connection error: {e}")
        
        return ticker, results


async def main():
    print(f"📊 CDO K-line Downloader")
    print(f"   Output: {OUTPUT_DIR}")
    print(f"   Tickers: {len(ALL_TICKERS)}")
    print(f"   Intervals: 1d, 1wk, 1mo")
    print()
    
    # Check existing files
    existing = {}
    for f in OUTPUT_DIR.iterdir():
        if f.suffix == ".json":
            parts = f.stem.rsplit("_", 1)
            if len(parts) == 2:
                ticker, interval = parts
                existing.setdefault(ticker, set()).add(interval)
    
    # Filter to only missing intervals
    to_download = []
    for ticker in ALL_TICKERS:
        for interval in ["1d", "1wk", "1mo"]:
            if ticker not in existing or interval not in existing[ticker]:
                to_download.append((ticker, interval))
    
    unique_tickers_needed = set(t for t, _ in to_download)
    print(f"Need to download: {len(unique_tickers_needed)} tickers, {len(to_download)} interval files")
    
    # Get CDP WebSocket URL
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            ws_url = browser.ws_endpoint
            await browser.close()
            print(f"CDP WebSocket: {ws_url}")
        except Exception as e:
            print(f"Failed to get CDP WS URL: {e}")
            return
    
    # Semaphore for concurrency limit
    sem = asyncio.Semaphore(4)  # 4 concurrent connections
    
    # Download all tickers
    tasks = []
    for ticker in ALL_TICKERS:
        tasks.append(download_ticker(ws_url, ticker, sem))
    
    all_results = await asyncio.gather(*tasks)
    
    # Save results
    saved = []
    failed = []
    no_data = []
    
    for ticker, results in all_results:
        for interval_key, data in results.items():
            out_path = OUTPUT_DIR / f"{ticker}_{interval_key}.json"
            try:
                with open(out_path, "w") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                saved.append(f"{ticker}_{interval_key}")
            except Exception as e:
                print(f"  !! Failed to save {ticker}_{interval_key}: {e}")
                failed.append(f"{ticker}_{interval_key}")
    
    print()
    print("=" * 50)
    print("📋 SUMMARY")
    print(f"  Saved:   {len(saved)} files")
    print(f"  Failed: {len(failed)} files")
    print()
    print(f"  Saved files:")
    for s in sorted(saved):
        print(f"    + {s}")
    if failed:
        print(f"  Failed files:")
        for f in sorted(failed):
            print(f"    - {f}")


if __name__ == "__main__":
    asyncio.run(main())
