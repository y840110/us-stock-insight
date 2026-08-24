#!/usr/bin/env python3
"""
批量回溯执行器
==============
将 symbol 池分成多批，每批回溯完成后做快速验证，再执行下一批。

用法：
  python3 batch_backfill.py --interval 1d --chunk 0      # 第0批（首批），约100只
  python3 batch_backfill.py --interval 1d --all          # 全量（分6批自动执行）
  python3 batch_backfill.py --interval 1d --status       # 查看各批状态
  python3 batch_backfill.py --interval 1d --resume       # 从断点继续
"""
import json, subprocess, sys, time, argparse
from pathlib import Path
from datetime import date

PROJ   = Path(__file__).parent.parent.parent
P1     = Path(__file__).parent
STATE  = P1 / 'state'
BATCH_FILE = STATE / 'batch_backfill.json'

STATE.mkdir(parents=True, exist_ok=True)

# 每批股票数量（1d 每批约100只，1h 每批约80只）
CHUNK_SIZE = {'1d': 100, '1h': 80}

# 1d: 回溯到 2018-01-01（8年）
# 1h: 回溯到 2022-01-01（4年）
TARGET_YEARS = {'1d': 8, '1h': 4}

# 固定目标开始日期（不按当前日期浮动）
TARGET_START = {'1d': date(2018, 1, 1), '1h': date(2022, 1, 1)}

# ─────────────────────────────────────────────
# 股票池加载
# ─────────────────────────────────────────────
def load_symbols(exclude_special=True):
    pool_file = PROJ / 'fintech' / 'stock_pool.json'
    d = json.load(open(pool_file))
    symbols = [s['code'] for s in d.get('stocks', []) if s.get('code')]
    special = d.get('_special_symbols', {})
    for sym in special:
        if sym not in {'TNX'} and sym not in symbols:
            symbols.append(sym)
    exclude = {'DXY', '^VIX', 'TNX'} if exclude_special else set()
    return [s for s in symbols if s not in exclude]

# ─────────────────────────────────────────────
# 状态管理
# ─────────────────────────────────────────────
def load_state(interval):
    f = BATCH_FILE.with_name(f'batch_backfill_{interval}.json')
    if f.exists():
        return json.load(open(f))
    return {'interval': interval, 'chunks': []}

def save_state(interval, state):
    f = BATCH_FILE.with_name(f'batch_backfill_{interval}.json')
    with open(f, 'w') as fp:
        json.dump(state, fp, indent=2)

def get_batch_symbols(interval, chunk_idx):
    """返回某批次的 symbol 列表"""
    symbols = load_symbols()
    size = CHUNK_SIZE[interval]
    start = chunk_idx * size
    return symbols[start:start + size]

# ─────────────────────────────────────────────
# 验证（快速采样）
# ─────────────────────────────────────────────
def verify_chunk(interval, symbols, chunk_idx, target_start):
    """采样10只，验证起始日期是否达标（允许最多3年容忍，覆盖IPO晚的情况）"""
    KL = PROJ / '中间过程' / 'klines'
    import random
    sample = random.sample(symbols, min(10, len(symbols)))
    dt_key = 'datetime' if interval == '1h' else 'date'
    # 容忍：晚于目标最多3年（Yahoo 无 IPO 前的历史数据属正常）
    max_allowed = date(target_start.year + 3, target_start.month, target_start.day)
    results = []
    for sym in sample:
        fp = KL / (sym.lstrip('^') + '_' + interval + '.json')
        if not fp.exists():
            results.append((sym, 'MISSING', None))
            continue
        try:
            d = json.load(open(fp)); data = d.get('data', d)
            if not data: results.append((sym, 'EMPTY', None)); continue
            first = data[0][dt_key][:10]
            first_d = date.fromisoformat(first[:10])
            ok = first_d <= max_allowed
            results.append((sym, 'OK' if ok else 'SHORT', first))
        except Exception as e:
            results.append((sym, 'ERR: ' + str(e), None))

    ok_count = sum(1 for _, s, _ in results if s == 'OK')
    print('')
    print('  🔍 Chunk', chunk_idx, '验证（采样', len(results), '只）：', ok_count, '/', len(results), '达标')
    for sym, status, first in results:
        mark = '✅' if status == 'OK' else '❌'
        print('   ', mark, sym + ':', status, ('(' + str(first) + ')' if first else ''))
    return ok_count >= len(results) * 0.8   # 80% 通过即可

# ─────────────────────────────────────────────
# 运行一批
# ─────────────────────────────────────────────
def run_chunk(interval, chunk_idx, force=False, years=None):
    symbols = get_batch_symbols(interval, chunk_idx)
    if not symbols:
        print(f"Chunk {chunk_idx} 为空，已全部完成")
        return True

    years = years or TARGET_YEARS[interval]
    target_start = TARGET_START[interval]   # 固定日期，不浮动
    total_symbols = len(load_symbols())
    total_chunks = (total_symbols + CHUNK_SIZE[interval] - 1) // CHUNK_SIZE[interval]

    print(f"\n{'='*60}")
    print(f"📦 Chunk {chunk_idx}/{total_chunks-1} | {len(symbols)} 只 | {interval} | 目标: ≥ {target_start}")
    print(f"{'='*60}")

    # 构建命令
    cmd = [
        sys.executable, str(P1 / 'backfill_orchestrator.py'),
        '--interval', interval,
        '--start', str(target_start),
        '--demo',
    ] + symbols
    if force:
        cmd.append('--force')

    print(f"  命令: {sys.executable} backfill_orchestrator.py --interval {interval} --demo ...({len(symbols)} symbols)")
    print(f"  预计: {len(symbols) * years * 2 / 60:.0f}-{len(symbols) * years * 5 / 60:.0f} 分钟（仅供参考）")
    print()

    result = subprocess.run(cmd, cwd=str(PROJ))
    if result.returncode != 0:
        print(f"\n  ❌ Chunk {chunk_idx} 执行失败（exit {result.returncode}）")
        return False

    # 验证
    ok = verify_chunk(interval, symbols, chunk_idx, target_start)
    if not ok:
        print(f"\n  ⚠️ Chunk {chunk_idx} 验证未通过（<80%），请检查数据后再继续")
        return False

    print(f"\n  ✅ Chunk {chunk_idx} 完成并验证通过")
    return True

# ─────────────────────────────────────────────
# main
# ─────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--interval', required=True, choices=['1d', '1h'])
    parser.add_argument('--chunk', type=int, default=None, help='执行第N批')
    parser.add_argument('--all', action='store_true', help='自动执行全部批次')
    parser.add_argument('--status', action='store_true', help='查看所有批次状态')
    parser.add_argument('--resume', action='store_true', help='从断点继续')
    parser.add_argument('--force', action='store_true', help='删除现有数据重新来')
    args = parser.parse_args()

    interval = args.interval
    symbols = load_symbols()
    total_chunks = (len(symbols) + CHUNK_SIZE[interval] - 1) // CHUNK_SIZE[interval]

    if args.status:
        state = load_state(interval)
        print(f"\n📊 {interval} 回溯状态（总共 {len(symbols)} 只，分 {total_chunks} 批）")
        print(f"  目标: {TARGET_YEARS[interval]} 年前（1d→2018, 1h→2022）")
        for i in range(total_chunks):
            batch_syms = get_batch_symbols(interval, i)
            done = any(c.get('idx') == i for c in state.get('chunks', []))
            mark = '✅' if done else '⏳'
            print(f"  {mark} Chunk {i}: {batch_syms[0]}...{batch_syms[-1]} ({len(batch_syms)}只)")
        sys.exit(0)

    if args.resume:
        state = load_state(interval)
        # 从最后一个未完成的 chunk 继续
        done_idxs = {c['idx'] for c in state.get('chunks', [])}
        for i in range(total_chunks):
            if i not in done_idxs:
                ok = run_chunk(interval, i, force=args.force)
                if ok:
                    state = load_state(interval)
                    state['chunks'].append({'idx': i, 'done': True})
                    save_state(interval, state)
                else:
                    break
        sys.exit(0)

    if args.chunk is not None:
        run_chunk(interval, args.chunk, force=args.force)

    elif args.all:
        state = load_state(interval)
        done_idxs = {c['idx'] for c in state.get('chunks', [])}
        for i in range(total_chunks):
            if i in done_idxs and not args.force:
                print(f"\n  ⏭ Chunk {i} 已完成，跳过（用 --force 重新执行）")
                continue
            ok = run_chunk(interval, i, force=args.force)
            if ok:
                state = load_state(interval)
                state['chunks'].append({'idx': i, 'done': True, 'time': time.strftime('%Y-%m-%d %H:%M')})
                save_state(interval, state)
            else:
                print(f"\n  ⚠️ Chunk {i} 失败，停在此处。用 --resume 继续")
                break
        print(f"\n{'='*60}")
        print(f"✅ 全部完成（{interval}）")
    else:
        print("用法：--chunk N（执行第N批）或 --all（全量自动）或 --status（查看状态）")
