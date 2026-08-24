#!/usr/bin/env python3
"""
参数网格扫描 — sweep.py
========================
给定引擎 + 参数网格，逐组跑回测，自动登记进 backtest.db，最后报排名。

用法:
    python3 sweep.py --engine h3_4_1 --rf 0.25 0.30 0.35 --trail 3.5 4.0 4.5 --years 2025 2026
    python3 sweep.py --engine daily --rf 0.25 0.35 --trail 2.5 3.0 --capital 20000
    python3 sweep.py --engine h3_4_1 --rf 0.30 --trail 4.0 --dry-run   # 只预览组合

只对用户显式给出的参数做笛卡尔积；未给出的参数用引擎默认值。
"""
import argparse, itertools, json, subprocess
from pathlib import Path
import db

PROJ_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJ_ROOT / 'exp9' / 'backtest' / 'results'

ENGINES = {
    'h3_4_1': {
        'script': 'exp9/live_trading/engine/engine_h3_4_1.py',
        'prefix': 'results_h3_4_1_',
        'param_map': {  # 通用参数名 → 引擎 CLI flag
            'rf': '--risk-frac', 'trail': '--atr-trailing-mult',
            'atr': '--atr-mult', 'tgt': '--target-mult',
            'hold': '--min-hold', 'pos': '--max-pos',
        },
    },
    'daily': {
        'script': 'exp9/live_trading/engine/engine_daily.py',
        'prefix': 'results_daily_',
        'param_map': {
            'rf': '--risk-frac', 'trail': '--trail-mult',
            'atr': '--atr-mult', 'tgt': '--target-mult',
            'hold': '--min-hold', 'pos': '--max-pos',
        },
    },
}


def build_grid(args):
    """只对用户指定的参数做笛卡尔积，返回参数 dict 列表。"""
    axes = []
    for key, vals in [('rf', args.rf), ('trail', args.trail), ('atr', args.atr),
                      ('tgt', args.tgt), ('hold', args.hold), ('pos', args.pos)]:
        if vals:
            axes.append((key, vals))
    if not axes:
        return [{}]
    keys = [k for k, _ in axes]
    combos = [dict(zip(keys, c)) for c in itertools.product(*[v for _, v in axes])]
    return combos


def make_tag(combo):
    return 'sweep_' + '_'.join(f'{k}{v}' for k, v in sorted(combo.items()))


def run_one(engine, cfg, combo, args, tag):
    """跑一组参数，返回结果 JSON 路径（失败返回 None）。"""
    cmd = ['python3', str(PROJ_ROOT / cfg['script'])]
    for key, val in combo.items():
        cmd += [cfg['param_map'][key], str(val)]
    cmd += ['--years', str(args.years[0]), str(args.years[1]), '--capital', str(args.capital)]
    if args.tickers:
        cmd += ['--tickers'] + args.tickers
    cmd += ['--tag', tag]

    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJ_ROOT))
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or '').strip().splitlines()[-3:]
        print(f'  ❌ {tag} 失败: {" | ".join(tail)}')
        return None
    rp = RESULTS_DIR / f'{cfg["prefix"]}{tag}.json'
    if not rp.exists():
        print(f'  ❌ {tag} 结果文件缺失: {rp.name}')
        return None
    return rp


def main():
    ap = argparse.ArgumentParser(description='参数网格扫描回测')
    ap.add_argument('--engine', required=True, choices=list(ENGINES.keys()))
    ap.add_argument('--rf', nargs='+', type=float)
    ap.add_argument('--trail', nargs='+', type=float)
    ap.add_argument('--atr', nargs='+', type=float)
    ap.add_argument('--tgt', nargs='+', type=float)
    ap.add_argument('--hold', nargs='+', type=int)
    ap.add_argument('--pos', nargs='+', type=int)
    ap.add_argument('--years', nargs=2, default=['2025', '2026'])
    ap.add_argument('--capital', type=float, default=20000)
    ap.add_argument('--tickers', nargs='*')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    cfg = ENGINES[args.engine]
    combos = build_grid(args)
    print(f'引擎 {args.engine} | {len(combos)} 组参数 | 区间 {args.years[0]}-{args.years[1]}')

    if args.dry_run:
        for c in combos:
            print(f'  [dry] {json.dumps(c, ensure_ascii=False)}')
        return

    db.init_db()
    conn = db.get_conn()
    rows = []
    for i, combo in enumerate(combos, 1):
        tag = make_tag(combo)
        print(f'[{i}/{len(combos)}] {json.dumps(combo, ensure_ascii=False)} ...', end=' ', flush=True)
        rp = run_one(args.engine, cfg, combo, args, tag)
        if rp is None:
            continue
        data = json.load(open(rp, encoding='utf-8'))
        m = db.extract_metrics(data)
        # 登记
        cur = conn.execute(
            """INSERT INTO experiments
               (engine, params, date_start, date_end, capital, final_cash,
                return_pct, win_rate, avg_win, avg_loss, rr, max_drawdown,
                trade_count, total_profit, status, note, result_file)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (args.engine, db.params_to_json(combo), None, None,
             m.get('capital'), m.get('final_cash'), m.get('return_pct'),
             m.get('win_rate'), m.get('avg_win'), m.get('avg_loss'),
             m.get('rr'), m.get('max_drawdown'),
             m.get('trade_count'), m.get('total_profit'),
             'ok', f'sweep', str(rp.relative_to(PROJ_ROOT))))
        conn.commit()
        rows.append((cur.lastrowid, combo, m))
        print(f"收益={m.get('return_pct') if m.get('return_pct') is not None else '—'}% "
              f"胜率={m.get('win_rate')}% RR={m.get('rr')} 回撤={m.get('max_drawdown') if m.get('max_drawdown') is not None else '—'}%")

    # 排名（按收益率，NULL 排最后）
    print(f'\n===== 本轮扫描排名（{len(rows)} 组成功）=====')
    ranked = sorted(rows, key=lambda x: (x[2].get('return_pct') is None,
                                         -(x[2].get('return_pct') or 0),
                                         -(x[2].get('rr') or 0)))
    for rank, (eid, combo, m) in enumerate(ranked, 1):
        flag = '🏆' if rank == 1 else '  '
        print(f'  {flag} #{rank} {json.dumps(combo, ensure_ascii=False)} | '
              f"收益={m.get('return_pct') if m.get('return_pct') is not None else '—'}% "
              f"胜率={m.get('win_rate')}% RR={m.get('rr')} 回撤={m.get('max_drawdown') if m.get('max_drawdown') is not None else '—'}%")
    conn.close()


if __name__ == '__main__':
    main()
