import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common.pdf_report import generate_generator_pdf_report
from common.concepts import render_theory_tab
from common.sld import generator_zone_svg
from common.ui_helpers import slider_with_exact_input
from common.settings_advisor import mismatch_ratio_pct, suggest_bias_settings
from common.project_state import with_restored_preset, get_restorable_preset, record_equipment_settings
from common.historian import render_historian_overlay
from common.relay_settings_sheet import render_settings_sheet
from engines.generator import AdvancedDifferentialRelay

st.title("Enterprise Generator Differential Protection (87G) Suite")
st.caption("Active Phase Vector Analysis, GE G60 Dual-Breakpoint Curve Engine & Secondary Injection Testing")

st.markdown("### Generator Relay Type Select")
mode_selection = st.radio(
    "Choose Relay Implementation:",
    ["GE G60", "GE CFD22B4A"],
    horizontal=True
)

# Convert selection to internal mode
if mode_selection == "GE CFD22B4A":
    current_mode = "GENERATOR_LEGACY"
else:
    current_mode = "GENERATOR"

PRESETS = {
    "GENERATOR": {
        "POMI Unit 7 & 8 - 846 MVA": {"mva": 846.231, "kv": 23.0, "ct_n": 24000, "ct_t": 24000, "pickup": 0.06, "s1": 20, "break_1": 1.15, "s2": 80, "break_2": 8.00},
        "Custom Profile": {"mva": 10.0, "kv": 11.0, "ct_n": 100, "ct_t": 100, "pickup": 0.1, "s1": 20, "break_1": 1.15, "s2": 60, "break_2": 6.00},
    },
    "GENERATOR_LEGACY": {
        "POMI Unit 7 - 846 MVA": {"mva": 846.231, "kv": 23.0, "ct_n": 24000, "ct_t": 24000, "target_amps": 0.2, "s1": 10},
        "Custom Profile": {"mva": 10.0, "kv": 11.0, "ct_n": 100, "ct_t": 100, "target_amps": 0.2, "s1": 10},
    },
}

current_mode_presets = PRESETS[current_mode]
_restored_generator = get_restorable_preset("generator")
if _restored_generator is not None and _restored_generator.get("mode") == current_mode:
    # Only offer the restored preset for the mode it was actually saved under -
    # GENERATOR and GENERATOR_LEGACY presets have different shapes (pickup/slopes/
    # breaks vs. target_amps), so injecting it under the wrong mode would break
    # the p_data["..."] lookups every other preset here already relies on.
    current_mode_presets = with_restored_preset(current_mode_presets, "generator")
st.sidebar.header("Equipment Presets")
selected_preset = st.sidebar.selectbox(
    "Load Standard Profile", list(current_mode_presets.keys()),
    help="Pick a built-in POMI relay, or Custom Profile to enter your own equipment's ratings, "
         "CT specs, and protection settings — this app isn't limited to POMI equipment."
)
p_data = current_mode_presets[selected_preset]
is_custom = selected_preset == "Custom Profile"

st.sidebar.header("Protection Characteristic")
target_amps = None
i_unrestrained_value = None

if current_mode == "GENERATOR_LEGACY":
    target_amps = slider_with_exact_input(
        st.sidebar, "Target / Seal-in Pickup (Secondary Amps)", 0.1, 1.0, p_data["target_amps"], 0.05,
        key=f"{current_mode}__{selected_preset}__target_amps",
        help_text="Factory default is 0.2 A. Per GEK-34124E, it is NOT recommended to set below "
                   "0.1 A, and the rear contact may need up to ~0.25 A to close — verify the actual "
                   "closing current during commissioning."
    )
    slope_1 = slider_with_exact_input(
        st.sidebar, "Restraint Slope (%)", 5, 30, p_data["s1"], 1,
        key=f"{current_mode}__{selected_preset}__slope1",
        help_text="Confirmed by GEK-34124E's Principles of Operation: this relay balances when "
                   "the differential current is 10% of the SMALLER of the two terminal currents, "
                   "up to approximately rated current. This is fixed by the relay's internal "
                   "design, not a field setting — the slider exists here only to explore 'what if' "
                   "sensitivity; leave at 10% to match the actual hardware."
    )
    i_pickup = 0.0
    slope_2 = slope_1
    break_1, break_2 = 1e6, 1e6

else:
    i_pickup = slider_with_exact_input(
        st.sidebar, "Pickup (pu)", 0.05, 1.00, p_data["pickup"], 0.01,
        key=f"{current_mode}__{selected_preset}__pickup",
        help_text="G60 manual range: 0.050 to 1.00 pu, step 0.01"
    )
    slope_1 = slider_with_exact_input(
        st.sidebar, "Slope 1 (%)", 1, 100, p_data["s1"], 1,
        key=f"{current_mode}__{selected_preset}__slope1",
        help_text="G60 manual range: 1 to 100%, step 1"
    )
    break_1 = slider_with_exact_input(
        st.sidebar, "Break 1 (pu)", 1.00, 1.50, p_data["break_1"], 0.01,
        key=f"{current_mode}__{selected_preset}__break1",
        help_text="G60 manual range: 1.00 to 1.50 pu, step 0.01. Restraint stays flat at Pickup below this point."
    )
    slope_2 = slider_with_exact_input(
        st.sidebar, "Slope 2 (%)", 1, 100, p_data["s2"], 1,
        key=f"{current_mode}__{selected_preset}__slope2",
        help_text="G60 manual range: 1 to 100%, step 1"
    )
    break_2 = slider_with_exact_input(
        st.sidebar, "Break 2 (pu)", 1.50, 30.00, p_data["break_2"], 0.01,
        key=f"{current_mode}__{selected_preset}__break2",
        help_text="G60 manual range: 1.50 to 30.00 pu, step 0.01. Slope 2 applies above this point."
    )

    enable_unrestrained = st.sidebar.checkbox(
        "Enable Unrestrained High-Set Element",
        value=False,
        help="Only enable this if your G60 manual confirms a separate unrestrained/high-set "
             "differential element with its own pickup setting. Left unconfirmed by default."
    )
    if enable_unrestrained:
        i_unrestrained_value = slider_with_exact_input(
            st.sidebar, "Unrestrained High-Set Pickup (pu)", 3.0, 30.0, 8.0, 0.5,
            key=f"{current_mode}__{selected_preset}__unrestrained"
        )

with st.sidebar.expander("Advanced Settings (CT Spec & Wiring)", expanded=False):
    st.markdown("**Generator & CT Spec**")
    mva = st.number_input("Generator Rating (MVA)", value=p_data["mva"], step=10.0, key=f"{current_mode}__{selected_preset}__mva")
    kv = st.number_input("Rated Voltage (kV)", value=p_data["kv"], step=1.0, key=f"{current_mode}__{selected_preset}__kv")
    ct_ratio_N = st.number_input("Neutral Side CT Rating (Primary A, e.g. 20000 in '20000:5')", value=float(p_data["ct_n"]), key=f"{current_mode}__{selected_preset}__ct_n")
    ct_ratio_T = st.number_input("Terminal Side CT Rating (Primary A)", value=float(p_data["ct_t"]), key=f"{current_mode}__{selected_preset}__ct_t")

    ct_secondary_rating = st.selectbox(
        "CT Secondary Rating (A)", [1.0, 5.0], index=1, key=f"{current_mode}__{selected_preset}__ct_sec",
        help="The rated secondary current stamped on the CT nameplate (e.g. the '5' in '2000:5'). "
             "This is applied to both CTs and determines the true turns ratio used in all "
             "per-unit scaling — entering only the primary rating without this was a labelling bug."
    )
    st.caption(
        f"Effective ratio → Neutral: **{ct_ratio_N:.0f} : {ct_secondary_rating:.0f}** "
        f"(= {ct_ratio_N/ct_secondary_rating:.1f}:1)  |  "
        f"Terminal: **{ct_ratio_T:.0f} : {ct_secondary_rating:.0f}** "
        f"(= {ct_ratio_T/ct_secondary_rating:.1f}:1)"
    )

    st.markdown("**Wiring & Convention**")
    col_conv, col_pol = st.columns(2)
    with col_conv:
        convention = st.radio("Restraint Standard", ["IEEE", "IEC"], help="IEEE: Average current. IEC: Arithmetic sum.")
    with col_pol:
        def _on_polarity_change():
            # Keep each phase's Terminal Side angle box in sync with the newly selected
            # polarity, instead of leaving it at whatever value was set under the
            # previously selected polarity — otherwise switching this radio silently
            # pairs stale angle values with a different vec_op formula (+ vs -), which
            # looks like the SAME/OPPOSITE results have "swapped".
            new_polarity = st.session_state["ct_polarity_widget"]
            for _idx, _phase in enumerate(["Phase A", "Phase B", "Phase C"]):
                _def_ang_N = -120.0 * _idx
                # vec_op = vec_T - vec_N for OPPOSITE (needs matching angles to cancel),
                # vec_op = vec_T + vec_N for SAME (needs 180 deg apart to cancel).
                _def_ang_T = _def_ang_N if new_polarity == "OPPOSITE" else _def_ang_N + 180.0
                st.session_state[f"T_a_{_phase}"] = _def_ang_T

        ct_polarity = st.radio(
            "Polarity Reference", ["OPPOSITE", "SAME"], index=1,
            key="ct_polarity_widget", on_change=_on_polarity_change,
            help="OPPOSITE: standard facing inwards. SAME: facing identical directions."
        )

with st.sidebar.expander("🧮 Settings Calculator (from ratings)", expanded=False):
    st.caption(
        "Derives a starting point FROM the ratings above, the same direction the settings docs' own "
        "worked examples work in — CT-matching is exact math; Bias/Pickup/HOC are rule-of-thumb "
        "starting points that still need engineering review."
    )
    i_rated_sec_N_calc = (mva * 1000.0 / (1.7320508 * kv)) / (ct_ratio_N / ct_secondary_rating) if kv > 0 and ct_ratio_N > 0 else 0.0
    i_rated_sec_T_calc = (mva * 1000.0 / (1.7320508 * kv)) / (ct_ratio_T / ct_secondary_rating) if kv > 0 and ct_ratio_T > 0 else 0.0
    calc_mismatch = mismatch_ratio_pct([i_rated_sec_N_calc, i_rated_sec_T_calc])
    cc1, cc2 = st.columns(2)
    cc1.metric("Neutral CT secondary A @ rated", f"{i_rated_sec_N_calc:.3f} A")
    cc2.metric("Terminal CT secondary A @ rated", f"{i_rated_sec_T_calc:.3f} A")
    st.metric("CT mismatch between sides", f"{calc_mismatch:.2f}%" if calc_mismatch is not None else "—",
              help="Unlike the tap-matching transformer relays, this relay has no CT-matching tap — "
                   "the two sides' CT ratios should be chosen equal in the first place. A nonzero "
                   "mismatch here just means the Neutral and Terminal CT ratios you entered aren't "
                   "identical; recheck them if this isn't intentional.")
    suggestion = suggest_bias_settings(calc_mismatch or 0.0, num_windings=2)
    st.markdown(
        f"**Suggested starting point:** Pickup/Min Operate ≈ **{suggestion['min_operate_pct']:.0f}%**, "
        f"Bias/Slope 1 ≈ **{suggestion['bias_pct']:.0f}%**, unrestrained HOC ≈ **{suggestion['hoc_multiple']:.0f}x** tap current."
    )
    st.caption(suggestion["basis"])

_generator_project_settings = {"mva": mva, "kv": kv, "ct_n": ct_ratio_N, "ct_t": ct_ratio_T, "mode": current_mode, "calc_mismatch_pct": calc_mismatch}
if current_mode == "GENERATOR_LEGACY":
    _generator_project_settings.update({"target_amps": target_amps, "s1": slope_1})
else:
    _generator_project_settings.update({"pickup": i_pickup, "s1": slope_1, "break_1": break_1, "s2": slope_2, "break_2": break_2})
record_equipment_settings("generator", _generator_project_settings)

relay = AdvancedDifferentialRelay(
    mode=current_mode, mva_rated=mva, kv_rated=kv,
    ct_ratio_N=ct_ratio_N, ct_ratio_T=ct_ratio_T, ct_secondary_rating=ct_secondary_rating,
    i_pickup=i_pickup, slope_1=slope_1, slope_2=slope_2,
    break_1=break_1, break_2=break_2,
    i_unrestrained=i_unrestrained_value,
    convention=convention, ct_polarity=ct_polarity,
    target_amps=target_amps
)

tab_theory, tab1, tab2, tab3 = st.tabs([
    "Theory", "Live Vector Simulation",
    "Commissioning & Injection Tool", "Test Point Verification & Curve"
])

with tab_theory:
    render_theory_tab(
        "generator",
        purpose_text=(
            "The 87G relay exists to detect and instantly clear electrical faults occurring "
            "inside the generator's own stator winding — between the neutral-end CT and the "
            "terminal-end CT. This zone is uniquely dangerous because the generator continues to "
            "feed a fault with its own excitation current even after the main breaker and grid-"
            "side devices open; only tripping the field breaker and stopping the prime mover "
            "actually removes the fault's energy source. A stator winding fault left uncleared "
            "for even a fraction of a second can cause severe, expensive iron and copper damage, "
            "so 87G is set to be as fast and as sensitive as possible within its own zone."
        ),
        sld_image_name="generator.png",
        sld_fallback_svg=generator_zone_svg(relay, ct_polarity, tag="87G"),
    )

with tab1:
    col_inputs, col_results = st.columns([1.2, 1.0])

    with col_inputs:
        st.subheader("Primary (Generator) Operating Phase Inputs")
        st.caption(
            "Enter the actual PRIMARY-side current in Amps (e.g. generator load current or "
            "fault current at the machine terminals) — the app converts this through the CT "
            "ratio and rated base automatically. You do not need to divide by the CT ratio "
            "yourself. For the actual 0–5 A (or 0–1 A) secondary current you'd inject into "
            "the physical relay during testing, see the Commissioning & Injection Tool tab."
        )

        st.info(f"Generator Nominal Rated Current: **{relay.i_rated_pri:.1f} A**")

        phases = ["Phase A", "Phase B", "Phase C"]

        n_side_label, t_side_label = "Neutral Side (End 1)", "Terminal Side (End 2)"
        inputs = {}

        for idx, phase in enumerate(phases):
            with st.expander(f"{phase} Settings", expanded=(phase == "Phase A")):
                c1, c2 = st.columns(2)

                def_val = relay.i_rated_pri if phase == "Phase A" else 0.0
                def_ang_N = -120.0 * idx
                # vec_op = vec_T - vec_N for OPPOSITE (needs matching angles to cancel),
                # vec_op = vec_T + vec_N for SAME (needs 180 deg apart to cancel) - see
                # engines/generator.py's evaluate_protection().
                def_ang_T = def_ang_N if ct_polarity == "OPPOSITE" else def_ang_N + 180.0

                with c1:
                    i_N = st.number_input(f"{n_side_label} Primary Amps [A]", value=def_val, key=f"N_i_{phase}")
                    a_N = st.number_input(f"{n_side_label} Angle (°)", value=def_ang_N, key=f"N_a_{phase}")
                with c2:
                    i_T = st.number_input(f"{t_side_label} Primary Amps [A]", value=def_val, key=f"T_i_{phase}")
                    a_T = st.number_input(f"{t_side_label} Angle (°)", value=def_ang_T, key=f"T_a_{phase}")

                inputs[phase] = {"i_N": i_N, "a_N": a_N, "i_T": i_T, "a_T": a_T}

        evals = {p: relay.evaluate_protection(
            inputs[p]["i_N"], inputs[p]["a_N"],
            inputs[p]["i_T"], inputs[p]["a_T"]
        ) for p in phases}

    with col_results:
        st.subheader("Real-time Protection Verdict")

        any_trip = any(res["is_trip"] for res in evals.values())
        if any_trip:
            st.error("PROTECTIVE RELAY TRIP INITIATED!")
        else:
            st.success("SYSTEM HEALTHY (Stability / Restraint Zone)")

        table_rows = []
        for p in phases:
            e = evals[p]
            table_rows.append({
                "Phase": p,
                "I_op [pu]": f"{e['i_op_pu']:.3f}",
                "I_rest [pu]": f"{e['i_rest_pu']:.3f}",
                "Threshold [pu]": f"{e['i_threshold_pu']:.3f}",
                "Action Verdict": e["status"]
            })
        st.table(table_rows)

        pdf_bytes = generate_generator_pdf_report(selected_preset, relay, evals, phases, inputs=inputs)
        st.download_button(
            label="Export Certified Protection Audit Report",
            data=pdf_bytes,
            file_name=f"Generator_Differential_Protection_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf"
        )

        if current_mode == "GENERATOR_LEGACY":
            _sheet_rows = [
                ("Relay Type", "GE CFD22B4A (GEK-34124)"),
                ("Target/Seal-in Pickup (A sec.)", f"{target_amps:.2f}" if target_amps is not None else "N/A"),
                ("Restraint Slope (%)", f"{slope_1:.0f}"),
            ]
        else:
            _sheet_rows = [
                ("Relay Type", "GE G60 (Numerical)"),
                ("Pickup (pu)", f"{i_pickup:.3f}"),
                ("Slope 1 (%)", f"{slope_1:.0f}"),
                ("Break 1 (pu)", f"{break_1:.2f}"),
                ("Slope 2 (%)", f"{slope_2:.0f}"),
                ("Break 2 (pu)", f"{break_2:.2f}"),
                ("Unrestrained High-Set (pu)", f"{i_unrestrained_value:.2f}" if i_unrestrained_value is not None else "Not enabled"),
            ]
        _sheet_rows += [
            ("Neutral CT Ratio", f"{ct_ratio_N:.0f}:{ct_secondary_rating:.0f}"),
            ("Terminal CT Ratio", f"{ct_ratio_T:.0f}:{ct_secondary_rating:.0f}"),
            ("Restraint Standard", convention),
            ("CT Polarity Reference", ct_polarity),
        ]
        render_settings_sheet(st, "GE G60" if current_mode == "GENERATOR" else "GE CFD22B4A", _sheet_rows, key_prefix="Generator")


    st.subheader("Differential Slope Characteristic Curve")

    chart_units = st.radio(
        "Chart units", ["Per-Unit (pu)", "Secondary Amps (A)"], horizontal=True,
        help="Secondary Amps matches how commissioning test reports are usually plotted "
             "(e.g. GEK-34124 Figure 7). Conversion uses the Neutral-side rated secondary "
             "current as the base — accurate as long as both CTs share the same ratio, "
             "which they do for this unit (24000:5 on both sides)."
    )
    use_amps = chart_units == "Secondary Amps (A)"
    amps_base = relay.i_rated_sec_N

    has_unrestrained_element = relay.i_unrestrained < 1e5
    extra_range = (relay.break_2 + 1.0) if current_mode == "GENERATOR" else 0.0
    max_x_val = max(6.0, max(e["i_rest_pu"] for e in evals.values()) + 1.5, extra_range)
    x_axis_line = np.linspace(0, max_x_val, 400)
    y_axis_line = [relay.calculate_trip_threshold(x) for x in x_axis_line]

    x_plot = x_axis_line * amps_base if use_amps else x_axis_line
    y_plot = np.array(y_axis_line) * amps_base if use_amps else np.array(y_axis_line)
    unit_label = "A" if use_amps else "pu"

    y_upper_pu = max(relay.i_unrestrained + 2.0, max(y_axis_line) + 1.0) if has_unrestrained_element else max(y_axis_line) + 1.0
    y_upper = y_upper_pu * amps_base if use_amps else y_upper_pu
    x_upper = max_x_val * amps_base if use_amps else max_x_val

    fig = go.Figure()

    # Shaded Restraint Region (below the trip line, safe) and Operating Region
    # (above it, trips) - the fill follows the CAL. line's actual shape exactly.
    fig.add_trace(go.Scatter(
        x=x_plot, y=np.zeros_like(x_plot), mode='lines',
        line=dict(width=0), showlegend=False, hoverinfo='skip'
    ))
    fig.add_trace(go.Scatter(
        x=x_plot, y=y_plot, mode='lines', name='CAL.',
        line=dict(color='#2563EB', width=3),
        fill='tonexty', fillcolor='rgba(22,163,74,0.10)'
    ))
    fig.add_trace(go.Scatter(
        x=x_plot, y=np.full_like(x_plot, y_upper), mode='lines',
        line=dict(width=0), fill='tonexty', fillcolor='rgba(220,38,38,0.08)',
        showlegend=False, hoverinfo='skip'
    ))
    fig.add_annotation(
        text="OPERATING REGION (TRIP)", xref="paper", yref="paper", x=0.98, y=0.95,
        showarrow=False, font=dict(size=13, color="#B91C1C"), xanchor="right", yanchor="top",
        bgcolor="rgba(255,255,255,0.75)"
    )
    fig.add_annotation(
        text="RESTRAINT REGION (SAFE)", xref="paper", yref="paper", x=0.02, y=0.05,
        showarrow=False, font=dict(size=13, color="#15803D"), xanchor="left", yanchor="bottom",
        bgcolor="rgba(255,255,255,0.75)"
    )

    if has_unrestrained_element:
        hs_val = relay.i_unrestrained * amps_base if use_amps else relay.i_unrestrained
        fig.add_trace(go.Scatter(
            x=[0, max_x_val * amps_base if use_amps else max_x_val], y=[hs_val, hs_val],
            mode='lines', name='Unrestrained High-Set',
            line=dict(color='#DC2626', width=2, dash='dash')
        ))

    phase_colors = {"Phase A": "red", "Phase B": "green", "Phase C": "blue"}
    for p in phases:
        e = evals[p]
        px = e["i_rest_pu"] * amps_base if use_amps else e["i_rest_pu"]
        py = e["i_op_pu"] * amps_base if use_amps else e["i_op_pu"]
        fig.add_trace(go.Scatter(
            x=[px], y=[py],
            mode='markers+text', name=f"{p}",
            text=[f"{p}"], textposition="top center",
            marker=dict(size=14, color=phase_colors[p], symbol='x' if e["is_trip"] else 'circle'),
            hovertemplate=f"<b>{p}</b><br>I_rest: %{{x:.3f}} {unit_label}<br>I_op: %{{y:.3f}} {unit_label}<br>State: {e['status']}<extra></extra>"
        ))

    fig.update_layout(
        title="Differential Slope Characteristic Curve",
        xaxis_title=f"Restraint Current I_rest ({unit_label})",
        yaxis_title=f"Differential/Operating Current I_op ({unit_label})",
        xaxis=dict(range=[0, x_upper]),
        yaxis=dict(range=[0, y_upper]),
        template="plotly_white",
        height=500
    )

    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        f"Curve shape: {'GE G60 dual-breakpoint' if relay.mode == 'GENERATOR' else 'CFD22B4A single-slope'} "
        f"characteristic ({relay.mode})."
    )


with tab2:
    st.subheader("Commissioning & Secondary Current Injection Assistant")
    st.write(
        "Pick a target restraint current for each phase to calculate the exact secondary "
        "Amps to inject at your test set for that phase — this is your test plan, telling "
        "you what to dial in before you inject."
    )

    n_inj_label, t_inj_label = "Neutral Side", "Terminal Side"
    default_restraints = {"Phase A": 0.5, "Phase B": 2.5, "Phase C": 5.0}

    st.markdown("#### Boundary Injection Calculator")
    phase_test_points = {}
    cols = st.columns(3)
    for p, col in zip(phases, cols):
        with col:
            st.markdown(f"**{p}**")
            r_val = slider_with_exact_input(
                st, f"{p} Target Restraint (pu)", 0.1, 30.0, default_restraints[p], 0.1,
                key=f"{current_mode}__{selected_preset}__commtest__{p}"
            )
            boundary_op = relay.calculate_trip_threshold(r_val)
            sec_N = (r_val + boundary_op / 2.0) * relay.i_rated_sec_N
            sec_T = (r_val - boundary_op / 2.0) * relay.i_rated_sec_T
            phase_test_points[p] = {"i_rest_pu": r_val, "i_op_pu": boundary_op, "sec_N": sec_N, "sec_T": sec_T}
            st.metric("Boundary I_op", f"{boundary_op:.3f} pu")
            st.caption(f"{n_inj_label} inject: **{sec_N:.3f} A**")
            st.caption(f"{t_inj_label} inject: **{sec_T:.3f} A**")

    st.markdown("---")
    st.subheader("Auto-Sweep Full Curve Test Table")
    st.write(
        "Generates a full table of boundary test points across the restraint range in one go, "
        "instead of testing one point at a time — useful for a complete commissioning verification."
    )

    sw1, sw2, sw3 = st.columns(3)
    with sw1:
        sweep_start = st.number_input("Sweep Start (pu)", value=0.2, min_value=0.0, step=0.1)
    with sw2:
        if current_mode == "GENERATOR":
            default_end = float(relay.break_2) + 2.0
        else:
            default_end = float(relay.i_unrestrained) if relay.i_unrestrained < 1e5 else 6.0
        sweep_end = st.number_input("Sweep End (pu)", value=max(6.0, default_end), step=0.5)
    with sw3:
        sweep_step = st.number_input("Sweep Step (pu)", value=0.5, min_value=0.1, step=0.1)

    if st.button("Generate Sweep Table"):
        if sweep_end <= sweep_start or sweep_step <= 0:
            st.error("Sweep End must be greater than Sweep Start, and Sweep Step must be positive.")
        else:
            sweep_points = np.arange(sweep_start, sweep_end + sweep_step / 2.0, sweep_step)
            sweep_rows = []
            for i_rest in sweep_points:
                boundary_op = relay.calculate_trip_threshold(i_rest)
                sec_n = (i_rest + boundary_op / 2.0) * relay.i_rated_sec_N
                sec_t = (i_rest - boundary_op / 2.0) * relay.i_rated_sec_T
                sweep_rows.append({
                    "I_rest (pu)": round(float(i_rest), 3),
                    "Boundary I_op (pu)": round(boundary_op, 3),
                    "Neutral Injection I_N (A)": round(sec_n, 3),
                    "Terminal Injection I_T (A)": round(sec_t, 3),
                })
            st.session_state["sweep_df"] = pd.DataFrame(sweep_rows)

    if "sweep_df" in st.session_state:
        st.dataframe(st.session_state["sweep_df"], use_container_width=True)
        csv_sweep = st.session_state["sweep_df"].to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Sweep Table as CSV",
            data=csv_sweep,
            file_name=f"87G_Sweep_Test_Table_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )


with tab3:
    st.subheader("Test Point Verification & Curve")
    st.write(
        "Enter measured test results and see them plotted against the calculated "
        "characteristic curve, all in one place."
    )
    st.markdown("#### Add Test Points (Actual Measured Results)")
    st.caption(
        "Enter the restraint and differential currents actually read off your test set's "
        "ammeters during injection testing — each one you add is plotted on the curve "
        "below, so you can see how real results compare to the calculated CAL. line. "
        "Pick whichever unit matches your test set's readout; values are stored and "
        "converted consistently either way."
    )

    if "manual_test_points" not in st.session_state:
        st.session_state.manual_test_points = []

    with st.form("add_test_point_form", clear_on_submit=True):
        tp_unit = st.radio(
            "Entry units", ["Secondary Amps (A)", "Per-Unit (pu)"], horizontal=True,
            key="tp_entry_unit",
            help="pu is converted to Amps using the Neutral-side rated secondary current "
                 "(same base used everywhere else in this app) before it's stored."
        )
        tc1, tc2, tc3, tc4 = st.columns([1, 1, 1, 1.4])
        restraint_label = "Restraint Current" if tp_unit.startswith("Secondary") else "Restraint Current (pu)"
        diff_label = "Measured Diff. Current" if tp_unit.startswith("Secondary") else "Measured Diff. Current (pu)"
        restraint_step = 0.1 if tp_unit.startswith("Secondary") else 0.05
        diff_step = 0.05 if tp_unit.startswith("Secondary") else 0.01
        restraint_default = 1.0 if tp_unit.startswith("Secondary") else 0.3
        diff_default = 0.3 if tp_unit.startswith("Secondary") else 0.06
        with tc1:
            tp_phase = st.selectbox("Phase", ["Phase A", "Phase B", "Phase C", "Other"])
        with tc2:
            tp_restraint = st.number_input(restraint_label, min_value=0.0, value=restraint_default, step=restraint_step)
        with tc3:
            tp_diff = st.number_input(diff_label, min_value=0.0, value=diff_default, step=diff_step)
        with tc4:
            tp_label = st.text_input("Label (optional)", value="")
        submitted = st.form_submit_button("Add Test Point")
        if submitted:
            if tp_unit.startswith("Secondary"):
                restraint_amps = tp_restraint
                diff_amps = tp_diff
            else:
                restraint_amps = tp_restraint * amps_base
                diff_amps = tp_diff * amps_base
            st.session_state.manual_test_points.append({
                "Phase": tp_phase,
                "Restraint (A)": round(restraint_amps, 3),
                "Measured Diff (A)": round(diff_amps, 3),
                "Label": tp_label
            })

    if st.session_state.manual_test_points:
        table_unit = st.radio(
            "Display units for table", ["Secondary Amps (A)", "Per-Unit (pu)"], horizontal=True,
            key="tp_table_unit",
            help="Points are always stored consistently in Secondary Amps internally, but you "
                 "can view this table in whichever unit you prefer — the values convert either way."
        )
        table_in_pu = table_unit.startswith("Per-Unit")
        restraint_col = "Restraint (pu)" if table_in_pu else "Restraint (A)"
        diff_col = "Measured Diff (pu)" if table_in_pu else "Measured Diff (A)"

        tp_display_rows = []
        for tp in st.session_state.manual_test_points:
            r_amps = tp["Restraint (A)"]
            d_amps = tp["Measured Diff (A)"]
            tp_display_rows.append({
                "Phase": tp["Phase"],
                restraint_col: round(r_amps / amps_base, 3) if table_in_pu else round(r_amps, 3),
                diff_col: round(d_amps / amps_base, 3) if table_in_pu else round(d_amps, 3),
                "Label": tp["Label"]
            })
        tp_df = pd.DataFrame(tp_display_rows)
        st.dataframe(tp_df, use_container_width=True)

        rc1, rc2 = st.columns(2)
        with rc1:
            remove_idx = st.number_input(
                "Row # to remove (0-indexed)", min_value=0,
                max_value=max(len(st.session_state.manual_test_points) - 1, 0),
                value=0, step=1
            )
            if st.button("Remove Row"):
                st.session_state.manual_test_points.pop(int(remove_idx))
                st.rerun()
        with rc2:
            if st.button("Clear All Test Points"):
                st.session_state.manual_test_points = []
                st.rerun()
    else:
        st.info("No test points added yet — add some above to see them plotted below.")

    st.markdown("---")
    st.markdown("#### Differential Slope Characteristic Curve")

    comm_chart_units = st.radio(
        "Chart units", ["Per-Unit (pu)", "Secondary Amps (A)"], horizontal=True,
        key="comm_chart_units",
        help="Secondary Amps matches how commissioning test reports are usually plotted "
             "(e.g. GEK-34124 Figure 7). Conversion uses the Neutral-side rated secondary "
             "current as the base — accurate as long as both CTs share the same ratio, "
             "which they do for this unit (24000:5 on both sides)."
    )
    use_amps_comm = comm_chart_units == "Secondary Amps (A)"
    unit_label_comm = "A" if use_amps_comm else "pu"

    cal_source = st.radio(
        "CAL. line source",
        ["Connect my test points (commissioning report style)", "Theoretical relay characteristic"],
        horizontal=True,
        key="cal_line_source",
        help="'Connect my test points' draws a straight line through your entered test points "
             "sorted by restraint current, exactly like the CAL. line in a commissioning test "
             "report. 'Theoretical' plots the smooth curve from the relay's Pickup/Slope/Break "
             "settings instead."
    )

    sweep_fig = go.Figure()

    if cal_source.startswith("Connect") and len(st.session_state.manual_test_points) >= 2:
        sorted_pts = sorted(st.session_state.manual_test_points, key=lambda tp: tp["Restraint (A)"])
        cal_x_amps = [tp["Restraint (A)"] for tp in sorted_pts]
        cal_y_amps = [tp["Measured Diff (A)"] for tp in sorted_pts]
        curve_x = cal_x_amps if use_amps_comm else [x / amps_base for x in cal_x_amps]
        curve_y = cal_y_amps if use_amps_comm else [y / amps_base for y in cal_y_amps]
        sweep_fig.add_trace(go.Scatter(
            x=curve_x, y=curve_y, mode="lines", name="CAL.",
            line=dict(color="#2E8B57", width=3)
        ))
    else:
        if cal_source.startswith("Connect"):
            st.info("Add at least 2 test points above to draw the CAL. line through them — showing the theoretical characteristic for now.")
        manual_restraints_pu = [tp["Restraint (A)"] / amps_base for tp in st.session_state.manual_test_points]
        default_reach = (relay.break_2 + 2.0) if current_mode == "GENERATOR" else 6.0
        max_restraint = max(manual_restraints_pu + [default_reach]) if manual_restraints_pu else default_reach

        curve_x_pu = np.linspace(0, max_restraint * 1.2 + 0.5, 300)
        curve_y_pu = [relay.calculate_trip_threshold(x) for x in curve_x_pu]
        curve_x = curve_x_pu * amps_base if use_amps_comm else curve_x_pu
        curve_y = np.array(curve_y_pu) * amps_base if use_amps_comm else np.array(curve_y_pu)

        # Shaded Restraint/Operating regions - only meaningful for the theoretical
        # curve (a straight line through test points isn't the real characteristic).
        sweep_fig.add_trace(go.Scatter(
            x=curve_x, y=np.zeros_like(curve_x), mode='lines',
            line=dict(width=0), showlegend=False, hoverinfo='skip'
        ))
        sweep_fig.add_trace(go.Scatter(
            x=curve_x, y=curve_y, mode="lines", name="CAL.",
            line=dict(color="#2E8B57", width=3),
            fill='tonexty', fillcolor='rgba(22,163,74,0.10)'
        ))
        sweep_fig.add_trace(go.Scatter(
            x=curve_x, y=np.full_like(curve_x, max(curve_y) * 1.15 + 0.1), mode='lines',
            line=dict(width=0), fill='tonexty', fillcolor='rgba(220,38,38,0.08)',
            showlegend=False, hoverinfo='skip'
        ))

    sweep_fig.add_annotation(
        text="OPERATING REGION (TRIP)", xref="paper", yref="paper", x=0.98, y=0.95,
        showarrow=False, font=dict(size=12, color="#B91C1C"), xanchor="right", yanchor="top",
        bgcolor="rgba(255,255,255,0.75)"
    )
    sweep_fig.add_annotation(
        text="RESTRAINT REGION (SAFE)", xref="paper", yref="paper", x=0.02, y=0.05,
        showarrow=False, font=dict(size=12, color="#15803D"), xanchor="left", yanchor="bottom",
        bgcolor="rgba(255,255,255,0.75)"
    )

    tp_marker_colors = {"Phase A": "#D63384", "Phase B": "#6C757D", "Phase C": "#1E3A8A", "Other": "#F59E0B"}
    tp_marker_symbols = {"Phase A": "square", "Phase B": "triangle-up", "Phase C": "square", "Other": "diamond"}

    for tp in st.session_state.manual_test_points:
        r_amps = tp["Restraint (A)"]
        d_amps = tp["Measured Diff (A)"]
        px = r_amps if use_amps_comm else r_amps / amps_base
        py = d_amps if use_amps_comm else d_amps / amps_base
        trace_name = tp["Phase"] + (f' ({tp["Label"]})' if tp["Label"] else "")
        sweep_fig.add_trace(go.Scatter(
            x=[px], y=[py], mode="markers", name=trace_name,
            marker=dict(size=13, color=tp_marker_colors.get(tp["Phase"], "#F59E0B"),
                        symbol=tp_marker_symbols.get(tp["Phase"], "diamond")),
            hovertemplate=f"<b>{tp['Phase']}</b><br>Restraint: %{{x:.3f}} {unit_label_comm}<br>Measured Diff: %{{y:.3f}} {unit_label_comm}<extra></extra>"
        ))

    sweep_fig.update_layout(
        title="Differential Slope Characteristic Curve",
        xaxis_title=f"Restraint Current ({unit_label_comm})",
        yaxis_title=f"Diff. Current ({unit_label_comm})",
        template="plotly_white",
        height=450
    )

    png_filename = f"87G_Differential_Slope_Curve_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}"
    st.plotly_chart(
        sweep_fig, use_container_width=True,
        config={"toImageButtonOptions": {"format": "png", "filename": png_filename, "scale": 3}}
    )
    st.caption(
        "To save this chart as an image: hover over the top-right of the chart and "
        "click the camera icon — it downloads a PNG directly from your browser, no extra "
        "software needed."
    )

    st.markdown("---")
    render_historian_overlay(st, "generator", reference_lines=[
        ("Generator Rated (A)", relay.i_rated_pri),
    ])
