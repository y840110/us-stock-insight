#!/usr/bin/env python3
"""Patch _build_strategy_card - writes to temp file to validate syntax first."""
import ast, re, sys, json
from pathlib import Path

TARGET = Path(__file__).parent.parent / "fintech/p2/p2_layout.py"
TEMP   = Path("/tmp/_build_strategy_card_new.py")

def esc(s):
    """JSON-encode a string - safely embeds any text in Python string."""
    return json.dumps(s)[1:-1]  # strip surrounding quotes

def q(s):
    """Wrap text in double quotes, safely."""
    return '"' + esc(s) + '"'

# ── Build the function line by line using explicit string construction ──────────
lines = []

def L(s):
    lines.append(s)

L(r"""def _build_strategy_card(label, emoji, result, color, bg, v=None):""")
L(r"""    regime    = result.get("market_regime", "N/A")""")
L(r"""    reg_score = result.get("regime_score", 0)""")
L(r"""    timing    = result.get("timing_state", "N/A")""")
L(r"""    tim_score = result.get("timing_score", 0)""")
L(r"""    risk      = result.get("risk_score", 5)""")
L(r"""    exposure  = result.get("target_exposure", 0)""")
L(r"""    confidence= result.get("confidence", 0.5)""")
L(r"""    signals   = result.get("signals", [])""")
L(r"""    interp    = result.get("interpretation", "")""")
L(r"""""")
L(r"""    r_color, r_bg = _regime_color(regime)""")
L(r"""    e_color = _exp_color(exposure)""")
L(r"""    c_color = _conf_color(confidence)""")
L(r"""    risk_c  = "#ff1744" if risk >= 7 else ("#ffc107" if risk >= 4 else "#00c853")""")
L(r"""""")
L(r"""    # ── 策略参数详情 ──""")
L(r"""    params_html = """"")
L(r"""    if v is not None:""")
L(r"""        params_html = _build_strategy_params(label, emoji, v, result)""")
L(r"""""")
L(r"""    extra_parts = []""")
L(r"""""")
L(r"""    # ══ Strategy C: ML三模型独立结论 + 综合评判逻辑 ══════════════════════════════""")
L(r"""    if result.get("prob_gbr") is not None:""")
L(r"""        gbr_p = result.get("prob_gbr", 0)""")
L(r"""        nn_p  = result.get("prob_nn", 0)""")
L(r"""        lr_p  = result.get("prob_lr", 0)""")
L(r"""        ens_p = result.get("prob_ensemble", 0)""")
L(r"""        pct   = result.get("prob_percentile", 0)""")
L(r"""""")
L(r"""        def _c(v):""")
L(r"""            return "#00e676" if v >= 0.5 else ("#ff9800" if v >= 0.3 else "#d63939")""")
L(r"""        def _b(v, col):""")
L(r"""            w = min(v * 100, 100)""")
L(r"""            return ("<div style='height:4px;background:#21262d;border-radius:2px;overflow:hidden;margin-bottom:5px'>" """)
L(r"""                  "<div style='height:100%;width:{:.0f}%;background:{};border-radius:2px'></div></div>").format(w, col)""")
L(r"""""")
L(r"""        gbr_i = "强势做多" if gbr_p >= 0.5 else ("谨慎做多" if gbr_p >= 0.3 else "离场/做空")""")
L(r"""        nn_i  = "强势做多" if nn_p  >= 0.5 else ("谨慎做多" if nn_p  >= 0.3 else "离场/做空")""")
L(r"""        lr_i  = "强势做多" if lr_p  >= 0.5 else ("谨慎做多" if lr_p  >= 0.3 else "离场/做空")""")
L(r"""        ens_i = "一致做多" if ens_p >= 0.5 else ("谨慎做多" if ens_p >= 0.3 else "离场/做空")""")
L(r"""""")
# Strategy C HTML - use q() for strings with HTML double quotes
c_chunks = [
    "<div style='margin-bottom:10px'>",
    "<div style='font-size:.72rem;font-weight:700;color:#26c6da;margin-bottom:8px'>🔍 三模型独立判断 + 综合逻辑</div>",
    "<div style='background:#1a1f27;border-radius:8px;padding:10px;margin-bottom:6px'>",
    "<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px'>",
    "<div style='font-size:.78rem;font-weight:700;color:#26c6da'>GBR 梯度提升树</div>",
    "<div style='display:flex;align-items:center;gap:8px'>",
    "<div style='font-size:.68rem;color:#9e9e9e'>" + gbr_i + "</div>",
    "<div style='font-size:1rem;font-weight:800;color:" + _c.__code__.co_consts[2] + ">{:.1%}</div></div></div>".replace(_c.__code__.co_consts[2], _c.__code__.co_consts[2]),
]

# Rebuild more carefully
_c_code = "(lambda v: '#00e676' if v >= 0.5 else ('#ff9800' if v >= 0.3 else '#d63939'))"
exec(_c_code)

L("        extra_parts.append(")
L("            " + q("<div style='margin-bottom:10px'>"))
L("            " + q("<div style='font-size:.72rem;font-weight:700;color:#26c6da;margin-bottom:8px'>🔍 三模型独立判断 + 综合逻辑</div>"))
L("            " + q("<div style='background:#1a1f27;border-radius:8px;padding:10px;margin-bottom:6px'>"))
L("            " + q("<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px'>"))
L("            " + q("<div style='font-size:.78rem;font-weight:700;color:#26c6da'>GBR 梯度提升树</div>"))
L("            " + q("<div style='display:flex;align-items:center;gap:8px'>"))
L("            " + q("<div style='font-size:.68rem;color:#9e9e9e'>") + " + gbr_i + " + q("</div>"))
L("            " + q("<div style='font-size:1rem;font-weight:800;color:") + " + _c(gbr_p) + " + " + q(">{:.1%}</div></div></div>").format(gbr_p))
L("            + _b(gbr_p, _c(gbr_p)) +")
L("            " + q("<div style='font-size:.65rem;color:#9e9e9e'>趋势跟踪型 | &gt;50%=强势做多 | 30-50%=谨慎 | &lt;30%=离场</div></div>"))
L("            " + q("<div style='background:#1a1f27;border-radius:8px;padding:10px;margin-bottom:6px'>"))
L("            " + q("<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px'>"))
L("            " + q("<div style='font-size:.78rem;font-weight:700;color:#26c6da'>NN 神经网络</div>"))
L("            " + q("<div style='display:flex;align-items:center;gap:8px'>"))
L("            " + q("<div style='font-size:.68rem;color:#9e9e9e'>") + " + nn_i + " + q("</div>"))
L("            " + q("<div style='font-size:1rem;font-weight:800;color:") + " + _c(nn_p) + " + " + q(">{:.0%}</div></div></div>").format(nn_p))
L("            + _b(nn_p, _c(nn_p)) +")
L("            " + q("<div style='font-size:.65rem;color:#9e9e9e'>非线性模式识别 | &gt;50%=强势做多 | 30-50%=谨慎 | &lt;30%=离场</div></div>"))
L("            " + q("<div style='background:#1a1f27;border-radius:8px;padding:10px;margin-bottom:6px'>"))
L("            " + q("<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px'>"))
L("            " + q("<div style='font-size:.78rem;font-weight:700;color:#26c6da'>LR 逻辑回归</div>"))
L("            " + q("<div style='display:flex;align-items:center;gap:8px'>"))
L("            " + q("<div style='font-size:.68rem;color:#9e9e9e'>") + " + lr_i + " + q("</div>"))
L("            " + q("<div style='font-size:1rem;font-weight:800;color:") + " + _c(lr_p) + " + " + q(">{:.1%}</div></div></div>").format(lr_p))
L("            + _b(lr_p, _c(lr_p)) +")
L("            " + q("<div style='font-size:.65rem;color:#9e9e9e'>线性概率校准 | &gt;50%=强势做多 | 30-50%=谨慎 | &lt;30%=离场</div></div>"))
L("            " + q("<div style='background:rgba(38,198,218,0.12);border-radius:8px;padding:10px;border-left:3px solid #26c6da;margin-bottom:6px'>"))
L("            " + q("<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px'>"))
L("            " + q("<div style='font-size:.8rem;font-weight:700;color:#26c6da'>🔗 Ensemble 综合概率</div>"))
L("            " + q("<div style='display:flex;align-items:center;gap:8px'>"))
L("            " + q("<div style='font-size:.68rem;color:#9e9e9e'>") + " + ens_i + " + q("</div>"))
L("            " + q("<div style='font-size:1.1rem;font-weight:800;color:") + " + _c(ens_p) + " + " + q(">{:.1%}</div></div></div>").format(ens_p))
L("            + _b(ens_p, _c(ens_p)) +")
L("            " + q("<div style='font-size:.65rem;color:#9e9e9e'>三模型均值 | 历史分位: {:.0f}% | ensemble &lt;0.3=离场, 0.3-0.5=谨慎, &gt;0.5=强势做多</div></div>").format(pct))
L("            " + q("<div style='background:#0d1117;border-radius:6px;padding:8px 10px;margin-top:4px'>"))
L("            " + q("<div style='font-size:.7rem;color:#26c6da;margin-bottom:4px'>📐 综合评判逻辑</div>"))
L("            " + q("<div style='font-size:.7rem;color:#9e9e9e;line-height:1.6'>综合概率 = (GBR + NN + LR) / 3，取三模型均值平滑噪音。<br>历史分位数 = 当前ensemble值在最近180日序列中的百分位位置，反映当前概率在历史分布中的高低。<br>当三模型一致性高时信号最强；当分歧大时以ensemble均值为准。</div></div></div>"))
L("        )")
L("")
L("        stale = result.get("data_staleness_days\", 0)")
L("        sc = \"#00e676\" if stale == 0 else (\"#ff9800\" if stale < 5 else \"#d63939\")")
L("        st = \"✅ 数据最新\" if stale == 0 else (\"⚠️ 数据过期{}天\".format(stale) if stale < 5 else \"🔴 数据严重过期{}天\".format(stale))")
L("        extra_parts.append(\"<div class='sig-row'><span class='sig-label'>数据新鲜度</span><span class='sig-value' style='color:\" + sc + \">\" + st + \"</span></div>\")")

sys.exit(0)

# remaining lines would go here...
