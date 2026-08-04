import streamlit as st

st.title("Electrical Equipment Protection Suite")
st.caption("Protection settings calculation, commissioning-injection assistance, and settings verification for generator, transformer, and motor protection relays.")

st.markdown(
    """
This app helps engineers work through protection relay settings for generator,
transformer, and motor equipment. For each relay it provides:

- **Live simulation** — enter operating currents and see the real-time trip/restraint verdict against the relay's characteristic curve.
- **Commissioning & injection tool** — calculates the exact secondary current to inject at a test set for a target test point.
- **Test point verification** — log actual measured test results and compare them against the calculated characteristic.
- **PDF / CSV export** — for keeping a record of settings and test results.

Every equipment page ships with built-in presets (currently POMI's own relay settings), but you're not
limited to them — each page also lets you add a **custom profile** with your own ratings, CT
specs, and protection settings, so the app works for equipment outside POMI too.

Working across several equipment for the same plant? The **Project** page bundles the settings
you've configured across all of them into one named, saveable file — see the sidebar.

Pick an equipment category from the sidebar to get started.
"""
)

st.markdown("### Quick Start")
st.markdown(
    """
1. **Pick an equipment category from the sidebar** (Generator, Transformer, or Motor) and choose the specific relay.
2. **Load a preset** at the top of the sidebar — a real POMI relay, or *Custom Profile* to enter your own ratings and CT specs. The page fills in immediately with real settings.
3. **Scroll the "Current Settings" section** at the top of the page — every setting currently applied is right there, editable in place. Adjust a value and read the comment beside it:
   - 🟢 green = clears the recommended margin
   - 🟠 orange = below the recommended margin, worth a second look
   - ⚪ neutral = informational only (no automated check exists for that setting yet — engineering judgment required)
4. **Use the tabs below** for deeper work — simulate a fault, calculate a commissioning test injection, view the trip-time curve, or export a report. See the breakdown below for what each tab does.
"""
)

with st.expander("What each part of an equipment page does", expanded=False):
    st.markdown(
        """
**Current Settings** (top of every page, always visible)
The full picture in one scroll — no digging through a sidebar or expanders to find a value. Comments next to each field reuse the same engineering checks the app uses everywhere else (CT/tap mismatch, pickup vs. FLA/locked-rotor current, starting time vs. safe-stall time) — nothing is invented on the spot. Where no rule-of-thumb check exists yet, the app says so instead of guessing. An "Overall status" line at the end summarizes whether everything shown clears its margin.

**Theory tab**
What the relay protects and why, plus a single-line diagram of its zone and (for motors) a live thermal-capacity replica.

**Live Simulation tab**
Enter an operating or fault current and see the real-time trip/restraint verdict against the relay's actual characteristic curve — the fastest way to sanity-check "would this trip?" for a specific scenario.

**Commissioning & Injection Tool tab**
Pick a target test point and get the exact secondary current to inject at your test set, plus an auto-generated sweep table for a full commissioning test plan.

**TCC Curve / Test Point Verification tab**
The relay's time-current characteristic plotted out, with the motor's starting profile and safe-stall limits overlaid where that data exists. Log actual measured test results here too, to compare against the calculated curve.

**Settings Summary & Approval tab**
A document-control record — source document, revision, prepared/reviewed by, review status — plus a consolidated coordination review and a PDF/JSON export, for when settings are ready to go through engineering sign-off.
"""
    )

with st.expander("Cross-equipment features (Project page)", expanded=False):
    st.markdown(
        """
- **Save/load a Project** — bundles every equipment page's current settings into one named file, so you can pick up where you left off or hand it to someone else.
- **Equipment Status dashboard** — a one-glance health signal (OK / Review / not yet configured) across everything you've touched this session.
- **Protection Zone Coordination Check** — cross-references the Generator, GSUT, and Overall GSUT-GEN pages against each other: CT ratios that should physically match (shared CTs feeding both a primary and backup relay), and which equipment has documented backup differential coverage and which doesn't.
"""
    )

st.markdown(
    """
**A note on what this app is (and isn't):** every page supports settings checks and commissioning
calculations, but does not itself approve relay settings. Recommendations are rule-of-thumb starting
points and consistency checks, not a substitute for a real through-fault/inrush coordination study —
always verify against the approved coordination study, relay manual, and site test procedure before
applying settings in service.
"""
)

st.markdown("### Available Equipment")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("#### Generator")
    st.write(
        "Generator differential protection (87G) covering:\n"
        "- GE G60 numerical dual-breakpoint characteristic\n"
        "- GE CFD22B4A legacy product-restraint characteristic"
    )

with col2:
    st.markdown("#### Transformer")
    st.write(
        "Transformer differential protection covering:\n"
        "- Excitation Transformer (EXCT)\n"
        "- Generator Step-Up Transformer (GSUT)\n"
        "- Overall GSUT-GEN (backup, 3-winding)\n"
        "- Auxiliary Transformer"
    )

with col3:
    st.markdown("#### Motor")
    st.write(
        "Motor protection covering:\n"
        "- Induced Draft (ID) Fan — 50/50/51 time-overcurrent, GE 869 microprocessor MPR\n"
        "- Primary Air (PA) Fan and Forced Draft (FD) Fan — Multilin SR469 static MPR"
    )
