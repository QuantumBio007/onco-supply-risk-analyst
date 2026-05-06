"""
test_openfda_shortages.py — pytest suite for the openFDA drug shortage ingestion module.

Run unit tests (default):
    pytest phase2_realtime/tests/test_openfda_shortages.py -v

Run including live API test (requires network):
    pytest phase2_realtime/tests/test_openfda_shortages.py -v -m live
"""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------
from phase2_realtime.data_ingestion.openfda_shortages import (
    _record_hash,
    fetch_oncology_shortages,
    get_active_shortages,
    ingest_to_db,
    run_daily_cycle,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_record(
    generic_name: str = "Methotrexate Sodium",
    package_ndc: str = "0143-9678-10",
    initial_posting_date: str = "20240101",
    status: str = "Current",
    n: int = 0,
) -> dict:
    """Build a minimal parsed record dict for testing."""
    suffix = f"_{n}" if n else ""
    name = generic_name + suffix
    return {
        "record_hash": _record_hash(name, package_ndc, initial_posting_date),
        "generic_name": name,
        "proprietary_name": "Methotrexate Injection",
        "company_name": "Accord Healthcare",
        "package_ndc": package_ndc,
        "therapeutic_category": "Oncology",
        "status": status,
        "shortage_reason": "Shortage of active ingredient",
        "availability": "Limited availability",
        "initial_posting_date": initial_posting_date,
        "update_date": "20240601",
        "change_date": "",
        "raw_json": json.dumps({"generic_name": name}),
        "ingested_at": "2026-05-05T00:00:00",
    }


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """
    Redirect the module-level _DB_PATH to a temp file so each test
    gets a fresh, isolated database.
    """
    import phase2_realtime.data_ingestion.openfda_shortages as mod

    temp_db = tmp_path / "test_openfda.db"
    monkeypatch.setattr(mod, "_DB_PATH", temp_db)
    # Re-init so the tables exist in the temp DB
    mod._init_db()
    return temp_db


# ---------------------------------------------------------------------------
# Test 1: Hash function is deterministic
# ---------------------------------------------------------------------------

class TestRecordHash:
    def test_same_input_same_hash(self):
        h1 = _record_hash("Cisplatin", "12345-678-90", "20230101")
        h2 = _record_hash("Cisplatin", "12345-678-90", "20230101")
        assert h1 == h2, "Hash must be deterministic for identical inputs"

    def test_different_name_different_hash(self):
        h1 = _record_hash("Cisplatin", "12345-678-90", "20230101")
        h2 = _record_hash("Carboplatin", "12345-678-90", "20230101")
        assert h1 != h2

    def test_different_ndc_different_hash(self):
        h1 = _record_hash("Cisplatin", "11111-111-11", "20230101")
        h2 = _record_hash("Cisplatin", "22222-222-22", "20230101")
        assert h1 != h2

    def test_returns_hex_string(self):
        h = _record_hash("Cisplatin", "12345-678-90", "20230101")
        assert isinstance(h, str)
        assert len(h) == 32  # MD5 hex digest

    def test_empty_fields_stable(self):
        h1 = _record_hash("", "", "")
        h2 = _record_hash("", "", "")
        assert h1 == h2


# ---------------------------------------------------------------------------
# Test 2: ingest_to_db with empty list
# ---------------------------------------------------------------------------

class TestIngestEmpty:
    def test_empty_list_returns_zero_counts(self, isolated_db):
        result = ingest_to_db([])
        assert result["new"] == 0
        assert result["existing"] == 0
        assert result["errors"] == []


# ---------------------------------------------------------------------------
# Test 3: ingest_to_db with 5 new records
# ---------------------------------------------------------------------------

class TestIngestNew:
    def test_five_new_records_inserted(self, isolated_db):
        records = [_make_record(n=i) for i in range(5)]
        result = ingest_to_db(records)
        assert result["new"] == 5
        assert result["existing"] == 0
        assert result["errors"] == []

    def test_db_row_count_after_insert(self, isolated_db):
        records = [_make_record(n=i) for i in range(5)]
        ingest_to_db(records)
        with sqlite3.connect(isolated_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM openfda_shortages").fetchone()[0]
        assert count == 5


# ---------------------------------------------------------------------------
# Test 4: Re-ingesting same 5 records → new=0, existing=5
# ---------------------------------------------------------------------------

class TestIngestDedup:
    def test_reingest_same_records(self, isolated_db):
        records = [_make_record(n=i) for i in range(5)]
        # First pass
        ingest_to_db(records)
        # Second pass — same records, same hashes
        result = ingest_to_db(records)
        assert result["new"] == 0
        assert result["existing"] == 5
        assert result["errors"] == []

    def test_db_row_count_unchanged_after_reingest(self, isolated_db):
        records = [_make_record(n=i) for i in range(5)]
        ingest_to_db(records)
        ingest_to_db(records)
        with sqlite3.connect(isolated_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM openfda_shortages").fetchone()[0]
        assert count == 5


# ---------------------------------------------------------------------------
# Test 5: get_active_shortages filters by status="Current shortage"
# ---------------------------------------------------------------------------

class TestGetActiveShortages:
    def test_filters_current_shortage_only(self, isolated_db):
        # Real openFDA status values: "Current", "Resolved", "To Be Discontinued", "Discontinued"
        records = [
            _make_record(n=0, status="Current"),
            _make_record(n=1, status="Current"),
            _make_record(n=2, status="Resolved"),
            _make_record(n=3, status="Discontinued"),
        ]
        ingest_to_db(records)
        active = get_active_shortages()
        assert len(active) == 2
        for row in active:
            assert row["status"] == "Current"

    def test_returns_empty_when_no_current(self, isolated_db):
        records = [
            _make_record(n=0, status="Resolved"),
            _make_record(n=1, status="Discontinued"),
        ]
        ingest_to_db(records)
        active = get_active_shortages()
        assert active == []

    def test_since_date_filter(self, isolated_db):
        records = [
            _make_record(n=0, status="Current", initial_posting_date="20230101"),
            _make_record(n=1, status="Current", initial_posting_date="20240601"),
        ]
        ingest_to_db(records)
        # since_date filters to records with initial_posting_date >= "20240101"
        active = get_active_shortages(since_date="20240101")
        assert len(active) == 1
        assert active[0]["initial_posting_date"] == "20240601"

    def test_returns_list_of_dicts(self, isolated_db):
        ingest_to_db([_make_record(status="Current")])
        active = get_active_shortages()
        assert isinstance(active, list)
        assert isinstance(active[0], dict)
        assert "generic_name" in active[0]


# ---------------------------------------------------------------------------
# Test 6: End-to-end live API test (skipped by default)
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestLiveAPI:
    """
    Live network tests. Run with: pytest -m live
    These tests are excluded from the default test run.
    """

    def test_fetch_returns_oncology_records(self):
        """Fetch a small page from openFDA and verify at least one oncology record."""
        records = fetch_oncology_shortages(limit=10)
        assert len(records) >= 1, (
            "Expected at least 1 oncology record from openFDA. "
            "Check network connectivity or API availability."
        )

    def test_fetched_records_have_required_fields(self):
        """All fetched records must have the canonical fields."""
        required = {
            "record_hash", "generic_name", "therapeutic_category",
            "status", "raw_json", "ingested_at",
        }
        records = fetch_oncology_shortages(limit=10)
        for rec in records:
            missing = required - set(rec.keys())
            assert not missing, f"Record missing fields: {missing}"

    def test_fetched_records_are_oncology_category(self):
        """Verify the therapeutic_category filter is respected.
        therapeutic_category is stored as a pipe-joined string; must contain 'Oncology'.
        """
        records = fetch_oncology_shortages(limit=20)
        for rec in records:
            cat = rec.get("therapeutic_category", "")
            # Pipe-joined e.g. "Rheumatology|Oncology" or empty for bad records
            assert "Oncology" in cat or cat == "", (
                f"Non-oncology record slipped through: {cat}"
            )

    def test_live_ingest_and_active_query(self, isolated_db):
        """Full end-to-end: fetch → ingest → get_active_shortages."""
        records = fetch_oncology_shortages(limit=10)
        result = ingest_to_db(records)

        assert result["errors"] == [], f"Ingest errors: {result['errors']}"
        assert result["new"] + result["existing"] == len(records)

        # Re-ingest should flip all to existing
        result2 = ingest_to_db(records)
        assert result2["new"] == 0
        assert result2["existing"] == len(records)
