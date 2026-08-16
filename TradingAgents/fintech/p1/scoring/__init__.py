"""
US Stock Quantitative System - Scoring Layer
评分层：六因子评分、综合信号生成、板块热度指数
"""

from .factor_scorer import calc_composite_score
from .signal_generator import SignalGenerator
from .composite_index import calc_sector_heat

__all__ = [
    "calc_composite_score",
    "SignalGenerator",
    "calc_sector_heat",
]
