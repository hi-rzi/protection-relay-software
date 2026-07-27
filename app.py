import streamlit as st

st.set_page_config(page_title="Electrical Equipment Protection Suite", layout="wide")

pg = st.navigation({
    "": [st.Page("views/home.py", title="Home", icon="🏠", default=True)],
    "Generator": [st.Page("views/generator.py", title="Generator (87G)", icon="⚡")],
    "Transformer": [
        st.Page("views/transformer_exct.py", title="Excitation Transformer", icon="🔌"),
        st.Page("views/transformer_gsut.py", title="Generator Step-Up Transformer", icon="🔌"),
        st.Page("views/transformer_overall.py", title="Overall GSUT-GEN", icon="🔌"),
        st.Page("views/transformer_aux.py", title="Auxiliary Transformer", icon="🔌"),
    ],
    "Motor": [st.Page("views/motor_idfan.py", title="ID Fan", icon="🌀")],
})
pg.run()
