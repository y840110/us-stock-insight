"""
P2 单一数据加载模块
所有策略共用的指标数据统一从这里获取
每个指标只定义一次，避免重复逻辑
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any, Optional

from p2_shared.utils import (
    BASE_DIR, P1_KLINES, MID_KLINES, MARKET_IND,
    ema, sma, rsi, atr, bollinger, linear_slope,
    realized_vol, vix_rolling_vol,
    load_json, load_market_indicator, load_market_indicator_raw, resolve_bars
)


# ═══════════════════════════════════════════════════════════════
# 指标获取函数（统一入口，所有策略共用）
# ═══════════════════════════════════════════════════════════════

def get_spy_close(trade_date: str) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", 1)
    return float(bars[-1]["close"]) if bars else None


def get_spy_ema20(trade_date: str) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", 60)
    if not bars or len(bars) < 20:
        return None
    return ema([float(b["close"]) for b in bars], 20)


def get_spy_sma50(trade_date: str) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", 60)
    if not bars or len(bars) < 50:
        return None
    return sma([float(b["close"]) for b in bars], 50)


def get_spy_sma200(trade_date: str) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", 250)
    if not bars or len(bars) < 200:
        return None
    return sma([float(b["close"]) for b in bars], 200)


def get_ema20_slope(trade_date: str, window: int = 20) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", window + 40)
    if not bars or len(bars) < window + 5:
        return None
    closes = [float(b["close"]) for b in bars]
    ema_vals = []
    e = ema(closes[:window + 5], 20)
    for c in closes[window + 4:]:
        e = c * (2 / 21) + e * (19 / 21)
        ema_vals.append(e)
    if len(ema_vals) < 2:
        return None
    return linear_slope(ema_vals)


def get_20d_return(trade_date: str) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", 25)
    if not bars or len(bars) < 21:
        return None
    c0 = float(bars[-21]["close"])
    c1 = float(bars[-1]["close"])
    return (c1 - c0) / c0 if c0 else None


def get_5d_return(trade_date: str) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", 10)
    if not bars or len(bars) < 6:
        return None
    c0 = float(bars[-6]["close"])
    c1 = float(bars[-1]["close"])
    return (c1 - c0) / c0 if c0 else None


def get_distance_ema20(trade_date: str) -> Optional[float]:
    close = get_spy_close(trade_date)
    ema20 = get_spy_ema20(trade_date)
    if close is None or ema20 is None or ema20 == 0:
        return None
    return (close - ema20) / ema20


def get_rsi14(trade_date: str) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", 50)
    if not bars or len(bars) < 15:
        return None
    return rsi([float(b["close"]) for b in bars], 14)


def get_macd_histogram(trade_date: str) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", 60)
    if not bars or len(bars) < 35:
        return None
    closes = [float(b["close"]) for b in bars]

    # EMA12, EMA26
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    macd = ema12 - ema26

    # Signal = EMA9 of MACD
    macd_series = []
    e = macd
    k = 2.0 / 10.0
    for m in [macd] * 9:
        e = m * k + e * (1 - k)
        macd_series.append(e)
    for c in closes[26:]:
        ema12 = c * (2 / 13) + ema12 * (1 - 2 / 13)
        ema26 = c * (2 / 27) + ema26 * (1 - 2 / 27)
        macd_series.append(ema12 - ema26)

    if len(macd_series) < 10:
        return None
    signal = ema(macd_series[1:], 9)  # skip first (used for seed)
    return macd - signal if macd and signal is not None else None


def get_macd_histogram_peak(trade_date: str, lookback: int = 60) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", lookback + 40)
    if not bars or len(bars) < 40:
        return None
    closes = [float(b["close"]) for b in bars]

    macd_vals = []
    ema12 = ema(closes[:27], 12)
    ema26 = ema(closes[:27], 26)
    for c in closes[26:]:
        ema12 = c * (2 / 13) + ema12 * (1 - 2 / 13)
        ema26 = c * (2 / 27) + ema26 * (1 - 2 / 27)
        macd_vals.append(ema12 - ema26)

    if len(macd_vals) < 10:
        return None
    signal_vals = []
    s = ema(macd_vals[:9], 9)
    for m in macd_vals[8:]:
        s = m * (2 / 10) + s * (8 / 10)
        signal_vals.append(s)

    hist_vals = [m - s for m, s in zip(macd_vals[8:], signal_vals)]
    return max(hist_vals[-lookback:]) if hist_vals else None


def get_vix(trade_date: str = None) -> Optional[float]:
    bars = load_json(Path("VIX_1d.json"), trade_date)
    if not bars:
        return None
    return float(bars[-1].get("vix_close", bars[-1].get("close", bars[-1].get("value"))))


def get_vvix(trade_date: str = None) -> Optional[float]:
    """VVIX: 从VVIX_1d.json读取；无数据时用VIX×1.08估算"""
    bars = load_json(Path("VVIX_1d.json"), trade_date)
    if bars:
        last = bars[-1]
        return float(last.get("value", last.get("close")))
    # Fallback approximation
    vix = get_vix(trade_date)
    return vix * 1.08 if vix else None


def _vix_close(b):
    """从 VIX bar 中提取收盘价，兼容 vix_close / close / value"""
    return float(b.get("vix_close", b.get("close", b.get("value"))))


def get_vix9d(trade_date: str = None) -> Optional[float]:
    bars = load_json(Path("VIX_1d.json"), trade_date)
    if not bars or len(bars) < 10:
        return None
    closes = [_vix_close(b) for b in bars]
    return vix_rolling_vol(closes[-20:], 9)


def get_vix1m(trade_date: str = None) -> Optional[float]:
    bars = load_json(Path("VIX_1d.json"), trade_date)
    if not bars or len(bars) < 22:
        return None
    closes = [_vix_close(b) for b in bars]
    return vix_rolling_vol(closes[-30:], 21)


def get_vix3m(trade_date: str = None) -> Optional[float]:
    bars = load_json(Path("VIX_1d.json"), trade_date)
    if not bars or len(bars) < 64:
        return None
    closes = [_vix_close(b) for b in bars]
    return vix_rolling_vol(closes[-75:], 63)


def get_atr14(trade_date: str) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", 25)
    if not bars or len(bars) < 15:
        return None
    return atr(bars, 14)


def get_atr14_peak(trade_date: str, lookback: int = 60) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", lookback + 20)
    if not bars or len(bars) < lookback:
        return None
    peaks = []
    for i in range(lookback, len(bars)):
        window = bars[i - lookback + 1:i + 1]
        a = atr(window, 14)
        if a:
            peaks.append(a)
    return max(peaks) if peaks else None


# ── NYAD ──────────────────────────────────────────────────────

def get_nyad(trade_date: str) -> Optional[float]:
    path = P1_KLINES / "NYAD_1d.json"
    alt = MID_KLINES / "NYAD_1d.json"
    for p in [p for p in [path, alt] if p.exists()]:
        try:
            with open(p) as f:
                d = json.load(f)
            nyad = d.get("nyad", {})
            if isinstance(nyad, dict):
                dates = sorted(nyad.keys())
                if trade_date in nyad:
                    return float(nyad[trade_date])
                # Get most recent <= trade_date
                for d in reversed(dates):
                    if d <= trade_date:
                        return float(nyad[d])
        except Exception:
            pass
    return None


def get_nyad_slope(trade_date: str, window: int = 20) -> Optional[float]:
    path = P1_KLINES / "NYAD_1d.json"
    alt = MID_KLINES / "NYAD_1d.json"
    for p in [p for p in [path, alt] if p.exists()]:
        try:
            with open(p) as f:
                d = json.load(f)
            nyad = d.get("nyad", {})
            if isinstance(nyad, dict):
                dates = sorted(nyad.keys())
                recent = [float(nyad[d]) for d in dates if d <= trade_date][-window:]
                if len(recent) >= window:
                    return linear_slope(recent)
        except Exception:
            pass
    return None


def get_spy_high_status(trade_date: str, lookback: int = 252) -> Optional[bool]:
    bars = resolve_bars(trade_date, "SPY", lookback + 5)
    if not bars or len(bars) < lookback:
        return None
    window = [float(b["close"]) for b in bars[-lookback:]]
    current = float(bars[-1]["close"])
    return current >= max(window)


def get_nyad_confirm_status(trade_date: str) -> Optional[bool]:
    """
    SPY创20日新高时，NYAD是否同步创新高
    True = 确认（两者均创新高）
    False = 背离（SPY新高但NYAD未新高）
    None = SPY今日未创新高（无效测试）
    """
    path = P1_KLINES / "NYAD_1d.json"
    alt = MID_KLINES / "NYAD_1d.json"
    nyad_path = None
    for p in [path, alt]:
        if p.exists():
            nyad_path = p
            break
    if not nyad_path:
        return None

    with open(nyad_path) as f:
        nyad_data = json.load(f)
    nyad_series = nyad_data.get("nyad", {})
    if not isinstance(nyad_series, dict):
        return None

    nyad_dates = sorted(nyad_series.keys())
    idx = None
    for i, d in enumerate(nyad_dates):
        if d <= trade_date:
            idx = i
    if idx is None or idx < 40:
        return None

    # SPY是否今日创20日新高？
    spy_high = get_spy_high_status(trade_date, 20)
    if not spy_high:
        return None  # SPY未创新高，无效测试

    # 前一窗口高点
    prev_window_dates = nyad_dates[idx - 39:idx - 19]
    if len(prev_window_dates) < 20:
        return None

    nyad_current = float(nyad_series[trade_date])
    nyad_prev_high = max(float(nyad_series[d]) for d in prev_window_dates)
    return nyad_current >= nyad_prev_high


# ── Breadth ───────────────────────────────────────────────────

def _breadth_file() -> Optional[Path]:
    candidates = [
        P1_KLINES / "sp500_breadth_finviz.json",
        MID_KLINES / "sp500_breadth_finviz.json",
    ]
    return next((p for p in candidates if p.exists()), None)


def get_sp500_above_50ma(trade_date: str = None) -> Optional[float]:
    bf = _breadth_file()
    if not bf:
        return None
    try:
        with open(bf) as f:
            d = json.load(f)
        val = d.get("above_sma50")
        return float(val) if val is not None else None
    except Exception:
        return None


def get_sp500_above_200ma(trade_date: str = None) -> Optional[float]:
    bf = _breadth_file()
    if not bf:
        return None
    try:
        with open(bf) as f:
            d = json.load(f)
        val = d.get("above_sma200")
        return float(val) if val is not None else None
    except Exception:
        return None


def get_new_high_low_ratio(trade_date: str) -> Optional[float]:
    bf = _breadth_file()
    if not bf:
        return None
    try:
        with open(bf) as f:
            d = json.load(f)
        nh = float(d.get("new_high_pct", 0))
        nl = float(d.get("new_low_pct", 0))
        total = nh + nl
        return nh / total if total > 0 else 0.5
    except Exception:
        return None


# ── 相对强弱 ──────────────────────────────────────────────────

def _rs_slope(trade_date: str, ticker: str, window: int = 20) -> Optional[float]:
    spy_bars = resolve_bars(trade_date, "SPY", window + 10)
    tk_bars = resolve_bars(trade_date, ticker, window + 10)
    if not spy_bars or not tk_bars or len(spy_bars) < window + 2:
        return None

    spy_closes = {b["date"]: float(b["close"]) for b in spy_bars}
    tk_closes = {b["date"]: float(b["close"]) for b in tk_bars}
    common = sorted(set(spy_closes.keys()) & set(tk_closes.keys()))
    if len(common) < window + 2:
        return None

    rs = [tk_closes[d] / spy_closes[d] for d in common[-window - 1:]]
    return linear_slope(rs)


def get_iwm_rs_slope(trade_date: str, window: int = 20) -> Optional[float]:
    return _rs_slope(trade_date, "IWM", window)


def get_soxx_rs_slope(trade_date: str, window: int = 20) -> Optional[float]:
    return _rs_slope(trade_date, "SOXX", window)


def get_qqq_rs_slope(trade_date: str, window: int = 20) -> Optional[float]:
    return _rs_slope(trade_date, "QQQ", window)


# ── 宏观 ──────────────────────────────────────────────────────

def get_us10y_yield(trade_date: str = None) -> Optional[float]:
    candidates = [
        MID_KLINES / "TNX_1d.json",
        BASE_DIR / "TradingAgents" / "fintech" / "p1" / "klines" / "TNX_1d.json",
        P1_KLINES / "TNX_1d.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                with open(path) as f:
                    raw = json.load(f)
                bars = raw if isinstance(raw, list) else raw.get("data", [])
                bars = [b for b in bars if not trade_date or b.get("date", "") <= trade_date]
                if bars:
                    return float(bars[-1].get("value", bars[-1].get("close")))
            except Exception:
                pass
    return None


def get_dxy(trade_date: str = None) -> Optional[float]:
    path = P1_KLINES / "DXY_1d.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            d = json.load(f)
        bars = d.get("data", [])
        bars = [b for b in bars if not trade_date or b.get("date", "") <= trade_date]
        if bars:
            return float(bars[-1]["close"])
    except Exception:
        pass
    return None


def get_hy_spread(trade_date: str = None) -> Optional[float]:
    candidates = [
        BASE_DIR / "TradingAgents" / "fintech" / "p1" / "klines" / "HY_SPREAD_1d.json",
        MID_KLINES / "HY_SPREAD_1d.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                with open(path) as f:
                    raw = json.load(f)
                bars = raw if isinstance(raw, list) else raw.get("data", [])
                bars = [b for b in bars if not trade_date or b.get("date", "") <= trade_date]
                if bars:
                    return float(bars[-1].get("value", bars[-1].get("close")))
            except Exception:
                pass
    return None


def get_fci(trade_date: str = None) -> Optional[float]:
    """
    FCI代理 = (US10Y - VIX) / DXY
    > 0 = 紧缩；< 0 = 宽松
    """
    us10y = get_us10y_yield(trade_date)
    vix = get_vix(trade_date)
    dxy = get_dxy(trade_date)
    if us10y is not None and vix is not None and dxy and dxy != 0:
        return (us10y - vix) / dxy
    return None


def get_liquidity_score(trade_date: str = None) -> Optional[float]:
    record = load_market_indicator("LIQUIDITY_SCORE_1d.json", trade_date)
    if record and isinstance(record, dict):
        return float(record.get("score", 0))
    return None


# ── 期权 ──────────────────────────────────────────────────────

def get_gex(trade_date: str) -> float:
    """
    GEX: +1(正Gamma均值回归) / 0(中性) / -1(负Gamma趋势)
    数据源: SPX_GAMMA_1d.json → data[0].total_net_gamma
    Fallback: GAMMA_REGIME_1d.json → regime score
    """
    # 优先: SPX_GAMMA（需要原始JSON，data[0]为最近到期日）
    raw = load_market_indicator_raw("SPX_GAMMA_1d.json")
    if raw and isinstance(raw, dict):
        exps = raw.get("data", [])
        if exps:
            # 过滤到 trade_date 之前（含）的最近一条
            valid_exps = [e for e in exps if e.get("date", "") <= trade_date]
            if not valid_exps:
                valid_exps = exps  # fallback to nearest
            net_gamma = float(valid_exps[0].get("total_net_gamma", 0))
            if net_gamma < -0.5:
                return -1.0
            elif net_gamma > 0.5:
                return 1.0
            return 0.0

    # Fallback: GAMMA_REGIME
    proxy = load_market_indicator("GAMMA_REGIME_1d.json", trade_date)
    if proxy and isinstance(proxy, dict):
        regime = proxy.get("regime", "").upper()
        if regime == "POSITIVE":
            return 1.0
        elif regime == "NEGATIVE":
            return -1.0
        return 0.0

    return 0.0


def get_put_call_ratio(trade_date: str = None) -> Optional[float]:
    record = load_market_indicator("PUT_CALL_RATIO_1d.json", trade_date)
    if record:
        if isinstance(record, dict):
            return float(record.get("value", 0.7))
        elif isinstance(record, list) and record:
            return float(record[-1].get("value", 0.7))
    return 0.7  # 默认中性


def get_cta_positioning(trade_date: str) -> Optional[float]:
    """
    CTA 历史百分位（0-100）
    来源: CTA_POSITIONING_1d.json (Tradingster COT)
    """
    path = P1_KLINES / "CTA_POSITIONING_1d.json"
    alt = MID_KLINES / "CTA_POSITIONING_1d.json"
    for p in [p for p in [path, alt] if p.exists()]:
        try:
            with open(p) as f:
                d = json.load(f)
            data = d.get("data", {})
            if isinstance(data, dict):
                dates = sorted(data.keys())
                recent = [r for r in dates if r <= trade_date]
                if recent:
                    return float(data[recent[-1]].get("hist_pct", 50))
        except Exception:
            pass
    return None


# ── 时机指标 ──────────────────────────────────────────────────

def get_bb_percent(trade_date: str) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", 30)
    if not bars or len(bars) < 21:
        return None
    closes = [float(b["close"]) for b in bars]
    bb = bollinger(closes, 20, 2.0)
    return bb.get("bb_pct")


def get_bb_bandwidth(trade_date: str) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", 30)
    if not bars or len(bars) < 21:
        return None
    closes = [float(b["close"]) for b in bars]
    bb = bollinger(closes, 20, 2.0)
    return bb.get("bandwidth")


def get_volume_ratio(trade_date: str) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", 25)
    if not bars or len(bars) < 21:
        return None
    vols = [float(b["volume"]) for b in bars[-20:]]
    avg_vol = sum(vols) / len(vols)
    vol_today = float(bars[-1]["volume"])
    return vol_today / avg_vol if avg_vol > 0 else None


def get_vwap_distance(trade_date: str) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", 25)
    if not bars or len(bars) < 2:
        return None
    tp = [(float(b["high"]) + float(b["low"]) + float(b["close"])) / 3.0 for b in bars[-20:]]
    vwap = sum(tp) / len(tp)
    close = float(bars[-1]["close"])
    return (close - vwap) / vwap if vwap > 0 else None


def get_realized_vol(trade_date: str, window: int = 20) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", window + 10)
    if not bars or len(bars) < window + 1:
        return None
    closes = [float(b["close"]) for b in bars]
    return realized_vol(closes, window)


def get_current_drawdown(trade_date: str) -> Optional[float]:
    bars = resolve_bars(trade_date, "SPY", 300)
    if not bars:
        return None
    closes = [float(b["close"]) for b in bars]
    peak = max(closes)
    current = closes[-1]
    return (current - peak) / peak if peak > 0 else 0.0


# ═══════════════════════════════════════════════════════════════
# 统一加载器：一次获取所有指标
# ═══════════════════════════════════════════════════════════════

def load_all_variables(trade_date: str) -> Dict[str, Any]:
    """
    加载全部44个指标，供所有策略共同使用
    不重复从磁盘读取，同一数据源只加载一次
    """
    return {
        # 价格结构
        "SPY_CLOSE":           get_spy_close(trade_date),
        "SPY_EMA20":           get_spy_ema20(trade_date),
        "SPY_SMA50":           get_spy_sma50(trade_date),
        "SPY_SMA200":          get_spy_sma200(trade_date),
        "SPY_EMA20_SLOPE":     get_ema20_slope(trade_date),
        "SPY_20D_RETURN":      get_20d_return(trade_date),
        "SPY_5D_RETURN":       get_5d_return(trade_date),
        "SPY_DISTANCE_EMA20":  get_distance_ema20(trade_date),

        # 动量
        "SPY_RSI14":           get_rsi14(trade_date),
        "MACD_HISTOGRAM":      get_macd_histogram(trade_date),
        "MACD_HISTOGRAM_PEAK": get_macd_histogram_peak(trade_date),

        # 波动率
        "VIX":                 get_vix(trade_date),
        "VVIX":                get_vvix(trade_date),
        "VIX9D":               get_vix9d(trade_date),
        "VIX1M":               get_vix1m(trade_date),
        "VIX3M":               get_vix3m(trade_date),
        "ATR14":               get_atr14(trade_date),
        "ATR14_PEAK":          get_atr14_peak(trade_date),

        # 广度
        "NYAD":                get_nyad(trade_date),
        "NYAD_SLOPE":          get_nyad_slope(trade_date),
        "SPY_NEW_HIGH":        get_spy_high_status(trade_date),
        "NYAD_CONFIRM":        get_nyad_confirm_status(trade_date),
        "SP500_ABOVE_50MA":    get_sp500_above_50ma(),
        "SP500_ABOVE_200MA":   get_sp500_above_200ma(),
        "NEW_HIGH_LOW_RATIO":  get_new_high_low_ratio(trade_date),
        "IWM_RS_SLOPE":        get_iwm_rs_slope(trade_date),
        "SOXX_RS_SLOPE":       get_soxx_rs_slope(trade_date),
        "QQQ_RS_SLOPE":        get_qqq_rs_slope(trade_date),

        # 宏观
        "US10Y":               get_us10y_yield(trade_date),
        "DXY":                 get_dxy(trade_date),
        "HY_SPREAD":           get_hy_spread(trade_date),
        "FCI":                 get_fci(trade_date),
        "LIQUIDITY_SCORE":     get_liquidity_score(trade_date),

        # 期权
        "GEX":                 get_gex(trade_date),
        "PUT_CALL_RATIO":      get_put_call_ratio(trade_date),
        "CTA_POSITIONING":     get_cta_positioning(trade_date),

        # 时机
        "BB_PERCENT":          get_bb_percent(trade_date),
        "BB_BANDWIDTH":        get_bb_bandwidth(trade_date),
        "VOLUME_RATIO":        get_volume_ratio(trade_date),
        "VWAP_DISTANCE":       get_vwap_distance(trade_date),

        # 风险
        "REALIZED_VOL":        get_realized_vol(trade_date),
        "CURRENT_DRAWDOWN":    get_current_drawdown(trade_date),

        # 内部计算
        "BREADTH_DIVERGENCE":  None,   # 由dispatcher填充
        "MACD_CONTRACTION":     None,   # 由dispatcher填充
        "ATR_COMPRESSION":      None,   # 由dispatcher填充
        "VIX_TERM_STRUCTURE":  None,   # 由dispatcher填充

        # 常量
        "TARGET_VOL":          0.15,
        "MAX_DRAWDOWN_LIMIT":  -0.12,
    }
