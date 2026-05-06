# Email Draft — Dr. Gustavo Marin (Alcaraz et al. 2024 dataset request)

**TO:** gmarin@med.unlp.edu.ar
**CC:** info@iecs.org.ar (Andrea Alcaraz / Verónica Alfie via IECS)
**FROM:** cmart156@jh.edu
**SUBJECT:** Solicitud de datos agregados — estudio Alcaraz et al. 2024 (Medicina BA 84:445-458) — investigación académica JHU sobre desabastecimiento oncológico en LATAM

---

## Spanish version (send this)

Estimado Dr. Marin,

Le escribo desde la Johns Hopkins Carey Business School, donde estoy desarrollando un proyecto académico (capstone MBA) llamado **OncoSupply** — un modelo predictivo de desabastecimiento de medicamentos oncológicos para América Latina, con foco actual en Argentina, Colombia y Venezuela. El proyecto es estrictamente académico y no comercial; los resultados serán de acceso público y, si corresponde, presentados ante PAHO y la Organización Angels for Change.

He leído con mucho interés su artículo:

> Alcaraz A, Donato M, Alvarez J, Messina N, Alfie VA, Marin GH. **Judicialización de medicamentos de alto precio en Argentina: estudio cuali-cuantitativo.** *Medicina (Buenos Aires)* 2024;84(3):445-458. PMID: 38907958.

El conjunto de 405 casos de amparo 2017–2020 que ustedes analizaron tiene un valor enorme para validar externamente el modelo predictivo que estoy construyendo. Mi hipótesis pre-registrada es que las celdas (medicamento × jurisdicción × trimestre) donde el modelo predice mayor riesgo de desabastecimiento deberían correlacionar con una mayor tasa de presentación de amparos. La validación contra datos reales de acceso (vs. datos sintéticos) es justamente lo que diferencia un proyecto serio de un ejercicio teórico.

**Lo que les solicitaría, si fuera posible:**

1. **Una extracción agregada** del dataset al nivel de medicamento × jurisdicción (provincia o nivel federal/provincial) × trimestre — sin datos identificables de pacientes. Esto cumpliría plenamente con la Ley 25.326 y aún así permitiría una correlación estadística válida.
2. **Alternativamente, el codebook** y las tablas resumen que utilizaron para el análisis publicado — incluso eso sería suficiente para una validación inicial.
3. **Si hay un reporte previo de 2020** del Ministerio de Salud que mencionan en métodos (Alcaraz, *Judicialización de medicamentos de alto costo en Argentina*, 2020), agradecería una referencia.

Estoy comprometido a:
- Citar correctamente el artículo (PMID 38907958) y reconocer al equipo IECS/CONETEC/UNLP en cualquier publicación o presentación.
- Compartir con ustedes los resultados del análisis antes de cualquier presentación pública.
- Cumplir con todos los requisitos legales y éticos de protección de datos.
- Ofrecer una llamada de 30 minutos si fuera de interés discutir el proyecto.

Entiendo perfectamente que la decisión depende de múltiples factores institucionales (IECS, CONETEC, BNDE) y que la respuesta puede no ser inmediata. Cualquier orientación sobre el camino apropiado sería muy valiosa.

Quedo a disposición para cualquier consulta adicional. Adjunto un resumen de una página del proyecto OncoSupply si fuera de utilidad.

Cordialmente,

**Carlos F. Martino, PhD**
Johns Hopkins Carey Business School — MBA candidato 2026
Founder, JCNB Biotech (proyecto académico OncoSupply)
cmart156@jh.edu | LinkedIn: [añadir]

---

## English version (for your records / forwarding)

Dear Dr. Marin,

I am writing from Johns Hopkins Carey Business School, where I am developing an academic capstone project called **OncoSupply** — a predictive shortage-risk model for oncology drugs in Latin America, currently focused on Argentina, Colombia, and Venezuela. The project is strictly academic and non-commercial; results will be publicly available and, if appropriate, presented to PAHO and Angels for Change.

I read your article with great interest:

> Alcaraz A, Donato M, Alvarez J, Messina N, Alfie VA, Marin GH. *Judicialización de medicamentos de alto precio en Argentina: estudio cuali-cuantitativo.* Medicina (Buenos Aires) 2024;84(3):445-458. PMID: 38907958.

The 405 amparo cases (2017–2020) you analyzed have great value for externally validating the predictive model I am building. My pre-registered hypothesis is that drug × jurisdiction × quarter cells where the model predicts higher shortage risk should correlate with higher amparo filing rates. Validating against real access data (rather than synthetic data) is what distinguishes a serious project from a theoretical exercise.

**What I would ask, if possible:**

1. **An aggregated extract** of the dataset at the drug × jurisdiction (province or federal/provincial level) × quarter level — with no patient-identifiable data. This would fully comply with Argentine Law 25.326 and still allow valid statistical correlation.
2. **Alternatively, the codebook and summary tables** used in the published analysis — even that would suffice for initial validation.
3. **If there is a prior 2020 Ministry of Health report** mentioned in your methods (Alcaraz, *Judicialización de medicamentos de alto costo en Argentina*, 2020), I would appreciate a reference.

I commit to:
- Citing the article correctly (PMID 38907958) and acknowledging the IECS/CONETEC/UNLP team in any publication.
- Sharing analysis results with you before any public presentation.
- Complying with all legal and ethical data-protection requirements.
- Offering a 30-minute call if of interest to discuss the project.

I fully understand the decision depends on multiple institutional factors (IECS, CONETEC, BNDE) and the response may not be immediate. Any guidance on the appropriate path would be very valuable.

I remain available for any additional questions. I have attached a one-page project summary if useful.

Best regards,

**Carlos F. Martino, PhD**
Johns Hopkins Carey Business School — 2026 MBA candidate
Founder, JCNB Biotech (academic project OncoSupply)
cmart156@jh.edu

---

## Notes for Carlos before sending

1. **Attach** the one-pager: `Strategy/ONCOSUPPLY_ONE_PAGER_PAHO.docx`. This signals seriousness and matches what's in PAHO outreach.
2. **CC IECS** as well as Marin — the analytic file is likely held by Alcaraz/Alfie at IECS, even though Marin is corresponding author. CCing both routes the request through whichever channel is faster.
3. **Send Spanish version primarily.** A bilingual email (Spanish first, English appended) is acceptable but Spanish-only is better for a Latin American academic recipient. The English version above is for your own records.
4. **Send window:** Tuesday–Thursday 9–11am Argentina local (UTC-3). Avoid Mondays (clearing inbox) and Fridays (deferring to next week). Argentina is 1–2h ahead of US Eastern depending on DST.
5. **If no reply in 10 days:** send a one-line polite follow-up. If still nothing in 20 days, fall back to BNDE direct request (`bndo@msal.gov.ar`) — see `data_acquisition_alcaraz_2026-05-05.md` step 3.
6. **Citation correction reminder:** the project KB still says "Romero et al. 2024" in `knowledge_base/docs/argentina_procurement_system.txt` and `phase2_realtime/docs/preregistration_t3_1_amparo_backtest.md`. Fix before any external eyes see those files. Quick `sed` or manual edit.
