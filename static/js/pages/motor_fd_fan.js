/*
 * Page-specific glue for the FD Fan page — field lists + page quirks,
 * mirroring common/motor_fan_page.py's shared script body (no IFC66KD2A
 * stack — see static/js/pages/motor_pa_fan.js for the PA Fan variant that
 * has it). Heavy math (relay evaluation, TCC curve, sweep, fault sim) is
 * server-side via /api/motor/fd-fan/recompute; cheap field-derived captions
 * are computed client-side.
 */
(function () {
  "use strict";

  var RECOMPUTE_URL = "/api/motor/fd-fan/recompute";
  var SETTINGS_SHEET_URL = "/api/motor/fd-fan/settings-sheet.csv";
  var REPORT_PDF_URL = "/api/motor/fd-fan/report.pdf";
  var EQUIPMENT_TAG = "fd_fan";

  var SETTINGS_FIELDS = [
    "fla", "ct_ratio", "ct_sec", "gct_ratio",
    "diff87m_ct_ratio", "diff87m_pickup_sec",
    "ovl_pct", "cm",
    "lrc_100", "lrc_80", "accel_100", "accel_80", "stall_100", "stall_80",
    "inst_ct", "inst_delay", "gf_frac", "gf_delay",
    "unb_alarm_pct", "unb_alarm_delay", "unb_trip_pct", "unb_trip_delay",
    "jam_pct", "jam_delay", "accel", "ovl_alarm_delay", "pdiff_frac", "pdiff_delay",
  ];

  var initialData = JSON.parse(document.getElementById("initial-data").textContent);

  var state = {
    selectedPreset: initialData.default_preset_name,
    isCustom: initialData.default_preset_name === "Custom Profile",
    lastResponse: null,
    sweepRows: [],
  };

  // -----------------------------------------------------------------------
  // Settings collection
  // -----------------------------------------------------------------------
  function currentSettings() {
    var settings = window.SettingsForm.collectFields(document);
    var out = {};
    SETTINGS_FIELDS.forEach(function (field) {
      if (field in settings) out[field] = settings[field];
    });
    return out;
  }

  // -----------------------------------------------------------------------
  // Preset handling
  // -----------------------------------------------------------------------
  function applyPreset(presetName) {
    state.selectedPreset = presetName;
    state.isCustom = presetName === "Custom Profile";
    var data = initialData.presets[presetName];
    var fieldValues = {};
    SETTINGS_FIELDS.forEach(function (f) { if (f in data) fieldValues[f] = data[f]; });
    window.SettingsForm.applyFields(document, fieldValues);
    document.getElementById("preset-confidence-warning").hidden = state.isCustom;
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
    var s = currentSettings();
    document.getElementById("ct-effective-ratio-caption").innerHTML =
      "Effective ratio &rarr; <strong>" + s.ct_ratio.toFixed(0) + ":" + s.ct_sec.toFixed(0) + "</strong> " +
      "(= " + (s.ct_ratio / s.ct_sec).toFixed(1) + ":1)";

    var diff87mPrimary = s.diff87m_pickup_sec * (s.ct_sec > 0 ? (s.diff87m_ct_ratio / s.ct_sec) : s.diff87m_ct_ratio);
    var diff87mAlert = document.getElementById("diff87m-alert");
    var diff87mOk = Math.abs(diff87mPrimary - 20.0) < 0.5;
    diff87mAlert.className = "alert " + (diff87mOk ? "alert--success" : "alert--warning");
    diff87mAlert.textContent = diff87mOk
      ? "Pickup = " + diff87mPrimary.toFixed(1) + " A primary — matches the settings doc's own 20A primary target."
      : "Pickup = " + diff87mPrimary.toFixed(1) + " A primary — the settings doc sets every 87M relay to 20A primary; review if the difference isn't intentional.";

    var ovlAlert = document.getElementById("ovl-pct-alert");
    if (s.ovl_pct >= 110.0 && s.ovl_pct <= 115.0) {
      ovlAlert.className = "alert alert--success";
      ovlAlert.textContent = "Pickup set at " + s.ovl_pct.toFixed(0) + "% FLA — within the typical 110-115% range.";
    } else if (s.ovl_pct > 100.0) {
      ovlAlert.className = "alert alert--info";
      ovlAlert.textContent = "Pickup set at " + s.ovl_pct.toFixed(0) + "% FLA — above 100%, though outside the typical 110-115% range.";
    } else {
      ovlAlert.className = "alert alert--warning";
      ovlAlert.textContent = "Pickup set at " + s.ovl_pct.toFixed(0) + "% FLA — at or below 100% FLA, review overload coordination.";
    }

    var instPrimary = s.inst_ct * s.ct_ratio;
    var instAlert = document.getElementById("inst-alert");
    if (instPrimary > s.fla) {
      instAlert.className = "alert alert--success";
      instAlert.textContent = "Pickup " + instPrimary.toFixed(0) + " A primary (" + (instPrimary / s.fla).toFixed(2) + "x FLA) clears motor FLA.";
    } else {
      instAlert.className = "alert alert--warning";
      instAlert.textContent = "Pickup " + instPrimary.toFixed(0) + " A primary is at or below motor FLA (" + s.fla.toFixed(0) + " A) — review coordination.";
    }

    var unbAlert = document.getElementById("unbalance-alert");
    if (s.unb_trip_pct >= s.unb_alarm_pct) {
      unbAlert.className = "alert alert--success";
      unbAlert.textContent = "Trip pickup (" + s.unb_trip_pct.toFixed(0) + "%) is at or above alarm pickup (" + s.unb_alarm_pct.toFixed(0) + "%) — alarm gives advance warning.";
    } else {
      unbAlert.className = "alert alert--warning";
      unbAlert.textContent = "Trip pickup (" + s.unb_trip_pct.toFixed(0) + "%) is below alarm pickup (" + s.unb_alarm_pct.toFixed(0) + "%) — review this pair.";
    }

    window.ProjectStore.mirror(EQUIPMENT_TAG, s);
  }

  // -----------------------------------------------------------------------
  // Live Preview mini chart (Current Settings tab) — overload curve only
  // -----------------------------------------------------------------------
  function renderSettingsPreview() {
    var s = currentSettings();
    var xAmps = [], t = [];
    for (var i = 0; i <= 200; i++) {
      var m = 1.01 + (8.0 - 1.01) * i / 200;
      xAmps.push(m * s.fla);
      var x = m - 1.0;
      var denom = 0.025303373 * x * x + 0.050547581 * x;
      t.push(denom > 0 ? (s.cm * 2.2116623) / denom : null);
    }
    window.Charts.plot("settings-preview-chart", [
      { x: xAmps, y: t, mode: "lines", name: "Curve X" + s.cm, line: { color: "#2563EB", width: 3 } },
    ], {
      xaxis: { title: "Current (A primary)" },
      yaxis: { title: "Trip Time (s)", type: "log" },
      height: 320,
      showlegend: false,
    });
  }

  // -----------------------------------------------------------------------
  // Recompute
  // -----------------------------------------------------------------------
  function buildRecomputePayload(extra) {
    var payload = {
      settings: currentSettings(),
      test_current: parseFloat(document.getElementById("test-current").value) || 0,
      ground_current: parseFloat(document.getElementById("ground-current").value) || 0,
      unbalance_pct: parseFloat(document.getElementById("unbalance-input").value) || 0,
      diff87m_test_imbalance: parseFloat(document.getElementById("diff87m-test-imbalance").value) || 0,
    };
    return Object.assign(payload, extra || {});
  }

  var recomputeDebounced = window.Recompute.debounce(function () { recompute(); }, 250);

  function recompute(extra) {
    return window.Recompute.postJSON(RECOMPUTE_URL, buildRecomputePayload(extra)).then(function (data) {
      state.lastResponse = data;
      renderAfterRecompute(data);
      return data;
    }).catch(function (err) { console.error(err); });
  }

  function onSettingsChanged() {
    updateSettingsCaptions();
    if (!document.getElementById("settings-preview-chart").hidden) renderSettingsPreview();
    recomputeDebounced();
  }

  // -----------------------------------------------------------------------
  // Live Simulation tab
  // -----------------------------------------------------------------------
  function renderVerdict(data) {
    document.getElementById("fla-pickup-info").innerHTML =
      "Motor FLA: <strong>" + data.motor_fla.toFixed(0) + " A</strong> | Instantaneous Pickup: <strong>" + data.inst_pickup_amps.toFixed(0) + " A primary</strong>";
    if (!document.getElementById("test-current").dataset.touched) {
      document.getElementById("test-current").value = data.motor_fla.toFixed(0);
    }

    var banner = document.getElementById("trip-status-banner");
    banner.className = "alert " + (data.any_trip ? "alert--danger" : "alert--success");
    banner.textContent = data.any_trip ? "PROTECTIVE RELAY TRIP INITIATED!" : "SYSTEM HEALTHY";

    var rows = [
      ["Overload (51) / Instantaneous (50)", data.eval.multiple_of_fla.toFixed(2) + "x FLA", data.eval.status],
      ["Ground Fault (50G/51G)", data.ground_current.toFixed(1) + " A", data.gf_eval.status],
      ["Current Unbalance (46)", data.unbalance_pct.toFixed(1) + " %", data.unbal_eval.status],
      ["87M (Self-Balancing Differential)", data.diff87m_test_imbalance.toFixed(1) + " A", data.diff87m_eval.status],
    ];
    var tbody = document.querySelector("#verdict-table tbody");
    tbody.innerHTML = "";
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + r[0] + "</td><td>" + r[1] + "</td><td>" + r[2] + "</td>";
      tbody.appendChild(tr);
    });
  }

  function renderSettingsSheetTables() {
    var s = currentSettings();
    var rowsSr469 = [
      ["CT Ratio", s.ct_ratio.toFixed(0) + ":" + s.ct_sec.toFixed(0)],
      ["Ground CT Ratio", s.gct_ratio.toFixed(0) + ":" + s.ct_sec.toFixed(0)],
      ["Overload Pickup (% FLA)", s.ovl_pct.toFixed(0)],
      ["Curve Multiplier (CM)", s.cm.toFixed(1)],
      ["Instantaneous Pickup (x CT sec.)", s.inst_ct.toFixed(1)],
      ["Instantaneous Delay (ms)", s.inst_delay.toFixed(0)],
      ["Ground Fault Pickup (x Ground CT)", s.gf_frac.toFixed(2)],
      ["Ground Fault Delay (ms)", s.gf_delay.toFixed(0)],
      ["Unbalance Alarm/Trip (%)", s.unb_alarm_pct.toFixed(0) + " / " + s.unb_trip_pct.toFixed(0)],
      ["Mechanical Jam Pickup (% FLA)", s.jam_pct.toFixed(0)],
    ];
    var rows87m = [
      ["87M CT Ratio", s.diff87m_ct_ratio.toFixed(0) + ":" + s.ct_sec.toFixed(0)],
      ["87M Pickup (A sec.)", s.diff87m_pickup_sec.toFixed(2)],
      ["87M Tap", s.diff87m_pickup_sec >= 2.0 ? "High" : "Low"],
    ];
    fillTable("#settings-sheet-table-sr469 tbody", rowsSr469);
    fillTable("#settings-sheet-table-87m tbody", rows87m);
  }

  function fillTable(selector, rows) {
    var tbody = document.querySelector(selector);
    tbody.innerHTML = "";
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      r.forEach(function (c) {
        var td = document.createElement("td");
        td.textContent = c;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  }

  // -----------------------------------------------------------------------
  // Commissioning & Injection tab
  // -----------------------------------------------------------------------
  function updateInjection() {
    var m = parseFloat(document.getElementById("inj-multiple-number").value) || 1.05;
    recompute({ injection: { target_multiple: m } });
  }

  function renderInjection(data) {
    if (!data.injection) return;
    document.getElementById("inj-pri-value").textContent = data.injection.inj_pri_amps.toFixed(1) + " A";
    document.getElementById("inj-sec-value").textContent = data.injection.inj_sec_amps.toFixed(3) + " A";
    document.getElementById("inj-trip-value").textContent = data.injection.expected_t !== null ? data.injection.expected_t.toFixed(2) + "s" : "No Trip";
  }

  function generateSweepTable() {
    var start = parseFloat(document.getElementById("sweep-start").value) || 1.05;
    var end = parseFloat(document.getElementById("sweep-end").value) || 6.0;
    var step = parseFloat(document.getElementById("sweep-step").value) || 0.5;
    if (end <= start || step <= 0) {
      alert("Sweep End must be greater than Sweep Start, and Sweep Step must be positive.");
      return;
    }
    recompute({ sweep: { sweep_start: start, sweep_end: end, sweep_step: step } }).then(function (data) {
      if (!data.sweep) return;
      state.sweepRows = data.sweep;
      var tbody = document.querySelector("#sweep-table tbody");
      tbody.innerHTML = "";
      data.sweep.forEach(function (r) {
        var tr = document.createElement("tr");
        tr.innerHTML = "<td>" + r.multiple + "</td><td>" + r.primary_a + "</td><td>" + r.secondary_a + "</td><td>" + (r.trip_time_s !== null ? r.trip_time_s : "No Trip") + "</td>";
        tbody.appendChild(tr);
      });
      document.getElementById("sweep-table").hidden = false;
      document.getElementById("download-sweep-csv-btn").hidden = false;
    });
  }

  function downloadSweepCsv() {
    var header = "Multiple of FLA (M),Primary Current (A),Secondary Current (A),Overload Trip Time (s)\n";
    var lines = state.sweepRows.map(function (r) { return [r.multiple, r.primary_a, r.secondary_a, r.trip_time_s !== null ? r.trip_time_s : ""].join(","); });
    var blob = new Blob([header + lines.join("\n")], { type: "text/csv" });
    window.Recompute.downloadBlob(blob, "FD_Fan_Sweep_Test_Table.csv");
  }

  // -----------------------------------------------------------------------
  // TCC Curve & Test Points tab
  // -----------------------------------------------------------------------
  function renderTccChart(data) {
    var traces = [
      { x: data.tcc_curve.mult, y: data.tcc_curve.t, mode: "lines", name: "Overload (51)", line: { color: "#2563EB", width: 3 } },
    ];
    if (data.eval.t51 !== null) {
      traces.push({ x: [data.eval.multiple_of_fla], y: [data.eval.t51], mode: "markers", name: "Operating Point", marker: { size: 14, color: "red", symbol: "x" } });
    }
    if (data.stall) {
      traces.push({ x: [data.stall.lrc_100_x], y: [data.stall.accel_100], mode: "markers+text", name: "Start @ 100% V", text: ["Start @ 100%V"], textposition: "top center", marker: { size: 13, color: "green", symbol: "triangle-up" } });
      traces.push({ x: [data.stall.lrc_80_x], y: [data.stall.accel_80], mode: "markers+text", name: "Start @ 80% V", text: ["Start @ 80%V"], textposition: "top center", marker: { size: 13, color: "darkgreen", symbol: "triangle-up" } });
      traces.push({ x: [data.stall.lrc_100_x], y: [data.stall.stall_100], mode: "markers+text", name: "Safe Stall @ 100% V", text: ["Safe Stall @ 100%V"], textposition: "bottom center", marker: { size: 13, color: "black", symbol: "x" } });
      traces.push({ x: [data.stall.lrc_80_x], y: [data.stall.stall_80], mode: "markers+text", name: "Safe Stall @ 80% V", text: ["Safe Stall @ 80%V"], textposition: "bottom center", marker: { size: 13, color: "gray", symbol: "x" } });
    }
    window.Charts.plot("tcc-chart", traces, {
      title: "SR469 Overload Trip Time vs. Multiple of FLA",
      xaxis: { title: "Current (x Motor FLA)" },
      yaxis: { title: "Trip Time (s)", type: "log" },
      height: 450,
    });

    var section = document.getElementById("stall-margin-section");
    if (!data.stall) {
      document.getElementById("stall-100-result").innerHTML = '<p class="caption">No Locked Rotor Current / Safe Stall Time data is on record for this equipment.</p>';
      document.getElementById("stall-80-result").innerHTML = "";
      return;
    }
    function stallHtml(label, t, accel, stall, ok) {
      var tStr = t !== null ? t.toFixed(1) + "s" : "No Trip";
      return "<p><strong>" + label + ":</strong> trips in " + tStr + " at LRC</p>" +
        "<p>Accel " + accel + "s &lt; Trip &lt; Safe Stall " + stall + "s</p>" +
        '<p class="alert ' + (ok ? "alert--success" : "alert--danger") + '">' + (ok ? "Margin OK" : "Check margin") + "</p>";
    }
    document.getElementById("stall-100-result").innerHTML = stallHtml("100% V", data.stall.t_100, data.stall.accel_100, data.stall.stall_100, data.stall.ok_100);
    document.getElementById("stall-80-result").innerHTML = stallHtml("80% V", data.stall.t_80, data.stall.accel_80, data.stall.stall_80, data.stall.ok_80);
  }

  function renderOtherFunctionsTable() {
    var preset = initialData.presets[state.selectedPreset];
    var s = currentSettings();
    var rows = [
      ["Overload Alarm", s.ovl_alarm_delay.toFixed(1) + "s delay at Overload Pickup", "Early warning before the 51 trip"],
      ["Mechanical Jam Trip", s.jam_pct.toFixed(0) + "% FLA, " + s.jam_delay.toFixed(1) + "s delay", "Disabled until after motor start"],
      ["Acceleration Timer", s.accel.toFixed(0) + "s", "Trips if current stays above Overload Pickup past this time after start"],
      ["Phase Differential (87)", s.pdiff_frac.toFixed(2) + "x CT, " + s.pdiff_delay.toFixed(0) + "ms delay", "Separate zero-sequence differential CTs"],
      ["Stator RTD Alarm/Trip", preset.rtd_stator_c + "°C", "No bearing RTDs fitted on this motor"],
      ["Overvoltage (59)", preset.ov_pickup_pu.toFixed(2) + " x rated, " + preset.ov_delay_s.toFixed(0) + "s delay", "Alarm only"],
      ["Over/Underfrequency (81)", preset.of_hz.toFixed(1) + "Hz / " + preset.uf_hz.toFixed(1) + "Hz", "Alarm only"],
      ["Underpower (37)", preset.underpower_kw.toFixed(0) + "kW, " + preset.underpower_delay_s.toFixed(0) + "s delay", "Detects lost/broken shaft coupling"],
      ["Jogging Block (66)", preset.starts_per_hour.toFixed(0) + " starts/hour, " + preset.time_between_starts_min.toFixed(0) + " min between starts", ""],
      ["Phase Reversal", "Enabled", ""],
    ];
    fillTable("#other-functions-table tbody", rows);
  }

  function runFaultSim() {
    var scenario = document.querySelector('input[name="fault_scenario"]:checked').value;
    var breakerCycles = parseFloat(document.getElementById("fault-breaker-cycles").value) || 5.0;
    recompute({ fault_sim: { fault_scenario: scenario, breaker_cycles: breakerCycles } }).then(function (data) {
      renderFaultSim(data.fault_sim);
    });
  }

  function renderFaultSim(sim) {
    if (!sim) return;
    var caption = document.getElementById("fault-sim-caption");
    var preloadMs = 40.0;
    if (sim.kind === "trip" || sim.kind === "trip_51") {
      caption.className = "alert alert--success";
      caption.textContent = "Trip signal reaches the breaker — total clearing time " + sim.total_ms.toFixed(0) + " ms. " + sim.status;
      window.Charts.plot("fault-sim-chart", [{
        x: [-preloadMs, 0, 0, sim.total_ms, sim.total_ms, sim.total_ms + 40.0],
        y: [sim.preload_current, sim.preload_current, sim.sim_current, sim.sim_current, 0.0, 0.0],
        mode: "lines", line: { color: "#DC2626", width: 3 }, name: "Fault Current",
      }], { xaxis: { title: "Time (ms, t=0 is fault inception)" }, yaxis: { title: "Primary Current (A)" }, height: 340 });
    } else {
      caption.className = "alert alert--info";
      caption.textContent = "Relay stays SECURE — no trip. " + sim.status;
      window.Charts.plot("fault-sim-chart", [{
        x: [-preloadMs, 0, 0, sim.window_ms],
        y: [sim.preload_current, sim.preload_current, sim.sim_current, sim.sim_current],
        mode: "lines", line: { color: "#DC2626", width: 3 }, name: "Fault Current",
      }], { xaxis: { title: "Time (ms, t=0 is fault inception)" }, yaxis: { title: "Primary Current (A)" }, height: 340 });
    }
  }

  // -----------------------------------------------------------------------
  // Settings Summary & Approval tab
  // -----------------------------------------------------------------------
  function renderApproval(data) {
    var s = currentSettings();
    var rows = [
      ["Motor", "Full-load current", s.fla.toFixed(0) + " A"],
      ["CT", "Phase CT ratio", s.ct_ratio.toFixed(0) + ":" + s.ct_sec.toFixed(0)],
      ["CT", "Ground CT ratio", s.gct_ratio.toFixed(0) + ":" + s.ct_sec.toFixed(0)],
      ["Overload", "Pickup / Curve Multiplier", s.ovl_pct.toFixed(0) + "% FLA / CM " + s.cm.toFixed(1)],
      ["Instantaneous", "Pickup / Delay", s.inst_ct.toFixed(1) + "x CT sec. (" + data.inst_pickup_amps.toFixed(0) + "A primary) / " + s.inst_delay.toFixed(0) + "ms"],
      ["Ground Fault", "Pickup / Delay", s.gf_frac.toFixed(2) + "x Ground CT (" + data.gf_pickup_amps.toFixed(2) + "A) / " + s.gf_delay.toFixed(0) + "ms"],
      ["Unbalance", "Alarm / Trip", s.unb_alarm_pct.toFixed(0) + "% / " + s.unb_trip_pct.toFixed(0) + "%"],
    ];
    fillTable("#applied-settings-table tbody", rows);

    var status = document.getElementById("coordination-status");
    var allPass = data.checks.every(function (c) { return c.passed; });
    status.className = "alert " + (allPass ? "alert--success" : "alert--danger");
    status.textContent = allPass
      ? "All displayed coordination checks pass. Engineering approval is still required before issue."
      : "One or more coordination checks require engineering review before approval.";
    var checkRows = data.checks.map(function (c) { return [c.label, c.passed ? "PASS" : "REVIEW REQUIRED", c.detail]; });
    fillTable("#coordination-table tbody", checkRows);
  }

  function exportReport() {
    var body = Object.assign(buildRecomputePayload(), { selected_preset: state.selectedPreset });
    window.Recompute.postForBlob(REPORT_PDF_URL, body).then(function (blob) {
      window.Recompute.downloadBlob(blob, "FD_Fan_Protection_Report.pdf");
    });
  }

  function exportApprovalPdf() {
    var approval = {
      source_document: document.getElementById("source-document").value,
      revision: document.getElementById("revision").value,
      prepared_by: document.getElementById("prepared-by").value,
      reviewed_by: document.getElementById("reviewed-by").value,
      approval_status: document.getElementById("approval-status").value,
      review_note: document.getElementById("review-note").value,
    };
    var body = Object.assign(buildRecomputePayload(), { selected_preset: state.selectedPreset, approval: approval });
    window.Recompute.postForBlob(REPORT_PDF_URL, body).then(function (blob) {
      window.Recompute.downloadBlob(blob, "FD_Fan_Settings_Summary.pdf");
    });
  }

  function downloadSettingsSheet() {
    window.Recompute.postForBlob(SETTINGS_SHEET_URL, buildRecomputePayload()).then(function (blob) {
      window.Recompute.downloadBlob(blob, "FD_Fan_Settings_Sheet.csv");
    });
  }

  function saveProfile() {
    var name = document.getElementById("profile-name").value || "Forced Draft (FD) Fan Profile";
    window.Profile.save(EQUIPMENT_TAG, name, currentSettings());
  }

  function loadProfile(file) {
    window.Profile.load(file, EQUIPMENT_TAG).then(function (payload) {
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
    renderVerdict(data);
    renderSettingsSheetTables();
    renderInjection(data);
    renderTccChart(data);
    renderOtherFunctionsTable();
    renderApproval(data);
  }

  // -----------------------------------------------------------------------
  // Wiring
  // -----------------------------------------------------------------------
  function init() {
    window.SettingsForm.initTabs(document);

    document.querySelectorAll("#equipment-page [data-field]").forEach(function (el) {
      el.addEventListener("change", onSettingsChanged);
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

    ["test-current", "ground-current", "unbalance-input", "diff87m-test-imbalance"].forEach(function (id) {
      document.getElementById(id).addEventListener("input", function () {
        document.getElementById(id).dataset.touched = "1";
        recomputeDebounced();
      });
    });
    document.getElementById("export-report-btn").addEventListener("click", exportReport);

    var slider = document.getElementById("inj-multiple-slider"), number = document.getElementById("inj-multiple-number");
    slider.addEventListener("input", function () { number.value = slider.value; updateInjection(); });
    number.addEventListener("input", function () { slider.value = number.value; updateInjection(); });

    document.getElementById("generate-sweep-btn").addEventListener("click", generateSweepTable);
    document.getElementById("download-sweep-csv-btn").addEventListener("click", downloadSweepCsv);

    document.querySelectorAll('input[name="fault_scenario"]').forEach(function (el) { el.addEventListener("change", function () {}); });
    document.getElementById("run-fault-sim-btn").addEventListener("click", runFaultSim);

    document.getElementById("export-approval-pdf-btn").addEventListener("click", exportApprovalPdf);
    document.getElementById("download-settings-sheet-btn").addEventListener("click", downloadSettingsSheet);
    document.getElementById("save-profile-btn").addEventListener("click", saveProfile);

    // Initial paint
    updateSettingsCaptions();
    recompute().then(function (data) { updateInjection(); });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
