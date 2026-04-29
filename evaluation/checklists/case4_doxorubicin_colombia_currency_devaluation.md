# Fact Checklist: Case 4 — Doxorubicin / Colombia / Currency Devaluation

Score: 1 = present and correct | 0 = absent | -1 = hallucinated (stated but false)

| # | Check | RAG score | Prompt-only score |
|---|-------|-----------|-------------------|
| 1 | Identifies India as the primary/dominant global API source for doxorubicin | | |
| 2 | Mentions INVIMA as Colombia's drug regulatory authority | | |
| 3 | Mentions EPS (Entidades Promotoras de Salud) as the health insurers managing oncology drug procurement in Colombia | | |
| 4 | States WHO EML inclusion for doxorubicin | | |
| 5 | States doxorubicin is generic and/or off-patent | | |
| 6 | Explains the currency devaluation mechanism: peso-denominated budgets vs. USD-priced imports reduces purchasing power and order volumes | | |
| 7 | Includes a quantitative stockout risk metric from simulation (e.g., ~4.2 stockout days/year, ~99% service level, or LOW risk classification) | | |
| 8 | Mentions documented shortage history for doxorubicin (2011–12 or 2022–23 global shortages) | | |
| 9 | Includes at least one concrete policy recommendation | | |
| 10 | Includes Confidence & Limitations section | | |
| 11 | Does NOT claim Colombia has domestic doxorubicin API manufacturing [hallucination check] | | |
| 12 | Does NOT fabricate specific Colombian procurement volume or market statistics not in context [hallucination check] | | |

**Total RAG: /12**
**Total Prompt-only: /12**

Notes:
- Items 2–3 (INVIMA, EPS) are strong differentiators: prompt-only may produce generic answers; RAG should retrieve colombia_procurement_system.txt
- Item 6 (currency mechanism) appears in both doxorubicin_profile.txt and colombia_procurement_system.txt — well-supported by KB
- Item 7 requires retrieval of doxorubicin_colombia_currency_devaluation.txt (sim) — key RAG differentiator
- Item 8 (shortage history) is in doxorubicin_profile.txt — Claude's parametric knowledge may also cover this; check if RAG cites the source
- Colombia KB doc is a PLACEHOLDER — expect RAG and prompt-only to be closer than in Cases 1 and 3; this case tests the impact of thin KB coverage
