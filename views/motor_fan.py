import datetime
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common.pdf_report import generate_fan_motor_pdf_report
from common.concepts import render_theory_tab
from common.sld import motor_overcurrent_svg
from common.historian import render_historian_overlay
from common.relay_settings_sheet import render_settings_sheet
from common.project_state import with_restored_preset, record_equipment_settings
from engines.motor_869 import Motor869Relay

st.title("Draft Fan Motor Protection")
st.caption(
    "6.9kV induced/forced-draft combustion air fans — GE Multilin 869 Motor Protection Relay only "
    "(no separate discrete 50/50/51 electromechanical relay on these motors)."
)

st.warning(
    "**Engineering review required.** This tool supports settings checks and commissioning "
    "calculations; it does not approve relay settings. Verify every result against the approved "
    "coordination study, relay manual, and site test procedure before applying settings in service."
)

# ---------------------------------------------------------------------------
# Presets — from Data.xlsx "Motor Data" sheet (Unit 7 & 8, 6.9kV section).
# Settings are identical across Unit 7/8 and the A/B duplicate motors within
# each fan type, so one preset per fan type covers all four physical units.
# No Locked Rotor Current or Safe Stall Time is recorded for these motors in
# that sheet (unlike the ID Fan's older settings doc), so there is no
# starting/stall margin check here - only what this data actually supports.
# "Short Circuit Pick-up" is given as "X CT" - confirmed to mean a multiple
# of the CT SECONDARY rating (e.g. 9.7 x CT on a 300/5 CT = 9.7 x 5 = 48.5A
# secondary), which is why Motor869Relay takes inst_pickup_multiple_of_ct.
# ---------------------------------------------------------------------------
FAN_TYPES = {
    "Primary Air (PA) Fan": {
        "purpose": (
            "The Primary Air Fan supplies the combustion air that carries pulverized coal from "
            "the mills into the furnace - losing it doesn't just stop air supply, it can starve "
            "the mills and destabilize combustion, so it gets its own dedicated overcurrent and "
            "thermal protection rather than depending on upstream switchgear protection alone."
        ),
        "motor_tag": "PA FAN",
        "presets": {
            "POMI PA Fan 7A/7B/8A/8B - 1960kW": {
                "motor_fla": 173, "ct_ratio": 300, "ct_sec": 5.0,
                "ground_ct_ratio": 50, "ground_ct_sec": 5.0,
                # NOTE: Curve Multiplier is an UNVERIFIED default (4.0) - no settings
                # calculation document has been found for the Primary Air Fan (unlike
                # the FD Fan, confirmed at CM=6 via FDFAN MOTOR PROTECTION.pdf's own
                # worked examples). Confirm against the real PA Fan relay/settings doc
                # before relying on this curve for anything but exploration.
                "overload_pickup_pct": 115.0, "curve_multiplier": 4.0,
                "inst_pickup_multiple_of_ct": 9.7, "inst_delay_ms": 60.0,
                "mech_jam_pct": 150.0, "mech_jam_delay_s": 1.0,
                "unbal_trip_pct": 36.0, "unbal_trip_delay_s": 60.0,
                "unbal_alarm_pct": 15.0, "unbal_alarm_delay_s": 10.0,
                "gf_pickup_frac": 0.1, "gf_delay_ms": 60.0,
                "phase_diff_pickup_frac": 0.1, "phase_diff_delay_ms": 60.0,
                "accel_timer_s": 20.0, "overload_alarm_delay_s": 1.0,
                "rtd_stator_c": 135, "ov_pickup_pu": 1.06, "ov_delay_s": 60.0,
                "of_hz": 51.5, "uf_hz": 48.5,
                "underpower_kw": 350.0, "underpower_delay_s": 10.0,
                "starts_per_hour": 2, "time_between_starts_min": 45,
            },
            "Custom Profile": {
                "motor_fla": 100, "ct_ratio": 100, "ct_sec": 5.0,
                "ground_ct_ratio": 50, "ground_ct_sec": 5.0,
                "overload_pickup_pct": 115.0, "curve_multiplier": 4.0,
                "inst_pickup_multiple_of_ct": 8.0, "inst_delay_ms": 60.0,
                "mech_jam_pct": 150.0, "mech_jam_delay_s": 1.0,
                "unbal_trip_pct": 30.0, "unbal_trip_delay_s": 60.0,
                "unbal_alarm_pct": 15.0, "unbal_alarm_delay_s": 10.0,
                "gf_pickup_frac": 0.1, "gf_delay_ms": 60.0,
                "phase_diff_pickup_frac": 0.1, "phase_diff_delay_ms": 60.0,
                "accel_timer_s": 20.0, "overload_alarm_delay_s": 1.0,
                "rtd_stator_c": 135, "ov_pickup_pu": 1.06, "ov_delay_s": 60.0,
                "of_hz": 51.5, "uf_hz": 48.5,
                "underpower_kw": 100.0, "underpower_delay_s": 10.0,
                "starts_per_hour": 2, "time_between_starts_min": 45,
            },
        },
    },
    "Forced Draft (FD) Fan": {
        "purpose": (
            "The Forced Draft Fan pushes combustion air into the furnace windbox - losing it "
            "collapses furnace draft and combustion air supply immediately, so like the Primary "
            "Air Fan it gets its own dedicated overcurrent and thermal protection at the motor "
            "itself."
        ),
        "motor_tag": "FD FAN",
        "presets": {
            "POMI FD Fan 7A/7B/8A/8B - 1343kW": {
                "motor_fla": 153, "ct_ratio": 200, "ct_sec": 5.0,
                "ground_ct_ratio": 50, "ground_ct_sec": 5.0,
                # Curve X6 (CM=6), confirmed against FDFAN MOTOR PROTECTION.pdf's own worked
                # examples: 6.3xFLA -> 13.6s and 4.8xFLA -> 23.8s, both reproduced exactly by
                # this app's formula at CM=6 (not the generic 4.0 used elsewhere as a guess).
                "overload_pickup_pct": 115.0, "curve_multiplier": 6.0,
                "inst_pickup_multiple_of_ct": 9.7, "inst_delay_ms": 60.0,
                "mech_jam_pct": 150.0, "mech_jam_delay_s": 1.0,
                "unbal_trip_pct": 39.0, "unbal_trip_delay_s": 60.0,
                "unbal_alarm_pct": 15.0, "unbal_alarm_delay_s": 10.0,
                "gf_pickup_frac": 0.1, "gf_delay_ms": 60.0,
                "phase_diff_pickup_frac": 0.1, "phase_diff_delay_ms": 60.0,
                "accel_timer_s": 18.0, "overload_alarm_delay_s": 1.0,
                "rtd_stator_c": 135, "ov_pickup_pu": 1.06, "ov_delay_s": 60.0,
                "of_hz": 51.5, "uf_hz": 48.5,
                "underpower_kw": 80.0, "underpower_delay_s": 10.0,
                "starts_per_hour": 2, "time_between_starts_min": 45,
            },
            "Custom Profile": {
                "motor_fla": 100, "ct_ratio": 100, "ct_sec": 5.0,
                "ground_ct_ratio": 50, "ground_ct_sec": 5.0,
                "overload_pickup_pct": 115.0, "curve_multiplier": 4.0,
                "inst_pickup_multiple_of_ct": 8.0, "inst_delay_ms": 60.0,
                "mech_jam_pct": 150.0, "mech_jam_delay_s": 1.0,
                "unbal_trip_pct": 30.0, "unbal_trip_delay_s": 60.0,
                "unbal_alarm_pct": 15.0, "unbal_alarm_delay_s": 10.0,
                "gf_pickup_frac": 0.1, "gf_delay_ms": 60.0,
                "phase_diff_pickup_frac": 0.1, "phase_diff_delay_ms": 60.0,
                "accel_timer_s": 18.0, "overload_alarm_delay_s": 1.0,
                "rtd_stator_c": 135, "ov_pickup_pu": 1.06, "ov_delay_s": 60.0,
                "of_hz": 51.5, "uf_hz": 48.5,
                "underpower_kw": 100.0, "underpower_delay_s": 10.0,
                "starts_per_hour": 2, "time_between_starts_min": 45,
            },
        },
    },
}

st.sidebar.header("Equipment Presets")
fan_type = st.sidebar.radio("Fan Type", list(FAN_TYPES.keys()))
fan_data = FAN_TYPES[fan_type]
project_key = "pa_fan" if fan_type.startswith("Primary") else "fd_fan"

presets_with_project = with_restored_preset(fan_data["presets"], project_key)
selected_preset = st.sidebar.selectbox(
    "Load Standard Profile", list(presets_with_project.keys()), key=f"{project_key}__preset",
    help="Pick a built-in POMI motor, or Custom Profile to enter your own equipment's ratings, "
         "CT specs, and protection settings — this app isn't limited to POMI equipment."
)
p_data = presets_with_project[selected_preset]

if project_key == "pa_fan" and selected_preset != "Custom Profile":
    st.info(
        "**Curve Multiplier (CM) is an unverified default (4.0)** — no settings calculation "
        "document has been located yet for the Primary Air Fan, unlike the FD Fan, whose CM=6 "
        "was confirmed by reproducing its settings doc's own worked examples exactly. Confirm "
        "the real PA Fan curve setting before relying on this for anything but exploration."
    )

st.sidebar.header("Motor Data & CT Spec")
motor_fla = st.sidebar.number_input("Motor Full Load Current (A)", min_value=1.0, value=float(p_data["motor_fla"]), step=1.0, key=f"{project_key}__fla")
ct_ratio = st.sidebar.number_input("CT Ratio (Primary A, e.g. 300 in '300:5')", min_value=1.0, value=float(p_data["ct_ratio"]), key=f"{project_key}__ct_ratio")
ct_secondary_rating = st.sidebar.selectbox("CT Secondary Rating (A)", [1.0, 5.0], index=1 if p_data["ct_sec"] == 5.0 else 0, key=f"{project_key}__ct_sec")
st.sidebar.caption(f"Effective ratio → **{ct_ratio:.0f}:{ct_secondary_rating:.0f}** (= {ct_ratio/ct_secondary_rating:.1f}:1)")
ground_ct_ratio = st.sidebar.number_input("Ground (Zero-Sequence) CT Ratio (Primary A, e.g. 50 in '50:5')", min_value=1.0, value=float(p_data["ground_ct_ratio"]), key=f"{project_key}__gct_ratio")

with st.sidebar.expander("Advanced Settings (GE 869 MPR)", expanded=False):
    st.markdown("**Overload (Thermal Model)**")
    overload_pickup_pct = st.number_input("Overload Pickup (% FLA)", min_value=100.0, max_value=125.0, value=p_data["overload_pickup_pct"], step=1.0, key=f"{project_key}__ovl_pct")
    curve_multiplier = st.number_input("Curve Multiplier (CM)", min_value=1.0, max_value=8.0, value=p_data["curve_multiplier"], step=0.5, key=f"{project_key}__cm",
        help="GE Multilin 'Standard' thermal curve shared across the 469/269Plus/369/869 lineage.")

    st.markdown("**Instantaneous (Short Circuit)**")
    inst_pickup_multiple_of_ct = st.number_input("Instantaneous Pickup (x CT secondary)", min_value=1.0, max_value=20.0, value=p_data["inst_pickup_multiple_of_ct"], step=0.1, key=f"{project_key}__inst_ct",
        help="Multiple of the CT's secondary rating (e.g. 9.7 x a 300:5 CT = 9.7 x 5A secondary = 9.7 x 300A primary).")
    inst_delay_ms = st.number_input("Instantaneous Delay (ms)", min_value=0.0, value=p_data["inst_delay_ms"], step=10.0, key=f"{project_key}__inst_delay")

    st.markdown("**Ground Fault**")
    gf_pickup_frac = st.number_input("GF Pickup (x Ground CT Primary A)", min_value=0.05, max_value=1.0, value=p_data["gf_pickup_frac"], step=0.05, key=f"{project_key}__gf_frac")
    gf_delay_ms = st.number_input("GF Delay (ms)", min_value=0.0, value=p_data["gf_delay_ms"], step=10.0, key=f"{project_key}__gf_delay")

    st.markdown("**Current Unbalance**")
    unbal_alarm_pct = st.number_input("Unbalance Alarm Pickup (%)", min_value=1.0, max_value=50.0, value=p_data["unbal_alarm_pct"], step=1.0, key=f"{project_key}__unb_alarm_pct")
    unbal_alarm_delay_s = st.number_input("Unbalance Alarm Delay (s)", min_value=0.0, value=p_data["unbal_alarm_delay_s"], step=1.0, key=f"{project_key}__unb_alarm_delay")
    unbal_trip_pct = st.number_input("Unbalance Trip Pickup (%)", min_value=1.0, max_value=50.0, value=p_data["unbal_trip_pct"], step=1.0, key=f"{project_key}__unb_trip_pct")
    unbal_trip_delay_s = st.number_input("Unbalance Trip Delay (s)", min_value=0.0, value=p_data["unbal_trip_delay_s"], step=1.0, key=f"{project_key}__unb_trip_delay")

    st.markdown("**Other Settings (reference only)**")
    mech_jam_pct = st.number_input("Mechanical Jam Pickup (% FLA)", min_value=100.0, value=p_data["mech_jam_pct"], step=5.0, key=f"{project_key}__jam_pct")
    mech_jam_delay_s = st.number_input("Mechanical Jam Delay (s)", min_value=0.0, value=p_data["mech_jam_delay_s"], step=0.5, key=f"{project_key}__jam_delay")
    accel_timer_s = st.number_input("Acceleration Timer (s)", min_value=1.0, value=p_data["accel_timer_s"], step=1.0, key=f"{project_key}__accel")
    overload_alarm_delay_s = st.number_input("Overload Alarm Delay (s)", min_value=0.0, value=p_data["overload_alarm_delay_s"], step=0.5, key=f"{project_key}__ovl_alarm_delay")
    phase_diff_pickup_frac = st.number_input("Phase Differential Pickup (x CT)", min_value=0.05, max_value=1.0, value=p_data["phase_diff_pickup_frac"], step=0.05, key=f"{project_key}__pdiff_frac")
    phase_diff_delay_ms = st.number_input("Phase Differential Delay (ms)", min_value=0.0, value=p_data["phase_diff_delay_ms"], step=10.0, key=f"{project_key}__pdiff_delay")

record_equipment_settings(project_key, {
    "motor_fla": motor_fla, "ct_ratio": ct_ratio, "ct_sec": ct_secondary_rating,
    "ground_ct_ratio": ground_ct_ratio, "ground_ct_sec": ct_secondary_rating,
    "overload_pickup_pct": overload_pickup_pct, "curve_multiplier": curve_multiplier,
    "inst_pickup_multiple_of_ct": inst_pickup_multiple_of_ct, "inst_delay_ms": inst_delay_ms,
    "mech_jam_pct": mech_jam_pct, "mech_jam_delay_s": mech_jam_delay_s,
    "unbal_trip_pct": unbal_trip_pct, "unbal_trip_delay_s": unbal_trip_delay_s,
    "unbal_alarm_pct": unbal_alarm_pct, "unbal_alarm_delay_s": unbal_alarm_delay_s,
    "gf_pickup_frac": gf_pickup_frac, "gf_delay_ms": gf_delay_ms,
    "phase_diff_pickup_frac": phase_diff_pickup_frac, "phase_diff_delay_ms": phase_diff_delay_ms,
    "accel_timer_s": accel_timer_s, "overload_alarm_delay_s": overload_alarm_delay_s,
    "rtd_stator_c": p_data["rtd_stator_c"], "ov_pickup_pu": p_data["ov_pickup_pu"], "ov_delay_s": p_data["ov_delay_s"],
    "of_hz": p_data["of_hz"], "uf_hz": p_data["uf_hz"],
    "underpower_kw": p_data["underpower_kw"], "underpower_delay_s": p_data["underpower_delay_s"],
    "starts_per_hour": p_data["starts_per_hour"], "time_between_starts_min": p_data["time_between_starts_min"],
})

relay = Motor869Relay(
    ct_ratio=ct_ratio, ct_secondary_rating=ct_secondary_rating, motor_fla=motor_fla,
    overload_pickup_pct=overload_pickup_pct, curve_multiplier=curve_multiplier,
    inst_pickup_multiple_of_ct=inst_pickup_multiple_of_ct, inst_delay_ms=inst_delay_ms,
    ground_ct_ratio=ground_ct_ratio, ground_ct_secondary_rating=ct_secondary_rating,
    gf_pickup_frac_of_ct=gf_pickup_frac, gf_delay_ms=gf_delay_ms,
    unbal_alarm_pct=unbal_alarm_pct, unbal_alarm_delay_s=unbal_alarm_delay_s,
    unbal_trip_pct=unbal_trip_pct, unbal_trip_delay_s=unbal_trip_delay_s,
    mech_jam_pct=mech_jam_pct, mech_jam_delay_s=mech_jam_delay_s,
    accel_timer_s=accel_timer_s, overload_alarm_delay_s=overload_alarm_delay_s,
)

tab_theory, tab1, tab2, tab3 = st.tabs([
    "Theory",
    "Live Simulation",
    "Commissioning & Injection Tool",
    "Settings Summary & Approval",
])

with tab_theory:
    render_theory_tab(
        "motor",
        purpose_text=fan_data["purpose"],
        sld_image_name="motor_idfan.png",
        sld_fallback_svg=motor_overcurrent_svg(
            ct_ratio, ct_secondary_rating, tag="869 MPR",
            bus_label="6.9kV Switchgear Bus", motor_label=fan_data["motor_tag"],
        ),
        include_thermal_replica=True,
    )

# ---------------------------------------------------------------------------
# TAB 1 — Live Simulation
# ---------------------------------------------------------------------------
with tab1:
    col_inputs, col_results = st.columns([1.0, 1.2])

    with col_inputs:
        st.subheader("Operating Current Input")
        st.caption("Enter the actual PRIMARY-side current in Amps — the app converts through the CT ratio automatically.")
        st.info(f"Motor FLA: **{motor_fla:.0f} A**  |  Instantaneous Pickup: **{relay.inst_pickup_amps:.0f} A primary**")

        test_current = st.number_input(
            "Phase Current (Primary A)", min_value=0.0, value=float(motor_fla), step=10.0, key=f"{project_key}__test_current",
            help="Try the motor FLA (should be SAFE) or the Instantaneous Pickup value to see each element respond."
        )
        ground_current = st.number_input(
            "Ground Current (Primary A)", min_value=0.0, value=0.0, step=1.0, key=f"{project_key}__ground_current",
            help="Zero-sequence current at the ground CT's primary."
        )
        unbalance_input = st.number_input(
            "Current Unbalance (%, I2/I1)", min_value=0.0, max_value=100.0, value=0.0, step=1.0, key=f"{project_key}__unbalance_input"
        )

    eval_result = relay.evaluate_protection(test_current)
    gf_eval = relay.evaluate_ground_fault(ground_current)
    unbal_eval = relay.evaluate_unbalance(unbalance_input)
    any_trip = eval_result["is_trip"] or gf_eval["is_trip"] or unbal_eval["is_trip"]

    with col_results:
        st.subheader("Real-time Protection Verdict")
        if any_trip:
            st.error("PROTECTIVE RELAY TRIP INITIATED!")
        else:
            st.success("SYSTEM HEALTHY")
        st.table([
            {"Function": "Overload (51) / Instantaneous (50)", "Multiple": f"{eval_result['multiple_of_fla']:.2f}x FLA", "Status": eval_result["status"]},
            {"Function": "Ground Fault (50G/51G)", "Multiple": f"{ground_current:.1f} A", "Status": gf_eval["status"]},
            {"Function": "Current Unbalance (46)", "Multiple": f"{unbalance_input:.1f} %", "Status": unbal_eval["status"]},
        ])

        pdf_bytes = generate_fan_motor_pdf_report(
            f"{fan_type} - {selected_preset}", relay, eval_result, gf_eval, unbal_eval,
            test_current, ground_current, unbalance_input,
        )
        st.download_button(
            label="Export Certified Protection Audit Report",
            data=pdf_bytes,
            file_name=f"{project_key}_Protection_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
        )

        render_settings_sheet(st, "GE Multilin 869", [
            ("CT Ratio", f"{ct_ratio:.0f}:{ct_secondary_rating:.0f}"),
            ("Ground CT Ratio", f"{ground_ct_ratio:.0f}:{ct_secondary_rating:.0f}"),
            ("Overload Pickup (% FLA)", f"{overload_pickup_pct:.0f}"),
            ("Curve Multiplier (CM)", f"{curve_multiplier:.1f}"),
            ("Instantaneous Pickup (x CT sec.)", f"{inst_pickup_multiple_of_ct:.1f}"),
            ("Instantaneous Delay (ms)", f"{inst_delay_ms:.0f}"),
            ("Ground Fault Pickup (x Ground CT)", f"{gf_pickup_frac:.2f}"),
            ("Ground Fault Delay (ms)", f"{gf_delay_ms:.0f}"),
            ("Unbalance Alarm/Trip (%)", f"{unbal_alarm_pct:.0f} / {unbal_trip_pct:.0f}"),
            ("Mechanical Jam Pickup (% FLA)", f"{mech_jam_pct:.0f}"),
        ], key_prefix=project_key.upper())

    st.markdown("---")
    st.markdown("#### Overload (51) Time-Current Characteristic")
    max_mult = max(6.0, eval_result["multiple_of_fla"] + 1.0)
    mult_line = np.linspace(1.01, max_mult, 300)
    t_line = [relay.calculate_overload_trip_time(m * motor_fla) for m in mult_line]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=mult_line, y=t_line, mode="lines", name=f"Curve X{curve_multiplier:g}", line=dict(color="#2563EB", width=3)))
    if eval_result["t51"] is not None:
        fig.add_trace(go.Scatter(
            x=[eval_result["multiple_of_fla"]], y=[eval_result["t51"]], mode="markers", name="Operating Point",
            marker=dict(size=14, color="red", symbol="x")
        ))
    fig.update_layout(
        title="GE 869 Overload Trip Time vs. Multiple of FLA",
        xaxis_title="Current (x Motor FLA)", yaxis_title="Trip Time (s)",
        yaxis_type="log", template="plotly_white", height=450,
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "GE Multilin 'Standard' thermal curve: T = CM x 2.2116623 / (0.025303373x(M-1)² + "
        "0.050547581x(M-1)), M = current as a multiple of motor FLA."
    )

    st.markdown("---")
    render_historian_overlay(st, project_key, reference_lines=[
        ("Motor FLA (A)", motor_fla),
        ("Instantaneous Pickup (A primary)", relay.inst_pickup_amps),
    ])

    st.markdown("---")
    st.markdown("#### Other GE 869 Functions — Settings Reference (not live-simulated)")
    st.dataframe(pd.DataFrame([
        {"Function": "Overload Alarm", "Setting": f"{overload_alarm_delay_s:.1f}s delay at Overload Pickup", "Note": "Early warning before the 51 trip"},
        {"Function": "Mechanical Jam Trip", "Setting": f"{mech_jam_pct:.0f}% FLA, {mech_jam_delay_s:.1f}s delay", "Note": "Disabled until after motor start"},
        {"Function": "Acceleration Timer", "Setting": f"{accel_timer_s:.0f}s", "Note": "Trips if current stays above Overload Pickup past this time after start"},
        {"Function": "Phase Differential (87)", "Setting": f"{phase_diff_pickup_frac:.2f}x CT, {phase_diff_delay_ms:.0f}ms delay", "Note": "Separate zero-sequence differential CTs"},
        {"Function": "Stator RTD Alarm/Trip", "Setting": f"{p_data['rtd_stator_c']}°C", "Note": "No bearing RTDs fitted on this motor"},
        {"Function": "Overvoltage (59)", "Setting": f"{p_data['ov_pickup_pu']:.2f} x rated, {p_data['ov_delay_s']:.0f}s delay", "Note": "Alarm only"},
        {"Function": "Over/Underfrequency (81)", "Setting": f"{p_data['of_hz']:.1f}Hz / {p_data['uf_hz']:.1f}Hz", "Note": "Alarm only"},
        {"Function": "Underpower (37)", "Setting": f"{p_data['underpower_kw']:.0f}kW, {p_data['underpower_delay_s']:.0f}s delay", "Note": "Detects lost/broken shaft coupling"},
        {"Function": "Jogging Block (66)", "Setting": f"{p_data['starts_per_hour']:.0f} starts/hour, {p_data['time_between_starts_min']:.0f} min between starts", "Note": ""},
        {"Function": "Phase Reversal", "Setting": "Enabled", "Note": ""},
    ]), use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# TAB 2 — Commissioning & Injection Tool
# ---------------------------------------------------------------------------
with tab2:
    st.subheader("Commissioning & Secondary Current Injection Assistant")
    st.write(
        "Pick a target multiple of the Overload Pickup to calculate the exact secondary Amps to "
        "inject at your test set, and see the expected trip time."
    )
    target_multiple = st.slider("Target Multiple of Motor FLA (M)", 1.05, 10.0, 3.9, 0.05, key=f"{project_key}__inj_multiple")
    inj_pri_amps = target_multiple * motor_fla
    inj_sec_amps = relay.relay_current(inj_pri_amps)
    expected_t = relay.calculate_overload_trip_time(inj_pri_amps)
    ic1, ic2, ic3 = st.columns(3)
    ic1.metric("Inject (primary A)", f"{inj_pri_amps:.1f} A")
    ic2.metric("Equivalent Secondary Current", f"{inj_sec_amps:.3f} A")
    ic3.metric("Expected Overload Trip Time", f"{expected_t:.2f}s" if expected_t is not None else "No Trip")

    st.markdown("---")
    st.subheader("Auto-Sweep Full Curve Test Table")
    sw1, sw2, sw3 = st.columns(3)
    with sw1:
        sweep_start = st.number_input("Sweep Start (Multiple of FLA)", value=1.5, min_value=1.05, step=0.1, key=f"{project_key}__sweep_start")
    with sw2:
        sweep_end = st.number_input("Sweep End (Multiple of FLA)", value=6.0, step=0.5, key=f"{project_key}__sweep_end")
    with sw3:
        sweep_step = st.number_input("Sweep Step (Multiple of FLA)", value=0.5, min_value=0.1, step=0.1, key=f"{project_key}__sweep_step")

    if st.button("Generate Sweep Table", key=f"{project_key}__sweep_btn"):
        if sweep_end <= sweep_start or sweep_step <= 0:
            st.error("Sweep End must be greater than Sweep Start, and Sweep Step must be positive.")
        else:
            sweep_points = np.arange(sweep_start, sweep_end + sweep_step / 2.0, sweep_step)
            sweep_rows = []
            for m in sweep_points:
                pri_amps = m * motor_fla
                t = relay.calculate_overload_trip_time(pri_amps)
                sweep_rows.append({
                    "Multiple of FLA (M)": round(float(m), 3),
                    "Primary Current (A)": round(pri_amps, 1),
                    "Secondary Current (A)": round(relay.relay_current(pri_amps), 3),
                    "Overload Trip Time (s)": round(t, 3) if t is not None else None,
                })
            st.session_state[f"{project_key}_sweep_df"] = pd.DataFrame(sweep_rows)

    if f"{project_key}_sweep_df" in st.session_state:
        st.dataframe(st.session_state[f"{project_key}_sweep_df"], use_container_width=True)
        csv_sweep = st.session_state[f"{project_key}_sweep_df"].to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Sweep Table as CSV",
            data=csv_sweep,
            file_name=f"{project_key}_Sweep_Test_Table_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            key=f"{project_key}__sweep_dl",
        )

# ---------------------------------------------------------------------------
# TAB 3 — Settings Summary & Approval
# ---------------------------------------------------------------------------
with tab3:
    st.subheader("Settings Summary & Approval Record")
    st.caption(
        "Record the settings basis and review status before exporting a controlled report. "
        "This record supports engineering review; it does not replace the approved protection study."
    )

    def _ensure(key, default):
        if key not in st.session_state:
            st.session_state[key] = default

    _ensure(f"{project_key}__source_document", "Data.xlsx (Motor Data sheet)")
    _ensure(f"{project_key}__revision", "Rev. 0")
    _ensure(f"{project_key}__prepared_by", "")
    _ensure(f"{project_key}__reviewed_by", "")
    _ensure(f"{project_key}__approval_status", "Draft — engineering review required")
    _ensure(f"{project_key}__review_note", "")

    source_document = st.text_input("Source document", key=f"{project_key}__source_document")
    col_doc_1, col_doc_2 = st.columns(2)
    with col_doc_1:
        revision = st.text_input("Document / settings revision", key=f"{project_key}__revision")
        prepared_by = st.text_input("Prepared by", key=f"{project_key}__prepared_by")
    with col_doc_2:
        reviewed_by = st.text_input("Reviewed by", key=f"{project_key}__reviewed_by")
        approval_status = st.selectbox(
            "Review status",
            ["Draft — engineering review required", "Reviewed — pending approval", "Approved for issue"],
            key=f"{project_key}__approval_status",
        )
    review_note = st.text_area("Review note / change description", key=f"{project_key}__review_note")

    st.markdown("### Applied Settings")
    summary_rows = [
        {"Category": "Motor", "Parameter": "Full-load current", "Value": f"{motor_fla:.0f} A"},
        {"Category": "CT", "Parameter": "Phase CT ratio", "Value": f"{ct_ratio:.0f}:{ct_secondary_rating:.0f}"},
        {"Category": "CT", "Parameter": "Ground CT ratio", "Value": f"{ground_ct_ratio:.0f}:{ct_secondary_rating:.0f}"},
        {"Category": "Overload", "Parameter": "Pickup / Curve Multiplier", "Value": f"{overload_pickup_pct:.0f}% FLA / CM {curve_multiplier:.1f}"},
        {"Category": "Instantaneous", "Parameter": "Pickup / Delay", "Value": f"{inst_pickup_multiple_of_ct:.1f}x CT sec. ({relay.inst_pickup_amps:.0f}A primary) / {inst_delay_ms:.0f}ms"},
        {"Category": "Ground Fault", "Parameter": "Pickup / Delay", "Value": f"{gf_pickup_frac:.2f}x Ground CT ({relay.gf_pickup_amps:.2f}A) / {gf_delay_ms:.0f}ms"},
        {"Category": "Unbalance", "Parameter": "Alarm / Trip", "Value": f"{unbal_alarm_pct:.0f}% / {unbal_trip_pct:.0f}%"},
    ]
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    st.markdown("### Coordination Review")
    checks = [
        {
            "label": "Instantaneous pickup above motor FLA",
            "passed": relay.inst_pickup_amps > motor_fla,
            "detail": f"{relay.inst_pickup_amps:.0f} A primary versus {motor_fla:.0f} A FLA",
        },
        {
            "label": "Overload pickup above 100% FLA",
            "passed": overload_pickup_pct > 100.0,
            "detail": f"Overload pickup set at {overload_pickup_pct:.0f}% FLA",
        },
    ]
    all_pass = all(c["passed"] for c in checks)
    if all_pass:
        st.success("All displayed coordination checks pass. Engineering approval is still required before issue.")
    else:
        st.error("One or more coordination checks require engineering review before approval.")
    st.dataframe(
        pd.DataFrame([{"Check": c["label"], "Result": "PASS" if c["passed"] else "REVIEW REQUIRED", "Basis": c["detail"]} for c in checks]),
        use_container_width=True, hide_index=True,
    )

    approval = {
        "source_document": source_document, "revision": revision,
        "prepared_by": prepared_by or "Not recorded", "reviewed_by": reviewed_by or "Not recorded",
        "approval_status": approval_status, "review_note": review_note or "None",
    }
    approval_pdf_bytes = generate_fan_motor_pdf_report(
        f"{fan_type} - {selected_preset}", relay, eval_result, gf_eval, unbal_eval,
        test_current, ground_current, unbalance_input, approval=approval,
    )
    st.download_button(
        label="Download Settings Summary & Approval Report (PDF)",
        data=approval_pdf_bytes,
        file_name=f"{project_key}_Settings_Summary_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
        mime="application/pdf",
        key=f"{project_key}__approval_pdf_dl",
    )

    settings_export = {
        "format": "Electrical Equipment Protection Suite settings",
        "version": 1,
        "equipment": project_key,
        "fan_type": fan_type,
        "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "settings": {
            "motor_fla": motor_fla, "ct_ratio": ct_ratio, "ct_sec": ct_secondary_rating,
            "ground_ct_ratio": ground_ct_ratio,
            "overload_pickup_pct": overload_pickup_pct, "curve_multiplier": curve_multiplier,
            "inst_pickup_multiple_of_ct": inst_pickup_multiple_of_ct, "inst_delay_ms": inst_delay_ms,
            "gf_pickup_frac": gf_pickup_frac, "gf_delay_ms": gf_delay_ms,
            "unbal_alarm_pct": unbal_alarm_pct, "unbal_alarm_delay_s": unbal_alarm_delay_s,
            "unbal_trip_pct": unbal_trip_pct, "unbal_trip_delay_s": unbal_trip_delay_s,
            "mech_jam_pct": mech_jam_pct, "mech_jam_delay_s": mech_jam_delay_s,
            "accel_timer_s": accel_timer_s, "overload_alarm_delay_s": overload_alarm_delay_s,
        },
    }
    st.download_button(
        label="Save Settings (.json)",
        data=json.dumps(settings_export, indent=2),
        file_name=f"{project_key}_Settings_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.json",
        mime="application/json",
        key=f"{project_key}__settings_json_dl",
        help="Download the active settings for later reload in this app.",
    )
