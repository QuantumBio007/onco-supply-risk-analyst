"""
news_listener.py — Fetch news articles about pharma supply shocks.

Polls NewsAPI every hour for articles about:
- Geopolitical events (Iran, Suez, trade wars)
- Logistics disruptions (ports, shipping)
- Currency/economic crises
- Environmental shocks (heat waves, monsoons)

Usage:
    from phase2_realtime.news_listener import fetch_news
    articles = fetch_news(query="pharma supply chain geopolitical")
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Load API key from project root .env
load_dotenv(Path(__file__).parent.parent / ".env")

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")  # Register at newsapi.org (free tier: 100 req/day)

# News search queries (customize based on Phase 2 roadmap)
QUERIES = {
    "geopolitical": "(pharma OR supply chain) AND (Iran OR sanctions OR Hormuz OR Suez)",
    "logistics": "(shipping OR port OR logistics) AND (congestion OR delay OR disruption)",
    "currency": "(currency OR devaluation OR peso OR peso crisis) AND (Latin America OR Colombia OR Argentina)",
    "environmental": "(heat wave OR monsoon OR drought) AND (manufacturing OR supply chain)",
}


def fetch_news(query: str = None, days_back: int = 1) -> list:
    """
    Fetch articles from NewsAPI about supply chain shocks.

    Args:
        query: Custom search query. If None, searches all QUERIES.
        days_back: How many days of articles to retrieve (default: 1 = last 24h)

    Returns:
        List of articles with: title, description, url, publishedAt, source
    """
    if not NEWSAPI_KEY:
        raise ValueError("NEWSAPI_KEY not set. Register at https://newsapi.org and add to .env")

    articles = []

    # For now: placeholder. After newsapi install, use:
    # from newsapi import NewsApiClient
    # client = NewsApiClient(api_key=NEWSAPI_KEY)
    # response = client.get_everything(q=query, sort_by="recency", language="en", ...)
    # articles = response['articles']

    print(f"[news_listener] Would fetch: {query}")
    print(f"[news_listener] Placeholder: install 'pip install newsapi' to enable real fetching")

    return articles


if __name__ == "__main__":
    # Test fetch
    try:
        articles = fetch_news(query=QUERIES["geopolitical"])
        print(f"Fetched {len(articles)} articles")
        for a in articles[:3]:
            print(f"  - {a.get('title', 'N/A')}")
    except Exception as e:
        print(f"Error: {e}")
