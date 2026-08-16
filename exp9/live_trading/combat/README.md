# 盘中实时监控推送系统

## 架构

```
intraday_monitor.py  ← 主入口（调度/数据更新/推送）
        ↓
alerts_scanner.py   ← 扫描（调用 engine_interface）
        ↓
engine_interface.py  ← 稳定 API（调用 BuyFilterEngine + h3-4-1 出场规则）
        ↓
engine_h3_4_1.py    ← 引擎实现（回测 + 实盘共用规则）
```

## 核心依赖关系

| 文件 | 作用 |
|------|------|
| `alerts_scanner.py` | 扫描全市场买信号 + 持仓盯盘（通过 engine_interface） |
| `engine_interface.py` | 稳定 API 接口，入场/出场规则不重写 |
| `engine_h3_4_1.py` | 引擎核心实现（回测和实盘共用同一套逻辑） |

**重要**：`alerts_scanner.py` **不重写**入场/出场逻辑，只调用 `engine_interface`。  
引擎升级（如加入 EMA50_20d 过滤器 / 93天退出）时，**无需修改 `alerts_scanner.py`**，因为接口不变。

## 每日使用流程

### 1. 交易日开盘前（推荐 9:00-9:25 ET）

在 OpenClaw 主会话运行：

```bash
cd 美股投资洞察分析/exp9/live_trading/combat
python3 scripts/intraday_monitor.py --schedule
```

### 2. 手动触发一次扫描

```bash
python3 scripts/intraday_monitor.py
```

### 3. 检查数据完整性

```bash
python3 scripts/intraday_monitor.py --check
```

### 4. 清除今日 cron jobs

```bash
python3 scripts/intraday_monitor.py --clear-schedule
```

---

## 推送逻辑

| 时间（ET） | 触发 | 说明 |
|-----------|------|------|
| 09:32 | 首根K线 | 数据已更新到最新 |
| 10:32-16:32 | 每小时 | 盘中监控 |
| 17:00 | 收盘 | 本日总结 |

---

## 推送内容

每次推送包含：
- 🟢 立即买入机会（STAGE_4 NOW）
- 🟡 即将买入机会（STAGE_3 WATCH）
- 📋 持仓变动（止损触发 / Lot1触达 / ATR止盈）

---

## 引擎参数（V2 默认值）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `atr_mult` | 1.5 | 初始止损 ATR 倍数 |
| `atr_trailing_mult` | 4.0 | ATR 跟踪止盈倍数 |
| `min_hold` | 5h | 最小持仓小时后检查出场 |
| `target_mult` | 3.0 | 日线目标 ATR 倍数 |

---

## 出场规则（来自 engine_h3_4_1.py）

1. **止损**：价格 ≤ 止损价 → STOP_LOSS
2. **Lot1 目标**：价格 ≥ 目标价 + 持仓≥2h → 保本止损（止损上移至入场价）
3. **Lot2 ATR trailing**：lot1_done + 持仓≥5h + close < 峰值 - 4×ATR_1h → 止盈
4. **Lot2 跌回入场**：lot1_done + 持仓≥5h + 价格跌回入场价 → 保本出场

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `scripts/alerts_scanner.py` | 全市场扫描 + 持仓盯盘 |
| `scripts/intraday_monitor.py` | 盘中监控主入口 |
| `positions_live.json` | 实际持仓（手动维护） |
| `latest_alert.json` | 最近一次扫描结果（自动生成） |
| `engine_interface.py` | 稳定 API（位于 `live_trading/engine/`） |

---

## 时区说明

- 所有时间以**美东时间（ET）** 为准
- 自动处理夏令时（DST）：EDT（UTC-4）vs EST（UTC-5）
