# Fact Checklist: Case 5 — Carboplatin / Venezuela / Combined Shock

Score: 1 = present and correct | 0 = absent | -1 = hallucinated (stated but false)

| # | Check | RAG score | Prompt-only score |
|---|-------|-----------|-------------------|
| 1 | Identifies India and/or China as primary API source for carboplatin | | |
| 2 | Notes that carboplatin and cisplatin share the same API supply chain — an export restriction affects both simultaneously | | |
| 3 | Mentions MPPS (Ministerio del Poder Popular para la Salud) or Venezuela's institutional collapse / structural crisis as the baseline condition | | |
| 4 | States WHO EML inclusion for carboplatin | | |
| 5 | States carboplatin is generic, off-patent, and platinum-based (second-generation cisplatin analog) | | |
| 6 | Describes the combined shock as both API export restriction AND currency devaluation occurring simultaneously | | |
| 7 | Includes a quantitative stockout risk metric from simulation (e.g., ~35 stockout days/year, ~91% service level, HIGH risk, or p(critical)=15.8%) | | |
| 8 | Notes that Venezuela's baseline is already a structural crisis — scenario shocks produce marginal additional impact on top of a collapsed baseline | | |
| 9 | Includes at least one concrete policy recommendation | | |
| 10 | Includes Confidence & Limitations section | | |
| 11 | Does NOT claim Venezuela has functioning strategic drug reserves or a normally operating procurement system [hallucination check — Venezuela's system has structurally collapsed] | | |
| 12 | Does NOT fabricate specific carboplatin stockout statistics for Venezuela beyond what is in the simulation context [hallucination check] | | |

**Total RAG: /12**
**Total Prompt-only: /12**

Notes:
- Item 2 (shared cisplatin/carboplatin API chain) is in carboplatin_profile.txt — strong RAG differentiator
- Item 3 (MPPS, structural collapse) is in venezuela_procurement_system.txt — strong RAG differentiator; prompt-only may acknowledge crisis generically without institutional specifics
- Item 7 requires retrieval of carboplatin_venezuela_combined_shock.txt: 35.2 stockout days, HIGH, p(crit)=15.8% — key RAG differentiator
- Item 8 (baseline already collapsed) is a subtle insight from venezuela_procurement_system.txt — tests whether RAG retrieves the analytical framing, not just statistics
- Item 11 is a critical hallucination check: Venezuela's simulation model uses 30% effective budget cap and 60% structural fill rate as the BASELINE — prompt-only may describe Venezuela as if it has a functioning safety net
- Expected outcome: RAG should win clearly on items 2, 3, 7, 8, 11 — these are entirely KB/sim-dependent and not general knowledge
