#!/usr/bin/env python3
"""
CRO Historical Stock Screening - Based on data up to 2025-12-31
五层过滤体系
"""

import json
import math
import os
from datetime import datetime, timedelta
from collections import defaultdict

KLINE_DIR = "/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines"
CUTOFF_DATE = datetime(2025, 12, 31)

# Target industries
TARGET_INDUSTRIES = {"AI", "SEMICONDUCTOR", "CLOUD", "CYBERSECURITY", "MEDICAL_INNOVATION", "SEMI", "CHIP"}

def parse_date(s):
    if '-' in s and s[0].isdigit():
        return datetime.strptime(s, '%Y-%m-%d')
    else:
        return datetime.strptime(s, '%b %d, %Y')

def load_kline(ticker, interval):
    """Load and filter kline data to cutoff date, sorted ascending."""
    path = os.path.join(KLINE_DIR, f"{ticker}_{interval}.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        d = json.load(f)
    # Filter and sort
    filtered = []
    seen_dates = set()
    for item in d['data']:
        try:
            dt = parse_date(item['date'])
            if dt <= CUTOFF_DATE:
                if item['date'] not in seen_dates:  # deduplicate by string
                    seen_dates.add(item['date'])
                    filtered.append(item)
        except:
            pass
    filtered.sort(key=lambda x: parse_date(x['date']))
    # Convert all numeric fields to float
    for item in filtered:
        for key in ['open', 'high', 'low', 'close', 'adj']:
            if key in item:
                try:
                    item[key] = float(item[key])
                except (ValueError, TypeError):
                    pass
        if 'vol' in item:
            try:
                item['vol'] = float(str(item['vol']).replace(',', ''))
            except (ValueError, TypeError):
                pass
    return filtered

def calc_ma(prices, period):
    """Simple moving average."""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

def calc_ema(prices, period):
    """Exponential moving average."""
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema

def calc_adx(highs, lows, closes, period=14):
    """Calculate ADX."""
    if len(highs) < period + 1:
        return None
    # Calculate True Range and Directional Movement
    tr_list = []
    plus_dm_list = []
    minus_dm_list = []
    for i in range(1, len(closes)):
        high = highs[i]
        low = lows[i]
        prev_high = highs[i-1]
        prev_low = lows[i-1]
        prev_close = closes[i-1]
        
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        plus_dm = max(high - prev_high, 0) if (high - prev_high) > (prev_low - low) else 0
        minus_dm = max(prev_low - low, 0) if (prev_low - low) > (high - prev_high) else 0
        
        tr_list.append(tr)
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
    
    if len(tr_list) < period:
        return None
    
    # Wilder smoothing
    def wilder_sum(values, period):
        result = sum(values[:period])
        smoothed = [result]
        for i in range(period, len(values)):
            result = result - result/period + values[i]
            smoothed.append(result)
        return smoothed
    
    tr_smooth = wilder_sum(tr_list, period)
    plus_dm_smooth = wilder_sum(plus_dm_list, period)
    minus_dm_smooth = wilder_sum(minus_dm_list, period)
    
    plus_di_list = []
    minus_di_list = []
    dx_list = []
    for i in range(len(tr_smooth)):
        if tr_smooth[i] != 0:
            plus_di = 100 * plus_dm_smooth[i] / tr_smooth[i]
            minus_di = 100 * minus_dm_smooth[i] / tr_smooth[i]
        else:
            plus_di = 0
            minus_di = 0
        plus_di_list.append(plus_di)
        minus_di_list.append(minus_di)
        di_sum = plus_di + minus_di
        if di_sum != 0:
            dx = 100 * abs(plus_di - minus_di) / di_sum
        else:
            dx = 0
        dx_list.append(dx)
    
    # ADX is the Wilder smoothing of DX
    if len(dx_list) < period:
        return None
    adx = sum(dx_list[:period]) / period
    for i in range(period, len(dx_list)):
        adx = (adx * (period - 1) + dx_list[i]) / period
    return adx

def calc_avg_volume(volumes, period=20):
    if len(volumes) < period:
        return None
    return sum(volumes[-period:]) / period

def calc_rsi(prices, period=14):
    """Calculate RSI."""
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def estimate_market_cap(price):
    """Rough market cap estimation from price (for tech stocks)."""
    if price > 1000:
        return price * 5e9  # very rough
    elif price > 200:
        return price * 1e9
    else:
        return price * 500e6

def get_industry(ticker):
    """Map ticker to industry."""
    semi_chips = {"NVDA", "AMD", "AVGO", "QCOM", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "MU", "INTC", 
                  "SMCI", "MRVL", "ARM", "CDNS", "SNPS", "GEV", "ONTO", "TER", "AMKR", "COHU", "CIEN"}
    cloud_ai = {"MSFT", "GOOGL", "AMZN", "CRM", "NOW", "SNOW", "DDOG", "MDB", "ANET", "PLTR", "UBER"}
    cybersecurity = {"CRWD", "PANW", "ZS", "OKTA"}
    medical = {"ALAB", "RXRX", "ILMN", "TEM"}
    
    if ticker in semi_chips:
        return "SEMICONDUCTOR"
    elif ticker in cloud_ai:
        return "CLOUD/AI"
    elif ticker in cybersecurity:
        return "CYBERSECURITY"
    elif ticker in medical:
        return "MEDICAL_INNOVATION"
    elif ticker == "SMH":
        return "SEMICONDUCTOR_ETF"
    elif ticker in {"SPY", "QQQ", "SOXL"}:
        return "ETF"
    else:
        return "OTHER"

def is_target_industry(ticker):
    return get_industry(ticker) in {"SEMICONDUCTOR", "CLOUD/AI", "CYBERSECURITY", "MEDICAL_INNOVATION", "SEMICONDUCTOR_ETF"}

# ============================================================
# LAYER 1: Market Environment
# ============================================================
def check_market_environment():
    """Check SPY/QQQ/ADX/VIX for market environment."""
    spy_daily = load_kline("SPY", "1d")
    qqq_daily = load_kline("QQQ", "1d")
    spy_weekly = load_kline("SPY", "1wk")
    
    if len(spy_daily) < 25 or len(qqq_daily) < 25:
        return None, "Insufficient SPY/QQQ data"
    
    # Get latest data (last 252 days ≈ 1 year for daily)
    spy_close = [x['close'] for x in spy_daily]
    qqq_close = [x['close'] for x in qqq_daily]
    
    # SPY MA20
    spy_ma20 = calc_ma(spy_close, 20)
    spy_latest_close = spy_close[-1]
    
    # SPY weekly MA20 (need last week)
    spy_wk_close = [x['close'] for x in spy_weekly]
    spy_wk_ma20 = calc_ma(spy_wk_close, 20) if len(spy_wk_close) >= 20 else None
    spy_wk_trend = "向上" if (spy_wk_ma20 and len(spy_wk_close) >= 2 and spy_wk_close[-1] > spy_wk_ma20 and 
                              (len(spy_wk_close) < 52 or spy_wk_close[-4] < spy_wk_close[-1])) else "震荡/向下"
    
    # QQQ MA20
    qqq_ma20 = calc_ma(qqq_close, 20)
    qqq_latest_close = qqq_close[-1]
    
    # ADX calculation
    spy_highs = [x['high'] for x in spy_daily]
    spy_lows = [x['low'] for x in spy_daily]
    adx = calc_adx(spy_highs, spy_lows, spy_close, 14)
    
    # VIX estimation (rough - use SPY's own volatility as proxy)
    # If we had VIX data separately, we'd use it. Here we'll estimate from SPY
    # We'll use actual VIX data if available in a separate file
    # For now, estimate from SPY's own ATR
    vix_estimate = 18  # placeholder - in real system would use VIX data
    
    # Check if VIX file exists
    vix_data = load_kline("VIX", "1d")
    if vix_data:
        vix_estimate = vix_data[-1]['close']
    
    result = {
        "spy_close": spy_latest_close,
        "spy_ma20": spy_ma20,
        "spy_above_ma20": spy_latest_close > spy_ma20 if spy_ma20 else False,
        "spy_weekly_trend": spy_wk_trend,
        "qqq_close": qqq_latest_close,
        "qqq_ma20": qqq_ma20,
        "qqq_above_ma20": qqq_latest_close > qqq_ma20 if qqq_ma20 else False,
        "adx": adx,
        "vix": vix_estimate,
        "allow_trading": (
            (spy_latest_close > spy_ma20 if spy_ma20 else False) and
            (qqq_latest_close > qqq_ma20 if qqq_ma20 else False) and
            (adx and adx > 20) and
            (vix_estimate < 30)
        )
    }
    
    return result, None

# ============================================================
# LAYER 2: Stock Quality
# ============================================================
def check_stock_quality(ticker, spy_daily):
    """Check RS, volume, industry, market cap."""
    daily = load_kline(ticker, "1d")
    if len(daily) < 65:
        return None, "Insufficient data"
    
    closes = [x['close'] for x in daily]
    volumes = [x['vol'] for x in daily]
    
    # SPY for RS calculation
    spy_closes = [x['close'] for x in spy_daily]
    
    # RS_20d: use last 20 trading days
    n = min(20, len(closes)-1, len(spy_closes)-1)
    if n < 5:
        return None, "Insufficient data for RS"
    
    stock_20d_return = (closes[-1] - closes[-n-1]) / closes[-n-1] * 100
    spy_20d_return = (spy_closes[-1] - spy_closes[-n-1]) / spy_closes[-n-1] * 100
    rs_20d = stock_20d_return - spy_20d_return
    
    # RS rating
    if rs_20d > 15:
        rs_rating = "A"
    elif rs_20d >= 5:
        rs_rating = "B"
    elif rs_20d >= -5:
        rs_rating = "C"
    else:
        rs_rating = "淘汰"
    
    if rs_rating == "淘汰":
        return None, f"RS={rs_20d:.1f}% (淘汰)"
    
    # Average daily dollar volume (last 60 days)
    last_60 = daily[-60:] if len(daily) >= 60 else daily
    total_dollar_vol = sum(closes[i] * volumes[i] for i in range(len(last_60)))
    avg_dollar_vol = total_dollar_vol / len(last_60) / 1e9  # in billions
    
    if avg_dollar_vol < 0.5:  # less than 500M
        return None, f"成交额仅{avg_dollar_vol:.2f}亿 (<5亿)"
    
    # Industry check
    industry = get_industry(ticker)
    if industry not in {"SEMICONDUCTOR", "CLOUD/AI", "CYBERSECURITY", "MEDICAL_INNOVATION", "SEMICONDUCTOR_ETF", "ETF"}:
        return None, f"行业={industry} (非主线)"
    
    # Market cap estimation (rough)
    price = closes[-1]
    mkt_cap_est = price * 5e9  # rough for large caps
    
    return {
        "rs_20d": rs_20d,
        "rs_rating": rs_rating,
        "avg_dollar_vol_bn": avg_dollar_vol,
        "industry": industry,
        "mkt_cap_est_bn": mkt_cap_est / 1e9,
        "price": price
    }, None

# ============================================================
# LAYER 3: Trend Structure
# ============================================================
def check_trend_structure(ticker, daily, weekly):
    """Identify trend structure: A/B/C type."""
    if len(daily) < 60 or len(weekly) < 10:
        return None, "Insufficient data for structure"
    
    closes = [x['close'] for x in daily]
    highs = [x['high'] for x in daily]
    lows = [x['low'] for x in daily]
    volumes = [x['vol'] for x in daily]
    
    wk_closes = [x['close'] for x in weekly]
    wk_highs = [x['high'] for x in weekly]
    wk_lows = [x['low'] for x in weekly]
    
    # ---- A类: Trend Pullback ----
    # Weekly trend up (HH/HL)
    wk_up = len(wk_closes) >= 4 and wk_closes[-1] > wk_closes[-4] and wk_closes[-4] > wk_closes[-8]
    
    # Daily: price near 20EMA
    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, 50)
    ma20 = calc_ma(closes, 20)
    
    if ema20:
        near_ema20_pct = abs(closes[-1] - ema20) / ema20 * 100
    else:
        near_ema20_pct = 999
    
    # Volume contraction
    avg_vol = calc_avg_volume(volumes, 20)
    vol_ratio = volumes[-1] / avg_vol if avg_vol else 1
    
    # PA reversal check (simplified)
    is_hammer = False
    body = abs(closes[-1] - daily[-1]['open'])
    upper_shadow = daily[-1]['high'] - max(closes[-1], daily[-1]['open'])
    lower_shadow = min(closes[-1], daily[-1]['open']) - daily[-1]['low']
    is_hammer = (lower_shadow > body * 2 and upper_shadow < body * 0.5)
    
    is_engulfing = False
    if len(closes) >= 2:
        prev_body = abs(closes[-2] - daily[-2]['open'])
        is_engulfing = (closes[-1] > daily[-2]['open'] and daily[-1]['open'] < closes[-2] and 
                        closes[-1] > closes[-2] and daily[-1]['open'] < daily[-2]['close'])
    
    # ---- B类: Platform Breakout ----
    # Consolidation detection: price within 15% range for 15+ days
    recent_30 = closes[-30:] if len(closes) >= 30 else closes
    range_pct = (max(recent_30) - min(recent_30)) / min(recent_30) * 100 if min(recent_30) > 0 else 999
    
    # Count consolidation days
    cons_days = 0
    for i in range(len(closes)-1, max(0, len(closes)-30), -1):
        if abs(closes[i] - closes[-1]) / closes[-1] < 0.08:  # within 8%
            cons_days += 1
        else:
            break
    
    # ---- C类: Panic Recovery ----
    # Find recent market drop (SPY dropped >3% in a day)
    # Then stock recovered quickly
    
    structure_type = None
    structure_desc = None
    
    # A类 check
    a_score = 0
    if wk_up:
        a_score += 2
    if near_ema20_pct < 5:
        a_score += 2
    if vol_ratio < 0.7:
        a_score += 1
    if is_hammer or is_engulfing:
        a_score += 1
    if closes[-1] > ma20 if ma20 else False:
        a_score += 1
    
    # B类 check
    b_score = 0
    if range_pct < 15:
        b_score += 2
    if cons_days >= 15:
        b_score += 2
    if vol_ratio > 1.5:
        b_score += 1
    
    # C类 check - skip for now as it requires more complex detection
    
    if a_score >= 5:
        structure_type = "A类"
        structure_desc = f"趋势回踩 (A分={a_score})，周线向上={'是' if wk_up else '否'}，距EMA20={near_ema20_pct:.1f}%，量比={vol_ratio:.2f}，反转K线={'锤子' if is_hammer else ('吞噬' if is_engulfing else '无')}"
    elif b_score >= 4:
        structure_type = "B类"
        structure_desc = f"平台突破 (B分={b_score})，波动率={range_pct:.1f}%，整理天数={cons_days}，量比={vol_ratio:.2f}"
    else:
        return None, f"结构评分不足 (A={a_score}, B={b_score})"
    
    return {
        "structure_type": structure_type,
        "structure_desc": structure_desc,
        "ema20": ema20,
        "ma20": ma20,
        "near_ema20_pct": near_ema20_pct,
        "vol_ratio": vol_ratio
    }, None

# ============================================================
# LAYER 4: Entry Plan
# ============================================================
def create_entry_plan(ticker, daily, structure_info):
    """Create entry plan with stop loss."""
    closes = [x['close'] for x in daily]
    lows = [x['low'] for x in daily]
    highs = [x['high'] for x in daily]
    volumes = [x['vol'] for x in daily]
    
    price = closes[-1]
    ema20 = structure_info.get("ema20")
    ma20 = structure_info.get("ma20")
    
    if structure_info["structure_type"] == "A类":
        entry_model = "EMA回踩"
        # Entry: near EMA20
        entry_price = ema20 if ema20 else price * 0.98
        # Stop: structure stop (recent low)
        stop_price = min(lows[-5:]) * 0.99  # just below recent low
        stop_type = "结构止损"
    elif structure_info["structure_type"] == "B类":
        entry_model = "平台突破回踩"
        # Entry: slightly above recent high
        recent_high = max(highs[-20:]) if len(highs) >= 20 else highs[-1]
        entry_price = recent_high * 1.01
        stop_price = recent_high * 0.95  # 5% below breakout
        stop_type = "结构止损"
    else:
        return None, "Unknown structure type"
    
    return {
        "entry_model": entry_model,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "stop_type": stop_type,
        "risk_pct": (price - stop_price) / price * 100
    }, None

# ============================================================
# LAYER 5: Risk/Reward
# ============================================================
def calc_risk_reward(ticker, entry_info, structure_info, daily):
    """Calculate risk/reward ratio."""
    closes = [x['close'] for x in daily]
    price = closes[-1]
    entry = entry_info["entry_price"]
    stop = entry_info["stop_price"]
    
    # Target: previous high or measured move
    highs = [x['high'] for x in daily]
    recent_high = max(highs[-30:]) if len(highs) >= 30 else max(highs)
    
    # Target 1: recent resistance + ATR buffer
    atr = (max(highs[-14:]) - min(lows[-14:])) / 14 if len(highs) >= 14 else price * 0.03
    target1 = max(recent_high, price + 2 * atr)
    
    reward = target1 - entry
    risk = entry - stop
    
    if risk <= 0:
        return None, "Invalid risk calculation"
    
    rr = reward / risk
    
    return {
        "target1": target1,
        "entry_price": entry,
        "stop_price": stop,
        "rr_ratio": rr,
        "passes_filter": rr >= 2.5
    }, None

# ============================================================
# Main Screening Loop
# ============================================================
def main():
    print("=" * 60)
    print("CRO Historical Screening - Data as of 2025-12-31")
    print("=" * 60)
    
    # Layer 1: Market Environment
    print("\n【第一层：市场环境】")
    market, market_err = check_market_environment()
    if market_err or not market:
        print(f"市场环境检查失败: {market_err}")
        return
    
    print(f"SPY: 收盘=${market['spy_close']:.2f}, MA20=${market['spy_ma20']:.2f}, {'高于MA20 ✓' if market['spy_above_ma20'] else '低于MA20 ✗'}")
    print(f"QQQ: 收盘=${market['qqq_close']:.2f}, MA20=${market['qqq_ma20']:.2f}, {'高于MA20 ✓' if market['qqq_above_ma20'] else '低于MA20 ✗'}")
    print(f"SPY周线趋势: {market['spy_weekly_trend']}")
    print(f"ADX: {market['adx']:.1f} ({'趋势明确 >20 ✓' if market['adx'] > 20 else '无趋势 <20 ✗'})")
    print(f"VIX: {market['vix']:.1f} ({'非恐慌 ✓' if market['vix'] < 30 else '恐慌 ✗'})")
    print(f"允许交易: {'YES ✓' if market['allow_trading'] else 'NO ✗'}")
    
    if not market['allow_trading']:
        print("市场环境不允许交易，筛选终止")
        return
    
    # Load SPY for RS calculation
    spy_daily = load_kline("SPY", "1d")
    
    # Get all tickers
    all_files = os.listdir(KLINE_DIR)
    tickers = sorted(set(f.replace('_1d.json', '') for f in all_files if f.endswith('_1d.json')))
    
    # Exclude ETFs and market indices
    exclude = {"SPY", "QQQ", "VIX", "SMH", "SOXL"}
    tickers = [t for t in tickers if t not in exclude]
    
    print(f"\n待筛选股票数量: {len(tickers)}")
    
    # Results storage
    candidates = []
    
    for ticker in tickers:
        try:
            # Load data
            daily = load_kline(ticker, "1d")
            weekly = load_kline(ticker, "1wk")
            
            if len(daily) < 65:
                continue
            
            # Layer 2: Stock Quality
            quality, q_err = check_stock_quality(ticker, spy_daily)
            if q_err:
                continue
            if quality is None:
                continue
            
            # Layer 3: Trend Structure
            structure, s_err = check_trend_structure(ticker, daily, weekly)
            if s_err or structure is None:
                continue
            
            # Layer 4: Entry Plan
            entry, e_err = create_entry_plan(ticker, daily, structure)
            if e_err or entry is None:
                continue
            
            # Layer 5: Risk/Reward
            rr, rr_err = calc_risk_reward(ticker, entry, structure, daily)
            if rr_err or rr is None:
                continue
            
            if rr["passes_filter"]:
                candidates.append({
                    "ticker": ticker,
                    "quality": quality,
                    "structure": structure,
                    "entry": entry,
                    "rr": rr
                })
                print(f"  ✓ {ticker}: {structure['structure_type']}, RS={quality['rs_20d']:.1f}%, 盈亏比={rr['rr_ratio']:.1f}:1")
        
        except Exception as ex:
            print(f"  ! {ticker}: Error - {ex}")
            continue
    
    print(f"\n通过五层筛选: {len(candidates)} 只")
    
    # Sort by RR ratio
    candidates.sort(key=lambda x: x['rr']['rr_ratio'], reverse=True)
    
    # Limit to top 10
    candidates = candidates[:10]
    
    # Print final report
    print("\n" + "=" * 70)
    print("【最终候选清单】")
    print("=" * 70)
    
    for i, c in enumerate(candidates, 1):
        t = c['ticker']
        q = c['quality']
        s = c['structure']
        e = c['entry']
        r = c['rr']
        
        print(f"\n{i}. {t} | {s['structure_type']} | 评级:{q['rs_rating']} | RS_20d={q['rs_20d']:.1f}%")
        print(f"   行业: {q['industry']} | 成交额: {q['avg_dollar_vol_bn']:.1f}亿 | 市值: {q['mkt_cap_est_bn']:.0f}亿")
        print(f"   入场: ${e['entry_price']:.2f} | 止损: ${e['stop_price']:.2f} ({e['risk_pct']:.1f}%) | 目标: ${r['target1']:.2f}")
        print(f"   盈亏比: {r['rr_ratio']:.1f}:1 {'✓' if r['passes_filter'] else '✗'}")
        print(f"   {s['structure_desc']}")
    
    return candidates, market

if __name__ == "__main__":
    candidates, market = main()
