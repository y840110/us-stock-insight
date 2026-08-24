#!/usr/bin/env python3
"""
美股 1h K线回溯补数脚本
=========================

用 range=2y 回补 2024-08-22 ~ 2025-06-02 的缺失数据。
适用于已有 1h 数据但起点在 2025-06-03 之后的股票。

原理：
- Yahoo 1h 数据最多保留 ~730 交易日（~2年）
- range=2y 可稳定返回 2024-08-22 起的数据
- 新数据与本地数据按 datetime 去重合并

流程：
1. 扫描本地 1h 文件，找出起点在 2025-06-03 之后的股票
2. 对每只股票：用 2y range 抓新数据
3. 合并新数据 + 本地已有数据（按 datetime 去重）
4. 保存合并结果
"""
import json, time, os, sys, argparse, threading, queue, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

PROJ_DIR  = Path(__file__).parent.parent.parent.resolve()
WORK_DIR  = PROJ_DIR / '中间过程' / 'klines'
POOL_FILE = PROJ_DIR / 'fintech' / 'stock_pool.json'
CHROME    = 'http://172.25.192.1:19222'

MAX_TABS  = 4
SLEEP_BETWEEN = 0.3

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────
def _fn(symbol):
    return symbol.lstrip('^')

def _fpath(symbol, interval='1h'):
    return WORK_DIR / f'{_fn(symbol)}_{interval}.json'

def datetime_to_ts(dt_str):
    try:
        return int(datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S').timestamp())
    except ValueError:
        return int(datetime.strptime(dt_str[:10], '%Y-%m-%d').timestamp())

def load_local_1h(symbol):
    """返回 (records, earliest_dt_str)"""
    fp = _fpath(symbol, '1h')
    if not fp.exists() or fp.stat().st_size == 0:
        return [], None
    try:
        with open(fp) as f:
            d = json.load(f)
        records = d.get('data', d) if isinstance(d, dict) else d
        if not isinstance(records, list):
            return [], None
        if records:
            return records, records[0]['datetime']
        return [], None
    except:
        return [], None

def save_merged(symbol, records):
    fp = _fpath(symbol, '1h')
    records_sorted = sorted(records, key=lambda x: datetime_to_ts(x['datetime']))
    with open(fp, 'w') as f:
        json.dump({'data': records_sorted}, f, ensure_ascii=False)

# ─────────────────────────────────────────────
# 异常
# ─────────────────────────────────────────────
class TechnicalError(Exception):
    """网络/超时，可重试"""
    pass

class BusinessError(Exception):
    """空数据/数据不足，不可重试"""
    pass

# ─────────────────────────────────────────────
# 股票池
# ─────────────────────────────────────────────
def load_pool():
    with open(POOL_FILE) as f:
        pool = json.load(f)
    symbols = [s['code'] for s in pool['stocks']]
    special = pool.get('_special_symbols', {})
    for sym in special:
        if sym not in {'TNX'} and sym not in symbols:
            symbols.append(sym)
    return symbols

# ─────────────────────────────────────────────
# Yahoo 抓取（2y range）
# ─────────────────────────────────────────────
def fetch_2y_range(page, symbol):
    """用 range=2y 抓取 1h 数据（不回退到其他 range）"""
    ysym = {'DXY': 'DX-Y.NYB', '^VIX': '^VIX'}.get(symbol, symbol)
    url  = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}"
            f"?range=2y&interval=1h")
    return _fetch_url(page, symbol, url)

def _fetch_url(page, symbol, url):
    dt_key = 'datetime'
    try:
        r = page.goto(url, timeout=60000)
    except Exception as e:
        raise TechnicalError(f"goto failed: {e}")
    if not r or r.status != 200:
        raise TechnicalError(f"HTTP {r.status if r else 'None'}")
    content = page.content()
    if not content or len(content) < 200:
        raise BusinessError("页面内容过短，可能是反爬")
    m = re.search(r'\{"chart":\s*{.*}', content, re.DOTALL)
    if not m:
        raise BusinessError("页面中未找到 JSON 数据，可能是反爬拦截")
    chart_data = json.loads(m.group())
    result = chart_data.get('chart', {}).get('result', [])
    if not result:
        raise BusinessError("Yahoo 返回空 result")
    r0 = result[0]
    if r0.get('error'):
        raise BusinessError(f"Yahoo error: {r0['error'].get('description', '?')}")
    timestamps = r0.get('timestamp', [])
    if not timestamps:
        raise BusinessError("timestamp 为空")
    quote = r0.get('indicators', {}).get('quote', [{}])
    if not quote:
        raise BusinessError("quote 数据为空")
    q = quote[0]
    closes = q.get('close', [])
    opens  = q.get('open', [])
    highs  = q.get('high', [])
    lows   = q.get('low', [])
    vols   = q.get('volume', [])
    if len(timestamps) < 5:
        raise BusinessError(f"数据量异常: {len(timestamps)} 根 < 5")
    gmtoffset = r0.get('meta', {}).get('gmtoffset', -14400)
    data = []
    for i, ts in enumerate(timestamps):
        dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
        dt_et  = dt_utc + timedelta(seconds=gmtoffset)
        data.append({
            'datetime': dt_et.strftime('%Y-%m-%d %H:%M:%S'),
            'open':   round(float(opens[i]),  2) if opens[i]  is not None else 0,
            'high':   round(float(highs[i]),  2) if highs[i]  is not None else 0,
            'low':    round(float(lows[i]),   2) if lows[i]   is not None else 0,
            'close':  round(float(closes[i]), 2) if closes[i] is not None else 0,
            'volume': int(vols[i])             if vols[i]   is not None else 0,
        })
    return data

# ─────────────────────────────────────────────
# 主逻辑
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='1h K线回溯补数（range=2y）')
    parser.add_argument('--symbol', help='只处理指定股票')
    parser.add_argument('--check', action='store_true', help='只检查需要补数的股票')
    args = parser.parse_args()

    symbols = [args.symbol] if args.symbol else load_pool()
    
    # 扫描本地 1h 文件，找出需要补数的
    needs_backfill = []
    no_data = []  # 完全无数据的
    
    for sym in symbols:
        local, earliest = load_local_1h(sym)
        if not local:
            no_data.append(sym)
            continue
        # 已有数据，检查最早日期
        try:
            earliest_dt = datetime.strptime(earliest, '%Y-%m-%d %H:%M:%S')
            cutoff = datetime(2025, 6, 3, tzinfo=None)  # 数据应该早在2025-06-03之前
            if earliest_dt > datetime(2025, 6, 3):  # 起点晚于2025-06-03，需要补
                needs_backfill.append({
                    'symbol': sym,
                    'local_count': len(local),
                    'earliest': earliest,
                    'new_bars_expected': '~1324'  # 估算
                })
        except:
            pass
    
    if args.check:
        print(f"=== 1h 数据缺口检查 ===")
        print(f"需要回补: {len(needs_backfill)} 只")
        print(f"无数据:   {len(no_data)} 只")
        print()
        if needs_backfill:
            print("需要回补的股票（前10）:")
            for item in sorted(needs_backfill, key=lambda x: x['earliest'])[:10]:
                print(f"  {item['symbol']}: 本地最早 {item['earliest']}, {item['local_count']}条")
        if no_data:
            print(f"\n无数据股票: {no_data}")
        return
    
    # 合并需要回补 + 无数据的股票
    target_symbols = [item['symbol'] for item in needs_backfill] + no_data
    print(f"=== 1h 回溯补数 ===")
    print(f"需补数股票: {len(needs_backfill)} 只")
    print(f"无数据股票: {len(no_data)} 只")
    print(f"合计: {len(target_symbols)} 只")
    print()
    
    if not target_symbols:
        print("所有股票数据已完整，无需补数")
        return
    
    # ── 固定4 Tab 连接池 ──────────────────────
    # Playwright sync API 不是线程安全的，每个 worker 必须独立实例
    task_queue    = queue.Queue()
    result_queue  = queue.Queue()
    
    for sym in target_symbols:
        task_queue.put(sym)
    
    num_workers = min(MAX_TABS, len(target_symbols))
    
    def worker(tab_id):
        """每个 worker 独立 Playwright 实例，独立 CDP 连接"""
        new_bars_total = 0
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(CHROME)
            page    = browser.new_page()
            
            while True:
                try:
                    sym = task_queue.get_nowait()
                except queue.Empty:
                    break
                
                local, earliest = load_local_1h(sym)
                local_count = len(local)
                
                try:
                    bars = fetch_2y_range(page, sym)
                    
                    # 合并：本地 + 新数据，按 datetime 去重
                    existing_ts = {r['datetime'] for r in local}
                    new_bars = [b for b in bars if b['datetime'] not in existing_ts]
                    
                    if new_bars:
                        merged = local + new_bars
                        save_merged(sym, merged)
                        new_added = len(new_bars)
                        new_bars_total += new_added
                        status = f"✅ {sym}: 新增 {new_added} 条（本地 {local_count} → {len(merged)}）"
                    else:
                        status = f"⏩ {sym}: 无新增（range=2y 与本地重叠），本地 {local_count} 条"
                    
                    result_queue.put(('success', status))
                    
                except BusinessError as e:
                    result_queue.put(('skip', f"⏭ {sym}: {e}"))
                except TechnicalError as e:
                    result_queue.put(('fail', f"❌ {sym}: {e}"))
                finally:
                    task_queue.task_done()
                
                time.sleep(SLEEP_BETWEEN)
            
            browser.close()
        return new_bars_total
    
    # 启动 workers
    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(num_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # ── 收集结果 ─────────────────────────────
    success = skip = fail = 0
    new_total = 0
    
    while not result_queue.empty():
        kind, msg = result_queue.get()
        print(msg)
        if kind == 'success':
            m = re.search(r'新增 (\d+) 条', msg)
            if m:
                new_total += int(m.group(1))
            success += 1
        elif kind == 'skip':
            skip += 1
        else:
            fail += 1
    
    print()
    print(f"=== 完成 ===")
    print(f"✅ 成功: {success}  ⏭ 跳过: {skip}  ❌ 失败: {fail}")
    print(f"📊 新增 1h bars 合计: {new_total:,}")

if __name__ == '__main__':
    main()
