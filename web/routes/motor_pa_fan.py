import csv
import io
import json

from flask import Blueprint, Response, jsonify, render_template, request

from common.pdf_report import generate_fan_motor_pdf_report
from web.presets.motor_pa_fan import PRESETS
from web.services import pa_fan as svc

bp = Blueprint("motor_pa_fan", __name__, url_prefix="")


@bp.route("/motor/pa-fan")
def page():
    default_preset_name = list(PRESETS.keys())[0]
    default_settings = PRESETS[default_preset_name]

    initial_data = {
        "presets": PRESETS,
        "default_preset_name": default_preset_name,
    }

    return render_template(
        "motor_pa_fan.html",
        presets=PRESETS,
        default_preset_name=default_preset_name,
        default_settings=default_settings,
        has_fault_current=False,
        initial_data_json=json.dumps(initial_data),
    )


@bp.route("/api/motor/pa-fan/recompute", methods=["POST"])
def recompute():
    payload = request.get_json(force=True, silent=True) or {}
    result = svc.recompute(payload)
    return jsonify(result)


@bp.route("/api/motor/pa-fan/settings-sheet.csv", methods=["POST"])
def settings_sheet_csv():
    payload = request.get_json(force=True, silent=True) or {}
    settings = payload.get("settings", {})
    relay = svc.build_relay(settings)
    diff87m_relay = svc.build_diff87m(settings)
    rows = svc.settings_sheet_rows(settings, relay)
    rows_87m = svc.settings_sheet_rows_87m(settings, diff87m_relay)

    rows_all = list(rows) + [("", "")] + list(rows_87m)
    if all(k in settings and settings.get(k) not in (None, "") for k in ("ifc_tap51", "ifc_td")):
        ifc_relay = svc.build_ifc_relay(settings)
        ifc_backup_relay = svc.build_ifc_backup_relay(settings)
        rows_ifc = svc.ifc_settings_sheet_rows(settings, ifc_relay, ifc_backup_relay)
        rows_all += [("", "")] + list(rows_ifc)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Parameter", "Value"])
    writer.writerows(rows_all)
    csv_bytes = buf.getvalue().encode("utf-8")

    return Response(
        csv_bytes, mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=PA_Fan_Settings_Sheet.csv"},
    )


@bp.route("/api/motor/pa-fan/report.pdf", methods=["POST"])
def report_pdf():
    payload = request.get_json(force=True, silent=True) or {}
    settings = payload.get("settings", {})
    unit_name = payload.get("selected_preset", "PA Fan")
    test_current = float(payload.get("test_current", settings.get("fla", 0.0)) or 0.0)
    ground_current = float(payload.get("ground_current", 0.0) or 0.0)
    unbalance_pct = float(payload.get("unbalance_pct", 0.0) or 0.0)
    approval = payload.get("approval")

    relay = svc.build_relay(settings)
    eval_result = relay.evaluate_protection(test_current)
    gf_eval = relay.evaluate_ground_fault(ground_current)
    unbal_eval = relay.evaluate_unbalance(unbalance_pct)

    pdf_buf = generate_fan_motor_pdf_report(
        f"Primary Air (PA) Fan - {unit_name}", relay, eval_result, gf_eval, unbal_eval,
        test_current, ground_current, unbalance_pct, approval=approval,
    )

    return Response(
        pdf_buf.getvalue(), mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=PA_Fan_Protection_Report.pdf"},
    )
