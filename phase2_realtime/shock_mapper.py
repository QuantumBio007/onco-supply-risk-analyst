"""
shock_mapper.py — Map classified events to supply_sim.py, compute risk deltas.

Two simulation paths:

  1. DYNAMIC (preferred, post-2026-05-03):
     When event_classifier returns continuous impact parameters
     (lead_time_multiplier, demand_multiplier, fill_rate, budget_multiplier),
     run supply_sim.simulate_dynamic() with those parameters directly.
     This makes the "multi-dimensional shock propagation" claim TRUE — Claude's
     article-specific reading drives the simulation, not a 24-cell lookup.

  2. SCENARIO_MAP fallback (legacy):
     When impact dict is missing or invalid, fall back to (shock_type, severity)
     lookup against SCENARIO_PARAMS named scenarios.

Closes the H1 defect identified in the 2026-05-03 strategic review.
Each result carries `simulation_mode` ("dynamic" or "scenario_map") for auditability.
"""

import json
from pathlib import Path
import sys
from typing import Optional

# Add parent to path for supply_sim import
sys.path.insert(0, str(Path(__file__).parent.parent))
from supply_sim import simulate, simulate_dynamic


# ── Scenario fallback map (used only when Claude impact params absent) ──────
# (shock_type, severity) → SCENARIO_PARAMS scenario name
SCENARIO_MAP = {
    ("manufacturing", "CRITICAL"): "API export restriction",
    ("manufacturing", "MODERATE"): "API export restriction",
    ("manufacturing", "MINOR"):    "Baseline",

    ("logistics", "CRITICAL"): "Combined shock",
    ("logistics", "MODERATE"): "API export restriction",
    ("logistics", "MINOR"):    "Baseline",

    # Regulatory: CRITICAL = full import suspension (API + budget hit = Combined);
    # MODERATE = pricing controls / re-registration delays → dedicated scenario
    ("regulatory", "CRITICAL"): "Combined shock",
    ("regulatory", "MODERATE"): "Regulatory squeeze",
    ("regulatory", "MINOR"):    "Baseline",

    # Demand: MODERATE guideline expansion or incidence surge → Demand surge scenario.
    # Dynamic path preferred; SCENARIO_MAP fallback now non-null for MODERATE.
    ("demand", "CRITICAL"): "Combined shock",
    ("demand", "MODERATE"): "Demand surge",
    ("demand", "MINOR"):    "Baseline",

    ("currency", "CRITICAL"): "Combined shock",
    ("currency", "MODERATE"): "Currency devaluation",
    ("currency", "MINOR"):    "Baseline",

    ("political", "CRITICAL"): "Combined shock",
    ("political", "MODERATE"): "API export restriction",
    ("political", "MINOR"):    "Baseline",

    ("climate", "CRITICAL"): "Combined shock",
    ("climate", "MODERATE"): "API export restriction",
    ("climate", "MINOR"):    "Baseline",

    ("company", "CRITICAL"): "API export restriction",
    ("company", "MODERATE"): "Baseline",
    ("company", "MINOR"):    "Baseline",

    # Macro-economic: oil/commodity shocks → LATAM inflation → health budget compression.
    # Dynamic path preferred when Claude quantifies budget_multiplier from article data.
    # CRITICAL = >25% procurement budget compression; MODERATE = 12-25%.
    ("macro_economic", "CRITICAL"): "Macro/inflation shock",
    ("macro_economic", "MODERATE"): "Macro/inflation shock",
    ("macro_economic", "MINOR"):    "Baseline",
}

# Default disruption duration per shock_type, in days (used by dynamic path
# because Claude does not extract duration). Calibrated to the family of
# durations in SCENARIO_PARAMS and to literature on shock recovery times.
DEFAULT_DURATION_BY_SHOCK = {
    "manufacturing":  90,    # Izen 2025: 2023 cisplatin shortage lasted ~3-4 months
    "logistics":      60,    # Port congestion / customs typically resolves in ~2 months
    "regulatory":    365,    # Pricing controls and patent rulings persist 1+ year
    "demand":        180,    # Disease surges / guideline changes persist ~6 months
    "currency":      180,    # Peso devaluations are prolonged structural events
    "political":     120,    # Trade restrictions / sanctions resolve in ~4 months
    "climate":        60,    # Floods, landslides resolve in weeks-to-months
    "company":        90,    # Recalls / facility issues resolve in ~3 months
    "macro_economic": 270,   # Oil/inflation cycles persist 9 months (UBA economist May 2026:
                             # "impact not yet fully realized, at least until mid-year, perhaps following months")
}

# Sentinel: values within this tolerance of the no-shock defaults are treated
# as "Claude returned defaults" (no quantitative reading) → fallback to SCENARIO_MAP.
_NO_INFO_TOL = 1e-3


def _clamp(value, low, high, default):
    """Clamp value to [low, high]; use default if not numeric / NaN."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN check
        return default
    return max(low, min(high, v))


def _extract_impact_params(classification: dict) -> Optional[dict]:
    """
    Extract and clamp Claude's impact parameters from an event_classifier result.

    Returns a dict of clamped multipliers if at least ONE parameter deviates
    meaningfully from the no-shock defaults (i.e., Claude actually quantified
    impact). Returns None when the impact dict is missing, empty, or all values
    are at no-shock defaults — in which case the caller should fall back to
    SCENARIO_MAP.

    Clamping ranges (defense against bad LLM output):
      lead_time_multiplier: [1.0, 5.0]   (a shock cannot speed delivery)
      demand_multiplier:    [0.5, 2.0]
      fill_rate:            [0.10, 1.0]
      budget_multiplier:    [0.20, 1.0]
    """
    impact = classification.get("impact")
    if not impact or not isinstance(impact, dict):
        return None

    clamped = {
        "lead_time_multiplier": _clamp(impact.get("lead_time_multiplier", 1.0), 1.0, 5.0, 1.0),
        "demand_multiplier":    _clamp(impact.get("demand_multiplier",    1.0), 0.5, 2.0, 1.0),
        "fill_rate":            _clamp(impact.get("fill_rate",            0.95), 0.10, 1.0, 0.95),
        "budget_multiplier":    _clamp(impact.get("budget_multiplier",    1.0), 0.20, 1.0, 1.0),
    }

    # If every parameter is essentially at its no-shock default, Claude provided
    # no quantitative reading — fall back to the discretized SCENARIO_MAP.
    deviates = (
        abs(clamped["lead_time_multiplier"] - 1.0) > _NO_INFO_TOL or
        abs(clamped["demand_multiplier"]    - 1.0) > _NO_INFO_TOL or
        abs(clamped["fill_rate"]            - 0.95) > _NO_INFO_TOL or
        abs(clamped["budget_multiplier"]    - 1.0) > _NO_INFO_TOL
    )
    return clamped if deviates else None


def trigger_simulation(event_classification: dict, drug: str, country: str) -> dict:
    """
    Run baseline → shocked simulation pair and compute risk delta.

    Path selection:
      • If event_classifier returned non-default impact parameters,
        run simulate_dynamic with those values (preferred — uses Claude's
        article-specific quantitative reading).
      • Otherwise fall back to SCENARIO_MAP lookup (legacy path).

    Args:
        event_classification: From event_classifier.py — must include
                              severity, shock_type, optional impact dict.
        drug: Target drug (e.g., "cisplatin").
        country: Target country (e.g., "Venezuela").

    Returns:
        dict with baseline_risk, shocked_risk, risk_delta, shock_type,
        simulation_mode ("dynamic" | "scenario_map"), and applied_scenario
        (named scenario when scenario_map; "_dynamic_" when dynamic).
    """
    severity = event_classification.get("severity", "IRRELEVANT")
    shock_type = event_classification.get("shock_type", "unknown")

    if severity == "IRRELEVANT":
        return {
            "drug": drug,
            "country": country,
            "shock_type": shock_type,
            "status": "no_shock",
            "simulation_mode": "skipped",
            "baseline_risk": None,
            "shocked_risk": None,
            "risk_delta": 0,
        }

    try:
        # 1. Baseline (always uses the named "Baseline" scenario)
        baseline_result = simulate(
            drug=drug, country=country, scenario="Baseline", n_runs=500
        )
        baseline_risk = baseline_result["stockout_days_mean"]
        baseline_cvar = baseline_result["cvar_90"]

        # 2. Choose path: dynamic (preferred) vs. scenario_map (fallback)
        impact_params = _extract_impact_params(event_classification)

        if impact_params is not None:
            # Dynamic path — consume Claude's continuous impact parameters
            duration = DEFAULT_DURATION_BY_SHOCK.get(shock_type, 120)
            shocked_result = simulate_dynamic(
                drug=drug, country=country,
                lead_time_multiplier=impact_params["lead_time_multiplier"],
                demand_multiplier=impact_params["demand_multiplier"],
                fill_rate=impact_params["fill_rate"],
                budget_multiplier=impact_params["budget_multiplier"],
                disruption_duration_mean=duration,
                n_runs=500,
            )
            simulation_mode = "dynamic"
            applied_scenario = "_dynamic_"
            applied_params = impact_params
        else:
            # Fallback — SCENARIO_MAP lookup
            applied_scenario = SCENARIO_MAP.get((shock_type, severity), "Baseline")
            shocked_result = simulate(
                drug=drug, country=country, scenario=applied_scenario, n_runs=500
            )
            simulation_mode = "scenario_map"
            applied_params = None

        shocked_risk = shocked_result["stockout_days_mean"]
        shocked_cvar = shocked_result["cvar_90"]

        risk_delta = shocked_risk - baseline_risk
        cvar_delta = shocked_cvar - baseline_cvar

        # Anti-artifact: (Q,r) safety-stock adaptation can paradoxically reduce
        # simulated stockouts when lead-time increase dominates fill-rate degradation
        # (Badejo & Ierapetritou 2022 §4.3). A CRITICAL/MODERATE event cannot
        # realistically improve drug availability. If baseline is not already at
        # structural floor (≥60d = Venezuela-class collapse), negative delta is an
        # artifact → fall back to SCENARIO_MAP for a conservative monotone estimate.
        if severity in ("CRITICAL", "MODERATE") and risk_delta < 0 and baseline_risk < 60:
            fallback_scenario = SCENARIO_MAP.get((shock_type, severity), "Baseline")
            fallback_result = simulate(
                drug=drug, country=country, scenario=fallback_scenario, n_runs=500
            )
            shocked_risk     = fallback_result["stockout_days_mean"]
            shocked_cvar     = fallback_result["cvar_90"]
            risk_delta       = shocked_risk - baseline_risk
            cvar_delta       = shocked_cvar - baseline_cvar
            simulation_mode  = "scenario_map_fallback"
            applied_scenario = fallback_scenario

        return {
            "drug": drug,
            "country": country,
            "shock_type": shock_type,
            "event_classification": severity,
            "simulation_mode": simulation_mode,
            "applied_scenario": applied_scenario,
            "applied_impact_params": applied_params,
            "status": "simulated",
            "baseline_risk": round(baseline_risk, 1),
            "baseline_cvar_90": round(baseline_cvar, 1),
            "shocked_risk": round(shocked_risk, 1),
            "shocked_cvar_90": round(shocked_cvar, 1),
            "risk_delta": round(risk_delta, 1),
            "cvar_delta": round(cvar_delta, 1),
            "percent_increase": round((risk_delta / baseline_risk * 100) if baseline_risk > 0 else 0, 1),
        }

    except Exception as e:
        return {
            "drug": drug,
            "country": country,
            "shock_type": shock_type,
            "status": f"simulation_error: {str(e)}",
            "simulation_mode": "error",
            "baseline_risk": None,
            "shocked_risk": None,
            "risk_delta": None,
        }


if __name__ == "__main__":
    # Test 1: Dynamic path — Claude provides quantitative impact
    print("=== Test 1: Manufacturing CRITICAL with Claude impact params (DYNAMIC) ===")
    test_dynamic = {
        "severity": "CRITICAL",
        "shock_type": "manufacturing",
        "affected_drugs": ["cisplatin"],
        "affected_countries": ["Argentina"],
        "impact": {
            "lead_time_multiplier": 3.0,
            "demand_multiplier":    1.0,
            "fill_rate":            0.55,
            "budget_multiplier":    1.0,
        },
        "reasoning": "India API factory strike — 3x lead time, 55% fill rate"
    }
    result = trigger_simulation(test_dynamic, "cisplatin", "Argentina")
    print(json.dumps(result, indent=2))

    # Test 2: Fallback path — Claude returns no impact (or all defaults)
    print("\n=== Test 2: Currency MODERATE without impact params (FALLBACK to SCENARIO_MAP) ===")
    test_fallback = {
        "severity": "MODERATE",
        "shock_type": "currency",
        "affected_drugs": ["doxorubicin"],
        "affected_countries": ["Argentina"],
        "reasoning": "Peso devaluation reported (no quantitative impact in article)"
        # NOTE: no "impact" key — should trigger fallback
    }
    result = trigger_simulation(test_fallback, "doxorubicin", "Argentina")
    print(json.dumps(result, indent=2))

    # Test 3: Defense — Claude returns out-of-range values (should clamp)
    print("\n=== Test 3: Defensive clamping — bad Claude output ===")
    test_bad = {
        "severity": "CRITICAL",
        "shock_type": "logistics",
        "impact": {
            "lead_time_multiplier": 99.0,    # nonsense, should clamp to 5.0
            "demand_multiplier":    0.1,      # below floor, should clamp to 0.5
            "fill_rate":            -0.5,     # negative, should clamp to 0.10
            "budget_multiplier":    "NaN",    # bad type, should default to 1.0
        },
        "reasoning": "Garbage LLM output stress test"
    }
    result = trigger_simulation(test_bad, "trastuzumab", "Venezuela")
    print(json.dumps(result, indent=2))

    # Test 4: All-default impact (Claude provided no info) → should fallback
    print("\n=== Test 4: Claude returns all-default impact (FALLBACK) ===")
    test_default_impact = {
        "severity": "MODERATE",
        "shock_type": "climate",
        "impact": {
            "lead_time_multiplier": 1.0,
            "demand_multiplier":    1.0,
            "fill_rate":            0.95,
            "budget_multiplier":    1.0,
        },
        "reasoning": "Climate event reported but Claude could not quantify impact"
    }
    result = trigger_simulation(test_default_impact, "carboplatin", "Colombia")
    print(json.dumps(result, indent=2))
