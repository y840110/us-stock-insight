"""
P2 Master Dispatcher
──────────────────────────────────────────────────────────────────
职责：
  1. 统一加载所有数据（一次加载，所有策略共享）
  2. 并行运行 4 策略：
     A) Momentum   动量趋势
     B) Macro      宏观择时
     C) ML_Prob    机器学习概率
     D) Agents     TradingAgents 多Agent辩论
  3. 诊断多策略分歧 → 输出保守处理
  4. 生成 HTML 报告

使用方式：
  from p2_master_dispatcher import run
  result = run("2026-05-15")
──────────────────────────────────────────────────────────────────
"""
from __future__ import annotations
import sys, os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from p2_shared.variables import load_all_variables
from p2_momentum_v20260516 import analyze_momentum
from p2_macro_v20260516 import analyze_macro
from p2_ml_prob_v20260516 import (
    analyze_ml_probability, get_data_staleness_days
)
from p2_agents_debate_v20260516 import analyze_agents_debate

# 默认权重（4策略）
DEFAULT_WEIGHTS = {
    "MOMENTUM": 0.30,
    "MACRO": 0.25,
    "ML_PROB": 0.20,
    "AGENTS": 0.25,
}

RISK_OFF_set = {"RISK_OFF", "CURDLE", "STRESS", "HIGH_RISK"}
BULL_set = {"BULL_TREND", "RECOVERY", "EXPANSION", "LOW_RISK"}


# ───────────────────────────────────────────────────────────────
# 主入口
# ───────────────────────────────────────────────────────────────

def run(
    trade_date: str,
    weights: Optional[Dict[str, float]] = None,
    output_html: bool = True,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    P2 总入口
    参数:
        trade_date:  分析日期（YYYY-MM-DD）
        weights:     策略权重，默认 {"MOMENTUM":0.30, "MACRO":0.25, "ML_PROB":0.20, "AGENTS":0.25}
        output_html: 是否生成 HTML 报告
        verbose:     是否打印详细诊断
    返回:
        {
          "trade_date": str,
          "strategy_A": {...},
          "strategy_B": {...},
          "strategy_C": {...},
          "strategy_D": {...},
          "combined": {...},
          "diagnostic": {...},
          "variables": {...},
        }
    """
    weights = weights or DEFAULT_WEIGHTS.copy()

    # ── Step 1: 加载数据 ─────────────────────────────────────
    v = load_all_variables(trade_date)

    # ── Step 2: 并行运行四策略 ───────────────────────────────
    rA = analyze_momentum(trade_date, v)
    rB = analyze_macro(trade_date, v)
    rC = analyze_ml_probability(trade_date, v)
    # ── Strategy D: Agents Debate（LLM多智能体辩论，内存密集）────────
    # 失败时返回中性结果，不阻塞整体流程
    # Yahoo 限流会导致 SIGKILL，加 30s 超时保护
    import threading, queue
    _result_queue = queue.Queue()

    def _run_d():
        try:
            r = analyze_agents_debate(trade_date, v)
            _result_queue.put(("ok", r))
        except Exception as e:
            _result_queue.put(("err", str(e)))

    _t = threading.Thread(target=_run_d, daemon=True)
    _t.start()
    _t.join(timeout=30)
    if _t.is_alive():
        print(f"[P2] Strategy D (Agents Debate) 超时30s，使用中性结果")
        rD = {"strategy": "AGENTS_DEBATE", "trade_date": trade_date,
              "market_regime": "NEUTRAL", "regime_score": 1,
              "timing_state": "NEUTRAL_TIMING", "timing_score": 1,
              "risk_score": 3, "target_exposure": 50.0,
              "interpretation": "[降级] Agents Debate 超时，使用中性假设",
              "signals": ["⚪中性"], "confidence": 0.0}
    else:
        try:
            status, val = _result_queue.get_nowait()
            if status == "ok":
                rD = val
            else:
                print(f"[P2] Strategy D 失败: {val}，使用中性结果")
                rD = {"strategy": "AGENTS_DEBATE", "trade_date": trade_date,
                      "market_regime": "NEUTRAL", "regime_score": 1,
                      "timing_state": "NEUTRAL_TIMING", "timing_score": 1,
                      "risk_score": 3, "target_exposure": 50.0,
                      "interpretation": "[降级] Agents Debate 不可用，使用中性假设",
                      "signals": ["⚪中性"], "confidence": 0.0}
        except queue.Empty:
            rD = {"strategy": "AGENTS_DEBATE", "trade_date": trade_date,
                  "market_regime": "NEUTRAL", "regime_score": 1,
                  "timing_state": "NEUTRAL_TIMING", "timing_score": 1,
                  "risk_score": 3, "target_exposure": 50.0,
                  "interpretation": "[降级] Agents Debate 超时，使用中性假设",
                  "signals": ["⚪中性"], "confidence": 0.0}

    # Inject full judge decision from cache
    try:
        import os, json
        cache_path = "/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/fintech/agent_talk/spy_decision_" + trade_date + ".json"
        if os.path.exists(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                cache = json.load(f)
            inv = cache.get("investment_debate", {})
            rD["judge_decision_full"] = inv.get("judge_decision", "")
    except Exception:
        pass

    # ── Step 3: 合并 ────────────────────────────────────────
    combined = _combine(rA, rB, rC, rD, weights)
    diagnostic = _diagnose(rA, rB, rC, rD, v)

    if verbose:
        _print_diagnostic(rA, rB, rC, rD, diagnostic, v)

    result = {
        "trade_date": trade_date,
        "strategy_A": rA,
        "strategy_B": rB,
        "strategy_C": rC,
        "strategy_D": rD,
        "combined": combined,
        "diagnostic": diagnostic,
        "variables": v,
    }

    # ── Step 4: 生成 HTML ────────────────────────────────────
    if output_html:
        try:
            from p2_layout import generate_html
            html_path = generate_html(result)
            result["html_path"] = str(html_path)
        except Exception as e:
            print(f"HTML 生成失败: {e}")

    return result


# ───────────────────────────────────────────────────────────────
# 四策略合并
# ───────────────────────────────────────────────────────────────

def _combine(rA, rB, rC, rD, weights) -> Dict[str, Any]:
    exp_A = rA["target_exposure"] / 100.0
    exp_B = rB["target_exposure"] / 100.0
    exp_C = rC["target_exposure"] / 100.0
    exp_D = rD["target_exposure"] / 100.0
    wA, wB, wC, wD = (weights.get(k, 0.25) for k in ["MOMENTUM", "MACRO", "ML_PROB", "AGENTS"])

    raw_exposure = exp_A * wA + exp_B * wB + exp_C * wC + exp_D * wD

    rA_reg = rA.get("standard_regime", rA["market_regime"])
    rB_reg = rB.get("standard_regime", rB["market_regime"])
    rC_reg = rC["market_regime"]
    rD_reg = rD["market_regime"]

    risk_off_count = sum(1 for r in [rA_reg, rB_reg, rD_reg] if r in RISK_OFF_set)
    bull_count = sum(1 for r in [rA_reg, rB_reg, rD_reg] if r in BULL_set)

    c_conflicts = (risk_off_count >= 2 and rC_reg in BULL_set) or \
                  (bull_count >= 2 and rC_reg in RISK_OFF_set)
    divergence = (risk_off_count > 0 and bull_count > 0) or c_conflicts

    if c_conflicts:
        non_c = [exp_A, exp_B, exp_D]
        non_c_w = [wA, wB, wD]
        total_w = sum(non_c_w)
        final_exposure = sum(e * w for e, w in zip(non_c, non_c_w)) / total_w * 0.5
        confidence = (rA.get("confidence", 0.5) * wA + rB.get("confidence", 0.5) * wB +
                     rD.get("confidence", 0.5) * wD) / (wA + wB + wD) * 0.85
        suppression_note = f"C(ML_PROB)给出{rC_reg}但A+B+D确认{'RISK_OFF' if risk_off_count >= 2 else 'BULL'}，C被压制"
    elif not (risk_off_count >= 2 or bull_count >= 2):
        final_exposure = raw_exposure * 0.6
        confidence = (rA.get("confidence", 0.5) + rB.get("confidence", 0.5) +
                     rC.get("confidence", 0.5) + rD.get("confidence", 0.5)) / 4.0 * 0.7
        suppression_note = None
    else:
        final_exposure = raw_exposure
        confidence = (rA.get("confidence", 0.5) + rB.get("confidence", 0.5) +
                      rC.get("confidence", 0.5) + rD.get("confidence", 0.5)) / 4.0 + 0.05
        suppression_note = None

    if risk_off_count >= 2:
        final_regime = "RISK_OFF"
    elif bull_count >= 2:
        final_regime = "BULL_TREND"
    elif rD_reg in RISK_OFF_set:
        final_regime = "RISK_OFF"
    elif rC_reg in BULL_set:
        final_regime = "BULL_TREND"
    else:
        final_regime = "NEUTRAL"

    signals = []
    for r in [rA, rB, rC, rD]:
        signals.extend(r.get("signals", []))
    if suppression_note:
        signals.append(f"⚠️ {suppression_note}")

    interpretation = _build_interpretation(final_regime, final_exposure * 100,
                                          rA, rB, rC, rD, divergence, suppression_note)

    return {
        "market_regime": final_regime,
        "target_exposure": round(final_exposure * 100, 1),
        "confidence": round(min(confidence, 0.95), 2),
        "signals": signals,
        "divergence": divergence,
        "interpretation": interpretation,
        "weights_used": {"MOMENTUM": wA, "MACRO": wB, "ML_PROB": wC, "AGENTS": wD},
        "raw_weighted_exposure": round(raw_exposure * 100, 1),
        "C_suppressed": c_conflicts,
    }


# ───────────────────────────────────────────────────────────────
# 分歧诊断
# ───────────────────────────────────────────────────────────────

def _diagnose(rA, rB, rC, rD, v) -> Dict[str, Any]:
    rA_reg = rA.get("standard_regime", rA["market_regime"])
    rB_reg = rB.get("standard_regime", rB["market_regime"])
    rC_reg = rC["market_regime"]
    rD_reg = rD["market_regime"]

    risk_off_count = sum(1 for r in [rA_reg, rB_reg, rD_reg] if r in RISK_OFF_set)
    bull_count = sum(1 for r in [rA_reg, rB_reg, rD_reg] if r in BULL_set)
    c_conflicts = (risk_off_count >= 2 and rC_reg in BULL_set) or \
                  (bull_count >= 2 and rC_reg in RISK_OFF_set)
    divergence = (risk_off_count > 0 and bull_count > 0) or c_conflicts

    reasons = []
    if divergence:
        if (rA_reg in RISK_OFF_set) != (rB_reg in RISK_OFF_set):
            reasons.append(f"A={rA_reg}({rA.get('target_exposure')}%) vs B={rB_reg}({rB.get('target_exposure')}%)")
        if c_conflicts:
            reasons.append(f"C={rC_reg}(prob={rC.get('prob_ensemble'):.1%})与A+B+D冲突")
        staleness = get_data_staleness_days(rC.get('trade_date', '2026-05-15'))
        if staleness > 0:
            reasons.append(f"ML数据过期{staleness}天")
        nyad_slope = v.get("NYAD_SLOPE", 0) or 0
        if nyad_slope < -30:
            reasons.append(f"NYAD下跌{nyad_slope:.0f}/天，严重背离")
        cta = v.get("CTA_POSITIONING")
        if cta and cta < 15:
            reasons.append(f"CTA极度做空({cta:.0f}%)")

    suggestion = "四策略综合，保守仓位优先"
    if c_conflicts:
        suggestion = "ML_PROB被压制，以前三者多数意见为准"

    return {
        "divergence": divergence,
        "regime_A": rA_reg, "regime_B": rB_reg,
        "regime_C": rC_reg, "regime_D": rD_reg,
        "risk_off_count": risk_off_count, "bull_count": bull_count,
        "prob_C": rC.get("prob_ensemble"),
        "data_staleness_days": get_data_staleness_days(rC.get("trade_date", "2026-05-15")),
        "reasons": reasons,
        "suggestion": suggestion,
    }


def _build_interpretation(regime, exposure, rA, rB, rC, rD, divergence, suppression_note):
    tags = {
        "BULL_TREND": "📈 总体偏多",
        "RISK_OFF": "🔴 总体防御",
        "NEUTRAL": "⚪ 方向待确认",
    }
    lines = [tags.get(regime, regime)]
    if divergence:
        lines.append("（存在策略分歧）")
    if exposure < 10:
        lines.append(f"建议极低仓位（{exposure:.1f}%）")
    elif exposure < 30:
        lines.append(f"建议低配（{exposure:.1f}%）")
    elif exposure < 60:
        lines.append(f"建议标配（{exposure:.1f}%）")
    else:
        lines.append(f"建议高配（{exposure:.1f}%）")
    lines.append(f"四策略: A:{rA['market_regime']}({rA['target_exposure']:.0f}%) "
                 f"B:{rB['market_regime']}({rB['target_exposure']:.0f}%) "
                 f"C:{rC['market_regime']}({rC['target_exposure']:.0f}%) "
                 f"D:{rD['market_regime']}({rD['target_exposure']:.0f}%)")
    if suppression_note:
        lines.append(f"[压制C] {suppression_note}")
    return " | ".join(lines)


def _print_diagnostic(rA, rB, rC, rD, diagnostic, v):
    print(f"\n{'='*60}")
    print("策略分歧诊断（四策略）")
    print(f"{'='*60}")
    print(f"  A(Momentum): {rA.get('market_regime')} | {rA.get('target_exposure')}%")
    print(f"  B(Macro):    {rB.get('market_regime')} | {rB.get('target_exposure')}%")
    print(f"  C(ML_Prob): {rC.get('market_regime')} | prob:{rC.get('prob_ensemble')} | {rC.get('target_exposure')}%")
    print(f"  D(Agents):   {rD.get('market_regime')} | {rD.get('decision')} | {rD.get('target_exposure')}%")
    print(f"  一致性: {'✅ 一致' if not diagnostic['divergence'] else '⚠️ 分歧'}")
    if diagnostic.get('divergence'):
        print(f"\n  分歧原因:")
        for reason in diagnostic.get('reasons', []):
            print(f"    - {reason}")
    def _fmt(v, key, default='N/A'):
        val = v.get(key, default)
        if val is None or val == 'N/A':
            return str(default)
        try:
            return f"{float(val):.1f}"
        except (TypeError, ValueError):
            return str(val)

    print(f"\n  关键指标:")
    print(f"    RSI14: {_fmt(v, 'SPY_RSI14')}")
    print(f"    NYAD_SLOPE: {_fmt(v, 'NYAD_SLOPE')}")
    print(f"    CTA %ile: {_fmt(v, 'CTA_POSITIONING')}")
    if v.get('HY_SPREAD') is not None:
        try:
            print(f"    HY Spread: {float(v.get('HY_SPREAD')):.2f}%")
        except (TypeError, ValueError):
            pass
    if v.get('VIX') is not None:
        try:
            print(f"    VIX: {float(v.get('VIX')):.2f}")
        except (TypeError, ValueError):
            print(f"    VIX: {v.get('VIX')}")


# ───────────────────────────────────────────────────────────────
# CLI 入口
# ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    trade_date = sys.argv[1] if len(sys.argv) > 1 else "2026-05-15"
    result = run(trade_date, verbose=True)

    print(f"\n{'='*60}")
    print(f"P2 综合结果 — {trade_date}（4策略并行）")
    print(f"{'='*60}")
    comb = result["combined"]
    print(f"  Regime:  {comb['market_regime']}")
    print(f"  仓位:   {comb['target_exposure']}%  (原始: {comb['raw_weighted_exposure']}%)")
    print(f"  置信度: {comb['confidence']}")
    print(f"  C被压制: {'是 ⚠️' if comb.get('C_suppressed') else '否 ✅'}")
    print(f"  分歧:   {'是 ⚠️' if comb['divergence'] else '否 ✅'}")
    if "html_path" in result:
        print(f"\n  HTML: {result['html_path']}")
