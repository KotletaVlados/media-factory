"""Small private storage primitives for authoring; no vendor data or recordings on disk."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import secrets
import stat
import struct
import unicodedata


class Refusal(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.message, self.status = message, status


def directory(path, create=False):
    if create:
        os.makedirs(path, mode=0o700, exist_ok=True)
    try:
        valid = stat.S_ISDIR(os.lstat(path).st_mode)
    except FileNotFoundError:
        valid = False
    if not valid:
        raise Refusal("папка данных недоступна", 404)
    return path


def read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, encoding="utf-8") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            raise Refusal("файл данных недоступен")
        return json.load(fh)


def atomic(path, data):
    tmp = path + "." + secrets.token_hex(8)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextlib.contextmanager
def lock(path, nonblocking=False):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        except BlockingIOError:
            raise Refusal("уже выполняется") from None
        yield
    finally:
        os.close(fd)


def text(value, limit, label):
    if not isinstance(value, str):
        raise Refusal("неверный запрос", 400)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise Refusal("неверный запрос", 400) from None
    value = unicodedata.normalize("NFC", value)
    if len(value) > limit:
        raise Refusal(f"{label}: не больше {limit} знаков")
    return value


def jpeg_exif(data):
    """Marker walk over at most 64 KB of JPEG headers (authoring.md §8.4); entropy-coded
    bytes are never searched. "exif" when an APP1 segment starting with "Exif\\0\\0" comes
    before the scan, "ok" at the scan or the end marker, "bad" for anything else. Shared by
    the Gemini view-copy check (B′) and the crop route (D′)."""
    pos = 2
    while pos < min(len(data), 65536):
        if data[pos] != 0xff:
            return "bad"
        while pos < len(data) and data[pos] == 0xff:
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker in (0xda, 0xd9):
            return "ok"
        if marker in range(0xd0, 0xd9) or marker == 0x01:
            continue
        if pos + 2 > len(data):
            break
        length = struct.unpack(">H", data[pos:pos + 2])[0]
        if length < 2 or pos + length > len(data) or pos + length > 65536:
            break
        if marker == 0xe1 and data[pos + 2:pos + 8] == b"Exif\x00\x00":
            return "exif"
        pos += length
    return "bad"
