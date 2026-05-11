"""
alert_engine.py — Generate and send alerts when risk threshold exceeded.

Compares baseline risk vs. shocked risk along THREE independent dimensions:
  1. Mean stockout days (per year): captures expected supply impact
  2. CVaR_90 absolute (worst-10% mean): captures tail risk magnitude
  3. CVaR_90 relative (% increase): captures tail risk amplification

Severity is the MAXIMUM trigger across the three dimensions. This is critical:
the (Q,r) policy in supply_sim.py adapts to long lead times by raising the
reorder point (r = d × L_mean + SS), which can SUPPRESS mean stockout while
DOUBLING CVaR_90 — a real false-negative hazard if alerts use mean only.
Discovered during H1 testing 2026-05-03; see STRATEGIC_REVIEW_2026-05-03.md.

Macro-economic shocks (currency_devaluation, budget_cut, inflation, currency,
macro_economic) produce smaller absolute deltas than direct supply shocks but
are SYSTEMIC — they affect all drugs simultaneously. A separate lower-threshold
path (60% of normal) is applied when shock_type is a macro variant, and fires
a "macro_systemic" trigger label to distinguish it from normal-threshold alerts.
"""

import json
from datetime import datetime
from typing import Optional


# Severity rank for max-of-triggers composition
_SEVERITY_RANK = {"none": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
_SEVERITY_NAME = {0: "none", 1: "MODERATE", 2: "HIGH", 3: "CRITICAL"}

# Shock types that warrant lower detection thresholds.
# Macro shocks are systemic (affect all drugs simultaneously) but produce
# smaller per-drug deltas than direct supply-chain events.
MACRO_SHOCK_TYPES = {
    "currency_devaluation",
    "budget_cut",
    "inflation",
    "currency",
    "macro",
    "macro_economic",
}

# Multiplier applied to all thresholds for macro shocks.
# 0.60 means thresholds are 60% of their normal values.
_MACRO_THRESHOLD_FACTOR = 0.60

# ── FIX (2026-05-07): single source of truth for alert thresholds ───────────
# Audit finding: magic numbers were duplicated across three trigger functions
# and inline in comments. Extracted here so threshold changes touch one place.
# Keys: "critical" → severity 3, "high" → 2, "moderate" → 1.
THRESHOLDS = {
    "mean_pct":  {"critical": 100, "high": 50, "moderate": 25},   # % increase
    "mean_abs":  {"critical":  60, "high": 30, "moderate": 14},   # days/yr
    "cvar_abs":  {"critical":  90, "high": 45, "moderate": 21},   # days/yr
    "cvar_pct":  {"critical": 100, "high": 50, "moderate": 25},   # % increase
}


def _mean_trigger(baseline_risk: float, shocked_risk: float, macro: bool = False):
    """Return (severity_level, percent_increase, trigger_label or None) for mean dimension.

    Args:
        macro: When True, use 60% of normal absolute and relative thresholds.
    """
    delta = shocked_risk - baseline_risk
    pct = (delta / baseline_risk * 100) if baseline_risk > 0 else 0

    # Mean stockout: 60d=2mo critical, 30d=chronic, 14d=meaningful.
    # Relative thresholds catch shocks against low baselines.
    f = _MACRO_THRESHOLD_FACTOR if macro else 1.0
    pT, aT = THRESHOLDS["mean_pct"], THRESHOLDS["mean_abs"]
    if pct >= pT["critical"] * f or shocked_risk >= aT["critical"] * f:
        return 3, pct, "mean_critical"
    if pct >= pT["high"]     * f or shocked_risk >= aT["high"]     * f:
        return 2, pct, "mean_high"
    if pct >= pT["moderate"] * f or shocked_risk >= aT["moderate"] * f:
        return 1, pct, "mean_moderate"
    return 0, pct, None


def _cvar_abs_trigger(shocked_cvar: float, macro: bool = False):
    """Return (severity_level, trigger_label or None) for absolute CVaR dimension.

    Args:
        macro: When True, use 60% of normal absolute thresholds.
    """
    # Absolute CVaR_90 (worst-10% mean stockout days/yr). Higher than mean
    # thresholds because the tail is supposed to exceed the mean.
    f = _MACRO_THRESHOLD_FACTOR if macro else 1.0
    aT = THRESHOLDS["cvar_abs"]
    if shocked_cvar >= aT["critical"] * f:
        return 3, "cvar_abs_critical"
    if shocked_cvar >= aT["high"]     * f:
        return 2, "cvar_abs_high"
    if shocked_cvar >= aT["moderate"] * f:
        return 1, "cvar_abs_moderate"
    return 0, None


def _cvar_rel_trigger(baseline_cvar: float, shocked_cvar: float, macro: bool = False):
    """Return (severity_level, percent_increase, trigger_label or None) for relative CVaR dimension.

    Args:
        macro: When True, use 60% of normal relative thresholds.
    """
    delta = shocked_cvar - baseline_cvar
    pct = (delta / baseline_cvar * 100) if baseline_cvar > 0 else 0
    f = _MACRO_THRESHOLD_FACTOR if macro else 1.0
    pT = THRESHOLDS["cvar_pct"]
    if pct >= pT["critical"] * f:
        return 3, pct, "cvar_rel_critical"
    if pct >= pT["high"]     * f:
        return 2, pct, "cvar_rel_high"
    if pct >= pT["moderate"] * f:
        return 1, pct, "cvar_rel_moderate"
    return 0, pct, None


def evaluate_risk_change(
    baseline_risk: float,
    shocked_risk: float,
    baseline_cvar: Optional[float] = None,
    shocked_cvar: Optional[float] = None,
    shock_type: str = "unknown",
) -> dict:
    """
    Evaluate if risk change warrants alert.

    Severity is the MAXIMUM trigger across three dimensions:
      • Mean stockout days (existing): absolute (>=60/30/14) or relative (>=100%/50%/25%)
      • CVaR_90 absolute: shocked CVaR (>=90/45/21 days)
      • CVaR_90 relative: % increase in CVaR (>=100%/50%/25%)

    CVaR dimensions are skipped when baseline_cvar / shocked_cvar are not provided.
    Existing callers (mean-only) keep working unchanged.

    Macro-economic shocks (shock_type in MACRO_SHOCK_TYPES) use 60% of normal
    thresholds because macro shocks are systemic — affecting all drugs at once —
    even when per-drug deltas are small. A "macro_systemic" trigger label is added
    when the lower threshold fires but the normal threshold would not.

    Args:
        baseline_risk: Baseline mean stockout days/yr
        shocked_risk:  Shocked mean stockout days/yr
        baseline_cvar: Baseline CVaR_90 (optional but strongly recommended)
        shocked_cvar:  Shocked CVaR_90  (optional but strongly recommended)
        shock_type:    Shock category from event_classifier (default "unknown").
                       Callers that do not pass this argument get normal thresholds.

    Returns:
        dict with severity, should_alert, all numerical fields, triggers[] for audit,
        and shock_type for downstream traceability.
    """
    is_macro = shock_type in MACRO_SHOCK_TYPES
    triggers = []
    level = 0

    # --- Mean dimension (normal thresholds) ---
    mean_level, mean_pct, mean_label = _mean_trigger(baseline_risk, shocked_risk, macro=False)
    if mean_label:
        triggers.append(mean_label)
    level = max(level, mean_level)

    # --- Mean dimension (macro lower thresholds, when applicable) ---
    # Only add "macro_systemic" if the lower threshold fires but the normal one did not.
    if is_macro:
        macro_mean_level, _, macro_mean_label = _mean_trigger(baseline_risk, shocked_risk, macro=True)
        if macro_mean_label and macro_mean_level > mean_level:
            triggers.append("macro_systemic")
            level = max(level, macro_mean_level)

    cvar_delta = None
    cvar_pct = None
    if baseline_cvar is not None and shocked_cvar is not None:
        cvar_delta = shocked_cvar - baseline_cvar

        # --- CVaR absolute dimension (normal) ---
        abs_level, abs_label = _cvar_abs_trigger(shocked_cvar, macro=False)
        if abs_label:
            triggers.append(abs_label)
        level = max(level, abs_level)

        # --- CVaR absolute dimension (macro lower thresholds) ---
        if is_macro:
            macro_abs_level, macro_abs_label = _cvar_abs_trigger(shocked_cvar, macro=True)
            if macro_abs_label and macro_abs_level > abs_level:
                if "macro_systemic" not in triggers:
                    triggers.append("macro_systemic")
                level = max(level, macro_abs_level)

        # --- CVaR relative dimension (normal) ---
        rel_level, cvar_pct, rel_label = _cvar_rel_trigger(baseline_cvar, shocked_cvar, macro=False)
        if rel_label:
            triggers.append(rel_label)
        level = max(level, rel_level)

        # --- CVaR relative dimension (macro lower thresholds) ---
        if is_macro:
            macro_rel_level, _, macro_rel_label = _cvar_rel_trigger(baseline_cvar, shocked_cvar, macro=True)
            if macro_rel_label and macro_rel_level > rel_level:
                if "macro_systemic" not in triggers:
                    triggers.append("macro_systemic")
                level = max(level, macro_rel_level)

        # Ensure cvar_pct is set even when only macro path fired
        if cvar_pct is None:
            _, cvar_pct, _ = _cvar_rel_trigger(baseline_cvar, shocked_cvar, macro=False)

    severity = _SEVERITY_NAME[level]
    should_alert = level >= 1

    # Compose summary message
    parts = [f"mean {baseline_risk:.1f}d→{shocked_risk:.1f}d ({mean_pct:+.0f}%)"]
    if baseline_cvar is not None and shocked_cvar is not None:
        parts.append(f"CVaR_90 {baseline_cvar:.1f}d→{shocked_cvar:.1f}d ({cvar_pct:+.0f}%)")
    summary = " | ".join(parts)

    macro_note = " [MACRO/SYSTEMIC]" if is_macro and "macro_systemic" in triggers else ""
    if severity == "none":
        message = f"No action needed. {summary}"
    else:
        icon = "⚠️" if severity in ("CRITICAL", "HIGH") else "ℹ️"
        trigger_str = ",".join(triggers) if triggers else "—"
        message = f"{icon} {severity}: {summary}  [triggers: {trigger_str}]{macro_note}"

    return {
        "timestamp": datetime.now().isoformat(),
        "baseline_risk": baseline_risk,
        "shocked_risk": shocked_risk,
        "risk_delta": shocked_risk - baseline_risk,
        "percent_increase": mean_pct,
        "baseline_cvar": baseline_cvar,
        "shocked_cvar": shocked_cvar,
        "cvar_delta": cvar_delta,
        "cvar_percent_increase": cvar_pct,
        "should_alert": should_alert,
        "severity": severity,
        "triggers": triggers,
        "shock_type": shock_type,
        "message": message,
    }


def format_alert(alert: dict, drug: str, country: str, event_title: str) -> str:
    """Format alert for client delivery (email/Streamlit notification)."""

    if alert["severity"] == "none":
        return f"[{country}] {drug}: No supply chain impact detected."

    cvar_section = ""
    if alert.get("baseline_cvar") is not None and alert.get("shocked_cvar") is not None:
        cvar_section = (
            f"Tail risk (CVaR_90, worst-10% mean stockout):\n"
            f"  Baseline:  {alert['baseline_cvar']:.1f} days\n"
            f"  Shocked:   {alert['shocked_cvar']:.1f} days\n"
            f"  Change:    {alert['cvar_delta']:+.1f} days ({alert['cvar_percent_increase']:+.0f}%)\n\n"
        )

    triggers_str = ",".join(alert.get("triggers", [])) or "—"

    # Surface macro-systemic context when the lower threshold path fired.
    shock_type = alert.get("shock_type", "unknown")
    is_macro_alert = "macro_systemic" in alert.get("triggers", [])
    macro_section = ""
    if is_macro_alert:
        macro_section = (
            f"Shock context: MACRO/SYSTEMIC ({shock_type})\n"
            f"  This shock is systemic — it compresses procurement budgets across\n"
            f"  ALL oncology drugs simultaneously. Per-drug deltas are smaller than\n"
            f"  direct supply events but the aggregate exposure is elevated.\n"
            f"  Lower detection thresholds applied (60% of normal).\n\n"
        )

    msg = f"""
╔══════════════════════════════════════════════════╗
║ ONCOSUPPLY RISK ALERT                           ║
╚══════════════════════════════════════════════════╝

Drug: {drug}
Country: {country}
Event: {event_title}
Severity: {alert['severity']}

{alert['message']}

Mean stockout days/year:
  Baseline:  {alert['baseline_risk']:.1f}
  Shocked:   {alert['shocked_risk']:.1f}
  Change:    {alert['risk_delta']:+.1f} days ({alert['percent_increase']:+.0f}%)

{cvar_section}{macro_section}Triggers fired: {triggers_str}

Recommendation:
- Review current inventory levels
- Consider accelerated procurement
- Evaluate alternative suppliers

Generated: {alert['timestamp']}
"""
    return msg.strip()


if __name__ == "__main__":
    print("=== Test 1: mean-only (legacy interface) — should still work ===")
    a = evaluate_risk_change(baseline_risk=7.0, shocked_risk=35.0)
    print(json.dumps({k: v for k, v in a.items() if k != "timestamp"}, indent=2))

    print("\n=== Test 2: CVaR-only trigger (mean delta negative — H1 test 1 case) ===")
    # cisplatin/Argentina manufacturing CRITICAL: mean drops slightly, CVaR jumps 84%.
    # Old engine: NO ALERT. New engine: HIGH on cvar_rel_high.
    a = evaluate_risk_change(
        baseline_risk=7.0, shocked_risk=6.0,
        baseline_cvar=23.2, shocked_cvar=42.8,
    )
    print(json.dumps({k: v for k, v in a.items() if k != "timestamp"}, indent=2))

    print("\n=== Test 3: Mean + CVaR both critical (Trastuzumab/Venezuela) ===")
    # Updated 2026-05-03 (session 17): canonical Venezuela trastuzumab Baseline
    # recalibrated to 185.4d / CVaR_90=203.8 (was 79.3 / 103.3 prior to structural
    # parameter recalibration validated against Lancet 2017 / ENH 2024 reality).
    a = evaluate_risk_change(
        baseline_risk=185.4, shocked_risk=184.0,
        baseline_cvar=203.8, shocked_cvar=240.0,
    )
    print(json.dumps({k: v for k, v in a.items() if k != "timestamp"}, indent=2))

    print("\n=== Test 4: No alert — fallback case where CVaR DECREASED ===")
    a = evaluate_risk_change(
        baseline_risk=7.3, shocked_risk=5.8,
        baseline_cvar=24.7, shocked_cvar=19.5,
    )
    print(json.dumps({k: v for k, v in a.items() if k != "timestamp"}, indent=2))

    print("\n=== Formatted alert (Test 2 case) ===")
    a = evaluate_risk_change(
        baseline_risk=7.0, shocked_risk=6.0,
        baseline_cvar=23.2, shocked_cvar=42.8,
    )
    print(format_alert(a, "cisplatin", "Argentina", "India halts API exports"))

    print("\n=== Test 5: Macro smoke test — Trastuzumab/Colombia currency devaluation ===")
    # Δmean=+1.3d (baseline 8.0 → 9.3), ΔCVaR=+3.2d (baseline 15.0 → 18.2)
    #
    # Normal thresholds — why they stay silent:
    #   mean: pct=+16.25% < 25%; abs=9.3 < 14  → no trigger
    #   CVaR abs: 18.2 < 21                      → no trigger
    #   CVaR rel: pct=+21.3% < 25%               → no trigger
    #
    # Macro thresholds (60% of normal) — why they fire:
    #   mean: pct=+16.25% ≥ 15% (60%×25)         → macro_systemic + mean_moderate
    #   CVaR abs: 18.2 ≥ 12.6 (60%×21)           → macro_systemic + cvar_abs_moderate
    #   CVaR rel: pct=+21.3% ≥ 15% (60%×25)      → macro_systemic + cvar_rel_moderate
    a_no_macro = evaluate_risk_change(
        baseline_risk=8.0, shocked_risk=9.3,
        baseline_cvar=15.0, shocked_cvar=18.2,
    )
    a_macro = evaluate_risk_change(
        baseline_risk=8.0, shocked_risk=9.3,
        baseline_cvar=15.0, shocked_cvar=18.2,
        shock_type="currency_devaluation",
    )
    print(f"  Without shock_type → should_alert={a_no_macro['should_alert']}, severity={a_no_macro['severity']}, triggers={a_no_macro['triggers']}")
    print(f"  With shock_type='currency_devaluation' → should_alert={a_macro['should_alert']}, severity={a_macro['severity']}, triggers={a_macro['triggers']}")

    # Assertion: macro path MUST fire; normal path must NOT
    assert not a_no_macro["should_alert"], (
        f"REGRESSION: normal path fired unexpectedly — triggers={a_no_macro['triggers']}"
    )
    assert a_macro["should_alert"], (
        f"FAIL: macro path did not fire for trastuzumab/Colombia case"
    )
    assert "macro_systemic" in a_macro["triggers"], (
        f"FAIL: 'macro_systemic' trigger label missing — triggers={a_macro['triggers']}"
    )
    print("  [PASS] Trastuzumab/Colombia macro smoke test passed.")
    print()
    print(format_alert(a_macro, "trastuzumab", "Colombia", "Colombia peso devaluation 2026"))
