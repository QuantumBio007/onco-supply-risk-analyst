"""
test_anmat_scraper.py — pytest suite for the ANMAT scraper.

Tests:
  1. Latin-1 fixture: shortage table with accented chars parses without mojibake.
  2. UTF-8 fixture: Boletín Oficial snippet parses correctly.
  3. Hash determinism for each table.
  4. Re-ingestion idempotency (0 new rows on second run).
  5. Live test (skip unless ANMAT_LIVE_TEST=1): real site returns ≥1 row.
  6. Gold-standard: Disposición 3865/2025 fixture yields correct number, lab, date.

Run:
    pytest phase2_realtime/tests/test_anmat_scraper.py -v
    ANMAT_LIVE_TEST=1 pytest phase2_realtime/tests/test_anmat_scraper.py -v -k live
"""

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FIXTURES = Path(__file__).parent / "fixtures" / "anmat"
SHORTAGE_FIXTURE   = FIXTURES / "shortage_latin1.html"
ALERTS_FIXTURE     = FIXTURES / "alerts_latin1.html"
BOLETIN_FIXTURE    = FIXTURES / "boletin_utf8.html"
GOLD_FIXTURE       = FIXTURES / "disposicion_3865_gold.html"

# ---------------------------------------------------------------------------
# Import helpers — import from installed package path
# ---------------------------------------------------------------------------
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from phase2_realtime.data_ingestion.anmat_scraper import (
    _get_conn,
    _ingest_alerts,
    _ingest_dispositions,
    _ingest_shortages,
    _init_db,
    _normalise_headers,
    _parse_alerts_page,
    _parse_boletin_page,
    _sha1,
    fetch_shortage_list,
)


# ---------------------------------------------------------------------------
# Fixtures helpers
# ---------------------------------------------------------------------------

def _read_latin1(path: Path) -> str:
    """Read a Latin-1 encoded file and decode it correctly."""
    return path.read_bytes().decode("latin-1")


def _read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _make_tmp_db() -> sqlite3.Connection:
    """Return an in-memory SQLite connection with the ANMAT schema."""
    conn = sqlite3.connect(":memory:")
    _init_db(conn)
    return conn


# ---------------------------------------------------------------------------
# Test 1: Latin-1 fixture parses without mojibake
# ---------------------------------------------------------------------------

class TestLatin1Parsing:
    """Shortage table with accented Spanish characters must parse cleanly."""

    def test_no_mojibake_in_producto(self):
        """'CÁPSULAS' must decode as Á, not as mojibake like Ã."""
        html = _read_latin1(SHORTAGE_FIXTURE)
        assert "Ã" not in html, "Fixture itself has mojibake — re-encode as Latin-1"
        assert "Á" in html or "á" in html or "é" in html or "ó" in html or "ó" in html, \
            "Expected accented characters in fixture"

    def test_soup_preserves_accents(self):
        """BeautifulSoup parsed from Latin-1 bytes must preserve accented chars."""
        raw_bytes = SHORTAGE_FIXTURE.read_bytes()
        # Simulate what requests does after response.encoding = 'latin-1'
        html = raw_bytes.decode("latin-1")
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()
        # 'é' in 'Pérez', 'ó' in 'importación', 'Á' in 'CÁPSULAS'
        assert "é" in text or "ó" in text or "Á" in text, (
            f"Accented characters lost. Got (sample): {text[:200]!r}"
        )

    def test_wrong_encoding_produces_mojibake(self):
        """Reading Latin-1 file as UTF-8 MUST produce mojibake (validates the test itself)."""
        raw_bytes = SHORTAGE_FIXTURE.read_bytes()
        # Deliberately decode as UTF-8 with replacement
        bad_text = raw_bytes.decode("utf-8", errors="replace")
        assert "é" not in bad_text or "?" in bad_text or "�" in bad_text, \
            "Expected mojibake when using wrong encoding"

    def test_shortage_table_parses_rows(self):
        """Parser extracts ≥2 data rows from the fixture."""
        html = _read_latin1(SHORTAGE_FIXTURE)

        # Patch _get so fetch_shortage_list uses the fixture HTML
        mock_resp = MagicMock()
        mock_resp.text = html

        with patch("phase2_realtime.data_ingestion.anmat_scraper._get",
                   return_value=mock_resp):
            rows = fetch_shortage_list()

        assert len(rows) >= 2, f"Expected ≥2 rows, got {len(rows)}"

    def test_row_fields_present(self):
        """Every row must have the 8 canonical field keys."""
        html = _read_latin1(SHORTAGE_FIXTURE)
        mock_resp = MagicMock()
        mock_resp.text = html

        with patch("phase2_realtime.data_ingestion.anmat_scraper._get",
                   return_value=mock_resp):
            rows = fetch_shortage_list()

        required = {
            "producto", "ifa", "laboratorio", "certificado",
            "fecha_notificacion", "estado", "motivo", "fecha_normalizacion",
        }
        for row in rows:
            missing = required - row.keys()
            assert not missing, f"Row missing fields: {missing}. Row: {row}"

    def test_accented_field_values(self):
        """Parsed laboratorio field must contain 'é' (from 'Pérez'), not mojibake."""
        html = _read_latin1(SHORTAGE_FIXTURE)
        mock_resp = MagicMock()
        mock_resp.text = html

        with patch("phase2_realtime.data_ingestion.anmat_scraper._get",
                   return_value=mock_resp):
            rows = fetch_shortage_list()

        all_labs = " ".join(r.get("laboratorio", "") for r in rows)
        assert "é" in all_labs or "ó" in all_labs, (
            f"Accented chars missing in laboratorio field. Got: {all_labs!r}"
        )


# ---------------------------------------------------------------------------
# Test 2: UTF-8 fixture (Boletín Oficial) parses correctly
# ---------------------------------------------------------------------------

class TestUTF8Parsing:
    """Boletín Oficial UTF-8 page must parse disposiciones correctly."""

    def test_boletin_parses_dispositions(self):
        html = _read_utf8(BOLETIN_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        dispositions = _parse_boletin_page(soup, "20250606")
        assert len(dispositions) >= 1, "Expected ≥1 disposition from UTF-8 fixture"

    def test_disposition_fields_present(self):
        html = _read_utf8(BOLETIN_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        dispositions = _parse_boletin_page(soup, "20250606")
        required = {"numero_disposicion", "fecha", "sumario", "detalle_url"}
        for d in dispositions:
            missing = required - d.keys()
            assert not missing, f"Disposition missing fields: {missing}"

    def test_utf8_accents_preserved(self):
        """Sumario text must contain Spanish accented chars without corruption."""
        html = _read_utf8(BOLETIN_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        dispositions = _parse_boletin_page(soup, "20250606")
        all_text = " ".join(d.get("sumario", "") for d in dispositions)
        # 'ó' in 'oncológicas', 'é' in 'especialidades'
        assert "ó" in all_text or "é" in all_text, (
            f"UTF-8 accents lost. Got: {all_text[:200]!r}"
        )


# ---------------------------------------------------------------------------
# Test 3: Hash determinism
# ---------------------------------------------------------------------------

class TestHashDeterminism:
    """Hashes must be stable (deterministic) across calls."""

    def test_shortage_hash_deterministic(self):
        h1 = _sha1("Cisplatino", "Cisplatino", "M-XXXX-001")
        h2 = _sha1("Cisplatino", "Cisplatino", "M-XXXX-001")
        assert h1 == h2

    def test_shortage_hash_case_insensitive(self):
        """Hash normalises to lowercase so 'CISPLATINO' == 'cisplatino'."""
        h1 = _sha1("CISPLATINO", "Cisplatino", "M-XXXX-001")
        h2 = _sha1("cisplatino", "cisplatino", "m-xxxx-001")
        assert h1 == h2

    def test_alert_hash_deterministic(self):
        h1 = _sha1("Disposición 3865/2025", "06/06/2025")
        h2 = _sha1("Disposición 3865/2025", "06/06/2025")
        assert h1 == h2

    def test_different_inputs_give_different_hashes(self):
        h1 = _sha1("Cisplatino", "Cisplatino", "M-XXXX-001")
        h2 = _sha1("Temozolomida", "Temozolomida", "M-YYYY-002")
        assert h1 != h2

    def test_disposition_id_is_disposition_number(self):
        """disposition_id is the numero_disposicion string — check it's stable."""
        from phase2_realtime.data_ingestion.anmat_scraper import _extract_disposicion_number
        text = "Disposición 3865/2025 — ANMAT — Eczane Pharma S.A."
        n1 = _extract_disposicion_number(text)
        n2 = _extract_disposicion_number(text)
        assert n1 == n2 == "3865/2025"


# ---------------------------------------------------------------------------
# Test 4: Re-ingestion idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    """Running ingestion twice on the same data must produce 0 new rows on second run."""

    def _shortage_rows(self):
        return [
            {
                "producto": "CISPLATINO 50MG",
                "ifa": "Cisplatino",
                "laboratorio": "Lab Pérez S.A.",
                "certificado": "M-XXXX-001",
                "fecha_notificacion": "15/03/2025",
                "estado": "Faltante temporal",
                "motivo": "Demora importación",
                "fecha_normalizacion": "30/06/2025",
            }
        ]

    def _alert_rows(self):
        return [
            {
                "fecha": "06/06/2025",
                "titulo": "Disposición 3865/2025",
                "descripcion": "Suspensión oncológicos",
                "pdf_url": "http://www.anmat.gob.ar/comunicados/alerta_3865.pdf",
            }
        ]

    def _disposition_rows(self):
        return [
            {
                "numero_disposicion": "3865/2025",
                "fecha": "20250606",
                "sumario": "Eczane Pharma suspensión",
                "detalle_url": "https://www.boletinoficial.gob.ar/detalleAviso/primera/326644/20250606",
            }
        ]

    def test_shortage_idempotent(self):
        conn = _make_tmp_db()
        rows = self._shortage_rows()
        n1 = _ingest_shortages(rows, conn)
        n2 = _ingest_shortages(rows, conn)
        assert n1 == 1
        assert n2 == 0, f"Second ingest produced {n2} new rows; expected 0"

    def test_alert_idempotent(self):
        conn = _make_tmp_db()
        alerts = self._alert_rows()
        n1 = _ingest_alerts(alerts, conn)
        n2 = _ingest_alerts(alerts, conn)
        assert n1 == 1
        assert n2 == 0, f"Second ingest produced {n2} new rows; expected 0"

    def test_disposition_idempotent(self):
        conn = _make_tmp_db()
        disps = self._disposition_rows()
        n1 = _ingest_dispositions(disps, conn)
        n2 = _ingest_dispositions(disps, conn)
        assert n1 == 1
        assert n2 == 0, f"Second ingest produced {n2} new rows; expected 0"

    def test_mixed_batch_idempotent(self):
        """Ingesting 2 rows, then same 2 + 1 new → only 1 new on second call."""
        conn = _make_tmp_db()
        rows = self._shortage_rows()
        n1 = _ingest_shortages(rows, conn)
        assert n1 == 1

        extra = {
            "producto": "TRASTUZUMAB 440MG",
            "ifa": "Trastuzumab",
            "laboratorio": "Lab Alpha",
            "certificado": "M-ZZZZ-003",
            "fecha_notificacion": "01/04/2025",
            "estado": "Faltante temporal",
            "motivo": "Planta manufacturera",
            "fecha_normalizacion": "01/09/2025",
        }
        n2 = _ingest_shortages(rows + [extra], conn)
        assert n2 == 1, f"Expected 1 new row, got {n2}"


# ---------------------------------------------------------------------------
# Test 5: Live test (skipped by default)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.getenv("ANMAT_LIVE_TEST"),
    reason="Set ANMAT_LIVE_TEST=1 to run live network tests",
)
class TestLive:
    def test_fetch_shortage_list_returns_rows(self):
        """Real ANMAT site must return ≥1 row."""
        rows = fetch_shortage_list()
        assert len(rows) >= 1, "No rows from live ANMAT shortage list"

    def test_no_mojibake_in_live_data(self):
        """Live data must not contain mojibake sequences like 'Ã©'."""
        rows = fetch_shortage_list()
        all_text = " ".join(str(v) for row in rows for v in row.values())
        assert "Ã©" not in all_text, f"Mojibake detected in live data: {all_text[:300]}"
        assert "Ã" not in all_text, f"Mojibake detected in live data: {all_text[:300]}"


# ---------------------------------------------------------------------------
# Test 6: Gold-standard — Disposición 3865/2025
# ---------------------------------------------------------------------------

class TestGoldStandard:
    """
    Gold-standard: parse saved fixture of Eczane Pharma Disposición 3865/2025.
    Confirm disposition number, lab name, and date extracted correctly.
    """

    def test_disposition_number_extracted(self):
        html = _read_utf8(GOLD_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        dispositions = _parse_boletin_page(soup, "20250606")
        numbers = [d["numero_disposicion"] for d in dispositions]
        assert "3865/2025" in numbers, (
            f"Disposición 3865/2025 not found. Got: {numbers}"
        )

    def test_lab_name_in_sumario(self):
        """Eczane Pharma must appear in the sumario of 3865/2025."""
        html = _read_utf8(GOLD_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        dispositions = _parse_boletin_page(soup, "20250606")
        target = next(
            (d for d in dispositions if d["numero_disposicion"] == "3865/2025"),
            None,
        )
        assert target is not None, "Disposición 3865/2025 not parsed"
        assert "Eczane" in target["sumario"], (
            f"'Eczane' not in sumario: {target['sumario']!r}"
        )

    def test_fecha_extracted(self):
        """Fecha field must equal '20250606' (the date passed to the parser)."""
        html = _read_utf8(GOLD_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        dispositions = _parse_boletin_page(soup, "20250606")
        target = next(
            (d for d in dispositions if d["numero_disposicion"] == "3865/2025"),
            None,
        )
        assert target is not None
        assert target["fecha"] == "20250606", (
            f"Expected fecha='20250606', got {target['fecha']!r}"
        )

    def test_detalle_url_contains_aviso_id(self):
        """Detail URL must contain the Boletín Oficial aviso ID 326644."""
        html = _read_utf8(GOLD_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        dispositions = _parse_boletin_page(soup, "20250606")
        target = next(
            (d for d in dispositions if d["numero_disposicion"] == "3865/2025"),
            None,
        )
        assert target is not None
        assert "326644" in target["detalle_url"], (
            f"Aviso ID 326644 not in detalle_url: {target['detalle_url']!r}"
        )

    def test_extract_disposicion_number_from_text(self):
        """_extract_disposicion_number must work on various text formats."""
        from phase2_realtime.data_ingestion.anmat_scraper import _extract_disposicion_number
        cases = [
            ("Disposición 3865/2025 — ANMAT", "3865/2025"),
            ("DISPOSICION 3865/2025", "3865/2025"),
            ("Disp. 3865/2025 oncológicos", "3865/2025"),
            ("Disposición Nº 3752/2025", "3752/2025"),
        ]
        for text, expected in cases:
            got = _extract_disposicion_number(text)
            assert got == expected, f"Input: {text!r} → expected {expected!r}, got {got!r}"
