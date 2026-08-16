#!/usr/bin/env python3
"""
SPY v3信号体系回测
==================

策略规则（基于 spy_swing_analysis_v3.html 的信号）:
  BUY  信号 → 全仓买入
  BOTTOM信号 → 全仓买入
  TOP  信号 → 全仓卖出
  SELL 信号 → 全仓卖出
  GD   信号 → 全仓卖出（死叉）
  STOP 信号 → 全仓卖出（止损/死叉）

执行：信号日收盘计算，下一交易日开盘买入/卖出（更现实）
"""

import json
from pathlib import Path

KLINES_DIR = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines')
SIGNALS_FP = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spy_signals_v3.json')
OUTPUT_HTML = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spy_v3_backtest.html')


# ═══════════════════════════════════════
#  数据加载
# ═══════════════════════════════════════

def load_data():
    with open(KLINES_DIR / 'SPY_1d.json') as f:
        bars = json.load(f)['data']
    return bars


def load_signals():
    with open(SIGNALS_FP) as f:
        d = json.load(f)
    return d['signals']


# ═══════════════════════════════════════
#  回测
# ═══════════════════════════════════════

def backtest_v3(bars, signals, initial=10_000.0):
    """
    按 v3 信号执行:
      - BUY/BOTTOM → 买入
      - TOP/SELL/STOP/GD → 卖出
    执行价格: 下一交易日开盘价（信号日收盘后第二天开盘操作）
    """
    # 建立 date → bar 映射（用于找下一日开盘价）
    date_to_bar = {b['date']: b for b in bars}
    dates = [b['date'] for b in bars]

    # 建立信号集合（当日有某类型信号）
    signal_set = {}  # date → list of types
    for s in signals:
        d = s['date']
        if d not in signal_set:
            signal_set[d] = []
        signal_set[d].append(s['type'])

    cash    = initial
    shares  = 0.0
    in_pos  = False
    entry_price = 0.0

    equity_curve = []
    trades = []

    BUY_TYPES  = {'BUY', 'BOTTOM'}
    SELL_TYPES = {'TOP', 'SELL', 'STOP', 'GD'}

    for i, bar in enumerate(bars):
        date    = bar['date']
        close   = bar['close']
        cur_sig = set(signal_set.get(date, []))

        # ── 执行信号 ──
        # 逻辑：
        # 1. 如果有 SELL 信号且在持仓 → 卖出（下一日开盘执行）
        # 2. 如果有 BUY 信号且不在持仓 → 买入（下一日开盘执行）
        # 3. 如果同时有 BUY 和 SELL → 先卖后买（下一日）

        if i < len(bars) - 1:
            next_open = bars[i + 1]['open']
        else:
            next_open = close

        sold_today = False
        bought_today = False

        # 优先处理卖出信号
        if cur_sig & SELL_TYPES and in_pos:
            # 卖出
            cash = shares * next_open
            pnl_pct = (next_open - entry_price) / entry_price
            trades.append({
                'date':   dates[i + 1] if i + 1 < len(dates) else date,
                'action': 'SELL',
                'price':  next_open,
                'shares': shares,
                'equity': cash,
                'pnl_pct': pnl_pct,
            })
            shares = 0.0
            in_pos = False
            sold_today = True

        # 处理买入信号
        if (cur_sig & BUY_TYPES) and not in_pos:
            shares = cash / next_open
            entry_price = next_open
            cash = 0.0
            in_pos = True
            trades.append({
                'date':   dates[i + 1] if i + 1 < len(dates) else date,
                'action': 'BUY',
                'price':  next_open,
                'shares': shares,
            })
            bought_today = True

        # 权益记录
        pos_value = shares * close
        equity = cash + pos_value
        equity_curve.append({
            'date':   date,
            'price':  close,
            'equity': equity,
            'in_pos': in_pos,
        })

    # 最后一天若仍持仓，按最后收盘价结算
    if in_pos and bars:
        final_price = bars[-1]['close']
        equity_curve[-1]['equity'] = shares * final_price
        equity_curve[-1]['close']   = final_price

    return equity_curve, trades


def buy_and_hold(bars, initial=10_000.0):
    """基准：第一天开盘价买入，持有到最后"""
    if not bars:
        return [], []
    first_open = bars[0]['open']
    shares = initial / first_open
    curve = []
    for b in bars:
        curve.append({
            'date':   b['date'],
            'price':  b['close'],
            'equity': shares * b['close'],
            'in_pos': True,
        })
    return curve, [{'date': bars[0]['date'], 'action': 'BUY', 'price': first_open, 'shares': shares}]


# ═══════════════════════════════════════
#  绩效计算
# ═══════════════════════════════════════

def calc_stats(curve, trades, initial):
    if not curve:
        return {}
    final_eq = curve[-1]['equity']
    n_days   = len(curve)
    n_years  = n_days / 252

    total_ret = (final_eq - initial) / initial
    cagr      = (final_eq / initial) ** (1 / n_years) - 1 if n_years > 0 else 0

    # 最大回撤
    peak = initial
    max_dd = 0.0
    for row in curve:
        eq = row['equity']
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > max_dd:
            max_dd = dd

    # 完整波段
    win_trades, loss_trades = [], []
    buy_trade = None
    for t in trades:
        if t['action'] == 'BUY':
            buy_trade = t
        elif t['action'] == 'SELL' and buy_trade:
            pnl_pct = t.get('pnl_pct', (t['price'] - buy_trade['price']) / buy_trade['price'])
            if pnl_pct > 0:
                win_trades.append(pnl_pct)
            else:
                loss_trades.append(pnl_pct)
            buy_trade = None

    n_win  = len(win_trades)
    n_loss = len(loss_trades)
    n_total = n_win + n_loss
    win_rate = n_win / n_total if n_total > 0 else 0
    avg_win  = sum(win_trades) / n_win  if n_win  > 0 else 0
    avg_loss = sum(loss_trades) / n_loss if n_loss > 0 else 0
    pf       = abs(sum(win_trades) / sum(loss_trades)) if loss_trades else float('inf')

    return {
        'initial':      initial,
        'final':        final_eq,
        'total_return': total_ret,
        'cagr':         cagr,
        'max_drawdown': max_dd,
        'n_total_trades': len(trades),
        'n_round_trips': n_total,
        'win_rate':     win_rate,
        'avg_win':      avg_win,
        'avg_loss':     avg_loss,
        'profit_factor': pf,
        'equity_curve': curve,
    }


# ═══════════════════════════════════════
#  报告
# ═══════════════════════════════════════

def fmt_pct(v):  return f"{v*100:+.2f}%"
def fmt_money(v):return f"${v:,.2f}"

def print_report(v3, bh, excess):
    print(f"\n{'='*65}")
    print(f"  SPY v3信号体系回测 vs 买入持有")
    print(f"{'='*65}")
    print(f"\n  {'指标':<18} {'v3策略':>14} {'B&H':>14}")
    print(f"  {'-'*18} {'-'*14} {'-'*14}")
    print(f"  {'最终权益':<18} {fmt_money(v3['final']):>14} {fmt_money(bh['final']):>14}")
    print(f"  {'总收益率':<18} {fmt_pct(v3['total_return']):>14} {fmt_pct(bh['total_return']):>14}")
    print(f"  {'年化(CAGR)':<18} {fmt_pct(v3['cagr']):>14} {fmt_pct(bh['cagr']):>14}")
    print(f"  {'最大回撤':<18} {fmt_pct(v3['max_drawdown']):>14} {fmt_pct(bh['max_drawdown']):>14}")
    print(f"  {'交易次数':<18} {v3['n_total_trades']:>14} {'N/A':>14}")
    print(f"  {'完整波段':<18} {v3['n_round_trips']:>14} {'N/A':>14}")
    print(f"  {'胜率':<18} {fmt_pct(v3['win_rate']):>14} {'N/A':>14}")
    print(f"  {'盈亏比':<18} {v3['profit_factor']:>14.2f} {'N/A':>14}")
    print(f"\n  盈利波段平均: {fmt_pct(v3['avg_win'])}")
    print(f"  亏损波段平均: {fmt_pct(v3['avg_loss'])}")

    winner = "✅ v3策略跑赢" if excess > 0 else "❌ B&H跑赢"
    print(f"\n  超额收益: {fmt_pct(excess)}  ({winner})")


# ═══════════════════════════════════════
#  HTML
# ═══════════════════════════════════════

def build_html(v3, bh, trades, signals, bars):
    def eq_series(curve):
        return json.dumps([{'time': r['date'], 'value': r['equity']} for r in curve])

    # SPY 价格序列
    candles = json.dumps([{'time': b['date'], 'open': b['open'], 'high': b['high'],
                           'low': b['low'], 'close': b['close']} for b in bars])

    # price markers
    sig_map = {}
    for s in signals:
        sig_map.setdefault(s['date'], []).append(s['type'])

    markers = []
    for s in signals:
        t = s['type']
        cmap = {'TOP':'#FF1744','BOTTOM':'#00E676','BUY':'#00C853',
                'SELL':'#FF9100','STOP':'#FF6D00','GC':'#00B0FF','GD':'#FF1744'}
        markers.append({
            'time':     s['date'],
            'position': 'belowBar' if t in ('BUY','BOTTOM','GC') else 'aboveBar',
            'color':    cmap.get(t, '#FFD700'),
            'shape':    'arrowUp' if t in ('BUY','BOTTOM','GC') else 'arrowDown',
            'text':     s['label'][:22],
        })

    lc_path = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/dtrade/lightweight-charts.js')
    lc_lib  = open(lc_path).read() if lc_path.exists() else ''

    v3_final = v3['final']
    bh_final = bh['final']
    win_v3   = v3_final > bh_final

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>v3信号体系回测 vs B&H</title>
<script>{lc_lib}</script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}
.wrap{{padding:16px;max-width:1400px;margin:0 auto}}
.title{{font-size:22px;font-weight:700;color:#58a6ff;margin-bottom:4px}}
.sub{{color:#8b949e;font-size:12px}}
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin:16px 0}}
.kpi{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px}}
.kpi .l{{color:#8b949e;font-size:11px;text-transform:uppercase;margin-bottom:6px}}
.kpi .v{{font-size:22px;font-weight:700}}
.kpi .v.g{{color:#3fb950}}.kpi .v.r{{color:#f85149}}
.kpi .s{{color:#8b949e;font-size:11px;margin-top:3px}}
.chart-box{{background:#161b22;border:1px solid #30363d;border-radius:8px;margin-bottom:14px;overflow:hidden}}
.ch-hdr{{padding:10px 14px;border-bottom:1px solid #30363d;font-size:13px;font-weight:600}}
.ch-note{{padding:6px 14px 4px;font-size:11px;color:#8b949e;background:#0d1117}}
.legend{{display:flex;gap:14px;padding:8px 14px;background:#0d1117;border-top:1px solid #21262d;font-size:11px;color:#8b949e}}
.legend span{{display:flex;align-items:center;gap:5px}}
.dot{{width:10px;height:10px;border-radius:50%;display:inline-block}}
</style>
</head>
<body>
<div class="wrap">
  <div class="title">SPY v3信号体系回测 vs 买入持有</div>
  <div class="sub">{bars[0]['date']} ~ {bars[-1]['date']} · 初始本金 $10,000 · {len(bars)}交易日</div>

  <div class="kpi-grid">
    <div class="kpi">
      <div class="l">v3策略最终权益</div>
      <div class="v {'g' if v3_final>10000 else 'r'}">{fmt_money(v3_final)}</div>
      <div class="s">{fmt_pct(v3['total_return'])} ({v3['cagr']*100:+.2f}%/年)</div>
    </div>
    <div class="kpi">
      <div class="l">B&amp;H最终权益</div>
      <div class="v {'g' if bh_final>10000 else 'r'}">{fmt_money(bh_final)}</div>
      <div class="s">{fmt_pct(bh['total_return'])} ({bh['cagr']*100:+.2f}%/年)</div>
    </div>
    <div class="kpi">
      <div class="l">超额收益</div>
      <div class="v {'g' if win_v3 else 'r'}">{fmt_pct(v3['total_return']-bh['total_return'])}</div>
      <div class="s">{'✅ v3跑赢' if win_v3 else '❌ B&H跑赢'}</div>
    </div>
    <div class="kpi">
      <div class="l">v3最大回撤</div>
      <div class="v r">{fmt_pct(v3['max_drawdown'])}</div>
      <div class="s">B&H {fmt_pct(bh['max_drawdown'])}</div>
    </div>
    <div class="kpi">
      <div class="l">v3交易次数</div>
      <div class="v">{v3['n_total_trades']}</div>
      <div class="s">胜率 {v3['win_rate']*100:.0f}% · 盈亏比 {v3['profit_factor']:.2f}</div>
    </div>
    <div class="kpi">
      <div class="l">v3完整波段</div>
      <div class="v">{v3['n_round_trips']}</div>
      <div class="s">均盈 {fmt_pct(v3['avg_win'])} · 均亏 {fmt_pct(v3['avg_loss'])}</div>
    </div>
  </div>

  <div class="chart-box">
    <div class="ch-hdr">📈 权益曲线对比</div>
    <div id="c1" style="height:280px"></div>
  </div>
  <div class="chart-box">
    <div class="ch-hdr">💹 SPY 价格 + v3信号标注</div>
    <div id="c2" style="height:280px"></div>
    <div class="legend">
      <span><span class="dot" style="background:#00C853"></span> 🟢 买入</span>
      <span><span class="dot" style="background:#FF1744"></span> 🔴 卖出/止损</span>
      <span><span class="dot" style="background:#00E676"></span> 🟢🕳️ 恐慌底买入</span>
      <span><span class="dot" style="background:#FF9100"></span> ⚠️ 卖出信号</span>
    </div>
  </div>
</div>

<script>
{lc_lib}

const v3_eq = {eq_series(v3['equity_curve'])};
const bh_eq = {eq_series(bh['equity_curve'])};
const candles = {candles};
const markers = {json.dumps(markers)};

// 权益曲线
const ch1 = LightweightCharts.createChart(document.getElementById('c1'), {{
  layout: {{background: {{color: '#161b22'}}, textColor: '#e6edf3'}},
  grid: {{vertLines: {{color: '#21262d'}}, horzLines: {{color: '#21262d'}}}},
  width: document.getElementById('c1').offsetWidth,
  height: 280,
  timeScale: {{timeVisible: true, secondsVisible: false, borderColor: '#30363d'}},
  rightPrice: {{borderColor: '#30363d'}},
}});
ch1.addLineSeries({{color: '#FFD700', lineWidth: 2, title: 'v3策略'}}).setData(v3_eq.map(d=>({{time:d.time,value:d.value}})));
ch1.addLineSeries({{color: '#58a6ff', lineWidth: 1, title: 'B&amp;H'}}).setData(bh_eq.map(d=>({{time:d.time,value:d.value}})));
ch1.timeScale().fitContent();
window.addEventListener('resize',()=>ch1.resize(document.getElementById('c1').offsetWidth,280));

// SPY 价格
const ch2 = LightweightCharts.createChart(document.getElementById('c2'), {{
  layout: {{background: {{color: '#161b22'}}, textColor: '#e6edf3'}},
  grid: {{vertLines: {{color: '#21262d'}}, horzLines: {{color: '#21262d'}}}},
  width: document.getElementById('c2').offsetWidth,
  height: 280,
  timeScale: {{timeVisible: true, secondsVisible: false, borderColor: '#30363d'}},
  rightPrice: {{borderColor: '#30363d'}},
}});
const cs = ch2.addCandlestickSeries({{
  upColor:'#26a69a',downColor:'#ef5350',
  borderUpColor:'#26a69a',borderDownColor:'#ef5350',
  wickUpColor:'#26a69a',wickDownColor:'#ef5350',
}});
cs.setData(candles);
cs.setMarkers(markers);
ch2.timeScale().fitContent();
window.addEventListener('resize',()=>ch2.resize(document.getElementById('c2').offsetWidth,280));
</script>
</body>
</html>"""


# ═══════════════════════════════════════
#  主程序
# ═══════════════════════════════════════

def main():
    print('=' * 65)
    print('  SPY v3信号体系回测 vs B&H')
    print('=' * 65)

    bars    = load_data()
    signals = load_signals()
    print(f'  数据: {len(bars)} 天 | {bars[0]["date"]} ~ {bars[-1]["date"]}')
    print(f'  信号: {len(signals)} 个')

    INITIAL = 10_000.0

    v3_curve, v3_trades = backtest_v3(bars, signals, INITIAL)
    bh_curve, bh_trades = buy_and_hold(bars, INITIAL)

    v3_stats = calc_stats(v3_curve, v3_trades, INITIAL)
    bh_stats = calc_stats(bh_curve, bh_trades, INITIAL)

    excess = v3_stats['total_return'] - bh_stats['total_return']
    print_report(v3_stats, bh_stats, excess)

    html = build_html(v3_stats, bh_stats, v3_trades, signals, bars)
    with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'\n  ✅ HTML: {OUTPUT_HTML}')

    # 保存结果
    result = {
        'v3_final':     v3_stats['final'],
        'bh_final':     bh_stats['final'],
        'v3_return':    v3_stats['total_return'],
        'bh_return':    bh_stats['total_return'],
        'excess':       excess,
        'v3_cagr':      v3_stats['cagr'],
        'bh_cagr':      bh_stats['cagr'],
        'v3_max_dd':    v3_stats['max_drawdown'],
        'bh_max_dd':    bh_stats['max_drawdown'],
        'v3_n_trades':  v3_stats['n_total_trades'],
        'win_rate':     v3_stats['win_rate'],
        'profit_factor':v3_stats['profit_factor'],
        'n_round_trips':v3_stats['n_round_trips'],
        'avg_win':      v3_stats['avg_win'],
        'avg_loss':     v3_stats['avg_loss'],
        'trades':       v3_trades,
    }
    out_path = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spy_v3_result.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f'  ✅ JSON: {out_path}')


if __name__ == '__main__':
    main()
