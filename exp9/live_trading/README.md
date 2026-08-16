# 实盘实战系统

> 2026-06-03 正式启用

## 目录结构

```
exp9/live_trading/
├── engine/                          # 策略引擎（核心逻辑）
│   ├── engine_interface.py          # ⭐ 对外 API（evaluate_entry / evaluate_exit）
│   ├── engine_h3_4_1.py             # 原始引擎（含完整出场规则）
│   └── engine__h3_4_1-v1.py         # V1 wrapper（trail=3.0，main() 入口）
│
├── backtest/                        # 回测能力
│   └── results/                     # 回测输出（Excel + JSON）
│
├── combat/                          # 实盘脚本
│   ├── positions_live.json          # 实时持仓文件
│   ├── latest_alert.json            # 最近一次扫描结果
│   ├── README.md                    # 本文件
│   └── scripts/
│       ├── alerts_scanner.py        # 市场扫描入口（577只）
│       └── intraday_monitor.py      # 盘中监控 + 飞书推送
│
└── logs/                            # 日志（预留）
```

---

## 脚本入口

### 1. `combat/scripts/alerts_scanner.py`

全市场扫描，输出交易信号和持仓状态。

```bash
cd exp9/live_trading/combat

# 基础扫描（只显示 NOW 信号）
python3 scripts/alerts_scanner.py

# 显示所有信号（包括 WATCH）
python3 scripts/alerts_scanner.py --show-all

# 指定 RR 阈值
python3 scripts/alerts_scanner.py --min-rr-buy 1.5 --min-rr-watch 0.8

# 读取实时持仓文件
python3 scripts/alerts_scanner.py --positions positions_live.json

# 输出 JSON 格式（供程序调用）
python3 scripts/alerts_scanner.py --positions positions_live.json --json
```

**输出内容：**
- 🟢 立即买入机会（STAGE_4 NOW）
- 🟡 即将买入机会（STAGE_3 WATCH）
- 📋 持仓监控（出场信号判断）

**依赖：** `engine/engine_interface.py`

---

### 2. `combat/scripts/intraday_monitor.py`

盘中监控 + 自动飞书推送。cron 调度后全自动运行。

```bash
cd exp9/live_trading/combat

# 检查数据完整性
python3 scripts/intraday_monitor.py --check

# 手动触发一次盘中扫描（打印结果，不推送）
python3 scripts/intraday_monitor.py

# 全自动：更新数据 → 扫描 → 飞书推送
python3 scripts/intraday_monitor.py --auto-update

# 为今天调度 cron jobs（交易日开盘前运行一次即可）
python3 scripts/intraday_monitor.py --schedule

# 清除今日所有 cron jobs
python3 scripts/intraday_monitor.py --clear-schedule

# 演练模式（不实际创建）
python3 scripts/intraday_monitor.py --schedule --dry-run
```

**Cron 调度时刻（自动）：**
| 时刻 ET | 内容 |
|---------|------|
| 09:32 | 首根K线后首次推送 |
| 10:32 ~ 16:32 | 每小时一次盘中推送 |
| 17:00 | 收盘总结 |

**推送内容：**
- SPY 数据时间戳
- 数据更新结果（成功/失败）
- 信号汇总（NOW / WATCH 数量）
- 持仓状态（现价、止损、目标、状态）

---

## 引擎接口（`engine/`

### `engine_interface.py` — 唯二的两个纯计算函数

```python
from engine.engine_interface import evaluate_entry, evaluate_exit

# 入场信号判断
sig = evaluate_entry(ticker, daily_bars, spy_bars, h1_bars)
# 返回: {action, stage, grade, rr, entry, stop, target, l1_regime, pullback_tier}

# 出场信号判断
exit = evaluate_exit(position, h1_bars, entry_h1_idx, current_h1_idx,
                    atr_mult=1.5, atr_trailing_mult=4.0, min_hold=5)
# 返回: {action, exit_price, message, trail_stop}
```

**设计原则：**
- 纯计算，无副作用（不写文件、不操作现金）
- 内部委托 `BuyFilterEngine`（入场）和 `engine_h3_4_1._track_1h`（出场）
- 引擎升级时 `alerts_scanner.py` 零改动

---

## 持仓管理

**持仓文件：** `combat/positions_live.json`

格式：
```json
{
  "positions": [
    {
      "ticker": "AAPL",
      "shares": 10,
      "entry_price": 300.00,
      "entry_date": "2026-06-01",
      "stop_loss": 295.00,
      "target": 310.00,
      "atr": 2.50,
      "atr_mult": 1.5,
      "atr_trailing_mult": 4.0,
      "min_hold": 5,
      "l1_regime": "BULL",
      "status": "open"
    }
  ],
  "cash": 7000.00,
  "last_updated": "2026-06-03 09:35 ET"
}
```

---

## 数据

- **K线来源：** Chrome CDP → Yahoo Finance
- **本地目录：** `TradingAgents/中间过程/klines/`
- **股票池：** `TradingAgents/fintech/stock_pool.json`（579只）
- **数据检查：** `python3 scripts/check_data_freshness.py`

---

## 飞书推送

- **会话 ID：** `oc_c76cd3b3bc91d7f50594ab5a242d73a6`
- **推送方式：** `openclaw message send --channel feishu --target <session_id>`
- **推送触发：** `intraday_monitor.py` 的 `run_intraday_update(push=True)` 自动调用

---

## 策略参数（V2，trail=4.0）

| 参数 | 值 | 说明 |
|------|-----|------|
| ATR 倍数（止损）| 1.5 | 入场止损 |
| ATR trailing | 4.0 | 持仓中追踪止损 |
| 最小持仓 | 5h | Lot 2 止盈生效前最低持仓 |
| 目标倍数 | 3.0×ATR | Lot 1 目标价 |
| 最大持仓 | 8只 | 同时持仓上限 |
| 回测结果 | +74.1% | 2025-2026 |

---

## 快速启动（新交易日）

```bash
cd ~/workspace/美股投资洞察分析/exp9/live_trading/combat

# 1. 检查数据
python3 scripts/intraday_monitor.py --check

# 2. 调度今日盘中推送（开盘前运行一次）
python3 scripts/intraday_monitor.py --schedule

# 3. 手动跑一次扫描
python3 scripts/alerts_scanner.py --positions positions_live.json --show-all
```
