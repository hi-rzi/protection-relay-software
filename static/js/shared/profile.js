/*
 * Profile save/load — replaces common/profile_io.py. Client-side only: Blob
 * download for save, FileReader for load. Same JSON shape as the Streamlit
 * app's exported profiles ({format, version, equipment, profile_name,
 * settings}), so files saved from either version are interchangeable.
 */
(function (global) {
  "use strict";

  var FORMAT_TAG = "Electrical Equipment Protection Suite profile";

  function safeFilename(name, fallback) {
    fallback = fallback || "profile";
    var cleaned = (name || "").replace(/[^a-zA-Z0-9 _-]/g, "").trim().replace(/ /g, "_");
    return cleaned || fallback;
  }

  function save(equipmentTag, profileName, settings) {
    var payload = {
      format: FORMAT_TAG,
      version: 1,
      equipment: equipmentTag,
      profile_name: profileName,
      exported_at: new Date().toISOString(),
      settings: settings,
    };
    var blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    global.Recompute.downloadBlob(blob, safeFilename(profileName) + ".json");
  }

  function load(file, equipmentTag) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () {
        try {
          var payload = JSON.parse(reader.result);
          if (payload.format !== FORMAT_TAG) {
            reject(new Error("This does not look like a profile saved from this app."));
            return;
          }
          if (payload.equipment !== equipmentTag) {
            reject(new Error('This profile is for "' + payload.equipment + '", not this equipment.'));
            return;
          }
          if (typeof payload.settings !== "object" || payload.settings === null) {
            reject(new Error("The file does not contain a settings section."));
            return;
          }
          resolve(payload);
        } catch (err) {
          reject(err);
        }
      };
      reader.onerror = function () { reject(new Error("Could not read the file.")); };
      reader.readAsText(file);
    });
  }

  global.Profile = { save: save, load: load, safeFilename: safeFilename };
})(window);
