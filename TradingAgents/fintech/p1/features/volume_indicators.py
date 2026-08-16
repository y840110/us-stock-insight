"""
VSA量化：放量/缩量/量比，量能评分
"""

from typing import Dict


def _ema(values: list, span: int) -> list:
    """计算EMA序列"""
    if not values:
        return []
    alpha = 2.0 / (span + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * alpha + ema[-1] * (1 - alpha))
    return ema


def calc_volume_score(klines: dict) -> dict:
    """
    计算量能评分

    Args:
        klines: K线数据（JSON格式）

    Returns:
        {
            'vol_ma20': float,
            'vol_ratio': float,           # vol / ma20
            'pullback_shrinking': bool,   # 回踩缩量确认
            'breakout_volume': bool,      # 放量突破
            'volume_score': int           # 0~15
        }
    """
    data = klines.get("data", [])
    if not data:
        return _empty_volume_result()

    # 按ymd升序
    data = sorted(data, key=lambda x: x["ymd"])

    closes = [float(d["close"]) for d in data]
    volumes = [float(d["vol"]) for d in data]

    if len(volumes) < 21:
        return _empty_volume_result()

    # 20日量能均线
    vol_ma20 = sum(volumes[-20:]) / 20
    latest_vol = volumes[-1]
    vol_ratio = latest_vol / vol_ma20 if vol_ma20 > 0 else 0

    # 放量突破：今日量比 > 1.5 且 价格上涨
    latest_close = closes[-1]
    prev_close = closes[-2] if len(closes) >= 2 else closes[-1]
    price_rising = latest_close > prev_close
    breakout_volume = vol_ratio > 1.5 and price_rising

    # 回踩缩量：近3日量能逐日递减（至少3根K线）
    pullback_shrinking = False
    if len(volumes) >= 4:
        v1, v2, v3, v4 = volumes[-4], volumes[-3], volumes[-2], volumes[-1]
        # 回踩：价格低于20日均价的10%以内视为回踩
        ema20_price = _ema(closes, 20)
        if len(ema20_price) >= 1:
            ma20_price = ema20_price[-1]
            near_ma = latest_close < ma20_price * 1.1
            if near_ma and v4 < v3 < v2:
                pullback_shrinking = True

    # 量能评分（0~15）
    score = 0
    if vol_ratio > 2.0:
        score += 8  # 巨量
    elif vol_ratio > 1.5:
        score += 5  # 明显放量
    elif vol_ratio > 1.2:
        score += 3  # 温和放量
    elif vol_ratio >= 0.8:
        score += 1  # 正常量能

    if pullback_shrinking:
        score += 4  # 回踩缩量确认

    if breakout_volume:
        score += 3  # 放量突破加分

    score = max(0, min(15, score))

    return {
        "vol_ma20": round(vol_ma20, 2),
        "vol_ratio": round(vol_ratio, 4),
        "pullback_shrinking": pullback_shrinking,
        "breakout_volume": breakout_volume,
        "volume_score": score,
    }


def _ema(values: list, span: int) -> list:
    if not values:
        return []
    alpha = 2.0 / (span + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * alpha + ema[-1] * (1 - alpha))
    return ema


def _empty_volume_result() -> dict:
    return {
        "vol_ma20": 0.0,
        "vol_ratio": 0.0,
        "pullback_shrinking": False,
        "breakout_volume": False,
        "volume_score": 0,
    }


if __name__ == "__main__":
    import json
    import random

    def _gen_klines(days: int = 60) -> dict:
        data = []
        close = 180.0
        for i in range(days):
            ymd = f"2024-{(i // 30) + 1:02d}_{(i % 30) + 1:02d}"
            close += random.uniform(-1, 1.2)
            vol = int(random.uniform(20e6, 80e6))
            # 某天放量
            if i == 50:
                vol = int(120e6)
            high = close + random.uniform(0, 1)
            low = close - random.uniform(0, 1)
            data.append({
                "ymd": ymd,
                "open": round(low + 0.2, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "adj": round(close, 2),
                "vol": vol,
            })
        return {"ticker": "AAPL", "interval": "1d", "count": len(data), "data": data}

    klines = _gen_klines()
    result = calc_volume_score(klines)
    print("Volume Score:", json.dumps(result, indent=2))
