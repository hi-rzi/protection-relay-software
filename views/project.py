import datetime
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common.project_state import EQUIPMENT_LABELS, project_summary, differential_zone_coordination
from common.theme import flow_row
from engines.motor import MotorTimeOvercurrentRelay
from engines.motor_869 import Motor869Relay

st.title("Project")
st.caption(
    "Bundle settings across Generator, all Transformer relays, and Motor into one named "
    "project you can save and reload later — instead of exporting each equipment's settings "
    "one at a time."
)

with st.expander("📍 How to use this page", expanded=False):
    flow_row("Build a project this session", [
        ("⚡🔌🌀", "Visit equipment pages"),
        ("📊", "Come here"),
        ("🔍", "Review status"),
        ("💾", "Save Project (.json)"),
    ])
    flow_row("Reload a saved project later", [
        ("📂", "Load Project (.json)"),
        ("📊", "Project page"),
        ("🔁", "Revisit each equipment page"),
        ("✅", "Pick \"Restored from Project\""),
    ])
    st.caption(
        "This page only bundles settings already configured in this browser session — it "
        "doesn't reach into equipment pages you haven't opened yet."
    )
    g1, g2, g3 = st.columns(3)
    with g1:
        with st.container(border=True):
            st.markdown("#### 🔍 Equipment Status")
            st.write("A rule-of-thumb health check per equipment — not a coordination study or an approval.")
    with g2:
        with st.container(border=True):
            st.markdown("#### ⚡ Coordination Check")
            st.write("Shared-CT consistency and backup differential zone coverage across Generator, GSUT, and Overall.")
    with g3:
        with st.container(border=True):
            st.markdown("#### 📈 Motor Curves")
            st.write("Overlays every visited motor's trip curve on one chart, in absolute primary Amps.")

st.info(
    "Visit each equipment page at least once (with the settings you want to keep) before "
    "saving the project — this page only bundles up what's already been configured in this "
    "session. After loading a saved project, revisit each equipment page and pick "
    "\"📁 Restored from Project\" from its Load Standard Profile list to apply it there."
)

# Handled before any widget bound to "project_name"/"project_notes" is created below -
# Streamlit forbids writing to st.session_state[key] once a widget with that key has
# already been instantiated in this script run, so an uploaded file must be processed
# (and its session_state writes made) up here, not further down the page.
st.markdown("### Load Project")
uploaded_project = st.file_uploader("Load a saved project (.json)", type=["json"], key="project_upload")
if uploaded_project is not None:
    file_hash = hash(uploaded_project.getvalue())
    if st.session_state.get("project_loaded_file_hash") != file_hash:
        try:
            payload = json.loads(uploaded_project.getvalue().decode("utf-8"))
            if payload.get("format") != "Electrical Equipment Protection Suite project":
                raise ValueError("This does not look like a project file exported from this app.")
            equipment = payload.get("equipment")
            if not isinstance(equipment, dict):
                raise ValueError("The file does not contain an equipment settings section.")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            st.error(f"Could not load project file: {exc}")
            st.session_state["project_loaded_file_hash"] = file_hash
        else:
            st.session_state["project_equipment"] = equipment
            st.session_state["project_name"] = payload.get("project_name", "Untitled Project")
            st.session_state["project_notes"] = payload.get("notes", "")
            st.session_state["project_loaded_file_hash"] = file_hash
            st.rerun()
st.caption(
    "Loading a project only restores settings into this Project page's memory - each "
    "equipment page still needs to be opened once and set to \"📁 Restored from Project\" to "
    "actually apply those settings there."
)

if "project_name" not in st.session_state:
    st.session_state["project_name"] = "Untitled Project"
if "project_notes" not in st.session_state:
    st.session_state["project_notes"] = ""

st.markdown("### Project Details")
project_name = st.text_input("Project Name", key="project_name")
commissioning_notes = st.text_area(
    "Commissioning Notes", key="project_notes",
    help="Free-text notes for this project - test dates, site conditions, outstanding items, etc. "
         "Saved and reloaded along with the equipment settings."
)

st.markdown("### Equipment Status")
st.caption(
    "Health is a rule-of-thumb signal only (reusing each page's own suggested-settings "
    "math) - it is not a coordination study or an approval. Revisit an equipment page for "
    "the full picture behind any ⚠️ Review flag."
)
st.dataframe(pd.DataFrame(project_summary()), use_container_width=True, hide_index=True)

st.markdown("### Protection Zone Coordination Check")
st.caption(
    "Checks the Generator, GSUT, and Overall GSUT-GEN pages against each other — not a full "
    "grading/coordination study, just (1) CT ratios that the Overall relay's own settings "
    "document confirms are the SAME physical CT feeding two relays at once, and (2) which "
    "equipment has a documented backup differential zone. Visit the Generator, GSUT, and "
    "Overall pages at least once in this session for this section to populate."
)
shared_ct_checks, coverage_rows = differential_zone_coordination()
if shared_ct_checks:
    st.markdown("**Shared CT consistency**")
    st.dataframe(pd.DataFrame(shared_ct_checks), use_container_width=True, hide_index=True)
else:
    st.caption("Visit the Generator, GSUT, and Overall GSUT-GEN pages to populate this check.")
st.markdown("**Backup differential zone coverage** (per Transformer Diff Setting - Overall GSUT-GEN.pdf, Section 5.10)")
st.dataframe(pd.DataFrame(coverage_rows), use_container_width=True, hide_index=True)

st.markdown("### Motor Protection Coordination Curves")
st.caption(
    "Overlays each motor's time-overcurrent curve(s) on one chart, in absolute primary Amps, "
    "so curves from motors with different FLA/CT ratios can still be compared directly. These "
    "are parallel loads on the same bus, not a primary/backup series pair, so there's no strict "
    "coordination-time-interval requirement between different motors — treat this as a "
    "settings-consistency comparison. The one genuine same-zone pair is on the Primary Air Fan "
    "itself: its SR469 and IFC66KD2A are two independent relays protecting the SAME motor on "
    "the SAME CT, so those two curves are worth checking for sensible margin between them. "
    "Visit each motor page at least once in this session to populate its curve(s) here."
)

_proj_equipment = st.session_state.get("project_equipment", {})
_curve_defs = []

_id_fan_data = _proj_equipment.get("motor")
if _id_fan_data and all(_id_fan_data.get(k) is not None for k in ("ct_ratio", "ct_sec", "tap_51", "time_dial")):
    _r = MotorTimeOvercurrentRelay(
        ct_ratio=_id_fan_data["ct_ratio"], ct_secondary_rating=_id_fan_data["ct_sec"],
        tap_51=1.0, time_dial=_id_fan_data["time_dial"], pickup_50a=1e9, dropout_50b=1e9,
    )
    _m = np.linspace(1.01, 20.0, 200)
    _x = _m * _id_fan_data["tap_51"] * _r.effective_ratio
    _y = [_r.calculate_51_trip_time(mm) for mm in _m]
    _curve_defs.append(("ID Fan — IFC66KD2A 51", _x, _y))

for _fan_key, _fan_label in [("pa_fan", "Primary Air Fan"), ("fd_fan", "Forced Draft Fan")]:
    _data = _proj_equipment.get(_fan_key)
    if _data and all(_data.get(k) is not None for k in ("motor_fla", "curve_multiplier")):
        _r869 = Motor869Relay(
            ct_ratio=1.0, ct_secondary_rating=1.0, motor_fla=1.0,
            overload_pickup_pct=115.0, curve_multiplier=_data["curve_multiplier"], inst_pickup_multiple_of_ct=1.0,
        )
        _m = np.linspace(1.01, 8.0, 200)
        _x = _m * _data["motor_fla"]
        _y = [_r869.calculate_overload_trip_time(mm) for mm in _m]
        _curve_defs.append((f"{_fan_label} — SR469 Overload (51)", _x, _y))
    if _data and all(_data.get(k) is not None for k in ("ifc_tap_51", "ifc_time_dial", "ct_ratio", "ct_sec")):
        _r_ifc = MotorTimeOvercurrentRelay(
            ct_ratio=_data["ct_ratio"], ct_secondary_rating=_data["ct_sec"],
            tap_51=1.0, time_dial=_data["ifc_time_dial"], pickup_50a=1e9, dropout_50b=1e9,
        )
        _m = np.linspace(1.01, 20.0, 200)
        _x = _m * _data["ifc_tap_51"] * _r_ifc.effective_ratio
        _y = [_r_ifc.calculate_51_trip_time(mm) for mm in _m]
        _curve_defs.append((f"{_fan_label} — IFC66KD2A 51", _x, _y))

if len(_curve_defs) < 2:
    st.info("Visit at least 2 of the motor pages (Induced Draft Fan, Primary Air Fan, Forced Draft Fan) this session to populate this comparison.")
else:
    _curve_labels = [c[0] for c in _curve_defs]
    _selected_curves = st.multiselect("Curves to compare", _curve_labels, default=_curve_labels, key="project_coord_curve_select")
    _coord_colors = ["#2563EB", "#DC2626", "#16A34A", "#7C3AED", "#F59E0B"]
    _coord_fig = go.Figure()
    for _i, (_label, _x, _y) in enumerate(_curve_defs):
        if _label in _selected_curves:
            _coord_fig.add_trace(go.Scatter(
                x=_x, y=_y, mode="lines", name=_label,
                line=dict(width=3, color=_coord_colors[_i % len(_coord_colors)]),
            ))
    _coord_fig.update_layout(
        xaxis_title="Current (A primary)", yaxis_title="Trip Time (s)",
        xaxis_type="log", yaxis_type="log", template="plotly_white", height=450,
    )
    st.plotly_chart(_coord_fig, use_container_width=True, key="project_coord_curve_fig")

st.markdown("### Save Project")
project_export = {
    "format": "Electrical Equipment Protection Suite project",
    "version": 1,
    "project_name": project_name,
    "notes": commissioning_notes,
    "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
    "equipment": st.session_state.get("project_equipment", {}),
}
configured_count = len(st.session_state.get("project_equipment", {}))
st.download_button(
    label=f"Download Project (.json) — {configured_count} equipment configured",
    data=json.dumps(project_export, indent=2),
    file_name=f"{project_name.replace(' ', '_') or 'Project'}_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.json",
    mime="application/json",
    disabled=configured_count == 0,
    help="Disabled until at least one equipment page has been visited in this session." if configured_count == 0 else None,
)
