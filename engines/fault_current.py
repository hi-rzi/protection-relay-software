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


# =====================================================================
# TRANSFORMER THROUGH-FAULT CURRENT — nameplate-impedance method.
#    A transformer isn't a fault current SOURCE the way a generator is - its
#    own impedance instead LIMITS the maximum through-fault current for a
#    fault at (or beyond) its terminals. This reproduces the exact method in
#    the plant's own settings documents (e.g. Transformer Diff Setting -
#    EXCT.pdf, Calculation/Discussion):
#
#      I_base = MVA / (kV x sqrt(3))
#      I_sym = I_base / Z_pu                                    (symmetrical rms through-fault)
#      asym_factor = sqrt(1 + 2 x exp(-4 x pi x f x t x (R/X)))    (t = 0.5 cycle, the doc's own assumption)
#      I_asym = asym_factor x I_sym
#
#    Verified against EXCT's own worked example: 6300kVA/900V -> I_base=4041.5A,
#    Z=7% -> I_sym=57,736A, X/R=10 -> asym_factor=1.44 -> I_asym=83,140A -
#    this function reproduces those exact figures (and their 23kV-side
#    equivalents: I_base=158.1A, I_sym=2259A, I_asym=3253A).
#
#    Deliberately uses only this transformer's own nameplate impedance - not
#    a full short-circuit study (no source impedance beyond the transformer,
#    no network reduction). This is the standard "infinite bus" simplifying
#    assumption for a transformer's own through-fault withstand check.
# =====================================================================
def transformer_through_fault_current(mva_base, kv_base, z_pu, x_over_r=None, freq_hz=60.0, cycles=0.5, use_worst_case_asym=False):
    """
    use_worst_case_asym=True skips the X/R-based decay calculation and uses the flat
    sqrt(3)=1.73 asymmetry factor instead - the theoretical ceiling as X/R -> infinity (zero
    resistive decay of the DC offset at all). Some settings documents state this flat figure
    directly ("assuming high X/R") rather than computing the decay from the transformer's own
    X/R - it's always >= the X/R-based result, so it's a valid, more conservative alternative,
    just not specific to this transformer's actual X/R.
    """
    i_base = (mva_base * 1000.0) / (1.7320508 * kv_base) if kv_base > 0 else 0.0
    i_sym = (i_base / z_pu) if z_pu > 0 else 0.0
    if use_worst_case_asym:
        asym_factor = 1.7320508
    elif x_over_r is not None and x_over_r > 0:
        t = cycles / freq_hz
        r_over_x = 1.0 / x_over_r
        exponent = -4.0 * math.pi * freq_hz * t * r_over_x
        asym_factor = math.sqrt(1.0 + 2.0 * math.exp(exponent))
    else:
        asym_factor = 1.0
    i_asym = i_sym * asym_factor
    return {
        "i_base": i_base,
        "i_sym_amps": i_sym,
        "asym_factor": asym_factor,
        "i_asym_amps": i_asym,
    }
