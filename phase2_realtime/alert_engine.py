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
"""

import json
from datetime import datetime
from typing import Optional


# Severity rank for max-of-triggers composition
_SEVERITY_RANK = {"none": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
_SEVERITY_NAME = {0: "none", 1: "MODERATE", 2: "HIGH", 3: "CRITICAL"}


def _mean_trigger(baseline_risk: float, shocked_risk: float):
    """Return (severity_level, percent_increase, trigger_label or None) for mean dimension."""
    delta = shocked_risk - baseline_risk
    pct = (delta / baseline_risk * 100) if baseline_risk > 0 else 0
    # Mean stockout thresholds (days/yr): 60=2mo critical, 30=chronic, 14=meaningful
    # Relative thresholds catch shocks against low baselines.
    if pct >= 100 or shocked_risk >= 60:
        return 3, pct, "mean_critical"
    if pct >= 50 or shocked_risk >= 30:
        return 2, pct, "mean_high"
    if pct >= 25 or shocked_risk >= 14:
        return 1, pct, "mean_moderate"
    return 0, pct, None


def _cvar_abs_trigger(shocked_cvar: float):
    """Return (severity_level, trigger_label or None) for absolute CVaR dimension."""
    # Absolute CVaR_90 thresholds (worst-10% mean stockout days/yr).
    # Higher than mean thresholds because tail is supposed to exceed mean.
    if shocked_cvar >= 90:
        return 3, "cvar_abs_critical"
    if shocked_cvar >= 45:
        return 2, "cvar_abs_high"
    if shocked_cvar >= 21:
        return 1, "cvar_abs_moderate"
    return 0, None


def _cvar_rel_trigger(baseline_cvar: float, shocked_cvar: float):
    """Return (severity_level, percent_increase, trigger_label or None) for relative CVaR dimension."""
    delta = shocked_cvar - baseline_cvar
    pct = (delta / baseline_cvar * 100) if baseline_cvar > 0 else 0
    if pct >= 100:
        return 3, pct, "cvar_rel_critical"
    if pct >= 50:
        return 2, pct, "cvar_rel_high"
    if pct >= 25:
        return 1, pct, "cvar_rel_moderate"
    return 0, pct, None


def evaluate_risk_change(
    baseline_risk: float,
    shocked_risk: float,
    baseline_cvar: Optional[float] = None,
    shocked_cvar: Optional[float] = None,
) -> dict:
    """
    Evaluate if risk change warrants alert.

    Severity is the MAXIMUM trigger across three dimensions:
      • Mean stockout days (existing): absolute (>=60/30/14) or relative (>=100%/50%/25%)
      • CVaR_90 absolute: shocked CVaR (>=90/45/21 days)
      • CVaR_90 relative: % increase in CVaR (>=100%/50%/25%)

    CVaR dimensions are skipped when baseline_cvar / shocked_cvar are not provided.
    Existing callers (mean-only) keep working unchanged.

    Args:
        baseline_risk: Baseline mean stockout days/yr
        shocked_risk:  Shocked mean stockout days/yr
        baseline_cvar: Baseline CVaR_90 (optional but strongly recommended)
        shocked_cvar:  Shocked CVaR_90  (optional but strongly recommended)

    Returns:
        dict with severity, should_alert, all numerical fields, and triggers[] for audit.
    """
    triggers = []
    level = 0

    mean_level, mean_pct, mean_label = _mean_trigger(baseline_risk, shocked_risk)
    if mean_label:
        triggers.append(mean_label)
    level = max(level, mean_level)

    cvar_delta = None
    cvar_pct = None
    if baseline_cvar is not None and shocked_cvar is not None:
        cvar_delta = shocked_cvar - baseline_cvar

        abs_level, abs_label = _cvar_abs_trigger(shocked_cvar)
        if abs_label:
            triggers.append(abs_label)
        level = max(level, abs_level)

        rel_level, cvar_pct, rel_label = _cvar_rel_trigger(baseline_cvar, shocked_cvar)
        if rel_label:
            triggers.append(rel_label)
        level = max(level, rel_level)

    severity = _SEVERITY_NAME[level]
    should_alert = level >= 1

    # Compose summary message
    parts = [f"mean {baseline_risk:.1f}d→{shocked_risk:.1f}d ({mean_pct:+.0f}%)"]
    if baseline_cvar is not None and shocked_cvar is not None:
        parts.append(f"CVaR_90 {baseline_cvar:.1f}d→{shocked_cvar:.1f}d ({cvar_pct:+.0f}%)")
    summary = " | ".join(parts)

    if severity == "none":
        message = f"No action needed. {summary}"
    else:
        icon = "⚠️" if severity in ("CRITICAL", "HIGH") else "ℹ️"
        trigger_str = ",".join(triggers) if triggers else "—"
        message = f"{icon} {severity}: {summary}  [triggers: {trigger_str}]"

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

{cvar_section}Triggers fired: {triggers_str}

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
