# AI研究系统升级方案

> 从"问答型Agent"升级为"研究型Agent"，提升token密度和alpha质量
> 创建日期：2026-05-11 | 负责人：Jax

---

## 一、目标

**核心问题**：当前token利用率低，消耗在低价值任务（问答、简单计算）上
**解决方向**：把token花在"市场结构理解"和"研究自动化"上

---

## 二、现有基础（可直接用）

| 模块 | 状态 | 说明 |
|------|------|------|
| 数据层 | ✅ 完整 | 172只股票日K（2020-2026，1596交易日） |
| 回测引擎 | ✅ 完整 | G1/G2/G3/G5全量回测框架 |
| ML模型 | ✅ 已修复 | winrate_predictor + rr_estimator（NaN bug已修复） |
| CRO框架 | ✅ 完整 | 7层市场状态机 |
| Agent定义 | ✅ 静态 | CDO/CRO/科技/能源/金融/消费/医药研究员 |
| 历史回测 | ✅ 完整 | 2020-2026详细回测JSON + HTML报告 |
| 记忆系统 | ⚠️ 基础 | memory/每日记忆，非结构化 |

---

## 三、5层升级架构

### Layer 1：市场状态层 [✅ 完成]
**优先级：🔴 最高**

| 任务 | 状态 | 文件 |
|------|------|------|
| `memory/market_regime.md` 模板 | ✅ | `memory/market_regime.md` |
| `scripts/daily_market_regime.py` | ✅ | `scripts/daily_market_regime.py` |
| Cron每日17:00自动运行 | ✅ | cron id: 34dc1ad4 |
| 分析前强制读取机制 | ✅ | AGENTS.md 已内置 |

**首次运行结果（2026-05-11）：**
- Regime: 🚀 超强牛市（6.5/7分）
- SPY: $737.62, RSI=73.8, MACD +
- QQQ: $711.23, RSI=84.2 (极度超买)
- VIX: 18.15 ✅ | DXY: 97.92 ✅ | TNX: 4.36%
- 结论：市场强势但极度超买，ML策略可积极参与

**功能**：每天自动生成市场状态报告（trend/liquidity/volatility/risk appetite/rotation）

---

### Layer 2：信号发现层 [✅ 完成]
**优先级：🔴 高**

| 任务 | 状态 | 说明 |
|------|------|------|
| `scripts/daily_signal_screener.py` | ✅ | 每日扫描172只股票，输出L1-L4候选池 |
| `agents/research_reports/每日信号扫描_YYYY-MM-DD.html` | ✅ | HTML格式候选股报告 |
| Cron每日17:00 HK | ⬜ | 待设置 |
| ML P_up过滤 | ⬜ | G3模型路径问题待修复 |

**首次扫描结果（2026-05-11）：**
- L1 趋势确认：76只（ALAB/IONQ/CDNS/MP/ATEYY等）
- L2 SETUPS低吸：18只
- L3 ML信号：0只（ML模型路径问题）
- L4 观察：21只
- Regime：🚀超强牛市(5.0/8)，趋势跟随为主

---

### Layer 3：自动复盘层 [未启动]
**优先级：🟡 中**

| 任务 | 状态 | 文件 |
|------|------|------|
| `scripts/daily_review.py` | ⬜ | 每日自动复盘 |
| `memory/auto_review/{date}.md` | ⬜ | 复盘存档 |
| `memory/factor_effectiveness.md` | ⬜ | 因子有效性统计 |

---

### Layer 4：长上下文记忆层 [未启动]
**优先级：🟡 中**

| 任务 | 状态 | 文件 |
|------|------|------|
| `memory/sector_view.md` | ⬜ | 行业轮动判断 |
| `memory/active_signals.md` | ⬜ | 强势标的跟踪 |
| Context增强机制 | ⬜ | 分析前自动携带相关memory |

---

### Layer 5：Hypothesis Generator [未启动]
**优先级：🟢 低**

| 任务 | 状态 | 文件 |
|------|------|------|
| `scripts/hypothesis_generator.py` | ⬜ | AI自动提出市场假设 |
| `memory/hypotheses/{date}.md` | ⬜ | 假设存档 |

---

## 四、执行记录

### Phase 1：Layer 1 市场状态层 ✅

- [x] 新建 `memory/market_regime.md` 模板 — ✅
- [x] 新建 `scripts/daily_market_regime.py` — ✅
- [x] 测试单次regime报告生成（2026-05-11） — ✅
- [x] 设置cron每日17:00触发（cron id: 34dc1ad4） — ✅
- [x] 分析前自动读取机制（AGENTS.md已内置） — ✅
- [x] 报告完成时间：2026-05-11 16:34 — ✅

**Phase 1 完成后需要更新**：
- [x] 记录每日regime报告内容样本 — ✅（见上方首次运行结果）
- [x] 评估token消耗增量 — ✅（每次报告约5-10K tokens）
- [ ] 评估alpha提升效果 — 待持续运行后验证

---

## 五、核心指标跟踪

| 指标 | 基准（当前） | 目标 |
|------|------------|------|
| 单次分析input token | ~2-5K | ~30-80K |
| 日均有效研究token | ~50K | ~300-500K |
| 市场状态覆盖 | 0% | 每日100% |
| 复盘覆盖率 | 0% | 每日自动 |
| 多Agent并行 | 0% | 5路并行 |
| Context记忆连续性 | 几乎为零 | 3-5年积累 |

---

## 六、技术债务与已知问题

- [x] ML NaN bug（winrate_predictor.py 第226行）— 已修复
- [ ] G3/G5零信号问题（P_up集中在0.43-0.50）— 待解决（建议重训模型）
- [ ] G2 SETUPS单股票信号极少 — 需全市场扫描
- [ ] 历史回测数据持久化（进程kill导致丢失）— 待改进

---

## 七、版本历史

| 日期 | 更新内容 |
|------|---------|
| 2026-05-11 | 创建本方案，梳理现有基础和5层架构 |
| 2026-05-11 | Phase 1完成：daily_market_regime.py + cron每日17:00 + market_regime.md |
| 2026-05-11 | 首次报告：Regime=🚀超强牛市(6.5/7), SPY $737, QQQ RSI=84.2极度超买 |
