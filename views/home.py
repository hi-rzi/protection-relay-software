import streamlit as st

from common.equipment_icons import GENERATOR_SVG, TRANSFORMER_SVG, MOTOR_SVG, CUSTOM_SVG, render_equipment_card

st.title("Electrical Equipment Protection Suite")
st.caption("Protection settings calculation, commissioning-injection assistance, and settings verification for generator, transformer, and motor protection relays.")

st.markdown(
    "This app helps engineers work through protection relay settings for generator, transformer, "
    "and motor equipment — settings checks, commissioning-injection calculations, and trip-curve "
    "verification, all in one place. New here? See the **Guide** page in the sidebar."
)

st.markdown("### Available Equipment")
st.caption("Click a card to open that equipment's settings and tools.")

st.subheader("⚡ Generator")
render_equipment_card(
    GENERATOR_SVG, "views/generator.py", "Generator (87G)",
    "GE G60 numerical dual-breakpoint characteristic, GE CFD22B4A legacy product-restraint characteristic",
    "card_generator",
)

st.subheader("🔌 Transformer")
t1, t2, t3, t4 = st.columns(4)
with t1:
    render_equipment_card(TRANSFORMER_SVG, "views/transformer_exct.py", "Excitation Transformer", "EXCT differential protection", "card_exct")
with t2:
    render_equipment_card(TRANSFORMER_SVG, "views/transformer_gsut.py", "Generator Step-Up Transformer", "GSUT differential protection", "card_gsut")
with t3:
    render_equipment_card(TRANSFORMER_SVG, "views/transformer_overall.py", "Overall GSUT-GEN", "Backup, 3-winding differential", "card_overall")
with t4:
    render_equipment_card(TRANSFORMER_SVG, "views/transformer_aux.py", "Auxiliary Transformer", "Auxiliary differential protection", "card_aux")

st.subheader("🌀 Motor")
m1, m2, m3 = st.columns(3)
with m1:
    render_equipment_card(
        MOTOR_SVG, "views/motor_idfan.py", "Induced Draft Fan",
        "50/50/51 time-overcurrent, GE 869 microprocessor MPR", "card_idfan",
    )
with m2:
    render_equipment_card(
        MOTOR_SVG, "views/motor_pa_fan.py", "Primary Air Fan",
        "Multilin SR469 static MPR, plus a separate discrete GE IFC66KD2A 50/50/51", "card_pafan",
    )
with m3:
    render_equipment_card(
        MOTOR_SVG, "views/motor_fd_fan.py", "Forced Draft Fan",
        "Multilin SR469 static MPR", "card_fdfan",
    )

st.subheader("🧩 Custom")
render_equipment_card(
    CUSTOM_SVG, "views/custom_relays.py", "Custom Relay Types",
    "Model any other relay — standard IEC/IEEE curves, self-balancing differential, unbalance",
    "card_custom",
)
