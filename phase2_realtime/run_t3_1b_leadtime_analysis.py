"""
run_t3_1b_leadtime_analysis.py — INVIMA retrospective lead-time analysis.

Tests the three pre-registered hypotheses in:
  phase2_realtime/docs/preregistration_t3_1b_invima_leadtime.md

H1: INVIMA monitorizacion provides >=1 snapshot lead-time before desabastecido*
H2: openFDA initial_posting_date precedes INVIMA shortage flag (median > 0 days)
H3: drugs reaching descontinuado had >=1 prior monitorizacion/desabastecido* snapshot

Design choices locked here BEFORE running:
  - Unit of analysis = (inn_normalized, producto_canonical) tuple
  - producto_canonical = lowercase, whitespace-stripped, trailing dose tokens removed
  - Snapshots are ordinal (1..9), not calendar months
  - openFDA Spanish→English INN normalization map is locked below

Usage:
  .venv/bin/python phase2_realtime/run_t3_1b_leadtime_analysis.py
  .venv/bin/python phase2_realtime/run_t3_1b_leadtime_analysis.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

# ── Constants ───────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
INVIMA_DB    = PROJECT_ROOT / "phase2_data" / "invima.db"
OPENFDA_DB   = PROJECT_ROOT / "phase2_data" / "openfda.db"

SHORTAGE_ESTADOS = {
    "desabastecido",
    "desabastecido_lmvnd",
    "desabastecido_lmvnd_pendiente",
    "desabastecido_no_lmvnd",
}
WARNING_ESTADOS = {"monitorizacion", "riesgo"}
BENIGN_ESTADOS  = WARNING_ESTADOS | {"no_desabastecido"}
DISCONT_ESTADOS = {"descontinuado", "no_comercializado"}

# Snapshot ordinal map — locked before analysis runs
SNAPSHOT_ORDER = [
    "2022-12", "2023-04", "2023-06", "2023-12", "2024-01", "2024-04", "2024-08",
    "2024-12", "2025-01", "2025-06", "2025-09",
]
SNAPSHOT_INDEX = {p: i for i, p in enumerate(SNAPSHOT_ORDER)}

# Approximate snapshot publication dates (first day of period)
def snapshot_to_date(period: str) -> date:
    yyyy, mm = period.split("-")
    return date(int(yyyy), int(mm), 1)

# openFDA Spanish→English INN normalization (subset of project INN_WHITELIST)
OPENFDA_TO_INVIMA_INN = {
    "carboplatin":   "carboplatin",
    "cisplatin":     "cisplatin",
    "methotrexate":  "methotrexate",
    "asparaginase":  "asparaginase",
    "vincristine":   "vincristine",
    "vinblastine":   "vinblastine",
    "vinorelbine":   "vinorelbine",
    "cytarabine":    "cytarabine",
    "daunorubicin":  "daunorubicin",
    "doxorubicin":   "doxorubicin",
    "paclitaxel":    "paclitaxel",
    "ifosfamide":    "ifosfamide",
    "bleomycin":     "bleomycin",
    "thalidomide":   "thalidomide",
    "tamoxifen":     "tamoxifen",
    "dasatinib":     "dasatinib",
    "trastuzumab":   "trastuzumab",
    "rituximab":     "rituximab",
    "imatinib":      "imatinib",
    "fluorouracil":  "fluorouracil",
    "cyclophosphamide": "cyclophosphamide",
}


# ── Producto canonicalization ───────────────────────────────────────────────
_DOSE_TOKEN_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:mg|g|ml|mcg|ui|u|%)\b", re.IGNORECASE
)

def canonicalize_producto(producto_raw: str) -> str:
    """
    Canonical form of a producto_raw string:
      - lowercase
      - collapse whitespace
      - strip trailing dose tokens (e.g., "10 mg / 1 ml")
      - keep formulation keywords (polvo, solución, tableta, inyectable)
    Locked before analysis runs.
    """
    if not producto_raw:
        return ""
    s = producto_raw.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = _DOSE_TOKEN_RE.sub("", s)
    s = re.sub(r"\s*[/-]\s*", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ── Timeline reconstruction ─────────────────────────────────────────────────
def load_oncology_timelines(db_path: Path) -> dict:
    """
    Return dict keyed by (inn_normalized, producto_canonical) → list of
    (snapshot_idx, period, estado, fecha_inicio, fecha_cierre, producto_raw).
    Sorted by snapshot_idx.
    """
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT report_period, inn_normalized, estado, fecha_inicio, fecha_cierre,
               producto_raw
        FROM invima_drug_shortages
        WHERE is_oncology = 1 AND inn_normalized IS NOT NULL AND inn_normalized != ''
    """).fetchall()
    conn.close()

    timelines: dict = {}
    for period, inn, estado, finicio, fcierre, producto in rows:
        if period not in SNAPSHOT_INDEX:
            continue
        canonical = canonicalize_producto(producto or "")
        if not canonical:
            continue
        key = (inn, canonical)
        timelines.setdefault(key, []).append({
            "snapshot_idx":   SNAPSHOT_INDEX[period],
            "period":         period,
            "estado":         (estado or "").strip(),
            "fecha_inicio":   finicio,
            "fecha_cierre":   fcierre,
            "producto_raw":   producto,
        })
    for key in timelines:
        timelines[key].sort(key=lambda r: r["snapshot_idx"])
    return timelines


def first_snapshot_in_state(timeline: list, states: set) -> Optional[int]:
    """Return snapshot_idx of first row whose estado is in `states`, else None."""
    for r in timeline:
        if r["estado"] in states:
            return r["snapshot_idx"]
    return None


def first_snapshot_estado(timeline: list) -> str:
    return timeline[0]["estado"]


# ── Hypothesis 1 ────────────────────────────────────────────────────────────
def evaluate_h1(timelines: dict) -> dict:
    """
    H1: median observable lead-time (snapshots) from first warning to first
    desabastecido* >= 1.

    Population: formulations whose first observed estado is benign and that
    later transition to desabastecido*.
    """
    qualifying = []   # list of (key, lead_snapshots, first_warn_period, first_short_period)
    left_truncated = []  # formulations already in shortage at first observation

    for key, timeline in timelines.items():
        first_estado = first_snapshot_estado(timeline)
        first_short_idx = first_snapshot_in_state(timeline, SHORTAGE_ESTADOS)
        first_warn_idx  = first_snapshot_in_state(timeline, WARNING_ESTADOS)

        if first_estado in SHORTAGE_ESTADOS:
            left_truncated.append(key)
            continue

        if first_short_idx is None:
            continue   # no shortage event in window

        if first_estado not in BENIGN_ESTADOS:
            continue   # first observation is not benign (e.g., descontinuado)

        if first_warn_idx is None or first_warn_idx >= first_short_idx:
            # No prior warning before shortage — lead-time = 0
            lead = 0
        else:
            lead = first_short_idx - first_warn_idx

        qualifying.append({
            "key": key,
            "lead_snapshots": lead,
            "first_warn_period":  SNAPSHOT_ORDER[first_warn_idx] if first_warn_idx is not None else None,
            "first_short_period": SNAPSHOT_ORDER[first_short_idx],
        })

    leads = [q["lead_snapshots"] for q in qualifying]
    n_qual = len(qualifying)
    n_lt   = len(left_truncated)
    median = statistics.median(leads) if leads else None

    # Pre-registered verdict logic
    if n_qual <= 2:
        verdict = "NULL"
        reason  = f"Insufficient power: only {n_qual} qualifying formulations (pre-registered N>=3 required)"
    elif median is None or median < 1:
        verdict = "NULL"
        reason  = f"Median lead-time {median} < 1 snapshot threshold"
    else:
        ratio = n_qual / max(1, n_qual + n_lt)
        if ratio < 0.30:
            verdict = "PARTIAL-NULL"
            reason  = (f"Median {median} >= 1 but qualifying-vs-left-truncated ratio "
                       f"{ratio:.2f} < 0.30 — most events not observable")
        else:
            verdict = "PASS"
            reason  = f"Median lead-time {median} snapshots across {n_qual} qualifying formulations"

    return {
        "hypothesis": "H1",
        "verdict": verdict,
        "reason": reason,
        "n_qualifying": n_qual,
        "n_left_truncated": n_lt,
        "leads_snapshots": leads,
        "median_lead_snapshots": median,
        "qualifying_detail": qualifying,
        "left_truncated_keys": left_truncated,
    }


# ── Hypothesis 2 ────────────────────────────────────────────────────────────
def parse_openfda_date(s: str) -> Optional[date]:
    """openFDA dates are MM/DD/YYYY strings."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%m/%d/%Y").date()
    except ValueError:
        return None


def load_openfda_first_postings(db_path: Path) -> dict:
    """Return dict inn_normalized (English) → earliest initial_posting_date."""
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT generic_name, initial_posting_date, status
        FROM openfda_shortages
        WHERE therapeutic_category LIKE '%Oncology%'
    """).fetchall()
    conn.close()

    earliest: dict[str, date] = {}
    for generic_name, posting_date_str, status in rows:
        if not generic_name:
            continue
        gname_lower = generic_name.lower()
        for inn_key in OPENFDA_TO_INVIMA_INN:
            if inn_key in gname_lower:
                d = parse_openfda_date(posting_date_str)
                if d is None:
                    continue
                inn = OPENFDA_TO_INVIMA_INN[inn_key]
                if inn not in earliest or d < earliest[inn]:
                    earliest[inn] = d
                break
    return earliest


def evaluate_h2(timelines: dict, openfda_dates: dict) -> dict:
    """
    H2: For drugs in BOTH databases that reach shortage in INVIMA,
    median(INVIMA_first_short_date - openFDA_initial_posting_date) > 0.
    """
    matched = []   # list of dicts per matched drug

    # Aggregate by inn_normalized — earliest INVIMA shortage across formulations
    inn_to_earliest_shortage: dict[str, str] = {}
    for (inn, _producto), timeline in timelines.items():
        idx = first_snapshot_in_state(timeline, SHORTAGE_ESTADOS | DISCONT_ESTADOS)
        if idx is None:
            continue
        period = SNAPSHOT_ORDER[idx]
        if inn not in inn_to_earliest_shortage or period < inn_to_earliest_shortage[inn]:
            inn_to_earliest_shortage[inn] = period

    for inn, period in inn_to_earliest_shortage.items():
        ofda_date = openfda_dates.get(inn)
        if ofda_date is None:
            continue
        invima_date = snapshot_to_date(period)
        lead_days = (invima_date - ofda_date).days
        matched.append({
            "inn":              inn,
            "openfda_date":     ofda_date.isoformat(),
            "invima_period":    period,
            "invima_date_approx": invima_date.isoformat(),
            "lead_days":        lead_days,
        })

    leads = [m["lead_days"] for m in matched]
    n_matched = len(matched)
    median = statistics.median(leads) if leads else None

    if n_matched < 2:
        verdict = "NULL"
        reason  = f"Insufficient power: only {n_matched} matched drugs (pre-registered N>=2)"
    elif median is None or median <= 0:
        verdict = "NULL"
        reason  = f"Median lead-days {median} not > 0"
    else:
        verdict = "PASS"
        reason  = f"openFDA leads INVIMA by median {median} days across {n_matched} drugs"

    return {
        "hypothesis": "H2",
        "verdict": verdict,
        "reason": reason,
        "n_matched": n_matched,
        "leads_days": leads,
        "median_lead_days": median,
        "matched_detail": matched,
    }


# ── Hypothesis 3 ────────────────────────────────────────────────────────────
def evaluate_h3(timelines: dict) -> dict:
    """
    H3: >=80% of OBSERVABLE descontinuado formulations had a prior warning
    or shortage snapshot. Left-truncated count must be reported separately.
    """
    observable_with_signal = []
    observable_without_signal = []
    left_truncated = []

    for key, timeline in timelines.items():
        first_disc_idx = first_snapshot_in_state(timeline, DISCONT_ESTADOS)
        if first_disc_idx is None:
            continue

        if timeline[0]["estado"] in DISCONT_ESTADOS:
            left_truncated.append({
                "key":             key,
                "first_period":    timeline[0]["period"],
            })
            continue

        # Observable: did any earlier snapshot show warning or shortage?
        had_signal = any(
            r["snapshot_idx"] < first_disc_idx
            and (r["estado"] in WARNING_ESTADOS or r["estado"] in SHORTAGE_ESTADOS)
            for r in timeline
        )
        record = {
            "key":             key,
            "first_disc_period": SNAPSHOT_ORDER[first_disc_idx],
            "prior_signal":    had_signal,
            "first_obs_period": timeline[0]["period"],
            "first_obs_estado": timeline[0]["estado"],
        }
        (observable_with_signal if had_signal else observable_without_signal).append(record)

    n_obs_signal = len(observable_with_signal)
    n_obs_nosignal = len(observable_without_signal)
    n_obs = n_obs_signal + n_obs_nosignal
    n_lt  = len(left_truncated)
    pct_with_signal = (n_obs_signal / n_obs * 100) if n_obs > 0 else None

    if n_obs == 0:
        verdict = "NULL"
        reason  = "No observable descontinuado formulations in window"
    elif pct_with_signal is None or pct_with_signal < 80.0:
        verdict = "NULL"
        reason  = f"{pct_with_signal:.0f}% with prior signal < 80% threshold"
    elif n_lt > n_obs:
        verdict = "PARTIAL-PASS"
        reason  = (f"{pct_with_signal:.0f}% of observable cases have prior signal, "
                   f"but left-truncated cases ({n_lt}) outnumber observable ({n_obs}); "
                   f"claim does not generalize")
    else:
        verdict = "PASS"
        reason  = f"{pct_with_signal:.0f}% of {n_obs} observable descontinuado formulations had prior signal"

    return {
        "hypothesis": "H3",
        "verdict": verdict,
        "reason": reason,
        "n_observable_with_signal":    n_obs_signal,
        "n_observable_without_signal": n_obs_nosignal,
        "n_left_truncated":            n_lt,
        "pct_with_signal":             pct_with_signal,
        "with_signal_detail":    observable_with_signal,
        "without_signal_detail": observable_without_signal,
        "left_truncated_detail": left_truncated,
    }


# ── Hypothesis 4 ────────────────────────────────────────────────────────────
def evaluate_h4(timelines: dict) -> dict:
    """
    H4: At the INN level, monitorizacion/riesgo for ANY formulation precedes
    desabastecido* for ANY formulation of the same INN by >=1 snapshot.

    Pre-registration: phase2_realtime/docs/preregistration_t3_1c_h4_inn_leadtime.md
    Expected verdict: AUTO-NULL (qualifying N=1, carboplatin only).
    """
    inn_first_warn: dict[str, int] = {}
    inn_first_short: dict[str, int] = {}

    for (inn, _prod), tl in timelines.items():
        for obs in tl:
            idx = obs["snapshot_idx"]
            if obs["estado"] in WARNING_ESTADOS:
                if inn not in inn_first_warn or idx < inn_first_warn[inn]:
                    inn_first_warn[inn] = idx
            if obs["estado"] in SHORTAGE_ESTADOS:
                if inn not in inn_first_short or idx < inn_first_short[inn]:
                    inn_first_short[inn] = idx

    rows = []
    qualifying_leads = []
    for inn in sorted(inn_first_short):
        fs = inn_first_short[inn]
        fw = inn_first_warn.get(inn)
        left_trunc = fs == 0
        lead = (fs - fw) if fw is not None else None
        qualifying = lead is not None and lead > 0
        if qualifying:
            qualifying_leads.append(lead)
        rows.append({
            "inn": inn,
            "first_warn_period":  SNAPSHOT_ORDER[fw] if fw is not None else None,
            "first_short_period": SNAPSHOT_ORDER[fs],
            "lead_snapshots": lead,
            "qualifying": qualifying,
            "left_truncated": left_trunc,
        })

    n_q = len(qualifying_leads)
    if n_q < 2:
        import statistics as _stats
        verdict = "AUTO-NULL"
        reason = f"qualifying N={n_q} < 2; one data point cannot establish median trend"
        median_lead = qualifying_leads[0] if n_q == 1 else None
    else:
        import statistics as _stats
        median_lead = _stats.median(qualifying_leads)
        verdict = "PASS" if median_lead >= 1 else "NULL"
        reason = f"qualifying N={n_q}, median lead={median_lead} snapshots"

    return {"verdict": verdict, "reason": reason, "n_qualifying": n_q,
            "qualifying_leads": qualifying_leads, "median_lead_snapshots": median_lead,
            "rows": rows}


# ── Summary table ───────────────────────────────────────────────────────────
def build_summary_table(timelines: dict) -> list[dict]:
    out = []
    for (inn, producto_canonical), timeline in sorted(timelines.items()):
        first_obs = timeline[0]
        first_warn_idx = first_snapshot_in_state(timeline, WARNING_ESTADOS)
        first_short_idx = first_snapshot_in_state(timeline, SHORTAGE_ESTADOS)
        first_disc_idx = first_snapshot_in_state(timeline, DISCONT_ESTADOS)
        is_left_truncated = first_obs["estado"] in (SHORTAGE_ESTADOS | DISCONT_ESTADOS)
        if first_warn_idx is not None and first_short_idx is not None and first_warn_idx < first_short_idx:
            obs_lead = first_short_idx - first_warn_idx
        else:
            obs_lead = None
        out.append({
            "inn":                inn,
            "producto_canonical": producto_canonical[:60],
            "first_obs_period":   first_obs["period"],
            "first_obs_estado":   first_obs["estado"],
            "first_warn_period":  SNAPSHOT_ORDER[first_warn_idx]  if first_warn_idx  is not None else None,
            "first_short_period": SNAPSHOT_ORDER[first_short_idx] if first_short_idx is not None else None,
            "first_disc_period":  SNAPSHOT_ORDER[first_disc_idx]  if first_disc_idx  is not None else None,
            "observable_lead_snapshots": obs_lead,
            "left_truncated":     is_left_truncated,
        })
    return out


# ── Main ────────────────────────────────────────────────────────────────────
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=str, default=None,
                    help="Optional path to write full results as JSON")
    args = ap.parse_args(argv)

    if not INVIMA_DB.exists():
        print(f"ERROR: INVIMA DB not found at {INVIMA_DB}", file=sys.stderr)
        return 2

    print("=" * 80)
    print("T3.1b RETROSPECTIVE LEAD-TIME ANALYSIS — INVIMA")
    print("=" * 80)
    print(f"INVIMA DB:   {INVIMA_DB}")
    print(f"openFDA DB:  {OPENFDA_DB} (exists={OPENFDA_DB.exists()})")
    print(f"Snapshots:   {len(SNAPSHOT_ORDER)} ({SNAPSHOT_ORDER[0]} → {SNAPSHOT_ORDER[-1]})")

    timelines = load_oncology_timelines(INVIMA_DB)
    print(f"Formulations (INN, producto_canonical) tuples: {len(timelines)}")

    h1 = evaluate_h1(timelines)
    print()
    print("─" * 80)
    print(f"H1 verdict: {h1['verdict']}")
    print(f"  reason:                {h1['reason']}")
    print(f"  qualifying formulations:    {h1['n_qualifying']}")
    print(f"  left-truncated formulations: {h1['n_left_truncated']}")
    print(f"  lead-times (snapshots):     {h1['leads_snapshots']}")
    print(f"  median lead-time:           {h1['median_lead_snapshots']}")
    if h1["qualifying_detail"]:
        print("  qualifying cases:")
        for q in h1["qualifying_detail"]:
            inn, prod = q["key"]
            print(f"    - {inn:14s} | {prod[:50]:50s} | warn={q['first_warn_period']} → short={q['first_short_period']} | lead={q['lead_snapshots']}")

    openfda_dates = load_openfda_first_postings(OPENFDA_DB)
    print()
    print("─" * 80)
    print(f"openFDA earliest posting dates by INN: {len(openfda_dates)} matched")
    for inn, d in sorted(openfda_dates.items()):
        print(f"    {inn:18s} {d.isoformat()}")

    h2 = evaluate_h2(timelines, openfda_dates)
    print()
    print("─" * 80)
    print(f"H2 verdict: {h2['verdict']}")
    print(f"  reason:           {h2['reason']}")
    print(f"  matched drugs:    {h2['n_matched']}")
    print(f"  lead-days:        {h2['leads_days']}")
    print(f"  median lead-days: {h2['median_lead_days']}")
    if h2["matched_detail"]:
        print("  matched detail:")
        for m in h2["matched_detail"]:
            print(f"    - {m['inn']:14s} | openFDA {m['openfda_date']} → INVIMA {m['invima_period']} ({m['invima_date_approx']}) | lead={m['lead_days']}d")

    h3 = evaluate_h3(timelines)
    print()
    print("─" * 80)
    print(f"H3 verdict: {h3['verdict']}")
    print(f"  reason:                            {h3['reason']}")
    print(f"  observable WITH prior signal:       {h3['n_observable_with_signal']}")
    print(f"  observable WITHOUT prior signal:    {h3['n_observable_without_signal']}")
    print(f"  left-truncated (already discontinued): {h3['n_left_truncated']}")
    print(f"  pct with signal:                    {h3['pct_with_signal']}")

    h4 = evaluate_h4(timelines)
    print()
    print("─" * 80)
    print(f"H4 verdict: {h4['verdict']}")
    print(f"  reason:          {h4['reason']}")
    print(f"  qualifying INNs: {h4['n_qualifying']} | median lead: {h4['median_lead_snapshots']} snapshots")
    print(f"  {'INN':<20} {'first_warn':<14} {'first_short':<14} {'lead':<6} {'qualifying'}")
    for r in h4["rows"]:
        print(f"  {r['inn']:<20} {str(r['first_warn_period']):<14} {r['first_short_period']:<14} "
              f"{str(r['lead_snapshots']):<6} {r['qualifying']}")

    summary = build_summary_table(timelines)
    print()
    print("─" * 80)
    print("ALL ONCOLOGY FORMULATIONS — TIMELINE SUMMARY")
    print(f"{'INN':<14} | {'PRODUCTO_CANONICAL':<50} | {'1st_obs':<10} | {'estado':<22} | {'warn':<8} | {'short':<8} | {'disc':<8} | {'lead':<5} | LT")
    for s in summary:
        print(f"{s['inn']:<14} | {s['producto_canonical']:<50} | {s['first_obs_period']:<10} | {s['first_obs_estado'] or '-':<22} | "
              f"{s['first_warn_period'] or '-':<8} | {s['first_short_period'] or '-':<8} | {s['first_disc_period'] or '-':<8} | "
              f"{str(s['observable_lead_snapshots']) if s['observable_lead_snapshots'] is not None else '-':<5} | "
              f"{'Y' if s['left_truncated'] else 'N'}")

    if args.json:
        out = {
            "snapshot_order":  SNAPSHOT_ORDER,
            "n_formulations":  len(timelines),
            "h1": h1, "h2": h2, "h3": h3,
            "summary":         summary,
        }
        Path(args.json).write_text(json.dumps(out, indent=2, default=str))
        print(f"\nFull results written to {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
