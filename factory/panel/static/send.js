// Media factory panel: sending a draft (design authoring.md §17.4). On the review page it
// makes the missing crops (author.js draws them on a canvas from the original and they are
// posted one by one), moves the focus on a tap, opens the confirmation dialogs, reloads the
// page for another queue folder, and polls the status while a publish runs. On the draft
// page it only opens the «Удалить черновик» dialog. Every write is a same-origin POST; the
// server checks each one again.
(function () {
  "use strict";

  // ------------------------------------------------------------ dialogs (both pages)
  var opened = {};
  Array.prototype.forEach.call(document.querySelectorAll("[data-open]"), function (button) {
    button.addEventListener("click", function () {
      var dialog = document.getElementById(button.getAttribute("data-open"));
      if (!dialog || dialog.open || button.disabled) {
        return;
      }
      opened[dialog.id] = performance.now();
      dialog.showModal();   // modal: the page behind is inert, Escape closes it
    });
  });
  Array.prototype.forEach.call(document.querySelectorAll("dialog.dlg"), function (dialog) {
    var form = dialog.querySelector("form");
    var yes = dialog.querySelector("[data-confirm]");
    dialog.querySelector("[data-close]").addEventListener("click", function () { dialog.close(); });
    // The opener's second click of a double click lands where «Да, …» now is: such a click,
    // or one within 400 ms of opening, does nothing and the dialog stays open.
    yes.addEventListener("click", function (event) {
      if (event.detail > 1 || performance.now() - (opened[dialog.id] || 0) < 400) {
        event.preventDefault();
      }
    });
    form.addEventListener("submit", function (event) {
      if (yes.disabled) {
        event.preventDefault();
        return;
      }
      yes.disabled = true;   // one POST per confirmation
    });
    dialog.addEventListener("close", function () { yes.disabled = false; });
  });

  var root = document.querySelector("[data-send]");
  if (!root) {
    return;
  }
  var D = JSON.parse(root.getAttribute("data-send"));
  var T = D.strings;
  var MAX_BYTES = {facebook: 8 * 1024 * 1024, instagram: 8000000, linkedin: 8 * 1024 * 1024,
                   x: 5000000};
  var RATIO = {instagram: [4, 5], x: [16, 9]};
  var api = window.MFSend = {reload: function () { window.location.reload(); }, results: [],
                             posts: 0};

  function fill(text, values) {
    return text.replace(/\{(\w+)\}/g, function (_, key) {
      return values[key] === undefined ? "" : String(values[key]);
    });
  }

  function post(path, body, type) {
    return window.fetch(path, {method: "POST", body: body, credentials: "same-origin",
                               headers: {"Content-Type": type, "X-CSRF-Token": D.csrf}})
      .then(function (resp) {
        return resp.json().catch(function () { return {}; }).then(function (data) {
          if (!resp.ok) {
            throw new Error(data.error || String(resp.status));
          }
          return data;
        });
      }, function () { throw new Error(T.network); });
  }

  // ------------------------------------------------------------ the queue folder
  var select = root.querySelector("[data-folder]");
  if (select) {
    select.addEventListener("change", function () {
      window.location.assign(window.location.pathname + "?folder=" + encodeURIComponent(select.value));
    });
  }

  // ------------------------------------------------------------ crops
  var line = root.querySelector(".send-crops");

  function failed(network, reason, retry) {
    line.hidden = false;
    line.setAttribute("role", "alert");
    line.classList.add("k-bad");
    line.textContent = fill(T.crop_failed, {name: D.names[network] || network, reason: reason}) + " ";
    var again = document.createElement("button");
    again.type = "button";
    again.className = "btn";
    again.textContent = T.repeat;
    again.addEventListener("click", retry);
    line.appendChild(again);
  }

  // Draw and post the crops of `missing` (network names) from the original, then reload once.
  function prepare(missing, focus) {
    if (!missing.length) {
      return Promise.resolve();
    }
    line.hidden = false;
    line.setAttribute("role", "status");
    line.classList.remove("k-bad");
    line.textContent = fill(T.crops, {names: missing.map(function (n) { return D.names[n]; }).join(", ")});
    var current = missing[0], bitmap = null;
    return window.fetch(D.orig, {credentials: "same-origin"}).then(function (resp) {
      if (!resp.ok) {
        throw new Error(String(resp.status));
      }
      return resp.blob();
    }).then(function (blob) {
      return createImageBitmap(blob, {imageOrientation: "from-image"}).catch(function () {
        throw new Error(T.decode);
      });
    }, function () { throw new Error(T.network); }).then(function (decoded) {
      bitmap = decoded;
      var chain = Promise.resolve();
      missing.forEach(function (network) {
        chain = chain.then(function () {
          current = network;
          var size = window.MFAuthor.cropSize(network, bitmap.width, bitmap.height);
          var spec = {ratio: RATIO[network] || null, width: size[0], height: size[1],
                      maxBytes: MAX_BYTES[network]};
          return window.MFAuthor.makeCrop(bitmap, spec, focus).then(function (crop) {
            api.results.push({network: network, width: crop.width, height: crop.height,
                              window: crop.window, bytes: crop.blob.size, quality: crop.quality});
            api.posts += 1;
            var query = new URLSearchParams({network: network, fx: String(focus[0]),
                                             fy: String(focus[1])}).toString();
            return post("/create/" + D.did + "/image?" + query, crop.blob, "image/jpeg");
          });
        });
      });
      return chain;
    }).then(function () {
      bitmap.close();
      api.reload();
    }, function (err) {
      if (bitmap) {
        bitmap.close();
      }
      var left = missing.slice(missing.indexOf(current));
      failed(current, err.message, function () { prepare(left, focus); });
    });
  }
  api.prepare = prepare;

  // ------------------------------------------------------------ focus
  var photo = root.querySelector("[data-focus]");
  if (photo) {
    var img = photo.querySelector("img");
    var ring = photo.querySelector(".send-ring");
    // the image's box inside the fixed box (object-fit: contain)
    var contained = function () {
      var r = img.getBoundingClientRect();
      var k = Math.min(r.width / (img.naturalWidth || 1), r.height / (img.naturalHeight || 1));
      var w = img.naturalWidth * k, h = img.naturalHeight * k;
      return {left: r.left + (r.width - w) / 2, top: r.top + (r.height - h) / 2, width: w, height: h};
    };
    var place = function () {
      if (!img.naturalWidth) {
        return;
      }
      var c = contained(), own = photo.getBoundingClientRect();
      ring.style.left = (c.left - own.left + D.focus[0] * c.width) + "px";
      ring.style.top = (c.top - own.top + D.focus[1] * c.height) + "px";
      ring.hidden = false;
    };
    if (img.complete) {
      place();
    } else {
      img.addEventListener("load", place);
    }
    window.addEventListener("resize", place);
    var tap = function (fx, fy) {
      var focus = {fx: Math.round(fx * 1000) / 1000, fy: Math.round(fy * 1000) / 1000};
      return post("/create/" + D.did + "/focus", JSON.stringify(focus), "application/json")
        .then(function (stored) { api.focus = stored.focus; api.reload(); },
              function (err) { failed("instagram", err.message, function () { tap(fx, fy); }); });
    };
    api.tap = tap;
    photo.addEventListener("click", function (event) {
      var c = contained();
      var fx = Math.min(1, Math.max(0, (event.clientX - c.left) / c.width));
      var fy = Math.min(1, Math.max(0, (event.clientY - c.top) / c.height));
      tap(fx, fy);
    });
  }

  // ------------------------------------------------------------ status while publishing
  function render(status) {
    var head = root.querySelector(".send-status-line");
    if (head) {
      head.textContent = status.line;
    }
    status.targets.forEach(function (item) {
      var row = root.querySelector('.send-rows li[data-target="' + item.target + '"]');
      if (!row) {
        return;
      }
      var word = row.querySelector("[data-status]");
      word.textContent = item.text;
      word.className = "st k-" + ({published: "ok", waiting: "muted"}[item.status] || "bad");
      var holder = row.querySelector(".send-link");
      holder.textContent = "";
      if (item.url) {
        var a = document.createElement("a");
        a.className = "send-open";
        a.href = item.url;
        a.target = "_blank";
        a.rel = "noopener";
        a.textContent = fill(T.open, {name: D.names[item.network]});
        holder.append(" · ", a);
      }
    });
  }
  api.render = render;

  if (D.live) {
    var timer = window.setInterval(function () {
      window.fetch("/create/" + D.did + "/status", {credentials: "same-origin"})
        .then(function (resp) { return resp.json(); })
        .then(function (status) {
          render(status);
          if (status.state !== "publishing" || status.interrupted) {
            window.clearInterval(timer);
            api.reload();   // once: the finished page carries its own actions
          }
        }, function () { /* the next poll tries again */ });
    }, 3000);
  }

  if (D.state === "draft" && D.missing.length) {
    prepare(D.missing, D.focus);
  }
})();
