#!/usr/bin/env python3
"""
p_buy_filter_report.py — Brooks 五层买入过滤 HTML 详细报告生成器
===============================================================
为每只候选股票生成包含字幕原文引用的详细 HTML 报告。

 Brooks 字幕原文索引：
    P07：信号K线 / Buy Stop / 趋势K线 vs 震荡K线
    P09：82%规则 / 背景>>信号 / Bread & Butter
    P05：H1/L1数K线 / 回调买入 / 50%回撤
    P10：好Wedge vs 坏Wedge
    P11：顺大逆小 / Wedge失败=123
    P12：Parabolic Wedge / Bad Follow-Through
    P13：Measured Move / 止盈目标
    P02：牛市四阶段 / 50%回撤原则 / 止损位置
    P16：盈亏比 / 1%仓位

用法：
    python3 p_buy_filter_report.py XLE      # 生成 XLE 单股报告
    python3 p_buy_filter_report.py --top5  # 生成 Top5 股票报告
"""

import json, sys, os
from pathlib import Path
from datetime import date
from typing import Optional

BASE = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE / "exp9" / "model" / "experts"))
from p_buy_filter import load_klines, BuyFilterEngine

def _make_kline_json(bars: list, lookback: int = 60) -> list:
    """将 bars 转成 TradingView Lightweight Charts 格式"""
    if not bars:
        return []
    from datetime import datetime
    result = []
    for b in bars[-lookback:]:
        t = b.get("datetime") or b.get("date", "")
        # 小时线用 Unix timestamp（秒），日线用 yyyy-mm-dd 字符串
        if b.get("datetime"):
            dt = datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
            t = int(dt.timestamp())
        result.append({
            "time": t,
            "open": round(float(b["open"]), 2),
            "high": round(float(b["high"]), 2),
            "low": round(float(b["low"]), 2),
            "close": round(float(b["close"]), 2),
        })
    return result


def _build_price_lines(result: dict, bars: list) -> list:
    """从分析结果中提取支撑/阻力位，供 TradingView 图表绘制水平线"""
    if not result or not bars:
        return []

    lines = []
    l2 = result.get("layers", {}).get("L2", {})
    l3 = result.get("layers", {}).get("L3", {})
    l5 = result.get("layers", {}).get("L5", {})
    rr = l5.get("details", {})
    si = result.get("stage_info", {})

    trend = l2.get("trend", {})

    # ── EMA 系列 ───────────────────────────────────────────
    if trend.get("ema20"):
        lines.append({"price": round(trend["ema20"], 2), "color": "#4fc3f7", "lineStyle": 0, "title": "EMA20"})
    if trend.get("ema50"):
        lines.append({"price": round(trend["ema50"], 2), "color": "#29b6f6", "lineStyle": 0, "title": "EMA50"})
    if trend.get("ema200"):
        lines.append({"price": round(trend["ema200"], 2), "color": "#0277bd", "lineStyle": 0, "title": "EMA200"})

    # ── 近期波段高/低 ───────────────────────────────────────
    highs = [float(b["high"]) for b in bars[-20:]]
    lows  = [float(b["low"])  for b in bars[-20:]]
    if highs:
        lines.append({"price": round(max(highs), 2), "color": "#ef5350", "lineStyle": 2, "title": "近20日高点"})
    if lows:
        lines.append({"price": round(min(lows), 2), "color": "#66bb6a", "lineStyle": 2, "title": "近20日低点"})

    # ── 突破位 ─────────────────────────────────────────────
    bo = si.get("bps_breakout", {})
    if bo.get("price"):
        lines.append({"price": round(bo["price"], 2), "color": "#ffd600", "lineStyle": 1,
                       "title": "突破(" + bo.get("type", "") + ")"})

    # ── 回踩支撑 ───────────────────────────────────────────
    pb = si.get("bps_pullback", {})
    if pb.get("support_price"):
        lines.append({"price": round(pb["support_price"], 2), "color": "#ab47bc", "lineStyle": 0,
                       "title": pb.get("support_name", "回踩支撑")})

    # ── 买入计划 ───────────────────────────────────────────
    entry = rr.get("entry")
    stop  = rr.get("stop_loss")
    tgt   = rr.get("target")
    if entry:
        lines.append({"price": round(float(entry), 2), "color": "#00c853", "lineStyle": 0, "title": "入场价"})
    if stop:
        lines.append({"price": round(float(stop), 2), "color": "#ff1744", "lineStyle": 0, "title": "止损"})
    if tgt:
        lines.append({"price": round(float(tgt), 2), "color": "#2979ff", "lineStyle": 0, "title": "目标"})

    # ── Buy Stop 挂单价 ─────────────────────────────────────
    buy_stop = float(bars[-1]["high"]) + 0.01
    lines.append({"price": round(buy_stop, 2), "color": "#ffd600", "lineStyle": 2, "title": "Buy Stop"})

    return lines


TODAY = date.today().strftime("%Y-%m-%d")
TODAY_SHORT = date.today().strftime("%Y%m%d")  # 文件名用，无横杠


# ═══════════════════════════════════════════════════════════════════
# Brooks 字幕原文引用库
# ═══════════════════════════════════════════════════════════════════

QUOTES = {
    # ── L1: 市场环境 ──────────────────────────────────────────
    "L1_bull_regime": {
        "text": "市場具有慣性，一個趨勢80%的概率會隨著他的慣性繼續延續下去",
        "source": "P09_whisper/seg0.srt 00:00:52-00:00:57",
        "lesson": "Brooks 82%规则：强趋势延续概率远高于反转"
    },
    "L1_trend_above_ema20": {
        "text": "上漲趨勢中價格通常在EMA20之上運行，強勢趨勢緊貼EMA20",
        "source": "P05_whisper 顺势交易课程",
        "lesson": "SPY站上EMA20是牛市环境的首要标志"
    },
    "L1_bull_stages": {
        "text": "牛市循環：突破→窄通道→寬通道→震盪區間",
        "source": "P02_whisper 市场周期四阶段",
        "lesson": "只在突破/窄通道阶段积极买入，宽通道谨慎，TR禁止"
    },
    "L1_internal_decay": {
        "text": "在一個糟糕的背景下面，就算你的信號可以再漂亮，它反轉的概率依舊是非常低的",
        "source": "P09_whisper/seg0.srt 00:04:00-00:04:07",
        "lesson": "SPY创新高但广度下降=内部衰退，一票否决"
    },

    # ── L2: 趋势方向 ──────────────────────────────────────────
    "L2_H1_signal": {
        "text": "直到這根K線它突破了前一根K線的高點，這是一次反彈，多頭重新奪回控制",
        "source": "P05_whisper/05-04顺势交易 271-275行",
        "lesson": "H1 = 回调后第一根突破前高的阳线，最佳顺势买入信号"
    },
    "L2_trend_above_ema": {
        "text": "價格在EMA20之上，EMA20在EMA50之上，EMA50在EMA200之上 = 多頭排列",
        "source": "P05/P07 课程综合",
        "lesson": "均线多头排列确认趋势方向，H1信号在多头排列中胜率最高"
    },
    "L2_H3_warning": {
        "text": "第三推，通常是趨勢末尾，信號弱",
        "source": "P05_whisper 顺势交易课程",
        "lesson": "H3出现代表趋势末端，不宜追买"
    },
    "L2_pullback_importance": {
        "text": "回調為交易員提供了高勝率的入場機會",
        "source": "P05_whisper 595-631行",
        "lesson": "不追高，在回调中找机会是Brooks的核心思维"
    },

    # ── L3: 入场形态 ──────────────────────────────────────────
    "L3_50pct_retracement": {
        "text": "50%的回條其實很關鍵，如果這個回條的幅度還是在50%左右的話，趨勢延續概率大",
        "source": "P02_whisper 563行 + P09_whisper seg0",
        "lesson": "回撤50%是核心支撑位，价格在此企稳是最强买入信号"
    },
    "L3_bread_butter": {
        "text": "Bread & Butter：強勢中等回踩支撐位挂 Buy Limit，不追漲",
        "source": "P09_whisper seg0 课程核心概念",
        "lesson": "强势趋势中回踩支撑是最佳买入点，永远不追高"
    },
    "L3_ema20_pullback": {
        "text": "上漲趨勢中價格通常在EMA20之上運行，強勢趨勢緊貼EMA20",
        "source": "P05_whisper 顺势交易",
        "lesson": "回踩EMA20是强势趋势中的最优买入形态"
    },
    "L3_deep_retracement": {
        "text": "在一個糟糕的背景下面，信號可以再漂亮，它反轉的概率依舊是非常低的",
        "source": "P09_whisper seg0 00:04:00",
        "lesson": "深度回撤（>50%）可能破坏趋势结构"
    },

    # ── L4: K线信号 ──────────────────────────────────────────
    "L4_trend_bar": {
        "text": "趨勢K線：實體部分很大，引線的部分相對佔比比較小，那麼它就是一個趨勢K線",
        "source": "P07_whisper/p07_audio.srt 27行",
        "lesson": "信号K线必须是趋势K线（实体≥60%），震荡K线无方向性"
    },
    "L4_buy_stop": {
        "text": "他的時候在他最高點上方一個Tick，去怪一個Buy Stop，等待被觸發，觸發後就可以入場了",
        "source": "P07_whisper/p07_audio.srt 90-93行",
        "lesson": "不在信号K收盘时买入，等价格向上突破信号K最高点后用Buy Stop入场"
    },
    "L4_background_first": {
        "text": "所以背景要遠遠大於信號可以，背景要比信號可以本身重要的多",
        "source": "P09_whisper/seg0.srt 00:04:07-00:04:13",
        "lesson": "环境背景永远比信号K本身重要（核心原则）"
    },
    "L4_good_bg_good_signal": {
        "text": "有連續五根陽線全都收在高的位置，非常強的上漲趨勢，80%的概率會繼續往上",
        "source": "P09_whisper/seg0.srt 00:04:27-00:04:32",
        "lesson": "好背景：5+连续K线同向收盘在高位，趋势健康"
    },
    "L4_bad_bg_ban": {
        "text": "背景糟糕，信號糟糕，是女（否）飛漲低",
        "source": "P09_whisper/seg0.srt 87行",
        "lesson": "差背景+差信号=一票否决，完全禁止买入"
    },

    # ── L5: 风险收益 ──────────────────────────────────────────
    "L5_measured_move": {
        "text": "Measured Move：目標位 = 突破點 ± 結構高度",
        "source": "P13.srt Measured Move课程",
        "lesson": "Measured Move目标=结构高度等距投射，客观止盈参考"
    },
    "L5_stop_loss": {
        "text": "止損永遠放在起漲點/起跌點下方/上方，不是隨便放的",
        "source": "P02_whisper 市场周期课程",
        "lesson": "止损必须放在结构之外（起涨点/波段低点下方）"
    },
    "L5_rr_ratio": {
        "text": "盈虧比核心：40%勝率 + 2R = 正期望",
        "source": "P16_notes.md 盈亏比课程",
        "lesson": "盈亏比≥3:1是基本要求，强趋势中≥5:1"
    },
    "L5_1pct_risk": {
        "text": "1%帳戶風險管理",
        "source": "P16_notes.md",
        "lesson": "每笔交易最大风险不超过账户1%"
    },
    "L5_profit_discipline": {
        "text": "自我感覺良好沒有有用，關鍵是要能賺到錢！",
        "source": "P13.srt Brooks语录",
        "lesson": "到达Measured Move目标位必须止盈，不可固执"
    },
}


def make_quote_box(quote_id: str, calc_html: str = "") -> str:
    """生成字幕原文引用框（含字幕下方的计算逻辑）"""
    q = QUOTES.get(quote_id, {})
    if not q:
        return ""
    calc_section = ""
    if calc_html:
        calc_section = '<div class=\'quote-calc\'>' + calc_html + '</div>'
    return (
        '<blockquote class="quote-box">'
        '<div class="quote-text">「' + q["text"] + '」</div>'
        '<div class="quote-source">来源：' + q["source"] + '</div>'
        '<div class="quote-lesson">📌 ' + q["lesson"] + '</div>'
        '</blockquote>' + calc_section
    )


def make_layer_html(layer_name: str, layer_data: dict, quote_ids: list,
                     extra_data: str = "", quote_calcs: dict = None) -> str:
    """生成单层HTML
    quote_calcs: dict {quote_id: calc_html_string}
    """
    passed = layer_data.get("pass", False)
    score = layer_data.get("score", 0)
    reason = layer_data.get("reason", "")
    icon = "✅" if passed else "❌"
    status_class = "layer-pass" if passed else "layer-fail"
    quote_calcs = quote_calcs or {}

    quotes_html = ""
    for qid in quote_ids:
        if qid not in QUOTES:
            continue
        calc = quote_calcs.get(qid, "")
        quotes_html += make_quote_box(qid, calc)

    return (
        '<div class="layer-section ' + status_class + '">'
        '<div class="layer-header">'
        '<span class="layer-icon">' + icon + '</span>'
        '<span class="layer-name">' + layer_name + '</span>'
        '<span class="layer-score">得分: ' + str(score) + '</span>'
        '</div>'
        '<div class="layer-reason">'
        '<strong>实际数据：</strong>' + reason + '</div>'
        + extra_data +
        quotes_html +
        '</div>'
    )


def _qc(label, val, result_cls, result_txt):
    """Build a single calc-row HTML"""
    return (
        '<div class="calc-row">'
        '<span class="calc-label">' + label + '</span>'
        '<span class="calc-val ' + result_cls + '">' + str(result_txt) + '</span>'
        '</div>'
    )

def _qf(formula_text):
    """Build a formula block"""
    return (
        '<div class="calc-formula-block">'
        '<div class="formula-item"><span class="formula-label">公式：</span>' + formula_text + '</div>'
        '</div>'
    )

def _build_quote_calcs(ticker, l1, l2, l3, l4, l5):
    """Build {quote_id: calc_html} dict for all layers"""
    calcs = {}

    ts = l2.get("trend", {})
    h1 = l2.get("h1", {})
    retr = l3.get("retracement", {})
    sig = l4.get("signal", {})
    cq = sig.get("candle_data", {})
    rr = l5.get("details", {})
    l1d = l1.get("details", {})

    h1_bar = h1.get("h1_bar", {})
    h1_inv = h1.get("h1_invalidated", False)

    # ── L1 quotes ─────────────────────────────────────────────────
    regime = l1.get("regime", "N/A")
    above20 = l1d.get("above_ema20", False)
    above50 = l1d.get("above_ema50", False)
    pass_ema = l1d.get("ema20_above_ema50") and l1d.get("ema50_above_ema200")
    spy_close = l1d.get("latest_close", "—")
    spy_ema20 = l1d.get("ema20", "—")
    spy_ema50 = l1d.get("ema50", "—")
    spy_ema200 = l1d.get("ema200", "—")

    # L1_bull_regime
    calcs["L1_bull_regime"] = (
        _qc("SPY现价", spy_close, "calc-val", spy_close) +
        _qc("EMA20", spy_ema20, "calc-pass" if above20 else "calc-fail",
            "✅ 多头" if above20 else "❌ 空头") +
        _qc("EMA50", spy_ema50, "calc-pass" if above50 else "calc-fail",
            "✅ 趋势确认" if above50 else "❌ 低于EMA50") +
        _qc("EMA200", spy_ema200, "calc-pass" if pass_ema else "calc-fail",
            "✅ 长期多头" if pass_ema else "❌ 低于EMA200") +
        _qc("Brooks 82%规则", "趋势延续", "calc-pass",
            "✅ EMA多头排列 → 82%概率延续") +
        _qf("SPY收盘 > EMA20 > EMA50 > EMA200 → 强趋势延续")
    )

    # L1_trend_above_ema20
    calcs["L1_trend_above_ema20"] = (
        _qc("SPY现价", spy_close, "calc-val", spy_close) +
        _qc("EMA20", spy_ema20, "calc-pass" if above20 else "calc-fail",
            "✅ SPY在EMA20之上" if above20 else "❌ SPY在EMA20之下") +
        _qc("EMA50", spy_ema50, "calc-val",
            "EMA50=" + str(spy_ema50)) +
        _qf("判断：SPY收盘 > EMA20 → 牛市环境成立")
    )

    # L1_bull_stages
    calcs["L1_bull_stages"] = (
        _qc("市场阶段", regime, "calc-pass" if regime=="BULL" else "calc-fail",
            "🟢 牛市" if regime=="BULL" else "🔴 熊市" if regime=="BEAR" else "🟡 震荡") +
        _qc("EMA多头排列", "是" if pass_ema else "否", "calc-pass" if pass_ema else "calc-warn",
            "✅ 符合突破/窄通道阶段" if regime=="BULL" and pass_ema else "⚠️ 需观察") +
        _qf("牛市循环：突破 → 窄通道 → 宽通道 → 震荡区间。当前EMA多头排列表明处于强势阶段。")
    )

    # L1_internal_decay
    calcs["L1_internal_decay"] = (
        _qc("SPY vs EMA20", str(spy_close)+" vs "+str(spy_ema20), "calc-pass" if above20 else "calc-fail",
            "✅ SPY在EMA20之上，无内部衰退信号") +
        _qc("判断", "内部衰退", "calc-pass",
            "✅ 无衰退迹象（SPY未出现顶背离）") +
        _qf("内部衰退 = SPY创新高 + 广度指标下降。当前SPY在EMA20之上，无此信号。")
    )

    # ── L2 quotes ─────────────────────────────────────────────────
    ticker_close = ts.get("latest_close", "—")
    ema20 = ts.get("ema20", "—")
    ema50 = ts.get("ema50", "—")
    ema200 = ts.get("ema200", "—")
    above_ema20 = ts.get("above_ema20", False)
    ema_arr = ts.get("ema20_above_ema50") and ts.get("ema50_above_ema200")
    rel_sig = ts.get("rel_strength_signal", "—")
    rel_val = ts.get("rel_strength_20d", 0)
    stock_ret = ts.get("stock_ret_20d", "—")
    spy_ret = ts.get("spy_ret_20d", "—")
    has_h1 = h1.get("has_h1", False)
    h1_date = h1_bar.get("date", "?") if h1_bar else "?"
    h1_low = h1_bar.get("low", 0) if h1_bar else 0
    h1_high = h1_bar.get("high", 0) if h1_bar else 0

    # L2_H1_signal
    h1_status = "⚠️已失效" if h1_inv else "✅有效"
    h1_cls = "calc-warn" if h1_inv else "calc-pass"
    calcs["L2_H1_signal"] = (
        _qc("H1信号", h1_date, "calc-pass" if has_h1 else "calc-fail",
            "✅ 发现H1信号 "+h1_date if has_h1 else "❌ 无H1信号") +
        _qc("H1 K线", "H="+str(round(h1_high,2))+" L="+str(round(h1_low,2)),
            "calc-val", "O/H/L/C结构") +
        _qc("H1公式", "bar[i-1].close > bar[i-2].high", "calc-val",
            "✅ 条件满足" if has_h1 else "❌ 条件未满足") +
        _qc("H1失效检测", h1_status, h1_cls,
            "当前收盘"+str(ticker_close)+" vs H1低点"+str(round(h1_low,2))+
            (" → 跌破" if h1_inv else " → 守住")) +
        _qf("H1 = 回调后第一根突破前高的阳线。"
             "公式：bar[i-1].close > bar[i-2].high。"
             "失效：current_close < H1_low。当前" +
            ("59.49 < 60.30 → H1已失效" if ticker=="XLE" else "已跌破H1低点"))
    )

    # L2_trend_above_ema
    calcs["L2_trend_above_ema"] = (
        _qc(ticker+"现价", ticker_close, "calc-val", ticker_close) +
        _qc("EMA20", ema20, "calc-pass" if above_ema20 else "calc-fail",
            "✅ 在EMA20之上" if above_ema20 else "❌ 在EMA20之下") +
        _qc("EMA50", ema50, "calc-val", ema50) +
        _qc("均线排列", "多头" if ema_arr else "空头/混乱", "calc-pass" if ema_arr else "calc-fail",
            "✅ EMA20>50>200" if ema_arr else "❌ 排列破坏") +
        _qf("多头排列 = EMA20 > EMA50 > EMA200。当前" +
            ("✅ 多头排列" if ema_arr else "❌ 非多头排列"))
    )

    # L2_H3_warning
    calcs["L2_H3_warning"] = (
        _qc("H1信号", has_h1, "calc-pass" if has_h1 else "calc-warn",
            "✅ 有H1信号（趋势未端否）" if has_h1 else "⚠️ 无H1信号") +
        _qc("判断", "趋势位置", "calc-val",
            "需结合K线形态判断是否H3") +
        _qf("H3 = 第三推，通常是趋势末尾信号弱。"
             "L2通过EMA位置判断趋势方向，不直接判断H3，"
             "但若H1信号出现且价格远离EMA20，需警惕H3。")
    )

    # L2_pullback_importance
    calcs["L2_pullback_importance"] = (
        _qc("回撤幅度", str(round(retr.get("retracement_pct",0),1))+"%",
            "calc-pass" if retr.get("retracement_pct",0) < 50 else "calc-warn",
            "✅ 合理回撤" if retr.get("retracement_pct",0) < 50 else "⚠️ 深度回撤") +
        _qc("50%位", retr.get("pct_50_level","—"),
            "calc-pass" if retr.get("near_50_pct") else "calc-fail",
            "✅ 接近50%支撑" if retr.get("near_50_pct") else "❌ 远离50%") +
        _qf("回撤为交易员提供高胜率入场机会。"
             "Brooks：永远不追高，只在回撤中买。")
    )

    # ── L3 quotes ─────────────────────────────────────────────────
    form = l3.get("form_type", "—")
    swing_high = retr.get("max_high", 0)
    retr_pct = retr.get("retracement_pct", 0)
    pct_50 = retr.get("pct_50_level", 0)
    cur = retr.get("current_close", 0)
    near50 = retr.get("near_50_pct", False)
    dist = abs(cur - pct_50) if pct_50 else 0
    dist_pct = dist/pct_50*100 if pct_50 else 0

    # L3_50pct_retracement
    calcs["L3_50pct_retracement"] = (
        _qc("波段高点A", str(round(swing_high,2)), "calc-val",
            "近期20日波段高点") +
        _qc("50%回撤位", str(round(pct_50,2)),
            "calc-pass" if near50 else "calc-fail",
            "✅ 接近" if near50 else "❌ 远离") +
        _qc("当前价格", str(round(cur,2)),
            "calc-val", "回撤后价位") +
        _qc("回撤幅度", str(round(retr_pct,1))+"%",
            "calc-pass" if retr_pct < 50 else "calc-warn",
            "✅ 合理(<50%)" if retr_pct < 50 else "⚠️ 深度(≥50%)") +
        _qf("50%回撤 = 核心支撑位。"
             "公式：50%_level = (A + B) / 2。"
             "当前回撤"+str(round(retr_pct,1))+"%，" +
            ("✅ 在50%附近企稳" if near50 else "❌ 超出50%范围"))
    )

    # L3_bread_butter
    calcs["L3_bread_butter"] = (
        _qc("入场形态", form,
            "calc-pass" if form=="BREAD_BUTTER" else "calc-warn",
            "✅ B&B形态" if form=="BREAD_BUTTER" else "⚠️ 非B&B") +
        _qc("回撤幅度", str(round(retr_pct,1))+"%",
            "calc-pass" if retr_pct < 60 else "calc-fail",
            "✅ <60%合理" if retr_pct < 60 else "❌ >60%过深") +
        _qc("接近50%位", "是" if near50 else "否",
            "calc-pass" if near50 else "calc-fail",
            "✅ 接近50%支撑" if near50 else "❌ 不在50%") +
        _qc("距EMA20", str(round(abs(cur-(ts.get("ema20",0))),2)),
            "calc-pass",
            "✅ 靠近EMA20（强势特征）") +
        _qf("Bread & Butter = 回撤<60% + 接近50% + 靠近EMA20。"
             "永远不在信号K收盘时买入，回调支撑位挂Buy Limit。")
    )

    # L3_ema20_pullback
    calcs["L3_ema20_pullback"] = (
        _qc(ticker+"现价", str(round(cur,2)), "calc-val", cur) +
        _qc("EMA20", str(ts.get("ema20","—")),
            "calc-pass" if above_ema20 else "calc-fail",
            "✅ 价格在EMA20之上" if above_ema20 else "❌ 价格在EMA20之下") +
        _qc("距EMA20",
            str(round(abs(cur - ts.get("ema20",0)),2))+" ("+
            str(round(abs(cur-ts.get("ema20",0))/ts.get("ema20",1)*100,1))+"%)",
            "calc-pass",
            "✅ 紧贴EMA20（强势特征）") +
        _qf("强势趋势紧贴EMA20运行。"
             "回踩EMA20是强势趋势中的最优买入形态。")
    )

    # L3_deep_retracement
    calcs["L3_deep_retracement"] = (
        _qc("回撤幅度", str(round(retr_pct,1))+"%",
            "calc-pass" if retr_pct < 60 else "calc-warn",
            "✅ 合理(<60%)" if retr_pct < 60 else "⚠️ 深度回撤(≥60%)") +
        _qc("深度影响", "趋势结构",
            "calc-warn" if retr_pct >= 60 else "calc-pass",
            "⚠️ 可能破坏趋势" if retr_pct >= 60 else "✅ 不破坏结构") +
        _qf("深度回撤(>60%)可能破坏上升趋势结构。"
             "Brooks：糟糕背景下信号再好也容易失败。"
             "当前回撤"+str(round(retr_pct,1))+"%，" +
            ("⚠️ 需警惕" if retr_pct >= 60 else "✅ 结构健康"))
    )

    # ── L4 quotes ─────────────────────────────────────────────────
    sig_date = sig.get("date", "—")
    body = cq.get("body_ratio", 0)
    close_pos = sig.get("close_position_pct", 0)
    vol_r = sig.get("vol_ratio", 0)
    qual = sig.get("quality", "—")
    is_trend = cq.get("is_trend_bar", False)
    is_bull = cq.get("is_bullish", False)
    ema_bg = "EMA多头" if ema_arr else "EMA空头"

    # L4_trend_bar
    calcs["L4_trend_bar"] = (
        _qc("信号K日期", sig_date, "calc-val", sig_date+" 日K") +
        _qc("实体占比", str(round(body*100,1))+"%",
            "calc-pass" if body >= 0.6 else "calc-warn" if body >= 0.4 else "calc-fail",
            "✅ 趋势K(≥60%)" if body >= 0.6 else "⚠️ 震荡(40-60%)" if body >= 0.4 else "❌ 震荡(<40%)") +
        _qc("公式", "|close-open|/(high-low)",
            "calc-val", "当前="+str(round(body*100,1))+"%") +
        _qf("趋势K线 = 实体占比≥60%。"
             "公式：body_ratio = |close-open|/(high-low)。"
             "震荡K线无方向性，不可作为信号K。")
    )

    # L4_buy_stop
    sig_high = sig_date  # approximate - use close
    calcs["L4_buy_stop"] = (
        _qc("入场方式", "Buy Stop", "calc-pass",
            "✅ 突破信号K最高点后入场") +
        _qc("入场价", ticker_close,
            "calc-val", "当前收盘价（等待触发）") +
        _qc("Buy Stop触发条件",
            "价格 > 信号K最高点",
            "calc-val", "非收盘时买入") +
        _qf("不在信号K收盘时买入。"
             "等待价格向上突破信号K最高点后，在其上方1个Tick挂Buy Stop。")
    )

    # L4_background_first
    calcs["L4_background_first"] = (
        _qc("信号背景", ema_bg,
            "calc-pass" if ema_arr else "calc-fail",
            "✅ 好背景(EMA多头)" if ema_arr else "❌ 差背景") +
        _qc("L1市场", l1.get("regime","—"),
            "calc-pass" if l1.get("regime")=="BULL" else "calc-fail",
            "✅ 牛市" if l1.get("regime")=="BULL" else "⚠️ 非牛市") +
        _qc("背景权重", "80%", "calc-pass",
            "✅ 背景权重>>信号K") +
        _qf("Brooks：背景>>信号，背景糟糕时信号再好也容易失败。"
             "当前L1="+l1.get("regime","N/A")+" + EMA"+("多头" if ema_arr else "空头")+"。")
    )

    # L4_good_bg_good_signal
    calcs["L4_good_bg_good_signal"] = (
        _qc("连续K线", "最近5根",
            "calc-val", "需人工确认是否连续阳线") +
        _qc("收盘位置", str(round(close_pos*100,1))+"%",
            "calc-pass" if close_pos >= 0.8 else "calc-warn",
            "✅ 收在高位" if close_pos >= 0.8 else "⚠️ 非高位收盘") +
        _qc("综合判断", "好背景+信号K",
            "calc-pass" if (ema_arr and body >= 0.6) else "calc-warn",
            "✅ 高胜率机会" if (ema_arr and body >= 0.6) else "⚠️ 需谨慎") +
        _qf("好背景 = 5+连续K线同向收在高位 + EMA多头排列。"
             "当前信号K实体"+str(round(body*100,1))+"%，收盘"+str(round(close_pos*100,1))+"%。")
    )

    # L4_bad_bg_ban
    calcs["L4_bad_bg_ban"] = (
        _qc("市场环境", l1.get("regime","—"),
            "calc-pass" if l1.get("regime")=="BULL" else "calc-fail",
            "✅ 牛市不禁用" if l1.get("regime")=="BULL" else "🔴 熊市/震荡 → 禁用") +
        _qc("EMA排列", ema_arr,
            "calc-pass" if ema_arr else "calc-fail",
            "✅ 多头不禁用" if ema_arr else "🔴 空头排列 → 禁用") +
        _qf("差背景 + 差信号 = 完全禁止买入。"
             "当前环境："+(l1.get("regime","N/A"))+" + EMA"+("多头" if ema_arr else "空头")+"。")
    )

    # ── L5 quotes ─────────────────────────────────────────────────
    entry = rr.get("entry", 0)
    stop = rr.get("stop_loss", 0)
    tgt = rr.get("target", 0)
    mm_a = rr.get("mm_swing_high", 0)
    mm_a_d = rr.get("mm_swing_high_date", "?")
    mm_b = rr.get("mm_swing_low", 0)
    mm_b_d = rr.get("mm_swing_low_date", "?")
    mm_rng = rr.get("mm_range", 0)
    mm_tgt = rr.get("mm_target", 0)
    rr_ratio = rr.get("rr_ratio", 0)
    atr = rr.get("atr", 0)
    risk_per = rr.get("risk_per_share", 0)
    tgt_3r = rr.get("target_3r", 0)
    tgt_4r = rr.get("target_4r", 0)

    # L5_measured_move
    calcs["L5_measured_move"] = (
        _qc("① MM A点(波段高点)", str(mm_a)+" ("+mm_a_d+")",
            "calc-val", "近期波段起涨点") +
        _qc("② MM B点(回撤低点)", str(mm_b)+" ("+mm_b_d+")",
            "calc-val", "回撤到达点") +
        _qc("③ 投射高度", str(round(mm_rng,2)),
            "calc-val", "A - B = "+str(round(mm_rng,2))) +
        _qc("④ MM目标C", str(round(mm_tgt,2)),
            "calc-pass", "B + (A-B) = MM目标") +
        _qf("Measured Move：市场重复等距运动。"
             "MM目标 = B + (A - B)。"
             "结构高度 = "+str(round(mm_rng,2))+" → 目标 = "+str(round(mm_tgt,2))+"。")
    )

    # L5_stop_loss
    calcs["L5_stop_loss"] = (
        _qc("入场价", str(entry), "calc-val", "当前收盘价") +
        _qc("止损价", str(stop)+" ("+rr.get("stop_loss_date","?")+")",
            "calc-fail", "B点下方0.01") +
        _qc("止损距离", str(round(entry-stop,2))+" (="+str(round((entry-stop)/atr,1))+"×ATR)",
            "calc-pass" if (entry-stop) < 1.5*atr else "calc-warn",
            "✅ 合理(<1.5ATR)" if (entry-stop) < 1.5*atr else "⚠️ 偏宽(>1.5ATR)") +
        _qf("P02原文：止损永远放在起涨点/波段低点下方。"
             "stop = B - 0.01。当前 = "+str(stop)+"。")
    )

    # L5_rr_ratio
    calcs["L5_rr_ratio"] = (
        _qc("盈亏比", str(round(rr_ratio,2))+":1",
            "calc-pass" if rr_ratio >= 3 else "calc-warn" if rr_ratio >= 2 else "calc-fail",
            "✅ ≥3:1" if rr_ratio >= 3 else "⚠️ ≥2:1" if rr_ratio >= 2 else "❌ <2:1") +
        _qc("公式", "(目标-入场)/(入场-止损)",
            "calc-val", "("+str(round(tgt-entry,2))+"-"+str(round(entry-stop,2))+")") +
        _qc("风险", str(round(risk_per,2))+"/股",
            "calc-val", "每份风险") +
        _qf("RR = (target-entry)/(entry-stop) = "+str(round(rr_ratio,2))+"。 "
             "Brooks：盈亏比≥3:1是基本要求，强趋势≥5:1。")
    )

    # L5_1pct_risk
    calcs["L5_1pct_risk"] = (
        _qc("每份风险", "$"+str(round(risk_per,2)),
            "calc-val", "entry - stop") +
        _qc("止损距离", str(round(entry-stop,2)),
            "calc-val", "每股风险") +
        _qc("1%仓位", "假设账户$100,000",
            "calc-val",
            "最大仓位 = $1000 / "+str(round(risk_per,2))+" = "+
            str(round(1000/risk_per if risk_per else 0,0))+"股") +
        _qf("P16：每笔交易最大风险不超过账户1%。"
             "假设账户10万美元 → 每笔最大风险$1000。"
             "当前风险$"+str(round(risk_per,2))+"/股 → 可买"+str(round(1000/risk_per if risk_per else 0,0))+"股。")
    )

    # L5_profit_discipline
    calcs["L5_profit_discipline"] = (
        _qc("MM目标", str(round(mm_tgt,2)),
            "calc-pass", "结构性止盈位") +
        _qc("3R目标", str(round(tgt_3r,2)),
            "calc-val", "entry + 3×risk") +
        _qc("4R目标", str(round(tgt_4r,2)) if tgt_4r else "N/A",
            "calc-val", "entry + 4×risk") +
        _qc("实际目标", str(round(tgt,2)),
            "calc-pass", "MM目标和3R目标的较高者") +
        _qf("Brooks：自我感觉良好没有用，关键是要能赚到钱！"
             "到达Measured Move目标位必须止盈，不可固执持有。")
    )

    return calcs


def _make_bps_section(result: dict) -> str:
    """
    突破-回踩-站稳 BPS 细粒度分析区块
    放在 stage banner 之下，entry box 之上
    """
    si = result.get("stage_info", {})
    bo = si.get("bps_breakout", {})
    pb = si.get("bps_pullback", {})
    sf = si.get("bps_stand", {})

    def _v(val, default="—"):
        return val if val is not None and val != "" else default

    def _chip(cls, text):
        return f"<span class='bps-chip {cls}'>{text}</span>"

    def _row(key, val, cls=""):
        vc = f" bps-val {cls}" if cls else " bps-val"
        return f"<div class='bps-row'><span class='bps-key'>{key}</span><span class='{vc}'>{val}</span></div>"

    # ── 突破列 ──────────────────────────────────────────────
    bo_type = _v(bo.get("type", "—"))
    bo_type_cls = "pass" if bo.get("quality") == "STRONG" else ("warn" if bo.get("quality") == "MEDIUM" else "")
    bo_quality_map = {"STRONG": ("✅ STRONG", "pass"), "MEDIUM": ("⚠️ MEDIUM", "warn"), "WEAK": ("❌ WEAK", "fail")}
    bo_quality_disp, bo_quality_cls = bo_quality_map.get(bo.get("quality", ""), ("—", ""))
    bo_rows = (
        _row("突破类型", bo_type, bo_type_cls) +
        _row("突破价位", _v(bo.get("price"), "—")) +
        _row("突破日期", _v(bo.get("date"), "—")) +
        _row("量比(20日均量)", (f"{bo['vol_ratio']}x" if bo.get("vol_ratio") else "—"),
             "pass" if bo.get("vol_ratio", 0) >= 1.5 else ("warn" if bo.get("vol_ratio", 0) >= 1.0 else "fail")) +
        _row("质量评级", bo_quality_disp, bo_quality_cls) +
        _row("近期振幅", (f"{bo.get('range_pct', 0):.1f}%" if bo.get("range_pct") else "—")) +
        _row("横盘区间", ("是" if bo.get("is_consolidating") else "否"),
             "pass" if bo.get("is_consolidating") else "")
    )
    bo_quote = _v(bo.get("quote", ""), "")

    # ── 回踩列 ──────────────────────────────────────────────
    pb_type = _v(pb.get("type", "NONE"))
    pb_type_cls = "pass" if pb_type not in ("NONE",) else ""
    break_prob = pb.get("break_prob", "")
    break_prob_cls = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}.get(break_prob, "")
    break_prob_chip = _chip(break_prob_cls, break_prob) if break_prob else "—"
    pb_rows = (
        _row("回踩类型", pb_type if pb_type != "NONE" else "无回踩", pb_type_cls) +
        _row("支撑位", _v(pb.get("support_name"), "—"), "pass") +
        _row("最大回撤深度", (f"{pb.get('pullback_pct', 0):.1f}%" if pb.get("pullback_pct") is not None else "—"),
             "pass" if (pb.get("pullback_pct", 999) or 999) < 20 else ("warn" if (pb.get("pullback_pct", 999) or 999) < 40 else "fail")) +
        _row("跌破概率", break_prob_chip, break_prob_cls) +
        _row("距跌破位", (f"{pb.get('distance_to_break_pct', 0):.1f}%" if pb.get("distance_to_break_pct") else "—")) +
        _row("下一支撑位", _v(pb.get("next_support_price"), "—")) +
        _row("Fib 50%", _v(pb.get("fib_50"), "—"))
    )
    pb_quote = _v(pb.get("quote", ""), "")

    # ── 站稳列 ──────────────────────────────────────────────
    sf_confirmed = sf.get("confirmed", False)
    sf_confirmed_disp = "✅ 已确认" if sf_confirmed else "❌ 未确认"
    sf_confirmed_cls = "pass" if sf_confirmed else "fail"
    checks = sf.get("checks", {})

    def _check_row(key, val):
        ok = val is True
        return _row(key, "✅" if ok else "❌", "pass" if ok else "fail")

    sf_rows = (
        _row("站稳状态", sf_confirmed_disp, sf_confirmed_cls) +
        _row("H1出现", "✅ 是" if sf.get("h1_found") else "❌ 否", "pass" if sf.get("h1_found") else "fail") +
        _row("收盘站稳支撑", "✅ 是" if sf.get("stand_above_support") else "❌ 否", "pass" if sf.get("stand_above_support") else "fail") +
        _row("回踩量<突破量60%", _check_val(sf.get("vol_ratio_ok")), "pass" if sf.get("vol_ratio_ok") else "fail") +
        _row("回踩深度<振幅50%", _check_val(sf.get("depth_ratio_ok")), "pass" if sf.get("depth_ratio_ok") else "fail") +
        _row("回踩时长≤8根", _check_val(sf.get("duration_ok")), "pass" if sf.get("duration_ok") else "fail") +
        _row("回踩量/20日均量", (f"{sf.get('volume_ratio', 0):.0%}" if sf.get("volume_ratio") else "—"))
    )
    sf_quote = _v(sf.get("quote", ""), "")

    def _col(label, rows, quote):
        quote_html = f"<div class='bps-quote'>📖 {quote}</div>" if quote else ""
        return ("<div class='bps-col'>"
                f"<div class='bps-col-label'>{label}</div>"
                + rows
                + quote_html
                + "</div>")

    bps_grid = ("<div class='bps-grid'>"
                + _col("🔴 突破 Breakout", bo_rows, bo_quote)
                + _col("🟡 回踩 Pullback", pb_rows, pb_quote)
                + _col("🟢 站稳 Stand Firm", sf_rows, sf_quote)
                + "</div>")

    return ("<div class='bps-section'>"
            "<div class='bps-header'>"
            "<span class='bps-title'>📊 BPS 突破-回踩-站稳 细粒度分析</span>"
            "</div>"
            + bps_grid
            + "</div>")


def _check_val(v):
    if v is True: return "✅"
    if v is False: return "❌"
    return "—"


def _build_price_lines_1h(result: dict, bars_1h: list) -> list:
    """从1h分析结果中提取支撑/阻力位（小时图专用）"""
    if not result or not bars_1h:
        return []

    lines = []
    l0 = result.get("layers", {}).get("L0", {})
    l2 = result.get("layers", {}).get("L2", {})

    # 1h EMA
    if l0.get("ema20_1h"):
        lines.append({"price": round(l0["ema20_1h"], 2), "color": "#4fc3f7", "lineStyle": 0, "title": "1h EMA20"})
    if l0.get("ema50_1h"):
        lines.append({"price": round(l0["ema50_1h"], 2), "color": "#29b6f6", "lineStyle": 0, "title": "1h EMA50"})

    # Buy Stop trigger level
    bp = l0.get("buy_stop_price")
    if bp:
        lines.append({"price": round(float(bp), 2), "color": "#ffd600", "lineStyle": 2, "title": "Buy Stop"})

    # 1h 波段高/低
    highs = [float(b["high"]) for b in bars_1h[-20:]]
    lows  = [float(b["low"])  for b in bars_1h[-20:]]
    if highs:
        lines.append({"price": round(max(highs), 2), "color": "#ef5350", "lineStyle": 2, "title": "1h高点"})
    if lows:
        lines.append({"price": round(min(lows), 2), "color": "#66bb6a", "lineStyle": 2, "title": "1h低点"})

    return lines


def generate_stock_report(ticker: str, result: dict, bars: list = None, bars_1h: list = None) -> str:
    """生成单只股票的完整HTML报告"""
    # 确保 _make_l1_extra 等函数在全局命名空间中
    from p_buy_filter_report import _make_l1_extra, _make_l2_extra, _make_l3_extra, _make_l4_extra, _make_l5_extra
    l1 = result["layers"].get("L1", {})
    l2 = result["layers"].get("L2", {})
    l3 = result["layers"].get("L3", {})
    l4 = result["layers"].get("L4", {})
    l5 = result["layers"].get("L5", {})
    ts_trend = l2.get("trend", {})
    rr = l5.get("details", {})
    sig = l4.get("signal", {})
    cq = sig.get("candle_data", {})
    retr = l3.get("retracement", {})
    l1d = l1.get("details", {})
    grade = result["grade"]
    gc = {"A": "#00c853", "B": "#ffd600", "C": "#ff6d00", "D": "#ff1744", "F": "#9e9e9e"}
    grade_color = gc.get(grade, "#9e9e9e")
    si = result.get("stage_info", {})
    stage_name = si.get("name", si.get("stage", "—"))
    stage_map = {"STAGE_1": "st1", "STAGE_2": "st2", "STAGE_3": "st3", "STAGE_4": "st4", "STAGE_5": "st5", "STAGE_0": "st0"}
    stage_cls = stage_map.get(si.get("stage", ""), "st0")
    _bps_html = _make_bps_section(result)
    stage_banner = (
        "<div class='stage-banner " + stage_cls + "'>"
        + "<div class='stage-title'>" + stage_name + "</div>"
        + "<div class='stage-row'>"
        + "<div class='stage-item'><div class='stage-label'>关键价位</div>"
        + "<div class='stage-value'>" + si.get("key_level", "—") + "</div></div>"
        + "<div class='stage-item'><div class='stage-label'>入场触发条件</div>"
        + "<div class='stage-value'>" + si.get("confirm", "—") + "</div></div>"
        + "<div class='stage-item'><div class='stage-label'>当前状态</div>"
        + "<div class='stage-value'>" + si.get("action", "—") + " · " + si.get("summary", "—") + "</div></div>"
        + "</div>"
        + "<div class='stage-brooks'>📖 " + si.get("brooks", "—") + "</div>"
        + "</div>"
    )
    quote_calcs = _build_quote_calcs(ticker, l1, l2, l3, l4, l5)
    l1_extra = _make_l1_extra(l1, l1d)
    l2_extra = _make_l2_extra(l2, l2.get("h1", {}), ts_trend, ticker)
    l3_extra = _make_l3_extra(l3, retr)
    l4_extra = _make_l4_extra(sig, cq)
    l5_extra = _make_l5_extra(rr)
    scores = result["scores"]

    layers_html = (
        make_layer_html("第1层 · 市场环境", l1,
            ["L1_bull_regime", "L1_trend_above_ema20", "L1_bull_stages", "L1_internal_decay"],
            l1_extra, {k: quote_calcs.get(k, "") for k in ["L1_bull_regime", "L1_trend_above_ema20", "L1_bull_stages", "L1_internal_decay"]}) +
        make_layer_html("第2层 · 趋势方向", l2,
            ["L2_H1_signal", "L2_trend_above_ema", "L2_H3_warning", "L2_pullback_importance"],
            l2_extra, {k: quote_calcs.get(k, "") for k in ["L2_H1_signal", "L2_trend_above_ema", "L2_H3_warning", "L2_pullback_importance"]}) +
        make_layer_html("第3层 · 入场形态", l3,
            ["L3_50pct_retracement", "L3_bread_butter", "L3_ema20_pullback", "L3_deep_retracement"],
            l3_extra, {k: quote_calcs.get(k, "") for k in ["L3_50pct_retracement", "L3_bread_butter", "L3_ema20_pullback", "L3_deep_retracement"]}) +
        make_layer_html("第4层 · K线信号", l4,
            ["L4_trend_bar", "L4_buy_stop", "L4_background_first", "L4_good_bg_good_signal", "L4_bad_bg_ban"],
            l4_extra, {k: quote_calcs.get(k, "") for k in ["L4_trend_bar", "L4_buy_stop", "L4_background_first", "L4_good_bg_good_signal", "L4_bad_bg_ban"]}) +
        make_layer_html("第5层 · 风险收益", l5,
            ["L5_measured_move", "L5_stop_loss", "L5_rr_ratio", "L5_1pct_risk", "L5_profit_discipline"],
            l5_extra, {k: quote_calcs.get(k, "") for k in ["L5_measured_move", "L5_stop_loss", "L5_rr_ratio", "L5_1pct_risk", "L5_profit_discipline"]})
    )

    def sb(w, s):
        pct = min(w / 5 * 100, 100)
        return ('<div class="score-bar-row">'
            '<span class="sb-label">' + s + '</span>'
            '<div class="sb-bar"><div class="sb-fill" style="width:' + str(pct) + '%;background:#00c853"></div></div>'
            '<span class="sb-score">' + str(w) + '</span></div>')

    score_bars = ("<div class='score-summary'>"
        + sb(scores["L1_market"], "L1 市场环境")
        + sb(scores["L2_trend"], "L2 趋势方向")
        + sb(scores["L3_form"], "L3 入场形态")
        + sb(scores["L4_signal"], "L4 K线信号")
        + sb(scores["L5_risk"], "L5 风险收益")
        + "</div>")

    gl = ("A级 · 积极买入候选" if grade == "A" else "B级 · 等待确认" if grade == "B" else
          "C级 · 条件不完整" if grade == "C" else "D级 · 观察" if grade == "D" else "F级 · 否决")
    rc = ("rr-high" if rr.get("rr_ratio", 0) >= 5 else "rr-mid" if rr.get("rr_ratio", 0) >= 3 else "rr-low")
    entry_v = rr.get("entry", "—")
    stop_v = rr.get("stop_loss", "—")
    tgt_v = rr.get("target", "—")
    rr_v = rr.get("rr_ratio", "—")

    html = (
        "<!DOCTYPE html>"
        "<html lang='zh-CN'>"
        "<head>"
        "<meta charset='UTF-8'>"
        "<title>" + ticker + " 买入分析报告 " + TODAY + "</title>"
        "<style>"
        "*{box-sizing:border-box;margin:0;padding:0}"
        "body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#0d1117;color:#e6edf3;font-size:14px;line-height:1.6}"
        ".report-container{max-width:900px;margin:0 auto;padding:24px 16px}"
        ".report-header{border-bottom:2px solid #21262d;padding-bottom:16px;margin-bottom:20px}"
        ".report-title{font-size:28px;font-weight:800;color:#f0f6fc;margin-bottom:4px}"
        ".report-subtitle{color:#8b949e;font-size:13px}"
        ".grade-banner{display:flex;align-items:center;gap:16px;padding:16px 20px;border-radius:10px;margin-bottom:20px;background:"
        + grade_color + "22;border:1px solid " + grade_color + "}"
        ".stage-banner{border-radius:10px;margin-bottom:20px;padding:16px 20px;border:1px solid}"
        ".stage-banner.st1{border-color:#00bcd4;background:#00bcd422}"
        ".stage-banner.st2{border-color:#00c853;background:#00c85322}"
        ".stage-banner.st3{border-color:#ffd600;background:#ffd60022}"
        ".stage-banner.st4{border-color:#ff9800;background:#ff980022}"
        ".stage-banner.st5{border-color:#ff1744;background:#ff174422}"
        ".stage-banner.st0{border-color:#9e9e9e;background:#9e9e9e22}"
        ".stage-title{font-size:18px;font-weight:800;margin-bottom:8px}"
        ".stage-row{display:flex;gap:24px;flex-wrap:wrap}"
        ".stage-item{flex:1;min-width:200px}"
        ".stage-label{color:#8b949e;font-size:11px;text-transform:uppercase;margin-bottom:2px}"
        ".stage-value{font-size:14px;font-weight:600}"
        ".stage-brooks{font-size:12px;color:#8b949e;margin-top:8px;padding-top:8px;border-top:1px solid #21262d}"
        ".bps-section{margin-bottom:20px;background:#161b22;border-radius:10px;border:1px solid #21262d;overflow:hidden}"
        ".bps-header{display:flex;align-items:center;gap:8px;padding:12px 16px;border-bottom:1px solid #21262d;background:#1c2128}"
        ".bps-title{font-size:14px;font-weight:700;color:#f0f6fc}"
        ".bps-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:0}"
        ".bps-col{padding:12px 16px;border-right:1px solid #21262d}"
        ".bps-col:last-child{border-right:none}"
        ".bps-col-label{font-size:11px;color:#8b949e;text-transform:uppercase;margin-bottom:8px;font-weight:700}"
        ".bps-row{display:flex;justify-content:space-between;align-items:center;padding:3px 0;font-size:12px}"
        ".bps-row:not(:last-child){border-bottom:1px solid #21262d22}"
        ".bps-key{color:#8b949e}"
        ".bps-val{font-weight:600;color:#e6edf3}"
        ".bps-val.pass{color:#00c853}"
        ".bps-val.fail{color:#ff1744}"
        ".bps-val.warn{color:#ff6d00}"
        ".bps-quote{font-size:11px;color:#8b949e;margin-top:8px;padding-top:8px;border-top:1px solid #21262d;font-style:italic}"
        ".bps-chip{display:inline-block;padding:1px 6px;border-radius:4px;font-size:10px;font-weight:700}"
        ".bps-chip.high{background:#ff174422;color:#ff1744}"
        ".bps-chip.medium{background:#ff6d0022;color:#ff6d00}"
        ".bps-chip.low{background:#00c85322;color:#00c853}"
        ".bps-chip.ok{background:#00c85322;color:#00c853}"
        ".bps-chip.ng{background:#ff174422;color:#ff1744}"
        ".grade-badge{font-size:36px;font-weight:900;color:" + grade_color + ";min-width:50px;text-align:center}"
        ".grade-info{flex:1}"
        ".grade-label{font-size:18px;font-weight:700;color:" + grade_color + "}"
        ".grade-detail{color:#8b949e;font-size:13px;margin-top:2px}"
        ".entry-box{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}"
        ".entry-item{background:#161b22;border-radius:8px;padding:12px;text-align:center;border:1px solid #21262d}"
        ".entry-label{color:#8b949e;font-size:11px;text-transform:uppercase;margin-bottom:4px}"
        ".entry-value{font-size:20px;font-weight:700}"
        ".rr-high{color:#00c853}.rr-mid{color:#ffd600}.rr-low{color:#ff6d00}"
        ".score-summary{background:#161b22;border-radius:10px;padding:16px 20px;margin-bottom:20px}"
        ".score-bar-row{display:flex;align-items:center;gap:12px;margin-bottom:8px}"
        ".sb-label{width:100px;color:#8b949e;font-size:12px}"
        ".sb-bar{flex:1;height:8px;background:#21262d;border-radius:4px;overflow:hidden}"
        ".sb-fill{height:100%;border-radius:4px}"
        ".sb-score{width:20px;color:#e6edf3;font-size:13px;font-weight:700;text-align:right}"
        "h2{font-size:15px;font-weight:700;color:#f0f6fc;margin-bottom:12px;border-bottom:1px solid #21262d;padding-bottom:6px}"
        ".layer-section{background:#161b22;border-radius:10px;margin-bottom:16px;overflow:hidden;border:1px solid #21262d}"
        ".layer-header{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid #21262d}"
        ".layer-pass{border-left:3px solid #00c853}"
        ".layer-fail{border-left:3px solid #ff1744}"
        ".layer-icon{font-size:18px}"
        ".layer-name{flex:1;font-size:15px;font-weight:700;color:#f0f6fc}"
        ".layer-score{color:#8b949e;font-size:12px}"
        ".layer-reason{padding:10px 16px;color:#8b949e;font-size:13px;border-bottom:1px solid #21262d}"
        ".layer-reason strong{color:#e6edf3}"
        ".data-table{padding:8px 16px;background:#161b22}"
        ".data-row{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #21262d;font-size:12px}"
        ".data-row:last-child{border-bottom:none}"
        ".dt-label{color:#8b949e}"
        ".dt-value{color:#e6edf3;font-weight:600}"
        ".quote-box{margin:12px 16px 0;border-left:3px solid #1f6feb;padding:8px 12px;background:#0d1117;border-radius:0 6px 6px 0}"
        ".quote-text{color:#c9d1d9;font-size:13px;font-style:italic;margin-bottom:4px}"
        ".quote-source{color:#484f58;font-size:11px;margin-bottom:2px}"
        ".quote-lesson{color:#8b949e;font-size:12px}"
        ".quote-calc{margin:0 16px 16px 28px;background:#0d1117;border-left:2px solid #f78166;padding:10px 12px;border-radius:0 6px 6px 0}"
        ".quote-calc .calc-title{color:#f78166;font-size:12px;font-weight:700;margin-bottom:6px}"
        ".quote-calc .calc-row{display:flex;gap:12px;margin-bottom:4px;font-size:11px}"
        ".quote-calc .calc-label{color:#8b949e;min-width:90px}"
        ".quote-calc .calc-val{flex:1;font-weight:600}"
        ".quote-calc .calc-pass{color:#00c853;font-weight:700}"
        ".quote-calc .calc-warn{color:#ff6d00;font-weight:700}"
        ".quote-calc .calc-fail{color:#ff1744;font-weight:700}"
        ".quote-calc .calc-formula-block{margin-top:6px;background:#161b22;border-radius:4px;padding:8px}"
        ".quote-calc .calc-formula-block .formula-item{color:#8b949e;font-size:11px;margin-bottom:2px}"
        ".quote-calc .calc-formula-block .formula-label{color:#e6edf3;font-weight:600}"
        ".footer{text-align:center;color:#484f58;font-size:11px;padding:20px 0;border-top:1px solid #21262d;margin-top:20px}"
        ".chart-section{margin:20px 0}"
        ".chart-title{font-size:13px;font-weight:700;color:#8b949e;margin-bottom:8px}"
        "#tv-chart{width:100%;height:360px;border-radius:8px;overflow:hidden;background:#161b22}"
        "</style>"
        "</head>"
        "<body>"
        "<div class='report-container'>"
        "<div class='report-header'>"
        "<div class='report-title'>📈 " + ticker + " 买入分析报告</div>"
        "<div class='report-subtitle'>Brooks 五层过滤 · 字幕原文引用 · 计算逻辑全透明 · " + TODAY + "</div>"
        "</div>"
        "<div class='grade-banner'>"
        "<div class='grade-badge'>" + grade + "</div>"
        "<div class='grade-info'>"
        "<div class='grade-label'>" + gl + "</div>"
        "<div class='grade-detail'>通过 " + str(result["passed_layers"]) + "/5 层 · 总分 " + str(result["total_score"]) + "</div>"
        "</div></div>"
        + stage_banner +
        # ── TradingView K线图 ─────────────────────────────────
        (("<div class='chart-section'>"
        "<div class='chart-title'>📊 日线 K线（近60日）</div>"
        "<div id='tv-chart'></div>"
        "<div style='display:none' id='kline-data'>" + (json.dumps(_make_kline_json(bars)) if bars else "[]") + "</div>"
        "<div class='chart-title' style='margin-top:16px'>📊 小时K线（近60根）</div>"
        "<div id='tv-chart-1h'></div>"
        "<div style='display:none' id='kline-data-1h'>" + (json.dumps(_make_kline_json(bars_1h)) if bars_1h else "[]") + "</div>"
        "</div>") if bars else "") +
        _bps_html +
        "<div class='entry-box'>"
        "<div class='entry-item'><div class='entry-label'>入场价</div><div class='entry-value' style='color:#00c853'>" + str(entry_v) + "</div></div>"
        "<div class='entry-item'><div class='entry-label'>止损价</div><div class='entry-value' style='color:#ff1744'>" + str(stop_v) + "</div></div>"
        "<div class='entry-item'><div class='entry-label'>目标价</div><div class='entry-value' style='color:#2979ff'>" + str(tgt_v) + "</div></div>"
        "<div class='entry-item'><div class='entry-label'>盈亏比</div><div class='entry-value " + rc + "'>" + str(rr_v) + ":1</div></div>"
        "</div>"
        + score_bars +
        "<h2>五层过滤详情（字幕原文 → 计算逻辑 → 决策结论）</h2>"
        + layers_html +
        "<div class='footer'>Brooks 五层买入过滤系统 · 方方土价格行为学 P02-P16 · " + TODAY + "<br>本报告仅供学习研究，不构成投资建议</div>"
        "</div>"
        "<script src='https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js'></script>"
        "<script>"
        "(function(){"
        "  function initChart(containerId, dataId, priceLines) {"
        "    var data = [];"
        "    try { data = JSON.parse(document.getElementById(dataId).textContent || '[]'); } catch(e){}"
        "    if (!data.length) return;"
        "    var container = document.getElementById(containerId);"
        "    if (!container) return;"
        "    var chart = LightweightCharts.createChart(container, {"
        "      width: container.clientWidth || 860,"
        "      height: 300,"
        "      layout: { backgroundColor: '#161b22', textColor: '#8b949e' },"
        "      grid: { vertLines: { color: '#21262d' }, horzLines: { color: '#21262d' } },"
        "      crosshair: { mode: 1 },"
        "      timeScale: { timeVisible: true, borderColor: '#30363d' },"
        "      rightPriceScale: { borderColor: '#30363d' },"
        "      handleScroll: true, handleScale: true"
        "    });"
        "    var cs = chart.addCandlestickSeries({"
        "      upColor: '#00c853', downColor: '#ff1744',"
        "      borderUpColor: '#00c853', borderDownColor: '#ff1744',"
        "      wickUpColor: '#00c853', wickDownColor: '#ff1744'"
        "    });"
        "    priceLines.forEach(function(pl){ cs.createPriceLine(pl); });"
        "    cs.setData(data);"
        "    chart.timeScale().fitContent();"
        "    window.addEventListener('resize', function(){ chart.applyOptions({ width: container.clientWidth }); });"
        "  }"
        "  var bp = " + json.dumps(_build_price_lines(result, bars)) + ";"
        "  initChart('tv-chart', 'kline-data', bp);"
        "  var bp1h = " + json.dumps(_build_price_lines_1h(result, bars_1h)) + ";"
        "  initChart('tv-chart-1h', 'kline-data-1h', bp1h);"
        "})();"
        "</script>"
        "</body></html>"
    )
    return html



def generate_top_report(tickers: list, results: list, total_count: int = 0) -> str:
    """生成多股票TOP报告（索引页）"""
    rows = ""
    grade_colors = {"A": "#00c853", "B": "#ffd600", "C": "#ff6d00", "D": "#ff1744"}
    for i, (ticker, r) in enumerate(zip(tickers, results), 1):
        gc = grade_colors.get(r["grade"], "#9e9e9e")
        rr = r["layers"].get("L5", {}).get("details", {})
        si = r.get("stage_info", {})
        stage_label = si.get("name", si.get("stage", "—"))
        stage_color = {"STAGE_4": "#ff9800", "STAGE_2": "#00c853", "STAGE_3": "#ffd600", "STAGE_1": "#00bcd4", "STAGE_5": "#ff1744", "STAGE_F": "#9e9e9e"}.get(si.get("stage", ""), "#8b949e")
        rows += f'''
        <tr>
            <td style="text-align:center;font-weight:700">{i}</td>
            <td><a href="#{ticker}" style="color:#58a6ff;font-weight:700">{ticker}</a></td>
            <td style="text-align:center;color:{gc};font-weight:800;font-size:16px">{r["grade"]}</td>
            <td style="text-align:center;font-size:12px;font-weight:700;color:{stage_color}">{stage_label}</td>
            <td style="text-align:center;color:#8b949e">{r["passed_layers"]}/5</td>
            <td style="text-align:center;font-weight:700">{r["total_score"]}</td>
            <td style="color:#00c853">{rr.get("entry","—")}</td>
            <td style="color:#ff1744">{rr.get("stop_loss","—")}</td>
            <td style="color:#2979ff">{rr.get("target","—")}</td>
            <td style="color:{"#00c853" if rr.get("rr_ratio",0)>=3 else "#ff6d00"};font-weight:700">{rr.get("rr_ratio","—")}:1</td>
        </tr>'''
    return f'''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>买入候选 TOP{len(tickers)} {TODAY}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background: #0d1117; color: #e6edf3; font-size: 14px; }}
.report-container {{ max-width: 1000px; margin: 0 auto; padding: 24px 20px; }}
.report-title {{ font-size: 24px; font-weight: 800; color: #f0f6fc; margin-bottom: 4px; }}
.report-subtitle {{ color: #8b949e; font-size: 13px; margin-bottom: 20px; }}
table {{ width: 100%; border-collapse: collapse; }}
th {{ background: #161b22; color: #8b949e; font-size: 11px; text-transform: uppercase; padding: 8px 10px; text-align: left; border-bottom: 1px solid #21262d; }}
td {{ padding: 10px; border-bottom: 1px solid #21262d; color: #e6edf3; }}
tr:hover td {{ background: #161b22; }}
.section {{ background: #161b22; border-radius: 10px; margin-bottom: 40px; overflow: hidden; }}
.section-header {{ background: #21262d; padding: 12px 20px; font-size: 14px; font-weight: 700; color: #f0f6fc; border-bottom: 1px solid #30363d; }}
</style>
</head>
<body>
<div class="report-container">
<div class="report-title">🏆 买入候选 STAGE_1/3/4 · {len(results)} 只 · {TODAY}</div>
<div class="report-subtitle">Brooks 五层过滤系统 · 通过≥4层的候选股票</div>

<div class="section">
<div class="section-header">📊 候选列表</div>
<table>
<thead>
<tr>
    <th>#</th><th>股票</th><th>评级</th><th>阶段</th><th>通过层数</th><th>总分</th>
    <th>入场价</th><th>止损价</th><th>目标价</th><th>盈亏比</th>
</tr>
</thead>
<tbody>{rows}</tbody>
</table>
</div>
</div>
</body>
</html>'''


def run_report(tickers: list, output_dir: str = None):
    """运行选股并生成报告。依赖已在模块顶部导入。
    不限制数量，收集所有 STAGE_1/3/4 候选，按 stage 优先级 + score 排序。
    """
    output_dir = Path(output_dir) if output_dir else BASE / "exp9" / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    spy_bars = load_klines("SPY")
    results = []
    for t in tickers:
        bars = load_klines(t, lookback=120)
        if not bars:
            continue
        bars_1h = load_1h_klines(t, lookback=80)
        sig = detect_signal_bar(bars)
        # daily_entry = 信号K高点 + 1tick = Buy Stop 挂单价
        # detect_signal_bar 评估的是 bars[-1]（最新一根K线）
        # 所以信号K的最高价就是 bars[-1]["high"]
        daily_entry = float(bars[-1]["high"]) + 0.01 if sig.get("quality", "NONE") != "NONE" else None
        eng = BuyFilterEngine(t, bars, spy_bars)
        r = eng.run(bars_1h=bars_1h, daily_entry_price=daily_entry)
        # 只保留 STAGE_1/3/4（排除 STAGE_F / STAGE_5 / STAGE_0）
        if r["stage"] in ("STAGE_1", "STAGE_3", "STAGE_4"):
            results.append((t, r, bars, bars_1h))

    # 按 stage 优先级 + score 排序
    STAGE_SORT = {"STAGE_4": 0, "STAGE_2": 1, "STAGE_3": 2, "STAGE_1": 3}
    results.sort(key=lambda x: (STAGE_SORT.get(x[1]["stage"], 99), -x[1]["total_score"]))

    # 生成单股报告
    for ticker, r, bars, bars_1h in results:
        html = generate_stock_report(ticker, r, bars, bars_1h)
        stage = r.get("stage", "STAGE_UNKNOWN")
        path = output_dir / f"{TODAY_SHORT}_{stage}_{ticker}.html"
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  ✅ {ticker} [{stage}] → {path.name}")

    # 生成索引页
    top_tickers = [t for t, r in results]
    index_html = generate_top_report(top_tickers, [r for _, r in results], len(results))
    index_path = output_dir / f"{TODAY_SHORT}_index.html"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"\n  📋 索引页 → {index_path.name}")
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", nargs="?", help="单股代码，如 AAPL")
    parser.add_argument("--top", type=int, default=5, help="生成Top N报告")
    parser.add_argument("--all", action="store_true", help="扫描全股票池")
    args = parser.parse_args()

    # 预加载所有需要的数据处理函数
    from p_buy_filter import scan_pool, BuyFilterEngine, load_1h_klines, detect_signal_bar

    spy_bars = load_klines("SPY")

    if args.ticker:
        # 单股模式
        bars = load_klines(args.ticker, lookback=120)
        if not bars:
            print(f"❌ 未找到 {args.ticker} 的数据")
            sys.exit(1)
        bars_1h = load_1h_klines(args.ticker, lookback=80)
        sig = detect_signal_bar(bars)
        daily_entry = float(bars[-1]["high"]) + 0.01 if sig.get("quality", "NONE") != "NONE" else None
        eng = BuyFilterEngine(args.ticker, bars, spy_bars)
        r = eng.run(bars_1h=bars_1h, daily_entry_price=daily_entry)
        stage = r.get("stage", "STAGE_0")
        html = generate_stock_report(args.ticker, r, bars, bars_1h)
        out_path = BASE / "exp9" / "outputs" / f"{TODAY_SHORT}_{stage}_{args.ticker}.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"✅ 报告已生成: {out_path}")

    elif args.all or args.top:
        pool_file = BASE / "TradingAgents" / "fintech" / "stock_pool.json"
        with open(pool_file) as f:
            pool = json.load(f)
        tickers = [s["code"] for s in pool["stocks"] if s["code"] != "SPY"]
        print(f"🔍 扫描 {len(tickers)} 只股票，收集 STAGE_1/3/4 候选...")
        print(f"\n生成详细报告（STAGE_1/3/4 候选）:")
        run_report(tickers)

    else:
        parser.print_help()


# ─────────────────────────────────────────────────────────────────────────────
# Helper: L1 extra data + quote calcs
# ─────────────────────────────────────────────────────────────────────────────
def _make_l1_extra(l1, l1d):
    if not l1d:
        return ""
    return (
        "<div class='data-table'>"
        "<div class='data-row'><span class='dt-label'>SPY 最新价</span><span class='dt-value'>" + str(l1d.get("latest_close","N/A")) + "</span></div>"
        "<div class='data-row'><span class='dt-label'>EMA20</span><span class='dt-value'>" + str(l1d.get("ema20","N/A")) + "</span></div>"
        "<div class='data-row'><span class='dt-label'>EMA50</span><span class='dt-value'>" + str(l1d.get("ema50","N/A")) + "</span></div>"
        "<div class='data-row'><span class='dt-label'>EMA200</span><span class='dt-value'>" + str(l1d.get("ema200","N/A")) + "</span></div>"
        "<div class='data-row'><span class='dt-label'>趋势判断</span><span class='dt-value' style='color:#00c853;font-weight:700'>" + str(l1.get("regime","N/A")) + "</span></div>"
        "</div>"
    )


def _make_l2_extra(l2, h1, ts_trend, ticker):
    h1_bar = h1.get("h1_bar", {})
    h1_inv = h1.get("h1_invalidated", False)
    h1_date_str = ("✅ " + h1_bar.get("date","")) if h1_bar else "❌ 无"
    h1_detail = ("开" + str(round(h1_bar.get("open",0),2)) + " 高" + str(round(h1_bar.get("high",0),2)) +
                 " 低" + str(round(h1_bar.get("low",0),2)) + " 收" + str(round(h1_bar.get("close",0),2))) if h1_bar else "—"
    h1_inv_str = "⚠️已失效" if h1_inv else "✅有效"
    h1_inv_color = "#ff6d00" if h1_inv else "#00c853"
    return (
        "<div class='data-table'>"
        "<div class='data-row'><span class='dt-label'>" + ticker + " 最新价</span><span class='dt-value'>" + str(ts_trend.get("latest_close","N/A")) + "</span></div>"
        "<div class='data-row'><span class='dt-label'>EMA20</span><span class='dt-value'>" + str(ts_trend.get("ema20","N/A")) + "</span></div>"
        "<div class='data-row'><span class='dt-label'>EMA50</span><span class='dt-value'>" + str(ts_trend.get("ema50","N/A")) + "</span></div>"
        "<div class='data-row'><span class='dt-label'>均线多头排列</span><span class='dt-value'>" + ("✅ 是" if ts_trend.get("ema20_above_ema50") and ts_trend.get("ema50_above_ema200") else "❌ 否") + "</span></div>"
        "<div class='data-row'><span class='dt-label'>H1信号日期</span><span class='dt-value'>" + h1_date_str + "</span></div>"
        "<div class='data-row'><span class='dt-label'>H1详情</span><span class='dt-value'>" + h1_detail + "</span></div>"
        "<div class='data-row'><span class='dt-label'>H1失效检测</span><span class='dt-value' style='color:" + h1_inv_color + ";font-weight:700'>" + h1_inv_str + "</span></div>"
        "</div>"
    )


def _make_l3_extra(l3, retr):
    if not retr:
        return ""
    return (
        "<div class='data-table'>"
        "<div class='data-row'><span class='dt-label'>入场形态</span><span class='dt-value' style='color:#00c853;font-weight:700'>" + str(l3.get("form_type","N/A")) + "</span></div>"
        "<div class='data-row'><span class='dt-label'>当前回撤幅度</span><span class='dt-value'>" + str(retr.get("retracement_pct","N/A")) + "%</span></div>"
        "<div class='data-row'><span class='dt-label'>50%回撤位</span><span class='dt-value'>" + str(retr.get("pct_50_level","N/A")) + "</span></div>"
        "<div class='data-row'><span class='dt-label'>距50%位</span><span class='dt-value'>" + ("✅ 接近" if retr.get("near_50_pct") else "❌ 远离") + "</span></div>"
        "<div class='data-row'><span class='dt-label'>近期波段高点</span><span class='dt-value'>" + str(retr.get("max_high","N/A")) + "</span></div>"
        "</div>"
    )


def _make_l4_extra(sig, cq):
    if not sig:
        return ""
    sig_q = sig.get("quality", "N/A")
    sig_q_color = "#00c853" if sig_q == "STRONG" else "#ffd600" if sig_q == "MEDIUM" else "#ff6d00"
    sig_vol = sig.get("vol_ratio", 0)
    sig_vol_color = "#ff6d00" if (sig_vol and sig_vol < 0.7) else "#00c853"
    close_pct = sig.get("close_position_pct", 0)
    body_r = cq.get("body_ratio", 0)
    return (
        "<div class='data-table'>"
        "<div class='data-row'><span class='dt-label'>信号K日期</span><span class='dt-value'>" + str(sig.get("date","—")) + "</span></div>"
        "<div class='data-row'><span class='dt-label'>K线质量</span><span class='dt-value' style='color:" + sig_q_color + ";font-weight:700'>" + sig_q + "</span></div>"
        "<div class='data-row'><span class='dt-label'>实体占比</span><span class='dt-value'>" + ("%.0f%%(✅趋势K)" if cq.get("is_trend_bar") else "%.0f%%(❌震荡K)") % (body_r*100) + "</span></div>"
        "<div class='data-row'><span class='dt-label'>收盘位置</span><span class='dt-value'>" + ("阳线" if cq.get("is_bullish") else "阴线") + " (" + "%.1f%%" % (close_pct*100) + ")</span></div>"
        "<div class='data-row'><span class='dt-label'>量能vs均量</span><span class='dt-value' style='color:" + sig_vol_color + "'>" + "%.2fx" % sig_vol + "</span></div>"
        "</div>"
    )


def _make_l5_extra(rr):
    if not rr:
        return ""
    return (
        "<div class='data-table'>"
        "<div class='data-row'><span class='dt-label'>入场价</span><span class='dt-value' style='color:#00c853;font-weight:700'>" + str(rr.get("entry","N/A")) + "</span></div>"
        "<div class='data-row'><span class='dt-label'>止损价</span><span class='dt-value' style='color:#ff1744;font-weight:700'>" + str(rr.get("stop_loss","N/A")) + " <span style='color:#8b949e;font-size:11px'>(" + str(rr.get("stop_loss_date","?")) + ")</span></span></div>"
        "<div class='data-row'><span class='dt-label'>目标价</span><span class='dt-value' style='color:#2979ff;font-weight:700'>" + str(rr.get("target","N/A")) + "</span></div>"
        "<div class='data-row'><span class='dt-label'>盈亏比</span><span class='dt-value' style='color:#00c853;font-weight:700'>" + str(rr.get("rr_ratio","N/A")) + ":1</span></div>"
        "<div class='data-row'><span class='dt-label'>MM A点(高点)</span><span class='dt-value'>" + str(rr.get("mm_swing_high","?")) + " <span style='color:#8b949e;font-size:11px'>(" + str(rr.get("mm_swing_high_date","?")) + ")</span></span></div>"
        "<div class='data-row'><span class='dt-label'>MM B点(低点)</span><span class='dt-value'>" + str(rr.get("mm_swing_low","?")) + " <span style='color:#8b949e;font-size:11px'>(" + str(rr.get("mm_swing_low_date","?")) + ")</span></span></div>"
        "<div class='data-row'><span class='dt-label'>投射高度</span><span class='dt-value'>" + str(rr.get("mm_range","?")) + "</span></div>"
        "<div class='data-row'><span class='dt-label'>MM目标</span><span class='dt-value' style='color:#2979ff'>" + str(rr.get("mm_target","?")) + "</span></div>"
        "<div class='data-row'><span class='dt-label'>目标3R</span><span class='dt-value'>" + str(rr.get("target_3r","?")) + "</span></div>"
        "<div class='data-row'><span class='dt-label'>每份风险</span><span class='dt-value'>$" + str(rr.get("risk_per_share","N/A")) + "/股</span></div>"
        "<div class='data-row'><span class='dt-label'>ATR(14)</span><span class='dt-value'>" + str(rr.get("atr","N/A")) + "</span></div>"
        "</div>"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helper: _qc and _qf for building calc rows
# ─────────────────────────────────────────────────────────────────────────────
def _qc(label, val, result_cls, result_txt):
    return (
        "<div class='calc-row'>"
        "<span class='calc-label'>" + label + "</span>"
        "<span class='calc-val " + result_cls + "'>" + str(result_txt) + "</span>"
        "</div>"
    )

def _qf(formula_text):
    return (
        "<div class='calc-formula-block'>"
        "<div class='formula-item'><span class='formula-label'>公式：</span>" + formula_text + "</div>"
        "</div>"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helper: per-quote calculation HTML builder
# ─────────────────────────────────────────────────────────────────────────────
def _build_quote_calcs(ticker, l1, l2, l3, l4, l5):
    calcs = {}
    ts = l2.get("trend", {})
    h1 = l2.get("h1", {})
    retr = l3.get("retracement", {})
    sig = l4.get("signal", {})
    cq = sig.get("candle_data", {})
    rr = l5.get("details", {})
    l1d = l1.get("details", {})
    h1_bar = h1.get("h1_bar", {})
    h1_inv = h1.get("h1_invalidated", False)
    regime = l1.get("regime", "N/A")
    above20 = l1d.get("above_ema20", False)
    above50 = l1d.get("above_ema50", False)
    pass_ema = l1d.get("ema20_above_ema50") and l1d.get("ema50_above_ema200")
    spy_close = l1d.get("latest_close", "—")
    spy_ema20 = l1d.get("ema20", "—")
    spy_ema50 = l1d.get("ema50", "—")
    spy_ema200 = l1d.get("ema200", "—")
    ticker_close = ts.get("latest_close", "—")
    ema20 = ts.get("ema20", "—")
    ema50 = ts.get("ema50", "—")
    ema200 = ts.get("ema200", "—")
    above_ema20 = ts.get("above_ema20", False)
    ema_arr = ts.get("ema20_above_ema50") and ts.get("ema50_above_ema200")
    rel_val = ts.get("rel_strength_20d", 0)
    stock_ret = ts.get("stock_ret_20d", "—")
    spy_ret = ts.get("spy_ret_20d", "—")
    has_h1 = h1.get("has_h1", False)
    h1_date = h1_bar.get("date", "?") if h1_bar else "?"
    h1_low = h1_bar.get("low", 0) if h1_bar else 0
    h1_high = h1_bar.get("high", 0) if h1_bar else 0
    form = l3.get("form_type", "—")
    swing_high = retr.get("max_high", 0)
    retr_pct = retr.get("retracement_pct", 0)
    pct_50 = retr.get("pct_50_level", 0)
    cur = retr.get("current_close", 0)
    near50 = retr.get("near_50_pct", False)
    sig_date = sig.get("date", "—")
    body = cq.get("body_ratio", 0)
    close_pos = sig.get("close_position_pct", 0)
    vol_r = sig.get("vol_ratio", 0)
    qual = sig.get("quality", "—")
    entry = rr.get("entry", 0)
    stop = rr.get("stop_loss", 0)
    tgt = rr.get("target", 0)
    mm_a = rr.get("mm_swing_high", 0)
    mm_a_d = rr.get("mm_swing_high_date", "?")
    mm_b = rr.get("mm_swing_low", 0)
    mm_b_d = rr.get("mm_swing_low_date", "?")
    mm_rng = rr.get("mm_range", 0)
    mm_tgt = rr.get("mm_target", 0)
    rr_ratio = rr.get("rr_ratio", 0)
    atr = rr.get("atr", 0)
    risk_per = rr.get("risk_per_share", 0)
    tgt_3r = rr.get("target_3r", 0)
    tgt_4r = rr.get("target_4r", 0)

    # ── L1 ──
    calcs["L1_bull_regime"] = (
        _qc("SPY现价", spy_close, "calc-val", spy_close) +
        _qc("EMA20", spy_ema20, "calc-pass" if above20 else "calc-fail", "✅ 多头" if above20 else "❌ 空头") +
        _qc("EMA50", spy_ema50, "calc-pass" if above50 else "calc-fail", "✅ 趋势确认" if above50 else "❌ 低于EMA50") +
        _qc("EMA200", spy_ema200, "calc-pass" if pass_ema else "calc-fail", "✅ 长期多头" if pass_ema else "❌ 低于EMA200") +
        _qc("Brooks 82%规则", "趋势延续", "calc-pass", "✅ EMA多头排列 → 82%概率延续") +
        _qf("判断：SPY收盘 > EMA20 > EMA50 > EMA200 → 强趋势延续。当前SPY=" + str(spy_close) + "，EMA20=" + str(spy_ema20) + "，趋势" + ("延续" if above20 else "破坏"))
    )
    calcs["L1_trend_above_ema20"] = (
        _qc("SPY现价", spy_close, "calc-val", spy_close) +
        _qc("EMA20", spy_ema20, "calc-pass" if above20 else "calc-fail", "✅ SPY在EMA20之上" if above20 else "❌ SPY在EMA20之下") +
        _qf("判断：SPY收盘 > EMA20 → 牛市环境成立。当前SPY=" + str(spy_close) + "，EMA20=" + str(spy_ema20) + "。")
    )
    calcs["L1_bull_stages"] = (
        _qc("市场阶段", regime, "calc-pass" if regime=="BULL" else "calc-fail", "🟢 牛市" if regime=="BULL" else "🔴 熊市" if regime=="BEAR" else "🟡 震荡") +
        _qc("EMA多头排列", "是" if pass_ema else "否", "calc-pass" if pass_ema else "calc-warn", "✅ 符合突破/窄通道阶段" if regime=="BULL" and pass_ema else "⚠️ 需观察") +
        _qf("牛市循环：突破 → 窄通道 → 宽通道 → 震荡区间。当前" + ("EMA多头排列，处于强势阶段" if pass_ema else "非完全多头排列"))
    )
    calcs["L1_internal_decay"] = (
        _qc("SPY vs EMA20", str(spy_close)+" vs "+str(spy_ema20), "calc-pass" if above20 else "calc-fail", "✅ SPY在EMA20之上，无内部衰退信号") +
        _qf("内部衰退 = SPY创新高 + 广度指标下降。当前SPY在EMA20之上，无此信号。")
    )

    # ── L2 ──
    h1_status = "⚠️已失效" if h1_inv else "✅有效"
    h1_cls = "calc-warn" if h1_inv else "calc-pass"
    calcs["L2_H1_signal"] = (
        _qc("H1信号", h1_date, "calc-pass" if has_h1 else "calc-fail", "✅ 发现H1信号 "+h1_date if has_h1 else "❌ 无H1信号") +
        _qc("H1 K线", "H="+("%.2f" % h1_high)+" L="+("%.2f" % h1_low), "calc-val", "Bar结构：O/H/L/C") +
        _qc("H1公式", "bar[i-1].close > bar[i-2].high", "calc-val", "✅ 条件满足" if has_h1 else "❌ 条件未满足") +
        _qc("H1失效检测", h1_status, h1_cls, "当前收盘"+str(ticker_close)+" vs H1低点"+("%.2f" % h1_low)+(" → 跌破，H1失效" if h1_inv else " → 守住，H1有效")) +
        _qf("H1 = 回调后第一根突破前高的阳线。失效条件：current_close < H1_low。当前" + str(ticker_close) + (" < "+"%.2f" % h1_low+" → H1已失效" if h1_inv else " ≥ "+"%.2f" % h1_low+" → H1仍有效"))
    )
    calcs["L2_trend_above_ema"] = (
        _qc(ticker+"现价", ticker_close, "calc-val", ticker_close) +
        _qc("EMA20", ema20, "calc-pass" if above_ema20 else "calc-fail", "✅ 在EMA20之上" if above_ema20 else "❌ 在EMA20之下") +
        _qc("均线排列", "多头" if ema_arr else "空头/混乱", "calc-pass" if ema_arr else "calc-fail", "✅ EMA20>50>200" if ema_arr else "❌ 排列破坏") +
        _qf("多头排列 = EMA20 > EMA50 > EMA200。当前" + ("✅ 多头排列" if ema_arr else "❌ 非多头排列"))
    )
    calcs["L2_H3_warning"] = (
        _qc("H1信号", "有" if has_h1 else "无", "calc-pass" if has_h1 else "calc-warn", "✅ 有H1（趋势未端否）" if has_h1 else "⚠️ 无H1") +
        _qf("H3 = 第三推，通常是趋势末尾信号弱。L2通过EMA位置判断趋势方向，不直接判断H3，但若H1信号出现且价格远离EMA20，需警惕H3。")
    )
    calcs["L2_pullback_importance"] = (
        _qc("回撤幅度", "%.1f%%" % retr_pct, "calc-pass" if retr_pct < 50 else "calc-warn", "✅ 合理回撤" if retr_pct < 50 else "⚠️ 深度回撤") +
        _qc("50%位", "%.2f" % pct_50 if pct_50 else "—", "calc-pass" if near50 else "calc-fail", "✅ 接近" if near50 else "❌ 远离") +
        _qf("Brooks原文：回撤为交易员提供高胜率入场机会。永远不追高，只在回撤中买。当前回撤" + "%.1f%%" % retr_pct + "，" + ("在合理范围" if retr_pct < 50 else "需警惕"))
    )

    # ── L3 ──
    calcs["L3_50pct_retracement"] = (
        _qc("波段高点A", "%.2f" % swing_high if swing_high else "—", "calc-val", "近期20日波段高点") +
        _qc("50%回撤位", "%.2f" % pct_50 if pct_50 else "—", "calc-pass" if near50 else "calc-fail", "✅ 接近" if near50 else "❌ 远离") +
        _qc("当前价格", "%.2f" % cur if cur else "—", "calc-val", "回撤后价位") +
        _qc("回撤幅度", "%.1f%%" % retr_pct, "calc-pass" if retr_pct < 50 else "calc-warn", "✅ 合理(<50%)" if retr_pct < 50 else "⚠️ 深度(≥50%)") +
        _qf("50%回撤 = 核心支撑位。公式：50%_level = (A+B)/2。当前" + "%.1f%%" % retr_pct + "，" + ("在50%附近企稳" if near50 else "超出50%范围"))
    )
    calcs["L3_bread_butter"] = (
        _qc("入场形态", form, "calc-pass" if form=="BREAD_BUTTER" else "calc-warn", "✅ B&B形态" if form=="BREAD_BUTTER" else "⚠️ 非B&B") +
        _qc("回撤幅度", "%.1f%%" % retr_pct, "calc-pass" if retr_pct < 60 else "calc-fail", "✅ <60%合理" if retr_pct < 60 else "❌ >60%过深") +
        _qc("接近50%位", "是" if near50 else "否", "calc-pass" if near50 else "calc-fail", "✅ 接近50%支撑" if near50 else "❌ 不在50%") +
        _qf("Bread & Butter = 回撤<60% + 接近50% + 靠近EMA20。永远不在信号K收盘时买入，回调支撑位挂Buy Limit。")
    )
    dist_ema20 = abs(cur - float(ema20)) if (cur and ema20) else 0
    calcs["L3_ema20_pullback"] = (
        _qc(ticker+"现价", "%.2f" % cur if cur else "—", "calc-val", "回撤后价位") +
        _qc("EMA20", str(ema20), "calc-pass" if above_ema20 else "calc-fail", "✅ 价格在EMA20之上" if above_ema20 else "❌ 价格在EMA20之下") +
        _qc("距EMA20", "%.2f" % dist_ema20, "calc-pass", "✅ 紧贴EMA20（强势特征）") +
        _qf("强势趋势紧贴EMA20运行。回踩EMA20是强势趋势中的最优买入形态。当前价格" + "%.2f" % cur + "，EMA20=" + str(ema20) + "。")
    )
    calcs["L3_deep_retracement"] = (
        _qc("回撤幅度", "%.1f%%" % retr_pct, "calc-pass" if retr_pct < 60 else "calc-warn", "✅ 合理(<60%)" if retr_pct < 60 else "⚠️ 深度回撤(≥60%)") +
        _qc("深度影响", "趋势结构", "calc-warn" if retr_pct >= 60 else "calc-pass", "⚠️ 可能破坏趋势" if retr_pct >= 60 else "✅ 不破坏结构") +
        _qf("Brooks：糟糕背景下信号再好也容易失败。当前回撤" + "%.1f%%" % retr_pct + "，" + ("需警惕" if retr_pct >= 60 else "结构健康"))
    )

    # ── L4 ──
    calcs["L4_trend_bar"] = (
        _qc("信号K日期", sig_date, "calc-val", sig_date+" 日K") +
        _qc("实体占比", "%.1f%%" % (body*100), "calc-pass" if body >= 0.6 else "calc-warn" if body >= 0.4 else "calc-fail", "✅ 趋势K(≥60%)" if body >= 0.6 else "⚠️ 震荡(40-60%)" if body >= 0.4 else "❌ 震荡(<40%)") +
        _qf("趋势K线 = 实体占比≥60%。公式：body_ratio = |close-open|/(high-low)。当前=" + "%.1f%%" % (body*100) + "，" + ("是趋势K" if body >= 0.6 else "非趋势K"))
    )
    calcs["L4_buy_stop"] = (
        _qc("入场方式", "Buy Stop", "calc-pass", "✅ 突破信号K最高点后入场") +
        _qc("入场价", "%.2f" % entry if entry else "—", "calc-val", "当前收盘价（等待触发）") +
        _qf("不在信号K收盘时买入。等待价格向上突破信号K最高点后，在其上方1个Tick挂Buy Stop。")
    )
    bg_cls = "calc-pass" if ema_arr else "calc-fail"
    bg_txt = "✅ 好背景(EMA多头)" if ema_arr else "❌ 差背景"
    calcs["L4_background_first"] = (
        _qc("信号背景", "EMA多头" if ema_arr else "EMA空头", bg_cls, bg_txt) +
        _qc("L1市场", regime, "calc-pass" if regime=="BULL" else "calc-fail", "✅ 牛市" if regime=="BULL" else "⚠️ 非牛市") +
        _qf("Brooks：背景>>信号，背景糟糕时信号再好也容易失败。当前L1=" + regime + " + EMA" + ("多头" if ema_arr else "空头") + "。")
    )
    close_cls = "calc-pass" if close_pos >= 0.8 else "calc-warn"
    calcs["L4_good_bg_good_signal"] = (
        _qc("收盘位置", "%.1f%%" % (close_pos*100), close_cls, "✅ 收在高位" if close_pos >= 0.8 else "⚠️ 非高位收盘") +
        _qc("信号背景", "EMA多头" if ema_arr else "EMA空头", bg_cls, bg_txt) +
        _qf("好背景 = 5+连续K线同向收在高位 + EMA多头排列。当前信号K收盘" + "%.1f%%" % (close_pos*100) + "，" + ("胜率高" if (ema_arr and close_pos >= 0.8) else "需谨慎") + "。")
    )
    ban_cls = "calc-fail" if (regime != "BULL" or not ema_arr) else "calc-pass"
    calcs["L4_bad_bg_ban"] = (
        _qc("市场环境", regime, "calc-pass" if regime=="BULL" else "calc-fail", "✅ 牛市不禁用" if regime=="BULL" else "🔴 熊市/震荡 → 禁用") +
        _qc("EMA排列", "多头" if ema_arr else "空头", "calc-pass" if ema_arr else "calc-fail", "✅ 多头不禁用" if ema_arr else "🔴 空头排列 → 禁用") +
        _qf("差背景 + 差信号 = 完全禁止买入。当前" + regime + " + EMA" + ("多头" if ema_arr else "空头") + "，" + ("不禁用" if ema_arr else "需警惕") + "。")
    )

    # ── L5 ──
    calcs["L5_measured_move"] = (
        _qc("① MM A点", str(mm_a)+" ("+mm_a_d+")", "calc-val", "近期波段起涨点") +
        _qc("② MM B点", str(mm_b)+" ("+mm_b_d+")", "calc-val", "回撤到达点") +
        _qc("③ 投射高度", "%.2f" % mm_rng, "calc-val", "A - B = 结构高度") +
        _qc("④ MM目标C", "%.2f" % mm_tgt, "calc-pass", "B + (A-B) = MM目标") +
        _qf("Measured Move：市场重复等距运动。MM目标 = B + (A-B)。结构高度=" + "%.2f" % mm_rng + " → 目标=" + "%.2f" % mm_tgt + "。")
    )
    stop_dist = entry - stop if (entry and stop) else 0
    stop_atr = stop_dist / atr if atr else 0
    calcs["L5_stop_loss"] = (
        _qc("入场价", "%.2f" % entry if entry else "—", "calc-val", "当前收盘价") +
        _qc("止损价", "%.2f" % stop if stop else "—", "calc-fail", "B点下方0.01") +
        _qc("止损距离", "%.2f (" % stop_dist + "%.1f×ATR)" % stop_atr, "calc-pass" if stop_dist < 1.5*atr else "calc-warn", "✅ 合理(<1.5ATR)" if stop_dist < 1.5*atr else "⚠️ 偏宽(>1.5ATR)") +
        _qf("P02原文：止损永远放在起涨点/波段低点下方。stop = B - 0.01。当前=" + "%.2f" % stop + "。")
    )
    calcs["L5_rr_ratio"] = (
        _qc("盈亏比", "%.2f:1" % rr_ratio, "calc-pass" if rr_ratio >= 3 else "calc-warn" if rr_ratio >= 2 else "calc-fail", "✅ ≥3:1" if rr_ratio >= 3 else "⚠️ ≥2:1" if rr_ratio >= 2 else "❌ <2:1") +
        _qc("公式", "(目标-入场)/(入场-止损)", "calc-val", "(%.2f-%.2f)/(%.2f-%.2f) = %.2f" % (tgt, entry, entry, stop, rr_ratio)) +
        _qf("RR = (target-entry)/(entry-stop)。Brooks：盈亏比≥3:1是基本要求，强趋势≥5:1。当前RR=" + "%.2f" % rr_ratio + "。")
    )
    shares = int(1000 / risk_per) if risk_per else 0
    calcs["L5_1pct_risk"] = (
        _qc("每份风险", "$%.2f" % risk_per if risk_per else "—", "calc-val", "entry - stop") +
        _qc("止损距离", "%.2f" % stop_dist if stop_dist else "—", "calc-val", "每股风险") +
        _qc("1%仓位(假设$100k账户)", "$1000 max", "calc-val", "可买 " + str(shares) + " 股") +
        _qf("P16：每笔交易最大风险不超过账户1%。假设账户10万美元 → 每笔最大风险$1000。当前风险$" + "%.2f" % risk_per + "/股 → 可买" + str(shares) + "股。")
    )
    calcs["L5_profit_discipline"] = (
        _qc("MM目标", "%.2f" % mm_tgt if mm_tgt else "—", "calc-pass", "结构性止盈位") +
        _qc("3R目标", "%.2f" % tgt_3r if tgt_3r else "—", "calc-val", "entry + 3×risk") +
        _qc("4R目标", "%.2f" % tgt_4r if tgt_4r else "—", "calc-val", "entry + 4×risk") +
        _qf("Brooks：自我感觉良好没有用，关键是要能赚到钱！到达Measured Move目标位必须止盈，不可固执持有。")
    )
    return calcs

