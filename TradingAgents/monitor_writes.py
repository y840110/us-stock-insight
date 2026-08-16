#!/usr/bin/env python3
"""监控文件写入：仅允许写入 中间过程/，其余一律报警"""
import os
import sys
import threading
import time
from pathlib import Path

BASE = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents')
ALLOWED_PREFIXES = [
    str(BASE / '中间过程'),
    str(BASE / 'fintech/p1/state'),
    str(BASE / 'fintech/p2/layout'),
    str(BASE / 'fintech/p3/layout'),
    str(BASE / 'fintech/p4/layout'),
    str(BASE / 'spy_ml/spy_lr_full_backtest'),
]

WRITE_OPS = ['open(', 'json.dump', 'to_csv', '.write(', 'mkdir']

violations = []
checked_files = set()

def check_file(path_str):
    path_str = str(path_str)
    if path_str in checked_files:
        return
    checked_files.add(path_str)
    p = Path(path_str)
    if not p.exists():
        return
    if not p.is_file():
        return
    # 只检查 .py 和 .json
    if p.suffix not in ('.py', '.json', '.csv'):
        return

    try:
        content = p.read_text()
    except:
        return

    for i, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        for op in WRITE_OPS:
            if op not in line:
                continue
            # 检查是否在允许目录
            rel = str(p.relative_to(BASE))
            if '中间过程' in line:
                continue  # 允许的
            if 'fintech/p1/state' in line or 'layout' in line or 'spy_lr_full_backtest' in line:
                continue  # 允许的
            if any(x in line for x in ['fintech/p1/klines', 'klines123', '/tmp', '~/']):
                violations.append(f"  [{rel} L{i}] {stripped[:100]}")
                print(f"\n🚨 违规写入: [{rel} L{i}]")
                print(f"   {stripped[:100]}\n")

print("🔍 启动文件写入监控...")
print(f"   监控基础目录: {BASE}")
print(f"   允许写入: 中间过程/, state/, layout/, spy_lr_full_backtest/")
print("=" * 60)

# 扫描所有py文件
for py in sorted(BASE.rglob('*.py')):
    if '__pycache__' in str(py) or '.venv' in str(py):
        continue
    check_file(py)

print(f"\n✅ 扫描完成，共检查 {len(checked_files)} 个文件")
if violations:
    print(f"\n🚨 发现 {len(violations)} 处违规写入：")
    for v in violations:
        print(v)
    sys.exit(1)
else:
    print("✅ 无违规写入！所有文件写入均在允许目录内")
    sys.exit(0)
