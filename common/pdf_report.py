import datetime
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
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


def generate_generator_pdf_report(unit_name, relay_obj, evals, phases, inputs=None):
    """Generator (87G) report — output is identical to the original monolithic
    generate_pdf_report(), now built on top of the shared build_pdf_report().

    inputs: optional {phase: {"i_N": ..., "i_T": ...}} — when supplied, the
    Neutral/Terminal primary Amps actually entered for each phase are added
    to the results table, not just the derived pu values."""
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
        sections=[("Generator Parameters", generator_rows), ("Relay Parameters", relay_rows)],
        results_header=results_header, results_rows=results_rows, results_col_widths=results_col_widths,
    )


def generate_transformer_pdf_report(unit_name, relay_obj, evals, phases, relay_type_label="CAC1-10-M3", winding_currents=None):
    """Transformer differential (87T) report — built on the same shared
    build_pdf_report() used for the Generator report. Works for any winding
    count (2-winding EXCT/GSUT, 3-winding Overall).

    winding_currents: optional {phase: [primary_amps, ...]}, aligned in order
    with relay_obj.windings — when supplied, each winding's primary Amps
    actually entered for that phase are added to the results table."""
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
        sections=[("Transformer Parameters", transformer_rows), ("Relay Parameters", relay_rows)],
        results_header=results_header, results_rows=results_rows, results_col_widths=results_col_widths,
    )


def generate_motor_pdf_report(unit_name, relay_obj, eval_result, test_current_amps,
                               backup_relay_obj=None, backup_eval_result=None,
                               approval=None, coordination_checks=None):
    """Motor 50/50/51 time-overcurrent (IFC66KD2A) report — built on the same
    shared build_pdf_report(). Single test-current evaluation (this relay
    is single-phase A & C, not a 3-phase differential), with an optional
    second section for the backup 50 (HFC22B2A) instantaneous relay."""
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

    return build_pdf_report(
        report_title, meta_text,
        sections=sections,
        results_header=results_header, results_rows=results_rows,
        results_col_widths=(90, 90, 80, 90, 150),
    )
