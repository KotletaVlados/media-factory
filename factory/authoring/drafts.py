"""Draft storage and one-entry summary cache (authoring.md §7).

Only this module writes draft.json. Field mutations reload under .lock; the independent
.ai.lock spans a vendor request without blocking autosave. No GET creates storage.
"""
from __future__ import annotations

import copy
import datetime as dt
import os
import re
import secrets
import shutil
import threading
from zoneinfo import ZoneInfo

from poster.config import iso_utc
from factory.authoring import photos
from factory.authoring.common import Refusal, atomic, directory, lock, read, text

ID_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9][a-z0-9-]*-[0-9a-f]{4}\Z")
LANGS = {"x": "en", "linkedin": "en", "instagram": "uk", "facebook": "uk"}
MAX_DRAFTS = 500


def validate(data):
    if not isinstance(data, dict) or data.get("schema") != 1 or data.get("state") != "draft":
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
    return data


def valid_id(did):
    return isinstance(did, str) and len(did) <= 80 and ID_RE.fullmatch(did) is not None


def stage(d):
    """Where a draft stands, for the list: error, over, texts, topics, topic or new."""
    from poster import rules
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
                raise Refusal("черновиков уже 500 — удаление черновиков появится в срезе D")
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

    def update(self, did, mutate):
        path = self.path(did)
        with lock(os.path.join(path, ".lock")):
            data = self.load(did)
            mutate(data)
            data["updated"] = iso_utc(self.clock())
            atomic(os.path.join(path, "draft.json"), validate(data))
            return data

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
                    d = self.load(did)
                    rows.append(dict({k: d[k] for k in ("id", "folder", "photo", "topic", "updated")},
                                     stage=stage(d)))
                self._summaries = sorted(rows, key=lambda d: (d["updated"], d["id"]), reverse=True)
                self._key = key
            return copy.deepcopy(self._summaries)
