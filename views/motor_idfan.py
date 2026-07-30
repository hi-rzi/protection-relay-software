import datetime
import hashlib
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common.pdf_report import generate_motor_pdf_report
from common.concepts import render_theory_tab
from common.sld import motor_overcurrent_svg
from common.ui_helpers import slider_with_exact_input
from common.settings_advisor import suggest_bias_settings
from common.project_state import with_restored_preset, record_equipment_settings
from common.historian import render_historian_overlay
from common.relay_settings_sheet import render_settings_sheet
from engines.motor import MotorTimeOvercurrentRelay, BackupInstantaneousRelay
from engines.motor_869 import Motor869Relay, hot_cold_safe_stall_ratio

st.title("Induced Draft (ID) Fan Motor Protection")
st.caption(
    "10,001HP, 13.2kV — GE IFC66KD2A electromechanical 50/50/51 time-overcurrent relay, "
    "GE HFC22B2A backup instantaneous relay, and GE 869 microprocessor Motor Protection Relay."
)

st.info(
    "This page covers the 50/50/51 (IFC66KD2A) and backup 50 (HFC22B2A) discrete "
    "overcurrent relays per the settings doc's Sections 5.1.1–5.1.2, plus the GE 869 "
    "microprocessor Motor Protection Relay (Section 5.1.3). The settings doc was written "
    "against the plant's originally-specified SR469, since superseded in service by the 869 — "
    "both share the same GE Multilin Thermal Capacity Used architecture, so the doc's "
    "current-based settings carry over directly. The 869's primary current-based elements "
    "(Overload thermal model, Instantaneous, Ground Fault, Current Unbalance) are live-simulated "
    "in the GE 869 MPR tab; its other functions (Mechanical Jam, Acceleration Timer, "
    "Overtemperature, Overvoltage, Jogging Block, Over/Underfrequency, Phase Differential, "
    "Underpower, Start Inhibit, Digital Inputs) are shown there as a documented settings "
    "reference, not live-simulated."
)

st.warning(
    "**Engineering review required.** This tool supports settings checks and commissioning "
    "calculations; it does not approve relay settings. Verify every result against the approved "
    "coordination study, relay manual, and site test procedure before applying settings in service."
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
        # GE 869 MPR (Section 5.1.3 - written against the legacy SR469, same thermal model)
        "mpr_ground_ct_ratio": 50, "mpr_gf_pickup_frac": 0.1, "mpr_gf_delay_ms": 60.0,
        "mpr_overload_pickup_pct": 115.0, "mpr_curve_multiplier": 4.0,
        "mpr_inst_multiple_lr": 2.0, "mpr_inst_delay_ms": 60.0,
        "mpr_unbal_alarm_pct": 15.0, "mpr_unbal_alarm_delay_s": 30.0,
        "mpr_unbal_trip_pct": 15.0, "mpr_unbal_trip_delay_s": 60.0,
        "mpr_mech_jam_pct": 150.0, "mpr_mech_jam_delay_s": 1.0,
        "mpr_accel_timer_s": 25.0, "mpr_overload_alarm_delay_s": 1.0,
    },
    "Custom Profile": {
        "motor_fla": 100, "locked_rotor_amps": 600, "locked_rotor_amps_80pct": 480,
        "accel_time_100": 10.0, "accel_time_80": 15.0,
        "safe_stall_100_ambient": 20.0, "safe_stall_80_ambient": 30.0,
        "safe_stall_100_hot": 18.0, "safe_stall_80_hot": 27.0,
        "ct_ratio": 100, "ct_sec": 5.0,
        "tap_51": 4.0, "time_dial": 5.0,
        "pickup_50a": 50.0, "dropout_50b": 3.0, "target_seal_in": 0.2,
        "backup_ct_ratio": 200, "backup_pickup_50": 10.0,
        "mpr_ground_ct_ratio": 50, "mpr_gf_pickup_frac": 0.1, "mpr_gf_delay_ms": 60.0,
        "mpr_overload_pickup_pct": 115.0, "mpr_curve_multiplier": 4.0,
        "mpr_inst_multiple_lr": 2.0, "mpr_inst_delay_ms": 60.0,
        "mpr_unbal_alarm_pct": 15.0, "mpr_unbal_alarm_delay_s": 30.0,
        "mpr_unbal_trip_pct": 15.0, "mpr_unbal_trip_delay_s": 60.0,
        "mpr_mech_jam_pct": 150.0, "mpr_mech_jam_delay_s": 1.0,
        "mpr_accel_timer_s": 25.0, "mpr_overload_alarm_delay_s": 1.0,
    },
}

MOTOR_CONFIG_FIELDS = (
    "motor_selected_preset", "motor_fla", "motor_lrc_100", "motor_lrc_80",
    "motor_accel_time_100", "motor_accel_time_80", "motor_safe_stall_100",
    "motor_safe_stall_80", "motor_safe_stall_100_cold", "motor_safe_stall_80_cold",
    "motor_ct_ratio", "motor_ct_sec", "motor_tap_51",
    "motor_time_dial", "motor_pickup_50a", "motor_dropout_50b",
    "motor_target_seal_in", "motor_enable_backup", "motor_backup_ct_ratio",
    "motor_backup_pickup_50", "motor_source_document", "motor_revision",
    "motor_prepared_by", "motor_reviewed_by", "motor_approval_status", "motor_review_note",
    "mpr_ground_ct_ratio", "mpr_gf_pickup_frac", "mpr_gf_delay_ms",
    "mpr_overload_pickup_pct", "mpr_curve_multiplier",
    "mpr_inst_multiple_lr", "mpr_inst_delay_ms",
    "mpr_unbal_alarm_pct", "mpr_unbal_alarm_delay_s",
    "mpr_unbal_trip_pct", "mpr_unbal_trip_delay_s",
    "mpr_mech_jam_pct", "mpr_mech_jam_delay_s",
    "mpr_accel_timer_s", "mpr_overload_alarm_delay_s",
)


def ensure_setting(key, default):
    """Set a default without overwriting a saved or user-entered value."""
    if key not in st.session_state:
        st.session_state[key] = default


def restore_motor_settings(uploaded_file):
    """Restore only known ID Fan settings from a user-exported JSON file."""
    file_bytes = uploaded_file.getvalue()
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    if st.session_state.get("motor_loaded_file_hash") == file_hash:
        return

    try:
        payload = json.loads(file_bytes.decode("utf-8"))
        if payload.get("equipment") != "id_fan_motor":
            raise ValueError("This is not an ID Fan Motor settings file.")
        settings = payload.get("settings")
        if not isinstance(settings, dict):
            raise ValueError("The file does not contain a settings section.")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        st.sidebar.error(f"Could not load settings file: {exc}")
        st.session_state["motor_loaded_file_hash"] = file_hash
        return

    selected_preset = settings.get("motor_selected_preset")
    if selected_preset is not None and selected_preset not in PRESETS:
        st.sidebar.error("The saved preset is not available in this version of the app.")
        st.session_state["motor_loaded_file_hash"] = file_hash
        return

    for key in MOTOR_CONFIG_FIELDS:
        if key in settings:
            st.session_state[key] = settings[key]

    for key in ("motor_time_dial", "motor_pickup_50a", "motor_dropout_50b"):
        if key in settings:
            st.session_state[f"{key}__slider"] = settings[key]
            st.session_state[f"{key}__number"] = settings[key]

    st.session_state["motor_loaded_file_hash"] = file_hash
    st.rerun()


st.sidebar.header("Settings File")
uploaded_settings = st.sidebar.file_uploader(
    "Load ID Fan settings (.json)", type=["json"], key="motor_settings_upload"
)
if uploaded_settings is not None:
    restore_motor_settings(uploaded_settings)

def _load_preset_into_state():
    """Force every field to the newly-selected preset's values, bypassing
    ensure_setting()'s "only if unset" guard - otherwise switching presets
    silently does nothing once the fields already hold a value."""
    pd_ = PRESETS_WITH_PROJECT[st.session_state["motor_selected_preset"]]
    plain_fields = {
        "motor_ct_ratio": float(pd_["ct_ratio"]), "motor_ct_sec": pd_["ct_sec"],
        "motor_tap_51": pd_["tap_51"], "motor_target_seal_in": pd_["target_seal_in"],
        "motor_backup_ct_ratio": float(pd_["backup_ct_ratio"]), "motor_backup_pickup_50": pd_["backup_pickup_50"],
        "motor_fla": float(pd_["motor_fla"]), "motor_lrc_100": float(pd_["locked_rotor_amps"]),
        "motor_lrc_80": float(pd_["locked_rotor_amps_80pct"]),
        "motor_accel_time_100": pd_["accel_time_100"], "motor_accel_time_80": pd_["accel_time_80"],
        "motor_safe_stall_100": pd_["safe_stall_100_hot"], "motor_safe_stall_80": pd_["safe_stall_80_hot"],
        "motor_safe_stall_100_cold": pd_["safe_stall_100_ambient"], "motor_safe_stall_80_cold": pd_["safe_stall_80_ambient"],
        "mpr_ground_ct_ratio": float(pd_["mpr_ground_ct_ratio"]), "mpr_gf_pickup_frac": pd_["mpr_gf_pickup_frac"],
        "mpr_gf_delay_ms": pd_["mpr_gf_delay_ms"],
        "mpr_overload_pickup_pct": pd_["mpr_overload_pickup_pct"], "mpr_curve_multiplier": pd_["mpr_curve_multiplier"],
        "mpr_inst_multiple_lr": pd_["mpr_inst_multiple_lr"], "mpr_inst_delay_ms": pd_["mpr_inst_delay_ms"],
        "mpr_unbal_alarm_pct": pd_["mpr_unbal_alarm_pct"], "mpr_unbal_alarm_delay_s": pd_["mpr_unbal_alarm_delay_s"],
        "mpr_unbal_trip_pct": pd_["mpr_unbal_trip_pct"], "mpr_unbal_trip_delay_s": pd_["mpr_unbal_trip_delay_s"],
        "mpr_mech_jam_pct": pd_["mpr_mech_jam_pct"], "mpr_mech_jam_delay_s": pd_["mpr_mech_jam_delay_s"],
        "mpr_accel_timer_s": pd_["mpr_accel_timer_s"], "mpr_overload_alarm_delay_s": pd_["mpr_overload_alarm_delay_s"],
    }
    for k, v in plain_fields.items():
        st.session_state[k] = v
    # slider_with_exact_input-backed fields track a slider/number sub-key pair too.
    for key, value in {"motor_time_dial": pd_["time_dial"], "motor_pickup_50a": pd_["pickup_50a"], "motor_dropout_50b": pd_["dropout_50b"]}.items():
        st.session_state[key] = value
        st.session_state[f"{key}__slider"] = value
        st.session_state[f"{key}__number"] = value


PRESETS_WITH_PROJECT = with_restored_preset(PRESETS, "motor")
st.sidebar.header("Equipment Presets")
ensure_setting("motor_selected_preset", next(iter(PRESETS_WITH_PROJECT)))
selected_preset = st.sidebar.selectbox(
    "Load Standard Profile", list(PRESETS_WITH_PROJECT.keys()), key="motor_selected_preset",
    on_change=_load_preset_into_state,
    help="Pick a built-in POMI relay, or Custom Profile to enter your own equipment's ratings, "
         "CT specs, and protection settings — this app isn't limited to POMI equipment."
)
p_data = PRESETS_WITH_PROJECT[selected_preset]

st.sidebar.header("Protection Characteristic")

ensure_setting("motor_ct_ratio", float(p_data["ct_ratio"]))
ensure_setting("motor_ct_sec", p_data["ct_sec"])

st.sidebar.markdown("**51 (Long Time Inverse)**")
tap_51_options = [2.5, 2.8, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.5]
ensure_setting("motor_tap_51", p_data["tap_51"])
tap_51 = st.sidebar.select_slider(
    "51 Tap (A sec.)", options=tap_51_options, key="motor_tap_51",
    help="IFC66KD2A range: 2.5-7.5A at these discrete taps."
)
time_dial = slider_with_exact_input(
    st.sidebar, "51 Time Dial", 0.5, 10.0, p_data["time_dial"], 0.1,
    key="motor_time_dial",
    help_text="IFC66KD2A range: 1/2 to 10, continuously adjustable. Curve: GE IAC 'Long Time "
               "Inverse' 5-constant polynomial (GEK-106618C constants), calibrated to the "
               "settings doc's reference point of ~16s at 500% pickup."
)

st.sidebar.markdown("**50A / 50B (Instantaneous)**")
pickup_50a = slider_with_exact_input(
    st.sidebar, "50A Pickup (A sec.)", 6.0, 150.0, p_data["pickup_50a"], 1.0,
    key="motor_pickup_50a",
    help_text="IFC66KD2A range: L-tap 6-30A, H-tap 30-150A. Should be set at ~300% of locked "
               "rotor current to allow motor starting inrush."
)
dropout_50b = slider_with_exact_input(
    st.sidebar, "50B Dropout (A sec.)", 2.0, 8.0, p_data["dropout_50b"], 0.1,
    key="motor_dropout_50b",
    help_text="IFC66KD2A range: L-tap 2-4A, H-tap 4-8A. High-dropout overload ALARM element — "
               "estimated pickup = dropout / 0.8 (per GEK-49949, dropout occurs above 80% of pickup)."
)
ensure_setting("motor_target_seal_in", p_data["target_seal_in"])
target_seal_in = st.sidebar.number_input("Target & Seal-in (A)", min_value=0.2, max_value=2.0, step=0.1, key="motor_target_seal_in")

st.sidebar.markdown("**Backup Instantaneous (50)**")
ensure_setting("motor_enable_backup", True)
ensure_setting("motor_backup_ct_ratio", float(p_data["backup_ct_ratio"]))
ensure_setting("motor_backup_pickup_50", p_data["backup_pickup_50"])
enable_backup = st.sidebar.checkbox("Enable HFC22B2A backup relay", key="motor_enable_backup")
backup_ct_ratio = st.sidebar.number_input("Backup CT Ratio (Primary A, e.g. 3000 in '3000:5')", min_value=1.0, key="motor_backup_ct_ratio", disabled=not enable_backup)
backup_pickup_50 = st.sidebar.number_input("Backup 50 Pickup (A sec.)", min_value=2.0, max_value=50.0, step=0.5, key="motor_backup_pickup_50", disabled=not enable_backup)

with st.sidebar.expander("Advanced Settings (Motor Data & CT Spec)", expanded=False):
    st.markdown("**Motor Data**")
    ensure_setting("motor_fla", float(p_data["motor_fla"]))
    ensure_setting("motor_lrc_100", float(p_data["locked_rotor_amps"]))
    ensure_setting("motor_lrc_80", float(p_data["locked_rotor_amps_80pct"]))
    ensure_setting("motor_accel_time_100", p_data["accel_time_100"])
    ensure_setting("motor_accel_time_80", p_data["accel_time_80"])
    ensure_setting("motor_safe_stall_100", p_data["safe_stall_100_hot"])
    ensure_setting("motor_safe_stall_80", p_data["safe_stall_80_hot"])
    ensure_setting("motor_safe_stall_100_cold", p_data["safe_stall_100_ambient"])
    ensure_setting("motor_safe_stall_80_cold", p_data["safe_stall_80_ambient"])
    motor_fla = st.number_input("Full Load Current (A)", min_value=1.0, step=1.0, key="motor_fla")
    locked_rotor_amps = st.number_input("Locked Rotor Current @ 100% V (A)", min_value=1.0, step=1.0, key="motor_lrc_100")
    locked_rotor_amps_80 = st.number_input("Locked Rotor Current @ 80% V (A)", min_value=1.0, step=1.0, key="motor_lrc_80")
    accel_time_100 = st.number_input("Acceleration Time @ 100% V (s)", min_value=0.1, step=0.1, key="motor_accel_time_100")
    accel_time_80 = st.number_input("Acceleration Time @ 80% V (s)", min_value=0.1, step=0.1, key="motor_accel_time_80")
    safe_stall_100 = st.number_input("Safe Stall Time @ 100% V, hot (s)", min_value=0.1, step=0.1, key="motor_safe_stall_100",
        help="Using the 'after one start attempt' (hot) value — the more conservative of the two documented safe stall times.")
    safe_stall_80 = st.number_input("Safe Stall Time @ 80% V, hot (s)", min_value=0.1, step=0.1, key="motor_safe_stall_80")
    safe_stall_100_cold = st.number_input("Safe Stall Time @ 100% V, cold (s)", min_value=0.1, step=0.1, key="motor_safe_stall_100_cold",
        help="The 'from ambient' (cold) safe stall time — used only to compute the GE 869's Hot/Cold Safe Stall Ratio (HCR), not for the coordination checks above.")
    safe_stall_80_cold = st.number_input("Safe Stall Time @ 80% V, cold (s)", min_value=0.1, step=0.1, key="motor_safe_stall_80_cold")

    st.markdown("**CT Spec**")
    ct_ratio = st.number_input("50/50/51 CT Ratio (Primary A, e.g. 600 in '600:5')", min_value=1.0, key="motor_ct_ratio")
    ct_secondary_rating = st.selectbox("CT Secondary Rating (A)", [1.0, 5.0], key="motor_ct_sec")
    st.caption(f"Effective ratio → **{ct_ratio/ct_secondary_rating:.1f}:1**")

relay = MotorTimeOvercurrentRelay(
    ct_ratio=ct_ratio, ct_secondary_rating=ct_secondary_rating,
    tap_51=tap_51, time_dial=time_dial,
    pickup_50a=pickup_50a, dropout_50b=dropout_50b, target_seal_in=target_seal_in,
    motor_fla=motor_fla, locked_rotor_amps=locked_rotor_amps,
)
backup_relay = BackupInstantaneousRelay(
    ct_ratio=backup_ct_ratio, ct_secondary_rating=ct_secondary_rating, pickup_amps=backup_pickup_50
) if enable_backup else None

with st.sidebar.expander("Advanced Settings (GE 869 MPR)", expanded=False):
    st.markdown("**Overload (51) Thermal Model**")
    ensure_setting("mpr_overload_pickup_pct", p_data["mpr_overload_pickup_pct"])
    ensure_setting("mpr_curve_multiplier", p_data["mpr_curve_multiplier"])
    mpr_overload_pickup_pct = st.number_input("Overload Pickup (% FLA)", min_value=100.0, max_value=125.0, step=1.0, key="mpr_overload_pickup_pct",
        help="Settings doc criterion: set to operate at 115% of motor FLA.")
    mpr_curve_multiplier = st.number_input("Curve Multiplier (CM)", min_value=1.0, max_value=8.0, step=0.5, key="mpr_curve_multiplier",
        help="GE Multilin 'Standard' thermal curve shared across the 469/269Plus/369/869 lineage, verified against the settings doc's Curve X4 worked examples.")

    st.markdown("**Instantaneous (50)**")
    ensure_setting("mpr_inst_multiple_lr", p_data["mpr_inst_multiple_lr"])
    ensure_setting("mpr_inst_delay_ms", p_data["mpr_inst_delay_ms"])
    mpr_inst_multiple_lr = st.number_input("Instantaneous Pickup (x Locked Rotor A)", min_value=1.0, max_value=5.0, step=0.1, key="mpr_inst_multiple_lr",
        help="Settings doc criterion: ~200% of locked rotor current.")
    mpr_inst_delay_ms = st.number_input("Instantaneous Delay (ms)", min_value=0.0, step=10.0, key="mpr_inst_delay_ms")

    st.markdown("**Ground Fault (50G/51G)**")
    ensure_setting("mpr_ground_ct_ratio", float(p_data["mpr_ground_ct_ratio"]))
    ensure_setting("mpr_gf_pickup_frac", p_data["mpr_gf_pickup_frac"])
    ensure_setting("mpr_gf_delay_ms", p_data["mpr_gf_delay_ms"])
    mpr_ground_ct_ratio = st.number_input("Ground (Zero-Sequence) CT Ratio (Primary A, e.g. 50 in '50:5')", min_value=1.0, key="mpr_ground_ct_ratio")
    mpr_gf_pickup_frac = st.number_input("GF Pickup (x Ground CT Primary A)", min_value=0.1, max_value=1.0, step=0.05, key="mpr_gf_pickup_frac",
        help="Settings doc: pickup is set on the ground CT's own primary rating, not the CT ratio - 0.1x600/5 ground CT = 5A primary here.")
    mpr_gf_delay_ms = st.number_input("GF Delay (ms)", min_value=0.0, step=10.0, key="mpr_gf_delay_ms")

    st.markdown("**Current Unbalance (46)**")
    ensure_setting("mpr_unbal_alarm_pct", p_data["mpr_unbal_alarm_pct"])
    ensure_setting("mpr_unbal_alarm_delay_s", p_data["mpr_unbal_alarm_delay_s"])
    ensure_setting("mpr_unbal_trip_pct", p_data["mpr_unbal_trip_pct"])
    ensure_setting("mpr_unbal_trip_delay_s", p_data["mpr_unbal_trip_delay_s"])
    mpr_unbal_alarm_pct = st.number_input("Unbalance Alarm Pickup (%)", min_value=1.0, max_value=50.0, step=1.0, key="mpr_unbal_alarm_pct")
    mpr_unbal_alarm_delay_s = st.number_input("Unbalance Alarm Delay (s)", min_value=0.0, step=1.0, key="mpr_unbal_alarm_delay_s")
    mpr_unbal_trip_pct = st.number_input("Unbalance Trip Pickup (%)", min_value=1.0, max_value=50.0, step=1.0, key="mpr_unbal_trip_pct")
    mpr_unbal_trip_delay_s = st.number_input("Unbalance Trip Delay (s)", min_value=0.0, step=1.0, key="mpr_unbal_trip_delay_s")

    st.markdown("**Other Settings (reference only)**")
    ensure_setting("mpr_mech_jam_pct", p_data["mpr_mech_jam_pct"])
    ensure_setting("mpr_mech_jam_delay_s", p_data["mpr_mech_jam_delay_s"])
    ensure_setting("mpr_accel_timer_s", p_data["mpr_accel_timer_s"])
    ensure_setting("mpr_overload_alarm_delay_s", p_data["mpr_overload_alarm_delay_s"])
    mpr_mech_jam_pct = st.number_input("Mechanical Jam Pickup (% FLA)", min_value=100.0, step=5.0, key="mpr_mech_jam_pct")
    mpr_mech_jam_delay_s = st.number_input("Mechanical Jam Delay (s)", min_value=0.0, step=0.5, key="mpr_mech_jam_delay_s")
    mpr_accel_timer_s = st.number_input("Acceleration Timer (s)", min_value=1.0, step=1.0, key="mpr_accel_timer_s")
    mpr_overload_alarm_delay_s = st.number_input("Overload Alarm Delay (s)", min_value=0.0, step=0.5, key="mpr_overload_alarm_delay_s")

with st.sidebar.expander("🧮 Settings Calculator (from ratings)", expanded=False):
    st.caption(
        "Derives a starting point FROM the motor data above — the 51 Tap suggestion is a hard "
        "formula (nearest available tap to FLA + margin); K-factor is GE Multilin's own two "
        "published variants; Overload Pickup is a rule-of-thumb starting point."
    )
    i_sec_at_fla = motor_fla / ct_ratio * ct_secondary_rating if ct_ratio > 0 else 0.0
    ideal_tap_51 = i_sec_at_fla * 1.15
    nearest_tap_51 = min(tap_51_options, key=lambda t: abs(t - ideal_tap_51))
    cc1, cc2 = st.columns(2)
    cc1.metric("Ideal 51 Tap (FLA + 15%)", f"{ideal_tap_51:.2f} A sec.")
    cc2.metric("Nearest available tap", f"{nearest_tap_51:.1f} A sec.")
    lr_multiple = (locked_rotor_amps / motor_fla) if motor_fla > 0 else 0.0
    k_conservative = (230.0 / (lr_multiple ** 2)) if lr_multiple > 0 else 0.0
    k_typical = (175.0 / (lr_multiple ** 2)) if lr_multiple > 0 else 0.0
    cc3, cc4 = st.columns(2)
    cc3.metric("K-factor (conservative)", f"{k_conservative:.2f}", help="K = 230 / (LRC ÷ FLA)² — currently used by the GE 869 MPR tab.")
    cc4.metric("K-factor (typical)", f"{k_typical:.2f}", help="K = 175 / (LRC ÷ FLA)² — GE Multilin's less-conservative published alternative.")
    st.markdown(
        "**Suggested starting point:** Overload Pickup ≈ **110-115% FLA** (GE Multilin guidance, "
        "matched to the motor's service factor); Instantaneous ≈ **200% locked-rotor current** "
        "(clears starting inrush, trips well below a genuine terminal fault)."
    )
    st.caption(
        "Engineering review required — these are starting points, not a substitute for a "
        "coordination study against the motor's actual thermal damage curve."
    )

record_equipment_settings("motor", {
    "motor_fla": motor_fla, "locked_rotor_amps": locked_rotor_amps, "locked_rotor_amps_80pct": locked_rotor_amps_80,
    "accel_time_100": accel_time_100, "accel_time_80": accel_time_80,
    "safe_stall_100_ambient": safe_stall_100_cold, "safe_stall_80_ambient": safe_stall_80_cold,
    "safe_stall_100_hot": safe_stall_100, "safe_stall_80_hot": safe_stall_80,
    "ct_ratio": ct_ratio, "ct_sec": ct_secondary_rating,
    "tap_51": tap_51, "time_dial": time_dial,
    "pickup_50a": pickup_50a, "dropout_50b": dropout_50b, "target_seal_in": target_seal_in,
    "backup_ct_ratio": backup_ct_ratio, "backup_pickup_50": backup_pickup_50,
    "mpr_ground_ct_ratio": mpr_ground_ct_ratio, "mpr_gf_pickup_frac": mpr_gf_pickup_frac, "mpr_gf_delay_ms": mpr_gf_delay_ms,
    "mpr_overload_pickup_pct": mpr_overload_pickup_pct, "mpr_curve_multiplier": mpr_curve_multiplier,
    "mpr_inst_multiple_lr": mpr_inst_multiple_lr, "mpr_inst_delay_ms": mpr_inst_delay_ms,
    "mpr_unbal_alarm_pct": mpr_unbal_alarm_pct, "mpr_unbal_alarm_delay_s": mpr_unbal_alarm_delay_s,
    "mpr_unbal_trip_pct": mpr_unbal_trip_pct, "mpr_unbal_trip_delay_s": mpr_unbal_trip_delay_s,
    "mpr_mech_jam_pct": mpr_mech_jam_pct, "mpr_mech_jam_delay_s": mpr_mech_jam_delay_s,
    "mpr_accel_timer_s": mpr_accel_timer_s, "mpr_overload_alarm_delay_s": mpr_overload_alarm_delay_s,
})

mpr_relay = Motor869Relay(
    ct_ratio=ct_ratio, ct_secondary_rating=ct_secondary_rating,
    motor_fla=motor_fla, locked_rotor_amps=locked_rotor_amps,
    overload_pickup_pct=mpr_overload_pickup_pct, curve_multiplier=mpr_curve_multiplier,
    inst_pickup_multiple_of_lr=mpr_inst_multiple_lr, inst_delay_ms=mpr_inst_delay_ms,
    ground_ct_ratio=mpr_ground_ct_ratio, gf_pickup_frac_of_ct=mpr_gf_pickup_frac, gf_delay_ms=mpr_gf_delay_ms,
    unbal_alarm_pct=mpr_unbal_alarm_pct, unbal_alarm_delay_s=mpr_unbal_alarm_delay_s,
    unbal_trip_pct=mpr_unbal_trip_pct, unbal_trip_delay_s=mpr_unbal_trip_delay_s,
    mech_jam_pct=mpr_mech_jam_pct, mech_jam_delay_s=mpr_mech_jam_delay_s,
    accel_timer_s=mpr_accel_timer_s, overload_alarm_delay_s=mpr_overload_alarm_delay_s,
)

tab_theory, tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Theory",
    "Live Simulation",
    "Commissioning & Injection Tool",
    "TCC Curve",
    "Settings Summary & Approval",
    "GE 869 MPR",
])

with tab_theory:
    render_theory_tab(
        "motor",
        purpose_text=(
            "The 50/50/51 (and GE 869) relays protect the Induced Draft Fan motor winding from "
            "thermal damage due to overload, locked rotor, or a short-circuit fault, while still "
            "allowing the motor to start normally. Induced Draft Fans are large, high-inertia "
            "loads — they take noticeably longer to reach full speed than a typical motor of "
            "similar size, so their acceleration time (seconds) sits much closer to their safe "
            "stall time (also seconds) than most motors. That's why this page tracks "
            "acceleration/safe-stall time at *both* 100% and 80% voltage separately — a voltage "
            "sag during start (from a nearby fault elsewhere in the system, for example) "
            "meaningfully lengthens how long the motor takes to reach speed, eating into the same "
            "margin the relay's time-delayed elements need to avoid tripping on a legitimate, if "
            "slow, start."
        ),
        sld_image_name="motor_idfan.png",
        sld_fallback_svg=motor_overcurrent_svg(
            ct_ratio, ct_secondary_rating,
            backup_ct_ratio=backup_ct_ratio if enable_backup else None,
            tag="50/50/51", backup_tag="50 (HFC22B2A)"
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
            st.error(f"{eval_result['status']}")
        elif eval_result["alarm_50b"]:
            st.warning(f"{eval_result['status']}")
        else:
            st.success("SYSTEM HEALTHY (Below Pickup)")

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
                st.success("Margin OK")
            else:
                st.error("Check margin")
        with c2:
            ok_80 = t_at_lrc_80 is not None and accel_time_80 < t_at_lrc_80 < safe_stall_80
            st.write(f"**80% V:** 51 trips in {t_at_lrc_80:.1f}s at LRC" if t_at_lrc_80 else "**80% V:** No trip at LRC")
            st.write(f"Accel {accel_time_80}s < Trip < Safe Stall {safe_stall_80}s")
            if ok_80:
                st.success("Margin OK")
            else:
                st.error("Check margin")

        st.markdown("---")
        st.markdown("**Engineering Input Checks**")
        st.caption("These checks highlight conditions that need engineering review; they are not automatic setting approvals.")

        pickup_51_primary = relay.tap_51 * relay.effective_ratio
        pickup_50a_primary = relay.pickup_50a * relay.effective_ratio
        pickup_50b_primary = relay.pickup_50b * relay.effective_ratio
        backup_pickup_primary = (
            backup_relay.pickup_amps * backup_relay.effective_ratio
            if backup_relay is not None else None
        )

        checks = [
            (
                "51 pickup above motor FLA",
                pickup_51_primary > motor_fla,
                f"51 pickup = {pickup_51_primary:.0f} A primary ({pickup_51_primary / motor_fla:.2f} × FLA)",
                "51 pickup is at or below motor FLA; review overload coordination.",
            ),
            (
                "50A pickup above locked-rotor current",
                pickup_50a_primary > locked_rotor_amps,
                f"50A pickup = {pickup_50a_primary:.0f} A primary ({pickup_50a_primary / locked_rotor_amps:.2f} × LRC)",
                "50A pickup is at or below locked-rotor current; a normal start could trip instantaneously.",
            ),
            (
                "50B alarm pickup above motor FLA",
                pickup_50b_primary > motor_fla,
                f"50B estimated pickup = {pickup_50b_primary:.0f} A primary ({pickup_50b_primary / motor_fla:.2f} × FLA)",
                "50B alarm pickup is at or below motor FLA; review the overload-alarm setting.",
            ),
            (
                "100% voltage safe-stall time exceeds acceleration time",
                safe_stall_100 > accel_time_100,
                f"Acceleration = {accel_time_100:.1f} s; safe stall = {safe_stall_100:.1f} s",
                "The 100% voltage safe-stall time is not greater than the acceleration time.",
            ),
            (
                "80% voltage safe-stall time exceeds acceleration time",
                safe_stall_80 > accel_time_80,
                f"Acceleration = {accel_time_80:.1f} s; safe stall = {safe_stall_80:.1f} s",
                "The 80% voltage safe-stall time is not greater than the acceleration time.",
            ),
        ]
        if backup_pickup_primary is not None:
            checks.append((
                "Backup 50 pickup above locked-rotor current",
                backup_pickup_primary > locked_rotor_amps,
                f"Backup 50 pickup = {backup_pickup_primary:.0f} A primary ({backup_pickup_primary / locked_rotor_amps:.2f} × LRC)",
                "Backup 50 pickup is at or below locked-rotor current; review starting security and coordination.",
            ))

        for label, passed, detail, review_note in checks:
            if passed:
                st.success(f"**{label}:** {detail}")
            else:
                st.error(f"**{label}:** {review_note} ({detail})")

        pdf_bytes = generate_motor_pdf_report(
            selected_preset, relay, eval_result, test_current,
            backup_relay_obj=backup_relay, backup_eval_result=backup_result
        )
        st.download_button(
            label="Export Certified Protection Audit Report",
            data=pdf_bytes,
            file_name=f"IDFan_Motor_Protection_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf"
        )

        _motor_sheet_rows = [
            ("CT Ratio", f"{ct_ratio:.0f}:{ct_secondary_rating:.0f}"),
            ("51 Tap (A sec.)", f"{tap_51:.2f}"),
            ("51 Time Dial", f"{time_dial:.2f}"),
            ("50A Pickup (A sec.)", f"{pickup_50a:.2f}"),
            ("50B Dropout (A sec.)", f"{dropout_50b:.2f}"),
            ("Target & Seal-in (A)", f"{target_seal_in:.2f}"),
        ]
        if enable_backup:
            _motor_sheet_rows += [
                ("Backup 50 CT Ratio", f"{backup_ct_ratio:.0f}:{ct_secondary_rating:.0f}"),
                ("Backup 50 Pickup (A sec.)", f"{backup_pickup_50:.2f}"),
            ]
        _motor_sheet_rows += [
            ("GE 869 Overload Pickup (% FLA)", f"{mpr_overload_pickup_pct:.0f}"),
            ("GE 869 Curve Multiplier (CM)", f"{mpr_curve_multiplier:.1f}"),
            ("GE 869 Instantaneous Pickup (x LR)", f"{mpr_inst_multiple_lr:.1f}"),
            ("GE 869 Ground CT Ratio", f"{mpr_ground_ct_ratio:.0f}:5"),
            ("GE 869 GF Pickup (x Ground CT)", f"{mpr_gf_pickup_frac:.2f}"),
            ("GE 869 Unbalance Alarm/Trip (%)", f"{mpr_unbal_alarm_pct:.0f} / {mpr_unbal_trip_pct:.0f}"),
        ]
        render_settings_sheet(st, "IFC66KD2A / GE 869", _motor_sheet_rows, key_prefix="IDFan")

# ---------------------------------------------------------------------------
# TAB 2 — Commissioning & Injection Tool
# ---------------------------------------------------------------------------
with tab2:
    st.subheader("Commissioning & Secondary Current Injection Assistant")
    st.write(
        "Pick a target multiple of the 51 pickup to calculate the exact secondary Amps to "
        "inject at your test set, and see the expected trip time."
    )

    st.markdown("#### 51 Element Injection Calculator")
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
    st.subheader("Auto-Sweep Full Curve Test Table")
    sw1, sw2, sw3 = st.columns(3)
    with sw1:
        sweep_start = st.number_input("Sweep Start (Multiple)", value=1.5, min_value=1.05, step=0.1)
    with sw2:
        sweep_end = st.number_input("Sweep End (Multiple)", value=10.0, step=0.5)
    with sw3:
        sweep_step = st.number_input("Sweep Step (Multiple)", value=0.5, min_value=0.1, step=0.1)

    if st.button("Generate Sweep Table"):
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
            label="Download Sweep Table as CSV",
            data=csv_sweep,
            file_name=f"50-51_Sweep_Test_Table_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )

# ---------------------------------------------------------------------------
# TAB 3 — TCC Curve
# ---------------------------------------------------------------------------
with tab3:
    st.subheader("Time-Current Characteristic (TCC) Curve")
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
        "markers () for correct coordination — i.e. the relay must not trip during a normal "
        "start, but must trip before the motor's insulation is thermally damaged on a stall."
    )

    st.markdown("---")
    render_historian_overlay(st, "motor", reference_lines=[
        ("Motor FLA (A)", motor_fla),
        ("51 Pickup (A primary)", relay.tap_51 * relay.effective_ratio),
        ("Locked Rotor Current (A)", locked_rotor_amps),
    ])


# ---------------------------------------------------------------------------
# TAB 4 — Settings Summary & Approval
# ---------------------------------------------------------------------------
with tab4:
    st.subheader("Settings Summary & Approval Record")
    st.caption(
        "Record the settings basis and review status before exporting a controlled report. "
        "This record supports engineering review; it does not replace the approved protection study."
    )

    ensure_setting("motor_source_document", "Motor Protection Setting - IDFAN.pdf")
    ensure_setting("motor_revision", "Rev. 0")
    ensure_setting("motor_prepared_by", "")
    ensure_setting("motor_reviewed_by", "")
    ensure_setting("motor_approval_status", "Draft — engineering review required")
    ensure_setting("motor_review_note", "")

    source_document = st.text_input("Source document", key="motor_source_document")
    col_doc_1, col_doc_2 = st.columns(2)
    with col_doc_1:
        revision = st.text_input("Document / settings revision", key="motor_revision")
        prepared_by = st.text_input("Prepared by", key="motor_prepared_by")
    with col_doc_2:
        reviewed_by = st.text_input("Reviewed by", key="motor_reviewed_by")
        approval_status = st.selectbox(
            "Review status",
            ["Draft — engineering review required", "Reviewed — pending approval", "Approved for issue"],
            key="motor_approval_status",
        )
    review_note = st.text_area("Review note / change description", key="motor_review_note")

    st.markdown("### Applied Settings")
    summary_rows = [
        {"Category": "Motor", "Parameter": "Full-load current", "Value": f"{motor_fla:.0f} A"},
        {"Category": "Motor", "Parameter": "Locked-rotor current", "Value": f"{locked_rotor_amps:.0f} A at 100% V / {locked_rotor_amps_80:.0f} A at 80% V"},
        {"Category": "CT", "Parameter": "50/50/51 CT ratio", "Value": f"{ct_ratio:.0f}:{ct_secondary_rating:.0f}"},
        {"Category": "51", "Parameter": "Tap / time dial", "Value": f"{tap_51:.2f} A sec. / {time_dial:.2f}"},
        {"Category": "50A", "Parameter": "Instantaneous pickup", "Value": f"{pickup_50a:.2f} A sec. ({pickup_50a * relay.effective_ratio:.0f} A primary)"},
        {"Category": "50B", "Parameter": "Alarm dropout / estimated pickup", "Value": f"{dropout_50b:.2f} / {relay.pickup_50b:.2f} A sec."},
    ]
    if backup_relay is not None:
        summary_rows.append({
            "Category": "Backup 50", "Parameter": "CT ratio / pickup",
            "Value": f"{backup_ct_ratio:.0f}:{ct_secondary_rating:.0f} / {backup_pickup_50:.2f} A sec.",
        })
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    st.markdown("### Coordination Review")
    trip_time_100 = f"{t_at_lrc_100:.1f} s" if t_at_lrc_100 is not None else "No trip"
    trip_time_80 = f"{t_at_lrc_80:.1f} s" if t_at_lrc_80 is not None else "No trip"
    summary_checks = [
        {
            "label": "51 pickup above motor FLA",
            "passed": relay.tap_51 * relay.effective_ratio > motor_fla,
            "detail": f"{relay.tap_51 * relay.effective_ratio:.0f} A primary versus {motor_fla:.0f} A FLA",
        },
        {
            "label": "50A pickup above locked-rotor current",
            "passed": relay.pickup_50a * relay.effective_ratio > locked_rotor_amps,
            "detail": f"{relay.pickup_50a * relay.effective_ratio:.0f} A primary versus {locked_rotor_amps:.0f} A LRC",
        },
        {
            "label": "51 coordination at 100% voltage",
            "passed": t_at_lrc_100 is not None and accel_time_100 < t_at_lrc_100 < safe_stall_100,
            "detail": f"Start {accel_time_100:.1f} s / trip {trip_time_100} / safe stall {safe_stall_100:.1f} s",
        },
        {
            "label": "51 coordination at 80% voltage",
            "passed": t_at_lrc_80 is not None and accel_time_80 < t_at_lrc_80 < safe_stall_80,
            "detail": f"Start {accel_time_80:.1f} s / trip {trip_time_80} / safe stall {safe_stall_80:.1f} s",
        },
    ]
    if backup_relay is not None:
        summary_checks.append({
            "label": "Backup 50 pickup above locked-rotor current",
            "passed": backup_relay.pickup_amps * backup_relay.effective_ratio > locked_rotor_amps,
            "detail": f"{backup_relay.pickup_amps * backup_relay.effective_ratio:.0f} A primary versus {locked_rotor_amps:.0f} A LRC",
        })

    all_checks_pass = all(check["passed"] for check in summary_checks)
    if all_checks_pass:
        st.success("All displayed coordination checks pass. Engineering approval is still required before issue.")
    else:
        st.error("One or more coordination checks require engineering review before approval.")
    st.dataframe(
        pd.DataFrame([
            {"Check": check["label"], "Result": "PASS" if check["passed"] else "REVIEW REQUIRED", "Basis": check["detail"]}
            for check in summary_checks
        ]),
        use_container_width=True,
        hide_index=True,
    )

    approval = {
        "source_document": source_document,
        "revision": revision,
        "prepared_by": prepared_by or "Not recorded",
        "reviewed_by": reviewed_by or "Not recorded",
        "approval_status": approval_status,
        "review_note": review_note or "None",
    }
    approval_pdf_bytes = generate_motor_pdf_report(
        selected_preset,
        relay,
        eval_result,
        test_current,
        backup_relay_obj=backup_relay,
        backup_eval_result=backup_result,
        approval=approval,
        coordination_checks=summary_checks,
    )
    st.download_button(
        label="Download Settings Summary & Approval Report (PDF)",
        data=approval_pdf_bytes,
        file_name=f"IDFan_Settings_Summary_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
        mime="application/pdf",
    )

    settings_export = {
        "format": "Electrical Equipment Protection Suite settings",
        "version": 1,
        "equipment": "id_fan_motor",
        "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "settings": {key: st.session_state[key] for key in MOTOR_CONFIG_FIELDS},
    }
    st.download_button(
        label="Save ID Fan Settings (.json)",
        data=json.dumps(settings_export, indent=2),
        file_name=f"IDFan_Settings_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.json",
        mime="application/json",
        help="Download the active settings and document-control fields for later reload in this app.",
    )

# ---------------------------------------------------------------------------
# TAB 5 — GE 869 Microprocessor MPR
# ---------------------------------------------------------------------------
with tab5:
    st.subheader("GE 869 Motor Management Relay (Multilin)")
    st.caption(
        "Per the settings doc's Section 5.1.3 (written against the plant's originally-specified "
        "SR469, since superseded in service by the 869 - same Thermal Capacity Used protection "
        "architecture, so the settings carry over directly). Live-simulates the primary "
        "current-based elements (Overload thermal model, Instantaneous, Ground Fault, Current "
        "Unbalance); the remaining functions are shown below as a documented settings reference."
    )
    st.info(f"K-factor (Unbalance Bias, per GE Multilin formula K = 230 / (Locked Rotor ÷ FLA)², "
            f"conservative variant): **{mpr_relay.k_factor:.2f}**")

    col_mpr_in, col_mpr_out = st.columns([1.1, 1.0])
    with col_mpr_in:
        st.markdown("#### Operating Current Input")
        mpr_test_current = st.number_input(
            "Phase Current (Primary A)", min_value=0.0, value=float(motor_fla), step=10.0, key="mpr_test_current",
            help="Enter the actual primary motor current — converted through the CT ratio automatically."
        )
        mpr_ground_current = st.number_input(
            "Ground Current (Primary A)", min_value=0.0, value=0.0, step=1.0, key="mpr_ground_current",
            help="Zero-sequence current at the ground CT's primary."
        )
        mpr_unbalance_input = st.number_input(
            "Current Unbalance (%, I2/I1)", min_value=0.0, max_value=100.0, value=0.0, step=1.0, key="mpr_unbalance_input"
        )

    mpr_eval = mpr_relay.evaluate_protection(mpr_test_current)
    mpr_gf_eval = mpr_relay.evaluate_ground_fault(mpr_ground_current)
    mpr_unbal_eval = mpr_relay.evaluate_unbalance(mpr_unbalance_input)
    mpr_any_trip = mpr_eval["is_trip"] or mpr_gf_eval["is_trip"] or mpr_unbal_eval["is_trip"]

    with col_mpr_out:
        st.markdown("#### Real-time Protection Verdict")
        if mpr_any_trip:
            st.error("GE 869 TRIP INITIATED!")
        else:
            st.success("SYSTEM HEALTHY")
        st.table([
            {"Function": "Overload (51) / Instantaneous (50)", "Multiple": f"{mpr_eval['multiple_of_fla']:.2f}x FLA", "Status": mpr_eval["status"]},
            {"Function": "Ground Fault (50G/51G)", "Multiple": f"{mpr_ground_current:.1f} A", "Status": mpr_gf_eval["status"]},
            {"Function": "Current Unbalance (46)", "Multiple": f"{mpr_unbalance_input:.1f} %", "Status": mpr_unbal_eval["status"]},
        ])

    st.markdown("---")
    st.markdown("#### Overload (51) Time-Current Characteristic")
    max_mult = max(6.0, mpr_eval["multiple_of_fla"] + 1.0)
    mult_line = np.linspace(1.01, max_mult, 300)
    t_line = [mpr_relay.calculate_overload_trip_time(m * motor_fla) for m in mult_line]
    mpr_fig = go.Figure()
    mpr_fig.add_trace(go.Scatter(x=mult_line, y=t_line, mode="lines", name=f"Curve X{mpr_curve_multiplier:g}", line=dict(color="#2563EB", width=3)))
    if mpr_eval["t51"] is not None:
        mpr_fig.add_trace(go.Scatter(
            x=[mpr_eval["multiple_of_fla"]], y=[mpr_eval["t51"]], mode="markers", name="Operating Point",
            marker=dict(size=14, color="red", symbol="x")
        ))
    mpr_fig.update_layout(
        title="GE 869 Overload Trip Time vs. Multiple of FLA",
        xaxis_title="Current (x Motor FLA)", yaxis_title="Trip Time (s)",
        yaxis_type="log", template="plotly_white", height=450,
    )
    st.plotly_chart(mpr_fig, use_container_width=True)
    st.caption(
        "GE Multilin 'Standard' thermal curve (shared across the 469/269Plus/369/869 lineage): "
        "T = CM x 2.2116623 / (0.025303373x(M-1)² + 0.050547581x(M-1)), M = current as a multiple "
        "of motor FLA - verified against the settings doc's own worked examples "
        "(4.8x FLA on Curve X4 = 15.9s; 3.8x FLA = 25.8s)."
    )

    st.markdown("---")
    st.markdown("#### Hot/Cold Safe Stall Ratio (Thermal Model Setup)")
    hcr_100 = hot_cold_safe_stall_ratio(safe_stall_100, safe_stall_100_cold)
    hcr_80 = hot_cold_safe_stall_ratio(safe_stall_80, safe_stall_80_cold)
    hcr_col1, hcr_col2 = st.columns(2)
    hcr_col1.metric("HCR @ 100% V", f"{hcr_100:.2f}" if hcr_100 is not None else "—",
                     help=f"= hot safe stall ({safe_stall_100:.1f}s) / cold safe stall ({safe_stall_100_cold:.1f}s)")
    hcr_col2.metric("HCR @ 80% V", f"{hcr_80:.2f}" if hcr_80 is not None else "—",
                     help=f"= hot safe stall ({safe_stall_80:.1f}s) / cold safe stall ({safe_stall_80_cold:.1f}s)")
    st.caption(
        "HCR = LRT_hot / LRT_cold, per GE Multilin's own thermal-model setup methodology — it tells the "
        "869 how much less thermal margin a motor that's already running hot has left before a stall "
        "becomes damaging, versus starting from cold. A ratio well below 1.0 means the relay must bias "
        "its trip time noticeably faster on a hot restart."
    )

    st.markdown("---")
    st.markdown("#### Other GE 869 Functions — Settings Reference (not live-simulated)")
    st.dataframe(pd.DataFrame([
        {"Function": "Overload Alarm", "Setting": f"{mpr_overload_alarm_delay_s:.1f}s delay at Overload Pickup", "Note": "Early warning before the 51 trip"},
        {"Function": "Mechanical Jam Trip", "Setting": f"{mpr_mech_jam_pct:.0f}% FLA, {mpr_mech_jam_delay_s:.1f}s delay", "Note": "Disabled until after motor start"},
        {"Function": "Acceleration Timer", "Setting": f"{mpr_accel_timer_s:.0f}s", "Note": "Trips if current stays above Overload Pickup past this time after start"},
        {"Function": "Overtemperature (38/49)", "Setting": "Alarm 135°C (stator), 90°C (bearing)", "Note": "Via RTDs/thermocouples to DCS, not read back by MPR"},
        {"Function": "RTD Bias", "Setting": "Min 40°C / Center 120°C / Max 155°C", "Note": "Biases the thermal model using stator RTD input"},
        {"Function": "Overvoltage (59)", "Setting": "106% rated, 60s delay", "Note": "Alarm only"},
        {"Function": "Jogging Block (66)", "Setting": "2 starts/hour, 20 min between starts", "Note": ""},
        {"Function": "Over/Underfrequency (81)", "Setting": "51.5Hz / 48.5Hz, 10s delay", "Note": "Alarm only"},
        {"Function": "Phase Differential (87)", "Setting": "0.1x CT (10A primary, 100:5 CT), 60ms delay", "Note": "Separate zero-sequence differential CTs"},
        {"Function": "Underpower (37)", "Setting": "300kW, ~20s Block-From-Start Timer", "Note": "Detects lost/broken shaft coupling"},
        {"Function": "Start Inhibit", "Setting": "Enabled (Block = OFF)", "Note": "Blocks a start the thermal model predicts will trip"},
        {"Function": "Digital Input 2", "Setting": "Vibration Switch Trip, 0.1s delay", "Note": ""},
    ]), use_container_width=True, hide_index=True)
