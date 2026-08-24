#!/usr/bin/env python3
"""
回溯导入旧回测结果 — import_legacy.py
=====================================
扫描 exp9/ 下所有 results_*.json，解析文件名得到 engine+params，
抽取指标入库，重建历史演进记录。

用法:
    python3 import_legacy.py            # 全量导入（按 result_file 去重）
    python3 import_legacy.py --dry-run  # 只预览，不写库
"""
import sys, json, argparse, glob
from pathlib import Path
import db

PROJ_ROOT = Path(__file__).resolve().parent.parent


def find_result_files():
    return sorted(glob.glob(str(PROJ_ROOT / 'exp9' / '**' / 'results_*.json'), recursive=True))


def extract_date_range(data):
    """从 trades 推回测区间：min(entry_date) ~ max(exit_date)。"""
    trades = data.get('trades') or []
    starts, ends = [], []
    for t in trades:
        if t.get('entry_date'):
            starts.append(str(t['entry_date'])[:10])
        if t.get('exit_date'):
            ends.append(str(t['exit_date'])[:10])
    if not starts and not ends:
        return None, None
    return (min(starts) if starts else None, max(ends) if ends else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    files = find_result_files()
    print(f'找到 {len(files)} 个 results_*.json')

    db.init_db()
    conn = db.get_conn()
    existing = {r['result_file'] for r in conn.execute(
        'SELECT result_file FROM experiments WHERE result_file IS NOT NULL')}

    imported = skipped = failed = 0
    for fp in files:
        rel = str(Path(fp).relative_to(PROJ_ROOT))
        if rel in existing:
            skipped += 1
            continue
        try:
            data = json.load(open(fp, encoding='utf-8'))
            stem = Path(fp).stem            # results_h3_4_1_rf0.25_t4.0
            name = stem.replace('results_', '', 1)
            engine, params = db.parse_filename(name)
            metrics = db.extract_metrics(data)
            dstart, dend = extract_date_range(data)
            note = f'legacy:{stem}'

            if args.dry_run:
                print(f'  [dry] {rel} -> engine={engine} params={params} '
                      f'win={metrics.get("win_rate")}% rr={metrics.get("rr")} '
                      f'profit={metrics.get("total_profit")}')
                imported += 1
                continue

            conn.execute(
                """INSERT INTO experiments
                   (engine, params, date_start, date_end, capital, final_cash,
                    return_pct, win_rate, avg_win, avg_loss, rr, max_drawdown,
                    trade_count, lot1_hit, total_profit,
                    status, note, result_file)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (engine, db.params_to_json(params), dstart, dend,
                 metrics.get('capital'), metrics.get('final_cash'), metrics.get('return_pct'),
                 metrics.get('win_rate'), metrics.get('avg_win'), metrics.get('avg_loss'),
                 metrics.get('rr'), metrics.get('max_drawdown'),
                 metrics.get('trade_count'), metrics.get('lot1_hit'),
                 metrics.get('total_profit'), 'ok', note, rel))
            imported += 1
        except Exception as e:
            failed += 1
            print(f'  ❌ 导入失败 {fp}: {e}')

    conn.commit()
    conn.close()
    print(f'\n完成: 导入 {imported} | 跳过(已存在) {skipped} | 失败 {failed}')


if __name__ == '__main__':
    main()
