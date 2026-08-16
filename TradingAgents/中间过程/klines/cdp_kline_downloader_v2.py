#!/usr/bin/env python3
"""
CDO K-line Downloader v2 - Connects to existing Chrome via WebSocket URL
Uses CDP fetch to get Yahoo Finance data
"""
import asyncio
import json
import sys
from pathlib import Path
from playwright.async_api import async_playwright

# Config
OUTPUT_DIR = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/中间过程/klines")

# All tickers to process
ALL_TICKERS = sorted(set([
    "ANET", "PLTR", "IONQ", "MU", "COHR",
    "MCHP", "SWKS", "NET", "DDOG", "SMCI",
    "SNOW", "WDC", "QUBT", "RGTI", "PANW",
    "CRWD", "ZS", "SOXX", "ROBO", "QT",
]))

INTERVALS = {
    "1d": ("1d", "365d"),
    "1wk": ("1wk", "365d"),
    "1mo": ("1mo", "730d"),
}


def parse_yahoo_chart(text: str, ticker: str, interval: str):
    try:
        data = json.loads(text)
        result = data.get("chart", {}).get("result", [None])[0]
        if not result:
            return None
        ts = result.get("timestamp", [])
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        adj = result.get("indicators", {}).get("adjclose", [{}])
        adj_closes = adj[0].get("adjclose", []) if adj else []
        
        from datetime import datetime
        rows = []
        for i, t in enumerate(ts):
            dt = datetime.fromtimestamp(t)
            rows.append({
                "date": dt.strftime("%b %d, %Y"),
                "ymd": dt.strftime("%Y-%m-%d"),
                "open": f"{quote['open'][i]:.2f}" if quote['open'][i] is not None else None,
                "high": f"{quote['high'][i]:.2f}" if quote['high'][i] is not None else None,
                "low": f"{quote['low'][i]:.2f}" if quote['low'][i] is not None else None,
                "close": f"{quote['close'][i]:.2f}" if quote['close'][i] is not None else None,
                "vol": int(quote['volume'][i]) if quote['volume'][i] is not None else 0,
            })
        return {"ticker": ticker, "interval": interval, "count": len(rows), "data": rows}
    except Exception as e:
        print(f"    [PARSE ERR] {ticker}/{interval}: {e}")
        return None


async def fetch_via_cdp(ws_url: str, page_id: str, tickers: list) -> dict:
    """Use a specific browser page to do fetch() calls"""
    results = {}
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect(ws_url, timeout=30000)
            # Find the target page
            target = None
            for ctx in browser.contexts:
                for pg in ctx.pages:
                    if page_id in pg.url:
                        target = pg
                        break
                if target:
                    break
            
            if not target:
                # Fallback: use first available page
                for ctx in browser.contexts:
                    if ctx.pages:
                        target = ctx.pages[0]
                        break
            
            if not target:
                print("  !! No target page found")
                await browser.close()
                return {}
            
            print(f"  Using page: {target.url[:60]}")
            
            for ticker in tickers:
                results[ticker] = {}
                for intv_key, (intv, rng) in INTERVALS.items():
                    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={intv}&range={rng}"
                    script = f"""
                    async () => {{
                        try {{
                            const r = await fetch('{url}', {{
                                headers: {{
                                    'User-Agent': 'Mozilla/5.0',
                                    'Accept': 'application/json',
                                }}
                            }});
                            const t = await r.text();
                            return {{ok: r.ok, status: r.status, body: t}};
                        }} catch(e) {{
                            return {{ok: false, error: e.message}};
                        }}
                    }}
                    """
                    for attempt in range(3):
                        try:
                            res = await target.evaluate(script, timeout=20000)
                            if res.get("ok") and res.get("body"):
                                parsed = parse_yahoo_chart(res["body"], ticker, intv_key)
                                if parsed:
                                    results[ticker][intv_key] = parsed
                                    print(f"    ✓ {ticker}/{intv_key} ({parsed['count']} bars)")
                                    break
                                else:
                                    print(f"    ! {ticker}/{intv_key}: parse failed")
                            else:
                                print(f"    ! {ticker}/{intv_key}: HTTP {res.get('status')} - {res.get('error')}")
                            if attempt < 2:
                                await asyncio.sleep(2 * (attempt + 1))
                        except Exception as e:
                            print(f"    ! {ticker}/{intv_key} attempt {attempt+1}: {e}")
                            if attempt < 2:
                                await asyncio.sleep(2)
            
            await browser.close()
        except Exception as e:
            print(f"  !! Connection error: {e}")
    return results


async def main():
    print("📊 CDO K-line Downloader v2")
    print(f"   Output: {OUTPUT_DIR}")
    print(f"   Tickers: {len(ALL_TICKERS)}")
    print()
    
    # Get WebSocket URL from CDP HTTP API
    import urllib.request
    try:
        with urllib.request.urlopen("http://172.25.192.1:19222/json", timeout=5) as r:
            tabs = json.loads(r.read())
    except Exception as e:
        print(f"Failed to get CDP tabs: {e}")
        return
    
    # Find Yahoo Finance page
    yf_page = None
    for t in tabs:
        if "yahoo" in t.get("url", "").lower() and t.get("type") == "page":
            yf_page = t
            break
    
    if yf_page:
        ws_url = yf_page["webSocketDebuggerUrl"]
        page_id = yf_page["id"]
        print(f"Found Yahoo Finance tab: {yf_page['title'][:50]}")
    else:
        # Use first page
        yf_page = tabs[0]
        ws_url = yf_page["webSocketDebuggerUrl"]
        page_id = yf_page["id"]
        print(f"Using first tab: {yf_page.get('title', '?')[:50]}")
    
    print(f"   WS URL: {ws_url[:80]}")
    print()
    
    # Check existing files
    existing = {}
    for f in OUTPUT_DIR.iterdir():
        if f.suffix == ".json":
            parts = f.stem.rsplit("_", 1)
            if len(parts) == 2:
                ticker, intv = parts
                existing.setdefault(ticker, set()).add(intv)
    
    # Determine what needs downloading
    to_download = []
    for ticker in ALL_TICKERS:
        for intv in ["1d", "1wk", "1mo"]:
            if ticker not in existing or intv not in existing[ticker]:
                to_download.append(ticker)
    
    unique_needed = sorted(set(to_download))
    print(f"Need to download: {len(unique_needed)} tickers: {unique_needed}")
    print()
    
    if not unique_needed:
        print("All data already present!")
        return
    
    # Split into batches for 4 workers
    batch_size = (len(unique_needed) + 3) // 4
    batches = [unique_needed[i:i+batch_size] for i in range(0, len(unique_needed), batch_size)]
    
    tasks = [fetch_via_cdp(ws_url, page_id, batch) for batch in batches]
    all_results = await asyncio.gather(*tasks)
    
    # Merge results
    merged = {}
    for r in all_results:
        merged.update(r)
    
    # Save
    saved = []
    failed = []
    for ticker, intv_data in merged.items():
        for intv_key, data in intv_data.items():
            out_path = OUTPUT_DIR / f"{ticker}_{intv_key}.json"
            try:
                with open(out_path, "w") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                saved.append(f"{ticker}_{intv_key}")
            except Exception as e:
                print(f"  !! Save error {ticker}_{intv_key}: {e}")
                failed.append(f"{ticker}_{intv_key}")
    
    print()
    print("=" * 50)
    print("📋 SUMMARY")
    print(f"  Saved:   {len(saved)} files")
    print(f"  Failed:  {len(failed)} files")
    if saved:
        print(f"  Files: {', '.join(sorted(saved))}")
    if failed:
        print(f"  Failed: {', '.join(sorted(failed))}")


if __name__ == "__main__":
    asyncio.run(main())
