"""
PRESETS dict, ported verbatim from views/generator.py (lines 38-62).
Source: Generator Diff setting.pdf / GEK-34124E.

Unlike every transformer page, PRESETS is nested one level deeper here — by
`mode` ("GENERATOR" = GE G60, "GENERATOR_LEGACY" = GE CFD22B4A) — since the
two relay implementations have different preset shapes entirely (pickup/
slope/break settings vs. a single target_amps/slope1 pair).
"""

PRESETS = {
    "GENERATOR": {
        "POMI Unit 7 & 8 - 846 MVA": {
            "mva": 846.231, "kv": 23.0, "ct_n": 24000, "ct_t": 24000,
            "pickup": 0.06, "slope1": 20, "break1": 1.15, "slope2": 80, "break2": 8.00,
            # Fault current analysis basis - Generator Diff setting.pdf Section 5.1.1
            # Calculation/Discussion: X1G=0.155pu, 1.73x asymmetry, 186kA grid-fed
            # through-fault via GSUT, 84A CT/relay secondary withstand limit.
            "x1_pu": 0.155, "asym_factor": 1.73, "external_fault_ka": 186.0, "ct_withstand_a": 84.0,
        },
        "Custom Profile": {
            "mva": 10.0, "kv": 11.0, "ct_n": 100, "ct_t": 100,
            "pickup": 0.1, "slope1": 20, "break1": 1.15, "slope2": 60, "break2": 6.00,
            "x1_pu": 0.15, "asym_factor": 1.73, "external_fault_ka": 0.0, "ct_withstand_a": 40.0,
        },
    },
    "GENERATOR_LEGACY": {
        "POMI Unit 7 - 846 MVA": {
            "mva": 846.231, "kv": 23.0, "ct_n": 24000, "ct_t": 24000,
            "target_amps": 0.2, "slope1": 10,
            "x1_pu": 0.155, "asym_factor": 1.73, "external_fault_ka": 186.0, "ct_withstand_a": 84.0,
        },
        "Custom Profile": {
            "mva": 10.0, "kv": 11.0, "ct_n": 100, "ct_t": 100,
            "target_amps": 0.2, "slope1": 10,
            "x1_pu": 0.15, "asym_factor": 1.73, "external_fault_ka": 0.0, "ct_withstand_a": 40.0,
        },
    },
}

MODE_LABELS = {
    "GENERATOR": "GE G60",
    "GENERATOR_LEGACY": "GE CFD22B4A",
}
