"""
Central configuration for the Intraday Screener.
Edit STOCK_LIST, WEIGHTS, and BROKER settings here.
"""

# ---------------------------------------------------------------
# Stock universe (NSE symbols, yfinance format uses ".NS" suffix)
# Replace/extend this list with your own 100 stocks.
# ---------------------------------------------------------------
STOCK_LIST = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", "LT",
    "AXISBANK", "HINDUNILVR", "BAJFINANCE", "MARUTI", "SUNPHARMA",
    "TITAN", "ULTRACEMCO", "ASIANPAINT", "NESTLEIND", "WIPRO",
    "ADANIENT", "ADANIPORTS", "TATASTEEL", "TATAMOTORS", "ONGC",
    "NTPC", "POWERGRID", "COALINDIA", "JSWSTEEL", "HCLTECH",
]

# NIFTY 50 index symbol (used for the market-trend filter)
INDEX_SYMBOL = "^NSEI"

# ---------------------------------------------------------------
# Scoring weights (must sum to 1.0)
# ---------------------------------------------------------------
TECH_WEIGHT = 0.60
NEWS_WEIGHT = 0.40

# Technical sub-score weights (points out of 100, tunable)
TECH_POINTS = {
    "vwap": 30,
    "rsi": 20,
    "volume_spike": 30,
    "ema_cross": 20,
}

# Data refresh interval (seconds) — used by the dashboard auto-refresh
REFRESH_INTERVAL_SEC = 300  # 5 minutes

# ---------------------------------------------------------------
# Trade level (Entry / Stop-Loss / Target) settings
# ---------------------------------------------------------------
# Stop-loss distance = ATR * ATR_MULTIPLIER (bigger = wider stop,
# fewer stop-outs but bigger loss per trade if wrong).
ATR_MULTIPLIER = 1.5

# Target distance = risk * RISK_REWARD (e.g. 2.0 means target is
# twice as far as the stop-loss — a 1:2 risk-reward setup).
RISK_REWARD = 2.0

# A stock only gets a BUY call if final_score >= this.
# A stock only gets a SHORT call if final_score <= (100 - this).
# Anything in between gets no call — final_score too weak either way.
CALL_THRESHOLD = 65

# ---------------------------------------------------------------
# Trade log / feedback loop settings
# ---------------------------------------------------------------
TRADE_LOG_DB = "trade_log.db"

# Don't log the same (symbol, call_type) again if it was already
# logged as OPEN within this many minutes — avoids duplicate rows
# when you re-run the screener frequently.
CALL_DEDUP_MINUTES = 20

# How often the dashboard auto-generates a fresh set of calls
# while it's open in your browser (used with streamlit-autorefresh).
AUTO_REFRESH_MINUTES = 15

# Candle interval for intraday indicator calculation
CANDLE_INTERVAL = "5m"
CANDLE_PERIOD = "5d"   # how much historical data to pull for indicator calc

# NSE market hours (IST). Used to detect "market closed" so the app
# doesn't generate live-looking calls off stale end-of-day data.
MARKET_OPEN = "09:15:00"
MARKET_CLOSE = "15:30:00"

# ---------------------------------------------------------------
# Broker deep-link settings
# ---------------------------------------------------------------
# Zerodha Kite Connect basket link needs YOUR api_key from
# https://developers.kite.trade (paid, ~Rs 500/month subscription).
# Leave blank to fall back to a plain "search stock on Kite" link.
KITE_API_KEY = ""   # <-- put your Kite Connect api_key here if you have one

DEFAULT_ORDER_QTY = 1
DEFAULT_PRODUCT = "MIS"   # MIS = Intraday, CNC = Delivery
