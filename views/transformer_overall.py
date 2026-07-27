import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common.pdf_report import generate_transformer_pdf_report
from common.sld import overall_zone_svg, render_zone_diagram
from common.ui_helpers import slider_with_exact_input, MR_CT_TAPS_2000_5
from engines.transformer import TransformerDifferentialRelay, winding_internal_vector, raw_input_for_internal_vector

st.title("🔌 Overall GSUT-GEN Differential Protection")
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
    }
}

st.sidebar.header("📋 Equipment Presets")
selected_preset = st.sidebar.selectbox("Load Standard Profile", list(PRESETS.keys()))
p_data = PRESETS[selected_preset]

st.sidebar.header("🎯 Protection Characteristic")
bias_pct = slider_with_exact_input(
    st.sidebar, "Bias, τ (%)", 20, 40, p_data["bias"], 10,
    key=f"{selected_preset}__bias",
    help_text="CAC2-10-M3 available settings: 20%, 30%, or 40%."
)
min_operate_pct = slider_with_exact_input(
    st.sidebar, "Minimum Operate (%)", 20, 40, p_data["min_operate"], 10,
    key=f"{selected_preset}__min_operate",
    help_text="CAC2-10-M3 available settings: IT x 20%, 30%, or 40% (IT = tap value current)."
)
hoc_options = [5, 6, 8, 10, 12]
hoc_multiple = st.sidebar.select_slider(
    "HOC (x tap value current)", options=hoc_options,
    value=p_data["hoc"] if p_data["hoc"] in hoc_options else 5,
    help="CAC2-10-M3 available settings: 5, 6, 8, 10, or 12 times tap value current. Not "
         "harmonically restrained — operates on differential current only, so LV-side faults won't trip it."
)

with st.sidebar.expander("🔧 Advanced Settings (CT Spec, Taps & Wiring)", expanded=False):
    st.markdown("**Winding 1 — HV (525kV side, Multi-Ratio Delta CT)**")
    kv_hv = st.number_input("HV Rated Voltage (kV)", value=p_data["kv_hv"], step=1.0, format="%.3f",
        help="Uses the center-of-tap-range voltage (538.125kV) per the settings doc's full-load calc, not the 525kV nameplate.")
    ct_hv = st.select_slider(
        "HV CT Ratio Tap (Multi-Ratio, Primary A)", options=MR_CT_TAPS_2000_5,
        value=p_data["ct_hv"] if p_data["ct_hv"] in MR_CT_TAPS_2000_5 else 1600,
        help="Same 2000:5 Delta-connected multi-ratio bushing CT as the GSUT page (it's the same "
             "physical CT feeding both relays) — documented as set on 1600:5."
    )
    ct_conn_hv = st.selectbox("HV CT Connection", ["DELTA", "WYE"], index=0 if p_data["ct_conn_hv"] == "DELTA" else 1, key="ov_ct_conn_hv")

    st.markdown("**Winding 2 — Generator (23kV side, Wye CT)**")
    kv_gen = st.number_input("Generator Rated Voltage (kV)", value=p_data["kv_gen"], step=0.1, format="%.3f")
    ct_gen = st.number_input("Generator CT Ratio (Primary A, e.g. 24000 in '24000:5')", value=p_data["ct_gen"])
    ct_conn_gen = st.selectbox("Generator CT Connection", ["WYE", "DELTA"], index=0 if p_data["ct_conn_gen"] == "WYE" else 1, key="ov_ct_conn_gen")

    st.markdown("**Winding 3 — Unit Auxiliary Transformer (23kV side, Wye CT)**")
    kv_uat = st.number_input("UAT Rated Voltage (kV)", value=p_data["kv_uat"], step=0.1, format="%.3f")
    ct_uat = st.number_input("UAT CT Ratio (Primary A, e.g. 24000 in '24000:5')", value=p_data["ct_uat"])
    ct_conn_uat = st.selectbox("UAT CT Connection", ["WYE", "DELTA"], index=0 if p_data["ct_conn_uat"] == "WYE" else 1, key="ov_ct_conn_uat")

    mva = st.number_input(
        "Base Rating (MVA)", value=p_data["mva"], step=10.0,
        help="Relay currents are calculated assuming each device carries the full rating of the "
             "Generator Step-Up Transformer (per the settings doc's Calculation/Discussion)."
    )

    ct_secondary_rating = st.selectbox(
        "CT Secondary Rating (A)", [1.0, 5.0], index=1, key="ov_ct_sec",
        help="The rated secondary current stamped on the CT nameplate (the '5' in 'x:5'). Applied to all three CTs."
    )
    st.caption(
        f"Effective ratio → HV: **{ct_hv/ct_secondary_rating:.1f}:1**  |  "
        f"Generator: **{ct_gen/ct_secondary_rating:.1f}:1**  |  "
        f"UAT: **{ct_uat/ct_secondary_rating:.1f}:1**"
    )

    st.markdown("**CT Matching Taps**")
    tap_hv = slider_with_exact_input(
        st, "HV Tap (T1)", 0.4, 2.18, p_data["tap_hv"], 0.02,
        key=f"{selected_preset}__tap_hv",
        help_text="CAC2-10-M3 setting range: 0.4-2.18 in steps of 0.02."
    )
    tap_gen = slider_with_exact_input(
        st, "Generator Tap (T2)", 0.4, 2.18, p_data["tap_gen"], 0.02,
        key=f"{selected_preset}__tap_gen",
        help_text="CAC2-10-M3 setting range: 0.4-2.18 in steps of 0.02."
    )
    tap_uat = slider_with_exact_input(
        st, "UAT Tap (T3)", 0.4, 2.18, p_data["tap_uat"], 0.02,
        key=f"{selected_preset}__tap_uat",
        help_text="CAC2-10-M3 setting range: 0.4-2.18 in steps of 0.02."
    )

    st.markdown("**Wiring & Convention**")
    col_conv, col_pol = st.columns(2)
    with col_conv:
        convention = st.radio("Restraint Standard", ["IEEE", "IEC"], help="IEEE: Average current. IEC: Arithmetic sum.", key="ov_convention")
    with col_pol:
        ct_polarity = st.radio(
            "Polarity Reference", ["OPPOSITE", "SAME"], index=0, key="ov_ct_polarity",
            help="OPPOSITE: HV (Winding 1) is the reference; Generator and UAT windings are flipped "
                 "relative to it, as current flows into the zone from HV and out to the other two."
        )

windings = [
    {"name": "HV (525kV)", "kv": kv_hv, "ct_ratio": ct_hv, "ct_secondary_rating": ct_secondary_rating, "tap": tap_hv, "ct_connection": ct_conn_hv},
    {"name": "Generator (23kV)", "kv": kv_gen, "ct_ratio": ct_gen, "ct_secondary_rating": ct_secondary_rating, "tap": tap_gen, "ct_connection": ct_conn_gen},
    {"name": "UAT (23kV)", "kv": kv_uat, "ct_ratio": ct_uat, "ct_secondary_rating": ct_secondary_rating, "tap": tap_uat, "ct_connection": ct_conn_uat},
]
st.sidebar.caption(
    "ℹ️ Delta-connected CTs get an automatic √3 magnitude step-up and a +30° phase "
    "shift (see engines/transformer.py) — the standard compensation for a Wye/Delta "
    "power transformer so healthy through-load doesn't read as a fault."
)

relay = TransformerDifferentialRelay(
    mva_rated=mva, windings=windings,
    bias_pct=bias_pct, min_operate_pct=min_operate_pct, hoc_multiple=hoc_multiple,
    convention=convention, ct_polarity=ct_polarity,
)

phases = ["Phase A", "Phase B", "Phase C"]
winding_names = ["HV (525kV)", "Generator (23kV)", "UAT (23kV)"]
amps_base = relay.windings[0]["i_rated_sec"]  # HV-side rated secondary current, used as pu base for charts

tab_sld, tab1, tab2, tab3 = st.tabs([
    "🗺️ Protection Zone (SLD)", "📊 Live Vector Simulation",
    "🧰 Commissioning & Injection Tool", "🧪 Test Point Verification & Curve"
])

with tab_sld:
    st.subheader("🗺️ Protection Zone — Single Line Diagram")
    st.caption(
        "Shows the three-restraint backup zone spanning the Generator, GSUT, and Unit "
        "Auxiliary Transformer."
    )
    render_zone_diagram("overall.png", overall_zone_svg(relay, ct_polarity, tag="87OA/87OB"))

# ---------------------------------------------------------------------------
# TAB 1 — Live Simulation
# ---------------------------------------------------------------------------
with tab1:
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
            with st.expander(f"📌 {phase} Settings", expanded=(phase == "Phase A")):
                c1, c2, c3 = st.columns(3)
                def_ang_hv = -120.0 * idx
                def_ang_other = def_ang_hv + 180.0 if ct_polarity == "OPPOSITE" else def_ang_hv
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
            st.error("🚨 PROTECTIVE RELAY TRIP INITIATED!")
        else:
            st.success("✅ SYSTEM HEALTHY (Stability / Restraint Zone)")

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

        pdf_bytes = generate_transformer_pdf_report(selected_preset, relay, evals, phases, relay_type_label="CAC2-10-M3")
        st.download_button(
            label="📄 Export Certified Protection Audit Report",
            data=pdf_bytes,
            file_name=f"Overall_GSUT-GEN_Protection_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf"
        )

    st.subheader("📈 Differential Bias Characteristic Curve")

    chart_units = st.radio(
        "Chart units", ["Per-Unit (pu)", "Secondary Amps (A)"], horizontal=True, key="ov_chart_units",
        help="pu base is the HV-side rated secondary current."
    )
    use_amps = chart_units == "Secondary Amps (A)"

    max_x_val = max(6.0, max(e["i_rest_pu"] for e in evals.values()) + 1.5, relay.hoc_pu + 1.0)
    x_axis_line = np.linspace(0, max_x_val, 400)
    y_axis_line = [relay.calculate_trip_threshold(x) for x in x_axis_line]

    x_plot = x_axis_line * amps_base if use_amps else x_axis_line
    y_plot = np.array(y_axis_line) * amps_base if use_amps else np.array(y_axis_line)
    unit_label = "A" if use_amps else "pu"

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x_plot, y=y_plot, mode='lines', name='CAL.', line=dict(color='#2563EB', width=3)))

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

    y_upper_pu = max(relay.hoc_pu + 2.0, max(y_axis_line) + 1.0)
    y_upper = y_upper_pu * amps_base if use_amps else y_upper_pu
    x_upper = max_x_val * amps_base if use_amps else max_x_val
    fig.update_layout(
        title="Overall GSUT-GEN Differential Bias Characteristic",
        xaxis_title=f"Restraint Current I_rest ({unit_label})",
        yaxis_title=f"Differential/Operating Current I_op ({unit_label})",
        xaxis=dict(range=[0, x_upper]), yaxis=dict(range=[0, y_upper]),
        template="plotly_white", height=500
    )
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# TAB 2 — Commissioning & Injection Tool
# ---------------------------------------------------------------------------
with tab2:
    st.subheader("🧰 Commissioning & Secondary Current Injection Assistant")
    st.write(
        "With a 3-restraint relay there's no single unique way to split a target differential "
        "across three currents, so this tool uses the standard commissioning method instead: "
        "**energize one winding at a time** (the other two at zero) and read the resulting "
        "I_op / I_rest / trip verdict straight from the relay engine — exactly how these "
        "relays are normally verified in the field."
    )

    st.markdown("#### 🎯 Single-Winding Injection Test")
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
    st.subheader("🔁 Auto-Sweep Single-Winding Test Table")
    sw1, sw2, sw3 = st.columns(3)
    with sw1:
        sweep_start = st.number_input("Sweep Start (pu)", value=0.2, min_value=0.0, step=0.1, key="ov_sweep_start")
    with sw2:
        sweep_end = st.number_input("Sweep End (pu)", value=max(6.0, relay.hoc_pu + 1.0), step=0.5, key="ov_sweep_end")
    with sw3:
        sweep_step = st.number_input("Sweep Step (pu)", value=0.5, min_value=0.1, step=0.1, key="ov_sweep_step")

    if st.button("▶️ Generate Sweep Table", key="ov_sweep_btn"):
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
            label="⬇️ Download Sweep Table as CSV",
            data=csv_sweep,
            file_name=f"87OA_Sweep_Test_Table_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )

# ---------------------------------------------------------------------------
# TAB 3 — Test Point Verification & Curve
# ---------------------------------------------------------------------------
with tab3:
    st.subheader("🧪 Test Point Verification & Curve")
    st.write("Enter measured test results and see them plotted against the calculated characteristic curve.")

    if "ov_manual_test_points" not in st.session_state:
        st.session_state.ov_manual_test_points = []

    with st.form("ov_add_test_point_form", clear_on_submit=True):
        tp_unit = st.radio(
            "Entry units", ["Secondary Amps (A)", "Per-Unit (pu)"], horizontal=True, key="ov_tp_entry_unit"
        )
        tc1, tc2, tc3, tc4 = st.columns([1, 1, 1, 1.4])
        restraint_label = "Restraint Current" if tp_unit.startswith("Secondary") else "Restraint Current (pu)"
        diff_label = "Measured Diff. Current" if tp_unit.startswith("Secondary") else "Measured Diff. Current (pu)"
        restraint_step = 0.1 if tp_unit.startswith("Secondary") else 0.05
        diff_step = 0.05 if tp_unit.startswith("Secondary") else 0.01
        restraint_default = 1.0 if tp_unit.startswith("Secondary") else 0.3
        diff_default = 0.3 if tp_unit.startswith("Secondary") else 0.06
        with tc1:
            tp_phase = st.selectbox("Phase", ["Phase A", "Phase B", "Phase C", "Other"], key="ov_tp_phase")
        with tc2:
            tp_restraint = st.number_input(restraint_label, min_value=0.0, value=restraint_default, step=restraint_step, key="ov_tp_restraint")
        with tc3:
            tp_diff = st.number_input(diff_label, min_value=0.0, value=diff_default, step=diff_step, key="ov_tp_diff")
        with tc4:
            tp_label = st.text_input("Label (optional)", value="", key="ov_tp_label")
        submitted = st.form_submit_button("➕ Add Test Point")
        if submitted:
            if tp_unit.startswith("Secondary"):
                restraint_amps, diff_amps = tp_restraint, tp_diff
            else:
                restraint_amps, diff_amps = tp_restraint * amps_base, tp_diff * amps_base
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
            if st.button("🗑️ Remove Row", key="ov_remove_btn"):
                st.session_state.ov_manual_test_points.pop(int(remove_idx))
                st.rerun()
        with rc2:
            if st.button("🗑️ Clear All Test Points", key="ov_clear_btn"):
                st.session_state.ov_manual_test_points = []
                st.rerun()
    else:
        st.info("No test points added yet — add some above to see them plotted below.")

    st.markdown("---")
    st.markdown("#### 📈 Differential Bias Characteristic Curve")

    comm_chart_units = st.radio("Chart units", ["Per-Unit (pu)", "Secondary Amps (A)"], horizontal=True, key="ov_comm_chart_units")
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
        sweep_fig.add_trace(go.Scatter(x=curve_x, y=curve_y, mode="lines", name="CAL.", line=dict(color="#2E8B57", width=3)))

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
