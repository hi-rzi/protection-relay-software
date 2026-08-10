"""
PRESETS dict, ported verbatim from views/transformer_aux.py (lines 32-61).
Source: Transformer_Diff_Setting_-_UAT.pdf, Section 5.3.1
(Relays 87AT7 / 87AT8, Setting Summary + Calculation/Discussion).
"""

PRESETS = {
    "POMI UAT 87AT7/87AT8 - 112 MVA": {
        "mva": 112.0,
        "kv_hv": 22.425, "kv_lv": 13.8,  # HV calc uses Tap Position 3 (22.425kV), not the 23kV nameplate
        "ct_hv": 3000, "ct_lv": 4000, "ct_sec": 5.0,
        "ct_conn_hv": "WYE", "ct_conn_lv": "DELTA",
        "tap_hv": 1.02, "tap_lv": 0.48,
        "bias": 20, "min_operate": 20, "hoc": 5,
        # Through-fault basis - confirmed against the UAT's own settings document
        # (Mitsubishi CAC1-10-M3, Instruction Book L9036 Ref. 4.27): Design Impedance 8.5%,
        # Minimum Impedance 8.47% and X/R=38.9 (both Appendix A). Uses the MINIMUM impedance
        # (not the design/nameplate value) paired with Appendix A's own X/R, since a lower
        # impedance gives the worst-case (higher) maximum through-fault current - the figure
        # this tab is meant to check CTs against. Impedance base uses the transformer's OA
        # (self-cooled, lowest) rating of 60MVA, per "60/80/100/112MVA OA/FA/FA/FA" - the
        # convention nameplate impedance is stated on, matching EXCT's and GSUT's own pages.
        "fault_mva_base": 60.0, "z_pct": 8.47, "x_over_r": 38.9, "ct_withstand_a": 60.0,
        "fault_kv_hv": 23.0,  # actual HV nameplate voltage - NOT the 22.425kV tap-adjusted kv_hv above
    },
    "Custom Profile": {
        "mva": 10.0,
        "kv_hv": 11.0, "kv_lv": 0.4,
        "ct_hv": 100, "ct_lv": 100, "ct_sec": 5.0,
        "ct_conn_hv": "WYE", "ct_conn_lv": "WYE",
        "tap_hv": 1.0, "tap_lv": 1.0,
        "bias": 25, "min_operate": 20, "hoc": 8,
        "fault_mva_base": 10.0, "z_pct": 8.0, "x_over_r": 15.0, "ct_withstand_a": 40.0,
        "fault_kv_hv": 11.0,
    },
}

# Standard ANSI multi-ratio bushing CT tap set for the 3000:5 CT family
# (ui_helpers.MR_CT_TAPS_3000_5, ported for use client-side).
MR_CT_TAPS_3000_5 = [300, 500, 750, 1000, 1250, 1500, 2000, 2400, 2800, 3000]
