// Media factory panel: photo upload into a photo-lane stock folder (design authoring.md §6.1).
// Loaded only on the folder view of a photo folder. All pixel work happens here: the browser
// decodes the original (EXIF orientation applied), draws a 480 px thumb and a 1 600 px view
// copy, and posts the original bytes, the thumb and the view copy one by one, each as the raw
// request body with the CSRF token in a header. Strings come from strings.py (data-strings).
(function () {
  "use strict";

  var TYPES = {"image/jpeg": 1, "image/png": 1, "image/webp": 1};
  var EXTS = /\.(jpe?g|png|webp)$/i;
  var HEIC = /\.(heic|heif)$/i;
  var MAX_PICK = 300;
  var THUMB = {side: 480, quality: 0.82};
  var VIEW = {side: 1600, quality: 0.88};

  // One downscaled JPEG copy of a decoded bitmap: long side at most `side`, never upscaled.
  function copy(bitmap, spec) {
    var k = Math.min(1, spec.side / Math.max(bitmap.width, bitmap.height));
    var w = Math.max(1, Math.round(bitmap.width * k));
    var h = Math.max(1, Math.round(bitmap.height * k));
    return createImageBitmap(bitmap, {resizeWidth: w, resizeHeight: h, resizeQuality: "high"})
      .then(function (small) {
        var canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        var g = canvas.getContext("2d");
        g.fillStyle = "#ffffff";   // a transparent PNG gets a white ground, not black
        g.fillRect(0, 0, w, h);
        g.drawImage(small, 0, 0);
        small.close();
        return new Promise(function (resolve, reject) {
          canvas.toBlob(function (blob) {
            if (blob) {
              resolve({blob: blob, width: w, height: h});
            } else {
              reject(new Error("toBlob"));
            }
          }, "image/jpeg", spec.quality);
        });
      });
  }

  // The thumb and the view copy of one image Blob; the probe calls this same function.
  function makeCopies(blob) {
    return createImageBitmap(blob, {imageOrientation: "from-image"}).then(function (full) {
      var out = {width: full.width, height: full.height};
      return copy(full, THUMB).then(function (thumb) {
        out.thumb = thumb;
        return copy(full, VIEW);
      }).then(function (view) {
        out.view = view;
        full.close();
        return out;
      }, function (err) {
        full.close();
        throw err;
      });
    });
  }

  window.MFAuthor = {makeCopies: makeCopies};

  var section = document.querySelector("section[data-photos]");
  if (!section) {
    return;
  }
  var folder = section.getAttribute("data-photos");
  var csrf = section.getAttribute("data-csrf");
  var T = JSON.parse(section.getAttribute("data-strings"));
  var statusLine = section.querySelector(".upload-status");
  var skippedList = section.querySelector(".upload-skipped");
  var buttons = section.querySelectorAll("[data-pick]");

  function fill(text, values) {
    return text.replace(/\{(\w+)\}/g, function (_, key) {
      return values[key] === undefined ? "" : String(values[key]);
    });
  }

  function plural(n, forms) {
    var a = Math.abs(n) % 100, b = a % 10;
    if (b === 1 && a !== 11) {
      return forms[0];
    }
    return b >= 2 && b <= 4 && (a < 12 || a > 14) ? forms[1] : forms[2];
  }

  function post(params, body, type) {
    var url = "/files/photos?" + new URLSearchParams(params).toString();
    return fetch(url, {method: "POST", body: body, credentials: "same-origin",
                       headers: {"Content-Type": type, "X-CSRF-Token": csrf}})
      .then(function (resp) {
        return resp.json().catch(function () { return {}; }).then(function (data) {
          if (!resp.ok) {
            var err = new Error(data.error || String(resp.status));
            err.status = resp.status;
            throw err;
          }
          return data;
        });
      }, function () {
        var err = new Error(T.network);
        err.status = 0;
        throw err;
      });
  }

  // The status line: each label with its number is one unbreakable piece, and a "·"
  // closes the piece before it, so no wrapped line starts with a separator.
  function show(state) {
    var parts = [fill(T.progress, {done: state.done, total: state.total})];
    if (state.dup) {
      parts.push(fill(T.dup, {n: state.dup}));
    }
    if (state.skipped.length) {
      parts.push(fill(T.skipped, {n: state.skipped.length}));
    }
    statusLine.textContent = "";
    statusLine.appendChild(document.createTextNode((state.finished ? T.done : T.running) + " "));
    parts.forEach(function (text, i) {
      var piece = document.createElement("span");
      piece.className = "nw";
      piece.textContent = text + (i < parts.length - 1 ? " ·" : "");
      statusLine.appendChild(piece);
      statusLine.appendChild(document.createTextNode(" "));
    });
    if (state.skipped.length) {
      var tags = [];
      state.skipped.forEach(function (s) {
        if (tags.indexOf(s.tag) < 0) {
          tags.push(s.tag);
        }
      });
      statusLine.appendChild(document.createTextNode("(" + tags.join(", ") + ")"));
    }
  }

  function skip(state, file, reason, tag) {
    state.skipped.push({name: file.webkitRelativePath || file.name, reason: reason, tag: tag});
    var li = document.createElement("li");
    li.className = "small";
    var name = document.createElement("span");
    name.className = "mono";
    name.textContent = file.webkitRelativePath || file.name;
    li.appendChild(name);
    li.appendChild(document.createTextNode(" — " + reason));
    skippedList.appendChild(li);
  }

  function uploadOne(state, file) {
    return makeCopies(file).then(function (copies) {
      return post({folder: folder, kind: "orig"}, file, file.type || "image/jpeg")
        .then(function (answer) {
          if (answer.dup) {   // already listed: counted as loaded, and named apart
            state.done += 1;
            state.dup += 1;
            return null;
          }
          return post({folder: folder, kind: "thumb", id: answer.id}, copies.thumb.blob,
                      "image/jpeg").then(function () {
            return post({folder: folder, kind: "view", id: answer.id, w: copies.view.width,
                         h: copies.view.height, name: file.name},
                        copies.view.blob, "image/jpeg");
          }).then(function () {
            state.done += 1;
          });
        });
    }, function () {
      skip(state, file, T.decode, T.decode);
      return null;
    }).catch(function (err) {
      if (err.status === 403 || err.status === 0) {
        throw err;   // a stale token or a stopped panel: the rest would fail the same way
      }
      skip(state, file, err.message, err.message);
    });
  }

  function upload(files) {
    var list = Array.prototype.slice.call(files);
    list.sort(function (a, b) {
      var x = a.webkitRelativePath || a.name, y = b.webkitRelativePath || b.name;
      return x < y ? -1 : (x > y ? 1 : 0);
    });
    skippedList.textContent = "";
    if (list.length > MAX_PICK) {
      statusLine.textContent = fill(T.too_many, {n: list.length,
                                                 files: plural(list.length, T.files)});
      return Promise.resolve(null);
    }
    var state = {done: 0, dup: 0, total: list.length, skipped: [], finished: false,
                 stopped: false};
    var photos = list.filter(function (f) {
      if (HEIC.test(f.name) || /heic|heif/i.test(f.type)) {
        skip(state, f, T.heic, "HEIC");
        return false;
      }
      if (!TYPES[f.type] && !EXTS.test(f.name)) {
        skip(state, f, T.type, T.type);
        return false;
      }
      return true;
    });
    buttons.forEach(function (b) { b.disabled = true; });
    show(state);
    var chain = Promise.resolve();
    photos.forEach(function (f) {
      chain = chain.then(function () {
        return uploadOne(state, f).then(function () { show(state); });
      });
    });
    return chain.then(function () {
      state.finished = true;
      show(state);
      return state;
    }, function (err) {
      state.finished = true;
      state.stopped = true;
      statusLine.textContent = fill(T.stopped, {reason: err.message});
      return state;
    }).then(function (result) {
      buttons.forEach(function (b) { b.disabled = false; });
      if (result.skipped.length === 0 && !result.stopped) {
        window.location.reload();
      } else {
        var again = document.createElement("a");
        again.className = "btn";
        again.href = window.location.pathname + window.location.search;
        again.textContent = T.reload;
        statusLine.appendChild(document.createTextNode(" "));
        statusLine.appendChild(again);
      }
      return result;
    });
  }

  window.MFAuthor.upload = upload;

  buttons.forEach(function (button) {
    var input = section.querySelector('[data-input="' + button.getAttribute("data-pick") + '"]');
    button.disabled = false;
    button.addEventListener("click", function () {
      input.value = "";
      input.click();
    });
    input.addEventListener("change", function () {
      if (input.files && input.files.length) {
        upload(input.files);
      }
    });
  });
})();
