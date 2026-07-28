import cmath
import math


# =====================================================================
# TRANSFORMER DIFFERENTIAL RELAY ENGINE (87T)
#    GE CAC1-10-M3 (2-winding: EXCT, GSUT) / CAC2-10-M3 (3-winding: Overall
#    GSUT-GEN backup) family, per P101-17-1823.16-0001 Rev. 5.
#
#    Each winding carries its own CT-matching tap T_i, selected (per the
#    source document) so that the tap-corrected current at rated load is
#    close to the relay's own rated tap current (I_N, typically 5A):
#        i_tap_pu_i = (i_secondary_i * T_i) / ct_secondary_rating_i
#    This intentionally reproduces the small residual "mismatch" between
#    windings at rated load rather than assuming a perfect 0 pu balance.
#
#    Operate current is the magnitude of the phasor sum of all windings'
#    tap-corrected currents (winding 0 is the reference/HV winding; the
#    OPPOSITE/SAME polarity convention flips the others, exactly mirroring
#    the 2-winding Generator engine's N/T convention, generalized to N
#    windings).
#
#    Trip threshold = max(Minimum Operate %, Bias % x restraint) - confirmed
#    directly by the source document's plain-language description of the
#    relay's "bias setting (slope)" and "minimum operating current setting".
#    HOC is an unrestrained instantaneous element: trips if operate current
#    >= HOC x tap current (i.e. >= HOC pu, since 1.0 pu = I_N).
#
#    Restraint convention (average vs. sum across windings) is NOT fully
#    pinned down by the scanned Setting Summary pages for the 3-winding
#    case, so — consistent with the existing IEEE/IEC toggle on the
#    Generator engine — it is exposed as a selectable convention rather
#    than silently assumed.
#
#    Delta/Wye CT compensation: whenever a winding's CT is connected in
#    DELTA (the standard way to compensate for the power transformer's own
#    Wye/Delta vector group so healthy through-load doesn't look like a
#    fault), the settings doc's own worked examples (GSUT and UAT
#    Calculation/Discussion sections) show the relay current is the CT
#    secondary current times sqrt(3) - e.g. GSUT: I_RH = I_SH x sqrt(3).
#    That magnitude step is applied automatically below based on each
#    winding's "ct_connection". The accompanying 30-degree phase shift is
#    also applied (defaulted to +30 deg, since the source documents only
#    verify magnitude balance, not a phase reference) - override via
#    "delta_angle_shift": -30.0 on a winding if commissioning results show
#    the sign is backwards for that CT's actual field wiring.
# =====================================================================
class TransformerDifferentialRelay:
    def __init__(self, mva_rated, windings, bias_pct, min_operate_pct, hoc_multiple,
                 convention="IEEE", ct_polarity="OPPOSITE"):
        """
        windings: list of dicts, each with keys:
            name, kv, ct_ratio, ct_secondary_rating, tap
          windings[0] is the reference (HV) winding.
        """
        self.mva_rated = mva_rated
        self.windings = [dict(w) for w in windings]
        self.bias = bias_pct / 100.0
        self.min_operate_pu = min_operate_pct / 100.0
        self.hoc_pu = hoc_multiple
        self.convention = convention.upper()
        self.ct_polarity = ct_polarity.upper()

        for w in self.windings:
            w["effective_ratio"] = (w["ct_ratio"] / w["ct_secondary_rating"]) if w["ct_secondary_rating"] > 0 else w["ct_ratio"]
            w["i_rated_pri"] = (mva_rated * 1000.0) / (math.sqrt(3) * w["kv"]) if w["kv"] > 0 else 1.0
            w["i_rated_sec"] = w["i_rated_pri"] / w["effective_ratio"] if w["effective_ratio"] > 0 else w["i_rated_pri"]
            is_delta = w.get("ct_connection", "WYE").upper() == "DELTA"
            w["delta_factor"] = math.sqrt(3) if is_delta else 1.0
            w["delta_angle_shift"] = w.get("delta_angle_shift", 30.0) if is_delta else 0.0

    def calculate_trip_threshold(self, i_rest_pu):
        return max(self.min_operate_pu, self.bias * i_rest_pu)

    def evaluate_protection(self, winding_inputs):
        """winding_inputs: list of (i_primary_amps, angle_deg), same order as self.windings."""
        vecs_pu = []
        mags_pu = []
        for idx, (w, (i_pri, angle_deg)) in enumerate(zip(self.windings, winding_inputs)):
            i_sec = i_pri / w["effective_ratio"] if w["effective_ratio"] > 0 else 0.0
            i_tap_pu = (i_sec * w["tap"]) / w["ct_secondary_rating"] if w["ct_secondary_rating"] > 0 else 0.0
            i_tap_pu *= w["delta_factor"]
            effective_angle = angle_deg + w["delta_angle_shift"]
            vec = cmath.rect(i_tap_pu, math.radians(effective_angle))
            if idx > 0 and self.ct_polarity == "OPPOSITE":
                vec = -vec
            vecs_pu.append(vec)
            mags_pu.append(abs(vec))

        vec_op = sum(vecs_pu)
        i_op_pu = abs(vec_op)

        if self.convention == "IEEE":
            i_rest_pu = sum(mags_pu) / len(mags_pu)
        else:
            i_rest_pu = sum(mags_pu)

        i_threshold_pu = self.calculate_trip_threshold(i_rest_pu)

        is_unrestrained_trip = i_op_pu >= self.hoc_pu
        is_restrained_trip = i_op_pu > i_threshold_pu
        is_trip = is_unrestrained_trip or is_restrained_trip

        status_text = "SAFE"
        if is_unrestrained_trip:
            status_text = "UNRESTRAINED TRIP (HOC)"
        elif is_restrained_trip:
            status_text = "SLOPE TRIP"

        return {
            "i_op_pu": i_op_pu,
            "i_rest_pu": i_rest_pu,
            "i_threshold_pu": i_threshold_pu,
            "is_trip": is_trip,
            "is_unrestrained": is_unrestrained_trip,
            "status": status_text,
            "winding_mags_pu": mags_pu,
        }


# =====================================================================
# UI-DEFAULT HELPERS
#    Used only to compute "healthy through-load" default values for the
#    Live Simulation tab's phase-input widgets - not part of the relay's
#    own trip logic. Forward/inverse pair for the per-winding transform
#    evaluate_protection() applies BEFORE the OPPOSITE/SAME polarity flip
#    (CT ratio -> tap -> Delta sqrt(3)+angle compensation).
# =====================================================================
def winding_internal_vector(relay, idx, i_pri, angle_deg):
    """Forward: raw (primary amps, angle) -> per-unit phasor for that winding,
    before the OPPOSITE/SAME polarity flip is applied."""
    w = relay.windings[idx]
    i_sec = i_pri / w["effective_ratio"] if w["effective_ratio"] > 0 else 0.0
    i_tap_pu = (i_sec * w["tap"] / w["ct_secondary_rating"]) * w["delta_factor"] if w["ct_secondary_rating"] > 0 else 0.0
    return cmath.rect(i_tap_pu, math.radians(angle_deg + w["delta_angle_shift"]))


def raw_input_for_internal_vector(relay, idx, target_internal_vec):
    """Inverse of winding_internal_vector: given a target pre-polarity-flip phasor,
    back-solve the raw (primary_amps, angle_deg) a user would type in the UI."""
    w = relay.windings[idx]
    mag = abs(target_internal_vec)
    ang = math.degrees(cmath.phase(target_internal_vec)) if mag > 0 else 0.0
    denom = (w["tap"] / (w["effective_ratio"] * w["ct_secondary_rating"])) * w["delta_factor"] \
        if w["effective_ratio"] > 0 and w["ct_secondary_rating"] > 0 else 0.0
    i_pri = mag / denom if denom > 0 else 0.0
    angle_deg = ang - w["delta_angle_shift"]
    return i_pri, angle_deg


def solve_healthy_target_angle(relay, target_idx, reference_idx, reference_amps, reference_angle):
    """
    Solve the angle that makes `target_idx` winding's contribution cancel the
    `reference_idx` winding's (assuming every OTHER winding is at 0A), for
    whichever ct_polarity the relay currently has. Magnitude is left to the
    caller (typically the target winding's own rated current).

    This is what keeps a Live Simulation default healthy when the user changes
    Polarity Reference AFTER the page has already loaded: Streamlit widgets
    stop re-reading their `value=` argument once created, so recomputing this
    inline on every script rerun isn't enough - it must also be called from an
    on_change callback that overwrites st.session_state directly (see each
    transformer page's _on_polarity_change()).
    """
    vec_ref = winding_internal_vector(relay, reference_idx, reference_amps, reference_angle)
    sign = -1 if relay.ct_polarity == "OPPOSITE" else 1
    target_internal = -vec_ref * sign
    _, angle_deg = raw_input_for_internal_vector(relay, target_idx, target_internal)
    return angle_deg
