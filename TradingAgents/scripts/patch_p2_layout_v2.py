#!/usr/bin/env python3
"""Patch p2_layout.py to enhance Strategy C and D output in _build_strategy_card."""

import ast

# ========== NEW extra_parts BLOCK ==========
# This will be joined and assigned to extra_parts
NEW_EXTRA_PARTS = []

# ----- Strategy C: ML三模型独立结论 + 综合评判逻辑 -----
NEW_EXTRA_PARTS.append("""
    # 📐 Strategy C: ML三模型独立结论 + 综合评判逻辑
    if result.get('prob_gbr') is not None:
        gbr = result['prob_gbr']
        nn = result.get('prob_nn', 0)
        lr = result.get('prob_lr', 0)
        ens = result.get('prob_ensemble', 0)
        pct = result.get('prob_percentile', 0)

        def _c(v):
            if v >= 70: return '#00e676'
            if v >= 50: return '#ff9800'
            return '#d63939'

        def _b(v, col):
            return (
                f"<div style='background:#2a2a3e;border-radius:4px;overflow:hidden;margin-top:4px;'>"
                f"<div style='width:{v:.1f}%;height:6px;background:{col};border-radius:4px;'></div>"
                f"</div>"
            )

        def _model_card(label, prob, accent):
            color = _c(prob)
            if prob >= 70:
                tag_class = 'sig-bull'
                tag_text = '强势做多'
            elif prob >= 50:
                tag_class = 'sig-neutral'
                tag_text = '谨慎做多'
            else:
                tag_class = 'sig-bear'
                tag_text = '离场/做空'
            return (
                f"<div style='background:#1e1e30;border-radius:8px;padding:12px;flex:1;min-width:0;'>"
                f"<div style='display:flex;align-items:center;gap:6px;margin-bottom:8px;'>"
                f"<span style='font-size:13px;color:#e0e0e0;font-weight:600;'>{label}</span>"
                f"<span class='{tag_class}' style='font-size:11px;padding:1px 7px;border-radius:10px;'>{tag_text}</span>"
                f"</div>"
                f"<div style='font-size:22px;font-weight:700;color:{color};margin-bottom:6px;'>{prob:.1f}%</div>"
                f"{_b(prob, color)}"
                f"</div>"
            )

        NEW_EXTRA_PARTS.append("<div style='display:flex;gap:10px;margin-top:12px;flex-wrap:wrap;'>")
        NEW_EXTRA_PARTS.append(_model_card('GBR', gbr, '#2196f3'))
        NEW_EXTRA_PARTS.append(_model_card('NN', nn, '#9c27b0'))
        NEW_EXTRA_PARTS.append(_model_card('LR', lr, '#ff9800'))
        NEW_EXTRA_PARTS.append('</div>')

        # 综合评判逻辑解读
        color = _c(ens)
        if ens >= 70:
            ens_tag_class = 'sig-bull'
            ens_tag_text = '强势做多'
        elif ens >= 50:
            ens_tag_class = 'sig-neutral'
            ens_tag_text = '谨慎做多'
        else:
            ens_tag_class = 'sig-bear'
            ens_tag_text = '离场/做空'

        NEW_EXTRA_PARTS.append(
            f"<div style='background:#1a1a2e;border-radius:8px;padding:12px;margin-top:10px;border-left:3px solid #2196f3;'>"
            f"<div style='font-size:12px;color:#9fa8da;margin-bottom:6px;letter-spacing:0.5px;'>📐 综合评判逻辑（Ensemble）</div>"
            f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:8px;'>"
            f"<span style='font-size:20px;font-weight:700;color:{color};'>{ens:.1f}%</span>"
            f"<span class='{ens_tag_class}' style='font-size:11px;padding:1px 7px;border-radius:10px;'>{ens_tag_text}</span>"
            f"<span style='font-size:11px;color:#78909c;margin-left:auto;'>百分位: {pct:.0f}%</span>"
            f"</div>"
            f"<div style='font-size:12px;color:#b0bec5;line-height:1.6;'>"
            f"综合概率 = GBR({gbr:.1f}%) × 0.4 + NN({nn:.1f}%) × 0.35 + LR({lr:.1f}%) × 0.25，加权平均后经百分位标准化。"
            f"百分位{pct:.0f}%表示当前概率处于历史{pct:.0f}%的分位以上。</div>"
            f"</div>"
        )

        staleness = result.get('data_staleness_days', 0)
        if staleness > 0:
            NEW_EXTRA_PARTS.append(
                f"<div style='font-size:11px;color:#78909c;margin-top:6px;text-align:right;'>数据龄: {staleness}天</div>"
            )
""")

# ----- Strategy D: Agents辩论完整过程 -----
NEW_EXTRA_PARTS.append("""
    # 🗳️ Strategy D: Agents辩论完整过程
    bull_count = result.get('bull_count', 0)
    bear_count = result.get('bear_count', 0)
    if result.get('decision') and (bull_count + bear_count) > 0:
        trade_date = result.get('trade_date', '')
        cache_path = Path(__file__).parent.parent.parent / 'fintech' / 'agent_talk' / f'spy_decision_{trade_date}.json'
        debate_data = {}
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    debate_data = json.load(f)
            except:
                pass

        def _arg_html(args, accent, max_n=8):
            if not args:
                return "<span style='color:#546e7a;font-size:12px;'>无</span>"
            items = []
            for i, arg in enumerate(args[:max_n]):
                role = arg.get('role', 'agent')
                content = arg.get('content', '')[:120]
                if role == 'bull':
                    icon = '🐂'
                    cls = 'bull-arg'
                    col = '#00c853'
                elif role == 'bear':
                    icon = '🐻'
                    cls = 'bear-arg'
                    col = '#d63939'
                else:
                    icon = '⚖️'
                    cls = 'neutral-arg'
                    col = '#9e9e9e'
                items.append(
                    f"<div style='background:#1e1e30;border-radius:6px;padding:8px 10px;margin-bottom:6px;border-left:2px solid {col};'>"
                    f"<span style='font-size:11px;color:{col};margin-right:4px;'>{icon}</span>"
                    f"<span style='font-size:12px;color:#cfd8dc;'>{content}</span>"
                    f"</div>"
                )
            return ''.join(items)

        inv = debate_data.get('investment_debate', {})
        risk = debate_data.get('risk_debate', {})

        # 投资辩论
        NEW_EXTRA_PARTS.append(
            "<div style='background:#1a1a2e;border-radius:8px;padding:14px;margin-top:12px;'>"
            "<div style='font-size:13px;color:#e0e0e0;font-weight:600;margin-bottom:10px;'>🗳️ 投资辩论（Investment Debate）</div>"
        )
        NEW_EXTRA_PARTS.append(
            f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;'>"
            f"<div>"
            f"<div style='display:flex;align-items:center;gap:6px;margin-bottom:6px;'>"
            f"<span style='color:#00c853;font-size:12px;'>🐂 多头 ({inv.get('bull_count', bull_count)}人)</span>"
            f"</div>"
            f"{_arg_html(inv.get('bull_history', []), '#00c853')}"
            f"</div>"
            f"<div>"
            f"<div style='display:flex;align-items:center;gap:6px;margin-bottom:6px;'>"
            f"<span style='color:#d63939;font-size:12px;'>🐻 空头 ({inv.get('bear_count', bear_count)}人)</span>"
            f"</div>"
            f"{_arg_html(inv.get('bear_history', []), '#d63939')}"
            f"</div>"
            f"</div>"
        )
        jdg = inv.get('judge_decision', {})
        if jdg:
            jdg_action = jdg.get('action', '')
            jdg_conf = jdg.get('confidence', 0)
            jdg_col = '#00c853' if 'bull' in jdg_action.lower() or 'long' in jdg_action.lower() else '#d63939'
            NEW_EXTRA_PARTS.append(
                f"<div style='background:#1e1e30;border-radius:6px;padding:10px;border-left:3px solid {jdg_col};margin-bottom:12px;'>"
                f"<div style='font-size:11px;color:#78909c;margin-bottom:4px;'>⚖️ 投资裁决</div>"
                f"<div style='font-size:13px;color:{jdg_col};font-weight:600;'>{jdg_action}</div>"
                f"<div style='font-size:11px;color:#78909c;margin-top:2px;'>置信度: {jdg_conf:.0%}</div>"
                f"</div>"
            )

        # 风险辩论
        risk_cons = risk.get('conservative_history', [])
        risk_agg = risk.get('aggressive_history', [])
        NEW_EXTRA_PARTS.append(
            "<div style='font-size:13px;color:#e0e0e0;font-weight:600;margin-bottom:10px;'>🛡️ 风险辩论（Risk Debate）</div>"
        )
        NEW_EXTRA_PARTS.append(
            f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;'>"
            f"<div>"
            f"<div style='display:flex;align-items:center;gap:6px;margin-bottom:6px;'>"
            f"<span style='color:#42a5f5;font-size:12px;'>🛡️ 保守派 ({len(risk_cons)}条)</span>"
            f"</div>"
            f"{_arg_html(risk_cons, '#42a5f5')}"
            f"</div>"
            f"<div>"
            f"<div style='display:flex;align-items:center;gap:6px;margin-bottom:6px;'>"
            f"<span style='color:#ff7043;font-size:12px;'>⚡ 激进派 ({len(risk_agg)}条)</span>"
            f"</div>"
            f"{_arg_html(risk_agg, '#ff7043')}"
            f"</div>"
            f"</div>"
        )
        rjdg = risk.get('judge_decision', {})
        if rjdg:
            rjdg_action = rjdg.get('action', '')
            rjdg_conf = rjdg.get('confidence', 0)
            rjdg_col = '#42a5f5' if 'conservative' in rjdg_action.lower() or 'low' in rjdg_action.lower() else '#ff7043'
            NEW_EXTRA_PARTS.append(
                f"<div style='background:#1e1e30;border-radius:6px;padding:10px;border-left:3px solid {rjdg_col};'>"
                f"<div style='font-size:11px;color:#78909c;margin-bottom:4px;'>⚖️ 风险裁决</div>"
                f"<div style='font-size:13px;color:{rjdg_col};font-weight:600;'>{rjdg_action}</div>"
                f"<div style='font-size:11px;color:#78909c;margin-top:2px;'>置信度: {rjdg_conf:.0%}</div>"
                f"</div>"
            )
        NEW_EXTRA_PARTS.append("</div>")
""")

# Now build the actual Python code string that will replace the old block
# We need to build it as a series of string literals that append to extra_parts

NEW_CODE = '''
    # === Enhanced Strategy C & D Output ===
    extra_parts = []
''' + '\n'.join(NEW_EXTRA_PARTS) + '''
    extra_html = "".join(extra_parts)
'''

print("New block built successfully, length:", len(NEW_CODE))
print("Statements:", NEW_CODE.count('\n'))
