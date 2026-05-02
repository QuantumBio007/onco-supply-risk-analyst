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

SYSTEM_PROMPT = """You are a supply chain risk analyst evaluating pharmaceutical news for oncology drugs in LATAM.

CLASSIFICATION: Assign IRRELEVANT / MINOR / MODERATE / CRITICAL based on impact severity.

SHOCK TYPE: Identify the nature of the shock:
  - "manufacturing" - API factory disruption, labor strike, recall, quality issue in source countries (India, China)
  - "logistics" - Port congestion, shipping delays, road closures, border restrictions affecting LATAM
  - "regulatory" - Drug pricing policy, patent changes, approval delays, healthcare budget cuts
  - "demand" - Disease outbreak, hospital shortages, treatment guideline changes affecting patient volume
  - "currency" - FX volatility, devaluation affecting procurement costs
  - "political" - Government instability, trade war, sanctions, border closure
  - "climate" - Weather, flooding, landslides affecting ports/roads in LATAM
  - "company" - Manufacturer recalls, M&A, supply agreements

IMPACT PARAMETERS (if CRITICAL or MODERATE):
  - lead_time_multiplier: How much longer does delivery take? (e.g., 1.5 = 50% longer)
  - demand_multiplier: Does demand increase? (e.g., 1.2 = 20% higher demand, 0.8 = 20% lower)
  - fill_rate: Can suppliers meet demand? (e.g., 0.7 = only 70% of orders fulfilled)

Output JSON only, no explanation:
{
  "classification": "CRITICAL|MODERATE|MINOR|IRRELEVANT",
  "shock_type": "manufacturing|logistics|regulatory|demand|currency|political|climate|company",
  "affected_drugs": ["drug1", "drug2"],
  "affected_countries": ["country1"],
  "impact": {
    "lead_time_multiplier": 1.0,
    "demand_multiplier": 1.0,
    "fill_rate": 1.0
  },
  "reasoning": "one sentence explaining the shock"
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
            "classification": "IRRELEVANT",
            "affected_drugs": [],
            "affected_countries": [],
            "impact": {},
            "reasoning": f"Classification failed: {str(e)}",
        }


if __name__ == "__main__":
    # Test
    test_article = {
        "title": "Iran closes Strait of Hormuz over new sanctions",
        "description": "Iran announced closure of critical shipping lane. 30% of global oil passes through strait. Pharmaceutical APIs from India face 20-day delay.",
    }

    result = classify_article(test_article["title"], test_article["description"])
    print("Classification result:")
    import json

    print(json.dumps(result, indent=2))
