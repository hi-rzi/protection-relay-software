"""
Shared dark-dashboard theme, injected once from app.py before st.navigation runs.

This is one <style> block via st.markdown(unsafe_allow_html=True) - it lands in the
same HTML document every page renders into (not an iframe), so it applies globally
for the rest of the script run regardless of which page is active. Colors mirror
.streamlit/config.toml's [theme] section (that file sets Streamlit's own base
widget palette; this file layers card/nav-specific styling Streamlit's theme system
doesn't cover on its own).

Streamlit's internal data-testid / class names shift between releases - if a
selector below stops matching after a Streamlit upgrade, re-inspect the live DOM
rather than assuming the old selector is still correct.
"""

import streamlit as st

ACCENT = "#2dd4a7"
BG = "#0d1117"
CARD_BG = "#161b22"
BORDER = "#21262d"
TEXT = "#e6edf3"
NEGATIVE = "#f85149"


def apply_theme():
    st.markdown(
        f"""<style>
        [data-testid="stSidebar"] {{
            background-color: {BG};
            border-right: 1px solid {BORDER};
        }}
        [data-testid="stSidebarNav"] a {{
            border-radius: 999px;
            margin: 2px 8px;
            padding: 0.4rem 0.9rem;
        }}
        [data-testid="stSidebarNav"] a[aria-current="page"] {{
            background-color: rgba(45, 212, 167, 0.15);
            color: {ACCENT} !important;
            font-weight: 600;
        }}
        [data-testid="stSidebar"] .stRadio [role="radiogroup"] label {{
            border-radius: 999px;
            padding: 0.35rem 0.8rem;
            margin-bottom: 2px;
        }}
        [data-testid="stSidebar"] .stRadio [role="radiogroup"] label:has(input:checked) {{
            background-color: rgba(45, 212, 167, 0.15);
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            border-radius: 12px;
            border: 1px solid {BORDER};
            background-color: {CARD_BG};
        }}
        div[class*="st-key-card_"] {{
            transition: border-color 0.15s ease;
        }}
        div[class*="st-key-card_"]:hover {{
            border-color: {ACCENT};
        }}
        .stButton > button[kind="primary"] {{
            background-color: {ACCENT};
            color: {BG};
            border: none;
            border-radius: 8px;
            font-weight: 600;
        }}
        .stButton > button[kind="primary"]:hover {{
            background-color: {ACCENT};
            opacity: 0.85;
        }}
        .positive {{ color: {ACCENT}; }}
        .negative {{ color: {NEGATIVE}; }}
        [data-testid="stMetric"] {{
            background-color: {CARD_BG};
            border: 1px solid {BORDER};
            border-radius: 12px;
            padding: 0.75rem 1rem;
        }}
        </style>""",
        unsafe_allow_html=True,
    )
