#!/usr/bin/env python3
"""
CTA Positioning Fetch Script
============================
获取 S&P 500 COT 数据（Non-Commercial 机构净仓位）
数据源: Tradingster JSON API
     (原始来源: CFTC COT Weekly Report)

CTA Positioning 用于 regime_engine_v2 的 get_cta_positioning() 函数。

用法:
    python3 fetch_cot_cta.py              # 抓取并保存
    python3 fetch_cot_cta.py --check       # 只检查最新值
"""

import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

API_URL = "https://www.tradingster.com/api/cot/legacy-futures/13874%2B"
OUTPUT_FILE = Path(__file__).parent.parent.parent / "中间过程" / "klines" / "CTA_POSITIONING_1d.json"

# COT 报告每周五发布（数据截止周三），通常周三/周四可获取
_COT_PUBLISH_DAYS = [3, 4]  # 周四、周五通常能拿到最新周数据


def fetch_cot_data() -> list:
    """从 Tradingster API 获取完整 COT 历史数据"""
    req = urllib.request.Request(
        API_URL,
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def compute_cta_metrics(records: list) -> dict:
    """
    从 COT 原始记录计算 CTA 指标
    - net_position: Noncommercial_Long - Noncommercial_Short
    - net_position_pct: net / (Long + Short) * 100
    - weekly_change: net_position 相比上周变化
    """
    metrics = {}
    for i, rec in enumerate(records):
        date = rec["As_of_Date"]
        long_all = rec["Noncommercial_Positions_Long_All"]
        short_all = rec["Noncommercial_Positions_Short_All"]
        net = long_all - short_all
        total = long_all + short_all
        pct = net / total * 100 if total > 0 else 0

        # 周变化（需要前一周数据）
        prev_net = None
        if i > 0:
            prev_net = (
                records[i - 1]["Noncommercial_Positions_Long_All"]
                - records[i - 1]["Noncommercial_Positions_Short_All"]
            )

        metrics[date] = {
            "long": long_all,
            "short": short_all,
            "net": net,
            "net_pct": round(pct, 3),
            "weekly_change": net - prev_net if prev_net is not None else 0,
        }
    return metrics


def compute_historical_percentile(net: int, all_nets: list) -> float:
    """计算当前净仓位的历史百分位"""
    below = sum(1 for n in all_nets if n < net)
    return round(below / len(all_nets) * 100, 2)


def _latest_cot_friday() -> str:
    """计算最近一个可获取COT数据的周五（今天或之前）"""
    today = datetime.now()
    # COT 周五发布，数据通常在周四/周五可查
    # 找到上一个周五
    days_since_friday = (today.weekday() - 4) % 7
    last_friday = today - timedelta(days=days_since_friday)
    return last_friday.strftime("%Y-%m-%d")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--force", action="store_true", help="强制重新获取")
    args = parser.parse_args()

    # ── 检查本地最新日期 ──
    latest_local = None
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE) as f:
            obj = json.load(f)
        dates = list(obj.get("data", {}).keys())
        if dates:
            latest_local = max(dates)

    latest_needed = _latest_cot_friday()

    if not args.force and latest_local is not None and latest_local >= latest_needed:
        print(f"[SKIP] 本地数据已是最新: {latest_local} >= {latest_needed}")
        print(f"       如需强制更新，请加 --force")
        # 仍然输出状态
        obj = json.load(open(OUTPUT_FILE)) if OUTPUT_FILE.exists() else {"data": {}}
        all_nets = [m["net"] for m in obj.get("data", {}).values()]
        latest_date = max(obj["data"].keys()) if obj.get("data") else None
        if latest_date:
            m = obj["data"][latest_date]
            pct = compute_historical_percentile(m["net"], all_nets)
            print(f"\n[CTA Positioning Check]  {latest_date}")
            print(f"  Net Position:   {m['net']:+,}  ({m['net_pct']:+.1f}%)")
            print(f"  Historical %ile: {pct:.1f}%")
        return

    print(f"[INFO] 本地最新: {latest_local or '无'} → 需要: {latest_needed}，开始获取...")
    records = fetch_cot_data()
    print(f"  Received {len(records)} weekly records")

    metrics = compute_cta_metrics(records)

    # 历史百分位
    all_nets = [m["net"] for m in metrics.values()]
    latest_date = sorted(metrics.keys())[-1]
    latest = metrics[latest_date]
    pct = compute_historical_percentile(latest["net"], all_nets)

    if args.check:
        print(f"\n[CTA Positioning Check]  {latest_date}")
        print(f"  Net Position:   {latest['net']:+,}  ({latest['net_pct']:+.1f}%)")
        print(f"  Historical %ile: {pct:.1f}%  ({'extreme short' if pct < 20 else 'short' if pct < 40 else 'neutral'})")
        print(f"  Weekly Change:   {latest['weekly_change']:+,}  ({'more short' if latest['weekly_change'] < 0 else 'less short'})")
        return

    # 写入文件
    output = {
        "metadata": {
            "source": "CFTC COT via Tradingster API",
            "url": API_URL,
            "description": "S&P 500 Noncommercial Net Positions (CTA Proxy)",
            "fields": {
                "net": "Long - Short (positive = net long)",
                "net_pct": "Net / Total * 100",
                "weekly_change": "Change vs previous week",
                "hist_pct": "Historical percentile of net position"
            },
            "last_updated": datetime.now().isoformat(),
        },
        "data": {}
    }

    for date, m in sorted(metrics.items()):
        hist_pct = compute_historical_percentile(m["net"], all_nets)
        output["data"][date] = {
            "long": m["long"],
            "short": m["short"],
            "net": m["net"],
            "net_pct": m["net_pct"],
            "weekly_change": m["weekly_change"],
            "hist_pct": hist_pct,
        }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to {OUTPUT_FILE}")
    print(f"Records: {len(output['data'])}")
    print(f"\nLatest ({latest_date}):")
    print(f"  Net Position:   {latest['net']:+,}  ({latest['net_pct']:+.1f}%)")
    print(f"  Historical %ile: {pct:.1f}%")
    print(f"  Weekly Change:  {latest['weekly_change']:+,}  (more short)" if latest["weekly_change"] < 0 else f"  Weekly Change:  {latest['weekly_change']:+,}")

    # 解读
    if pct < 10:
        interpretation = "🔴 EXTREME SHORT - Contrarian bullish (potential squeeze)"
    elif pct < 25:
        interpretation = "🟠 VERY SHORT - Bearish positioning, but bullish for squeezes"
    elif pct < 45:
        interpretation = "🟡 SHORT - Mildly bearish"
    elif pct < 55:
        interpretation = "⚪ NEUTRAL"
    else:
        interpretation = "🟢 NET LONG territory"

    print(f"  Interpretation: {interpretation}")


if __name__ == "__main__":
    main()
