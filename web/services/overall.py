"""
Overall GSUT-GEN backup differential (CAC2-10-M3, 3-winding) calculation glue
for the Flask reference page. Ports the arithmetic from
views/transformer_overall.py's script body into plain functions that take a
JSON-friendly settings dict in and return JSON-friendly dicts out — no
Streamlit, no session_state.

Same TransformerDifferentialRelay engine as web/services/gsut.py (engines/
transformer.py already generalizes to N windings) — this file just feeds it
3 windings (HV/Generator/UAT) instead of 2 (HV/LV), and adds the
single-winding-energize injection logic that a 3-restraint relay needs for
commissioning (there's no single unique way to split a target differential
across three currents, so the standard method is "energize one winding at a
time, other two at zero" — see views/transformer_overall.py's Commissioning
& Injection Tool tab).
"""
import math

import numpy as np

from engines.transformer import (
    TransformerDifferentialRelay,
    winding_internal_vector,
    raw_input_for_internal_vector,
)
from common.settings_advisor import suggest_ct_matching_tap, mismatch_ratio_pct, suggest_bias_settings

PHASES = ["Phase A", "Phase B", "Phase C"]
WINDING_NAMES = ["HV (525kV)", "Generator (23kV)", "UAT (23kV)"]


def _f(d, key, default=0.0):
    v = d.get(key, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def build_windings(settings):
    return [
        {
            "name": "HV (525kV)",
            "kv": _f(settings, "kv_hv"),
            "ct_ratio": _f(settings, "ct_hv"),
            "ct_secondary_rating": _f(settings, "ct_sec", 5.0),
            "tap": _f(settings, "tap_hv", 1.0),
            "ct_connection": str(settings.get("ct_conn_hv", "DELTA")).upper(),
        },
        {
            "name": "Generator (23kV)",
            "kv": _f(settings, "kv_gen"),
            "ct_ratio": _f(settings, "ct_gen"),
            "ct_secondary_rating": _f(settings, "ct_sec", 5.0),
            "tap": _f(settings, "tap_gen", 1.0),
            "ct_connection": str(settings.get("ct_conn_gen", "WYE")).upper(),
        },
        {
            "name": "UAT (23kV)",
            "kv": _f(settings, "kv_uat"),
            "ct_ratio": _f(settings, "ct_uat"),
            "ct_secondary_rating": _f(settings, "ct_sec", 5.0),
            "tap": _f(settings, "tap_uat", 1.0),
            "ct_connection": str(settings.get("ct_conn_uat", "WYE")).upper(),
        },
    ]


def build_relay(settings, convention="IEEE", ct_polarity="OPPOSITE"):
    windings = build_windings(settings)
    return TransformerDifferentialRelay(
        mva_rated=_f(settings, "mva"),
        windings=windings,
        bias_pct=_f(settings, "bias", 30),
        min_operate_pct=_f(settings, "min_operate", 30),
        hoc_multiple=_f(settings, "hoc", 5),
        convention=convention, ct_polarity=ct_polarity,
    )


def compute_mismatch(settings):
    """Mirrors views/transformer_overall.py lines 191-244 — CT matching tap
    reference (T1_E/T2_E/T3_E, informational) and the actual live 3-way
    mismatch % at the currently-set taps (the real pass/fail signal)."""
    mva = _f(settings, "mva")
    kv_hv = _f(settings, "kv_hv")
    kv_gen = _f(settings, "kv_gen")
    kv_uat = _f(settings, "kv_uat")
    ct_hv = _f(settings, "ct_hv")
    ct_gen = _f(settings, "ct_gen")
    ct_uat = _f(settings, "ct_uat")
    ct_sec = _f(settings, "ct_sec", 5.0)
    tap_hv = _f(settings, "tap_hv", 1.0)
    tap_gen = _f(settings, "tap_gen", 1.0)
    tap_uat = _f(settings, "tap_uat", 1.0)
    ct_conn_hv = str(settings.get("ct_conn_hv", "DELTA")).upper()
    ct_conn_gen = str(settings.get("ct_conn_gen", "WYE")).upper()
    ct_conn_uat = str(settings.get("ct_conn_uat", "WYE")).upper()

    delta_factor_hv = 1.7320508 if ct_conn_hv == "DELTA" else 1.0
    delta_factor_gen = 1.7320508 if ct_conn_gen == "DELTA" else 1.0
    delta_factor_uat = 1.7320508 if ct_conn_uat == "DELTA" else 1.0
    i_rated_pri_hv = (mva * 1000.0) / (1.7320508 * kv_hv) if kv_hv > 0 else 0.0
    i_rated_pri_gen = (mva * 1000.0) / (1.7320508 * kv_gen) if kv_gen > 0 else 0.0
    i_rated_pri_uat = (mva * 1000.0) / (1.7320508 * kv_uat) if kv_uat > 0 else 0.0

    t1_e = suggest_ct_matching_tap(i_rated_pri_hv, ct_hv, ct_sec, delta_factor_hv)
    t2_e = suggest_ct_matching_tap(i_rated_pri_gen, ct_gen, ct_sec, delta_factor_gen)
    t3_e = suggest_ct_matching_tap(i_rated_pri_uat, ct_uat, ct_sec, delta_factor_uat)

    i_relay_hv_at_set_tap = (i_rated_pri_hv / (ct_hv / ct_sec) * delta_factor_hv * tap_hv) if ct_hv > 0 and ct_sec > 0 else None
    i_relay_gen_at_set_tap = (i_rated_pri_gen / (ct_gen / ct_sec) * delta_factor_gen * tap_gen) if ct_gen > 0 and ct_sec > 0 else None
    i_relay_uat_at_set_tap = (i_rated_pri_uat / (ct_uat / ct_sec) * delta_factor_uat * tap_uat) if ct_uat > 0 and ct_sec > 0 else None
    calc_mismatch = mismatch_ratio_pct([i_relay_hv_at_set_tap, i_relay_gen_at_set_tap, i_relay_uat_at_set_tap])

    suggestion = suggest_bias_settings(calc_mismatch or 0.0, num_windings=3)

    bias_pct = _f(settings, "bias", 30)
    min_operate_pct = _f(settings, "min_operate", 30)

    all_clear = (
        calc_mismatch is not None
        and calc_mismatch < 5.0
        and bias_pct >= suggestion["bias_pct"]
        and min_operate_pct >= suggestion["min_operate_pct"]
    )

    return {
        "t1_e": t1_e,
        "t2_e": t2_e,
        "t3_e": t3_e,
        "calc_mismatch_pct": calc_mismatch,
        "suggestion": suggestion,
        "all_clear": all_clear,
        "effective_ratio_hv": f"{ct_hv:.0f}:{ct_sec:.0f}" if ct_sec else "-",
        "effective_ratio_hv_ratio": (ct_hv / ct_sec) if ct_sec else None,
        "effective_ratio_gen": f"{ct_gen:.0f}:{ct_sec:.0f}" if ct_sec else "-",
        "effective_ratio_gen_ratio": (ct_gen / ct_sec) if ct_sec else None,
        "effective_ratio_uat": f"{ct_uat:.0f}:{ct_sec:.0f}" if ct_sec else "-",
        "effective_ratio_uat_ratio": (ct_uat / ct_sec) if ct_sec else None,
    }


def bias_curve(relay, max_x=None, n=400):
    """Theoretical CAL. line, per-unit — matches views/transformer_overall.py's
    Live Simulation bias-curve x/y arrays, pu only (the frontend scales to
    Amps via amps_base for the pu/Amps chart-units toggle)."""
    if max_x is None:
        max_x = max(6.0, relay.hoc_pu + 1.0)
    x = np.linspace(0, max_x, n)
    y = [relay.calculate_trip_threshold(v) for v in x]
    return {"x_pu": x.tolist(), "y_pu": y, "max_x_pu": max_x}


def evaluate_phases(relay, phase_inputs):
    """phase_inputs: {phase: {"i_hv":.., "a_hv":.., "i_gen":.., "a_gen":.., "i_uat":.., "a_uat":..}}"""
    evals = {}
    for p in PHASES:
        pin = phase_inputs.get(p, {"i_hv": 0.0, "a_hv": 0.0, "i_gen": 0.0, "a_gen": 0.0, "i_uat": 0.0, "a_uat": 0.0})
        result = relay.evaluate_protection([
            (_f(pin, "i_hv"), _f(pin, "a_hv")),
            (_f(pin, "i_gen"), _f(pin, "a_gen")),
            (_f(pin, "i_uat"), _f(pin, "a_uat")),
        ])
        evals[p] = result
    return evals


def default_phase_a_angles(relay, ct_polarity):
    """Solves the healthy-through-load default Generator angle for Phase A
    (nulling only HV+Generator — UAT is treated as off-load, 0A, by default,
    matching views/transformer_overall.py lines 436-476 / _on_polarity_change),
    plus the trivial Phase B/C zero-magnitude defaults."""
    def_ang_hv_a = 0.0
    def_val_hv = relay.windings[0]["i_rated_pri"]
    def_val_gen = relay.windings[1]["i_rated_pri"]
    vec_hv_internal = winding_internal_vector(relay, 0, def_val_hv, def_ang_hv_a)
    target_gen_internal = vec_hv_internal if ct_polarity == "OPPOSITE" else -vec_hv_internal
    _, def_ang_gen_a = raw_input_for_internal_vector(relay, 1, target_gen_internal)

    out = {
        "Phase A": {
            "i_hv": def_val_hv, "a_hv": def_ang_hv_a,
            "i_gen": def_val_gen, "a_gen": def_ang_gen_a,
            "i_uat": 0.0, "a_uat": def_ang_hv_a,
        },
    }
    for idx, phase in enumerate(["Phase B", "Phase C"], start=1):
        def_ang_hv = -120.0 * idx
        def_ang_other = def_ang_hv if ct_polarity == "OPPOSITE" else def_ang_hv + 180.0
        out[phase] = {
            "i_hv": 0.0, "a_hv": def_ang_hv,
            "i_gen": 0.0, "a_gen": def_ang_other,
            "i_uat": 0.0, "a_uat": def_ang_other,
        }
    return out


def single_winding_injection(relay, winding_idx, current_pu):
    """Single-Winding Injection Test — mirrors views/transformer_overall.py
    lines 598-624. Energizes exactly one winding at `current_pu` x its own
    rated current, other two windings at zero, and evaluates the relay. This
    is the standard 3-restraint-relay commissioning method (there's no single
    unique way to split a target differential across three currents)."""
    test_inputs = [(0.0, 0.0) for _ in relay.windings]
    inj_primary_amps = current_pu * relay.windings[winding_idx]["i_rated_pri"]
    test_inputs[winding_idx] = (inj_primary_amps, 0.0)
    result = relay.evaluate_protection(test_inputs)
    inj_secondary_amps = current_pu * relay.windings[winding_idx]["i_rated_sec"]
    return {
        "winding_idx": winding_idx,
        "winding_name": relay.windings[winding_idx]["name"],
        "inject_secondary_amps": inj_secondary_amps,
        "i_op_pu": result["i_op_pu"],
        "i_rest_pu": result["i_rest_pu"],
        "i_threshold_pu": result["i_threshold_pu"],
        "is_trip": result["is_trip"],
        "status": result["status"],
    }


def single_winding_sweep(relay, winding_idx, sweep_start, sweep_end, sweep_step):
    """Auto-Sweep Single-Winding Test Table — mirrors lines 626-654."""
    if sweep_end <= sweep_start or sweep_step <= 0:
        return None
    points = np.arange(sweep_start, sweep_end + sweep_step / 2.0, sweep_step)
    rows = []
    for i_test in points:
        t_inputs = [(0.0, 0.0) for _ in relay.windings]
        t_inputs[winding_idx] = (float(i_test) * relay.windings[winding_idx]["i_rated_pri"], 0.0)
        res = relay.evaluate_protection(t_inputs)
        rows.append({
            "test_current_pu": round(float(i_test), 3),
            "injection_a": round(float(i_test) * relay.windings[winding_idx]["i_rated_sec"], 3),
            "i_op_pu": round(res["i_op_pu"], 3),
            "i_rest_pu": round(res["i_rest_pu"], 3),
            "i_threshold_pu": round(res["i_threshold_pu"], 3),
            "status": res["status"],
        })
    return rows


def raw_test_point_eval(relay, raw_inputs):
    """raw_inputs: [(i_hv_amps, a_hv_deg), (i_gen_amps, a_gen_deg), (i_uat_amps, a_uat_deg)]
    — reuses evaluate_protection exactly like common/test_point_input.py's
    raw-current path does (no restraint/diff math duplicated)."""
    return relay.evaluate_protection(raw_inputs)


def settings_sheet_rows(settings, relay, convention, ct_polarity):
    """Reimplements views/transformer_overall.py lines 878-890's
    render_settings_sheet() rows (CSV shape only — no Streamlit
    container/download-button)."""
    ct_hv = _f(settings, "ct_hv")
    ct_gen = _f(settings, "ct_gen")
    ct_uat = _f(settings, "ct_uat")
    ct_sec = _f(settings, "ct_sec", 5.0)
    tap_hv = _f(settings, "tap_hv", 1.0)
    tap_gen = _f(settings, "tap_gen", 1.0)
    tap_uat = _f(settings, "tap_uat", 1.0)
    bias_pct = _f(settings, "bias", 30)
    min_operate_pct = _f(settings, "min_operate", 30)
    hoc_multiple = _f(settings, "hoc", 5)
    return [
        ("HV CT Ratio", f"{ct_hv:.0f}:{ct_sec:.0f}"),
        ("Generator CT Ratio", f"{ct_gen:.0f}:{ct_sec:.0f}"),
        ("UAT CT Ratio", f"{ct_uat:.0f}:{ct_sec:.0f}"),
        ("T1 (HV Tap)", f"{tap_hv:.3f}"),
        ("T2 (Generator Tap)", f"{tap_gen:.3f}"),
        ("T3 (UAT Tap)", f"{tap_uat:.3f}"),
        ("Bias, τ (%)", f"{bias_pct:.0f}"),
        ("Minimum Operate (%)", f"{min_operate_pct:.0f}"),
        ("HOC (x tap value current)", f"{hoc_multiple:.2f}"),
        ("Restraint Standard", convention),
        ("CT Polarity Reference", ct_polarity),
    ]


def recompute(payload):
    """Full recompute — mirrors today's Streamlit behavior of recomputing
    everything on every rerun regardless of active tab. `payload` is the
    posted settings JSON (see web/routes/transformer_overall.py for shape)."""
    settings = payload.get("settings", {})
    convention = str(payload.get("convention", "IEEE")).upper()
    ct_polarity = str(payload.get("ct_polarity", "OPPOSITE")).upper()

    relay = build_relay(settings, convention, ct_polarity)
    mismatch = compute_mismatch(settings)
    amps_base = relay.windings[0]["i_rated_sec"]  # HV-side rated secondary current

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
        "winding_names": WINDING_NAMES,
        "mismatch": mismatch,
        "evals": evals,
        "any_trip": any_trip,
        "default_angles": default_angles,
        "bias_curve": curve,
    }

    # Optional: single-winding injection (Commissioning & Injection tab)
    injection_req = payload.get("injection")
    if injection_req:
        winding_idx = int(injection_req.get("winding_idx", 0))
        current_pu = float(injection_req.get("current_pu", 1.0))
        out["injection"] = single_winding_injection(relay, winding_idx, current_pu)

    # Optional: single-winding sweep table (Commissioning & Injection tab)
    sweep_req = payload.get("sweep")
    if sweep_req:
        winding_idx = int(sweep_req.get("winding_idx", 0))
        rows = single_winding_sweep(
            relay, winding_idx,
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
            (float(raw_tp_req["gen"]["amps"]), float(raw_tp_req["gen"]["angle"])),
            (float(raw_tp_req["uat"]["amps"]), float(raw_tp_req["uat"]["angle"])),
        ]
        out["raw_test_point_eval"] = raw_test_point_eval(relay, raw_inputs)

    return out
