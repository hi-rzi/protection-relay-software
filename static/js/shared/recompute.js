/* Shared fetch/POST + debounce helpers used by every equipment page's JS. */
(function (global) {
  "use strict";

  function postJSON(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }).then(function (resp) {
      if (!resp.ok) {
        return resp.text().then(function (text) {
          throw new Error("Request to " + url + " failed (" + resp.status + "): " + text);
        });
      }
      return resp.json();
    });
  }

  function postForBlob(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }).then(function (resp) {
      if (!resp.ok) throw new Error("Request to " + url + " failed (" + resp.status + ")");
      return resp.blob();
    });
  }

  function downloadBlob(blob, filename) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function debounce(fn, waitMs) {
    var timer = null;
    return function () {
      var args = arguments, ctx = this;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(ctx, args); }, waitMs);
    };
  }

  global.Recompute = {
    postJSON: postJSON,
    postForBlob: postForBlob,
    downloadBlob: downloadBlob,
    debounce: debounce,
  };
})(window);
