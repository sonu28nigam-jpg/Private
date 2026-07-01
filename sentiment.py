"""
News sentiment layer.

Free approach (no API key required):
1. Pull recent headlines for a stock from Google News RSS.
2. Score each headline with VADER (rule-based sentiment, runs
   fully offline once the lexicon is downloaded).

If you'd rather use an LLM (GPT-4o-mini, FinBERT, etc.) for more
nuanced scoring, replace `score_headline()` internals — the rest
of the app just needs a float in [-1, 1] back.
"""

import logging
import feedparser
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import nltk

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sentiment")

_analyzer = None


def _get_analyzer():
    global _analyzer
    if _analyzer is None:
        try:
            _analyzer = SentimentIntensityAnalyzer()
        except LookupError:
            nltk.download("vader_lexicon")
            _analyzer = SentimentIntensityAnalyzer()
    return _analyzer


def fetch_headlines(symbol: str, company_query: str = None, max_headlines: int = 8) -> list[str]:
    """
    Pull recent headlines for a stock via Google News RSS.
    `company_query` lets you pass a friendlier search term
    (e.g. "Reliance Industries") instead of the raw ticker.
    """
    query = company_query or symbol
    url = f"https://news.google.com/rss/search?q={query}+NSE+stock&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        feed = feedparser.parse(url)
        headlines = [entry.title for entry in feed.entries[:max_headlines]]
        return headlines
    except Exception as e:
        logger.warning(f"Failed to fetch news for {symbol}: {e}")
        return []


def score_headline(headline: str) -> float:
    analyzer = _get_analyzer()
    return analyzer.polarity_scores(headline)["compound"]  # -1.0 to +1.0


def news_score(symbol: str, company_query: str = None) -> dict:
    """
    Returns a 0-100 news sentiment score for a stock (averaged
    across recent headlines), plus the raw headlines + scores for
    transparency/debugging.
    """
    headlines = fetch_headlines(symbol, company_query)
    if not headlines:
        return {"score": 50, "headlines": [], "reason": "no_news_found"}  # neutral default

    scored = [(h, score_headline(h)) for h in headlines]
    avg_compound = sum(s for _, s in scored) / len(scored)  # -1..1
    score_0_100 = (avg_compound + 1) / 2 * 100
    return {
        "score": round(score_0_100, 2),
        "headlines": scored,
        "reason": "ok",
    }


if __name__ == "__main__":
    result = news_score("RELIANCE", "Reliance Industries")
    print(result)
