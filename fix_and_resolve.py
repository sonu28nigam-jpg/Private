"""
Fixes database schema and auto-resolves past calls with simple Hinglish root causes.
"""
import sqlite3
import logging
from datetime import datetime
from config import TRADE_LOG_DB
from data_fetcher import fetch_candles

logging.basicConfig(level=logging.INFO, format="%(asctime)s [FIX_RESOLVER] %(message)s")
logger = logging.getLogger("fix_resolver")

def diagnose_failure_simple(df, call_type: str, entry: float, sl: float) -> str:
    if df.empty or len(df) < 5:
        return "Market me sudden tez uthar-chadhaw (volatility) aa gayi thi."
    
    last_vol = df["Volume"].iloc[-1]
    avg_vol = df["Volume"].mean()
    last_close = df["Close"].iloc[-1]
    
    if last_vol < avg_vol * 0.5:
        return "Volume sudden kam ho gaya, matlab momentum khatam ho gaya."
    elif call_type == "BUY" and last_close < entry:
        return "Upar ke level par heavy selling pressue aane se price niche gir gaya."
    elif call_type == "SHORT" and last_close > entry:
        return "Achanak se heavy buying aa gayi, jisse Stop-loss hit ho gaya."
    return "Pura Market (NIFTY) ulte direction me jane laga, jisse ye stock bhi kheench gaya."

def resolve_all_past_calls():
    conn = sqlite3.connect(TRADE_LOG_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM calls WHERE status='OPEN' OR status IS NULL OR root_cause=''").fetchall()
    
    logger.info(f"Found {len(rows)} calls to resolve/update...")
    
    for row in rows:
        call_id = row["id"]
        sym = row["symbol"]
        call_type = row["call_type"]
        entry = row["entry"]
        target = row["target"]
        sl = row["stop_loss"]
        
        if not entry or not target or not sl:
            continue

        df = fetch_candles(sym, interval="5m", period="1d")
        if df.empty:
            continue

        highs = df["High"]
        lows = df["Low"]
        last_close = float(df["Close"].iloc[-1])

        hit_target = (call_type == "BUY" and (highs >= target).any()) or (call_type == "SHORT" and (lows <= target).any())
        hit_sl = (call_type == "BUY" and (lows <= sl).any()) or (call_type == "SHORT" and (highs >= sl).any())

        status = "OPEN"
        exit_price = None
        points = 0.0
        target_miss = 0.0
        cause = ""

        if hit_target:
            status = "HIT_TARGET"
            exit_price = target
            points = round(target - entry if call_type == "BUY" else entry - target, 2)
            cause = "Sahi setup! Smoothly target touch ho gaya."
        elif hit_sl:
            status = "HIT_SL"
            exit_price = sl
            points = round(sl - entry if call_type == "BUY" else entry - sl, 2)
            cause = diagnose_failure_simple(df, call_type, entry, sl)
        else:
            status = "SESSION_CLOSE"
            exit_price = last_close
            points = round(last_close - entry if call_type == "BUY" else entry - last_close, 2)
            target_miss = round(last_close - target if call_type == "BUY" else target - last_close, 2)
            cause = "Market time khatam ho gaya, Target ya SL tak price nahi pahunch paya."

        conn.execute(
            """UPDATE calls SET status=?, exit_price=?, exit_at=?,
               points_captured=?, target_miss_by=?, root_cause=? WHERE id=?""",
            (status, exit_price, datetime.now().isoformat(), points, target_miss, cause, call_id)
        )

    conn.commit()
    conn.close()
    logger.info("✅ All calls updated with simple Hinglish causes!")

if __name__ == "__main__":
    resolve_all_past_calls()