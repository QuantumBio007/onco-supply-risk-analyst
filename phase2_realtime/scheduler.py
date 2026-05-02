"""
scheduler.py — Orchestrate the Phase 2 pipeline: news → classify → shock → alert

Runs hourly (or on-demand) to fetch news and update risk estimates.
"""

import json
from datetime import datetime
from .news_listener import fetch_news, QUERIES
from .event_classifier import classify_article
from .shock_mapper import trigger_simulation
from .alert_engine import evaluate_risk_change, format_alert

# Target drugs and countries (from Phase 1)
TARGETS = {
    "drugs": ["cisplatin", "trastuzumab", "doxorubicin", "carboplatin"],
    "countries": ["Argentina", "Colombia", "Venezuela"],
}

# Cache to avoid re-processing same articles
PROCESSED_ARTICLES = set()


def run_cycle(query_category: str = "all") -> dict:
    """
    Run one complete Phase 2 cycle: fetch → classify → shock → alert.

    Args:
        query_category: "geopolitical" / "logistics" / "currency" / "environmental" / "all"

    Returns:
        dict with cycle results, alerts, articles processed
    """

    results = {
        "timestamp": datetime.now().isoformat(),
        "articles_fetched": 0,
        "articles_classified": 0,
        "alerts_triggered": [],
        "status": "ready",
    }

    # Step 1: Fetch news
    try:
        articles = fetch_news(query=query_category)
        results["articles_fetched"] = len(articles)
        print(f"[scheduler] Fetched {len(articles)} articles")
    except Exception as e:
        results["status"] = f"fetch_error: {str(e)}"
        return results

    # Step 2: Classify each article
    for article in articles:
        article_id = hash(article.get("title", ""))

        if article_id in PROCESSED_ARTICLES:
            continue  # Skip already-processed

        try:
            classification = classify_article(
                title=article.get("title", ""),
                description=article.get("description", ""),
            )

            if classification["classification"] in ["CRITICAL", "MODERATE"]:
                # Article identified as supply risk
                results["articles_classified"] += 1
                PROCESSED_ARTICLES.add(article_id)

                # Step 3: Trigger simulations for affected drug/country pairs
                affected_drugs = classification.get("affected_drugs", ["unknown"])
                affected_countries = classification.get("affected_countries", ["unknown"])

                for drug in affected_drugs:
                    for country in affected_countries:
                        if (
                            drug in TARGETS["drugs"]
                            or drug == "unknown"
                        ) and (country in TARGETS["countries"] or country == "unknown"):
                            # Step 4: Alert if risk jumped
                            shock_result = trigger_simulation(
                                classification, drug, country
                            )

                            alert_obj = {
                                "drug": drug,
                                "country": country,
                                "event": article.get("title", ""),
                                "classification": classification,
                                "shock_params": shock_result.get("shock_params"),
                            }
                            results["alerts_triggered"].append(alert_obj)
                            print(
                                f"[scheduler] ALERT: {drug}/{country} — {article.get('title')}"
                            )

        except Exception as e:
            print(f"[scheduler] Error classifying article: {str(e)}")
            continue

    return results


if __name__ == "__main__":
    # Test run
    print("[scheduler] Starting Phase 2 cycle...")
    result = run_cycle(query_category="geopolitical")
    print(json.dumps(result, indent=2))
