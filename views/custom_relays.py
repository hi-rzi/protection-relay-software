import datetime

import plotly.graph_objects as go
import streamlit as st

from common.custom_relay_store import list_relays, create_relay, delete_relay, get_fields
from common.pdf_report import generate_custom_relay_pdf_report
from common.profile_io import export_profile_button, restore_profile_uploader
from common.ui_helpers import sidebar_section_nav
from engines.custom_relay import CustomRelay, CURVE_NAMES, curve_sweep, curve_trip_time

st.title("Custom Relay Types")
st.caption(
    "Model a relay this app doesn't have a dedicated page for. Enter its CT spec and "
    "whichever standard protection elements it actually has, then use the same simulate, "
    "commission, and export tools the plant's own equipment pages use."
)
st.info(
    "Curves offered here are the published IEC 60255-151 / IEEE C37.112 standard "
    "inverse-time formulas, plus Definite Time — a generic starting point for any relay "
    "that offers selectable standard curves. This does not cover percentage-restrained "
    "(dual-slope) differential protection, which needs a restraint-current input "
    "structure specific to the protected equipment (see the Generator/Transformer pages "
    "for that) — engineering review is required before applying any setting shown here."
)

# -----------------------------------------------------------------------
# Relay picker (sidebar) - unlike every other equipment page (one fixed
# relay per page), this page manages any number of user-defined relays.
# -----------------------------------------------------------------------
relays = list_relays()

st.sidebar.markdown("### Your Custom Relays")

if not relays:
    st.sidebar.caption("No custom relays yet — add your first one below.")
    new_name = st.sidebar.text_input("New relay name", value="New Custom Relay", key="cr_new_name_first")
    if st.sidebar.button("+ Add Relay", key="cr_add_first"):
        new_rid = create_relay(new_name.strip() or "New Custom Relay")
        st.session_state["cr_selected_id"] = new_rid
        st.rerun()
    st.info("Add your first custom relay from the sidebar to get started.")
    st.stop()

labels = [name for _, name in relays]
ids = [rid for rid, _ in relays]
if st.session_state.get("cr_selected_id") not in ids:
    st.session_state["cr_selected_id"] = ids[0]

selected_label = st.sidebar.selectbox(
    "Selected Relay", labels, index=ids.index(st.session_state["cr_selected_id"]), key="cr_picker",
)
rid = ids[labels.index(selected_label)]
st.session_state["cr_selected_id"] = rid

# Only the SELECTED relay's widgets render each rerun (every other relay is
# entirely absent from this run, not just CSS-hidden) - Streamlit purges a
# widget's session_state entry whenever it isn't instantiated on a rerun, so
# relying on plain `key=f"{rid}__field"` persistence alone would silently
# wipe every other relay's settings the moment the user switched away and
# back. `data` is a persistent, non-widget dict that survives that; ensure()
# reseeds a widget's session_state key from `data` only the first time it's
# (re)created, and every widget's value is written straight back into `data`
# right after - see common/custom_relay_store.py's module docstring.
data = get_fields(rid)


def k(name):
    return f"{rid}__{name}"


def ensure(name, default):
    key = k(name)
    if key not in st.session_state:
        st.session_state[key] = data.get(name, default)
    return key


restore_profile_uploader(st.sidebar, "custom_relay", f"{rid}__", uploader_key=rid)

new_name = st.sidebar.text_input("New relay name", value="New Custom Relay", key="cr_new_name")
if st.sidebar.button("+ Add Relay", key="cr_add"):
    new_rid = create_relay(new_name.strip() or "New Custom Relay")
    st.session_state["cr_selected_id"] = new_rid
    st.rerun()

with st.sidebar.popover("🗑️ Delete This Relay"):
    st.write(f"Permanently delete **{selected_label}**? This can't be undone.")
    if st.button("Confirm Delete", key="cr_delete_confirm"):
        delete_relay(rid)
        st.session_state.pop("cr_selected_id", None)
        st.rerun()

selected, c, _ = sidebar_section_nav(
    ["Current Settings", "Simulate & Test", "Commissioning & Injection Tool", "Settings Summary & Approval"],
    key_prefix=rid,
)

# -----------------------------------------------------------------------
# Current Settings
# -----------------------------------------------------------------------
with c["Current Settings"]:
    st.subheader("Relay Identification")
    display_name = st.text_input("Relay Name / Tag", key=ensure("display_name", selected_label))
    data["display_name"] = display_name
    col_m, col_mo = st.columns(2)
    with col_m:
        manufacturer = st.text_input("Manufacturer (optional)", key=ensure("manufacturer", ""))
        data["manufacturer"] = manufacturer
    with col_mo:
        model = st.text_input("Model (optional)", key=ensure("model", ""))
        data["model"] = model
    equipment_tag = st.text_input(
        "Protected Equipment (optional)", key=ensure("equipment_tag", ""),
        help='What this relay protects, e.g. "Feeder F-12" or "Bus Tie Breaker".',
    )
    data["equipment_tag"] = equipment_tag

    st.markdown("#### CT Specification")
    col1, col2 = st.columns(2)
    with col1:
        ct_ratio = st.number_input("Phase CT Ratio (Primary A)", min_value=1.0, key=ensure("ct_ratio", 100.0))
        data["ct_ratio"] = ct_ratio
        ct_secondary_rating = st.selectbox("CT Secondary Rating (A)", [1.0, 5.0], key=ensure("ct_sec", 5.0))
        data["ct_sec"] = ct_secondary_rating
    with col2:
        ground_ct_ratio = st.number_input(
            "Ground CT Ratio (Primary A, 0 = not used)", min_value=0.0, key=ensure("gct_ratio", 0.0),
        )
        data["gct_ratio"] = ground_ct_ratio
        ground_ct_secondary_rating = st.selectbox("Ground CT Secondary Rating (A)", [1.0, 5.0], key=ensure("gct_sec", 5.0))
        data["gct_sec"] = ground_ct_secondary_rating

    st.markdown("#### Protection Elements")
    st.caption("Enable whichever elements this relay actually has — only enabled elements are simulated and included in the report.")

    elements = {}

    en51 = st.checkbox("51 — Phase Time-Overcurrent", key=ensure("en51", False))
    data["en51"] = en51
    if en51:
        with st.container(border=True):
            p51_pickup = st.number_input("Pickup (A secondary)", min_value=0.01, key=ensure("p51_pickup", 4.0))
            p51_curve = st.selectbox("Curve", CURVE_NAMES, key=ensure("p51_curve", CURVE_NAMES[0]))
            p51_td = st.number_input("Time Dial / TMS", min_value=0.01, step=0.05, key=ensure("p51_td", 1.0))
        data.update({"p51_pickup": p51_pickup, "p51_curve": p51_curve, "p51_td": p51_td})
        elements["51"] = {"pickup_sec": p51_pickup, "curve": p51_curve, "time_dial": p51_td}

    en50 = st.checkbox("50 — Phase Instantaneous", key=ensure("en50", False))
    data["en50"] = en50
    if en50:
        with st.container(border=True):
            p50_pickup = st.number_input("Pickup (A secondary)", min_value=0.01, key=ensure("p50_pickup", 40.0))
            p50_delay = st.number_input("Delay (ms)", min_value=0.0, key=ensure("p50_delay", 50.0))
        data.update({"p50_pickup": p50_pickup, "p50_delay": p50_delay})
        elements["50"] = {"pickup_sec": p50_pickup, "delay_ms": p50_delay}

    en51g = st.checkbox("51G — Ground Time-Overcurrent", key=ensure("en51g", False))
    data["en51g"] = en51g
    if en51g:
        with st.container(border=True):
            p51g_pickup = st.number_input("Pickup (A secondary)", min_value=0.01, key=ensure("p51g_pickup", 1.0))
            p51g_curve = st.selectbox("Curve", CURVE_NAMES, key=ensure("p51g_curve", CURVE_NAMES[0]))
            p51g_td = st.number_input("Time Dial / TMS", min_value=0.01, step=0.05, key=ensure("p51g_td", 1.0))
        data.update({"p51g_pickup": p51g_pickup, "p51g_curve": p51g_curve, "p51g_td": p51g_td})
        elements["51G"] = {"pickup_sec": p51g_pickup, "curve": p51g_curve, "time_dial": p51g_td}

    en50g = st.checkbox("50G — Ground Instantaneous", key=ensure("en50g", False))
    data["en50g"] = en50g
    if en50g:
        with st.container(border=True):
            p50g_pickup = st.number_input("Pickup (A secondary)", min_value=0.01, key=ensure("p50g_pickup", 5.0))
            p50g_delay = st.number_input("Delay (ms)", min_value=0.0, key=ensure("p50g_delay", 50.0))
        data.update({"p50g_pickup": p50g_pickup, "p50g_delay": p50g_delay})
        elements["50G"] = {"pickup_sec": p50g_pickup, "delay_ms": p50g_delay}

    en87 = st.checkbox(
        "87 — Self-Balancing Differential", key=ensure("en87", False),
        help="Instantaneous fixed-pickup differential (one CT sensing line and neutral together) — "
             "not a percentage-restrained/dual-slope differential.",
    )
    data["en87"] = en87
    if en87:
        with st.container(border=True):
            p87_pickup = st.number_input("Pickup (A primary)", min_value=0.1, key=ensure("p87_pickup", 20.0))
        data["p87_pickup"] = p87_pickup
        elements["87"] = {"pickup_primary": p87_pickup}

    en46 = st.checkbox("46 — Current Unbalance", key=ensure("en46", False))
    data["en46"] = en46
    if en46:
        with st.container(border=True):
            colu1, colu2 = st.columns(2)
            with colu1:
                p46_alarm_pct = st.number_input("Alarm Pickup (%)", min_value=0.0, key=ensure("46_alarm_pct", 15.0))
                p46_alarm_delay = st.number_input("Alarm Delay (s)", min_value=0.0, key=ensure("46_alarm_delay", 5.0))
            with colu2:
                p46_trip_pct = st.number_input("Trip Pickup (%)", min_value=0.0, key=ensure("46_trip_pct", 25.0))
                p46_trip_delay = st.number_input("Trip Delay (s)", min_value=0.0, key=ensure("46_trip_delay", 2.0))
        data.update({
            "46_alarm_pct": p46_alarm_pct, "46_alarm_delay": p46_alarm_delay,
            "46_trip_pct": p46_trip_pct, "46_trip_delay": p46_trip_delay,
        })
        elements["46"] = {
            "alarm_pct": p46_alarm_pct, "alarm_delay_s": p46_alarm_delay,
            "trip_pct": p46_trip_pct, "trip_delay_s": p46_trip_delay,
        }

    if not elements:
        st.warning("Enable at least one protection element above to simulate and test this relay.")

    st.markdown("---")
    st.markdown("#### Save Profile")
    st.caption("Name and download this relay's settings — use the loader in the sidebar to restore it later.")
    export_profile_button(st, "custom_relay", f"{rid}__", default_name=display_name, button_key=rid)

relay = CustomRelay(
    tag=display_name, ct_ratio=ct_ratio, ct_secondary_rating=ct_secondary_rating,
    ground_ct_ratio=ground_ct_ratio or None, ground_ct_secondary_rating=ground_ct_secondary_rating,
    elements=elements,
)

# -----------------------------------------------------------------------
# Simulate & Test - test-current inputs are intentionally left ephemeral
# (plain widget keys, not synced into `data`): resetting them when you
# switch to a different relay is expected, the same as switching between
# equipment PAGES elsewhere in the app doesn't remember test currents either.
# -----------------------------------------------------------------------
with c["Simulate & Test"]:
    st.subheader("Test Currents")
    test_phase = st.number_input(
        "Phase Current (A primary)", min_value=0.0, value=0.0, key=k("test_phase"),
    ) if ("51" in elements or "50" in elements) else 0.0
    test_ground = st.number_input(
        "Ground Current (A primary)", min_value=0.0, value=0.0, key=k("test_ground"),
    ) if ("51G" in elements or "50G" in elements) else 0.0
    test_diff = st.number_input(
        "Differential Current (A primary)", min_value=0.0, value=0.0, key=k("test_diff"),
    ) if "87" in elements else 0.0
    test_unbal = st.number_input(
        "Current Unbalance (%)", min_value=0.0, value=0.0, key=k("test_unbal"),
    ) if "46" in elements else 0.0

    if not elements:
        st.info("Enable at least one protection element under Current Settings to simulate.")
    else:
        results = relay.evaluate(
            i_phase_primary=test_phase, i_ground_primary=test_ground,
            i_diff_primary=test_diff, unbalance_pct=test_unbal,
        )
        if any(r["is_trip"] for r in results.values()):
            st.error("PROTECTION TRIP")
        else:
            st.success("SYSTEM HEALTHY")

        st.dataframe(
            [
                {
                    "Element": relay.ELEMENT_LABELS[tag],
                    "Multiple": f"{r['multiple']:.2f}x" if r["multiple"] is not None else "—",
                    "Status": r["status"],
                }
                for tag, r in results.items()
            ],
            use_container_width=True, hide_index=True,
        )

        st.markdown("#### Time-Current Characteristic")
        sim_curve_elements = [tag for tag in ("51", "51G") if tag in elements]
        if sim_curve_elements:
            fig = go.Figure()
            for tag in sim_curve_elements:
                el = elements[tag]
                multiples, times = curve_sweep(el["curve"], el["time_dial"])
                fig.add_trace(go.Scatter(x=multiples, y=times, mode="lines", name=f"{tag} ({el['curve']})"))
            fig.update_layout(
                xaxis_title="Current (x Pickup)", yaxis_title="Trip Time (s)",
                xaxis_type="log", yaxis_type="log", template="plotly_white", height=450,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No time-curve (51/51G) elements enabled — nothing to plot.")

# -----------------------------------------------------------------------
# Commissioning & Injection Tool
# -----------------------------------------------------------------------
with c["Commissioning & Injection Tool"]:
    st.subheader("Secondary Current Injection Assistant")
    inj_curve_elements = [tag for tag in ("51", "51G") if tag in elements]
    if not inj_curve_elements:
        st.info("Enable a 51 or 51G element under Current Settings to use the injection tool.")
    else:
        target_tag = st.selectbox(
            "Element to Test", inj_curve_elements, format_func=lambda t: relay.ELEMENT_LABELS[t], key=k("inj_element"),
        )
        el = elements[target_tag]
        target_multiple = st.slider("Target Multiple of Pickup (M)", 1.05, 20.0, 3.0, 0.05, key=k("inj_multiple"))
        inject_sec = el["pickup_sec"] * target_multiple
        t = curve_trip_time(el["curve"], target_multiple, el["time_dial"])

        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("Inject (A secondary)", f"{inject_sec:.3f} A")
        with col_b:
            st.metric("Expected Trip Time", f"{t:.2f}s" if t else "No Trip")

        st.markdown("##### Auto-Sweep Test Table")
        sweep_start = st.number_input("Sweep Start (x Pickup)", min_value=1.05, value=1.5, key=k("sweep_start"))
        sweep_end = st.number_input("Sweep End (x Pickup)", min_value=sweep_start, value=10.0, key=k("sweep_end"))
        sweep_step = st.number_input("Sweep Step (x Pickup)", min_value=0.1, value=1.0, key=k("sweep_step"))
        if st.button("Generate Sweep Table", key=k("sweep_btn")):
            sweep_rows = []
            m = sweep_start
            while m <= sweep_end + 1e-9:
                tt = curve_trip_time(el["curve"], m, el["time_dial"])
                sweep_rows.append({
                    "Multiple": f"{m:.2f}x",
                    "Inject (A sec.)": f"{el['pickup_sec'] * m:.3f}",
                    "Trip Time (s)": f"{tt:.2f}" if tt else "No Trip",
                })
                m += sweep_step
            st.dataframe(sweep_rows, use_container_width=True, hide_index=True)

# -----------------------------------------------------------------------
# Settings Summary & Approval
# -----------------------------------------------------------------------
with c["Settings Summary & Approval"]:
    st.subheader("Settings Summary & Approval Record")
    st.caption(
        "Record the settings basis and review status before exporting a controlled report. "
        "This record supports engineering review; it does not replace an approved protection study."
    )
    source_document = st.text_input("Source document", key=ensure("src_doc", ""))
    data["src_doc"] = source_document
    col1, col2 = st.columns(2)
    with col1:
        revision = st.text_input("Document / settings revision", key=ensure("revision", ""))
        data["revision"] = revision
        prepared_by = st.text_input("Prepared by", key=ensure("prepared_by", ""))
        data["prepared_by"] = prepared_by
    with col2:
        reviewed_by = st.text_input("Reviewed by", key=ensure("reviewed_by", ""))
        data["reviewed_by"] = reviewed_by
        approval_status = st.selectbox(
            "Review status",
            ["Draft — engineering review required", "Reviewed — pending approval", "Approved"],
            key=ensure("approval_status", "Draft — engineering review required"),
        )
        data["approval_status"] = approval_status
    review_note = st.text_area("Review note / change description", key=ensure("review_note", ""))
    data["review_note"] = review_note

    approval = {
        "source_document": source_document, "revision": revision,
        "prepared_by": prepared_by, "reviewed_by": reviewed_by,
        "approval_status": approval_status, "review_note": review_note,
    }

    settings_sheet_rows = [("CT Ratio", f"{ct_ratio:.0f}:{ct_secondary_rating:.0f}")]
    if ground_ct_ratio:
        settings_sheet_rows.append(("Ground CT Ratio", f"{ground_ct_ratio:.0f}:{ground_ct_secondary_rating:.0f}"))
    for tag, el in elements.items():
        label = relay.ELEMENT_LABELS[tag]
        if tag in ("51", "51G"):
            settings_sheet_rows += [
                (f"{label} — Pickup", f"{el['pickup_sec']:.2f} A sec."),
                (f"{label} — Curve", el["curve"]),
                (f"{label} — Time Dial / TMS", f"{el['time_dial']:.2f}"),
            ]
        elif tag in ("50", "50G"):
            settings_sheet_rows += [
                (f"{label} — Pickup", f"{el['pickup_sec']:.2f} A sec."),
                (f"{label} — Delay", f"{el['delay_ms']:.0f} ms"),
            ]
        elif tag == "87":
            settings_sheet_rows.append((f"{label} — Pickup", f"{el['pickup_primary']:.1f} A primary"))
        elif tag == "46":
            settings_sheet_rows += [
                (f"{label} — Alarm", f"{el['alarm_pct']:.0f}% / {el['alarm_delay_s']:.0f}s"),
                (f"{label} — Trip", f"{el['trip_pct']:.0f}% / {el['trip_delay_s']:.0f}s"),
            ]

    st.markdown("#### Applied Settings")
    st.dataframe(
        [{"Parameter": p, "Value": v} for p, v in settings_sheet_rows],
        use_container_width=True, hide_index=True,
    )

    st.markdown("---")
    if not elements:
        st.info("Enable at least one protection element to export a report.")
    else:
        results = relay.evaluate(
            i_phase_primary=test_phase, i_ground_primary=test_ground,
            i_diff_primary=test_diff, unbalance_pct=test_unbal,
        )
        test_inputs = {
            "i_phase_primary": test_phase, "i_ground_primary": test_ground,
            "i_diff_primary": test_diff, "unbalance_pct": test_unbal,
        }
        pdf_bytes = generate_custom_relay_pdf_report(
            display_name, relay, results, test_inputs, approval=approval,
            settings_sheets=[(display_name, settings_sheet_rows)],
        )
        st.download_button(
            label="Export Certified Protection Audit Report",
            data=pdf_bytes,
            file_name=f"{display_name.replace(' ', '_')}_Protection_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
            help="Includes the Relay-Ready Settings Sheet as its final section.",
        )
