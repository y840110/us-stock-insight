#!/usr/bin/env python3
"""
1h 数据专用回溯脚本
===================
Yahoo 对 1h 数据不接受 period1/period2，只接受 range=Ny 参数。
range=2y 最多返回约2年前至今的数据。

策略：所有股票用 range=2y 覆盖，从 2024-08-22 至今。
如果本地数据已经比 2024-08-22 更早，则跳过。
"""

import sys, os, time, json, random, queue, threading
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_us_stocks_cdp import fetch_yahoo, save_stock_data, load_local, _fpath, TechnicalError

PROJ = Path(__file__).resolve().parents[2]
KL = PROJ / '中间过程' / 'klines'
CHROME = 'http://172.25.192.1:19222'

# 4-tab pool
NUM_TABS = 4
SLEEP_BETWEEN = 0.3
MAX_RETRIES = 2

# Yahoo 1h range=2y 最早约 2024-08-22
RANGE_START = '2024-08-22'

def load_symbols():
    sp = PROJ / 'scripts' / 'stock_pool.json'
    if sp.exists():
        data = json.load(open(sp))
        return [s['code'] for s in data.get('stocks', [])]
    # fallback: 从 klines 目录扫描
    files = [f for f in os.listdir(KL) if f.endswith('_1h.json')]
    return sorted(set(f.replace('_1h.json', '') for f in files))

def needs_backfill(sym):
    """检查本地数据是否早于 range=2y 的覆盖起始日"""
    fp = _fpath(sym, '1h')
    if not fp.exists():
        return True
    local = load_local(sym, '1h')
    if not local or not local.get('data'):
        return True
    first_date = local['data'][0]['datetime'][:10]
    return first_date > RANGE_START

def worker(tab_id, task_queue, results, lock):
    """每个 worker 持有一个固定的 CDP page"""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(CHROME, timeout=20000)
    ctx = browser.contexts[0]
    page = ctx.new_page()
    page.set_default_timeout(90000)

    print(f"[Tab-{tab_id}] 启动")

    while True:
        try:
            sym = task_queue.get(timeout=5)
        except queue.Empty:
            break

        for attempt in range(MAX_RETRIES):
            try:
                bars = fetch_yahoo(page, sym, '1h', '2y')
                if bars and len(bars) > 100:
                    save_stock_data(sym, bars, '1h')
                    with lock:
                        results[sym] = ('ok', len(bars))
                    print(f"[Tab-{tab_id}] ✅ {sym}: {len(bars)} 根")
                else:
                    with lock:
                        results[sym] = ('skip', 0, '数据不足')
                    print(f"[Tab-{tab_id}] ⚠️ {sym}: 数据不足({len(bars) if bars else 0}根)")
                time.sleep(SLEEP_BETWEEN)
                break
            except TechnicalError as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2)
                    continue
                with lock:
                    results[sym] = ('fail', 0, str(e)[:60])
                print(f"[Tab-{tab_id}] ❌ {sym}: {e}")
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2)
                    continue
                with lock:
                    results[sym] = ('fail', 0, str(e)[:60])
                print(f"[Tab-{tab_id}] ❌ {sym}: {e}")

        task_queue.task_done()

    page.close()
    browser.close()
    pw.stop()
    print(f"[Tab-{tab_id}] 退出")

def main():
    symbols = load_symbols()
    print(f"股票总数: {len(symbols)}")

    # 过滤只需要回溯的
    todo = [s for s in symbols if needs_backfill(s)]
    print(f"需要回溯: {len(todo)} 只")
    print(f"数据范围: {RANGE_START} → 今（range=2y）")

    if not todo:
        print("没有需要回溯的股票")
        return

    task_queue = queue.Queue()
    for sym in todo:
        task_queue.put(sym)

    results = {}
    lock = threading.Lock()

    # 启动 worker
    threads = []
    for i in range(NUM_TABS):
        t = threading.Thread(target=worker, args=(i, task_queue, results, lock))
        t.start()
        threads.append(t)

    # 等待完成
    task_queue.join()
    for t in threads:
        t.join()

    # 统计
    ok = sum(1 for v in results.values() if v[0] == 'ok')
    fail = sum(1 for v in results.values() if v[0] == 'fail')
    skip = sum(1 for v in results.values() if v[0] in ('skip',))
    print(f"\n完成: ✅{ok} ❌{fail} ⚠️{skip}")

    # 保存结果
    out = PROJ / '中间过程' / 'backfill_1h_result.json'
    with open(out, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"结果已保存: {out}")

if __name__ == '__main__':
    main()
