#!/usr/bin/env python3
"""
Gamma Regime Proxy 计算引擎
================================
通过市场行为指标代理 GEX 的 Gamma Regime 判断。

核心思路：
    真正的 GEX（Gamma Exposure）需要 SPX 期权链数据（OI + IV by strike），
    这需要付费数据源。本脚本用市场行为指标建立一个实用的 Proxy。

五个代理指标（全部免费）：
───────────────────────────────────────────────────────────────
1. VIX Level（VIX 隐含波动率）
   ─────────────────────────────────
   原理：
     VIX 低（< 15）：波动率平稳 → Dealer 更可能 Positive Gamma
     VIX 高（> 25）：波动率放大 → Dealer 更可能 Negative Gamma
   阈值：
     < 15 → POSITIVE_GAMMA（+1）
     15-20 → NEUTRAL（0）
     20-30 → NEGATIVE_GAMMA（-1）
     > 30 → EXTREME_NEGATIVE（-2）

2. VIX Momentum（VIX 变化率）
   ─────────────────────────────────
   原理：VIX 快速上升 = 恐慌 = Negative Gamma 强化
   阈值（5日变化率）：
     > +20% → EXTREME_NEGATIVE（-2）
     > +10% → NEGATIVE（-1）
     > 0% → SLIGHT_NEGATIVE（0）
     < 0% → SLIGHT_POSITIVE（+1）

3. Put/Call Ratio（PCR）
   ─────────────────────────────────
   原理：
     PCR 低（< 0.7）：市场乐观 → Dealer Buy Dips（Positive Gamma）
     PCR 高（> 1.0）：市场恐慌 → Dealer Sell Dips（Negative Gamma）
   阈值：
     < 0.6 → VERY_POSITIVE（+2）
     0.6-0.8 → POSITIVE（+1）
     0.8-1.0 → NEUTRAL（0）
     > 1.0 → NEGATIVE（-1）

4. SPY vs 20EMA（SPY 相对均线）
   ─────────────────────────────────
   原理：
     SPY > 20EMA：上涨趋势 → Dealer Buy Dips（Positive Gamma）
     SPY < 20EMA：下跌趋势 → Dealer Sell Dips（Negative Gamma）
   阈值（SPY / 20EMA - 1）：
     > +2% → POSITIVE（+1）
     -2% ~ +2% → NEUTRAL（0）
     < -2% → NEGATIVE（-1）

5. SPY RSI（SPY 相对强弱指数）
   ─────────────────────────────────
   原理：
     RSI 40-60：平衡 → Positive Gamma（震荡）
     RSI > 70：极度乐观 → Negative Gamma（可能反转）
     RSI < 30：极度悲观 → Negative Gamma（可能反转）
   阈值：
     40-60 → POSITIVE（+1）
     30-40 或 60-70 → NEUTRAL（0）
     < 30 或 > 70 → NEGATIVE（-1）

───────────────────────────────────────────────────────────────
最终 Gamma Regime 判断：
    综合分 = VIX_level + VIX_momentum + PCR + SPY_ema + RSI
    范围：-7 ~ +7

    >= +3 → POSITIVE_GAMMA（均值回归环境）
    -2 ~ +2 → NEUTRAL（震荡）
    <= -3 → NEGATIVE_GAMMA（趋势/波动放大环境）

用法：
    python3 fetch_gamma_regime_chrome.py         # 抓取并计算
    python3 fetch_gamma_regime_chrome.py --check  # 仅显示状态
"""

import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ──────────────────────────────────────────────────────────────
# 路径配置
# ──────────────────────────────────────────────────────────────

PROJ   = Path(__file__).parent.parent.parent
KLINE  = PROJ / "中间过程" / "klines"
MIDDLE = PROJ / "中间过程" / "market_indicators"
MIDDLE.mkdir(parents=True, exist_ok=True)

CHROME_DEBUG_URL = "http://172.25.192.1:19222"

# ──────────────────────────────────────────────────────────────
# 数据获取
# ──────────────────────────────────────────────────────────────

def get_vix_data() -> dict:
    """读取本地 VIX 数据（Yahoo Finance）"""
    vix_file = KLINE / "VIX_1d.json"
    if not vix_file.exists():
        return {}
    with open(vix_file, encoding="utf-8") as f:
        obj = json.load(f)
    bars = obj.get("data", [])
    return {b["date"]: b for b in bars}


def get_spy_data() -> dict:
    """读取本地 SPY 数据"""
    spy_files = list(KLINE.glob("SPY_1d.json"))
    if not spy_files:
        return {}
    with open(spy_files[0], encoding="utf-8") as f:
        obj = json.load(f)
    bars = obj.get("data", [])
    return {b["date"]: b for b in bars}


def get_pcr_data() -> dict:
    """读取 Put/Call Ratio 数据"""
    pcr_file = MIDDLE / "PUT_CALL_RATIO_1d.json"
    if not pcr_file.exists():
        return {}
    with open(pcr_file, encoding="utf-8") as f:
        obj = json.load(f)
    bars = obj.get("data", [])
    return {b["date"]: b for b in bars}


def fetch_pcr_latest() -> Optional[dict]:
    """通过 Chrome CDP 抓取最新 CBOE PCR"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(CHROME_DEBUG_URL, timeout=30000)
            page = browser.contexts[0].new_page()
            try:
                page.goto(
                    "https://www.cboe.com/markets/us/options/market-statistics/daily",
                    timeout=25000,
                    wait_until="domcontentloaded"
                )
                page.wait_for_timeout(6000)

                text = page.inner_text("body")

                ratios = {}
                for line in text.split("\n"):
                    line = line.strip()
                    if "TOTAL PUT/CALL RATIO" in line.upper():
                        parts = line.split()
                        for i, p in enumerate(parts):
                            if p.replace(".", "").replace(",", "").isdigit():
                                try:
                                    val = float(p.replace(",", ""))
                                    if 0.1 < val < 5.0:
                                        ratios["TOTAL"] = round(val, 2)
                                        break
                                except ValueError:
                                    pass
            finally:
                # 无论成功失败，page 用完即关闭
                try:
                    page.close()
                except Exception:
                    pass

            browser.close()

            if not ratios:
                return None

            return {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "ratio_name": "TOTAL PUT/CALL RATIO",
                "value": ratios.get("TOTAL", 0.7),
            }
    except Exception:
        return None


def calc_rsi(prices: list, period: int = 14) -> float:
    """计算 RSI"""
    if len(prices) < period + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(1, len(prices)):
        delta = prices[i] - prices[i - 1]
        if delta > 0:
            gains.append(delta)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(delta))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_ema(prices: list, period: int) -> list:
    """计算 EMA"""
    if len(prices) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(prices[:period]) / period]
    for price in prices[period:]:
        ema.append(price * k + ema[-1] * (1 - k))
    return ema


# ──────────────────────────────────────────────────────────────
# Gamma Regime 计算
# ──────────────────────────────────────────────────────────────

def compute_gamma_regime(vix_bars: dict, spy_bars: dict, pcr_bars: dict, trade_date: str) -> dict:
    """
    计算 Gamma Regime Proxy

    返回:
        {
            "date": "2026-05-14",
            "regime": "POSITIVE_GAMMA" | "NEUTRAL" | "NEGATIVE_GAMMA",
            "score": int,  # -7 ~ +7
            "signals": {
                "vix_level": {"value": float, "signal": str, "score": int},
                "vix_momentum": {"value": float, "signal": str, "score": int},
                "pcr": {"value": float, "signal": str, "score": int},
                "spy_ema20": {"value": float, "signal": str, "score": int},
                "rsi14": {"value": float, "signal": str, "score": int},
            }
        }
    """

    def get_bar(bars: dict, date: str):
        """获取 <= date 的最近一条"""
        best = None
        for d in sorted(bars.keys()):
            if d <= date:
                best = bars[d]
            else:
                break
        return best

    vix_bar = get_bar(vix_bars, trade_date)
    spy_bar = get_bar(spy_bars, trade_date)
    pcr_bar = get_bar(pcr_bars, trade_date)

    if not vix_bar or not spy_bar:
        return {"error": "Missing data", "date": trade_date}

    vix_now = vix_bar["close"]
    spy_now = spy_bar["close"]

    # ── 1. VIX Level ──
    if vix_now < 15:
        vix_level_score = 1
        vix_level_signal = "POSITIVE (低波动)"
    elif vix_now < 20:
        vix_level_score = 0
        vix_level_signal = "NEUTRAL"
    elif vix_now < 30:
        vix_level_score = -1
        vix_level_signal = "NEGATIVE (高波动)"
    else:
        vix_level_score = -2
        vix_level_signal = "EXTREME_NEGATIVE"

    # ── 2. VIX Momentum（5日变化率） ──
    dates = sorted(vix_bars.keys())
    vix_5d_ago = None
    for d in dates:
        if d < trade_date:
            vix_5d_ago = vix_bars[d]
    vix_mom = 0.0
    if vix_5d_ago and vix_5d_ago["close"] > 0:
        vix_mom = (vix_now - vix_5d_ago["close"]) / vix_5d_ago["close"]

    if vix_mom > 0.20:
        vix_mom_score = -2
        vix_mom_signal = "EXTREME_NEGATIVE (VIX急升)"
    elif vix_mom > 0.10:
        vix_mom_score = -1
        vix_mom_signal = "NEGATIVE"
    elif vix_mom > 0:
        vix_mom_score = 0
        vix_mom_signal = "SLIGHT_NEGATIVE"
    else:
        vix_mom_score = 1
        vix_mom_signal = "POSITIVE (VIX下降)"

    # ── 3. Put/Call Ratio ──
    pcr_val = 0.7  # 默认
    if pcr_bar:
        pcr_val = pcr_bar.get("value", 0.7)

    if pcr_val < 0.6:
        pcr_score = 2
        pcr_signal = "VERY_POSITIVE (极度乐观)"
    elif pcr_val < 0.8:
        pcr_score = 1
        pcr_signal = "POSITIVE"
    elif pcr_val < 1.0:
        pcr_score = 0
        pcr_signal = "NEUTRAL"
    else:
        pcr_score = -1
        pcr_signal = "NEGATIVE (恐慌)"

    # ── 4. SPY vs 20EMA ──
    spy_prices = [b["close"] for b in sorted(spy_bars.values(), key=lambda x: x["date"])]
    ema20 = calc_ema(spy_prices, 20)
    if len(ema20) >= 1:
        spy_ema_diff = (spy_now - ema20[-1]) / ema20[-1]
    else:
        spy_ema_diff = 0.0

    if spy_ema_diff > 0.02:
        spy_ema_score = 1
        spy_ema_signal = "POSITIVE (SPY强势)"
    elif spy_ema_diff < -0.02:
        spy_ema_score = -1
        spy_ema_signal = "NEGATIVE (SPY弱势)"
    else:
        spy_ema_score = 0
        spy_ema_signal = "NEUTRAL"

    # ── 5. SPY RSI(14) ──
    rsi14 = calc_rsi(spy_prices, 14)
    if 40 <= rsi14 <= 60:
        rsi_score = 1
        rsi_signal = "POSITIVE (平衡区)"
    elif (30 <= rsi14 < 40) or (60 < rsi14 <= 70):
        rsi_score = 0
        rsi_signal = "NEUTRAL"
    else:
        rsi_score = -1
        rsi_signal = "NEGATIVE (极端区)"

    # ── 综合 ──
    total_score = vix_level_score + vix_mom_score + pcr_score + spy_ema_score + rsi_score

    if total_score >= 3:
        regime = "POSITIVE_GAMMA"
    elif total_score <= -3:
        regime = "NEGATIVE_GAMMA"
    else:
        regime = "NEUTRAL"

    return {
        "date": trade_date,
        "regime": regime,
        "score": total_score,
        "signals": {
            "vix_level": {
                "value": round(vix_now, 2),
                "signal": vix_level_signal,
                "score": vix_level_score,
            },
            "vix_momentum": {
                "value": round(vix_mom * 100, 2),
                "signal": vix_mom_signal,
                "score": vix_mom_score,
                "unit": "%",
            },
            "pcr": {
                "value": round(pcr_val, 2),
                "signal": pcr_signal,
                "score": pcr_score,
            },
            "spy_ema20": {
                "value": round(spy_ema_diff * 100, 2),
                "signal": spy_ema_signal,
                "score": spy_ema_score,
                "unit": "% vs EMA20",
            },
            "rsi14": {
                "value": round(rsi14, 1),
                "signal": rsi_signal,
                "score": rsi_score,
            },
        },
    }


def save_gamma_regime(records: list):
    """保存 Gamma Regime 历史"""
    out_file = MIDDLE / "GAMMA_REGIME_1d.json"
    obj = {
        "name": "GAMMA_REGIME_PROXY",
        "formula": "VIX_level*w1 + VIX_momentum*w2 + PCR*w3 + SPY_EMA20*w4 + RSI14*w5",
        "description": (
            "Gamma Regime Proxy using market behavioral indicators. "
            "Score range: -7~+7. >=+3=POSITIVE_GAMMA, <=-3=NEGATIVE_GAMMA, else=NEUTRAL."
        ),
        "source": "VIX(Yahoo)+SPY(Yahoo)+PutCallRatio(CBOE via Chrome CDP)",
        "last_updated": datetime.now().isoformat(),
        "data": records,
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    return out_file


def load_existing() -> list:
    """加载已有历史"""
    f = MIDDLE / "GAMMA_REGIME_1d.json"
    if not f.exists():
        return []
    with open(f, encoding="utf-8") as fp:
        obj = json.load(fp)
    return obj.get("data", [])


def update_and_save(trade_date: str) -> dict:
    """增量更新：抓PCR → 计算 → 保存"""
    # ── 检查本地是否已有当日数据，避免重复抓取（Chrome耗资源）──
    existing = load_existing()
    if existing:
        latest_local = max(r["date"] for r in existing)
        if latest_local >= trade_date:
            result = next((r for r in existing if r["date"] == latest_local), None)
            if result:
                print(f"[SKIP] Gamma Regime 已有 {latest_local}，无需更新")
                return result

    # 尝试更新 PCR
    pcr_latest = fetch_pcr_latest()
    if pcr_latest:
        pcr_file = MIDDLE / "PUT_CALL_RATIO_1d.json"
        existing = load_existing()  # 借用一下，实际用专门的loader
        # 合并 PCR
        if pcr_file.exists():
            with open(pcr_file, encoding="utf-8") as f:
                pcr_obj = json.load(f)
            pcr_bars = {r["date"]: r for r in pcr_obj.get("data", [])}
        else:
            pcr_bars = {}
        pcr_bars[pcr_latest["date"]] = pcr_latest
        pcr_records = sorted(pcr_bars.values(), key=lambda x: x["date"])
        with open(pcr_file, "w", encoding="utf-8") as f:
            json.dump({
                "name": "PUT_CALL_RATIO",
                "source": "CBOE (via Chrome CDP)",
                "last_updated": datetime.now().isoformat(),
                "data": pcr_records,
            }, f, indent=2, ensure_ascii=False)

    # 读取数据
    vix_bars = get_vix_data()
    spy_bars = get_spy_data()
    pcr_bars = {}
    pcr_file = MIDDLE / "PUT_CALL_RATIO_1d.json"
    if pcr_file.exists():
        with open(pcr_file, encoding="utf-8") as f:
            pcr_obj = json.load(f)
        pcr_bars = {r["date"]: r for r in pcr_obj.get("data", [])}

    # 计算
    result = compute_gamma_regime(vix_bars, spy_bars, pcr_bars, trade_date)

    # 合并保存
    existing = load_existing()
    all_records = {r["date"]: r for r in existing}
    all_records[result["date"]] = result
    merged = sorted(all_records.values(), key=lambda x: x["date"])
    save_gamma_regime(merged)

    return result


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gamma Regime Proxy")
    parser.add_argument("--check", action="store_true", help="仅显示状态")
    parser.add_argument("--date", default=None, help="指定日期 YYYY-MM-DD")
    args = parser.parse_args()

    trade_date = args.date or datetime.now().strftime("%Y-%m-%d")

    if args.check:
        result = update_and_save(trade_date)
        if "error" in result:
            print(f"[ERROR] {result['error']}")
        else:
            sigs = result["signals"]
            print(f"\n📊 Gamma Regime ({result['date']}):")
            print(f"  Regime: {result['regime']}  Score: {result['score']}")
            print(f"  VIX Level:     {sigs['vix_level']['value']}  → {sigs['vix_level']['signal']} (score={sigs['vix_level']['score']})")
            print(f"  VIX Momentum:   {sigs['vix_momentum']['value']}%  → {sigs['vix_momentum']['signal']} (score={sigs['vix_momentum']['score']})")
            print(f"  Put/Call Ratio:{sigs['pcr']['value']}  → {sigs['pcr']['signal']} (score={sigs['pcr']['score']})")
            print(f"  SPY vs 20EMA:  {sigs['spy_ema20']['value']}%  → {sigs['spy_ema20']['signal']} (score={sigs['spy_ema20']['score']})")
            print(f"  SPY RSI(14):   {sigs['rsi14']['value']}  → {sigs['rsi14']['signal']} (score={sigs['rsi14']['score']})")
            regime_emoji = "🟢" if result["regime"] == "POSITIVE_GAMMA" else ("🔴" if result["regime"] == "NEGATIVE_GAMMA" else "🟡")
            print(f"\n  {regime_emoji} {result['regime']}")
    else:
        result = update_and_save(trade_date)
        if "error" not in result:
            print(f"✅ {result['date']}  {result['regime']}  score={result['score']}")
