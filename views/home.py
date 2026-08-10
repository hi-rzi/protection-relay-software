import streamlit as st

st.title("Electrical Equipment Protection Suite")
st.caption("Protection settings calculation, commissioning-injection assistance, and settings verification for generator, transformer, and motor protection relays.")

st.markdown(
    "This app helps engineers work through protection relay settings for generator, transformer, "
    "and motor equipment — settings checks, commissioning-injection calculations, and trip-curve "
    "verification, all in one place. New here? See the **Guide** page in the sidebar."
)

st.markdown("### Available Equipment")
st.caption("Click a card to open that equipment's settings and tools.")


def equipment_card(page_path, title, subtitle, icon, key):
    with st.container(border=True, key=key):
        st.page_link(page_path, label=f"{icon}  **{title}**", use_container_width=True)
        st.caption(subtitle)


st.subheader("⚡ Generator")
equipment_card(
    "views/generator.py", "Generator (87G)",
    "GE G60 numerical dual-breakpoint characteristic, GE CFD22B4A legacy product-restraint characteristic",
    "⚡", "card_generator",
)

st.subheader("🔌 Transformer")
t1, t2, t3, t4 = st.columns(4)
with t1:
    equipment_card("views/transformer_exct.py", "Excitation Transformer", "EXCT differential protection", "🔌", "card_exct")
with t2:
    equipment_card("views/transformer_gsut.py", "Generator Step-Up Transformer", "GSUT differential protection", "🔌", "card_gsut")
with t3:
    equipment_card("views/transformer_overall.py", "Overall GSUT-GEN", "Backup, 3-winding differential", "🔌", "card_overall")
with t4:
    equipment_card("views/transformer_aux.py", "Auxiliary Transformer", "Auxiliary differential protection", "🔌", "card_aux")

st.subheader("🌀 Motor")
m1, m2, m3 = st.columns(3)
with m1:
    equipment_card(
        "views/motor_idfan.py", "Induced Draft Fan",
        "50/50/51 time-overcurrent, GE 869 microprocessor MPR", "🌀", "card_idfan",
    )
with m2:
    equipment_card(
        "views/motor_pa_fan.py", "Primary Air Fan",
        "Multilin SR469 static MPR, plus a separate discrete GE IFC66KD2A 50/50/51", "🌀", "card_pafan",
    )
with m3:
    equipment_card(
        "views/motor_fd_fan.py", "Forced Draft Fan",
        "Multilin SR469 static MPR", "🌀", "card_fdfan",
    )
