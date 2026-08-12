import streamlit as st

from common.theme import flow_row

st.title("Guide")
st.caption("How to use this app — same flow on every equipment page.")

flow_row("1 · Get started", [
    ("🏠", "Home"),
    ("⚡🔌🌀", "Pick a card"),
    ("⚙️", "Load preset"),
])
st.caption(
    "Protecting something other than the plant's own generator/transformer/motor lineup? "
    "Use the **🧩 Custom** card on Home instead of a preset — it walks through the same "
    "sections below for a relay you define yourself (CT spec + whichever protection elements "
    "it has)."
)
st.caption(
    "Home is also where the 📖 Guide and 📁 Project quick links live, since Home hides the "
    "sidebar to keep the equipment picker uncluttered — once you're on any equipment page, "
    "the sidebar (with Home, Guide, Project, FMEA, Reliability) is back."
)

flow_row("2 · Work through these sections, in order", [
    ("📋", "Current Settings"),
    ("📖", "Theory"),
    ("🧪", "Simulate & Test"),
    ("🔧", "Commissioning"),
    ("⚡", "Fault Analysis*"),
    ("✅", "Approval"),
])

flow_row("3 · Wrap up", [
    ("📊", "Project page"),
    ("💾", "Save / Export"),
])

st.caption("*Fault Analysis is a separate section only on generator and transformer pages — on motor pages it's folded into Simulate & Test.")

st.divider()

card1, card2, card3 = st.columns(3)
with card1:
    with st.container(border=True):
        st.markdown("#### 📋 Current Settings")
        st.write(
            "Every applied setting, editable in place. 🟢 clears its margin, 🟠 needs a second "
            "look, ⚪ is informational only. ✓/⚠ near the top shows how verified this preset is."
        )
with card2:
    with st.container(border=True):
        st.markdown("#### 📖 Theory")
        st.write("How the protection scheme works, with the protection-zone diagram.")
with card3:
    with st.container(border=True):
        st.markdown("#### 🧪 Simulate & Test")
        st.write(
            "Test a current/fault scenario against the real trip logic and watch the "
            "characteristic curve live, then log real test points on that same curve."
        )

card4, card5, card6 = st.columns(3)
with card4:
    with st.container(border=True):
        st.markdown("#### 🔧 Commissioning")
        st.write("The exact secondary Amps to inject at the test set for a target result.")
with card5:
    with st.container(border=True):
        st.markdown("#### ⚡ Fault Analysis")
        st.write("Checks the CTs against a real fault current, with a step-by-step clearing simulation.")
with card6:
    with st.container(border=True):
        st.markdown("#### ✅ Approval")
        st.write("Document control, the relay-ready settings sheet, and a certified PDF audit report.")

st.divider()

st.info(
    "Every recommendation is a rule-of-thumb starting point, not a substitute for a real "
    "coordination study — always confirm against the approved study, relay manual, and site "
    "test procedure before applying settings in service."
)
st.warning(
    "If a recommendation looks extreme (e.g. a bias floor in the hundreds of percent), it's "
    "almost always an *input* that's wrong — a CT ratio, tap, or connection type — not that the "
    "setting genuinely needs to be that high. Check the inputs first."
)

with st.expander("Notes on a few equipment-specific differences"):
    st.markdown(
        """
- **Wiring & Convention** (Restraint Standard, CT Polarity) is at the top of the **Simulate & Test** section for the generator and transformer pages, not Current Settings — it only affects that evaluation.
- **Motor pages** don't have a separate Fault Current Analysis section. Their fault-clearing simulation lives inside **Simulate & Test** instead, and skips the current waveform (no real X/R data exists for a motor short-circuit contribution).
- **Pin Current Settings** (sidebar checkbox on every equipment page) keeps Current Settings visible above whichever section you're viewing, instead of it being just another section in the list — off by default.
- **Custom Relay Types** works the same way as the plant's own pages, but lets you add and switch between any number of relay definitions from its sidebar. Standard IEC/IEEE time-current curves and a self-balancing differential are offered — percentage-restrained (dual-slope) differential protection isn't, since that needs a restraint-current structure specific to the equipment it's protecting.
"""
    )
