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

  // Slice D′ (authoring.md §17.1, D18–D20). The output size of one network's plain crop for
  // an original of w x h (D19): Instagram 4k x 5k (k <= 270), X 16k x 9k (k <= 100), Facebook
  // and LinkedIn the original ratio with the long side min(2048, the original's). Never
  // upscaled. send.py's crop_size is the same rule.
  var CROP = {instagram: [4, 5, 270], x: [16, 9, 100]};
  function cropSize(network, w, h) {
    var r = CROP[network];
    if (r) {
      var k = Math.min(r[2], Math.floor(w / r[0]), Math.floor(h / r[1]));
      return [r[0] * k, r[1] * k];
    }
    var long = Math.max(w, h), side = Math.min(2048, long);
    return w >= h ? [side, Math.max(1, Math.round(h * side / long))] :
      [Math.max(1, Math.round(w * side / long)), side];
  }

  // The source window: the largest one of `ratio` ([a, b] or null for the whole photo),
  // centred on `focus` ([fx, fy] in 0..1) and clamped inside the photo.
  function cropWindow(w, h, ratio, focus) {
    if (!ratio) {
      return [0, 0, w, h];
    }
    var ww, wh;
    if (w * ratio[1] > h * ratio[0]) {
      ww = Math.round(h * ratio[0] / ratio[1]);
      wh = h;
    } else {
      ww = w;
      wh = Math.round(w * ratio[1] / ratio[0]);
    }
    return [Math.round(Math.min(Math.max(focus[0] * w - ww / 2, 0), w - ww)),
            Math.round(Math.min(Math.max(focus[1] * h - wh / 2, 0), h - wh)), ww, wh];
  }

  // One plain crop of a decoded original (no effects): spec = {ratio, width, height,
  // maxBytes}. JPEG at 0.9, then 0.8 and 0.7 while the file is over maxBytes. The canvas
  // writes no camera metadata. Resolves {blob, width, height, window, quality}.
  function makeCrop(bitmap, spec, focus) {
    var win = cropWindow(bitmap.width, bitmap.height, spec.ratio, focus || [0.5, 0.5]);
    return createImageBitmap(bitmap, win[0], win[1], win[2], win[3],
                             {resizeWidth: spec.width, resizeHeight: spec.height, resizeQuality: "high"})
      .then(function (small) {
        var canvas = document.createElement("canvas");
        canvas.width = spec.width;
        canvas.height = spec.height;
        var g = canvas.getContext("2d");
        g.fillStyle = "#ffffff";
        g.fillRect(0, 0, spec.width, spec.height);
        g.drawImage(small, 0, 0);
        small.close();
        var qualities = [0.9, 0.8, 0.7];
        function attempt(i) {
          return new Promise(function (resolve, reject) {
            canvas.toBlob(function (blob) {
              if (blob) { resolve(blob); } else { reject(new Error("toBlob")); }
            }, "image/jpeg", qualities[i]);
          }).then(function (blob) {
            if (blob.size > spec.maxBytes && i + 1 < qualities.length) {
              return attempt(i + 1);
            }
            return {blob: blob, width: spec.width, height: spec.height, window: win,
                    quality: qualities[i]};
          });
        }
        return attempt(0);
      });
  }

  function uploadStrings() {
    var root = document.querySelector("[data-create]");
    return root ? JSON.parse(root.dataset.create).upload_strings :
      JSON.parse(document.querySelector("[data-strings]").dataset.strings);
  }

  function uploadFile(folder, csrf, file) {
    var strings = uploadStrings();
    var reason = HEIC.test(file.name) || /heic|heif/i.test(file.type) ? strings.heic :
      (!TYPES[file.type] && !EXTS.test(file.name) ? strings.type : "");
    if (reason) {
      var invalid = new Error(reason);
      invalid.status = 422;
      return Promise.reject(invalid);
    }
    return makeCopies(file).catch(function () {
      var error = new Error(strings.decode);
      error.status = 422;
      throw error;
    }).then(function (copies) {
      return post({folder: folder, kind: "orig"}, file, file.type || "image/jpeg", csrf)
        .then(function (answer) {
          if (answer.dup) { return answer; }
          return post({folder: folder, kind: "thumb", id: answer.id}, copies.thumb.blob,
                      "image/jpeg", csrf).then(function () {
            return post({folder: folder, kind: "view", id: answer.id,
                         w: copies.view.width, h: copies.view.height, name: file.name},
                        copies.view.blob, "image/jpeg", csrf);
          }).then(function () { return {id: answer.id, dup: false}; });
        });
    });
  }

  window.MFAuthor = {makeCopies: makeCopies, uploadFile: uploadFile, makeCrop: makeCrop,
                     cropSize: cropSize, cropWindow: cropWindow};

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

  function post(params, body, type, csrfToken) {
    var url = "/files/photos?" + new URLSearchParams(params).toString();
    return fetch(url, {method: "POST", body: body, credentials: "same-origin",
                       headers: {"Content-Type": type, "X-CSRF-Token": csrfToken}})
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
        var err = new Error(uploadStrings().network);
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
    statusLine.appendChild(document.createTextNode(state.finished ? T.done : T.running));
    parts.forEach(function (text, i) {
      var piece = document.createElement("span");
      piece.className = "nw";
      piece.textContent = text + (i < parts.length - 1 ? " ·" : "");
      statusLine.appendChild(document.createTextNode(" "));
      statusLine.appendChild(piece);
    });
  }

  // A skipped file is listed under its folder (shown once per folder) by base name, then
  // ": reason". The status line only counts; the reasons live here.
  var groups = {};

  function skip(state, file, reason) {
    var path = file.webkitRelativePath || file.name;
    var cut = path.lastIndexOf("/");
    var dir = cut < 0 ? "" : path.slice(0, cut + 1);
    state.skipped.push({name: path, reason: reason});
    var group = groups[dir];
    if (!group) {
      var item = document.createElement("li");
      if (dir) {
        var heading = document.createElement("span");
        heading.className = "dir mono small";
        heading.textContent = dir;
        item.appendChild(heading);
      }
      group = document.createElement("ul");
      item.appendChild(group);
      skippedList.appendChild(item);
      groups[dir] = group;
    }
    var li = document.createElement("li");
    li.className = "small";
    var name = document.createElement("span");
    name.className = "mono";
    name.textContent = path.slice(cut + 1);
    li.appendChild(name);
    li.appendChild(document.createTextNode(": " + reason));
    group.appendChild(li);
  }

  function uploadOne(state, file) {
    return uploadFile(folder, csrf, file).then(function (answer) {
      state.done += 1;
      if (answer.dup) { state.dup += 1; } else { state.fresh += 1; }
    }).catch(function (err) {
      if (err.status === 403 || err.status === 0) { throw err; }
      skip(state, file, err.message);
    });
  }

  function upload(files) {
    var list = Array.prototype.slice.call(files);
    list.sort(function (a, b) {
      var x = a.webkitRelativePath || a.name, y = b.webkitRelativePath || b.name;
      return x < y ? -1 : (x > y ? 1 : 0);
    });
    skippedList.textContent = "";
    groups = {};
    if (list.length > MAX_PICK) {
      statusLine.textContent = fill(T.too_many, {n: list.length,
                                                 files: plural(list.length, T.files)});
      return Promise.resolve(null);
    }
    var state = {done: 0, dup: 0, fresh: 0, total: list.length, skipped: [], finished: false,
                 stopped: false};
    var photos = list.filter(function (f) {
      if (HEIC.test(f.name) || /heic|heif/i.test(f.type)) {
        skip(state, f, T.heic);
        return false;
      }
      if (!TYPES[f.type] && !EXTS.test(f.name)) {
        skip(state, f, T.type);
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
        remember(result);
        window.MFAuthor.reload();
      } else {
        var again = document.createElement("a");
        again.className = "btn";
        again.href = window.location.pathname + window.location.search;
        // a run that stored photos names what the button shows; a stopped one may need a
        // fresh page (token) first, so it keeps the plain word
        again.textContent = result.fresh > 0 && !result.stopped ? T.reload_new : T.reload;
        statusLine.appendChild(document.createTextNode(" "));
        statusLine.appendChild(again);
      }
      return result;
    });
  }

  // A clean run ends with a reload; the count of that run is kept for the new page, which
  // shows it as the done line (the grid lists the newest photos first).
  var KEY = "mf-upload-done";

  function remember(result) {
    try {
      window.sessionStorage.setItem(KEY, JSON.stringify(
        {folder: folder, done: result.done, dup: result.dup, total: result.total}));
    } catch (err) {
      // storage refused: the page reloads without the line
    }
  }

  function restore() {
    var saved = null;
    try {
      saved = JSON.parse(window.sessionStorage.getItem(KEY));
      window.sessionStorage.removeItem(KEY);
    } catch (err) {
      return null;
    }
    if (!saved || saved.folder !== folder || !(saved.done > 0) || !(saved.total >= saved.done)) {
      return null;
    }
    var state = {done: saved.done, dup: saved.dup > 0 ? saved.dup : 0, total: saved.total,
                 skipped: [], finished: true};
    show(state);
    return state;
  }

  window.MFAuthor.reload = function () { window.location.reload(); };
  window.MFAuthor.restore = restore;
  window.MFAuthor.upload = upload;

  restore();

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
