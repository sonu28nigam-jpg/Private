"""
Automatic Trade Outcome Resolver & Root Cause Analyzer.
Runs continuously in background to check if target/SL hit.
"""
import time
import logging
from datetime import datetime
import trade_log
from data_fetcher import fetch_candles, is_market_open

logging.basicConfig(level=logging.INFO, format="%(asctime)s [RESOLVER] %(message)s")
logger = logging.getLogger("auto_resolver")

def diagnose_failure_simple(df, call_type: str, entry: float, sl: float) -> str:
    """Generates post-mortem diagnostics in simple Hinglish"""
    if df.empty or len(df) < 5:
        return "Market me sudden tez uthar-chadhaw (volatility) aa gayi thi."
    
    last_vol = df["Volume"].iloc[-1]
    avg_vol = df["Volume"].mean()
    last_close = df["Close"].iloc[-1]
    
    if last_vol < avg_vol * 0.5:
        return "Volume sudden kam ho gaya, matlab khareedne/bechne walo ka interest khatam ho gaya."
    elif call_type == "BUY" and last_close < entry:
        return "Upar ke level par heavy selling pressure aane se price niche gir gaya."
    elif call_type == "SHORT" and last_close > entry:
        return "Achanak se heavy buying aa gayi, jisse Stop-loss hit ho gaya."
    return "Pura Market (NIFTY) ulte direction me jane laga, jisse ye stock bhi kheencha chala gaya."

def resolve_open_trades():
    open_calls = trade_log.get_open_calls() if hasattr(trade_log, 'get_open_calls') else []
    if not open_calls:
        return

    logger.info(f"Checking outcomes for {len(open_calls)} open calls...")

    for call in open_calls:
        sym = call["symbol"]
        # period="5d" taaki kal/parso ki open calls bhi resolve ho sakein
        df = fetch_candles(sym, interval="5m", period="5d")
        if df.empty:
            continue

        highs = df["High"]
        lows = df["Low"]
        last_close = float(df["Close"].iloc[-1])

        call_type = call.get("call_type", call.get("call", "BUY"))
        entry = call["entry"]
        target = call["target"]
        sl = call["stop_loss"]

        hit_target = (call_type == "BUY" and (highs >= target).any()) or (call_type == "SHORT" and (lows <= target).any())
        hit_sl = (call_type == "BUY" and (lows <= sl).any()) or (call_type == "SHORT" and (highs >= sl).any())

        if hit_target:
            trade_log.record_outcome(call["id"], "HIT_TARGET", exit_price=target, root_cause="Sahi setup! Smoothly target touch ho gaya.")
            logger.info(f"🎯 {sym} HIT TARGET!")
        elif hit_sl:
            cause = diagnose_failure_simple(df, call_type, entry, sl)
            trade_log.record_outcome(call["id"], "HIT_SL", exit_price=sl, root_cause=cause)
            logger.info(f"🔴 {sym} HIT SL! Reason: {cause}")
        elif not is_market_open():
            cause = "Market time khatam ho gaya, Target ya SL tak price nahi pahunch paya."
            trade_log.record_outcome(call["id"], "SESSION_CLOSE", exit_price=last_close, root_cause=cause)

if __name__ == "__main__":
    logger.info("Auto Resolver Engine Started...")
    while True:
        try:
            resolve_open_trades()
            time.sleep(120)
        except Exception as e:
            logger.error(f"Resolver error: {e}")
            time.sleep(30)