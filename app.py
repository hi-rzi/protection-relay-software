import streamlit as st

st.set_page_config(page_title="Electrical Equipment Protection Suite", layout="wide")

pg = st.navigation({
    "": [
        st.Page("views/home.py", title="Home", default=True),
        st.Page("views/guide.py", title="Guide"),
        st.Page("views/project.py", title="Project"),
    ],
    "Generator": [st.Page("views/generator.py", title="Generator (87G)")],
    "Transformer": [
        st.Page("views/transformer_exct.py", title="Excitation Transformer"),
        st.Page("views/transformer_gsut.py", title="Generator Step-Up Transformer"),
        st.Page("views/transformer_overall.py", title="Overall GSUT-GEN"),
        st.Page("views/transformer_aux.py", title="Auxiliary Transformer"),
    ],
    "Motor": [
        st.Page("views/motor_idfan.py", title="Induced Draft Fan"),
        st.Page("views/motor_pa_fan.py", title="Primary Air Fan"),
        st.Page("views/motor_fd_fan.py", title="Forced Draft Fan"),
    ],
})
pg.run()
