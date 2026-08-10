import streamlit as st

st.title("Guide")
st.caption("How to use this app.")

st.markdown(
    """
Every equipment page follows the same 5-step sequence — once you know it on one page, you know it
on all nine:

1. **Pick equipment from the Home page** — click the card for the relay you want (Generator, Transformer, or Motor); Home is the only place equipment is chosen, it's not in the sidebar.
2. **Load a preset** at the top of the sidebar — a real POMI relay, or *Custom Profile* to enter your own ratings and CT specs. Not happy with what you've changed? The **↺ Reset to preset defaults** button below it puts every field back to the preset's stock values. Want to keep what you've entered? **💾 Save Profile** (bottom of Settings Summary & Approval) downloads it under a name you choose — reload it later with the loader further down the sidebar.
3. **Review "Current Settings"** — every applied setting, editable in place, with a live comment on whether it clears the recommended margin (🟢), needs a second look (🟠), or is informational only (⚪). A banner near the top shows whether this preset's values are ✓ verified against the real settings document or ⚠ only partially confirmed. Click **📊 Show Live Preview** any time to see the characteristic curve reflect the settings below it. By default it stays pinned above whichever section you pick next — uncheck **Pin Current Settings** in the sidebar if you'd rather it be just another section.
4. **Work through the sidebar sections in order** — they're always in this sequence:
   - **Theory** — how this protection scheme actually works, with the protection zone diagram.
   - **Simulate & Test** — test a current/fault scenario against the relay's real trip logic and see the characteristic curve live, then (if you want) log real test results and build your own graph against that same curve, all in one place.
   - **Commissioning & Injection Tool** — the exact secondary Amps to inject at the test set for a target result.
   - **Fault Current Analysis** *(generator and transformer pages)* — checks the CTs against a real fault current, including a step-by-step fault-clearing simulation.
   - **Settings Summary & Approval** — document control (source doc, revision, prepared/reviewed by, approval status), the relay-ready settings sheet, and a certified PDF audit report — the last step before sign-off.
5. **Check cross-equipment consistency and export everything together** on the **Project** page (sidebar) — settings status across all equipment, a coordination check, motor curve comparisons, and one bundled save/load.

Every recommendation is a rule-of-thumb starting point, not a substitute for a real coordination study — always confirm against the approved study, relay manual, and site test procedure before applying settings in service.

If a recommendation on a page looks extreme (e.g. a bias floor in the hundreds of percent), it's
almost always telling you an *input* is wrong — a CT ratio, tap, or connection type — not that the
setting genuinely needs to be that high. Check the inputs first.
"""
)

with st.expander("Notes on a few equipment-specific differences"):
    st.markdown(
        """
- **Wiring & Convention** (Restraint Standard, CT Polarity) is at the top of the **Simulate & Test** section for the generator and transformer pages, not Current Settings — it only affects that evaluation.
- **Motor pages** don't have a separate Fault Current Analysis section. Their fault-clearing simulation lives inside **Simulate & Test** instead, and skips the current waveform (no real X/R data exists for a motor short-circuit contribution).
"""
    )
