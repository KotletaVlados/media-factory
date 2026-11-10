"""LinkedIn personal profile: image upload, create post, one-time login (design §9.4, §10)."""

from __future__ import annotations

import datetime as _dt
import hmac
import http.server
import secrets
import time
import urllib.parse

from poster import config
from poster.context import Ctx, Result
from poster.http import (ApiError, FilePart, Request, TransportError, check, form_request,
                         json_request, UPLOAD_TIMEOUT)
from poster.rules import linkedin_escape, sniff

API = "https://api.linkedin.com"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
SCOPE = "openid profile w_member_social"   # fixed: a different scope invalidates tokens (L7)
DEFAULT_PORT = 8765
RELOGIN = "run: python3 -m poster login linkedin"


def redirect_uri(port: int) -> str:
    return f"http://localhost:{port}/callback"


def rest_headers(ctx: Ctx, token: str | None = None) -> dict:
    return {"Authorization": f"Bearer {token or ctx.env['LINKEDIN_ACCESS_TOKEN']}",
            "Linkedin-Version": ctx.settings.linkedin_version,
            "X-Restli-Protocol-Version": "2.0.0"}


def is_linkedin_host(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (host == "linkedin.com" or host.endswith(".linkedin.com"))


def post_body(author: str, commentary: str, image_urn: str | None) -> dict:
    body = {
        "author": author,
        "commentary": commentary,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                         "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if image_urn:
        body["content"] = {"media": {"id": image_urn}}
    return body


def _hint(exc: ApiError) -> str:
    text = str(exc)
    if exc.status == 401:
        text += f" — token expired or revoked; {RELOGIN}"
    return text


def initialize_upload(ctx: Ctx, owner: str, token: str | None = None):
    url = f"{API}/rest/images?action=initializeUpload"
    req = json_request("POST", url, {"initializeUploadRequest": {"owner": owner}},
                       headers=rest_headers(ctx, token))
    return ctx.send(req)


def upload_image(ctx: Ctx, path: str) -> str:
    owner = ctx.env["LINKEDIN_PERSON_URN"]
    data = check(initialize_upload(ctx, owner), "LinkedIn initializeUpload")
    value = data.get("value") or {}
    upload_url, image_urn = value.get("uploadUrl"), value.get("image")
    if not upload_url or not image_urn:
        raise ApiError(0, "LinkedIn initializeUpload: no uploadUrl or image returned")
    ctx.redactor.add("LINKEDIN_UPLOAD_URL", upload_url)
    if not is_linkedin_host(upload_url):
        raise ApiError(0, "LinkedIn uploadUrl is not an https *.linkedin.com address; "
                          "refusing to send the token there")
    info = sniff(path)
    with open(path, "rb") as fh:
        data_bytes = bytes(fh.read())
    headers = {"Authorization": f"Bearer {ctx.env['LINKEDIN_ACCESS_TOKEN']}",
               "Content-Type": info.mime}
    req = Request("PUT", upload_url, headers, data_bytes, "bytes", {},
                  [FilePart("body", path.rsplit("/", 1)[-1], info.mime, b"", info.describe())],
                  (), UPLOAD_TIMEOUT)
    check(ctx.send(req), "LinkedIn image upload")
    return str(image_urn)


def publish(variant, target, ctx: Ctx) -> Result:
    result = Result(target.id, "linkedin", "failed")
    image_urn = None
    try:
        if variant.image_path:
            image_urn = upload_image(ctx, variant.image_path)
            result.extra["image_urn"] = image_urn
        body = post_body(ctx.env["LINKEDIN_PERSON_URN"], linkedin_escape(variant.text), image_urn)
        req = json_request("POST", f"{API}/rest/posts", body, headers=rest_headers(ctx))
    except ApiError as exc:
        result.error = _hint(exc)
        return result
    except TransportError as exc:
        result.error = f"LinkedIn image upload: {exc}; nothing was posted"
        return result
    try:
        resp = ctx.send(req)
        check(resp, "LinkedIn post")
    except TransportError as exc:
        result.status = "unknown"
        result.error = (f"{exc}; the post may exist — look at the LinkedIn profile before "
                        f"re-running with --force-target {target.id}")
        return result
    except ApiError as exc:
        result.error = _hint(exc)
        if exc.uncertain:   # 5xx: LinkedIn may have created the post before failing
            result.status = "unknown"
            result.error += (f"; the post may exist — look at the LinkedIn profile before "
                             f"re-running with --force-target {target.id}")
        return result
    urn = resp.header("x-restli-id")
    if not urn:
        result.status = "unknown"
        result.error = "LinkedIn returned no x-restli-id; look at the profile"
        return result
    result.status = "published"
    result.post_id = urn
    result.url = f"https://www.linkedin.com/feed/update/{urn}/"
    return result


def token_problems(env: dict, now: _dt.datetime) -> tuple[list[str], list[str]]:
    """Pre-flight: refuse a token expiring within 10 minutes; warn under 7 days."""
    errors, warnings = [], []
    raw = env.get("LINKEDIN_TOKEN_EXPIRES_AT")
    if not raw:
        return errors, warnings
    try:
        expires = config.parse_utc(raw)
    except ValueError:
        errors.append(f"LINKEDIN_TOKEN_EXPIRES_AT is not an ISO-8601 time; {RELOGIN}")
        return errors, warnings
    left = expires - now
    if left <= _dt.timedelta(minutes=10):
        errors.append(f"LinkedIn token expired or expires within 10 minutes; {RELOGIN}")
    elif left < _dt.timedelta(days=7):
        warnings.append(f"LinkedIn token expires in {left.days} day(s) "
                        f"({config.iso_utc(expires)}); {RELOGIN}")
    return errors, warnings


# ---------------------------------------------------------------- login (§10)

def authorization_url(client_id: str, redirect: str, state: str) -> str:
    query = urllib.parse.urlencode({"response_type": "code", "client_id": client_id,
                                    "redirect_uri": redirect, "state": state, "scope": SCOPE},
                                   quote_via=urllib.parse.quote)
    return f"{AUTH_URL}?{query}"


class LoginError(Exception):
    pass


def _make_handler(box: dict):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (stdlib name)
            parts = urllib.parse.urlsplit(self.path)
            if parts.path != "/callback":
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Not found")
                return
            box["query"] = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Done, you can close this tab.".encode())

        def log_message(self, *args):  # never echo request lines (they carry the code)
            pass

    return Handler


def bind_callback(port: int, host: str = "127.0.0.1"):
    box: dict = {}
    try:
        server = http.server.HTTPServer((host, port), _make_handler(box))
    except (OSError, OverflowError):
        raise LoginError(f"port {port} on {host} is busy; pick another --port and register "
                         f"{redirect_uri(port) if port else 'that URL'} in the LinkedIn app instead") from None
    server.timeout = 0.5
    return server, box


def wait_callback(server, box: dict, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    try:
        while "query" not in box:
            if time.monotonic() >= deadline:
                raise LoginError(f"no callback within {int(timeout)} seconds; run login again")
            server.handle_request()
    finally:
        server.server_close()
    return box["query"]


def login(ctx: Ctx, env_path: str, *, port: int, timeout: float, out,
          on_auth_url=None) -> int:
    env = ctx.env
    missing = [n for n in ("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET") if not env.get(n)]
    out(f"Register this exact redirect URL in the LinkedIn app (Auth tab -> Authorized redirect "
        f"URLs): {redirect_uri(port or DEFAULT_PORT)}")
    out("LINKEDIN_CLIENT_ID: " + ("missing" if "LINKEDIN_CLIENT_ID" in missing else "present")
        + ", LINKEDIN_CLIENT_SECRET: "
        + ("missing" if "LINKEDIN_CLIENT_SECRET" in missing else "present"))
    if missing:
        out("missing " + ", ".join(missing) + " in the env file", err=True)
        return 2
    try:
        server, box = bind_callback(port)
    except LoginError as exc:
        out(str(exc), err=True)
        return 2
    actual_port = server.server_address[1]
    redirect = redirect_uri(actual_port)
    state = secrets.token_urlsafe(32)
    url = authorization_url(env["LINKEDIN_CLIENT_ID"], redirect, state)
    out("Open this link and click Allow:")
    out(url)
    ctx.redactor.add("OAUTH_STATE", state)   # shown once above; masked from here on
    if on_auth_url:
        on_auth_url(url)
    try:
        query = wait_callback(server, box, timeout)
    except LoginError as exc:
        out(str(exc), err=True)
        return 1
    if "code" in query:
        ctx.redactor.add("OAUTH_CODE", query["code"])
    if not hmac.compare_digest(query.get("state", ""), state):
        out("login refused: the callback's state does not match (possible forged request)", err=True)
        return 1
    if query.get("error"):
        out(f"LinkedIn refused the login: {query.get('error')}: "
            f"{query.get('error_description', '')}", err=True)
        return 1
    code = query.get("code")
    if not code:
        out("login failed: the callback carried no code", err=True)
        return 1

    try:
        data = check(ctx.send(form_request("POST", TOKEN_URL, {
            "grant_type": "authorization_code", "code": code,
            "client_id": env["LINKEDIN_CLIENT_ID"], "client_secret": env["LINKEDIN_CLIENT_SECRET"],
            "redirect_uri": redirect}, secret_fields=("code", "client_secret"))),
            "LinkedIn token exchange")
        token = data.get("access_token")
        if not token:
            raise ApiError(0, "LinkedIn token exchange: no access_token returned")
        ctx.redactor.add("LINKEDIN_ACCESS_TOKEN", token)
        expires_in = int(data.get("expires_in") or 0)
        if not 0 < expires_in <= 10 * 365 * 86400:
            raise ApiError(0, "LinkedIn token exchange: no usable expires_in returned")
        info = check(ctx.send(Request("GET", USERINFO_URL, {"Authorization": f"Bearer {token}"})),
                     "LinkedIn userinfo")
        sub = info.get("sub")
        if not sub:
            raise ApiError(0, "LinkedIn userinfo: no sub returned")
    except (ApiError, TransportError, ValueError, TypeError, OverflowError) as exc:
        out(f"login failed: {exc}", err=True)
        return 1
    person = f"urn:li:person:{sub}"
    expires = ctx.clock() + _dt.timedelta(seconds=expires_in)

    try:
        probe = initialize_upload(ctx, person, token)
        if probe.ok:
            out("versioned Posts API reachable (probe created an unused upload slot; "
                "nothing was published)")
        elif probe.status == 403:
            out("warning: /rest/images answered 403 for this token; the versioned Posts API "
                "may need another product — the ugcPosts fallback is deferred (design §17)",
                err=True)
        else:
            out(f"warning: access probe answered {probe.status}; posting may fail", err=True)
    except TransportError as exc:
        out(f"warning: access probe failed: {exc}", err=True)

    config.write_back(env_path, {"LINKEDIN_ACCESS_TOKEN": token,
                                 "LINKEDIN_TOKEN_EXPIRES_AT": config.iso_utc(expires),
                                 "LINKEDIN_PERSON_URN": person})
    out(f"LinkedIn connected; token valid until {config.iso_utc(expires)} "
        f"({expires_in // 86400} days)")
    return 0
