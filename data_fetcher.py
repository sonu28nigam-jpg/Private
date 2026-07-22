import logging
import time
from datetime import datetime, time as dtime
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import yfinance as yf
from config import CANDLE_INTERVAL, CANDLE_PERIOD, MARKET_OPEN, MARKET_CLOSE

try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except ImportError:
    IST = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data_fetcher")

def is_market_open(now: datetime = None) -> bool:
    """Checks if Indian Equity Market (NSE) is currently open using IST timezone."""
    now = now or (datetime.now(IST) if IST else datetime.now())
    if now.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        return False
    open_t = dtime.fromisoformat(MARKET_OPEN)
    close_t = dtime.fromisoformat(MARKET_CLOSE)
    return open_t <= now.time() <= close_t

def to_yf_symbol(symbol: str) -> str:
    if symbol.startswith("^") or symbol.endswith(".NS"):
        return symbol
    return f"{symbol}.NS"

def fetch_candles(symbol: str, interval: str = CANDLE_INTERVAL, period: str = CANDLE_PERIOD) -> pd.DataFrame:
    yf_symbol = to_yf_symbol(symbol)
    try:
        df = yf.Ticker(yf_symbol).history(period=period, interval=interval)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(columns=str.title)
        return df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    except Exception as e:
        logger.warning(f"Failed to fetch {symbol}: {e}")
        return pd.DataFrame()

def fetch_all(stock_list: list[str], interval: str = CANDLE_INTERVAL, period: str = CANDLE_PERIOD, max_workers: int = 10) -> dict[str, pd.DataFrame]:
    """Parallel multi-threaded stock candle fetcher for speed optimization."""
    data = {}
    def worker(sym):
        df = fetch_candles(sym, interval=interval, period=period)
        if not df.empty:
            return sym, df
        return sym, None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = executor.map(worker, stock_list)
        for sym, df in results:
            if df is not None:
                data[sym] = df
    return data