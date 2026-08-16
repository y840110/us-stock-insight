#!/usr/bin/env python3
"""
SPYTREND v3 — 牛市模式 + 空头能量评估体系
============================================

规则（基于 v2 的改进）：
  买入：同 v1（EMA50由负转正；EMA20由负转正再入场）
  卖出：
    · 空头能量弱 → EMA20由正转负才走（与v1相同）
    · 空头能量中 → EMA20由正转负走，或RSI65超买走
    · 空头能量强 → EMA20刚转负就走，或RSI60超买就走

空头能量评估（买入时计算上次卖出到本次买入的区间）：
  · 方向：EMA50在区间内是否全程向下
  · 幅度：区间最大跌幅（从卖出收盘价到最低价的比例）
  · 持续：买卖间隔天数

初始本金: $10,000
"""

import json
from pathlib import Path
from datetime import datetime

KLINES_DIR  = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines')
OUT_HTML    = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spytrend/v3_chart.html')
OUT_JSON    = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spytrend/v3_result.json')
OUT_BEAR    = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/spytrend/v2_bear_trades.json')


# ═══════════════════════════════════════
#  数据 & 指标
# ═══════════════════════════════════════

def calc_ema(prices, period):
    if len(prices) < period:
        return [None] * len(prices)
    k = 2 / (period + 1)
    r = [None] * (period - 1) + [prices[period - 1]]
    for i in range(period, len(prices)):
        r.append(prices[i] * k + r[-1] * (1 - k))
    return r


def load_data():
    with open(KLINES_DIR / 'SPY_1d.json') as f:
        bars = json.load(f)['data']
    closes = [b['close'] for b in bars]
    highs  = [b['high']  for b in bars]
    lows   = [b['low']   for b in bars]
    dates  = [b['date']  for b in bars]

    e20 = calc_ema(closes, 20)
    e50 = calc_ema(closes, 50)

    # 斜率：今日值 / 5日前值 - 1
    e20s = [None] * len(closes)
    e50s = [None] * len(closes)
    for i in range(5, len(closes)):
        if e20[i - 5] and e20[i]:
            e20s[i] = e20[i] / e20[i - 5] - 1
        if e50[i - 5] and e50[i]:
            e50s[i] = e50[i] / e50[i - 5] - 1

    # RSI(14) 预计算
    rsi14 = calc_rsi(closes, 14)

    records = []
    for i, bar in enumerate(bars):
        records.append({
            'date':   dates[i],
            'open':   bar['open'],
            'high':   highs[i],
            'low':    lows[i],
            'close':  closes[i],
            'ema20':  e20[i],
            'ema50':  e50[i],
            'e20s':   e20s[i],
            'e50s':   e50s[i],
            'rsi14':  rsi14[i],
        })
    return records


def calc_rsi(prices, period=14):
    """标准RSI，14日"""
    if len(prices) < period + 1:
        return [None] * len(prices)
    rsi = [None] * len(prices)
    gains, losses = [], []
    for i in range(1, len(prices)):
        delta = prices[i] - prices[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    # 初始均值
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi[period] = 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi[i + 1] = 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return rsi


# ═══════════════════════════════════════
#  空头能量评估
# ═══════════════════════════════════════

def assess_bear_energy(sell_record, buy_record, records, date_to_idx):
    """
    评估从上次卖出到本次买入之间的空头能量。

    返回 dict:
      direction:  'down'   = EMA50全程向下
                 'mixed'  = 中间有反复
                 'up'     = 全程向上（不是下跌后买入，忽略）
      drawdown:  卖出价到区间最低的最大跌幅（正数）
      days:      买卖间隔天数
      energy:    'strong' / 'medium' / 'weak'
      score:     0-3 分数（energy的数值化）
    """
    s_date = sell_record['date']
    b_date = buy_record['date']
    s_idx  = date_to_idx.get(s_date)
    b_idx  = date_to_idx.get(b_date)

    if s_idx is None or b_idx is None or b_idx <= s_idx:
        return {'direction': 'up', 'drawdown': 0, 'days': 0, 'energy': 'weak', 'score': 0}

    # 区间数据
    window = records[s_idx:b_idx + 1]  # 包含卖出日和买入日
    if len(window) < 3:
        return {'direction': 'mixed', 'drawdown': 0, 'days': len(window) - 1, 'energy': 'weak', 'score': 1}

    # 1. EMA50 方向：用净变化（而非单调性）
    #    - 卖出日 EMA50 vs 买入日 EMA50：净跌幅 >2% 视为向下
    ema50_start = window[0]['ema50']
    ema50_end   = window[-1]['ema50']
    if ema50_start and ema50_end:
        ema50_chg = (ema50_end - ema50_start) / ema50_start
        if ema50_chg < -0.02:
            direction = 'down'
        elif ema50_chg > 0.02:
            direction = 'up'
        else:
            direction = 'mixed'
    else:
        direction = 'mixed'

    # 2. 下跌幅度：从卖出收盘价到区间最低价的跌幅
    sell_price  = sell_record['close']
    lowest_low  = min(r['low'] for r in window)
    drawdown    = max(0.0, (sell_price - lowest_low) / sell_price)  # 正数表示跌幅

    # 3. 持续天数
    days = b_idx - s_idx

    # 综合打分：score 0-3
    # 条件：方向向下 + 跌幅大 + 天数多 → 能量强
    score = 0
    if direction == 'down':
        score += 1
    if drawdown >= 0.05:       # ≥5%
        score += 1
    elif drawdown >= 0.10:     # ≥10%
        score += 1             # 额外加分
    if days >= 20:
        score += 1

    if score >= 3:
        energy = 'strong'
    elif score >= 2:
        energy = 'medium'
    elif score == 1:
        energy = 'weak'
    else:
        energy = 'weak'

    return {
        'direction': direction,
        'drawdown':  drawdown,
        'days':      days,
        'energy':    energy,
        'score':     score,
    }


# ═══════════════════════════════════════
#  回测（v3 — 牛市模式 + 空头能量 exit）
# ═══════════════════════════════════════

def backtest_v3(records, initial=10_000.0):
    """
    v3 状态机（彻底重想的 exit 逻辑）：

    核心洞察：
      EMA20 slope 转负 = 快退出（适用于震荡/跌市）
      EMA20 价格死叉下穿 EMA50 = 慢退出（适用于趋势/牛市）
      → 持仓中动态选择：EMA20在50之上用死叉exit，在50之下用slope exit

    买入信号：
      EMA50 slope 由负转正 → 首次入场
      EMA20 slope 由负转正 → 再入场

    卖出信号（动态）：
      · EMA20 价格 > EMA50 价格：EMA20 死叉下穿 EMA50 → SELL（更宽容）
      · EMA20 价格 < EMA50 价格：EMA20 slope 由正转负 → SELL（更保守）
      · 空头能量 strong/medium：叠加 RSI > 55/60 逃生口
    """
    cash, shares, in_pos = initial, 0.0, False
    entry_px    = 0.0
    equity_curve, trades = [], []

    date_to_idx = {r['date']: i for i, r in enumerate(records)}

    # 持仓状态
    bear_energy   = None    # 空头能量（来自v2）
    last_sell_px  = 0.0    # 上次卖出的执行价
    last_sell_rec = None   # 上次卖出的 record

    for i, r in enumerate(records):
        price    = r['close']
        nxt_open = records[i + 1]['open'] if i < len(records) - 1 else price
        prev     = records[i - 1] if i > 0 else None

        # ── 买入信号 ──────────────────────────────────────
        buy1 = (not in_pos and
                r['e50s'] is not None and r['e50s'] >= 0 and
                prev and prev['e50s'] is not None and prev['e50s'] < 0)

        buy2 = (not in_pos and
                r['e20s'] is not None and r['e20s'] >= 0 and
                prev and prev['e20s'] is not None and prev['e20s'] < 0)

        # ── 卖出信号 ──────────────────────────────────────
        be_str = bear_energy.get('energy', 'weak') if isinstance(bear_energy, dict) else str(bear_energy)

        # ① EMA20价格死叉下穿EMA50价格（慢exit：用于趋势中）
        death_cross = (
            in_pos and
            r['ema20'] is not None and r['ema50'] is not None and
            prev and prev['ema20'] is not None and prev['ema50'] is not None and
            prev['ema20'] > prev['ema50'] and r['ema20'] <= r['ema50']
        )

        # ② EMA20 slope 由正转负（快exit：用于震荡/弱势）
        slope_cross_down = (
            in_pos and
            r['e20s'] is not None and
            prev and prev['e20s'] is not None and
            prev['e20s'] > 0 and r['e20s'] <= 0
        )

        # ③ RSI 逃生口（空头能量 strong/medium）
        rsi_escape = (
            in_pos and
            r['rsi14'] is not None and
            be_str == 'strong' and r['rsi14'] > 55
        ) or (
            in_pos and
            r['rsi14'] is not None and
            be_str == 'medium' and r['rsi14'] > 60
        )

        # 动态选择 exit：EMA20 > EMA50 用死叉（慢），EMA20 < EMA50 用slope（快）
        # RSI逃生口优先级最高
        # 动态 exit：先判断 EMA20 vs EMA50 的相对位置
        # · EMA20 > EMA50（上升趋势）：用死叉 exit（更耐心）
        # · EMA20 < EMA50（下降/震荡趋势）：用 slope 转负 exit（更快）
        # · RSI 逃生口始终最高优先级
        ema20_above = (
            r['ema20'] is not None and r['ema50'] is not None and
            r['ema20'] > r['ema50']
        )

        if rsi_escape:
            sell = True
            src  = f'RSI>{55 if be_str == "strong" else 60}'
        elif ema20_above and death_cross:
            # EMA20在50之上，出现死叉 → 趋势结束
            sell = True
            src  = '死叉(EMA20>EMA50)'
        elif not ema20_above and slope_cross_down:
            # EMA20在50之下，slope转负 → 动能衰竭
            sell = True
            src  = 'EMA20<=0'
        else:
            sell = False
            src  = None

        # ── 执行 ──────────────────────────────────────────
        if buy1 or buy2:
            src_buy = 'EMA50转正' if buy1 else 'EMA20再转正'
            shares = cash / nxt_open
            entry_px = nxt_open
            cash = 0.0
            in_pos = True

            bear_energy = assess_bear_energy(last_sell_rec, r, records, date_to_idx) if last_sell_rec else {'energy': 'weak', 'score': 0, 'direction': 'up', 'drawdown': 0, 'days': 0}

            next_date = records[i + 1]['date'] if i + 1 < len(records) else r['date']
            trades.append({
                'd': next_date, 'a': 'BUY', 'px': nxt_open,
                'src': src_buy,
                'bear_energy': bear_energy,
            })

        elif sell:
            cash = shares * nxt_open
            pnl = (nxt_open - entry_px) / entry_px

            next_date = records[i + 1]['date'] if i + 1 < len(records) else r['date']
            trades.append({
                'd': next_date, 'a': 'SELL', 'px': nxt_open,
                'pnl': pnl,
                'src': src,
                'exit_energy': bear_energy,
            })

            last_sell_px  = nxt_open
            last_sell_rec = r
            shares = 0.0
            in_pos = False
            bear_energy = None

        equity_curve.append({'d': r['date'], 'v': cash + shares * price})

    if in_pos:
        equity_curve[-1]['v'] = shares * records[-1]['close']
    return equity_curve, trades


def buy_and_hold(records, initial=10_000.0):
    shares = initial / records[0]['open']
    curve = [{'d': r['date'], 'v': shares * r['close']} for r in records]
    return curve, [{'d': records[0]['date'], 'a': 'BUY', 'px': records[0]['open']}]


# ═══════════════════════════════════════
#  绩效
# ═══════════════════════════════════════

def calc_stats(curve, trades, initial):
    final = curve[-1]['v']
    n_years = len(curve) / 252
    cagr = (final / initial) ** (1 / n_years) - 1
    peak, max_dd = initial, 0.0
    for e in curve:
        if e['v'] > peak:
            peak = e['v']
        dd = (peak - e['v']) / peak
        if dd > max_dd:
            max_dd = dd
    wins, losses = [], []
    bt = None
    for t in trades:
        if t['a'] == 'BUY':
            bt = t
        elif t['a'] == 'SELL' and bt:
            (wins if t['pnl'] > 0 else losses).append(t['pnl'])
            bt = None
    nw, nl = len(wins), len(losses)

    # 按空头能量分类统计
    energy_stats = {}
    for t in trades:
        be = t.get('bear_energy', {})
        e  = be.get('energy', 'unknown') if isinstance(be, dict) else 'unknown'
        if e not in energy_stats:
            energy_stats[e] = {'count': 0, 'wins': 0, 'losses': 0}
        if t['a'] == 'BUY':
            energy_stats[e]['count'] += 1

    return {
        'final':      final,
        'cagr':       cagr,
        'max_dd':     max_dd,
        'n_buys':     sum(1 for t in trades if t['a'] == 'BUY'),
        'n_sells':    sum(1 for t in trades if t['a'] == 'SELL'),
        'win_rate':   nw / (nw + nl) if nw + nl else 0,
        'avg_w':      sum(wins) / nw if nw else 0,
        'avg_l':      sum(losses) / nl if nl else 0,
        'pf':         abs(sum(wins) / sum(losses)) if losses else float('inf'),
        'equity_curve': curve,
        'energy_stats': energy_stats,
    }


def fmt_pct(v):   return f"{v * 100:+.2f}%"
def fmt_money(v): return f"${v:,.2f}"


# ═══════════════════════════════════════
#  HTML（复用 v1 模板，调整配色）
# ═══════════════════════════════════════

def build_html(records, trades, strat, bh, INITIAL):
    candles    = [{'time': r['date'], 'open': r['open'], 'high': r['high'],
                  'low': r['low'], 'close': r['close']} for r in records]
    ema20_line = [{'time': r['date'], 'value': r['ema20']} for r in records if r['ema20']]
    ema50_line = [{'time': r['date'], 'value': r['ema50']} for r in records if r['ema50']]
    e20s_pos   = [{'time': r['date'], 'value': max(r['e20s'], 0)} for r in records if r['e20s'] is not None]
    e20s_neg   = [{'time': r['date'], 'value': min(r['e20s'], 0)} for r in records if r['e20s'] is not None]
    e50s_pos   = [{'time': r['date'], 'value': max(r['e50s'], 0)} for r in records if r['e50s'] is not None]
    e50s_neg   = [{'time': r['date'], 'value': min(r['e50s'], 0)} for r in records if r['e50s'] is not None]
    zero_line  = [{'time': r['date'], 'value': 0} for r in records]

    # RSI 辅助线
    rsi_line   = [{'time': r['date'], 'value': r['rsi14']} for r in records if r['rsi14'] is not None]

    # 买卖点 + 空头能量标签
    markers = []
    for t in trades:
        be = t.get('bear_energy', {})
        energy = be.get('energy', '') if isinstance(be, dict) else ''
        label = {'strong': '⚠️', 'medium': '🔶', 'weak': '✅'}.get(energy, '')
        if t['a'] == 'BUY':
            markers.append({'time': t['d'], 'position': 'belowBar',
                           'color': '#00BFFF', 'shape': 'arrowUp',
                           'text': f"买 {t.get('src','')} {label}"})
        else:
            color = '#FF4444' if 'RSI' in t.get('src', '') else '#DA70D6'
            markers.append({'time': t['d'], 'position': 'aboveBar',
                           'color': color, 'shape': 'arrowDown',
                           'text': f"卖 {t.get('src','')}"})

    # 持仓区间
    in_pos, reg_start, regions = False, None, []
    for r in records:
        has_buy  = any(t['a'] == 'BUY'  and t['d'] == r['date'] for t in trades)
        has_sell = any(t['a'] == 'SELL' and t['d'] == r['date'] for t in trades)
        if has_buy and not in_pos:
            in_pos = True
            reg_start = r['date']
        elif has_sell and in_pos:
            in_pos = False
            regions.append({'start': reg_start, 'end': r['date']})
    if in_pos:
        regions.append({'start': reg_start, 'end': records[-1]['date']})

    eq_strat = [{'time': e['d'], 'value': e['v']} for e in strat['equity_curve']]
    eq_bh    = [{'time': e['d'], 'value': e['v']} for e in bh['equity_curve']]

    lc_path = Path('/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9/dtrade/lightweight-charts.js')
    lc_lib  = open(lc_path).read() if lc_path.exists() else ''

    s_final = strat['final']
    b_final = bh['final']
    win_v3  = s_final > b_final

    # 空头能量统计
    es = strat.get('energy_stats', {})
    bear_summary = ' | '.join(
        f"{k}: {v['count']}次" for k, v in es.items()
    )

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>SPYTREND v3 — 牛市模式 + 空头能量评估体系</title>
<script>
{lc_lib}
</script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;overflow:hidden}}
#main{{width:100vw;height:34vh}}
#sub{{width:100vw;height:28vh;border-top:3px solid #30363d}}
#rsi{{width:100vw;height:18vh;border-top:3px solid #30363d}}
#eq{{width:100vw;height:20vh;border-top:3px solid #30363d}}
.kpi{{padding:8px 14px;background:#161b22;border-bottom:1px solid #30363d;display:flex;gap:24px;flex-wrap:wrap;font-size:12px}}
.kpi span{{color:#8b949e}}
.kpi strong{{color:#e6edf3;font-weight:600}}
.kpi .win{{color:#3fb950}}
.kpi .lose{{color:#f85149}}
</style>
</head>
<body>
<div class="kpi">
  <span>最终权益: <strong class="{'win' if s_final>INITIAL else 'lose'}">{fmt_money(s_final)}</strong> ({fmt_pct(strat['cagr'])})  <span class="{'win' if win_v3 else 'lose'}">{'✅' if win_v3 else '❌'} vs B&H {fmt_money(b_final)}</span></span>
  <span>买 {strat['n_buys']} 卖 {strat['n_sells']} 波段 {strat['n_buys']-strat['n_sells']} 胜率 {strat['win_rate']*100:.0f}%</span>
  <span>均盈 {fmt_pct(strat['avg_w'])} 均亏 {fmt_pct(strat['avg_l'])} 盈亏比 {strat['pf']:.1f}×</span>
  <span>最大回撤 {fmt_pct(strat['max_dd'])}</span>
  <span>空头能量 {bear_summary}</span>
</div>
<div id="main"></div>
<div id="sub"></div>
<div id="rsi"></div>
<div id="eq"></div>
<script>
const candles = {json.dumps(candles)};
const ema20Line = {json.dumps(ema20_line)};
const ema50Line = {json.dumps(ema50_line)};
const e20Pos = {json.dumps(e20s_pos)};
const e20Neg = {json.dumps(e20s_neg)};
const e50Pos = {json.dumps(e50s_pos)};
const e50Neg = {json.dumps(e50s_neg)};
const zeroLine = {json.dumps(zero_line)};
const rsiLine = {json.dumps(rsi_line)};
const markers = {json.dumps(markers)};
const regions = {json.dumps(regions)};
const eqStrat = {json.dumps(eq_strat)};
const eqBH   = {json.dumps(eq_bh)};

// ── 主图 ──
const mainChart = LightweightCharts.createChart(document.getElementById('main'),{{
  layout:{{background:{{color:'#0d1117'}},textColor:'#e6edf3'}},
  grid:{{vertLines:{{color:'#21262d'}},horzLines:{{color:'#21262d'}}}},
  width:window.innerWidth,height:window.innerHeight*0.34,
  timeScale:{{timeVisible:true,secondsVisible:false,borderColor:'#30363d'}},
  rightPrice:{{borderColor:'#30363d'}},
}});

regions.forEach(reg => {{
  const hi = candles.filter(c => c.time >= reg.start && c.time <= reg.end)
    .map(c => ({{time:c.time,value:c.high+2}}));
  if (!hi.length) return;
  mainChart.addAreaSeries({{
    color:'rgba(0,191,255,0.06)',lineWidth:0,priceLineVisible:false,
    lastValueVisible:false,crosshairMarkerVisible:false,
    topColor:'rgba(0,191,255,0.10)',bottomColor:'rgba(0,191,255,0.02)',
  }}).setData(hi);
}});

const cs = mainChart.addCandlestickSeries({{
  upColor:'#26a69a',downColor:'#ef5350',
  borderUpColor:'#26a69a',borderDownColor:'#ef5350',
  wickUpColor:'#26a69a',wickDownColor:'#ef5350',
}});
cs.setData(candles);
cs.setMarkers(markers);

const L = (color) => ({{color,lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false}});
mainChart.addLineSeries({{...L('#FF6B35'),title:'EMA20'}}).setData(ema20Line);
mainChart.addLineSeries({{...L('#00BFFF'),title:'EMA50'}}).setData(ema50Line);
mainChart.timeScale().fitContent();

// ── 斜率副图 ──
const subChart = LightweightCharts.createChart(document.getElementById('sub'),{{
  layout:{{background:{{color:'#0d1117'}},textColor:'#e6edf3'}},
  grid:{{vertLines:{{color:'#21262d'}},horzLines:{{color:'#21262d'}}}},
  width:window.innerWidth,height:window.innerHeight*0.28,
  timeScale:{{timeVisible:true,secondsVisible:false,borderColor:'#30363d'}},
  rightPrice:{{borderColor:'#30363d',visible:true}},
}});
subChart.addLineSeries({{color:'rgba(255,255,255,0.6)',lineWidth:2,priceLineVisible:true,lastValueVisible:false,crosshairMarkerVisible:false}}).setData(zeroLine);
subChart.addAreaSeries({{topColor:'rgba(76,175,80,0.4)',bottomColor:'rgba(76,175,80,0.02)',invertFilledArea:false}}).setData(e20Pos);
subChart.addAreaSeries({{topColor:'rgba(244,67,54,0.02)',bottomColor:'rgba(244,67,54,0.4)',invertFilledArea:false}}).setData(e20Neg);
subChart.addAreaSeries({{topColor:'rgba(33,150,243,0.3)',bottomColor:'rgba(33,150,243,0.02)',invertFilledArea:false}}).setData(e50Pos);
subChart.addAreaSeries({{topColor:'rgba(255,235,59,0.02)',bottomColor:'rgba(255,235,59,0.3)',invertFilledArea:false}}).setData(e50Neg);

// ── RSI 副图 ──
const rsiChart = LightweightCharts.createChart(document.getElementById('rsi'),{{
  layout:{{background:{{color:'#0d1117'}},textColor:'#e6edf3'}},
  grid:{{vertLines:{{color:'#21262d'}},horzLines:{{color:'#21262d'}}}},
  width:window.innerWidth,height:window.innerHeight*0.18,
  timeScale:{{timeVisible:true,secondsVisible:false,borderColor:'#30363d'}},
  rightPrice:{{borderColor:'#30363d',visible:true}},
}});
rsiChart.addLineSeries({{color:'rgba(255,187,41,0.8)',lineWidth:1,priceLineVisible:false,lastValueVisible:false}}).setData(rsiLine);
rsiChart.addLineSeries({{color:'rgba(255,255,255,0.3)',lineWidth:1,priceLineVisible:false,lastValueVisible:false}}).setData(zeroLine);
// 70/30 超买超卖线（RSI专用）
const rsi70 = records.map(r => ({{time: r.date, value: 70}}));
const rsi30 = records.map(r => ({{time: r.date, value: 30}}));
rsiChart.addLineSeries({{color:'rgba(248,81,73,0.5)',lineWidth:1,priceLineVisible:false,lastValueVisible:false}}).setData(rsi70);
rsiChart.addLineSeries({{color:'rgba(63,185,80,0.5)',lineWidth:1,priceLineVisible:false,lastValueVisible:false}}).setData(rsi30);

// ── 权益对比 ──
const eqChart = LightweightCharts.createChart(document.getElementById('eq'),{{
  layout:{{background:{{color:'#0d1117'}},textColor:'#e6edf3'}},
  grid:{{vertLines:{{color:'#21262d'}},horzLines:{{color:'#21262d'}}}},
  width:window.innerWidth,height:window.innerHeight*0.20,
  timeScale:{{timeVisible:true,secondsVisible:false,borderColor:'#30363d'}},
  rightPrice:{{borderColor:'#30363d'}},
}});
eqChart.addLineSeries({{color:'#FFD700',lineWidth:2,title:'v2策略'}}).setData(eqStrat);
eqChart.addLineSeries({{color:'#58a6ff',lineWidth:1,title:'B&H'}}).setData(eqBH);
eqChart.timeScale().fitContent();

// 同步
const sync = (a, b, c) => {{
  a.timeScale().subscribeVisibleLogicalRangeChange(r => {{ if (r) {{ b.timeScale().setVisibleLogicalRange(r); c.timeScale().setVisibleLogicalRange(r); }} }});
  b.timeScale().subscribeVisibleLogicalRangeChange(r => {{ if (r) {{ a.timeScale().setVisibleLogicalRange(r); c.timeScale().setVisibleLogicalRange(r); }} }});
  c.timeScale().subscribeVisibleLogicalRangeChange(r => {{ if (r) {{ a.timeScale().setVisibleLogicalRange(r); b.timeScale().setVisibleLogicalRange(r); }} }});
}};
sync(mainChart, subChart, eqChart);
sync(subChart, rsiChart, eqChart);

window.addEventListener('resize',() => {{
  mainChart.resize(window.innerWidth, window.innerHeight*0.34);
  subChart.resize(window.innerWidth, window.innerHeight*0.28);
  rsiChart.resize(window.innerWidth, window.innerHeight*0.18);
  eqChart.resize(window.innerWidth, window.innerHeight*0.20);
}});
</script>
</body>
</html>"""


# ═══════════════════════════════════════
#  主程序
# ═══════════════════════════════════════

def main():
    print('=' * 60)
    print('  SPYTREND v3 — 牛市模式 + 空头能量评估体系回测')
    print('=' * 60)

    records = load_data()
    print(f'  数据: {len(records)} 天 | {records[0]["date"]} ~ {records[-1]["date"]}')

    INITIAL = 10_000.0
    strat_curve, strat_trades = backtest_v3(records, INITIAL)
    bh_curve,    bh_trades    = buy_and_hold(records, INITIAL)

    strat = calc_stats(strat_curve, strat_trades, INITIAL)
    bh    = calc_stats(bh_curve,    bh_trades,    INITIAL)

    excess = (strat['final'] - bh['final']) / bh['final']

    print(f'\n  策略最终权益: {fmt_money(strat["final"])}  ({fmt_pct(strat["cagr"])}/年)')
    print(f'  B&H 最终权益:  {fmt_money(bh["final"])}  ({fmt_pct(bh["cagr"])}/年)')
    print(f'  超额收益:      {fmt_pct(excess)}  {"✅ 跑赢" if excess > 0 else "❌ 跑输"}')
    print(f'  最大回撤:      {fmt_pct(strat["max_dd"])}  |  胜率 {strat["win_rate"]*100:.0f}%  |  盈亏比 {strat["pf"]:.2f}×')
    print(f'  买 {strat["n_buys"]} 卖 {strat["n_sells"]}')

    # 空头能量分布
    es = strat.get('energy_stats', {})
    print(f'\n  空头能量分布:')
    for k, v in es.items():
        print(f'    {k}: {v["count"]}次')

    print(f'\n  买卖明细:')
    n = 0
    for t in strat_trades:
        if t['a'] == 'BUY':
            n += 1
            be = t.get('bear_energy', {})
            e  = be.get('energy', '') if isinstance(be, dict) else ''
            icon = {'strong': '⚠️', 'medium': '🔶', 'weak': '✅'}.get(e, '❓')
            print(f'  {t["d"]}  🟢买  ${t["px"]:.2f}  [{n} {t.get("src","")}] {icon}空头:{e}')
        else:
            pnl = f" ({t.get('pnl',0)*100:+.1f}%)"
            print(f'  {t["d"]}  🔴卖  ${t["px"]:.2f}  [{n}{t.get("src","")}]{pnl}')
            n -= 1

    # HTML
    html = build_html(records, strat_trades, strat, bh, INITIAL)
    with open(OUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'\n  ✅ HTML: {OUT_HTML}')

    # JSON
    result = {
        'strategy_final': strat['final'],
        'bh_final':       bh['final'],
        'excess':        excess,
        'strat_cagr':    strat['cagr'],
        'bh_cagr':       bh['cagr'],
        'strat_max_dd':  strat['max_dd'],
        'bh_max_dd':     bh['max_dd'],
        'n_buys':        strat['n_buys'],
        'n_sells':       strat['n_sells'],
        'win_rate':      strat['win_rate'],
        'avg_w':         strat['avg_w'],
        'avg_l':         strat['avg_l'],
        'profit_factor': strat['pf'],
        'energy_stats':  strat.get('energy_stats', {}),
        'trades':        strat_trades,
    }
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f'  ✅ JSON: {OUT_JSON}')

    # 空头能量明细
    bear_trades = [
        {**t, 'bear_energy': t.get('bear_energy', {})} | {'exit_energy': t.get('exit_energy', {})}
        for t in strat_trades if t['a'] == 'BUY'
    ]
    with open(OUT_BEAR, 'w', encoding='utf-8') as f:
        json.dump(bear_trades, f, ensure_ascii=False, indent=2)
    print(f'  ✅ 空头能量明细: {OUT_BEAR}')


if __name__ == '__main__':
    main()
