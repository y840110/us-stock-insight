"""
RS计算：20日/65日相对强弱，RS评分，板块内百分位
"""

from typing import Optional


def _ema(values: list, span: int) -> list:
    """计算EMA序列"""
    if not values:
        return []
    alpha = 2.0 / (span + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * alpha + ema[-1] * (1 - alpha))
    return ema


def _pct_change_series(values: list, period: int) -> list:
    """计算百分比变化序列"""
    if len(values) < period + 1:
        return []
    return [((values[i] - values[i - period]) / values[i - period]) * 100
            for i in range(period, len(values))]


def calc_rs(
    stock_klines: dict,
    spy_klines: dict,
    market: str = "US",
) -> dict:
    """
    计算相对强弱指标

    Args:
        stock_klines: 股票K线数据（JSON格式）
        spy_klines: SPY K线数据（JSON格式）
        market: 市场标识（仅作注释用）

    Returns:
        {
            'rs_20d': float,   # 20日RS
            'rs_65d': float,   # 65日RS
            'rs_score': int,   # 0~25
            'rs_rank': float   # 板块内百分位（默认0.5）
        }
    """
    stock_data = stock_klines.get("data", [])
    spy_data = spy_klines.get("data", [])

    if not stock_data or not spy_data:
        return _empty_rs_result()

    # 按ymd升序
    stock_data = sorted(stock_data, key=lambda x: x["ymd"])
    spy_data = sorted(spy_data, key=lambda x: x["ymd"])

    stock_closes = [float(d["close"]) for d in stock_data]
    spy_closes = [float(d["close"]) for d in spy_data]

    # 找最近共同ymd锚点
    stock_dates = set(d["ymd"] for d in stock_data)
    spy_dates = set(d["ymd"] for d in spy_data)
    common_dates = sorted(stock_dates & spy_dates, reverse=True)

    if len(common_dates) < 66:  # 至少需要65天数据
        return _empty_rs_result()

    latest_date = common_dates[0]

    # 提取最新日期对应的index
    stock_idx_map = {d["ymd"]: i for i, d in enumerate(stock_data)}
    spy_idx_map = {d["ymd"]: i for i, d in enumerate(spy_data)}

    latest_sidx = spy_idx_map.get(latest_date, len(spy_closes) - 1)
    latest_tidx = stock_idx_map.get(latest_date, len(stock_closes) - 1)

    def _get_pct_change(closes: list, end_idx: int, period: int) -> float:
        start_idx = end_idx - period
        if start_idx < 0:
            return 0.0
        start_val = closes[start_idx]
        end_val = closes[end_idx]
        if start_val == 0:
            return 0.0
        return ((end_val - start_val) / start_val) * 100

    # RS = 股票涨幅 - SPY涨幅（越大越强）
    rs_20d = _get_pct_change(stock_closes, latest_tidx, 20) - \
             _get_pct_change(spy_closes, latest_sidx, 20)

    rs_65d = _get_pct_change(stock_closes, latest_tidx, 65) - \
             _get_pct_change(spy_closes, latest_sidx, 65)

    # RS评分（0~25）
    # RS > 10 → 25分；RS > 5 → 18分；RS > 0 → 12分；RS > -5 → 6分；否则 0
    if rs_20d > 10:
        rs_score = 25
    elif rs_20d > 7:
        rs_score = 20
    elif rs_20d > 5:
        rs_score = 16
    elif rs_20d > 2:
        rs_score = 12
    elif rs_20d > 0:
        rs_score = 8
    elif rs_20d > -5:
        rs_score = 4
    else:
        rs_score = 0

    rs_score = max(0, min(25, rs_score))

    return {
        "rs_20d": round(rs_20d, 4),
        "rs_65d": round(rs_65d, 4),
        "rs_score": rs_score,
        "rs_rank": 0.5,  # 需外部板块数据计算百分位，此处默认0.5
    }


def _empty_rs_result() -> dict:
    return {
        "rs_20d": 0.0,
        "rs_65d": 0.0,
        "rs_score": 0,
        "rs_rank": 0.5,
    }


if __name__ == "__main__":
    import json
    import random

    def _gen_klines(days: int = 300, trend: float = 0.1) -> dict:
        data = []
        close = 150.0
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
                "vol": int(random.uniform(10e6, 50e6)),
            })
        return {"ticker": "AAPL", "interval": "1d", "count": len(data), "data": data}

    stock = _gen_klines(300, trend=0.15)
    spy = _gen_klines(300, trend=0.08)
    result = calc_rs(stock, spy)
    print("RS Result:", json.dumps(result, indent=2))
