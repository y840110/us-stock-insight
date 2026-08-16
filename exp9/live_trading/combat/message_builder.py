#!/usr/bin/env python3
"""
Message Builder — Schema 驱动的飞书消息生成器
=============================================

所有飞书推送消息必须通过此模块生成，不可自行拼装字符串。

用法：
    from message_builder import build_message
    text = build_message(alert_data, message_type='intraday_alert')

Schema 定义文件：schema/feishu_message_schema.json
"""

import json
import re
from pathlib import Path
from typing import Any

# ── Schema 路径 ──────────────────────────────────────────────
SCHEMA_DIR = Path(__file__).parent / 'schema'
DEFAULT_SCHEMA = SCHEMA_DIR / 'feishu_message_schema.json'

# ── 全局 Schema 缓存 ────────────────────────────────────────
_schema_cache: dict = {}

def load_schema(schema_path: Path = None) -> dict:
    """加载 Schema，支持缓存"""
    path = schema_path or DEFAULT_SCHEMA
    if str(path) in _schema_cache:
        return _schema_cache[str(path)]
    with open(path, encoding='utf-8') as f:
        schema = json.load(f)
    _schema_cache[str(path)] = schema
    return schema

def get_message_type_schema(schema: dict, message_type: str) -> dict:
    """获取指定消息类型的 Schema"""
    mt = schema.get('message_types', {}).get(message_type)
    if mt is None:
        raise ValueError(f"未知 message_type: {message_type}，可用: {list(schema.get('message_types', {}).keys())}")
    return mt

# ── 条件判断引擎 ────────────────────────────────────────────
def eval_condition(condition: str, data: dict) -> bool:
    """
    评估 show_when 条件表达式。
    支持：field, field == val, field != val, field > n, field < n,
          field.length > n, field.length == 0, field.length > 0,
          &&, ||, !, 括号分组
    """
    if not condition:
        return True
    condition = condition.strip()

    # 解析字段路径（如 data_update.ok）
    def get_val(expr: str, d: dict) -> Any:
        expr = expr.strip()
        # 处理 .length
        if '.length' in expr:
            field = expr.replace('.length', '')
            val = _get_nested(d, field)
            return 0 if val is None else len(val)
        # 处理 == false / == true
        if '==' in expr:
            left, right = expr.split('==', 1)
            lv = _get_nested(d, left.strip())
            rv = right.strip()
            if rv == 'true': return lv is True
            if rv == 'false': return lv is False
            try: return float(rv) == float(lv) if lv is not None else False
            except: return str(lv) == rv
        if '!=' in expr:
            left, right = expr.split('!=', 1)
            lv = _get_nested(d, left.strip())
            rv = right.strip()
            try: return float(lv) != float(rv) if lv is not None else True
            except: return str(lv) != rv
        if '>' in expr:
            parts = expr.split('>')
            left, right = parts[0].strip(), parts[1].strip()
            lv = _get_nested(d, left)
            rv = float(right) if right.replace('.', '').isdigit() else right.strip('"\'')
            return (lv or 0) > rv
        if '<' in expr:
            parts = expr.split('<')
            left, right = parts[0].strip(), parts[1].strip()
            lv = _get_nested(d, left)
            rv = float(right) if right.replace('.', '').isdigit() else right.strip('"\'')
            return (lv or 0) < rv
        # 简单字段
        val = _get_nested(d, expr)
        if isinstance(val, bool):
            return val
        if isinstance(val, (list, dict, str)):
            return bool(val)
        return val is not None

    # 预处理：拆分为 token
    tokens = re.split(r'(\s*(&&|\|\|)\s*)', condition)
    # 简单情况：无逻辑运算符
    if len(tokens) == 1:
        return get_val(condition, data)

    # 复杂情况：递归求值
    i = 0
    result = get_val(tokens[0].strip(), data)
    i = 1
    while i < len(tokens):
        op = tokens[i].strip()
        if i + 1 < len(tokens):
            rhs = get_val(tokens[i + 1].strip(), data)
            if op == '&&':
                result = result and rhs
            elif op == '||':
                result = result or rhs
        i += 2
    return result

def _get_nested(data: dict, path: str) -> Any:
    """
    支持嵌套字段访问，如 data_update.ok
    支持 .length 属性，如 positions.length
    """
    # 处理 .length 后缀
    is_length = False
    if '.length' in path:
        path = path.replace('.length', '')
        is_length = True

    keys = path.split('.')
    val = data
    for k in keys:
        if val is None:
            return None
        if isinstance(val, dict):
            val = val.get(k)
        else:
            return None

    if is_length:
        return 0 if val is None else len(val)
    return val

# ── 持仓文件加载 ────────────────────────────────────────────
def _load_live_positions() -> dict:
    """
    从 positions_live.json 加载持仓信息，返回 {ticker: pos_dict} 字典。
    路径：../scripts/positions_live.json（相对于本文件位置）
    """
    pos_file = Path(__file__).parent / 'scripts' / 'positions_live.json'
    if not pos_file.exists():
        return {}
    try:
        with open(pos_file, encoding='utf-8') as f:
            content = json.load(f)
        positions = content if isinstance(content, list) else content.get('positions', [])
        return {p['ticker']: p for p in positions if isinstance(p, dict) and 'ticker' in p}
    except Exception:
        return {}


# ── 数据预处理 ──────────────────────────────────────────────
def preprocess_alert_data(raw: dict) -> dict:
    """
    将 alerts_scanner 原始输出预处理为 Builder 所需的标准化字段。
    主要处理：
      - 解析 full_output 中的 NOW/WATCH 信号
      - 标准化 positions 数组（从 positions_live.json 补全成本字段）
      - 提取 data_update.failed_detail
      - 补全所有必填字段（无内容则空字符串）
    """
    data = dict(raw)

    # ── data_update：展平为顶层字段 ─────────────────────────
    du = data.get('data_update') or {}
    failed_tickers = du.get('failed_tickers', [])
    data['data_update'] = dict(du)
    data['data_update_success']   = du.get('success', 0)
    data['data_update_failed']    = du.get('failed', 0)
    data['data_update_skipped']   = du.get('skipped', 0)
    data['data_update_elapsed_s'] = du.get('elapsed_s', 0)
    # report 字段含原始输出（与前面重复），不用
    data['data_update_report']    = ''
    data['data_update_failed_detail'] = (
        f"失败: {', '.join(failed_tickers)}" if failed_tickers else "无"
    )

    # ── 解析 NOW / WATCH 信号（从 full_output） ──────────────
    now_signals = []
    watch_signals = []
    full = data.get('full_output', '') or ''
    if full:
        in_now = False
        for line in full.split('\n'):
            if '立即买入机会' in line or 'STAGE_4 NOW' in line:
                in_now = True; continue
            if '即将买入机会' in line or 'STAGE_3 WATCH' in line or '═' in line:
                in_now = False
            if in_now and line.strip() and not line.startswith('═'):
                parsed = _parse_signal_line(line)
                if parsed:
                    now_signals.append(parsed)
        in_watch = False
        for line in full.split('\n'):
            if '即将买入机会' in line or 'STAGE_3 WATCH' in line:
                in_watch = True; continue
            if '═' in line and in_watch:
                in_watch = False
            if in_watch and line.strip() and not line.startswith('═'):
                parsed = _parse_signal_line(line)
                if parsed:
                    watch_signals.append(parsed)

    data['now_signals']   = now_signals
    data['watch_signals'] = watch_signals

    # ── 标准化 positions ─────────────────────────────────────
    # 优先从 positions_live.json 读取（包含成本），其次用 raw 中的 positions
    raw_positions = data.get('positions') or []
    normalized = {}
    for p in raw_positions:
        if isinstance(p, dict):
            t = p.get('ticker', p.get('symbol', '?'))
            normalized[t] = {
                'ticker':        t,
                'qty':           p.get('qty', p.get('quantity', 0)),
                'cost_basis':   _float(p.get('cost_basis') or p.get('cost', 0)),
                'current_price': _float(p.get('current_price') or p.get('price', 0)),
                'stop_loss':     _float(p.get('stop_loss') or p.get('stop', 0)),
                'target':        _float(p.get('target') or p.get('tgt', 0)),
                'status':        p.get('status', p.get('note', '')),
            }
        elif isinstance(p, str):
            parsed = _parse_position_line(p)
            if parsed:
                t = parsed.get('ticker')
                normalized[t] = parsed

    # 从 positions_live.json 补全缺失字段（成本等）
    live_positions = _load_live_positions()
    for t, lp in live_positions.items():
        if t in normalized:
            # 补全缺失字段
            for k in ('qty', 'cost_basis', 'stop_loss', 'target', 'status'):
                if not normalized[t].get(k):
                    normalized[t][k] = lp.get(k, normalized[t].get(k, 0 if k in ('qty', 'cost_basis', 'stop_loss', 'target') else ''))
        else:
            normalized[t] = lp

    data['positions'] = list(normalized.values())

    # ── 补全所有必填字段（空字符串 / 空列表） ─────────────────
    for field in ('title', 'time', 'spy_timestamp', 'market_date',
                  'market_regime', 'summary'):
        data.setdefault(field, '')

    for lst in ('now_signals', 'watch_signals'):
        data.setdefault(lst, [])

    # ── 模板用 .length / .count 的预计算字段 ─────────────────
    data['positions_count']   = len(data.get('positions', []))
    data['now_signals_count']  = len(data.get('now_signals', []))
    data['watch_signals_count'] = len(data.get('watch_signals', []))

    return data

def _float(v) -> float:
    try: return float(v)
    except: return 0.0

def _parse_signal_line(line: str) -> dict:
    """
    解析形如：
      🟢 AAPL  315.50  买/入场  目标 325  止损 310  [Stage 4]
    或
      🟢 AAPL   315.50  →  322(+2.1%)  <310(-1.7%)
    返回 {'ticker': 'AAPL', 'entry': 315.50, 'target': 322, 'stop': 310}
    """
    line = line.strip()
    if not line:
        return None
    # 去除 emoji 前缀
    clean = re.sub(r'[🔴🟡🟢➖🟠⚪]', '', line).strip()

    # 提取股票代码（大写字母 2-5 位）
    m = re.match(r'^([A-Z]{2,5})', clean)
    if not m:
        return None
    ticker = m.group(1)

    # 提取所有数字（价格/百分比）
    nums = re.findall(r'[-+]?\d+\.?\d*', clean)
    nums = [float(n) for n in nums if '.' in n or len(n) >= 3]

    result = {'ticker': ticker, 'raw': clean}

    # 尝试找目标价和止损价
    # 常见模式: 目标 325 / 止损 310 / → 322(+2.1%)
    target_m = re.search(r'目标\s*(\d+\.?\d*)', clean)
    stop_m   = re.search(r'止损\s*(\d+\.?\d*)', clean)
    if target_m:
        result['target'] = float(target_m.group(1))
    if stop_m:
        result['stop'] = float(stop_m.group(1))

    # 尝试从 → 或 () 提取
    arrow_m = re.search(r'→\s*(\d+\.?\d*)\(', clean)
    if arrow_m and 'target' not in result:
        result['target'] = float(arrow_m.group(1))

    return result

def _parse_position_line(line: str) -> dict:
    """
    解析持仓行，形如：
      🟡AAPL     315.19   310.50   310.50   保本止损
    返回 {'ticker': 'AAPL', 'current_price': 315.19, 'stop_loss': 310.50, 'target': 310.50, 'status': '保本止损'}
    """
    line = line.strip()
    if not line:
        return None
    # 去除 emoji
    clean = re.sub(r'[🔴🟡🟢➖🟠⚪]', '', line).strip()

    # 提取 ticker
    m = re.match(r'^([A-Z]{2,5})', clean)
    if not m:
        return None
    ticker = m.group(1)

    # 提取数字
    nums = re.findall(r'\d+\.?\d*', clean)
    nums = [float(n) for n in nums if float(n) > 0]

    result = {
        'ticker': ticker,
        'current_price': nums[0] if len(nums) >= 1 else 0,
        'stop_loss':     nums[1] if len(nums) >= 2 else 0,
        'target':        nums[2] if len(nums) >= 3 else 0,
        'status':        '',
    }

    # 提取文字状态（数字之后的剩余部分）
    if len(nums) >= 3:
        idx3 = clean.find(str(nums[2]))
        rest = clean[idx3 + len(str(nums[2])):].strip()
        # 去除分隔符
        rest = re.sub(r'^[|\s\-:]+', '', rest).strip()
        result['status'] = rest

    return result

# ── Section Renderer ─────────────────────────────────────────
def _render_header(section: dict, data: dict) -> str:
    return section['template'].format(**data)

def _render_text(section: dict, data: dict) -> str:
    try:
        return section['template'].format(**data)
    except KeyError:
        return section['template']

def _render_divider(section: dict, data: dict) -> str:
    return "─" * 40

def _render_kv_block(section: dict, data: dict) -> str:
    try:
        return section['template'].format(**data)
    except KeyError as e:
        return f"[字段缺失: {e}]"

def _render_section_header(section: dict, data: dict) -> str:
    try:
        return section['template'].format(**data)
    except KeyError as e:
        return section['template'].replace('{' + str(e) + '}', '')

def _render_position_table(section: dict, data: dict) -> str:
    positions = data.get('positions', [])

    # 分隔线
    sep = "─" * 72
    # 表头
    header = (f"{'股票':<7} {'持仓':>4} {'成本':>8} {'现价':>8} {'止损':>8} {'目标':>8} {'涨跌幅':>8}  {'状态'}")
    lines = [sep, header, sep]

    if not positions:
        lines.append("（无持仓）".center(60))
        lines.append(sep)
        return '\n'.join(lines)

    for p in positions:
        ticker = str(p.get('ticker', ''))[:7]
        qty    = p.get('qty', p.get('quantity', 0))
        cost   = p.get('cost_basis', 0)
        cur_p  = p.get('current_price', 0)
        stop_p = p.get('stop_loss', 0)
        tgt_p  = p.get('target', 0)
        status = str(p.get('status', ''))[:12]

        # 涨跌幅
        if cost and cur_p:
            gain = (cur_p - cost) / cost * 100
            gain_str = f"{gain:+.2f}%"
        else:
            gain_str = "—"

        lines.append(
            f"{ticker:<7} {qty:>4} {cost:>8.2f} {cur_p:>8.2f} "
            f"{stop_p:>8.2f} {tgt_p:>8.2f} {gain_str:>9}  {status}"
        )

    lines.append(sep)
    return '\n'.join(lines)

def _render_signal_list(section: dict, data: dict) -> str:
    items_ref = section.get('items_ref', '')
    items = data.get(items_ref, [])
    if not items:
        return "  （无）"
    lines = []
    for item in items:
        raw = item.get('raw', '')
        if raw:
            lines.append(f"  {raw}")
        else:
            ticker = item.get('ticker', '?')
            target = item.get('target', item.get('tgt', '?'))
            stop   = item.get('stop', item.get('stop_loss', '?'))
            lines.append(f"  {ticker}  目标:{target}  止损:{stop}")
    return '\n'.join(lines)

def _render_footer(section: dict, data: dict) -> str:
    try:
        return section['template'].format(**data)
    except KeyError:
        return section['template']

_renderer_map = {
    'header':          _render_header,
    'text':            _render_text,
    'divider':         _render_divider,
    'kv_block':        _render_kv_block,
    'section_header':  _render_section_header,
    'position_table':  _render_position_table,
    'signal_list':     _render_signal_list,
    'footer':          _render_footer,
}

def _render_section(section: dict, data: dict) -> str:
    """渲染单个 section，所有 section 必填，无内容时显示占位符"""
    stype = section.get('type')
    renderer = _renderer_map.get(stype)
    if not renderer:
        return f"[未知 section type: {stype}]"
    return renderer(section, data)

# ── 主入口 ───────────────────────────────────────────────────
def build_message(alert_data: dict, message_type: str = 'intraday_alert',
                 schema_path: str = None,
                 default_title: str = '盘中推送') -> str:
    """
    根据 Schema 生成飞书消息文本。

    参数：
        alert_data  — alerts_scanner 输出（或 latest_alert.json 内容）
        message_type — Schema 中的消息类型，如 'intraday_alert'
        schema_path  — 可选，指定 Schema 文件路径

    返回：
        格式化的纯文本消息，可直接用于飞书推送
    """
    # 1. 加载 Schema
    sp = Path(schema_path) if schema_path else None
    schema = load_schema(sp)
    mt_schema = get_message_type_schema(schema, message_type)

    # 2. 预处理数据
    data = preprocess_alert_data(alert_data)

    # 3. 填充默认值
    data.setdefault('title', default_title)

    # 3. 渲染每个 section
    parts = []
    for section in mt_schema.get('sections', []):
        rendered = _render_section(section, data)
        if rendered is not None:
            parts.append(rendered)

    # 4. 合并，清理多余空行
    text = '\n'.join(parts)
    # 去除连续超过2个的空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def build_and_send(alert_data: dict, message_type: str = 'intraday_alert',
                   silent: bool = False) -> tuple[bool, str]:
    """
    生成消息并推送到飞书（调用 openclaw message send）。
    返回 (success: bool, message_text: str)
    """
    text = build_message(alert_data, message_type)
    success = _send_to_feishu(text, silent=silent)
    return success, text

def _send_to_feishu(text: str, silent: bool = False) -> bool:
    """通过 openclaw message send 发送文本到飞书"""
    from pathlib import Path
    OPENCLAW = Path(__file__).parent.parent / '..' / '..' / '..' / '..' / '.npm-global' / 'bin' / 'openclaw'
    if not OPENCLAW.exists():
        OPENCLAW = '/home/yudengfeng/.npm-global/bin/openclaw'
    FEISHU_ID = 'oc_c76cd3b3bc91d7f50594ab5a242d73a6'
    cmd = [str(OPENCLAW), 'message', 'send',
           '--channel', 'feishu',
           '--target', FEISHU_ID,
           '--message', text]
    if silent:
        cmd.append('--silent')
    import subprocess
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False

# ── CLI 测试 ─────────────────────────────────────────────────
if __name__ == '__main__':
    import argparse, sys
    parser = argparse.ArgumentParser(description='Message Builder CLI')
    parser.add_argument('--alert', default=None, help='latest_alert.json 路径')
    parser.add_argument('--type', default='intraday_alert', help='消息类型')
    parser.add_argument('--send', action='store_true', help='发送测试')
    parser.add_argument('--silent', action='store_true', help='静默发送')
    args = parser.parse_args()

    if args.alert:
        with open(args.alert) as f:
            alert_data = json.load(f)
    else:
        # 尝试默认路径
        default = Path(__file__).parent / 'scripts' / 'latest_alert.json'
        if default.exists():
            with open(default) as f:
                alert_data = json.load(f)
        else:
            print("❌ 未指定 --alert，且默认文件不存在", file=sys.stderr)
            sys.exit(1)

    text = build_message(alert_data, message_type=args.type)
    print(text)
    print(f"\n[长度: {len(text)} 字符]")

    if args.send:
        ok = _send_to_feishu(text, silent=args.silent)
        print(f"\n{'✅ 发送成功' if ok else '❌ 发送失败'}")
