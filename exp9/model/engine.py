#!/usr/bin/env python3
"""
G4 专家决策引擎 — 统一入口
================================================
支持两种输入：
  1. 图片文件（K线截图）→ MiniMax Vision API 理解图表
  2. JSON K线数据  → 技术指标计算 + 规则匹配

输入：
  - analyze_image(path)       ：图片文件路径
  - analyze_klines(json_path)：JSON K线文件路径（美股投资洞察分析格式）
  - analyze_klines_dict(data) ：Python dict（直接传入）

输出：
  - DecisionResult（与 analyze_pattern 格式一致）
"""

from __future__ import annotations
import json
import subprocess
import sys
import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

# ── 项目路径 ──────────────────────────────────────────────────────────────────
EXP9_ROOT = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/exp9")
MODEL_DIR  = EXP9_ROOT / "model"
KLINES_ROOT = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines")

# ── MiniMax Vision 配置 ───────────────────────────────────────────────────────
MCP_BIN   = os.path.expanduser("~/.local/share/uv/tools/minimax-coding-plan-mcp/bin/minimax-coding-plan-mcp")
MCP_HOST  = "https://api.minimaxi.com"
MCP_KEY   = os.environ.get("MINIMAX_API_KEY", "")

# 支持的图片格式
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif"}

# ══════════════════════════════════════════════════════════════════════════════
# 数据结构（复用 p18 引擎）
# ══════════════════════════════════════════════════════════════════════════════

class Direction(Enum):
    LONG  = "LONG"
    SHORT = "SHORT"
    WATCH = "WATCH"
    NONE  = "NONE"

@dataclass
class PatternMatch:
    name: str
    direction: Direction
    confidence: str
    signal: str
    entry_condition: list[str] = field(default_factory=list)
    stop_loss: Optional[str] = None
    target: Optional[str] = None
    risk: list[str] = field(default_factory=list)

@dataclass
class DecisionResult:
    video: str = ""
    primary_signal: Direction = Direction.NONE
    confidence: str = "低"
    matched_patterns: list[PatternMatch] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    risk_warnings: list[str] = field(default_factory=list)
    summary: str = ""
    # 输入来源
    input_type: str = ""   # "image" / "klines"
    input_source: str = "" # 文件路径或股票代码

# ══════════════════════════════════════════════════════════════════════════════
# 内部工具
# ══════════════════════════════════════════════════════════════════════════════

def _run_mcp_vision(image_path: str, prompt: str) -> str:
    """
    通过 subprocess 调用 MiniMax Vision API。
    返回：API 输出的原始字符串（不含 jsonrpc 包装）。
    """
    # 构造 MCP JSON-RPC 请求
    tool_call = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "understand_image",
            "arguments": {
                "prompt": prompt,
                "image_source": image_path,
            }
        }
    }

    env = os.environ.copy()
    env["MINIMAX_API_HOST"] = MCP_HOST
    env["MINIMAX_API_KEY"]  = MCP_KEY

    proc = subprocess.Popen(
        [MCP_BIN, "-y"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    # 先发 initialize
    init = {
        "jsonrpc": "2.0", "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "g4-engine", "version": "1.0"},
        }
    }

    import json as _json
    req = _json.dumps(init) + "\n" + _json.dumps(tool_call) + "\n"
    out, err = proc.communicate(input=req.encode(), timeout=60)

    stderr = err.decode(errors="replace").strip()
    if stderr and "Traceback" in stderr:
        raise RuntimeError(f"MCP Error:\n{stderr}")

    # 解析最后一行（tool result）
    lines = [l for l in out.decode(errors="replace").splitlines() if l.strip()]
    for line in reversed(lines):
        try:
            resp = _json.loads(line)
            if resp.get("id") == 2 and "result" in resp:
                content = resp["result"].get("content", [])
                if content and isinstance(content, list):
                    return content[0].get("text", "")
        except Exception:
            continue

    raise RuntimeError(f"Unexpected MCP output:\n{out.decode(errors='replace')[:500]}")


def _call_vision_api(image_path: str, extra_prompt: str = "") -> dict:
    """
    发送图片到 MiniMax Vision，返回解析后的 dict。
    结构：{chart_type, market_env, patterns, signals, kline_shape, advice, confidence}
    """
    prompt = (
        "你是一位专业的价格行为（Price Action）分析师。"
        "请详细描述这张K线图表的内容，并提取以下结构化信息：\n\n"
        "1. 图表类型：属于哪类K线图？（如：日K、周K、分时K、均线图等）\n"
        "2. 市场环境：当前趋势是什么？（如：上升趋势、下降趋势、震荡、横盘）\n"
        "3. K线形态：发现了哪些具体形态？（如：Pin Bar、Inside Bar、旗形、三角形、楔形、吞没形态等）\n"
        "4. 信号K线：是否有信号K线？具体描述（方向：大阳线/大阴线、实体大小、上下影线）\n"
        "5. 关键价位：支撑位、阻力位在哪里？\n"
        "6. 成交量：成交量是否配合？（放量/缩量）\n"
        "7. 你的初步判断：根据图表，当前的交易信号是什么？（买入/卖出/观望）\n"
        "8. 置信度：这个信号的置信度高吗？（高/中/低）\n\n"
        "请用简洁专业的中文输出，结构化地呈现你的分析。\n\n"
        f"附加关注点（如果适用）：{extra_prompt}"
    )

    raw = _run_mcp_vision(image_path, prompt)

    # 解析：把自然语言转成 dict（简化处理，直接返回原文）
    return {
        "raw_description": raw,
        "chart_type": _extract_field(raw, "图表类型"),
        "market_env": _extract_field(raw, "市场环境"),
        "patterns": _extract_list(raw, ["形态", "形态有", "发现"]),
        "signals": _extract_list(raw, ["信号", "买入", "卖出", "做多", "做空", "观望"]),
        "advice": _extract_field(raw, "初步判断") or _extract_field(raw, "交易信号"),
        "confidence": _extract_field(raw, "置信度") or "中",
    }

def _extract_field(text: str, keyword: str) -> str:
    """提取关键字后面的内容（到换行或句号为止）"""
    pattern = rf"{keyword}[：:]\s*([^\n。.]+)"
    m = re.search(pattern, text)
    return m.group(1).strip() if m else ""

def _extract_list(text: str, keywords: list[str]) -> list[str]:
    """提取包含任一关键字的行"""
    results = []
    for line in text.split("\n"):
        if any(kw in line for kw in keywords):
            cleaned = re.sub(r"^\d+[.)、\s]+", "", line.strip())
            if len(cleaned) > 3:
                results.append(cleaned)
    return results

# ══════════════════════════════════════════════════════════════════════════════
# K线技术指标计算
# ══════════════════════════════════════════════════════════════════════════════

def _load_klines(path_or_data) -> list[dict]:
    """加载K线数据（文件路径或 dict）"""
    if isinstance(path_or_data, (str, Path)):
        with open(path_or_data) as f:
            d = json.load(f)
    else:
        d = path_or_data
    return d["data"] if "data" in d else d


def _calc_indicators(bars: list[dict]) -> dict:
    """计算常用技术指标"""
    n = len(bars)
    closes  = [b["close"] for b in bars]
    highs   = [b["high"]  for b in bars]
    lows    = [b["low"]   for b in bars]
    volumes = [b.get("vol", 0) for b in bars]

    # ── 简单移动平均 ────────────────────────────────────────────
    def sma(data, period):
        result = []
        for i in range(len(data)):
            if i < period - 1:
                result.append(None)
            else:
                result.append(sum(data[i-period+1:i+1]) / period)
        return result

    ma5  = sma(closes, 5)
    ma10 = sma(closes, 10)
    ma20 = sma(closes, 20)

    # ── RSI(14) ───────────────────────────────────────────────
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

    # ── 最近 N 根K线 ──────────────────────────────────────────
    def last_n(arr, n=5):
        valid = [x for x in arr[-n:] if x is not None]
        return valid[-1] if valid else None

    def last_n_all(arr, n=5):
        return [x for x in arr[-n:] if x is not None]

    last_close = closes[-1] if closes else None
    last_high  = max(highs[-5:]) if highs else None
    last_low   = min(lows[-5:])  if lows  else None

    # ── 趋势判断 ──────────────────────────────────────────────
    ma5_last  = last_n(ma5)
    ma10_last = last_n(ma10)
    ma20_last = last_n(ma20)

    if all(x is not None for x in [ma5_last, ma10_last, ma20_last]):
        if ma5_last > ma10_last > ma20_last:
            trend = "上升趋势"
        elif ma5_last < ma10_last < ma20_last:
            trend = "下降趋势"
        else:
            trend = "震荡/混乱"
    else:
        trend = "数据不足"

    # ── 均线排列 ──────────────────────────────────────────────
    ma_alignment = []
    if all(x is not None for x in [ma5_last, ma10_last]):
        if ma5_last > ma10_last:
            ma_alignment.append("MA5>MA10")
        else:
            ma_alignment.append("MA5<MA10")
    if ma20_last is not None and ma10_last is not None:
        if ma10_last > ma20_last:
            ma_alignment.append("MA10>MA20")
        else:
            ma_alignment.append("MA10<MA20")

    # ── 成交量分析 ────────────────────────────────────────────
    vol_avg5 = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else sum(volumes)/len(volumes) if volumes else 0
    vol_now  = volumes[-1] if volumes else 0
    vol_ratio = round(vol_now / vol_avg5, 2) if vol_avg5 > 0 else 1.0
    volume_signal = "放量" if vol_ratio > 1.3 else ("缩量" if vol_ratio < 0.7 else "正常")

    # ── 波动率 ────────────────────────────────────────────────
    if len(closes) >= 20:
        ret_std = (sum((c - sum(closes[-20:])/20)**2 for c in closes[-20:]) / 20) ** 0.5
        avg_close = sum(closes[-20:]) / 20
        volatility = round(ret_std / avg_close * 100, 2) if avg_close > 0 else 0
    else:
        volatility = 0

    # ── RSI 状态 ──────────────────────────────────────────────
    rsi_last = last_n(rsi14)
    if rsi_last is not None:
        if rsi_last > 70:
            rsi_status = "RSI极度超买"
        elif rsi_last < 30:
            rsi_status = "RSI极度超卖"
        elif rsi_last > 55:
            rsi_status = "RSI偏强"
        elif rsi_last < 45:
            rsi_status = "RSI偏弱"
        else:
            rsi_status = "RSI中性"
    else:
        rsi_status = "RSI数据不足"

    return {
        "latest_bar": {
            "date":  bars[-1]["date"]  if bars else None,
            "close": last_close,
            "high":  last_high,
            "low":   last_low,
        },
        "trend":         trend,
        "ma5":           ma5_last,
        "ma10":          ma10_last,
        "ma20":          ma20_last,
        "ma_alignment":  ma_alignment,
        "rsi14":         rsi_last,
        "rsi_status":    rsi_status,
        "volume_now":    vol_now,
        "volume_avg5":   round(vol_avg5, 0),
        "volume_ratio":  vol_ratio,
        "volume_signal": volume_signal,
        "volatility_20d": volatility,
        "bars_count": n,
    }


def _klines_to_text(indicators: dict) -> str:
    """把指标计算结果转成人类可读文本"""
    ib = indicators
    lines = [
        f"日期：{ib['latest_bar']['date']}",
        f"最新价：{ib['latest_bar']['close']}",
        f"趋势：{ib['trend']}",
        f"均线排列：{'，'.join(ib['ma_alignment']) if ib['ma_alignment'] else '无'}",
        f"MA5={ib['ma5']}，MA10={ib['ma10']}，MA20={ib['ma20']}",
        f"RSI(14)={ib['rsi14']}（{ib['rsi_status']}）",
        f"成交量：{ib['volume_signal']}（当前{ib['volume_now']:.0f}，5日均值{ib['volume_avg5']:.0f}，比值{ib['volume_ratio']}）",
        f"20日波动率：{ib['volatility_20d']}%",
    ]
    return "；".join(lines)

# ══════════════════════════════════════════════════════════════════════════════
# 规则匹配（K线数据版）
# ══════════════════════════════════════════════════════════════════════════════

def _match_kline_rules(indicators: dict) -> list[tuple[str, Direction, str, list[str]]]:
    """
    基于技术指标值匹配 P18 规则。
    返回：list of (规则名, 方向, 信号, 理由列表)
    """
    matches = []
    trend    = indicators["trend"]
    rsi      = indicators["rsi14"]
    ma_ali   = indicators["ma_alignment"]
    vol_sig  = indicators["volume_signal"]
    vol_ratio = indicators["volume_ratio"]
    rsi_stat = indicators["rsi_status"]

    # ── 均线多头/空头排列 ────────────────────────────────────
    if "MA5>MA10" in ma_ali and "MA10>MA20" in ma_ali:
        matches.append((
            "均线多头排列（上升趋势）",
            Direction.LONG,
            "顺势做多，MA5支撑买入",
            ["均线多头排列", "MA5>MA10>MA20"]
        ))
    elif "MA5<MA10" in ma_ali and "MA10<MA20" in ma_ali:
        matches.append((
            "均线空头排列（下降趋势）",
            Direction.SHORT,
            "顺势做空，反弹至MA5/MA10受阻做空",
            ["均线空头排列", "MA5<MA10<MA20"]
        ))

    # ── RSI 超买/超卖 ────────────────────────────────────────
    if rsi is not None:
        if rsi < 30:
            matches.append((
                "RSI极度超卖",
                Direction.LONG,
                "关注反弹机会，等待反转信号",
                [f"RSI={rsi}，极度超卖"]
            ))
        elif rsi > 70:
            matches.append((
                "RSI极度超买",
                Direction.SHORT,
                "关注回调或做空机会",
                [f"RSI={rsi}，极度超买"]
            ))

    # ── 放量配合 ────────────────────────────────────────────
    if vol_ratio > 1.5 and trend == "上升趋势":
        matches.append((
            "放量突破（量价配合）",
            Direction.LONG,
            "放量确认趋势，做多",
            [f"放量{vol_ratio}倍，量价齐升"]
        ))
    elif vol_ratio > 1.5 and trend == "下降趋势":
        matches.append((
            "放量下跌（恐慌抛售）",
            Direction.SHORT,
            "放量确认下跌，做空",
            [f"放量{vol_ratio}倍，量价齐跌"]
        ))

    # ── 震荡市场 ────────────────────────────────────────────
    if trend == "震荡/混乱":
        matches.append((
            "震荡市场（无趋势）",
            Direction.WATCH,
            "观望为主，不追涨杀跌",
            ["趋势不明", "等待突破确认"]
        ))

    return matches

# ══════════════════════════════════════════════════════════════════════════════
# 统一决策引擎
# ══════════════════════════════════════════════════════════════════════════════

def _merge_results(
    kline_text: str,
    kline_indicators: dict,
    kline_matches: list,
    vision_result: Optional[dict] = None,
) -> DecisionResult:
    """
    合并 K线指标 + Vision 图片分析的结果，输出统一 DecisionResult。
    """
    from model.p18_second_leg_trap import analyze_pattern, Direction as Dir, PatternMatch

    # 构建模拟的 "chart_description"
    chart_desc = kline_text
    market_env = kline_indicators["trend"]
    patterns   = []
    signals    = []

    if vision_result:
        vd = vision_result
        if vd.get("market_env"):
            market_env = vd["market_env"]
        patterns = vd.get("patterns", [])
        signals  = vd.get("signals", [])
        chart_desc += "\n" + vd.get("raw_description", "")

    # ── 先跑 P18 规则引擎（文本分析）───────────────────────
    text_result = analyze_pattern(
        chart_description=chart_desc,
        market_environment=market_env,
        patterns_found=patterns,
        kline_signals=signals,
    )

    # ── 合并 K线指标的规则匹配 ──────────────────────────────
    for rule_name, direction, signal, _rule_reasons in kline_matches:
        text_result.matched_patterns.append(PatternMatch(
            name=rule_name,
            direction=direction,
            confidence="中",
            signal=signal,
        ))

    # ── 更新方向（综合两个来源，取高优先级）────────────────
    all_dirs = [m.direction for m in text_result.matched_patterns]
    priority = {Direction.SHORT: 3, Direction.LONG: 2, Direction.WATCH: 1}
    if all_dirs:
        text_result.primary_signal = max(all_dirs, key=lambda d: priority.get(d, 0))
        text_result.confidence = max(
            text_result.matched_patterns,
            key=lambda m: {"极高": 4, "高": 3, "中": 2, "低": 1}.get(m.confidence, 0)
        ).confidence

    text_result.input_type = "image+klines" if vision_result else "klines"
    return text_result


# ══════════════════════════════════════════════════════════════════════════════
# 公开 API
# ══════════════════════════════════════════════════════════════════════════════

def analyze_image(image_path: str) -> DecisionResult:
    """
    输入：图片文件路径（支持 jpg/png/webp/bmp/gif/tiff）
    流程：图片 → MiniMax Vision API → 结构化描述 → P18规则引擎 → 决策
    """
    p = Path(image_path)
    if not p.exists():
        raise FileNotFoundError(f"图片不存在：{image_path}")
    if p.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(f"不支持的图片格式：{p.suffix}，支持：{IMAGE_EXTENSIONS}")

    # 1. Vision API 分析图片
    vision = _call_vision_api(str(p.resolve()))

    # 2. 加载 K线数据（如有同名文件）
    kline_matches = []
    kline_indicators = {}
    kline_text = ""

    # 尝试找同名或同目录下的 kline 文件
    stock_code = p.stem.upper()  # 文件名（无扩展名）
    kline_file = KLINES_ROOT / f"{stock_code}_1d.json"
    if not kline_file.exists():
        # 尝试上级目录
        kline_file = KLINES_ROOT / f"{stock_code.replace('US', '_US')}_1d.json"

    if kline_file.exists():
        bars = _load_klines(kline_file)
        kline_indicators = _calc_indicators(bars)
        kline_text = _klines_to_text(kline_indicators)
        kline_matches = _match_kline_rules(kline_indicators)
    else:
        # 无K线数据时，用纯Vision描述构建指标文本
        kline_text = vision.get("raw_description", "")
        kline_indicators = {}

    # 3. 合并结果
    result = _merge_results(kline_text, kline_indicators, kline_matches, vision)
    result.input_type  = "image"
    result.input_source = str(p.resolve())
    return result


def analyze_klines(stock_code: str, period: str = "1d") -> DecisionResult:
    """
    输入：股票代码 + 周期（如 "1d", "1wk"）
    流程：加载K线JSON → 计算指标 → 规则匹配 → 决策
    """
    kline_file = KLINES_ROOT / f"{stock_code}_{period}.json"
    if not kline_file.exists():
        raise FileNotFoundError(f"K线文件不存在：{kline_file}")

    bars = _load_klines(kline_file)
    if not bars:
        raise ValueError(f"K线数据为空：{kline_file}")

    indicators = _calc_indicators(bars)
    kline_text = _klines_to_text(indicators)
    matches    = _match_kline_rules(indicators)

    result = _merge_results(kline_text, indicators, matches, vision_result=None)
    result.input_type   = "klines"
    result.input_source = f"{stock_code}_{period}"
    return result


def analyze_klines_dict(data: dict) -> DecisionResult:
    """
    输入：Python dict（直接传入 K线数据）
    格式：{"data": [{date, open, high, low, close, vol}, ...]}
    """
    bars = _load_klines(data)
    if not bars:
        raise ValueError("K线数据为空")

    indicators = _calc_indicators(bars)
    kline_text = _klines_to_text(indicators)
    matches    = _match_kline_rules(indicators)

    result = _merge_results(kline_text, indicators, matches, vision_result=None)
    result.input_type   = "klines_dict"
    result.input_source = "dict_input"
    return result


# ══════════════════════════════════════════════════════════════════════════════
# CLI 演示
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="G4 专家决策引擎")
    parser.add_argument("--image", help="图片文件路径")
    parser.add_argument("--kline", help="股票代码（如 AAPL）")
    parser.add_argument("--period", default="1d", help="K线周期（默认1d）")
    args = parser.parse_args()

    if args.image:
        r = analyze_image(args.image)
        print(f"\n📊 输入类型：图片")
        print(f"📁 文件：{r.input_source}")
        print(f"\n🎯 信号：{r.primary_signal.value}（置信度：{r.confidence}）")
        print(f"📝 理由：")
        for x in r.reasons:
            print(f"   · {x}")
        if r.matched_patterns:
            print(f"\n🔍 匹配规则：")
            for p in r.matched_patterns:
                print(f"   · [{p.confidence}] {p.name}: {p.signal}")
        if r.risk_warnings:
            print(f"\n⚠️ 风险提示：")
            for w in r.risk_warnings:
                print(f"   · {w}")

    elif args.kline:
        r = analyze_klines(args.kline.upper(), args.period)
        print(f"\n📊 输入类型：K线数据")
        print(f"📁 文件：{r.input_source}")
        print(f"\n🎯 信号：{r.primary_signal.value}（置信度：{r.confidence}）")
        print(f"📝 理由：")
        for x in r.reasons:
            print(f"   · {x}")
        if r.matched_patterns:
            print(f"\n🔍 匹配规则：")
            for p in r.matched_patterns:
                print(f"   · [{p.confidence}] {p.name}: {p.signal}")
        if r.risk_warnings:
            print(f"\n⚠️ 风险提示：")
            for w in r.risk_warnings:
                print(f"   · {w}")

    else:
        # 内置 demo
        print("G4 专家决策引擎 · Demo")
        print("=" * 50)

        # Demo 1: K线数据
        print("\n📈 Demo 1：AAPL 日K")
        try:
            r = analyze_klines("AAPL", "1d")
            print(f"信号：{r.primary_signal.value} | 置信度：{r.confidence}")
            print(f"理由：{r.reasons}")
            print(f"匹配：{[p.name for p in r.matched_patterns]}")
        except Exception as e:
            print(f"（AAPL数据不存在，跳过）{e}")

        # Demo 2: 指标计算
        print("\n📊 Demo 2：指标计算")
        # 21根K线（足够计算MA5/MA10/MA20）
        sample = {
            "data": [
                {"date":"2026-04-10","open":170,"high":172,"low":169,"close":171,"vol":40000000},
                {"date":"2026-04-13","open":171,"high":173,"low":170,"close":172,"vol":42000000},
                {"date":"2026-04-14","open":172,"high":174,"low":171,"close":173,"vol":43000000},
                {"date":"2026-04-15","open":173,"high":175,"low":172,"close":174,"vol":44000000},
                {"date":"2026-04-16","open":174,"high":177,"low":173,"close":176,"vol":50000000},
                {"date":"2026-04-17","open":176,"high":179,"low":175,"close":178,"vol":52000000},
                {"date":"2026-04-20","open":178,"high":180,"low":177,"close":179,"vol":48000000},
                {"date":"2026-04-21","open":179,"high":181,"low":178,"close":180,"vol":51000000},
                {"date":"2026-04-22","open":180,"high":182,"low":179,"close":181,"vol":49000000},
                {"date":"2026-04-23","open":181,"high":183,"low":180,"close":182,"vol":50000000},
                {"date":"2026-04-24","open":182,"high":185,"low":181,"close":184,"vol":55000000},
                {"date":"2026-04-27","open":184,"high":186,"low":183,"close":185,"vol":53000000},
                {"date":"2026-04-28","open":185,"high":187,"low":184,"close":186,"vol":52000000},
                {"date":"2026-04-29","open":186,"high":188,"low":185,"close":187,"vol":54000000},
                {"date":"2026-04-30","open":187,"high":190,"low":186,"close":189,"vol":60000000},
                {"date":"2026-05-01","open":189,"high":191,"low":188,"close":190,"vol":58000000},
                {"date":"2026-05-04","open":190,"high":193,"low":189,"close":192,"vol":65000000},
                {"date":"2026-05-05","open":192,"high":195,"low":191,"close":194,"vol":70000000},
                {"date":"2026-05-06","open":194,"high":198,"low":193,"close":197,"vol":80000000},
                {"date":"2026-05-07","open":197,"high":200,"low":196,"close":199,"vol":85000000},
                {"date":"2026-05-08","open":199,"high":202,"low":198,"close":201,"vol":90000000},
            ]
        }
        r = analyze_klines_dict(sample)
        print(f"信号：{r.primary_signal.value} | 置信度：{r.confidence}")
        print(f"匹配：{[p.name for p in r.matched_patterns]}")
        print("✅ Engine demo 完成")
