#!/usr/bin/env python3
"""Worker entry point: fetch one ticker+interval via Chrome CDP (standalone process)"""

import json
import sys
import time
from playwright.sync_api import sync_playwright

CDP_URL = "http://172.25.192.1:19222"
SAVE_DIR = "/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/中间过程/klines/"


def fetch_one(ticker, interval):
    key = f"{ticker}_{interval}"
    filepath = f"{SAVE_DIR}{ticker}_{interval}.json"
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0]
            page = context.new_page()

            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range=365d"
            resp = page.goto(url, wait_until="networkidle", timeout=30000)
            if resp.status != 200:
                return key, False, f"HTTP {resp.status}"

            content = page.evaluate("""() => {
                let el = document.querySelector("pre");
                return el ? el.textContent : document.body.innerText;
            }""")
            browser.close()

        raw = json.loads(content)
        chart = raw.get("chart", {}).get("result", [{}])[0]
        ts = chart.get("timestamp", [])
        ind = chart.get("indicators", {}).get("quote", [{}])[0]

        quotes = []
        for i, t in enumerate(ts):
            date_str = time.strftime("%b %d, %Y", time.gmtime(t))
            quotes.append({
                "date": date_str,
                "open": str(ind.get("open", [None])[i] or ""),
                "high": str(ind.get("high", [None])[i] or ""),
                "low": str(ind.get("low", [None])[i] or ""),
                "close": str(ind.get("close", [None])[i] or ""),
                "vol": int(ind.get("volume", [None])[i] or 0)
            })

        output = {"ticker": ticker, "interval": interval, "count": len(quotes), "data": quotes}
        with open(filepath, "w") as f:
            json.dump(output, f, indent=2)

        return key, True, f"OK: {len(quotes)} bars → {filepath}"

    except Exception as e:
        return key, False, str(e)


if __name__ == "__main__":
    ticker = sys.argv[1]
    interval = sys.argv[2]
    key, ok, msg = fetch_one(ticker, interval)
    print("RESULT:", json.dumps({"key": key, "ok": ok, "msg": msg}))
