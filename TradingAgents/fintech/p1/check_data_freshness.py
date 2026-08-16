#!/usr/bin/env python3
"""快速检查美股数据新鲜度（基于NYSE交易日历）"""
import json, os
from datetime import datetime, date, timedelta
from pathlib import Path
import pandas_market_calendars as mcal

PROJ_DIR  = Path(__file__).parent.parent.parent.resolve()
KLINES_DIR = PROJ_DIR / '中间过程' / 'klines'
POOL_FILE = PROJ_DIR / 'fintech' / 'stock_pool.json'

# NYSE 交易日历（缓存）
_nyse = None
def nyse_valid_days(n=20):
    global _nyse
    if _nyse is None:
        _nyse = mcal.get_calendar('NYSE')
    end = date.today()
    start = end - timedelta(days=n * 2)
    days = _nyse.valid_days(start_date=start, end_date=end)
    return sorted(set(d.strftime('%Y-%m-%d') for d in days))

def get_last_trading_day():
    """返回最后一个已收盘的交易日（昨天或更早）"""
    days = nyse_valid_days(10)  # 过去20个日历天内的交易日
    today = date.today()
    today_str = today.strftime('%Y-%m-%d')
    # 如果今天是交易日（但还没收盘），排除今天；否则找最近的过去交易日
    if today_str in days:
        prev = today - timedelta(days=1)
        while prev.weekday() >= 5:
            prev -= timedelta(days=1)
        return prev.strftime('%Y-%m-%d')
    # 今天不是交易日（周末/假日），找最近的前一个交易日
    prev = today - timedelta(days=1)
    while prev.weekday() >= 5 or prev.strftime('%Y-%m-%d') not in days:
        prev -= timedelta(days=1)
    return prev.strftime('%Y-%m-%d')

def get_tickers():
    with open(POOL_FILE) as f:
        pool = json.load(f)
    return sorted([s['code'] for s in pool['stocks']])

TICKERS = get_tickers()
UNAVAILABLE = {'TNX'}

def get_local_dates(ticker):
    fpath = KLINES_DIR / f'{ticker}_1d.json'
    if not fpath.exists() or fpath.stat().st_size == 0:
        return None, '文件不存在'
    try:
        with open(fpath) as f:
            d = json.load(f)
        data = d
        while isinstance(data, dict) and 'data' in data:
            data = data['data']
        if not isinstance(data, list):
            return None, f'格式错误'
        return {e['date'] for e in data if isinstance(e, dict) and 'date' in e}, None
    except Exception as e:
        return None, str(e)

def parse_date(s):
    for fmt in ('%b %d, %Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except Exception:
            pass
    return None

def check_all():
    today = date.today()
    weekday_name = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][today.weekday()]
    today_str = today.strftime('%Y-%m-%d')
    last_td = get_last_trading_day()  # 最后一个已收盘的交易日

    # 获取最近20个交易日（作为参考）
    recent_trading_days = nyse_valid_days(20)

    results = {'ok': [], 'stale': [], 'error': []}

    for ticker in sorted(TICKERS):
        if ticker in UNAVAILABLE:
            results['ok'].append((ticker, last_td, 0, 'unavailable'))
            continue

        dates, err = get_local_dates(ticker)
        if err:
            results['error'].append((ticker, err))
            continue
        if not dates:
            results['error'].append((ticker, '空文件'))
            continue

        latest_date_str = max(dates)

        # 计算latest之后过了多少个已收盘交易日
        trading_days_after = [d for d in recent_trading_days if d > latest_date_str and d <= last_td]
        missing_count = len(trading_days_after)

        if missing_count == 0:
            results['ok'].append((ticker, latest_date_str, 0, 'up to date'))
        else:
            results['stale'].append((ticker, latest_date_str, missing_count, trading_days_after[:3]))

    total = len(TICKERS)
    ok_count = len(results['ok'])
    stale_count = len(results['stale'])
    error_count = len(results['error'])
    needs_update = stale_count > 0 or error_count > 0

    return {
        'today': today_str,
        'weekday_name': weekday_name,
        'last_trading_day': last_td,
        'total': total,
        'ok_count': ok_count,
        'stale_count': stale_count,
        'error_count': error_count,
        'needs_update': needs_update,
        'ok': results['ok'],
        'stale': results['stale'],
        'error': results['error'],
    }

if __name__ == '__main__':
    r = check_all()
    print(f"{r['weekday_name']} {r['today']} | 检查 {r['total']} 只 | ✅{r['ok_count']} | ⚠️{r['stale_count']} | ❌{r['error_count']}")
    print(f"最后交易日: {r['last_trading_day']}")

    if r['stale']:
        print(f"\n⚠️ 过期股票（缺交易日数量）：")
        for ticker, latest, missing_cnt, examples in sorted(r['stale'], key=lambda x: -x[2])[:10]:
            ex = f' 例: {examples}' if examples else ''
            print(f"  {ticker}: 最新 {latest}, 缺 {missing_cnt} 个交易日{ex}")
        if len(r['stale']) > 10:
            print(f"  ... 还有 {len(r['stale'])-10} 只")
    if r['error']:
        print(f"\n❌ 出错:")
        for ticker, err in r['error']:
            print(f"  {ticker}: {err}")

    print(f"\n{'NEED_UPDATE' if r['needs_update'] else 'OK'}")
