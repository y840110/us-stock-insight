"""
P2 Strategy D: Agents Debate Engine
=====================================
包装 agent_talk（原 experiment_8）的 TradingAgents 多 Agent 辩论框架：
  Market Analyst → Fundamentals Analyst
  → Bull Researcher vs Bear Researcher 辩论
  → Conservative vs Aggressive Risk Debater 辩论
  → Research Manager 综合 → Trader 最终决策

职责：
  - 变盘信号识别（基于多空辩论强度）
  - 市场情绪评估（乐观/悲观/中性）
  - 输出结构化信号，供 P2 合并使用

依赖：
  - tradingagents 包（系统安装版，已打 SPY 本地缓存补丁）
  - agent_talk 的 yf_cache_patch 已在 P1 数据体系中不再需要（SPY 走 P1 klines 目录）
"""
from __future__ import annotations
import json, sys, os, time
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

# ── 补丁：SPY 走本地缓存，新闻返回空 ───────────────────────────────
# 必须在任何 tradingagents 或 yfinance 模块导入之前执行！

import sys
_LOCAL_KLINE_DIR = "/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines"

def _load_local_kline_csv(symbol: str, start_date: str, end_date: str):
    """返回 CSV 字符串（匹配 get_YFin_data_online 的返回格式）。"""
    path = os.path.join(_LOCAL_KLINE_DIR, f"{symbol.upper()}_1d.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        raw = json.load(f)
    records = [r for r in raw["data"] if start_date <= r["date"] <= end_date]
    if not records:
        return None
    import pandas as pd
    df = pd.DataFrame(records)
    df["Date"] = pd.to_datetime(df["date"])
    df = df.set_index("Date").sort_index()
    for col in ["Open", "High", "Low", "Close", "Adj Close"]:
        if col in df.columns:
            df[col] = df[col].round(2)
    if "Volume" in df.columns:
        df["Volume"] = df["Volume"].astype(int)
    header = (f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
              f"# Total records: {len(df)}\n"
              f"# Data source: local SPY cache (yfinance bypassed)\n\n")
    return header + df.to_csv()

# ── Patch tradingagents.dataflows.y_finance ─────────────────────
# 在 get_YFin_data_online 层面拦截 SPY，不动 yfinance.Ticker 类（避免递归）
import tradingagents.dataflows.y_finance as _yf_dflow
_orig_get_YFin = _yf_dflow.get_YFin_data_online
def _patched_get_YFin(symbol, start_date, end_date):
    if symbol.upper() == "SPY":
        csv_data = _load_local_kline_csv(symbol, start_date, end_date)
        if csv_data is not None:
            return csv_data
    return _orig_get_YFin(symbol, start_date, end_date)
_yf_dflow.get_YFin_data_online = _patched_get_YFin

# ── Patch route_to_vendor ─────────────────────────────────────
import tradingagents.dataflows.interface as _iface
_orig_route = _iface.route_to_vendor
def _patched_route(method, *args, **kwargs):
    if method == "get_stock_data" and len(args) >= 3:
        symbol = args[0]
        if symbol.upper() == "SPY":
            csv_data = _load_local_kline_csv(symbol, args[1], args[2])
            if csv_data is not None:
                return csv_data
    return _orig_route(method, *args, **kwargs)
_iface.route_to_vendor = _patched_route

# ── 4. Patch news ───────────────────────────────────────────────
import tradingagents.dataflows.yfinance_news as _yf_news
_orig_news  = _yf_news.get_news_yfinance
_orig_gnews = _yf_news.get_global_news_yfinance
def _patched_news(ticker, start, end, max_items=None):
    return "[yfinance 限速中，新闻数据暂不可用]"
def _patched_gnews(lookback_days, max_items=None):
    return "[yfinance 限速中，全球新闻数据暂不可用]"
_yf_news.get_news_yfinance        = _patched_news
_yf_news.get_global_news_yfinance = _patched_gnews

# ── 5. Patch reasoning_split (MiniMax API 不兼容) ──────────────
import tradingagents.llm_clients.openai_client as _oai
_oai_get_payload = _oai.MinimaxChatOpenAI._get_request_payload
def _patched_payload(self, input_, *, stop=None, **kwargs):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI._get_request_payload(self, input_, stop=stop, **kwargs)
_oai.MinimaxChatOpenAI._get_request_payload = _patched_payload


# ── TradingAgents 图初始化（延迟导入，避免循环） ─────────────────────
def _get_ta_graph():
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config.update({
        "llm_provider":       "minimax-cn",
        "backend_url":         "https://api.minimaxi.com/v1",
        "deep_think_llm":     "MiniMax-M2.7",
        "quick_think_llm":    "MiniMax-M2.7-highspeed",
        "output_language":    "Chinese",
        "max_debate_rounds":         1,
        "max_risk_discuss_rounds":   1,
        "checkpoint_enabled":  False,
        "data_vendors": {
            "core_stock_apis":      "yfinance",
            "technical_indicators":"yfinance",
            "fundamental_data":    "yfinance",
            "news_data":           "yfinance",
        },
        "global_news_queries": [
            "Federal Reserve interest rates inflation 2026",
            "S&P 500 economy earnings outlook",
            "trade tariffs geopolitical risk",
            "VIX market volatility",
        ],
    })

    ta = TradingAgentsGraph(
        selected_analysts=["market", "fundamentals"],
        debug=False,
        config=config,
    )
    return ta


# ── 安全序列化 ─────────────────────────────────────────────────────
def _serialize(obj, limit=3000):
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj[:limit]
    if isinstance(obj, dict):
        return {k: _serialize(v, limit) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(x, limit) for x in obj]
    try:
        return str(obj)[:limit]
    except Exception:
        return repr(obj)[:limit]


# ── 辩论过程写文件 ─────────────────────────────────────────────────
_DEBATE_PROCESS_DIR = Path(__file__).parent / "agent_talk"


def _write_debate_process(state: dict, decision, trade_date: str) -> str:
    """将完整辩论过程写入中文文本文件，返回文件路径。"""
    _DEBATE_PROCESS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _DEBATE_PROCESS_DIR / f"spy_debate_process_{trade_date}.txt"

    analyst_reports = state.get("analyst_reports", {})
    inv_debate = state.get("investment_debate_state") or state.get("investment_debate") or {}
    risk_debate = state.get("risk_debate_state") or state.get("risk_debate") or {}

    lines = []
    lines.append("=" * 60)
    lines.append(f"  TradingAgents 多智能体辩论 · SPY  ·  日期: {trade_date}")
    lines.append("=" * 60)

    # ── 1. 分析师报告 ─────────────────────────────────────────────
    if analyst_reports:
        lines.append("\n【一、分析师报告摘要】")
        for name, report in analyst_reports.items():
            content = report if isinstance(report, str) else str(report)
            lines.append(f"\n  ▶ {name.upper()} 观点：")
            # 截取前800字
            for chunk in [content[i:i+400] for i in range(0, min(len(content), 800), 400)]:
                lines.append(f"    {chunk.strip()}")

    # ── 2. 多空辩论 ─────────────────────────────────────────────
    bull_hist = inv_debate.get("bull_history", [])
    bear_hist = inv_debate.get("bear_history", [])
    judge1 = inv_debate.get("judge_decision", "")
    lines.append("\n" + "-" * 60)
    lines.append("【二、多空博弈辩论】")
    lines.append("-" * 60)

    if bull_hist:
        lines.append("\n  🐂 多头研究员观点：")
        # bull_hist 是单字符列表，join后才是完整文本
        full_bull = ''.join(c if isinstance(c, str) else str(c) for c in bull_hist)
        for chunk in [full_bull[i:i+600] for i in range(0, min(len(full_bull), 3000), 600)]:
            lines.append(f"\n    {chunk.strip()}")
    else:
        lines.append("\n  🐂 多头研究员：无有效观点")

    if bear_hist:
        lines.append("\n\n  🐻 空头研究员观点：")
        full_bear = ''.join(c if isinstance(c, str) else str(c) for c in bear_hist)
        for chunk in [full_bear[i:i+600] for i in range(0, min(len(full_bear), 3000), 600)]:
            lines.append(f"\n    {chunk.strip()}")
    else:
        lines.append("\n\n  🐻 空头研究员：无有效观点")

    if judge1:
        lines.append(f"\n  ⚖️ 裁判判决：{str(judge1)[:800]}")

    # ── 3. 风险辩论 ─────────────────────────────────────────────
    cons_hist = risk_debate.get("conservative_history", [])
    agg_hist = risk_debate.get("aggressive_history", [])
    judge2 = risk_debate.get("judge_decision", "")
    lines.append("\n\n" + "-" * 60)
    lines.append("【三、风险辩论】")
    lines.append("-" * 60)

    if cons_hist:
        lines.append("\n  🛡️ 保守型风险辩论员：")
        full_cons = ''.join(c if isinstance(c, str) else str(c) for c in cons_hist)
        for chunk in [full_cons[i:i+600] for i in range(0, min(len(full_cons), 2000), 600)]:
            lines.append(f"\n    {chunk.strip()}")
    else:
        lines.append("\n  🛡️ 保守型风险辩论员：无有效观点")

    if agg_hist:
        lines.append("\n\n  ⚔️ 激进型风险辩论员：")
        full_agg = ''.join(c if isinstance(c, str) else str(c) for c in agg_hist)
        for chunk in [full_agg[i:i+600] for i in range(0, min(len(full_agg), 2000), 600)]:
            lines.append(f"\n    {chunk.strip()}")
    else:
        lines.append("\n\n  ⚔️ 激进型风险辩论员：无有效观点")

    if judge2:
        lines.append(f"\n  ⚖️ 风险裁判判决：{str(judge2)[:800]}")

    # ── 4. 最终决策 ─────────────────────────────────────────────
    decision_val = decision if isinstance(decision, str) else str(decision)
    lines.append("\n\n" + "=" * 60)
    lines.append("【四、最终交易决策】")
    lines.append("=" * 60)
    lines.append(f"\n  {decision_val}\n")

    # 写入文件
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        print(f"[Agents] 辩论过程写入失败: {e}")

    return str(out_path)


# ── 主分析函数 ─────────────────────────────────────────────────────
def analyze_agents_debate(trade_date: str, v: Dict[str, Any]) -> Dict[str, Any]:
    """
    P2 Strategy D: TradingAgents 多 Agent 辩论框架

    参数:
        trade_date: 分析日期（YYYY-MM-DD）
        v: 全局变量（此处未使用，TradingAgents 自行获取数据）

    返回:
        {
          "strategy":         "AGENTS_DEBATE",
          "trade_date":       trade_date,
          "market_regime":    str,    # BULLISH / BEARISH / NEUTRAL
          "regime_score":     int,    # -10 ~ +10（多空辩论强度）
          "timing_state":     str,    # OVERBOUGHT / OVERSOLD / NEUTRAL
          "timing_score":     int,    # -3 ~ +3
          "risk_score":       int,    # 0 ~ 10
          "target_exposure":  float,  # 0 ~ 100（%）
          "interpretation":   str,
          "signals":          list[str],
          "confidence":       float,  # 0 ~ 1
          "decision":         str,    # Buy / Hold / Sell（来自 Trader Agent）
          "bull_bear_score":  float,  # 多头辩论得分 -1 ~ +1
          "debate_text":      str,   # 裁判判决摘要
        }
    """
    cache_dir = "/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/fintech/agent_talk"
    cache_file = os.path.join(cache_dir, f"spy_decision_{trade_date}.json")

    # ── 已有缓存时直接读取 ──────────────────────────────────────
    if os.path.exists(cache_file):
        try:
            with open(cache_file, encoding="utf-8") as f:
                cached = json.load(f)
            decision_val = cached.get("decision", "Hold")
            inv = cached.get("investment_debate", {})
            risk = cached.get("risk_debate", {})
            bull_hist = inv.get("bull_history", [])
            bear_hist = inv.get("bear_history", [])
            judge_text = str(inv.get("judge_decision", ""))[:2000]

            regime, regime_score, timing, timing_score, risk_score, exposure = \
                _parse_decision(decision_val, bull_hist, bear_hist, judge_text)

            # 辩论过程文件路径（与 fresh run 相同路径）
            debate_file = str(Path(__file__).parent / "agent_talk" / f"spy_debate_process_{trade_date}.txt")
            # 缓存命中时也从缓存数据写辩论文件
            state_from_cache = {"investment_debate": inv, "risk_debate": risk}
            _write_debate_process(state_from_cache, decision_val, trade_date)

            return _build_result(
                trade_date, decision_val, regime, regime_score,
                timing, timing_score, risk_score, exposure,
                judge_text, bull_hist, bear_hist,
                debate_file=debate_file,
            )
        except Exception:
            pass  # 缓存损坏，重新运行

    # ── 无缓存，运行 TradingAgents ──────────────────────────────
    print(f"  [AGENTS] 运行 TradingAgents 辩论框架（首次运行较慢，约30-60秒）...")
    ta = _get_ta_graph()

    # 回溯30天数据足够辩论框架使用
    from datetime import timedelta
    start = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
    end = trade_date

    try:
        state, decision = ta.propagate("SPY", trade_date)
    except Exception as e:
        # Fallback: 返回中性结果
        return _fallback(trade_date, f"TradingAgents 运行失败: {e}")

    # ── 写辩论过程文件（中文）─────────────────────────────────────
    debate_file = _write_debate_process(state, decision, trade_date)
    print(f"  [AGENTS] 辩论过程: {debate_file}")

    # ── 解析辩论结果 ────────────────────────────────────────────
    inv_debate = state.get("investment_debate_state") or state.get("investment_debate") or {}
    risk_debate = state.get("risk_debate_state") or state.get("risk_debate") or {}

    bull_hist = inv_debate.get("bull_history", [])
    bear_hist = inv_debate.get("bear_history", [])
    judge_text = str(inv_debate.get("judge_decision", ""))[:2000]

    decision_val = decision if isinstance(decision, str) else str(decision)

    # ── 保存缓存 ────────────────────────────────────────────────
    try:
        os.makedirs(cache_dir, exist_ok=True)
        result_for_cache = {
            "ticker": "SPY",
            "date": trade_date,
            "decision": decision_val,
            "timestamp": datetime.now().isoformat(),
            "investment_debate": {
                "bull_history": [_serialize(m) for m in bull_hist],
                "bear_history": [_serialize(m) for m in bear_hist],
                "judge_decision": _serialize(inv_debate.get("judge_decision", "")),
            },
            "risk_debate": {
                "conservative_history": [_serialize(m) for m in risk_debate.get("conservative_history", [])],
                "aggressive_history":  [_serialize(m) for m in risk_debate.get("aggressive_history", [])],
                "judge_decision":      _serialize(risk_debate.get("judge_decision", "")),
            },
        }
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(result_for_cache, f, indent=2, ensure_ascii=False)
    except Exception:
        pass  # 缓存写入失败不影响返回

    regime, regime_score, timing, timing_score, risk_score, exposure = \
        _parse_decision(decision_val, bull_hist, bear_hist, judge_text)

    return _build_result(
        trade_date, decision_val, regime, regime_score,
        timing, timing_score, risk_score, exposure,
        judge_text, bull_hist, bear_hist,
        debate_file=debate_file,
    )


# ── 解析辩论输出 → 策略信号 ─────────────────────────────────────────
def _parse_decision(decision: str, bull_hist: list, bear_hist: list, judge_text: str):
    """
    从辩论决策中提取 regime / timing / risk / exposure
    """
    # 基础决策
    if decision in ("Buy", "BUY", "Long"):
        base_exposure = 80.0
        regime_base = "BULLISH"
        regime_score = 6
        timing_score = 2
        risk_score = 3
    elif decision in ("Sell", "SELL", "Short"):
        base_exposure = 10.0
        regime_base = "BEARISH"
        regime_score = -6
        timing_score = -2
        risk_score = 8
    else:  # Hold / Neutral
        base_exposure = 30.0
        regime_base = "NEUTRAL"
        regime_score = 0
        timing_score = 0
        risk_score = 5

    # ── 辩论深度调整 ───────────────────────────────────────────
    # 辩论历史长度反映分歧强度
    bull_len = len(bull_hist)
    bear_len = len(bear_hist)
    total_debate = bull_len + bear_len

    if total_debate > 0:
        bull_ratio = bull_len / total_debate  # 多头辩论参与度
    else:
        bull_ratio = 0.5

    # 辩论异常激烈（历史记录极多）→ 说明多空分歧大 → 降低仓位
    if total_debate > 10000:
        base_exposure *= 0.5
        risk_score = min(risk_score + 2, 10)
    elif total_debate > 5000:
        base_exposure *= 0.75

    # 从裁判判决文本提取关键词微调
    jt_lower = judge_text.lower()
    if any(k in jt_lower for k in ["overbought", "rsis", "stretched", "高估"]):
        timing_score = min(timing_score - 1, 3)
        risk_score = min(risk_score + 1, 10)
    if any(k in jt_lower for k in ["oversold", "低估", "attractive", "value"]):
        timing_score = max(timing_score + 1, -3)
        risk_score = max(risk_score - 1, 0)

    # Bullish ratio 调整
    if bull_ratio > 0.65:
        regime_score = min(regime_score + 2, 10)
        base_exposure = min(base_exposure * 1.1, 95)
    elif bull_ratio < 0.35:
        regime_score = max(regime_score - 2, -10)
        base_exposure = max(base_exposure * 0.6, 5)

    # Timing 状态
    if timing_score >= 2:
        timing = "BULL_CONFIRM"
    elif timing_score <= -2:
        timing = "BEAR_CONFIRM"
    else:
        timing = "NEUTRAL"

    # Regime 最终
    if regime_score >= 5:
        regime = "BULLISH"
    elif regime_score <= -5:
        regime = "BEARISH"
    else:
        regime = "NEUTRAL"

    return regime, regime_score, timing, timing_score, risk_score, base_exposure


def _build_result(trade_date: str, decision: str,
                  regime: str, regime_score: int,
                  timing: str, timing_score: int,
                  risk_score: int, exposure: float,
                  judge_text: str,
                  bull_hist: list, bear_hist: list,
                  debate_file: str = "") -> Dict[str, Any]:
    """构建标准 P2 策略输出结构"""

    # 多空得分
    total = len(bull_hist) + len(bear_hist)
    bull_bear_score = (len(bull_hist) / total * 2 - 1) if total > 0 else 0.0

    # 信号标签
    signals = []
    if regime in ("BULLISH",):
        signals.append("🐂 多头主导")
    elif regime in ("BEARISH",):
        signals.append("🐻 空头主导")
    else:
        signals.append("⚖️ 多空均衡")

    if timing == "BULL_CONFIRM":
        signals.append("✅ 多头确认")
    elif timing == "BEAR_CONFIRM":
        signals.append("🔴 空头确认")

    if risk_score >= 7:
        signals.append("⚠️ 高风险")
    elif risk_score <= 2:
        signals.append("🟢 低风险")

    signals.append(f"辩论决策: {decision}")
    if len(bull_hist) > 5000:
        signals.append("🔥 激烈辩论(分歧大)")

    # 解读文本
    interpretation = (
        f"AGENTS辩论框架决策：{decision} | "
        f"市场状态：{regime}(score={regime_score:+d}) | "
        f"择时：{timing}(score={timing_score:+d}) | "
        f"风险：{risk_score}/10 | "
        f"目标仓位：{exposure:.0f}% | "
        f"多空辩论比={len(bull_hist)}:{len(bear_hist)}"
    )

    # 置信度
    confidence = 0.5 + min(abs(regime_score) / 20, 0.3) + min(abs(timing_score) / 10, 0.2)
    confidence = round(min(confidence, 0.9), 2)

    return {
        "strategy":       "AGENTS_DEBATE",
        "trade_date":     trade_date,
        "market_regime":  regime,
        "regime_score":   regime_score,
        "timing_state":   timing,
        "timing_score":   timing_score,
        "risk_score":     risk_score,
        "target_exposure": round(exposure, 1),
        "interpretation": interpretation,
        "signals":        signals,
        "confidence":     confidence,
        # 额外字段
        "decision":       decision,
        "bull_bear_score": round(bull_bear_score, 3),
        "debate_text":    judge_text[:8000],
        "bull_count":     len(bull_hist),
        "bear_count":     len(bear_hist),
        "debate_file":    debate_file,
    }


def _fallback(trade_date: str, error: str) -> Dict[str, Any]:
    return {
        "strategy":       "AGENTS_DEBATE",
        "trade_date":     trade_date,
        "market_regime":  "NEUTRAL",
        "regime_score":   0,
        "timing_state":   "NEUTRAL",
        "timing_score":   0,
        "risk_score":     5,
        "target_exposure": 30.0,
        "interpretation": f"AGENTS辩论框架异常: {error}",
        "signals":        ["⚠️ AGENTS异常"],
        "confidence":     0.3,
        "decision":       "Hold",
        "bull_bear_score": 0.0,
        "debate_text":    error,
        "bull_count":     0,
        "bear_count":     0,
        "debate_file":    "",
    }
