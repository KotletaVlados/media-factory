"""HTTP plumbing: request/response objects, the real urllib transport, the dry-run transport,
a multipart encoder and vendor error reduction (design §9 common rules, §12).
"""

from __future__ import annotations

import http.client
import json
import secrets
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from poster import __version__
from poster.redact import mask_long_runs

USER_AGENT = f"media-factory-poster/{__version__}"
API_TIMEOUT = 30
UPLOAD_TIMEOUT = 120


@dataclass
class FilePart:
    field: str
    filename: str
    mime: str
    data: bytes
    describe: str  # e.g. "jpeg 1200x800, 245123 bytes" (for dry-run output)


@dataclass
class Request:
    method: str
    url: str
    headers: dict = field(default_factory=dict)
    body: bytes | None = None
    kind: str = "none"                    # none | form | json | multipart | bytes
    fields: dict = field(default_factory=dict)   # display copy of form/JSON fields
    files: list = field(default_factory=list)    # FilePart list (multipart / bytes)
    secret_fields: tuple = ()             # field names masked in display
    timeout: float = API_TIMEOUT
    anonymous: bool = False               # no credentials attached (check-staging)

    def describe(self) -> list[str]:
        """Human-readable request for dry-run output. Secrets are masked here and again
        by the redactor on output."""
        url = self.url
        parts = urllib.parse.urlsplit(url)
        if parts.query:
            q = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
            q = [(k, "[redacted]" if k in self.secret_fields else v) for k, v in q]
            url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(q)))
        lines = [f"{self.method} {url}"]
        for name, value in self.headers.items():
            shown = "[redacted]" if name.lower() == "authorization" else value
            lines.append(f"  header {name}: {shown}")
        if self.kind in ("form", "json", "multipart"):
            lines.append(f"  {self.kind} body:")
            if self.kind == "json":
                shown = _mask_json(self.fields, self.secret_fields)
                for row in json.dumps(shown, ensure_ascii=False, indent=2).splitlines():
                    lines.append("    " + row)
            else:
                for name, value in self.fields.items():
                    shown = "[redacted]" if name in self.secret_fields else str(value)
                    pad = "\n" + " " * (len(name) + 7)
                    lines.append(f"    {name} = {shown.replace(chr(10), pad)}")
        for part in self.files:
            lines.append(f"    {part.field} = <file {part.filename}: {part.describe}>")
        return lines


def _mask_json(obj, secret_fields):
    if isinstance(obj, dict):
        return {k: "[redacted]" if k in secret_fields else _mask_json(v, secret_fields)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask_json(v, secret_fields) for v in obj]
    return obj


def form_request(method, url, fields, *, secret_fields=("access_token",), timeout=API_TIMEOUT,
                 headers=None) -> Request:
    body = urllib.parse.urlencode(fields).encode()
    h = {"Content-Type": "application/x-www-form-urlencoded"}
    h.update(headers or {})
    return Request(method, url, h, body, "form", dict(fields), [], tuple(secret_fields), timeout)


def json_request(method, url, obj, *, display=None, headers=None, timeout=API_TIMEOUT,
                 secret_fields=()) -> Request:
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    return Request(method, url, h, body, "json", display if display is not None else obj, [],
                   tuple(secret_fields), timeout)


def multipart_request(method, url, fields, files, *, secret_fields=("access_token",),
                      timeout=UPLOAD_TIMEOUT, boundary=None) -> Request:
    boundary = boundary or "mfposter" + secrets.token_hex(16)
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                      .encode() + str(value).encode("utf-8") + b"\r\n")
    for part in files:
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{part.field}\"; "
            f"filename=\"{_safe_filename(part.filename)}\"\r\nContent-Type: {part.mime}\r\n\r\n"
            .encode() + part.data + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    return Request(method, url, headers, b"".join(chunks), "multipart", dict(fields), list(files),
                   tuple(secret_fields), timeout)


def _safe_filename(name: str) -> str:
    return "".join(c if c.isascii() and c.isprintable() and c not in '"\\' else "_" for c in name)


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self):
        if not self.body:
            return {}
        try:
            return json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


class TransportError(Exception):
    """Timeout or connection failure: the request may or may not have reached the vendor."""


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status} {message}")
        self.status = status
        self.message = message

    @property
    def uncertain(self) -> bool:
        """A 5xx on a write: the vendor may have acted before it failed, so the outcome is
        unknown, not failed. A 4xx is a definite refusal."""
        return self.status >= 500


def graph_error_codes(resp: Response) -> tuple[int | None, int | None]:
    """(code, error_subcode) of a Graph API error body, None where absent or not a number."""
    data = resp.json()
    err = data.get("error") if isinstance(data, dict) else None
    if not isinstance(err, dict):
        return None, None

    def num(key):
        value = err.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    return num("code"), num("error_subcode")


def describe_status(resp: Response) -> str:
    """'HTTP 400, code 10' (code only when the body carries one)."""
    code, _ = graph_error_codes(resp)
    return f"HTTP {resp.status}" + (f", code {code}" if code is not None else "")


def vendor_message(resp: Response) -> str:
    """Reduce a vendor error body to its documented message fields (design §12)."""
    data = resp.json()
    # Google sends its error as a one-element array of the object (seen on a 402, 2026-11-13).
    if isinstance(data, list) and data and isinstance(data[0], dict):
        data = data[0]
    parts: list[str] = []
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):  # Graph API
            for key in ("message", "code", "error_subcode", "fbtrace_id"):
                if key in err:
                    parts.append(f"{key} {err[key]}" if key != "message" else str(err[key]))
        else:
            for key in ("title", "detail", "type", "message", "serviceErrorCode"):
                if key in data and isinstance(data[key], (str, int)):
                    parts.append(f"{key} {data[key]}" if key not in ("message", "title", "detail")
                                 else str(data[key]))
            if not parts and isinstance(data.get("errors"), list) and data["errors"]:
                first = data["errors"][0]
                if isinstance(first, dict):
                    parts.append(str(first.get("message") or first.get("detail") or ""))
            if not parts and isinstance(err, str):
                parts.append(err + (": " + str(data.get("error_description"))
                                    if data.get("error_description") else ""))
    if not parts:
        parts.append(resp.body[:200].decode("utf-8", "replace").strip() or "(empty body)")
    text = "; ".join(p for p in parts if p)
    return mask_long_runs(text)[:500]


def check(resp: Response, what: str) -> dict:
    """Return the JSON body of a 2xx response, or raise ApiError with a reduced message."""
    if not resp.ok:
        raise ApiError(resp.status, f"{what}: {vendor_message(resp)}")
    return resp.json()


# ---------------------------------------------------------------- real transport

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # never forward Authorization to another host


class UrllibTransport:
    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_NoRedirect())

    def send(self, req: Request) -> Response:
        if not req.url.startswith("https://"):
            raise TransportError("refusing a non-HTTPS URL")
        headers = {"User-Agent": USER_AGENT}
        headers.update(req.headers)
        r = urllib.request.Request(req.url, data=req.body, headers=headers, method=req.method)
        try:
            with self._opener.open(r, timeout=req.timeout) as resp:
                return Response(resp.status, {k.lower(): v for k, v in resp.headers.items()},
                                resp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read() if exc.fp else b""
            return Response(exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, body)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise TransportError(f"network error: {type(reason).__name__}") from None
        except http.client.HTTPException as exc:
            # IncompleteRead, BadStatusLine, ...: raised while the reply is read, after the
            # request reached the vendor, so callers must treat the write as possibly landed
            raise TransportError(f"network error: {type(exc).__name__}") from None


# ---------------------------------------------------------------- dry-run transport

class DryRunTransport:
    """Records every request and answers with synthetic responses. Opens no socket."""

    def __init__(self) -> None:
        self.requests: list[Request] = []
        self._deleted: set[str] = set()

    def send(self, req: Request) -> Response:
        self.requests.append(req)
        parts = urllib.parse.urlsplit(req.url)
        path = parts.path
        query = dict(urllib.parse.parse_qsl(parts.query))
        host = parts.hostname or ""

        def ok(obj, status=200, headers=None):
            return Response(status, headers or {}, json.dumps(obj).encode())

        if host == "graph.facebook.com":
            node = path.rstrip("/").split("/")[-1]
            if req.method == "DELETE":
                self._deleted.add(node)
                return ok({"success": True})
            if req.method == "GET" and node in self._deleted:
                return ok({"error": {"message": "dry-run: object does not exist", "code": 100,
                                     "error_subcode": 33}}, 400)
            if path.endswith("/feed") and req.method == "POST":
                return ok({"id": "DRYRUN-page_post_id"})
            if path.endswith("/feed") or path.endswith("/published_posts"):
                return ok({"data": []})
            if path.endswith("/photos"):
                if req.fields.get("published") == "false":
                    return ok({"id": "DRYRUN-staging_photo_id"})
                return ok({"id": "DRYRUN-photo_id", "post_id": "DRYRUN-page_post_id"})
            if path.endswith("/media_publish"):
                return ok({"id": "DRYRUN-ig_media_id"})
            if path.endswith("/media"):
                return ok({"id": "DRYRUN-ig_container_id"})
            fields = query.get("fields", "")
            if fields == "images":
                return ok({"images": [{"width": 1080, "height": 1080,
                                       "source": "https://dry-run.invalid/staged.jpg"}]})
            if fields.startswith("status_code"):
                return ok({"status_code": "FINISHED"})
            if fields == "permalink":
                return ok({"permalink": "https://www.instagram.com/p/DRYRUN/"})
            return ok({"id": node})
        if host == "api.x.com":
            if path.endswith("/media/upload"):
                return ok({"data": {"id": "DRYRUN-media_id"}})
            return ok({"data": {"id": "DRYRUN-post_id"}}, 201)
        if host == "api.linkedin.com":
            if "initializeUpload" in req.url:
                return ok({"value": {"uploadUrl": "https://www.linkedin.com/dry-run-upload",
                                     "image": "urn:li:image:DRYRUN"}})
            return ok({}, 201, {"x-restli-id": "urn:li:share:DRYRUN"})
        if "linkedin.com" in host and req.method == "PUT":
            return ok({}, 201)
        return ok({})
