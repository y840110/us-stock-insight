#!/usr/bin/env python3
"""
回测实验登记 — record.py
=========================
跑完一次回测后，把结果登记进库。

用法:
    python3 record.py --engine h3_4_1 \
        --params '{"rf":0.35,"trail":4.0}' \
        --result exp9/backtest/results/xxx.json \
        --note "rf35最优候选" --tags '["高杠杆"]'

--result 缺省时，只登记元信息（engine+params+note），指标留空。
"""
import sys, json, argparse
from pathlib import Path
import db


def parse_tags(s):
    if not s:
        return []
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else [s]
    except json.JSONDecodeError:
        return [x.strip() for x in s.split(',') if x.strip()]


def main():
    ap = argparse.ArgumentParser(description='登记一次回测实验')
    ap.add_argument('--engine', required=True, help='引擎名: h3_4_1 / daily / ...')
    ap.add_argument('--engine-file', default=None)
    ap.add_argument('--params', default='{}', help='参数 JSON')
    ap.add_argument('--result', default=None, help='结果 JSON 路径')
    ap.add_argument('--symbols', default=None)
    ap.add_argument('--capital', type=float, default=None, help='初始资金（结果里没有时用）')
    ap.add_argument('--date-start', default=None)
    ap.add_argument('--date-end', default=None)
    ap.add_argument('--status', default='ok')
    ap.add_argument('--tags', default='[]')
    ap.add_argument('--note', default=None)
    args = ap.parse_args()

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError:
        print(f'ERROR: --params 不是合法 JSON: {args.params}')
        sys.exit(1)

    metrics = {}
    if args.result:
        rp = Path(args.result)
        if not rp.exists():
            print(f'ERROR: 结果文件不存在: {args.result}')
            sys.exit(1)
        data = json.load(open(rp, encoding='utf-8'))
        metrics = db.extract_metrics(data, capital=args.capital)

    db.init_db()
    conn = db.get_conn()
    cur = conn.execute(
        """INSERT INTO experiments
           (engine, engine_file, params, symbols, date_start, date_end,
            capital, final_cash, return_pct, win_rate, avg_win, avg_loss,
            rr, max_drawdown, trade_count, lot1_hit, total_profit,
            status, tags, note, result_file)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (args.engine, args.engine_file, json.dumps(params, ensure_ascii=False, sort_keys=True),
         args.symbols, args.date_start, args.date_end,
         metrics.get('capital'), metrics.get('final_cash'), metrics.get('return_pct'),
         metrics.get('win_rate'), metrics.get('avg_win'), metrics.get('avg_loss'),
         metrics.get('rr'), metrics.get('max_drawdown'),
         metrics.get('trade_count'), metrics.get('lot1_hit'), metrics.get('total_profit'),
         args.status, json.dumps(parse_tags(args.tags), ensure_ascii=False),
         args.note, args.result)
    )
    conn.commit()
    eid = cur.lastrowid
    conn.close()
    print(f'✅ 已登记实验 #{eid}: {args.engine} {json.dumps(params, ensure_ascii=False)}'
          + (f' | 收益 {metrics["return_pct"]}%' if metrics.get('return_pct') is not None else ''))


if __name__ == '__main__':
    main()
