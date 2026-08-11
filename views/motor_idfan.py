import datetime
import hashlib
import json
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common.pdf_report import generate_motor_pdf_report
from common.concepts import render_theory_tab
from common.sld import motor_overcurrent_svg
from common.ui_helpers import slider_with_exact_input, sidebar_section_nav
from common.settings_advisor import suggest_bias_settings, suggest_time_overcurrent_settings
from common.project_state import with_restored_preset, record_equipment_settings
from common.historian import render_historian_overlay
from common.relay_settings_sheet import render_settings_sheet
from common.profile_io import safe_filename
from engines.motor import MotorTimeOvercurrentRelay, BackupInstantaneousRelay
from engines.motor_differential import SelfBalancingDifferentialRelay

st.title("Induced Draft (ID) Fan Motor Protection")
st.caption(
    "10,001HP, 13.2kV — GE IFC66KD2A electromechanical 50/50/51 time-overcurrent relay, "
    "GE HFC22B2A backup instantaneous relay, GE 869 microprocessor Motor Protection Relay, "
    "and GE HFC23C1A self-balancing differential (87M)."
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
        # 87M self-balancing differential (Section 5.13) - Induced Draft Fans use a
        # different, larger CT (100/5, Low tap) than every other motor (50/5, High tap).
        # Pickup is 20A primary either way: 20/(100/5) = 1.0A secondary here.
        "diff87m_ct_ratio": 100, "diff87m_pickup_sec": 1.0,
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
        "diff87m_ct_ratio": 50, "diff87m_pickup_sec": 2.0,
    },
}

MOTOR_CONFIG_FIELDS = (
    "motor_selected_preset", "motor_fla", "motor_lrc_100", "motor_lrc_80",
    "motor_accel_time_100", "motor_accel_time_80", "motor_safe_stall_100",
    "motor_safe_stall_80", "motor_safe_stall_100_cold", "motor_safe_stall_80_cold",
    "motor_ct_ratio", "motor_ct_sec", "motor_tap_51",
    "motor_time_dial", "motor_pickup_50a", "motor_dropout_50b",
    "motor_target_seal_in", "motor_enable_backup", "motor_backup_ct_ratio",
    "motor_backup_pickup_50", "motor_diff87m_ct_ratio", "motor_diff87m_pickup_sec",
    "motor_source_document", "motor_revision",
    "motor_prepared_by", "motor_reviewed_by", "motor_approval_status", "motor_review_note",
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
    st.toast(f"Loaded profile: {payload.get('profile_name', 'Untitled')}")
    st.rerun()


st.sidebar.header("Settings File")
uploaded_settings = st.sidebar.file_uploader(
    "Load a saved profile (.json)", type=["json"], key="motor_settings_upload"
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
        "motor_diff87m_ct_ratio": float(pd_["diff87m_ct_ratio"]), "motor_diff87m_pickup_sec": pd_["diff87m_pickup_sec"],
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

if st.sidebar.button(
    "↺ Reset to preset defaults", key="motor_reset_btn",
    help="Revert every Current Settings field below back to the selected preset's stock values.",
):
    _load_preset_into_state()
    st.toast(f"Reset to {selected_preset} defaults.")
    st.rerun()

if selected_preset != "Custom Profile":
    st.success(
        "✓ **Data confidence:** 50/50/51, 87M self-balancing differential, and backup "
        "instantaneous settings are all verified against Motor Protection Setting - IDFAN.pdf's "
        "own worked examples."
    )

# ---------------------------------------------------------------------------
# CURRENT SETTINGS — every applied setting, editable in place, with a live
# comment on whether an adjustment improves or weakens protection. Comments
# reuse the exact same checks already used elsewhere on this page (the old
# "Engineering Input Checks" in the Simulate & Test tab, and the "Starting/
# Stall Margin Check") - no new engineering judgment invented, just surfaced
# inline per-field instead of only after entering a test current.
# ---------------------------------------------------------------------------
sections = ["Current Settings", "Settings Calculator", "Theory", "Simulate & Test", "Commissioning & Injection Tool", "Settings Summary & Approval"]
selected, c, pinned = sidebar_section_nav(sections, key_prefix="idfan", pin_first=True)

with c["Current Settings"]:
    # Live preview, click to reveal, at the top of the tab. Reads CT Ratio, Tap, and Time Dial
    # straight from session_state (falling back to the preset default) since the actual settings
    # widgets are drawn further down this same tab and haven't run yet on this script pass. The
    # 87M element has no time-current curve (instantaneous, single pickup), so it isn't part of
    # this chart - its pickup value is shown in its own settings card further down instead.
    _pv_ct_ratio = st.session_state.get("motor_ct_ratio", float(p_data["ct_ratio"]))
    _pv_ct_sec = st.session_state.get("motor_ct_sec", p_data["ct_sec"])
    _pv_tap_51 = st.session_state.get("motor_tap_51", p_data["tap_51"])
    _pv_time_dial = st.session_state.get("motor_time_dial", p_data["time_dial"])
    _pv_probe = MotorTimeOvercurrentRelay(
        ct_ratio=_pv_ct_ratio, ct_secondary_rating=_pv_ct_sec, tap_51=_pv_tap_51, time_dial=_pv_time_dial,
        pickup_50a=1e9, dropout_50b=1e9,
    )
    if st.button(
        "📊 Show Live Preview — 51 (Long Time Inverse) Curve",
        key="idfan_show_preview_btn",
        help="Reflects the CT Ratio, 51 Tap, and Time Dial settings below as you adjust them. Starting/safe-stall overlay and commissioning tools are in the Simulate & Test section (sidebar).",
    ):
        st.session_state["idfan_preview_shown"] = True
    if st.session_state.get("idfan_preview_shown", False):
        _pv_m = np.linspace(1.01, 20.0, 200)
        _pv_effective_ratio = _pv_probe.effective_ratio
        _pv_x_amps = _pv_m * _pv_tap_51 * _pv_effective_ratio
        _pv_t = [_pv_probe.calculate_51_trip_time(m * _pv_tap_51) for m in _pv_m]
        _pv_y_lower = min(_pv_t) * 0.3
        _pv_y_upper = max(_pv_t) * 2.5
        _pv_fig = go.Figure()
        _pv_fig.add_trace(go.Scatter(
            x=_pv_x_amps, y=np.full_like(_pv_x_amps, _pv_y_lower), mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip",
        ))
        _pv_fig.add_trace(go.Scatter(
            x=_pv_x_amps, y=_pv_t, mode="lines", name="51", line=dict(color="#2563EB", width=3),
            fill="tonexty", fillcolor="rgba(22,163,74,0.10)",
        ))
        _pv_fig.add_trace(go.Scatter(
            x=_pv_x_amps, y=np.full_like(_pv_x_amps, _pv_y_upper), mode="lines", line=dict(width=0),
            fill="tonexty", fillcolor="rgba(220,38,38,0.08)", showlegend=False, hoverinfo="skip",
        ))
        _pv_fig.add_annotation(
            text="TRIP REGION (OPERATED)", xref="paper", yref="paper", x=0.98, y=0.95,
            showarrow=False, font=dict(size=12, color="#B91C1C"), xanchor="right", yanchor="top",
            bgcolor="rgba(255,255,255,0.75)",
        )
        _pv_fig.add_annotation(
            text="SAFE REGION (NOT YET TRIPPED)", xref="paper", yref="paper", x=0.02, y=0.05,
            showarrow=False, font=dict(size=12, color="#15803D"), xanchor="left", yanchor="bottom",
            bgcolor="rgba(255,255,255,0.75)",
        )
        _pv_fig.update_layout(
            xaxis_title="Current (A primary)", yaxis_title="Trip Time (s)",
            yaxis_type="log", template="plotly_white", height=320, margin=dict(t=20, b=40),
        )
        st.plotly_chart(_pv_fig, use_container_width=True, key="idfan_settings_preview_fig")
    st.markdown("---")

    st.markdown("## Current Settings")
    st.caption("Every setting currently applied to this relay. Adjust a value below and the comment beside it updates live.")

    ensure_setting("motor_ct_ratio", float(p_data["ct_ratio"]))
    ensure_setting("motor_ct_sec", p_data["ct_sec"])
    ensure_setting("motor_fla", float(p_data["motor_fla"]))
    ensure_setting("motor_lrc_100", float(p_data["locked_rotor_amps"]))
    ensure_setting("motor_lrc_80", float(p_data["locked_rotor_amps_80pct"]))
    ensure_setting("motor_accel_time_100", p_data["accel_time_100"])
    ensure_setting("motor_accel_time_80", p_data["accel_time_80"])
    ensure_setting("motor_safe_stall_100", p_data["safe_stall_100_hot"])
    ensure_setting("motor_safe_stall_80", p_data["safe_stall_80_hot"])
    ensure_setting("motor_safe_stall_100_cold", p_data["safe_stall_100_ambient"])
    ensure_setting("motor_safe_stall_80_cold", p_data["safe_stall_80_ambient"])
    ensure_setting("motor_diff87m_ct_ratio", float(p_data["diff87m_ct_ratio"]))
    ensure_setting("motor_diff87m_pickup_sec", p_data["diff87m_pickup_sec"])

    with st.container(border=True):
        st.markdown("**Motor Data & CT Spec**")
        m1c1, m1c2 = st.columns(2)
        with m1c1:
            motor_fla = st.number_input("Full Load Current (A)", min_value=1.0, step=1.0, key="motor_fla")
            locked_rotor_amps = st.number_input("Locked Rotor Current @ 100% V (A)", min_value=1.0, step=1.0, key="motor_lrc_100")
            locked_rotor_amps_80 = st.number_input("Locked Rotor Current @ 80% V (A)", min_value=1.0, step=1.0, key="motor_lrc_80")
            accel_time_100 = st.number_input("Acceleration Time @ 100% V (s)", min_value=0.1, step=0.1, key="motor_accel_time_100")
            accel_time_80 = st.number_input("Acceleration Time @ 80% V (s)", min_value=0.1, step=0.1, key="motor_accel_time_80")
        with m1c2:
            safe_stall_100 = st.number_input("Safe Stall Time @ 100% V, hot (s)", min_value=0.1, step=0.1, key="motor_safe_stall_100",
                help="Using the 'after one start attempt' (hot) value — the more conservative of the two documented safe stall times.")
            safe_stall_80 = st.number_input("Safe Stall Time @ 80% V, hot (s)", min_value=0.1, step=0.1, key="motor_safe_stall_80")
            safe_stall_100_cold = st.number_input("Safe Stall Time @ 100% V, cold (s)", min_value=0.1, step=0.1, key="motor_safe_stall_100_cold",
                help="The 'from ambient' (cold) safe stall time — used only to compute the GE 869's Hot/Cold Safe Stall Ratio (HCR), not for the coordination checks below.")
            safe_stall_80_cold = st.number_input("Safe Stall Time @ 80% V, cold (s)", min_value=0.1, step=0.1, key="motor_safe_stall_80_cold")
            ct_ratio = st.number_input("50/50/51 CT Ratio (Primary A, e.g. 600 in '600:5')", min_value=1.0, key="motor_ct_ratio")
            ct_secondary_rating = st.selectbox("CT Secondary Rating (A)", [1.0, 5.0], key="motor_ct_sec")
        st.caption(f"Effective ratio → **{ct_ratio/ct_secondary_rating:.1f}:1**")
        if safe_stall_100 > accel_time_100:
            st.success(f"Safe stall time @ 100% V ({safe_stall_100:.1f}s) exceeds acceleration time ({accel_time_100:.1f}s) — a normal start won't be mistaken for a stall.")
        else:
            st.warning(f"Safe stall time @ 100% V ({safe_stall_100:.1f}s) does not exceed acceleration time ({accel_time_100:.1f}s) — review this motor data before relying on the margin checks below.")
        if safe_stall_80 > accel_time_80:
            st.success(f"Safe stall time @ 80% V ({safe_stall_80:.1f}s) exceeds acceleration time ({accel_time_80:.1f}s) — a normal start won't be mistaken for a stall.")
        else:
            st.warning(f"Safe stall time @ 80% V ({safe_stall_80:.1f}s) does not exceed acceleration time ({accel_time_80:.1f}s) — review this motor data before relying on the margin checks below.")

    with st.container(border=True):
        st.markdown("**87M Self-Balancing Differential (GE HFC23C1A)**")
        st.caption(
            "A separate relay from the 50/50/51 above — both the line and neutral conductors of "
            "each phase pass through ONE current transformer here, so a healthy motor's current "
            "cancels to zero at the relay. Fitted to motors over 1500HP. Not restraint/bias-based "
            "and has no time-current curve — instantaneous, one pickup setting."
        )
        d87c1, d87c2 = st.columns(2)
        with d87c1:
            diff87m_ct_ratio = st.number_input(
                "87M CT Ratio (Primary A, e.g. 100 in '100:5')", min_value=1.0, step=1.0, key="motor_diff87m_ct_ratio",
                help="Induced Draft Fans use a 100/5 CT here — every other motor at this plant uses 50/5."
            )
        with d87c2:
            diff87m_pickup_sec = st.number_input(
                "87M Pickup (A sec.)", min_value=0.5, max_value=4.0, step=0.1, key="motor_diff87m_pickup_sec",
                help="HFC23C1A range: Low tap 0.5-2A, High tap 2-4A, continuously adjustable."
            )
        diff87m_pickup_primary = diff87m_pickup_sec * (diff87m_ct_ratio / ct_secondary_rating if ct_secondary_rating > 0 else diff87m_ct_ratio)
        if abs(diff87m_pickup_primary - 20.0) < 0.5:
            st.success(f"Pickup = {diff87m_pickup_primary:.1f} A primary — matches the settings doc's own 20A primary target for every 87M relay at this plant.")
        else:
            st.warning(f"Pickup = {diff87m_pickup_primary:.1f} A primary — the settings doc sets every 87M relay to 20A primary regardless of CT ratio; review this if the difference isn't intentional.")

    effective_ratio = ct_ratio / ct_secondary_rating if ct_secondary_rating > 0 else ct_ratio
    i_sec_at_fla = motor_fla / ct_ratio * ct_secondary_rating if ct_ratio > 0 else 0.0
    ideal_tap_51 = i_sec_at_fla * 1.15
    tap_51_options = [2.5, 2.8, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.5]
    nearest_tap_51 = min(tap_51_options, key=lambda t: abs(t - ideal_tap_51))

    with st.container(border=True):
        st.markdown("**51 (Long Time Inverse)**")
        st.caption(f"Ideal tap ≈ FLA + 15% = {ideal_tap_51:.2f} A sec. (nearest available: {nearest_tap_51:.1f} A sec.)")
        ensure_setting("motor_tap_51", p_data["tap_51"])
        t51c1, t51c2 = st.columns(2)
        with t51c1:
            tap_51 = st.select_slider(
                "51 Tap (A sec.)", options=tap_51_options, key="motor_tap_51",
                help="IFC66KD2A range: 2.5-7.5A at these discrete taps."
            )
            pickup_51_primary = tap_51 * effective_ratio
            if pickup_51_primary > motor_fla:
                st.success(f"Pickup {pickup_51_primary:.0f} A primary ({pickup_51_primary/motor_fla:.2f}x FLA) clears motor FLA.")
            else:
                st.warning(f"Pickup {pickup_51_primary:.0f} A primary is at or below motor FLA ({motor_fla:.0f} A) — review overload coordination.")
        with t51c2:
            time_dial = slider_with_exact_input(
                st, "51 Time Dial", 0.5, 10.0, p_data["time_dial"], 0.1,
                key="motor_time_dial",
                help_text="IFC66KD2A range: 1/2 to 10, continuously adjustable. Curve: GE IAC 'Long Time "
                           "Inverse' 5-constant polynomial (GEK-106618C constants), calibrated to the "
                           "settings doc's reference point of ~16s at 500% pickup."
            )
            # Probe relay just to evaluate the 51 trip-time formula against the starting
            # profile - 50A/50B fields aren't set yet at this point in the page, so dummy
            # (irrelevant-to-this-check) values are used for those two required args.
            _probe_51 = MotorTimeOvercurrentRelay(
                ct_ratio=ct_ratio, ct_secondary_rating=ct_secondary_rating,
                tap_51=tap_51, time_dial=time_dial, pickup_50a=1e9, dropout_50b=1e9,
                motor_fla=motor_fla, locked_rotor_amps=locked_rotor_amps,
            )
            t_at_lrc_100 = _probe_51.calculate_51_trip_time(_probe_51.relay_current(locked_rotor_amps))
            t_at_lrc_80 = _probe_51.calculate_51_trip_time(_probe_51.relay_current(locked_rotor_amps_80))
            ok_100 = t_at_lrc_100 is not None and accel_time_100 < t_at_lrc_100 < safe_stall_100
            ok_80 = t_at_lrc_80 is not None and accel_time_80 < t_at_lrc_80 < safe_stall_80
            t100_str = f"{t_at_lrc_100:.1f}s" if t_at_lrc_100 is not None else "no trip"
            t80_str = f"{t_at_lrc_80:.1f}s" if t_at_lrc_80 is not None else "no trip"
            if ok_100 and ok_80:
                st.success(f"Trips in {t100_str} @ 100%V / {t80_str} @ 80%V at locked rotor — inside the start/safe-stall margin both times. Lower time dial = faster trip (less thermal margin used on a stall) but less starting security.")
            else:
                st.warning(f"Trips in {t100_str} @ 100%V / {t80_str} @ 80%V at locked rotor — outside the start/safe-stall margin at one or both voltages. See the Simulate & Test tab for the full picture.")

    with st.container(border=True):
        st.markdown("**50A / 50B (Instantaneous)**")
        t50c1, t50c2 = st.columns(2)
        with t50c1:
            pickup_50a = slider_with_exact_input(
                st, "50A Pickup (A sec.)", 6.0, 150.0, p_data["pickup_50a"], 1.0,
                key="motor_pickup_50a",
                help_text="IFC66KD2A range: L-tap 6-30A, H-tap 30-150A. Should be set at ~300% of locked "
                           "rotor current to allow motor starting inrush."
            )
            pickup_50a_primary = pickup_50a * effective_ratio
            if pickup_50a_primary > locked_rotor_amps:
                st.success(f"Pickup {pickup_50a_primary:.0f} A primary ({pickup_50a_primary/locked_rotor_amps:.2f}x LRC) clears locked-rotor current — won't trip instantaneously on a normal start.")
            else:
                st.warning(f"Pickup {pickup_50a_primary:.0f} A primary is at or below locked-rotor current ({locked_rotor_amps:.0f} A) — a normal start could trip instantaneously.")
        with t50c2:
            dropout_50b = slider_with_exact_input(
                st, "50B Dropout (A sec.)", 2.0, 8.0, p_data["dropout_50b"], 0.1,
                key="motor_dropout_50b",
                help_text="IFC66KD2A range: L-tap 2-4A, H-tap 4-8A. High-dropout overload ALARM element — "
                           "estimated pickup = dropout / 0.8 (per GEK-49949, dropout occurs above 80% of pickup)."
            )
            pickup_50b_primary = (dropout_50b / 0.8) * effective_ratio
            if pickup_50b_primary > motor_fla:
                st.success(f"Estimated pickup {pickup_50b_primary:.0f} A primary ({pickup_50b_primary/motor_fla:.2f}x FLA) clears motor FLA.")
            else:
                st.warning(f"Estimated pickup {pickup_50b_primary:.0f} A primary is at or below motor FLA ({motor_fla:.0f} A) — review the overload-alarm setting.")
        ensure_setting("motor_target_seal_in", p_data["target_seal_in"])
        target_seal_in = st.number_input("Target & Seal-in (A)", min_value=0.2, max_value=2.0, step=0.1, key="motor_target_seal_in")

    with st.container(border=True):
        st.markdown("**Backup Instantaneous (50, HFC22B2A)**")
        ensure_setting("motor_enable_backup", True)
        ensure_setting("motor_backup_ct_ratio", float(p_data["backup_ct_ratio"]))
        ensure_setting("motor_backup_pickup_50", p_data["backup_pickup_50"])
        enable_backup = st.checkbox("Enable HFC22B2A backup relay", key="motor_enable_backup")
        bkc1, bkc2 = st.columns(2)
        with bkc1:
            backup_ct_ratio = st.number_input("Backup CT Ratio (Primary A, e.g. 3000 in '3000:5')", min_value=1.0, key="motor_backup_ct_ratio", disabled=not enable_backup)
        with bkc2:
            backup_pickup_50 = st.number_input("Backup 50 Pickup (A sec.)", min_value=2.0, max_value=50.0, step=0.5, key="motor_backup_pickup_50", disabled=not enable_backup)
        if enable_backup:
            backup_effective_ratio = backup_ct_ratio / ct_secondary_rating if ct_secondary_rating > 0 else backup_ct_ratio
            backup_pickup_primary = backup_pickup_50 * backup_effective_ratio
            if backup_pickup_primary > locked_rotor_amps:
                st.success(f"Pickup {backup_pickup_primary:.0f} A primary ({backup_pickup_primary/locked_rotor_amps:.2f}x LRC) clears locked-rotor current.")
            else:
                st.warning(f"Pickup {backup_pickup_primary:.0f} A primary is at or below locked-rotor current ({locked_rotor_amps:.0f} A) — review starting security and coordination.")
        else:
            st.caption("Backup relay disabled — not included in the checks below.")

    lr_multiple = (locked_rotor_amps / motor_fla) if motor_fla > 0 else 0.0
    k_conservative = (230.0 / (lr_multiple ** 2)) if lr_multiple > 0 else 0.0
    k_typical = (175.0 / (lr_multiple ** 2)) if lr_multiple > 0 else 0.0
    with st.expander("K-factor reference (GE 869 unbalance-bias formula, informational)", expanded=False):
        st.caption("Not used by this page's IFC66KD2A relay — reference only, in case a GE 869 MPR is later added for this motor.")
        kc1, kc2 = st.columns(2)
        kc1.metric("K-factor (conservative)", f"{k_conservative:.2f}", help="K = 230 / (LRC ÷ FLA)²")
        kc2.metric("K-factor (typical)", f"{k_typical:.2f}", help="K = 175 / (LRC ÷ FLA)² — GE Multilin's less-conservative published alternative.")

    relay = MotorTimeOvercurrentRelay(
        ct_ratio=ct_ratio, ct_secondary_rating=ct_secondary_rating,
        tap_51=tap_51, time_dial=time_dial,
        pickup_50a=pickup_50a, dropout_50b=dropout_50b, target_seal_in=target_seal_in,
        motor_fla=motor_fla, locked_rotor_amps=locked_rotor_amps,
    )
    backup_relay = BackupInstantaneousRelay(
        ct_ratio=backup_ct_ratio, ct_secondary_rating=ct_secondary_rating, pickup_amps=backup_pickup_50
    ) if enable_backup else None
    diff87m_relay = SelfBalancingDifferentialRelay(
        ct_ratio=diff87m_ct_ratio, ct_secondary_rating=ct_secondary_rating, pickup_amps_sec=diff87m_pickup_sec
    )

    all_clear = (
        pickup_51_primary > motor_fla
        and pickup_50a_primary > locked_rotor_amps
        and pickup_50b_primary > motor_fla
        and safe_stall_100 > accel_time_100
        and safe_stall_80 > accel_time_80
        and ok_100 and ok_80
        and (not enable_backup or backup_pickup_primary > locked_rotor_amps)
        and abs(diff87m_pickup_primary - 20.0) < 0.5
    )
    if all_clear:
        st.success("Overall status: all settings shown clear their recommended margins. Engineering approval is still required before issue.")
    else:
        st.warning("Overall status: one or more settings above need review before this is applied.")


record_equipment_settings("motor", {
    "motor_fla": motor_fla, "locked_rotor_amps": locked_rotor_amps, "locked_rotor_amps_80pct": locked_rotor_amps_80,
    "accel_time_100": accel_time_100, "accel_time_80": accel_time_80,
    "safe_stall_100_ambient": safe_stall_100_cold, "safe_stall_80_ambient": safe_stall_80_cold,
    "safe_stall_100_hot": safe_stall_100, "safe_stall_80_hot": safe_stall_80,
    "ct_ratio": ct_ratio, "ct_sec": ct_secondary_rating,
    "tap_51": tap_51, "time_dial": time_dial,
    "pickup_50a": pickup_50a, "dropout_50b": dropout_50b, "target_seal_in": target_seal_in,
    "backup_ct_ratio": backup_ct_ratio, "backup_pickup_50": backup_pickup_50,
    "diff87m_ct_ratio": diff87m_ct_ratio, "diff87m_pickup_sec": diff87m_pickup_sec,
})

with c["Settings Calculator"]:
    st.caption(
        "Enter motor ratings, CT, and starting/safe-stall data below to get a suggested "
        "settings sheet — a starting point, not a substitute for a coordination study. "
        "Prefilled from Current Settings, but independent of it: change a value here to test "
        "a scenario without touching your actual settings."
    )
    with st.container(border=True):
        st.markdown("**Motor & CT**")
        idcalc1, idcalc2 = st.columns(2)
        with idcalc1:
            calc_motor_fla = st.number_input("Motor Full Load Current (A)", min_value=1.0, value=float(motor_fla), step=1.0, key="idfan_calc_fla")
            calc_ct_ratio = st.number_input("CT Ratio (Primary A)", min_value=1.0, value=float(ct_ratio), step=1.0, key="idfan_calc_ct_ratio")
            calc_ct_sec = st.number_input("CT Secondary Rating (A)", min_value=1.0, value=float(ct_secondary_rating), step=1.0, key="idfan_calc_ct_sec")
        with idcalc2:
            calc_lrc_100 = st.number_input("Locked Rotor Current @ 100% V (A)", min_value=1.0, value=float(locked_rotor_amps), step=1.0, key="idfan_calc_lrc_100")
            calc_lrc_80 = st.number_input("Locked Rotor Current @ 80% V (A)", min_value=1.0, value=float(locked_rotor_amps_80), step=1.0, key="idfan_calc_lrc_80")
        st.markdown("**Starting & Safe Stall**")
        idcalc3, idcalc4 = st.columns(2)
        with idcalc3:
            calc_accel_100 = st.number_input("Acceleration Time @ 100% V (s)", min_value=0.1, value=float(accel_time_100), step=0.1, key="idfan_calc_accel_100")
            calc_accel_80 = st.number_input("Acceleration Time @ 80% V (s)", min_value=0.1, value=float(accel_time_80), step=0.1, key="idfan_calc_accel_80")
        with idcalc4:
            calc_stall_100 = st.number_input("Safe Stall Time @ 100% V (s)", min_value=0.1, value=float(safe_stall_100), step=0.1, key="idfan_calc_stall_100")
            calc_stall_80 = st.number_input("Safe Stall Time @ 80% V (s)", min_value=0.1, value=float(safe_stall_80), step=0.1, key="idfan_calc_stall_80")

    idc_suggestion = suggest_time_overcurrent_settings(
        motor_fla=calc_motor_fla, ct_ratio=calc_ct_ratio, ct_secondary_rating=calc_ct_sec,
        locked_rotor_amps_100=calc_lrc_100, locked_rotor_amps_80=calc_lrc_80,
        accel_time_100=calc_accel_100, accel_time_80=calc_accel_80,
        safe_stall_100=calc_stall_100, safe_stall_80=calc_stall_80,
    )
    idc1, idc2 = st.columns(2)
    with idc1:
        with st.container(border=True):
            st.markdown("#### 51 Tap")
            st.metric("Suggested", f"{idc_suggestion['tap_51']:.1f} A sec.")
            st.caption(idc_suggestion["basis_tap_51"])
    with idc2:
        with st.container(border=True):
            st.markdown("#### 51 Time Dial")
            st.metric("Suggested", f"{idc_suggestion['time_dial']:.1f}")
            st.caption(idc_suggestion["basis_time_dial"])
    idc3, idc4 = st.columns(2)
    with idc3:
        with st.container(border=True):
            st.markdown("#### 50A Pickup")
            st.metric("Suggested", f"{idc_suggestion['pickup_50a']:.1f} A sec." if idc_suggestion["pickup_50a"] is not None else "—")
            st.caption(idc_suggestion["basis_pickup_50a"])
    with idc4:
        with st.container(border=True):
            st.markdown("#### 50B Dropout")
            st.metric("Suggested", f"{idc_suggestion['dropout_50b']:.2f} A sec." if idc_suggestion["dropout_50b"] is not None else "—")
            st.caption(idc_suggestion["basis_dropout_50b"])

with c["Theory"]:
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
# TAB — Simulate & Test (Live Simulation + TCC Curve & Test Points)
# ---------------------------------------------------------------------------
with c["Simulate & Test"]:
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
        diff87m_test_imbalance = st.number_input(
            "87M Imbalance Test Current [A]", value=0.0, min_value=0.0, step=1.0,
            help="The NET (line minus neutral) current through the self-balancing CT — zero for "
                 "a healthy motor. Try the pickup primary current above to see it trip."
        )

        eval_result = relay.evaluate_protection(test_current)
        backup_result = backup_relay.evaluate_protection(test_current) if backup_relay else None
        diff87m_result = diff87m_relay.evaluate_protection(diff87m_test_imbalance)

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
        elem_rows.append({
            "Element": "87M (Self-Balancing Differential)",
            "State": "TRIP" if diff87m_result["is_trip"] else "Below Pickup",
            "Detail": f"Pickup {diff87m_relay.pickup_amps_sec:.1f}A sec. ({diff87m_relay.pickup_amps_primary:.0f}A primary) — separate CT from the elements above"
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
        render_settings_sheet(st, "IFC66KD2A", _motor_sheet_rows, key_prefix="IDFan")

        render_settings_sheet(st, "GE HFC23C1A", [
            ("87M CT Ratio", f"{diff87m_ct_ratio:.0f}:{ct_secondary_rating:.0f}"),
            ("87M Pickup (A sec.)", f"{diff87m_pickup_sec:.2f}"),
            ("87M Tap", "High" if diff87m_pickup_sec >= 2.0 else "Low"),
        ], key_prefix="IDFan_87M")

    st.markdown("---")
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

    st.markdown("---")
    st.markdown("#### Fault Clearing Time Simulation")
    st.caption(
        "Feeds a fault current through the same evaluate_protection() logic used above, "
        "then adds a typical breaker operating time to show how long the "
        "current actually flows before it's cleared. The 51 element's trip time comes "
        "straight from the curve above; the 50A instantaneous element's own operate time "
        "below is a typical value for this class of equipment, not confirmed against this "
        "relay's own manual."
    )

    idfan_fault_scenario = st.radio(
        "Fault Scenario",
        ["Locked Rotor / Stall", "Short-Circuit Fault"],
        key="idfan_fault_sim_scenario",
        horizontal=True,
        help=(
            "Locked Rotor / Stall: uses this motor's own Locked Rotor Current @ 100% V — "
            "normally only enough to exercise the 51 time-overcurrent curve, not the "
            "instantaneous element. Short-Circuit Fault: a current above the 50A pickup, to "
            "show the instantaneous element operating instead."
        ),
    )
    idfan_fc1, idfan_fc2 = st.columns(2)
    with idfan_fc1:
        idfan_relay_op_cycles = st.number_input(
            "50A Instantaneous Operate Time (cycles)", min_value=0.25, max_value=10.0, value=1.0, step=0.25,
            key="idfan_relay_op_cycles",
            help="Time from fault inception to the 50A element issuing a trip signal — electromechanical instantaneous elements of this class are typically under 1-2 cycles. Not a figure confirmed against this relay's own manual."
        )
    with idfan_fc2:
        idfan_breaker_cycles = st.number_input(
            "Breaker Interrupting Time (cycles)", min_value=1.0, max_value=15.0, value=5.0, step=0.5,
            key="idfan_breaker_cycles",
            help="Time from trip coil energization to fault current interruption — typical motor breakers/contactors are 3-5 cycles. Not confirmed against this plant's own breaker nameplate."
        )

    idfan_cycle_ms = 1000.0 / 60.0
    idfan_preload_ms = 40.0
    idfan_preload_current = motor_fla
    if idfan_fault_scenario.startswith("Locked"):
        idfan_sim_current = locked_rotor_amps
    else:
        idfan_sim_current = relay.pickup_50a * relay.effective_ratio * 1.5
    idfan_sim_eval = relay.evaluate_protection(idfan_sim_current)

    idfan_run_sim = st.button(
        "▶ Run Fault Simulation", key="idfan_run_fault_sim",
        help="Plays back the fault step by step: current spikes, the relay detects it, then the trip signal reaches the breaker."
    )
    idfan_sim_caption_ph = st.empty()
    idfan_sim_chart_ph = st.empty()
    idfan_done_key = "idfan_fault_sim_last"

    def _idfan_fault_sim_base_fig():
        fig = go.Figure()
        fig.update_layout(
            xaxis_title="Time (ms, t=0 is fault inception)", yaxis_title="Primary Current (A)",
            template="plotly_white", height=340, margin=dict(t=20, b=40),
        )
        return fig

    if idfan_run_sim:
        if idfan_sim_eval["trip_50a"]:
            idfan_relay_ms = idfan_relay_op_cycles * idfan_cycle_ms
            idfan_total_ms = idfan_relay_ms + idfan_breaker_cycles * idfan_cycle_ms

            idfan_sim_caption_ph.warning(f"⚡ Fault occurs at t=0 — current spikes to {idfan_sim_current:,.0f} A primary.")
            fig1 = _idfan_fault_sim_base_fig()
            fig1.add_trace(go.Scatter(
                x=[-idfan_preload_ms, 0, 0], y=[idfan_preload_current, idfan_preload_current, idfan_sim_current],
                mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
            ))
            idfan_sim_chart_ph.plotly_chart(fig1, use_container_width=True, key="idfan_fault_sim_f1")
            time.sleep(0.9)

            idfan_sim_caption_ph.warning(f"🔍 The 50A instantaneous element detects the fault and issues a trip signal at t={idfan_relay_ms:.0f} ms — {idfan_sim_eval['status']}.")
            fig2 = _idfan_fault_sim_base_fig()
            fig2.add_trace(go.Scatter(
                x=[-idfan_preload_ms, 0, 0, idfan_relay_ms], y=[idfan_preload_current, idfan_preload_current, idfan_sim_current, idfan_sim_current],
                mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
            ))
            fig2.add_vline(x=idfan_relay_ms, line=dict(color="#F59E0B", width=2, dash="dot"), annotation_text="50A Trips")
            idfan_sim_chart_ph.plotly_chart(fig2, use_container_width=True, key="idfan_fault_sim_f2")
            time.sleep(0.9)

            idfan_sim_caption_ph.success(f"✅ Trip signal reaches the breaker — it interrupts the fault at t={idfan_total_ms:.0f} ms. Total clearing time: {idfan_total_ms:.0f} ms ({idfan_total_ms / idfan_cycle_ms:.1f} cycles).")
            fig3 = _idfan_fault_sim_base_fig()
            fig3.add_trace(go.Scatter(
                x=[-idfan_preload_ms, 0, 0, idfan_total_ms, idfan_total_ms, idfan_total_ms + 40.0],
                y=[idfan_preload_current, idfan_preload_current, idfan_sim_current, idfan_sim_current, 0.0, 0.0],
                mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
            ))
            fig3.add_vline(x=idfan_relay_ms, line=dict(color="#F59E0B", width=2, dash="dot"), annotation_text="50A Trips")
            fig3.add_vline(x=idfan_total_ms, line=dict(color="#16A34A", width=2, dash="dash"), annotation_text="Breaker Clears")
            idfan_sim_chart_ph.plotly_chart(fig3, use_container_width=True, key="idfan_fault_sim_f3")

            st.session_state[idfan_done_key] = {
                "kind": "trip", "status": idfan_sim_eval["status"], "relay_ms": idfan_relay_ms, "total_ms": idfan_total_ms,
                "sim_current": idfan_sim_current, "preload_current": idfan_preload_current, "log_x": False,
            }
        elif idfan_sim_eval["trip_51"]:
            idfan_relay_ms = idfan_sim_eval["t51"] * 1000.0
            idfan_total_ms = idfan_relay_ms + idfan_breaker_cycles * idfan_cycle_ms

            idfan_sim_caption_ph.warning(f"⚡ Fault occurs at t=0 — current rises to {idfan_sim_current:,.0f} A primary (locked rotor).")
            fig1 = _idfan_fault_sim_base_fig()
            fig1.add_trace(go.Scatter(
                x=[-idfan_preload_ms, 0, 0], y=[idfan_preload_current, idfan_preload_current, idfan_sim_current],
                mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
            ))
            fig1.update_xaxes(type="log")
            idfan_sim_chart_ph.plotly_chart(fig1, use_container_width=True, key="idfan_fault_sim_f1t")
            time.sleep(0.9)

            idfan_sim_caption_ph.warning(f"🔍 The 51 time-overcurrent element times out and issues a trip signal at t={idfan_relay_ms:.0f} ms ({idfan_sim_eval['t51']:.2f}s) — {idfan_sim_eval['status']}.")
            fig2 = _idfan_fault_sim_base_fig()
            fig2.add_trace(go.Scatter(
                x=[-idfan_preload_ms, 0, 0, idfan_relay_ms], y=[idfan_preload_current, idfan_preload_current, idfan_sim_current, idfan_sim_current],
                mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
            ))
            fig2.add_vline(x=idfan_relay_ms, line=dict(color="#F59E0B", width=2, dash="dot"), annotation_text="51 Trips")
            fig2.update_xaxes(type="log")
            idfan_sim_chart_ph.plotly_chart(fig2, use_container_width=True, key="idfan_fault_sim_f2t")
            time.sleep(0.9)

            idfan_sim_caption_ph.success(f"✅ Trip signal reaches the breaker — it interrupts the fault at t={idfan_total_ms:.0f} ms. Total clearing time: {idfan_total_ms / 1000.0:.2f} s.")
            fig3 = _idfan_fault_sim_base_fig()
            fig3.add_trace(go.Scatter(
                x=[-idfan_preload_ms, 0, 0, idfan_total_ms, idfan_total_ms, idfan_total_ms * 1.1 + 40.0],
                y=[idfan_preload_current, idfan_preload_current, idfan_sim_current, idfan_sim_current, 0.0, 0.0],
                mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
            ))
            fig3.add_vline(x=idfan_relay_ms, line=dict(color="#F59E0B", width=2, dash="dot"), annotation_text="51 Trips")
            fig3.add_vline(x=idfan_total_ms, line=dict(color="#16A34A", width=2, dash="dash"), annotation_text="Breaker Clears")
            fig3.update_xaxes(type="log")
            idfan_sim_chart_ph.plotly_chart(fig3, use_container_width=True, key="idfan_fault_sim_f3t")

            st.session_state[idfan_done_key] = {
                "kind": "trip_51", "status": idfan_sim_eval["status"], "relay_ms": idfan_relay_ms, "total_ms": idfan_total_ms,
                "sim_current": idfan_sim_current, "preload_current": idfan_preload_current, "log_x": True,
            }
        else:
            idfan_window_ms = 200.0
            idfan_sim_caption_ph.warning(f"⚡ Fault occurs at t=0 — current rises to {idfan_sim_current:,.0f} A primary.")
            fig1 = _idfan_fault_sim_base_fig()
            fig1.add_trace(go.Scatter(
                x=[-idfan_preload_ms, 0, 0], y=[idfan_preload_current, idfan_preload_current, idfan_sim_current],
                mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
            ))
            idfan_sim_chart_ph.plotly_chart(fig1, use_container_width=True, key="idfan_fault_sim_f1n")
            time.sleep(0.9)

            idfan_sim_caption_ph.info("🛡️ Neither the 51 nor the 50A element crosses its trip threshold at the settings above. No trip.")
            fig2 = _idfan_fault_sim_base_fig()
            fig2.add_trace(go.Scatter(
                x=[-idfan_preload_ms, 0, 0, idfan_window_ms], y=[idfan_preload_current, idfan_preload_current, idfan_sim_current, idfan_sim_current],
                mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
            ))
            idfan_sim_chart_ph.plotly_chart(fig2, use_container_width=True, key="idfan_fault_sim_f2n")

            st.session_state[idfan_done_key] = {
                "kind": "no_trip", "status": idfan_sim_eval["status"], "window_ms": idfan_window_ms,
                "sim_current": idfan_sim_current, "preload_current": idfan_preload_current,
            }
    else:
        idfan_last = st.session_state.get(idfan_done_key)
        if idfan_last is None:
            idfan_sim_caption_ph.caption("Click **Run Fault Simulation** to watch the fault current rise, the relay detect it, and the breaker clear it, step by step.")
        elif idfan_last["kind"] in ("trip", "trip_51"):
            idfan_unit = "cycles" if idfan_last["kind"] == "trip" else "s"
            idfan_dur = f"{idfan_last['total_ms'] / idfan_cycle_ms:.1f} cycles" if idfan_last["kind"] == "trip" else f"{idfan_last['total_ms'] / 1000.0:.2f} s"
            idfan_sim_caption_ph.success(f"Last run: {idfan_last['status']} — total clearing time {idfan_last['total_ms']:.0f} ms ({idfan_dur}).")
            fig_last = _idfan_fault_sim_base_fig()
            idfan_tail = idfan_last["total_ms"] + 40.0 if idfan_last["kind"] == "trip" else idfan_last["total_ms"] * 1.1 + 40.0
            fig_last.add_trace(go.Scatter(
                x=[-idfan_preload_ms, 0, 0, idfan_last["total_ms"], idfan_last["total_ms"], idfan_tail],
                y=[idfan_last["preload_current"], idfan_last["preload_current"], idfan_last["sim_current"], idfan_last["sim_current"], 0.0, 0.0],
                mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
            ))
            fig_last.add_vline(x=idfan_last["relay_ms"], line=dict(color="#F59E0B", width=2, dash="dot"), annotation_text="Relay Trips")
            fig_last.add_vline(x=idfan_last["total_ms"], line=dict(color="#16A34A", width=2, dash="dash"), annotation_text="Breaker Clears")
            if idfan_last.get("log_x"):
                fig_last.update_xaxes(type="log")
            idfan_sim_chart_ph.plotly_chart(fig_last, use_container_width=True, key="idfan_fault_sim_last_fig")
        else:
            idfan_sim_caption_ph.info(f"Last run: {idfan_last['status']} — no trip.")
            fig_last = _idfan_fault_sim_base_fig()
            fig_last.add_trace(go.Scatter(
                x=[-idfan_preload_ms, 0, 0, idfan_last["window_ms"]],
                y=[idfan_last["preload_current"], idfan_last["preload_current"], idfan_last["sim_current"], idfan_last["sim_current"]],
                mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
            ))
            idfan_sim_chart_ph.plotly_chart(fig_last, use_container_width=True, key="idfan_fault_sim_last_fig")


# ---------------------------------------------------------------------------
# TAB 2 — Commissioning & Injection Tool
# ---------------------------------------------------------------------------
with c["Commissioning & Injection Tool"]:
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
# TAB 4 — Settings Summary & Approval
# ---------------------------------------------------------------------------
with c["Settings Summary & Approval"]:
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

    st.markdown("---")
    st.markdown("#### Save Profile")
    st.caption(
        "Name and download the currently active settings — most useful after entering your own "
        "values under Custom Profile, so you can pick this file back up next time instead of "
        "re-typing everything. Use the loader in the sidebar to restore it later."
    )
    idfan_profile_name = st.text_input(
        "Profile Name", value="ID Fan Profile", key="idfan_profile_name",
        help="Used as the downloaded file's name, and shown when you reload it later.",
    )
    settings_export = {
        "format": "Electrical Equipment Protection Suite settings",
        "version": 1,
        "equipment": "id_fan_motor",
        "profile_name": idfan_profile_name,
        "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "settings": {key: st.session_state[key] for key in MOTOR_CONFIG_FIELDS},
    }
    st.download_button(
        label="💾 Save Profile (.json)",
        data=json.dumps(settings_export, indent=2),
        file_name=f"{safe_filename(idfan_profile_name, 'IDFan_profile')}.json",
        mime="application/json",
        help="Download the active settings and document-control fields for later reload in this app.",
    )
