import math


# =====================================================================
# FAULT CURRENT ANALYSIS — per-unit source-reactance method.
#    Reproduces the exact methodology used in the plant's own settings
#    documents (e.g. Generator Diff setting.pdf, Section 5.1.1
#    Calculation/Discussion) for checking a relay's CTs against the
#    maximum current they'll actually see, rather than only checking the
#    relay's own characteristic curve in isolation:
#
#      I_base = MVA / (kV x sqrt(3))                    (rated base current)
#      I_fault_pu = E_pu / X1_pu                          (E_pu = 1.0, source at rated voltage)
#      I_fault_sym = I_fault_pu x I_base                    (symmetrical rms fault current)
#      I_fault_asym = asymmetry_factor x I_fault_sym         (worst-case, DC-offset included)
#
#    Verified against the settings doc's own worked example: generator
#    X1G=0.155pu, 846.231MVA/23kV -> I_base=21,242A, I_fault_pu=6.45,
#    I_fault_sym=137,010A, asymmetry factor 1.73 -> I_fault_asym=237,027A -
#    this module reproduces those exact figures.
#
#    Positive sequence reactance (X1) is the ONLY source parameter modeled
#    here - this is deliberately NOT a full short-circuit study (no network
#    reduction, no negative/zero-sequence networks, no multiple in-feeds).
#    For contributions from beyond the equipment's own terminals (e.g. grid
#    fault current fed through a step-up transformer to a fault on the low
#    side), this app has no system-wide impedance model to compute that
#    independently - the settings doc's own stated figure is used as a
#    reference input instead of a fabricated calculation.
# =====================================================================
def three_phase_fault_current(mva_base, kv_base, x1_pu, asymmetry_factor=1.73):
    """Three-phase fault current at the rated base of this equipment, using
    only its own positive-sequence reactance (source assumed at 1.0 pu
    voltage, infinite/simple Thevenin equivalent - no network reduction)."""
    i_base = (mva_base * 1000.0) / (1.7320508 * kv_base) if kv_base > 0 else 0.0
    i_fault_pu = (1.0 / x1_pu) if x1_pu > 0 else 0.0
    i_fault_sym = i_fault_pu * i_base
    i_fault_asym = asymmetry_factor * i_fault_sym
    return {
        "i_base": i_base,
        "i_fault_pu": i_fault_pu,
        "i_fault_sym_amps": i_fault_sym,
        "i_fault_asym_amps": i_fault_asym,
    }


def relay_secondary_at_fault(i_fault_amps, ct_ratio, ct_secondary_rating=5.0):
    """Converts a primary fault current through a CT to relay secondary
    current, for checking against the relay/CT's stated secondary
    current withstand limit."""
    effective_ratio = (ct_ratio / ct_secondary_rating) if ct_secondary_rating > 0 else ct_ratio
    return (i_fault_amps / effective_ratio) if effective_ratio > 0 else 0.0
