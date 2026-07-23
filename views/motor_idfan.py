import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common.pdf_report import generate_motor_pdf_report
from common.ui_helpers import slider_with_exact_input
from engines.motor import MotorTimeOvercurrentRelay, BackupInstantaneousRelay

st.title("🌀 Induced Draft (ID) Fan Motor Protection")
st.caption(
    "10,001HP, 13.2kV — GE IFC66KD2A electromechanical 50/50/51 time-overcurrent relay, "
    "with GE HFC22B2A backup instantaneous relay."
)

st.info(
    "ℹ️ This page covers the 50/50/51 (IFC66KD2A) and backup 50 (HFC22B2A) discrete "
    "overcurrent relays per the settings doc's Sections 5.1.1–5.1.2. The SR469 microprocessor "
    "Motor Protection Relay (MPR — Section 5.1.3, covering thermal overload model, ground "
    "fault, unbalance, RTD bias, and other multi-function elements) is not yet implemented."
)

# ---------------------------------------------------------------------------
# Presets — from Motor_Protection_Setting_-_IDFAN.pdf, Sections 5.1 / 5.1.1 / 5.1.2
# ---------------------------------------------------------------------------
PRESETS = {
    "POMI ID Fan 50/50/51 (7EM/8EM) - 10,001HP": {
        "motor_fla": 392, "locked_rotor_amps": 1869, "locked_rotor_amps_80pct": 1495,
        "accel_time_100": 12.6, "accel_time_80": 19.0,
        "safe_stall_100_ambient": 31.0, "safe_stall_80_ambient": 48.0,
        "safe_stall_100_hot": 28.0, "safe_stall_80_hot": 43.0,
        "ct_ratio": 600, "ct_sec": 5.0,
        "tap_51": 4.0, "time_dial": 4.5,
        "pickup_50a": 47.0, "dropout_50b": 3.3, "target_seal_in": 0.2,
        "backup_ct_ratio": 3000, "backup_pickup_50": 10.0,
    }
}

st.sidebar.header("📋 Equipment Presets")
selected_preset = st.sidebar.selectbox("Load Standard Profile", list(PRESETS.keys()))
p_data = PRESETS[selected_preset]

st.sidebar.header("1. Motor Data")
motor_fla = st.sidebar.number_input("Full Load Current (A)", value=float(p_data["motor_fla"]), step=1.0)
locked_rotor_amps = st.sidebar.number_input("Locked Rotor Current @ 100% V (A)", value=float(p_data["locked_rotor_amps"]), step=1.0)
locked_rotor_amps_80 = st.sidebar.number_input("Locked Rotor Current @ 80% V (A)", value=float(p_data["locked_rotor_amps_80pct"]), step=1.0)
accel_time_100 = st.sidebar.number_input("Acceleration Time @ 100% V (s)", value=p_data["accel_time_100"], step=0.1)
accel_time_80 = st.sidebar.number_input("Acceleration Time @ 80% V (s)", value=p_data["accel_time_80"], step=0.1)
safe_stall_100 = st.sidebar.number_input("Safe Stall Time @ 100% V, hot (s)", value=p_data["safe_stall_100_hot"], step=0.1,
    help="Using the 'after one start attempt' (hot) value — the more conservative of the two documented safe stall times.")
safe_stall_80 = st.sidebar.number_input("Safe Stall Time @ 80% V, hot (s)", value=p_data["safe_stall_80_hot"], step=0.1)

st.sidebar.header("2. CT Spec")
ct_ratio = st.sidebar.number_input("50/50/51 CT Ratio (Primary A, e.g. 600 in '600:5')", value=p_data["ct_ratio"])
ct_secondary_rating = st.sidebar.selectbox("CT Secondary Rating (A)", [1.0, 5.0], index=1, key="motor_ct_sec")
st.sidebar.caption(f"Effective ratio → **{ct_ratio/ct_secondary_rating:.1f}:1**")

st.sidebar.header("3. 51 (Long Time Inverse)")
tap_51_options = [2.5, 2.8, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.5]
tap_51 = st.sidebar.select_slider(
    "51 Tap (A sec.)", options=tap_51_options, value=p_data["tap_51"],
    help="IFC66KD2A range: 2.5-7.5A at these discrete taps."
)
time_dial = slider_with_exact_input(
    st.sidebar, "51 Time Dial", 0.5, 10.0, p_data["time_dial"], 0.1,
    key=f"{selected_preset}__time_dial",
    help_text="IFC66KD2A range: 1/2 to 10, continuously adjustable. Curve: GE IAC 'Long Time "
               "Inverse' 5-constant polynomial (GEK-106618C constants), calibrated to the "
               "settings doc's reference point of ~16s at 500% pickup."
)

st.sidebar.header("4. 50A / 50B (Instantaneous)")
pickup_50a = slider_with_exact_input(
    st.sidebar, "50A Pickup (A sec.)", 6.0, 150.0, p_data["pickup_50a"], 1.0,
    key=f"{selected_preset}__pickup_50a",
    help_text="IFC66KD2A range: L-tap 6-30A, H-tap 30-150A. Should be set at ~300% of locked "
               "rotor current to allow motor starting inrush."
)
dropout_50b = slider_with_exact_input(
    st.sidebar, "50B Dropout (A sec.)", 2.0, 8.0, p_data["dropout_50b"], 0.1,
    key=f"{selected_preset}__dropout_50b",
    help_text="IFC66KD2A range: L-tap 2-4A, H-tap 4-8A. High-dropout overload ALARM element — "
               "estimated pickup = dropout / 0.8 (per GEK-49949, dropout occurs above 80% of pickup)."
)
target_seal_in = st.sidebar.number_input("Target & Seal-in (A)", value=p_data["target_seal_in"], min_value=0.2, max_value=2.0, step=0.1)

st.sidebar.header("5. Backup Instantaneous (50)")
enable_backup = st.sidebar.checkbox("Enable HFC22B2A backup relay", value=True)
backup_ct_ratio = st.sidebar.number_input("Backup CT Ratio (Primary A, e.g. 3000 in '3000:5')", value=p_data["backup_ct_ratio"], disabled=not enable_backup)
backup_pickup_50 = st.sidebar.number_input("Backup 50 Pickup (A sec.)", value=p_data["backup_pickup_50"], min_value=2.0, max_value=50.0, step=0.5, disabled=not enable_backup)

relay = MotorTimeOvercurrentRelay(
    ct_ratio=ct_ratio, ct_secondary_rating=ct_secondary_rating,
    tap_51=tap_51, time_dial=time_dial,
    pickup_50a=pickup_50a, dropout_50b=dropout_50b, target_seal_in=target_seal_in,
    motor_fla=motor_fla, locked_rotor_amps=locked_rotor_amps,
)
backup_relay = BackupInstantaneousRelay(
    ct_ratio=backup_ct_ratio, ct_secondary_rating=ct_secondary_rating, pickup_amps=backup_pickup_50
) if enable_backup else None

tab1, tab2, tab3 = st.tabs(["📊 Live Simulation", "🧰 Commissioning & Injection Tool", "📈 TCC Curve"])

# ---------------------------------------------------------------------------
# TAB 1 — Live Simulation
# ---------------------------------------------------------------------------
with tab1:
    col_inputs, col_results = st.columns([1.0, 1.2])

    with col_inputs:
        st.subheader("Operating Current Input")
        st.caption("Enter the actual PRIMARY-side current in Amps — the app converts through the CT ratio automatically.")
        st.info(f"Motor FLA: **{motor_fla:.0f} A**  |  Locked Rotor: **{locked_rotor_amps:.0f} A** "
                f"({locked_rotor_amps/motor_fla:.1f}x FLA)")

        test_current = st.number_input(
            "Test Primary Current [A]", value=float(motor_fla), min_value=0.0, step=10.0,
            help="Try the motor FLA (392A, should be SAFE), locked rotor current (1869A, should "
                 "time-delay trip), or 50A pickup primary current to see each element respond."
        )

        eval_result = relay.evaluate_protection(test_current)
        backup_result = backup_relay.evaluate_protection(test_current) if backup_relay else None

    with col_results:
        st.subheader("Real-time Protection Verdict")

        if eval_result["is_trip"]:
            st.error(f"🚨 {eval_result['status']}")
        elif eval_result["alarm_50b"]:
            st.warning(f"⚠️ {eval_result['status']}")
        else:
            st.success("✅ SYSTEM HEALTHY (Below Pickup)")

        m1, m2, m3 = st.columns(3)
        m1.metric("Relay Secondary", f"{eval_result['i_relay_sec']:.3f} A")
        m2.metric("Multiple of 51 Pickup", f"{eval_result['multiple_of_pickup_51']:.2f}x")
        m3.metric("51 Trip Time", f"{eval_result['t51']:.2f}s" if eval_result["t51"] is not None else "No Trip")

        elem_rows = [
            {"Element": "51 (Long Time Inverse)", "State": "TRIP" if eval_result["trip_51"] else "Below Pickup",
             "Detail": f"{eval_result['t51']:.2f}s" if eval_result["t51"] is not None else "—"},
            {"Element": "50A (Instantaneous)", "State": "TRIP" if eval_result["trip_50a"] else "Below Pickup",
             "Detail": f"Pickup {relay.pickup_50a:.1f}A sec."},
            {"Element": "50B (Overload Alarm)", "State": "ALARM" if eval_result["alarm_50b"] else "Normal",
             "Detail": f"Est. pickup {relay.pickup_50b:.2f}A sec. / dropout {relay.dropout_50b:.2f}A sec."},
        ]
        if backup_result is not None:
            elem_rows.append({
                "Element": "50 (Backup, HFC22B2A)",
                "State": "TRIP" if backup_result["is_trip"] else "Below Pickup",
                "Detail": f"Pickup {backup_relay.pickup_amps:.1f}A sec. (higher-ratio CT, won't saturate)"
            })
        st.table(elem_rows)

        st.markdown("---")
        st.markdown("**Starting/Stall Margin Check**")
        t_at_lrc_100 = relay.calculate_51_trip_time(relay.relay_current(locked_rotor_amps))
        t_at_lrc_80 = relay.calculate_51_trip_time(relay.relay_current(locked_rotor_amps_80))
        c1, c2 = st.columns(2)
        with c1:
            ok_100 = t_at_lrc_100 is not None and accel_time_100 < t_at_lrc_100 < safe_stall_100
            st.write(f"**100% V:** 51 trips in {t_at_lrc_100:.1f}s at LRC" if t_at_lrc_100 else "**100% V:** No trip at LRC")
            st.write(f"Accel {accel_time_100}s < Trip < Safe Stall {safe_stall_100}s")
            if ok_100:
                st.success("✅ Margin OK")
            else:
                st.error("⚠️ Check margin")
        with c2:
            ok_80 = t_at_lrc_80 is not None and accel_time_80 < t_at_lrc_80 < safe_stall_80
            st.write(f"**80% V:** 51 trips in {t_at_lrc_80:.1f}s at LRC" if t_at_lrc_80 else "**80% V:** No trip at LRC")
            st.write(f"Accel {accel_time_80}s < Trip < Safe Stall {safe_stall_80}s")
            if ok_80:
                st.success("✅ Margin OK")
            else:
                st.error("⚠️ Check margin")

        pdf_bytes = generate_motor_pdf_report(
            selected_preset, relay, eval_result, test_current,
            backup_relay_obj=backup_relay, backup_eval_result=backup_result
        )
        st.download_button(
            label="📄 Export Certified Protection Audit Report",
            data=pdf_bytes,
            file_name=f"IDFan_Motor_Protection_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf"
        )

# ---------------------------------------------------------------------------
# TAB 2 — Commissioning & Injection Tool
# ---------------------------------------------------------------------------
with tab2:
    st.subheader("🧰 Commissioning & Secondary Current Injection Assistant")
    st.write(
        "Pick a target multiple of the 51 pickup to calculate the exact secondary Amps to "
        "inject at your test set, and see the expected trip time."
    )

    st.markdown("#### 🎯 51 Element Injection Calculator")
    ic1, ic2 = st.columns(2)
    with ic1:
        target_multiple = slider_with_exact_input(
            st, "Target Multiple of Pickup (M = I / Tap)", 1.05, 20.0, 3.9, 0.05,
            key=f"{selected_preset}__inj_multiple"
        )
    inj_sec_amps = target_multiple * relay.tap_51
    inj_pri_amps = inj_sec_amps * relay.effective_ratio
    expected_t = relay.calculate_51_trip_time(inj_sec_amps)
    with ic2:
        st.metric("Inject (secondary A)", f"{inj_sec_amps:.3f} A")
        st.metric("Equivalent Primary Current", f"{inj_pri_amps:.1f} A")
        st.metric("Expected 51 Trip Time", f"{expected_t:.2f}s" if expected_t is not None else "No Trip")

    st.markdown("---")
    st.subheader("🔁 Auto-Sweep Full Curve Test Table")
    sw1, sw2, sw3 = st.columns(3)
    with sw1:
        sweep_start = st.number_input("Sweep Start (Multiple)", value=1.5, min_value=1.05, step=0.1)
    with sw2:
        sweep_end = st.number_input("Sweep End (Multiple)", value=10.0, step=0.5)
    with sw3:
        sweep_step = st.number_input("Sweep Step (Multiple)", value=0.5, min_value=0.1, step=0.1)

    if st.button("▶️ Generate Sweep Table"):
        if sweep_end <= sweep_start or sweep_step <= 0:
            st.error("Sweep End must be greater than Sweep Start, and Sweep Step must be positive.")
        else:
            sweep_points = np.arange(sweep_start, sweep_end + sweep_step / 2.0, sweep_step)
            sweep_rows = []
            for m in sweep_points:
                sec_amps = m * relay.tap_51
                t = relay.calculate_51_trip_time(sec_amps)
                sweep_rows.append({
                    "Multiple (M)": round(float(m), 3),
                    "Inject (Secondary A)": round(sec_amps, 3),
                    "Equivalent Primary (A)": round(sec_amps * relay.effective_ratio, 1),
                    "51 Trip Time (s)": round(t, 3) if t is not None else None,
                })
            st.session_state["motor_sweep_df"] = pd.DataFrame(sweep_rows)

    if "motor_sweep_df" in st.session_state:
        st.dataframe(st.session_state["motor_sweep_df"], use_container_width=True)
        csv_sweep = st.session_state["motor_sweep_df"].to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️ Download Sweep Table as CSV",
            data=csv_sweep,
            file_name=f"50-51_Sweep_Test_Table_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )

# ---------------------------------------------------------------------------
# TAB 3 — TCC Curve
# ---------------------------------------------------------------------------
with tab3:
    st.subheader("📈 Time-Current Characteristic (TCC) Curve")
    st.write(
        "51 Long Time Inverse curve, plotted alongside the motor's starting profile "
        "(locked rotor current vs. acceleration time) and safe stall limits, plus the "
        "50A/50B/backup 50 pickup thresholds."
    )

    chart_units = st.radio("X-axis units", ["Multiple of 51 Tap", "Primary Amps (A)"], horizontal=True)
    use_amps_axis = chart_units == "Primary Amps (A)"

    m_range = np.linspace(1.01, 20.0, 400)
    t_range = [relay.calculate_51_trip_time(m * relay.tap_51) for m in m_range]
    x_51 = (m_range * relay.tap_51 * relay.effective_ratio) if use_amps_axis else m_range

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x_51, y=t_range, mode="lines", name="51 (Long Time Inverse)", line=dict(color="#2563EB", width=3)))

    # 50A instantaneous — vertical line
    x_50a = (relay.pickup_50a * relay.effective_ratio) if use_amps_axis else (relay.pickup_50a / relay.tap_51)
    fig.add_vline(x=x_50a, line=dict(color="#DC2626", width=2, dash="dash"), annotation_text="50A Pickup")

    # 50B alarm pickup — vertical line
    x_50b = (relay.pickup_50b * relay.effective_ratio) if use_amps_axis else (relay.pickup_50b / relay.tap_51)
    fig.add_vline(x=x_50b, line=dict(color="#F59E0B", width=2, dash="dot"), annotation_text="50B Alarm")

    # Backup 50 — vertical line, own primary-amp scale converted to this chart's x units
    if backup_relay is not None:
        x_backup = (backup_relay.pickup_amps * backup_relay.effective_ratio) if use_amps_axis else \
                   ((backup_relay.pickup_amps * backup_relay.effective_ratio) / relay.tap_51 / relay.effective_ratio)
        fig.add_vline(x=x_backup, line=dict(color="#7C3AED", width=2, dash="dashdot"), annotation_text="Backup 50")

    # Motor starting points (locked rotor current vs acceleration time)
    lrc_100_x = locked_rotor_amps if use_amps_axis else (relay.relay_current(locked_rotor_amps) / relay.tap_51)
    lrc_80_x = locked_rotor_amps_80 if use_amps_axis else (relay.relay_current(locked_rotor_amps_80) / relay.tap_51)

    fig.add_trace(go.Scatter(
        x=[lrc_100_x], y=[accel_time_100], mode="markers+text", name="Start @ 100% V",
        text=["Start @ 100%V"], textposition="top center",
        marker=dict(size=13, color="green", symbol="triangle-up")
    ))
    fig.add_trace(go.Scatter(
        x=[lrc_80_x], y=[accel_time_80], mode="markers+text", name="Start @ 80% V",
        text=["Start @ 80%V"], textposition="top center",
        marker=dict(size=13, color="darkgreen", symbol="triangle-up")
    ))
    fig.add_trace(go.Scatter(
        x=[lrc_100_x], y=[safe_stall_100], mode="markers+text", name="Safe Stall @ 100% V",
        text=["Safe Stall @ 100%V"], textposition="bottom center",
        marker=dict(size=13, color="black", symbol="x")
    ))
    fig.add_trace(go.Scatter(
        x=[lrc_80_x], y=[safe_stall_80], mode="markers+text", name="Safe Stall @ 80% V",
        text=["Safe Stall @ 80%V"], textposition="bottom center",
        marker=dict(size=13, color="gray", symbol="x")
    ))

    unit_label = "A (primary)" if use_amps_axis else "x Tap (M)"
    fig.update_layout(
        title="ID Fan Motor Protection TCC",
        xaxis_title=f"Current ({unit_label})",
        yaxis_title="Time (seconds)",
        xaxis_type="log", yaxis_type="log",
        template="plotly_white", height=550
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "The 51 curve should pass BELOW both safe-stall markers (X) and ABOVE both starting "
        "markers (▲) for correct coordination — i.e. the relay must not trip during a normal "
        "start, but must trip before the motor's insulation is thermally damaged on a stall."
    )
