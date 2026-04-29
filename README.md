# OncoSupply Risk Analyst

AI-powered oncology drug shortage risk briefs for Latin America, built with RAG (Retrieval-Augmented Generation).

Given a drug, country, and disruption scenario, the system retrieves relevant supply chain context and simulation data, then generates a structured risk brief using Claude.

**Coverage:** Cisplatin, Doxorubicin, Carboplatin, Trastuzumab × Argentina, Colombia, Venezuela × Baseline, API Export Restriction, Currency Devaluation, Combined Shock

---

## Prerequisites

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com)

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/QuantumBio007/onco-supply-risk-analyst.git
cd onco-supply-risk-analyst

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your Anthropic API key (never hardcode it)
export ANTHROPIC_API_KEY="sk-ant-api03-..."

# 4. Generate simulation outputs (48 drug-country-scenario files)
python3 knowledge_base/run_sims.py

# 5. Build the vector index
python3 knowledge_base/build_index.py
```

Step 5 downloads the embedding model (~420 MB) on first run. Takes 3–5 minutes.

---

## Run the app

```bash
python3 -m streamlit run app/app.py
```

Opens at `http://localhost:8501`. Select a drug, country, and scenario, then click **Generate Risk Brief**.

---

## Run the evaluation

Evaluates RAG vs. prompt-only (no context) across 5 test cases using a model-as-judge pipeline.

```bash
python3 evaluation/run_rag.py        # generate RAG briefs (cases 1–5)
python3 evaluation/run_baseline.py   # generate prompt-only briefs (cases 1–5)
python3 evaluation/run_judge.py      # score all outputs, writes judge_results.txt
```

Results are written to `evaluation/outputs/judge_results.txt` and `judge_scores.json`.

---

## Project structure

```
app/
  app.py                        Streamlit app
knowledge_base/
  docs/                         9 KB documents (drug profiles, procurement systems)
  sim_outputs/                  48 Monte Carlo simulation outputs
  build_index.py                Builds ChromaDB vector index
  run_sims.py                   Generates simulation outputs
evaluation/
  checklists/                   Fact checklists for 5 test cases
  outputs/                      Generated briefs and judge scores
  run_rag.py / run_baseline.py  Brief generation scripts
  run_judge.py                  Model-as-judge scoring
supply_sim.py                   (Q,r) Monte Carlo inventory model
requirements.txt
```

---

## Evaluation results (session 4 — 150-token chunks)

| Case | RAG | Prompt-only | Notes |
|------|-----|-------------|-------|
| Cisplatin / Argentina / Baseline | 12/12 | 6/12 | RAG wins on PAMI, obras sociales, no domestic API |
| Trastuzumab / Venezuela / Baseline | 10/12 | 11/12 | Near-tie — Venezuela crisis is public knowledge |
| Cisplatin / Argentina / API Restriction | 10/12 | 4/12 | Strong RAG win — simulation data is decisive |

Cases 4–5 (Doxorubicin/Colombia and Carboplatin/Venezuela) scored after pipeline re-run with 256-token chunks.
