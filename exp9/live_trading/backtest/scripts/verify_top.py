#!/usr/bin/env python3
"""独立验证 Top 组合（同一引擎，仅参数不同）"""
import subprocess, re, sys, json
from pathlib import Path

ENGINE = 'live_trading/当前最优/engine_h3_4_1_final.py'
REPLAY = 'live_trading/replay_engine.py'
BASE = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9')
LOGS_DIR = BASE / 'live_trading' / 'htrade' / 'logs'
CAPITAL = 10000
MODEL_EP = '/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/model/experts'
OUT_FILE = Path('/tmp/verify_results.json')

def run_test(atr_mult, atr_trailing, min_hold, risk_frac, target_mult, max_pos):
    cmd = [
        sys.executable, str(BASE / ENGINE),
        '--years','2025','2026','--capital', str(CAPITAL),
        '--atr-mult', str(atr_mult),
        '--atr-trailing-mult', str(atr_trailing),
        '--min-hold', str(min_hold),
        '--target-mult', str(target_mult),
        '--max-pos', str(max_pos),
        '--debug',
    ]
    env = {'PYTHONPATH': MODEL_EP}
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(BASE), env=env)
    output = r.stdout + r.stderr

    jsonl_name = None
    for line in output.split('\n'):
        if '写入' in line and '.jsonl' in line:
            jsonl_name = line.split(': ')[-1].strip()
            break

    if not jsonl_name:
        return {'error': f'no jsonl: {output[-300:]}'}

    jsonl_path = LOGS_DIR / jsonl_name
    rp = subprocess.run(
        [sys.executable, str(BASE / REPLAY), '--log', str(jsonl_path), '--cash', str(CAPITAL)],
        capture_output=True, text=True, timeout=60, cwd=str(BASE)
    )

    result = {'params': {'atr_mult':atr_mult,'atr_trailing':atr_trailing,
                         'min_hold':min_hold,'risk_frac':risk_frac,
                         'target_mult':target_mult,'max_pos':max_pos},
              'replay_output': rp.stdout}

    for line in rp.stdout.split('\n'):
        if '总收益率' in line:
            try:
                result['return_pct'] = float(re.search(r'([+-]?[\d.]+)%', line).group(1))
            except: pass
        if '最终现金' in line:
            try:
                result['final_cash'] = float(re.search(r'\$?([\d,]+\.?\d*)', line).group(1).replace(',',''))
            except: pass
        if '胜率' in line:
            try:
                result['win_rate'] = float(re.search(r'([\d.]+)%', line).group(1))
            except: pass
        if '盈利交易' in line:
            try:
                result['win_count'] = int(re.search(r'(\d+)', line).group(1))
            except: pass

    try: jsonl_path.unlink()
    except: pass

    return result

# 测试矩阵
tests = [
    # (label, atr_mult, atr_trailing, min_hold, risk_frac, target_mult, max_pos)
    ('baseline(1.5/4.0/5/0.20/3.0/5)',  1.5, 4.0,  5, 0.20, 3.0, 5),
    ('rf=0.10/pos=8',                     1.5, 4.0,  5, 0.10, 3.0, 8),
    ('atr=1.0/trail=2.5',                1.0, 2.5,  5, 0.20, 3.0, 5),
    ('atr=1.5/trail=2.5/rf=0.15',       1.5, 2.5,  5, 0.15, 3.0, 5),
    ('atr=1.5/trail=5.0/hold=8/tgt=5',  1.5, 5.0,  8, 0.20, 5.0, 5),
    ('atr=0.75/trail=3.0',                0.75,3.0,  5, 0.20, 3.0, 5),
    ('atr=1.5/trail=2.0',                1.5, 2.0,  5, 0.20, 3.0, 5),
    ('atr=1.5/trail=3.0/rf=0.10/pos=8',  1.5, 3.0,  5, 0.10, 3.0, 8),
]

all_results = []
for label, am, at, mh, rf, tm, mp in tests:
    print(f'Running: {label}', flush=True)
    result = run_test(am, at, mh, rf, tm, mp)
    result['label'] = label
    all_results.append(result)
    ret = result.get('return_pct', '?')
    print(f'  → return={ret}', flush=True)

# 保存
with open(OUT_FILE, 'w') as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)

print(f'\n全部完成，结果已保存到 {OUT_FILE}', flush=True)
