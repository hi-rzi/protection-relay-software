"""
ID Fan (Induced Draft Fan) Motor Protection calculation glue for the Flask
reference page. Ports the arithmetic from views/motor_idfan.py's script body
into plain functions that take a JSON-friendly settings dict in and return
JSON-friendly dicts out — no Streamlit, no session_state.

Reuses engines/motor.py (MotorTimeOvercurrentRelay, BackupInstantaneousRelay)
and engines/motor_differential.py (SelfBalancingDifferentialRelay) UNCHANGED.
This is a standalone relay engine, distinct from PA/FD Fan's SR469 (Motor869)
pattern — the two pages only share engines/motor.py's classes, not any glue
code here.
"""
import numpy as np

from engines.motor import MotorTimeOvercurrentRelay, BackupInstantaneousRelay
from engines.motor_differential import SelfBalancingDifferentialRelay

M_RANGE_MIN = 1.01
M_RANGE_MAX = 20.0
M_RANGE_N = 400


def _f(d, key, default=0.0):
    v = d.get(key, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _b(d, key, default=True):
    v = d.get(key, default)
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "0", "no", "")
    return bool(v)


# ---------------------------------------------------------------------------
# Relay construction
# ---------------------------------------------------------------------------
def build_relay(settings):
    return MotorTimeOvercurrentRelay(
        ct_ratio=_f(settings, "ct_ratio"),
        ct_secondary_rating=_f(settings, "ct_sec", 5.0),
        tap_51=_f(settings, "tap_51"),
        time_dial=_f(settings, "time_dial"),
        pickup_50a=_f(settings, "pickup_50a"),
        dropout_50b=_f(settings, "dropout_50b"),
        target_seal_in=_f(settings, "target_seal_in", 0.2),
        motor_fla=_f(settings, "motor_fla"),
        locked_rotor_amps=_f(settings, "locked_rotor_amps"),
    )


def build_backup_relay(settings):
    if not _b(settings, "enable_backup", True):
        return None
    return BackupInstantaneousRelay(
        ct_ratio=_f(settings, "backup_ct_ratio"),
        ct_secondary_rating=_f(settings, "ct_sec", 5.0),
        pickup_amps=_f(settings, "backup_pickup_50"),
    )


def build_diff87m_relay(settings):
    return SelfBalancingDifferentialRelay(
        ct_ratio=_f(settings, "diff87m_ct_ratio"),
        ct_secondary_rating=_f(settings, "ct_sec", 5.0),
        pickup_amps_sec=_f(settings, "diff87m_pickup_sec"),
    )


# ---------------------------------------------------------------------------
# Current Settings tab — live pickup/margin checks
# (mirrors views/motor_idfan.py lines 283-448)
# ---------------------------------------------------------------------------
def compute_checks(settings, relay, backup_relay, diff87m_relay):
    motor_fla = _f(settings, "motor_fla")
    locked_rotor_amps = _f(settings, "locked_rotor_amps")
    accel_time_100 = _f(settings, "accel_time_100")
    accel_time_80 = _f(settings, "accel_time_80")
    safe_stall_100 = _f(settings, "safe_stall_100_hot")
    safe_stall_80 = _f(settings, "safe_stall_80_hot")

    pickup_51_primary = relay.tap_51 * relay.effective_ratio
    pickup_50a_primary = relay.pickup_50a * relay.effective_ratio
    pickup_50b_primary = relay.pickup_50b * relay.effective_ratio
    backup_pickup_primary = (backup_relay.pickup_amps * backup_relay.effective_ratio) if backup_relay is not None else None
    diff87m_pickup_primary = diff87m_relay.pickup_amps_primary
    diff87m_ok = abs(diff87m_pickup_primary - 20.0) < 0.5

    t_at_lrc_100 = relay.calculate_51_trip_time(relay.relay_current(locked_rotor_amps))
    t_at_lrc_80 = relay.calculate_51_trip_time(relay.relay_current(_f(settings, "locked_rotor_amps_80pct")))
    ok_100 = t_at_lrc_100 is not None and accel_time_100 < t_at_lrc_100 < safe_stall_100
    ok_80 = t_at_lrc_80 is not None and accel_time_80 < t_at_lrc_80 < safe_stall_80

    # "Engineering Input Checks" (Live Simulation tab, lines 606-644)
    checks_live = [
        {
            "label": "51 pickup above motor FLA",
            "passed": pickup_51_primary > motor_fla,
            "detail": f"51 pickup = {pickup_51_primary:.0f} A primary ({(pickup_51_primary / motor_fla if motor_fla else 0):.2f}x FLA)",
            "review_note": "51 pickup is at or below motor FLA; review overload coordination.",
        },
        {
            "label": "50A pickup above locked-rotor current",
            "passed": pickup_50a_primary > locked_rotor_amps,
            "detail": f"50A pickup = {pickup_50a_primary:.0f} A primary ({(pickup_50a_primary / locked_rotor_amps if locked_rotor_amps else 0):.2f}x LRC)",
            "review_note": "50A pickup is at or below locked-rotor current; a normal start could trip instantaneously.",
        },
        {
            "label": "50B alarm pickup above motor FLA",
            "passed": pickup_50b_primary > motor_fla,
            "detail": f"50B estimated pickup = {pickup_50b_primary:.0f} A primary ({(pickup_50b_primary / motor_fla if motor_fla else 0):.2f}x FLA)",
            "review_note": "50B alarm pickup is at or below motor FLA; review the overload-alarm setting.",
        },
        {
            "label": "100% voltage safe-stall time exceeds acceleration time",
            "passed": safe_stall_100 > accel_time_100,
            "detail": f"Acceleration = {accel_time_100:.1f} s; safe stall = {safe_stall_100:.1f} s",
            "review_note": "The 100% voltage safe-stall time is not greater than the acceleration time.",
        },
        {
            "label": "80% voltage safe-stall time exceeds acceleration time",
            "passed": safe_stall_80 > accel_time_80,
            "detail": f"Acceleration = {accel_time_80:.1f} s; safe stall = {safe_stall_80:.1f} s",
            "review_note": "The 80% voltage safe-stall time is not greater than the acceleration time.",
        },
    ]
    if backup_pickup_primary is not None:
        checks_live.append({
            "label": "Backup 50 pickup above locked-rotor current",
            "passed": backup_pickup_primary > locked_rotor_amps,
            "detail": f"Backup 50 pickup = {backup_pickup_primary:.0f} A primary ({(backup_pickup_primary / locked_rotor_amps if locked_rotor_amps else 0):.2f}x LRC)",
            "review_note": "Backup 50 pickup is at or below locked-rotor current; review starting security and coordination.",
        })

    # "Coordination Review" (Settings Summary & Approval tab, lines 1074-1101)
    trip_time_100 = f"{t_at_lrc_100:.1f} s" if t_at_lrc_100 is not None else "No trip"
    trip_time_80 = f"{t_at_lrc_80:.1f} s" if t_at_lrc_80 is not None else "No trip"
    checks_summary = [
        {
            "label": "51 pickup above motor FLA",
            "passed": pickup_51_primary > motor_fla,
            "detail": f"{pickup_51_primary:.0f} A primary versus {motor_fla:.0f} A FLA",
        },
        {
            "label": "50A pickup above locked-rotor current",
            "passed": pickup_50a_primary > locked_rotor_amps,
            "detail": f"{pickup_50a_primary:.0f} A primary versus {locked_rotor_amps:.0f} A LRC",
        },
        {
            "label": "51 coordination at 100% voltage",
            "passed": ok_100,
            "detail": f"Start {accel_time_100:.1f} s / trip {trip_time_100} / safe stall {safe_stall_100:.1f} s",
        },
        {
            "label": "51 coordination at 80% voltage",
            "passed": ok_80,
            "detail": f"Start {accel_time_80:.1f} s / trip {trip_time_80} / safe stall {safe_stall_80:.1f} s",
        },
    ]
    if backup_pickup_primary is not None:
        checks_summary.append({
            "label": "Backup 50 pickup above locked-rotor current",
            "passed": backup_pickup_primary > locked_rotor_amps,
            "detail": f"{backup_pickup_primary:.0f} A primary versus {locked_rotor_amps:.0f} A LRC",
        })

    all_clear = (
        pickup_51_primary > motor_fla
        and pickup_50a_primary > locked_rotor_amps
        and pickup_50b_primary > motor_fla
        and safe_stall_100 > accel_time_100
        and safe_stall_80 > accel_time_80
        and ok_100 and ok_80
        and (backup_pickup_primary is None or backup_pickup_primary > locked_rotor_amps)
        and diff87m_ok
    )

    return {
        "pickup_51_primary": pickup_51_primary,
        "pickup_50a_primary": pickup_50a_primary,
        "pickup_50b_primary": pickup_50b_primary,
        "backup_pickup_primary": backup_pickup_primary,
        "diff87m_pickup_primary": diff87m_pickup_primary,
        "diff87m_ok": diff87m_ok,
        "t_at_lrc_100": t_at_lrc_100,
        "t_at_lrc_80": t_at_lrc_80,
        "ok_100": ok_100,
        "ok_80": ok_80,
        "checks_live": checks_live,
        "checks_summary": checks_summary,
        "all_clear": all_clear,
    }


def ideal_tap_51(settings):
    """Mirrors lines 318-322: ideal tap ~= FLA + 15%, snapped to nearest discrete tap."""
    from web.presets.motor_idfan import TAP_51_OPTIONS
    motor_fla = _f(settings, "motor_fla")
    ct_ratio = _f(settings, "ct_ratio")
    ct_sec = _f(settings, "ct_sec", 5.0)
    i_sec_at_fla = (motor_fla / ct_ratio * ct_sec) if ct_ratio > 0 else 0.0
    ideal = i_sec_at_fla * 1.15
    nearest = min(TAP_51_OPTIONS, key=lambda t: abs(t - ideal))
    return {"ideal_tap_51": ideal, "nearest_tap_51": nearest}


# ---------------------------------------------------------------------------
# 51 curve (used by both the Current Settings live-preview mini chart and the
# TCC Curve & Test Points tab's main trace) — mirrors lines 213-217 / 760-762.
# ---------------------------------------------------------------------------
def curve_51(relay):
    m_range = np.linspace(M_RANGE_MIN, M_RANGE_MAX, M_RANGE_N)
    t_range = [relay.calculate_51_trip_time(float(m) * relay.tap_51) for m in m_range]
    x_amps = (m_range * relay.tap_51 * relay.effective_ratio).tolist()
    return {"m": m_range.tolist(), "t": t_range, "x_amps": x_amps}


def tcc_data(settings, relay, backup_relay):
    """Mirrors views/motor_idfan.py lines 749-819 — vertical-line thresholds and
    motor starting/safe-stall marker points, in both 'multiple of tap' and
    primary-amps units so the client can toggle without another round trip."""
    locked_rotor_amps = _f(settings, "locked_rotor_amps")
    locked_rotor_amps_80 = _f(settings, "locked_rotor_amps_80pct")
    accel_time_100 = _f(settings, "accel_time_100")
    accel_time_80 = _f(settings, "accel_time_80")
    safe_stall_100 = _f(settings, "safe_stall_100_hot")
    safe_stall_80 = _f(settings, "safe_stall_80_hot")

    x_50a_amps = relay.pickup_50a * relay.effective_ratio
    x_50a_multiple = relay.pickup_50a / relay.tap_51 if relay.tap_51 else 0.0
    x_50b_amps = relay.pickup_50b * relay.effective_ratio
    x_50b_multiple = relay.pickup_50b / relay.tap_51 if relay.tap_51 else 0.0

    x_backup_amps = None
    x_backup_multiple = None
    if backup_relay is not None:
        x_backup_amps = backup_relay.pickup_amps * backup_relay.effective_ratio
        x_backup_multiple = (x_backup_amps / relay.tap_51 / relay.effective_ratio) if (relay.tap_51 and relay.effective_ratio) else 0.0

    lrc_100_multiple = relay.relay_current(locked_rotor_amps) / relay.tap_51 if relay.tap_51 else 0.0
    lrc_80_multiple = relay.relay_current(locked_rotor_amps_80) / relay.tap_51 if relay.tap_51 else 0.0

    return {
        "x_50a_amps": x_50a_amps, "x_50a_multiple": x_50a_multiple,
        "x_50b_amps": x_50b_amps, "x_50b_multiple": x_50b_multiple,
        "x_backup_amps": x_backup_amps, "x_backup_multiple": x_backup_multiple,
        "lrc_100_amps": locked_rotor_amps, "lrc_100_multiple": lrc_100_multiple,
        "lrc_80_amps": locked_rotor_amps_80, "lrc_80_multiple": lrc_80_multiple,
        "accel_time_100": accel_time_100, "accel_time_80": accel_time_80,
        "safe_stall_100": safe_stall_100, "safe_stall_80": safe_stall_80,
    }


# ---------------------------------------------------------------------------
# Live Simulation tab — single test-current evaluation (lines 512-682)
# ---------------------------------------------------------------------------
def evaluate(relay, backup_relay, diff87m_relay, test_current, diff87m_test_imbalance):
    eval_result = relay.evaluate_protection(test_current)
    backup_result = backup_relay.evaluate_protection(test_current) if backup_relay is not None else None
    diff87m_result = diff87m_relay.evaluate_protection(diff87m_test_imbalance)
    return {
        "test_current": test_current,
        "diff87m_test_imbalance": diff87m_test_imbalance,
        "result": eval_result,
        "backup_result": backup_result,
        "diff87m_result": diff87m_result,
    }


# ---------------------------------------------------------------------------
# Commissioning & Injection tab (lines 687-744)
# ---------------------------------------------------------------------------
def injection_calc(relay, target_multiple):
    inj_sec_amps = target_multiple * relay.tap_51
    inj_pri_amps = inj_sec_amps * relay.effective_ratio
    expected_t = relay.calculate_51_trip_time(inj_sec_amps)
    return {"inj_sec_amps": inj_sec_amps, "inj_pri_amps": inj_pri_amps, "expected_t": expected_t}


def sweep_table(relay, sweep_start, sweep_end, sweep_step):
    if sweep_end <= sweep_start or sweep_step <= 0:
        return None
    points = np.arange(sweep_start, sweep_end + sweep_step / 2.0, sweep_step)
    rows = []
    for m in points:
        sec_amps = float(m) * relay.tap_51
        t = relay.calculate_51_trip_time(sec_amps)
        rows.append({
            "multiple": round(float(m), 3),
            "inject_sec_a": round(sec_amps, 3),
            "equivalent_primary_a": round(sec_amps * relay.effective_ratio, 1),
            "trip_time_s": round(t, 3) if t is not None else None,
        })
    return rows


# ---------------------------------------------------------------------------
# Fault Clearing Time Simulation (TCC tab, lines 828-1021)
# ---------------------------------------------------------------------------
def fault_clearing_sim(relay, fault_scenario, relay_operate_cycles, breaker_cycles, motor_fla, locked_rotor_amps):
    cycle_ms = 1000.0 / 60.0
    preload_current = motor_fla
    if str(fault_scenario).startswith("Locked"):
        sim_current = locked_rotor_amps
    else:
        sim_current = relay.pickup_50a * relay.effective_ratio * 1.5

    sim_eval = relay.evaluate_protection(sim_current)
    result = {
        "sim_current": sim_current,
        "preload_current": preload_current,
        "status": sim_eval["status"],
    }
    if sim_eval["trip_50a"]:
        relay_ms = relay_operate_cycles * cycle_ms
        total_ms = relay_ms + breaker_cycles * cycle_ms
        result.update({"kind": "trip", "relay_ms": relay_ms, "total_ms": total_ms, "log_x": False})
    elif sim_eval["trip_51"]:
        relay_ms = sim_eval["t51"] * 1000.0
        total_ms = relay_ms + breaker_cycles * cycle_ms
        result.update({"kind": "trip_51", "relay_ms": relay_ms, "total_ms": total_ms, "log_x": True})
    else:
        result.update({"kind": "no_trip", "window_ms": 200.0})
    return result


# ---------------------------------------------------------------------------
# Settings Summary & Approval tab — settings sheet rows (lines 663-682)
# TWO separate sheets in the Streamlit source (IFC66KD2A main relay +
# GE HFC23C1A 87M) — both are returned, never silently dropped.
# ---------------------------------------------------------------------------
def settings_sheet_rows_main(relay, backup_relay):
    rows = [
        ("CT Ratio", f"{relay.ct_ratio:.0f}:{relay.ct_secondary_rating:.0f}"),
        ("51 Tap (A sec.)", f"{relay.tap_51:.2f}"),
        ("51 Time Dial", f"{relay.time_dial:.2f}"),
        ("50A Pickup (A sec.)", f"{relay.pickup_50a:.2f}"),
        ("50B Dropout (A sec.)", f"{relay.dropout_50b:.2f}"),
        ("Target & Seal-in (A)", f"{relay.target_seal_in:.2f}"),
    ]
    if backup_relay is not None:
        rows += [
            ("Backup 50 CT Ratio", f"{backup_relay.ct_ratio:.0f}:{relay.ct_secondary_rating:.0f}"),
            ("Backup 50 Pickup (A sec.)", f"{backup_relay.pickup_amps:.2f}"),
        ]
    return rows


def settings_sheet_rows_87m(diff87m_relay):
    return [
        ("87M CT Ratio", f"{diff87m_relay.ct_ratio:.0f}:{diff87m_relay.ct_secondary_rating:.0f}"),
        ("87M Pickup (A sec.)", f"{diff87m_relay.pickup_amps_sec:.2f}"),
        ("87M Tap", "High" if diff87m_relay.pickup_amps_sec >= 2.0 else "Low"),
    ]


# ---------------------------------------------------------------------------
# Master recompute — mirrors today's Streamlit behavior of recomputing
# everything on every rerun regardless of active tab.
# ---------------------------------------------------------------------------
def recompute(payload):
    settings = payload.get("settings", {})

    relay = build_relay(settings)
    backup_relay = build_backup_relay(settings)
    diff87m_relay = build_diff87m_relay(settings)

    checks = compute_checks(settings, relay, backup_relay, diff87m_relay)
    tap_info = ideal_tap_51(settings)
    curve = curve_51(relay)
    tcc = tcc_data(settings, relay, backup_relay)

    default_test_current = _f(settings, "motor_fla")
    try:
        test_current = float(payload.get("test_current")) if payload.get("test_current") is not None else default_test_current
    except (TypeError, ValueError):
        test_current = default_test_current
    diff87m_test_imbalance = _f(payload, "diff87m_test_imbalance", 0.0)
    ev = evaluate(relay, backup_relay, diff87m_relay, test_current, diff87m_test_imbalance)

    out = {
        "effective_ratio": relay.effective_ratio,
        "backup_effective_ratio": backup_relay.effective_ratio if backup_relay is not None else None,
        "diff87m_effective_ratio": diff87m_relay.effective_ratio,
        "pickup_50b": relay.pickup_50b,
        "enable_backup": backup_relay is not None,
        "checks": checks,
        "tap_info": tap_info,
        "curve": curve,
        "tcc": tcc,
        "eval": ev,
    }

    injection_req = payload.get("injection")
    if injection_req:
        out["injection"] = injection_calc(relay, float(injection_req.get("target_multiple", 3.9)))

    sweep_req = payload.get("sweep")
    if sweep_req:
        out["sweep"] = sweep_table(
            relay,
            float(sweep_req.get("sweep_start", 1.5)),
            float(sweep_req.get("sweep_end", 10.0)),
            float(sweep_req.get("sweep_step", 0.5)),
        )

    fault_sim_req = payload.get("fault_sim")
    if fault_sim_req:
        out["fault_sim"] = fault_clearing_sim(
            relay,
            fault_sim_req.get("fault_scenario", "Locked Rotor / Stall"),
            float(fault_sim_req.get("relay_operate_cycles", 1.0)),
            float(fault_sim_req.get("breaker_cycles", 5.0)),
            _f(settings, "motor_fla"),
            _f(settings, "locked_rotor_amps"),
        )

    return out
