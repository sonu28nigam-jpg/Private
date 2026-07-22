import logging
import time
from scorer import run_screener
from data_fetcher import is_market_open
import trade_log

logging.basicConfig(level=logging.INFO, format="%(asctime)s [PAPER_TRADE] %(message)s")
logger = logging.getLogger("paper_trade")

def run_paper_trade():
    logger.info("Paper Trading Engine Active...")
    while True:
        try:
            if is_market_open():
                df = run_screener()
                if df is not None and not df.empty:
                    saved = trade_log.log_calls_bulk(df, is_paper=1)
                    logger.info(f"Auto-logged {saved} paper trades.")
                time.sleep(5 * 60) # 5 min refresh
            else:
                logger.info("Market Closed. Waiting for next cycle...")
                time.sleep(10 * 60)
        except Exception as e:
            logger.error(f"Paper trade engine error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_paper_trade()