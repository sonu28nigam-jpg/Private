import sqlite3
import pandas as pd
from datetime import datetime

DB_NAME = "trade_log.db"

def init_learning_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_learnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            total_trades INTEGER,
            fakeout_sl_count INTEGER,
            win_rate_pct REAL,
            learned_insight TEXT,
            applied_sl_buffer REAL DEFAULT 1.0
        )
    """)
    conn.commit()
    conn.close()

def analyze_and_learn():
    """Analyzes closed trades to detect SL hunting/fakeouts and auto-adjust strategy parameters."""
    init_learning_db()
    conn = sqlite3.connect(DB_NAME)
    
    try:
        df = pd.read_sql_query("SELECT * FROM calls WHERE status != 'OPEN'", conn)
        if df.empty:
            conn.close()
            return {
                "insight": "Need at least 5 closed trades to start AI Learning loop.",
                "sl_buffer_multiplier": 1.0,
                "fakeouts": 0
            }
        
        # Detect Fakeouts (SL hit but max_after_exit reached Target)
        fakeouts = 0
        for _, row in df.iterrows():
            if row.get("status") == "HIT_SL":
                max_post = float(row.get("max_post_exit_price") or 0.0)
                target = float(row.get("target") or 0.0)
                call_type = row.get("call_type", "BUY")
                
                if call_type == "BUY" and max_post >= target:
                    fakeouts += 1
                elif call_type == "SHORT" and max_post > 0 and max_post <= target:
                    fakeouts += 1

        total = len(df)
        fakeout_rate = (fakeouts / total) * 100 if total > 0 else 0
        
        # Learning Rule & Parameter Adjustment
        sl_buffer = 1.0
        if fakeout_rate > 30:
            sl_buffer = 1.25  # Increase SL width by 25% to avoid noise
            insight = f"⚠️ High SL Hunting Detected ({fakeout_rate:.1f}% fakeouts)! AI expanded SL buffer by +25% to avoid noise."
        elif fakeout_rate > 15:
            sl_buffer = 1.10
            insight = f"🔍 Moderate Fakeouts ({fakeout_rate:.1f}%). AI added +10% SL padding buffer for market volatility."
        else:
            insight = f"✅ Strategy execution is optimal! Low SL hunt rate ({fakeout_rate:.1f}%)."

        # Save Daily Learning Snapshot
        cursor = conn.cursor()
        today_str = datetime.now().strftime("%Y-%m-%d")
        wins = len(df[df["status"] == "HIT_TARGET"])
        win_rate = (wins / total) * 100

        cursor.execute("""
            INSERT INTO ai_learnings (date, total_trades, fakeout_sl_count, win_rate_pct, learned_insight, applied_sl_buffer)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (today_str, total, fakeouts, win_rate, insight, sl_buffer))
        
        conn.commit()
        conn.close()
        
        return {
            "insight": insight,
            "sl_buffer_multiplier": sl_buffer,
            "fakeouts": fakeouts,
            "total": total
        }

    except Exception as e:
        conn.close()
        return {"insight": f"AI Learning system active. Error during analysis: {str(e)}", "sl_buffer_multiplier": 1.0, "fakeouts": 0}