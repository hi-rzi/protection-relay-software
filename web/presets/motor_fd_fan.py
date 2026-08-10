"""
PRESETS dict for the Forced Draft (FD) Fan page, ported from
common/motor_fan_page.py's FAN_TYPES["Forced Draft (FD) Fan"]["presets"] —
field names match this page's data-field attributes (see
templates/motor_fd_fan.html / static/js/pages/motor_fd_fan.js). No
ifc_* fields — the discrete IFC66KD2A/HFC22B2A relay stack documented for
the PA Fan is NOT confirmed/modeled for this motor.
Source: FDFAN MOTOR PROTECTION.pdf Section 5.6.3.
"""

PRESETS = {
    "POMI FD Fan 7A/7B/8A/8B - 1343kW": {
        "fla": 153, "ct_ratio": 200, "ct_sec": 5.0, "gct_ratio": 50,
        "diff87m_ct_ratio": 50, "diff87m_pickup_sec": 2.0,
        "ovl_pct": 115.0, "cm": 6.0,
        "inst_ct": 9.7, "inst_delay": 60.0,
        "gf_frac": 0.1, "gf_delay": 60.0,
        "unb_alarm_pct": 15.0, "unb_alarm_delay": 10.0,
        "unb_trip_pct": 15.0, "unb_trip_delay": 60.0,
        "jam_pct": 150.0, "jam_delay": 1.0,
        "accel": 18.0, "ovl_alarm_delay": 1.0,
        "pdiff_frac": 0.1, "pdiff_delay": 60.0,
        "lrc_100": 965.0, "lrc_80": 739.0,
        "accel_100": 3.2, "accel_80": 5.3,
        "stall_100": 20.0, "stall_80": 34.0,
        "rtd_stator_c": 135, "ov_pickup_pu": 1.06, "ov_delay_s": 60.0,
        "of_hz": 51.5, "uf_hz": 48.5,
        "underpower_kw": 80.0, "underpower_delay_s": 10.0,
        "starts_per_hour": 2, "time_between_starts_min": 45,
    },
    "Custom Profile": {
        "fla": 100, "ct_ratio": 100, "ct_sec": 5.0, "gct_ratio": 50,
        "diff87m_ct_ratio": 50, "diff87m_pickup_sec": 2.0,
        "ovl_pct": 115.0, "cm": 4.0,
        "inst_ct": 8.0, "inst_delay": 60.0,
        "gf_frac": 0.1, "gf_delay": 60.0,
        "unb_alarm_pct": 15.0, "unb_alarm_delay": 10.0,
        "unb_trip_pct": 30.0, "unb_trip_delay": 60.0,
        "jam_pct": 150.0, "jam_delay": 1.0,
        "accel": 18.0, "ovl_alarm_delay": 1.0,
        "pdiff_frac": 0.1, "pdiff_delay": 60.0,
        "lrc_100": 600.0, "lrc_80": 460.0,
        "accel_100": 3.0, "accel_80": 5.0,
        "stall_100": 15.0, "stall_80": 25.0,
        "rtd_stator_c": 135, "ov_pickup_pu": 1.06, "ov_delay_s": 60.0,
        "of_hz": 51.5, "uf_hz": 48.5,
        "underpower_kw": 100.0, "underpower_delay_s": 10.0,
        "starts_per_hour": 2, "time_between_starts_min": 45,
    },
}
