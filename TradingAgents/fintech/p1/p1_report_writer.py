#!/usr/bin/env python3
"""
P1 层 HTML 报告生成器
=====================
每次 fetch_us_stocks_cdp.py 结束时调用，生成三块报告：
  第一块：基础行情数据（更新的股票列表、K线级别、日期）
  第二块：计算指标（广度、健康回踩、危险变盘、趋势健康度）
  第三块：网络下载数据（finviz 原始广度数据）
"""
from __future__ import annotations

import json
from datetime import datetime, date
from pathlib import Path

PROJ_DIR   = Path(__file__).parent.parent.parent
P1_DIR    = Path(__file__).parent
STATE_DIR = P1_DIR / "state"
KLINES_DIR = P1_DIR.parent.parent / "中间过程" / "klines"
LAYOUT_DIR = P1_DIR / "layout"
LAYOUT_DIR.mkdir(parents=True, exist_ok=True)


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.load(open(path))
    except Exception:
        return {}


def list_kline_files() -> list[dict]:
    files = []
    if not KLINES_DIR.exists():
        return files
    for f in sorted(KLINES_DIR.glob("*_1d.json")):
        code = f.stem.replace("_1d", "")
        try:
            d = json.load(open(f))
            bars = d.get("data", []) if isinstance(d, dict) else d
            if bars:
                files.append({
                    "code":       code,
                    "count":      len(bars),
                    "start":      bars[0]["date"],
                    "end":        bars[-1]["date"],
                    "last_close": bars[-1]["close"],
                })
        except Exception:
            pass
    return files


# ── HTML 小部件 ──────────────────────────────────────────────────────────────

def _css() -> str:
    return """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0d1117; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 14px; line-height: 1.6; }
.report-header { background: linear-gradient(135deg,#1a1a2e,#16213e); border-bottom: 2px solid #e94560; padding: 24px 32px; }
.phase-tag { display:inline-block; background:#e94560; color:#fff; font-size:12px; font-weight:700; padding:2px 10px; border-radius:12px; margin-bottom:8px; letter-spacing:1px; }
.report-title { font-size:22px; font-weight:700; color:#fff; margin-bottom:4px; }
.report-subtitle { color:#9e9e9e; font-size:13px; }
.report-body { padding: 24px 32px; }
.section { background:#161b22; border:1px solid #30363d; border-radius:10px; margin-bottom:20px; overflow:hidden; }
.section-header { background:#1c2128; padding:12px 20px; border-bottom:1px solid #30363d; font-weight:600; font-size:13px; color:#e0e0e0; }
.section-body { padding:16px 20px; }
.data-row { display:flex; padding:6px 0; border-bottom:1px solid #21262d; gap:16px; }
.data-row:last-child { border-bottom:none; }
.data-label { color:#9e9e9e; min-width:120px; flex-shrink:0; font-size:13px; }
.data-value { color:#e0e0e0; font-size:13px; }
table { width:100%; border-collapse:collapse; }
th { background:#1c2128; color:#9e9e9e; text-align:left; padding:6px 8px; font-size:11px; text-transform:uppercase; font-weight:600; }
td { padding:6px 8px; border-bottom:1px solid #21262d; }
tr:last-child td { border-bottom:none; }
tr:hover td { background:#1c2128; }
"""


def state_color(pct: float) -> str:
    if pct >= 80:   return "#00c853"
    if pct >= 65:   return "#64dd17"
    if pct >= 50:   return "#ffc107"
    if pct >= 35:   return "#ff6d00"
    return "#d50000"


def icon_for(sig: str) -> str:
    return {
        "SAFE": "✅", "WATCH": "👁", "WARNING": "⚠️", "SEVERE": "🚨",
        "HEALTHY": "✅", "NO_PULLBACK": "❌",
        "Strong Trend": "🚀", "Healthy Correction": "🐂",
        "High Vol Divergence": "⚠️", "Trend Deterioration": "🐻",
        "High Probability Shift": "🚨",
    }.get(sig, "⬜")


def mini_bar(pct: float, color: str = "") -> str:
    c = color or state_color(pct)
    return (f'<div style="background:#21262d;border-radius:4px;height:6px;width:100px">'
            f'<div style="background:{c};height:6px;border-radius:4px;width:{min(100,pct):.0f}%"></div></div>')


def badge(val: str, cls: str = "dim") -> str:
    bg   = {"bull": "#00c85322", "bear": "#ff174422", "neutral": "#ffc10722",
            "accent": "#58a6ff22", "dim": "#9e9e9e22"}.get(cls, "#9e9e9e22")
    fore = {"bull": "#00c853",   "bear": "#ff1744",   "neutral": "#ffc107",
            "accent": "#58a6ff",   "dim": "#9e9e9e"}.get(cls, "#9e9e9e")
    return f'<span style="background:{bg};color:{fore};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600">{val}</span>'


def section(title: str, body: str) -> str:
    return f'<div class="section"><div class="section-header">{title}</div><div class="section-body">{body}</div></div>'


def factor_table(factors: dict) -> str:
    rows = ""
    for fname, f in factors.items():
        pct   = f.get("pct", 0)
        score = f.get("score", 0)
        max_s = f.get("max", 100)
        label = f.get("label", "")
        raw   = str(f.get("raw_value") or f.get("raw") or "")
        c     = state_color(pct)
        rows += f"""<tr>
  <td style="font-weight:600;padding:6px 8px">{fname}</td>
  <td style="color:{c};font-weight:700;padding:6px 4px;white-space:nowrap">{score}/{max_s}</td>
  <td style="padding:6px 8px">{mini_bar(pct, c)}</td>
  <td style="color:#9e9e9e;font-size:12px">{label}</td>
  <td style="color:#9e9e9e;font-size:12px">{raw}</td>
</tr>"""
    return (f'<table><thead><tr><th style="padding:6px 8px">因子</th><th style="padding:6px 4px">得分</th>'
            f'<th style="padding:6px 8px">进度</th><th style="padding:6px 8px">状态</th>'
            f'<th style="padding:6px 8px">原始值</th></tr></thead><tbody>{rows}</tbody></table>')


# ── 主函数 ───────────────────────────────────────────────────────────────────

def build_report() -> str:
    today = str(date.today())
    now   = datetime.now().strftime("%H:%M:%S")

    # 读取数据
    bv     = read_json(KLINES_DIR / "sp500_breadth_finviz.json")
    th     = read_json(STATE_DIR / "trend_health.json")
    pb     = read_json(STATE_DIR / "pullback_state.json")
    ds     = read_json(STATE_DIR / "dangerous_shift_state.json")
    klines = list_kline_files()

    # ── 第一块：行情文件 ──────────────────────────────────────────────
    kline_rows = ""
    if klines:
        for f in klines[:60]:
            kline_rows += f"""<tr>
  <td style="font-weight:600">{f['code']}</td>
  <td style="color:#9e9e9e">{f['count']}</td>
  <td style="font-size:12px">{f['start']}</td>
  <td style="font-size:12px">{f['end']}</td>
  <td style="text-align:right">${f['last_close']:.2f}</td>
</tr>"""
    else:
        kline_rows = "<tr><td colspan=5 style='color:#9e9e9e;padding:12px'>无数据</td></tr>"

    sec1 = section("📡 行情文件", f"""
<p style="color:#9e9e9e;font-size:12px;margin-bottom:12px">
  共 {len(klines)} 只股票 | 最后更新 {now}
</p>
<table>
  <thead><tr>
    <th>代码</th><th>K线数</th><th>起始日</th><th>截止日</th><th style="text-align:right">最新价</th>
  </tr></thead>
  <tbody>{kline_rows}</tbody>
</table>""")

    # ── 第二块：计算指标 ──────────────────────────────────────────────
    th_score  = th.get("total_score") or 0
    th_pct    = th_score
    th_icon   = th.get("state_icon", "")
    th_label  = th.get("state", "N/A")
    th_cons   = th.get("consensus", "")
    th_color  = state_color(th_pct)
    th_facts  = th.get("factors", {})

    sec2_th = section(f"{th_icon} 趋势健康度评分（{th_score:.0f}/100）", f"""
<div style="text-align:center;padding:16px 0">
  <div style="font-size:52px;font-weight:800;color:{th_color};line-height:1">{th_score:.0f}</div>
  <div style="color:#9e9e9e;font-size:13px;margin-top:4px">{th_label} | {th_cons}</div>
</div>
{factor_table(th_facts)}""")

    ds_sig  = ds.get("signal", "N/A")
    ds_cnt  = ds.get("danger_count", 0)
    ds_icon = icon_for(ds_sig)
    sec2_ds = section(f"{ds_icon} 危险变盘检测", f"""
<p style="margin-bottom:10px">{badge(ds_sig, 'bear' if ds_sig in ('WARNING','SEVERE') else 'bull')} 
<span style="color:#9e9e9e">{ds_cnt}/5 个条件触发</span></p>""")
    for cname, c in ds.get("checks", {}).items():
        ok = c.get("ok", False)
        reason = c.get("reason", "")
        cls = "bull" if not ok else "bear"
        sec2_ds += (f'<div class="data-row"><span class="data-label">'
                    f'{"✅" if not ok else "🚨"} {cname}</span>'
                    f'<span class="data-value" style="color:#{"00c853" if not ok else "ff1744"}">{reason}</span></div>')

    pb_sig  = pb.get("signal", "N/A")
    pb_icon = icon_for(pb_sig)
    sec2_pb = section(f"{pb_icon} 健康回踩检测", f"""
<p style="margin-bottom:10px">{badge(pb_sig, 'bear' if pb_sig == 'WARNING' else 'bull')}</p>""")
    for cname, c in pb.get("checks", {}).items():
        ok = c.get("ok", False)
        sec2_pb += (f'<div class="data-row"><span class="data-label">'
                    f'{"✅" if ok else "❌"} {cname}</span>'
                    f'<span class="data-value">{c.get("reason", "")}</span></div>')

    sec2 = sec2_th + sec2_ds + sec2_pb

    # ── 第三块：网络数据 ──────────────────────────────────────────────
    bv_50   = bv.get("above_sma50")
    bv_200  = bv.get("above_sma200")
    bv_adv  = bv.get("advancing_pct")
    bv_dec  = bv.get("declining_pct")
    bv_nh   = bv.get("new_high_pct")
    bv_nl   = bv.get("new_low_pct")
    bv_nh_c = bv.get("new_high_cnt")
    bv_nl_c = bv.get("new_low_cnt")

    def card(label, value, color="#00c853"):
        return (f'<div style="background:#1c2128;border-radius:8px;padding:14px">'
                f'<div style="color:#9e9e9e;font-size:11px;margin-bottom:6px">{label}</div>'
                f'<div style="font-weight:700;color:{color}">{value}</div></div>')

    sec3 = section("🌐 网络数据（finviz.com）", f"""
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px">
  {card('数据日期', bv.get('date', 'N/A'), '#58a6ff')}
  {card('SMA50 上方', f'{bv_50*100:.1f}%' if bv_50 else 'N/A')}
  {card('SMA200 上方', f'{bv_200*100:.1f}%' if bv_200 else 'N/A')}
  {card('上涨股票', f'{bv_adv*100:.1f}%' if bv_adv else 'N/A', '#00c853')}
  {card('下跌股票', f'{bv_dec*100:.1f}%' if bv_dec else 'N/A', '#ff1744')}
  {card('52W 新高', f'{bv_nh*100:.1f}%' if bv_nh else 'N/A', '#00c853')}
  {card('52W 新低', f'{bv_nl*100:.1f}%' if bv_nl else 'N/A', '#ff1744')}
</div>
<div style="padding:10px;background:#1c2128;border-radius:8px;font-size:12px;color:#9e9e9e">
  数据来源：finviz.com · Chrome CDP 抓取 · 每个交易日自动更新
</div>""")

    # ── 组合 ─────────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>P1 数据层报告 {today}</title>
<style>{_css()}</style>
</head>
<body>
<div class="report-header">
  <div class="phase-tag">P1 · 数据层</div>
  <div class="report-title">P1 市场数据报告</div>
  <div class="report-subtitle">更新于 {today} {now} · 自动生成</div>
</div>
<div class="report-body">
  {sec1}
  {sec2}
  {sec3}
</div>
</body>
</html>"""

    out_path = LAYOUT_DIR / f"p1_{today.replace('-','')}.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    latest = LAYOUT_DIR / "p1_latest.html"
    with open(latest, "w", encoding="utf-8") as f:
        f.write(html)
    return str(out_path)


if __name__ == "__main__":
    out = build_report()
    print(f"[P1] HTML 报告已保存: {out}")
