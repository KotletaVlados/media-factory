"""The panel's HTTP server: `python3 -m factory panel [--port 8770]` (design factory.md §11.1).

A `ThreadingHTTPServer` bound to 127.0.0.1. Server-side checks keep the promises "local only"
and "never shows a secret":

- every request: `Host` must be `127.0.0.1:<port>` or `localhost:<port>`, otherwise 421
  (DNS rebinding);
- every POST: Origin must match Host (required for non-form bodies); CSRF is checked
  in the form field or X-CSRF-Token header. Each route declares its media types and
  length bound (415/413), including authoring JSON and in-memory audio;
- `/img` serves only an image ref that one of the package's variants names, whose real path
  lies inside the library or the package's folder and that sniffs as JPEG, PNG, GIF or WEBP;
  anything else is 404;
- every page passes through the snapshot's Redactor once more before it is sent.
"""

from __future__ import annotations

import errno
import hmac
import http.server
import json
import os
import re
import secrets
import shutil
import threading
import urllib.parse
from dataclasses import dataclass

from poster import config, package as poster_package, rules as poster_rules
from poster.redact import Redactor
from factory import ruleset as fruleset
from factory.authoring import photos, drafts, profile, budget, gemini
from factory.authoring.common import Refusal, text
from factory.panel import actions, model, strings as S, views

MAX_BODY = 16 * 1024
FORM_TYPE = "application/x-www-form-urlencoded"
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC = {"panel.css": "text/css; charset=utf-8",
          "panel.js": "text/javascript; charset=utf-8",
          "probe.js": "text/javascript; charset=utf-8",
          "author.js": "text/javascript; charset=utf-8",
          "create.js": "text/javascript; charset=utf-8"}
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
FORM, IMAGE, JSON, AUDIO = "form", "image", "json", "audio"


@dataclass(frozen=True)
class Route:
    """One POST route (design authoring.md §14.1): its body kind, the Content-Length limit and
    the accepted media types, and for forms the write it runs."""
    kind: str
    limit: int
    types: tuple
    handler: str = ""
    action: str = ""


def declared_length(raw) -> int | None:
    """Content-Length as ASCII digits only (int() would also take "5_000", " 5" or other
    scripts' digits); None when absent or malformed."""
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9]{1,18}", raw):
        return None
    return int(raw)


def post_route(path: str, query: dict) -> Route | None:
    if path.startswith("/rules/") and path[len("/rules/"):] in RULE_ACTIONS:
        return Route(FORM, MAX_BODY, (FORM_TYPE,), "rules", path[len("/rules/"):])
    if path == "/files/new-folder":
        return Route(FORM, MAX_BODY, (FORM_TYPE,), "files", "new-folder")
    if path == "/files/photos":
        kind = (query.get("kind") or [""])[0]
        return Route(IMAGE, photos.limit_for(kind), photos.types_for(kind))
    if path == "/create/profile":
        return Route(FORM, MAX_BODY, (FORM_TYPE,), "profile")
    if path == "/create/new":
        return Route(JSON, 64 * 1024, ("application/json",), "create", "new")
    match = re.fullmatch(r"/create/([^/]+)/(topics|topic|expand|regenerate|text|voice)", path)
    if match:
        op = match[2]
        return Route(AUDIO if op == "voice" else JSON,
                     1024 * 1024 if op == "voice" else 64 * 1024,
                     ("audio/webm", "audio/ogg") if op == "voice" else ("application/json",),
                     match[1], op)
    return None


class Panel:
    """State shared by the request threads: the snapshot holder, the CSRF token, the lock
    that serialises the panel's own writes."""

    def __init__(self, paths, clock, machine_tz: str, log=None, ai_transport=None):
        self.paths, self.clock, self.machine_tz = paths, clock, machine_tz
        self.holder = model.Holder(paths, clock, machine_tz, log)
        self.csrf = secrets.token_hex(32)
        self.write_lock = threading.Lock()
        self.drafts = drafts.Store(paths.content, clock, machine_tz)
        self.ai_ledger = budget.Ledger(paths.state, clock)
        self.ai = gemini.Service(paths, clock, self.drafts, self.ai_ledger, self.redactor, ai_transport)

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
    # allow_reuse_address stays at the stdlib default (SO_REUSEADDR): the port is free again
    # right after Ctrl+C, while on Linux a second live listener is still refused (EADDRINUSE).

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
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # Closing a page cannot undo a settled AI call. Its draft and reservation
            # already persist; do not turn a disconnected response into a second error.
            self.close_connection = True

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
            return self._redirect("/create", 302)
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        if path == "/img":
            return self._img(query)
        if path == "/photo":
            return self._photo(query)
        if path == "/create":
            return self._page(path, query, "create", views.create)
        if path == "/create/profile":
            return self._page(path, query, "create", views.create_profile)
        if path.startswith("/create/"):
            did = path[len("/create/"):]
            try:
                self.panel.drafts.load(did)
            except Refusal as exc:
                return self._page(path, query, "error", views.not_found_page, status=exc.status)
            return self._page(path, query, "create", views.create_draft)
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
                            probe=(query.get("probe") or [""])[0] == "1", author=self.panel)
            if snap.env_error and tab not in ("dialogs", "error"):
                html = views.env_error_page(ctx, tab)
            elif refusal is not None:
                html = render(ctx, refusal=refusal)
            else:
                html = render(ctx)
        except Exception as exc:
            return self._last_resort(path, query, exc, snap)
        body = self.panel.redactor(snap).redact(html).encode("utf-8")
        self._send(status, body, "text/html; charset=utf-8", {"Cache-Control": "no-store"})

    def _last_resort(self, path, query, exc, snap=None):
        """The one last-resort path for pages and writes: HTTP 500, a shell with the redacted
        `type: message`, and one redacted line on the panel's log."""
        redactor = self.panel.redactor(snap)
        message = redactor.redact(f"{type(exc).__name__}: {exc}")
        print(f"panel: {message}", file=self.panel.holder.log, flush=True)
        html = views.other_error_page(views.Ctx(None, path, query, self.panel.csrf), message)
        self._send(500, redactor.redact(html).encode("utf-8"), "text/html; charset=utf-8",
                   {"Cache-Control": "no-store"})

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

    def _photo(self, query):
        """GET /photo?folder=F&id=P&v=thumb|view|orig (design authoring.md §6.5): the file
        resolves inside the folder's photos/ and sniffs as JPEG, PNG or WebP; else 404."""
        def q(name):
            return (query.get(name) or [""])[0]
        path = photos.file_path(self.panel.paths.stock, q("folder"), q("id"), q("v"))
        if path is None:
            return self._plain(404, "not found")
        try:
            info = poster_rules.sniff(path)
            fh = open(path, "rb")
        except OSError:
            return self._plain(404, "not found")
        if info.format not in photos.EXT:
            fh.close()
            return self._plain(404, "not found")
        with fh:
            size = os.fstat(fh.fileno()).st_size
            self.send_response(200)
            self.send_header("Content-Type", poster_rules.MIME[info.format])
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "private, max-age=300")
            self.end_headers()
            if self.command != "HEAD":
                shutil.copyfileobj(fh, self.wfile, 64 * 1024)

    # ------------------------------------------------------------ POST

    def do_POST(self):  # noqa: N802 - stdlib name
        """Checks in this order for every POST (design authoring.md §14.1): Host (421); route
        (404); Origin (foreign 403, absent 403 for non-form kinds); Content-Length (411, 400,
        413); Content-Type (415); CSRF (form: the `csrf` field after parsing; other kinds: the
        `X-CSRF-Token` header, before any body byte is read); then the handler."""
        if not self._host_ok():
            return self._refuse(421, "misdirected request")
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query, keep_blank_values=True, max_num_fields=50)
        route = post_route(url.path, query)
        if route is None:
            return self._refuse(404, "not found")
        json_kind = route.kind != FORM
        origin = self.headers.get("Origin")
        if (origin is not None and origin != f"http://{self.headers.get('Host')}") or (
                origin is None and json_kind):
            return self._refuse(403, S.UP_FORBIDDEN if json_kind else "forbidden: foreign origin",
                                json_kind)
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            return self._refuse(411, S.UP_LENGTH if json_kind else "length required", json_kind)
        length = declared_length(raw_length)
        if length is None:
            return self._refuse(400, S.UP_LENGTH if json_kind else "bad Content-Length", json_kind)
        if length > route.limit:
            return self._refuse(413, S.UP_TOO_LARGE.format(mb=route.limit // (1024 * 1024))
                                if json_kind else "form too large", json_kind)
        ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if ctype not in route.types:
            if json_kind:   # same origin, a fitting length: drain it, answer in JSON
                self._drain(length)
                return self._json(415, {"error": S.UP_BAD_TYPE})
            return self._refuse(415, f"unsupported media type: send {FORM_TYPE}")
        if json_kind:
            token = self.headers.get("X-CSRF-Token") or ""
            if not hmac.compare_digest(token.encode(), self.panel.csrf.encode()):
                self._drain(length)   # a stale page after a restart reads the reason
                return self._json(403, {"error": S.UP_FORBIDDEN})
            if route.kind == IMAGE:
                return self._upload(query, length)
            return self._create_write(route, length, ctype)
        data = self.rfile.read(length)
        try:
            form = urllib.parse.parse_qs(data.decode("utf-8"), keep_blank_values=True,
                                         max_num_fields=200, strict_parsing=False)
        except (UnicodeDecodeError, ValueError):
            return self._plain(400, "bad form")
        token = (form.get("csrf") or [""])[0]
        if not hmac.compare_digest(token.encode(), self.panel.csrf.encode()):
            return self._plain(403, "forbidden: missing or wrong csrf")
        if route.handler == "profile":
            return self._profile_write(form, query)
        return self._write(route.handler, route.action, form, query)

    def _profile_write(self, form, query):
        values = {"audience": {}}
        for name, *_ in profile.FIELDS:
            v = (form.get(name) or [""])[0]
            if name.startswith("audience."):
                values["audience"][name.split(".")[1]] = v
            else:
                values[name] = v
        try:
            clean = json.loads(self.panel.redactor().redact(json.dumps(values, ensure_ascii=False)))
            profile.save(self.panel.paths.content, clean, self.panel.clock())
        except Refusal as exc:
            return self._page("/create/profile", query, "create", views.create_profile,
                              status=exc.status, refusal={"values": values, "error": exc.message})
        except Exception as exc:
            return self._last_resort("/create/profile", query, exc)
        return self._redirect("/create/profile?saved=1")

    def _create_write(self, route, length, ctype):
        panel, op, did = self.panel, route.action, route.handler
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise Refusal("неверный запрос", 400)
            if route.kind == JSON:
                try:
                    data = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError, RecursionError):
                    raise Refusal("неверный запрос", 400) from None
                if not isinstance(data, dict):
                    raise Refusal("неверный запрос", 400)
                # All persisted operator text crosses the same redaction boundary.
                data = json.loads(panel.redactor().redact(json.dumps(data, ensure_ascii=False)))
            else:
                data = {}
            if op == "new":
                draft = panel.drafts.create(panel.paths.stock, data.get("folder"), data.get("photo"),
                                            bool(panel.ai.env().get("GEMINI_API_KEY", "").strip()))
                return self._json(200, {"id": draft["id"], "url": "/create/" + draft["id"]})
            panel.drafts.load(did)
            if op == "topic":
                value = text(data.get("topic"), 2000, "тема")
                draft = panel.drafts.update(did, lambda d: d.update(topic=value))
                return self._json(200, {"topic": draft["topic"]})
            network = data.get("network", "")
            if op in ("text", "regenerate") and (not isinstance(network, str) or network not in drafts.LANGS):
                raise Refusal("неверная сеть", 400)
            if op == "text":
                value = data.get("text")
                if isinstance(value, str) and len(value) > 5000:
                    raise Refusal("текст длиннее 5 000 знаков")
                value = text(value, 5000, "текст")
                def edit(d):
                    d["variants"][network] = {"text": value, "lang": drafts.LANGS[network], "source": "edited"}
                draft = panel.drafts.update(did, edit)
                check = poster_rules.check_text(network, draft["variants"][network]["text"])
                return self._json(200, dict(gemini.present(network, draft["variants"][network]["text"]),
                                            counts=check.counts, errors=check.errors))
            auto = data.get("auto", False)
            if op == "topics" and not isinstance(auto, bool):
                raise Refusal("неверный запрос", 400)
            wish = text(data.get("wish", ""), 200, "пожелание") if op == "regenerate" else ""
            try:
                result = panel.ai.run(did, op, auto=auto, network=network, wish=wish,
                                      audio=raw if op == "voice" else b"", mime=ctype)
            except Refusal as exc:
                if exc.status != 400:
                    def error(d):
                        d["error"] = {"op": op, "network": network if isinstance(network, str) else "",
                                      "text": panel.redactor().redact(exc.message),
                                      "ts": config.iso_utc(panel.clock())}
                    panel.drafts.update(did, error)
                raise
            result["month"] = panel.ai_ledger.display(panel.ai.env())
            return self._json(200, result)
        except (Refusal, photos.UploadError) as exc:
            reply = {"error": exc.message}
            try:
                reply["month"] = panel.ai_ledger.display(panel.ai.env())
            except (Refusal, config.ConfigError, OSError):
                pass
            return self._json(exc.status, reply)
        except Exception as exc:
            message = panel.redactor().redact(f"{type(exc).__name__}: {exc}")
            print(f"panel: create: {message}", file=panel.holder.log, flush=True)
            return self._json(500, {"error": "Ошибка панели — повторите"})

    def _refuse(self, status: int, text: str, as_json: bool = False):
        """A refusal before the body is read: the unread body would be taken for the next
        request, so the connection closes after the answer. A small declared body (at most
        a form's 16 KB) is read and dropped first, so the client reads the answer rather than
        a reset."""
        length = declared_length(self.headers.get("Content-Length"))
        if length is not None and length <= MAX_BODY:
            self._drain(length)
        self.close_connection = True
        if as_json:
            return self._json(status, {"error": text}, {"Connection": "close"})
        self._send(status, (text + "\n").encode(), "text/plain; charset=utf-8",
                   {"Cache-Control": "no-store", "Connection": "close"})

    def _json(self, status: int, data: dict, headers: dict | None = None):
        """Every JSON reply: no-store, the body redacted (design authoring.md §14.1)."""
        body = self.panel.redactor().redact(json.dumps(data, ensure_ascii=False))
        self._send(status, body.encode("utf-8"), "application/json; charset=utf-8",
                   dict({"Cache-Control": "no-store"}, **(headers or {})))

    def _drain(self, length: int) -> None:
        """Read and drop a body that a same-origin request with a fitting length sent, so the
        browser reads the refusal instead of a reset connection."""
        left = length
        try:
            while left > 0:
                chunk = self.rfile.read(min(photos.CHUNK, left))
                if not chunk:
                    break
                left -= len(chunk)
        except OSError:   # a timeout or a reset: the answer may still reach the client
            pass
        if left > 0:
            self.close_connection = True

    def _upload(self, query, length: int):
        """POST /files/photos (design authoring.md §6.2). Not under the panel's write lock: a
        slow body must not hold up rules writes; `photos.store_body` locks its own folder."""
        def q(name):
            return (query.get(name) or [""])[0]
        kind, pid = q("kind"), q("id")
        try:
            folder_photos = photos.pre_check(self.panel.paths.stock, q("folder"), kind, pid)
            photos.check_space(folder_photos, length)
        except photos.UploadError as exc:
            self._drain(length)
            return self._json(exc.status, {"error": exc.message})
        except Exception as exc:  # noqa: BLE001 - the last resort, as for a page
            self.close_connection = True
            return self._upload_failed(exc)
        try:
            result = photos.store_body(folder_photos, kind, pid, q("name"), self.rfile, length,
                                       self.panel.clock())
        except photos.UploadError as exc:
            if exc.message == S.UP_CUT:
                self.close_connection = True
            return self._json(exc.status, {"error": exc.message})
        except Exception as exc:  # noqa: BLE001 - a socket timeout, a disk error, a bug
            self.close_connection = True
            return self._upload_failed(exc)
        return self._json(200, result)

    def _upload_failed(self, exc):
        """HTTP 500 with a fixed Russian text; one redacted line on the panel's log."""
        message = self.panel.redactor().redact(f"{type(exc).__name__}: {exc}")
        print(f"panel: upload: {message}", file=self.panel.holder.log, flush=True)
        try:
            return self._json(500, {"error": S.UP_FAILED})
        except OSError:
            return None   # the client is gone

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
            except Exception as exc:  # the last-resort path, as for a page: 500, redacted
                return self._last_resort(f"/{tab}", query, exc)
        if refusal is None:
            return self._redirect(location)
        render = views.rules if tab == "rules" else views.files
        return self._page(f"/{tab}", query, tab, render, status=refusal["status"],
                          refusal=refusal)


def make_server(paths, clock, machine_tz: str, port: int = 0, log=None, ai_transport=None) -> Server:
    """Bind 127.0.0.1:port (0 picks a free port; read it back from `.port`)."""
    return Server(("127.0.0.1", port), Panel(paths, clock, machine_tz, log, ai_transport))


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
