import math


# =====================================================================
# MOTOR SELF-BALANCING DIFFERENTIAL RELAY (87M)
#    GE HFC23C1A, per GEK-49826C / P101-17-1823.10-0002 Section 5.13.
#    Fitted to motors larger than 1500HP (in addition to whatever
#    overcurrent/thermal protection - 50/50/51, SR469, GE 869 - that
#    motor already has, modeled elsewhere in this app).
#
#    This is NOT a percentage-bias differential like the generator/
#    transformer relays elsewhere in this app - it's a self-balancing
#    (core-balance) scheme: both the LINE and NEUTRAL conductors of a
#    single phase pass through ONE current transformer. Under a healthy
#    motor, line and neutral current are equal and opposite through
#    that CT window, so they cancel and no current flows in the CT
#    secondary at all. Any imbalance (an internal winding fault between
#    the phase and neutral conductors) produces CT secondary current
#    and trips the relay - instantaneously, with a single pickup
#    setting, no restraint/bias slope and no time-current curve.
#
#    Per the settings document's own Calculation/Discussion: pickup is
#    set at 20A PRIMARY for every motor regardless of its CT ratio -
#    which becomes 2.0A secondary on a 50/5 CT (all motors except
#    Induced Draft Fans) or 1.0A secondary on a 100/5 CT (Induced Draft
#    Fans specifically, which use a different, larger CT ratio here).
#    Verified: 20/(50/5)=2.0A, 20/(100/5)=1.0A - both match the doc's
#    own stated Setting Summary exactly.
# =====================================================================
class SelfBalancingDifferentialRelay:
    def __init__(self, ct_ratio, ct_secondary_rating, pickup_amps_sec):
        self.ct_ratio = ct_ratio
        self.ct_secondary_rating = ct_secondary_rating
        self.effective_ratio = (ct_ratio / ct_secondary_rating) if ct_secondary_rating > 0 else ct_ratio
        self.pickup_amps_sec = pickup_amps_sec  # relay secondary amps (the field-set tap value)
        self.pickup_amps_primary = pickup_amps_sec * self.effective_ratio

    def relay_current(self, i_primary):
        return i_primary / self.effective_ratio if self.effective_ratio > 0 else 0.0

    def evaluate_protection(self, imbalance_primary_amps):
        """imbalance_primary_amps: the NET (line minus neutral) current through the
        self-balancing CT window - zero for a healthy motor, nonzero only for an
        internal winding fault or a genuine CT/wiring problem."""
        i_sec = self.relay_current(imbalance_primary_amps)
        is_trip = i_sec >= self.pickup_amps_sec
        return {
            "i_relay_sec": i_sec,
            "is_trip": is_trip,
            "status": "87M INSTANTANEOUS TRIP" if is_trip else "SAFE",
        }
