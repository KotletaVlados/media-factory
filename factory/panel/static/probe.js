// Visual-check probe, loaded only with ?probe=1 (design factory.md §13.3 item 4). It measures
// the rendered page and writes the findings as JSON into <pre id="probe">.
(function () {
  "use strict";
  var MAX = 60;

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
      window.scrollTo(0, 0);
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
        if (w > 0.5 && h > 0.5 && !controls[i].contains(controls[j]) &&
            !controls[j].contains(controls[i])) {
          add("overlap", controls[i], "with " + name(controls[j]));
        }
      }
    }
    var pre = document.createElement("pre");
    pre.id = "probe";
    pre.textContent = JSON.stringify({width: W, height: document.documentElement.scrollHeight,
                                      controls: controls.length, findings: findings,
                                      ellipsis: ellipsized.map(clampText),
                                      whole: whole.map(clampText)});
    document.body.appendChild(pre);
  }

  if (document.readyState === "complete") {
    run();
  } else {
    window.addEventListener("load", run);
  }
})();
