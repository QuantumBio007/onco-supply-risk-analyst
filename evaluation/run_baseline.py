"""
run_baseline.py — Generate prompt-only (no RAG) briefs for evaluation Cases 1-3.

Run from Project root:
    python3 evaluation/run_baseline.py

Outputs:
    evaluation/outputs/case1_prompt_only.txt
    evaluation/outputs/case2_prompt_only.txt
    evaluation/outputs/case3_prompt_only.txt
"""
import anthropic
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
os.makedirs("evaluation/outputs", exist_ok=True)

CASES = [
    ("cisplatin",    "Argentina", "Baseline",              "case1_prompt_only.txt"),
    ("trastuzumab",  "Venezuela", "Baseline",              "case2_prompt_only.txt"),
    ("cisplatin",    "Argentina", "API export restriction", "case3_prompt_only.txt"),
    ("doxorubicin",  "Colombia",  "Currency devaluation",  "case4_prompt_only.txt"),
    ("carboplatin",  "Venezuela", "Combined shock",         "case5_prompt_only.txt"),
]

SYSTEM_PROMPT = """You are an expert supply-chain analyst at JCNB Biotech Consulting \
specializing in oncology drug shortage risk in Latin America.

Output format — use exactly these section headers:
## Drug Profile
## Supply Chain Vulnerability
## Scenario Impact Analysis
## Policy Recommendations
## Confidence & Limitations

Never provide clinical advice or drug substitution recommendations."""

client = anthropic.Anthropic()

for drug, country, scenario, outfile in CASES:
    print(f"Generating: {drug} / {country} / {scenario} ...")
    # max_tokens differs deliberately across the eval harness:
    #   run_baseline.py = 1500 — prompt-only briefs run shorter (no retrieved
    #                            context to elaborate on; cuts truncation risk
    #                            without artificially inflating their length).
    #   run_rag.py      = 2500 — RAG briefs need more headroom to summarize
    #                            ~2,000 tokens of retrieved context + sources.
    #   agent_core.py   = 2000 — per-iteration cap inside agentic loop; not
    #                            the full brief budget.
    #   run_judge.py    = 2000 — JSON-only scoring output; needs no more.
    # Standardizing would either truncate RAG briefs or pad baseline ones —
    # both would distort the comparison. Intentional, not drift.
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"Generate a Drug Shortage Risk Brief for {drug} in {country} "
                f"under scenario: {scenario}"
            ),
        }],
    )
    brief = response.content[0].text
    outpath = os.path.join("evaluation", "outputs", outfile)
    with open(outpath, "w") as f:
        f.write(f"CASE: {drug} / {country} / {scenario}\n")
        f.write("SOURCE: prompt-only (no RAG context)\n")
        f.write("=" * 60 + "\n\n")
        f.write(brief)
    print(f"  Saved → {outpath}")

print("\nDone. Run evaluation/run_rag.py next to generate RAG outputs.")
