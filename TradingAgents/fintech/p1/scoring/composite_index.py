"""
板块综合热度指数：板块内股票平均评分、RS百分位、放量家数、创新高家数
"""

from typing import TypedDict, Optional
from .factor_scorer import calc_composite_score


class SectorHeat(TypedDict):
    """calc_sector_heat 返回类型"""
    sector_name: str
    avg_score: float           # 板块内股票平均评分
    stock_count: int           # 成分股数量
    heat_level: str            # 'HOT' | 'WARM' | 'COLD'
    leader_tickers: list[str]  # 评分最高的3只
    avg_rs: float              # 板块平均RS（相对SPY）
    rising_count: int          # 上涨家数
    volume_burst_count: int    # 放量家数（量比>1.5）
    new_high_count: int         # 20日新高家数


def calc_sector_heat(
    sector_name: str,
    sector_stocks: list[dict],
    spy_klines: Optional[dict] = None,
) -> SectorHeat:
    """
    计算板块热度

    Args:
        sector_name: 板块名称
        sector_stocks: 板块内成分股列表，每个元素为完整因子字典（calc_all_factors输出）
        spy_klines: SPY K线数据（用于计算新高，不必需）

    Returns:
        {
            'sector_name': str,
            'avg_score': float,
            'stock_count': int,
            'heat_level': 'HOT' | 'WARM' | 'COLD',
            'leader_tickers': list[str],   # 评分最高的3只
            'avg_rs': float,
            'rising_count': int,
            'volume_burst_count': int,
            'new_high_count': int,
        }

    热度等级规则：
    - HOT: avg_score ≥ 70 或 leader_tickers 中有 ≥ 2 只 A+ 档
    - WARM: 50 ≤ avg_score < 70
    - COLD: avg_score < 50
    """
    if not sector_stocks:
        return SectorHeat(
            sector_name=sector_name,
            avg_score=0.0,
            stock_count=0,
            heat_level="COLD",
            leader_tickers=[],
            avg_rs=0.0,
            rising_count=0,
            volume_burst_count=0,
            new_high_count=0,
        )

    scored = []
    rs_sum = 0.0
    rising_count = 0
    volume_burst_count = 0
    new_high_count = 0
    apx_count = 0

    for stock in sector_stocks:
        cs = calc_composite_score(stock)
        ticker = stock.get("ticker", "?")
        scored.append((ticker, cs["total_score"], cs))

        rs_20d = stock.get("rs_20d", 0)
        rs_sum += rs_20d

        if stock.get("above_20ema") and stock.get("above_50ema"):
            rising_count += 1

        if stock.get("breakout_volume"):
            volume_burst_count += 1

        # 20日新高：当前收盘价 >= 近20日最高价
        if _is_near_20d_high(stock):
            new_high_count += 1

        if cs["rating"] == "A+":
            apx_count += 1

    stock_count = len(sector_stocks)
    avg_score = sum(s for _, s, _ in scored) / stock_count if stock_count else 0.0
    avg_rs = rs_sum / stock_count if stock_count else 0.0

    # 按评分降序取前3
    scored.sort(key=lambda x: x[1], reverse=True)
    leader_tickers = [t for t, _, _ in scored[:3]]

    # 热度等级
    if avg_score >= 70 or apx_count >= 2:
        heat_level = "HOT"
    elif avg_score >= 50:
        heat_level = "WARM"
    else:
        heat_level = "COLD"

    return SectorHeat(
        sector_name=sector_name,
        avg_score=round(avg_score, 2),
        stock_count=stock_count,
        heat_level=heat_level,
        leader_tickers=leader_tickers,
        avg_rs=round(avg_rs, 4),
        rising_count=rising_count,
        volume_burst_count=volume_burst_count,
        new_high_count=new_high_count,
    )


def _is_near_20d_high(stock: dict, tolerance: float = 0.02) -> bool:
    """
    判断当前收盘价是否接近20日高点（容差 ±2%）

    Args:
        stock: 因子字典（需含 data 字段）
        tolerance: 容差，默认 2%

    Returns:
        True if close >= (1 - tolerance) * 20d_high
    """
    data = stock.get("data", [])
    if not data or len(data) < 20:
        return False

    closes = [float(d["close"]) for d in data[-20:]]
    high_20d = max(closes)
    latest_close = closes[-1]

    return latest_close >= high_20d * (1 - tolerance)


def rank_sectors(sector_results: list[SectorHeat]) -> list[SectorHeat]:
    """
    对板块热度结果按 avg_score 降序排列

    Args:
        sector_results: calc_sector_heat 的返回值列表

    Returns:
        排序后的列表（评分最高的在最前）
    """
    return sorted(sector_results, key=lambda x: x["avg_score"], reverse=True)


# ----------------------------------------------------------------------
# 单元测试
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import random

    def _gen_klines(days: int = 60, close_start: float = 180.0) -> list[dict]:
        data = []
        close = close_start
        for i in range(days):
            close += random.uniform(-1.5, 2.0)
            data.append({
                "ymd": f"2024-{(i // 30) + 1:02d}_{(i % 30) + 1:02d}",
                "open": round(close - 0.3, 2),
                "high": round(close + random.uniform(0, 1), 2),
                "low": round(close - random.uniform(0, 1), 2),
                "close": round(close, 2),
                "adj": round(close, 2),
                "vol": int(random.uniform(20e6, 80e6)),
            })
        return data

    def make_stock(ticker: str, mkt: int, rs: int, trend: int, vol: int, volc: int) -> dict:
        data = _gen_klines()
        return dict(
            ticker=ticker,
            data=data,
            market_score=mkt,
            rs_score=rs,
            trend_score=trend,
            volume_score=vol,
            vol_score=volc,
            rs_20d=random.uniform(0, 15),
            above_20ema=True,
            above_50ema=True,
            breakout_volume=(vol > 10),
        )

    # 测试1：HOT 板块（高评分）
    hot_stocks = [
        make_stock("A", 28, 24, 19, 14, 9),
        make_stock("B", 27, 23, 18, 13, 8),
        make_stock("C", 26, 22, 17, 12, 7),
    ]
    r = calc_sector_heat("科技", hot_stocks)
    assert r["heat_level"] == "HOT", f"期望 HOT，实际 {r['heat_level']}"
    assert r["stock_count"] == 3
    assert len(r["leader_tickers"]) == 3
    assert r["avg_score"] > 70
    print(f"✅ HOT 板块测试通过：avg_score={r['avg_score']}")

    # 测试2：WARM 板块
    warm_stocks = [
        make_stock("D", 15, 15, 10, 8, 5),
        make_stock("E", 12, 14, 12, 7, 4),
    ]
    r = calc_sector_heat("金融", warm_stocks)
    assert r["heat_level"] == "WARM", f"期望 WARM，实际 {r['heat_level']}"
    print(f"✅ WARM 板块测试通过：avg_score={r['avg_score']}")

    # 测试3：COLD 板块
    cold_stocks = [
        make_stock("F", 5, 5, 5, 3, 2),
    ]
    r = calc_sector_heat("能源", cold_stocks)
    assert r["heat_level"] == "COLD", f"期望 COLD，实际 {r['heat_level']}"
    print(f"✅ COLD 板块测试通过：avg_score={r['avg_score']}")

    # 测试4：空板块
    r = calc_sector_heat("空板块", [])
    assert r["stock_count"] == 0
    assert r["heat_level"] == "COLD"
    assert r["leader_tickers"] == []
    print(f"✅ 空板块测试通过")

    # 测试5：leader_tickers 排序正确
    stocks = [
        make_stock("LOW", 10, 10, 10, 5, 2),
        make_stock("MID", 20, 20, 15, 10, 5),
        make_stock("HIGH", 30, 25, 20, 15, 10),
    ]
    r = calc_sector_heat("测试板块", stocks)
    assert r["leader_tickers"] == ["HIGH", "MID", "LOW"], f"排序错误：{r['leader_tickers']}"
    print(f"✅ leader_tickers 排序测试通过：{r['leader_tickers']}")

    # 测试6：rank_sectors
    sectors = [
        calc_sector_heat("板块C", [make_stock("X", 10, 10, 10, 5, 5)]),
        calc_sector_heat("板块A", [make_stock("Y", 30, 30, 20, 15, 10)]),
        calc_sector_heat("板块B", [make_stock("Z", 20, 20, 15, 10, 5)]),
    ]
    ranked = rank_sectors(sectors)
    names = [s["sector_name"] for s in ranked]
    assert names == ["板块A", "板块B", "板块C"], f"板块排序错误：{names}"
    print(f"✅ rank_sectors 测试通过：{names}")

    # 测试7：volume_burst_count / rising_count
    s1 = make_stock("VOL", 20, 20, 20, 14, 8)  # vol>10 → breakout_volume=True
    r = calc_sector_heat("量能测试", [s1])
    assert r["volume_burst_count"] >= 1
    print(f"✅ volume_burst_count 测试通过：{r['volume_burst_count']}")

    print("\n🎉 所有 composite_index 单元测试通过！")
