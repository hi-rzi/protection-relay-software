"""
Shared calculation glue for the two 6.9kV combustion-air fan motor pages (PA
Fan, FD Fan) - both use a Multilin SR469 static motor protection relay
(modeled via engines/motor_869.py's Motor869Relay, same TCU thermal-curve
architecture as the GE 869) plus a GE HFC23C1A self-balancing differential
(87M, engines/motor_differential.py). Ports the shared arithmetic from
common/motor_fan_page.py's script body into plain functions that take a
JSON-friendly settings dict in and return JSON-friendly dicts out - no
Streamlit, no session_state.

web/services/pa_fan.py and web/services/fd_fan.py both import from here.
pa_fan.py additionally layers on its own IFC66KD2A 50/50/51 + HFC22B2A
backup functions (engines/motor.py) - not shared, since FD Fan doesn't have
that relay stack.
"""
import numpy as np

from engines.motor_869 import Motor869Relay
from engines.motor_differential import SelfBalancingDifferentialRelay


def _f(d, key, default=0.0):
    v = d.get(key, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def build_relay(settings):
    ct_sec = _f(settings, "ct_sec", 5.0)
    return Motor869Relay(
        ct_ratio=_f(settings, "ct_ratio"),
        ct_secondary_rating=ct_sec,
        motor_fla=_f(settings, "fla"),
        overload_pickup_pct=_f(settings, "ovl_pct", 115.0),
        curve_multiplier=_f(settings, "cm", 4.0),
        inst_pickup_multiple_of_ct=_f(settings, "inst_ct", 8.0),
        inst_delay_ms=_f(settings, "inst_delay", 60.0),
        ground_ct_ratio=_f(settings, "gct_ratio", 50.0),
        ground_ct_secondary_rating=ct_sec,
        gf_pickup_frac_of_ct=_f(settings, "gf_frac", 0.1),
        gf_delay_ms=_f(settings, "gf_delay", 60.0),
        unbal_alarm_pct=_f(settings, "unb_alarm_pct", 15.0),
        unbal_alarm_delay_s=_f(settings, "unb_alarm_delay", 10.0),
        unbal_trip_pct=_f(settings, "unb_trip_pct", 30.0),
        unbal_trip_delay_s=_f(settings, "unb_trip_delay", 60.0),
        mech_jam_pct=_f(settings, "jam_pct", 150.0),
        mech_jam_delay_s=_f(settings, "jam_delay", 1.0),
        accel_timer_s=_f(settings, "accel", 20.0),
        overload_alarm_delay_s=_f(settings, "ovl_alarm_delay", 1.0),
    )


def build_diff87m(settings):
    return SelfBalancingDifferentialRelay(
        ct_ratio=_f(settings, "diff87m_ct_ratio", 50.0),
        ct_secondary_rating=_f(settings, "ct_sec", 5.0),
        pickup_amps_sec=_f(settings, "diff87m_pickup_sec", 2.0),
    )


def has_stall_data(settings):
    return all(k in settings and settings.get(k) not in (None, "") for k in (
        "lrc_100", "lrc_80", "accel_100", "accel_80", "stall_100", "stall_80",
    ))


def overload_curve(relay, motor_fla, max_mult=None):
    """Overload (51) TCC — trip time vs multiple of motor FLA."""
    if max_mult is None:
        max_mult = 6.0
    mult = np.linspace(1.01, max_mult, 300)
    t = [relay.calculate_overload_trip_time(m * motor_fla) for m in mult]
    return {"mult": mult.tolist(), "t": t}


def stall_margin_check(relay, settings):
    """Mirrors views' Starting/Stall Margin Check block. Returns None if the
    motor has no starting/stall data on record (Custom Profile w/o it)."""
    if not has_stall_data(settings):
        return None
    lrc_100 = _f(settings, "lrc_100")
    lrc_80 = _f(settings, "lrc_80")
    accel_100 = _f(settings, "accel_100")
    accel_80 = _f(settings, "accel_80")
    stall_100 = _f(settings, "stall_100")
    stall_80 = _f(settings, "stall_80")

    t_100 = relay.calculate_overload_trip_time(lrc_100)
    t_80 = relay.calculate_overload_trip_time(lrc_80)
    ok_100 = t_100 is not None and accel_100 < t_100 < stall_100
    ok_80 = t_80 is not None and accel_80 < t_80 < stall_80
    motor_fla = relay.motor_fla
    return {
        "lrc_100": lrc_100, "lrc_80": lrc_80,
        "lrc_100_x": (lrc_100 / motor_fla) if motor_fla else None,
        "lrc_80_x": (lrc_80 / motor_fla) if motor_fla else None,
        "accel_100": accel_100, "accel_80": accel_80,
        "stall_100": stall_100, "stall_80": stall_80,
        "t_100": t_100, "t_80": t_80,
        "ok_100": ok_100, "ok_80": ok_80,
    }


def evaluate_all(relay, diff87m_relay, test_current, ground_current, unbalance_pct, diff87m_test_imbalance):
    eval_result = relay.evaluate_protection(test_current)
    gf_eval = relay.evaluate_ground_fault(ground_current)
    unbal_eval = relay.evaluate_unbalance(unbalance_pct)
    diff87m_result = diff87m_relay.evaluate_protection(diff87m_test_imbalance)
    any_trip = eval_result["is_trip"] or gf_eval["is_trip"] or unbal_eval["is_trip"] or diff87m_result["is_trip"]
    return {
        "eval": eval_result, "gf_eval": gf_eval, "unbal_eval": unbal_eval,
        "diff87m_eval": diff87m_result, "any_trip": any_trip,
    }


def injection_calc(relay, motor_fla, target_multiple):
    inj_pri_amps = target_multiple * motor_fla
    inj_sec_amps = relay.relay_current(inj_pri_amps)
    expected_t = relay.calculate_overload_trip_time(inj_pri_amps)
    return {"inj_pri_amps": inj_pri_amps, "inj_sec_amps": inj_sec_amps, "expected_t": expected_t}


def sweep_table(relay, motor_fla, sweep_start, sweep_end, sweep_step):
    if sweep_end <= sweep_start or sweep_step <= 0:
        return None
    points = np.arange(sweep_start, sweep_end + sweep_step / 2.0, sweep_step)
    rows = []
    for m in points:
        pri_amps = float(m) * motor_fla
        t = relay.calculate_overload_trip_time(pri_amps)
        rows.append({
            "multiple": round(float(m), 3),
            "primary_a": round(pri_amps, 1),
            "secondary_a": round(relay.relay_current(pri_amps), 3),
            "trip_time_s": round(t, 3) if t is not None else None,
        })
    return rows


def fault_clearing_sim(relay, motor_fla, settings, fault_scenario, breaker_cycles):
    """Mirrors views' Fault Clearing Time Simulation (motor_fan_page.py lines
    ~910-1095) — simplified to a single-shot result (no client-side step
    animation, matching this page's server-side recompute pattern)."""
    cycle_ms = 1000.0 / 60.0
    preload_current = motor_fla
    stall = stall_margin_check(relay, settings)
    if fault_scenario.startswith("Locked") and stall is not None:
        sim_current = stall["lrc_100"]
    else:
        sim_current = relay.inst_pickup_amps * 1.5
    sim_eval = relay.evaluate_protection(sim_current)

    result = {
        "status": sim_eval["status"], "sim_current": sim_current, "preload_current": preload_current,
    }
    if sim_eval["trip_50"]:
        relay_ms = relay.inst_delay_ms
        total_ms = relay_ms + breaker_cycles * cycle_ms
        result.update({"kind": "trip", "relay_ms": relay_ms, "total_ms": total_ms})
    elif sim_eval["trip_51"]:
        relay_ms = sim_eval["t51"] * 1000.0
        total_ms = relay_ms + breaker_cycles * cycle_ms
        result.update({"kind": "trip_51", "relay_ms": relay_ms, "total_ms": total_ms})
    else:
        result.update({"kind": "no_trip", "window_ms": 200.0})
    return result


def settings_sheet_rows(settings, relay):
    """Mirrors render_settings_sheet(st, "Multilin SR469", [...]) rows from
    common/motor_fan_page.py."""
    ct_sec = _f(settings, "ct_sec", 5.0)
    return [
        ("CT Ratio", f"{relay.ct_ratio:.0f}:{ct_sec:.0f}"),
        ("Ground CT Ratio", f"{relay.ground_ct_ratio:.0f}:{ct_sec:.0f}"),
        ("Overload Pickup (% FLA)", f"{relay.overload_pickup_pct:.0f}"),
        ("Curve Multiplier (CM)", f"{relay.curve_multiplier:.1f}"),
        ("Instantaneous Pickup (x CT sec.)", f"{_f(settings, 'inst_ct', 8.0):.1f}"),
        ("Instantaneous Delay (ms)", f"{relay.inst_delay_ms:.0f}"),
        ("Ground Fault Pickup (x Ground CT)", f"{_f(settings, 'gf_frac', 0.1):.2f}"),
        ("Ground Fault Delay (ms)", f"{relay.gf_delay_ms:.0f}"),
        ("Unbalance Alarm/Trip (%)", f"{relay.unbal_alarm_pct:.0f} / {relay.unbal_trip_pct:.0f}"),
        ("Mechanical Jam Pickup (% FLA)", f"{relay.mech_jam_pct:.0f}"),
    ]


def settings_sheet_rows_87m(settings, diff87m_relay):
    ct_sec = _f(settings, "ct_sec", 5.0)
    pickup_sec = _f(settings, "diff87m_pickup_sec", 2.0)
    return [
        ("87M CT Ratio", f"{diff87m_relay.ct_ratio:.0f}:{ct_sec:.0f}"),
        ("87M Pickup (A sec.)", f"{pickup_sec:.2f}"),
        ("87M Tap", "High" if pickup_sec >= 2.0 else "Low"),
    ]


def coordination_checks(relay, settings):
    """Mirrors the Settings Summary & Approval tab's Coordination Review."""
    motor_fla = relay.motor_fla
    checks = [
        {
            "label": "Instantaneous pickup above motor FLA",
            "passed": relay.inst_pickup_amps > motor_fla,
            "detail": f"{relay.inst_pickup_amps:.0f} A primary versus {motor_fla:.0f} A FLA",
        },
        {
            "label": "Overload pickup above 100% FLA",
            "passed": relay.overload_pickup_pct > 100.0,
            "detail": f"Overload pickup set at {relay.overload_pickup_pct:.0f}% FLA",
        },
    ]
    return checks


def recompute_common(payload, extra_all_clear_checks=None):
    """Full shared recompute — mirrors motor_fan_page.py recomputing
    everything on every rerun regardless of active tab. `payload` is the
    posted settings JSON. `extra_all_clear_checks` lets pa_fan.py fold its
    IFC66KD2A all-clear flag into the overall status without duplicating
    this function."""
    settings = payload.get("settings", {})
    relay = build_relay(settings)
    diff87m_relay = build_diff87m(settings)

    test_current = _f(payload, "test_current", relay.motor_fla)
    ground_current = _f(payload, "ground_current", 0.0)
    unbalance_pct = _f(payload, "unbalance_pct", 0.0)
    diff87m_test_imbalance = _f(payload, "diff87m_test_imbalance", 0.0)

    ev = evaluate_all(relay, diff87m_relay, test_current, ground_current, unbalance_pct, diff87m_test_imbalance)

    stall = stall_margin_check(relay, settings)
    max_mult = max(6.0, ev["eval"]["multiple_of_fla"] + 1.0)
    if stall is not None and stall["lrc_100_x"] is not None:
        max_mult = max(max_mult, stall["lrc_100_x"] + 1.0)
    curve = overload_curve(relay, relay.motor_fla, max_mult=max_mult)

    diff87m_pickup_primary = diff87m_relay.pickup_amps_primary
    diff87m_ok = abs(diff87m_pickup_primary - 20.0) < 0.5

    checks = coordination_checks(relay, settings)
    all_pass = all(c["passed"] for c in checks)
    stall_ok = stall is None or (stall["ok_100"] and stall["ok_80"])
    unb_ok = relay.unbal_trip_pct >= relay.unbal_alarm_pct

    extra_ok = True
    if extra_all_clear_checks is not None:
        extra_ok = extra_all_clear_checks(settings, relay)

    all_clear = all_pass and stall_ok and unb_ok and diff87m_ok and extra_ok

    out = {
        "motor_fla": relay.motor_fla,
        "ct_ratio": relay.ct_ratio, "ct_sec": relay.ct_secondary_rating,
        "ground_ct_ratio": relay.ground_ct_ratio,
        "inst_pickup_amps": relay.inst_pickup_amps,
        "gf_pickup_amps": relay.gf_pickup_amps,
        "diff87m_pickup_primary": diff87m_pickup_primary,
        "diff87m_ok": diff87m_ok,
        "eval": ev["eval"], "gf_eval": ev["gf_eval"], "unbal_eval": ev["unbal_eval"],
        "diff87m_eval": ev["diff87m_eval"], "any_trip": ev["any_trip"],
        "tcc_curve": curve,
        "stall": stall,
        "checks": checks,
        "unb_ok": unb_ok,
        "all_clear": all_clear,
        "test_current": test_current, "ground_current": ground_current,
        "unbalance_pct": unbalance_pct, "diff87m_test_imbalance": diff87m_test_imbalance,
    }

    inj = payload.get("injection")
    if inj:
        out["injection"] = injection_calc(relay, relay.motor_fla, _f(inj, "target_multiple", 3.9))

    sweep_req = payload.get("sweep")
    if sweep_req:
        out["sweep"] = sweep_table(
            relay, relay.motor_fla,
            _f(sweep_req, "sweep_start", 1.5), _f(sweep_req, "sweep_end", 6.0), _f(sweep_req, "sweep_step", 0.5),
        )

    fault_sim_req = payload.get("fault_sim")
    if fault_sim_req:
        out["fault_sim"] = fault_clearing_sim(
            relay, relay.motor_fla, settings,
            fault_sim_req.get("fault_scenario", "Short-Circuit Fault"),
            _f(fault_sim_req, "breaker_cycles", 5.0),
        )

    return out, relay, diff87m_relay
