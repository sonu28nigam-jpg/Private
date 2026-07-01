"""
Trade Log — the feedback loop.

Every call the screener issues gets saved here. You mark what
actually happened (hit target / hit stop-loss / manually closed),
and the app uses that history to show you which indicators are
actually working — real numbers, not guesses.

Uses SQLite (single file, zero setup) so your trade history
survives across restarts.
"""

import sqlite3
import json
from datetime import datetime, timedelta

from config import TRADE_LOG_DB, CALL_DEDUP_MINUTES


def _json_safe(obj):
    """
    Recursively converts numpy/pandas scalar types (np.bool_, np.int64,
    np.float64, etc.) to native Python types so json.dumps doesn't choke.
    Indicator functions can return numpy types depending on pandas/numpy
    version, so this is a safety net independent of upstream fixes.
    """
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if hasattr(obj, "item"):  # numpy scalar (np.bool_, np.int64, np.float64, ...)
        return obj.item()
    return obj

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    call_type TEXT NOT NULL,       -- BUY or SHORT
    issued_at TEXT NOT NULL,       -- ISO timestamp when the call was generated
    entry REAL,
    stop_loss REAL,
    target REAL,
    tech_score REAL,
    news_score REAL,
    final_score REAL,
    breakdown TEXT,                -- JSON string of the indicator breakdown
    status TEXT DEFAULT 'OPEN',    -- OPEN, HIT_TARGET, HIT_SL, MANUAL_CLOSE
    exit_price REAL,
    exit_at TEXT,
    points_captured REAL,          -- actual profit/loss per share (signed)
    target_miss_by REAL,           -- how far the exit was from the target (signed)
    notes TEXT
);
"""


def get_conn():
    conn = sqlite3.connect(TRADE_LOG_DB)
    conn.execute(SCHEMA)
    return conn


def log_call(row: dict) -> int | None:
    """
    Saves a call from the screener's output row. Skips saving if
    an identical (symbol, call_type) call was already logged within
    CALL_DEDUP_MINUTES, so re-running the screener every few minutes
    doesn't spam duplicate rows for the same signal.
    Returns the new row's id, or None if skipped as a duplicate.
    """
    if row.get("call") not in ("BUY", "SHORT"):
        return None  # don't log NO_CALL rows

    conn = get_conn()
    cutoff = (datetime.now() - timedelta(minutes=CALL_DEDUP_MINUTES)).isoformat()
    existing = conn.execute(
        """SELECT id FROM calls WHERE symbol=? AND call_type=? AND status='OPEN'
           AND issued_at >= ? ORDER BY issued_at DESC LIMIT 1""",
        (row["symbol"], row["call"], cutoff),
    ).fetchone()
    if existing:
        conn.close()
        return None

    cur = conn.execute(
        """INSERT INTO calls
           (symbol, call_type, issued_at, entry, stop_loss, target,
            tech_score, news_score, final_score, breakdown, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')""",
        (
            row["symbol"], row["call"], datetime.now().isoformat(),
            row["entry"], row["stop_loss"], row["target"],
            row["tech_score"], row["news_score"], row["final_score"],
            json.dumps(_json_safe(row.get("breakdown", {}))),
        ),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def log_calls_bulk(df) -> int:
    """Logs every BUY/SHORT row in a screener result DataFrame. Returns count actually saved."""
    saved = 0
    for _, row in df.iterrows():
        if log_call(row.to_dict()) is not None:
            saved += 1
    return saved


def get_open_calls():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM calls WHERE status='OPEN' ORDER BY issued_at DESC"
    ).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM calls LIMIT 0").description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def get_all_calls(limit: int = 200):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM calls ORDER BY issued_at DESC LIMIT ?", (limit,)
    ).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM calls LIMIT 0").description]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def record_outcome(call_id: int, status: str, exit_price: float = None, notes: str = ""):
    """
    Marks a call's outcome. status must be one of:
    'HIT_TARGET', 'HIT_SL', 'MANUAL_CLOSE'.
    Automatically computes points_captured and target_miss_by.
    """
    conn = get_conn()
    row = conn.execute("SELECT call_type, entry, target FROM calls WHERE id=?", (call_id,)).fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"No call with id {call_id}")

    call_type, entry, target = row
    points_captured = None
    target_miss_by = None

    if exit_price is not None and entry is not None:
        if call_type == "BUY":
            points_captured = round(exit_price - entry, 2)
            if target is not None:
                target_miss_by = round(exit_price - target, 2)  # negative = fell short
        else:  # SHORT
            points_captured = round(entry - exit_price, 2)
            if target is not None:
                target_miss_by = round(target - exit_price, 2)  # negative = fell short

    conn.execute(
        """UPDATE calls SET status=?, exit_price=?, exit_at=?,
           points_captured=?, target_miss_by=?, notes=? WHERE id=?""",
        (status, exit_price, datetime.now().isoformat(),
         points_captured, target_miss_by, notes, call_id),
    )
    conn.commit()
    conn.close()


def performance_summary() -> dict:
    """
    Overall stats across every closed call: win rate, average
    points captured, and a breakdown of win rate by which
    technical conditions were true at call time — this is the
    "what's actually working" signal you tune weights with.
    """
    conn = get_conn()
    closed = conn.execute(
        "SELECT * FROM calls WHERE status != 'OPEN'"
    ).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM calls LIMIT 0").description]
    conn.close()
    closed = [dict(zip(cols, r)) for r in closed]

    if not closed:
        return {"total_closed": 0, "reason": "no_closed_trades_yet"}

    wins = [c for c in closed if c["status"] == "HIT_TARGET"]
    losses = [c for c in closed if c["status"] == "HIT_SL"]
    manual = [c for c in closed if c["status"] == "MANUAL_CLOSE"]

    win_rate = round(len(wins) / len(closed) * 100, 1)
    pts = [c["points_captured"] for c in closed if c["points_captured"] is not None]
    avg_points = round(sum(pts) / len(pts), 2) if pts else None

    # Win rate per indicator condition (this is the "learning" signal)
    condition_stats = {}
    for c in closed:
        try:
            breakdown = json.loads(c["breakdown"]) if c["breakdown"] else {}
        except (json.JSONDecodeError, TypeError):
            breakdown = {}
        is_win = c["status"] == "HIT_TARGET"
        for cond, val in breakdown.items():
            if not isinstance(val, bool):
                continue
            key = f"{cond}={val}"
            if key not in condition_stats:
                condition_stats[key] = {"wins": 0, "total": 0}
            condition_stats[key]["total"] += 1
            if is_win:
                condition_stats[key]["wins"] += 1

    condition_win_rates = {
        k: {"win_rate": round(v["wins"] / v["total"] * 100, 1), "sample_size": v["total"]}
        for k, v in condition_stats.items()
    }

    return {
        "total_closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "manual_closes": len(manual),
        "win_rate_pct": win_rate,
        "avg_points_per_trade": avg_points,
        "condition_win_rates": condition_win_rates,
    }


if __name__ == "__main__":
    # Quick smoke test
    fake_row = {
        "symbol": "TESTSTOCK", "call": "BUY", "entry": 100.0,
        "stop_loss": 98.0, "target": 104.0, "tech_score": 80,
        "news_score": 60, "final_score": 72, "breakdown": {"above_vwap": True},
    }
    new_id = log_call(fake_row)
    print("Logged call id:", new_id)
    if new_id:
        record_outcome(new_id, "HIT_TARGET", exit_price=104.5)
    print(performance_summary())