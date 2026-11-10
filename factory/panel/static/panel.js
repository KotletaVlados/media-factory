// Media factory panel: progressive enhancement only. Every action also works without this
// file as a plain form POST followed by a redirect (design factory.md §11.1).
(function () {
  "use strict";

  function setParam(name, value) {
    var url = new URL(window.location.href);
    if (value === null) {
      url.searchParams.delete(name);
    } else {
      url.searchParams.set(name, value);
    }
    window.history.replaceState(null, "", url);
  }

  // The bell and the strip's "hide" link toggle the attention strip in place.
  function toggleStrip(id) {
    var strip = document.getElementById(id);
    if (!strip) {
      return false;
    }
    var open = strip.hidden;
    strip.hidden = !open;
    document.querySelectorAll('[aria-controls="' + id + '"]').forEach(function (el) {
      el.setAttribute("aria-expanded", open ? "true" : "false");
    });
    setParam("attention", open ? "1" : null);
    return true;
  }

  document.addEventListener("click", function (ev) {
    var toggle = ev.target.closest("[data-toggle]");
    if (toggle && toggleStrip(toggle.getAttribute("data-toggle"))) {
      ev.preventDefault();
      return;
    }
    var closer = ev.target.closest("[data-close]");
    if (closer) {
      var dialog = document.getElementById(closer.getAttribute("data-close"));
      if (dialog && dialog.open && dialog.matches(":modal")) {
        ev.preventDefault();
        dialog.close();
      }
    }
  });

  // The day window: rendered as a section for ?day=, shown as a modal so the page behind it
  // is inert; Escape, the close button and a click on the backdrop close it.
  var day = document.querySelector("dialog.day[open]");
  if (day && typeof day.showModal === "function") {
    day.close();
    day.showModal();
    day.addEventListener("close", function () {
      setParam("day", null);
    });
    day.addEventListener("click", function (ev) {
      if (ev.target === day) {
        day.close();
      }
    });
  }

  // A form submits once: a second click before the page reloads would carry the same rules
  // revision and be refused as stale.
  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (form.dataset.busy) {
      ev.preventDefault();
      return;
    }
    form.dataset.busy = "1";
  });

  // A picked time zone saves without pressing OK.
  document.querySelectorAll(".zone-form input[name=zone]").forEach(function (input) {
    input.addEventListener("change", function () {
      if (input.value && input.value !== input.defaultValue && input.form.requestSubmit) {
        input.form.requestSubmit();
      }
    });
  });
})();
