import datetime
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _two_col_table(rows, col_widths=(200, 200)):
    t = Table(rows, colWidths=list(col_widths))
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor("#1F2937")),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    return t


def build_pdf_report(report_title, meta_text, sections, results_header=None, results_rows=None,
                      results_col_widths=(90, 90, 90, 100, 150)):
    """Generic equipment-agnostic protection evaluation report builder.

    sections: list of (heading, two_col_rows) tuples, each rendered as a titled
        Heading2 followed by a 2-column key/value table.
    results_header / results_rows: optional final "Evaluation Results" table
        (e.g. per-phase trip verdicts), styled distinctly from the spec tables.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor("#1E3A8A"))
    story.append(Paragraph(report_title, title_style))
    story.append(Spacer(1, 10))

    story.append(Paragraph(meta_text, styles['Normal']))
    story.append(Spacer(1, 15))

    for idx, (heading, rows) in enumerate(sections, start=1):
        story.append(Paragraph(f"<b>{idx}. {heading}</b>", styles['Heading2']))
        story.append(_two_col_table(rows))
        story.append(Spacer(1, 15))

    if results_header and results_rows is not None:
        story.append(Paragraph(f"<b>{len(sections) + 1}. Evaluation Results</b>", styles['Heading2']))
        # Header cells are wrapped in a Paragraph (not left as plain strings) so
        # long column labels (e.g. a 3-winding relay's per-winding Amps columns)
        # word-wrap within their column instead of overlapping neighboring cells.
        header_style = ParagraphStyle('ResultsHeader', parent=styles['Normal'], fontSize=8,
                                       leading=10, textColor=colors.white, fontName='Helvetica-Bold',
                                       alignment=1)
        wrapped_header = [Paragraph(str(cell), header_style) for cell in results_header]
        results_data = [wrapped_header] + results_rows
        t_results = Table(results_data, colWidths=list(results_col_widths))
        t_results.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
        ]))
        story.append(t_results)

    doc.build(story)
    buffer.seek(0)
    return buffer


def _settings_sheet_sections(settings_sheets):
    """settings_sheets: optional list of (relay_type_label, rows) tuples, rows
    being (Parameter, Value) pairs using the SAME terminology as that relay's
    own instruction manual/settings summary - a checklist for manual entry
    into the relay's own settings software or front-panel HMI, deliberately
    not an importable relay project file (see module docstring precedent:
    this app has no access to vendor proprietary settings-file formats).
    Returns a list of (heading, two_col_rows) tuples ready to append to a
    build_pdf_report() sections list - empty list if none supplied."""
    if not settings_sheets:
        return []
    out = []
    for relay_type_label, rows in settings_sheets:
        out.append((f"Relay-Ready Settings Sheet — {relay_type_label}", [["Parameter", "Value"]] + list(rows)))
    return out


def generate_generator_pdf_report(unit_name, relay_obj, evals, phases, inputs=None, settings_sheets=None):
    """Generator (87G) report — output is identical to the original monolithic
    generate_pdf_report(), now built on top of the shared build_pdf_report().

    inputs: optional {phase: {"i_N": ..., "i_T": ...}} — when supplied, the
    Neutral/Terminal primary Amps actually entered for each phase are added
    to the results table, not just the derived pu values.
    settings_sheets: optional list of (relay_type_label, rows) tuples - see
    _settings_sheet_sections()."""
    report_title = f"Generator Differential Protection (87G) Evaluation Report - {relay_obj.mode} Mode"
    meta_text = f"<b>Date/Time:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | <b>Configuration:</b> {unit_name}"

    generator_rows = [
        ["Parameter", "Value"],
        ["Generator Rating", f"{relay_obj.mva_rated} MVA"],
        ["Rated Voltage", f"{relay_obj.kv_rated} kV"],
        ["Rated Current (Pri)", f"{relay_obj.i_rated_pri:.2f} A"],
        ["Neutral CT Ratio", f"{relay_obj.ct_ratio_N:.0f}:{relay_obj.ct_secondary_rating:.0f}"],
        ["Terminal CT Ratio", f"{relay_obj.ct_ratio_T:.0f}:{relay_obj.ct_secondary_rating:.0f}"]
    ]

    if relay_obj.mode == "GENERATOR_LEGACY":
        relay_rows = [
            ["Parameter", "Value"],
            ["Relay Type", "GE CFD22B4A (GEK-34124)"],
            ["Target/Seal-in Pickup", f"{relay_obj.target_amps} A sec." if relay_obj.target_amps is not None else "N/A"],
            ["Equivalent Pickup", f"{relay_obj.i_pickup:.3f} pu"],
            ["Restraint Slope (GEK-34124E)", f"{relay_obj.s1*100:.1f} %"],
            ["Breakpoints / 2nd Slope / High-Set", "N/A - fixed by relay design"]
        ]
    else:
        has_unrestrained = relay_obj.i_unrestrained < 1e5
        relay_rows = [
            ["Parameter", "Value"],
            ["Relay Type", "GE G60 (Numerical)"],
            ["Pickup", f"{relay_obj.i_pickup:.3f} pu"],
            ["Slope 1", f"{relay_obj.s1*100:.0f} %"],
            ["Slope 2", f"{relay_obj.s2*100:.0f} %"],
            ["Break 1", f"{relay_obj.break_1:.2f} pu"],
            ["Break 2", f"{relay_obj.break_2:.2f} pu"],
            ["Unrestrained High-Set", f"{relay_obj.i_unrestrained:.2f} pu" if has_unrestrained else "Not enabled / unconfirmed"]
        ]

    if inputs:
        results_header = ["Phase", "Neutral Pri (A)", "Terminal Pri (A)", "I_op [pu]", "I_rest [pu]", "Threshold [pu]", "Status"]
        results_rows = []
        for p in phases:
            e = evals[p]
            i = inputs[p]
            results_rows.append([
                p, f"{i['i_N']:.1f}", f"{i['i_T']:.1f}",
                f"{e['i_op_pu']:.3f}", f"{e['i_rest_pu']:.3f}", f"{e['i_threshold_pu']:.3f}", e['status'],
            ])
        results_col_widths = (55, 75, 75, 65, 65, 75, 90)
    else:
        results_header = ["Phase", "I_op [pu]", "I_rest [pu]", "Threshold [pu]", "Status"]
        results_rows = []
        for p in phases:
            e = evals[p]
            results_rows.append([p, f"{e['i_op_pu']:.3f}", f"{e['i_rest_pu']:.3f}", f"{e['i_threshold_pu']:.3f}", e['status']])
        results_col_widths = (90, 90, 90, 100, 150)

    return build_pdf_report(
        report_title, meta_text,
        sections=[("Generator Parameters", generator_rows), ("Relay Parameters", relay_rows)]
                 + _settings_sheet_sections(settings_sheets),
        results_header=results_header, results_rows=results_rows, results_col_widths=results_col_widths,
    )


def generate_transformer_pdf_report(unit_name, relay_obj, evals, phases, relay_type_label="CAC1-10-M3",
                                     winding_currents=None, settings_sheets=None):
    """Transformer differential (87T) report — built on the same shared
    build_pdf_report() used for the Generator report. Works for any winding
    count (2-winding EXCT/GSUT, 3-winding Overall).

    winding_currents: optional {phase: [primary_amps, ...]}, aligned in order
    with relay_obj.windings — when supplied, each winding's primary Amps
    actually entered for that phase are added to the results table.
    settings_sheets: optional list of (relay_type_label, rows) tuples - see
    _settings_sheet_sections()."""
    report_title = f"Transformer Differential Protection (87T) Evaluation Report - {unit_name}"
    meta_text = f"<b>Date/Time:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | <b>Configuration:</b> {unit_name}"

    transformer_rows = [["Parameter", "Value"], ["Transformer Rating", f"{relay_obj.mva_rated} MVA"]]
    for w in relay_obj.windings:
        transformer_rows.append([f"{w['name']} Rated Voltage", f"{w['kv']} kV"])
        transformer_rows.append([f"{w['name']} CT Ratio", f"{w['ct_ratio']:.0f}:{w['ct_secondary_rating']:.0f}"])
        transformer_rows.append([f"{w['name']} Tap", f"{w['tap']:.3f}"])

    relay_rows = [
        ["Parameter", "Value"],
        ["Relay Type", relay_type_label],
        ["Bias (Slope)", f"{relay_obj.bias*100:.1f} %"],
        ["Minimum Operate", f"{relay_obj.min_operate_pu*100:.1f} %"],
        ["HOC (Unrestrained High-Set)", f"{relay_obj.hoc_pu:.2f} x tap current"],
        ["Restraint Convention", relay_obj.convention],
        ["CT Polarity Reference", relay_obj.ct_polarity],
    ]

    if winding_currents:
        winding_names = [w["name"] for w in relay_obj.windings]
        results_header = ["Phase"] + [f"{name} Pri (A)" for name in winding_names] + ["I_op [pu]", "I_rest [pu]", "Threshold [pu]", "Status"]
        results_rows = []
        for p in phases:
            e = evals[p]
            amp_cells = [f"{amps:.1f}" for amps in winding_currents[p]]
            results_rows.append([p] + amp_cells + [f"{e['i_op_pu']:.3f}", f"{e['i_rest_pu']:.3f}", f"{e['i_threshold_pu']:.3f}", e['status']])
        amp_col_width = 70
        results_col_widths = [45] + [amp_col_width] * len(winding_names) + [60, 60, 70, 85]
    else:
        results_header = ["Phase", "I_op [pu]", "I_rest [pu]", "Threshold [pu]", "Status"]
        results_rows = []
        for p in phases:
            e = evals[p]
            results_rows.append([p, f"{e['i_op_pu']:.3f}", f"{e['i_rest_pu']:.3f}", f"{e['i_threshold_pu']:.3f}", e['status']])
        results_col_widths = (90, 90, 90, 100, 150)

    return build_pdf_report(
        report_title, meta_text,
        sections=[("Transformer Parameters", transformer_rows), ("Relay Parameters", relay_rows)]
                 + _settings_sheet_sections(settings_sheets),
        results_header=results_header, results_rows=results_rows, results_col_widths=results_col_widths,
    )


def generate_motor_pdf_report(unit_name, relay_obj, eval_result, test_current_amps,
                               backup_relay_obj=None, backup_eval_result=None,
                               approval=None, coordination_checks=None, settings_sheets=None):
    """Motor 50/50/51 time-overcurrent (IFC66KD2A) report — built on the same
    shared build_pdf_report(). Single test-current evaluation (this relay
    is single-phase A & C, not a 3-phase differential), with an optional
    second section for the backup 50 (HFC22B2A) instantaneous relay.
    settings_sheets: optional list of (relay_type_label, rows) tuples - see
    _settings_sheet_sections()."""
    report_title = f"Motor Time-Overcurrent Protection (50/50/51) Evaluation Report - {unit_name}"
    meta_text = f"<b>Date/Time:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | <b>Configuration:</b> {unit_name}"

    motor_rows = [
        ["Parameter", "Value"],
        ["CT Ratio", f"{relay_obj.ct_ratio:.0f}:{relay_obj.ct_secondary_rating:.0f}"],
    ]
    if relay_obj.motor_fla is not None:
        motor_rows.append(["Motor Full Load Current", f"{relay_obj.motor_fla:.0f} A"])
    if relay_obj.locked_rotor_amps is not None:
        motor_rows.append(["Locked Rotor Current", f"{relay_obj.locked_rotor_amps:.0f} A"])

    relay_rows = [
        ["Parameter", "Value"],
        ["Relay Type", "GE IFC66KD2A (GEK-49949)"],
        ["51 Tap", f"{relay_obj.tap_51:.2f} A sec."],
        ["51 Time Dial", f"{relay_obj.time_dial:.2f}"],
        ["50A Pickup (Instantaneous)", f"{relay_obj.pickup_50a:.2f} A sec."],
        ["50B Dropout (Overload Alarm)", f"{relay_obj.dropout_50b:.2f} A sec."],
        ["Target & Seal-in", f"{relay_obj.target_seal_in:.2f} A"],
    ]

    results_header = ["Test Current (Pri A)", "Relay Sec. (A)", "51 Multiple", "51 Trip Time", "Status"]
    t51_str = f"{eval_result['t51']:.2f}s" if eval_result["t51"] is not None else "No Trip"
    results_rows = [[
        f"{test_current_amps:.1f}",
        f"{eval_result['i_relay_sec']:.3f}",
        f"{eval_result['multiple_of_pickup_51']:.2f}x",
        t51_str,
        eval_result["status"],
    ]]

    sections = [("Motor Data", motor_rows), ("Relay Parameters (50/50/51)", relay_rows)]

    if backup_relay_obj is not None and backup_eval_result is not None:
        backup_rows = [
            ["Parameter", "Value"],
            ["Relay Type", "GE HFC22B2A (GEK-49826C)"],
            ["CT Ratio", f"{backup_relay_obj.ct_ratio:.0f}:{backup_relay_obj.ct_secondary_rating:.0f}"],
            ["50 Pickup", f"{backup_relay_obj.pickup_amps:.2f} A sec."],
            ["Relay Secondary Current at Test", f"{backup_eval_result['i_relay_sec']:.3f} A"],
            ["Status", backup_eval_result["status"]],
        ]
        sections.append(("Backup Instantaneous Relay (50)", backup_rows))

    if coordination_checks:
        coordination_rows = [["Check", "Result"]]
        for check in coordination_checks:
            result = "PASS" if check["passed"] else "REVIEW REQUIRED"
            coordination_rows.append([check["label"], f"{result} — {check['detail']}"])
        sections.append(("Coordination Checks", coordination_rows))

    if approval:
        approval_rows = [
            ["Parameter", "Value"],
            ["Source Document", approval.get("source_document", "Not recorded")],
            ["Revision", approval.get("revision", "Not recorded")],
            ["Prepared By", approval.get("prepared_by", "Not recorded")],
            ["Reviewed By", approval.get("reviewed_by", "Not recorded")],
            ["Approval Status", approval.get("approval_status", "Not recorded")],
            ["Review Note", approval.get("review_note", "None")],
        ]
        sections.append(("Document Control and Approval", approval_rows))

    sections += _settings_sheet_sections(settings_sheets)

    return build_pdf_report(
        report_title, meta_text,
        sections=sections,
        results_header=results_header, results_rows=results_rows,
        results_col_widths=(90, 90, 80, 90, 150),
    )


def generate_fan_motor_pdf_report(unit_name, relay_obj, eval_result, gf_eval, unbal_eval,
                                   test_current_amps, ground_current_amps, unbalance_pct,
                                   approval=None, settings_sheets=None):
    """SR469 MPR motor report (Primary Air Fan / FD Fan) - covers only what this app
    models for these motors (the SR469 static MPR); a separate discrete 50/50/51
    electromechanical relay documented in these motors' settings docs is not covered
    here.
    settings_sheets: optional list of (relay_type_label, rows) tuples - see
    _settings_sheet_sections()."""
    report_title = f"Fan Motor Protection (SR469 MPR) Evaluation Report - {unit_name}"
    meta_text = f"<b>Date/Time:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | <b>Configuration:</b> {unit_name}"

    motor_rows = [
        ["Parameter", "Value"],
        ["CT Ratio", f"{relay_obj.ct_ratio:.0f}:{relay_obj.ct_secondary_rating:.0f}"],
        ["Motor Full Load Current", f"{relay_obj.motor_fla:.0f} A"],
        ["Ground CT Ratio", f"{relay_obj.ground_ct_ratio:.0f}:{relay_obj.ground_ct_secondary_rating:.0f}"],
    ]

    relay_rows = [
        ["Parameter", "Value"],
        ["Relay Type", "Multilin SR469 MPR"],
        ["Overload Pickup", f"{relay_obj.overload_pickup_pct:.0f}% FLA"],
        ["Curve Multiplier (CM)", f"{relay_obj.curve_multiplier:.1f}"],
        ["Instantaneous Pickup", f"{relay_obj.inst_pickup_amps:.0f} A primary"],
        ["Instantaneous Delay", f"{relay_obj.inst_delay_ms:.0f} ms"],
        ["Ground Fault Pickup", f"{relay_obj.gf_pickup_amps:.2f} A (ground CT primary)"],
        ["Ground Fault Delay", f"{relay_obj.gf_delay_ms:.0f} ms"],
        ["Unbalance Alarm / Trip", f"{relay_obj.unbal_alarm_pct:.0f}% / {relay_obj.unbal_trip_pct:.0f}%"],
        ["Mechanical Jam Pickup", f"{relay_obj.mech_jam_pct:.0f}% FLA, {relay_obj.mech_jam_delay_s:.1f}s delay"],
    ]

    results_header = ["Input", "Value", "Relay Sec. (A)", "Multiple/Level", "Status"]
    t51_str = f"{eval_result['t51']:.2f}s" if eval_result["t51"] is not None else "No Trip"
    results_rows = [
        ["Phase Current (A primary)", f"{test_current_amps:.1f}", f"{eval_result['i_relay_sec']:.3f}",
         f"{eval_result['multiple_of_fla']:.2f}x FLA / {t51_str}", eval_result["status"]],
        ["Ground Current (A primary)", f"{ground_current_amps:.1f}", "—", "—", gf_eval["status"]],
        ["Current Unbalance (%)", f"{unbalance_pct:.1f}", "—", "—", unbal_eval["status"]],
    ]

    sections = [("Motor Data", motor_rows), ("Relay Parameters (SR469 MPR)", relay_rows)]

    if approval:
        approval_rows = [
            ["Parameter", "Value"],
            ["Source Document", approval.get("source_document", "Not recorded")],
            ["Revision", approval.get("revision", "Not recorded")],
            ["Prepared By", approval.get("prepared_by", "Not recorded")],
            ["Reviewed By", approval.get("reviewed_by", "Not recorded")],
            ["Approval Status", approval.get("approval_status", "Not recorded")],
            ["Review Note", approval.get("review_note", "None")],
        ]
        sections.append(("Document Control and Approval", approval_rows))

    sections += _settings_sheet_sections(settings_sheets)

    return build_pdf_report(
        report_title, meta_text,
        sections=sections,
        results_header=results_header, results_rows=results_rows,
        results_col_widths=(120, 70, 90, 130, 130),
    )


def generate_custom_relay_pdf_report(unit_name, relay, results, test_inputs, approval=None, settings_sheets=None):
    """User-assembled generic relay (engines/custom_relay.CustomRelay) report.

    results: relay.evaluate(...)'s return dict (tag -> {multiple, trip_time, is_trip, status}).
    test_inputs: dict with whichever of i_phase_primary/i_ground_primary/i_diff_primary/
        unbalance_pct were used for this evaluation - only elements present in `results`
        are reported.
    settings_sheets: optional list of (relay_type_label, rows) tuples - see
    _settings_sheet_sections()."""
    report_title = f"Custom Relay Protection Evaluation Report - {unit_name}"
    meta_text = f"<b>Date/Time:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | <b>Configuration:</b> {unit_name}"

    relay_rows = [["Parameter", "Value"], ["CT Ratio", f"{relay.ct_ratio:.0f}:{relay.ct_secondary_rating:.0f}"]]
    if relay.ground_ct_ratio:
        relay_rows.append(["Ground CT Ratio", f"{relay.ground_ct_ratio:.0f}:{relay.ground_ct_secondary_rating:.0f}"])

    element_rows = [["Element", "Parameter", "Value"]]
    for tag, el in relay.elements.items():
        label = relay.ELEMENT_LABELS[tag]
        if tag in ("51", "51G"):
            element_rows += [
                [label, "Pickup", f"{el['pickup_sec']:.2f} A sec."],
                [label, "Curve", el["curve"]],
                [label, "Time Dial / TMS", f"{el['time_dial']:.2f}"],
            ]
        elif tag in ("50", "50G"):
            element_rows += [
                [label, "Pickup", f"{el['pickup_sec']:.2f} A sec."],
                [label, "Delay", f"{el['delay_ms']:.0f} ms"],
            ]
        elif tag == "87":
            element_rows.append([label, "Pickup", f"{el['pickup_primary']:.1f} A primary"])
        elif tag == "46":
            element_rows += [
                [label, "Alarm Pickup / Delay", f"{el['alarm_pct']:.0f}% / {el['alarm_delay_s']:.0f}s"],
                [label, "Trip Pickup / Delay", f"{el['trip_pct']:.0f}% / {el['trip_delay_s']:.0f}s"],
            ]

    results_header = ["Element", "Test Input", "Multiple", "Status"]
    results_rows = []
    input_labels = {
        "51": f"{test_inputs.get('i_phase_primary', 0):.1f} A primary",
        "50": f"{test_inputs.get('i_phase_primary', 0):.1f} A primary",
        "51G": f"{test_inputs.get('i_ground_primary', 0):.1f} A primary",
        "50G": f"{test_inputs.get('i_ground_primary', 0):.1f} A primary",
        "87": f"{test_inputs.get('i_diff_primary', 0):.1f} A primary",
        "46": f"{test_inputs.get('unbalance_pct', 0):.1f} %",
    }
    for tag, r in results.items():
        multiple_str = f"{r['multiple']:.2f}x" if r["multiple"] is not None else "—"
        results_rows.append([relay.ELEMENT_LABELS[tag], input_labels.get(tag, "—"), multiple_str, r["status"]])

    sections = [("Relay Settings", relay_rows), ("Protection Elements", element_rows)]

    if approval:
        approval_rows = [
            ["Parameter", "Value"],
            ["Source Document", approval.get("source_document", "Not recorded")],
            ["Revision", approval.get("revision", "Not recorded")],
            ["Prepared By", approval.get("prepared_by", "Not recorded")],
            ["Reviewed By", approval.get("reviewed_by", "Not recorded")],
            ["Approval Status", approval.get("approval_status", "Not recorded")],
            ["Review Note", approval.get("review_note", "None")],
        ]
        sections.append(("Document Control and Approval", approval_rows))

    sections += _settings_sheet_sections(settings_sheets)

    return build_pdf_report(
        report_title, meta_text,
        sections=sections,
        results_header=results_header, results_rows=results_rows,
        results_col_widths=(160, 110, 80, 130),
    )


def generate_fmea_pdf_report(rows, categories):
    """FMEA (Failure Mode and Effects Analysis) report, views/fmea.py.

    Not built on build_pdf_report()'s results table: that table wraps only its
    header cells in Paragraph, leaving body cells as plain unwrapped strings -
    fine for the short numeric/verdict values every other report's results table
    holds, but FMEA's Category/Component/Failure Mode/Effect/Diagnostics/
    Maintenance Task columns are long free text that would overflow into
    neighboring columns unwrapped. This builds its own landscape table with
    every cell (header and body) wrapped in Paragraph. Includes Diagnostics and
    Maintenance Task/Frequency per the supervisor's requirement that the report
    show not just what can fail, but how it's detected and what maintenance
    response it calls for - deliberately omits Potential Cause and Recommended
    Action (present in the CSV/JSON export, which has no page-width constraint)
    to keep the columns readable on one landscape page.

    rows: list of dicts with keys Category, Component, Failure Category, Failure
        Mode, Potential Effect, Diagnostics, S, O, D, RPN, Risk, Maintenance Task,
        Frequency (the same shape views/fmea.py already builds for its on-screen
        table). Failure Category is the root-cause branch (Hardware Failure /
        Software Defects / Measurement Errors / Wiring Problems / Environment)
        from the supervisor-supplied failure-cause diagram for digital relays.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter),
                             rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor("#1E3A8A"))
    story.append(Paragraph("FMEA — Digital Protection Relays", title_style))
    story.append(Spacer(1, 6))
    meta_text = (
        f"<b>Generated:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
        f"<b>Relay families:</b> {', '.join(categories)} | <b>{len(rows)} failure mode(s)</b>"
    )
    story.append(Paragraph(meta_text, styles['Normal']))
    story.append(Spacer(1, 12))

    cell_style = ParagraphStyle('FmeaCell', parent=styles['Normal'], fontSize=7.5, leading=9)
    header_style = ParagraphStyle('FmeaHeader', parent=styles['Normal'], fontSize=8, leading=10,
                                   textColor=colors.white, fontName='Helvetica-Bold', alignment=1)

    columns = ["Category", "Component", "Failure Category", "Failure Mode", "Potential Effect",
               "Diagnostics", "S", "O", "D", "RPN", "Risk", "Maintenance Task", "Frequency"]
    col_widths = (58, 58, 62, 74, 90, 74, 16, 16, 16, 26, 32, 70, 40)

    table_data = [[Paragraph(c, header_style) for c in columns]]
    for r in rows:
        table_data.append([
            Paragraph(str(r.get(c, "")), cell_style) for c in columns
        ])

    t = Table(table_data, colWidths=list(col_widths), repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))
    story.append(t)

    doc.build(story)
    buffer.seek(0)
    return buffer
