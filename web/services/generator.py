"""
Generator (87G) differential relay calculation glue for the Flask reference
page. Ports the arithmetic from views/generator.py's script body into plain
functions that take a JSON-friendly settings dict in and return JSON-friendly
dicts out — no Streamlit, no session_state.

Reuses engines/generator.py and engines/fault_current.py UNCHANGED.

Structurally distinct from web/services/gsut.py in two ways:
  - AdvancedDifferentialRelay.evaluate_protection() takes 4 positional scalar
    args (i_primary_N, angle_N_deg, i_primary_T, angle_T_deg) — NOT a list of
    (amps, angle) winding tuples like TransformerDifferentialRelay.
  - Everything is gated by `mode` ("GENERATOR" = GE G60 dual-breakpoint,
    "GENERATOR_LEGACY" = GE CFD22B4A single-slope) - which settings fields
    exist, which preset dict is active, and the trip-threshold curve shape
    (handled internally by AdvancedDifferentialRelay.calculate_trip_threshold).
"""
import math

import numpy as np

from engines.generator import AdvancedDifferentialRelay
from engines.fault_current import three_phase_fault_current, relay_secondary_at_fault
from common.settings_advisor import mismatch_ratio_pct, suggest_bias_settings

PHASES = ["Phase A", "Phase B", "Phase C"]


def _f(d, key, default=0.0):
    v = d.get(key, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def normalize_mode(mode):
    mode = str(mode or "GENERATOR").upper()
    return mode if mode in ("GENERATOR", "GENERATOR_LEGACY") else "GENERATOR"


def build_relay(settings, mode, convention="IEEE", ct_polarity="SAME"):
    mode = normalize_mode(mode)
    mva = _f(settings, "mva")
    kv = _f(settings, "kv")
    ct_n = _f(settings, "ct_n")
    ct_t = _f(settings, "ct_t")
    ct_sec = _f(settings, "ct_sec", 5.0)

    kwargs = dict(
        mode=mode, mva_rated=mva, kv_rated=kv,
        ct_ratio_N=ct_n, ct_ratio_T=ct_t, ct_secondary_rating=ct_sec,
        convention=convention, ct_polarity=ct_polarity,
    )

    if mode == "GENERATOR_LEGACY":
        kwargs.update(
            slope_1=_f(settings, "slope1", 10.0),
            target_amps=_f(settings, "target_amps", 0.2),
        )
    else:
        i_unrestrained = None
        if bool(settings.get("unrestrained_enabled")):
            i_unrestrained = _f(settings, "unrestrained", 8.0)
        kwargs.update(
            i_pickup=_f(settings, "pickup", 0.10),
            slope_1=_f(settings, "slope1", 20.0),
            slope_2=_f(settings, "slope2", 80.0),
            break_1=_f(settings, "break1", 1.15),
            break_2=_f(settings, "break2", 8.00),
            i_unrestrained=i_unrestrained,
        )

    return AdvancedDifferentialRelay(**kwargs)


def compute_mismatch(settings):
    """Mirrors lines 209-217 of views/generator.py — this relay has no
    CT-matching tap to absorb a mismatch (unlike the transformer relays), so
    Neutral/Terminal CT ratios should normally be identical; this is purely
    a live pass/fail check on the ratios as entered, not a tap-selection aid."""
    mva = _f(settings, "mva")
    kv = _f(settings, "kv")
    ct_n = _f(settings, "ct_n")
    ct_t = _f(settings, "ct_t")
    ct_sec = _f(settings, "ct_sec", 5.0)

    i_rated_sec_n_calc = (mva * 1000.0 / (1.7320508 * kv)) / (ct_n / ct_sec) if kv > 0 and ct_n > 0 and ct_sec > 0 else 0.0
    i_rated_sec_t_calc = (mva * 1000.0 / (1.7320508 * kv)) / (ct_t / ct_sec) if kv > 0 and ct_t > 0 and ct_sec > 0 else 0.0
    calc_mismatch = mismatch_ratio_pct([i_rated_sec_n_calc, i_rated_sec_t_calc])

    suggestion = suggest_bias_settings(calc_mismatch or 0.0, num_windings=2)

    return {
        "calc_mismatch_pct": calc_mismatch,
        "suggestion": suggestion,
        "effective_ratio_n": f"{ct_n:.0f}:{ct_sec:.0f}" if ct_sec else "-",
        "effective_ratio_n_ratio": (ct_n / ct_sec) if ct_sec else None,
        "effective_ratio_t": f"{ct_t:.0f}:{ct_sec:.0f}" if ct_sec else "-",
        "effective_ratio_t_ratio": (ct_t / ct_sec) if ct_sec else None,
    }


def bias_curve(relay, mode, max_x=None, n=400):
    """Theoretical CAL. line, per-unit — matches views/generator.py's
    Live Simulation bias-curve x/y arrays (lines 512-513)."""
    mode = normalize_mode(mode)
    if max_x is None:
        max_x = max(6.0, relay.break_2 + 1.0) if mode == "GENERATOR" else 6.0
    x = np.linspace(0, max_x, n)
    y = [relay.calculate_trip_threshold(v) for v in x]
    return {"x_pu": x.tolist(), "y_pu": y, "max_x_pu": max_x}


def evaluate_phases(relay, phase_inputs):
    """phase_inputs: {phase: {"i_N":.., "a_N":.., "i_T":.., "a_T":..}}.

    Unlike TransformerDifferentialRelay.evaluate_protection() (a list of
    winding (amps, angle) tuples), AdvancedDifferentialRelay.evaluate_protection
    takes 4 positional scalar args: (i_primary_N, angle_N_deg, i_primary_T,
    angle_T_deg) — Neutral-side magnitude/angle, then Terminal-side
    magnitude/angle. Every call site here uses that exact signature."""
    evals = {}
    for p in PHASES:
        pin = phase_inputs.get(p, {"i_N": 0.0, "a_N": 0.0, "i_T": 0.0, "a_T": 0.0})
        result = relay.evaluate_protection(
            _f(pin, "i_N"), _f(pin, "a_N"), _f(pin, "i_T"), _f(pin, "a_T"),
        )
        evals[p] = result
    return evals


def default_phase_a_angles(relay, ct_polarity):
    """Matches views/generator.py lines 449-458 — trivial angle defaults, no
    trig solve needed (unlike the transformer pages) since the generator
    differential zone has no turns-ratio/tap between the two CTs to correct for."""
    out = {}
    for idx, phase in enumerate(PHASES):
        def_val = relay.i_rated_pri if phase == "Phase A" else 0.0
        def_ang_n = -120.0 * idx
        def_ang_t = def_ang_n if ct_polarity == "OPPOSITE" else def_ang_n + 180.0
        out[phase] = {"i_N": def_val, "a_N": def_ang_n, "i_T": def_val, "a_T": def_ang_t}
    return out


def compute_fault_current(settings, relay):
    """Generator's own contribution (Thevenin source method, three_phase_fault_current)
    plus an externally-supplied through-fault reference figure — mirrors
    views/generator.py lines 914-972. Both checked against the same CT
    withstand limit, on the Terminal-side CT (relay_obj.ct_ratio_T) only."""
    mva = _f(settings, "mva")
    kv = _f(settings, "kv")
    x1_pu = _f(settings, "x1_pu", 0.155)
    asym_factor = _f(settings, "asym_factor", 1.73)
    ct_t = _f(settings, "ct_t")
    ct_sec = _f(settings, "ct_sec", 5.0)
    ct_withstand_a = _f(settings, "ct_withstand_a", 84.0)
    external_fault_ka = _f(settings, "external_fault_ka", 0.0)

    fault_calc = three_phase_fault_current(mva, kv, x1_pu, asym_factor)
    relay_sec_internal = relay_secondary_at_fault(fault_calc["i_fault_asym_amps"], ct_t, ct_sec)
    within_internal_withstand = relay_sec_internal <= ct_withstand_a

    relay_sec_external = None
    within_external_withstand = None
    if external_fault_ka > 0:
        relay_sec_external = relay_secondary_at_fault(external_fault_ka * 1000.0, ct_t, ct_sec)
        within_external_withstand = relay_sec_external <= ct_withstand_a

    return {
        "fault_calc": fault_calc,
        "relay_sec_internal": relay_sec_internal,
        "within_internal_withstand": within_internal_withstand,
        "external_fault_ka": external_fault_ka,
        "relay_sec_external": relay_sec_external,
        "within_external_withstand": within_external_withstand,
        "ct_withstand_a": ct_withstand_a,
    }


def fault_waveform(fault_calc, asym_factor, cycles=5, freq_hz=60.0, n=800):
    """Instantaneous decaying-DC-offset waveform — mirrors views/generator.py
    lines 986-999. Generator fault current uses a flat, editable Asymmetry
    Factor rather than a real X/R ratio (unlike the transformer pages), so
    the decay rate here is BACK-CALCULATED from that factor (inverting the
    same X/R-based formula the transformer pages use directly) purely to draw
    a physically plausible waveform shape."""
    asym_ceiling = 1.7320508
    if asym_factor >= asym_ceiling - 1e-6:
        x_over_r = 5000.0
    else:
        ratio_sq = max((asym_factor ** 2 - 1.0) / 2.0, 1e-9)
        r_over_x = -math.log(ratio_sq) / (2 * math.pi)
        x_over_r = (1.0 / r_over_x) if r_over_x > 1e-9 else 5000.0

    w = 2 * math.pi * freq_hz
    t = np.linspace(0, cycles / freq_hz, n)
    i_peak_sym = math.sqrt(2) * fault_calc["i_fault_sym_amps"]
    decay_rate = w / x_over_r if x_over_r else 0.0
    i = i_peak_sym * (np.exp(-t * decay_rate) - np.cos(w * t))
    return {"t_ms": (t * 1000.0).tolist(), "i_amps": i.tolist(), "i_peak_sym": i_peak_sym}


def fault_clearing_sim(relay, fault_calc, ct_polarity, fault_scenario, external_fault_ka,
                        relay_operate_cycles, breaker_cycles):
    """Mirrors views/generator.py lines 1055-1150. Internal: fault current is
    fed almost entirely from the Neutral side (evaluate_protection(i_fault, 0, 0, 0))
    — a large, easily-detected mismatch. External: the same current passes
    through both CTs (a healthy 87G should NOT operate); only runs if a
    non-zero external through-fault current has been entered."""
    cycle_ms = 1000.0 / 60.0
    preload_current = relay.i_rated_pri

    if fault_scenario.startswith("Internal"):
        sim_eval = relay.evaluate_protection(fault_calc["i_fault_asym_amps"], 0.0, 0.0, 0.0)
        sim_current_primary = fault_calc["i_fault_asym_amps"]
    elif external_fault_ka > 0:
        thru_amps = external_fault_ka * 1000.0
        ang_t = 0.0
        ang_n = ang_t if ct_polarity == "OPPOSITE" else ang_t + 180.0
        sim_eval = relay.evaluate_protection(thru_amps, ang_n, thru_amps, ang_t)
        sim_current_primary = thru_amps
    else:
        return {"kind": "no_data"}

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
        sec_n = (i_rest + boundary_op / 2.0) * relay.i_rated_sec_N
        sec_t = (i_rest - boundary_op / 2.0) * relay.i_rated_sec_T
        rows.append({
            "i_rest_pu": round(float(i_rest), 3),
            "boundary_op_pu": round(boundary_op, 3),
            "n_injection_a": round(float(sec_n), 3),
            "t_injection_a": round(float(sec_t), 3),
        })
    return rows


def boundary_injection(relay, r_val):
    """Boundary Injection Calculator — mirrors lines 601-617."""
    boundary_op = relay.calculate_trip_threshold(r_val)
    sec_n = (r_val + boundary_op / 2.0) * relay.i_rated_sec_N
    sec_t = (r_val - boundary_op / 2.0) * relay.i_rated_sec_T
    return {"boundary_op_pu": boundary_op, "n_inject_a": sec_n, "t_inject_a": sec_t}


def raw_test_point_eval(relay, raw_inputs):
    """raw_inputs: (i_N_amps, a_N_deg, i_T_amps, a_T_deg) — the 4-arg
    evaluate_protection signature, reused directly (no restraint/diff math
    duplicated here), matching common/test_point_input.py's raw-current path."""
    return relay.evaluate_protection(*raw_inputs)


def settings_sheet_rows(settings, relay, mode, convention, ct_polarity):
    """Reimplements common/relay_settings_sheet.py's row-building (CSV shape
    only) for both modes — mirrors views/generator.py lines 1216-1237.
    Relay-type label and the fields shown are both mode-dependent."""
    mode = normalize_mode(mode)
    ct_n = _f(settings, "ct_n")
    ct_t = _f(settings, "ct_t")
    ct_sec = _f(settings, "ct_sec", 5.0)

    if mode == "GENERATOR_LEGACY":
        rows = [
            ("Relay Type", "GE CFD22B4A (GEK-34124)"),
            ("Target/Seal-in Pickup (A sec.)", f"{_f(settings, 'target_amps', 0.2):.2f}"),
            ("Restraint Slope (%)", f"{_f(settings, 'slope1', 10.0):.0f}"),
        ]
    else:
        unrestrained_enabled = bool(settings.get("unrestrained_enabled"))
        rows = [
            ("Relay Type", "GE G60 (Numerical)"),
            ("Pickup (pu)", f"{_f(settings, 'pickup', 0.10):.3f}"),
            ("Slope 1 (%)", f"{_f(settings, 'slope1', 20.0):.0f}"),
            ("Break 1 (pu)", f"{_f(settings, 'break1', 1.15):.2f}"),
            ("Slope 2 (%)", f"{_f(settings, 'slope2', 80.0):.0f}"),
            ("Break 2 (pu)", f"{_f(settings, 'break2', 8.0):.2f}"),
            ("Unrestrained High-Set (pu)", f"{_f(settings, 'unrestrained', 8.0):.2f}" if unrestrained_enabled else "Not enabled"),
        ]

    rows += [
        ("Neutral CT Ratio", f"{ct_n:.0f}:{ct_sec:.0f}"),
        ("Terminal CT Ratio", f"{ct_t:.0f}:{ct_sec:.0f}"),
        ("Restraint Standard", convention),
        ("CT Polarity Reference", ct_polarity),
    ]
    return rows


def relay_type_label(mode):
    return "GE G60" if normalize_mode(mode) == "GENERATOR" else "GE CFD22B4A"


def recompute(payload):
    """Full recompute — mirrors today's Streamlit behavior of recomputing
    everything on every rerun regardless of active tab. `payload` is the
    posted settings JSON (see web/routes/generator.py for shape). `mode`
    ("GENERATOR" or "GENERATOR_LEGACY") gates the preset shape, the field set,
    and (inside the engine) the trip-threshold curve shape."""
    settings = payload.get("settings", {})
    mode = normalize_mode(payload.get("mode", "GENERATOR"))
    convention = str(payload.get("convention", "IEEE")).upper()
    ct_polarity = str(payload.get("ct_polarity", "SAME")).upper()

    relay = build_relay(settings, mode, convention, ct_polarity)
    mismatch = compute_mismatch(settings)
    amps_base = relay.i_rated_sec_N

    default_angles = default_phase_a_angles(relay, ct_polarity)
    phase_inputs = payload.get("phase_inputs") or {}
    if not phase_inputs:
        phase_inputs = default_angles
    evals = evaluate_phases(relay, phase_inputs)

    extra_range = (relay.break_2 + 1.0) if mode == "GENERATOR" else 0.0
    curve = bias_curve(relay, mode, max_x=max(
        6.0, max((e["i_rest_pu"] for e in evals.values()), default=0.0) + 1.5, extra_range
    ))

    any_trip = any(e["is_trip"] for e in evals.values())

    out = {
        "mode": mode,
        "relay_type_label": relay_type_label(mode),
        "amps_base": amps_base,
        "i_rated_pri": relay.i_rated_pri,
        "i_rated_sec_N": relay.i_rated_sec_N,
        "i_rated_sec_T": relay.i_rated_sec_T,
        "has_unrestrained": relay.i_unrestrained < 1e5,
        "i_unrestrained": relay.i_unrestrained if relay.i_unrestrained < 1e5 else None,
        "break_2": relay.break_2 if mode == "GENERATOR" else None,
        "mismatch": mismatch,
        "evals": evals,
        "any_trip": any_trip,
        "default_angles": default_angles,
        "bias_curve": curve,
    }

    # Optional: Fault Current Analysis (posted only when that tab's fields
    # are present in `settings`)
    if "x1_pu" in settings or "asym_factor" in settings:
        fault = compute_fault_current(settings, relay)
        out["fault"] = fault
        out["fault"]["waveform"] = fault_waveform(fault["fault_calc"], _f(settings, "asym_factor", 1.73))

        fault_sim_req = payload.get("fault_sim")
        if fault_sim_req:
            out["fault"]["sim"] = fault_clearing_sim(
                relay, fault["fault_calc"], ct_polarity,
                fault_sim_req.get("fault_scenario", "Internal Fault (within 87G zone)"),
                _f(settings, "external_fault_ka", 0.0),
                float(fault_sim_req.get("relay_operate_cycles", 1.5)),
                float(fault_sim_req.get("breaker_cycles", 5.0)),
            )

    # Optional: sweep table (Commissioning & Injection tab)
    sweep_req = payload.get("sweep")
    if sweep_req:
        default_end = (relay.break_2 + 2.0) if mode == "GENERATOR" else 6.0
        rows = sweep_table(
            relay,
            float(sweep_req.get("sweep_start", 0.2)),
            float(sweep_req.get("sweep_end", max(6.0, default_end))),
            float(sweep_req.get("sweep_step", 0.5)),
        )
        out["sweep"] = rows

    # Optional: raw-current test-point evaluation (Curve & Test Points tab)
    raw_tp_req = payload.get("raw_test_point")
    if raw_tp_req:
        raw_inputs = (
            float(raw_tp_req["n"]["amps"]), float(raw_tp_req["n"]["angle"]),
            float(raw_tp_req["t"]["amps"]), float(raw_tp_req["t"]["angle"]),
        )
        out["raw_test_point_eval"] = raw_test_point_eval(relay, raw_inputs)

    return out
