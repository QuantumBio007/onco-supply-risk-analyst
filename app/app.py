import streamlit as st
import sys
import os
import json
import csv
import datetime
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Human-AI Fusion helpers ──────────────────────────────────────────────────
# These implement the design responses from the OncoSupply Human-AI Fusion
# review (confidence tier, predict-first ritual, override audit log) per
# BU.330.765 course concepts (Dietvorst 2015 algorithm aversion, Wang 2023
# Knowledge Trap, Moffatt v. Air Canada liability, Brynjolfsson 2019 productivity
# paradox). See Tracker/PILOT_DEPLOYMENT_PLAYBOOK.md for operating model.

# Country-level KB data-density tiers. Hardcoded from institutional review,
# cross-checked against word counts of country procurement docs:
#   Argentina = 3,303 words   Colombia = 2,185 words   Venezuela = 1,751 words.
# The institutional rationale captures structural data availability (Venezuela
# has thin transactional data BY GROUND TRUTH due to OFAC sanctions + IVSS
# opacity, not because of incomplete KB curation).
COUNTRY_KB_TIERS = {
    "Argentina": {
        "tier": "HIGH",
        "color": "#2ca02c",
        "rationale": (
            "Rich regulatory and procurement data: ANMAT, PAMI, obras sociales, "
            "DNU 70/2023, CONETEC, cepo chronology. Alcaraz et al. 2024 amparo "
            "dataset (n=405) provides retrospective validation substrate."
        ),
    },
    "Colombia": {
        "tier": "HIGH",
        "color": "#2ca02c",
        "rationale": (
            "EPS-IPS structure documented, INVIMA active surveillance, MIPRES "
            "Constitutional Court ruling (COP 819B), tutela volume quantified, "
            "biosimilar adoption data available."
        ),
    },
    "Venezuela": {
        "tier": "LOW",
        "color": "#d62728",
        "rationale": (
            "Structural collapse documented (OFAC sanctions, IVSS opacity, "
            "diaspora Zelle mechanism, SIVERC). Transactional data NOT publicly "
            "available; stockout estimates rely on indirect indicators (WHO 2023 "
            "28.4% shortage rate, Convite Mar 2024, ENH Sept 2024). Predictions "
            "inherit this uncertainty — treat magnitude as indicative, direction "
            "as reliable."
        ),
    },
}

# Persistent logs (append-only)
_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "evaluation", "outputs")
PREDICT_FIRST_LOG = os.path.join(_LOG_DIR, "predict_first_log.csv")
OVERRIDE_AUDIT_LOG = os.path.join(_LOG_DIR, "override_audit_log.jsonl")


def confidence_tier(country):
    """Return the structural data-density tier for a country."""
    return COUNTRY_KB_TIERS.get(country, {
        "tier": "UNKNOWN",
        "color": "#888888",
        "rationale": "Country not in OncoSupply coverage scope.",
    })


def log_prediction(drug, country, scenario, user_est, ai_est):
    """Append one row to predict_first log. CSV (append-only, no edits)."""
    if user_est is None:
        return
    os.makedirs(_LOG_DIR, exist_ok=True)
    new_file = not os.path.exists(PREDICT_FIRST_LOG)
    with open(PREDICT_FIRST_LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["timestamp_utc", "drug", "country", "scenario",
                        "user_est_stockout_days", "ai_est_stockout_days",
                        "delta_days"])
        w.writerow([
            datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            drug, country, scenario,
            round(float(user_est), 1),
            round(float(ai_est), 1),
            round(float(ai_est) - float(user_est), 1),
        ])


def log_override(drug, country, scenario, ai_q, alt_q, reason, user_name):
    """Append-only audit log. JSONL is read-only after write (no edit UI)."""
    os.makedirs(_LOG_DIR, exist_ok=True)
    entry = {
        "timestamp_utc": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "user": (user_name or "anonymous").strip()[:80],
        "drug": drug, "country": country, "scenario": scenario,
        "ai_recommended_q": int(ai_q),
        "user_chosen_q":    int(alt_q),
        "reason": (reason or "").strip()[:500],
    }
    with open(OVERRIDE_AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def recent_overrides(n=5):
    """Read last n override entries (display-only; never returns writable handle)."""
    if not os.path.exists(OVERRIDE_AUDIT_LOG):
        return []
    with open(OVERRIDE_AUDIT_LOG, "r") as f:
        lines = f.readlines()
    out = []
    for line in lines[-n:][::-1]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out

from agent_core import run_agent
from supply_sim import (
    simulate as _simulate_raw,
    portfolio_risk_matrix,
    DRUG_PARAMS, SCENARIO_PARAMS, COUNTRY_PARAMS, RISK_COLORS, _risk_label
)


# ── Monte Carlo caching ──────────────────────────────────────────────────────
# Per-click, the app previously ran simulate() up to 5 times with overlapping
# args (Risk Brief tab, Inventory Model tab, Sim Chart distribution, Sim Chart
# scenario-comparison bar, plus the agent's internal run_simulation tool).
# Each call is 100-500 Monte Carlo runs × 365 days = expensive Python loop.
# Caching on (drug, country, scenario, n_runs, return_distribution) eliminates
# the duplicates; first call materializes the result, subsequent calls within
# the session hit the cache. TTL=1h handles edge case where user leaves browser
# open across model/code changes.
@st.cache_data(ttl=3600, show_spinner=False)
def simulate(drug, country, scenario, n_runs=500, return_distribution=False):
    """Cached wrapper around supply_sim.simulate. Identical signature."""
    return _simulate_raw(drug, country, scenario,
                         n_runs=n_runs,
                         return_distribution=return_distribution)


# ── Embedding model preload ──────────────────────────────────────────────────
# Without this, the first agent click stalls ~3 seconds while SentenceTransformer
# loads "all-MiniLM-L6-v2" (~80 MB). @st.cache_resource ensures the model is
# loaded exactly once per Streamlit worker process, on app boot, not on first
# user interaction. agent_core._get_retriever() has its own module-level cache,
# so subsequent calls within the same process are no-ops.
@st.cache_resource(show_spinner="Loading retrieval model...")
def _preload_retriever():
    from agent_core import _get_retriever
    return _get_retriever()


_preload_retriever()

ALLOWED_DRUGS     = ["cisplatin", "doxorubicin", "carboplatin", "trastuzumab"]
ALLOWED_COUNTRIES = ["Argentina", "Venezuela", "Colombia"]
ALLOWED_SCENARIOS = ["Baseline", "API export restriction",
                     "Currency devaluation", "Combined shock",
                     "Demand surge", "Regulatory squeeze",
                     "Macro/inflation shock"]

def check_refusal(drug, country):
    """Validate that drug and country are in scope. Returns error message or None."""
    if not drug or drug.lower() not in [d.lower() for d in ALLOWED_DRUGS]:
        return f"This system only covers oncology drugs in scope. '{drug}' is not available. Allowed: {', '.join(ALLOWED_DRUGS)}"
    if country not in ALLOWED_COUNTRIES:
        return f"This system only covers Argentina, Colombia, and Venezuela. '{country}' is not in scope."
    return None

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="OncoSupply Risk Analyst", layout="wide")
st.title("OncoSupply Risk Analyst")
st.caption("Oncology drug shortage risk briefs for Latin America · OncoSupply")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Parameters")
    drug     = st.selectbox("Drug",     ALLOWED_DRUGS)
    country  = st.selectbox("Country",  ALLOWED_COUNTRIES)
    scenario = st.selectbox("Scenario", ALLOWED_SCENARIOS)

    # Predict-first ritual — protects against algorithm aversion (Dietvorst 2015)
    # AND skill atrophy (M7 REVERIE finding). Optional by design: requiring it
    # creates friction; making it visible-but-optional self-selects users who
    # care about calibration.
    st.markdown("**Your prediction (optional)**")
    user_prediction = st.number_input(
        "Your own estimate of stockout days/year",
        min_value=0, max_value=365, value=None, step=1,
        help="Enter your gut estimate BEFORE generating the brief. After the brief "
             "loads, you'll see your estimate vs. the AI's side-by-side. Logged "
             "anonymously for calibration analysis. Skip if you have no prior.",
        placeholder="e.g. 30",
    )

    generate = st.button("Generate Risk Brief", type="primary")
    st.divider()
    st.caption("Model: Claude Haiku 4.5 (Sonnet judge for eval) · Simulation: (Q,r) Monte Carlo 500 runs · KB: ChromaDB all-MiniLM-L6-v2")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_brief, tab_sim, tab_inventory, tab_portfolio = st.tabs(
    ["Risk Brief", "Simulation Chart", "Inventory Model", "Portfolio Risk Matrix"]
)


# ─────────────────────────────────────────────────────────────────────────────
# Helper: simulate one (Q,r) inventory trajectory for visualization
# ─────────────────────────────────────────────────────────────────────────────
def _qr_trajectory(Q, r_pt, daily_demand, lead_time, days=365, seed=42):
    """
    Single-run (Q,r) inventory simulation under single-outstanding-order policy
    (LATAM government procurement reality). Returns inventory trajectory + events
    for plotting. Pure visualization — not the production Monte Carlo simulator.
    """
    rng = np.random.default_rng(seed)
    inv = r_pt + Q
    inv_hist, stockout_days = [], []
    pending = []   # list of (arrive_day, qty)
    place_d, arrive_d = [], []
    units_demanded = units_filled = 0
    lt_int = max(1, int(round(lead_time)))

    for day in range(days):
        # Receive any due orders
        still = []
        for (arr, qty) in pending:
            if arr <= day:
                inv += qty
                arrive_d.append(day)
            else:
                still.append((arr, qty))
        pending = still

        # Poisson demand (matches biologic) or rounded normal (generic)
        d_today = max(0, int(round(rng.poisson(max(daily_demand, 0.01)))))
        filled  = min(inv, d_today)
        inv     = max(0, inv - d_today)
        units_demanded += d_today
        units_filled   += filled
        if inv == 0:
            stockout_days.append(day)
        inv_hist.append(inv)

        # Reorder when inv hits r AND no order outstanding (real procurement constraint)
        if inv <= r_pt and len(pending) == 0:
            pending.append((day + lt_int, Q))
            place_d.append(day)

    return dict(
        inv_history   = np.array(inv_hist),
        stockout_days = stockout_days,
        place_days    = place_d,
        arrive_days   = arrive_d,
        fill_rate     = units_filled / max(units_demanded, 1) * 100,
        avg_inventory = float(np.mean(inv_hist)),
    )


def _draw_qr_panel(ax, traj, Q, r_pt, ss, lead_time, label, color_status):
    """Draw a single (Q,r) sawtooth panel into the given axis."""
    DARK = "#0e1117"
    ax.set_facecolor(DARK)
    inv_arr = traj["inv_history"]
    days_arr = np.arange(len(inv_arr))

    # Stockout shading
    for d in traj["stockout_days"]:
        ax.axvspan(d - 0.5, d + 0.5, color="#d62728", alpha=0.20, zorder=0)

    # Reference lines
    ax.axhline(r_pt, color="#ffd54f", lw=1.3, ls="--", zorder=2)
    ax.axhline(ss,   color="#81c784", lw=1.3, ls="--", zorder=2)
    ax.axhline(0,    color="#d62728", lw=0.8, ls=":",  zorder=2)

    # Inventory line
    ax.plot(days_arr, inv_arr, color="#4fc3f7", lw=1.6, zorder=3)

    # Right-margin labels
    days = len(inv_arr)
    ax.text(days + 3, r_pt, f"  r={r_pt}", va="center",
            color="#ffd54f", fontsize=8)
    ax.text(days + 3, ss,   f"  SS={ss}",   va="center",
            color="#81c784", fontsize=8)
    ax.text(days + 3, 2,    "  Zero",        va="bottom",
            color="#d62728", fontsize=7.5)

    # Q-jump labels — first 4 visible arrivals
    shown = 0
    for d in traj["arrive_days"]:
        if d < days and d > 0 and shown < 4:
            before = inv_arr[d - 1]
            after  = inv_arr[d]
            if after - before > 5:
                ax.annotate("", xy=(d, after), xytext=(d, before),
                            arrowprops=dict(arrowstyle="->", color="#a5d6a7", lw=1.4))
                ax.text(d + 1.5, (after + before) / 2, f"+{Q}",
                        color="#a5d6a7", fontsize=7.5, va="center")
                shown += 1

    # Metrics box
    so_count = len(traj["stockout_days"])
    so_pct   = so_count / days * 100
    msg = (f"Q = {Q}  |  LT = {lead_time:.0f} d\n"
           f"Stockout days: {so_count} ({so_pct:.0f}% of year)\n"
           f"Fill rate: {traj['fill_rate']:.0f}%  |  Avg inv: {traj['avg_inventory']:.0f}")
    ax.text(0.02, 0.97, msg, transform=ax.transAxes,
            va="top", ha="left", color=color_status, fontsize=8,
            bbox=dict(boxstyle="round,pad=0.35", facecolor="#1a1f2e",
                      edgecolor=color_status, alpha=0.92))

    ax.set_title(label, color="white", fontsize=10, pad=6, loc="left")
    ax.set_xlabel("Day (365-day horizon)", color="#aaa", fontsize=8)
    ax.set_ylabel("Inventory (units)", color="white", fontsize=8)
    ax.tick_params(colors="white", labelsize=8)
    for sp in ax.spines.values():
        sp.set_edgecolor("#444")
    yhi = max(r_pt + Q + 30, int(inv_arr.max()) + 20)
    ax.set_xlim(0, days + 25)
    ax.set_ylim(-10, yhi)
    ax.grid(axis="y", color="#1e1e1e", lw=0.5, zorder=0)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1: RISK BRIEF (agentic)
# ─────────────────────────────────────────────────────────────────────────────
with tab_brief:
    if generate:
        # ── Run agent + a parallel simulation pull (for predict-first comparison
        # and override Q reference). The agent will also call simulate; this is
        # additional context for the human-in-loop layer, not duplicated work
        # that affects the brief content.
        with st.spinner("Agent working — retrieving KB, running simulation..."):
            brief, trace = run_agent(drug, country, scenario)
            sim_for_ui = simulate(drug, country, scenario, n_runs=100)

        ai_stockout_days = float(sim_for_ui["stockout_days_mean"])
        ai_recommended_q = int(sim_for_ui["eoq"])

        # ── 1. Confidence-degradation badge (top, before brief)
        ct = confidence_tier(country)
        st.markdown(
            f"<div style='padding:10px 14px;border-radius:6px;background:{ct['color']}22;"
            f"border-left:5px solid {ct['color']};margin-bottom:12px;'>"
            f"<span style='color:{ct['color']};font-weight:700;font-size:1.05em;'>"
            f"Data confidence: {ct['tier']}</span><br>"
            f"<span style='font-size:0.92em;color:#ccc;'>{ct['rationale']}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # ── 2. Predict-first comparison (if user entered an estimate)
        if user_prediction is not None:
            log_prediction(drug, country, scenario, user_prediction, ai_stockout_days)
            delta = ai_stockout_days - user_prediction
            arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "=")
            c1, c2, c3 = st.columns(3)
            c1.metric("Your estimate",  f"{int(user_prediction)} d / yr")
            c2.metric("AI estimate",    f"{ai_stockout_days:.0f} d / yr",
                      delta=f"{arrow} {abs(delta):.0f} d", delta_color="off")
            agreement = ("Strong agreement" if abs(delta) <= 10 else
                         "Moderate agreement" if abs(delta) <= 30 else
                         "Significant divergence — review assumptions")
            c3.metric("Calibration",    agreement)
            st.caption(
                "Logged to `evaluation/outputs/predict_first_log.csv` for "
                "calibration analysis. Your estimate was captured *before* the "
                "AI brief was generated."
            )
            st.divider()

        with st.expander("Agent reasoning trace", expanded=True):
            st.markdown("**Tools called by the agent:**")
            for i, step in enumerate(trace, 1):
                st.markdown(f"{i}. {step}")

        st.divider()
        st.markdown(f"## {drug.title()} — {country} — {scenario}")
        st.markdown(brief)

        # ── 3. Override workflow (Moffatt v. Air Canada hedge)
        st.divider()
        with st.expander("⚠️  Disagree with this recommendation? Log an override.", expanded=False):
            st.caption(
                "Append-only audit log. If you proceed against the AI's recommendation, "
                "this captures the reason and your alternative. If a shortage occurs, "
                "the audit log protects both the institution and the AI. If you comply "
                "with the AI's recommendation, the log captures the AI's stated "
                "assumptions for the same protection. Per *Moffatt v. Air Canada* "
                "(2024 BCCRT 149)."
            )
            with st.form("override_form", clear_on_submit=True):
                user_name = st.text_input("Your name or role",
                                          placeholder="e.g. M. Rodriguez, Pharmacy Director")
                alt_q = st.number_input(
                    f"Alternative order quantity (AI recommended Q = {ai_recommended_q} units)",
                    min_value=1, max_value=10000, value=ai_recommended_q, step=1,
                )
                reason = st.text_area(
                    "Reason for override (required)",
                    placeholder="e.g. Q too aggressive given current budget constraint; "
                                "supplier confirmed faster lead time; clinical demand "
                                "expected to drop due to protocol change…",
                    max_chars=500,
                )
                submitted = st.form_submit_button("Log override")
                if submitted:
                    if not reason.strip():
                        st.error("Reason is required for audit integrity.")
                    elif alt_q == ai_recommended_q:
                        st.warning(
                            "Alternative Q matches the AI's recommendation — "
                            "no override to log. Use this form only when you intend "
                            "to procure a different quantity."
                        )
                    else:
                        entry = log_override(drug, country, scenario,
                                             ai_recommended_q, alt_q, reason, user_name)
                        st.success(
                            f"Override logged at {entry['timestamp_utc']} "
                            f"({entry['user']}: {entry['ai_recommended_q']} → "
                            f"{entry['user_chosen_q']} units)."
                        )

            # Recent overrides display
            recent = recent_overrides(5)
            if recent:
                st.markdown("**Recent overrides (last 5)**")
                for r in recent:
                    st.markdown(
                        f"- `{r['timestamp_utc']}` · {r['user']} · "
                        f"{r['drug']}/{r['country']} · "
                        f"{r['ai_recommended_q']} → {r['user_chosen_q']} units · "
                        f"*{r['reason'][:100]}{'…' if len(r['reason']) > 100 else ''}*"
                    )
    else:
        st.info("Select parameters in the sidebar and click **Generate Risk Brief**.")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2: SIMULATION CHART
# ─────────────────────────────────────────────────────────────────────────────
with tab_sim:
    st.subheader(f"Monte Carlo Stockout Distribution — {drug.title()} / {country} / {scenario}")
    st.caption("500-run (Q,r) inventory simulation. X-axis: stockout days per year. Y-axis: frequency across runs.")

    if generate:
        with st.spinner("Running 500 Monte Carlo simulations..."):
            result = simulate(drug, country, scenario, n_runs=500, return_distribution=True)
        dist = np.array(result["stockout_distribution"])
        risk = _risk_label(result["stockout_days_mean"])
        color = RISK_COLORS[risk]

        fig, axes = plt.subplots(1, 2, figsize=(12, 4))
        fig.patch.set_facecolor("#0e1117")
        for ax in axes:
            ax.set_facecolor("#1a1f2e")
            ax.tick_params(colors="white")
            ax.spines["bottom"].set_color("#444")
            ax.spines["left"].set_color("#444")
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)

        # ── Left: histogram ──────────────────────────────────────────────────
        ax = axes[0]
        ax.hist(dist, bins=40, color=color, alpha=0.85, edgecolor="none")
        ax.axvline(result["stockout_days_mean"], color="white", linestyle="--",
                   linewidth=1.5, label=f"Mean: {result['stockout_days_mean']:.1f}d")
        ax.axvline(result["cvar_90"], color="#ff7f0e", linestyle="-.",
                   linewidth=1.5, label=f"CVaR₉₀: {result['cvar_90']:.1f}d")
        ax.axvline(60, color="#aaaaaa", linestyle=":", linewidth=1,
                   label="Critical threshold (60d)")
        ax.set_xlabel("Stockout days per year", color="white")
        ax.set_ylabel("Frequency (runs)", color="white")
        ax.set_title(f"Stockout Distribution  |  Risk: {risk}", color="white", fontsize=11)
        ax.legend(framealpha=0.2, labelcolor="white", facecolor="#0e1117")

        # ── Right: KPI summary bars ──────────────────────────────────────────
        ax2 = axes[1]
        scenarios_list = list(SCENARIO_PARAMS.keys())
        means = []
        colors_list = []
        for s in scenarios_list:
            r2 = simulate(drug, country, s, n_runs=200)
            means.append(r2["stockout_days_mean"])
            colors_list.append(RISK_COLORS[_risk_label(r2["stockout_days_mean"])])

        bars = ax2.barh(scenarios_list, means, color=colors_list, alpha=0.85)
        ax2.set_xlabel("Mean stockout days / year", color="white")
        ax2.set_title(f"Scenario Comparison — {drug.title()} / {country}", color="white", fontsize=11)
        for bar, val in zip(bars, means):
            ax2.text(max(val + 0.5, 1), bar.get_y() + bar.get_height() / 2,
                     f"{val:.1f}d", va="center", color="white", fontsize=9)

        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

        # KPI metrics row
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Mean stockout days", f"{result['stockout_days_mean']:.1f} ± {result['stockout_days_ci']}")
        c2.metric("CVaR₉₀ (tail risk)", f"{result['cvar_90']:.1f}d",
                  help="Expected stockout days in worst 10% of simulations (Badejo & Ierapetritou, AIChE 2025)")
        c3.metric("Unit service level", f"{result['sl_units_mean']:.1%}")
        c4.metric("P(critical >60d)", f"{result['prob_critical_shortage']:.0%}")
        c5.metric("Risk rating", risk)
    else:
        st.info("Click **Generate Risk Brief** to run the simulation and view the distribution chart.")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3: INVENTORY MODEL — (Q, r) sawtooth visualization
# ─────────────────────────────────────────────────────────────────────────────
with tab_inventory:
    st.subheader(f"(Q, r) Inventory Model — {drug.title()} / {country} / {scenario}")
    st.caption(
        "Continuous-review (Q, r) policy under single-outstanding-order procurement "
        "(LATAM government cycle). Compares the cost-optimal EOQ against the "
        "feasibility-corrected Q. When the EOQ falls below mean lead-time demand, "
        "the cost-optimal value guarantees stockout on every cycle regardless of "
        "safety stock — the feasibility floor (d × L) is the binding constraint."
    )

    if generate:
        # Re-run simulation for current selection (cached in tab_sim's `result` var
        # would be cleaner, but Streamlit reruns the whole page on each interaction
        # so a fresh policy lookup is the safest pattern).
        with st.spinner("Loading inventory policy parameters..."):
            inv_result = simulate(drug, country, scenario, n_runs=100)

        Q_corrected   = int(inv_result["eoq"])
        Q_cost_opt    = int(inv_result["eoq_cost_optimal"])
        r_pt          = int(inv_result["reorder_point"])
        ss            = int(inv_result["safety_stock"])
        d_mean        = float(inv_result["daily_demand_mean"])
        L_mean        = float(inv_result["lead_time_mean"])
        floor_binding = bool(inv_result["q_floor_binding"])

        # ── Policy summary panel ──
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Recommended Q*", f"{Q_corrected} units",
                  help="Feasibility-corrected order quantity used in the simulation")
        c2.metric("Cost-optimal EOQ", f"{Q_cost_opt} units",
                  delta=f"{Q_corrected - Q_cost_opt:+d}" if floor_binding else "no change",
                  delta_color="off",
                  help="Raw EOQ from sqrt(2DS/H); ignores lead time and service level")
        c3.metric("Reorder point r", f"{r_pt} units",
                  help="r = d × L_mean + safety stock")
        c4.metric("Safety stock", f"{ss} units")
        c5.metric("Mean lead time", f"{L_mean:.0f} days")

        if floor_binding:
            st.warning(
                f"⚠️  **Feasibility floor binding.** The cost-optimal EOQ "
                f"({Q_cost_opt} units) is below the mean lead-time demand "
                f"({Q_corrected} units = d × L = {d_mean:.1f} × {L_mean:.0f}). "
                f"Using EOQ alone would cause guaranteed stockouts on every "
                f"order cycle. The algorithm has corrected upward to "
                f"Q = {Q_corrected} units. The cost penalty is offset by the "
                f"shortage-avoidance benefit, which the EOQ formula does not "
                f"price in."
            )
        else:
            st.success(
                f"✓ **Cost-optimal EOQ is feasibility-adequate.** "
                f"EOQ = {Q_cost_opt} units exceeds mean lead-time demand "
                f"({d_mean:.1f} × {L_mean:.0f} = {int(round(d_mean * L_mean))} units). "
                f"No correction needed; the cost-optimal policy is also operationally feasible."
            )

        # ── Trajectory simulation + plotting ──
        with st.spinner("Simulating inventory trajectories..."):
            traj_broken = _qr_trajectory(Q_cost_opt, r_pt, d_mean, L_mean, days=365, seed=7)
            traj_fixed  = _qr_trajectory(Q_corrected, r_pt, d_mean, L_mean, days=365, seed=7)

        # Two side-by-side panels
        fig, axes = plt.subplots(2, 1, figsize=(13, 8))
        fig.patch.set_facecolor("#0e1117")

        _draw_qr_panel(
            axes[0], traj_broken, Q_cost_opt, r_pt, ss, L_mean,
            label=f"BROKEN: Q = {Q_cost_opt} units (cost-optimal EOQ alone, no feasibility check)",
            color_status="#ef5350" if floor_binding else "#a5d6a7",
        )
        _draw_qr_panel(
            axes[1], traj_fixed, Q_corrected, r_pt, ss, L_mean,
            label=f"CORRECTED: Q = {Q_corrected} units (cost-optimal ∪ lead-time feasibility floor)",
            color_status="#a5d6a7",
        )

        plt.suptitle(
            f"(Q, r) Inventory Model — {drug.title()} / {country} / {scenario}",
            color="white", fontsize=12, y=1.00
        )
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

        # ── Method note ──
        with st.expander("Method & interpretation"):
            st.markdown(f"""
**Model**
- Continuous-review (Q, r) inventory policy: when on-hand inventory drops to **r**, place an order of **Q** units. Lead time **L** (mean = {L_mean:.0f} days) passes; order arrives.
- **Single-outstanding-order constraint**: at most one order in transit. Reflects LATAM government procurement cycles (IVSS in Venezuela, PAMI/obras sociales in Argentina, EPS in Colombia) where reorders cannot be stacked.

**Why two Q values?**
- **Cost-optimal EOQ** (`sqrt(2 × D × S / H)`) minimizes order + holding cost. For high-unit-cost biologics like trastuzumab, this collapses to single-digit values that cannot cover even one lead-time demand cycle.
- **Feasibility floor** (`d × L_mean` = {int(round(d_mean * L_mean))} units) is the minimum Q required to avoid guaranteed stockout under the single-order constraint. Reference: Hopp & Spearman, *Factory Physics* §2.5.
- The algorithm uses `max(EOQ, feasibility floor)` to ensure the recommended policy is both cost-aware and operationally achievable.

**Residual stockout in the corrected panel**
- If the corrected panel still shows stockout days, those are caused by **budget constraints** (`budget_multiplier` < 1, meaning the procurement officer cannot actually pay for the full Q every cycle), **fill-rate constraints** (supplier delivers < 100% of ordered units), or **demand volatility** exceeding safety stock — not by the (Q,r) policy itself.
- This is the diagnostic value of the chart: it separates *policy-design failure* (the bug we just fixed) from *structural country failure* (the real OncoSupply story).
""")

    else:
        st.info("Click **Generate Risk Brief** in the sidebar to load the inventory model for the selected drug / country / scenario.")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 4: PORTFOLIO RISK MATRIX
# ─────────────────────────────────────────────────────────────────────────────
with tab_portfolio:
    st.subheader(f"Portfolio Risk Matrix — {country}")
    st.caption(
        "All 4 drugs × 4 scenarios for the selected country. "
        "Cell = mean stockout days / year. Color = risk tier. "
        "Run: 300 simulations per cell."
    )

    run_portfolio = st.button(f"Run Portfolio Analysis for {country}", key="portfolio_btn")

    if run_portfolio:
        with st.spinner(f"Running 4 × 4 = 16 simulations for {country} (may take 20-30 seconds)..."):
            pm = portfolio_risk_matrix(country, n_runs=300)

        drugs_list     = pm["drugs"]
        scenarios_list = pm["scenarios"]
        matrix         = pm["matrix"]

        # ── Heatmap ──────────────────────────────────────────────────────────
        fig, ax = plt.subplots(figsize=(10, 4))
        fig.patch.set_facecolor("#0e1117")
        ax.set_facecolor("#0e1117")

        risk_to_num = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
        data = np.array([
            [risk_to_num[matrix[d][s]["risk"]] for s in scenarios_list]
            for d in drugs_list
        ])

        cmap = plt.cm.colors.ListedColormap(["#2ca02c", "#ffdd57", "#ff7f0e", "#d62728"])
        im = ax.imshow(data, cmap=cmap, vmin=-0.5, vmax=3.5, aspect="auto")

        ax.set_xticks(range(len(scenarios_list)))
        ax.set_xticklabels([s.replace(" ", "\n") for s in scenarios_list],
                           color="white", fontsize=9)
        ax.set_yticks(range(len(drugs_list)))
        ax.set_yticklabels([DRUG_PARAMS[d]["label"].split(" (")[0] for d in drugs_list],
                           color="white", fontsize=9)
        ax.tick_params(colors="white")
        for spine in ax.spines.values():
            spine.set_visible(False)

        # Annotate cells with stockout days
        for i, drug_name in enumerate(drugs_list):
            for j, sc in enumerate(scenarios_list):
                cell = matrix[drug_name][sc]
                ax.text(j, i,
                        f"{cell['stockout_days_mean']:.1f}d\n{cell['risk']}",
                        ha="center", va="center", color="black",
                        fontsize=8, fontweight="bold")

        patches = [
            mpatches.Patch(color="#2ca02c", label="LOW (<10d)"),
            mpatches.Patch(color="#ffdd57", label="MODERATE (10–30d)"),
            mpatches.Patch(color="#ff7f0e", label="HIGH (30–60d)"),
            mpatches.Patch(color="#d62728", label="CRITICAL (>60d)"),
        ]
        ax.legend(handles=patches, loc="upper right", bbox_to_anchor=(1.35, 1.05),
                  framealpha=0.2, labelcolor="white", facecolor="#0e1117", fontsize=8)
        ax.set_title(f"Portfolio Risk Matrix — {country}", color="white", fontsize=12, pad=10)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

        # ── Worst-case summary table ──────────────────────────────────────────
        st.markdown("**Highest-risk drug-scenario pairs:**")
        rows = []
        for d in drugs_list:
            for s in scenarios_list:
                cell = matrix[d][s]
                rows.append({
                    "Drug": DRUG_PARAMS[d]["label"].split(" (")[0],
                    "Scenario": s,
                    "Stockout days/yr": cell["stockout_days_mean"],
                    "Service level": f"{cell['sl_units_mean']:.1%}",
                    "P(critical)": f"{cell['prob_critical']:.0%}",
                    "Risk": cell["risk"],
                })
        rows.sort(key=lambda x: x["Stockout days/yr"], reverse=True)

        import pandas as pd
        df = pd.DataFrame(rows[:8])  # top 8 worst

        def color_risk(val):
            colors = {"CRITICAL": "background-color: #d62728; color: black",
                      "HIGH": "background-color: #ff7f0e; color: black",
                      "MODERATE": "background-color: #ffdd57; color: black",
                      "LOW": "background-color: #2ca02c; color: black"}
            return colors.get(val, "")

        st.dataframe(df.style.applymap(color_risk, subset=["Risk"]),
                     use_container_width=True, hide_index=True)
    else:
        st.info("Click **Run Portfolio Analysis** to see all drugs × scenarios for this country.")
