#!/usr/bin/env python3
"""
SPY Analysis using TradingAgents + MiniMax
分析日期：2026-05-14（最后完整交易日）

多 Agent 辩论框架：Market Analyst → News Analyst → Fundamentals Analyst
 → Bull/Bear Researcher 辩论 → Risk Debater 辩论 → Research Manager 综合 → Trader 最终决策
"""
import json, sys, os, time
from datetime import datetime

# ══════════════════════════════════════════════════════════════
# PATCH 0: 拦截所有 yfinance 调用 → SPY 走本地缓存
# ══════════════════════════════════════════════════════════════
LOCAL_KLINE_DIR = "/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines"

import pandas as pd

def _load_local_kline(symbol, start_date, end_date):
    """返回 CSV 格式的 OHLCV 数据（SPY 专用）。"""
    path = os.path.join(LOCAL_KLINE_DIR, f"{symbol.upper()}_1d.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        raw = json.load(f)
    records = [r for r in raw["data"] if start_date <= r["date"] <= end_date]
    if not records:
        return None
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
              f"# Data source: local cache (yfinance bypassed)\n\n")
    return header + df.to_csv()

# Patch get_YFin_data_online
import tradingagents.dataflows.y_finance as yf_module
_orig_get_YFin = yf_module.get_YFin_data_online
def _patched_get_YFin(symbol, start_date, end_date):
    if symbol.upper() == "SPY":
        data = _load_local_kline(symbol, start_date, end_date)
        if data:
            return data
    return _orig_get_YFin(symbol, start_date, end_date)
yf_module.get_YFin_data_online = _patched_get_YFin

# Patch route_to_vendor
import tradingagents.dataflows.interface as interface_module
_orig_route = interface_module.route_to_vendor
def _patched_route(method, *args, **kwargs):
    if method == "get_stock_data" and len(args) >= 3:
        symbol, start_date, end_date = args[0], args[1], args[2]
        if symbol.upper() == "SPY":
            data = _load_local_kline(symbol, start_date, end_date)
            if data:
                return data
    return _orig_route(method, *args, **kwargs)
interface_module.route_to_vendor = _patched_route

# Patch yfinance_news（新闻返回空，避免报错中断辩论流程）
import tradingagents.dataflows.yfinance_news as yf_news
_orig_news  = yf_news.get_news_yfinance
_orig_gnews = yf_news.get_global_news_yfinance
def _patched_news(ticker, start, end, max_items=None):
    return "[yfinance 限速中，新闻数据暂不可用]"
def _patched_gnews(lookback_days, max_items=None):
    return "[yfinance 限速中，全球新闻数据暂不可用]"
yf_news.get_news_yfinance        = _patched_news
yf_news.get_global_news_yfinance = _patched_gnews

# ══════════════════════════════════════════════════════════════
# PATCH 1: 移除 reasoning_split（MiniMax API 不兼容）
# ══════════════════════════════════════════════════════════════
import tradingagents.llm_clients.openai_client as oai_client
_oai_get_payload = oai_client.MinimaxChatOpenAI._get_request_payload
def _patched_payload(self, input_, *, stop=None, **kwargs):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI._get_request_payload(self, input_, stop=stop, **kwargs)
oai_client.MinimaxChatOpenAI._get_request_payload = _patched_payload

# ══════════════════════════════════════════════════════════════
# 2. Config
# ══════════════════════════════════════════════════════════════
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config.update({
    "llm_provider":       "minimax-cn",
    "backend_url":        "https://api.minimaxi.com/v1",
    "deep_think_llm":     "MiniMax-M2.7",
    "quick_think_llm":    "MiniMax-M2.7-highspeed",
    "output_language":    "Chinese",
    "max_debate_rounds":  1,      # 牛市 vs 熊市辩论轮数
    "max_risk_discuss_rounds": 1, # 风险辩论轮数
    "checkpoint_enabled": False,
    "data_vendors": {
        "core_stock_apis":     "yfinance",
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

print(f"\n{'='*60}")
print(f" TradingAgents 多 Agent 辩论框架初始化")
print(f" 辩论节点: Market Analyst → Fundamentals Analyst")
print(f"         → Bull Researcher vs Bear Researcher")
print(f"         → Conservative vs Aggressive Risk Debater")
print(f"         → Research Manager → Trader")
print(f"{'='*60}\n")

ta = TradingAgentsGraph(
    selected_analysts=["market", "fundamentals"],  # 市场+基本面（新闻数据限速中）
    debug=True,
    config=config,
)

TICKER     = "SPY"
TRADE_DATE = "2026-05-14"

print(f"{'='*60}")
print(f"开始 SPY 多 Agent 辩论分析 | 日期: {TRADE_DATE}")
print(f"{'='*60}\n")

state, decision = ta.propagate(TICKER, TRADE_DATE)

# ══════════════════════════════════════════════════════════════
# 3. 提取并展示完整辩论过程
# ══════════════════════════════════════════════════════════════

# 从 state 中提取辩论内容
inv_debate = state.get("investment_debate_state", {})
risk_debate = state.get("risk_debate_state", {})

# Analyst reports
analyst_reports = state.get("analyst_reports", {})

print(f"\n{'='*60}")
print(f"📊 各 Analyst 分析师报告摘要:")
print(f"{'='*60}")
for name, report in analyst_reports.items():
    print(f"\n--- {name.upper()} ---")
    # 打印摘要（前200字）
    if isinstance(report, str):
        summary = report[:500] + "..." if len(report) > 500 else report
        print(summary)
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False)[:500])

print(f"\n{'='*60}")
print(f"🐂 Bull Researcher 多头研究员观点:")
print(f"{'='*60}")
bull_hist = inv_debate.get("bull_history", [])
for i, msg in enumerate(bull_hist):
    print(f"\n[Round {i+1}]")
    if isinstance(msg, dict):
        content = msg.get("content", str(msg))
    else:
        content = str(msg)
    print(content[:800] if len(str(content)) > 800 else content)

print(f"\n{'='*60}")
print(f"🐻 Bear Researcher 空头研究员观点:")
print(f"{'='*60}")
bear_hist = inv_debate.get("bear_history", [])
for i, msg in enumerate(bear_hist):
    print(f"\n[Round {i+1}]")
    if isinstance(msg, dict):
        content = msg.get("content", str(msg))
    else:
        content = str(msg)
    print(content[:800] if len(str(content)) > 800 else content)

print(f"\n{'='*60}")
print(f"⚖️ Investment Debate Judge 裁判判决:")
print(f"{'='*60}")
judge1 = inv_debate.get("judge_decision", "无")
print(judge1[:1000] if len(str(judge1)) > 1000 else judge1)

print(f"\n{'='*60}")
print(f"🛡️ Conservative Risk Debater 保守型风险辩论:")
print(f"{'='*60}")
cons_hist = risk_debate.get("conservative_history", [])
for i, msg in enumerate(cons_hist):
    print(f"\n[Round {i+1}]")
    if isinstance(msg, dict):
        content = msg.get("content", str(msg))
    else:
        content = str(msg)
    print(content[:800] if len(str(content)) > 800 else content)

print(f"\n{'='*60}")
print(f"⚔️ Aggressive Risk Debater 激进型风险辩论:")
print(f"{'='*60}")
agg_hist = risk_debate.get("aggressive_history", [])
for i, msg in enumerate(agg_hist):
    print(f"\n[Round {i+1}]")
    if isinstance(msg, dict):
        content = msg.get("content", str(msg))
    else:
        content = str(msg)
    print(content[:800] if len(str(content)) > 800 else content)

print(f"\n{'='*60}")
print(f"⚖️ Risk Debate Judge 风险裁判判决:")
print(f"{'='*60}")
judge2 = risk_debate.get("judge_decision", "无")
print(judge2[:1000] if len(str(judge2)) > 1000 else judge2)

print(f"\n{'='*60}")
print(f"📋 多 Agent 辩论最终决策:")
print(f"{'='*60}")
print(json.dumps(decision, indent=2, ensure_ascii=False))

# ══════════════════════════════════════════════════════════════
# 4. 保存完整结果（含辩论过程）- 修复版
# ══════════════════════════════════════════════════════════════
out_path = f"/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/fintech/agent_talk/spy_decision_{TRADE_DATE}.json"

def _serialize(obj, limit=4000):
    """安全序列化对象，截断过长内容。"""
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

result = {
    "ticker": TICKER,
    "date": TRADE_DATE,
    "decision": decision,
    "timestamp": datetime.now().isoformat(),
    # 分析师报告
    "analyst_reports": {
        name: _serialize(rep) for name, rep in analyst_reports.items()
    },
    # 投资辩论（多空博弈）
    "investment_debate": {
        "bull_history": [_serialize(m) for m in bull_hist],
        "bear_history": [_serialize(m) for m in bear_hist],
        "judge_decision": _serialize(judge1),
    },
    # 风险辩论（保守 vs 激进）
    "risk_debate": {
        "conservative_history": [_serialize(m) for m in cons_hist],
        "aggressive_history": [_serialize(m) for m in agg_hist],
        "neutral_history": [_serialize(m) for m in risk_debate.get("neutral_history", [])],
        "judge_decision": _serialize(judge2),
    },
    # 原始 state 关键字段（用于调试）
    "state_keys": list(state.keys()) if isinstance(state, dict) else [],
}

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
print(f"\n💾 完整辩论记录已保存: {out_path}")

# 同时打印文件内容供确认
print(f"\n📄 文件内容预览（前500字）:")
with open(out_path) as f:
    content = f.read()
print(content[:500])
