"""
data_fetcher.py
Fetches live NSE option chain, Nifty OHLCV, India VIX.
Uses NSE's public web endpoints (no API key needed).
"""

import requests
import pandas as pd
import numpy as np
import time
import logging
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger(__name__)

# --- NSE session (must mimic browser headers or NSE returns 403) ---
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer":         "https://www.nseindia.com/",
    "Connection":      "keep-alive",
}

NSE_BASE   = "https://www.nseindia.com"
OC_URL     = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
VIX_URL    = "https://www.nseindia.com/api/allIndices"
QUOTE_URL  = "https://www.nseindia.com/api/quote-equity?symbol=NIFTY+50"
FII_URL    = "https://www.nseindia.com/api/fiidiiTradeReact"


def _get_nse_session() -> requests.Session:
    """Create a session that first visits the NSE homepage to get cookies."""
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        session.get(NSE_BASE, timeout=10)
        time.sleep(0.5)
    except Exception as e:
        logger.warning(f"Could not prime NSE session: {e}")
    return session


_session: Optional[requests.Session] = None
_session_created: Optional[float] = None
SESSION_TTL = 300  # refresh session every 5 minutes


def get_session() -> requests.Session:
    global _session, _session_created
    now = time.time()
    if _session is None or (now - (_session_created or 0)) > SESSION_TTL:
        logger.info("Creating new NSE session...")
        _session = _get_nse_session()
        _session_created = now
    return _session


def _fetch(url: str, retries: int = 3) -> Optional[dict]:
    for attempt in range(retries):
        try:
            session = get_session()
            resp = session.get(url, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 403:
                logger.warning("NSE 403 — refreshing session")
                global _session
                _session = None
                time.sleep(2)
            else:
                logger.warning(f"HTTP {resp.status_code} from {url}")
                time.sleep(1)
        except Exception as e:
            logger.warning(f"Fetch attempt {attempt+1} failed: {e}")
            time.sleep(2)
    return None


# ------------------------------------------------------------------ #
#  OPTION CHAIN
# ------------------------------------------------------------------ #

def fetch_option_chain(symbol: str = "NIFTY") -> Optional[dict]:
    """
    Returns a dict with:
      - spot_price
      - expiry           (nearest weekly)
      - calls            (DataFrame)
      - puts             (DataFrame)
      - pcr              (put-call ratio by OI)
      - max_pain         (strike)
      - atm_strike
      - atm_iv
      - total_call_oi
      - total_put_oi
    """
    url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    data = _fetch(url)
    if not data:
        return None

    try:
        spot = float(data["records"]["underlyingValue"])
        expiries = data["records"]["expiryDates"]
        nearest_expiry = expiries[0]   # closest expiry (weekly)

        records = []
        for item in data["records"]["data"]:
            if item.get("expiryDate") != nearest_expiry:
                continue
            strike = item["strikePrice"]
            ce = item.get("CE", {})
            pe = item.get("PE", {})
            records.append({
                "strike":    strike,
                "ce_ltp":    ce.get("lastPrice", 0),
                "ce_oi":     ce.get("openInterest", 0),
                "ce_chg_oi": ce.get("changeinOpenInterest", 0),
                "ce_vol":    ce.get("totalTradedVolume", 0),
                "ce_iv":     ce.get("impliedVolatility", 0),
                "pe_ltp":    pe.get("lastPrice", 0),
                "pe_oi":     pe.get("openInterest", 0),
                "pe_chg_oi": pe.get("changeinOpenInterest", 0),
                "pe_vol":    pe.get("totalTradedVolume", 0),
                "pe_iv":     pe.get("impliedVolatility", 0),
            })

        df = pd.DataFrame(records).sort_values("strike").reset_index(drop=True)

        total_call_oi = df["ce_oi"].sum()
        total_put_oi  = df["pe_oi"].sum()
        pcr = round(total_put_oi / total_call_oi, 3) if total_call_oi > 0 else 0

        # Max Pain — strike where total option buyer loss is maximum
        max_pain = _calc_max_pain(df)

        # ATM strike
        atm_strike = df.iloc[(df["strike"] - spot).abs().argsort()[:1]]["strike"].values[0]
        atm_row = df[df["strike"] == atm_strike].iloc[0]
        atm_iv = round((atm_row["ce_iv"] + atm_row["pe_iv"]) / 2, 2)

        return {
            "spot_price":    spot,
            "expiry":        nearest_expiry,
            "df":            df,
            "pcr":           pcr,
            "max_pain":      max_pain,
            "atm_strike":    atm_strike,
            "atm_iv":        atm_iv,
            "total_call_oi": total_call_oi,
            "total_put_oi":  total_put_oi,
        }

    except Exception as e:
        logger.error(f"Option chain parse error: {e}")
        return None


def _calc_max_pain(df: pd.DataFrame) -> int:
    """Standard max pain calculation."""
    pain = {}
    for target in df["strike"]:
        loss = 0
        for _, row in df.iterrows():
            # call writer loss
            if target > row["strike"]:
                loss += (target - row["strike"]) * row["ce_oi"]
            # put writer loss
            if target < row["strike"]:
                loss += (row["strike"] - target) * row["pe_oi"]
        pain[target] = loss
    return min(pain, key=pain.get)


# ------------------------------------------------------------------ #
#  SPOT PRICE + OHLCV (from index quotes)
# ------------------------------------------------------------------ #

def fetch_nifty_ohlcv() -> Optional[dict]:
    """Fetch today's Nifty OHLCV from NSE indices endpoint."""
    data = _fetch(VIX_URL)
    if not data:
        return None
    try:
        for item in data.get("data", []):
            if item.get("index") == "NIFTY 50":
                return {
                    "ltp":    item.get("last",     0),
                    "open":   item.get("open",     0),
                    "high":   item.get("dayHigh",  0),
                    "low":    item.get("dayLow",   0),
                    "prev":   item.get("previousClose", 0),
                    "change": item.get("change",   0),
                    "pct":    item.get("percentChange", 0),
                }
    except Exception as e:
        logger.error(f"OHLCV parse error: {e}")
    return None


# ------------------------------------------------------------------ #
#  INDIA VIX
# ------------------------------------------------------------------ #

def fetch_india_vix() -> Optional[float]:
    data = _fetch(VIX_URL)
    if not data:
        return None
    try:
        for item in data.get("data", []):
            if item.get("index") == "India VIX":
                return float(item.get("last", 0))
    except Exception as e:
        logger.error(f"VIX parse error: {e}")
    return None


# ------------------------------------------------------------------ #
#  FII / DII DATA
# ------------------------------------------------------------------ #

def fetch_fii_dii() -> Optional[dict]:
    data = _fetch(FII_URL)
    if not data:
        return None
    try:
        # NSE returns last few days; we want today's row
        rows = data if isinstance(data, list) else data.get("data", [])
        if not rows:
            return None
        today = rows[0]   # most recent
        return {
            "date":     today.get("date", ""),
            "fii_net":  float(today.get("fi_netValue", 0)),
            "dii_net":  float(today.get("di_netValue", 0)),
        }
    except Exception as e:
        logger.error(f"FII/DII parse error: {e}")
    return None


# ------------------------------------------------------------------ #
#  CANDLE HISTORY (from NSE historical — last 20 days for EMA)
# ------------------------------------------------------------------ #

def fetch_historical_data(symbol: str = "NIFTY 50", days: int = 30) -> Optional[pd.DataFrame]:
    """
    Fetch historical OHLCV to compute EMAs and trend on daily timeframe.
    Uses NSE's historical API.
    """
    from datetime import timedelta
    end_date   = date.today()
    start_date = end_date - timedelta(days=days + 10)  # buffer for holidays

    url = (
        f"https://www.nseindia.com/api/historical/cm/equity"
        f"?symbol=NIFTY+50&series=[%22EQ%22]"
        f"&from={start_date.strftime('%d-%m-%Y')}"
        f"&to={end_date.strftime('%d-%m-%Y')}"
    )
    # Nifty 50 as an index uses a different endpoint
    index_url = (
        f"https://www.nseindia.com/api/historical/indicesHistory"
        f"?indexType=NIFTY%2050"
        f"&from={start_date.strftime('%d-%m-%Y')}"
        f"&to={end_date.strftime('%d-%m-%Y')}"
    )
    data = _fetch(index_url)
    if not data:
        return None

    try:
        rows = data.get("data", {}).get("indexCloseOnlineRecords", [])
        if not rows:
            return None
        df = pd.DataFrame(rows)
        df = df.rename(columns={
            "EOD_TIMESTAMP":     "date",
            "EOD_OPEN_INDEX_VAL":"open",
            "EOD_HIGH_INDEX_VAL":"high",
            "EOD_LOW_INDEX_VAL": "low",
            "EOD_CLOSE_INDEX_VAL":"close",
        })
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").tail(days).reset_index(drop=True)
        for col in ["open","high","low","close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Compute EMAs
        df["ema20"]  = df["close"].ewm(span=20,  adjust=False).mean()
        df["ema50"]  = df["close"].ewm(span=50,  adjust=False).mean()
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()

        return df
    except Exception as e:
        logger.error(f"Historical parse error: {e}")
        return None


# ------------------------------------------------------------------ #
#  AGGREGATE — single call returns everything
# ------------------------------------------------------------------ #

def fetch_all_data() -> dict:
    """Master fetch — returns all data needed by the scorer."""
    logger.info("Fetching all market data...")
    oc    = fetch_option_chain("NIFTY")
    ohlcv = fetch_nifty_ohlcv()
    vix   = fetch_india_vix()
    fii   = fetch_fii_dii()
    hist  = fetch_historical_data()

    result = {
        "timestamp":    datetime.now(),
        "option_chain": oc,
        "ohlcv":        ohlcv,
        "vix":          vix,
        "fii_dii":      fii,
        "historical":   hist,
        "fetch_ok":     all([oc, ohlcv, vix]),
    }
    logger.info(
        f"Fetch complete | spot={oc['spot_price'] if oc else 'N/A'} "
        f"| VIX={vix} | PCR={oc['pcr'] if oc else 'N/A'}"
    )
    return result
