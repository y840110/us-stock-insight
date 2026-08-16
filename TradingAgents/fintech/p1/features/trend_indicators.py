"""
EMA趋势结构：多头排列判断、周线EMA确认
"""

from typing import Dict


def _ema(values: list, span: int) -> list:
    """计算EMA序列（不使用TA-Lib）"""
    if not values:
        return []
    alpha = 2.0 / (span + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * alpha + ema[-1] * (1 - alpha))
    return ema


def calc_trend_score(klines: dict, interval: str = "1d") -> dict:
    """
    计算EMA趋势结构评分

    Args:
        klines: K线数据（JSON格式）
        interval: K线周期 ('1d' 日线 或 '1wk' 周线)

    Returns:
        {
            'above_20ema': bool,
            'above_50ema': bool,
            'ema20_above_ema50': bool,
            'ema50_above_ema200': bool,
            'weekly_ema20_rising': bool,  # 周线20EMA连续3周升高
            'trend_score': int,  # 0~20
            'ema_values': {'ema20': float, 'ema50': float, 'ema200': float}
        }
    """
    data = klines.get("data", [])
    if not data:
        return _empty_trend_result()

    # 按ymd升序
    data = sorted(data, key=lambda x: x["ymd"])
    closes = [float(d["close"]) for d in data]

    if len(closes) < 200:
        return _empty_trend_result()

    # 计算EMA
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)

    latest_close = closes[-1]
    latest_ema20 = ema20[-1]
    latest_ema50 = ema50[-1]
    latest_ema200 = ema200[-1]

    above_20ema = latest_close > latest_ema20
    above_50ema = latest_close > latest_ema50
    ema20_above_ema50 = latest_ema20 > latest_ema50
    ema50_above_ema200 = latest_ema50 > latest_ema200

    # 周线EMA20连续3周升高
    weekly_ema20_rising = False
    if interval == "1wk" and len(ema20) >= 4:
        weekly_ema20_rising = ema20[-1] > ema20[-2] > ema20[-3] > ema20[-4]
    elif interval == "1d":
        # 日线：检查近3根日K的EMA20是否逐日升高
        if len(ema20) >= 4:
            weekly_ema20_rising = ema20[-1] > ema20[-2] > ema20[-3] > ema20[-4]

    # 趋势评分（0~20）
    score = 0
    if above_20ema:
        score += 4
    if above_50ema:
        score += 6
    if ema20_above_ema50:
        score += 5
    if ema50_above_ema200:
        score += 5

    score = max(0, min(20, score))

    return {
        "above_20ema": above_20ema,
        "above_50ema": above_50ema,
        "ema20_above_ema50": ema20_above_ema50,
        "ema50_above_ema200": ema50_above_ema200,
        "weekly_ema20_rising": weekly_ema20_rising,
        "trend_score": score,
        "ema_values": {
            "ema20": round(latest_ema20, 4),
            "ema50": round(latest_ema50, 4),
            "ema200": round(latest_ema200, 4),
        },
    }


def _empty_trend_result() -> dict:
    return {
        "above_20ema": False,
        "above_50ema": False,
        "ema20_above_ema50": False,
        "ema50_above_ema200": False,
        "weekly_ema20_rising": False,
        "trend_score": 0,
        "ema_values": {"ema20": 0.0, "ema50": 0.0, "ema200": 0.0},
    }


if __name__ == "__main__":
    import json
    import random

    def _gen_klines(days: int = 300, trend: float = 0.1) -> dict:
        data = []
        close = 180.0
        for i in range(days):
            ymd = f"2024-{(i // 30) + 1:02d}_{(i % 30) + 1:02d}"
            close += random.uniform(-1, trend)
            high = close + random.uniform(0, 1)
            low = close - random.uniform(0, 1)
            data.append({
                "ymd": ymd,
                "open": round(low + 0.2, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "adj": round(close, 2),
                "vol": int(random.uniform(30e6, 70e6)),
            })
        return {"ticker": "AAPL", "interval": "1d", "count": len(data), "data": data}

    klines = _gen_klines(300, trend=0.12)
    result = calc_trend_score(klines)
    print("Trend Score:", json.dumps(result, indent=2))
