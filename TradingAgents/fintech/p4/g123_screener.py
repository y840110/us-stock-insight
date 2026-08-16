#!/usr/bin/env python3
"""
g123_screener.py — 兼容层
==========================
保留此文件仅用于向后兼容旧代码。
实际逻辑已拆分至 g1_screener.py / g2_screener.py / g3_screener.py / p4_dispatcher.py

用法（向后兼容）：
    from fintech.p4.g123_screener import scan_stocks
    regime, score, candidates, flat = scan_stocks(p2_regime)
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

# 代理到 p4_dispatcher
sys.path.insert(0, str(Path(__file__).parent))
from p4_dispatcher import run_p4 as _dispatcher_run_p4

def scan_stocks(p2_regime: dict | None = None):
    """
    向后兼容接口。
    内部调用 p4_dispatcher.run_p4()。

    返回 (regime, regime_score, candidates_dict, flat_candidates_list)
    """
    if p2_regime is None:
        p2_regime = {"regime": "超强牛市", "score": 8.0}

    result = _dispatcher_run_p4(p2_regime, {"sectors": [], "hot_sectors": [], "cold_sectors": []})

    # 转换回旧格式
    candidates_dict = {"L1": [], "L2": [], "L3": [], "L4": []}
    for s in result["candidates"]:
        for tier_key in ["tier_g1", "tier_g2", "tier_g3"]:
            tier_val = s.get(tier_key, "NONE")
            if tier_val in ("L1", "L2", "L3", "L4"):
                candidates_dict[tier_val].append(s)

    return (
        result["regime"],
        result["regime_score"],
        candidates_dict,
        result["candidates"],
    )
