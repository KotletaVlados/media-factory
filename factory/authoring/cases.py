"""The author's cases, outside git (authoring.md §19.3).

`content/cases.json` (0600) holds at most 30 short records: what was automated, with which
tools, and what came of it. Only the «Кейсы» form writes it, under `content/.cases.lock`.
Every Gemini text call reads it: topics see one line per case, a draft that carries a case
sees that case's whole record (§19.5).
"""
from __future__ import annotations

import os
import re
import secrets

from poster.config import iso_utc
from factory.authoring.common import Refusal, atomic, directory, lock, read, text

FILE = "cases.json"
LOCK = ".cases.lock"
MAX = 30
ID_RE = re.compile(r"c-[0-9a-f]{8}\Z")
FIELDS = (
    ("title", "Название", 80, True),
    ("what", "Что автоматизировали", 600, True),
    ("tools", "Чем: инструменты и нейросети", 200, True),
    ("result", "Что вышло", 600, True),
    ("when", "Когда (необязательно)", 40, False),
)
FULL = "кейсов уже 30 — удалите ненужные"
NOT_FOUND = "кейс не найден"


def valid_id(value) -> bool:
    return isinstance(value, str) and ID_RE.fullmatch(value) is not None


def clean(values: dict) -> dict:
    """The five fields through `common.text` (NFC, the limit, never cut); a required field
    blank after strip() is refused. Raises Refusal (409) naming the field."""
    if not isinstance(values, dict):
        raise Refusal("неверный запрос", 400)
    out = {}
    for name, label, limit, required in FIELDS:
        value = text(values.get(name, ""), limit, label.split(" (")[0])
        if required and not value.strip():
            raise Refusal(f"{label}: заполните")
        out[name] = value
    return out


def _validate(data) -> dict:
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("cases"), list):
        raise Refusal("файл кейсов повреждён — проверьте content/cases.json")
    if len(data["cases"]) > MAX:
        raise Refusal("файл кейсов повреждён — проверьте content/cases.json")
    seen = set()
    for case in data["cases"]:
        if not isinstance(case, dict) or not valid_id(case.get("id")) or case["id"] in seen:
            raise Refusal("файл кейсов повреждён — проверьте content/cases.json")
        seen.add(case["id"])
        try:
            clean(case)
        except Refusal:
            raise Refusal("файл кейсов повреждён — проверьте content/cases.json") from None
        for key in ("created", "updated"):
            if not isinstance(case.get(key), str):
                raise Refusal("файл кейсов повреждён — проверьте content/cases.json")
    return data


def load(content: str) -> dict:
    """The stored list, or an empty one when nothing is stored. An unreadable or invalid
    file is a Refusal: the caller shows the reason and sends nothing."""
    empty = {"schema": 1, "cases": []}
    if not os.path.lexists(content):
        return empty
    directory(content)
    try:
        return _validate(read(os.path.join(content, FILE)))
    except FileNotFoundError:
        return empty
    except (OSError, ValueError):
        raise Refusal("файл кейсов не читается — проверьте content/cases.json") from None


def listed(content: str) -> list:
    return load(content)["cases"]


def find(cases, cid):
    """The stored record with this id, or None."""
    if not valid_id(cid):
        return None
    return next((c for c in cases if c["id"] == cid), None)


def _write(content: str, mutate, now):
    directory(content, True)
    with lock(os.path.join(content, LOCK)):
        data = load(content)
        result = mutate(data)
        data["updated"] = iso_utc(now)
        atomic(os.path.join(content, FILE), data)
        return result


def save(content: str, values: dict, now, cid: str = "") -> dict:
    """Add a case (no `cid`) first in the list, or replace the five fields and `updated` of
    the case `cid` (404 when it is not stored). Returns the stored record."""
    fields = clean(values)
    if cid and not valid_id(cid):
        raise Refusal(NOT_FOUND, 404)
    stamp = iso_utc(now)

    def mutate(data):
        cases = data["cases"]
        if cid:
            case = find(cases, cid)
            if case is None:
                raise Refusal(NOT_FOUND, 404)
            case.update(fields, updated=stamp)
            return case
        if len(cases) >= MAX:
            raise Refusal(FULL)
        taken = {c["id"] for c in cases}
        for _ in range(100):
            new = "c-" + secrets.token_hex(4)
            if new not in taken:
                break
        else:
            raise Refusal("не удалось создать кейс — повторите")
        case = dict({"id": new}, **fields, created=stamp, updated=stamp)
        cases.insert(0, case)
        return case
    return _write(content, mutate, now)


def delete(content: str, cid: str, now) -> None:
    if not valid_id(cid):
        raise Refusal(NOT_FOUND, 404)

    def mutate(data):
        if find(data["cases"], cid) is None:
            raise Refusal(NOT_FOUND, 404)
        data["cases"] = [c for c in data["cases"] if c["id"] != cid]
    _write(content, mutate, now)


def gist(cases) -> str:
    """The topics block on a draft without a case (§19.5): id, title and tools only."""
    if not cases:
        return "Cases: none recorded."
    lines = [f"{c['id']}: {c['title']} (tools: {c['tools']})" for c in cases]
    return "Cases (the author's own records; id, title and tools only):\n" + "\n".join(lines)


def record(case) -> str:
    """The whole record of the draft's case (§19.5)."""
    lines = [f"Case {case['id']} (the only source of facts about it):",
             f"Title: {case['title']}", f"What was automated: {case['what']}",
             f"Tools: {case['tools']}", f"Result: {case['result']}"]
    if case.get("when", "").strip():
        lines.append(f"When: {case['when']}")
    return "\n".join(lines)


NONE_CHOSEN = ("Case: none chosen. Do not present any project, client or result as the author's own "
               "experience unless the topic or the profile states it.")
