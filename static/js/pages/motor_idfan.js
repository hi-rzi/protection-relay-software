/*
 * Page-specific glue for the ID Fan (Induced Draft Fan) Motor Protection page —
 * field lists + page quirks, mirroring views/motor_idfan.py's script body. All
 * relay math (51 IAC Long Time Inverse trip time, 50A/50B/backup/87M pickup
 * evaluation) is server-side via /api/motor/idfan/recompute, reusing
 * engines/motor.py and engines/motor_differential.py unchanged — this is a
 * standalone engine, not shared with the PA/FD Fan (SR469) page beyond
 * engines/motor.py's classes.
 */
(function () {
  "use strict";

  var RECOMPUTE_URL = "/api/motor/idfan/recompute";
  var SETTINGS_SHEET_URL = "/api/motor/idfan/settings-sheet.csv";
  var REPORT_PDF_URL = "/api/motor/idfan/report.pdf";

  var SETTINGS_FIELDS = [
    "motor_fla", "locked_rotor_amps", "locked_rotor_amps_80pct",
    "accel_time_100", "accel_time_80",
    "safe_stall_100_hot", "safe_stall_80_hot", "safe_stall_100_ambient", "safe_stall_80_ambient",
    "ct_ratio", "ct_sec",
    "diff87m_ct_ratio", "diff87m_pickup_sec",
    "tap_51", "time_dial", "pickup_50a", "dropout_50b", "target_seal_in",
    "backup_ct_ratio", "backup_pickup_50",
  ];

  var initialData = JSON.parse(document.getElementById("initial-data").textContent);
  var equipmentTag = "id_fan";

  var state = {
    selectedPreset: initialData.default_preset_name,
    userEditedTestCurrent: false,
    sweepRows: [],
    lastResponse: null,
  };

  // -----------------------------------------------------------------------
  // Settings collection
  // -----------------------------------------------------------------------
  function currentSettings() {
    var settings = {};
    SETTINGS_FIELDS.forEach(function (field) {
      var el = document.querySelector('[data-field="' + field + '"]');
      if (!el) return;
      var raw = el.value;
      var num = parseFloat(raw);
      settings[field] = (!isNaN(num) && raw !== "") ? num : raw;
    });
    var enableBackupEl = document.getElementById("f-enable_backup");
    settings.enable_backup = enableBackupEl ? enableBackupEl.checked : true;
    return settings;
  }

  function testCurrentInputs() {
    var testCurrentEl = document.getElementById("test-current");
    var imbalanceEl = document.getElementById("diff87m-test-imbalance");
    return {
      test_current: parseFloat(testCurrentEl.value) || 0,
      diff87m_test_imbalance: parseFloat(imbalanceEl.value) || 0,
    };
  }

  // -----------------------------------------------------------------------
  // Preset handling
  // -----------------------------------------------------------------------
  function applyPreset(presetName) {
    state.selectedPreset = presetName;
    var data = initialData.presets[presetName];
    var fieldValues = {};
    SETTINGS_FIELDS.forEach(function (field) {
      if (field in data) fieldValues[field] = data[field];
    });
    window.SettingsForm.applyFields(document, fieldValues);
    document.getElementById("f-enable_backup").checked = data.enable_backup !== false;
    document.getElementById("preset-confidence-warning").hidden = (presetName === "Custom Profile");

    if (!state.userEditedTestCurrent) {
      document.getElementById("test-current").value = data.motor_fla;
    }
    document.getElementById("diff87m-test-imbalance").value = 0;

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
  // Recompute (server round-trip for the actual relay evaluation)
  // -----------------------------------------------------------------------
  function buildRecomputePayload(extra) {
    var ti = testCurrentInputs();
    var payload = {
      settings: currentSettings(),
      test_current: ti.test_current,
      diff87m_test_imbalance: ti.diff87m_test_imbalance,
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
    if (document.getElementById("settings-preview-chart").hidden === false) renderSettingsPreview();
    recomputeDebounced();
  }

  // -----------------------------------------------------------------------
  // Live Preview mini chart (Current Settings tab) — reuses the same 51 curve
  // data as the TCC tab's main trace (returned in every recompute response).
  // -----------------------------------------------------------------------
  function renderSettingsPreview() {
    if (!state.lastResponse) return;
    var curve = state.lastResponse.curve;
    var xLower = curve.x_amps.map(function () { return 0; });
    var tValid = curve.t.map(function (v) { return v === null ? null : v; });
    var finiteT = tValid.filter(function (v) { return v !== null; });
    var yLower = finiteT.length ? Math.min.apply(null, finiteT) * 0.3 : 0;
    var yUpper = finiteT.length ? Math.max.apply(null, finiteT) * 2.5 : 1;

    window.Charts.plot("settings-preview-chart", [
      { x: curve.x_amps, y: curve.x_amps.map(function () { return yLower; }), mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
      { x: curve.x_amps, y: curve.t, mode: "lines", name: "51", line: { color: window.Charts.COLORS.line, width: 3 }, fill: "tonexty", fillcolor: window.Charts.COLORS.fillSafe },
      { x: curve.x_amps, y: curve.x_amps.map(function () { return yUpper; }), mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: window.Charts.COLORS.fillTrip, showlegend: false, hoverinfo: "skip" },
    ], {
      xaxis: { title: "Current (A primary)" },
      yaxis: { title: "Trip Time (s)", type: "log" },
      height: 320,
      showlegend: false,
      annotations: window.Charts.regionAnnotations(),
    });
  }

  // -----------------------------------------------------------------------
  // Current Settings tab — captions/alerts driven by the recompute response
  // -----------------------------------------------------------------------
  function alertify(el, passed, successText, warningText) {
    el.className = passed ? "alert alert--success" : "alert alert--warning";
    el.textContent = passed ? successText : warningText;
  }

  function updateSettingsCaptions(data) {
    var settings = currentSettings();
    var checks = data.checks;

    document.getElementById("ct-effective-ratio-caption").innerHTML =
      "Effective ratio &rarr; <strong>" + data.effective_ratio.toFixed(1) + ":1</strong>";

    var safeStall100 = settings.safe_stall_100_hot, accel100 = settings.accel_time_100;
    alertify(document.getElementById("stall-100-alert"), safeStall100 > accel100,
      "Safe stall time @ 100% V (" + safeStall100.toFixed(1) + "s) exceeds acceleration time (" + accel100.toFixed(1) + "s) — a normal start won't be mistaken for a stall.",
      "Safe stall time @ 100% V (" + safeStall100.toFixed(1) + "s) does not exceed acceleration time (" + accel100.toFixed(1) + "s) — review this motor data before relying on the margin checks below.");
    var safeStall80 = settings.safe_stall_80_hot, accel80 = settings.accel_time_80;
    alertify(document.getElementById("stall-80-alert"), safeStall80 > accel80,
      "Safe stall time @ 80% V (" + safeStall80.toFixed(1) + "s) exceeds acceleration time (" + accel80.toFixed(1) + "s) — a normal start won't be mistaken for a stall.",
      "Safe stall time @ 80% V (" + safeStall80.toFixed(1) + "s) does not exceed acceleration time (" + accel80.toFixed(1) + "s) — review this motor data before relying on the margin checks below.");

    alertify(document.getElementById("diff87m-alert"), checks.diff87m_ok,
      "Pickup = " + checks.diff87m_pickup_primary.toFixed(1) + " A primary — matches the settings doc's own 20A primary target for every 87M relay at this plant.",
      "Pickup = " + checks.diff87m_pickup_primary.toFixed(1) + " A primary — the settings doc sets every 87M relay to 20A primary regardless of CT ratio; review this if the difference isn't intentional.");

    document.getElementById("ideal-tap-caption").textContent =
      "Ideal tap ≈ FLA + 15% = " + data.tap_info.ideal_tap_51.toFixed(2) + " A sec. (nearest available: " + data.tap_info.nearest_tap_51.toFixed(1) + " A sec.)";

    var pickup51Primary = checks.pickup_51_primary, motorFla = settings.motor_fla;
    alertify(document.getElementById("tap51-alert"), pickup51Primary > motorFla,
      "Pickup " + pickup51Primary.toFixed(0) + " A primary (" + (pickup51Primary / motorFla).toFixed(2) + "x FLA) clears motor FLA.",
      "Pickup " + pickup51Primary.toFixed(0) + " A primary is at or below motor FLA (" + motorFla.toFixed(0) + " A) — review overload coordination.");

    alertify(document.getElementById("time-dial-alert"), checks.ok_100 && checks.ok_80,
      "Trips in " + (checks.t_at_lrc_100 !== null ? checks.t_at_lrc_100.toFixed(1) + "s" : "no trip") + " @ 100%V / " +
        (checks.t_at_lrc_80 !== null ? checks.t_at_lrc_80.toFixed(1) + "s" : "no trip") + " @ 80%V at locked rotor — inside the start/safe-stall margin both times.",
      "Trips in " + (checks.t_at_lrc_100 !== null ? checks.t_at_lrc_100.toFixed(1) + "s" : "no trip") + " @ 100%V / " +
        (checks.t_at_lrc_80 !== null ? checks.t_at_lrc_80.toFixed(1) + "s" : "no trip") + " @ 80%V at locked rotor — outside the start/safe-stall margin at one or both voltages. See the TCC Curve tab for the full picture.");

    var pickup50aPrimary = checks.pickup_50a_primary, lrc = settings.locked_rotor_amps;
    alertify(document.getElementById("pickup-50a-alert"), pickup50aPrimary > lrc,
      "Pickup " + pickup50aPrimary.toFixed(0) + " A primary (" + (pickup50aPrimary / lrc).toFixed(2) + "x LRC) clears locked-rotor current — won't trip instantaneously on a normal start.",
      "Pickup " + pickup50aPrimary.toFixed(0) + " A primary is at or below locked-rotor current (" + lrc.toFixed(0) + " A) — a normal start could trip instantaneously.");

    var pickup50bPrimary = checks.pickup_50b_primary;
    alertify(document.getElementById("dropout-50b-alert"), pickup50bPrimary > motorFla,
      "Estimated pickup " + pickup50bPrimary.toFixed(0) + " A primary (" + (pickup50bPrimary / motorFla).toFixed(2) + "x FLA) clears motor FLA.",
      "Estimated pickup " + pickup50bPrimary.toFixed(0) + " A primary is at or below motor FLA (" + motorFla.toFixed(0) + " A) — review the overload-alarm setting.");

    var backupAlert = document.getElementById("backup-alert");
    if (settings.enable_backup && checks.backup_pickup_primary !== null) {
      alertify(backupAlert, checks.backup_pickup_primary > lrc,
        "Pickup " + checks.backup_pickup_primary.toFixed(0) + " A primary (" + (checks.backup_pickup_primary / lrc).toFixed(2) + "x LRC) clears locked-rotor current.",
        "Pickup " + checks.backup_pickup_primary.toFixed(0) + " A primary is at or below locked-rotor current (" + lrc.toFixed(0) + " A) — review starting security and coordination.");
    } else {
      backupAlert.className = "alert alert--info";
      backupAlert.textContent = "Backup relay disabled — not included in the checks below.";
    }

    var lrMultiple = motorFla > 0 ? lrc / motorFla : 0;
    var kConservative = lrMultiple > 0 ? 230.0 / (lrMultiple * lrMultiple) : 0;
    var kTypical = lrMultiple > 0 ? 175.0 / (lrMultiple * lrMultiple) : 0;
    document.getElementById("k-conservative-value").textContent = kConservative.toFixed(2);
    document.getElementById("k-typical-value").textContent = kTypical.toFixed(2);

    var overall = document.getElementById("overall-status-caption");
    if (checks.all_clear) {
      overall.className = "alert alert--success";
      overall.textContent = "Overall status: all settings shown clear their recommended margins. Engineering approval is still required before issue.";
    } else {
      overall.className = "alert alert--warning";
      overall.textContent = "Overall status: one or more settings above need review before this is applied.";
    }

    window.ProjectStore.mirror(equipmentTag, settings);
  }

  // -----------------------------------------------------------------------
  // Live Simulation tab
  // -----------------------------------------------------------------------
  function renderLiveSim(data) {
    var settings = currentSettings();
    var ev = data.eval;
    var eResult = ev.result;

    document.getElementById("rated-current-info").className = "alert alert--info";
    document.getElementById("rated-current-info").innerHTML =
      "Motor FLA: <strong>" + settings.motor_fla.toFixed(0) + " A</strong>  |  Locked Rotor: <strong>" +
      settings.locked_rotor_amps.toFixed(0) + " A</strong> (" + (settings.locked_rotor_amps / settings.motor_fla).toFixed(1) + "x FLA)";

    var banner = document.getElementById("trip-status-banner");
    if (eResult.is_trip) {
      banner.className = "alert alert--danger";
      banner.textContent = eResult.status;
    } else if (eResult.alarm_50b) {
      banner.className = "alert alert--warning";
      banner.textContent = eResult.status;
    } else {
      banner.className = "alert alert--success";
      banner.textContent = "SYSTEM HEALTHY (Below Pickup)";
    }

    document.getElementById("m-relay-sec").textContent = eResult.i_relay_sec.toFixed(3) + " A";
    document.getElementById("m-multiple-51").textContent = eResult.multiple_of_pickup_51.toFixed(2) + "x";
    document.getElementById("m-t51").textContent = eResult.t51 !== null ? eResult.t51.toFixed(2) + "s" : "No Trip";

    var rows = [
      { element: "51 (Long Time Inverse)", state: eResult.trip_51 ? "TRIP" : "Below Pickup", detail: eResult.t51 !== null ? eResult.t51.toFixed(2) + "s" : "—" },
      { element: "50A (Instantaneous)", state: eResult.trip_50a ? "TRIP" : "Below Pickup", detail: "Pickup " + settings.pickup_50a.toFixed(1) + "A sec." },
      { element: "50B (Overload Alarm)", state: eResult.alarm_50b ? "ALARM" : "Normal", detail: "Est. pickup " + data.pickup_50b.toFixed(2) + "A sec. / dropout " + settings.dropout_50b.toFixed(2) + "A sec." },
    ];
    if (ev.backup_result !== null) {
      rows.push({
        element: "50 (Backup, HFC22B2A)", state: ev.backup_result.is_trip ? "TRIP" : "Below Pickup",
        detail: "Pickup " + settings.backup_pickup_50.toFixed(1) + "A sec. (higher-ratio CT, won't saturate)",
      });
    }
    rows.push({
      element: "87M (Self-Balancing Differential)", state: ev.diff87m_result.is_trip ? "TRIP" : "Below Pickup",
      detail: "Pickup " + settings.diff87m_pickup_sec.toFixed(1) + "A sec. (" + data.checks.diff87m_pickup_primary.toFixed(0) + "A primary) — separate CT from the elements above",
    });
    var tbody = document.querySelector("#elements-table tbody");
    tbody.innerHTML = "";
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + r.element + "</td><td>" + r.state + "</td><td>" + r.detail + "</td>";
      tbody.appendChild(tr);
    });

    var checks = data.checks;
    document.getElementById("margin-100-text").textContent = checks.t_at_lrc_100 !== null
      ? "100% V: 51 trips in " + checks.t_at_lrc_100.toFixed(1) + "s at LRC (accel " + settings.accel_time_100 + "s < trip < safe stall " + settings.safe_stall_100_hot + "s)"
      : "100% V: No trip at LRC";
    alertify(document.getElementById("margin-100-alert"), checks.ok_100, "Margin OK", "Check margin");
    document.getElementById("margin-80-text").textContent = checks.t_at_lrc_80 !== null
      ? "80% V: 51 trips in " + checks.t_at_lrc_80.toFixed(1) + "s at LRC (accel " + settings.accel_time_80 + "s < trip < safe stall " + settings.safe_stall_80_hot + "s)"
      : "80% V: No trip at LRC";
    alertify(document.getElementById("margin-80-alert"), checks.ok_80, "Margin OK", "Check margin");

    var checksWrap = document.getElementById("engineering-checks");
    checksWrap.innerHTML = "";
    checks.checks_live.forEach(function (c) {
      var p = document.createElement("p");
      p.className = c.passed ? "alert alert--success" : "alert alert--danger";
      p.innerHTML = c.passed
        ? "<strong>" + c.label + ":</strong> " + c.detail
        : "<strong>" + c.label + ":</strong> " + c.review_note + " (" + c.detail + ")";
      checksWrap.appendChild(p);
    });
  }

  // -----------------------------------------------------------------------
  // Commissioning & Injection tab
  // -----------------------------------------------------------------------
  function renderInjection(data) {
    if (!data.injection) return;
    document.getElementById("inj-sec-value").textContent = data.injection.inj_sec_amps.toFixed(3) + " A";
    document.getElementById("inj-pri-value").textContent = data.injection.inj_pri_amps.toFixed(1) + " A";
    document.getElementById("inj-t-value").textContent = data.injection.expected_t !== null ? data.injection.expected_t.toFixed(2) + "s" : "No Trip";
  }

  function runInjectionCalc() {
    var targetMultiple = parseFloat(document.querySelector('[data-number-pair="target_multiple"]').value) || 3.9;
    recompute({ injection: { target_multiple: targetMultiple } }).then(renderInjection);
  }

  function generateSweepTable() {
    var start = parseFloat(document.querySelector('[data-field="sweep_start"]').value) || 1.5;
    var end = parseFloat(document.querySelector('[data-field="sweep_end"]').value) || 10.0;
    var step = parseFloat(document.querySelector('[data-field="sweep_step"]').value) || 0.5;
    if (end <= start || step <= 0) {
      alert("Sweep End must be greater than Sweep Start, and Sweep Step must be positive.");
      return;
    }
    recompute({ sweep: { sweep_start: start, sweep_end: end, sweep_step: step } }).then(function (data) {
      if (!data.sweep) return;
      state.sweepRows = data.sweep;
      var table = document.getElementById("sweep-table");
      var tbody = table.querySelector("tbody");
      tbody.innerHTML = "";
      data.sweep.forEach(function (r) {
        var tr = document.createElement("tr");
        tr.innerHTML = "<td>" + r.multiple + "</td><td>" + r.inject_sec_a + "</td><td>" + r.equivalent_primary_a + "</td><td>" + (r.trip_time_s !== null ? r.trip_time_s : "No Trip") + "</td>";
        tbody.appendChild(tr);
      });
      table.hidden = false;
      document.getElementById("download-sweep-csv-btn").hidden = false;
    });
  }

  function downloadSweepCsv() {
    var header = "Multiple (M),Inject (Secondary A),Equivalent Primary (A),51 Trip Time (s)\n";
    var lines = state.sweepRows.map(function (r) { return [r.multiple, r.inject_sec_a, r.equivalent_primary_a, r.trip_time_s !== null ? r.trip_time_s : ""].join(","); });
    var blob = new Blob([header + lines.join("\n")], { type: "text/csv" });
    var stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "").replace(/(\d{8})(\d{4})/, "$1_$2");
    window.Recompute.downloadBlob(blob, "50-51_Sweep_Test_Table_" + stamp + ".csv");
  }

  // -----------------------------------------------------------------------
  // TCC Curve & Test Points tab
  // -----------------------------------------------------------------------
  function chartUnitsIsAmps() {
    var el = document.querySelector('input[name="chart_units"]:checked');
    return el ? el.value === "amps" : false;
  }

  function renderTccChart(data) {
    var useAmps = chartUnitsIsAmps();
    var curve = data.curve, tcc = data.tcc;
    var x51 = useAmps ? curve.x_amps : curve.m;

    var traces = [
      { x: x51, y: curve.t, mode: "lines", name: "51 (Long Time Inverse)", line: { color: window.Charts.COLORS.line, width: 3 } },
    ];

    var x50a = useAmps ? tcc.x_50a_amps : tcc.x_50a_multiple;
    var x50b = useAmps ? tcc.x_50b_amps : tcc.x_50b_multiple;
    var lrc100x = useAmps ? tcc.lrc_100_amps : tcc.lrc_100_multiple;
    var lrc80x = useAmps ? tcc.lrc_80_amps : tcc.lrc_80_multiple;

    var shapes = [
      { type: "line", x0: x50a, x1: x50a, y0: 0, y1: 1, yref: "paper", line: { color: "#DC2626", width: 2, dash: "dash" } },
      { type: "line", x0: x50b, x1: x50b, y0: 0, y1: 1, yref: "paper", line: { color: "#F59E0B", width: 2, dash: "dot" } },
    ];
    var annotations = [
      { x: x50a, y: 1, yref: "paper", text: "50A Pickup", showarrow: false, yanchor: "bottom" },
      { x: x50b, y: 1, yref: "paper", text: "50B Alarm", showarrow: false, yanchor: "bottom" },
    ];
    if (tcc.x_backup_amps !== null) {
      var xBackup = useAmps ? tcc.x_backup_amps : tcc.x_backup_multiple;
      shapes.push({ type: "line", x0: xBackup, x1: xBackup, y0: 0, y1: 1, yref: "paper", line: { color: "#7C3AED", width: 2, dash: "dashdot" } });
      annotations.push({ x: xBackup, y: 1, yref: "paper", text: "Backup 50", showarrow: false, yanchor: "bottom" });
    }

    traces.push({ x: [lrc100x], y: [tcc.accel_time_100], mode: "markers+text", name: "Start @ 100% V", text: ["Start @ 100%V"], textposition: "top center", marker: { size: 13, color: "green", symbol: "triangle-up" } });
    traces.push({ x: [lrc80x], y: [tcc.accel_time_80], mode: "markers+text", name: "Start @ 80% V", text: ["Start @ 80%V"], textposition: "top center", marker: { size: 13, color: "darkgreen", symbol: "triangle-up" } });
    traces.push({ x: [lrc100x], y: [tcc.safe_stall_100], mode: "markers+text", name: "Safe Stall @ 100% V", text: ["Safe Stall @ 100%V"], textposition: "bottom center", marker: { size: 13, color: "black", symbol: "x" } });
    traces.push({ x: [lrc80x], y: [tcc.safe_stall_80], mode: "markers+text", name: "Safe Stall @ 80% V", text: ["Safe Stall @ 80%V"], textposition: "bottom center", marker: { size: 13, color: "gray", symbol: "x" } });

    var unitLabel = useAmps ? "A (primary)" : "x Tap (M)";
    window.Charts.plot("tcc-chart", traces, {
      title: "ID Fan Motor Protection TCC",
      xaxis: { title: "Current (" + unitLabel + ")", type: "log" },
      yaxis: { title: "Time (seconds)", type: "log" },
      height: 550,
      shapes: shapes,
      annotations: annotations,
    });
  }

  function faultSimBaseLayout() {
    return { xaxis: { title: "Time (ms, t=0 is fault inception)" }, yaxis: { title: "Primary Current (A)" }, height: 340 };
  }

  function renderFaultSim(sim) {
    var caption = document.getElementById("fault-sim-caption");
    var preloadMs = 40.0;
    if (sim.kind === "trip" || sim.kind === "trip_51") {
      var durText = sim.kind === "trip" ? (sim.total_ms / (1000 / 60)).toFixed(1) + " cycles" : (sim.total_ms / 1000.0).toFixed(2) + " s";
      caption.className = "alert alert--success";
      caption.textContent = "Trip signal reaches the breaker — total clearing time " + sim.total_ms.toFixed(0) + " ms (" + durText + "). " + sim.status;
      var tail = sim.kind === "trip" ? sim.total_ms + 40.0 : sim.total_ms * 1.1 + 40.0;
      var layout = Object.assign(faultSimBaseLayout(), {
        shapes: [
          { type: "line", x0: sim.relay_ms, x1: sim.relay_ms, y0: 0, y1: sim.sim_current, line: { color: "#F59E0B", width: 2, dash: "dot" } },
          { type: "line", x0: sim.total_ms, x1: sim.total_ms, y0: 0, y1: sim.sim_current, line: { color: "#16A34A", width: 2, dash: "dash" } },
        ],
      });
      if (sim.log_x) layout.xaxis = Object.assign({}, layout.xaxis, { type: "log" });
      window.Charts.plot("fault-sim-chart", [{
        x: [-preloadMs, 0, 0, sim.total_ms, sim.total_ms, tail],
        y: [sim.preload_current, sim.preload_current, sim.sim_current, sim.sim_current, 0.0, 0.0],
        mode: "lines", line: { color: "#DC2626", width: 3 }, name: "Fault Current",
      }], layout);
    } else {
      caption.className = "alert alert--info";
      caption.textContent = "Neither the 51 nor the 50A element crosses its trip threshold at the settings above. No trip. " + sim.status;
      window.Charts.plot("fault-sim-chart", [{
        x: [-preloadMs, 0, 0, sim.window_ms],
        y: [sim.preload_current, sim.preload_current, sim.sim_current, sim.sim_current],
        mode: "lines", line: { color: "#DC2626", width: 3 }, name: "Fault Current",
      }], faultSimBaseLayout());
    }
  }

  function runFaultSim() {
    var scenario = document.querySelector('input[name="fault_scenario"]:checked').value;
    var relayCycles = parseFloat(document.querySelector('[data-field="relay_operate_cycles"]').value) || 1.0;
    var breakerCycles = parseFloat(document.querySelector('[data-field="breaker_cycles"]').value) || 5.0;
    recompute({
      fault_sim: { fault_scenario: scenario, relay_operate_cycles: relayCycles, breaker_cycles: breakerCycles },
    }).then(function (data) {
      if (data.fault_sim) renderFaultSim(data.fault_sim);
    });
  }

  // -----------------------------------------------------------------------
  // Settings Summary & Approval tab
  // -----------------------------------------------------------------------
  function renderSettingsSheet(data) {
    var settings = currentSettings();

    var mainRows = [
      ["CT Ratio", settings.ct_ratio.toFixed(0) + ":" + settings.ct_sec.toFixed(0)],
      ["51 Tap (A sec.)", settings.tap_51.toFixed(2)],
      ["51 Time Dial", settings.time_dial.toFixed(2)],
      ["50A Pickup (A sec.)", settings.pickup_50a.toFixed(2)],
      ["50B Dropout (A sec.)", settings.dropout_50b.toFixed(2)],
      ["Target & Seal-in (A)", settings.target_seal_in.toFixed(2)],
    ];
    if (settings.enable_backup) {
      mainRows.push(["Backup 50 CT Ratio", settings.backup_ct_ratio.toFixed(0) + ":" + settings.ct_sec.toFixed(0)]);
      mainRows.push(["Backup 50 Pickup (A sec.)", settings.backup_pickup_50.toFixed(2)]);
    }
    var mainTbody = document.querySelector("#settings-sheet-table-main tbody");
    mainTbody.innerHTML = "";
    mainRows.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + r[0] + "</td><td>" + r[1] + "</td>";
      mainTbody.appendChild(tr);
    });

    var diffRows = [
      ["87M CT Ratio", settings.diff87m_ct_ratio.toFixed(0) + ":" + settings.ct_sec.toFixed(0)],
      ["87M Pickup (A sec.)", settings.diff87m_pickup_sec.toFixed(2)],
      ["87M Tap", settings.diff87m_pickup_sec >= 2.0 ? "High" : "Low"],
    ];
    var diffTbody = document.querySelector("#settings-sheet-table-87m tbody");
    diffTbody.innerHTML = "";
    diffRows.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + r[0] + "</td><td>" + r[1] + "</td>";
      diffTbody.appendChild(tr);
    });
  }

  function renderApprovalTab(data) {
    var settings = currentSettings();
    var checks = data.checks;

    var summaryRows = [
      ["Motor", "Full-load current", settings.motor_fla.toFixed(0) + " A"],
      ["Motor", "Locked-rotor current", settings.locked_rotor_amps.toFixed(0) + " A at 100% V / " + settings.locked_rotor_amps_80pct.toFixed(0) + " A at 80% V"],
      ["CT", "50/50/51 CT ratio", settings.ct_ratio.toFixed(0) + ":" + settings.ct_sec.toFixed(0)],
      ["51", "Tap / time dial", settings.tap_51.toFixed(2) + " A sec. / " + settings.time_dial.toFixed(2)],
      ["50A", "Instantaneous pickup", settings.pickup_50a.toFixed(2) + " A sec. (" + checks.pickup_50a_primary.toFixed(0) + " A primary)"],
      ["50B", "Alarm dropout / estimated pickup", settings.dropout_50b.toFixed(2) + " / " + data.pickup_50b.toFixed(2) + " A sec."],
    ];
    if (settings.enable_backup) {
      summaryRows.push(["Backup 50", "CT ratio / pickup", settings.backup_ct_ratio.toFixed(0) + ":" + settings.ct_sec.toFixed(0) + " / " + settings.backup_pickup_50.toFixed(2) + " A sec."]);
    }
    var appliedTbody = document.querySelector("#applied-settings-table tbody");
    appliedTbody.innerHTML = "";
    summaryRows.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + r[0] + "</td><td>" + r[1] + "</td><td>" + r[2] + "</td>";
      appliedTbody.appendChild(tr);
    });

    var allPass = checks.checks_summary.every(function (c) { return c.passed; });
    var statusEl = document.getElementById("coordination-status-caption");
    if (allPass) {
      statusEl.className = "alert alert--success";
      statusEl.textContent = "All displayed coordination checks pass. Engineering approval is still required before issue.";
    } else {
      statusEl.className = "alert alert--danger";
      statusEl.textContent = "One or more coordination checks require engineering review before approval.";
    }
    var coordTbody = document.querySelector("#coordination-table tbody");
    coordTbody.innerHTML = "";
    checks.checks_summary.forEach(function (c) {
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + c.label + "</td><td>" + (c.passed ? "PASS" : "REVIEW REQUIRED") + "</td><td>" + c.detail + "</td>";
      coordTbody.appendChild(tr);
    });
  }

  function approvalFields() {
    return {
      source_document: document.getElementById("source-document").value,
      revision: document.getElementById("revision").value,
      prepared_by: document.getElementById("prepared-by").value || "Not recorded",
      reviewed_by: document.getElementById("reviewed-by").value || "Not recorded",
      approval_status: document.getElementById("approval-status").value,
      review_note: document.getElementById("review-note").value || "None",
    };
  }

  function downloadSettingsSheet() {
    window.Recompute.postForBlob(SETTINGS_SHEET_URL, buildRecomputePayload()).then(function (blob) {
      window.Recompute.downloadBlob(blob, "IDFan_Settings_Sheet.csv");
    });
  }

  function exportReport() {
    window.Recompute.postForBlob(REPORT_PDF_URL, Object.assign(buildRecomputePayload(), { selected_preset: state.selectedPreset })).then(function (blob) {
      window.Recompute.downloadBlob(blob, "IDFan_Motor_Protection_Report.pdf");
    });
  }

  function exportSummary() {
    var payload = Object.assign(buildRecomputePayload(), { selected_preset: state.selectedPreset, approval: approvalFields() });
    window.Recompute.postForBlob(REPORT_PDF_URL, payload).then(function (blob) {
      window.Recompute.downloadBlob(blob, "IDFan_Settings_Summary.pdf");
    });
  }

  function saveProfile() {
    var name = document.getElementById("profile-name").value || "ID Fan Profile";
    window.Profile.save(equipmentTag, name, currentSettings());
  }

  function loadProfile(file) {
    window.Profile.load(file, equipmentTag).then(function (payload) {
      window.SettingsForm.applyFields(document, payload.settings);
      if ("enable_backup" in payload.settings) document.getElementById("f-enable_backup").checked = !!payload.settings.enable_backup;
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
    updateSettingsCaptions(data);
    renderLiveSim(data);
    renderTccChart(data);
    renderSettingsSheet(data);
    renderApprovalTab(data);
    if (document.getElementById("settings-preview-chart").hidden === false) renderSettingsPreview();
  }

  // -----------------------------------------------------------------------
  // Wiring
  // -----------------------------------------------------------------------
  function init() {
    window.SettingsForm.initTabs(document);
    window.SettingsForm.bindSliderPairs(document, onSettingsChanged);

    document.querySelectorAll("#equipment-page .tabpanel input, #equipment-page .tabpanel select").forEach(function (el) {
      if (el.id === "test-current" || el.id === "diff87m-test-imbalance") return; // handled separately
      el.addEventListener("change", function () {
        var field = el.getAttribute("data-field");
        if (SETTINGS_FIELDS.indexOf(field) !== -1 || el.id === "f-enable_backup" || el.name === "chart_units") {
          onSettingsChanged();
          if (el.name === "chart_units" && state.lastResponse) renderTccChart(state.lastResponse);
        }
      });
    });

    document.getElementById("test-current").addEventListener("input", function () {
      state.userEditedTestCurrent = true;
      recomputeDebounced();
    });
    document.getElementById("diff87m-test-imbalance").addEventListener("input", function () {
      recomputeDebounced();
    });

    document.getElementById("preset-select").addEventListener("change", function (e) {
      applyPreset(e.target.value);
      showToast("Loaded " + e.target.value);
    });
    document.getElementById("reset-preset-btn").addEventListener("click", function () {
      state.userEditedTestCurrent = false;
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

    document.querySelector('[data-number-pair="target_multiple"]').addEventListener("input", window.Recompute.debounce(runInjectionCalc, 200));
    document.querySelector('[data-slider-pair="target_multiple"]').addEventListener("input", window.Recompute.debounce(runInjectionCalc, 200));

    document.getElementById("generate-sweep-btn").addEventListener("click", generateSweepTable);
    document.getElementById("download-sweep-csv-btn").addEventListener("click", downloadSweepCsv);

    document.getElementById("run-fault-sim-btn").addEventListener("click", runFaultSim);

    document.getElementById("export-report-btn").addEventListener("click", exportReport);
    document.getElementById("export-summary-btn").addEventListener("click", exportSummary);
    document.getElementById("download-settings-sheet-btn").addEventListener("click", downloadSettingsSheet);
    document.getElementById("save-profile-btn").addEventListener("click", saveProfile);

    // Initial paint
    document.getElementById("test-current").value = initialData.presets[state.selectedPreset].motor_fla;
    recompute().then(runInjectionCalc);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
