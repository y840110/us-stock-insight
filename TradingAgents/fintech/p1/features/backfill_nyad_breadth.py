#!/usr/bin/env python3
"""
Backfill NYAD and market breadth from local K-line data.

Data sources (merged for maximum coverage):
  - p1/klines/     : 570 stocks, 2024-05-15 → present  (primary, most complete)
  - 中间过程/klines : 120 stocks, 2020-01-02 → 2025-09-09 (historical supplement)

For each date:
  1. Collect all stocks available from BOTH sources
  2. Deduplicate by ticker (prefer p1 source if ticker exists in both)
  3. Compute NYAD cumulative = sum of (close > prev_close)
  4. Compute breadth metrics

Output:
  - 中间过程/klines/NYAD_1d.json   (nyad + daily_net, full history)
  - 中间过程/klines/breadth_history.json (market breadth time series)
"""
import json, sys, os
from pathlib import Path
from datetime import datetime, date
from collections import defaultdict

PROJ   = Path(__file__).parent.parent.parent.parent.resolve()
P1_KL  = PROJ / "中间过程" / "klines"
MID_KL = PROJ / "中间过程" / "klines"
OUT_NYAD    = P1_KL / "NYAD_1d.json"
OUT_BREADTH = P1_KL / "breadth_local_history.json"
POOL  = PROJ / "fintech" / "stock_pool.json"

# ─── helpers ─────────────────────────────────────────────────────────────────

def get_pool_tickers():
    """All tickers in the SPX stock pool."""
    with open(POOL) as f:
        pool = json.load(f)
    return {s["code"] for s in pool.get("stocks", [])}


def load_klines_p1():
    """Load close prices from p1/klines/, keyed by date → {ticker: close}."""
    data_by_date = defaultdict(dict)
    count = 0
    for f in P1_KL.glob("*_1d.json"):
        ticker = f.stem.replace("_1d", "")
        if ticker in ("NYAD", "VIX"):
            continue
        try:
            with open(f) as fh:
                d = json.load(fh)
            recs = d
            while isinstance(recs, dict) and "data" in recs:
                recs = recs["data"]
            if not isinstance(recs, list):
                continue
            for bar in recs:
                dt = bar.get("date")
                c  = bar.get("close")
                if dt and c is not None:
                    data_by_date[dt][ticker] = float(c)
                    count += 1
        except Exception:
            pass
    print(f"  [p1] Loaded {count:,} price records across {len(data_by_date)} dates")
    return data_by_date


def load_klines_mid():
    """Load close prices from 中间过程/klines/, keyed by date → {ticker: close}."""
    data_by_date = defaultdict(dict)
    count = 0
    for f in MID_KL.glob("*_1d.json"):
        ticker = f.stem.replace("_1d", "")
        if ticker in ("VIX", "TNX", "DXY"):
            continue
        try:
            with open(f) as fh:
                d = json.load(fh)
            recs = d
            while isinstance(recs, dict) and "data" in recs:
                recs = recs["data"]
            if not isinstance(recs, list):
                continue
            for bar in recs:
                dt = bar.get("date")
                c  = bar.get("close")
                if dt and c is not None:
                    data_by_date[dt][ticker] = float(c)
                    count += 1
        except Exception:
            pass
    print(f"  [mid] Loaded {count:,} price records across {len(data_by_date)} dates")
    return data_by_date


def merge_sources(p1_data, mid_data, pool_tickers):
    """
    For each date, merge data from both sources.
    Prefer p1 data when ticker exists in both.
    Returns: dict[date] = {ticker: close}
    """
    all_dates = sorted(set(p1_data.keys()) | set(mid_data.keys()))
    merged = {}
    for dt in all_dates:
        day = {}
        # mid first (older data), then p1 overwrites (newer/better)
        for t, c in mid_data.get(dt, {}).items():
            if t in pool_tickers:
                day[t] = c
        for t, c in p1_data.get(dt, {}).items():
            if t in pool_tickers:
                day[t] = c  # p1 overwrites mid
        if day:
            merged[dt] = day
    print(f"  [merged] {len(merged)} dates, tickers per date: {len(next(iter(merged.values())))} in earliest")
    return merged


def compute_nyad_and_breadth(merged_data: dict):
    """
    Compute NYAD cumulative and daily breadth metrics.
    Returns: (daily_net, nyad, breadth_records)
    """
    dates = sorted(merged_data.keys())
    daily_net   = {}
    nyad        = {}
    breadth_rec = {}
    prev_closes = {}
    cumulative  = 0

    for dt in dates:
        cur  = merged_data[dt]
        net  = 0
        adv  = 0
        dec  = 0
        unchanged = 0
        closes_above_ema20 = 0

        tickers_with_prev = [t for t in cur if t in prev_closes]
        n = len(tickers_with_prev)

        for t in tickers_with_prev:
            c   = cur[t]
            p   = prev_closes[t]
            if c > p:
                adv  += 1
                net  += 1
            elif c < p:
                dec  += 1
                net  -= 1
            else:
                unchanged += 1

        daily_net[dt] = net
        cumulative    += net
        nyad[dt]      = cumulative

        # Breadth metrics
        n_today = len(cur)
        above50_ema = 0  # need EMA calc, skip for breadth rec

        breadth_rec[dt] = {
            "advancing":    adv,
            "declining":    dec,
            "unchanged":    unchanged,
            "total":        n_today,
            "ad_net":       net,
            "ad_ratio":     adv / n if n > 0 else None,   # A/D ratio
        }

        prev_closes = cur

    return daily_net, nyad, breadth_rec


def load_existing_nyad():
    """Load existing NYAD data to merge with."""
    if OUT_NYAD.exists():
        try:
            with open(OUT_NYAD) as f:
                d = json.load(f)
            return d.get("nyad", {}), d.get("daily_net", {})
        except Exception:
            pass
    return {}, {}


def save_nyad(nyad, daily_net, dates):
    obj = {
        "metadata": {
            "description": "NYSE Advance-Decline Line computed from SPX constituent stocks daily data",
            "source": "local K-line database (p1 + middle_process merged)",
            "date_range": f"{dates[0]} to {dates[-1]}",
            "total_days": len(dates),
            "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "daily_net": daily_net,
        "nyad": nyad,
    }
    with open(OUT_NYAD, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    print(f"  [saved] NYAD_1d.json: {len(nyad)} days, {dates[0]} → {dates[-1]}")


def save_breadth(breadth_rec, dates):
    # Load existing to preserve any extra fields
    existing = {}
    if OUT_BREADTH.exists():
        try:
            with open(OUT_BREADTH) as f:
                existing = json.load(f)
        except Exception:
            pass

    merged = dict(existing)
    merged.update(breadth_rec)

    obj = {
        "metadata": {
            "description": "Market breadth metrics from SPX stocks daily data",
            "source": "local K-line database (p1 + middle_process merged)",
            "date_range": f"{dates[0]} to {dates[-1]}",
            "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "breadth": merged,
    }
    with open(OUT_BREADTH, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    print(f"  [saved] breadth_history.json: {len(merged)} days")


# ─── main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("📊 Backfill NYAD + Market Breadth (2020 → present)")
    print("=" * 60)

    pool_tickers = get_pool_tickers()
    print(f"  Pool size: {len(pool_tickers)} tickers")

    print("\n[1] Loading p1/klines (570 stocks, 2024-05 → present)...")
    p1_data = load_klines_p1()

    print("\n[2] Loading 中间过程/klines (120 stocks, 2020 → 2025-09)...")
    mid_data = load_klines_mid()

    print("\n[3] Merging sources (p1 overwrites mid for overlapping tickers/dates)...")
    merged = merge_sources(p1_data, mid_data, pool_tickers)

    if not merged:
        print("  [ERROR] No merged data! Aborting.")
        return

    all_dates = sorted(merged.keys())
    print(f"  Date range: {all_dates[0]} → {all_dates[-1]} ({len(all_dates)} trading days)")

    print("\n[4] Computing NYAD and breadth metrics...")
    daily_net, nyad, breadth_rec = compute_nyad_and_breadth(merged)

    # Load existing + merge
    old_nyad, old_daily_net = load_existing_nyad()

    # Full merge for nyad
    full_nyad      = dict(old_nyad)
    full_daily_net = dict(old_daily_net)
    full_nyad.update(nyad)
    full_daily_net.update(daily_net)

    # Re-cumulate from sorted dates
    sorted_dates = sorted(full_daily_net.keys())
    cumulative = 0
    for dt in sorted_dates:
        cumulative += full_daily_net[dt]
        full_nyad[dt] = cumulative

    full_dates = sorted(full_nyad.keys())

    print(f"  NYAD: {len(full_nyad)} days total, {full_dates[0]} → {full_dates[-1]}")
    print(f"  Recent NYAD: {full_dates[-1]} = {full_nyad[full_dates[-1]]}")

    print("\n[5] Saving NYAD_1d.json...")
    save_nyad(full_nyad, full_daily_net, full_dates)

    print("\n[6] Saving breadth_history.json...")
    save_breadth(breadth_rec, all_dates)

    print("\nDone. ✅")


if __name__ == "__main__":
    main()
