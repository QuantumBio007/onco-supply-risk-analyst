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

# Load API key from project root .env (override=True ensures .env takes precedence over shell environment)
load_dotenv(Path(__file__).parent.parent / ".env", override=True)

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")  # Register at newsapi.org (free tier: 100 req/day)

# News search queries (multi-dimensional LATAM-specific supply chain shocks)
# Each topic targets different shock types: manufacturing, logistics, regulatory, demand, currency, political, climate
QUERIES = {
    # Manufacturing shocks: facility disruptions, labor, quality issues in API source countries (India, China)
    "manufacturing": "(API OR pharmaceutical OR drug) AND (India OR China) AND (facility OR factory) AND (strike OR shutdown OR recall OR accident OR GMP OR quality)",

    # LATAM-specific logistics: Port congestion, road closures, shipping delays
    "logistics_latam": "(shipping OR cargo OR port OR logistics) AND (Santos OR Valparaiso OR Callao OR Buenaventura OR La Guaira) AND (congestion OR delay OR closure OR backlog)",

    # Regional political instability: sanctions, border closures, trade wars, government changes
    "latam_politics": "(Venezuela OR Colombia OR Argentina OR Brazil OR LATAM) AND (pharma OR drug OR medicine OR oncology) AND (sanction OR embargo OR blockade OR protest OR political OR trade war)",

    # Regulatory/policy shocks: drug pricing, patent changes, approval delays, healthcare policy
    "regulatory": "(drug OR pharma OR pharmaceutical) AND (Argentina OR Colombia OR Venezuela OR Brazil) AND (approval OR pricing OR patent OR regulation OR policy OR generic)",

    # Currency/FX volatility: affects procurement costs and payment delays
    "currency": "(exchange rate OR devaluation OR inflation OR peso OR bolivar OR currency crisis) AND (Argentina OR Colombia OR Venezuela OR Brazil OR LATAM) AND (pharma OR healthcare OR supply)",

    # Healthcare system demand shocks: cancer outbreaks, disease surges, hospital capacity, policy changes
    "healthcare_demand": "(cancer OR oncology OR drug shortage OR hospital) AND (Argentina OR Colombia OR Venezuela OR Brazil) AND (outbreak OR surge OR shortage OR access OR budget)",

    # Climate-specific to LATAM: Rainy season, landslides affecting mountain logistics, flooding of ports
    "climate_latam": "(flooding OR landslide OR rainy season OR drought OR weather) AND (Andes OR Peru OR Colombia OR Ecuador OR road OR port OR warehouse)",

    # Company-level disruptions: manufacturer recalls, M&A affecting production, supply agreements
    "company_events": "(pharmaceutical OR drug manufacturer) AND (recall OR merger OR acquisition OR facility OR partnership OR supply agreement) AND (Cipla OR Aurobindo OR Hikma OR Pfizer OR Roche)",

    # Macro-economic signals: oil/commodity shocks → LATAM inflation → health budget compression.
    # Intentionally excludes pharma keywords — the transmission pathway is macro, not supply-side.
    # Macro-economic signals: oil/commodity shocks → LATAM health budget compression → procurement cuts.
    # Tightened 2026-05-06 (session 26): original query too broad, returning Asian markets/Ukraine/satellite
    # news as IRRELEVANT. New query anchors on health/medicine budget specifically in target countries.
    "macro_latam": "(health budget OR medicine procurement OR salud presupuesto OR medicamentos) AND (Argentina OR Colombia OR Venezuela OR Peru OR Brazil) AND (recorte OR austerity OR inflation OR devaluation OR 'budget cut' OR desabastecimiento OR shortage OR crisis)",
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

    try:
        import requests
        from datetime import datetime, timedelta

        from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query or "pharma supply chain",
            "sortBy": "recency",
            "language": "en",
            "from": from_date,
            "apiKey": NEWSAPI_KEY,
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        articles = data.get("articles", [])
        print(f"[news_listener] Fetched {len(articles)} articles for: {query}")

    except Exception as e:
        print(f"[news_listener] Error: {str(e)}")
        articles = []

    return articles


if __name__ == "__main__":
    # Test fetch — use first available query key
    try:
        first_category = next(iter(QUERIES))
        articles = fetch_news(query=QUERIES[first_category])
        print(f"Fetched {len(articles)} articles for category: {first_category}")
        for a in articles[:3]:
            print(f"  - {a.get('title', 'N/A')}")
    except Exception as e:
        print(f"Error: {e}")
