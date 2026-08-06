"""
Shared "Raw per-CT currents" input mode for the Test Point Verification forms on the 5
differential pages. Some commissioning workflows read restraint/operate current straight
off a test set (Omicron, Doble) or the relay's own metering display; others only have raw
current measured/injected at each winding's CT and would otherwise have to hand-compute
tap-corrected restraint/differential current themselves. This lets either be entered, with
the raw-current path reusing the relay's own evaluate_protection() so the math matches
exactly what the relay does internally.
"""
import streamlit as st

TEST_POINT_SOURCE_OPTIONS = ["Restraint & Diff directly", "Raw per-CT currents"]

TEST_POINT_SOURCE_HELP = (
    "If your test set (e.g. Omicron, Doble) or the relay's own metering display already shows "
    "restraint/operate current, enter those directly. Otherwise, enter the raw current "
    "measured or injected at each winding's CT and the app computes restraint & differential "
    "current the same way the relay does internally — no manual tap-correction math needed."
)


def raw_current_inputs(winding_labels, key_prefix, default_primary_amps=None):
    """Renders one Primary Amps + Angle number_input pair per winding, in columns.
    Call this INSIDE an st.form. Returns a list of (i_primary_amps, angle_deg) tuples,
    same order as winding_labels."""
    inputs = []
    cols = st.columns(len(winding_labels))
    for idx, (col, label) in enumerate(zip(cols, winding_labels)):
        with col:
            default_amp = float(default_primary_amps[idx]) if default_primary_amps else 0.0
            amp = st.number_input(
                f"{label} [A]", min_value=0.0, value=default_amp, step=1.0,
                key=f"{key_prefix}_i_{idx}",
            )
            ang = st.number_input(
                f"{label} Angle (°)", value=0.0, step=1.0, key=f"{key_prefix}_a_{idx}",
            )
            inputs.append((amp, ang))
    return inputs
