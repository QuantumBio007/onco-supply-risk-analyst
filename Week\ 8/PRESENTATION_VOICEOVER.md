# OncoSupply Risk Analyst — Presentation Voiceover Script

**Target Audience:** MBA instructors, biotech industry stakeholders  
**Duration:** 12-15 minutes  
**Format:** Step-by-step presentation with live demo  
**Key Message:** RAG (Retrieval-Augmented Generation) is essential for analyzing drug shortage risk in fragmented healthcare systems.

---

## PART 1: THE PROBLEM (1:30 — 2:00 minutes)

### Opening Hook
"Imagine you're a cancer patient in Argentina. Your oncologist prescribes cisplatin—a drug that's been treating cancer for 45 years. Standard treatment. But when the pharmacy calls your insurance company, there's a problem: the drug isn't available. Not because it doesn't exist globally. Not because it's expensive. But because it's stuck in a supply chain so fragmented that no one knows where it is.

This is the problem I'm solving."

### The Scope
"Oncology drug shortages in Latin America aren't hypothetical. In 2023–2024, cisplatin and carboplatin—two platinum-based chemotherapy agents—disappeared from US supply for over a year. In Argentina, Venezuela, and Colombia, the situation is chronic.

Why? Three reasons:
1. **API concentration:** 80% of cisplatin's active ingredient comes from India and China. One factory shutdown, one export restriction, and global supply collapses.
2. **Procurement fragmentation:** Argentina has 8 independent drug procurement channels—public hospitals, insurance funds, provincial systems, private pharmacies. They don't talk to each other. A hospital can face shortage while another channel has surplus stock sitting unused.
3. **Regulatory lag:** If you find an alternative supplier, it takes 12–18 months for ANMAT (Argentina's drug regulator) to approve them. During a crisis, that's too slow.

The result? Patients don't get cancer treatment. Hospitals can't plan. Regulators fly blind."

### Why It Matters
"This isn't just a supply chain problem—it's a patient outcomes problem. Every day of delay in chemotherapy is a day cancer cells divide unchecked. It's also a regulatory and market risk for pharmaceutical companies and healthcare systems."

---

## PART 2: WHO I AM & THE COMPANY (1:00 minute)

"I'm Carlos Martino, an MBA student at Johns Hopkins Carey School of Business. I have a background in biotech consulting. I was brought in to help JCNB Biotech Consulting, a consulting firm that advises pharmaceutical companies and health systems on supply chain risk.

Their business question was: **'Can AI help us rapidly assess oncology drug shortage risk in Latin America so our clients can act before supply fails?'**

The answer is yes—but only if we do it right."

---

## PART 3: THE APPROACH — WHY RAG? (2:00 minutes)

### The Core Challenge
"Here's the hard part: drug shortage risk isn't one-dimensional. It's not 'Is there demand?' It's a web of interdependencies:

- **What** is the drug? (Generic? Biologic? Cold-chain requirement?)
- **Where** is it made? (Single-source API risk?)
- **How** is it procured in this country? (Fragmented? Centralized?)
- **What** could disrupt supply? (Geopolitical? Currency? Regulatory?)
- **What** does that disruption cost? (Lives? Days of delay?)

A junior analyst would spend weeks researching. A consultant using ChatGPT directly would get hallucinations and missing context. A database query would miss the narrative.

That's why I chose **Retrieval-Augmented Generation (RAG).**"

### What Is RAG?
"RAG has three steps:

**1. Retrieve:** Before generating anything, search a knowledge base of sourced documents. 
   - My KB has 11 documents: drug profiles, country procurement systems, API risk analysis, regulatory data, research papers.
   - Total: 156 indexed chunks of real knowledge.

**2. Augment:** Take the retrieved chunks and give them to an AI model as context.

**3. Generate:** Claude uses that context to write a structured brief—not from hallucinations, but from facts.

Why does this matter? A pure prompt-only system is like asking a consultant 'What do you think?' A RAG system is like saying 'Here's the research. Now write the brief.' The first one might be wrong. The second one is grounded in evidence."

### The Evidence
"I evaluated this on 5 real-world cases:
- Each case: a drug, a country, a scenario (e.g., API export restriction)
- Each brief: scored against a 12-item fact checklist
- Each score: independently validated by a model-as-judge pipeline

**Results:**
- RAG: 12/12 (100% perfect on all 5 cases)
- Prompt-only: 8/12 average (67%)
- RAG advantage: +4 points per case

Graders immediately ask: 'How is RAG so good?' The answer is in the demo."

---

## PART 4: LIVE DEMO SETUP (0:30 seconds)

"I'm going to run the app live. We're going to:
1. Select a drug (cisplatin)
2. Select a country (Argentina)
3. Select a scenario (baseline—normal operations)
4. Watch the app generate a brief
5. I'll show you **exactly** what RAG is doing—the retrieval step, the context it found, and the brief it generated
6. We'll read the graphs and metrics
7. I'll compare it to what prompt-only would have said

Let me start the app..."

---

## PART 5: LIVE DEMO — RUNNING THE APP

### [SCREEN: Streamlit app loading]

"The app is loading. You can see:
- **Sidebar parameters:** Drug, Country, Scenario selectors
- **Three tabs:** Risk Brief, Simulation Chart, Portfolio Risk Matrix

I'm selecting:
- **Drug:** Cisplatin (platinum-based chemotherapy)
- **Country:** Argentina (highly fragmented procurement system)
- **Scenario:** Baseline (normal operations, no shock)

Now I'll click 'Generate Risk Brief.' Watch what happens..."

### [CLICK: Generate button]

"The app is now running the RAG pipeline behind the scenes. Specifically:
1. **Agent starts:** Claude decides what tools to call
2. **Search KB:** 'Find me everything about cisplatin in Argentina'
3. **Run simulation:** Monte Carlo with 500 iterations to model stockout risk
4. **Generate:** Write a structured brief using the results

It should take about 10–15 seconds. First time is slower because ChromaDB initializes..."

---

## PART 6: READING THE RAG OUTPUT (2:30 minutes)

### [SCREEN: Brief appears]

"Here's the brief. Let me walk you through what RAG did and why it matters."

### Section 1: Drug Profile
"**First section: 'Drug Profile'**

The brief says:
- 'Cisplatin is a platinum-based alkylating chemotherapy agent...'
- 'It has been on the WHO Model List of Essential Medicines since 1979'
- 'Cisplatin is fully off-patent with multiple generic manufacturers'
- 'API origin: The overwhelming majority of cisplatin API is manufactured in India and China, which together account for over 80% of global supply'

Where did this come from? **RAG retrieved it from the knowledge base.** My KB document on cisplatin profiles contains exactly this. But notice: it's not generic knowledge. It's **structured knowledge about why this drug is vulnerable:**
- WHO EML status signals countries should stock it
- Off-patent means multiple manufacturers globally compete
- India/China concentration means concentrated risk

A prompt-only system might say 'Cisplatin is a chemotherapy drug.' RAG says 'Cisplatin is a chemotherapy drug, and here's why supply is fragile.'"

### Section 2: Supply Chain Vulnerability
"**Second section: 'Supply Chain Vulnerability'**

The brief lists:
- Concentration of API supply (India + China)
- Shared platinum API chain (cisplatin and carboplatin suffer together)
- Generic market consolidation risk
- Argentine procurement fragmentation (8 independent channels)
- Regulatory lag (ANMAT 12–18 month approval)

This is **institutional and regulatory context that you can't get from training data alone.** The fragmentation of Argentina's procurement system is real but obscure. ANMAT approval timelines are domain-specific. The shared API chain insight comes from connecting two different drug profiles.

RAG found this because my knowledge base includes:
- Argentina procurement system document (describing all 8 channels)
- Cisplatin profile (mentioning carboplatin shared supply)
- Regulatory risk analysis

Prompt-only would guess or hallucinate."

### Section 3: Scenario Impact Analysis
"**Third section: 'Scenario Impact Analysis'**

This is where the simulation output appears. The brief shows:

- **Stockout days per year:** 7.0 ± 0.65 (95% CI)
- **Service level (unit fill rate):** 98.3%
- **Probability of any stockout during the year:** 74%
- **Probability of critical shortage (>60 stockout days):** 0.0%

**What does this mean?**

In a typical year, Argentina can expect cisplatin to be in stockout about 7 days. That's ~2% of the year unavailable—which sounds low. But it means there's a 74% chance you'll experience **some** shortage during the year. And when stockouts happen, they're usually brief (not critical). This is 'acceptable operational range' but not comfortable.

The brief interprets this: 'This is within acceptable operational range. However, the 74% probability of experiencing any stockout during the year, even if brief, indicates that supply tightness is an inherent feature of the current system.'

**This interpretation is crucial.** A raw number (7 days) is meaningless without context. RAG connected it to clinical impact: 'Even brief stockouts delay chemotherapy cycles, potentially compromising oncologic outcomes.'

**Where did the 7 days come from?** The simulation. Monte Carlo with 500 runs, stochastic lead times, realistic demand. But where did the simulation parameters come from? **The knowledge base.** Lead time = 35 days (from Argentina procurement docs). Order fill rate = 86% (from normal supplier performance). Demand = historical oncology treatment patterns.

Again: everything is grounded."

### Section 4: Policy Recommendations
"**Fourth section: 'Policy Recommendations'**

The brief lists 7 concrete recommendations:
1. National strategic cisplatin reserve (60–90 day buffer)
2. Integrated supply visibility system (real-time dashboard)
3. Pre-register alternative suppliers with ANMAT
4. Coordinate procurement timing across channels
5. Carboplatin-cisplatin contingency protocols
6. Monitor generic manufacturer market
7. Formalize emergency access mechanisms

**Why are these specific?** Because RAG understood the constraint structure. The reserve directly addresses fragmentation. Pre-registration addresses regulatory lag. Contingency protocols address the shared platinum supply chain risk.

Prompt-only might say 'improve supply chain.' RAG says 'improve supply chain **by addressing these 7 specific bottlenecks in Argentina's system.**'"

### Section 5: Confidence & Limitations
"**Fifth section: 'Confidence & Limitations'**

The brief is explicit about:
- What's confirmed (WHO EML status, API concentration)
- What's model-based (stockout days)
- Limitations (demand distribution assumptions, cold-chain not modeled, heterogeneous access not captured)

This honesty is critical. A bad RAG system would hide limitations. A good one says 'Here's what we're confident about, here's where you should be skeptical.'

This is the RAG advantage: **grounded reasoning with honest caveats.**"

---

## PART 7: SHOWING THE RAG SOURCES (1:00 minute)

### [CLICK: Sources expander]

"Now look at the 'Sources' section. The app shows exactly which documents RAG retrieved:

- Source 1: cisplatin_profile.txt
- Source 2: cisplatin_profile.txt
- Source 3: carboplatin_profile.txt
- Source 4: argentina_procurement_system.txt
- Source 5: argentina_procurement_system.txt
- etc.

**This is transparency.** Every claim in the brief can be traced back to a source. You can audit it. You can verify it's not hallucinated.

Compare this to prompt-only: 'Trust me, I know about drug supply chains.' RAG says: 'Here's my working, here's my sources, verify me.'"

---

## PART 8: COMPARISON — PROMPT-ONLY vs RAG (1:30 minutes)

### [SHOW: Side-by-side comparison]

"Let me show you what prompt-only generates for the same case. Here's a brief from ChatGPT-4 with **no context:**

[Display prompt-only output from evaluation]

**Prompt-only mentions:**
- ✗ Cisplatin is on WHO EML (hallucination: never mentioned it)
- ✗ Obra sociales as a procurement channel (hallucination: generic knowledge, no detail)
- ✗ ANMAT regulatory timelines (hallucination: made-up numbers)
- ✗ Specific stockout risk (hallucination: invented a statistic)
- ✓ API concentration in India/China (general knowledge—correct, but generic)

**RAG mentions:**
- ✓ WHO EML (sourced from KB)
- ✓ 8 procurement channels including obras sociales (sourced, detailed)
- ✓ ANMAT 12–18 month timelines (sourced from regulatory analysis)
- ✓ 7.0 stockout days (from simulation, not fabricated)
- ✓ API concentration (sourced, plus carboplatin connection)

**The difference:** RAG doesn't hallucinate because it doesn't generate from imagination—it generates from evidence."

---

## PART 9: THE METRICS (1:00 minute)

### [SHOW: Simulation Chart tab]

"Let me click to the Simulation Chart. You see:
- A histogram of 500 Monte Carlo runs
- The x-axis is stockout days per year
- The y-axis is frequency
- The distribution is right-skewed (most runs have 5–10 stockout days, a few tail out to 30+)

**What does this mean?** In 74% of simulated years, you have at least one stockout. In most years, it's brief (5–10 days). In rare years (maybe 1 in 100), it's longer (20+ days).

This is a **risk profile.** It's not 'stockout happens' or 'no stockout.' It's 'stockout is a feature of the system, here's the distribution of severity.'

The brief captures this: 'The 74% probability indicates supply tightness is inherent.'"

### [SHOW: Portfolio Risk Matrix tab]

"This tab shows a 4×4 heatmap: 4 drugs (rows) × 4 scenarios (columns). Each cell is colored:
- Green: LOW risk
- Yellow: MODERATE risk
- Orange: HIGH risk
- Red: CRITICAL risk

Look at the Venezuela column: it's all orange/red. Venezuela baseline is CRITICAL because structural factors (currency collapse, procurement failure) make shortage permanent.

Look at Argentina column: mostly green/yellow. Argentina has fragmentation, but the system functions. Scenarios make it worse, but it's manageable.

This is what RAG enables: rapid risk stratification across the entire portfolio. You can see at a glance which drug-country combinations need immediate attention."

---

## PART 10: EVALUATION RESULTS (1:00 minute)

### The Numbers
"I evaluated the system on 5 real-world cases using a model-as-judge pipeline. Each brief was scored on 12 criteria:

1. Identifies India/China as API source
2. Mentions local procurement channels
3. States WHO EML status
4. Identifies off-patent status
5. Quantifies risk metrics
6. Explains fragmentation
7. Includes policy recommendations
8. Includes confidence & limitations
9. No hallucinations about country manufacturing
10. No fabricated statistics
11. No ungrounded claims
12. No irrelevant tangents

**RAG score: 12/12 on all 5 cases (100%)**

**Prompt-only score: 8/12 average (67%)**

What did prompt-only miss?
- No WHO EML status (2 cases)
- No obras sociales mention (1 case)
- No fragmentation risk (1 case)
- No confidence section (all 5 cases)
- Occasional hallucinations (invented suppliers, fake statistics)

**Why does RAG win?** Because it can't make things up. It can only recombine what's in the knowledge base."

---

## PART 11: CRITICAL ANALYSIS (1:00 minute)

### What RAG Can Do
"RAG excels at:
- Domain-specific analysis (supply chain, regulatory, institutional)
- Multi-source synthesis (connecting drug, country, scenario knowledge)
- Transparent sourcing (graders can audit every claim)
- Consistent structure (always 5 sections, always metrics, always caveats)
- Rapid generation (15–30 seconds vs hours of research)

### What RAG Can't Do
"RAG has limits:
- **Model simplifications:** My Monte Carlo is (Q,r) inventory—it doesn't capture hoarding, political expropriation, or violence
- **Data gaps:** Demand is estimated, not real-time from hospitals
- **No cold-chain logistics:** I model lead time but not physical distribution complexity
- **No second-order effects:** If cisplatin shortage causes protocol substitution to carboplatin, that's not modeled

These aren't failures—they're **honest caveats.** The brief states them explicitly in the Confidence & Limitations section."

### When RAG Matters Most
"RAG is essential in this domain because:
1. **Institutional knowledge is essential:** Generic LLMs know 'India makes APIs.' They don't know 'ANMAT approvals take 12–18 months and during crises that's the bottleneck.'
2. **Fragmentation requires synthesis:** Argentina's 8 procurement channels aren't in Wikipedia. I had to research them, synthesize them, document them.
3. **Time matters:** A consultant would spend weeks. RAG does it in seconds.
4. **Audit trail matters:** If I advise a client to stock cisplatin, they need to know why. Sources matter."

---

## PART 12: CLOSING (1:00 minute)

### The Impact
"So what did I build?

A system that takes unstructured supply chain knowledge, structures it, indexes it, and uses it to generate defensible risk briefs in seconds.

Not a replacement for human experts. A force multiplier for them.

JCNB can now:
- **Rapidly assess** drug-country-scenario combinations
- **Identify blind spots** (which combinations need more research)
- **Advise clients** with sourced evidence
- **Scale** their consulting practice without hiring 10 new analysts

This is the power of RAG in regulated domains: it's not magic, it's **accountability with speed.**"

### The Business Case
"For a biotech company:
- Shortages cost lives (patient outcomes)
- Shortages create liability (regulatory exposure)
- Shortages disrupt supply (competitive disadvantage)

A system that predicts and explains shortage risk is worth millions. That's not an exaggeration—it's the difference between proactive supply chain management and reactive crisis response."

### Final Word
"RAG isn't hype. It's a practical tool for handling complexity in knowledge-intensive domains. This project proves it works.

Thank you."

---

## APPENDIX: LIVE DEMO SCREENSHOTS (if available)

If running live, capture:
1. App loading with parameters selected
2. Brief generating (spinning icon)
3. Completed brief with all 5 sections visible
4. Sources panel expanded (showing which docs were retrieved)
5. Simulation Chart tab (histogram visible)
6. Portfolio Risk Matrix (heatmap showing risk stratification)

---

## TALKING POINTS FOR Q&A

**Q: Why not just use ChatGPT directly?**  
A: "ChatGPT doesn't know Argentina's 8 procurement channels or ANMAT's 12–18 month approval timeline. It would hallucinate. RAG prevents hallucination by grounding generation in sourced knowledge."

**Q: How long did it take to build?**  
A: "4 weeks from research to live evaluation. 1 week research, 1 week RAG pipeline, 1 week simulation integration, 1 week evaluation and documentation."

**Q: What's the cost per brief?**  
A: "~$0.05 in API calls (Claude Haiku is cheap). Labor cost was research + development. Operational cost is near-zero."

**Q: Can this predict the next shortage?**  
A: "Partially. It identifies **structural vulnerability** (which drug-country combos are fragile). It can't predict **exogenous shocks** (coups, wars, pandemics). The simulation models shocks, but it's not a prediction system—it's a risk stratification system."

**Q: Why evaluation on only 5 cases?**  
A: "5 cases × 2 approaches (RAG + prompt-only) × 12 criteria each = 120 scored items. That's statistically robust for a capstone project. A production system would need 50+ cases and continuous validation."

**Q: How is this different from hiring a supply chain consultant?**  
A: "Consultants take weeks and cost $10K+. This takes 15 seconds and costs $0.05. Consultants provide depth; this provides scale. You use both: RAG to identify which cases need consultant attention, then hire a consultant for those."

---

## DELIVERY NOTES

- **Pacing:** 12–15 minutes. Don't rush the demo.
- **Tech check:** Ensure ChromaDB loads, API key is set, internet connection is stable
- **Backup:** Have a video recording of the demo in case live fails
- **Engagement:** Pause after each section for questions if time allows
- **Emphasis:** The RAG retrieval is the hero. Show sources. Show the gap vs prompt-only.
- **Honesty:** Talk about limitations. Shows maturity.

