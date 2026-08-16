#!/usr/bin/env python3
"""
engine_daily_rf35.py — 日线版 最优策略
══════════════════════════════════════════════
策略: h3-4-1 日线移植版
入场: BuyFilterEngine STAGE_4 NOW
出场: Lot1 target→保本 + Lot2 ATR trailing
保护: SPY趋势过滤 + 可选熔断
══════════════════════════════════════════════
参数: Trail=2.5×ATR | RF=0.35 | Hold=3d | Pos=8
历史: $20,000 → $43,661 (+118%)
══════════════════════════════════════════════
用法:
    python3 engine_daily_rf35.py
    python3 engine_daily_rf35.py --years 2025 2026 --capital 50000
    python3 engine_daily_rf35.py --dd-limit 0.15  # 启用熔断
"""
import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / 'live_trading' / 'engine'))
from engine_daily import main as _main

ap = argparse.ArgumentParser(description='日线最优策略 rf=0.35 trail=2.5')
ap.add_argument('--years', nargs=2, default=['2025', '2026'])
ap.add_argument('--capital', type=float, default=20000.0)
ap.add_argument('--dd-limit', type=float, default=None, help='熔断阈值 (如 0.15)')
ap.add_argument('--debug', action='store_true')
ap.add_argument('--tag', type=str, default='daily_rf35_trail2.5')
args = ap.parse_args()

sys.argv = [
    'engine_daily_rf35',
    '--atr-mult', '1.5',
    '--trail-mult', '2.5',
    '--min-hold', '3',
    '--target-mult', '3.0',
    '--max-pos', '8',
    '--risk-frac', '0.35',
    '--years', *args.years,
    '--capital', str(args.capital),
    '--tag', args.tag,
]
if args.dd_limit is not None:
    sys.argv.extend(['--dd-limit', str(args.dd_limit)])
if args.debug:
    sys.argv.append('--debug')
_main()
