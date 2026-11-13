// Visual-check probe, loaded only with ?probe=1 (design factory.md §13.3 item 4). It measures
// the rendered page and writes the findings as JSON into <pre id="probe">.
(function () {
  "use strict";
  var MAX = 60;
  var measured = [];   // reported in the JSON, so a run shows what was measured

  function name(el) {
    var s = el.tagName.toLowerCase();
    if (el.id) {
      s += "#" + el.id;
    }
    var cls = el.getAttribute("class");
    if (cls) {
      s += "." + cls.trim().split(/\s+/).join(".");
    }
    return s;
  }

  function shown(el) {
    if (el.closest(".sr")) {
      return false;
    }
    var details = el.closest("details");
    if (details && !details.open && !el.closest("summary")) {
      return false;   // inside a closed <details>: not rendered, though Chrome keeps its box
    }
    var cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none") {
      return false;
    }
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  var BLOCKS = ["block", "inline-block", "flow-root", "list-item", "table-cell", "-webkit-box"];

  // text-overflow: ellipsis (and a line clamp) only render on a block-level container that
  // clips its overflow; flex, grid and plain inline boxes ignore it
  function cs_noEllipsis(cs) {
    if (cs.webkitLineClamp && cs.webkitLineClamp !== "none" && cs.textOverflow !== "ellipsis") {
      return false;
    }
    return BLOCKS.indexOf(cs.display) < 0 || cs.overflowX === "visible";
  }

  function clampText(e) {
    return e.textContent.trim().slice(0, 60);
  }

  var splits = [];
  var ellipsized = [];
  var whole = [];

  // a number (digits, thin-space groups, decimal mark) must stay on one line
  function splitNumbers(node, el) {
    var re = /\d[\d\u00a0\u202f.,]*\d|\d/g, m;
    while ((m = re.exec(node.textContent))) {
      var r = document.createRange();
      r.setStart(node, m.index);
      r.setEnd(node, m.index + m[0].length);
      var rs = Array.prototype.filter.call(r.getClientRects(), function (t) { return t.width > 0; });
      if (rs.length > 1) {
        var tops = rs.map(function (t) { return t.top; });
        if (Math.max.apply(null, tops) - Math.min.apply(null, tops) > rs[0].height / 2) {
          splits.push([el, m[0]]);
          break;
        }
      }
    }
  }

  function run() {
    var findings = [];
    var startY = window.scrollY;   // where a #fragment left the page; the checks restore it
    var W = document.documentElement.clientWidth;
    function add(kind, el, detail) {
      if (findings.length < MAX) {
        findings.push({kind: kind, el: el ? name(el) : "", text: (el && el.textContent || "")
          .trim().slice(0, 60), detail: detail || ""});
      }
    }
    var modal = document.querySelector("dialog:modal");
    var root = modal || document.body;

    if (document.documentElement.scrollWidth > W + 0.5) {
      add("page-scroll", document.documentElement, document.documentElement.scrollWidth + " > " + W);
    }
    document.body.querySelectorAll("*").forEach(function (el) {
      if (!shown(el)) {
        return;
      }
      var r = el.getBoundingClientRect();
      if (r.right > W + 0.5 || r.left < -0.5) {
        add("wider-than-viewport", el, Math.round(r.left) + ".." + Math.round(r.right));
      }
    });

    // text cut by its box: compare each text node's Range with its element and every
    // clipping ancestor; deliberate clamps must carry a title (or be decorative)
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    var node;
    while ((node = walker.nextNode())) {
      if (!node.textContent.trim()) {
        continue;
      }
      var el = node.parentElement;
      if (!el || !shown(el) || el.closest("#probe")) {
        continue;
      }
      var clamped = null;
      for (var e = el; e && e !== document.body; e = e.parentElement) {
        var cs = getComputedStyle(e);
        if (cs.textOverflow === "ellipsis" || (cs.webkitLineClamp && cs.webkitLineClamp !== "none")) {
          clamped = e;
          break;
        }
      }
      if (clamped) {
        // an ellipsis only renders on a block container that clips: a flex/grid/inline box
        // or an unclipped one cuts or spills the text with no "…"
        var ccs = getComputedStyle(clamped);
        if (!cs_noEllipsis(ccs) && ccs.textOverflow === "ellipsis") {
          // truncated: the "…" really renders here; otherwise the whole text is visible
          var list = clamped.scrollWidth > clamped.clientWidth + 0.5 ? ellipsized : whole;
          if (list.indexOf(clamped) < 0) {
            list.push(clamped);
          }
        }
        if (cs_noEllipsis(ccs)) {
          add("clamp-cannot-ellipsize", clamped, "display " + ccs.display + ", overflow " +
            ccs.overflowX);
        }
        if (!clamped.hasAttribute("title") && !clamped.closest("[title]") &&
            !clamped.closest('[aria-hidden="true"]')) {
          add("clamp-without-title", clamped);
        }
        continue;
      }
      var range = document.createRange();
      range.selectNodeContents(node);
      var rects = Array.prototype.slice.call(range.getClientRects());
      splitNumbers(node, el);
      var own = el.getBoundingClientRect();
      var bad = rects.some(function (t) {
        return t.width > 0 && (t.right > own.right + 1 || t.left < own.left - 1);
      });
      if (bad && el.namespaceURI !== "http://www.w3.org/2000/svg") {
        add("text-overflows-box", el);
        continue;
      }
      for (var a = el; a && a !== document.documentElement; a = a.parentElement) {
        var st = getComputedStyle(a);
        if (st.overflowX === "visible" && st.overflowY === "visible") {
          continue;
        }
        var box = a.getBoundingClientRect();
        var cut = rects.some(function (t) {
          return t.width > 0 && (t.right > box.right + 1 || t.left < box.left - 1 ||
            (st.overflowY !== "auto" && st.overflowY !== "scroll" &&
             (t.bottom > box.bottom + 1 || t.top < box.top - 1)));
        });
        if (cut) {
          add("text-cut", el, "by " + name(a));
          break;
        }
      }
    }

    splits.forEach(function (pair) { add("number-split", pair[0], pair[1]); });

    // anchors that a link jumps to must not land under the sticky tab bar
    var bar = document.querySelector(".topbar");
    if (bar && getComputedStyle(bar).position === "sticky" && !modal) {
      document.querySelectorAll('[id^="rule-"]:not(#rule-new), #today').forEach(function (target) {
        target.scrollIntoView();
        var top = target.getBoundingClientRect().top;
        if (top < bar.getBoundingClientRect().bottom - 1) {
          add("under-sticky-bar", target, Math.round(top) + " < " +
            Math.round(bar.getBoundingClientRect().bottom));
        }
      });
      window.scrollTo(0, startY);
    }

    // a page-level alert (a refusal or error banner) is read on the first screen: measure
    // its text range, not its box
    document.querySelectorAll(".main > .error[role=alert], .main > section.error").forEach(
      function (el) {
        var range = document.createRange();
        range.selectNodeContents(el);
        var rect = range.getBoundingClientRect();
        if (shown(el) && rect.bottom > window.innerHeight) {
          add("alert-below-first-screen", el, Math.round(rect.bottom) + " > " + window.innerHeight);
        }
      });

    // controls: at least 24 x 24, and no two overlapping (nested ones excepted)
    var controls = Array.prototype.filter.call(
      root.querySelectorAll("a[href], button, input, select, textarea, summary, [tabindex]"),
      function (el) { return shown(el) && el.type !== "hidden"; });
    var boxes = controls.map(function (el) { return el.getBoundingClientRect(); });
    controls.forEach(function (el, i) {
      var r = boxes[i];
      if ((r.width < 24 || r.height < 24) && !(el.type === "checkbox" && el.closest("label"))) {
        add("small-target", el, Math.round(r.width) + "x" + Math.round(r.height));
      }
    });
    for (var i = 0; i < controls.length; i++) {
      for (var j = i + 1; j < controls.length; j++) {
        var p = boxes[i], q = boxes[j];
        var w = Math.min(p.right, q.right) - Math.max(p.left, q.left);
        var h = Math.min(p.bottom, q.bottom) - Math.max(p.top, q.top);
        // content scrolled under the opaque sticky bar is covered, not overlapped
        var bar = document.querySelector(".topbar");
        var underBar = bar && getComputedStyle(bar).position === "sticky" &&
          bar.contains(controls[i]) !== bar.contains(controls[j]);
        if (w > 0.5 && h > 0.5 && !underBar && !controls[i].contains(controls[j]) &&
            !controls[j].contains(controls[i])) {
          add("overlap", controls[i], "with " + name(controls[j]));
        }
      }
    }
    measureLayout(add, W, modal);
    expanders(add, startY, function () {
      photoChecks(function (photos) {
        var pre = document.createElement("pre");
        pre.id = "probe";
        pre.textContent = JSON.stringify({width: W, height: document.documentElement.scrollHeight,
                                          controls: controls.length, findings: findings, scrollY: window.scrollY,
                                          hash: location.hash, expanders: measured,
                                          ellipsis: ellipsized.map(clampText),
                                          whole: whole.map(clampText), photos: photos, author: window.MFProbeAuthor});
        document.body.appendChild(pre);
      });
    });
  }

  function canvasJpeg(w, h, shade) {
    var canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    var g = canvas.getContext("2d");
    g.fillStyle = "rgb(" + shade + ", 90, " + (255 - shade) + ")";
    g.fillRect(0, 0, w, h);
    g.fillStyle = "#ffffff";
    g.fillRect(w >> 2, h >> 2, w >> 1, h >> 1);
    return new Promise(function (resolve) { canvas.toBlob(resolve, "image/jpeg", 0.9); });
  }

  function runInfo(state, calls) {
    var button = document.querySelector(".upload-status a.btn");
    // the skip list as rendered: [folder heading or "", [row text, ...]] per group
    var list = Array.prototype.map.call(document.querySelectorAll(".upload-skipped > li"),
      function (group) {
        var heading = group.querySelector(".dir");
        return [heading ? heading.textContent : "", Array.prototype.map.call(
          group.querySelectorAll("ul > li"), function (li) { return li.textContent; })];
      });
    return {done: state.done, dup: state.dup, fresh: state.fresh, stopped: state.stopped,
            calls: calls,
            skipped: state.skipped.map(function (s) { return [s.name, s.reason]; }),
            list: list, button: button ? button.textContent : null,
            status: document.querySelector(".upload-status").textContent};
  }

  // A file as a folder pick lists it: with its folder-relative path.
  function inFolder(file, path) {
    Object.defineProperty(file, "webkitRelativePath", {value: path});
    return file;
  }

  // The real upload loop, three runs on one page (probe_upload=1). Run 1: the first listed
  // original (already stored: a duplicate), a HEIC file, a text file, an undecodable .jpg,
  // a decodable file sent as image/gif (the server refuses it) and one new decodable file
  // whose size and colour depend on the window width, so parallel widths never collide as
  // duplicates; it goes through the orig, thumb and view posts for real. Runs 2 and 3 stub
  // fetch (a refused request, then a stale-token 403): the loop must stop after one request.
  // Between run 1 and the stubs, a clean run of one new file ends with the page reload (stubbed
  // here) and the count it keeps for the new page, which restore() shows as the done line.
  function uploadRuns(origBlob, out) {
    var W = window.innerWidth;
    var realFetch = window.fetch;
    var calls = 0;
    function stub(make) {
      window.fetch = function () {
        calls += 1;
        return make();
      };
    }
    function run(files) {
      calls = 0;
      return window.MFAuthor.upload(files);
    }
    var tiny;
    return canvasJpeg(20, 20, 7).then(function (blob) {
      tiny = blob;
      return canvasJpeg(40 + (W % 97), 30 + (W % 53), W % 200);
    }).then(function (fresh) {
      out.newName = "new-" + W + ".jpg";
      out.newSize = [40 + (W % 97), 30 + (W % 53)];
      var gif = new File([fresh], "refused.jpg", {type: "image/gif"});
      return run([new File([origBlob], "IMG_0001.jpg", {type: "image/jpeg"}),
                  inFolder(new File([new Uint8Array(32)], "IMG_0002.HEIC", {type: ""}),
                           "Поездка/Набережная/IMG_0002.HEIC"),
                  inFolder(new File(["notes"], "notes.txt", {type: "text/plain"}),
                           "Поездка/notes.txt"),
                  inFolder(new File(["not an image"], "broken.jpg", {type: "image/jpeg"}),
                           "Поездка/Набережная/broken.jpg"),
                  gif,
                  new File([fresh], out.newName, {type: "image/jpeg"})]);
    }).then(function (state) {
      out.upload = runInfo(state, null);
      return canvasJpeg(50 + (W % 89), 35 + (W % 47), (W + 90) % 200);
    }).then(function (clean) {
      out.cleanName = "clean-" + W + ".jpg";
      out.cleanSize = [50 + (W % 89), 35 + (W % 47)];
      var reloads = 0;
      var realReload = window.MFAuthor.reload;
      window.MFAuthor.reload = function () { reloads += 1; };
      return run([new File([clean], out.cleanName, {type: "image/jpeg"})]).then(function (s4) {
        window.MFAuthor.reload = realReload;
        out.clean = runInfo(s4, null);
        out.clean.reloads = reloads;
        out.clean.kept = window.sessionStorage.getItem("mf-upload-done");
        var back = window.MFAuthor.restore();
        out.clean.restored = back ? document.querySelector(".upload-status").textContent : null;
        out.clean.keptAfter = window.sessionStorage.getItem("mf-upload-done");
      });
    }).then(function () {
      stub(function () {
        // the buttons are disabled while a request is in flight: they must look it
        var b = document.querySelector("[data-pick]");
        var cs = getComputedStyle(b);
        out.disabledLook = {disabled: b.disabled, opacity: cs.opacity, cursor: cs.cursor};
        return Promise.reject(new TypeError("offline"));
      });
      return run([new File([tiny], "a.jpg", {type: "image/jpeg"})]).then(function (s2) {
        out.offline = runInfo(s2, calls);
      });
    }).then(function () {
      stub(function () {
        return Promise.resolve(new Response(JSON.stringify({error: "stale"}), {
          status: 403, headers: {"Content-Type": "application/json"}}));
      });
      return run([new File([tiny], "b.jpg", {type: "image/jpeg"}),
                  new File([tiny], "c.jpg", {type: "image/jpeg"})]).then(function (s3) {
        out.forbidden = runInfo(s3, calls);
      });
    }).then(function () {
      window.fetch = realFetch;
    }, function (err) {
      window.fetch = realFetch;
      throw err;
    });
  }

  // Photo folder view (authoring.md §15.1 acceptance 2): the first listed original, fetched
  // from /photo, goes through the same author.js function the upload loop uses; the probe
  // reports the decoded size and the thumb and view copy sizes. With probe_upload=1 it also
  // runs the real upload loop (uploadRuns) and reports each run's counts and status line.
  // With probe_webp=<id> it also decodes that stored WebP original (the fixture's 1 x 1 image).
  function photoChecks(done) {
    var tile = document.querySelector(".pgrid .ptile");
    var section = document.querySelector("section[data-photos]");
    if (!tile || !section || !window.MFAuthor) {
      done(null);
      return;
    }
    // the grid lists the newest photo first, so the fixture's EXIF-6 original (its first
    // upload) is named by probe_orig=<id>
    var named = /[?&]probe_orig=([\w-]+)/.exec(location.search);
    var id = named ? named[1] : tile.getAttribute("data-id");
    var url = "/photo?folder=" + encodeURIComponent(section.getAttribute("data-photos")) +
      "&id=" + encodeURIComponent(id) + "&v=orig";
    var out = {id: id};
    fetch(url).then(function (r) { return r.blob(); }).then(function (blob) {
      out.origBytes = blob.size;
      return window.MFAuthor.makeCopies(blob).then(function (c) {
        out.decoded = [c.width, c.height];
        out.thumb = [c.thumb.width, c.thumb.height, c.thumb.blob.type, c.thumb.blob.size];
        out.view = [c.view.width, c.view.height, c.view.blob.type, c.view.blob.size];
        var webp = /[?&]probe_webp=([\w-]+)/.exec(location.search);
        var seen = webp ? fetch("/photo?folder=" + encodeURIComponent(
          section.getAttribute("data-photos")) + "&id=" + webp[1] + "&v=orig")
          .then(function (r) { return r.blob(); })
          .then(function (b) { return createImageBitmap(b); })
          .then(function (bmp) { out.webp = [bmp.width, bmp.height]; }) : Promise.resolve();
        return seen.then(function () {
          if (location.search.indexOf("probe_upload=1") < 0) {
            return null;
          }
          return uploadRuns(blob, out);
        });
      });
    }).catch(function (err) {
      out.error = String(err);
    }).then(function () {
      done(out);
    });
  }

  function stickyBottom() {
    var bar = document.querySelector(".topbar");
    return bar && getComputedStyle(bar).position === "sticky" ?
      bar.getBoundingClientRect().bottom : 0;
  }

  // Layout facts the panel promises: the Files preview strip fits its card, the Rules unit
  // word sits under its number, and a tapped ring node leaves the detail's heading and first
  // line on the first screen (the page is loaded with the node link's #net-detail fragment).
  function measureLayout(add, W, modal) {
    document.querySelectorAll(".fcard .tiles").forEach(function (strip) {
      var card = strip.closest(".fcard"), tiles = strip.children;
      if (!tiles.length || !shown(strip)) {
        return;
      }
      var box = card.getBoundingClientRect(), cs = getComputedStyle(card);
      var inner = box.right - parseFloat(cs.borderRightWidth) - parseFloat(cs.paddingRight);
      var last = tiles[tiles.length - 1].getBoundingClientRect();
      if (last.right > inner + 0.5) {
        add("strip-overflows", strip, Math.round(last.right * 10) / 10 + " > " +
          Math.round(inner * 10) / 10);
      }
      var left = tiles[0].getBoundingClientRect().left - box.left;
      var right = box.right - last.right;
      if (box.width <= 240 && tiles.length >= 4 && Math.abs(left - right) > 1.5) {
        add("strip-insets-unequal", strip, Math.round(left * 10) / 10 + " vs " +
          Math.round(right * 10) / 10);
      }
    });
    document.querySelectorAll(".mini-count").forEach(function (box) {
      var num = box.querySelector(".num-s"), unit = box.querySelector(".muted");
      if (!num || !unit || !shown(box)) {
        return;
      }
      var a = num.getBoundingClientRect(), b = unit.getBoundingClientRect();
      var across = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      if (b.top < a.bottom - 1 || across < 1) {
        add("unit-detached-from-number", box, "number " + Math.round(a.top) + ".." +
          Math.round(a.bottom) + ", unit " + Math.round(b.top));
      }
    });
    document.querySelectorAll("a.node").forEach(function (node) {
      var href = node.getAttribute("href") || "";
      if (href.indexOf("#net-detail") < 0) {
        add("node-link-without-fragment", node, href);
      }
    });
    var detail = document.getElementById("net-detail");
    if (!detail && location.hash === "#net-detail") {
      add("net-detail-missing", document.body, "the fragment names no element");
    }
    if (detail && !modal && location.hash === "#net-detail") {
      var heading = detail.querySelector("h2"), line = heading && heading.nextElementSibling;
      [heading, line].forEach(function (el) {
        if (!el) {
          return;
        }
        var range = document.createRange();
        range.selectNodeContents(el);
        var r = range.getBoundingClientRect();
        measured.push("net-detail " + el.tagName.toLowerCase() + ": " + Math.round(r.top) + ".." +
          Math.round(r.bottom) + " of " + window.innerHeight + " (scrollY " +
          Math.round(window.scrollY) + ")");
        if (r.top < stickyBottom() - 1 || r.bottom > window.innerHeight) {
          add("net-detail-off-screen", el, Math.round(r.top) + ".." + Math.round(r.bottom) +
            " of " + window.innerHeight +
            " (scrollY " + Math.round(window.scrollY) + ", detail top " +
            Math.round(detail.getBoundingClientRect().top) + ", page " +
            document.documentElement.scrollHeight + ")");
        }
      });
    }
  }

  // An expander opened with its summary's top 40 px above the bottom edge must show its form's top
  // inside the viewport (the toggle handler in panel.js scrolls it into view).
  function expanders(add, startY, done) {
    var boxes = Array.prototype.filter.call(
      document.querySelectorAll("details.newcard, details.newrule"),
      function (d) { return !d.open && shown(d.querySelector("summary")); });
    var i = 0;
    function next() {
      if (i >= boxes.length) {
        window.scrollTo(0, startY);
        done();
        return;
      }
      var box = boxes[i++];
      var sum = box.querySelector("summary");
      var y = window.scrollY + sum.getBoundingClientRect().top + 40 - window.innerHeight;
      window.scrollTo(0, Math.max(0, y));
      var settled = false;
      function measure() {
        if (settled) {
          return;
        }
        settled = true;
        var form = box.querySelector("form"), r = form.getBoundingClientRect();
        var field = form.querySelector("input:not([type=hidden]), select, textarea, button");
        var f = field.getBoundingClientRect();
        measured.push(name(box) + ": form top " + Math.round(r.top) + ", control bottom " +
          Math.round(f.bottom) + " of " + window.innerHeight);
        if (r.top < stickyBottom() - 1 || r.top >= window.innerHeight ||
            f.bottom > window.innerHeight) {
          add("expander-form-off-screen", box, "form top " + Math.round(r.top * 10) / 10 +
            ", first control bottom " + Math.round(f.bottom) + " of " + window.innerHeight);
        }
        box.open = false;
        setTimeout(next, 0);
      }
      box.addEventListener("toggle", function () { setTimeout(measure, 50); }, {once: true});
      box.open = true;
    }
    next();
  }

  // Authoring states run with the real browser clock. All Gemini replies come from
  // the fixture's FakeGemini; no probe ever calls a vendor.
  async function authorChecks() {
    var state = new URLSearchParams(location.search).get("probe_create");
    if (!state) { return; }
    var root = document.querySelector("[data-create]");
    var anchored = ["create-texts", "create-over-limit"];
    var out = {state: state, problems: [], busy: [], defining: []};
    window.MFProbeAuthor = out;
    async function until(predicate, label, timeout) {
      var deadline = performance.now() + (timeout || 10000);
      while (!predicate()) {
        if (performance.now() > deadline) { throw new Error("timed out: " + label); }
        await new Promise(function (ok) { requestAnimationFrame(ok); });
      }
    }
    function see(selector, expected, scope) {
      var el = (scope || document).querySelector(selector);
      if (!el) { out.problems.push("missing " + selector); return; }
      var text = el.value !== undefined && el.tagName === "TEXTAREA" ? el.value : el.textContent;
      if (expected && text.indexOf(expected) < 0) { out.problems.push(selector + " lacks " + expected); }
      var range = document.createRange(); range.selectNodeContents(el);
      var r = el.tagName === "TEXTAREA" ? el.getBoundingClientRect() : range.getBoundingClientRect();
      out.defining.push({selector: selector, text: text, top: Math.round(r.top), bottom: Math.round(r.bottom)});
      // Text inside the sticky bar is measured against the viewport, not below the bar.
      var top = el.closest(".topbar") ? 0 : stickyBottom();
      if (r.top < top - 1 || r.bottom > innerHeight + 1) {
        out.problems.push("defining text off screen: " + selector + " " + Math.round(r.top) + ".." + Math.round(r.bottom));
      }
    }
    // the element's text (or its box, for the textarea) lies whole between the sticky bar and the window's bottom
    function onScreen(label, selector) {
      var el = document.querySelector(selector);
      if (!el) { out.problems.push(label + ": missing " + selector); return; }
      var range = document.createRange(); range.selectNodeContents(el);
      var r = el.tagName === "TEXTAREA" ? el.getBoundingClientRect() : range.getBoundingClientRect();
      var box = el.getBoundingClientRect();
      if (r.top < stickyBottom() - 1 || r.bottom > innerHeight + 1 || box.bottom > innerHeight + 1) {
        out.problems.push(label + ": " + selector + " is at " + Math.round(box.top) + ".." + Math.round(box.bottom) +
                          " in a " + innerHeight + " px window (scrollY " + Math.round(scrollY) + ")");
      }
    }
    function scroll(selector) { var el = document.querySelector(selector); if (el) { el.scrollIntoView({block: "start"}); } }
    function looks(selector) {
      document.querySelectorAll(selector).forEach(function (el) {
        var cs = getComputedStyle(el);
        out.busy.push({text: el.textContent, disabled: el.disabled, opacity: cs.opacity, cursor: cs.cursor,
                       width: el.getBoundingClientRect().width});
      });
    }
    try {
      if (state === "create-topics-loading") {
        await until(function () { return document.querySelector(".ai-status").textContent.indexOf("Gemini") >= 0; }, "topics loading");
        see(".ai-status", "Gemini подбирает темы…");
        see('[data-op="topics"]', "Ещё темы · до $0.02");
        looks('[data-op="topics"], [data-op="expand"]');
      } else if (state === "create-autoretry") {
        // the automatic topics request answers 503; «Повторить» must send a second, real request
        var topicPosts = [], realFetch3 = window.fetch;
        window.fetch = function (url, options) {
          if (String(url).endsWith("/topics")) { topicPosts.push(String(options && options.body)); }
          return realFetch3(url, options);
        };
        await until(function () { return !document.querySelector(".create-error").hidden && document.querySelector(".create-error [data-retry], .create-error button"); }, "503 with a retry button");
        see(".create-error p", "Не удалось получить темы от Gemini");
        var retry = document.querySelector(".create-error button");
        retry.click();
        await until(function () { return document.querySelectorAll(".topic-card").length >= 3 && root.getAttribute("aria-busy") === "false"; }, "cards after retry");
        var count = document.querySelectorAll(".topic-card").length;
        if (topicPosts.length !== 1 || count < 3 || count > 5 || !document.querySelector(".create-error").hidden) {
          out.problems.push("«Повторить» sent " + topicPosts.length + " topics posts (expected 1; the automatic one left before this probe), " + count + " cards, error hidden " + document.querySelector(".create-error").hidden);
        }
        out.autoretry = {posts: topicPosts, cards: count};
        window.fetch = realFetch3;
      } else if (state === "create-expand-loading") {
        document.querySelector('[data-op="expand"]').click();
        await until(function () { return root.getAttribute("aria-busy") === "true"; }, "expand loading");
        // the loading line stands in «Тексты», which is on screen (the click scrolls to it on a narrow page);
        // «Тема» keeps no loading line and the «появятся после» box gives way to it
        see(".texts-heading .text-ai-status", "Gemini пишет тексты…");
        see(".texts-heading h2", "Тексты");
        if (document.querySelector(".ai-status").textContent !== "") { out.problems.push("the loading line is also in «Тема»"); }
        var before = document.querySelector(".text-cards .empty");
        if (before && !before.hidden) { out.problems.push("«Тексты» still says " + before.textContent + " while writing"); }
        if (document.querySelector('[data-op="expand"]').textContent !== "Развернуть · до $0.05") { out.problems.push("expand label"); }
        looks('[data-op="topics"], [data-op="expand"]');
      } else if (state === "create-voice") {
        var audioContext = new AudioContext(), source = audioContext.createOscillator();
        source.frequency.value = 250;
        var dest = audioContext.createMediaStreamDestination(); source.connect(dest); source.start();
        await audioContext.resume();
        navigator.mediaDevices.getUserMedia = async function () { return dest.stream; };
        var audioBlob, voiceCalls = 0, realFetch = window.fetch;
        window.fetch = function (url, options) {
          if (String(url).endsWith("/voice")) { audioBlob = options.body; voiceCalls++; }
          return realFetch(url, options);
        };
        document.querySelector('[data-op="voice"]').click();
        await until(function () { return document.querySelector('[data-op="voice"]').textContent.indexOf("0:01") >= 0; }, "voice timer");
        see('[data-op="voice"]', "Стоп · 0:01");
        // one timer: the button carries it, the status line stays empty
        if (document.querySelector(".voice-status").textContent !== "") { out.problems.push("the voice timer shows twice"); }
        window.MFProbeVoiceFinish = async function () {
          window.MFCreate.stopVoice();
          await until(function () { return audioBlob && root.getAttribute("aria-busy") === "false" && document.querySelector("#topic").value.indexOf("Утренняя пробежка у моря") >= 0; }, "voice transcript");
          var buffer = await audioContext.decodeAudioData(await audioBlob.arrayBuffer());
          var energy = buffer.getChannelData(0).reduce(function (sum, x) { return sum + x * x; }, 0);
          source.stop(); await audioContext.close(); window.fetch = realFetch;
          return {calls: voiceCalls, energy: energy, transcript: document.querySelector("#topic").value};
        };
      } else if (state === "create-behaviour") {
        // Browser behaviour of acceptance items 6, 7 and 9, driven in the page: every Gemini reply
        // comes from FakeGemini; the clock is faked only where the check says so.
        var Cb = JSON.parse(root.dataset.create), Tb = Cb.strings;
        var B = out.behaviour = {}, posts = [], realFetch2 = window.fetch;
        window.fetch = function (url, options) {
          posts.push({url: String(url), body: options && options.body, type: options && options.headers && options.headers["Content-Type"]});
          return realFetch2(url, options);
        };
        var topicBox = document.querySelector("#topic"), expandBtn = document.querySelector('[data-op="expand"]');
        var voiceBtn = document.querySelector('[data-op="voice"]'), voiceLine = document.querySelector(".voice-status");
        var sleep = function (ms) { return new Promise(function (ok) { setTimeout(ok, ms); }); };
        function expect(ok, message) { if (!ok) { out.problems.push(message); } }
        async function serverPage() {
          return new DOMParser().parseFromString(await (await realFetch2(location.pathname)).text(), "text/html");
        }
        // typing arms exactly one 800 ms timer; the autosave runs when that timer fires, not before
        async function typeAndSave(el, value, statusEl) {
          var realSet = window.setTimeout, armed = [];
          statusEl.textContent = "";
          window.setTimeout = function (fn, delay) { armed.push({fn: fn, delay: delay}); return 9000000 + armed.length; };
          try { el.value = value; el.dispatchEvent(new Event("input", {bubbles: true})); }
          finally { window.setTimeout = realSet; }
          var delays = armed.map(function (a) { return a.delay; }).join(",");
          expect(delays === "800", "autosave timer delays " + delays + ", expected 800");
          expect(statusEl.textContent !== Tb.saved, "saved shown before the timer fired");
          var before = posts.length;
          armed.forEach(function (a) { a.fn(); });
          await until(function () { return statusEl.textContent === Tb.saved; }, "saved status");
          expect(posts.length === before + 1, "autosave sent " + (posts.length - before) + " requests");
        }
        // 1. tapping a card saves "<title> — <angle>"
        var cards = Array.from(document.querySelectorAll(".topic-card"));
        var tapped = cards[0], tappedText = tapped.dataset.topic;
        expect(cards.length === 5 && cards[1].getAttribute("aria-pressed") === "true", "start state: card 2 chosen");
        document.querySelector(".topic-save").textContent = "";
        tapped.click();
        expect(tapped.getAttribute("aria-pressed") === "true" && tapped.querySelector(".chosen").textContent === Tb.chosen &&
               cards[1].getAttribute("aria-pressed") === "false" && cards[1].querySelector(".chosen").textContent === "",
               "tapped card is not the only chosen one");
        expect(topicBox.value === tappedText && /^.+ — .+$/.test(tappedText), "tapped card did not fill the topic box");
        see('.topic-card[aria-pressed="true"] .chosen', "выбрано");
        // after the tap the box and «Развернуть» are on the screen, whatever the width (the tap scrolls when it must)
        await new Promise(function (ok) { requestAnimationFrame(function () { requestAnimationFrame(ok); }); });
        onScreen("after a card tap", "#topic"); onScreen("after a card tap", '[data-op="expand"]');
        window.scrollTo(0, 0);   // the later steps read the first screen
        // the tap saves by itself: no input event, no flush from here
        await until(function () { return document.querySelector(".topic-save").textContent === Tb.saved; }, "tapped topic saved");
        var page = await serverPage();
        expect(page.querySelector("#topic").value === tappedText, "draft.json lacks the tapped topic");
        expect(page.querySelector('.topic-card[aria-pressed="true"]') && page.querySelector('.topic-card[aria-pressed="true"]').dataset.topic === tappedText,
               "reloaded page does not mark the tapped card");
        // 2. typing into the topic box autosaves after 800 ms and unmarks the cards
        await typeAndSave(topicBox, "Своя тема про утро", document.querySelector(".topic-save"));
        expect(!document.querySelector('.topic-card[aria-pressed="true"]'), "typed topic left a card chosen");
        page = await serverPage();
        expect(page.querySelector("#topic").value === "Своя тема про утро", "typed topic not in draft.json");
        // 3. an edited text card autosaves after 800 ms and switches the button to "Развернуть заново"
        var card = document.querySelector('.create-text[data-network="linkedin"]'), editor = card.querySelector("textarea");
        await typeAndSave(editor, "Edited by hand. One line.", card.querySelector(".save-status"));
        page = await serverPage();
        expect(page.querySelector('.create-text[data-network="linkedin"] textarea').value === "Edited by hand. One line.", "edited text not in draft.json");
        expect(expandBtn.textContent.indexOf(Tb.expand_again) === 0, "expand button lacks the redo label after an edit");
        // 4. an empty box disables «Развернуть» and shows the hint; typing enables it again
        var hint = document.querySelector(".topic-hint");
        topicBox.value = ""; topicBox.dispatchEvent(new Event("input", {bubbles: true}));
        expect(expandBtn.disabled && !hint.hidden && hint.textContent === Tb.empty_topic, "empty box: expand enabled or hint hidden");
        topicBox.value = "Тема для голоса"; topicBox.dispatchEvent(new Event("input", {bubbles: true}));
        expect(!expandBtn.disabled && hint.hidden, "typed box: expand disabled or hint shown");
        await window.MFCreate.flush();
        // 5. microphone refusals each give their own reason, send nothing and leave the button usable
        async function refuses(label, expected, setup, undo) {
          voiceLine.textContent = ""; var before = posts.length;
          setup();
          try {
            voiceBtn.click();
            await until(function () { return voiceLine.textContent !== "" && root.getAttribute("aria-busy") === "false"; }, label);
          } finally { undo(); }
          expect(voiceLine.textContent === expected, label + ": " + voiceLine.textContent);
          expect(posts.length === before && !voiceBtn.disabled && voiceBtn.getAttribute("aria-pressed") === "false", label + ": sent a request or left the button stuck");
          return voiceLine.textContent;
        }
        var denyWith = function (name) {
          return function () { navigator.mediaDevices.getUserMedia = async function () { throw new DOMException("stub", name); }; };
        };
        var undoMedia = function () { delete navigator.mediaDevices.getUserMedia; };
        var reasons = [
          await refuses("NotAllowedError", Tb.voice_denied, denyWith("NotAllowedError"), undoMedia),
          await refuses("NotFoundError", Tb.voice_missing, denyWith("NotFoundError"), undoMedia),
          await refuses("no mediaDevices", Tb.voice_context, function () {
            Object.defineProperty(navigator, "mediaDevices", {value: undefined, configurable: true});
          }, function () { delete navigator.mediaDevices; }),
          await refuses("unsupported type", Tb.voice_unsupported, function () {
            window.MFRealTypeSupported = MediaRecorder.isTypeSupported;
            MediaRecorder.isTypeSupported = function () { return false; };
          }, function () { MediaRecorder.isTypeSupported = window.MFRealTypeSupported; })
        ];
        await refuses("other error", Tb.voice_unsupported, denyWith("NotReadableError"), undoMedia);
        expect(new Set(reasons).size === 4 && /запрещ/.test(reasons[0]) && /не найден/.test(reasons[1]) &&
               /localhost/.test(reasons[2]) && /не записывает/.test(reasons[3]), "microphone reasons are not four distinct texts: " + reasons.join(" | "));
        B.reasons = reasons;
        // 6. a recording stops by itself at 2:00 (fake clock), the first transcription answers 503,
        //    and «Повторить расшифровку» sends the same bytes
        var ac = new AudioContext(), osc = ac.createOscillator();
        osc.frequency.value = 250;
        var sink = ac.createMediaStreamDestination(); osc.connect(sink); osc.start(); await ac.resume();
        navigator.mediaDevices.getUserMedia = async function () { return sink.stream; };
        var heard = [], watcher = new MutationObserver(function (records) {
          records.forEach(function (rec) { rec.addedNodes.forEach(function (n) { heard.push(n.textContent); }); });
        });
        watcher.observe(voiceBtn, {childList: true, characterData: true, subtree: true});
        var realNow = Date.now.bind(Date), voiceCalls2 = function () { return posts.filter(function (x) { return x.url.endsWith("/voice"); }); };
        var t0 = realNow();
        voiceBtn.click();
        await until(function () { return voiceBtn.textContent.indexOf("0:01") >= 0; }, "recording running");
        // the fake clock reads t0 + the chosen elapsed time and runs on from there
        function clockAt(ms) { var set = realNow(); Date.now = function () { return t0 + ms + (realNow() - set); }; }
        clockAt(119000);
        await until(function () { return voiceBtn.textContent.indexOf("1:59") >= 0; }, "fake 1:59");
        await sleep(500);
        expect(voiceBtn.getAttribute("aria-pressed") === "true" && voiceCalls2().length === 0, "recording stopped before 2:00");
        clockAt(120100);
        await until(function () { return heard.some(function (t) { return t.indexOf("2:00") >= 0; }); }, "fake 2:00");
        Date.now = realNow;
        await until(function () { return voiceLine.querySelector("button"); }, "retry button after 503");
        var again = voiceLine.querySelector("button");
        expect(again.textContent === Tb.voice_retry && voiceCalls2().length === 1 && voiceBtn.getAttribute("aria-pressed") === "false",
               "auto-stop at 2:00 did not send exactly one recording");
        expect(/расшифровку голоса/.test(document.querySelector(".create-error").textContent) && !document.querySelector(".create-error").hidden, "503 not shown");
        see(".voice-status button", "Повторить расшифровку");
        again.click();
        await until(function () { return voiceCalls2().length === 2; }, "retry sent");
        await until(function () { return root.getAttribute("aria-busy") === "false" && topicBox.value.indexOf("Утренняя пробежка у моря") >= 0; }, "retried transcript");
        var sent = voiceCalls2();
        var bytes = await Promise.all(sent.map(function (x) { return x.body.arrayBuffer(); }));
        expect(sent[0].body.size > 0 && bytes[0].byteLength === bytes[1].byteLength &&
               new Uint8Array(bytes[0]).every(function (b, i) { return b === new Uint8Array(bytes[1])[i]; }) &&
               sent[0].type === sent[1].type, "retry sent other bytes than the first recording");
        expect(voiceLine.textContent === Tb.saved && document.querySelector(".create-error").hidden, "retry left an error or no saved mark");
        B.voiceBytes = bytes[0].byteLength;
        watcher.disconnect(); osc.stop(); await ac.close(); window.fetch = realFetch2;
      } else if (state === "create-drop") {
        var calls = [], actualFetch = window.fetch, navigation;
        window.fetch = function (url, options) { calls.push(String(url)); return actualFetch(url, options); };
        window.MFCreate.navigate(function (url) { navigation = url; });
        var w = innerWidth, blob = await canvasJpeg(40 + w % 97, 30 + w % 53, w % 255);
        var file = new File([blob], "drop-" + w + ".jpg", {type: "image/jpeg"});
        function counted() { return {uploads: calls.filter(function (u) { return u.indexOf("/files/photos?") === 0; }).length,
          new: calls.filter(function (u) { return u === "/create/new"; }).length, url: navigation}; }
        await window.MFCreate.drop([file, file]);
        out.many = {calls: calls.length, message: document.querySelector(".create-status").textContent.indexOf("Перетащите одно фото") >= 0};
        calls = []; await window.MFCreate.drop([file]); out.drop = counted();
        calls = []; await window.MFCreate.drop([file]); out.duplicate = counted();
        calls = []; document.querySelector("[data-recent]").click();
        await until(function () { return root.getAttribute("aria-busy") === "false"; }, "recent draft");
        out.recent = counted();
        var C = JSON.parse(root.dataset.create);
        var response = await actualFetch("/create/new", {method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": C.csrf + "mutated"}, body: "{}"});
        out.hostile = {status: response.status}; window.fetch = actualFetch;
      } else if (state === "create-topics") {
        document.querySelectorAll(".topic-card").forEach(function (el, i) { see("strong", null, el); });
        see('.topic-card[aria-pressed="true"] .chosen', "выбрано");
        if (document.querySelector('[data-op="expand"]').textContent !== "Развернуть · до $0.05") { out.problems.push("expand label"); }
      } else if (state === "create-own-topic") {
        see("#topic", "Прогулянка і робочі звички");
        see('[data-op="topics"]', "Предложить темы · до $0.02");
        see('[data-op="expand"]', "Развернуть · до $0.05");
        if (document.querySelector('[data-op="expand"]').disabled) { out.problems.push("own topic expand disabled"); }
      } else if (state === "create-texts" || state === "create-over-limit") {
        scroll("#texts");
        if (state === "create-over-limit") { see(".text-errors", "длиннее лимита: 312 / 280 — сократите");
          if (document.querySelectorAll(".create-text")[0].textContent.split("312").length !== 2) { out.problems.push("the X count shows more than once"); } }
        document.querySelectorAll(".create-text").forEach(function (card) {
          card.scrollIntoView(); see("h3", null, card); see(".text-check", null, card);
          var el = card.querySelector("textarea");
          if (el.scrollHeight > el.clientHeight + 2) { out.problems.push("text editor clips " + card.dataset.network); }
        });
        scroll("#texts");
        // the sub row (draft header and the month figure the expand reply just updated) must
        // be fully visible or fully under the sticky bar, never cut by its bottom edge
        document.querySelectorAll(".sub-left, .sub-right").forEach(function (el) {
          var range = document.createRange(); range.selectNodeContents(el);
          var r = range.getBoundingClientRect(), bar = stickyBottom();
          out.defining.push({selector: ".sub " + el.className, text: el.textContent, top: Math.round(r.top), bottom: Math.round(r.bottom)});
          if (r.top < bar - 1 && r.bottom > bar + 1) {
            out.problems.push("sub row cut by the sticky bar: " + el.className + " " + Math.round(r.top) + ".." + Math.round(r.bottom) + " bar " + bar);
          }
        });
      } else if (state === "create-empty" || state === "create-start" || state === "create-nokey-start") {
        see(".create-drop strong", "Бросьте фото сюда"); see(".create-drop .btn", "Выбрать фото");
        if (state === "create-empty") { see(".profile-line", "Профиль автора не заполнен"); see("#ai-month", "ИИ · ноябрь $0.00 из $10.00"); }
        if (state === "create-start") {
          see(".recent-photos", null);
          var draftHeading = document.querySelector(".draft-list").previousElementSibling;
          var dr = document.createRange(); dr.selectNodeContents(draftHeading);
          var db = dr.getBoundingClientRect();
          if (draftHeading.textContent !== "Черновики · 5" || db.bottom > innerHeight) { out.problems.push("draft heading off screen"); }
        }
        if (state === "create-nokey-start" && document.querySelector("#create-file").disabled) { out.problems.push("no key disabled upload"); }
      } else if (state === "create-budget") {
        see(".create-notice", "Бюджет ИИ на ноябрь исчерпан"); see("#ai-month", "$9.99 из $10.00 · лимит");
        if (document.body.textContent.split("$9.99 из $10.00").length !== 2) { out.problems.push("the month amount shows more than once"); }
      } else if (state === "create-error") {
        see(".create-error", "Не удалось получить темы от Gemini"); see("[data-retry]", "Повторить · до $0.02");
        if (document.querySelector('[data-op="topics"]').offsetParent !== null) { out.problems.push("two buttons for one retry"); }
        if (/HTTP/.test(document.querySelector(".create-error").textContent)) { out.problems.push("a status code in the error"); }
      } else if (state === "create-nokey" || state === "create-nokey-start") {
        see(".create-notice", "нет GEMINI_API_KEY в .env — темы, тексты и голос недоступны");
      } else if (state === "create-profile") {
        see(".create-profile h2", "Профиль автора"); see(".create-profile [role=status]", "Профиль сохранён");
        document.querySelectorAll(".profile-field label").forEach(function (el, i) {
          // one column below 600 px: the first fields are on the first screen, the rest are reached by scrolling
          if (innerWidth >= 600 || i < 2) { see("label", null, el.parentElement); }
        });
      } else if (state === "files-mediateka") {
        see('.tab[aria-current="page"]', "Медиатека");
        var mine = Array.from(document.querySelectorAll(".fcard")).find(function (card) {
          return card.querySelector('a[href*="folder=my-photos"]') || (card.href || "").indexOf("folder=my-photos") >= 0;
        });
        if (!mine) { out.problems.push("missing Мои фото card"); }
        else {
          if (!/12\s*фото/.test(mine.textContent.replace(/\u00a0/g, " "))) { out.problems.push("Мои фото card lacks 12 фото"); }
          mine.setAttribute("data-probe-mine", ""); see("[data-probe-mine]", "Мои фото");
        }
      } else if (state === "files-mine") {
        see("#photos-h", "Фото");
        // the count stands once on this surface: in the sub row, not in the heading
        if (/12/.test(document.querySelector("#photos-h").textContent)) { out.problems.push("the photo count is repeated in the heading"); }
        if (!document.querySelector(".pgrid").textContent.includes("черновик")) { out.problems.push("missing draft chip"); }
      }
      if (state === "files-mine") {
        var subLeft = document.querySelector(".sub-left").textContent;
        if (!/^12\s*фото$/.test(subLeft.replace(/\u00a0/g, " ").trim())) { out.problems.push("sub row does not count the photos: " + subLeft); }
      }
      if (root && root.classList.contains("create-draft") && anchored.indexOf(state) < 0) {
        // one layout for every draft state (design §8.3): card → box → «Развернуть», texts on the right
        var box = document.querySelector("#topic").getBoundingClientRect();
        var go = document.querySelector('[data-op="expand"]'), goBox = go.getBoundingClientRect();
        if (!go.classList.contains("green")) { out.problems.push("«Развернуть» is not the primary button"); }
        if (goBox.top < box.bottom - 1 || Math.abs(goBox.left - box.left) > 1) { out.problems.push("«Развернуть» is not directly under the topic box"); }
        var head = document.querySelector(".topic-heading").getBoundingClientRect(), first = document.querySelector(".topic-cards").getBoundingClientRect();
        if (first.top - head.bottom > 16) { out.problems.push("a blank band under the «Тема» heading: " + Math.round(first.top - head.bottom) + " px"); }
        if (innerWidth >= 1000) {
          var photo = document.querySelector(".create-photo").getBoundingClientRect();
          var tr = document.createRange(); tr.selectNodeContents(document.querySelector(".texts-heading h2"));
          var tb = tr.getBoundingClientRect(), col = document.querySelector(".create-texts").getBoundingClientRect();
          if (tb.left < photo.right || tb.bottom > innerHeight) { out.problems.push("«Тексты» is not in the right column on the first screen"); }
          if (Math.abs(col.right - document.querySelector(".create-columns").getBoundingClientRect().right) > 1) { out.problems.push("the texts column is not the full right column"); }
          out.defining.push({selector: ".texts-heading h2", text: "Тексты", top: Math.round(tb.top), bottom: Math.round(tb.bottom)});
          // the left column fits the topic box and «Развернуть» on the screen, with no scroll
          if (state === "create-topics") { onScreen("first screen", '[data-op="expand"]'); onScreen("first screen", "#topic"); }
        }
      }
      // §16.2: states that are not anchor states are judged on the first screen, unscrolled
      // (the expand click scrolls a one-column page to «Тексты», where its loading line is)
      if (anchored.indexOf(state) < 0 && scrollY !== 0 && !(state === "create-expand-loading" && innerWidth < 1000)) {
        out.problems.push("first screen measured after a scroll: scrollY " + Math.round(scrollY));
      }
    } catch (err) { out.problems.push(err.message); }
  }

  // after the load event, so the browser has already scrolled to a #fragment
  function later() {
    authorChecks().then(function () { setTimeout(run, 100); }, function (err) {
      window.MFProbeAuthor = {problems: [err.message]}; setTimeout(run, 100);
    });
  }

  if (document.readyState === "complete") {
    later();
  } else {
    window.addEventListener("load", later);
  }
})();
