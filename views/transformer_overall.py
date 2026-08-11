import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common.pdf_report import generate_transformer_pdf_report
from common.concepts import render_theory_tab
from common.sld import overall_zone_svg
from common.ui_helpers import slider_with_exact_input, MR_CT_TAPS_2000_5, sidebar_section_nav, equipment_switcher
from common.settings_advisor import suggest_ct_matching_tap, mismatch_ratio_pct, suggest_bias_settings
from common.project_state import with_restored_preset, record_equipment_settings
from common.historian import render_historian_overlay
from common.profile_io import export_profile_button, restore_profile_uploader
from common.test_point_input import TEST_POINT_SOURCE_OPTIONS, TEST_POINT_SOURCE_HELP, raw_current_inputs
from engines.transformer import TransformerDifferentialRelay, winding_internal_vector, raw_input_for_internal_vector, solve_healthy_target_angle

st.title("Overall GSUT-GEN Differential Protection")
st.caption(
    "Backup differential zone covering Generator + GSUT + Unit Auxiliary Transformer — "
    "CAC2-10-M3 three-restraint percentage-bias differential relay (Mitsubishi, 3-winding)."
)

# ---------------------------------------------------------------------------
# Presets — from Transformer_Diff_Setting_-_Overall_GSUT-GEN.pdf, Section 5.10
# (Relays 87OA7 / 87OA8, Setting Summary + Calculation/Discussion). Relay
# currents are calculated assuming each device carries the full 873.6 MVA
# rating of the Generator Step-Up Transformer.
# ---------------------------------------------------------------------------
PRESETS = {
    "POMI Overall 87OA7/87OA8 - 873.6 MVA base": {
        "mva": 873.6,
        "kv_hv": 538.125, "kv_gen": 23.0, "kv_uat": 23.0,
        "ct_hv": 1600, "ct_gen": 24000, "ct_uat": 24000, "ct_sec": 5.0,
        "ct_conn_hv": "DELTA", "ct_conn_gen": "WYE", "ct_conn_uat": "WYE",
        "tap_hv": 1.0, "tap_gen": 1.1, "tap_uat": 1.1,
        "bias": 30, "min_operate": 30, "hoc": 5,
    },
    "Custom Profile": {
        "mva": 10.0,
        "kv_hv": 11.0, "kv_gen": 11.0, "kv_uat": 11.0,
        "ct_hv": 100, "ct_gen": 100, "ct_uat": 100, "ct_sec": 5.0,
        "ct_conn_hv": "WYE", "ct_conn_gen": "WYE", "ct_conn_uat": "WYE",
        "tap_hv": 1.0, "tap_gen": 1.0, "tap_uat": 1.0,
        "bias": 30, "min_operate": 30, "hoc": 5,
    },
}

PRESETS_WITH_PROJECT = with_restored_preset(PRESETS, "overall")
equipment_switcher("views/transformer_overall.py")
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

restore_profile_uploader(st.sidebar, "overall", f"{selected_preset}__", "overall")

if not is_custom:
    st.success(
        "✓ **Data confidence:** Differential settings (Bias/Min Operate/HOC/CT ratios/taps for "
        "all 3 windings) are verified against this backup zone's own settings document."
    )

# ---------------------------------------------------------------------------
# CURRENT SETTINGS — every applied setting, editable in place, with a live
# comment on whether an adjustment improves or weakens protection. Comments
# reuse the exact same functions as the old sidebar "Settings Calculator" (no
# new engineering judgment invented) - just surfaced inline per-field. Taps
# are shown against their individual T_E only as a reference (informational),
# not a pass/fail check - same reasoning as EXCT/GSUT: taps are chosen
# JOINTLY to minimize the actual 3-way mismatch, not to each independently
# match their own T_E, so the mismatch metric below is the real signal.
# ---------------------------------------------------------------------------
sections = ["Current Settings", "Settings Calculator", "Theory", "Simulate & Test", "Commissioning & Injection Tool", "Settings Summary & Approval"]
selected, c, pinned = sidebar_section_nav(sections, key_prefix="overall", pin_first=True)

with c["Current Settings"]:
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
        help="Reflects the Bias/Minimum Operate settings below as you adjust them. The HOC line and operating-point testing are in the Simulate & Test section (sidebar).",
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
        st.plotly_chart(_pv_fig, use_container_width=True, key="overall_settings_preview_fig")
    st.markdown("---")

    st.markdown("## Current Settings")
    st.caption("Every setting currently applied to this relay. Adjust a value below and the comment beside it updates live.")

    with st.container(border=True):
        st.markdown("**Ratings and CT**")
        mva = st.number_input(
            "Base Rating (MVA)", value=p_data["mva"], step=10.0, key=f"{selected_preset}__mva",
            help="Relay currents are calculated assuming each device carries the full rating of the "
                 "Generator Step-Up Transformer (per the settings doc's Calculation/Discussion)."
        )
        r1c1, r1c2, r1c3 = st.columns(3)
        with r1c1:
            st.markdown("**Winding 1 — HV (525kV)**" if not is_custom else "**Winding 1 — HV**")
            kv_hv = st.number_input("HV Rated Voltage (kV)", value=p_data["kv_hv"], step=1.0, format="%.3f",
                key=f"{selected_preset}__kv_hv",
                help="Uses the center-of-tap-range voltage (538.125kV) per the settings doc's full-load calc, not the 525kV nameplate.")
            if is_custom:
                ct_hv = st.number_input("HV CT Ratio (Primary A, e.g. 100 in '100:5')", value=float(p_data["ct_hv"]), key=f"{selected_preset}__ct_hv")
            else:
                ct_hv = st.select_slider(
                    "HV CT Ratio Tap (Multi-Ratio, Primary A)", options=MR_CT_TAPS_2000_5,
                    value=p_data["ct_hv"] if p_data["ct_hv"] in MR_CT_TAPS_2000_5 else 1600,
                    key=f"{selected_preset}__ct_hv",
                    help="Same 2000:5 Delta-connected multi-ratio bushing CT as the GSUT page (it's the same "
                         "physical CT feeding both relays) — documented as set on 1600:5."
                )
            ct_conn_hv = st.selectbox("HV CT Connection", ["DELTA", "WYE"], index=0 if p_data["ct_conn_hv"] == "DELTA" else 1, key=f"{selected_preset}__ct_conn_hv")
        with r1c2:
            st.markdown("**Winding 2 — Generator (23kV)**" if not is_custom else "**Winding 2 — Generator**")
            kv_gen = st.number_input("Generator Rated Voltage (kV)", value=p_data["kv_gen"], step=0.1, format="%.3f", key=f"{selected_preset}__kv_gen")
            ct_gen = st.number_input("Generator CT Ratio (Primary A, e.g. 24000 in '24000:5')", value=float(p_data["ct_gen"]), key=f"{selected_preset}__ct_gen")
            ct_conn_gen = st.selectbox("Generator CT Connection", ["WYE", "DELTA"], index=0 if p_data["ct_conn_gen"] == "WYE" else 1, key=f"{selected_preset}__ct_conn_gen")
        with r1c3:
            st.markdown("**Winding 3 — Unit Aux. Transformer (23kV)**" if not is_custom else "**Winding 3 — Auxiliary**")
            kv_uat = st.number_input("UAT Rated Voltage (kV)", value=p_data["kv_uat"], step=0.1, format="%.3f", key=f"{selected_preset}__kv_uat")
            ct_uat = st.number_input("UAT CT Ratio (Primary A, e.g. 24000 in '24000:5')", value=float(p_data["ct_uat"]), key=f"{selected_preset}__ct_uat")
            ct_conn_uat = st.selectbox("UAT CT Connection", ["WYE", "DELTA"], index=0 if p_data["ct_conn_uat"] == "WYE" else 1, key=f"{selected_preset}__ct_conn_uat")

        ct_secondary_rating = st.selectbox(
            "CT Secondary Rating (A)", [1.0, 5.0], index=1 if p_data["ct_sec"] == 5.0 else 0, key=f"{selected_preset}__ct_sec",
            help="The rated secondary current stamped on the CT nameplate (the '5' in 'x:5'). Applied to all three CTs."
        )
        st.caption(
            f"Effective ratio → HV: **{ct_hv/ct_secondary_rating:.1f}:1**  |  "
            f"Generator: **{ct_gen/ct_secondary_rating:.1f}:1**  |  "
            f"UAT: **{ct_uat/ct_secondary_rating:.1f}:1**"
        )

    delta_factor_hv = 1.7320508 if ct_conn_hv.upper() == "DELTA" else 1.0
    delta_factor_gen = 1.7320508 if ct_conn_gen.upper() == "DELTA" else 1.0
    delta_factor_uat = 1.7320508 if ct_conn_uat.upper() == "DELTA" else 1.0
    i_rated_pri = (mva * 1000.0) / (1.7320508 * kv_hv) if kv_hv > 0 else 0.0
    i_rated_pri_gen = (mva * 1000.0) / (1.7320508 * kv_gen) if kv_gen > 0 else 0.0
    i_rated_pri_uat = (mva * 1000.0) / (1.7320508 * kv_uat) if kv_uat > 0 else 0.0
    t1_e = suggest_ct_matching_tap(i_rated_pri, ct_hv, ct_secondary_rating, delta_factor_hv)
    t2_e = suggest_ct_matching_tap(i_rated_pri_gen, ct_gen, ct_secondary_rating, delta_factor_gen)
    t3_e = suggest_ct_matching_tap(i_rated_pri_uat, ct_uat, ct_secondary_rating, delta_factor_uat)

    with st.container(border=True):
        st.markdown("**CT Matching Taps**")
        st.caption(
            "T_E is the reference tap that would give zero mismatch if this winding were tapped alone — "
            "T1/T2/T3 are then chosen JOINTLY to minimize the actual 3-way mismatch below, not to each "
            "independently match their own T_E. The mismatch metric below is the real signal."
        )
        t1c1, t1c2, t1c3 = st.columns(3)
        with t1c1:
            tap_hv = slider_with_exact_input(
                st, "HV Tap (T1)", 0.4, 2.18, p_data["tap_hv"], 0.02,
                key=f"{selected_preset}__tap_hv",
                help_text="CAC2-10-M3 setting range: 0.4-2.18 in steps of 0.02."
            )
            if t1_e is not None:
                st.caption(f"T1_E (reference) ≈ {t1_e:.3f}")
        with t1c2:
            tap_gen = slider_with_exact_input(
                st, "Generator Tap (T2)", 0.4, 2.18, p_data["tap_gen"], 0.02,
                key=f"{selected_preset}__tap_gen",
                help_text="CAC2-10-M3 setting range: 0.4-2.18 in steps of 0.02."
            )
            if t2_e is not None:
                st.caption(f"T2_E (reference) ≈ {t2_e:.3f}")
        with t1c3:
            tap_uat = slider_with_exact_input(
                st, "UAT Tap (T3)", 0.4, 2.18, p_data["tap_uat"], 0.02,
                key=f"{selected_preset}__tap_uat",
                help_text="CAC2-10-M3 setting range: 0.4-2.18 in steps of 0.02."
            )
            if t3_e is not None:
                st.caption(f"T3_E (reference) ≈ {t3_e:.3f}")

        i_relay_hv_at_set_tap = (i_rated_pri / (ct_hv / ct_secondary_rating) * delta_factor_hv * tap_hv) if ct_hv > 0 else None
        i_relay_gen_at_set_tap = (i_rated_pri_gen / (ct_gen / ct_secondary_rating) * delta_factor_gen * tap_gen) if ct_gen > 0 else None
        i_relay_uat_at_set_tap = (i_rated_pri_uat / (ct_uat / ct_secondary_rating) * delta_factor_uat * tap_uat) if ct_uat > 0 else None
        calc_mismatch = mismatch_ratio_pct([i_relay_hv_at_set_tap, i_relay_gen_at_set_tap, i_relay_uat_at_set_tap])
        st.metric("Mismatch at currently-set taps (the actual signal)", f"{calc_mismatch:.2f}%" if calc_mismatch is not None else "—")
        if calc_mismatch is not None:
            if calc_mismatch < 5.0:
                st.success(f"{calc_mismatch:.2f}% mismatch — low, well within the usual rule-of-thumb range.")
            else:
                st.warning(f"{calc_mismatch:.2f}% mismatch — unusually high. Review the tap selection before applying.")

    suggestion = suggest_bias_settings(calc_mismatch or 0.0, num_windings=3)

    with st.container(border=True):
        st.markdown("**Differential Settings**")
        st.caption(
            f"Rule-of-thumb floor for the current {calc_mismatch:.2f}% mismatch: Bias ≈ {suggestion['bias_pct']:.0f}%, "
            f"Min Operate ≈ {suggestion['min_operate_pct']:.0f}%, HOC ≈ {suggestion['hoc_multiple']:.0f}x tap current. "
            "Engineering review required — always confirm against a real through-fault/inrush coordination study."
            if calc_mismatch is not None else
            "Set the taps above first to compute a mismatch-based floor for these settings."
        )
        d1c1, d1c2, d1c3 = st.columns(3)
        with d1c1:
            bias_pct = slider_with_exact_input(
                st, "Bias, τ (%)", 20, 40, p_data["bias"], 10,
                key=f"{selected_preset}__bias",
                help_text="CAC2-10-M3 available settings: 20%, 30%, or 40%."
            )
            if bias_pct >= suggestion["bias_pct"]:
                st.success(f"Clears the {suggestion['bias_pct']:.0f}% floor. Higher = more secure against nuisance trips, but less sensitive to small internal faults.")
            else:
                st.warning(f"Below the {suggestion['bias_pct']:.0f}% floor for this mismatch — raises the risk of a nuisance trip on inrush or normal mismatch current.")
        with d1c2:
            min_operate_pct = slider_with_exact_input(
                st, "Minimum Operate (%)", 20, 40, p_data["min_operate"], 10,
                key=f"{selected_preset}__min_operate",
                help_text="CAC2-10-M3 available settings: IT x 20%, 30%, or 40% (IT = tap value current)."
            )
            if min_operate_pct >= suggestion["min_operate_pct"]:
                st.success(f"Clears the {suggestion['min_operate_pct']:.0f}% floor — secure against CT/relay noise at light load.")
            else:
                st.warning(f"Below the {suggestion['min_operate_pct']:.0f}% floor — more sensitive to light internal faults, but more exposed to false operation from CT noise/tap mismatch.")
        with d1c3:
            hoc_options = [5, 6, 8, 10, 12]
            hoc_multiple = st.select_slider(
                "HOC (x tap value current)", options=hoc_options,
                value=p_data["hoc"] if p_data["hoc"] in hoc_options else 5,
                key=f"{selected_preset}__hoc",
                help="CAC2-10-M3 available settings: 5, 6, 8, 10, or 12 times tap value current. Not "
                     "harmonically restrained — operates on differential current only, so LV-side faults won't trip it."
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
        st.info("Overall status: set the taps above to compute a status.")
    elif all_clear:
        st.success("Overall status: all settings shown clear their recommended margins. Engineering approval is still required before issue.")
    else:
        st.warning("Overall status: one or more settings above need review before this is applied.")


windings = [
    {"name": "HV (525kV)", "kv": kv_hv, "ct_ratio": ct_hv, "ct_secondary_rating": ct_secondary_rating, "tap": tap_hv, "ct_connection": ct_conn_hv},
    {"name": "Generator (23kV)", "kv": kv_gen, "ct_ratio": ct_gen, "ct_secondary_rating": ct_secondary_rating, "tap": tap_gen, "ct_connection": ct_conn_gen},
    {"name": "UAT (23kV)", "kv": kv_uat, "ct_ratio": ct_uat, "ct_secondary_rating": ct_secondary_rating, "tap": tap_uat, "ct_connection": ct_conn_uat},
]
record_equipment_settings("overall", {
    "mva": mva, "kv_hv": kv_hv, "kv_gen": kv_gen, "kv_uat": kv_uat,
    "ct_hv": ct_hv, "ct_gen": ct_gen, "ct_uat": ct_uat, "ct_sec": ct_secondary_rating,
    "ct_conn_hv": ct_conn_hv, "ct_conn_gen": ct_conn_gen, "ct_conn_uat": ct_conn_uat,
    "tap_hv": tap_hv, "tap_gen": tap_gen, "tap_uat": tap_uat,
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
winding_names = ["HV (525kV)", "Generator (23kV)", "UAT (23kV)"]
amps_base = relay.windings[0]["i_rated_sec"]  # HV-side rated secondary current, used as pu base for charts

with c["Settings Calculator"]:
    st.caption(
        "Enter equipment ratings and CT data below to get a suggested settings sheet — a "
        "starting point, not a substitute for a coordination study. Prefilled from Current "
        "Settings, but independent of it: change a value here to test a scenario without "
        "touching your actual settings."
    )
    with st.container(border=True):
        st.markdown("**Ratings and CT**")
        calc_mva = st.number_input("Base Rating (MVA)", min_value=0.1, value=float(mva), step=1.0, key="overall_calc_mva")
        calc_ct_sec = st.number_input("CT Secondary Rating (A)", min_value=1.0, value=float(ct_secondary_rating), step=1.0, key="overall_calc_ct_sec")
        ocalc1, ocalc2, ocalc3 = st.columns(3)
        with ocalc1:
            st.markdown("HV Winding")
            calc_kv_hv = st.number_input("HV Rated Voltage (kV)", min_value=0.1, value=float(kv_hv), step=1.0, key="overall_calc_kv_hv")
            calc_ct_hv = st.number_input("HV CT Ratio (Primary A)", min_value=1.0, value=float(ct_hv), step=1.0, key="overall_calc_ct_hv")
            calc_conn_hv = st.selectbox("HV CT Connection", ["DELTA", "WYE"], index=0 if ct_conn_hv.upper() == "DELTA" else 1, key="overall_calc_conn_hv")
            calc_tap_hv = st.number_input("HV Tap (as set)", min_value=0.1, value=float(tap_hv), step=0.01, key="overall_calc_tap_hv")
        with ocalc2:
            st.markdown("Generator Winding")
            calc_kv_gen = st.number_input("Generator Rated Voltage (kV)", min_value=0.1, value=float(kv_gen), step=1.0, key="overall_calc_kv_gen")
            calc_ct_gen = st.number_input("Generator CT Ratio (Primary A)", min_value=1.0, value=float(ct_gen), step=1.0, key="overall_calc_ct_gen")
            calc_conn_gen = st.selectbox("Generator CT Connection", ["DELTA", "WYE"], index=0 if ct_conn_gen.upper() == "DELTA" else 1, key="overall_calc_conn_gen")
            calc_tap_gen = st.number_input("Generator Tap (as set)", min_value=0.1, value=float(tap_gen), step=0.01, key="overall_calc_tap_gen")
        with ocalc3:
            st.markdown("UAT Winding")
            calc_kv_uat = st.number_input("UAT Rated Voltage (kV)", min_value=0.1, value=float(kv_uat), step=1.0, key="overall_calc_kv_uat")
            calc_ct_uat = st.number_input("UAT CT Ratio (Primary A)", min_value=1.0, value=float(ct_uat), step=1.0, key="overall_calc_ct_uat")
            calc_conn_uat = st.selectbox("UAT CT Connection", ["DELTA", "WYE"], index=0 if ct_conn_uat.upper() == "DELTA" else 1, key="overall_calc_conn_uat")
            calc_tap_uat = st.number_input("UAT Tap (as set)", min_value=0.1, value=float(tap_uat), step=0.01, key="overall_calc_tap_uat")

        calc_delta_hv = 1.7320508 if calc_conn_hv == "DELTA" else 1.0
        calc_delta_gen = 1.7320508 if calc_conn_gen == "DELTA" else 1.0
        calc_delta_uat = 1.7320508 if calc_conn_uat == "DELTA" else 1.0
        calc_i_pri_hv = (calc_mva * 1000.0) / (1.7320508 * calc_kv_hv) if calc_kv_hv > 0 else 0.0
        calc_i_pri_gen = (calc_mva * 1000.0) / (1.7320508 * calc_kv_gen) if calc_kv_gen > 0 else 0.0
        calc_i_pri_uat = (calc_mva * 1000.0) / (1.7320508 * calc_kv_uat) if calc_kv_uat > 0 else 0.0
        calc_t1_e = suggest_ct_matching_tap(calc_i_pri_hv, calc_ct_hv, calc_ct_sec, calc_delta_hv)
        calc_t2_e = suggest_ct_matching_tap(calc_i_pri_gen, calc_ct_gen, calc_ct_sec, calc_delta_gen)
        calc_t3_e = suggest_ct_matching_tap(calc_i_pri_uat, calc_ct_uat, calc_ct_sec, calc_delta_uat)
        calc_i_relay_hv = (calc_i_pri_hv / (calc_ct_hv / calc_ct_sec) * calc_delta_hv * calc_tap_hv) if calc_ct_hv > 0 else None
        calc_i_relay_gen = (calc_i_pri_gen / (calc_ct_gen / calc_ct_sec) * calc_delta_gen * calc_tap_gen) if calc_ct_gen > 0 else None
        calc_i_relay_uat = (calc_i_pri_uat / (calc_ct_uat / calc_ct_sec) * calc_delta_uat * calc_tap_uat) if calc_ct_uat > 0 else None
        calc_mismatch_overall = mismatch_ratio_pct([calc_i_relay_hv, calc_i_relay_gen, calc_i_relay_uat])
        st.metric("Mismatch at entered taps", f"{calc_mismatch_overall:.2f}%" if calc_mismatch_overall is not None else "—")

    calc_suggestion = suggest_bias_settings(calc_mismatch_overall or 0.0, num_windings=3)

    tcalc1, tcalc2, tcalc3 = st.columns(3)
    with tcalc1:
        with st.container(border=True):
            st.markdown("#### HV Tap (T1_E)")
            st.metric("Suggested", f"{calc_t1_e:.3f}" if calc_t1_e is not None else "—")
    with tcalc2:
        with st.container(border=True):
            st.markdown("#### Generator Tap (T2_E)")
            st.metric("Suggested", f"{calc_t2_e:.3f}" if calc_t2_e is not None else "—")
    with tcalc3:
        with st.container(border=True):
            st.markdown("#### UAT Tap (T3_E)")
            st.metric("Suggested", f"{calc_t3_e:.3f}" if calc_t3_e is not None else "—")
    st.caption("Ideal (unrounded) CT-matching tap for each winding at rated load — round to the nearest tap your relay's settings software offers.")

    bcalc1, bcalc2, bcalc3 = st.columns(3)
    with bcalc1:
        with st.container(border=True):
            st.markdown("#### Bias")
            st.metric("Suggested", f"{calc_suggestion['bias_pct']:.0f} %")
    with bcalc2:
        with st.container(border=True):
            st.markdown("#### Min Operate")
            st.metric("Suggested", f"{calc_suggestion['min_operate_pct']:.0f} %")
    with bcalc3:
        with st.container(border=True):
            st.markdown("#### HOC")
            st.metric("Suggested", f"{calc_suggestion['hoc_multiple']:.0f}x tap current")
    st.caption(calc_suggestion["basis"])

with c["Theory"]:
    render_theory_tab(
        "transformer_3w",
        purpose_text=(
            "The 87O relay is a backup differential zone spanning the Generator, GSUT, and the "
            "Unit Auxiliary Transformer tap-off together. It exists because the individual 87G "
            "and 87GT zones don't cover everything — the short bus and leads connecting them, and "
            "the point where UAT taps off, aren't uniquely protected by either dedicated relay. "
            "87O catches a fault anywhere in that gap, or backs up the dedicated relays if "
            "something in their own CTs or wiring fails, rather than depending entirely on remote/"
            "upstream protection to eventually clear it."
        ),
        sld_image_name="overall.png",
        sld_fallback_svg=overall_zone_svg(relay, ct_polarity, tag="87OA/87OB"),
    )

# ---------------------------------------------------------------------------
# TAB — Simulate & Test
# ---------------------------------------------------------------------------
with c["Simulate & Test"]:
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
            convention = st.radio("Restraint Standard", ["IEEE", "IEC"], help="IEEE: Average current. IEC: Arithmetic sum.", key="ov_convention")
        with col_pol:
            def _on_polarity_change():
                # Streamlit widgets stop re-reading their value= argument once
                # created, so recomputing the healthy default inline on every
                # rerun (below, for Phase A) only ever applies on first page
                # load - switching this radio afterwards needs to explicitly
                # overwrite session_state here, or the Generator angle goes
                # stale and a healthy through-load starts reading as a phantom
                # trip. UAT stays at 0A by default regardless, so only the
                # Generator winding (vs. HV) needs solving here.
                new_polarity = st.session_state["ov_ct_polarity"]
                windings_tmp = [
                    {"name": "HV", "kv": kv_hv, "ct_ratio": ct_hv, "ct_secondary_rating": ct_secondary_rating, "tap": tap_hv, "ct_connection": ct_conn_hv},
                    {"name": "Generator", "kv": kv_gen, "ct_ratio": ct_gen, "ct_secondary_rating": ct_secondary_rating, "tap": tap_gen, "ct_connection": ct_conn_gen},
                    {"name": "UAT", "kv": kv_uat, "ct_ratio": ct_uat, "ct_secondary_rating": ct_secondary_rating, "tap": tap_uat, "ct_connection": ct_conn_uat},
                ]
                relay_tmp = TransformerDifferentialRelay(
                    mva_rated=mva, windings=windings_tmp,
                    bias_pct=30, min_operate_pct=30, hoc_multiple=5,
                    convention="IEEE", ct_polarity=new_polarity,
                )
                hv_rated = relay_tmp.windings[0]["i_rated_pri"]
                st.session_state["ov_gen_a_Phase A"] = solve_healthy_target_angle(relay_tmp, 1, 0, hv_rated, 0.0)

            ct_polarity = st.radio(
                "Polarity Reference", ["OPPOSITE", "SAME"], index=0, key="ov_ct_polarity",
                on_change=_on_polarity_change,
                help="OPPOSITE: HV (Winding 1) is the reference; Generator and UAT windings are flipped "
                     "relative to it, as current flows into the zone from HV and out to the other two."
            )

    # Rebuilds `relay` with the real Wiring & Convention selection above, replacing the
    # placeholder built earlier (before this tab ran) for the Theory tab's SLD. Every tab
    # after this one in script order (Commissioning, TCC Curve, Settings Summary & Approval)
    # sees this rebuilt object too.
    relay = TransformerDifferentialRelay(
        mva_rated=mva, windings=windings,
        bias_pct=bias_pct, min_operate_pct=min_operate_pct, hoc_multiple=hoc_multiple,
        convention=convention, ct_polarity=ct_polarity,
    )

    col_inputs, col_results = st.columns([1.3, 1.0])

    with col_inputs:
        st.subheader("Winding Operating Phase Inputs")
        st.caption(
            "Enter the actual PRIMARY-side current in Amps for each of the three windings — "
            "the app converts this through the CT ratio and matching tap automatically."
        )
        st.info(
            f"HV Rated: **{relay.windings[0]['i_rated_pri']:.1f} A**  |  "
            f"Generator Rated: **{relay.windings[1]['i_rated_pri']:.1f} A**  |  "
            f"UAT Rated: **{relay.windings[2]['i_rated_pri']:.1f} A**"
        )

        inputs = {}
        for idx, phase in enumerate(phases):
            with st.expander(f"{phase} Settings", expanded=(phase == "Phase A")):
                c1, c2, c3 = st.columns(3)
                def_ang_hv = -120.0 * idx
                # Same sign convention as the Phase A Generator solve below (harmless
                # here since magnitude is 0 for Phase B/C and for UAT always, but was
                # backwards - matches the Generator page's fixed bug: OPPOSITE needs
                # matching angles to cancel, SAME needs 180 deg apart).
                def_ang_other = def_ang_hv if ct_polarity == "OPPOSITE" else def_ang_hv + 180.0
                def_val_uat = 0.0  # UAT typically carries house-load current, not full rating, by default
                if phase == "Phase A":
                    def_val_hv = relay.windings[0]["i_rated_pri"]
                    def_val_gen = relay.windings[1]["i_rated_pri"]
                    # Solve only the ANGLE that makes a healthy through-load (with
                    # UAT off-load, i.e. 0A by default, so HV and Generator alone
                    # must cancel) net to ~0 pu, accounting for HV's Delta CT
                    # compensation - not just a naive +-180 degree guess. Magnitude
                    # is left at Generator's own Nominal Rated Current (matching the
                    # info box above) rather than solved-for, so a small residual is
                    # expected and correct, not a bug.
                    vec_hv_internal = winding_internal_vector(relay, 0, def_val_hv, def_ang_hv)
                    target_gen_internal = vec_hv_internal if ct_polarity == "OPPOSITE" else -vec_hv_internal
                    _, def_ang_gen = raw_input_for_internal_vector(relay, 1, target_gen_internal)
                else:
                    def_val_hv = 0.0
                    def_val_gen = 0.0
                    def_ang_gen = def_ang_other

                with c1:
                    st.markdown("**HV**")
                    i_hv = st.number_input("Primary Amps [A]", value=def_val_hv, key=f"ov_hv_i_{phase}")
                    a_hv = st.number_input("Angle (°)", value=def_ang_hv, key=f"ov_hv_a_{phase}")
                with c2:
                    st.markdown("**Generator**")
                    i_gen = st.number_input("Primary Amps [A]", value=def_val_gen, key=f"ov_gen_i_{phase}")
                    a_gen = st.number_input("Angle (°)", value=def_ang_gen, key=f"ov_gen_a_{phase}")
                with c3:
                    st.markdown("**UAT**")
                    i_uat = st.number_input("Primary Amps [A]", value=def_val_uat, key=f"ov_uat_i_{phase}")
                    a_uat = st.number_input("Angle (°)", value=def_ang_other, key=f"ov_uat_a_{phase}")

                inputs[phase] = {"i_hv": i_hv, "a_hv": a_hv, "i_gen": i_gen, "a_gen": a_gen, "i_uat": i_uat, "a_uat": a_uat}

        evals = {p: relay.evaluate_protection([
            (inputs[p]["i_hv"], inputs[p]["a_hv"]),
            (inputs[p]["i_gen"], inputs[p]["a_gen"]),
            (inputs[p]["i_uat"], inputs[p]["a_uat"]),
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

        with st.expander("Per-winding magnitudes (pu)"):
            for p in phases:
                mags = evals[p]["winding_mags_pu"]
                st.caption(f"**{p}**: " + " | ".join(f"{n}: {m:.3f} pu" for n, m in zip(winding_names, mags)))
        st.caption("The Relay-Ready Settings Sheet, settings export, and a certified audit report are in the Settings Summary & Approval tab.")
        winding_currents = {p: [inputs[p]["i_hv"], inputs[p]["i_gen"], inputs[p]["i_uat"]] for p in phases}

    st.subheader("Differential Bias Characteristic Curve")

    chart_units = st.radio(
        "Chart units", ["Per-Unit (pu)", "Secondary Amps (A)"], horizontal=True, key="ov_live_chart_units",
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
        title="Overall GSUT-GEN Differential Bias Characteristic",
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

    if "ov_manual_test_points" not in st.session_state:
        st.session_state.ov_manual_test_points = []

    tp_source = st.radio(
        "How was this measured?", TEST_POINT_SOURCE_OPTIONS, horizontal=True,
        key="ov_tp_source", help=TEST_POINT_SOURCE_HELP,
    )
    with st.form("ov_add_test_point_form", clear_on_submit=True):
        tp_phase = st.selectbox("Phase", ["Phase A", "Phase B", "Phase C", "Other"], key="ov_tp_phase")
        if tp_source.startswith("Restraint"):
            tp_unit = st.radio(
                "Entry units", ["Secondary Amps (A)", "Per-Unit (pu)"], horizontal=True, key="ov_tp_entry_unit"
            )
            tc2, tc3 = st.columns(2)
            restraint_label = "Restraint Current" if tp_unit.startswith("Secondary") else "Restraint Current (pu)"
            diff_label = "Measured Diff. Current" if tp_unit.startswith("Secondary") else "Measured Diff. Current (pu)"
            restraint_step = 0.1 if tp_unit.startswith("Secondary") else 0.05
            diff_step = 0.05 if tp_unit.startswith("Secondary") else 0.01
            restraint_default = 1.0 if tp_unit.startswith("Secondary") else 0.3
            diff_default = 0.3 if tp_unit.startswith("Secondary") else 0.06
            with tc2:
                tp_restraint = st.number_input(restraint_label, min_value=0.0, value=restraint_default, step=restraint_step, key="ov_tp_restraint")
            with tc3:
                tp_diff = st.number_input(diff_label, min_value=0.0, value=diff_default, step=diff_step, key="ov_tp_diff")
        else:
            st.caption("Enter the actual primary Amps and phase angle measured/injected at each winding's CT.")
            raw_inputs = raw_current_inputs(
                ["HV", "Gen", "UAT"], "ov_tp_raw",
                default_primary_amps=[w["i_rated_pri"] for w in relay.windings],
            )
        tp_label = st.text_input("Label (optional)", value="", key="ov_tp_label")
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
            st.session_state.ov_manual_test_points.append({
                "Phase": tp_phase,
                "Restraint (A)": round(restraint_amps, 3),
                "Measured Diff (A)": round(diff_amps, 3),
                "Label": tp_label
            })

    if st.session_state.ov_manual_test_points:
        table_unit = st.radio("Display units for table", ["Secondary Amps (A)", "Per-Unit (pu)"], horizontal=True, key="ov_tp_table_unit")
        table_in_pu = table_unit.startswith("Per-Unit")
        restraint_col = "Restraint (pu)" if table_in_pu else "Restraint (A)"
        diff_col = "Measured Diff (pu)" if table_in_pu else "Measured Diff (A)"

        tp_display_rows = []
        for tp in st.session_state.ov_manual_test_points:
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
                max_value=max(len(st.session_state.ov_manual_test_points) - 1, 0), value=0, step=1, key="ov_remove_idx"
            )
            if st.button("Remove Row", key="ov_remove_btn"):
                st.session_state.ov_manual_test_points.pop(int(remove_idx))
                st.rerun()
        with rc2:
            if st.button("Clear All Test Points", key="ov_clear_btn"):
                st.session_state.ov_manual_test_points = []
                st.rerun()
    else:
        st.info("No test points added yet — add some above to see them plotted below.")

    st.markdown("---")
    st.markdown("#### Differential Bias Characteristic Curve")

    comm_chart_units = st.radio("Chart units", ["Per-Unit (pu)", "Secondary Amps (A)"], horizontal=True, key="ov_test_chart_units")
    use_amps_comm = comm_chart_units == "Secondary Amps (A)"
    unit_label_comm = "A" if use_amps_comm else "pu"

    cal_source = st.radio(
        "CAL. line source",
        ["Connect my test points (commissioning report style)", "Theoretical relay characteristic"],
        horizontal=True, key="ov_cal_line_source"
    )

    sweep_fig = go.Figure()
    if cal_source.startswith("Connect") and len(st.session_state.ov_manual_test_points) >= 2:
        sorted_pts = sorted(st.session_state.ov_manual_test_points, key=lambda tp: tp["Restraint (A)"])
        cal_x_amps = [tp["Restraint (A)"] for tp in sorted_pts]
        cal_y_amps = [tp["Measured Diff (A)"] for tp in sorted_pts]
        curve_x = cal_x_amps if use_amps_comm else [x / amps_base for x in cal_x_amps]
        curve_y = cal_y_amps if use_amps_comm else [y / amps_base for y in cal_y_amps]
        sweep_fig.add_trace(go.Scatter(x=curve_x, y=curve_y, mode="lines", name="CAL.", line=dict(color="#2E8B57", width=3)))
    else:
        if cal_source.startswith("Connect"):
            st.info("Add at least 2 test points above to draw the CAL. line through them — showing the theoretical characteristic for now.")
        manual_restraints_pu = [tp["Restraint (A)"] / amps_base for tp in st.session_state.ov_manual_test_points]
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
    for tp in st.session_state.ov_manual_test_points:
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
    png_filename = f"87OA_Differential_Bias_Curve_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}"
    st.plotly_chart(sweep_fig, use_container_width=True, config={"toImageButtonOptions": {"format": "png", "filename": png_filename, "scale": 3}})

    st.markdown("---")
    render_historian_overlay(st, "overall", reference_lines=[
        ("HV Rated (A)", relay.windings[0]["i_rated_pri"]),
        ("Generator Rated (A)", relay.windings[1]["i_rated_pri"]),
        ("UAT Rated (A)", relay.windings[2]["i_rated_pri"]),
    ])

# ---------------------------------------------------------------------------
# TAB 2 — Commissioning & Injection Tool
# ---------------------------------------------------------------------------
with c["Commissioning & Injection Tool"]:
    st.subheader("Commissioning & Secondary Current Injection Assistant")
    st.write(
        "With a 3-restraint relay there's no single unique way to split a target differential "
        "across three currents, so this tool uses the standard commissioning method instead: "
        "**energize one winding at a time** (the other two at zero) and read the resulting "
        "I_op / I_rest / trip verdict straight from the relay engine — exactly how these "
        "relays are normally verified in the field."
    )

    st.markdown("#### Single-Winding Injection Test")
    inj_col1, inj_col2 = st.columns(2)
    with inj_col1:
        inj_winding_name = st.selectbox("Winding to energize", winding_names, key="ov_inj_winding")
        inj_winding_idx = winding_names.index(inj_winding_name)
    with inj_col2:
        inj_current_pu = slider_with_exact_input(
            st, "Test Current (pu of that winding's rated current)", 0.05, 20.0, 1.0, 0.05,
            key=f"{selected_preset}__ov_inj_current"
        )

    test_inputs = [(0.0, 0.0), (0.0, 0.0), (0.0, 0.0)]
    inj_primary_amps = inj_current_pu * relay.windings[inj_winding_idx]["i_rated_pri"]
    test_inputs[inj_winding_idx] = (inj_primary_amps, 0.0)
    inj_result = relay.evaluate_protection(test_inputs)

    inj_secondary_amps = inj_current_pu * relay.windings[inj_winding_idx]["i_rated_sec"]

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Inject (secondary A)", f"{inj_secondary_amps:.3f} A")
    r2.metric("I_op", f"{inj_result['i_op_pu']:.3f} pu")
    r3.metric("I_rest", f"{inj_result['i_rest_pu']:.3f} pu")
    r4.metric("Threshold", f"{inj_result['i_threshold_pu']:.3f} pu")
    if inj_result["is_trip"]:
        st.error(f"Status: {inj_result['status']}")
    else:
        st.success(f"Status: {inj_result['status']}")

    st.markdown("---")
    st.subheader("Auto-Sweep Single-Winding Test Table")
    sw1, sw2, sw3 = st.columns(3)
    with sw1:
        sweep_start = st.number_input("Sweep Start (pu)", value=0.2, min_value=0.0, step=0.1, key="ov_sweep_start")
    with sw2:
        sweep_end = st.number_input("Sweep End (pu)", value=max(6.0, relay.hoc_pu + 1.0), step=0.5, key="ov_sweep_end")
    with sw3:
        sweep_step = st.number_input("Sweep Step (pu)", value=0.5, min_value=0.1, step=0.1, key="ov_sweep_step")

    if st.button("Generate Sweep Table", key="ov_sweep_btn"):
        if sweep_end <= sweep_start or sweep_step <= 0:
            st.error("Sweep End must be greater than Sweep Start, and Sweep Step must be positive.")
        else:
            sweep_points = np.arange(sweep_start, sweep_end + sweep_step / 2.0, sweep_step)
            sweep_rows = []
            for i_test in sweep_points:
                t_inputs = [(0.0, 0.0), (0.0, 0.0), (0.0, 0.0)]
                t_inputs[inj_winding_idx] = (i_test * relay.windings[inj_winding_idx]["i_rated_pri"], 0.0)
                res = relay.evaluate_protection(t_inputs)
                sweep_rows.append({
                    "Test Current (pu)": round(float(i_test), 3),
                    f"{inj_winding_name} Injection (A)": round(i_test * relay.windings[inj_winding_idx]["i_rated_sec"], 3),
                    "I_op (pu)": round(res["i_op_pu"], 3),
                    "I_rest (pu)": round(res["i_rest_pu"], 3),
                    "Threshold (pu)": round(res["i_threshold_pu"], 3),
                    "Status": res["status"],
                })
            st.session_state["ov_sweep_df"] = pd.DataFrame(sweep_rows)

    if "ov_sweep_df" in st.session_state:
        st.dataframe(st.session_state["ov_sweep_df"], use_container_width=True)
        csv_sweep = st.session_state["ov_sweep_df"].to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Sweep Table as CSV",
            data=csv_sweep,
            file_name=f"87OA_Sweep_Test_Table_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )

# ---------------------------------------------------------------------------
# TAB — Settings Summary & Approval
# ---------------------------------------------------------------------------
with c["Settings Summary & Approval"]:
    st.subheader("Settings Summary & Approval Record")
    st.caption(
        "Record the settings basis and review status before exporting a controlled report. "
        "This record supports engineering review; it does not replace the approved protection study."
    )

    st.session_state.setdefault("overall_source_document", "Transformer Diff Setting - Overall GSUT-GEN.pdf")
    st.session_state.setdefault("overall_revision", "Rev. 0")
    st.session_state.setdefault("overall_prepared_by", "")
    st.session_state.setdefault("overall_reviewed_by", "")
    st.session_state.setdefault("overall_approval_status", "Draft — engineering review required")
    st.session_state.setdefault("overall_review_note", "")

    source_document = st.text_input("Source document", key="overall_source_document")
    col_doc_1, col_doc_2 = st.columns(2)
    with col_doc_1:
        revision = st.text_input("Document / settings revision", key="overall_revision")
        prepared_by = st.text_input("Prepared by", key="overall_prepared_by")
    with col_doc_2:
        reviewed_by = st.text_input("Reviewed by", key="overall_reviewed_by")
        approval_status = st.selectbox(
            "Review status",
            ["Draft — engineering review required", "Reviewed — pending approval", "Approved for issue"],
            key="overall_approval_status",
        )
    review_note = st.text_area("Review note / change description", key="overall_review_note")

    _sheet_rows = [
        ("HV CT Ratio", f"{ct_hv:.0f}:{ct_secondary_rating:.0f}"),
        ("Generator CT Ratio", f"{ct_gen:.0f}:{ct_secondary_rating:.0f}"),
        ("UAT CT Ratio", f"{ct_uat:.0f}:{ct_secondary_rating:.0f}"),
        ("T1 (HV Tap)", f"{tap_hv:.3f}"),
        ("T2 (Generator Tap)", f"{tap_gen:.3f}"),
        ("T3 (UAT Tap)", f"{tap_uat:.3f}"),
        ("Bias, τ (%)", f"{bias_pct:.0f}"),
        ("Minimum Operate (%)", f"{min_operate_pct:.0f}"),
        ("HOC (x tap value current)", f"{hoc_multiple:.2f}"),
        ("Restraint Standard", convention),
        ("CT Polarity Reference", ct_polarity),
    ]

    st.markdown("---")
    pdf_bytes = generate_transformer_pdf_report(
        selected_preset, relay, evals, phases, relay_type_label="CAC2-10-M3", winding_currents=winding_currents,
        settings_sheets=[("CAC2-10-M3", _sheet_rows)],
    )
    st.download_button(
        label="Export Certified Protection Audit Report",
        data=pdf_bytes,
        file_name=f"Overall_GSUT-GEN_Protection_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
        mime="application/pdf",
        help="Includes the Relay-Ready Settings Sheet as its final section.",
    )

    st.markdown("---")
    st.markdown("#### Save Profile")
    st.caption(
        "Name and download every setting currently active under the selected preset above — "
        "most useful after entering your own values under Custom Profile, so you can pick this "
        "file back up next time instead of re-typing everything. Use the loader in the sidebar "
        "to restore it later."
    )
    export_profile_button(
        st, "overall", f"{selected_preset}__",
        default_name="Overall GSUT-GEN Profile", button_key="overall",
    )
