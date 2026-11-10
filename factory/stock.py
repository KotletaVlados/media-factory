"""Stock: folders of approved post packages (design factory.md §6.1).

A folder is `content/stock/<name>/` with a `folder.json` and post packages in the poster's
own format. Loading reads every file once; the states of §6.2 are computed by the planner
from these entries plus the record and the journal, so nothing here is stored.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from poster import package as poster_package
from poster import rules as poster_rules

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
FOLDER_FILE = "folder.json"
LANES = ("photo", "text")
APPROVAL_KEY = "approved_by_operator"


@dataclass
class Entry:
    folder: str
    file: str                       # file name inside the folder, e.g. 001-focus.json
    path: str
    id: str                         # package id (the file stem when the file is unreadable)
    package: object | None          # poster.package.Package, or None when it failed to load
    images: dict = field(default_factory=dict)   # network -> poster.rules.ImageInfo | None
    problems: list = field(default_factory=list)  # load problems, duplicate ids
    approved: bool = False
    fingerprint: tuple = (0, 0)     # (size, mtime_ns): a held package is released by a change

    def networks(self) -> set:
        return set(self.package.variants) if self.package else set()

    def check(self, networks) -> list[str]:
        """Problems for the given networks: load problems, then the poster's own checks."""
        if self.problems:
            return list(self.problems)
        found: list[str] = []
        for network in sorted(networks):
            variant = self.package.variants.get(network)
            if variant is None:
                continue
            for c in (poster_rules.check_text(network, variant.text),
                      poster_rules.check_image(network, self.images.get(network))):
                found.extend(f"{network}: {e}" for e in c.errors)
        return found


@dataclass
class Folder:
    name: str
    path: str
    title: str = ""
    lane: str | None = None         # photo | text | None when folder.json is broken
    entries: list = field(default_factory=list)
    problems: list = field(default_factory=list)


@dataclass
class Stock:
    root: str
    folders: dict = field(default_factory=dict)  # name -> Folder, sorted by name
    problems: list = field(default_factory=list)

    def entries(self):
        for name in sorted(self.folders):
            yield from self.folders[name].entries


def fingerprint(path: str) -> tuple:
    try:
        st = os.stat(path)
    except OSError:
        return (0, 0)
    return (st.st_size, st.st_mtime_ns)


def _load_folder_meta(folder: Folder) -> None:
    path = os.path.join(folder.path, FOLDER_FILE)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        folder.problems.append(f"{FOLDER_FILE} is missing")
        return
    except (ValueError, UnicodeDecodeError) as exc:
        folder.problems.append(f"{FOLDER_FILE} is not valid UTF-8 JSON: {exc}")
        return
    if not isinstance(data, dict):
        folder.problems.append(f"{FOLDER_FILE} must be a JSON object")
        return
    if data.get("schema") != 1 or isinstance(data.get("schema"), bool):
        folder.problems.append(f"{FOLDER_FILE}: schema must be 1")
    title = data.get("title", folder.name)
    folder.title = title if isinstance(title, str) else folder.name
    lane = data.get("lane")
    if lane not in LANES:
        folder.problems.append(f"{FOLDER_FILE}: lane must be photo or text")
    else:
        folder.lane = lane


def _load_entry(folder: Folder, file: str, library: str) -> Entry:
    path = os.path.join(folder.path, file)
    stem = file[:-len(".json")]
    entry = Entry(folder.name, file, path, stem, None, fingerprint=fingerprint(path))
    try:
        pkg = poster_package.load(path, library)
    except poster_package.PackageError as exc:
        entry.problems.extend(exc.problems)
        try:  # keep the declared id when the JSON itself is readable, for duplicate checks
            with open(path, encoding="utf-8") as fh:
                declared = json.load(fh).get("id")
            if isinstance(declared, str) and declared:
                entry.id = declared
        except (OSError, ValueError, AttributeError, UnicodeDecodeError):
            pass
        return entry
    entry.package, entry.id = pkg, pkg.id
    approval = pkg.meta.get(APPROVAL_KEY)
    entry.approved = isinstance(approval, str) and bool(approval.strip())
    for network, variant in pkg.variants.items():
        try:
            entry.images[network] = (poster_rules.sniff(variant.image_path)
                                     if variant.image_path else None)
        except OSError as exc:
            entry.problems.append(f"{network}: image unreadable: {exc.strerror or exc}")
    return entry


def reload_entry(entry: Entry, library: str) -> Entry:
    """Read one entry's file again, right now (the runner re-validates a package at the moment
    it publishes it, §9.4). Duplicate ids are not re-checked: they need another file."""
    return _load_entry(Folder(entry.folder, os.path.dirname(entry.path)), entry.file, library)


def _package_ids(folder: str) -> dict:
    """Ids used by one-off packages in content/packages/ (the poster record is keyed by id)."""
    ids: dict = {}
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return ids
    for name in names:
        if not name.endswith(".json") or name.startswith("."):
            continue
        pid = name[:-len(".json")]
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                declared = json.load(fh).get("id")
            if isinstance(declared, str) and declared:
                pid = declared
        except (OSError, ValueError, AttributeError, UnicodeDecodeError):
            pass
        ids.setdefault(pid, f"packages/{name}")
    return ids


def load(stock_dir: str, library: str, packages_dir: str | None = None) -> Stock:
    stock = Stock(stock_dir)
    try:
        names = sorted(os.listdir(stock_dir))
    except FileNotFoundError:
        return stock
    except OSError as exc:
        stock.problems.append(f"stock folder unreadable: {exc.strerror or exc}")
        return stock
    for name in names:
        path = os.path.join(stock_dir, name)
        if name.startswith(".") or not os.path.isdir(path):
            continue
        if not NAME_RE.match(name):
            stock.problems.append(f"folder '{name}' ignored: names match [a-z0-9][a-z0-9-]{{0,39}}")
            continue
        folder = Folder(name, path, title=name)
        _load_folder_meta(folder)
        for file in sorted(os.listdir(path)):
            if (file.startswith(".") or not file.endswith(".json") or file == FOLDER_FILE
                    or not os.path.isfile(os.path.join(path, file))):
                continue
            folder.entries.append(_load_entry(folder, file, library))
        stock.folders[name] = folder

    # A package id must be unique across the stock and content/packages/ (§6.1).
    seen: dict = {}
    for entry in stock.entries():
        seen.setdefault(entry.id, []).append(f"{entry.folder}/{entry.file}")
    outside = _package_ids(packages_dir) if packages_dir else {}
    for entry in stock.entries():
        others = [w for w in seen[entry.id] if w != f"{entry.folder}/{entry.file}"]
        if entry.id in outside:
            others.append(outside[entry.id])
        if others:
            entry.problems.append(f"duplicate id '{entry.id}' (also {', '.join(others)})")
    return stock
