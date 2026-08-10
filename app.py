import streamlit as st

from common.theme import apply_theme

st.set_page_config(page_title="Electrical Equipment Protection Suite", layout="wide")
apply_theme()

pg = st.navigation({
    "": [
        st.Page("views/home.py", title="Home", default=True),
        st.Page("views/guide.py", title="Guide"),
        st.Page("views/project.py", title="Project"),
        st.Page("views/fmea.py", title="FMEA"),
    ],
    "Generator": [st.Page("views/generator.py", title="Generator (87G)", visibility="hidden")],
    "Transformer": [
        st.Page("views/transformer_exct.py", title="Excitation Transformer", visibility="hidden"),
        st.Page("views/transformer_gsut.py", title="Generator Step-Up Transformer", visibility="hidden"),
        st.Page("views/transformer_overall.py", title="Overall GSUT-GEN", visibility="hidden"),
        st.Page("views/transformer_aux.py", title="Auxiliary Transformer", visibility="hidden"),
    ],
    "Motor": [
        st.Page("views/motor_idfan.py", title="Induced Draft Fan", visibility="hidden"),
        st.Page("views/motor_pa_fan.py", title="Primary Air Fan", visibility="hidden"),
        st.Page("views/motor_fd_fan.py", title="Forced Draft Fan", visibility="hidden"),
    ],
})
pg.run()
