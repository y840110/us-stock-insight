#!/usr/bin/env python3
"""
Top3 策略详细交易报告 v2
=======================
资金：100万 | 区间：2020-01-02 → 2026-05-13
仓位：Regime分数决定（从 equity CSV 读取实际仓位）

入场/出场判定：position_pct 从 0→正（入场），正→0（出场）
P&L 计算：直接用 equity curve 的 portfolio value，不自己算
"""
import csv, json
from datetime import datetime
from pathlib import Path
from collections import defaultdict

PROJ   = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析")
OUTPUT = PROJ / "backtest"
INITIAL_CAPITAL = 1_000_000.0
# equity CSV 以 10万为基底，1M = 10x
CSV_SCALE = 10

# ── 读取 equity curve ─────────────────────────────────────────────────────

def load_equity(suffix):
    rows = []
    with open(OUTPUT / f"combined_equity_{suffix}.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "date":         row["date"],
                "value":        float(row["value"]),   # 组合总市值（已含现金）
                "cash":         float(row["cash"]),
                "shares":       int(float(row["shares"])),
                "position_pct": float(row["position_pct"]),
                "regime":       float(row["regime"]),
                "danger":       int(row["danger"]),
                "price":        float(row["price"]),   # SPY 当日收盘价
            })
    return rows


# ── 重建交易 ────────────────────────────────────────────────────────────

def reconstruct_trades(equity_rows, strategy_name, regime_enter, regime_exit, stop_loss=0.10):
    """
    通过 equity curve 的 position_pct 变化重建交易。
    P&L 直接取 equity curve 的 value 差值（不需要自己算持仓市值）。
    """
    trades = []
    trade_id = 0
    in_pos = False

    entry_idx   = None
    entry_date  = None
    entry_px    = None
    entry_value = None  # 组合总市值（入场时）

    for i, row in enumerate(equity_rows):
        pos_pct = row["position_pct"]
        price   = row["price"]
        regime  = row["regime"]
        danger  = row["danger"]
        date_s  = row["date"]
        value   = row["value"]

        if not in_pos:
            # ── 入场 ──
            if pos_pct > 0.05 and row["shares"] > 0:
                in_pos      = True
                entry_idx   = i
                entry_date  = date_s
                entry_px    = price
                entry_value = value * CSV_SCALE  # 缩放到 100万
                entry_regime = regime
                entry_pos   = pos_pct
                stop_loss_px  = round(entry_px * (1 - stop_loss), 2)
                take_profit_px = round(entry_px * (1 + 2 * stop_loss), 2)  # 20%

        else:
            # ── 持仓中 ──
            # 1. 止损（价格触及止损位）
            if price <= stop_loss_px:
                trade_id += 1
                exit_reason = "止损"
                exit_date   = date_s
                exit_idx    = i
                exit_px     = price
                exit_value  = value * CSV_SCALE
                ret_pct     = (exit_value / entry_value - 1) * 100
                pnl         = (exit_value - entry_value)  # 已在100万尺度
                holding     = (datetime.strptime(exit_date, "%Y-%m-%d") -
                               datetime.strptime(entry_date, "%Y-%m-%d")).days
                trades.append({
                    "trade_id":    trade_id,
                    "strategy":    strategy_name,
                    "entry_date":  entry_date,
                    "exit_date":   exit_date,
                    "entry_price": entry_px,
                    "exit_price":  exit_px,
                    "stop_loss":   stop_loss_px,
                    "take_profit": take_profit_px,
                    "exit_reason": exit_reason,
                    "return_pct":  round(ret_pct, 2),
                    "pnl_dollar":  round(pnl, 2),
                    "regime_entry":entry_regime,
                    "regime_exit": regime,
                    "holding_days":holding,
                    "danger_entry":danger,
                    "entry_value": round(entry_value, 2),
                    "exit_value":  round(exit_value, 2),
                })
                in_pos = False

            # 2. 止盈（价格触及止盈位）
            elif price >= take_profit_px:
                trade_id += 1
                exit_reason = "止盈"
                exit_date   = date_s
                exit_idx    = i
                exit_px     = take_profit_px  # 以止盈价记录
                exit_value  = value * CSV_SCALE
                ret_pct     = 20.0
                pnl         = (exit_value - entry_value)  # 已在100万尺度
                holding     = (datetime.strptime(exit_date, "%Y-%m-%d") -
                               datetime.strptime(entry_date, "%Y-%m-%d")).days
                trades.append({
                    "trade_id":    trade_id,
                    "strategy":    strategy_name,
                    "entry_date":  entry_date,
                    "exit_date":   exit_date,
                    "entry_price": entry_px,
                    "exit_price":  round(exit_px, 2),
                    "stop_loss":   stop_loss_px,
                    "take_profit": take_profit_px,
                    "exit_reason": exit_reason,
                    "return_pct":  20.0,
                    "pnl_dollar":  round(pnl, 2),
                    "regime_entry":entry_regime,
                    "regime_exit": regime,
                    "holding_days":holding,
                    "danger_entry":danger,
                    "entry_value": round(entry_value, 2),
                    "exit_value":  round(exit_value, 2),
                })
                in_pos = False

            # 3. Regime 出场
            elif regime < regime_exit:
                trade_id += 1
                exit_reason = "Regime出场"
                exit_date   = date_s
                exit_idx    = i
                exit_px     = price
                exit_value  = value * CSV_SCALE
                ret_pct     = round((exit_value / entry_value - 1) * 100, 2)
                pnl         = (exit_value - entry_value)
                holding     = (datetime.strptime(exit_date, "%Y-%m-%d") -
                               datetime.strptime(entry_date, "%Y-%m-%d")).days
                trades.append({
                    "trade_id":    trade_id,
                    "strategy":    strategy_name,
                    "entry_date":  entry_date,
                    "exit_date":   exit_date,
                    "entry_price": entry_px,
                    "exit_price":  exit_px,
                    "stop_loss":   stop_loss_px,
                    "take_profit": take_profit_px,
                    "exit_reason": exit_reason,
                    "return_pct":  ret_pct,
                    "pnl_dollar":  round(pnl, 2),
                    "regime_entry":entry_regime,
                    "regime_exit": regime,
                    "holding_days":holding,
                    "danger_entry":danger,
                    "entry_value": round(entry_value, 2),
                    "exit_value":  round(exit_value, 2),
                })
                in_pos = False

    return trades


# ── 绩效统计 ──────────────────────────────────────────────────────────────

def calc_stats(trades, equity_rows):
    final_value  = equity_rows[-1]["value"] * CSV_SCALE   # 缩放到 100万
    total_ret    = (final_value / INITIAL_CAPITAL - 1) * 100  # = (last/first-1)*100，scale无关
    vals         = [r["value"] * CSV_SCALE for r in equity_rows]
    peak, max_dd = vals[0], 0
    for v in vals:
        if v > peak: peak = v
        dd = (v - peak) / peak * 100
        if dd < max_dd: max_dd = dd

    n_years = len(equity_rows) / 252
    cagr    = ((final_value / INITIAL_CAPITAL) ** (1/n_years) - 1) * 100 if n_years > 0 else 0

    wins    = [t for t in trades if t["return_pct"] > 0]
    losses  = [t for t in trades if t["return_pct"] <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    avg_win   = sum(t["return_pct"] for t in wins)   / len(wins)   if wins   else 0
    avg_loss  = sum(t["return_pct"] for t in losses) / len(losses) if losses else 0

    # PnL 用 CSV_SCALE 缩放
    wins_pnl  = sum(t["pnl_dollar"] for t in wins)
    loss_pnl  = sum(t["pnl_dollar"] for t in losses)
    pf = abs(wins_pnl / loss_pnl) if loss_pnl != 0 else float('inf')

    return {
        "total_trades": len(trades),
        "wins":        len(wins),
        "losses":      len(losses),
        "win_rate":    round(win_rate, 1),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct":round(avg_loss, 2),
        "profit_factor": round(pf, 2) if pf != float('inf') else "∞",
        "stops":       len([t for t in trades if t["exit_reason"] == "止损"]),
        "profits":     len([t for t in trades if t["exit_reason"] == "止盈"]),
        "regime_outs": len([t for t in trades if t["exit_reason"] == "Regime出场"]),
        "total_return":round(total_ret, 2),
        "cagr":        round(cagr, 2),
        "max_drawdown":round(max_dd, 2),
        "final_value": round(final_value, 2),
        "avg_holding": round(sum(t["holding_days"] for t in trades) / len(trades), 1) if trades else 0,
        "total_pnl":   round(sum(t["pnl_dollar"] for t in trades) * CSV_SCALE, 2),
    }


# ── HTML 报告 ────────────────────────────────────────────────────────────

def generate_html(top3):
    def ret_color(v):
        return "#00c853" if v >= 0 else "#ff1744"
    def dd_color(v):
        return "#ff1744" if v < -15 else ("#ffc107" if v < -8 else "#00c853")

    # ── 各策略 HTML ──
    strategy_sections = ""
    for key, strat_data in top3.items():
        trades = strat_data["trades"]
        s      = strat_data["stats"]
        label  = s["strategy_label"]

        # ── 逐笔明细 ──
        rows_html = ""
        for t in trades:
            rc = ret_color(t["return_pct"])
            reason_class = {"止损":"stop","止盈":"profit","Regime出场":"regime"}.get(t["exit_reason"], t["exit_reason"])
            rows_html += f"""<tr>
              <td class="center">{t['trade_id']}</td>
              <td>{t['entry_date']}</td>
              <td class="num">${t['entry_price']:,.2f}</td>
              <td class="num">{t['entry_value']:,.0f}</td>
              <td class="num">{t['holding_days']}天</td>
              <td>{t['exit_date']}</td>
              <td class="num">${t['exit_price']:,.2f}</td>
              <td class="num">{t['exit_value']:,.0f}</td>
              <td class="num stop">${t['stop_loss']:,.2f}</td>
              <td class="num profit">${t['take_profit']:,.2f}</td>
              <td class="center"><span class="tag {reason_class}">{t['exit_reason']}</span></td>
              <td class="num" style="color:{rc};font-weight:700">{t['return_pct']:+.2f}%</td>
              <td class="num" style="color:{rc}">${t['pnl_dollar']:+,.2f}</td>
              <td class="center">{t['regime_entry']:.1f} → {t['regime_exit']:.1f}</td>
              <td class="center">{t['danger_entry']}</td>
            </tr>"""

        # ── 年度汇总 ──
        yearly = defaultdict(lambda: {"n":0,"wins":0,"rets":[]})
        for t in trades:
            yr = t["exit_date"][:4]
            yearly[yr]["n"] += 1
            yearly[yr]["rets"].append(t["return_pct"])
            if t["return_pct"] > 0: yearly[yr]["wins"] += 1

        yr_html = ""
        for yr in sorted(yearly.keys()):
            y = yearly[yr]
            wr = y["wins"]/y["n"]*100 if y["n"] > 0 else 0
            avg_r = sum(y["rets"])/y["n"] if y["n"] > 0 else 0
            yr_html += f"""<tr>
              <td><strong>{yr}</strong></td>
              <td class="num">{y['n']}</td>
              <td class="num">{y['wins']}</td>
              <td class="num">{wr:.0f}%</td>
              <td class="num" style="color:{ret_color(avg_r)}">{avg_r:+.2f}%</td>
            </tr>"""

        strategy_sections += f"""
<div class="strategy-section" id="{key}">
  <div class="strat-header">
    <h2>📈 {label}</h2>
    <div class="rule-box">规则：Regime ≥ {s['regime_enter']:.1f} 入场 | Regime &lt; {s['regime_exit']:.1f} / 止损10% / 止盈20% 出场</div>
    <div class="kpi-row">
      <div class="kpi"><div class="kn">{s['total_trades']}</div><div class="ks">交易次数</div></div>
      <div class="kpi"><div class="kn" style="color:#00c853">{s['win_rate']:.1f}%</div><div class="ks">胜率</div></div>
      <div class="kpi"><div class="kn">{s['avg_holding']:.0f}天</div><div class="ks">平均持仓</div></div>
      <div class="kpi"><div class="kn" style="color:{'#00c853' if s['profit_factor']!='∞' and float(s['profit_factor'])>1 else '#ffc107'}">{s['profit_factor']}</div><div class="ks">盈亏比</div></div>
      <div class="kpi"><div class="kn" style="color:{ret_color(s['total_return'])}">{s['total_return']:+.1f}%</div><div class="ks">总收益</div></div>
      <div class="kpi"><div class="kn" style="color:{ret_color(s['cagr'])}">{s['cagr']:+.1f}%</div><div class="ks">CAGR</div></div>
      <div class="kpi"><div class="kn" style="color:{dd_color(s['max_drawdown'])}">{s['max_drawdown']:.1f}%</div><div class="ks">最大回撤</div></div>
      <div class="kpi"><div class="kn">${s['final_value']:,.0f}</div><div class="ks">终值(100万)</div></div>
      <div class="kpi"><div class="kn" style="color:{ret_color(s['total_pnl'])}">${s['total_pnl']:+,.0f}</div><div class="ks">累计盈亏</div></div>
    </div>
    <div class="exit-chips">
      <span class="chip stop">⚠️ 止损 {s['stops']}次</span>
      <span class="chip profit">🎯 止盈 {s['profits']}次</span>
      <span class="chip regime">📊 Regime出场 {s['regime_outs']}次</span>
    </div>
  </div>

  <h3>年度绩效</h3>
  <table class="tbl"><thead><tr><th>年</th><th>交易</th><th>盈利</th><th>胜率</th><th>平均收益</th></tr></thead><tbody>{yr_html}</tbody></table>

  <h3>逐笔交易明细（共 {len(trades)} 笔）</h3>
  <div class="scroll">
  <table class="tbl">
    <thead><tr>
      <th>#</th><th>入场日期</th><th>入场价</th><th>入场市值</th>
      <th>持仓</th><th>出场日期</th><th>出场价</th><th>出场市值</th>
      <th>止损位</th><th>止盈位</th>
      <th>出场原因</th><th>收益率</th><th>盈亏(¥)</th>
      <th>Regime</th><th>Danger</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  </div>
</div>"""

    # ── 总览表格 ──
    summary_rows = ""
    for key, strat_data in top3.items():
        s = strat_data["stats"]
        summary_rows += f"""<tr>
          <td><strong>{s['strategy_label']}</strong></td>
          <td class="num">{s['total_trades']}</td>
          <td class="num" style="color:#00c853">{s['win_rate']:.1f}%</td>
          <td class="num">{s['avg_holding']:.0f}天</td>
          <td class="num">{s['stops']}</td>
          <td class="num">{s['profits']}</td>
          <td class="num">{s['regime_outs']}</td>
          <td class="num" style="color:{ret_color(s['total_return'])}">{s['total_return']:+.1f}%</td>
          <td class="num" style="color:{ret_color(s['cagr'])}">{s['cagr']:+.1f}%</td>
          <td class="num" style="color:{dd_color(s['max_drawdown'])}">{s['max_drawdown']:.1f}%</td>
          <td class="num">${s['final_value']:,.0f}</td>
          <td class="num" style="color:{'#00c853' if s['profit_factor']!='∞' and float(s['profit_factor'])>1 else '#ffc107'}">{s['profit_factor']}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Top3 策略详细交易报告 2020-2026</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d1117;color:#e0e0e0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px;line-height:1.5}}
h1{{background:linear-gradient(135deg,#1a1a2e,#16213e);padding:20px 32px;border-bottom:3px solid #e94560;font-size:20px}}
h2{{font-size:16px;padding:16px 0 8px;color:#58a6ff}}
h3{{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#9e9e9e;padding:12px 0 8px;border-bottom:1px solid #30363d;margin-bottom:12px}}
.strategy-section{{background:#161b22;border:1px solid #30363d;border-radius:12px;margin:20px 32px;overflow:hidden}}
.strat-header{{padding:20px 24px;border-bottom:1px solid #30363d}}
.rule-box{{background:#1c2128;border:1px solid #30363d;border-radius:6px;padding:8px 14px;font-size:12px;color:#9ca3af;margin:8px 0}}
.kpi-row{{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0}}
.kpi{{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:10px 14px;text-align:center;min-width:75px;flex:1}}
.kn{{font-size:1.5rem;font-weight:700;line-height:1.2}}
.ks{{font-size:9px;color:#6b7280;margin-top:4px;text-transform:uppercase}}
.exit-chips{{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}}
.chip{{padding:4px 12px;border-radius:12px;font-size:11px;font-weight:600}}
.chip.stop{{background:rgba(255,23,68,0.15);color:#ff1744}}
.chip.profit{{background:rgba(0,200,83,0.15);color:#00c853}}
.chip.regime{{background:rgba(88,166,255,0.15);color:#58a6ff}}
.scroll{{max-height:520px;overflow-y:auto;padding:0 16px}}
.tbl{{width:100%;border-collapse:collapse;font-size:12px;min-width:1100px;table-layout:fixed}}
.tbl th{{background:#1c2128;color:#9ca3af;text-align:left;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #30363d;position:sticky;top:0;z-index:1;white-space:nowrap}}
.tbl td{{padding:8px 10px;border-bottom:1px solid #21262d;vertical-align:middle;white-space:nowrap}}
.tbl tr:hover td{{background:#1c2128}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.center{{text-align:center}}
.tag{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;white-space:nowrap}}
.tag.stop{{background:rgba(255,23,68,0.2);color:#ff6b6b}}
.tag.profit{{background:rgba(0,200,83,0.2);color:#4caf50}}
.tag.regime{{background:rgba(88,166,255,0.2);color:#58a6ff}}
.stop{{color:#ff6b6b}}
.profit{{color:#4caf50}}
.summary-section{{margin:20px 32px}}
.footer{{padding:16px 32px;border-top:1px solid #30363d;color:#6b7280;font-size:11px}}
</style>
</head>
<body>
<h1>🏆 Top3 策略详细交易报告 &nbsp;|&nbsp; SPY 交易回测 &nbsp;|&nbsp; 初始资金 ¥1,000,000</h1>

<div class="summary-section">
  <h2>一、绩效总览（2020-01-02 → 2026-05-13，共 1599 交易日）</h2>
  <table class="tbl">
    <thead><tr>
      <th>策略</th><th>交易</th><th>胜率</th><th>平均持仓</th>
      <th>止损</th><th>止盈</th><th>Regime</th>
      <th>总收益</th><th>CAGR</th><th>最大回撤</th>
      <th>终值</th><th>盈亏比</th>
    </tr></thead>
    <tbody>{summary_rows}</tbody>
  </table>
</div>

{strategy_sections}

<div class="footer">
  生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M")} &nbsp;|&nbsp; 美股投资洞察分析 &nbsp;|&nbsp; 回测区间：2020-01-02 → 2026-05-13
</div>
</body>
</html>"""

    return html


# ── 主程序 ────────────────────────────────────────────────────────────────

def main():
    strategies = {
        "S1b": {"label": "S1b · Regime ≥ 5.5 入场 | Regime &lt; 4 出场 | 止损10% | 止盈20%", "regime_enter": 5.5, "regime_exit": 4.0},
        "S1":  {"label": "S1 · Regime ≥ 6.0 入场 | Regime &lt; 4 出场 | 止损10% | 止盈20%", "regime_enter": 6.0, "regime_exit": 4.0},
        "S4":  {"label": "S4 · Regime ≥ 6 OR Shift≤1 入场 | Regime &lt; 4 出场 | 止损10% | 止盈20%", "regime_enter": 6.0, "regime_exit": 4.0},
    }

    top3 = {}
    for key, cfg in strategies.items():
        equity = load_equity(key)
        trades = reconstruct_trades(equity, cfg["label"], cfg["regime_enter"], cfg["regime_exit"])
        stats  = calc_stats(trades, equity)
        stats["regime_enter"]  = cfg["regime_enter"]
        stats["regime_exit"]   = cfg["regime_exit"]
        stats["strategy_label"] = cfg["label"]
        top3[key] = {"trades": trades, "stats": stats}

        print(f"\n{'='*80}")
        print(f"  {cfg['label']}")
        print(f"  初始资金: ¥1,000,000 | 终值: ¥{stats['final_value']:,.0f}")
        print(f"  总收益: {stats['total_return']:+.1f}%  CAGR: {stats['cagr']:+.1f}%  "
              f"最大回撤: {stats['max_drawdown']:+.1f}%")
        print(f"  交易: {stats['total_trades']}次  胜率: {stats['win_rate']:.1f}%  "
              f"盈亏比: {stats['profit_factor']}  平均持仓: {stats['avg_holding']:.0f}天")
        print(f"  止损: {stats['stops']}次  止盈: {stats['profits']}次  Regime出场: {stats['regime_outs']}次")
        print(f"\n  逐笔交易:")
        print(f"  {'#':<3} {'入场日':<12} {'入场价':>8} {'入场市值':>10} {'持仓':>5} "
              f"{'出场日':<12} {'出场价':>8} {'出场市值':>10} {'原因':<10} {'收益':>7} {'盈亏(¥)':>12}")
        print(f"  {'-'*90}")
        for t in trades:
            print(f"  {t['trade_id']:<3} {t['entry_date']:<12} ${t['entry_price']:>7.2f} "
                  f"¥{t['entry_value']:>9,.0f} {t['holding_days']:>4}天 "
                  f"{t['exit_date']:<12} ${t['exit_price']:>7.2f} ¥{t['exit_value']:>9,.0f} "
                  f"{t['exit_reason']:<10} {t['return_pct']:>+6.2f}% ¥{t['pnl_dollar']:>+11,.2f}")

    # 生成报告
    html = generate_html(top3)
    out_path = OUTPUT / "top3_strategies_detailed_report.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ HTML报告: {out_path}")

    # JSON
    for key, strat_data in top3.items():
        json_path = OUTPUT / f"top3_trades_{key}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"strategy": strat_data["stats"]["strategy_label"],
                        "stats": {k:v for k,v in strat_data["stats"].items() if k not in ("strategy_label","regime_enter","regime_exit")},
                        "trades": strat_data["trades"]}, f, indent=2, ensure_ascii=False)
        print(f"✅ JSON: {json_path}")


if __name__ == "__main__":
    main()
