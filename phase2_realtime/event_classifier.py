"""
event_classifier.py — Classify news articles: are they supply chain shocks?

Uses Claude to classify each article:
  IRRELEVANT — Not about supply chain
  MINOR — Affects supply but limited impact
  MODERATE — Notable supply risk
  CRITICAL — Major supply chain threat

Returns: classification + affected drugs/countries + impact estimate
"""

import anthropic
import os
from pathlib import Path
from dotenv import load_dotenv

# Load API key — resolve absolute path from this file's location to handle
# any calling context (direct run, module import, -m invocation).
# override=True ensures we always use .env values even if shell env differs.
_project_dir = Path(__file__).resolve().parent.parent  # phase2_realtime/ → Project/
load_dotenv(str(_project_dir / ".env"), override=True)

SYSTEM_PROMPT = """You are a supply chain risk analyst evaluating news for oncology drug procurement risk in LATAM.

Your task: assess whether an article represents a supply chain shock — direct OR indirect —
that threatens drug availability for cancer patients in Argentina, Colombia, or Venezuela.
An article does NOT need to mention drugs or pharma to be relevant. Macro-economic and
geopolitical events that compress health procurement budgets are valid signals.

CLASSIFICATION: Assign IRRELEVANT / MINOR / MODERATE / CRITICAL based on impact severity.
  - IRRELEVANT: No plausible impact on pharmaceutical supply chains
  - MINOR: Limited, localized, or recoverable impact
  - MODERATE: Notable risk — supply disruption likely within 30-90 days
  - CRITICAL: Severe, immediate threat to drug availability

SHOCK TYPE: Identify the PRIMARY nature of the shock.

PRECEDENCE — apply BEFORE choosing a type:
  Direct supply-chain events ALWAYS override macro framing, even when the article
  also describes broader macro/geopolitical context. If ANY of the following is
  present in the article, classify by THAT event — NOT macro_economic:
    • API/drug factory shutdown, contamination, GMP failure → manufacturing
    • Port closure, shipping route disruption, customs backlog, road/rail closure,
      cold-chain failure in transit, "X-day delay" for APIs/drugs → logistics
    • Form 483, import alert, pricing controls, approval denial → regulatory
    • Sanctions, embargo, border closure, nationalization → political
    • Voluntary recall, M&A, supply contract change, bankruptcy → company
    • Flood, drought, hurricane affecting routes/production → climate
    • Disease outbreak, guideline change, hospital admission shifts → demand
    • Acute overnight FX event (peso crash) → currency

  macro_economic is RESERVED for articles where the mechanism is PURELY INDIRECT:
  commodity/inflation/geopolitical pressure on LATAM economies WITHOUT a specific
  factory, port, regulatory action, recall, FX event, or shipment delay. If both
  direct AND macro are present (e.g., "Hormuz closure AND 20-day API delay"), the
  direct event wins — macro is context, not the primary shock.

  Counterexample (do NOT misclassify): "Iran closes Strait of Hormuz; pharmaceutical
  APIs face 20-day delay" → logistics CRITICAL (NOT macro_economic). The 20-day
  delay is a direct, measurable supply event.

Type definitions:

  - "manufacturing" - Physical production capacity disrupted: API factory shutdown, GMP
    quality failure, labor strike at manufacturing site, equipment failure, contamination
    recall. KEY: disruption is to PHYSICAL PRODUCTION of APIs or drugs.

  - "logistics" - Movement of goods disrupted: port congestion, shipping delays, road/rail
    closures, customs bottlenecks, cold-chain failure in transit. KEY: drugs exist but
    cannot move.

  - "regulatory" - Government or agency ACTION on market access or compliance:
    FDA/ANVISA/COFEPRIS import alerts, Form 483 warnings, approval denials, drug pricing
    controls, patent rulings. FDA Form 483 = "regulatory" even if target is a factory.
    Healthcare budget policy changes = "regulatory".

  - "demand" - Patient-side volume changes: disease outbreak, cancer diagnosis surge,
    treatment guideline changes, hospital capacity shifts.
    Hospital budget CUTS reducing patient throughput = "demand", NOT "regulatory".

  - "currency" - DIRECT FX volatility: overnight peso/bolivar devaluation, exchange rate
    crisis, dollar-access restrictions. Use when the shock is an acute FX event itself,
    not an indirect macro pathway. If oil/commodity prices are the root cause, use
    "macro_economic" instead.

  - "political" - Government instability, trade wars, sanctions, border closures,
    nationalization. Use when mechanism is trade policy or physical border restriction.

  - "climate" - Weather events affecting LATAM logistics or production: flooding, landslides,
    drought. Agricultural disruptions that propagate to pharmaceutical excipients or chemical
    feedstocks are RELEVANT — do not dismiss as IRRELEVANT.

  - "company" - Firm-level events: voluntary recalls, M&A, supply agreement changes,
    bankruptcy.

  - "macro_economic" - INDIRECT macro pathway: external commodity or geopolitical shocks
    compressing LATAM health procurement budgets through inflation.

    WHEN TO USE: article describes (a) oil price surge, global inflation, commodity shock,
    or geopolitical conflict with economic spillover, AND (b) the mechanism to drug
    procurement is INDIRECT — through inflation eroding ministry of health budgets — not
    a direct supply chain event (no factory closed, no port blocked).

    CAUSAL CHAIN (recognize all links, not just the first):
      oil/commodity spike → LATAM import inflation → peso purchasing-power loss
      → health ministry USD-denominated budget compression
      → reduced oncology drug procurement volumes → stockout risk

    COUNTRY DIRECTIONALITY — required for correct country list:
    • Argentina, Colombia (consumers), Central America: NEGATIVE — oil importers;
      inflation compresses procurement budgets. Include, classify MODERATE–CRITICAL.
    • Venezuela: COMPLEX — oil exporter, but OFAC sanctions + production collapse
      (~700K bbl/day vs. 3.5M in 1990s) mean oil windfall does NOT reach MPPS drug
      procurement. Classify Venezuela as MINOR or omit unless article says otherwise.
    • Brazil: MIXED — Petrobras exporter benefits government; consumers still hurt.
      Include only if article specifically addresses Brazilian health budget impact.

    COLD-CHAIN SIGNAL: Air freight/air fare cost increases are a BUDGET shock, not a
    lead-time shock. Higher air freight costs mean the same procurement budget buys fewer
    doses — fold this into a lower budget_multiplier. Do NOT increase lead_time_multiplier
    for macro_economic shocks (that would cause policy adaptation to paradoxically reduce
    simulated stockouts). Set lead_time_multiplier=1.0 for macro_economic always.

    KEY: An article does NOT need to mention drugs or pharma to qualify. Quantified
    LATAM budget/inflation impact from an external shock = valid macro_economic signal.

DISAMBIGUATION EXAMPLES:
  - "FDA inspects Indian plant, issues Form 483" → regulatory
  - "Indian plant shuts down voluntarily after contamination" → manufacturing
  - "Brazil cuts healthcare budget 15%" → regulatory
  - "Hospital budget cuts reduce oncology admissions" → demand
  - "Argentina peso drops 25% overnight" → currency (direct FX event)
  - "Iran war: LATAM fuel prices surge 20%, air fares up 24%, inflation 3.4%/month"
    → macro_economic MODERATE, Argentina/Colombia (NOT Venezuela); lead_time_multiplier=1.0
    (air freight is a budget effect, not lead-time); budget_multiplier in low 0.7s
    (compute from cumulative inflation × duration, do not echo this exact number)
  - "Iran closes Strait of Hormuz; pharmaceutical APIs face 20-day delay"
    → logistics CRITICAL (NOT macro_economic — direct supply event takes precedence)
  - "IMF warns LATAM growth cut, oil shock stresses health budgets" → macro_economic MODERATE
  - "Oil hits $100/bbl, LATAM health ministers warn procurement budgets strained"
    → macro_economic CRITICAL, all LATAM importers
  - "Argentina imposes import restrictions on medical goods" → political
  - "Colombia flooding closes highway to port" → logistics
  - "Drought raises excipient prices" → climate MODERATE
  - "Pfizer recalls cisplatin batch" → company
  - "Trade tariffs raise cost of medical equipment imports in Argentina"
    → macro_economic MODERATE (tariff-driven cost inflation; same budget channel as oil)

AFFECTED DRUGS:
  Oncology drugs: cisplatin, carboplatin, doxorubicin, trastuzumab, paclitaxel,
  oxaliplatin, vincristine, methotrexate.
  For macro_economic shocks: trastuzumab is disproportionately affected (highest unit
  cost → most budget-sensitive; cold-chain → air freight sensitivity). If no specific
  drug is identifiable, return ["trastuzumab", "cisplatin", "carboplatin", "doxorubicin"].

AFFECTED COUNTRIES:
  LATAM focus: Argentina, Brazil, Colombia, Venezuela, Mexico, Peru, Chile.
  For macro_economic: list oil-importing/budget-constrained countries only
  (Argentina, Colombia, Peru, Chile) unless article explicitly names others.

IMPACT PARAMETERS (required for CRITICAL or MODERATE):

DERIVE EACH PARAMETER FROM ARTICLE SPECIFICS — do not echo the example values
below. Vary parameters per article based on the actual data quoted. If an article
describes acute panic (Hormuz closure, plant fire), demand_multiplier should rise
above 1.10. If suppliers are clearly stressed (sanctions, recall, GMP failure),
fill_rate should drop below 0.85. If an article quotes specific percentages,
compute parameters from those — do not fall back to mid-range defaults.

  - lead_time_multiplier: delivery time change (1.5 = 50% longer; 1.0 = unchanged)
    Derive from article-specific delay quotes. "20-day API delay" on a 35-day
    baseline → multiplier ≈ 1.6. Plant strike with no quoted delay but described
    as "weeks" → 1.3–2.0 depending on severity.
    macro_economic: ALWAYS 1.0 (air freight cost ≠ lead-time delay)

  - demand_multiplier: volume change (1.2 = +20%; 1.0 = unchanged)
    Direct shocks with panic ordering: 1.10–1.30
    Disease outbreak / guideline change: 1.20–1.50
    macro_economic: 1.03–1.08 (mild forward-buying)
    Hospital budget cuts reducing throughput: 0.80–0.95

  - fill_rate: supplier fulfillment fraction (0.7 = 70% of orders fill; 1.0 = full)
    Direct manufacturing/logistics shock: 0.40–0.70 (severe allocation cuts)
    Regulatory pricing controls: 0.75–0.85 (vendor exit at margin)
    macro_economic: 0.85–0.95 (shock is budget/demand side, supply capacity intact)

  - budget_multiplier: procurement budget fraction remaining (0.6 = 40% cut; 1.0 = none)
    macro_economic: derive from cumulative-inflation arithmetic.
      Worked example (DO NOT copy verbatim — article specifics vary):
      X%/month inflation × N months → real-USD budget erosion.
      Then estimate the multiplier as 1 / (1 + cumulative_inflation).
      For CRITICAL (>25% compression): multiplier in 0.55–0.75 range.
      For MODERATE (10–25% compression): multiplier in 0.75–0.90 range.
    Direct currency devaluation: 0.50–0.70
    Regulatory budget cuts: derive from article-quoted % cut
    Manufacturing/logistics shocks (no budget channel): 1.0

Output JSON only, no explanation, no markdown:
{
  "severity": "CRITICAL|MODERATE|MINOR|IRRELEVANT",
  "shock_type": "manufacturing|logistics|regulatory|demand|currency|political|climate|company|macro_economic",
  "affected_drugs": ["drug1", "drug2"],
  "affected_countries": ["country1"],
  "impact": {
    "lead_time_multiplier": 1.0,
    "demand_multiplier": 1.0,
    "fill_rate": 1.0,
    "budget_multiplier": 1.0
  },
  "reasoning": "one sentence: transmission chain from event to LATAM oncology drug procurement impact"
}
"""


def classify_article(title: str, description: str) -> dict:
    """
    Classify a news article using Claude.

    Args:
        title: Article headline
        description: Article summary

    Returns:
        dict with classification, affected_drugs, affected_countries, impact
    """
    # Explicitly pass API key to client
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not api_key.strip():
        raise ValueError("ANTHROPIC_API_KEY not found or empty in environment")

    client = anthropic.Anthropic(api_key=api_key)

    user_msg = f"""Classify this article:

Title: {title}
Description: {description}
"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )

        import json
        import re

        # Strip markdown code blocks if present
        raw_text = response.content[0].text
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

        result = json.loads(raw_text)
        return result

    except Exception as e:
        print(f"[event_classifier] Error: {e}")
        return {
            "severity": "IRRELEVANT",
            "affected_drugs": [],
            "affected_countries": [],
            "impact": {},
            "reasoning": f"Classification failed: {str(e)}",
        }


if __name__ == "__main__":
    import json

    tests = [
        {
            "label": "Direct logistics (Hormuz closure, pharma mentioned)",
            "title": "Iran closes Strait of Hormuz over new sanctions",
            "description": "Iran announced closure of critical shipping lane. 30% of global oil passes through strait. Pharmaceutical APIs from India face 20-day delay.",
        },
        {
            "label": "Macro-economic (CNN Iran/LATAM article — NO pharma keywords)",
            "title": "Expensive tortillas, fewer buses: How war in Iran is squeezing Latin America",
            "description": "From rising fuel prices to the frequency of public transport and the cost of popular foods like tortillas, Latin American households feel strained. Argentina: fuel +20%, air fares +24%, intercity transport +22%, inflation 3.4% in March. Economist: impact not yet fully realized, will be felt at least until mid-year.",
        },
        {
            "label": "Macro-economic (oil price threshold)",
            "title": "Oil reaches $100 per barrel — Latin American health ministries warn of budget pressure",
            "description": "Brent crude surpassed $100/bbl for the first time since 2022. Argentina, Colombia, and Peru health ministers issued joint statement warning that oncology drug procurement budgets face 20-30% compression if prices hold through Q3.",
        },
    ]

    for t in tests:
        print(f"\n=== {t['label']} ===")
        result = classify_article(t["title"], t["description"])
        print(json.dumps(result, indent=2))
