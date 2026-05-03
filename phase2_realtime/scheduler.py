"""
scheduler.py — Orchestrate the Phase 2 pipeline: news → classify → shock → alert

Runs hourly (or on-demand) to fetch news and update risk estimates.
"""

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .news_listener import fetch_news, QUERIES
from .event_classifier import classify_article
from .shock_mapper import trigger_simulation
from .alert_engine import evaluate_risk_change, format_alert

# Target drugs and countries (from Phase 1)
TARGETS = {
    "drugs": ["cisplatin", "trastuzumab", "doxorubicin", "carboplatin"],
    "countries": ["Argentina", "Colombia", "Venezuela"],
}

# SQLite-backed deduplication — survives restarts.
# Phase 2 alert dedup: only CRITICAL/MODERATE articles are persisted.
# MINOR/IRRELEVANT are re-evaluated each cycle (news context can evolve).
_DB_PATH = Path(__file__).parent.parent / "phase2_data" / "processed.db"


def _init_db() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_articles (
                article_hash  TEXT PRIMARY KEY,
                processed_at  TEXT NOT NULL,
                classification TEXT
            )
        """)


def _article_hash(title: str) -> str:
    # MD5 of title — stable across restarts (unlike Python's hash()).
    return hashlib.md5(title.encode("utf-8", errors="replace")).hexdigest()


def _is_processed(article_hash: str) -> bool:
    try:
        with sqlite3.connect(_DB_PATH) as conn:
            return conn.execute(
                "SELECT 1 FROM processed_articles WHERE article_hash = ?",
                (article_hash,),
            ).fetchone() is not None
    except Exception:
        return False


def _mark_processed(article_hash: str, severity: str, shock_type: str) -> None:
    try:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO processed_articles "
                "(article_hash, processed_at, classification) VALUES (?, ?, ?)",
                (article_hash, datetime.now().isoformat(),
                 json.dumps({"severity": severity, "shock_type": shock_type})),
            )
    except Exception as e:
        print(f"[scheduler] DB write warning: {e}")


_init_db()


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
        article_id = _article_hash(article.get("title", ""))

        if _is_processed(article_id):
            continue

        try:
            classification = classify_article(
                title=article.get("title", ""),
                description=article.get("description", ""),
            )

            if classification["severity"] in ["CRITICAL", "MODERATE"]:
                results["shocks_detected"] += 1
                _mark_processed(article_id,
                                 classification["severity"],
                                 classification.get("shock_type", "unknown"))

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
