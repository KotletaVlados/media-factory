"""Draft storage and one-entry summary cache (authoring.md §7).

Only this module writes draft.json. Field mutations reload under .lock; the independent
.ai.lock spans a vendor request without blocking autosave. No GET creates storage.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import threading
from zoneinfo import ZoneInfo

from poster.config import iso_utc
from factory.authoring import photos
from factory.authoring.common import Refusal, atomic, directory, lock, read, text

ID_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9][a-z0-9-]*-[0-9a-f]{4}\Z")
LANGS = {"x": "en", "linkedin": "en", "instagram": "uk", "facebook": "uk"}
MAX_DRAFTS = 500
STATES = ("draft", "publishing", "partial", "published")   # D′ (authoring.md §17.2)
STATUSES = ("published", "failed", "unknown", "interrupted")
MAX_ATTEMPTS = 20
MAX_LINE = 500
SENT = "черновик уже отправлен"

# Slice C (authoring.md §18.2): the base, each network's look, the quotes and the highlight.
STYLES = ("blur", "glow", "outline")
BASES = ("orig",) + STYLES
CHOICES = {"instagram": ("4:5", "1:1", "1.91:1"), "facebook": ("orig", "4:5", "1:1", "16:9"),
           "linkedin": ("orig", "1.91:1", "1:1"), "x": ("16:9", "orig", "1:1")}
FRAMES = ("none", "white", "black", "gold")
PLACES = ("none", "top", "bottom")
QUOTE_MAX = 140
WHO_MAX = 120
LOOK_KEYS = ("ratio", "frame", "quote_at")


def _ts(value):
    try:
        dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        raise Refusal("неверная дата черновика") from None


def _line(value):
    if not isinstance(value, str) or len(value) > MAX_LINE:
        raise Refusal("неверный черновик")


def _unit(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and 0 <= value <= 1)


def _validate_send(data):
    """The D′ fields (§17.2): `focus`, `refused` and `publish`, each optional."""
    focus = data.get("focus")
    if focus is not None and (not isinstance(focus, list) or len(focus) != 2
                              or not all(_unit(v) for v in focus)):
        raise Refusal("неверный черновик")
    refused = data.get("refused")
    if refused is not None:
        if not isinstance(refused, dict) or not isinstance(refused.get("lines"), list) \
                or len(refused["lines"]) > 40:
            raise Refusal("неверный черновик")
        for line in refused["lines"]:
            _line(line)
        _ts(refused.get("ts"))
    publish = data.get("publish")
    if publish is None:
        if data["state"] != "draft":
            raise Refusal("неверный черновик")
        return
    if (not isinstance(publish, dict) or not isinstance(publish.get("package"), str)
            or not isinstance(publish.get("targets"), list) or not publish["targets"]
            or not all(isinstance(t, str) and len(t) <= 40 for t in publish["targets"])
            or not isinstance(publish.get("attempts"), list)
            or not 1 <= len(publish["attempts"]) <= MAX_ATTEMPTS):
        raise Refusal("неверный черновик")
    for attempt in publish["attempts"]:
        if not isinstance(attempt, dict) or not isinstance(attempt.get("targets"), list):
            raise Refusal("неверный черновик")
        if not all(t in publish["targets"] for t in attempt["targets"]):
            raise Refusal("неверный черновик")
        _ts(attempt.get("started"))
        if attempt.get("ended") is not None:
            _ts(attempt["ended"])
        offset = attempt.get("offset")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise Refusal("неверный черновик")
        code = attempt.get("exit")
        if code is not None and (not isinstance(code, int) or isinstance(code, bool)):
            raise Refusal("неверный черновик")
        outcome = attempt.get("outcome", {})
        if not isinstance(outcome, dict):
            raise Refusal("неверный черновик")
        for target, row in outcome.items():
            if target not in attempt["targets"] or not isinstance(row, dict) \
                    or row.get("status") not in STATUSES:
                raise Refusal("неверный черновик")
            for key in ("url", "error"):
                if row.get(key) is not None:
                    _line(row[key])


def quote_problem(value):
    """Why a quote cannot be stored (§18.2), or "": one line, at most 140 characters."""
    if not isinstance(value, str):
        return "неверный запрос"
    if "\n" in value or "\r" in value or "\u2028" in value or "\u2029" in value:
        return "цитата — одна строка, без переноса"
    if len(value) > QUOTE_MAX:
        return f"цитата — не больше {QUOTE_MAX} знаков"
    return ""


def _validate_images(data):
    """The C fields (§18.2), each optional."""
    base = data.get("base", "orig")
    if base not in BASES:
        raise Refusal("неверный черновик")
    look = data.get("look")
    if look is not None:
        if not isinstance(look, dict) or any(n not in CHOICES for n in look):
            raise Refusal("неверный черновик")
        for n, item in look.items():
            if not isinstance(item, dict) or any(k not in LOOK_KEYS for k in item):
                raise Refusal("неверный черновик")
            if (item.get("ratio", CHOICES[n][0]) not in CHOICES[n] or item.get("frame", "none") not in FRAMES
                    or item.get("quote_at", "none") not in PLACES):
                raise Refusal("неверный черновик")
    quotes = data.get("quotes")
    if quotes is not None:
        if not isinstance(quotes, dict) or any(n not in CHOICES for n in quotes):
            raise Refusal("неверный черновик")
        if any(quote_problem(q) for q in quotes.values()):
            raise Refusal("неверный черновик")
    who = data.get("who")
    if who is not None and (not isinstance(who, str) or len(who) > WHO_MAX):
        raise Refusal("неверный черновик")
    error = data.get("highlight_error")
    if error is not None:
        if (not isinstance(error, dict) or error.get("style") not in STYLES
                or not isinstance(error.get("text"), str) or len(error["text"]) > 500
                or not isinstance(error.get("model_text", ""), str) or len(error.get("model_text", "")) > 300
                or any(k not in ("style", "text", "model_text", "ts") for k in error)):
            raise Refusal("неверный черновик")
        _ts(error.get("ts"))


def look(data, network):
    """One network's look with its defaults filled (§18.2): D′'s crop when nothing is set."""
    item = (data.get("look") or {}).get(network) or {}
    ratio = item.get("ratio", CHOICES[network][0])
    quote_at = item.get("quote_at", "none")
    quote = (data.get("quotes") or {}).get(network, "") if quote_at != "none" else ""
    return {"base": data.get("base", "orig"), "ratio": ratio, "frame": item.get("frame", "none"),
            "quote_at": quote_at, "quote": quote}


def look_digest(data, network):
    """D30: 12 hex of the network's base, ratio, frame, quote place and the quote it draws."""
    value = look(data, network)
    raw = json.dumps([value[k] for k in ("base", "ratio", "frame", "quote_at", "quote")],
                     ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def default_digest(network):
    return look_digest({}, network)


def drop_changed(folder, before, after, networks):
    """Delete `out/<n>.jpg` of each network whose look digest changed between two versions of
    a draft; the caller holds the draft's `.lock` (D30). An `out` that is not a real
    directory holds no crop of ours: nothing is deleted through it."""
    out = os.path.join(folder, "out")
    try:
        if not stat.S_ISDIR(os.lstat(out).st_mode):
            return []
    except FileNotFoundError:
        return []
    dropped = []
    for n in networks:
        if look_digest(before, n) != look_digest(after, n):
            try:
                os.unlink(os.path.join(out, f"{n}.jpg"))
            except FileNotFoundError:
                pass
            dropped.append(n)
    return dropped


def validate(data):
    if not isinstance(data, dict) or data.get("schema") != 1 or data.get("state") not in STATES:
        raise Refusal("неверный черновик")
    if not valid_id(data.get("id")) or not isinstance(data.get("folder"), str):
        raise Refusal("неверный черновик")
    if (not photos.fstock.NAME_RE.fullmatch(data["folder"]) or
            not isinstance(data.get("photo"), str) or not photos.ID_RE.fullmatch(data["photo"])):
        raise Refusal("неверный черновик")
    if data.get("topics_auto") not in ("pending", "done", "manual"):
        raise Refusal("неверный черновик")
    text(data.get("topic"), 2000, "тема")
    topics = data.get("topics")
    if not isinstance(topics, list) or (topics and not 3 <= len(topics) <= 5):
        raise Refusal("неверный черновик")
    for item in topics:
        if not isinstance(item, dict):
            raise Refusal("неверный черновик")
        text(item.get("title"), 1000, "название темы")
        text(item.get("angle"), 1000, "ракурс темы")
    variants = data.get("variants")
    if not isinstance(variants, dict) or any(n not in LANGS for n in variants):
        raise Refusal("неверный черновик")
    for n, v in variants.items():
        if not isinstance(v, dict) or v.get("lang") != LANGS[n] or v.get("source") not in ("gemini", "edited"):
            raise Refusal("неверный черновик")
        text(v.get("text"), 5000, "текст")
    for field in ("created", "updated"):
        try:
            dt.datetime.fromisoformat(data[field].replace("Z", "+00:00"))
        except (ValueError, TypeError, KeyError, AttributeError):
            raise Refusal("неверная дата черновика") from None
    error = data.get("error")
    if error is not None and (not isinstance(error, dict) or error.get("op") not in (
            "topics", "expand", "regenerate", "voice") or not isinstance(error.get("text"), str)):
        raise Refusal("неверная ошибка черновика")
    _validate_send(data)
    _validate_images(data)
    return data


def valid_id(did):
    return isinstance(did, str) and len(did) <= 80 and ID_RE.fullmatch(did) is not None


def stage(d):
    """Where a draft stands, for the list: the D′ states first (publishing, partial,
    published, or interrupted when its last attempt holds an interrupted target), then
    error, over, texts, topics, topic or new. A `publishing` draft whose publisher died is
    told apart by the server (it needs the publish lock), never stored."""
    from poster import rules
    if d["state"] != "draft":
        last = d["publish"]["attempts"][-1].get("outcome", {})
        if d["state"] == "partial" and any(r["status"] == "interrupted" for r in last.values()):
            return "interrupted"
        return d["state"]
    if d["error"]:
        return "error"
    if d["variants"]:
        broken = any(rules.check_text(n, v["text"]).errors for n, v in d["variants"].items())
        return "over" if broken else "texts"
    return "topics" if d["topics"] else "topic" if d["topic"].strip() else "new"


class Store:
    def __init__(self, content, clock, machine_tz):
        self.content, self.clock, self.machine_tz = content, clock, machine_tz
        self.root = os.path.join(content, "drafts")
        self._key, self._summaries = None, []
        self._cache_lock = threading.Lock()

    def path(self, did):
        if not valid_id(did):
            raise Refusal("черновик не найден", 404)
        directory(self.content)
        directory(self.root)
        return directory(os.path.join(self.root, did))

    def load(self, did):
        try:
            data = validate(read(os.path.join(self.path(did), "draft.json")))
            if data["id"] != did:
                raise Refusal("неверный черновик")
            return data
        except (OSError, ValueError):
            raise Refusal("черновик не найден", 404) from None

    def create(self, stock, folder, photo, key):
        if (not isinstance(folder, str) or not isinstance(photo, str) or
                not photos.ID_RE.fullmatch(photo)):
            raise Refusal("фото не найдено", 404)
        real = photos.folder_path(stock, folder)
        indexed = photos.read_index(os.path.join(real, photos.PHOTOS))
        if not any(p["id"] == photo for p in indexed):
            raise Refusal("фото не найдено", 404)
        directory(self.content, True)
        directory(self.root, True)
        with lock(os.path.join(self.root, ".create.lock")):
            if len(self.summaries()) >= MAX_DRAFTS:
                raise Refusal("черновиков уже 500 — удалите ненужные")
            date = self.clock().astimezone(ZoneInfo(self.machine_tz)).date().isoformat()
            # Build under a dot-name so concurrent lists never see a half-created draft.
            # os.mkdir still claims the id, under the cross-process creation lock.
            for _ in range(100):
                did = f"{date}-{folder}-{secrets.token_hex(2)}"
                if not valid_id(did):
                    raise Refusal("слишком длинное имя папки")
                target = os.path.join(self.root, did)
                if not os.path.lexists(target):
                    break
            else:
                raise Refusal("не удалось создать черновик — повторите")
            prepared = os.path.join(self.root, ".new-" + secrets.token_hex(8))
            os.mkdir(prepared, 0o700)
            try:
                ts = iso_utc(self.clock())
                data = {"schema": 1, "id": did, "created": ts, "updated": ts,
                        "folder": folder, "photo": photo, "topics_auto": "pending" if key else "manual",
                        "topics": [], "topic": "", "variants": {}, "error": None, "state": "draft"}
                atomic(os.path.join(prepared, "draft.json"), validate(data))
                os.rename(prepared, target)
            finally:
                if os.path.isdir(prepared):
                    shutil.rmtree(prepared)
            return data

    def locked(self, did):
        """The draft's short `.lock` (§7.2). flock belongs to the open file, so a holder
        writes with `save`, never with `update` (a second open would wait on itself)."""
        return lock(os.path.join(self.path(did), ".lock"))

    def save(self, did, data):
        """Write a whole draft; the caller holds `locked(did)`."""
        data["updated"] = iso_utc(self.clock())
        atomic(os.path.join(self.path(did), "draft.json"), validate(data))
        return data

    def update(self, did, mutate, sent_ok=False):
        """A field write under `.lock`. Only a draft in state `draft` takes operator and AI
        edits (§17.2: a sent draft is read-only); the send code passes `sent_ok`."""
        with self.locked(did):
            data = self.load(did)
            if data["state"] != "draft" and not sent_ok:
                raise Refusal(SENT)
            mutate(data)
            return self.save(did, data)

    def remove(self, did):
        """Delete a draft folder; the caller holds `locked(did)`. It is renamed to a dot-name
        first, so a list never sees half of it, then removed."""
        path = self.path(did)
        gone = os.path.join(self.root, f".gone-{did}-{secrets.token_hex(4)}")
        os.rename(path, gone)
        shutil.rmtree(gone, ignore_errors=True)

    def ai_lock(self, did):
        return lock(os.path.join(self.path(did), ".ai.lock"), nonblocking=True)

    def summaries(self):
        if not os.path.lexists(self.root):
            return []
        directory(self.content)
        directory(self.root)
        with self._cache_lock:
            with os.scandir(self.root) as entries:
                key = tuple(sorted((e.name, e.inode(), e.stat(follow_symlinks=False).st_mtime_ns,
                                    e.stat(follow_symlinks=False).st_size) for e in entries
                                   if valid_id(e.name) and e.is_dir(follow_symlinks=False)))
            if key != self._key:
                rows = []
                for did, *_ in key:
                    try:
                        d = self.load(did)
                    except Refusal as exc:   # deleted or queued between the scan and the read
                        if exc.status != 404:
                            raise
                        continue
                    rows.append(dict({k: d[k] for k in ("id", "folder", "photo", "topic", "updated",
                                                        "state")},
                                     stage=stage(d)))
                self._summaries = sorted(rows, key=lambda d: (d["updated"], d["id"]), reverse=True)
                self._key = key
            return copy.deepcopy(self._summaries)
