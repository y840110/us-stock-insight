"""
价格结构特征：实体比、影线比、波动率STD、高低点区间（ML专用特征）
"""

from typing import Dict
import math


def _ema(values: list, span: int) -> list:
    """计算EMA序列"""
    if not values:
        return []
    alpha = 2.0 / (span + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * alpha + ema[-1] * (1 - alpha))
    return ema


def calc_price_structure(klines: dict) -> dict:
    """
    计算价格结构特征（ML专用特征，不直接参与评分）

    Args:
        klines: K线数据（JSON格式）

    Returns:
        {
            'candle_body_ratio': float,   # (close-open)/(high-low)，实体占比
            'upper_wick_ratio': float,     # 上影线/日内振幅
            'lower_wick_ratio': float,     # 下影线/日内振幅
            'volatility_20d': float,       # 20日收益率STD
            'volatility_65d': float,       # 65日收益率STD
            'high_low_range': float,       # (high-low)/close
            'volume_ratio': float,         # vol/MA20
            'max_drawdown_20d': float     # 20日高点回撤
        }
    """
    data = klines.get("data", [])
    if not data:
        return _empty_price_structure()

    # 按ymd升序
    data = sorted(data, key=lambda x: x["ymd"])

    opens = [float(d["open"]) for d in data]
    highs = [float(d["high"]) for d in data]
    lows = [float(d["low"]) for d in data]
    closes = [float(d["close"]) for d in data]
    volumes = [float(d["vol"]) for d in data]

    if len(closes) < 66:
        return _empty_price_structure()

    # === 最新K线价格结构（以ymd为锚，取最后一条） ===
    latest_open = opens[-1]
    latest_close = closes[-1]
    latest_high = highs[-1]
    latest_low = lows[-1]

    day_range = latest_high - latest_low

    # 实体比：正值=阳线，负值=阴线，绝对值=实体大小/日内振幅
    if day_range > 0:
        candle_body_ratio = (latest_close - latest_open) / day_range
        upper_wick = max(0, latest_high - max(latest_close, latest_open))
        lower_wick = max(0, min(latest_close, latest_open) - latest_low)
        upper_wick_ratio = upper_wick / day_range
        lower_wick_ratio = lower_wick / day_range
    else:
        candle_body_ratio = 0.0
        upper_wick_ratio = 0.0
        lower_wick_ratio = 0.0

    # 高低点区间
    high_low_range = day_range / latest_close if latest_close > 0 else 0.0

    # === 历史波动率（收益率STD） ===
    # 日收益率
    returns_20d = _calc_returns(closes, 20)
    returns_65d = _calc_returns(closes, 65)

    volatility_20d = _std(returns_20d) if len(returns_20d) >= 2 else 0.0
    volatility_65d = _std(returns_65d) if len(returns_65d) >= 2 else 0.0

    # === 量比 ===
    vol_ma20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else volumes[-1]
    volume_ratio = volumes[-1] / vol_ma20 if vol_ma20 > 0 else 0.0

    # === 20日最大回撤 ===
    max_drawdown_20d = _calc_max_drawdown(closes, period=20)

    return {
        "candle_body_ratio": round(candle_body_ratio, 6),
        "upper_wick_ratio": round(upper_wick_ratio, 6),
        "lower_wick_ratio": round(lower_wick_ratio, 6),
        "volatility_20d": round(volatility_20d, 6),
        "volatility_65d": round(volatility_65d, 6),
        "high_low_range": round(high_low_range, 6),
        "volume_ratio": round(volume_ratio, 4),
        "max_drawdown_20d": round(max_drawdown_20d, 6),
    }


def _calc_returns(closes: list, period: int) -> list:
    """计算period日收益率序列"""
    if len(closes) < period + 1:
        return []
    return [(closes[i] - closes[i - period]) / closes[i - period] * 100
            for i in range(period, len(closes))]


def _std(values: list) -> float:
    """计算标准差"""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _calc_max_drawdown(closes: list, period: int = 20) -> float:
    """
    计算近period日高点回撤百分比
    返回负值表示回撤幅度
    """
    if len(closes) < period:
        period = len(closes)
    if period < 2:
        return 0.0

    window = closes[-period:]
    peak = max(window)
    trough = min(window)
    if peak == 0:
        return 0.0
    return (trough - peak) / peak * 100


def _empty_price_structure() -> dict:
    return {
        "candle_body_ratio": 0.0,
        "upper_wick_ratio": 0.0,
        "lower_wick_ratio": 0.0,
        "volatility_20d": 0.0,
        "volatility_65d": 0.0,
        "high_low_range": 0.0,
        "volume_ratio": 0.0,
        "max_drawdown_20d": 0.0,
    }


if __name__ == "__main__":
    import json
    import random

    def _gen_klines(days: int = 100) -> dict:
        data = []
        close = 180.0
        for i in range(days):
            ymd = f"2024-{(i // 30) + 1:02d}_{(i % 30) + 1:02d}"
            close += random.uniform(-2, 2.5)
            day_range = random.uniform(0.5, 3)
            high = close + random.uniform(0, day_range)
            low = close - random.uniform(0, day_range)
            data.append({
                "ymd": ymd,
                "open": round(low + 0.2, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "adj": round(close, 2),
                "vol": int(random.uniform(20e6, 80e6)),
            })
        return {"ticker": "AAPL", "interval": "1d", "count": len(data), "data": data}

    klines = _gen_klines()
    result = calc_price_structure(klines)
    print("Price Structure:", json.dumps(result, indent=2))
