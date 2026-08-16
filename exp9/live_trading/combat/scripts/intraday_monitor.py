#!/usr/bin/env python3
"""
盘中实时监控推送系统
=========================

功能：
- 交易日启动后，按美东时间每小时推送实战操作建议
- 非交易日 / 未开盘时静默退出
- 09:30 ET 首根 K 线后开始，每小时更新数据 + 推送
- 17:00 ET 收盘后推送"本日结束"总结

用法：
    python3 intraday_monitor.py --check        # 检查状态
    python3 intraday_monitor.py                # 启动今日监控
"""

import sys, argparse, subprocess, json, re, zoneinfo
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
import pytz

# Schema 驱动的消息构建器
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from message_builder import build_message

# ── 路径配置 ──────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent
PROJ_BASE  = BASE_DIR.parent.parent.parent
KLINES_DIR = PROJ_BASE / 'TradingAgents' / '中间过程' / 'klines'
SYS_EVT_SCRIPT = PROJ_BASE / 'TradingAgents' / 'fintech' / 'p1' / 'fetch_us_1h_cdp.py'
ALERTS_SCRIPT  = BASE_DIR / 'alerts_scanner.py'
POSITIONS_FILE = BASE_DIR / 'positions_live.json'
TZ_ET = pytz.timezone('America/New_York')
# 飞书会话 ID（用于盘中推送）
FEISHU_SESSION_ID = 'oc_c76cd3b3bc91d7f50594ab5a242d73a6'

# ── US 交易日历 ───────────────────────────────────────────
US_HOLIDAYS_2026 = {
    date(2026, 1, 1): "New Year's Day",
    date(2026, 1, 19): "Martin Luther King Jr. Day",
    date(2026, 2, 16): "Presidents' Day",
    date(2026, 4, 3): "Good Friday",
    date(2026, 5, 25): "Memorial Day",
    date(2026, 6, 19): "Juneteenth",
    date(2026, 7, 3): "Independence Day (observed)",
    date(2026, 9, 7): "Labor Day",
    date(2026, 11, 26): "Thanksgiving",
    date(2026, 12, 25): "Christmas",
}

def is_us_trading_day(d: date) -> bool:
    """判断是否为 US 交易日"""
    if d.weekday() >= 5:
        return False  # 周六日
    if d in US_HOLIDAYS_2026:
        return False
    return True

def now_et():
    """返回当前美东时间（ET，带 DST 支持）"""
    return datetime.now(TZ_ET)

def is_market_open(et: datetime = None) -> bool:
    """判断美东时间是否在 RTH 时段（9:30-16:00 ET）"""
    if et is None:
        et = now_et()
    if et.hour < 9:
        return False
    if et.hour == 9 and et.minute < 30:
        return False
    if et.hour >= 16:
        return False
    return True

def is_market_closed(et: datetime = None) -> bool:
    """判断美东时间是否已收盘（>= 17:00 ET）"""
    if et is None:
        et = now_et()
    return et.hour > 17  # >17:00 ET 才算收盘（17:00 本身还要跑一次最终扫描）

# ── 核心消息构建 ─────────────────────────────────────────

def build_position_summary() -> str:
    """运行 alerts_scanner.py，提取持仓摘要"""
    import subprocess, json
    from pathlib import Path as P

    alerts_script = ALERTS_SCRIPT
    pos_file = POSITIONS_FILE

    if not alerts_script.exists():
        return "⚠️ alerts_scanner.py 未找到"

    cmd = [
        sys.executable, str(alerts_script),
        '--positions', str(pos_file),
        '--min-rr-buy', '0.5',
        '--min-rr-watch', '0.3',
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(alerts_script.parent),
        )
        output = result.stdout + result.stderr
    except Exception as e:
        return f"⚠️ alerts_scanner 执行失败: {e}"

    # 解析持仓段落
    lines = output.split('\n')
    pos_lines = []
    in_pos = False
    for line in lines:
        if '📋 持仓监控' in line or '持仓监控' in line:
            in_pos = True
        if in_pos:
            pos_lines.append(line)
            if line.strip() == '' and len(pos_lines) > 3:
                break

    if not pos_lines:
        return "📋 持仓：无信号变化"

    summary = '\n'.join(pos_lines[:20])
    return summary

def build_full_summary(market_date: str, scans: list) -> str:
    """构建收盘后总结"""
    msg = f"""📡 盘中监控日报 — {market_date}

🏁 收盘了。今日推送结束。

今日共执行 {len(scans)} 次扫描：
"""
    for i, s in enumerate(scans):
        msg += f"  第{i+1}次（{s.get('time','?')}）: {s.get('summary','?')}\n"
    msg += "\n📋 当前持仓状态：\n"
    msg += build_position_summary()
    return msg

# ── 持仓 Enrichment ─────────────────────────────────────────

def load_enriched_positions() -> list:
    """
    从 positions_live.json 加载持仓，并从对应 1h K 线补全 current_price。
    返回持仓列表，每条包含：ticker, qty, cost_basis, current_price, stop_loss, target, status
    """
    pos_file = POSITIONS_FILE
    if not pos_file.exists():
        return []
    try:
        with open(pos_file, encoding='utf-8') as f:
            content = json.load(f)
        positions = content if isinstance(content, list) else content.get('positions', [])
    except Exception:
        return []

    enriched = []
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        ticker = pos.get('ticker', '')
        if not ticker:
            continue
        # 读取对应 1h K 线获取当前价格
        kline_file = KLINES_DIR / f'{ticker}_1h.json'
        current_price = 0.0
        try:
            if kline_file.exists():
                with open(kline_file, encoding='utf-8') as f:
                    bars = json.load(f).get('data', [])
                if bars:
                    current_price = float(bars[-1].get('close', 0))
        except Exception:
            pass
        enriched.append({
            'ticker':         ticker,
            'qty':            pos.get('qty', pos.get('quantity', 0)),
            'cost_basis':     pos.get('cost_basis', 0),
            'current_price':  current_price,
            'stop_loss':      pos.get('stop_loss', 0),
            'target':         pos.get('target', 0),
            'status':         pos.get('status', pos.get('notes', '')),
        })
    return enriched


# ── 日内扫描（每小时调用）────────────────────────────────

def get_spy_timestamp_et() -> str:
    """
    读取 SPY 1h 最新 bar 的 datetime，
    返回美东时间字符串，精确到小时，格式：'2026-06-03 15:00 ET'
    """
    try:
        spy_file = KLINES_DIR / 'SPY_1h.json'
        with open(spy_file) as f:
            d = json.load(f)
        bars = d.get('data', [])
        if bars:
            last_dt = bars[-1].get('datetime', '')
            if last_dt:
                # datetime 格式: '2026-06-01 14:00:00'
                dt_utc = datetime.strptime(last_dt, '%Y-%m-%d %H:%M:%S')
                dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                et = dt_utc.astimezone(zoneinfo.ZoneInfo('America/New_York'))
                return et.strftime('%Y-%m-%d %H:%M ET')
    except Exception:
        pass
    return ''


def _format_push_message(alert_data: dict, title: str) -> str:
    """将 alert_data 格式化为飞书推送文本"""
    lines = []
    lines.append(f"📡 {title}")
    lines.append(f"⏰ {alert_data.get('time','?')} | SPY数据: {alert_data.get('spy_timestamp','?')}")
    lines.append("")

    # 数据更新
    du = alert_data.get('data_update')
    if du:
        lines.append(f"📥 数据: {du.get('report', '无')}")
        lines.append("")

    # 信号汇总
    summary = alert_data.get('summary', '')
    if summary:
        lines.append(f"📊 {summary}")
        lines.append("")

    # 持仓详情
    pos_lines = alert_data.get('pos_lines', [])
    if pos_lines:
        lines.append("📋 持仓状态")
        lines.append("```")
        # 表头
        lines.append(f"{'股票':<8} {'现价':>8} {'止损':>8} {'目标':>8}   {'状态'}")
        lines.append("─" * 55)
        for pl in pos_lines:
            pl = pl.strip()
            if not pl:
                continue
            # 格式: 🟡AAPL     315.19   310.50   310.50   保本止损...
            # 去掉 emoji 来对齐
            import re
            clean = re.sub(r'[🔴🟡🟢➖🟠]', '', pl).strip()
            # 提取股票代码（首个大写字母开头的词）
            ticker_m = re.match(r'([A-Z]{1,5})', clean)
            ticker = ticker_m.group(1) if ticker_m else clean[:6]
            parts = clean.split()
            # 尝试提取数字
            nums = [p for p in parts if re.match(r'^\d+\.?\d*$', p)]
            if len(nums) >= 3:
                cur_p, stop_p, tgt_p = nums[0], nums[1], nums[2]
                rest = ' '.join(parts[parts.index(nums[2])+1:]) if parts.index(nums[2])+1 < len(parts) else ''
                lines.append(f"{ticker:<8} {cur_p:>8} {stop_p:>8} {tgt_p:>8}   {rest}")
            else:
                lines.append(f"{ticker:<8}   {clean[:40]}")
        lines.append("```")
        lines.append("")

    # 完整文本输出（如果有）
    full = alert_data.get('full_output', '')
    if full:
        # 提取 NOW 和 WATCH 段落
        in_now = False; in_watch = False
        for line in full.split('\n'):
            if '立即买入机会' in line: in_now = True; in_watch = False; lines.append("🟢 立即买入")
            elif '即将买入机会' in line: in_watch = True; in_now = False; lines.append("🟡 即将买入")
            elif line.startswith('==') or line.startswith('─'): in_now = in_watch = False
            elif (in_now or in_watch) and ('🟢' in line or '🟡' in line) and 'AAPL' not in line and 'MSFT' not in line:
                lines.append(line.strip()[:60])

    return '\n'.join(lines)


def _compute_push_hash(alert_data: dict) -> str:
    """
    计算推送内容的稳定哈希，用于去重。
    只要 summary + 持仓状态 + NOW/WATCH 信号数量不变，哈希就不变。
    """
    import hashlib
    parts = [
        alert_data.get('summary', ''),
        alert_data.get('market_date', ''),
    ]
    # 持仓状态：每只股票的 status + current_price（精确到小数点后2位）
    for p in sorted(alert_data.get('positions', []), key=lambda x: x.get('ticker', '')):
        parts.append(f"{p.get('ticker')}:{p.get('status')}:{round(p.get('current_price', 0), 2)}")
    # NOW / WATCH 信号数量
    parts.append(f"now:{len(alert_data.get('now_signals', []))}")
    parts.append(f"watch:{len(alert_data.get('watch_signals', []))}")
    hash_str = '|'.join(parts)
    return hashlib.md5(hash_str.encode()).hexdigest()[:12]


def _push_to_feishu(text: str, alert_data: dict, silent: bool = False) -> bool:
    """
    通过 openclaw message send 推送文本到飞书。
    做内容去重：对比上次推送哈希，相同时跳过推送。
    """
    import hashlib

    # 从 alert_data 获取本次内容哈希
    current_hash = alert_data.get('_pending_hash') or _compute_push_hash(alert_data)

    # 读取上次的推送哈希（从已存在的文件中，覆写前）
    latest_file = BASE_DIR / 'latest_alert.json'
    last_hash = None
    if latest_file.exists():
        try:
            with open(latest_file, encoding='utf-8') as f:
                last_data = json.load(f)
            last_hash = last_data.get('_last_push_hash')
        except Exception:
            pass

    if current_hash == last_hash:
        print(f"   ⏭️  内容无变化（哈希 {current_hash}），跳过推送")
        return True  # 视为成功，不重试

    # 推送
    OPENCLAW = '/home/yudengfeng/.npm-global/bin/openclaw'
    cmd = [
        OPENCLAW, 'message', 'send',
        '--channel', 'feishu',
        '--target', FEISHU_SESSION_ID,
        '--message', text,
    ]
    if silent:
        cmd.append('--silent')
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        pushed = result.returncode == 0
        if pushed:
            # 合并写入：保留已有字段，只更新本次需要持久化的字段
            _persist_alert_with_hash(alert_data, current_hash, latest_file)
        return pushed
    except Exception:
        return False


def _persist_alert_with_hash(alert_data: dict, current_hash: str, latest_file: Path):
    """原子性更新 latest_alert.json：合并已有内容 + 本次哈希"""
    existing = {}
    if latest_file.exists():
        try:
            with open(latest_file, encoding='utf-8') as f:
                existing = json.load(f)
        except Exception:
            pass
    # 合并：保留 _last_push_hash 不变，更新本次字段
    existing.update({k: v for k, v in alert_data.items() if not k.startswith('_')})
    existing['_last_push_hash'] = current_hash
    try:
        with open(latest_file, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except Exception:
        pass



def run_intraday_update(data_update: dict = None, push: bool = True, push_title: str = "盘中推送") -> dict:
    """
    执行一次盘中数据更新 + 扫描
    push=True 时自动推送结果到飞书
    返回：{'time': '14:30 ET', 'summary': '...', 'status': 'ok',
           'spy_timestamp': '14:00 ET', 'data_update': {...}}
    """
    import subprocess, json
    from pathlib import Path as P

    et = now_et()
    time_str = et.strftime('%H:%M ET')
    spy_ts = get_spy_timestamp_et()

    alerts_script = ALERTS_SCRIPT
    pos_file = POSITIONS_FILE

    if not alerts_script.exists():
        return {'time': time_str, 'status': 'error', 'summary': 'alerts_scanner.py 未找到', 'spy_timestamp': spy_ts}

    has_positions = pos_file.exists()

    # 先用 --json 模式获取结构化数据
    json_cmd = [
        sys.executable, str(alerts_script),
        '--min-rr-buy', '0.5',
        '--min-rr-watch', '0.3',
        '--json',
    ]
    text_cmd = [
        sys.executable, str(alerts_script),
        '--min-rr-buy', '0.5',
        '--min-rr-watch', '0.3',
        '--show-all',
    ]  # 纯文本模式（fallback）
    if has_positions:
        json_cmd.insert(3, '--positions')
        json_cmd.insert(4, str(pos_file))
        text_cmd.insert(3, '--positions')
        text_cmd.insert(4, str(pos_file))

    structured_positions = []
    pos_lines = []
    now_count = 0
    watch_count = 0
    output = ''

    try:
        # 优先 JSON 模式
        result = subprocess.run(
            json_cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(alerts_script.parent),
        )
        output = result.stdout
        try:
            scan_data = json.loads(output)
            structured_positions = scan_data.get('positions', [])
            now_count = scan_data.get('now_signals', 0)
            watch_count = scan_data.get('watch_signals', 0)
        except Exception:
            pass  # 回退到文本解析
    except Exception as e:
        pass  # 回退到文本解析

    # 文本模式（解析 NOW/WATCH/持仓行）
    if not structured_positions:
        try:
            result = subprocess.run(
                text_cmd,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(alerts_script.parent),
            )
            output = result.stdout
        except Exception as e:
            return {'time': time_str, 'status': 'error', 'summary': str(e), 'spy_timestamp': spy_ts}

        in_now = False; in_watch = False; in_pos = False
        for line in output.split('\n'):
            if '立即买入机会' in line or 'NOW信号' in line:
                in_now = True; in_watch = False; in_pos = False
            elif '即将买入机会' in line or 'WATCH信号' in line:
                in_watch = True; in_now = False; in_pos = False
            elif '持仓监控' in line:
                in_pos = True; in_now = False; in_watch = False
            elif line.startswith('==') or line.startswith('─'):
                in_now = in_watch = in_pos = False
            elif in_now and '🟢' in line:
                now_count += 1
            elif in_watch and '🟡' in line:
                watch_count += 1
            elif in_pos and ('🟡' in line or '➖' in line or '🟢' in line):
                pos_lines.append(line.strip())

    summary_parts = []
    if now_count > 0:
        summary_parts.append(f"🟢 立即买入 {now_count} 只")
    if watch_count > 0:
        summary_parts.append(f"🟡 即将买入 {watch_count} 只")
    if pos_lines:
        summary_parts.append(f"📋 持仓变动 {len(pos_lines)} 条")
    if not summary_parts:
        summary_parts.append("✅ 无变化，持仓正常")

    alert_data = {
        'title':           push_title,
        'time':            time_str,
        'spy_timestamp':   spy_ts,
        'market_date':     et.strftime('%Y-%m-%d'),
        'market_regime':   '',
        'status':          'ok',
        'summary':         ' | '.join(summary_parts),
        'pos_lines':       pos_lines,
        'data_update':     data_update,
        'full_output':     output,
        'positions':       load_enriched_positions(),  # 包含 current_price 的完整持仓
        'now_signals':     [],
        'watch_signals':   [],
    }

    # 先算本次内容哈希，写入 _pending_hash，再推送
    # 注意：不整体覆写 latest_alert.json（由 _push_to_feishu 合并写入）
    current_hash = _compute_push_hash(alert_data)
    alert_data['_pending_hash'] = current_hash  # 供 _push_to_feishu 读取

    # 自动推送飞书（去重：对比上次推送的哈希）
    if push and alert_data.get('status') == 'ok':
        msg = build_message(alert_data, message_type='intraday_alert', default_title=push_title)
        _push_to_feishu(msg, alert_data)

    return alert_data

# ── 数据新鲜度检查 ───────────────────────────────────────

def check_data_freshness(tickers: list = None) -> dict:
    """
    检查本地 1h 数据是否足够（覆盖当天 RTH 所需的历史）
    返回：{
        'ok': True/False,
        'missing': ['MSTR', ...],
        'stale': ['AAPL', ...],  # 数据不够新的
        'report': '...'
    }
    """
    import json
    from datetime import datetime

    pool_file = PROJ_BASE / 'TradingAgents' / 'fintech' / 'stock_pool.json'
    klines_dir = PROJ_BASE / 'TradingAgents' / '中间过程' / 'klines'

    if tickers is None:
        try:
            with open(pool_file) as f:
                pool = json.load(f)
            tickers = [s['code'] for s in pool.get('stocks', [])]
            tickers = [t for t in tickers if t not in ('TNX', 'DXY', '^VIX')]
        except Exception as e:
            return {'ok': False, 'missing': [], 'stale': [], 'report': f'无法加载股票池: {e}'}

    # 所需最小 bar 数量（到当天 09:30 ET 往前推 2000 根）
    MIN_BARS = 100  # 最少需要这么多 bar 才认为"有数据"

    missing = []
    stale = []   # 数据有但不够新（缺今天）
    fresh = []   # 今天数据已有

    et_today = now_et().date()

    for ticker in tickers:
        fp = klines_dir / f'{ticker}_1h.json'
        if not fp.exists():
            missing.append(ticker)
            continue

        try:
            with open(fp) as f:
                d = json.load(f)
            bars = d.get('data', [])
            if len(bars) < MIN_BARS:
                missing.append(ticker)
                continue

            # 检查最新日期
            latest = max(b.get('datetime', '')[:10] for b in bars if b.get('datetime'))
            if latest < str(et_today):
                stale.append(ticker)
            else:
                fresh.append(ticker)
        except Exception:
            missing.append(ticker)

    total = len(tickers)
    ok = len(missing) == 0 and len(stale) == 0

    report = (f"数据完整性检查：\n"
              f"  ✅ 正常: {len(fresh)} 只\n"
              f"  ⚠️ 数据不新鲜（缺今天）: {len(stale)} 只\n"
              f"  ❌ 数据缺失: {len(missing)} 只\n"
              f"  总计: {total} 只")

    if stale:
        report += f"\n  不新鲜（需今日更新）: {', '.join(stale[:10])}"
        if len(stale) > 10:
            report += f" ... 等 {len(stale)} 只"
    if missing:
        report += f"\n  缺失: {', '.join(missing[:10])}"
        if len(missing) > 10:
            report += f" ... 等 {len(missing)} 只"

    return {'ok': ok, 'missing': missing, 'stale': stale, 'fresh': fresh,
            'report': report, 'total': total}


# ── 数据更新（增量，拉今日最新）──────────────────────────

def update_today_data() -> dict:
    """
    执行今日数据增量更新，返回结构化结果：
    {'ok': True/False, 'success': N, 'failed': N, 'skipped': N,
     'failed_tickers': [...], 'elapsed_s': float, 'report': str}
    """
    import subprocess, re

    updater = SYS_EVT_SCRIPT
    if not updater.exists():
        return {'ok': False, 'success': 0, 'failed': 0, 'skipped': 0,
                'failed_tickers': [], 'elapsed_s': 0,
                'report': f'❌ 数据更新脚本不存在: {updater}'}

    cmd = [sys.executable, str(updater), '--update', '--force']
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(updater.parent),
        )
        output = result.stdout + result.stderr

        # 解析汇总行
        m = re.search(r'✅ 成功: (\d+)  ❌ 失败: (\d+)  ⏭️ 跳过: (\d+)', output)
        success = int(m.group(1)) if m else 0
        failed  = int(m.group(2)) if m else 0
        skipped = int(m.group(3)) if m else 0

        # 解析失败股票列表
        failed_tickers = []
        for line in output.split('\n'):
            if line.startswith('     ❌ ') and ':' in line:
                sym = line.split(':')[0].replace('     ❌ ', '').strip()
                failed_tickers.append(sym)

        # 解析耗时
        em = re.search(r'完成 \((\d+)s\)', output)
        elapsed_s = int(em.group(1)) if em else 0

        ok_flag = failed == 0
        report = (f'数据更新 | 成功 {success} | 失败 {failed} | 跳过 {skipped}'
                  + (f' ({elapsed_s}s)' if elapsed_s else ''))
        if failed_tickers:
            report += f'\n❌ 失败: {', '.join(failed_tickers)}'

        return {
            'ok': ok_flag,
            'success': success,
            'failed': failed,
            'skipped': skipped,
            'failed_tickers': failed_tickers,
            'elapsed_s': elapsed_s,
            'report': report,
        }
    except Exception as e:
        return {'ok': False, 'success': 0, 'failed': 0, 'skipped': 0,
                'failed_tickers': [], 'elapsed_s': 0, 'report': f'❌ 数据更新异常: {e}'}


# ── Cron 调度（通过 openclaw CLI）─────────────────────────

def schedule_today_crons(dry_run: bool = False) -> dict:
    """
    通过 openclaw cron CLI 为今天调度盘中推送。
    使用 isolated session 直接执行脚本并推飞书，main session 是否在线不影响。
    """
    et = now_et()
    today = et.date()

    # 调度时刻：每小时的 :32 分（K线成型后），收盘时 :00
    slots = [
        (9, 32, '首根K线'),
        (10, 32, '盘中'),
        (11, 32, '盘中'),
        (12, 32, '盘中'),
        (13, 32, '盘中'),
        (14, 32, '盘中'),
        (15, 32, '盘中'),
        (16, 32, '盘中'),
        (17, 0, '收盘总结'),
    ]

    # 过滤已过的时刻
    future_slots = [
        (h, m, label) for h, m, label in slots
        if et.hour < h or (et.hour == h and et.minute < m)
    ]

    if not future_slots:
        print("⚠️ 所有推送时刻已过")
        return {'scheduled': [], 'skipped': 'all_past'}

    print(f"📅 计划调度 {len(future_slots)} 个推送时刻:")
    scheduled = []

    for h, m, label in future_slots:
        # 构建 ISO 时间戳（带时区偏移）
        slot_time = et.replace(hour=h, minute=m, second=0, microsecond=0)
        ts_str = slot_time.strftime('%Y-%m-%dT%H:%M:%S%z')
        # Python 的 %z 输出 "-0400"，openclaw 可以接受（会自动转 UTC）
        job_name = f"intraday_{today}_{h:02d}{m:02d}_et"

        WORKSPACE = Path.home() / '.openclaw' / 'workspace'
        COMBAT_DIR_STR = str(BASE_DIR.parent.relative_to(WORKSPACE))
        EXPERTS_DIR_STR = str((PROJ_BASE / 'model' / 'experts').relative_to(WORKSPACE))
        if h == 17 and m == 0:
            title = f"收盘总结 {today}"
        else:
            title = f"盘中推送 {h:02d}:{m:02d} ET"

        if dry_run:
            print(f"  [Dry] {h:02d}:{m:02d} ET → {job_name}")
            scheduled.append(f"{h:02d}:{m:02d} ET [Dry]")
            continue

        # isolated session 直接运行脚本 → 自动推飞书，不依赖 main session 在线
        agent_message = (
            f"请在后台执行以下命令，完成后直接退出（无需回复用户）：\n"
            f"cd /home/yudengfeng/.openclaw/workspace/{COMBAT_DIR_STR} && \n"
            f"PYTHONPATH=/home/yudengfeng/.openclaw/workspace/{EXPERTS_DIR_STR} \n"
            f"python3 scripts/intraday_monitor.py --auto-update\n\n"
            f"该脚本会自动更新数据、扫描市场、并将结果推送到飞书，无需额外操作。"
        )

        cmd = [
            'openclaw', 'cron', 'add',
            '--name', job_name,
            '--at', ts_str,
            '--session', 'isolated',
            '--message', agent_message,
            '--no-deliver',
            '--json',
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                try:
                    raw = result.stdout
                    js = raw[raw.find('{'):]
                    out = json.loads(js)
                    jid = out.get('id', out.get('jobId', '?'))
                except Exception:
                    jid = 'ok'
                print(f"  ✅ {h:02d}:{m:02d} ET → {job_name} (id={jid})")
                scheduled.append(f"{h:02d}:{m:02d} ET")
            else:
                print(f"  ❌ {h:02d}:{m:02d} ET → exit={result.returncode}")
                print(f"     stderr: {result.stderr[:150]}")
        except Exception as e:
            print(f"  ❌ {h:02d}:{m:02d} ET → {e}")

    return {'scheduled': scheduled}


def clear_today_crons():
    """清除今天的所有盘中 cron jobs"""
    today = now_et().date()

    # 先列出所有 jobs，找到今天的 intraday jobs
    list_cmd = ['openclaw', 'cron', 'list', '--json']
    try:
        result = subprocess.run(list_cmd, capture_output=True, text=True, timeout=10)
        # stdout 可能带 warning 前缀，需要找到 JSON 起始位置
        raw = result.stdout
        json_start = raw.find('{')
        jobs_data = json.loads(raw[json_start:]) if json_start >= 0 else {}
        jobs = jobs_data.get('jobs', []) if isinstance(jobs_data, dict) else []
    except Exception:
        jobs = []

    removed = 0
    for j in (jobs if isinstance(jobs, list) else []):
        name = j.get('name', '')
        jid = j.get('id', '')
        if f'intraday_{today}' in name and jid:
            rm_cmd = ['openclaw', 'cron', 'rm', jid]
            try:
                subprocess.run(rm_cmd, capture_output=True, text=True, timeout=10)
                print(f"  🗑️  删除: {name}")
                removed += 1
            except Exception:
                pass

    print(f"已删除 {removed} 个今日 cron jobs")


# ── CLI ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='盘中实时监控推送系统')
    parser.add_argument('--check', action='store_true', help='仅检查数据完整性')
    parser.add_argument('--dry-run', action='store_true', help='演练模式（不实际推送）')
    parser.add_argument('--force-update', action='store_true', help='强制先全量更新数据')
    parser.add_argument('--full', action='store_true', help='强制全量回溯数据（慎用）')
    parser.add_argument('--auto-update', action='store_true',
                       help='盘中扫描前先自动跑增量数据更新（cron 调用时使用）')
    parser.add_argument('--schedule', action='store_true',
                       help='为今天调度所有 cron jobs（盘中监控）')
    parser.add_argument('--clear-schedule', action='store_true',
                       help='清除今日所有 cron jobs')
    args = parser.parse_args()

    et = now_et()
    today = et.date()
    today_str = today.strftime('%Y-%m-%d (%A)')

    print(f"📡 盘中监控系统")
    print(f"   当前时间: {et.strftime('%Y-%m-%d %H:%M ET')} (DST={'是' if et.dst() else '否'})")
    print(f"   今日: {today_str}")

    # ══════════════════════════════════════════════════════════
    # ═  第一层：日程管理（任何日期均可，不受市场状态影响）
    # ══════════════════════════════════════════════════════════
    if args.clear_schedule:
        print("\n🗑️  清除今日 cron jobs...")
        clear_today_crons()
        print("完成")
        sys.exit(0)

    if args.schedule:
        if not is_us_trading_day(today):
            print(f"\n⚠️ 今日（{today_str}）非交易日，请在交易日运行:")
            print(f"   python3 intraday_monitor.py --schedule")
            sys.exit(0)
        print(f"\n📅 为今日（{today_str}）调度盘中 cron jobs...")
        r = schedule_today_crons(dry_run=args.dry_run)
        if r.get('dry_run'):
            print(f"[Dry Run] 演练完成，未实际创建")
        elif r.get('error'):
            print(f"❌ 调度失败: {r['error']}")
        else:
            print(f"\n✅ 成功调度 {len(r.get('scheduled', []))} 个 cron jobs")
            for s in r.get('scheduled', []):
                print(f"   {s}")
        sys.exit(0)

    # ══════════════════════════════════════════════════════════
    # ═  第二层：完整盘中监控（需要交易日 + 市场状态）
    # ══════════════════════════════════════════════════════════
    if not is_us_trading_day(today):
        print(f"\n⏭️ 今日（{today_str}）非交易日，结束。")
        print(f"\n💡 为下一个交易日调度盘中推送:")
        print(f"   python3 intraday_monitor.py --schedule")
        sys.exit(0)

    print(f"\n✅ 今日为交易日")

    # ── 数据完整性检查 ───────────────────────────────
    print("\n🔍 检查本地数据完整性...")
    freshness = check_data_freshness()
    print(freshness['report'])

    if not freshness['ok']:
        print("\n⚠️ 数据不完整，建议先运行数据更新")
        if args.force_update:
            print("\n🚀 强制执行增量更新...")
            print(update_today_data())
        elif args.full:
            print("\n🚀 强制执行全量回溯（耗时较长）...")
            import subprocess
            updater = SYS_EVT_SCRIPT
            cmd = [sys.executable, str(updater), '--full']
            subprocess.run(cmd, cwd=str(updater.parent))
            print("全量回溯完成")

    if args.check:
        sys.exit(0)

    # ── 市场状态判断 ─────────────────────────────────
    if is_market_closed(et):
        print(f"\n🏁 当前已收盘（17:00 ET 后）")
        print("\n📊 执行收盘后最终扫描...")
        du = None
        if args.auto_update:
            print("\n🚀 盘中自动数据更新...")
            du = update_today_data()
            print(du['report'])
        result = run_intraday_update(data_update=du)
        print(f"结果: {result}")
        sys.exit(0)

    if not is_market_open(et):
        # 市场未开盘（当前 < 9:30 ET）
        print(f"\n⏳ 市场未开盘（当前 {et.strftime('%H:%M ET')}，9:30 开市）")
        print("\n💡 为今日自动调度盘中 cron jobs（推荐）:")
        print(f"   python3 intraday_monitor.py --schedule")
        print("\n   或者手动触发盘中扫描:")
        print(f"   python3 intraday_monitor.py")
        sys.exit(0)

    # ── 开盘中：执行盘中扫描（仅手动触发时）────────────
    du = None
    if args.auto_update:
        print("\n🚀 盘中自动数据更新...")
        du = update_today_data()
        print(du['report'])
    print(f"\n🚀 市场开盘中（{et.strftime('%H:%M ET')}），执行盘中监控...")
    result = run_intraday_update(data_update=du)
    print(f"\n📊 扫描结果:")
    print(f"   时间: {result['time']}")
    print(f"   状态: {result['status']}")
    print(f"   摘要: {result.get('summary', '')}")
    if result.get('pos_lines'):
        print(f"\n📋 持仓详情:")
        for line in result['pos_lines'][:10]:
            print(f"   {line}")

if __name__ == '__main__':
    main()
