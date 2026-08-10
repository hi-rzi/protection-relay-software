"""
FMEA (Failure Mode and Effects Analysis) reference data for the digital/numerical
protection relays modeled in this app - GE G60 (Generator 87G), the Mitsubishi
CAC1-10-M3 / CAC2-10-M3 family (Transformer differential), and the Multilin SR469 /
GE 869 family (Motor protection).

Deliberately excludes the electromechanical relays also modeled elsewhere in the app
(GE CFD22B4A legacy generator relay, GE IFC66KD2A/HFC22B2A stack on ID Fan and PA
Fan) - the app's own theory text already describes those as electromechanical, and
their dominant failure modes (contact wear, mechanical wear-out, coil burnout) are
different enough from a microprocessor relay's (firmware, power supply, watchdog,
CT/output circuitry) that folding them into the same FMEA would blur two different
failure physics rather than usefully compare them.

Severity / Occurrence / Detection are all 1-10, standard FMEA convention. Detection
is the one axis that inverts intuition: 1 = failure is caught immediately and
reliably, 10 = failure would go essentially unnoticed until it mattered. These
starting values are engineering-judgment placeholders (labeled as such in the UI),
not measured plant data - the app has no logged relay failure history to calibrate
Occurrence against (see Reliability Data.py at the repo root for a related MTBF/
Arrhenius derating analysis, kept separate rather than duplicated here).
"""

CATEGORIES = [
    "GE G60 (Generator 87G)",
    "Mitsubishi CAC1-10-M3 / CAC2-10-M3 (Transformer Differential)",
    "Multilin SR469 / GE 869 (Motor Protection)",
]

# RPN = severity * occurrence * detection, range 1-1000. These thresholds are a
# commonly-used rule of thumb, not a formal standard - re-calibrate them if your
# plant's own risk-acceptance criteria differ.
RISK_BANDS = [
    (0, 99, "Low"),
    (100, 199, "Medium"),
    (200, 1000, "High"),
]


def risk_level(rpn):
    for lo, hi, label in RISK_BANDS:
        if lo <= rpn <= hi:
            return label
    return "High"


_G60 = "GE G60 (Generator 87G)"
_CAC = "Mitsubishi CAC1-10-M3 / CAC2-10-M3 (Transformer Differential)"
_SR469 = "Multilin SR469 / GE 869 (Motor Protection)"

FMEA_ENTRIES = [
    # --- GE G60 (Generator 87G) -------------------------------------------------
    dict(id="g60-01", category=_G60, component="DC control power",
         failure_mode="Loss of DC supply to the relay",
         potential_cause="Station battery/charger failure, tripped supply fuse, loose terminal",
         potential_effect="Relay fully de-energized - complete loss of 87G protection until restored",
         detection_method="DC supply monitoring alarm / relay \"OK\" status loss reported to SCADA",
         default_severity=9, default_occurrence=2, default_detection=3),
    dict(id="g60-02", category=_G60, component="CT input circuit (Neutral or Terminal)",
         failure_mode="Open circuit (broken/loose CT secondary wiring)",
         potential_cause="Loose terminal, broken lead, corroded CT terminal block",
         potential_effect="False restraint imbalance - risk of nuisance trip, or relay's own CT-failure alarm",
         detection_method="CT supervision/broken-conductor alarm if fitted, else nuisance-trip pattern",
         default_severity=8, default_occurrence=3, default_detection=4),
    dict(id="g60-03", category=_G60, component="CT input circuit (Neutral or Terminal)",
         failure_mode="Short circuit / cross-connection between CT circuits",
         potential_cause="Insulation breakdown, wiring error introduced during maintenance",
         potential_effect="Relay under-reads current on the affected side - reduced sensitivity to a real internal fault",
         detection_method="Commissioning secondary injection test; periodic re-test",
         default_severity=8, default_occurrence=2, default_detection=6),
    dict(id="g60-04", category=_G60, component="Trip output contact",
         failure_mode="Contact stuck closed (welded)",
         potential_cause="Contact arcing from repeated interrupting duty, wear over service life",
         potential_effect="Spurious breaker trip when the relay picks up even briefly, or breaker fails to reset",
         detection_method="Trip circuit supervision (52a/b monitoring), periodic maintenance test",
         default_severity=6, default_occurrence=2, default_detection=4),
    dict(id="g60-05", category=_G60, component="Trip output contact",
         failure_mode="Contact fails to close on command",
         potential_cause="Contact wear, driver circuit failure, mechanical binding",
         potential_effect="Correct trip decision computed but never reaches the breaker - protection failure for a real fault",
         detection_method="Trip circuit supervision (loss-of-continuity alarm), periodic trip test",
         default_severity=10, default_occurrence=2, default_detection=3),
    dict(id="g60-06", category=_G60, component="Firmware / logic",
         failure_mode="Misoperation from a firmware defect or corrupted logic",
         potential_cause="Firmware bug, corrupted memory, incomplete/failed firmware update",
         potential_effect="Unpredictable - false trip or failure to trip",
         detection_method="Manufacturer firmware advisories, periodic function test, internal checksum/self-test",
         default_severity=8, default_occurrence=1, default_detection=6),
    dict(id="g60-07", category=_G60, component="Watchdog / self-test",
         failure_mode="Self-test failure that is itself not reported",
         potential_cause="Fault inside the self-test/watchdog subsystem, or the alarm path to SCADA is down",
         potential_effect="Relay is actually degraded or failed but appears healthy - protection gap goes unnoticed",
         detection_method="Periodic manual functional test - the only independent check once self-test itself is suspect",
         default_severity=9, default_occurrence=1, default_detection=7),
    dict(id="g60-08", category=_G60, component="HMI / settings access",
         failure_mode="Incorrect settings applied",
         potential_cause="Wrong value keyed in during commissioning/change, applied to the wrong relay, misread from the settings sheet",
         potential_effect="Nuisance tripping (over-sensitive) or failure to trip on a real fault (under-sensitive)",
         detection_method="Independent settings peer review, relay-ready settings sheet cross-check",
         default_severity=7, default_occurrence=3, default_detection=5),
    dict(id="g60-09", category=_G60, component="Communications / SCADA interface",
         failure_mode="Loss of communication link",
         potential_cause="Network switch failure, fiber/cable damage, IED configuration error",
         potential_effect="Local trip logic unaffected, but remote monitoring, alarming, and event retrieval are lost",
         detection_method="SCADA \"communication failure\" alarm (self-evident)",
         default_severity=3, default_occurrence=4, default_detection=2),
    dict(id="g60-10", category=_G60, component="Internal hardware (power supply / ADC / CPU)",
         failure_mode="Component-level hardware failure",
         potential_cause="Component aging/thermal stress (see the plant's own MTBF/Arrhenius derating analysis), manufacturing defect",
         potential_effect="Ranges from complete relay shutdown to subtle measurement drift",
         detection_method="Relay self-diagnostics for major failures; periodic secondary injection test for drift",
         default_severity=8, default_occurrence=2, default_detection=5),

    # --- Mitsubishi CAC1-10-M3 / CAC2-10-M3 (Transformer Differential) ---------
    dict(id="cac-01", category=_CAC, component="DC control power",
         failure_mode="Loss of DC supply to the relay",
         potential_cause="Station battery/charger failure, tripped supply fuse, loose terminal",
         potential_effect="Complete loss of primary 87T protection; unit may rely solely on backup (e.g. Overall 87O) if available",
         detection_method="DC supply monitoring alarm",
         default_severity=9, default_occurrence=2, default_detection=3),
    dict(id="cac-02", category=_CAC, component="CT input circuit (any winding)",
         failure_mode="Open circuit (broken/loose CT secondary wiring)",
         potential_cause="Loose/broken CT secondary wiring, terminal block issue",
         potential_effect="False differential current appears - risk of spurious trip of a healthy transformer",
         detection_method="CT supervision alarm if fitted; otherwise diagnosed after the fact from the trip pattern",
         default_severity=8, default_occurrence=3, default_detection=4),
    dict(id="cac-03", category=_CAC, component="CT matching tap / setting",
         failure_mode="Tap set incorrectly",
         potential_cause="Wrong tap value entered vs. the calculated T1/T2/T3, or changed without re-verifying mismatch",
         potential_effect="Chronic false restraint imbalance - masks a real internal fault, or nuisance-trips under normal load swings",
         detection_method="Commissioning mismatch check (this app's own live Mismatch % calculation), periodic settings audit",
         default_severity=7, default_occurrence=3, default_detection=4),
    dict(id="cac-04", category=_CAC, component="Delta/Wye CT compensation wiring",
         failure_mode="Incorrect wiring of the required √3 / 30° compensation on a Delta-connected CT set",
         potential_cause="Wiring error during CT installation or after a wiring change",
         potential_effect="Large apparent differential current at healthy full load - high risk of trip on energization or normal loading",
         detection_method="Commissioning load-current phasor check, √3 magnitude sanity check",
         default_severity=8, default_occurrence=2, default_detection=5),
    dict(id="cac-05", category=_CAC, component="Trip output contact",
         failure_mode="Contact stuck closed (welded)",
         potential_cause="Contact arcing/wear over service life",
         potential_effect="Spurious unit/transformer trip",
         detection_method="Trip circuit supervision, periodic maintenance test",
         default_severity=7, default_occurrence=2, default_detection=4),
    dict(id="cac-06", category=_CAC, component="Trip output contact",
         failure_mode="Contact fails to close on command",
         potential_cause="Contact wear, driver circuit failure, mechanical binding",
         potential_effect="Failure to trip on a real internal transformer fault - internal faults escalate rapidly (e.g. oil fire risk)",
         detection_method="Trip circuit supervision (loss-of-continuity alarm), periodic trip test",
         default_severity=10, default_occurrence=2, default_detection=3),
    dict(id="cac-07", category=_CAC, component="Firmware / logic",
         failure_mode="Misoperation from a firmware defect or corrupted logic",
         potential_cause="Firmware bug, corrupted memory, incomplete/failed firmware update",
         potential_effect="Unpredictable - false trip or failure to trip",
         detection_method="Manufacturer firmware advisories, periodic function test",
         default_severity=8, default_occurrence=1, default_detection=6),
    dict(id="cac-08", category=_CAC, component="Watchdog / self-test",
         failure_mode="Self-test failure that is itself not reported",
         potential_cause="Fault inside the self-test/watchdog subsystem, or the alarm path to SCADA is down",
         potential_effect="Relay is actually degraded or failed but appears healthy - protection gap goes unnoticed",
         detection_method="Periodic manual functional test",
         default_severity=9, default_occurrence=1, default_detection=7),
    dict(id="cac-09", category=_CAC, component="HOC (unrestrained instantaneous) setting",
         failure_mode="Threshold set too low relative to expected inrush",
         potential_cause="Setting error, not re-verified against inrush current studies",
         potential_effect="Nuisance trip on transformer energization inrush",
         detection_method="Energization event review, settings audit against the Calculation/Discussion in the settings document",
         default_severity=5, default_occurrence=3, default_detection=4),
    dict(id="cac-10", category=_CAC, component="Restraint / bias calculation",
         failure_mode="Internal relay algorithm computes the wrong restraint/bias point",
         potential_cause="Firmware defect in the specific restraint-slope implementation",
         potential_effect="Relay trips or fails to trip at the wrong point vs. its own published characteristic",
         detection_method="Periodic test-point verification against the calculated CAL. line (this app's own Simulate & Test feature)",
         default_severity=7, default_occurrence=1, default_detection=5),

    # --- Multilin SR469 / GE 869 (Motor Protection) -----------------------------
    dict(id="sr469-01", category=_SR469, component="DC control power",
         failure_mode="Loss of DC supply to the relay",
         potential_cause="Station battery/charger failure, tripped supply fuse, loose terminal",
         potential_effect="Complete loss of motor protection - motor left unprotected against overload/short circuit/ground fault",
         detection_method="DC supply monitoring alarm",
         default_severity=8, default_occurrence=2, default_detection=3),
    dict(id="sr469-02", category=_SR469, component="CT input circuit",
         failure_mode="Open circuit (broken/loose CT secondary wiring)",
         potential_cause="Loose/broken CT secondary wiring, terminal block issue",
         potential_effect="Apparent current unbalance - possible nuisance trip on unbalance protection, or reduced overload sensitivity",
         detection_method="Unbalance alarm pattern, periodic secondary injection test",
         default_severity=7, default_occurrence=3, default_detection=4),
    dict(id="sr469-03", category=_SR469, component="Ground CT (zero-sequence) circuit",
         failure_mode="Wiring fault or incorrect CT ratio setting",
         potential_cause="Wiring damage, wrong ratio entered at commissioning",
         potential_effect="Ground fault protection desensitized, or false ground fault alarms",
         detection_method="Periodic ground fault injection test",
         default_severity=7, default_occurrence=2, default_detection=5),
    dict(id="sr469-04", category=_SR469, component="Trip output contact",
         failure_mode="Contact stuck closed (welded)",
         potential_cause="Contact arcing/wear over service life",
         potential_effect="Spurious motor trip, unplanned process/fan outage",
         detection_method="Trip circuit supervision, periodic maintenance test",
         default_severity=5, default_occurrence=2, default_detection=4),
    dict(id="sr469-05", category=_SR469, component="Trip output contact",
         failure_mode="Contact fails to close on command",
         potential_cause="Contact wear, driver circuit failure, mechanical binding",
         potential_effect="Failure to trip on a locked-rotor/overload condition - risk of winding thermal damage before any backup intervenes",
         detection_method="Trip circuit supervision",
         default_severity=8, default_occurrence=2, default_detection=3),
    dict(id="sr469-06", category=_SR469, component="Thermal (overload) model",
         failure_mode="Thermal replica algorithm fault or thermal memory lost on reset",
         potential_cause="Firmware fault in the thermal model, thermal memory not retained across a relay power cycle",
         potential_effect="Relay under- or over-estimates accumulated heating - allows a start into an already-hot rotor, or nuisance-trips a cold motor",
         detection_method="Periodic thermal-model verification against the settings document's own safe-stall-time curve",
         default_severity=7, default_occurrence=2, default_detection=5),
    dict(id="sr469-07", category=_SR469, component="Firmware / logic",
         failure_mode="Misoperation from a firmware defect or corrupted logic",
         potential_cause="Firmware bug, corrupted memory, incomplete/failed firmware update",
         potential_effect="Unpredictable - false trip or failure to trip",
         detection_method="Manufacturer firmware advisories, periodic function test",
         default_severity=7, default_occurrence=1, default_detection=6),
    dict(id="sr469-08", category=_SR469, component="Watchdog / self-test",
         failure_mode="Self-test failure that is itself not reported",
         potential_cause="Fault inside the self-test/watchdog subsystem, or the alarm path to SCADA is down",
         potential_effect="Relay is actually degraded or failed but appears healthy - protection gap goes unnoticed",
         detection_method="Periodic manual functional test",
         default_severity=8, default_occurrence=1, default_detection=7),
    dict(id="sr469-09", category=_SR469, component="HMI / settings access",
         failure_mode="Incorrect settings applied (FLA, CT ratio, curve multiplier)",
         potential_cause="Human error during commissioning, or FLA not updated after a motor rewind/replacement",
         potential_effect="Chronic under- or over-protection depending on the direction of the error",
         detection_method="Settings audit against motor nameplate, periodic review after any motor maintenance",
         default_severity=7, default_occurrence=3, default_detection=4),
    dict(id="sr469-10", category=_SR469, component="RTD inputs (if monitored)",
         failure_mode="RTD wiring fault or sensor failure",
         potential_cause="Open/short RTD circuit, damaged sensor or leads",
         potential_effect="Loss of RTD-based thermal backup protection, and/or a spurious high-temperature alarm/trip",
         detection_method="RTD \"sensor fail\" self-diagnostic (most modern relays flag this distinctly)",
         default_severity=5, default_occurrence=3, default_detection=3),
]
