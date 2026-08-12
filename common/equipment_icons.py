"""
Shared line-art SVG icons for the equipment categories (Generator, Transformer,
Motor, Custom) - used by both views/welcome.py (decorative, first-entry hero)
and views/home.py (clickable equipment cards), so the two pages share one
visual identity for "what this app protects" instead of drifting apart.

Colors are read from common.theme so these follow the app's palette
automatically if it's ever retuned again.
"""

import streamlit as st

from common.theme import ACCENT, TEXT

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

# A hexagon (build-your-own-shape) with a plus sign - "assemble a relay from
# parts" reads more clearly than a literal puzzle-piece at this size.
CUSTOM_SVG = """
<svg viewBox="0 0 120 120" width="72" height="72">
    <polygon points="60,16 96,38 96,82 60,104 24,82 24,38"
             fill="none" stroke="{accent}" stroke-width="4" stroke-linejoin="round"/>
    <line x1="60" y1="42" x2="60" y2="78" stroke="{text}" stroke-width="5" stroke-linecap="round"/>
    <line x1="42" y1="60" x2="78" y2="60" stroke="{text}" stroke-width="5" stroke-linecap="round"/>
</svg>
""".format(accent=ACCENT, text=TEXT)

# Clipboard with a checkmark - failure-mode analysis / checklist, distinct
# from the equipment icons above.
FMEA_SVG = """
<svg viewBox="0 0 120 120" width="72" height="72">
    <rect x="28" y="20" width="64" height="86" rx="8" fill="none" stroke="{accent}" stroke-width="4"/>
    <rect x="44" y="14" width="32" height="14" rx="4" fill="{text}"/>
    <path d="M42 62 L54 74 L80 46" fill="none" stroke="{accent}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
    <line x1="42" y1="88" x2="78" y2="88" stroke="{text}" stroke-width="4" stroke-linecap="round"/>
</svg>
""".format(accent=ACCENT, text=TEXT)


def render_equipment_card(svg, page_path, title, subtitle, key):
    """One clickable equipment tile: icon, title, subtitle, the whole card
    a link to page_path. Shared by views/welcome.py and views/home.py so
    both pages present equipment the same way.

    Relies on common/theme.py's global CSS: any st.container(border=True,
    key="...") automatically gets the card background/radius/shadow, and the
    stretched-link overlay rule (targeting any st-key-* container holding a
    page_link) is what makes the whole card clickable rather than just the
    link text.
    """
    with st.container(border=True, key=key):
        st.markdown(
            f'<div style="text-align:center; padding-top:0.25rem;">{svg}</div>',
            unsafe_allow_html=True,
        )
        st.page_link(page_path, label=f"**{title}**", use_container_width=True)
        st.caption(subtitle)
