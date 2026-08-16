#!/usr/bin/env python3
"""engine_h3_4_1_rf30 — rf=0.30 | trail=4.0 | $20k → +283%"""
import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine_h3_4_1 import main as _main

ap = argparse.ArgumentParser()
ap.add_argument('--years', nargs=2, default=['2025', '2026'])
ap.add_argument('--capital', type=float, default=20000.0)
ap.add_argument('--debug', action='store_true')
ap.add_argument('--tag', type=str, default='rf30_trail4.0')
args = ap.parse_args()

sys.argv = [
    'engine_rf30',
    '--atr-mult', '1.5',
    '--atr-trailing-mult', '4.0',
    '--min-hold', '5',
    '--target-mult', '3.0',
    '--max-pos', '8',
    '--risk-frac', '0.30',
    '--years', *args.years,
    '--capital', str(args.capital),
    '--tag', args.tag,
]
if args.debug:
    sys.argv.append('--debug')
_main()
