import streamlit as st

from common.equipment_icons import GENERATOR_SVG, TRANSFORMER_SVG, MOTOR_SVG, CUSTOM_SVG, FMEA_SVG, render_equipment_card
from common.theme import MUTED

# This is the app's equipment picker as well as its front door - no sidebar
# nav is useful here (every destination is a card on this page already), so
# hidden here only. Scoped to this page's own script run, unlike
# common/theme.py's apply_theme() which injects globally from app.py before
# every page renders. Reachable from any other page via the sidebar's "Home"
# link (registered as this same file in app.py).
st.markdown(
    """<style>
    [data-testid="stSidebar"] { display: none; }
    [data-testid="stSidebarCollapsedControl"] { display: none; }
    [data-testid="stMainBlockContainer"] { padding-top: 1.5rem; }
    </style>""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""<div style="text-align:center; padding: 0.5rem 1rem 1rem 1rem;">
        <div style="font-size:3rem; line-height:1;">⚡</div>
        <h1 style="margin-bottom:0.25rem;">Electrical Equipment Protection Suite</h1>
        <p style="font-size:1.1rem; color:{MUTED}; max-width:640px; margin:0.5rem auto 0 auto;">
            Protection settings calculation, commissioning-injection assistance, and settings
            verification for generator, transformer, and motor protection relays.
        </p>
    </div>""",
    unsafe_allow_html=True,
)

# Quick links to the two plant-wide pages that aren't equipment - no sidebar
# on this page to reach them from otherwise.
qcol1, qcol2, qcol3 = st.columns([1, 1, 1])
with qcol2:
    gcol, pcol = st.columns(2)
    with gcol:
        st.page_link("views/guide.py", label="📖 Guide", use_container_width=True)
    with pcol:
        st.page_link("views/project.py", label="📁 Project", use_container_width=True)

st.markdown("<div style='margin-top:1.5rem;'></div>", unsafe_allow_html=True)

# Keys must start with "card_" - common/theme.py's whole-card-clickable
# overlay CSS matches on `[class*="st-key-card_"]` specifically (that's also
# what gives every equipment card its background/border/hover glow).
st.subheader("⚡ Generator")
render_equipment_card(
    GENERATOR_SVG, "views/generator.py", "Generator (87G)",
    "GE G60 numerical dual-breakpoint characteristic, GE CFD22B4A legacy product-restraint characteristic",
    "card_generator",
)

st.subheader("🔌 Transformer")
t1, t2, t3, t4 = st.columns(4)
with t1:
    render_equipment_card(TRANSFORMER_SVG, "views/transformer_exct.py", "Excitation Transformer", "EXCT differential protection", "card_exct")
with t2:
    render_equipment_card(TRANSFORMER_SVG, "views/transformer_gsut.py", "Generator Step-Up Transformer", "GSUT differential protection", "card_gsut")
with t3:
    render_equipment_card(TRANSFORMER_SVG, "views/transformer_overall.py", "Overall GSUT-GEN", "Backup, 3-winding differential", "card_overall")
with t4:
    render_equipment_card(TRANSFORMER_SVG, "views/transformer_aux.py", "Auxiliary Transformer", "Auxiliary differential protection", "card_aux")

st.subheader("🌀 Motor")
m1, m2, m3 = st.columns(3)
with m1:
    render_equipment_card(
        MOTOR_SVG, "views/motor_idfan.py", "Induced Draft Fan",
        "50/50/51 time-overcurrent, GE 869 microprocessor MPR", "card_idfan",
    )
with m2:
    render_equipment_card(
        MOTOR_SVG, "views/motor_pa_fan.py", "Primary Air Fan",
        "Multilin SR469 static MPR, plus a separate discrete GE IFC66KD2A 50/50/51", "card_pafan",
    )
with m3:
    render_equipment_card(
        MOTOR_SVG, "views/motor_fd_fan.py", "Forced Draft Fan",
        "Multilin SR469 static MPR", "card_fdfan",
    )

v4, v5 = st.columns(2)
with v4:
    st.subheader("🧩 Custom")
    render_equipment_card(CUSTOM_SVG, "views/custom_relays.py", "Custom Relay Types", "Model any other relay — standard IEC/IEEE curves, self-balancing differential, unbalance", "card_custom")
with v5:
    st.subheader("📋 Analysis")
    render_equipment_card(FMEA_SVG, "views/fmea.py", "FMEA", "Failure Mode and Effects Analysis for the numerical/microprocessor-based relays modeled in this app", "card_fmea")

st.markdown(
    f"""<div style="text-align:center; margin-top:1.5rem; color:{MUTED}; font-size:0.9rem;">
        New here? The 📖 Guide link above walks through the recommended workflow.
    </div>""",
    unsafe_allow_html=True,
)
