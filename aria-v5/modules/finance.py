"""modules/finance.py — Realtime finance: stocks, crypto, forex, indices (free APIs)"""
import os, time, json, threading
import requests

_cache = {}
_LOCK  = threading.Lock()

# ── Free API sources ──────────────────────────────────────────────────────
ALPHA_KEY = os.environ.get("ALPHA_KEY", "")  # alphavantage.co — free 25 req/day

CRYPTO_IDS = {
    "BTC": "bitcoin",  "ETH": "ethereum",    "BNB": "binancecoin",
    "SOL": "solana",   "ADA": "cardano",      "XRP": "ripple",
    "DOGE": "dogecoin","AVAX": "avalanche-2", "DOT": "polkadot",
    "LINK": "chainlink","MATIC": "matic-network","LTC": "litecoin",
}

INDICES = {
    "SET":  ("^SET.BK",  "Thailand SET"),
    "SP500":("^GSPC",    "S&P 500"),
    "DJI":  ("^DJI",     "Dow Jones"),
    "NDX":  ("^NDX",     "NASDAQ 100"),
    "NIKKEI":("^N225",   "Nikkei 225"),
    "HSI":  ("^HSI",     "Hang Seng"),
    "FTSE": ("^FTSE",    "FTSE 100"),
}

def _coingecko_batch(ids: list) -> dict:
    """Fetch multiple crypto prices from CoinGecko (free, no key)"""
    id_str = ",".join(ids)
    url = (f"https://api.coingecko.com/api/v3/simple/price"
           f"?ids={id_str}&vs_currencies=usd,thb"
           f"&include_24hr_change=true&include_24hr_vol=true&include_market_cap=true")
    r = requests.get(url, timeout=10, headers={"User-Agent":"ARIA-Finance/5"})
    r.raise_for_status()
    return r.json()

def _yf_quote(symbol: str) -> dict:
    """Yahoo Finance quote (unofficial but free)"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
    r = requests.get(url, timeout=8, headers={
        "User-Agent": "Mozilla/5.0 (compatible; ARIA-Finance/5)"
    })
    d = r.json()
    meta = d.get("chart", {}).get("result", [{}])[0].get("meta", {})
    return {
        "symbol":        symbol,
        "name":          meta.get("longName") or meta.get("shortName") or symbol,
        "price":         meta.get("regularMarketPrice", 0),
        "prev_close":    meta.get("chartPreviousClose", 0),
        "currency":      meta.get("currency", "USD"),
        "exchange":      meta.get("exchangeName", ""),
        "market_state":  meta.get("marketState", ""),
    }

def get_crypto_prices(symbols: list = None) -> list:
    if symbols is None:
        symbols = list(CRYPTO_IDS.keys())[:12]
    ids = [CRYPTO_IDS[s] for s in symbols if s in CRYPTO_IDS]
    cache_key = "crypto_" + ",".join(symbols)
    with _LOCK:
        c = _cache.get(cache_key)
        if c and time.time() - c["ts"] < 30:  # 30s cache for crypto
            return c["data"]
    try:
        raw = _coingecko_batch(ids)
        result = []
        for sym in symbols:
            cg_id = CRYPTO_IDS.get(sym)
            if not cg_id or cg_id not in raw: continue
            d = raw[cg_id]
            price = d.get("usd", 0)
            prev  = price / (1 + (d.get("usd_24h_change", 0)/100)) if price else 0
            result.append({
                "symbol":   sym,
                "name":     cg_id.replace("-"," ").title(),
                "price":    round(price, 6 if price < 1 else 2),
                "price_thb":round(d.get("thb", 0), 2),
                "change24h":round(d.get("usd_24h_change", 0), 2),
                "vol24h":   d.get("usd_24h_vol", 0),
                "mcap":     d.get("usd_market_cap", 0),
                "type":     "crypto",
                "ts":       time.time(),
            })
        with _LOCK:
            _cache[cache_key] = {"ts": time.time(), "data": result}
        return result
    except Exception as e:
        return [{"error": str(e)}]

def get_forex() -> list:
    """Free forex from exchangerate-api.com"""
    cache_key = "forex"
    with _LOCK:
        c = _cache.get(cache_key)
        if c and time.time() - c["ts"] < 60:
            return c["data"]
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=8)
        rates = r.json().get("rates", {})
        pairs = ["THB","EUR","GBP","JPY","CNY","KRW","SGD","HKD","AUD","CAD","CHF","MYR"]
        result = [{"pair": f"USD/{p}", "rate": round(rates[p],4), "type":"forex", "ts": time.time()}
                  for p in pairs if p in rates]
        with _LOCK:
            _cache[cache_key] = {"ts": time.time(), "data": result}
        return result
    except Exception as e:
        return [{"error": str(e)}]

def get_indices() -> list:
    """World indices via Yahoo Finance"""
    cache_key = "indices"
    with _LOCK:
        c = _cache.get(cache_key)
        if c and time.time() - c["ts"] < 60:
            return c["data"]
    result = []
    for name, (sym, label) in INDICES.items():
        try:
            q = _yf_quote(sym)
            price = q["price"]
            prev  = q["prev_close"] or price
            chg   = round((price - prev) / prev * 100, 2) if prev else 0
            result.append({
                "symbol":   name,
                "name":     label,
                "price":    round(price, 2),
                "change24h":chg,
                "currency": q["currency"],
                "type":     "index",
                "state":    q["market_state"],
                "ts":       time.time(),
            })
        except:
            pass
    with _LOCK:
        _cache[cache_key] = {"ts": time.time(), "data": result}
    return result

def get_thai_stocks(symbols: list = None) -> list:
    """Thai SET stocks via Yahoo Finance (.BK suffix)"""
    if symbols is None:
        symbols = ["PTT","ADVANC","AOT","SCB","CPALL","GULF","TRUE","KBANK"]
    cache_key = "thai_" + ",".join(symbols)
    with _LOCK:
        c = _cache.get(cache_key)
        if c and time.time() - c["ts"] < 60:
            return c["data"]
    result = []
    for sym in symbols:
        try:
            q = _yf_quote(sym + ".BK")
            price = q["price"]
            prev  = q["prev_close"] or price
            chg   = round((price - prev) / prev * 100, 2) if prev else 0
            result.append({
                "symbol":   sym,
                "name":     q["name"],
                "price":    round(price, 2),
                "change24h":chg,
                "currency": "THB",
                "type":     "stock",
                "exchange": "SET",
                "state":    q["market_state"],
                "ts":       time.time(),
            })
        except:
            pass
    with _LOCK:
        _cache[cache_key] = {"ts": time.time(), "data": result}
    return result

def get_us_stocks(symbols: list = None) -> list:
    if symbols is None:
        symbols = ["AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","NFLX"]
    cache_key = "us_" + ",".join(symbols)
    with _LOCK:
        c = _cache.get(cache_key)
        if c and time.time() - c["ts"] < 60:
            return c["data"]
    result = []
    for sym in symbols:
        try:
            q = _yf_quote(sym)
            price = q["price"]
            prev  = q["prev_close"] or price
            chg   = round((price - prev) / prev * 100, 2) if prev else 0
            result.append({
                "symbol":   sym,
                "name":     q["name"],
                "price":    round(price, 2),
                "change24h":chg,
                "currency": "USD",
                "type":     "stock",
                "exchange": q["exchange"],
                "state":    q["market_state"],
                "ts":       time.time(),
            })
        except:
            pass
    with _LOCK:
        _cache[cache_key] = {"ts": time.time(), "data": result}
    return result
