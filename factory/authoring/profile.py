"""The explicit author profile, outside git (authoring.md §8.7)."""
from __future__ import annotations

import os
from poster.config import iso_utc
from factory.authoring.common import Refusal, atomic, directory, lock, read, text

FIELDS = (
    ("who", "Кто вы", 600, "Who the author is"),
    ("topics", "О чём пишете", 600, "Author's themes"),
    ("audience.x", "Аудитория в X", 300, "Audience on X"),
    ("audience.linkedin", "Аудитория в LinkedIn", 300, "Audience on LinkedIn"),
    ("audience.instagram", "Аудитория в Instagram", 300, "Audience on Instagram"),
    ("audience.facebook", "Аудитория в Facebook", 300, "Audience on Facebook"),
    ("tone", "Тон", 300, "Tone"),
    ("avoid", "Каких слов и тем избегать", 300, "Words and topics to avoid"),
)


def value(data, name):
    if name.startswith("audience."):
        return data.get("audience", {}).get(name.split(".")[1], "")
    return data.get(name, "")


def validate(data):
    if not isinstance(data, dict) or not isinstance(data.get("audience", {}), dict):
        raise Refusal("неверный профиль", 400)
    out = {"schema": 1, "audience": {}}
    for name, label, limit, _ in FIELDS:
        v = text(value(data, name), limit, label)
        if name.startswith("audience."):
            out["audience"][name.split(".")[1]] = v
        else:
            out[name] = v
    return out


def load(content):
    if not os.path.lexists(content):
        return validate({})
    directory(content)
    try:
        return validate(read(os.path.join(content, "profile.json")))
    except FileNotFoundError:
        return validate({})


def save(content, data, now):
    data = validate(data)
    data["updated"] = iso_utc(now)
    directory(content, True)
    with lock(os.path.join(content, ".profile.lock")):
        atomic(os.path.join(content, "profile.json"), data)
    return data


def prompt(data):
    lines = [f"{label}: {value(data, name)}" for name, _, _, label in FIELDS if value(data, name)]
    return "Author profile:\n" + "\n".join(lines) if lines else (
        "Author profile: not filled in; write for a general audience.")
