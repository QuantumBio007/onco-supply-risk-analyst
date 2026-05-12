"""
run_judge.py — Model-as-judge evaluation of RAG vs. prompt-only briefs.

Uses Claude to score each brief against the fact checklist.
Score: 1 = present and correct, 0 = absent, -1 = hallucinated (stated but false).

Run from Project root:
    python3 evaluation/run_judge.py

Prerequisites:
    python3 evaluation/run_baseline.py   # generates prompt-only outputs
    python3 evaluation/run_rag.py        # generates RAG outputs

Outputs:
    evaluation/outputs/judge_results.txt   (human-readable summary)
    evaluation/outputs/judge_scores.json   (machine-readable)
"""
import anthropic
import json
import os
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

CASES = [
    {
        "name": "Case 1: Cisplatin / Argentina / Baseline",
        "checklist": "evaluation/checklists/case1_cisplatin_argentina_baseline.md",
        "rag_output": "evaluation/outputs/case1_rag.txt",
        "baseline_output": "evaluation/outputs/case1_prompt_only.txt",
    },
    {
        "name": "Case 2: Trastuzumab / Venezuela / Baseline",
        "checklist": "evaluation/checklists/case2_trastuzumab_venezuela_baseline.md",
        "rag_output": "evaluation/outputs/case2_rag.txt",
        "baseline_output": "evaluation/outputs/case2_prompt_only.txt",
    },
    {
        "name": "Case 3: Cisplatin / Argentina / API Export Restriction",
        "checklist": "evaluation/checklists/case3_cisplatin_argentina_api_restriction.md",
        "rag_output": "evaluation/outputs/case3_rag.txt",
        "baseline_output": "evaluation/outputs/case3_prompt_only.txt",
    },
    {
        "name": "Case 4: Doxorubicin / Colombia / Currency Devaluation",
        "checklist": "evaluation/checklists/case4_doxorubicin_colombia_currency_devaluation.md",
        "rag_output": "evaluation/outputs/case4_rag.txt",
        "baseline_output": "evaluation/outputs/case4_prompt_only.txt",
    },
    {
        "name": "Case 5: Carboplatin / Venezuela / Combined Shock",
        "checklist": "evaluation/checklists/case5_carboplatin_venezuela_combined_shock.md",
        "rag_output": "evaluation/outputs/case5_rag.txt",
        "baseline_output": "evaluation/outputs/case5_prompt_only.txt",
    },
]

JUDGE_SYSTEM = """You are an expert evaluator assessing oncology drug supply chain briefs.

For each checklist item, score the brief as:
  1  = The brief contains this information and it is correct
  0  = The brief does not mention this item
 -1  = The brief states something false or hallucinated regarding this item

Return a JSON array. Each element must have exactly these keys:
  "item_number": integer
  "check": string (the check text)
  "score": integer (1, 0, or -1)
  "reasoning": string (one sentence explaining your score)

Return ONLY the JSON array. No preamble, no markdown fences."""


def extract_checks(checklist_path: str) -> list[dict]:
    """Parse numbered table rows from the checklist markdown."""
    checks = []
    with open(checklist_path) as f:
        for line in f:
            # Match table rows like: | 1 | Some check text | | |
            m = re.match(r"\|\s*(\d+)\s*\|\s*(.+?)\s*\|", line)
            if m:
                num = int(m.group(1))
                text = m.group(2).strip()
                # Skip header row
                if text.lower() != "check":
                    checks.append({"item_number": num, "check": text})
    return checks


def judge_brief(brief_text: str, checks: list[dict], client: anthropic.Anthropic) -> list[dict]:
    checks_str = "\n".join(f'{c["item_number"]}. {c["check"]}' for c in checks)
    user_msg = (
        f"BRIEF TO EVALUATE:\n{brief_text}\n\n"
        f"CHECKLIST ITEMS:\n{checks_str}\n\n"
        f"Score each item per the instructions."
    )
    # Judge model: Sonnet 4.5 (not Haiku) — removes same-model bias.
    # The brief generator (agent_core.py) uses Haiku 4.5; if the judge were
    # also Haiku, model-self-preference would inflate RAG scores. Using a
    # stronger, architecturally different judge is the standard practice for
    # rigorous model-as-judge evaluation. Cost is bounded: ~10 calls per eval,
    # ~$0.50 total. References: G-Eval (Liu et al. 2023), Zheng et al. 2023
    # LMSYS "Judging LLM-as-a-Judge" — both recommend stronger judges than
    # generators for credible scoring.
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=2000,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = response.content[0].text.strip()
    # Strip markdown fences if model includes them despite instructions
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def score_total(scored_items: list[dict]) -> int:
    return sum(item["score"] for item in scored_items)


client = anthropic.Anthropic()
all_results = []

os.makedirs("evaluation/outputs", exist_ok=True)
summary_lines = ["OncoSupply Risk Analyst — Model-as-Judge Evaluation", "=" * 60, ""]

for case in CASES:
    print(f"\n{'='*60}\n{case['name']}")
    checks = extract_checks(case["checklist"])

    missing = [k for k in ("rag_output", "baseline_output") if not os.path.exists(case[k])]
    if missing:
        print(f"  SKIP — missing files: {missing}")
        print(f"  Run run_rag.py and run_baseline.py first.")
        continue

    with open(case["rag_output"]) as f:
        rag_brief = f.read()
    with open(case["baseline_output"]) as f:
        baseline_brief = f.read()

    print("  Judging RAG output ...")
    rag_scores = judge_brief(rag_brief, checks, client)
    print("  Judging prompt-only output ...")
    baseline_scores = judge_brief(baseline_brief, checks, client)

    rag_total = score_total(rag_scores)
    baseline_total = score_total(baseline_scores)
    max_score = len(checks)

    result = {
        "case": case["name"],
        "max_score": max_score,
        "rag_total": rag_total,
        "baseline_total": baseline_total,
        "rag_items": rag_scores,
        "baseline_items": baseline_scores,
    }
    all_results.append(result)

    print(f"  RAG: {rag_total}/{max_score}  |  Prompt-only: {baseline_total}/{max_score}")

    summary_lines.append(case["name"])
    summary_lines.append(f"  RAG score:         {rag_total}/{max_score}")
    summary_lines.append(f"  Prompt-only score: {baseline_total}/{max_score}")
    summary_lines.append(f"  RAG advantage:     {rag_total - baseline_total:+d} points")
    summary_lines.append("")
    summary_lines.append("  Item-level breakdown:")
    for rs, bs in zip(rag_scores, baseline_scores):
        flag = "  " if rs["score"] == bs["score"] else "**"
        summary_lines.append(
            f"  {flag}[{rs['item_number']:2d}] RAG={rs['score']:+d} Baseline={bs['score']:+d}  {rs['check'][:70]}"
        )
        if rs["score"] != bs["score"]:
            summary_lines.append(f"       RAG note:  {rs['reasoning']}")
            summary_lines.append(f"       Base note: {bs['reasoning']}")
    summary_lines.append("")

# Write outputs
with open("evaluation/outputs/judge_results.txt", "w") as f:
    f.write("\n".join(summary_lines))

with open("evaluation/outputs/judge_scores.json", "w") as f:
    json.dump(all_results, f, indent=2)

print("\nSaved:")
print("  evaluation/outputs/judge_results.txt")
print("  evaluation/outputs/judge_scores.json")
