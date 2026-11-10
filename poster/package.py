"""Post package: one theme -> one text and one image choice per network (design §5)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from poster.config import NETWORKS
from poster.rules import nfc

TOP_KEYS = {"schema", "id", "theme", "variants", "meta"}
VARIANT_KEYS = {"text", "image"}
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")


class PackageError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class Variant:
    network: str
    text: str                    # NFC-normalised, otherwise exactly as written
    image_ref: str | None        # as written in the package
    image_path: str | None       # resolved absolute path, or None


@dataclass
class Package:
    path: str
    id: str
    theme: str
    variants: dict = field(default_factory=dict)   # network -> Variant
    meta: dict = field(default_factory=dict)


def resolve_image(ref: str, package_dir: str, library: str) -> str:
    """A value without '/' is a library name; with '/' it is a path (relative to the package)."""
    if "/" in ref:
        path = os.path.expanduser(ref)
        if not os.path.isabs(path):
            path = os.path.join(package_dir, path)
        where = "path"
    else:
        if ref.startswith(".") or not ref:
            raise ValueError(f"image library name '{ref}' may not start with '.'")
        path = os.path.join(library, ref)
        where = "library"
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise ValueError(f"image '{ref}' not found ({where}: {path})")
    return path


def load(path: str, library: str) -> Package:
    problems: list[str] = []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise PackageError([f"package file not found: {path}"]) from None
    except (ValueError, UnicodeDecodeError) as exc:
        raise PackageError([f"package is not valid UTF-8 JSON: {exc}"]) from None
    if not isinstance(data, dict):
        raise PackageError(["package must be a JSON object"])

    unknown = sorted(set(data) - TOP_KEYS)
    if unknown:
        problems.append("unknown top-level key(s): " + ", ".join(unknown))
    if data.get("schema") != 1 or isinstance(data.get("schema"), bool):
        problems.append("schema must be 1")

    pkg_id = data.get("id")
    if pkg_id is None:
        pkg_id = os.path.splitext(os.path.basename(path))[0]
    if not isinstance(pkg_id, str) or not _ID_RE.match(pkg_id):
        problems.append("id must match [a-z0-9][a-z0-9._-]{0,79} "
                        "(defaults to the file name without .json)")
        pkg_id = str(pkg_id)

    theme = data.get("theme", "")
    if not isinstance(theme, str):
        problems.append("theme must be a string")
        theme = ""
    meta = data.get("meta", {})
    if not isinstance(meta, dict):
        problems.append("meta must be an object")
        meta = {}

    variants: dict[str, Variant] = {}
    raw_variants = data.get("variants")
    if not isinstance(raw_variants, dict) or not raw_variants:
        problems.append("variants must be a non-empty object keyed by network")
        raw_variants = {}
    package_dir = os.path.dirname(os.path.abspath(path))
    for network, raw in raw_variants.items():
        if network not in NETWORKS:
            problems.append(f"unknown network '{network}' (use {', '.join(NETWORKS)})")
            continue
        if not isinstance(raw, dict):
            problems.append(f"{network}: variant must be an object")
            continue
        extra = sorted(set(raw) - VARIANT_KEYS)
        if extra:
            problems.append(f"{network}: unknown key(s) " + ", ".join(extra))
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            problems.append(f"{network}: text is required and must not be empty")
            continue
        image_ref = raw.get("image")
        image_path = None
        if image_ref is not None:
            if not isinstance(image_ref, str):
                problems.append(f"{network}: image must be a string or null")
                continue
            try:
                image_path = resolve_image(image_ref, package_dir, library)
            except ValueError as exc:
                problems.append(f"{network}: {exc}")
                continue
        variants[network] = Variant(network, nfc(text), image_ref, image_path)

    if problems:
        raise PackageError(problems)
    return Package(path=os.path.abspath(path), id=pkg_id, theme=theme, variants=variants, meta=meta)
