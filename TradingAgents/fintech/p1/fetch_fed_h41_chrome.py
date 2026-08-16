#!/usr/bin/env python3
"""
Fed H.4.1 每周资产负债表抓取
================================
通过 Chrome CDP 从 Fed 官网抓取 H.4.1 每周数据，
解析出 LIQUIDITY_SCORE 所需的三个指标：

  WALCL     → Reserve Bank credit（Fed 总资产）
  RRPONTSYD → Reverse repurchase agreements（隔夜逆回购）
  WTREGEN   → U.S. Treasury General Account（财政部活期账户）

H.4.1 每周四发布，数据截止到上一个周三。
每周只有一个数据点（非交易日顺延）。

数据来源：https://www.federalreserve.gov/releases/h41/YYYYMMDD/

注意：Fed H.4.1 数据为"Factors Affecting Reserve Balances"表中的：
  - Reserve Bank credit（行1，列：Wednesday May xx）
  - Reverse repurchase agreements总额（行36，含 foreign official + others）
  - U.S. Treasury, General Account（行48）

单位：百万美元

用法：
    python3 fetch_fed_h41_chrome.py              # 增量更新（自动找最新可用日期）
    python3 fetch_fed_h41_chrome.py --full       # 回溯3年
    python3 fetch_fed_h41_chrome.py --check     # 仅检查最新状态
"""

import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ──────────────────────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────────────────────

PROJ  = Path(__file__).parent.parent.parent
KLINE = PROJ / "中间过程" / "klines"
KLINE.mkdir(parents=True, exist_ok=True)

CHROME_DEBUG_URL = "http://172.25.192.1:19222"

# FRED 系列对应（H.4.1 映射）
SERIES_MAP = {
    "WALCL": {
        "name": "Fed Total Assets (Reserve Bank Credit)",
        "unit": "million USD",
        "file": "WALCL_1d.json",
        "h41_label": "Reserve Bank credit",
        "col_idx": 1,   # Wednesday 列
    },
    "RRPONTSYD": {
        "name": "Overnight Reverse Repurchase (Total RRP)",
        "unit": "million USD",
        "file": "RRPONTSYD_1d.json",
        "h41_label": "Reverse repurchase agreements",
        "col_idx": 1,
    },
    "WTREGEN": {
        "name": "Treasury General Account Balance",
        "unit": "million USD",
        "file": "WTREGEN_1d.json",
        "h41_label": "U.S. Treasury, General Account",
        "col_idx": 1,
    },
}


# ──────────────────────────────────────────────────────────────
# Chrome CDP 抓取单周数据
# ──────────────────────────────────────────────────────────────

def fetch_week_via_chrome(date_str: str) -> Optional[dict]:
    """
    通过 Chrome CDP 抓取指定周的 H.4.1 数据

    参数:
        date_str: 周四日期 YYYYMMDD 或 YYYY-MM-DD

    返回:
        {"date": "2026-05-13", "WALCL": 6673028, "RRPONTSYD": 299605, "WTREGEN": 838584}
        若失败返回 None
    """
    # 规范化日期
    clean = date_str.replace("-", "")
    url = f"https://www.federalreserve.gov/releases/h41/{clean}/"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[ERROR] playwright not installed")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(CHROME_DEBUG_URL, timeout=30000)
            page = browser.contexts[0].new_page()
            try:
                page.goto(url, timeout=25000)
                page.wait_for_timeout(5000)
                text = page.inner_text("body")
            finally:
                # 无论成功失败，page 和 browser 用完即关闭
                try:
                    page.close()
                except Exception:
                    pass
            browser.close()
    except Exception as e:
        print(f"  [Chrome ERROR] {e}")
        return None

    # 解析文本内容
    # H.4.1 表格结构：
    #   [日期行] "Wednesday May 13, 2026"
    #   [标签行] "Reserve Bank credit"
    #   [数据行] "6,673,028    +18,239    +7,863    6,681,090"
    #
    # 注意：同一个标签在页脚可能出现多次（如 RRP 在正文、表尾、备注均有）
    # 策略：只取第一次出现的匹配（主表），后续的忽略

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    result = {}
    result_date = None
    found_labels = set()  # 防止页脚重复匹配

    for i, line in enumerate(lines):
        # 识别日期行 - H.4.1 日期分两行：
        #   "Wednesday"
        #   "May 13, 2026"
        if result_date is None:
            # 尝试单行模式
            date_match = re.search(
                r"(Wednesday|Thursday|Friday)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(\d{4})",
                line
            )
            if date_match:
                months = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,"Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
                month = months.get(date_match.group(2), 1)
                day = int(date_match.group(3))
                year = int(date_match.group(4))
                result_date = f"{year:04d}-{month:02d}-{day:02d}"
                continue

            # 尝试两行模式
            if line in ("Wednesday", "Thursday", "Friday"):
                for j in range(1, 5):
                    if i + j < len(lines):
                        next_line = lines[i + j]
                        date_match2 = re.search(
                            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(\d{4})",
                            next_line
                        )
                        if date_match2:
                            months = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,"Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
                            month = months.get(date_match2.group(1), 1)
                            day = int(date_match2.group(2))
                            year = int(date_match2.group(3))
                            result_date = f"{year:04d}-{month:02d}-{day:02d}"
                            break

        # 识别目标指标（每个标签只取第一次）
        for sym, info in SERIES_MAP.items():
            if sym in found_labels:
                continue
            label = info["h41_label"]
            if label in line:
                # 在当前行和后续3行找第一个大数字
                search_lines = lines[i : i + 3]
                for sl in search_lines:
                    # 去掉不可见字符（非白色空格分隔的数字，如 + 18,239 中的 + 不算独立token）
                    clean_line = re.sub(r"[^0-9,]", "", sl)
                    nums = re.findall(r"([0-9,]{6,})", clean_line)
                    if nums:
                        try:
                            value = int(nums[0].replace(",", ""))
                            if value > 100_000:  # 至少10亿美元（百万单位）
                                result[sym] = value
                                found_labels.add(sym)
                                print(f"  [OK] {sym}: {value:,} ({result_date})")
                                break
                        except ValueError:
                            pass

    if result_date and len(result) >= 1:
        result["date"] = result_date
        return result
    else:
        print(f"  [WARN] 解析失败: {date_str} (found: {list(result.keys())})")
        return None


# ──────────────────────────────────────────────────────────────
# 获取最新可用周（周四发布，顺延找最近已发布的）
# ──────────────────────────────────────────────────────────────

def get_latest_thursday_url() -> Optional[str]:
    """找到最近一个有 H.4.1 数据的周四日期"""
    # 今天
    today = datetime.now()

    # 最多回溯8天（找最近的周四）
    for days_back in range(0, 8):
        check_date = today - timedelta(days=days_back)
        if check_date.weekday() == 3:  # 周四
            return check_date.strftime("%Y%m%d")

    # 如果今天不是周四，找上一个周四
    days_since_thursday = (today.weekday() - 3) % 7
    last_thursday = today - timedelta(days=days_since_thursday if days_since_thursday else 7)
    return last_thursday.strftime("%Y%m%d")


# ──────────────────────────────────────────────────────────────
# 文件操作
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
        "source": "Federal Reserve H.4.1 (via Chrome CDP)",
        "source_url": "https://www.federalreserve.gov/releases/h41/",
        "last_updated": datetime.now().isoformat(),
        "unit": meta.get("unit", "million USD"),
        "note": meta.get("note", ""),
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


# ──────────────────────────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────────────────────────

def fetch_all(lookback_weeks: int = 52, force: bool = False):
    """
    批量获取 H.4.1 历史数据

    参数:
        lookback_weeks: 回溯周数（默认52周≈1年）
        force: True=忽略本地数据强制重抓，False=跳过已有日期（默认）
    """
    today = datetime.now()
    results = {}

    for sym, info in SERIES_MAP.items():
        print(f"\n{'='*50}")
        print(f"🏦 {sym}: {info['name']}")
        print(f"{'='*50}")

        file_path = KLINE / info["file"]
        existing = load_existing(file_path)
        existing_dates = set(r["date"] for r in existing)

        if existing:
            latest = max(r["date"] for r in existing)
            print(f"  [INFO] 现有 {len(existing)} 条，最新 {latest}")

        print(f"  [INFO] 回溯 {lookback_weeks} 周...")

    # 获取所需日期列表
    # 找上一个周四作为起点
    today_dt = datetime.now()
    days_since_thursday = (today_dt.weekday() - 3) % 7
    last_thursday = today_dt - timedelta(days=days_since_thursday)

    dates_to_fetch = []
    current = last_thursday
    for _ in range(lookback_weeks):
        dates_to_fetch.append(current.strftime("%Y%m%d"))
        current -= timedelta(days=7)  # 每周倒退

    # 反转，从旧到新
    dates_to_fetch = list(reversed(dates_to_fetch))

    print(f"\n  [INFO] 需获取 {len(dates_to_fetch)} 周数据")

    # ── 预先构建已有日期集合（一次性，避免循环内重复计算）──
    existing_dates_set = set()
    if not force:
        for sym in SERIES_MAP:
            fp = KLINE / SERIES_MAP[sym]["file"]
            if fp.exists():
                existing_dates_set.update(r["date"] for r in load_existing(fp))
        print(f"  [INFO] 本地已有 {len(existing_dates_set)} 周数据")

    # 分批获取（每批5个，防止频率限制）
    all_weeks = []
    for i, date_str in enumerate(dates_to_fetch):
        clean = date_str
        date_iso = f"{clean[:4]}-{clean[4:6]}-{clean[6:8]}"
        print(f"\n  [{i+1}/{len(dates_to_fetch)}] {date_iso}...", end=" ", flush=True)

        if not force and date_iso in existing_dates_set:
            print("已存在，跳过")
            continue

        week_data = fetch_week_via_chrome(clean)
        if week_data:
            all_weeks.append(week_data)
            time.sleep(1.5)
        else:
            time.sleep(1)

    # 保存各指标
    for sym, info in SERIES_MAP.items():
        file_path = KLINE / info["file"]
        sym_records = []
        for week in all_weeks:
            if sym in week:
                sym_records.append({
                    "date": week["date"],
                    "value": week[sym],
                    "note": "weekly H.4.1",
                })

        if sym_records:
            merged = merge_and_save(file_path, sym_records, info)
            print(f"\n  [OK] {sym}: 保存 {len(sym_records)} 条，总计 {len(merged)} 条")

    return results


def fetch_latest() -> dict:
    """仅抓取最新一周"""
    latest = get_latest_thursday_url()
    if not latest:
        return {}

    date_iso = f"{latest[:4]}-{latest[4:6]}-{latest[6:8]}"
    print(f"[INFO] 抓取最新周: {latest} ({date_iso})")

    week_data = fetch_week_via_chrome(latest)
    if not week_data:
        return {}

    for sym, info in SERIES_MAP.items():
        file_path = KLINE / info["file"]
        if sym in week_data:
            record = {"date": week_data["date"], "value": week_data[sym], "note": "weekly H.4.1"}
            merge_and_save(file_path, [record], info)
            print(f"  [OK] {sym}: {record['value']:,}")

    return week_data


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fed H.4.1 每周资产负债表抓取")
    parser.add_argument("--full",   action="store_true", help="回溯52周")
    parser.add_argument("--weeks", type=int, default=8,  help=f"回溯周数（默认8周）")
    parser.add_argument("--check",  action="store_true", help="仅检查最新状态")
    parser.add_argument("--force",  action="store_true", help="强制重新获取所有周")
    args = parser.parse_args()

    # ── 快速检查：本地是否已有最新周数据 ──
    def _local_latest():
        """返回本地已有的最新 H.4.1 日期"""
        latest = None
        for sym in SERIES_MAP:
            fp = KLINE / SERIES_MAP[sym]["file"]
            if fp.exists():
                with open(fp) as f:
                    obj = json.load(f)
                dates = [r["date"] for r in obj.get("data", [])]
                if dates:
                    m = max(dates)
                    if latest is None or m > latest:
                        latest = m
        return latest

    local_latest = _local_latest()
    today = datetime.now()
    days_since_thursday = (today.weekday() - 3) % 7
    latest_thursday = (today - timedelta(days=days_since_thursday)).strftime("%Y-%m-%d")

    if args.check:
        if local_latest and local_latest >= latest_thursday:
            print(f"[INFO] 本地已有最新周数据: {local_latest} >= {latest_thursday}，无需打开 Chrome")
            # 显示本地数据
            for sym in SERIES_MAP:
                fp = KLINE / SERIES_MAP[sym]["file"]
                if fp.exists():
                    with open(fp) as f:
                        obj = json.load(f)
                    rec = next((r for r in reversed(obj.get("data", [])) if r["date"] == local_latest), None)
                    if rec:
                        print(f"  {sym}: {local_latest} = {rec['value']:,}")
        else:
            latest = get_latest_thursday_url()
            print(f"[INFO] 本地最新: {local_latest} < {latest_thursday}，需要获取最新周: {latest}")
            week = fetch_week_via_chrome(latest)
            if week:
                print(f"\n📊 {week.get('date')}:")
                for sym in SERIES_MAP:
                    if sym in week:
                        print(f"  {sym}: {week[sym]:,}")
    elif args.full:
        fetch_all(lookback_weeks=52, force=args.force)
    else:
        fetch_all(lookback_weeks=args.weeks, force=args.force)
