import streamlit as st

st.set_page_config(page_title="Electrical Equipment Protection Suite", layout="wide")

pg = st.navigation({
    "": [st.Page("views/home.py", title="Home", default=True)],
    "Generator": [st.Page("views/generator.py", title="Generator (87G)")],
    "Transformer": [
        st.Page("views/transformer_exct.py", title="Excitation Transformer"),
        st.Page("views/transformer_gsut.py", title="Generator Step-Up Transformer"),
        st.Page("views/transformer_overall.py", title="Overall GSUT-GEN"),
        st.Page("views/transformer_aux.py", title="Auxiliary Transformer"),
    ],
    "Motor": [st.Page("views/motor_idfan.py", title="ID Fan")],
})
pg.run()
