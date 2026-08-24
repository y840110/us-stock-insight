#!/usr/bin/env python3
"""
回测实验查询 — query.py
========================
用法:
    python3 query.py --optimal          # 按引擎分组，各自当前最优
    python3 query.py --optimal-all      # 全局最优（跨引擎）
    python3 query.py --history h3_4_1   # 某引擎参数演进史
    python3 query.py --pits             # 全部坑记录
    python3 query.py --compare 12 15    # 两两对比
    --by return_pct|rr|win_rate|drawdown   # 最优排序依据（默认 return_pct）
"""
import sys, json, argparse
import db


def _fmt_pct(v):
    return f'{v:+.1f}%' if v is not None else '—'


def _print_rows(rows, title):
    print(f'\n===== {title} =====')
    if not rows:
        print('  (无记录)')
        return
    for r in rows:
        p = json.loads(r['params']) if r['params'] else {}
        line = (f"#{r['id']} [{r['engine']}] 收益={_fmt_pct(r['return_pct'])} "
                f"| 胜率={_fmt_pct(r['win_rate'])} | RR={r['rr'] if r['rr'] is not None else '—'} "
                f"| 回撤={_fmt_pct(r['max_drawdown'])} | 交易={r['trade_count'] or 0}笔")
        if p:
            line += f"\n       参数={json.dumps(p, ensure_ascii=False)}"
        if r['note']:
            line += f"\n       备注={r['note']}"
        print('  ' + line.replace('\n', '\n  '))
    print()


def _optimal(conn, by, group_by_engine):
    sort = {'return_pct': 'return_pct', 'rr': 'rr',
            'win_rate': 'win_rate', 'drawdown': 'max_drawdown'}.get(by, 'return_pct')
    # NULL 排最后：ORDER BY (col IS NULL), col DESC
    order = f'({sort} IS NULL), {sort} DESC, rr DESC'
    if group_by_engine:
        rows = conn.execute(
            f"""SELECT e.* FROM experiments e
                JOIN (SELECT engine, MAX({sort}) mx FROM experiments
                      WHERE {sort} IS NOT NULL GROUP BY engine) b
                  ON e.engine = b.engine AND e.{sort} = b.mx
                ORDER BY e.{sort} DESC""").fetchall()
        title = f'各引擎当前最优（按 {sort}）'
    else:
        rows = conn.execute(
            f'SELECT * FROM experiments ORDER BY {order} LIMIT 10').fetchall()
        title = f'全局最优 TOP10（按 {sort}）'
    _print_rows(rows, title)


def _history(conn, engine):
    rows = conn.execute(
        'SELECT * FROM experiments WHERE engine=? ORDER BY created_at, id',
        (engine,)).fetchall()
    _print_rows(rows, f'{engine} 演进史（{len(rows)} 次）')


def _pits(conn):
    rows = conn.execute('SELECT * FROM pitfalls ORDER BY severity DESC, id').fetchall()
    print('\n===== 坑/教训记录 =====')
    if not rows:
        print('  (暂无记录)')
        return
    for r in rows:
        sev = {'高': '🔴', '中': '🟠', '低': '🟡'}.get(r['severity'], '')
        print(f"  {sev}[{r['severity']}] #{r['id']} {r['title']} (引擎={r['engine'] or '—'}, 类={r['category'] or '—'})")
        if r['lesson']:
            print(f"       教训: {r['lesson']}")
    print()


def _compare(conn, ids):
    ids = [int(i) for i in ids]
    ph = ','.join('?' * len(ids))
    rows = conn.execute(f'SELECT * FROM experiments WHERE id IN ({ph}) ORDER BY id', ids).fetchall()
    _print_rows(rows, '对比')


def main():
    ap = argparse.ArgumentParser(description='查询回测实验')
    ap.add_argument('--optimal', action='store_true')
    ap.add_argument('--optimal-all', action='store_true')
    ap.add_argument('--history', metavar='ENGINE')
    ap.add_argument('--pits', action='store_true')
    ap.add_argument('--compare', nargs='+', metavar='ID')
    ap.add_argument('--by', default='return_pct',
                    choices=['return_pct', 'rr', 'win_rate', 'drawdown'])
    args = ap.parse_args()

    db.init_db()
    conn = db.get_conn()

    if args.optimal:
        _optimal(conn, args.by, group_by_engine=True)
    elif args.optimal_all:
        _optimal(conn, args.by, group_by_engine=False)
    elif args.history:
        _history(conn, args.history)
    elif args.pits:
        _pits(conn)
    elif args.compare:
        _compare(conn, args.compare)
    else:
        ap.print_help()
    conn.close()


if __name__ == '__main__':
    main()
