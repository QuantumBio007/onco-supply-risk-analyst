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


def run_cycle(query_category: str = "latam_politics", limit_articles: int = 10) -> dict:
    """
    Run one complete Phase 2 cycle: fetch → classify → simulate → alert.

    Args:
        query_category: one of the QUERIES keys: manufacturing / logistics_latam /
                        latam_politics / regulatory / currency / healthcare_demand /
                        climate_latam / company_events
        limit_articles: Max articles to process per cycle (simulation is slow)

    Returns:
        dict with cycle results, alerts, risk deltas
    """

    results = {
        "timestamp": datetime.now().isoformat(),
        "articles_fetched": 0,
        "articles_processed": 0,
        "shocks_detected": 0,
        "alerts_triggered": [],
        "status": "ready",
    }

    # Step 1: Fetch news
    try:
        articles = fetch_news(query=QUERIES.get(query_category, "pharma supply chain"))
        results["articles_fetched"] = len(articles)
        print(f"[scheduler] Fetched {len(articles)} articles")
    except Exception as e:
        results["status"] = f"fetch_error: {str(e)}"
        return results

    # Step 2: Classify each article (limit for performance)
    for article in articles[:limit_articles]:
        article_id = hash(article.get("title", ""))

        if article_id in PROCESSED_ARTICLES:
            continue

        try:
            classification = classify_article(
                title=article.get("title", ""),
                description=article.get("description", ""),
            )

            if classification["severity"] in ["CRITICAL", "MODERATE"]:
                results["shocks_detected"] += 1
                PROCESSED_ARTICLES.add(article_id)

                # Step 3: Run simulation for each affected drug/country
                affected_drugs = classification.get("affected_drugs", [])
                affected_countries = classification.get("affected_countries", [])

                # If no specific drugs/countries identified, check all
                if not affected_drugs or "unknown" in affected_drugs:
                    affected_drugs = TARGETS["drugs"]
                if not affected_countries or "unknown" in affected_countries:
                    affected_countries = TARGETS["countries"]

                for drug in affected_drugs:
                    for country in affected_countries:
                        if drug in TARGETS["drugs"] and country in TARGETS["countries"]:
                            # Step 4: Compute risk delta
                            shock_result = trigger_simulation(
                                classification, drug, country
                            )
                            results["articles_processed"] += 1

                            if shock_result.get("status") == "simulated":
                                # Step 5: Evaluate alert (CVaR-aware)
                                alert = evaluate_risk_change(
                                    shock_result["baseline_risk"],
                                    shock_result["shocked_risk"],
                                    baseline_cvar=shock_result.get("baseline_cvar_90"),
                                    shocked_cvar=shock_result.get("shocked_cvar_90"),
                                )

                                alert_msg = format_alert(
                                    alert,
                                    drug,
                                    country,
                                    article.get("title", ""),
                                )

                                if alert["should_alert"]:
                                    results["alerts_triggered"].append({
                                        "drug": drug,
                                        "country": country,
                                        "shock_type": shock_result.get("shock_type", "unknown"),
                                        "simulation_mode": shock_result.get("simulation_mode", "unknown"),
                                        "severity": alert["severity"],
                                        "triggers": alert.get("triggers", []),
                                        "baseline_risk": shock_result["baseline_risk"],
                                        "shocked_risk": shock_result["shocked_risk"],
                                        "risk_delta": shock_result["risk_delta"],
                                        "percent_increase": shock_result["percent_increase"],
                                        "baseline_cvar_90": shock_result.get("baseline_cvar_90"),
                                        "shocked_cvar_90": shock_result.get("shocked_cvar_90"),
                                        "cvar_delta": alert.get("cvar_delta"),
                                        "cvar_percent_increase": alert.get("cvar_percent_increase"),
                                        "event": article.get("title", "")[:100],
                                    })
                                    print(
                                        f"[scheduler] {alert['severity']}: {drug}/{country} ({shock_result.get('shock_type', 'unknown')}) "
                                        f"mean +{shock_result['risk_delta']}d ({shock_result['percent_increase']:+.0f}%) | "
                                        f"CVaR_90 {alert.get('cvar_delta', 0):+.1f}d ({alert.get('cvar_percent_increase', 0):+.0f}%) "
                                        f"[{','.join(alert.get('triggers', []))}]"
                                    )

        except Exception as e:
            print(f"[scheduler] Error: {str(e)}")
            continue

    return results


if __name__ == "__main__":
    # Test run
    print("[scheduler] Starting Phase 2 cycle...")
    result = run_cycle(query_category="latam_politics")
    print(json.dumps(result, indent=2))
