import yfinance as yf
import pandas as pd
import numpy as np
import config

def classify_strategy_basis(details, action):
    """
    🤖 AUTO-DETECTS the basis for this call using the SAME detail flags
    calculate_technical_score() already computed — no manual tagging needed.
    """
    vwap_matches = (action == "BUY" and details.get("vwap") == "ABOVE") or \
                   (action == "SELL" and details.get("vwap") == "BELOW")
    if vwap_matches and details.get("volume") == "HIGH":
        return "BREAKOUT"
    if details.get("ema") == "BULLISH" and action == "BUY":
        return "MOMENTUM"
    return "SCREENER_DEFAULT"


def calculate_technical_score(df):
    """Calculates technical score safely without throwing NaN errors."""
    if df is None or len(df) < 15:
        return 0, {}

    score = 0
    details = {}
    
    try:
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 1. VWAP Check (Safe calculation)
        close_price = latest['Close']
        vwap_val = latest.get('VWAP', close_price)
        if close_price > vwap_val:
            score += config.TECH_POINTS.get('vwap', 25)
            details['vwap'] = "ABOVE"
        else:
            details['vwap'] = "BELOW"

        # 2. RSI Check (Between 45 and 70 for bullish momentum)
        rsi_val = latest.get('RSI', 50)
        if pd.notna(rsi_val) and rsi_val > 50:
            score += config.TECH_POINTS.get('rsi', 20)
            details['rsi'] = f"{rsi_val:.1f}"

        # 3. Volume Check (Relative to 10-period average)
        avg_vol = df['Volume'].tail(10).mean()
        if avg_vol > 0 and latest['Volume'] > avg_vol:
            score += config.TECH_POINTS.get('volume_spike', 25)
            details['volume'] = "HIGH"

        # 4. EMA Cross / Trend Alignment Check
        ema_short = latest.get('EMA_9', close_price)
        ema_long = latest.get('EMA_21', close_price)
        if pd.notna(ema_short) and pd.notna(ema_long) and ema_short > ema_long:
            score += config.TECH_POINTS.get('ema_cross', 15)
            details['ema'] = "BULLISH"

    except Exception as e:
        print(f"Error in technical calculation: {e}")
        return 0, {}

    return score, details

def scan_single_stock(ticker):
    """Fetches data and evaluates score against config threshold."""
    try:
        data = yf.Ticker(ticker).history(period=config.CANDLE_PERIOD, interval=config.CANDLE_INTERVAL)
        if data.empty or len(data) < 15:
            return None

        # Calculate Basic Indicators
        data['VWAP'] = (data['Volume'] * (data['High'] + data['Low'] + data['Close']) / 3).cumsum() / data['Volume'].cumsum()
        
        # Simple RSI Calculation
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        data['RSI'] = 100 - (100 / (1 + rs))

        # EMAs
        data['EMA_9'] = data['Close'].ewm(span=9, adjust=False).mean()
        data['EMA_21'] = data['Close'].ewm(span=21, adjust=False).mean()

        # Calculate Scores
        tech_score, details = calculate_technical_score(data)
        
        # Combined Final Weighted Score
        total_score = tech_score  # Fallback to pure technical if news module is off
        
        # Dynamic Threshold Match Check
        if total_score >= config.CALL_THRESHOLD:
            latest_price = float(data['Close'].iloc[-1])
            action = "BUY" if details.get('vwap') == "ABOVE" else "SELL"
            return {
                "symbol": ticker.replace(".NS", ""),
                "price": round(latest_price, 2),
                "score": int(total_score),
                "action": action,
                "strategy": classify_strategy_basis(details, action),
                "details": details
            }
    except Exception as e:
        print(f"Failed to scan {ticker}: {e}")
        return None

    return None

def run_screener_universe():
    """Runs scanning over the entire STOCK_LIST defined in config."""
    valid_calls = []
    print(f"🔍 Starting Screener Scan for {len(config.STOCK_LIST)} stocks at Threshold {config.CALL_THRESHOLD}...")
    
    for ticker in config.STOCK_LIST:
        res = scan_single_stock(ticker)
        if res:
            valid_calls.append(res)
            
    print(f"✅ Scan Complete! Found {len(valid_calls)} setup signals.")
    return valid_calls