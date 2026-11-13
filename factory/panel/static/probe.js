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
                                          whole: whole.map(clampText), photos: photos, author: window.MFProbeAuthor,
                                          send: window.MFProbeSend});
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
      } else if (state === "create-expand-texts") {
        // The whole main flow on the draft's own page, real clicks, FakeGemini replies: tap the LAST card,
        // then «Развернуть»; the box and the button stay clear of the window edge after «сохранено»
        // appears, and when the texts arrive «Тексты» and the first card's editor are on the screen.
        var frame = function () { return new Promise(function (ok) { requestAnimationFrame(function () { requestAnimationFrame(ok); }); }); };
        var lastCard = Array.from(document.querySelectorAll(".topic-card")).pop();
        document.querySelector(".topic-save").textContent = "";
        lastCard.click();
        await frame();
        onScreen("after the last card was tapped", "#topic"); onScreen("after the last card was tapped", '[data-op="expand"]');
        await until(function () { return document.querySelector(".topic-save").textContent === "сохранено"; }, "tapped topic saved");
        await frame();
        onScreen("after «сохранено» appeared", '[data-op="expand"]');
        var goEdge = document.querySelector('[data-op="expand"]').getBoundingClientRect().bottom;
        if (goEdge > innerHeight - 8) { out.problems.push("«Развернуть» sits against the window edge after «сохранено»: bottom " + goEdge.toFixed(1) + " of " + innerHeight); }
        if (document.querySelectorAll(".create-text").length) { out.problems.push("the fixture draft already has texts"); }
        document.querySelector('[data-op="expand"]').click();
        await until(function () { return document.querySelectorAll(".create-text").length === 4 && root.getAttribute("aria-busy") === "false"; }, "four texts");
        await frame();
        onScreen("after the texts arrived", ".texts-heading h2");
        onScreen("after the texts arrived", ".create-text textarea");
        onScreen("after the texts arrived", ".create-text h3");
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
          // the whole «пожелание…» hint fits its field: measured with the field's own font, since a
          // placeholder is cut mid-word without an ellipsis
          var wish = card.querySelector(".wish"), wishStyle = getComputedStyle(wish), wishCanvas = document.createElement("canvas").getContext("2d");
          wishCanvas.font = wishStyle.font;
          var need = wishCanvas.measureText(wish.placeholder).width;
          var room = wish.clientWidth - parseFloat(wishStyle.paddingLeft) - parseFloat(wishStyle.paddingRight);
          out.defining.push({selector: ".wish placeholder " + card.dataset.network, text: wish.placeholder, need: Math.round(need), room: Math.round(room)});
          if (need > room) { out.problems.push("the hint «" + wish.placeholder + "» is cut in the " + card.dataset.network + " field: needs " + Math.round(need) + " px, has " + Math.round(room)); }
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
        // the one green button is the next step: «Проверить и отправить» once every network has a text
        var next = document.querySelector(".send-go-row:not([hidden]) .send-go");
        if (go.classList.contains("green") === !!next) {
          out.problems.push(next ? "«Развернуть» stays primary next to «Проверить и отправить»" : "«Развернуть» is not the primary button");
        }
        if (next && !next.classList.contains("green")) { out.problems.push("«Проверить и отправить» is not the primary button"); }
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
      if (anchored.indexOf(state) < 0 && scrollY !== 0 && !((state === "create-expand-loading" || state === "create-expand-texts") && innerWidth < 1000)) {
        out.problems.push("first screen measured after a scroll: scrollY " + Math.round(scrollY));
      }
    } catch (err) { out.problems.push(err.message); }
  }

  // ------------------------------------------------------------ slice D′ (authoring.md §17.6)
  // Installed while the deferred scripts run, before send.js's first crop post: the page's
  // reload is counted instead of done, and in `review-crops` the first /image POST waits
  // until the probe has read the crop line.
  var sendState = new URLSearchParams(location.search).get("probe_send");
  var sendHold = {held: false};
  if (sendState && window.MFSend) {
    window.MFSend.reloads = 0;
    window.MFSend.reload = function () { window.MFSend.reloads += 1; };
    if (sendState === "review-focus") {
      // the focus POST waits for the probe, which meanwhile tries every competing control
      var focusFetch = window.fetch, focusGate = new Promise(function (ok) { sendHold.release = ok; });
      sendHold.seen = [];
      window.fetch = function (url, options) {
        sendHold.seen.push(String(url).split("?")[0]);
        if (!sendHold.held && String(url).indexOf("/focus") >= 0) {
          sendHold.held = true;
          return focusGate.then(function () { return focusFetch(url, options); });
        }
        return focusFetch(url, options);
      };
    }
    if (sendState === "review-crops") {
      var realFetch = window.fetch, gate = new Promise(function (ok) { sendHold.release = ok; });
      window.fetch = function (url, options) {
        if (!sendHold.held && String(url).indexOf("/image?") >= 0) {
          sendHold.held = true;
          return gate.then(function () { return realFetch(url, options); });
        }
        return realFetch(url, options);
      };
    }
  }

  // ------------------------------------------------------------ slice C (authoring.md §18.6)
  // Every fetch of a C state is listed with its answer; the page's own navigation after a
  // highlight (MFSend.go) is recorded instead of done. A state that needs the page reloaded
  // sets MFProbeNext: the visual check opens that URL in the same tab (sessionStorage keeps
  // what the next stage compares), and only the last stage writes the probe's JSON.
  var cState = sendState && /^(review-(styles|based|template|ratio|highlight|base)|create-error-402)/.test(sendState);
  var cFetch = [];
  if (cState) {
    var innerFetch = window.fetch;
    window.fetch = function (url, options) {
      var item = {url: String(url), method: (options && options.method) || "GET", status: null};
      cFetch.push(item);
      return innerFetch(url, options).then(function (r) { item.status = r.status; return r; });
    };
    if (window.MFSend) {
      window.MFSend.went = [];
      window.MFSend.go = function (url) { window.MFSend.went.push(url); };
    }
  }

  async function sendChecks() {
    if (!sendState) { return; }
    var params = new URLSearchParams(location.search);
    var out = {state: sendState, problems: [], defining: [], busy: []};
    window.MFProbeSend = out;
    var submits = 0;
    // every form submission is counted and stopped: no state in this probe posts a form
    document.addEventListener("submit", function (e) {
      if (!e.defaultPrevented) { submits += 1; e.preventDefault(); }
    });
    window.MFProbeSubmits = function () { return submits; };
    function sleep(ms) { return new Promise(function (ok) { setTimeout(ok, ms); }); }
    async function until(predicate, label, timeout) {
      var deadline = performance.now() + (timeout || 10000);
      while (!predicate()) {
        if (performance.now() > deadline) { throw new Error("timed out: " + label); }
        await sleep(50);
      }
    }
    function words(el) { return el.textContent.replace(/[\s\u00a0]+/g, " ").trim(); }
    // the element holding `expected` is whole between the sticky bar (or the top, in a dialog) and the bottom
    function see(selector, expected, whenScrolled) {
      var el = Array.prototype.find.call(document.querySelectorAll(selector), function (e) {
        return shown(e) && (!expected || words(e).indexOf(expected) >= 0);
      });
      if (!el) { out.problems.push("missing «" + (expected || selector) + "»"); return null; }
      if (whenScrolled) { el.scrollIntoView({block: "nearest"}); }
      var range = document.createRange(); range.selectNodeContents(el);
      var r = range.getBoundingClientRect();
      out.defining.push({selector: selector, text: expected || words(el).slice(0, 80),
                         top: Math.round(r.top), bottom: Math.round(r.bottom)});
      var top = el.closest("dialog") ? 0 : stickyBottom();
      if (r.top < top - 1 || r.bottom > innerHeight + 1 || r.left < -1 || r.right > innerWidth + 1) {
        out.problems.push("defining text off screen: «" + (expected || selector) + "» at " +
                          Math.round(r.top) + ".." + Math.round(r.bottom) + " in " + innerHeight);
      }
      return el;
    }
    function looks(selector) {
      document.querySelectorAll(selector).forEach(function (el) {
        var cs = getComputedStyle(el);
        out.busy.push({text: words(el), disabled: el.disabled, opacity: cs.opacity, cursor: cs.cursor,
                       width: Math.round(el.getBoundingClientRect().width)});
      });
    }
    function modal(id) {
      var d = document.getElementById(id);
      return !!(d && d.open && d.matches(":modal"));
    }
    async function dialogCheck(opener, id, texts) {
      var button = document.querySelector(opener);
      if (!button) { out.problems.push("missing " + opener); return; }
      var behind = document.querySelector('[form="send-queue"]') || document.querySelector(".send-rows a");
      button.click();
      await until(function () { return modal(id); }, "dialog " + id);
      var dialog = document.getElementById(id);
      // the second click of a double click on the opener lands on «Да, …»: nothing is posted
      dialog.querySelector("[data-confirm]").dispatchEvent(
        new MouseEvent("click", {bubbles: true, cancelable: true, detail: 2}));
      await sleep(50);
      if (!modal(id) || submits) { out.problems.push("a double click on the opener confirmed " + id); }
      texts.forEach(function (t) { see("#" + id + " h2, #" + id + " p, #" + id + " button", t); });
      out.focus = document.activeElement ? words(document.activeElement) : "";
      if (!dialog.contains(document.activeElement)) { out.problems.push("focus is outside the dialog"); }
      var box = dialog.getBoundingClientRect();
      if (box.top < 0 || box.left < 0 || box.bottom > innerHeight || box.right > innerWidth) {
        out.problems.push("the dialog leaves the viewport: " + Math.round(box.left) + "," + Math.round(box.top) +
                          ".." + Math.round(box.right) + "," + Math.round(box.bottom));
      }
      if (behind) {   // a click on a control behind the dialog reaches nothing
        var b = behind.getBoundingClientRect();
        var hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
        out.behind = hit ? hit.tagName.toLowerCase() + (hit.id ? "#" + hit.id : "") : "";
        if (hit && behind.contains(hit)) { out.problems.push("a click behind the dialog reaches " + out.behind); }
        if (hit) { hit.dispatchEvent(new MouseEvent("click", {bubbles: true, cancelable: true})); }
        await sleep(50);
        if (submits) { out.problems.push("a click behind the dialog submitted a form"); }
      }
      dialog.querySelector("[data-close]").click();
      if (dialog.open) { out.problems.push("«Отмена» left the dialog open"); }
      button.click();   // open again: Tab and Escape are pressed over DevTools after this probe
      await until(function () { return modal(id); }, "dialog reopened");
      out.dialog = id;
    }
    async function sha(path) {
      var r = await fetch(path, {credentials: "same-origin", cache: "no-store"});
      var d = await crypto.subtle.digest("SHA-256", await r.arrayBuffer());
      return Array.from(new Uint8Array(d)).map(function (b) { return b.toString(16).padStart(2, "0"); }).join("");
    }
    async function sizesOf(pid) {   // an original through the same author.js functions, nothing posted
      var blob = await (await fetch("/photo?folder=my-photos&id=" + pid + "&v=orig")).blob();
      var bitmap = await createImageBitmap(blob, {imageOrientation: "from-image"});
      var result = {decoded: [bitmap.width, bitmap.height]};
      for (var n of ["facebook", "instagram", "linkedin", "x"]) {
        var size = window.MFAuthor.cropSize(n, bitmap.width, bitmap.height);
        var crop = await window.MFAuthor.makeCrop(bitmap, {ratio: {instagram: [4, 5], x: [16, 9]}[n] || null,
          width: size[0], height: size[1], maxBytes: 5000000}, [0.5, 0.5]);
        var back = await createImageBitmap(crop.blob);
        result[n] = [back.width, back.height];
        back.close();
      }
      bitmap.close();
      return result;
    }
    var did = (location.pathname.match(/^\/create\/([^/]+)/) || [])[1];
    try {
      if (sendState === "send-draft") {
        see(".send-go", "Проверить и отправить →");
        var y = scrollY;
        see(".draft-links", "Удалить черновик", true);
        scrollTo(0, y);
      } else if (sendState === "review") {
        ["Проверка перед отправкой", "Проблем нет · 4 сети", "Опубликовать сейчас", "В очередь", "Папка",
         "Публиковать из «Мои фото» по правилу: пн, ср, пт в 16:00"].forEach(function (t) {
          see(".send-action h2, .send-action p, .send-action button, .send-action label", t);
        });
      } else if (sendState === "review-rule") {
        see(".send-rule", "Правило «city-main»: пн, ср, пт в 10:00 · перед этим постом в очереди");
        see(".send-rule", "ближайшая публикация из папки: пт, 13 нояб., 10:00");
        if (document.querySelector('[name="rule"]')) { out.problems.push("a rule is offered next to an existing one"); }
      } else if (sendState === "review-problems") {
        see(".send-problems");   // the whole block
        ["Отправить нельзя — исправьте:", "X: длиннее лимита: 312 / 280 — сократите",
         "Facebook: нет FB_PAGE_KOTLETA_TOKEN в .env", "LinkedIn: токен истёк"].forEach(function (t) {
          see(".send-problems p, .send-problems li", t);
        });
        looks('[data-open="dlg-publish"], [form="send-queue"]');
      } else if (sendState === "review-crops") {
        await until(function () { return sendHold.held; }, "the first crop post", 60000);
        see(".send-crops", "Готовлю картинки: Facebook, Instagram, LinkedIn, X…");
        if (document.querySelector(".send-ok")) { out.problems.push("«Проблем нет» shows while the crops are being made"); }
        looks('[data-open="dlg-publish"], [form="send-queue"]');
        sendHold.release();
        await until(function () { return window.MFSend.reloads >= 1; }, "four crops posted", 60000);
        out.crops = window.MFSend.results;
        out.posts = window.MFSend.posts;
        out.reloads = window.MFSend.reloads;
        out.exif = await sizesOf(params.get("probe_exif"));
        out.small = await sizesOf(params.get("probe_small"));
      } else if (sendState === "review-focus") {
        var base = "/create/" + did + "/file?name=";
        var before = {instagram: await sha(base + "instagram"), x: await sha(base + "x")};
        var img = document.querySelector(".send-photo img");
        await until(function () { return img.complete && img.naturalWidth; }, "source photo");
        var r = img.getBoundingClientRect(), k = Math.min(r.width / img.naturalWidth, r.height / img.naturalHeight);
        var w = img.naturalWidth * k, h = img.naturalHeight * k;
        var tapAt = function () {
          document.querySelector("[data-focus]").dispatchEvent(new MouseEvent("click", {bubbles: true,
            clientX: r.left + (r.width - w) / 2 + 0.5 * w, clientY: r.top + (r.height - h) / 2 + 0.2 * h}));
        };
        var focusWidths = Array.prototype.map.call(document.querySelectorAll("#photo [data-c]"), function (el) {
          return Math.round(el.getBoundingClientRect().width);
        });
        tapAt();
        await until(function () { return sendHold.held && window.MFSend.busy(); }, "focus POST held");
        // while /focus is in flight every C control is blocked and keeps its width; a click on
        // a style, the base, the photo again, or a key on the photo starts nothing
        looks("#photo [data-c]");
        out.busy.forEach(function (l, i) {
          if (Math.abs(l.width - focusWidths[i]) > 1) { out.problems.push("a blocked control changed its width: " + l.text); }
        });
        if (!document.querySelector("#photo [data-style]")) { out.problems.push("no style button to block"); }
        document.querySelectorAll("#photo [data-style], #photo [data-base]").forEach(function (el) { el.click(); });
        tapAt();
        document.querySelector("[data-focus]").dispatchEvent(new KeyboardEvent("keydown", {key: "Enter", bubbles: true}));
        window.MFSend.tap(0.1, 0.1);
        await sleep(300);
        var competing = sendHold.seen.filter(function (u) { return /\/(highlight|settings|image)$/.test(u) || u.indexOf("/focus") >= 0; });
        out.competing = competing;
        if (competing.length !== 1 || window.MFSend.reloads !== 0) {
          out.problems.push("requests while /focus is in flight: " + JSON.stringify(competing) + ", reloads " + window.MFSend.reloads);
        }
        sendHold.release();
        await until(function () { return window.MFSend.reloads >= 1; }, "focus stored");
        window.MFSend.idle();
        if (document.querySelector("[data-focus]").disabled || document.querySelector("#photo [data-style]:disabled")
            && !document.querySelector("#photo [data-style][title]")) {
          out.problems.push("the controls did not come back after the focus POST");
        }
        var stored = window.MFSend.focus || [];
        // a click lands on whole pixels: the stored point is (0.5, 0.2) within a pixel of the box
        if (Math.abs(stored[0] - 0.5) > 0.01 || Math.abs(stored[1] - 0.2) > 0.01) {
          out.problems.push("the tap stored focus " + JSON.stringify(stored) + ", expected about [0.5, 0.2]");
        }
        // the reload (counted, not done) would make the dropped crops: the same call, with the stored point
        await window.MFSend.prepare(["instagram", "x"], stored);
        var line = document.querySelector(".send-crops");
        await until(function () { return window.MFSend.reloads >= 2 || line.getAttribute("role") === "alert"; },
                    "crops made again", 50000);
        if (window.MFSend.reloads < 2) { out.problems.push("crops after the tap: " + line.textContent); }
        var after = {instagram: await sha(base + "instagram"), x: await sha(base + "x")};
        out.focus = {before: before, after: after, crops: window.MFSend.results, reloads: window.MFSend.reloads,
                     stored: stored};
      } else if (sendState === "review-confirm") {
        await dialogCheck('[data-open="dlg-publish"]', "dlg-publish",
                          ["Опубликовать в 4 сети сейчас?", "Это нельзя отменить.", "Да, опубликовать", "Отмена"]);
      } else if (sendState === "review-delete") {
        await dialogCheck('.send-status [data-open="dlg-delete"]', "dlg-delete",
                          ["Удалить черновик?", "Да, удалить", "Отмена"]);
      } else if (sendState === "review-publishing") {
        ["Публикация", "Публикуется… 1 из 4 · не закрывайте панель", "Facebook · kotleta — опубликовано",
         "Instagram · kotleta — ждём…"].forEach(function (t) { see(".send-action h2, .send-status p, .send-rows li", t); });
      } else if (sendState === "review-partial") {
        ["Отправлено", "Опубликовано в 2 из 4 сетей", "LinkedIn — ошибка: вход истёк или отозван",
         "X — ошибка: доступ запрещён", "Подключение", "Переподключить: LinkedIn", "Повторить упавшие: LinkedIn, X"]
          .forEach(function (t) { see(".send-action h2, .send-status p, .send-rows li, .send-status button, .send-status a", t); });
        // the poster's own English words and its command stay out of the screen
        var sendText = (document.querySelector(".send") || document.body).innerText;
        if (/python3|HTTP|\b40[13]\b|token|Forbidden|revoked/.test(sendText)) {
          out.problems.push("an English poster error or a command is on the partial screen");
        }
      } else if (sendState === "review-published") {
        see(".send-status-line", "Опубликовано во всех 4 сетях");
        see(".send-action h2", "Отправлено");
        ["Facebook", "Instagram", "LinkedIn", "X"].forEach(function (n) { see(".send-open", "открыть в " + n); });
      } else if (sendState === "review-interrupted") {
        see(".send-status-line", "Публикация прервана — проверьте аккаунт");
        see(".send-rows li", "Instagram · kotleta — прервано");
        see(".send-action h2", "Публикация");
      } else if (sendState === "queued") {
        var pkg = params.get("probe_pkg"), row = document.getElementById("pkg-" + pkg);
        see("#pkg-" + pkg + " .queued-line", "В очереди «Мои фото» · выйдет");   // where the link lands, not scrolled
        see("#pkg-" + pkg + " h3", "Время заметить");
        see("#pkg-" + pkg + " .pkg-main", "-" + pkg + ".json");
        if (/\b(fb|ig):kotleta\b/.test(document.querySelector("#pkg-" + pkg).innerText)) {
          out.problems.push("the queued row shows target ids, not network names");
        }
        var tile = row && row.querySelector("img");
        await until(function () { return tile && tile.complete; }, "the row's image");
        if (!tile || !tile.naturalWidth || tile.getAttribute("src").indexOf("/img?") !== 0) {
          out.problems.push("the queued row shows no image from /img");
        }
        var chip = Array.prototype.some.call(document.querySelectorAll(".pgrid .ptile"), function (t) {
          return words(t).indexOf("в очереди") >= 0;
        });
        if (!chip) { out.problems.push("no «в очереди» chip on the queued photo"); }
      } else if (sendState === "rule-refused") {
        see(".main > .error", "Пост в очереди «Мои фото». Правило сохранено черновиком, но не запущено:");
        see(".main > .error li", "между постами");
      } else if (cState) {
        await imageChecks(out, {see: see, looks: looks, until: until, sleep: sleep, words: words, did: did});
      } else if (sendState === "send-start") {
        // measured where the page opens: no scrolling, so a word below the window fails
        if (scrollY !== 0) { out.problems.push("send-start did not open at the top (scrollY " + scrollY + ")"); }
        see("section h2", "Черновики · 4");
        ["публикуется", "частично", "опубликован"].forEach(function (t) { see(".draft-stage", t); });
      }
    } catch (err) { out.problems.push(err.message); }
  }

  async function imageChecks(out, h) {
    var see = h.see, until = h.until, sleep = h.sleep, words = h.words, did = h.did;
    var api = window.MFSend;
    var KEY = "mf-probe-c-" + did;
    var CHOICES = {instagram: ["4:5", "1:1", "1.91:1"], facebook: ["orig", "4:5", "1:1", "16:9"],
                   linkedin: ["orig", "1.91:1", "1:1"], x: ["16:9", "orig", "1:1"]};
    // §18.5 item 1, the first column (3 024 x 4 032) and the third (a 1 536 x 2 048 style)
    var FIRST = {"instagram 4:5": [1080, 1350], "instagram 1:1": [1080, 1080], "instagram 1.91:1": [955, 500],
                 "facebook orig": [1536, 2048], "facebook 4:5": [1636, 2045], "facebook 1:1": [2048, 2048],
                 "facebook 16:9": [2048, 1152], "linkedin orig": [1536, 2048], "linkedin 1.91:1": [1910, 1000],
                 "linkedin 1:1": [2048, 2048], "x 16:9": [1600, 900], "x orig": [1200, 1600], "x 1:1": [1600, 1600]};
    var THIRD = {facebook: [1536, 2048], instagram: [1080, 1350], linkedin: [1536, 2048], x: [1536, 864]};
    var RAW = ["[{", '{"', '"error"', "prepayment"];
    var LINE402 = "Не удалось получить {what} от Gemini (HTTP 402): закончились предоплаченные кредиты Gemini — пополните баланс в Google AI Studio";
    function next(stage, hash, query) {
      window.MFProbeNext = location.pathname + "?" + (query ? query + "&" : "") + "probe=1&probe_send=" + stage + (hash || "");
    }
    function keep(data) { sessionStorage.setItem(KEY, JSON.stringify(data)); }
    function kept() { try { return JSON.parse(sessionStorage.getItem(KEY)) || {}; } catch (e) { return {}; } }
    async function sha(path) {
      var r = await fetch(path, {credentials: "same-origin", cache: "no-store"});
      var d = await crypto.subtle.digest("SHA-256", await r.arrayBuffer());
      return Array.from(new Uint8Array(d)).map(function (b) { return b.toString(16).padStart(2, "0"); }).join("");
    }
    async function size(path) {
      var b = await createImageBitmap(await (await fetch(path, {cache: "no-store"})).blob());
      var v = [b.width, b.height];
      b.close();
      return v;
    }
    // the two tiles: side by side, the same top and width, 160 px boxes
    function tiles() {
      var t = document.querySelectorAll(".photo-tile .photo-box");
      if (t.length !== 2) { out.problems.push("photo tiles: " + t.length); return; }
      var a = t[0].getBoundingClientRect(), b = t[1].getBoundingClientRect();
      out.tiles = {a: [Math.round(a.left), Math.round(a.top), Math.round(a.width), Math.round(a.height)],
                   b: [Math.round(b.left), Math.round(b.top), Math.round(b.width), Math.round(b.height)]};
      if (Math.abs(a.top - b.top) > 1 || Math.abs(a.width - b.width) > 1 || b.left < a.right ||
          Math.abs(a.height - 160) > 1 || Math.abs(b.height - 160) > 1) {
        out.problems.push("the photo tiles are not two equal 160 px boxes side by side: " + JSON.stringify(out.tiles));
      }
    }
    function underTile(label) {   // the «основа» / «Взять за основу» row under the tile named `label`
      var tile = Array.prototype.find.call(document.querySelectorAll(".photo-tile"), function (t) {
        return words(t.querySelector(".photo-label")) === label;
      });
      return tile ? words(tile.querySelector(".photo-under")) : null;
    }
    function expectUnder(label, text) {
      var u = underTile(label);
      if (u === null || u.indexOf(text) < 0) { out.problems.push("under «" + label + "»: «" + u + "», expected «" + text + "»"); }
    }
    function seeSelect(network, key, expected) {
      var sel = document.querySelector('.look[data-look="' + network + '"] select[data-k="' + key + '"]');
      if (!sel) { out.problems.push("missing select " + network + " " + key); return; }
      var shown = sel.selectedOptions[0] ? sel.selectedOptions[0].textContent : "";
      if (shown !== expected) { out.problems.push(network + " " + key + " shows «" + shown + "», expected «" + expected + "»"); }
      sel.scrollIntoView({block: "nearest"});
      var r = sel.getBoundingClientRect();
      out.defining.push({selector: network + " " + key, text: shown, top: Math.round(r.top), bottom: Math.round(r.bottom)});
      if (sel.scrollWidth > sel.clientWidth + 1 || r.top < 0 || r.bottom > innerHeight + 1 || r.right > innerWidth + 1) {
        out.problems.push("select " + network + " " + key + " cut or off screen");
      }
    }
    function widths(selector) {
      return Array.prototype.map.call(document.querySelectorAll(selector), function (el) {
        return Math.round(el.getBoundingClientRect().width);
      });
    }
    function disabledLook(selector, before) {
      var els = Array.prototype.slice.call(document.querySelectorAll(selector));
      els.forEach(function (el, i) {
        var cs = getComputedStyle(el), w = Math.round(el.getBoundingClientRect().width);
        var off = el.disabled || el.getAttribute("aria-disabled") === "true";
        out.busy.push({text: words(el).slice(0, 40) || el.tagName, disabled: off, opacity: cs.opacity,
                       cursor: cs.cursor, width: w});
        if (!off || Number(cs.opacity) >= 1 || (before && Math.abs(before[i] - w) > 1)) {
          out.problems.push("a blocked control looks enabled or changed its width: " + (words(el).slice(0, 40) || el.tagName));
        }
      });
    }
    function noRaw() {
      var text = document.body.innerText;
      RAW.forEach(function (r) { if (text.indexOf(r) >= 0) { out.problems.push("raw vendor text on the page: " + r); } });
    }
    async function images() {   // every <img> on screen has loaded
      await until(function () {
        return Array.prototype.every.call(document.images, function (i) { return i.complete; });
      }, "images", 20000);
    }
    // the template layout, numerically and with a Range over DOM text at the same place (item 3)
    function checkLayout(layout, W, H, label) {
      var f = layout.inset, problems = [];
      if (!layout.fits) { problems.push(label + ": does not fit"); return problems; }
      if (!layout.band) { return problems; }
      var b = layout.band, pad = layout.padding, max = Math.min(0.86 * W, W - 2 * f - 2 * pad);
      if (layout.lines.length > 4 || !layout.lines.length) { problems.push(label + ": " + layout.lines.length + " lines"); }
      layout.lines.forEach(function (l) { if (l.w > max + 0.01) { problems.push(label + ": line " + l.w + " > " + max); } });
      if (b[0] < f - 0.01 || b[1] < f - 0.01 || b[0] + b[2] > W - f + 0.01 || b[1] + b[3] > H - f + 0.01) {
        problems.push(label + ": band outside the frame " + JSON.stringify(b));
      }
      if (layout.size < Math.max(10, 0.025 * W)) { problems.push(label + ": font " + layout.size); }
      var box = document.createElement("div");
      box.style.cssText = "position:absolute;left:0;top:0;width:" + W + "px;height:" + H + "px;visibility:hidden;pointer-events:none;overflow:hidden";
      document.body.appendChild(box);
      var origin = box.getBoundingClientRect(), rects = 0;
      layout.lines.forEach(function (l, i) {
        var span = document.createElement("span");
        span.style.cssText = "position:absolute;white-space:pre;left:" + l.x + "px;top:" + l.y + "px;font:" + layout.font +
                             ";line-height:" + layout.lineHeight + "px";
        span.textContent = l.text;
        box.appendChild(span);
        var range = document.createRange();
        range.selectNodeContents(span.firstChild);
        var rs = Array.prototype.filter.call(range.getClientRects(), function (r) { return r.width > 0; });
        rects += rs.length;
        if (rs.length !== 1) { problems.push(label + ": line " + i + " has " + rs.length + " rects"); return; }
        var r = rs[0], x0 = r.left - origin.left, y0 = r.top - origin.top;
        if (x0 < b[0] - 1 || x0 + r.width > b[0] + b[2] + 1 || y0 < b[1] - 1 || y0 + r.height > b[1] + b[3] + 1) {
          problems.push(label + ": line " + i + " outside its band");
        }
      });
      box.remove();
      if (rects !== layout.lines.length) { problems.push(label + ": " + rects + " line rects for " + layout.lines.length + " lines"); }
      return problems;
    }
    var did_ = did;
    if (sendState === "review-styles-empty") {
      ["Фото", "Оригинал", "основа", "Здесь появится фото со стилем — выберите стиль ниже",
       "Размыть фон — создать · до $0.09", "Свечение — создать · до $0.09", "Контур — создать · до $0.09",
       "Кто главный на фото (необязательно)"].forEach(function (t) {
        see("#photo h2, #photo figcaption, #photo .photo-under span, #photo .photo-empty p, #photo .chip, #photo label", t);
      });
      tiles();
    } else if (sendState === "review-styles") {
      await images();
      ["Оригинал", "основа", "Размыть фон", "Взять за основу", "Создать заново · до $0.09",
       "Свечение — создать · до $0.09", "Контур — создать · до $0.09"].forEach(function (t) {
        see("#photo figcaption, #photo .photo-under span, #photo .photo-under button, #photo .chip", t);
      });
      expectUnder("Оригинал", "основа");
      expectUnder("Размыть фон", "Взять за основу");
      if (/Размыть фон — создать/.test(document.querySelector("#photo").innerText)) {
        out.problems.push("a chip repeats the shown style");
      }
      tiles();
    } else if (sendState === "review-based") {
      await images();
      expectUnder("Размыть фон", "основа");
      expectUnder("Оригинал", "Взять за основу");
      ["основа", "Взять за основу", "Нажмите на фото-основу, чтобы сдвинуть центр кадра (Instagram и X)"].forEach(function (t) {
        see("#photo .photo-under span, #photo .photo-under button, #photo .photo-hint", t);
      });
      if (!document.querySelector('.photo-tile:nth-child(2) [data-focus]')) { out.problems.push("the base tile is not the focus tile"); }
      tiles();
    } else if (sendState === "review-template") {
      // the crop line is running: the photo takes no tap (a focus POST here would reload
      // the page under the crops) and says so like the other C controls
      var tplFocus = document.querySelector("[data-focus]");
      if (!tplFocus) { out.problems.push("the base photo is not a focus button"); }
      else if (api.busy()) {
        disabledLook("[data-focus]");
        tplFocus.dispatchEvent(new MouseEvent("click", {bubbles: true, clientX: 10, clientY: 10}));
        tplFocus.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter", bubbles: true}));
        tplFocus.click();
        if (cFetch.some(function (x) { return x.url.indexOf("/focus") >= 0; })) {
          out.problems.push("a focus POST was sent while the crops run");
        }
      }
      await until(function () { return api.reloads >= 1 || document.querySelector('.send-crops[role="alert"]'); },
                  "the template crops", 90000);
      if (api.reloads < 1) { out.problems.push("template crops: " + words(document.querySelector(".send-crops"))); }
      out.crops = api.results.map(function (c) { return {network: c.network, width: c.width, height: c.height, layout: c.layout}; });
      api.results.forEach(function (c) {
        if (c.layout) { out.problems = out.problems.concat(checkLayout(c.layout, c.width, c.height, c.network)); }
      });
      // every size of item 1's first column, four quotes, both places, with and without a frame
      var quotes = ["Маленькие шаги — новый взгляд.",
                    ("Маленькие шаги каждый день открывают новый взгляд на привычный город и на работу, которую " +
                     "делаешь каждое утро без спешки и без лишних слов вокруг").slice(0, 140),
                    new Array(141).join("а"), "Small steps make room for a fresh perspective every day."];
      var sweep = 0;
      Object.keys(FIRST).forEach(function (key) {
        var sz = FIRST[key];
        quotes.forEach(function (q, qi) {
          [["none", "bottom"], ["gold", "top"], ["white", "bottom"]].forEach(function (fa) {
            var lay = window.MFAuthor.layoutTemplate(sz[0], sz[1], fa[0], q, fa[1]);
            sweep += 1;
            out.problems = out.problems.concat(checkLayout(lay, sz[0], sz[1], key + " q" + qi + " " + fa.join("/")));
          });
        });
      });
      out.sweep = sweep;
      if (Array.from(quotes[1]).length !== 140) { out.problems.push("the long quote is not 140 characters"); }
      // the frame is drawn inside the image: the pixel at (f/2, f/2) has the frame's colour
      var src = await createImageBitmap(await canvasJpeg(400, 300, 5));
      out.frames = {};
      for (var colour of [["white", [255, 255, 255]], ["black", [0, 0, 0]], ["gold", [232, 196, 124]]]) {
        var crop = await window.MFAuthor.makeCrop(src, {ratio: [1, 1], width: 300, height: 300, maxBytes: 5000000,
                                                        frame: colour[0]}, [0.5, 0.5]);
        var back = await createImageBitmap(crop.blob), cv = document.createElement("canvas");
        cv.width = 300; cv.height = 300;
        var g = cv.getContext("2d");
        g.drawImage(back, 0, 0);
        back.close();
        var f = crop.layout.inset, px = Array.from(g.getImageData(Math.floor(f / 2), Math.floor(f / 2), 1, 1).data).slice(0, 3);
        out.frames[colour[0]] = px;
        if (px.some(function (v, i) { return Math.abs(v - colour[1][i]) > 12; })) {
          out.problems.push(colour[0] + " frame pixel " + JSON.stringify(px));
        }
      }
      src.close();
      // at the limit: 140 characters on a 191 x 100 crop do not fit, and nothing is posted
      var limit = window.MFAuthor.layoutTemplate(191, 100, "none", quotes[1], "bottom");
      out.limit = {fits: limit.fits};
      if (limit.fits) { out.problems.push("140 characters fit on 191 x 100"); }
      var D = api.data, saved = {source: D.source, look: D.looks.instagram};
      var posts = cFetch.filter(function (x) { return x.url.indexOf("/image?") >= 0; }).length;
      D.source = "/photo?folder=my-photos&id=" + new URLSearchParams(location.search).get("probe_small") + "&v=orig";
      D.looks.instagram = {ratio: "1.91:1", pair: [191, 100], frame: "none", quote: quotes[1], quote_at: "bottom",
                           digest: saved.look.digest};
      await api.prepare(["instagram"], D.focus);
      var line = document.querySelector(".send-crops");
      out.limit.line = words(line);
      if (words(line).indexOf("Не удалось подготовить картинку для Instagram: цитата не помещается в 4 строки — сократите") !== 0) {
        out.problems.push("the crop line at the limit: «" + words(line) + "»");
      }
      if (cFetch.filter(function (x) { return x.url.indexOf("/image?") >= 0; }).length !== posts) {
        out.problems.push("a crop was posted at the limit");
      }
      D.source = saved.source;
      D.looks.instagram = saved.look;
      out.posts = cFetch.filter(function (x) { return x.url.indexOf("/image?") >= 0; }).map(function (x) { return x.status; });
      next("review-template-after", "#send-cards-h");
    } else if (sendState === "review-template-after") {
      await images();
      [["instagram", "ratio", "1:1"], ["instagram", "frame", "белая"], ["instagram", "quote_at", "внизу"],
       ["x", "ratio", "1:1"], ["x", "frame", "чёрная"], ["x", "quote_at", "вверху"],
       ["linkedin", "ratio", "1.91:1"], ["linkedin", "frame", "золотая"],
       ["facebook", "ratio", "16:9"], ["facebook", "quote_at", "внизу"]].forEach(function (c) { seeSelect(c[0], c[1], c[2]); });
      ["instagram", "x", "facebook"].forEach(function (n) {
        var input = document.querySelector('.look[data-look="' + n + '"] [data-q]');
        if (!input || !input.offsetWidth || !input.value) { out.problems.push("no quote input for " + n); }
      });
      [["instagram", "1 080 × 1 080"], ["x", "1 600 × 1 600"], ["linkedin", "1 910 × 1 000"], ["facebook", "2 048 × 1 152"]]
        .forEach(function (c) { see('.send-card[data-network="' + c[0] + '"] .send-size', c[1], true); });
      document.getElementById("send-cards-h").scrollIntoView();
    } else if (sendState === "review-ratio") {
      out.ratio = [];
      for (var net of ["instagram", "facebook", "linkedin", "x"]) {
        var sel = document.querySelector('.look[data-look="' + net + '"] select[data-k="ratio"]');
        var order = CHOICES[net].filter(function (c) { return c !== sel.value; }).concat([sel.value]);
        for (var choice of order) {
          var r0 = api.reloads;
          sel.value = choice;
          sel.dispatchEvent(new Event("change", {bubbles: true}));
          await until(function () { return api.reloads > r0 || document.querySelector('.send-crops[role="alert"]'); },
                      "settings " + net + " " + choice, 20000);
          api.idle();
          var r1 = api.reloads;
          await api.prepare([net], api.data.focus);
          if (api.reloads === r1) { out.problems.push(net + " " + choice + ": " + words(document.querySelector(".send-crops"))); }
          api.idle();
          var last = api.results[api.results.length - 1] || {};
          out.ratio.push({network: net, choice: choice, size: [last.width, last.height]});
          var want = FIRST[net + " " + choice];
          if (!want || last.network !== net || last.width !== want[0] || last.height !== want[1]) {
            out.problems.push(net + " " + choice + " gave " + last.width + " x " + last.height + ", expected " + want);
          }
        }
      }
      out.posts = cFetch.filter(function (x) { return x.url.indexOf("/image?") >= 0; }).map(function (x) { return x.status; });
      out.settings = cFetch.filter(function (x) { return x.url.indexOf("/settings") >= 0; }).map(function (x) { return x.status; });
      if (out.posts.length !== 13 || out.posts.some(function (st) { return st !== 200; })) {
        out.problems.push("crop posts " + JSON.stringify(out.posts) + ", expected 13 answered 200");
      }
    } else if (sendState === "review-highlight-loading") {
      var sel_ = "#photo [data-c], .look [data-c]";
      var before = widths(sel_);
      var links = document.querySelectorAll("#photo a.chip[data-c]");
      if (links.length !== 2) { out.problems.push("expected two saved-style links, found " + links.length); }
      document.querySelector('[data-style="blur"]').click();
      await until(function () { return words(document.querySelector(".photo-status")).indexOf("Gemini рисует") >= 0; }, "running");
      see(".photo-status", "Gemini рисует «Размыть фон»… до 3 минут");
      disabledLook(sel_, before);
      // a saved-style link is inert while the call runs: out of the tab order, no navigation
      var href = location.href;
      links.forEach(function (a) {
        a.focus();
        a.click();
        if (a.getAttribute("tabindex") !== "-1" || a.getAttribute("aria-disabled") !== "true"
            || location.href !== href) {
          out.problems.push("a saved-style link stays live while the call runs: " + words(a));
        }
      });
      if (!cFetch.some(function (x) { return x.url.indexOf("/highlight") >= 0; })) { out.problems.push("no highlight POST"); }
      // the photo is a C control too: no tap while the call runs
      var holdFocus = document.querySelector("[data-focus]");
      if (holdFocus) {
        holdFocus.dispatchEvent(new MouseEvent("click", {bubbles: true, clientX: 10, clientY: 10}));
        holdFocus.click();
        await sleep(200);
        if (cFetch.some(function (x) { return x.url.indexOf("/focus") >= 0; })) {
          out.problems.push("a focus POST was sent while the highlight call runs");
        }
      }
    } else if (sendState === "review-highlight" || sendState === "review-highlight-text" || sendState === "review-highlight-402") {
      keep({month: words(document.getElementById("ai-month"))});
      document.querySelector('[data-style="blur"]').click();
      await until(function () { return api.went.length; }, "the highlight answer", 60000);
      out.went = api.went;
      out.calls = cFetch.filter(function (x) { return x.url.indexOf("/highlight") >= 0; }).map(function (x) { return x.status; });
      if (sendState === "review-highlight") {
        next("review-highlight-after", "#photo", "style=blur");
      } else {
        next(sendState + "-after", "#photo");
      }
    } else if (sendState === "review-highlight-after") {
      await images();
      ["Оригинал", "Размыть фон", "Взять за основу", "Создать заново · до $0.09"].forEach(function (t) {
        see("#photo figcaption, #photo .photo-under button", t);
      });
      var right = document.querySelector('.photo-tile:nth-child(2) img'), left = document.querySelector('.photo-tile:nth-child(1) img');
      out.loaded = [left && left.naturalWidth, right && right.naturalWidth, right && right.naturalHeight];
      if (!left || !left.naturalWidth || !right || right.naturalWidth !== 1536 || right.naturalHeight !== 2048) {
        out.problems.push("tile images " + JSON.stringify(out.loaded));
      }
      tiles();
      var month = words(document.getElementById("ai-month"));
      out.month = [kept().month, month];
      if (month === kept().month) { out.problems.push("the month did not change after the call: " + month); }
    } else if (sendState === "review-highlight-text-after") {
      ["Gemini не вернул картинку", "Ответ Gemini: «I can describe the photo, but I cannot edit it.»", "Повторить · до $0.09"]
        .forEach(function (t) { see("#photo .photo-error p, #photo .photo-error button", t); });
    } else if (sendState === "review-highlight-402-after") {
      see("#photo .photo-error p", LINE402.replace("{what}", "картинку"));
      see("#photo .photo-error button", "Повторить · до $0.09");
      noRaw();
    } else if (sendState === "create-error-402") {
      document.querySelector('[data-op="expand"]').click();
      await until(function () { var e = document.querySelector(".create-error"); return e && !e.hidden && /HTTP 402/.test(e.textContent); },
                  "the 402 line", 30000);
      see(".create-error p", LINE402.replace("{what}", "тексты"));
      see(".create-error button", "Повторить · до $0.05");
      noRaw();
    } else if (sendState === "review-base") {
      var names = ["facebook", "instagram", "linkedin", "x"], before_ = {};
      for (var n of names) { before_[n] = await sha("/create/" + did_ + "/file?name=" + n); }
      keep({before: before_});
      var under = document.querySelector('[data-base="blur"]');
      if (!under) { out.problems.push("no «Взять за основу» under «Размыть фон»"); } else { under.click(); }
      await until(function () { return api.reloads >= 1; }, "the base saved", 20000);
      out.settings = cFetch.filter(function (x) { return x.url.indexOf("/settings") >= 0; }).map(function (x) { return x.status; });
      next("review-base-make", "#photo");
    } else if (sendState === "review-base-make") {
      await until(function () { return api.reloads >= 1 || document.querySelector('.send-crops[role="alert"]'); },
                  "four crops from the base", 90000);
      out.source = api.data.source;
      out.made = api.results.map(function (c) { return [c.network, c.width, c.height]; });
      out.posts = cFetch.filter(function (x) { return x.url.indexOf("/image?") >= 0; }).map(function (x) { return x.status; });
      if (!/\/file\?name=blur$/.test(out.source) || out.posts.length !== 4 || out.posts.some(function (st) { return st !== 200; })) {
        out.problems.push("crops from the base: source " + out.source + ", posts " + JSON.stringify(out.posts));
      }
      next("review-base-after", "#photo");
    } else if (sendState === "review-base-after") {
      await images();
      var was = kept().before || {};
      out.after = {};
      for (var m of ["facebook", "instagram", "linkedin", "x"]) {
        var hash = await sha("/create/" + did_ + "/file?name=" + m), sz = await size("/create/" + did_ + "/file?name=" + m);
        out.after[m] = sz;
        if (!was[m] || hash === was[m]) { out.problems.push(m + " crop unchanged after the base switch"); }
        if (sz[0] !== THIRD[m][0] || sz[1] !== THIRD[m][1]) { out.problems.push(m + " is " + sz + ", expected " + THIRD[m]); }
        var img = document.querySelector('.send-card[data-network="' + m + '"] img');
        if (!img || img.naturalWidth !== THIRD[m][0]) { out.problems.push("the " + m + " card does not show the new crop"); }
      }
      see(".send-ok", "Проблем нет · 4 сети", true);
      document.getElementById("photo").scrollIntoView();
      await sleep(50);
      expectUnder("Размыть фон", "основа");
      see("#photo .photo-under span", "основа");
      tiles();
    } else if (sendState === "review-styles-budget") {
      var refusal = "Бюджет ИИ на ноябрь исчерпан: «Стиль фото» стоит до $0.09.";
      see("#photo .create-notice", refusal);
      var count = document.body.innerText.replace(/\u00a0/g, " ").split(refusal).length - 1;
      if (count !== 1) { out.problems.push("the budget refusal shows " + count + " times"); }
      disabledLook("#photo .chip[data-style]");
      var monthEl = document.getElementById("ai-month");
      if (!monthEl || words(monthEl) !== "ИИ · ноябрь $9.99 из $10.00 · лимит" || !monthEl.classList.contains("k-bad")) {
        out.problems.push("the month reads «" + (monthEl && words(monthEl)) + "»");
      }
      tiles();
    } else if (sendState === "review-styles-nokey") {
      see("#photo .create-notice", "нет GEMINI_API_KEY в .env — стили фото недоступны");
      disabledLook("#photo .chip[data-style], #photo [data-style].btn");
      var take = document.querySelector('[data-base]');
      if (!take || take.disabled) { out.problems.push("«Взять за основу» is disabled without a key"); }
      tiles();
    }
  }

  // after the load event, so the browser has already scrolled to a #fragment
  function later() {
    authorChecks().then(function () { return sendChecks(); }).then(function () {
      if (!window.MFProbeNext) { setTimeout(run, 100); }   // a staged state writes JSON on its last stage
    }, function (err) {
      window.MFProbeAuthor = {problems: [err.message]}; setTimeout(run, 100);
    });
  }

  if (document.readyState === "complete") {
    later();
  } else {
    window.addEventListener("load", later);
  }
})();
