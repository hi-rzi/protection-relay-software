import streamlit as st

from common.motor_fan_page import render_fan_motor_page

st.title("Primary Air Fan Motor Protection")
st.caption(
    "6.9kV Primary Air Fan — GE Multilin 869 Motor Protection Relay only "
    "(no separate discrete 50/50/51 electromechanical relay on this motor)."
)

render_fan_motor_page("Primary Air (PA) Fan")
