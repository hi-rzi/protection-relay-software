"""
Shared "engineering concept" explanations for the Protection Concept tab on
each equipment page. These describe WHY each protection scheme is built the
way it is - the same underlying theory applies across several equipment
pages (all differential relays share the same restraint/bias/HOC logic;
both motor relays share the same time-overcurrent coordination logic), so
the core write-up lives here once and each page adds its own equipment-
specific notes on top.
"""
import streamlit as st


def render_differential_concept(variant):
    """variant: 'generator', 'transformer', or 'transformer_3w'."""
    st.markdown("### ⚡ How Percentage (Biased) Differential Protection Works")

    st.markdown(
        "**The zone concept & Kirchhoff's Current Law** — A differential relay watches every "
        "conductor entering and leaving a defined *zone* (via CTs on those conductors) and "
        "applies Kirchhoff's Current Law: in a healthy zone, everything that flows in must equal "
        "everything that flows out. If the CT-measured currents don't balance, current must be "
        "leaving the zone somewhere the relay didn't expect — a fault *inside* the zone."
    )

    with st.expander("📐 Operate current, restraint current, and why the trip line is sloped"):
        st.markdown(
            "- **Operate current (I_op)** — the vector sum of all CT currents into the zone. "
            "Should sit at ~0 whenever the zone is healthy.\n"
            "- **Restraint current (I_rest)** — a measure of how much current is passing *through* "
            "the zone (IEEE convention: average of the CT magnitudes; IEC convention: their sum). "
            "It represents how hard the zone is working under normal conditions.\n\n"
            "No pair of CTs is ever perfectly identical, and (for transformers) tap-changer "
            "position adds its own small error. That error current is proportional to how much "
            "current is flowing — so a *fixed* trip threshold would eventually misoperate on "
            "heavy healthy load or an external through-fault. The sloped (biased) characteristic "
            "fixes this: the I_op needed to trip rises with I_rest, so the relay tolerates the "
            "expected CT-error imbalance at high load while staying maximally sensitive to a real "
            "fault at low load."
        )
        st.latex(r"I_{threshold} = \max(\text{Minimum Operate}, \ \text{Bias\%} \times I_{rest})")

    with st.expander("🚦 Minimum Operate and the unrestrained instantaneous element (HOC)"):
        st.markdown(
            "**Minimum Operate** is a flat pickup floor. At near-zero restraint current, the "
            "sloped formula alone would demand an unrealistically tiny I_op to trip — easily "
            "triggered by noise — so a minimum sensible floor is set instead.\n\n"
            "**HOC (unrestrained instantaneous)** exists because, during a *very* severe internal "
            "fault, the resulting high current can saturate a CT badly enough to distort the "
            "restraint calculation itself, making the sloped math unreliable right when it matters "
            "most. HOC bypasses the restraint logic entirely: if I_op alone ever exceeds a large "
            "fixed threshold, trip immediately — no plausible through-load or CT error could ever "
            "produce differential current that large."
        )

    with st.expander("🔌 Why CT polarity matters"):
        st.markdown(
            "The whole \"current in = current out\" comparison only works if every CT's polarity "
            "mark is correctly oriented *and* correctly told to the relay. Get the polarity wrong "
            "and a sign in the math flips — a perfectly healthy zone can look like a permanent "
            "internal fault, or worse, a real fault can look healthy. That's why this app exposes "
            "a Polarity Reference (OPPOSITE/SAME) setting instead of silently assuming one — it "
            "needs to match how the CTs are actually wired in the field."
        )

    if variant in ("transformer", "transformer_3w"):
        st.markdown("### 🔧 Transformer-Specific: CT Tap Matching & Vector Group Compensation")
        with st.expander("⚖️ Why every winding needs its own CT matching tap"):
            st.markdown(
                "A transformer's two sides operate at completely different voltages — and "
                "therefore completely different currents. Even with perfect CTs, the raw "
                "secondary amps from (say) a 525kV-side CT and a 23kV-side CT for the *same* "
                "power flow will never numerically match. Each winding's relay input passes "
                "through its own matching tap, selected so that at rated load, every winding's "
                "tap-corrected current lands close to the same reference (1.0 pu) — that's what "
                "actually makes \"compare the currents from both sides\" a meaningful idea for a "
                "transformer in the first place. A small residual mismatch (~1%, from tap "
                "rounding) is normal and expected, not an error."
            )
        with st.expander("🔺 Why Delta/Wye transformers need √3 + 30° CT compensation"):
            st.markdown(
                "When a transformer has one Wye winding and one Delta winding, the phase "
                "relationship between the two sides' currents is inherently shifted (typically "
                "30°) by the transformer's own winding connection — a physical consequence of how "
                "three-phase transformers work, not a wiring mistake. Left uncorrected, a "
                "perfectly healthy, fully-loaded transformer would show up as a large phantom "
                "differential current. Classic protection practice corrects for this by wiring "
                "the CTs on the transformer's Wye side in Delta (and vice versa) — which also "
                "introduces a √3 magnitude step. `engines/transformer.py` reproduces that same "
                "compensation numerically (per each winding's `ct_connection` setting) instead of "
                "relying on physical CT wiring."
            )

    if variant == "transformer_3w":
        st.markdown("### 🛡️ Why an \"Overall\" Backup Zone Exists")
        with st.expander("🗺️ Overlapping zones of protection"):
            st.markdown(
                "Protection zones are deliberately designed to *overlap*. The Generator's own "
                "87G relay protects only the stator winding; GSUT's own 87GT relay protects only "
                "the transformer. The short bus and leads connecting them — and the Unit "
                "Auxiliary Transformer tap-off — aren't uniquely covered by either one. The "
                "Overall (87O) relay creates a wider, encompassing zone spanning all of it, so a "
                "fault anywhere in that gap is still cleared quickly by a dedicated (if less "
                "sensitive) backup element, rather than depending entirely on remote/upstream "
                "protection to eventually clear it."
            )


def render_overcurrent_concept(include_thermal_replica=False):
    st.markdown("### ⏱️ How Motor Time-Overcurrent Protection Works")

    with st.expander("🏁 Coordinating with the starting characteristic"):
        st.markdown(
            "A motor draws several times its running (FLA) current for several seconds every "
            "time it starts — completely normal, and must *not* trip the relay. But if the rotor "
            "is locked (jammed, stalled), that same high current continues indefinitely and will "
            "burn out the winding insulation within a fixed *safe stall time*. The relay's entire "
            "job is threading that needle: ride through a normal start, but trip before the safe "
            "stall time on a genuine locked-rotor condition."
        )

    with st.expander("📉 Why inverse-time curves, not a fixed time delay"):
        st.markdown(
            "An inverse-time curve trips *faster* as current increases — which happens to match "
            "how motor thermal damage accelerates with current too. A single curve shape can "
            "simultaneously tolerate the (known, bounded) starting current for its expected "
            "duration *and* trip quickly on a severe stall, without needing a separate timer "
            "logic for each condition."
        )

    with st.expander("⚡ Why there's also an instantaneous element"):
        st.markdown(
            "For a genuine short-circuit fault (as opposed to starting or stall, which are "
            "thermal/mechanical events, not electrical faults), current can reach many times even "
            "locked-rotor level — high enough that immediate tripping is both safe (it will never "
            "occur during a legitimate start) and necessary (a fault of that magnitude must clear "
            "fast, before it does other damage)."
        )

    if include_thermal_replica:
        with st.expander("🌡️ Thermal replica / memory (why the SR469 goes further than a re-timed curve)"):
            st.markdown(
                "A microprocessor relay like the SR469 maintains a running **Thermal Capacity "
                "Used** — a percentage-like memory of how hot the motor's internal model currently "
                "is, which decays over time once current drops (with a slower decay when stopped, "
                "since a stationary motor without airflow cools more slowly than one still "
                "running). This means back-to-back starts, or an overload that partially heats the "
                "motor before easing off, are still tracked correctly — the relay \"remembers\" "
                "the motor was already warm, rather than treating every new event as starting from "
                "cold, the way a simple discrete electromechanical relay effectively does."
            )
        with st.expander("🌀 K-factor & why unbalance causes extra heating"):
            st.markdown(
                "Unbalanced supply voltage (or single-phasing) creates negative-sequence current "
                "in the motor. Even a *small* negative-sequence current causes disproportionately "
                "large extra heating, because it induces rotor currents at roughly double system "
                "frequency that concentrate very close to the rotor bar surface (skin effect) — "
                "generating far more heat per amp than the same magnitude of normal "
                "(positive-sequence) current would. The K-factor is how the thermal model weights "
                "negative-sequence current more heavily than positive-sequence current, so the "
                "\"memory\" reflects real heating rather than just total RMS amps."
            )
            st.latex(r"K = \dfrac{230}{(\text{Locked Rotor Current, in multiples of FLA})^2}")
