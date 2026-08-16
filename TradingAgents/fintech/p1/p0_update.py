#!/usr/bin/env python3
"""
P0 数据更新入口
================
统一管理所有美股数据的更新场景。

场景：
  python3 p0_update.py --check              快速检查数据新鲜度（1d + 1h + 外部指标）
  python3 p0_update.py --pre-market         开盘前：全量检查 + 补漏
  python3 p0_update.py --intraday           盘中：小时增量更新 1h + 计算小时线指标
  python3 p0_update.py --post-market        盘后：更新日线 + 1h + 计算日线指标
  python3 p0_update.py --full               全量重建（1d + 1h + 全部指标）
  python3 p0_update.py --externals           仅更新外部指标（GEX/VIX/TNX/COT/Gamma/Fed）

数据源：
  1d/1h K线    → fetch_us_stocks_cdp.py / fetch_us_1h_cdp.py
  GEX          → fetch_cboe_gex_chrome.py
  VIX/TNX      → fetch_vix_tnx_fred.py
  COT CTA      → fetch_cot_cta.py
  Gamma Regime → fetch_gamma_regime_chrome.py
  Fed H41      → fetch_fed_h41_chrome.py

输出目录：
  klines/             → 1d / 1h K线 + VIX/TNX/COT
  market_indicators/  → GEX/SPX_GAMMA/PUT_CALL_RATIO/GAMMA_REGIME
  中间过程/indicators/ → {sym}_1d_indicators.json / {sym}_1h_indicators.json
"""

import json
import subprocess
import sys
import time
import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas_market_calendars as mcal
import zoneinfo

PROJ   = Path(__file__).parent.parent.parent.resolve()
P1     = PROJ / 'fintech' / 'p1'
INDICATORS_DIR = PROJ / '中间过程' / 'indicators'

# 确保输出目录存在
INDICATORS_DIR.mkdir(parents=True, exist_ok=True)

# ── NYSE 交易日历 ──────────────────────────────────────────────
_nyse = None
def nyse():
    global _nyse
    if _nyse is None:
        import pandas_market_calendars as mcal
        _nyse = mcal.get_calendar('NYSE')
    return _nyse

def is_trading_day(d=None):
    d = d or date.today()
    days = nyse().valid_days(
        start_date=(d - timedelta(days=7)).strftime('%Y-%m-%d'),
        end_date=(d + timedelta(days=1)).strftime('%Y-%m-%d')
    )
    return d.strftime('%Y-%m-%d') in {str(x.date()) for x in days}

def last_closed_trading_day():
    """返回最后一个已收盘的交易日（今天若已收盘也包含）"""
    today = date.today()
    today_str = today.strftime('%Y-%m-%d')

    # Get recent trading days
    days = nyse().valid_days(
        start_date=(today - timedelta(days=7)).strftime('%Y-%m-%d'),
        end_date=(today + timedelta(days=1)).strftime('%Y-%m-%d')
    )
    trading_days_set = {str(x.date()) for x in days}

    # Current ET time
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(zoneinfo.ZoneInfo('America/New_York'))
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)

    if today_str in trading_days_set and now_et >= market_close:
        return today
    # Find most recent past trading day
    for d in [today - timedelta(days=i) for i in range(1, 10)]:
        if d.strftime('%Y-%m-%d') in trading_days_set:
            return d
    return today - timedelta(days=1)

def get_last_n_trading_days(n=5):
    today = date.today()
    days = nyse().valid_days(
        start_date=(today - timedelta(days=n*3)).strftime('%Y-%m-%d'),
        end_date=today.strftime('%Y-%m-%d')
    )
    return sorted([str(x.date()) for x in days])[-n:]

# ── 数据新鲜度检查 ──────────────────────────────────────────────
def get_tickers():
    with open(PROJ / 'fintech' / 'stock_pool.json') as f:
        pool = json.load(f)
    return [s['code'] for s in pool['stocks']]

def latest_date_1d(ticker):
    f = PROJ / '中间过程' / 'klines' / f'{ticker}_1d.json'
    if not f.exists(): return None
    with open(f) as fh:
        d = json.load(fh)
    bars = d.get('data', [])
    return bars[-1]['date'] if bars else None

def latest_datetime_1h(ticker):
    f = PROJ / '中间过程' / 'klines' / f'{ticker}_1h.json'
    if not f.exists(): return None
    with open(f) as fh:
        d = json.load(fh)
    bars = d.get('data', [])
    return bars[-1]['datetime'] if bars else None

def check_freshness():
    """检查所有数据新鲜度，返回报告字典"""
    tickers = get_tickers()
    today_str = date.today().strftime('%Y-%m-%d')
    last_td = last_closed_trading_day().strftime('%Y-%m-%d')
    trading_days_after = get_last_n_trading_days(10)

    stale_1d, stale_1h = [], []

    for t in sorted(tickers):
        d1 = latest_date_1d(t)
        h1 = latest_datetime_1h(t)
        missing_1d = [d for d in trading_days_after if d > (d1 or '1900') and d <= last_td]
        now_et = datetime.now(timezone.utc).astimezone(zoneinfo.ZoneInfo('America/New_York'))
        cutoff = now_et.replace(hour=16, minute=30, second=0, microsecond=0)
        past_close_today = is_trading_day() and now_et >= cutoff
        missing_1h_today = past_close_today and (today_str not in (h1 or ''))
        if missing_1d:
            stale_1d.append((t, d1, missing_1d))
        elif missing_1h_today:
            stale_1h.append((t, h1))

    return {
        'today': today_str,
        'last_closed': last_td,
        'stale_1d': stale_1d,
        'stale_1h': stale_1h,
        'ok_1d': len(tickers) - len(stale_1d),
        'ok_1h': len(tickers) - len(stale_1h),
        'total': len(tickers),
    }

# ── 执行子脚本 ────────────────────────────────────────────────
def run(script_name, args, timeout=600, quiet=False):
    """运行 P1 子脚本，返回 (success, elapsed_seconds, stdout+stderr)"""
    script = P1 / script_name
    if not script.exists():
        return False, 0, f"Script not found: {script}"
    cmd = ['python3', str(script)] + args
    start = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        elapsed = time.time() - start
        out = (r.stdout + r.stderr).strip()
        if not quiet and out:
            print(f"  [{script_name}] {out[-300:]}")
        return r.returncode == 0, elapsed, out
    except subprocess.TimeoutExpired:
        return False, timeout, "Timeout"
    except Exception as e:
        return False, 0, str(e)

def run_bg(script_name, args):
    """后台运行子脚本"""
    script = P1 / script_name
    cmd = ['python3', str(script)] + args
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ── 场景实现 ────────────────────────────────────────────────
def do_check():
    r = check_freshness()
    print(f"\n📊 数据新鲜度检查")
    print(f"   今天: {r['today']} | 最后收盘交易日: {r['last_closed']}")
    print(f"   股票: {r['total']} 只")
    print(f"   1d OK: {r['ok_1d']}  {'✅' if r['ok_1d']==r['total'] else '⚠️'} | "
          f"1h OK: {r['ok_1h']}  {'✅' if r['ok_1h']==r['total'] else '⚠️'}")
    if r['stale_1d']:
        print(f"   1d 缺交易日({len(r['stale_1d'])}只): {[x[0] for x in r['stale_1d'][:5]]}{'...' if len(r['stale_1d'])>5 else ''}")
    if r['stale_1h']:
        print(f"   1h 缺今日({len(r['stale_1h'])}只): {[x[0] for x in r['stale_1h'][:5]]}{'...' if len(r['stale_1h'])>5 else ''}")
    if not r['stale_1d'] and not r['stale_1h']:
        print(f"   ✅ 所有数据已是最新")
    return r

def do_pre_market():
    print(f"\n🌅 开盘前数据准备")
    print(f"   今日: {date.today()} | 是否交易日: {is_trading_day()}")
    r = check_freshness()

    tasks = []

    # 1d 缺漏 → 补日线
    if r['stale_1d']:
        missing_days = set()
        for _, _, days in r['stale_1d']:
            missing_days.update(days)
        print(f"   📅 缺日线数据: {sorted(missing_days)}")
        tasks.append(('1d_force', ['--force', '--interval', 'both']))
    else:
        print(f"   ✅ 日线已是最新")

    # 1h 缺今日 → 补1h
    if r['stale_1h']:
        print(f"   ⏰ 缺1h今日数据: {len(r['stale_1h'])}只")
        tasks.append(('1h_update', ['--update']))
    else:
        print(f"   ✅ 1h 已是最新")

    if not tasks:
        print(f"   ✅ 无需更新，开盘前准备完成")
        return

    print(f"\n🚀 开始更新...")
    total_start = time.time()
    for name, args in tasks:
        script = {'1d_force': 'fetch_us_stocks_cdp.py', '1h_update': 'fetch_us_1h_cdp.py'}[name]
        print(f"\n   ── {name} ──")
        ok, elapsed, _ = run(script, args, timeout=900, quiet=False)
        status = '✅' if ok else '❌'
        print(f"   {status} {name} 完成 ({elapsed:.0f}s)")

    # 外部指标（开盘前尽量更新）
    print(f"\n   ── 外部指标 ──")
    _update_externals(quiet=False)

    total_elapsed = time.time() - total_start
    print(f"\n✅ 开盘前准备完成 ({total_elapsed:.0f}s)")

def do_intraday():
    print(f"\n⏰ 盘中增量更新（1h + 小时线指标）")
    r = check_freshness()
    if not r['stale_1h']:
        print(f"   ✅ 1h 数据已是最新")
    else:
        print(f"   缺今日 1h 数据: {len(r['stale_1h'])} 只")
        ok, elapsed, _ = run('fetch_us_1h_cdp.py', ['--update'], timeout=300)
        status = '✅' if ok else '❌'
        print(f"   {status} 1h 更新完成 ({elapsed:.0f}s)")

    # 计算小时级指标
    _compute_hourly_indicators_batch()

def do_post_market():
    print(f"\n🌙 盘后数据更新（1d + 1h + 日线指标）")
    print(f"   今天: {date.today()}")

    tasks = [
        ('1d_force', 'fetch_us_stocks_cdp.py', ['--force', '--interval', 'both']),
        ('1h_update', 'fetch_us_1h_cdp.py',     ['--update']),
    ]

    total_start = time.time()
    for name, script, args in tasks:
        print(f"\n   ── {name} ──")
        ok, elapsed, _ = run(script, args, timeout=900)
        status = '✅' if ok else '❌'
        print(f"   {status} {name} 完成 ({elapsed:.0f}s)")

    # 计算日线指标
    _compute_daily_indicators_batch()

    print(f"\n   ── 外部指标 ──")
    _update_externals(quiet=False)

    total_elapsed = time.time() - total_start
    print(f"\n✅ 盘后更新完成 ({total_elapsed:.0f}s)")

def do_full():
    print(f"\n🔨 全量重建（1d + 1h + 全部指标）")
    tasks = [
        ('1d_full', 'fetch_us_stocks_cdp.py', ['--full', '--interval', 'both']),
        ('1h_full', 'fetch_us_1h_cdp.py',    ['--full']),
    ]
    total_start = time.time()
    for name, script, args in tasks:
        print(f"\n   ── {name} ──")
        ok, elapsed, _ = run(script, args, timeout=1800)
        status = '✅' if ok else '❌'
        print(f"   {status} {name} 完成 ({elapsed:.0f}s)")

    # 计算全部指标
    _compute_daily_indicators_batch()
    _compute_hourly_indicators_batch()

    print(f"\n   ── 外部指标 ──")
    _update_externals(quiet=False)
    print(f"\n✅ 全量重建完成 ({time.time()-total_start:.0f}s)")

def _update_externals(quiet=True):
    """更新所有外部指标（GEX/VIX/TNX/COT/Gamma/Fed）"""
    scripts = [
        ('GEX',      'fetch_cboe_gex_chrome.py',       []),
        ('VIX/TNX',  'fetch_vix_tnx_fred.py',         ['--days', '30'] if not quiet else ['--check']),
        ('COT',      'fetch_cot_cta.py',               []),
        ('Gamma',    'fetch_gamma_regime_chrome.py',   []),
        ('Fed H41',  'fetch_fed_h41_chrome.py',        []),
    ]
    for label, script, args in scripts:
        ok, elapsed, _ = run(script, args, timeout=120, quiet=True)
        status = '✅' if ok else '❌'
        if not quiet:
            print(f"   {status} {label} ({elapsed:.0f}s)")

def do_externals():
    print(f"\n📈 外部指标更新")
    _update_externals(quiet=False)

# ────────────────────────────────────────────────────────────
# 指标计算（内联，不依赖外部模块）
# ────────────────────────────────────────────────────────────
def _ema(values, span):
    k = 2 / (span + 1)
    r = [values[0]]
    for v in values[1:]:
        r.append(v * k + r[-1] * (1 - k))
    return r

def _atr(bars, period=14):
    if len(bars) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(bars)):
        h = float(bars[i]['high'])
        l = float(bars[i]['low'])
        pc = float(bars[i - 1]['close'])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period

def _trend_structure_1d(bars):
    if len(bars) < 50:
        return {'ema20': None, 'ema50': None, 'trend': 'UNKNOWN'}
    closes = [float(b['close']) for b in bars]
    e20 = _ema(closes, 20)[-1]
    e50 = _ema(closes, 50)[-1]
    last = closes[-1]
    trend = 'BULL' if (e20 > e50 and last > e20) else 'BEAR' if (e20 < e50 and last < e20) else 'TRANSITION'
    return {
        'ema20': round(e20, 2), 'ema50': round(e50, 2),
        'last_close': round(last, 2), 'trend': trend,
        'dist_ema20_pct': round((last - e20) / e20 * 100, 2),
        'dist_ema50_pct': round((last - e50) / e50 * 100, 2),
        'atr14': round(_atr(bars[-30:]), 2),
    }

def _trend_structure_1h(bars):
    if len(bars) < 50:
        return {'ema20': None, 'ema50': None, 'trend': 'UNKNOWN'}
    closes = [float(b['close']) for b in bars]
    e20 = _ema(closes, 20)[-1]
    e50 = _ema(closes, 50)[-1]
    last = closes[-1]
    trend = 'BULL' if (e20 > e50 and last > e20) else 'BEAR' if (e20 < e50 and last < e20) else 'TRANSITION'
    return {
        'ema20': round(e20, 2), 'ema50': round(e50, 2),
        'last_close': round(last, 2), 'trend': trend,
        'dist_ema20_pct': round((last - e20) / e20 * 100, 2),
        'atr14': round(_atr(bars[-50:]), 2),
    }

def _signal_bar_1d(bars):
    if len(bars) < 3:
        return {'has_signal': False}
    for b in reversed(bars[-5:-1]):
        o = float(b['open']); h = float(b['high'])
        l = float(b['low']); c = float(b['close'])
        body = abs(c - o); rng = h - l
        if rng == 0:
            continue
        if body / rng >= 0.6:
            if c > o and c >= h - 0.2 * rng:
                return {'has_signal': True, 'type': 'BULL_SIGNAL_BAR',
                        'datetime': b['date'], 'body_pct': round(body / rng, 2)}
            elif c < o and c <= l + 0.2 * rng:
                return {'has_signal': True, 'type': 'BEAR_SIGNAL_BAR',
                        'datetime': b['date'], 'body_pct': round(body / rng, 2)}
    return {'has_signal': False}

def _h1_signal_1h(bars):
    if len(bars) < 20:
        return {'has_h1': False, 'has_l1': False}
    closes = [float(b['close']) for b in bars]
    recent = closes[-20:]
    if recent[-1] > recent[0]:
        min_idx = min(range(len(recent)), key=lambda i: recent[i])
        if min_idx < len(recent) - 1:
            for i in range(min_idx + 1, len(recent)):
                if recent[i] > max(recent[:i]):
                    return {'has_h1': True,
                            'h1_datetime': bars[-(20 - i)]['datetime'],
                            'has_l1': False}
    else:
        max_idx = max(range(len(recent)), key=lambda i: recent[i])
        if max_idx < len(recent) - 1:
            for i in range(max_idx + 1, len(recent)):
                if recent[i] < min(recent[:i]):
                    return {'has_l1': True,
                            'l1_datetime': bars[-(20 - i)]['datetime'],
                            'has_h1': False}
    return {'has_h1': False, 'has_l1': False}

def _bearish_liquidation_1h(bars):
    if len(bars) < 20:
        return {'detected': False}
    closes = [float(b['close']) for b in bars]
    last_close = closes[-1]
    low_20 = min(closes[-20:])
    vol_last = float(bars[-1].get('volume', 0))
    vols = [float(b.get('volume', 0)) for b in bars[-20:] if b.get('volume')]
    avg_vol = (sum(vols) / len(vols)) if vols else 1
    if last_close <= low_20 and last_close < closes[-2] and vol_last < avg_vol * 1.5:
        return {'detected': True, 'type': 'BEARISH_LIQUIDATION'}
    return {'detected': False}

def _compute_daily_indicators_single(ticker):
    """为单只股票计算日线指标"""
    p1d = PROJ / '中间过程' / 'klines' / f'{ticker}_1d.json'
    if not p1d.exists():
        return {'ticker': ticker, 'error': 'no_data'}
    bars = json.load(open(p1d)).get('data', [])
    if not bars:
        return {'ticker': ticker, 'error': 'no_data'}
    result = {
        'ticker': ticker, 'bar_count': len(bars),
        'last_date': bars[-1]['date'],
        'computed_at': datetime.now(timezone.utc).isoformat(),
    }
    try:
        import statistics
        ts = _trend_structure_1d(bars)
        result.update({'trend_structure': ts, 'atr14': ts.get('atr14', 0)})
        result['signal_bar'] = _signal_bar_1d(bars)
        c20 = [float(b['close']) for b in bars[-25:]]
        if len(c20) >= 20:
            mid = statistics.mean(c20[-20:])
            std = statistics.stdev(c20[-20:]) if len(c20) > 1 else 0
            result['bollinger'] = {
                'upper': round(mid + 2 * std, 2),
                'mid': round(mid, 2),
                'lower': round(mid - 2 * std, 2),
                'width': round(2 * std / mid * 100, 2) if mid else 0,
            }
        highs = [float(b['high']) for b in bars]
        lows = [float(b['low']) for b in bars]
        result['swing_high'] = round(max(highs[-60:]), 2)
        result['swing_low'] = round(min(lows[-60:]), 2)
    except Exception as e:
        result['compute_error'] = str(e)
    return result

def _compute_hourly_indicators_single(ticker):
    """为单只股票计算小时线指标"""
    p1h = PROJ / '中间过程' / 'klines' / f'{ticker}_1h.json'
    if not p1h.exists():
        return {'ticker': ticker, 'error': 'no_data'}
    bars = json.load(open(p1h)).get('data', [])
    if not bars:
        return {'ticker': ticker, 'error': 'no_data'}
    result = {
        'ticker': ticker, 'bar_count': len(bars),
        'last_datetime': bars[-1]['datetime'],
        'computed_at': datetime.now(timezone.utc).isoformat(),
    }
    try:
        ts = _trend_structure_1h(bars)
        result.update({'trend_structure': ts, 'atr14': ts.get('atr14', 0)})
        result.update(_h1_signal_1h(bars))
        result['liquidation'] = _bearish_liquidation_1h(bars)
        today_str = date.today().isoformat()
        today_bars = [b for b in bars if b['datetime'].startswith(today_str)]
        if today_bars:
            result['today'] = {
                'open': round(float(today_bars[0]['open']), 2),
                'high': round(max(float(b['high']) for b in today_bars), 2),
                'low': round(min(float(b['low']) for b in today_bars), 2),
                'close': round(float(today_bars[-1]['close']), 2),
                'bars': len(today_bars),
            }
    except Exception as e:
        result['compute_error'] = str(e)
    return result

def _compute_daily_indicators_batch(workers=8):
    """并行计算全部股票的日线指标"""
    tickers = get_tickers()
    print(f"\n   ── 日线指标计算 ({len(tickers)} 只) ──")
    t0 = time.time()
    ok = err = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_compute_daily_indicators_single, t): t for t in tickers}
        done = 0
        for fut in as_completed(futures):
            done += 1
            ticker = futures[fut]
            try:
                data = fut.result()
                if data.get('error'):
                    err += 1
                else:
                    p = INDICATORS_DIR / f'{ticker}_1d_indicators.json'
                    with open(p, 'w') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    ok += 1
            except Exception:
                err += 1
            if done % 100 == 0:
                print(f"     ... {done}/{len(tickers)}")
    print(f"   ✅ 日线指标完成: {ok} 成功 | {err} 失败 ({time.time()-t0:.1f}s)")
    return {'ok': ok, 'err': err}

def _compute_hourly_indicators_batch(workers=8):
    """并行计算全部股票的小时线指标"""
    tickers = get_tickers()
    print(f"\n   ── 小时线指标计算 ({len(tickers)} 只) ──")
    t0 = time.time()
    ok = err = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_compute_hourly_indicators_single, t): t for t in tickers}
        done = 0
        for fut in as_completed(futures):
            done += 1
            ticker = futures[fut]
            try:
                data = fut.result()
                if data.get('error'):
                    err += 1
                else:
                    p = INDICATORS_DIR / f'{ticker}_1h_indicators.json'
                    with open(p, 'w') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    ok += 1
            except Exception:
                err += 1
            if done % 100 == 0:
                print(f"     ... {done}/{len(tickers)}")
    print(f"   ✅ 小时线指标完成: {ok} 成功 | {err} 失败 ({time.time()-t0:.1f}s)")
    return {'ok': ok, 'err': err}

# ── CLI 入口 ────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='P0 数据更新入口')
    parser.add_argument('--check',        action='store_true', help='快速检查数据新鲜度')
    parser.add_argument('--pre-market',  action='store_true', help='开盘前：全量检查 + 补漏')
    parser.add_argument('--intraday',     action='store_true', help='盘中：小时增量更新 1h + 计算小时线指标')
    parser.add_argument('--post-market', action='store_true', help='盘后：更新日线 + 1h + 计算日线指标')
    parser.add_argument('--full',        action='store_true', help='全量重建（1d+1h+全部指标）')
    parser.add_argument('--externals',    action='store_true', help='仅更新外部指标')
    parser.add_argument('--force',       action='store_true', help='强制更新（跳过新鲜度检查）')
    args = parser.parse_args()

    if args.check:
        do_check()
    elif args.pre_market:
        do_pre_market()
    elif args.intraday:
        do_intraday()
    elif args.post_market:
        do_post_market()
    elif args.full:
        do_full()
    elif args.externals:
        do_externals()
    else:
        r = do_check()
        if not r['stale_1d'] and not r['stale_1h']:
            print(f"\n💡 数据已是最新，无需更新")
        else:
            print(f"\n💡 使用 --pre-market / --intraday / --post-market / --full 指定场景")
