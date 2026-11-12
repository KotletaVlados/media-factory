"""Visual check of the panel (design factory.md §13.3 items 4 and 5; panel brief §5).

    python3 tools/visual_check.py --out DIR [--widths 390,900,1280,1440,1600,1920] [--only TEXT]

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
reports the copy sizes, which must be portrait; `files-photos-upload` also runs the real
upload loop (a duplicate, a HEIC file and a text file) and checks its status line.

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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from factory.panel import server  # noqa: E402
from tests import panel_fixture  # noqa: E402

WIDTHS = {390: 844, 900: 900, 1000: 700, 1280: 800, 1440: 900, 1600: 900, 1920: 1080}
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
             "--disable-gpu", "--hide-scrollbars",
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
        return r.get("result", {}).get("value")

    def wait_value(self, expression: str, timeout: float):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.evaluate(expression)
            if value is not None:
                return value
            time.sleep(0.2)
        raise RuntimeError(f"no probe output for {self.url} within {timeout} s")

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


def start(fixture):
    srv = server.make_server(fixture.paths, fixture.clock, fixture.machine_tz, 0,
                             log=io.StringIO())
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


UPLOAD_STATUS = ("Готово: загружено 1 из 3 · уже были: 1 · пропущено 2 "
                 "(HEIC, не JPEG, PNG или WebP)")


def photo_problems(state: str, photos) -> list:
    """The EXIF-6 original (stored landscape) must come out of author.js as portrait copies:
    thumb 360 x 480 and view 1200 x 1600, both JPEG; the upload state ends with its status."""
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
        status = (photos.get("upload") or {}).get("status", "")
        if not status.startswith(UPLOAD_STATUS):
            out.append(f"upload status «{status}», expected «{UPLOAD_STATUS} обновить»")
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

    servers = {name: start(fx) for name, fx in
               (("data", data), ("empty", empty), ("bad-rules", bad_rules), ("no-env", no_env),
                ("photos", with_photos))}
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
        ("files-photos", url("photos", "/files")),
        ("files-photos-folder", url("photos", "/files?folder=city")),
        ("files-photos-more", url("photos", "/files?folder=city&photos=70#photo-61")),
        # the upload loop's end state (photo states run in real time, see Chrome.live)
        ("files-photos-upload", url("photos", "/files?folder=city&probe=1&probe_upload=1")),
    ]
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
    if args.only:
        states = [s for s in states if args.only in s[0]]

    chrome = Chrome(find_chrome(), scratch)
    findings: dict = {}
    heights: dict = {}
    ellipsis_at: dict = {}

    def one(state, address, w):
        h = WIDTHS.get(w, 900)
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

    jobs = [(s, a, w) for s, a in states for w in widths]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for state, w, result, full_h in pool.map(lambda j: one(*j), jobs):
            heights[(state, w)] = full_h
            if result["findings"]:
                findings[f"{state}-{w}"] = result["findings"]
            if state.startswith("files-photos-") and state != "files-photos-more":
                for problem in photo_problems(state, result.get("photos")):
                    findings.setdefault(f"{state}-{w}", []).append(
                        {"kind": "photo-copies", "el": "", "text": "", "detail": problem})
                if w == widths[0]:
                    print(f"photos: {state}: {json.dumps(result.get('photos'), ensure_ascii=False)}")
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
    for srv in servers.values():
        srv.shutdown()
        srv.server_close()
    shutil.rmtree(scratch, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
