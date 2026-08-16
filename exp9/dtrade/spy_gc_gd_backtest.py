#!/usr/bin/env python3
"""
SPY EMA20/50 金叉死叉策略回测
================================

策略规则：
  - 金叉（GC）= EMA20 上穿 EMA50  → 全仓买入
  - 死叉（GD）= EMA20 下穿 EMA50  → 全仓卖出（空仓等待）
  - 基准：买入后持有不动（B&H）

初始金额：$10,000
不计手续费（对比公平）
"""

import json
import math
from pathlib import Path

KLINES_DIR = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines')
OUTPUT_HTML = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spy_gc_gd_backtest.html')


# ═══════════════════════════════════════
#  数据 & 指标
# ═══════════════════════════════════════

def calc_ema(prices, period):
    if len(prices) < period:
        return [None] * len(prices)
    k = 2 / (period + 1)
    result = [None] * (period - 1)
    result.append(prices[period - 1])
    for i in range(period, len(prices)):
        result.append(prices[i] * k + result[-1] * (1 - k))
    return result


def load_data():
    with open(KLINES_DIR / 'SPY_1d.json') as f:
        bars = json.load(f)['data']
    return bars


def build_records(bars):
    closes = [b['close'] for b in bars]
    dates  = [b['date'] for b in bars]

    e20 = calc_ema(closes, 20)
    e50 = calc_ema(closes, 50)

    records = []
    for i in range(len(bars)):
        prev_e20 = e20[i - 1] if i > 0 else None
        prev_e50 = e50[i - 1] if i > 0 else None

        # 金叉/死叉判断
        gc = (prev_e20 is not None and prev_e50 is not None and
              prev_e20 <= prev_e50 and e20[i] is not None and e50[i] is not None and
              e20[i] > e50[i])
        gd = (prev_e20 is not None and prev_e50 is not None and
              prev_e20 >= prev_e50 and e20[i] is not None and e50[i] is not None and
              e20[i] < e50[i])

        records.append({
            'date':   dates[i],
            'close':  closes[i],
            'ema20':  e20[i],
            'ema50':  e50[i],
            'gc':     gc,
            'gd':     gd,
        })
    return records


# ═══════════════════════════════════════
#  回测引擎
# ═══════════════════════════════════════

def backtest(records, initial_capital=10_000.0):
    """
    策略：GC 满仓买入，GD 清仓，空仓等待
    返回每日净值序列和关键统计
    """
    cash    = initial_capital
    shares  = 0.0
    position_value = 0.0

    equity_curve = []   # 每日总权益
    trades       = []   # 交易记录
    in_position  = False

    for i, r in enumerate(records):
        price = r['close']

        # ── 入场 ──
        if r['gc'] and not in_position:
            shares = cash / price
            cash   = 0.0
            in_position = True
            trades.append({
                'date':    r['date'],
                'action':  'BUY',
                'price':   price,
                'shares':  shares,
                'equity':  0.0,   # 待收盘后更新
            })

        # ── 出场 ──
        elif r['gd'] and in_position:
            cash  = shares * price
            trades.append({
                'date':    r['date'],
                'action':  'SELL',
                'price':   price,
                'shares':  shares,
                'equity':  cash,
            })
            shares = 0.0
            in_position = False

        # ── 每日净值 ──
        if in_position:
            position_value = shares * price
        else:
            position_value = 0.0
        total_equity = cash + position_value
        equity_curve.append({
            'date':   r['date'],
            'price':  price,
            'equity': total_equity,
            'in_pos': in_position,
        })

    # 最后一天若仍持仓，按最后收盘价计算
    if in_position and records:
        final_price = records[-1]['close']
        final_equity = shares * final_price
        equity_curve[-1]['equity'] = final_equity

    return equity_curve, trades


def buy_and_hold(records, initial_capital=10_000.0):
    """
    基准：第一天收盘买入，全程持有
    """
    if not records:
        return [], []
    first_price = records[0]['close']
    shares = initial_capital / first_price
    equity_curve = []
    for r in records:
        equity_curve.append({
            'date':   r['date'],
            'price':  r['close'],
            'equity': shares * r['close'],
            'in_pos': True,
        })
    return equity_curve, [{'date': records[0]['date'], 'action': 'BUY', 'price': first_price, 'shares': shares}]


# ═══════════════════════════════════════
#  绩效计算
# ═══════════════════════════════════════

def calc_stats(equity_curve, trades, initial_capital):
    if not equity_curve:
        return {}

    final_equity = equity_curve[-1]['equity']
    total_return = (final_equity - initial_capital) / initial_capital

    # 年化（基于实际交易日天数）
    n_days  = len(equity_curve)
    n_years = n_days / 252
    cagr    = (final_equity / initial_capital) ** (1 / n_years) - 1 if n_years > 0 else 0

    # 最大回撤
    peak = initial_capital
    max_dd = 0.0
    for row in equity_curve:
        eq = row['equity']
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > max_dd:
            max_dd = dd

    # 交易次数
    n_trades = len(trades)

    # 胜率（盈亏比）
    wins, losses = 0, 0
    winAmt, lossAmt = 0.0, 0.0
    for i in range(0, len(trades) - 1, 2):
        if i + 1 < len(trades):
            buy_tr  = trades[i]
            sell_tr = trades[i + 1]
            if buy_tr['action'] == 'BUY' and sell_tr['action'] == 'SELL':
                pnl = (sell_tr['price'] - buy_tr['price']) / buy_tr['price']
                if pnl > 0:
                    wins += 1
                    winAmt += pnl
                else:
                    losses += 1
                    lossAmt += abs(pnl)

    total_closed = wins + losses
    win_rate     = wins / total_closed if total_closed > 0 else 0
    avg_win      = winAmt / wins       if wins > 0 else 0
    avg_loss     = lossAmt / losses    if losses > 0 else 0
    profit_factor= winAmt / lossAmt    if lossAmt > 0 else float('inf')

    return {
        'initial':      initial_capital,
        'final':        final_equity,
        'total_return': total_return,
        'cagr':         cagr,
        'max_drawdown': max_dd,
        'n_trades':     n_trades,
        'n_round_trips': total_closed,
        'win_rate':     win_rate,
        'avg_win':      avg_win,
        'avg_loss':     avg_loss,
        'profit_factor': profit_factor,
        'equity_curve': equity_curve,
    }


# ═══════════════════════════════════════
#  报告输出
# ═══════════════════════════════════════

def print_report(strategy_stats, bh_stats):
    print(f"\n{'='*65}")
    print(f"  SPY EMA20/50 金叉死叉策略 vs 买入持有 回测报告")
    print(f"{'='*65}")

    print(f"\n  初始本金: ${strategy_stats['initial']:,.2f}")
    print(f"\n  {'指标':<20} {'GC/GD策略':>15} {'买入持有(B&H)':>15}")
    print(f"  {'-'*20} {'-'*15} {'-'*15}")

    def fmt_pct(v): return f"{v*100:.2f}%"
    def fmt_dd(v):  return f"{v*100:.2f}%"
    def fmt_ratio(v):return f"{v:.2f}"
    def fmt_money(v):return f"${v:,.2f}"

    print(f"  {'最终权益':<20} {fmt_money(strategy_stats['final']):>15} {fmt_money(bh_stats['final']):>15}")
    print(f"  {'总收益率':<20} {fmt_pct(strategy_stats['total_return']):>15} {fmt_pct(bh_stats['total_return']):>15}")
    print(f"  {'年化收益率(CAGR)':<20} {fmt_pct(strategy_stats['cagr']):>15} {fmt_pct(bh_stats['cagr']):>15}")
    print(f"  {'最大回撤':<20} {fmt_dd(strategy_stats['max_drawdown']):>15} {fmt_dd(bh_stats['max_drawdown']):>15}")
    print(f"  {'交易次数':<20} {strategy_stats['n_trades']:>15} {'N/A':>15}")
    print(f"  {'完整波段数':<20} {strategy_stats['n_round_trips']:>15} {'N/A':>15}")
    print(f"  {'胜率':<20} {fmt_pct(strategy_stats['win_rate']):>15} {'N/A':>15}")
    print(f"  {'盈亏比':<20} {fmt_ratio(strategy_stats['profit_factor']):>15} {'N/A':>15}")

    # 胜负明细
    print(f"\n  策略胜负明细:")
    print(f"    盈利波段平均涨幅: {fmt_pct(strategy_stats['avg_win'])}")
    print(f"    亏损波段平均跌幅: {fmt_pct(strategy_stats['avg_loss'])}")

    # 超额收益
    excess = strategy_stats['total_return'] - bh_stats['total_return']
    winner  = "策略优于B&H ✅" if excess > 0 else "B&H优于策略 ❌"
    print(f"\n  超额收益: {fmt_pct(excess)}  ({winner})")

    return excess


# ═══════════════════════════════════════
#  HTML 可视化
# ═══════════════════════════════════════

def build_html(strategy_stats, bh_stats, trades, records):
    strat_curve = strategy_stats['equity_curve']
    bh_curve    = bh_stats['equity_curve']

    def series_data(curve):
        return json.dumps([{'time': r['date'], 'value': r['equity']} for r in curve])

    # 买卖 markers（从 records 的 gc/gd 标注）
    markers = []
    for r in records:
        if r['gc']:
            markers.append({
                'time': r['date'], 'position': 'belowBar',
                'color': '#00C853', 'shape': 'arrowUp',
                'text': 'GC 买入',
            })
        elif r['gd']:
            markers.append({
                'time': r['date'], 'position': 'aboveBar',
                'color': '#FF1744', 'shape': 'arrowDown',
                'text': 'GD 卖出',
            })

    lc_path = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/dtrade/lightweight-charts.js')
    lc_lib  = open(lc_path).read() if lc_path.exists() else ''

    strat_final = strategy_stats['final']
    bh_final    = bh_stats['final']
    strat_win   = "✅" if strat_final > bh_final else "❌"

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>SPY 金叉死叉策略回测</title>
<script>{lc_lib}</script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}
.wrap{{padding:16px;max-width:1400px;margin:0 auto}}
.header{{display:flex;align-items:flex-start;gap:24px;flex-wrap:wrap;margin-bottom:20px}}
.title{{font-size:22px;font-weight:700;color:#58a6ff}}
.sub{{color:#8b949e;font-size:12px;margin-top:4px}}
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:20px}}
.kpi{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px 16px}}
.kpi .label{{color:#8b949e;font-size:11px;text-transform:uppercase;margin-bottom:6px}}
.kpi .val{{font-size:20px;font-weight:700}}
.kpi .val.green{{color:#3fb950}}
.kpi .val.red{{color:#f85149}}
.kpi .sub{{color:#8b949e;font-size:11px;margin-top:2px}}
.chart-section{{background:#161b22;border:1px solid #30363d;border-radius:8px;margin-bottom:16px;overflow:hidden}}
.chart-header{{padding:12px 16px;border-bottom:1px solid #30363d;font-size:13px;font-weight:600;color:#e6edf3}}
.chart-note{{padding:8px 16px 4px;font-size:11px;color:#8b949e}}
#chart1,#chart2{{width:100%}}
.legend-box{{display:flex;gap:16px;padding:8px 16px;background:#0d1117;border-top:1px solid #30363d;font-size:11px;color:#8b949e}}
.legend-box span{{display:flex;align-items:center;gap:6px}}
.dot{{width:10px;height:3px;border-radius:2px;display:inline-block}}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <div>
      <div class="title">SPY EMA20/50 金叉死叉策略回测</div>
      <div class="sub">{records[0]['date']} ~ {records[-1]['date']} · 初始本金 $10,000 · {len(records)}交易日</div>
    </div>
  </div>

  <div class="kpi-grid">
    <div class="kpi">
      <div class="label">策略最终权益</div>
      <div class="val {'green' if strat_final > 10000 else 'red'}">${strat_final:,.0f}</div>
      <div class="sub">总收益 {strategy_stats['total_return']*100:+.1f}%</div>
    </div>
    <div class="kpi">
      <div class="label">B&H 最终权益</div>
      <div class="val {'green' if bh_final > 10000 else 'red'}">${bh_final:,.0f}</div>
      <div class="sub">总收益 {bh_stats['total_return']*100:+.1f}%</div>
    </div>
    <div class="kpi">
      <div class="label">超额收益</div>
      <div class="val {'green' if strat_final > bh_final else 'red'}">{(strat_final-bh_final):+,.0f}</div>
      <div class="sub">{strat_win} GC/GD {'优于' if strat_final > bh_final else '劣于'}B&H</div>
    </div>
    <div class="kpi">
      <div class="label">策略年化</div>
      <div class="val {'green' if strategy_stats['cagr'] > 0 else 'red'}">{strategy_stats['cagr']*100:.2f}%</div>
      <div class="sub">B&H {bh_stats['cagr']*100:.2f}%</div>
    </div>
    <div class="kpi">
      <div class="label">策略最大回撤</div>
      <div class="val red">{strategy_stats['max_drawdown']*100:.1f}%</div>
      <div class="sub">B&H {bh_stats['max_drawdown']*100:.1f}%</div>
    </div>
    <div class="kpi">
      <div class="label">交易次数</div>
      <div class="val">{strategy_stats['n_trades']}</div>
      <div class="sub">胜率 {strategy_stats['win_rate']*100:.0f}% · 盈亏比 {strategy_stats['profit_factor']:.2f}</div>
    </div>
  </div>

  <!-- 权益曲线对比 -->
  <div class="chart-section">
    <div class="chart-header">📈 权益曲线对比</div>
    <div class="chart-note">绿色=GC/GD策略 | 蓝色=买入持有</div>
    <div id="chart1" style="height:320px"></div>
  </div>

  <!-- SPY 价格 + GC/GD 标注 -->
  <div class="chart-section">
    <div class="chart-header">💹 SPY 价格走势 + 金叉/死叉信号</div>
    <div id="chart2" style="height:320px"></div>
    <div class="legend-box">
      <span><span class="dot" style="background:#00C853"></span> 🟢 金叉买入</span>
      <span><span class="dot" style="background:#FF1744"></span> 🔴 死叉卖出</span>
    </div>
  </div>
</div>

<script>
{lc_lib}

const init_capital = 10000;

// ── 权益曲线 ──
const strat_eq = {series_data(strat_curve)};
const bh_eq   = {series_data(bh_curve)};

const chart1 = LightweightCharts.createChart(document.getElementById('chart1'), {{
  layout: {{background: {{color: '#161b22'}}, textColor: '#e6edf3'}},
  grid: {{vertLines: {{color: '#21262d'}}, horzLines: {{color: '#21262d'}}}},
  width: document.getElementById('chart1').offsetWidth,
  height: 320,
  timeScale: {{timeVisible: true, secondsVisible: false, borderColor: '#30363d'}},
  rightPrice: {{borderColor: '#30363d'}},
}});

const candl1 = chart1.addCandlestickSeries({{
  upColor: 'transparent', downColor: 'transparent',
  borderUpColor: 'transparent', borderDownColor: 'transparent',
  wickUpColor: 'transparent', wickDownColor: 'transparent',
}});
candl1.setData(strat_eq.map(d => ({{time: d.time, open: d.value, high: d.value, low: d.value, close: d.value}})));

const s1 = chart1.addLineSeries({{color: '#3fb950', lineWidth: 2, title: 'GC/GD策略'}}).setData(strat_eq);
const s2 = chart1.addLineSeries({{color: '#58a6ff', lineWidth: 1, title: 'B&H'}}).setData(bh_eq);

chart1.timeScale().fitContent();
window.addEventListener('resize', () => chart1.resize(document.getElementById('chart1').offsetWidth, 320));

// ── SPY 价格 + markers ──
const candles = {json.dumps([{'time': r['date'], 'open': r['close'], 'high': r['close'], 'low': r['close'], 'close': r['close']} for r in records])};
const priceMarkers = {json.dumps(markers)};

const chart2 = LightweightCharts.createChart(document.getElementById('chart2'), {{
  layout: {{background: {{color: '#161b22'}}, textColor: '#e6edf3'}},
  grid: {{vertLines: {{color: '#21262d'}}, horzLines: {{color: '#21262d'}}}},
  width: document.getElementById('chart2').offsetWidth,
  height: 320,
  timeScale: {{timeVisible: true, secondsVisible: false, borderColor: '#30363d'}},
  rightPrice: {{borderColor: '#30363d'}},
}});

const candl2 = chart2.addCandlestickSeries({{
  upColor: '#26a69a', downColor: '#ef5350',
  borderUpColor: '#26a69a', borderDownColor: '#ef5350',
  wickUpColor: '#26a69a', wickDownColor: '#ef5350',
}});
const priceData = candles.map(d => ({{time: d.time, open: d.open, high: d.high, low: d.low, close: d.close}}));
candl2.setData(priceData);
candl2.setMarkers(priceMarkers);

chart2.timeScale().fitContent();
window.addEventListener('resize', () => chart2.resize(document.getElementById('chart2').offsetWidth, 320));
</script>
</body>
</html>"""


# ═══════════════════════════════════════
#  主程序
# ═══════════════════════════════════════

def main():
    print('=' * 65)
    print('  SPY EMA20/50 金叉死叉策略回测')
    print('=' * 65)

    # 加载数据
    bars    = load_data()
    records = build_records(bars)
    print(f'  数据: {len(records)} 天 | {records[0]["date"]} ~ {records[-1]["date"]}')

    # 金叉/死叉统计
    gc_count = sum(1 for r in records if r['gc'])
    gd_count = sum(1 for r in records if r['gd'])
    print(f'  金叉: {gc_count} 次 | 死叉: {gd_count} 次')

    INITIAL = 10_000.0

    # 两套策略
    strat_curve, strat_trades = backtest(records, INITIAL)
    bh_curve,    bh_trades    = buy_and_hold(records, INITIAL)

    strat_stats = calc_stats(strat_curve, strat_trades, INITIAL)
    bh_stats    = calc_stats(bh_curve,    bh_trades,    INITIAL)

    # 报告
    excess = print_report(strat_stats, bh_stats)

    # HTML
    html = build_html(strat_stats, bh_stats, strat_trades, records)
    with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'\n  ✅ HTML: {OUTPUT_HTML}')

    # 保存结果 JSON
    import math
    out = {
        'initial': INITIAL,
        'strategy_final': strat_stats['final'],
        'bh_final':       bh_stats['final'],
        'strategy_return':strat_stats['total_return'],
        'bh_return':      bh_stats['total_return'],
        'excess_return':  excess,
        'strategy_cagr':  strat_stats['cagr'],
        'bh_cagr':        bh_stats['cagr'],
        'strategy_max_dd':strat_stats['max_drawdown'],
        'bh_max_dd':      bh_stats['max_drawdown'],
        'n_trades':       strat_stats['n_trades'],
        'win_rate':       strat_stats['win_rate'],
        'profit_factor':  strat_stats['profit_factor'],
        'trades':         strat_trades,
    }
    json_out = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spy_gc_gd_result.json')
    with open(json_out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'  ✅ JSON: {json_out}')


if __name__ == '__main__':
    main()
