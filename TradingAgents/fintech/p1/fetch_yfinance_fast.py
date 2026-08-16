#!/usr/bin/env python3
"""
yfinance快速补数据脚本
- 不需要Chrome CDP
- 直接调用Yahoo Finance API
- 多线程加速
"""
import json, os, sys, time
from pathlib import Path
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import yfinance as yf

PROJ = Path(__file__).parent.parent.parent
WORK = PROJ / '中间过程' / 'klines'
POOL = PROJ / 'fintech' / 'stock_pool.json'

WORK.mkdir(parents=True, exist_ok=True)

def load_pool():
    with open(POOL) as f:
        pool = json.load(f)
    symbols = [s['code'] for s in pool['stocks']]
    special = pool.get('_special_symbols', {})
    for sym in special:
        if sym not in symbols:
            symbols.append(sym)
    return symbols

def get_last_date(symbol):
    fpath = WORK / f'{symbol.replace("^","")}_1d.json'
    if not fpath.exists():
        return None
    try:
        with open(fpath) as f:
            d = json.load(f)
        data = d
        while isinstance(data, dict) and 'data' in data:
            data = data['data']
        if isinstance(data, list) and len(data) > 0:
            return data[-1].get('date')
    except:
        pass
    return None

def fetch_and_merge(symbol):
    """获取单只股票数据并合并到现有文件"""
    fpath = WORK / f'{symbol.replace("^","")}_1d.json'
    
    # 读取现有数据
    existing = []
    if fpath.exists() and fpath.stat().st_size > 0:
        try:
            with open(fpath) as f:
                d = json.load(f)
            data = d
            while isinstance(data, dict) and 'data' in data:
                data = data['data']
            if isinstance(data, list):
                existing = data
        except:
            existing = []
    
    last_date = existing[-1]['date'] if existing else None
    
    # 用yfinance获取最新数据
    ticker = yf.Ticker(symbol)
    try:
        hist = ticker.history(period='3mo', auto_adjust=True)
    except Exception as e:
        return symbol, 'error', str(e)
    
    if hist.empty:
        return symbol, 'skip', 'no data'
    
    # 转换格式
    new_bars = []
    for idx, row in hist.iterrows():
        date_str = idx.strftime('%Y-%m-%d')
        new_bars.append({
            'date': date_str,
            'open': round(float(row['Open']), 2),
            'high': round(float(row['High']), 2),
            'low': round(float(row['Low']), 2),
            'close': round(float(row['Close']), 2),
            'volume': int(row['Volume'])
        })
    
    # 合并：去重+追加
    all_dates = {b['date'] for b in existing}
    merged = existing.copy()
    for bar in new_bars:
        if bar['date'] not in all_dates:
            merged.append(bar)
            all_dates.add(bar['date'])
    
    # 按日期排序
    merged.sort(key=lambda x: x['date'])
    
    # 保存
    output = {'data': merged}
    with open(fpath, 'w') as f:
        json.dump(output, f)
    
    new_count = len(merged) - len(existing)
    return symbol, 'ok', f'+{new_count} bars'

def main():
    symbols = load_pool()
    print(f"Total symbols: {len(symbols)}")
    
    # 检查哪些需要更新
    to_update = []
    for sym in symbols:
        last = get_last_date(sym)
        if last is None or ('2026-05-20' not in last and '2026-05-21' not in last and 'May 20' not in last and 'May 21' not in last):
            to_update.append(sym)
    
    print(f"Need update: {len(to_update)}")
    print(f"Up to date: {len(symbols) - len(to_update)}")
    
    if not to_update:
        print("All data is up to date!")
        return
    
    print(f"\nFetching {len(to_update)} stocks with yfinance (10 threads)...\n")
    
    success = 0
    failed = 0
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_and_merge, sym): sym for sym in to_update}
        for i, future in enumerate(as_completed(futures)):
            sym = futures[future]
            try:
                name, status, msg = future.result()
                if status == 'ok':
                    success += 1
                    print(f"[{i+1}/{len(to_update)}] ✅ {sym}: {msg}")
                elif status == 'skip':
                    print(f"[{i+1}/{len(to_update)}] ⏭ {sym}: {msg}")
                else:
                    failed += 1
                    print(f"[{i+1}/{len(to_update)}] ❌ {sym}: {msg}")
            except Exception as e:
                failed += 1
                print(f"[{i+1}/{len(to_update)}] ❌ {sym}: EXCEPTION {e}")
    
    print(f"\n=== Done ===")
    print(f"Success: {success}")
    print(f"Failed: {failed}")
    print(f"Total updated: {success}")

if __name__ == '__main__':
    main()
