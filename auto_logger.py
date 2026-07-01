"""
Standalone background runner — for TRUE every-15-minutes calls,
even when the Streamlit dashboard isn't open.

Run manually:
    python auto_logger.py

Or schedule it (Windows Task Scheduler):
    1. Open Task Scheduler -> Create Task
    2. Trigger: Daily, repeat every 15 minutes, during market hours
       (e.g. 9:15 AM - 3:30 PM)
    3. Action: Start a program
       Program: C:\\path\\to\\trading_app\\venv\\Scripts\\python.exe
       Arguments: auto_logger.py
       Start in: C:\\path\\to\\trading_app

Every run: fetches data, scores, logs new BUY/SHORT calls to
trade_log.db (same file the dashboard reads), and prints a short
summary to logger output. Open the dashboard any time afterward
to see everything that was logged while it was closed.
"""

import logging
from datetime import datetime

from scorer import run_screener
from data_fetcher import is_market_open
import trade_log

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("auto_logger")


def run_once(use_news: bool = True, force: bool = False):
    """
    force=True skips the market-hours check (useful for manual testing
    outside market hours). Scheduled/production runs should leave it False.
    """
    if not force and not is_market_open():
        logger.info("Market is closed (outside 9:15 AM - 3:30 PM IST, Mon-Fri). Skipping this run.")
        return

    logger.info("Running screener...")
    df = run_screener(use_news=use_news)

    if df is None or df.empty:
        logger.warning("No data returned this run (no network, or symbol issues).")
        return

    saved = trade_log.log_calls_bulk(df)
    calls = df[df["call"].isin(["BUY", "SHORT"])]
    logger.info(
        f"Run complete: {len(calls)} call(s) generated, {saved} new (not duplicates)."
    )
    for _, row in calls.iterrows():
        logger.info(
            f"  {row['call']:5s} {row['symbol']:12s} entry={row['entry']} "
            f"sl={row['stop_loss']} target={row['target']} score={row['final_score']}"
        )


if __name__ == "__main__":
    run_once()
