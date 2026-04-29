"""
run_sims.py — Generate drug-country-scenario specific simulation output files
for ChromaDB indexing.

Generates 48 files (4 drugs × 3 countries × 4 scenarios) in knowledge_base/sim_outputs/
Named: {drug}_{country}_{scenario_slug}.txt for precise RAG retrieval.
"""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from supply_sim import (
    simulate, result_to_text,
    DRUG_PARAMS, COUNTRY_PARAMS, SCENARIO_PARAMS,
)

OUT_DIR = os.path.join(os.path.dirname(__file__), "sim_outputs")
os.makedirs(OUT_DIR, exist_ok=True)

def slugify(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")

drugs     = list(DRUG_PARAMS.keys())
countries = list(COUNTRY_PARAMS.keys())
scenarios = list(SCENARIO_PARAMS.keys())

total = len(drugs) * len(countries) * len(scenarios)
done  = 0

for drug in drugs:
    for country in countries:
        for scenario in scenarios:
            r    = simulate(drug, country, scenario, n_runs=500, days=365)
            text = result_to_text(r)

            fname = f"{slugify(drug)}_{slugify(country)}_{slugify(scenario)}.txt"
            fpath = os.path.join(OUT_DIR, fname)
            with open(fpath, "w") as f:
                f.write(text)

            done += 1
            sl_flag = "⚠" if r["stockout_days_mean"] > 30 else ("!" if r["stockout_days_mean"] > 10 else " ")
            print(f"[{done:2d}/{total}] {sl_flag} {fname}")
            print(f"       stockout={r['stockout_days_mean']}d  "
                  f"SL={r['sl_units_mean']:.1%}  "
                  f"p(crit)={r['prob_critical_shortage']:.0%}  "
                  f"disrupt_exp={r.get('avg_disruption_days','N/A')}d")

print(f"\nDone: {done} files written to {OUT_DIR}")
