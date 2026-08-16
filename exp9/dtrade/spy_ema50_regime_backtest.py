#!/usr/bin/env python3
"""
SPY EMA50斜率区间策略回测
==========================

规则：
  - EMA50 斜率 < 0 → 卖出，空仓等待
  - EMA50 斜率从 <0 站上 ≥0 → 买入
  - 对比：买入持有不动

初始本金: $10,000
不计手续费
"""

import json
from pathlib import Path

KLINES_DIR = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines')
OUTPUT_HTML = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spy_ema50_regime_backtest.html')


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

    e50 = calc_ema(closes, 50)

    # 5日斜率
    e50_slope = [None] * len(closes)
    for i in range(5, len(closes)):
        if e50[i - 5] and e50[i] and e50[i - 5] > 0:
            e50_slope[i] = e50[i] / e50[i - 5] - 1

    records = []
    for i, bar in enumerate(bars):
        records.append({
            'date':      dates[i],
            'open':      bar.get('open', bar['close']),
            'high':      bar['high'],
            'low':       bar['low'],
            'close':     closes[i],
            'ema50':     e50[i],
            'e50_slope': e50_slope[i],
        })
    return records


# ═══════════════════════════════════════
#  回测
# ═══════════════════════════════════════

def backtest(records, initial=10_000.0):
    """
    EMA50斜率 < 0 → 空仓
    斜率从 <0 站上 ≥0 → 买入
    """
    cash   = initial
    shares = 0.0
    in_pos = False
    entry_price = 0.0

    equity_curve = []
    trades = []

    for i, r in enumerate(records):
        price     = r['close']
        slope     = r['e50_slope']
        in_regime = slope is not None and slope < 0

        # 下一日开盘执行
        if i < len(records) - 1:
            next_open = records[i + 1]['open']
        else:
            next_open = price

        # ── 买入：斜率从负转非负 ──
        if (not in_pos and
            slope is not None and slope >= 0 and
            i > 0 and records[i - 1]['e50_slope'] is not None and
            records[i - 1]['e50_slope'] < 0):
            shares     = cash / next_open
            entry_price = next_open
            cash      = 0.0
            in_pos    = True
            trades.append({
                'date':   records[i + 1]['date'] if i + 1 < len(records) else r['date'],
                'action': 'BUY',
                'price':  next_open,
                'shares': shares,
            })

        # ── 卖出：斜率进入负区间 ──
        elif (in_pos and
              slope is not None and slope < 0 and
              i > 0 and records[i - 1]['e50_slope'] is not None and
              records[i - 1]['e50_slope'] >= 0):
            cash      = shares * next_open
            pnl_pct   = (next_open - entry_price) / entry_price
            trades.append({
                'date':    records[i + 1]['date'] if i + 1 < len(records) else r['date'],
                'action':  'SELL',
                'price':   next_open,
                'shares':  shares,
                'equity':  cash,
                'pnl_pct': pnl_pct,
            })
            shares = 0.0
            in_pos = False

        # ── 权益记录 ──
        pos_val  = shares * price
        equity   = cash + pos_val
        equity_curve.append({
            'date':   r['date'],
            'price':  price,
            'equity': equity,
            'in_pos': in_pos,
        })

    # 最后一天若仍持仓
    if in_pos and records:
        final_price   = records[-1]['close']
        equity_curve[-1]['equity'] = shares * final_price
        equity_curve[-1]['price']  = final_price

    return equity_curve, trades


def buy_and_hold(records, initial=10_000.0):
    first_open = records[0]['open']
    shares = initial / first_open
    curve = []
    for r in records:
        curve.append({
            'date':   r['date'],
            'price':  r['close'],
            'equity': shares * r['close'],
            'in_pos': True,
        })
    return curve, [{'date': records[0]['date'], 'action': 'BUY', 'price': first_open, 'shares': shares}]


# ═══════════════════════════════════════
#  绩效
# ═══════════════════════════════════════

def calc_stats(curve, trades, initial):
    if not curve:
        return {}
    final_eq = curve[-1]['equity']
    n_days   = len(curve)
    n_years  = n_days / 252
    total_ret= (final_eq - initial) / initial
    cagr     = (final_eq / initial) ** (1 / n_years) - 1 if n_years > 0 else 0

    peak, max_dd = initial, 0.0
    for row in curve:
        if row['equity'] > peak:
            peak = row['equity']
        dd = (peak - row['equity']) / peak
        if dd > max_dd:
            max_dd = dd

    wins, losses = [], []
    buy_t = None
    for t in trades:
        if t['action'] == 'BUY':
            buy_t = t
        elif t['action'] == 'SELL' and buy_t:
            pnl = t.get('pnl_pct', (t['price'] - buy_t['price']) / buy_t['price'])
            (wins if pnl > 0 else losses).append(pnl)
            buy_t = None

    n_win  = len(wins)
    n_loss = len(losses)
    n_tot  = n_win + n_loss
    wr     = n_win / n_tot if n_tot > 0 else 0
    avg_w  = sum(wins) / n_win  if n_win  > 0 else 0
    avg_l  = sum(losses) / n_loss if n_loss > 0 else 0
    pf     = abs(sum(wins) / sum(losses)) if losses else float('inf')

    return {
        'initial':      initial,
        'final':        final_eq,
        'total_return': total_ret,
        'cagr':         cagr,
        'max_drawdown': max_dd,
        'n_trades':     len(trades),
        'n_round_trips': n_tot,
        'win_rate':     wr,
        'avg_win':      avg_w,
        'avg_loss':     avg_l,
        'profit_factor': pf,
        'equity_curve': curve,
    }


def fmt_pct(v):   return f"{v*100:+.2f}%"
def fmt_money(v): return f"${v:,.2f}"


def print_report(strategy, bh, excess):
    print(f"\n{'='*62}")
    print(f"  SPY EMA50斜率策略 vs 买入持有")
    print(f"{'='*62}")
    print(f"\n  {'指标':<18} {'EMA50斜率策略':>16} {'B&H':>14}")
    print(f"  {'-'*18} {'-'*16} {'-'*14}")
    print(f"  {'最终权益':<18} {fmt_money(strategy['final']):>16} {fmt_money(bh['final']):>14}")
    print(f"  {'总收益率':<18} {fmt_pct(strategy['total_return']):>16} {fmt_pct(bh['total_return']):>14}")
    print(f"  {'年化(CAGR)':<18} {fmt_pct(strategy['cagr']):>16} {fmt_pct(bh['cagr']):>14}")
    print(f"  {'最大回撤':<18} {fmt_pct(strategy['max_drawdown']):>16} {fmt_pct(bh['max_drawdown']):>14}")
    print(f"  {'交易次数':<18} {strategy['n_trades']:>16} {'N/A':>14}")
    print(f"  {'完整波段':<18} {strategy['n_round_trips']:>16} {'N/A':>14}")
    print(f"  {'胜率':<18} {fmt_pct(strategy['win_rate']):>16} {'N/A':>14}")
    print(f"  {'盈亏比':<18} {strategy['profit_factor']:>16.2f} {'N/A':>14}")
    print(f"\n  盈利波段平均: {fmt_pct(strategy['avg_win'])}")
    print(f"  亏损波段平均: {fmt_pct(strategy['avg_loss'])}")
    winner = "✅ EMA50策略跑赢" if excess > 0 else "❌ B&H跑赢"
    print(f"\n  超额收益: {fmt_pct(excess)}  ({winner})")


# ═══════════════════════════════════════
#  HTML
# ═══════════════════════════════════════

def build_html(strategy, bh, trades, records):
    def eq_series(curve):
        return json.dumps([{'time': r['date'], 'value': r['equity']} for r in curve])

    candles = json.dumps([{'time': r['date'], 'open': r['open'], 'high': r['high'],
                           'low': r['low'], 'close': r['close']} for r in records])

    # markers: 斜率由负转非负 → BUY, 由正转负 → SELL
    markers = []
    for i, r in enumerate(records):
        if i == 0:
            continue
        prev_slope = records[i - 1]['e50_slope']
        cur_slope  = r['e50_slope']
        if cur_slope is None or prev_slope is None:
            continue
        if prev_slope < 0 and cur_slope >= 0:
            markers.append({
                'time': r['date'], 'position': 'belowBar',
                'color': '#00BFFF', 'shape': 'arrowUp',
                'text': f"↗ EMA50恢复 买",
            })
        elif prev_slope >= 0 and cur_slope < 0:
            markers.append({
                'time': r['date'], 'position': 'aboveBar',
                'color': '#FF6D00', 'shape': 'arrowDown',
                'text': f"📉 EMA50下行 卖",
            })

    # 背景区间：EMA50斜率<0的区间
    in_regime = False
    regime_start = None
    regions = []
    for r in records:
        if r['e50_slope'] is not None and r['e50_slope'] < 0:
            if not in_regime:
                in_regime = True
                regime_start = r['date']
        else:
            if in_regime:
                regions.append({'start': regime_start, 'end': r['date']})
                in_regime = False
    if in_regime:
        regions.append({'start': regime_start, 'end': records[-1]['date']})

    lc_path = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/dtrade/lightweight-charts.js')
    lc_lib  = open(lc_path).read() if lc_path.exists() else ''

    s_final = strategy['final']
    b_final = bh['final']
    win     = s_final > b_final

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>EMA50斜率策略回测 vs B&H</title>
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
.legend{{display:flex;gap:14px;padding:8px 14px;background:#0d1117;border-top:1px solid #21262d;font-size:11px;color:#8b949e}}
.legend span{{display:flex;align-items:center;gap:5px}}
.dot{{width:10px;height:10px;border-radius:50%;display:inline-block}}
</style>
</head>
<body>
<div class="wrap">
  <div class="title">SPY EMA50斜率区间策略回测</div>
  <div class="sub">{records[0]['date']} ~ {records[-1]['date']} · 初始本金 $10,000</div>

  <div class="kpi-grid">
    <div class="kpi">
      <div class="l">策略最终权益</div>
      <div class="v {'g' if s_final>10000 else 'r'}">{fmt_money(s_final)}</div>
      <div class="s">{fmt_pct(strategy['total_return'])} ({strategy['cagr']*100:+.2f}%/年)</div>
    </div>
    <div class="kpi">
      <div class="l">B&amp;H 最终权益</div>
      <div class="v {'g' if b_final>10000 else 'r'}">{fmt_money(b_final)}</div>
      <div class="s">{fmt_pct(bh['total_return'])} ({bh['cagr']*100:+.2f}%/年)</div>
    </div>
    <div class="kpi">
      <div class="l">超额收益</div>
      <div class="v {'g' if win else 'r'}">{fmt_pct(strategy['total_return']-bh['total_return'])}</div>
      <div class="s">{'✅ 策略跑赢' if win else '❌ B&H跑赢'}</div>
    </div>
    <div class="kpi">
      <div class="l">策略最大回撤</div>
      <div class="v r">{fmt_pct(strategy['max_drawdown'])}</div>
      <div class="s">B&amp;H {fmt_pct(bh['max_drawdown'])}</div>
    </div>
    <div class="kpi">
      <div class="l">交易次数</div>
      <div class="v">{strategy['n_trades']}</div>
      <div class="s">胜率 {strategy['win_rate']*100:.0f}% · 盈亏比 {strategy['profit_factor']:.2f}</div>
    </div>
    <div class="kpi">
      <div class="l">完整波段</div>
      <div class="v">{strategy['n_round_trips']}</div>
      <div class="s">均盈 {fmt_pct(strategy['avg_win'])} · 均亏 {fmt_pct(strategy['avg_loss'])}</div>
    </div>
  </div>

  <div class="chart-box">
    <div class="ch-hdr">📈 权益曲线对比</div>
    <div id="c1" style="height:280px"></div>
  </div>
  <div class="chart-box">
    <div class="ch-hdr">💹 SPY 价格 + EMA50斜率信号（蓝色背景=空仓区间）</div>
    <div id="c2" style="height:280px"></div>
    <div class="legend">
      <span><span class="dot" style="background:#00BFFF"></span> 🟢 EMA50恢复买入</span>
      <span><span class="dot" style="background:#FF6D00"></span> 🔴 EMA50下行卖出</span>
      <span style="background:rgba(0,191,255,0.1);padding:2px 6px;border-radius:3px">蓝色背景=空仓等待</span>
    </div>
  </div>
</div>

<script>
{lc_lib}

const s_eq = {eq_series(strategy['equity_curve'])};
const b_eq = {eq_series(bh['equity_curve'])};
const candles = {candles};
const markers = {json.dumps(markers)};
const regions = {json.dumps(regions)};

// ── 权益曲线 ──
const ch1 = LightweightCharts.createChart(document.getElementById('c1'), {{
  layout: {{background: {{color: '#161b22'}}, textColor: '#e6edf3'}},
  grid: {{vertLines: {{color: '#21262d'}}, horzLines: {{color: '#21262d'}}}},
  width: document.getElementById('c1').offsetWidth,
  height: 280,
  timeScale: {{timeVisible: true, secondsVisible: false, borderColor: '#30363d'}},
  rightPrice: {{borderColor: '#30363d'}},
}});
ch1.addLineSeries({{color: '#FFD700', lineWidth: 2, title: 'EMA50策略'}}).setData(s_eq.map(d=>({{time:d.time,value:d.value}})));
ch1.addLineSeries({{color: '#58a6ff', lineWidth: 1, title: 'B&amp;H'}}).setData(b_eq.map(d=>({{time:d.time,value:d.value}})));
ch1.timeScale().fitContent();
window.addEventListener('resize',()=>ch1.resize(document.getElementById('c1').offsetWidth,280));

// ── SPY价格 + markers + 背景区间 ──
const ch2 = LightweightCharts.createChart(document.getElementById('c2'), {{
  layout: {{background: {{color: '#161b22'}}, textColor: '#e6edf3'}},
  grid: {{vertLines: {{color: '#21262d'}}, horzLines: {{color: '#21262d'}}}},
  width: document.getElementById('c2').offsetWidth,
  height: 280,
  timeScale: {{timeVisible: true, secondsVisible: false, borderColor: '#30363d'}},
  rightPrice: {{borderColor: '#30363d'}},
}});

// 背景区间
regions.forEach(reg => {{
  const hiData = candles
    .filter(c => c.time >= reg.start && c.time <= reg.end)
    .map(c => ({{time: c.time, value: c.high + 2}}));
  if (!hiData.length) return;
  ch2.addAreaSeries({{
    color: 'rgba(0,191,255,0.12)',
    lineWidth: 0,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
    topColor: 'rgba(0,191,255,0.12)',
    bottomColor: 'rgba(0,191,255,0.05)',
  }}).setData(hiData);
}});

const cs2 = ch2.addCandlestickSeries({{
  upColor:'#26a69a',downColor:'#ef5350',
  borderUpColor:'#26a69a',borderDownColor:'#ef5350',
  wickUpColor:'#26a69a',wickDownColor:'#ef5350',
}});
cs2.setData(candles);
cs2.setMarkers(markers);
ch2.timeScale().fitContent();
window.addEventListener('resize',()=>ch2.resize(document.getElementById('c2').offsetWidth,280));
</script>
</body>
</html>"""


# ═══════════════════════════════════════
#  主程序
# ═══════════════════════════════════════

def main():
    print('=' * 62)
    print('  SPY EMA50斜率策略回测')
    print('=' * 62)

    bars    = load_data()
    records = build_records(bars)
    print(f'  数据: {len(records)} 天 | {records[0]["date"]} ~ {records[-1]["date"]}')

    INITIAL = 10_000.0

    strat_curve, strat_trades = backtest(records, INITIAL)
    bh_curve,    bh_trades    = buy_and_hold(records, INITIAL)

    strat = calc_stats(strat_curve, strat_trades, INITIAL)
    bh    = calc_stats(bh_curve,    bh_trades,    INITIAL)

    excess = strat['total_return'] - bh['total_return']
    print_report(strat, bh, excess)

    html = build_html(strat, bh, strat_trades, records)
    with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'\n  ✅ HTML: {OUTPUT_HTML}')

    out = {
        'strategy_final': strat['final'],
        'bh_final':      bh['final'],
        'strategy_return':strat['total_return'],
        'bh_return':     bh['total_return'],
        'excess':        excess,
        'strategy_cagr': strat['cagr'],
        'bh_cagr':      bh['cagr'],
        'strategy_max_dd':strat['max_drawdown'],
        'bh_max_dd':    bh['max_drawdown'],
        'n_trades':     strat['n_trades'],
        'win_rate':     strat['win_rate'],
        'profit_factor':strat['profit_factor'],
        'n_round_trips':strat['n_round_trips'],
        'avg_win':      strat['avg_win'],
        'avg_loss':     strat['avg_loss'],
    }
    out_path = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spy_ema50_regime_result.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'  ✅ JSON: {out_path}')


if __name__ == '__main__':
    main()
