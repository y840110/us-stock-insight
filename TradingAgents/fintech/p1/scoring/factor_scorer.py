"""
六因子评分器：将 calc_all_factors() 输出的因子字典转换为评分、评级、仓位
"""

from typing import TypedDict


class CompositeScore(TypedDict):
    """calc_composite_score 返回类型"""
    market_score: int       # 0~30
    rs_score: int           # 0~25
    trend_score: int        # 0~20
    volume_score: int       # 0~15
    volatility_score: int   # 0~10
    total_score: int        # 0~100
    rating: str             # 'A+' | 'A' | 'B' | 'C' | 'D'
    action: str             # 'LONG' | 'WATCH' | 'ABANDON'
    position_size: float    # 1.0 | 0.5 | 0.25 | 0.0


def calc_composite_score(factors: dict) -> CompositeScore:
    """
    将完整因子字典转换为综合评分

    Args:
        factors: calc_all_factors() 输出的完整因子字典

    Returns:
        {
            'market_score': int,      # 0~30
            'rs_score': int,          # 0~25
            'trend_score': int,       # 0~20
            'volume_score': int,      # 0~15
            'volatility_score': int, # 0~10
            'total_score': int,       # 0~100
            'rating': str,            # 'A+' / 'A' / 'B' / 'C' / 'D'
            'action': str,            # 'LONG' / 'WATCH' / 'ABANDON'
            'position_size': float,   # 1.0 / 0.5 / 0.25 / 0.0
        }

    评分映射：
    | 总分   | 评级 | 动作   | 仓位  |
    |--------|------|--------|-------|
    | ≥ 85   | A+   | LONG   | 1.0   |
    | 75~84  | A    | LONG   | 0.5   |
    | 60~74  | B    | WATCH  | 0.25  |
    | 40~59  | C    | ABANDON| 0.0   |
    | < 40   | D    | ABANDON| 0.0   |
    """
    # 提取各因子分（兼容不同字段名）
    market_score = int(factors.get("market_score", 0))
    rs_score = int(factors.get("rs_score", 0))
    trend_score = int(factors.get("trend_score", 0))
    volume_score = int(factors.get("volume_score", 0))
    # volatility 有时叫 vol_score，有时叫 volatility_score
    volatility_score = int(factors.get("vol_score", factors.get("volatility_score", 0)))

    total_score = market_score + rs_score + trend_score + volume_score + volatility_score

    # 评分映射
    if total_score >= 85:
        rating = "A+"
        action = "LONG"
        position_size = 1.0
    elif total_score >= 75:
        rating = "A"
        action = "LONG"
        position_size = 0.5
    elif total_score >= 60:
        rating = "B"
        action = "WATCH"
        position_size = 0.25
    elif total_score >= 40:
        rating = "C"
        action = "ABANDON"
        position_size = 0.0
    else:
        rating = "D"
        action = "ABANDON"
        position_size = 0.0

    return CompositeScore(
        market_score=market_score,
        rs_score=rs_score,
        trend_score=trend_score,
        volume_score=volume_score,
        volatility_score=volatility_score,
        total_score=total_score,
        rating=rating,
        action=action,
        position_size=position_size,
    )


# ----------------------------------------------------------------------
# 单元测试
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # 测试1：全满分 → A+, LONG, 1.0
    f满分 = dict(
        market_score=30,
        rs_score=25,
        trend_score=20,
        volume_score=15,
        vol_score=10,
    )
    r = calc_composite_score(f满分)
    assert r["total_score"] == 100, f"满分100，实际={r['total_score']}"
    assert r["rating"] == "A+"
    assert r["action"] == "LONG"
    assert r["position_size"] == 1.0
    print("✅ 满分测试通过")

    # 测试2：A档边界 75分
    f75 = dict(market_score=30, rs_score=25, trend_score=20, volume_score=0, vol_score=0)
    r = calc_composite_score(f75)
    assert r["rating"] == "A"
    assert r["action"] == "LONG"
    assert r["position_size"] == 0.5
    print("✅ A档边界测试通过")

    # 测试3：B档 60~74 → WATCH, 0.25
    f65 = dict(market_score=15, rs_score=20, trend_score=15, volume_score=10, vol_score=5)
    r = calc_composite_score(f65)
    assert r["rating"] == "B"
    assert r["action"] == "WATCH"
    assert r["position_size"] == 0.25
    print("✅ B档测试通过")

    # 测试4：C档 40~59 → ABANDON, 0.0
    f50 = dict(market_score=10, rs_score=15, trend_score=10, volume_score=10, vol_score=5)
    r = calc_composite_score(f50)
    assert r["rating"] == "C"
    assert r["action"] == "ABANDON"
    assert r["position_size"] == 0.0
    print("✅ C档测试通过")

    # 测试5：D档 <40
    f30 = dict(market_score=5, rs_score=10, trend_score=5, volume_score=5, vol_score=5)
    r = calc_composite_score(f30)
    assert r["rating"] == "D"
    assert r["action"] == "ABANDON"
    assert r["position_size"] == 0.0
    print("✅ D档测试通过")

    # 测试6：兼容 vol_score vs volatility_score
    f1 = dict(market_score=30, rs_score=25, trend_score=20, volume_score=15, vol_score=5)
    f2 = dict(market_score=30, rs_score=25, trend_score=20, volume_score=15, volatility_score=5)
    r1 = calc_composite_score(f1)
    r2 = calc_composite_score(f2)
    assert r1["volatility_score"] == r2["volatility_score"] == 5
    print("✅ vol_score/volatility_score 兼容测试通过")

    # 测试7：缺失字段默认0
    f_empty = {}
    r = calc_composite_score(f_empty)
    assert r["total_score"] == 0
    assert r["rating"] == "D"
    print("✅ 空输入默认0分测试通过")

    print("\n🎉 所有单元测试通过！")
