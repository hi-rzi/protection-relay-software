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
        "- Primary Air (PA) Fan and Forced Draft (FD) Fan — GE 869 microprocessor MPR"
    )
