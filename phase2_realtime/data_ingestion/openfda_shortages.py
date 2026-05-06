"""
openfda_shortages.py — Daily ingestion of oncology drug shortage records from openFDA.

Usage:
    from phase2_realtime.data_ingestion.openfda_shortages import run_daily_cycle
    summary = run_daily_cycle()

openFDA drug shortages endpoint: https://api.fda.gov/drug/shortages.json
Oncology filter: search=therapeutic_category:"Oncology"
Rate limit: 240 req/min (unauthenticated), 240 req/min (with key — same limit, higher daily quota)
No API key required; OPENFDA_API_KEY in .env unlocks 120k req/day vs 1000/day anonymous.
"""

import hashlib
import json
import logging
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Load API key from project root .env — matches news_listener.py pattern
load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)
OPENFDA_API_KEY: Optional[str] = os.getenv("OPENFDA_API_KEY")

_BASE_URL = "https://api.fda.gov/drug/shortages.json"
_ONCOLOGY_SEARCH = 'therapeutic_category:"Oncology"'

# DB lives in phase2_data/ alongside processed.db (same pattern as scheduler.py)
_DB_PATH = Path(__file__).parent.parent.parent / "phase2_data" / "openfda.db"

# Respect openFDA rate limit: 240 req/min anonymous = 0.25 s/req minimum
_REQUEST_DELAY_SECONDS = 0.3

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Database initialisation
# ---------------------------------------------------------------------------

def _init_db() -> None:
    """Create the SQLite database and tables if they do not already exist."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS openfda_shortages (
                record_hash           TEXT PRIMARY KEY,
                generic_name          TEXT,
                proprietary_name      TEXT,
                company_name          TEXT,
                package_ndc           TEXT,
                therapeutic_category  TEXT,
                status                TEXT,
                shortage_reason       TEXT,
                availability          TEXT,
                initial_posting_date  TEXT,
                update_date           TEXT,
                change_date           TEXT,
                raw_json              TEXT,
                ingested_at           TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_status_category
            ON openfda_shortages(status, therapeutic_category)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dates
            ON openfda_shortages(initial_posting_date, update_date)
        """)


# Initialise on import (same pattern as scheduler.py calling _init_db() at module level)
_init_db()


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def _record_hash(generic_name: str, package_ndc: str, initial_posting_date: str) -> str:
    """
    Stable, deterministic hash over the three fields that identify a unique shortage record.
    MD5 is fine here — this is deduplication, not cryptography.
    """
    key = f"{generic_name}|{package_ndc}|{initial_posting_date}"
    return hashlib.md5(key.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _build_params(limit: int, skip: int, since_date: Optional[str]) -> dict:
    """Build openFDA query parameters."""
    search = _ONCOLOGY_SEARCH
    if since_date:
        # openFDA date format: YYYYMMDD
        date_compact = since_date.replace("-", "")
        search = f'{search}+AND+update_date:[{date_compact}+TO+29991231]'

    params: dict = {
        "search": search,
        "limit": limit,
        "skip": skip,
    }
    if OPENFDA_API_KEY:
        params["api_key"] = OPENFDA_API_KEY
    return params


def _parse_record(raw: dict) -> dict:
    """
    Flatten an openFDA shortage record into our canonical schema.

    Observed API structure (2026-05-05):
    - Dates are flat strings in "MM/DD/YYYY" format at top-level keys:
      initial_posting_date, update_date, discontinued_date (no nested dict).
    - therapeutic_category is a list (e.g. ["Rheumatology", "Oncology"]).
    - proprietary_name is not a top-level field; brand_name lives in openfda{}.
    - status values: "Current", "Resolved", "To Be Discontinued", "Discontinued".
    """

    def _safe_str(val) -> str:
        """Coerce any scalar to a stripped string; skip lists/dicts."""
        if val is None:
            return ""
        if isinstance(val, (list, dict)):
            return ""
        return str(val).strip()

    def _list_to_str(val) -> str:
        """Join list values to a pipe-separated string; coerce scalar to string."""
        if val is None:
            return ""
        if isinstance(val, list):
            return "|".join(str(v).strip() for v in val if v)
        return str(val).strip()

    generic_name = _safe_str(raw.get("generic_name"))
    package_ndc = _safe_str(raw.get("package_ndc"))
    initial_posting_date = _safe_str(raw.get("initial_posting_date"))

    # Brand name lives inside openfda{} as a list
    openfda_block = raw.get("openfda") or {}
    brand_names = openfda_block.get("brand_name") or []
    proprietary_name = brand_names[0] if brand_names else ""

    # therapeutic_category may be a list or a string
    therapeutic_category = _list_to_str(raw.get("therapeutic_category"))

    return {
        "record_hash": _record_hash(generic_name, package_ndc, initial_posting_date),
        "generic_name": generic_name,
        "proprietary_name": proprietary_name.strip(),
        "company_name": _safe_str(raw.get("company_name")),
        "package_ndc": package_ndc,
        "therapeutic_category": therapeutic_category,
        "status": _safe_str(raw.get("status")),
        "shortage_reason": _safe_str(raw.get("shortage_reason")),
        "availability": _safe_str(raw.get("availability")),
        "initial_posting_date": initial_posting_date,
        "update_date": _safe_str(raw.get("update_date")),
        "change_date": _safe_str(raw.get("discontinued_date") or raw.get("change_date")),
        "raw_json": json.dumps(raw, ensure_ascii=False),
        "ingested_at": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_oncology_shortages(
    limit: int = 100,
    since_date: Optional[str] = None,
) -> list[dict]:
    """
    Fetch oncology shortage records from openFDA, paginating until exhausted.

    Args:
        limit:      Records per page (max 1000 per openFDA docs, default 100).
        since_date: ISO date string "YYYY-MM-DD". If supplied, filters to records
                    updated on or after this date.

    Returns:
        List of parsed record dicts ready for ingest_to_db().
    """
    records: list[dict] = []
    skip = 0

    while True:
        params = _build_params(limit=limit, skip=skip, since_date=since_date)

        try:
            resp = requests.get(_BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as exc:
            log.error("[openfda] HTTP error at skip=%d: %s", skip, exc)
            break
        except json.JSONDecodeError as exc:
            log.error("[openfda] JSON decode error at skip=%d: %s", skip, exc)
            break

        # openFDA sometimes returns {"error": {...}} instead of {"results": [...]}
        if "error" in data:
            err = data["error"]
            # "No matches found" is not a real error — stop pagination cleanly
            if "No matches" in str(err.get("message", "")):
                log.info("[openfda] No matches found (skip=%d) — pagination complete", skip)
            else:
                log.error("[openfda] API error at skip=%d: %s", skip, err)
            break

        page_results = data.get("results", [])
        if not page_results:
            break

        for raw in page_results:
            try:
                records.append(_parse_record(raw))
            except Exception as exc:
                log.warning("[openfda] Failed to parse record: %s | record=%s", exc, raw)

        total_available = data.get("meta", {}).get("results", {}).get("total", 0)
        skip += len(page_results)

        log.info(
            "[openfda] Page fetched: %d records (skip=%d, total_available=%d)",
            len(page_results), skip, total_available,
        )

        # Stop if we've pulled everything or got a short page
        if skip >= total_available or len(page_results) < limit:
            break

        # Respect rate limit
        time.sleep(_REQUEST_DELAY_SECONDS)

    log.info("[openfda] fetch complete: %d oncology records", len(records))
    return records


def ingest_to_db(records: list[dict]) -> dict:
    """
    INSERT OR IGNORE records into the local SQLite DB.

    Args:
        records: List of dicts as returned by fetch_oncology_shortages().

    Returns:
        {"new": N, "existing": M, "errors": [...]}
    """
    result = {"new": 0, "existing": 0, "errors": []}

    if not records:
        return result

    _init_db()  # idempotent — safe to call multiple times

    with sqlite3.connect(_DB_PATH) as conn:
        for rec in records:
            try:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO openfda_shortages (
                        record_hash, generic_name, proprietary_name,
                        company_name, package_ndc, therapeutic_category,
                        status, shortage_reason, availability,
                        initial_posting_date, update_date, change_date,
                        raw_json, ingested_at
                    ) VALUES (
                        :record_hash, :generic_name, :proprietary_name,
                        :company_name, :package_ndc, :therapeutic_category,
                        :status, :shortage_reason, :availability,
                        :initial_posting_date, :update_date, :change_date,
                        :raw_json, :ingested_at
                    )
                    """,
                    rec,
                )
                if cursor.rowcount == 1:
                    result["new"] += 1
                else:
                    result["existing"] += 1
            except Exception as exc:
                msg = f"DB insert error for hash {rec.get('record_hash')}: {exc}"
                log.warning("[openfda] %s", msg)
                result["errors"].append(msg)

    log.info(
        "[openfda] ingest complete: new=%d existing=%d errors=%d",
        result["new"], result["existing"], len(result["errors"]),
    )
    return result


def get_active_shortages(since_date: Optional[str] = None) -> list[dict]:
    """
    Query the local DB for records where status = "Current shortage".

    Args:
        since_date: ISO date "YYYY-MM-DD". If supplied, further filters by
                    initial_posting_date >= since_date.

    Returns:
        List of row dicts from the DB.
    """
    _init_db()

    # openFDA status values observed: "Current", "Resolved", "To Be Discontinued", "Discontinued"
    # The spec said "Current shortage" — the real API uses "Current". We match on prefix to be safe.
    query = "SELECT * FROM openfda_shortages WHERE status = 'Current'"
    params: list = []

    if since_date:
        query += " AND initial_posting_date >= ?"
        params.append(since_date)

    query += " ORDER BY initial_posting_date DESC"

    try:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
    except Exception as exc:
        log.error("[openfda] get_active_shortages error: %s", exc)
        return []


def run_daily_cycle() -> dict:
    """
    Orchestrator: fetch → ingest → return summary.

    Returns:
        {
            "fetched": N,
            "new": M,
            "existing": K,
            "errors": [...],
            "active_shortages": X,
            "timestamp": "...",
        }
    """
    timestamp = datetime.utcnow().isoformat()
    log.info("[openfda] Starting daily cycle at %s", timestamp)

    records = fetch_oncology_shortages()
    ingest_result = ingest_to_db(records)
    active = get_active_shortages()

    summary = {
        "fetched": len(records),
        "new": ingest_result["new"],
        "existing": ingest_result["existing"],
        "errors": ingest_result["errors"],
        "active_shortages": len(active),
        "timestamp": timestamp,
    }

    log.info("[openfda] Daily cycle complete: %s", summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = run_daily_cycle()
    print(json.dumps(result, indent=2))
