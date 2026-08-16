#!/usr/bin/env python3
"""
h3-4-1 策略进化引擎 v2
======================

策略方向扫描 + 网格细化

Phase 1: 8个策略方向快速扫描（每方向1-2个代表参数）
Phase 2: 基于Phase1敏感度，网格细化最优方向

基准：SPY +29.7% | QQQ +45.6%
目标：跑赢两者

参数空间：
  atr_mult        : 初始止损倍数（守住本金）
  atr_trailing   : ATR跟踪止盈（控制出场）
  min_hold       : 最小持仓小时（避免频繁交易）
  risk_frac      : 每仓资金比例（仓位管理）
  target_mult    : 日线目标倍数（让利润奔跑）
  max_pos        : 最大持仓数（集中度）
"""

import sys
import json
import time
import re
import os
import argparse
from pathlib import Path
from datetime import datetime
from multiprocessing import Pool, cpu_count

BASE = Path(__file__).resolve().parent.parent
# 引擎位于 live_trading/当前最优/，其 BASE 是 live_trading/
ENGINE_LIVE = BASE / 'live_trading'
ENGINE_PATH = ENGINE_LIVE / 'engine' / 'engine_h3_4_1.py'
# 引擎写入结果的路径 = ENGINE_LIVE / 'htrade' / ...
ENGINE_RESULT_JSON = ENGINE_LIVE / 'htrade' / 'results_h3_4_1_2025_2026.json'
MODEL_EXPERTS = '/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/model/experts'
INITIAL_CASH = 10000   # 保持 $10k 与原始引擎一致（仓位比例核心指标）

BENCHMARKS = {'SPY': 29.7, 'QQQ': 45.6}

# ═══════════════════════════════════════════════════════
# 8个策略方向（Phase 1）
# ═══════════════════════════════════════════════════════
STRATEGIES = {
    'baseline': {
        'desc': '当前参数（基准）',
        'atr_mult': 1.5, 'atr_trailing': 4.0, 'min_hold': 5, 'risk_frac': 0.20,
        'target_mult': 3.0, 'max_pos': 5,
    },
    'tight_stop': {
        'desc': '核心：紧止损守住本金',
        'atr_mult': 0.75, 'atr_trailing': 3.0, 'min_hold': 5, 'risk_frac': 0.20,
        'target_mult': 3.0, 'max_pos': 5,
    },
    'aggressive_trail': {
        'desc': '核心：紧跟踪止盈（防止回撤吞噬）',
        'atr_mult': 1.5, 'atr_trailing': 2.0, 'min_hold': 5, 'risk_frac': 0.20,
        'target_mult': 3.0, 'max_pos': 5,
    },
    'small_pos': {
        'desc': '核心：小仓位多分散（降低黑天鹅）',
        'atr_mult': 1.5, 'atr_trailing': 4.0, 'min_hold': 5, 'risk_frac': 0.10,
        'target_mult': 3.0, 'max_pos': 8,
    },
    'large_pos': {
        'desc': '核心：大仓位少集中（牛市中子弹用在刀刃上）',
        'atr_mult': 1.5, 'atr_trailing': 4.0, 'min_hold': 5, 'risk_frac': 0.35,
        'target_mult': 3.0, 'max_pos': 3,
    },
    'short_target': {
        'desc': '核心：短目标早出场（强势市场落袋为安）',
        'atr_mult': 1.5, 'atr_trailing': 4.0, 'min_hold': 5, 'risk_frac': 0.20,
        'target_mult': 2.0, 'max_pos': 5,
    },
    'long_target': {
        'desc': '核心：长目标让利润奔跑（趋势跟踪）',
        'atr_mult': 1.5, 'atr_trailing': 5.0, 'min_hold': 8, 'risk_frac': 0.20,
        'target_mult': 5.0, 'max_pos': 5,
    },
    'combined': {
        'desc': '激进组合：紧止损+紧跟踪+小仓位',
        'atr_mult': 0.75, 'atr_trailing': 2.0, 'min_hold': 5, 'risk_frac': 0.10,
        'target_mult': 2.5, 'max_pos': 5,
    },
    'momentum': {
        'desc': '动量模式：长持仓+宽跟踪+大目标',
        'atr_mult': 2.0, 'atr_trailing': 6.0, 'min_hold': 12, 'risk_frac': 0.25,
        'target_mult': 6.0, 'max_pos': 5,
    },
}


# ═══════════════════════════════════════════════════════
# Phase 2 细化网格（基于 Phase1 最优方向）
# ═══════════════════════════════════════════════════════
REFINEMENT_GRID = [
    #atr_mult, atr_trailing, min_hold, risk_frac, target_mult, max_pos
    [1.5, 4.0,  5, 0.20, 3.0, 5],  # baseline
    [1.5, 3.0,  5, 0.20, 3.0, 5],   # trail tighter
    [1.5, 2.5,  5, 0.20, 3.0, 5],   # trail even tighter
    [1.5, 2.0,  5, 0.20, 3.0, 5],   # very tight trail
    [1.5, 3.0,  5, 0.15, 3.0, 5],   # + lower risk_frac
    [1.5, 2.5,  5, 0.15, 3.0, 5],   # + lower risk_frac
    [1.5, 2.0,  5, 0.15, 3.0, 5],   # + lower risk_frac
    [1.5, 3.0,  5, 0.25, 3.0, 5],   # + higher risk_frac
    [1.5, 2.5,  5, 0.25, 3.0, 5],   # + higher risk_frac
    [1.5, 2.0,  5, 0.25, 3.0, 5],   # + higher risk_frac
    [1.0, 3.0,  5, 0.20, 3.0, 5],   # tighter entry stop
    [1.0, 2.5,  5, 0.20, 3.0, 5],   #
    [1.0, 2.0,  5, 0.20, 3.0, 5],   #
    [1.0, 2.5,  5, 0.15, 3.0, 5],   #
    [1.0, 2.0,  5, 0.15, 3.0, 5],   #
    [1.5, 3.0,  8, 0.20, 3.0, 5],   # longer hold
    [1.5, 2.5,  8, 0.20, 3.0, 5],   #
    [1.5, 2.0,  8, 0.20, 3.0, 5],   #
    [1.0, 2.5,  8, 0.15, 3.0, 5],   #
    [1.0, 2.0,  8, 0.15, 3.0, 5],   #
    [1.5, 3.0,  5, 0.20, 4.0, 5],   # higher target
    [1.5, 2.5,  5, 0.20, 4.0, 5],   #
    [1.5, 2.0,  5, 0.20, 4.0, 5],   #
    [1.0, 2.5,  8, 0.15, 4.0, 5],   #
    [1.0, 2.0,  8, 0.15, 4.0, 5],   #
    # 集中持牛市方向
    [1.5, 3.0,  5, 0.30, 3.0, 3],   # high conviction, fewer pos
    [1.0, 2.5,  5, 0.30, 3.0, 3],   #
    [1.0, 2.0,  5, 0.25, 3.0, 3],   #
    [1.5, 2.5,  5, 0.25, 3.0, 3],   #
]


# ═══════════════════════════════════════════════════════
def run_backtest(params: list) -> dict:
    """
    params: [atr_mult, atr_trailing, min_hold, risk_frac, target_mult, max_pos]
    策略：
      1. 运行引擎生成 JSONL 日志（--debug）
      2. 用 replay_engine 计算精确最终资金（修复 lot2 双倍问题）
    """
    import subprocess, re

    atr_mult, atr_trailing, min_hold, risk_frac, target_mult, max_pos = params

    # 引擎 JSONL 日志目录（引擎会在此写入 trades_h3_4_1_{ts}.jsonl）
    jsonl_dir = ENGINE_LIVE / 'htrade' / 'logs'
    jsonl_dir.mkdir(exist_ok=True)
    # jsonl_out 稍后从引擎输出中提取实际文件名

    cmd = [
        sys.executable, str(ENGINE_PATH),
        '--years', '2025', '2026',
        '--capital', str(INITIAL_CASH),
        '--atr-mult', str(atr_mult),
        '--atr-trailing-mult', str(atr_trailing),
        '--min-hold', str(min_hold),
        '--target-mult', str(target_mult),
        '--max-pos', str(max_pos),
        '--debug',
    ]

    env = os.environ.copy()
    env['PYTHONPATH'] = MODEL_EXPERTS

    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=300, cwd=str(BASE), env=env)
        output = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return {**dict(zip(['atr_mult','atr_trailing','min_hold','risk_frac','target_mult','max_pos'], params)), 'error': 'timeout', 'return_pct': -999}
    except Exception as e:
        return {**dict(zip(['atr_mult','atr_trailing','min_hold','risk_frac','target_mult','max_pos'], params)), 'error': str(e), 'return_pct': -999}

    # 从引擎输出中提取实际 JSONL 文件名
    jsonl_name = None
    for line in output.split('\n'):
        if '写入' in line and '.jsonl' in line:
            jsonl_name = line.split(': ')[-1].strip()
            break

    if not jsonl_name:
        return {**dict(zip(['atr_mult','atr_trailing','min_hold','risk_frac','target_mult','max_pos'], params)),
                'error': f'no_jsonl_line: {output[-300:] if output else "empty"}', 'return_pct': -999}

    jsonl_out = jsonl_dir / jsonl_name

    if not jsonl_out.exists():
        return {**dict(zip(['atr_mult','atr_trailing','min_hold','risk_frac','target_mult','max_pos'], params)),
                'error': f'jsonl_not_found: {jsonl_out}', 'return_pct': -999}

    # replay_engine 计算精确最终资金
    replay_cmd = [
        sys.executable, str(BASE / 'live_trading' / 'replay_engine.py'),
        '--log', str(jsonl_out),
        '--cash', str(INITIAL_CASH),
    ]
    try:
        rp = subprocess.run(replay_cmd, capture_output=True, text=True,
                           timeout=60, cwd=str(BASE))
        replay_out = rp.stdout + rp.stderr
    except:
        replay_out = ''

    # 解析 replay_engine 输出
    final_cash = None
    return_pct = None
    win_rate = None
    total_trades = None
    buy_count = None
    skip_count = None

    for line in replay_out.split('\n'):
        m = re.search(r'最终现金.*?\$?([\d,]+\.?\d*)', line)
        if m:
            try: final_cash = float(m.group(1).replace(',',''))
            except: pass
        m = re.search(r'总收益率.*?([+-]?[\d.]+)%', line)
        if m:
            try: return_pct = float(m.group(1))
            except: pass
        m = re.search(r'胜率.*?([\d.]+)%', line)
        if m:
            try: win_rate = float(m.group(1))
            except: pass
        m = re.search(r'买操作.*?(\d+)\s*次', line)
        if m:
            try: buy_count = int(m.group(1))
            except: pass
        m = re.search(r'盈利交易.*?(\d+)\s*笔', line)
        if m:
            try: total_trades = int(m.group(1))
            except: pass
        m = re.search(r'跳过.*?(\d+)\s*次', line)
        if m:
            try: skip_count = int(m.group(1))
            except: pass

    if final_cash is None:
        return {**dict(zip(['atr_mult','atr_trailing','min_hold','risk_frac','target_mult','max_pos'], params)),
                'error': 'replay_parse_failed', 'return_pct': -999}

    # 清理临时 JSONL
    try:
        jsonl_out.unlink()
    except: pass

    return parse_and_score(params=params, output=output,
                           final_cash=final_cash, return_pct=return_pct,
                           win_rate=win_rate,
                           total_trades=total_trades,
                           buy_count=buy_count)


def subprocess_run(cmd, env, timeout=300):
    import subprocess
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(BASE), env=env)
    return r.stdout + r.stderr


def parse_and_score(params, output, final_cash=None, return_pct=None, win_rate=None,
                     total_trades=None, buy_count=None, skip_count=None):
    """基于引擎输出和交易记录计算最终分数"""
    spy_bh = BENCHMARKS['SPY']
    qqq_bh = BENCHMARKS['QQQ']
    return_pct = return_pct if return_pct is not None else -999
    beat_spy = 1 if return_pct > spy_bh else 0
    beat_qqq = 1 if return_pct > qqq_bh else 0

    return {
        'atr_mult': params[0], 'atr_trailing': params[1],
        'min_hold': params[2], 'risk_frac': params[3],
        'target_mult': params[4], 'max_pos': params[5],
        'final_cash': round(final_cash, 2) if final_cash else None,
        'return_pct': round(return_pct, 2),
        'win_rate': round(win_rate, 1) if win_rate else None,
        'total_trades': total_trades,
        'buy_count': buy_count,
        'skip_count': skip_count,
        'beat_spy': beat_spy,
        'beat_qqq': beat_qqq,
        'excess_vs_spy': round(return_pct - spy_bh, 2),
        'excess_vs_qqq': round(return_pct - qqq_bh, 2),
        'score': round((return_pct - spy_bh) * 0.4 + (return_pct - qqq_bh) * 0.6, 2),
        'error': None,
    }


# ═══════════════════════════════════════════════════════
def run_phase1() -> list:
    """Phase 1: 策略方向扫描"""
    print(f"\n{'='*60}")
    print(f"  Phase 1: 策略方向扫描 ({len(STRATEGIES)} 个方向)")
    print(f"  基准: SPY +{BENCHMARKS['SPY']}% | QQQ +{BENCHMARKS['QQQ']}%")
    print(f"{'='*60}\n")

    results = []
    t0 = time.time()

    for name, s in STRATEGIES.items():
        params = [s['atr_mult'], s['atr_trailing'], s['min_hold'],
                  s['risk_frac'], s['target_mult'], s['max_pos']]
        label = f"{name:20s} | {s['desc']}"
        print(f"  ▶ {label}", flush=True)
        r = run_backtest(params)
        r['strategy'] = name
        r['desc'] = s['desc']
        results.append(r)
        mark = ' 🏆' if r['beat_spy'] and r['beat_qqq'] else (' ✅SPY' if r['beat_spy'] else (' ✅QQQ' if r['beat_qqq'] else ''))
        print(f"    ← return={r['return_pct']:+.1f}% | excess_vs_spy={r['excess_vs_spy']:+.1f}% | excess_vs_qqq={r['excess_vs_qqq']:+.1f}% | win={r.get('win_rate','?')}%{mark}")

    elapsed = time.time() - t0
    return results, elapsed


def run_phase2(best_base: list) -> list:
    """Phase 2: 基于最优方向细化网格"""
    print(f"\n{'='*60}")
    print(f"  Phase 2: 网格细化 ({len(REFINEMENT_GRID)} 组合)")
    print(f"{'='*60}\n")

    t0 = time.time()
    with Pool(processes=min(cpu_count(), 12)) as pool:
        results = pool.map(run_backtest, REFINEMENT_GRID)

    elapsed = time.time() - t0
    return results, elapsed


def print_summary(all_results: list, phase1_time: float, phase2_time: float):
    all_results.sort(key=lambda x: x.get('score', -999), reverse=True)

    print(f"\n{'='*70}")
    print(f"  进化结果汇总 | Phase1={phase1_time:.0f}s | Phase2={phase2_time:.0f}s")
    print(f"  基准: SPY +{BENCHMARKS['SPY']}% | QQQ +{BENCHMARKS['QQQ']}%")
    print(f"{'='*70}")

    beat_spy = [r for r in all_results if r.get('beat_spy') == 1]
    beat_qqq = [r for r in all_results if r.get('beat_qqq') == 1]
    beat_both = [r for r in all_results if r.get('beat_spy') == 1 and r.get('beat_qqq') == 1]

    print(f"\n  跑赢 SPY: {len(beat_spy)}/{len(all_results)} 个组合")
    print(f"  跑赢 QQQ: {len(beat_qqq)}/{len(all_results)} 个组合")
    print(f"  同时跑赢两者: {len(beat_both)} 个组合")

    if beat_both:
        print(f"\n  🏆 同时跑赢 SPY & QQQ 的最优组合：")
        for i, r in enumerate(beat_both[:5], 1):
            print(f"  {i}. return={r['return_pct']:+.1f}% | "
                  f"vs_spy={r['excess_vs_spy']:+.1f}% | vs_qqq={r['excess_vs_qqq']:+.1f}% | "
                  f"atr×={r['atr_mult']} trail={r['atr_trailing']}×ATR | "
                  f"hold={r['min_hold']}h | rf={r['risk_frac']} | "
                  f"tgt={r['target_mult']}× | pos={r['max_pos']}")

    if beat_spy and not beat_both:
        print(f"\n  ✅ 跑赢 SPY 的最优组合：")
        for i, r in enumerate(beat_spy[:5], 1):
            print(f"  {i}. return={r['return_pct']:+.1f}% | "
                  f"atr×={r['atr_mult']} trail={r['atr_trailing']}×ATR | "
                  f"hold={r['min_hold']}h | rf={r['risk_frac']} | tgt={r['target_mult']}×")

    # Top10 全部组合
    print(f"\n  📊 Top10 所有组合：")
    print(f"  {'#':<3} {'return':>8} {'vsSPY':>7} {'vsQQQ':>7} {'win%':>5} | "
          f"{'atr×':>5} {'tr':>5} {'hld':>4} {'rf':>5} {'tgt':>5} {'pos':>4} | desc")
    print(f"  {'-'*90}")
    for i, r in enumerate(all_results[:10], 1):
        m = ''
        if r.get('beat_spy') and r.get('beat_qqq'): m = ' 🏆'
        elif r.get('beat_spy'): m = ' ✅SPY'
        elif r.get('beat_qqq'): m = ' ✅QQQ'
        desc = r.get('desc', r.get('strategy', ''))
        print(f"  {i:<3} {r['return_pct']:>+7.1f}% {r['excess_vs_spy']:>+6.1f}% {r['excess_vs_qqq']:>+6.1f}% {str(r.get('win_rate','?')):>4}% | "
              f"{r['atr_mult']:>5} {r['atr_trailing']:>5} {r['min_hold']:>4} {r['risk_frac']:>5} {r['target_mult']:>5} {r['max_pos']:>4} | {desc[:30]}{m}")

    # 单参数敏感度
    print(f"\n  📈 单参数敏感度分析：")
    for param in ['atr_mult', 'atr_trailing', 'min_hold', 'risk_frac', 'target_mult', 'max_pos']:
        vals = {}
        for r in all_results:
            pv = r.get(param)
            if pv is not None:
                if pv not in vals: vals[pv] = []
                vals[pv].append(r['return_pct'])
        if vals:
            avgs = {v: sum(ret)/len(ret) for v, ret in vals.items()}
            best_v = max(avgs, key=avgs.get)
            worst_v = min(avgs, key=avgs.get)
            print(f"  {param:15s}: best={best_v}({avgs[best_v]:+.1f}%) | "
                  f"worst={worst_v}({avgs[worst_v]:+.1f}%) | spread={avgs[best_v]-avgs[worst_v]:+.1f}%")

    return all_results


def save_results(all_results, phase1_results, phase2_results, out_dir):
    import csv
    out_dir.mkdir(parents=True, exist_ok=True)

    # 全部结果
    all_sorted = sorted(all_results, key=lambda x: x.get('score', -999), reverse=True)
    fieldnames = list(all_sorted[0].keys()) if all_sorted else []

    csv_path = out_dir / 'evolution_results.csv'
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_sorted)
    print(f"\n✅ 结果已保存: {csv_path}")

    # Top5
    top5_path = out_dir / 'evolution_top5.csv'
    with open(top5_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_sorted[:5])
    print(f"✅ Top5 已保存: {top5_path}")

    # Phase1 分组
    p1_path = out_dir / 'evolution_phase1.csv'
    with open(p1_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sorted(phase1_results, key=lambda x: x.get('score', -999), reverse=True))
    print(f"✅ Phase1 已保存: {p1_path}")


# ═══════════════════════════════════════════════════════
if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase1-only', action='store_true')
    ap.add_argument('--phase2-only', action='store_true')
    ap.add_argument('--output-dir', default=None)
    args = ap.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else (
        BASE / 'live_trading' / 'evolution_results' / datetime.now().strftime('%Y%m%d_%H%M%S')
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    all_results = []

    phase1_results = []
    phase2_results = []
    phase1_time = 0
    phase2_time = 0

    if not args.phase2_only:
        phase1_results, phase1_time = run_phase1()
        all_results.extend(phase1_results)

    if not args.phase1_only:
        # 从 Phase1 找最优 base params 决定 Phase2 方向
        if phase1_results:
            best_p1 = max(phase1_results, key=lambda x: x.get('score', -999))
            print(f"\n  → Phase1 最优: {best_p1.get('strategy','?')} ({best_p1.get('desc','')})")
            print(f"    return={best_p1['return_pct']:+.1f}% | score={best_p1.get('score','?')}")
        phase2_results, phase2_time = run_phase2(phase1_results)
        all_results.extend(phase2_results)

    # 汇总
    summary_results = print_summary(all_results, phase1_time, phase2_time)
    save_results(all_results, phase1_results, phase2_results, out_dir)

    print(f"\n  📁 结果目录: {out_dir}")
    print(f"\n{'='*70}")
    print(f"  基准: SPY +{BENCHMARKS['SPY']}% | QQQ +{BENCHMARKS['QQQ']}%")
    best = max(all_results, key=lambda x: x.get('score', -999)) if all_results else None
    if best:
        print(f"  最优: return={best['return_pct']:+.1f}% | "
              f"vs_spy={best['excess_vs_spy']:+.1f}% | vs_qqq={best['excess_vs_qqq']:+.1f}%")
    print(f"{'='*70}\n")
