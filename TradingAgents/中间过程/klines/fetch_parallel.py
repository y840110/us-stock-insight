#!/usr/bin/env python3
"""CDO single-shot fetcher for one ticker+interval"""
import json, sys, time, subprocess, os
from playwright.sync_api import sync_playwright

CDP = "http://172.25.192.1:19222"
SAVE = "/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/中间过程/klines/"
ticker = sys.argv[1]
interval = sys.argv[2]
fp = f"{SAVE}{ticker}_{interval}.json"

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP, timeout=20000)
        page = browser.contexts[0].new_page()
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range=365d"
        resp = page.goto(url, wait_until="networkidle", timeout=25000)
        if resp.status != 200:
            print(f"FAIL {ticker}_{interval} HTTP {resp.status}")
            sys.exit(1)
        text = page.evaluate("() => { const e=document.querySelector('pre'); return e?e.textContent:document.body.innerText; }")
        browser.close()

    raw = json.loads(text)
    chart = raw["chart"]["result"][0]
    ts = chart["timestamp"]
    q = chart["indicators"]["quote"][0]
    bars = []
    for i, t in enumerate(ts):
        bars.append({"date": time.strftime("%b %d, %Y", time.gmtime(t)),
                     "open": str(q["open"][i] or ""),
                     "high": str(q["high"][i] or ""),
                     "low": str(q["low"][i] or ""),
                     "close": str(q["close"][i] or ""),
                     "vol": int(q["volume"][i] or 0)})

    with open(fp, "w") as f:
        json.dump({"ticker": ticker, "interval": interval, "count": len(bars), "data": bars}, f, indent=2)
    print(f"OK {ticker}_{interval} {len(bars)} bars")
except Exception as e:
    print(f"FAIL {ticker}_{interval} {e}")
