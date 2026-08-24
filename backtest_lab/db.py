#!/usr/bin/env python3
"""
回测实验登记系统 — 数据库层
=============================
单文件 SQLite，两表：
  experiments  每次回测一条记录
  pitfalls     坑/教训记录

设计原则：最小复杂度，不做框架。所有脚本 import 本模块共用连接和适配器。
"""
import sqlite3, re, json
from pathlib import Path

LAB_DIR = Path(__file__).resolve().parent
DB_PATH = LAB_DIR / 'backtest.db'


SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    engine       TEXT NOT NULL,          -- 引擎名: h3_4_1 / daily / spytrend_v6 ...
    engine_file  TEXT,                    -- 引擎脚本路径
    params       TEXT NOT NULL DEFAULT '{}',  -- JSON 参数
    symbols      TEXT,                    -- 股票范围
    date_start   TEXT,                    -- 回测区间起
    date_end     TEXT,                    -- 回测区间止
    capital      REAL,                    -- 初始资金
    final_cash   REAL,                    -- 期末现金
    return_pct   REAL,                    -- 收益率 %（关键排序字段）
    win_rate     REAL,                    -- 胜率 %
    avg_win      REAL,
    avg_loss     REAL,
    rr           REAL,                    -- 盈亏比 |avg_win/avg_loss|
    max_drawdown REAL,                    -- 最大回撤 %
    trade_count  INTEGER,
    lot1_hit     INTEGER,
    total_profit REAL,                    -- 累计美元盈亏（旧结果反推）
    status       TEXT DEFAULT 'ok',       -- ok / failed / superseded
    tags         TEXT DEFAULT '[]',       -- JSON 数组
    note         TEXT,                    -- 一句话结论
    result_file  TEXT,                    -- 原始结果 JSON 路径（溯源）
    created_at   TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS pitfalls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    engine      TEXT,                     -- 关联引擎（可空）
    category    TEXT,                     -- 参数/数据/逻辑/过拟合/环境
    title       TEXT NOT NULL,            -- 一句话标题
    description TEXT,                     -- 现象 + 根因
    lesson      TEXT,                     -- 结论/教训
    severity    TEXT DEFAULT '中',        -- 高/中/低
    related_exp INTEGER,                  -- 关联实验 id
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_exp_engine ON experiments(engine);
CREATE INDEX IF NOT EXISTS idx_exp_return ON experiments(return_pct);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────
# 适配器：结果 JSON → 标准指标
# ─────────────────────────────────────────────────────────────
def extract_metrics(data: dict, capital: float = None) -> dict:
    """从结果 JSON 抽取标准指标，兼容现有 h3_4_1/daily 格式。

    返回 dict，键与 experiments 表列对应（除 engine/params/result_file）。
    """
    m = {}
    m['win_rate']   = data.get('win_rate')
    m['avg_win']    = data.get('avg_win')
    m['avg_loss']   = data.get('avg_loss')
    m['rr']         = data.get('win_loss_ratio')          # 旧格式用 win_loss_ratio
    m['trade_count'] = data.get('total')
    m['lot1_hit']   = data.get('lot1_hit')

    # 收益率：final_cash/capital（daily 用 initial_capital），其次用传入 capital
    fc = data.get('final_cash')
    cap = data.get('capital') or data.get('initial_capital') or capital
    if fc is not None and cap:
        m['final_cash'] = fc
        m['capital'] = cap
        m['return_pct'] = round((fc - cap) / cap * 100, 2)

    # 最大回撤：h3_4_1 用 max_drawdown，daily 用 max_drawdown_pct（0.0 是合法值，不能用 or）
    m['max_drawdown'] = data.get('max_drawdown')
    if m['max_drawdown'] is None:
        m['max_drawdown'] = data.get('max_drawdown_pct')

    # 累计美元盈亏：只信 top-level total_pnl_dollar（trades 里的 total_pnl/realized_profit
    # 因 lot1/lot2 拆分逻辑求和不可靠，旧结果无此字段则留空）
    tpd = data.get('total_pnl_dollar')
    if tpd is not None:
        m['total_profit'] = round(tpd, 2)
    return m


# ─────────────────────────────────────────────────────────────
# 适配器：文件名 → (engine, params)
# ─────────────────────────────────────────────────────────────
_PARAM_RULES = [
    ('rf',      r'rf(\d+\.?\d*)'),
    ('trail',   r'trail(\d+\.?\d*)'),
    ('atr',     r'atr(\d+\.?\d*)'),
    ('tgt',     r'tgt(\d+\.?\d*)'),
    ('hold',    r'hold(\d+)'),
    ('pos',     r'pos(\d+)'),
    ('k',       r'[_-]k(\d+\.?\d*)'),
    ('v',       r'[_-]v(\d+)'),
]


def parse_filename(name: str):
    """从结果文件名（去掉 results_ 前缀和 .json 后缀）解析引擎名和参数。

    例: 'h3_4_1_rf0.25_t4.0' -> ('h3_4_1', {'rf':0.25, 'trail':4.0})
        'daily_sweep_rf0.30_t2.5' -> ('daily', {'rf':0.30, 'trail':2.5})
    参数解析是尽力而为，取不到就留空；原始名另存 note 保真。
    """
    engine = 'unknown'
    if name.startswith('h3_4_1') or 'h3_4_1' in name:
        engine = 'h3_4_1'
    elif name.startswith('daily'):
        engine = 'daily'
    else:
        engine = name.split('_')[0]

    params = {}
    for key, pat in _PARAM_RULES:
        mm = re.search(pat, name)
        if mm:
            val = mm.group(1)
            params[key] = float(val) if '.' in val else int(val)

    # 裸 't' 视为 trail（如 _t4.0），排除 trail/tgt/atr 已匹配的情况
    if 'trail' not in params:
        for mm in re.finditer(r'(?<![a-z])t(\d+\.?\d*)', name):
            params['trail'] = float(mm.group(1))
            break
    return engine, params


def params_to_json(params: dict) -> str:
    return json.dumps(params, ensure_ascii=False, sort_keys=True)


if __name__ == '__main__':
    init_db()
    print(f'数据库已初始化: {DB_PATH}')
