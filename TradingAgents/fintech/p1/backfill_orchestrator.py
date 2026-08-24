#!/usr/bin/env python3
"""
历史数据回溯编排器
===================
将 Yahoo 730 天限制拆分为多个 period 段，回溯到指定目标日期。

设计原则（与 fetch_us_stocks_cdp.py 一致）：
1. 分段回溯，每段完成后验证，发现问题立即停
2. 固定4 Tab 连接池，防止 Chrome OOM
3. 快速失败：业务层验证失败立即中止
4. 每只股票独立 merge，不污染其他股票

用法：
  python3 backfill_orchestrator.py --interval 1d --demo AAPL   # AAPL 单只测试
  python3 backfill_orchestrator.py --interval 1d --dry          # 预览，不执行
  python3 backfill_orchestrator.py --interval 1d --force       # 删除现有重新来
  python3 backfill_orchestrator.py --interval 1d               # 正式全量回溯
  python3 backfill_orchestrator.py --interval 1h
"""
import json, time, sys, argparse, threading, queue
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from playwright.sync_api import sync_playwright

PROJ_DIR  = Path(__file__).parent.parent.parent.resolve()
WORK_DIR   = PROJ_DIR / '中间过程' / 'klines'
POOL_FILE  = PROJ_DIR / 'fintech' / 'stock_pool.json'
CHROME_DEBUG_URL = 'http://172.25.192.1:19222'

MAX_TABS  = 4
SLEEP_BETWEEN = 0.3   # 请求间隔（秒），防 Yahoo 限流

# Yahoo 每次最多返回 730 天，period 段不能超过此限制
MAX_DAYS_PER_REQUEST = 700   # 留一点余量

# ─────────────────────────────────────────────
# 时间工具
# ─────────────────────────────────────────────
def dt_to_ts(dt_str: str) -> int:
    """'2020-01-01' 或 '2020-01-01 00:00:00' → Unix timestamp"""
    try:
        return int(datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S').timestamp())
    except ValueError:
        return int(datetime.strptime(dt_str[:10], '%Y-%m-%d').timestamp())

def ts_to_dt(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')

def next_year_start(d: date) -> date:
    """下一年1月1日"""
    return date(d.year + 1, 1, 1)

# ─────────────────────────────────────────────
# period 段生成
# ─────────────────────────────────────────────
def build_periods(target_start: date, target_end: date):
    """
    将 [target_start, target_end] 拆成多个 period 段，
    每段不超过 MAX_DAYS_PER_REQUEST 天。
    返回 [(period1_ts, period2_ts, label), ...]，升序排列。
    """
    periods = []
    cur = target_start
    while cur < target_end:
        # 段结束：下一年1月1日 或 target_end，取较小者
        seg_end = min(next_year_start(cur), target_end)
        # 但每段不超过 MAX_DAYS_PER_REQUEST 天
        max_date = cur + timedelta(days=MAX_DAYS_PER_REQUEST)
        if seg_end > max_date:
            seg_end = max_date
        periods.append((
            int(datetime(cur.year, cur.month, cur.day, 0, 0, 0).timestamp()),
            int(datetime(seg_end.year, seg_end.month, seg_end.day, 0, 0, 0).timestamp()),
            f"{cur} → {seg_end}"
        ))
        cur = seg_end
    return periods

# ─────────────────────────────────────────────
# 数据读写
# ─────────────────────────────────────────────
def _fn(symbol):
    return symbol.lstrip('^')

def _fpath(symbol, interval):
    return WORK_DIR / f'{_fn(symbol)}_{interval}.json'

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
        dt_key = 'datetime' if interval == '1h' else 'date'
        return [e[dt_key] for e in data if isinstance(e, dict) and dt_key in e]
    except Exception:
        return []

def save_stock_data(symbol, data_list, interval):
    """增量合并写入：本地数据 + 新数据 → 去重排序 → 写回"""
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

    dt_key = 'datetime' if interval == '1h' else 'date'
    date_map = {e[dt_key]: e for e in existing}
    for e in data_list:
        date_map[e[dt_key]] = e

    merged = sorted(date_map.values(), key=lambda x: dt_to_ts(x[dt_key]))
    with open(fp, 'w') as f:
        json.dump({'data': merged}, f, indent=2)

# ─────────────────────────────────────────────
# Yahoo 抓取（直接用 fetch_us_stocks_cdp 的 _fetch_url）
# ─────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from fetch_us_stocks_cdp import fetch_yahoo_period, TechnicalError, BusinessError

# ─────────────────────────────────────────────
# Tab Worker
# ─────────────────────────────────────────────
def tab_worker(tab_id: int, work_queue: queue.Queue, results: dict,
               lock: threading.Lock, chrome_url: str):
    """
    从 work_queue 取任务：(symbol, interval, [(period1, period2, label), ...])
    顺序处理每段，merge 到本地文件。
    """
    browser = None
    page = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(chrome_url, timeout=30000)
        ctx = browser.contexts[0]
        page = ctx.new_page()
        page.set_default_timeout(90000)   # 历史数据可能稍慢

        while True:
            try:
                task = work_queue.get_nowait()
                if task is None:
                    work_queue.task_done()
                    break
                sym, iv, periods = task
            except queue.Empty:
                break

            total_bars = 0
            fail_reason = None

            skipped_early = []   # 记录因历史不存在而跳过的段
            for p1, p2, label in periods:
                try:
                    bars = fetch_yahoo_period(page, sym, iv, p1, p2)
                    if not bars:
                        raise BusinessError(f"段 {label} 返回空数据")
                    save_stock_data(sym, bars, iv)
                    total_bars += len(bars)
                    time.sleep(SLEEP_BETWEEN)
                except TechnicalError as e:
                    err_str = str(e)
                    # HTTP 400/404 说明该段历史不存在（IPO 较晚），跳过并继续
                    if 'HTTP 400' in err_str or 'HTTP 404' in err_str:
                        skipped_early.append(label)
                        continue
                    fail_reason = f"段 {label} 技术失败: {err_str[:60]}"
                    break   # 其他技术错误快速失败
                except BusinessError as e:
                    err_str = str(e)
                    # HTTP 400/404 / Yahoo error / 数据量异常 → IPO 早于段起始日，跳过
                    if any(x in err_str for x in ('HTTP 400', 'HTTP 404', 'Yahoo error', '数据量异常')):
                        skipped_early.append(label)
                        continue
                    fail_reason = f"段 {label} 业务失败: {err_str[:60]}"
                    break

            # 读取最终文件，验证日期范围
            fp = _fpath(sym, iv)
            local = load_local(sym, iv)
            with lock:
                if fail_reason:
                    results[sym] = ('fail', total_bars, fail_reason)
                elif not local:
                    results[sym] = ('fail', 0, f'所有段均无数据（可能IPO于{target_start}之后）')
                else:
                    skip_msg = f' [{len(skipped_early)}段跳过]' if skipped_early else ''
                    results[sym] = ('ok', total_bars,
                        f'{local[0]} → {local[-1]} [{len(local)} bars]{skip_msg}')

            work_queue.task_done()

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
# 分段回溯
# ─────────────────────────────────────────────
def backfill_interval(interval: str, target_years_back: int,
                      demo_symbols: list = None,
                      dry: bool = False, force: bool = False,
                      target_start: date = None):
    """
    interval: '1d' 或 '1h'
    target_years_back: 从当前往回多少年（当 target_start 未指定时使用）
    target_start: 固定起始日期（优先于滚动年数）
    """
    target_end = date.today()
    if target_start is None:
        target_start = date(target_end.year - target_years_back, target_end.month, target_end.day)

    print(f"\n{'='*60}")
    print(f"📡 回溯 {interval} | 目标: {target_start} → {target_end}")
    print(f"{'='*60}")

    # 加载股票池
    with open(POOL_FILE) as f:
        pool = json.load(f)
    all_symbols = [s['code'] for s in pool['stocks']]
    special = pool.get('_special_symbols', {})
    for sym in special:
        if sym not in {'TNX'} and sym not in all_symbols:
            all_symbols.append(sym)

    targets = demo_symbols or [c for c in all_symbols if c not in ('DXY', '^VIX', 'TNX')]
    print(f"  股票数量: {len(targets)}")

    # 生成 period 段
    periods = build_periods(target_start, target_end)
    print(f"  分段数量: {len(periods)}")
    for p1, p2, lbl in periods:
        print(f"    {lbl}  ({ts_to_dt(p1)} → {ts_to_dt(p2)})")

    if dry:
        print("\n  ✅ Dry Run，以上计划不执行")
        return None, None, None

    # 删除现有文件（force 模式）
    if force:
        cnt = 0
        for sym in targets:
            fp = _fpath(sym, interval)
            if fp.exists():
                fp.unlink()
                cnt += 1
        print(f"\n  ⚠️ Force: 删除 {cnt} 个现有 {interval} 文件")

    # 预览每只股票的现有日期范围
    print(f"\n  现有数据预览（前10只）:")
    for sym in targets[:10]:
        local = load_local(sym, interval)
        if local:
            print(f"    {sym}: {local[0]} → {local[-1]} [{len(local)} bars]")
        else:
            print(f"    {sym}: 无数据")

    # 构建任务
    work_queue = queue.Queue()
    results = {}
    lock = threading.Lock()

    for sym in targets:
        work_queue.put((sym, interval, periods))

    # 启动4个 Tab worker
    threads = []
    for i in range(MAX_TABS):
        t = threading.Thread(target=tab_worker,
                           args=(i, work_queue, results, lock, CHROME_DEBUG_URL))
        t.start()
        threads.append(t)

    # 等待完成
    work_queue.join()
    for _ in range(MAX_TABS):
        work_queue.put(None)
    for t in threads:
        t.join()

    # 汇总
    ok = {k: v for k, v in results.items() if v[0] == 'ok'}
    fail = {k: v for k, v in results.items() if v[0] == 'fail'}

    print(f"\n{'='*60}")
    print(f"📊 回溯结果: {len(ok)} ✅  {len(fail)} ❌")
    if fail:
        print("  失败列表:")
        for sym, (st, cnt, msg) in fail.items():
            print(f"    {sym}: [{cnt} bars] {msg}")
    return results, ok, fail


# ─────────────────────────────────────────────
# 验证脚本
# ─────────────────────────────────────────────
def validate_interval(interval: str, target_start: date, demo_symbols: list = None):
    """回溯完成后，验证日期范围是否达标"""
    print(f"\n{'='*60}")
    print(f"🔍 验证 {interval} 数据范围 | 期望: ≥ {target_start}")
    print(f"{'='*60}")

    with open(POOL_FILE) as f:
        pool = json.load(f)
    all_symbols = [s['code'] for s in pool['stocks']]

    targets = demo_symbols or [c for c in all_symbols if c not in ('DXY', '^VIX', 'TNX')]

    ok_list, fail_list = [], []

    for sym in targets:
        fp = _fpath(sym, interval)
        if not fp.exists() or fp.stat().st_size == 0:
            fail_list.append((sym, '文件不存在'))
            continue
        try:
            with open(fp) as f:
                d = json.load(f)
            data = d.get('data', d) if isinstance(d, dict) else d
            if not data:
                fail_list.append((sym, '文件为空'))
                continue
            dt_key = 'datetime' if interval == '1h' else 'date'
            first = data[0][dt_key][:10] if data else ''
            last = data[-1][dt_key][:10] if data else ''
            first_d = date.fromisoformat(first[:10])
            if first_d <= target_start:
                ok_list.append((sym, first, last, len(data)))
            else:
                fail_list.append((sym, f'起始日期 {first} > {target_start}'))
        except Exception as e:
            fail_list.append((sym, f'解析错误: {e}'))

    print(f"  ✅ 达标: {len(ok_list)}")
    print(f"  ❌ 不达标: {len(fail_list)}")
    if fail_list:
        for sym, reason in fail_list[:10]:
            print(f"    {sym}: {reason}")

    # 展示达标样本
    print(f"\n  达标样本（前5只）:")
    for sym, first, last, cnt in ok_list[:5]:
        print(f"    {sym}: {first} → {last} [{cnt} bars]")
    print(f"  总达标率: {len(ok_list)}/{len(targets)}")

    return ok_list, fail_list


# ─────────────────────────────────────────────
# main
# ─────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='历史数据回溯编排器')
    parser.add_argument('--interval', required=True, choices=['1d', '1h'],
                        help='回溯的 K 线周期')
    parser.add_argument('--years', type=int, default=None,
                        help='往回多少年（默认 1d=8年，1h=4年）')
    parser.add_argument('--demo', nargs='*', help='只回溯指定股票（demo 模式）')
    parser.add_argument('--dry', action='store_true', help='预览计划，不执行')
    parser.add_argument('--force', action='store_true', help='删除现有文件重新来')
    parser.add_argument('--validate', action='store_true',
                        help='仅验证现有数据范围，不回溯')
    parser.add_argument('--start', type=str, default=None,
                        help='固定起始日期 YYYY-MM-DD（优先于 --years）')
    parser.add_argument('--check', action='store_true',
                        help='检查现有数据的起始日期分布')
    args = parser.parse_args()

    # 默认回溯年数
    DEFAULT_YEARS = {'1d': 8, '1h': 4}
    years = args.years or DEFAULT_YEARS[args.interval]
    if args.start:
        target_start = date.fromisoformat(args.start)
    else:
        target_start = date(date.today().year - years, date.today().month, date.today().day)

    if args.check:
        # 只检查，不回溯
        validate_interval(args.interval, target_start, demo_symbols=args.demo)
        sys.exit(0)

    if args.validate:
        validate_interval(args.interval, target_start, demo_symbols=args.demo)
        sys.exit(0)

    if args.demo:
        print(f"\n🚀 Demo 模式: 只回溯 {args.demo}")

    results, ok, fail = backfill_interval(
        interval=args.interval,
        target_years_back=years,
        demo_symbols=args.demo,
        dry=args.dry,
        force=args.force,
        target_start=target_start,
    )

    if not args.dry:
        print(f"\n✅ 回溯完成，验证日期范围...")
        validate_interval(args.interval, target_start, demo_symbols=args.demo)
