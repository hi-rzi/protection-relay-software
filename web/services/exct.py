"""
EXCT (Excitation Transformer, 2-winding CAC1-10-M3 differential relay)
calculation glue for the Flask reference page. Ports the arithmetic from
views/transformer_exct.py's script body into plain functions that take a
JSON-friendly settings dict in and return JSON-friendly dicts out — no
Streamlit, no session_state.

Reuses engines/transformer.py and engines/fault_current.py UNCHANGED.

Difference from web/services/gsut.py: EXCT's settings doc doesn't use a
tap-adjusted HV voltage distinct from the fault-current base (GSUT/UAT do —
their kv_hv is tap-corrected while a separate fault_kv_hv holds the nameplate
value). EXCT's kv_hv IS the nameplate voltage already, so compute_fault_current
here uses settings' kv_hv/kv_lv directly, with no fault_kv_hv field at all —
matching views/transformer_exct.py lines 841-842 exactly.
"""
import math

import numpy as np

from engines.transformer import (
    TransformerDifferentialRelay,
    winding_internal_vector,
    raw_input_for_internal_vector,
    solve_healthy_target_angle,
)
from engines.fault_current import transformer_through_fault_current, relay_secondary_at_fault
from common.settings_advisor import suggest_ct_matching_tap, mismatch_ratio_pct, suggest_bias_settings

PHASES = ["Phase A", "Phase B", "Phase C"]


def _f(d, key, default=0.0):
    v = d.get(key, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def build_windings(settings):
    return [
        {
            "name": "HV (23kV)",
            "kv": _f(settings, "kv_hv"),
            "ct_ratio": _f(settings, "ct_hv"),
            "ct_secondary_rating": _f(settings, "ct_sec", 5.0),
            "tap": _f(settings, "tap_hv", 1.0),
            "ct_connection": str(settings.get("ct_conn_hv", "DELTA")).upper(),
        },
        {
            "name": "LV (900V)",
            "kv": _f(settings, "kv_lv"),
            "ct_ratio": _f(settings, "ct_lv"),
            "ct_secondary_rating": _f(settings, "ct_sec", 5.0),
            "tap": _f(settings, "tap_lv", 1.0),
            "ct_connection": str(settings.get("ct_conn_lv", "WYE")).upper(),
        },
    ]


def build_relay(settings, convention="IEEE", ct_polarity="OPPOSITE"):
    windings = build_windings(settings)
    return TransformerDifferentialRelay(
        mva_rated=_f(settings, "mva"),
        windings=windings,
        bias_pct=_f(settings, "bias", 20),
        min_operate_pct=_f(settings, "min_operate", 20),
        hoc_multiple=_f(settings, "hoc", 5),
        convention=convention, ct_polarity=ct_polarity,
    )


def compute_mismatch(settings):
    """Mirrors lines 192-235 of views/transformer_exct.py — CT matching tap
    reference (T_E, informational) and the actual live mismatch % at the
    currently-set taps (the real pass/fail signal)."""
    mva = _f(settings, "mva")
    kv_hv = _f(settings, "kv_hv")
    kv_lv = _f(settings, "kv_lv")
    ct_hv = _f(settings, "ct_hv")
    ct_lv = _f(settings, "ct_lv")
    ct_sec = _f(settings, "ct_sec", 5.0)
    tap_hv = _f(settings, "tap_hv", 1.0)
    tap_lv = _f(settings, "tap_lv", 1.0)
    ct_conn_hv = str(settings.get("ct_conn_hv", "DELTA")).upper()
    ct_conn_lv = str(settings.get("ct_conn_lv", "WYE")).upper()

    delta_factor_hv = 1.7320508 if ct_conn_hv == "DELTA" else 1.0
    delta_factor_lv = 1.7320508 if ct_conn_lv == "DELTA" else 1.0
    i_rated_pri_hv = (mva * 1000.0) / (1.7320508 * kv_hv) if kv_hv > 0 else 0.0
    i_rated_pri_lv = (mva * 1000.0) / (1.7320508 * kv_lv) if kv_lv > 0 else 0.0

    t1_e = suggest_ct_matching_tap(i_rated_pri_hv, ct_hv, ct_sec, delta_factor_hv)
    t2_e = suggest_ct_matching_tap(i_rated_pri_lv, ct_lv, ct_sec, delta_factor_lv)

    i_relay_hv_at_set_tap = (i_rated_pri_hv / (ct_hv / ct_sec) * delta_factor_hv * tap_hv) if ct_hv > 0 and ct_sec > 0 else None
    i_relay_lv_at_set_tap = (i_rated_pri_lv / (ct_lv / ct_sec) * delta_factor_lv * tap_lv) if ct_lv > 0 and ct_sec > 0 else None
    calc_mismatch = mismatch_ratio_pct([i_relay_hv_at_set_tap, i_relay_lv_at_set_tap])

    suggestion = suggest_bias_settings(calc_mismatch or 0.0, num_windings=2)

    bias_pct = _f(settings, "bias", 20)
    min_operate_pct = _f(settings, "min_operate", 20)

    all_clear = (
        calc_mismatch is not None
        and calc_mismatch < 5.0
        and bias_pct >= suggestion["bias_pct"]
        and min_operate_pct >= suggestion["min_operate_pct"]
    )

    return {
        "t1_e": t1_e,
        "t2_e": t2_e,
        "calc_mismatch_pct": calc_mismatch,
        "suggestion": suggestion,
        "all_clear": all_clear,
        "effective_ratio_hv": f"{ct_hv:.0f}:{ct_sec:.0f}" if ct_sec else "-",
        "effective_ratio_hv_ratio": (ct_hv / ct_sec) if ct_sec else None,
        "effective_ratio_lv": f"{ct_lv:.0f}:{ct_sec:.0f}" if ct_sec else "-",
        "effective_ratio_lv_ratio": (ct_lv / ct_sec) if ct_sec else None,
    }


def bias_curve(relay, max_x=None, n=400):
    """Theoretical CAL. line, per-unit — matches views/transformer_exct.py's
    Live Simulation bias-curve x/y arrays, pu only (the frontend scales to
    Amps via amps_base for the pu/Amps chart-units toggle)."""
    if max_x is None:
        max_x = max(6.0, relay.hoc_pu + 1.0)
    x = np.linspace(0, max_x, n)
    y = [relay.calculate_trip_threshold(v) for v in x]
    return {"x_pu": x.tolist(), "y_pu": y, "max_x_pu": max_x}


def evaluate_phases(relay, phase_inputs):
    """phase_inputs: {phase: {"i_hv":.., "a_hv":.., "i_lv":.., "a_lv":..}}"""
    evals = {}
    for p in PHASES:
        pin = phase_inputs.get(p, {"i_hv": 0.0, "a_hv": 0.0, "i_lv": 0.0, "a_lv": 0.0})
        result = relay.evaluate_protection([
            (_f(pin, "i_hv"), _f(pin, "a_hv")),
            (_f(pin, "i_lv"), _f(pin, "a_lv")),
        ])
        evals[p] = result
    return evals


def default_phase_a_angles(relay, ct_polarity):
    """Solves the healthy-through-load default LV angle for Phase A (and the
    trivial Phase B/C zero-magnitude defaults), matching
    views/transformer_exct.py lines 422-447 / _on_polarity_change."""
    def_ang_hv_a = 0.0
    def_val_hv = relay.windings[0]["i_rated_pri"]
    def_val_lv = relay.windings[1]["i_rated_pri"]
    vec_hv_internal = winding_internal_vector(relay, 0, def_val_hv, def_ang_hv_a)
    target_lv_internal = vec_hv_internal if ct_polarity == "OPPOSITE" else -vec_hv_internal
    _, def_ang_lv_a = raw_input_for_internal_vector(relay, 1, target_lv_internal)

    out = {
        "Phase A": {"i_hv": def_val_hv, "a_hv": def_ang_hv_a, "i_lv": def_val_lv, "a_lv": def_ang_lv_a},
    }
    for idx, phase in enumerate(["Phase B", "Phase C"], start=1):
        def_ang_hv = -120.0 * idx
        def_ang_lv = def_ang_hv if ct_polarity == "OPPOSITE" else def_ang_hv + 180.0
        out[phase] = {"i_hv": 0.0, "a_hv": def_ang_hv, "i_lv": 0.0, "a_lv": def_ang_lv}
    return out


def compute_fault_current(settings, kv_hv, kv_lv):
    """Mirrors views/transformer_exct.py lines 841-847 — unlike GSUT/UAT, EXCT
    has no separate fault_kv_hv field; the HV fault base is settings' own
    kv_hv (already the nameplate voltage, not tap-adjusted)."""
    fault_side = str(settings.get("fault_side", "HV")).upper()
    fault_mva_base = _f(settings, "fault_mva_base")
    z_pct = _f(settings, "z_pct", 7.0)
    x_over_r = _f(settings, "x_over_r", 10.0)
    asym_basis = settings.get("asym_basis", "Actual X/R")
    ct_hv = _f(settings, "ct_hv")
    ct_lv = _f(settings, "ct_lv")
    ct_sec = _f(settings, "ct_sec", 5.0)

    fault_kv = kv_hv if fault_side == "HV" else kv_lv
    fault_ct = ct_hv if fault_side == "HV" else ct_lv

    fault_calc = transformer_through_fault_current(
        fault_mva_base, fault_kv, z_pct / 100.0, x_over_r,
        use_worst_case_asym=(asym_basis == "Worst-case (1.73x flat)" or asym_basis == "Worst-case (1.73× flat)"),
    )
    relay_sec_fault = relay_secondary_at_fault(fault_calc["i_asym_amps"], fault_ct, ct_sec)

    ct_withstand_a = _f(settings, "ct_withstand_a", 60.0)
    within_withstand = relay_sec_fault <= ct_withstand_a

    return {
        "fault_side": fault_side,
        "fault_calc": fault_calc,
        "relay_sec_fault": relay_sec_fault,
        "ct_withstand_a": ct_withstand_a,
        "within_withstand": within_withstand,
    }


def fault_waveform(fault_calc, x_over_r, cycles=5, freq_hz=60.0, n=800):
    """Instantaneous decaying-DC-offset waveform — mirrors views/transformer_exct.py
    lines 884-890."""
    w = 2 * math.pi * freq_hz
    t = np.linspace(0, cycles / freq_hz, n)
    i_peak_sym = math.sqrt(2) * fault_calc["i_sym_amps"]
    decay_rate = w / x_over_r if x_over_r else 0.0
    i = i_peak_sym * (np.exp(-t * decay_rate) - np.cos(w * t))
    return {"t_ms": (t * 1000.0).tolist(), "i_amps": i.tolist(), "i_peak_sym": i_peak_sym}


def fault_clearing_sim(relay, fault_calc, fault_side, fault_scenario, relay_operate_cycles, breaker_cycles):
    """Mirrors views/transformer_exct.py lines 945-1044 — evaluates whether the
    fault (as posed) trips the relay, and (if so) the total clearing time."""
    cycle_ms = 1000.0 / 60.0
    preload_current = relay.windings[0]["i_rated_pri"]
    fault_idx = 0 if fault_side == "HV" else 1
    other_idx = 1 - fault_idx

    winding_inputs = [(0.0, 0.0) for _ in relay.windings]
    winding_inputs[fault_idx] = (fault_calc["i_asym_amps"], 0.0)
    if fault_scenario.startswith("External"):
        other_rated = relay.windings[other_idx]["i_rated_pri"]
        fault_rated = relay.windings[fault_idx]["i_rated_pri"]
        ref_mult = fault_calc["i_asym_amps"] / fault_rated if fault_rated > 0 else 0.0
        other_amps = ref_mult * other_rated
        other_angle = solve_healthy_target_angle(relay, other_idx, fault_idx, fault_calc["i_asym_amps"], 0.0)
        winding_inputs[other_idx] = (other_amps, other_angle)

    sim_eval = relay.evaluate_protection(winding_inputs)
    sim_current_primary = fault_calc["i_asym_amps"]

    result = {
        "is_trip": sim_eval["is_trip"],
        "status": sim_eval["status"],
        "preload_current": preload_current,
        "sim_current_primary": sim_current_primary,
    }
    if sim_eval["is_trip"]:
        relay_ms = relay_operate_cycles * cycle_ms
        total_ms = relay_ms + breaker_cycles * cycle_ms
        result.update({"kind": "trip", "relay_ms": relay_ms, "total_ms": total_ms})
    else:
        result.update({"kind": "no_trip", "window_ms": 200.0})
    return result


def sweep_table(relay, sweep_start, sweep_end, sweep_step):
    if sweep_end <= sweep_start or sweep_step <= 0:
        return None
    points = np.arange(sweep_start, sweep_end + sweep_step / 2.0, sweep_step)
    rows = []
    for i_rest in points:
        boundary_op = relay.calculate_trip_threshold(float(i_rest))
        sec_hv = (i_rest + boundary_op / 2.0) * relay.windings[0]["i_rated_sec"]
        sec_lv = (i_rest - boundary_op / 2.0) * relay.windings[1]["i_rated_sec"]
        rows.append({
            "i_rest_pu": round(float(i_rest), 3),
            "boundary_op_pu": round(boundary_op, 3),
            "hv_injection_a": round(float(sec_hv), 3),
            "lv_injection_a": round(float(sec_lv), 3),
        })
    return rows


def boundary_injection(relay, r_val):
    """Boundary Injection Calculator — mirrors lines 573-583."""
    boundary_op = relay.calculate_trip_threshold(r_val)
    sec_hv = (r_val + boundary_op / 2.0) * relay.windings[0]["i_rated_sec"]
    sec_lv = (r_val - boundary_op / 2.0) * relay.windings[1]["i_rated_sec"]
    return {"boundary_op_pu": boundary_op, "hv_inject_a": sec_hv, "lv_inject_a": sec_lv}


def raw_test_point_eval(relay, raw_inputs):
    """raw_inputs: [(i_hv_amps, a_hv_deg), (i_lv_amps, a_lv_deg)] — reuses
    evaluate_protection exactly like common/test_point_input.py's raw-current
    path does (no restraint/diff math duplicated)."""
    return relay.evaluate_protection(raw_inputs)


def settings_sheet_rows(settings, relay, convention, ct_polarity):
    """Reimplements common/relay_settings_sheet.py's row-building (CSV shape
    only — no Streamlit container/download-button)."""
    ct_hv = _f(settings, "ct_hv")
    ct_lv = _f(settings, "ct_lv")
    ct_sec = _f(settings, "ct_sec", 5.0)
    tap_hv = _f(settings, "tap_hv", 1.0)
    tap_lv = _f(settings, "tap_lv", 1.0)
    bias_pct = _f(settings, "bias", 20)
    min_operate_pct = _f(settings, "min_operate", 20)
    hoc_multiple = _f(settings, "hoc", 5)
    return [
        ("HV CT Ratio", f"{ct_hv:.0f}:{ct_sec:.0f}"),
        ("LV CT Ratio", f"{ct_lv:.0f}:{ct_sec:.0f}"),
        ("T1 (HV Tap)", f"{tap_hv:.3f}"),
        ("T2 (LV Tap)", f"{tap_lv:.3f}"),
        ("Bias, τ (%)", f"{bias_pct:.0f}"),
        ("Minimum Operate (%)", f"{min_operate_pct:.0f}"),
        ("HOC (x tap current)", f"{hoc_multiple:.2f}"),
        ("Restraint Standard", convention),
        ("CT Polarity Reference", ct_polarity),
    ]


def recompute(payload):
    """Full recompute — mirrors today's Streamlit behavior of recomputing
    everything on every rerun regardless of active tab. `payload` is the
    posted settings JSON (see web/routes/transformer_exct.py for shape)."""
    settings = payload.get("settings", {})
    convention = str(payload.get("convention", "IEEE")).upper()
    ct_polarity = str(payload.get("ct_polarity", "OPPOSITE")).upper()

    relay = build_relay(settings, convention, ct_polarity)
    mismatch = compute_mismatch(settings)
    amps_base = relay.windings[0]["i_rated_sec"]

    windings_info = [
        {
            "name": w["name"], "kv": w["kv"], "ct_ratio": w["ct_ratio"],
            "ct_secondary_rating": w["ct_secondary_rating"], "tap": w["tap"],
            "ct_connection": w["ct_connection"],
            "i_rated_pri": w["i_rated_pri"], "i_rated_sec": w["i_rated_sec"],
        }
        for w in relay.windings
    ]

    phase_inputs = payload.get("phase_inputs") or {}
    if not phase_inputs:
        phase_inputs = default_phase_a_angles(relay, ct_polarity)
    evals = evaluate_phases(relay, phase_inputs)
    default_angles = default_phase_a_angles(relay, ct_polarity)

    curve = bias_curve(relay, max_x=max(
        6.0, max((e["i_rest_pu"] for e in evals.values()), default=0.0) + 1.5, relay.hoc_pu + 1.0
    ))

    any_trip = any(e["is_trip"] for e in evals.values())

    out = {
        "amps_base": amps_base,
        "hoc_pu": relay.hoc_pu,
        "windings": windings_info,
        "mismatch": mismatch,
        "evals": evals,
        "any_trip": any_trip,
        "default_angles": default_angles,
        "bias_curve": curve,
    }

    # Optional: Fault Current Analysis (posted only when that tab is active /
    # its fields are present)
    if "fault_mva_base" in settings or "z_pct" in settings:
        kv_hv = _f(settings, "kv_hv")
        kv_lv = _f(settings, "kv_lv")
        fault = compute_fault_current(settings, kv_hv, kv_lv)
        out["fault"] = fault
        out["fault"]["waveform"] = fault_waveform(fault["fault_calc"], _f(settings, "x_over_r", 10.0))

        fault_sim_req = payload.get("fault_sim")
        if fault_sim_req:
            out["fault"]["sim"] = fault_clearing_sim(
                relay, fault["fault_calc"], fault["fault_side"],
                fault_sim_req.get("fault_scenario", "Internal Fault (within 87ET zone)"),
                float(fault_sim_req.get("relay_operate_cycles", 1.5)),
                float(fault_sim_req.get("breaker_cycles", 5.0)),
            )

    # Optional: sweep table (Commissioning & Injection tab)
    sweep_req = payload.get("sweep")
    if sweep_req:
        rows = sweep_table(
            relay,
            float(sweep_req.get("sweep_start", 0.2)),
            float(sweep_req.get("sweep_end", max(6.0, relay.hoc_pu + 1.0))),
            float(sweep_req.get("sweep_step", 0.5)),
        )
        out["sweep"] = rows

    # Optional: raw-current test-point evaluation (Curve & Test Points tab)
    raw_tp_req = payload.get("raw_test_point")
    if raw_tp_req:
        raw_inputs = [
            (float(raw_tp_req["hv"]["amps"]), float(raw_tp_req["hv"]["angle"])),
            (float(raw_tp_req["lv"]["amps"]), float(raw_tp_req["lv"]["angle"])),
        ]
        out["raw_test_point_eval"] = raw_test_point_eval(relay, raw_inputs)

    return out
