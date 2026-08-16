#!/usr/bin/env python3
"""
CDP WebSocket client using Python websockets
Connects to Chrome's CDP and runs fetch() via Runtime.evaluate
"""
import asyncio
import json
import websockets
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/中间过程/klines")
WS_URL = "ws://172.25.192.1:19222/devtools/page/5C8CAE7FBF06704FBBAB30149CC797C8"

ALL_TICKERS = sorted(set([
    "ANET", "PLTR", "IONQ", "MU", "COHR",
    "MCHP", "SWKS", "NET", "DDOG", "SMCI",
    "SNOW", "WDC", "QUBT", "RGTI", "PANW",
    "CRWD", "ZS", "SOXX", "ROBO", "QT",
]))

INTERVALS = [("1d", "1d", "365d"), ("1wk", "1wk", "365d"), ("1mo", "1mo", "730d")]


def parse_yahoo(text, ticker, interval):
    try:
        if isinstance(text, dict):
            data = text
        else:
            data = json.loads(text)
        result = data.get("chart", {}).get("result", [None])[0]
        if not result:
            return None
        ts = result.get("timestamp", [])
        quote = result.get("indicators", {}).get("quote", [{}])[0]
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


def make_fetch_script(url):
    escaped_url = url.replace("'", "\\'")
    return (
        "(async()=>{"
        "try{"
        "const r=await fetch('" + escaped_url + "',{"
        "headers:{'User-Agent':'Mozilla/5.0','Accept':'application/json'}"
        "});"
        "return await r.text()"
        "}catch(e){return 'ERROR:'+e.message}"
        "})()"
    )


async def cdp_call(ws, msg_id, method, params, timeout=30):
    msg = json.dumps({"id": msg_id, "method": method, "params": params})
    await ws.send(msg)
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            resp = json.loads(raw)
            if resp.get("id") == msg_id:
                return resp
        except asyncio.TimeoutError:
            return {"id": msg_id, "error": "timeout"}


async def fetch_data(ws, ticker, intv_key, interval, range_str):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={range_str}"
    script = make_fetch_script(url)
    
    resp = await cdp_call(ws, 1, "Runtime.evaluate", {
        "expression": script,
        "returnByValue": True,
        "timeout": 30000
    }, timeout=45)
    
    result = resp.get("result", {})
    if result.get("wasThrown"):
        exc = result.get("exceptionDetails", {})
        return None, f"JS: {exc.get('text', '?')}"
    
    val = result.get("result", {}).get("value")
    if val is None:
        return None, "null response"
    if isinstance(val, str) and val.startswith("ERROR:"):
        return None, val
    
    # If already a dict (JSON parsed by CDP), serialize back
    if isinstance(val, dict):
        return val, None
    if isinstance(val, str):
        return val, None
    
    return None, f"unexpected type: {type(val)}"


async def main():
    print("📊 CDP K-line Fetcher")
    print(f"   WS: {WS_URL[:70]}")
    print()
    
    existing = {}
    for f in OUTPUT_DIR.iterdir():
        if f.suffix == ".json":
            parts = f.stem.rsplit("_", 1)
            if len(parts) == 2:
                existing.setdefault(parts[0], set()).add(parts[1])
    
    to_download = []
    for ticker in ALL_TICKERS:
        for intv_key, _, _ in INTERVALS:
            if ticker not in existing or intv_key not in existing[ticker]:
                to_download.append((ticker, intv_key))
    
    unique_tickers = sorted(set(t for t, _ in to_download))
    print(f"Need: {len(unique_tickers)} tickers, {len(to_download)} files")
    print(f"Tickers: {unique_tickers}")
    print()
    
    if not to_download:
        print("All complete!")
        return
    
    try:
        async with websockets.connect(WS_URL, open_timeout=10, close_timeout=5) as ws:
            print("Connected to Chrome!")
            
            # Test
            print("Test ANET/1d...")
            data, err = await fetch_data(ws, "ANET", "1d", "1d", "365d")
            if err:
                print(f"  Error: {err}")
            elif data is not None:
                parsed = parse_yahoo(data, "ANET", "1d")
                if parsed:
                    print(f"  OK: {parsed['count']} bars, saved to file")
                    out = OUTPUT_DIR / "ANET_1d.json"
                    with open(out, "w") as f:
                        json.dump(parsed, f, indent=2, ensure_ascii=False)
                else:
                    print(f"  Parse fail. Data type: {type(data)}, first 100: {str(data)[:100]}")
            else:
                print("  No data returned")
            
            if data is None:
                print("\nBrowser fetch failed. Aborting.")
                return
            
            # Process all
            print()
            for ticker in unique_tickers:
                for intv_key, interval, range_str in INTERVALS:
                    if ticker in existing and intv_key in existing[ticker]:
                        continue
                    
                    print(f"  {ticker}/{intv_key}...", end=" ", flush=True)
                    data, err = await fetch_data(ws, ticker, intv_key, interval, range_str)
                    
                    if err:
                        print(f"ERR: {err}")
                        await asyncio.sleep(2)
                        continue
                    
                    if data is None:
                        print("empty")
                        await asyncio.sleep(2)
                        continue
                    
                    parsed = parse_yahoo(data, ticker, intv_key)
                    if parsed:
                        out = OUTPUT_DIR / f"{ticker}_{intv_key}.json"
                        with open(out, "w") as f:
                            json.dump(parsed, f, indent=2, ensure_ascii=False)
                        print(f"OK ({parsed['count']} bars)")
                    else:
                        print(f"PARSE FAIL: {str(data)[:80]}")
                    
                    await asyncio.sleep(0.3)
    
    except Exception as e:
        print(f"Connection error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
