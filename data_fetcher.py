"""
Data ingestion layer.

Uses yfinance for free, no-API-key live/historical OHLCV data.
Swap `fetch_candles()` internals later for Dhan/Angel One/Fyers
WebSocket feeds if you want true tick-by-tick data — the rest of
the app only depends on getting back a pandas DataFrame with
columns: Open, High, Low, Close, Volume indexed by datetime.
"""

import logging
from datetime import datetime, time as dtime

try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except ImportError:
    IST = None  # fall back to system local time if zoneinfo/tzdata unavailable

import pandas as pd
import yfinance as yf

from config import CANDLE_INTERVAL, CANDLE_PERIOD, MARKET_OPEN, MARKET_CLOSE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data_fetcher")


def is_market_open(now: datetime = None) -> bool:
    """
    True only on NSE trading days (Mon-Fri, holidays not accounted
    for) between MARKET_OPEN and MARKET_CLOSE (config.py), IST.
    """
    now = now or (datetime.now(IST) if IST else datetime.now())
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    open_t = dtime.fromisoformat(MARKET_OPEN)
    close_t = dtime.fromisoformat(MARKET_CLOSE)
    return open_t <= now.time() <= close_t


def to_yf_symbol(symbol: str) -> str:
    """Convert a plain NSE symbol like 'RELIANCE' to yfinance format 'RELIANCE.NS'."""
    if symbol.startswith("^"):
        return symbol
    if symbol.endswith(".NS"):
        return symbol
    return f"{symbol}.NS"


def fetch_candles(symbol: str, interval: str = CANDLE_INTERVAL,
                   period: str = CANDLE_PERIOD) -> pd.DataFrame:
    """
    Fetch OHLCV candle data for a single symbol.
    Returns an empty DataFrame on failure (never raises), so the
    scoring loop can skip a bad symbol without crashing the run.
    """
    yf_symbol = to_yf_symbol(symbol)
    try:
        df = yf.Ticker(yf_symbol).history(period=period, interval=interval)
        if df is None or df.empty:
            logger.warning(f"No data returned for {symbol}")
            return pd.DataFrame()
        df = df.rename(columns=str.title)  # ensure Open/High/Low/Close/Volume
        return df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    except Exception as e:
        logger.warning(f"Failed to fetch {symbol}: {e}")
        return pd.DataFrame()


def fetch_last_price(symbol: str) -> float | None:
    """Quick helper to get the latest close price for a symbol."""
    df = fetch_candles(symbol, interval="1m", period="1d")
    if df.empty:
        return None
    return float(df["Close"].iloc[-1])


def fetch_all(stock_list: list[str], interval: str = CANDLE_INTERVAL,
              period: str = CANDLE_PERIOD) -> dict[str, pd.DataFrame]:
    """Fetch candles for a whole list of symbols. Sequential + safe."""
    data = {}
    for sym in stock_list:
        df = fetch_candles(sym, interval=interval, period=period)
        if not df.empty:
            data[sym] = df
    return data


def fetch_index_trend(index_symbol: str) -> str:
    """
    Very simple market trend check: is the index above or below
    today's opening price? Returns 'bullish', 'bearish', or 'flat'.
    """
    df = fetch_candles(index_symbol, interval="5m", period="1d")
    if df.empty or len(df) < 2:
        return "flat"
    open_price = df["Open"].iloc[0]
    last_price = df["Close"].iloc[-1]
    change_pct = (last_price - open_price) / open_price * 100
    if change_pct > 0.15:
        return "bullish"
    elif change_pct < -0.15:
        return "bearish"
    return "flat"


if __name__ == "__main__":
    # Quick manual test: run `python data_fetcher.py`
    df = fetch_candles("RELIANCE")
    print(df.tail())
    print("Index trend:", fetch_index_trend("^NSEI"))
