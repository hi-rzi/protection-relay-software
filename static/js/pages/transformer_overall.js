/*
 * Page-specific glue for the Overall GSUT-GEN backup differential page —
 * field lists + page quirks, mirroring views/transformer_overall.py's script
 * body. All heavy math (relay evaluation, CT-tap trig) is server-side via
 * /api/transformer/overall/recompute; cheap arithmetic (mismatch %, bias/
 * min-op floors, single-winding injection/sweep math) is client-side, same
 * split as the GSUT reference page.
 *
 * Two genuinely new pieces of logic vs. the 2-winding GSUT page:
 *  - 3rd winding (UAT) threaded through every settings/phase-input/test-point
 *    field list, and a 3-column phase-input layout (.phase-expander__body--3col).
 *  - Single-winding-energize commissioning: a <select> of winding_names picks
 *    which ONE winding gets a test current (the other two stay at 0A) — the
 *    standard way to commission a 3-restraint relay, since there's no single
 *    unique way to split a target differential across three currents.
 */
(function () {
  "use strict";

  var RECOMPUTE_URL = "/api/transformer/overall/recompute";
  var SETTINGS_SHEET_URL = "/api/transformer/overall/settings-sheet.csv";
  var REPORT_PDF_URL = "/api/transformer/overall/report.pdf";
  var PHASES = ["Phase A", "Phase B", "Phase C"];
  var SETTINGS_FIELDS = [
    "mva", "kv_hv", "kv_gen", "kv_uat", "ct_hv", "ct_gen", "ct_uat", "ct_sec",
    "ct_conn_hv", "ct_conn_gen", "ct_conn_uat",
    "tap_hv", "tap_gen", "tap_uat", "bias", "min_operate", "hoc",
  ];

  var initialData = JSON.parse(document.getElementById("initial-data").textContent);
  var equipmentTag = "overall";
  var windingNames = initialData.winding_names || ["HV (525kV)", "Generator (23kV)", "UAT (23kV)"];

  var state = {
    selectedPreset: initialData.default_preset_name,
    isCustom: initialData.default_preset_name === "Custom Profile",
    phaseInputs: {},
    userEditedPhaseInputs: {}, // phase -> true once user has typed into that phase's fields
    testPoints: [],
    sweepRows: [],
    lastResponse: null,
  };

  // -----------------------------------------------------------------------
  // Settings collection
  // -----------------------------------------------------------------------
  function currentSettings() {
    var settings = {};
    SETTINGS_FIELDS.forEach(function (field) {
      var el = document.querySelector('[data-field="' + field + '"]:not([hidden])') ||
        document.querySelector('[data-field="' + field + '"]');
      if (!el) return;
      // ct_hv can be a <select> (standard preset) or a <number> (Custom Profile) —
      // whichever wrap is currently visible wins.
      if (field === "ct_hv") {
        var visibleWrap = state.isCustom
          ? document.getElementById("ct-hv-number-wrap")
          : document.getElementById("ct-hv-select-wrap");
        var input = visibleWrap.querySelector("[data-field]");
        settings.ct_hv = parseFloat(input.value);
        return;
      }
      var raw = el.value;
      var num = parseFloat(raw);
      settings[field] = (!isNaN(num) && raw !== "") ? num : raw;
    });
    return settings;
  }

  function conventionAndPolarity() {
    var conv = document.querySelector('input[name="convention"]:checked');
    var pol = document.querySelector('input[name="ct_polarity"]:checked');
    return {
      convention: conv ? conv.value : "IEEE",
      ct_polarity: pol ? pol.value : "OPPOSITE",
    };
  }

  // -----------------------------------------------------------------------
  // Preset handling
  // -----------------------------------------------------------------------
  function applyPreset(presetName) {
    state.selectedPreset = presetName;
    state.isCustom = presetName === "Custom Profile";
    var data = initialData.presets[presetName];
    document.getElementById("ct-hv-select-wrap").hidden = state.isCustom;
    document.getElementById("ct-hv-number-wrap").hidden = !state.isCustom;
    var fieldValues = {
      mva: data.mva, kv_hv: data.kv_hv, kv_gen: data.kv_gen, kv_uat: data.kv_uat,
      ct_gen: data.ct_gen, ct_uat: data.ct_uat,
      ct_conn_hv: data.ct_conn_hv, ct_conn_gen: data.ct_conn_gen, ct_conn_uat: data.ct_conn_uat,
      ct_sec: data.ct_sec, tap_hv: data.tap_hv, tap_gen: data.tap_gen, tap_uat: data.tap_uat,
      bias: data.bias, min_operate: data.min_operate, hoc: data.hoc,
    };
    window.SettingsForm.applyFields(document, fieldValues);
    if (state.isCustom) {
      document.getElementById("f-ct_hv-number").value = data.ct_hv;
    } else {
      document.getElementById("f-ct_hv").value = data.ct_hv;
    }

    // Reset transient live-sim/test-point state to a fresh page's worth
    state.userEditedPhaseInputs = {};
    state.testPoints = [];
    renderTestPointTable();

    onSettingsChanged();
  }

  function showToast(message) {
    var toast = document.getElementById("toast");
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(function () { toast.hidden = true; }, 2500);
  }

  // -----------------------------------------------------------------------
  // 3-winding mismatch — client-side port of web/services/overall.py's
  // compute_mismatch(), built from settings-form.js's already-generic (N-
  // winding) suggestCtMatchingTap / mismatchRatioPct / suggestBiasSettings
  // helpers rather than duplicating their formulas here.
  // -----------------------------------------------------------------------
  function computeMismatch3(settings) {
    var mva = parseFloat(settings.mva) || 0;
    var kvHv = parseFloat(settings.kv_hv) || 0;
    var kvGen = parseFloat(settings.kv_gen) || 0;
    var kvUat = parseFloat(settings.kv_uat) || 0;
    var ctHv = parseFloat(settings.ct_hv) || 0;
    var ctGen = parseFloat(settings.ct_gen) || 0;
    var ctUat = parseFloat(settings.ct_uat) || 0;
    var ctSec = parseFloat(settings.ct_sec) || 5.0;
    var tapHv = parseFloat(settings.tap_hv) || 1.0;
    var tapGen = parseFloat(settings.tap_gen) || 1.0;
    var tapUat = parseFloat(settings.tap_uat) || 1.0;
    var ctConnHv = String(settings.ct_conn_hv || "DELTA").toUpperCase();
    var ctConnGen = String(settings.ct_conn_gen || "WYE").toUpperCase();
    var ctConnUat = String(settings.ct_conn_uat || "WYE").toUpperCase();

    var dfHv = ctConnHv === "DELTA" ? 1.7320508 : 1.0;
    var dfGen = ctConnGen === "DELTA" ? 1.7320508 : 1.0;
    var dfUat = ctConnUat === "DELTA" ? 1.7320508 : 1.0;
    var iRatedPriHv = kvHv > 0 ? (mva * 1000.0) / (1.7320508 * kvHv) : 0.0;
    var iRatedPriGen = kvGen > 0 ? (mva * 1000.0) / (1.7320508 * kvGen) : 0.0;
    var iRatedPriUat = kvUat > 0 ? (mva * 1000.0) / (1.7320508 * kvUat) : 0.0;

    var t1e = window.SettingsForm.suggestCtMatchingTap(iRatedPriHv, ctHv, ctSec, dfHv);
    var t2e = window.SettingsForm.suggestCtMatchingTap(iRatedPriGen, ctGen, ctSec, dfGen);
    var t3e = window.SettingsForm.suggestCtMatchingTap(iRatedPriUat, ctUat, ctSec, dfUat);

    var iRelayHv = (ctHv > 0 && ctSec > 0) ? (iRatedPriHv / (ctHv / ctSec) * dfHv * tapHv) : null;
    var iRelayGen = (ctGen > 0 && ctSec > 0) ? (iRatedPriGen / (ctGen / ctSec) * dfGen * tapGen) : null;
    var iRelayUat = (ctUat > 0 && ctSec > 0) ? (iRatedPriUat / (ctUat / ctSec) * dfUat * tapUat) : null;
    var calcMismatch = window.SettingsForm.mismatchRatioPct([iRelayHv, iRelayGen, iRelayUat]);

    var suggestion = window.SettingsForm.suggestBiasSettings(calcMismatch || 0.0, 3);

    return {
      t1_e: t1e, t2_e: t2e, t3_e: t3e,
      calc_mismatch_pct: calcMismatch, suggestion: suggestion,
      effective_ratio_hv: ctSec ? (ctHv / ctSec) : null,
      effective_ratio_gen: ctSec ? (ctGen / ctSec) : null,
      effective_ratio_uat: ctSec ? (ctUat / ctSec) : null,
    };
  }

  // -----------------------------------------------------------------------
  // Live (client-side) captions on the Current Settings tab
  // -----------------------------------------------------------------------
  function updateSettingsCaptions() {
    var settings = currentSettings();
    var ctHv = settings.ct_hv, ctGen = settings.ct_gen, ctUat = settings.ct_uat, ctSec = settings.ct_sec;
    document.getElementById("ct-effective-ratio-caption").innerHTML =
      "Effective ratio &rarr; HV: <strong>" + ctHv.toFixed(0) + ":" + ctSec.toFixed(0) + "</strong> (= " + (ctHv / ctSec).toFixed(1) + ":1)  |  " +
      "Generator: <strong>" + ctGen.toFixed(0) + ":" + ctSec.toFixed(0) + "</strong> (= " + (ctGen / ctSec).toFixed(1) + ":1)  |  " +
      "UAT: <strong>" + ctUat.toFixed(0) + ":" + ctSec.toFixed(0) + "</strong> (= " + (ctUat / ctSec).toFixed(1) + ":1)";

    var m = computeMismatch3(settings);

    document.getElementById("t1e-caption").textContent = m.t1_e !== null
      ? "T1_E (reference, this winding alone) ≈ " + m.t1_e.toFixed(3) : "";
    document.getElementById("t2e-caption").textContent = m.t2_e !== null
      ? "T2_E (reference, this winding alone) ≈ " + m.t2_e.toFixed(3) : "";
    document.getElementById("t3e-caption").textContent = m.t3_e !== null
      ? "T3_E (reference, this winding alone) ≈ " + m.t3_e.toFixed(3) : "";

    var mismatchEl = document.getElementById("mismatch-value");
    var mismatchAlert = document.getElementById("mismatch-alert");
    if (m.calc_mismatch_pct !== null) {
      mismatchEl.textContent = m.calc_mismatch_pct.toFixed(2) + "%";
      mismatchAlert.hidden = false;
      if (m.calc_mismatch_pct < 5.0) {
        mismatchAlert.className = "alert alert--success";
        mismatchAlert.textContent = m.calc_mismatch_pct.toFixed(2) + "% mismatch — low, well within the usual rule-of-thumb range.";
      } else {
        mismatchAlert.className = "alert alert--warning";
        mismatchAlert.textContent = m.calc_mismatch_pct.toFixed(2) + "% mismatch — unusually high. Review the tap selection before applying.";
      }
    } else {
      mismatchEl.textContent = "—";
      mismatchAlert.hidden = true;
    }

    var suggestion = m.suggestion;
    document.getElementById("bias-floor-caption").textContent = (m.calc_mismatch_pct !== null)
      ? "Rule-of-thumb floor for the current " + m.calc_mismatch_pct.toFixed(2) + "% mismatch: Bias ≈ " +
        suggestion.bias_pct.toFixed(0) + "%, Min Operate ≈ " + suggestion.min_operate_pct.toFixed(0) +
        "%, HOC ≈ " + suggestion.hoc_multiple.toFixed(0) + "x tap current. Engineering review required."
      : "Set the taps above first to compute a mismatch-based floor for these settings.";

    var bias = settings.bias, minOp = settings.min_operate, hoc = settings.hoc;
    var biasAlert = document.getElementById("bias-alert");
    if (bias >= suggestion.bias_pct) {
      biasAlert.className = "alert alert--success";
      biasAlert.textContent = "Clears the " + suggestion.bias_pct.toFixed(0) + "% floor.";
    } else {
      biasAlert.className = "alert alert--warning";
      biasAlert.textContent = "Below the " + suggestion.bias_pct.toFixed(0) + "% floor for this mismatch.";
    }
    var minOpAlert = document.getElementById("min-operate-alert");
    if (minOp >= suggestion.min_operate_pct) {
      minOpAlert.className = "alert alert--success";
      minOpAlert.textContent = "Clears the " + suggestion.min_operate_pct.toFixed(0) + "% floor.";
    } else {
      minOpAlert.className = "alert alert--warning";
      minOpAlert.textContent = "Below the " + suggestion.min_operate_pct.toFixed(0) + "% floor.";
    }
    var hocAlert = document.getElementById("hoc-alert");
    if (hoc <= suggestion.hoc_multiple + 2.0) {
      hocAlert.className = "alert alert--success";
      hocAlert.textContent = "Clears inrush at this relay family's typical " + suggestion.hoc_multiple.toFixed(0) + "x floor.";
    } else {
      hocAlert.className = "alert alert--info";
      hocAlert.textContent = "Higher setting — more secure against inrush/CT saturation misoperation.";
    }

    var overall = document.getElementById("overall-status-caption");
    if (m.calc_mismatch_pct === null) {
      overall.className = "alert alert--info";
      overall.textContent = "Overall status: set the taps above to compute a status.";
    } else if (m.calc_mismatch_pct < 5.0 && bias >= suggestion.bias_pct && minOp >= suggestion.min_operate_pct) {
      overall.className = "alert alert--success";
      overall.textContent = "Overall status: all settings shown clear their recommended margins. Engineering approval is still required before issue.";
    } else {
      overall.className = "alert alert--warning";
      overall.textContent = "Overall status: one or more settings above need review before this is applied.";
    }

    window.ProjectStore.mirror(equipmentTag, Object.assign({}, settings, { calc_mismatch_pct: m.calc_mismatch_pct }));
  }

  // -----------------------------------------------------------------------
  // Live Preview mini chart (Current Settings tab)
  // -----------------------------------------------------------------------
  function renderSettingsPreview() {
    var settings = currentSettings();
    var bias = settings.bias / 100.0, minOp = settings.min_operate / 100.0;
    var xPu = [];
    for (var i = 0; i <= 200; i++) xPu.push((6.0 * i) / 200);
    var yPu = xPu.map(function (x) { return Math.max(minOp, bias * x); });
    var built = window.Charts.biasCurveTraces(xPu, yPu, { useAmps: false });
    window.Charts.plot("settings-preview-chart", built.traces, {
      xaxis: { title: "Restraint Current (pu)" },
      yaxis: { title: "Differential/Operating Current (pu)", range: [0, built.yUpper] },
      height: 320,
      showlegend: false,
      annotations: window.Charts.regionAnnotations(),
    });
  }

  // -----------------------------------------------------------------------
  // Recompute (server round-trip for evaluate_protection)
  // -----------------------------------------------------------------------
  function buildRecomputePayload(extra) {
    var cp = conventionAndPolarity();
    var payload = {
      settings: currentSettings(),
      convention: cp.convention,
      ct_polarity: cp.ct_polarity,
      phase_inputs: state.phaseInputs,
    };
    return Object.assign(payload, extra || {});
  }

  var recomputeDebounced = window.Recompute.debounce(function () { recompute(); }, 250);

  function recompute(extra) {
    return window.Recompute.postJSON(RECOMPUTE_URL, buildRecomputePayload(extra)).then(function (data) {
      state.lastResponse = data;
      renderAfterRecompute(data);
      return data;
    }).catch(function (err) {
      console.error(err);
    });
  }

  function onSettingsChanged() {
    updateSettingsCaptions();
    if (document.getElementById("settings-preview-chart").hidden === false) renderSettingsPreview();
    recomputeDebounced();
  }

  // -----------------------------------------------------------------------
  // Live Simulation tab — 3-column phase inputs (HV / Generator / UAT)
  // -----------------------------------------------------------------------
  function ensurePhaseInputDefaults(defaultAngles) {
    PHASES.forEach(function (phase) {
      if (!state.userEditedPhaseInputs[phase]) {
        state.phaseInputs[phase] = defaultAngles[phase];
      }
    });
  }

  function renderPhaseInputs() {
    var container = document.getElementById("phase-inputs");
    container.innerHTML = "";
    PHASES.forEach(function (phase) {
      var vals = state.phaseInputs[phase] || { i_hv: 0, a_hv: 0, i_gen: 0, a_gen: 0, i_uat: 0, a_uat: 0 };
      var wrap = document.createElement("div");
      wrap.className = "phase-expander";
      wrap.innerHTML =
        '<div class="phase-expander__header">' + phase + ' Settings</div>' +
        '<div class="phase-expander__body phase-expander__body--3col">' +
        '<div>' +
        '<div class="field"><label>HV Primary Amps [A]</label><input type="number" class="pi-input" data-phase="' + phase + '" data-key="i_hv" value="' + vals.i_hv + '"></div>' +
        '<div class="field"><label>HV Angle (°)</label><input type="number" class="pi-input" data-phase="' + phase + '" data-key="a_hv" value="' + vals.a_hv + '"></div>' +
        '</div>' +
        '<div>' +
        '<div class="field"><label>Generator Primary Amps [A]</label><input type="number" class="pi-input" data-phase="' + phase + '" data-key="i_gen" value="' + vals.i_gen + '"></div>' +
        '<div class="field"><label>Generator Angle (°)</label><input type="number" class="pi-input" data-phase="' + phase + '" data-key="a_gen" value="' + vals.a_gen + '"></div>' +
        '</div>' +
        '<div>' +
        '<div class="field"><label>UAT Primary Amps [A]</label><input type="number" class="pi-input" data-phase="' + phase + '" data-key="i_uat" value="' + vals.i_uat + '"></div>' +
        '<div class="field"><label>UAT Angle (°)</label><input type="number" class="pi-input" data-phase="' + phase + '" data-key="a_uat" value="' + vals.a_uat + '"></div>' +
        '</div>' +
        '</div>';
      container.appendChild(wrap);
    });
    container.querySelectorAll(".pi-input").forEach(function (el) {
      el.addEventListener("input", function () {
        var phase = el.getAttribute("data-phase"), key = el.getAttribute("data-key");
        state.userEditedPhaseInputs[phase] = true;
        state.phaseInputs[phase][key] = parseFloat(el.value) || 0;
        recomputeDebounced();
      });
    });
  }

  function renderVerdictTable(evals) {
    var tbody = document.querySelector("#verdict-table tbody");
    tbody.innerHTML = "";
    var anyTrip = false;
    PHASES.forEach(function (p) {
      var e = evals[p];
      if (e.is_trip) anyTrip = true;
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + p + "</td><td>" + e.i_op_pu.toFixed(3) + "</td><td>" + e.i_rest_pu.toFixed(3) +
        "</td><td>" + e.i_threshold_pu.toFixed(3) + "</td><td>" + e.status + "</td>";
      tbody.appendChild(tr);
    });
    var banner = document.getElementById("trip-status-banner");
    if (anyTrip) {
      banner.className = "alert alert--danger";
      banner.textContent = "PROTECTIVE RELAY TRIP INITIATED!";
    } else {
      banner.className = "alert alert--success";
      banner.textContent = "SYSTEM HEALTHY (Stability / Restraint Zone)";
    }
  }

  function renderWindingMags(evals) {
    var lines = PHASES.map(function (p) {
      var mags = evals[p].winding_mags_pu;
      var parts = windingNames.map(function (n, i) { return n + ": " + mags[i].toFixed(3) + " pu"; });
      return "<strong>" + p + "</strong>: " + parts.join(" | ");
    });
    document.getElementById("winding-mags-caption").innerHTML = lines.join("<br>");
  }

  function chartUnitsFor(radioName) {
    var el = document.querySelector('input[name="' + radioName + '"]:checked');
    return el ? el.value === "amps" : false;
  }

  function renderBiasCurveChart(data) {
    var useAmps = chartUnitsFor("chart_units");
    var ampsBase = data.amps_base;
    var built = window.Charts.biasCurveTraces(data.bias_curve.x_pu, data.bias_curve.y_pu, { useAmps: useAmps, ampsBase: ampsBase });
    var traces = built.traces.slice();

    var hocVal = useAmps ? data.hoc_pu * ampsBase : data.hoc_pu;
    var xMax = built.xMax;
    traces.push({ x: [0, xMax], y: [hocVal, hocVal], mode: "lines", name: "HOC (Unrestrained)", line: { color: window.Charts.COLORS.hoc, width: 2, dash: "dash" } });

    var phaseColors = { "Phase A": "red", "Phase B": "green", "Phase C": "blue" };
    PHASES.forEach(function (p) {
      var e = data.evals[p];
      var px = useAmps ? e.i_rest_pu * ampsBase : e.i_rest_pu;
      var py = useAmps ? e.i_op_pu * ampsBase : e.i_op_pu;
      traces.push({
        x: [px], y: [py], mode: "markers+text", name: p, text: [p], textposition: "top center",
        marker: { size: 14, color: phaseColors[p], symbol: e.is_trip ? "x" : "circle" },
      });
    });

    var unitLabel = useAmps ? "A" : "pu";
    window.Charts.plot("bias-curve-chart", traces, {
      title: "Overall GSUT-GEN Differential Bias Characteristic",
      xaxis: { title: "Restraint Current I_rest (" + unitLabel + ")", range: [0, xMax] },
      yaxis: { title: "Differential/Operating Current I_op (" + unitLabel + ")", range: [0, Math.max(built.yUpper, hocVal + (useAmps ? ampsBase : 1))] },
      height: 500,
      annotations: window.Charts.regionAnnotations(),
    });
  }

  // -----------------------------------------------------------------------
  // Commissioning & Injection tab — single-winding-energize
  // -----------------------------------------------------------------------
  function selectedInjWindingIdx() {
    var sel = document.getElementById("inj-winding-select");
    return parseInt(sel.value, 10) || 0;
  }

  function injectionCurrentPu() {
    var el = document.querySelector('[data-field="inj_current_pu"]');
    return el ? (parseFloat(el.value) || 1.0) : 1.0;
  }

  function renderInjectionResult(injection) {
    if (!injection) return;
    document.getElementById("inj-secondary-value").textContent = injection.inject_secondary_amps.toFixed(3) + " A";
    document.getElementById("inj-iop-value").textContent = injection.i_op_pu.toFixed(3) + " pu";
    document.getElementById("inj-irest-value").textContent = injection.i_rest_pu.toFixed(3) + " pu";
    document.getElementById("inj-threshold-value").textContent = injection.i_threshold_pu.toFixed(3) + " pu";
    var alertEl = document.getElementById("inj-status-alert");
    alertEl.className = injection.is_trip ? "alert alert--danger" : "alert alert--success";
    alertEl.textContent = "Status: " + injection.status;
  }

  function refreshInjection() {
    recompute({
      injection: { winding_idx: selectedInjWindingIdx(), current_pu: injectionCurrentPu() },
    });
  }

  function generateSweepTable() {
    var start = parseFloat(document.querySelector('[data-field="sweep_start"]').value) || 0;
    var end = parseFloat(document.querySelector('[data-field="sweep_end"]').value) || 6;
    var step = parseFloat(document.querySelector('[data-field="sweep_step"]').value) || 0.5;
    if (end <= start || step <= 0) {
      alert("Sweep End must be greater than Sweep Start, and Sweep Step must be positive.");
      return;
    }
    var windingIdx = selectedInjWindingIdx();
    var windingName = windingNames[windingIdx];
    document.getElementById("sweep-injection-col").textContent = windingName + " Injection (A)";
    recompute({
      sweep: { winding_idx: windingIdx, sweep_start: start, sweep_end: end, sweep_step: step },
    }).then(function (data) {
      if (!data.sweep) return;
      state.sweepRows = data.sweep;
      var table = document.getElementById("sweep-table");
      var tbody = table.querySelector("tbody");
      tbody.innerHTML = "";
      data.sweep.forEach(function (r) {
        var tr = document.createElement("tr");
        tr.innerHTML = "<td>" + r.test_current_pu + "</td><td>" + r.injection_a + "</td><td>" + r.i_op_pu +
          "</td><td>" + r.i_rest_pu + "</td><td>" + r.i_threshold_pu + "</td><td>" + r.status + "</td>";
        tbody.appendChild(tr);
      });
      table.hidden = false;
      document.getElementById("download-sweep-csv-btn").hidden = false;
    });
  }

  function downloadSweepCsv() {
    var windingName = windingNames[selectedInjWindingIdx()];
    var header = "Test Current (pu)," + windingName + " Injection (A),I_op (pu),I_rest (pu),Threshold (pu),Status\n";
    var lines = state.sweepRows.map(function (r) {
      return [r.test_current_pu, r.injection_a, r.i_op_pu, r.i_rest_pu, r.i_threshold_pu, r.status].join(",");
    });
    var blob = new Blob([header + lines.join("\n")], { type: "text/csv" });
    var stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "").replace(/(\d{8})(\d{4})/, "$1_$2");
    window.Recompute.downloadBlob(blob, "87OA_Sweep_Test_Table_" + stamp + ".csv");
  }

  // -----------------------------------------------------------------------
  // Curve & Test Points tab
  // -----------------------------------------------------------------------
  function tpSourceIsRaw() {
    var el = document.querySelector('input[name="tp_source"]:checked');
    return el && el.value === "raw";
  }

  function addTestPoint(e) {
    e.preventDefault();
    var data = state.lastResponse;
    if (!data) return;
    var phase = document.getElementById("tp-phase").value;
    var label = document.getElementById("tp-label").value;

    function push(restraintAmps, diffAmps) {
      state.testPoints.push({ phase: phase, restraint_a: restraintAmps, diff_a: diffAmps, label: label });
      renderTestPointTable();
      renderTestPointCurve();
      document.getElementById("add-test-point-form").reset();
    }

    if (!tpSourceIsRaw()) {
      var unitIsAmps = document.querySelector('input[name="tp_unit"]:checked').value === "amps";
      var r = parseFloat(document.getElementById("tp-restraint").value) || 0;
      var d = parseFloat(document.getElementById("tp-diff").value) || 0;
      var restraintAmps = unitIsAmps ? r : r * data.amps_base;
      var diffAmps = unitIsAmps ? d : d * data.amps_base;
      push(restraintAmps, diffAmps);
    } else {
      var raw = {
        hv: { amps: document.getElementById("tp-raw-hv-amps").value, angle: document.getElementById("tp-raw-hv-angle").value },
        gen: { amps: document.getElementById("tp-raw-gen-amps").value, angle: document.getElementById("tp-raw-gen-angle").value },
        uat: { amps: document.getElementById("tp-raw-uat-amps").value, angle: document.getElementById("tp-raw-uat-angle").value },
      };
      window.Recompute.postJSON(RECOMPUTE_URL, buildRecomputePayload({ raw_test_point: raw })).then(function (resp) {
        var ev = resp.raw_test_point_eval;
        push(ev.i_rest_pu * resp.amps_base, ev.i_op_pu * resp.amps_base);
      });
    }
  }

  function renderTestPointTable() {
    var wrap = document.getElementById("tp-table-wrap");
    var emptyHint = document.getElementById("tp-empty-hint");
    if (state.testPoints.length === 0) {
      wrap.hidden = true;
      emptyHint.hidden = false;
      return;
    }
    wrap.hidden = false;
    emptyHint.hidden = true;
    var ampsBase = (state.lastResponse && state.lastResponse.amps_base) || 1;
    var inPu = document.querySelector('input[name="tp_table_unit"]:checked').value === "pu";
    document.querySelector(".tp-restraint-col").textContent = inPu ? "Restraint (pu)" : "Restraint (A)";
    document.querySelector(".tp-diff-col").textContent = inPu ? "Measured Diff (pu)" : "Measured Diff (A)";
    var tbody = document.querySelector("#tp-table tbody");
    tbody.innerHTML = "";
    state.testPoints.forEach(function (tp) {
      var r = inPu ? tp.restraint_a / ampsBase : tp.restraint_a;
      var d = inPu ? tp.diff_a / ampsBase : tp.diff_a;
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + tp.phase + "</td><td>" + r.toFixed(3) + "</td><td>" + d.toFixed(3) + "</td><td>" + (tp.label || "") + "</td>";
      tbody.appendChild(tr);
    });
  }

  function renderTestPointCurve() {
    var data = state.lastResponse;
    if (!data) return;
    var useAmps = chartUnitsFor("comm_chart_units");
    var ampsBase = data.amps_base;
    var connectMode = document.querySelector('input[name="cal_source"]:checked').value === "connect";
    var traces = [];

    if (connectMode && state.testPoints.length >= 2) {
      var sorted = state.testPoints.slice().sort(function (a, b) { return a.restraint_a - b.restraint_a; });
      var x = sorted.map(function (tp) { return useAmps ? tp.restraint_a : tp.restraint_a / ampsBase; });
      var y = sorted.map(function (tp) { return useAmps ? tp.diff_a : tp.diff_a / ampsBase; });
      traces.push({ x: x, y: y, mode: "lines", name: "CAL.", line: { color: "#2E8B57", width: 3 } });
    } else {
      var built = window.Charts.biasCurveTraces(data.bias_curve.x_pu, data.bias_curve.y_pu, { useAmps: useAmps, ampsBase: ampsBase });
      traces = built.traces.slice();
    }

    var tpColors = { "Phase A": "#D63384", "Phase B": "#6C757D", "Phase C": "#1E3A8A", "Other": "#F59E0B" };
    var tpSymbols = { "Phase A": "square", "Phase B": "triangle-up", "Phase C": "square", "Other": "diamond" };
    state.testPoints.forEach(function (tp) {
      var px = useAmps ? tp.restraint_a : tp.restraint_a / ampsBase;
      var py = useAmps ? tp.diff_a : tp.diff_a / ampsBase;
      traces.push({
        x: [px], y: [py], mode: "markers", name: tp.phase + (tp.label ? " (" + tp.label + ")" : ""),
        marker: { size: 13, color: tpColors[tp.phase] || "#F59E0B", symbol: tpSymbols[tp.phase] || "diamond" },
      });
    });

    var unitLabel = useAmps ? "A" : "pu";
    window.Charts.plot("tp-curve-chart", traces, {
      title: "Differential Bias Characteristic Curve",
      xaxis: { title: "Restraint Current (" + unitLabel + ")" },
      yaxis: { title: "Diff. Current (" + unitLabel + ")" },
      height: 450,
      annotations: connectMode && state.testPoints.length >= 2 ? [] : window.Charts.regionAnnotations(),
    });
  }

  // -----------------------------------------------------------------------
  // Settings Summary & Approval tab
  // -----------------------------------------------------------------------
  function renderSettingsSheet() {
    var settings = currentSettings();
    var cp = conventionAndPolarity();
    var rows = [
      ["HV CT Ratio", settings.ct_hv.toFixed(0) + ":" + settings.ct_sec.toFixed(0)],
      ["Generator CT Ratio", settings.ct_gen.toFixed(0) + ":" + settings.ct_sec.toFixed(0)],
      ["UAT CT Ratio", settings.ct_uat.toFixed(0) + ":" + settings.ct_sec.toFixed(0)],
      ["T1 (HV Tap)", settings.tap_hv.toFixed(3)],
      ["T2 (Generator Tap)", settings.tap_gen.toFixed(3)],
      ["T3 (UAT Tap)", settings.tap_uat.toFixed(3)],
      ["Bias, τ (%)", settings.bias.toFixed(0)],
      ["Minimum Operate (%)", settings.min_operate.toFixed(0)],
      ["HOC (x tap value current)", settings.hoc.toFixed(2)],
      ["Restraint Standard", cp.convention],
      ["CT Polarity Reference", cp.ct_polarity],
    ];
    var tbody = document.querySelector("#settings-sheet-table tbody");
    tbody.innerHTML = "";
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + r[0] + "</td><td>" + r[1] + "</td>";
      tbody.appendChild(tr);
    });
  }

  function downloadSettingsSheet() {
    window.Recompute.postForBlob(SETTINGS_SHEET_URL, buildRecomputePayload()).then(function (blob) {
      window.Recompute.downloadBlob(blob, "Overall_GSUT-GEN_Settings_Sheet.csv");
    });
  }

  function exportReport() {
    window.Recompute.postForBlob(REPORT_PDF_URL, Object.assign(buildRecomputePayload(), { selected_preset: state.selectedPreset })).then(function (blob) {
      window.Recompute.downloadBlob(blob, "Overall_GSUT-GEN_Protection_Report.pdf");
    });
  }

  function saveProfile() {
    var name = document.getElementById("profile-name").value || "Overall GSUT-GEN Profile";
    window.Profile.save(equipmentTag, name, currentSettings());
  }

  function loadProfile(file) {
    window.Profile.load(file, equipmentTag).then(function (payload) {
      window.SettingsForm.applyFields(document, payload.settings);
      showToast("Loaded profile: " + (payload.profile_name || "Untitled"));
      onSettingsChanged();
    }).catch(function (err) {
      alert("Could not load profile: " + err.message);
    });
  }

  // -----------------------------------------------------------------------
  // Master render after each /recompute response
  // -----------------------------------------------------------------------
  function renderAfterRecompute(data) {
    ensurePhaseInputDefaults(data.default_angles);
    renderPhaseInputs();
    var w = data.windings;
    document.getElementById("rated-current-info").className = "alert alert--info";
    document.getElementById("rated-current-info").innerHTML =
      "HV Rated: <strong>" + w[0].i_rated_pri.toFixed(1) + " A</strong>  |  " +
      "Generator Rated: <strong>" + w[1].i_rated_pri.toFixed(1) + " A</strong>  |  " +
      "UAT Rated: <strong>" + w[2].i_rated_pri.toFixed(1) + " A</strong>";
    renderVerdictTable(data.evals);
    renderWindingMags(data.evals);
    renderBiasCurveChart(data);
    if (data.injection) renderInjectionResult(data.injection);
    renderTestPointTable();
    renderTestPointCurve();
    renderSettingsSheet();
  }

  // -----------------------------------------------------------------------
  // Wiring
  // -----------------------------------------------------------------------
  function init() {
    window.SettingsForm.initTabs(document);
    window.SettingsForm.bindSliderPairs(document, onSettingsChanged);

    document.querySelectorAll("#equipment-page .tabpanel input, #equipment-page .tabpanel select").forEach(function (el) {
      if (el.closest("#phase-inputs")) return; // handled separately
      if (el.id === "inj-winding-select" || el.closest("[data-slider-pair='inj_current_pu']") || el.getAttribute("data-field") === "inj_current_pu") return; // handled separately
      el.addEventListener("change", function () {
        if (SETTINGS_FIELDS.indexOf(el.getAttribute("data-field")) !== -1 || el.name === "convention" || el.name === "ct_polarity" || el.name === "chart_units") {
          onSettingsChanged();
          if (el.name === "chart_units" && state.lastResponse) renderBiasCurveChart(state.lastResponse);
        }
      });
    });

    document.getElementById("preset-select").addEventListener("change", function (e) {
      applyPreset(e.target.value);
      showToast("Loaded " + e.target.value);
    });
    document.getElementById("reset-preset-btn").addEventListener("click", function () {
      applyPreset(state.selectedPreset);
      showToast("Reset to " + state.selectedPreset + " defaults.");
    });
    document.getElementById("profile-load-input").addEventListener("change", function (e) {
      if (e.target.files[0]) loadProfile(e.target.files[0]);
    });

    document.getElementById("show-preview-btn").addEventListener("click", function () {
      var chart = document.getElementById("settings-preview-chart");
      chart.hidden = !chart.hidden;
      if (!chart.hidden) renderSettingsPreview();
    });

    // Single-winding injection wiring
    document.getElementById("inj-winding-select").addEventListener("change", refreshInjection);
    document.querySelectorAll('[data-slider-pair="inj_current_pu"], [data-number-pair="inj_current_pu"]').forEach(function (el) {
      el.addEventListener("input", function () { refreshInjection(); });
    });

    document.getElementById("generate-sweep-btn").addEventListener("click", generateSweepTable);
    document.getElementById("download-sweep-csv-btn").addEventListener("click", downloadSweepCsv);

    document.getElementById("add-test-point-form").addEventListener("submit", addTestPoint);
    document.querySelectorAll('input[name="tp_source"]').forEach(function (el) {
      el.addEventListener("change", function () {
        document.getElementById("tp-restraint-fields").hidden = tpSourceIsRaw();
        document.getElementById("tp-raw-fields").hidden = !tpSourceIsRaw();
      });
    });
    document.querySelectorAll('input[name="tp_table_unit"]').forEach(function (el) { el.addEventListener("change", renderTestPointTable); });
    document.querySelectorAll('input[name="comm_chart_units"], input[name="cal_source"]').forEach(function (el) { el.addEventListener("change", renderTestPointCurve); });
    document.getElementById("tp-remove-btn").addEventListener("click", function () {
      var idx = parseInt(document.getElementById("tp-remove-idx").value, 10) || 0;
      if (idx >= 0 && idx < state.testPoints.length) {
        state.testPoints.splice(idx, 1);
        renderTestPointTable();
        renderTestPointCurve();
      }
    });
    document.getElementById("tp-clear-btn").addEventListener("click", function () {
      state.testPoints = [];
      renderTestPointTable();
      renderTestPointCurve();
    });

    document.getElementById("export-report-btn").addEventListener("click", exportReport);
    document.getElementById("download-settings-sheet-btn").addEventListener("click", downloadSettingsSheet);
    document.getElementById("save-profile-btn").addEventListener("click", saveProfile);

    // Initial paint
    updateSettingsCaptions();
    recompute().then(function () { refreshInjection(); });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
