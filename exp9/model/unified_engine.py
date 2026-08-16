#!/usr/bin/env python3
"""
G4 融合引擎 — 统一分析入口
================================================
同时调用多个专家脚本（目前：P02蜡烛图 + P18第二段陷阱），
对同一只股票/图片进行综合分析，输出统一的决策结果。

用法：
    from unified_engine import analyze_stock
    result = analyze_stock("AAPL")
"""

from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

# ── 专家脚本导入 ─────────────────────────────────────────────────────────────
# 每个专家脚本需要实现：analyze_pattern(chart_desc, market_env, patterns, signals)
# 和 quick_signal(env, patterns)

import sys
sys.path.insert(0, str(Path(__file__).parent))

from model.p02_candlestick import (
    analyze_pattern as p02_analyze,
    quick_signal   as p02_quick,
    Direction      as Dir,
)
from model.p18_second_leg_trap import (
    analyze_pattern as p18_analyze,
    quick_signal   as p18_quick,
    PatternMatch   as PM,
)

# ══════════════════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════════════════

class Direction(Enum):
    LONG  = "LONG"
    SHORT = "SHORT"
    WATCH = "WATCH"
    NONE  = "NONE"

@dataclass
class ExpertResult:
    """单个专家脚本的分析结果"""
    video: str
    primary_signal: str  # 统一用字符串: "LONG"/"SHORT"/"WATCH"/"NONE"
    confidence: str
    matched_patterns: list
    reasons: list
    risk_warnings: list

@dataclass
class UnifiedResult:
    """融合后的综合结果"""
    stock: str
    period: str
    # 各专家意见
    p02: Optional[ExpertResult]
    p18: Optional[ExpertResult]
    # 融合信号（字符串）
    unified_signal: str
    unified_confidence: str
    # 共识规则
    consensus_patterns: list
    all_patterns: list
    all_reasons: list
    all_risks: list
    summary: str

# ══════════════════════════════════════════════════════════════════════════════
# K线数据加载（复用于 engine.py）
# ══════════════════════════════════════════════════════════════════════════════

KLINES_ROOT = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines")

def load_klines(stock: str, period: str = "1d") -> Optional[list]:
    path = KLINES_ROOT / f"{stock}_{period}.json"
    if not path.exists():
        return None
    with open(path) as f:
        d = json.load(f)
    return d.get("data", d)

def calc_indicators(bars: list) -> dict:
    closes  = [b["close"] for b in bars]
    highs   = [b["high"]  for b in bars]
    lows    = [b["low"]   for b in bars]
    volumes = [b.get("vol", 0) for b in bars]

    def sma(data, period):
        result = []
        for i in range(len(data)):
            result.append(sum(data[max(0,i-period+1):i+1])/min(period,i+1) if i >= 0 else None)
        return result

    ma5  = sma(closes, 5)
    ma10 = sma(closes, 10)
    ma20 = sma(closes, 20)

    def calc_rsi(data, period=14):
        result = [None] * len(data)
        if len(data) < period + 1:
            return result
        gains, losses = [], []
        for i in range(1, len(data)):
            delta = data[i] - data[i-1]
            gains.append(max(delta, 0))
            losses.append(max(-delta, 0))
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        for i in range(period, len(data)):
            if i > period:
                avg_gain = (avg_gain * (period-1) + gains[i-1]) / period
                avg_loss = (avg_loss * (period-1) + losses[i-1]) / period
            rs = avg_gain / avg_loss if avg_loss != 0 else 100
            result[i] = round(100 - 100 / (1 + rs), 1)
        return result

    rsi14 = calc_rsi(closes, 14)

    n = len(closes)
    ma5_last  = ma5[-1]  if n >= 1 and ma5[-1]  is not None else None
    ma10_last = ma10[-1] if n >= 2 and ma10[-1] is not None else None
    ma20_last = ma20[-1] if n >= 20 else None

    if ma5_last and ma10_last and ma20_last:
        if ma5_last > ma10_last > ma20_last:
            trend = "上升趋势"
        elif ma5_last < ma10_last < ma20_last:
            trend = "下降趋势"
        else:
            trend = "震荡/混乱"
    else:
        trend = "数据不足"

    ma_ali = []
    if ma5_last and ma10_last:
        ma_ali.append("MA5>MA10" if ma5_last > ma10_last else "MA5<MA10")
    if ma10_last and ma20_last:
        ma_ali.append("MA10>MA20" if ma10_last > ma20_last else "MA10<MA20")

    vol_avg5 = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else 0
    vol_now = volumes[-1] if volumes else 0
    vol_ratio = round(vol_now / vol_avg5, 2) if vol_avg5 > 0 else 1.0

    rsi_last = rsi14[-1] if rsi14 and rsi14[-1] is not None else None
    rsi_stat = "RSI中性"
    if rsi_last:
        if rsi_last > 70:   rsi_stat = "RSI极度超买"
        elif rsi_last < 30:  rsi_stat = "RSI极度超卖"
        elif rsi_last > 55:  rsi_stat = "RSI偏强"
        elif rsi_last < 45:  rsi_stat = "RSI偏弱"

    return {
        "date":  bars[-1]["date"] if bars else None,
        "close": closes[-1],
        "high":  max(highs[-5:]),
        "low":   min(lows[-5:]),
        "trend": trend,
        "ma5":   round(ma5_last, 2)  if ma5_last  else None,
        "ma10":  round(ma10_last, 2) if ma10_last else None,
        "ma20":  round(ma20_last, 2) if ma20_last else None,
        "ma_alignment": ma_ali,
        "rsi14": rsi_last,
        "rsi_status": rsi_stat,
        "volume_ratio": vol_ratio,
        "volume_signal": "放量" if vol_ratio > 1.3 else ("缩量" if vol_ratio < 0.7 else "正常"),
        "bars_count": n,
    }

def indicators_to_text(ib: dict) -> str:
    parts = [
        f"日期：{ib['date']}",
        f"最新价：{ib['close']}",
        f"趋势：{ib['trend']}",
        f"均线：{'，'.join(ib['ma_alignment']) if ib['ma_alignment'] else '无'}",
        f"MA5={ib['ma5']}，MA10={ib['ma10']}，MA20={ib['ma20']}",
        f"RSI(14)={ib['rsi14']}（{ib['rsi_status']}）",
        f"成交量：{ib['volume_signal']}（比值{ib['volume_ratio']}）",
    ]
    return "；".join(parts)

def indicators_to_patterns(ib: dict) -> list[str]:
    """把指标计算结果转成规则引擎能理解的模式列表"""
    patterns = []
    if ib["trend"] == "上升趋势":
        patterns.extend(["上升趋势", "均线多头排列"])
    elif ib["trend"] == "下降趋势":
        patterns.extend(["下降趋势", "均线空头排列"])

    if ib.get("rsi14"):
        if ib["rsi14"] > 70:
            patterns.append("RSI极度超买")
        elif ib["rsi14"] < 30:
            patterns.append("RSI极度超卖")
        elif ib["rsi14"] > 55:
            patterns.append("RSI偏强")
        elif ib["rsi14"] < 45:
            patterns.append("RSI偏弱")

    if ib["volume_ratio"] > 1.3:
        patterns.append("放量")
    elif ib["volume_ratio"] < 0.7:
        patterns.append("缩量")

    if "MA5>MA10" in ib.get("ma_alignment", []):
        patterns.append("MA5在MA10上方")
    return patterns

# ══════════════════════════════════════════════════════════════════════════════
# 专家脚本调用
# ══════════════════════════════════════════════════════════════════════════════

def call_expert(analyzer_func, chart_desc: str, env: str, patterns: list[str], signals: list[str]):
    """调用单个专家脚本，返回 ExpertResult"""
    try:
        result = analyzer_func(
            chart_description=chart_desc,
            market_environment=env,
            patterns_found=patterns,
            kline_signals=signals,
        )
        return ExpertResult(
            video=result.video or "unknown",
            primary_signal=_normalize_dir(result.primary_signal),
            confidence=result.confidence,
            matched_patterns=result.matched_patterns,
            reasons=result.reasons,
            risk_warnings=result.risk_warnings,
        )
    except Exception as e:
        return ExpertResult(
            video="error",
            primary_signal="NONE",
            confidence="低",
            matched_patterns=[],
            reasons=[f"分析出错: {e}"],
            risk_warnings=[],
        )

# ══════════════════════════════════════════════════════════════════════════════
# 融合决策
# ══════════════════════════════════════════════════════════════════════════════

def _normalize_dir(d) -> str:
    """把任意Direction枚举转成字符串"""
    if hasattr(d, 'value'):
        return d.value  # Enum
    return str(d)  # fallback

def _merge_direction(d1, d2) -> tuple:
    """
    合并两个专家的方向信号。
    规则：
      - 双方一致 → 采用该方向
      - 一方WATCH → 采用另一方
      - 冲突 → SHORT > LONG
    """
    v1 = _normalize_dir(d1)
    v2 = _normalize_dir(d2)

    if v1 == v2:
        # 双方一致：都用同一个normalized值
        return v1, "两个专家一致"
    if v1 == "WATCH":
        return v2, f"P18:{v2} > P02观望"
    if v2 == "WATCH":
        return v1, f"P02:{v1} > P18观望"
    # 冲突：SHORT > LONG
    if v1 == "SHORT" or v2 == "SHORT":
        return "SHORT", "信号冲突，SHORT优先"
    return "LONG", "信号冲突，默认LONG"

def _extract_pattern_names(results: list[ExpertResult]) -> list[str]:
    names = []
    for r in results:
        if not r.matched_patterns:
            continue
        for p in r.matched_patterns:
            if hasattr(p, 'name'):
                names.append(p.name)
            elif isinstance(p, dict):
                names.append(p.get('name', ''))
    return names

def _extract_reasons(results: list[ExpertResult]) -> list[str]:
    reasons = []
    for r in results:
        for reason in r.reasons:
            # 避免重复
            if reason not in reasons:
                reasons.append(reason)
    return reasons

def _extract_risks(results: list[ExpertResult]) -> list[str]:
    risks = []
    for r in results:
        for w in r.risk_warnings:
            if w not in risks:
                risks.append(w)
    return risks

# ══════════════════════════════════════════════════════════════════════════════
# 公开 API
# ══════════════════════════════════════════════════════════════════════════════

def analyze_stock(stock: str, period: str = "1d") -> UnifiedResult:
    """
    统一分析入口：加载K线 → 计算指标 → 同时调用P02+P18专家 → 融合结果
    """
    bars = load_klines(stock.upper(), period)
    if not bars:
        raise FileNotFoundError(f"未找到K线数据: {stock}_{period}.json")

    ib = calc_indicators(bars)
    kline_text = indicators_to_text(ib)
    env = ib["trend"]
    patterns = indicators_to_patterns(ib)
    signals = []

    # ── 调用两个专家脚本 ─────────────────────────────────────────────
    p02 = call_expert(p02_analyze, kline_text, env, patterns, signals)
    p18 = call_expert(p18_analyze, kline_text, env, patterns, signals)

    # ── 融合决策 ─────────────────────────────────────────────────
    unified_dir, dir_reason = _merge_direction(p02.primary_signal, p18.primary_signal)

    # 置信度：取两个专家中较高的
    conf_map = {"极高": 4, "高": 3, "中": 2, "低": 1}
    c1 = conf_map.get(p02.confidence, 0)
    c2 = conf_map.get(p18.confidence, 0)
    unified_conf = max(c1, c2)
    unified_confidence = next((k for k, v in conf_map.items() if v == unified_conf), "中")

    # 共识规则
    p02_names = set(_extract_pattern_names([p02]))
    p18_names = set(_extract_pattern_names([p18]))
    consensus = list(p02_names & p18_names)
    all_patterns = list(p02_names | p18_names)
    all_reasons = _extract_reasons([p02, p18])
    all_risks   = _extract_risks([p02, p18])

    # ── 总结 ──────────────────────────────────────────────────────
    expert_views = []
    if p02.primary_signal not in ("NONE", ""):
        expert_views.append(f"P02({p02.confidence}): {p02.primary_signal}")
    if p18.primary_signal not in ("NONE", ""):
        expert_views.append(f"P18({p18.confidence}): {p18.primary_signal}")

    summary = (
        f"{stock} {period} 综合分析 | "
        f"指标: {kline_text} | "
        f"专家意见: {', '.join(expert_views)} | "
        f"统一信号: {unified_dir}({unified_confidence}) | "
        f"共识规则: {consensus if consensus else '无'} | "
        f"融合原因: {dir_reason}"
    )

    return UnifiedResult(
        stock=stock.upper(),
        period=period,
        p02=p02,
        p18=p18,
        unified_signal=unified_dir,
        unified_confidence=unified_confidence,
        consensus_patterns=consensus,
        all_patterns=all_patterns,
        all_reasons=all_reasons,
        all_risks=all_risks,
        summary=summary,
    )


def print_report(result: UnifiedResult):
    """打印分析报告"""
    print(f"\n{'='*60}")
    print(f"📊 {result.stock} {result.period} 综合分析报告")
    print(f"{'='*60}")

    # 指标摘要
    if result.p02:
        ib_summary = result.p02.reasons[0] if result.p02.reasons else ""
        print(f"\n【技术指标】{ib_summary}")

    # P02 意见
    if result.p02 and result.p02.primary_signal not in ("NONE", ""):
        print(f"\n🕯️ P02 蜡烛图专家:")
        print(f"   信号: {result.p02.primary_signal} | 置信度: {result.p02.confidence}")
        if result.p02.matched_patterns:
            print(f"   规则: {[p.name if hasattr(p,'name') else p.get('name','') for p in result.p02.matched_patterns]}")
        if result.p02.reasons:
            for r in result.p02.reasons[:3]:
                print(f"   · {r}")

    # P18 意见
    if result.p18 and result.p18.primary_signal not in ("NONE", ""):
        print(f"\n🎯 P18 第二段陷阱专家:")
        print(f"   信号: {result.p18.primary_signal} | 置信度: {result.p18.confidence}")
        if result.p18.matched_patterns:
            print(f"   规则: {[p.name if hasattr(p,'name') else p.get('name','') for p in result.p18.matched_patterns]}")
        if result.p18.reasons:
            for r in result.p18.reasons[:3]:
                print(f"   · {r}")

    # 共识
    if result.consensus_patterns:
        print(f"\n🤝 共识规则: {result.consensus_patterns}")

    # 风险
    if result.all_risks:
        print(f"\n⚠️ 风险提示:")
        for w in result.all_risks:
            print(f"   · {w}")

    # 统一结论
    print(f"\n{'='*60}")
    print(f"🎯 统一信号: {result.unified_signal}（置信度: {result.unified_confidence}）")
    print(f"{'='*60}")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="G4 融合引擎")
    parser.add_argument("stock", help="股票代码，如 AAPL")
    parser.add_argument("--period", default="1d", help="周期，默认1d")
    args = parser.parse_args()

    try:
        result = analyze_stock(args.stock.upper(), args.period)
        print_report(result)
    except FileNotFoundError as e:
        print(f"错误: {e}")
