# Amparo Paper Acquisition — 2026-05-05

## ⚠ Citation correction required

**The paper is Alcaraz et al. 2024, NOT Romero et al. 2024.**
Same journal, same volume, same pages, same statistics (405 cases, nusinersen 21.7%, etc.). Issue is **n3, not n5**. The "500445" in the SciELO PID encodes article position, not issue number.

**Correct citation:**
> Alcaraz A, Donato M, Alvarez J, Messina N, Alfie VA, Marin GH. Judicialización de medicamentos de alto precio en Argentina: estudio cuali-cuantitativo. *Medicina (Buenos Aires)* 2024;84(3):445-458. PMID: 38907958.

**Files that propagate the wrong citation and need fixing:**
- `knowledge_base/docs/argentina_procurement_system.txt` (Source line)
- `phase2_realtime/docs/preregistration_t3_1_amparo_backtest.md` (multiple references)
- Any grant doc that cites this work (check `grants/` and NIH Specific Aims)

## Article URLs

- Publisher PDF: https://www.medicinabuenosaires.com/revistas/vol84-24/n3/445.pdf
- SciELO HTML: https://www.scielo.org.ar/scielo.php?script=sci_arttext&pid=S0025-76802024000500445
- SciELO PDF: https://www.scielo.org.ar/pdf/medba/v84n3/1669-9106-medba-84-03-445.pdf
- PubMed: https://pubmed.ncbi.nlm.nih.gov/38907958/
- IECS: https://iecs.org.ar/judicializacion-de-medicamentos-de-alto-precio-en-argentina-estudio-cuali-cuantitativo/

No DOI (Medicina BA does not consistently mint DOIs). Cite by PMID 38907958.

## Authors

| Author | Affiliation |
|---|---|
| Andrea Alcaraz (1st) | IECS — Instituto de Efectividad Clínica y Sanitaria, Buenos Aires |
| Manuel Donato | CONETEC, Ministerio de Salud de la Nación |
| Jorgelina Alvarez | Unidad Coordinadora de Tecnologías Sanitarias, MoH Mendoza |
| Natalia Messina | Dirección de Medicamentos Especiales y Alto Precio, MoH Nación |
| Verónica A. Alfie | IECS, Buenos Aires |
| **Gustavo H. Marin (corresponding)** | CUFAR-UNLP / OPS-OMS |

## Dataset availability

**No supplementary materials. No public dataset.** Methods state data is from "tres bases de datos nacionales y provinciales" — almost certainly:
- BNDE (Banco Nacional de Drogas Especiales) — Messina's unit
- SUR (Sistema Único de Reembolso) — APE/SSSalud high-cost drug reimbursement
- Mendoza provincial registry — Alvarez's unit

**Privacy caveat:** Argentine Ley 25.326 (Protección de Datos Personales) — any data the authors share will be aggregated or de-identified. Plan model around drug × month × jurisdiction granularity, not patient-level.

## Acquisition path (ranked)

1. **Email Marin (cc IECS) in Spanish.** `gmarin@med.unlp.edu.ar` and `info@iecs.org.ar`. Frame: JHU Carey MBA capstone, non-commercial supply-risk model, request de-identified case-level extract OR codebook + aggregated tables. Include `cmart156@jh.edu`.
2. **Alcaraz 2020 precursor report** — likely contains line-item annexes the 2024 journal omitted. Contact `investigacion@msal.gov.ar`. BVS record: https://pesquisa.bvsalud.org/portal/resource/pt/biblio-1379286
3. **BNDE direct request** — `bndo@msal.gov.ar`. Aggregate statistics, oncology-specific. Best fallback if author route fails.
4. **SUR / SSSalud reembolsos via Ley 27.275 (FOIA)** — slow (30–45 days) but structured.
5. **(Last resort) Reconstruct from CIJ/PJN public court records.** Multi-week NLP build. Don't start until 1–4 fail.

**Recommendation:** Single Spanish email to Marin + IECS this week. If no reply in 10 days, BNDE request in parallel. Do not scrape courts until both routes fail.

## Friend-from-Argentina path

Your friend's added value: institutional access. The corresponding author Marin is at **UNLP (La Plata)**. If your friend has any UNLP / IECS / CONETEC / MoH connection, that's the single highest-leverage warm intro available. Otherwise the cold email path is fine.
