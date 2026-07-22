"""
trade_log.py — AI Pro Intraday Terminal trade journal / DB layer.

CHANGELOG (advanced upgrade):
  [Reliability]
    - All connections now go through a context manager (get_connection) that
      enables WAL mode, commits/rolls back automatically, and always closes —
      fixes silent 'except: pass' failures and reduces DB-lock risk when
      Streamlit has multiple concurrent sessions.
    - Real logging (via `logging` module) instead of silently swallowed errors.

  [Schema / Data]
    - New columns: strategy, risk_amount, risk_per_trade_pct, slippage.
    - Indexes added on status, symbol, issued_at, strategy for faster queries
      as the table grows.

  [Analytics / Reporting]
    - performance_summary() extended with expectancy, profit_factor, avg_win,
      avg_loss, best_trade, worst_trade (old keys kept for compatibility).
    - equity_curve(), drawdown_stats(), strategy_performance(),
      time_of_day_performance() — new functions for deeper reporting.
    - export_backup_csv() for simple manual/automatic backups.

  [AI / Risk Management]
    - calculate_quantity_by_risk() — risk-based position sizing (fixed ₹ risk
      per trade instead of fixed capital per trade).
    - check_daily_loss_limit() — circuit breaker helper for the dashboard.
    - get_adaptive_confidence_threshold() — suggests a raised/lowered minimum
      confidence score based on how recent trades actually performed, meant
      to feed into ai_learner.py / the screener.

Everything that existed before still works exactly the same way — this is a
drop-in replacement.
"""

import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime
import pandas as pd

DB_NAME = "trade_log.db"

# ---------------------------------------------------------------------------
# Logging setup — replaces the old silent `except Exception: pass` pattern
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] trade_log: %(message)s"
)
logger = logging.getLogger("trade_log")


# ---------------------------------------------------------------------------
# Connection management (NEW): WAL mode + guaranteed commit/rollback/close
# ---------------------------------------------------------------------------
@contextmanager
def get_connection():
    """Every DB call now goes through this so a crash mid-write can't leave
    a connection open, and concurrent Streamlit sessions don't lock the DB."""
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
def init_db():
    """Database initialization and dynamic table schema setup."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                call_type TEXT,
                entry REAL,
                target REAL,
                stop_loss REAL,
                win_probability REAL,
                final_score REAL,
                confidence_score REAL,
                allocated_amount REAL,
                quantity INTEGER,
                issued_at TEXT,
                status TEXT DEFAULT 'OPEN',
                exit_price REAL,
                exit_at TEXT,
                pnl REAL DEFAULT 0.0,
                pnl_pct REAL DEFAULT 0.0,
                root_cause TEXT,
                is_paper INTEGER DEFAULT 1,
                max_post_exit_price REAL DEFAULT 0.0,
                min_post_exit_price REAL DEFAULT 0.0,
                post_exit_status TEXT DEFAULT 'MONITORING'
            )
        """)

        cursor.execute("PRAGMA table_info(calls)")
        existing_cols = [row[1] for row in cursor.fetchall()]

        required_cols = {
            "confidence_score": "REAL",
            "quantity": "INTEGER DEFAULT 1",
            "pnl": "REAL DEFAULT 0.0",
            "pnl_pct": "REAL DEFAULT 0.0",
            "allocated_amount": "REAL DEFAULT 50000",
            "root_cause": "TEXT",
            "is_paper": "INTEGER DEFAULT 1",
            "max_post_exit_price": "REAL DEFAULT 0.0",
            "min_post_exit_price": "REAL DEFAULT 0.0",
            "post_exit_status": "TEXT DEFAULT 'MONITORING'",
            # NEW columns
            "strategy": "TEXT DEFAULT 'UNTAGGED'",
            "risk_amount": "REAL DEFAULT 0.0",
            "risk_per_trade_pct": "REAL DEFAULT 0.0",
            "slippage": "REAL DEFAULT 0.0",
        }

        for col_name, col_type in required_cols.items():
            if col_name not in existing_cols:
                try:
                    cursor.execute(f"ALTER TABLE calls ADD COLUMN {col_name} {col_type}")
                    logger.info(f"Added missing column '{col_name}' to calls table.")
                except Exception as e:
                    logger.warning(f"Could not add column '{col_name}': {e}")

        # NEW: indexes so lookups stay fast as history grows
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status)",
            "CREATE INDEX IF NOT EXISTS idx_calls_symbol ON calls(symbol)",
            "CREATE INDEX IF NOT EXISTS idx_calls_issued_at ON calls(issued_at)",
            "CREATE INDEX IF NOT EXISTS idx_calls_strategy ON calls(strategy)",
        ]:
            cursor.execute(idx_sql)


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------
def log_call(call_data, allocated_amount=50000.0, is_paper=1, strategy=None, risk_amount=None):
    """
    Log a new trading call into the database.

    Sizing modes:
      - Default (unchanged): quantity = allocated_amount / entry_price
      - Risk-based (NEW): pass risk_amount (₹ you're willing to lose on this
        trade). Quantity is derived from the entry/stop-loss distance instead,
        so every trade risks the same rupee amount no matter how wide the SL is.
    """
    init_db()
    entry_price = float(call_data.get("entry", 1.0))
    if entry_price <= 0:
        entry_price = 1.0

    stop_loss = call_data.get("stop_loss")
    computed_risk_amount = 0.0
    risk_per_trade_pct = 0.0

    if risk_amount is not None and stop_loss is not None:
        risk_per_share = abs(entry_price - float(stop_loss))
        if risk_per_share > 0:
            quantity = max(1, int(float(risk_amount) / risk_per_share))
            computed_risk_amount = round(risk_per_share * quantity, 2)
        else:
            quantity = max(1, int(float(allocated_amount) / entry_price))
    else:
        quantity = max(1, int(float(allocated_amount) / entry_price))
        if stop_loss is not None:
            risk_per_share = abs(entry_price - float(stop_loss))
            computed_risk_amount = round(risk_per_share * quantity, 2)

    if allocated_amount and allocated_amount > 0:
        risk_per_trade_pct = round((computed_risk_amount / allocated_amount) * 100, 2)

    issued_at = call_data.get("issued_at", datetime.now().isoformat())
    score = call_data.get("confidence_score", call_data.get("final_score", 0))
    strategy_tag = strategy or call_data.get("strategy", "UNTAGGED")

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO calls
            (symbol, call_type, entry, target, stop_loss, confidence_score, allocated_amount,
             quantity, issued_at, status, is_paper, strategy, risk_amount, risk_per_trade_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?)
        """, (
            call_data.get("symbol"),
            call_data.get("call", call_data.get("call_type", "BUY")),
            entry_price,
            call_data.get("target"),
            stop_loss,
            score,
            allocated_amount,
            quantity,
            issued_at,
            is_paper,
            strategy_tag,
            computed_risk_amount,
            risk_per_trade_pct,
        ))
    logger.info(f"Logged call: {call_data.get('symbol')} qty={quantity} strategy={strategy_tag}")


def update_stop_loss(call_id, new_sl):
    """🤖 AI Auto-Trailing SL function to dynamically update Stop Loss in DB."""
    init_db()
    with get_connection() as conn:
        conn.execute("UPDATE calls SET stop_loss=? WHERE id=?", (round(new_sl, 2), call_id))


def delete_call(call_id):
    """Delete a single call by ID."""
    init_db()
    with get_connection() as conn:
        conn.execute("DELETE FROM calls WHERE id=?", (call_id,))
    logger.info(f"Deleted call #{call_id}")


def delete_all_calls(scope="OPEN"):
    """Delete calls based on scope: OPEN, CLOSED, or ALL."""
    init_db()
    with get_connection() as conn:
        if scope == "OPEN":
            conn.execute("DELETE FROM calls WHERE status='OPEN'")
        elif scope == "CLOSED":
            conn.execute("DELETE FROM calls WHERE status!='OPEN'")
        elif scope == "ALL":
            conn.execute("DELETE FROM calls")
    logger.info(f"Deleted calls (scope={scope})")


def update_call_amount(call_id, new_amount, entry):
    """Update allocated capital and re-calculate quantity."""
    init_db()
    new_qty = max(1, int(float(new_amount) / float(entry)))
    with get_connection() as conn:
        conn.execute(
            "UPDATE calls SET allocated_amount=?, quantity=? WHERE id=?",
            (new_amount, new_qty, call_id)
        )


def update_post_exit_tracking(call_id, max_p, min_p, post_status, new_pnl=None, new_pnl_pct=None):
    """Update post-exit analysis data for fakeout detection."""
    init_db()
    with get_connection() as conn:
        if new_pnl is not None and new_pnl_pct is not None:
            conn.execute("""
                UPDATE calls
                SET max_post_exit_price=?, min_post_exit_price=?, post_exit_status=?, pnl=?, pnl_pct=?
                WHERE id=?
            """, (max_p, min_p, post_status, new_pnl, new_pnl_pct, call_id))
        else:
            conn.execute("""
                UPDATE calls
                SET max_post_exit_price=?, min_post_exit_price=?, post_exit_status=?
                WHERE id=?
            """, (max_p, min_p, post_status, call_id))


def record_outcome(call_id, status, exit_price, root_cause="", pnl=0.0, pnl_pct=0.0):
    """Record final status and outcome when a trade is closed."""
    init_db()
    with get_connection() as conn:
        conn.execute("""
            UPDATE calls
            SET status=?, exit_price=?, exit_at=?, root_cause=?, pnl=?, pnl_pct=?,
                max_post_exit_price=?, min_post_exit_price=?
            WHERE id=?
        """, (status, exit_price, datetime.now().isoformat(), root_cause,
              round(pnl, 2), round(pnl_pct, 2), exit_price, exit_price, call_id))
    logger.info(f"Closed call #{call_id} -> {status} @ ₹{exit_price} (PnL ₹{round(pnl, 2)})")


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------
def get_open_calls():
    """Fetch all open trades."""
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM calls WHERE status='OPEN' ORDER BY id DESC").fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"get_open_calls failed: {e}")
            return []


def get_closed_calls():
    """Fetch all closed trades."""
    init_db()
    with get_connection() as conn:
        try:
            df = pd.read_sql_query("SELECT * FROM calls WHERE status != 'OPEN' ORDER BY id DESC", conn)
            return df.to_dict(orient="records")
        except Exception as e:
            logger.warning(f"get_closed_calls failed: {e}")
            return []


def get_all_calls():
    """Fetch all trades regardless of status."""
    init_db()
    with get_connection() as conn:
        try:
            df = pd.read_sql_query("SELECT * FROM calls ORDER BY id DESC", conn)
            return df.to_dict(orient="records")
        except Exception as e:
            logger.warning(f"get_all_calls failed: {e}")
            return []


def get_calls_by_date(target_date):
    """Fetch all trades for a specific single date (Format: 'YYYY-MM-DD')."""
    init_db()
    with get_connection() as conn:
        try:
            df = pd.read_sql_query(
                "SELECT * FROM calls WHERE DATE(issued_at) = ? ORDER BY id DESC",
                conn, params=(str(target_date),)
            )
            return df.to_dict(orient="records")
        except Exception as e:
            logger.warning(f"get_calls_by_date failed: {e}")
            return []


def get_calls_by_date_range(start_date, end_date):
    """Fetch all trades within a date range (Format: 'YYYY-MM-DD')."""
    init_db()
    with get_connection() as conn:
        try:
            df = pd.read_sql_query(
                "SELECT * FROM calls WHERE DATE(issued_at) BETWEEN ? AND ? ORDER BY id DESC",
                conn, params=(str(start_date), str(end_date))
            )
            return df.to_dict(orient="records")
        except Exception as e:
            logger.warning(f"get_calls_by_date_range failed: {e}")
            return []


# ---------------------------------------------------------------------------
# Performance summary (extended, backward-compatible)
# ---------------------------------------------------------------------------
def performance_summary(start_date=None, end_date=None):
    """
    Calculate overall performance metrics with optional date range filter.
    All original keys are unchanged. NEW keys added:
    expectancy, profit_factor, avg_win, avg_loss, best_trade, worst_trade.
    """
    init_db()
    where = "WHERE status != 'OPEN'"
    params = []
    if start_date and end_date:
        where += " AND DATE(issued_at) BETWEEN ? AND ?"
        params = [str(start_date), str(end_date)]
    elif start_date:
        where += " AND DATE(issued_at) = ?"
        params = [str(start_date)]

    with get_connection() as conn:
        try:
            df = pd.read_sql_query(f"SELECT pnl, root_cause FROM calls {where}", conn, params=params)
        except Exception as e:
            logger.warning(f"performance_summary failed: {e}")
            df = pd.DataFrame(columns=["pnl", "root_cause"])

    empty_result = {
        "total_closed": 0, "wins": 0, "win_rate_pct": 0.0,
        "total_profit": 0.0, "total_loss": 0.0, "net_pnl": 0.0,
        "root_causes": [], "expectancy": 0.0, "profit_factor": None,
        "avg_win": 0.0, "avg_loss": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
    }
    if df.empty:
        return empty_result

    total_closed = len(df)
    wins_df = df[df["pnl"] > 0]
    losses_df = df[df["pnl"] < 0]
    wins = len(wins_df)
    win_rate = round((wins / total_closed) * 100, 2) if total_closed else 0.0

    total_profit = round(wins_df["pnl"].sum(), 2) if not wins_df.empty else 0.0
    total_loss = round(losses_df["pnl"].sum(), 2) if not losses_df.empty else 0.0
    net_pnl = round(total_profit + total_loss, 2)

    avg_win = round(wins_df["pnl"].mean(), 2) if not wins_df.empty else 0.0
    avg_loss = round(abs(losses_df["pnl"].mean()), 2) if not losses_df.empty else 0.0
    expectancy = round((win_rate / 100 * avg_win) - ((1 - win_rate / 100) * avg_loss), 2)
    profit_factor = round(total_profit / abs(total_loss), 2) if total_loss != 0 else None

    causes = [c for c in df["root_cause"].tolist() if c]

    return {
        "total_closed": total_closed,
        "wins": wins,
        "win_rate_pct": win_rate,
        "total_profit": total_profit,
        "total_loss": total_loss,
        "net_pnl": net_pnl,
        "root_causes": causes,
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "best_trade": round(df["pnl"].max(), 2),
        "worst_trade": round(df["pnl"].min(), 2),
    }


# ---------------------------------------------------------------------------
# NEW: Analytics / Reporting
# ---------------------------------------------------------------------------
def equity_curve(start_date=None, end_date=None):
    """Cumulative realized PnL over time — feed directly into a line chart."""
    where = "WHERE status != 'OPEN' AND exit_at IS NOT NULL"
    params = []
    if start_date and end_date:
        where += " AND DATE(exit_at) BETWEEN ? AND ?"
        params = [str(start_date), str(end_date)]
    elif start_date:
        where += " AND DATE(exit_at) = ?"
        params = [str(start_date)]

    with get_connection() as conn:
        try:
            df = pd.read_sql_query(
                f"SELECT exit_at, pnl FROM calls {where} ORDER BY exit_at ASC",
                conn, params=params
            )
        except Exception as e:
            logger.warning(f"equity_curve failed: {e}")
            return []

    if df.empty:
        return []

    df["cumulative_pnl"] = df["pnl"].cumsum().round(2)
    return df[["exit_at", "pnl", "cumulative_pnl"]].to_dict(orient="records")


def drawdown_stats(start_date=None, end_date=None):
    """Max drawdown (₹ and %) computed off the equity curve."""
    curve = equity_curve(start_date, end_date)
    if not curve:
        return {"max_drawdown": 0.0, "max_drawdown_pct": 0.0, "peak_equity": 0.0}

    running_peak = float("-inf")
    max_dd = 0.0
    peak_at_max_dd = 0.0
    for point in curve:
        eq = point["cumulative_pnl"]
        running_peak = max(running_peak, eq)
        dd = running_peak - eq
        if dd > max_dd:
            max_dd = dd
            peak_at_max_dd = running_peak

    max_dd_pct = round((max_dd / peak_at_max_dd) * 100, 2) if peak_at_max_dd > 0 else 0.0
    return {
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": max_dd_pct,
        "peak_equity": round(peak_at_max_dd, 2),
    }


def strategy_performance():
    """Win-rate / expectancy broken down by strategy tag."""
    with get_connection() as conn:
        try:
            df = pd.read_sql_query("SELECT strategy, pnl FROM calls WHERE status != 'OPEN'", conn)
        except Exception as e:
            logger.warning(f"strategy_performance failed: {e}")
            return []

    if df.empty:
        return []

    df["strategy"] = df["strategy"].fillna("UNTAGGED").replace("", "UNTAGGED")
    results = []
    for strat, group in df.groupby("strategy"):
        total = len(group)
        wins_df = group[group["pnl"] > 0]
        losses_df = group[group["pnl"] < 0]
        wins = len(wins_df)
        win_rate = round((wins / total) * 100, 2) if total else 0.0
        avg_win = round(wins_df["pnl"].mean(), 2) if not wins_df.empty else 0.0
        avg_loss = round(abs(losses_df["pnl"].mean()), 2) if not losses_df.empty else 0.0
        expectancy = round((win_rate / 100 * avg_win) - ((1 - win_rate / 100) * avg_loss), 2)
        results.append({
            "strategy": strat,
            "total_trades": total,
            "win_rate_pct": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "expectancy": expectancy,
            "net_pnl": round(group["pnl"].sum(), 2),
        })
    return sorted(results, key=lambda x: x["net_pnl"], reverse=True)


def time_of_day_performance():
    """Win-rate and net PnL bucketed by the hour a call was issued — helps
    spot which part of the trading day actually works for you."""
    with get_connection() as conn:
        try:
            df = pd.read_sql_query("SELECT issued_at, pnl FROM calls WHERE status != 'OPEN'", conn)
        except Exception as e:
            logger.warning(f"time_of_day_performance failed: {e}")
            return []

    if df.empty:
        return []

    def safe_hour(x):
        try:
            return datetime.fromisoformat(str(x)).hour
        except Exception:
            return None

    df["hour"] = df["issued_at"].apply(safe_hour)
    df = df.dropna(subset=["hour"])
    if df.empty:
        return []

    results = []
    for hour, group in df.groupby("hour"):
        total = len(group)
        wins = (group["pnl"] > 0).sum()
        win_rate = round((wins / total) * 100, 2) if total else 0.0
        results.append({
            "hour": int(hour),
            "total_trades": total,
            "win_rate_pct": win_rate,
            "net_pnl": round(group["pnl"].sum(), 2),
        })
    return sorted(results, key=lambda x: x["hour"])


def export_backup_csv(path=None):
    """Dump the full calls table to CSV — simple manual/automatic backup."""
    path = path or f"trade_log_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with get_connection() as conn:
        try:
            df = pd.read_sql_query("SELECT * FROM calls", conn)
            df.to_csv(path, index=False)
            logger.info(f"Backup exported to {path} ({len(df)} rows).")
            return path
        except Exception as e:
            logger.error(f"Backup export failed: {e}")
            return None


# ---------------------------------------------------------------------------
# NEW: AI / Risk management helpers
# ---------------------------------------------------------------------------
def calculate_quantity_by_risk(capital_risk_amount, entry, stop_loss):
    """Risk-based position sizing — same ₹ risk on every trade regardless of
    how wide the stop-loss is. Use this in the dashboard before calling
    log_call(..., risk_amount=capital_risk_amount)."""
    risk_per_share = abs(float(entry) - float(stop_loss))
    if risk_per_share <= 0:
        return 1
    return max(1, int(float(capital_risk_amount) / risk_per_share))


def check_daily_loss_limit(max_loss_amount, target_date=None):
    """Circuit-breaker helper. Call before logging a new trade to check
    whether today's realized losses have already breached your configured
    max daily loss. Returns {can_trade, current_pnl, limit}."""
    target_date = target_date or datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        try:
            df = pd.read_sql_query(
                "SELECT pnl FROM calls WHERE status != 'OPEN' AND DATE(exit_at) = ?",
                conn, params=(str(target_date),)
            )
        except Exception as e:
            logger.warning(f"check_daily_loss_limit failed: {e}")
            return {"can_trade": True, "current_pnl": 0.0, "limit": -abs(max_loss_amount)}

    current_pnl = round(df["pnl"].sum(), 2) if not df.empty else 0.0
    limit = -abs(max_loss_amount)
    return {"can_trade": current_pnl > limit, "current_pnl": current_pnl, "limit": limit}


def get_adaptive_confidence_threshold(lookback=20, base_threshold=70.0):
    """
    Suggests an adjusted minimum confidence-score threshold based on how the
    most recent `lookback` closed trades actually performed. If recent win
    rate is weak, the bar is raised (be more selective); if it's strong, it's
    eased slightly. Meant to be consumed by ai_learner.py / the screener to
    filter new signals — plug the 'suggested_threshold' into your scan filter.
    """
    with get_connection() as conn:
        try:
            df = pd.read_sql_query(
                "SELECT confidence_score, pnl FROM calls WHERE status != 'OPEN' "
                "ORDER BY id DESC LIMIT ?", conn, params=(lookback,)
            )
        except Exception as e:
            logger.warning(f"get_adaptive_confidence_threshold failed: {e}")
            return {"suggested_threshold": base_threshold, "recent_win_rate": None, "sample_size": 0}

    if df.empty:
        return {"suggested_threshold": base_threshold, "recent_win_rate": None, "sample_size": 0}

    total = len(df)
    wins = int((df["pnl"] > 0).sum())
    win_rate = round((wins / total) * 100, 2)

    if win_rate < 40:
        adjustment = 10
    elif win_rate < 55:
        adjustment = 5
    elif win_rate > 75:
        adjustment = -5
    else:
        adjustment = 0

    suggested = max(50.0, min(95.0, base_threshold + adjustment))
    return {
        "suggested_threshold": suggested,
        "recent_win_rate": win_rate,
        "sample_size": total,
    }


# ---------------------------------------------------------------------------
# NEW: Investment / capital & detailed outcome-breakdown analytics
# ---------------------------------------------------------------------------
def get_investment_summary():
    """
    Total capital picture — how much is currently deployed in open positions,
    how much has been used historically in closed trades, and the all-time
    total. This is the 'how much money is actually at play' view.
    """
    with get_connection() as conn:
        try:
            df = pd.read_sql_query("SELECT status, allocated_amount FROM calls", conn)
        except Exception as e:
            logger.warning(f"get_investment_summary failed: {e}")
            df = pd.DataFrame(columns=["status", "allocated_amount"])

    empty_result = {
        "total_invested_all_time": 0.0,
        "currently_deployed": 0.0,
        "closed_capital": 0.0,
        "open_positions_count": 0,
        "closed_positions_count": 0,
        "total_trades": 0,
    }
    if df.empty:
        return empty_result

    df["allocated_amount"] = df["allocated_amount"].fillna(0.0)
    open_df = df[df["status"] == "OPEN"]
    closed_df = df[df["status"] != "OPEN"]

    return {
        "total_invested_all_time": round(df["allocated_amount"].sum(), 2),
        "currently_deployed": round(open_df["allocated_amount"].sum(), 2),
        "closed_capital": round(closed_df["allocated_amount"].sum(), 2),
        "open_positions_count": len(open_df),
        "closed_positions_count": len(closed_df),
        "total_trades": len(df),
    }


def outcome_breakdown(start_date=None, end_date=None):
    """
    Detailed breakdown of HOW closed trades actually ended:
      - target_hit          : clean target hits
      - sl_hit_legit        : stop-loss hit and price never came back (real loss)
      - sl_hit_fakeout      : stop-loss hit but price later hit target anyway
                              (SL-hunting / fakeout, flagged by the post-exit monitor)
      - manual_exit         : user squared off manually
    Each comes with a count and a % of total closed trades.
    """
    where = "WHERE status != 'OPEN'"
    params = []
    if start_date and end_date:
        where += " AND DATE(issued_at) BETWEEN ? AND ?"
        params = [str(start_date), str(end_date)]
    elif start_date:
        where += " AND DATE(issued_at) = ?"
        params = [str(start_date)]

    with get_connection() as conn:
        try:
            df = pd.read_sql_query(
                f"SELECT status, post_exit_status FROM calls {where}", conn, params=params
            )
        except Exception as e:
            logger.warning(f"outcome_breakdown failed: {e}")
            df = pd.DataFrame(columns=["status", "post_exit_status"])

    empty_result = {
        "target_hit": 0, "target_hit_pct": 0.0,
        "sl_hit_legit": 0, "sl_hit_legit_pct": 0.0,
        "sl_hit_fakeout": 0, "sl_hit_fakeout_pct": 0.0,
        "manual_exit": 0, "manual_exit_pct": 0.0,
        "other": 0, "other_pct": 0.0,
        "total": 0,
    }
    if df.empty:
        return empty_result

    total = len(df)
    post = df["post_exit_status"].fillna("")
    fakeout_mask = post.str.contains("FAKEOUT", case=False, na=False)

    target_hit = int((df["status"] == "HIT_TARGET").sum())
    sl_hit_fakeout = int(((df["status"] == "HIT_SL") & fakeout_mask).sum())
    sl_hit_legit = int(((df["status"] == "HIT_SL") & (~fakeout_mask)).sum())
    manual_exit = int((df["status"] == "MANUAL_EXIT").sum())
    other = max(0, total - target_hit - sl_hit_fakeout - sl_hit_legit - manual_exit)

    def pct(n):
        return round((n / total) * 100, 2) if total else 0.0

    return {
        "target_hit": target_hit, "target_hit_pct": pct(target_hit),
        "sl_hit_legit": sl_hit_legit, "sl_hit_legit_pct": pct(sl_hit_legit),
        "sl_hit_fakeout": sl_hit_fakeout, "sl_hit_fakeout_pct": pct(sl_hit_fakeout),
        "manual_exit": manual_exit, "manual_exit_pct": pct(manual_exit),
        "other": other, "other_pct": pct(other),
        "total": total,
    }


def avg_holding_time_minutes(start_date=None, end_date=None):
    """Average time (in minutes) between a call being issued and being closed."""
    where = "WHERE status != 'OPEN' AND exit_at IS NOT NULL AND issued_at IS NOT NULL"
    params = []
    if start_date and end_date:
        where += " AND DATE(issued_at) BETWEEN ? AND ?"
        params = [str(start_date), str(end_date)]
    elif start_date:
        where += " AND DATE(issued_at) = ?"
        params = [str(start_date)]

    with get_connection() as conn:
        try:
            df = pd.read_sql_query(f"SELECT issued_at, exit_at FROM calls {where}", conn, params=params)
        except Exception as e:
            logger.warning(f"avg_holding_time_minutes failed: {e}")
            return 0.0

    if df.empty:
        return 0.0

    def diff_minutes(row):
        try:
            i = datetime.fromisoformat(str(row["issued_at"]))
            e = datetime.fromisoformat(str(row["exit_at"]))
            return (e - i).total_seconds() / 60
        except Exception:
            return None

    diffs = df.apply(diff_minutes, axis=1).dropna()
    return round(diffs.mean(), 1) if not diffs.empty else 0.0