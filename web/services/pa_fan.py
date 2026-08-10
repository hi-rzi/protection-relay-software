"""
PA Fan (Primary Air Fan) service glue for the Flask page. Wires the shared
SR469/87M logic in fan_motor_common.py, PLUS this motor's own separate
discrete GE IFC66KD2A 50/50/51 electromechanical relay and GE HFC22B2A
backup instantaneous relay (confirmed present per PAFAN MOTOR PROTECTION.pdf
Section 5.3.1/5.3.2 — NOT modeled for the FD Fan, see web/services/fd_fan.py).
"""
import numpy as np

from engines.motor import MotorTimeOvercurrentRelay, BackupInstantaneousRelay
from web.services import fan_motor_common as common

build_relay = common.build_relay
build_diff87m = common.build_diff87m
settings_sheet_rows = common.settings_sheet_rows
settings_sheet_rows_87m = common.settings_sheet_rows_87m
_f = common._f


def build_ifc_relay(settings):
    return MotorTimeOvercurrentRelay(
        ct_ratio=_f(settings, "ct_ratio"),
        ct_secondary_rating=_f(settings, "ct_sec", 5.0),
        tap_51=_f(settings, "ifc_tap51", 4.0),
        time_dial=_f(settings, "ifc_td", 4.0),
        pickup_50a=_f(settings, "ifc_50a", 50.0),
        dropout_50b=_f(settings, "ifc_50b", 3.0),
        target_seal_in=_f(settings, "ifc_target", 0.2),
        motor_fla=_f(settings, "fla"),
        locked_rotor_amps=_f(settings, "lrc_100") if settings.get("lrc_100") not in (None, "") else None,
    )


def build_ifc_backup_relay(settings):
    if not settings.get("ifc_backup_en", True):
        return None
    return BackupInstantaneousRelay(
        ct_ratio=_f(settings, "ifc_backup_ct", 2000.0),
        ct_secondary_rating=_f(settings, "ct_sec", 5.0),
        pickup_amps=_f(settings, "ifc_backup_pickup", 7.5),
    )


def ifc_stall_margin_check(ifc_relay, settings):
    if not common.has_stall_data(settings):
        return None
    lrc_100 = _f(settings, "lrc_100")
    lrc_80 = _f(settings, "lrc_80")
    accel_100 = _f(settings, "accel_100")
    accel_80 = _f(settings, "accel_80")
    stall_100 = _f(settings, "stall_100")
    stall_80 = _f(settings, "stall_80")

    t_100 = ifc_relay.calculate_51_trip_time(ifc_relay.relay_current(lrc_100))
    t_80 = ifc_relay.calculate_51_trip_time(ifc_relay.relay_current(lrc_80))
    ok_100 = t_100 is not None and accel_100 < t_100 < stall_100
    ok_80 = t_80 is not None and accel_80 < t_80 < stall_80
    return {
        "lrc_100": lrc_100, "lrc_80": lrc_80,
        "lrc_100_x": ifc_relay.relay_current(lrc_100) / ifc_relay.tap_51 if ifc_relay.tap_51 else None,
        "lrc_80_x": ifc_relay.relay_current(lrc_80) / ifc_relay.tap_51 if ifc_relay.tap_51 else None,
        "accel_100": accel_100, "accel_80": accel_80,
        "stall_100": stall_100, "stall_80": stall_80,
        "t_100": t_100, "t_80": t_80,
        "ok_100": ok_100, "ok_80": ok_80,
    }


def ifc_curve(ifc_relay):
    m_range = np.linspace(1.01, 20.0, 400)
    t_range = [ifc_relay.calculate_51_trip_time(m * ifc_relay.tap_51) for m in m_range]
    return {"mult": m_range.tolist(), "t": t_range}


def ifc_settings_sheet_rows(settings, ifc_relay, ifc_backup_relay):
    ct_sec = _f(settings, "ct_sec", 5.0)
    rows = [
        ("CT Ratio", f"{ifc_relay.ct_ratio:.0f}:{ct_sec:.0f}"),
        ("51 Tap (A sec.)", f"{ifc_relay.tap_51:.2f}"),
        ("51 Time Dial", f"{ifc_relay.time_dial:.2f}"),
        ("50A Pickup (A sec.)", f"{ifc_relay.pickup_50a:.2f}"),
        ("50B Dropout (A sec.)", f"{ifc_relay.dropout_50b:.2f}"),
        ("Target & Seal-in (A)", f"{ifc_relay.target_seal_in:.2f}"),
    ]
    if ifc_backup_relay is not None:
        rows += [
            ("Backup 50 CT Ratio", f"{ifc_backup_relay.ct_ratio:.0f}:{ct_sec:.0f}"),
            ("Backup 50 Pickup (A sec.)", f"{ifc_backup_relay.pickup_amps:.2f}"),
        ]
    return rows


def _ifc_all_clear(settings, relay):
    ifc_relay = build_ifc_relay(settings)
    ifc_backup_relay = build_ifc_backup_relay(settings)
    ifc_effective_ratio = ifc_relay.effective_ratio
    motor_fla = relay.motor_fla
    ifc_pickup_51_primary = ifc_relay.tap_51 * ifc_effective_ratio
    ifc_pickup_50a_primary = ifc_relay.pickup_50a * ifc_effective_ratio
    ifc_pickup_50b_primary = ifc_relay.pickup_50b * ifc_effective_ratio

    stall = ifc_stall_margin_check(ifc_relay, settings)
    if stall is None:
        return ifc_pickup_51_primary > motor_fla and ifc_pickup_50b_primary > motor_fla

    lrc_100 = stall["lrc_100"]
    ok = (
        ifc_pickup_51_primary > motor_fla
        and stall["ok_100"] and stall["ok_80"]
        and ifc_pickup_50a_primary > lrc_100
        and ifc_pickup_50b_primary > motor_fla
    )
    if ifc_backup_relay is not None:
        ifc_backup_pickup_primary = ifc_backup_relay.pickup_amps * ifc_backup_relay.effective_ratio
        ok = ok and ifc_backup_pickup_primary > lrc_100
    return ok


def recompute(payload):
    out, relay, diff87m_relay = common.recompute_common(payload, extra_all_clear_checks=_ifc_all_clear)

    settings = payload.get("settings", {})
    ifc_relay = build_ifc_relay(settings)
    ifc_backup_relay = build_ifc_backup_relay(settings)

    test_current = out["test_current"]
    ifc_eval = ifc_relay.evaluate_protection(test_current)
    ifc_backup_eval = ifc_backup_relay.evaluate_protection(test_current) if ifc_backup_relay else None

    ifc_effective_ratio = ifc_relay.effective_ratio
    ifc_out = {
        "eval": ifc_eval,
        "backup_eval": ifc_backup_eval,
        "curve": ifc_curve(ifc_relay),
        "stall": ifc_stall_margin_check(ifc_relay, settings),
        "tap_51": ifc_relay.tap_51, "time_dial": ifc_relay.time_dial,
        "pickup_50a": ifc_relay.pickup_50a, "dropout_50b": ifc_relay.dropout_50b,
        "pickup_50b": ifc_relay.pickup_50b, "target_seal_in": ifc_relay.target_seal_in,
        "pickup_51_primary": ifc_relay.tap_51 * ifc_effective_ratio,
        "pickup_50a_primary": ifc_relay.pickup_50a * ifc_effective_ratio,
        "pickup_50b_primary": ifc_relay.pickup_50b * ifc_effective_ratio,
        "x_50a": ifc_relay.pickup_50a / ifc_relay.tap_51 if ifc_relay.tap_51 else None,
        "x_50b": ifc_relay.pickup_50b / ifc_relay.tap_51 if ifc_relay.tap_51 else None,
        "backup_enabled": ifc_backup_relay is not None,
    }
    if ifc_backup_relay is not None:
        ifc_out["backup_ct_ratio"] = ifc_backup_relay.ct_ratio
        ifc_out["backup_pickup_amps"] = ifc_backup_relay.pickup_amps
        ifc_out["backup_pickup_primary"] = ifc_backup_relay.pickup_amps * ifc_backup_relay.effective_ratio
        ifc_out["x_backup"] = (
            (ifc_backup_relay.pickup_amps * ifc_backup_relay.effective_ratio) / ifc_relay.tap_51 / ifc_effective_ratio
            if ifc_relay.tap_51 and ifc_effective_ratio else None
        )

    out["ifc"] = ifc_out
    return out
