#!/usr/bin/env python3
"""
P1 每日统一更新入口
===================
一次性执行 P1 层所有数据更新与分析：
  1. K线抓取（Yahoo Finance，单线程 + retry）
  2. finviz 广度更新
  3. FRED 宏观指标（US10Y、HY Spread）
  4. CBOE 专属指标（Put/Call Ratio、NYAD 等）
  5. 健康回踩检测
  6. 危险变盘检测
  7. 趋势健康度计算
  8. P1 HTML 报告输出

用法：
  python3 fintech/p1/p1_main.py           # 完整流程
  python3 fintech/p1/p1_main.py --check   # 仅检查新鲜度
  python3 fintech/p1/p1_main.py --symbols AAPL MSFT  # 只抓指定股票
"""
import os, sys, time, importlib
from pathlib import Path
from datetime import date

PROJ  = Path(__file__).parent.parent.parent
P1    = Path(__file__).parent
WORK  = PROJ / "中间过程" / "klines"
STATE = P1 / "state"
CHROME_DEBUG_URL = 'http://172.25.192.1:19222'

WORK.mkdir(parents=True, exist_ok=True)
STATE.mkdir(parents=True, exist_ok=True)

os.environ['PYTHONPATH'] = str(PROJ)


def load_pool():
    pool_file = PROJ / "fintech" / "stock_pool.json"
    d = __import__('json').load(open(pool_file))
    return [s['code'] for s in d.get('stocks', []) if s.get('code')]


def step_klines(symbols):
    """K线抓取：1d + 1h（统一用 fetch_us_stocks_cdp）"""
    print("\n" + "="*60)
    print("📡 Step 1: K线抓取（1d + 1h）")
    print("="*60)

    sys.path.insert(0, str(P1))
    from fetch_us_stocks_cdp import fetch_with_pool, load_pool as _lp

    pool = symbols if symbols else [c for c in _lp() if c not in ('DXY', '^VIX')]
    pool = [c for c in pool if c not in ('DXY', '^VIX')]

    # 构建任务列表（1d + 1h 一起，用 fetch_with_pool 统一处理）
    all_tasks = [(s, '1d') for s in pool] + [(s, '1h') for s in pool]

    # 增量过滤：已有本地数据的任务跳过
    from fetch_us_stocks_cdp import load_local as ll_1d
    from fetch_us_1h_cdp import load_local as ll_1h
    stale_tasks = []
    for sym, iv in all_tasks:
        loader = ll_1d if iv == '1d' else ll_1h
        if not loader(sym, iv):
            stale_tasks.append((sym, iv))

    if stale_tasks:
        print(f"\n  待更新: {len(stale_tasks)} 个任务（{len(pool)} 只 × 2 频）")
        t0 = time.time()
        results = fetch_with_pool(stale_tasks, CHROME_DEBUG_URL, force=False)
        elapsed = time.time() - t0
        ok   = [(s, r) for s, r in results.items() if r[0] == 'ok']
        fail = [(s, r) for s, r in results.items() if r[0] == 'fail']
        print(f"  ✅ 成功: {len(ok)}  ❌ 失败: {len(fail)}  ({elapsed:.0f}s)")
        if fail:
            for s, (_, __, msg) in sorted(fail)[:5]:
                print(f"     ❌ {s}: {msg}")
    else:
        print(f"\n  全部 {len(pool)} 只 1d+1h 数据已存在，跳过")

    return 0, 0


def step_breadth():
    """finviz 广度抓取"""
    print("\n" + "="*60)
    print("🌐 Step 2: finviz 广度数据")
    print("="*60)
    try:
        spec = importlib.util.spec_from_file_location('market_breadth', P1 / 'features' / 'market_breadth.py')
        mb   = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mb)
        r = mb.update_breadth()
        if r:
            print(f"  ✅ SMA50={r.get('above_sma50',0)*100:.1f}%  SMA200={r.get('above_sma200',0)*100:.1f}%")
            print(f"     上涨={r.get('advancing_pct',0)*100:.1f}%  下跌={r.get('declining_pct',0)*100:.1f}%")
            print(f"     52W新高={r.get('new_high_cnt')}  新低={r.get('new_low_cnt')}")
        return r
    except Exception as e:
        print(f"  ❌ {e}")
        return None


def step_pullback():
    """健康回踩检测"""
    print("\n" + "="*60)
    print("🔍 Step 3: 健康回踩检测")
    print("="*60)
    try:
        spec = importlib.util.spec_from_file_location('pullback_detector', P1 / 'features' / 'pullback_detector.py')
        pd   = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pd)
        r = pd.detect_healthy_pullback()
        pd.save_pullback_state(r)
        sig = r.get('signal', '?')
        print(f"  信号: {sig}")
        for cname, c in r.get('checks', {}).items():
            tag = '✅' if c.get('ok') else '❌'
            print(f"    {tag} {cname}: {c.get('reason','')}")
        return r
    except Exception as e:
        print(f"  ❌ {e}")
        return None


def step_dangerous_shift():
    """危险变盘检测"""
    print("\n" + "="*60)
    print("🚨 Step 4: 危险变盘检测")
    print("="*60)
    try:
        spec = importlib.util.spec_from_file_location('dangerous_shift_detector', P1 / 'features' / 'dangerous_shift_detector.py')
        ds   = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ds)
        r = ds.detect_dangerous_shift()
        sig  = r.get('signal', '?')
        cnt  = r.get('danger_count', 0)
        print(f"  信号: {sig} ({cnt}/5)")
        for cname, c in r.get('checks', {}).items():
            tag = '✅' if not c.get('ok') else '🚨'
            print(f"    {tag} {cname}: {c.get('reason','')}")
        return r
    except Exception as e:
        print(f"  ❌ {e}")
        return None


def step_trend_health():
    """趋势健康度计算"""
    print("\n" + "="*60)
    print("📊 Step 5: 趋势健康度评分")
    print("="*60)
    try:
        spec = importlib.util.spec_from_file_location('trend_health_detector', P1 / 'features' / 'trend_health_detector.py')
        th   = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(th)
        r = th.calc_trend_health()
        score = r.get('total_score', 0)
        state = r.get('state', '?')
        icon  = r.get('state_icon', '')
        cons  = r.get('consensus', '')
        print(f"  {icon} {state} ({score}/100) | {cons}")
        for fname, f in r.get('factors', {}).items():
            pct = f.get('pct', 0)
            bar = '█' * int(pct/10) + '░' * (10 - int(pct/10))
            print(f"    {fname:<20} {f.get('score',0):>3}/{f.get('max',100):<3} {bar} {f.get('label','')}")
        return r
    except Exception as e:
        print(f"  ❌ {e}")
        return None


def step_report():
    """P1 HTML 报告"""
    print("\n" + "="*60)
    print("📄 Step 8: P1 HTML 报告")
    print("="*60)
    try:
        spec = importlib.util.spec_from_file_location('p1_report_writer', P1 / 'p1_report_writer.py')
        rw   = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rw)
        out = rw.build_report()
        print(f"  ✅ {out}")
        return out
    except Exception as e:
        print(f"  ❌ {e}")
        return None


def step_fred_indicators():
    """FRED 宏观指标（US10Y、HY Spread）"""
    print("\n" + "="*60)
    print("📊 Step 3: FRED 宏观指标")
    print("="*60)
    try:
        import fetch_market_indicators_fred as fred_mod
        r = fred_mod.fetch_all(lookback_days=5)
        for sym, records in r.items():
            if records:
                latest = records[-1]
                print(f"  ✅ {sym}: {latest['date']} = {latest['value']}")
            else:
                print(f"  ⚠️  {sym}: 无数据")
        return r
    except Exception as e:
        print(f"  ❌ {e}")
        return None


def step_cboe_indicators():
    """CBOE 专属指标（Put/Call Ratio、NYAD 等）"""
    print("\n" + "="*60)
    print("📈 Step 4: CBOE 专属指标")
    print("="*60)
    try:
        import fetch_cboe_indicators as cboe_mod
        r = cboe_mod.fetch_all(lookback_days=30)
        for sym, records in r.items():
            if records:
                latest = records[-1]
                print(f"  ✅ {sym}: {latest['date']} = {latest['value']}")
            else:
                print(f"  ⚠️  {sym}: 无数据（后续处理）")
        return r
    except Exception as e:
        print(f"  ❌ {e}")
        return None


# ─────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="P1 每日统一更新")
    parser.add_argument('--check',   action='store_true', help='仅检查新鲜度')
    parser.add_argument('--symbols', nargs='*',           help='只抓指定股票')
    args = parser.parse_args()

    print("="*60)
    print("  P1 · 数据层  每日统一更新")
    print(f"  日期: {date.today()}")
    print("="*60)

    # 检查模式
    if args.check:
        from fetch_us_stocks_cdp import load_local, load_pool as _lp
        pool = _lp()
        missing_1d = []
        missing_1h = []
        for s in pool:
            if s in ('DXY', '^VIX'):
                continue
            bars_1d = load_local(s, '1d')
            bars_1h = load_local(s, '1h')
            if not bars_1d:
                missing_1d.append(s)
            if not bars_1h:
                missing_1h.append(s)
        print(f"\n  1d 缺失: {len(missing_1d)} 只")
        for s in missing_1d[:10]:
            print(f"    ❌ {s}: 无本地 1d 数据")
        if len(missing_1d) > 10:
            print(f"    ... 还有 {len(missing_1d)-10} 只")
        print(f"\n  1h 缺失: {len(missing_1h)} 只")
        for s in missing_1h[:10]:
            print(f"    ❌ {s}: 无本地 1h 数据")
        if len(missing_1h) > 10:
            print(f"    ... 还有 {len(missing_1h)-10} 只")
        return

    # 完整流程
    step_klines(args.symbols)
    step_breadth()
    step_fred_indicators()
    step_cboe_indicators()
    step_pullback()
    step_dangerous_shift()
    step_trend_health()
    step_report()

    print("\n" + "="*60)
    print("  P1 每日更新完成 ✅")
    print("="*60)


if __name__ == "__main__":
    main()
