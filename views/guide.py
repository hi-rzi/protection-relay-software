import streamlit as st

st.title("Guide")
st.caption("How to use this app.")

st.markdown(
    """
Every equipment page follows the same 6-step sequence — once you know it on one page, you know it
on all nine:

1. **Pick equipment from the sidebar** (Generator, Transformer, or Motor) and choose the specific relay.
2. **Load a preset** at the top of the sidebar — a real POMI relay, or *Custom Profile* to enter your own ratings and CT specs. Not happy with what you've changed? The **↺ Reset to preset defaults** button below it puts every field back to the preset's stock values.
3. **Review "Current Settings"** — every applied setting, editable in place, with a live comment on whether it clears the recommended margin (🟢), needs a second look (🟠), or is informational only (⚪). A banner near the top shows whether this preset's values are ✓ verified against the real settings document or ⚠ only partially confirmed.
4. **Work through "Analysis & Tools" in order** — the tabs are always in this sequence:
   - **Theory** — how this protection scheme actually works, with the protection zone diagram.
   - **Live Simulation** — test a current/fault scenario against the relay's real trip logic.
   - **Commissioning & Injection Tool** — the exact secondary Amps to inject at the test set for a target result.
   - **Curve & Test Points** — the relay's own characteristic curve (a time-current curve for the motor pages' overcurrent elements, a bias/restraint curve for the generator and transformer differential relays), plus logging real test results against it.
   - **Fault Current Analysis** *(where this equipment has one)* — checks the CTs against a real fault current, including a CT saturation check and a step-by-step fault-clearing simulation.
   - **Settings Summary & Approval** — document control (source doc, revision, prepared/reviewed by, approval status), the relay-ready settings sheet, and a certified PDF audit report — the last step before sign-off.
5. **Check cross-equipment consistency and export everything together** on the **Project** page (sidebar) — settings status across all equipment, a coordination check, motor curve comparisons, and one bundled save/load.

Every recommendation is a rule-of-thumb starting point, not a substitute for a real coordination study — always confirm against the approved study, relay manual, and site test procedure before applying settings in service.

If a recommendation on a page looks extreme (e.g. a bias floor in the hundreds of percent), it's
almost always telling you an *input* is wrong — a CT ratio, tap, or connection type — not that the
setting genuinely needs to be that high. Check the inputs first.
"""
)
