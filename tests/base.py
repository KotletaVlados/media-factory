"""Shared test harness (design §13): network guard, temp env/state/library folders with
canary secrets, a scripted FakeTransport, a frozen clock and tiny generated images.

No test reads the real env file, opens a non-loopback socket, or needs credentials.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import socket
import struct
import sys
import tempfile
import unittest
import zlib

from poster import cli
from poster.http import Response

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Captured before any patching, so restoring never re-installs a fake.
_ORIG_CONNECT = socket.socket.connect
_ORIG_CONNECT_EX = socket.socket.connect_ex
_ORIG_GETADDRINFO = socket.getaddrinfo
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class NetworkBlocked(AssertionError):
    pass


def _guard_connect(sock, address, *a):
    host = address[0] if isinstance(address, tuple) else address
    if host not in _LOOPBACK:
        raise NetworkBlocked(f"test tried to connect to {host}")
    return _ORIG_CONNECT(sock, address, *a)


def _guard_connect_ex(sock, address, *a):
    host = address[0] if isinstance(address, tuple) else address
    if host not in _LOOPBACK:
        raise NetworkBlocked(f"test tried to connect to {host}")
    return _ORIG_CONNECT_EX(sock, address, *a)


def _guard_getaddrinfo(host, *a, **kw):
    if host not in _LOOPBACK and host is not None:
        raise NetworkBlocked(f"test tried to resolve {host}")
    return _ORIG_GETADDRINFO(host, *a, **kw)


# Canary secret values: unique strings that must never appear in any output or state file.
CANARIES = {
    "GEMINI_API_KEY": "cnry-gemini-api-key-dd17",
    "META_USER_TOKEN": "cnry-meta-user-token-91af",
    "FB_PAGE_KOTLETA_TOKEN": "cnry-fb-kotleta-token-33cd",
    "FB_PAGE_DEMO_TOKEN": "cnry-fb-demo-token+/=4",
    "LINKEDIN_CLIENT_SECRET": "cnry-li-client-secret-55ef",
    "LINKEDIN_ACCESS_TOKEN": "cnry-li-access-token-66a0",
    "X_API_KEY": "cnry-x-api-key-77b1",
    "X_API_SECRET": "cnry-x-api-secret-88c2",
    "X_BEARER_TOKEN": "cnry-x-bearer-token-99d3",
    "X_OAUTH2_CLIENT_SECRET": "cnry-x-oauth2-secret-aae4",
    "X_ACCESS_TOKEN": "cnry-x-access-token-bbf5",
    "X_ACCESS_SECRET": "cnry-x-access-secret-cc06",
}
PLAIN = {
    "META_APP_ID": "100000000000001",
    "FB_PAGE_KOTLETA_ID": "300000000000003",
    "FB_PAGE_DEMO_ID": "400000000000004",
    "IG_KOTLETA_USER_ID": "17800000000000006",
    "LINKEDIN_CLIENT_ID": "fakeclientid77",
    "X_OAUTH2_CLIENT_ID": "fake-x-oauth2-client",
    "LINKEDIN_TOKEN_EXPIRES_AT": "2027-01-05T00:00:00Z",
    "LINKEDIN_PERSON_URN": "urn:li:person:FAKEsub123",
}
FROZEN_NOW = dt.datetime(2026, 11, 9, 10, 15, 0, tzinfo=dt.timezone.utc)


def env_text(values: dict) -> str:
    lines = ["# fake env for tests", ""]
    lines += [f"{k}={v}" for k, v in values.items()]
    return "\n".join(lines) + "\n"


class Clock:
    def __init__(self, now: dt.datetime = FROZEN_NOW):
        self.now = now

    def __call__(self) -> dt.datetime:
        return self.now


def resp(status: int = 200, obj=None, headers=None, body: bytes | None = None) -> Response:
    if body is None:
        body = json.dumps(obj if obj is not None else {}).encode()
    return Response(status, {k.lower(): v for k, v in (headers or {}).items()}, body)


class FakeTransport:
    """Answers scripted responses in order and records every request."""

    def __init__(self, responses=()):
        self.queue = list(responses)
        self.requests = []

    def add(self, *responses):
        self.queue.extend(responses)

    def send(self, req):
        self.requests.append(req)
        if not self.queue:
            raise AssertionError(f"unexpected request {req.method} {req.url.split('?')[0]}")
        item = self.queue.pop(0)
        if callable(item) and not isinstance(item, Response):
            item = item(req)
        if isinstance(item, BaseException):
            raise item
        return item


# ---------------------------------------------------------------- images

def make_jpeg(w: int, h: int, pad: int = 0) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, h, w, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8" + app0 + sof + b"\x00" * pad + b"\xff\xd9"


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def make_png(w: int, h: int, pad: int = 0) -> bytes:
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr)
            + (_png_chunk(b"tEXt", b"p\x00" + b"x" * pad) if pad else b"")
            + _png_chunk(b"IEND", b""))


def make_gif(w: int, h: int, frames: int = 1) -> bytes:
    out = b"GIF89a" + struct.pack("<HHBBB", w, h, 0, 0, 0)
    for _ in range(frames):
        out += b"\x2c" + struct.pack("<HHHHB", 0, 0, w, h, 0) + b"\x02\x01\x00\x00"
    return out + b"\x3b"


def make_webp(w: int, h: int, kind: str = "VP8X") -> bytes:
    if kind == "VP8X":
        payload = b"\x00\x00\x00\x00" + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    elif kind == "VP8 ":
        payload = b"\x00\x00\x00" + b"\x9d\x01\x2a" + struct.pack("<HH", w, h)
    else:  # VP8L
        bits = (w - 1) | ((h - 1) << 14)
        payload = b"\x2f" + bits.to_bytes(4, "little")
    chunk = kind.encode() + struct.pack("<I", len(payload)) + payload
    return b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk


def make_bmp() -> bytes:
    return b"BM" + b"\x00" * 60


def make_tiff() -> bytes:
    return b"II*\x00" + b"\x00" * 60


# ---------------------------------------------------------------- test case

class PosterTestCase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        socket.socket.connect = _guard_connect
        socket.socket.connect_ex = _guard_connect_ex
        socket.getaddrinfo = _guard_getaddrinfo
        self.addCleanup(self._restore_socket)
        self._tmp = tempfile.TemporaryDirectory(prefix="poster-test-")
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.home = os.path.join(self.root, "home")
        self.state_dir = os.path.join(self.root, "state")
        self.library = os.path.join(self.root, "library")
        self.pkg_dir = os.path.join(self.root, "packages")
        for d in (self.home, self.library, self.pkg_dir):
            os.makedirs(d)
        self.env_path = os.path.join(self.root, "fake.env")
        self.env_values = dict(PLAIN)
        self.env_values.update(CANARIES)
        self.write_env(self.env_values)
        self.environ = {"HOME": self.home, "XDG_STATE_HOME": os.path.join(self.root, "xdg"),
                        "MF_STATE_DIR": self.state_dir, "MF_ENV_FILE": self.env_path,
                        "MF_IMAGE_LIBRARY": self.library}
        self.clock = Clock()
        self.sleeps: list[float] = []
        self.outputs: list[str] = []
        self.addCleanup(self._assert_no_canary_leak)

    def _restore_socket(self):
        socket.socket.connect = _ORIG_CONNECT
        socket.socket.connect_ex = _ORIG_CONNECT_EX
        socket.getaddrinfo = _ORIG_GETADDRINFO
        assert socket.socket.connect is _ORIG_CONNECT

    def write_env(self, values: dict, extra: str = ""):
        with open(self.env_path, "w", encoding="utf-8") as fh:
            fh.write(env_text(values) + extra)
        os.chmod(self.env_path, 0o600)

    def image(self, name: str, data: bytes, folder: str | None = None) -> str:
        path = os.path.join(folder or self.library, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def package(self, variants: dict, name: str = "pkg-1", **top) -> str:
        data = {"schema": 1, "theme": "test theme", "variants": variants}
        data.update(top)
        path = os.path.join(self.pkg_dir, name + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        return path

    def run_cli(self, *argv, transport=None):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(list(argv), environ=self.environ, transport=transport or FakeTransport(),
                        sleep=self.sleeps.append, clock=self.clock, stdout=out, stderr=err)
        self.outputs += [out.getvalue(), err.getvalue()]
        return code, out.getvalue(), err.getvalue()

    def records(self) -> list[dict]:
        path = os.path.join(self.state_dir, "posts.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def ledger_rows(self) -> list[dict]:
        path = os.path.join(self.state_dir, "x-ledger.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def assert_no_canary(self, text: str):
        for name, value in CANARIES.items():
            self.assertNotIn(value, text, f"secret {name} leaked")

    def _assert_no_canary_leak(self):
        for text in self.outputs:
            self.assert_no_canary(text)
        if os.path.isdir(self.state_dir):
            for dirpath, _, files in os.walk(self.state_dir):
                for f in files:
                    with open(os.path.join(dirpath, f), encoding="utf-8", errors="replace") as fh:
                        self.assert_no_canary(fh.read())


def isolated_subprocess_env(test: PosterTestCase) -> dict:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    env.update(test.environ)
    return env


SUBPROCESS_PREFIX = [sys.executable, "-I", "-B", "-c",
                     f"import sys; sys.path.insert(0, {REPO_ROOT!r}); "
                     "import datetime as dt; from poster.cli import main; "
                     f"NOW = dt.datetime.fromisoformat({FROZEN_NOW.isoformat()!r}); "
                     "sys.exit(main(clock=lambda: NOW))"]
