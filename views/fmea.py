import copy
import datetime
import json
import uuid

import pandas as pd
import streamlit as st

from common.fmea_data import CATEGORIES, FAILURE_CATEGORIES, FMEA_ENTRIES, FREQUENCY_OPTIONS, risk_level
from common.fmea_store import load_saved_rows, save_rows
from common.pdf_report import generate_fmea_pdf_report
from common.theme import flow_row, pill_row

st.title("FMEA — Digital Protection Relays")
st.caption(
    "Failure Mode and Effects Analysis for the numerical/microprocessor-based relays "
    "modeled in this app: GE G60 (Generator 87G), the Mitsubishi CAC1-10-M3 / CAC2-10-M3 "
    "family (Transformer differential), and the Multilin SR469 / GE 869 family (Motor "
    "protection)."
)

with st.expander("📍 How to use this page", expanded=False):
    flow_row("Add a failure mode (optional)", [
        ("➕", "Add New Failure Mode"),
        ("🧩", "Relay + Component + Failure Mode"),
        ("🧭", "Failure Category"),
    ])
    flow_row("Scan the table", [
        ("🔍", "Filter (family + cause)"),
        ("📊", "Scan the table"),
        ("✏️", "Edit S / O / D"),
    ])
    flow_row("Drill into one failure mode", [
        ("👆", "Pick a row below"),
        ("🔬", "Cause / effect / diagnostics"),
        ("🛠️", "Set maintenance task + frequency"),
    ])
    flow_row("Wrap up", [
        ("🚨", "Check High-risk callout"),
        ("💾", "Save / Export (JSON, CSV, PDF)"),
    ])
    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        with st.container(border=True):
            st.markdown("#### ➕ Add New Failure Mode")
            st.write(
                "Log a failure mode against any relay — including one you've modeled on the "
                "🧩 Custom Relay Types page — not just the 3 relay families built into this "
                "app. Pick \"+ Add a new relay type\" under Relay to name it."
            )
    with fc2:
        with st.container(border=True):
            st.markdown("#### 🎯 RPN")
            st.write("Severity × Occurrence × Detection (1–1000). Higher = more urgent. 🟢 Low, 🟠 Medium, 🔴 High.")
    with fc3:
        with st.container(border=True):
            st.markdown("#### 🧭 Failure Category")
            st.write("Root-cause branch (Hardware, Software, Measurement, Wiring, Environment) from the plant's failure-cause diagram.")
    with fc4:
        with st.container(border=True):
            st.markdown("#### 🛠️ Row Detail")
            st.write("Cause, effect, diagnostics, and the editable maintenance task/frequency for one row at a time — kept attached to its failure mode, not a separate tab.")
    st.caption(
        "💾 Everything on this page — scores, maintenance tasks, and any rows you add — is "
        "saved automatically and is still here next time you open the app."
    )

with st.expander("Scope & FMEA scoring conventions", expanded=False):
    st.markdown("##### Scope")
    scope_in, scope_out = st.columns(2)
    with scope_in:
        with st.container(border=True):
            st.markdown(":green[**✅ In scope — numerical/microprocessor relays**]")
            st.write("⚡ GE G60 (Generator 87G)")
            st.write("🔌 Mitsubishi CAC1-10-M3 / CAC2-10-M3 (Transformer)")
            st.write("🌀 Multilin SR469 / GE 869 (Motor)")
    with scope_out:
        with st.container(border=True):
            st.markdown(":red[**❌ Out of scope — electromechanical relays**]")
            st.write("⚙️ GE CFD22B4A (legacy generator)")
            st.write("⚙️ GE IFC66KD2A / HFC22B2A (ID Fan, PA Fan)")
    st.caption(
        "Different failure physics — contact wear/mechanical wear-out vs. firmware/power "
        "supply/watchdog — mixing them would blur two failure physics rather than usefully "
        "compare them."
    )
    st.caption(
        "This is the built-in reference library's scope, not a hard limit — use the "
        "➕ Add New Failure Mode form above to log failure modes for any other relay, "
        "including one modeled on the 🧩 Custom Relay Types page."
    )

    st.markdown("##### Scoring, 1–10 each")
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        with st.container(border=True):
            st.markdown("#### 💥 Severity")
            st.write("How bad if it happens. **1** = minor, **10** = catastrophic.")
    with sc2:
        with st.container(border=True):
            st.markdown("#### 🔁 Occurrence")
            st.write("How likely it is. **1** = rare, **10** = frequent.")
    with sc3:
        with st.container(border=True):
            st.markdown("#### 🔎 Detection ⚠️")
            st.write("**Inverted** from the others: **1** = caught immediately, **10** = goes unnoticed.")

    st.markdown("##### RPN = Severity × Occurrence × Detection")
    pill_row([
        ("accent", "🟢 Low · RPN &lt; 100"),
        ("warning", "🟠 Medium · 100–199"),
        ("negative", "🔴 High · ≥ 200"),
    ])
    st.caption(
        "Starting scores are engineering-judgment placeholders, not measured plant data — "
        "this app has no logged relay failure history to calibrate Occurrence against (see "
        "`Reliability Data.py` at the repo root for a related MTBF/Arrhenius thermal-"
        "derating analysis). Recalibrate against your own plant's experience."
    )

    st.markdown("##### Failure Category root causes")
    fcat1, fcat2, fcat3 = st.columns(3)
    with fcat1:
        with st.container(border=True):
            st.markdown("**⚙️ Hardware Failure**")
            st.caption("Aging, component deterioration")
    with fcat2:
        with st.container(border=True):
            st.markdown("**💻 Software Defects**")
            st.caption("Firmware bugs, weak design, improper specification/settings")
    with fcat3:
        with st.container(border=True):
            st.markdown("**📏 Measurement Errors**")
            st.caption("Sensor failure, filtering, out-of-range operation")
    fcat4, fcat5 = st.columns(2)
    with fcat4:
        with st.container(border=True):
            st.markdown("**🔌 Wiring Problems**")
            st.caption("Mal-connection, electromagnetic compatibility")
    with fcat5:
        with st.container(border=True):
            st.markdown("**🌡️ Environment**")
            st.caption("Temperature/humidity, dust, a noisy operating environment")
    st.caption("From the supervisor-supplied failure-cause diagram for digital relays.")

if "fmea_rows" not in st.session_state:
    # Rows saved to disk from a previous session take priority over the
    # built-in defaults, so S/O/D edits, maintenance tasks, and any rows the
    # engineer has added persist across closing and reopening the app.
    st.session_state.fmea_rows = load_saved_rows() or copy.deepcopy(FMEA_ENTRIES)

# ---------------------------------------------------------------------------
# Load a saved FMEA — processed before any widget bound to session_state keys
# below is created, same ordering constraint views/project.py follows (Streamlit
# forbids writing to a session_state key after a widget with that key already
# exists in this script run).
# ---------------------------------------------------------------------------
st.markdown("### Load Saved FMEA")
uploaded_fmea = st.file_uploader("Load a saved FMEA (.json)", type=["json"], key="fmea_upload")
if uploaded_fmea is not None:
    file_hash = hash(uploaded_fmea.getvalue())
    if st.session_state.get("fmea_loaded_file_hash") != file_hash:
        try:
            payload = json.loads(uploaded_fmea.getvalue().decode("utf-8"))
            if payload.get("format") != "Electrical Equipment Protection Suite FMEA":
                raise ValueError("This does not look like an FMEA file exported from this app.")
            rows = payload.get("rows")
            if not isinstance(rows, list):
                raise ValueError("The file does not contain an FMEA rows section.")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            st.error(f"Could not load FMEA file: {exc}")
            st.session_state["fmea_loaded_file_hash"] = file_hash
        else:
            st.session_state.fmea_rows = rows
            st.session_state["fmea_loaded_file_hash"] = file_hash
            st.toast("Loaded saved FMEA.")
            st.rerun()

st.caption(
    "💾 Every edit here — scores, maintenance tasks, and any failure modes you add — "
    "is saved automatically and will still be here next time you open the app."
)

# ---------------------------------------------------------------------------
# Add New Failure Mode - relay family is free text (not restricted to the 3
# built-in CATEGORIES) so a failure mode can be logged against a relay
# modeled on the Custom Relay Types page too, not just the plant's fixed
# lineup. Existing relay names already in use are offered as a starting
# point; picking "+ Add a new relay type" reveals a text input instead.
# ---------------------------------------------------------------------------
_ADD_NEW_RELAY = "+ Add a new relay type…"

with st.expander("➕ Add New Failure Mode", expanded=False):
    existing_relays = sorted({r["category"] for r in st.session_state.fmea_rows} | set(CATEGORIES))
    add_col1, add_col2 = st.columns(2)
    with add_col1:
        relay_choice = st.selectbox(
            "Relay", existing_relays + [_ADD_NEW_RELAY], key="fmea_add_relay_choice",
        )
        if relay_choice == _ADD_NEW_RELAY:
            new_relay_name = st.text_input("New relay type name", key="fmea_add_relay_new")
        else:
            new_relay_name = relay_choice
        new_component = st.text_input("Component", key="fmea_add_component", help="What part of the relay/circuit this failure mode affects, e.g. \"CT input circuit\".")
    with add_col2:
        new_failure_category = st.selectbox("Failure Category", FAILURE_CATEGORIES, key="fmea_add_failure_category")
        new_failure_mode = st.text_input("Failure Mode", key="fmea_add_failure_mode")

    with st.expander("Optional: cause / effect / diagnostics", expanded=False):
        new_cause = st.text_area("Potential Cause", key="fmea_add_cause", height=60)
        new_effect = st.text_area("Potential Effect", key="fmea_add_effect", height=60)
        new_detection = st.text_area("Diagnostics", key="fmea_add_detection", height=60)

    if st.button("Add Failure Mode", key="fmea_add_btn"):
        if not new_relay_name.strip() or not new_component.strip() or not new_failure_mode.strip():
            st.warning("Relay, Component, and Failure Mode are required.")
        else:
            new_row = dict(
                id=f"custom-{uuid.uuid4().hex[:8]}",
                category=new_relay_name.strip(),
                component=new_component.strip(),
                failure_mode=new_failure_mode.strip(),
                failure_category=new_failure_category,
                potential_cause=new_cause.strip(),
                potential_effect=new_effect.strip(),
                detection_method=new_detection.strip(),
                # Mid-range placeholders, same "engineering judgment, not measured
                # data" convention as the built-in rows - edit immediately below.
                default_severity=5, default_occurrence=5, default_detection=5,
                maintenance_task="", maintenance_frequency=FREQUENCY_OPTIONS[0],
                recommended_action="",
            )
            st.session_state.fmea_rows.append(new_row)
            # Keep the new relay/failure category visible in the filters below
            # without an extra click, rather than silently hiding the row the
            # engineer just added.
            st.session_state["fmea_category_filter"] = list(
                dict.fromkeys(st.session_state.get("fmea_category_filter", list(CATEGORIES)) + [new_relay_name.strip()])
            )
            st.session_state["fmea_failure_category_filter"] = list(
                dict.fromkeys(st.session_state.get("fmea_failure_category_filter", list(FAILURE_CATEGORIES)) + [new_failure_category])
            )
            save_rows(st.session_state.fmea_rows)
            st.toast(f"Added: {new_component.strip()} — {new_failure_mode.strip()}")
            st.rerun()

st.markdown("### Scored FMEA")

# Dynamic, not the static CATEGORIES import: a relay family added via "Add
# New Failure Mode" above must stay filterable/visible, not silently
# disappear because it isn't one of the 3 built-in relay families.
all_relay_categories = sorted({r["category"] for r in st.session_state.fmea_rows} | set(CATEGORIES))

# Both filters' session_state can also be set directly by the "Add New
# Failure Mode" handler above (to keep a just-added row visible without an
# extra click) - only seed a `default` the first time the key doesn't exist
# yet, since passing `default=` alongside a key Streamlit already has a
# direct-assigned value for triggers its "default value AND session state
# API" policy warning.
if "fmea_category_filter" not in st.session_state:
    st.session_state["fmea_category_filter"] = all_relay_categories
if "fmea_failure_category_filter" not in st.session_state:
    st.session_state["fmea_failure_category_filter"] = list(FAILURE_CATEGORIES)

filter_col1, filter_col2 = st.columns(2)
with filter_col1:
    selected_categories = st.multiselect(
        "Relay family", all_relay_categories, key="fmea_category_filter"
    )
with filter_col2:
    selected_failure_categories = st.multiselect(
        "Failure category", FAILURE_CATEGORIES,
        key="fmea_failure_category_filter",
        help="Root-cause branch from the failure-cause diagram (Hardware Failure / "
             "Software Defects / Measurement Errors / Wiring Problems / Environment).",
    )
sort_desc = st.checkbox("Sort by RPN (highest risk first)", value=True, key="fmea_sort_desc")

rows_by_id = {r["id"]: r for r in st.session_state.fmea_rows}

if not selected_categories or not selected_failure_categories:
    st.info("Select at least one relay family and one failure category above to see FMEA rows.")
    st.stop()

visible_ids = [
    r["id"] for r in st.session_state.fmea_rows
    if r["category"] in selected_categories and r.get("failure_category") in selected_failure_categories
]

if not visible_ids:
    st.info("No FMEA rows match that relay family + failure category combination.")
    st.stop()

display_rows = []
for rid in visible_ids:
    r = rows_by_id[rid]
    rpn = r["default_severity"] * r["default_occurrence"] * r["default_detection"]
    display_rows.append({
        "id": r["id"],
        "Category": r["category"],
        "Component": r["component"],
        "Failure Category": r.get("failure_category", ""),
        "Failure Mode": r["failure_mode"],
        "S": r["default_severity"],
        "O": r["default_occurrence"],
        "D": r["default_detection"],
        "RPN": rpn,
        "Risk": risk_level(rpn),
    })

display_df = pd.DataFrame(display_rows)
if sort_desc and not display_df.empty:
    display_df = display_df.sort_values("RPN", ascending=False).reset_index(drop=True)

st.caption(
    "Scores only. Pick a row below to view its cause/effect/diagnostics and edit its "
    "maintenance task."
)
edited_df = st.data_editor(
    display_df,
    key="fmea_editor",
    use_container_width=True,
    hide_index=True,
    disabled=["id", "Category", "Component", "Failure Category", "Failure Mode", "RPN", "Risk"],
    column_config={
        "id": None,
        "Failure Category": st.column_config.TextColumn("Failure Category", width="small", help="Root-cause branch from the failure-cause diagram."),
        "S": st.column_config.NumberColumn("S", min_value=1, max_value=10, step=1, help="Severity (1-10)"),
        "O": st.column_config.NumberColumn("O", min_value=1, max_value=10, step=1, help="Occurrence (1-10)"),
        "D": st.column_config.NumberColumn("D", min_value=1, max_value=10, step=1, help="Detection (1 = easily caught, 10 = essentially undetectable)"),
        "RPN": st.column_config.NumberColumn("RPN", help="Severity x Occurrence x Detection"),
    },
)

# Write S/O/D edits back into the session-held rows by id, so switching the
# category filter (which only changes what's passed to data_editor next rerun)
# doesn't lose anything already typed.
for _, row in edited_df.iterrows():
    target = rows_by_id[row["id"]]
    target["default_severity"] = int(row["S"])
    target["default_occurrence"] = int(row["O"])
    target["default_detection"] = int(row["D"])

# ---------------------------------------------------------------------------
# Row detail - the table above is deliberately lean (scores only); everything
# else about one failure mode (cause, effect, diagnostics, maintenance task/
# frequency, recommended action) lives here, one row at a time, rather than as
# 6 more columns nobody can scan at once. Still attached to the specific row
# by id, same as before - just a different presentation of the same data.
# ---------------------------------------------------------------------------
st.markdown("#### Row Detail")

detail_ids = edited_df["id"].tolist()
detail_key = f"fmea_detail_selector_{hash(tuple(detail_ids))}"
selected_id = st.selectbox(
    "Failure mode",
    options=detail_ids,
    format_func=lambda rid: f"{rows_by_id[rid]['component']} — {rows_by_id[rid]['failure_mode']}",
    key=detail_key,
)
detail_row = rows_by_id[selected_id]
detail_rpn = detail_row["default_severity"] * detail_row["default_occurrence"] * detail_row["default_detection"]

with st.container(border=True):
    st.markdown(
        f"**{detail_row['category']} · {detail_row.get('failure_category', '')}** — "
        f"RPN {detail_rpn} ({risk_level(detail_rpn)})"
    )
    cause = st.text_area(
        "Potential Cause", value=detail_row.get("potential_cause", ""),
        key=f"fmea_cause_{selected_id}", height=60,
    )
    effect = st.text_area(
        "Potential Effect", value=detail_row.get("potential_effect", ""),
        key=f"fmea_effect_{selected_id}", height=60,
    )
    detection = st.text_area(
        "Diagnostics", value=detail_row.get("detection_method", ""),
        key=f"fmea_detection_{selected_id}", height=60,
        help="How this failure is caught - a monitoring alarm, a periodic test, an inspection.",
    )

    detail_task_col, detail_freq_col = st.columns([3, 1])
    with detail_task_col:
        maint_task = st.text_area(
            "Maintenance Task", value=detail_row.get("maintenance_task", ""),
            key=f"fmea_maint_task_{selected_id}", height=80,
            help="What to do to prevent, detect, or respond to this failure mode.",
        )
    with detail_freq_col:
        freq_options = FREQUENCY_OPTIONS
        current_freq = detail_row.get("maintenance_frequency", freq_options[0])
        freq_index = freq_options.index(current_freq) if current_freq in freq_options else 0
        maint_freq = st.selectbox(
            "Frequency", freq_options, index=freq_index,
            key=f"fmea_maint_freq_{selected_id}",
            help="Recalibrate against your plant's own maintenance procedure/standard.",
        )
    rec_action = st.text_area(
        "Recommended Action", value=detail_row.get("recommended_action", ""),
        key=f"fmea_rec_action_{selected_id}", height=60,
    )

detail_row["potential_cause"] = cause
detail_row["potential_effect"] = effect
detail_row["detection_method"] = detection
detail_row["maintenance_task"] = maint_task
detail_row["maintenance_frequency"] = maint_freq
detail_row["recommended_action"] = rec_action

# Persist to disk every rerun (rows_by_id holds the SAME dict objects as
# st.session_state.fmea_rows, so every edit above is already reflected here)
# - this is what makes values "stay the same after closing and reopening the
# app" rather than only lasting for the current browser session.
save_rows(st.session_state.fmea_rows)

# Recompute RPN/Risk from the just-written-back values for the callout below,
# so it reflects this rerun's edits immediately rather than the pre-edit table.
scored = []
for rid in visible_ids:
    r = rows_by_id[rid]
    rpn = r["default_severity"] * r["default_occurrence"] * r["default_detection"]
    scored.append((r, rpn))

high_risk = [(r, rpn) for r, rpn in scored if risk_level(rpn) == "High"]
if high_risk:
    high_risk.sort(key=lambda t: t[1], reverse=True)
    lines = "\n".join(f"- **{r['component']} — {r['failure_mode']}** (RPN {rpn})" for r, rpn in high_risk)
    st.error(f"**{len(high_risk)} High-risk item(s):**\n\n{lines}")
else:
    st.success("No High-risk items in the current filter.")

st.markdown("### Save / Export")

fmea_export = {
    "format": "Electrical Equipment Protection Suite FMEA",
    "version": 1,
    "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
    "rows": st.session_state.fmea_rows,
}

# CSV/PDF export need every column, not just the lean on-screen table - rebuilt
# here from rows_by_id (already holds this rerun's S/O/D and maintenance edits)
# in the same row order the table is currently showing.
full_rows = []
for rid in detail_ids:
    r = rows_by_id[rid]
    rpn = r["default_severity"] * r["default_occurrence"] * r["default_detection"]
    full_rows.append({
        "Category": r["category"],
        "Component": r["component"],
        "Failure Category": r.get("failure_category", ""),
        "Failure Mode": r["failure_mode"],
        "Potential Cause": r["potential_cause"],
        "Potential Effect": r["potential_effect"],
        "Diagnostics": r["detection_method"],
        "S": r["default_severity"],
        "O": r["default_occurrence"],
        "D": r["default_detection"],
        "RPN": rpn,
        "Risk": risk_level(rpn),
        "Maintenance Task": r.get("maintenance_task", ""),
        "Frequency": r.get("maintenance_frequency", FREQUENCY_OPTIONS[0]),
        "Recommended Action": r.get("recommended_action", ""),
    })
full_df = pd.DataFrame(full_rows)

save_col, csv_col, pdf_col = st.columns(3)
with save_col:
    st.download_button(
        "💾 Save FMEA (.json)",
        data=json.dumps(fmea_export, indent=2),
        file_name=f"FMEA_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.json",
        mime="application/json",
        help="Saves every row's current scores and recommended actions - reload it later with the loader above.",
    )
with csv_col:
    st.download_button(
        "Download CSV",
        data=full_df.to_csv(index=False),
        file_name=f"FMEA_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
    )
with pdf_col:
    if st.button("Export PDF"):
        pdf_buf = generate_fmea_pdf_report(full_rows, selected_categories)
        st.download_button(
            "Download PDF",
            data=pdf_buf.getvalue(),
            file_name=f"FMEA_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
            key="fmea_pdf_dl",
        )
