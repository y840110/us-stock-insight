#!/usr/bin/env python3
"""
VIX & TNX 数据获取脚本
======================
由于 Yahoo Finance 不提供 VIX 和 TNX 的标准 K 线数据，
本脚本通过 FRED（Federal Reserve Economic Data）API 获取。

FRED 数据说明：
- VIX: CBOE VIX Index  → FRED代码: VIXCLS
- US10Y: 10年期国债收益率 → FRED代码: DGS10
- VVIX: VIX of VIX → FRED代码: VVIXCLS（需授权）

FRED API: https://fred.stlouisfed.org/docs/api/fred/
无需API Key即可获取大部分数据（限速）
"""

import json
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# ──────────────────────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────────────────────

KLINE_DIR = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines")

FRED_DATA = {
    "VIX": {
        "fred_code": "VIXCLS",
        "name": "CBOE Volatility Index (VIX)",
        "unit": "percent",
        "file": "VIX_1d.json",
    },
    "TNX": {
        "fred_code": "DGS10",
        "name": "10-Year Treasury Constant Maturity Rate",
        "unit": "percent",
        "file": "TNX_1d.json",
    },
}

# ──────────────────────────────────────────────────────────────
# FRED API 读取函数
# ──────────────────────────────────────────────────────────────

def fetch_fred_series(series_id: str, start_date: str, end_date: str = None) -> list:
    """
    从 FRED API 获取数据序列
    
    参数:
        series_id: FRED 数据代码（如 VIXCLS, DGS10）
        start_date: 开始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD，默认为今天
    
    返回:
        [{"date": "2026-05-13", "value": 17.8}, ...]
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    
    url = (
        f"https://fred.stlouisfed.org/graph/fredgraph.csv"
        f"?bgcolor=%23e1e9f4&chart_type=line&drpcd=0"
        f"&fo=%23ffffff&graph_bgcolor=%23ffffff&height=450"
        f"&mode=fred&recession_bars=on&txtcolor=%23444444"
        f"&ts=12&tts=12&width=1168&nt=0&thu=0&trc=0&show_legend=yes"
        f"&show_axis_titles=yes&show_tooltip=yes&id={series_id}"
        f"&cosd={start_date}&coed={end_date}"
        f"&line_color=%234572a7&link_values=false"
        f"&line_style=solid&mark_type=none&mw=3&lw=2&ost=-99999"
        f"&oet=99999&mma=0&fml=a&fq=Daily%2C%20Close&fam=avg"
        f"&fgst=lin&fgsnd=2020-02-01&line_index=1&transformation=lin"
        f"&vintage_date=2026-05-15&revision_date=2026-05-15"
        f"&nd={start_date}"
    )
    
    # 简化版：直接用 CSV 格式
    csv_url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start_date}&coed={end_date}"
    
    print(f"[FRED] Fetching {series_id} from {start_date} to {end_date}...")
    
    try:
        req = urllib.request.Request(
            csv_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; OpenClaw/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8")
        
        lines = content.strip().split("\n")
        if len(lines) < 2:
            print(f"[FRED] {series_id}: No data returned")
            return []
        
        # 解析 CSV（第一行是日期,值）
        records = []
        for line in lines[1:]:  # 跳过表头
            parts = line.strip().split(",")
            if len(parts) >= 2:
                date_str = parts[0]
                value_str = parts[1].strip()
                if value_str and value_str != ".":
                    try:
                        value = float(value_str)
                        records.append({"date": date_str, "value": value})
                    except ValueError:
                        pass
        
        print(f"[FRED] {series_id}: Got {len(records)} records")
        return records
        
    except Exception as e:
        print(f"[FRED] {series_id}: ERROR - {e}")
        return []


def load_existing_data(file_path: Path) -> dict:
    """加载现有数据文件"""
    if file_path.exists():
        with open(file_path) as f:
            return json.load(f)
    return {"data": []}


def save_data(file_path: Path, data: list, name: str):
    """保存数据到文件"""
    # 保留元数据头
    obj = {
        "name": name,
        "source": "FRED",
        "last_updated": datetime.now().isoformat(),
        "data": data,
    }
    with open(file_path, "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    print(f"[SAVE] {file_path.name}: {len(data)} records")


def merge_fred_data(existing: list, new: list) -> list:
    """
    合并现有数据和新数据
    以日期为 key，去重，排序
    """
    all_records = {r["date"]: r for r in existing}
    all_records.update({r["date"]: r for r in new})
    sorted_records = sorted(all_records.values(), key=lambda x: x["date"])
    return sorted_records


# ──────────────────────────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────────────────────────

def fetch_all(lookback_days: int = 365):
    """
    获取所有 FRED 数据的入口函数
    
    参数:
        lookback_days: 回溯天数（默认365天）
    """
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    
    results = {}
    
    for symbol, info in FRED_DATA.items():
        print(f"\n{'='*50}")
        print(f"处理 {symbol}: {info['name']}")
        print(f"{'='*50}")
        
        # 读取现有数据
        file_path = KLINE_DIR / info["file"]
        existing_obj = load_existing_data(file_path)
        existing_records = existing_obj.get("data", [])
        
        # 找出最新已有日期
        latest_date = None
        if existing_records:
            latest_date = max(r["date"] for r in existing_records)
            print(f"[INFO] 现有数据最新日期: {latest_date} ({len(existing_records)} 条)")
        
        # 确定需要获取的日期范围
        if latest_date and latest_date >= end_date:
            print(f"[INFO] 数据已是最新，跳过获取")
            results[symbol] = existing_records
            continue
        
        fetch_start = latest_date if latest_date else start_date
        print(f"[INFO] 需要获取: {fetch_start} → {end_date}")
        
        # 从 FRED 获取新数据
        new_records = fetch_fred_series(info["fred_code"], fetch_start, end_date)
        
        if not new_records:
            print(f"[WARN] {symbol}: FRED 返回空数据，保留现有数据")
            results[symbol] = existing_records
            continue
        
        # 合并数据
        if existing_records:
            merged = merge_fred_data(existing_records, new_records)
        else:
            merged = new_records
        
        # 保存
        save_data(file_path, merged, info["name"])
        results[symbol] = merged
        
        # FRED 限速：每秒请求不超过1次
        time.sleep(1.5)
    
    return results


def fetch_latest_only(symbol: str) -> dict:
    """
    仅获取最新一条数据（用于快速更新）
    """
    if symbol not in FRED_DATA:
        print(f"[ERROR] Unknown symbol: {symbol}")
        return None
    
    info = FRED_DATA[symbol]
    end_date = datetime.now().strftime("%Y-%m-%d")
    # 只取最近30天
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    records = fetch_fred_series(info["fred_code"], start_date, end_date)
    if records:
        latest = records[-1]
        print(f"[INFO] {symbol} 最新值: {latest['date']} = {latest['value']}")
        return latest
    return None


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="VIX & TNX FRED数据获取")
    parser.add_argument("--full", action="store_true", help="全量获取（365天回溯）")
    parser.add_argument("--days", type=int, default=30, help="回溯天数（默认30天）")
    parser.add_argument("--symbol", type=str, default=None, help="仅获取指定品种（VIX或TNX）")
    args = parser.parse_args()
    
    if args.full:
        print("全量模式：回溯365天...")
        results = fetch_all(lookback_days=365)
    else:
        print(f"增量模式：回溯{args.days}天...")
        results = fetch_all(lookback_days=args.days)
    
    print("\n\n[完成] 数据获取结果:")
    for sym, records in results.items():
        if records:
            latest = records[-1]
            print(f"  {sym}: {latest['date']} = {latest['value']}")
        else:
            print(f"  {sym}: 无数据")
