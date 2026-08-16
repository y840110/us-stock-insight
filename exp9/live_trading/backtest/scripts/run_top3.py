#!/usr/bin/env python3
"""生成Top3参数组合的交割单Excel"""
import subprocess, sys, shutil
from pathlib import Path

BASE = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9')
ENGINE = BASE / 'live_trading/当前最优/engine_h3_4_1_final.py'
OUT_DIR = BASE / 'live_trading' / '当前最优'
CAPITAL = 10000
MODEL_EP = '/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/model/experts'

# 已知验证结果
KNOWN = {
    'v1_top1_atr1.5_trail3.0_rf0.10_pos8': (77.7, 48.0, 32.1),
    'v2_top2_rf0.10_pos8':                    (65.2, 35.5, 19.6),
    'v3_top3_trail5.0_hold8_tgt5.0':         (39.5,  9.8, -6.1),
}

configs = [
    ('v1_top1_atr1.5_trail3.0_rf0.10_pos8',  1.5, 3.0, 5, 0.10, 3.0, 8),
    ('v2_top2_rf0.10_pos8',                     1.5, 4.0, 5, 0.10, 3.0, 8),
    ('v3_top3_trail5.0_hold8_tgt5.0',          1.5, 5.0, 8, 0.20, 5.0, 5),
]

for i, (name, am, at, mh, rf, tm, mp) in enumerate(configs):
    print(f'\n[{i+1}/3] 运行 {name}', flush=True)
    print(f'    atr×={am} trail={at} hold={mh}h rf={rf} tgt={tm}× pos={mp}', flush=True)

    cmd = [
        sys.executable, str(ENGINE),
        '--years', '2025', '2026',
        '--capital', str(CAPITAL),
        '--atr-mult', str(am),
        '--atr-trailing-mult', str(at),
        '--min-hold', str(mh),
        '--target-mult', str(tm),
        '--max-pos', str(mp),
        '--debug',
    ]
    env = {'PYTHONPATH': MODEL_EP}
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(BASE), env=env)
    output = r.stdout + r.stderr

    # 找交割单路径
    trade_log = None
    for line in output.split('\n'):
        if '交割单已保存' in line:
            trade_log = line.split('保存: ')[-1].strip()
            break

    ret, vs_spy, vs_qqq = KNOWN.get(name, (None, None, None))

    if trade_log:
        src = Path(trade_log)
        if src.exists():
            dst = OUT_DIR / f'trade_log_h341_{name}.xlsx'
            shutil.copy2(src, dst)
            print(f'    ✅ → {dst.name}', flush=True)
            if ret is not None:
                print(f'    📊 return=+{ret}% | vs_spy=+{vs_spy}% | vs_qqq={vs_qqq:+.1f}%', flush=True)
        else:
            print(f'    ❌ 文件不存在: {src}', flush=True)
            print(f'    stdout: {r.stdout[-200:] if r.stdout else "(empty)"}', flush=True)
    else:
        print(f'    ❌ 未找到交割单路径', flush=True)
        print(f'    stdout: {r.stdout[-200:] if r.stdout else "(empty)"}', flush=True)

print('\n✅ 全部完成！', flush=True)
