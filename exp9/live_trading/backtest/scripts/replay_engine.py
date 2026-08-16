#!/usr/bin/env python3
"""
h3-4-1 实盘回测复现引擎
=============================

功能：
  读取 h3-4-1 JSONL 日志，按真实时间顺序重放所有买卖操作，
  追踪现金余额，生成 Excel 流水账和汇总报告。

日志格式（每行）：
  日期 | 操作类型 | 股票 | 股数 | 操作金额 | 剩余现金

规则：
  - 初始现金：$100,000
  - 买：cash -= 股数 × 成交价（不足则跳过该笔）
  - 卖：cash += 股数 × 成交价
  - 所有操作严格按时间顺序
  - cash >= 0

用法：
    python3 replay_engine.py [--log LOG_FILE] [--cash INITIAL_CASH] [--output OUTPUT_DIR]
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    print("ERROR: openpyxl not installed. Run: pip install openpyxl")
    sys.exit(1)


# ── 颜色常量 ───────────────────────────────────────────
C_HEADER_BG   = "1F4E79"   # 深蓝
C_HEADER_FG   = "FFFFFF"
C_BUY_BG      = "E2EFDA"   # 浅绿
C_SELL_BG     = "FCE4D6"   # 浅红
C_BUY_FG      = "375623"
C_SELL_FG     = "833C00"
C_ALT_ROW     = "F2F2F2"
C_SKIP_BG     = "FFF2CC"   # 跳过（现金不足）
C_SKIP_FG     = "7F6000"


def load_log(log_path: str) -> list:
    """加载 JSONL 日志，返回所有条目列表（保留顺序）"""
    entries = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


def replay_cash_journal(entries: list, initial_cash: float = 100_000.0):
    """
    重放所有操作，生成现金流水账

    Returns:
        journal: list[dict]  — 每行一条操作记录
        summary: dict          — 汇总指标
    """
    CASH = initial_cash
    journal = []
    skipped = []

    # ── 重建完整交易链 ──────────────────────────────────
    # 问题：tid 被多只股票共用（tid=0 的 lot2_sell 是孤儿）
    # 解决：以 (ticker, entry_date) 为键组织交易链，只保留有买入的交易
    ticker_entry_map = {}
    for e in entries:
        key = (e.get("ticker", "?"), e.get("entry_date", ""))
        if key not in ticker_entry_map:
            ticker_entry_map[key] = []
        ticker_entry_map[key].append(e)

    # 验证每组是否有有效的买入
    valid_events = []
    for key, legs in ticker_entry_map.items():
        has_buy = any(e.get("leg") in ("lot1_buy", "lot2_buy") for e in legs)
        if has_buy:
            valid_events.extend(legs)

    # 丢弃孤儿 lot2_sell（无对应买入的）
    orphan_count = len(entries) - len(valid_events)
    if orphan_count > 0:
        print(f"  ⚠️ 丢弃 {orphan_count} 条孤儿事件（tid=0 重复使用）")

    # ── 按时间排序所有有效事件 ────────────────────────────────
    order = {"lot1_buy": 0, "lot2_buy": 1, "lot1_sell": 2, "lot2_sell": 3}

    def sort_key(e):
        d = e.get("exit_date") or e.get("entry_date") or ""
        return (d, order.get(e.get("leg", ""), 99))

    all_events = sorted(valid_events, key=sort_key)

    # ── 重放 ────────────────────────────────────────────
    for e in all_events:
        leg       = e.get("leg", "")
        ticker    = e.get("ticker", "?")
        date      = e.get("exit_date") or e.get("entry_date") or "?"
        shares    = e.get("shares", 0)
        price     = e.get("exit_price") or e.get("entry_price", 0)
        amount    = round(shares * price, 2)

        if leg in ("lot1_buy", "lot2_buy"):
            # 买入：检查现金是否足够
            if CASH < amount:
                journal.append({
                    "日期": date,
                    "操作类型": "跳过（现金不足）",
                    "股票": ticker,
                    "股数": shares,
                    "操作金额": -amount,
                    "剩余现金": round(CASH, 2),
                    "交易ID": e.get("trade_id"),
                    "leg": leg,
                    "原因": f"现金${CASH:.2f} < 需${amount:.2f}",
                })
                skipped.append(e)
                continue

            CASH -= amount
            journal.append({
                "日期": date,
                "操作类型": "买",
                "股票": ticker,
                "股数": shares,
                "操作金额": -amount,
                "剩余现金": round(CASH, 2),
                "交易ID": e.get("trade_id"),
                "leg": leg,
                "原因": "",
            })

        elif leg in ("lot1_sell", "lot2_sell"):
            # 卖出：现金增加
            # 修复：lot2_sell 的股数和 pnl 按完整仓位记录，需除以 2 还原真实 50% 仓位
            _shares = shares
            _amount = amount
            _pnl = e.get("total_pnl", 0)
            if leg == "lot2_sell":
                # 检查同交易是否有 lot1_sell（lot1 先卖出 50%，lot2 才是剩余 50%）
                key = (ticker, e.get("entry_date", ""))
                if key in ticker_entry_map:
                    has_lot1 = any(ev.get("leg") == "lot1_sell"
                                   for ev in ticker_entry_map[key])
                    if has_lot1:
                        _shares = round(shares / 2)
                        _amount = round(_shares * price, 2)
                        _pnl    = round(_pnl / 2, 2)

            CASH += _amount
            journal.append({
                "日期": date,
                "操作类型": "卖",
                "股票": ticker,
                "股数": _shares,
                "操作金额": +_amount,
                "剩余现金": round(CASH, 2),
                "交易ID": e.get("trade_id"),
                "leg": leg,
                "原因": e.get("exit_reason", ""),
            })

    # ── 汇总 ────────────────────────────────────────────
    buys  = [r for r in journal if r["操作类型"] == "买"]
    sells = [r for r in journal if r["操作类型"] == "卖"]
    skip  = [r for r in journal if r["操作类型"] == "跳过（现金不足）"]

    # 胜率统计：每笔完整交易（lot2_sell）的 total_pnl 即为该笔交易的净利润
    trade_pnl_map = {}
    for e in all_events:
        if e.get("leg") == "lot2_sell":
            tid = e.get("trade_id")
            trade_pnl_map[tid] = e.get("total_pnl", 0)  # 已含 lot1 贡献

    win_trades   = sum(1 for v in trade_pnl_map.values() if v > 0)
    loss_trades  = sum(1 for v in trade_pnl_map.values() if v <= 0)
    total_trades = win_trades + loss_trades

    summary = {
        "初始现金": initial_cash,
        "最终现金": round(CASH, 2),
        "总收益率": f"{(CASH/initial_cash - 1)*100:+.1f}%",
        "买操作次数": len(buys),
        "卖操作次数": len(sells),
        "跳过（现金不足）": len(skip),
        "盈利交易": win_trades,
        "亏损交易": loss_trades,
        "胜率": f"{win_trades/total_trades*100:.0f}%" if total_trades > 0 else "N/A",
        "skipped_entries": skipped,
    }
    return journal, summary


def write_excel(journal: list, summary: dict, output_path: Path):
    """将流水账写入 Excel 文件（格式化）"""
    wb = openpyxl.Workbook()

    # ── Sheet 1: 流水账 ──────────────────────────────────
    ws = wb.active
    ws.title = "现金流水账"

    headers = ["日期", "操作类型", "股票", "股数", "操作金额($)", "剩余现金($)", "交易ID", "说明"]
    col_widths = [14, 12, 10, 8, 14, 14, 10, 40]

    # 样式
    hdr_font  = Font(name="Calibri", bold=True, color=C_HEADER_FG, size=11)
    hdr_fill  = PatternFill("solid", fgColor=C_HEADER_BG)
    hdr_align = Alignment(horizontal="center", vertical="center")
    buy_fill  = PatternFill("solid", fgColor=C_BUY_BG)
    sell_fill = PatternFill("solid", fgColor=C_SELL_BG)
    skip_fill = PatternFill("solid", fgColor=C_SKIP_BG)
    alt_fill  = PatternFill("solid", fgColor=C_ALT_ROW)
    thin       = Side(style="thin", color="CCCCCC")
    border     = Border(left=thin, right=thin, top=thin, bottom=thin)

    # 表头
    for col, (h, w) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font      = hdr_font
        cell.fill      = hdr_fill
        cell.alignment = hdr_align
        cell.border    = border
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.row_dimensions[1].height = 22

    # 数据行
    for row_idx, r in enumerate(journal, 2):
        op_type = r["操作类型"]

        if op_type == "买":
            row_fill = buy_fill
            amt_color = C_BUY_FG
        elif op_type == "卖":
            row_fill = sell_fill
            amt_color = C_SELL_FG
        else:  # 跳过
            row_fill = skip_fill
            amt_color = C_SKIP_FG

        # 斑马纹
        if row_idx % 2 == 0 and op_type not in ("买", "卖"):
            row_fill = alt_fill

        row_data = [
            r["日期"],
            op_type,
            r["股票"],
            r["股数"],
            r["操作金额"],
            r["剩余现金"],
            r["交易ID"],
            r.get("原因", "") or r.get("说明", ""),
        ]
        for col, val in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col, value=val)
            cell.fill   = row_fill
            cell.border = border
            if col in (5, 6):  # 金额列
                cell.number_format = '#,##0.00'
                if col == 5:
                    cell.font = Font(name="Calibri", color=amt_color,
                                    bold=(op_type in ("买", "卖", "跳过（现金不足）")))
            elif col == 3:  # 股票代码
                cell.font = Font(name="Calibri", bold=True)
            else:
                cell.font = Font(name="Calibri")
            cell.alignment = Alignment(horizontal="center" if col != 8 else "left",
                                       vertical="center")

    # ── Sheet 2: 汇总 ──────────────────────────────────────
    ws2 = wb.create_sheet("回测汇总")
    ws2.column_dimensions["A"].width = 28
    ws2.column_dimensions["B"].width = 20

    summary_rows = [
        ("═══════════", "═══════════════"),
        ("  h3-4-1 实盘回测汇总", ""),
        ("═══════════", "═══════════════"),
        ("初始现金", f"${summary['初始现金']:,.2f}"),
        ("最终现金", f"${summary['最终现金']:,.2f}"),
        ("总收益率", summary["总收益率"]),
        ("买操作次数", str(summary["买操作次数"])),
        ("卖操作次数", str(summary["卖操作次数"])),
        ("跳过（现金不足）", str(summary["跳过（现金不足）"])),
        ("盈利交易", str(summary["盈利交易"])),
        ("亏损交易", str(summary["亏损交易"])),
        ("胜率", summary["胜率"]),
        ("═══════════", "═══════════════"),
        ("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("引擎版本", "h3-4-1"),
        ("═══════════", "═══════════════"),
    ]

    for row_idx, (k, v) in enumerate(summary_rows, 1):
        for col, val in enumerate([k, v], 1):
            cell = ws2.cell(row=row_idx, column=col, value=val)
            if "═" in k:
                cell.font = Font(name="Calibri", bold=True, size=12,
                                 color=C_HEADER_BG)
            else:
                cell.font = Font(name="Calibri", bold=(col == 1), size=11)
            cell.alignment = Alignment(horizontal="left", vertical="center")
            ws2.row_dimensions[row_idx].height = 18

    wb.save(output_path)
    print(f"✅ Excel 已生成: {output_path}")


def print_summary(journal: list, summary: dict):
    """打印汇总到终端"""
    CASH = summary["初始现金"]
    print()
    print("=" * 52)
    print("  h3-4-1 实盘回测汇总")
    print("=" * 52)
    print(f"  初始现金:   ${summary['初始现金']:>12,.2f}")
    print(f"  最终现金:   ${summary['最终现金']:>12,.2f}")
    print(f"  总收益率:   {summary['总收益率']:>12}")
    print("-" * 52)
    print(f"  买操作:    {summary['买操作次数']:>12} 次")
    print(f"  卖操作:    {summary['卖操作次数']:>12} 次")
    print(f"  跳过（现金不足）: {summary['跳过（现金不足）']:>6} 次")
    print(f"  盈利交易:  {summary['盈利交易']:>12} 笔")
    print(f"  亏损交易:  {summary['亏损交易']:>12} 笔")
    print(f"  胜率:      {summary['胜率']:>12}")
    print("=" * 52)
    if summary["skipped_entries"]:
        print(f"\n  ⚠️  现金不足跳过的操作: {len(summary['skipped_entries'])} 笔")
        for e in summary["skipped_entries"][:3]:
            print(f"     {e.get('exit_date') or e.get('entry_date')} "
                  f"{e.get('ticker')} 需${e.get('shares',0)*e.get('entry_price',0):.2f}")
    print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="h3-4-1 实盘回测复现引擎")
    ap.add_argument(
        "--log", "-l",
        default="/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/live_trading/htrade/logs/trades_h3_4_1_20260602_210100.jsonl",
        help="JSONL 日志路径",
    )
    ap.add_argument(
        "--cash", "-c",
        type=float,
        default=100_000.0,
        help="初始现金（默认 $100,000）",
    )
    ap.add_argument(
        "--output", "-o",
        default=None,
        help="Excel 输出路径（默认与日志同名 .xlsx）",
    )
    args = ap.parse_args()

    log_path = Path(args.log)
    if not log_path.exists():
        print(f"ERROR: 日志文件不存在: {log_path}")
        sys.exit(1)

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = log_path.with_suffix(".xlsx")

    print(f"加载日志: {log_path}")
    entries = load_log(str(log_path))
    print(f"共 {len(entries)} 条记录")

    journal, summary = replay_cash_journal(entries, initial_cash=args.cash)
    print_summary(journal, summary)
    write_excel(journal, summary, out_path)

    # 同时打印完整流水账
    print("\n前 20 条操作记录:")
    print(f"{'日期':<12} {'类型':<6} {'股票':<8} {'股数':>6} {'金额':>10} {'余额':>12}")
    print("-" * 62)
    for r in journal[:20]:
        print(f"{r['日期']:<12} {r['操作类型']:<6} {r['股票']:<8} "
              f"{r['股数']:>6} {r['操作金额']:>+10.2f} {r['剩余现金']:>+12.2f}")
    if len(journal) > 20:
        print(f"  ... 共 {len(journal)} 条记录")
