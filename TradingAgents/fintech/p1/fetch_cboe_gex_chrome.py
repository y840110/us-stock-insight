#!/usr/bin/env python3
"""
CBOE SPX 期权链 Gamma 解析
==============================
从 CBOE 官方期权链页面提取 Gamma 数据，计算：

1. Gamma Flip（近似）：Net Gamma 穿过零点的 Strike
2. Net Gamma Exposure：整个链的累计 dealer gamma 方向
3. 最大 Gamma Strike：Gamma 最集中的位置

数据来源：https://www.cboe.com/delayed_quotes/spx/quote_table
（需要 Chrome CDP 访问，显示延迟 15 分钟）

页面格式（每节）：
    Strike
    SPXW 7490.000
    SPXW 7495.000
    ...
    Calls（或 Puts）
    Last
    Net
    Bid
    Ask
    Vol
    IV
    Delta
    Gamma
    Int
    [9行数据 x N个strike]
    [下一个到期日...]

用法：
    python3 fetch_cboe_gex_chrome.py --check
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJ   = Path(__file__).parent.parent.parent
KLINE  = PROJ / "中间过程" / "klines"
MIDDLE = PROJ / "中间过程" / "market_indicators"
MIDDLE.mkdir(parents=True, exist_ok=True)

CHROME_DEBUG_URL = "http://172.25.192.1:19222"


def parse_spx_gamma_page(text: str) -> dict:
    """
    解析 CBOE SPX 期权链页面。
    每strike数据占9行（Last/Net/Bid/Ask/Vol/IV/Delta/Gamma/Int）。
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    result = {
        "expirations": [],
        "spx_price": None,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }

    # ── 找 SPX 当前价（可能在多行） ──
    for i, line in enumerate(lines):
        if "7,501" in line or "7501" in line:
            m = re.search(r'([\d,]+\.?\d{2})', line)
            if m:
                result["spx_price"] = float(m.group(1).replace(",", ""))
                break
        if "Last:" in line or line.strip() == "Last":
            # 在当前行和后续3行找 7500 附近的数字
            for j in range(5):
                if i + j < len(lines):
                    cand = lines[i + j]
                    m = re.search(r'([4-9]\d{3}[,.]\d{2})', cand)
                    if m:
                        result["spx_price"] = float(m.group(1).replace(",", ""))
                        break
            if result["spx_price"]:
                break

    i = 0
    current_exp = None
    all_strikes = []      # 当前到期日的所有strike
    section = None        # "CALLS" or "PUTS"
    data_buffer = []      # 累积的9行数据

    def parse_nine(pieces: list) -> dict:
        """解析9行数据：Last/Net/Bid/Ask/Vol/IV/Delta/Gamma/Int"""
        try:
            return {
                "last":   float(pieces[0].replace(",", "")),
                "net":    float(pieces[1].replace(",", "")),
                "bid":    float(pieces[2].replace(",", "")),
                "ask":    float(pieces[3].replace(",", "")),
                "vol":    int(pieces[4].replace(",", "")),
                "iv":     float(pieces[5].replace(",", "")),
                "delta":  float(pieces[6].replace(",", "")),
                "gamma":  float(pieces[7].replace(",", "")),
                "int":    int(pieces[8].replace(",", "")),
            }
        except (ValueError, IndexError):
            return None

    def process_section(section_type: str, strikes: list, data_list: list) -> list:
        """把数据绑定到strike"""
        if not data_list or not strikes:
            return []
        # data_list 应该有 9*len(strikes) 行
        results = []
        for idx, strike_val in enumerate(strikes):
            start = idx * 9
            end = start + 9
            chunk = data_list[start:end]
            if len(chunk) < 9:
                break
            parsed = parse_nine(chunk)
            if parsed:
                parsed["strike"] = strike_val
                parsed["type"] = section_type
                results.append(parsed)
        return results

    while i < len(lines):
        line = lines[i]

        # 识别到期日
        exp_match = re.search(
            r'(Mon|Tue|Wed|Thu|Fri)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(\d{4})',
            line
        )
        if exp_match:
            # 保存上一个到期日
            if current_exp is not None and all_strikes:
                exp_data = _process_expiration(
                    current_exp, call_data, put_data, result["spx_price"]
                )
                if exp_data:
                    result["expirations"].append(exp_data)

            months = {
                "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
                "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
                "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
            }
            month = months.get(exp_match.group(2), 1)
            day = int(exp_match.group(3))
            year = int(exp_match.group(4))
            current_exp = f"{year:04d}-{month:02d}-{day:02d}"
            all_strikes = []
            call_data = []
            put_data = []
            section = None
            data_buffer = []
            i += 1
            continue

        # 识别 SPXW / SPX strike 行
        strike_match = re.search(r'(SPX|SPXW)\s+([\d,]+\.?\d*)', line)
        if strike_match:
            try:
                strike_val = float(strike_match.group(2).replace(",", ""))
                if 4000 < strike_val < 10000:
                    all_strikes.append(strike_val)
            except ValueError:
                pass
            i += 1
            continue

        # 识别 Calls / Puts 段落
        if line == "Calls":
            section = "CALLS"
            data_buffer = []
            i += 1
            continue
        if line == "Puts":
            # 处理已收集的 Calls 数据
            if section == "CALLS" and data_buffer and all_strikes:
                call_data = process_section("CALLS", all_strikes, data_buffer)

            section = "PUTS"
            data_buffer = []
            i += 1
            continue

        # 解析9行数据（Last/Net/Bid/Ask/Vol/IV/Delta/Gamma/Int）
        if section in ("CALLS", "PUTS"):
            # 检查是否是数字行（数据行）
            # 数据行的特征：有小数点或大数字，不含字母
            if line and not re.search(r'[A-Za-z]', line) and line not in ("Strike",):
                try:
                    # 尝试解析为数字
                    float(line.replace(",", ""))
                    data_buffer.append(line)
                except ValueError:
                    pass

                # 每9行处理一次
                if len(data_buffer) >= 9:
                    if section == "PUTS":
                        put_data = process_section("PUTS", all_strikes, data_buffer)
                        data_buffer = []
                    else:
                        data_buffer = data_buffer[-9:]  # keep last 9
            else:
                # 非数据行（如 "Last", "Net" 等标题）
                i += 1
                continue

        i += 1

    # 处理最后一个到期日
    if current_exp is not None and (call_data or put_data):
        exp_data = _process_expiration(current_exp, call_data, put_data, result["spx_price"])
        if exp_data:
            result["expirations"].append(exp_data)

    return result


def _process_expiration(exp_date: str, call_data: list, put_data: list, spx_price: float) -> Optional[dict]:
    """计算某个到期日的 Gamma 统计"""
    if not call_data and not put_data:
        return None

    # 建立 strike -> data 映射
    calls_by_strike = {c["strike"]: c for c in call_data}
    puts_by_strike  = {p["strike"]: p for p in put_data}

    all_strikes = sorted(set(list(calls_by_strike.keys()) + list(puts_by_strike.keys())))

    net_gamma_by_strike = []
    cumulative = 0.0
    max_gamma_val = 0.0
    max_gamma_strike = None

    for strike in all_strikes:
        c = calls_by_strike.get(strike, {})
        p = puts_by_strike.get(strike, {})

        call_g = c.get("gamma", 0.0)
        call_o = c.get("int", 0)
        put_g  = p.get("gamma", 0.0)
        put_o  = p.get("int", 0)

        net = call_g * call_o - put_g * put_o
        cumulative += net

        total_abs = abs(call_g * call_o) + abs(put_g * put_o)
        if total_abs > max_gamma_val:
            max_gamma_val = total_abs
            max_gamma_strike = strike

        net_gamma_by_strike.append({
            "strike": strike,
            "net_gamma": round(net, 4),
            "cumulative_net_gamma": round(cumulative, 4),
            "call_gamma": call_g,
            "call_oi": call_o,
            "put_gamma": put_g,
            "put_oi": put_o,
        })

    # 找 Gamma Flip（cumulative 穿过零的地方）
    gamma_flip = None
    prev_sign = None
    prev_cum = 0.0
    for item in net_gamma_by_strike:
        curr_sign = 1 if item["cumulative_net_gamma"] > 0 else -1 if item["cumulative_net_gamma"] < 0 else 0
        if prev_sign is not None and curr_sign != prev_sign and curr_sign != 0 and prev_sign != 0:
            gamma_flip = item["strike"]
            break
        prev_sign = curr_sign
        prev_cum = item["cumulative_net_gamma"]

    return {
        "date": exp_date,
        "strikes": net_gamma_by_strike,
        "net_gamma_flip": gamma_flip,
        "max_gamma_strike": max_gamma_strike,
        "total_net_gamma": round(cumulative, 4),
        "spx_price": spx_price,
    }


def fetch_spx_gamma(max_retries: int = 3) -> Optional[dict]:
    """带重试的抓取"""
    for attempt in range(max_retries):
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
                        "https://www.cboe.com/delayed_quotes/spx/quote_table",
                        timeout=60000,
                        wait_until="domcontentloaded"
                    )
                    page.wait_for_timeout(8000)
                    text = page.inner_text("body")
                finally:
                    # 无论成功失败，page 用完即关闭
                    try:
                        page.close()
                    except Exception:
                        pass

                browser.close()

            if len(text) < 1000:
                raise ValueError(f"Page too short: {len(text)}")

            data = parse_spx_gamma_page(text)

            # 如果 SPX price 为空，从本地 SPY 数据获取（SPX ≈ SPY × 10）
            if not data.get("spx_price"):
                spy_files = list((PROJ / "fintech" / "p1" / "klines").glob("SPY_1d.json"))
                if spy_files:
                    import json as _json
                    with open(spy_files[0]) as f:
                        obj = _json.load(f)
                    bars = obj.get("data", [])
                    if bars:
                        spy_close = float(bars[-1]["close"])
                        data["spx_price"] = round(spy_close * 10, 2)
            return data

        except Exception as e:
            print(f"[WARN] Attempt {attempt+1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
            continue

    print("[ERROR] All attempts failed")
    return None


def main(check_mode: bool = False):
    today_str = datetime.now().strftime("%Y-%m-%d")

    # ── 检查本地最新日期，避免重复抓取 ──
    out_file = MIDDLE / "SPX_GAMMA_1d.json"
    if out_file.exists():
        import json as _json
        try:
            existing = _json.loads(out_file.read_text(encoding="utf-8"))
            data_list = existing.get("data", [])
            if data_list and data_list[0].get("date"):
                # 取最近到期日（第一个）的日期
                latest = data_list[0].get("date", "")[:10]
                if latest >= today_str:
                    print(f"[SKIP] SPX Gamma 数据已是今日 ({today_str})，无需重复抓取")
                    print(f"       如需强制更新，请手动删除 {out_file}")
                    # 仍显示状态
                    spx = existing.get("spx_price", 0)
                    flip = data_list[0].get("net_gamma_flip")
                    tot_g = data_list[0].get("total_net_gamma", 0)
                    sign = "🟢" if tot_g > 0 else "🔴" if tot_g < 0 else "🟡"
                    print(f"\n📊 {latest}  SPX: {spx}  {sign} Net={tot_g:.2f}  Flip={flip}")
                    return
        except Exception:
            pass

    print("[INFO] 抓取 CBOE SPX 期权链...")
    data = fetch_spx_gamma()

    if not data or not data.get("expirations"):
        print("[ERROR] 无法获取数据")
        return

    spx = data.get("spx_price")
    print(f"  SPX: {spx}")
    print(f"  到期日数: {len(data['expirations'])}")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "name": "SPX_GAMMA_CHAIN",
            "source": "CBOE SPX Option Chain (via Chrome CDP)",
            "source_url": "https://www.cboe.com/delayed_quotes/spx/quote_table",
            "last_updated": datetime.now().isoformat(),
            "spx_price": spx,
            "data": data["expirations"],
        }, f, indent=2, ensure_ascii=False)

    nearest = data["expirations"][0]
    flip = nearest.get("net_gamma_flip")
    max_s = nearest.get("max_gamma_strike")
    tot_g = nearest.get("total_net_gamma", 0)

    print(f"\n{'='*50}")
    print(f"📊 最近到期日: {nearest['date']}  SPX: {spx}")
    print(f"  Gamma Flip（近似）: {flip}")
    print(f"  Max Gamma Strike: {max_s}")
    print(f"  Total Net Gamma:  {tot_g}")

    print(f"\n{'='*50}")
    print("📋 各到期日 Gamma Summary:")
    for exp in data["expirations"][:6]:
        f = exp.get("net_gamma_flip", "N/A")
        ms = exp.get("max_gamma_strike", "N/A")
        tg = exp.get("total_net_gamma", 0)
        sign = "🟢" if tg > 0 else "🔴" if tg < 0 else "🟡"
        print(f"  {exp['date']}: Flip={f} MaxGamma={ms} Net={tg:.2f} {sign}")

    if flip and spx:
        above = spx > flip
        regime = "POSITIVE_GAMMA" if above else "NEGATIVE_GAMMA"
        emoji = "🟢" if above else "🔴"
        print(f"\n{emoji} Gamma Regime: {regime}")
        print(f"   SPX ({spx}) {'>' if above else '<'} Gamma Flip ({flip})")
    elif tot_g != 0:
        regime = "POSITIVE_GAMMA" if tot_g > 0 else "NEGATIVE_GAMMA"
        print(f"\n🔮 Regime: {regime}")
    else:
        print(f"\n🔮 Regime: NEUTRAL")

    print(f"\n[OK] 保存到 {out_file}")
    return data


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    main(check_mode=args.check)
