"""
smoke_phase2_no_news.py — Phase 2 end-to-end smoke test WITHOUT NewsAPI.

Mocks the news-fetch layer with hand-crafted articles, runs them through
the REAL `event_classifier` (Claude Haiku) → REAL `shock_mapper` → REAL
`alert_engine`. Tests the full pipeline minus the NewsAPI dependency,
so it can be re-run any number of times without burning your 100/day
NewsAPI quota.

Cost per run: ~$0.005 total (Claude Haiku, ~5 classification calls).
Runtime: ~15 seconds.

Run:
    cd "<project root>"
    source .venv/bin/activate
    python3 -m optimized.smoke_phase2_no_news

Use this BEFORE any live cycle to confirm:
  • ANTHROPIC_API_KEY is loaded and the classifier returns valid JSON
  • shock_mapper resolves dynamic vs fallback paths correctly
  • alert_engine fires the expected severity tiers
  • format_alert renders cleanly

The articles below are illustrative — swap in any title/description to
test specific scenarios. They cover the four canonical shock pathways:
manufacturing, logistics, currency, macro_economic.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phase2_realtime.event_classifier import classify_article
from phase2_realtime.shock_mapper import trigger_simulation
from phase2_realtime.alert_engine import evaluate_risk_change, format_alert


# Hand-crafted "news articles" — each represents a realistic shock signal.
# These bypass NewsAPI entirely; the classifier sees only title+description.
MOCK_ARTICLES = [
    {
        "label": "manufacturing CRITICAL — direct API factory disruption",
        "title": "Indian API maker Aurobindo halts Hyderabad production after FDA Form 483",
        "description": (
            "Aurobindo Pharma announced an indefinite shutdown of its Hyderabad "
            "API facility following a Form 483 from the FDA citing critical "
            "GMP violations. The facility produces ~22% of global cisplatin API. "
            "Industry analysts expect 90+ day disruption to platinum-based "
            "chemotherapy supply across Latin American import markets."
        ),
        "drug": "cisplatin",
        "country": "Argentina",
    },
    {
        "label": "logistics CRITICAL — Hormuz closure (precedence test)",
        "title": "Iran closes Strait of Hormuz; pharmaceutical APIs face 20-day delay",
        "description": (
            "Iran announced closure of the Strait of Hormuz over new sanctions. "
            "Pharmaceutical APIs from India transit this route to LATAM ports. "
            "Industry expects 20-day delays on cisplatin, doxorubicin, and "
            "trastuzumab shipments to Buenos Aires and Santos."
        ),
        "drug": "doxorubicin",
        "country": "Argentina",
    },
    {
        # Colombia/cisplatin: EPS-IPS debt cascade makes budget compression bite harder
        # than Argentina/trastuzumab (baseline 3.8d too low to show macro delta).
        "label": "macro_economic MODERATE — indirect budget compression",
        "title": "Expensive tortillas, fewer buses: war in Iran squeezes Latin America",
        "description": (
            "Argentina: fuel +20%, air fares +24%, intercity transport +22%, "
            "inflation 3.4% in March. Economist Hugo Vasques (UBA): impact not "
            "yet fully realized, will be felt at least until mid-year. Health "
            "ministry budgets in Argentina, Colombia, and Peru face material "
            "compression as USD-priced imports become more expensive."
        ),
        "drug": "cisplatin",
        "country": "Colombia",
    },
    {
        "label": "currency MODERATE — peso devaluation",
        "title": "Argentine peso drops 18% as central bank intervention fails",
        "description": (
            "The Argentine peso fell 18% against the dollar overnight after "
            "the central bank's dollar reserve auction failed. Hospital "
            "procurement officers warn of immediate compression of oncology "
            "drug budgets, with imported biologics like trastuzumab most exposed."
        ),
        "drug": "trastuzumab",
        "country": "Argentina",
    },
    {
        "label": "irrelevant control — should classify IRRELEVANT",
        "title": "Lionel Messi scores hat-trick in Inter Miami win",
        "description": (
            "Argentine soccer star Lionel Messi scored three goals as Inter "
            "Miami defeated Toronto FC 4-1 in MLS action."
        ),
        "drug": "cisplatin",
        "country": "Argentina",
    },
]


def run_one(art: dict, idx: int, total: int) -> dict:
    print(f"\n{'='*78}\n[{idx}/{total}] {art['label']}\n{'='*78}")
    print(f"  Title: {art['title']}")

    t0 = time.perf_counter()
    classification = classify_article(art["title"], art["description"])
    t_classify = time.perf_counter() - t0
    print(f"  Classification ({t_classify*1000:.0f} ms):")
    print(f"    severity:   {classification.get('severity')}")
    print(f"    shock_type: {classification.get('shock_type')}")
    print(f"    drugs:      {classification.get('affected_drugs')}")
    print(f"    countries:  {classification.get('affected_countries')}")
    impact = classification.get("impact") or {}
    if impact:
        print(f"    impact:     LT={impact.get('lead_time_multiplier')} "
              f"D={impact.get('demand_multiplier')} "
              f"fill={impact.get('fill_rate')} "
              f"bud={impact.get('budget_multiplier')}")
    print(f"    reasoning:  {classification.get('reasoning', '')[:120]}")

    if classification.get("severity") == "IRRELEVANT":
        print("  → IRRELEVANT, skipping simulation (pipeline correctly filters)")
        return {"label": art["label"], "skipped": True}

    t0 = time.perf_counter()
    shock = trigger_simulation(classification, art["drug"], art["country"])
    t_sim = time.perf_counter() - t0
    print(f"  Simulation ({t_sim*1000:.0f} ms): mode={shock.get('simulation_mode')}  "
          f"baseline={shock.get('baseline_risk')}d  shocked={shock.get('shocked_risk')}d  "
          f"Δ={shock.get('risk_delta')}d")

    if shock.get("status") != "simulated":
        print(f"  → simulation status={shock.get('status')}")
        return {"label": art["label"], "shock": shock}

    alert = evaluate_risk_change(
        shock["baseline_risk"], shock["shocked_risk"],
        baseline_cvar=shock.get("baseline_cvar_90"),
        shocked_cvar=shock.get("shocked_cvar_90"),
    )
    print(f"  Alert: {alert['severity']}  (triggers: {','.join(alert['triggers']) or '—'})")
    print(f"  Should alert: {alert['should_alert']}")
    print()
    print(format_alert(alert, art["drug"], art["country"], art["title"]))
    return {"label": art["label"], "alert": alert, "shock": shock}


def main() -> int:
    print("=" * 78)
    print("PHASE 2 SMOKE TEST — no NewsAPI, real Claude, real simulation")
    print("=" * 78)
    print(f"Articles: {len(MOCK_ARTICLES)}  "
          f"(estimated cost: ~$0.005 on Haiku, ~$0 on cached prompt)")

    results = []
    t0 = time.perf_counter()
    for i, art in enumerate(MOCK_ARTICLES, 1):
        try:
            results.append(run_one(art, i, len(MOCK_ARTICLES)))
        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            results.append({"label": art["label"], "error": str(e)})
    elapsed = time.perf_counter() - t0

    print("\n" + "=" * 78)
    print(f"SUMMARY ({elapsed:.1f}s total)")
    print("=" * 78)
    for r in results:
        if r.get("error"):
            print(f"  ✗ {r['label']:<60} ERROR: {r['error'][:60]}")
        elif r.get("skipped"):
            print(f"  ○ {r['label']:<60} (correctly skipped)")
        elif "alert" in r:
            sev = r["alert"]["severity"]
            sd  = r["shock"]["risk_delta"]
            mode = r["shock"]["simulation_mode"]
            print(f"  ✓ {r['label']:<60} {sev:<10} Δmean={sd:+.1f}d  [{mode}]")
        else:
            print(f"  ? {r['label']:<60} (unexpected state)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
