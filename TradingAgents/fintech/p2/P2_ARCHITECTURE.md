# P2 层架构文档
> 架构版本：2026-05-16（3策略并行）
> 维护状态：✅ 生产可用

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     P2 调度层 (regime_dispatcher.py)             │
│  analyze(trade_date, weights, verbose)                            │
│  ①统一加载数据 ②并行运行A+B+C ③合并结论 ④输出供P3               │
└──────────────────────────┬──────────────────────────────────────┘
                            │ v = load_all_variables()
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│               统一数据层 (shared/variables.py)                    │
│          一次读取磁盘，44个指标，所有策略共用                      │
│  价格结构/动量/波动率/广度/宏观/期权/风险 共用同一份数据          │
└───────────────────────────┬──────────────────────────────────────┘
                            │
       ┌────────────────────┼────────────────────┐
       ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────┐
│ 策略A: MOMENTUM │  │ 策略B: MACRO    │  │ 策略C: ML_PROBABILITY  │
│ momentum_engine │  │ macro_engine    │  │ ml_probability_engine    │
│ ─────────────── │  │ ──────────────  │  │ ─────────────────────   │
│ 趋势是你的朋友  │  │ 宏观周期驱动    │  │ ML预测变盘概率           │
│ EMA多头排列     │  │ + RSI/VIX逆向   │  │ 3模型Ensemble输出        │
│ NYAD趋势确认    │  │                 │  │ GBR + NN + LR            │
│ VIX低位+结构    │  │ FCI/HY利差/流动性│  │                          │
└────────┬────────┘  └────────┬────────┘  └────────────┬──────────┘
         │                    │                         │
         └────────────────────┼─────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     综合输出 (combined)                            │
│  ──────────────────────────────────────────────────────────    │
│  Regime:    RISK_OFF  (A+B一致 → RISK_OFF，C被压制)           │
│  仓位:      1.0%      (min(A,B)×0.4，因为C分歧被压制)         │
│  置信度:    44%       (分歧导致置信度降低)                     │
│  分歧:      ⚠️ C(M-low)与A+B(R-off)冲突，C被压制             │
│  ──────────────────────────────────────────────────────────    │
│  ✅ 三策略结论 → P3基本面分析使用                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、三策略分工

| | **策略A MOMENTUM** | **策略B MACRO** | **策略C ML_PROBABILITY** |
|---|---|---|---|
| **核心理念** | 趋势是你的朋友 | 宏观周期+逆向信号 | ML定量概率预测 |
| **数据来源** | SPY价格结构+NYAD+VIX | FCI/HY利差/流动性/VIX | GBR+NN+LR Ensemble |
| **Regime** | BULL_TREND / NEUTRAL / RISK_OFF | RECOVERY / CURDLE / STRESS 等 | LOW_RISK / CAUTION / HIGH_RISK |
| **权重** | 40% | 35% | 25% |
| **更新频率** | 日更 | 日更 | 模型训练后更新 |
| **数据时效** | 实时 | 实时 | ⚠️ 需定期重训练 |

### 策略C - ML模型说明

| 模型 | 类型 | 标签定义 | 概率文件 |
|------|------|---------|---------|
| GBR | GradientBoosting | 未来20日回撤>8% | `spy_shift_prob_timeseries.csv` |
| NN | 神经网络(128→64→32) | 未来10日回撤>3% | `spy_nn_enhanced_prob.csv` |
| LR | Logistic Regression | 极值点附近分类 | `lr_daily_prob.csv` |

Ensemble概率 = 三模型均值（各模型等权重）

---

## 三、分歧处理逻辑

```
C说 LOW_RISK（prob<30%），
但 A+B 都说 RISK_OFF/CURDLE/STRESS
→ C 被压制（suppressed=True）
→ final_exposure = min(A仓位, B仓位) × 0.4
→ A+B=2.5%/6.0% → min=2.5% → 2.5%×0.4 = 1.0% ✅

原因：ML模型数据过期约2个月，历史规律可能
     不适用当前宏观环境（HY利差新高+CTA极度做空）
```

---

## 四、文件清单

```
p2/
├── __init__.py                     # 统一包入口
├── regime_dispatcher.py             # 🎯 主入口：analyze(trade_date)
│                                   #    返回 strategy_A/B/C + combined + diagnostic
├── P2_ARCHITECTURE.md              # 本文档
├── shared/
│   ├── __init__.py
│   ├── utils.py                    # EMA/RSI/ATR/Bollinger/linear_slope
│   └── variables.py                # load_all_variables()：44指标统一获取
└── strategies/
    ├── __init__.py
    ├── momentum_engine.py          # 策略A：动量趋势
    ├── macro_engine.py             # 策略B：宏观择时 + 均值回归
    └── ml_probability_engine.py    # 策略C：ML概率引擎 ⭐新增
```

---

## 五、调用示例

```python
from p2 import analyze_dispatcher

# 完整分析（三策略）
result = analyze_dispatcher("2026-05-15", verbose=True)

result["strategy_A"]   # MOMENTUM 结果
result["strategy_B"]   # MACRO 结果
result["strategy_C"]   # ML_PROBABILITY 结果
result["combined"]      # 综合结论（供P3使用）
result["diagnostic"]    # 分歧诊断
result["variables"]     # 44个原始指标

# 关键字段
combined = result["combined"]
combined["regime"]       # "RISK_OFF"
combined["exposure"]    # 1.0（%）
combined["C_suppressed"]# True（C被压制）
```

---

## 六、向后兼容

```python
# 旧接口仍然可用（返回策略A的结果，但嵌入完整三策略信息）
from regime_engine_v2 import analyze_regime_engine
result = analyze_regime_engine("2026-05-15")
result["strategy_A"]   # 动量引擎
result["strategy_B"]   # 宏观引擎
result["strategy_C"]   # ML概率引擎（新增）
result["combined"]      # 综合结论
```

---

## 七、当前结果（2026-05-15）

| 策略 | Regime | 仓位(原始) | 置信度 | 状态 |
|------|--------|------------|--------|------|
| A MOMENTUM | RISK_OFF | 2.5% | 61% | ✅ |
| B MACRO | CURDLE | 6.0% | 43% | ✅ |
| C ML_PROB | LOW_RISK | 68.0% | 65% | ⚠️ **被压制** |
| **综合** | **RISK_OFF** | **1.0%** | 44% | ✅ |

> **分歧原因**：A+B一致确认RISK_OFF（CURDLE+CTA极度做空），但C的ML模型给出LOW_RISK（prob=28.7%）。由于ML数据过期约2个月，历史规律不适用当前宏观环境，**C被压制**。
>
> **建议**：模型需重新训练（再训练触发条件：staleness > 7天）

---

## 八、策略C数据新鲜度监控

```python
from strategies.ml_probability_engine import is_prob_data_fresh, get_data_staleness_days

is_fresh = is_prob_data_fresh("2026-05-15")   # staleness≤7天 → True
days_old = get_data_staleness_days("2026-05-15") # 2（天）
```

当 `days_old > 7` 时，dispatcher自动输出再训练建议。
