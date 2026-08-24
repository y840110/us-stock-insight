#!/usr/bin/env python3
"""修复 verify_chunk 的 tolerance 年数"""
import re

with open('TradingAgents/fintech/p1/batch_backfill.py') as f:
    content = f.read()

# 新的 verify_chunk 函数
new_func = '''def verify_chunk(interval, symbols, chunk_idx, target_start):
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
    return ok_count >= len(results) * 0.8
'''

# 替换
old_pattern = r'def verify_chunk\(interval, symbols, chunk_idx, target_start\):.*?return ok >= len\(results\) \* 0\.8'
new_content = re.sub(old_pattern, new_func.strip(), content, flags=re.DOTALL)

with open('TradingAgents/fintech/p1/batch_backfill.py', 'w') as f:
    f.write(new_content)

print('Patched verify_chunk. Verifying...')

# 验证：检查是否包含 year + 3
with open('TradingAgents/fintech/p1/batch_backfill.py') as f:
    content = f.read()
if 'year + 3' in content:
    print('✅ year + 3 替换成功')
else:
    print('❌ 未找到 year + 3')
