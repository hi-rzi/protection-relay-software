"""
PRESETS dict, ported verbatim from views/transformer_gsut.py (lines 32-58).
Source: Transformer_Diff_Setting_-_EXCT.pdf / GSUT settings doc, Section 5.12.1
(Relays 87ET7 / 87ET8, Setting Summary + Calculation/Discussion).
"""

PRESETS = {
    "POMI GSUT 87GT7/87GT8 - 873.6 MVA": {
        "mva": 873.6,
        "kv_hv": 538.125, "kv_lv": 23.0,  # HV calc uses center-of-range tap (538.125kV), not the 525kV nameplate
        "ct_hv": 1600, "ct_lv": 24000, "ct_sec": 5.0,
        "ct_conn_hv": "DELTA", "ct_conn_lv": "WYE",
        "tap_hv": 1.0, "tap_lv": 1.1,
        "bias": 30, "min_operate": 30, "hoc": 5,
        # Through-fault basis - Design Impedance 10% on 468MVA (OA) base, per the
        # "Generator Step-Up Transformer Data" section embedded in Transformer Diff
        # Setting - Overall GSUT-GEN.pdf. X/R ratio is NOT confirmed against this
        # transformer's own design data (no worked through-fault example found for
        # GSUT specifically, unlike EXCT) - flagged as an editable placeholder.
        "fault_mva_base": 468.0, "z_pct": 10.0, "x_over_r": 20.0, "ct_withstand_a": 60.0,
        "fault_kv_hv": 525.0,  # actual HV nameplate voltage - NOT the 538.125kV tap-adjusted kv_hv above
    },
    "Custom Profile": {
        "mva": 10.0,
        "kv_hv": 11.0, "kv_lv": 0.4,
        "ct_hv": 100, "ct_lv": 100, "ct_sec": 5.0,
        "ct_conn_hv": "WYE", "ct_conn_lv": "WYE",
        "tap_hv": 1.0, "tap_lv": 1.0,
        "bias": 25, "min_operate": 20, "hoc": 8,
        "fault_mva_base": 10.0, "z_pct": 10.0, "x_over_r": 20.0, "ct_withstand_a": 40.0,
        "fault_kv_hv": 11.0,
    },
}

# Standard ANSI multi-ratio bushing CT tap set for the 2000:5 CT family
# (ui_helpers.MR_CT_TAPS_2000_5, ported for use client-side).
MR_CT_TAPS_2000_5 = [200, 400, 500, 600, 800, 1000, 1200, 1500, 1600, 2000]
