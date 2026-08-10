/*
 * Shared Plotly theming/shading helpers so every bias-curve chart looks
 * consistent without re-implementing it per page. Colors/shapes mirror the
 * Streamlit source's plotly.graph_objects figures as closely as practical
 * (exact pixel parity isn't required — functional/data parity is what matters).
 */
(function (global) {
  "use strict";

  var COLORS = {
    line: "#2563EB",
    fillSafe: "rgba(22,163,74,0.08)",
    fillTrip: "rgba(220,38,38,0.06)",
    hoc: "#DC2626",
    tripText: "#B91C1C",
    safeText: "#15803D",
    muted: "#94A3B8",
  };

  // Shared multi-trace colorway (phase markers, sweep overlays, etc.) so any
  // page adding more than the 3 core CAL./region traces gets a consistent,
  // pleasant palette instead of Plotly's default blue/orange/green defaults.
  var COLORWAY = ["#2563EB", "#DC2626", "#059669", "#D97706", "#7C3AED", "#0891B2"];

  var BASE_LAYOUT = {
    template: undefined, // plotly_white isn't bundled standalone via CDN's plain build; approximate manually below
    paper_bgcolor: "#ffffff",
    plot_bgcolor: "#ffffff",
    colorway: COLORWAY,
    font: { family: "Inter, -apple-system, Segoe UI, Arial, sans-serif", color: "#111827", size: 12 },
    xaxis: { gridcolor: "#eef1f5", zerolinecolor: "#e2e8f0", linecolor: "#e2e8f0" },
    yaxis: { gridcolor: "#eef1f5", zerolinecolor: "#e2e8f0", linecolor: "#e2e8f0" },
    legend: { bgcolor: "rgba(255,255,255,0.85)", bordercolor: "#e2e8f0", borderwidth: 1 },
    hoverlabel: { bgcolor: "#111827", bordercolor: "#111827", font: { color: "#ffffff", family: "Inter, Arial, sans-serif" } },
    margin: { t: 44, b: 50, l: 60, r: 24 },
  };

  function mergeLayout(overrides) {
    var layout = JSON.parse(JSON.stringify(BASE_LAYOUT));
    return Object.assign(layout, overrides || {});
  }

  function regionAnnotations() {
    return [
      {
        text: "OPERATING REGION (TRIP)", xref: "paper", yref: "paper", x: 0.98, y: 0.95,
        showarrow: false, font: { size: 12, color: COLORS.tripText }, xanchor: "right", yanchor: "top",
        bgcolor: "rgba(255,255,255,0.75)",
      },
      {
        text: "RESTRAINT REGION (SAFE)", xref: "paper", yref: "paper", x: 0.02, y: 0.05,
        showarrow: false, font: { size: 12, color: COLORS.safeText }, xanchor: "left", yanchor: "bottom",
        bgcolor: "rgba(255,255,255,0.75)",
      },
    ];
  }

  function scale(arr, factor) {
    return arr.map(function (v) { return v * factor; });
  }

  /* Builds the CAL. line + shaded restraint/operating regions, used by the
   * settings-preview mini chart, the Live Simulation main chart, and the
   * Curve & Test Points chart (theoretical mode). */
  function biasCurveTraces(xPu, yPu, opts) {
    opts = opts || {};
    var factor = opts.useAmps ? opts.ampsBase : 1.0;
    var x = scale(xPu, factor);
    var y = scale(yPu, factor);
    var yUpper = Math.max.apply(null, y) * 1.3 + 0.1 * (opts.useAmps ? opts.ampsBase : 1);

    var traces = [
      { x: x, y: x.map(function () { return 0; }), mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
      { x: x, y: y, mode: "lines", name: "CAL.", line: { color: COLORS.line, width: 3 }, fill: "tonexty", fillcolor: COLORS.fillSafe },
      { x: x, y: x.map(function () { return yUpper; }), mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: COLORS.fillTrip, showlegend: false, hoverinfo: "skip" },
    ];
    return { traces: traces, yUpper: yUpper, xMax: x[x.length - 1] };
  }

  function plot(divId, traces, layout) {
    Plotly.newPlot(divId, traces, mergeLayout(layout), {
      responsive: true,
      displaylogo: false,
      modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
    });
  }

  global.Charts = {
    COLORS: COLORS,
    COLORWAY: COLORWAY,
    mergeLayout: mergeLayout,
    regionAnnotations: regionAnnotations,
    biasCurveTraces: biasCurveTraces,
    scale: scale,
    plot: plot,
  };
})(window);
