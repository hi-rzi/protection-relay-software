import streamlit as st

from common.motor_fan_page import render_fan_motor_page

st.title("Primary Air Fan Motor Protection")
st.caption(
    "6.9kV Primary Air Fan — this page models the Multilin SR469 static Motor Protection Relay, "
    "the separate discrete 50/50/51 electromechanical relay (IFC66KD2A) with its backup "
    "instantaneous relay (HFC22B2A), and the GE HFC23C1A self-balancing differential (87M)."
)

render_fan_motor_page("Primary Air (PA) Fan")
