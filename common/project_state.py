"""
Project save/load layer.

Each equipment page already loads its settings from a PRESETS dict shaped
like {"mva": ..., "ct_hv": ..., "tap_hv": ..., "bias": ..., ...} and reads
values back out via p_data["mva"] etc. That shape is reused here: every
equipment page's *current* live settings are mirrored into
st.session_state["project_equipment"][equipment_key] on every rerun (via
record_equipment_settings), using the exact same key names that page's own
PRESETS entries use. Restoring is then just injecting that same dict back
into the page's own PRESETS list as a selectable "From Project" preset -
no change to a page's own widget keys or restore logic is needed, since
selecting that preset flows through the exact same p_data["..."] lookups
every other preset already goes through.

A "Project" is therefore just: a name, a free-text commissioning-notes
field, and this per-equipment dict of live settings - exported/imported as
one JSON file, the same pattern the Motor page already used for its own
single-equipment settings file, just bundled across all equipment.
"""
import streamlit as st

EQUIPMENT_LABELS = {
    "generator": "Generator (87G)",
    "exct": "Excitation Transformer",
    "gsut": "Generator Step-Up Transformer",
    "overall": "Overall GSUT-GEN",
    "aux": "Auxiliary Transformer",
    "motor": "ID Fan Motor",
}

RESTORED_PRESET_LABEL = "📁 Restored from Project"


def _project():
    if "project_equipment" not in st.session_state:
        st.session_state["project_equipment"] = {}
    if "project_name" not in st.session_state:
        st.session_state["project_name"] = "Untitled Project"
    if "project_notes" not in st.session_state:
        st.session_state["project_notes"] = ""
    return st.session_state


def record_equipment_settings(equipment_key, settings: dict):
    """Call once per script run, after an equipment page has computed its
    current settings, with a dict shaped exactly like that page's own
    PRESETS entries. Keeps the project's copy live without needing an
    explicit "save" action - matches how the rest of each page already
    re-derives its state every rerun."""
    proj = _project()
    proj["project_equipment"][equipment_key] = dict(settings)


def get_restorable_preset(equipment_key):
    """Returns the recorded settings dict for this equipment if the current
    project has one, else None."""
    return _project()["project_equipment"].get(equipment_key)


def with_restored_preset(presets_dict, equipment_key):
    """Returns a NEW presets dict with a "From Project" entry prepended if
    the current project has saved settings for this equipment - callers
    just use list(...) on the result for their selectbox options, same as
    they already do with their plain PRESETS dict."""
    restored = get_restorable_preset(equipment_key)
    if restored is None:
        return presets_dict
    merged = {RESTORED_PRESET_LABEL: restored}
    merged.update(presets_dict)
    return merged


def project_summary():
    """One-line summaries per equipment for the Project page's overview
    table - deliberately tolerant of missing keys, since a page's PRESETS
    shape could still evolve."""
    proj = _project()
    rows = []
    for key, label in EQUIPMENT_LABELS.items():
        data = proj["project_equipment"].get(key)
        if data is None:
            rows.append({"Equipment": label, "Status": "Not yet configured", "Summary": "—"})
            continue
        mva = data.get("mva")
        summary = f"{mva:g} MVA" if isinstance(mva, (int, float)) else "Configured"
        if key == "motor" and "motor_fla" in data:
            summary = f"FLA {data['motor_fla']:g} A"
        rows.append({"Equipment": label, "Status": "Configured", "Summary": summary})
    return rows
