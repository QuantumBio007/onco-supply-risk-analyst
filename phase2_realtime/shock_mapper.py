"""
shock_mapper.py — Map classified events to supply_sim.py, compute risk deltas.

Takes event classification and runs supply_sim.py twice:
  1. Baseline scenario (no shock)
  2. Shocked scenario (with event parameters)
  3. Returns risk comparison (stockout days baseline vs shocked)
"""

import json
from pathlib import Path
import sys

# Add parent to path for supply_sim import
sys.path.insert(0, str(Path(__file__).parent.parent))
from supply_sim import simulate


# Shock type → scenario mapping
# Maps (shock_type, severity) to the most appropriate supply_sim scenario
SCENARIO_MAP = {
    # Manufacturing disruptions: API delays, quality issues
    ("manufacturing", "CRITICAL"): "API export restriction",
    ("manufacturing", "MODERATE"): "API export restriction",
    ("manufacturing", "MINOR"): "Baseline",

    # Logistics disruptions: Port/shipping delays, road closures
    ("logistics", "CRITICAL"): "Combined shock",
    ("logistics", "MODERATE"): "API export restriction",
    ("logistics", "MINOR"): "Baseline",

    # Regulatory shocks: Pricing, approvals, policy changes
    ("regulatory", "CRITICAL"): "Combined shock",
    ("regulatory", "MODERATE"): "API export restriction",
    ("regulatory", "MINOR"): "Baseline",

    # Demand shocks: Disease outbreaks, surge in oncology cases
    ("demand", "CRITICAL"): "Combined shock",
    ("demand", "MODERATE"): "Baseline",  # Demand alone doesn't break supply
    ("demand", "MINOR"): "Baseline",

    # Currency shocks: FX volatility affecting procurement
    ("currency", "CRITICAL"): "Combined shock",
    ("currency", "MODERATE"): "Baseline",
    ("currency", "MINOR"): "Baseline",

    # Political instability: Trade wars, sanctions, border closures
    ("political", "CRITICAL"): "Combined shock",
    ("political", "MODERATE"): "API export restriction",
    ("political", "MINOR"): "Baseline",

    # Climate disruptions: Flooding, landslides affecting LATAM logistics
    ("climate", "CRITICAL"): "Combined shock",
    ("climate", "MODERATE"): "API export restriction",
    ("climate", "MINOR"): "Baseline",

    # Company-level events: Recalls, M&A, supply agreements
    ("company", "CRITICAL"): "API export restriction",
    ("company", "MODERATE"): "Baseline",
    ("company", "MINOR"): "Baseline",
}


def trigger_simulation(event_classification: dict, drug: str, country: str) -> dict:
    """
    Run simulation: baseline → shocked → compare risk.

    Uses shock_type to select appropriate scenario (manufacturing → API delays,
    logistics → combined disruption, etc.), enabling differentiated risk modeling.

    Args:
        event_classification: From event_classifier.py (includes shock_type)
        drug: Target drug (e.g., "cisplatin")
        country: Target country (e.g., "Venezuela")

    Returns:
        dict with baseline_risk, shocked_risk, risk_delta, shock_type, applied_scenario
    """

    classification = event_classification.get("classification", "IRRELEVANT")
    shock_type = event_classification.get("shock_type", "unknown")

    if classification == "IRRELEVANT":
        return {
            "drug": drug,
            "country": country,
            "shock_type": shock_type,
            "status": "no_shock",
            "baseline_risk": None,
            "shocked_risk": None,
            "risk_delta": 0,
        }

    try:
        # 1. Run baseline (no shock scenario)
        baseline_result = simulate(
            drug=drug, country=country, scenario="Baseline", n_runs=500
        )
        baseline_risk = baseline_result["stockout_days_mean"]
        baseline_cvar = baseline_result["cvar_90"]

        # 2. Map (shock_type, severity) to appropriate scenario
        # This differentiation allows manufacturing shocks to affect API delays differently
        # than logistics shocks (which affect multiple parameters simultaneously)
        scenario = SCENARIO_MAP.get(
            (shock_type, classification),
            "Baseline"  # Default if unmapped combination
        )

        # 3. Run shocked scenario
        shocked_result = simulate(
            drug=drug, country=country, scenario=scenario, n_runs=500
        )
        shocked_risk = shocked_result["stockout_days_mean"]
        shocked_cvar = shocked_result["cvar_90"]

        # 4. Compute deltas
        risk_delta = shocked_risk - baseline_risk
        cvar_delta = shocked_cvar - baseline_cvar

        return {
            "drug": drug,
            "country": country,
            "shock_type": shock_type,
            "event_classification": classification,
            "applied_scenario": scenario,
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
            "baseline_risk": None,
            "shocked_risk": None,
            "risk_delta": None,
        }


if __name__ == "__main__":
    # Test: Manufacturing shock (API disruption)
    test_event_manufacturing = {
        "classification": "CRITICAL",
        "shock_type": "manufacturing",
        "affected_drugs": ["cisplatin"],
        "affected_countries": ["Argentina"],
        "impact": {"lead_time_multiplier": 3.0, "fill_rate": 0.55},
        "reasoning": "India API factory strike"
    }

    print("=== Manufacturing Shock (CRITICAL) ===")
    result = trigger_simulation(test_event_manufacturing, "cisplatin", "Argentina")
    print(json.dumps(result, indent=2))

    # Test: Logistics shock (Port closure)
    test_event_logistics = {
        "classification": "MODERATE",
        "shock_type": "logistics",
        "affected_drugs": ["trastuzumab"],
        "affected_countries": ["Colombia"],
        "impact": {"lead_time_multiplier": 2.5, "fill_rate": 0.75},
        "reasoning": "Santos port flooding delays"
    }

    print("\n=== Logistics Shock (MODERATE) ===")
    result = trigger_simulation(test_event_logistics, "trastuzumab", "Colombia")
    print(json.dumps(result, indent=2))

    # Test: Political shock (Trade war)
    test_event_political = {
        "classification": "CRITICAL",
        "shock_type": "political",
        "affected_drugs": ["doxorubicin"],
        "affected_countries": ["Venezuela"],
        "impact": {"lead_time_multiplier": 4.0, "fill_rate": 0.4},
        "reasoning": "Border closure affecting supply"
    }

    print("\n=== Political Shock (CRITICAL) ===")
    result = trigger_simulation(test_event_political, "doxorubicin", "Venezuela")
    print(json.dumps(result, indent=2))
