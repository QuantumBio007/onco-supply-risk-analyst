# OncoSupply Risk Analyst

**AI-powered drug shortage risk briefs for Latin America oncology procurement.** Generates structured risk assessments for supply chain disruptions (API restrictions, currency devaluation, combined shocks) in Argentina, Colombia, and Venezuela.

---

## Business Context

Oncology drug shortages in Latin America create dual risks: **patient outcomes** (treatment delays) and **regulatory exposure** (compliance failures under WHO and national procurement standards). This system generates **structured, sourced risk briefs** in minutes—replacing weeks of manual research.

**Coverage:** 4 essential drugs (cisplatin, carboplatin, doxorubicin, trastuzumab) × 3 countries × 4 scenarios = 48 risk profiles. Each brief cites procurement data, supply chain facts, and Monte Carlo simulation results.

---

## Evaluation: Perfect Performance

RAG (Retrieval-Augmented Generation) **outperforms prompt-only generation on all test cases.**

| Case | Drug | Country | Scenario | RAG | Prompt-Only | RAG Advantage |
|------|------|---------|----------|-----|-------------|---------------|
| 1 | Cisplatin | Argentina | Baseline | **12/12** | 7/12 | +5 |
| 2 | Trastuzumab | Venezuela | Baseline | **12/12** | 10/12 | +2 |
| 3 | Cisplatin | Argentina | API Restriction | **12/12** | 9/12 | +3 |
| 4 | Doxorubicin | Colombia | Currency Devaluation | **12/12** | 6/12 | +6 |
| 5 | Carboplatin | Venezuela | Combined Shock | **12/12** | 8/12 | +4 |
| **AVERAGE** | — | — | — | **12/12 (100%)** | **8/12 (67%)** | **+4.0 pts** |

**Methodology:** Model-as-judge pipeline (Claude Haiku 4.5 scoring each brief against 12-item fact checklist per case, 60 total items). All 5 cases evaluated independently. RAG wins 5/5.

**Key insight:** RAG dominates where **institutional & regulatory context is required** — procurement channels, WHO EML status, ANMAT/INVIMA dynamics, fragmentation. Prompt-only hallucinates or omits.

---

## How It Works

### Architecture

```
Input (drug, country, scenario)
    ↓
[Retrieval] ChromaDB semantic search (all-mpnet-base-v2, 768-dim)
    ├─ KB docs: 9 procurement + drug profile documents
    ├─ Sim outputs: 48 Monte Carlo inventory model results
    └─ Returns: Top 5 relevant chunks (~2,000 tokens context)
    ↓
[Generation] Claude + agentic tool use
    ├─ Tool 1: search_kb() — retrieves context
    ├─ Tool 2: run_simulation() — live Monte Carlo (500 runs, ~5 sec)
    └─ Tool 3: web_search() — (optional, disabled in eval mode)
    ↓
Output: Structured risk brief (5 sections, ~800 words)
    ├─ Drug Profile
    ├─ Supply Chain Vulnerability
    ├─ Scenario Impact Analysis
    ├─ Policy Recommendations
    └─ Confidence & Limitations
```

### Knowledge Base

**11 domain documents** (total ~4,500 words, sourced and peer-reviewed):
- **Argentina:** Procurement channels (public, obras sociales, provincial, private), ANMAT, PAMI, DNU 70/2023, cepo chronology
- **Colombia:** EPS-IPS structure, INVIMA, MIPRES Constitutional Court ruling (COP 819B), tutela volume surge, biosimilar availability
- **Venezuela:** Structural failure (OFAC, diaspora Zelle mechanism, SIVERC), 28.4% shortage rate (WHO 2023), currency collapse
- **Drugs:** Cisplatin (India/China API, generic), Trastuzumab (biologic, cold chain, $$$), Doxorubicin (shortage history 2011–12, 2022–23), Carboplatin (shared platinum supply chain)
- **Cross-cutting:** WHO EML oncology section, API concentration risk (India 30–40%, China 25–35% of global supply)

**Evidence grounding:**
- Clark & Scarf (1960) — foundational (Q,r) inventory theory
- Graves & Willems (2000) — dynamic demand modeling  
- Zipkin (2000) — service-level metrics
- Izen et al. (2025) — fill-rate reduction under API disruption (PMID 41002874)
- Badejo & Ierapetritou (2022) — disruption duration (geometric distribution)

### Simulation Model

**Monte Carlo (Q,r) inventory:**
- 500 runs per scenario, 365 days/year
- **Poisson demand** (zero-demand days realistic for volatile markets)
- **Lead time variability:** baseline 10d → export restriction 30d
- **Service level:** both unit-based and day-based metrics
- **Scenario mapping:**
  - Baseline: nominal
  - API restriction: lead_time ×3, fill_rate ×0.55 (Izen 2025)
  - Currency devaluation: daily_demand +50% (peso erosion reduces buying power)
  - Combined: both restrictions simultaneously

**Output:** Stockout days/year, service level %, probability of critical shortage (p > 20 days/month).

---

## Setup (5 minutes)

### Prerequisites
- Python 3.10+ (check: `python3 --version`)
- Anthropic API key ([create one](https://console.anthropic.com); $10 monthly spend limit recommended)
- 5 GB disk (embedding model ~420 MB, ChromaDB ~10 MB, sim outputs ~2 MB)

### Installation

```bash
# Clone
git clone https://github.com/QuantumBio007/onco-supply-risk-analyst.git
cd onco-supply-risk-analyst

# Virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
# First time: ~2 min (downloads ~500 MB of packages)

# Set API key (never hardcode in files; never commit to git)
export ANTHROPIC_API_KEY="sk-ant-..."
# Verify it works:
python3 -c "import anthropic; print('✓ API key OK')"
```

**API Cost:** First 5-minute index build is free (no API calls). Running the app ~$0.01–$0.05 per brief (Haiku is cheap). Full evaluation (10 briefs) ~$0.10. Set a $10/month limit in the Anthropic console as a safeguard.

### Build the Vector Index (5 minutes, first time only)

```bash
python3 knowledge_base/build_index.py
```

This:
1. Loads all KB docs and 48 simulation files
2. Downloads embedding model (all-mpnet-base-v2, ~90 MB on first run)
3. Creates ChromaDB index (155 chunks, persistent to `./chroma_db/`)
4. Prints: `Indexed 155 chunks from 57 files`

---

## Run the App

```bash
python3 -m streamlit run app/app.py
```

Opens at `http://localhost:8501`. 

**UI:**
- **Sidebar:** Select drug, country, scenario
- **Main:** Risk brief with 5 sections
- **Expander:** Retrieved sources (show your work)

**Example workflow:**
1. Drug: Cisplatin
2. Country: Argentina
3. Scenario: API Export Restriction
4. Click "Generate Risk Brief"
5. Read brief (30 sec) + review sources (expander)

---

## Run the Evaluation

Reproduces the 12/12 vs 8/12 scores. Generates all briefs and scores them with model-as-judge.

```bash
# Step 1: RAG briefs (all 5 cases)
python3 evaluation/run_rag.py

# Step 2: Prompt-only briefs (baseline)
python3 evaluation/run_baseline.py

# Step 3: Score both with model-as-judge
python3 evaluation/run_judge.py

# Results
cat evaluation/outputs/judge_results.txt  # human-readable
cat evaluation/outputs/judge_scores.json  # machine-readable
```

**Runtime:** ~2 minutes total (API calls are sequential, not parallelized).

**Fact checklist:** See `evaluation/checklists/case*.md` for the 12 items each brief must hit (e.g., "Mentions works sociales," "Includes confidence & limitations section").

---

## Project Structure

```
app/
  app.py                      Streamlit UI + agentic tool loop
knowledge_base/
  docs/                       9 KB documents (searchable context)
  sim_outputs/                48 Monte Carlo simulation outputs
  build_index.py              Creates ChromaDB vector database
  run_sims.py                 Generates all simulation files
evaluation/
  checklists/                 5 fact checklists (case1–case5)
  outputs/                    Generated briefs + judge scores
  run_rag.py                  Brief generation (with RAG)
  run_baseline.py             Brief generation (no context)
  run_judge.py                Model-as-judge scoring
supply_sim.py                 Monte Carlo (Q,r) inventory model
requirements.txt              Dependencies (pip install)
TRACKER.md                    Development log + session notes
README.md                     This file
```

---

## Limitations & Caveats

**Model:**
- Claude Haiku for speed; larger models (Sonnet, Opus) not evaluated
- Model-as-judge scoring is **not** clinical/regulatory validation—it's a proxy for fact coverage

**Simulation:**
- Simplified (Q,r) model; doesn't capture cold-chain logistics or political risk (expropriation, violence)
- **Demand distribution:** Poisson assumes mean demand is stable; actual markets may have regime shifts
- **Lead time:** Geometric distribution (Badejo 2022), not empirical import duration data
- **Fill rate:** Izen et al. (2025) baseline (55% reduction under API restriction) is **indicative**, not binding

**Data:**
- KB procurement docs curated from public sources (WHO, government, academic); not proprietary supply-chain data
- Venezuela data as of 2025; hyperinflation and currency regime shifts can render assumptions obsolete within months
- Colombia EPS-IPS debt figures are official (2024); structural parameters are stable but budget dynamics may have shifted
- Argentina regulatory/procurement landscape stable through 2025

**Coverage:**
- Only 4 drugs (essential generics + 1 biologic); no P&T formulary dynamics
- Only 3 countries; no Central America, Caribbean, or Brazil
- Only 4 scenarios; complex second-order effects (e.g., hoarding behavior) not modeled

---

## Deployment (Streamlit Cloud)

To share a live link with graders:

```bash
# 1. Ensure no secrets are in the repo
grep -r "sk-ant" . --include="*.py"  # should return nothing
git status                           # should show no uncommitted changes

# 2. Push to GitHub
git add -A
git commit -m "Final evaluation: 100% RAG (12/12 all cases)"
git push origin main

# 3. Go to https://share.streamlit.io
# → "New app"
# → Connect GitHub repo (QuantumBio007/onco-supply-risk-analyst)
# → Runtime settings → Secrets → add ANTHROPIC_API_KEY
# → Deploy

# 4. Share the link (e.g., https://onco-supply-risk-analyst.streamlit.app)
```

**Note:** First load takes ~10 sec (embedding model initialization); subsequent loads <1 sec.

---

## For Graders

This system is **ready to evaluate.** To verify:

1. **Clone & run:**
   ```bash
   git clone https://github.com/QuantumBio007/onco-supply-risk-analyst.git
   cd onco-supply-risk-analyst
   pip install -r requirements.txt
   export ANTHROPIC_API_KEY="your-key"
   python3 knowledge_base/build_index.py
   python3 -m streamlit run app/app.py
   ```

2. **Test a case:** Drug=Cisplatin, Country=Argentina, Scenario=Baseline. Brief should mention obras sociales, API concentration, fragmentation, and quantitative risk.

3. **Reproduce evaluation:**
   ```bash
   python3 evaluation/run_rag.py      # ~30 sec, generates case1–5_rag.txt
   python3 evaluation/run_baseline.py # ~30 sec, generates case1–5_prompt_only.txt
   python3 evaluation/run_judge.py    # ~1 min, scores all 10 outputs
   # View results:
   cat evaluation/outputs/judge_results.txt
   ```
   Expected output: RAG averages **12/12 across all 5 cases**; prompt-only averages **8/12**. Case-by-case variance expected due to model sampling (~±1 point), but RAG should win all 5 cases decisively. See `judge_results.txt` for item-by-item breakdown.

---

## Citation

If you use this system:
```
@software{oncosupply2025,
  title = {OncoSupply Risk Analyst: RAG-Based Drug Shortage Risk Assessment for Latin America},
  author = {Martino, Carlos},
  year = {2025},
  url = {https://github.com/QuantumBio007/onco-supply-risk-analyst}
}
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: No module named 'anthropic'` | Dependencies not installed | Run `pip install -r requirements.txt` |
| `AuthenticationError` when running app | API key not set or invalid | `export ANTHROPIC_API_KEY="sk-ant-..."` and verify via `python3 -c "import anthropic; anthropic.Anthropic()"` |
| `IndexError` in ChromaDB query | Index not built | Run `python3 knowledge_base/build_index.py` |
| Streamlit app won't load (blank page) | Port 8501 already in use | Kill prior Streamlit process: `lsof -ti:8501 \| xargs kill -9` |
| Brief is generic/missing context | Retrieval failed (doc not in index) | Verify `knowledge_base/docs/` is populated (should have 9 files); rebuild index. |
| Evaluation scores very different from table above | Model sampling variance | This is expected (±1–2 point variance). RAG should still win all 5 cases. Check `judge_results.txt` for item-level detail. |

## Questions?

- **"How do I change the scenario thresholds?"** Edit `supply_sim.py` (lead_time, daily_demand parameters).
- **"Can I add a new drug?"** Add a profile doc to `knowledge_base/docs/`, rebuild index, test retrieval. Add to UI dropdown.
- **"What if my API key runs out?"** Set a monthly spend limit in the Anthropic console (Billing → Usage limits). The system will error gracefully.
- **"Is this production-ready?"** No. Use for research/demos only. Clinical/regulatory deployment requires validated procurement data, audit logs, and compliance review per local healthcare authorities.

---

**Last updated:** 2026-04-30 | **Evaluation date:** 2026-04-30 (Session 9, Poisson demand model, 256-token chunks, all-mpnet-base-v2 embedding)
