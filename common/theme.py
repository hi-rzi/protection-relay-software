"""
Shared dark-dashboard theme, injected once from app.py before st.navigation runs.

This is one <style> block via st.markdown(unsafe_allow_html=True) - it lands in the
same HTML document every page renders into (not an iframe), so it applies globally
for the rest of the script run regardless of which page is active. Colors mirror
.streamlit/config.toml's [theme] section (that file sets Streamlit's own base
widget palette; this file layers card/nav-specific styling Streamlit's theme system
doesn't cover on its own).

Palette targets a polished analytics-dashboard look (indigo/violet on near-black,
soft glow on interactive elements) rather than the flat GitHub-dark look this app
started with - deliberately not a literal clone of any one reference product, since
this app has no AI-chat/map features to give that chrome a real function; same
information architecture (sidebar nav, cards, metrics), refreshed color/depth only.

Streamlit's internal data-testid / class names shift between releases - if a
selector below stops matching after a Streamlit upgrade, re-inspect the live DOM
rather than assuming the old selector is still correct.
"""

import streamlit as st

ACCENT = "#7c6cf6"
ACCENT_2 = "#4f9dff"
BG = "#0a0a1a"
CARD_BG = "#15162e"
CARD_BG_HOVER = "#191a35"
BORDER = "#2a2b4d"
TEXT = "#e8e9f5"
MUTED = "#9497c2"
NEGATIVE = "#f85149"
WARNING = "#f0883e"
POSITIVE = "#2dd4a7"


def apply_theme():
    st.markdown(
        f"""<style>
        [data-testid="stAppViewContainer"] {{
            background:
                radial-gradient(1200px 600px at 12% -8%, rgba(124,108,246,0.16), transparent 60%),
                radial-gradient(900px 500px at 100% 0%, rgba(79,157,255,0.10), transparent 55%),
                {BG};
        }}
        [data-testid="stHeader"] {{
            background: rgba(10, 10, 26, 0.0);
        }}
        [data-testid="stSidebar"] {{
            background-color: #0c0c22;
            border-right: 1px solid {BORDER};
        }}
        [data-testid="stSidebarNav"] a {{
            border-radius: 999px;
            margin: 2px 8px;
            padding: 0.4rem 0.9rem;
        }}
        [data-testid="stSidebarNav"] a[aria-current="page"] {{
            background: linear-gradient(90deg, rgba(124,108,246,0.22), rgba(79,157,255,0.12));
            color: {ACCENT} !important;
            font-weight: 600;
        }}
        [data-testid="stSidebar"] .stRadio [role="radiogroup"] label {{
            border-radius: 999px;
            padding: 0.35rem 0.8rem;
            margin-bottom: 2px;
        }}
        [data-testid="stSidebar"] .stRadio [role="radiogroup"] label:has(input:checked) {{
            background: linear-gradient(90deg, rgba(124,108,246,0.22), rgba(79,157,255,0.12));
        }}
        /* Streamlit renders st.container(border=True) as a plain stVerticalBlock with
           its border applied through an unstable, per-instance generated class - there
           is no stable testid/attribute to target every bordered container generically.
           Every container this app wants panel-styled already carries an explicit
           key=... (Home's equipment cards, each equipment page's section-nav panels),
           so that's what's targeted here instead - broader and more reliable than
           trying to chase Streamlit's own internal border styling. */
        div[data-testid="stVerticalBlockBorderWrapper"],
        div[data-testid="stVerticalBlock"][class*="st-key-"] {{
            border-radius: 14px !important;
            border: 1px solid {BORDER} !important;
            background-color: {CARD_BG} !important;
            box-shadow: 0 1px 0 rgba(255,255,255,0.02) inset, 0 6px 20px rgba(0,0,0,0.25);
            padding: 1rem;
        }}
        div[class*="st-key-card_"] {{
            position: relative;
            transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
        }}
        div[class*="st-key-card_"]:hover {{
            border-color: {ACCENT};
            box-shadow: 0 0 0 1px rgba(124,108,246,0.35), 0 10px 28px rgba(124,108,246,0.16);
            transform: translateY(-1px);
        }}
        /* Streamlit puts position:relative on every stElementContainer, which would
           otherwise become the nearest positioned ancestor and trap the stretched-link
           overlay below to just the link's own row instead of the whole card - override
           it back to static (scoped to only link-containing containers inside a card) so
           containing-block resolution walks up to the card itself. */
        div[class*="st-key-card_"] div[data-testid="stElementContainer"]:has(a[data-testid="stPageLink-NavLink"]) {{
            position: static !important;
        }}
        div[class*="st-key-card_"] a[data-testid="stPageLink-NavLink"]::after {{
            content: "";
            position: absolute;
            inset: 0;
            z-index: 1;
            cursor: pointer;
        }}
        /* Section-nav cards (common/ui_helpers.py's card_section_nav) - same
           whole-card-clickable idea as the page_link cards above, but there's
           no real link to stretch (switching sections is a same-page rerun,
           not navigation), so the actual st.button is stretched invisibly
           over the card instead; the icon/label markdown underneath is what
           the user actually sees. */
        div[class*="st-key-card_nav_"] div[data-testid="stElementContainer"]:has(button) {{
            position: static !important;
        }}
        div[class*="st-key-card_nav_"] button {{
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            margin: 0;
            padding: 0;
            opacity: 0;
            cursor: pointer;
            z-index: 2;
        }}
        /* Without this, the icon/label markdown text underneath (painted
           behind the invisible button, but still hit-testable at its own
           pixel positions in some browsers) shows a text-selection cursor,
           and the cursor visibly flickers between pointer/text as the mouse
           crosses those overlapping regions. Force pointer everywhere in
           the card so hovering anywhere on it reads as one clickable
           surface, never a text-select target. */
        div[class*="st-key-card_nav_"],
        div[class*="st-key-card_nav_"] * {{
            cursor: pointer !important;
        }}
        div[class*="st-key-card_nav_"][class*="__active"] {{
            border-color: {ACCENT} !important;
            box-shadow: 0 0 0 2px rgba(124,108,246,0.45), 0 10px 28px rgba(124,108,246,0.20) !important;
        }}
        .stButton > button[kind="primary"] {{
            background: linear-gradient(90deg, {ACCENT}, {ACCENT_2});
            color: #0a0a1a;
            border: none;
            border-radius: 8px;
            font-weight: 700;
            box-shadow: 0 4px 16px rgba(124,108,246,0.35);
        }}
        .stButton > button[kind="primary"]:hover {{
            filter: brightness(1.08);
            box-shadow: 0 6px 20px rgba(124,108,246,0.45);
        }}
        .positive {{ color: {POSITIVE}; }}
        .negative {{ color: {NEGATIVE}; }}
        [data-testid="stMetric"] {{
            background: linear-gradient(180deg, {CARD_BG_HOVER}, {CARD_BG});
            border: 1px solid {BORDER};
            border-radius: 14px;
            padding: 0.9rem 1.1rem;
        }}
        [data-testid="stMetricValue"] {{
            background: linear-gradient(90deg, {TEXT}, {ACCENT_2});
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .poe-flow-row {{
            display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
            margin: 0.5rem 0 1.5rem 0;
        }}
        .poe-step {{
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            min-width: 108px; padding: 0.6rem 0.5rem;
            background-color: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 12px;
            text-align: center;
        }}
        .poe-step .poe-icon {{ font-size: 1.6rem; line-height: 1.2; }}
        .poe-step .poe-label {{ font-size: 0.78rem; font-weight: 600; color: {TEXT}; margin-top: 2px; }}
        .poe-arrow {{ color: {ACCENT}; font-size: 1.3rem; flex-shrink: 0; }}
        .poe-row-title {{
            font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em;
            color: {ACCENT}; font-weight: 700; margin-bottom: 0.4rem;
        }}
        </style>""",
        unsafe_allow_html=True,
    )


_PILL_COLORS = {"accent": ACCENT, "warning": WARNING, "negative": NEGATIVE}


def pill_row(pills):
    """Renders a row of small colored pill badges - pills is a list of
    (color_key, label) tuples, color_key one of "accent"/"warning"/"negative".
    Used for compact Low/Medium/High-style legends instead of a text list."""
    spans = ""
    for color_key, label in pills:
        color = _PILL_COLORS[color_key]
        spans += (
            f'<span style="background:{color}26; color:{color}; padding:3px 12px; '
            f'border-radius:999px; font-size:0.8rem; font-weight:600; margin-right:6px; '
            f'display:inline-block; margin-bottom:4px;">{label}</span>'
        )
    st.markdown(spans, unsafe_allow_html=True)


def flow_row(row_title, steps):
    """Renders one row of the icon-boxes-connected-by-arrows flow diagram used
    on the Guide and Project pages - steps is a list of (icon, label) tuples.
    Relies on the .poe-* classes injected globally by apply_theme(), so any
    page using this must run after apply_theme() has been called (already
    true everywhere, since app.py calls it before st.navigation runs)."""
    boxes = ""
    for i, (icon, label) in enumerate(steps):
        if i > 0:
            boxes += '<div class="poe-arrow">→</div>'
        boxes += f'<div class="poe-step"><div class="poe-icon">{icon}</div><div class="poe-label">{label}</div></div>'
    st.markdown(
        f'<div class="poe-row-title">{row_title}</div><div class="poe-flow-row">{boxes}</div>',
        unsafe_allow_html=True,
    )
