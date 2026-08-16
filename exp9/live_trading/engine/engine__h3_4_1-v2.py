#!/usr/bin/env python3
"""engine_v2 — 进化引擎2（trail=4.0, min_hold=5, max_pos=8）"""
import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from engine_h3_4_1 import main

sys.argv = ['engine_v2',
    '--atr-mult','1.5','--atr-trailing-mult','4.0',
    '--min-hold','5','--target-mult','3.0','--max-pos','8',
    '--years','2025','2026','--capital','10000',
    '--debug','--tag','v2_trail4.0']
main()
