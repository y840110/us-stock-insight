"""
市场因子：SPY EMA结构、ADX、VIX
"""

from typing import Optional
import math


def _ema(values: list, span: int) -> list:
    """计算EMA序列（不使用TA-Lib）"""
    if not values:
        return []
    alpha = 2.0 / (span + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * alpha + ema[-1] * (1 - alpha))
    return ema


def _latest_ymd(klines: dict) -> int:
    """返回最近一根K线的ymd整数（YYYYMMDD），用于锚定最新价格"""
    if not klines.get("data"):
        return 0
    return int(klines["data"][-1]["ymd"].replace("-", ""))


def calc_market_score(
    spy_klines: dict, vix_klines: Optional[dict] = None
) -> dict:
    """
    计算市场综合评分

    Args:
        spy_klines: SPY K线数据（JSON格式）
        vix_klines: VIX K线数据（可选，JSON格式）

    Returns:
        {
            'spy_above_20ema': bool,
            'spy_above_50ema': bool,
            'spy_above_200ema': bool,
            'spy_adx': float,
            'vix': float,
            'market_score': int,  # 0~30
            'risk_level': 'ON'|'OFF'
        }
    """
    spy_data = spy_klines.get("data", [])
    if not spy_data:
        return _empty_market_result()

    # 按ymd升序排列（铁律：以ymd为锚）
    spy_data = sorted(spy_data, key=lambda x: x["ymd"])

    closes = [float(d["close"]) for d in spy_data]
    highs = [float(d["high"]) for d in spy_data]
    lows = [float(d["low"]) for d in spy_data]

    # 计算EMA
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)

    # 最新价格（以ymd为锚，取最后一条）
    latest_close = closes[-1]
    latest_ema20 = ema20[-1] if len(ema20) >= 20 else ema20[-1] if ema20 else 0
    latest_ema50 = ema50[-1] if len(ema50) >= 50 else ema50[-1] if ema50 else 0
    latest_ema200 = ema200[-1] if len(ema200) >= 200 else ema200[-1] if ema200 else 0

    # SPY均线结构
    spy_above_20ema = latest_close > latest_ema20
    spy_above_50ema = latest_close > latest_ema50
    spy_above_200ema = latest_close > latest_ema200

    # ADX计算（不使用TA-Lib）
    spy_adx = _calc_adx(highs, lows, closes, period=14)

    # VIX
    vix = None
    if vix_klines and vix_klines.get("data"):
        vix_data = sorted(vix_klines["data"], key=lambda x: x["ymd"])
        vix = float(vix_data[-1]["close"]) if vix_data else None

    # 市场评分（0~30）
    score = 0
    if spy_above_20ema:
        score += 5
    if spy_above_50ema:
        score += 8
    if spy_above_200ema:
        score += 12
    # ADX > 25 表示趋势明显，顺势加分
    if spy_adx > 25:
        score += 5
    # VIX > 25 风险偏好低
    if vix is not None:
        if vix < 20:
            score += 0  # 低波动，积极
        elif vix > 30:
            score -= 5  # 高波动，风险
        elif vix > 25:
            score -= 2

    score = max(0, min(30, score))

    # 风险等级：VIX > 25 或 SPY 在 200EMA 下方 → OFF
    risk_level = "OFF" if (vix is not None and vix > 25) or not spy_above_200ema else "ON"

    return {
        "spy_above_20ema": spy_above_20ema,
        "spy_above_50ema": spy_above_50ema,
        "spy_above_200ema": spy_above_200ema,
        "spy_adx": round(spy_adx, 2),
        "vix": round(vix, 2) if vix is not None else None,
        "market_score": score,
        "risk_level": risk_level,
    }


def _calc_adx(highs: list, lows: list, closes: list, period: int = 14) -> float:
    """
    自实现ADX（不用TA-Lib）
    所有输入输出均为百分比（相对于前收盘价）。
    """
    if len(closes) < period + 1:
        return 0.0

    # 第一步：计算并归一化为百分比
    tr_pct, pdm_pct, mdm_pct = [], [], []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        up  = max(highs[i] - highs[i - 1], 0.0)
        dn  = max(lows[i - 1] - lows[i], 0.0)
        c   = closes[i - 1]            # 前收盘价为基准
        tr_pct.append(tr / c * 100)
        pdm_pct.append(up  / c * 100)
        mdm_pct.append(dn  / c * 100)

    n = len(tr_pct)
    if n < period:
        return 0.0

    # Wilder EMA 平滑
    def _wilder_ema(data):
        """Wilder EMA：首值为SMA，之后每次 +alpha*(新值-旧值)"""
        alpha = 1.0 / period
        n_data = len(data)
        result = [sum(data[:period]) / period]  # 首个 smoothed value = SMA
        for i in range(period, n_data):
            result.append(result[-1] + alpha * (data[i] - result[-1]))
        return result

    tr_s  = _wilder_ema(tr_pct)
    pdm_s = _wilder_ema(pdm_pct)
    mdm_s = _wilder_ema(mdm_pct)

    # +DI, -DI (%)
    # tr_s has length n-period+1 (first=SMA, then EMA from index=period)
    m = len(tr_s)  # = n - period + 1
    plus_di  = [pdm_s[i] / tr_s[i] * 100 if tr_s[i] > 0 else 0.0 for i in range(m)]
    minus_di = [mdm_s[i] / tr_s[i] * 100 if tr_s[i] > 0 else 0.0 for i in range(m)]

    # DX
    dx = [abs(plus_di[i] - minus_di[i]) / (plus_di[i] + minus_di[i]) * 100
          if (plus_di[i] + minus_di[i]) > 0 else 0.0 for i in range(m)]

    # ADX = Wilder EMA of DX
    adx_ema = _wilder_ema(dx)
    return round(adx_ema[-1], 2)


def _empty_market_result() -> dict:
    return {
        "spy_above_20ema": False,
        "spy_above_50ema": False,
        "spy_above_200ema": False,
        "spy_adx": 0.0,
        "vix": None,
        "market_score": 0,
        "risk_level": "OFF",
    }


if __name__ == "__main__":
    # 示例用法
    import json

    # 构造模拟SPY数据
    import random

    def _gen_klines(days: int = 300) -> dict:
        data = []
        close = 400.0
        for i in range(days):
            ymd = f"2024-01-{(i % 28) + 1:02d}"
            if i >= 28:
                ymd = f"2024-{(i // 28) + 1:02d}_{(i % 28) + 1:02d}"
            close += random.uniform(-2, 2.5)
            high = close + random.uniform(0, 1.5)
            low = close - random.uniform(0, 1.5)
            data.append({
                "ymd": ymd,
                "open": round(low + 0.3, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "adj": round(close, 2),
                "vol": int(random.uniform(30e6, 80e6)),
            })
        return {"ticker": "SPY", "interval": "1d", "count": len(data), "data": data}

    spy = _gen_klines()
    result = calc_market_score(spy)
    print("Market Score:", json.dumps(result, indent=2))
