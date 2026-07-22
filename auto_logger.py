import logging
from scorer import run_screener
from data_fetcher import is_market_open
import trade_log

logging.basicConfig(level=logging.INFO, format="%(asctime)s [AUTO_LOGGER] %(message)s")
logger = logging.getLogger("auto_logger")

def run_once(force: bool = False):
    if not force and not is_market_open():
        logger.info("Market closed. Skipping scan.")
        return

    df = run_screener()
    if df is None or df.empty:
        logger.info("No calls generated in this scan.")
        return

    saved = trade_log.log_calls_bulk(df, is_paper=1)
    logger.info(f"Successfully logged {saved} market calls.")

if __name__ == "__main__":
    run_once()