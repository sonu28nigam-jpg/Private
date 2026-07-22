"""
Central configuration for the Intraday Screener.
Updated: Lowered CALL_THRESHOLD to 25 for generating active high-probability signals.
"""

# Yahoo Finance compliant tickers with .NS suffix (Duplicates removed)
STOCK_LIST = [
    # Top Financials & Banks
    "HDFCBANK.NS", "KOTAKBANK.NS", "AXISBANK.NS", "SBIN.NS", 
    "INDUSINDBK.NS", "BANKBARODA.NS", "PNB.NS", "CANBK.NS", "IDFCFIRSTB.NS",
    "BAJFINANCE.NS", "MUTHOOTFIN.NS", "PFC.NS", 
    "RECLTD.NS", "SHRIRAMFIN.NS", "JIOFIN.NS", "HDFCLIFE.NS",

    # IT & Technology
    "TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS", 
    "LTIM.NS",  "NAUKRI.NS",

    # Energy, Utilities & Oil
     "ONGC.NS", "BPCL.NS", "IOC.NS", "GAIL.NS",
    "NTPC.NS", "POWERGRID.NS", "TATAPOWER.NS", "ADANIPOWER.NS", "COALINDIA.NS",

    # Automobiles & Auto Components
    "TATAMOTORS.NS", "M&M.NS", "MARUTI.NS", "BAJAJ-AUTO.NS", "HEROMOTOCO.NS", 
     "TVSMOTOR.NS", "BHARATFORG.NS", "ASHOKLEY.NS",

    # Metals & Mining
    "TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS", "JINDALSTEL.NS", "VEDL.NS",

    # Consumer Goods & Retail (FMCG)
    "HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS", "TATACONSUM.NS", 
    "DABUR.NS", "GODREJCP.NS",  "ZOMATO.NS", "ASIANPAINT.NS", "TITAN.NS",

    # Pharma & Healthcare
    "SUNPHARMA.NS", "CIPLA.NS", "DRREDDY.NS", "DIVISLAB.NS", "APOLLOHOSP.NS", "LUPIN.NS",

    # Infrastructure & Capital Goods
    "LT.NS", "HAL.NS", "BEL.NS", "BHEL.NS", "ABB.NS",

    # Telecom & Durables
    "BHARTIARTL.NS", "POLYCAB.NS", "HAVELLS.NS",
    "BALRAMCHIN.NS", "BANDHANBANK.NS", "BELRISE.NS",
    "BLS.NS", "CANBK.NS", "CASTROLIND.NS", "CGCL.NS", "CHAMBLFERT.NS",
    "CROMPTON.NS", "ETERNAL.NS", "FEDERALBNK.NS", "GODIGIT.NS",
    "GSFC.NS", "HBLPOWER.NS", "HONASA.NS", "HUHTAMAKI.NS", "IDEA.NS",
    "IIFL.NS", "INDUSTOWER.NS", "IOC.NS", "IOLCP.NS", "IRB.NS", 
    "IRCON.NS", "IREDA.NS", "IRFC.NS", "JAIBALAJI.NS", "JAYNECOIND.NS",
    "JWL.NS", "KARURVYSYA.NS", "KERNEX.NS", "LTF.NS", "MONARCH.NS",
    "NATIONALUM.NS", "NHPC.NS", "PFC.NS",
    "RALLIS.NS", "RAMRAT.NS", "RVNL.NS", "SAIL.NS", "SCI.NS",
    "SOLARA.NS", "SUMICHEM.NS", "SUPRIYA.NS", "TRIVENI.NS", "UNIONBANK.NS",
    "VEDL.NS", "EXIDEIND.NS", "AMARAJABAT.NS", "BALKRISIND.NS", "BATAINDIA.NS",
    "NMDC.NS", "GMRINFRA.NS", "ADANIGREEN.NS", "ADANITRANS.NS",
      "ADANIPORTS.NS", "ADANIGAS.NS", "ADANIENT.NS", "BIOCON.NS", "PETRONET.NS", "ABCAPITAL.NS", "MANAPPURAM.NS",
      "HINDPETRO.NS", "AMBUJACEM.NS", "UPL.NS", "IGL.NS", "GUJGASLTD.NS", "APOLLOTYRE.NS", "LAURUSLABS.NS",
      "AARTIIND.NS", ""
]
INDEX_SYMBOL = "^NSEI"



# Scoring weights & Points
TECH_POINTS = {
    "vwap": 25,
    "rsi": 20,
    "volume_spike": 25,
    "ema_cross": 15,
    "trend_alignment": 15
}

REFRESH_INTERVAL_SEC = 60
ATR_MULTIPLIER = 1.5
RISK_REWARD = 2.0

# Dynamic CALL_THRESHOLD (Lowered to 25 so active signals generate smoothly)
CALL_THRESHOLD = 70

TRADE_LOG_DB = "trade_log.db"

# Candle Settings
CANDLE_INTERVAL = "5m"
CANDLE_PERIOD = "5d"

MARKET_OPEN = "09:15:00"
MARKET_CLOSE = "15:30:00"