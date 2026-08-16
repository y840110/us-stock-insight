#!/usr/bin/env python3
"""
FinTech Analysis Pipeline — 总入口
===================================
P1 数据 → P2 择时 → P3 择势 → P4 择股

用法:
    python3 fintech/main.py              # 执行完整流水线
    python3 fintech/main.py --phase 2  # 只执行 P2
    python3 fintech/main.py --phase 3  # 只执行 P3
    python3 fintech/main.py --phase 4  # 只执行 P4
    python3 fintech/main.py --date 2026-05-12  # 指定日期
"""

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

# ── 项目路径配置 ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
KLINES_DIR   = PROJECT_ROOT / "中间过程" / "klines"
STOCK_POOL   = PROJECT_ROOT / "fintech" / "stock_pool.json"
P1_DIR       = PROJECT_ROOT / "fintech" / "p1"

# ── P1 features / scoring 路径（供各阶段使用）───────────────────────────────
p1_features = P1_DIR / "features"
p1_scoring  = P1_DIR / "scoring"

# 动态注册到 sys.path（后续各 phase 直接 import）
for _p in [str(P1_DIR), str(p1_features), str(p1_scoring)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
STATE_DIR    = PROJECT_ROOT / "fintech" / "state"
REPORT_DIR   = PROJECT_ROOT / "fintech" / "reports"

STATE_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ── 全局状态 ─────────────────────────────────────────────────────────────────
class PipelineState:
    """流水线状态，跨阶段共享"""

    def __init__(self, trade_date: str):
        self.date = trade_date
        self.state_file = STATE_DIR / f"{trade_date}.json"
        self.data = {
            "date": trade_date,
            "phases": {},
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        self._load()

    def _load(self):
        if self.state_file.exists():
            with open(self.state_file) as f:
                self.data = json.load(f)

    def save(self):
        self.data["updated_at"] = datetime.now().isoformat()
        with open(self.state_file, "w") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def set_phase(self, name: str, result: dict):
        self.data["phases"][name] = result
        self.save()

    def get_phase(self, name: str) -> dict:
        return self.data.get("phases", {}).get(name, {})

    def get_previous_phase_result(self, current_phase: str) -> dict:
        """获取上一阶段的结果，供当前阶段使用"""
        order = ["p1", "p2", "p3", "p4"]
        idx = order.index(current_phase) if current_phase in order else 0
        if idx > 0:
            return self.get_phase(order[idx - 1])
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# P1 · 数据层
# ══════════════════════════════════════════════════════════════════════════════

def run_p1_data_check(state: PipelineState) -> dict:
    """
    P1 数据层：完整执行数据抓取 + P1 分析
    调用 p1_main.py 中的各 step 函数
    """
    print("\n" + "="*60)
    print("P1 · 数据层  完整执行")
    print("="*60)

    # 动态导入 p1_main
    import importlib
    spec = importlib.util.spec_from_file_location('p1_main', P1_DIR / 'p1_main.py')
    p1_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(p1_mod)

    # Step 1: K线抓取（检查模式，不实际抓取，只报告状态）
    from check_data_freshness import check_all
    freshness = check_all()
    print(f"  数据新鲜度: ✅ {freshness['ok_count']} 只最新  |  ⚠️ {freshness['stale_count']} 只过期")
    print(f"  最后交易日: {freshness['last_trading_day']}")

    # 如果有 stale 数据，执行完整抓取
    if freshness['stale_count'] > 0:
        print(f"\n  检测到 {freshness['stale_count']} 只过期，执行抓取...")
        p1_mod.step_klines(None)  # None = 抓取所有 stale
    else:
        print("  数据已是最新，跳过抓取")

    # Step 2-5: P1 分析模块
    p1_mod.step_breadth()
    p1_mod.step_pullback()
    p1_mod.step_dangerous_shift()
    p1_mod.step_trend_health()
    p1_mod.step_report()

    # 最终新鲜度复核
    freshness_final = check_all()
    result = {
        "ok_count": freshness_final['ok_count'],
        "stale_count": freshness_final['stale_count'],
        "error_count": freshness_final['error_count'],
        "last_trading_day": freshness_final['last_trading_day'],
    }
    state.set_phase("p1", result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# P2 · 择时层
# ══════════════════════════════════════════════════════════════════════════════

def run_p2_regime(state: PipelineState) -> dict:
    """
    P2 择时层：Regime 判断
    调用 fintech/p2/regime.py 模块
    """
    print("\n" + "="*60)
    print("P2 · 择时层  Regime 判断")
    print("="*60)

    from p2.regime import analyze_regime, print_regime, save_html_report as p2_save_html
    result = analyze_regime(KLINES_DIR)
    print_regime(result)

    # 保存 P2 HTML 报告
    p2_html = p2_save_html(result, date=state.date,
                            output_dir=PROJECT_ROOT / "fintech" / "p2" / "layout")
    print(f"  [P2] HTML → {p2_html.name}")

    state.set_phase("p2", result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# P3 · 择势层
# ══════════════════════════════════════════════════════════════════════════════

def run_p3_sector(state: PipelineState) -> dict:
    """
    P3 择势层：板块轮动分析
    调用 fintech/p3/sector_v2.py 模块
    """
    print("\n" + "="*60)
    print("P3 · 择势层  六大维度板块分析")
    print("="*60)

    try:
        from p3.sector_v2 import analyze_sectors_v2, print_sector_analysis_v2
        from p3.sector_v2 import save_html_report_v2 as p3_save_html
        result = analyze_sectors_v2(KLINES_DIR)
        print_sector_analysis_v2(result)

        # 保存 P3 HTML 报告
        p3_html = p3_save_html(result, date=state.date,
                                output_dir=PROJECT_ROOT / "fintech" / "p3" / "layout")
        print(f"  [P3] HTML → {p3_html.name}")

        state.set_phase("p3", result)
        return result

    except Exception as e:
        import traceback as _tb, datetime as _dt
        warn_dir = PROJECT_ROOT / "fintech" / "p3" / "layout" / "warn"
        warn_dir.mkdir(parents=True, exist_ok=True)
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = warn_dir / f"error_p3_{ts}.log"
        tb = _tb.format_exc()
        # 诊断性信息：哪些数据可能有问题
        missing = []
        SECTOR_ETFS = [
            ("SPY","标普500","宽基"), ("QQQ","纳斯达克100","宽基"),
            ("XLK","科技","科技"), ("XLV","医药","医药"), ("XLF","金融","金融"),
            ("XLY","可选消费","消费"), ("XLE","能源","能源"),
            ("GLD","黄金","贵金属"), ("SMH","半导体ETF","半导体"),
            ("SOXX","半导体","半导体"), ("IBIT","加密货币","加密"),
        ]
        for ticker, _name, _cat in SECTOR_ETFS:
            f1 = KLINES_DIR / f"{ticker}_1d.json"
            f2 = KLINES_DIR / f"{ticker}.json"
            if not f1.exists() and not f2.exists():
                missing.append(ticker)
        content = f"""P3 板块分析异常
=======================
时间: {_dt.datetime.now().isoformat()}
错误: {e}

--- Traceback ---
{tb}

--- 可能缺失的数据 ---
{missing}

--- Klines目录 ---
{KLINES_DIR}
目录存在: {KLINES_DIR.exists()}
"""
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  [P3 异常] 已写入日志: {log_file.name}")
        # 返回空结果，避免上游崩溃
        result = {
            "sectors": [], "hot_sectors": [], "cold_sectors": [],
            "warnings": [f"P3执行异常: {e}，已写日志 {log_file.name}"],
            "spy_mom1": 0.0, "spy_mom5": 0.0, "spy_mom20": 0.0,
            "vix": 20.0, "breadth_above20ema": 50.0, "last_date": "",
            "weights": {},
        }
        state.set_phase("p3", result)
        return result


# ══════════════════════════════════════════════════════════════════════════════
# P4 · 择股层
# ══════════════════════════════════════════════════════════════════════════════

def _adapt_p2_regime(p2: dict) -> dict:
    """
    将 P2 输出的 regime 格式（combined.market_regime）
    适配为 G1/G2/G3 策略能识别的格式（top-level regime + score）。

    G1/G2/G3 识别："牛市" / "震荡" / "熊市"
    P2 输出："RISK_OFF" / "BULLISH" / "BEARISH" / "NEUTRAL" / ...
    """
    combined = p2.get("combined", {})
    raw_regime = combined.get("market_regime", "NEUTRAL")
    exposure   = combined.get("target_exposure", 5.0)  # 0-100 的百分比当分数用

    # P2 regime → G1/G2/G3 兼容 regime
    _map = {
        "RISK_OFF":  "熊市",
        "BULLISH":   "牛市",
        "BEARISH":   "熊市",
        "NEUTRAL":   "震荡",
        "RISK_ON":   "牛市",
    }
    regime = _map.get(raw_regime, "震荡")   # 未知 → 默认震荡

    # score 用 exposure（3.8% → score=3.8），在 get_weights 里对应 低仓位区间
    return {"regime": regime, "score": float(exposure)}


def run_p4_screener(state: PipelineState) -> dict:
    """
    P4 择股层：G1/G2/G3 策略打分 + 综合评判
    调用 fintech/p4/stock_picker.py 模块
    """
    print("\n" + "="*60)
    print("P4 · 择股层  G1/G2/G3 策略打分 + 综合评判")
    print("="*60)

    p2 = state.get_phase("p2")
    p3 = state.get_phase("p3")

    # 适配 P2 regime 格式
    p2_adapted = _adapt_p2_regime(p2)
    print(f"  [P4] Regime适配: {p2.get('combined',{}).get('market_regime','N/A')} → "
          f"{p2_adapted['regime']} (score={p2_adapted['score']})")

    # 动态 import P4 模块
    sys.path.insert(0, str(PROJECT_ROOT / "fintech" / "p4"))
    from p4.stock_picker import run_p4, print_p4_result

    try:
        result = run_p4(KLINES_DIR, p2_adapted, p3)
        print_p4_result(result)

        # 保存 P4 HTML 报告
        from p4.synthesize import save_html_report as p4_save_html
        p4_html = p4_save_html(
            result["ranked"], p2_adapted, p3,
            date=state.date,
            output_dir=PROJECT_ROOT / "fintech" / "p4" / "layout",
        )
        print(f"  [P4] HTML → {p4_html.name}")

        state.set_phase("p4", result)
        return result

    except Exception as e:
        import traceback as _tb, datetime as _dt
        warn_dir = PROJECT_ROOT / "fintech" / "p4" / "layout" / "warn"
        warn_dir.mkdir(parents=True, exist_ok=True)
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = warn_dir / f"error_p4_{ts}.log"
        tb = _tb.format_exc()
        content = f"""P4 择股层异常
=======================\n时间: {_dt.datetime.now().isoformat()}\n错误: {e}\n\n--- Traceback ---\n{tb}\n\n--- P2 raw ---\n{p2}\n\n--- P2 adapted ---\n{p2_adapted}\n\n--- P3 hot ---\n{p3.get('hot_sectors', [])}\n\n--- Klines目录 ---\n{KLINES_DIR}\n目录存在: {KLINES_DIR.exists()}\n"""
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  [P4 异常] 已写入日志: {log_file.name}")
        result = {
            "regime": p2_adapted["regime"], "regime_score": p2_adapted["score"],
            "ranked": [], "candidates": [],
            "l1": [], "l2": [], "l3": [], "l4": [],
            "stats": {"G1": 0, "G2": 0, "G3": 0},
            "warnings": [f"P4执行异常: {e}，已写日志 {log_file.name}"],
        }
        state.set_phase("p4", result)
        return result


# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════════════════

PHASE_HANDLERS = {
    1: ("P1 数据层",  run_p1_data_check),
    2: ("P2 择时层",  run_p2_regime),
    3: ("P3 择势层",  run_p3_sector),
    4: ("P4 择股层",  run_p4_screener),
}

# 阶段依赖关系：key 依赖 value
PHASE_DEPS = {
    1: [],       # P1 无依赖
    2: [1],      # P2 依赖 P1
    3: [2],      # P3 依赖 P2
    4: [3],      # P4 依赖 P3
}


def get_required_phases(target_phase: int, state: PipelineState) -> list:
    """
    返回执行 target_phase 所需的前置阶段列表（按顺序）。
    只返回"状态文件中尚无结果"的阶段。
    """
    required = []
    for dep in PHASE_DEPS[target_phase]:
        # 先递归确保依赖的依赖已满足
        required.extend(get_required_phases(dep, state))
    # 去重并追加当前阶段（如果状态文件中没有）
    if not state.get_phase(f"p{target_phase}"):
        required.append(target_phase)
    return required


def run_pipeline(target_phase: int, state: PipelineState):
    """
    执行指定阶段及其所有前置依赖（顺序执行）。
    例：run_pipeline(4, state) → P1→P2→P3→P4
    """
    phases = get_required_phases(target_phase, state)
    if not phases:
        name = PHASE_HANDLERS[target_phase][0]
        print(f"  [{name}] 状态文件中已有结果，跳过（如需强制重跑，请删除状态文件）")
        return
    print(f"  Pipeline 自动补齐前置阶段: {[PHASE_HANDLERS[p][0] for p in phases]}")
    for phase_num in phases:
        name, handler = PHASE_HANDLERS[phase_num]
        try:
            handler(state)
        except Exception as e:
            print(f"  [错误] {name} 执行失败: {e}")
            import traceback
            traceback.print_exc()
            break  # 某阶段失败则中断，不再继续下游


def main():
    parser = argparse.ArgumentParser(
        description="FinTech 分析流水线 | P1→P2→P3→P4 顺序执行，下游阶段自动等待上游完成"
    )
    parser.add_argument(
        "--phase", type=int, default=None,
        help="指定运行哪个阶段 (1-4)，默认运行全部。"
               "指定 P2/P3/P4 时会自动补齐并顺序执行所有前置阶段。"
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="指定交易日 (YYYY-MM-DD)，默认今天"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="强制重跑指定阶段（即使状态文件中已有结果）"
    )
    args = parser.parse_args()

    trade_date = args.date or date.today().strftime("%Y-%m-%d")
    print(f"\n{'='*60}")
    print(f"  FinTech Pipeline  {trade_date}")
    print(f"{'='*60}")

    state = PipelineState(trade_date)

    # 默认跑全部阶段（1→2→3→4）
    target_phase = args.phase if args.phase else 4

    # --force 时清除目标阶段的历史结果，强制重跑
    if args.force and state.get_phase(f"p{target_phase}"):
        print(f"  [Force] 清除 p{target_phase} 历史结果，强制重跑")
        state.data.setdefault("phases", {})
        state.data["phases"].pop(f"p{target_phase}", None)
        state.save()

    run_pipeline(target_phase, state)

    print(f"\n{'='*60}")
    print(f"  Pipeline 完成  {trade_date}")
    print(f"  状态文件: {state.state_file}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
