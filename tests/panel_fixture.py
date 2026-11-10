"""Fixture state for the panel (design factory.md §13.3 item 1), shared by the panel tests and
`tools/visual_check.py`.

`build_data(root)` writes, under `root`: an env file with canary secrets, an image library, a
stock of 2 lanes and 5 folders, 4 rules (2 active, 2 drafts, one of them with validation
problems), 60 days of runner journal and poster record with failed, unknown, missed and
over-budget slots plus one manual publication, an X ledger, a heartbeat, and the two lane-L2
stats files (40 posts with metrics, 4 follower series, one declining). `build_empty(root)`
writes an env file without any target variables and nothing else.

Everything is deterministic: a frozen clock, fixed ids and a seeded generator. Folder names,
titles and texts are neutral inventions. The default profile's targets are read from
`poster.config.PROFILES` at runtime.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import random
import struct
from dataclasses import dataclass

from poster import config, state as poster_state
from factory import cli as fcli, journal as fjournal, paths as fpaths, planner
from factory import ruleset as fruleset, stock as fstock
from tests.base import CANARIES, PLAIN

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 11, 9, 40, 0, tzinfo=UTC)     # a Wednesday, 10:40 in Berlin
MACHINE_TZ = "Europe/Berlin"
HISTORY_DAYS = 60
EXTRA_ENV = {"IG_DEMO_USER_ID": "17800000000000007"}


@dataclass
class Fixture:
    root: str
    environ: dict
    paths: fpaths.Paths
    now: dt.datetime = NOW
    machine_tz: str = MACHINE_TZ

    def clock(self):
        return self.now


def profile() -> dict:
    """network -> target id of the default profile."""
    out = {}
    for spec in config.PROFILES[fcli.DEFAULT_PROFILE]:
        out[config.parse_target(spec).network] = spec
    return out


# ---------------------------------------------------------------- a small baseline JPEG

def _huff_codes(bits: list, vals: list) -> dict:
    codes, code, k = {}, 0, 0
    for length, n in enumerate(bits, start=1):
        for _ in range(n):
            codes[vals[k]] = (code, length)
            code += 1
            k += 1
        code <<= 1
    return codes


DC_BITS = [0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]
DC_VALS = list(range(12))
AC_BITS = [1] + [0] * 15
AC_VALS = [0]          # only end-of-block: every block is flat


def make_photo(w: int, h: int, seed: int) -> bytes:
    """A real (decodable) baseline JPEG of 8x8 flat blocks: an abstract sky, sun and ground
    whose colours depend on `seed`."""
    rnd = random.Random(seed)
    sky = [rnd.randint(60, 200) for _ in range(3)]
    ground = [rnd.randint(20, 110) for _ in range(3)]
    sun = (rnd.uniform(0.2, 0.8), rnd.uniform(0.15, 0.4), rnd.uniform(0.08, 0.16))
    horizon = rnd.uniform(0.45, 0.7)
    bw, bh = (w + 7) // 8, (h + 7) // 8

    def colour(bx, by):
        x, y = (bx + 0.5) / bw, (by + 0.5) / bh
        if (x - sun[0]) ** 2 + ((y - sun[1]) * h / w) ** 2 < sun[2] ** 2:
            return (250, 236, 200)
        if y < horizon:
            t = y / horizon
            return tuple(int(c * (0.6 + 0.4 * t)) for c in sky)
        t = (y - horizon) / (1 - horizon)
        return tuple(int(c * (1 - 0.5 * t)) for c in ground)

    dc = _huff_codes(DC_BITS, DC_VALS)
    ac = _huff_codes(AC_BITS, AC_VALS)
    acc, nbits, out = 0, 0, bytearray()

    def put(code, length):
        nonlocal acc, nbits
        acc = (acc << length) | code
        nbits += length
        while nbits >= 8:
            nbits -= 8
            byte = (acc >> nbits) & 0xFF
            out.append(byte)
            if byte == 0xFF:
                out.append(0)
        acc &= (1 << nbits) - 1

    prev = [0, 0, 0]
    for by in range(bh):
        for bx in range(bw):
            r, g, b = colour(bx, by)
            ycc = (0.299 * r + 0.587 * g + 0.114 * b,
                   128 - 0.168736 * r - 0.331264 * g + 0.5 * b,
                   128 + 0.5 * r - 0.418688 * g - 0.081312 * b)
            for c in range(3):
                value = int(round(ycc[c])) - 128          # DC quantised by 8: (8 * mean) / 8
                diff = value - prev[c]
                prev[c] = value
                size = abs(diff).bit_length()
                put(*dc[size])
                if size:
                    put(diff if diff >= 0 else diff + (1 << size) - 1, size)
                put(*ac[0])
    if nbits:
        put((1 << (8 - nbits)) - 1, 8 - nbits)

    def segment(marker, payload):
        return struct.pack(">BBH", 0xFF, marker, len(payload) + 2) + payload

    app0 = segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    dqt = segment(0xDB, b"\x00" + bytes([8] + [1] * 63))
    sof = segment(0xC0, struct.pack(">BHHB", 8, h, w, 3) + b"\x01\x11\x00\x02\x11\x00\x03\x11\x00")
    dht = segment(0xC4, b"\x00" + bytes(DC_BITS) + bytes(DC_VALS)
                  + b"\x10" + bytes(AC_BITS) + bytes(AC_VALS))
    sos = segment(0xDA, b"\x03\x01\x00\x02\x00\x03\x00\x00\x3f\x00")
    return b"\xff\xd8" + app0 + dqt + sof + dht + sos + bytes(out) + b"\xff\xd9"


# ---------------------------------------------------------------- texts (neutral inventions)

CITY = ("Утро на набережной: туман над водой и первые трамваи.",
        "Старый двор, где каждое окно светится по-своему.",
        "Мост в час пик: город спешит, река никуда не торопится.",
        "Крыши после дождя блестят, как новые.",
        "Вечерний рынок закрывается, пахнет яблоками и хлебом.",
        "Пустая площадь в семь утра — редкий подарок.",
        "Велосипеды у библиотеки ждут хозяев с лекций.",
        "Фонари зажигаются по одному, улица просыпается к ночи.")
NATURE = ("Сосны на ветру и тишина, которую слышно.",
          "Озеро без единой волны, небо дважды.",
          "Тропа уходит в туман — значит, надо идти.",
          "Первый снег на папоротнике.")
QUOTES = ("Маленький шаг каждый день сильнее большого рывка раз в месяц.",
          "Сначала сделай, потом сделай хорошо.",
          "Скучные привычки дают нескучные результаты.",
          "Список дел короче, когда в нём три пункта.",
          "Отдых — тоже часть работы.",
          "Лучшее время начать было вчера, второе лучшее — сейчас.")
NOTES = ("Заметка о том, как планировать неделю за десять минут.",
         "Три вопроса перед любым созвоном.",
         "Почему черновик лучше пустой страницы.")
TIPS = ("Совет: делайте резервную копию до, а не после.",
        "Совет: одна вкладка — одна задача.",
        "Совет: подпишите папки так, чтобы понять их через год.")


# ---------------------------------------------------------------- writers

def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def _env_file(path: str, values: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# fake env for the panel fixture\n")
        for k, v in values.items():
            fh.write(f"{k}={v}\n")
    os.chmod(path, 0o600)


def _environ(root: str) -> dict:
    return {"HOME": os.path.join(root, "home"), "XDG_STATE_HOME": os.path.join(root, "xdg"),
            "MF_STATE_DIR": os.path.join(root, "poster-state"),
            "MF_ENV_FILE": os.path.join(root, "fake.env"),
            "MF_IMAGE_LIBRARY": os.path.join(root, "library"),
            "MF_CONTENT_DIR": os.path.join(root, "content"),
            "MF_FACTORY_STATE_DIR": os.path.join(root, "factory-state"),
            "TZ": MACHINE_TZ}


def build_empty(root: str) -> Fixture:
    """No stock, no rules, no records, no stats; an env file without target variables."""
    environ = _environ(root)
    os.makedirs(environ["HOME"], exist_ok=True)
    _env_file(environ["MF_ENV_FILE"], {"X_MONTHLY_CAP_USD": "5.00"})
    return Fixture(root, environ, fpaths.resolve(environ))


def _folder(stock: str, name: str, title: str, lane: str) -> str:
    path = os.path.join(stock, name)
    _write_json(os.path.join(path, fstock.FOLDER_FILE), {"schema": 1, "title": title, "lane": lane})
    return path


def _package(folder: str, index: int, pid: str, theme: str, variants: dict,
             approved: bool = True) -> str:
    data = {"schema": 1, "id": pid, "theme": theme, "variants": variants}
    if approved:
        data["meta"] = {"approved_by_operator": "2026-09-01"}
    path = os.path.join(folder, f"{index:03d}-{pid}.json")
    _write_json(path, data)
    return path


def build_data(root: str) -> Fixture:
    environ = _environ(root)
    os.makedirs(environ["HOME"], exist_ok=True)
    env = dict(PLAIN)
    env.update(CANARIES)
    env.update(EXTRA_ENV)
    _env_file(environ["MF_ENV_FILE"], env)
    paths = fpaths.resolve(environ)
    p = profile()
    library = paths.library
    os.makedirs(library, exist_ok=True)

    # ------------------------------------------------------------ stock: 2 lanes, 5 folders
    city = _folder(paths.stock, "city", "Город", "photo")
    for k in range(40):
        image = f"city-{k + 1:02d}.jpg"
        with open(os.path.join(library, image), "wb") as fh:
            fh.write(make_photo(320, 400, seed=k))
        text = CITY[k % len(CITY)]
        _package(city, k + 1, f"city-{k + 1:02d}", "город",
                 {"facebook": {"text": text + " Подробнее в нашем блоге.", "image": image},
                  "instagram": {"text": text + " #город", "image": image},
                  "linkedin": {"text": "Наблюдение дня. " + text, "image": image},
                  "x": {"text": text, "image": image}})
    nature = _folder(paths.stock, "nature", "Природа", "photo")
    for k in range(8):
        image = f"nature-{k + 1:02d}.jpg"
        with open(os.path.join(library, image), "wb") as fh:
            fh.write(make_photo(320, 400, seed=100 + k))
        text = NATURE[k % len(NATURE)]
        _package(nature, k + 1, f"nature-{k + 1:02d}", "природа",
                 {"facebook": {"text": text, "image": image},
                  "instagram": {"text": text + " #природа", "image": image}},
                 approved=k != 5)
    quotes = _folder(paths.stock, "quotes", "Цитаты", "text")
    for k in range(40):
        text = QUOTES[k % len(QUOTES)]
        x_text = text if k != 33 else ("Слишком длинная цитата. " * 14).strip()
        _package(quotes, k + 1, f"quote-{k + 1:02d}", "цитата",
                 {"facebook": {"text": text}, "linkedin": {"text": text + "\n\nА как у вас?"},
                  "x": {"text": x_text}})
    notes = _folder(paths.stock, "notes", "Короткие заметки", "text")
    for k in range(12):
        text = NOTES[k % len(NOTES)]
        _package(notes, k + 1, f"note-{k + 1:02d}", "заметка",
                 {"facebook": {"text": text}, "linkedin": {"text": text}})
    tips = _folder(paths.stock, "tips", "Советы", "text")
    for k in range(6):
        text = TIPS[k % len(TIPS)]
        _package(tips, k + 1, f"tip-{k + 1:02d}", "совет",
                 {"facebook": {"text": text}, "linkedin": {"text": text}, "x": {"text": text}})

    # ------------------------------------------------------------ rules
    rules = [
        {"id": "city-main", "folder": "city", "targets": [p[n] for n in config.NETWORKS],
         "days": ["mon", "wed", "fri"], "hours": ["10:00"], "timezone": "Europe/Berlin",
         "status": "active", "active_since": "2026-09-07T00:00:00Z"},
        {"id": "quotes-main", "folder": "quotes",
         "targets": [p["facebook"], "fb:demo", "linkedin", "x"],
         "days": ["tue", "thu"], "hours": ["12:00"], "timezone": "Europe/Berlin",
         "status": "active", "active_since": "2026-09-08T00:00:00Z"},
        {"id": "notes-draft", "folder": "notes", "targets": [p["facebook"], "linkedin"],
         "days": ["thu", "sat"], "hours": ["17:00"], "timezone": "Europe/Lisbon",
         "status": "draft"},
        {"id": "tips-ig", "folder": "tips", "targets": [p["instagram"]],
         "days": ["sun"], "hours": ["09:00"], "timezone": "Europe/Berlin", "status": "draft"},
    ]
    _write_json(paths.rules, {"schema": 1, "rules": rules})
    ruleset = fruleset.load(paths.rules)

    # ------------------------------------------------------------ 60 days of history
    os.makedirs(paths.poster_state, exist_ok=True)
    os.makedirs(paths.state, exist_ok=True)
    stock = fstock.load(paths.stock, library, paths.packages)
    records, journal, ledger = [], [], []
    ledger.append({"ts": "2026-10-02T08:00:00Z", "month": "2026-10", "rid": "r-earlier",
                   "op": "post", "price": "4.000", "package": "earlier", "status": "reserved"})
    ledger.append({"ts": "2026-10-02T08:00:01Z", "month": "2026-10", "rid": "r-earlier",
                   "status": "ok"})
    special = {
        ("city-main", "2026-10-19"): "missed-off",
        ("city-main", "2026-10-26"): "x-budget",
        ("city-main", "2026-10-28"): "x-budget",
        ("city-main", "2026-10-30"): "x-budget",
        ("city-main", "2026-11-06"): "failed-unknown",
        ("quotes-main", "2026-10-20"): "missed-off",
        ("quotes-main", "2026-11-10"): "token",
    }
    start = NOW - dt.timedelta(days=HISTORY_DAYS)
    for rule in ruleset.rules:
        if not rule.active:
            continue
        since = config.parse_utc(rule.active_since)
        entries = iter(stock.folders[rule.folder].entries)
        for slot in planner.rule_slots(rule, max(since, start), NOW):
            key = f"{rule.id}@{config.iso_utc(slot.when)}"
            local_day = slot.when.astimezone(rule.zone).date().isoformat()
            case = special.get((rule.id, local_day), "ok")
            claim_ts = slot.when + dt.timedelta(seconds=20)
            if case == "missed-off":
                journal.append({"ts": config.iso_utc(slot.when + dt.timedelta(hours=14)),
                                "slot": key, "status": "missed", "reason": "off"})
                continue
            entry = next(entries)
            while not entry.approved or entry.problems:
                entry = next(entries)
            targets = list(rule.targets)
            skipped = {"x": "budget"} if case == "x-budget" else {}
            sent = [t for t in targets if t not in skipped]
            journal.append({"ts": config.iso_utc(claim_ts), "slot": key, "status": "claimed",
                            "rule": rule.id, "folder": entry.folder, "file": entry.file,
                            "package": entry.id, "fp": list(entry.fingerprint), "targets": sent,
                            **({"skipped": skipped} if skipped else {})})
            outcome = {}
            for n, t in enumerate(sent):
                network = config.parse_target(t).network
                ts = config.iso_utc(claim_ts + dt.timedelta(seconds=5 + n))
                status = "published"
                row = {"ts": ts, "package": entry.id, "target": t, "network": network}
                if case == "failed-unknown" and t == "linkedin":
                    status = "failed"
                    row["error"] = "HTTP 500 from LinkedIn: internal server error; try later"
                elif case == "failed-unknown" and t == "x":
                    status = "unknown"
                    row["error"] = "connection reset after the request was sent"
                elif case == "token" and t == "fb:demo":
                    status = "failed"
                    row["error"] = ("Graph code 190: Error validating access token "
                                    + CANARIES["FB_PAGE_DEMO_TOKEN"])
                row["status"] = status
                if status == "published":
                    post_id = f"{DOMAIN[network]}-{entry.id}-{n}"
                    row["post_id"] = post_id
                    row["url"] = f"https://example.com/{DOMAIN[network]}/{post_id}"
                records.append(row)
                outcome[t] = status
                if network == "x" and status in ("published", "unknown"):
                    month = slot.when.strftime("%Y-%m")
                    price = "0.215" if entry.package.variants["x"].image_path else "0.015"
                    rid = f"r-{entry.id}"
                    ledger.append({"ts": ts, "month": month, "rid": rid, "op": "post",
                                   "price": price, "package": entry.id, "status": "reserved"})
                    ledger.append({"ts": ts, "month": month, "rid": rid,
                                   "status": "ok" if status == "published" else "reserved"})
            outcome.update({t: fjournal.SKIPPED_BUDGET for t in skipped})
            bad = any(v in ("failed", "unknown") for v in outcome.values())
            journal.append({"ts": config.iso_utc(claim_ts + dt.timedelta(seconds=40)),
                            "slot": key, "status": "done", "exit": 1 if bad else 0,
                            "outcome": outcome})
    # one manual publication, outside the factory
    records.append({"ts": "2026-11-03T15:12:00Z", "package": "manual-note",
                    "target": p["facebook"], "network": "facebook", "status": "published",
                    "post_id": "fb-manual-1", "url": "https://example.com/fb/fb-manual-1"})
    records.sort(key=lambda r: r["ts"])
    journal.sort(key=lambda r: r["ts"])
    poster_state.append_jsonl(os.path.join(paths.poster_state, poster_state.RECORD_FILE), records)
    poster_state.append_jsonl(os.path.join(paths.poster_state, poster_state.LEDGER_FILE), ledger)
    poster_state.append_jsonl(os.path.join(paths.state, fjournal.RUNS), journal)
    fjournal.write_heartbeat(paths.state, {"ts": config.iso_utc(NOW - dt.timedelta(minutes=2)),
                                           "version": "test", "due": 0, "published": 0,
                                           "errors": 0})

    # ------------------------------------------------------------ stats (lane L2's files)
    rnd = random.Random(11)
    published = [r for r in records if r["status"] == "published"
                 and r["network"] in ("facebook", "instagram")]
    posts = []
    for k, r in enumerate(published[-40:]):
        m = {"target": r["target"], "network": r["network"], "post_id": r["post_id"],
             "date": r["ts"][:10]}
        if r["network"] == "instagram":
            views = 0 if k % 9 == 4 else rnd.randint(300, 9000) * (40 if k % 13 == 0 else 1)
            m.update(views=views, likes=rnd.randint(0, 900) if views else 0,
                     comments=rnd.randint(0, 60) if views else 0, saves=rnd.randint(0, 200),
                     shares=rnd.randint(0, 80))
        elif r["target"] == "fb:demo":
            m.update(likes=rnd.randint(0, 30), comments=rnd.randint(0, 5), shares=rnd.randint(0, 4))
        else:
            m.update(views=rnd.randint(100, 4000), likes=rnd.randint(2, 120),
                     comments=rnd.randint(0, 20), shares=rnd.randint(0, 15))
        posts.append(m)
    followers = {}
    today = NOW.date()
    series = {p["facebook"]: (1520, 2.1), p["instagram"]: (5300, 4.7), "fb:demo": (431, -0.4),
              "ig:demo": (88, 0.3)}
    for target, (base, slope) in series.items():
        points = []
        for d in range(120):
            day = today - dt.timedelta(days=119 - d)
            wobble = rnd.randint(-3, 3)
            points.append([day.isoformat(), max(0, int(base + slope * d + wobble))])
        followers[target] = points
    stats = os.path.join(paths.state, "stats")
    _write_json(os.path.join(stats, "latest.json"),
                {"schema": 1, "collected_at": "2026-11-11T06:01:00Z", "posts": posts,
                 "followers": followers})
    _write_json(os.path.join(stats, "collect.json"),
                {"ts": "2026-11-11T06:01:00Z",
                 "results": {p["facebook"]: "ok", p["instagram"]: "ok",
                             "fb:demo": "token rejected",
                             "ig:demo": "no-permission instagram_manage_insights",
                             "x": "off", "linkedin": "not built"}})
    return Fixture(root, environ, paths)


DOMAIN = {"facebook": "fb", "instagram": "ig", "x": "x", "linkedin": "li"}


# ---------------------------------------------------------------- test base

import hashlib  # noqa: E402
import http.client  # noqa: E402
import io  # noqa: E402
import threading  # noqa: E402
import urllib.parse  # noqa: E402

from tests.base import Clock, PosterTestCase  # noqa: E402


class PanelCase(PosterTestCase):
    """A panel on 127.0.0.1 port 0 over a fresh fixture, with a frozen clock. Every page the
    test reads is checked for canary secrets at cleanup (PosterTestCase.outputs)."""

    FIXTURE = "data"

    def setUp(self):
        super().setUp()
        from factory.panel import server
        build = build_data if self.FIXTURE == "data" else build_empty
        self.fx = build(os.path.join(self.root, "panel"))
        self.panel_clock = Clock(NOW)
        self.log = io.StringIO()
        self.srv = server.make_server(self.fx.paths, self.panel_clock, self.fx.machine_tz, 0,
                                      log=self.log)
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(5)

    @property
    def host(self) -> str:
        return f"127.0.0.1:{self.srv.port}"

    def request(self, method: str, path: str, body: bytes | None = None,
                headers: dict | None = None, host: str | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=30)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            all_headers = {"Host": host if host is not None else self.host}
            all_headers.update(headers or {})
            for k, v in all_headers.items():
                if v is not None:
                    conn.putheader(k, v)
            if body is not None and "Content-Length" not in all_headers:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            resp = conn.getresponse()
            data = resp.read()
        finally:
            conn.close()
        if (resp.getheader("Content-Type") or "").startswith("text/"):
            self.outputs.append(data.decode("utf-8", "replace"))
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data

    def get(self, path: str, **kw):
        status, headers, data = self.request("GET", path, **kw)
        return status, headers, data.decode("utf-8", "replace")

    def post(self, path: str, fields: dict | list, *, csrf: bool | str = True,
             origin: str | None = None, ctype: str = "application/x-www-form-urlencoded",
             host: str | None = None):
        items = list(fields.items()) if isinstance(fields, dict) else list(fields)
        if csrf is True:
            items.append(("csrf", self.srv.panel.csrf))
        elif isinstance(csrf, str):
            items.append(("csrf", csrf))
        body = urllib.parse.urlencode(items, doseq=True).encode()
        headers = {"Content-Type": ctype}
        if origin is not None:
            headers["Origin"] = origin
        status, headers, data = self.request("POST", path, body=body, headers=headers, host=host)
        return status, headers, data.decode("utf-8", "replace")

    def revision(self) -> str:
        return fruleset.load(self.fx.paths.rules).revision

    def rules_doc(self) -> dict:
        with open(self.fx.paths.rules, encoding="utf-8") as fh:
            return json.load(fh)

    def file_hash(self, path: str) -> str:
        try:
            with open(path, "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()
        except FileNotFoundError:
            return "absent"

    def state_hashes(self) -> dict:
        """Hash of every file under the fixture except the rules file and the stock."""
        out = {}
        for dirpath, _, files in os.walk(self.fx.root):
            for f in files:
                path = os.path.join(dirpath, f)
                out[os.path.relpath(path, self.fx.root)] = self.file_hash(path)
        return out
