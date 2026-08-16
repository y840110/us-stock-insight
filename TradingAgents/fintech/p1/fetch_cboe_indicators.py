#!/usr/bin/env python3
"""
CBOE & 市场专属指标抓取
========================
通过 Chrome CDP 或 web_fetch 获取无法从 Yahoo Finance / FRED 获取的指标：

1. PUT_CALL_RATIO - 期权买卖比率（CBOE 官方每日发布）
2. NYAD - 纽交所涨跌线（通过 StockCharts.com 或 NYSE 官方数据计算）
3. GEX  - 机构 Gamma Exposure（通过 GitHub 开源算法计算）
4. CTA_POSITIONING - CTA 期货持仓（COT 报告）

用法：
    python3 fetch_cboe_indicators.py              # 抓取所有
    python3 fetch_cboe_indicators.py --symbol PUT_CALL_RATIO
    python3 fetch_cboe_indicators.py --check     # 仅检查最新状态
"""

import json
import time
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# ──────────────────────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────────────────────

PROJ  = Path(__file__).parent.parent.parent
KLINE = PROJ / "中间过程" / "klines"
INDICATORS_DIR = PROJ / "中间过程" / "market_indicators"
INDICATORS_DIR.mkdir(parents=True, exist_ok=True)
KLINE.mkdir(parents=True, exist_ok=True)

CHROME_DEBUG_URL = "http://172.25.192.1:19222"

# ──────────────────────────────────────────────────────────────
# 数据源定义
# ──────────────────────────────────────────────────────────────

INDICATORS = {
    "PUT_CALL_RATIO": {
        "name": "CBOE Total Put/Call Ratio",
        "source": "CBOE",
        "source_url": "https://www.cboe.com/us/options/market_statistics/?downloadable=1",
        "file": "PUT_CALL_RATIO_1d.json",
        "method": "cboe_web",
        "note": "CBOE每日期权统计，包含put/call比率",
    },
    "GEX": {
        "name": "SPX Gamma Exposure (估算)",
        "source": "Self-calculated",
        "source_url": "https://github.com/dmart1441/SPX-Gamma-Exposure",
        "file": "GEX_1d.json",
        "method": "calculate",
        "note": "需要SPX期权链数据，当前用代理指标代替",
    },
    "CTA_POSITIONING": {
        "name": "CFTC Commitment of Traders (CTA Proxy)",
        "source": "CFTC COT",
        "source_url": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
        "file": "CTA_POSITIONING_1d.json",
        "method": "cftec_web",
        "note": "COT报告中资产管理人净持仓，作为CTA趋势代理",
    },
    "NYAD": {
        "name": "NYSE Advance-Decline Line",
        "source": "StockCharts / Self-calculated",
        "source_url": "https://stockcharts.com/freecharts/advdecl.php?b=1",
        "file": "NYAD_1d.json",
        "method": "stockcharts_web",
        "note": "NYSE上涨-下跌家数累计值，需从网页抓取",
    },
}


# ──────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────

def load_existing(file_path: Path) -> list:
    if file_path.exists():
        with open(file_path) as f:
            obj = json.load(f)
        return obj.get("data", [])
    return []


def save_data(file_path: Path, records: list, meta: dict):
    obj = {
        "name": meta.get("name", ""),
        "source": meta.get("source", ""),
        "source_url": meta.get("source_url", ""),
        "last_updated": datetime.now().isoformat(),
        "note": meta.get("note", ""),
        "method": meta.get("method", ""),
        "data": records,
    }
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def merge_and_save(file_path: Path, new_records: list, meta: dict):
    existing = load_existing(file_path)
    all_records = {r["date"]: r for r in existing}
    all_records.update({r["date"]: r for r in new_records})
    merged = sorted(all_records.values(), key=lambda x: x["date"])
    save_data(file_path, merged, meta)
    return merged


def fetch_web_content(url: str, timeout: int = 20) -> str:
    """通过 web_fetch 获取页面内容"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        print(f"  [WEB ERROR] {e}")
        return ""


# ──────────────────────────────────────────────────────────────
# 1. Put/Call Ratio - CBOE 官方（Chrome CDP）
# ──────────────────────────────────────────────────────────────

def _get_chrome_debug_url():
    """获取 Chrome CDP URL"""
    # 尝试多个可能的路径
    possible_paths = [
        Path(__file__).parent / 'fetch_us_stocks_cdp.py',
        Path(__file__).parent.parent / 'p1' / 'fetch_us_stocks_cdp.py',
    ]
    for p in possible_paths:
        if p.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location('fsc', str(p))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return getattr(mod, 'CHROME_DEBUG_URL', 'http://172.25.192.1:19222')
    return 'http://172.25.192.1:19222'


def fetch_put_call_ratio_via_cboe() -> list:
    """
    从 CBOE 官方每日市场统计页面抓取 Put/Call Ratio
    使用 Chrome CDP 访问 JS 动态渲染的页面

    页面: https://www.cboe.com/markets/us/options/market-statistics/daily
    数据: TOTAL PUT/CALL RATIO, EQUITY PUT/CALL RATIO 等19个指标
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [ERROR] playwright not installed")
        return []

    CHROME_DEBUG_URL = _get_chrome_debug_url()
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(CHROME_DEBUG_URL, timeout=30000)
            page = browser.contexts[0].new_page()

            try:
                page.goto(
                    'https://www.cboe.com/markets/us/options/market-statistics/daily',
                    timeout=25000
                )
                page.wait_for_timeout(8000)  # 等待JS渲染

                # 获取页面文本内容
                text = page.inner_text('body')
                lines = [l.strip() for l in text.split('\n') if l.strip()]

                # 解析 PUT/CALL RATIO 数据
                records = []
                for line in lines:
                    parts = line.split('\t')
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val_str = parts[1].strip()
                        if 'PUT/CALL RATIO' in key or key.endswith('PUT/CALL'):
                            try:
                                value = float(val_str)
                                records.append({
                                    "date": today,
                                    "ratio_name": key,
                                    "value": value
                                })
                            except ValueError:
                                pass
            finally:
                # 无论成功失败，page 用完即关闭
                try:
                    page.close()
                except Exception:
                    pass

            browser.close()

            if records:
                print(f"  [OK] 获取到 {len(records)} 个 Put/Call 比率")
                # 打印关键指标
                for r in records:
                    if r['ratio_name'] in ('TOTAL PUT/CALL RATIO', 'EQUITY PUT/CALL RATIO', 'SPX + SPXW PUT/CALL RATIO'):
                        print(f"      {r['ratio_name']}: {r['value']}")
            else:
                print(f"  [WARN] 未解析到 Put/Call 数据")

            return records

    except Exception as e:
        print(f"  [ERROR] Chrome CDP failed: {e}")
        return []


def fetch_put_call_ratio_simple() -> list:
    """
    简化版：通过 urllib 直接获取 CBOE 页面文本（不依赖 Chrome）
    适用于无头环境
    """
    url = 'https://www.cboe.com/markets/us/options/market-statistics/daily'
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; OpenClaw/1.0)',
        'Accept': 'text/html',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"  [WEB ERROR] {e}")
        return []

    # 页面是JS渲染的，直接解析HTML拿不到数据
    # 但尝试找 data-* 属性或内联JSON
    import re
    records = []
    today = datetime.now().strftime("%Y-%m-%d")

    # 格式: "TOTAL PUT/CALL RATIO	0.67"
    pattern = r'([A-Z][A-Za-z]*(?:\s+A?[A-Z][A-Za-z]*)*\s+PUT/CALL\s+RATIO)\t+([0-9.]+)'
    matches = re.findall(pattern, content)
    for key, val_str in matches:
        try:
            value = float(val_str)
            records.append({
                "date": today,
                "ratio_name": key.strip(),
                "value": value
            })
        except ValueError:
            pass

    if records:
        print(f"  [OK] 获取到 {len(records)} 个比率（简化模式）")
    else:
        print(f"  [WARN] 简化模式无法解析数据，需要 Chrome CDP")

    return records


# ──────────────────────────────────────────────────────────────
# 2. NYAD - 通过 StockCharts 抓取
# ──────────────────────────────────────────────────────────────

def fetch_nyad_via_stockcharts() -> list:
    """
    从 StockCharts.com 的 A/D 线页面抓取 NYSE Cumulative A/D Line

    NYSE A/D Line 计算：
    每日 NYAD = 前一日 NYAD + (上涨家数 - 下跌家数)

    StockCharts 页面提供可直接使用的 cumulative 数据
    """
    url = "https://stockcharts.com/freecharts/advdecl.php?b=1"

    content = fetch_web_content(url)
    if not content:
        print(f"  [WARN] 无法获取 StockCharts 页面")
        return []

    records = _parse_nyad_from_html(content)
    return records


def _parse_nyad_from_html(content: str) -> list:
    """从 HTML 解析 NYAD 数据"""
    import re

    records = []
    # StockCharts 图表数据通常在 JavaScript 数组中
    # 格式: [new Date("2026-05-13"), 12450.33]
    pattern = r'new\s+Date\s*\(\s*["\'](\d{4}-\d{2}-\d{2})["\']\s*\)\s*,\s*([0-9.,]+)'
    matches = re.findall(pattern, content)

    for date_str, value_str in matches[-60:]:  # 取最近60条
        try:
            value = float(value_str.replace(",", ""))
            records.append({"date": date_str, "value": value})
        except ValueError:
            pass

    if records:
        print(f"  [OK] 解析到 {len(records)} 条 NYAD 数据")
    else:
        # 尝试更宽松的匹配
        pattern2 = r'(\d{4}-\d{2}-\d{2})[^0-9-]*(-?[0-9,]+\.[0-9]+)'
        matches2 = re.findall(pattern2, content)
        for date_str, value_str in matches2[-60:]:
            try:
                value = float(value_str.replace(",", ""))
                if abs(value) > 1000:  # NYAD 通常是大数字
                    records.append({"date": date_str, "value": value})
            except ValueError:
                pass

    return sorted(records, key=lambda x: x["date"])


# ──────────────────────────────────────────────────────────────
# 3. CTA Positioning - CFTC COT
# ──────────────────────────────────────────────────────────────

def fetch_cta_positioning_via_cftc() -> list:
    """
    从 CFTC 官方 COT 报告获取资产管理人净持仓

    CFTC 每周五发布_commitment_of_traders_报告，
    包含 Futures & Options Combined 的资产管理人（Asset Manager）净多空持仓

    可作为 CTA 趋势跟随策略的代理指标
    """
    # CFTC 提供 CSV 下载
    csv_url = (
        "https://www.cftc.gov/files/dea/cOTs拱current.csv"
    )

    alt_url = "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm"

    content = fetch_web_content(alt_url)
    if not content:
        print(f"  [WARN] 无法获取 CFTC 页面")
        return []

    # CFTC 页面通常有 CSV 下载链接
    import re
    csv_link_pattern = r'href=["\']([^"\']*cOTs[^"\']*\.csv[^"\']*)["\']'
    links = re.findall(csv_link_pattern, content, re.IGNORECASE)

    if links:
        print(f"  [FOUND] CFTC CSV 链接: {links[0][:80]}")
        csv_content = fetch_web_content(links[0])
        if csv_content:
            records = _parse_cftc_csv(csv_content)
            return records

    print(f"  [WARN] 无法解析 CFTC COT 数据")
    return records


def _parse_cftc_csv(content: str) -> list:
    """解析 CFTC COT CSV"""
    import re

    records = []
    lines = content.strip().split("\n")

    # 跳过头部，找到 Futures & Options Combined 的 Asset Manager 持仓
    for line in lines:
        # 寻找 S&P 500 相关
        if "SP500" in line or "E-mini S&P" in line:
            parts = line.split(",")
            if len(parts) > 8:
                try:
                    # 格式：Date,CFTC S&P 500 Futures and Options,...
                    date_str = parts[0].strip()
                    # 第8列开始是各类持仓
                    # 需要找到 Asset Manager Net Position
                    for i, p in enumerate(parts):
                        if "Asset Manager" in p or "Managed Money" in p:
                            if i + 1 < len(parts):
                                value = float(parts[i + 1].strip())
                                records.append({
                                    "date": date_str,
                                    "value": value,
                                    "note": p.strip()
                                })
                except (ValueError, IndexError):
                    pass

    return records[-30:]  # 最近30周


# ──────────────────────────────────────────────────────────────
# 4. GEX - 代理指标（当无法计算时）
# ──────────────────────────────────────────────────────────────

def get_gex_proxy() -> float:
    """
    GEX 代理指标：当无法从期权链计算真实GEX时，使用代理

    简化代理逻辑：
    - 当 VIX < 15 且 SPY 创新高 → GEX = 正（稳定）
    - 当 VIX > 25 → GEX = 负（波动放大）
    - 其他情况 → GEX = 0（中性）

    真实 GEX 计算需要 SPX 期权链数据（Bloomberg/Refinitiv）
    """
    vix_file = KLINE / "VIX_1d.json"
    spy_file = KLINE / "SPY_1d.json"

    vix = None
    spy_hist = None

    if vix_file.exists():
        with open(vix_file) as f:
            d = json.load(f)
        for bar in reversed(d.get("data", [])):
            vix = bar.get("close") or bar.get("value")
            if vix:
                break

    if spy_file.exists():
        with open(spy_file) as f:
            spy_data = json.load(f).get("data", [])
        spy_hist = spy_data[-252:] if spy_data else []

    if vix is None:
        return 0.0

    # 简化代理
    if vix < 15:
        return 1.0
    elif vix > 25:
        return -1.0
    else:
        return 0.0


# ──────────────────────────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────────────────────────

def fetch_all(lookback_days: int = 60, symbols: list = None):
    """批量获取所有/指定指标"""
    results = {}
    end_date   = datetime.now().strftime("%Y-%m-%d")
    start_date  = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    for sym, info in INDICATORS.items():
        if symbols and sym not in symbols:
            continue

        print(f"\n{'='*50}")
        print(f"📊 {sym}: {info['name']}")
        print(f"{'='*50}")
        print(f"  方法: {info['method']}")

        file_path = INDICATORS_DIR / info["file"]

        # 已有数据
        existing = load_existing(file_path)
        latest_date = max((r["date"] for r in existing), default=None)
        if existing:
            print(f"  [INFO] 现有 {len(existing)} 条，最新 {latest_date}")

        # ── 增量跳过检查：已有今日数据则跳过 ──
        def _is_fresh(sym_name, latest):
            if not latest:
                return False
            today = datetime.now().strftime("%Y-%m-%d")
            return latest >= today

        if sym == "PUT_CALL_RATIO":
            if _is_fresh(sym, latest_date):
                print(f"  [SKIP] PUT_CALL_RATIO 已是今日 ({latest_date})，跳过 Chrome 抓取")
                records = []
            else:
                records = fetch_put_call_ratio_via_cboe()

        elif sym == "NYAD":
            if _is_fresh(sym, latest_date):
                print(f"  [SKIP] NYAD 已是今日 ({latest_date})，跳过抓取")
                records = []
            else:
                records = fetch_nyad_via_stockcharts()

        elif sym == "CTA_POSITIONING":
            # CTA COT 每周五发布，检查是否已有最新周数据
            if latest_date:
                today = datetime.now()
                days_since_friday = (today.weekday() - 4) % 7
                latest_friday = (today - timedelta(days=days_since_friday)).strftime("%Y-%m-%d")
                if latest_date >= latest_friday:
                    print(f"  [SKIP] CTA 已是最新周 ({latest_date})，跳过抓取")
                    records = []
                else:
                    records = fetch_cta_positioning_via_cftc()
            else:
                records = fetch_cta_positioning_via_cftc()

        elif sym == "GEX":
            # GEX 无法每日获取，写代理值
            proxy_val = get_gex_proxy()
            records = [{"date": end_date, "value": proxy_val}]
            print(f"  [PROXY] GEX 代理值: {proxy_val}")

        else:
            records = []

        if records:
            merged = merge_and_save(file_path, records, info)
            print(f"  [OK] 保存 {len(records)} 条，总计 {len(merged)} 条")
            results[sym] = merged
        else:
            results[sym] = existing
            print(f"  [SKIP] 无新数据")

    return results


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CBOE & 市场专属指标获取")
    parser.add_argument("--symbol", type=str, default=None,
                         help="指定指标（PUT_CALL_RATIO|NYAD|GEX|CTA_POSITIONING）")
    parser.add_argument("--days",   type=int, default=60, help="回溯天数")
    parser.add_argument("--check",   action="store_true", help="仅检查状态")
    args = parser.parse_args()

    if args.check:
        for sym, info in INDICATORS.items():
            fp = INDICATORS_DIR / info["file"]
            existing = load_existing(fp) if fp.exists() else []
            if existing:
                latest = existing[-1]
                print(f"  ✅ {sym}: {latest['date']} = {latest['value']}")
            else:
                print(f"  ❌ {sym}: 无数据")
    else:
        symbols = [args.symbol] if args.symbol else None
        results = fetch_all(lookback_days=args.days, symbols=symbols)
        print("\n\n[完成]")
        for sym, records in results.items():
            if records:
                latest = records[-1]
                print(f"  ✅ {sym}: {latest['date']} = {latest['value']}")
