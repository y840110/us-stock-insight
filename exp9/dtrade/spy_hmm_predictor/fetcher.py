"""
SPY 本地数据读取（不依赖外部网络）
VIX 由实现波动率(RV)作为代理
"""
import json
from pathlib import Path

DATA_DIR = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines')
OUT_DIR  = Path(__file__).parent / 'data'
OUT_DIR.mkdir(exist_ok=True)


def load_spy():
    with open(DATA_DIR / 'SPY_1d.json') as f:
        raw = json.load(f)['data']
    bars = []
    for b in raw:
        bars.append({
            'date':   b['date'],
            'open':   b['open'],
            'high':   b['high'],
            'low':    b['low'],
            'close':  b['close'],
            'volume': b.get('volume', 0),
        })
    return bars


def main():
    bars = load_spy()
    print(f'SPY: {bars[0]["date"]} → {bars[-1]["date"]}, {len(bars)} 条')

    # 按年统计
    for year in range(2020, 2027):
        yr = [b for b in bars if b['date'].startswith(str(year))]
        print(f'  {year}: {len(yr)} 条')

    out = OUT_DIR / 'spy_vix_merged.json'
    with open(out, 'w') as f:
        json.dump(bars, f, ensure_ascii=False)
    print(f'已保存: {out}')


if __name__ == '__main__':
    main()
