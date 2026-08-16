"""
yfinance caching layer with THREE fallback levels:
  1. SQLite cache (7-day TTL)
  2. Local SPY JSON (always available)
  3. Chrome CDP via Playwright (bypasses Yahoo Finance rate limits)
  4. Direct yfinance (last resort, may be rate limited)
"""

import os, sqlite3, json, time, re
from pathlib import Path
from datetime import datetime as dt

CACHE_DIR = Path(__file__).parent
CACHE_DB = CACHE_DIR / "yf_cache.db"
CACHE_TTL = 86400 * 7
LOCAL_SPY_JSON = Path("/home/yudengfeng/.openclaw/workspace/美股投资洞察分析/TradingAgents/中间过程/klines/SPY_1d.json")
CHROME_DEBUG_URL = "http://172.25.192.1:19222"

# ─── Cache DB ─────────────────────────────────────────────────────────────────

def _init_cache():
    CACHE_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(CACHE_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS yf_cache (
            ticker TEXT, start_date TEXT, end_date TEXT,
            result_json TEXT, cached_at REAL,
            PRIMARY KEY (ticker, start_date, end_date)
        )
    """)
    conn.commit()
    conn.close()


def _get_cached(ticker, start, end):
    try:
        conn = sqlite3.connect(str(CACHE_DB))
        row = conn.execute(
            "SELECT result_json, cached_at FROM yf_cache WHERE ticker=? AND start_date=? AND end_date=?",
            (ticker.upper(), start, end)
        ).fetchone()
        conn.close()
        if row and (time.time() - row[1]) < CACHE_TTL:
            return json.loads(row[0])
    except Exception:
        pass
    return None


def _save_cached(ticker, start, end, result_data):
    """Serialize DataFrame to JSON-friendly dict, handling MultiIndex columns."""
    try:
        import pandas as pd
        if not hasattr(result_data, 'to_dict'):
            serializable = {'type': 'raw', 'data': result_data}
            conn = sqlite3.connect(str(CACHE_DB))
            conn.execute(
                "INSERT OR REPLACE INTO yf_cache (ticker, start_date, end_date, result_json, cached_at) VALUES (?, ?, ?, ?, ?)",
                (ticker.upper(), start, end, json.dumps(serializable), time.time())
            )
            conn.commit()
            conn.close()
            return

        df = result_data
        # Capture index name BEFORE reset (reset_index destroys the original index)
        original_index_name = getattr(df.index, 'name', None)
        # Rename date-like index to 'Date' (uppercase) to match _clean_dataframe expectations
        if original_index_name is not None and str(original_index_name).lower() == 'date':
            pass  # index name will be normalized after reset_index below

        # Flatten MultiIndex columns if present
        flat_cols = []
        for col in df.columns:
            if isinstance(col, tuple):
                flat_cols.append('_'.join(str(c) for c in col))
            else:
                flat_cols.append(str(col))
        df_flat = df.copy()
        df_flat.columns = flat_cols

        # reset_index AFTER capturing name; then rename the 'date' column to 'Date'
        df_for_save = df_flat.reset_index()
        # The column from reset_index might be 'date' (lowercase) - normalize to 'Date'
        if original_index_name is not None and original_index_name.lower() == 'date':
            if 'date' in df_for_save.columns and 'Date' not in df_for_save.columns:
                df_for_save = df_for_save.rename(columns={'date': 'Date'})
            elif 'Date' not in df_for_save.columns and original_index_name.lower() in df_for_save.columns:
                df_for_save = df_for_save.rename(columns={original_index_name.lower(): 'Date'})

        # Convert Timestamp/ datetime values to strings for JSON serialization
        for col in df_for_save.columns:
            if col == 'Date' or col == 'date':
                df_for_save[col] = df_for_save[col].apply(
                    lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else str(x)
                )

        serializable = {
            'type': 'dataframe',
            'data': df_for_save.to_dict('list'),
            'index': [str(x) for x in df_for_save.index],
            'columns': list(df_for_save.columns),
            'index_name': 'Date',
            'original_columns': [list(c) if isinstance(c, tuple) else str(c) for c in df.columns]
        }
        conn = sqlite3.connect(str(CACHE_DB))
        conn.execute(
            "INSERT OR REPLACE INTO yf_cache (ticker, start_date, end_date, result_json, cached_at) VALUES (?, ?, ?, ?, ?)",
            (ticker.upper(), start, end, json.dumps(serializable), time.time())
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[yf_cache] Save error: {e}")


def _unserialize_cached(serialized):
    import pandas as pd
    if serialized.get('type') == 'dataframe':
        df = pd.DataFrame(serialized['data'], columns=serialized['columns'])
        df.index = pd.to_datetime(serialized['index'])
        if serialized.get('index_name'):
            df.index.name = serialized['index_name']
        df.index.freq = None
        return df
    if serialized.get('type') == 'raw':
        return serialized.get('data')
    return None


# ─── Chrome CDP ───────────────────────────────────────────────────────────────

_cdp_browser = None


def _fetch_via_cdp(ticker, start_date, end_date):
    """Fetch OHLCV data from Yahoo Finance via Chrome CDP (bypasses IP rate limits)."""
    global _cdp_browser
    from playwright.sync_api import sync_playwright

    with _cdp_lock:
        try:
            if _cdp_browser is None:
                p = sync_playwright().start()
                _cdp_browser = p.chromium.connect_over_cdp(CHROME_DEBUG_URL)
                ctx = _cdp_browser.contexts[0]
                page = ctx.new_page()
                page.set_default_timeout(20000)
                try:
                    page.goto('https://finance.yahoo.com', timeout=15000)
                    time.sleep(2)
                except Exception:
                    pass
                finally:
                    page.close()
                print(f"[yf_cache] Chrome CDP connected")

            browser = _cdp_browser
            ctx = browser.contexts[0]
            page = ctx.new_page()
            page.set_default_timeout(30000)

            start_ts = int(dt.strptime(start_date, '%Y-%m-%d').timestamp()) if isinstance(start_date, str) else int(start_date)
            end_ts = int(dt.strptime(end_date, '%Y-%m-%d').timestamp()) + 86399 if isinstance(end_date, str) else int(end_date) + 86399

            chart_url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
                         f"?period1={start_ts}&period2={end_ts}&interval=1d")

            r = page.goto(chart_url, timeout=30000)
            if not r or r.status != 200:
                page.close()
                return None

            content = page.content()
            page.close()

            m = re.search(r'\{"chart":\s*{.*}', content, re.DOTALL)
            if not m:
                return None

            chart_data = json.loads(m.group())
            result = chart_data.get('chart', {}).get('result', [])
            if not result:
                return None

            r0 = result[0]
            timestamps = r0.get('timestamp', [])
            quote = r0.get('indicators', {}).get('quote', [{}])
            if not timestamps or not quote:
                return None

            q = quote[0]
            closes = q.get('close', [])
            opens = q.get('open', [])
            highs = q.get('high', [])
            lows = q.get('low', [])
            vols = q.get('volume', [])

            bars = []
            for i, ts in enumerate(timestamps):
                dt_str = dt.utcfromtimestamp(ts).strftime('%Y-%m-%d')
                try:
                    bars.append({
                        'date': dt_str,
                        'open': round(float(opens[i]), 2) if opens[i] is not None else 0,
                        'high': round(float(highs[i]), 2) if highs[i] is not None else 0,
                        'low': round(float(lows[i]), 2) if lows[i] is not None else 0,
                        'close': round(float(closes[i]), 2) if closes[i] is not None else 0,
                        'volume': int(vols[i]) if vols[i] is not None else 0,
                    })
                except (ValueError, IndexError, TypeError):
                    continue

            bars.sort(key=lambda x: x['date'])
            print(f"[yf_cache] CDP fetched {len(bars)} bars for {ticker} {start_date}~{end_date}")
            return bars

        except Exception as e:
            print(f"[yf_cache] CDP error for {ticker}: {e}")
            try:
                page.close()
            except Exception:
                pass
            return None


def _bars_to_df(bars):
    import pandas as pd
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame(bars)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').set_index('date')
    df.index.name = 'Date'  # Must match what load_ohlcv/_clean_dataframe expects
    df = df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'})
    return df


# ─── Local SPY ────────────────────────────────────────────────────────────────

def _get_local_spy(start_str, end_str):
    try:
        with open(LOCAL_SPY_JSON) as f:
            data = json.load(f)
        bars = data.get('data', [])
        if not bars:
            return None
        import pandas as pd
        df = pd.DataFrame(bars)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').set_index('date')
        df = df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'})
        start_dt = pd.to_datetime(start_str) if start_str else df.index.min()
        end_dt = pd.to_datetime(end_str) if end_str else df.index.max()
        filtered = df[(df.index >= start_dt) & (df.index <= end_dt)]
        if len(filtered) == 0:
            return None
        return filtered
    except Exception as e:
        print(f"[yf_cache] Local SPY error: {e}")
        return None


# ─── Patched Ticker ──────────────────────────────────────────────────────────

_original_ticker_class = None
_original_download_func = None
import threading
_cdp_lock = threading.Lock()  # Global lock to serialize Playwright CDP calls

# -------------------------------------------------------------------
# Patch pd.Timestamp.today so load_ohlcv uses our backtest date, not
# the real system date (avoids cache filename mismatches across timezones)
# -------------------------------------------------------------------
_patched_today = None

def _patch_timestamp_today():
    global _patched_today
    import pandas as pd
    original_today = pd.Timestamp.today

    def fixed_today(tz=None):
        if _patched_today is not None:
            return _patched_today if tz is None else _patched_today.tz_localize(tz)
        return original_today(tz=tz)

    pd.Timestamp.today = staticmethod(fixed_today)


def set_experiment_date(date_str):
    """Set the date that load_ohlcv will use for its cache filename."""
    global _patched_today
    import pandas as pd
    _patched_today = pd.Timestamp(date_str)
    print(f"[yf_cache] Set experiment date to {date_str} (UTC)")


class CachedTicker:
    def __init__(self, ticker):
        global _original_ticker_class
        self._ticker = _original_ticker_class(ticker)
        self.ticker = ticker.upper()

    def history(self, start=None, end=None, auto_adjust=None, actions=None,
                group_by=None, adjust_close=None, keepna=None,
                period=None, postback=None, fixes=None):
        start_str = start.strftime('%Y-%m-%d') if hasattr(start, 'strftime') else str(start) if start else None
        end_str = end.strftime('%Y-%m-%d') if hasattr(end, 'strftime') else str(end) if end else None

        # 1. SQLite cache
        cached = _get_cached(self.ticker, start_str, end_str)
        if cached is not None:
            return _unserialize_cached(cached)

        # 2. Local SPY
        if self.ticker == 'SPY':
            local = _get_local_spy(start_str, end_str)
            if local is not None:
                _save_cached(self.ticker, start_str, end_str, local)
                return local

        # 3. Try original history
        try:
            result = self._ticker.history(
                start=start, end=end, auto_adjust=auto_adjust, actions=actions,
                group_by=group_by, adjust_close=adjust_close, keepna=keepna,
                period=period, postback=postback, fixes=fixes
            )
            # yfinance may return empty DF instead of raising on rate limit
            if result is not None and not result.empty:
                _save_cached(self.ticker, start_str, end_str, result)
                return result
            print(f"[yf_cache] history returned empty for {self.ticker} {start_str}~{end_str}, trying CDP...")
        except Exception as e:
            print(f"[yf_cache] history exception for {self.ticker} {start_str}~{end_str}: {e}, trying CDP...")

        # 4. CDP fallback
        bars = _fetch_via_cdp(self.ticker, start_str or '2019-01-01', end_str or '2030-01-01')
        if bars:
            df = _bars_to_df(bars)
            _save_cached(self.ticker, start_str, end_str, df)
            return df

        from yfinance.exceptions import YFRateLimitError
        raise YFRateLimitError(f"All sources failed for {self.ticker} {start_str}~{end_str}")

    def __getattr__(self, name):
        return getattr(self._ticker, name)


# ─── CDP download helper ──────────────────────────────────────────────────────

def _cdp_download(symbol, start, end, multi_level_index=True, **kwargs):
    bars = _fetch_via_cdp(symbol, start, end)
    if not bars:
        return None
    df_simple = _bars_to_df(bars)
    import pandas as pd
    if multi_level_index:
        # MultiIndex columns: (symbol, field)
        df_out = pd.DataFrame({
            (symbol, 'Open'): df_simple['Open'],
            (symbol, 'High'): df_simple['High'],
            (symbol, 'Low'): df_simple['Low'],
            (symbol, 'Close'): df_simple['Close'],
            (symbol, 'Volume'): df_simple['Volume'],
        }, index=df_simple.index)
        df_out.index.name = 'Datetime'
    else:
        # Simple columns matching yf.download with multi_level_index=False
        # Includes Adj Close = Close (CDP doesn't provide adjusted prices)
        df_out = df_simple.copy()
        df_out['Adj Close'] = df_out['Close']
        df_out.index.name = 'Date'
    return df_out


# ─── Apply patch ─────────────────────────────────────────────────────────────

def apply():
    global _original_ticker_class, _original_download_func
    _init_cache()
    _patch_timestamp_today()

    import yfinance as yf
    from yfinance.exceptions import YFRateLimitError as YFRE

    # Patch yf.Ticker
    _original_ticker_class = yf.Ticker
    yf.Ticker = lambda t: CachedTicker(t)

    # Patch yf.download
    _original_download_func = yf.download
    def cached_download(symbol, start=None, end=None, **kwargs):
        if isinstance(symbol, list):
            symbol = symbol[0] if symbol else symbol
        start_str = start.strftime('%Y-%m-%d') if hasattr(start, 'strftime') else str(start) if start else None
        end_str = end.strftime('%Y-%m-%d') if hasattr(end, 'strftime') else str(end) if end else None
        import sys
        print(f"[yf_cache][CD] called: {symbol} {start_str}~{end_str}", flush=True)

        cached = _get_cached(str(symbol), start_str, end_str)
        if cached is not None:
            print(f"[yf_cache][CD] SQLite HIT", flush=True)
            return _unserialize_cached(cached)

        try:
            result = _original_download_func(symbol, start=start, end=end, **kwargs)
            print(f"[yf_cache][CD] yf.download returned {len(result) if result is not None else 'None'} rows", flush=True)
            if result is not None and not result.empty:
                _save_cached(str(symbol), start_str, end_str, result)
                print(f"[yf_cache][CD] saved to cache", flush=True)
                return result
        except Exception as e:
            print(f"[yf_cache][CD] yf.download exception: {e}", flush=True)

        # Rate limited or error → CDP fallback
        print(f"[yf_cache][CD] falling back to CDP...", flush=True)
        multi_level = kwargs.get('multi_level_index', True)
        result = _cdp_download(symbol, start_str or '2019-01-01', end_str or '2030-01-01',
                              multi_level_index=multi_level)
        if result is not None:
            _save_cached(str(symbol), start_str, end_str, result)
            print(f"[yf_cache][CD] CDP returned {len(result)} rows", flush=True)
            return result

        from yfinance.exceptions import YFRateLimitError
        raise YFRateLimitError("All sources failed")

        result = _cdp_download(symbol, start_str or '2019-01-01', end_str or '2030-01-01')
        if result is not None:
            _save_cached(str(symbol), start_str, end_str, result)
            return result

        raise YFRE(f"All sources failed for {symbol}")

    yf.download = cached_download

    print(f"[yf_cache] Patch applied. Cache: {CACHE_DB}")
    print(f"[yf_cache] Local SPY: {LOCAL_SPY_JSON}")
    print(f"[yf_cache] Chrome CDP: {CHROME_DEBUG_URL}")
