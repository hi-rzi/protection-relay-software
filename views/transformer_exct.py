import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common.pdf_report import generate_transformer_pdf_report
from common.ui_helpers import slider_with_exact_input
from engines.transformer import TransformerDifferentialRelay

st.title("🔌 Excitation Transformer (EXCT) Differential Protection")
st.caption(
    "6300/7875kVA, 23kV Ungrounded Wye / 900V Delta — CAC1-10-M3 percentage-bias "
    "differential relay (Mitsubishi, 2-winding)."
)

# ---------------------------------------------------------------------------
# Presets — from Transformer_Diff_Setting_-_EXCT.pdf, Section 5.12.1
# (Relays 87ET7 / 87ET8, Setting Summary + Calculation/Discussion)
# ---------------------------------------------------------------------------
PRESETS = {
    "POMI EXCT 87ET7/87ET8 - 7875 kVA": {
        "mva": 7.875,
        "kv_hv": 23.0, "kv_lv": 0.9,
        "ct_hv": 400, "ct_lv": 5000, "ct_sec": 5.0,
        "tap_hv": 0.7, "tap_lv": 0.6,
        "bias": 20, "min_operate": 20, "hoc": 5,
    }
}

st.sidebar.header("📋 Equipment Presets")
selected_preset = st.sidebar.selectbox("Load Standard Profile", list(PRESETS.keys()))
p_data = PRESETS[selected_preset]

st.sidebar.header("1. Transformer & CT Spec")
mva = st.sidebar.number_input("Transformer Rating (MVA)", value=p_data["mva"], step=0.1, format="%.3f")

st.sidebar.markdown("**HV Winding (23kV side)**")
kv_hv = st.sidebar.number_input("HV Rated Voltage (kV)", value=p_data["kv_hv"], step=1.0)
ct_hv = st.sidebar.number_input("HV CT Ratio (Primary A, e.g. 400 in '400:5')", value=p_data["ct_hv"])

st.sidebar.markdown("**LV Winding (900V side)**")
kv_lv = st.sidebar.number_input("LV Rated Voltage (kV)", value=p_data["kv_lv"], step=0.1, format="%.3f")
ct_lv = st.sidebar.number_input("LV CT Ratio (Primary A, e.g. 5000 in '5000:5')", value=p_data["ct_lv"])

ct_secondary_rating = st.sidebar.selectbox(
    "CT Secondary Rating (A)", [1.0, 5.0], index=1,
    help="The rated secondary current stamped on the CT nameplate (the '5' in '400:5'). "
         "Applied to both CTs to determine the true turns ratio used in all per-unit scaling."
)
st.sidebar.caption(
    f"Effective ratio → HV: **{ct_hv:.0f}:{ct_secondary_rating:.0f}** "
    f"(= {ct_hv/ct_secondary_rating:.1f}:1)  |  "
    f"LV: **{ct_lv:.0f}:{ct_secondary_rating:.0f}** "
    f"(= {ct_lv/ct_secondary_rating:.1f}:1)"
)

st.sidebar.header("2. CT Matching Taps")
tap_hv = slider_with_exact_input(
    st.sidebar, "HV Tap (T1)", 0.4, 2.18, p_data["tap_hv"], 0.01,
    key=f"{selected_preset}__tap_hv",
    help_text="CAC1-10-M3 setting range: 0.4-2.18. Selected so the tap-corrected current at "
               "rated load is close to the relay's rated tap current (I_N = 5A)."
)
tap_lv = slider_with_exact_input(
    st.sidebar, "LV Tap (T2)", 0.4, 2.18, p_data["tap_lv"], 0.01,
    key=f"{selected_preset}__tap_lv",
    help_text="CAC1-10-M3 setting range: 0.4-2.18."
)

st.sidebar.header("3. Protection Characteristic")
bias_pct = slider_with_exact_input(
    st.sidebar, "Bias, τ (%)", 5, 60, p_data["bias"], 1,
    key=f"{selected_preset}__bias",
    help_text="Must exceed the sum of tap-changer error, CT error, relay operating error "
               "(10% of bias) and mismatch — see Calculation/Discussion in the settings doc."
)
min_operate_pct = slider_with_exact_input(
    st.sidebar, "Minimum Operate (%)", 5, 60, p_data["min_operate"], 1,
    key=f"{selected_preset}__min_operate",
    help_text="Minimum differential pickup at zero restraint current."
)
hoc_multiple = slider_with_exact_input(
    st.sidebar, "HOC (x tap current)", 2.0, 20.0, float(p_data["hoc"]), 0.5,
    key=f"{selected_preset}__hoc",
    help_text="Unrestrained instantaneous element. Set high enough not to operate on "
               "transformer inrush current (see Calculation/Discussion)."
)

st.sidebar.header("4. Wiring & Convention")
col_conv, col_pol = st.sidebar.columns(2)
with col_conv:
    convention = st.radio("Restraint Standard", ["IEEE", "IEC"], help="IEEE: Average current. IEC: Arithmetic sum.")
with col_pol:
    ct_polarity = st.radio(
        "Polarity Reference", ["OPPOSITE", "SAME"], index=0,
        help="OPPOSITE is standard for a 2-winding transformer differential (currents flow "
             "into the zone on one side, out on the other)."
    )

windings = [
    {"name": "HV (23kV)", "kv": kv_hv, "ct_ratio": ct_hv, "ct_secondary_rating": ct_secondary_rating, "tap": tap_hv},
    {"name": "LV (900V)", "kv": kv_lv, "ct_ratio": ct_lv, "ct_secondary_rating": ct_secondary_rating, "tap": tap_lv},
]

relay = TransformerDifferentialRelay(
    mva_rated=mva, windings=windings,
    bias_pct=bias_pct, min_operate_pct=min_operate_pct, hoc_multiple=hoc_multiple,
    convention=convention, ct_polarity=ct_polarity,
)

phases = ["Phase A", "Phase B", "Phase C"]
amps_base = relay.windings[0]["i_rated_sec"]  # HV-side rated secondary current, used as pu base for charts

tab1, tab2, tab3 = st.tabs(["📊 Live Vector Simulation", "🧰 Commissioning & Injection Tool", "🧪 Test Point Verification & Curve"])

# ---------------------------------------------------------------------------
# TAB 1 — Live Simulation
# ---------------------------------------------------------------------------
with tab1:
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
            with st.expander(f"📌 {phase} Settings", expanded=(phase == "Phase A")):
                c1, c2 = st.columns(2)
                def_val_hv = relay.windings[0]["i_rated_pri"] if phase == "Phase A" else 0.0
                def_val_lv = relay.windings[1]["i_rated_pri"] if phase == "Phase A" else 0.0
                def_ang_hv = -120.0 * idx
                def_ang_lv = def_ang_hv + 180.0 if ct_polarity == "OPPOSITE" else def_ang_hv

                with c1:
                    i_hv = st.number_input(f"HV Primary Amps [A]", value=def_val_hv, key=f"exct_hv_i_{phase}")
                    a_hv = st.number_input(f"HV Angle (°)", value=def_ang_hv, key=f"exct_hv_a_{phase}")
                with c2:
                    i_lv = st.number_input(f"LV Primary Amps [A]", value=def_val_lv, key=f"exct_lv_i_{phase}")
                    a_lv = st.number_input(f"LV Angle (°)", value=def_ang_lv, key=f"exct_lv_a_{phase}")

                inputs[phase] = {"i_hv": i_hv, "a_hv": a_hv, "i_lv": i_lv, "a_lv": a_lv}

        evals = {p: relay.evaluate_protection([
            (inputs[p]["i_hv"], inputs[p]["a_hv"]),
            (inputs[p]["i_lv"], inputs[p]["a_lv"]),
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

        pdf_bytes = generate_transformer_pdf_report(selected_preset, relay, evals, phases)
        st.download_button(
            label="📄 Export Certified Protection Audit Report",
            data=pdf_bytes,
            file_name=f"EXCT_Differential_Protection_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf"
        )

    st.subheader("📈 Differential Bias Characteristic Curve")

    chart_units = st.radio(
        "Chart units", ["Per-Unit (pu)", "Secondary Amps (A)"], horizontal=True,
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
        title="Transformer Differential Bias Characteristic",
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
        "Pick a target restraint current for each phase to calculate the exact secondary "
        "Amps to inject at your test set for that phase."
    )

    default_restraints = {"Phase A": 0.5, "Phase B": 2.5, "Phase C": 5.0}
    st.markdown("#### 🎯 Boundary Injection Calculator")
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
    st.subheader("🔁 Auto-Sweep Full Curve Test Table")
    sw1, sw2, sw3 = st.columns(3)
    with sw1:
        sweep_start = st.number_input("Sweep Start (pu)", value=0.2, min_value=0.0, step=0.1)
    with sw2:
        sweep_end = st.number_input("Sweep End (pu)", value=max(6.0, relay.hoc_pu + 1.0), step=0.5)
    with sw3:
        sweep_step = st.number_input("Sweep Step (pu)", value=0.5, min_value=0.1, step=0.1)

    if st.button("▶️ Generate Sweep Table"):
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
            st.session_state["exct_sweep_df"] = pd.DataFrame(sweep_rows)

    if "exct_sweep_df" in st.session_state:
        st.dataframe(st.session_state["exct_sweep_df"], use_container_width=True)
        csv_sweep = st.session_state["exct_sweep_df"].to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️ Download Sweep Table as CSV",
            data=csv_sweep,
            file_name=f"87ET_Sweep_Test_Table_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )

# ---------------------------------------------------------------------------
# TAB 3 — Test Point Verification & Curve
# ---------------------------------------------------------------------------
with tab3:
    st.subheader("🧪 Test Point Verification & Curve")
    st.write("Enter measured test results and see them plotted against the calculated characteristic curve.")

    if "exct_manual_test_points" not in st.session_state:
        st.session_state.exct_manual_test_points = []

    with st.form("exct_add_test_point_form", clear_on_submit=True):
        tp_unit = st.radio(
            "Entry units", ["Secondary Amps (A)", "Per-Unit (pu)"], horizontal=True, key="exct_tp_entry_unit"
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
        submitted = st.form_submit_button("➕ Add Test Point")
        if submitted:
            if tp_unit.startswith("Secondary"):
                restraint_amps, diff_amps = tp_restraint, tp_diff
            else:
                restraint_amps, diff_amps = tp_restraint * amps_base, tp_diff * amps_base
            st.session_state.exct_manual_test_points.append({
                "Phase": tp_phase,
                "Restraint (A)": round(restraint_amps, 3),
                "Measured Diff (A)": round(diff_amps, 3),
                "Label": tp_label
            })

    if st.session_state.exct_manual_test_points:
        table_unit = st.radio("Display units for table", ["Secondary Amps (A)", "Per-Unit (pu)"], horizontal=True, key="exct_tp_table_unit")
        table_in_pu = table_unit.startswith("Per-Unit")
        restraint_col = "Restraint (pu)" if table_in_pu else "Restraint (A)"
        diff_col = "Measured Diff (pu)" if table_in_pu else "Measured Diff (A)"

        tp_display_rows = []
        for tp in st.session_state.exct_manual_test_points:
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
                max_value=max(len(st.session_state.exct_manual_test_points) - 1, 0), value=0, step=1
            )
            if st.button("🗑️ Remove Row"):
                st.session_state.exct_manual_test_points.pop(int(remove_idx))
                st.rerun()
        with rc2:
            if st.button("🗑️ Clear All Test Points"):
                st.session_state.exct_manual_test_points = []
                st.rerun()
    else:
        st.info("No test points added yet — add some above to see them plotted below.")

    st.markdown("---")
    st.markdown("#### 📈 Differential Bias Characteristic Curve")

    comm_chart_units = st.radio("Chart units", ["Per-Unit (pu)", "Secondary Amps (A)"], horizontal=True, key="exct_comm_chart_units")
    use_amps_comm = comm_chart_units == "Secondary Amps (A)"
    unit_label_comm = "A" if use_amps_comm else "pu"

    cal_source = st.radio(
        "CAL. line source",
        ["Connect my test points (commissioning report style)", "Theoretical relay characteristic"],
        horizontal=True, key="exct_cal_line_source"
    )

    sweep_fig = go.Figure()
    if cal_source.startswith("Connect") and len(st.session_state.exct_manual_test_points) >= 2:
        sorted_pts = sorted(st.session_state.exct_manual_test_points, key=lambda tp: tp["Restraint (A)"])
        cal_x_amps = [tp["Restraint (A)"] for tp in sorted_pts]
        cal_y_amps = [tp["Measured Diff (A)"] for tp in sorted_pts]
        curve_x = cal_x_amps if use_amps_comm else [x / amps_base for x in cal_x_amps]
        curve_y = cal_y_amps if use_amps_comm else [y / amps_base for y in cal_y_amps]
        sweep_fig.add_trace(go.Scatter(x=curve_x, y=curve_y, mode="lines", name="CAL.", line=dict(color="#2E8B57", width=3)))
    else:
        if cal_source.startswith("Connect"):
            st.info("Add at least 2 test points above to draw the CAL. line through them — showing the theoretical characteristic for now.")
        manual_restraints_pu = [tp["Restraint (A)"] / amps_base for tp in st.session_state.exct_manual_test_points]
        default_reach = relay.hoc_pu + 2.0
        max_restraint = max(manual_restraints_pu + [default_reach]) if manual_restraints_pu else default_reach
        curve_x_pu = np.linspace(0, max_restraint * 1.2 + 0.5, 300)
        curve_y_pu = [relay.calculate_trip_threshold(x) for x in curve_x_pu]
        curve_x = curve_x_pu * amps_base if use_amps_comm else curve_x_pu
        curve_y = np.array(curve_y_pu) * amps_base if use_amps_comm else np.array(curve_y_pu)
        sweep_fig.add_trace(go.Scatter(x=curve_x, y=curve_y, mode="lines", name="CAL.", line=dict(color="#2E8B57", width=3)))

    tp_marker_colors = {"Phase A": "#D63384", "Phase B": "#6C757D", "Phase C": "#1E3A8A", "Other": "#F59E0B"}
    tp_marker_symbols = {"Phase A": "square", "Phase B": "triangle-up", "Phase C": "square", "Other": "diamond"}
    for tp in st.session_state.exct_manual_test_points:
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
    png_filename = f"87ET_Differential_Bias_Curve_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}"
    st.plotly_chart(sweep_fig, use_container_width=True, config={"toImageButtonOptions": {"format": "png", "filename": png_filename, "scale": 3}})
