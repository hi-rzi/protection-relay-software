import copy
import datetime
import json

import pandas as pd
import streamlit as st

from common.fmea_data import CATEGORIES, FAILURE_CATEGORIES, FMEA_ENTRIES, FREQUENCY_OPTIONS, risk_level
from common.pdf_report import generate_fmea_pdf_report

st.title("FMEA — Digital Protection Relays")
st.caption(
    "Failure Mode and Effects Analysis for the numerical/microprocessor-based relays "
    "modeled in this app: GE G60 (Generator 87G), the Mitsubishi CAC1-10-M3 / CAC2-10-M3 "
    "family (Transformer differential), and the Multilin SR469 / GE 869 family (Motor "
    "protection)."
)

with st.expander("Scope and how to use this page", expanded=False):
    st.markdown(
        "**Why only these three relay families?** The GE CFD22B4A (legacy generator "
        "relay) and the GE IFC66KD2A/HFC22B2A stack (on ID Fan and PA Fan) are "
        "electromechanical — this app's own Theory tabs already describe them that way. "
        "An electromechanical relay's dominant failure modes are physical (contact wear, "
        "mechanical wear-out, coil burnout), genuinely different from a microprocessor "
        "relay's (firmware, power supply, watchdog, CT/output circuitry). Mixing the two "
        "into one FMEA would blur two different failure physics rather than usefully "
        "compare them, so they're intentionally out of scope here.\n\n"
        "**Severity / Occurrence / Detection** are each scored 1–10, standard FMEA "
        "convention. Detection is the one axis that inverts intuition: **1 = the failure "
        "would be caught immediately and reliably, 10 = it would go essentially "
        "unnoticed** until it mattered.\n\n"
        "**Risk Priority Number (RPN)** = Severity × Occurrence × Detection (range "
        "1–1000). The starting scores below are engineering-judgment placeholders, not "
        "measured plant data — this app has no logged relay failure history to calibrate "
        "Occurrence against (see `Reliability Data.py` at the repo root for a related "
        "MTBF/Arrhenius thermal-derating analysis for generator relays). Edit any score "
        "to reflect your own plant's experience; every value below is a starting point, "
        "not a finding.\n\n"
        "**Diagnostics** (how the failure is actually caught — an alarm, a supervision "
        "circuit, a periodic test) and **Maintenance Task / Frequency** (what to do about "
        "it, and how often) are attached to each failure mode below, not split into a "
        "separate tab — a maintenance action divorced from the specific failure it "
        "addresses isn't actionable. Frequency is editable for the same reason S/O/D are: "
        "these are starting suggestions, recalibrate them against your plant's own "
        "maintenance procedure/standard.\n\n"
        "**Failure Category** classifies each row's root cause using the five-branch "
        "taxonomy from the supervisor-supplied failure-cause diagram for digital relays: "
        "**Hardware Failure** (aging, component deterioration), **Software Defects** "
        "(firmware bugs, weak design, improper specification/settings), **Measurement "
        "Errors** (sensor failure, filtering, out-of-range operation), **Wiring Problems** "
        "(mal-connection, electromagnetic compatibility), and **Environment** (temperature/"
        "humidity, dust, a noisy operating environment). Filter by it below to view the "
        "FMEA the same way the diagram organizes root causes."
    )

if "fmea_rows" not in st.session_state:
    st.session_state.fmea_rows = copy.deepcopy(FMEA_ENTRIES)

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

st.markdown("### Scored FMEA")

filter_col1, filter_col2 = st.columns(2)
with filter_col1:
    selected_categories = st.multiselect(
        "Relay family", CATEGORIES, default=CATEGORIES, key="fmea_category_filter"
    )
with filter_col2:
    selected_failure_categories = st.multiselect(
        "Failure category", FAILURE_CATEGORIES, default=FAILURE_CATEGORIES,
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

display_df = pd.DataFrame(display_rows)
if sort_desc and not display_df.empty:
    display_df = display_df.sort_values("RPN", ascending=False).reset_index(drop=True)

edited_df = st.data_editor(
    display_df,
    key="fmea_editor",
    use_container_width=True,
    hide_index=True,
    disabled=["id", "Category", "Component", "Failure Category", "Failure Mode",
              "Potential Cause", "Potential Effect", "Diagnostics", "RPN", "Risk"],
    column_config={
        "id": None,
        "Failure Category": st.column_config.TextColumn("Failure Category", width="small", help="Root-cause branch from the failure-cause diagram."),
        "S": st.column_config.NumberColumn("S", min_value=1, max_value=10, step=1, help="Severity (1-10)"),
        "O": st.column_config.NumberColumn("O", min_value=1, max_value=10, step=1, help="Occurrence (1-10)"),
        "D": st.column_config.NumberColumn("D", min_value=1, max_value=10, step=1, help="Detection (1 = easily caught, 10 = essentially undetectable)"),
        "RPN": st.column_config.NumberColumn("RPN", help="Severity x Occurrence x Detection"),
        "Diagnostics": st.column_config.TextColumn("Diagnostics", width="medium", help="How this failure is actually detected - an alarm, a supervision circuit, a periodic test."),
        "Maintenance Task": st.column_config.TextColumn("Maintenance Task", width="large", help="What to do to prevent, detect, or respond to this failure mode."),
        "Frequency": st.column_config.SelectboxColumn("Frequency", options=FREQUENCY_OPTIONS, help="Recalibrate against your plant's own maintenance procedure/standard."),
        "Recommended Action": st.column_config.TextColumn("Recommended Action", width="large"),
    },
)

# Write edits back into the session-held rows by id, so switching the category
# filter (which only changes what's passed to data_editor next rerun) doesn't
# lose anything already typed.
for _, row in edited_df.iterrows():
    target = rows_by_id[row["id"]]
    target["default_severity"] = int(row["S"])
    target["default_occurrence"] = int(row["O"])
    target["default_detection"] = int(row["D"])
    target["maintenance_task"] = row["Maintenance Task"]
    target["maintenance_frequency"] = row["Frequency"]
    target["recommended_action"] = row["Recommended Action"]

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
    csv_df = edited_df.drop(columns=["id"])
    st.download_button(
        "Download CSV",
        data=csv_df.to_csv(index=False),
        file_name=f"FMEA_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
    )
with pdf_col:
    if st.button("Export PDF"):
        pdf_buf = generate_fmea_pdf_report(edited_df.to_dict("records"), selected_categories)
        st.download_button(
            "Download PDF",
            data=pdf_buf.getvalue(),
            file_name=f"FMEA_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
            key="fmea_pdf_dl",
        )
