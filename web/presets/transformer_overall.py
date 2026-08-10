"""
PRESETS dict, ported verbatim from views/transformer_overall.py (lines 32-49).
Source: Transformer_Diff_Setting_-_Overall_GSUT-GEN.pdf, Section 5.10 (Relays
87OA7 / 87OA8, Setting Summary + Calculation/Discussion). Relay currents are
calculated assuming each device carries the full 873.6 MVA rating of the
Generator Step-Up Transformer.

No fault-current fields here — the Overall (backup) zone page has no Fault
Current Analysis tab.
"""

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

# Standard ANSI multi-ratio bushing CT tap set for the 2000:5 CT family
# (ui_helpers.MR_CT_TAPS_2000_5, ported for use client-side) — same physical
# HV CT as the GSUT page (it feeds both relays).
MR_CT_TAPS_2000_5 = [200, 400, 500, 600, 800, 1000, 1200, 1500, 1600, 2000]
