/*
 * Project-wide dashboard state — replaces common/project_state.py's
 * record_equipment_settings() mirror-into-session_state call. Each equipment
 * page's JS mirrors its current-settings object into localStorage under a
 * fixed key on every change; the (later-phase) Project page's JS reads all
 * 9 keys directly — no network call, no server-side state.
 */
(function (global) {
  "use strict";

  var STORAGE_PREFIX = "pomi_project_equipment.";

  function mirror(equipmentTag, settings) {
    try {
      localStorage.setItem(STORAGE_PREFIX + equipmentTag, JSON.stringify(settings));
    } catch (err) {
      // localStorage can throw in private-browsing/quota-exceeded situations —
      // this mirror is a nice-to-have, never block the page on it.
      console.warn("project-store: could not mirror settings for " + equipmentTag, err);
    }
  }

  function read(equipmentTag) {
    try {
      var raw = localStorage.getItem(STORAGE_PREFIX + equipmentTag);
      return raw ? JSON.parse(raw) : null;
    } catch (err) {
      return null;
    }
  }

  global.ProjectStore = { mirror: mirror, read: read, STORAGE_PREFIX: STORAGE_PREFIX };
})(window);
