"""
anmat_scraper.py — Daily scraper for three ANMAT data streams.

Endpoints:
  - Shortage list (Listado_Faltantes): Latin-1 / Windows-1252 legacy ASP HTML table
  - Alerts archive (alertas_medicamentos): Latin-1 HTML, reverse-chronological
  - Boletín Oficial Rubro 5006: UTF-8, ANMAT Disposiciones for a given date

Polite scraping: 1 req/sec, 5s timeout, 1 retry, descriptive User-Agent.
No Selenium/Playwright. No PDF download (sprint constraint).

Usage:
    from phase2_realtime.data_ingestion.anmat_scraper import run_daily_cycle
    result = run_daily_cycle()
"""

import hashlib
import logging
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

SHORTAGE_URL = "http://www.anmat.gob.ar/listados/Listado_Faltantes.asp"
ALERTS_URL = "http://www.anmat.gob.ar/alertas_medicamentos.asp"
BOLETIN_URL = "https://www.boletinoficial.gob.ar/seccion/primera/"

ANMAT_BASE = "http://www.anmat.gob.ar"

DB_PATH = Path(__file__).parent.parent.parent / "phase2_data" / "anmat.db"

REQUEST_TIMEOUT = 5       # seconds; hard timeout per request
POLITE_DELAY   = 1.0      # seconds between requests


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _get(url: str, session: Optional[requests.Session] = None,
         encoding: str = "latin-1", params: Optional[dict] = None) -> requests.Response:
    """GET with 1 retry and explicit encoding assignment."""
    s = session or _session()
    for attempt in range(2):
        try:
            resp = s.get(url, timeout=REQUEST_TIMEOUT, params=params)
            resp.raise_for_status()
            resp.encoding = encoding   # override auto-detected; critical for ASP pages
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
        CREATE TABLE IF NOT EXISTS anmat_shortages (
            record_hash         TEXT PRIMARY KEY,
            producto            TEXT,
            ifa                 TEXT,
            laboratorio         TEXT,
            certificado         TEXT,
            fecha_notificacion  TEXT,
            estado              TEXT,
            motivo              TEXT,
            fecha_normalizacion TEXT,
            scraped_at          TEXT,
            raw_html            TEXT
        );

        CREATE TABLE IF NOT EXISTS anmat_alerts (
            alert_hash  TEXT PRIMARY KEY,
            fecha       TEXT,
            titulo      TEXT,
            descripcion TEXT,
            pdf_url     TEXT,
            scraped_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS anmat_dispositions (
            disposition_id TEXT PRIMARY KEY,
            fecha          TEXT,
            sumario        TEXT,
            detalle_url    TEXT,
            scraped_at     TEXT
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
# Scraper 1 — Shortage list
# ---------------------------------------------------------------------------

def fetch_shortage_list() -> list[dict]:
    """
    Scrape http://www.anmat.gob.ar/listados/Listado_Faltantes.asp

    Returns list of dicts with keys:
        producto, ifa, laboratorio, certificado, fecha_notificacion,
        estado, motivo, fecha_normalizacion
    """
    resp = _get(SHORTAGE_URL, encoding="latin-1")
    soup = BeautifulSoup(resp.text, "html.parser")

    rows = []
    table = soup.find("table")
    if table is None:
        logger.warning("fetch_shortage_list: no <table> found at %s", SHORTAGE_URL)
        return rows

    headers: list[str] = []
    expected = [
        "producto", "ifa", "laboratorio", "certificado",
        "fecha_notificacion", "estado", "motivo", "fecha_normalizacion",
    ]

    trs = table.find_all("tr")
    for tr in trs:
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        texts = [c.get_text(separator=" ", strip=True) for c in cells]

        # Detect header row heuristically (first non-empty row or row containing "Producto")
        if not headers:
            lower = [t.lower() for t in texts]
            if any("producto" in l or "ifa" in l or "laboratorio" in l for l in lower):
                # Normalise header names to expected keys
                headers = _normalise_headers(texts)
                continue
            elif all(t == "" for t in texts):
                continue
            else:
                # No recognisable header yet — skip
                continue

        if len(texts) < len(headers):
            texts += [""] * (len(headers) - len(texts))
        row = dict(zip(headers, texts))

        # Ensure all expected fields present
        for key in expected:
            row.setdefault(key, "")

        rows.append(row)

    logger.info("fetch_shortage_list: %d rows parsed", len(rows))
    return rows


def _normalise_headers(raw: list[str]) -> list[str]:
    """Map Spanish column headers to canonical snake_case keys."""
    mapping = {
        "producto": "producto",
        "ifa": "ifa",
        "laboratorio": "laboratorio",
        "certificado": "certificado",
        "fecha de notificacion": "fecha_notificacion",
        "fecha notificacion": "fecha_notificacion",
        "notificacion": "fecha_notificacion",
        "estado": "estado",
        "motivo": "motivo",
        "fecha estimada de normalizacion": "fecha_normalizacion",
        "fecha normalizacion": "fecha_normalizacion",
        "normalizacion": "fecha_normalizacion",
    }
    result = []
    for h in raw:
        key = h.strip().lower()
        # Remove accents for matching
        key = (key.replace("á", "a").replace("é", "e").replace("í", "i")
                   .replace("ó", "o").replace("ú", "u").replace("ó", "o")
                   .replace("ñ", "n"))
        matched = mapping.get(key, key.replace(" ", "_"))
        result.append(matched)
    return result


# ---------------------------------------------------------------------------
# Scraper 2 — Alerts archive
# ---------------------------------------------------------------------------

def fetch_alerts_archive(max_pages: int = 5) -> list[dict]:
    """
    Scrape http://www.anmat.gob.ar/alertas_medicamentos.asp

    Returns list of dicts with keys:
        fecha, titulo, descripcion, pdf_url

    PDFs are NOT downloaded — only URLs are stored.
    """
    alerts: list[dict] = []
    s = _session()

    for page in range(max_pages):
        # The ANMAT alerts page is single-page paginated via a POST/GET param.
        # Try page param; if site returns same content, break.
        params = {}
        if page > 0:
            params["pagina"] = page + 1

        try:
            resp = _get(ALERTS_URL, session=s, encoding="latin-1",
                        params=params if page > 0 else None)
        except requests.RequestException as exc:
            logger.error("fetch_alerts_archive page %d error: %s", page, exc)
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        page_alerts = _parse_alerts_page(soup)

        if not page_alerts:
            break

        # Detect duplicate page (site served same first page for all params)
        if page > 0 and page_alerts and page_alerts[0]["titulo"] == alerts[0]["titulo"]:
            logger.debug("fetch_alerts_archive: duplicate page detected at page %d, stopping", page)
            break

        alerts.extend(page_alerts)

        if page < max_pages - 1:
            time.sleep(POLITE_DELAY)

    logger.info("fetch_alerts_archive: %d alerts parsed", len(alerts))
    return alerts


def _parse_alerts_page(soup: BeautifulSoup) -> list[dict]:
    """Extract alert rows from a parsed alerts page."""
    alerts = []

    # ANMAT alerts page structure: table rows, each with date, title/link
    table = soup.find("table")
    if table is None:
        # Fallback: look for list items or div-based layout
        return _parse_alerts_list_fallback(soup)

    trs = table.find_all("tr")
    header_skipped = False
    for tr in trs:
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue

        # First row is often header
        if not header_skipped:
            header_text = cells[0].get_text(strip=True).lower()
            if "fecha" in header_text or "date" in header_text:
                header_skipped = True
                continue
            header_skipped = True  # skip regardless if first

        fecha = cells[0].get_text(strip=True)

        # Find link in remaining cells
        link_cell = cells[1] if len(cells) > 1 else cells[0]
        a_tag = link_cell.find("a")
        titulo = a_tag.get_text(strip=True) if a_tag else link_cell.get_text(strip=True)
        href = a_tag.get("href", "") if a_tag else ""

        # Build absolute PDF URL
        pdf_url = ""
        if href:
            if href.lower().startswith("http"):
                pdf_url = href
            elif href.startswith("/"):
                pdf_url = ANMAT_BASE + href
            else:
                pdf_url = ANMAT_BASE + "/" + href

        descripcion = cells[2].get_text(strip=True) if len(cells) > 2 else ""

        if titulo:
            alerts.append({
                "fecha": fecha,
                "titulo": titulo,
                "descripcion": descripcion,
                "pdf_url": pdf_url,
            })

    return alerts


def _parse_alerts_list_fallback(soup: BeautifulSoup) -> list[dict]:
    """Fallback parser if alerts page uses non-table layout."""
    alerts = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/comunicados/" not in href.lower() and ".pdf" not in href.lower():
            continue
        titulo = a.get_text(strip=True)
        if not titulo:
            continue
        # Try to find a sibling date
        parent = a.parent
        fecha = ""
        if parent:
            text = parent.get_text(separator="|", strip=True)
            parts = text.split("|")
            for p in parts:
                if "/" in p and any(c.isdigit() for c in p):
                    fecha = p.strip()
                    break

        pdf_url = href if href.startswith("http") else ANMAT_BASE + ("" if href.startswith("/") else "/") + href
        alerts.append({
            "fecha": fecha,
            "titulo": titulo,
            "descripcion": "",
            "pdf_url": pdf_url,
        })
    return alerts


# ---------------------------------------------------------------------------
# Scraper 3 — Boletín Oficial Rubro 5006
# ---------------------------------------------------------------------------

def fetch_boletin_oficial(date_yyyymmdd: str) -> list[dict]:
    """
    Query https://www.boletinoficial.gob.ar/seccion/primera/?rubro=5006

    Finds ANMAT Disposiciones for a given date.

    Args:
        date_yyyymmdd: e.g. "20250606"

    Returns list of dicts with keys:
        numero_disposicion, fecha, sumario, detalle_url
    """
    params = {
        "rubro": "5006",
        "fecha": date_yyyymmdd,
    }
    try:
        resp = _get(BOLETIN_URL, encoding="utf-8", params=params)
    except requests.RequestException as exc:
        logger.error("fetch_boletin_oficial error for %s: %s", date_yyyymmdd, exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    dispositions = _parse_boletin_page(soup, date_yyyymmdd)

    logger.info("fetch_boletin_oficial(%s): %d dispositions", date_yyyymmdd, len(dispositions))
    return dispositions


def _parse_boletin_page(soup: BeautifulSoup, fecha: str) -> list[dict]:
    """
    Parse Boletín Oficial listing for ANMAT Disposiciones.

    The Boletín Oficial page lists disposiciones as rows/items with:
      - Número (e.g. "3865/2025")
      - Sumario / title text
      - Link to detail page
    """
    dispositions = []
    BOLETIN_BASE = "https://www.boletinoficial.gob.ar"

    # The Boletín Oficial renders aviso items in <section> or <article> tags,
    # or in a structured table. Try multiple strategies.

    # Strategy A: look for aviso/item containers
    aviso_containers = (
        soup.find_all("div", class_=lambda c: c and "aviso" in c.lower())
        or soup.find_all("article")
        or soup.find_all("li", class_=lambda c: c and "aviso" in c.lower())
    )

    for item in aviso_containers:
        text = item.get_text(separator=" ", strip=True)
        numero = _extract_disposicion_number(text)
        if not numero:
            continue
        sumario = text[:500]  # cap at 500 chars
        a_tag = item.find("a", href=True)
        detalle_url = ""
        if a_tag:
            href = a_tag["href"]
            detalle_url = href if href.startswith("http") else BOLETIN_BASE + href

        dispositions.append({
            "numero_disposicion": numero,
            "fecha": fecha,
            "sumario": sumario,
            "detalle_url": detalle_url,
        })

    if dispositions:
        return dispositions

    # Strategy B: scan all <a> tags that look like disposicion detail links
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "detalleAviso" not in href and "aviso" not in href.lower():
            continue
        title_text = a.get_text(separator=" ", strip=True)
        parent_text = ""
        if a.parent:
            parent_text = a.parent.get_text(separator=" ", strip=True)
        combined = parent_text or title_text
        numero = _extract_disposicion_number(combined)
        if not numero:
            # Use a fallback id from the URL itself
            numero = _extract_disposicion_from_url(href)
        if not numero:
            continue
        detalle_url = href if href.startswith("http") else BOLETIN_BASE + href
        dispositions.append({
            "numero_disposicion": numero,
            "fecha": fecha,
            "sumario": combined[:500],
            "detalle_url": detalle_url,
        })

    # Deduplicate by numero_disposicion
    seen: set[str] = set()
    unique = []
    for d in dispositions:
        if d["numero_disposicion"] not in seen:
            seen.add(d["numero_disposicion"])
            unique.append(d)

    return unique


def _extract_disposicion_number(text: str) -> str:
    """Extract Disposición number like '3865/2025' from text."""
    import re
    # Patterns: "Disposición 3865/2025", "DISPOSICION 3865/2025", "Disp. 3865/2025", "3865/2025"
    # IGNORECASE so all-caps headers like "DISPOSICION" match.
    patterns = [
        r"disposici[oó]n\s+n?[°ºo]?\s*(\d{1,6}/\d{4})",
        r"disp\.?\s+n?[°ºo]?\s*(\d{1,6}/\d{4})",
        r"\bdisp(?:osici[oó]n)?\s*n?[°º]?\s*(\d{1,6}/\d{4})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


def _extract_disposicion_from_url(url: str) -> str:
    """Try to extract an aviso ID from a Boletín Oficial detail URL."""
    import re
    # e.g. /detalleAviso/primera/326644/20250606
    m = re.search(r"/detalleAviso/[^/]+/(\d+)/(\d{8})", url)
    if m:
        return f"aviso_{m.group(1)}"
    return ""


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _ingest_shortages(rows: list[dict], conn: sqlite3.Connection) -> int:
    """Insert shortage rows with deduplication. Returns count of new rows."""
    new = 0
    ts = datetime.utcnow().isoformat()
    for row in rows:
        h = _sha1(
            row.get("producto", ""),
            row.get("ifa", ""),
            row.get("certificado", ""),
        )
        try:
            conn.execute(
                "INSERT OR IGNORE INTO anmat_shortages "
                "(record_hash, producto, ifa, laboratorio, certificado, "
                " fecha_notificacion, estado, motivo, fecha_normalizacion, scraped_at, raw_html) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    h,
                    row.get("producto", ""),
                    row.get("ifa", ""),
                    row.get("laboratorio", ""),
                    row.get("certificado", ""),
                    row.get("fecha_notificacion", ""),
                    row.get("estado", ""),
                    row.get("motivo", ""),
                    row.get("fecha_normalizacion", ""),
                    ts,
                    "",   # raw_html not stored to keep DB lean
                ),
            )
            if conn.execute(
                "SELECT changes()"
            ).fetchone()[0]:
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
                "INSERT OR IGNORE INTO anmat_alerts "
                "(alert_hash, fecha, titulo, descripcion, pdf_url, scraped_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    h,
                    alert.get("fecha", ""),
                    alert.get("titulo", ""),
                    alert.get("descripcion", ""),
                    alert.get("pdf_url", ""),
                    ts,
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                new += 1
        except sqlite3.Error as exc:
            logger.error("DB insert alert: %s", exc)
    conn.commit()
    return new


def _ingest_dispositions(dispositions: list[dict], conn: sqlite3.Connection) -> int:
    """Insert Boletín dispositions with deduplication. Returns count of new rows."""
    new = 0
    ts = datetime.utcnow().isoformat()
    for d in dispositions:
        disp_id = d.get("numero_disposicion", "")
        if not disp_id:
            continue
        try:
            conn.execute(
                "INSERT OR IGNORE INTO anmat_dispositions "
                "(disposition_id, fecha, sumario, detalle_url, scraped_at) "
                "VALUES (?,?,?,?,?)",
                (
                    disp_id,
                    d.get("fecha", ""),
                    d.get("sumario", ""),
                    d.get("detalle_url", ""),
                    ts,
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                new += 1
        except sqlite3.Error as exc:
            logger.error("DB insert disposition: %s", exc)
    conn.commit()
    return new


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_daily_cycle() -> dict:
    """
    Orchestrate daily ANMAT data collection.

    Fetches: shortage_list + alerts archive + today's Boletín Oficial.
    Persists to SQLite with deduplication.

    Returns:
        dict with keys: shortages_new, alerts_new, dispositions_new, errors
    """
    errors: list[str] = []
    result = {
        "shortages_new": 0,
        "alerts_new": 0,
        "dispositions_new": 0,
        "errors": errors,
    }

    conn = _get_conn()
    today = datetime.utcnow().strftime("%Y%m%d")

    # 1. Shortage list
    try:
        shortages = fetch_shortage_list()
        time.sleep(POLITE_DELAY)
        result["shortages_new"] = _ingest_shortages(shortages, conn)
        logger.info("Daily cycle: %d new shortages", result["shortages_new"])
    except Exception as exc:
        msg = f"shortage_list: {exc}"
        logger.error(msg)
        errors.append(msg)

    # 2. Alerts archive
    try:
        alerts = fetch_alerts_archive(max_pages=5)
        time.sleep(POLITE_DELAY)
        result["alerts_new"] = _ingest_alerts(alerts, conn)
        logger.info("Daily cycle: %d new alerts", result["alerts_new"])
    except Exception as exc:
        msg = f"alerts_archive: {exc}"
        logger.error(msg)
        errors.append(msg)

    # 3. Boletín Oficial — today
    try:
        dispositions = fetch_boletin_oficial(today)
        result["dispositions_new"] = _ingest_dispositions(dispositions, conn)
        logger.info("Daily cycle: %d new dispositions", result["dispositions_new"])
    except Exception as exc:
        msg = f"boletin_oficial: {exc}"
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
