import streamlit as st

from common.theme import ACCENT, CARD_BG, BORDER, TEXT, MUTED

# This page is the app's front door - no sidebar nav is useful yet (nothing
# to switch to before "Get Started"), so hide it here only. Scoped to this
# page's own script run, unlike common/theme.py's apply_theme() which
# injects globally from app.py before every page renders.
st.markdown(
    """<style>
    [data-testid="stSidebar"] { display: none; }
    [data-testid="stSidebarCollapsedControl"] { display: none; }
    </style>""",
    unsafe_allow_html=True,
)

GENERATOR_SVG = """
<svg viewBox="0 0 120 120" width="72" height="72">
    <circle cx="60" cy="60" r="46" fill="none" stroke="{accent}" stroke-width="4"/>
    <path d="M67 22 L42 66 L58 66 L51 98 L80 54 L62 54 Z" fill="{accent}"/>
</svg>
""".format(accent=ACCENT)

TRANSFORMER_SVG = """
<svg viewBox="0 0 120 120" width="72" height="72">
    <line x1="57" y1="22" x2="57" y2="98" stroke="{text}" stroke-width="4"/>
    <line x1="63" y1="22" x2="63" y2="98" stroke="{text}" stroke-width="4"/>
    <circle cx="42" cy="42" r="16" fill="none" stroke="{accent}" stroke-width="4"/>
    <circle cx="42" cy="60" r="16" fill="none" stroke="{accent}" stroke-width="4"/>
    <circle cx="42" cy="78" r="16" fill="none" stroke="{accent}" stroke-width="4"/>
    <circle cx="78" cy="42" r="16" fill="none" stroke="{accent}" stroke-width="4"/>
    <circle cx="78" cy="60" r="16" fill="none" stroke="{accent}" stroke-width="4"/>
    <circle cx="78" cy="78" r="16" fill="none" stroke="{accent}" stroke-width="4"/>
</svg>
""".format(accent=ACCENT, text=TEXT)

MOTOR_SVG = """
<svg viewBox="0 0 120 120" width="72" height="72">
    <circle cx="52" cy="60" r="38" fill="none" stroke="{accent}" stroke-width="4"/>
    <path d="M52 60 L52 30 A30 30 0 0 1 79 47 Z" fill="{accent}" opacity="0.85"/>
    <path d="M52 60 L79 73 A30 30 0 0 1 52 90 Z" fill="{accent}" opacity="0.6"/>
    <path d="M52 60 L25 47 A30 30 0 0 1 25 73 Z" fill="{accent}" opacity="0.4"/>
    <circle cx="52" cy="60" r="8" fill="{text}"/>
    <rect x="90" y="53" width="20" height="14" rx="3" fill="{text}"/>
</svg>
""".format(accent=ACCENT, text=TEXT)


def equipment_visual(svg, title, subtitle):
    st.markdown(
        f"""<div style="
            background-color:{CARD_BG}; border:1px solid {BORDER}; border-radius:14px;
            padding:1.5rem 1rem; text-align:center; height:100%;
        ">
            <div style="margin-bottom:0.75rem;">{svg}</div>
            <div style="font-weight:700; font-size:1.05rem; color:{TEXT};">{title}</div>
            <div style="font-size:0.85rem; color:{MUTED}; margin-top:0.35rem;">{subtitle}</div>
        </div>""",
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

v1, v2, v3 = st.columns(3)
with v1:
    equipment_visual(GENERATOR_SVG, "Generator", "Differential protection for the stator zone (87G)")
with v2:
    equipment_visual(TRANSFORMER_SVG, "Transformer", "Excitation, GSUT, Overall, and Auxiliary differential protection")
with v3:
    equipment_visual(MOTOR_SVG, "Motor", "Induced Draft, Primary Air, and Forced Draft fan motor protection")

st.markdown("<div style='margin-top:2rem;'></div>", unsafe_allow_html=True)

col = st.columns([1, 1, 1])[1]
with col:
    if st.button("Get Started →", type="primary", use_container_width=True):
        st.switch_page("views/home.py")

st.markdown(
    f"""<div style="text-align:center; margin-top:1.5rem; color:{MUTED}; font-size:0.9rem;">
        New here? The Guide page, once inside the app, walks through the recommended workflow.
    </div>""",
    unsafe_allow_html=True,
)
