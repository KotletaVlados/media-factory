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
      var pre = document.createElement("pre");
      pre.id = "probe";
      pre.textContent = JSON.stringify({width: W, height: document.documentElement.scrollHeight,
                                        controls: controls.length, findings: findings, scrollY: window.scrollY,
                                        hash: location.hash, expanders: measured,
                                        ellipsis: ellipsized.map(clampText),
                                        whole: whole.map(clampText)});
      document.body.appendChild(pre);
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

  // after the load event, so the browser has already scrolled to a #fragment
  function later() {
    setTimeout(run, 100);
  }

  if (document.readyState === "complete") {
    later();
  } else {
    window.addEventListener("load", later);
  }
})();
