#!/usr/bin/env python3
"""
Market Indicators via FRED
=========================
从 FRED (Federal Reserve Economic Data) 获取非价格类市场指标：

1. US10Y   - 10年期国债收益率（FRED: DGS10）
2. HY_SPREAD - 高收益债信用利差（FRED: BAMLH0A0HYM2EY）
3. VIX_FRED  - VIX指数（FRED: VIXCLS，仅作为本地VIX_1d.json的备份）

用法：
    python3 fetch_market_indicators_fred.py              # 增量更新（最新日期起）
    python3 fetch_market_indicators_fred.py --full      # 全量回溯1年
    python3 fetch_market_indicators_fred.py --days 30   # 指定天数回溯
"""

import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# ──────────────────────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────────────────────

PROJ   = Path(__file__).parent.parent.parent
KLINE  = PROJ / "中间过程" / "klines"
KLINE.mkdir(parents=True, exist_ok=True)

FRED_SERIES = {
    "TNX": {
        "fred_code": "DGS10",
        "name": "10-Year Treasury Constant Maturity Rate",
        "unit": "percent",
        "file": "TNX_1d.json",
        "note": "国债收益率（非标准OHLCV，只取收盘value）",
    },
    "HY_SPREAD": {
        "fred_code": "BAMLH0A0HYM2EY",
        "name": "ICE BofA US High Yield Index Option-Adjusted Spread",
        "unit": "percent",
        "file": "HY_SPREAD_1d.json",
        "note": "高收益债信用利差",
    },
    "VIX_FRED": {
        "fred_code": "VIXCLS",
        "name": "CBOE Volatility Index (VIX)",
        "unit": "percent",
        "file": "VIX_FRED_1d.json",
        "note": "VIX指数（FRED备份，与本地VIX_1d.json同步）",
    },
}

# CBOE 专属指数（非 FRED）
CBOE_SERIES = {
    "VVIX": {
        "cboe_api": "https://cdn.cboe.com/api/global/delayed_quotes/quotes/_VVIX.json",
        "name": "Cboe VVIX Index (Vol of Vol)",
        "unit": "index",
        "file": "VVIX_1d.json",
        "note": "VIX的波动率指数，通过CBOE API获取",
    },
}

# ──────────────────────────────────────────────────────────────
# Fed 流动性指标（用于计算 LIQUIDITY_SCORE）
# ──────────────────────────────────────────────────────────────
# LIQUIDITY_SCORE = walcl_z * 0.4 + rrp_z * 0.3 + tga_z * 0.3
# Z-score 基于 252 日滚动窗口计算
#
# 参数含义：
#   WALCL (Total Assets of the Federal Reserve): Fed 总资产规模（万美元）
#     - 包含美国国债、MBS、回购协议等所有资产
#     - 上升 = 宽松（量化宽松）
#     - 下降 = 收紧（量化紧缩）
#     - FRED: https://fred.stlouisfed.org/series/WALCL
#
#   RRPONTSYD (Overnight Reverse Repurchase Agreements): 隔夜逆回购
#     - 货币市场基金等对手方存入 Fed 的隔夜存款
#     - 上升 = 流动性过剩（银行间市场资金充裕）
#     - 下降 = 流动性收紧
#     - FRED: https://fred.stlouisfed.org/series/RRPONTSYD
#     - 注意：若当日数据为 . （点）= 无数据，代表与前一日相同
#
#   WTREGEN (Treasury General Account Balance): 财政部一般账户余额
#     - 财政部在 Fed 的活期存款（US Treasury checking account）
#     - 上升 = 财政存款增加 = 银行体系流动性减少
#     - 下降 = 财政存款减少 = 银行体系流动性增加
#     - FRED: https://fred.stlouisfed.org/series/WTREGEN
#
LIQUIDITY_SERIES = {
    "WALCL": {
        "fred_code": "WALCL",
        "name": "Fed Total Assets (Total Assets of the Federal Reserve)",
        "unit": "million USD",
        "file": "WALCL_1d.json",
        "note": "Fed总资产规模（万美元）",
    },
    "RRPONTSYD": {
        "fred_code": "RRPONTSYD",
        "name": "Overnight Reverse Repurchase Agreements",
        "unit": "million USD",
        "file": "RRPONTSYD_1d.json",
        "note": "隔夜逆回购（若无数据点=与前一日相同）",
    },
    "WTREGEN": {
        "fred_code": "WTREGEN",
        "name": "Treasury General Account Balance",
        "unit": "million USD",
        "file": "WTREGEN_1d.json",
        "note": "财政部一般账户余额（万美元）",
    },
}

DEFAULT_LOOKBACK_DAYS = 30


# ──────────────────────────────────────────────────────────────
# 核心 FRED 获取函数
# ──────────────────────────────────────────────────────────────

def fetch_fred_csv(series_id: str, start_date: str, end_date: str = None,
                   timeout: int = 30, forward_fill: bool = False) -> list:
    """
    从 FRED 获取 CSV 格式数据

    参数:
        series_id: FRED 系列代码
        start_date: 起始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD
        forward_fill: 若为 True，则对 "."（缺失值）使用前值填充
                      用于 RRPONTSYD 等可能无数据的指标

    返回: [{"date": "2026-05-13", "value": 4.46}, ...]
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    url = (
        f"https://fred.stlouisfed.org/graph/fredgraph.csv"
        f"?id={series_id}"
        f"&cosd={start_date}"
        f"&coed={end_date}"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; OpenClaw/1.0; +https://openclaw.ai)",
        "Accept": "text/csv",
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        print(f"  [HTTP ERROR] {e.code} - {e.reason}")
        return []
    except Exception as e:
        print(f"  [NET ERROR] {e}")
        return []

    lines = content.strip().split("\n")
    if len(lines) < 2:
        return []

    records = []
    last_value = None
    for line in lines[1:]:
        parts = line.strip().split(",")
        if len(parts) >= 2:
            date_str = parts[0].strip()
            value_str = parts[1].strip()
            if value_str and value_str != ".":
                try:
                    last_value = float(value_str)
                    records.append({"date": date_str, "value": last_value})
                except ValueError:
                    pass
            elif forward_fill and last_value is not None:
                # 前值填充
                records.append({"date": date_str, "value": last_value, "forward_filled": True})
    return records


def fetch_cboe_json(api_url: str, timeout: int = 30) -> dict:
    """
    从 CBOE API 获取 JSON 数据

    返回: {"date": "2026-05-15", "value": 94.26, ...}
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; OpenClaw/1.0; +https://openclaw.ai)",
        "Accept": "application/json",
    }
    req = urllib.request.Request(api_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content)
    except Exception as e:
        print(f"  [CBOE API ERROR] {e}")
        return {}


def fetch_cboe_quote(series_id: str, info: dict) -> list:
    """
    从 CBOE API 获取单个指数的当日收盘数据
    """
    api_url = info.get("cboe_api", "")
    if not api_url:
        return []

    data = fetch_cboe_json(api_url)
    if not data:
        return []

    # 解析 CBOE 实时行情 API 格式
    quote = data.get("data", {})
    price = quote.get("current_price") or quote.get("close")
    date_str = data.get("timestamp", "")[:10]  # 取前10位 YYYY-MM-DD

    if price and date_str:
        return [{"date": date_str, "value": float(price)}]
    return []


# ──────────────────────────────────────────────────────────────
# 文件读写
# ──────────────────────────────────────────────────────────────

def load_existing(file_path: Path) -> list:
    """加载现有数据"""
    if file_path.exists():
        with open(file_path) as f:
            obj = json.load(f)
        return obj.get("data", [])
    return []


def save_data(file_path: Path, records: list, meta: dict):
    """保存数据"""
    obj = {
        "name": meta.get("name", ""),
        "source": "FRED",
        "fred_code": meta.get("fred_code", ""),
        "unit": meta.get("unit", ""),
        "last_updated": datetime.now().isoformat(),
        "note": meta.get("note", ""),
        "data": records,
    }
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def merge_and_save(file_path: Path, new_records: list, meta: dict):
    """合并新旧数据后保存"""
    existing = load_existing(file_path)
    all_records = {r["date"]: r for r in existing}
    all_records.update({r["date"]: r for r in new_records})
    merged = sorted(all_records.values(), key=lambda x: x["date"])
    save_data(file_path, merged, meta)
    return merged


# ──────────────────────────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────────────────────────

def fetch_all(lookback_days: int = DEFAULT_LOOKBACK_DAYS,
              symbols: list = None):
    """
    批量获取所有/指定 FRED + CBOE 指标

    参数:
        lookback_days: 回溯天数
        symbols: 指定只获取某些指标（如 ["TNX", "HY_SPREAD", "VVIX"]）
    """
    end_date   = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    results = {}

    # ── FRED 指标 ──────────────────────────────────────────
    for sym, info in FRED_SERIES.items():
        if symbols and sym not in symbols:
            continue

        print(f"\n{'='*50}")
        print(f"📊 {sym}: {info['name']}")
        print(f"{'='*50}")

        file_path = KLINE / info["file"]

        existing = load_existing(file_path)
        latest_date = None
        if existing:
            latest_date = max(r["date"] for r in existing)
            print(f"  [INFO] 现有数据: {len(existing)} 条，最新 {latest_date}")

        fetch_start = latest_date if latest_date else start_date
        print(f"  [INFO] 获取范围: {fetch_start} → {end_date}")

        if latest_date and latest_date >= end_date:
            print(f"  [SKIP] 数据已是最新")
            results[sym] = existing
            continue

        records = fetch_fred_csv(info["fred_code"], fetch_start, end_date)

        if not records:
            print(f"  [WARN] FRED 返回空数据")
            results[sym] = existing
            continue

        merged = merge_and_save(file_path, records, info)
        print(f"  [OK] 保存 {len(records)} 条新数据，总计 {len(merged)} 条")
        results[sym] = merged
        time.sleep(1.2)

    # ── CBOE 指标 ──────────────────────────────────────────
    for sym, info in CBOE_SERIES.items():
        if symbols and sym not in symbols:
            continue

        print(f"\n{'='*50}")
        print(f"📈 {sym}: {info['name']}")
        print(f"{'='*50}")

        file_path = KLINE / info["file"]

        existing = load_existing(file_path)
        latest_date = None
        if existing:
            latest_date = max(r["date"] for r in existing)
            print(f"  [INFO] 现有数据: {len(existing)} 条，最新 {latest_date}")

        if latest_date and latest_date >= end_date:
            print(f"  [SKIP] 数据已是最新")
            results[sym] = existing
            continue

        records = fetch_cboe_quote(sym, info)

        if not records:
            print(f"  [WARN] CBOE API 返回空数据")
            results[sym] = existing
            continue

        merged = merge_and_save(file_path, records, info)
        print(f"  [OK] 保存 {len(records)} 条新数据，当前值 {records[0]['value']}")
        results[sym] = merged
        time.sleep(1.0)

    # ── Fed 流动性指标（LIQUIDITY_SCORE）────────────────────
    for sym, info in LIQUIDITY_SERIES.items():
        if symbols and sym not in symbols:
            continue

        print(f"\n{'='*50}")
        print(f"🏦 {sym}: {info['name']}")
        print(f"{'='*50}")

        file_path = KLINE / info["file"]

        existing = load_existing(file_path)
        latest_date = None
        if existing:
            latest_date = max(r["date"] for r in existing)
            print(f"  [INFO] 现有数据: {len(existing)} 条，最新 {latest_date}")

        fetch_start = latest_date if latest_date else start_date
        print(f"  [INFO] 获取范围: {fetch_start} → {end_date}")

        if latest_date and latest_date >= end_date:
            print(f"  [SKIP] 数据已是最新")
            results[sym] = existing
            continue

        # RRPONTSYD 需要 forward_fill
        forward_fill = (sym == "RRPONTSYD")
        records = fetch_fred_csv(info["fred_code"], fetch_start, end_date,
                                forward_fill=forward_fill)

        if not records:
            print(f"  [WARN] FRED 返回空数据")
            results[sym] = existing
            continue

        merged = merge_and_save(file_path, records, info)
        print(f"  [OK] 保存 {len(records)} 条新数据，总计 {len(merged)} 条")
        results[sym] = merged
        time.sleep(1.2)

    return results


def fetch_latest(symbol: str) -> dict:
    """仅获取单个指标最新一条数据"""
    if symbol not in FRED_SERIES:
        print(f"[ERROR] Unknown symbol: {symbol}")
        return None

    info = FRED_SERIES[symbol]
    end_date   = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")

    records = fetch_fred_csv(info["fred_code"], start_date, end_date)
    if records:
        latest = records[-1]
        print(f"[INFO] {symbol} 最新: {latest['date']} = {latest['value']}")
        return latest
    return None


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="FRED 市场指标数据获取")
    parser.add_argument("--full",    action="store_true", help="全量回溯1年")
    parser.add_argument("--days",    type=int, default=DEFAULT_LOOKBACK_DAYS,
                         help=f"回溯天数（默认{DEFAULT_LOOKBACK_DAYS}天）")
    parser.add_argument("--symbol",  type=str, default=None,
                         help="只获取指定指标（TNX|HY_SPREAD|VIX_FRED）")
    args = parser.parse_args()

    lookback = 365 if args.full else args.days
    symbols  = [args.symbol] if args.symbol else None

    print(f"[INFO] 回溯 {lookback} 天{'（全量）' if args.full else ''}")
    results = fetch_all(lookback_days=lookback, symbols=symbols)

    print("\n\n[完成] 获取结果:")
    for sym, records in results.items():
        if records:
            latest = records[-1]
            print(f"  ✅ {sym}: {latest['date']} = {latest['value']}")
        else:
            print(f"  ❌ {sym}: 无数据")
