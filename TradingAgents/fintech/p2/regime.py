"""
p2.regime - P2 择时层统一入口
==================================
封装 p2_master_dispatcher.run()，为 main.py 提供统一接口。

接口：
    analyze_regime(klines_dir)     → 执行完整 P2 分析，返回结果字典
    print_regime(result)          → 打印摘要
    save_html_report(result, date, output_dir) → 保存 HTML
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path
from datetime import datetime

# ── 确保 p2 内部模块可被裸 import 找到 ──────────────────────
# （与 p2_master_dispatcher.py 保持一致：在同一目录下用裸 import）
_p2_dir = Path(__file__).parent
if str(_p2_dir) not in _sys.path:
    _sys.path.insert(0, str(_p2_dir))

from p2_master_dispatcher import run as _dispatcher_run

# ─────────────────────────────────────────────────────────────
def analyze_regime(klines_dir) -> dict:
    """
    执行完整 P2 择时分析。

    参数:
        klines_dir: K线数据目录（Path 或 str，本函数不直接使用）
    """
    trade_date = datetime.now().strftime("%Y-%m-%d")
    result = _dispatcher_run(
        trade_date=trade_date,
        weights=None,
        output_html=True,
        verbose=False,
    )
    return result


# ─────────────────────────────────────────────────────────────
def print_regime(result: dict):
    """打印 P2 择时摘要"""
    combined = result.get("combined", {})
    regime = combined.get("market_regime", "UNKNOWN")
    exposure = combined.get("target_exposure", 0)
    confidence = combined.get("confidence", 0)
    signals = result.get("diagnostic", {}).get("signals", [])

    emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(regime, "⚪")
    print(f"\n  {emoji} Regime: {regime}  (持仓: {exposure:.0f}%  置信度: {confidence:.0%})")
    if signals:
        for s in signals:
            print(f"     {s}")
    else:
        print(f"     无特殊信号")


# ─────────────────────────────────────────────────────────────
def save_html_report(result: dict, date: str, output_dir) -> Path:
    """
    保存 P2 HTML 报告。

    参数:
        result: analyze_regime() 返回的结果字典
        date:   日期字符串（YYYY-MM-DD）
        output_dir: 输出目录（Path 或 str）

    返回:
        生成的 HTML 文件路径
    """
    import shutil

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"p2_{date}.html"
    out_path = output_dir / filename

    # HTML 已由 dispatcher 内部生成，复制到标准路径
    dispatcher_html = result.get("html_path")
    if dispatcher_html:
        dp = Path(dispatcher_html)
        if dp.exists() and dp.resolve() != out_path.resolve():
            shutil.copy2(dp, out_path)
        elif not out_path.exists():
            shutil.copy2(dp, out_path)
    else:
        _write_fallback_html(result, out_path)

    return out_path


# ─────────────────────────────────────────────────────────────
def _write_fallback_html(result: dict, out_path: Path):
    """生成简单 HTML 报告（fallback）"""
    combined = result.get("combined", {})
    regime = combined.get("market_regime", "N/A")
    exposure = combined.get("target_exposure", 0)
    confidence = combined.get("confidence", 0)
    signals = result.get("diagnostic", {}).get("signals", [])
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>P2 择时报告 {result['trade_date']}</title></head>
<body>
<h1>P2 择时报告 · {result['trade_date']}</h1>
<p>Regime: <strong>{regime}</strong> | 持仓: {exposure:.0f}% | 置信度: {confidence:.0%}</p>
<h2>信号</h2>
<ul>{''.join(f'<li>{s}</li>' for s in signals)}</ul>
</body></html>"""
    out_path.write_text(html, encoding="utf-8")
