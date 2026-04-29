"""
supply_sim.py — Enhanced (Q, r) inventory simulation for oncology drug supply chains
in Latin America.

Theoretical foundation:
  - (Q, r) continuous-review model with stochastic lead times:
      Warren, Operations Management Textbook, Ch. 6, JHU Carey Business School (2025)
      Safety stock: SS = z * sqrt(d^2 * sigma_L^2 + L * sigma_D^2)
  - System dynamics / R3 inventory loop (price -> inventory -> stockout):
      Andrade & Wang, MIT SCM Capstone (2024)
  - Pharmaceutical shortage parameterization (2023 cisplatin/carboplatin):
      Izen et al., Cancer Journal (2025)
  - Discrete event simulation methodology:
      Kogler & Maxera, Journal of Simulation (2026)
  - Disruption duration modeling via geometric distribution (rolling horizon):
      Badejo & Ierapetritou, Ind. Eng. Chem. Res. (2022)
      Key insight: disruptions are finite-duration events, not permanent state shifts.
      Disruption duration ~ Geometric(1/mu_disruption); mean = mu_disruption days.
"""

import numpy as np
import os

# ── Service level z-scores (normal distribution) ─────────────────────────────
# Source: Warren OM Textbook Table 6.2 — NORM.INV(ltsl, 0, 1)
Z_SCORES = {0.90: 1.282, 0.95: 1.645, 0.97: 1.881, 0.99: 2.326}

# ── Drug parameters ───────────────────────────────────────────────────────────
# Units: treatment doses per day for a representative mid-size oncology center
# Demand assumed normally distributed (Warren OM §6.6 assumption)
# std = CV * mean; oncology generics CV ~ 0.3; biologics CV ~ 0.45
DRUG_PARAMS = {
    "cisplatin": {
        "daily_demand_mean": 8.0,   # doses/day
        "daily_demand_std":  2.4,   # sigma_D
        "shelf_life_days":   730,   # 2 years
        "unit_cost_usd":     12,
        "label":             "Cisplatin (platinum-based chemotherapy)",
    },
    "doxorubicin": {
        "daily_demand_mean": 5.0,
        "daily_demand_std":  1.8,
        "shelf_life_days":   730,
        "unit_cost_usd":     18,
        "label":             "Doxorubicin (anthracycline antibiotic)",
    },
    "carboplatin": {
        "daily_demand_mean": 6.0,
        "daily_demand_std":  1.9,
        "shelf_life_days":   730,
        "unit_cost_usd":     15,
        "label":             "Carboplatin (platinum-based, 2nd generation)",
    },
    "trastuzumab": {
        "daily_demand_mean": 1.5,
        "daily_demand_std":  0.7,
        "shelf_life_days":   365,   # 1 year — cold-chain biologic; shorter shelf life
        "unit_cost_usd":     800,
        "label":             "Trastuzumab (HER2+ monoclonal antibody, biologic)",
    },
}

# ── Country parameters ────────────────────────────────────────────────────────
# Base lead times: import logistics + regulatory clearance
# Sources: MSF Argentina field report (2022-23); Andrade & Wang MIT (2024)
# Lead time modeled as log-normal (always positive, right-skewed — realistic for imports)
#
# Structural fragility parameters (applied even under Baseline scenario):
#   structural_fill_rate: fraction of orders actually received under normal ops.
#     Venezuela = 0.70 — chronic procurement failures, informal/non-existent
#     public health supply chain; dollar-denominated prices vs. collapsed bolivar
#     budget make many orders impossible to fulfill.
#   structural_budget_cap: max fraction of EOQ the health system can actually fund.
#     Venezuela = 0.35 — severe fiscal austerity; oil revenue collapse since 2015
#     has gutted MPPS (Ministry of Health) procurement budgets.
#   These are FLOORS: scenario multipliers stack multiplicatively but cannot
#   exceed these structural ceilings.
COUNTRY_PARAMS = {
    "Argentina": {
        "lead_time_mean":         35,    # days: air/sea import + ANMAT customs clearance
        "lead_time_cv":           0.25,
        "structural_fill_rate":   0.90,
        "structural_budget_cap":  0.75,
        "initial_stock_days":     45,    # realistic starting inventory: ~6 weeks on-hand
        "label": "Argentina",
    },
    "Venezuela": {
        "lead_time_mean":         60,    # days: severe logistics, bureaucratic, and financial barriers
        "lead_time_cv":           0.60,  # very high variability
        "structural_fill_rate":   0.60,  # ~40% of orders fail or arrive severely short
        "structural_budget_cap":  0.30,  # oil revenue collapse → MPPS budget ~70% below 2013 levels
        "initial_stock_days":     10,    # chronic shortages: hospitals typically hold <2 weeks stock
        "label": "Venezuela",
    },
    "Colombia": {
        "lead_time_mean":         28,
        "lead_time_cv":           0.20,
        "structural_fill_rate":   0.93,
        "structural_budget_cap":  0.85,
        "initial_stock_days":     35,    # moderate stock: ~5 weeks on-hand
        "label": "Colombia",
    },
}

# ── Scenario parameters ───────────────────────────────────────────────────────
# Parameterized from:
#   - Izen et al. Cancer Journal (2025): 2023 shortage — lead time 2.5x, fill rate 40-60%
#   - MIT R3 loop (Andrade & Wang 2024): currency devaluation -> budget cut -> smaller orders
#   - disruption_duration_mean: geometric distribution mean (Badejo & Ierapetritou 2022)
#     None = permanent (worst-case bound); a value = expected disruption window in days.
#     API restriction: ~90 days (Izen 2025: 2023 shortage lasted ~3-4 months)
#     Currency crisis: ~180 days (structural; peso devaluations in Argentina historically persist 6+ months)
SCENARIO_PARAMS = {
    "Baseline": {
        "lead_time_multiplier":   1.0,
        "demand_multiplier":      1.0,
        "fill_rate":              0.95,
        "budget_multiplier":      1.0,
        "disruption_duration_mean": None,  # no disruption
        "label": "Normal operations",
    },
    "API export restriction": {
        "lead_time_multiplier":   2.5,
        "demand_multiplier":      1.0,
        "fill_rate":              0.55,    # hospitals received 40-60% of orders (Izen 2025)
        "budget_multiplier":      1.0,
        "disruption_duration_mean": 90,   # ~3 months; geometric distribution (Badejo & Ierapetritou 2022)
        "label": "API export restriction (India/China supply disruption)",
    },
    "Currency devaluation": {
        "lead_time_multiplier":   1.0,
        "demand_multiplier":      1.15,   # demand spike: patients accelerate treatment
        "fill_rate":              0.90,
        "budget_multiplier":      0.60,   # MIT R3: devaluation -> 40% effective budget cut
        "disruption_duration_mean": 180,  # 6 months; peso devaluations are prolonged structural events
        "label": "Currency crisis (peso devaluation, budget compression)",
    },
    "Combined shock": {
        "lead_time_multiplier":   2.5,
        "demand_multiplier":      1.15,
        "fill_rate":              0.55,
        "budget_multiplier":      0.60,
        "disruption_duration_mean": 120,  # intermediate: both shocks co-occur, resolve ~4 months
        "label": "Combined shock (API restriction + currency devaluation)",
    },
}


# ── Policy calculation (textbook formulas) ────────────────────────────────────

def compute_policy(d, sigma_d, L_mean, L_cv, service_level=0.95,
                   unit_cost=10, days=365):
    """
    Compute optimal (Q*, r) policy using Warren OM Textbook Ch. 6 formulas.

    Safety stock (both demand AND lead time variable):
        SS = z * sqrt(d^2 * sigma_L^2 + L * sigma_D^2)
    Reorder point:
        r = d * L + SS
    EOQ:
        Q* = sqrt(2 * D_annual * S_order / H_holding)
    """
    z       = Z_SCORES.get(service_level, 1.645)
    sigma_L = L_mean * L_cv

    # Warren OM Textbook §6.6 — safety stock with variable demand AND lead time
    SS = z * np.sqrt(d**2 * sigma_L**2 + L_mean * sigma_d**2)
    r  = d * L_mean + SS

    # EOQ: ordering cost $50/order, holding cost = 20% of unit cost per year
    D_annual  = d * days
    S_order   = 50.0
    H_holding = 0.20 * unit_cost
    Q_star    = max(10, int(np.sqrt(2 * D_annual * S_order / H_holding)))

    return {
        "reorder_point": round(r),
        "safety_stock":  round(SS),
        "eoq":           Q_star,
        "z_score":       z,
    }


# ── Single simulation run ─────────────────────────────────────────────────────

def _run_once(d, sigma_d, L_mean, L_cv, fill_rate, budget_multiplier,
              reorder_point, order_quantity, days=365, seed=None,
              disruption_duration_mean=None,
              base_L_mean=None, base_L_cv=None,
              base_fill_rate=0.95, base_budget_multiplier=1.0,
              base_d=None, base_sigma_d=None,
              initial_inventory=None):
    """
    One (Q, r) discrete-event simulation run with dynamic disruption modeling.

    Key mechanics:
    - Stochastic lead time: log-normal(L_mean, L_cv) — always positive, right-skewed
    - Normal demand: truncated at 0
    - Partial fill rate: orders arrive at fill_rate * Q_ordered
    - Budget constraint: caps effective order quantity (MIT R3 loop)
    - Backorders NOT allowed (stockout = lost treatment dose)
    - Disruption duration: geometric distribution (Badejo & Ierapetritou 2022)
      When disruption_duration_mean is set, the disruption starts on a random day
      within the first 60 days and lasts Geometric(1/disruption_duration_mean) days.
      Outside the disruption window, baseline parameters apply.
      This reflects the empirical finding that supply shocks are finite events, not
      permanent state changes — the rolling horizon insight from Badejo & Ierapetritou.
    """
    rng = np.random.default_rng(seed)

    # Disruption window (Badejo & Ierapetritou 2022: geometric distribution)
    if disruption_duration_mean is not None and disruption_duration_mean > 0:
        disruption_start = int(rng.integers(1, 45))  # onset within first 6 weeks
        # Geometric(p): duration with mean = disruption_duration_mean
        p_recovery = 1.0 / disruption_duration_mean
        raw_duration = int(rng.geometric(p_recovery))
        disruption_end = disruption_start + raw_duration
    else:
        disruption_start = 0
        disruption_end   = days  # disruption is permanent (worst-case scenario)

    # Baseline parameters (pre/post disruption)
    _base_L_mean  = base_L_mean  if base_L_mean  is not None else L_mean
    _base_L_cv    = base_L_cv    if base_L_cv    is not None else L_cv
    _base_d       = base_d       if base_d       is not None else d
    _base_sigma_d = base_sigma_d if base_sigma_d is not None else sigma_d

    def _lognormal_params(lm, lcv):
        lv = np.log(1 + lcv**2)
        return np.log(lm) - 0.5 * lv, np.sqrt(lv)

    # Disruption-state lead time log-normal params
    mu_log_disrupt, sigma_log_disrupt   = _lognormal_params(L_mean, L_cv)
    mu_log_base,    sigma_log_base      = _lognormal_params(_base_L_mean, _base_L_cv)

    # Budget-constrained order quantities (MIT R3 loop: currency -> reduced budget)
    effective_Q_disrupt = max(5, int(order_quantity * budget_multiplier))
    effective_Q_base    = max(5, int(order_quantity * base_budget_multiplier))

    inventory  = reorder_point if initial_inventory is None else initial_inventory
    pipeline   = []                     # (quantity, arrival_day)
    stockout_days        = 0
    total_demand         = 0.0
    total_fulfilled      = 0.0
    inv_history          = []
    disruption_days_seen = 0            # track actual disruption exposure

    for day in range(days):
        # Current state: disruption active or normal operations?
        in_disruption = disruption_start <= day < disruption_end

        if in_disruption:
            disruption_days_seen += 1
            cur_fill_rate = fill_rate
            cur_demand_d  = d
            cur_sigma_d   = sigma_d
            cur_Q         = effective_Q_disrupt
            mu_log_cur    = mu_log_disrupt
            sigma_log_cur = sigma_log_disrupt
        else:
            cur_fill_rate = base_fill_rate
            cur_demand_d  = _base_d
            cur_sigma_d   = _base_sigma_d
            cur_Q         = effective_Q_base
            mu_log_cur    = mu_log_base
            sigma_log_cur = sigma_log_base

        # 1. Receive arriving orders (partial fill applied at arrival)
        new_pipeline = []
        for qty, arrival, order_fill in pipeline:
            if arrival <= day:
                inventory += int(qty * order_fill)
            else:
                new_pipeline.append((qty, arrival, order_fill))
        pipeline = new_pipeline

        # 2. Daily demand (normal, floored at 0)
        demand = max(0.0, float(rng.normal(cur_demand_d, cur_sigma_d)))
        total_demand += demand

        # 3. Fulfill demand — no backorders
        if demand > inventory:
            stockout_days   += 1
            total_fulfilled += inventory
            inventory        = 0
        else:
            inventory       -= demand
            total_fulfilled += demand

        # 4. Reorder decision: (Q, r) continuous-review — place order whenever
        #    inventory (on-hand + on-order) falls at or below reorder point.
        #    Using inventory position (IP = on-hand + pipeline) to avoid
        #    order redundancy when multiple orders are in transit.
        #    Standard (Q,r) policy allows simultaneous orders in the pipeline.
        on_order = sum(qty for qty, _, _ in pipeline)
        ip = inventory + on_order
        if ip <= reorder_point:
            lt = max(1, int(rng.lognormal(mu_log_cur, sigma_log_cur)))
            pipeline.append((cur_Q, day + lt, cur_fill_rate))

        inv_history.append(inventory)

    sl_days  = 1.0 - stockout_days / days
    sl_units = total_fulfilled / total_demand if total_demand > 0 else 1.0

    return {
        "stockout_days":         stockout_days,
        "avg_inventory":         float(np.mean(inv_history)),
        "service_level_days":    sl_days,
        "service_level_units":   sl_units,
        "disruption_days_seen":  disruption_days_seen,
    }


# ── Monte Carlo wrapper ───────────────────────────────────────────────────────

def simulate(drug, country, scenario, n_runs=500, days=365,
             service_level_target=0.95):
    """
    Run Monte Carlo simulation for a drug-country-scenario triple.

    Returns a dict of aggregated KPIs with 95% confidence intervals.
    Methodology: DES + Monte Carlo (Kogler & Maxera 2026) with dynamic disruption
    duration (Badejo & Ierapetritou 2022).
    """
    dp = DRUG_PARAMS[drug]
    cp = COUNTRY_PARAMS[country]
    sp = SCENARIO_PARAMS[scenario]

    # Structural country constraints applied BEFORE scenario multipliers
    # Venezuela's broken procurement system caps effective fill rate and budget
    # even in Baseline — scenario shocks stack on top of these structural floors.
    struct_fill   = cp["structural_fill_rate"]
    struct_budget = cp["structural_budget_cap"]

    # Disruption-state parameters (scenario multipliers × structural country floors)
    d        = dp["daily_demand_mean"] * sp["demand_multiplier"]
    sigma_d  = dp["daily_demand_std"]  * sp["demand_multiplier"]
    L_mean   = cp["lead_time_mean"]    * sp["lead_time_multiplier"]
    L_cv     = cp["lead_time_cv"]
    # Effective fill rate: structural floor × scenario fill rate (both constraints active)
    eff_fill_rate   = struct_fill   * sp["fill_rate"]
    eff_budget_mult = struct_budget * sp["budget_multiplier"]

    # Baseline (pre/post-disruption) parameters — structural constraints still apply
    base_d          = dp["daily_demand_mean"]
    base_sigma_d    = dp["daily_demand_std"]
    base_L_mean     = cp["lead_time_mean"]
    base_L_cv       = cp["lead_time_cv"]
    base_fill_rate  = struct_fill   * SCENARIO_PARAMS["Baseline"]["fill_rate"]
    base_budget_mult = struct_budget * SCENARIO_PARAMS["Baseline"]["budget_multiplier"]

    # Policy is computed under disruption-state parameters (conservative sizing)
    policy = compute_policy(
        d=d, sigma_d=sigma_d, L_mean=L_mean, L_cv=L_cv,
        service_level=service_level_target,
        unit_cost=dp["unit_cost_usd"], days=days,
    )

    # Realistic starting inventory: country-specific initial stock days (not the theoretical
    # reorder point, which assumes a fully-stocked ideal system).
    initial_inv = int(base_d * cp["initial_stock_days"])

    runs = [
        _run_once(
            d=d, sigma_d=sigma_d, L_mean=L_mean, L_cv=L_cv,
            fill_rate=eff_fill_rate,
            budget_multiplier=eff_budget_mult,
            reorder_point=policy["reorder_point"],
            order_quantity=policy["eoq"],
            days=days, seed=i,
            disruption_duration_mean=sp["disruption_duration_mean"],
            base_L_mean=base_L_mean, base_L_cv=base_L_cv,
            base_fill_rate=base_fill_rate,
            base_budget_multiplier=base_budget_mult,
            base_d=base_d, base_sigma_d=base_sigma_d,
            initial_inventory=initial_inv,
        )
        for i in range(n_runs)
    ]

    so   = np.array([r["stockout_days"]        for r in runs])
    slu  = np.array([r["service_level_units"]   for r in runs])
    sld  = np.array([r["service_level_days"]    for r in runs])
    inv  = np.array([r["avg_inventory"]         for r in runs])
    ddays = np.array([r["disruption_days_seen"] for r in runs])

    ci = lambda a: round(1.96 * a.std() / np.sqrt(n_runs), 2)

    return {
        "drug": drug, "country": country, "scenario": scenario,
        "n_runs": n_runs, "days": days,
        # Policy (from textbook formulas)
        "reorder_point":     policy["reorder_point"],
        "safety_stock":      policy["safety_stock"],
        "eoq":               policy["eoq"],
        "lead_time_mean":    round(L_mean, 1),
        "lead_time_std":     round(L_mean * L_cv, 1),
        "fill_rate":              eff_fill_rate,
        "fill_rate_scenario":     sp["fill_rate"],
        "fill_rate_structural":   struct_fill,
        "budget_multiplier":      eff_budget_mult,
        "budget_structural":      struct_budget,
        "disruption_duration_mean": sp["disruption_duration_mean"],
        # KPIs
        "stockout_days_mean":    round(float(so.mean()), 1),
        "stockout_days_ci":      ci(so),
        "sl_units_mean":         round(float(slu.mean()), 4),
        "sl_units_ci":           ci(slu),
        "sl_days_mean":          round(float(sld.mean()), 4),
        "avg_inventory_mean":    round(float(inv.mean()), 1),
        "avg_disruption_days":   round(float(ddays.mean()), 1),
        # Risk flags
        "prob_critical_shortage": round(float((so > 60).mean()), 3),
        "prob_any_stockout":      round(float((so > 0).mean()), 3),
    }


# ── Output text generator ─────────────────────────────────────────────────────

def result_to_text(r):
    """
    Format simulation results as a structured text document for RAG indexing.
    Named drug_country_scenario to enable precise retrieval.
    """
    dp = DRUG_PARAMS[r["drug"]]
    sp = SCENARIO_PARAMS[r["scenario"]]
    cp = COUNTRY_PARAMS[r["country"]]

    risk = ("CRITICAL" if r["stockout_days_mean"] > 60
            else "HIGH"     if r["stockout_days_mean"] > 30
            else "MODERATE" if r["stockout_days_mean"] > 10
            else "LOW")

    shortage_prob_pct = r["prob_critical_shortage"] * 100

    dur = r["disruption_duration_mean"]
    dur_str = (f"~{dur} days (geometric distribution, Badejo & Ierapetritou 2022)"
               if dur else "permanent / worst-case bound (no recovery modeled)")
    avg_disrupt_str = (f"Average realized disruption exposure: {r.get('avg_disruption_days', 'N/A')} days/year"
                       if dur else "Disruption active for full simulation horizon")

    # ── Fill rate interpretation ──────────────────────────────────────────────
    # Distinguish scenario-driven vs. structural-country-driven fill rate
    if r["fill_rate_scenario"] < 0.70:
        # Scenario shock (API restriction / combined): cite Izen 2025
        fill_note = (
            f"severe supply allocation constraints documented during the 2023 "
            f"cisplatin/carboplatin shortage (Izen et al., Cancer Journal, 2025); "
            f"structural country floor: {r['fill_rate_structural']:.0%}"
        )
    elif r["fill_rate_structural"] < 0.90:
        # Structural country constraint only (e.g. Venezuela Baseline)
        fill_note = (
            f"chronic structural procurement failures in {r['country']} "
            f"(~{100-int(r['fill_rate_structural']*100)}% of orders fail or arrive severely short "
            f"due to fiscal constraints and informal supply chains — not scenario-specific)"
        )
    else:
        fill_note = "normal supplier performance under current market conditions"

    # ── Budget interpretation ─────────────────────────────────────────────────
    # Distinguish structural (e.g. Venezuela oil collapse) vs scenario (currency devaluation)
    scenario_budget_mult = round(r["budget_multiplier"] / r["budget_structural"], 3) if r["budget_structural"] > 0 else 1.0
    if scenario_budget_mult < 1.0:
        # Scenario-level currency shock active
        budget_note = (
            f"The budget multiplier of {int(r['budget_multiplier']*100)}% reflects the impact "
            f"of currency devaluation on procurement budgets (scenario factor: "
            f"{int(scenario_budget_mult*100)}%), reducing effective order quantities — "
            f"consistent with the R3 inventory loop (Andrade & Wang, MIT SCM, 2024)."
        )
    elif r["budget_structural"] < 1.0:
        # Structural constraint only (Venezuela Baseline — oil revenue collapse)
        budget_note = (
            f"The effective budget of {int(r['budget_multiplier']*100)}% reflects chronic "
            f"fiscal constraints in {r['country']} (oil revenue collapse / structural austerity) "
            f"independent of any scenario shock — consistent with the R3 inventory loop "
            f"(Andrade & Wang, MIT SCM, 2024)."
        )
    else:
        budget_note = ""

    return f"""DRUG: {r["drug"]}
COUNTRY: {r["country"]}
TOPIC: simulation, inventory, stockout, supply chain, {r["scenario"].lower()}
SOURCE: supply_sim.py Monte Carlo (Q,r) model — Warren OM Ch.6 / Izen 2025 / Badejo & Ierapetritou 2022
DATE: 2026
---
Simulation Results: {dp["label"]} in {cp["label"]}
Scenario: {sp["label"]}
Model: Continuous-review (Q, r) with stochastic lead times and dynamic disruption duration | {r["n_runs"]} Monte Carlo runs | {r["days"]} days

--- Optimal Policy (Warren OM Textbook §6.6) ---
Safety stock (SS = z*sqrt(d^2*sigma_L^2 + L*sigma_D^2)): {r["safety_stock"]} units
Reorder point (r = d*L + SS): {r["reorder_point"]} units
Economic Order Quantity (Q*): {r["eoq"]} units
Target service level: 95%

--- Scenario Parameters ---
Mean lead time during disruption: {r["lead_time_mean"]} days (std: {r["lead_time_std"]} days, log-normal)
Effective order fill rate: {r["fill_rate"]*100:.0f}% (structural floor {r["fill_rate_structural"]*100:.0f}% × scenario {r["fill_rate_scenario"]*100:.0f}%)
Effective budget multiplier: {r["budget_multiplier"]*100:.0f}% (structural cap {r["budget_structural"]*100:.0f}% × scenario {int(scenario_budget_mult*100)}%)
Disruption duration: {dur_str}
{avg_disrupt_str}

--- Monte Carlo Results ({r["n_runs"]} simulations) ---
Stockout days per year: {r["stockout_days_mean"]} ± {r["stockout_days_ci"]} (95% CI)
Service level (unit fill rate): {r["sl_units_mean"]:.1%} ± {r["sl_units_ci"]:.1%} (95% CI)
Service level (days without stockout): {r["sl_days_mean"]:.1%}
Average inventory on hand: {r["avg_inventory_mean"]:.0f} units

--- Risk Assessment ---
Overall supply risk: {risk}
Probability of any stockout during the year: {r["prob_any_stockout"]:.0%}
Probability of critical shortage (>60 stockout days): {shortage_prob_pct:.1f}%

--- Interpretation ---
Under {sp["label"].lower()} conditions, {r["drug"]} supply in {r["country"]} is projected
to experience {r["stockout_days_mean"]} stockout days per year (95% CI: ±{r["stockout_days_ci"]} days),
with a unit service level of {r["sl_units_mean"]:.1%}.
{"This represents a CRITICAL supply disruption risk that directly threatens treatment continuity for cancer patients." if risk == "CRITICAL"
 else "This represents HIGH supply risk. Treatment delays and rationing are likely without intervention." if risk == "HIGH"
 else "This represents MODERATE supply risk. Buffer stock and procurement coordination are recommended." if risk == "MODERATE"
 else "This is within acceptable operational range, though monitoring is warranted."}
The {r["fill_rate"]*100:.0f}% fill rate assumption reflects {fill_note}.
{budget_note}{"Disruption duration modeled as a geometric random variable (mean=" + str(dur) + " days), reflecting the insight from Badejo & Ierapetritou (Ind. Eng. Chem. Res., 2022) that supply chain shocks have finite durations and recovery dynamics. KPIs incorporate both disruption and recovery phases within each annual simulation." if dur else ""}
"""


if __name__ == "__main__":
    r = simulate("cisplatin", "Argentina", "Baseline", n_runs=200)
    print(result_to_text(r))
