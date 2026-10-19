"""
Equity Analyst Agent — world-class NSE India equity research powered by Claude.

Capabilities:
  - Live index & stock quotes with fundamentals (P/E, P/B, 52-week, VWAP)
  - Stock screener across any NSE index
  - 1-year price history + technical indicators (SMA, RSI, MACD, Bollinger)
  - Peer / sector comparison
  - Full agentic loop: Claude decides which tools to call and synthesises analysis
"""

import csv
import io
import json
import math
import sys
import time
from datetime import datetime, timedelta

import requests
import anthropic

MODEL = "claude-opus-5-5"

# ── NSE constituent CSV map (reused from nse_indices.py) ──────────────────────

CONSTITUENT_CSV = {
    "NIFTY 50":                "ind_nifty50list.csv",
    "NIFTY NEXT 50":           "ind_niftynext50list.csv",
    "NIFTY 100":               "ind_nifty100list.csv",
    "NIFTY 200":               "ind_nifty200list.csv",
    "NIFTY 500":               "ind_nifty500list.csv",
    "NIFTY BANK":              "ind_niftybanklist.csv",
    "NIFTY IT":                "ind_niftyitlist.csv",
    "NIFTY AUTO":              "ind_niftyautolist.csv",
    "NIFTY PHARMA":            "ind_niftypharmalist.csv",
    "NIFTY FMCG":              "ind_niftyfmcglist.csv",
    "NIFTY METAL":             "ind_niftymetallist.csv",
    "NIFTY REALTY":            "ind_niftyrealtylist.csv",
    "NIFTY MIDCAP 50":         "ind_niftymidcap50list.csv",
    "NIFTY MIDCAP 100":        "ind_niftymidcap100list.csv",
    "NIFTY MIDCAP 150":        "ind_niftymidcap150list.csv",
    "NIFTY SMALLCAP 50":       "ind_niftysmallcap50list.csv",
    "NIFTY SMALLCAP 100":      "ind_niftysmallcap100list.csv",
    "NIFTY SMALLCAP 250":      "ind_niftysmallcap250list.csv",
    "NIFTY LARGEMIDCAP 250":   "ind_niftylargemidcap250list.csv",
    "NIFTY MIDSMALLCAP 400":   "ind_niftymidsmallcap400list.csv",
    "NIFTY HEALTHCARE INDEX":  "ind_niftyhealthcarelist.csv",
    "NIFTY INFRASTRUCTURE":    "ind_niftyinfralist.csv",
    "NIFTY ENERGY":            "ind_niftyenergylist.csv",
    "NIFTY MEDIA":             "ind_niftymedialist.csv",
    "NIFTY MNC":               "ind_niftymnclist.csv",
    "NIFTY PSU BANK":          "ind_niftypsubanklist.csv",
    "NIFTY CPSE":              "ind_niftycpselist.csv",
    "NIFTY PSE":               "ind_niftypselist.csv",
    "NIFTY COMMODITIES":       "ind_niftycommoditieslist.csv",
    "NIFTY INDIA CONSUMPTION": "ind_niftyconsumptionlist.csv",
    "NIFTY CONSUMER DURABLES": "ind_niftyconsumerdurableslist.csv",
}

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "X-Requested-With": "XMLHttpRequest",
}

# ── Tool definitions ──────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "fetch_nse_indices",
        "description": (
            "Fetch live NSE India index overview. Returns all indices with "
            "last price, change, % change, open, high, low, previous close, "
            "52-week high/low, P/E, P/B, dividend yield, advances/declines. "
            "Filter by category: BROAD MARKET INDICES, SECTORAL INDICES, "
            "THEMATIC INDICES, STRATEGY INDICES, FIXED INCOME INDICES."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": (
                        "Optional category filter. One of: 'BROAD MARKET INDICES', "
                        "'INDICES ELIGIBLE IN DERIVATIVES', 'SECTORAL INDICES', "
                        "'THEMATIC INDICES', 'STRATEGY INDICES', 'FIXED INCOME INDICES'."
                    ),
                }
            },
            "required": [],
        },
    },
    {
        "name": "fetch_index_stocks",
        "description": (
            "Fetch all constituent stocks of an NSE index with live market data. "
            "Returns each stock's symbol, company name, sector, last price, "
            "change, % change, open, high, low, 52-week high/low, traded volume & value, "
            "1-year return, 30-day return. "
            f"Supported indices: {', '.join(sorted(CONSTITUENT_CSV.keys()))}. "
            "Use this for sector analysis, ranking stocks within an index, "
            "or getting a broad market snapshot."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "index": {
                    "type": "string",
                    "description": "The index name exactly, e.g. 'NIFTY 50', 'NIFTY BANK'.",
                }
            },
            "required": ["index"],
        },
    },
    {
        "name": "fetch_stock_quote",
        "description": (
            "Fetch a detailed live quote for a single NSE-listed stock by its symbol. "
            "Returns: company name, industry/sector, last price, open, high, low, "
            "previous close, VWAP, % change, 52-week high/low (with date), "
            "total traded volume, total traded value, face value, issued capital, "
            "P/E, P/B, and intraday range. "
            "Use this for single-stock deep dives."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "NSE ticker symbol, e.g. 'RELIANCE', 'INFY', 'HDFCBANK'.",
                }
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "fetch_stock_history",
        "description": (
            "Fetch up to 1 year of daily OHLCV price history for an NSE stock. "
            "Also computes technical indicators: "
            "SMA-20, SMA-50, SMA-200 (simple moving averages), "
            "RSI-14 (relative strength index), "
            "MACD line / signal / histogram (12-26-9), "
            "Bollinger Bands (20-day, 2σ). "
            "Use for trend analysis, momentum, support/resistance identification."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "NSE ticker symbol, e.g. 'TCS', 'WIPRO'.",
                },
                "days": {
                    "type": "integer",
                    "description": "Number of calendar days to look back (max 365). Default 365.",
                },
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "screen_stocks",
        "description": (
            "Screen / filter stocks across an NSE index by fundamental or "
            "price-momentum criteria. "
            "Criteria fields (all optional, use only the ones you need): "
            "min_pe, max_pe, min_pb, max_pb, "
            "min_pct_change_today, max_pct_change_today, "
            "min_pct_change_1y, max_pct_change_1y, "
            "min_pct_change_30d, max_pct_change_30d, "
            "near_52w_high (bool — within 5% of 52-week high), "
            "near_52w_low (bool — within 5% of 52-week low), "
            "sector (string — exact sector name match). "
            "Returns the filtered list sorted by 1-year return descending."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "index": {
                    "type": "string",
                    "description": "NSE index to screen within, e.g. 'NIFTY 500'.",
                },
                "criteria": {
                    "type": "object",
                    "description": "Key-value pairs of screening criteria as described.",
                    "additionalProperties": True,
                },
            },
            "required": ["index", "criteria"],
        },
    },
    {
        "name": "compare_stocks",
        "description": (
            "Side-by-side comparison of 2–10 NSE stocks on key metrics: "
            "price, % change today, 52-week high/low, 1-year return, 30-day return, "
            "P/E, P/B, traded volume. "
            "Use for peer group / sector comparison, or relative-value analysis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of 2–10 NSE ticker symbols.",
                },
                "index": {
                    "type": "string",
                    "description": (
                        "Optional NSE index name to pull data from (faster). "
                        "If omitted, data is fetched per-symbol."
                    ),
                },
            },
            "required": ["symbols"],
        },
    },
]

# ── NSE session helper ────────────────────────────────────────────────────────

_session_cache: dict = {}


def _nse_session() -> requests.Session:
    """Create (or reuse) a cookie-primed NSE session."""
    if _session_cache.get("session"):
        return _session_cache["session"]
    s = requests.Session()
    s.headers.update({
        "User-Agent": NSE_HEADERS["User-Agent"],
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    s.get("https://www.nseindia.com/", timeout=15)
    s.headers.update(NSE_HEADERS)
    _session_cache["session"] = s
    return s


def _safe_float(v) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


# ── Tool implementations ──────────────────────────────────────────────────────

def fetch_nse_indices(category: str | None = None) -> list[dict]:
    session = _nse_session()
    resp = session.get("https://www.nseindia.com/api/allIndices", timeout=15)
    resp.raise_for_status()
    data = resp.json()["data"]
    if category:
        data = [d for d in data if d.get("key", "").upper() == category.upper()]
    fields = [
        "key", "index", "indexSymbol", "last", "variation", "percentChange",
        "open", "high", "low", "previousClose", "yearHigh", "yearLow",
        "pe", "pb", "dy", "advances", "declines",
    ]
    return [{f: d[f] for f in fields if f in d} for d in data]


def fetch_index_stocks(index: str) -> list[dict] | dict:
    """Get live stock data for all constituents of an index."""
    index_upper = index.upper()
    # Map common abbreviations
    index_map = {
        "NIFTY50": "NIFTY 50", "NIFTY100": "NIFTY 100",
        "NIFTY200": "NIFTY 200", "NIFTY500": "NIFTY 500",
        "NIFTYBANK": "NIFTY BANK", "NIFTYIT": "NIFTY IT",
    }
    resolved = index_map.get(index_upper.replace(" ", ""), index)

    session = _nse_session()
    url = f"https://www.nseindia.com/api/equity-stockIndices?index={requests.utils.quote(resolved)}"
    resp = session.get(url, timeout=15)
    if resp.status_code == 404:
        return {"error": f"Index '{index}' not found on NSE."}
    resp.raise_for_status()
    raw = resp.json().get("data", [])

    results = []
    for s in raw:
        sym = s.get("symbol", "")
        if not sym or sym == resolved:  # skip the index row itself
            continue
        results.append({
            "symbol":         sym,
            "companyName":    s.get("meta", {}).get("companyName", ""),
            "industry":       s.get("meta", {}).get("industry", ""),
            "lastPrice":      s.get("lastPrice"),
            "open":           s.get("open"),
            "high":           s.get("high"),
            "low":            s.get("low"),
            "previousClose":  s.get("previousClose"),
            "pChange":        s.get("pChange"),
            "change":         s.get("change"),
            "totalVolume":    s.get("totalTradedVolume"),
            "totalValue":     s.get("totalTradedValue"),
            "yearHigh":       s.get("yearHigh") or s.get("fiftyTwoWeekHigh"),
            "yearLow":        s.get("yearLow") or s.get("fiftyTwoWeekLow"),
            "perChange365d":  s.get("perChange365d"),
            "perChange30d":   s.get("perChange30d"),
        })
    return results


def fetch_stock_quote(symbol: str) -> dict:
    session = _nse_session()
    url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol.upper()}"
    resp = session.get(url, timeout=15)
    if resp.status_code == 404:
        return {"error": f"Symbol '{symbol}' not found on NSE."}
    resp.raise_for_status()
    d = resp.json()

    pi = d.get("priceInfo", {})
    meta = d.get("metadata", {})
    si = d.get("securityInfo", {})
    ii = d.get("industryInfo", {})
    wkhl = pi.get("weekHighLow", {})
    intra = pi.get("intraDayHighLow", {})

    return {
        "symbol":         symbol.upper(),
        "companyName":    meta.get("companyName"),
        "series":         meta.get("series"),
        "isin":           meta.get("isin"),
        "industry":       meta.get("industry"),
        "sector":         ii.get("sector"),
        "basicIndustry":  ii.get("basicIndustry"),
        "lastPrice":      pi.get("lastPrice"),
        "open":           pi.get("open"),
        "high":           intra.get("max") or pi.get("intraDayHighLow", {}).get("max"),
        "low":            intra.get("min") or pi.get("intraDayHighLow", {}).get("min"),
        "previousClose":  pi.get("previousClose"),
        "vwap":           pi.get("vwap"),
        "pChange":        pi.get("pChange"),
        "change":         pi.get("change"),
        "weekHigh52":     wkhl.get("max"),
        "weekHigh52Date": wkhl.get("maxDate"),
        "weekLow52":      wkhl.get("min"),
        "weekLow52Date":  wkhl.get("minDate"),
        "totalVolume":    d.get("marketDeptOrderBook", {}).get("tradeInfo", {}).get("totalTradedVolume"),
        "totalValue":     d.get("marketDeptOrderBook", {}).get("tradeInfo", {}).get("totalTradedValue"),
        "faceValue":      si.get("faceValue"),
        "issuedCap":      si.get("issuedCap"),
        "pdSymbolPe":     d.get("metadata", {}).get("pdSymbolPe"),
        "pdSectorPe":     d.get("metadata", {}).get("pdSectorPe"),
        "pdSectorPb":     d.get("metadata", {}).get("pdSectorPb"),
    }


# ── Technical indicator helpers ───────────────────────────────────────────────

def _sma(closes: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        result[i] = sum(closes[i - period + 1 : i + 1]) / period
    return result


def _ema(closes: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(closes)
    k = 2 / (period + 1)
    seed_idx = period - 1
    if seed_idx >= len(closes):
        return result
    result[seed_idx] = sum(closes[:period]) / period
    for i in range(seed_idx + 1, len(closes)):
        result[i] = closes[i] * k + result[i - 1] * (1 - k)  # type: ignore[operator]
    return result


def _rsi(closes: list[float], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(closes)
    if len(closes) < period + 1:
        return result
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(closes)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else float("inf")
        result[i] = 100 - (100 / (1 + rs))
    return result


def _macd(closes: list[float], fast=12, slow=26, signal=9):
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line: list[float | None] = []
    for f, s in zip(ema_fast, ema_slow):
        macd_line.append(f - s if f is not None and s is not None else None)  # type: ignore[operator]
    valid_macd = [v for v in macd_line if v is not None]
    signal_raw = _ema(valid_macd, signal)
    # re-align signal to full length
    offset = len(macd_line) - len(valid_macd)
    signal_line: list[float | None] = [None] * offset + signal_raw
    histogram: list[float | None] = []
    for m, sg in zip(macd_line, signal_line):
        histogram.append(m - sg if m is not None and sg is not None else None)  # type: ignore[operator]
    return macd_line, signal_line, histogram


def _bollinger(closes: list[float], period: int = 20, num_std: float = 2.0):
    upper: list[float | None] = [None] * len(closes)
    lower: list[float | None] = [None] * len(closes)
    mid = _sma(closes, period)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        mean = mid[i]
        if mean is None:
            continue
        std = math.sqrt(sum((x - mean) ** 2 for x in window) / period)
        upper[i] = mean + num_std * std
        lower[i] = mean - num_std * std
    return mid, upper, lower


def fetch_stock_history(symbol: str, days: int = 365) -> dict:
    days = min(max(days, 30), 365)
    end = datetime.now()
    start = end - timedelta(days=days)

    fmt = "%d-%m-%Y"
    url = (
        "https://www.nseindia.com/api/historical/cm/equity"
        f"?symbol={symbol.upper()}"
        f'&series=["EQ"]'
        f"&from={start.strftime(fmt)}&to={end.strftime(fmt)}"
    )
    session = _nse_session()
    resp = session.get(url, timeout=20)
    if resp.status_code == 404:
        return {"error": f"No history for '{symbol}'."}
    resp.raise_for_status()
    raw = resp.json().get("data", [])

    if not raw:
        return {"error": f"No historical data returned for '{symbol}'."}

    # NSE returns newest first — reverse to chronological
    raw = list(reversed(raw))
    dates   = [r["CH_TIMESTAMP"] for r in raw]
    closes  = [float(r["CH_CLOSING_PRICE"]) for r in raw]
    opens   = [float(r["CH_OPENING_PRICE"]) for r in raw]
    highs   = [float(r["CH_TRADE_HIGH_PRICE"]) for r in raw]
    lows    = [float(r["CH_TRADE_LOW_PRICE"]) for r in raw]
    volumes = [int(r.get("CH_TOT_TRADED_QTY", 0)) for r in raw]

    sma20  = _sma(closes, 20)
    sma50  = _sma(closes, 50)
    sma200 = _sma(closes, 200)
    rsi14  = _rsi(closes, 14)
    macd_line, signal_line, histogram = _macd(closes)
    bb_mid, bb_upper, bb_lower = _bollinger(closes, 20)

    def last(lst):
        for v in reversed(lst):
            if v is not None:
                return round(v, 2)
        return None

    latest = closes[-1] if closes else None
    history = []
    for i, d in enumerate(dates):
        history.append({
            "date": d, "open": opens[i], "high": highs[i],
            "low": lows[i], "close": closes[i], "volume": volumes[i],
        })

    return {
        "symbol":       symbol.upper(),
        "bars":         len(dates),
        "from":         dates[0] if dates else None,
        "to":           dates[-1] if dates else None,
        "currentPrice": latest,
        "indicators": {
            "sma20":      last(sma20),
            "sma50":      last(sma50),
            "sma200":     last(sma200),
            "rsi14":      last(rsi14),
            "macdLine":   last(macd_line),
            "macdSignal": last(signal_line),
            "macdHist":   last(histogram),
            "bbUpper":    last(bb_upper),
            "bbMid":      last(bb_mid),
            "bbLower":    last(bb_lower),
        },
        "trend": {
            "above_sma20":  (latest > last(sma20))  if latest and last(sma20)  else None,
            "above_sma50":  (latest > last(sma50))  if latest and last(sma50)  else None,
            "above_sma200": (latest > last(sma200)) if latest and last(sma200) else None,
            "rsi_signal": (
                "overbought" if (r14 := last(rsi14)) and r14 > 70
                else "oversold" if r14 and r14 < 30
                else "neutral"
            ),
            "macd_signal": (
                "bullish" if (mh := last(histogram)) and mh > 0
                else "bearish" if mh and mh < 0
                else "neutral"
            ),
        },
        "history": history[-30:],  # last 30 bars to keep payload manageable
    }


def screen_stocks(index: str, criteria: dict) -> list[dict]:
    stocks = fetch_index_stocks(index)
    if isinstance(stocks, dict) and "error" in stocks:
        return [stocks]  # type: ignore[list-item]

    results = []
    for s in stocks:
        pc_today = _safe_float(s.get("pChange"))
        pc_1y    = _safe_float(s.get("perChange365d"))
        pc_30d   = _safe_float(s.get("perChange30d"))
        price    = _safe_float(s.get("lastPrice"))
        yr_high  = _safe_float(s.get("yearHigh"))
        yr_low   = _safe_float(s.get("yearLow"))

        # Sector filter
        if "sector" in criteria:
            ind = (s.get("industry") or "").lower()
            if criteria["sector"].lower() not in ind:
                continue

        # P/E and P/B — only available from index-level data (perChange365d endpoint)
        # skip PE/PB filters here since they're not in index-stocks payload
        # (they are available via quote endpoint — screener uses what it has)

        if "min_pct_change_today" in criteria and (pc_today is None or pc_today < criteria["min_pct_change_today"]):
            continue
        if "max_pct_change_today" in criteria and (pc_today is None or pc_today > criteria["max_pct_change_today"]):
            continue
        if "min_pct_change_1y" in criteria and (pc_1y is None or pc_1y < criteria["min_pct_change_1y"]):
            continue
        if "max_pct_change_1y" in criteria and (pc_1y is None or pc_1y > criteria["max_pct_change_1y"]):
            continue
        if "min_pct_change_30d" in criteria and (pc_30d is None or pc_30d < criteria["min_pct_change_30d"]):
            continue
        if "max_pct_change_30d" in criteria and (pc_30d is None or pc_30d > criteria["max_pct_change_30d"]):
            continue
        if criteria.get("near_52w_high") and (not price or not yr_high or price < yr_high * 0.95):
            continue
        if criteria.get("near_52w_low") and (not price or not yr_low or price > yr_low * 1.05):
            continue

        results.append(s)

    results.sort(key=lambda x: _safe_float(x.get("perChange365d")) or -9999, reverse=True)
    return results


def compare_stocks(symbols: list[str], index: str | None = None) -> list[dict]:
    if index:
        all_stocks = fetch_index_stocks(index)
        if isinstance(all_stocks, dict):
            all_stocks = []
        lookup = {s["symbol"]: s for s in all_stocks}
        rows = []
        for sym in symbols:
            row = lookup.get(sym.upper())
            if row:
                rows.append(row)
            else:
                # fallback to quote
                q = fetch_stock_quote(sym)
                if "error" not in q:
                    rows.append({
                        "symbol": q["symbol"],
                        "companyName": q.get("companyName"),
                        "industry": q.get("industry"),
                        "lastPrice": q.get("lastPrice"),
                        "pChange": q.get("pChange"),
                        "yearHigh": q.get("weekHigh52"),
                        "yearLow": q.get("weekLow52"),
                        "perChange365d": None,
                        "perChange30d": None,
                    })
    else:
        rows = []
        for sym in symbols:
            q = fetch_stock_quote(sym)
            if "error" not in q:
                rows.append({
                    "symbol": q["symbol"],
                    "companyName": q.get("companyName"),
                    "industry": q.get("industry"),
                    "lastPrice": q.get("lastPrice"),
                    "open": q.get("open"),
                    "high": q.get("high"),
                    "low": q.get("low"),
                    "previousClose": q.get("previousClose"),
                    "pChange": q.get("pChange"),
                    "yearHigh": q.get("weekHigh52"),
                    "yearLow": q.get("weekLow52"),
                    "pe": q.get("pdSymbolPe"),
                    "sectorPe": q.get("pdSectorPe"),
                    "sectorPb": q.get("pdSectorPb"),
                    "perChange365d": None,
                    "perChange30d": None,
                })
            time.sleep(0.3)  # be polite to NSE
    return rows


# ── Tool dispatcher ───────────────────────────────────────────────────────────

def run_tool(name: str, tool_input: dict) -> str:
    try:
        if name == "fetch_nse_indices":
            return json.dumps(fetch_nse_indices(tool_input.get("category")))
        if name == "fetch_index_stocks":
            return json.dumps(fetch_index_stocks(tool_input["index"]))
        if name == "fetch_stock_quote":
            return json.dumps(fetch_stock_quote(tool_input["symbol"]))
        if name == "fetch_stock_history":
            return json.dumps(fetch_stock_history(
                tool_input["symbol"], tool_input.get("days", 365)
            ))
        if name == "screen_stocks":
            return json.dumps(screen_stocks(
                tool_input["index"], tool_input.get("criteria", {})
            ))
        if name == "compare_stocks":
            return json.dumps(compare_stocks(
                tool_input["symbols"], tool_input.get("index")
            ))
        return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ── System prompt — world-class equity analyst persona ────────────────────────

SYSTEM_PROMPT = """You are an elite sell-side equity analyst specialising in Indian equities (NSE/BSE). \
You combine the rigour of a Goldman Sachs / Morgan Stanley analyst with deep knowledge of the Indian \
market structure, regulatory environment (SEBI), and macro backdrop.

Your analytical framework:
1. FUNDAMENTAL ANALYSIS — assess valuation multiples (P/E, P/B, EV/EBITDA), return ratios (ROE, ROCE), \
   growth trajectory, balance-sheet health, and dividend history relative to sector peers.
2. TECHNICAL ANALYSIS — interpret price action, moving averages (SMA-20/50/200), momentum (RSI, MACD), \
   Bollinger Bands, 52-week range positioning, and volume trends.
3. SECTOR & MACRO CONTEXT — relate company performance to sector themes (rate cycle, commodity cycle, \
   credit growth, capex cycle, FII/DII flows) and broader Nifty/market breadth signals.
4. RISK FACTORS — identify key downside risks: promoter pledging, debt levels, regulatory headwinds, \
   concentration risk, competitive threats.
5. INVESTMENT THESIS — synthesise all the above into a clear BUY / ACCUMULATE / HOLD / REDUCE / SELL \
   recommendation with a 12-month price target rationale and catalysts to watch.

Communication style:
- Lead with the most important insight; avoid burying the lede.
- Use bullet points and clear section headers for readability.
- Always cite the specific data points (price, P/E, RSI value, etc.) underpinning your view.
- Quantify everything you can: "up 42% YTD, P/E at 28x vs sector at 22x".
- Flag data limitations honestly (e.g. live P/E not available for small-caps via index API).
- If asked for a screening result, present a ranked table with key metrics.
- Speak with conviction but acknowledge uncertainty; give probabilities where appropriate.
- Today's date context: use it to frame 52-week ranges and YTD / calendar-year performance.

Tools available:
- fetch_nse_indices: broad market & sector index dashboard
- fetch_index_stocks: all stocks inside an index with live prices and returns
- fetch_stock_quote: single-stock deep-dive (live price, 52w range, VWAP, sector P/E)
- fetch_stock_history: 1-year OHLCV + SMA/RSI/MACD/Bollinger indicators
- screen_stocks: filter any index by momentum or valuation criteria
- compare_stocks: peer-group side-by-side table

Always call the most relevant tools before answering. Never guess prices from memory — always fetch live data."""


# ── Agent loop ────────────────────────────────────────────────────────────────

def ask(question: str, verbose: bool = False) -> str:
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": question}]

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if verbose:
            print(f"[stop_reason={response.stop_reason}]", file=sys.stderr)

        text_parts = [b.text for b in response.content if b.type == "text"]

        if response.stop_reason == "end_turn":
            return "\n".join(text_parts)

        if response.stop_reason != "tool_use":
            return "\n".join(text_parts) or f"[stopped: {response.stop_reason}]"

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                if verbose:
                    print(f"[tool] {block.name}({json.dumps(block.input)})", file=sys.stderr)
                result = run_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
        messages.append({"role": "user", "content": tool_results})


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="NSE Equity Analyst Agent")
    parser.add_argument("question", nargs="*", help="Your question or analysis request")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show tool calls")
    args = parser.parse_args()

    question = " ".join(args.question) if args.question else (
        "Give me a market overview: top 3 Nifty 50 gainers and losers today, "
        "plus a quick read on which sectors are leading/lagging."
    )
    print(f"\n{'='*72}")
    print(f"Q: {question}")
    print(f"{'='*72}\n")
    print(ask(question, verbose=args.verbose))


if __name__ == "__main__":
    main()
