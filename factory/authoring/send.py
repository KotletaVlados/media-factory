"""Slice D′ (authoring.md §17): plain crops, the review checks, the package, one publish at a
time with its status, the queue with the offered rule, and deleting a draft.

The poster is reused, never re-implemented. The review runs the steps of
`poster.cli.cmd_publish` in its order, on the same env, record and X month, and words each
problem in Russian (D21). The package is loaded by `poster.package.load`. Publishing calls
the poster's own `cli.main` in this process (by default through `factory.runner.poster_main`),
whose pre-flight runs again and is the authority. Nothing in this module sends a request.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import io
import json
import math
import os
import re
import secrets
import shutil
import stat
import threading
from dataclasses import dataclass, field
from decimal import Decimal
from zoneinfo import ZoneInfo

from poster import config, linkedin, package as poster_package, rules, state as poster_state, xapi
from factory import checks, inputs as finputs, journal as fjournal, planner, ruleset as fruleset, runner as frunner, stock as fstock
from factory.authoring import drafts, gemini, photos
from factory.authoring.common import Refusal, jpeg_exif
from factory.panel import strings as S

MB = 1024 * 1024
MAX_CROP = 8 * MB                       # the route's Content-Length limit (§14.1)
OUT = "out"
MEDIA = "media"
LOCK_FILE = ".publish.lock"
NETWORKS = ("facebook", "instagram", "linkedin", "x")
RATIO = {"instagram": (4, 5), "x": (16, 9)}          # D19: exact integer multiples
MAX_SIZE = {"instagram": (1080, 1350), "x": (1600, 900)}
LONG_SIDE = 2048                                       # Facebook and LinkedIn
BYTES = {"facebook": rules.FB_MAX_BYTES, "instagram": rules.IG_MAX_BYTES,
         "x": rules.X_MAX_BYTES}
OFFER_DAYS, OFFER_HOURS = ("mon", "wed", "fri"), ("10:00",)
TAIL_LIMIT = 4 * MB                     # record bytes read after an attempt's offset

BUSY = "публикация уже идёт — дождитесь конца"
CHANGED = "черновик изменился после проверки — проверьте ещё раз"
NOT_READY = "картинки ещё не готовы"
FOCUS_MOVED = "кадр изменился — обновите страницу"
DELETE_BUSY = "идёт публикация"
DUPLICATE = "пакет с таким id уже есть"
NO_TEXT = "нет текста — нажмите «Развернуть»"
HELD = "повторять нечего: {names} уже отмечены в журнале постера как опубликованные, удалённые или неизвестные — проверьте аккаунт"
UNKNOWN = "прошлая попытка закончилась неизвестно — проверьте аккаунт"
RELOGIN = "войдите заново: python3 -m poster login linkedin"


class Problems(Refusal):
    """A publish or queue POST refused by the review: 409 with the same list."""

    def __init__(self, lines):
        super().__init__(S.SEND_PROBLEMS)
        self.lines = list(lines)


# ---------------------------------------------------------------- crops (D18–D20)

def _round(value: float) -> int:
    """Math.round for the non-negative values here, so Python and send.js agree."""
    return int(math.floor(value + 0.5))


def crop_size(network: str, w: int, h: int) -> tuple:
    """D19: Instagram 4k x 5k (k <= 270), X 16k x 9k (k <= 100), Facebook and LinkedIn the
    original ratio with the long side min(2048, the original's). Nothing is upscaled."""
    if network in RATIO:
        a, b = RATIO[network]
        k = min(MAX_SIZE[network][0] // a, w // a, h // b)
        return a * k, b * k
    long = max(w, h)
    side = min(LONG_SIDE, long)
    if w >= h:
        return side, max(1, _round(h * side / long))
    return max(1, _round(w * side / long)), side


def crop_window(network: str, w: int, h: int, fx: float = 0.5, fy: float = 0.5) -> tuple:
    """(x, y, width, height) of the source window: the largest one of the network's ratio,
    centred on the focus and clamped inside the photo (D20); the whole photo otherwise."""
    if network not in RATIO:
        return 0, 0, w, h
    a, b = RATIO[network]
    if w * b > h * a:
        ww, wh = _round(h * a / b), h
    else:
        ww, wh = w, _round(w * b / a)
    x = _round(min(max(fx * w - ww / 2, 0), w - ww))
    y = _round(min(max(fy * h - wh / 2, 0), h - wh))
    return x, y, ww, wh


def crop_problem(network: str, info, view: tuple) -> str:
    """Why a posted crop does not fit its network (§17.5 item 3), or ""."""
    w, h = info.width, info.height
    vw, vh = view
    if network in RATIO:
        a, b = RATIO[network]
        if w * b != h * a:
            return f"соотношение сторон не {a}:{b}"
        if w > MAX_SIZE[network][0]:
            mw, mh = MAX_SIZE[network]
            return f"больше {S.group(mw)} × {S.group(mh)}"
        return ""
    if abs(w * vh - h * vw) > 0.01 * h * vw:
        return "соотношение сторон не как у фото"
    if max(w, h) > LONG_SIDE:
        return f"длинная сторона больше {S.group(LONG_SIDE)}"
    if max(w, h) < max(vw, vh):
        return "меньше копии фото"
    return ""


def image_words(network: str, info, error: str) -> str:
    """One `check_image` error in Russian (§17.4)."""
    dims = (f"{S.group(info.width)} × {S.group(info.height)} "
            if info and info.width and info.height else "")
    if "aspect ratio" in error:
        reason = (f"соотношение сторон {info.width / info.height:.3f} вне "
                  f"{rules.IG_MIN_ASPECT:g}–{rules.IG_MAX_ASPECT:g}")
    elif " accepts " in error or "not a recognised image" in error:
        reason = "нужен JPEG"
    elif "bytes," in error:
        reason = f"больше {BYTES.get(network, 0) // 1_000_000} МБ"
    elif "pixels" in error:
        reason = f"больше {S.group(rules.LI_MAX_PIXELS)} пикселей"
    elif "dimensions" in error:
        reason = "не читаются размеры"
    elif "GIF" in error:
        reason = "анимированный GIF"
    else:
        reason = "не проходит проверку постера"
    return f"картинка {dims}не подходит: {reason}"


def token_words(error: str) -> str:
    if "ISO-8601" in error:
        return f"LINKEDIN_TOKEN_EXPIRES_AT не читается — {RELOGIN}"
    return f"токен истёк или истекает в ближайшие 10 минут — {RELOGIN}"


# ---------------------------------------------------------------- review (D21)

@dataclass
class Facts:
    """What the review reads besides the draft: the env, the poster record and the X month,
    from the snapshot (pages) or from the files (parity tests)."""
    env: dict | None
    records: list
    x_month: Decimal
    now: dt.datetime
    env_error: str = ""


@dataclass
class Card:
    target: object                 # poster.config.Target
    text: str | None
    crop: object | None            # poster.rules.ImageInfo of out/<network>.jpg
    present: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)
    x_line: str = ""
    note: str = ""


@dataclass
class Review:
    cards: list = field(default_factory=list)
    general: list = field(default_factory=list)
    missing: list = field(default_factory=list)     # networks whose crop is not stored yet

    @property
    def problems(self) -> list:
        out = list(self.general)
        for c in self.cards:
            out.extend(f"{S.NET_NAME[c.target.network]}: {p}" for p in c.problems)
        return out


def review(draft: dict, targets: list, facts: Facts, crops: dict) -> Review:
    """The poster's own pre-flight, step by step in the order of `cmd_publish`, for the
    package `send` would write from this draft. Stricter on purpose in two places: a missing
    text is a problem (the poster skips the target), and a missing crop is listed in
    `missing` (the poster would send Facebook, LinkedIn and X without an image)."""
    rv = Review()
    settings = None
    if facts.env_error:
        rv.general.append(f".env: {facts.env_error}")
    else:
        try:
            settings = config.load_settings(facts.env)
        except config.ConfigError as exc:   # the poster stops here, before any target
            rv.general.append(f".env: {exc}")
    latest = planner.record_latest(facts.records)
    to_run = []
    for t in targets:
        variant = draft["variants"].get(t.network)
        path = crops.get(t.network)
        info = rules.sniff(path) if path else None
        card = Card(t, variant["text"] if variant else None, info)
        if variant:
            card.present = gemini.present(t.network, variant["text"])
        rv.cards.append(card)
        if path is None:
            rv.missing.append(t.network)
        if settings is None:
            continue
        if variant is None:
            card.problems.append(NO_TEXT)
            continue
        row = latest.get((draft["id"], t.id))
        if row and row.get("status") == "published":
            continue
        if row and row.get("status") == "unknown":
            card.problems.append(UNKNOWN)
            continue
        missing = t.missing(facts.env)
        if missing:
            card.problems.append(f"нет {', '.join(missing)} в .env")
        if rules.check_text(t.network, variant["text"]).errors:
            card.problems.extend(card.present["problems"] or ["текст не проходит проверку постера"])
        if info is not None:
            card.problems.extend(image_words(t.network, info, e)
                                 for e in rules.check_image(t.network, info).errors)
        if t.network == "linkedin" and not missing:
            errors, warnings = linkedin.token_problems(facts.env, facts.now)
            card.problems.extend(token_words(e) for e in errors)
            if warnings:
                left = config.parse_utc(facts.env["LINKEDIN_TOKEN_EXPIRES_AT"]) - facts.now
                card.note = S.SEND_LI_NOTE.format(n=left.days)
        to_run.append(card)
    month = S.month_lower(facts.now.month)
    for card in to_run:
        if card.target.network != "x":
            continue
        est = xapi.estimate(card.text, True, settings)
        after = facts.x_month + est
        card.x_line = S.SEND_X_LINE.format(est=f"{est:.3f}", month=month, after=f"{after:.3f}",
                                           cap=f"{settings.cap:.2f}")
        if after > settings.cap:
            card.problems.append(f"этот пост стоит ${est:.3f}, за {month} уже "
                                 f"${facts.x_month:.3f} из ${settings.cap:.2f} — не помещается в лимит")
    return rv


def seen(draft: dict, targets: list, crops: dict) -> str:
    """SHA-256 of the targets' texts and crop bytes, as the review renders them (§17.3)."""
    h = hashlib.sha256()
    for t in targets:
        variant = draft["variants"].get(t.network)
        digest = ""
        if crops.get(t.network):
            with open(crops[t.network], "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
        h.update(json.dumps([t.id, variant["text"] if variant else None, digest],
                            ensure_ascii=False).encode("utf-8") + b"\n")
    return h.hexdigest()


# ---------------------------------------------------------------- record tail and outcomes

def record_rows(path: str, offset: int, package: str, targets) -> dict:
    """target -> the last record row for `package` written after byte `offset`. Only the
    tail is read; a torn or foreign line is skipped (§17.5 item 10)."""
    out: dict = {}
    try:
        with open(path, "rb") as fh:
            size = os.fstat(fh.fileno()).st_size
            if size < offset:
                return out
            fh.seek(offset)
            data = fh.read(TAIL_LIMIT)
    except FileNotFoundError:
        return out
    for line in data.split(b"\n"):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("package") == package and row.get("target") in targets:
            out[row["target"]] = row
    return out


def _clip(text, redact) -> str:
    return redact(str(text))[:drafts.MAX_LINE]


def row_outcome(row: dict, redact) -> dict:
    status = row.get("status") if row.get("status") in ("published", "failed", "unknown") else "unknown"
    out = {"status": status}
    url = row.get("url")
    if status == "published" and isinstance(url, str) and url.startswith("https://"):
        out["url"] = _clip(url, redact)
    if row.get("error"):
        out["error"] = _clip(row["error"], redact)
    return out


def combined(publish: dict) -> dict:
    """target -> its latest outcome over the attempts that carry one."""
    out: dict = {}
    for attempt in publish["attempts"]:
        out.update(attempt.get("outcome") or {})
    return out


def refusal_lines(output: str, redact) -> list:
    """The poster's refusal lines from its captured output (exit 2)."""
    lines = []
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("- "):
            lines.append(line[2:])
        elif line.startswith("error:"):
            lines.append(line)
    if not lines:
        tail = [line.strip() for line in output.splitlines() if line.strip()]
        lines = tail[-1:] or ["exit 2"]
    return [_clip(line, redact) for line in lines[:20]]


# ---------------------------------------------------------------- files

def _real_dir(path: str, create: bool = False) -> str | None:
    if create:
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            pass
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(mode):
        raise Refusal("папка для картинок — не каталог (ссылка или файл)")
    return path


def _write_new(path: str, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def _unlink(path) -> None:
    if path:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def next_number(folder: str) -> int:
    """1 + the largest three-digit prefix of the folder's package files."""
    found = [int(m[1]) for name in os.listdir(folder)
             if (m := re.match(r"(\d{3})-.*\.json\Z", name))]
    return max(found, default=0) + 1


# ---------------------------------------------------------------- the sender

class Sender:
    """Owns slice D′'s writes and the one publish thread of this panel (D22)."""

    def __init__(self, paths, clock, machine_tz, store, holder, redactor, log,
                 publish=None, targets=None):
        self.paths, self.clock, self.machine_tz = paths, clock, machine_tz
        self.store, self.holder, self.redactor, self.log = store, holder, redactor, log
        self.publish_fn = publish or frunner.poster_main
        self.target_ids = tuple(targets or config.PROFILES["kotleta"])
        self._mutex = threading.Lock()
        self._thread: threading.Thread | None = None
        self._live: str | None = None

    # ------------------------------------------------------------ basics

    def targets(self) -> list:
        return config.targets_for(None, ",".join(self.target_ids))

    def networks(self) -> list:
        out = []
        for t in self.targets():
            if t.network not in out:
                out.append(t.network)
        return out

    def redact(self, text) -> str:
        return self.redactor().redact(text)

    def _say(self, line: str) -> None:
        print(self.redact(line), file=self.log, flush=True)

    @property
    def record_path(self) -> str:
        return os.path.join(self.paths.poster_state, poster_state.RECORD_FILE)

    def _record_size(self) -> int:
        try:
            return os.path.getsize(self.record_path)
        except FileNotFoundError:
            return 0

    def _now(self) -> str:
        return config.iso_utc(self.clock())

    def facts(self, snap=None) -> Facts:
        snap = snap or self.holder.get()
        now = self.clock()
        if snap.inputs is None:
            return Facts(None, [], Decimal(0), now, snap.env_error or "не читается")
        month = now.astimezone(dt.timezone.utc).strftime("%Y-%m")
        return Facts(snap.inputs.env, snap.inputs.records,
                     snap.inputs.x_spent.get(month, Decimal(0)), now)

    # ------------------------------------------------------------ crops

    def out_dir(self, did: str, create: bool = False) -> str | None:
        return _real_dir(os.path.join(self.store.path(did), OUT), create)

    def crops(self, did: str) -> dict:
        """network -> path of out/<network>.jpg for each target network that has one. An
        out/ that is not a real directory counts as no crops (the image POST refuses it)."""
        try:
            out = self.out_dir(did)
        except Refusal:
            return {}
        found = {}
        for n in self.networks():
            path = os.path.join(out, f"{n}.jpg") if out else None
            try:
                if path and stat.S_ISREG(os.lstat(path).st_mode):
                    found[n] = path
            except FileNotFoundError:
                pass
        return found

    def crop_file(self, did: str, name: str) -> str | None:
        """The file GET /create/<id>/file serves: a target network's crop that sniffs JPEG."""
        if name not in NETWORKS:
            return None
        try:
            self.store.load(did)
        except Refusal:
            return None
        path = self.crops(did).get(name)
        if path is None or rules.sniff(path).format != "jpeg":
            return None
        return path

    def view_size(self, draft: dict) -> tuple:
        try:
            folder = photos.folder_path(self.paths.stock, draft["folder"])
        except photos.UploadError as exc:
            raise Refusal(exc.message, exc.status) from None
        row = next((r for r in photos.read_index(os.path.join(folder, photos.PHOTOS))
                    if r["id"] == draft["photo"]), None)
        if row is None:
            raise Refusal("фото не найдено", 404)
        return row["w"], row["h"]

    @staticmethod
    def focus(draft: dict) -> list:
        return draft.get("focus") or [0.5, 0.5]

    def store_crop(self, did: str, network: str, fx: str, fy: str, body: bytes) -> dict:
        """POST /create/<id>/image (§17.5 item 3): sniff, Exif walk, `check_image`, the
        network's ratio and size, the focus the page drew with; then out/.up-* moved into
        place under `.lock`. Any refusal leaves nothing behind."""
        if network not in self.networks():
            raise Refusal("неверная сеть", 400)
        try:
            focus = [round(float(fx), 3), round(float(fy), 3)]
        except ValueError:
            raise Refusal("неверный кадр", 400) from None
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in focus):
            raise Refusal("неверный кадр", 400)
        draft = self.store.load(did)
        if draft["state"] != "draft":
            raise Refusal(drafts.SENT)
        view = self.view_size(draft)
        out = self.out_dir(did, create=True)
        tmp = os.path.join(out, ".up-" + secrets.token_hex(8))
        _write_new(tmp, body)
        try:
            info = rules.sniff(tmp)
            if info.format != "jpeg" or not (info.width and info.height):
                raise Refusal("картинка должна быть JPEG")
            kind = jpeg_exif(body)
            if kind == "exif":
                raise Refusal("в картинке есть EXIF — она должна прийти из холста")
            if kind != "ok":
                raise Refusal("картинка не читается")
            errors = rules.check_image(network, info).errors
            if errors:
                raise Refusal(image_words(network, info, errors[0]))
            problem = crop_problem(network, info, view)
            if problem:
                raise Refusal(f"картинка {S.group(info.width)} × {S.group(info.height)} "
                              f"не подходит: {problem}")
            with self.store.locked(did):
                draft = self.store.load(did)
                if draft["state"] != "draft":
                    raise Refusal(drafts.SENT)
                if self.focus(draft) != focus:
                    raise Refusal(FOCUS_MOVED)
                os.replace(tmp, os.path.join(out, f"{network}.jpg"))
                tmp = None
        finally:
            _unlink(tmp)
        return {"network": network, "width": info.width, "height": info.height,
                "bytes": info.size}

    def set_focus(self, did: str, data: dict) -> dict:
        """POST /create/<id>/focus: save the point and drop the Instagram and X crops."""
        values = [data.get("fx"), data.get("fy")]
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                   and 0 <= v <= 1 for v in values):
            raise Refusal("неверный кадр", 400)
        focus = [round(float(v), 3) for v in values]

        def mutate(d):
            d["focus"] = focus
            out = self.out_dir(did)
            for n in RATIO:
                if out:
                    _unlink(os.path.join(out, f"{n}.jpg"))
        self.store.update(did, mutate)
        return {"focus": focus}

    # ------------------------------------------------------------ checks before a write

    def _ready(self, draft: dict, seen_value: str, facts: Facts):
        """Under `.lock`: crops present, `seen` equal, the review clean. Returns
        (targets, crops)."""
        if draft["state"] != "draft":
            raise Refusal(drafts.SENT)
        targets = self.targets()
        crops = self.crops(draft["id"])
        if any(t.network not in crops for t in targets):
            raise Refusal(NOT_READY)
        if not isinstance(seen_value, str) or seen_value != seen(draft, targets, crops):
            raise Refusal(CHANGED)
        rv = review(draft, targets, facts, crops)
        if rv.problems:
            raise Problems(rv.problems)
        return targets, crops

    def _unique(self, did: str, snap) -> None:
        if os.path.lexists(os.path.join(self.paths.packages, f"{did}.json")):
            raise Refusal(DUPLICATE)
        # the factory's own reader: a one-off package under any file name, by its declared id
        if did in fstock._package_ids(self.paths.packages):
            raise Refusal(DUPLICATE)
        if snap.inputs is not None:
            for folder in snap.inputs.stock.folders.values():
                for e in folder.entries:
                    if e.id == did or e.file.endswith(f"-{did}.json"):
                        raise Refusal(DUPLICATE)

    def _write_package(self, folder: str, name: str, draft: dict, targets: list,
                       crops: dict) -> tuple:
        """Media first (prepared under a dot-name, renamed into place), then the package (a
        dot-file put in place with os.link, which refuses an existing name), then
        `poster.package.load`; a failure removes what this call wrote."""
        did = draft["id"]
        media = _real_dir(os.path.join(folder, MEDIA), create=True)
        final_media = os.path.join(media, did)
        final = os.path.join(folder, name)
        if os.path.lexists(final_media) or os.path.lexists(final):
            raise Refusal(DUPLICATE)
        prepared = os.path.join(media, f".{did}-{secrets.token_hex(4)}")
        os.mkdir(prepared, 0o700)
        variants = {}
        try:
            for t in targets:
                n = t.network
                with open(crops[n], "rb") as fh:
                    _write_new(os.path.join(prepared, f"{n}.jpg"), fh.read())
                variants[n] = {"text": draft["variants"][n]["text"],
                               "image": f"{MEDIA}/{did}/{n}.jpg"}
            os.rename(prepared, final_media)
            prepared = None
        finally:
            if prepared:
                shutil.rmtree(prepared, ignore_errors=True)
        today = self.clock().astimezone(ZoneInfo(self.machine_tz)).date().isoformat()
        doc = {"schema": 1, "id": did, "theme": draft["topic"], "variants": variants,
               "meta": {"approved_by_operator": today, "source": "panel", "photo": draft["photo"]}}
        tmp = os.path.join(folder, f".{name}.{secrets.token_hex(4)}")
        try:
            # the media directory is ours from the rename on: any failure before the package
            # is linked (a full disk at the JSON write, an existing name) removes it again
            try:
                _write_new(tmp, (json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
                           .encode("utf-8"))
                os.link(tmp, final)
            except FileExistsError:
                raise Refusal(DUPLICATE) from None
            finally:
                _unlink(tmp)
        except BaseException:
            shutil.rmtree(final_media, ignore_errors=True)
            raise
        try:
            poster_package.load(final, self.paths.library)
        except poster_package.PackageError as exc:
            _unlink(final)
            shutil.rmtree(final_media, ignore_errors=True)
            raise Refusal("пакет не прошёл проверку постера: "
                          + self.redact("; ".join(exc.problems[:3]))) from None
        return final, final_media

    # ------------------------------------------------------------ the publish lock

    def _lock_path(self) -> str:
        return os.path.join(self.store.root, LOCK_FILE)

    def _take_lock(self, refusal: str = BUSY) -> int:
        drafts.directory(self.paths.content, True)
        drafts.directory(self.store.root, True)
        fd = os.open(self._lock_path(), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise Refusal(refusal) from None
        return fd

    @staticmethod
    def _release(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def lock_free(self) -> bool:
        """True when no process holds the publish lock. Read-only: an absent lock file is
        free, and the probe opens the file without creating it (GETs never write)."""
        try:
            fd = os.open(self._lock_path(), os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return True
        except OSError:
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            return True
        finally:
            os.close(fd)

    def live(self, did: str | None = None) -> bool:
        with self._mutex:
            return self._live is not None and (did is None or self._live == did)

    def busy(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def join(self, timeout=None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    # ------------------------------------------------------------ publish now (§17.5 8–12)

    def publish(self, did: str, seen_value: str) -> None:
        fd = self._take_lock()
        handed = False
        try:
            snap = self.holder.get()
            with self.store.locked(did):
                draft = self.store.load(did)
                targets, crops = self._ready(draft, seen_value, self.facts(snap))
                self._unique(did, snap)
                drafts.directory(self.paths.content, True)
                _real_dir(self.paths.packages, create=True)
                path, media = self._write_package(self.paths.packages, f"{did}.json", draft,
                                                  targets, crops)
                ids = [t.id for t in targets]
                try:
                    draft["state"] = "publishing"
                    draft.pop("refused", None)
                    draft["publish"] = {"package": f"packages/{did}.json", "targets": ids,
                                        "attempts": [self._attempt(ids)]}
                    self.store.save(did, draft)
                except BaseException:
                    _unlink(path)
                    shutil.rmtree(media, ignore_errors=True)
                    raise
            self._start(fd, did, path, ids)
            handed = True
        finally:
            if not handed:
                self._release(fd)

    def _attempt(self, ids: list) -> dict:
        return {"started": self._now(), "targets": list(ids), "offset": self._record_size()}

    def retry(self, did: str) -> None:
        """POST /create/<id>/retry: the failed targets of the draft, on the same package.
        Unknown and interrupted targets are never retried here (a double post)."""
        fd = self._take_lock()
        handed = False
        try:
            with self.store.locked(did):
                draft = self.store.load(did)
                if draft["state"] == "publishing":   # interrupted: store what the record says
                    self._settle(draft, None, crashed=True)
                    self.store.save(did, draft)
                if draft["state"] != "partial":
                    raise Refusal("повторять нечего")
                pub = draft["publish"]
                outcome = combined(pub)
                failed = [t for t in pub["targets"] if outcome.get(t, {}).get("status") == "failed"]
                if not failed:
                    raise Refusal("повторять нечего: упавших сетей нет")
                failed, held = self._unheld(did, failed)
                if not failed:
                    raise Refusal(HELD.format(names=", ".join(held)))
                if len(pub["attempts"]) >= drafts.MAX_ATTEMPTS:
                    raise Refusal("попыток уже 20 — удалите черновик")
                path = os.path.join(self.paths.content, pub["package"])
                if not os.path.isfile(path):
                    raise Refusal("пакета нет — удалите черновик")
                pub["attempts"].append(self._attempt(failed))
                draft["state"] = "publishing"
                draft.pop("refused", None)
                self.store.save(did, draft)
            self._start(fd, did, path, failed)
            handed = True
        finally:
            if not handed:
                self._release(fd)

    def _unheld(self, did: str, targets: list) -> tuple:
        """(free, held): a target whose latest poster row is published, deleted or unknown, or
        that a factory slot's attempt holds, is never sent again whatever the draft's saved
        outcome says (the poster skips only a latest `published` row, so a post recovered and
        then deleted through the CLI would go out again). Read fresh, like the factory's retry
        (§9.3)."""
        records = poster_state.read_jsonl(self.record_path)
        logs = fjournal.index(poster_state.read_jsonl(os.path.join(self.paths.state, fjournal.RUNS)))
        free, held = [], []
        for t in targets:
            (held if planner.taken_elsewhere(records, logs, did, t, "") else free).append(t)
        return free, held

    def _start(self, fd: int, did: str, path: str, ids: list) -> None:
        with self._mutex:
            self._live = did
            self._thread = threading.Thread(target=self._run, args=(fd, did, path, ids),
                                            name=f"publish-{did}", daemon=True)
            self._thread.start()

    def _environ(self) -> dict:
        return {"HOME": os.environ.get("HOME", ""), "MF_ENV_FILE": self.paths.env_file,
                "MF_STATE_DIR": self.paths.poster_state, "MF_IMAGE_LIBRARY": self.paths.library}

    def argv(self, path: str, ids: list) -> list:
        return ["--env-file", self.paths.env_file, "--state-dir", self.paths.poster_state,
                "publish", path, "--targets", ",".join(ids), "--library", self.paths.library]

    def _run(self, fd: int, did: str, path: str, ids: list) -> None:
        out = io.StringIO()
        code, crashed = None, False
        try:
            try:
                code = self.publish_fn(self.argv(path, ids), environ=self._environ(),
                                       stdout=out, stderr=out, clock=self.clock)
            except Exception as exc:  # noqa: BLE001 - a crash is a state, never a lost draft
                crashed = True
                self._say(f"panel: publish {did}: {type(exc).__name__}: {exc}")
            try:
                with self.store.locked(did):
                    draft = self.store.load(did)
                    self._settle(draft, code, crashed, out.getvalue())
                    self.store.save(did, draft)
            except Exception as exc:  # noqa: BLE001
                self._say(f"panel: publish {did}: result not stored: {type(exc).__name__}: {exc}")
        finally:
            with self._mutex:
                self._live = None
            self._release(fd)

    def _settle(self, draft: dict, code, crashed: bool, output: str = "") -> None:
        """The outcome of the last attempt, from the record rows after its offset."""
        pub = draft["publish"]
        attempt = pub["attempts"][-1]
        now = self._now()
        if code == 2 and not crashed:
            draft["refused"] = {"lines": refusal_lines(output, self.redact), "ts": now}
            if len(pub["attempts"]) == 1:   # nothing was sent: back to a draft, package gone
                _unlink(os.path.join(self.paths.content, pub["package"]))
                shutil.rmtree(os.path.join(self.paths.packages, MEDIA, draft["id"]),
                              ignore_errors=True)
                del draft["publish"]
                draft["state"] = "draft"
                return
            attempt.update(ended=now, exit=2, outcome={})
            draft["state"] = "partial"
            return
        rows = record_rows(self.record_path, attempt["offset"], draft["id"], attempt["targets"])
        outcome, latest = {}, None
        for t in attempt["targets"]:
            if t in rows:
                outcome[t] = row_outcome(rows[t], self.redact)
            elif crashed:
                outcome[t] = {"status": "interrupted"}
            else:
                # no new row: the poster found it "already published", or wrote nothing
                if latest is None:
                    latest = planner.record_latest(poster_state.read_jsonl(self.record_path))
                row = latest.get((draft["id"], t))
                outcome[t] = (row_outcome(row, self.redact) if row and row.get("status") == "published"
                              else {"status": "unknown", "error": "постер не записал результат"})
        attempt.update(ended=now, exit=code, outcome=outcome)
        done = combined(pub)
        draft["state"] = ("published" if all(done.get(t, {}).get("status") == "published"
                                             for t in pub["targets"]) else "partial")

    # ------------------------------------------------------------ status (§17.5 item 10)

    def view(self, draft: dict) -> dict:
        """The status block: state, interrupted, rows and the heading line. Reads draft.json,
        plus the record tail after the offset only while the draft is `publishing`."""
        pub = draft.get("publish")
        out = {"state": draft["state"], "interrupted": False, "done": 0, "total": 0,
               "line": "", "targets": [], "failed": []}
        if not pub:
            return out
        outcome = combined(pub)
        last = pub["attempts"][-1]
        if draft["state"] == "publishing":
            rows = record_rows(self.record_path, last["offset"], draft["id"], last["targets"])
            dead = not self.live(draft["id"]) and self.lock_free()
            for t in last["targets"]:
                if t in rows:
                    outcome[t] = row_outcome(rows[t], self.redact)
                else:
                    outcome[t] = {"status": "interrupted" if dead else "waiting"}
            out["interrupted"] = dead
        else:
            out["interrupted"] = any(r["status"] == "interrupted"
                                     for r in (last.get("outcome") or {}).values())
        total = len(pub["targets"])
        done = sum(1 for t in pub["targets"] if outcome.get(t, {}).get("status") == "published")
        for t in pub["targets"]:
            network = config.parse_target(t).network
            row = outcome.get(t) or {"status": "waiting"}
            status = row["status"]
            words = S.SEND_ROW[status].format(error=row.get("error") or "")
            item = {"target": t, "network": network, "status": status, "text": words}
            if row.get("url"):
                item["url"] = row["url"]
            out["targets"].append(item)
            if status == "failed" and draft["state"] != "publishing":
                out["failed"].append(t)
        out.update(done=done, total=total)
        if out["interrupted"]:
            out["line"] = S.SEND_INTERRUPTED
        elif draft["state"] == "publishing":
            out["line"] = S.SEND_LIVE.format(done=done, total=total)
        elif draft["state"] == "published":
            out["line"] = (S.SEND_ONE.format(name=S.NET_NAME[out["targets"][0]["network"]])
                           if total == 1 else S.SEND_ALL.format(total=total))
        else:
            out["line"] = S.SEND_PARTIAL.format(done=done, total=total,
                                                word=S.plural(total, S.NET_OF_WORDS))
        return out

    def stage(self, summary: dict) -> str:
        """The list's stage word key, with «прервано» for a dead `publishing` draft."""
        if (summary["stage"] == "publishing" and not self.live(summary["id"])
                and self.lock_free()):
            return "interrupted"
        return summary["stage"]

    # ------------------------------------------------------------ queue (§17.5 13–15)

    def queue_folders(self, snap) -> list:
        """(name, title) of the photo-lane folders without problems, by name."""
        if snap.inputs is None:
            return []
        return [(name, snap.red(f.title or name)) for name, f in sorted(snap.inputs.stock.folders.items())
                if f.lane == "photo" and not f.problems]

    def rule_conflicts(self, folder: str) -> list:
        """(rule id, [target ids outside the review]) for every rule, active or draft, that
        reads `folder` and names a destination the review never showed (D24): the review and
        the package cover the fixed main-profile targets only. Reads the rules file itself,
        not the snapshot, so a rule changed after the review is seen."""
        try:
            ruleset = fruleset.load(self.paths.rules)
        except fruleset.RulesError:
            raise Refusal(S.SEND_RULES_UNREADABLE) from None
        reviewed = {t.id for t in self.targets()}
        out = []
        for rule in ruleset.rules:
            if rule.folder != folder:
                continue
            extra = [i for i in (config.parse_target(t).id for t in rule.targets) if i not in reviewed]
            if extra:
                out.append((rule.id, extra))
        return out

    @staticmethod
    def conflict_text(conflicts: list) -> str:
        return S.SEND_RULE_ELSEWHERE.format(id=conflicts[0][0], targets=", ".join(conflicts[0][1]))

    def queue(self, did: str, folder: str, rule_on: bool, seen_value: str, write_lock):
        """Returns (location, rules refusal or None)."""
        with write_lock:
            snap = self.holder.get()
            titles = dict(self.queue_folders(snap))
            with self.store.locked(did):
                draft = self.store.load(did)
                targets, crops = self._ready(draft, seen_value, self.facts(snap))
                if folder not in titles:
                    raise Refusal("в эту папку ставить нельзя")
                conflicts = self.rule_conflicts(folder)
                if conflicts:
                    raise Refusal(self.conflict_text(conflicts))
                try:
                    real = photos.folder_path(self.paths.stock, folder)
                except photos.UploadError as exc:
                    raise Refusal(exc.message, exc.status) from None
                self._unique(did, snap)
                nnn = next_number(real)
                if nnn > 999:
                    raise Refusal("в папке уже 999 пакетов — создайте новую папку")
                self._write_package(real, f"{nnn:03d}-{did}.json", draft, targets, crops)
                self.store.remove(did)
            refusal = self.offer_rule(folder, titles[folder]) if rule_on else None
        return f"/files?folder={folder}#pkg-{did}", refusal

    def active_rules(self, snap, folder: str) -> list:
        return [r for r in snap.inputs.ruleset.rules if r.active and r.folder == folder] \
            if snap.inputs is not None else []

    def offer_rule(self, folder: str, title: str):
        """D25: «пн, ср, пт в 10:00» for the folder, through `checks.activation_problems`
        on inputs loaded after the package was written; written against the loaded
        revision. A refusal saves the rule as a draft and returns the Rules refusal."""
        now = self.clock()
        inputs = finputs.load(self.paths, lambda: now, self.redactor())
        rs = inputs.ruleset
        if any(r.active and r.folder == folder for r in rs.rules):
            return None
        taken = {r.id for r in rs.rules}
        rid = next((c for c in [folder] + [f"{folder}-{k}" for k in range(2, 10)]
                    if c not in taken and fruleset.ID_RE.match(c)), None)
        base = {"status": 409, "stale": False, "form": {}, "queued": title}
        if rid is None:
            return dict(base, rule="new", problems=["нет свободного имени правила для этой папки"])
        data = {"id": rid, "folder": folder, "targets": list(self.target_ids),
                "days": list(OFFER_DAYS), "hours": list(OFFER_HOURS),
                "timezone": self.machine_tz, "status": "active",
                "active_since": config.iso_utc(now)}
        problems: list = []
        rule = fruleset.parse_rule(data, problems)
        if rule is None:
            return dict(base, rule="new", problems=problems)
        rs.rules.append(rule)
        found = checks.activation_problems(inputs, rule, now)
        if found:
            data.update(status="draft")
            data.pop("active_since")
            rs.rules[-1] = fruleset.parse_rule(data, [])
        try:
            fruleset.write(self.paths.rules, rs, rs.revision)
        except fruleset.RevisionMismatch:
            return dict(base, rule=rid, problems=[], stale=True)
        if found:
            return dict(base, rule=rid, problems=[self.redact(p) for p in found])
        return None

    # ------------------------------------------------------------ delete (§17.5 item 16)

    def delete(self, did: str) -> None:
        draft = self.store.load(did)
        fd = None
        if draft["state"] == "publishing":
            if self.live(did):
                raise Refusal(DELETE_BUSY)
            fd = self._take_lock(DELETE_BUSY)
        try:
            with self.store.locked(did):
                draft = self.store.load(did)
                if draft["state"] == "publishing" and fd is None:
                    raise Refusal(DELETE_BUSY)
                self.store.remove(did)
        finally:
            if fd is not None:
                self._release(fd)
