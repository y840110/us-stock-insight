"""
US Stock Quantitative System - Feature Layer
因子计算层：市场因子、RS、趋势、量能、波动率、价格结构
"""

from .market_indicators import calc_market_score
from .rs_indicators import calc_rs
from .trend_indicators import calc_trend_score
from .volume_indicators import calc_volume_score
from .volatility_indicators import calc_volatility_score
from .price_structure import calc_price_structure
from .ml_features import calc_ml_features

__all__ = [
    "calc_market_score",
    "calc_rs",
    "calc_trend_score",
    "calc_volume_score",
    "calc_volatility_score",
    "calc_price_structure",
    "calc_all_factors",
]


def calc_all_factors(
    ticker: str,
    klines: dict,
    spy_klines: dict,
    vix_klines: dict = None,
    interval: str = "1d",
) -> dict:
    """
    合并所有因子，返回完整因子字典（用于ML输入 + 评分）

    Args:
        ticker: 股票代码
        klines: 股票K线数据（JSON格式）
        spy_klines: SPY K线数据（市场基准）
        vix_klines: VIX K线数据（可选）
        interval: K线周期 ('1d' 或 '1wk')

    Returns:
        完整因子字典，包含所有子模块的计算结果
    """
    # ---- 标准化 date→ymd（铁律：所有因子模块以 ymd 为锚）----
    # 部分K线文件 date 字段为 MMM DD, YYYY 格式
    def _standardize(klines_dict):
        if klines_dict and "data" in klines_dict:
            for bar in klines_dict["data"]:
                if "date" in bar and "ymd" not in bar:
                    bar["ymd"] = bar.pop("date")
                if "volume" in bar and "vol" not in bar:
                    bar["vol"] = bar.pop("volume")
        return klines_dict

    klines = _standardize(klines)
    if spy_klines:
        spy_klines = _standardize(spy_klines)
    if vix_klines:
        vix_klines = _standardize(vix_klines)

    market = calc_market_score(spy_klines, vix_klines) if spy_klines else {}
    rs = calc_rs(klines, spy_klines)
    trend = calc_trend_score(klines)
    volume = calc_volume_score(klines)
    volatility = calc_volatility_score(klines)
    price_struct = calc_price_structure(klines)
    ml_feats = calc_ml_features(klines)  # ML 原始特征

    # RS 原始数据也加入 ml_feats
    ml_feats["rs_5d"] = rs.get("rs_5d", 0.0)

    # 计算总分（满分100）
    total_score = (
        market.get("market_score", 0)
        + rs.get("rs_score", 0)
        + trend.get("trend_score", 0)
        + volume.get("volume_score", 0)
        + volatility.get("vol_score", 0)
    )

    # 合并所有因子
    result = {
        # 原始数据
        "ticker": ticker,
        "interval": interval,
        # 市场因子
        "spy_above_20ema": market.get("spy_above_20ema", False),
        "spy_above_50ema": market.get("spy_above_50ema", False),
        "spy_above_200ema": market.get("spy_above_200ema", False),
        "spy_adx": market.get("spy_adx", 0.0),
        "vix": market.get("vix", None),
        "market_score": market.get("market_score", 0),
        "risk_level": market.get("risk_level", "OFF"),
        # RS因子
        "rs_20d": rs.get("rs_20d", 0.0),
        "rs_65d": rs.get("rs_65d", 0.0),
        "rs_score": rs.get("rs_score", 0),
        "rs_rank": rs.get("rs_rank", 0.0),
        # 趋势因子
        "above_20ema": trend.get("above_20ema", False),
        "above_50ema": trend.get("above_50ema", False),
        "ema20_above_ema50": trend.get("ema20_above_ema50", False),
        "ema50_above_ema200": trend.get("ema50_above_ema200", False),
        "weekly_ema20_rising": trend.get("weekly_ema20_rising", False),
        "trend_score": trend.get("trend_score", 0),
        "ema_values": trend.get("ema_values", {}),
        # 量能因子
        "vol_ma20": volume.get("vol_ma20", 0.0),
        "vol_ratio": volume.get("vol_ratio", 0.0),
        "pullback_shrinking": volume.get("pullback_shrinking", False),
        "breakout_volume": volume.get("breakout_volume", False),
        "volume_score": volume.get("volume_score", 0),
        # 波动率因子
        "atr14": volatility.get("atr14", 0.0),
        "atr_pct": volatility.get("atr_pct", 0.0),
        "vol_score": volatility.get("vol_score", 0),
        # 价格结构（ML特征）
        "candle_body_ratio": price_struct.get("candle_body_ratio", 0.0),
        "upper_wick_ratio": price_struct.get("upper_wick_ratio", 0.0),
        "lower_wick_ratio": price_struct.get("lower_wick_ratio", 0.0),
        "volatility_20d": price_struct.get("volatility_20d", 0.0),
        "volatility_65d": price_struct.get("volatility_65d", 0.0),
        "high_low_range": price_struct.get("high_low_range", 0.0),
        "volume_ratio": price_struct.get("volume_ratio", 0.0),
        "max_drawdown_20d": price_struct.get("max_drawdown_20d", 0.0),
        # 总分
        "total_score": total_score,
    }

    # 追加 ML 原始特征（与训练特征名完全一致）
    result.update(ml_feats)

    return result
