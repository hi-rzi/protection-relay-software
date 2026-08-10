"""
PRESETS dict, ported verbatim from views/transformer_exct.py (lines 32-54).
Source: Transformer_Diff_Setting_-_EXCT.pdf, Section 5.12.1
(Relays 87ET7 / 87ET8, Setting Summary + Calculation/Discussion).
"""

PRESETS = {
    "POMI EXCT 87ET7/87ET8 - 7875 kVA": {
        "mva": 7.875,
        "kv_hv": 23.0, "kv_lv": 0.9,
        "ct_hv": 400, "ct_lv": 5000, "ct_sec": 5.0,
        "ct_conn_hv": "DELTA", "ct_conn_lv": "WYE",
        "tap_hv": 0.7, "tap_lv": 0.6,
        "bias": 20, "min_operate": 20, "hoc": 5,
        # Through-fault basis - Transformer Diff Setting - EXCT.pdf Calculation/Discussion:
        # impedance is stated on the 6300kVA (OA, self-cooled) nameplate base, NOT the
        # 7875kVA (FA) rating used for the CT-tap calcs above. X/R=10 per Appendix A.
        "fault_mva_base": 6.3, "z_pct": 7.0, "x_over_r": 10.0, "ct_withstand_a": 60.0,
    },
    "Custom Profile": {
        "mva": 10.0,
        "kv_hv": 11.0, "kv_lv": 0.4,
        "ct_hv": 100, "ct_lv": 100, "ct_sec": 5.0,
        "ct_conn_hv": "WYE", "ct_conn_lv": "WYE",
        "tap_hv": 1.0, "tap_lv": 1.0,
        "bias": 25, "min_operate": 20, "hoc": 8,
        "fault_mva_base": 10.0, "z_pct": 7.0, "x_over_r": 10.0, "ct_withstand_a": 40.0,
    },
}

# Standard ANSI multi-ratio bushing CT tap set for the 600:5 CT family
# (ui_helpers.MR_CT_TAPS_600_5, ported for use client-side).
MR_CT_TAPS_600_5 = [50, 100, 150, 200, 250, 300, 400, 450, 500, 600]
