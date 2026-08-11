"""
Generic protection relay engine for equipment this app has no dedicated model
for - lets a user assemble a relay from a library of standard, published
time-current curves and instantaneous/threshold elements rather than a
plant-specific hardcoded formula (contrast with engines/motor_869.py etc.,
each of which encodes one real relay's own settings-doc formula).

Curve library is the published IEC 60255-151 and IEEE C37.112 standard
inverse-time formulas - these are generic industry standards, not tied to any
one manufacturer, and are what most modern numerical relays offer as
selectable curve shapes. Element set (51/50/51N-50N/87/46) covers the common
overcurrent + self-balancing-differential + unbalance protection philosophy
already used elsewhere in this app; a percentage-restrained (dual-slope)
differential is deliberately NOT offered here, since that needs a
restraint-current input structure that varies per equipment (see the
Generator/Transformer engines for that) - out of scope for a generic model.
"""

# IEC 60255-151: t = TMS * k / ((I/Is)^alpha - 1)
# IEEE C37.112:  t = TD  * (A / ((I/Is)^p - 1) + B)
CURVE_LIBRARY = {
    "IEC Standard Inverse":     {"family": "IEC",  "k": 0.14,  "alpha": 0.02},
    "IEC Very Inverse":         {"family": "IEC",  "k": 13.5,  "alpha": 1.0},
    "IEC Extremely Inverse":    {"family": "IEC",  "k": 80.0,  "alpha": 2.0},
    "IEC Long Time Inverse":    {"family": "IEC",  "k": 120.0, "alpha": 1.0},
    "IEEE Moderately Inverse":  {"family": "IEEE", "A": 0.0515, "B": 0.1140, "p": 0.02},
    "IEEE Very Inverse":        {"family": "IEEE", "A": 19.61,  "B": 0.491,  "p": 2.0},
    "IEEE Extremely Inverse":   {"family": "IEEE", "A": 28.2,   "B": 0.1217, "p": 2.0},
    "Definite Time":            {"family": "DT"},
}

CURVE_NAMES = list(CURVE_LIBRARY.keys())


def curve_trip_time(curve_name, multiple, time_dial):
    """Trip time in seconds for a current `multiple` of pickup, or None if
    multiple <= 1 (no trip - below pickup). `time_dial` is the curve's own
    TMS (IEC) / Time Dial (IEEE) setting, or the fixed delay in seconds for
    Definite Time."""
    if multiple <= 1.0:
        return None
    params = CURVE_LIBRARY[curve_name]
    family = params["family"]
    if family == "IEC":
        return time_dial * params["k"] / (multiple ** params["alpha"] - 1.0)
    if family == "IEEE":
        return time_dial * (params["A"] / (multiple ** params["p"] - 1.0) + params["B"])
    if family == "DT":
        return time_dial
    raise ValueError(f"Unknown curve family: {family}")


def curve_sweep(curve_name, time_dial, m_min=1.05, m_max=20.0, points=60):
    """(multiples, trip_times) sample pair for plotting a TCC curve, log-spaced
    across the current-multiple range."""
    multiples = [m_min * (m_max / m_min) ** (i / (points - 1)) for i in range(points)]
    times = [curve_trip_time(curve_name, m, time_dial) for m in multiples]
    return multiples, times


class CustomRelay:
    """A user-assembled relay: CT spec + a set of enabled protection elements.

    `elements` is a dict keyed by element tag, only enabled elements present:
      "51":  {"pickup_sec": float, "curve": name in CURVE_LIBRARY, "time_dial": float}
      "50":  {"pickup_sec": float, "delay_ms": float}
      "51G": {"pickup_sec": float, "curve": name, "time_dial": float}
      "50G": {"pickup_sec": float, "delay_ms": float}
      "87":  {"pickup_primary": float}   -- self-balancing differential, instantaneous
      "46":  {"alarm_pct": float, "alarm_delay_s": float, "trip_pct": float, "trip_delay_s": float}
    """

    ELEMENT_LABELS = {
        "51": "51 (Phase Time-Overcurrent)",
        "50": "50 (Phase Instantaneous)",
        "51G": "51G (Ground Time-Overcurrent)",
        "50G": "50G (Ground Instantaneous)",
        "87": "87 (Self-Balancing Differential)",
        "46": "46 (Current Unbalance)",
    }

    def __init__(self, tag, ct_ratio, ct_secondary_rating, ground_ct_ratio=None,
                 ground_ct_secondary_rating=None, elements=None):
        self.tag = tag
        self.ct_ratio = ct_ratio
        self.ct_secondary_rating = ct_secondary_rating
        self.ground_ct_ratio = ground_ct_ratio
        self.ground_ct_secondary_rating = ground_ct_secondary_rating
        self.elements = elements or {}

    def phase_secondary_amps(self, i_primary):
        return (i_primary / self.ct_ratio * self.ct_secondary_rating) if self.ct_ratio else 0.0

    def ground_secondary_amps(self, i_ground_primary):
        if not self.ground_ct_ratio:
            return 0.0
        return i_ground_primary / self.ground_ct_ratio * self.ground_ct_secondary_rating

    def evaluate(self, i_phase_primary=0.0, i_ground_primary=0.0, i_diff_primary=0.0, unbalance_pct=0.0):
        """Evaluates every enabled element against the given test currents.
        Returns a dict of tag -> {multiple, trip_time, is_trip, status}."""
        results = {}
        i_phase_sec = self.phase_secondary_amps(i_phase_primary)
        i_ground_sec = self.ground_secondary_amps(i_ground_primary)

        for tag in ("51", "51G"):
            el = self.elements.get(tag)
            if not el:
                continue
            i_sec = i_phase_sec if tag == "51" else i_ground_sec
            multiple = (i_sec / el["pickup_sec"]) if el["pickup_sec"] else 0.0
            t = curve_trip_time(el["curve"], multiple, el["time_dial"]) if multiple > 1.0 else None
            is_trip = t is not None
            results[tag] = {
                "multiple": multiple, "trip_time": t, "is_trip": is_trip,
                "status": f"TRIP — {t:.2f}s" if is_trip else "Below Pickup",
            }

        for tag in ("50", "50G"):
            el = self.elements.get(tag)
            if not el:
                continue
            i_sec = i_phase_sec if tag == "50" else i_ground_sec
            multiple = (i_sec / el["pickup_sec"]) if el["pickup_sec"] else 0.0
            is_trip = multiple >= 1.0
            t = el["delay_ms"] / 1000.0 if is_trip else None
            results[tag] = {
                "multiple": multiple, "trip_time": t, "is_trip": is_trip,
                "status": f"TRIP — {el['delay_ms']:.0f}ms delay" if is_trip else "Below Pickup",
            }

        el = self.elements.get("87")
        if el:
            multiple = (i_diff_primary / el["pickup_primary"]) if el["pickup_primary"] else 0.0
            is_trip = multiple >= 1.0
            results["87"] = {
                "multiple": multiple, "trip_time": 0.0 if is_trip else None, "is_trip": is_trip,
                "status": "INSTANTANEOUS TRIP" if is_trip else "Below Pickup",
            }

        el = self.elements.get("46")
        if el:
            alarm = unbalance_pct >= el["alarm_pct"]
            trip = unbalance_pct >= el["trip_pct"]
            results["46"] = {
                "multiple": None, "trip_time": el["trip_delay_s"] if trip else None, "is_trip": trip,
                "status": (
                    f"TRIP — {el['trip_delay_s']:.0f}s delay" if trip
                    else f"ALARM — {el['alarm_delay_s']:.0f}s delay" if alarm
                    else "Below Pickup"
                ),
            }

        return results
