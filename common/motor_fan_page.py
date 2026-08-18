"""
Shared render logic for the 6.9kV combustion-air fan motors (Primary Air
Fan, Forced Draft Fan) - both use a Multilin SR469 static motor protection
relay (confirmed by both fans' own settings docs; NOT a GE 869 - the two
share the same "Standard"/TCU thermal-curve architecture, which is why the
Motor869Relay engine is reused here, but the settings sheet and labels
below say SR469 to match the real installed hardware). Both fans' source
docs also describe a separate discrete 50/50/51 electromechanical relay
(IFC66KD2A) plus a backup instantaneous relay (HFC22B2A), mirroring the ID
Fan's own retrofit relay stack. Confirmed present on the Primary Air Fan
(PAFAN MOTOR PROTECTION.pdf Section 5.3.1/5.3.2) and modeled here, gated to
project_key == "pa_fan" only - not yet confirmed/added for the FD Fan.
This one module is called by two thin, separate view pages
(views/motor_pa_fan.py and views/motor_fd_fan.py) instead of duplicating
~500 lines twice. Each page gets its own nav entry, title, and settings,
but shares this logic.
"""
import datetime
import json
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common.pdf_report import generate_fan_motor_pdf_report
from common.concepts import render_theory_tab
from common.sld import motor_overcurrent_svg
from common.historian import render_historian_overlay
from common.project_state import with_restored_preset, record_equipment_settings
from common.profile_io import export_profile_button, restore_profile_uploader
from common.ui_helpers import sidebar_section_nav, equipment_switcher
from engines.motor_869 import Motor869Relay
from engines.motor import MotorTimeOvercurrentRelay, BackupInstantaneousRelay
from engines.motor_differential import SelfBalancingDifferentialRelay

# ---------------------------------------------------------------------------
# Presets — base values from Data.xlsx "Motor Data" sheet (Unit 7 & 8, 6.9kV
# section), cross-checked and corrected against each fan's own settings
# calculation document where available (PA Fan: "PAFAN MOTOR PROTECTION.pdf"
# Section 5.3; FD Fan: "FDFAN MOTOR PROTECTION.pdf" Section 5.6.3). Settings
# are identical across Unit 7/8 and the A/B duplicate motors within each fan
# type, so one preset per fan type covers all four physical units.
# "Short Circuit Pick-up" / instantaneous pickup is given as "X CT" -
# confirmed (via user-provided chat + both fans' own settings docs) to mean
# a multiple of the CT PRIMARY rating (e.g. PA Fan: 6.5 x a 300/5 CT =
# 6.5 x 300 = 1950A primary, ~200% of locked rotor current), which is why
# Motor869Relay takes inst_pickup_multiple_of_ct and multiplies by ct_ratio.
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
            "POMI PA Fan 7A/7B/8A/8B - 1660kW": {
                "motor_fla": 173, "ct_ratio": 300, "ct_sec": 5.0,
                "ground_ct_ratio": 50, "ground_ct_sec": 5.0,
                # Curve Multiplier confirmed at CM=5 (not the earlier 4.0 guess) by solving
                # the Standard-curve formula against PAFAN MOTOR PROTECTION.pdf's own two
                # worked points: 5.83xFLA -> 13.4s and 5.10xFLA -> 17.5s both give CM~5.0.
                "overload_pickup_pct": 115.0, "curve_multiplier": 5.0,
                # Instantaneous pickup corrected to 6.5x CT primary (~1950A, ~200% locked
                # rotor current, per the doc's own calc) - the earlier 9.7 was an unconfirmed
                # carryover from Data.xlsx and gave 2910A, well above what the doc specifies.
                "inst_pickup_multiple_of_ct": 6.5, "inst_delay_ms": 60.0,
                "mech_jam_pct": 150.0, "mech_jam_delay_s": 1.0,
                # Confirmed exactly as-is against the doc's own Current Unbalance (46) calc.
                "unbal_trip_pct": 36.0, "unbal_trip_delay_s": 60.0,
                "unbal_alarm_pct": 15.0, "unbal_alarm_delay_s": 10.0,
                "gf_pickup_frac": 0.1, "gf_delay_ms": 60.0,
                "phase_diff_pickup_frac": 0.1, "phase_diff_delay_ms": 60.0,
                "accel_timer_s": 20.0, "overload_alarm_delay_s": 1.0,
                "rtd_stator_c": 135, "ov_pickup_pu": 1.06, "ov_delay_s": 60.0,
                "of_hz": 51.5, "uf_hz": 48.5,
                "underpower_kw": 350.0, "underpower_delay_s": 10.0,
                "starts_per_hour": 2, "time_between_starts_min": 45,
                # Starting/stall data (from PAFAN MOTOR PROTECTION.pdf) - only the HOT safe
                # stall time is documented (hot/cold ratio = 1.0 per the doc's own statement).
                # 90% voltage figures are also documented (882A / 17.3s / 18s) but omitted
                # here to match this app's 100%/80% two-level model (same simplification
                # already used for the FD Fan).
                "locked_rotor_amps_100": 1009.0, "locked_rotor_amps_80": 776.0,
                "accel_time_100": 13.2, "accel_time_80": 23.8,
                "safe_stall_100": 14.2, "safe_stall_80": 23.8,
                # IFC66KD2A discrete 50/50/51 electromechanical relay (PAFAN MOTOR PROTECTION.pdf
                # Section 5.3.1) - a SEPARATE relay from the SR469 MPR above, on the same 300/5 CT.
                # Time dial verified against the doc's own worked points: TD4 gives ~13.3s at 500%
                # (doc: "13 seconds at 500%"), ~16.8s at 3.7x tap (doc: "about 16 seconds" at 100%V
                # LRC), ~18.4s at 3.3x tap (doc: "about 18 seconds" at 90%V LRC) - all via the IAC
                # Long Time Inverse curve already used for the ID Fan's own IFC66KD2A.
                "ifc_tap_51": 4.5, "ifc_time_dial": 4.0,
                "ifc_pickup_50a": 50.0, "ifc_dropout_50b": 2.9, "ifc_target_seal_in": 0.2,
                # Backup instantaneous relay (GEK-49826C HFC22B2A), Section 5.3.2 - separate,
                # higher-ratio 2000/5 CT so it won't saturate under high fault current.
                "ifc_backup_ct_ratio": 2000, "ifc_backup_pickup_50": 7.5,
                # 87M self-balancing differential (Motor_Protection_Setting doc family,
                # Section 5.13) - "all motors except Induced Draft Fans" use a 50/5 CT,
                # High tap, 2.0A secondary pickup (20A primary, same target for every motor).
                "diff87m_ct_ratio": 50, "diff87m_pickup_sec": 2.0,
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
                "locked_rotor_amps_100": 600.0, "locked_rotor_amps_80": 460.0,
                "accel_time_100": 3.0, "accel_time_80": 5.0,
                "safe_stall_100": 15.0, "safe_stall_80": 25.0,
                "ifc_tap_51": 4.0, "ifc_time_dial": 5.0,
                "ifc_pickup_50a": 50.0, "ifc_dropout_50b": 3.0, "ifc_target_seal_in": 0.2,
                "ifc_backup_ct_ratio": 200, "ifc_backup_pickup_50": 10.0,
                "diff87m_ct_ratio": 50, "diff87m_pickup_sec": 2.0,
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
                # Confirmed values (trip 15%/60s, alarm 15%/10s) - the alarm delay stays at
                # 10s per Data.xlsx; an earlier guess to align it to 30s (from
                # FDFAN MOTOR PROTECTION.pdf's prose) was corrected back to the confirmed 10s.
                "unbal_trip_pct": 15.0, "unbal_trip_delay_s": 60.0,
                "unbal_alarm_pct": 15.0, "unbal_alarm_delay_s": 10.0,
                "gf_pickup_frac": 0.1, "gf_delay_ms": 60.0,
                "phase_diff_pickup_frac": 0.1, "phase_diff_delay_ms": 60.0,
                "accel_timer_s": 18.0, "overload_alarm_delay_s": 1.0,
                "rtd_stator_c": 135, "ov_pickup_pu": 1.06, "ov_delay_s": 60.0,
                "of_hz": 51.5, "uf_hz": 48.5,
                "underpower_kw": 80.0, "underpower_delay_s": 10.0,
                "starts_per_hour": 2, "time_between_starts_min": 45,
                # Starting/stall data (from FDFAN MOTOR PROTECTION.pdf, Section 5.6.3) -
                # not available for the Primary Air Fan (no equivalent settings doc found
                # yet), which is why this block is FD-only: LRC = 6.3x FLA @ 100% V / 4.8x
                # FLA @ 80% V; only the HOT safe stall time is documented for these motors
                # (hot/cold ratio = 1.0 per the doc's own statement).
                "locked_rotor_amps_100": 965.0, "locked_rotor_amps_80": 739.0,
                "accel_time_100": 3.2, "accel_time_80": 5.3,
                "safe_stall_100": 20.0, "safe_stall_80": 34.0,
                # 87M self-balancing differential - "all motors except Induced Draft Fans"
                # use a 50/5 CT, High tap, 2.0A secondary pickup (20A primary).
                "diff87m_ct_ratio": 50, "diff87m_pickup_sec": 2.0,
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
                "locked_rotor_amps_100": 600.0, "locked_rotor_amps_80": 460.0,
                "accel_time_100": 3.0, "accel_time_80": 5.0,
                "safe_stall_100": 15.0, "safe_stall_80": 25.0,
                "diff87m_ct_ratio": 50, "diff87m_pickup_sec": 2.0,
            },
        },
    },
}


def render_fan_motor_page(fan_type):
    """Renders the full page body for a single, fixed fan type (no in-page
    fan-type switcher - each of the two view files calls this with its own
    fixed fan_type, so they show up as separate nav entries)."""
    fan_data = FAN_TYPES[fan_type]
    project_key = "pa_fan" if fan_type.startswith("Primary") else "fd_fan"

    st.warning(
        "**Engineering review required.** This tool supports settings checks and commissioning "
        "calculations; it does not approve relay settings. Verify every result against the approved "
        "coordination study, relay manual, and site test procedure before applying settings in service."
    )

    equipment_switcher(f"views/motor_{project_key}.py")
    st.sidebar.header("Equipment Presets")
    presets_with_project = with_restored_preset(fan_data["presets"], project_key)
    selected_preset = st.sidebar.selectbox(
        "Load Standard Profile", list(presets_with_project.keys()), key=f"{project_key}__preset",
        help="Pick a built-in POMI motor, or Custom Profile to enter your own equipment's ratings, "
             "CT specs, and protection settings — this app isn't limited to POMI equipment."
    )
    p_data = presets_with_project[selected_preset]

    # Field-key map for the "Reset to preset defaults" button below - every
    # Current Settings widget that's actually backed by a preset value (not
    # test/analysis-tool inputs, and not review metadata like "Reviewed by",
    # which a reset shouldn't silently erase). ifc_* fields are PA Fan only -
    # p_data won't have them for FD Fan, so they're skipped automatically.
    _RESET_FIELD_MAP = {
        "fla": "motor_fla", "ct_ratio": "ct_ratio", "ct_sec": "ct_sec",
        "gct_ratio": "ground_ct_ratio",
        "diff87m_ct_ratio": "diff87m_ct_ratio", "diff87m_pickup_sec": "diff87m_pickup_sec",
        "ovl_pct": "overload_pickup_pct", "cm": "curve_multiplier",
        "lrc_100": "locked_rotor_amps_100", "lrc_80": "locked_rotor_amps_80",
        "accel_100": "accel_time_100", "accel_80": "accel_time_80",
        "stall_100": "safe_stall_100", "stall_80": "safe_stall_80",
        "inst_ct": "inst_pickup_multiple_of_ct", "inst_delay": "inst_delay_ms",
        "gf_frac": "gf_pickup_frac", "gf_delay": "gf_delay_ms",
        "unb_alarm_pct": "unbal_alarm_pct", "unb_alarm_delay": "unbal_alarm_delay_s",
        "unb_trip_pct": "unbal_trip_pct", "unb_trip_delay": "unbal_trip_delay_s",
        "jam_pct": "mech_jam_pct", "jam_delay": "mech_jam_delay_s",
        "accel": "accel_timer_s", "ovl_alarm_delay": "overload_alarm_delay_s",
        "pdiff_frac": "phase_diff_pickup_frac", "pdiff_delay": "phase_diff_delay_ms",
        "ifc_tap51": "ifc_tap_51", "ifc_td": "ifc_time_dial",
        "ifc_50a": "ifc_pickup_50a", "ifc_50b": "ifc_dropout_50b",
        "ifc_target": "ifc_target_seal_in",
        "ifc_backup_ct": "ifc_backup_ct_ratio", "ifc_backup_pickup": "ifc_backup_pickup_50",
    }

    if st.sidebar.button(
        "↺ Reset to preset defaults", key=f"{project_key}__reset_btn",
        help="Revert every Current Settings field below back to the selected preset's stock values.",
    ):
        for _suffix, _preset_key in _RESET_FIELD_MAP.items():
            if _preset_key in p_data:
                st.session_state[f"{project_key}__{_suffix}"] = p_data[_preset_key]
        st.toast(f"Reset to {selected_preset} defaults.")
        st.rerun()

    restore_profile_uploader(st.sidebar, project_key, f"{project_key}__", project_key)

    if selected_preset != "Custom Profile":
        if project_key == "pa_fan":
            st.success(
                "✓ **Data confidence:** SR469 overload curve, IFC66KD2A 50/50/51, and 87M "
                "self-balancing differential settings are all verified against PAFAN MOTOR "
                "PROTECTION.pdf's own worked examples."
            )
        else:
            st.warning(
                "⚠ **Data confidence:** The SR469 overload curve (Curve Multiplier) and 87M "
                "differential are verified against FDFAN MOTOR PROTECTION.pdf. The "
                "**Instantaneous Pickup** (9.7x CT) is NOT confirmed against this fan's own "
                "document — the Primary Air Fan had this exact same carryover value corrected "
                "to 6.5x after checking its own doc, but this specific setting hasn't been "
                "cross-checked for the Forced Draft Fan yet. The separate IFC66KD2A/HFC22B2A "
                "relay stack (present on PA Fan and ID Fan) also isn't modeled for this motor."
            )

    # -------------------------------------------------------------------
    # CURRENT SETTINGS — every applied setting, editable in place, with a
    # live comment on whether an adjustment improves or weakens protection.
    # Comments reuse the exact checks already used elsewhere on this page
    # (the "Coordination Review" pickup-vs-FLA/LRC checks, and the "Starting/
    # Stall Margin Check") - no new engineering judgment invented, just
    # surfaced inline per field.
    # -------------------------------------------------------------------
    sections = ["Current Settings", "Theory", "Simulate & Test", "Commissioning & Injection Tool", "Settings Summary & Approval"]
    selected, c, pinned = sidebar_section_nav(sections, key_prefix=project_key, pin_first=True)

    with c["Current Settings"]:
        # Live preview, click to reveal, at the top of the tab. Reads Motor FLA and Curve
        # Multiplier straight from session_state (falling back to the preset default) since the
        # actual settings widgets are drawn further down this same tab and haven't run yet on
        # this script pass. The 87M element has no time-current curve (instantaneous, single
        # pickup), so it isn't part of this chart - its pickup value is shown in its own settings
        # card further down instead.
        _pv_fla = st.session_state.get(f"{project_key}__fla", float(p_data["motor_fla"]))
        _pv_cm = st.session_state.get(f"{project_key}__cm", p_data["curve_multiplier"])
        _pv_probe = Motor869Relay(
            ct_ratio=1.0, ct_secondary_rating=1.0, motor_fla=_pv_fla,
            overload_pickup_pct=115.0, curve_multiplier=_pv_cm, inst_pickup_multiple_of_ct=1.0,
        )
        if st.button(
            "📊 Show Live Preview — Overload (51) Curve",
            key=f"{project_key}__show_preview_btn",
            help="Reflects the Motor FLA and Curve Multiplier settings below as you adjust them. Starting/safe-stall overlay and commissioning tools are in the Simulate & Test section (sidebar).",
        ):
            st.session_state[f"{project_key}__preview_shown"] = True
        if st.session_state.get(f"{project_key}__preview_shown", False):
            _pv_m = np.linspace(1.01, 8.0, 200)
            _pv_x_amps = _pv_m * _pv_fla
            _pv_t = [_pv_probe.calculate_overload_trip_time(m * _pv_fla) for m in _pv_m]
            _pv_y_lower = min(_pv_t) * 0.3
            _pv_y_upper = max(_pv_t) * 2.5
            _pv_fig = go.Figure()
            _pv_fig.add_trace(go.Scatter(
                x=_pv_x_amps, y=np.full_like(_pv_x_amps, _pv_y_lower), mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip",
            ))
            _pv_fig.add_trace(go.Scatter(
                x=_pv_x_amps, y=_pv_t, mode="lines", name=f"Curve X{_pv_cm:g}", line=dict(color="#2563EB", width=3),
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
            st.plotly_chart(_pv_fig, use_container_width=True, key=f"{project_key}_settings_preview_fig")
        st.markdown("---")

        st.markdown("## Current Settings")
        st.caption("Every setting currently applied to this relay. Adjust a value below and the comment beside it updates live.")

        with st.container(border=True):
            st.markdown("**Motor Data & CT Spec**")
            d1c1, d1c2 = st.columns(2)
            with d1c1:
                motor_fla = st.number_input("Motor Full Load Current (A)", min_value=1.0, value=float(p_data["motor_fla"]), step=1.0, key=f"{project_key}__fla")
                ct_ratio = st.number_input("CT Ratio (Primary A, e.g. 300 in '300:5')", min_value=1.0, value=float(p_data["ct_ratio"]), key=f"{project_key}__ct_ratio")
            with d1c2:
                ct_secondary_rating = st.selectbox("CT Secondary Rating (A)", [1.0, 5.0], index=1 if p_data["ct_sec"] == 5.0 else 0, key=f"{project_key}__ct_sec")
                ground_ct_ratio = st.number_input("Ground (Zero-Sequence) CT Ratio (Primary A, e.g. 50 in '50:5')", min_value=1.0, value=float(p_data["ground_ct_ratio"]), step=1.0, key=f"{project_key}__gct_ratio")
            st.caption(f"Effective ratio → **{ct_ratio:.0f}:{ct_secondary_rating:.0f}** (= {ct_ratio/ct_secondary_rating:.1f}:1)")

        with st.container(border=True):
            st.markdown("**87M Self-Balancing Differential (GE HFC23C1A)**")
            st.caption(
                "A separate relay from the SR469/IFC66KD2A above — both the line and neutral "
                "conductors of each phase pass through ONE current transformer here, so a healthy "
                "motor's current cancels to zero at the relay. Fitted to motors over 1500HP. Not "
                "restraint/bias-based and has no time-current curve — instantaneous, one pickup setting."
            )
            d87c1, d87c2 = st.columns(2)
            with d87c1:
                diff87m_ct_ratio = st.number_input(
                    "87M CT Ratio (Primary A, e.g. 50 in '50:5')", min_value=1.0, value=float(p_data["diff87m_ct_ratio"]), step=1.0,
                    key=f"{project_key}__diff87m_ct_ratio",
                    help="Induced Draft Fans use a 100/5 CT here — every other motor at this plant uses 50/5."
                )
            with d87c2:
                diff87m_pickup_sec = st.number_input(
                    "87M Pickup (A sec.)", min_value=0.5, max_value=4.0, value=p_data["diff87m_pickup_sec"], step=0.1,
                    key=f"{project_key}__diff87m_pickup_sec",
                    help="HFC23C1A range: Low tap 0.5-2A, High tap 2-4A, continuously adjustable."
                )
            diff87m_pickup_primary = diff87m_pickup_sec * (diff87m_ct_ratio / ct_secondary_rating if ct_secondary_rating > 0 else diff87m_ct_ratio)
            if abs(diff87m_pickup_primary - 20.0) < 0.5:
                st.success(f"Pickup = {diff87m_pickup_primary:.1f} A primary — matches the settings doc's own 20A primary target for every 87M relay at this plant.")
            else:
                st.warning(f"Pickup = {diff87m_pickup_primary:.1f} A primary — the settings doc sets every 87M relay to 20A primary regardless of CT ratio; review this if the difference isn't intentional.")

        with st.container(border=True):
            st.markdown("**Overload (Thermal Model)**")
            ovc1, ovc2 = st.columns(2)
            with ovc1:
                overload_pickup_pct = st.number_input(
                    "Overload Pickup (% FLA)", min_value=100.0, max_value=125.0, value=p_data["overload_pickup_pct"], step=1.0, key=f"{project_key}__ovl_pct",
                    help="Typical range is 110-115% FLA — rides through minor overload/voltage fluctuation while still protecting per the thermal damage curve.",
                )
                if 110.0 <= overload_pickup_pct <= 115.0:
                    st.success(f"Pickup set at {overload_pickup_pct:.0f}% FLA — within the typical 110-115% range.")
                elif overload_pickup_pct > 100.0:
                    st.info(f"Pickup set at {overload_pickup_pct:.0f}% FLA — above 100% so a healthy full-load current won't nuisance-trip, though outside the typical 110-115% range.")
                else:
                    st.warning(f"Pickup set at {overload_pickup_pct:.0f}% FLA — at or below 100% FLA, review overload coordination.")
            with ovc2:
                curve_multiplier = st.number_input("Curve Multiplier (CM)", min_value=1.0, max_value=8.0, value=p_data["curve_multiplier"], step=0.5, key=f"{project_key}__cm",
                    help="GE Multilin 'Standard' thermal curve shared across the 469/269Plus/369/869 lineage.")
                st.caption("Higher CM = slower trip (more starting security, more thermal margin used on a stall). See the Starting/Stall Margin Check below if starting data is on record.")

        # Probe relay just to evaluate the overload trip-time formula against the
        # starting profile below - only needs ct_ratio/ct_secondary_rating/motor_fla/
        # overload_pickup_pct/curve_multiplier. inst_pickup_multiple_of_ct=1.0 is a
        # harmless placeholder (unused by calculate_overload_trip_time) needed only
        # because the constructor would otherwise try inst_pickup_multiple_of_lr *
        # locked_rotor_amps, and locked_rotor_amps isn't gathered yet at this point.
        _probe_ovl = Motor869Relay(
            ct_ratio=ct_ratio, ct_secondary_rating=ct_secondary_rating, motor_fla=motor_fla,
            overload_pickup_pct=overload_pickup_pct, curve_multiplier=curve_multiplier,
            inst_pickup_multiple_of_ct=1.0,
        )

        # Starting/Stall data exists for both fans now (PAFAN / FDFAN MOTOR PROTECTION.pdf) -
        # stays None only for a Custom Profile that hasn't supplied it.
        locked_rotor_amps_100 = locked_rotor_amps_80 = None
        accel_time_100 = accel_time_80 = None
        safe_stall_100 = safe_stall_80 = None
        if project_key in ("fd_fan", "pa_fan"):
            with st.container(border=True):
                st.markdown("**Motor Starting & Safe Stall Data**")
                s1c1, s1c2 = st.columns(2)
                with s1c1:
                    locked_rotor_amps_100 = st.number_input("Locked Rotor Current @ 100% V (A)", min_value=1.0, value=float(p_data["locked_rotor_amps_100"]), step=1.0, key=f"{project_key}__lrc_100")
                    locked_rotor_amps_80 = st.number_input("Locked Rotor Current @ 80% V (A)", min_value=1.0, value=float(p_data["locked_rotor_amps_80"]), step=1.0, key=f"{project_key}__lrc_80")
                with s1c2:
                    accel_time_100 = st.number_input("Acceleration Time @ 100% V (s)", min_value=0.1, value=p_data["accel_time_100"], step=0.1, key=f"{project_key}__accel_100")
                    accel_time_80 = st.number_input("Acceleration Time @ 80% V (s)", min_value=0.1, value=p_data["accel_time_80"], step=0.1, key=f"{project_key}__accel_80")
                s1c3, s1c4 = st.columns(2)
                with s1c3:
                    safe_stall_100 = st.number_input("Safe Stall Time @ 100% V (s)", min_value=0.1, value=p_data["safe_stall_100"], step=0.1, key=f"{project_key}__stall_100",
                        help="Only the hot safe stall time is documented for this motor (hot/cold ratio = 1.0 per the settings doc).")
                with s1c4:
                    safe_stall_80 = st.number_input("Safe Stall Time @ 80% V (s)", min_value=0.1, value=p_data["safe_stall_80"], step=0.1, key=f"{project_key}__stall_80")

                t_at_lrc_100 = _probe_ovl.calculate_overload_trip_time(locked_rotor_amps_100)
                t_at_lrc_80 = _probe_ovl.calculate_overload_trip_time(locked_rotor_amps_80)
                ok_100 = t_at_lrc_100 is not None and accel_time_100 < t_at_lrc_100 < safe_stall_100
                ok_80 = t_at_lrc_80 is not None and accel_time_80 < t_at_lrc_80 < safe_stall_80
                t100_str = f"{t_at_lrc_100:.1f}s" if t_at_lrc_100 is not None else "no trip"
                t80_str = f"{t_at_lrc_80:.1f}s" if t_at_lrc_80 is not None else "no trip"
                if ok_100 and ok_80:
                    st.success(f"Overload trips in {t100_str} @ 100%V / {t80_str} @ 80%V at locked rotor — inside the start/safe-stall margin both times.")
                else:
                    st.warning(f"Overload trips in {t100_str} @ 100%V / {t80_str} @ 80%V at locked rotor — outside the start/safe-stall margin at one or both voltages. See the TCC Curve tab for the full picture.")

        with st.container(border=True):
            st.markdown("**Instantaneous (Short Circuit)**")
            ic1, ic2 = st.columns(2)
            with ic1:
                inst_pickup_multiple_of_ct = st.number_input("Instantaneous Pickup (x CT primary)", min_value=1.0, max_value=20.0, value=p_data["inst_pickup_multiple_of_ct"], step=0.1, key=f"{project_key}__inst_ct",
                    help="Multiple of the CT's primary rating (e.g. 6.5 x a 300:5 CT = 6.5 x 300A primary = 1950A).")
                inst_pickup_primary = inst_pickup_multiple_of_ct * ct_ratio
                if inst_pickup_primary > motor_fla:
                    st.success(f"Pickup {inst_pickup_primary:.0f} A primary ({inst_pickup_primary/motor_fla:.2f}x FLA) clears motor FLA.")
                else:
                    st.warning(f"Pickup {inst_pickup_primary:.0f} A primary is at or below motor FLA ({motor_fla:.0f} A) — review coordination.")
            with ic2:
                inst_delay_ms = st.number_input("Instantaneous Delay (ms)", min_value=0.0, value=p_data["inst_delay_ms"], step=10.0, key=f"{project_key}__inst_delay")
                st.caption("Short definite time delay to ride through starting transients — not a tunable protection margin in the same sense as pickup.")

        with st.container(border=True):
            st.markdown("**Ground Fault**")
            gfc1, gfc2 = st.columns(2)
            with gfc1:
                gf_pickup_frac = st.number_input("GF Pickup (x Ground CT Primary A)", min_value=0.05, max_value=1.0, value=p_data["gf_pickup_frac"], step=0.05, key=f"{project_key}__gf_frac")
            with gfc2:
                gf_delay_ms = st.number_input("GF Delay (ms)", min_value=0.0, value=p_data["gf_delay_ms"], step=10.0, key=f"{project_key}__gf_delay")
            st.caption("No documented rule-of-thumb floor for this setting in the app yet — reference only.")

        with st.container(border=True):
            st.markdown("**Current Unbalance**")
            uc1, uc2 = st.columns(2)
            with uc1:
                unbal_alarm_pct = st.number_input("Unbalance Alarm Pickup (%)", min_value=1.0, max_value=50.0, value=p_data["unbal_alarm_pct"], step=1.0, key=f"{project_key}__unb_alarm_pct")
                unbal_alarm_delay_s = st.number_input("Unbalance Alarm Delay (s)", min_value=0.0, value=p_data["unbal_alarm_delay_s"], step=1.0, key=f"{project_key}__unb_alarm_delay")
            with uc2:
                unbal_trip_pct = st.number_input("Unbalance Trip Pickup (%)", min_value=1.0, max_value=50.0, value=p_data["unbal_trip_pct"], step=1.0, key=f"{project_key}__unb_trip_pct")
                unbal_trip_delay_s = st.number_input("Unbalance Trip Delay (s)", min_value=0.0, value=p_data["unbal_trip_delay_s"], step=1.0, key=f"{project_key}__unb_trip_delay")
            if unbal_trip_pct >= unbal_alarm_pct:
                st.success(f"Trip pickup ({unbal_trip_pct:.0f}%) is at or above alarm pickup ({unbal_alarm_pct:.0f}%) — alarm gives advance warning before the trip stage.")
            else:
                st.warning(f"Trip pickup ({unbal_trip_pct:.0f}%) is below alarm pickup ({unbal_alarm_pct:.0f}%) — the trip stage would fire before any alarm, review this pair.")

        with st.container(border=True):
            st.markdown("**Other Settings (reference only)**")
            st.caption("No documented rule-of-thumb floor for these in the app yet — reference only, not live-checked.")
            oc1, oc2 = st.columns(2)
            with oc1:
                mech_jam_pct = st.number_input("Mechanical Jam Pickup (% FLA)", min_value=100.0, value=p_data["mech_jam_pct"], step=5.0, key=f"{project_key}__jam_pct")
                mech_jam_delay_s = st.number_input("Mechanical Jam Delay (s)", min_value=0.0, value=p_data["mech_jam_delay_s"], step=0.5, key=f"{project_key}__jam_delay")
                accel_timer_s = st.number_input("Acceleration Timer (s)", min_value=1.0, value=p_data["accel_timer_s"], step=1.0, key=f"{project_key}__accel")
            with oc2:
                overload_alarm_delay_s = st.number_input("Overload Alarm Delay (s)", min_value=0.0, value=p_data["overload_alarm_delay_s"], step=0.5, key=f"{project_key}__ovl_alarm_delay")
                phase_diff_pickup_frac = st.number_input("Phase Differential Pickup (x CT)", min_value=0.05, max_value=1.0, value=p_data["phase_diff_pickup_frac"], step=0.05, key=f"{project_key}__pdiff_frac")
                phase_diff_delay_ms = st.number_input("Phase Differential Delay (ms)", min_value=0.0, value=p_data["phase_diff_delay_ms"], step=10.0, key=f"{project_key}__pdiff_delay")

        # IFC66KD2A discrete 50/50/51 electromechanical relay + HFC22B2A backup instantaneous relay -
        # confirmed present on the Primary Air Fan (PAFAN MOTOR PROTECTION.pdf Section 5.3.1/5.3.2),
        # in ADDITION to the SR469 MPR above. Not yet confirmed/added for the FD Fan.
        ifc_tap_51 = ifc_time_dial = ifc_pickup_50a = ifc_dropout_50b = ifc_target_seal_in = None
        ifc_backup_enabled = False
        ifc_backup_ct_ratio = ifc_backup_pickup_50 = None
        ifc_all_clear = True
        if project_key == "pa_fan":
            with st.container(border=True):
                st.markdown("**IFC66KD2A 50/50/51 (separate discrete electromechanical relay)**")
                st.caption(
                    "Documented alongside the SR469 MPR above - same relay model as the Induced Draft "
                    "Fan's own 50/50/51, on this motor's 300:5 phase CT."
                )
                i51c1, i51c2 = st.columns(2)
                with i51c1:
                    ifc_tap_51 = st.number_input("51 Tap (A sec.)", min_value=2.5, max_value=7.5, value=p_data["ifc_tap_51"], step=0.1, key=f"{project_key}__ifc_tap51",
                        help="IFC66KD2A range: 2.5-7.5A at discrete taps (2.5, 2.8, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.5).")
                    ifc_effective_ratio = ct_ratio / ct_secondary_rating if ct_secondary_rating > 0 else ct_ratio
                    ifc_pickup_51_primary = ifc_tap_51 * ifc_effective_ratio
                    if ifc_pickup_51_primary > motor_fla:
                        st.success(f"Pickup {ifc_pickup_51_primary:.0f} A primary ({ifc_pickup_51_primary/motor_fla:.2f}x FLA) clears motor FLA.")
                    else:
                        st.warning(f"Pickup {ifc_pickup_51_primary:.0f} A primary is at or below motor FLA ({motor_fla:.0f} A) — review overload coordination.")
                with i51c2:
                    ifc_time_dial = st.number_input("51 Time Dial", min_value=0.5, max_value=10.0, value=p_data["ifc_time_dial"], step=0.1, key=f"{project_key}__ifc_td",
                        help="IAC 'Long Time Inverse' curve (GEK-106618C constants) - same formula used for the ID Fan's IFC66KD2A.")
                    _probe_ifc = MotorTimeOvercurrentRelay(
                        ct_ratio=ct_ratio, ct_secondary_rating=ct_secondary_rating,
                        tap_51=ifc_tap_51, time_dial=ifc_time_dial, pickup_50a=1e9, dropout_50b=1e9,
                        motor_fla=motor_fla, locked_rotor_amps=locked_rotor_amps_100,
                    )
                    t_ifc_100 = _probe_ifc.calculate_51_trip_time(_probe_ifc.relay_current(locked_rotor_amps_100)) if locked_rotor_amps_100 else None
                    t_ifc_80 = _probe_ifc.calculate_51_trip_time(_probe_ifc.relay_current(locked_rotor_amps_80)) if locked_rotor_amps_80 else None
                    ifc_ok_100 = t_ifc_100 is not None and accel_time_100 < t_ifc_100 < safe_stall_100
                    ifc_ok_80 = t_ifc_80 is not None and accel_time_80 < t_ifc_80 < safe_stall_80
                    t_ifc_100_str = f"{t_ifc_100:.1f}s" if t_ifc_100 is not None else "no trip"
                    t_ifc_80_str = f"{t_ifc_80:.1f}s" if t_ifc_80 is not None else "no trip"
                    if ifc_ok_100 and ifc_ok_80:
                        st.success(f"Trips in {t_ifc_100_str} @ 100%V / {t_ifc_80_str} @ 80%V at locked rotor — inside the start/safe-stall margin both times.")
                    else:
                        st.warning(f"Trips in {t_ifc_100_str} @ 100%V / {t_ifc_80_str} @ 80%V at locked rotor — outside the margin at one or both voltages (the settings doc itself accepts this at 100%V — see the IFC66KD2A tab for details).")

                i50c1, i50c2 = st.columns(2)
                with i50c1:
                    ifc_pickup_50a = st.number_input("50A Pickup (A sec.)", min_value=6.0, max_value=150.0, value=p_data["ifc_pickup_50a"], step=1.0, key=f"{project_key}__ifc_50a",
                        help="Set at ~200-300% of locked rotor current to allow starting inrush.")
                    ifc_pickup_50a_primary = ifc_pickup_50a * ifc_effective_ratio
                    if locked_rotor_amps_100 and ifc_pickup_50a_primary > locked_rotor_amps_100:
                        st.success(f"Pickup {ifc_pickup_50a_primary:.0f} A primary ({ifc_pickup_50a_primary/locked_rotor_amps_100:.2f}x LRC) clears locked-rotor current.")
                    elif locked_rotor_amps_100:
                        st.warning(f"Pickup {ifc_pickup_50a_primary:.0f} A primary is at or below locked-rotor current ({locked_rotor_amps_100:.0f} A) — a normal start could trip instantaneously.")
                with i50c2:
                    ifc_dropout_50b = st.number_input("50B Dropout (A sec.)", min_value=2.0, max_value=8.0, value=p_data["ifc_dropout_50b"], step=0.1, key=f"{project_key}__ifc_50b",
                        help="High-dropout overload ALARM element - estimated pickup = dropout / 0.8.")
                    ifc_pickup_50b_primary = (ifc_dropout_50b / 0.8) * ifc_effective_ratio
                    if ifc_pickup_50b_primary > motor_fla:
                        st.success(f"Estimated pickup {ifc_pickup_50b_primary:.0f} A primary ({ifc_pickup_50b_primary/motor_fla:.2f}x FLA) clears motor FLA.")
                    else:
                        st.warning(f"Estimated pickup {ifc_pickup_50b_primary:.0f} A primary is at or below motor FLA ({motor_fla:.0f} A) — review the overload-alarm setting.")
                ifc_target_seal_in = st.number_input("Target & Seal-in (A)", min_value=0.2, max_value=2.0, value=p_data["ifc_target_seal_in"], step=0.1, key=f"{project_key}__ifc_target")

                ifc_backup_enabled = st.checkbox("Enable HFC22B2A backup relay", value=True, key=f"{project_key}__ifc_backup_en")
                bkc1, bkc2 = st.columns(2)
                with bkc1:
                    ifc_backup_ct_ratio = st.number_input("Backup CT Ratio (Primary A, e.g. 2000 in '2000:5')", min_value=1.0, value=float(p_data["ifc_backup_ct_ratio"]), key=f"{project_key}__ifc_backup_ct", disabled=not ifc_backup_enabled)
                with bkc2:
                    ifc_backup_pickup_50 = st.number_input("Backup 50 Pickup (A sec.)", min_value=2.0, max_value=50.0, value=p_data["ifc_backup_pickup_50"], step=0.5, key=f"{project_key}__ifc_backup_pickup", disabled=not ifc_backup_enabled)
                if ifc_backup_enabled and locked_rotor_amps_100:
                    ifc_backup_effective_ratio = ifc_backup_ct_ratio / ct_secondary_rating if ct_secondary_rating > 0 else ifc_backup_ct_ratio
                    ifc_backup_pickup_primary = ifc_backup_pickup_50 * ifc_backup_effective_ratio
                    if ifc_backup_pickup_primary > locked_rotor_amps_100:
                        st.success(f"Pickup {ifc_backup_pickup_primary:.0f} A primary ({ifc_backup_pickup_primary/locked_rotor_amps_100:.2f}x LRC) clears locked-rotor current.")
                    else:
                        st.warning(f"Pickup {ifc_backup_pickup_primary:.0f} A primary is at or below locked-rotor current ({locked_rotor_amps_100:.0f} A) — review starting security and coordination.")
                    ifc_all_clear = ifc_pickup_51_primary > motor_fla and ifc_ok_100 and ifc_ok_80 and ifc_pickup_50a_primary > locked_rotor_amps_100 and ifc_pickup_50b_primary > motor_fla and ifc_backup_pickup_primary > locked_rotor_amps_100
                else:
                    ifc_all_clear = ifc_pickup_51_primary > motor_fla and ifc_pickup_50b_primary > motor_fla

        all_clear = (
            overload_pickup_pct > 100.0
            and inst_pickup_primary > motor_fla
            and unbal_trip_pct >= unbal_alarm_pct
            and (project_key not in ("fd_fan", "pa_fan") or (ok_100 and ok_80))
            and ifc_all_clear
            and abs(diff87m_pickup_primary - 20.0) < 0.5
        )
        if all_clear:
            st.success("Overall status: all settings shown clear their recommended margins. Engineering approval is still required before issue.")
        else:
            st.warning("Overall status: one or more settings above need review before this is applied.")

        st.markdown("---")
        st.markdown("#### Save Profile")
        st.caption(
            "Name and download every setting currently active on this page — most useful after "
            "entering your own values under Custom Profile, so you can pick this file back up "
            "next time instead of re-typing everything. Use the loader in the sidebar to restore "
            "it later."
        )
        export_profile_button(
            st, project_key, f"{project_key}__",
            default_name=f"{fan_type} Profile", button_key=project_key,
        )

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
        "locked_rotor_amps_100": locked_rotor_amps_100, "locked_rotor_amps_80": locked_rotor_amps_80,
        "accel_time_100": accel_time_100, "accel_time_80": accel_time_80,
        "safe_stall_100": safe_stall_100, "safe_stall_80": safe_stall_80,
        "ifc_tap_51": ifc_tap_51, "ifc_time_dial": ifc_time_dial,
        "ifc_pickup_50a": ifc_pickup_50a, "ifc_dropout_50b": ifc_dropout_50b,
        "ifc_target_seal_in": ifc_target_seal_in,
        "ifc_backup_ct_ratio": ifc_backup_ct_ratio, "ifc_backup_pickup_50": ifc_backup_pickup_50,
        "diff87m_ct_ratio": diff87m_ct_ratio, "diff87m_pickup_sec": diff87m_pickup_sec,
    })

    diff87m_relay = SelfBalancingDifferentialRelay(
        ct_ratio=diff87m_ct_ratio, ct_secondary_rating=ct_secondary_rating, pickup_amps_sec=diff87m_pickup_sec
    )

    ifc_relay = ifc_backup_relay = None
    if project_key == "pa_fan":
        ifc_relay = MotorTimeOvercurrentRelay(
            ct_ratio=ct_ratio, ct_secondary_rating=ct_secondary_rating,
            tap_51=ifc_tap_51, time_dial=ifc_time_dial,
            pickup_50a=ifc_pickup_50a, dropout_50b=ifc_dropout_50b, target_seal_in=ifc_target_seal_in,
            motor_fla=motor_fla, locked_rotor_amps=locked_rotor_amps_100,
        )
        if ifc_backup_enabled:
            ifc_backup_relay = BackupInstantaneousRelay(
                ct_ratio=ifc_backup_ct_ratio, ct_secondary_rating=ct_secondary_rating, pickup_amps=ifc_backup_pickup_50
            )

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

    with c["Theory"]:
        render_theory_tab(
            "motor",
            purpose_text=fan_data["purpose"],
            sld_image_name="motor_idfan.png",
            sld_fallback_svg=motor_overcurrent_svg(
                ct_ratio, ct_secondary_rating, tag="SR469 MPR",
                bus_label="6.9kV Switchgear Bus", motor_label=fan_data["motor_tag"],
            ),
            include_thermal_replica=True,
        )

    # -----------------------------------------------------------------------
    # TAB 1 — Simulate & Test
    # -----------------------------------------------------------------------
    with c["Simulate & Test"]:
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
            diff87m_test_imbalance = st.number_input(
                "87M Imbalance Test Current (Primary A)", min_value=0.0, value=0.0, step=1.0, key=f"{project_key}__diff87m_test_imbalance",
                help="The NET (line minus neutral) current through the self-balancing CT — zero for a healthy motor. Try the pickup primary current to see it trip."
            )

        eval_result = relay.evaluate_protection(test_current)
        gf_eval = relay.evaluate_ground_fault(ground_current)
        unbal_eval = relay.evaluate_unbalance(unbalance_input)
        diff87m_result = diff87m_relay.evaluate_protection(diff87m_test_imbalance)
        any_trip = eval_result["is_trip"] or gf_eval["is_trip"] or unbal_eval["is_trip"] or diff87m_result["is_trip"]

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
                {"Function": "87M (Self-Balancing Differential)", "Multiple": f"{diff87m_test_imbalance:.1f} A", "Status": diff87m_result["status"]},
            ])

            # PDF export moved to the end of this tab (after the IFC66KD2A section
            # below, PA Fan only) so its settings_sheets can include all three
            # relays' rows in one report instead of splitting them - see the
            # relocated generate_fan_motor_pdf_report() call near the end of
            # `with c["Simulate & Test"]:`.
            _sr469_sheet_rows = [
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
            ]
            _87m_sheet_rows = [
                ("87M CT Ratio", f"{diff87m_ct_ratio:.0f}:{ct_secondary_rating:.0f}"),
                ("87M Pickup (A sec.)", f"{diff87m_pickup_sec:.2f}"),
                ("87M Tap", "High" if diff87m_pickup_sec >= 2.0 else "Low"),
            ]

        st.markdown("---")

        st.markdown("#### Overload (51) Time-Current Characteristic")
        has_stall_data = locked_rotor_amps_100 is not None
        max_mult = max(6.0, eval_result["multiple_of_fla"] + 1.0)
        if has_stall_data:
            max_mult = max(max_mult, (locked_rotor_amps_100 / motor_fla) + 1.0)
        mult_line = np.linspace(1.01, max_mult, 300)
        t_line = [relay.calculate_overload_trip_time(m * motor_fla) for m in mult_line]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=mult_line, y=t_line, mode="lines", name=f"Curve X{curve_multiplier:g}", line=dict(color="#2563EB", width=3)))
        if eval_result["t51"] is not None:
            fig.add_trace(go.Scatter(
                x=[eval_result["multiple_of_fla"]], y=[eval_result["t51"]], mode="markers", name="Operating Point",
                marker=dict(size=14, color="red", symbol="x")
            ))

        t_at_lrc_100 = t_at_lrc_80 = None
        if has_stall_data:
            lrc_100_x = locked_rotor_amps_100 / motor_fla
            lrc_80_x = locked_rotor_amps_80 / motor_fla
            t_at_lrc_100 = relay.calculate_overload_trip_time(locked_rotor_amps_100)
            t_at_lrc_80 = relay.calculate_overload_trip_time(locked_rotor_amps_80)
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

        fig.update_layout(
            title="SR469 Overload Trip Time vs. Multiple of FLA",
            xaxis_title="Current (x Motor FLA)", yaxis_title="Trip Time (s)",
            yaxis_type="log", template="plotly_white", height=450,
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "GE Multilin 'Standard' thermal curve: T = CM x 2.2116623 / (0.025303373x(M-1)² + "
            "0.050547581x(M-1)), M = current as a multiple of motor FLA."
        )

        if has_stall_data:
            st.markdown("---")
            st.markdown("**Starting/Stall Margin Check**")
            st.caption(
                "The overload curve should pass BELOW both Safe Stall markers (X) and ABOVE both "
                "Start markers (▲) — i.e. the relay must not trip during a normal start, but must "
                "trip before the motor's insulation is thermally damaged on a stall."
            )
            c1, c2 = st.columns(2)
            with c1:
                ok_100 = t_at_lrc_100 is not None and accel_time_100 < t_at_lrc_100 < safe_stall_100
                st.write(f"**100% V:** trips in {t_at_lrc_100:.1f}s at LRC" if t_at_lrc_100 else "**100% V:** No trip at LRC")
                st.write(f"Accel {accel_time_100}s < Trip < Safe Stall {safe_stall_100}s")
                st.success("Margin OK") if ok_100 else st.error("Check margin")
            with c2:
                ok_80 = t_at_lrc_80 is not None and accel_time_80 < t_at_lrc_80 < safe_stall_80
                st.write(f"**80% V:** trips in {t_at_lrc_80:.1f}s at LRC" if t_at_lrc_80 else "**80% V:** No trip at LRC")
                st.write(f"Accel {accel_time_80}s < Trip < Safe Stall {safe_stall_80}s")
                st.success("Margin OK") if ok_80 else st.error("Check margin")
        else:
            st.caption(
                "No Locked Rotor Current / Safe Stall Time data is on record for this equipment, "
                "so the starting/stall margin overlay shown on the Induced Draft Fan's TCC Curve "
                "isn't available here yet."
            )

        st.markdown("---")
        render_historian_overlay(st, project_key, reference_lines=[
            ("Motor FLA (A)", motor_fla),
            ("Instantaneous Pickup (A primary)", relay.inst_pickup_amps),
        ])

        st.markdown("---")
        st.markdown("#### Other SR469 Functions — Settings Reference (not live-simulated)")
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

        st.markdown("---")
        st.markdown("#### Fault Clearing Time Simulation")
        st.caption(
            "Feeds a fault current through the same evaluate_protection() logic used above, "
            "then adds a typical breaker operating time to show how long the "
            "current actually flows before it's cleared. The 51 element's trip time comes "
            "straight from the curve above; the 50 instantaneous element's operate time uses "
            "the real Instantaneous Delay setting from Current Settings."
        )

        _fs_scenario_options = ["Short-Circuit Fault"]
        if has_stall_data:
            _fs_scenario_options = ["Locked Rotor / Stall", "Short-Circuit Fault"]
        else:
            st.caption("No Locked Rotor Current is on record for this equipment, so only the Short-Circuit Fault scenario is available.")
        fs_scenario = st.radio(
            "Fault Scenario", _fs_scenario_options, key=f"{project_key}__fault_sim_scenario", horizontal=True,
            help=(
                "Locked Rotor / Stall: uses this motor's own Locked Rotor Current @ 100% V — "
                "normally only enough to exercise the 51 overload curve, not the instantaneous "
                "element. Short-Circuit Fault: a current above the Instantaneous Pickup, to show "
                "that element operating instead."
            ),
        )
        fs_breaker_cycles = st.number_input(
            "Breaker Interrupting Time (cycles)", min_value=1.0, max_value=15.0, value=5.0, step=0.5,
            key=f"{project_key}__fault_sim_breaker_cycles",
            help="Time from trip coil energization to fault current interruption — typical motor breakers/contactors are 3-5 cycles. Not confirmed against this plant's own breaker nameplate."
        )

        fs_cycle_ms = 1000.0 / 60.0
        fs_preload_ms = 40.0
        fs_preload_current = motor_fla
        if fs_scenario.startswith("Locked"):
            fs_sim_current = locked_rotor_amps_100
        else:
            fs_sim_current = relay.inst_pickup_amps * 1.5
        fs_sim_eval = relay.evaluate_protection(fs_sim_current)

        fs_run_sim = st.button(
            "▶ Run Fault Simulation", key=f"{project_key}__run_fault_sim",
            help="Plays back the fault step by step: current spikes, the relay detects it, then the trip signal reaches the breaker."
        )
        fs_caption_ph = st.empty()
        fs_chart_ph = st.empty()
        fs_done_key = f"{project_key}__fault_sim_last"

        def _fs_base_fig():
            fig = go.Figure()
            fig.update_layout(
                xaxis_title="Time (ms, t=0 is fault inception)", yaxis_title="Primary Current (A)",
                template="plotly_white", height=340, margin=dict(t=20, b=40),
            )
            return fig

        if fs_run_sim:
            if fs_sim_eval["trip_50"]:
                fs_relay_ms = relay.inst_delay_ms
                fs_total_ms = fs_relay_ms + fs_breaker_cycles * fs_cycle_ms

                fs_caption_ph.warning(f"⚡ Fault occurs at t=0 — current spikes to {fs_sim_current:,.0f} A primary.")
                fig1 = _fs_base_fig()
                fig1.add_trace(go.Scatter(
                    x=[-fs_preload_ms, 0, 0], y=[fs_preload_current, fs_preload_current, fs_sim_current],
                    mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
                ))
                fs_chart_ph.plotly_chart(fig1, use_container_width=True, key=f"{project_key}__fault_sim_f1")
                time.sleep(0.9)

                fs_caption_ph.warning(f"🔍 The 50 instantaneous element detects the fault and issues a trip signal at t={fs_relay_ms:.0f} ms — {fs_sim_eval['status']}.")
                fig2 = _fs_base_fig()
                fig2.add_trace(go.Scatter(
                    x=[-fs_preload_ms, 0, 0, fs_relay_ms], y=[fs_preload_current, fs_preload_current, fs_sim_current, fs_sim_current],
                    mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
                ))
                fig2.add_vline(x=fs_relay_ms, line=dict(color="#F59E0B", width=2, dash="dot"), annotation_text="50 Trips")
                fs_chart_ph.plotly_chart(fig2, use_container_width=True, key=f"{project_key}__fault_sim_f2")
                time.sleep(0.9)

                fs_caption_ph.success(f"✅ Trip signal reaches the breaker — it interrupts the fault at t={fs_total_ms:.0f} ms. Total clearing time: {fs_total_ms:.0f} ms ({fs_total_ms / fs_cycle_ms:.1f} cycles).")
                fig3 = _fs_base_fig()
                fig3.add_trace(go.Scatter(
                    x=[-fs_preload_ms, 0, 0, fs_total_ms, fs_total_ms, fs_total_ms + 40.0],
                    y=[fs_preload_current, fs_preload_current, fs_sim_current, fs_sim_current, 0.0, 0.0],
                    mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
                ))
                fig3.add_vline(x=fs_relay_ms, line=dict(color="#F59E0B", width=2, dash="dot"), annotation_text="50 Trips")
                fig3.add_vline(x=fs_total_ms, line=dict(color="#16A34A", width=2, dash="dash"), annotation_text="Breaker Clears")
                fs_chart_ph.plotly_chart(fig3, use_container_width=True, key=f"{project_key}__fault_sim_f3")

                st.session_state[fs_done_key] = {
                    "kind": "trip", "status": fs_sim_eval["status"], "relay_ms": fs_relay_ms, "total_ms": fs_total_ms,
                    "sim_current": fs_sim_current, "preload_current": fs_preload_current, "log_x": False,
                }
            elif fs_sim_eval["trip_51"]:
                fs_relay_ms = fs_sim_eval["t51"] * 1000.0
                fs_total_ms = fs_relay_ms + fs_breaker_cycles * fs_cycle_ms

                fs_caption_ph.warning(f"⚡ Fault occurs at t=0 — current rises to {fs_sim_current:,.0f} A primary (locked rotor).")
                fig1 = _fs_base_fig()
                fig1.add_trace(go.Scatter(
                    x=[-fs_preload_ms, 0, 0], y=[fs_preload_current, fs_preload_current, fs_sim_current],
                    mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
                ))
                fig1.update_xaxes(type="log")
                fs_chart_ph.plotly_chart(fig1, use_container_width=True, key=f"{project_key}__fault_sim_f1t")
                time.sleep(0.9)

                fs_caption_ph.warning(f"🔍 The 51 overload element times out and issues a trip signal at t={fs_relay_ms:.0f} ms ({fs_sim_eval['t51']:.2f}s) — {fs_sim_eval['status']}.")
                fig2 = _fs_base_fig()
                fig2.add_trace(go.Scatter(
                    x=[-fs_preload_ms, 0, 0, fs_relay_ms], y=[fs_preload_current, fs_preload_current, fs_sim_current, fs_sim_current],
                    mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
                ))
                fig2.add_vline(x=fs_relay_ms, line=dict(color="#F59E0B", width=2, dash="dot"), annotation_text="51 Trips")
                fig2.update_xaxes(type="log")
                fs_chart_ph.plotly_chart(fig2, use_container_width=True, key=f"{project_key}__fault_sim_f2t")
                time.sleep(0.9)

                fs_caption_ph.success(f"✅ Trip signal reaches the breaker — it interrupts the fault at t={fs_total_ms:.0f} ms. Total clearing time: {fs_total_ms / 1000.0:.2f} s.")
                fig3 = _fs_base_fig()
                fig3.add_trace(go.Scatter(
                    x=[-fs_preload_ms, 0, 0, fs_total_ms, fs_total_ms, fs_total_ms * 1.1 + 40.0],
                    y=[fs_preload_current, fs_preload_current, fs_sim_current, fs_sim_current, 0.0, 0.0],
                    mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
                ))
                fig3.add_vline(x=fs_relay_ms, line=dict(color="#F59E0B", width=2, dash="dot"), annotation_text="51 Trips")
                fig3.add_vline(x=fs_total_ms, line=dict(color="#16A34A", width=2, dash="dash"), annotation_text="Breaker Clears")
                fig3.update_xaxes(type="log")
                fs_chart_ph.plotly_chart(fig3, use_container_width=True, key=f"{project_key}__fault_sim_f3t")

                st.session_state[fs_done_key] = {
                    "kind": "trip_51", "status": fs_sim_eval["status"], "relay_ms": fs_relay_ms, "total_ms": fs_total_ms,
                    "sim_current": fs_sim_current, "preload_current": fs_preload_current, "log_x": True,
                }
            else:
                fs_window_ms = 200.0
                fs_caption_ph.warning(f"⚡ Fault occurs at t=0 — current rises to {fs_sim_current:,.0f} A primary.")
                fig1 = _fs_base_fig()
                fig1.add_trace(go.Scatter(
                    x=[-fs_preload_ms, 0, 0], y=[fs_preload_current, fs_preload_current, fs_sim_current],
                    mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
                ))
                fs_chart_ph.plotly_chart(fig1, use_container_width=True, key=f"{project_key}__fault_sim_f1n")
                time.sleep(0.9)

                fs_caption_ph.info("🛡️ Neither the 51 nor the instantaneous element crosses its trip threshold at the settings above. No trip.")
                fig2 = _fs_base_fig()
                fig2.add_trace(go.Scatter(
                    x=[-fs_preload_ms, 0, 0, fs_window_ms], y=[fs_preload_current, fs_preload_current, fs_sim_current, fs_sim_current],
                    mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
                ))
                fs_chart_ph.plotly_chart(fig2, use_container_width=True, key=f"{project_key}__fault_sim_f2n")

                st.session_state[fs_done_key] = {
                    "kind": "no_trip", "status": fs_sim_eval["status"], "window_ms": fs_window_ms,
                    "sim_current": fs_sim_current, "preload_current": fs_preload_current,
                }
        else:
            fs_last = st.session_state.get(fs_done_key)
            if fs_last is None:
                fs_caption_ph.caption("Click **Run Fault Simulation** to watch the fault current rise, the relay detect it, and the breaker clear it, step by step.")
            elif fs_last["kind"] in ("trip", "trip_51"):
                fs_dur = f"{fs_last['total_ms'] / fs_cycle_ms:.1f} cycles" if fs_last["kind"] == "trip" else f"{fs_last['total_ms'] / 1000.0:.2f} s"
                fs_caption_ph.success(f"Last run: {fs_last['status']} — total clearing time {fs_last['total_ms']:.0f} ms ({fs_dur}).")
                fig_last = _fs_base_fig()
                fs_tail = fs_last["total_ms"] + 40.0 if fs_last["kind"] == "trip" else fs_last["total_ms"] * 1.1 + 40.0
                fig_last.add_trace(go.Scatter(
                    x=[-fs_preload_ms, 0, 0, fs_last["total_ms"], fs_last["total_ms"], fs_tail],
                    y=[fs_last["preload_current"], fs_last["preload_current"], fs_last["sim_current"], fs_last["sim_current"], 0.0, 0.0],
                    mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
                ))
                fig_last.add_vline(x=fs_last["relay_ms"], line=dict(color="#F59E0B", width=2, dash="dot"), annotation_text="Relay Trips")
                fig_last.add_vline(x=fs_last["total_ms"], line=dict(color="#16A34A", width=2, dash="dash"), annotation_text="Breaker Clears")
                if fs_last.get("log_x"):
                    fig_last.update_xaxes(type="log")
                fs_chart_ph.plotly_chart(fig_last, use_container_width=True, key=f"{project_key}__fault_sim_last_fig")
            else:
                fs_caption_ph.info(f"Last run: {fs_last['status']} — no trip.")
                fig_last = _fs_base_fig()
                fig_last.add_trace(go.Scatter(
                    x=[-fs_preload_ms, 0, 0, fs_last["window_ms"]],
                    y=[fs_last["preload_current"], fs_last["preload_current"], fs_last["sim_current"], fs_last["sim_current"]],
                    mode="lines", line=dict(color="#DC2626", width=3), name="Fault Current",
                ))
                fs_chart_ph.plotly_chart(fig_last, use_container_width=True, key=f"{project_key}__fault_sim_last_fig")

        _ifc_sheet_rows = None
        if project_key == "pa_fan":
            with st.expander("GE IFC66KD2A 50/50/51 (separate discrete relay)", expanded=False):
                st.subheader("Electromechanical 50/50/51 Relay (IFC66KD2A)")
                st.caption(
                    "This motor's own settings document specifies a separate, discrete GE IFC66KD2A "
                    "50/50/51 electromechanical relay and a GE HFC22B2A backup instantaneous relay, "
                    "in addition to the SR469 MPR modeled on the other tabs — the same relay stack "
                    "architecture as the Induced Draft Fan."
                )

                ifc_eval = ifc_relay.evaluate_protection(test_current)
                ifc_backup_eval = ifc_backup_relay.evaluate_protection(test_current) if ifc_backup_relay else None

                st.info(f"Test current (set above): **{test_current:.1f} A primary**")
                m1, m2, m3 = st.columns(3)
                m1.metric("Relay Secondary", f"{ifc_eval['i_relay_sec']:.3f} A")
                m2.metric("Multiple of 51 Pickup", f"{ifc_eval['multiple_of_pickup_51']:.2f}x")
                m3.metric("51 Trip Time", f"{ifc_eval['t51']:.2f}s" if ifc_eval["t51"] is not None else "No Trip")

                if ifc_eval["is_trip"]:
                    st.error(ifc_eval["status"])
                elif ifc_eval["alarm_50b"]:
                    st.warning(ifc_eval["status"])
                else:
                    st.success("SYSTEM HEALTHY (Below Pickup)")

                elem_rows = [
                    {"Element": "51 (Long Time Inverse)", "State": "TRIP" if ifc_eval["trip_51"] else "Below Pickup",
                     "Detail": f"{ifc_eval['t51']:.2f}s" if ifc_eval["t51"] is not None else "—"},
                    {"Element": "50A (Instantaneous)", "State": "TRIP" if ifc_eval["trip_50a"] else "Below Pickup",
                     "Detail": f"Pickup {ifc_relay.pickup_50a:.1f}A sec."},
                    {"Element": "50B (Overload Alarm)", "State": "ALARM" if ifc_eval["alarm_50b"] else "Normal",
                     "Detail": f"Est. pickup {ifc_relay.pickup_50b:.2f}A sec. / dropout {ifc_relay.dropout_50b:.2f}A sec."},
                ]
                if ifc_backup_eval is not None:
                    elem_rows.append({
                        "Element": "50 (Backup, HFC22B2A)",
                        "State": "TRIP" if ifc_backup_eval["is_trip"] else "Below Pickup",
                        "Detail": f"Pickup {ifc_backup_relay.pickup_amps:.1f}A sec. (higher-ratio CT, won't saturate)",
                    })
                st.table(elem_rows)

                st.markdown("---")
                st.markdown("**Starting/Stall Margin Check (51 element)**")
                t_ifc_lrc_100 = ifc_relay.calculate_51_trip_time(ifc_relay.relay_current(locked_rotor_amps_100)) if locked_rotor_amps_100 else None
                t_ifc_lrc_80 = ifc_relay.calculate_51_trip_time(ifc_relay.relay_current(locked_rotor_amps_80)) if locked_rotor_amps_80 else None
                c1, c2 = st.columns(2)
                with c1:
                    ok_100 = t_ifc_lrc_100 is not None and accel_time_100 < t_ifc_lrc_100 < safe_stall_100
                    st.write(f"**100% V:** 51 trips in {t_ifc_lrc_100:.1f}s at LRC" if t_ifc_lrc_100 else "**100% V:** No trip at LRC")
                    st.write(f"Accel {accel_time_100}s < Trip < Safe Stall {safe_stall_100}s")
                    st.success("Margin OK") if ok_100 else st.error("Check margin")
                with c2:
                    ok_80 = t_ifc_lrc_80 is not None and accel_time_80 < t_ifc_lrc_80 < safe_stall_80
                    st.write(f"**80% V:** 51 trips in {t_ifc_lrc_80:.1f}s at LRC" if t_ifc_lrc_80 else "**80% V:** No trip at LRC")
                    st.write(f"Accel {accel_time_80}s < Trip < Safe Stall {safe_stall_80}s")
                    st.success("Margin OK") if ok_80 else st.error("Check margin")
                st.caption(
                    "Per the settings document's own discussion: at the default Time Dial (4.0), the "
                    "100% voltage trip time (~16.8s) exceeds the 14.2s safe stall time - accepted in "
                    "the doc because the SR469 MPR's own cooldown timers already prevent back-to-back "
                    "hot starts, so the IFC66 is unlikely to see a start from a fully hot motor."
                )

                st.markdown("---")
                st.subheader("Time-Current Characteristic (TCC) Curve")
                m_range_ifc = np.linspace(1.01, 20.0, 400)
                t_range_ifc = [ifc_relay.calculate_51_trip_time(m * ifc_relay.tap_51) for m in m_range_ifc]
                fig_ifc = go.Figure()
                fig_ifc.add_trace(go.Scatter(x=m_range_ifc, y=t_range_ifc, mode="lines", name="51 (Long Time Inverse)", line=dict(color="#2563EB", width=3)))

                x_50a = ifc_relay.pickup_50a / ifc_relay.tap_51
                fig_ifc.add_vline(x=x_50a, line=dict(color="#DC2626", width=2, dash="dash"), annotation_text="50A Pickup")
                x_50b = ifc_relay.pickup_50b / ifc_relay.tap_51
                fig_ifc.add_vline(x=x_50b, line=dict(color="#F59E0B", width=2, dash="dot"), annotation_text="50B Alarm")
                if ifc_backup_relay is not None:
                    x_backup = (ifc_backup_relay.pickup_amps * ifc_backup_relay.effective_ratio) / ifc_relay.tap_51 / ifc_relay.effective_ratio
                    fig_ifc.add_vline(x=x_backup, line=dict(color="#7C3AED", width=2, dash="dashdot"), annotation_text="Backup 50")

                if locked_rotor_amps_100 is not None:
                    lrc_100_x = ifc_relay.relay_current(locked_rotor_amps_100) / ifc_relay.tap_51
                    lrc_80_x = ifc_relay.relay_current(locked_rotor_amps_80) / ifc_relay.tap_51
                    fig_ifc.add_trace(go.Scatter(
                        x=[lrc_100_x], y=[accel_time_100], mode="markers+text", name="Start @ 100% V",
                        text=["Start @ 100%V"], textposition="top center", marker=dict(size=13, color="green", symbol="triangle-up")
                    ))
                    fig_ifc.add_trace(go.Scatter(
                        x=[lrc_80_x], y=[accel_time_80], mode="markers+text", name="Start @ 80% V",
                        text=["Start @ 80%V"], textposition="top center", marker=dict(size=13, color="darkgreen", symbol="triangle-up")
                    ))
                    fig_ifc.add_trace(go.Scatter(
                        x=[lrc_100_x], y=[safe_stall_100], mode="markers+text", name="Safe Stall @ 100% V",
                        text=["Safe Stall @ 100%V"], textposition="bottom center", marker=dict(size=13, color="black", symbol="x")
                    ))
                    fig_ifc.add_trace(go.Scatter(
                        x=[lrc_80_x], y=[safe_stall_80], mode="markers+text", name="Safe Stall @ 80% V",
                        text=["Safe Stall @ 80%V"], textposition="bottom center", marker=dict(size=13, color="gray", symbol="x")
                    ))

                fig_ifc.update_layout(
                    title="IFC66KD2A 50/50/51 TCC",
                    xaxis_title="Current (x 51 Tap)", yaxis_title="Trip Time (s)",
                    xaxis_type="log", yaxis_type="log", template="plotly_white", height=500,
                )
                st.plotly_chart(fig_ifc, use_container_width=True)
                st.caption(
                    "GE IAC 'Long Time Inverse' curve (5-constant polynomial, GEK-106618C constants) — "
                    "same formula used for the Induced Draft Fan's own IFC66KD2A. Time dial verified "
                    "against this motor's own settings doc: TD4 gives ~13.3s at 500% (doc: 13s), "
                    "~16.8s at 3.7x tap / 100%V LRC (doc: ~16s), ~18.4s at 3.3x tap / 90%V LRC (doc: ~18s)."
                )

                st.markdown("---")
                st.markdown("#### Settings Reference")
                _ifc_sheet_rows = [
                    ("CT Ratio", f"{ct_ratio:.0f}:{ct_secondary_rating:.0f}"),
                    ("51 Tap (A sec.)", f"{ifc_relay.tap_51:.2f}"),
                    ("51 Time Dial", f"{ifc_relay.time_dial:.2f}"),
                    ("50A Pickup (A sec.)", f"{ifc_relay.pickup_50a:.2f}"),
                    ("50B Dropout (A sec.)", f"{ifc_relay.dropout_50b:.2f}"),
                    ("Target & Seal-in (A)", f"{ifc_relay.target_seal_in:.2f}"),
                ]
                if ifc_backup_relay is not None:
                    _ifc_sheet_rows += [
                        ("Backup 50 CT Ratio", f"{ifc_backup_relay.ct_ratio:.0f}:{ct_secondary_rating:.0f}"),
                        ("Backup 50 Pickup (A sec.)", f"{ifc_backup_relay.pickup_amps:.2f}"),
                    ]

        settings_sheets = [("Multilin SR469", _sr469_sheet_rows), ("GE HFC23C1A", _87m_sheet_rows)] + (
            [("IFC66KD2A", _ifc_sheet_rows)] if _ifc_sheet_rows else []
        )
        pdf_bytes = generate_fan_motor_pdf_report(
            f"{fan_type} - {selected_preset}", relay, eval_result, gf_eval, unbal_eval,
            test_current, ground_current, unbalance_input,
            settings_sheets=settings_sheets,
        )
        st.download_button(
            label="Export Certified Protection Audit Report",
            data=pdf_bytes,
            file_name=f"{project_key}_Protection_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
            help="Includes the Relay-Ready Settings Sheet as its final section(s).",
        )

    # -----------------------------------------------------------------------
    # TAB 2 — Commissioning & Injection Tool
    # -----------------------------------------------------------------------
    with c["Commissioning & Injection Tool"]:
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

    # -----------------------------------------------------------------------
    # TAB 4 — Settings Summary & Approval
    # -----------------------------------------------------------------------
    with c["Settings Summary & Approval"]:
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

