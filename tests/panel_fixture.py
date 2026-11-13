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
    city = _folder(paths.stock, "city", "Фотографии с городских прогулок", "photo")
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


# ---------------------------------------------------------------- photos (authoring.md §15.1)

EXIF6 = (b"Exif\x00\x00MM\x00\x2a\x00\x00\x00\x08\x00\x01"
         b"\x01\x12\x00\x03\x00\x00\x00\x01\x00\x06\x00\x00\x00\x00\x00\x00")
# a 1 x 1 lossless WebP (VP8L); a trailing private chunk makes each copy's bytes distinct
# chunk: "VP8L", size 13, 13 data bytes, one pad byte (RIFF chunks are word-aligned)
WEBP_VP8L = bytes.fromhex("5650384c0d0000002f00000010071011118888fe0700")
HEIC_HEAD = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + bytes(64)


def make_exif6(w: int, h: int, seed: int) -> bytes:
    """A baseline JPEG stored w x h (landscape when w > h) whose EXIF orientation 6 tells a
    viewer to rotate it 90 degrees clockwise: shown h x w (portrait)."""
    data = make_photo(w, h, seed)
    app1 = struct.pack(">BBH", 0xFF, 0xE1, len(EXIF6) + 2) + EXIF6
    return data[:2] + app1 + data[2:]


def make_png(w: int, h: int, seed: int) -> bytes:
    """A real RGB PNG (zlib, stdlib only): a diagonal gradient whose colours depend on seed."""
    import zlib
    rnd = random.Random(seed)
    base = [rnd.randint(0, 255) for _ in range(3)]
    rows = bytearray()
    for y in range(h):
        rows.append(0)
        for x in range(w):
            t = (x + y) * 255 // max(1, w + h - 2)
            rows.extend(((base[0] + t) % 256, (base[1] + t // 2) % 256, (base[2] + 255 - t) % 256))

    def chunk(kind, payload):
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(rows)))
            + chunk(b"IEND", b""))


def make_webp(seed: int) -> bytes:
    """The 1 x 1 VP8L template plus a private 4-byte chunk carrying `seed`."""
    extra = b"MFIX" + struct.pack("<I", 4) + struct.pack("<I", seed)
    body = b"WEBP" + WEBP_VP8L + extra
    return b"RIFF" + struct.pack("<I", len(body)) + body


def store_photo(fx: Fixture, folder: str, orig: bytes, thumb: bytes, view: bytes,
                name: str) -> str:
    """Store one photo through the panel's own writer (the three bodies of an upload)."""
    from factory.authoring import photos
    stock = fx.paths.stock
    pid = photos.store(stock, folder, "orig", "", "", io.BytesIO(orig), len(orig), fx.now)["id"]
    photos.store(stock, folder, "thumb", pid, "", io.BytesIO(thumb), len(thumb), fx.now)
    photos.store(stock, folder, "view", pid, name, io.BytesIO(view), len(view), fx.now)
    return pid


PHOTO_NAMES = ("набережная", "двор", "мост", "крыши", "рынок", "площадь", "парк", "вокзал")


def build_photos(root: str, n: int = 70) -> Fixture:
    """`build_data` plus uploaded photos: `n` in the city folder (the first an EXIF-6
    original stored 1920 x 1440, shown portrait) and 2 in the nature folder. One city package
    names photo 2 and has a published row (chip "опубликовано"), another names photo 3 and
    has none (chip "в очереди")."""
    fx = build_data(root)
    ids = [store_photo(fx, "city", make_exif6(1920, 1440, 500), make_photo(360, 480, 500),
                       make_photo(1200, 1600, 500), "walk-0001-portrait.jpg")]
    for k in range(1, n):
        w, h = (640, 480) if k % 3 else (480, 640)
        orig = make_photo(w, h, 500 + k)
        small = make_photo(w * 3 // 4, h * 3 // 4, 500 + k)
        ids.append(store_photo(fx, "city", orig, small, orig,
                               f"walk-{k + 1:04d}-{PHOTO_NAMES[k % len(PHOTO_NAMES)]}.jpg"))
    for k in range(2):
        orig = make_photo(480, 640, 900 + k)
        store_photo(fx, "nature", orig, make_photo(360, 480, 900 + k), orig, f"forest-{k + 1}.jpg")
    records = poster_state.read_jsonl(os.path.join(fx.paths.poster_state, poster_state.RECORD_FILE))
    published = {r["package"] for r in records if r.get("status") == "published"}
    city = os.path.join(fx.paths.stock, "city")
    files = sorted(f for f in os.listdir(city) if f.endswith(".json") and f != fstock.FOLDER_FILE)
    done = next(f for f in files if f[4:-5] in published)
    waiting = next(f for f in reversed(files) if f[4:-5] not in published)
    for file, pid in ((done, ids[1]), (waiting, ids[2])):
        with open(os.path.join(city, file), encoding="utf-8") as fh:
            data = json.load(fh)
        data["meta"]["photo"] = pid
        _write_json(os.path.join(city, file), data)
    return fx


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


# ---------------------------------------------------------------- Создать (authoring.md §16.2)

TOPICS = [
    {"title": "Маленькие шаги", "angle": "Как ежедневные привычки помогают двигаться вперёд."},
    {"title": "Время заметить", "angle": "Почему полезно остановиться и посмотреть вокруг."},
    {"title": "Новый маршрут", "angle": "Что меняется, когда выбираешь другой путь."},
    {"title": "Простое решение", "angle": "Как убрать лишнее и оставить главное."},
    {"title": "Свежий взгляд", "angle": "Чему можно научиться у обычной прогулки."},
]
TEXTS = {
    "x": "Small steps make room for a fresh perspective. Today I am taking a moment to notice what is already around me.",
    "linkedin": ("A change of perspective often starts with a pause.\n\nI find that a short walk helps me separate urgent tasks from useful work. "
                 "It is a simple habit, but it makes the next decision easier.\n\nWhat helps you find a fresh angle at work?"),
    "instagram": "Іноді достатньо зупинитися й озирнутися. Маленькі кроки відкривають нові маршрути.\n\n#прогулянка #натхнення #звички",
    "facebook": "Сьогодні я обираю трохи сповільнитися. Під час прогулянки легше помітити те, повз що зазвичай проходжу. А що допомагає вам перемкнутися?",
}
AUTHOR_PROFILE = {"who": "Пишу про міські прогулянки та робочі звички.", "topics": "Місто, природа, прості рішення.",
                  "audience": {"x": "Curious readers", "linkedin": "Small business teams",
                               "instagram": "Люди, які люблять прогулянки", "facebook": "Друзі та спільнота"},
                  "tone": "Спокійний, конкретний", "avoid": "Гучні обіцянки"}


def gemini_reply(value, *, status="completed", path="steps", usage=None):
    from tests.base import resp
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    data = {"status": status, "usage": usage or {"total_input_tokens": 2000, "total_output_tokens": 700,
                                                "total_thought_tokens": 100, "total_tokens": 2800}}
    if path == "steps":
        data["steps"] = [{"type": "model_output", "content": [{"type": "text", "text": text}]}]
    else:
        data["output_text"] = text
    return resp(obj=data)


class FakeGemini:
    """No sockets. Calls identified from their schema/audio; private display metadata only
    picks held/error drafts. Every fixture response is synthetic, not a vendor observation."""
    def __init__(self):
        self.requests = []
        self.release = threading.Event()
        self.entered = threading.Event()
        self.hold = set()
        self.fail = set()
        self.fail_voice_once = set()   # drafts whose next voice call answers 503, then recovers
        self.fail_topics_once = set()  # drafts whose next topics call answers 503, then recovers

    def send(self, req):
        from tests.base import resp
        self.requests.append(req)
        self.entered.set()
        did = req.fields.get("draft")
        if did in self.hold and not self.release.wait(120):
            from poster.http import TransportError
            raise TransportError("fixture deadline")
        if did in self.fail:
            return resp(503, {"error": {"message": "temporarily unavailable"}})
        body = json.loads(req.body)
        schema = body.get("response_format", {}).get("schema", {}).get("properties", {})
        if did in self.fail_voice_once and not schema:
            self.fail_voice_once.discard(did)
            return resp(503, {"error": {"message": "temporarily unavailable"}})
        if "topics" in schema:
            if did in self.fail_topics_once:
                self.fail_topics_once.discard(did)
                return resp(503, {"error": {"message": "temporarily unavailable"}})
            return gemini_reply({"topics": TOPICS})
        if "x" in schema:
            return gemini_reply(TEXTS)
        if "text" in schema:
            return gemini_reply({"text": "A shorter post, with a clear point."})
        return gemini_reply("Утренняя пробежка у моря")


def build_create(root: str, key=True, ledger_usd=None, live_widths=()) -> Fixture:
    from unittest import mock
    from factory.authoring import drafts, profile, budget
    fx = build_data(root)
    if not key:
        with open(fx.paths.env_file, encoding="utf-8") as fh:
            lines = [line for line in fh if not line.startswith("GEMINI_API_KEY=")]
        with open(fx.paths.env_file, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
    ids = []
    for k in range(12):
        orig = make_photo(320, 240, 1100 + k)
        ids.append(store_photo(fx, "my-photos", orig, make_photo(160, 120, 1100 + k), orig, f"walk-{k + 1:02d}.jpg"))
    profile.save(fx.paths.content, AUTHOR_PROFILE, fx.now)
    store = drafts.Store(fx.paths.content, fx.clock, fx.machine_tz)
    fx.create_ids = {}
    states = [f"{state}-{w}" for w in live_widths for state in ("topics-loading", "expand-loading", "expand-texts", "voice", "behaviour", "autoretry")] if live_widths else ["topics", "own-topic", "texts", "over-limit", "error"]
    for i, name in enumerate(states):
        with mock.patch("factory.authoring.drafts.secrets.token_hex", return_value=f"{i + 1:04x}"):
            d = store.create(fx.paths.stock, "my-photos", ids[i % len(ids)], key)
        def fill(d):
            d["topics_auto"] = "pending" if name.startswith(("topics-loading", "autoretry")) else "done" if key else "manual"
            d["topics"] = [] if name.startswith(("own-topic", "voice", "autoretry")) else TOPICS
            d["topic"] = "Прогулянка і робочі звички" if not d["topics"] else TOPICS[1]["title"] + " — " + TOPICS[1]["angle"]
            if name in ("texts", "over-limit") or name.startswith("behaviour"):
                d["variants"] = {n: {"text": t, "lang": drafts.LANGS[n], "source": "gemini"} for n, t in TEXTS.items()}
                if name == "over-limit":
                    d["variants"]["x"]["text"] = "x" * 312
            if name == "error":
                d["error"] = {"op": "topics", "text": "Не удалось получить темы от Gemini", "ts": config.iso_utc(fx.now)}
        store.update(d["id"], fill)
        fx.create_ids[name] = d["id"]
    if ledger_usd is not None:
        ledger = budget.Ledger(fx.paths.state, fx.clock)
        from decimal import Decimal
        rid = ledger.reserve("topics", Decimal(str(ledger_usd)), Decimal("10"), "fixture")
        ledger.settle(rid, "ok", actual=Decimal(str(ledger_usd)))
    return fx


# ---------------------------------------------------------------- Отправка (authoring.md §17.6, §17.8)

PAGE_ID = PLAIN["FB_PAGE_KOTLETA_ID"]
SEND_SIZES = {"facebook": (1536, 2048), "instagram": (1080, 1350), "linkedin": (1536, 2048),
              "x": (1600, 900)}


def fb_ok(n: int = 1) -> list:
    from tests.base import resp
    return [resp(200, {"id": f"P{n}", "post_id": f"{PAGE_ID}_{n}"})]


def ig_ok() -> list:
    """Staging photo, its CDN URL, container, status, publish, permalink, staging delete and
    the check that it is gone (the shapes of tests/test_cli.py `ig_success`)."""
    from tests.base import resp
    return [resp(200, {"id": "PH1"}),
            resp(200, {"images": [{"width": 1080, "source": "https://cdn.invalid/a.jpg"}]}),
            resp(200, {"id": "C1"}), resp(200, {"status_code": "FINISHED"}),
            resp(200, {"id": "M1"}), resp(200, {"permalink": "https://www.instagram.com/p/OK/"}),
            resp(200, {"success": True}),
            resp(400, {"error": {"message": "gone", "code": 100, "error_subcode": 33}})]


def li_ok() -> list:
    from tests.base import resp
    return [resp(200, {"value": {"uploadUrl": "https://www.linkedin.com/dms-uploads/u1",
                                 "image": "urn:li:image:1"}}),
            resp(201, {}), resp(201, {}, {"x-restli-id": "urn:li:share:1"})]


def li_401(echo: str = "") -> list:
    """initializeUpload refused with 401; the body may echo a token, as a hostile vendor might."""
    from tests.base import resp
    return [resp(401, {"message": "Invalid access token " + echo, "status": 401})]


def x_ok() -> list:
    from tests.base import resp
    return [resp(200, {"data": {"id": "M77"}}), resp(201, {"data": {"id": "77"}})]


def x_403() -> list:
    from tests.base import resp
    return [resp(403, {"title": "Forbidden", "detail": "not permitted"})]


def four_ok() -> list:
    return fb_ok() + ig_ok() + li_ok() + x_ok()


class Crash(BaseException):
    """Raised inside the fake transport; not an Exception, so neither the poster's per-target
    isolation nor its last-resort path catches it, and the publish function itself raises."""


class FakePoster:
    """The panel's publish function for tests and the visual check (authoring.md §17.8): it
    calls the real `poster.cli.main` with a scripted FakeTransport (never a socket), no sleep
    and the panel's clock. `script` is one response list per call (default: four targets
    published). With `hold` (an Event), the first request after `after` record rows of the
    package waits on it; with `crash`, that request raises instead."""

    def __init__(self, script=None, hold=None, crash=False, after=1, wait=120):
        self.script = list(script) if script is not None else None
        self.hold, self.crash, self.after, self.wait = hold, crash, after, wait
        self.calls: list = []
        self.transports: list = []
        self.entered = threading.Event()     # the hold point was reached
        self.ended = threading.Event()

    def __call__(self, argv, *, environ, stdout, stderr, clock):
        from poster import cli
        from tests.base import FakeTransport
        self.calls.append(list(argv))
        self.ended.clear()
        responses = (self.script.pop(0) if self.script else []) if self.script is not None else four_ok()
        transport = FakeTransport(responses)
        record = os.path.join(argv[argv.index("--state-dir") + 1], poster_state.RECORD_FILE)
        with open(argv[argv.index("publish") + 1], encoding="utf-8") as fh:
            package = json.load(fh)["id"]
        start = os.path.getsize(record) if os.path.exists(record) else 0
        fired = []
        send = transport.send

        def gated(req):
            if not fired and (self.hold is not None or self.crash):
                with open(record, "rb") if os.path.exists(record) else io.BytesIO() as fh:
                    fh.seek(start)
                    rows = [line for line in fh.read().split(b"\n") if package.encode() in line]
                if len(rows) >= self.after:
                    fired.append(1)
                    self.entered.set()
                    if self.crash:
                        raise Crash()
                    self.hold.wait(self.wait)
            return send(req)
        transport.send = gated
        self.transports.append(transport)
        try:
            return cli.main(argv, environ=environ, transport=transport, sleep=lambda s: None,
                            clock=clock, stdout=stdout, stderr=stderr)
        except Crash:
            raise RuntimeError("the publisher stopped") from None
        finally:
            self.ended.set()


def write_crops(fx: Fixture, did: str, sizes=None, seed: int = 0) -> dict:
    """Crops at the D19 sizes stored as the browser would (out/<network>.jpg, 0600), so static
    states do not wait on the canvas. Returns network -> path."""
    from factory.authoring import drafts
    out = os.path.join(fx.paths.content, "drafts", did, "out")
    os.makedirs(out, mode=0o700, exist_ok=True)
    found = {}
    for k, (n, (w, h)) in enumerate(sorted((sizes or SEND_SIZES).items())):
        key = (w, h, seed + k)
        if key not in _CROP_CACHE:
            _CROP_CACHE[key] = make_photo(w, h, seed + k)
        path = os.path.join(out, f"{n}.jpg")
        with open(path, "wb") as fh:
            fh.write(_CROP_CACHE[key])
        os.chmod(path, 0o600)
        found[n] = path
    assert drafts.valid_id(did)
    return found


_CROP_CACHE: dict = {}
_BIG: dict = {}


def big_photo() -> bytes:
    """One 3 024 x 4 032 JPEG (about 0.9 s to generate), made once per process."""
    if "orig" not in _BIG:
        _BIG["orig"] = make_photo(3024, 4032, 4242)
        _BIG["view"] = make_photo(1200, 1600, 4242)
        _BIG["thumb"] = make_photo(360, 480, 4242)
    return _BIG["orig"]


def send_draft(fx: Fixture, store, photo: str, name: str, i: int, texts=None) -> str:
    """A draft of `my-photos` with the given texts, its id fixed by `i`."""
    from unittest import mock
    from factory.authoring import drafts
    with mock.patch("factory.authoring.drafts.secrets.token_hex", return_value=f"{0xd000 + i:04x}"):
        d = store.create(fx.paths.stock, "my-photos", photo, True)

    def fill(d):
        d["topics_auto"] = "done"
        d["topic"] = TOPICS[1]["title"] + " — " + TOPICS[1]["angle"]
        d["variants"] = {n: {"text": t, "lang": drafts.LANGS[n], "source": "gemini"}
                         for n, t in (texts or TEXTS).items()}
    store.update(d["id"], fill)
    return d["id"]


def set_sent(fx: Fixture, did: str, state: str, outcome: dict, package=True) -> None:
    """Put a fixture draft in a sent state with one finished attempt (no publisher)."""
    from factory.authoring import drafts
    store = drafts.Store(fx.paths.content, fx.clock, fx.machine_tz)
    targets = list(config.PROFILES[fcli.DEFAULT_PROFILE])
    if package:
        _write_json(os.path.join(fx.paths.packages, f"{did}.json"),
                    {"schema": 1, "id": did, "theme": "fixture", "variants": {
                        "facebook": {"text": "fixture"}},
                     "meta": {"approved_by_operator": "2026-11-11", "source": "panel"}})

    def mutate(d):
        d["state"] = state
        d["publish"] = {"package": f"packages/{did}.json", "targets": targets, "attempts": [
            {"started": config.iso_utc(fx.now), "ended": config.iso_utc(fx.now), "targets": targets,
             "offset": 0, "exit": 0 if state == "published" else 1, "outcome": outcome}]}
    store.update(did, mutate, sent_ok=True)


def build_send(root: str, *, problems=False, crash=False, live_widths=(), go_widths=()) -> Fixture:
    """The «send» fixtures of authoring.md §17.6, on top of `build_data` (its env, record and
    `city-main`): `my-photos` with one 3 024 x 4 032 photo and 12 small ones.

    - default: the drafts `ready`, `publishing`, `partial`, `published`, `queue-me` and
      `rule-me`, each with crops at the D19 sizes (the visual check posts the publish of
      `publishing` and the two queues itself);
    - `problems`: an env without FB_PAGE_KOTLETA_TOKEN, LINKEDIN_TOKEN_EXPIRES_AT in the past,
      and a draft `problems` whose X text is 312 weighted characters;
    - `crash`: one draft `crash` left in `publishing` with a Facebook row in the record;
    - `live_widths`: per width, a draft `crops-<w>` without crops and `focus-<w>` with them;
    - `go_widths`: per width, drafts `publish-<w>` and `queue-<w>` for the browser-driven submits
      of «Да, опубликовать» and «В очередь» (the real browser sends its own Origin).
    """
    from factory.authoring import drafts
    fx = build_data(root)
    if problems:
        with open(fx.paths.env_file, encoding="utf-8") as fh:
            lines = [line for line in fh if not line.startswith(("FB_PAGE_KOTLETA_TOKEN=",
                                                                 "LINKEDIN_TOKEN_EXPIRES_AT="))]
        lines.append("LINKEDIN_TOKEN_EXPIRES_AT=2026-11-01T00:00:00Z\n")
        with open(fx.paths.env_file, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
    big = store_photo(fx, "my-photos", big_photo(), _BIG["thumb"], _BIG["view"], "portrait.jpg")
    for k in range(12):
        orig = make_photo(320, 240, 1300 + k)
        store_photo(fx, "my-photos", orig, make_photo(160, 120, 1300 + k), orig, f"walk-{k + 1:02d}.jpg")
    store = drafts.Store(fx.paths.content, fx.clock, fx.machine_tz)
    fx.send_ids = {}
    if live_widths:
        names = [f"{state}-{w}" for w in live_widths for state in ("crops", "focus")]
    elif go_widths:
        names = [f"{state}-{w}" for w in go_widths for state in ("publish", "queue")]
    elif problems:
        names = ["problems"]
    elif crash:
        names = ["crash"]
    else:
        names = ["ready", "publishing", "partial", "published", "queue-me", "rule-me"]
    for i, name in enumerate(names):
        texts = dict(TEXTS, x="x" * 312) if name == "problems" else None
        did = send_draft(fx, store, big, name, i, texts)
        fx.send_ids[name] = did
        if not name.startswith("crops-"):
            write_crops(fx, did)
    if "partial" in fx.send_ids:
        set_sent(fx, fx.send_ids["partial"], "partial", {
            "fb:kotleta": {"status": "published", "url": "https://www.facebook.com/" + PAGE_ID + "_1"},
            "ig:kotleta": {"status": "published", "url": "https://www.instagram.com/p/OK/"},
            "linkedin": {"status": "failed", "error": "HTTP 401 from LinkedIn: invalid access token"},
            "x": {"status": "failed", "error": "HTTP 403 from X: not permitted"}})
    if "published" in fx.send_ids:
        set_sent(fx, fx.send_ids["published"], "published", {
            "fb:kotleta": {"status": "published", "url": "https://www.facebook.com/" + PAGE_ID + "_2"},
            "ig:kotleta": {"status": "published", "url": "https://www.instagram.com/p/OK2/"},
            "linkedin": {"status": "published", "url": "https://www.linkedin.com/feed/update/urn:li:share:2/"},
            "x": {"status": "published", "url": "https://x.com/i/web/status/78"}})
    if crash:
        did = fx.send_ids["crash"]
        record = os.path.join(fx.paths.poster_state, poster_state.RECORD_FILE)
        offset = os.path.getsize(record)
        set_sent(fx, did, "publishing", {})
        store.update(did, lambda d: d["publish"]["attempts"][0].update(
            offset=offset, outcome={}, exit=None, ended=None) or d["publish"]["attempts"][0].pop("ended"),
            sent_ok=True)
        poster_state.append_jsonl(record, [{
            "ts": config.iso_utc(fx.now), "package": did, "target": "fb:kotleta",
            "network": "facebook", "status": "published", "post_id": f"{PAGE_ID}_9",
            "url": f"https://www.facebook.com/{PAGE_ID}_9"}])
    return fx
