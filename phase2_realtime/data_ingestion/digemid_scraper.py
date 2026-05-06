"""
digemid_scraper.py — Scraper for DIGEMID (Peru) pharmaceutical data streams.

DIGEMID = Dirección General de Medicamentos, Insumos y Drogas
Peru's FDA equivalent. Website: https://www.digemid.minsa.gob.pe

--------------------------------------------------------------------
ARCHITECTURE NOTES (read before modifying)
--------------------------------------------------------------------

This module targets two publicly accessible, JavaScript-free endpoints:

1. DISCONTINUATIONS registry — full-table static HTML:
   https://serviciosweb-digemid.minsa.gob.pe/DiscontinuidadMedicamentos/Discontinuados
   - 400+ rows of temporal/definitive discontinuations of fabrication or import
   - Columns: Código, Tipo, Nombre Producto, IFA, Concentración, Forma Farmacéutica,
     Razón Social, Categoría, Tipo de discontinuación, Situación, Motivos,
     Fecha estimada de inicio/fin, Fecha de reporte
   - The filter form appears to require POST; the full table loads without it.
   - Strategy: fetch the full unfiltered table and filter in Python by drug_name.

2. ALERTS feed — paginated static WordPress-style HTML:
   https://www.digemid.minsa.gob.pe/webDigemid/publicaciones/alertas-modificaciones/
   - Pagination via /page/N/ suffix; 184+ pages as of 2026-05.
   - Fields extracted per alert: titulo, fecha, categoria, detail_url, pdf_url.
   - We scrape only the first max_pages pages (default 3) per run.

WHAT DOES NOT WORK (and why):
- Registro Sanitario search (/rsProductosFarmaceuticos/): returns HTTP 403
  for automated requests. Cannot scrape without Selenium/Playwright session.
  The public URL requires an active browser session. No fallback available.
- fetch_digemid_registrations() is implemented as the required interface
  function but ALWAYS returns an empty list with an explicit warning
  because this specific endpoint is access-controlled.
  → Use fetch_discontinuations() + fetch_alerts() for actionable data.

JAVASCRIPT RENDERING: NOT required for either working endpoint.
The pages are server-rendered static HTML. requests + BeautifulSoup suffice.

POLITE SCRAPING:
- 1 req/sec minimum delay between pages
- 10s timeout (DIGEMID servers respond slowly)
- 1 retry per request
- Descriptive User-Agent

Usage:
    from phase2_realtime.data_ingestion.digemid_scraper import (
        fetch_digemid_registrations,   # always empty — see notes above
        fetch_discontinuations,
        fetch_alerts,
        run_daily_cycle,
    )
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

DIGEMID_BASE = "https://www.digemid.minsa.gob.pe"
SERVICIOS_BASE = "https://serviciosweb-digemid.minsa.gob.pe"

# Registro Sanitario search — 403 for automated requests; kept for documentation.
RS_URL = "https://www.digemid.minsa.gob.pe/rsProductosFarmaceuticos/"

# Discontinuations: full static table, no JS required.
DISCONTINUATIONS_URL = (
    "https://serviciosweb-digemid.minsa.gob.pe"
    "/DiscontinuidadMedicamentos/Discontinuados"
)

# Alerts archive.
ALERTS_BASE_URL = (
    "https://www.digemid.minsa.gob.pe"
    "/webDigemid/publicaciones/alertas-modificaciones/"
)

# Availability reports index (monthly Excel files per region).
AVAILABILITY_INDEX_URL = (
    "https://www.digemid.minsa.gob.pe"
    "/webDigemid/publicaciones/disponibilidad-de-productos-farmaceuticos/"
)

DB_PATH = Path(__file__).parent.parent.parent / "phase2_data" / "digemid.db"

REQUEST_TIMEOUT = 10     # seconds; DIGEMID servers respond slowly
POLITE_DELAY = 1.0       # seconds between requests

# Drugs of interest for OncoSupply (Spanish INN names as they appear in DIGEMID)
DRUGS_OF_INTEREST = ["cisplatino", "carboplatino", "doxorrubicina", "trastuzumab"]

# Mapping from English names the caller might pass to Spanish DIGEMID INN names
_DRUG_NAME_MAP = {
    "cisplatin":     "cisplatino",
    "carboplatin":   "carboplatino",
    "doxorubicin":   "doxorrubicina",
    "trastuzumab":   "trastuzumab",
    # Spanish variants already normalised
    "cisplatino":    "cisplatino",
    "carboplatino":  "carboplatino",
    "doxorrubicina": "doxorrubicina",
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _get(
    url: str,
    session: Optional[requests.Session] = None,
    encoding: str = "utf-8",
    params: Optional[dict] = None,
) -> requests.Response:
    """GET with 1 retry, explicit encoding, and polite delay on retry."""
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
        CREATE TABLE IF NOT EXISTS digemid_discontinuations (
            record_hash         TEXT PRIMARY KEY,
            codigo              TEXT,
            tipo                TEXT,
            nombre_producto     TEXT,
            ifa                 TEXT,
            concentracion       TEXT,
            forma_farmaceutica  TEXT,
            razon_social        TEXT,
            categoria           TEXT,
            tipo_discontinuacion TEXT,
            situacion           TEXT,
            motivos             TEXT,
            fecha_inicio_est    TEXT,
            fecha_fin_est       TEXT,
            fecha_reporte       TEXT,
            scraped_at          TEXT
        );

        CREATE TABLE IF NOT EXISTS digemid_alerts (
            alert_hash  TEXT PRIMARY KEY,
            titulo      TEXT,
            fecha       TEXT,
            categoria   TEXT,
            detail_url  TEXT,
            pdf_url     TEXT,
            scraped_at  TEXT
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
# Public interface — fetch_digemid_registrations
# (Required by task spec; blocked by HTTP 403 at RS endpoint)
# ---------------------------------------------------------------------------

def fetch_digemid_registrations(drug_name: str) -> list[dict]:
    """
    Attempt to fetch drug registration records from DIGEMID's Registro Sanitario
    portal for the given drug name.

    IMPORTANT: This function ALWAYS returns an empty list.

    The Registro Sanitario search endpoint (/rsProductosFarmaceuticos/) returns
    HTTP 403 for all automated requests. The portal requires an active browser
    session and cannot be accessed without Selenium or Playwright. No static-HTML
    fallback is available for registration status, approval dates, or holder data.

    For actionable drug-level data from DIGEMID, use:
        - fetch_discontinuations(drug_name)  — discontinuation/reactivation events
        - fetch_alerts(max_pages=3)          — safety alerts and market withdrawals

    Args:
        drug_name: Drug name in English or Spanish (e.g. "cisplatin", "cisplatino").

    Returns:
        [] — always empty; warning is logged.

    Expected schema if the endpoint were accessible:
        drug_name, registro_sanitario, status, fecha_vencimiento, fabricante
    """
    spanish_name = _DRUG_NAME_MAP.get(drug_name.lower().strip(), drug_name)
    logger.warning(
        "fetch_digemid_registrations('%s'): RS endpoint (%s) returns HTTP 403 "
        "for automated requests. A browser session (Selenium/Playwright) is "
        "required. Returning empty list. Use fetch_discontinuations() instead.",
        spanish_name,
        RS_URL,
    )
    print(
        f"[DIGEMID] WARNING: Registro Sanitario search is blocked for automated "
        f"access (HTTP 403). Cannot retrieve registration records for "
        f"'{spanish_name}'. Use fetch_discontinuations() for supply signal data."
    )
    return []


# ---------------------------------------------------------------------------
# Scraper 1 — Discontinuations registry
# ---------------------------------------------------------------------------

def fetch_discontinuations(drug_name: Optional[str] = None) -> list[dict]:
    """
    Scrape the DIGEMID discontinuations registry.

    Fetches the full table of temporal and definitive discontinuations of
    fabrication or import of medicines and biological products. Filters
    results in Python by drug_name (IFA or Nombre Producto).

    URL: https://serviciosweb-digemid.minsa.gob.pe/DiscontinuidadMedicamentos/Discontinuados

    The page returns a complete static HTML table (400+ rows) without requiring
    JavaScript rendering. No POST needed to load the full dataset.

    Args:
        drug_name: Optional filter — English or Spanish drug name.
                   If None, all records are returned.

    Returns:
        List of dicts with keys:
            codigo, tipo, nombre_producto, ifa, concentracion,
            forma_farmaceutica, razon_social, categoria, tipo_discontinuacion,
            situacion, motivos, fecha_inicio_est, fecha_fin_est, fecha_reporte
    """
    try:
        resp = _get(DISCONTINUATIONS_URL, encoding="utf-8")
    except requests.RequestException as exc:
        logger.error("fetch_discontinuations: HTTP error: %s", exc)
        print(f"[DIGEMID] ERROR fetching discontinuations: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    records = _parse_discontinuations_table(soup)
    logger.info("fetch_discontinuations: %d total records parsed", len(records))
    print(f"[DIGEMID] Discontinuations: {len(records)} total records fetched.")

    if drug_name:
        spanish_name = _DRUG_NAME_MAP.get(drug_name.lower().strip(), drug_name)
        query = spanish_name.lower()
        records = [
            r for r in records
            if query in r.get("nombre_producto", "").lower()
            or query in r.get("ifa", "").lower()
        ]
        logger.info(
            "fetch_discontinuations: %d records match '%s'", len(records), drug_name
        )
        print(f"[DIGEMID] Discontinuations matching '{drug_name}': {len(records)} records.")

    return records


def _parse_discontinuations_table(soup: BeautifulSoup) -> list[dict]:
    """
    Parse the DIGEMID discontinuations HTML table.

    Expected column order (may vary; we fall back to positional mapping):
        Item, Código, Tipo, Nombre Producto, IFA, Concentración,
        Forma Farmacéutica, Razón Social, Categoría, Tipo de discontinuación,
        Situación del último reporte, Motivos de la discontinuación,
        Fecha estimada de inicio, Fecha estimada de fin, Fecha de reporte
    """
    # Column name → canonical key mapping
    _COL_MAP = {
        "item":                         "item",
        "código":                       "codigo",
        "codigo":                       "codigo",
        "tipo":                         "tipo",
        "nombre producto":              "nombre_producto",
        "ifa":                          "ifa",
        "concentración":                "concentracion",
        "concentracion":                "concentracion",
        "forma farmacéutica":           "forma_farmaceutica",
        "forma farmaceutica":           "forma_farmaceutica",
        "razón social":                 "razon_social",
        "razon social":                 "razon_social",
        "razón social del establecimiento": "razon_social",
        "categoría del establecimiento": "categoria",
        "categoria del establecimiento": "categoria",
        "tipo de discontinuación":      "tipo_discontinuacion",
        "tipo de discontinuacion":      "tipo_discontinuacion",
        "situación del último reporte": "situacion",
        "situacion del ultimo reporte": "situacion",
        "motivos de la discontinuación": "motivos",
        "motivos de la discontinuacion": "motivos",
        "fecha estimada de inicio":     "fecha_inicio_est",
        "fecha estimada de fin":        "fecha_fin_est",
        "fecha de reporte":             "fecha_reporte",
    }

    def _normalise_header(raw: str) -> str:
        """Strip accents and lower for lookup."""
        key = raw.strip().lower()
        key = (key.replace("á", "a").replace("é", "e").replace("í", "i")
                   .replace("ó", "o").replace("ú", "u").replace("ñ", "n"))
        return _COL_MAP.get(key, key.replace(" ", "_"))

    # The DIGEMID page has two tables: table[0] is the filter form, table[1] is
    # the data table. We select the first table whose header row contains drug-
    # specific column names. This is resilient to layout changes that add more
    # form tables above the data table.
    all_tables = soup.find_all("table")
    table = None
    for candidate in all_tables:
        candidate_rows = candidate.find_all("tr")
        for tr in candidate_rows[:3]:  # check only the first few rows for a header
            cells = tr.find_all(["th", "td"])
            if not cells:
                continue
            joined = " ".join(c.get_text(strip=True) for c in cells).lower()
            if "ifa" in joined and "producto" in joined:
                table = candidate
                break
        if table is not None:
            break

    if table is None:
        logger.warning(
            "_parse_discontinuations_table: data table not found among %d tables; "
            "trying div fallback", len(all_tables)
        )
        return _parse_discontinuations_div_fallback(soup)

    rows = table.find_all("tr")
    if not rows:
        logger.warning("_parse_discontinuations_table: table has no <tr> rows")
        return []

    # Detect header row
    headers: list[str] = []
    data_rows = []

    for tr in rows:
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        texts = [c.get_text(separator=" ", strip=True) for c in cells]

        if not headers:
            # Identify the header row: it must contain BOTH "ifa" and at least
            # one of the other structural column names. This prevents matching
            # title rows like "LISTADO DE MEDICAMENTOS Y PRODUCTOS" which contain
            # "producto" but not "ifa".
            lower_joined = " ".join(texts).lower()
            # Require multiple canonical column tokens to be present
            col_signals = sum([
                "ifa" in lower_joined,
                "nombre producto" in lower_joined,
                "código" in lower_joined or "codigo" in lower_joined,
                "tipo de discontinu" in lower_joined,
                "forma farmac" in lower_joined,
            ])
            if col_signals >= 2:
                headers = [_normalise_header(t) for t in texts]
                continue
            # Not the header row — skip silently
            continue

        data_rows.append(texts)

    if not headers:
        logger.warning(
            "_parse_discontinuations_table: could not identify header row; "
            "falling back to fixed positional mapping"
        )
        # Use positional fallback column names
        headers = [
            "item", "codigo", "tipo", "nombre_producto", "ifa",
            "concentracion", "forma_farmaceutica", "razon_social", "categoria",
            "tipo_discontinuacion", "situacion", "motivos",
            "fecha_inicio_est", "fecha_fin_est", "fecha_reporte",
        ]
        # Re-parse skipping first row as header
        table_rows = table.find_all("tr")
        data_rows = []
        for tr in table_rows[1:]:
            cells = tr.find_all("td")
            if cells:
                data_rows.append([c.get_text(separator=" ", strip=True) for c in cells])

    records = []
    expected_keys = [
        "codigo", "tipo", "nombre_producto", "ifa", "concentracion",
        "forma_farmaceutica", "razon_social", "categoria", "tipo_discontinuacion",
        "situacion", "motivos", "fecha_inicio_est", "fecha_fin_est", "fecha_reporte",
    ]
    for texts in data_rows:
        if len(texts) < len(headers):
            texts += [""] * (len(headers) - len(texts))
        row = dict(zip(headers, texts))
        # Ensure all expected keys are present
        for key in expected_keys:
            row.setdefault(key, "")
        # Drop the positional 'item' counter column if present
        row.pop("item", None)
        # Skip blank rows
        if not row.get("nombre_producto") and not row.get("ifa"):
            continue
        records.append(row)

    return records


def _parse_discontinuations_div_fallback(soup: BeautifulSoup) -> list[dict]:
    """
    Fallback parser if the DIGEMID discontinuations page does not render a
    standard <table>. This can happen if the server returns a partial page
    or if the layout changes.

    Returns an empty list with a warning rather than crashing.
    """
    logger.warning(
        "_parse_discontinuations_div_fallback: No <table> found. "
        "DIGEMID may have changed its page structure. Returning empty list."
    )
    print(
        "[DIGEMID] WARNING: Discontinuations page has no <table> element. "
        "The site layout may have changed. Manual inspection required."
    )
    return []


# ---------------------------------------------------------------------------
# Scraper 2 — Alerts feed
# ---------------------------------------------------------------------------

def fetch_alerts(max_pages: int = 3) -> list[dict]:
    """
    Scrape the DIGEMID alerts and modifications feed.

    URL pattern:
        Page 1: /webDigemid/publicaciones/alertas-modificaciones/
        Page N: /webDigemid/publicaciones/alertas-modificaciones/page/{N}/

    The site has 184+ pages of historical alerts (as of 2026-05).
    Default: fetch the 3 most recent pages (~30 alerts).

    Returns list of dicts with keys:
        titulo, fecha, categoria, detail_url, pdf_url
    """
    alerts: list[dict] = []
    s = _session()

    for page_num in range(1, max_pages + 1):
        if page_num == 1:
            url = ALERTS_BASE_URL
        else:
            url = f"{ALERTS_BASE_URL}page/{page_num}/"

        try:
            resp = _get(url, session=s, encoding="utf-8")
        except requests.RequestException as exc:
            logger.error("fetch_alerts page %d error: %s", page_num, exc)
            print(f"[DIGEMID] ERROR fetching alerts page {page_num}: {exc}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        page_alerts = _parse_alerts_page(soup)

        if not page_alerts:
            logger.debug("fetch_alerts: empty page %d, stopping", page_num)
            break

        # Duplicate-page guard
        if (
            alerts
            and page_alerts
            and page_alerts[0]["titulo"] == alerts[0]["titulo"]
        ):
            logger.debug("fetch_alerts: duplicate page at %d, stopping", page_num)
            break

        alerts.extend(page_alerts)
        logger.debug("fetch_alerts: page %d → %d alerts", page_num, len(page_alerts))

        if page_num < max_pages:
            time.sleep(POLITE_DELAY)

    logger.info("fetch_alerts: %d alerts total across %d pages", len(alerts), max_pages)
    print(f"[DIGEMID] Alerts: {len(alerts)} alerts fetched across up to {max_pages} pages.")
    return alerts


def _parse_alerts_page(soup: BeautifulSoup) -> list[dict]:
    """
    Parse one page of DIGEMID alerts.

    The DIGEMID alerts archive uses a WordPress-style layout:
    - Each alert is in an <article> or a <div class="post"> container
    - The title is in an <h2> or <h3> with an <a> tag
    - The date is in a <time> tag or a span with class containing "date"
    - Category tags are <a> elements linking to category pages
    - PDF links have href containing /Archivos/Alertas/
    """
    alerts = []

    # Strategy A: article/post containers
    containers = (
        soup.find_all("article")
        or soup.find_all("div", class_=lambda c: c and "post" in c.lower())
        or soup.find_all("div", class_=lambda c: c and "entry" in c.lower())
    )

    if containers:
        for item in containers:
            alert = _extract_alert_from_container(item)
            if alert and alert.get("titulo"):
                alerts.append(alert)

    if alerts:
        return alerts

    # Strategy B: scan all anchor tags for alert-like links
    alerts = _parse_alerts_link_fallback(soup)
    return alerts


def _extract_alert_from_container(container) -> dict:
    """Extract alert fields from a single article/post container element."""
    alert: dict = {
        "titulo": "",
        "fecha": "",
        "categoria": "",
        "detail_url": "",
        "pdf_url": "",
    }

    # Title: look for h1/h2/h3 with an anchor
    for tag in ["h1", "h2", "h3", "h4"]:
        heading = container.find(tag)
        if heading:
            a = heading.find("a", href=True)
            if a:
                alert["titulo"] = a.get_text(strip=True)
                href = a["href"].strip()
                alert["detail_url"] = (
                    href if href.startswith("http") else DIGEMID_BASE + href
                )
            else:
                alert["titulo"] = heading.get_text(strip=True)
            if alert["titulo"]:
                break

    # Date: prefer <time datetime="..."> attribute, else text
    time_tag = container.find("time")
    if time_tag:
        dt = time_tag.get("datetime", "")
        if dt:
            # ISO datetime → YYYY-MM-DD
            m = re.match(r"(\d{4}-\d{2}-\d{2})", dt)
            alert["fecha"] = m.group(1) if m else dt
        else:
            alert["fecha"] = time_tag.get_text(strip=True)
    else:
        # Fallback: look for a span/div with a date-like class
        for cls in ["date", "fecha", "published", "entry-date"]:
            date_el = container.find(
                True, class_=lambda c: c and cls in c.lower()
            )
            if date_el:
                raw = date_el.get_text(strip=True)
                # Attempt to parse DD/MM/YYYY or YYYY-MM-DD
                m = re.search(r"(\d{2})/(\d{2})/(\d{4})", raw)
                if m:
                    alert["fecha"] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
                else:
                    m2 = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
                    alert["fecha"] = m2.group(1) if m2 else raw
                break

    # Category: collect category anchor texts
    cats = []
    for a in container.find_all("a", href=True):
        href = a["href"]
        # Category links typically contain "/category/" or "/alertas-modificaciones/"
        if "/category/" in href or (
            "/alertas-modificaciones/" in href
            and "alertas-modificaciones/20" not in href  # exclude year-based archive links
        ):
            cat_text = a.get_text(strip=True)
            if cat_text and cat_text not in cats:
                cats.append(cat_text)
    alert["categoria"] = " | ".join(cats) if cats else ""

    # PDF link
    for a in container.find_all("a", href=True):
        href = a["href"]
        if "/Archivos/" in href and (
            ".pdf" in href.lower() or "Alerta" in href or "alert" in href.lower()
        ):
            alert["pdf_url"] = (
                href if href.startswith("http") else DIGEMID_BASE + href
            )
            break

    return alert


def _parse_alerts_link_fallback(soup: BeautifulSoup) -> list[dict]:
    """
    Fallback alert parser: scan all <a> tags for links that look like alert pages.
    Used when the page has no recognisable article/post containers.
    """
    alerts = []
    seen_urls: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        titulo = a.get_text(strip=True)

        # Must look like an alert page (year-based path) and have meaningful text
        if not (
            "/alertas-modificaciones/20" in href
            or "alerta" in href.lower()
            or "alerta" in titulo.lower()
        ):
            continue
        if len(titulo) < 8 or titulo in seen_urls:
            continue

        full_url = href if href.startswith("http") else DIGEMID_BASE + href
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Try to find a date nearby
        fecha = ""
        parent = a.parent
        if parent:
            parent_text = parent.get_text(separator=" ", strip=True)
            m = re.search(r"(\d{4}-\d{2}-\d{2})", parent_text)
            if m:
                fecha = m.group(1)
            else:
                m2 = re.search(r"(\d{2})/(\d{2})/(\d{4})", parent_text)
                if m2:
                    fecha = f"{m2.group(3)}-{m2.group(2)}-{m2.group(1)}"

        alerts.append({
            "titulo": titulo,
            "fecha": fecha,
            "categoria": "",
            "detail_url": full_url,
            "pdf_url": "",
        })

    return alerts


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _ingest_discontinuations(records: list[dict], conn: sqlite3.Connection) -> int:
    """Insert discontinuation records with deduplication. Returns new row count."""
    new = 0
    ts = datetime.utcnow().isoformat()
    for row in records:
        h = _sha1(
            row.get("codigo", ""),
            row.get("nombre_producto", ""),
            row.get("tipo_discontinuacion", ""),
            row.get("fecha_reporte", ""),
        )
        try:
            conn.execute(
                "INSERT OR IGNORE INTO digemid_discontinuations "
                "(record_hash, codigo, tipo, nombre_producto, ifa, concentracion, "
                " forma_farmaceutica, razon_social, categoria, tipo_discontinuacion, "
                " situacion, motivos, fecha_inicio_est, fecha_fin_est, "
                " fecha_reporte, scraped_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    h,
                    row.get("codigo", ""),
                    row.get("tipo", ""),
                    row.get("nombre_producto", ""),
                    row.get("ifa", ""),
                    row.get("concentracion", ""),
                    row.get("forma_farmaceutica", ""),
                    row.get("razon_social", ""),
                    row.get("categoria", ""),
                    row.get("tipo_discontinuacion", ""),
                    row.get("situacion", ""),
                    row.get("motivos", ""),
                    row.get("fecha_inicio_est", ""),
                    row.get("fecha_fin_est", ""),
                    row.get("fecha_reporte", ""),
                    ts,
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                new += 1
        except sqlite3.Error as exc:
            logger.error("DB insert discontinuation: %s", exc)
    conn.commit()
    return new


def _ingest_alerts(alerts: list[dict], conn: sqlite3.Connection) -> int:
    """Insert alert rows with deduplication. Returns new row count."""
    new = 0
    ts = datetime.utcnow().isoformat()
    for alert in alerts:
        h = _sha1(alert.get("titulo", ""), alert.get("fecha", ""))
        try:
            conn.execute(
                "INSERT OR IGNORE INTO digemid_alerts "
                "(alert_hash, titulo, fecha, categoria, detail_url, pdf_url, scraped_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    h,
                    alert.get("titulo", ""),
                    alert.get("fecha", ""),
                    alert.get("categoria", ""),
                    alert.get("detail_url", ""),
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


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_daily_cycle() -> dict:
    """
    Orchestrate daily DIGEMID data collection.

    Fetches:
    1. Full discontinuations table (all drugs) — filtered in-memory for drugs of interest.
    2. Alerts feed (most recent 3 pages).

    Persists to SQLite at phase2_data/digemid.db with deduplication.

    Returns:
        dict with keys: discontinuations_new, alerts_new, errors
    """
    errors: list[str] = []
    result = {
        "discontinuations_new": 0,
        "alerts_new": 0,
        "errors": errors,
    }

    conn = _get_conn()

    # 1. Discontinuations — fetch once, store all records (not just drugs of interest)
    # so the DB is useful for cross-drug analysis.
    try:
        print("[DIGEMID] Fetching discontinuations registry...")
        records = fetch_discontinuations(drug_name=None)
        time.sleep(POLITE_DELAY)
        result["discontinuations_new"] = _ingest_discontinuations(records, conn)
        logger.info(
            "Daily cycle: %d new discontinuations", result["discontinuations_new"]
        )
        print(
            f"[DIGEMID] {result['discontinuations_new']} new discontinuation records stored."
        )
    except Exception as exc:
        msg = f"discontinuations: {exc}"
        logger.error(msg)
        errors.append(msg)
        print(f"[DIGEMID] ERROR in discontinuations fetch: {exc}")

    # 2. Alerts feed — 3 most recent pages
    try:
        print("[DIGEMID] Fetching alerts feed...")
        alerts = fetch_alerts(max_pages=3)
        result["alerts_new"] = _ingest_alerts(alerts, conn)
        logger.info("Daily cycle: %d new alerts", result["alerts_new"])
        print(f"[DIGEMID] {result['alerts_new']} new alert records stored.")
    except Exception as exc:
        msg = f"alerts: {exc}"
        logger.error(msg)
        errors.append(msg)
        print(f"[DIGEMID] ERROR in alerts fetch: {exc}")

    conn.close()
    return result


# ---------------------------------------------------------------------------
# CLI entry point / smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    print("=" * 60)
    print("DIGEMID Scraper — Smoke Test")
    print("=" * 60)

    # Test 1: fetch_digemid_registrations — must return [] with a warning
    print("\n[TEST 1] fetch_digemid_registrations('cisplatino')")
    result = fetch_digemid_registrations("cisplatino")
    print(f"  → Returned {len(result)} records (expected 0 — endpoint blocked).")
    assert result == [], "Expected empty list from blocked RS endpoint"

    # Test 2: fetch_digemid_registrations with English name
    print("\n[TEST 2] fetch_digemid_registrations('cisplatin')  [English alias]")
    result_en = fetch_digemid_registrations("cisplatin")
    print(f"  → Returned {len(result_en)} records.")

    # Test 3: fetch_discontinuations for cisplatino
    print("\n[TEST 3] fetch_discontinuations('cisplatino')")
    disc = fetch_discontinuations("cisplatino")
    print(f"  → {len(disc)} discontinuation record(s) found for cisplatino.")
    if disc:
        first = disc[0]
        print("  → First record keys:", list(first.keys()))
        print("  → nombre_producto:", first.get("nombre_producto"))
        print("  → tipo_discontinuacion:", first.get("tipo_discontinuacion"))
        print("  → motivos:", first.get("motivos"))

    # Test 4: fetch_discontinuations without filter (full table)
    print("\n[TEST 4] fetch_discontinuations() — full table (no filter)")
    all_disc = fetch_discontinuations(drug_name=None)
    print(f"  → {len(all_disc)} total discontinuation records in registry.")

    # Test 5: fetch_alerts — 2 pages only for speed
    print("\n[TEST 5] fetch_alerts(max_pages=2)")
    alerts = fetch_alerts(max_pages=2)
    print(f"  → {len(alerts)} alert(s) fetched.")
    if alerts:
        first_alert = alerts[0]
        print("  → First alert titulo:", first_alert.get("titulo"))
        print("  → First alert fecha:", first_alert.get("fecha"))
        print("  → First alert categoria:", first_alert.get("categoria"))
        print("  → First alert detail_url:", first_alert.get("detail_url"))

    print("\n" + "=" * 60)
    print("Smoke test complete.")
    print("=" * 60)
