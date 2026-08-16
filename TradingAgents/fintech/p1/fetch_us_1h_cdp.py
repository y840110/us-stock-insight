#!/usr/bin/env python3
"""
1h K线下载器 - async Playwright，固定4 Tab 连接池
====================================================

关键设计：
1. async_playwright：规避 sync API 在 asyncio loop 线程初始化的问题
2. 固定4个 Page，全程复用，不反复开闭
3. 每 Tab 独立 Browser 连接，复用到底
4. 时间戳正确解析：使用 Yahoo meta 中的 gmtoffset 转换为美东时间（ET）
5. 快速失败：业务层0次重试，技术层最多1次重试

用法：
    python3 fetch_us_1h_cdp.py --check                   # 检查本地状态
    python3 fetch_us_1h_cdp.py --full                    # 全量回溯（删除旧数据，重新下载）
    python3 fetch_us_1h_cdp.py --update                  # 增量更新（自动判断 range）
    python3 fetch_us_1h_cdp.py --symbols AAPL MSFT GOOGL  # 指定股票
    python3 fetch_us_1h_cdp.py --demo                    # Demo: SPY/AAPL/MSFT
"""

import asyncio, json, time, argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.async_api import async_playwright

PROJ_DIR  = Path(__file__).parent.parent.parent.resolve()
WORK_DIR   = PROJ_DIR / '中间过程' / 'klines'
POOL_FILE  = PROJ_DIR / 'fintech' / 'stock_pool.json'
CHROME_DEBUG_URL = 'http://172.25.192.1:19222'

MAX_TABS   = 4
SLEEP_BETWEEN = 0.3   # 请求间隔（秒）

# Yahoo 支持的 range 选项（按时间长短排序）
RANGE_OPTIONS = ['1d', '5d', '1mo', '3mo', '6mo', '1y']

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────
def _fn(symbol):
    return symbol.lstrip('^')

def _fpath(symbol, interval):
    return WORK_DIR / f'{_fn(symbol)}_{interval}.json'

def datetime_to_ts(dt_str):
    try:
        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        dt = datetime.strptime(dt_str[:10], '%Y-%m-%d')
    return int(dt.timestamp())

def _load_local_bars(symbol, interval='1h'):
    """加载本地已有数据，返回 bars 列表"""
    fp = _fpath(symbol, interval)
    if not fp.exists() or fp.stat().st_size == 0:
        return []
    try:
        with open(fp) as f:
            d = json.load(f)
        data = d.get('data', d) if isinstance(d, dict) else d
        if not isinstance(data, list):
            return []
        return data
    except Exception:
        return []

def _latest_date(bars):
    """从 bars 中找最新日期字符串 YYYY-MM-DD"""
    if not bars:
        return None
    dates = [b.get('datetime', b.get('date', ''))[:10] for b in bars if b.get('datetime') or b.get('date')]
    return max(dates) if dates else None


# ─────────────────────────────────────────────
# 异常
# ─────────────────────────────────────────────
class TechnicalError(Exception):
    pass

class BusinessError(Exception):
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
# 本地数据操作
# ─────────────────────────────────────────────
def save_stock_data(symbol, data_list, interval='1h'):
    """增量合并保存到本地文件"""
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
    return len(merged)


# ─────────────────────────────────────────────
# 自动判断 range
# ─────────────────────────────────────────────
def _range_to_days(r: str) -> int:
    """range 字符串转天数"""
    mapping = {'1d': 1, '5d': 5, '1mo': 30, '3mo': 90, '6mo': 180, '1y': 365}
    return mapping.get(r, 365)

def _auto_range(local_bars: list) -> str:
    """
    根据本地数据最新日期和当前日期，选择最小所需 range。

    逻辑：
    - 本地数据为空或不足100根 → 1y（全量）
    - 计算本地最新日期距今天数
    - 从最短的 range 开始逐个检查，选择第一个覆盖所需天数的
    """
    if not local_bars or len(local_bars) < 100:
        return '1y'

    latest = _latest_date(local_bars)
    if not latest:
        return '1y'

    try:
        latest_dt = datetime.strptime(latest, '%Y-%m-%d')
    except ValueError:
        return '1y'

    today = datetime.now(timezone.utc)
    # 假设数据在美东时间当天收盘后更新，latest 是美东日期
    # 用北京时间减去13小时估算美东日期
    bj_offset = timedelta(hours=-13)  # 北京时间比美东快13小时
    today_et = today + bj_offset
    days_gap = (today_et.date() - latest_dt.date()).days

    if days_gap <= 0:
        # 今天的数据：在交易时段仍可能有新 bar，强制用 5d 拉取并合并
        return '5d'
    if days_gap == 1:
        # 选 5d 而非 1d：1d 在盘中只有 3 根柱，触发"<10根"校验失败；
        # 5d 约 30+ 根柱，稳定通过校验，且合并逻辑会保留最新 bar
        return '5d'
    if days_gap <= 5:
        return '5d'
    if days_gap <= 30:
        return '1mo'
    if days_gap <= 90:
        return '3mo'
    if days_gap <= 180:
        return '6mo'
    return '1y'


# ─────────────────────────────────────────────
# Yahoo 抓取（核心修复：时区）
# ─────────────────────────────────────────────
async def fetch_1h_async(page, symbol: str, range_str: str = '1y') -> tuple:
    """
    抓取 1h 数据（async）

    返回：(bars_list, meta_dict)
    meta_dict 包含 gmtoffset / timezone 等，用于正确解析时间戳

    时间戳转换逻辑：
    - Yahoo API 返回的 timestamp 是 Unix UTC 秒数
    - meta 中有 gmtoffset（如 -14400 表示 EDT，即 UTC-4）
    - 转换公式：ET_time = UTC_time + gmtoffset
    - 存储格式：美东时间字符串 "YYYY-MM-DD HH:MM:SS"
    """
    import re
    ysym = {'DXY': 'DX-Y.NYB', '^VIX': '^VIX'}.get(symbol, symbol)
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}"
           f"?range={range_str}&interval=1h")

    try:
        r = await page.goto(url, timeout=60000)
    except Exception as e:
        raise TechnicalError(f"goto failed: {e}")

    if not r or r.status != 200:
        raise TechnicalError(f"HTTP {r.status if r else 'None'}")

    content = await page.content()
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

    # ── 提取 meta（包含时区信息）─────────────────────────────
    meta = r0.get('meta', {})
    gmtoffset = meta.get('gmtoffset', -14400)  # 默认 EDT UTC-4
    tz_name = meta.get('exchangeTimezoneName', 'America/New_York')
    currency = meta.get('currency', 'USD')
    symbol_meta = meta.get('symbol', symbol)

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

    if len(timestamps) < 10:
        raise BusinessError(f"数据量异常: {len(timestamps)} 根 < 10")

    # ── 时间戳转换：正确解析为美东时间 ─────────────────────
    # Yahoo timestamps are Unix UTC seconds
    # gmtoffset is in seconds (e.g., -14400 for EDT = UTC-4)
    # We want the exchange local time (ET)
    # Formula: ET_time = UTC_time + gmtoffset
    # datetime.utcfromtimestamp(ts) gives UTC time
    # Then add gmtoffset to get ET

    # 使用一个固定的 UTC 时区来解析
    utc_tz = timezone.utc
    gmtoffset_secs = int(gmtoffset)

    data = []
    for i, ts in enumerate(timestamps):
        # UTC 时间
        utc_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        # 加上 gmtoffset 得到交易所本地时间（ET）
        et_dt = utc_dt + timedelta(seconds=gmtoffset_secs)
        data.append({
            'datetime': et_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'open':   round(float(opens[i]),  2) if opens[i]  is not None else 0,
            'high':   round(float(highs[i]),  2) if highs[i]  is not None else 0,
            'low':    round(float(lows[i]),   2) if lows[i]   is not None else 0,
            'close':  round(float(closes[i]), 2) if closes[i] is not None else 0,
            'volume': int(vols[i])             if vols[i]   is not None else 0,
        })

    data.sort(key=lambda x: datetime_to_ts(x['datetime']))

    # 附带 meta 信息
    meta_info = {
        'gmtoffset': gmtoffset_secs,
        'tz': tz_name,
        'currency': currency,
        'range_used': range_str,
    }
    return data, meta_info


async def fetch_1h_with_retry(page, symbol: str, range_str: str = '1y') -> tuple:
    """带一次技术层重试，返回 (bars, meta)"""
    try:
        return await fetch_1h_async(page, symbol, range_str)
    except TechnicalError:
        try:
            new_page = await page.context.new_page()
            await page.close()
            page.context._pages.remove(page)
            return await fetch_1h_async(new_page, symbol, range_str)
        except Exception:
            return await fetch_1h_async(page, symbol, range_str)


# ─────────────────────────────────────────────
# Tab 池（async）
# ─────────────────────────────────────────────
class AsyncTabPool:
    def __init__(self, num_tabs: int, chrome_url: str, playwright):
        self.num_tabs = num_tabs
        self.chrome_url = chrome_url
        self._pw = playwright
        self.tabs = []
        self._sem = asyncio.Semaphore(num_tabs)
        self._lock = asyncio.Lock()

    async def _init_tabs(self):
        for i in range(self.num_tabs):
            browser = None
            page = None
            try:
                browser = await self._pw.chromium.connect_over_cdp(
                    self.chrome_url, timeout=30000)
                ctx = browser.contexts[0]
                page = await ctx.new_page()
                page.set_default_timeout(60000)
            except Exception as e:
                if browser:
                    try: await browser.close()
                    except: pass
                raise TechnicalError(f"[Tab{i}] 初始化失败: {e}")

            self.tabs.append({
                'tab_id': i,
                'browser': browser,
                'page': page,
                'uses': 0,
            })
        print(f"  TabPool: {self.num_tabs} 个 Tab 全部初始化完成")

    async def is_page_alive(self, tab: dict) -> bool:
        try:
            await asyncio.wait_for(
                tab['page'].evaluate('1 + 1'),
                timeout=5
            )
            return True
        except Exception:
            return False

    async def _recycle_tab(self, tab: dict):
        tab_id = tab['tab_id']
        try:
            await tab['page'].close()
        except Exception:
            pass
        try:
            await tab['browser'].close()
        except Exception:
            pass

        try:
            browser = await self._pw.chromium.connect_over_cdp(
                self.chrome_url, timeout=30000)
            ctx = browser.contexts[0]
            page = await ctx.new_page()
            page.set_default_timeout(60000)
            tab['browser'] = browser
            tab['page'] = page
            tab['uses'] = 0
            print(f"  [Tab{tab_id}] 已重建")
        except Exception as e:
            raise TechnicalError(f"[Tab{tab_id}] 重建失败: {e}")

    async def acquire(self) -> dict:
        await self._sem.acquire()
        async with self._lock:
            for tab in self.tabs:
                if not hasattr(tab, '_in_use'):
                    tab['_in_use'] = True
                    tab['uses'] += 1
                    alive = await self.is_page_alive(tab)
                    if not alive:
                        await self._recycle_tab(tab)
                    return tab
            self._sem.release()
            await asyncio.sleep(0.05)
            return await self.acquire()

    async def release(self, tab: dict, healthy: bool = True):
        if not healthy:
            try:
                await self._recycle_tab(tab)
            except Exception:
                pass
        tab.pop('_in_use', None)
        self._sem.release()

    async def close_all(self):
        for tab in self.tabs:
            try:
                await tab['page'].close()
            except Exception:
                pass
            try:
                await tab['browser'].close()
            except Exception:
                pass

    async def run_tasks(self, tasks: list, force: bool, update_mode: bool = False,
                        full_mode: bool = False):
        """
        核心：4 Tab 轮询消费任务队列。

        force:      跳过本地，全量重下
        update_mode: 增量更新（自动判断 range）
        full_mode:   全量回溯（先删除旧数据再下）
        """
        import queue as q
        work_queue = q.Queue()
        for t in tasks:
            work_queue.put(t)

        results = {}
        results_lock = asyncio.Lock()
        active = len(tasks)

        async def worker(tab: dict):
            nonlocal active
            while True:
                try:
                    sym = work_queue.get_nowait()
                except q.Empty:
                    break

                try:
                    local = _load_local_bars(sym, '1h')

                    # ── 全量回溯：先删除本地 ──────────────────
                    if full_mode:
                        fp = _fpath(sym, '1h')
                        if fp.exists():
                            fp.unlink()
                        local = []  # 清空后全量下载

                    if update_mode and local:
                        # 增量更新：自动判断 range
                        chosen_range = _auto_range(local)
                        if chosen_range is None:
                            async with results_lock:
                                results[sym] = ('skip', len(local),
                                    f'数据最新，无需更新 | {local[0]["datetime"]}~{local[-1]["datetime"]}')
                            work_queue.task_done()
                            active -= 1
                            await self.release(tab, healthy=True)
                            continue
                        elif chosen_range == '1y':
                            # 差距太大，全量
                            fp = _fpath(sym, '1h')
                            if fp.exists():
                                fp.unlink()
                            local = []

                        bars, meta = await fetch_1h_with_retry(tab['page'], sym, chosen_range)
                        if bars:
                            save_stock_data(sym, bars, '1h')
                        async with results_lock:
                            results[sym] = ('ok', len(bars),
                                f'[{meta["range_used"]}] {bars[0]["datetime"]}~{bars[-1]["datetime"]} tz={meta["tz"]}')

                    elif force or not local:
                        # 全量下载
                        bars, meta = await fetch_1h_with_retry(tab['page'], sym, '1y')
                        save_stock_data(sym, bars, '1h')
                        async with results_lock:
                            results[sym] = ('ok', len(bars),
                                f'[1y FULL] {bars[0]["datetime"]}~{bars[-1]["datetime"]} tz={meta["tz"]}')

                    else:
                        # 增量（有本地，不强制，不 update_mode）
                        try:
                            chosen_range = _auto_range(local)
                            if chosen_range and chosen_range != '1y':
                                bars, meta = await fetch_1h_with_retry(tab['page'], sym, chosen_range)
                                if bars:
                                    save_stock_data(sym, bars, '1h')
                                async with results_lock:
                                    results[sym] = ('ok', len(bars),
                                        f'[增量{chosen_range}] {bars[0]["datetime"]}~{bars[-1]["datetime"]} tz={meta["tz"]}')
                            else:
                                async with results_lock:
                                    results[sym] = ('skip', len(local),
                                        f'本地最新({local[-1]["datetime"]})，无需更新')
                        except (TechnicalError, BusinessError) as e:
                            async with results_lock:
                                results[sym] = ('ok', len(local),
                                    f'增量失败(有{len(local)}根): {str(e)[:40]}')

                except (TechnicalError, BusinessError) as e:
                    async with results_lock:
                        results[sym] = ('fail', 0, str(e)[:80])

                work_queue.task_done()
                active -= 1
                await asyncio.sleep(SLEEP_BETWEEN)

            await self.release(tab, healthy=True)

        await asyncio.gather(
            *[worker(tab) for tab in self.tabs],
            return_exceptions=True
        )
        return results


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────
async def main_async(args):
    codes = load_pool()

    if args.demo:
        targets = [s for s in ['SPY', 'AAPL', 'MSFT'] if s in codes]
    elif args.symbols:
        targets = [s for s in args.symbols if s in codes]
    else:
        targets = [c for c in codes if c not in {'TNX'}]

    mode = '全量回溯' if args.full else ('增量更新' if args.update else ('强制全下' if args.force else '增量（有则补）'))
    print(f'=== 1h K线下载器 ===')
    print(f'  目标: {len(targets)} 只 | 固定 {MAX_TABS} Tab | 模式: {mode}')

    # ── 检查状态 ─────────────────────────────────────
    if args.check:
        local_ok = [s for s in targets if _load_local_bars(s, '1h')]
        print(f'  本地已有: {len(local_ok)} 只')
        for s in local_ok[:10]:
            bars = _load_local_bars(s, '1h')
            latest = _latest_date(bars)
            rng = _auto_range(bars) or '最新'
            print(f'    {s:<8}: {len(bars)} bars | 最新 {latest} | 建议 range: {rng}')
        if len(local_ok) > 10:
            print(f'    ... 还有 {len(local_ok)-10} 只')
        return

    # ── 全量删除（--full 模式下先删） ─────────────────
    if args.full:
        cnt = 0
        for sym in targets:
            fp = _fpath(sym, '1h')
            if fp.exists():
                fp.unlink()
                cnt += 1
        print(f'  ⚠️ 全量删除: {cnt} 个文件')

    # ── 启动 Tab 池 ─────────────────────────────────
    async with asyncio.timeout(900):
        pw = await async_playwright().start()
        pool = AsyncTabPool(MAX_TABS, CHROME_DEBUG_URL, pw)
        await pool._init_tabs()

        print(f'\n开始下载 {len(targets)} 只...')
        t0 = time.time()
        results = await pool.run_tasks(
            targets,
            force=args.force,
            update_mode=args.update,
            full_mode=args.full,
        )
        elapsed = time.time() - t0

        await pool.close_all()
        await pw.stop()

    # ── 汇总 ────────────────────────────────────────
    ok   = [(s, r) for s, r in results.items() if r[0] == 'ok']
    fail = [(s, r) for s, r in results.items() if r[0] == 'fail']
    skip = [(s, r) for s, r in results.items() if r[0] == 'skip']
    print(f'\n=== 完成 ({elapsed:.0f}s) ===')
    print(f'  ✅ 成功: {len(ok)}  ❌ 失败: {len(fail)}  ⏭️ 跳过: {len(skip)}')
    if skip:
        for sym, (_, cnt, msg) in sorted(skip)[:5]:
            print(f'     ⏭️ {sym}: {msg}')
    if fail:
        for sym, (_, __, msg) in sorted(fail)[:10]:
            print(f'     ❌ {sym}: {msg}')
        if len(fail) > 10:
            print(f'     ... 还有 {len(fail)-10} 只')


def main():
    parser = argparse.ArgumentParser(
        description='1h K线下载器 - async 4 Tab | 时区修正版')
    parser.add_argument('--check',   action='store_true', help='检查本地状态')
    parser.add_argument('--demo',    action='store_true', help='Demo: SPY/AAPL/MSFT')
    parser.add_argument('--full',   action='store_true',
                        help='全量回溯：删除旧数据，重新下载（1y）')
    parser.add_argument('--update', action='store_true',
                        help='增量更新：自动判断 range（1d/5d/1mo/3mo/6mo/1y）')
    parser.add_argument('--force',  action='store_true',
                        help='强制全量重下（不清旧数据，但跳过增量逻辑）')
    parser.add_argument('--symbols', nargs='*', help='指定股票代码')
    args = parser.parse_args()

    from playwright.async_api import async_playwright
    asyncio.run(main_async(args))


if __name__ == '__main__':
    main()
