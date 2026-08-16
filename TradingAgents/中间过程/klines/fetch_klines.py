import json
import time
from playwright.sync_api import sync_playwright

symbols = ['ABB', 'DFS', 'JNPR', 'TTM', 'FBTC', 'IBIT']
output_dir = '/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/中间过程/klines'

results = {}

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://172.25.192.1:19222")
    ctx = browser.contexts[0]
    page = ctx.new_page()

    for sym in symbols:
        output_path = f"{output_dir}/{sym}_1d.json"
        try:
            print(f"Fetching {sym}...")
            page.goto(f"https://finance.yahoo.com/quote/{sym}/history", timeout=20000)
            time.sleep(3)

            # Check if we got redirected to a search/results page
            current_url = page.url
            if '/quote/' not in current_url or sym not in page.title():
                print(f"  {sym}: SKIP - redirected to {current_url}")
                results[sym] = "SKIP"
                with open(output_path, 'w') as f:
                    json.dump({"data": "SKIP"}, f)
                continue

            # Parse table
            rows = page.query_selector_all('table tbody tr')
            data_list = []

            for row in rows:
                cells = row.query_selector_all('td')
                if len(cells) >= 6:
                    try:
                        date = cells[0].inner_text().strip()
                        open_ = cells[1].inner_text().strip()
                        high = cells[2].inner_text().strip()
                        low = cells[3].inner_text().strip()
                        close = cells[4].inner_text().strip()
                        volume = cells[5].inner_text().strip()

                        # Skip rows that look like dividers or empty
                        if not date or date == 'Date':
                            continue
                        if 'Dividend' in date or 'Stock Split' in date:
                            continue

                        data_list.append({
                            'date': date,
                            'open': open_,
                            'high': high,
                            'low': low,
                            'close': close,
                            'volume': volume
                        })
                    except Exception as e:
                        continue

            # Sort by date ascending
            data_list.sort(key=lambda x: x['date'])

            with open(output_path, 'w') as f:
                json.dump({"data": data_list}, f)

            print(f"  {sym}: {len(data_list)} rows saved to {output_path}")
            results[sym] = f"OK - {len(data_list)} rows"

        except Exception as e:
            print(f"  {sym}: ERROR - {e}")
            results[sym] = f"ERROR - {e}"
            with open(output_path, 'w') as f:
                json.dump({"data": "ERROR"}, f)

    browser.close()

print("\n=== Summary ===")
for sym, status in results.items():
    print(f"{sym}: {status}")
