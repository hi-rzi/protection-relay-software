import datetime
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common.pdf_report import generate_transformer_pdf_report
from common.concepts import render_theory_tab
from common.sld import two_winding_transformer_zone_svg
from common.ui_helpers import slider_with_exact_input, MR_CT_TAPS_3000_5, fault_term_info
from engines.fault_current import transformer_through_fault_current, relay_secondary_at_fault
from common.settings_advisor import suggest_ct_matching_tap, mismatch_ratio_pct, suggest_bias_settings
from common.project_state import with_restored_preset, record_equipment_settings
from common.historian import render_historian_overlay
from common.relay_settings_sheet import render_settings_sheet
from common.profile_io import export_profile_button, restore_profile_uploader
from common.test_point_input import TEST_POINT_SOURCE_OPTIONS, TEST_POINT_SOURCE_HELP, raw_current_inputs
from engines.transformer import TransformerDifferentialRelay, winding_internal_vector, raw_input_for_internal_vector, solve_healthy_target_angle

st.title("Unit Auxiliary Transformer (UAT) Differential Protection")
st.caption(
    "60/80/100/112MVA, 23kV Delta / 13.8kV Resistance-Grounded Wye — CAC1-10-M3 "
    "percentage-bias differential relay (Mitsubishi, 2-winding)."
)

# ---------------------------------------------------------------------------
# Presets — from Transformer_Diff_Setting_-_UAT.pdf, Section 5.3.1
# (Relays 87AT7 / 87AT8, Setting Summary + Calculation/Discussion)
# ---------------------------------------------------------------------------
PRESETS = {
    "POMI UAT 87AT7/87AT8 - 112 MVA": {
        "mva": 112.0,
        "kv_hv": 22.425, "kv_lv": 13.8,  # HV calc uses Tap Position 3 (22.425kV), not the 23kV nameplate
        "ct_hv": 3000, "ct_lv": 4000, "ct_sec": 5.0,
        "ct_conn_hv": "WYE", "ct_conn_lv": "DELTA",
        "tap_hv": 1.02, "tap_lv": 0.48,
        "bias": 20, "min_operate": 20, "hoc": 5,
        # Through-fault basis - now confirmed against the UAT's own settings document
        # (Mitsubishi CAC1-10-M3, Instruction Book L9036 Ref. 4.27): Design Impedance 8.5%,
        # Minimum Impedance 8.47% and X/R=38.9 (both Appendix A). Uses the MINIMUM impedance
        # (not the design/nameplate value) paired with Appendix A's own X/R, since a lower
        # impedance gives the worst-case (higher) maximum through-fault current - the figure
        # this tab is meant to check CTs against. Impedance base uses the transformer's OA
        # (self-cooled, lowest) rating of 60MVA, per "60/80/100/112MVA OA/FA/FA/FA" - the
        # convention nameplate impedance is stated on, matching EXCT's and GSUT's own pages.
        "fault_mva_base": 60.0, "z_pct": 8.47, "x_over_r": 38.9, "ct_withstand_a": 60.0,
        "fault_kv_hv": 23.0,  # actual HV nameplate voltage - NOT the 22.425kV tap-adjusted kv_hv above
    },
    "Custom Profile": {
        "mva": 10.0,
        "kv_hv": 11.0, "kv_lv": 0.4,
        "ct_hv": 100, "ct_lv": 100, "ct_sec": 5.0,
        "ct_conn_hv": "WYE", "ct_conn_lv": "WYE",
        "tap_hv": 1.0, "tap_lv": 1.0,
        "bias": 25, "min_operate": 20, "hoc": 8,
        "fault_mva_base": 10.0, "z_pct": 8.0, "x_over_r": 15.0, "ct_withstand_a": 40.0,
        "fault_kv_hv": 11.0,
    },
}

PRESETS_WITH_PROJECT = with_restored_preset(PRESETS, "aux")
st.sidebar.header("Equipment Presets")
selected_preset = st.sidebar.selectbox(
    "Load Standard Profile", list(PRESETS_WITH_PROJECT.keys()),
    help="Pick a built-in POMI relay, or Custom Profile to enter your own equipment's ratings, "
         "CT specs, and protection settings — this app isn't limited to POMI equipment."
)
p_data = PRESETS_WITH_PROJECT[selected_preset]
is_custom = selected_preset == "Custom Profile"

if st.sidebar.button(
    "↺ Reset to preset defaults", key=f"{selected_preset}__reset_btn",
    help="Revert every Current Settings field below back to the selected preset's stock values.",
):
    # Every field's widget key is namespaced f"{selected_preset}__...", including
    # slider_with_exact_input's paired __slider/__number sub-keys - so deleting
    # everything under that prefix is enough to make every widget fall back to
    # its value=p_data[...] default on the next draw, without needing to know
    # each field's name individually.
    _reset_prefix = f"{selected_preset}__"
    for _k in [k for k in st.session_state.keys() if k.startswith(_reset_prefix)]:
        del st.session_state[_k]
    st.toast(f"Reset to {selected_preset} defaults.")
    st.rerun()

restore_profile_uploader(st.sidebar, "aux", f"{selected_preset}__", "aux")

if not is_custom:
    st.success(
        "✓ **Data confidence:** Differential settings (Bias/Min Operate/HOC/CT ratios/taps) and "
        "the Fault Current Analysis basis (Minimum Impedance 8.47%, X/R 38.9, both from Appendix A) "
        "are all verified against Transformer Diff Setting - UAT.pdf and this relay's instruction "
        "book (Mitsubishi CAC1-10-M3, L9036)."
    )

# ---------------------------------------------------------------------------
# CURRENT SETTINGS — every applied setting, editable in place, with a live
# comment on whether an adjustment improves or weakens protection. Comments
# reuse the exact same functions as the old sidebar "Settings Calculator" (no
# new engineering judgment invented) - just surfaced inline per-field. Taps
# are shown against their individual T_E only as a reference (informational),
# not a pass/fail check - same reasoning as EXCT/GSUT/Overall: taps are
# chosen JOINTLY to minimize the actual HV/LV mismatch, not to each
# independently match their own T_E, so the mismatch metric is the real signal.
# ---------------------------------------------------------------------------
outer_settings, outer_analysis = st.tabs(["Current Settings", "Analysis & Tools"])
with outer_settings:
    # Live preview, click to reveal, at the top of the tab. Reads straight from session_state
    # (falling back to the preset default) since the actual settings widgets are drawn further
    # down this same tab and haven't run yet on this script pass. The curve only depends on
    # Bias/Minimum Operate (see engines/transformer.py's calculate_trip_threshold) - CT ratios
    # and taps don't affect its shape, so no relay object is needed here at all.
    _pv_bias = st.session_state.get(f"{selected_preset}__bias", p_data["bias"]) / 100.0
    _pv_min_op = st.session_state.get(f"{selected_preset}__min_operate", p_data["min_operate"]) / 100.0
    if st.button(
        "📊 Show Live Preview — Differential Bias Characteristic Curve",
        key=f"{selected_preset}__show_preview_btn",
        help="Reflects the Bias/Minimum Operate settings below as you adjust them. The HOC line and operating-point testing are in the Simulate & Test tab under Analysis & Tools.",
    ):
        st.session_state[f"{selected_preset}__preview_shown"] = True
    if st.session_state.get(f"{selected_preset}__preview_shown", False):
        _pv_max_x = 6.0
        _pv_x = np.linspace(0, _pv_max_x, 200)
        _pv_y = [max(_pv_min_op, _pv_bias * x) for x in _pv_x]
        _pv_y_upper = max(_pv_y) * 1.3 + 0.1
        _pv_fig = go.Figure()
        _pv_fig.add_trace(go.Scatter(
            x=_pv_x, y=np.zeros_like(_pv_x), mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip",
        ))
        _pv_fig.add_trace(go.Scatter(
            x=_pv_x, y=_pv_y, mode="lines", name="CAL.", line=dict(color="#2563EB", width=3),
            fill="tonexty", fillcolor="rgba(22,163,74,0.10)",
        ))
        _pv_fig.add_trace(go.Scatter(
            x=_pv_x, y=np.full_like(_pv_x, _pv_y_upper), mode="lines", line=dict(width=0),
            fill="tonexty", fillcolor="rgba(220,38,38,0.08)", showlegend=False, hoverinfo="skip",
        ))
        _pv_fig.add_annotation(
            text="OPERATING REGION (TRIP)", xref="paper", yref="paper", x=0.98, y=0.95,
            showarrow=False, font=dict(size=12, color="#B91C1C"), xanchor="right", yanchor="top",
            bgcolor="rgba(255,255,255,0.75)",
        )
        _pv_fig.add_annotation(
            text="RESTRAINT REGION (SAFE)", xref="paper", yref="paper", x=0.02, y=0.05,
            showarrow=False, font=dict(size=12, color="#15803D"), xanchor="left", yanchor="bottom",
            bgcolor="rgba(255,255,255,0.75)",
        )
        _pv_fig.update_layout(
            xaxis_title="Restraint Current (pu)", yaxis_title="Differential/Operating Current (pu)",
            template="plotly_white", height=320, margin=dict(t=20, b=40),
        )
        st.plotly_chart(_pv_fig, use_container_width=True, key="aux_settings_preview_fig")
    st.markdown("---")

    st.markdown("## Current Settings")
    st.caption("Every setting currently applied to this relay. Adjust a value below and the comment beside it updates live.")

    with st.container(border=True):
        st.markdown("**Ratings and CT**")
        r1c1, r1c2 = st.columns(2)
        with r1c1:
            mva = st.number_input("Transformer Rating (MVA)", value=p_data["mva"], step=1.0, format="%.3f", key=f"{selected_preset}__mva")
            kv_hv = st.number_input("HV Rated Voltage (kV)", value=p_data["kv_hv"], step=1.0, format="%.3f",
                key=f"{selected_preset}__kv_hv",
                help="Uses Tap Position 3 (22.425kV) per the settings doc's full-load calc, not the 23kV nameplate.")
            if is_custom:
                ct_hv = st.number_input("HV CT Ratio (Primary A, e.g. 100 in '100:5')", value=float(p_data["ct_hv"]), key=f"{selected_preset}__ct_hv")
            else:
                ct_hv = st.select_slider(
                    "HV CT Ratio Tap (Multi-Ratio, Primary A)", options=MR_CT_TAPS_3000_5,
                    value=p_data["ct_hv"] if p_data["ct_hv"] in MR_CT_TAPS_3000_5 else 3000,
                    key=f"{selected_preset}__ct_hv",
                    help="3000:5 Wye-connected multi-ratio bushing CT — the tap can be reselected in the "
                         "field based on the actual/expected load current. Documented as set on 3000:5 (max)."
                )
            ct_conn_hv = st.selectbox(
                "HV CT Connection", ["WYE", "DELTA"],
                index=0 if p_data.get("ct_conn_hv", "WYE") == "WYE" else 1,
                key=f"{selected_preset}__ct_conn_hv"
            )
        with r1c2:
            ct_secondary_rating = st.selectbox(
                "CT Secondary Rating (A)", [1.0, 5.0], index=1 if p_data["ct_sec"] == 5.0 else 0,
                key=f"{selected_preset}__ct_sec",
                help="The rated secondary current stamped on the CT nameplate (the '5' in '4000:5'). "
                     "Applied to both CTs to determine the true turns ratio used in all per-unit scaling."
            )
            kv_lv = st.number_input("LV Rated Voltage (kV)", value=p_data["kv_lv"], step=0.1, format="%.3f", key=f"{selected_preset}__kv_lv")
            ct_lv = st.number_input("LV CT Ratio (Primary A, e.g. 4000 in '4000:5')", value=float(p_data["ct_lv"]), key=f"{selected_preset}__ct_lv")
            ct_conn_lv = st.selectbox(
                "LV CT Connection", ["DELTA", "WYE"],
                index=0 if p_data.get("ct_conn_lv", "DELTA") == "DELTA" else 1,
                key=f"{selected_preset}__ct_conn_lv"
            )
        st.caption(
            f"Effective ratio → HV: **{ct_hv:.0f}:{ct_secondary_rating:.0f}** "
            f"(= {ct_hv/ct_secondary_rating:.1f}:1)  |  "
            f"LV: **{ct_lv:.0f}:{ct_secondary_rating:.0f}** "
            f"(= {ct_lv/ct_secondary_rating:.1f}:1)"
        )

    delta_factor_hv = 1.7320508 if ct_conn_hv.upper() == "DELTA" else 1.0
    delta_factor_lv = 1.7320508 if ct_conn_lv.upper() == "DELTA" else 1.0
    i_rated_pri_hv = (mva * 1000.0) / (1.7320508 * kv_hv) if kv_hv > 0 else 0.0
    i_rated_pri_lv = (mva * 1000.0) / (1.7320508 * kv_lv) if kv_lv > 0 else 0.0
    t1_e = suggest_ct_matching_tap(i_rated_pri_hv, ct_hv, ct_secondary_rating, delta_factor_hv)
    t2_e = suggest_ct_matching_tap(i_rated_pri_lv, ct_lv, ct_secondary_rating, delta_factor_lv)

    with st.container(border=True):
        st.markdown("**CT Matching Taps**")
        st.caption(
            "T_E is the reference tap that would give zero mismatch if this winding were tapped alone — "
            "T1 and T2 are then chosen JOINTLY to minimize the actual mismatch between HV and LV below, "
            "not to each independently match their own T_E. The mismatch metric below is the real signal."
        )
        t1c1, t1c2 = st.columns(2)
        with t1c1:
            tap_hv = slider_with_exact_input(
                st, "HV Tap (T1)", 0.4, 2.18, p_data["tap_hv"], 0.01,
                key=f"{selected_preset}__tap_hv",
                help_text="CAC1-10-M3 setting range: 0.4-2.18. Selected so the tap-corrected current at "
                           "rated load is close to the relay's rated tap current (I_N = 5A)."
            )
            if t1_e is not None:
                st.caption(f"T1_E (reference, this winding alone) ≈ {t1_e:.3f}")
        with t1c2:
            tap_lv = slider_with_exact_input(
                st, "LV Tap (T2)", 0.4, 2.18, p_data["tap_lv"], 0.01,
                key=f"{selected_preset}__tap_lv",
                help_text="CAC1-10-M3 setting range: 0.4-2.18."
            )
            if t2_e is not None:
                st.caption(f"T2_E (reference, this winding alone) ≈ {t2_e:.3f}")

        i_relay_hv_at_set_tap = (i_rated_pri_hv / (ct_hv / ct_secondary_rating) * delta_factor_hv * tap_hv) if ct_hv > 0 else None
        i_relay_lv_at_set_tap = (i_rated_pri_lv / (ct_lv / ct_secondary_rating) * delta_factor_lv * tap_lv) if ct_lv > 0 else None
        calc_mismatch = mismatch_ratio_pct([i_relay_hv_at_set_tap, i_relay_lv_at_set_tap])
        st.metric("Mismatch at currently-set taps (the actual signal)", f"{calc_mismatch:.2f}%" if calc_mismatch is not None else "—")
        if calc_mismatch is not None:
            if calc_mismatch < 5.0:
                st.success(f"{calc_mismatch:.2f}% mismatch — low, well within the usual rule-of-thumb range.")
            else:
                st.warning(f"{calc_mismatch:.2f}% mismatch — unusually high. Review the tap selection before applying.")

    suggestion = suggest_bias_settings(calc_mismatch or 0.0, num_windings=2)

    with st.container(border=True):
        st.markdown("**Differential Settings**")
        st.caption(
            f"Rule-of-thumb floor for the current {calc_mismatch:.2f}% mismatch: Bias ≈ {suggestion['bias_pct']:.0f}%, "
            f"Min Operate ≈ {suggestion['min_operate_pct']:.0f}%, HOC ≈ {suggestion['hoc_multiple']:.0f}x tap current. "
            "Engineering review required — always confirm against a real through-fault/inrush coordination study."
            if calc_mismatch is not None else
            "Set the HV/LV taps above first to compute a mismatch-based floor for these settings."
        )
        d1c1, d1c2, d1c3 = st.columns(3)
        with d1c1:
            bias_pct = slider_with_exact_input(
                st, "Bias, τ (%)", 5, 60, p_data["bias"], 1,
                key=f"{selected_preset}__bias",
                help_text="Must exceed the sum of tap-changer error, CT error, relay operating error "
                           "(10% of bias) and mismatch — see Calculation/Discussion in the settings doc."
            )
            if bias_pct >= suggestion["bias_pct"]:
                st.success(f"Clears the {suggestion['bias_pct']:.0f}% floor. Higher = more secure against nuisance trips, but less sensitive to small internal faults.")
            else:
                st.warning(f"Below the {suggestion['bias_pct']:.0f}% floor for this mismatch — raises the risk of a nuisance trip on inrush or normal mismatch current.")
        with d1c2:
            min_operate_pct = slider_with_exact_input(
                st, "Minimum Operate (%)", 5, 60, p_data["min_operate"], 1,
                key=f"{selected_preset}__min_operate",
                help_text="Minimum differential pickup at zero restraint current."
            )
            if min_operate_pct >= suggestion["min_operate_pct"]:
                st.success(f"Clears the {suggestion['min_operate_pct']:.0f}% floor — secure against CT/relay noise at light load.")
            else:
                st.warning(f"Below the {suggestion['min_operate_pct']:.0f}% floor — more sensitive to light internal faults, but more exposed to false operation from CT noise/tap mismatch.")
        with d1c3:
            hoc_multiple = slider_with_exact_input(
                st, "HOC (x tap current)", 2.0, 20.0, float(p_data["hoc"]), 0.5,
                key=f"{selected_preset}__hoc",
                help_text="Unrestrained instantaneous element. Set high enough not to operate on "
                           "transformer inrush current (see Calculation/Discussion)."
            )
            if hoc_multiple <= suggestion["hoc_multiple"] + 2.0:
                st.success(f"Clears inrush at this relay family's typical {suggestion['hoc_multiple']:.0f}x floor while still tripping fast on a severe internal fault.")
            else:
                st.info("Higher setting — more secure against inrush/CT saturation misoperation, but needs a larger internal fault to trip instantaneously.")

    all_clear = (
        calc_mismatch is not None
        and calc_mismatch < 5.0
        and bias_pct >= suggestion["bias_pct"]
        and min_operate_pct >= suggestion["min_operate_pct"]
    )
    if calc_mismatch is None:
        st.info("Overall status: set the HV/LV taps above to compute a status.")
    elif all_clear:
        st.success("Overall status: all settings shown clear their recommended margins. Engineering approval is still required before issue.")
    else:
        st.warning("Overall status: one or more settings above need review before this is applied.")


windings = [
    {"name": "HV (23kV)", "kv": kv_hv, "ct_ratio": ct_hv, "ct_secondary_rating": ct_secondary_rating, "tap": tap_hv, "ct_connection": ct_conn_hv},
    {"name": "LV (13.8kV)", "kv": kv_lv, "ct_ratio": ct_lv, "ct_secondary_rating": ct_secondary_rating, "tap": tap_lv, "ct_connection": ct_conn_lv},
]
record_equipment_settings("aux", {
    "mva": mva, "kv_hv": kv_hv, "kv_lv": kv_lv,
    "ct_hv": ct_hv, "ct_lv": ct_lv, "ct_sec": ct_secondary_rating,
    "ct_conn_hv": ct_conn_hv, "ct_conn_lv": ct_conn_lv,
    "tap_hv": tap_hv, "tap_lv": tap_lv,
    "bias": bias_pct, "min_operate": min_operate_pct, "hoc": hoc_multiple,
    "calc_mismatch_pct": calc_mismatch,
})

# Placeholder Wiring & Convention values, used only to build the relay object needed by the
# Theory tab's SLD diagram below (which runs before the Simulate & Test tab in script order).
# The real Restraint Standard / Polarity Reference selection lives on the Simulate & Test tab
# now, which rebuilds this object with the user's actual choice before anything that needs the
# real value (test evaluation, the settings sheet) runs.
convention, ct_polarity = "IEEE", "OPPOSITE"
relay = TransformerDifferentialRelay(
    mva_rated=mva, windings=windings,
    bias_pct=bias_pct, min_operate_pct=min_operate_pct, hoc_multiple=hoc_multiple,
    convention=convention, ct_polarity=ct_polarity,
)

phases = ["Phase A", "Phase B", "Phase C"]
amps_base = relay.windings[0]["i_rated_sec"]  # HV-side rated secondary current, used as pu base for charts

with outer_analysis:
    st.caption(
        "Everything below reads the settings from the Current Settings tab — adjust them there. "
        "Tabs run in the same order on every equipment page: Theory → Simulate & Test → "
        "Commissioning & Injection Tool → Fault Current Analysis "
        "(where present) → Settings Summary & Approval. Full guide on the Home page."
    )

    tab_theory, tab_sim, tab2, tab_fault, tab_approval = st.tabs([
        "Theory", "Simulate & Test",
        "Commissioning & Injection Tool",
        "Fault Current Analysis", "Settings Summary & Approval",
    ])

    with tab_theory:
        render_theory_tab(
            "transformer",
            purpose_text=(
                "The 87AT relay protects the Unit Auxiliary Transformer, which feeds the plant's own "
                "medium-voltage house loads (pumps, fans, and other auxiliaries) directly off the "
                "generator bus. Losing it doesn't just risk equipment damage at the fault location — "
                "it can black out the auxiliaries an operating unit depends on to keep running, so it "
                "gets the same dedicated differential treatment as the main power-delivery "
                "transformers."
            ),
            sld_image_name="transformer_aux.png",
            sld_fallback_svg=two_winding_transformer_zone_svg(
                relay, ct_polarity, tag="87AT",
                hv_bus_label="23kV (from Generator/GSUT Bus)", lv_bus_label="13.8kV (to MV Switchgear Bus A/B/C)"
            ),
        )

    # ---------------------------------------------------------------------------
    # TAB — Simulate & Test
    # ---------------------------------------------------------------------------
    with tab_sim:
        with st.container(border=True):
            st.markdown("**Wiring & Convention**")
            st.caption(
                "Must match the actual field CT wiring — not a tunable protection margin, so no improve/worsen "
                "comment applies here. Delta-connected CTs get an automatic √3 magnitude step-up and a +30° "
                "phase shift (see engines/transformer.py) — the standard compensation for a Wye/Delta power "
                "transformer so healthy through-load doesn't read as a fault."
            )
            col_conv, col_pol = st.columns(2)
            with col_conv:
                convention = st.radio("Restraint Standard", ["IEEE", "IEC"], help="IEEE: Average current. IEC: Arithmetic sum.")
            with col_pol:
                def _on_polarity_change():
                    # Streamlit widgets stop re-reading their value= argument once
                    # created, so recomputing the healthy default inline on every
                    # rerun (below, for Phase A) only ever applies on first page
                    # load - switching this radio afterwards needs to explicitly
                    # overwrite session_state here, or the LV angle goes stale and
                    # a healthy through-load starts reading as a phantom trip.
                    new_polarity = st.session_state["aux_ct_polarity_widget"]
                    windings_tmp = [
                        {"name": "HV", "kv": kv_hv, "ct_ratio": ct_hv, "ct_secondary_rating": ct_secondary_rating, "tap": tap_hv, "ct_connection": ct_conn_hv},
                        {"name": "LV", "kv": kv_lv, "ct_ratio": ct_lv, "ct_secondary_rating": ct_secondary_rating, "tap": tap_lv, "ct_connection": ct_conn_lv},
                    ]
                    relay_tmp = TransformerDifferentialRelay(
                        mva_rated=mva, windings=windings_tmp,
                        bias_pct=30, min_operate_pct=30, hoc_multiple=5,
                        convention="IEEE", ct_polarity=new_polarity,
                    )
                    hv_rated = relay_tmp.windings[0]["i_rated_pri"]
                    st.session_state["aux_lv_a_Phase A"] = solve_healthy_target_angle(relay_tmp, 1, 0, hv_rated, 0.0)

                ct_polarity = st.radio(
                    "Polarity Reference", ["OPPOSITE", "SAME"], index=0,
                    key="aux_ct_polarity_widget", on_change=_on_polarity_change,
                    help="OPPOSITE is standard for a 2-winding transformer differential (currents flow "
                         "into the zone on one side, out on the other)."
                )

        # Rebuilds `relay` with the real Wiring & Convention selection above, replacing the
        # placeholder built earlier (before this tab ran) for the Theory tab's SLD. Every tab
        # after this one in script order (Commissioning, TCC Curve, Fault Current Analysis,
        # Settings Summary & Approval) sees this rebuilt object too.
        relay = TransformerDifferentialRelay(
            mva_rated=mva, windings=windings,
            bias_pct=bias_pct, min_operate_pct=min_operate_pct, hoc_multiple=hoc_multiple,
            convention=convention, ct_polarity=ct_polarity,
        )

        col_inputs, col_results = st.columns([1.2, 1.0])

        with col_inputs:
            st.subheader("Winding Operating Phase Inputs")
            st.caption(
                "Enter the actual PRIMARY-side current in Amps for each winding — the app "
                "converts this through the CT ratio and matching tap automatically."
            )
            st.info(f"HV Nominal Rated Current: **{relay.windings[0]['i_rated_pri']:.1f} A**  |  "
                    f"LV Nominal Rated Current: **{relay.windings[1]['i_rated_pri']:.1f} A**")

            inputs = {}
            for idx, phase in enumerate(phases):
                with st.expander(f"{phase} Settings", expanded=(phase == "Phase A")):
                    c1, c2 = st.columns(2)
                    def_ang_hv = -120.0 * idx
                    if phase == "Phase A":
                        def_val_hv = relay.windings[0]["i_rated_pri"]
                        def_val_lv = relay.windings[1]["i_rated_pri"]
                        # Solve only the ANGLE that makes a healthy through-load cancel,
                        # accounting for each winding's own Delta/Wye CT compensation -
                        # not just a naive +-180 degree guess. Magnitude is left at LV's
                        # own Nominal Rated Current (matching the info box above) rather
                        # than solved-for, so a small residual (~1%, the same order as
                        # the settings doc's documented tap mismatch) is expected and
                        # correct, not a bug - a perfect 0.000 would actually be less
                        # realistic.
                        vec_hv_internal = winding_internal_vector(relay, 0, def_val_hv, def_ang_hv)
                        target_lv_internal = vec_hv_internal if ct_polarity == "OPPOSITE" else -vec_hv_internal
                        _, def_ang_lv = raw_input_for_internal_vector(relay, 1, target_lv_internal)
                    else:
                        def_val_hv = 0.0
                        def_val_lv = 0.0
                        # Same sign convention as the Phase A solve above (harmless here
                        # since magnitude is 0, but was backwards - matches the Generator
                        # page's fixed bug: OPPOSITE needs matching angles to cancel, SAME
                        # needs 180 deg apart).
                        def_ang_lv = def_ang_hv if ct_polarity == "OPPOSITE" else def_ang_hv + 180.0

                    with c1:
                        i_hv = st.number_input(f"HV Primary Amps [A]", value=def_val_hv, key=f"aux_hv_i_{phase}")
                        a_hv = st.number_input(f"HV Angle (°)", value=def_ang_hv, key=f"aux_hv_a_{phase}")
                    with c2:
                        i_lv = st.number_input(f"LV Primary Amps [A]", value=def_val_lv, key=f"aux_lv_i_{phase}")
                        a_lv = st.number_input(f"LV Angle (°)", value=def_ang_lv, key=f"aux_lv_a_{phase}")

                    inputs[phase] = {"i_hv": i_hv, "a_hv": a_hv, "i_lv": i_lv, "a_lv": a_lv}

            evals = {p: relay.evaluate_protection([
                (inputs[p]["i_hv"], inputs[p]["a_hv"]),
                (inputs[p]["i_lv"], inputs[p]["a_lv"]),
            ]) for p in phases}

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
            st.caption("The Relay-Ready Settings Sheet, settings export, and a certified audit report are in the Settings Summary & Approval tab.")
            winding_currents = {p: [inputs[p]["i_hv"], inputs[p]["i_lv"]] for p in phases}

        st.subheader("Differential Bias Characteristic Curve")

        chart_units = st.radio(
            "Chart units", ["Per-Unit (pu)", "Secondary Amps (A)"], horizontal=True,
            key="aux_live_chart_units",
            help="pu base is the HV-side rated secondary current."
        )
        use_amps = chart_units == "Secondary Amps (A)"

        max_x_val = max(6.0, max(e["i_rest_pu"] for e in evals.values()) + 1.5, relay.hoc_pu + 1.0)
        x_axis_line = np.linspace(0, max_x_val, 400)
        y_axis_line = [relay.calculate_trip_threshold(x) for x in x_axis_line]

        x_plot = x_axis_line * amps_base if use_amps else x_axis_line
        y_plot = np.array(y_axis_line) * amps_base if use_amps else np.array(y_axis_line)
        unit_label = "A" if use_amps else "pu"

        y_upper_pu = max(relay.hoc_pu + 2.0, max(y_axis_line) + 1.0)
        y_upper = y_upper_pu * amps_base if use_amps else y_upper_pu
        x_upper = max_x_val * amps_base if use_amps else max_x_val

        fig = go.Figure()

        # Shaded Restraint Region (below the trip line, safe) and Operating Region
        # (above it, trips) - the fill follows the CAL. line's actual shape exactly.
        fig.add_trace(go.Scatter(x=x_plot, y=np.zeros_like(x_plot), mode='lines', line=dict(width=0), showlegend=False, hoverinfo='skip'))
        fig.add_trace(go.Scatter(
            x=x_plot, y=y_plot, mode='lines', name='CAL.', line=dict(color='#2563EB', width=3),
            fill='tonexty', fillcolor='rgba(22,163,74,0.10)'
        ))
        fig.add_trace(go.Scatter(
            x=x_plot, y=np.full_like(x_plot, y_upper), mode='lines', line=dict(width=0),
            fill='tonexty', fillcolor='rgba(220,38,38,0.08)', showlegend=False, hoverinfo='skip'
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

        hoc_val = relay.hoc_pu * amps_base if use_amps else relay.hoc_pu
        fig.add_trace(go.Scatter(
            x=[0, max_x_val * amps_base if use_amps else max_x_val], y=[hoc_val, hoc_val],
            mode='lines', name='HOC (Unrestrained)', line=dict(color='#DC2626', width=2, dash='dash')
        ))

        phase_colors = {"Phase A": "red", "Phase B": "green", "Phase C": "blue"}
        for p in phases:
            e = evals[p]
            px = e["i_rest_pu"] * amps_base if use_amps else e["i_rest_pu"]
            py = e["i_op_pu"] * amps_base if use_amps else e["i_op_pu"]
            fig.add_trace(go.Scatter(
                x=[px], y=[py], mode='markers+text', name=f"{p}",
                text=[f"{p}"], textposition="top center",
                marker=dict(size=14, color=phase_colors[p], symbol='x' if e["is_trip"] else 'circle'),
                hovertemplate=f"<b>{p}</b><br>I_rest: %{{x:.3f}} {unit_label}<br>I_op: %{{y:.3f}} {unit_label}<br>State: {e['status']}<extra></extra>"
            ))

        fig.update_layout(
            title="Transformer Differential Bias Characteristic",
            xaxis_title=f"Restraint Current I_rest ({unit_label})",
            yaxis_title=f"Differential/Operating Current I_op ({unit_label})",
            xaxis=dict(range=[0, x_upper]), yaxis=dict(range=[0, y_upper]),
            template="plotly_white", height=500
        )
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        st.subheader("Log a Test Point")

        st.subheader("Test Point Verification & Curve")
        st.write("Enter measured test results and see them plotted against the calculated characteristic curve.")

        if "aux_manual_test_points" not in st.session_state:
            st.session_state.aux_manual_test_points = []

        tp_source = st.radio(
            "How was this measured?", TEST_POINT_SOURCE_OPTIONS, horizontal=True,
            key="aux_tp_source", help=TEST_POINT_SOURCE_HELP,
        )
        with st.form("aux_add_test_point_form", clear_on_submit=True):
            tp_phase = st.selectbox("Phase", ["Phase A", "Phase B", "Phase C", "Other"])
            if tp_source.startswith("Restraint"):
                tp_unit = st.radio(
                    "Entry units", ["Secondary Amps (A)", "Per-Unit (pu)"], horizontal=True, key="aux_tp_entry_unit"
                )
                tc2, tc3 = st.columns(2)
                restraint_label = "Restraint Current" if tp_unit.startswith("Secondary") else "Restraint Current (pu)"
                diff_label = "Measured Diff. Current" if tp_unit.startswith("Secondary") else "Measured Diff. Current (pu)"
                restraint_step = 0.1 if tp_unit.startswith("Secondary") else 0.05
                diff_step = 0.05 if tp_unit.startswith("Secondary") else 0.01
                restraint_default = 1.0 if tp_unit.startswith("Secondary") else 0.3
                diff_default = 0.3 if tp_unit.startswith("Secondary") else 0.06
                with tc2:
                    tp_restraint = st.number_input(restraint_label, min_value=0.0, value=restraint_default, step=restraint_step)
                with tc3:
                    tp_diff = st.number_input(diff_label, min_value=0.0, value=diff_default, step=diff_step)
            else:
                st.caption("Enter the actual primary Amps and phase angle measured/injected at each winding's CT.")
                raw_inputs = raw_current_inputs(
                    ["HV", "LV"], "aux_tp_raw",
                    default_primary_amps=[relay.windings[0]["i_rated_pri"], relay.windings[1]["i_rated_pri"]],
                )
            tp_label = st.text_input("Label (optional)", value="")
            submitted = st.form_submit_button("Add Test Point")
            if submitted:
                if tp_source.startswith("Restraint"):
                    if tp_unit.startswith("Secondary"):
                        restraint_amps, diff_amps = tp_restraint, tp_diff
                    else:
                        restraint_amps, diff_amps = tp_restraint * amps_base, tp_diff * amps_base
                else:
                    raw_eval = relay.evaluate_protection(raw_inputs)
                    restraint_amps = raw_eval["i_rest_pu"] * amps_base
                    diff_amps = raw_eval["i_op_pu"] * amps_base
                st.session_state.aux_manual_test_points.append({
                    "Phase": tp_phase,
                    "Restraint (A)": round(restraint_amps, 3),
                    "Measured Diff (A)": round(diff_amps, 3),
                    "Label": tp_label
                })

        if st.session_state.aux_manual_test_points:
            table_unit = st.radio("Display units for table", ["Secondary Amps (A)", "Per-Unit (pu)"], horizontal=True, key="aux_tp_table_unit")
            table_in_pu = table_unit.startswith("Per-Unit")
            restraint_col = "Restraint (pu)" if table_in_pu else "Restraint (A)"
            diff_col = "Measured Diff (pu)" if table_in_pu else "Measured Diff (A)"

            tp_display_rows = []
            for tp in st.session_state.aux_manual_test_points:
                r_amps, d_amps = tp["Restraint (A)"], tp["Measured Diff (A)"]
                tp_display_rows.append({
                    "Phase": tp["Phase"],
                    restraint_col: round(r_amps / amps_base, 3) if table_in_pu else round(r_amps, 3),
                    diff_col: round(d_amps / amps_base, 3) if table_in_pu else round(d_amps, 3),
                    "Label": tp["Label"]
                })
            st.dataframe(pd.DataFrame(tp_display_rows), use_container_width=True)

            rc1, rc2 = st.columns(2)
            with rc1:
                remove_idx = st.number_input(
                    "Row # to remove (0-indexed)", min_value=0,
                    max_value=max(len(st.session_state.aux_manual_test_points) - 1, 0), value=0, step=1
                )
                if st.button("Remove Row"):
                    st.session_state.aux_manual_test_points.pop(int(remove_idx))
                    st.rerun()
            with rc2:
                if st.button("Clear All Test Points"):
                    st.session_state.aux_manual_test_points = []
                    st.rerun()
        else:
            st.info("No test points added yet — add some above to see them plotted below.")

        st.markdown("---")
        st.markdown("#### Differential Bias Characteristic Curve")

        comm_chart_units = st.radio("Chart units", ["Per-Unit (pu)", "Secondary Amps (A)"], horizontal=True, key="aux_test_chart_units")
        use_amps_comm = comm_chart_units == "Secondary Amps (A)"
        unit_label_comm = "A" if use_amps_comm else "pu"

        cal_source = st.radio(
            "CAL. line source",
            ["Connect my test points (commissioning report style)", "Theoretical relay characteristic"],
            horizontal=True, key="aux_cal_line_source"
        )

        sweep_fig = go.Figure()
        if cal_source.startswith("Connect") and len(st.session_state.aux_manual_test_points) >= 2:
            sorted_pts = sorted(st.session_state.aux_manual_test_points, key=lambda tp: tp["Restraint (A)"])
            cal_x_amps = [tp["Restraint (A)"] for tp in sorted_pts]
            cal_y_amps = [tp["Measured Diff (A)"] for tp in sorted_pts]
            curve_x = cal_x_amps if use_amps_comm else [x / amps_base for x in cal_x_amps]
            curve_y = cal_y_amps if use_amps_comm else [y / amps_base for y in cal_y_amps]
            sweep_fig.add_trace(go.Scatter(x=curve_x, y=curve_y, mode="lines", name="CAL.", line=dict(color="#2E8B57", width=3)))
        else:
            if cal_source.startswith("Connect"):
                st.info("Add at least 2 test points above to draw the CAL. line through them — showing the theoretical characteristic for now.")
            manual_restraints_pu = [tp["Restraint (A)"] / amps_base for tp in st.session_state.aux_manual_test_points]
            default_reach = relay.hoc_pu + 2.0
            max_restraint = max(manual_restraints_pu + [default_reach]) if manual_restraints_pu else default_reach
            curve_x_pu = np.linspace(0, max_restraint * 1.2 + 0.5, 300)
            curve_y_pu = [relay.calculate_trip_threshold(x) for x in curve_x_pu]
            curve_x = curve_x_pu * amps_base if use_amps_comm else curve_x_pu
            curve_y = np.array(curve_y_pu) * amps_base if use_amps_comm else np.array(curve_y_pu)
            # Shaded Restraint/Operating regions - only meaningful for the theoretical
            # curve (a straight line through test points isn't the real characteristic).
            sweep_fig.add_trace(go.Scatter(x=curve_x, y=np.zeros_like(curve_x), mode='lines', line=dict(width=0), showlegend=False, hoverinfo='skip'))
            sweep_fig.add_trace(go.Scatter(
                x=curve_x, y=curve_y, mode="lines", name="CAL.", line=dict(color="#2E8B57", width=3),
                fill='tonexty', fillcolor='rgba(22,163,74,0.10)'
            ))
            sweep_fig.add_trace(go.Scatter(
                x=curve_x, y=np.full_like(curve_x, max(curve_y) * 1.15 + 0.1), mode='lines', line=dict(width=0),
                fill='tonexty', fillcolor='rgba(220,38,38,0.08)', showlegend=False, hoverinfo='skip'
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
        for tp in st.session_state.aux_manual_test_points:
            r_amps, d_amps = tp["Restraint (A)"], tp["Measured Diff (A)"]
            px = r_amps if use_amps_comm else r_amps / amps_base
            py = d_amps if use_amps_comm else d_amps / amps_base
            trace_name = tp["Phase"] + (f' ({tp["Label"]})' if tp["Label"] else "")
            sweep_fig.add_trace(go.Scatter(
                x=[px], y=[py], mode="markers", name=trace_name,
                marker=dict(size=13, color=tp_marker_colors.get(tp["Phase"], "#F59E0B"), symbol=tp_marker_symbols.get(tp["Phase"], "diamond")),
                hovertemplate=f"<b>{tp['Phase']}</b><br>Restraint: %{{x:.3f}} {unit_label_comm}<br>Measured Diff: %{{y:.3f}} {unit_label_comm}<extra></extra>"
            ))

        sweep_fig.update_layout(
            title="Differential Bias Characteristic Curve",
            xaxis_title=f"Restraint Current ({unit_label_comm})",
            yaxis_title=f"Diff. Current ({unit_label_comm})",
            template="plotly_white", height=450
        )
        png_filename = f"87AT_Differential_Bias_Curve_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}"
        st.plotly_chart(sweep_fig, use_container_width=True, config={"toImageButtonOptions": {"format": "png", "filename": png_filename, "scale": 3}})

        st.markdown("---")
        render_historian_overlay(st, "aux", reference_lines=[
            ("HV Rated (A)", relay.windings[0]["i_rated_pri"]),
            ("LV Rated (A)", relay.windings[1]["i_rated_pri"]),
        ])

    # ---------------------------------------------------------------------------
    # TAB 2 — Commissioning & Injection Tool
    # ---------------------------------------------------------------------------
    with tab2:
        st.subheader("Commissioning & Secondary Current Injection Assistant")
        st.write(
            "Pick a target restraint current for each phase to calculate the exact secondary "
            "Amps to inject at your test set for that phase."
        )

        default_restraints = {"Phase A": 0.5, "Phase B": 2.5, "Phase C": 5.0}
        st.markdown("#### Boundary Injection Calculator")
        cols = st.columns(3)
        for p, col in zip(phases, cols):
            with col:
                st.markdown(f"**{p}**")
                r_val = slider_with_exact_input(
                    st, f"{p} Target Restraint (pu)", 0.1, 20.0, default_restraints[p], 0.1,
                    key=f"{selected_preset}__commtest__{p}"
                )
                boundary_op = relay.calculate_trip_threshold(r_val)
                # 2-winding, IEEE-average-style boundary split (matches Generator engine's N/T convention)
                sec_hv = (r_val + boundary_op / 2.0) * relay.windings[0]["i_rated_sec"]
                sec_lv = (r_val - boundary_op / 2.0) * relay.windings[1]["i_rated_sec"]
                st.metric("Boundary I_op", f"{boundary_op:.3f} pu")
                st.caption(f"HV inject: **{sec_hv:.3f} A**")
                st.caption(f"LV inject: **{sec_lv:.3f} A**")

        st.markdown("---")
        st.subheader("Auto-Sweep Full Curve Test Table")
        sw1, sw2, sw3 = st.columns(3)
        with sw1:
            sweep_start = st.number_input("Sweep Start (pu)", value=0.2, min_value=0.0, step=0.1)
        with sw2:
            sweep_end = st.number_input("Sweep End (pu)", value=max(6.0, relay.hoc_pu + 1.0), step=0.5)
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
                    sec_hv = (i_rest + boundary_op / 2.0) * relay.windings[0]["i_rated_sec"]
                    sec_lv = (i_rest - boundary_op / 2.0) * relay.windings[1]["i_rated_sec"]
                    sweep_rows.append({
                        "I_rest (pu)": round(float(i_rest), 3),
                        "Boundary I_op (pu)": round(boundary_op, 3),
                        "HV Injection (A)": round(sec_hv, 3),
                        "LV Injection (A)": round(sec_lv, 3),
                    })
                st.session_state["aux_sweep_df"] = pd.DataFrame(sweep_rows)

        if "aux_sweep_df" in st.session_state:
            st.dataframe(st.session_state["aux_sweep_df"], use_container_width=True)
            csv_sweep = st.session_state["aux_sweep_df"].to_csv(index=False).encode("utf-8")
            st.download_button(
                label="Download Sweep Table as CSV",
                data=csv_sweep,
                file_name=f"87AT_Sweep_Test_Table_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv"
            )

    with tab_fault:
        st.subheader("Fault Current Analysis")
        st.write(
            "Checks the 87AT CTs against the maximum through-fault current this transformer's own "
            "impedance allows, using the same method as EXCT's own settings document worked example "
            "— not just the relay's own characteristic curve in isolation."
        )
        st.caption(
            "A transformer isn't a fault current source the way a generator is — its own impedance "
            "instead LIMITS the maximum through-fault current for a fault at or beyond its "
            "terminals. This uses only this transformer's own nameplate impedance (an 'infinite "
            "bus' simplifying assumption — no source impedance beyond the transformer, no network "
            "reduction)."
        )

        fmc1, fmc2 = st.columns(2)
        with fmc1:
            fault_mva_base = st.number_input(
                "Impedance Base (MVA)", min_value=0.1, value=p_data.get("fault_mva_base", mva), step=1.0, format="%.3f",
                key=f"{selected_preset}__fault_mva_base",
                help="The MVA rating the nameplate impedance % is stated on."
            )
            z_pct = st.number_input(
                "Transformer Impedance, Z (%)", min_value=0.5, value=p_data.get("z_pct", 8.47), step=0.1,
                key=f"{selected_preset}__z_pct",
                help="Minimum Impedance (8.47%, Appendix A) from this UAT's own instruction book — used instead of the 8.5% design/nameplate value since the lower figure gives the worst-case maximum through-fault current."
            )
            x_over_r = st.number_input(
                "X/R Ratio", min_value=1.0, value=p_data.get("x_over_r", 38.9), step=0.5,
                key=f"{selected_preset}__x_over_r",
                help="From this UAT's own instruction book, Appendix A (X/R=38.9)."
            )
            fault_side = st.radio(
                "Check CT On", ["HV", "LV"], horizontal=True, key=f"{selected_preset}__fault_side",
                help="Which winding's CT to check."
            )
            fault_kv_hv = st.number_input(
                "HV Nameplate Voltage (kV, for fault base)", min_value=0.1, value=p_data.get("fault_kv_hv", 23.0), step=0.1,
                key=f"{selected_preset}__fault_kv_hv",
                help="The transformer's actual HV nameplate voltage (23kV) - deliberately separate "
                     "from the HV Rated Voltage in Current Settings above (22.425kV, Tap Position 3), "
                     "which is tap-adjusted for the differential relay's own CT-matching calculation "
                     "and would understate the fault current base if reused here."
            )
            asym_basis = st.radio(
                "Asymmetry Basis", ["Actual X/R", "Worst-case (1.73× flat)"], horizontal=True,
                key=f"{selected_preset}__asym_basis",
                help="Actual X/R: computes how much the DC offset has decayed by 0.5 cycle, using "
                     "this transformer's real X/R above. Worst-case: skips that decay and uses the "
                     "flat sqrt(3)=1.73 ceiling instead (X/R -> infinity) - what some settings "
                     "documents state directly rather than computing from the actual X/R. Worst-case "
                     "is always >= the Actual X/R result."
            )

        fault_kv = fault_kv_hv if fault_side == "HV" else kv_lv
        fault_ct = ct_hv if fault_side == "HV" else ct_lv
        fault_calc = transformer_through_fault_current(
            fault_mva_base, fault_kv, z_pct / 100.0, x_over_r,
            use_worst_case_asym=(asym_basis == "Worst-case (1.73× flat)"),
        )
        relay_sec_fault = relay_secondary_at_fault(fault_calc["i_asym_amps"], fault_ct, ct_secondary_rating)

        with fmc2:
            sm1, sm2 = st.columns([3, 1])
            with sm1:
                st.metric("Symmetrical Through-Fault Current", f"{fault_calc['i_sym_amps']:,.0f} A")
            with sm2:
                fault_term_info("symmetrical", "Symmetrical")
            am1, am2 = st.columns([3, 1])
            with am1:
                st.metric("Asymmetrical Through-Fault Current", f"{fault_calc['i_asym_amps']:,.0f} A ({fault_calc['asym_factor']:.2f}x)")
            with am2:
                fault_term_info("through", "Through-Fault")
            st.metric(f"Relay Secondary Current ({fault_side} CT)", f"{relay_sec_fault:.1f} A")

        st.markdown("---")
        ct_withstand_a = st.number_input(
            "CT / Relay Secondary Current Withstand Limit (A)", min_value=1.0, value=p_data.get("ct_withstand_a", 60.0), step=1.0,
            key=f"{selected_preset}__ct_withstand",
            help="Editable reference value — confirm against the relay manufacturer's own burden/CT "
                 "saturation calculation for this specific CT and cable run."
        )
        if relay_sec_fault <= ct_withstand_a:
            st.success(f"Through-fault relay secondary current ({relay_sec_fault:.1f} A) is within the {ct_withstand_a:.0f} A withstand limit.")
        else:
            st.warning(f"Through-fault relay secondary current ({relay_sec_fault:.1f} A) EXCEEDS the {ct_withstand_a:.0f} A withstand limit — review CT ratio, impedance base, or relay burden.")

        st.markdown("---")
        st.markdown("#### Actual Fault Current Waveform")
        st.caption(
            "The Asymmetrical Through-Fault Current above is an RMS figure — this shows what the "
            "actual instantaneous AC current looks like: a decaying DC offset riding on top of the "
            "steady-state sine wave, worst case (fault at a voltage zero-crossing). Extends the same "
            "X/R-based decay already verified in the asymmetry factor above from a single RMS "
            "multiplier into a continuous waveform — same underlying physics, not a new formula."
        )
        _wf_cycles = 5
        _wf_f = 60.0
        _wf_w = 2 * np.pi * _wf_f
        _wf_t = np.linspace(0, _wf_cycles / _wf_f, 800)
        _wf_i_peak_sym = np.sqrt(2) * fault_calc["i_sym_amps"]
        _wf_decay_rate = _wf_w / x_over_r
        _wf_i = _wf_i_peak_sym * (np.exp(-_wf_t * _wf_decay_rate) - np.cos(_wf_w * _wf_t))
        _wf_fig = go.Figure()
        _wf_fig.add_trace(go.Scatter(
            x=_wf_t * 1000.0, y=_wf_i, mode="lines", name="Instantaneous Current",
            line=dict(color="#DC2626", width=2),
        ))
        _wf_fig.add_hline(y=_wf_i_peak_sym, line=dict(color="#94A3B8", width=1, dash="dot"), annotation_text="Steady-state peak")
        _wf_fig.add_hline(y=-_wf_i_peak_sym, line=dict(color="#94A3B8", width=1, dash="dot"))
        _wf_fig.update_layout(
            xaxis_title="Time (ms, t=0 is fault inception)", yaxis_title="Instantaneous Current (A)",
            template="plotly_white", height=320, margin=dict(t=20, b=40),
        )
        st.plotly_chart(_wf_fig, use_container_width=True, key=f"{selected_preset}__fault_waveform_fig")

        st.markdown("---")
        st.markdown("#### Fault Clearing Time Simulation")
        st.caption(
            "Feeds the fault current above through the same trip logic as the Simulate & Test "
            "tab, then adds typical relay and breaker operating times to show how long fault current "
            "actually flows before the breaker interrupts it. Relay/breaker times below are typical "
            "values for this class of equipment (not confirmed against this transformer's own relay "
            "and breaker manuals) — adjust them if better data is available."
        )

        fault_scenario = st.radio(
            "Fault Scenario",
            ["Internal Fault (within 87AT zone)", "External Through-Fault"],
            key=f"{selected_preset}__fault_sim_scenario",
            horizontal=True,
            help=(
                f"Internal: modeled as the fault current above appearing only at the {fault_side} "
                "winding, with ~0 reaching the other winding — a large, easily-detected mismatch. "
                "This app doesn't model a separate internal-fault current for transformers, so it "
                "reuses the through-fault current computed above as a stand-in magnitude — treat "
                "this as illustrative, not a verified worst-case internal-fault study. External: the "
                "same current passes through both windings (properly turns-ratio referred), so a "
                "healthy 87AT should NOT operate — it's outside this differential zone's job to "
                "clear it."
            ),
        )

        fc_t1, fc_t2 = st.columns(2)
        with fc_t1:
            relay_operate_cycles = st.number_input(
                "Relay Operate Time (cycles)", min_value=0.25, max_value=10.0, value=1.5, step=0.25,
                key=f"{selected_preset}__relay_op_cycles",
                help="Time from fault inception to the relay issuing a trip signal. Microprocessor differential relays of this class are typically under 2 cycles — not a figure confirmed against this relay's own manual."
            )
        with fc_t2:
            breaker_cycles = st.number_input(
                "Breaker Interrupting Time (cycles)", min_value=1.0, max_value=15.0, value=5.0, step=0.5,
                key=f"{selected_preset}__breaker_cycles",
                help="Time from trip coil energization to fault current interruption — typical power transformer breakers are 3-5 cycles. Not confirmed against this plant's own breaker nameplate."
            )

        cycle_ms = 1000.0 / 60.0
        preload_ms = 40.0
        preload_current = relay.windings[0]["i_rated_pri"]
        fault_idx = 0 if fault_side == "HV" else 1
        other_idx = 1 - fault_idx

        winding_inputs = [(0.0, 0.0) for _ in relay.windings]
        winding_inputs[fault_idx] = (fault_calc["i_asym_amps"], 0.0)
        if fault_scenario.startswith("External"):
            other_rated = relay.windings[other_idx]["i_rated_pri"]
            fault_rated = relay.windings[fault_idx]["i_rated_pri"]
            ref_mult = fault_calc["i_asym_amps"] / fault_rated if fault_rated > 0 else 0.0
            other_amps = ref_mult * other_rated
            other_angle = solve_healthy_target_angle(relay, other_idx, fault_idx, fault_calc["i_asym_amps"], 0.0)
            winding_inputs[other_idx] = (other_amps, other_angle)

        sim_eval = relay.evaluate_protection(winding_inputs)
        sim_current_primary = fault_calc["i_asym_amps"]

        def _fault_sim_base_fig():
            fig = go.Figure()
            fig.update_layout(
                xaxis_title="Time (ms, t=0 is fault inception)", yaxis_title="Primary Current (A)",
                template="plotly_white", height=340, margin=dict(t=20, b=40),
            )
            return fig

        run_sim = st.button(
            "▶ Run Fault Simulation", key=f"{selected_preset}__run_fault_sim",
            help="Plays back the fault step by step: current spikes, the relay detects it, then the trip signal reaches the breaker."
        )
        sim_caption_ph = st.empty()
        sim_chart_ph = st.empty()
        done_key = f"{selected_preset}__fault_sim_last"

        if run_sim:
            if sim_eval["is_trip"]:
                relay_ms = relay_operate_cycles * cycle_ms
                total_ms = relay_ms + breaker_cycles * cycle_ms

                sim_caption_ph.warning(f"⚡ Fault occurs at t=0 — current spikes to {sim_current_primary:,.0f} A primary.")
                fig1 = _fault_sim_base_fig()
                fig1.add_trace(go.Scatter(
                    x=[-preload_ms, 0, 0], y=[preload_current, preload_current, sim_current_primary],
                    mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
                ))
                sim_chart_ph.plotly_chart(fig1, use_container_width=True, key=f"{selected_preset}__fault_sim_f1")
                time.sleep(0.9)

                sim_caption_ph.warning(f"🔍 Relay detects the fault and issues a trip signal at t={relay_ms:.0f} ms — {sim_eval['status']}.")
                fig2 = _fault_sim_base_fig()
                fig2.add_trace(go.Scatter(
                    x=[-preload_ms, 0, 0, relay_ms], y=[preload_current, preload_current, sim_current_primary, sim_current_primary],
                    mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
                ))
                fig2.add_vline(x=relay_ms, line=dict(color="#F59E0B", width=2, dash="dot"), annotation_text="Relay Trips")
                sim_chart_ph.plotly_chart(fig2, use_container_width=True, key=f"{selected_preset}__fault_sim_f2")
                time.sleep(0.9)

                sim_caption_ph.success(f"✅ Trip signal reaches the breaker — it interrupts the fault at t={total_ms:.0f} ms. Total clearing time: {total_ms:.0f} ms ({total_ms / cycle_ms:.1f} cycles).")
                fig3 = _fault_sim_base_fig()
                fig3.add_trace(go.Scatter(
                    x=[-preload_ms, 0, 0, total_ms, total_ms, total_ms + 40.0],
                    y=[preload_current, preload_current, sim_current_primary, sim_current_primary, 0.0, 0.0],
                    mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
                ))
                fig3.add_vline(x=relay_ms, line=dict(color="#F59E0B", width=2, dash="dot"), annotation_text="Relay Trips")
                fig3.add_vline(x=total_ms, line=dict(color="#16A34A", width=2, dash="dash"), annotation_text="Breaker Clears")
                sim_chart_ph.plotly_chart(fig3, use_container_width=True, key=f"{selected_preset}__fault_sim_f3")

                st.session_state[done_key] = {
                    "kind": "trip", "status": sim_eval["status"], "relay_ms": relay_ms, "total_ms": total_ms,
                    "sim_current_primary": sim_current_primary, "preload_current": preload_current,
                }
            else:
                window_ms = 200.0
                sim_caption_ph.warning(f"⚡ Fault occurs at t=0 — current rises to {sim_current_primary:,.0f} A primary.")
                fig1 = _fault_sim_base_fig()
                fig1.add_trace(go.Scatter(
                    x=[-preload_ms, 0, 0], y=[preload_current, preload_current, sim_current_primary],
                    mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
                ))
                sim_chart_ph.plotly_chart(fig1, use_container_width=True, key=f"{selected_preset}__fault_sim_f1n")
                time.sleep(0.9)

                if fault_scenario.startswith("External"):
                    sim_caption_ph.info("🛡️ Relay checks the fault — operate current stays at zero. 87AT correctly stays SECURE; clearing this through-fault is outside its zone.")
                else:
                    sim_caption_ph.info("🛡️ Relay checks the fault — current stays below the trip threshold at the settings above. No trip.")
                fig2 = _fault_sim_base_fig()
                fig2.add_trace(go.Scatter(
                    x=[-preload_ms, 0, 0, window_ms], y=[preload_current, preload_current, sim_current_primary, sim_current_primary],
                    mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
                ))
                sim_chart_ph.plotly_chart(fig2, use_container_width=True, key=f"{selected_preset}__fault_sim_f2n")

                st.session_state[done_key] = {
                    "kind": "no_trip", "status": sim_eval["status"], "window_ms": window_ms,
                    "sim_current_primary": sim_current_primary, "preload_current": preload_current,
                }
        else:
            last = st.session_state.get(done_key)
            if last is None:
                sim_caption_ph.caption("Click **Run Fault Simulation** to watch the fault current spike, the relay detect it, and the breaker clear it, step by step.")
            elif last["kind"] == "trip":
                sim_caption_ph.success(f"Last run: {last['status']} — total clearing time {last['total_ms']:.0f} ms ({last['total_ms'] / cycle_ms:.1f} cycles).")
                fig_last = _fault_sim_base_fig()
                fig_last.add_trace(go.Scatter(
                    x=[-preload_ms, 0, 0, last["total_ms"], last["total_ms"], last["total_ms"] + 40.0],
                    y=[last["preload_current"], last["preload_current"], last["sim_current_primary"], last["sim_current_primary"], 0.0, 0.0],
                    mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
                ))
                fig_last.add_vline(x=last["relay_ms"], line=dict(color="#F59E0B", width=2, dash="dot"), annotation_text="Relay Trips")
                fig_last.add_vline(x=last["total_ms"], line=dict(color="#16A34A", width=2, dash="dash"), annotation_text="Breaker Clears")
                sim_chart_ph.plotly_chart(fig_last, use_container_width=True, key=f"{selected_preset}__fault_sim_last_fig")
            else:
                sim_caption_ph.info(f"Last run: {last['status']} — no trip.")
                fig_last = _fault_sim_base_fig()
                fig_last.add_trace(go.Scatter(
                    x=[-preload_ms, 0, 0, last["window_ms"]],
                    y=[last["preload_current"], last["preload_current"], last["sim_current_primary"], last["sim_current_primary"]],
                    mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
                ))
                sim_chart_ph.plotly_chart(fig_last, use_container_width=True, key=f"{selected_preset}__fault_sim_last_fig")

    # ---------------------------------------------------------------------------
    # TAB — Settings Summary & Approval
    # ---------------------------------------------------------------------------
    with tab_approval:
        st.subheader("Settings Summary & Approval Record")
        st.caption(
            "Record the settings basis and review status before exporting a controlled report. "
            "This record supports engineering review; it does not replace the approved protection study."
        )

        st.session_state.setdefault("uat_source_document", "Transformer Diff Setting - UAT.pdf")
        st.session_state.setdefault("uat_revision", "Rev. 0")
        st.session_state.setdefault("uat_prepared_by", "")
        st.session_state.setdefault("uat_reviewed_by", "")
        st.session_state.setdefault("uat_approval_status", "Draft — engineering review required")
        st.session_state.setdefault("uat_review_note", "")

        source_document = st.text_input("Source document", key="uat_source_document")
        col_doc_1, col_doc_2 = st.columns(2)
        with col_doc_1:
            revision = st.text_input("Document / settings revision", key="uat_revision")
            prepared_by = st.text_input("Prepared by", key="uat_prepared_by")
        with col_doc_2:
            reviewed_by = st.text_input("Reviewed by", key="uat_reviewed_by")
            approval_status = st.selectbox(
                "Review status",
                ["Draft — engineering review required", "Reviewed — pending approval", "Approved for issue"],
                key="uat_approval_status",
            )
        review_note = st.text_area("Review note / change description", key="uat_review_note")

        st.markdown("---")
        pdf_bytes = generate_transformer_pdf_report(selected_preset, relay, evals, phases, winding_currents=winding_currents)
        st.download_button(
            label="Export Certified Protection Audit Report",
            data=pdf_bytes,
            file_name=f"UAT_Differential_Protection_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf"
        )

        render_settings_sheet(st, "CAC1-10-M3", [
            ("HV CT Ratio", f"{ct_hv:.0f}:{ct_secondary_rating:.0f}"),
            ("LV CT Ratio", f"{ct_lv:.0f}:{ct_secondary_rating:.0f}"),
            ("T1 (HV Tap)", f"{tap_hv:.3f}"),
            ("T2 (LV Tap)", f"{tap_lv:.3f}"),
            ("Bias, τ (%)", f"{bias_pct:.0f}"),
            ("Minimum Operate (%)", f"{min_operate_pct:.0f}"),
            ("HOC (x tap current)", f"{hoc_multiple:.2f}"),
            ("Restraint Standard", convention),
            ("CT Polarity Reference", ct_polarity),
        ], key_prefix="UAT")

        st.markdown("---")
        st.markdown("#### Save Profile")
        st.caption(
            "Name and download every setting currently active under the selected preset above — "
            "most useful after entering your own values under Custom Profile, so you can pick this "
            "file back up next time instead of re-typing everything. Use the loader in the sidebar "
            "to restore it later."
        )
        export_profile_button(
            st, "aux", f"{selected_preset}__",
            default_name="UAT Profile", button_key="aux",
        )
