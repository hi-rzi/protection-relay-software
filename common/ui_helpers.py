import streamlit as st

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
