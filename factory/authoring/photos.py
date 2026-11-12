"""Photos uploaded into photo-lane stock folders (design authoring.md §6, slice A of §15.1).

Layout of one folder (dirs 0700, files 0600, all under the git-ignored content folder):

    stock/<folder>/photos/<id>.<jpg|png|webp>   the original, byte-identical (EXIF kept)
    stock/<folder>/photos/thumb/<id>.jpg        480 px long side, made by the browser
    stock/<folder>/photos/view/<id>.jpg         1 600 px long side, made by the browser
    stock/<folder>/photos/index.jsonl           one row per complete photo

The server never decodes or re-encodes pixels: it streams each body to a temp file with a
hard length, sniffs it with `poster.rules.sniff`, and moves it in place. The id is `p-` plus
the first 16 hex digits of the original's SHA-256. A photo is listed only when its index row
exists; the row is written by the last of the three posts (`view`), so an upload cut short
leaves invisible files that the next attempt overwrites. "Duplicate" means "already listed":
an original that is stored but not yet indexed answers `dup: false`, so a repeat completes it.

The stock loader skips subfolders (`factory.stock`), so nothing here is seen by the factory.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re
import secrets
import stat
import unicodedata

from poster import rules as poster_rules, state as poster_state
from factory import stock as fstock
from factory.panel import strings as S

MB = 1024 * 1024
PHOTOS = "photos"
THUMB = "thumb"
VIEW = "view"
INDEX = "index.jsonl"
LOCK = ".lock"
TMP_PREFIX = ".up-"
ID_RE = re.compile(r"^p-[0-9a-f]{16}$")
KINDS = ("orig", "thumb", "view")
LIMITS = {"orig": 25 * MB, "thumb": 2 * MB, "view": 2 * MB}
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")
TYPES = {"orig": IMAGE_TYPES, "thumb": ("image/jpeg",), "view": ("image/jpeg",)}
EXT = {"jpeg": "jpg", "png": "png", "webp": "webp"}
MAX_PHOTOS = 2000
MIN_FREE = 1024 ** 3
CHUNK = 64 * 1024
MAX_NAME = 120
VERSIONS = ("thumb", "view", "orig")


class UploadError(Exception):
    """A refusal with its HTTP status and a Russian reason for the panel's JSON reply."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def limit_for(kind: str) -> int:
    """The Content-Length limit of a kind; an unknown kind gets the smallest one (and a 400
    from `store` when the body fits)."""
    return LIMITS.get(kind, min(LIMITS.values()))


def types_for(kind: str) -> tuple:
    return TYPES.get(kind, IMAGE_TYPES)


# ---------------------------------------------------------------- paths

def folder_path(stock_root: str, name: str) -> str:
    """Real path of an existing photo-lane stock folder whose real path is a direct child of
    the stock's real path; otherwise UploadError 404 (no such folder) or 409 (other lane)."""
    if not isinstance(name, str) or not fstock.NAME_RE.match(name):
        raise UploadError(404, S.UP_NO_FOLDER)
    root = os.path.realpath(stock_root)
    real = os.path.realpath(os.path.join(root, name))
    if os.path.dirname(real) != root or not os.path.isdir(real):
        raise UploadError(404, S.UP_NO_FOLDER)
    folder = fstock.Folder(name, real)
    fstock._load_folder_meta(folder)  # the loader's own reading of folder.json
    if folder.lane != "photo":
        raise UploadError(409, S.UP_NOT_PHOTO_LANE.format(name=name))
    return real


def _real_dir(path: str) -> bool:
    """A real directory, not a symlink to one."""
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def photos_dir(folder_real: str, create: bool) -> str:
    """`photos/` with its `thumb/` and `view/` (0700, created when `create`). Each must be a
    real directory, never a symlink (409); absent without `create` is 404."""
    path = os.path.join(folder_real, PHOTOS)
    for sub in (path, os.path.join(path, THUMB), os.path.join(path, VIEW)):
        if create:
            try:
                os.mkdir(sub, 0o700)
            except FileExistsError:
                pass
        if not os.path.lexists(sub):
            raise UploadError(404, S.UP_NO_PHOTO)
        if not _real_dir(sub):
            raise UploadError(409, S.UP_PHOTOS_NOT_DIR)
    return path


def original_path(photos: str, pid: str) -> str | None:
    for ext in EXT.values():
        path = os.path.join(photos, f"{pid}.{ext}")
        try:
            if stat.S_ISREG(os.lstat(path).st_mode):
                return path
        except OSError:
            continue
    return None


def file_path(stock_root: str, folder: str, pid: str, version: str) -> str | None:
    """The file `GET /photo` serves, or None. Checks the folder name, the id pattern, the
    version, that `photos/` and its subfolder are real directories, and that the file's real
    path lies inside the folder's `photos/` (design §6.5)."""
    if (not isinstance(folder, str) or not fstock.NAME_RE.match(folder)
            or not isinstance(pid, str) or not ID_RE.match(pid) or version not in VERSIONS):
        return None
    root = os.path.realpath(stock_root)
    folder_real = os.path.realpath(os.path.join(root, folder))
    if os.path.dirname(folder_real) != root:
        return None
    photos = os.path.join(folder_real, PHOTOS)
    if not _real_dir(photos):
        return None
    if version == "orig":
        path = original_path(photos, pid)
    else:
        if not _real_dir(os.path.join(photos, version)):
            return None
        path = os.path.join(photos, version, f"{pid}.jpg")
    if path is None:
        return None
    real = os.path.realpath(path)
    if not real.startswith(photos + os.sep) or not os.path.isfile(real):
        return None
    return real


# ---------------------------------------------------------------- index

def _valid_row(row: dict) -> bool:
    return (isinstance(row.get("id"), str) and bool(ID_RE.match(row["id"]))
            and row.get("ext") in EXT.values() and isinstance(row.get("name"), str)
            and all(isinstance(row.get(k), int) and not isinstance(row.get(k), bool)
                    and row[k] > 0 for k in ("w", "h", "bytes"))
            and isinstance(row.get("ts"), str))


def read_index(photos: str) -> list:
    """Index rows in upload order; malformed rows are skipped, a repeated id keeps its first
    row."""
    out, seen = [], set()
    for row in poster_state.read_jsonl(os.path.join(photos, INDEX)):
        if _valid_row(row) and row["id"] not in seen:
            seen.add(row["id"])
            out.append(row)
    return out


def list_photos(folder_dir: str) -> list:
    """The listed photos of one stock folder (empty when it has no real `photos/`)."""
    photos = os.path.join(folder_dir, PHOTOS)
    if not _real_dir(photos):
        return []
    return read_index(photos)


def clean_name(name: str, fallback: str) -> str:
    """The original's base name as data: the part after the last / or \\, control and
    format characters removed, at most 120 characters. Never used as a path."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = "".join(c for c in base if unicodedata.category(c) not in ("Cc", "Cf", "Cs"))
    base = " ".join(base.split())[:MAX_NAME]
    return base or fallback


# ---------------------------------------------------------------- upload

def check_space(path: str, length: int) -> None:
    st = os.statvfs(path)
    if st.f_bavail * st.f_frsize < MIN_FREE + length:
        raise UploadError(507, S.UP_NO_SPACE)


def receive(rfile, length: int, directory: str) -> tuple:
    """Stream exactly `length` bytes into a new temp file in `directory` (O_EXCL, 0600) and
    return (temp path, SHA-256 hex). A short body removes the temp file (400)."""
    tmp = os.path.join(directory, TMP_PREFIX + secrets.token_hex(8))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as fh:
            left = length
            while left > 0:
                chunk = rfile.read(min(CHUNK, left))
                if not chunk:
                    raise UploadError(400, S.UP_CUT)
                fh.write(chunk)
                digest.update(chunk)
                left -= len(chunk)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        _unlink(tmp)
        raise
    return tmp, digest.hexdigest()


def _unlink(path: str | None) -> None:
    if path:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def _ts(now: _dt.datetime) -> str:
    return now.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pre_check(stock_root: str, folder: str, kind: str, pid: str) -> str:
    """Every check of §6.2 that needs no body byte; returns the `photos/` path."""
    if kind not in KINDS:
        raise UploadError(400, S.UP_BAD_KIND)
    real = folder_path(stock_root, folder)
    if kind != "orig" and not (isinstance(pid, str) and ID_RE.match(pid)):
        raise UploadError(404, S.UP_NO_PHOTO)
    photos = photos_dir(real, create=kind == "orig")
    if kind == "orig":
        if len(read_index(photos)) >= MAX_PHOTOS:
            raise UploadError(409, S.UP_TOO_MANY.format(n=S.group(MAX_PHOTOS)))
    elif original_path(photos, pid) is None:
        raise UploadError(404, S.UP_NO_PHOTO)
    elif kind == VIEW and not os.path.isfile(os.path.join(photos, THUMB, f"{pid}.jpg")):
        raise UploadError(409, S.UP_THUMB_FIRST)
    return photos


def store(stock_root: str, folder: str, kind: str, pid: str, name: str, rfile, length: int,
          now: _dt.datetime) -> dict:
    """One upload body (design §6.2): `pre_check`, the free-space check, then `store_body`."""
    photos = pre_check(stock_root, folder, kind, pid)
    check_space(photos, length)
    return store_body(photos, kind, pid, name, rfile, length, now)


def store_body(photos: str, kind: str, pid: str, name: str, rfile, length: int,
               now: _dt.datetime) -> dict:
    """Stream, sniff and move one body into the `photos/` that `pre_check` returned. Returns
    `{"id", "dup"}` for `orig` and `{"id", "ok"}` for `thumb` and `view`; raises
    UploadError with nothing left behind."""
    tmp, sha = receive(rfile, length, photos)
    try:
        info = poster_rules.sniff(tmp)
        if kind == "orig" and info.format not in EXT:
            raise UploadError(415, S.UP_NOT_IMAGE)
        if kind != "orig" and info.format != "jpeg":
            raise UploadError(415, S.UP_NOT_JPEG)
        if not (info.width and info.height):
            raise UploadError(422, S.UP_NO_SIZE)
        with poster_state.locked(photos, LOCK):
            indexed = {r["id"] for r in read_index(photos)}
            if kind == "orig":
                pid = "p-" + sha[:16]
                if pid in indexed:
                    return {"id": pid, "dup": True}
                os.replace(tmp, os.path.join(photos, f"{pid}.{EXT[info.format]}"))
                tmp = None
                return {"id": pid, "dup": False}
            if kind == VIEW and pid not in indexed and len(indexed) >= MAX_PHOTOS:
                raise UploadError(409, S.UP_TOO_MANY.format(n=S.group(MAX_PHOTOS)))
            os.replace(tmp, os.path.join(photos, kind, f"{pid}.jpg"))
            tmp = None
            if kind == VIEW and pid not in indexed:
                orig = original_path(photos, pid)
                ext = orig.rsplit(".", 1)[1]
                poster_state.append_jsonl(os.path.join(photos, INDEX), [{
                    "id": pid, "name": clean_name(name, f"{pid}.{ext}"), "ext": ext,
                    "bytes": os.path.getsize(orig), "w": info.width, "h": info.height,
                    "ts": _ts(now)}])
            return {"id": pid, "ok": True}
    finally:
        _unlink(tmp)
