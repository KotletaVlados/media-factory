"""Visual check of the panel (design factory.md §13.3 items 4 and 5; panel brief §5).

    python3 tools/visual_check.py --out DIR [--widths 390,900,1000,1100,1200,1279,1280,1440,1600,1920] [--only TEXT]

It builds the data, empty and error fixtures under DIR/fixture, starts one panel per fixture
on 127.0.0.1 port 0 (in this process, frozen clock, nothing publishes), and for each tab and
state at each width:

- saves a viewport PNG and a whole-page PNG with the cached chrome-headless-shell
  (`--screenshot`), as DIR/<state>-<width>.png and DIR/<state>-<width>-full.png;
- runs `--dump-dom --virtual-time-budget=2000` on the same URL with `?probe=1` and reads the
  probe's JSON (text cut by its box, elements wider than the viewport, anchors under the
  sticky bar, overlapping controls, targets under 24 x 24, a page-level error banner whose
  text is not on the first screen, a Files preview strip wider than its card or off-centre in
  it, a Rules unit word detached from its number, a Connection detail whose heading and first
  line are below the first screen after a ring-node link, and an expander whose form top lands
  outside the viewport when it opens with its summary 40 px above the bottom edge).

The photo states (authoring.md §15.1) run on a fourth fixture with 70 uploaded photos: the
probe feeds the stored EXIF-6 original, fetched from /photo, to author.js's `makeCopies` and
reports the copy sizes, which must be portrait. `files-photos-upload` runs on a fifth, small
fixture that the upload loop may change: it decodes a stored 1 x 1 WebP, then runs the real
loop four times. Run 1 sends a duplicate, a HEIC file, a text file, an undecodable .jpg, a
file the server refuses and one new decodable file (three of them with a folder-relative
path); the check compares the counts, the status line (counts only, no reason text and the
button named "показать загруженные"), the skip list (each folder once, "name: reason" rows),
and afterwards the fixture's index, thumb and view files (two new rows per width, named after
the file). Run 2 is a clean run of one new file: the page reload is stubbed, the kept count
must come back as the done line. Runs 3 and 4 stub fetch (no connection, then a stale-token
403) and must stop after one request; the buttons must look disabled while the first waits.

The authoring states (authoring.md §16) are judged on the unscrolled first screen, except the two anchor
states that load with #texts; `create-behaviour` drives the browser behaviour of acceptance items 6, 7
and 9 against FakeGemini (card tap, 800 ms autosave of the topic box and a text card, the empty box,
the four microphone refusals, the 2:00 auto-stop on a faked clock, a 503 on the first transcription and
a retry that must send the same bytes, which the run also compares on the Gemini side); `create-autoretry`
fails the automatic topics request with a 503, clicks «Повторить» and needs a second topics request at
Gemini, 3–5 cards and an empty draft error; `create-expand-texts` taps the last card, waits for «сохранено»,
clicks «Развернуть» and fails if the box or the button is off screen (or against the window edge) after the
tap, or «Тексты» or the first card's editor is off screen once the texts arrive.
`create-texts` also fails when the whole «пожелание…» hint of a text card does not fit its field
(widths 1000, 1100, 1200 and 1279 are in the default set for this).

The send states (authoring.md §17.6) run on four more fixtures: «send» (static drafts in every
state; at start the check posts one publish, which a FakePoster holds until teardown, and queues
two drafts, the second with the offered rule, whose 409 Rules page is saved as `rule-refused`),
«send-problems», «send-crash» and «send-live» (a draft per width for the canvas crops and for the
focus tap). Every publish goes to the in-process FakePoster: the real poster with a scripted
transport, so nothing leaves the machine. The probe checks each state's defining text on the
first screen, the dialogs (a double click on the opener, focus inside, a click behind, «Отмена»;
Tab and Escape are then pressed over DevTools), the crop sizes and windows, and the focus tap;
afterwards the stored crops, the focus and the one publish call are checked here.

The image states (authoring.md §18.6) run on three «images» fixtures (static drafts; one with the
AI month at $9.99, one without the key) and «images-live» (a draft per state and width, each on its
own panel so a held Gemini call takes no other state's slot). States that reload the page run in
stages over one DevTools session: the probe names the next URL (MFProbeNext), the check opens it in
the same tab, and only the last stage writes the JSON (`review-template`, `review-highlight*`,
`review-base`). Afterwards the stored crops, style files, draft errors and the static fixtures'
unchanged files are checked here.

It also computes the WCAG contrast of every text colour pair from panel.css. It prints the
snapshot build time (`snapshot_ms`, budget 1000 ms) and exits 1 on any finding.

Chrome: MF_CHROME, default the newest
~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell.
MF_CHROME_LIBS adds a library folder (for machines missing libnspr4, libnss3 or libasound).
Chrome's own TMPDIR, HOME and profile live in a short folder under DIR (its socket path limit
is about 107 characters).
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import glob
import hashlib
import html
import http.client
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse

sys.dont_write_bytecode = True

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from factory.authoring import photos as fphotos  # noqa: E402
from factory.panel import server  # noqa: E402
from factory.panel import strings as S  # noqa: E402
from tests import panel_fixture  # noqa: E402

WIDTHS = {390: 844, 900: 900, 1000: 700, 1100: 700, 1200: 800, 1279: 800, 1280: 800, 1440: 900, 1600: 900, 1920: 1080}
LONG_TITLE = "Фотографии с городских прогулок"
ELLIPSIS_STATES = ("files", "rules")   # the Files card and the Rules source card clamp it
BUDGET_MS = 1000
FULL_MAX = 7000
CSS = os.path.join(REPO, "factory", "panel", "static", "panel.css")
TEXT_PAIRS = [
    ("--text", "--app"), ("--text", "--surface"), ("--text", "--surface-2"), ("--text", "--head"),
    ("--text", "--tab-active"), ("--text", "--hour-on-bg"),
    ("--muted", "--app"), ("--muted", "--surface"), ("--muted", "--surface-2"), ("--muted", "--head"),
    ("--green", "--app"), ("--green", "--surface"), ("--green", "--surface-2"),
    ("--green", "--day-on-bg"), ("--on-green", "--green"), ("--on-green", "--red"),
    ("--red", "--app"), ("--red", "--surface"), ("--red", "--surface-2"),
    ("--day-on", "--day-on-bg"), ("--hour-on", "--surface"), ("--hour-on", "--surface-2"),
    ("--lane-photo", "--surface"), ("--lane-photo", "--surface-2"), ("--lane-text", "--surface-2"),
] + [(f"--n-{n}", "--head") for n in ("fb", "ig", "x", "in", "tg", "th", "yt", "tt", "pi")]


# ---------------------------------------------------------------- contrast (WCAG 2.x)

def _lum(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def check_contrast(css_text: str) -> list:
    tokens = dict(re.findall(r"(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", css_text))
    out = []
    for fg, bg in TEXT_PAIRS:
        ratio = contrast(tokens[fg], tokens[bg])
        out.append((fg, bg, ratio))
    return out


# ---------------------------------------------------------------- chrome

def find_chrome() -> str:
    if os.environ.get("MF_CHROME"):
        return os.environ["MF_CHROME"]
    pattern = os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-*/"
                                 "chrome-headless-shell-linux64/chrome-headless-shell")
    found = sorted(glob.glob(pattern), key=lambda p: int(re.search(r"-(\d+)/", p).group(1)))
    if not found:
        sys.exit("no chrome-headless-shell found; set MF_CHROME")
    return found[-1]


class Chrome:
    def __init__(self, binary: str, scratch: str):
        self.binary, self.scratch = binary, scratch
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                    "HOME": os.path.join(scratch, "home"), "TMPDIR": scratch}
        libs = os.environ.get("MF_CHROME_LIBS")
        if libs:
            self.env["LD_LIBRARY_PATH"] = libs
        os.makedirs(self.env["HOME"], exist_ok=True)
        self._n = 0
        self._lock = threading.Lock()

    def _profile(self) -> str:
        with self._lock:
            self._n += 1
            return os.path.join(self.scratch, f"p{self._n}")

    def run(self, args: list, timeout: int = 60) -> subprocess.CompletedProcess:
        profile = self._profile()
        cmd = [self.binary, "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
               "--force-device-scale-factor=1", "--no-first-run", "--mute-audio",
               "--disable-extensions", f"--user-data-dir={profile}"] + args
        try:
            return subprocess.run(cmd, env=self.env, capture_output=True, timeout=timeout)
        finally:
            shutil.rmtree(profile, ignore_errors=True)

    def screenshot(self, url: str, out: str, w: int, h: int) -> None:
        r = self.run([f"--window-size={w},{h}", "--virtual-time-budget=2000",
                      f"--screenshot={out}", url])
        if not os.path.exists(out):
            raise RuntimeError(f"screenshot failed for {url}: {r.stderr.decode()[-400:]}")

    def live(self, url: str, w: int, h: int, png: str, full_png: str | None) -> dict:
        """Real time over the DevTools pipe, for pages whose probe waits on the browser's own
        async image work (createImageBitmap, toBlob), which does not run on virtual time:
        load `url` (with probe=1), wait for the probe's JSON, then wait for the images on
        screen and save the viewport PNG, and the whole-page PNG when the page is taller."""
        with Live(self, url, w, h) as page:
            raw = page.wait_value("(function () { var p = document.getElementById('probe');"
                                  " return p ? p.textContent : null; })()", 60)
            result = json.loads(raw)
            page.screenshot(png)
            if "probe_create=create-voice" in url:
                result["author_voice"] = page.evaluate("window.MFProbeVoiceFinish()", await_promise=True)
            if "probe_send=review-confirm" in url or "probe_send=review-delete" in url:
                result["keyboard"] = page.keyboard_in_dialog()
            full_h = min(max(h, int(result.get("height", h))), FULL_MAX)
            if full_png and full_h > h:
                page.send("Emulation.setDeviceMetricsOverride", {
                    "width": w, "height": full_h, "deviceScaleFactor": 1, "mobile": False})
                page.screenshot(full_png)
        return result

    def staged(self, url: str, w: int, h: int, png: str, full_png: str | None) -> dict:
        """Real time over DevTools for a state the probe runs in stages (§18.6): each stage
        but the last sets MFProbeNext, which is opened in the same tab; the last writes the
        JSON. Earlier stages' probe results are kept under "stages"."""
        stages, current = [], url
        with Live(self, url, w, h) as page:
            for _ in range(4):
                want = urllib.parse.parse_qs(urllib.parse.urlsplit(current).query).get("probe_send", [""])[0]
                expr = ("(function () { if (new URLSearchParams(location.search).get('probe_send') !== %s) { return null; }"
                        " if (window.MFProbeNext) { return JSON.stringify({next: window.MFProbeNext, stage: window.MFProbeSend || null}); }"
                        " var p = document.getElementById('probe'); return p ? JSON.stringify({done: p.textContent}) : null; })()"
                        % json.dumps(want))
                value = page.poll(expr, 150)
                if "done" in value:
                    result = json.loads(value["done"])
                    break
                stages.append(value["stage"])
                current = urllib.parse.urljoin(current, value["next"])
                page.send("Page.navigate", {"url": current})
            else:
                raise RuntimeError(f"{url}: more than four stages")
            result["stages"] = stages
            page.screenshot(png)
            full_h = min(max(h, int(result.get("height", h))), FULL_MAX)
            if full_png and full_h > h:
                page.send("Emulation.setDeviceMetricsOverride", {
                    "width": w, "height": full_h, "deviceScaleFactor": 1, "mobile": False})
                page.screenshot(full_png)
        return result

    def probe(self, url: str, w: int, h: int) -> dict:
        r = self.run([f"--window-size={w},{h}", "--virtual-time-budget=2000", "--dump-dom", url])
        m = re.search(r'<pre id="probe">(.*?)</pre>', r.stdout.decode("utf-8", "replace"), re.S)
        if not m:
            raise RuntimeError(f"no probe output for {url}: {r.stderr.decode()[-400:]}")
        return json.loads(html.unescape(m.group(1)))


# the browser reads DevTools commands on fd 3 and writes replies on fd 4
DUP_EXEC = ("import os, sys; os.dup2(int(os.environ['MF_CDP_IN']), 3); "
            "os.dup2(int(os.environ['MF_CDP_OUT']), 4); os.execv(sys.argv[1], sys.argv[1:])")


class Live:
    """A minimal DevTools-protocol client over --remote-debugging-pipe (fd 3 in, fd 4 out,
    NUL-terminated JSON), standard library only."""

    def __init__(self, chrome: Chrome, url: str, w: int, h: int):
        self.chrome, self.url, self.w, self.h = chrome, url, w, h
        self.n = 0
        self.buf = b""

    def __enter__(self):
        self.profile = self.chrome._profile()
        cmd_r, self.cmd_w = os.pipe()
        self.out_r, out_w = os.pipe()
        env = dict(self.chrome.env, MF_CDP_IN=str(cmd_r), MF_CDP_OUT=str(out_w))
        self.proc = subprocess.Popen(
            [sys.executable, "-I", "-c", DUP_EXEC, self.chrome.binary, "--no-sandbox",
             "--disable-gpu", "--hide-scrollbars", "--autoplay-policy=no-user-gesture-required",
             "--force-device-scale-factor=1", "--no-first-run", "--mute-audio",
             "--disable-extensions", f"--user-data-dir={self.profile}",
             "--remote-debugging-pipe", f"--window-size={self.w},{self.h}", "about:blank"],
            env=env, pass_fds=(cmd_r, out_w), stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        os.close(cmd_r)
        os.close(out_w)
        target = next(t for t in self.send("Target.getTargets")["targetInfos"]
                      if t["type"] == "page")
        self.session = self.send("Target.attachToTarget", {"targetId": target["targetId"],
                                                           "flatten": True})["sessionId"]
        self.send("Emulation.setDeviceMetricsOverride", {
            "width": self.w, "height": self.h, "deviceScaleFactor": 1, "mobile": False})
        self.send("Page.navigate", {"url": self.url})
        return self

    def __exit__(self, *exc):
        try:
            self.send("Browser.close", session=False, timeout=10)
        except (RuntimeError, OSError):
            pass
        try:
            self.proc.wait(15)
        except subprocess.TimeoutExpired:
            self.proc.kill()      # the browser this object started, by its own handle
            self.proc.wait(10)
        os.close(self.cmd_w)
        os.close(self.out_r)
        shutil.rmtree(self.profile, ignore_errors=True)

    def send(self, method: str, params: dict | None = None, session=True, timeout: float = 30):
        import select
        self.n += 1
        msg = {"id": self.n, "method": method, "params": params or {}}
        if session and getattr(self, "session", None):
            msg["sessionId"] = self.session
        os.write(self.cmd_w, json.dumps(msg).encode() + b"\0")
        deadline = time.monotonic() + timeout
        while True:
            while b"\0" not in self.buf:
                left = deadline - time.monotonic()
                if left <= 0 or not select.select([self.out_r], [], [], left)[0]:
                    raise RuntimeError(f"no DevTools answer to {method} within {timeout} s")
                chunk = os.read(self.out_r, 1 << 16)
                if not chunk:
                    raise RuntimeError(f"browser closed the DevTools pipe during {method}")
                self.buf += chunk
            raw, self.buf = self.buf.split(b"\0", 1)
            reply = json.loads(raw)
            if reply.get("id") == self.n:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error']}")
                return reply.get("result", {})

    def evaluate(self, expression: str, await_promise: bool = False):
        r = self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                           "awaitPromise": await_promise}, timeout=60)
        if "exceptionDetails" in r:
            detail = r["exceptionDetails"]
            raise RuntimeError(detail.get("exception", {}).get("description", detail.get("text", "browser error")))
        return r.get("result", {}).get("value")

    def wait_value(self, expression: str, timeout: float):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.evaluate(expression)
            if value is not None:
                return value
            time.sleep(0.2)
        raise RuntimeError(f"no probe output for {self.url} within {timeout} s")

    def poll(self, expression: str, timeout: float) -> dict:
        """Like wait_value across navigations: an evaluation that meets a document being
        replaced is tried again until the deadline. Returns the parsed JSON value."""
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            try:
                value = self.evaluate(expression)
            except RuntimeError as exc:
                value, last = None, str(exc)
            if value is not None:
                return json.loads(value)
            time.sleep(0.25)
        raise RuntimeError(f"no probe stage for {self.url} within {timeout} s {last}")

    def key(self, key: str, code: int) -> None:
        for kind in ("keyDown", "keyUp"):
            self.send("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": key,
                                                 "windowsVirtualKeyCode": code})

    def keyboard_in_dialog(self) -> dict:
        """Real Tab presses never reach the page behind the open modal dialog; Escape closes it;
        no form was submitted (authoring.md §17.5 item 7). Each stop is "dialog", "browser"
        (Chrome lets Tab leave a modal dialog for its own UI: the document then has no focused
        element) or "page:<tag>" (a focus behind the dialog, a finding)."""
        inside = []
        for _ in range(6):
            self.key("Tab", 9)
            inside.append(self.evaluate(
                "(function () { var a = document.activeElement;"
                " if (!a || a === document.body || a === document.documentElement) { return 'browser'; }"
                " return a.closest('dialog[open]') ? 'dialog' : 'page:' + a.tagName.toLowerCase(); })()"))
        self.key("Escape", 27)
        time.sleep(0.2)
        return {"tabs": inside, "closed": self.evaluate("!document.querySelector('dialog[open]')"),
                "submits": self.evaluate("window.MFProbeSubmits ? window.MFProbeSubmits() : -1")}

    def click(self, selector: str) -> None:
        """A real mouse click at the centre of the element (a native form submit follows, with
        the Origin and cookies Chrome itself sends)."""
        # a tile that decodes after the click point is measured moves the target: wait for the images
        self.wait_true("Array.prototype.every.call(document.images, function (i) { return i.complete; })",
                       30, "the images")
        box = self.evaluate("(function () { var e = document.querySelector(%s); if (!e) { return null; }"
                            " e.scrollIntoView({block: 'center'}); var r = e.getBoundingClientRect();"
                            " return [r.left + r.width / 2, r.top + r.height / 2]; })()" % json.dumps(selector))
        if not box:
            raise RuntimeError(f"nothing to click: {selector}")
        for kind in ("mousePressed", "mouseReleased"):
            self.send("Input.dispatchMouseEvent", {"type": kind, "x": box[0], "y": box[1],
                                                   "button": "left", "clickCount": 1})

    def wait_true(self, expression: str, timeout: float, what: str):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.evaluate(f"({expression}) ? true : null"):
                return
            time.sleep(0.2)
        raise RuntimeError(f"timed out waiting for {what}: {self.evaluate('location.href + \" | \" + document.body.innerText.slice(0, 200)')}")

    def screenshot(self, out: str) -> None:
        # every image inside the viewport has loaded (lazy tiles included) before the capture
        self.evaluate("Promise.all(Array.prototype.filter.call(document.images, function (i) {"
                      " var r = i.getBoundingClientRect();"
                      " return !i.complete && r.bottom > 0 && r.top < innerHeight; })"
                      ".map(function (i) { return new Promise(function (ok) {"
                      " i.addEventListener('load', ok); i.addEventListener('error', ok); }); }))"
                      ".then(function () { return true; })", await_promise=True)
        data = self.send("Page.captureScreenshot", {"format": "png"}, timeout=60)["data"]
        with open(out, "wb") as fh:
            fh.write(base64.b64decode(data))


# ---------------------------------------------------------------- states

def with_probe(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    query = parts.query + ("&" if parts.query else "") + "probe=1"
    return urllib.parse.urlunsplit(parts._replace(query=query))


def start(fixture, ai_transport=None, publish=None):
    srv = server.make_server(fixture.paths, fixture.clock, fixture.machine_tz, 0,
                             log=io.StringIO(), ai_transport=ai_transport or panel_fixture.FakeGemini(),
                             publish=publish or panel_fixture.FakePoster())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def post_page(srv, path: str, fields: dict, out_file: str) -> str:
    """POST a form and save the answer (with a <base> to the server) as a local file."""
    host = f"127.0.0.1:{srv.port}"
    body = urllib.parse.urlencode(dict(fields, csrf=srv.panel.csrf))
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    conn.request("POST", path, body=body, headers={
        "Host": host, "Content-Type": "application/x-www-form-urlencoded"})
    resp = conn.getresponse()
    page = resp.read().decode("utf-8")
    conn.close()
    page = page.replace("<head>", f'<head>\n<base href="http://{host}/">', 1)
    with open(out_file, "w", encoding="utf-8") as fh:
        fh.write(page)
    return resp.status


def form_values(srv, path: str) -> dict:
    """GET a page and read its hidden form values (csrf, seen) as the browser would post them."""
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    conn.request("GET", path, headers={"Host": f"127.0.0.1:{srv.port}"})
    page = conn.getresponse().read().decode("utf-8")
    conn.close()
    seen = re.search(r'name="seen" value="([0-9a-f]*)"', page)
    return {"seen": seen.group(1) if seen else ""}


def post_form(srv, path: str, fields: dict) -> int:
    host = f"127.0.0.1:{srv.port}"
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
    conn.request("POST", path, body=urllib.parse.urlencode(dict(fields, csrf=srv.panel.csrf)),
                 headers={"Host": host, "Content-Type": "application/x-www-form-urlencoded"})
    resp = conn.getresponse()
    resp.read()
    conn.close()
    return resp.status


D19 = {"facebook": [1536, 2048], "instagram": [1080, 1350], "linkedin": [1536, 2048], "x": [1600, 900]}
D19_SMALL = {"facebook": [320, 240], "instagram": [192, 240], "linkedin": [320, 240], "x": [320, 180]}
SEND_STATES = ("send-draft", "review", "review-rule", "review-problems", "review-crops", "review-focus",
               "review-confirm", "review-publishing", "review-partial", "review-published",
               "review-interrupted", "review-delete", "queued", "rule-refused", "send-start")


def send_problems(state, result) -> list:
    """The send probe's own problems plus the facts this state must report (§17.6)."""
    s = result.get("send") or {}
    out = list(s.get("problems", [])) if s else ["no send probe result"]
    for look in s.get("busy", []):
        if not look["disabled"] or float(look["opacity"]) >= 1 or look["cursor"] == "pointer" or look["width"] < 60:
            out.append(f"a blocked button looks enabled or lost its width: {look}")
    if state == "review-crops":
        sizes = {c["network"]: [c["width"], c["height"]] for c in s.get("crops") or []}
        if sizes != D19:
            out.append(f"crop sizes {sizes}, expected {D19}")
        x = next((c for c in s.get("crops") or [] if c["network"] == "x"), {})
        if x.get("window") != [0, 1166, 3024, 1701]:
            out.append(f"X window {x.get('window')}, expected [0, 1166, 3024, 1701]")
        if (s.get("posts"), s.get("reloads")) != (4, 1):
            out.append(f"posts/reloads {s.get('posts')}/{s.get('reloads')}, expected 4/1")
        exif = s.get("exif") or {}
        if exif.get("decoded") != [3024, 4032] or {n: exif.get(n) for n in D19} != D19:
            out.append(f"EXIF-6 original 4032 x 3024 gave {exif}, expected portrait {D19}")
        small = s.get("small") or {}
        if {n: small.get(n) for n in D19_SMALL} != D19_SMALL:
            out.append(f"320 x 240 original gave {small}, expected {D19_SMALL} (no upscale)")
    if state == "review-focus":
        f = s.get("focus") or {}
        before, after = f.get("before") or {}, f.get("after") or {}
        for n in ("instagram", "x"):
            if not before.get(n) or before.get(n) == after.get(n):
                out.append(f"the {n} crop did not change after the tap")
        x = next((c for c in f.get("crops") or [] if c["network"] == "x"), {})
        if x.get("window") != [0, 0, 3024, 1701] or f.get("reloads") != 2:
            out.append(f"after the tap: X window {x.get('window')}, reloads {f.get('reloads')}")
    if state in ("review-confirm", "review-delete"):
        k = result.get("keyboard") or {}
        tabs = k.get("tabs") or []
        if (any(t.startswith("page") for t in tabs) or tabs.count("dialog") < 2 or k.get("closed") is not True
                or k.get("submits") != 0):
            out.append(f"keyboard in the dialog: {k} (Tab must stay inside, Escape must close, nothing posted)")
    return out


IMAGE_STATES = ("review-styles-empty", "review-styles", "review-based", "review-template", "review-ratio",
                "review-highlight-loading", "review-highlight", "review-highlight-text", "review-highlight-402",
                "create-error-402", "review-base", "review-styles-budget", "review-styles-nokey")
# the live states and the draft each changes (panel_fixture.IMAGE_LIVE)
IMAGE_LIVE_STATE = {"review-template": "tpl", "review-ratio": "ratio", "review-highlight-loading": "hold",
                    "review-highlight": "hl", "review-highlight-text": "text", "review-highlight-402": "e402",
                    "review-base": "base", "create-error-402": "x402"}
TPL_SIZES = {"instagram": [1080, 1080], "x": [1600, 1600], "linkedin": [1910, 1000], "facebook": [2048, 1152]}
STYLED = {"facebook": [1536, 2048], "instagram": [1080, 1350], "linkedin": [1536, 2048], "x": [1536, 864]}
LINE_402 = ("Не удалось получить {what} от Gemini (HTTP 402): закончились предоплаченные кредиты Gemini — "
            "пополните баланс в Google AI Studio")


def image_problems(state, result) -> list:
    """The image probe's own problems from every stage, plus this state's facts (§18.6)."""
    stages = [x for x in (result.get("stages") or []) if x] + [result.get("send") or {}]
    out = []
    for stage in stages:
        out.extend(stage.get("problems", []))
    if not result.get("send"):
        out.append("no image probe result")
    first = stages[0]
    if state == "review-template":
        sizes = {c["network"]: [c["width"], c["height"]] for c in first.get("crops") or []}
        if sizes != TPL_SIZES:
            out.append(f"template crops {sizes}, expected {TPL_SIZES}")
        if first.get("sweep") != 13 * 4 * 3:
            out.append(f"layout sweep covered {first.get('sweep')} layouts, expected 156")
        if first.get("posts") != [200] * 4:
            out.append(f"template crop posts {first.get('posts')}, expected four 200s")
    if state == "review-ratio" and len(first.get("ratio") or []) != 13:
        out.append(f"ratio choices made {len(first.get('ratio') or [])}, expected 13")
    if state == "review-highlight-loading" and not first.get("busy"):
        out.append("no blocked controls measured while the call runs")
    if state == "review-highlight" and first.get("calls") != [200]:
        out.append(f"highlight calls {first.get('calls')}, expected one 200")
    if state in ("review-highlight-text", "review-highlight-402") and first.get("calls") != [502]:
        out.append(f"highlight calls {first.get('calls')}, expected one 502")
    if state == "review-base":
        if first.get("settings") != [200] or len(stages) < 3 or stages[1].get("posts") != [200] * 4:
            out.append(f"base switch: settings {first.get('settings')}, crop posts "
                       f"{stages[1].get('posts') if len(stages) > 1 else None}")
    return out


def content_hashes(fx) -> dict:
    out = {}
    for dirpath, _, files in os.walk(fx.paths.content):
        for f in files:
            path = os.path.join(dirpath, f)
            with open(path, "rb") as fh:
                out[os.path.relpath(path, fx.paths.content)] = hashlib.sha256(fh.read()).hexdigest()
    return out


def image_after(fx, widths, ran, fake, static: dict) -> list:
    """After the run: what the live image states stored (crops, style files, errors, the
    ledger's view of each call), and that no GET changed the static fixtures (§18.5 item 11)."""
    from factory.authoring import common, drafts
    from poster import rules as prules
    out = []
    store = drafts.Store(fx.paths.content, fx.clock, fx.machine_tz)

    def crops(did, want, label):
        folder = os.path.join(fx.paths.content, "drafts", did, "out")
        for n, size in want.items():
            path = os.path.join(folder, f"{n}.jpg")
            if not os.path.isfile(path):
                out.append(f"{label}: no {n} crop stored")
                continue
            info = prules.sniff(path)
            with open(path, "rb") as fh:
                data = fh.read()
            if [info.width, info.height] != size or info.format != "jpeg" or common.jpeg_exif(data) != "ok" \
                    or prules.check_image(n, info).errors:
                out.append(f"{label}: {n} is {info.describe()}, expected a {size} JPEG the poster accepts")
    for w in widths:
        ids = {k: fx.image_ids[f"{k}-{w}"] for k in ("tpl", "ratio", "hold", "hl", "text", "e402", "base", "x402")}
        if "review-template" in ran:
            crops(ids["tpl"], TPL_SIZES, f"tpl-{w}")
        if "review-base" in ran:
            crops(ids["base"], STYLED, f"base-{w}")
            if store.load(ids["base"]).get("base") != "blur":
                out.append(f"base-{w}: the base is not «blur»")
        if "review-highlight" in ran:
            if not os.path.isfile(os.path.join(fx.paths.content, "drafts", ids["hl"], "img", "blur.jpg")):
                out.append(f"hl-{w}: no img/blur.jpg")
        if "review-highlight-text" in ran:
            err = store.load(ids["text"]).get("highlight_error") or {}
            if err.get("text") != "Gemini не вернул картинку" or not err.get("model_text"):
                out.append(f"text-{w}: stored {err}")
        if "review-highlight-402" in ran:
            err = store.load(ids["e402"]).get("highlight_error") or {}
            if err.get("text") != LINE_402.format(what="картинку"):
                out.append(f"e402-{w}: stored {err}")
        if "create-error-402" in ran:
            err = store.load(ids["x402"]).get("error") or {}
            if err.get("text") != LINE_402.format(what="тексты"):
                out.append(f"x402-{w}: stored {err}")
        for kind in ("hl", "text", "e402", "hold"):
            state = {"hl": "review-highlight", "text": "review-highlight-text", "e402": "review-highlight-402",
                     "hold": "review-highlight-loading"}[kind]
            n = sum(1 for r in fake.requests if r.fields.get("draft") == ids[kind])
            if state in ran and n != 1:
                out.append(f"{kind}-{w}: {n} Gemini requests, expected 1")
    for name, (sfx, before) in static.items():
        if content_hashes(sfx) != before:
            out.append(f"the {name} fixture changed during its GET-only states")
    return out


def submit_problems(chrome, fx, srv, widths, out) -> list:
    """The two forms an operator presses first, submitted by the browser itself at each width:
    «Да, опубликовать» must land on the review page's status block and reach «Опубликовано во всех
    4 сетях», and «В очередь» must land on /files#pkg-<id> with the package listed. A refusal
    (the bare 403 of a foreign or `null` Origin) shows as the page that was reached. Serial, since
    one publish runs at a time."""
    problems = []
    for w in widths:
        h = WIDTHS.get(w, 900)
        did = fx.send_ids[f"publish-{w}"]
        review = f"http://127.0.0.1:{srv.port}/create/{did}/review"
        try:
            with Live(chrome, review, w, h) as page:
                page.wait_true("document.querySelector('[data-open=dlg-publish]')", 30, "the review page")
                for attempt in range(3):   # a click that lands on a shifting layout is tried again
                    page.click("[data-open=dlg-publish]")
                    try:
                        page.wait_true("document.querySelector('dialog[open] [data-confirm]')", 5, "the dialog")
                        break
                    except RuntimeError:
                        if attempt == 2:
                            raise
                time.sleep(0.6)   # the 400 ms guard against the second click of a double click
                page.click("dialog[open] [data-confirm]")
                page.wait_true(f"location.pathname === '/create/{did}/review' && document.querySelector('.send-status')",
                               30, "the status block")
                page.wait_true("document.querySelector('.send-status-line') && "
                               "/Опубликовано во всех 4 сетях/.test(document.querySelector('.send-status-line').textContent)",
                               30, "«Опубликовано во всех 4 сетях»")
                page.screenshot(os.path.join(out, f"submit-publish-{w}.png"))
        except RuntimeError as exc:
            problems.append(f"submit-publish-{w}: {exc}")
        did = fx.send_ids[f"queue-{w}"]
        review = f"http://127.0.0.1:{srv.port}/create/{did}/review"
        try:
            with Live(chrome, review, w, h) as page:
                page.wait_true("document.querySelector('button[form=send-queue]:not([disabled])')", 30, "the review page")
                for attempt in range(3):
                    page.click("button[form=send-queue]")
                    try:
                        page.wait_true("location.pathname === '/files'", 8, "the Files page")
                        break
                    except RuntimeError:
                        if attempt == 2:
                            raise
                # the landing says what was queued on its first screen: the line is whole in the window
                page.wait_true(f"location.pathname === '/files' && location.search.includes('queued={did}') && location.hash === '#pkg-{did}' && "
                               f"document.getElementById('pkg-{did}') && (() => {{ "
                               f"const r = document.querySelector('.queued-line')?.getBoundingClientRect(); "
                               f"return !!r && r.top >= 0 && r.bottom <= innerHeight; }})()",
                               30, "the queued line on /files")
                page.screenshot(os.path.join(out, f"submit-queue-{w}.png"))
        except RuntimeError as exc:
            problems.append(f"submit-queue-{w}: {exc}")
    return problems


def send_after(fx, widths, before: dict, fake, kinds) -> list:
    """After the run: the canvas crops stored by the page (`kinds` names the live states that
    ran: crops, focus), the focus tap, and the one publish of the send fixture."""
    from factory.authoring import common, drafts
    from poster import rules as prules
    out = []
    store = drafts.Store(fx.paths.content, fx.clock, fx.machine_tz)
    for w in widths:
        for kind in kinds:
            did = fx.send_ids[f"{kind}-{w}"]
            folder = os.path.join(fx.paths.content, "drafts", did, "out")
            for n, size in D19.items():
                path = os.path.join(folder, f"{n}.jpg")
                if not os.path.isfile(path):
                    out.append(f"{kind}-{w}: no {n} crop stored")
                    continue
                info = prules.sniff(path)
                with open(path, "rb") as fh:
                    data = fh.read()
                if [info.width, info.height] != size or info.format != "jpeg" or common.jpeg_exif(data) != "ok" \
                        or prules.check_image(n, info).errors:
                    out.append(f"{kind}-{w}: {n} is {info.describe()}, expected a {size} JPEG the poster accepts")
                if kind == "focus" and n in ("facebook", "linkedin") and os.stat(path).st_mtime_ns != before[(did, n)]:
                    out.append(f"focus-{w}: the {n} crop changed on the tap")
            focus = store.load(did).get("focus") or [9, 9]
            if kind == "focus" and (abs(focus[0] - 0.5) > 0.01 or abs(focus[1] - 0.2) > 0.01):
                out.append(f"focus-{w}: stored focus {focus}, expected the tapped point, about [0.5, 0.2]")
    if len(fake.calls) != 1:
        out.append(f"the send fixture's poster was called {len(fake.calls)} times, expected once")
    return out


UPLOAD_RUN1 = "Готово: загружено 2 из 6 · уже были: 1 · пропущено 4"
HEIC_PATH = "Поездка/Набережная/IMG_0002.HEIC"
BROKEN_PATH = "Поездка/Набережная/broken.jpg"
NOTES_PATH = "Поездка/notes.txt"
UPLOAD_SKIPS = sorted([
    [HEIC_PATH, S.UPLOAD_JS["heic"]],
    [NOTES_PATH, S.UPLOAD_JS["type"]],
    [BROKEN_PATH, S.UPLOAD_JS["decode"]],
    ["refused.jpg", S.UP_BAD_TYPE]])
# the skip list as rendered: each folder once as a heading, base names, "name: reason" rows
UPLOAD_LIST = [   # groups in the order the loop meets them: the sorted pick, filter skips first
    ["Поездка/", [f"notes.txt: {S.UPLOAD_JS['type']}"]],
    ["Поездка/Набережная/", [f"IMG_0002.HEIC: {S.UPLOAD_JS['heic']}",
                              f"broken.jpg: {S.UPLOAD_JS['decode']}"]],
    ["", [f"refused.jpg: {S.UP_BAD_TYPE}"]]]
UPLOAD_STOPS = (("offline", S.UPLOAD_JS["network"], "a.jpg", 1),
                ("forbidden", "stale", "b.jpg", 1))   # "stale": the stub's own error text


def photo_problems(state: str, photos, w: int = 0) -> list:
    """The EXIF-6 original (stored landscape) must come out of author.js as portrait copies:
    thumb 360 x 480 and view 1200 x 1600, both JPEG. The upload state also decodes the
    stored WebP and checks the three loop runs (counts, reasons, status lines, requests)."""
    if not photos:
        return ["no photo probe result"]
    if photos.get("error"):
        return [f"probe error: {photos['error']}"]
    out = []
    if photos.get("decoded") != [1440, 1920]:
        out.append(f"decoded {photos.get('decoded')}, expected [1440, 1920] (EXIF 6 applied)")
    for name, size in (("thumb", [360, 480]), ("view", [1200, 1600])):
        got = photos.get(name) or []
        if got[:2] != size or got[2:3] != ["image/jpeg"]:
            out.append(f"{name} {got}, expected portrait {size} JPEG")
    if state == "files-photos-upload":
        if photos.get("webp") != [1, 1]:
            out.append(f"stored WebP decoded as {photos.get('webp')}, expected [1, 1]")
        run = photos.get("upload") or {}
        if (run.get("done"), run.get("dup"), run.get("stopped")) != (2, 1, False):
            out.append(f"run 1 done/dup/stopped {run.get('done')}/{run.get('dup')}/"
                       f"{run.get('stopped')}, expected 2/1/False")
        if sorted(run.get("skipped") or []) != UPLOAD_SKIPS:
            out.append(f"run 1 skipped {run.get('skipped')}, expected {UPLOAD_SKIPS}")
        want = f"{UPLOAD_RUN1} {S.UPLOAD_JS['reload_new']}"
        if run.get("status") != want:
            out.append(f"run 1 status «{run.get('status')}», expected «{want}»")
        for _, reason in UPLOAD_SKIPS:   # a reason is told once, in the list below
            if reason in (run.get("status") or ""):
                out.append(f"run 1 status repeats the reason «{reason}»")
        if run.get("list") != UPLOAD_LIST:
            out.append(f"run 1 skip list {run.get('list')}, expected {UPLOAD_LIST}")
        if run.get("fresh") != 1 or run.get("button") != S.UPLOAD_JS["reload_new"]:
            out.append(f"run 1 fresh/button {run.get('fresh')}/{run.get('button')}, expected "
                       f"1/{S.UPLOAD_JS['reload_new']}")
        clean = photos.get("clean") or {}
        done_line = f"{S.UPLOAD_JS['done']} {S.UPLOAD_JS['progress'].format(done=1, total=1)}"
        if (clean.get("done"), clean.get("fresh"), clean.get("stopped"), clean.get("reloads")) \
                != (1, 1, False, 1):
            out.append(f"clean run done/fresh/stopped/reloads {clean.get('done')}/"
                       f"{clean.get('fresh')}/{clean.get('stopped')}/{clean.get('reloads')}, "
                       f"expected 1/1/False/1")
        if not clean.get("kept") or clean.get("keptAfter") is not None:
            out.append(f"clean run kept {clean.get('kept')!r}, after restore "
                       f"{clean.get('keptAfter')!r}: expected a note, then none")
        if clean.get("restored") != done_line:
            out.append(f"clean run restored line «{clean.get('restored')}», expected «{done_line}»")
        look = photos.get("disabledLook") or {}
        if look.get("disabled") is not True or float(look.get("opacity") or 1) >= 1 or \
                look.get("cursor") == "pointer":
            out.append(f"buttons while a request runs look like {look}: expected disabled, "
                       f"dimmed, no pointer")
        if photos.get("newName") != f"new-{w}.jpg":
            out.append(f"new file named {photos.get('newName')}, expected new-{w}.jpg")
        for key, reason, name, calls in UPLOAD_STOPS:
            stop = photos.get(key) or {}
            want = f"{S.UPLOAD_JS['stopped'].format(reason=reason)} {S.UPLOAD_JS['reload']}"
            if stop.get("status") != want:
                out.append(f"{key} status «{stop.get('status')}», expected «{want}»")
            if (stop.get("done"), stop.get("stopped"), stop.get("calls")) != (0, True, calls):
                out.append(f"{key} done/stopped/requests {stop.get('done')}/"
                           f"{stop.get('stopped')}/{stop.get('calls')}, expected 0/True/{calls}")
    return out


def upload_index_problems(fx, widths) -> list:
    """After the upload runs: the fixture's city folder lists the 5 stored photos and two new
    rows per width (run 1's file and the clean run's), named after its file with the size of the browser's copy, with its thumb
    and view files; the refused, undecodable and stubbed files left nothing."""
    folder = os.path.join(fx.paths.stock, "city", fphotos.PHOTOS)
    rows = fphotos.read_index(folder)
    names = [r["name"] for r in rows]
    out = []
    for w, want, size in [(w, f"new-{w}.jpg", [40 + (w % 97), 30 + (w % 53)]) for w in widths] + \
            [(w, f"clean-{w}.jpg", [50 + (w % 89), 35 + (w % 47)]) for w in widths]:
        got = [r for r in rows if r["name"] == want]
        if len(got) != 1:
            out.append(f"index lists {len(got)} rows named {want}, expected 1")
            continue
        row = got[0]
        if [row["w"], row["h"]] != size:
            out.append(f"{want}: row size {row['w']} x {row['h']}, expected the copy's size")
        for kind in ("thumb", "view"):
            if not os.path.isfile(os.path.join(folder, kind, row["id"] + ".jpg")):
                out.append(f"{want}: no {kind} file")
        if not os.path.isfile(os.path.join(folder, f"{row['id']}.jpg")):
            out.append(f"{want}: no original")
    if len(rows) != 5 + 2 * len(widths):
        out.append(f"index lists {len(rows)} photos {names}, expected {5 + 2 * len(widths)}")
    stray = [n for n in names if n in ("broken.jpg", "refused.jpg", "a.jpg", "b.jpg", "c.jpg")]
    if stray:
        out.append(f"index lists files that must not load: {stray}")
    return out


def author_problems(state, result):
    author = result.get("author") or {}
    problems = list(author.get("problems", []))
    if not author:
        problems.append("no author probe result")
    for look in author.get("busy", []):
        if not look["disabled"] or float(look["opacity"]) >= 1 or look["cursor"] == "pointer":
            problems.append(f"busy control looks enabled: {look}")
    if state == "create-drop":
        drop = author.get("drop", {})
        if drop.get("uploads") != 3 or drop.get("new") != 1 or not drop.get("url", "").startswith("/create/"):
            problems.append(f"drop path: {drop}")
        if author.get("many", {}).get("calls") != 0 or not author.get("many", {}).get("message"):
            problems.append("multiple-file drop sent a request or lost its reason")
        if author.get("duplicate", {}).get("uploads") != 1:
            problems.append("duplicate drop must send only orig, then new draft")
        if author.get("recent", {}).get("uploads") != 0 or author.get("recent", {}).get("new") != 1:
            problems.append("recent photo uploaded or did not create a draft")
        if author.get("hostile", {}).get("status") != 403:
            problems.append("mutated CSRF header was not refused")
    if state == "create-voice":
        voice = result.get("author_voice") or {}
        if voice.get("calls") != 1 or not voice.get("transcript") or not voice.get("energy", 0) > 0:
            problems.append(f"voice stop/transcript/audio energy: {voice}")
    return problems


def behaviour_problems(fx, fake, widths):
    """Server side of the `create-behaviour` probe: the 503'd voice call and its retry reached
    Gemini with identical bytes, and the draft kept the transcript."""
    from factory.authoring import drafts
    out = []
    store = drafts.Store(fx.paths.content, fx.clock, fx.machine_tz)
    for w in widths:
        did = fx.create_ids[f"behaviour-{w}"]
        calls = [r for r in list(fake.requests) if r.fields.get("draft") == did
                 and not json.loads(r.body).get("response_format", {}).get("schema", {}).get("properties")]
        if len(calls) != 2:
            out.append(f"{w}: {len(calls)} voice calls reached Gemini, expected the 503 and its retry")
        elif calls[0].body != calls[1].body or len(calls[0].body) < 200:
            out.append(f"{w}: the retried voice call did not send the same audio bytes")
        if "Утренняя пробежка у моря" not in store.load(did)["topic"]:
            out.append(f"{w}: the draft kept no transcript")
    return out


def autoretry_problems(fx, fake, widths):
    """Server side of the `create-autoretry` probe: the automatic topics call answered 503, and
    «Повторить» sent a second real topics call, after which the draft holds topics and no error."""
    from factory.authoring import drafts
    out = []
    store = drafts.Store(fx.paths.content, fx.clock, fx.machine_tz)
    for w in widths:
        did = fx.create_ids[f"autoretry-{w}"]
        calls = [r for r in list(fake.requests) if r.fields.get("draft") == did
                 and "topics" in json.loads(r.body).get("response_format", {}).get("schema", {}).get("properties", {})]
        if len(calls) != 2:
            out.append(f"{w}: {len(calls)} topics calls reached Gemini, expected the 503 and its retry")
        draft = store.load(did)
        if draft["error"] is not None or not 3 <= len(draft["topics"]) <= 5:
            out.append(f"{w}: draft.json error {draft['error']!r}, {len(draft['topics'])} topics")
    return out


def author_index_problems(fx, widths, dropped):
    out = []
    rows = fphotos.read_index(os.path.join(fx.paths.stock, "my-photos", fphotos.PHOTOS))
    for w in widths if dropped else ():
        named = [r for r in rows if r["name"] == f"drop-{w}.jpg"]
        if len(named) != 1:
            out.append(f"drop-{w}.jpg: {len(named)} index rows, expected one")
    if len(rows) != 12 + (len(widths) if dropped else 0):
        out.append(f"{len(rows)} photo rows, expected {12 + (len(widths) if dropped else 0)}")
    for root, _, files in os.walk(fx.root):
        for name in files:
            if name.endswith((".webm", ".ogg")):
                out.append("audio on disk")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--widths", default=",".join(map(str, WIDTHS)))
    ap.add_argument("--only", default="", help="only states whose name contains this text")
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args(argv)
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    widths = [int(w) for w in args.widths.split(",") if w]
    fixtures_root = os.path.join(out, "fixture")
    shutil.rmtree(fixtures_root, ignore_errors=True)
    scratch = os.path.join(out, "t")
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(scratch)

    data = panel_fixture.build_data(os.path.join(fixtures_root, "data"))
    empty = panel_fixture.build_empty(os.path.join(fixtures_root, "empty"))
    bad_rules = panel_fixture.build_data(os.path.join(fixtures_root, "bad-rules"))
    with open(bad_rules.paths.rules, "w", encoding="utf-8") as fh:
        fh.write('{"schema": 1, "rules": [{"id": "Bad Id", "folder": "city"}]}\n')
    no_env = panel_fixture.build_empty(os.path.join(fixtures_root, "no-env"))
    os.remove(no_env.paths.env_file)
    with_photos = panel_fixture.build_photos(os.path.join(fixtures_root, "photos"))
    # the upload state changes its folder, so it has its own fixture, with one stored WebP
    uploading = panel_fixture.build_photos(os.path.join(fixtures_root, "upload"), n=4)
    webp_id = panel_fixture.store_photo(
        uploading, "city", panel_fixture.make_webp(1), panel_fixture.make_photo(360, 480, 1),
        panel_fixture.make_photo(1200, 1600, 1), "tiny.webp")

    # the grid lists the newest photo first: the probe is told which one is the EXIF-6 original
    exif_id = {name: fphotos.read_index(os.path.join(fx.paths.stock, "city", fphotos.PHOTOS))[0]["id"]
               for name, fx in (("photos", with_photos), ("upload", uploading))}
    create = panel_fixture.build_create(os.path.join(fixtures_root, "create"))
    create_live = panel_fixture.build_create(os.path.join(fixtures_root, "create-live"), live_widths=widths)
    create_empty = panel_fixture.build_empty(os.path.join(fixtures_root, "create-empty"))
    panel_fixture._env_file(create_empty.paths.env_file, {"GEMINI_API_KEY": panel_fixture.CANARIES["GEMINI_API_KEY"]})
    create_budget = panel_fixture.build_create(os.path.join(fixtures_root, "create-budget"), ledger_usd="9.99")
    create_nokey = panel_fixture.build_create(os.path.join(fixtures_root, "create-nokey"), key=False)
    send = panel_fixture.build_send(os.path.join(fixtures_root, "send"))
    send_bad = panel_fixture.build_send(os.path.join(fixtures_root, "send-problems"), problems=True)
    send_crash = panel_fixture.build_send(os.path.join(fixtures_root, "send-crash"), crash=True)
    send_live = panel_fixture.build_send(os.path.join(fixtures_root, "send-live"), live_widths=widths)
    send_go = panel_fixture.build_send(os.path.join(fixtures_root, "send-go"), go_widths=widths)
    exif_pid = panel_fixture.store_photo(send_live, "my-photos", panel_fixture.make_exif6(4032, 3024, 77),
                                         panel_fixture.make_photo(360, 480, 77),
                                         panel_fixture.make_photo(1200, 1600, 77), "exif6.jpg")
    small_pid = next(r["id"] for r in fphotos.read_index(os.path.join(send_live.paths.stock, "my-photos",
                                                                      fphotos.PHOTOS))
                     if r["name"] == "walk-01.jpg")
    focus_mtimes = {(did, n): os.stat(os.path.join(send_live.paths.content, "drafts", did, "out", f"{n}.jpg")).st_mtime_ns
                    for key, did in send_live.send_ids.items() if key.startswith("focus-")
                    for n in ("facebook", "linkedin")}
    images = panel_fixture.build_images(os.path.join(fixtures_root, "images"))
    images_budget = panel_fixture.build_images(os.path.join(fixtures_root, "images-budget"), ledger_usd="9.99")
    images_nokey = panel_fixture.build_images(os.path.join(fixtures_root, "images-nokey"), key=False)
    images_live = panel_fixture.build_images(os.path.join(fixtures_root, "images-live"), live_widths=widths)
    static_images = {name: (fx, content_hashes(fx)) for name, fx in
                     (("images", images), ("images-budget", images_budget), ("images-nokey", images_nokey))}
    fake_img = panel_fixture.FakeGemini()
    fake_img.hold = {did for key, did in images_live.image_ids.items() if key.startswith("hold-")}
    fake_img.images = {did: "text" for key, did in images_live.image_ids.items() if key.startswith("text-")}
    fake_img.e402 = {did for key, did in images_live.image_ids.items() if key.startswith(("e402-", "x402-"))}
    send_hold = threading.Event()
    send_fake = panel_fixture.FakePoster(hold=send_hold, wait=4 * 3600)   # released at teardown
    fake = panel_fixture.FakeGemini()
    fake.hold = {did for name, did in create_live.create_ids.items() if "loading" in name}
    # the behaviour draft's first voice call answers 503 once: the retry must send the same bytes
    fake.fail_voice_once = {did for name, did in create_live.create_ids.items() if name.startswith("behaviour")}
    # the autoretry draft's automatic topics call answers 503 once: «Повторить» must send a real second call
    fake.fail_topics_once = {did for name, did in create_live.create_ids.items() if name.startswith("autoretry")}
    servers = {name: start(fx) for name, fx in
               (("data", data), ("empty", empty), ("bad-rules", bad_rules), ("no-env", no_env),
                ("photos", with_photos), ("upload", uploading))}
    for name, fx in (("create", create), ("create-empty", create_empty),
                     ("create-budget", create_budget), ("create-nokey", create_nokey)):
        servers[name] = start(fx, fake)
    # A held request belongs to one state/width panel. Its two admission slots must
    # not occupy another state's panel (voice has to be able to transcribe).
    # The shared fixture still has a different draft for each mutation.
    for w in widths:
        for kind in ("topics-loading", "expand-loading", "expand-texts", "voice", "drop", "behaviour", "autoretry"):
            servers[f"create-live-{kind}-{w}"] = start(create_live, fake)
    servers["send"] = start(send, publish=send_fake)
    servers["send-problems"] = start(send_bad)
    servers["send-crash"] = start(send_crash)
    servers["send-live"] = start(send_live)
    servers["send-go"] = start(send_go)   # a FakePoster that publishes at once
    for name, fx in (("images", images), ("images-budget", images_budget), ("images-nokey", images_nokey)):
        servers[name] = start(fx)
    for w in widths:   # one panel per spending state and width: a held call takes no other's slot
        for state in IMAGE_LIVE_STATE:
            servers[f"images-live-{state}-{w}"] = start(images_live, fake_img)
    t0 = time.perf_counter()
    snap = servers["data"].panel.holder.get()
    snapshot_ms = snap.build_ms
    print(f"snapshot_ms={snapshot_ms:.0f} (data fixture, budget {BUDGET_MS}; "
          f"wall {1000 * (time.perf_counter() - t0):.0f})")

    def url(name, path):
        return f"http://127.0.0.1:{servers[name].port}{path}"

    states = [
        ("connection", url("data", "/connection")),
        ("connection-net", url("data", "/connection?net=linkedin#net-detail")),
        ("attention", url("data", "/connection?attention=1")),
        ("files", url("data", "/files")),
        ("files-folder", url("data", "/files?folder=city")),
        ("rules", url("data", "/rules")),
        ("calendar", url("data", "/calendar")),
        ("calendar-day", url("data", "/calendar?day=2026-11-06")),
        ("calendar-plan", url("data", "/calendar?day=2026-11-12")),
        ("calendar-runout", url("data", "/calendar?day=2026-12-18")),
        ("calendar-budget", url("data", "/calendar?day=2026-10-26")),
        ("calendar-missed", url("data", "/calendar?day=2026-10-19")),
        ("reach", url("data", "/reach")),
        ("reach-weak", url("data", "/reach?sort=weak")),
        ("followers", url("data", "/followers")),
        ("followers-week", url("data", "/followers?period=week")),
        ("dialogs", url("data", "/dialogs")),
    ] + [(f"empty-{tab}", url("empty", f"/{tab}")) for tab in
         ("connection", "files", "rules", "calendar", "reach", "followers")] + [
        ("error-rules", url("bad-rules", "/rules")),
        ("error-rules-connection", url("bad-rules", "/connection")),
        ("error-env", url("no-env", "/files")),
        ("files-photos", url("photos", f"/files?probe_orig={exif_id['photos']}")),
        ("files-photos-folder", url("photos", f"/files?folder=city&probe_orig={exif_id['photos']}")),
        ("files-photos-more", url("photos", "/files?folder=city&photos=70#photo-61")),
        # the upload loop's end state (photo states run in real time, see Chrome.live)
        ("files-photos-upload", url("upload", f"/files?folder=city&probe=1&probe_upload=1&probe_webp={webp_id}&probe_orig={exif_id['upload']}")),
    ]
    author_paths = {
        "create-empty": ("create-empty", "/create"), "create-start": ("create", "/create"),
        "create-topics": ("create", "/create/" + create.create_ids["topics"]),
        "create-own-topic": ("create", "/create/" + create.create_ids["own-topic"]),
        "create-texts": ("create", "/create/" + create.create_ids["texts"] + "#texts"),
        "create-over-limit": ("create", "/create/" + create.create_ids["over-limit"] + "#texts"),
        "create-budget": ("create-budget", "/create/" + create_budget.create_ids["topics"]),
        "create-error": ("create", "/create/" + create.create_ids["error"]),
        "create-nokey": ("create-nokey", "/create/" + create_nokey.create_ids["topics"]),
        "create-nokey-start": ("create-nokey", "/create"),
        "create-profile": ("create", "/create/profile?saved=1"),
        "files-mediateka": ("create", "/files"), "files-mine": ("create", "/files?folder=my-photos"),
    }
    states += [(name, url(fixture, path)) for name, (fixture, path) in author_paths.items()]
    states += [("create-" + name, "") for name in ("topics-loading", "expand-loading", "expand-texts", "voice", "drop", "behaviour", "autoretry")]
    # the 409 refusal: starting the draft with validation problems
    pages = os.path.join(scratch, "pages")
    os.makedirs(pages)
    refuse = os.path.join(pages, "rules-409.html")
    refuse_probe = os.path.join(pages, "rules-409-probe.html")
    fields = {"rule": "tips-ig", "rev": snap.inputs.ruleset.revision}
    status = post_page(servers["data"], "/rules/start", fields, refuse)
    post_page(servers["data"], "/rules/start?probe=1", fields, refuse_probe)
    print(f"rules-409: POST /rules/start answered {status}")
    states.append(("rules-409", "file://" + refuse))
    probe_urls = {"rules-409": "file://" + refuse_probe}
    # the files 409: creating a folder whose name is taken (the banner sits above the lanes)
    folder_page = os.path.join(pages, "files-409.html")
    folder_probe = os.path.join(pages, "files-409-probe.html")
    fields = {"name": "city", "lane": "photo"}
    status = post_page(servers["data"], "/files/new-folder", fields, folder_page)
    post_page(servers["data"], "/files/new-folder?probe=1", fields, folder_probe)
    print(f"files-409: POST /files/new-folder answered {status}")
    states.append(("files-409", "file://" + folder_page))
    probe_urls["files-409"] = "file://" + folder_probe
    # slice D′: one held publish, one queue, and one queue whose offered rule is refused (§17.6)
    ids = send.send_ids
    status = post_form(servers["send"], f"/create/{ids['publishing']}/publish",
                       form_values(servers["send"], f"/create/{ids['publishing']}/review"))
    if status != 303 or not send_fake.entered.wait(30):
        sys.exit(f"send fixture: the held publish did not start ({status})")
    status = post_form(servers["send"], f"/create/{ids['queue-me']}/queue",
                       dict(form_values(servers["send"], f"/create/{ids['queue-me']}/review"), folder="my-photos"))
    print(f"queued: POST /create/<queue-me>/queue answered {status}")
    setup_problems = [] if status == 303 else [f"queueing queue-me answered {status}, expected 303"]
    refused = os.path.join(pages, "rule-refused.html")
    refused_probe = os.path.join(pages, "rule-refused-probe.html")
    status = post_page(servers["send"], f"/create/{ids['rule-me']}/queue?probe=1",
                       dict(form_values(servers["send"], f"/create/{ids['rule-me']}/review"),
                            folder="my-photos", rule="1", rule_hour="10:00"), refused_probe)
    with open(refused_probe, encoding="utf-8") as fh:
        shot = fh.read().replace('<script src="/static/probe.js" defer></script>', "")
    with open(refused, "w", encoding="utf-8") as fh:
        fh.write(shot)
    print(f"rule-refused: POST /create/<rule-me>/queue with the rule answered {status}")
    if status != 409:
        setup_problems.append(f"queueing rule-me with the rule answered {status}, expected 409")
    send_paths = {
        "send-draft": ("send", f"/create/{ids['ready']}#texts"),
        "review": ("send", f"/create/{ids['ready']}/review"),
        "review-rule": ("send", f"/create/{ids['ready']}/review?folder=city"),
        "review-problems": ("send-problems", f"/create/{send_bad.send_ids['problems']}/review"),
        "review-confirm": ("send", f"/create/{ids['ready']}/review"),
        "review-publishing": ("send", f"/create/{ids['publishing']}/review"),
        "review-partial": ("send", f"/create/{ids['partial']}/review"),
        "review-published": ("send", f"/create/{ids['published']}/review"),
        "review-interrupted": ("send-crash", f"/create/{send_crash.send_ids['crash']}/review"),
        "review-delete": ("send", f"/create/{ids['published']}/review"),
        "queued": ("send", f"/files?folder=my-photos&queued={ids['queue-me']}&probe_pkg={ids['queue-me']}#pkg-{ids['queue-me']}"),
        "send-start": ("send", "/create"),
    }
    states += [(name, url(fixture, path)) for name, (fixture, path) in send_paths.items()]
    states += [("review-crops", ""), ("review-focus", "")]
    states += [("submit-publish", ""), ("submit-queue", "")]   # driven after the pool, see submit_problems
    states.append(("rule-refused", "file://" + refused))
    # slice C (§18.6): static states on «images», live ones on «images-live» (address made per width)
    image_paths = {
        "review-styles-empty": ("images", f"/create/{images.image_ids['plain']}/review#photo"),
        "review-styles": ("images", f"/create/{images.image_ids['styled']}/review?style=blur#photo"),
        "review-based": ("images", f"/create/{images.image_ids['based']}/review#photo"),
        "review-styles-budget": ("images-budget", f"/create/{images_budget.image_ids['plain']}/review#photo"),
        "review-styles-nokey": ("images-nokey", f"/create/{images_nokey.image_ids['styled']}/review?style=blur#photo"),
    }
    states += [(name, url(fixture, path)) for name, (fixture, path) in image_paths.items()]
    states += [(name, "") for name in IMAGE_LIVE_STATE]
    probe_urls["rule-refused"] = "file://" + refused_probe
    if args.only:
        states = [s for s in states if args.only in s[0]]

    chrome = Chrome(find_chrome(), scratch)
    findings: dict = {}
    heights: dict = {}
    ellipsis_at: dict = {}

    def one(state, address, w):
        h = WIDTHS.get(w, 900)
        if state in SEND_STATES:   # real time: canvas work, dialogs, held requests (§17.6)
            if not address:
                did = send_live.send_ids[f"{state[len('review-'):]}-{w}"]
                address = url("send-live", f"/create/{did}/review?probe_exif={exif_pid}&probe_small={small_pid}")
            if state in probe_urls:
                address = probe_urls[state]
            parts = urllib.parse.urlsplit(address)
            query = parts.query + ("&" if parts.query else "") + "probe=1&probe_send=" + state
            address = urllib.parse.urlunsplit(parts._replace(query=query))
            result = chrome.live(address, w, h, os.path.join(out, f"{state}-{w}.png"),
                                 os.path.join(out, f"{state}-{w}-full.png"))
            with open(os.path.join(out, f"{state}-{w}-probe.json"), "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
            return state, w, result, min(max(h, int(result.get("height", h))), FULL_MAX)
        if state in IMAGE_STATES:   # real time and stages (§18.6)
            if not address:
                kind = IMAGE_LIVE_STATE[state]
                did = images_live.image_ids[f"{kind}-{w}"]
                hashes = {"review-template": f"?probe_small={images_live.small_photo}", "review-ratio": "#send-cards-h",
                          "create-error-402": ""}
                path = (f"/create/{did}" if state == "create-error-402" else f"/create/{did}/review") + \
                    hashes.get(state, "#photo")
                address = url(f"images-live-{state}-{w}", path)
            parts = urllib.parse.urlsplit(address)
            query = parts.query + ("&" if parts.query else "") + "probe=1&probe_send=" + state
            address = urllib.parse.urlunsplit(parts._replace(query=query))
            result = chrome.staged(address, w, h, os.path.join(out, f"{state}-{w}.png"),
                                   os.path.join(out, f"{state}-{w}-full.png"))
            with open(os.path.join(out, f"{state}-{w}-probe.json"), "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
            return state, w, result, min(max(h, int(result.get("height", h))), FULL_MAX)
        if state in author_paths or state in ("create-topics-loading", "create-expand-loading", "create-expand-texts",
                                              "create-voice", "create-drop", "create-behaviour", "create-autoretry"):
            if not address:
                name = state[len("create-"):]
                path = "/create" if name == "drop" else "/create/" + create_live.create_ids[f"{name}-{w}"]
                address = url(f"create-live-{name}-{w}", path)
            parts = urllib.parse.urlsplit(address)
            query = parts.query + ("&" if parts.query else "") + "probe=1&probe_create=" + state
            address = urllib.parse.urlunsplit(parts._replace(query=query))
            result = chrome.live(address, w, h, os.path.join(out, f"{state}-{w}.png"),
                                 os.path.join(out, f"{state}-{w}-full.png"))
            # Each text card also has its own mobile frame, with its entire editor visible.
            if state == "create-texts" and w == 390:
                with Live(chrome, address, w, h) as mobile:
                    mobile.wait_value("document.getElementById('probe') ? true : null", 60)
                    for n in ("x", "linkedin", "instagram", "facebook"):
                        mobile.evaluate(f"document.querySelector('[data-network={n}]').scrollIntoView(); true")
                        mobile.screenshot(os.path.join(out, f"{state}-{w}-{n}.png"))
            with open(os.path.join(out, f"{state}-{w}-probe.json"), "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
            return state, w, result, min(max(h, int(result.get("height", h))), FULL_MAX)
        if state.startswith("files-photos"):
            result = chrome.live(address if "probe=1" in address else with_probe(address), w, h,
                                 os.path.join(out, f"{state}-{w}.png"),
                                 os.path.join(out, f"{state}-{w}-full.png"))
            return state, w, result, min(max(h, int(result.get("height", h))), FULL_MAX)
        probe_url = probe_urls.get(state, address if "probe=1" in address else with_probe(address))
        result = chrome.probe(probe_url, w, h)
        chrome.screenshot(address, os.path.join(out, f"{state}-{w}.png"), w, h)
        full_h = min(max(h, int(result.get("height", h))), FULL_MAX)
        if full_h > h:
            chrome.screenshot(address, os.path.join(out, f"{state}-{w}-full.png"), w, full_h)
        return state, w, result, full_h

    jobs = [(s, a, w) for s, a in states for w in widths if not s.startswith("submit-")]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for state, w, result, full_h in pool.map(lambda j: one(*j), jobs):
            heights[(state, w)] = full_h
            if result["findings"]:
                findings[f"{state}-{w}"] = result["findings"]
            if state.startswith("files-photos-") and state != "files-photos-more":
                for problem in photo_problems(state, result.get("photos"), w):
                    findings.setdefault(f"{state}-{w}", []).append(
                        {"kind": "photo-copies", "el": "", "text": "", "detail": problem})
                if w == widths[0]:
                    print(f"photos: {state}: {json.dumps(result.get('photos'), ensure_ascii=False)}")
            if state in SEND_STATES:
                for problem in send_problems(state, result):
                    findings.setdefault(f"{state}-{w}", []).append(
                        {"kind": "send", "el": "", "text": "", "detail": problem})
            if state in IMAGE_STATES:
                for problem in image_problems(state, result):
                    findings.setdefault(f"{state}-{w}", []).append(
                        {"kind": "images", "el": "", "text": "", "detail": problem})
            elif state in author_paths or state.startswith("create-"):
                for problem in author_problems(state, result):
                    findings.setdefault(f"{state}-{w}", []).append(
                        {"kind": "authoring", "el": "", "text": "", "detail": problem})
            # the long fixture title is either whole or cut with a rendered "…", never cut bare
            if state in ELLIPSIS_STATES:
                if LONG_TITLE in result.get("ellipsis", []):
                    ellipsis_at.setdefault(state, []).append(w)
                elif state == "files" and w >= 900:   # a fixed 220 px card always cuts it
                    findings.setdefault(f"{state}-{w}", []).append(
                        {"kind": "no-ellipsis", "el": "", "text": LONG_TITLE,
                         "detail": "the fixed-width Files card shows no ellipsis"})
                elif LONG_TITLE not in result.get("whole", []):
                    findings.setdefault(f"{state}-{w}", []).append(
                        {"kind": "title-not-clamped-or-whole", "el": "", "text": LONG_TITLE,
                         "detail": "neither whole nor cut with an ellipsis"})

    failed = False
    for state in ELLIPSIS_STATES:
        shown = sorted(ellipsis_at.get(state, []))
        print(f"ellipsis: {state} cuts the long title with \u2026 at widths {shown}")
        if not shown and not args.only:   # the 220 px Files card and the narrower Rules cells clamp
            failed = True
            print(f"  - {state}: the long title never shows an ellipsis at any width")
    for key in sorted(findings):
        failed = True
        print(f"FINDINGS {key}:")
        grouped: dict = {}
        for f in findings[key]:
            line = f"{f['kind']}: {f['el']} {f['detail']} «{f['text']}»"
            grouped[line] = grouped.get(line, 0) + 1
        for line, n in grouped.items():
            print(f"  - {line}" + (f"  (x{n})" if n > 1 else ""))
    with open(CSS, encoding="utf-8") as fh:
        pairs = check_contrast(fh.read())
    for fg, bg, ratio in pairs:
        if ratio < 4.5:
            failed = True
            print(f"CONTRAST {fg} on {bg}: {ratio:.2f} < 4.5")
    print(f"contrast: {len(pairs)} pairs, lowest {min(r for _, _, r in pairs):.2f}")
    if snapshot_ms > BUDGET_MS:
        failed = True
        print(f"snapshot_ms {snapshot_ms:.0f} over the {BUDGET_MS} ms budget")
    print(f"{len(jobs)} state x width pages probed, {len(findings)} with findings; PNGs in {out}")
    if any(s[0] == "files-photos-upload" for s in states):
        for problem in upload_index_problems(uploading, widths):
            failed = True
            print(f"UPLOAD INDEX: {problem}")
    if any(s[0] == "create-autoretry" for s in states):
        for problem in autoretry_problems(create_live, fake, widths):
            failed = True
            print(f"AUTHOR AUTORETRY: {problem}")
    if any(s[0] == "create-behaviour" for s in states):
        for problem in behaviour_problems(create_live, fake, widths):
            failed = True
            print(f"AUTHOR BEHAVIOUR: {problem}")
    for problem in author_index_problems(create_live, widths, "create-drop" in [s[0] for s in states]):
        failed = True
        print(f"AUTHOR INDEX: {problem}")
    for problem in setup_problems:
        failed = True
        print(f"SEND SETUP: {problem}")
    ran = [s[0][len("review-"):] for s in states if s[0] in ("review-crops", "review-focus")]
    if any(s[0] in SEND_STATES for s in states):
        for problem in send_after(send_live, widths, focus_mtimes, send_fake, ran):
            failed = True
            print(f"SEND: {problem}")
    if any(s[0].startswith("submit-") for s in states):
        for problem in submit_problems(chrome, send_go, servers["send-go"], widths, out):
            failed = True
            print(f"SEND SUBMIT: {problem}")
        servers["send-go"].panel.sender.join(30)
    ran_images = [s[0] for s in states if s[0] in IMAGE_STATES]
    if ran_images:
        for problem in image_after(images_live, widths, ran_images, fake_img,
                                   static_images if any(s in ran_images for s in image_paths) else {}):
            failed = True
            print(f"IMAGES: {problem}")
    send_hold.set()
    servers["send"].panel.sender.join(30)
    fake.release.set()
    fake_img.release.set()
    for srv in servers.values():
        srv.shutdown()
        srv.server_close()
    shutil.rmtree(scratch, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
