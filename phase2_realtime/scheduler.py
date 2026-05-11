"""
scheduler.py — Orchestrate the Phase 2 pipeline: news → classify → shock → alert

Designed for DAILY cadence (not hourly). 9 queries × 1/day = 9 req/day vs. 100/day
free-tier limit. Running more than once per day per category wastes quota with no benefit —
shortage signals move on week-to-week timescales, not minute-to-minute.
"""

import hashlib
import json
import sqlite3
import time
from datetime import datetime, date
from pathlib import Path

# FIX (2026-05-07): runaway-loop guard. Hard cap on per-cycle wall-clock time
# prevents an infinite-retry loop or a stuck downstream call from burning API
# budget unnoticed. 300s = 5 min comfortably covers a 10-article cycle on the
# vectorized pipeline (~1s per article post-optimization).
_MAX_CYCLE_SECONDS = 300

from .news_listener import fetch_news, QUERIES
# FIX #2 (2026-05-07): swap to prompt-cached fast classifier.
# Original `from .event_classifier import classify_article` re-sent the 2.8k-token
# system prompt on every call. The fast version uses Anthropic's ephemeral cache
# (~5.6× cheaper per call after warm-up). Drop-in replacement, identical signature.
from optimized.event_classifier_fast import classify_article
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS category_last_run (
                category     TEXT PRIMARY KEY,
                last_run_date TEXT NOT NULL
            )
        """)


def _already_ran_today(category: str) -> bool:
    try:
        with sqlite3.connect(_DB_PATH) as conn:
            row = conn.execute(
                "SELECT last_run_date FROM category_last_run WHERE category = ?",
                (category,),
            ).fetchone()
            return row is not None and row[0] == date.today().isoformat()
    except Exception:
        return False


def _mark_category_run(category: str) -> None:
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO category_last_run (category, last_run_date) VALUES (?, ?)",
            (category, date.today().isoformat()),
        )


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


def run_cycle(query_category: str = "latam_politics", limit_articles: int = 10,
              force: bool = False) -> dict:
    """
    Run one complete Phase 2 cycle: fetch → classify → simulate → alert.

    Args:
        query_category: one of the QUERIES keys: manufacturing / logistics_latam /
                        latam_politics / regulatory / currency / healthcare_demand /
                        climate_latam / company_events / macro_latam
        limit_articles: Max articles to process per cycle (simulation is slow)
        force: Skip the daily cadence guard (use for testing/smoke tests)

    Returns:
        dict with cycle results, alerts, risk deltas
    """
    if not force and _already_ran_today(category=query_category):
        print(f"[scheduler] {query_category} already ran today — skipping (use force=True to override)")
        return {"status": "skipped_daily_guard", "category": query_category,
                "timestamp": datetime.now().isoformat()}

    cycle_start = time.monotonic()                       # FIX: runaway-loop timer
    results = {
        "timestamp": datetime.now().isoformat(),
        "articles_fetched": 0,
        "articles_processed": 0,
        "shocks_detected": 0,
        "alerts_triggered": [],
        "status": "ready",
        "cycle_aborted_on_timeout": False,
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
        # FIX: hard wall-clock cap — protect API budget against stuck loops.
        if time.monotonic() - cycle_start > _MAX_CYCLE_SECONDS:
            results["cycle_aborted_on_timeout"] = True
            results["status"] = f"timeout_after_{_MAX_CYCLE_SECONDS}s"
            print(f"[scheduler] cycle timeout after {_MAX_CYCLE_SECONDS}s — aborting remaining articles")
            break

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
                        if drug not in TARGETS["drugs"]:
                            print(f"[scheduler] skipping {drug} — not in TARGETS (add to DRUG_PARAMS in supply_sim.py to enable)")
                            continue
                        if country not in TARGETS["countries"]:
                            print(f"[scheduler] skipping {country} — not in TARGETS")
                            continue
                        if True:
                            # Step 4: Compute risk delta
                            shock_result = trigger_simulation(
                                classification, drug, country
                            )
                            results["articles_processed"] += 1

                            if shock_result.get("status") == "simulated":
                                # Step 5: Evaluate alert (CVaR-aware, macro-aware)
                                alert = evaluate_risk_change(
                                    shock_result["baseline_risk"],
                                    shock_result["shocked_risk"],
                                    baseline_cvar=shock_result.get("baseline_cvar_90"),
                                    shocked_cvar=shock_result.get("shocked_cvar_90"),
                                    shock_type=classification.get("shock_type", "unknown"),
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

    _mark_category_run(query_category)
    return results


if __name__ == "__main__":
    # Test run — force=True bypasses daily guard
    print("[scheduler] Starting Phase 2 cycle...")
    result = run_cycle(query_category="latam_politics", force=True)
    print(json.dumps(result, indent=2))
