"""
ml_features.py - 计算 ML 模型所需的原始技术指标
填补 calc_all_factors() 与训练特征之间的差距。
"""

import numpy as np
from typing import Optional


def calc_ml_features(klines: dict) -> dict:
    """
    计算 ML 训练/推理所需的全部原始技术指标。

    与 calc_all_factors() 的评分因子互补：
    - calc_all_factors: 人类可读评分 (0-100)
    - 本函数: ML 模型需要的原始数值特征

    返回与 DatasetBuilder.build() 训练时完全一致的30个特征。
    """
    data = klines.get("data", [])
    if len(data) < 5:
        return _empty_features()

    # 确保 ymd 字段存在（部分K线只有date字段）
    for bar in data:
        if "date" in bar and "ymd" not in bar:
            bar["ymd"] = bar.pop("date")

    # 提取数值
    closes = np.array([float(bar.get("close", 0)) for bar in data], dtype=np.float64)
    highs = np.array([float(bar.get("high", 0)) for bar in data], dtype=np.float64)
    lows = np.array([float(bar.get("low", 0)) for bar in data], dtype=np.float64)
    vols = np.array([float(bar.get("vol", 0)) for bar in data], dtype=np.float64)

    result = _empty_features()

    # ===== 回报率 =====
    result["return_1d"] = float((closes[-1] / closes[-2] - 1)) if closes[-2] != 0 else 0.0
    result["return_5d"] = float((closes[-1] / closes[-6] - 1)) if closes[-6] != 0 else 0.0
    result["return_10d"] = float((closes[-1] / closes[-11] - 1)) if closes[-11] != 0 else 0.0
    result["return_20d"] = float((closes[-1] / closes[-21] - 1)) if closes[-21] != 0 else 0.0

    # ===== 移动平均 =====
    for w in [5, 10, 20, 50, 200]:
        if len(closes) >= w:
            result[f"ma{w}"] = float(np.mean(closes[-w:]))
            # EMA
            alpha = 2.0 / (w + 1)
            ema_val = closes[-w]
            for p in closes[-w+1:]:
                ema_val = alpha * p + (1 - alpha) * ema_val
            result[f"ema{w}"] = float(ema_val)
        else:
            result[f"ma{w}"] = float(np.mean(closes))
            result[f"ema{w}"] = float(np.mean(closes))

    # ===== 均线交叉 =====
    result["ma5_above_ma20"] = 1 if result["ma5"] > result["ma20"] else 0
    result["ma20_above_ma50"] = 1 if result["ma20"] > result["ma50"] else 0
    result["price_above_ma200"] = 1 if closes[-1] > result["ma200"] else 0

    # ===== RSI ( Wilder ) =====
    result["rsi14"] = _rsi(closes, 14)

    # ===== 动量 =====
    result["mom5"] = result["return_5d"]
    result["mom10"] = result["return_10d"]
    result["mom20"] = result["return_20d"]

    # ===== ATR =====
    if len(closes) >= 15:
        tr_list = []
        for i in range(1, len(closes)):
            hl = highs[i] - lows[i]
            hc = abs(highs[i] - closes[i-1])
            lc = abs(lows[i] - closes[i-1])
            tr_list.append(max(hl, hc, lc))
        tr_arr = np.array(tr_list)
        result["atr14"] = float(np.mean(tr_arr[-14:])) if len(tr_arr) >= 14 else float(np.mean(tr_arr))
        result["atr20"] = float(np.mean(tr_arr[-20:])) if len(tr_arr) >= 20 else float(np.mean(tr_arr))
        result["atr14_pct"] = float(result["atr14"] / closes[-1] * 100) if closes[-1] > 0 else 0.0
    else:
        result["atr14"] = float(np.mean(highs - lows))
        result["atr20"] = result["atr14"]

    # ===== 布林带 =====
    if len(closes) >= 20:
        bb_mid = np.mean(closes[-20:])
        bb_std = np.std(closes[-20:], ddof=0)
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        result["bb_pos"] = float((closes[-1] - bb_lower) / (bb_upper - bb_lower)) if (bb_upper - bb_lower) > 0 else 0.5
        result["bb_width"] = float((bb_upper - bb_lower) / bb_mid) if bb_mid > 0 else 0.0
    else:
        result["bb_pos"] = 0.5
        result["bb_width"] = 0.0

    # ===== 成交量 =====
    if len(vols) >= 20:
        result["vol_ma20"] = float(np.mean(vols[-20:]))
        vol_std = float(np.std(vols[-20:], ddof=0))
        result["vol20_std"] = vol_std
        result["vol_ratio"] = float(vols[-1] / result["vol_ma20"]) if result["vol_ma20"] > 0 else 1.0
    else:
        result["vol_ma20"] = float(np.mean(vols))
        result["vol20_std"] = float(np.std(vols, ddof=0))
        result["vol_ratio"] = 1.0

    return result


def _rsi(closes: np.ndarray, period: int = 14) -> float:
    """计算 Wilder RSI"""
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains[-period:]))
    avg_loss = float(np.mean(losses[-period:]))
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def _empty_features() -> dict:
    """返回全零特征字典"""
    return {
        "return_1d": 0.0, "return_5d": 0.0, "return_10d": 0.0, "return_20d": 0.0,
        "ma5": 0.0, "ma10": 0.0, "ma20": 0.0, "ma50": 0.0, "ma200": 0.0,
        "ema5": 0.0, "ema10": 0.0, "ema20": 0.0, "ema50": 0.0, "ema200": 0.0,
        "ma5_above_ma20": 0, "ma20_above_ma50": 0, "price_above_ma200": 0,
        "rsi14": 50.0,
        "mom5": 0.0, "mom10": 0.0, "mom20": 0.0,
        "atr14": 0.0, "atr20": 0.0, "atr14_pct": 0.0,
        "bb_pos": 0.5, "bb_width": 0.0,
        "vol_ma20": 0.0, "vol_ratio": 1.0, "vol20_std": 0.0,
        "rs_5d": 0.0,
    }
