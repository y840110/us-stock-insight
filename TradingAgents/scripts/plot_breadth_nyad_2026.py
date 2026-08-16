#!/usr/bin/env python3
"""
Plot 2026 YTD:
  1. Above20EMA count (% of pool, normalised 0–100%)
  2. NYAD cumulative (normalised 0–100%)
  3. SPY price (normalised 0–100%)
All three on a single 0–100% y-axis for direct comparison.
"""
import json, sys
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

PROJ   = Path(__file__).parent.parent.resolve()
P1_KL  = PROJ / "中间过程" / "klines"
OUT    = PROJ / "中间过程" / "breadth_nyad_spy_2026.png"

# ── 1. Pool ─────────────────────────────────────────────────────────────
pool = json.load(open(PROJ / "fintech" / "stock_pool.json"))
pool_tickers = {s["code"] for s in pool.get("stocks", [])}
pool_n = len(pool_tickers)
print(f"Pool: {pool_n} stocks")

# ── 2. Stock closes ─────────────────────────────────────────────────────
ticker_closes = {}
for f in P1_KL.glob("*_1d.json"):
    ticker = f.stem.replace("_1d", "")
    if ticker in ("NYAD", "VIX", "^VIX", "SPY") or ticker not in pool_tickers:
        continue
    try:
        with open(f) as fh:
            d = json.load(fh)
        recs = d
        while isinstance(recs, dict) and "data" in recs:
            recs = recs["data"]
        closes = {}
        for bar in recs:
            dt = bar.get("date")
            c = bar.get("close") or bar.get("adj_close")
            if dt and c is not None:
                closes[dt] = float(c)
        if closes:
            ticker_closes[ticker] = closes
    except Exception:
        pass
print(f"Loaded closes: {len(ticker_closes)} stocks")

# ── 3. Above20EMA per date ──────────────────────────────────────────────
K = 2 / 21  # Wilder multiplier for period=20

above20_counts = {}   # {date: count}

for ticker, closes in ticker_closes.items():
    if len(closes) < 25:
        continue
    sorted_dates = sorted(closes.keys())
    price_by_date = {d: closes[d] for d in sorted_dates if d >= "2026-01-01"}

    ema = None
    for i, dt in enumerate(sorted_dates):
        price = closes[dt]
        if i < 19:
            continue
        elif i == 19:
            ema = sum(closes[d] for d in sorted_dates[:20]) / 20
        else:
            ema = price * K + ema * (1 - K)

        if dt >= "2026-01-01" and price > ema:
            above20_counts[dt] = above20_counts.get(dt, 0) + 1

above20_dates = sorted(above20_counts.keys())
print(f"Above20EMA dates: {len(above20_dates)}")

# ── 4. NYAD ─────────────────────────────────────────────────────────────
with open(P1_KL / "NYAD_1d.json") as f:
    d = json.load(f)
nyad_all = d.get("nyad", {})
nyad_2026 = {dt: val for dt, val in nyad_all.items() if dt >= "2026-01-01"}
print(f"NYAD dates: {len(nyad_2026)}")

# ── 5. SPY price ────────────────────────────────────────────────────────
with open(P1_KL / "SPY_1d.json") as f:
    d = json.load(f)
recs = d
while isinstance(recs, dict) and "data" in recs:
    recs = recs["data"]
spy_prices = {}
for bar in recs:
    dt = bar.get("date")
    c = bar.get("close") or bar.get("adj_close")
    if dt and c is not None:
        spy_prices[dt] = float(c)
spy_2026 = {dt: val for dt, val in spy_prices.items() if dt >= "2026-01-01"}
print(f"SPY dates: {len(spy_2026)}")

# ── 6. Common dates & normalise ──────────────────────────────────────────
common = sorted(set(above20_counts) & set(nyad_2026) & set(spy_2026))
print(f"Common dates: {len(common)}")

dates_num = mdates.datestr2num(common)

# Above20EMA % of pool
a20 = [above20_counts[d] / pool_n * 100 for d in common]

# NYAD → 0–100%
nyad_vals = [nyad_2026[d] for d in common]
nyad_min, nyad_max = min(nyad_vals), max(nyad_vals)
nyad_rng = nyad_max - nyad_min or 1
nyad_pct = [(v - nyad_min) / nyad_rng * 100 for v in nyad_vals]

# SPY → 0–100%
spy_vals = [spy_2026[d] for d in common]
spy_min, spy_max = min(spy_vals), max(spy_vals)
spy_rng = spy_max - spy_min or 1
spy_pct = [(v - spy_min) / spy_rng * 100 for v in spy_vals]

print(f"Above20EMA: {min(a20):.1f}% – {max(a20):.1f}%  |  NYAD: {nyad_min:,.0f} – {nyad_max:,.0f}  |  SPY: {spy_min:.2f} – {spy_max:.2f}")

# ── 7. Plot ─────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(16, 7))

c_a20  = "#1565C0"   # deep blue
c_nyad = "#E64A19"   # deep orange
c_spy  = "#2E7D32"   # deep green

# SPY area (background, lightest)
ax.fill_between(dates_num, spy_pct, alpha=0.10, color=c_spy)
ax.plot(dates_num, spy_pct, color=c_spy, linewidth=2.0,
        label=f"SPY Price ({spy_min:.0f}–{spy_max:.0f})", zorder=3)

# NYAD (middle)
ax.fill_between(dates_num, nyad_pct, alpha=0.15, color=c_nyad)
ax.plot(dates_num, nyad_pct, color=c_nyad, linewidth=2.3,
        label=f"NYAD Cumulative ({nyad_min:,.0f}–{nyad_max:,.0f})", zorder=4)

# Above20EMA (foreground, most salient)
ax.fill_between(dates_num, a20, alpha=0.20, color=c_a20)
ax.plot(dates_num, a20, color=c_a20, linewidth=2.5,
        label=f"Above 20EMA ({pool_n} stocks)", zorder=5)

ax.set_ylim(-2, 102)
ax.set_xlim(dates_num[0], dates_num[-1])
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0f}%"))
ax.set_ylabel("Normalised Value (0–100%)", fontsize=12)
ax.set_xlabel("Date (2026)", fontsize=12)

# Reference lines
for pct, col, ls in [(50, "gray", "--"), (80, "green", ":"), (20, "red", ":")]:
    ax.axhline(pct, color=col, linewidth=0.9, linestyle=ls, alpha=0.55)

ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

ax.legend(loc="upper left", fontsize=11, framealpha=0.88, ncol=3)
ax.grid(True, alpha=0.25)
ax.set_axisbelow(True)

last = common[-1]
last_spy = spy_vals[-1]
last_nyad = nyad_vals[-1]
last_a20 = above20_counts[last]
ax.set_title(
    f"Market Breadth + NYAD + SPY — 2026 YTD (Normalised 0–100%)\n"
    f"As of {last}  |  "
    f"SPY={last_spy:.2f}  |  "
    f"Above20EMA={last_a20}/{pool_n} ({a20[-1]:.1f}%)  |  "
    f"NYAD={last_nyad:,.0f} ({nyad_pct[-1]:.1f}%)",
    fontsize=13, fontweight="bold"
)

plt.tight_layout()
plt.savefig(OUT, dpi=150, bbox_inches="tight")
plt.close()
print(f"\nSaved: {OUT}")
