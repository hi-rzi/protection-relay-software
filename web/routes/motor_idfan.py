import csv
import io
import json

from flask import Blueprint, Response, jsonify, render_template, request

from common.pdf_report import generate_motor_pdf_report
from web.presets.motor_idfan import PRESETS, TAP_51_OPTIONS, CT_SEC_OPTIONS
from web.services import idfan as svc

bp = Blueprint("motor_idfan", __name__, url_prefix="")


@bp.route("/motor/idfan")
def page():
    default_preset_name = list(PRESETS.keys())[0]
    default_settings = PRESETS[default_preset_name]

    initial_data = {
        "presets": PRESETS,
        "default_preset_name": default_preset_name,
        "tap_51_options": TAP_51_OPTIONS,
        "ct_sec_options": CT_SEC_OPTIONS,
    }

    return render_template(
        "motor_idfan.html",
        presets=PRESETS,
        default_preset_name=default_preset_name,
        default_settings=default_settings,
        tap_51_options=TAP_51_OPTIONS,
        ct_sec_options=CT_SEC_OPTIONS,
        has_fault_current=False,
        initial_data_json=json.dumps(initial_data),
    )


@bp.route("/api/motor/idfan/recompute", methods=["POST"])
def recompute():
    payload = request.get_json(force=True, silent=True) or {}
    result = svc.recompute(payload)
    return jsonify(result)


@bp.route("/api/motor/idfan/settings-sheet.csv", methods=["POST"])
def settings_sheet_csv():
    payload = request.get_json(force=True, silent=True) or {}
    settings = payload.get("settings", {})

    relay = svc.build_relay(settings)
    backup_relay = svc.build_backup_relay(settings)
    diff87m_relay = svc.build_diff87m_relay(settings)

    main_rows = svc.settings_sheet_rows_main(relay, backup_relay)
    diff87m_rows = svc.settings_sheet_rows_87m(diff87m_relay)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["IFC66KD2A Relay Settings"])
    writer.writerow(["Parameter", "Value"])
    writer.writerows(main_rows)
    writer.writerow([])
    writer.writerow(["GE HFC23C1A (87M) Settings"])
    writer.writerow(["Parameter", "Value"])
    writer.writerows(diff87m_rows)
    csv_bytes = buf.getvalue().encode("utf-8")

    return Response(
        csv_bytes, mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=IDFan_Settings_Sheet.csv"},
    )


@bp.route("/api/motor/idfan/report.pdf", methods=["POST"])
def report_pdf():
    payload = request.get_json(force=True, silent=True) or {}
    settings = payload.get("settings", {})
    unit_name = payload.get("selected_preset", "ID Fan")

    relay = svc.build_relay(settings)
    backup_relay = svc.build_backup_relay(settings)
    diff87m_relay = svc.build_diff87m_relay(settings)

    default_test_current = float(settings.get("motor_fla", 0) or 0)
    try:
        test_current = float(payload.get("test_current")) if payload.get("test_current") is not None else default_test_current
    except (TypeError, ValueError):
        test_current = default_test_current
    diff87m_test_imbalance = float(payload.get("diff87m_test_imbalance", 0.0) or 0.0)

    ev = svc.evaluate(relay, backup_relay, diff87m_relay, test_current, diff87m_test_imbalance)
    checks = svc.compute_checks(settings, relay, backup_relay, diff87m_relay)

    approval = payload.get("approval")

    pdf_buf = generate_motor_pdf_report(
        unit_name, relay, ev["result"], test_current,
        backup_relay_obj=backup_relay, backup_eval_result=ev["backup_result"],
        approval=approval, coordination_checks=checks["checks_summary"] if approval else None,
    )

    return Response(
        pdf_buf.getvalue(), mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=IDFan_Motor_Protection_Report.pdf"},
    )
