from datetime import datetime
import pandas as pd
import config
from data_fetcher import is_market_open, fetch_all, fetch_candles
from indicators import technical_score, trade_levels

def get_nifty_trend() -> int:
    """Evaluates broader market trend from NIFTY Index (^NSEI)."""
    try:
        df_nifty = fetch_candles(config.INDEX_SYMBOL, interval="5m", period="2d")
        if df_nifty.empty or len(df_nifty) < 20:
            return 0
        
        close = float(df_nifty["Close"].iloc[-1])
        ema50 = float(df_nifty["Close"].ewm(span=50, adjust=False).mean().iloc[-1])
        
        if close > ema50 * 1.001:
            return 1   # Bullish 🟢
        elif close < ema50 * 0.999:
            return -1  # Bearish 🔴
        return 0       # Neutral ⚪
    except Exception:
        return 0

def run_screener(ignore_market_hours=False):
    """Runs market-wide screening across configured stock list."""
    # Market Open Check (bypass supported for off-market testing)
    if not ignore_market_hours and not is_market_open():
        print("Market is currently CLOSED. No new live signals generated.")
        return pd.DataFrame()

    nifty_trend = get_nifty_trend()
    trend_str = "BULLISH 🟢" if nifty_trend == 1 else ("BEARISH 🔴" if nifty_trend == -1 else "NEUTRAL ⚪")
    print(f"🔍 NIFTY Trend Filter: {trend_str} | Scanning {len(config.STOCK_LIST)} stocks...")
    
    all_candles = fetch_all(config.STOCK_LIST)
    valid_calls = []

    for symbol, df in all_candles.items():
        if df.empty or len(df) < 20:
            continue

        tech = technical_score(df, nifty_trend=nifty_trend)
        score = tech.get("score", 0)
        direction = tech.get("direction", "NO_CALL")

        if score >= getattr(config, "CALL_THRESHOLD", 65.0) and direction != "NO_CALL":
            levels = trade_levels(df, direction=direction, risk_reward=getattr(config, "RISK_REWARD", 2.0))
            if levels.get("entry") and levels.get("target") and levels.get("stop_loss"):
                valid_calls.append({
                    "symbol": symbol.replace(".NS", ""),
                    "call": direction,
                    "entry": levels["entry"],
                    "target": levels["target"],
                    "stop_loss": levels["stop_loss"],
                    "confidence_score": score,
                    "strategy": tech.get("strategy", "SCREENER_DEFAULT"),
                    "issued_at": datetime.now().isoformat(),
                    "details": tech.get("breakdown", {})
                })

    df_results = pd.DataFrame(valid_calls)
    
    if not df_results.empty:
        # Highest Confidence Score Top Par Sort Hoga
        df_results = df_results.sort_values(
            by=["confidence_score"], 
            ascending=[False]
        ).reset_index(drop=True)

    print(f"✅ Scan Complete! Found {len(df_results)} signals sorted by Highest Confidence Score.")
    return df_results