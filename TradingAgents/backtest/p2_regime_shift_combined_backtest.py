#!/usr/bin/env python3
"""
P2 · Regime × Dangerous Shift 综合回测
=========================================
测试 8 种策略组合，找到趋势健康度 + 变盘信号的最优结合方式

回测区间：2020-01-02 → 2026-05-13
数据：SPY 日K（Yahoo Finance via CDP）

策略列表：
  S0  基准：买入持有 SPY
  S1  Regime Only（分数阈值）
  S2  Dangerous Shift Only（信号过滤）
  S3  Regime + Shift_AND（两者同时满足才入场）
  S4  Regime + Shift_OR（两者任一满足即入场）
  S5  Regime入口 + Shift止损（Shift作为止损信号）
  S6  Regime分档仓位（Regime分数决定仓位）
  S7  Regime分档仓位 + Shift清仓（Shift≤1时降仓）

入场规则（基准）：
  - 5级 Regime >= 6 分（🐂+🚀）入场
  - 分档仓位：6-6.9→50% | 7-7.9→75% | 8+→100%

出场规则（基准）：
  - Regime < 4 清仓
  - STOP LOSS: 从高点回撤 10%
  - TAKE PROFIT: 从低点反弹 20%（不做，仅记录）

参数搜索空间：
  - regime_enter: [4.0, 5.0, 5.5, 6.0, 6.5]
  - regime_exit:  [3.0, 3.5, 4.0, 4.5]
  - shift_filter: [True, False]
  - stop_loss:    [0.08, 0.10, 0.15]

输出：
  - 各策略收益曲线（CSV）
  - 最优参数组合
  - HTML 报告
"""

import json, math, sys, warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from collections import defaultdict

warnings.filterwarnings("ignore")

# ── 路径 ────────────────────────────────────────────────────────────────────
PROJ    = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析")
KLINES  = PROJ / "中间过程" / "klines"
OUTPUT  = PROJ / "backtest"
OUTPUT.mkdir(exist_ok=True)

sys.path.insert(0, str(PROJ / "fintech" / "p1" / "features"))
sys.path.insert(0, str(PROJ / "fintech" / "p2"))

# ── 技术指标 ────────────────────────────────────────────────────────────────

def ema(closes, period):
    if len(closes) < period:
        return [sum(closes)/len(closes)] * len(closes) if closes else []
    k = 2.0 / (period + 1)
    out = [None] * (period - 1)
    out.append(sum(closes[:period]) / period)
    for i in range(period, len(closes)):
        out.append(closes[i] * k + out[-1] * (1 - k))
    return out


def sma(closes, period):
    out = []
    for i in range(len(closes)):
        out.append(sum(closes[max(0,i-period+1):i+1]) / min(period, i+1))
    return out


def rsi(closes, period=14):
    if len(closes) < period + 2:
        return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0.0 for d in deltas[-period:]]
    ag = sum(gains) / period
    al = sum(losses) / period
    return 100.0 if al == 0.0 else 100.0 - (100.0 / (1.0 + ag / al))


def atr(highs, lows, closes, period=14):
    if len(closes) < 2:
        return 0.0
    trs = [max(highs[i]-lows[i],
                abs(highs[i]-closes[i-1]),
                abs(lows[i]-closes[i-1]))
           for i in range(1, len(closes))]
    return sum(trs[-period:]) / min(period, len(trs))


def bollinger_width(closes, period=20):
    if len(closes) < period:
        return None
    recent = closes[-period:]
    m = sum(recent) / period
    std = math.sqrt(sum((c-m)**2 for c in recent) / period)
    return std / m


def adx(highs, lows, closes, period=14):
    """简化 ADX 计算"""
    if len(closes) < period + 2:
        return 20.0
    trs, p_dm, m_dm = [], [], []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        pdm = max(highs[i]-highs[i-1], 0)
        mdm = max(lows[i-1]-lows[i], 0)
        trs.append(tr); p_dm.append(pdm); m_dm.append(mdm)
    if len(trs) < period:
        return 20.0
    tr_s = sum(trs[-period:])
    p_s  = sum(p_dm[-period:])
    m_s  = sum(m_dm[-period:])
    if tr_s == 0:
        return 20.0
    p_di = (p_s / tr_s) * 100
    m_di = (m_s / tr_s) * 100
    dx = abs(p_di - m_di) / (p_di + m_di) * 100 if (p_di + m_di) > 0 else 0
    return dx


# ── K线加载 ────────────────────────────────────────────────────────────────

def load_klines(ticker):
    for suffix in ("_1d.json", ".json"):
        fpath = KLINES / f"{ticker}{suffix}"
        if fpath.exists():
            try:
                with open(fpath) as f:
                    d = json.load(f)
                data = d.get("data", d) if isinstance(d, dict) else d
                while isinstance(data, dict):
                    data = data.get("data", [])
                return {
                    "dates":   [r["date"] for r in data if r.get("close")],
                    "closes":  [float(r["close"]) for r in data if r.get("close")],
                    "highs":   [float(r["high"])  for r in data if r.get("high")],
                    "lows":    [float(r["low"])   for r in data if r.get("low")],
                    "volumes": [float(r.get("volume", r.get("vol", 0))) for r in data if r.get("close")],
                }
            except Exception:
                pass
    return None


def get_idx(dates, target):
    """在 dates 中找 target 对应的 index（向前找最近的交易日）"""
    if target in dates:
        return dates.index(target)
    dt = datetime.strptime(target, "%Y-%m-%d")
    for i in range(1, 7):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        if d in dates:
            return dates.index(d)
    return -1


# ── P2 Regime 计算 ─────────────────────────────────────────────────────────

def calc_regime_score(spy, qqq, vix_closes, idx):
    """
    计算 P2 Regime 评分（0-10），逐日版，不依赖 P1 模块
    """
    c   = spy["closes"][:idx+1]
    h   = spy["highs"][:idx+1]
    l   = spy["lows"][:idx+1]
    d   = spy["dates"][:idx+1]

    if len(c) < 60:
        return 5.0

    # ── 因子1: 广度（Above20EMA 估算）─────────────────────────────────
    ema20 = ema(c, 20)
    above_20 = sum(1 for e in ema20[-20:] if e is not None and e < c[len(c)-20:][ema20[-20:].index(e)]) / 20
    # 简化：用 SPY 自身在 20 日区间的高度代替广度
    low_20  = min(c[-20:])
    high_20 = max(c[-20:])
    price_range = high_20 - low_20
    if price_range > 0:
        pos_in_range = (c[-1] - low_20) / price_range
        above_est = max(0.1, min(0.95, 0.1 + 0.8 * pos_in_range))
    else:
        above_est = 0.5

    # ema20 ratio
    e20 = ema20[-1]
    if e20 and e20 > 0:
        ema_ratio = c[-1] / e20
        above_est2 = min(0.95, max(0.1, (ema_ratio - 0.02) ** 4 * 0.5 + 0.5 - max(0, ema_ratio - 1) * 2))
        above_est = 0.5 * above_est + 0.5 * above_est2

    # 广度评分 (0-30)
    if above_est > 0.70:    breadth = 30
    elif above_est > 0.55:  breadth = 20
    elif above_est > 0.40:  breadth = 10
    else:                   breadth = -20

    # ── 因子2: 领导力（用 QQQ 代替）───────────────────────────────────
    if qqq and idx < len(qqq["closes"]):
        qc = qqq["closes"][:idx+1]
        q_ema20 = ema(qc, 20)
        q_ema50 = ema(qc, 50)
        leadership = 0
        if q_ema20[-1] and q_ema50[-1] and q_ema20[-1] > q_ema50[-1]:
            leadership += 12
        if q_ema20[-1] and q_ema20[-1] > qc[-1] * 0.95:
            leadership += 8
        if len(qc) >= 20 and qc[-1] > qc[-20]:
            leadership += 5
        leadership = min(25, leadership)
    else:
        leadership = 10

    # ── 因子3: 波动率（VIX）────────────────────────────────────────────
    vix_val = vix_closes[-1] if vix_closes else 20
    bbw = bollinger_width(c, 20) or 0.08

    if vix_val < 15:       vix_score = 10
    elif vix_val < 20:     vix_score = 8
    elif vix_val < 25:     vix_score = 5
    elif vix_val < 30:     vix_score = 3
    else:                   vix_score = 0

    if bbw < 0.05:         bb_score = 10
    elif bbw < 0.08:       bb_score = 7
    elif bbw < 0.12:       bb_score = 5
    else:                   bb_score = 3

    volatility = vix_score + bb_score

    # ── 因子4: 流动性（QQQ/SPY 比值）──────────────────────────────────
    if qqq and idx >= 20:
        ratio_now = qqq["closes"][-1] / spy["closes"][-1]
        ratio_20d = qqq["closes"][-21] / spy["closes"][-21]
        chg = (ratio_now / ratio_20d - 1) * 100
        if chg > 3:    liq = 15
        elif chg > 1: liq = 12
        elif chg > 0: liq = 9
        elif chg > -1.5: liq = 6
        else:          liq = 3
    else:
        liq = 7

    # ── 因子5: 价格结构（ADX + MA 排列）───────────────────────────────
    adx_val = adx(h, l, c, 14)
    ma20 = ema(c, 20)
    ma50 = ema(c, 50)
    ma200 = ema(c, 200)

    if adx_val > 30:       adx_s = 6
    elif adx_val > 25:    adx_s = 5
    elif adx_val > 20:    adx_s = 4
    elif adx_val > 15:    adx_s = 2
    else:                  adx_s = 0

    ma_score = 0
    if ma20[-1] and ma50[-1] and ma20[-1] > ma50[-1]:
        ma_score += 2
    if ma20[-1] and ma200[-1] and ma20[-1] > ma200[-1]:
        ma_score += 2
    structure = min(4, adx_s + ma_score)

    # ── 汇总（0-10 分）────────────────────────────────────────────────
    raw = breadth + leadership + volatility + liq + structure
    max_possible = 30 + 25 + 20 + 15 + 4
    score = max(0, min(10, (raw / max_possible) * 10))

    return round(score, 2)


# ── Dangerous Shift 检测（逐日版）─────────────────────────────────────────

def calc_dangerous_shift(spy, qqq, vix_closes, idx):
    """
    计算 Dangerous Shift 评分（0-5 个条件触发）
    返回 (danger_count, signal)
    signal: SAFE(0) / WATCH(1) / WARNING(2-3) / SEVERE(4-5)
    """
    c   = spy["closes"][:idx+1]
    h   = spy["highs"][:idx+1]
    l   = spy["lows"][:idx+1]
    v   = spy["volumes"][:idx+1]
    dates = spy["dates"][:idx+1]

    if len(c) < 30:
        return 0, "SAFE"

    count = 0
    reasons = []

    # 条件1: 广度崩塌（用 SPY 自身位置估算 Above20EMA < 40%）
    ema20 = ema(c, 20)
    above_est = 0.5
    if ema20[-1] and ema20[-1] > 0:
        ratio = c[-1] / ema20[-1]
        above_est = min(0.95, max(0.05, (ratio - 0.95) * 20 + 0.5))
    if above_est < 0.40:
        count += 1
        reasons.append("BreadthCollapse")

    # 条件2: VIX 持续抬升（VIX > 25 且 5 日内无明显回落）
    if len(vix_closes) >= 5:
        v_now   = vix_closes[-1]
        v_5d_ago = vix_closes[-6] if len(vix_closes) >= 6 else vix_closes[0]
        v_peak  = max(vix_closes[-5:])
        if v_now > 25 and v_now >= v_5d_ago and v_now >= v_peak * 0.95:
            count += 1
            reasons.append("VIXRise")

    # 条件3: 高Beta先崩（用 QQQ vs SPY 判断科技/高Beta是否走弱）
    if qqq and len(qqq["closes"]) > idx >= 20:
        qc = qqq["closes"]
        spy_ret = (c[-1] / c[-20] - 1) * 100
        qqq_ret = (qc[-1] / qc[-20] - 1) * 100
        if qqq_ret < spy_ret - 3:   # QQQ 比 SPY 弱 3%+
            count += 1
            reasons.append("HighBetaCrash")

    # 条件4: 下跌放量（找最近一个下跌波段，对比成交量）
    if len(c) >= 20:
        seg_returns = [(c[-(i+1)] / c[-(i+2)] - 1) * 100 for i in range(min(19, len(c)-2))]
        decline_days = [i for i, r in enumerate(seg_returns) if r < -0.5]
        rally_days   = [i for i, r in enumerate(seg_returns) if r > 0.5]
        if decline_days and rally_days:
            avg_dec_vol = sum(v[-(i+2)] for i in decline_days[:5]) / max(1, len(decline_days[:5]))
            avg_rly_vol = sum(v[-(i+2)] for i in rally_days[:5]) / max(1, len(rally_days[:5]))
            if avg_dec_vol > avg_rly_vol * 1.3:
                count += 1
                reasons.append("VolumeWeakRally")

    # 条件5: 跌破 AVWAP（收盘 < 20日均线 × 1.02）
    ema20_arr = ema(c, 20)
    if ema20_arr[-1]:
        avwap = ema20_arr[-1] * 1.02
        if c[-1] < avwap:
            count += 1
            reasons.append("BelowAVWAP")

    # Signal
    if count >= 4:   sig = "SEVERE"
    elif count >= 2: sig = "WARNING"
    elif count >= 1: sig = "WATCH"
    else:            sig = "SAFE"

    return count, sig


# ── 策略模拟器 ────────────────────────────────────────────────────────────

def simulate_strategy(name, prices, dates, regime_scores, danger_counts,
                      regime_enter, regime_exit,
                      use_shift_filter, stop_loss,
                      position_fn):
    """
    通用策略模拟器
    position_fn(regime, shift_count) -> target_position_pct (0~1)
    """
    capital   = 100000.0
    position  = 0.0
    cash     = capital
    peak     = capital
    equity   = []
    trades   = []

    in_pos    = False
    entry_px  = 0.0
    shares    = 0

    STOP_PCT  = stop_loss

    for i in range(len(prices)):
        regime = regime_scores[i]
        shift  = danger_counts[i]
        price  = prices[i]
        date_s = dates[i]

        # 目标仓位
        target = position_fn(regime, shift, regime_enter, regime_exit, use_shift_filter)
        target = max(0.0, min(1.0, target))

        # 计算当前市值
        mkt_val = cash + shares * price

        # 止损
        if in_pos and shares > 0:
            loss_pct = (price - entry_px) / entry_px
            if loss_pct < -STOP_PCT:
                cash = shares * price
                trades.append({"date": date_s, "action": "STOP", "price": price,
                                "pnl": cash - mkt_val, "ret": loss_pct})
                shares = 0
                cash   = mkt_val
                in_pos = False

        # 再平衡
        if not in_pos:
            # 入场
            if target > 0:
                target_shares = int(mkt_val * target / price)
                if target_shares > 0:
                    shares  = target_shares
                    cash    = mkt_val - shares * price
                    entry_px = price
                    in_pos  = True
                    trades.append({"date": date_s, "action": "BUY", "price": price,
                                    "shares": shares, "target": target})
        else:
            # 出场
            if target == 0 and shares > 0:
                cash = shares * price
                pnl  = cash - (mkt_val - cash) if False else 0
                trades.append({"date": date_s, "action": "SELL", "price": price,
                                "ret": (price/entry_px - 1)*100})
                shares = 0
                in_pos = False
            elif abs(target - 1.0) < 0.01 and shares == 0:
                # 全仓入场
                target_shares = int(mkt_val / price)
                shares = target_shares
                cash   = mkt_val - shares * price
                entry_px = price
                in_pos = True
                trades.append({"date": date_s, "action": "BUY", "price": price,
                                "shares": shares, "target": target})

        # 结算
        mkt_val = cash + shares * price
        if mkt_val > peak: peak = mkt_val
        dd = (mkt_val - peak) / peak * 100

        equity.append({
            "date": date_s,
            "value": mkt_val,
            "cash": cash,
            "shares": shares,
            "position_pct": (shares * price / mkt_val) if mkt_val > 0 else 0,
            "regime": regime,
            "danger": shift,
            "drawdown": dd,
            "price": price,
        })

    # 最终结算
    if shares > 0:
        final_val = shares * prices[-1] + cash
    else:
        final_val = cash

    total_ret = (final_val / capital - 1) * 100
    n_years   = len(dates) / 252
    cagr      = ((final_val / capital) ** (1/n_years) - 1) * 100 if n_years > 0 else 0

    # 最大回撤
    vals  = [e["value"] for e in equity]
    peak  = vals[0]
    max_dd = 0
    for v in vals:
        if v > peak: peak = v
        dd = (v - peak) / peak * 100
        if dd < max_dd: max_dd = dd

    # 胜率
    rets = []
    for t in trades:
        if t["action"] == "SELL" and "ret" in t:
            rets.append(t["ret"])
    win_rate = sum(1 for r in rets if r > 0) / max(1, len(rets)) * 100

    return {
        "name": name,
        "initial": capital,
        "final": final_val,
        "total_ret": total_ret,
        "cagr": cagr,
        "max_dd": max_dd,
        "num_trades": len([t for t in trades if t["action"] in ("BUY","SELL")]),
        "num_stops": len([t for t in trades if t["action"] == "STOP"]),
        "win_rate": win_rate,
        "equity": equity,
        "trades": trades,
    }


# ── 策略定义 ──────────────────────────────────────────────────────────────

def pos_s0(regime, shift, re_enter, re_exit, filter):
    """S0: 买入持有"""
    return 1.0

def pos_s1(regime, shift, re_enter, re_exit, filter):
    """S1: Regime Only"""
    return 1.0 if regime >= re_enter else 0.0

def pos_s2(regime, shift, re_enter, re_exit, filter):
    """S2: Shift Only"""
    if filter:
        return 0.0 if shift >= 2 else 1.0
    return 1.0

def pos_s3(regime, shift, re_enter, re_exit, filter):
    """S3: Regime AND Shift（两者同时满足才入场）"""
    regime_ok = regime >= re_enter
    shift_ok  = shift <= 1 if filter else True
    return 1.0 if (regime_ok and shift_ok) else 0.0

def pos_s4(regime, shift, re_enter, re_exit, filter):
    """S4: Regime OR Shift（任一满足即入场）"""
    regime_ok = regime >= re_enter
    shift_ok  = shift <= 1 if filter else True
    return 1.0 if (regime_ok or shift_ok) else 0.0

def pos_s5(regime, shift, re_enter, re_exit, filter):
    """S5: Regime入口 + Shift动态仓位"""
    if regime < re_exit:
        return 0.0
    if regime >= re_enter:
        if shift >= 4:   return 0.0   # SEVERE → 清仓
        elif shift >= 2: return 0.25  # WARNING → 轻仓
        else:            return 1.0
    elif regime >= re_exit:
        return 0.5
    return 0.0

def pos_s6(regime, shift, re_enter, re_exit, filter):
    """S6: Regime分档仓位（无Shift过滤）"""
    if regime >= 8.0:   return 1.0
    elif regime >= 7.0: return 0.75
    elif regime >= 6.0: return 0.50
    elif regime >= 5.0: return 0.25
    elif regime >= 4.0: return 0.10
    return 0.0

def pos_s7(regime, shift, re_enter, re_exit, filter):
    """S7: Regime分档仓位 + Shift清仓"""
    base = pos_s6(regime, shift, re_enter, re_exit, filter)
    if shift >= 2:   return 0.0      # WARNING+ → 清仓
    return base


# ── 主程序 ────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("P2 · Regime × Dangerous Shift 综合回测")
    print("=" * 60)

    print("\n[1/4] 加载数据...")
    spy  = load_klines("SPY")
    qqq  = load_klines("QQQ")
    vix  = load_klines("VIX")

    if not spy:
        print("ERROR: SPY 数据不存在"); return

    # 对齐日期
    start_target = "2020-01-02"
    end_target   = "2026-05-13"

    all_dates = sorted(set(spy["dates"]))
    start_idx = next((i for i,d in enumerate(all_dates) if d >= start_target), 0)
    end_idx   = max((i for i,d in enumerate(all_dates) if d <= end_target), default=len(all_dates)-1)
    trade_dates = all_dates[start_idx : end_idx+1]

    print(f"  交易日: {trade_dates[0]} → {trade_dates[-1]} ({len(trade_dates)} 天)")

    # 建立 SPY 的 date→idx 映射
    spy_date_idx = {d: i for i, d in enumerate(spy["dates"])}

    # 对齐的收盘价序列
    prices = []
    for td in trade_dates:
        if td in spy_date_idx:
            prices.append(spy["closes"][spy_date_idx[td]])
        else:
            prices.append(prices[-1] if prices else spy["closes"][0])

    print("\n[2/4] 计算每日 Regime Score + Dangerous Shift...")
    regime_scores = []
    danger_counts = []

    # VIX 序列（按 spy 日期对齐）
    vix_date_idx = {d: i for i, d in enumerate(vix["dates"])} if vix else {}

    for td in trade_dates:
        spy_idx = spy_date_idx.get(td, -1)
        if spy_idx < 0:
            regime_scores.append(5.0)
            danger_counts.append(0)
            continue

        # VIX 对齐
        if vix and td in vix_date_idx:
            vix_c = vix["closes"][:vix_date_idx[td]+1]
        elif vix and vix["dates"]:
            # 向前找
            dt = datetime.strptime(td, "%Y-%m-%d")
            found = None
            for delta in range(1, 10):
                d2 = (dt - timedelta(days=delta)).strftime("%Y-%m-%d")
                if d2 in vix_date_idx:
                    found = vix_date_idx[d2]; break
            vix_c = vix["closes"][:found+1] if found is not None else [20.0]
        else:
            vix_c = [20.0]

        regime = calc_regime_score(spy, qqq, vix_c, spy_idx)
        danger, _ = calc_dangerous_shift(spy, qqq, vix_c, spy_idx)

        regime_scores.append(regime)
        danger_counts.append(danger)

    print(f"  Regime 均值: {sum(regime_scores)/len(regime_scores):.2f}")
    print(f"  Shift 分布: SAFE={danger_counts.count(0)}, WATCH={danger_counts.count(1)}, WARNING={danger_counts.count(2)+danger_counts.count(3)}, SEVERE={danger_counts.count(4)+danger_counts.count(5)}")

    # 统计 regime 分布
    regime_dist = defaultdict(int)
    for r in regime_scores:
        if r >= 8:   regime_dist["🚀超牛"] += 1
        elif r >= 6: regime_dist["🐂牛"]   += 1
        elif r >= 4: regime_dist["↔️震荡"] += 1
        elif r >= 2: regime_dist["🐻熊"]   += 1
        else:        regime_dist["💀大熊"] += 1
    print("  Regime 分布:", dict(regime_dist))

    print("\n[3/4] 运行策略组合...")

    # 策略参数
    strategies = [
        ("S0 基准-买入持有",      pos_s0,  0,    0,    False, 1.00),
        ("S1 RegimeOnly≥6",       pos_s1,  6.0,  4.0,  False, 0.10),
        ("S2 ShiftOnly",          pos_s2,  0,    0,    True,  0.10),
        ("S3 Reg≥6+ShiftAND",     pos_s3,  6.0,  4.0,  True,  0.10),
        ("S4 Reg≥6+ShiftOR",      pos_s4,  6.0,  4.0,  True,  0.10),
        ("S5 Reg+Shift动态仓位",  pos_s5,  6.0,  4.0,  True,  0.10),
        ("S6 Reg分档仓位",        pos_s6,  6.0,  4.0,  False, 0.10),
        ("S7 Reg分档+Shift清仓",  pos_s7,  6.0,  4.0,  True,  0.10),
        # 参数变化
        ("S1b Reg≥5.5",          pos_s1,  5.5,  3.5,  False, 0.10),
        ("S3b Reg≥5.5+ShiftAND", pos_s3,  5.5,  3.5,  True,  0.10),
        ("S6b Reg分档(Stop15%)",  pos_s6,  6.0,  4.0,  False, 0.15),
        ("S7b Reg分档+Shift(Stop15%)", pos_s7, 6.0, 4.0, True, 0.15),
    ]

    results = []
    for name, pos_fn, re, rx, flt, sl in strategies:
        r = simulate_strategy(
            name, prices, trade_dates,
            regime_scores, danger_counts,
            re, rx, flt, sl, pos_fn
        )
        results.append(r)
        print(f"  {name:<30} 收益={r['total_ret']:>7.2f}%  CAGR={r['cagr']:>6.2f}%  "
              f"回撤={r['max_dd']:>7.2f}%  交易={r['num_trades']:>4}  止损={r['num_stops']:>3}  "
              f"胜率={r['win_rate']:>5.1f}%")

    print("\n[4/4] 保存结果...")

    # 保存 equity CSV
    for r in results:
        csv_path = OUTPUT / f"combined_equity_{r['name'].split()[0]}.csv"
        with open(csv_path, "w") as f:
            f.write("date,value,cash,shares,position_pct,regime,danger,drawdown,price\n")
            for e in r["equity"]:
                f.write(f"{e['date']},{e['value']:.2f},{e['cash']:.2f},"
                        f"{e['shares']},{e['position_pct']:.4f},"
                        f"{e['regime']},{e['danger']},{e['drawdown']:.2f},{e['price']:.2f}\n")

    # 保存 summary JSON
    summary = []
    for r in results:
        summary.append({
            "name":       r["name"],
            "initial":    r["initial"],
            "final":      round(r["final"], 2),
            "total_ret":  round(r["total_ret"], 2),
            "cagr":       round(r["cagr"], 2),
            "max_dd":     round(r["max_dd"], 2),
            "num_trades": r["num_trades"],
            "num_stops": r["num_stops"],
            "win_rate":   round(r["win_rate"], 1),
        })

    with open(OUTPUT / "combined_backtest_summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # 生成 HTML 报告
    generate_html(results, trade_dates, regime_scores, danger_counts, prices)

    print("\n" + "=" * 60)
    print("回测完成！")
    print(f"报告：{OUTPUT}/combined_backtest_2020_2026.html")
    print("=" * 60)

    # 最优策略
    best = max(results, key=lambda x: x["cagr"])
    print(f"\n🏆 最优策略（按CAGR）: {best['name']}")
    print(f"   总收益: {best['total_ret']:.2f}%  CAGR: {best['cagr']:.2f}%  "
          f"最大回撤: {best['max_dd']:.2f}%  胜率: {best['win_rate']:.1f}%")


def generate_html(results, dates, regimes, dangers, prices):
    """生成 HTML 报告"""

    # 颜色
    def ret_color(v):
        return "#00c853" if v >= 0 else "#ff1744"

    rows = ""
    for r in results:
        ret_col  = ret_color(r["total_ret"])
        cagr_col = ret_color(r["cagr"])
        dd_col   = "#ff1744" if r["max_dd"] < -10 else ("#ffc107" if r["max_dd"] < -5 else "#00c853")
        rows += f"""
        <tr>
          <td><strong>{r['name']}</strong></td>
          <td class="num" style="color:{ret_col}">{r['total_ret']:+.2f}%</td>
          <td class="num" style="color:{cagr_col}">{r['cagr']:+.2f}%</td>
          <td class="num" style="color:{dd_col}">{r['max_dd']:.2f}%</td>
          <td class="num">{r['num_trades']}</td>
          <td class="num">{r['num_stops']}</td>
          <td class="num">{r['win_rate']:.1f}%</td>
          <td><span class="tag">{r['final']/r['initial']*100:.0f}</span></td>
        </tr>"""

    # Equity chart data
    import base64
    n = len(results)
    equity_json = []
    for r in results:
        eq = [[e["date"], round(e["value"], 2)] for e in r["equity"]]
        equity_json.append({"name": r["name"], "data": eq})

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>P2 · Regime × Shift 综合回测 2020-2026</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d1117;color:#e0e0e0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px}}
h1{{background:linear-gradient(135deg,#1a1a2e,#16213e);padding:20px 32px;border-bottom:2px solid #e94560;font-size:20px}}
h2{{padding:16px 32px 8px;font-size:15px;color:#9e9e9e;text-transform:uppercase;letter-spacing:1px}}
table{{width:100%;border-collapse:collapse}}
th{{background:#1c2128;color:#9e9e9e;text-align:left;padding:10px 14px;font-size:11px;text-transform:uppercase;border-bottom:2px solid #30363d}}
td{{padding:10px 14px;border-bottom:1px solid #21262d}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
tr:hover td{{background:#1c2128}}
.tag{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;background:rgba(88,166,255,0.15);color:#58a6ff}}
.kpi-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;padding:16px 32px}}
.kpi{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px;text-align:center}}
.kpi-num{{font-size:2rem;font-weight:700}}
.kpi-sub{{font-size:11px;color:#9e9e9e;margin-top:4px}}
.kpi span{{font-size:11px;color:#9e9e9e}}
#chart{{width:100%;height:400px;margin:16px 0}}
#regimeChart{{width:100%;height:200px;margin:8px 0}}
.controls{{padding:8px 32px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}}
.controls label{{font-size:12px;color:#9e9e9e}}
select,button{{background:#21262d;color:#e0e0e0;border:1px solid #30363d;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px}}
select:hover,button:hover{{background:#30363d}}
.legend{{display:flex;gap:16px;flex-wrap:wrap;padding:8px 32px}}
.legend-item{{display:flex;align-items:center;gap:6px;font-size:12px}}
.legend-dot{{width:10px;height:10px;border-radius:50%}}
.footer{{padding:16px 32px;border-top:1px solid #30363d;color:#6b7280;font-size:11px}}
</style>
</head>
<body>
<h1>P2 · Regime × Dangerous Shift 综合回测 &nbsp; 2020-01-02 → 2026-05-13</h1>

<div class="kpi-grid">
  <div class="kpi">
    <div class="kpi-num" style="color:#58a6ff">{len(results)}</div>
    <div class="kpi-sub">策略数量</div>
  </div>
  <div class="kpi">
    <div class="kpi-num" style="color:#00c853">{len(dates)}</div>
    <div class="kpi-sub">回测交易日</div>
  </div>
  <div class="kpi">
    <div class="kpi-num" style="color:#ffc107">{sum(regimes)/len(regimes):.1f}</div>
    <div class="kpi-sub">Regime 均值</div>
  </div>
  <div class="kpi">
    <div class="kpi-num" style="color:#ff1744">{min(regimes):.1f} ~ {max(regimes):.1f}</div>
    <div class="kpi-sub">Regime 范围</div>
  </div>
</div>

<h2>一、策略绩效对比</h2>
<table>
<thead><tr>
  <th>策略</th><th>总收益</th><th>CAGR</th><th>最大回撤</th>
  <th>交易次数</th><th>止损次数</th><th>胜率</th><th>终值指数</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>

<h2>二、净值曲线</h2>
<div class="controls">
  <label>显示策略：</label>
  <select id="strategySelect" multiple size="4">
""" + "".join(f'<option value="{i}" selected>{r["name"]}</option>' for i, r in enumerate(results)) + """
  </select>
  <button onclick="resetZoom()">重置缩放</button>
</div>
<div class="legend" id="chartLegend"></div>
<div id="chart"></div>

<h2>三、每日 Regime Score + Danger Count</h2>
<div id="regimeChart"></div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
<script>
const equityData = """ + json.dumps(equity_json, ensure_ascii=False) + """;
const regimes    = """ + json.dumps([[d, r] for d, r in zip(dates, regimes)]) + """;
const dangers    = """ + json.dumps([[d, v] for d, v in zip(dates, dangers)]) + """;
const priceData  = """ + json.dumps([[d, round(p,2)] for d, p in zip(dates, prices)]) + """;

const COLORS = ['#58a6ff','#00c853','#ffc107','#ff6b6b','#c084fc',
                '#34d399','#fb923c','#f472b6','#60a5fa','#a3e635','#e879f9','#2dd4bf'];

let mainChart = null;
let regimeChart = null;

function buildLegend() {
  const sel   = document.getElementById('strategySelect');
  const legend = document.getElementById('chartLegend');
  legend.innerHTML = '';
  Array.from(sel.selectedOptions).forEach((opt, i) => {
    const color = COLORS[i % COLORS.length];
    legend.innerHTML += `<div class="legend-item"><div class="legend-dot" style="background:${color}"></div>${opt.text}</div>`;
  });
}

function buildChart() {
  const sel   = document.getElementById('strategySelect');
  const selIdx = Array.from(sel.selectedOptions).map(o => parseInt(o.value));

  // Normalize to first date = 100
  const firstVals = selIdx.map(idx => equityData[idx].data[0][1]);

  const datasets = selIdx.map((idx, i) => {
    const color = COLORS[i % COLORS.length];
    const base  = firstVals[i];
    return {
      label: equityData[idx].name,
      data: equityData[idx].data.map(([d, v]) => ({x: d, y: +(v/base*100).toFixed(2)})),
      borderColor: color, backgroundColor: color+'22',
      borderWidth: 1.5, pointRadius: 0, tension: 0.1, fill: false,
    };
  });

  // Add SPY buy-hold as reference
  const spyBase = equityData[0].data[0][1];
  datasets.push({
    label: 'SPY 买入持有',
    data: equityData[0].data.map(([d, v]) => ({x: d, y: +(v/spyBase*100).toFixed(2)})),
    borderColor: '#6b7280', borderDash: [4,4],
    borderWidth: 1.5, pointRadius: 0, tension: 0.1, fill: false,
  });

  if (mainChart) mainChart.destroy();
  const ctx = document.getElementById('chart').getContext('2d');
  mainChart = new Chart(ctx, {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: false,
      scales: {
        x: {type:'category', ticks:{maxTicksLimit:12, color:'#6b7280'}, grid:{color:'#21262d'}},
        y: {title:{display:true,text:'净值 (初值=100)', color:'#6b7280'}, grid:{color:'#21262d'}, ticks:{color:'#6b7280'}},
      },
      plugins: {
        legend: {display: false},
        zoom: {zoom:{wheel:{enabled:true},mode:'x',onZoom:()=>{}},
               pan:{enabled:true,mode:'x'}},
      }
    }
  });
}

function buildRegimeChart() {
  const ctx = document.getElementById('regimeChart').getContext('2d');
  if (regimeChart) regimeChart.destroy();

  const regimeDs = {
    label: 'Regime Score',
    data: regimes.map(([d,r])=>({x:d, y:r})),
    borderColor:'#58a6ff', backgroundColor:'#58a6ff33',
    borderWidth:1.5, pointRadius:0, tension:0.3, fill:true,
    yAxisID:'y',
  };
  const dangerDs = {
    label: 'Danger Count',
    data: dangers.map(([d,v])=>({x:d, y:v})),
    borderColor:'#ff6b6b', backgroundColor:'#ff6b6b44',
    borderWidth:1.5, pointRadius:0, tension:0.3, fill:true,
    yAxisID:'y2',
  };

  regimeChart = new Chart(ctx, {
    type: 'line',
    data: { datasets: [regimeDs, dangerDs] },
    options: {
      responsive:true, maintainAspectRatio:false, animation:false,
      scales: {
        x:{type:'category',ticks:{maxTicksLimit:12,color:'#6b7280'},grid:{color:'#21262d'}},
        y:{title:{display:true,text:'Regime (0-10)',color:'#58a6ff'},min:0,max:10,
           grid:{color:'#21262d'},ticks:{color:'#6b7280'}},
        y2:{title:{display:true,text:'Danger Count',color:'#ff6b6b'},min:0,max:5,
            grid:{drawOnChartArea:false},ticks:{color:'#6b7280'}},
      },
      plugins:{legend:{display:false},zoom:{zoom:{wheel:{enabled:true},mode:'x'},pan:{enabled:true,mode:'x'}}},
    }
  });
}

document.getElementById('strategySelect').addEventListener('change', ()=>{buildLegend();buildChart();});
document.querySelector('button').addEventListener('click', ()=>{
  if(mainChart) mainChart.resetZoom();
  if(regimeChart) regimeChart.resetZoom();
});

buildLegend(); buildChart(); buildRegimeChart();
</script>
<div class="footer">
  生成时间：""" + datetime.now().strftime("%Y-%m-%d %H:%M") + """ &nbsp;|&nbsp; P2 Regime × Dangerous Shift 综合回测 2020-2026 &nbsp;|&nbsp; 美股投资洞察分析
</div>
</body>
</html>"""

    with open(OUTPUT / "combined_backtest_2020_2026.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  HTML → {OUTPUT}/combined_backtest_2020_2026.html")


if __name__ == "__main__":
    main()
