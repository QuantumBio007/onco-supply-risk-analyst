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
from pathlib import Path
from dotenv import load_dotenv

# Load API key
load_dotenv(Path(__file__).parent.parent / ".env")

SYSTEM_PROMPT = """You are a supply chain risk analyst evaluating pharmaceutical news.

Classify each article as: IRRELEVANT / MINOR / MODERATE / CRITICAL

If CRITICAL or MODERATE:
  - Identify affected drugs (cisplatin, trastuzumab, doxorubicin, carboplatin, or "unknown")
  - Identify affected countries (Argentina, Colombia, Venezuela, or "unknown")
  - Estimate impact: which supply chain parameter changes?
    * lead_time_multiplier (e.g., "1.5x" if delays expected)
    * demand_multiplier (e.g., "1.2x" if hoarding expected)
    * fill_rate (e.g., "0.7" if partial fulfillment expected)

Output JSON only, no explanation:
{
  "classification": "CRITICAL|MODERATE|MINOR|IRRELEVANT",
  "affected_drugs": ["drug1", "drug2"],
  "affected_countries": ["country1"],
  "impact": {
    "lead_time_multiplier": null,
    "demand_multiplier": null,
    "fill_rate": null
  },
  "reasoning": "one sentence"
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
    client = anthropic.Anthropic()

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
