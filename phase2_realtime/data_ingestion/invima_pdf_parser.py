"""
invima_pdf_parser.py — Drug-level parser for INVIMA monthly PDF shortage reports.

Handles three schema versions (v1 2023, v2 2024, v3 2025+) plus v3 sub-tables
(T2 No-desabastecidos, T3 No-comercializado/Descontinuado).

Usage:
    from phase2_realtime.data_ingestion.invima_pdf_parser import parse_pdf, ingest_pdf
    rows = parse_pdf("phase2_data/invima_sample_pdfs/2025-09_invima.pdf")
    n = ingest_pdf("phase2_data/invima_sample_pdfs/2025-09_invima.pdf")  # persist to DB
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pdfplumber

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).parent.parent.parent / "phase2_data" / "invima.db"

# Spanish INN → normalized English name (oncology whitelist + adjacent drugs)
INN_WHITELIST: dict[str, str] = {
    "cisplatino": "cisplatin",
    "carboplatino": "carboplatin",
    "doxorrubicina": "doxorubicin",
    "paclitaxel": "paclitaxel",
    "vincristina": "vincristine",
    "metotrexato": "methotrexate",
    "etopósido": "etoposide",
    "etoposido": "etoposide",
    "asparaginasa": "asparaginase",
    "ifosfamida": "ifosfamide",
    "trastuzumab": "trastuzumab",
    "oxaliplatino": "oxaliplatin",
    "bleomicina": "bleomycin",
    "capecitabina": "capecitabine",
    "citarabina": "cytarabine",
    "daunorrubicina": "daunorubicin",
    "melfalan": "melphalan",
    "talidomida": "thalidomide",
    "tamoxifeno": "tamoxifen",
    "vinblastina": "vinblastine",
    "vinorelbina": "vinorelbine",
    "ciclofosfamida": "cyclophosphamide",
    "epirubicina": "epirubicin",
    "crizotinib": "crizotinib",
    "dasatinib": "dasatinib",
    "ipilimumab": "ipilimumab",
    "lenalidomida": "lenalidomide",
}

# Normalize estado strings → canonical enum
_ESTADO_MAP: dict[str, str] = {
    "no desabastecido": "no_desabastecido",
    "en monitorización": "monitorizacion",
    "en monitorizacion": "monitorizacion",
    "en riesgo de desabastecimiento": "riesgo",
    "en riesgo de desabastecido": "riesgo",
    "desabastecido": "desabastecido",
    "desabastecido**": "desabastecido_lmvnd_pendiente",
    "desabastecido***": "desabastecido_lmvnd",
    "desabastecido****": "desabastecido_no_lmvnd",
    "no comercializado": "no_comercializado",
    "temporalmente no comercializado": "no_comercializado",
    "descontinuado": "descontinuado",
    "recién aprobado": "recien_aprobado",
    "recien aprobado": "recien_aprobado",
}

# Column mappings per schema version
# v3 PDFs have a frozen Excel header in col0 — strip it, then col1=No, col2=name, etc.
_COLS = {
    "v1": {
        "no": 0, "nombre": 1, "atc": None,
        "fecha_i": 2, "fecha_u": 3, "estado": 4,
        "causas": 5, "resumen_c": 6, "resumen_i": None, "cierre": 7,
    },
    # Pre-June 2023 PDFs: 9 cols, no ATC (Fecha alerta in col2, not ATC)
    "v1_2022": {
        "no": 0, "nombre": 1, "atc": None,
        "fecha_i": 2, "fecha_u": 3, "estado": 4,
        "causas": 5, "resumen_c": 7, "resumen_i": None, "cierre": 8,
    },
    # April 2023 PDF: 10 cols, no ATC (dual Estado + dual Causa columns)
    "v1_extended": {
        "no": 0, "nombre": 1, "atc": None,
        "fecha_i": 2, "fecha_u": 3, "estado": 4,
        "causas": 6, "resumen_c": 8, "resumen_i": None, "cierre": 9,
    },
    "v2": {
        "no": 0, "nombre": 1, "atc": 2,
        "fecha_i": 3, "fecha_u": 4, "estado": 5,
        "causas": 6, "resumen_c": 7, "resumen_i": None, "cierre": 8,
    },
    "v3_t1": {
        "no": 1, "nombre": 2, "atc": 3,
        "fecha_i": 4, "fecha_u": 5, "estado": 6,
        "causas": 7, "resumen_c": 8, "resumen_i": 9, "cierre": None,
    },
    "v3_compact": {  # T2 and T3
        "no": 1, "nombre": 2, "atc": 3,
        "fecha_i": 4, "fecha_u": 5, "estado": 6,
        "causas": 7, "resumen_c": None, "resumen_i": None, "cierre": 8,
    },
}


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class InvimaDrugRow:
    report_period: str          # "2025-09"
    pub_date: str               # "2025-09-01" (from PDF header)
    schema_version: str         # "v1" | "v2" | "v3_t1" | "v3_compact"
    table_id: str               # "T1" | "T2" | "T3"
    row_number: int
    sub_row_index: int          # 0 = first/only sub-row per drug
    producto_raw: str
    inn: str                    # Spanish INN, lowercase
    inn_normalized: str         # English normalized (empty if not in whitelist)
    atc_code: str
    fecha_inicio: str           # ISO
    fecha_ultimo: str           # ISO
    fecha_cierre: str           # ISO
    estado: str                 # canonical enum
    causas: list                # list of cause strings
    resumen_text: str           # raw resumen cells concatenated
    is_oncology: bool
    record_hash: str
    pdf_path: str


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _clean(val) -> str:
    """Normalize a cell value to a clean string."""
    if val is None:
        return ""
    s = str(val).strip()
    # Remove null placeholders
    if s.upper() in ("NULL", "NONE", "N/A", "---", ""):
        return ""
    return s


def _normalize_date(s: str) -> str:
    """Convert d/m/yy, dd/mm/yyyy, d/mm/yyyy → ISO YYYY-MM-DD."""
    s = _clean(s)
    if not s:
        return ""
    # Try YYYY-MM-DD already
    if re.match(r"\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    # dd/mm/yyyy or d/m/yyyy or d/mm/yy
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if m:
        d, mo, y = m.groups()
        y = f"20{y}" if len(y) == 2 else y
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return ""


def _normalize_estado(s: str) -> str:
    """Map raw estado string to canonical enum."""
    key = re.sub(r"\s+", " ", s.strip().lower())
    # Strip extra asterisks beyond 4
    key = re.sub(r"\*{5,}", "****", key)
    return _ESTADO_MAP.get(key, key)


def _extract_inn(producto_raw: str) -> tuple[str, str]:
    """
    Returns (inn_spanish, inn_normalized).
    Priority: exact whitelist substring match > first-word heuristic.
    """
    lower = producto_raw.lower()
    # Whitelist match: longest match wins (e.g. "doxorrubicina" over "rubicina")
    best = ("", "")
    for es, en in INN_WHITELIST.items():
        if es in lower and len(es) > len(best[0]):
            best = (es, en)
    if best[0]:
        return best
    # Fallback: first alpha word before any digit
    m = re.match(r"^([A-ZÁÉÍÓÚÑÜA-Za-záéíóúñü\s+/-]+?)(?:\s+\d|\s*$)", producto_raw.strip())
    inn_raw = m.group(1).strip().lower() if m else producto_raw.lower()[:40]
    return inn_raw, ""


def _parse_causas(s: str) -> list:
    """Split causas cell into list of cause strings."""
    if not s:
        return []
    parts = re.split(r"\n|;", s)
    return [p.strip() for p in parts if p.strip() and p.strip() not in ("---", "")]


def _sha1(*parts: str) -> str:
    blob = "|".join(str(p).strip().lower() for p in parts)
    return hashlib.sha1(blob.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# Schema detection
# ---------------------------------------------------------------------------

def _is_frozen_col0(row: list) -> bool:
    """Return True if this row indicates a v3 (Excel-exported) PDF table structure."""
    if not row:
        return False
    col0 = _clean(row[0])
    # v3 2025-09 style: col0 = "A B C D E F G H I\n1 1 3 4 MEDICAMENTOS..."
    if re.match(r"^[A-Z](?: [A-Z]){3,}", col0):
        return True
    # v3 2025-06 style: col0 empty, col1 = "A", col2 = "B" (header is its own row)
    if not col0 and len(row) >= 5:
        if _clean(row[1]) == "A" and _clean(row[2]) == "B":
            return True
    return False


def _detect_page_schema(rows: list) -> str:
    """
    Detect schema version from a page's table rows.
    Returns: "v1" | "v2" | "v3_t1" | "v3_compact" | "unknown"
    """
    if not rows:
        return "unknown"
    ncols = len(rows[0])
    frozen = _is_frozen_col0(rows[0])

    if not frozen:
        if ncols == 8:
            return "v1"
        if ncols >= 9:
            return "v2"
    else:
        # v3 — distinguish T1 (10 cols) from compact T2/T3 (9 cols)
        if ncols >= 10:
            return "v3_t1"
        if ncols == 9:
            return "v3_compact"
    return "unknown"


# ---------------------------------------------------------------------------
# Report metadata extraction
# ---------------------------------------------------------------------------

def _extract_report_metadata(pdf) -> tuple[str, str]:
    """
    Extract report_period (YYYY-MM) and pub_date (ISO) from PDF text.
    Returns ("", "") on failure.
    """
    _MONTHS_ES = {
        "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
        "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
        "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
    }
    for page in pdf.pages[:3]:
        text = (page.extract_text() or "").lower()
        # "listado ... de [mes] de [año]" or "publicacion [mes]"
        m = re.search(r"de\s+(" + "|".join(_MONTHS_ES) + r")\s+de\s+(20\d{2})", text)
        if m:
            month = _MONTHS_ES[m.group(1)]
            year = m.group(2)
            period = f"{year}-{month}"
            # Try to find explicit pub date "1/04/2024" or "29/01/2025"
            dm = re.search(r"(\d{1,2}/\d{1,2}/20\d{2})", text)
            pub_date = _normalize_date(dm.group(1)) if dm else f"{year}-{month}-01"
            return period, pub_date
    return "", ""


# ---------------------------------------------------------------------------
# Core row parser (shared across schemas)
# ---------------------------------------------------------------------------

def _parse_rows(
    all_rows: list,
    schema: str,
    table_id: str,
    report_period: str,
    pub_date: str,
    pdf_path: str,
) -> list[InvimaDrugRow]:
    """
    Parse a flat list of table rows into InvimaDrugRow objects.
    Handles multi-titular sub-rows via forward-fill on drug-identity columns.
    """
    cols = _COLS.get(schema)
    if cols is None:
        logger.warning("Unknown schema %s — skipping", schema)
        return []

    results = []
    # Running drug-block state (forward-filled)
    cur_no = 0
    cur_nombre = ""
    cur_atc = ""
    cur_fecha_i = ""
    cur_estado = ""
    cur_causas: list = []
    sub_idx = 0

    for row in all_rows:
        # Skip rows that are all-empty or are section/column headers
        nonempty_vals = [_clean(c) for c in row if _clean(c)]
        if not nonempty_vals:
            continue

        # Detect header rows: contains "No." or "Nombre del" in col_no position
        no_val = _clean(row[cols["no"]]) if cols["no"] < len(row) else ""
        if "No." in no_val or "NOMBRE" in no_val.upper() or "MEDICAMENTOS" in no_val.upper():
            continue

        # Detect section title rows (merged header spanning first few data rows)
        if len(nonempty_vals) <= 2 and any(
            kw in " ".join(nonempty_vals).upper()
            for kw in ("CLASIFICADOS", "SEGUIMIENTO REALIZADO", "INVIMA", "LISTADO")
        ):
            continue

        is_new_block = bool(no_val and re.match(r"^\d+$", no_val.strip()))

        if is_new_block:
            cur_no = int(no_val.strip())
            nombre_raw = _clean(row[cols["nombre"]]) if cols["nombre"] < len(row) else ""
            cur_nombre = nombre_raw
            cur_atc = _clean(row[cols["atc"]]) if cols["atc"] is not None and cols["atc"] < len(row) else ""
            cur_fecha_i = _normalize_date(_clean(row[cols["fecha_i"]]) if cols["fecha_i"] is not None and cols["fecha_i"] < len(row) else "")
            estado_raw = _clean(row[cols["estado"]]) if cols["estado"] < len(row) else ""
            cur_estado = _normalize_estado(estado_raw)
            causas_raw = _clean(row[cols["causas"]]) if cols["causas"] < len(row) else ""
            cur_causas = _parse_causas(causas_raw)
            sub_idx = 0
        else:
            # Sub-row: forward-fill drug identity; update sub-row counter
            sub_idx += 1
            # Some sub-rows have their own ATC/fecha (per titular) — use if present
            if cols["atc"] is not None and cols["atc"] < len(row):
                v = _clean(row[cols["atc"]])
                if v and not cur_atc:
                    cur_atc = v
            if cols["fecha_i"] is not None and cols["fecha_i"] < len(row):
                v = _normalize_date(_clean(row[cols["fecha_i"]]))
                if v and not cur_fecha_i:
                    cur_fecha_i = v

        if not cur_nombre:
            continue

        # Per-row varying fields
        fecha_u = _normalize_date(_clean(row[cols["fecha_u"]]) if cols["fecha_u"] is not None and cols["fecha_u"] < len(row) else "")
        fecha_c = _normalize_date(_clean(row[cols["cierre"]]) if cols["cierre"] is not None and cols["cierre"] < len(row) else "")

        resumen_c = _clean(row[cols["resumen_c"]]) if cols["resumen_c"] is not None and cols["resumen_c"] < len(row) else ""
        resumen_i = _clean(row[cols["resumen_i"]]) if cols["resumen_i"] is not None and cols["resumen_i"] < len(row) else ""
        resumen_text = " | ".join(r for r in [resumen_c, resumen_i] if r)

        inn, inn_norm = _extract_inn(cur_nombre)

        record_hash = _sha1(report_period, table_id, str(cur_no), str(sub_idx), cur_nombre[:40])

        results.append(InvimaDrugRow(
            report_period=report_period,
            pub_date=pub_date,
            schema_version=schema,
            table_id=table_id,
            row_number=cur_no,
            sub_row_index=sub_idx,
            producto_raw=cur_nombre,
            inn=inn,
            inn_normalized=inn_norm,
            atc_code=cur_atc,
            fecha_inicio=cur_fecha_i,
            fecha_ultimo=fecha_u,
            fecha_cierre=fecha_c,
            estado=cur_estado,
            causas=cur_causas,
            resumen_text=resumen_text,
            is_oncology=bool(inn_norm),
            record_hash=record_hash,
            pdf_path=str(pdf_path),
        ))

    return results


# ---------------------------------------------------------------------------
# PDF-level parser
# ---------------------------------------------------------------------------

def _find_v3_boundaries(pdf) -> dict:
    """
    Scan pages to find T2 and T3 section start page indices.
    T2: 9-col compact table that starts after T1 ends.
    T3: 9-col compact with "NO COMERCIALIZADO Y DESCONTINUADO" in section text.
    Returns {"t2": int|None, "t3": int|None}.
    """
    t2_start = t3_start = None
    for pi, page in enumerate(pdf.pages):
        text = (page.extract_text() or "").upper()
        tables = page.extract_tables()
        if not tables:
            continue
        ncols = len(tables[0][0])
        frozen = _is_frozen_col0(tables[0][0])

        # T3: explicit text signal
        if t3_start is None and frozen and ncols == 9 and "DESCONTINUADO" in text:
            t3_start = pi

        # T2: 9-col compact that appears before T3 and has "NO DESABASTECIDOS" text
        if t2_start is None and frozen and ncols == 9 and t3_start is None:
            if "NO DESABASTECIDOS" in text or "NO DESABASTECIDO" in text:
                t2_start = pi

    return {"t2": t2_start, "t3": t3_start}


def parse_pdf(pdf_path: str | Path) -> list[InvimaDrugRow]:
    """
    Parse all drug-level rows from an INVIMA monthly PDF.

    Returns a flat list of InvimaDrugRow — one entry per drug sub-row.
    Empty list on any unrecoverable error (logged).
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        logger.error("PDF not found: %s", pdf_path)
        return []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            _, pub_date = _extract_report_metadata(pdf)
            # Filename is ground truth for the report period (e.g. "2025-09_invima.pdf")
            fname_m = re.match(r"(\d{4}-\d{2})", pdf_path.name)
            report_period = fname_m.group(1) if fname_m else "unknown"
            if not pub_date:
                pub_date = f"{report_period}-01" if "-" in report_period else ""

            # Determine if this is a v3 PDF (has frozen col0 on first data page)
            is_v3 = False
            for page in pdf.pages[1:4]:
                tables = page.extract_tables()
                if tables and _is_frozen_col0(tables[0][0]):
                    is_v3 = True
                    break

            results: list[InvimaDrugRow] = []

            if is_v3:
                bounds = _find_v3_boundaries(pdf)
                t2_start = bounds["t2"]
                t3_start = bounds["t3"]

                # Collect rows per table section
                t1_rows: list = []
                t2_rows: list = []
                t3_rows: list = []

                for pi, page in enumerate(pdf.pages):
                    tables = page.extract_tables()
                    if not tables:
                        continue
                    rows = tables[0]
                    if t3_start is not None and pi >= t3_start:
                        t3_rows.extend(rows)
                    elif t2_start is not None and pi >= t2_start:
                        t2_rows.extend(rows)
                    else:
                        t1_rows.extend(rows)

                results.extend(_parse_rows(t1_rows, "v3_t1", "T1", report_period, pub_date, pdf_path))
                if t2_rows:
                    results.extend(_parse_rows(t2_rows, "v3_compact", "T2", report_period, pub_date, pdf_path))
                if t3_rows:
                    results.extend(_parse_rows(t3_rows, "v3_compact", "T3", report_period, pub_date, pdf_path))

            else:
                # v1 or v2: detect T3 section by page text, split rows accordingly
                t1_rows_old: list = []
                t3_rows_old: list = []
                t3_start_old = None

                for pi, page in enumerate(pdf.pages):
                    tables = page.extract_tables()
                    if not tables:
                        continue
                    page_text = (page.extract_text() or "").upper()
                    rows = tables[0]
                    # Detect T3 section: "NO COMERCIALIZADO Y DESCONTINUADO" or "DESCONTINUADO"
                    if t3_start_old is None and (
                        "NO COMERCIALIZADO Y DESCONTINUADO" in page_text
                        or ("DESCONTINUADO" in page_text and "PRINCIPIOS ACTIVOS" in page_text and pi > len(pdf.pages) // 2)
                    ):
                        t3_start_old = pi
                    if t3_start_old is not None and pi >= t3_start_old:
                        t3_rows_old.extend(rows)
                    else:
                        t1_rows_old.extend(rows)

                # Detect schema from t1 rows
                data_rows = [r for r in t1_rows_old if r and any(_clean(c) for c in r)]
                if not data_rows:
                    return []
                schema = "v1"
                for r in data_rows:
                    if _clean(r[0]).isdigit():
                        if len(r) <= 8:
                            schema = "v1"
                        elif len(r) == 9:
                            # Distinguish v1_2022 (fecha in col2) from v2 (ATC in col2)
                            col2 = _clean(r[2])
                            schema = "v1_2022" if re.match(r"\d{1,2}/\d", col2) else "v2"
                        else:
                            schema = "v1_extended"
                        break

                results.extend(_parse_rows(t1_rows_old, schema, "T1", report_period, pub_date, pdf_path))
                if t3_rows_old:
                    results.extend(_parse_rows(t3_rows_old, schema, "T3", report_period, pub_date, pdf_path))

    except Exception as exc:
        logger.error("parse_pdf %s failed: %s", pdf_path, exc, exc_info=True)
        return []

    logger.info("parse_pdf %s: %d rows (%d oncology)",
                pdf_path.name, len(results), sum(r.is_oncology for r in results))
    return results


# ---------------------------------------------------------------------------
# Database persistence
# ---------------------------------------------------------------------------

def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS invima_drug_shortages (
            record_hash       TEXT PRIMARY KEY,
            report_period     TEXT,
            pub_date          TEXT,
            schema_version    TEXT,
            table_id          TEXT,
            row_number        INTEGER,
            sub_row_index     INTEGER,
            producto_raw      TEXT,
            inn               TEXT,
            inn_normalized    TEXT,
            atc_code          TEXT,
            fecha_inicio      TEXT,
            fecha_ultimo      TEXT,
            fecha_cierre      TEXT,
            estado            TEXT,
            causas            TEXT,
            resumen_text      TEXT,
            is_oncology       INTEGER,
            pdf_path          TEXT,
            ingested_at       TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ids_period ON invima_drug_shortages(report_period);
        CREATE INDEX IF NOT EXISTS idx_ids_inn ON invima_drug_shortages(inn_normalized);
        CREATE INDEX IF NOT EXISTS idx_ids_oncology ON invima_drug_shortages(is_oncology, estado);
    """)
    conn.commit()


def _persist_rows(rows: list[InvimaDrugRow], conn: sqlite3.Connection) -> int:
    """Insert rows with deduplication. Returns count of new rows inserted."""
    ts = datetime.utcnow().isoformat()
    new = 0
    for row in rows:
        d = asdict(row)
        d["causas"] = json.dumps(d["causas"], ensure_ascii=False)
        d["is_oncology"] = int(d["is_oncology"])
        d["ingested_at"] = ts
        try:
            conn.execute(
                "INSERT OR IGNORE INTO invima_drug_shortages VALUES "
                "(:record_hash,:report_period,:pub_date,:schema_version,:table_id,"
                ":row_number,:sub_row_index,:producto_raw,:inn,:inn_normalized,"
                ":atc_code,:fecha_inicio,:fecha_ultimo,:fecha_cierre,:estado,"
                ":causas,:resumen_text,:is_oncology,:pdf_path,:ingested_at)",
                d,
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                new += 1
        except sqlite3.Error as exc:
            logger.error("DB insert: %s | row=%s", exc, row.record_hash)
    conn.commit()
    return new


def ingest_pdf(pdf_path: str | Path, db_path: str | Path = DB_PATH) -> int:
    """
    Parse a PDF and persist drug-level rows to SQLite.
    Returns count of new rows inserted.
    """
    rows = parse_pdf(pdf_path)
    if not rows:
        return 0
    conn = sqlite3.connect(db_path)
    _init_db(conn)
    n = _persist_rows(rows, conn)
    conn.close()
    logger.info("ingest_pdf %s: %d new rows", Path(pdf_path).name, n)
    return n


def ingest_all_pdfs(pdf_dir: str | Path = None, db_path: str | Path = DB_PATH) -> dict:
    """
    Ingest all PDFs in a directory.
    Default dir: phase2_data/invima_sample_pdfs/
    Returns summary dict.
    """
    if pdf_dir is None:
        pdf_dir = Path(__file__).parent.parent.parent / "phase2_data" / "invima_sample_pdfs"
    pdf_dir = Path(pdf_dir)
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        logger.warning("No PDFs found in %s", pdf_dir)
        return {"pdfs_processed": 0, "total_new_rows": 0}

    conn = sqlite3.connect(db_path)
    _init_db(conn)
    total = 0
    results = {}
    for pdf_path in pdfs:
        rows = parse_pdf(pdf_path)
        n = _persist_rows(rows, conn)
        total += n
        oncology_count = sum(r.is_oncology for r in rows)
        results[pdf_path.name] = {"rows": len(rows), "new_db_rows": n, "oncology": oncology_count}
        logger.info("%s: %d rows (%d oncology, %d new)", pdf_path.name, len(rows), oncology_count, n)
    conn.close()
    return {"pdfs_processed": len(pdfs), "total_new_rows": total, "detail": results}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if len(sys.argv) > 1:
        result = ingest_pdf(sys.argv[1])
        print(f"New rows ingested: {result}")
    else:
        result = ingest_all_pdfs()
        print(_json.dumps(result, indent=2))
