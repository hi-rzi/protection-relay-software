import streamlit as st

from common.motor_fan_page import render_fan_motor_page

st.title("Forced Draft Fan Motor Protection")
st.caption(
    "6.9kV Forced Draft Fan — this page models the Multilin SR469 static Motor Protection "
    "Relay and the GE HFC23C1A self-balancing differential (87M). Its settings document follows "
    "the same template as the Primary Air Fan's, which documents a separate discrete 50/50/51 "
    "electromechanical relay in addition to the SR469 — not confirmed or modeled for this motor "
    "specifically yet."
)

render_fan_motor_page("Forced Draft (FD) Fan")
