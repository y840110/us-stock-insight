#!/usr/bin/env python3
"""
engine_h3_4_1_rf35 — rf=0.35 | trail=4.0 | $20k → +370%
═══════════════════════════════════════════════════════
最优小时级策略（h3-4-1 引擎）
入场: BuyFilterEngine STAGE_4 NOW（日线信号确认）
出场: Lot1 目标触达→保本 + Lot2 ATR trailing 止盈
═══════════════════════════════════════════════════════
参数: ATR×1.5 | Trail=4.0×ATR | Hold=5h | Tgt=3.0×ATR | Pos=8 | RF=0.35
历史: $20,000 → $93,905 (+370%) | 胜率 38.6% | RR 2.47
═══════════════════════════════════════════════════════
用法:
    python3 engine_h3_4_1_rf35.py
    python3 engine_h3_4_1_rf35.py --years 2025 2026 --capital 50000 --tag my_run
"""
import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine_h3_4_1 import main as _main

ap = argparse.ArgumentParser(description='h3-4-1 最优策略 rf=0.35')
ap.add_argument('--years', nargs=2, default=['2025', '2026'])
ap.add_argument('--capital', type=float, default=20000.0)
ap.add_argument('--debug', action='store_true')
ap.add_argument('--tag', type=str, default='rf35_trail4.0_optimal')
args = ap.parse_args()

sys.argv = [
    'engine_rf35',
    '--atr-mult', '1.5',
    '--atr-trailing-mult', '4.0',
    '--min-hold', '5',
    '--target-mult', '3.0',
    '--max-pos', '8',
    '--risk-frac', '0.35',
    '--years', *args.years,
    '--capital', str(args.capital),
    '--tag', args.tag,
]
if args.debug:
    sys.argv.append('--debug')
_main()
