import logging
import feedparser
from transformers import BertTokenizer, BertForSequenceClassification
import torch

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sentiment")

tokenizer = BertTokenizer.from_pretrained('ProsusAI/finbert')
model = BertForSequenceClassification.from_pretrained('ProsusAI/finbert')

def score_headlines_batch(headlines: list[str]) -> list[float]:
    if not headlines:
        return []
    with torch.no_grad():
        inputs = tokenizer(headlines, return_tensors="pt", padding=True, truncation=True, max_length=128)
        outputs = model(**inputs)
        probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
        scores = (probs[:, 0] - probs[:, 1]).tolist()
    return scores

def news_score(symbol: str, company_query: str = None) -> dict:
    headlines = fetch_headlines(symbol, company_query)
    if not headlines:
        return {"score": 50, "headlines": [], "reason": "no_news"}

    scores = score_headlines_batch(headlines)
    avg_score = sum(scores) / len(scores) if scores else 0
    score_0_100 = (avg_score + 1) * 50
    scored_headlines = list(zip(headlines, scores))
    return {"score": round(score_0_100, 2), "headlines": scored_headlines}

def fetch_headlines(symbol: str, company_query: str = None, max_headlines: int = 5) -> list[str]:
    query = company_query or symbol
    url = f"https://news.google.com/rss/search?q={query}+NSE+stock&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        feed = feedparser.parse(url)
        return [entry.title for entry in feed.entries[:max_headlines]]
    except Exception as e:
        logger.warning(f"Error fetching headlines: {e}")
        return []