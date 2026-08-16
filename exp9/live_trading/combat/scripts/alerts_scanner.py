#!/usr/bin/env python3
"""
实战 Alerts Scanner — 基于 h3-4-1 最优引擎
=============================================

功能：
1. 扫描全市场 → 发现立即买入机会（STAGE_4, action=NOW）
2. 扫描全市场 → 发现即将买入机会（STAGE_3），给出进场条件
3. 监控持仓（positions_live.json）→ 提示卖出机会（止损/止盈/保本）

用法：
    # 扫描全市场（不加载持仓）
    python3 alerts_scanner.py

    # 扫描 + 输出持仓预警
    python3 alerts_scanner.py --positions positions_live.json

    # 仅扫描指定股票
    python3 alerts_scanner.py --tickers AAPL MSFT GOOGL

    # 生成 HTML 报告
    python3 alerts_scanner.py --html

    # 输出所有信号的股票（不过滤）
    python3 alerts_scanner.py --show-all
"""

import json, sys, argparse
from pathlib import Path
from datetime import datetime, date
from collections import defaultdict
import warnings
import pytz
warnings.filterwarnings('ignore')

# ── 路径配置 ───────────────────────────────────────────────────────
# engine_interface.py 在 live_trading/engine/，从 combat/ 往上级找到 live_trading/
BASE = Path(__file__).resolve().parent.parent.parent.parent
# engine_interface.py 在 live_trading/engine/，BASE 是 exp9/
sys.path.insert(0, str(BASE / 'live_trading' / 'engine'))

from engine_interface import (
    evaluate_entry, evaluate_exit,
    load_daily_bars, load_h1_bars, load_spy_bars,
    find_h1_entry_idx, entry_params_from_daily,
)

POOL_PATH  = BASE / "TradingAgents" / "fintech" / "stock_pool.json"
KLINES_DIR = BASE / "TradingAgents" / "中间过程" / "klines"


# ═══════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════







def load_positions(path):
    """加载持仓文件"""
    if not Path(path).exists():
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        raw = data.get('positions', data) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        # 统一字段名：cost_basis→entry_price, qty→shares
        normalized = []
        for p in (raw if isinstance(raw, list) else []):
            p = dict(p)
            if 'entry_price' not in p and 'cost_basis' in p:
                p['entry_price'] = p['cost_basis']
            if 'shares' not in p and 'qty' in p:
                p['shares'] = p['qty']
            normalized.append(p)
        return normalized
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════
# 信号扫描
# ═══════════════════════════════════════════════════════════════════

def scan_ticker(ticker, daily_bars, spy_bars, h1_bars):
    """对单只股票执行扫描，委托给 engine_interface.evaluate_entry()"""
    sig = evaluate_entry(ticker, daily_bars, spy_bars, h1_bars)
    return {
        'ticker': ticker,
        'stage': sig.get('stage'),
        'action': sig.get('action'),
        'grade': sig.get('grade'),
        'entry_price': sig.get('entry'),
        'stop_loss': sig.get('stop'),
        'target': sig.get('target'),
        'rr_ratio': sig.get('rr'),
        'pullback_tier': sig.get('pullback_tier', 0),
        'l1_regime': sig.get('l1_regime', 'UNKNOWN'),
        'l3_confirm': sig.get('l3_confirm', ''),
        'l4_confirm': sig.get('l4_confirm', ''),
        'l5_confirm': '',
        'volume_confirm': sig.get('volume_confirm', False),
        'last_price': sig.get('last_price'),
        'last_bar_time': sig.get('last_bar_time'),
        'data_fresh': sig.get('data_fresh', True),
        'error': sig.get('error'),
    }
def filter_buy_now(results, min_rr=1.5):
    """过滤立即买入信号（STAGE_4 + action=NOW + RR >= min_rr）"""
    buys = []
    for r in results:
        if (r['stage'] == 'STAGE_4'
                and r['action'] == 'NOW'
                and r['l1_regime'] == 'BULL'
                and not r.get('error')
                :
            buys.append(r)
    buys.sort(key=lambda x: x['rr_ratio'] or 0, reverse=True)
    return buys


def filter_buy_watch(results, min_rr=1.0):
    """过滤即将买入信号（STAGE_3 + action=WATCH + 良好回踩）"""
    watches = []
    for r in results:
        if (r['stage'] == 'STAGE_3'
                and r['action'] == 'WATCH'
                and r['l1_regime'] == 'BULL'
                and not r.get('error')
                and r['pullback_tier'] >= 1
                :
            watches.append(r)
    watches.sort(key=lambda x: (x['pullback_tier'], x['rr_ratio'] or 0), reverse=True)
    return watches


# ═══════════════════════════════════════════════════════════════════
# 持仓预警（h3-4-1 规则）
# ═══════════════════════════════════════════════════════════════════
def check_position_exit(pos, h1_bars, atr_mult=1.5, atr_trailing_mult=4.0, min_hold=5):
    """
    检查持仓是否触发出场条件，委托给 engine_interface.evaluate_exit()。
    规则完全源自 engine_h3_4_1.py _track_1h，不重写逻辑。
    """
    if not h1_bars:
        return {'action': 'HOLD', 'message': '无1h数据', 'exit_price': None, 'details': {}}

    entry_date = pos.get('entry_date', '')
    entry_h1_idx = find_h1_entry_idx(h1_bars, entry_date)
    current_h1_idx = len(h1_bars) - 1

    sig = evaluate_exit(
        pos, h1_bars, entry_h1_idx, current_h1_idx,
        atr_mult=atr_mult,
        atr_trailing_mult=atr_trailing_mult,
        min_hold=min_hold,
    )

    action_emoji = {
        'HOLD': '➖', 'STOP_LOSS': '🔴',
        'LOT1_HIT': '🟡', 'LOT2_ATR_TRAILING': '🟢',
        'LOT2_BACK_TO_ENTRY': '🟠',
    }
    emoji = action_emoji.get(sig['action'], '❓')

    d = sig.get('details', {})
    cur_close = float(h1_bars[-1]['close'])

    details = {
        'current': cur_close,
        'entry': pos['entry_price'],
        'stop': sig.get('exit_price') or pos.get('lot2_stop', pos.get('stop_loss', 0)),
        'target': pos.get('target', 0),
        'peak': d.get('peak', pos.get('peak_price', pos['entry_price'])),
        'profit_pct': d.get('profit_pct', 0),
        'hold_h1': d.get('hold_h1', 0),
        'lot1_done': pos.get('lot1_done', False),
        'atr_1h': d.get('atr_1h', 0),
        'trailing_stop': d.get('trailing_stop', 0),
    }

    return {
        'action': sig['action'],
        'exit_price': sig.get('exit_price'),
        'message': f'{emoji} {sig["message"]}',
        'details': details,
    }


def estimate_entry_params(daily_bars, entry_price):
    """根据日线估算入场参数（委托给 engine_interface）"""
    return entry_params_from_daily(daily_bars, entry_price)


# ═══════════════════════════════════════════════════════════════════
# 主扫描逻辑
# ═══════════════════════════════════════════════════════════════════

def scan_market(tickers=None, min_rr_buy=1.5, min_rr_watch=1.0,
                lookback_1h=1500, lookback_daily=300,
                show_all=False):
    """
    扫描全市场，返回 (buy_now_list, buy_watch_list, errors)
    """
    print(f"\n{'='*60}")
    print(f"🕐 扫描开始 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # 加载 SPY 日线（市场环境参考）
    spy_bars = load_spy_bars(lookback_daily + 50)
    print(f"📊 SPY 日线: {len(spy_bars)} 根 | 最新 {spy_bars[-1].get('date','?') if spy_bars else '?'}")

    # 加载股票池
    if tickers is None:
        try:
            with open(POOL_PATH) as f:
                pool = json.load(f)
            tickers = [s['code'] for s in pool.get('stocks', [])]
        except Exception as e:
            print(f"⚠️ 无法加载股票池: {e}")
            tickers = []
    else:
        if isinstance(tickers, str):
            tickers = [t.strip() for t in tickers.split(',')]

    print(f"📈 待扫描股票: {len(tickers)} 只")

    results    = []
    errors     = []
    buy_now    = []
    buy_watch  = []

    for i, ticker in enumerate(tickers):
        if ticker in ('SPY', 'SPX', 'QQQ', 'DIA', '^VIX'):
            continue

        if i % 50 == 0 and i > 0:
            print(f"  ... 已扫描 {i}/{len(tickers)} 只")

        daily_bars = load_daily_bars(ticker, lookback_daily)
        h1_bars    = load_h1_bars(ticker, lookback_1h)

        if len(daily_bars) < 60 or len(h1_bars) < 20:
            continue

        r = scan_ticker(ticker, daily_bars, spy_bars, h1_bars)

        if show_all:
            results.append(r)
        elif r.get('error') is None:
            results.append(r)

        if r.get('error'):
            errors.append({'ticker': ticker, 'error': r['error']})

    # 过滤
    buy_now  = filter_buy_now(results, min_rr=min_rr_buy)
    buy_watch = filter_buy_watch(results, min_rr=min_rr_watch)

    print(f"\n✅ 扫描完成 | NOW信号 {len(buy_now)} 只 | WATCH信号 {len(buy_watch)} 只 | 错误 {len(errors)} 只")

    return buy_now, buy_watch, errors


# ═══════════════════════════════════════════════════════════════════
# 输出格式
# ═══════════════════════════════════════════════════════════════════

def print_buy_now(buys):
    """打印立即买入信号"""
    print(f"\n{'='*60}")
    print(f"🟢 立即买入机会（STAGE_4 NOW）共 {len(buys)} 只")
    print(f"{'='*60}")
    if not buys:
        print("  （无）")
        return
    print(f"{'代码':<8} {'现价':>8} {'进场价':>8} {'止损':>8} {'目标':>8} {'RR':>5} {'回踩级':>6} {'评分':<4} {'确认信号'}")
    print(f"{'-'*80}")
    for r in buys:
        tier_emoji = '🔴' if r['pullback_tier'] == 1 else ('🟡' if r['pullback_tier'] == 2 else '⚪')
        l4_confirm = r['l4_confirm'] or ''
        # 截断过长的确认信息
        if len(l4_confirm) > 25:
            l4_confirm = l4_confirm[:22] + '...'
        print(
            f"{r['ticker']:<8} "
            f"{r['last_price']:>8.2f} "
            f"{r['entry_price'] or 0:>8.2f} "
            f"{r['stop_loss'] or 0:>8.2f} "
            f"{r['target'] or 0:>8.2f} "
            f"{r['rr_ratio'] or 0:>5.2f} "
            f"{tier_emoji}{r['pullback_tier']:<4} "
            f"{r['grade']:<4} "
            f"{l4_confirm}"
        )
    print()


def print_buy_watch(watches):
    """打印即将买入信号"""
    print(f"\n{'='*60}")
    print(f"🟡 即将买入机会（STAGE_3 WATCH）共 {len(watches)} 只")
    print(f"{'='*60}")
    if not watches:
        print("  （无）")
        return
    print(f"{'代码':<8} {'现价':>8} {'止损':>8} {'RR':>5} {'回踩级':>6} {'评分':<4} {'回踩确认'}")
    print(f"{'-'*70}")
    for r in watches:
        tier_emoji = '🔴' if r['pullback_tier'] == 1 else ('🟡' if r['pullback_tier'] == 2 else '⚪')
        l3_confirm = r['l3_confirm'] or ''
        if len(l3_confirm) > 30:
            l3_confirm = l3_confirm[:27] + '...'
        print(
            f"{r['ticker']:<8} "
            f"{r['last_price'] or 0:>8.2f} "
            f"{r['stop_loss'] or 0:>8.2f} "
            f"{r['rr_ratio'] or 0:>5.2f} "
            f"{tier_emoji}{r['pullback_tier']:<4} "
            f"{r['grade']:<4} "
            f"{l3_confirm}"
        )
    print()


def build_pos_template(pos, h1_bars, daily_bars):
    """构建持仓模板数据"""
    ticker = pos['ticker']

    # 补充 ATR 信息
    if 'atr' not in pos and daily_bars:
        params = estimate_entry_params(daily_bars, pos['entry_price'])
        pos.setdefault('atr', params['atr'])
        pos.setdefault('stop_loss', params['stop_loss'])
        pos.setdefault('target', params['target'])

    alert = check_position_exit(pos, h1_bars)
    d = alert['details']

    action_map = {
        'HOLD': ('➖', '持有'),
        'STOP_LOSS': ('🔴', '止损出场'),
        'LOT1_HIT': ('🟡', '保本止损'),
        'LOT2_TRAILING': ('🟢', '跟踪止盈'),
        'LOT2_BACK_TO_ENTRY': ('🟠', '保本出场'),
    }
    emoji, action_label = action_map.get(alert['action'], ('❓', '未知'))

    current_price = d.get('current', 0)
    stop_loss = d.get('stop', 0)
    target = d.get('target', 0)
    lot1_done = d.get('lot1_done', False)
    atr_1h = d.get('atr_1h', 0)
    trailing_stop = d.get('trailing_stop', 0)
    peak = d.get('peak', 0)
    profit_pct = d.get('profit_pct', 0)

    # 止盈条件文字
    if alert['action'] == 'LOT1_HIT':
        exit_condition = f"保本止损({stop_loss:.2f}) / ATR跟踪({atr_1h:.4f}×4)"
    elif alert['action'] == 'LOT2_TRAILING':
        exit_condition = f"ATR跟踪触发({trailing_stop:.2f})"
    elif alert['action'] == 'LOT2_BACK_TO_ENTRY':
        exit_condition = f"跌回入场价({stop_loss:.2f})"
    elif alert['action'] == 'STOP_LOSS':
        exit_condition = f"止损触发({stop_loss:.2f})"
    else:
        if lot1_done:
            exit_condition = f"目标{target:.2f} / ATR跟踪({atr_1h:.4f}×4={trailing_stop:.2f})"
        else:
            exit_condition = f"目标 {target:.2f}（{((target - current_price) / current_price * 100):+.1f}%）"

    # 操作建议
    if alert['action'] == 'STOP_LOSS':
        suggestion = f"⚠️ 建议出场: {alert['exit_price']:.2f}"
    elif alert['action'] == 'LOT1_HIT':
        suggestion = f"持有，止损上移至入场价保本"
    elif alert['action'] == 'LOT2_TRAILING':
        suggestion = f"⚠️ 跟踪止盈触发，建议出场: {alert['exit_price']:.2f}"
    elif alert['action'] == 'LOT2_BACK_TO_ENTRY':
        suggestion = f"⚠️ 跌回入场价，建议出场"
    else:
        dist_to_stop = (current_price - stop_loss) / current_price * 100
        if dist_to_stop < 3:
            suggestion = f"⚠️ 距止损仅 {dist_to_stop:.1f}%，密切关注"
        elif profit_pct > 8:
            suggestion = f"浮盈 {profit_pct:.1f}%，注意分批止盈"
        else:
            suggestion = "正常持有"

    return {
        'ticker': ticker,
        'emoji': emoji,
        'action': action_label,
        'current': current_price,
        'entry': pos['entry_price'],
        'stop_loss': stop_loss,
        'target': target,
        'exit_condition': exit_condition,
        'suggestion': suggestion,
        'profit_pct': profit_pct,
        'peak': peak,
        'atr_1h': atr_1h,
        'trailing_stop': trailing_stop,
        'exit_price': alert['exit_price'],
        'alert_action': alert['action'],
    }


def print_position_alerts(positions, lookback_1h=1500):
    """打印持仓预警（模板格式）"""
    print(f"\n{'='*72}")
    print(f"📋 持仓监控（{len(positions)} 只）")
    print(f"{'='*72}")
    if not positions:
        print("  （无持仓）")
        return

    # 表头
    print(f"\n{'股票':<8} {'现价':>8} {'止损':>8} {'目标':>8}   {'止盈条件':<30} 操作建议")
    print(f"{'─'*8} {'─'*8} {'─'*8} {'─'*8}   {'─'*30} {'─'*20}")

    templates = []
    for pos in positions:
        ticker = pos['ticker']
        h1_bars = load_h1_bars(ticker, lookback_1h)
        daily_bars = load_daily_bars(ticker, 300)

        tpl = build_pos_template(pos, h1_bars, daily_bars)
        templates.append(tpl)

        profit_ico = '🟢' if tpl['profit_pct'] > 5 else ('🟡' if tpl['profit_pct'] > 0 else '🔴')
        print(
            f"{tpl['emoji']}{tpl['ticker']:<6} "
            f"{tpl['current']:>8.2f} "
            f"{tpl['stop_loss']:>8.2f} "
            f"{tpl['target']:>8.2f}   "
            f"{tpl['exit_condition']:<30} "
            f"{tpl['suggestion']}"
        )

    print()
    return templates


# ═══════════════════════════════════════════════════════════════════
# HTML 报告
# ═══════════════════════════════════════════════════════════════════

def generate_html_report(buy_now, buy_watch, positions,
                         output_path=None):
    """生成 HTML 报告"""
    now_ts = datetime.now().strftime('%Y-%m-%d %H:%M')

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>实战 Alerts — {now_ts}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #0d1117; color: #e6edf3; padding: 20px; }}
  h1 {{ color: #58a6ff; margin-bottom: 4px; }}
  .timestamp {{ color: #8b949e; font-size: 13px; margin-bottom: 24px; }}
  h2 {{ color: #f0f6fc; border-left: 4px solid; padding-left: 10px;
        margin: 28px 0 14px; font-size: 18px; }}
  h2.red {{ border-color: #f85149; }}
  h2.yellow {{ border-color: #d29922; }}
  h2.green {{ border-color: #3fb950; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 28px; font-size: 14px; }}
  th {{ background: #161b22; color: #8b949e; text-align: left;
        padding: 10px 12px; font-weight: 600; border-bottom: 1px solid #30363d; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #21262d; }}
  tr:hover {{ background: #1c2128; }}
  .grade-a {{ color: #3fb950; font-weight: bold; }}
  .grade-b {{ color: #d29922; }}
  .grade-c {{ color: #f85149; }}
  .rr-high {{ color: #3fb950; font-weight: bold; }}
  .rr-mid  {{ color: #d29922; }}
  .rr-low  {{ color: #8b949e; }}
  .alert-red {{ background: rgba(248,81,73,0.1); }}
  .alert-yellow {{ background: rgba(210,153,34,0.1); }}
  .alert-green {{ background: rgba(63,185,80,0.1); }}
  .exit-price {{ color: #f85149; font-weight: bold; font-size: 15px; }}
  .summary {{ display: flex; gap: 20px; margin-bottom: 28px; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px;
           padding: 16px 24px; flex: 1; }}
  .card-num {{ font-size: 32px; font-weight: bold; }}
  .card-label {{ font-size: 13px; color: #8b949e; margin-top: 4px; }}
  .card.green .card-num {{ color: #3fb950; }}
  .card.yellow .card-num {{ color: #d29922; }}
  .card.red .card-num {{ color: #f85149; }}
  .no-data {{ color: #8b949e; font-style: italic; padding: 20px 0; }}
</style>
</head>
<body>
<h1>📡 实战 Alerts Scanner</h1>
<div class="timestamp">扫描时间: {now_ts} | 数据截至: {
    buy_now[0]['last_bar_time'] if buy_now else 'N/A'
}</div>

<div class="summary">
  <div class="card green">
    <div class="card-num">{len(buy_now)}</div>
    <div class="card-label">🟢 立即买入（STAGE_4 NOW）</div>
  </div>
  <div class="card yellow">
    <div class="card-num">{len(buy_watch)}</div>
    <div class="card-label">🟡 即将买入（STAGE_3 WATCH）</div>
  </div>
  <div class="card">
    <div class="card-num">{len(positions)}</div>
    <div class="card-label">📋 持仓监控</div>
  </div>
</div>

<h2 class="green">🟢 立即买入机会（STAGE_4 NOW）</h2>
"""

    if buy_now:
        html += """<table>
<tr>
  <th>代码</th><th>现价</th><th>进场价</th><th>止损</th><th>目标</th>
  <th>RR</th><th>回踩级</th><th>评分</th><th>1h信号确认</th>
</tr>"""
        for r in buy_now:
            grade_cls = f"grade-{r['grade'].lower()}" if r['grade'] else ''
            rr_cls = 'rr-high' if (r['rr_ratio'] or 0) >= 2.0 else ('rr-mid' if (r['rr_ratio'] or 0) >= 1.5 else 'rr-low')
            l4 = r['l4_confirm'] or ''
            tier_emoji = '🔴' if r['pullback_tier'] == 1 else ('🟡' if r['pullback_tier'] == 2 else '⚪')
            html += f"""<tr>
  <td><strong>{r['ticker']}</strong></td>
  <td>{r['last_price']:.2f}</td>
  <td>{r['entry_price']:.2f}</td>
  <td>{r['stop_loss']:.2f}</td>
  <td>{r['target']:.2f}</td>
  <td class="{rr_cls}">{r['rr_ratio']:.2f}</td>
  <td>{tier_emoji}{r['pullback_tier']}</td>
  <td class="{grade_cls}">{r['grade']}</td>
  <td style="font-size:12px;color:#8b949e">{l4[:60]}</td>
</tr>"""
        html += "</table>"
    else:
        html += "<div class='no-data'>（无信号）</div>"

    html += """
<h2 class="yellow">🟡 即将买入机会（STAGE_3 WATCH）</h2>
"""

    if buy_watch:
        html += """<table>
<tr>
  <th>代码</th><th>现价</th><th>止损（估算）</th><th>RR</th>
  <th>回踩级</th><th>评分</th><th>回踩确认（进场条件）</th>
</tr>"""
        for r in buy_watch:
            tier_emoji = '🔴' if r['pullback_tier'] == 1 else ('🟡' if r['pullback_tier'] == 2 else '⚪')
            rr_cls = 'rr-high' if (r['rr_ratio'] or 0) >= 2.0 else ('rr-mid' if (r['rr_ratio'] or 0) >= 1.0 else 'rr-low')
            l3 = r['l3_confirm'] or ''
            html += f"""<tr>
  <td><strong>{r['ticker']}</strong></td>
  <td>{r['last_price']:.2f}</td>
  <td>{r['stop_loss']:.2f}</td>
  <td class="{rr_cls}">{r['rr_ratio']:.2f}</td>
  <td>{tier_emoji}{r['pullback_tier']}</td>
  <td>{r['grade']}</td>
  <td style="font-size:12px;color:#8b949e">{l3[:70]}</td>
</tr>"""
        html += "</table>"
    else:
        html += "<div class='no-data'>（无信号）</div>"

    # 持仓预警
    html += """
<h2 style="border-color:#58a6ff;color:#f0f6fc">📋 持仓监控</h2>
"""
    if positions:
        html += """<table>
<tr>
  <th>代码</th><th>入场价</th><th>现价</th><th>浮盈%</th>
  <th>状态</th><th>出场建议</th><th>详情</th>
</tr>"""
        for pos in positions:
            ticker = pos['ticker']
            h1_bars = load_h1_bars(ticker, 1500)
            daily_bars = load_daily_bars(ticker, 300)
            if 'atr' not in pos and daily_bars:
                params = estimate_entry_params(daily_bars, pos['entry_price'])
                pos.setdefault('atr', params['atr'])
                pos.setdefault('stop_loss', params['stop_loss'])
                pos.setdefault('target', params['target'])
            alert = check_position_exit(pos, h1_bars)
            d = alert['details']
            action_bg = {
                'HOLD': '',
                'STOP_LOSS': 'alert-red',
                'LOT1_HIT': 'alert-yellow',
                'LOT2_TRAILING': 'alert-green',
                'LOT2_BACK_TO_ENTRY': 'alert-yellow',
            }.get(alert['action'], '')
            profit_pct = d.get('profit_pct', 0)
            profit_cls = 'rr-high' if profit_pct > 5 else ('rr-mid' if profit_pct > 0 else 'rr-low')
            html += f"""<tr class="{action_bg}">
  <td><strong>{ticker}</strong></td>
  <td>{pos['entry_price']:.2f}</td>
  <td>{d.get('current', 0):.2f}</td>
  <td class="{profit_cls}">{profit_pct:+.2f}%</td>
  <td>{alert['message'][:40]}</td>
  <td class="exit-price">{alert['exit_price'] if alert['exit_price'] else '—'}</td>
  <td style="font-size:12px;color:#8b949e">
    峰值 {d.get('peak', 0):.2f} |
    ATR_1h {d.get('atr_1h', 0):.4f} |
    跟踪 {d.get('trailing_stop', 0):.2f}
  </td>
</tr>"""
        html += "</table>"
    else:
        html += "<div class='no-data'>（无持仓）</div>"

    html += f"""
<hr style="border:none;border-top:1px solid #30363d;margin:40px 0">
<div style="color:#8b949e;font-size:12px">
  引擎: h3-4-1 | BuyFilterEngine v2 | 数据源: Yahoo Finance 1h K线<br>
  RR 阈值: NOW≥1.5 / WATCH≥1.0 | 回踩级: 🔴1=EMA50% / 🟡2=趋势线 / ⚪3=宽通道<br>
  卖出规则: 止损→LOT1触达→保本止损→ATR跟踪止盈(4×ATR_1h) 或 跌回入场价
</div>
</body>
</html>"""

    if output_path is None:
        output_path = Path(__file__).resolve().parent / f"alerts_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"\n📄 HTML 报告已生成: {output_path}")
    return output_path


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='实战 Alerts Scanner')
    parser.add_argument('--tickers', default=None,
                        help='逗号分隔的股票代码，如 AAPL,MSFT,GOOGL')
    parser.add_argument('--positions', default=None,
                        help='持仓文件路径（JSON数组）')
    parser.add_argument('--html', action='store_true',
                        help='生成 HTML 报告')
    parser.add_argument('--show-all', action='store_true',
                        help='显示所有扫描结果（不过滤）')
    parser.add_argument('--min-rr-buy', type=float, default=1.5,
                        help='立即买入 RR 最低阈值（默认 1.5）')
    parser.add_argument('--min-rr-watch', type=float, default=1.0,
                        help='即将买入 RR 最低阈值（默认 1.0）')
    parser.add_argument('--output', default=None,
                        help='HTML 报告输出路径')
    parser.add_argument('--json', action='store_true',
                        help='输出 JSON 格式（供系统集成使用）')
    args = parser.parse_args()

    # JSON 模式：立即重定向所有文本输出到 /dev/null
    _null = None
    if args.json:
        import os
        _null = open(os.devnull, 'w')
        _orig_stdout = sys.stdout
        sys.stdout = _null

    tickers = None
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(',')]

    positions = []
    if args.positions:
        positions = load_positions(args.positions)
        if positions:
            print(f"📋 已加载持仓: {len(positions)} 只")
            for p in positions:
                print(f"   {p['ticker']}: 入场 {p.get('entry_price', p.get('cost_basis','?'))} | {p.get('shares', p.get('qty',0))}股")

    buy_now, buy_watch, errors = scan_market(
        tickers=tickers,
        min_rr_buy=args.min_rr_buy,
        min_rr_watch=args.min_rr_watch,
        show_all=args.show_all,
    )

    print_buy_now(buy_now)
    print_buy_watch(buy_watch)

    pos_templates = []
    if positions:
        pos_templates = print_position_alerts(positions)

    if args.json:
        sys.stdout = _orig_stdout
        _null.close()
        import json as _json
        result = {
            'time': datetime.now().strftime('%H:%M ET'),
            'market_date': datetime.now(pytz.timezone('America/New_York')).strftime('%Y-%m-%d'),
            'now_signals': len(buy_now),
            'watch_signals': len(buy_watch),
            'errors': len(errors),
            'positions': pos_templates,
        }
        print(_json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.show_all and errors:
        print(f"\n{'='*60}")
        print(f"⚠️ 扫描错误 ({len(errors)} 只)")
        for e in errors[:10]:
            print(f"   {e['ticker']}: {e['error']}")
        if len(errors) > 10:
            print(f"   ... 还有 {len(errors) - 10} 只")

    if args.html:
        out = generate_html_report(buy_now, buy_watch, positions,
                                   output_path=args.output)
        print(f"\n🌐 报告: file://{out}")

    # 关键信息摘要（方便复制）
    if buy_now:
        print(f"\n{'='*60}")
        print(f"📝 立即买入 TOP 3（复制参考）")
        print(f"{'='*60}")
        for r in buy_now[:3]:
            print(f"  {r['ticker']:<8} | 入场 ${r['entry_price']:.2f} | 止损 ${r['stop_loss']:.2f} | "
                  f"目标 ${r['target']:.2f} | RR={r['rr_ratio']:.2f} | {r['l4_confirm'][:40]}")


if __name__ == '__main__':
    main()
