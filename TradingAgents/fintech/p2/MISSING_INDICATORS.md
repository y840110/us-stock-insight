# Regime Engine V2 - 缺失数据指标清单

> 创建时间：2026-05-15
> 更新状态：🟡 进行中

---

## ✅ 已解决（已集成到 P1）

| 指标 | 文件路径 | 数据源 | 状态 |
|------|---------|--------|------|
| DXY | `klines/DXY_1d.json` | Yahoo Finance (DX-Y.NYB) | ✅ 已有 |
| VIX | `klines/VIX_1d.json` | Yahoo Finance → 本地 | ✅ 已有 |
| US10Y (TNX) | `klines/TNX_1d.json` | FRED (DGS10) | ✅ 已集成 |
| HY Spread | `klines/HY_SPREAD_1d.json` | FRED (BAMLH0A0HYM2EY) | ✅ 已集成 |
| VVIX | `klines/VVIX_1d.json` | CBOE API | ✅ 已集成 |
| LIQUIDITY_SCORE | `klines/WALCL/RRPONTSYD/WTREGEN_1d.json` | Fed H.4.1 (Chrome CDP) | ✅ 已集成 |
| PUT_CALL_RATIO | `market_indicators/PUT_CALL_RATIO_1d.json` | CBOE (Chrome CDP) | ✅ 已集成 |
| SPY 相关全部 | `klines/SPY_1d.json` | Yahoo Finance → 本地 | ✅ 已有 |
| 广度数据 | `klines/sp500_breadth_*.json` | finviz.com | ✅ 已有 |

---

## ❌ 仍未解决

以下指标暂时**没有找到可靠的数据源**，需要逐一解决：

---

### 1. GEX（机构 Gamma Exposure）
- **状态**: ✅ 已解决！用 Gamma Regime Proxy（2026-05-15）
- **文件**: `中间过程/market_indicators/GAMMA_REGIME_1d.json`
- **数据源**: VIX(Yahoo) + SPY(Yahoo) + PutCallRatio(CBOE)
- **当前值**: NEUTRAL (score=2) → GEX=0.0

**计算方法**：
  5个市场行为指标加权综合：
  - VIX Level（最重要）
  - VIX Momentum（5日变化率）
  - Put/Call Ratio（CBOE）
  - SPY vs 20EMA
  - SPY RSI(14)
  score >= +3 → POSITIVE_GAMMA（+1）；<= -3 → NEGATIVE_GAMMA（-1）

**注意**：真正的 GEX（机构 Gamma Exposure）需要 SPX 期权链 OI+IV 数据，
无免费数据源。当前用市场行为代理，性价比最高。
如未来获得期权链数据，可替换为 `dmart1441/SPX-Gamma-Exposure` 算法。

---

### 3. PUT_CALL_RATIO（看跌/看涨比率）
- **状态**: ✅ 已解决（2026-05-15）
- **文件**: `中间过程/market_indicators/PUT_CALL_RATIO_1d.json`
- **数据源**: CBOE（Chrome CDP）
- **当前值**: TOTAL=0.67

---

### 4. CTA_POSITIONING（CTA 持仓方向）
- **来源**: CFTC COT 报告
- **FRED**: ⚠️ 有部分 COT 数据但格式复杂
- **状态**: 🟡 需要继续探索

**可行方案**：
1. CFTC 官方 COT CSV 下载（需要解析复杂格式）
2. FRED 有部分 COT 指数数据
3. **暂时用常量或代理**

---

### 5. NYAD（NYSE 涨跌线）
- **来源**: NYSE 官方每日涨跌家数
- **StockCharts**: ⚠️ 有 cumulative A/D 数据，但解析困难
- **状态**: 🟡 需要继续探索

**可行方案**：
1. 自己计算：每日 NYAD = 前日 NYAD + (NYSE上涨家数 - 下跌家数)
   - 需要 NYSE 每日 A/D 数据（可通过 Wikipedia、CNBC 等来源）
2. StockCharts 页面解析（HTML 结构不固定）
3. **暂时用代理指标**

---

### 6. VVIX（VIX 的波动率）
- **CBOE**: ✅ 已解决！专属 API
- **API**: `https://cdn.cboe.com/api/global/delayed_quotes/quotes/_VVIX.json`
- **FRED**: ❌ 无
- **Yahoo Finance**: ❌ 无
- **状态**: ✅ 已解决（2026-05-15）
- **当前值**: 94.26
- **文件**: `klines/VVIX_1d.json`
- **接入**: `fetch_market_indicators_fred.py`（CBOE_SERIES）

---

### 7. FCI（金融条件指数）
- **来源**: Bloomberg / Goldman Sachs / IMF
- **FRED**: ❌ 无
- **状态**: 🔴 极难获取

**可行方案**：
1. 用代理指标组合：`(US10Y - VIX) / DXY`
2. 参考 Goldman Sachs FCI 计算方法自建
3. **暂时用常量 0**

---

### 8. LIQUIDITY_SCORE（流动性评分）
- **来源**: Fed 资产负债表
- **FRED**: ⚠️ 有总资产数据（WALCL）
- **状态**: 🟡 可通过 Fed 资产负债表计算

**可行方案**：
1. FRED `WALCL`（Fed 总资产）同比变化率作为代理
2. 或用 `M2` 货币供应量变化率
3. **可实现，计算中**

---

## 📋 优先级排序

| 优先级 | 指标 | 难度 | 建议方案 |
|--------|------|------|----------|
| 🔴 高 | LIQUIDITY_SCORE | 简单 | FRED WALCL 同比变化 |
| 🔴 高 | CTA_POSITIONING | 中等 | CFTC COT 报告解析 |
| 🟡 中 | PUT_CALL_RATIO | 中等 | Yahoo Finance 或 CBOE 解析 |
| 🟡 中 | NYAD | 中等 | StockCharts 解析或自建 |
| 🟡 中 | GEX | 中等 | 开源算法 + 期权链数据 |
| 🟢 低 | VVIX | 难 | CBOE 专属页面 CDP |
| 🟢 低 | FCI | 极难 | 自建代理指标 |

---

## 📁 数据文件路径

```
美股投资洞察分析/
├── TradingAgents/fintech/p1/klines/
│   ├── SPY_1d.json           ✅
│   ├── DXY_1d.json           ✅
│   ├── VIX_1d.json           ✅
│   ├── TNX_1d.json           ✅（FRED）
│   ├── HY_SPREAD_1d.json     ✅（FRED）
│   └── VIX_FRED_1d.json     ✅（FRED备份）
│
└── 中间过程/market_indicators/     ← CBOE 指标存放目录
    ├── PUT_CALL_RATIO_1d.json     ❌ 待实现
    ├── GEX_1d.json                ❌ 待实现（代理）
    ├── CTA_POSITIONING_1d.json    ❌ 待实现
    ├── NYAD_1d.json               ❌ 待实现
    └── FCI_1d.json                ❌ 待实现（代理）
```

---

## 🔧 已知数据源 URL

| 指标 | URL | 备注 |
|------|-----|------|
| CBOE 历史数据下载 | https://www.cboe.com/us/options/market_statistics/historical_data/ | 需解析 |
| CBOE VIX 页面 | https://www.cboe.com/tradable_products/vix/ | VVIX 在此页 |
| StockCharts A/D | https://stockcharts.com/freecharts/advdecl.php?b=1 | NYAD |
| CFTC COT 报告 | https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm | CTA |
| FRED WALCL（Fed资产）| https://fred.stlouisfed.org/graph/freedgraph.csv?id=WALCL | LIQUIDITY |
| SPX-Gamma-Exposure | https://github.com/dmart1441/SPX-Gamma-Exposure | GEX 算法 |

---

## ✅ 2026-05-16 新解决

### NYAD（NYSE 涨跌线）
- **状态**: ✅ 已解决！
- **方法**: 从 569 只股票每日涨跌统计自建 NYAD
- **文件**: `fintech/p1/klines/NYAD_1d.json`
- **结果**: NYAD = +10,288（2026-05-15），20日斜率 -47.6/day
- **关键发现**: SPY 连续3次创20日新高，但 NYAD 未跟随 → 顶背离 🔴

### CTA_POSITIONING（CTA 持仓方向）
- **状态**: ✅ 已解决！
- **来源**: Tradingster JSON API（原始 CFTC COT 数据）
- **URL**: `https://www.tradingster.com/api/cot/legacy-futures/13874%2B`
- **文件**: `fintech/p1/klines/CTA_POSITIONING_1d.json`
- **脚本**: `fintech/p1/fetch_cot_cta.py`
- **当前值**（2026-05-12）：
  - Noncommercial Long: 266,045
  - Noncommercial Short: 404,950
  - Net = **-138,905（极度做空）**
  - Historical %ile: **10.9%**（历史上极度做空）
  - Weekly change: **-40,324**（做空增加）

### FCI（金融条件指数代理）
- **状态**: ✅ 已解决！
- **公式**: `(US10Y - VIX) / DXY`
- **来源**: US10Y (FRED DGS10), VIX, DXY
- **当前值**: -0.1407 → 🟢 宽松环境
- **解读**: FCI < 0 = 宽松，风险资产有利

### TNX（美国10年期国债）路径修复
- **问题**: `get_us10y_yield()` 找不到 TNX 文件
- **原因**: 文件实际在 `TradingAgents/TradingAgents/fintech/p1/klines/TNX_1d.json`（嵌套路径）
- **修复**: 更新路径搜索逻辑，优先查找嵌套路径
- **状态**: ✅ 已解决

---

## ❌ 仍未解决

| 指标 | 状态 | 说明 |
|------|------|------|
| GEX | ✅ 已用代理 | Gamma Regime Proxy（已有实现） |
| NYAD | ✅ 已解决 | 自建（569只股票统计） |
| CTA | ✅ 已解决 | Tradingster COT API |
| FCI | ✅ 已解决 | (US10Y - VIX) / DXY 代理 |
| LIQUIDITY_SCORE | ✅ 已解决 | Fed H.4.1（2026-05-15） |
| PUT_CALL_RATIO | ✅ 已解决 | CBOE CDP |
| VVIX | ✅ 已解决 | CBOE API |

**所有指标均已解决！regime_engine_v2.py 可以完整运行。**
