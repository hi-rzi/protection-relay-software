import streamlit as st

st.title("Electrical Equipment Protection Suite")
st.caption("Protection settings calculation, commissioning-injection assistance, and settings verification for generator, transformer, and motor protection relays.")

st.markdown(
    "This app helps engineers work through protection relay settings for generator, transformer, "
    "and motor equipment — settings checks, commissioning-injection calculations, and trip-curve "
    "verification, all in one place. New here? See the **Guide** page in the sidebar."
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
