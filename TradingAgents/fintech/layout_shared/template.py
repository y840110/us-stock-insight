#!/usr/bin/env python3
"""
layout_shared/template.py — 统一 HTML 报告模板
==============================================
所有 P2/P3/P4 层使用同一套 HTML 模板，保证格式一致。

用法：
    from layout_shared.template import render
    html = render(
        phase="P2",
        date="2026-05-12",
        title="P2 · 择时层",
        subtitle="Regime 判断",
        sections=[
            {"title": "市场状态", "content": "...", "type": "data"},
            {"title": "指标详情", "content": "...", "type": "table"},
        ],
        meta={"regime": "🚀 超强牛市", "score": "8.0/10.0"}
    )
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

# ─── 颜色变量 ────────────────────────────────────────────────────────────────

COLORS = {
    "primary":   "#1a1a2e",
    "secondary": "#16213e",
    "accent":    "#0f3460",
    "highlight": "#e94560",
    "bull":      "#00c853",
    "bear":      "#ff1744",
    "neutral":   "#ffc107",
    "text":     "#e0e0e0",
    "text_dim": "#9e9e9e",
    "bg":        "#0d1117",
    "card":      "#161b22",
    "border":    "#30363d",
    "tag_bull":  "background:#00c85322;color:#00c853;border:1px solid #00c85366",
    "tag_bear":  "background:#ff174422;color:#ff1744;border:1px solid #ff174466",
    "tag_neutral":"background:#ffc10722;color:#ffc107;border:1px solid #ffc10766",
}


# ─── CSS ─────────────────────────────────────────────────────────────────────

BASE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0d1117; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; line-height: 1.6; }
a { color: #58a6ff; text-decoration: none; }
a:hover { text-decoration: underline; }

.report-header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border-bottom: 2px solid #e94560; padding: 24px 32px; }
.phase-tag { display: inline-block; background: #e94560; color: #fff; font-size: 12px; font-weight: 700; padding: 2px 10px; border-radius: 12px; margin-bottom: 8px; letter-spacing: 1px; }
.report-title { font-size: 22px; font-weight: 700; color: #fff; margin-bottom: 4px; }
.report-subtitle { color: #9e9e9e; font-size: 13px; }
.report-meta { margin-top: 12px; display: flex; gap: 16px; flex-wrap: wrap; }
.meta-badge { display: inline-flex; align-items: center; gap: 4px; background: rgba(255,255,255,0.08); padding: 4px 12px; border-radius: 6px; font-size: 12px; }
.meta-badge.bull { background: rgba(0,200,83,0.15); color: #00c853; }
.meta-badge.bear { background: rgba(255,23,68,0.15); color: #ff1744; }
.meta-badge.neutral { background: rgba(255,193,7,0.15); color: #ffc107; }

.report-body { padding: 24px 32px; }

.two-panels-row { display: flex; gap: 0; }
.two-panel { flex: 1; padding: 16px 20px; border-right: 1px solid #30363d; min-width: 0; }
.two-panel:last-child { border-right: none; }
.panel-title { font-weight: 600; font-size: 13px; color: #e0e0e0; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid #30363d; }
.panel-body .data-row { gap: 12px; }
.panel-body .data-label { min-width: 80px; }
.data-divider { border-top: 1px solid #30363d; margin: 8px 0; }
.panel-body .score-number { font-size: 36px; font-weight: 800; }
.panel-body .score-denom { font-size: 14px; color: #9e9e9e; }

.section { background: #161b22; border: 1px solid #30363d; border-radius: 10px; margin-bottom: 20px; overflow: hidden; }
.section-header { background: #1c2128; padding: 12px 20px; border-bottom: 1px solid #30363d; font-weight: 600; font-size: 13px; color: #e0e0e0; display: flex; align-items: center; gap: 8px; }
.section-body { padding: 16px 20px; }

/* 数据行 */
.data-row { display: flex; padding: 6px 0; border-bottom: 1px solid #21262d; gap: 16px; }
.data-row:last-child { border-bottom: none; }
.data-label { color: #9e9e9e; min-width: 120px; flex-shrink: 0; font-size: 13px; }
.data-value { color: #e0e0e0; font-size: 13px; font-weight: 500; }
.data-value.bull { color: #00c853; }
.data-value.bear { color: #ff1744; }
.data-value.neutral { color: #ffc107; }
.data-value.highlight { color: #58a6ff; }

/* 表格 */
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th { background: #1c2128; color: #9e9e9e; text-align: left; padding: 8px 12px; border-bottom: 1px solid #30363d; font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
.data-table td { padding: 8px 12px; border-bottom: 1px solid #21262d; }
.data-table tr:last-child td { border-bottom: none; }
.data-table tr:hover td { background: #1c2128; }
.data-table .num { text-align: right; font-variant-numeric: tabular-nums; }
.data-table .positive { color: #00c853; }
.data-table .negative { color: #ff1744; }

/* 标签 */
.tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; margin-left: 4px; }
.tag-bull { background: rgba(0,200,83,0.15); color: #00c853; }
.tag-bear { background: rgba(255,23,68,0.15); color: #ff1744; }
.tag-neutral { background: rgba(255,193,7,0.15); color: #ffc107; }
.tag-hot { background: rgba(233,69,96,0.15); color: #e94560; }

/* 分隔 */
.divider { border: none; border-top: 1px solid #30363d; margin: 16px 0; }

/* 推荐表格 */
.rec-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.rec-table th { background: #1c2128; color: #9e9e9e; text-align: left; padding: 10px 14px; border-bottom: 2px solid #e94560; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
.rec-table td { padding: 10px 14px; border-bottom: 1px solid #21262d; vertical-align: middle; }
.rec-table tr:last-child td { border-bottom: none; }
.rec-table tr:hover td { background: #1c2128; }
.rec-table .ticker { font-weight: 700; color: #58a6ff; font-size: 14px; }
.rec-table .num { text-align: right; font-variant-numeric: tabular-nums; }
.rec-table .positive { color: #00c853; }
.rec-table .negative { color: #ff1744; }
.rec-table .tier-l1 { background: rgba(0,200,83,0.15); color: #00c853; font-weight: 700; }
.rec-table .tier-l2 { background: rgba(88,166,255,0.12); color: #58a6ff; }
.rec-table .tier-l3 { background: rgba(255,193,7,0.12); color: #ffc107; }

/* Footer */
.report-footer { padding: 16px 32px; border-top: 1px solid #30363d; color: #9e9e9e; font-size: 11px; display: flex; justify-content: space-between; align-items: center; }

/* 2列布局 */
.cols-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
@media (max-width: 800px) { .cols-2 { grid-template-columns: 1fr; } }

/* 趋势健康度评分 */
.score-section { padding: 20px; text-align: center; }
.score-main { display: flex; align-items: baseline; justify-content: center; gap: 6px; margin-bottom: 12px; }
.score-number { font-size: 56px; font-weight: 800; line-height: 1; }
.score-denom { font-size: 22px; color: #9e9e9e; }
.score-label { font-size: 14px; color: #9e9e9e; margin-left: 8px; margin-top: 2px; }
.score-bar-wrap { background: #21262d; border-radius: 8px; height: 8px; overflow: hidden; }
.score-bar { height: 100%; border-radius: 8px; transition: width 0.5s ease; }
.score-section .data-table { margin-top: 12px; }
.score-section .data-table td:first-child { font-weight: 600; }
.score-section .data-table .num { font-size: 14px; font-weight: 600; }
"""


# ─── 渲染函数 ──────────────────────────────────────────────────────────────

def render(
    phase: str,
    date: str,
    title: str,
    subtitle: str = "",
    sections: list[dict] | None = None,
    meta: dict | None = None,
    summary: str = "",
    rec_table: dict | None = None,
) -> str:
    """
    生成统一的 HTML 报告。

    参数：
        phase:    "P2" / "P3" / "P4"
        date:     "2026-05-12"
        title:    报告主标题
        subtitle: 副标题
        sections: [{"title": "", "type": "data"|"html"|"blank", "rows": [...], "html": ""}, ...]
        meta:     {"key": "value"} 显示为 badge
        summary:  摘要文字
        rec_table: {
            "headers": [...],
            "rows": [[...], ...],
            "tier_col": col_index (optional, 为 L1/L2/L3 添加 tier class)
        }
    """
    phase_num = phase.upper().replace("P", "")
    badge_class = "bull" if meta and any(
        v in str(meta.get("regime", "")) for v in ["牛市", "超强", "强势"]
    ) else "neutral" if meta and "震荡" in str(meta.get("regime", "") or "") else "bear"

    meta_html = ""
    if meta:
        for k, v in meta.items():
            cls = "bull" if isinstance(v, (int, float)) and v > 5 else \
                  "bear" if isinstance(v, (int, float)) and v < 3 else \
                  badge_class if "regime" in k.lower() or "score" in k.lower() else "neutral"
            meta_html += f'<span class="meta-badge {cls}"><strong>{k}:</strong> {v}</span>\n'

    sections_html = ""
    if sections:
        for sec in sections:
            sec_title = sec.get("title", "")
            sec_type = sec.get("type", "blank")

            if sec_type == "blank":
                body = sec.get("html", "")

            elif sec_type == "data":
                rows_html = ""
                for row in sec.get("rows", []):
                    label = row.get("label", "")
                    value = row.get("value", "")
                    cls   = row.get("class", "")
                    if isinstance(value, (int, float)):
                        if value > 0: cls = (cls + " positive").strip()
                        elif value < 0: cls = (cls + " negative").strip()
                    value_str = f'<span class="data-value {cls}">{value}</span>' if cls else f'<span class="data-value">{value}</span>'
                    rows_html += f'<div class="data-row"><span class="data-label">{label}</span>{value_str}</div>\n'
                body = f'<div class="section-body">{rows_html}</div>'

            elif sec_type == "score":
                score_val = sec.get("score_value", 0)
                score_max = sec.get("score_max", 100)
                score_pct = score_val / score_max * 100
                subtitle  = sec.get("subtitle", "")
                # 颜色
                if score_pct >= 80:  bar_color = "#00c853"
                elif score_pct >= 65: bar_color = "#64dd17"
                elif score_pct >= 50: bar_color = "#ffc107"
                elif score_pct >= 35: bar_color = "#ff6d00"
                else:                  bar_color = "#d50000"
                body = f"""
                <div class="score-section">
                  <div class="score-main">
                    <div class="score-number" style="color:{bar_color}">{score_val:.0f}</div>
                    <div class="score-denom">/ {score_max}</div>
                    <div class="score-label">{subtitle}</div>
                  </div>
                  <div class="score-bar-wrap">
                    <div class="score-bar" style="width:{score_pct:.1f}%;background:{bar_color}"></div>
                  </div>
                </div>
                <div class="section-body">
                <table class="data-table" style="margin-top:12px">
                <thead><tr><th>因子</th><th>得分</th><th>状态</th><th>原始值</th></tr></thead><tbody>
                """
                for row in sec.get("rows", []):
                    label  = row.get("label", "")
                    val    = row.get("value", "")
                    pct    = row.get("pct", 0)
                    detail = row.get("detail", "")
                    raw    = row.get("raw", "")
                    cls    = row.get("class", "")
                    row_cls = {"bull": "positive", "bear": "negative"}.get(cls, "")
                    pct_color = "#00c853" if pct >= 70 else ("#ff6d00" if pct < 40 else "#ffc107")
                    body += f"""<tr>
                        <td style="font-weight:600">{label}</td>
                        <td class="num {row_cls}">{val}</td>
                        <td><span style="color:{pct_color};font-size:12px">{detail}</span></td>
                        <td style="color:#9e9e9e;font-size:12px">{raw}</td>
                    </tr>"""
                body += "</tbody></table></div>"

            elif sec_type == "table":
                headers = sec.get("headers", [])
                rows_data = sec.get("rows", [])
                th_html = "".join(f"<th>{h}</th>" for h in headers)
                trs_html = ""
                for row_cells in rows_data:
                    tds = "".join(f"<td>{c}</td>" for c in row_cells)
                    trs_html += f"<tr>{tds}</tr>\n"
                body = (
                    '<div class="section-body">\n' +
                    '<table class="data-table">\n' +
                    f'<thead><tr>{th_html}</tr></thead>\n' +
                    '<tbody>\n' + trs_html + '</tbody>\n' +
                    '</table>\n</div>\n'
                )

            elif sec_type == "two_panel":
                # 两栏并列：left + right sub-sections
                def _render_sub(panel_sec):
                    ptitle = panel_sec.get("title", "")
                    ptype  = panel_sec.get("type", "blank")
                    pbody  = ""
                    if ptype == "score":
                        sv = panel_sec.get("score_value", 0)
                        sm = panel_sec.get("score_max", 100)
                        pct = sv / sm * 100
                        bar_color = "#00c853" if pct>=80 else "#64dd17" if pct>=65 else "#ffc107" if pct>=50 else "#ff6d00" if pct>=35 else "#d50000"
                        pbody = f"<div class='score-number' style='color:{bar_color}'>{sv:.0f}</div><div class='score-denom'>/ {sm}</div>"
                    elif ptype == "data":
                        for row in panel_sec.get("rows", []):
                            lc = row.get("class", "")
                            if lc == "divider":
                                pbody += "<div class='data-divider'></div>\n"
                                continue
                            lv = row.get("value", "")
                            pbody += f"<div class='data-row'><span class='data-label'>{row.get('label','')}</span><span class='data-value {lc}'>{lv}</span></div>\n"
                    return f"<div class='two-panel'><div class='panel-title'>{ptitle}</div><div class='panel-body'>{pbody}</div></div>"

                left_html  = _render_sub(sec.get("left", {}))
                right_html = _render_sub(sec.get("right", {}))
                body = f"<div class='two-panels-row'>{left_html}{right_html}</div>"

            else:
                body = sec.get("html", "")

            if sec_type == "two_panel":
                # two_panel: body already contains the full <div class='two-panels-row'>...</div>
                sections_html += body
            else:
                sections_html += f"""
<div class="section">
  <div class="section-header">{sec_title}</div>
  {body}
</div>\n"""

    rec_html = ""
    if rec_table:
        headers = rec_table.get("headers", [])
        rows_data = rec_table.get("rows", [])
        tier_col = rec_table.get("tier_col", -1)
        th_html = "".join(f"<th>{h}</th>" for h in headers)
        trs = ""
        for row in rows_data:
            tier = str(row[tier_col]) if tier_col >= 0 else ""
            tier_cls = f"tier-{tier.lower().replace(' ','')}" if tier in ("L1","L2","L3","L4") else ""
            if tier in ("L1","L2","L3","L4"):
                cells = "".join(
                    f'<td class="{tier_cls}">{c}</td>' if i == tier_col else f"<td>{c}</td>"
                    for i, c in enumerate(row)
                )
            else:
                cells = "".join(f"<td>{c}</td>" for c in row)
            trs += f"<tr>{cells}</tr>\n"
        rec_html = f"""
<div class="section">
  <div class="section-header">📋 推荐候选池</div>
  <div class="section-body" style="overflow-x:auto">
  <table class="rec-table"><thead><tr>{th_html}</tr></thead>
  <tbody>{trs}</tbody></table></div>
</div>\n"""

    summary_html = f'<div class="section"><div class="section-body"><strong style="color:#58a6ff">📌 摘要：</strong>{summary}</div></div>\n' if summary else ""

    dt = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now()
    dt_str = dt.strftime("%Y-%m-%d %H:%M")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{phase} · {title} — {date}</title>
<style>{BASE_CSS}</style>
</head>
<body>
<div class="report-header">
  <div class="phase-tag">{phase}</div>
  <div class="report-title">{title}</div>
  <div class="report-subtitle">{subtitle}</div>
  <div class="report-meta">{meta_html}</div>
</div>
<div class="report-body">
  {summary_html}
  {sections_html}
  {rec_html}
</div>
<div class="report-footer">
  <span>生成时间：{dt_str} · FinTech Pipeline {phase}</span>
  <span>美股投资洞察分析</span>
</div>
</body>
</html>"""


def save_report(
    phase: str,
    date: str,
    title: str,
    subtitle: str = "",
    sections: list[dict] | None = None,
    meta: dict | None = None,
    summary: str = "",
    rec_table: dict | None = None,
    output_dir: Path | str | None = None,
) -> Path:
    """
    渲染 HTML 并保存到文件。
    文件名格式：p2_20260512.html
    """
    date_str = date.replace("-", "")  # "2026-05-12" → "20260512"
    filename = f"{phase.lower()}_{date_str}.html"

    if output_dir:
        out_dir = Path(output_dir)
    else:
        out_dir = Path(__file__).parent.parent / phase.lower() / "layout"

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename

    html = render(
        phase=phase, date=date, title=title, subtitle=subtitle,
        sections=sections, meta=meta, summary=summary, rec_table=rec_table,
    )
    out_path.write_text(html, encoding="utf-8")
    return out_path
