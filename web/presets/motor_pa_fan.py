"""
PRESETS dict for the Primary Air (PA) Fan page, ported from
common/motor_fan_page.py's FAN_TYPES["Primary Air (PA) Fan"]["presets"] —
field names are shortened to match this page's data-field attributes
(see templates/motor_pa_fan.html / static/js/pages/motor_pa_fan.js).
Source: PAFAN MOTOR PROTECTION.pdf Section 5.3 (SR469 MPR + IFC66KD2A 50/50/51
+ HFC22B2A backup + 87M self-balancing differential).
"""

PRESETS = {
    "POMI PA Fan 7A/7B/8A/8B - 1660kW": {
        "fla": 173, "ct_ratio": 300, "ct_sec": 5.0, "gct_ratio": 50,
        "diff87m_ct_ratio": 50, "diff87m_pickup_sec": 2.0,
        "ovl_pct": 115.0, "cm": 5.0,
        "inst_ct": 6.5, "inst_delay": 60.0,
        "gf_frac": 0.1, "gf_delay": 60.0,
        "unb_alarm_pct": 15.0, "unb_alarm_delay": 10.0,
        "unb_trip_pct": 36.0, "unb_trip_delay": 60.0,
        "jam_pct": 150.0, "jam_delay": 1.0,
        "accel": 20.0, "ovl_alarm_delay": 1.0,
        "pdiff_frac": 0.1, "pdiff_delay": 60.0,
        "lrc_100": 1009.0, "lrc_80": 776.0,
        "accel_100": 13.2, "accel_80": 23.8,
        "stall_100": 14.2, "stall_80": 23.8,
        "ifc_tap51": 4.5, "ifc_td": 4.0,
        "ifc_50a": 50.0, "ifc_50b": 2.9, "ifc_target": 0.2,
        "ifc_backup_en": True, "ifc_backup_ct": 2000, "ifc_backup_pickup": 7.5,
        # Reference-only fields shown in the TCC tab's "Other SR469 Functions"
        # table — not editable, straight from the settings doc / Data.xlsx.
        "rtd_stator_c": 135, "ov_pickup_pu": 1.06, "ov_delay_s": 60.0,
        "of_hz": 51.5, "uf_hz": 48.5,
        "underpower_kw": 350.0, "underpower_delay_s": 10.0,
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
        "accel": 20.0, "ovl_alarm_delay": 1.0,
        "pdiff_frac": 0.1, "pdiff_delay": 60.0,
        "lrc_100": 600.0, "lrc_80": 460.0,
        "accel_100": 3.0, "accel_80": 5.0,
        "stall_100": 15.0, "stall_80": 25.0,
        "ifc_tap51": 4.0, "ifc_td": 5.0,
        "ifc_50a": 50.0, "ifc_50b": 3.0, "ifc_target": 0.2,
        "ifc_backup_en": True, "ifc_backup_ct": 200, "ifc_backup_pickup": 10.0,
        "rtd_stator_c": 135, "ov_pickup_pu": 1.06, "ov_delay_s": 60.0,
        "of_hz": 51.5, "uf_hz": 48.5,
        "underpower_kw": 100.0, "underpower_delay_s": 10.0,
        "starts_per_hour": 2, "time_between_starts_min": 45,
    },
}
