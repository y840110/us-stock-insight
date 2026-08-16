#!/usr/bin/env python3
"""
P3 · 板块分析 v2 — 六大维度量化体系
================================================
基于：Relative Strength · Breadth · 资金流 · 波动率 · 领导股 · 轮动

六维度权重：
  ① Relative Strength  30%  — 板块相对SPY的超额收益
  ② Breadth            20%  — 板块内部股票参与度（站上20EMA比例）
  ③ 资金流             20%  — 量能扩张、ETF流入代理
  ④ 波动率结构         10%  — ATR扩张、趋势强化信号
  ⑤ 领导股健康度       15%  — 板块龙头是否领涨
  ⑥ 轮动方向           5%   — RS排名边际变化

Tier 定义：
  L1（推荐）  final_score ≥ 75
  L2（持有）  60 ≤ score < 75
  L3（低配）  45 ≤ score < 60
  L4（规避）  score < 45

用法：
    from fintech.p3.sector_v2 import analyze_sectors_v2
    result = analyze_sectors_v2(klines_dir)
"""

from __future__ import annotations

import json, math
from pathlib import Path
from typing import Optional

# ══════════════════════════════════════════════════════════════════════════════
# 板块配置
# ══════════════════════════════════════════════════════════════════════════════

SECTOR_ETFS = [
    # GICS 11个一级行业（主 ETF 选 XLK/XLV/XLF 等 SPDR 系列）
    ("XLK",  "科技",       "科技"),
    ("VGT",  "科技(VGT)",  "科技"),
    ("XLV",  "医药",       "医药"),
    ("VHT",  "医药(VHT)",  "医药"),
    ("XLF",  "金融",       "金融"),
    ("VFH",  "金融(VFH)",  "金融"),
    ("XLY",  "可选消费",    "消费"),
    ("VCR",  "可选消费(VCR)","消费"),
    ("XLP",  "必需消费",    "必需消费"),
    ("VDC",  "必需消费(VDC)","必需消费"),
    ("XLI",  "工业",       "工业"),
    ("VIS",  "工业(VIS)",  "工业"),
    ("XLE",  "能源",       "能源"),
    ("VDE",  "能源(VDE)",  "能源"),
    ("XLB",  "材料",       "材料"),
    ("VAW",  "材料(VAW)",  "材料"),
    ("XLRE", "房地产",     "房地产"),
    ("VNQ",  "房地产(VNQ)","房地产"),
    ("XLU",  "公用事业",   "公用事业"),
    ("VPU",  "公用事业(VPU)","公用事业"),
    ("XLC",  "通信服务",   "通信"),
    ("VOX",  "通信服务(VOX)","通信"),
    # 宽基
    ("SPY",  "标普500",    "宽基"),
    ("QQQ",  "纳斯达克100", "宽基"),
    # 半导体主题
    ("SMH",  "半导体ETF",  "半导体"),
    ("SOXX", "半导体",     "半导体"),
    ("SOXL", "半导体3X",   "半导体"),
    ("DRAM", "存储",       "存储"),
    # 加密/贵金属/军工
    ("IBIT", "加密货币",   "加密"),
    ("FBTC", "比特币ETF",  "加密"),
    ("GLD",  "黄金",       "贵金属"),
    ("ITA",  "军工",       "军工"),
]

# 板块内主要成分股（用于 Breadth + Leadership 计算）
SECTOR_LEADERS = {
    "科技":       ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "AVGO"],
    "科技(VGT)":  ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "AVGO"],
    "半导体":     ["NVDA", "ASML", "AMAT", "MU",   "LRCX", "KLAC", "AMKR"],
    "半导体ETF":  ["NVDA", "ASML", "AMAT", "MU",   "LRCX", "KLAC", "AMKR"],
    "半导体3X":  ["NVDA", "ASML", "AMAT", "MU",   "LRCX", "KLAC", "AMKR"],
    "存储":       ["MU",   "NXPI", "SWKS", "QRVO"],
    "金融":       ["JPM",  "GS",   "BAC",  "MS",   "BLK",  "MA",   "COF"],
    "金融(VFH)":  ["JPM",  "GS",   "BAC",  "MS",   "BLK",  "MA",   "COF"],
    "医药":       ["LLY",  "JNJ",  "UNH",  "PFE",  "ABBV", "MRK", "BMY"],
    "医药(VHT)":  ["LLY",  "JNJ",  "UNH",  "PFE",  "ABBV", "MRK", "BMY"],
    "可选消费":   ["AMZN", "TSLA", "HD",   "MCD",  "NKE",  "LOW",  "SBUX"],
    "可选消费(VCR)":["AMZN","TSLA","HD","MCD","NKE","LOW","SBUX"],
    "必需消费":   ["PG",   "KO",   "PEP",  "WMT",  "COST", "MDLZ", "GIS"],
    "必需消费(VDC)":["PG","KO","PEP","WMT","COST","MDLZ","GIS"],
    "工业":       ["CAT",  "HON",  "UNP",  "BA",   "LMT",  "RTX",  "DE"],
    "工业(VIS)":  ["CAT",  "HON",  "UNP",  "BA",   "LMT",  "RTX",  "DE"],
    "能源":       ["XOM",  "CVX",  "COP",  "SLB",  "EOG",  "PSX",  "MPC"],
    "能源(VDE)":  ["XOM",  "CVX",  "COP",  "SLB",  "EOG",  "PSX",  "MPC"],
    "材料":       ["LIN",  "APD",  "SHW",  "ECL",  "NEM",  "FCX",  "DOW"],
    "材料(VAW)":  ["LIN",  "APD",  "SHW",  "ECL",  "NEM",  "FCX",  "DOW"],
    "房地产":     ["AMT",  "PLD",  "EQIX", "CCI",  "SPG",  "PSA",  "O"],
    "房地产(VNQ)":["AMT",  "PLD",  "EQIX", "CCI",  "SPG",  "PSA",  "O"],
    "公用事业":   ["NEE",  "DUK",  "SO",   "D",    "AEP",  "EXC",  "SRE"],
    "公用事业(VPU)":["NEE","DUK","SO","D","AEP","EXC","SRE"],
    "通信服务":   ["GOOGL","META","NFLX","DIS","CMCSA","T","VZ"],
    "通信服务(VOX)":["GOOGL","META","NFLX","DIS","CMCSA","T","VZ"],
    "标普500":    [],    # 宽基指数，用全市场代替
    "纳斯达克100":[],
    "加密货币":   ["COIN", "MSTR", "RIOT", "HUT",  "MARA"],
    "比特币ETF":  ["COIN", "MSTR", "RIOT", "HUT",  "MARA"],
    "黄金":       [],    # 单一商品无成分股
    "贵金属":     [],
    "军工":       ["LHX",  "LMT",  "RTX",  "NOC",  "BA",   "GD",   "GEV"],
}

SPY_TICKER = "SPY"
VIX_TICKER = "VIX"

WEIGHTS = {
    "rs":           0.30,
    "breadth":      0.20,
    "money_flow":   0.20,
    "volatility":   0.10,
    "leadership":   0.15,
    "rotation":     0.05,
}

# ══════════════════════════════════════════════════════════════════════════════
# 底层技术指标
# ══════════════════════════════════════════════════════════════════════════════

def ema(closes: list[float], period: int) -> list[float]:
    if len(closes) < 2:
        return closes
    k = 2.0 / (period + 1)
    out = [closes[0]]
    for c in closes[1:]:
        out.append(c * k + out[-1] * (1 - k))
    return out

def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        trs.append(tr)
    if len(trs) < period:
        return [sum(trs)/len(trs)] * len(closes) if trs else [0.0] * len(closes)
    return ema(trs, period)

def rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 2:
        return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0.0 for d in deltas[-period:]]
    ag = sum(gains) / period
    al = sum(losses) / period
    return 100.0 if al == 0.0 else 100.0 - (100.0 / (1.0 + ag / al))

# ══════════════════════════════════════════════════════════════════════════════
# K线数据加载
# ══════════════════════════════════════════════════════════════════════════════

def load_ohlcv(klines_dir: Path, ticker: str) -> dict | None:
    """加载单只ETF的OHLCV数据，返回dict或None"""
    for suffix in ("", "_1d"):
        fpath = klines_dir / f"{ticker}{suffix}_1d.json"
        if fpath.exists():
            try:
                d = json.load(open(fpath))
                bars = d.get("data") if isinstance(d, dict) else d
                if bars and isinstance(bars, list):
                    return {
                        "dates":  [b["date"] for b in bars],
                        "opens":  [b.get("open",  0) or 0 for b in bars],
                        "highs":  [b.get("high",  0) or 0 for b in bars],
                        "lows":   [b.get("low",   0) or 0 for b in bars],
                        "closes": [b.get("close", 0) or 0 for b in bars],
                        "volume": [b.get("volume",0) or 0 for b in bars],
                    }
            except Exception:
                pass
    return None

def momentum(closes: list[float], period: int) -> float:
    if len(closes) < period + 1:
        return 0.0
    return (closes[-1] / closes[-period-1] - 1) * 100

def vol_ma_ratio(volumes: list[float]) -> float:
    if len(volumes) < 21:
        return 1.0
    ma20 = sum(volumes[-20:]) / 20
    today_vol = volumes[-1]
    return today_vol / ma20 if ma20 > 0 else 1.0

def above_ema_pct(prices: list[float], period: int = 20) -> float:
    """价格站上EMA的比例（用于成分股）"""
    if len(prices) < period + 1:
        return 0.5
    ma = ema(prices, period)[-1]
    return 1.0 if prices[-1] > ma else 0.0

# ══════════════════════════════════════════════════════════════════════════════
# 六大维度计算
# ══════════════════════════════════════════════════════════════════════════════

def calc_rs_score(sector_return: float, spy_return: float) -> tuple[float, float]:
    """
    ① Relative Strength
    RS = sector_return / spy_return（>1 = 跑赢）
    返回 (score_0_100, raw_rs)
    """
    if abs(spy_return) < 0.001:
        rs = 0.0
    else:
        rs = sector_return / spy_return
    # tanh 压缩映射：rs=1 → 50分，rs>1 增幅递减，rs<1 降幅递减
    # 50 + 30*tanh(1.5*(rs-1)) → rs=4.5→97分 rs=2→83分 rs=1→50分 rs=0.5→26分
    import math
    score = 50.0 + 30.0 * math.tanh(1.5 * (rs - 1.0))
    return max(0.0, min(100.0, score)), round(rs, 2)


def calc_breadth_score(sector_name: str, klines_dir: Path) -> tuple[float, float, str]:
    """
    ② Breadth（板块内部参与度）
    站上20EMA的成分股比例
    返回 (score_0_100, raw_pct, detail_str)
    """
    leaders = SECTOR_LEADERS.get(sector_name, [])
    if not leaders:
        # 无成分股数据（如GLD/IBIT/FBTC），返回中性分
        return 50.0, 0.0, "单一资产ETF，无法计算"

    above = 0
    details = []
    for ticker in leaders:
        d = load_ohlcv(klines_dir, ticker)
        if d is None or len(d["closes"]) < 25:
            continue
        pct = above_ema_pct(d["closes"], 20)
        above += pct
        details.append(f"{ticker}:{'✅' if pct > 0.5 else '❌'}")

    if not details:
        return 50.0, 0.0, "无成分股数据"

    breadth_pct = above / len(details)
    score = breadth_pct * 100
    detail = f"{len([d for d in details if '✅' in d])}/{len(details)}成分股站上EMA"
    return score, round(breadth_pct * 100, 1), detail


def calc_money_flow_score(data: dict | None) -> tuple[float, float, str]:
    """
    ③ 资金流
    - vol_ma_ratio > 1 → 放量（机构参与）
    - 20日累积净流入代理：比较近期均价 vs 长期均价（>0 = 资金流入）
    """
    if data is None:
        return 50.0, 1.0, "无数据"

    closes = data["closes"]
    volumes = data["volume"]

    if len(closes) < 21:
        return 50.0, 1.0, "数据不足"

    # 量能比率
    v_ratio = vol_ma_ratio(volumes)  # >1 放量，<1 缩量

    # 资金方向代理：20日均价 vs 60日均价
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else ma20
    price_vs_ma60 = (closes[-1] / ma60 - 1) * 100 if ma60 > 0 else 0.0

    # 评分：量能 > MA20 得高分，价格 > MA60 得高分
    vol_score = min(100.0, v_ratio * 70)  # vol_ratio 1.0 → 70分，1.5 → 105分 cap at 100
    flow_score = 50.0 + (price_vs_ma60 * 5)  # 均价在MA60上方越多越高分
    flow_score = max(0.0, min(100.0, flow_score))

    final = vol_score * 0.5 + flow_score * 0.5

    detail = f"量比{v_ratio:.2f}x MA20 | {'↑资金流入' if price_vs_ma60 > 0 else '↓资金流出'} {price_vs_ma60:+.1f}%"
    return round(final, 1), round(v_ratio, 2), detail


def calc_volatility_score(data: dict | None) -> tuple[float, float, str]:
    """
    ④ 波动率结构
    ATR(20) / ATR(60) 比值：
    - 比值 > 1 → 波动率扩张，趋势强化中
    - 比值 < 1 → 波动率收缩，趋势可能结束
    也看RSI：RSI > 70 超买，RSI < 30 超卖
    """
    if data is None:
        return 50.0, 1.0, "无数据"

    closes = data["closes"]
    highs  = data["highs"]
    lows   = data["lows"]

    if len(closes) < 61:
        return 50.0, 1.0, "数据不足"

    atr20 = atr(highs, lows, closes, 20)
    atr20_val = atr20[-1]
    atr60 = atr(highs, lows, closes, 60)
    atr60_val = sum(atr60[-60:]) / 60

    ratio = atr20_val / atr60_val if atr60_val > 0 else 1.0

    # ATR扩张 → 高动量环境，对趋势有利
    # 但如果ATR极度扩张（>2x）可能是趋势末端
    if ratio > 2.0:
        vol_score = 40.0  # 过度扩张，反而不利
    elif ratio > 1.5:
        vol_score = 70.0  # 适度扩张
    elif ratio > 1.0:
        vol_score = 55.0 + (ratio - 1.0) * 30  # 轻微扩张
    else:
        vol_score = max(20.0, 50.0 - (1.0 - ratio) * 50)  # 收缩

    rsi_val = rsi(closes, 14)
    if rsi_val > 80:
        vol_score = min(vol_score, 60.0)  # RSI过高，适当扣分

    detail = f"ATR20/ATR60={ratio:.2f} | RSI(14)={rsi_val:.0f}"
    return round(vol_score, 1), round(ratio, 2), detail


def calc_leadership_score(sector_name: str, sector_return: float,
                          klines_dir: Path) -> tuple[float, float, str]:
    """
    ⑤ 领导股健康度
    成分股平均涨幅 vs 板块ETF涨幅：
    - 龙头涨幅 > 板块涨幅 → 确认健康
    - 龙头涨幅 < 板块涨幅 → 警惕（可能是ETF被动上涨）
    返回 (score, raw_leader_return, detail)
    """
    leaders = SECTOR_LEADERS.get(sector_name, [])
    if not leaders:
        return 50.0, 0.0, "单一资产ETF"

    leader_returns = []
    for ticker in leaders:
        d = load_ohlcv(klines_dir, ticker)
        if d is None or len(d["closes"]) < 21:
            continue
        ret20 = momentum(d["closes"], 20)
        leader_returns.append(ret20)

    if not leader_returns:
        return 50.0, 0.0, "无成分股数据"

    avg_leader_return = sum(leader_returns) / len(leader_returns)
    diff = avg_leader_return - sector_return  # 龙头 vs 板块

    # 评分 = 成分股绝对涨幅基础分 + 相对强弱调整
    # 基础分按成分股绝对涨幅
    abs_ret = avg_leader_return
    if abs_ret >= 30:   base = 95.0
    elif abs_ret >= 20: base = 80.0
    elif abs_ret >= 10: base = 65.0
    elif abs_ret >= 5:  base = 50.0
    elif abs_ret >= 0:  base = 35.0
    else:               base = 15.0   # 成分股整体下跌，危险信号

    # 调整：龙头 vs 板块 diff
    if diff > 10:      adj = +10
    elif diff > 5:     adj = +5
    elif diff > 0:     adj = +0
    elif diff > -5:    adj = -5
    else:              adj = -10   # 成分股明显弱于板块，警惕

    score = max(5.0, min(100.0, base + adj))

    detail = f"龙头均{avg_leader_return:+.1f}% vs 板块{sector_return:+.1}% | Δ{diff:+.1f}%"
    return round(score, 1), round(avg_leader_return, 1), detail


def calc_rotation_score(all_rs: list[tuple[str, float]],
                          ticker: str) -> tuple[float, float, int]:
    """
    ⑥ 轮动方向
    基于 RS 排名计算轮动得分和排名。
    all_rs: [(ticker, rs_value), ...]
    ticker: 当前板块代码
    返回 (score, raw_rs, rank)
    """
    if len(all_rs) < 2:
        return 50.0, 0.0, 0

    sorted_by_rs = sorted(all_rs, key=lambda x: x[1], reverse=True)
    ranks = {t: i+1 for i, (t, _) in enumerate(sorted_by_rs)}

    n = len(all_rs)
    rank = ranks.get(ticker, n // 2 + 1)
    # RS排名分位数（最强=#1=100分，最弱=#n=0分）
    rank_score = ((n - rank) / (n - 1)) * 100 if n > 1 else 50.0

    rs_val = next((rv for t, rv in all_rs if t == ticker), 0.0)
    rs_score = max(0.0, min(100.0, (rs_val - 0.5) * 100 + 50))

    final = rank_score * 0.5 + rs_score * 0.5
    return round(final, 1), round(rs_val, 2), rank


# ══════════════════════════════════════════════════════════════════════════════
# 主分析函数
# ══════════════════════════════════════════════════════════════════════════════

def _composite_score(rs_score: float, br_score: float, mf_score: float,
                       vol_score: float, ldr_score: float, rot_score: float) -> float:
    """六维度合成综合分"""
    return (
        rs_score   * WEIGHTS["rs"]
      + br_score  * WEIGHTS["breadth"]
      + mf_score  * WEIGHTS["money_flow"]
      + vol_score * WEIGHTS["volatility"]
      + ldr_score * WEIGHTS["leadership"]
    ) * (1 - WEIGHTS["rotation"]) + rot_score * WEIGHTS["rotation"]


def _tier(score: float) -> str:
    if score >= 75: return "L1"
    if score >= 60: return "L2"
    if score >= 45: return "L3"
    return "L4"


def _tier_rank(tier: str) -> int:
    return {"L1": 4, "L2": 3, "L3": 2, "L4": 1}[tier]


def analyze_sectors_v2(klines_dir: Path) -> dict:
    """
    六维度板块分析主入口 — 支持 1日 / 5日 / 20日 三个时间窗口
    自动检测短期与长期冲突，输出预警。
    """
    # ── 基础数据加载 ──────────────────────────────────────────────
    spy_data = load_ohlcv(klines_dir, SPY_TICKER)
    spy_mom1  = momentum(spy_data["closes"], 1)  if spy_data else 0.0
    spy_mom5  = momentum(spy_data["closes"], 5)  if spy_data else 0.0
    spy_mom20 = momentum(spy_data["closes"], 20) if spy_data else 0.0

    vix_data = load_ohlcv(klines_dir, VIX_TICKER)
    vix_val = vix_data["closes"][-1] if vix_data and vix_data["closes"] else 20.0

    breadth_file = klines_dir / "sp500_breadth_finviz.json"
    breadth_data = {}
    if breadth_file.exists():
        try:
            breadth_data = json.load(open(breadth_file))
        except Exception:
            pass
    above_ema20 = breadth_data.get("above_sma20", 0.5)

    # ── 第一遍：各板块基础数据 ────────────────────────────────────
    sector_data_map: dict = {}
    all_rs20: list = []

    for ticker, name, category in SECTOR_ETFS:
        data = load_ohlcv(klines_dir, ticker)
        if data is None or len(data["closes"]) < 21:
            continue
        mom1  = momentum(data["closes"], 1)
        mom5  = momentum(data["closes"], 5)
        mom20 = momentum(data["closes"], 20)
        rs20  = mom20 / spy_mom20 if abs(spy_mom20) > 0.001 else 0.0

        sector_data_map[ticker] = {
            "data": data, "name": name, "category": category,
            "mom1": mom1, "mom5": mom5, "mom20": mom20,
            "rs20": rs20,
        }
        all_rs20.append((ticker, rs20))

    # ── 第二遍：计算各时间窗口得分 ─────────────────────────────────
    results = []
    for ticker, name, category in SECTOR_ETFS:
        if ticker not in sector_data_map:
            continue
        sd = sector_data_map[ticker]
        data  = sd["data"]
        mom1, mom5, mom20 = sd["mom1"], sd["mom5"], sd["mom20"]
        rs20  = sd["rs20"]

        # ① RS（三个窗口）
        rs1_score,  raw_rs1  = calc_rs_score(mom1,  spy_mom1)
        rs5_score,  raw_rs5  = calc_rs_score(mom5,  spy_mom5)
        rs20_score, raw_rs20 = calc_rs_score(mom20, spy_mom20)

        # ② Breadth（成分股不随时窗变化，用20d窗口数据）
        br_score, raw_br, br_detail = calc_breadth_score(name, klines_dir)

        # ③ 资金流（用20d计算均量）
        mf_score, raw_vr, mf_detail = calc_money_flow_score(data)

        # ④ 波动率（用20d ATR）
        vol_score, raw_atr, vol_detail = calc_volatility_score(data)

        # ⑤ 领导股（成分股相对板块，用20d）
        ldr_score, raw_ldr, ldr_detail = calc_leadership_score(name, mom20, klines_dir)

        # ⑥ 轮动（基于20d RS排名）
        rot_score, rot_raw, rot_rank = calc_rotation_score(all_rs20, ticker)

        # 三个窗口合成
        sc1  = _composite_score(rs1_score,  br_score, mf_score, vol_score, ldr_score, rot_score)
        sc5  = _composite_score(rs5_score,  br_score, mf_score, vol_score, ldr_score, rot_score)
        sc20 = _composite_score(rs20_score, br_score, mf_score, vol_score, ldr_score, rot_score)

        tier1  = _tier(sc1)
        tier5  = _tier(sc5)
        tier20 = _tier(sc20)

        # ── 冲突预警检测 ──────────────────────────────────────
        warnings = []
        # 20d L1 但 5d L3/L4 → 预警
        if _tier_rank(tier20) >= 3 and _tier_rank(tier5) <= 2:
            warnings.append(f"⚠️ 5日线转弱（20d={tier20} → 5d={tier5}）")
        if _tier_rank(tier20) >= 3 and _tier_rank(tier1) <= 2:
            warnings.append(f"🔴 1日线转弱（20d={tier20} → 1d={tier1}）")
        # 20d L4 但 1d L1 → 预警（可能是反弹陷阱）
        if _tier_rank(tier20) <= 1 and _tier_rank(tier1) >= 3:
            warnings.append(f"🟡 1日急弹未确认（20d={tier20} ← 1d={tier1}，谨慎追高）")
        # 1d 与 5d 方向相反且差距大
        if _tier_rank(tier1) - _tier_rank(tier5) >= 2:
            warnings.append(f"⚡ 日内反转（5d={tier5} → 1d={tier1}）")

        results.append({
            "ticker": ticker,
            "name":   name,
            "category": category,
            "final_score": round(sc20, 1),
            "tier": tier20,
            "signal": {"L1": "BUY", "L2": "HOLD", "L3": "REDUCE", "L4": "AVOID"}[tier20],
            "mom1":  round(mom1, 2),
            "mom5":  round(mom5, 2),
            "mom20": round(mom20, 2),
            "spy_mom20": round(spy_mom20, 2),
            "timeframes": {
                "1d": {"score": round(sc1, 1), "tier": tier1,
                       "rs": round(rs1_score, 1),  "mom": round(mom1, 2)},
                "5d": {"score": round(sc5, 1), "tier": tier5,
                       "rs": round(rs5_score, 1),  "mom": round(mom5, 2)},
                "20d":{"score": round(sc20,1), "tier": tier20,
                       "rs": round(rs20_score,1), "mom": round(mom20,2)},
            },
            "warnings": warnings,
            "factors": {
                "rs":         {"score": round(rs20_score, 1), "raw": f"RS={raw_rs20:.2f}",
                                "detail": f"{mom20:+.1f}% vs SPY{spy_mom20:+.1}%"},
                "breadth":    {"score": round(br_score, 1),   "raw": f"{raw_br:.0f}%",      "detail": br_detail},
                "money_flow": {"score": round(mf_score, 1),   "raw": f"量比{raw_vr:.2f}x",     "detail": mf_detail},
                "volatility": {"score": round(vol_score, 1),  "raw": f"ATR{raw_atr:.2f}",       "detail": vol_detail},
                "leadership": {"score": round(ldr_score, 1),  "raw": f"{raw_ldr:+.1f}%",       "detail": ldr_detail},
                "rotation":   {"score": round(rot_score, 1),  "raw": f"RS={rot_raw:.2f} 排名#{rot_rank}", "detail": f"Top{rot_rank}/{len(all_rs20)} 板块RS排名"},
            },
        })

    results.sort(key=lambda x: x["final_score"], reverse=True)
    for i, r in enumerate(results, 1):
        r["rank"] = i

    hot_sectors  = [r["ticker"] for r in results if r["tier"] in ("L1", "L2")]
    cold_sectors = [r["ticker"] for r in results if r["tier"] in ("L3", "L4")]
    all_warnings = [w for r in results for w in r["warnings"]]

    return {
        "sectors": results,
        "hot_sectors":  hot_sectors,
        "cold_sectors": cold_sectors,
        "warnings": all_warnings,
        "spy_mom1":  round(spy_mom1, 2),
        "spy_mom5":  round(spy_mom5, 2),
        "spy_mom20": round(spy_mom20, 2),
        "vix": round(vix_val, 2),
        "breadth_above20ema": round(above_ema20 * 100, 1),
        "last_date": spy_data["dates"][-1] if spy_data else "",
        "weights": {k: f"{v:.0%}" for k, v in WEIGHTS.items()},
    }


# ══════════════════════════════════════════════════════════════════════════════
# 控制台输出
# ══════════════════════════════════════════════════════════════════════════════

def _bar(val: float, width: int = 10) -> str:
    filled = int(val / 100 * width)
    return "█" * filled + "░" * (width - filled)

def print_sector_analysis_v2(result: dict):
    sectors = result["sectors"]
    print(f"\n{'='*80}")
    print(f"  P3 板块分析 v2  |  SPY动量 {result['spy_mom20']:+.1f}%  |  VIX {result['vix']}  |  广度 {result['breadth_above20ema']:.0f}%")
    print(f"{'='*80}")
    print(f"\n  {'排名':>2}  {'板块':6}  {'名称':10}  {'综合':>5}  {'信号':5}  ①RS   ②BR   ③MF   ④VOL  ⑤LDR  ⑥ROT")
    print(f"  {'-'*75}")

    tier_colors = {"L1": "\033[92m", "L2": "\033[96m", "L3": "\033[93m", "L4": "\033[91m", "RESET": "\033[0m"}
    signal_icon = {"BUY": "🟢", "HOLD": "🟡", "REDUCE": "🟠", "AVOID": "🔴"}

    for s in sectors:
        f = s["factors"]
        c = tier_colors.get(s["tier"], "")
        sig_icon = signal_icon.get(s["signal"], "")
        print(f"  {c}{s['rank']:2d}  {s['ticker']:6}  {s['name']:10}  {s['final_score']:5.1f}  {s['tier']} {sig_icon}"
              f"  {f['rs']['score']:5.1f}  {f['breadth']['score']:5.1f}  {f['money_flow']['score']:5.1f}"
              f"  {f['volatility']['score']:5.1f}  {f['leadership']['score']:5.1f}  {f['rotation']['score']:5.1f}{tier_colors['RESET']}")

    print(f"\n  权重: " + "  ".join(f"{k}={v}" for k, v in result["weights"].items()))
    print(f"\n  🥵 强势: {', '.join(result['hot_sectors']) or '无'}")
    print(f"  🥶 弱势: {', '.join(result['cold_sectors']) or '无'}")


# ══════════════════════════════════════════════════════════════════════════════
# HTML 报告
# ══════════════════════════════════════════════════════════════════════════════

def _css() -> str:
    return """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0d1117; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 14px; line-height: 1.6; }
.report-header { background: linear-gradient(135deg,#1a1a2e,#16213e); border-bottom: 2px solid #e94560; padding: 24px 32px; }
.phase-tag { display:inline-block; background:#e94560; color:#fff; font-size:12px; font-weight:700; padding:2px 10px; border-radius:12px; margin-bottom:8px; letter-spacing:1px; }
.report-title { font-size:22px; font-weight:700; color:#fff; margin-bottom:4px; }
.report-meta { display:flex; gap:12px; flex-wrap:wrap; margin-top:8px; }
.meta-badge { display:inline-flex; align-items:center; background:rgba(255,255,255,0.08); padding:4px 12px; border-radius:6px; font-size:12px; }
.meta-badge.neutral { background:rgba(88,166,255,0.15); color:#58a6ff; }
.report-body { padding: 24px 32px; }
.section { background:#161b22; border:1px solid #30363d; border-radius:10px; margin-bottom:20px; overflow:hidden; }
.section-header { background:#1c2128; padding:10px 20px; border-bottom:1px solid #30363d; font-weight:600; font-size:13px; color:#e0e0e0; }
.section-body { padding:16px 20px; }
.weight-row { display:flex; gap:12px; flex-wrap:wrap; }
.wt { background:#1c2128; padding:6px 12px; border-radius:6px; font-size:12px; color:#9e9e9e; }
.wt strong { color:#fff; }
.tier-container { display:flex; flex-direction:column; gap:8px; }
.tier-row { display:flex; align-items:center; gap:12px; padding:10px 14px; border-radius:8px; }
.tier-badge { font-weight:800; font-size:13px; min-width:28px; }
.tier-dot { display:inline-block; padding:2px 8px; border-radius:10px; font-size:11px; font-weight:700; color:#fff; margin-right:4px; }
table.data-table { width:100%; border-collapse:collapse; font-size:13px; }
table.data-table th { background:#1c2128; color:#9e9e9e; text-align:left; padding:8px 10px; border-bottom:1px solid #30363d; font-weight:600; font-size:11px; text-transform:uppercase; }
table.data-table td { padding:9px 10px; border-bottom:1px solid #21262d; }
table.data-table tr:last-child td { border-bottom:none; }
table.data-table tr:hover td { background:#1c2128; }
.factor-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; }
.factor-card { background:#1c2128; border-radius:8px; padding:14px; }
.factor-name { font-weight:700; margin-bottom:6px; color:#58a6ff; font-size:13px; }
.factor-desc { font-size:12px; color:#9e9e9e; line-height:1.5; }
.report-footer { padding:14px 32px; border-top:1px solid #30363d; color:#9e9e9e; font-size:11px; display:flex; justify-content:space-between; }
.exec-summary { background:#161b22; border:1px solid #30363d; border-radius:10px; margin-bottom:20px; overflow:hidden; }
.exec-title { background:#1c2128; padding:12px 24px; border-bottom:1px solid #30363d; font-weight:700; font-size:15px; color:#fff; }
.exec-cards { display:grid; grid-template-columns:repeat(3, 1fr); gap:0; }
.exec-card { padding:16px 20px; border-right:1px solid #30363d; }
.exec-card:last-child { border-right:none; }
.exec-card-title { font-weight:700; font-size:13px; color:#e0e0e0; margin-bottom:10px; }
.exec-card-body { font-size:13px; color:#9e9e9e; line-height:1.7; }
.exec-card-body strong { color:#fff; }
.delta { font-size:11px; margin-left:3px; }
.delta.up   { color:#00c853; }
.delta.down { color:#ff1744; }
.delta.flat { color:#9e9e9e; }
"""

def save_html_report_v2(result: dict, date: str | None = None,
                         output_dir: Path | None = None,
                         prev: dict | None = None) -> Path:
    sectors = result["sectors"]

    if output_dir is None:
        output_dir = Path(__file__).parent / "layout"
    output_dir.mkdir(parents=True, exist_ok=True)

    today_str = date or result.get("last_date", "").replace("-", "")
    out_path = output_dir / f"p3_{today_str}.html"
    latest   = output_dir / "sector_v2_latest.html"

    tier_bg = {
        "L1": "rgba(0,200,83,0.15)",
        "L2": "rgba(88,166,255,0.12)",
        "L3": "rgba(255,193,7,0.12)",
        "L4": "rgba(255,23,68,0.12)",
    }
    tier_color = {
        "L1": "#00c853", "L2": "#58a6ff",
        "L3": "#ffc107", "L4": "#ff1744",
    }

    prev_map = {s["ticker"]: s for s in (prev.get("sectors", []) if prev else [])}

    def dcell(curr: float, prev_v, fmt="+.1f") -> str:
        if prev_v is None:
            return ""
        delta = round(curr - prev_v, 1)
        if delta > 0:
            return f'<span class="delta up">▲{abs(delta):{fmt}}</span>'
        elif delta < 0:
            return f'<span class="delta down">▼{abs(delta):{fmt}}</span>'
        return ""

    tier_rows = ""
    for tier in ["L1", "L2", "L3", "L4"]:
        items = [s for s in sectors if s["tier"] == tier]
        if not items:
            continue
        parts = []
        for r in items:
            p = prev_map.get(r["ticker"])
            d_fs = round(r["final_score"] - p["final_score"], 1) if p else 0.0
            d_tier = bool(p and r["tier"] != p["tier"])
            if d_fs != 0 or d_tier:
                d_html = f'<span class="delta {"up" if d_fs>0 else "down" if d_fs<0 else "flat"}">{"+" if d_fs>0 else ""}{d_fs:.1f}</span>'
            else:
                d_html = ""
            parts.append(f'<span class="tier-dot" style="background:{tier_color[tier]}">{r["ticker"]}</span>{d_html}')
        tier_rows += f'<div class="tier-row" style="background:{tier_bg[tier]}">'
        tier_rows += f'<span class="tier-badge" style="color:{tier_color[tier]}">{tier}</span>'
        tier_rows += f'<span>{"  ".join(parts)}</span></div>'


    # ── 主表格：三时间窗口 ─────────────────────────────────────
    detail_rows = ""
    for s in sectors:
        f = s["factors"]
        p = prev_map.get(s["ticker"])
        tier_c = tier_color.get(s["tier"], "#9e9e9e")
        tf = s.get("timeframes", {})
        # 三个窗口 tier/score
        t1  = tf.get("1d", {})
        t5  = tf.get("5d", {})
        t20 = tf.get("20d", {})
        tier1  = t1.get("tier","—")
        tier5  = t5.get("tier","—")
        tier20 = t20.get("tier","—")
        tier1_c = tier_color.get(tier1,"#9e9e9e")
        tier5_c = tier_color.get(tier5,"#9e9e9e")
        # 预警标记
        warn_html = ""
        if s.get("warnings"):
            icons = " ".join(set(w[0] for w in s["warnings"]))
            warn_html = f'<div style="font-size:11px;color:#ffc107;white-space:nowrap">{icons}</div>'
        detail_rows += f"""<tr>
  <td style="font-weight:700;color:{tier_c}">{s["ticker"]}</td>
  <td>{s["name"]}</td>
  <td style="text-align:center"><span class="tier-dot" style="background:{tier_c}">{s["tier"]}</span></td>
  <td style="text-align:center"><span class="tier-dot" style="background:{tier1_c}" title="1日">{tier1}</span></td>
  <td style="text-align:center"><span class="tier-dot" style="background:{tier5_c}" title="5日">{tier5}</span></td>
  <td style="text-align:center"><span class="tier-dot" style="background:{tier_c}" title="20日">{tier20}</span></td>
  <td style="text-align:right;font-weight:800;color:{tier_c}">{s["final_score"]:.1f}</td>
  <td style="text-align:right">{t1.get("score","—"):.1f}</td>
  <td style="text-align:right">{t5.get("score","—"):.1f}</td>
  <td style="text-align:right">{t20.get("score","—"):.1f}</td>
  <td style="text-align:right">{s["mom1"] if "mom1" in s else "—":+.2f}%</td>
  <td style="text-align:right">{s.get("mom5","—"):+.2f}%</td>
  <td style="text-align:right">{s["mom20"]:+.2f}%</td>
  <td>{warn_html}</td>
</tr>"""

    # ── 预警汇总行 ─────────────────────────────────────────────
    warning_rows = ""
    for s in sectors:
        if not s.get("warnings"):
            continue
        tier_c = tier_color.get(s["tier"], "#9e9e9e")
        warn_text = " | ".join(s["warnings"])
        warning_rows += f"""<tr>
  <td style="font-weight:700;color:{tier_c}">{s["ticker"]}</td>
  <td>{s["name"]}</td>
  <td style="text-align:center"><span class="tier-dot" style="background:{tier_c}">{s["tier"]}</span></td>
  <td style="text-align:right">{s["mom20"]:+.2f}%</td>
  <td style="color:#ffc107;font-size:12px">{warn_text}</td>
</tr>"""

    factor_rows = ""
    for s in sectors:
        f = s["factors"]
        tier_c = tier_color.get(s["tier"], "#9e9e9e")
        factor_rows += f"""<tr>
  <td style="font-weight:700;color:{tier_c}">{s["ticker"]}</td>
  <td style="color:#9e9e9e;font-size:12px">{f["rs"]["detail"]}</td>
  <td style="color:#9e9e9e;font-size:12px">{f["breadth"]["detail"]}</td>
  <td style="color:#9e9e9e;font-size:12px">{f["money_flow"]["detail"]}</td>
  <td style="color:#9e9e9e;font-size:12px">{f["volatility"]["detail"]}</td>
  <td style="color:#9e9e9e;font-size:12px">{f["leadership"]["detail"]}</td>
  <td style="color:#9e9e9e;font-size:12px">{f["rotation"]["detail"]}</td>
</tr>"""



    change_rows = ""
    if prev:
        for s in sectors:
            p = prev_map.get(s["ticker"])
            if not p:
                continue
            d_score = round(s["final_score"] - p["final_score"], 1)
            d_tier  = s["tier"] != p["tier"]
            if abs(d_score) < 0.05 and not d_tier:
                continue
            tier_c = tier_color.get(s["tier"], "#9e9e9e")
            icon = "🟢" if d_score > 0 else "🔴" if d_score < 0 else "🟡"
            tier_b    = f'<span class="tier-dot" style="background:{tier_c}">{s["tier"]}</span>'
            prev_tier = f'<span class="tier-dot" style="background:#555">{p["tier"]}</span>'
            change_rows += f"""<tr>
  <td style="font-weight:700">{s["ticker"]}</td>
  <td style="text-align:center">{tier_b}</td>
  <td style="text-align:center">{prev_tier}</td>
  <td style="text-align:right;font-weight:800">{s["final_score"]:.1f}</td>
  <td style="text-align:right">{icon} {d_score:+.1f}</td>
  <td style="text-align:right">{s["mom20"]:+.2f}%</td>
  <td style="color:#9e9e9e">{s["name"]}</td>
</tr>"""

    prev_date = prev.get("last_date", "—") if prev else "—"
    data_date = result.get("last_date", "—")
    has_prev  = bool(prev)

    # ── 三大核心摘要计算 ───────────────────────────────────────
    # ① 板块轮动信号（基于 mom20 真实变化）
    rot_signal_lines = []
    if has_prev and prev:
        prev_s_map = {s["ticker"]: s for s in prev.get("sectors", [])}
        tier_rank = {"L1": 4, "L2": 3, "L3": 2, "L4": 1}

        # 仅在两日都有数据的板块之间比较排名（剔除新增板块干扰）
        common_tickers = set(prev_s_map.keys()) & {s["ticker"] for s in result["sectors"]}
        prev_common = [(t, prev_s_map[t]["mom20"]) for t in common_tickers]
        curr_common = [(s["ticker"], s["mom20"]) for s in result["sectors"] if s["ticker"] in common_tickers]
        prev_common.sort(key=lambda x: x[1], reverse=True)
        curr_common.sort(key=lambda x: x[1], reverse=True)
        prev_top5 = {t for t, _ in prev_common[:5]}
        curr_top5 = {t for t, _ in curr_common[:5]}
        newly_entered = curr_top5 - prev_top5   # 在共同板块中新入Top5
        genuinely_exited = prev_top5 - curr_top5  # 在共同板块中退出Top5
        newly_added_sectors = {s["ticker"] for s in result["sectors"]} - set(prev_s_map.keys())

        if newly_added_sectors:
            rot_signal_lines.append(f"🆕 新增观察: {', '.join(sorted(newly_added_sectors))}\n")
        if newly_entered:
            rot_signal_lines.append(f"📈 资金流入Top5: {', '.join(sorted(newly_entered))}\n")
        if genuinely_exited:
            rot_signal_lines.append(f"📉 资金流出Top5: {', '.join(sorted(genuinely_exited))}\n")

        # Tier 升降（仅共同板块）
        for s in result["sectors"]:
            p = prev_s_map.get(s["ticker"])
            if not p:
                continue
            prev_t = p.get("tier", "L4")
            curr_t = s.get("tier", "L4")
            if tier_rank.get(curr_t, 0) > tier_rank.get(prev_t, 0):
                rot_signal_lines.append(f"↑ <strong>{s['ticker']}</strong> {prev_t}→{curr_t}，{s['mom20']:+.1f}%\n")
            elif tier_rank.get(curr_t, 0) < tier_rank.get(prev_t, 0):
                rot_signal_lines.append(f"↓ <strong>{s['ticker']}</strong> {prev_t}→{curr_t}，{s['mom20']:+.1f}%\n")

    rot_signal = "<br>".join(rot_signal_lines) if rot_signal_lines else "今日无明显轮动信号"

    # ② 昨日最强板块现状
    if has_prev and prev:
        prev_s_map2 = {s["ticker"]: s for s in prev.get("sectors", [])}
        prev_sorted = sorted(prev_s_map2.items(), key=lambda x: x[1].get("mom20", 0), reverse=True)
        if prev_sorted:
            top_ticker, top_prev = prev_sorted[0]
            today_s = next((s for s in result["sectors"] if s["ticker"] == top_ticker), None)
            if today_s:
                # 基于 mom20 排名（不受板块数量变化影响）
                curr_mom_sorted = sorted(result["sectors"], key=lambda x: x.get("mom20", 0), reverse=True)
                rank_today = next((i+1 for i, s in enumerate(curr_mom_sorted) if s["ticker"] == top_ticker), 0)
                top_sector_info = (f"<strong>{top_ticker}</strong>（{top_prev.get('name','')}）\n"
                                   f"20日涨跌 <strong>{top_prev.get('mom20',0):+.2f}%</strong>\n"
                                   f"当前排名 <strong>第{rank_today}名</strong>（共{len(result['sectors'])}板块）\n"
                                   f"Tier=<strong>{today_s['tier']}</strong>")
            else:
                top_sector_info = "无数据"
        else:
            top_sector_info = "昨日无板块数据"
    else:
        top_sector_info = "无昨日对比数据"

    # ③ 今日关键变化（仅比较共同板块的 Tier 变化）
    if has_prev and prev:
        prev_s_map3 = {s["ticker"]: s for s in prev.get("sectors", [])}
        common = set(prev_s_map3.keys()) & {s["ticker"] for s in result["sectors"]}
        tier_changes = []
        for s in result["sectors"]:
            p = prev_s_map3.get(s["ticker"])
            if not p or s["ticker"] not in common:
                continue
            if s.get("tier") != p.get("tier"):
                tier_changes.append((s["ticker"], s["name"], p.get("tier","?"), s["tier"]))
        if tier_changes:
            key_change = "、".join([f"<strong>{t}</strong> {pt}→{ct}" for t,_,pt,ct in tier_changes[:5]])
        else:
            key_change = "共同板块Tier无变化"
    else:
        key_change = "无昨日对比数据"

    no_warning = "<div style=\'color:#9e9e9e;font-size:13px;padding:8px\'>✅ 无时间窗口冲突预警</div>" if not warning_rows else ""

    change_section = ""
    if has_prev and change_rows:
        change_section = f"""
  <div class="section">
    <div class="section-header">📈 日环比变化（{prev_date} → {data_date}）</div>
    <div class="section-body" style="overflow-x:auto">
      <table class="data-table">
        <thead>
          <tr><th>代码</th><th>今日Tier</th><th>昨日Tier</th><th style="text-align:right">今日综合分</th><th style="text-align:right">变化</th><th style="text-align:right">20日涨跌</th><th>板块</th></tr>
        </thead>
        <tbody>{change_rows}</tbody>
      </table>
      <div style="margin-top:8px;font-size:11px;color:#555">注：只显示综合分或Tier有变化的板块</div>
    </div>
  </div>"""
    elif not has_prev:
        change_section = """
  <div class="section">
    <div class="section-header">📈 日环比变化</div>
    <div class="section-body">
      <div style="color:#9e9e9e;font-size:13px">昨日无板块分析数据，暂无日环比对比</div>
    </div>
  </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>P3 板块分析 v2 {date or ""}</title>
<style>
{_css()}
</style>
</head>
<body>
<div class="report-header">
  <div class="phase-tag">P3 · 板块分析 v2</div>
  <div class="report-title">P3 六大维度板块量化分析</div>
  <div class="report-meta">
    <span class="meta-badge neutral">数据日期 {data_date}</span>
    <span class="meta-badge neutral">SPY 1d {result["spy_mom1"]:+.1f}%</span>
    <span class="meta-badge neutral">SPY 5d {result["spy_mom5"]:+.1f}%</span>
    <span class="meta-badge neutral">SPY 20d {result["spy_mom20"]:+.1f}%</span>
  </div>
</div>

<div class="report-body">
  <!-- ═══ 三大核心摘要 ═══ -->
  <div class="exec-summary">
    <div class="exec-title">📌 三大核心判断</div>
    <div class="exec-cards">
      <div class="exec-card" style="border-left:4px solid #e94560">
        <div class="exec-card-title">🚨 板块轮动信号</div>
        <div class="exec-card-body">
          {rot_signal}
        </div>
      </div>
      <div class="exec-card" style="border-left:4px solid #00c853">
        <div class="exec-card-title">👑 昨日最强板块现状</div>
        <div class="exec-card-body">
          {top_sector_info}
        </div>
      </div>
      <div class="exec-card" style="border-left:4px solid #ffc107">
        <div class="exec-card-title">⚡ 今日关键变化</div>
        <div class="exec-card-body">
          {key_change}
        </div>
      </div>
    </div>
  </div>

    <span class="meta-badge neutral">SPY 1d {result["spy_mom1"]:+.1f}%</span>\n    <span class="meta-badge neutral">SPY 5d {result["spy_mom5"]:+.1f}%</span>\n    <span class="meta-badge neutral">SPY 20d {result["spy_mom20"]:+.1f}%</span>
    <span class="meta-badge neutral">VIX {result["vix"]}</span>
    <span class="meta-badge neutral">广度 {result["breadth_above20ema"]:.0f}%</span>
  </div>
</div>

<div class="report-body">
  <div class="section">
    <div class="section-header">📐 评分体系 · 权重</div>
    <div class="section-body">
      <div class="weight-row">
        <span class="wt">① Relative Strength <strong>30%</strong></span>
        <span class="wt">② Breadth <strong>20%</strong></span>
        <span class="wt">③ 资金流 <strong>20%</strong></span>
        <span class="wt">④ 波动率 <strong>10%</strong></span>
        <span class="wt">⑤ 领导股 <strong>15%</strong></span>
        <span class="wt">⑥ 轮动 <strong>5%</strong></span>
      </div>
      <div style="margin-top:10px;font-size:12px;color:#9e9e9e">
        <span class="delta up">▲</span>=上升 &nbsp;
        <span class="delta down">▼</span>=下降 &nbsp;
        对比基准：{prev_date}
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-header">📊 板块分层</div>
    <div class="section-body">
      <div class="tier-container">{tier_rows or "<div style='color:#9e9e9e'>无数据</div>"}</div>
    </div>
  </div>
{change_section}

  <div class="section">
    <div class="section-header">⚠️ 冲突预警（短期 vs 长期）</div>
    <div class="section-body" style="overflow-x:auto">
      <table class="data-table">
        <thead>
          <tr><th>代码</th><th>名称</th><th>Tier</th><th style="text-align:right">20日涨跌</th><th>预警</th></tr>
        </thead>
        <tbody>{warning_rows}</tbody>
      </table>
      {no_warning}
    </div>
  </div>

  <div class="section">
    <div class="section-header">🔍 三时间窗口综合明细（1日 / 5日 / 20日）</div>
    <div class="section-body" style="overflow-x:auto">
      <table class="data-table">
        <thead>
          <tr>
            <th>代码</th><th>名称</th><th>Tier(20d)</th>
            <th style="text-align:center" title="1日窗口">1d Tier</th>
            <th style="text-align:center" title="5日窗口">5d Tier</th>
            <th style="text-align:center" title="20日窗口">20d Tier</th>
            <th style="text-align:right">综合分(20d)</th>
            <th style="text-align:right">1d综合</th>
            <th style="text-align:right">5d综合</th>
            <th style="text-align:right">20d综合</th>
            <th style="text-align:right">1d涨跌</th>
            <th style="text-align:right">5d涨跌</th>
            <th style="text-align:right">20d涨跌</th>
            <th></th>
          </tr>
        </thead>
        <tbody>{detail_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <div class="section-header">📖 因子原始数据详情</div>
    <div class="section-body" style="overflow-x:auto">
      <table class="data-table">
        <thead>
          <tr><th>代码</th><th>①RS详情</th><th>②Breadth详情</th><th>③资金流详情</th><th>④波动率详情</th><th>⑤领导股详情</th><th>⑥轮动详情</th></tr>
        </thead>
        <tbody>{factor_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <div class="section-header">📖 因子说明</div>
    <div class="section-body">
      <div class="factor-grid">
        <div class="factor-card"><div class="factor-name">① Relative Strength</div><div class="factor-desc">板块涨幅 / SPY涨幅。比值&gt;1表示跑赢大市。tanh压缩：RS=4.5→97分，RS=2→83分，RS=1→50分。</div></div>
        <div class="factor-card"><div class="factor-name">② Breadth</div><div class="factor-desc">成分股站上20EMA比例。&gt;70%为健康参与，&lt;50%为抱团风险。</div></div>
        <div class="factor-card"><div class="factor-name">③ 资金流</div><div class="factor-desc">量比（今日量/20日均量）+ 价格vs60日均线方向。放量+价格强势=资金流入。</div></div>
        <div class="factor-card"><div class="factor-name">④ 波动率</div><div class="factor-desc">ATR(20)/ATR(60)。&gt;1.5趋势强化，&gt;2.0过度扩张警惕。</div></div>
        <div class="factor-card"><div class="factor-name">⑤ 领导股</div><div class="factor-desc">成分股龙头平均涨幅 vs 板块涨幅。龙头强=确认，龙头弱=警惕。</div></div>
        <div class="factor-card"><div class="factor-name">⑥ 轮动</div><div class="factor-desc">RS排名分位数。边际改善最多=资金正在流入。</div></div>
      </div>
    </div>
  </div>
</div>

<div class="report-footer">
  <span>P3 板块分析 v2 · 数据 {data_date} · 美股投资洞察分析</span>
  <span>对比基准 {prev_date}</span>
</div>
</body>
</html>"""

    for fp in (out_path, latest):
        with open(fp, "w", encoding="utf-8") as fh:
            fh.write(html)
    return out_path



# ══════════════════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    proj = Path(__file__).parent.parent.parent
    klines = proj / "中间过程/klines"

    print("[P3 v2] 六大维度板块分析")
    result = analyze_sectors_v2(klines)
    print_sector_analysis_v2(result)

    # HTML report only generated via main.py pipeline
