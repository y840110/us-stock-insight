#!/usr/bin/env python3
"""
P4 · 择股层 — stock_picker.py
================================
核心逻辑：
  1. 复用 fintech/p4/g123_screener.py（从 scripts/ 复制并适配）
  2. 叠加上 fintech/p4/synthesize.py 的综合评判层（P2+P3 动态权重）

用法：
    from fintech.p4.stock_picker import run_p4
    result = run_p4(klines_dir, p2_regime, p3_sectors)
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
KLINES_DIR   = PROJECT_ROOT / "中间过程" / "klines"
STOCK_POOL   = PROJECT_ROOT / "fintech" / "stock_pool.json"

# ── 添加 PROJECT_ROOT 到 sys.path（确保 fintech 包可导入）──────────────────
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── 加载 P4 总调度器 ────────────────────────────────────────────────
from fintech.p4.p4_dispatcher import run_p4 as _run_p4_dispatcher


# ══════════════════════════════════════════════════════════════════════════════
# 数据加载
# ══════════════════════════════════════════════════════════════════════════════

def load_pool() -> list[dict]:
    if not STOCK_POOL.exists(): return []
    with open(STOCK_POOL) as f:
        d = json.load(f)
    return d.get("stocks", [])


# ══════════════════════════════════════════════════════════════════════════════
# 主分析函数
# ══════════════════════════════════════════════════════════════════════════════

def run_p4(klines_dir: Path, p2_regime: dict, p3_sectors: dict) -> dict:
    """
    P4 主入口：委托 p4_dispatcher.run_p4() 执行 G1/G2/G3 调度
    """
    return _run_p4_dispatcher(p2_regime, p3_sectors)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# 控制台输出
# ══════════════════════════════════════════════════════════════════════════════

def print_p4_result(result: dict):
    from synthesize import print_recommendations

    stats = result["stats"]
    w = result["regime_score"]

    if w >= 8:   g1_w, g2_w, g3_w = 0.80, 0.10, 0.10
    elif w >= 6: g1_w, g2_w, g3_w = 0.60, 0.20, 0.20
    elif w >= 4: g1_w, g2_w, g3_w = 0.30, 0.50, 0.20
    else:         g1_w, g2_w, g3_w = 0.10, 0.40, 0.50

    print(f"  G1(趋势)通过: {stats['g1_pass']}  "
          f"G2(SETUPS)通过: {stats['g2_pass']}  "
          f"G3(ML)通过: {stats['g3_pass']}")
    print(f"  当前权重 → G1={g1_w:.0%}  G2={g2_w:.0%}  G3={g3_w:.0%}"
          f"  (Regime: {result['regime']})")
    print()
    print_recommendations(result["ranked"], top_n=15)


# ══════════════════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    state_file = PROJECT_ROOT / "fintech" / "state" / "2026-05-12.json"
    if len(sys.argv) > 1:
        state_file = Path(sys.argv[1])

    if state_file.exists():
        with open(state_file) as f:
            state = json.load(f)
        p2 = state.get("phases", {}).get("p2", {})
        p3 = state.get("phases", {}).get("p3", {})
    else:
        p2 = {"regime": "UNKNOWN", "score": 5.0}
        p3 = {"sectors": [], "hot_sectors": [], "cold_sectors": []}

    print(f"[P4] Regime: {p2.get('regime')} Score={p2.get('score')}")
    result = run_p4(KLINES_DIR, p2, p3)
    print_p4_result(result)
