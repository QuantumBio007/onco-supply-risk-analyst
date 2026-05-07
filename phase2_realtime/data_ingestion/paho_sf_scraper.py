"""
paho_sf_scraper.py — PAHO Strategic Fund price PDF fetcher and parser (stub)

Public PAHO SF price data is published as annual PDF snapshots only.
No CSV, Excel, or API endpoint is available publicly as of May 2026.
This module fetches the known public PDFs and attempts to extract drug prices
using pdfplumber (if available).

Data sources documented in:
  Literature/PAHO_analytics/PAHO_SF_DATA_SOURCES.md

Usage:
    from phase2_realtime.data_ingestion.paho_sf_scraper import fetch_sf_price_list
    prices = fetch_sf_price_list(year=2025)
"""

import os
import pathlib
import urllib.request

# ── Known public PDF URLs (as of May 2026) ────────────────────────────────────
# Sources: https://www.paho.org/en/paho-strategic-fund
# All three provide a rough 5-year price time series: 2020, 2022, 2025.
PAHO_SF_PRICE_PDFS = {
    2025: "https://www.paho.org/sites/default/files/2025-01/2025-lista-precios-eng-final-ncm.pdf",
    2022: "https://www.paho.org/sites/default/files/2022-10/sf-lta-ptoducts-and-prices-oct-2022.pdf",
    2020: None,  # 2020 antineoplastic-specific PDF: landing page only, direct URL not confirmed
    # Landing page for 2020 antineoplastic list:
    # https://www.paho.org/en/documents/strategic-fund-product-prices-antineoplastic-medicines-long-term-agreement-valid-until-31
}

# Target oncology drugs for OncoSupply model calibration
ONCOLOGY_DRUGS_OF_INTEREST = [
    "cisplatin",
    "carboplatin",
    "doxorubicin",
    "trastuzumab",
]

# Local cache directory for downloaded PDFs
CACHE_DIR = pathlib.Path(__file__).parent / "_cache" / "paho_sf"


def fetch_sf_price_list(year: int = 2025, cache: bool = True) -> pathlib.Path | None:
    """
    Download the PAHO Strategic Fund price list PDF for the given year.

    Args:
        year:  Publication year — one of 2025, 2022 (2020 not supported yet).
        cache: If True, skip download when local file already exists.

    Returns:
        pathlib.Path to the local PDF, or None if the URL is not configured.

    Notes:
        - PAHO does not require authentication for these URLs (public access).
        - paho.org may rate-limit repeated downloads; respect robots.txt.
        - PDF structure changes between years — the parser below may need updating.
    """
    url = PAHO_SF_PRICE_PDFS.get(year)
    if url is None:
        print(f"[paho_sf_scraper] No direct PDF URL configured for year={year}. "
              f"Check PAHO_SF_PRICE_PDFS dict or visit the landing page manually.")
        return None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    filename = url.split("/")[-1]
    local_path = CACHE_DIR / filename

    if cache and local_path.exists():
        print(f"[paho_sf_scraper] Using cached file: {local_path}")
        return local_path

    print(f"[paho_sf_scraper] Downloading {year} price list from PAHO...")
    headers = {"User-Agent": "OncoSupply-Research/1.0 (academic; contact cmart156@jh.edu)"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        local_path.write_bytes(data)
        print(f"[paho_sf_scraper] Saved to {local_path} ({len(data):,} bytes)")
        return local_path
    except Exception as e:
        print(f"[paho_sf_scraper] Download failed: {e}")
        return None


def parse_oncology_prices(pdf_path: pathlib.Path) -> list[dict]:
    """
    Attempt to extract oncology drug prices from a PAHO SF price list PDF.

    Requires pdfplumber (install: pip install pdfplumber).
    Returns a list of dicts with keys: drug_name, presentation, unit_price_usd, source_year.

    NOTE: This is a best-effort parser. The PAHO PDF table structure varies by year
    and is not guaranteed to be machine-parseable without manual column mapping.
    Actual production use should validate output against the PDF manually.
    """
    try:
        import pdfplumber
    except ImportError:
        print("[paho_sf_scraper] pdfplumber not installed. Run: pip install pdfplumber")
        return []

    results = []
    drug_keywords = [d.lower() for d in ONCOLOGY_DRUGS_OF_INTEREST]

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row is None:
                        continue
                    row_text = " ".join(str(cell) for cell in row if cell).lower()
                    for drug in drug_keywords:
                        if drug in row_text:
                            results.append({
                                "drug_name":       drug,
                                "raw_row":         row,
                                "page":            page_num,
                                "pdf_source":      str(pdf_path.name),
                            })

    return results


def get_price_snapshot(year: int = 2025) -> list[dict]:
    """
    End-to-end: download PDF for the given year and parse oncology prices.

    Returns parsed results list (may be empty if parsing fails or drug not found).
    """
    pdf_path = fetch_sf_price_list(year=year)
    if pdf_path is None:
        return []
    return parse_oncology_prices(pdf_path)


if __name__ == "__main__":
    # Quick test: download 2025 price list and attempt oncology price extraction
    rows = get_price_snapshot(year=2025)
    if rows:
        print(f"\nFound {len(rows)} potential oncology drug rows:")
        for r in rows[:10]:
            print(f"  [{r['drug_name']}] page={r['page']} | {r['raw_row']}")
    else:
        print("\nNo oncology drug rows extracted. Manual PDF inspection required.")
        print("2025 PDF: https://www.paho.org/sites/default/files/2025-01/2025-lista-precios-eng-final-ncm.pdf")
