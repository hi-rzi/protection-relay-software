/*
 * Page-specific glue for the EXCT page — field lists + page quirks, mirroring
 * views/transformer_exct.py's script body. All heavy math (relay evaluation,
 * fault current, CT-tap trig) is server-side via /api/transformer/exct/recompute;
 * cheap arithmetic (mismatch %, bias/min-op floors, boundary injection, sweep
 * table) is client-side per the Phase 1 plan. Ported from transformer_gsut.js —
 * the one notable difference is SETTINGS_FIELDS has no fault_kv_hv, since
 * EXCT's settings doc doesn't use a tap-adjusted HV voltage distinct from the
 * fault-current base (see web/services/exct.py's module docstring).
 */
(function () {
  "use strict";

  var RECOMPUTE_URL = "/api/transformer/exct/recompute";
  var SETTINGS_SHEET_URL = "/api/transformer/exct/settings-sheet.csv";
  var REPORT_PDF_URL = "/api/transformer/exct/report.pdf";
  var PHASES = ["Phase A", "Phase B", "Phase C"];
  var SETTINGS_FIELDS = [
    "mva", "kv_hv", "kv_lv", "ct_hv", "ct_lv", "ct_sec", "ct_conn_hv", "ct_conn_lv",
    "tap_hv", "tap_lv", "bias", "min_operate", "hoc",
    "fault_mva_base", "z_pct", "x_over_r", "ct_withstand_a",
  ];

  var initialData = JSON.parse(document.getElementById("initial-data").textContent);
  var equipmentTag = "exct";

  var state = {
    selectedPreset: initialData.default_preset_name,
    isCustom: initialData.default_preset_name === "Custom Profile",
    phaseInputs: {},
    userEditedPhaseInputs: {}, // phase -> true once user has typed into that phase's fields
    testPoints: [],
    sweepRows: [],
    lastResponse: null,
    lastFaultSim: null,
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
    // Radios that the server-side settings dict also expects as plain keys
    // (web/services/exct.py's compute_fault_current reads these from `settings`,
    // not as top-level payload fields).
    var faultSide = document.querySelector('input[name="fault_side"]:checked');
    var asymBasis = document.querySelector('input[name="asym_basis"]:checked');
    if (faultSide) settings.fault_side = faultSide.value;
    if (asymBasis) settings.asym_basis = asymBasis.value;
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
      mva: data.mva, kv_hv: data.kv_hv, kv_lv: data.kv_lv,
      ct_lv: data.ct_lv, ct_conn_hv: data.ct_conn_hv, ct_conn_lv: data.ct_conn_lv,
      ct_sec: data.ct_sec, tap_hv: data.tap_hv, tap_lv: data.tap_lv,
      bias: data.bias, min_operate: data.min_operate, hoc: data.hoc,
      fault_mva_base: data.fault_mva_base, z_pct: data.z_pct, x_over_r: data.x_over_r,
      ct_withstand_a: data.ct_withstand_a,
    };
    window.SettingsForm.applyFields(document, fieldValues);
    if (state.isCustom) {
      document.getElementById("f-ct_hv-number").value = data.ct_hv;
    } else {
      document.getElementById("f-ct_hv").value = data.ct_hv;
    }
    document.getElementById("preset-confidence-warning").hidden = state.isCustom;

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
  // Live (client-side) captions on the Current Settings tab
  // -----------------------------------------------------------------------
  function updateSettingsCaptions() {
    var settings = currentSettings();
    var ctHv = settings.ct_hv, ctLv = settings.ct_lv, ctSec = settings.ct_sec;
    document.getElementById("ct-effective-ratio-caption").innerHTML =
      "Effective ratio &rarr; HV: <strong>" + ctHv.toFixed(0) + ":" + ctSec.toFixed(0) + "</strong> " +
      "(= " + (ctHv / ctSec).toFixed(1) + ":1)  |  LV: <strong>" + ctLv.toFixed(0) + ":" + ctSec.toFixed(0) + "</strong> " +
      "(= " + (ctLv / ctSec).toFixed(1) + ":1)";

    var m = window.SettingsForm.computeMismatch(settings);

    document.getElementById("t1e-caption").textContent = m.t1_e !== null
      ? "T1_E (reference, this winding alone) ≈ " + m.t1_e.toFixed(3) : "";
    document.getElementById("t2e-caption").textContent = m.t2_e !== null
      ? "T2_E (reference, this winding alone) ≈ " + m.t2_e.toFixed(3) : "";

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
      : "Set the HV/LV taps above first to compute a mismatch-based floor for these settings.";

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
      overall.textContent = "Overall status: set the HV/LV taps above to compute a status.";
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
  // Recompute (server round-trip for evaluate_protection / fault current)
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
  // Live Simulation tab
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
    PHASES.forEach(function (phase, idx) {
      var vals = state.phaseInputs[phase] || { i_hv: 0, a_hv: 0, i_lv: 0, a_lv: 0 };
      var wrap = document.createElement("div");
      wrap.className = "phase-expander";
      wrap.innerHTML =
        '<div class="phase-expander__header">' + phase + ' Settings</div>' +
        '<div class="phase-expander__body">' +
        '<div class="field"><label>HV Primary Amps [A]</label><input type="number" class="pi-input" data-phase="' + phase + '" data-key="i_hv" value="' + vals.i_hv + '"></div>' +
        '<div class="field"><label>HV Angle (°)</label><input type="number" class="pi-input" data-phase="' + phase + '" data-key="a_hv" value="' + vals.a_hv + '"></div>' +
        '<div class="field"><label>LV Primary Amps [A]</label><input type="number" class="pi-input" data-phase="' + phase + '" data-key="i_lv" value="' + vals.i_lv + '"></div>' +
        '<div class="field"><label>LV Angle (°)</label><input type="number" class="pi-input" data-phase="' + phase + '" data-key="a_lv" value="' + vals.a_lv + '"></div>' +
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
      title: "Transformer Differential Bias Characteristic",
      xaxis: { title: "Restraint Current I_rest (" + unitLabel + ")", range: [0, xMax] },
      yaxis: { title: "Differential/Operating Current I_op (" + unitLabel + ")", range: [0, Math.max(built.yUpper, hocVal + (useAmps ? ampsBase : 1))] },
      height: 500,
      annotations: window.Charts.regionAnnotations(),
    });
  }

  // -----------------------------------------------------------------------
  // Commissioning & Injection tab (client-side, cheap)
  // -----------------------------------------------------------------------
  function thresholdOf(riPu, settings) {
    return Math.max(settings.min_operate / 100.0, (settings.bias / 100.0) * riPu);
  }

  function renderBoundaryInjection(data) {
    var settings = currentSettings();
    var defaults = { "Phase A": 0.5, "Phase B": 2.5, "Phase C": 5.0 };
    var grid = document.getElementById("boundary-injection-grid");
    grid.innerHTML = "";
    PHASES.forEach(function (p) {
      var boundaryOp = thresholdOf(defaults[p], settings);
      var secHv = (defaults[p] + boundaryOp / 2.0) * data.windings[0].i_rated_sec;
      var secLv = (defaults[p] - boundaryOp / 2.0) * data.windings[1].i_rated_sec;
      var div = document.createElement("div");
      div.innerHTML =
        "<strong>" + p + "</strong>" +
        '<div class="field"><label>Target Restraint (pu)</label><input type="number" step="0.1" value="' + defaults[p] + '" class="boundary-r-input" data-phase="' + p + '"></div>' +
        '<div class="metric"><span class="metric__label">Boundary I_op</span><span class="metric__value">' + boundaryOp.toFixed(3) + ' pu</span></div>' +
        '<p class="caption">HV inject: <strong>' + secHv.toFixed(3) + ' A</strong></p>' +
        '<p class="caption">LV inject: <strong>' + secLv.toFixed(3) + ' A</strong></p>';
      grid.appendChild(div);
    });
    grid.querySelectorAll(".boundary-r-input").forEach(function (el) {
      el.addEventListener("input", function () {
        var p = el.getAttribute("data-phase");
        var r = parseFloat(el.value) || 0;
        var boundaryOp = thresholdOf(r, currentSettings());
        var secHv = (r + boundaryOp / 2.0) * data.windings[0].i_rated_sec;
        var secLv = (r - boundaryOp / 2.0) * data.windings[1].i_rated_sec;
        var container = el.closest("div");
        container.querySelector(".metric__value").textContent = boundaryOp.toFixed(3) + " pu";
        var captions = container.querySelectorAll(".caption");
        captions[0].innerHTML = "HV inject: <strong>" + secHv.toFixed(3) + " A</strong>";
        captions[1].innerHTML = "LV inject: <strong>" + secLv.toFixed(3) + " A</strong>";
      });
    });
  }

  function generateSweepTable() {
    var settings = currentSettings();
    var data = state.lastResponse;
    if (!data) return;
    var start = parseFloat(document.querySelector('[data-field="sweep_start"]').value) || 0;
    var end = parseFloat(document.querySelector('[data-field="sweep_end"]').value) || 6;
    var step = parseFloat(document.querySelector('[data-field="sweep_step"]').value) || 0.5;
    if (end <= start || step <= 0) {
      alert("Sweep End must be greater than Sweep Start, and Sweep Step must be positive.");
      return;
    }
    var rows = [];
    for (var v = start; v <= end + step / 2.0; v += step) {
      var boundaryOp = thresholdOf(v, settings);
      var secHv = (v + boundaryOp / 2.0) * data.windings[0].i_rated_sec;
      var secLv = (v - boundaryOp / 2.0) * data.windings[1].i_rated_sec;
      rows.push({ i_rest_pu: Math.round(v * 1000) / 1000, boundary_op_pu: Math.round(boundaryOp * 1000) / 1000, hv_injection_a: Math.round(secHv * 1000) / 1000, lv_injection_a: Math.round(secLv * 1000) / 1000 });
    }
    state.sweepRows = rows;
    var table = document.getElementById("sweep-table");
    var tbody = table.querySelector("tbody");
    tbody.innerHTML = "";
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + r.i_rest_pu + "</td><td>" + r.boundary_op_pu + "</td><td>" + r.hv_injection_a + "</td><td>" + r.lv_injection_a + "</td>";
      tbody.appendChild(tr);
    });
    table.hidden = false;
    document.getElementById("download-sweep-csv-btn").hidden = false;
  }

  function downloadSweepCsv() {
    var header = "I_rest (pu),Boundary I_op (pu),HV Injection (A),LV Injection (A)\n";
    var lines = state.sweepRows.map(function (r) { return [r.i_rest_pu, r.boundary_op_pu, r.hv_injection_a, r.lv_injection_a].join(","); });
    var blob = new Blob([header + lines.join("\n")], { type: "text/csv" });
    var stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "").replace(/(\d{8})(\d{4})/, "$1_$2");
    window.Recompute.downloadBlob(blob, "87ET_Sweep_Test_Table_" + stamp + ".csv");
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
        lv: { amps: document.getElementById("tp-raw-lv-amps").value, angle: document.getElementById("tp-raw-lv-angle").value },
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
  // Fault Current Analysis tab
  // -----------------------------------------------------------------------
  function renderFault(data) {
    if (!data.fault) return;
    var fault = data.fault;
    document.getElementById("fault-sym-value").textContent = fault.fault_calc.i_sym_amps.toLocaleString(undefined, { maximumFractionDigits: 0 }) + " A";
    document.getElementById("fault-asym-value").textContent = fault.fault_calc.i_asym_amps.toLocaleString(undefined, { maximumFractionDigits: 0 }) + " A (" + fault.fault_calc.asym_factor.toFixed(2) + "x)";
    document.getElementById("fault-relay-sec-label").textContent = "Relay Secondary Current (" + fault.fault_side + " CT)";
    document.getElementById("fault-relay-sec-value").textContent = fault.relay_sec_fault.toFixed(1) + " A";

    var withstandAlert = document.getElementById("withstand-alert");
    if (fault.within_withstand) {
      withstandAlert.className = "alert alert--success";
      withstandAlert.textContent = "Through-fault relay secondary current (" + fault.relay_sec_fault.toFixed(1) + " A) is within the " + fault.ct_withstand_a.toFixed(0) + " A withstand limit.";
    } else {
      withstandAlert.className = "alert alert--warning";
      withstandAlert.textContent = "Through-fault relay secondary current (" + fault.relay_sec_fault.toFixed(1) + " A) EXCEEDS the " + fault.ct_withstand_a.toFixed(0) + " A withstand limit.";
    }

    var wf = fault.waveform;
    window.Charts.plot("fault-waveform-chart", [
      { x: wf.t_ms, y: wf.i_amps, mode: "lines", name: "Instantaneous Current", line: { color: "#DC2626", width: 2 } },
    ], {
      xaxis: { title: "Time (ms, t=0 is fault inception)" },
      yaxis: { title: "Instantaneous Current (A)" },
      height: 320,
      shapes: [
        { type: "line", x0: 0, x1: wf.t_ms[wf.t_ms.length - 1], y0: wf.i_peak_sym, y1: wf.i_peak_sym, line: { color: "#94A3B8", width: 1, dash: "dot" } },
        { type: "line", x0: 0, x1: wf.t_ms[wf.t_ms.length - 1], y0: -wf.i_peak_sym, y1: -wf.i_peak_sym, line: { color: "#94A3B8", width: 1, dash: "dot" } },
      ],
    });

    if (fault.sim) renderFaultSim(fault.sim);
  }

  function faultSimBaseLayout() {
    return { xaxis: { title: "Time (ms, t=0 is fault inception)" }, yaxis: { title: "Primary Current (A)" }, height: 340 };
  }

  function renderFaultSim(sim) {
    state.lastFaultSim = sim;
    var caption = document.getElementById("fault-sim-caption");
    var preloadMs = 40.0;
    if (sim.kind === "trip") {
      caption.className = "alert alert--success";
      caption.textContent = "Trip signal reaches the breaker — total clearing time " + sim.total_ms.toFixed(0) + " ms (" + (sim.total_ms / (1000 / 60)).toFixed(1) + " cycles). " + sim.status;
      window.Charts.plot("fault-sim-chart", [{
        x: [-preloadMs, 0, 0, sim.total_ms, sim.total_ms, sim.total_ms + 40.0],
        y: [sim.preload_current, sim.preload_current, sim.sim_current_primary, sim.sim_current_primary, 0.0, 0.0],
        mode: "lines", line: { color: "#DC2626", width: 3 }, name: "Fault Current",
      }], Object.assign(faultSimBaseLayout(), {
        shapes: [
          { type: "line", x0: sim.relay_ms, x1: sim.relay_ms, y0: 0, y1: sim.sim_current_primary, line: { color: "#F59E0B", width: 2, dash: "dot" } },
          { type: "line", x0: sim.total_ms, x1: sim.total_ms, y0: 0, y1: sim.sim_current_primary, line: { color: "#16A34A", width: 2, dash: "dash" } },
        ],
      }));
    } else {
      caption.className = "alert alert--info";
      caption.textContent = "Relay stays SECURE — no trip. " + sim.status;
      window.Charts.plot("fault-sim-chart", [{
        x: [-preloadMs, 0, 0, sim.window_ms],
        y: [sim.preload_current, sim.preload_current, sim.sim_current_primary, sim.sim_current_primary],
        mode: "lines", line: { color: "#DC2626", width: 3 }, name: "Fault Current",
      }], faultSimBaseLayout());
    }
  }

  function runFaultSim() {
    var scenario = document.querySelector('input[name="fault_scenario"]:checked').value;
    var relayCycles = parseFloat(document.querySelector('[data-field="relay_operate_cycles"]').value) || 1.5;
    var breakerCycles = parseFloat(document.querySelector('[data-field="breaker_cycles"]').value) || 5.0;
    recompute({
      fault_sim: { fault_scenario: scenario, relay_operate_cycles: relayCycles, breaker_cycles: breakerCycles },
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
      ["LV CT Ratio", settings.ct_lv.toFixed(0) + ":" + settings.ct_sec.toFixed(0)],
      ["T1 (HV Tap)", settings.tap_hv.toFixed(3)],
      ["T2 (LV Tap)", settings.tap_lv.toFixed(3)],
      ["Bias, τ (%)", settings.bias.toFixed(0)],
      ["Minimum Operate (%)", settings.min_operate.toFixed(0)],
      ["HOC (x tap current)", settings.hoc.toFixed(2)],
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
      window.Recompute.downloadBlob(blob, "EXCT_Settings_Sheet.csv");
    });
  }

  function exportReport() {
    window.Recompute.postForBlob(REPORT_PDF_URL, Object.assign(buildRecomputePayload(), { selected_preset: state.selectedPreset })).then(function (blob) {
      window.Recompute.downloadBlob(blob, "EXCT_Differential_Protection_Report.pdf");
    });
  }

  function saveProfile() {
    var name = document.getElementById("profile-name").value || "EXCT Profile";
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
      "HV (23kV) Nominal Rated Current: <strong>" + w[0].i_rated_pri.toFixed(1) + " A</strong>  |  " +
      "LV (900V) Nominal Rated Current: <strong>" + w[1].i_rated_pri.toFixed(1) + " A</strong>";
    renderVerdictTable(data.evals);
    renderBiasCurveChart(data);
    renderBoundaryInjection(data);
    renderTestPointTable();
    renderTestPointCurve();
    renderFault(data);
    renderSettingsSheet();
  }

  // -----------------------------------------------------------------------
  // Wiring
  // -----------------------------------------------------------------------
  function init() {
    window.SettingsForm.initTabs(document);
    window.SettingsForm.bindSliderPairs(document, onSettingsChanged);

    document.querySelectorAll("#equipment-page .tabpanel input, #equipment-page .tabpanel select").forEach(function (el) {
      if (el.closest("#phase-inputs") || el.closest("#boundary-injection-grid")) return; // handled separately
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

    document.querySelectorAll('input[name="fault_side"], input[name="asym_basis"]').forEach(function (el) {
      el.addEventListener("change", onSettingsChanged);
    });
    document.getElementById("run-fault-sim-btn").addEventListener("click", runFaultSim);

    document.getElementById("export-report-btn").addEventListener("click", exportReport);
    document.getElementById("download-settings-sheet-btn").addEventListener("click", downloadSettingsSheet);
    document.getElementById("save-profile-btn").addEventListener("click", saveProfile);

    // Initial paint
    updateSettingsCaptions();
    recompute();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
