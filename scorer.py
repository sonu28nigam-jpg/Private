"""
Ranking & Scoring Engine — the "brain" of the app.

Combines technical_score() and news_score() into a single
Final Score per stock, applies the market-trend filter, and
returns a sorted list ready for the dashboard.
"""

import logging
import pandas as pd

from config import (
    STOCK_LIST, INDEX_SYMBOL, TECH_WEIGHT, NEWS_WEIGHT,
    ATR_MULTIPLIER, RISK_REWARD, CALL_THRESHOLD,
)
from data_fetcher import fetch_all, fetch_index_trend
from indicators import technical_score, trade_levels
from sentiment import news_score


def decide_call(final_score: float) -> str:
    """
    Turns a 0-100 final_score into a plain-language call:
    BUY, SHORT, or NO_CALL (score too weak/ambiguous either way).
    """
    if final_score >= CALL_THRESHOLD:
        return "BUY"
    if final_score <= (100 - CALL_THRESHOLD):
        return "SHORT"
    return "NO_CALL"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scorer")


def run_screener(stock_list: list[str] = None, use_news: bool = True) -> pd.DataFrame:
    """
    Runs the full pipeline once and returns a DataFrame sorted by
    Final Score (descending), with columns:
    symbol, last_price, tech_score, news_score, final_score,
    market_trend, breakdown (dict), headlines (list)
    """
    stock_list = stock_list or STOCK_LIST

    market_trend = fetch_index_trend(INDEX_SYMBOL)
    logger.info(f"Market trend (NIFTY): {market_trend}")

    candles = fetch_all(stock_list)
    rows = []

    for symbol in stock_list:
        df = candles.get(symbol)
        if df is None or df.empty:
            continue

        tech = technical_score(df)
        if tech["reason"] != "ok":
            continue

        if use_news:
            news = news_score(symbol)
        else:
            news = {"score": 50, "headlines": [], "reason": "skipped"}

        final = tech["score"] * TECH_WEIGHT + news["score"] * TECH_WEIGHT * 0 \
            + news["score"] * NEWS_WEIGHT  # explicit, avoids weight-sum bugs
        final = round(final, 2)

        call = decide_call(final)
        if call == "NO_CALL":
            levels = {"entry": round(float(df["Close"].iloc[-1]), 2),
                      "stop_loss": None, "target": None,
                      "risk_per_share": None, "reason": "score_too_weak"}
        else:
            levels = trade_levels(df, direction=call,
                                   atr_multiplier=ATR_MULTIPLIER,
                                   risk_reward=RISK_REWARD)

        rows.append({
            "symbol": symbol,
            "last_price": round(float(df["Close"].iloc[-1]), 2),
            "tech_score": tech["score"],
            "news_score": news["score"],
            "final_score": final,
            "call": call,
            "entry": levels["entry"],
            "stop_loss": levels["stop_loss"],
            "target": levels["target"],
            "risk_per_share": levels["risk_per_share"],
            "market_trend": market_trend,
            "breakdown": tech["breakdown"],
            "headlines": news["headlines"],
        })

    result_df = pd.DataFrame(rows)
    if result_df.empty:
        return result_df

    # Market Trend Filter (the "golden rule" from the blueprint):
    # if the broader market is bearish, flip sort order so the
    # weakest stocks (best short candidates) bubble to the top.
    ascending = market_trend == "bearish"
    result_df = result_df.sort_values("final_score", ascending=ascending).reset_index(drop=True)
    result_df["rank"] = result_df.index + 1
    return result_df


if __name__ == "__main__":
    df = run_screener(use_news=False)  # skip news for a fast local test
    cols = ["rank", "symbol", "call", "entry", "stop_loss", "target", "final_score"]
    print(df[cols] if not df.empty else "No data (needs live internet access to Yahoo Finance)")
