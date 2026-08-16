#!/usr/bin/env python3
"""
Compute NYAD (NYSE Advance-Decline Line) from local SPX constituent K-line data.

NYAD = Cumulative sum of (Advancing stocks - Declining stocks) each day.
We use the SPX constituent stock pool (~569 stocks) to compute this locally.

Output: NYAD_1d.json in klines/ directory.
"""
import json, sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

PROJ  = Path(__file__).parent.parent.parent.parent.resolve()
KLINES = PROJ / "中间过程" / "klines"
POOL   = PROJ / "fintech" / "stock_pool.json"
OUT    = KLINES / "NYAD_1d.json"


def get_spx_tickers():
    with open(POOL) as f:
        pool = json.load(f)
    return [s["code"] for s in pool.get("stocks", [])]


def load_stock_closes(tickers):
    """Load close prices for all tickers, keyed by date."""
    closes_by_date = defaultdict(dict)  # date -> {ticker: close}
    for ticker in tickers:
        fpath = KLINES / f"{ticker}_1d.json"
        if not fpath.exists():
            continue
        try:
            with open(fpath) as f:
                d = json.load(f)
            data = d
            while isinstance(data, dict) and "data" in data:
                data = data["data"]
            if not isinstance(data, list):
                continue
            for bar in data:
                date = bar.get("date")
                close = bar.get("close")
                if date and close is not None:
                    closes_by_date[date][ticker] = float(close)
        except Exception:
            continue
    return closes_by_date


def compute_nyad():
    tickers = get_spx_tickers()
    print(f"  Loading K-line data for {len(tickers)} SPX stocks...")

    closes_by_date = load_stock_closes(tickers)
    if not closes_by_date:
        print("  [ERROR] No stock data found")
        return

    dates = sorted(closes_by_date.keys())
    print(f"  Date range: {dates[0]} → {dates[-1]} ({len(dates)} days)")

    # For each date, compute advances vs declines vs prior close
    daily_net = {}  # date -> net advances (adv - dec)
    prev_closes = {}

    for date in dates:
        current_closes = closes_by_date[date]
        net = 0
        advances = 0
        declines = 0
        unchanged = 0

        for ticker, close in current_closes.items():
            prev = prev_closes.get(ticker)
            if prev is not None:
                if close > prev:
                    advances += 1
                    net += 1
                elif close < prev:
                    declines += 1
                    net -= 1
                else:
                    unchanged += 1

        daily_net[date] = net
        prev_closes = current_closes

    # Build cumulative NYAD
    nyad = {}
    cumulative = 0
    for date in dates:
        cumulative += daily_net[date]
        nyad[date] = cumulative

    # Load existing data to merge
    existing_nyad = {}
    existing_daily_net = {}
    if OUT.exists():
        try:
            with open(OUT) as f:
                old = json.load(f)
            existing_nyad = old.get("nyad", {})
            existing_daily_net = old.get("daily_net", {})
        except Exception:
            pass

    # Merge: update only new/updated dates
    all_dates = set(daily_net.keys()) | set(existing_daily_net.keys())
    merged_daily_net = dict(existing_daily_net)
    merged_daily_net.update(daily_net)

    merged_nyad = dict(existing_nyad)
    # Recompute cumulative from sorted dates
    sorted_all_dates = sorted(merged_daily_net.keys())
    cumulative = 0
    for date in sorted_all_dates:
        cumulative += merged_daily_net[date]
        merged_nyad[date] = cumulative

    # Save
    obj = {
        "metadata": {
            "description": "NYSE Advance-Decline Line computed from SPX constituent stocks daily data",
            "source": "local K-line database",
            "date_range": f"{sorted_all_dates[0]} to {sorted_all_dates[-1]}",
            "total_days": len(sorted_all_dates),
            "total_stocks": len(tickers),
            "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "daily_net": merged_daily_net,
        "nyad": merged_nyad,
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

    print(f"  [OK] Saved NYAD_1d.json: {len(merged_nyad)} days, last={sorted_all_dates[-1]}")
    return merged_nyad


if __name__ == "__main__":
    print("=" * 60)
    print("📊 Computing NYAD from local SPX K-line data")
    print("=" * 60)
    result = compute_nyad()
    print("\nDone.")
