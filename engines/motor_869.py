import math


# =====================================================================
# GE MULTILIN 869 MOTOR PROTECTION RELAY (microprocessor-based)
#    Settings basis: P101-17-1823.10-0002 Rev. 0, Section 5.1.3, which was
#    written against the plant's originally-specified SR469. The SR469 has
#    since been superseded in service by the 869, but both are GE Multilin
#    motor relays built on the same Thermal Capacity Used (TCU) protection
#    architecture - the 869's own instruction manual (GEA-12784) describes
#    the identical model: a single integrated stator/rotor heating register
#    (TCU) that increments with overload current and unbalance, and decays
#    on a running/stopped cooling time constant. The settings doc's current-
#    based numbers (Overload Pickup, Curve, K-factor) therefore carry over
#    directly - only the relay hardware changed, not the protection math.
#
#    51 (Overload, thermal model):
#       Trip time formula per the settings doc's Calculation/Discussion,
#       verified against its own worked examples (4.8x FLA on Curve X4 ->
#       15.9s; 3.8x FLA -> 25.8s). This is the GE Multilin "Standard" thermal
#       curve shared across the 469/269Plus/369/869 relay lineage, not a
#       SR469-exclusive formula:
#           T = (CM x 2.2116623) / (0.025303373x(M-1)^2 + 0.050547581x(M-1))
#       where CM = Curve Multiplier (the "X4" setting) and M = measured
#       current AS A MULTIPLE OF MOTOR FLA (not of the % pickup setting -
#       confirmed by reproducing the doc's own numeric examples exactly).
#       No trip (M <= 1, i.e. below FLA) returns None.
#
#    50 (Instantaneous): set at ~200% of locked rotor current, per the
#       settings doc's stated criterion, with a short definite time delay
#       (60ms / 3 cycles) to ride through starting transients.
#
#    50G/51G (Ground Fault): via a separate low-ratio (50/5) zero-sequence
#       CT. Pickup expressed as a fraction of the ground CT's PRIMARY
#       rating (not the phase CT), per the settings doc.
#
#    46 (Current Unbalance): separate alarm and trip stages, both defined
#       as % negative-sequence-to-positive-sequence current ratio.
#
#    K-factor (Unbalance Bias): a static thermal-model bias setting, not a
#       live trip element - K = 230 / (locked rotor current, in multiples
#       of FLA)^2 (the "conservative" GE Multilin formula; 175/LRA^2 is the
#       "typical" alternative quoted in GE's own application guidance), per
#       the settings doc's reproduced formula.
#
#    Hot/Cold Safe Stall Ratio: HCR = LRT_hot / LRT_cold, the same
#       methodology GE Multilin publishes for setting up the 869's thermal
#       model - computed live in the view from the motor datasheet's own
#       ambient (cold) and hot safe-stall times, not a hardcoded constant.
#
#    All other 869 functions the settings doc covers (Mechanical Jam,
#    Acceleration Timer, Overload Alarm, Overtemperature 38/49, Overvoltage
#    59, Jogging Block 66, Over/Underfrequency 81, Phase Differential 87,
#    Underpower 37, Start Inhibit, Digital Inputs) are settings-only in
#    this app - documented and shown for reference, not live-simulated,
#    matching how the existing 50/50/51 page already scopes itself to the
#    primary current-based elements rather than modeling every function.
# =====================================================================
class Motor869Relay:
    OVERLOAD_CURVE = {"A": 2.2116623, "B": 0.025303373, "C": 0.050547581}

    def __init__(self, ct_ratio, ct_secondary_rating, motor_fla, locked_rotor_amps,
                 overload_pickup_pct=115.0, curve_multiplier=4.0,
                 inst_pickup_multiple_of_lr=2.0, inst_delay_ms=60.0,
                 ground_ct_ratio=50.0, ground_ct_secondary_rating=5.0,
                 gf_pickup_frac_of_ct=0.1, gf_delay_ms=60.0,
                 unbal_alarm_pct=15.0, unbal_alarm_delay_s=30.0,
                 unbal_trip_pct=15.0, unbal_trip_delay_s=60.0,
                 mech_jam_pct=150.0, mech_jam_delay_s=1.0,
                 accel_timer_s=25.0, overload_alarm_delay_s=1.0):
        self.ct_ratio = ct_ratio
        self.ct_secondary_rating = ct_secondary_rating
        self.effective_ratio = (ct_ratio / ct_secondary_rating) if ct_secondary_rating > 0 else ct_ratio
        self.motor_fla = motor_fla
        self.locked_rotor_amps = locked_rotor_amps
        self.overload_pickup_pct = overload_pickup_pct
        self.curve_multiplier = curve_multiplier
        self.inst_pickup_amps = inst_pickup_multiple_of_lr * locked_rotor_amps  # primary A
        self.inst_delay_ms = inst_delay_ms

        self.ground_ct_ratio = ground_ct_ratio
        self.ground_ct_secondary_rating = ground_ct_secondary_rating
        self.ground_effective_ratio = (ground_ct_ratio / ground_ct_secondary_rating) if ground_ct_secondary_rating > 0 else ground_ct_ratio
        self.gf_pickup_amps = gf_pickup_frac_of_ct * ground_ct_ratio  # primary A (of the ground CT, per settings doc)
        self.gf_delay_ms = gf_delay_ms

        self.unbal_alarm_pct = unbal_alarm_pct
        self.unbal_alarm_delay_s = unbal_alarm_delay_s
        self.unbal_trip_pct = unbal_trip_pct
        self.unbal_trip_delay_s = unbal_trip_delay_s

        self.mech_jam_pct = mech_jam_pct
        self.mech_jam_delay_s = mech_jam_delay_s
        self.accel_timer_s = accel_timer_s
        self.overload_alarm_delay_s = overload_alarm_delay_s

        lr_multiple_of_fla = (locked_rotor_amps / motor_fla) if motor_fla > 0 else 0.0
        self.k_factor = (230.0 / (lr_multiple_of_fla ** 2)) if lr_multiple_of_fla > 0 else 0.0

    def relay_current(self, i_primary):
        return i_primary / self.effective_ratio if self.effective_ratio > 0 else 0.0

    def calculate_overload_trip_time(self, i_primary):
        """Returns trip time in seconds, or None if below FLA (M <= 1)."""
        if self.motor_fla <= 0:
            return None
        m = i_primary / self.motor_fla
        if m <= 1.0:
            return None
        x = m - 1.0
        c = self.OVERLOAD_CURVE
        denom = c["B"] * (x ** 2) + c["C"] * x
        if denom <= 0:
            return None
        return self.curve_multiplier * c["A"] / denom

    def evaluate_protection(self, i_primary):
        i_sec = self.relay_current(i_primary)
        m_fla = (i_primary / self.motor_fla) if self.motor_fla > 0 else 0.0
        t51 = self.calculate_overload_trip_time(i_primary)
        trip_51 = t51 is not None
        trip_50 = i_primary >= self.inst_pickup_amps

        is_trip = trip_51 or trip_50
        if trip_50:
            status = f"INSTANTANEOUS TRIP (50) — {self.inst_delay_ms:.0f}ms delay"
        elif trip_51:
            status = f"OVERLOAD TRIP (51) — {t51:.2f}s"
        else:
            status = "SAFE"

        return {
            "i_relay_sec": i_sec,
            "multiple_of_fla": m_fla,
            "t51": t51,
            "trip_51": trip_51,
            "trip_50": trip_50,
            "is_trip": is_trip,
            "status": status,
        }

    def evaluate_ground_fault(self, i_ground_primary):
        is_trip = i_ground_primary >= self.gf_pickup_amps
        return {
            "i_ground_primary": i_ground_primary,
            "is_trip": is_trip,
            "status": f"GROUND FAULT TRIP (50G/51G) — {self.gf_delay_ms:.0f}ms delay" if is_trip else "SAFE",
        }

    def evaluate_unbalance(self, unbalance_pct):
        """unbalance_pct: negative-sequence / positive-sequence current ratio, in %."""
        alarm = unbalance_pct >= self.unbal_alarm_pct
        trip = unbalance_pct >= self.unbal_trip_pct
        if trip:
            status = f"UNBALANCE TRIP (46) — {self.unbal_trip_delay_s:.0f}s delay"
        elif alarm:
            status = f"UNBALANCE ALARM (46) — {self.unbal_alarm_delay_s:.0f}s delay"
        else:
            status = "SAFE"
        return {"alarm": alarm, "trip": trip, "is_trip": trip, "status": status}


def hot_cold_safe_stall_ratio(safe_stall_hot, safe_stall_cold):
    """HCR = LRT_hot / LRT_cold, per GE Multilin's thermal-model setup methodology."""
    return (safe_stall_hot / safe_stall_cold) if safe_stall_cold > 0 else None
