"""Per-network text counting, limits and image sniffing (design §8).

Text is never truncated: a check either passes or refuses with the count and the limit.
"""

from __future__ import annotations

import os
import re
import struct
import unicodedata
from dataclasses import dataclass, field

# ---------------------------------------------------------------- limits (vendor docs, §3)

X_MAX_WEIGHTED = 280          # X10
X_URL_WEIGHT = 23             # X10
X_MAX_CASHTAGS = 1            # X11
IG_MAX_CAPTION = 2200         # I4
IG_MAX_HASHTAGS = 30          # I4
IG_MAX_MENTIONS = 20          # I4
LI_MAX_COMMENTARY = 3000      # L4 (conservative for /rest/posts, U7)
FB_MAX_BYTES = 10_000_000     # F4 ("10MB", decimal = conservative)
FB_PNG_WARN_BYTES = 1_000_000  # F4 recommendation
IG_MAX_BYTES = 8_000_000      # I3
IG_MIN_ASPECT, IG_MAX_ASPECT = 0.8, 1.91   # I3: 4:5 .. 1.91:1
X_MAX_BYTES = 5_000_000       # X3
LI_MAX_PIXELS = 36_152_320    # L2 ("less than")

FORMATS = {
    "facebook": {"jpeg", "bmp", "png", "gif", "tiff"},   # F4
    "instagram": {"jpeg"},                               # I3
    "x": {"jpeg", "png", "webp", "gif"},                 # X3 (static GIF only)
    "linkedin": {"jpeg", "png", "gif"},                  # L2
}
MIME = {"jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp",
        "bmp": "image/bmp", "tiff": "image/tiff"}


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


# ---------------------------------------------------------------- X weighted length (§8.1)

_WEIGHT1 = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))
_EMOJI_IN_WEIGHT1 = {0x00A9, 0x00AE}   # © and ® are emoji for twitter-text
_TRAIL = ".,!?;:)]}\"'»…"
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_DOMAIN_RE = re.compile(
    r"(?<![\w@.\-/])(?:[^\W_](?:[\w-]*[^\W_])?\.)+[^\W\d_]{2,}(?:/\S*)?")
_CASHTAG_RE = re.compile(r"(?<![\w$])\$[A-Za-z]{1,6}(?:[._][A-Za-z]{1,2})?(?![\w])")


def _cp_weight(ch: str) -> int:
    cp = ord(ch)
    if cp in _EMOJI_IN_WEIGHT1:
        return 2
    return 1 if any(lo <= cp <= hi for lo, hi in _WEIGHT1) else 2


def _plain_weight(text: str) -> int:
    return sum(_cp_weight(c) for c in text)


def _strip_trailing(s: str) -> tuple[str, str]:
    core = s.rstrip(_TRAIL)
    return core, s[len(core):]


def x_url_spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, kind) for URL-like spans: 'url' for http(s), 'domain' for bare domains."""
    spans: list[tuple[int, int, str]] = []
    for m in _URL_RE.finditer(text):
        core, _ = _strip_trailing(m.group(0))
        spans.append((m.start(), m.start() + len(core), "url"))
    taken = [(s, e) for s, e, _ in spans]
    for m in _DOMAIN_RE.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue
        core, _ = _strip_trailing(m.group(0))
        if "." not in core:
            continue
        spans.append((m.start(), m.start() + len(core), "domain"))
    return sorted(spans)


def x_weighted_length(text: str) -> int:
    """Conservative twitter-text v3 weighted length: never below X's own count."""
    text = nfc(text)
    total = 0
    pos = 0
    for start, end, kind in x_url_spans(text):
        total += _plain_weight(text[pos:start])
        span = text[start:end]
        total += X_URL_WEIGHT if kind == "url" else max(X_URL_WEIGHT, _plain_weight(span))
        pos = end
    total += _plain_weight(text[pos:])
    return total


def x_has_url(text: str) -> bool:
    return bool(x_url_spans(nfc(text)))


def count_cashtags(text: str) -> int:
    return len(_CASHTAG_RE.findall(text))


_HASHTAG_RE = re.compile(r"(?<![\w&])#\w+")
_MENTION_RE = re.compile(r"(?<![\w.@])@[\w.]+")


def count_hashtags(text: str) -> int:
    return len(_HASHTAG_RE.findall(text))


def count_mentions(text: str) -> int:
    return len(_MENTION_RE.findall(text))


# ---------------------------------------------------------------- LinkedIn little text (§9.5)

LI_RESERVED = set("|{}@[]()<>#\\*_~")
_LI_HASHTAG_RE = re.compile(r"#([^\W]+)")


def linkedin_escape(text: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "#":
            m = _LI_HASHTAG_RE.match(text, i)
            if m:
                word = "".join("\\" + c if c in LI_RESERVED else c for c in m.group(1))
                out.append("{hashtag|\\#|" + word + "}")
                i = m.end()
                continue
        out.append("\\" + ch if ch in LI_RESERVED else ch)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------- image sniffing

@dataclass
class ImageInfo:
    path: str
    format: str | None            # jpeg | png | gif | webp | bmp | tiff | None
    size: int
    width: int | None = None
    height: int | None = None
    frames: int | None = None     # GIF only

    @property
    def mime(self) -> str:
        return MIME.get(self.format or "", "application/octet-stream")

    def describe(self) -> str:
        dims = f" {self.width}x{self.height}" if self.width and self.height else ""
        anim = " animated" if self.frames and self.frames > 1 else ""
        return f"{self.format or 'unknown format'}{dims}{anim}, {self.size} bytes"


def sniff(path: str) -> ImageInfo:
    with open(path, "rb") as fh:
        data = fh.read()
    info = ImageInfo(path, _format(data), len(data))
    try:
        dims = _DIMENSIONS.get(info.format, lambda d: None)(data)
    except (struct.error, IndexError, ValueError):
        dims = None
    if dims:
        info.width, info.height = dims
    if info.format == "gif":
        info.frames = _gif_frames(data)
    return info


def _format(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:2] == b"BM":
        return "bmp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    return None


def _jpeg_dims(data: bytes):
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        if marker == 0xDA:
            return None
        i += 2 + length
    return None


def _png_dims(data: bytes):
    if data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def _gif_dims(data: bytes):
    return struct.unpack("<HH", data[6:10])


def _webp_dims(data: bytes):
    chunk = data[12:16]
    if chunk == b"VP8 ":
        if data[23:26] != b"\x9d\x01\x2a":
            return None
        w, h = struct.unpack("<HH", data[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if chunk == b"VP8L":
        if data[20] != 0x2F:
            return None
        b = data[21:25]
        w = 1 + (((b[1] & 0x3F) << 8) | b[0])
        h = 1 + (((b[3] & 0x0F) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
        return w, h
    if chunk == b"VP8X":
        w = 1 + int.from_bytes(data[24:27], "little")
        h = 1 + int.from_bytes(data[27:30], "little")
        return w, h
    return None


_DIMENSIONS = {"jpeg": _jpeg_dims, "png": _png_dims, "gif": _gif_dims, "webp": _webp_dims}


def _gif_frames(data: bytes) -> int | None:
    """Count image descriptors by walking GIF blocks; None when the file cannot be walked."""
    try:
        i = 13
        flags = data[10]
        if flags & 0x80:
            i += 3 * (2 ** ((flags & 0x07) + 1))
        frames = 0
        while i < len(data):
            b = data[i]
            if b == 0x3B:
                return frames
            if b == 0x21:
                i += 2
                while data[i] != 0:
                    i += data[i] + 1
                i += 1
            elif b == 0x2C:
                frames += 1
                lflags = data[i + 9]
                i += 10
                if lflags & 0x80:
                    i += 3 * (2 ** ((lflags & 0x07) + 1))
                i += 1  # LZW minimum code size
                while data[i] != 0:
                    i += data[i] + 1
                i += 1
            else:
                return None
        return None
    except IndexError:
        return None


# ---------------------------------------------------------------- checks

@dataclass
class Check:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    counts: list = field(default_factory=list)   # human lines shown in dry-run


def check_text(network: str, text: str) -> Check:
    c = Check()
    if not text.strip():
        c.errors.append("text is empty")
        return c
    if network == "facebook":
        c.counts.append(f"text {len(text)} characters (Meta documents no Page post limit)")
    elif network == "instagram":
        n = utf16_len(text)
        c.counts.append(f"caption {n}/{IG_MAX_CAPTION} (UTF-16 units)")
        if n > IG_MAX_CAPTION:
            c.errors.append(f"caption is {n} characters, Instagram allows {IG_MAX_CAPTION} "
                            "(counted in UTF-16 units); shorten it, it is never truncated")
        h, m = count_hashtags(text), count_mentions(text)
        c.counts.append(f"hashtags {h}/{IG_MAX_HASHTAGS}, @mentions {m}/{IG_MAX_MENTIONS}")
        if h > IG_MAX_HASHTAGS:
            c.errors.append(f"caption has {h} hashtags, Instagram allows {IG_MAX_HASHTAGS}")
        if m > IG_MAX_MENTIONS:
            c.errors.append(f"caption has {m} @mentions, Instagram allows {IG_MAX_MENTIONS}")
    elif network == "x":
        n = x_weighted_length(text)
        c.counts.append(f"weighted {n}/{X_MAX_WEIGHTED} (twitter-text v3, conservative: "
                        "URL=23, CJK/emoji=2, Latin/Cyrillic=1)")
        if n > X_MAX_WEIGHTED:
            c.errors.append(f"text is {n} weighted characters, X allows {X_MAX_WEIGHTED} "
                            "(twitter-text v3, conservative); shorten it, it is never truncated")
        k = count_cashtags(text)
        if k > X_MAX_CASHTAGS:
            c.errors.append(f"text has {k} cashtags, X allows {X_MAX_CASHTAGS} per API post")
    elif network == "linkedin":
        escaped = linkedin_escape(text)
        n = utf16_len(escaped)
        c.counts.append(f"commentary {n}/{LI_MAX_COMMENTARY} after little-format escaping "
                        f"(text as written: {utf16_len(text)})")
        if n > LI_MAX_COMMENTARY:
            c.errors.append(f"commentary is {n} characters after escaping, LinkedIn allows "
                            f"{LI_MAX_COMMENTARY}; shorten it, it is never truncated")
    return c


def check_image(network: str, info: ImageInfo | None) -> Check:
    c = Check()
    if info is None:
        if network == "instagram":
            c.errors.append("Instagram needs an image; this variant has none "
                            "(text-only posts are not possible on Instagram)")
        return c
    name = os.path.basename(info.path)
    c.counts.append(f"image {name}: {info.describe()}")
    allowed = FORMATS[network]
    if info.format not in allowed:
        c.errors.append(f"image {name} is {info.format or 'not a recognised image'}; "
                        f"{network} accepts {', '.join(sorted(allowed))}")
        return c
    if network == "facebook":
        if info.size > FB_MAX_BYTES:
            c.errors.append(f"image {name} is {info.size} bytes, Facebook allows {FB_MAX_BYTES}")
        if info.format == "png" and info.size > FB_PNG_WARN_BYTES:
            c.warnings.append(f"PNG {name} is over 1 MB; Meta says it may appear pixelated")
    elif network == "instagram":
        if info.size > IG_MAX_BYTES:
            c.errors.append(f"image {name} is {info.size} bytes, Instagram allows {IG_MAX_BYTES}")
        if not (info.width and info.height):
            c.errors.append(f"cannot read the dimensions of {name}")
        else:
            ratio = info.width / info.height
            if not (IG_MIN_ASPECT <= ratio <= IG_MAX_ASPECT):
                c.errors.append(f"image {name} aspect ratio {ratio:.3f} ({info.width}x{info.height})"
                                " is outside Instagram's 4:5 (0.8) to 1.91:1 range")
    elif network == "x":
        if info.size > X_MAX_BYTES:
            c.errors.append(f"image {name} is {info.size} bytes, X allows {X_MAX_BYTES}")
        if info.format == "gif" and info.frames != 1:
            c.errors.append(f"GIF {name} is animated or unreadable; X simple upload takes "
                            "static images only")
    elif network == "linkedin":
        if not (info.width and info.height):
            c.errors.append(f"cannot read the dimensions of {name}")
        elif info.width * info.height >= LI_MAX_PIXELS:
            c.errors.append(f"image {name} has {info.width * info.height} pixels, LinkedIn "
                            f"requires fewer than {LI_MAX_PIXELS}")
    return c
