import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common.pdf_report import generate_generator_pdf_report
from common.concepts import render_theory_tab
from common.sld import generator_zone_svg
from common.ui_helpers import slider_with_exact_input, fault_term_info
from common.settings_advisor import mismatch_ratio_pct, suggest_bias_settings
from common.project_state import with_restored_preset, get_restorable_preset, record_equipment_settings
from common.historian import render_historian_overlay
from common.relay_settings_sheet import render_settings_sheet
from engines.generator import AdvancedDifferentialRelay
from engines.fault_current import three_phase_fault_current, relay_secondary_at_fault

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
        "POMI Unit 7 & 8 - 846 MVA": {
            "mva": 846.231, "kv": 23.0, "ct_n": 24000, "ct_t": 24000, "pickup": 0.06, "s1": 20, "break_1": 1.15, "s2": 80, "break_2": 8.00,
            # Fault current analysis basis - Generator Diff setting.pdf Section 5.1.1
            # Calculation/Discussion: X1G=0.155pu, 1.73x asymmetry, 186kA grid-fed
            # through-fault via GSUT, 84A CT/relay secondary withstand limit.
            "x1_pu": 0.155, "asym_factor": 1.73, "external_fault_ka": 186.0, "ct_withstand_a": 84.0,
        },
        "Custom Profile": {
            "mva": 10.0, "kv": 11.0, "ct_n": 100, "ct_t": 100, "pickup": 0.1, "s1": 20, "break_1": 1.15, "s2": 60, "break_2": 6.00,
            "x1_pu": 0.15, "asym_factor": 1.73, "external_fault_ka": 0.0, "ct_withstand_a": 40.0,
        },
    },
    "GENERATOR_LEGACY": {
        "POMI Unit 7 - 846 MVA": {
            "mva": 846.231, "kv": 23.0, "ct_n": 24000, "ct_t": 24000, "target_amps": 0.2, "s1": 10,
            "x1_pu": 0.155, "asym_factor": 1.73, "external_fault_ka": 186.0, "ct_withstand_a": 84.0,
        },
        "Custom Profile": {
            "mva": 10.0, "kv": 11.0, "ct_n": 100, "ct_t": 100, "target_amps": 0.2, "s1": 10,
            "x1_pu": 0.15, "asym_factor": 1.73, "external_fault_ka": 0.0, "ct_withstand_a": 40.0,
        },
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

# ---------------------------------------------------------------------------
# CURRENT SETTINGS — every applied setting, editable in place, with a live
# comment on whether an adjustment improves or weakens protection. Comments
# reuse the exact same functions as the old sidebar "Settings Calculator" (no
# new engineering judgment invented) - just surfaced inline per-field.
# ---------------------------------------------------------------------------
outer_settings, outer_analysis = st.tabs(["Current Settings", "Analysis & Tools"])
with outer_settings:
    # Live preview of the differential characteristic curve, right at the top so its shape is
    # visible immediately without switching to Analysis & Tools. Reads straight from
    # session_state (falling back to the preset default) since the actual settings widgets are
    # drawn further down this same tab and haven't run yet on this script pass - this preview
    # reflects whatever was set on the PREVIOUS interaction, and updates on the next rerun same
    # as everything else on the page. Deliberately theoretical only (no operating points, no
    # unrestrained high-set line) - the full picture with live test inputs is still the Live
    # Vector Simulation tab in Analysis & Tools.
    _pv_key = f"{current_mode}__{selected_preset}__"
    _pv_mva = st.session_state.get(_pv_key + "mva", p_data["mva"])
    _pv_kv = st.session_state.get(_pv_key + "kv", p_data["kv"])
    _pv_ct_n = st.session_state.get(_pv_key + "ct_n", p_data["ct_n"])
    _pv_ct_t = st.session_state.get(_pv_key + "ct_t", p_data["ct_t"])
    _pv_ct_sec = st.session_state.get(_pv_key + "ct_sec", 5.0)
    if current_mode == "GENERATOR_LEGACY":
        _pv_relay = AdvancedDifferentialRelay(
            mode=current_mode, mva_rated=_pv_mva, kv_rated=_pv_kv,
            ct_ratio_N=_pv_ct_n, ct_ratio_T=_pv_ct_t, ct_secondary_rating=_pv_ct_sec,
            slope_1=st.session_state.get(_pv_key + "slope1", p_data["s1"]),
            target_amps=st.session_state.get(_pv_key + "target_amps", p_data["target_amps"]),
        )
        _pv_max_x = 6.0
    else:
        _pv_break_2 = st.session_state.get(_pv_key + "break2", p_data["break_2"])
        _pv_relay = AdvancedDifferentialRelay(
            mode=current_mode, mva_rated=_pv_mva, kv_rated=_pv_kv,
            ct_ratio_N=_pv_ct_n, ct_ratio_T=_pv_ct_t, ct_secondary_rating=_pv_ct_sec,
            i_pickup=st.session_state.get(_pv_key + "pickup", p_data["pickup"]),
            slope_1=st.session_state.get(_pv_key + "slope1", p_data["s1"]),
            slope_2=st.session_state.get(_pv_key + "slope2", p_data["s2"]),
            break_1=st.session_state.get(_pv_key + "break1", p_data["break_1"]),
            break_2=_pv_break_2,
        )
        _pv_max_x = max(6.0, _pv_break_2 + 1.0)
    st.markdown("#### Live Preview — Differential Characteristic Curve")
    st.caption(
        "Reflects the settings below as you adjust them. Operating-point testing and the "
        "unrestrained high-set line (if enabled) are in the Live Vector Simulation tab under "
        "Analysis & Tools."
    )
    _pv_x = np.linspace(0, _pv_max_x, 200)
    _pv_y = [_pv_relay.calculate_trip_threshold(x) for x in _pv_x]
    _pv_fig = go.Figure()
    _pv_fig.add_trace(go.Scatter(x=_pv_x, y=_pv_y, mode="lines", name="CAL.", line=dict(color="#2563EB", width=3)))
    _pv_fig.update_layout(
        xaxis_title="Restraint Current (pu)", yaxis_title="Differential/Operating Current (pu)",
        template="plotly_white", height=320, margin=dict(t=20, b=40),
    )
    st.plotly_chart(_pv_fig, use_container_width=True, key="generator_settings_preview_fig")
    st.markdown("---")

    st.markdown("## Current Settings")
    st.caption("Every setting currently applied to this relay. Adjust a value below and the comment beside it updates live.")

    with st.container(border=True):
        st.markdown("**Ratings and CT**")
        r1c1, r1c2 = st.columns(2)
        with r1c1:
            mva = st.number_input("Generator Rating (MVA)", value=p_data["mva"], step=10.0, key=f"{current_mode}__{selected_preset}__mva")
            kv = st.number_input("Rated Voltage (kV)", value=p_data["kv"], step=1.0, key=f"{current_mode}__{selected_preset}__kv")
        with r1c2:
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
        i_rated_sec_N_calc = (mva * 1000.0 / (1.7320508 * kv)) / (ct_ratio_N / ct_secondary_rating) if kv > 0 and ct_ratio_N > 0 else 0.0
        i_rated_sec_T_calc = (mva * 1000.0 / (1.7320508 * kv)) / (ct_ratio_T / ct_secondary_rating) if kv > 0 and ct_ratio_T > 0 else 0.0
        calc_mismatch = mismatch_ratio_pct([i_rated_sec_N_calc, i_rated_sec_T_calc])
        st.metric("CT mismatch between sides", f"{calc_mismatch:.2f}%" if calc_mismatch is not None else "—")
        if calc_mismatch is not None:
            if calc_mismatch < 0.5:
                st.success("Neutral and Terminal CT ratios match — as expected (this relay has no CT-matching tap to absorb a mismatch, unlike the transformer relays).")
            else:
                st.warning(f"{calc_mismatch:.2f}% mismatch — this relay has no CT-matching tap, so the Neutral and Terminal CT ratios should normally be identical. Recheck the ratios above unless this is intentional.")

    suggestion = suggest_bias_settings(calc_mismatch or 0.0, num_windings=2)

    with st.container(border=True):
        st.markdown("**Protection Characteristic**")
        target_amps = None
        i_unrestrained_value = None

        if current_mode == "GENERATOR_LEGACY":
            p1c1, p1c2 = st.columns(2)
            with p1c1:
                target_amps = slider_with_exact_input(
                    st, "Target / Seal-in Pickup (Secondary Amps)", 0.1, 1.0, p_data["target_amps"], 0.05,
                    key=f"{current_mode}__{selected_preset}__target_amps",
                    help_text="Factory default is 0.2 A. Per GEK-34124E, it is NOT recommended to set below "
                               "0.1 A, and the rear contact may need up to ~0.25 A to close — verify the actual "
                               "closing current during commissioning."
                )
                if target_amps < 0.1:
                    st.warning("Below GEK-34124E's recommended 0.1A floor — the manual advises against this.")
                elif target_amps < 0.25:
                    st.info("Within range, but the rear contact may need up to ~0.25A to close — verify the actual closing current during commissioning.")
                else:
                    st.success("Clears GEK-34124E's recommended floor and the ~0.25A closing-current guidance.")
            with p1c2:
                slope_1 = slider_with_exact_input(
                    st, "Restraint Slope (%)", 5, 30, p_data["s1"], 1,
                    key=f"{current_mode}__{selected_preset}__slope1",
                    help_text="Confirmed by GEK-34124E's Principles of Operation: this relay balances when "
                               "the differential current is 10% of the SMALLER of the two terminal currents, "
                               "up to approximately rated current. This is fixed by the relay's internal "
                               "design, not a field setting — the slider exists here only to explore 'what if' "
                               "sensitivity; leave at 10% to match the actual hardware."
                )
                st.caption("Fixed by the relay's internal design, not a tunable field setting — no improve/worsen comment applies here.")
            i_pickup = 0.0
            slope_2 = slope_1
            break_1, break_2 = 1e6, 1e6

        else:
            p1c1, p1c2 = st.columns(2)
            with p1c1:
                i_pickup = slider_with_exact_input(
                    st, "Pickup (pu)", 0.05, 1.00, p_data["pickup"], 0.01,
                    key=f"{current_mode}__{selected_preset}__pickup",
                    help_text="G60 manual range: 0.050 to 1.00 pu, step 0.01"
                )
                # Unlike the transformer relays, generator differential pickup is conventionally set
                # LOW (5-10% typical) since a healthy generator zone has no equivalent to a
                # transformer's inherent tap/turns-ratio mismatch to guard against - the 20%-floor
                # heuristic used elsewhere doesn't apply here, so this is informational, not a
                # pass/fail check, unless the CT ratios above are actually mismatched.
                if calc_mismatch is not None and calc_mismatch >= 0.5 and i_pickup * 100 < suggestion["min_operate_pct"]:
                    st.warning(f"CT ratios above are mismatched ({calc_mismatch:.2f}%) and Pickup is below the {suggestion['min_operate_pct']:.0f}% floor that would compensate for it — raises the risk of a nuisance trip.")
                else:
                    st.info("Lower = more sensitive to small internal faults, but more exposed to CT/relay noise at light load. Generator differential pickup is conventionally set low (5-10% typical) since there's no CT mismatch to guard against when the ratios above match.")
                slope_1 = slider_with_exact_input(
                    st, "Slope 1 (%)", 1, 100, p_data["s1"], 1,
                    key=f"{current_mode}__{selected_preset}__slope1",
                    help_text="G60 manual range: 1 to 100%, step 1"
                )
                if calc_mismatch is not None and calc_mismatch >= 0.5 and slope_1 < suggestion["bias_pct"]:
                    st.warning(f"CT ratios above are mismatched ({calc_mismatch:.2f}%) and Slope 1 is below the {suggestion['bias_pct']:.0f}% floor that would compensate for it — raises the risk of a nuisance trip.")
                else:
                    st.info("Higher = more secure against nuisance trips, but less sensitive to small internal faults.")
            with p1c2:
                break_1 = slider_with_exact_input(
                    st, "Break 1 (pu)", 1.00, 1.50, p_data["break_1"], 0.01,
                    key=f"{current_mode}__{selected_preset}__break1",
                    help_text="G60 manual range: 1.00 to 1.50 pu, step 0.01. Restraint stays flat at Pickup below this point."
                )
                slope_2 = slider_with_exact_input(
                    st, "Slope 2 (%)", 1, 100, p_data["s2"], 1,
                    key=f"{current_mode}__{selected_preset}__slope2",
                    help_text="G60 manual range: 1 to 100%, step 1"
                )
                break_2 = slider_with_exact_input(
                    st, "Break 2 (pu)", 1.50, 30.00, p_data["break_2"], 0.01,
                    key=f"{current_mode}__{selected_preset}__break2",
                    help_text="G60 manual range: 1.50 to 30.00 pu, step 0.01. Slope 2 applies above this point."
                )
                st.caption("Break points/Slope 2 shape the curve above rated current — a through-fault/inrush coordination study is needed to tune these, not a rule-of-thumb check.")

            enable_unrestrained = st.checkbox(
                "Enable Unrestrained High-Set Element",
                value=False,
                help="Only enable this if your G60 manual confirms a separate unrestrained/high-set "
                     "differential element with its own pickup setting. Left unconfirmed by default."
            )
            if enable_unrestrained:
                i_unrestrained_value = slider_with_exact_input(
                    st, "Unrestrained High-Set Pickup (pu)", 3.0, 30.0, 8.0, 0.5,
                    key=f"{current_mode}__{selected_preset}__unrestrained"
                )
                # This element's presence isn't confirmed against the real G60 settings (see the
                # checkbox help text above), so there's no documented value to check against -
                # informational only, not a pass/fail claim.
                st.caption("Higher = more secure against inrush/CT saturation misoperation, but needs a larger internal fault to trip instantaneously. Confirm this element and its setting against the actual G60 configuration before relying on it.")

    with st.container(border=True):
        st.markdown("**Wiring & Convention**")
        st.caption("Must match the actual field CT wiring — not a tunable protection margin, so no improve/worsen comment applies here.")
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

    if current_mode == "GENERATOR_LEGACY":
        all_clear = calc_mismatch is not None and calc_mismatch < 0.5 and target_amps >= 0.1
    else:
        # Pickup/Slope 1 only count against "all clear" if the CT ratios are actually mismatched -
        # a low pickup is normal/desired for a generator differential with matched CTs, see the
        # comment next to those fields above.
        all_clear = calc_mismatch is not None and calc_mismatch < 0.5
        if calc_mismatch is not None and calc_mismatch >= 0.5:
            all_clear = all_clear and i_pickup * 100 >= suggestion["min_operate_pct"] and slope_1 >= suggestion["bias_pct"]
    if calc_mismatch is None:
        st.info("Overall status: enter the CT ratios above to compute a status.")
    elif all_clear:
        st.success("Overall status: all settings shown clear their recommended margins. Engineering approval is still required before issue.")
    else:
        st.warning("Overall status: one or more settings above need review before this is applied.")

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

with outer_analysis:
    st.caption("Everything below reads the settings from the Current Settings tab — adjust them there, then explore the effect here.")

    tab_theory, tab1, tab2, tab3, tab_fault = st.tabs([
        "Theory", "Live Vector Simulation",
        "Commissioning & Injection Tool", "Test Point Verification & Curve",
        "Fault Current Analysis",
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

    # ---------------------------------------------------------------------------
    # TAB — Fault Current Analysis
    # ---------------------------------------------------------------------------
    with tab_fault:
        st.subheader("Fault Current Analysis")
        st.write(
            "Checks the 87G CTs against the maximum current they'll actually see for a real fault, "
            "using the same method as the settings document's own worked example — not just the "
            "relay's own characteristic curve in isolation."
        )
        st.caption(
            "This uses only the generator's own positive-sequence reactance (a simple Thevenin "
            "source at 1.0pu voltage) - it is NOT a full short-circuit study (no network reduction, "
            "no negative/zero-sequence networks, no other in-feeds). The external through-fault "
            "figure below is a reference value from the plant's own fault study, not independently "
            "computed by this app."
        )

        fc1, fc2 = st.columns(2)
        with fc1:
            st.markdown("**Generator's own contribution to an internal fault**")
            x1_pu = st.number_input(
                "Positive Sequence Reactance, X1G (pu)", min_value=0.01, value=p_data.get("x1_pu", 0.155), step=0.005, format="%.3f",
                key=f"{current_mode}__{selected_preset}__x1_pu",
                help="Subtransient/transient reactance of the generator, on its own MVA base — from the machine's own datasheet."
            )
            asym_factor = st.number_input(
                "Asymmetry Factor", min_value=1.0, max_value=2.0, value=p_data.get("asym_factor", 1.73), step=0.01,
                key=f"{current_mode}__{selected_preset}__asym_factor",
                help="Multiplier for the worst-case DC-offset fault current, assuming the fault occurs at a voltage zero-crossing (1.73x is the settings doc's own assumption)."
            )
            fault_calc = three_phase_fault_current(mva, kv, x1_pu, asym_factor)
            sm1, sm2 = st.columns([3, 1])
            with sm1:
                st.metric("Symmetrical Fault Current", f"{fault_calc['i_fault_sym_amps']:,.0f} A ({fault_calc['i_fault_pu']:.2f} pu)")
            with sm2:
                fault_term_info("symmetrical", "Symmetrical")
            am1, am2 = st.columns([3, 1])
            with am1:
                st.metric("Asymmetrical Fault Current (worst case)", f"{fault_calc['i_fault_asym_amps']:,.0f} A")
            with am2:
                fault_term_info("asymmetrical", "Asymmetrical")
            relay_sec_internal = relay_secondary_at_fault(fault_calc["i_fault_asym_amps"], ct_ratio_T, ct_secondary_rating)
            st.metric("Relay Secondary Current at Max Fault", f"{relay_sec_internal:.1f} A")

        with fc2:
            tm1, tm2 = st.columns([3, 1])
            with tm1:
                st.markdown("**External (through-fault) contribution from upstream**")
            with tm2:
                fault_term_info("through", "Through-Fault")
            external_fault_ka = st.number_input(
                "Maximum Through-Fault Current (kA primary)", min_value=0.0, value=p_data.get("external_fault_ka", 0.0), step=1.0,
                key=f"{current_mode}__{selected_preset}__ext_fault",
                help="Maximum fault current that can be fed INTO this zone from elsewhere in the system (e.g. from the grid, through the step-up transformer, for a fault on the far side) - from the plant's own fault study, not computed by this app."
            )
            relay_sec_external = relay_secondary_at_fault(external_fault_ka * 1000.0, ct_ratio_T, ct_secondary_rating) if external_fault_ka > 0 else None
            if relay_sec_external is not None:
                st.metric("Relay Secondary Current at Max Through-Fault", f"{relay_sec_external:.1f} A")
            else:
                st.caption("Enter a through-fault current above to check it — left at 0 for a Custom Profile until you supply your own system's value.")

        st.markdown("---")
        ct_withstand_a = st.number_input(
            "CT / Relay Secondary Current Withstand Limit (A)", min_value=1.0, value=p_data.get("ct_withstand_a", 84.0), step=1.0,
            key=f"{current_mode}__{selected_preset}__ct_withstand",
            help="The maximum secondary current the CT and relay input circuit can carry without excessive voltage/saturation, per the relay manufacturer's burden calculation (84A per this generator's own settings doc)."
        )
        if relay_sec_internal <= ct_withstand_a:
            st.success(f"Internal-fault relay secondary current ({relay_sec_internal:.1f} A) is within the {ct_withstand_a:.0f} A withstand limit.")
        else:
            st.warning(f"Internal-fault relay secondary current ({relay_sec_internal:.1f} A) EXCEEDS the {ct_withstand_a:.0f} A withstand limit — review CT ratio or relay burden.")
        if relay_sec_external is not None:
            if relay_sec_external <= ct_withstand_a:
                st.success(f"External through-fault relay secondary current ({relay_sec_external:.1f} A) is within the {ct_withstand_a:.0f} A withstand limit.")
            else:
                st.warning(f"External through-fault relay secondary current ({relay_sec_external:.1f} A) EXCEEDS the {ct_withstand_a:.0f} A withstand limit — review CT ratio or relay burden.")

        st.markdown("---")
        st.markdown("#### Fault Clearing Time Simulation")
        st.caption(
            "Feeds the fault current above through the same trip logic as the Live Vector Simulation "
            "tab, then adds typical relay and breaker operating times to show how long fault current "
            "actually flows before the breaker interrupts it. Relay/breaker times below are typical "
            "values for this class of equipment (not confirmed against this generator's own relay and "
            "breaker manuals) — adjust them if better data is available."
        )

        fault_scenario = st.radio(
            "Fault Scenario",
            ["Internal Fault (within 87G zone)", "External Through-Fault"],
            key=f"{current_mode}__{selected_preset}__fault_sim_scenario",
            horizontal=True,
            help=(
                "Internal: fault current is fed almost entirely from the generator's own neutral "
                "side, with little/no current reaching the terminal CT — a large, easily-detected "
                "mismatch. External: the same current passes through both CTs in the zone, so a "
                "healthy 87G should NOT operate — it's outside this differential zone's job to "
                "clear it."
            ),
        )

        fc_t1, fc_t2 = st.columns(2)
        with fc_t1:
            relay_operate_cycles = st.number_input(
                "Relay Operate Time (cycles)", min_value=0.25, max_value=10.0, value=1.5, step=0.25,
                key=f"{current_mode}__{selected_preset}__relay_op_cycles",
                help="Time from fault inception to the relay issuing a trip signal. Microprocessor differential relays of this class are typically under 2 cycles — not a figure confirmed against this relay's own manual."
            )
        with fc_t2:
            breaker_cycles = st.number_input(
                "Breaker Interrupting Time (cycles)", min_value=1.0, max_value=15.0, value=5.0, step=0.5,
                key=f"{current_mode}__{selected_preset}__breaker_cycles",
                help="Time from trip coil energization to fault current interruption — typical generator/main breakers are 3-5 cycles. Not confirmed against this plant's own breaker nameplate."
            )

        cycle_ms = 1000.0 / 60.0
        preload_ms = 40.0
        preload_current = relay.i_rated_pri

        sim_eval = None
        sim_current_primary = 0.0
        if fault_scenario.startswith("Internal"):
            sim_eval = relay.evaluate_protection(fault_calc["i_fault_asym_amps"], 0.0, 0.0, 0.0)
            sim_current_primary = fault_calc["i_fault_asym_amps"]
        elif external_fault_ka > 0:
            thru_amps = external_fault_ka * 1000.0
            ang_T = 0.0
            ang_N = ang_T if ct_polarity == "OPPOSITE" else ang_T + 180.0
            sim_eval = relay.evaluate_protection(thru_amps, ang_N, thru_amps, ang_T)
            sim_current_primary = thru_amps
        else:
            st.info("Enter a Maximum Through-Fault Current above (it's currently 0) to run this scenario.")

        if sim_eval is not None:
            fig_sim = go.Figure()
            if sim_eval["is_trip"]:
                total_ms = relay_operate_cycles * cycle_ms + breaker_cycles * cycle_ms
                t = [-preload_ms, 0, 0, total_ms, total_ms, total_ms + 40.0]
                i = [preload_current, preload_current, sim_current_primary, sim_current_primary, 0.0, 0.0]

                sc1, sc2 = st.columns(2)
                with sc1:
                    st.metric("Relay Trip Decision", sim_eval["status"])
                with sc2:
                    st.metric("Total Clearing Time", f"{total_ms:.0f} ms ({total_ms / cycle_ms:.1f} cycles)")

                fig_sim.add_trace(go.Scatter(x=t, y=i, mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current"))
                fig_sim.add_vline(x=relay_operate_cycles * cycle_ms, line=dict(color="#F59E0B", width=1.5, dash="dot"), annotation_text="Relay Trips")
                fig_sim.add_vline(x=total_ms, line=dict(color="#16A34A", width=1.5, dash="dash"), annotation_text="Breaker Clears")
            else:
                total_window_ms = 200.0
                t = [-preload_ms, 0, 0, total_window_ms]
                i = [preload_current, preload_current, sim_current_primary, sim_current_primary]

                st.metric("Relay Trip Decision", sim_eval["status"])
                if fault_scenario.startswith("External"):
                    st.info(
                        "87G correctly stays SECURE for this through-fault — current keeps flowing "
                        "through the zone. Clearing it is the job of protection outside 87G's zone "
                        "(upstream/downstream backup relays), which isn't modeled on this page."
                    )
                else:
                    st.warning("This fault current doesn't exceed the relay's trip threshold at the settings above — no clearing to simulate.")

                fig_sim.add_trace(go.Scatter(x=t, y=i, mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current"))

            fig_sim.update_layout(
                xaxis_title="Time (ms, t=0 is fault inception)", yaxis_title="Primary Current (A)",
                template="plotly_white", height=340, margin=dict(t=20, b=40),
            )
            st.plotly_chart(fig_sim, use_container_width=True, key=f"{current_mode}__{selected_preset}__fault_sim_fig")
