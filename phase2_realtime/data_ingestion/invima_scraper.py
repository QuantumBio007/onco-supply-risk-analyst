"""
invima_scraper.py — Daily scraper for two INVIMA (Colombia) data streams.

Endpoints:
  - Desabastecimientos index page: static HTML listing PDF links, one per month.
    The PDFs themselves are NOT parsed (out of scope; no Selenium, no PDF parser).
    We scrape the index to record which monthly reports exist, their URLs, and
    extract metadata embedded in the link anchor text (month, year, tipo).
    DEVIATION from spec: structured fields (principio_activo, titular_registro, etc.)
    live inside the PDFs. The index page yields only {producto (report title), fecha,
    tipo, detail_url}. Full field extraction requires PDF parsing — documented as a
    known gap. record_hash is stable on (producto, fecha).
  - Alerts (Alertas Sanitarias): static HTML table at
    https://app.invima.gov.co/alertas/medicamentos-productos-biologicos
    Paginated. Fields: fecha, titulo, tipo_alerta, descripcion_breve, detail_url.

Polite scraping: 1 req/sec, 5s timeout, 1 retry, descriptive User-Agent.
No Selenium/Playwright. No PDF parsing (sprint constraint).
Encoding: UTF-8 (modern INVIMA site).

Usage:
    from phase2_realtime.data_ingestion.invima_scraper import run_daily_cycle
    result = run_daily_cycle()
"""

import hashlib
import logging
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_AGENT = "OncoSupply-research/0.1 (academic research; cmart156@jh.edu)"

INVIMA_BASE = "https://www.invima.gov.co"
ALERTS_BASE = "https://app.invima.gov.co"

SHORTAGES_URL = (
    "https://www.invima.gov.co/productos-vigilados/"
    "medicamentos-y-productos-biologicos/desabastecimientos"
)
ALERTS_URL = "https://app.invima.gov.co/alertas/medicamentos-productos-biologicos"

DB_PATH = Path(__file__).parent.parent.parent / "phase2_data" / "invima.db"

REQUEST_TIMEOUT = 5      # seconds
POLITE_DELAY = 1.0       # seconds between requests

# Spanish month name → zero-padded month number
_MONTHS_ES = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _get(url: str, session: Optional[requests.Session] = None,
         encoding: str = "utf-8", params: Optional[dict] = None) -> requests.Response:
    """GET with 1 retry and explicit UTF-8 encoding assignment."""
    s = session or _session()
    for attempt in range(2):
        try:
            resp = s.get(url, timeout=REQUEST_TIMEOUT, params=params)
            resp.raise_for_status()
            resp.encoding = encoding
            return resp
        except requests.RequestException as exc:
            if attempt == 0:
                logger.warning("Retry after error on %s: %s", url, exc)
                time.sleep(POLITE_DELAY)
            else:
                raise
    raise RuntimeError("Unreachable")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS invima_shortages (
            record_hash                  TEXT PRIMARY KEY,
            producto                     TEXT,
            principio_activo             TEXT,
            titular_registro             TEXT,
            registro_sanitario           TEXT,
            fecha_notificacion           TEXT,
            tipo                         TEXT,
            motivo                       TEXT,
            fecha_normalizacion_estimada TEXT,
            scraped_at                   TEXT,
            raw_html                     TEXT
        );

        CREATE TABLE IF NOT EXISTS invima_alerts (
            alert_hash       TEXT PRIMARY KEY,
            fecha            TEXT,
            titulo           TEXT,
            tipo_alerta      TEXT,
            descripcion_breve TEXT,
            detail_url       TEXT,
            scraped_at       TEXT
        );
    """)
    conn.commit()


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    _init_db(conn)
    return conn


# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------

def _sha1(*parts: str) -> str:
    blob = "|".join(p.strip().lower() for p in parts)
    return hashlib.sha1(blob.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# Scraper 1 — Desabastecimientos index (PDF-link harvest)
# ---------------------------------------------------------------------------

def fetch_desabastecimientos() -> list[dict]:
    """
    Scrape the INVIMA desabastecimientos index page.

    The shortage data at INVIMA is published exclusively as monthly PDF reports.
    This function harvests the index page to record which reports exist, their
    publication dates (from anchor text), and their download URLs.

    IMPORTANT DEVIATION FROM SPEC: principio_activo, titular_registro,
    registro_sanitario, motivo, fecha_normalizacion_estimada, and tipo are NOT
    available in the index HTML — they reside inside the PDFs. These fields are
    returned as empty strings. PDF parsing is out of scope for this sprint.
    The record_hash is computed on (producto, fecha_notificacion) so it remains
    stable across re-runs. See invima_scraper_notes.md for full discussion.

    Returns list of dicts with keys matching the invima_shortages schema:
        producto, principio_activo, titular_registro, registro_sanitario,
        fecha_notificacion, tipo, motivo, fecha_normalizacion_estimada,
        + extra: detail_url (download URL of the PDF)
    """
    try:
        resp = _get(SHORTAGES_URL, encoding="utf-8")
    except requests.RequestException as exc:
        logger.error("fetch_desabastecimientos: HTTP error: %s", exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    records = _parse_desabastecimientos_page(soup)
    logger.info("fetch_desabastecimientos: %d records parsed", len(records))
    return records


def _parse_desabastecimientos_page(soup: BeautifulSoup) -> list[dict]:
    """
    Parse the desabastecimientos index page.

    Looks for <a> tags whose href points to PDF files or /biblioteca/ paths
    and whose anchor text matches the pattern for monthly shortage reports.
    """
    records = []
    seen_hrefs: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        anchor = a.get_text(separator=" ", strip=True)

        # Only harvest links that look like shortage/availability report links
        anchor_lower = anchor.lower()
        if not (
            "abastecimiento" in anchor_lower
            or "desabastecimiento" in anchor_lower
            or "disponibilidad" in anchor_lower
        ):
            continue

        # Resolve relative URLs
        if href.startswith("http"):
            full_url = href
        elif href.startswith("/"):
            full_url = INVIMA_BASE + href
        else:
            full_url = INVIMA_BASE + "/" + href

        # Skip duplicates
        if full_url in seen_hrefs:
            continue
        seen_hrefs.add(full_url)

        fecha = _extract_date_from_anchor(anchor)
        tipo = _classify_report_tipo(anchor)

        records.append({
            "producto": anchor,
            "principio_activo": "",       # inside PDF — out of scope
            "titular_registro": "",       # inside PDF — out of scope
            "registro_sanitario": "",     # inside PDF — out of scope
            "fecha_notificacion": fecha,
            "tipo": tipo,
            "motivo": "",                 # inside PDF — out of scope
            "fecha_normalizacion_estimada": "",  # inside PDF — out of scope
            "detail_url": full_url,
        })

    return records


def _extract_date_from_anchor(anchor: str) -> str:
    """
    Extract YYYY-MM-DD from Spanish anchor text like
    'Listado ... - Marzo 2025' or '... febrero 2026'.

    Returns ISO date string (first day of the month) or empty string.
    """
    anchor_lower = anchor.lower()
    for month_name, month_num in _MONTHS_ES.items():
        if month_name in anchor_lower:
            m = re.search(r"\b(20\d{2})\b", anchor)
            if m:
                return f"{m.group(1)}-{month_num}-01"
    return ""


def _classify_report_tipo(anchor: str) -> str:
    """Classify report type from anchor text.

    Note: 'desabastecimiento' contains 'abastecimiento' as a substring, so
    naive `"abastecimiento" in lower` matches both. Use a negative lookbehind
    to detect the standalone 'abastecimiento' (not preceded by 'des').
    """
    lower = anchor.lower()
    has_desabastec = "desabastecimiento" in lower
    has_plain_abastec = bool(re.search(r"(?<!des)abastecimiento", lower))
    if has_desabastec and has_plain_abastec:
        return "abastecimiento_y_desabastecimiento"
    if has_desabastec:
        return "desabastecimiento"
    if "disponibilidad" in lower:
        return "disponibilidad"
    return "abastecimiento"


# ---------------------------------------------------------------------------
# Scraper 2 — Alertas Sanitarias (Medicamentos)
# ---------------------------------------------------------------------------

def fetch_alertas(max_pages: int = 5) -> list[dict]:
    """
    Scrape INVIMA safety alerts for medications from:
    https://app.invima.gov.co/alertas/medicamentos-productos-biologicos

    Paginated via ?page=N (0-indexed). Fetches up to max_pages pages.

    Returns list of dicts with keys:
        fecha, titulo, tipo_alerta, descripcion_breve, detail_url
    """
    alerts: list[dict] = []
    s = _session()

    for page_num in range(max_pages):
        params = {"page": page_num} if page_num > 0 else {}
        try:
            resp = _get(ALERTS_URL, session=s, encoding="utf-8",
                        params=params if params else None)
        except requests.RequestException as exc:
            logger.error("fetch_alertas page %d error: %s", page_num, exc)
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        page_alerts = _parse_alertas_page(soup)

        if not page_alerts:
            logger.debug("fetch_alertas: empty page %d, stopping", page_num)
            break

        # Duplicate-page guard: same first title as previous page → stop
        if alerts and page_alerts[0]["titulo"] == alerts[0]["titulo"]:
            logger.debug("fetch_alertas: duplicate page at %d, stopping", page_num)
            break

        alerts.extend(page_alerts)

        if page_num < max_pages - 1:
            time.sleep(POLITE_DELAY)

    logger.info("fetch_alertas: %d alerts parsed", len(alerts))
    return alerts


def _parse_alertas_page(soup: BeautifulSoup) -> list[dict]:
    """
    Parse one page of the INVIMA alerts listing.

    The page uses a <table> with columns: [icon/category], title, tipo_alerta,
    fecha, [ver link]. Falls back to scanning <a> tags if table not found.
    """
    alerts = []

    table = soup.find("table")
    if table:
        alerts = _parse_alertas_table(table)
    if not alerts:
        alerts = _parse_alertas_fallback(soup)

    return alerts


def _parse_alertas_table(table) -> list[dict]:
    """Parse alerts from an HTML table."""
    alerts = []
    rows = table.find_all("tr")
    header_skipped = False

    for tr in rows:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue

        texts = [c.get_text(separator=" ", strip=True) for c in cells]

        # Skip header row
        if not header_skipped:
            header_skipped = True
            joined = " ".join(texts).lower()
            if "titulo" in joined or "fecha" in joined or "tipo" in joined or "nombre" in joined:
                continue

        # Find anchor (detail link / PDF)
        detail_url = ""
        for cell in cells:
            a_tag = cell.find("a", href=True)
            if a_tag:
                href = a_tag["href"].strip()
                if href.startswith("http"):
                    detail_url = href
                elif href.startswith("/"):
                    detail_url = ALERTS_BASE + href
                else:
                    detail_url = ALERTS_BASE + "/" + href
                break

        # Column heuristics: table has variable layout; try to extract
        # fecha, titulo, tipo_alerta from whichever columns carry them
        fecha = ""
        titulo = ""
        tipo_alerta = ""

        for text in texts:
            # Date: YYYY-MM-DD or DD/MM/YYYY
            if not fecha:
                dm = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
                if dm:
                    fecha = dm.group(1)
                    continue
                dm2 = re.search(r"\b(\d{2}/\d{2}/20\d{2})\b", text)
                if dm2:
                    # Normalise to YYYY-MM-DD
                    parts = dm2.group(1).split("/")
                    fecha = f"{parts[2]}-{parts[1]}-{parts[0]}"
                    continue

            # Tipo: must be the canonical short label cell (≤30 chars, exact-ish match).
            # Long cells like "BEVACIZUMAB ... Retiro voluntario lote BV2024-001" contain
            # tipo keywords but are actually titles — do NOT consume them here.
            lower = text.lower().strip()
            canonical_tipos = {"alerta sanitaria", "informe de seguridad", "retiro", "comunicado"}
            if not tipo_alerta and len(text) <= 30 and lower in canonical_tipos:
                tipo_alerta = text
                continue

            # Titulo: longest non-date, non-tipo text
            if text and text != fecha and text != tipo_alerta:
                if len(text) > len(titulo):
                    titulo = text

        if not titulo and not fecha:
            continue

        alerts.append({
            "fecha": fecha,
            "titulo": titulo,
            "tipo_alerta": tipo_alerta,
            "descripcion_breve": "",   # not on index; in PDF
            "detail_url": detail_url,
        })

    return alerts


def _parse_alertas_fallback(soup: BeautifulSoup) -> list[dict]:
    """Fallback: scan <a> tags for PDF/alert links."""
    alerts = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        titulo = a.get_text(strip=True)
        if not titulo or len(titulo) < 5:
            continue
        if not (
            "alerta" in href.lower()
            or "alerta" in titulo.lower()
            or "informe" in titulo.lower()
            or ".pdf" in href.lower()
        ):
            continue

        detail_url = href if href.startswith("http") else ALERTS_BASE + ("" if href.startswith("/") else "/") + href

        # Try to find a date sibling
        fecha = ""
        parent = a.parent
        if parent:
            parent_text = parent.get_text(separator=" ", strip=True)
            dm = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", parent_text)
            if dm:
                fecha = dm.group(1)

        alerts.append({
            "fecha": fecha,
            "titulo": titulo,
            "tipo_alerta": "Alerta sanitaria",
            "descripcion_breve": "",
            "detail_url": detail_url,
        })
    return alerts


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _ingest_shortages(records: list[dict], conn: sqlite3.Connection) -> int:
    """Insert shortage records with deduplication. Returns count of new rows."""
    new = 0
    ts = datetime.utcnow().isoformat()
    for row in records:
        h = _sha1(row.get("producto", ""), row.get("fecha_notificacion", ""))
        try:
            conn.execute(
                "INSERT OR IGNORE INTO invima_shortages "
                "(record_hash, producto, principio_activo, titular_registro, "
                " registro_sanitario, fecha_notificacion, tipo, motivo, "
                " fecha_normalizacion_estimada, scraped_at, raw_html) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    h,
                    row.get("producto", ""),
                    row.get("principio_activo", ""),
                    row.get("titular_registro", ""),
                    row.get("registro_sanitario", ""),
                    row.get("fecha_notificacion", ""),
                    row.get("tipo", ""),
                    row.get("motivo", ""),
                    row.get("fecha_normalizacion_estimada", ""),
                    ts,
                    row.get("detail_url", ""),  # store PDF URL in raw_html column
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                new += 1
        except sqlite3.Error as exc:
            logger.error("DB insert shortage: %s", exc)
    conn.commit()
    return new


def _ingest_alerts(alerts: list[dict], conn: sqlite3.Connection) -> int:
    """Insert alert rows with deduplication. Returns count of new rows."""
    new = 0
    ts = datetime.utcnow().isoformat()
    for alert in alerts:
        h = _sha1(alert.get("titulo", ""), alert.get("fecha", ""))
        try:
            conn.execute(
                "INSERT OR IGNORE INTO invima_alerts "
                "(alert_hash, fecha, titulo, tipo_alerta, descripcion_breve, "
                " detail_url, scraped_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    h,
                    alert.get("fecha", ""),
                    alert.get("titulo", ""),
                    alert.get("tipo_alerta", ""),
                    alert.get("descripcion_breve", ""),
                    alert.get("detail_url", ""),
                    ts,
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                new += 1
        except sqlite3.Error as exc:
            logger.error("DB insert alert: %s", exc)
    conn.commit()
    return new


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_daily_cycle() -> dict:
    """
    Orchestrate daily INVIMA data collection.

    Fetches: desabastecimientos index + alerts (medicamentos).
    Persists to SQLite with deduplication.

    Returns:
        dict with keys: shortages_new, alerts_new, errors
    """
    errors: list[str] = []
    result = {
        "shortages_new": 0,
        "alerts_new": 0,
        "errors": errors,
    }

    conn = _get_conn()

    # 1. Shortage index
    try:
        shortages = fetch_desabastecimientos()
        time.sleep(POLITE_DELAY)
        result["shortages_new"] = _ingest_shortages(shortages, conn)
        logger.info("Daily cycle: %d new shortages", result["shortages_new"])
    except Exception as exc:
        msg = f"desabastecimientos: {exc}"
        logger.error(msg)
        errors.append(msg)

    # 2. Alerts
    try:
        alerts = fetch_alertas(max_pages=5)
        result["alerts_new"] = _ingest_alerts(alerts, conn)
        logger.info("Daily cycle: %d new alerts", result["alerts_new"])
    except Exception as exc:
        msg = f"alertas: {exc}"
        logger.error(msg)
        errors.append(msg)

    conn.close()
    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run_daily_cycle(), indent=2))
