"""
P2 共享工具函数
包含: EMA, RSI, ATR 等核心指标计算
所有策略共用此模块
"""
from __future__ import annotations
import json
import math
import statistics
from pathlib import Path
from typing import List, Dict, Any, Optional


# ═══════════════════════════════════════════════════════════════
# 数据路径配置（所有策略共用）
# ═══════════════════════════════════════════════════════════════

# 工作空间根目录（美股投资洞察分析/TradingAgents/）
BASE_DIR = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents")

# 股票K线目录
P1_KLINES = BASE_DIR / "fintech" / "p1" / "klines"

# 指数/宏观K线目录（VIX, DXY, TNX等）
MID_KLINES = BASE_DIR / "中间过程" / "klines"

# 市场指标目录
MARKET_IND = BASE_DIR / "中间过程" / "market_indicators"


# ═══════════════════════════════════════════════════════════════
# 核心计算函数
# ═══════════════════════════════════════════════════════════════

def ema(closes: List[float], period: int) -> float:
    """指数移动平均"""
    if not closes:
        return None
    ema = float(closes[0])
    k = 2.0 / (period + 1)
    for c in closes[1:]:
        ema = float(c) * k + ema * (1 - k)
    return ema


def sma(closes: List[float], period: int) -> float:
    """简单移动平均"""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """相对强弱指数"""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(bars: List[Dict], period: int = 14) -> Optional[float]:
    """平均真实波幅"""
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        high = float(bars[i]["high"])
        low = float(bars[i]["low"])
        prev_close = float(bars[i - 1]["close"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs[-period:]) / period


def bollinger(closes: List[float], period: int = 20, std_mult: float = 2.0) -> Dict[str, float]:
    """布林带: {mid, upper, lower, bb_pct, bandwidth}"""
    if len(closes) < period:
        return {}
    window = closes[-period:]
    mid = sum(window) / period
    std = statistics.stdev(window)
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    current = closes[-1]
    bb_pct = (current - lower) / (upper - lower) if upper != lower else 0.5
    bandwidth = (upper - lower) / mid if mid != 0 else 0
    return {"mid": mid, "upper": upper, "lower": lower, "bb_pct": bb_pct, "bandwidth": bandwidth}


def linear_slope(values: List[float]) -> float:
    """线性回归斜率（每期变化量）"""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    num = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / den if den != 0 else 0.0


def realized_vol(closes: List[float], window: int = 20) -> Optional[float]:
    """已实现波动率（年化百分比）"""
    if len(closes) < window + 1:
        return None
    rets = [(closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(len(closes) - window, len(closes)) if closes[i - 1] != 0]
    if len(rets) < window:
        return None
    std = statistics.stdev(rets)
    return std * (252 ** 0.5) * 100


def vix_rolling_vol(vix_closes: List[float], window: int) -> Optional[float]:
    """VIX滚动波动率（年化）"""
    if len(vix_closes) < window + 1:
        return None
    rets = []
    for i in range(len(vix_closes) - window, len(vix_closes)):
        prev = float(vix_closes[i - 1])
        curr = float(vix_closes[i])
        if prev > 0:
            rets.append((curr - prev) / prev)
    if len(rets) < window:
        return None
    std = statistics.stdev(rets)
    return std * (252 ** 0.5) * 100


# ═══════════════════════════════════════════════════════════════
# 数据加载辅助函数
# ═══════════════════════════════════════════════════════════════

def load_json(rel_path: Path, trade_date: Optional[str] = None) -> Optional[List[Dict]]:
    """
    通用JSON加载器
    支持 {data: [...]} 和直接 [ {...}, ... ] 两种格式
    可选按trade_date过滤
    """
    full_path = P1_KLINES / rel_path.name
    if not full_path.exists():
        # 尝试 MID_KLINES
        alt = MID_KLINES / rel_path.name
        if alt.exists():
            full_path = alt

    if not full_path.exists():
        return None

    try:
        with open(full_path) as f:
            raw = json.load(f)

        # 解析格式
        if isinstance(raw, list):
            bars = raw
        elif isinstance(raw, dict):
            bars = raw.get("data", [])
            # 有些文件是 {date_key: {...}} 格式（如 NYAD_1d.json）
            if not bars and "nyad" in raw:
                return raw  # 特殊处理，保留原格式
        else:
            return None

        # 日期过滤
        if trade_date:
            bars = [b for b in bars if b.get("date", "") <= trade_date]
        return bars
    except Exception:
        return None


def load_market_indicator(fname: str, trade_date: Optional[str] = None) -> Optional[Any]:
    """
    加载中间过程/market_indicators/下的文件
    返回：过滤后的单条记录（已解包），或原始 JSON 对象
    如果只需要数据列表，用 load_market_indicator_raw()
    """
    raw = load_market_indicator_raw(fname)
    if raw is None:
        return None
    records = raw.get("data", [])
    if not records:
        return raw
    # 日期过滤
    if trade_date:
        filtered = [r for r in records if r.get("date", "") <= trade_date]
        return filtered[-1] if filtered else (records[-1] if records else None)
    return records[-1] if isinstance(records, list) else records


def load_market_indicator_raw(fname: str) -> Optional[Any]:
    """加载中间过程/market_indicators/下的原始 JSON 对象（不解包）"""
    path = MARKET_IND / fname
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def resolve_bars(trade_date: str, ticker: str = "SPY", lookback: int = 300) -> List[Dict]:
    """
    加载并过滤K线数据
    返回 trade_date 之前（含）的 bars，最多 lookback 条
    """
    bars = load_json(Path(f"{ticker}_1d.json"), trade_date)
    if not bars:
        return []
    return bars[-lookback:] if len(bars) > lookback else bars
