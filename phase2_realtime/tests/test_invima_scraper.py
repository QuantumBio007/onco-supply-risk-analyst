"""
test_invima_scraper.py — pytest suite for the INVIMA scraper.

Tests:
  1. UTF-8 fixture: shortage index page with Spanish accented characters parses
     without mojibake.
  2. Hash determinism for both tables (shortages + alerts).
  3. Re-ingestion idempotency (0 new rows on second run).
  4. Live test (skip unless INVIMA_LIVE_TEST=1 env var).
  5. Edge cases: empty page, missing fields, date format variations.
  6. principio_activo field present (empty but present — PDF-gap documented).
  7. Alerts table parsing: tipo_alerta, detail_url, fecha extraction.

Run:
    pytest phase2_realtime/tests/test_invima_scraper.py -v
    INVIMA_LIVE_TEST=1 pytest phase2_realtime/tests/test_invima_scraper.py -v -k live
"""

import os
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FIXTURES = Path(__file__).parent / "fixtures" / "invima"
SHORTAGE_FIXTURE = FIXTURES / "desabastecimientos_utf8.html"
ALERTS_FIXTURE   = FIXTURES / "alertas_medicamentos_utf8.html"

# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from phase2_realtime.data_ingestion.invima_scraper import (
    _extract_date_from_anchor,
    _classify_report_tipo,
    _get_conn,
    _ingest_alerts,
    _ingest_shortages,
    _init_db,
    _parse_alertas_page,
    _parse_alertas_table,
    _parse_desabastecimientos_page,
    _sha1,
    fetch_alertas,
    fetch_desabastecimientos,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _make_tmp_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    _init_db(conn)
    return conn


def _mock_resp(html: str) -> MagicMock:
    m = MagicMock()
    m.text = html
    return m


# ---------------------------------------------------------------------------
# Test 1: UTF-8 encoding — no mojibake on Spanish accented chars
# ---------------------------------------------------------------------------

class TestUTF8Encoding:
    """Shortage index with accented Spanish chars must parse without mojibake."""

    def test_fixture_contains_accented_chars(self):
        """Fixture file itself must contain genuine UTF-8 accented characters."""
        raw = SHORTAGE_FIXTURE.read_bytes()
        text = raw.decode("utf-8")
        # Expect: é, ó, ú etc. from 'seguimiento', 'médicos', 'disponibilidad'
        has_accent = any(c in text for c in "áéíóúÁÉÍÓÚñÑ")
        assert has_accent, "Fixture must contain Spanish accented characters"

    def test_no_mojibake_in_fixture(self):
        """UTF-8 decoded text must NOT contain classic Latin-1/UTF-8 mojibake."""
        text = SHORTAGE_FIXTURE.read_bytes().decode("utf-8")
        assert "Ã©" not in text, "Mojibake 'Ã©' found — encoding bug in fixture"
        assert "Ã³" not in text, "Mojibake 'Ã³' found"
        assert "Â" not in text,  "Mojibake 'Â' found"

    def test_wrong_encoding_produces_corruption(self):
        """Reading UTF-8 file as Latin-1 must corrupt the accented characters."""
        raw = SHORTAGE_FIXTURE.read_bytes()
        bad_text = raw.decode("latin-1")
        # UTF-8 multi-byte sequences decoded as Latin-1 produce characteristic garbage
        assert any(c in bad_text for c in ["Ã", "Â", "\x83", "\x9a"]), (
            "Expected corruption when decoding UTF-8 as Latin-1"
        )

    def test_soup_preserves_utf8_accents(self):
        """BeautifulSoup parsed from UTF-8 text must preserve accented chars."""
        html = _read_utf8(SHORTAGE_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()
        assert any(c in text for c in "áéíóúÁÉÍÓÚñÑ"), (
            f"Accented chars lost in soup. Sample: {text[:200]!r}"
        )

    def test_shortage_index_parses_records(self):
        """Parser extracts ≥3 records from the fixture."""
        html = _read_utf8(SHORTAGE_FIXTURE)
        mock_resp = _mock_resp(html)
        with patch("phase2_realtime.data_ingestion.invima_scraper._get",
                   return_value=mock_resp):
            records = fetch_desabastecimientos()
        assert len(records) >= 3, f"Expected ≥3 records, got {len(records)}"

    def test_accented_chars_in_producto(self):
        """producto field must carry accented chars from anchor text."""
        html = _read_utf8(SHORTAGE_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        records = _parse_desabastecimientos_page(soup)
        all_productos = " ".join(r["producto"] for r in records)
        assert any(c in all_productos for c in "áéíóúÁÉÍÓÚñÑ"), (
            f"No accented chars in producto fields. Got: {all_productos[:200]!r}"
        )


# ---------------------------------------------------------------------------
# Test 2: Hash determinism
# ---------------------------------------------------------------------------

class TestHashDeterminism:

    def test_shortage_hash_deterministic(self):
        h1 = _sha1("Listado desabastecimiento - Marzo 2026", "2026-03-01")
        h2 = _sha1("Listado desabastecimiento - Marzo 2026", "2026-03-01")
        assert h1 == h2

    def test_shortage_hash_case_insensitive(self):
        h1 = _sha1("LISTADO DESABASTECIMIENTO - MARZO 2026", "2026-03-01")
        h2 = _sha1("listado desabastecimiento - marzo 2026", "2026-03-01")
        assert h1 == h2

    def test_alert_hash_deterministic(self):
        h1 = _sha1("BEVACIZUMAB retiro lote", "2026-04-15")
        h2 = _sha1("BEVACIZUMAB retiro lote", "2026-04-15")
        assert h1 == h2

    def test_different_records_give_different_hashes(self):
        h1 = _sha1("BEVACIZUMAB retiro lote", "2026-04-15")
        h2 = _sha1("TRASTUZUMAB informe calidad", "2026-03-28")
        assert h1 != h2

    def test_hash_stable_across_whitespace_variants(self):
        """Hash normalises strip+lower, so extra whitespace doesn't matter."""
        h1 = _sha1("  Listado Marzo 2026  ", "  2026-03-01  ")
        h2 = _sha1("Listado Marzo 2026", "2026-03-01")
        assert h1 == h2


# ---------------------------------------------------------------------------
# Test 3: Re-ingestion idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:

    def _shortage_records(self):
        return [
            {
                "producto": "Listado de abastecimiento y desabastecimiento - Marzo 2026",
                "principio_activo": "",
                "titular_registro": "",
                "registro_sanitario": "",
                "fecha_notificacion": "2026-03-01",
                "tipo": "abastecimiento_y_desabastecimiento",
                "motivo": "",
                "fecha_normalizacion_estimada": "",
                "detail_url": "https://www.invima.gov.co/biblioteca/listado-marzo-2026.pdf",
            }
        ]

    def _alert_records(self):
        return [
            {
                "fecha": "2026-04-15",
                "titulo": "BEVACIZUMAB — Retiro voluntario lote BV2024-001",
                "tipo_alerta": "Alerta sanitaria",
                "descripcion_breve": "",
                "detail_url": "https://app.invima.gov.co/alertas/ckfinder/BEVACIZUMAB.pdf",
            }
        ]

    def test_shortage_idempotent(self):
        conn = _make_tmp_db()
        rows = self._shortage_records()
        n1 = _ingest_shortages(rows, conn)
        n2 = _ingest_shortages(rows, conn)
        assert n1 == 1
        assert n2 == 0, f"Second ingest produced {n2} new rows; expected 0"

    def test_alert_idempotent(self):
        conn = _make_tmp_db()
        alerts = self._alert_records()
        n1 = _ingest_alerts(alerts, conn)
        n2 = _ingest_alerts(alerts, conn)
        assert n1 == 1
        assert n2 == 0, f"Second ingest produced {n2} new rows; expected 0"

    def test_mixed_batch_idempotent(self):
        """2 records, then same 2 + 1 new → only 1 new on second call."""
        conn = _make_tmp_db()
        rows = self._shortage_records()
        n1 = _ingest_shortages(rows, conn)
        assert n1 == 1

        extra = {
            "producto": "Listado de abastecimiento y desabastecimiento - Febrero 2026",
            "principio_activo": "",
            "titular_registro": "",
            "registro_sanitario": "",
            "fecha_notificacion": "2026-02-01",
            "tipo": "abastecimiento_y_desabastecimiento",
            "motivo": "",
            "fecha_normalizacion_estimada": "",
            "detail_url": "https://www.invima.gov.co/biblioteca/listado-febrero-2026.pdf",
        }
        n2 = _ingest_shortages(rows + [extra], conn)
        assert n2 == 1, f"Expected 1 new row, got {n2}"

    def test_alert_mixed_batch_idempotent(self):
        conn = _make_tmp_db()
        alerts = self._alert_records()
        n1 = _ingest_alerts(alerts, conn)
        assert n1 == 1

        extra = {
            "fecha": "2026-03-28",
            "titulo": "TRASTUZUMAB — Informe calidad",
            "tipo_alerta": "Informe de seguridad",
            "descripcion_breve": "",
            "detail_url": "https://app.invima.gov.co/alertas/ckfinder/TRASTUZUMAB.pdf",
        }
        n2 = _ingest_alerts(alerts + [extra], conn)
        assert n2 == 1, f"Expected 1 new alert, got {n2}"


# ---------------------------------------------------------------------------
# Test 4: Live test (skipped by default)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.getenv("INVIMA_LIVE_TEST"),
    reason="Set INVIMA_LIVE_TEST=1 to run live network tests",
)
class TestLive:
    def test_fetch_desabastecimientos_returns_rows(self):
        records = fetch_desabastecimientos()
        assert len(records) >= 1, "No rows from live INVIMA desabastecimientos page"

    def test_no_mojibake_in_live_shortage_data(self):
        records = fetch_desabastecimientos()
        all_text = " ".join(str(v) for r in records for v in r.values())
        assert "Ã©" not in all_text, f"Mojibake in live shortage data: {all_text[:300]}"

    def test_fetch_alertas_returns_rows(self):
        alerts = fetch_alertas(max_pages=1)
        assert len(alerts) >= 1, "No rows from live INVIMA alerts page"

    def test_no_mojibake_in_live_alert_data(self):
        alerts = fetch_alertas(max_pages=1)
        all_text = " ".join(str(v) for a in alerts for v in a.values())
        assert "Ã©" not in all_text, f"Mojibake in live alert data: {all_text[:300]}"


# ---------------------------------------------------------------------------
# Test 5: Edge cases — empty page, missing fields, date format variations
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_empty_page_returns_empty_list_shortages(self):
        """Parser must return [] for a page with no shortage links."""
        html = "<html><body><p>No hay registros.</p></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        records = _parse_desabastecimientos_page(soup)
        assert records == []

    def test_empty_page_returns_empty_list_alerts(self):
        html = "<html><body><table><tr><th>Tipo</th><th>Nombre</th></tr></table></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        alerts = _parse_alertas_page(soup)
        assert alerts == []

    def test_missing_date_returns_empty_string(self):
        """Anchor with no recognisable month → fecha_notificacion = ''."""
        date = _extract_date_from_anchor("Listado sin fecha identificable 2025")
        assert date == ""

    def test_date_extraction_all_months(self):
        """_extract_date_from_anchor must handle all 12 Spanish months."""
        cases = [
            ("Listado enero 2025", "2025-01-01"),
            ("Listado febrero 2025", "2025-02-01"),
            ("Listado marzo 2025", "2025-03-01"),
            ("Listado abril 2025", "2025-04-01"),
            ("Listado mayo 2025", "2025-05-01"),
            ("Listado junio 2025", "2025-06-01"),
            ("Listado julio 2025", "2025-07-01"),
            ("Listado agosto 2025", "2025-08-01"),
            ("Listado septiembre 2025", "2025-09-01"),
            ("Listado octubre 2025", "2025-10-01"),
            ("Listado noviembre 2025", "2025-11-01"),
            ("Listado diciembre 2025", "2025-12-01"),
        ]
        for anchor, expected in cases:
            got = _extract_date_from_anchor(anchor)
            assert got == expected, f"anchor={anchor!r}: expected {expected!r}, got {got!r}"

    def test_date_extraction_with_upper_case_month(self):
        """Month name matching must be case-insensitive."""
        date = _extract_date_from_anchor("Listado MARZO 2026")
        assert date == "2026-03-01"

    def test_tipo_classification(self):
        cases = [
            ("Listado de abastecimiento y desabastecimiento - Marzo 2026",
             "abastecimiento_y_desabastecimiento"),
            ("Informe de disponibilidad de medicamentos - Junio 2023",
             "disponibilidad"),
            ("Listado desabastecimiento medicamentos 2024",
             "desabastecimiento"),
        ]
        for anchor, expected_tipo in cases:
            got = _classify_report_tipo(anchor)
            assert got == expected_tipo, (
                f"anchor={anchor!r}: expected {expected_tipo!r}, got {got!r}"
            )

    def test_ingest_shortages_with_empty_list(self):
        """Ingesting an empty list must return 0 and not crash."""
        conn = _make_tmp_db()
        n = _ingest_shortages([], conn)
        assert n == 0

    def test_ingest_alerts_with_empty_list(self):
        conn = _make_tmp_db()
        n = _ingest_alerts([], conn)
        assert n == 0

    def test_missing_fields_handled_gracefully(self):
        """Records with missing optional fields must still be ingested."""
        conn = _make_tmp_db()
        rows = [{"producto": "Listado test", "fecha_notificacion": "2026-01-01"}]
        # Must not raise; missing keys get default empty string
        n = _ingest_shortages(rows, conn)
        assert n == 1


# ---------------------------------------------------------------------------
# Test 6: principio_activo field present (ATC join key)
# ---------------------------------------------------------------------------

class TestPrincipioActivo:
    """
    principio_activo is the ATC join key for the MAB.
    On the INVIMA shortage index page it is empty (data lives in PDFs).
    The field MUST be present in every record with value '' (not absent, not None).
    This documents the known gap and ensures the schema is correct for when
    PDF parsing is added in a future sprint.
    """

    def test_principio_activo_field_present_in_index_records(self):
        """Every shortage index record must have principio_activo key."""
        html = _read_utf8(SHORTAGE_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        records = _parse_desabastecimientos_page(soup)
        assert len(records) >= 1, "Need ≥1 record to test"
        for rec in records:
            assert "principio_activo" in rec, (
                f"principio_activo missing from record: {rec}"
            )

    def test_principio_activo_is_empty_string_not_none(self):
        """principio_activo must be '' not None — None breaks ATC crosswalk logic."""
        html = _read_utf8(SHORTAGE_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        records = _parse_desabastecimientos_page(soup)
        for rec in records:
            val = rec.get("principio_activo")
            assert val is not None, (
                f"principio_activo is None; must be '' for ATC join. Record: {rec}"
            )
            assert isinstance(val, str), (
                f"principio_activo must be str, got {type(val)}"
            )

    def test_all_schema_fields_present_in_shortage_record(self):
        """Every required schema field must exist on every parsed record."""
        required = {
            "producto", "principio_activo", "titular_registro",
            "registro_sanitario", "fecha_notificacion", "tipo",
            "motivo", "fecha_normalizacion_estimada", "detail_url",
        }
        html = _read_utf8(SHORTAGE_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        records = _parse_desabastecimientos_page(soup)
        for rec in records:
            missing = required - rec.keys()
            assert not missing, f"Record missing fields: {missing}. Record: {rec}"

    def test_all_schema_fields_present_in_alert_record(self):
        """Every required schema field must exist on every parsed alert."""
        required = {"fecha", "titulo", "tipo_alerta", "descripcion_breve", "detail_url"}
        html = _read_utf8(ALERTS_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        alerts = _parse_alertas_page(soup)
        assert len(alerts) >= 1, "Need ≥1 alert to test"
        for alert in alerts:
            missing = required - alert.keys()
            assert not missing, f"Alert missing fields: {missing}. Alert: {alert}"


# ---------------------------------------------------------------------------
# Test 7: Alerts parsing — tipo_alerta, detail_url, fecha, UTF-8 accents
# ---------------------------------------------------------------------------

class TestAlertsParsing:

    def test_alerts_fixture_parses_rows(self):
        """Alerts fixture must yield ≥3 alert records."""
        html = _read_utf8(ALERTS_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        alerts = _parse_alertas_page(soup)
        assert len(alerts) >= 3, f"Expected ≥3 alerts, got {len(alerts)}"

    def test_tipo_alerta_extracted(self):
        """tipo_alerta must contain 'Alerta sanitaria' or 'Informe de seguridad'."""
        html = _read_utf8(ALERTS_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        alerts = _parse_alertas_page(soup)
        known_tipos = {"Alerta sanitaria", "Informe de seguridad"}
        for alert in alerts:
            assert alert["tipo_alerta"] in known_tipos, (
                f"Unexpected tipo_alerta: {alert['tipo_alerta']!r}"
            )

    def test_fecha_extracted_iso_format(self):
        """fecha must be ISO YYYY-MM-DD or empty string, never garbage."""
        import re as _re
        html = _read_utf8(ALERTS_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        alerts = _parse_alertas_page(soup)
        iso_pattern = _re.compile(r"^20\d{2}-\d{2}-\d{2}$")
        for alert in alerts:
            if alert["fecha"]:
                assert iso_pattern.match(alert["fecha"]), (
                    f"fecha not ISO format: {alert['fecha']!r}"
                )

    def test_detail_url_is_absolute(self):
        """detail_url must be absolute (starts with http)."""
        html = _read_utf8(ALERTS_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        alerts = _parse_alertas_page(soup)
        for alert in alerts:
            if alert["detail_url"]:
                assert alert["detail_url"].startswith("http"), (
                    f"detail_url not absolute: {alert['detail_url']!r}"
                )

    def test_utf8_accents_in_alert_titulo(self):
        """Alert titulo must preserve accented chars from the UTF-8 fixture."""
        html = _read_utf8(ALERTS_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        alerts = _parse_alertas_page(soup)
        all_titulos = " ".join(a["titulo"] for a in alerts)
        assert any(c in all_titulos for c in "áéíóúÁÉÍÓÚñÑ"), (
            f"No accented chars in alert titulos. Got: {all_titulos[:200]!r}"
        )

    def test_bevacizumab_alert_parsed(self):
        """BEVACIZUMAB alert (gold-standard oncology drug) must be in results."""
        html = _read_utf8(ALERTS_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        alerts = _parse_alertas_page(soup)
        titulos = [a["titulo"] for a in alerts]
        assert any("BEVACIZUMAB" in t for t in titulos), (
            f"BEVACIZUMAB not found in alerts. Titles: {titulos}"
        )

    def test_cisplatino_alert_parsed(self):
        """CISPLATINO alert must be parsed — oncology drug, key for MAB."""
        html = _read_utf8(ALERTS_FIXTURE)
        soup = BeautifulSoup(html, "html.parser")
        alerts = _parse_alertas_page(soup)
        titulos = [a["titulo"] for a in alerts]
        assert any("CISPLATINO" in t for t in titulos), (
            f"CISPLATINO not found in alerts. Titles: {titulos}"
        )

    def test_fetch_alertas_uses_mock(self):
        """fetch_alertas with mocked HTTP must return parsed alerts."""
        html = _read_utf8(ALERTS_FIXTURE)
        mock_resp = _mock_resp(html)
        with patch("phase2_realtime.data_ingestion.invima_scraper._get",
                   return_value=mock_resp):
            alerts = fetch_alertas(max_pages=1)
        assert len(alerts) >= 3
