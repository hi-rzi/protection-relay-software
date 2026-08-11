import streamlit as st

st.markdown(
    """<div style="text-align:center; padding: 4rem 1rem 2rem 1rem;">
        <div style="font-size:3rem; line-height:1;">⚡</div>
        <h1 style="margin-bottom:0.25rem;">Electrical Equipment Protection Suite</h1>
        <p style="font-size:1.1rem; color:#8b949e; max-width:640px; margin:0.5rem auto 0 auto;">
            Protection settings calculation, commissioning-injection assistance, and settings
            verification for generator, transformer, and motor protection relays.
        </p>
    </div>""",
    unsafe_allow_html=True,
)

col = st.columns([1, 1, 1])[1]
with col:
    if st.button("Get Started →", type="primary", use_container_width=True):
        st.switch_page("views/home.py")

st.markdown(
    """<div style="text-align:center; margin-top:1.5rem; color:#6e7681; font-size:0.9rem;">
        New here? The Guide page (in the sidebar, once you're inside) walks through the
        recommended workflow.
    </div>""",
    unsafe_allow_html=True,
)
