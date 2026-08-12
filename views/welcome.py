import streamlit as st

from common.equipment_icons import GENERATOR_SVG, TRANSFORMER_SVG, MOTOR_SVG, CUSTOM_SVG, FMEA_SVG, render_equipment_card
from common.theme import MUTED

# This page is the app's front door - no sidebar nav is useful yet (nothing
# to switch to before a card is clicked), so hide it here only. Scoped to
# this page's own script run, unlike common/theme.py's apply_theme() which
# injects globally from app.py before every page renders.
st.markdown(
    """<style>
    [data-testid="stSidebar"] { display: none; }
    [data-testid="stSidebarCollapsedControl"] { display: none; }
    </style>""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""<div style="text-align:center; padding: 3rem 1rem 1.5rem 1rem;">
        <div style="font-size:3rem; line-height:1;">⚡</div>
        <h1 style="margin-bottom:0.25rem;">Electrical Equipment Protection Suite</h1>
        <p style="font-size:1.1rem; color:{MUTED}; max-width:640px; margin:0.5rem auto 0 auto;">
            Protection settings calculation, commissioning-injection assistance, and settings
            verification for generator, transformer, and motor protection relays.
        </p>
    </div>""",
    unsafe_allow_html=True,
)

# Generator/Custom/FMEA are each a single page, so their card links straight
# there. Transformer/Motor cover several relay types apiece (4 and 3 pages)
# - their card lands on Home, where each of those is its own card, rather
# than guessing which one the user wants.
v1, v2, v3 = st.columns(3)
with v1:
    render_equipment_card(GENERATOR_SVG, "views/generator.py", "Generator", "Differential protection for the stator zone (87G)", "wcard_generator")
with v2:
    render_equipment_card(TRANSFORMER_SVG, "views/home.py", "Transformer", "Excitation, GSUT, Overall, and Auxiliary differential protection", "wcard_transformer")
with v3:
    render_equipment_card(MOTOR_SVG, "views/home.py", "Motor", "Induced Draft, Primary Air, and Forced Draft fan motor protection", "wcard_motor")

v4, v5 = st.columns(2)
with v4:
    render_equipment_card(CUSTOM_SVG, "views/custom_relays.py", "Custom Relay Types", "Model any other relay — standard IEC/IEEE curves, self-balancing differential, unbalance", "wcard_custom")
with v5:
    render_equipment_card(FMEA_SVG, "views/fmea.py", "FMEA", "Failure Mode and Effects Analysis for the numerical/microprocessor-based relays modeled in this app", "wcard_fmea")

st.markdown(
    f"""<div style="text-align:center; margin-top:1.5rem; color:{MUTED}; font-size:0.9rem;">
        New here? The Guide page, once inside the app, walks through the recommended workflow.
    </div>""",
    unsafe_allow_html=True,
)
