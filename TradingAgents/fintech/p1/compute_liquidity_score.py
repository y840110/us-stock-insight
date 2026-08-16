#!/usr/bin/env python3
"""
LIQUIDITY_SCORE 计算引擎
==========================

描述：
    LIQUIDITY_SCORE 是衡量美国金融市场流动性的综合指标，基于美联储每周发布的
    H.4.1 资产负债表数据计算。

构成因子（各因子先做 Z-score 标准化，再加权平均）：
    LIQUIDITY_SCORE = walcl_z * 0.4 + rrp_z * 0.3 + tga_z * 0.3

三个分项指标说明：
───────────────────────────────────────────────────────────────
1. WALCL（Fed Total Assets / 联储总资产）
   ───────────────────────────────────────
   FRED 代码   ：WALCL（Weekly Update of the H.4.1 Factors...）
   数据来源   ：https://www.federalreserve.gov/releases/h41/
   H.4.1 标签 ：Reserve Bank credit
   单位       ：百万美元（Million USD）
   含义       ：
     - 联储资产负债表的总资产规模
     - 全球美元流动性的"锚"
     - WALCL ↑ = 量化宽松 / 流动性注入
     - WALCL ↓ = 量化紧缩 / 流动性回收

   Z-score 含义：
     - Z > 0：当前流动性高于过去 252 个交易日的均值（偏宽松）
     - Z < 0：当前流动性低于均值（偏紧缩）

───────────────────────────────────────────────────────────────
2. RRPONTSYD（隔夜逆回购 / Overnight Reverse Repurchase）
   ──────────────────────────────────────────────────────────
   FRED 代码   ：RRPONTSYD（Straight-line Premium / Discounts... 旧代码）
   实际含义   ：ONRRP 总规模（Overnight Reverse Repurchase）
   数据来源   ：https://www.federalreserve.gov/releases/h41/
   H.4.1 标签 ：Reverse repurchase agreements（总额 = foreign + others）
   单位       ：百万美元（Million USD）
   含义       ：
     - 隔夜逆回购协议总额（非机构专用）
     - 货币市场基金等对手方存放在 Fed 的过剩流动性
     - RRP ↑ = 金融市场有大量过剩流动性无处可去（偏宽松信号）
     - RRP ↓ = 过剩流动性被吸收回实体经济或购债（偏紧缩信号）

   ⚠️ 重要：RRP 数据在 H.4.1 表中有两项：
     - "Reverse repurchase agreements"（表1Liabilities，Wednesday列）- 本指标使用这个
     - 数值 = foreign official + others 两项之和
   若某日 H.4.1 表格中 RRP 字段为空（极少发生），则默认沿用上一周的值
   （RRP 变化较为平滑，不会剧烈跳动）

───────────────────────────────────────────────────────────────
3. WTREGEN（财政部活期账户 / Treasury General Account）
   ──────────────────────────────────────────────────────────
   FRED 代码   ：WTREGEN（U.S. Treasury General Account Balance）
   数据来源   ：https://www.federalreserve.gov/releases/h41/
   H.4.1 标签 ：U.S. Treasury, General Account
   单位       ：百万美元（Million USD）
   含义       ：
     - 财政部在 Fed 的活期存款余额
     - TGA ↑ = 财政部在囤积现金（回收流动性，偏紧缩信号）
     - TGA ↓ = 财政部在花钱/拨付（释放流动性，偏宽松信号）
     - 注意：2023-2024 年 TGA 变动较大，需关注趋势而非单周数值

───────────────────────────────────────────────────────────────
权重设计逻辑：
    - WALCL * 0.4：作为总锚，权重最高
    - RRP  * 0.3：反映银行间市场过剩程度
    - TGA  * 0.3：反映财政政策对流动性的影响

Z-score 计算方法：
    z = (value - mean_window) / std_window
    窗口：20 个交易周（约 5 个月），每周只新增 1 个数据点
    （注：FRED 原始公式用 252 日，但 H.4.1 为周数据，20 周 ≈ 5 个月更实用）

输出：
    LIQUIDITY_SCORE > 0：整体流动性偏宽松（利好风险资产）
    LIQUIDITY_SCORE < 0：整体流动性偏紧缩（利空风险资产）
    |SCORE| > 2：极端信号（警惕）

数据更新频率：每周（H.4.1 每周四发布，数据截止周三）

用法：
    python3 compute_liquidity_score.py          # 增量计算并保存
    python3 compute_liquidity_score.py --full   # 全量重新计算
    python3 compute_liquidity_score.py --check # 仅显示最新值
    python3 compute_liquidity_score.py --days N # 计算最近N周并保存
"""

import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# ──────────────────────────────────────────────────────────────
# 路径配置
# ──────────────────────────────────────────────────────────────

PROJ   = Path(__file__).parent.parent.parent          # .../TradingAgents/
KLINE  = PROJ / "fintech" / "p1" / "klines"         # K线数据目录
OUTPUT = PROJ / "中间过程" / "market_indicators"     # 输出目录

OUTPUT.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────────────────────
# Z-score 计算
# ──────────────────────────────────────────────────────────────

def calc_zscore(series: list[float], window: int = 20) -> list[float]:
    """
    计算滚动 Z-score 序列。

    参数:
        series: 按时间顺序排列的数值序列（ oldest → newest ）
        window: 滚动窗口大小（默认 20 周 ≈ 5个月；日数据用 252）

    返回:
        zscore 序列，长度与输入相同。前 window-1 个点返回 0.0（数据不足）
    """
    zscores = []
    for i in range(len(series)):
        if i < window - 1:
            zscores.append(0.0)
        else:
            window_slice = series[i - window + 1 : i + 1]
            mean = sum(window_slice) / window
            variance = sum((x - mean) ** 2 for x in window_slice) / window
            std = math.sqrt(variance)
            if std < 1e-12:
                zscores.append(0.0)
            else:
                zscores.append((series[i] - mean) / std)
    return zscores


# ──────────────────────────────────────────────────────────────
# 读取 H.4.1 原始数据
# ──────────────────────────────────────────────────────────────

def load_raw(symbol: str) -> list[dict]:
    """加载单个指标的 JSON 数据文件"""
    file_path = KLINE / f"{symbol}_1d.json"
    if not file_path.exists():
        return []
    with open(file_path, encoding="utf-8") as f:
        obj = json.load(f)
    return obj.get("data", [])


def load_merged_series() -> dict[str, list[tuple[str, float]]]:
    """
    加载三个指标，并按日期对齐合并。

    RRP 特殊处理：
        若某日 RRP 数据缺失（极少），用前一个有效值 forward-fill。
        这样可以保证 Z-score 计算连续。

    返回:
        {
            "WALCL": [("2026-04-29", 6656666), ...],
            "RRP":   [("2026-04-29", 317998),  ...],
            "TGA":   [("2026-04-29", 981929),  ...],
        }
    """
    walcl_raw = load_raw("WALCL")
    rrp_raw   = load_raw("RRPONTSYD")
    tga_raw   = load_raw("WTREGEN")

    def to_ordered(raw: list) -> list[tuple]:
        return sorted([(r["date"], float(r["value"])) for r in raw], key=lambda x: x[0])

    walcl_series = to_ordered(walcl_raw)
    rrp_series   = to_ordered(rrp_raw)
    tga_series   = to_ordered(tga_raw)

    # Forward-fill RRP（RRP 若当日无数据等同于之前）
    if rrp_series:
        filled_rrp = [rrp_series[0]]
        for i in range(1, len(rrp_series)):
            date, val = rrp_series[i]
            if val == 0 or val is None:
                # RRP 无数据时向前取值（极少发生）
                filled_rrp.append((date, filled_rrp[-1][1]))
            else:
                filled_rrp.append((date, val))
        rrp_series = filled_rrp

    return {
        "WALCL": walcl_series,
        "RRP":   rrp_series,
        "TGA":   tga_series,
    }


# ──────────────────────────────────────────────────────────────
# 核心计算
# ──────────────────────────────────────────────────────────────

def compute_liquidity_score(
    walcl_series: list[tuple[str, float]],
    rrp_series:   list[tuple[str, float]],
    tga_series:   list[tuple[str, float]],
    z_window: int = 20,   # 周数据：20周≈5个月；日数据：252
) -> list[dict]:
    """
    计算 LIQUIDITY_SCORE 历史序列。

    公式：
        LIQUIDITY_SCORE = walcl_z * 0.4 + rrp_z * 0.3 + tga_z * 0.3

    参数:
        walcl_series: [(date, value), ...] 有序列表
        rrp_series:   [(date, value), ...] 有序列表（已 forward-fill）
        tga_series:   [(date, value), ...] 有序列表
        z_window:     Z-score 滚动窗口（默认 20 周 ≈ 5个月，周数据专用）

    返回:
        [{"date": "YYYY-MM-DD", "score": float, "walcl_z": float, "rrp_z": float, "tga_z": float}, ...]
    """
    # 提取纯数值序列
    walcl_vals = [v for _, v in walcl_series]
    rrp_vals   = [v for _, v in rrp_series]
    tga_vals   = [v for _, v in tga_series]

    # 计算 Z-score
    walcl_z = calc_zscore(walcl_vals, z_window)
    rrp_z   = calc_zscore(rrp_vals,   z_window)
    tga_z   = calc_zscore(tga_vals,   z_window)

    # 以 WALCL 日期为基准（左对齐所有日期）
    # 取三个序列的公共部分（最早和最新共同覆盖的日期）
    all_dates_walcl = [d for d, _ in walcl_series]
    results = []

    for i, (date, walcl_val) in enumerate(walcl_series):
        # 找到 RRP 和 TGA 中对应日期的 index
        rrp_i = next((j for j, (d, _) in enumerate(rrp_series) if d == date), None)
        tga_i = next((j for j, (d, _) in enumerate(tga_series) if d == date), None)

        if rrp_i is None or tga_i is None:
            continue

        w_z = walcl_z[i] if i < len(walcl_z) else 0.0
        r_z = rrp_z[rrp_i]   if rrp_i < len(rrp_z) else 0.0
        t_z = tga_z[tga_i]   if tga_i < len(tga_z) else 0.0

        score = w_z * 0.4 + r_z * 0.3 + t_z * 0.3

        results.append({
            "date":   date,
            "score":  round(score, 4),
            "walcl_z": round(w_z, 4),
            "rrp_z":   round(r_z, 4),
            "tga_z":   round(t_z, 4),
        })

    return results


def compute_and_save(days: Optional[int] = None) -> list[dict]:
    """
    主函数：加载数据 → 计算 → 保存 LIQUIDITY_SCORE_1d.json

    参数:
        days: 若指定，只保存最近 N 条；若 None，保存全部

    返回:
        计算结果列表
    """
    print("[INFO] 加载 H.4.1 数据...")
    series = load_merged_series()
    print(f"  WALCL: {len(series['WALCL'])} 条, 范围 {series['WALCL'][0][0]} ~ {series['WALCL'][-1][0]}")
    print(f"  RRP:   {len(series['RRP'])} 条, 范围 {series['RRP'][0][0]} ~ {series['RRP'][-1][0]}")
    print(f"  TGA:   {len(series['TGA'])} 条, 范围 {series['TGA'][0][0]} ~ {series['TGA'][-1][0]}")

    print("\n[INFO] 计算 Z-score (window=20, 周数据≈5个月)...")
    results = compute_liquidity_score(
        series["WALCL"],
        series["RRP"],
        series["TGA"],
    )
    print(f"  共计算 {len(results)} 个 LIQUIDITY_SCORE")

    if days:
        results = results[-days:]

    # 保存
    out_file = OUTPUT / "LIQUIDITY_SCORE_1d.json"
    obj = {
        "name":        "LIQUIDITY_SCORE",
        "formula":     "LIQUIDITY_SCORE = WALCL_z * 0.4 + RRP_z * 0.3 + TGA_z * 0.3",
        "description": (
            "WALCL_z = Z-score(Fed Total Assets, 20w rolling ≈ 5months); "
            "RRP_z = Z-score(ONRRP, 20w rolling, forward-fill); "
            "TGA_z = Z-score(Treasury General Account, 20w rolling)"
        ),
        "weights": {"WALCL": 0.4, "RRP": 0.3, "TGA": 0.3},
        "source":  "Federal Reserve H.4.1 (weekly, via Chrome CDP)",
        "unit":    "Z-score (dimensionless)",
        "last_updated": datetime.now().isoformat(),
        "data":    results,
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

    print(f"\n[OK] 保存到 {out_file}")
    return results


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LIQUIDITY_SCORE 计算")
    parser.add_argument("--check", action="store_true", help="仅显示最新值")
    parser.add_argument("--days",  type=int, default=None, help="只保存最近N条")
    parser.add_argument("--full",  action="store_true", help="全量重新计算（所有历史）")
    args = parser.parse_args()

    results = compute_and_save(days=args.days if not args.full else None)

    if args.check:
        latest = results[-1] if results else None
        if latest:
            print(f"\n📊 LIQUIDITY_SCORE 最新值 ({latest['date']}):")
            print(f"  综合得分:  {latest['score']:+.4f}")
            print(f"  WALCL Z:   {latest['walcl_z']:+.4f} (权重 0.4)")
            print(f"  RRP   Z:   {latest['rrp_z']:+.4f} (权重 0.3)")
            print(f"  TGA   Z:   {latest['tga_z']:+.4f} (权重 0.3)")
            sig = "🟢 宽松" if latest['score'] > 0 else "🔴 紧缩"
            print(f"  信号:      {sig} ({'|SCORE|>2' if abs(latest['score']) > 2 else '正常范围'})")
        else:
            print("[WARN] 无计算结果")
    else:
        latest = results[-1] if results else None
        if latest:
            print(f"\n✅ 最新: {latest['date']}  SCORE={latest['score']:+.4f}  WALCL_z={latest['walcl_z']:+.4f}  RRP_z={latest['rrp_z']:+.4f}  TGA_z={latest['tga_z']:+.4f}")
