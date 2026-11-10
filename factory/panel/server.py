"""The panel's HTTP server: `python3 -m factory panel [--port 8770]` (design factory.md §11.1).

A `ThreadingHTTPServer` bound to 127.0.0.1. Server-side checks keep the promises "local only"
and "never shows a secret":

- every request: `Host` must be `127.0.0.1:<port>` or `localhost:<port>`, otherwise 421
  (DNS rebinding);
- every POST: an `Origin` that is present must match the Host, and the form field `csrf` must
  equal the token made at start, otherwise 403. The body must be
  `application/x-www-form-urlencoded` (415) and at most 16 KB (413);
- `/img` serves only an image ref that one of the package's variants names, whose real path
  lies inside the library or the package's folder and that sniffs as JPEG, PNG, GIF or WEBP;
  anything else is 404;
- every page passes through the snapshot's Redactor once more before it is sent.
"""

from __future__ import annotations

import errno
import hmac
import http.server
import os
import secrets
import shutil
import threading
import urllib.parse

from poster import config, package as poster_package, rules as poster_rules
from poster.redact import Redactor
from factory import ruleset as fruleset
from factory.panel import actions, model, views

MAX_BODY = 16 * 1024
FORM_TYPE = "application/x-www-form-urlencoded"
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC = {"panel.css": "text/css; charset=utf-8",
          "panel.js": "text/javascript; charset=utf-8",
          "probe.js": "text/javascript; charset=utf-8"}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self'; style-src 'self'; "
                               "script-src 'self'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
PAGES = {"/connection": ("connection", views.connection), "/files": ("files", views.files),
         "/rules": ("rules", views.rules), "/calendar": ("calendar", views.calendar),
         "/reach": ("reach", views.reach), "/followers": ("followers", views.followers),
         "/dialogs": ("dialogs", views.dialogs)}
RULE_ACTIONS = ("day", "hour", "zone", "start", "stop", "new")


class Panel:
    """State shared by the request threads: the snapshot holder, the CSRF token, the lock
    that serialises the panel's own writes."""

    def __init__(self, paths, clock, machine_tz: str, log=None):
        self.paths, self.clock, self.machine_tz = paths, clock, machine_tz
        self.holder = model.Holder(paths, clock, machine_tz, log)
        self.csrf = secrets.token_hex(32)
        self.write_lock = threading.Lock()

    def redactor(self, snap=None) -> Redactor:
        if snap is not None:
            return snap.redactor
        r = Redactor()
        try:
            r.add_env(config.load_env(self.paths.env_file))
        except (config.ConfigError, OSError, UnicodeDecodeError):
            pass
        return r


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, panel: Panel):
        self.panel = panel
        super().__init__(address, Handler)

    @property
    def port(self) -> int:
        return self.server_address[1]


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "media-factory-panel"
    sys_version = ""
    timeout = 30

    # ------------------------------------------------------------ plumbing

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass  # request lines carry query strings; nothing is logged

    def end_headers(self):
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    @property
    def panel(self) -> Panel:
        return self.server.panel

    def _send(self, status: int, body: bytes, ctype: str, headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _plain(self, status: int, text: str):
        self._send(status, (text + "\n").encode(), "text/plain; charset=utf-8",
                   {"Cache-Control": "no-store"})

    def _redirect(self, location: str, status: int = 303):
        self.send_response(status)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _host_ok(self) -> bool:
        port = self.server.port
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    # ------------------------------------------------------------ GET

    def do_GET(self):  # noqa: N802 - stdlib name
        if not self._host_ok():
            return self._plain(421, "misdirected request: open the panel at 127.0.0.1 or localhost")
        url = urllib.parse.urlsplit(self.path)
        path = url.path
        query = urllib.parse.parse_qs(url.query, keep_blank_values=True, max_num_fields=50)
        if path == "/":
            return self._redirect("/connection", 302)
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        if path == "/img":
            return self._img(query)
        if path in PAGES:
            tab, render = PAGES[path]
            return self._page(path, query, tab, render)
        return self._page(path, query, "error", views.not_found_page, status=404)

    def _static(self, name: str):
        ctype = STATIC.get(name)
        if ctype is None:
            return self._plain(404, "not found")
        with open(os.path.join(STATIC_DIR, name), "rb") as fh:
            body = fh.read()
        self._send(200, body, ctype, {"Cache-Control": "no-cache"})

    def _page(self, path, query, tab, render, *, status=200, refusal=None):
        snap = None
        try:
            snap = self.panel.holder.get()
            ctx = views.Ctx(snap, path, query, self.panel.csrf,
                            probe=(query.get("probe") or [""])[0] == "1")
            if snap.env_error and tab not in ("dialogs", "error"):
                html = views.env_error_page(ctx, tab)
            elif refusal is not None:
                html = render(ctx, refusal=refusal)
            else:
                html = render(ctx)
        except Exception as exc:  # the one last-resort path; the message is redacted
            status = 500
            message = self.panel.redactor(snap).redact(f"{type(exc).__name__}: {exc}")
            print(f"panel: {message}", file=self.panel.holder.log, flush=True)
            html = views.other_error_page(views.Ctx(None, path, query, self.panel.csrf), message)
        body = self.panel.redactor(snap).redact(html).encode("utf-8")
        self._send(status, body, "text/html; charset=utf-8", {"Cache-Control": "no-store"})

    def _img(self, query):
        def q(name):
            return (query.get(name) or [""])[0]
        try:
            snap = self.panel.holder.get()
        except Exception:  # noqa: BLE001 - an image never shows an error page
            return self._plain(404, "not found")
        if snap.inputs is None:
            return self._plain(404, "not found")
        folder = snap.inputs.stock.folders.get(q("folder"))
        entry = next((e for e in folder.entries if e.file == q("file")), None) if folder else None
        if entry is None or entry.package is None:
            return self._plain(404, "not found")
        ref = q("ref")
        if ref not in {v.image_ref for v in entry.package.variants.values() if v.image_ref}:
            return self._plain(404, "not found")
        try:
            path = poster_package.resolve_image(ref, os.path.dirname(entry.path),
                                                snap.inputs.paths.library)
        except ValueError:
            return self._plain(404, "not found")
        real = os.path.realpath(path)
        roots = [os.path.realpath(snap.inputs.paths.library), os.path.realpath(folder.path)]
        if not any(real.startswith(root + os.sep) for root in roots):
            return self._plain(404, "not found")
        try:
            info = poster_rules.sniff(real)
            fh = open(real, "rb")
        except OSError:
            return self._plain(404, "not found")
        if info.format not in model.IMAGE_FORMATS:
            fh.close()
            return self._plain(404, "not found")
        with fh:
            size = os.fstat(fh.fileno()).st_size
            self.send_response(200)
            self.send_header("Content-Type", poster_rules.MIME[info.format])
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "private, max-age=300")
            self.end_headers()
            shutil.copyfileobj(fh, self.wfile, 64 * 1024)

    # ------------------------------------------------------------ POST

    def do_POST(self):  # noqa: N802 - stdlib name
        if not self._host_ok():
            return self._plain(421, "misdirected request")
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{self.headers.get('Host')}":
            return self._plain(403, "forbidden: foreign origin")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            return self._plain(411, "length required")
        try:
            length = int(raw_length)
        except ValueError:
            return self._plain(400, "bad Content-Length")
        if length < 0:
            return self._plain(400, "bad Content-Length")
        if length > MAX_BODY:
            self.close_connection = True
            return self._plain(413, "form too large")
        ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if ctype != FORM_TYPE:
            self.close_connection = True
            return self._plain(415, f"unsupported media type: send {FORM_TYPE}")
        data = self.rfile.read(length)
        try:
            form = urllib.parse.parse_qs(data.decode("utf-8"), keep_blank_values=True,
                                         max_num_fields=200, strict_parsing=False)
        except (UnicodeDecodeError, ValueError):
            return self._plain(400, "bad form")
        token = (form.get("csrf") or [""])[0]
        if not hmac.compare_digest(token.encode(), self.panel.csrf.encode()):
            return self._plain(403, "forbidden: missing or wrong csrf")
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query, keep_blank_values=True, max_num_fields=50)
        if url.path.startswith("/rules/") and url.path[len("/rules/"):] in RULE_ACTIONS:
            return self._write("rules", url.path[len("/rules/"):], form, query)
        if url.path == "/files/new-folder":
            return self._write("files", "new-folder", form, query)
        return self._plain(404, "not found")

    def _write(self, tab: str, kind: str, form: dict, query: dict):
        panel = self.panel
        refusal = None
        with panel.write_lock:
            try:
                if tab == "rules":
                    location = actions.rules_action(kind, form, panel.paths, panel.clock(),
                                                    panel.redactor())
                else:
                    location = actions.new_folder(form, panel.paths)
            except actions.Refusal as r:
                refusal = {"status": r.status, "rule": r.rule, "problems": r.problems,
                           "stale": r.stale, "form": form,
                           "lane": (form.get("lane") or [""])[0],
                           "name": (form.get("name") or [""])[0]}
            except (config.ConfigError, fruleset.RulesError):
                location = None   # the page shows the env or rules error from a fresh snapshot
                refusal = {"status": 409, "rule": None, "problems": [], "stale": False,
                           "form": form}
        if refusal is None:
            return self._redirect(location)
        render = views.rules if tab == "rules" else views.files
        return self._page(f"/{tab}", query, tab, render, status=refusal["status"],
                          refusal=refusal)


def make_server(paths, clock, machine_tz: str, port: int = 0, log=None) -> Server:
    """Bind 127.0.0.1:port (0 picks a free port; read it back from `.port`)."""
    return Server(("127.0.0.1", port), Panel(paths, clock, machine_tz, log))


def serve(app, port: int) -> int:
    """`python3 -m factory panel`: serve until Ctrl+C."""
    try:
        server = make_server(app.paths, app.clock, app.machine_tz, port)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            app.out("error: port in use, pass --port", err=True)
            return 2
        raise
    app.out(f"panel: http://localhost:{server.port}/  (Ctrl+C stops it)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
