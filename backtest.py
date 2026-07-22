import pandas as pd
from data_fetcher import fetch_candles
from indicators import technical_score, trade_levels
from config import STOCK_LIST, ATR_MULTIPLIER, RISK_REWARD, CALL_THRESHOLD

def simulate_trades(symbol, threshold=CALL_THRESHOLD, days=30):
    df = fetch_candles(symbol, interval="30m", period=f"{days}d")
    if df.empty or len(df) < 20: 
        return 0, 0
    
    wins, total = 0, 0
    for i in range(15, len(df) - 10):
        hist_data = df.iloc[:i+1]
        tech = technical_score(hist_data)
        call = tech["direction"] if tech["score"] >= threshold else "NO_CALL"
        
        if call != "NO_CALL":
            total += 1
            levels = trade_levels(hist_data, direction=call, atr_multiplier=ATR_MULTIPLIER, risk_reward=RISK_REWARD)
            future = df.iloc[i+1 : i+10]
            for _, candle in future.iterrows():
                if (call == "BUY" and candle['High'] >= levels['target']) or (call == "SHORT" and candle['Low'] <= levels['target']):
                    wins += 1
                    break
                if (call == "BUY" and candle['Low'] <= levels['stop_loss']) or (call == "SHORT" and candle['High'] >= levels['stop_loss']):
                    break
                    
    return wins, total

if __name__ == "__main__":
    print(f"🚀 Backtesting Strategy on Top Stocks at Threshold {CALL_THRESHOLD}...")
    for sym in STOCK_LIST[:5]:
        w, t = simulate_trades(sym, threshold=CALL_THRESHOLD)
        print(f"{sym}: {w}/{t} wins (Win Rate: {round(w/t*100, 1) if t>0 else 0}%)")