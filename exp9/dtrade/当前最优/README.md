# 📊 当前最优策略

## 小时级 (h3-4-1)

| 文件 | rf | trail | 收益 | 用法 |
|------|-----|-------|------|------|
| `engine_h3_4_1_rf35.py` | 0.35 | 4.0 | +370% | 日内多频次 |
| `engine_h3_4_1_rf30.py` | 0.30 | 4.0 | +283% | 中杠杆 |
| `engine_h3_4_1_rf25.py` | 0.25 | 4.0 | +241% | 低杠杆 |

> 位于 `../live_trading/engine/`

## 日线 (Daily)

| 文件 | rf | trail | 收益 | 用法 |
|------|-----|-------|------|------|
| `engine_daily_rf35.py` | 0.35 | 2.5 | +118% | 日线低频 |
| `engine_daily.py` | 可配 | 可配 | — | 完整 CLI |

### 日线用法
```
python3 engine_daily_rf35.py
python3 engine_daily_rf35.py --years 2025 2026 --capital 50000
python3 engine_daily.py --trail-mult 3.0 --risk-frac 0.30 --dd-limit 0.15
```

### 日线 vs 小时级对比
| | 小时级 | 日线 |
|------|-------|------|
| 最优 trail | 4.0 | 2.5 |
| 收益 | +370% | +118% |
| 胜率 | 38.6% | 26.4% |
| RR | 2.47 | 4.59 |
| 交易频率 | 每小时 | 每天 |
| 保护机制 | 无 | 熔断 + 趋势 |

### 旧版引擎
- `engine_v2145_no_wsban.py` — Branch A 变体（已弃用）
- `gen_report_v2145.py` — 报告生成器
