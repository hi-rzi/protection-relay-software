/*
 * Shared settings-form behavior:
 *  - generic tab switching (any element with [data-tabgroup] / [data-tab])
 *  - slider_with_exact_input replacement (range + number pair sync)
 *  - collecting all data-field elements on the page into a plain settings object
 *  - settings_advisor.py's pure arithmetic, ported to JS so the Current Settings
 *    tab's pass/fail captions update with zero server round-trip
 */
(function (global) {
  "use strict";

  // ---------------------------------------------------------------------
  // Tab switching
  // ---------------------------------------------------------------------
  function initTabs(root) {
    root = root || document;
    root.querySelectorAll(".tabgroup").forEach(function (group) {
      var buttons = group.querySelectorAll(":scope > .tabgroup__tabs > .tab-btn");
      buttons.forEach(function (btn) {
        btn.addEventListener("click", function () {
          var tabName = btn.getAttribute("data-tab");
          buttons.forEach(function (b) { b.classList.toggle("tab-btn--active", b === btn); });
          group.querySelectorAll(":scope > .tabpanel").forEach(function (panel) {
            panel.hidden = panel.getAttribute("data-tabpanel") !== tabName;
          });
          group.dispatchEvent(new CustomEvent("tabchange", { detail: { tab: tabName }, bubbles: true }));
        });
      });
    });
  }

  // ---------------------------------------------------------------------
  // slider_with_exact_input pairing
  // ---------------------------------------------------------------------
  function bindSliderPairs(root, onChange) {
    root = root || document;
    root.querySelectorAll("[data-slider-pair]").forEach(function (slider) {
      var field = slider.getAttribute("data-slider-pair");
      var number = root.querySelector('[data-number-pair="' + field + '"]');
      if (!number) return;
      slider.addEventListener("input", function () {
        number.value = slider.value;
        if (onChange) onChange(field);
      });
      number.addEventListener("input", function () {
        var v = parseFloat(number.value);
        var min = parseFloat(number.min), max = parseFloat(number.max);
        if (!isNaN(min) && v < min) v = min;
        if (!isNaN(max) && v > max) v = max;
        slider.value = v;
        if (onChange) onChange(field);
      });
    });
  }

  // ---------------------------------------------------------------------
  // Collect every [data-field] element into a plain object
  // ---------------------------------------------------------------------
  function collectFields(root) {
    root = root || document;
    var out = {};
    root.querySelectorAll("[data-field]").forEach(function (el) {
      // Skip a field if its NEAREST hidden ancestor is a genuine alt-mode/conditional
      // wrap (e.g. ct_hv's select-vs-number toggle, or a checkbox-gated block) - but
      // NOT if the nearest hidden ancestor is a .tabpanel, since every equipment page
      // now starts with the Current Settings panel hidden behind the landing cards
      // (and every non-active inner analysis tab is hidden too). Without this
      // distinction, collectFields() would silently return an empty settings object
      // any time the user hasn't yet clicked into that tab.
      if (el.hidden) return;
      var hiddenAncestor = el.closest("[hidden]");
      if (hiddenAncestor && !hiddenAncestor.classList.contains("tabpanel")) return;
      var field = el.getAttribute("data-field");
      var raw = el.value;
      var num = parseFloat(raw);
      out[field] = (raw !== "" && !isNaN(num) && el.tagName !== "TEXTAREA") ? num : raw;
    });
    root.querySelectorAll('input[type="radio"]:checked').forEach(function (el) {
      if (el.name) out[el.name] = el.value;
    });
    return out;
  }

  function setFieldValue(el, value) {
    // <select> option values come from Jinja-rendered Python values (e.g. "5.0"),
    // which don't string-match a plain JS number (String(5) === "5", not "5.0").
    // A blind el.value = value silently fails to match any <option>, leaving the
    // select blank - so for selects, match loosely (numeric-aware) against the
    // option list instead of relying on the browser's exact-string match.
    if (el.tagName === "SELECT") {
      var target = String(value);
      var targetNum = parseFloat(value);
      var options = el.options;
      for (var i = 0; i < options.length; i++) {
        if (options[i].value === target || (!isNaN(targetNum) && parseFloat(options[i].value) === targetNum)) {
          el.value = options[i].value;
          return;
        }
      }
    }
    el.value = value;
  }

  function applyFields(root, values) {
    root = root || document;
    Object.keys(values || {}).forEach(function (field) {
      var value = values[field];
      root.querySelectorAll('[data-field="' + field + '"]').forEach(function (el) {
        setFieldValue(el, value);
      });
      root.querySelectorAll('[data-slider-pair="' + field + '"]').forEach(function (el) {
        setFieldValue(el, value);
      });
      var radios = root.querySelectorAll('input[type="radio"][name="' + field + '"]');
      radios.forEach(function (el) { el.checked = (String(el.value) === String(value)); });
    });
  }

  // ---------------------------------------------------------------------
  // common/settings_advisor.py, ported verbatim
  // ---------------------------------------------------------------------
  function suggestCtMatchingTap(iRatedPri, ctRatio, ctSecondaryRating, deltaFactor, relayRatedCurrent) {
    deltaFactor = deltaFactor === undefined ? 1.0 : deltaFactor;
    relayRatedCurrent = relayRatedCurrent === undefined ? 5.0 : relayRatedCurrent;
    var effectiveRatio = ctSecondaryRating > 0 ? ctRatio / ctSecondaryRating : ctRatio;
    var iSec = effectiveRatio > 0 ? iRatedPri / effectiveRatio : 0.0;
    var iRelay = iSec * deltaFactor;
    return iRelay > 0 ? relayRatedCurrent / iRelay : null;
  }

  function mismatchRatioPct(tapCurrents) {
    var valid = tapCurrents.filter(function (v) { return v !== null && v !== undefined && v > 0; });
    if (valid.length < 2) return null;
    var smallest = Math.min.apply(null, valid);
    var largest = Math.max.apply(null, valid);
    return smallest > 0 ? ((largest - smallest) / smallest) * 100.0 : null;
  }

  function suggestBiasSettings(mismatchPct, numWindings) {
    numWindings = numWindings === undefined ? 2 : numWindings;
    mismatchPct = (mismatchPct === null || mismatchPct === undefined) ? 0.0 : mismatchPct;
    var suggestedMinOperate = Math.max(20.0, Math.round(mismatchPct * 2 * 10) / 10);
    var suggestedBias = Math.max(suggestedMinOperate, numWindings === 2 ? 20.0 : 30.0);
    var suggestedHoc = numWindings === 2 ? 5.0 : 8.0;
    return { min_operate_pct: suggestedMinOperate, bias_pct: suggestedBias, hoc_multiple: suggestedHoc };
  }

  function computeMismatch(settings) {
    var mva = parseFloat(settings.mva) || 0;
    var kvHv = parseFloat(settings.kv_hv) || 0;
    var kvLv = parseFloat(settings.kv_lv) || 0;
    var ctHv = parseFloat(settings.ct_hv) || 0;
    var ctLv = parseFloat(settings.ct_lv) || 0;
    var ctSec = parseFloat(settings.ct_sec) || 5.0;
    var tapHv = parseFloat(settings.tap_hv) || 1.0;
    var tapLv = parseFloat(settings.tap_lv) || 1.0;
    var ctConnHv = String(settings.ct_conn_hv || "DELTA").toUpperCase();
    var ctConnLv = String(settings.ct_conn_lv || "WYE").toUpperCase();

    var deltaFactorHv = ctConnHv === "DELTA" ? 1.7320508 : 1.0;
    var deltaFactorLv = ctConnLv === "DELTA" ? 1.7320508 : 1.0;
    var iRatedPriHv = kvHv > 0 ? (mva * 1000.0) / (1.7320508 * kvHv) : 0.0;
    var iRatedPriLv = kvLv > 0 ? (mva * 1000.0) / (1.7320508 * kvLv) : 0.0;

    var t1e = suggestCtMatchingTap(iRatedPriHv, ctHv, ctSec, deltaFactorHv);
    var t2e = suggestCtMatchingTap(iRatedPriLv, ctLv, ctSec, deltaFactorLv);

    var iRelayHv = (ctHv > 0 && ctSec > 0) ? (iRatedPriHv / (ctHv / ctSec) * deltaFactorHv * tapHv) : null;
    var iRelayLv = (ctLv > 0 && ctSec > 0) ? (iRatedPriLv / (ctLv / ctSec) * deltaFactorLv * tapLv) : null;
    var calcMismatch = mismatchRatioPct([iRelayHv, iRelayLv]);

    var suggestion = suggestBiasSettings(calcMismatch || 0.0, 2);

    return { t1_e: t1e, t2_e: t2e, calc_mismatch_pct: calcMismatch, suggestion: suggestion };
  }

  global.SettingsForm = {
    initTabs: initTabs,
    bindSliderPairs: bindSliderPairs,
    collectFields: collectFields,
    applyFields: applyFields,
    suggestCtMatchingTap: suggestCtMatchingTap,
    mismatchRatioPct: mismatchRatioPct,
    suggestBiasSettings: suggestBiasSettings,
    computeMismatch: computeMismatch,
  };
})(window);
