# CDO 工作总结

> 本文件由 CDO 持续维护，每次数据获取任务后更新。记录铁律、流程、最佳实践和教训。

---

## 一、核心铁律

### 铁律 1：获取数据前，先确认本地现状

**永远不猜、不假设，先查再看。**

```
获取数据前必须执行：
1. 确认今日日期
2. 确认本地文件最新日期
3. 以两者差值决定是否需要拉取新数据
```

**错误的做法**：
- 「今天是周六，应该有周五数据」→ 直接假设
- 「上次数据应该是最新的」→ 不查文件
- 「yfinance 能用就直接用」→ 不检查本地日期

**正确的做法**：
- 先 `cat` 或 `python json.load` 查看本地文件最新日期
- 再确认今日日期
- 计算差值，判断是否需要补充

---

### 铁律 2：多数据源比对

**一个源失败，立即换另一个，不放弃。**

当日数据获取优先级：
| 优先级 | 数据源 | 方法 |
|--------|--------|------|
| ① | 富途 OpenD | Python SDK `OpenQuoteContext` |
| ② | Yahoo Finance API | `yfinance` Python 包 |
| ③ | Yahoo Finance | **Browser JS Fetch**（绕过 API 限速） |
| ④ | Yahoo Finance 网页 | Playwright CDP（等待渲染） |

---

### 铁律 3：K 线数据必须以 `time`/`date` 字段为锚点

**禁止用数组位置（如 `data[0]` 或 `data[-1]`）判断最新价格。**

每条 K 线都有 `date` 字段（格式：`"May 8, 2026"` 或 `"YYYY-MM-DD"`），必须遍历找 `date` 最近的那条，取其 `close`。

```python
# ❌ 错误
price = data[0]['close']  # 假设第一条是最新的

# ✅ 正确
latest_record = max(data, key=lambda x: x['date'])
price = latest_record['close']
```

---

### 铁律 4：交易日历是唯一标准，不用"周几"判断

**不用「周几」推测是否有新数据，以 Yahoo Finance 返回的实际交易日历为准。**

```python
# 获取美股真实交易日历（60天）
GET https://query1.finance.yahoo.com/v8/finance/chart/SPY?interval=1d&range=60d
# → 返回 timestamp[] → 转日期列表

# 比对差集
yahoo_dates = {2026-02-12, 2026-02-13, ..., 2026-05-08}
local_dates  = {Sep 9, 2025, Sep 10, 2025, ...}
missing      = yahoo_dates - local_dates  # 需要补充的日期
```

---

## 二、美股每日数据获取标准流程

### Step 1：确认今日日期和本地数据现状

```python
import json, os
from datetime import datetime

TODAY = datetime.now().strftime('%Y-%m-%d')  # e.g. "2026-05-09"
KLINES_DIR = '美股投资洞察分析/TradingAgents/中间过程/klines'
TICKERS = ['SPY', 'QQQ', 'NVDA', 'AMD', 'TSLA', 'AVGO', 'AMZN',
           'MSFT', 'GOOGL', 'AAPL', 'ARM', 'SMCI', 'PLTR', 'ASML', 'AMAT', 'MU']

# 检查本地现状
for ticker in TICKERS:
    fpath = f'{KLINES_DIR}/{ticker}_1d.json'
    if os.path.exists(fpath):
        with open(fpath) as f:
            d = json.load(f)
        dates = [r['date'] for r in d.get('data', [])]
        latest = max(dates) if dates else '空'
        print(f'{ticker}: 最新={latest}, 共{len(dates)}条')
```

---

### Step 2：获取 Yahoo Finance 真实交易日历

```python
from playwright.sync_api import sync_playwright

CHROME_DEBUG_URL = 'http://172.25.192.1:19222'

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(CHROME_DEBUG_URL)
    ctx = browser.contexts[0]
    # 找已有的 Yahoo Finance 页面，或新建一个
    page = ctx.pages[0]
    
    # 获取 SPY 的60日交易日历
    calendar = page.evaluate('''async () => {
        const resp = await fetch(
            `https://query1.finance.yahoo.com/v8/finance/chart/SPY?interval=1d&range=60d`,
            { headers: { 'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json' } }
        );
        const d = await resp.json();
        const r = d.chart.result[0];
        return r.timestamp.map((t, i) => ({
            date: new Date(t * 1000).toISOString().split('T')[0],
            ts: t,
            close: r.indicators.quote[0].close[i]?.toFixed(2)
        }));
    }''')
    # calendar 按时间升序：[最旧, ..., 最新]
    yahoo_dates = {row['date'] for row in calendar}
```

---

### Step 3：计算缺失日期，精确拉取

```python
def find_missing_dates(yahoo_dates, local_dates):
    """返回本地缺失的交易日期集合"""
    return yahoo_dates - local_dates

for ticker in TICKERS:
    local_dates = {r['date'] for r in d['data']}  # 从 Step 1 已加载
    missing = find_missing_dates(yahoo_dates, local_dates)
    
    if not missing:
        print(f'[{ticker}] ✅ 已最新')
    else:
        print(f'[{ticker}] 缺失 {sorted(missing)}')
        # fetch_klines_for_dates(page, ticker, missing)
```

---

### Step 4：Browser JS Fetch 拉取 K 线数据

**关键：yfinance API 限速时，用 Browser JS Fetch 绕过。**

```python
def fetch_klines(browser_page, ticker, date_set):
    """
    通过浏览器 JS fetch 获取60天K线，过滤出 date_set 中的日期
    """
    raw = browser_page.evaluate(f'''async () => {{
        const resp = await fetch(
            `https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=60d`,
            {{ headers: {{ 'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json' }} }}
        );
        const d = await resp.json();
        const r = d.chart.result[0];
        const adj = r.indicators.adjclose?.[0]?.adjclose ?? r.indicators.quote[0].close;
        return r.timestamp.map((t, i) => {{
            const dateObj = new Date(t * 1000);
            const dateStr = dateObj.toLocaleDateString('en-US',
                {{month:'short', day:'numeric', year:'numeric'}});
            return {{
                date: dateStr,
                ts: t,
                open: r.indicators.quote[0].open[i]?.toFixed(2),
                high: r.indicators.quote[0].high[i]?.toFixed(2),
                low: r.indicators.quote[0].low[i]?.toFixed(2),
                close: r.indicators.quote[0].close[i]?.toFixed(2),
                adj: adj[i]?.toFixed(2),
                vol: r.indicators.quote[0].volume[i]
            }};
        }});
    }}''')
    # 过滤出需要的日期
    return [r for r in raw if r['date'] in date_set]
```

---

### Step 5：增量更新本地 K 线文件

```python
def update_local_klines(ticker, new_records):
    """只追加本地没有的新日期，不覆盖已有数据"""
    fpath = f'{KLINES_DIR}/{ticker}_1d.json'
    
    if os.path.exists(fpath):
        with open(fpath) as f:
            existing = json.load(f)
        existing_dates = {r['date'] for r in existing['data']}
        to_add = [r for r in new_records if r['date'] not in existing_dates]
        if to_add:
            # 按 ts 倒序合并
            existing['data'] = sorted(
                to_add + existing['data'],
                key=lambda x: x['ts'], reverse=True
            )
            for r in existing['data']:
                del r['ts']  # 保存时不带 ts
            existing['count'] = len(existing['data'])
            with open(fpath, 'w') as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            return len(to_add)
        return 0
    else:
        # 新建文件
        ...
```

---

### Step 6：保存最新行情快照

```python
# 每次获取完成后，更新快照文件
snapshot = {
    'fetched_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'data_date': max(yahoo_dates),  # 日历中最新的交易日
    'source': 'Yahoo Finance (Browser JS Fetch)',
    'tickers': {
        ticker: {
            'price': price,
            'date': latest_date,
            'chg_pct': chg_pct,
            'volume': volume,
            'day_high': day_high,
            'day_low': day_low
        }
    }
}
with open('中间过程/us_market_latest.json', 'w') as f:
    json.dump(snapshot, f, indent=2)
```

---

## 三、数据文件路径

| 用途 | 路径 |
|------|------|
| 美股日K线 | `美股投资洞察分析/TradingAgents/中间过程/klines/{TICKER}_1d.json` |
| 美股周K线 | `美股投资洞察分析/TradingAgents/中间过程/klines/{TICKER}_1wk.json` |
| 最新行情快照 | `美股投资洞察分析/中间过程/us_market_latest.json` |
| 港股日K线 | `股票投资分析/中间过程/daily_YYYY-MM-DD/stock_historical_250d.json` |
| 富途连接 | `股票投资分析/scripts/daily_data_collect.py` |

---

## 四、K 线 JSON 文件格式

```json
{
  "ticker": "SPY",
  "interval": "1d",
  "count": 60,
  "data": [
    {
      "date": "May 8, 2026",
      "open": "734.93",
      "high": "738.07",
      "low": "734.57",
      "close": "737.62",
      "adj": "737.62",
      "vol": 46071534
    },
    {
      "date": "May 7, 2026",
      "open": "735.05",
      ...
    }
  ]
}
```

**排序规则**：`data[]` 按 `date` 倒序（最新在前）。

---

## 五、常见问题处理

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| `YFRateLimitError` | yfinance 请求过于频繁 | 等 5-10 分钟，或改用 Browser JS Fetch |
| HTTP 403 Forbidden | 直接 HTTP 请求被 Yahoo 拒绝 | 加 Origin/Referer Headers，或用 Browser JS |
| `networkidle` 超时 | Yahoo Finance JS 持续请求资源 | 改用 `wait_until='load'` 或 `'domcontentloaded'` |
| 价格元素为空 | JS 未渲染完成 | 加 `page.wait_for_timeout(2000)` 等待 |
| `data[-1]` 读错价格 | K 线数据未按日期排序 | 必须以 `date` 字段为准 |
| 以为是最新实际已过期 | 没有先检查本地日期 | 每次获取前必须检查本地文件最新日期 |
| 周六以为有周五数据 | 用"周几"推测 | 以 Yahoo 日历 API 返回的 `timestamp` 为准 |

---

## 六、Chrome CDP 连接方式

```python
from playwright.sync_api import sync_playwright

CHROME_DEBUG_URL = 'http://172.25.192.1:19222'  # WSL2 → Windows Chrome

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(CHROME_DEBUG_URL)
    ctx = browser.contexts[0]
    # 优先复用已有页面
    for pg in ctx.pages:
        if 'SPY' in pg.url and 'quote' in pg.url:
            page = pg
            break
    if not page:
        page = ctx.new_page()
    # 使用 page.evaluate() 执行 JS fetch
```

---

## 七、关键教训（2026-05-09）

### 教训 1：不要假设本地数据是最新的
**现象**：本地 SPY_1d.json 最新日期为 Sep 9, 2025，全部缺失 2026 年数据，但未经检查就尝试拉新数据。
**代价**：浪费一次 API 调用，且没有发现本地数据已过期。
**原则**：每次任务前，必须 `json.load` 检查本地文件最新日期。

### 教训 2：yfinance API 会限速，不能依赖
**现象**：连续调用 yfinance 多次后返回 `YFRateLimitError`。
**发现**：Browser JS Fetch（通过已登录的 Chrome 页面执行）可以绕过此限速。
**原则**：yfinance 是便捷工具但不稳定，Browser JS Fetch 是保底方案。

### 教训 3："周几"判断是错误的
**现象**：错误认为"周六应该有周五数据"，实际上 Yahoo Finance 5月7日前后确实有限速问题。
**原则**：永远以 `timestamp` 列表为准，不用日历日或星期几推测。

### 教训 4：Yahoo Finance 返回 403 时换源
**现象**：直接 HTTP 请求 Yahoo Finance API 返回 403 Forbidden。
**方案**：加 Browser  headers（Origin/Referer）后成功；或直接用 Browser JS Fetch。

---

### 教训 5："文件存在即跳过"导致大量数据过期（2026-05-10）
**现象**：`fetch_us_stock_klines_v4.py` 的更新逻辑是「文件已存在就跳过」，完全不检查日期。结果：107只股票中98只数据过期（最后日期2025年5月），只有15只碰巧较新（如 NVDA/SPY/AMD 等）。
**根因**：脚本设计时只考虑了「首次下载」，没有考虑「数据更新」场景。
**修复方案**：修改脚本，文件存在时也检查最新日期，若超过7天则重新下载。
**教训**：数据健康检查不能只看 GLW 一只股票，要检查所有持仓股票。

---

*最后更新：2026-05-10 17:15*
