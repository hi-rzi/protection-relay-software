import csv
import io
import json

from flask import Blueprint, Response, jsonify, render_template, request

from common.pdf_report import generate_generator_pdf_report
from web.presets.generator import PRESETS, MODE_LABELS
from web.services import generator as svc

bp = Blueprint("generator", __name__, url_prefix="")

PHASES = svc.PHASES
DEFAULT_MODE = "GENERATOR"


@bp.route("/generator")
def page():
    default_mode = DEFAULT_MODE
    default_preset_name = list(PRESETS[default_mode].keys())[0]
    default_settings = PRESETS[default_mode][default_preset_name]
    default_legacy_preset_name = list(PRESETS["GENERATOR_LEGACY"].keys())[0]
    default_settings_legacy = PRESETS["GENERATOR_LEGACY"][default_legacy_preset_name]

    initial_data = {
        "presets": PRESETS,
        "default_mode": default_mode,
        "default_preset_name": default_preset_name,
        "mode_labels": MODE_LABELS,
    }

    return render_template(
        "generator.html",
        presets=PRESETS[default_mode],
        default_preset_name=default_preset_name,
        default_settings=default_settings,
        default_settings_legacy=default_settings_legacy,
        default_mode=default_mode,
        presets_by_mode=PRESETS,
        has_fault_current=True,
        initial_data_json=json.dumps(initial_data),
    )


@bp.route("/api/generator/recompute", methods=["POST"])
def recompute():
    payload = request.get_json(force=True, silent=True) or {}
    result = svc.recompute(payload)
    return jsonify(result)


@bp.route("/api/generator/settings-sheet.csv", methods=["POST"])
def settings_sheet_csv():
    payload = request.get_json(force=True, silent=True) or {}
    settings = payload.get("settings", {})
    mode = svc.normalize_mode(payload.get("mode", DEFAULT_MODE))
    convention = str(payload.get("convention", "IEEE")).upper()
    ct_polarity = str(payload.get("ct_polarity", "SAME")).upper()
    relay = svc.build_relay(settings, mode, convention, ct_polarity)
    rows = svc.settings_sheet_rows(settings, relay, mode, convention, ct_polarity)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Parameter", "Value"])
    writer.writerows(rows)
    csv_bytes = buf.getvalue().encode("utf-8")

    return Response(
        csv_bytes, mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=Generator_Settings_Sheet.csv"},
    )


@bp.route("/api/generator/report.pdf", methods=["POST"])
def report_pdf():
    payload = request.get_json(force=True, silent=True) or {}
    settings = payload.get("settings", {})
    mode = svc.normalize_mode(payload.get("mode", DEFAULT_MODE))
    convention = str(payload.get("convention", "IEEE")).upper()
    ct_polarity = str(payload.get("ct_polarity", "SAME")).upper()
    unit_name = payload.get("selected_preset", "Generator")
    phase_inputs = payload.get("phase_inputs") or {}

    relay = svc.build_relay(settings, mode, convention, ct_polarity)
    if not phase_inputs:
        phase_inputs = svc.default_phase_a_angles(relay, ct_polarity)
    evals = svc.evaluate_phases(relay, phase_inputs)
    inputs = {
        p: {
            "i_N": float(phase_inputs.get(p, {}).get("i_N", 0.0)),
            "i_T": float(phase_inputs.get(p, {}).get("i_T", 0.0)),
        }
        for p in PHASES
    }

    pdf_buf = generate_generator_pdf_report(unit_name, relay, evals, PHASES, inputs=inputs)

    return Response(
        pdf_buf.getvalue(), mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=Generator_Differential_Protection_Report.pdf"},
    )
