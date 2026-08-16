#!/usr/bin/env python3
"""
短线交易日志管理器
功能：
  1. 添加交易记录
  2. 检查是否允许交易（每天最多3笔 + 2连亏后休3天）
  3. 每半年自动归档
  4. 统计胜率

用法：
  python3 短线交易管理器.py --add          # 添加交易记录（交互式）
  python3 短线交易管理器.py --status       # 查看当前状态
  python3 短线交易管理器.py --log          # 查看最近20条记录
  python3 短线交易管理器.py --stats       # 统计胜率
  python3 短线交易管理器.py --archive      # 手动归档（半年自动触发）
"""

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import datetime, timedelta
import sys, os, json

LOG_DIR = '/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/短线交易日志'
EXCEL_FILE = os.path.join(LOG_DIR, '短线交易日志.xlsx')
ARCHIVE_DIR = os.path.join(LOG_DIR, 'archives')
os.makedirs(ARCHIVE_DIR, exist_ok=True)

# 列定义
COLUMNS = [
    '序号', '日期', '时间', '标的', '模型',
    '入场价', '止损价', '出场价',
    '盈亏金额', '盈亏比例', '结果',
    '入场评分', '复盘备注', '是否归档'
]
COL_WIDTHS = [6, 12, 8, 10, 10, 10, 10, 10, 12, 10, 8, 10, 30, 8]

# 样式
HEADER_FILL = PatternFill(start_color='1F4E79', end_color='1F4E79', fill_type='solid')
HEADER_FONT = Font(color='FFFFFF', bold=True, size=11)
WIN_FILL = PatternFill(start_color='C6EFCE', end_color='C6EFCE', fill_type='solid')
LOSS_FILL = PatternFill(start_color='FFC7CE', end_color='FFC7CE', fill_type='solid')
EVEN_FILL = PatternFill(start_color='FFEB9C', end_color='FFEB9C', fill_type='solid')
SUSPEND_FILL = PatternFill(start_color='FF6B6B', end_color='FF6B6B', fill_type='solid')
THIN = Side(style='thin', color='BFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

def load_wb():
    if not os.path.exists(EXCEL_FILE):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = '交易日志'
        # 写表头
        for col_idx, (col_name, width) in enumerate(zip(COLUMNS, COL_WIDTHS), 1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = BORDER
            ws.column_dimensions[get_column_letter(col_idx)].width = width
        ws.row_dimensions[1].height = 22
        wb.save(EXCEL_FILE)
    else:
        wb = openpyxl.load_workbook(EXCEL_FILE)
        ws = wb.active
    return wb, ws

def get_all_entries(ws):
    entries = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            break
        entries.append(dict(zip(COLUMNS, row)))
    return entries

def get_today_entries(ws):
    today = datetime.now().strftime('%Y-%m-%d')
    return [e for e in get_all_entries(ws) if e['日期'] == today]

def get_recent_entries(ws, n=20):
    entries = get_all_entries(ws)
    return entries[-n:]

def check_suspension(ws):
    """检查是否在休市期（2连亏后休3天）"""
    entries = get_all_entries(ws)
    if len(entries) < 2:
        return False, None
    
    # 找最近2笔未归档的结果
    recent = [e for e in reversed(entries) if e['是否归档'] != '是'][:2]
    if len(recent) < 2:
        return False, None
    
    if recent[0]['结果'] == '亏' and recent[1]['结果'] == '亏':
        # 检查最近一笔亏损的日期
        last_loss_date = datetime.strptime(recent[0]['日期'], '%Y-%m-%d')
        suspension_end = last_loss_date + timedelta(days=3)
        now = datetime.now()
        if now < suspension_end:
            reason = f"2连亏后休市至 {suspension_end.strftime('%Y-%m-%d')}"
            return True, reason
    return False, None

def can_trade(ws):
    """综合检查是否允许交易"""
    now = datetime.now()
    
    # 检查是否在交易时间
    market_open = now.replace(hour=9, minute=30, second=0)
    market_close = now.replace(hour=16, minute=0, second=0)
    
    if now < market_open or now > market_close:
        return False, "非交易时段（9:30-16:00）"
    
    # 检查是否在休市期
    suspended, reason = check_suspension(ws)
    if suspended:
        return False, reason
    
    # 检查今日交易次数
    today_entries = get_today_entries(ws)
    if len(today_entries) >= 3:
        return False, f"今日已交易 {len(today_entries)} 笔（上限3笔）"
    
    return True, f"可交易（今日已 {len(today_entries)}/3）"

def add_entry(ws, wb, ticker, model, entry_price, stop_price, exit_price,
              pnl_amount, pnl_pct, score, notes):
    """添加一条交易记录"""
    entries = get_all_entries(ws)
    seq = (entries[-1]['序号'] + 1) if entries else 1
    
    today = datetime.now()
    date_str = today.strftime('%Y-%m-%d')
    time_str = today.strftime('%H:%M')
    
    result = '盈' if pnl_amount > 0 else ('亏' if pnl_amount < 0 else '平')
    
    row_idx = 2 + len(entries)
    
    values = [seq, date_str, time_str, ticker, model,
              entry_price, stop_price, exit_price,
              round(pnl_amount, 2), f"{pnl_pct:.2f}%", result,
              score, notes, '']
    
    fill = WIN_FILL if result == '盈' else (LOSS_FILL if result == '亏' else EVEN_FILL)
    
    for col_idx, val in enumerate(values, 1):
        cell = ws.cell(row=row_idx, column=col_idx, value=val)
        cell.border = BORDER
        cell.alignment = Alignment(horizontal='center', vertical='center')
        if col_idx == 11:  # 结果列
            cell.fill = fill
            cell.font = Font(bold=True)
    
    wb.save(EXCEL_FILE)
    
    # 检查是否触发休市
    recent = [e for e in get_all_entries(ws) if e['是否归档'] != '是'][:2]
    if len(recent) >= 2 and recent[0]['结果'] == '亏' and recent[1]['结果'] == '亏':
        last_loss = recent[0]['日期']
        suspension_end = (datetime.strptime(last_loss, '%Y-%m-%d') + timedelta(days=3)).strftime('%Y-%m-%d')
        suspended_msg = f"\n⚠️ 触发2连亏规则：休市至 {suspension_end}"
    else:
        suspended_msg = ""
    
    return f"✓ 记录已添加 #{seq} | 结果：{result} | 盈亏：{pnl_amount}" + suspended_msg

def archive_old_entries(ws, wb, months=6):
    """归档超过指定月数的记录"""
    cutoff = (datetime.now() - timedelta(days=months * 30)).strftime('%Y-%m-%d')
    entries = get_all_entries(ws)
    to_archive = [e for e in entries if e['日期'] < cutoff and e['是否归档'] != '是']
    
    if not to_archive:
        return f"无超过 {months} 个月的记录需要归档"
    
    # 创建归档sheet
    archive_name = f"归档_{datetime.now().strftime('%Y%m')}"
    if archive_name in wb.sheetnames:
        ar_ws = wb[archive_name]
    else:
        ar_ws = wb.create_sheet(archive_name)
        for col_idx, (col_name, width) in enumerate(zip(COLUMNS, COL_WIDTHS), 1):
            cell = ar_ws.cell(row=1, column=col_idx, value=col_name)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = BORDER
            ar_ws.column_dimensions[get_column_letter(col_idx)].width = width
    
    # 写入归档数据
    for e in to_archive:
        row_idx = ar_ws.max_row + 1
        for col_idx, col in enumerate(COLUMNS, 1):
            cell = ar_ws.cell(row=row_idx, column=col_idx, value=e[col])
            cell.border = BORDER
            cell.alignment = Alignment(horizontal='center', vertical='center')
    
    # 标记原记录为已归档
    main_entries = get_all_entries(ws)
    for i, e in enumerate(main_entries):
        if e['日期'] < cutoff and e['是否归档'] != '是':
            ws.cell(row=2 + i, column=14, value='是')
    
    wb.save(EXCEL_FILE)
    return f"✓ 已归档 {len(to_archive)} 条记录至 [{archive_name}]"

def print_status(ws):
    can, reason = can_trade(ws)
    print(f"\n{'='*50}")
    print(f"  短线账户交易状态")
    print(f"{'='*50}")
    print(f"  状态：{'✅ 可交易' if can else '❌ 禁止交易'}")
    print(f"  原因：{reason}")
    
    today = get_today_entries(ws)
    print(f"  今日交易：{len(today)}/3 笔")
    if today:
        for e in today:
            print(f"    - {e['标的']} | {e['模型']} | {e['结果']} | {e['盈亏金额']}")
    
    recent = get_recent_entries(ws, 5)
    if recent:
        print(f"  最近5笔：")
        for e in reversed(recent):
            print(f"    {e['日期']} {e['标的']} | {e['结果']} | {e['盈亏金额']}")
    print(f"{'='*50}\n")

def print_log(ws, n=20):
    entries = get_recent_entries(ws, n)
    if not entries:
        print("暂无记录")
        return
    print(f"\n{'='*80}")
    print(f"  最近 {len(entries)} 条交易记录")
    print(f"{'='*80}")
    print(f"{'日':<12} {'标的':<8} {'模型':<6} {'入':<8} {'损':<8} {'出':<8} {'盈亏':<10} {'结果':<4} {'评分'}")
    print(f"{'-'*80}")
    for e in reversed(entries):
        pnl = f"{e['盈亏金额']:>+.2f}"
        pct = e['盈亏比例']
        print(f"{e['日期']:<12} {e['标的']:<8} {e['模型']:<6} "
              f"{e['入场价']:<8} {e['止损价']:<8} {e['出场价']:<8} "
              f"{pnl:<10} {e['结果']:<4} {e['入场评分']}")
    print(f"{'='*80}\n")

def print_stats(ws):
    entries = [e for e in get_all_entries(ws) if e['是否归档'] != '是']
    if not entries:
        print("暂无记录")
        return
    
    wins = [e for e in entries if e['结果'] == '盈']
    losses = [e for e in entries if e['结果'] == '亏']
    evens = [e for e in entries if e['结果'] == '平']
    
    total_pnl = sum(e['盈亏金额'] for e in entries)
    win_rate = len(wins) / len(entries) * 100 if entries else 0
    avg_win = sum(e['盈亏金额'] for e in wins) / len(wins) if wins else 0
    avg_loss = sum(e['盈亏金额'] for e in losses) / len(losses) if losses else 0
    
    print(f"\n{'='*50}")
    print(f"  短线账户统计（未归档）")
    print(f"{'='*50}")
    print(f"  总交易笔数：{len(entries)}")
    print(f"  胜率：{win_rate:.1f}%（{len(wins)}胜 {len(losses)}亏 {len(evens)}平）")
    print(f"  总盈亏：{total_pnl:+.2f}")
    print(f"  平均盈利：{avg_win:+.2f}")
    print(f"  平均亏损：{avg_loss:+.2f}")
    if avg_loss != 0:
        print(f"  盈亏比：{abs(avg_win/avg_loss):.2f}")
    
    # 模型胜率
    models = {}
    for e in entries:
        m = e['模型']
        if m not in models:
            models[m] = {'total': 0, 'wins': 0}
        models[m]['total'] += 1
        if e['结果'] == '盈':
            models[m]['wins'] += 1
    
    print(f"\n  各模型胜率：")
    for m, d in sorted(models.items(), key=lambda x: x[1]['wins']/max(1,x[1]['total']), reverse=True):
        wr = d['wins']/d['total']*100
        print(f"    {m}：{wr:.0f}%（{d['wins']}/{d['total']}）")
    print(f"{'='*50}\n")

if __name__ == '__main__':
    wb, ws = load_wb()
    
    if len(sys.argv) < 2:
        print("用法：")
        print("  python3 短线交易管理器.py --status    查看状态")
        print("  python3 短线交易管理器.py --log       查看最近记录")
        print("  python3 短线交易管理器.py --stats     统计胜率")
        print("  python3 短线交易管理器.py --add       添加记录")
        print("  python3 短线交易管理器.py --archive   归档旧记录")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == '--status':
        print_status(ws)
    elif cmd == '--log':
        print_log(ws)
    elif cmd == '--stats':
        print_stats(ws)
    elif cmd == '--add':
        print("添加交易记录：")
        ticker = input("  标的：").strip()
        model = input("  模型（A/B/C）：").strip()
        entry_price = float(input("  入场价：").strip())
        stop_price = float(input("  止损价：").strip())
        exit_price = float(input("  出场价：").strip())
        pnl_amount = float(input("  盈亏金额：").strip())
        score = int(input("  入场评分（0-10）：").strip())
        notes = input("  复盘备注：").strip()
        pnl_pct = (exit_price - entry_price) / entry_price * 100
        print(add_entry(ws, wb, ticker, model, entry_price, stop_price,
                       exit_price, pnl_amount, pnl_pct, score, notes))
    elif cmd == '--archive':
        print(archive_old_entries(ws, wb))
    else:
        print(f"未知命令：{cmd}")
