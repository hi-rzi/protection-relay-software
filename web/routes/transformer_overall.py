import csv
import io
import json

from flask import Blueprint, Response, jsonify, render_template, request

from common.pdf_report import generate_transformer_pdf_report
from web.presets.transformer_overall import PRESETS, MR_CT_TAPS_2000_5
from web.services import overall as svc

bp = Blueprint("transformer_overall", __name__, url_prefix="")

PHASES = svc.PHASES
WINDING_NAMES = svc.WINDING_NAMES


@bp.route("/transformer/overall")
def page():
    default_preset_name = list(PRESETS.keys())[0]
    default_settings = PRESETS[default_preset_name]

    initial_data = {
        "presets": PRESETS,
        "default_preset_name": default_preset_name,
        "mr_ct_taps_2000_5": MR_CT_TAPS_2000_5,
        "winding_names": WINDING_NAMES,
    }

    return render_template(
        "transformer_overall.html",
        presets=PRESETS,
        default_preset_name=default_preset_name,
        default_settings=default_settings,
        mr_ct_taps_2000_5=MR_CT_TAPS_2000_5,
        winding_names=WINDING_NAMES,
        has_fault_current=False,
        initial_data_json=json.dumps(initial_data),
    )


@bp.route("/api/transformer/overall/recompute", methods=["POST"])
def recompute():
    payload = request.get_json(force=True, silent=True) or {}
    result = svc.recompute(payload)
    return jsonify(result)


@bp.route("/api/transformer/overall/settings-sheet.csv", methods=["POST"])
def settings_sheet_csv():
    payload = request.get_json(force=True, silent=True) or {}
    settings = payload.get("settings", {})
    convention = str(payload.get("convention", "IEEE")).upper()
    ct_polarity = str(payload.get("ct_polarity", "OPPOSITE")).upper()
    relay = svc.build_relay(settings, convention, ct_polarity)
    rows = svc.settings_sheet_rows(settings, relay, convention, ct_polarity)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Parameter", "Value"])
    writer.writerows(rows)
    csv_bytes = buf.getvalue().encode("utf-8")

    return Response(
        csv_bytes, mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=Overall_GSUT-GEN_Settings_Sheet.csv"},
    )


@bp.route("/api/transformer/overall/report.pdf", methods=["POST"])
def report_pdf():
    payload = request.get_json(force=True, silent=True) or {}
    settings = payload.get("settings", {})
    convention = str(payload.get("convention", "IEEE")).upper()
    ct_polarity = str(payload.get("ct_polarity", "OPPOSITE")).upper()
    unit_name = payload.get("selected_preset", "Overall GSUT-GEN")
    phase_inputs = payload.get("phase_inputs") or {}

    relay = svc.build_relay(settings, convention, ct_polarity)
    if not phase_inputs:
        phase_inputs = svc.default_phase_a_angles(relay, ct_polarity)
    evals = svc.evaluate_phases(relay, phase_inputs)
    winding_currents = {
        p: [
            float(phase_inputs.get(p, {}).get("i_hv", 0.0)),
            float(phase_inputs.get(p, {}).get("i_gen", 0.0)),
            float(phase_inputs.get(p, {}).get("i_uat", 0.0)),
        ]
        for p in PHASES
    }

    pdf_buf = generate_transformer_pdf_report(
        unit_name, relay, evals, PHASES, relay_type_label="CAC2-10-M3", winding_currents=winding_currents,
    )

    return Response(
        pdf_buf.getvalue(), mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=Overall_GSUT-GEN_Protection_Report.pdf"},
    )
