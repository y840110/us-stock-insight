"""
ATR/ATR% 波动率计算，波动率评分
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


def calc_volatility_score(klines: dict) -> dict:
    """
    计算波动率评分

    Args:
        klines: K线数据（JSON格式）

    Returns:
        {
            'atr14': float,
            'atr_pct': float,  # ATR/close * 100
            'vol_score': int    # 0~10
        }
    """
    data = klines.get("data", [])
    if not data:
        return _empty_volatility_result()

    # 按ymd升序
    data = sorted(data, key=lambda x: x["ymd"])

    highs = [float(d["high"]) for d in data]
    lows = [float(d["low"]) for d in data]
    closes = [float(d["close"]) for d in data]

    if len(closes) < 15:
        return _empty_volatility_result()

    # 计算 True Range
    tr_list = [highs[i] - lows[i] for i in range(len(closes))]
    for i in range(1, len(closes)):
        tr_list[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )

    # ATR(14) = Wilder平滑(TR)
    atr14 = _wilder_smooth(tr_list, 14)[-1] if len(tr_list) >= 14 else tr_list[-1]

    latest_close = closes[-1]
    atr_pct = (atr14 / latest_close) * 100 if latest_close > 0 else 0

    # 波动率评分（0~10）
    # ATR% > 5% → 高波动，低评分；ATR% 在 1~3% → 适中，标准评分
    if atr_pct > 5:
        vol_score = 2
    elif atr_pct > 4:
        vol_score = 4
    elif atr_pct > 3:
        vol_score = 6
    elif atr_pct > 2:
        vol_score = 8
    elif atr_pct > 1:
        vol_score = 10
    else:
        vol_score = 5  # 低波动但非极端

    vol_score = max(0, min(10, vol_score))

    return {
        "atr14": round(atr14, 4),
        "atr_pct": round(atr_pct, 4),
        "vol_score": vol_score,
    }


def _wilder_smooth(data: list, period: int) -> list:
    """
    Wilder平滑（标准EMA公式）。
    公式: EMA_n = EMA_{n-1} * (1 - 1/period) + value_n * (1/period)
        = EMA_{n-1} - EMA_{n-1}/period + value_n/period
    """
    if len(data) < period:
        return data
    result = []
    ema = sum(data[:period]) / period  # 初始化为 SMA
    result.append(ema)
    for i in range(period, len(data)):
        ema = ema - ema / period + data[i] / period
        result.append(ema)
    return result


def _empty_volatility_result() -> dict:
    return {
        "atr14": 0.0,
        "atr_pct": 0.0,
        "vol_score": 0,
    }


if __name__ == "__main__":
    import json
    import random

    def _gen_klines(days: int = 60) -> dict:
        data = []
        close = 180.0
        for i in range(days):
            ymd = f"2024-{(i // 30) + 1:02d}_{(i % 30) + 1:02d}"
            close += random.uniform(-2, 2.5)
            day_range = random.uniform(1, 3.5)
            high = close + random.uniform(0, day_range)
            low = close - random.uniform(0, day_range)
            data.append({
                "ymd": ymd,
                "open": round(low + 0.2, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "adj": round(close, 2),
                "vol": int(random.uniform(20e6, 60e6)),
            })
        return {"ticker": "AAPL", "interval": "1d", "count": len(data), "data": data}

    klines = _gen_klines()
    result = calc_volatility_score(klines)
    print("Volatility Score:", json.dumps(result, indent=2))
