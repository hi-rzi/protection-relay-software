import datetime
import json

import pandas as pd
import streamlit as st

from common.project_state import EQUIPMENT_LABELS, project_summary

st.title("Project")
st.caption(
    "Bundle settings across Generator, all Transformer relays, and Motor into one named "
    "project you can save and reload later — instead of exporting each equipment's settings "
    "one at a time."
)

st.info(
    "Visit each equipment page at least once (with the settings you want to keep) before "
    "saving the project — this page only bundles up what's already been configured in this "
    "session. After loading a saved project, revisit each equipment page and pick "
    "\"📁 Restored from Project\" from its Load Standard Profile list to apply it there."
)

if "project_name" not in st.session_state:
    st.session_state["project_name"] = "Untitled Project"
if "project_notes" not in st.session_state:
    st.session_state["project_notes"] = ""

project_name = st.text_input("Project Name", key="project_name")
commissioning_notes = st.text_area(
    "Commissioning Notes", key="project_notes",
    help="Free-text notes for this project - test dates, site conditions, outstanding items, etc. "
         "Saved and reloaded along with the equipment settings."
)

st.markdown("### Equipment Status")
st.dataframe(pd.DataFrame(project_summary()), use_container_width=True, hide_index=True)

st.markdown("### Save / Load")
col_save, col_load = st.columns(2)

with col_save:
    st.markdown("**Save Project**")
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

with col_load:
    st.markdown("**Load Project**")
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
