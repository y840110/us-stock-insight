#!/usr/bin/env python3
"""
美股 K 线数据抓取 - 固定4 Tab 连接池
==========================================

设计原则：
1. 固定4个 Tab，全程复用，不反复开闭
2. 每个 Tab 独立 Browser 连接，worker 绑定 Tab 不跨线程
3. Range 固定 1y（Yahoo 上限 730 天，1y 覆盖全部）
4. 快速失败：技术层最多重试1次，业务层0次
5. 业务层验证：HTTP 200 ≠ 成功，必须验证数据量
"""
import json, time, os, sys, argparse, threading, queue
from datetime import datetime, timezone, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

PROJ_DIR  = Path(__file__).parent.parent.parent.resolve()
WORK_DIR   = PROJ_DIR / '中间过程' / 'klines'
POOL_FILE  = PROJ_DIR / 'fintech' / 'stock_pool.json'
CHROME_DEBUG_URL = 'http://172.25.192.1:19222'

MAX_TABS  = 4           # 固定4个 Tab
SLEEP_BETWEEN = 0.3    # 请求间隔（秒），防 Yahoo 限流

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────
def _fn(symbol):
    return symbol.lstrip('^')

def _fpath(symbol, interval):
    return WORK_DIR / f'{_fn(symbol)}_{interval}.json'

def datetime_to_ts(dt_str):
    try:
        return int(datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S').timestamp())
    except ValueError:
        return int(datetime.strptime(dt_str[:10], '%Y-%m-%d').timestamp())


# ─────────────────────────────────────────────
# 异常
# ─────────────────────────────────────────────
class TechnicalError(Exception):
    """技术层失败：网络/超时/解析错误，可重试"""
    pass

class BusinessError(Exception):
    """业务层失败：空数据/数据不足，不可重试"""
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
# 本地数据
# ─────────────────────────────────────────────
def load_local(symbol, interval):
    fp = _fpath(symbol, interval)
    if not fp.exists() or fp.stat().st_size == 0:
        return []
    try:
        with open(fp) as f:
            d = json.load(f)
        data = d.get('data', d) if isinstance(d, dict) else d
        if not isinstance(data, list):
            return []
        key = 'datetime' if interval == '1h' else 'date'
        return [e[key] for e in data if isinstance(e, dict) and key in e]
    except Exception:
        return []

def save_stock_data(symbol, data_list, interval):
    fp = _fpath(symbol, interval)
    existing = []
    if fp.exists() and fp.stat().st_size > 0:
        try:
            with open(fp) as f:
                d = json.load(f)
            edata = d.get('data', d) if isinstance(d, dict) else d
            if isinstance(edata, list):
                existing = edata
        except Exception:
            existing = []

    key = 'datetime' if interval == '1h' else 'date'
    date_map = {e[key]: e for e in existing}
    for e in data_list:
        date_map[e[key]] = e

    merged = sorted(date_map.values(), key=lambda x: datetime_to_ts(x[key]))
    with open(fp, 'w') as f:
        json.dump({'data': merged}, f, indent=2)


# ─────────────────────────────────────────────
# Yahoo 抓取
# ─────────────────────────────────────────────
def fetch_yahoo(page, symbol: str, interval: str, use_range: str) -> list:
    """抓取指定 interval + range，返回 bar 列表"""
    import re
    ysym = {'DXY': 'DX-Y.NYB', '^VIX': '^VIX'}.get(symbol, symbol)
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}"
           f"?range={use_range}&interval={interval}")
    return _fetch_url(page, symbol, url, interval)


def fetch_yahoo_period(page, symbol: str, interval: str, period1_ts: int, period2_ts: int) -> list:
    """
    用 period1/period2 时间戳抓取，突破 Yahoo 730 天限制。
    period1_ts / period2_ts: Unix timestamp（秒）
    """
    import re
    ysym = {'DXY': 'DX-Y.NYB', '^VIX': '^VIX'}.get(symbol, symbol)
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}"
           f"?period1={period1_ts}&period2={period2_ts}&interval={interval}")
    return _fetch_url(page, symbol, url, interval)


def _fetch_url(page, symbol: str, url: str, interval: str) -> list:
    """通用 URL 抓取逻辑，返回 bar 列表"""
    import re
    dt_key = 'datetime' if interval == '1h' else 'date'

    try:
        r = page.goto(url, timeout=60000)
    except Exception as e:
        raise TechnicalError(f"goto failed: {e}")

    if not r or r.status != 200:
        raise TechnicalError(f"HTTP {r.status if r else 'None'}")

    content = page.content()
    if not content or len(content) < 200:
        raise BusinessError("页面内容过短，可能是反爬")

    m = re.search(r'{"chart":\s*{.*}', content, re.DOTALL)
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

    # 业务层验证：数据量门槛（通用最小值，range-based 请求由 caller 额外验证）
    if len(timestamps) < 5:
        raise BusinessError(f"数据量异常: {len(timestamps)} 根 < 5")

    # 获取 gmtoffset 用于 UTC → ET 转换（与 fetch_us_1h_cdp.py 一致）
    gmtoffset = r0.get('meta', {}).get('gmtoffset', -14400)  # 默认 EDT UTC-4

    data = []
    for i, ts in enumerate(timestamps):
        dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
        dt_et = dt_utc + timedelta(seconds=gmtoffset)
        data.append({
            dt_key: dt_et.strftime('%Y-%m-%d %H:%M:%S') if interval == '1h' else dt_et.strftime('%Y-%m-%d'),
            'open':   round(float(opens[i]),  2) if opens[i]  is not None else 0,
            'high':   round(float(highs[i]),  2) if highs[i]  is not None else 0,
            'low':    round(float(lows[i]),   2) if lows[i]   is not None else 0,
            'close':  round(float(closes[i]), 2) if closes[i] is not None else 0,
            'volume': int(vols[i])             if vols[i]   is not None else 0,
        })

    data.sort(key=lambda x: datetime_to_ts(x[dt_key]))
    return data


# ─────────────────────────────────────────────
# Tab Worker（固定4个 Tab，全程复用）
# ─────────────────────────────────────────────
def tab_worker(tab_id: int, work_queue: queue.Queue, results: dict,
               lock: threading.Lock, chrome_url: str, force: bool):
    """
    每个 worker：连接 CDP → 创建1个 Page → 轮询处理任务 → 用完关闭
    不跨线程使用 page，避免 greenlet 错误。
    """
    browser = None
    page = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(chrome_url, timeout=30000)
        ctx = browser.contexts[0]
        page = ctx.new_page()
        page.set_default_timeout(60000)

        while True:
            sym = None
            iv = None
            try:
                task = work_queue.get_nowait()
                if task is None:
                    work_queue.task_done()
                    break
                sym, iv = task
            except queue.Empty:
                break

            try:
                if iv == '1h':
                    local = load_local(sym, '1h')
                    if local and not force:
                        # 增量补最新（只补5天）
                        try:
                            bars = fetch_yahoo(page, sym, '1h', '5d')
                            if bars:
                                save_stock_data(sym, bars, '1h')
                            with lock:
                                results[sym] = ('ok', len(bars),
                                    f'增量 {bars[0]["datetime"]}~{bars[-1]["datetime"]}')
                        except (TechnicalError, BusinessError) as e:
                            # 增量5d失败 → 降级全量1y重试
                            try:
                                bars = fetch_yahoo(page, sym, '1h', '1y')
                                save_stock_data(sym, bars, '1h')
                                with lock:
                                    results[sym] = ('ok', len(bars),
                                        f'降级全量 {bars[0]["datetime"]}~{bars[-1]["datetime"]}')
                            except (TechnicalError, BusinessError) as e2:
                                with lock:
                                    results[sym] = ('fail', len(local),
                                        f'增量失败({len(local)}根): {str(e)[:40]}; 全量也失败: {str(e2)[:40]}')
                    else:
                        # 全量抓（1y = Yahoo 1h 上限）
                        bars = fetch_yahoo(page, sym, '1h', '1y')
                        save_stock_data(sym, bars, '1h')
                        with lock:
                            results[sym] = ('ok', len(bars),
                                f'{bars[0]["datetime"]}~{bars[-1]["datetime"]}')

                elif iv == '1d':
                    local = load_local(sym, '1d')
                    # 判断本地数据是否过期（超过最新交易日仍未更新）
                    # 最新交易日在工作日比昨天多（周末跨两天）
                    from datetime import date, timedelta
                    today = date.today()
                    latest_local = None
                    if local:
                        try:
                            latest_local = date.fromisoformat(local[-1][:10])
                        except ValueError:
                            latest_local = None
                    # 如果本地数据最新日期 < 昨天(工作日)，就强制刷新
                    # weekday(): 0=Mon, 4=Fri, 5=Sat, 6=Sun
                    days_back = 1 if today.weekday() != 6 else 2  # 周日算2天
                    cutoff = today - timedelta(days=days_back)
                    stale = (latest_local is None) or (latest_local < cutoff)

                    if local and not force and not stale:
                        with lock:
                            results[sym] = ('ok', len(local),
                                f'本地已有 {local[-1]}')
                    else:
                        # 全量抓（固定 1y），补回所有缺失交易日
                        try:
                            bars = fetch_yahoo(page, sym, '1d', '1y')
                            save_stock_data(sym, bars, '1d')
                            with lock:
                                results[sym] = ('ok', len(bars),
                                    f'更新 {bars[0]["date"]}~{bars[-1]["date"]} [1y]')
                        except (TechnicalError, BusinessError) as e:
                            with lock:
                                results[sym] = ('fail', len(local) if local else 0,
                                    f'1d全量失败: {str(e)[:60]}')

            except (TechnicalError, BusinessError) as e:
                with lock:
                    results[sym] = ('fail', 0, str(e)[:80])

            work_queue.task_done()
            time.sleep(SLEEP_BETWEEN)

    except Exception as e:
        print(f"[Tab{tab_id}] 异常: {e}")

    finally:
        if page:
            try: page.close()
            except: pass
        if browser:
            try: browser.close()
            except: pass
        try:
            pw.stop()
        except: pass


# ─────────────────────────────────────────────
# 连接池入口
# ─────────────────────────────────────────────
def fetch_with_pool(tasks: list, chrome_url: str, force: bool = False) -> dict:
    """
    固定4 Tab 并发抓取。
    tasks: [(symbol, interval), ...]  e.g. [('AAPL', '1d'), ('NVDA', '1h')]
    返回: {symbol: (status, count, message)}
    """
    work_queue = queue.Queue()
    results = {}
    lock = threading.Lock()

    for t in tasks:
        work_queue.put(t)
    # 预先 put None 的数量，以便 work_queue.join() 能正确等待
    # 先不塞 None，等所有任务出队后再塞

    threads = []
    for i in range(MAX_TABS):
        t = threading.Thread(target=tab_worker,
                           args=(i, work_queue, results, lock, chrome_url, force))
        t.start()
        threads.append(t)

    work_queue.join()   # 等待所有任务被 task_done()

    # 发送退出信号
    for _ in range(MAX_TABS):
        work_queue.put(None)
    for t in threads:
        t.join()

    return results


# ─────────────────────────────────────────────
# main
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='美股 K 线抓取 - 固定4 Tab 连接池')
    parser.add_argument('--check', action='store_true', help='检查本地数据状态')
    parser.add_argument('--demo', action='store_true', help='Demo: SPY/AAPL/MSFT')
    parser.add_argument('--full', action='store_true', help='删除本地，全量重下')
    parser.add_argument('--force', action='store_true', help='跳过本地，全量重下')
    parser.add_argument('--interval', default='both', choices=['1d', '1h', 'both'])
    parser.add_argument('--symbols', nargs='*', help='指定股票')
    args = parser.parse_args()

    codes = load_pool()

    if args.demo:
        targets = [s for s in ['SPY', 'AAPL', 'MSFT'] if s in codes]
    elif args.symbols:
        targets = [s for s in args.symbols if s in codes]
    else:
        targets = [c for c in codes if c not in {'TNX'}]

    print(f'=== 美股 K 线抓取 ===')
    print(f'  目标: {len(targets)} 只 | 固定 {MAX_TABS} Tab')

    # 全量删除
    if args.full:
        intervals = ['1d', '1h'] if args.interval == 'both' else [args.interval]
        for iv in intervals:
            cnt = 0
            for sym in targets:
                fp = _fpath(sym, iv)
                if fp.exists():
                    fp.unlink()
                    cnt += 1
            print(f'  ⚠️ 全量 [{iv}]: 删除 {cnt} 个文件')

    # 检查模式
    if args.check:
        local_ok_1d = [s for s in targets if load_local(s, '1d')]
        local_ok_1h = [s for s in targets if load_local(s, '1h')]
        print(f'  1d 本地已有: {len(local_ok_1d)} / {len(targets)} 只')
        print(f'  1h 本地已有: {len(local_ok_1h)} / {len(targets)} 只')
        return

    # 构建任务列表
    intervals = ['1d', '1h'] if args.interval == 'both' else [args.interval]
    all_tasks = [(s, iv) for s in targets for iv in intervals]

    print(f'\n开始: {len(all_tasks)} 个任务 | {MAX_TABS} Tab 并发')
    t0 = time.time()
    results = fetch_with_pool(all_tasks, CHROME_DEBUG_URL, force=args.force)
    elapsed = time.time() - t0

    ok   = [(s, r) for s, r in results.items() if r[0] == 'ok']
    fail = [(s, r) for s, r in results.items() if r[0] == 'fail']
    print(f'\n=== 完成 ({elapsed:.0f}s) ===')
    print(f'  ✅ 成功: {len(ok)}  ❌ 失败: {len(fail)}')
    if fail:
        for sym, (_, __, msg) in sorted(fail)[:10]:
            print(f'     ❌ {sym}: {msg}')
        if len(fail) > 10:
            print(f'     ... 还有 {len(fail)-10} 只')


if __name__ == '__main__':
    main()
