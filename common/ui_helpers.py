import streamlit as st


def sidebar_section_nav(section_names, key_prefix, pin_first=False):
    """Replaces a page's outer/inner st.tabs() with a sidebar-driven section
    switcher, styled as nav pills to match the rest of the app's theme.

    Every section gets its own st.container(key=...) and ALL of them are
    created (and their bodies executed) every rerun, exactly like st.tabs()
    already does under the hood - Streamlit's own tabs run every tab body's
    code every rerun and just CSS-toggle which one is visible. This function
    does the same thing manually: only the DOM visibility is driven by our
    own CSS instead of Streamlit's tab CSS, so any later section (e.g.
    "Simulate & Test") can safely read Python variables/objects built inside
    an earlier section (e.g. "Current Settings") in the same script run,
    same as it could when they were tabs.

    If pin_first, a "Pin Current Settings" sidebar checkbox lets the user
    choose whether section_names[0] stays permanently visible above whichever
    other section is selected (pinned=True), or behaves as just one more
    selectable section like the rest (pinned=False) - both are real, ongoing
    behaviors, not a one-off toggle.

    Returns (selected, containers, pinned_container):
      - selected: the name of the currently sidebar-selected section
      - containers: dict of section name -> st.container to render into,
        replacing `with tab_x:` with `with containers["X"]:`
      - pinned_container: containers[section_names[0]] if pinned is active,
        else None - render it above the selected section's content.
    """
    pinned = False
    if pin_first:
        pinned = st.sidebar.checkbox(
            "Pin Current Settings", value=True, key=f"{key_prefix}_pin",
            help="Keep Current Settings visible above whichever section you're viewing.",
        )

    nav_options = section_names[1:] if (pin_first and pinned) else section_names
    selected = st.sidebar.radio(
        "Section", nav_options, key=f"{key_prefix}_nav", label_visibility="collapsed",
    )

    containers = {name: st.container(key=f"{key_prefix}_c_{i}") for i, name in enumerate(section_names)}

    pinned_container = containers[section_names[0]] if (pin_first and pinned) else None

    hide_rules = []
    for i, name in enumerate(section_names):
        stays_visible = (name == selected) or (pin_first and pinned and name == section_names[0])
        if not stays_visible:
            hide_rules.append(f'div[class*="st-key-{key_prefix}_c_{i}"] {{ display: none; }}')
    if hide_rules:
        st.markdown(f"<style>{''.join(hide_rules)}</style>", unsafe_allow_html=True)

    return selected, containers, pinned_container

# Standard ANSI multi-ratio bushing CT tap sets (10-tap, X1-X5 terminal block
# style). The 600:5 set is well-documented industry-wide; the 2000:5 and
# 3000:5 sets follow the same proportional tap spacing scaled to those CTs'
# max ratio — verify exact intermediate taps against the CT nameplate. The
# taps confirmed directly by the settings docs (the actual "set on" value
# and the max) are exact: 600:5 max/set=600 (EXCT), 2000:5 set=1600 (GSUT/
# Overall HV), 3000:5 max/set=3000 (UAT HV).
MR_CT_TAPS_600_5 = [50, 100, 150, 200, 250, 300, 400, 450, 500, 600]
MR_CT_TAPS_2000_5 = [200, 400, 500, 600, 800, 1000, 1200, 1500, 1600, 2000]
MR_CT_TAPS_3000_5 = [300, 500, 750, 1000, 1250, 1500, 2000, 2400, 2800, 3000]


def render_placeholder(title, caption, note="Coming soon — this relay type is being added next."):
    st.title(title)
    st.caption(caption)
    st.info(note)


# Shared definitions for the fault-current terms used across every Fault
# Current Analysis tab - kept in one place so the wording stays identical
# everywhere it appears, and so future equipment pages read from the same
# glossary instead of re-explaining these terms slightly differently each time.
FAULT_CURRENT_DEFINITIONS = {
    "symmetrical": (
        "The steady-state RMS fault current, with the initial DC offset transient already "
        "decayed away — what the current settles to a few cycles after the fault starts. "
        "This is the value a per-unit source-impedance calculation gives directly."
    ),
    "asymmetrical": (
        "The worst-case RMS fault current INCLUDING the DC offset transient present in the "
        "first cycle(s) after the fault occurs (worst case when the fault happens at a voltage "
        "zero-crossing). Always higher than the symmetrical value — this is the number "
        "protection equipment (CTs, relays, breakers) actually has to survive without "
        "saturating or being damaged, not just the settled-out symmetrical figure."
    ),
    "through": (
        "Fault current that flows THROUGH a piece of equipment's CTs for a fault OUTSIDE its "
        "own protected zone (an external/'through' fault — e.g. a fault on the far side of a "
        "transformer, or fed from the grid into an adjacent zone). A differential relay must "
        "correctly RESTRAIN (not trip) for this current, however large it is — CT saturation "
        "during a severe through-fault is a well-documented cause of relay misoperation, which "
        "is exactly what checking this current against the CT/relay withstand limit guards against."
    ),
}


def fault_term_info(term_key, label=None):
    """A small clickable ⓘ button next to a fault-current metric that reveals
    that term's definition on click (st.popover) - label defaults to the
    term_key itself, title-cased, if not given."""
    display_label = label or term_key.replace("_", " ").title()
    with st.popover(f"ⓘ {display_label}", help=f"Click for the definition of {display_label}"):
        st.markdown(f"**{display_label}**")
        st.write(FAULT_CURRENT_DEFINITIONS[term_key])


def slider_with_exact_input(container, label, min_v, max_v, default, step, key, help_text=None):
    slider_key = f"{key}__slider"
    number_key = f"{key}__number"

    if key not in st.session_state:
        st.session_state[key] = default

    if slider_key not in st.session_state:
        st.session_state[slider_key] = default

    if number_key not in st.session_state:
        st.session_state[number_key] = default

    def _on_slider_change():
        v = st.session_state[slider_key]
        st.session_state[key] = v
        st.session_state[number_key] = v

    def _on_number_change():
        v = st.session_state[number_key]
        v = min(max(v, min_v), max_v)
        st.session_state[key] = v
        st.session_state[slider_key] = v

    col_s, col_n = container.columns([2.4, 1])
    with col_s:
        st.slider(
            label, min_value=min_v, max_value=max_v, step=step,
            key=slider_key, on_change=_on_slider_change, help=help_text
        )
    with col_n:
        st.number_input(
            "Exact", min_value=min_v, max_value=max_v, step=step,
            key=number_key, on_change=_on_number_change, label_visibility="collapsed"
        )

    return st.session_state[key]
