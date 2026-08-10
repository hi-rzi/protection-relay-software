/*
 * Page-specific glue for the Generator (87G) page — field lists + page
 * quirks, mirroring views/generator.py's script body. All heavy math (relay
 * evaluation, fault current) is server-side via /api/generator/recompute;
 * cheap arithmetic (mismatch %, bias/min-op floors, boundary injection,
 * sweep table, the settings-preview curve) is client-side per the Phase 1
 * plan. The Generator-specific settings-advisor equivalent (mismatch with
 * no CT-matching tap, pickup/slope floor checks) lives here, NOT in the
 * shared settings-form.js, since it isn't the transformer-family math that
 * file already carries.
 */
(function () {
  "use strict";

  var RECOMPUTE_URL = "/api/generator/recompute";
  var SETTINGS_SHEET_URL = "/api/generator/settings-sheet.csv";
  var REPORT_PDF_URL = "/api/generator/report.pdf";
  var PHASES = ["Phase A", "Phase B", "Phase C"];
  var COMMON_FIELDS = ["mva", "kv", "ct_n", "ct_t", "ct_sec", "x1_pu", "asym_factor", "external_fault_ka", "ct_withstand_a"];

  var initialData = JSON.parse(document.getElementById("initial-data").textContent);
  var equipmentTag = "generator";

  var state = {
    mode: initialData.default_mode,
    selectedPreset: initialData.default_preset_name,
    isCustom: initialData.default_preset_name === "Custom Profile",
    phaseInputs: {},
    userEditedPhaseInputs: {},
    testPoints: [],
    sweepRows: [],
    lastResponse: null,
    lastFaultSim: null,
  };

  // -----------------------------------------------------------------------
  // Settings collection (mode-gated — see module doc comment above)
  // -----------------------------------------------------------------------
  function readField(field) {
    var el = document.querySelector('[data-field="' + field + '"]');
    if (!el) return undefined;
    var raw = el.value;
    var num = parseFloat(raw);
    return (!isNaN(num) && raw !== "") ? num : raw;
  }

  function currentSettings() {
    var settings = {};
    COMMON_FIELDS.forEach(function (field) { settings[field] = readField(field); });

    if (state.mode === "GENERATOR_LEGACY") {
      settings.target_amps = readField("legacy_target_amps");
      settings.slope1 = readField("legacy_slope1");
    } else {
      settings.pickup = readField("pickup");
      settings.slope1 = readField("slope1");
      settings.break1 = readField("break1");
      settings.slope2 = readField("slope2");
      settings.break2 = readField("break2");
      var cb = document.getElementById("f-unrestrained_enabled");
      settings.unrestrained_enabled = !!(cb && cb.checked);
      if (settings.unrestrained_enabled) settings.unrestrained = readField("unrestrained");
    }
    return settings;
  }

  function conventionAndPolarity() {
    var conv = document.querySelector('input[name="convention"]:checked');
    var pol = document.querySelector('input[name="ct_polarity"]:checked');
    return {
      convention: conv ? conv.value : "IEEE",
      ct_polarity: pol ? pol.value : "SAME",
    };
  }

  // -----------------------------------------------------------------------
  // Generator's own settings-advisor equivalent (no CT-matching tap — the
  // Neutral/Terminal CT ratios should normally be identical)
  // -----------------------------------------------------------------------
  function computeGeneratorMismatch(settings) {
    var mva = parseFloat(settings.mva) || 0;
    var kv = parseFloat(settings.kv) || 0;
    var ctN = parseFloat(settings.ct_n) || 0;
    var ctT = parseFloat(settings.ct_t) || 0;
    var ctSec = parseFloat(settings.ct_sec) || 5.0;

    var iRatedSecN = (kv > 0 && ctN > 0 && ctSec > 0) ? ((mva * 1000.0) / (1.7320508 * kv)) / (ctN / ctSec) : 0.0;
    var iRatedSecT = (kv > 0 && ctT > 0 && ctSec > 0) ? ((mva * 1000.0) / (1.7320508 * kv)) / (ctT / ctSec) : 0.0;

    var calcMismatch = window.SettingsForm.mismatchRatioPct([iRatedSecN, iRatedSecT]);
    var suggestion = window.SettingsForm.suggestBiasSettings(calcMismatch || 0.0, 2);
    return { calc_mismatch_pct: calcMismatch, suggestion: suggestion };
  }

  function ratedSecN(settings) {
    var mva = parseFloat(settings.mva) || 0;
    var kv = parseFloat(settings.kv) || 0;
    var ctN = parseFloat(settings.ct_n) || 0;
    var ctSec = parseFloat(settings.ct_sec) || 5.0;
    var iRatedPri = kv > 0 ? (mva * 1000.0) / (1.7320508 * kv) : 0.0;
    var effRatioN = ctSec > 0 ? ctN / ctSec : ctN;
    return effRatioN > 0 ? iRatedPri / effRatioN : 0.0;
  }

  // Client-side mirror of AdvancedDifferentialRelay.calculate_trip_threshold(),
  // used only for the cheap settings-preview chart (no test-point evaluation,
  // no unrestrained line) — the authoritative curve always comes from
  // /api/generator/recompute's bias_curve.
  function clientTripThreshold(settings, mode) {
    if (mode === "GENERATOR_LEGACY") {
      var secN = ratedSecN(settings);
      var pickupPu = secN > 0 ? (parseFloat(settings.target_amps) || 0) / secN : 0;
      var slope = (parseFloat(settings.slope1) || 0) / 100.0;
      return function (x) { return pickupPu + slope * x; };
    }
    var pickup = parseFloat(settings.pickup) || 0;
    var s1 = (parseFloat(settings.slope1) || 0) / 100.0;
    var s2 = (parseFloat(settings.slope2) || 0) / 100.0;
    var b1 = parseFloat(settings.break1) || 0;
    var b2 = parseFloat(settings.break2) || 0;
    return function (x) {
      if (x <= b1) return pickup;
      if (x <= b2) return pickup + s1 * (x - b1);
      return pickup + s1 * (b2 - b1) + s2 * (x - b2);
    };
  }

  function clientMaxX(settings, mode) {
    if (mode === "GENERATOR_LEGACY") return 6.0;
    return Math.max(6.0, (parseFloat(settings.break2) || 0) + 1.0);
  }

  // -----------------------------------------------------------------------
  // Preset / mode handling
  // -----------------------------------------------------------------------
  function populatePresetSelect(mode) {
    var select = document.getElementById("preset-select");
    var names = Object.keys(initialData.presets[mode]);
    select.innerHTML = "";
    names.forEach(function (name) {
      var opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      select.appendChild(opt);
    });
    return names[0];
  }

  function applyPreset(mode, presetName) {
    state.mode = mode;
    state.selectedPreset = presetName;
    state.isCustom = presetName === "Custom Profile";
    var data = initialData.presets[mode][presetName];

    document.getElementById("mode-g60-fields").hidden = mode !== "GENERATOR";
    document.getElementById("mode-legacy-fields").hidden = mode !== "GENERATOR_LEGACY";

    var commonValues = {
      mva: data.mva, kv: data.kv, ct_n: data.ct_n, ct_t: data.ct_t, ct_sec: data.ct_sec || 5.0,
      x1_pu: data.x1_pu, asym_factor: data.asym_factor,
      external_fault_ka: data.external_fault_ka, ct_withstand_a: data.ct_withstand_a,
    };
    window.SettingsForm.applyFields(document, commonValues);

    if (mode === "GENERATOR_LEGACY") {
      window.SettingsForm.applyFields(document, { legacy_target_amps: data.target_amps, legacy_slope1: data.slope1 });
    } else {
      window.SettingsForm.applyFields(document, {
        pickup: data.pickup, slope1: data.slope1, break1: data.break1, slope2: data.slope2, break2: data.break2,
      });
      var cb = document.getElementById("f-unrestrained_enabled");
      cb.checked = false;
      document.getElementById("unrestrained-wrap").hidden = true;
    }

    document.getElementById("preset-confidence-warning").hidden = state.isCustom;

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
    var ctN = settings.ct_n, ctT = settings.ct_t, ctSec = settings.ct_sec;
    document.getElementById("ct-effective-ratio-caption").innerHTML =
      "Effective ratio &rarr; Neutral: <strong>" + ctN.toFixed(0) + ":" + ctSec.toFixed(0) + "</strong> " +
      "(= " + (ctN / ctSec).toFixed(1) + ":1)  |  Terminal: <strong>" + ctT.toFixed(0) + ":" + ctSec.toFixed(0) + "</strong> " +
      "(= " + (ctT / ctSec).toFixed(1) + ":1)";

    var m = computeGeneratorMismatch(settings);
    var mismatchEl = document.getElementById("mismatch-value");
    var mismatchAlert = document.getElementById("mismatch-alert");
    if (m.calc_mismatch_pct !== null) {
      mismatchEl.textContent = m.calc_mismatch_pct.toFixed(2) + "%";
      mismatchAlert.hidden = false;
      if (m.calc_mismatch_pct < 0.5) {
        mismatchAlert.className = "alert alert--success";
        mismatchAlert.textContent = "Neutral and Terminal CT ratios match — as expected (this relay has no CT-matching tap to absorb a mismatch).";
      } else {
        mismatchAlert.className = "alert alert--warning";
        mismatchAlert.textContent = m.calc_mismatch_pct.toFixed(2) + "% mismatch — this relay has no CT-matching tap, so the ratios should normally be identical. Recheck unless intentional.";
      }
    } else {
      mismatchEl.textContent = "—";
      mismatchAlert.hidden = true;
    }

    var suggestion = m.suggestion;
    var allClear;
    if (state.mode === "GENERATOR_LEGACY") {
      var targetAlert = document.getElementById("target-amps-alert");
      if (settings.target_amps < 0.1) {
        targetAlert.className = "alert alert--warning";
        targetAlert.textContent = "Below GEK-34124E's recommended 0.1A floor — the manual advises against this.";
      } else if (settings.target_amps < 0.25) {
        targetAlert.className = "alert alert--info";
        targetAlert.textContent = "Within range, but the rear contact may need up to ~0.25A to close — verify during commissioning.";
      } else {
        targetAlert.className = "alert alert--success";
        targetAlert.textContent = "Clears GEK-34124E's recommended floor and the ~0.25A closing-current guidance.";
      }
      allClear = m.calc_mismatch_pct !== null && m.calc_mismatch_pct < 0.5 && settings.target_amps >= 0.1;
    } else {
      var pickupAlert = document.getElementById("pickup-alert");
      var slope1Alert = document.getElementById("slope1-alert");
      var mismatched = m.calc_mismatch_pct !== null && m.calc_mismatch_pct >= 0.5;
      if (mismatched && settings.pickup * 100 < suggestion.min_operate_pct) {
        pickupAlert.className = "alert alert--warning";
        pickupAlert.textContent = "CT ratios above are mismatched (" + m.calc_mismatch_pct.toFixed(2) + "%) and Pickup is below the " + suggestion.min_operate_pct.toFixed(0) + "% floor that would compensate for it.";
      } else {
        pickupAlert.className = "alert alert--info";
        pickupAlert.textContent = "Lower = more sensitive to small internal faults. Generator differential pickup is conventionally set low (5-10% typical).";
      }
      if (mismatched && settings.slope1 < suggestion.bias_pct) {
        slope1Alert.className = "alert alert--warning";
        slope1Alert.textContent = "CT ratios above are mismatched (" + m.calc_mismatch_pct.toFixed(2) + "%) and Slope 1 is below the " + suggestion.bias_pct.toFixed(0) + "% floor that would compensate for it.";
      } else {
        slope1Alert.className = "alert alert--info";
        slope1Alert.textContent = "Higher = more secure against nuisance trips, but less sensitive to small internal faults.";
      }
      allClear = m.calc_mismatch_pct !== null && m.calc_mismatch_pct < 0.5;
      if (mismatched) {
        allClear = allClear && settings.pickup * 100 >= suggestion.min_operate_pct && settings.slope1 >= suggestion.bias_pct;
      }
    }

    var overall = document.getElementById("overall-status-caption");
    if (m.calc_mismatch_pct === null) {
      overall.className = "alert alert--info";
      overall.textContent = "Overall status: enter the CT ratios above to compute a status.";
    } else if (allClear) {
      overall.className = "alert alert--success";
      overall.textContent = "Overall status: all settings shown clear their recommended margins. Engineering approval is still required before issue.";
    } else {
      overall.className = "alert alert--warning";
      overall.textContent = "Overall status: one or more settings above need review before this is applied.";
    }

    window.ProjectStore.mirror(equipmentTag, Object.assign({}, settings, {
      mode: state.mode, calc_mismatch_pct: m.calc_mismatch_pct,
    }));
  }

  // -----------------------------------------------------------------------
  // Live Preview mini chart (Current Settings tab)
  // -----------------------------------------------------------------------
  function renderSettingsPreview() {
    var settings = currentSettings();
    var maxX = clientMaxX(settings, state.mode);
    var thresholdFn = clientTripThreshold(settings, state.mode);
    var xPu = [];
    for (var i = 0; i <= 200; i++) xPu.push((maxX * i) / 200);
    var yPu = xPu.map(thresholdFn);
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
      mode: state.mode,
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
    PHASES.forEach(function (phase) {
      var vals = state.phaseInputs[phase] || { i_N: 0, a_N: 0, i_T: 0, a_T: 0 };
      var wrap = document.createElement("div");
      wrap.className = "phase-expander";
      wrap.innerHTML =
        '<div class="phase-expander__header">' + phase + ' Settings</div>' +
        '<div class="phase-expander__body">' +
        '<div class="field"><label>Neutral Side Primary Amps [A]</label><input type="number" class="pi-input" data-phase="' + phase + '" data-key="i_N" value="' + vals.i_N + '"></div>' +
        '<div class="field"><label>Neutral Side Angle (°)</label><input type="number" class="pi-input" data-phase="' + phase + '" data-key="a_N" value="' + vals.a_N + '"></div>' +
        '<div class="field"><label>Terminal Side Primary Amps [A]</label><input type="number" class="pi-input" data-phase="' + phase + '" data-key="i_T" value="' + vals.i_T + '"></div>' +
        '<div class="field"><label>Terminal Side Angle (°)</label><input type="number" class="pi-input" data-phase="' + phase + '" data-key="a_T" value="' + vals.a_T + '"></div>' +
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
    var xMax = built.xMax;
    var yUpperBase = built.yUpper;

    if (data.has_unrestrained) {
      var hsVal = useAmps ? data.i_unrestrained * ampsBase : data.i_unrestrained;
      traces.push({ x: [0, xMax], y: [hsVal, hsVal], mode: "lines", name: "Unrestrained High-Set", line: { color: window.Charts.COLORS.hoc, width: 2, dash: "dash" } });
      yUpperBase = Math.max(yUpperBase, hsVal + (useAmps ? ampsBase : 1));
    }

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
      title: "Differential Slope Characteristic Curve",
      xaxis: { title: "Restraint Current I_rest (" + unitLabel + ")", range: [0, xMax] },
      yaxis: { title: "Differential/Operating Current I_op (" + unitLabel + ")", range: [0, yUpperBase] },
      height: 500,
      annotations: window.Charts.regionAnnotations(),
    });

    document.getElementById("curve-shape-caption").textContent =
      "Curve shape: " + (data.mode === "GENERATOR" ? "GE G60 dual-breakpoint" : "CFD22B4A single-slope") +
      " characteristic (" + data.mode + ").";
  }

  // -----------------------------------------------------------------------
  // Commissioning & Injection tab (client-side, cheap)
  // -----------------------------------------------------------------------
  function thresholdOf(riPu, settings) {
    return clientTripThreshold(settings, state.mode)(riPu);
  }

  function renderBoundaryInjection(data) {
    var settings = currentSettings();
    var defaults = { "Phase A": 0.5, "Phase B": 2.5, "Phase C": 5.0 };
    var grid = document.getElementById("boundary-injection-grid");
    grid.innerHTML = "";
    PHASES.forEach(function (p) {
      var boundaryOp = thresholdOf(defaults[p], settings);
      var secN = (defaults[p] + boundaryOp / 2.0) * data.i_rated_sec_N;
      var secT = (defaults[p] - boundaryOp / 2.0) * data.i_rated_sec_T;
      var div = document.createElement("div");
      div.innerHTML =
        "<strong>" + p + "</strong>" +
        '<div class="field"><label>Target Restraint (pu)</label><input type="number" step="0.1" value="' + defaults[p] + '" class="boundary-r-input" data-phase="' + p + '"></div>' +
        '<div class="metric"><span class="metric__label">Boundary I_op</span><span class="metric__value">' + boundaryOp.toFixed(3) + ' pu</span></div>' +
        '<p class="caption">Neutral inject: <strong>' + secN.toFixed(3) + ' A</strong></p>' +
        '<p class="caption">Terminal inject: <strong>' + secT.toFixed(3) + ' A</strong></p>';
      grid.appendChild(div);
    });
    grid.querySelectorAll(".boundary-r-input").forEach(function (el) {
      el.addEventListener("input", function () {
        var p = el.getAttribute("data-phase");
        var r = parseFloat(el.value) || 0;
        var boundaryOp = thresholdOf(r, currentSettings());
        var secN = (r + boundaryOp / 2.0) * data.i_rated_sec_N;
        var secT = (r - boundaryOp / 2.0) * data.i_rated_sec_T;
        var container = el.closest("div");
        container.querySelector(".metric__value").textContent = boundaryOp.toFixed(3) + " pu";
        var captions = container.querySelectorAll(".caption");
        captions[0].innerHTML = "Neutral inject: <strong>" + secN.toFixed(3) + " A</strong>";
        captions[1].innerHTML = "Terminal inject: <strong>" + secT.toFixed(3) + " A</strong>";
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
      var secN = (v + boundaryOp / 2.0) * data.i_rated_sec_N;
      var secT = (v - boundaryOp / 2.0) * data.i_rated_sec_T;
      rows.push({ i_rest_pu: Math.round(v * 1000) / 1000, boundary_op_pu: Math.round(boundaryOp * 1000) / 1000, n_injection_a: Math.round(secN * 1000) / 1000, t_injection_a: Math.round(secT * 1000) / 1000 });
    }
    state.sweepRows = rows;
    var table = document.getElementById("sweep-table");
    var tbody = table.querySelector("tbody");
    tbody.innerHTML = "";
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + r.i_rest_pu + "</td><td>" + r.boundary_op_pu + "</td><td>" + r.n_injection_a + "</td><td>" + r.t_injection_a + "</td>";
      tbody.appendChild(tr);
    });
    table.hidden = false;
    document.getElementById("download-sweep-csv-btn").hidden = false;
  }

  function downloadSweepCsv() {
    var header = "I_rest (pu),Boundary I_op (pu),Neutral Injection I_N (A),Terminal Injection I_T (A)\n";
    var lines = state.sweepRows.map(function (r) { return [r.i_rest_pu, r.boundary_op_pu, r.n_injection_a, r.t_injection_a].join(","); });
    var blob = new Blob([header + lines.join("\n")], { type: "text/csv" });
    var stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "").replace(/(\d{8})(\d{4})/, "$1_$2");
    window.Recompute.downloadBlob(blob, "87G_Sweep_Test_Table_" + stamp + ".csv");
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
        n: { amps: document.getElementById("tp-raw-n-amps").value, angle: document.getElementById("tp-raw-n-angle").value },
        t: { amps: document.getElementById("tp-raw-t-amps").value, angle: document.getElementById("tp-raw-t-angle").value },
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
      title: "Differential Slope Characteristic Curve",
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
    document.getElementById("fault-sym-value").textContent =
      fault.fault_calc.i_fault_sym_amps.toLocaleString(undefined, { maximumFractionDigits: 0 }) + " A (" + fault.fault_calc.i_fault_pu.toFixed(2) + " pu)";
    document.getElementById("fault-asym-value").textContent =
      fault.fault_calc.i_fault_asym_amps.toLocaleString(undefined, { maximumFractionDigits: 0 }) + " A";
    document.getElementById("fault-relay-sec-internal-value").textContent = fault.relay_sec_internal.toFixed(1) + " A";

    var internalAlert = document.getElementById("withstand-internal-alert");
    if (fault.within_internal_withstand) {
      internalAlert.className = "alert alert--success";
      internalAlert.textContent = "Internal-fault relay secondary current (" + fault.relay_sec_internal.toFixed(1) + " A) is within the " + fault.ct_withstand_a.toFixed(0) + " A withstand limit.";
    } else {
      internalAlert.className = "alert alert--warning";
      internalAlert.textContent = "Internal-fault relay secondary current (" + fault.relay_sec_internal.toFixed(1) + " A) EXCEEDS the " + fault.ct_withstand_a.toFixed(0) + " A withstand limit — review CT ratio or relay burden.";
    }

    var extEl = document.getElementById("fault-relay-sec-external-value");
    var externalAlert = document.getElementById("withstand-external-alert");
    if (fault.relay_sec_external !== null && fault.relay_sec_external !== undefined) {
      extEl.textContent = fault.relay_sec_external.toFixed(1) + " A";
      if (fault.within_external_withstand) {
        externalAlert.className = "alert alert--success";
        externalAlert.textContent = "External through-fault relay secondary current (" + fault.relay_sec_external.toFixed(1) + " A) is within the " + fault.ct_withstand_a.toFixed(0) + " A withstand limit.";
      } else {
        externalAlert.className = "alert alert--warning";
        externalAlert.textContent = "External through-fault relay secondary current (" + fault.relay_sec_external.toFixed(1) + " A) EXCEEDS the " + fault.ct_withstand_a.toFixed(0) + " A withstand limit.";
      }
    } else {
      extEl.textContent = "—";
      externalAlert.className = "alert alert--info";
      externalAlert.textContent = "Enter a through-fault current above to check it — left at 0 for a Custom Profile until you supply your own system's value.";
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
    if (sim.kind === "no_data") {
      caption.className = "alert alert--info";
      caption.textContent = "Enter a Maximum Through-Fault Current above (it's currently 0) to run this scenario.";
      return;
    }
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
    var rows;
    if (state.mode === "GENERATOR_LEGACY") {
      rows = [
        ["Relay Type", "GE CFD22B4A (GEK-34124)"],
        ["Target/Seal-in Pickup (A sec.)", settings.target_amps.toFixed(2)],
        ["Restraint Slope (%)", settings.slope1.toFixed(0)],
      ];
    } else {
      rows = [
        ["Relay Type", "GE G60 (Numerical)"],
        ["Pickup (pu)", settings.pickup.toFixed(3)],
        ["Slope 1 (%)", settings.slope1.toFixed(0)],
        ["Break 1 (pu)", settings.break1.toFixed(2)],
        ["Slope 2 (%)", settings.slope2.toFixed(0)],
        ["Break 2 (pu)", settings.break2.toFixed(2)],
        ["Unrestrained High-Set (pu)", settings.unrestrained_enabled ? settings.unrestrained.toFixed(2) : "Not enabled"],
      ];
    }
    rows = rows.concat([
      ["Neutral CT Ratio", settings.ct_n.toFixed(0) + ":" + settings.ct_sec.toFixed(0)],
      ["Terminal CT Ratio", settings.ct_t.toFixed(0) + ":" + settings.ct_sec.toFixed(0)],
      ["Restraint Standard", cp.convention],
      ["CT Polarity Reference", cp.ct_polarity],
    ]);
    var tbody = document.querySelector("#settings-sheet-table tbody");
    tbody.innerHTML = "";
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + r[0] + "</td><td>" + r[1] + "</td>";
      tbody.appendChild(tr);
    });
    document.getElementById("relay-type-caption").textContent =
      "Named exactly as the " + (state.mode === "GENERATOR_LEGACY" ? "CFD22B4A" : "G60") + " manual — reference only, not an importable relay project file.";
  }

  function downloadSettingsSheet() {
    window.Recompute.postForBlob(SETTINGS_SHEET_URL, buildRecomputePayload()).then(function (blob) {
      window.Recompute.downloadBlob(blob, "Generator_Settings_Sheet.csv");
    });
  }

  function exportReport() {
    window.Recompute.postForBlob(REPORT_PDF_URL, Object.assign(buildRecomputePayload(), { selected_preset: state.selectedPreset })).then(function (blob) {
      window.Recompute.downloadBlob(blob, "Generator_Differential_Protection_Report.pdf");
    });
  }

  function saveProfile() {
    var name = document.getElementById("profile-name").value || "Generator Profile";
    window.Profile.save(equipmentTag, name, Object.assign({ mode: state.mode }, currentSettings()));
  }

  function loadProfile(file) {
    window.Profile.load(file, equipmentTag).then(function (payload) {
      if (payload.settings && payload.settings.mode) {
        setMode(payload.settings.mode, /*resetPreset=*/false);
      }
      window.SettingsForm.applyFields(document, payload.settings);
      showToast("Loaded profile: " + (payload.profile_name || "Untitled"));
      onSettingsChanged();
    }).catch(function (err) {
      alert("Could not load profile: " + err.message);
    });
  }

  // -----------------------------------------------------------------------
  // Mode switching
  // -----------------------------------------------------------------------
  function setMode(mode, resetPreset) {
    resetPreset = resetPreset === undefined ? true : resetPreset;
    mode = (mode === "GENERATOR_LEGACY") ? "GENERATOR_LEGACY" : "GENERATOR";
    document.querySelectorAll('input[name="relay_mode"]').forEach(function (el) {
      el.checked = el.value === mode;
    });
    var firstPresetName = populatePresetSelect(mode);
    if (resetPreset) applyPreset(mode, firstPresetName);
  }

  // -----------------------------------------------------------------------
  // Master render after each /recompute response
  // -----------------------------------------------------------------------
  function renderAfterRecompute(data) {
    ensurePhaseInputDefaults(data.default_angles);
    renderPhaseInputs();
    document.getElementById("rated-current-info").className = "alert alert--info";
    document.getElementById("rated-current-info").innerHTML =
      "Generator Nominal Rated Current: <strong>" + data.i_rated_pri.toFixed(1) + " A</strong>";
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
        if (el.name === "relay_mode") return; // handled by its own listener below
        var field = el.getAttribute("data-field");
        var isSettingsField = field && (COMMON_FIELDS.indexOf(field) !== -1 ||
          ["pickup", "slope1", "break1", "slope2", "break2", "unrestrained", "unrestrained_enabled",
            "legacy_target_amps", "legacy_slope1"].indexOf(field) !== -1);
        if (isSettingsField || el.name === "convention" || el.name === "ct_polarity" || el.name === "chart_units") {
          onSettingsChanged();
          if (el.name === "chart_units" && state.lastResponse) renderBiasCurveChart(state.lastResponse);
        }
      });
    });

    document.querySelectorAll('input[name="relay_mode"]').forEach(function (el) {
      el.addEventListener("change", function () {
        setMode(el.value, true);
        showToast((el.value === "GENERATOR_LEGACY" ? "GE CFD22B4A" : "GE G60") + " mode selected.");
      });
    });

    document.getElementById("f-unrestrained_enabled").addEventListener("change", function (e) {
      document.getElementById("unrestrained-wrap").hidden = !e.target.checked;
      onSettingsChanged();
    });

    document.getElementById("preset-select").addEventListener("change", function (e) {
      applyPreset(state.mode, e.target.value);
      showToast("Loaded " + e.target.value);
    });
    document.getElementById("reset-preset-btn").addEventListener("click", function () {
      applyPreset(state.mode, state.selectedPreset);
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

    document.getElementById("run-fault-sim-btn").addEventListener("click", runFaultSim);

    document.getElementById("export-report-btn").addEventListener("click", exportReport);
    document.getElementById("download-settings-sheet-btn").addEventListener("click", downloadSettingsSheet);
    document.getElementById("save-profile-btn").addEventListener("click", saveProfile);

    // Initial paint
    populatePresetSelect(state.mode);
    updateSettingsCaptions();
    recompute();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
