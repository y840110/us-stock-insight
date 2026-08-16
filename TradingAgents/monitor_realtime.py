#!/usr/bin/env python3
"""实时监控文件写入（轮询方式）- 版本2，输出更紧凑"""
import os, time, sys
from pathlib import Path

BASE = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents')
ALLOWED = {'中间过程', 'state', 'layout', 'spy_lr_full_backtest', 'monitor'}
VIOLATIONS = []
SEEN = set()
START = time.time()

# 初始化：记录所有已存在的文件
for root, dirs, files in os.walk(BASE):
    dirs[:] = [d for d in dirs if d not in ('__pycache__', '.venv', '.git')]
    for fn in files:
        SEEN.add(os.path.join(root, fn))

print(f"[{time.strftime('%H:%M:%S')}] 监控已启动，已追踪 {len(SEEN)} 个文件", flush=True)
sys.stdout.flush()

while True:
    time.sleep(1.5)
    new_files = []
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', '.venv', '.git')]
        for fn in files:
            full = os.path.join(root, fn)
            if full not in SEEN:
                SEEN.add(full)
                new_files.append(full)
    
    for f in new_files:
        rel = str(Path(f).relative_to(BASE))
        parts = Path(rel).parts
        if parts[0] not in ALLOWED:
            VIOLATIONS.append((rel, time.time() - START))
            print(f"\n🚨 违规写入 [{time.strftime('%H:%M:%S')}]: {rel}", flush=True)
        else:
            print(f"  ✅ {rel}", flush=True)
    sys.stdout.flush()
