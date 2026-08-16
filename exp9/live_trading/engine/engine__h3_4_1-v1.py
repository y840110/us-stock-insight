#!/usr/bin/env python3
"""engine_v1 — 进化引擎1（trail=3.0, min_hold=5, max_pos=8）"""
import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from engine_h3_4_1 import main

ap = argparse.ArgumentParser()
ap.add_argument('--years', nargs=2, default=['2025','2026'])
ap.add_argument('--capital', type=float, default=10000.0)
ap.add_argument('--lookback', type=int, default=0)
ap.add_argument('--debug', action='store_true')
ap.add_argument('--output', type=str, default=None)
ap.add_argument('--from-log', type=str, default=None)
ap.add_argument('--tag', type=str, default='')
args = ap.parse_args()

argv = ['engine_v1',
    '--atr-mult','1.5','--atr-trailing-mult','3.0',
    '--min-hold','5','--target-mult','3.0','--max-pos','8',
    '--years',*args.years,'--capital',str(args.capital)]
if args.debug:
    argv.append('--debug')
argv.extend(['--tag', args.tag or 'v1_trail3.0'])
sys.argv = argv
main()
