"""Secret registry and pattern masks (design §12).

Everything the CLI prints passes through Redactor.redact().
"""

from __future__ import annotations

import re
import urllib.parse

SECRET_NAME_PARTS = ("TOKEN", "SECRET", "KEY")
NOT_SECRET = {"LINKEDIN_TOKEN_EXPIRES_AT"}
MIN_SECRET_LEN = 8

_PATTERNS = [
    (re.compile(r"(?i)(access_token=)[^&\s\"'<>]+"), r"\1[redacted]"),
    (re.compile(r"(?i)(client_secret=)[^&\s\"'<>]+"), r"\1[redacted]"),
    (re.compile(r"(?i)(?<![\w])(code=)[^&\s\"'<>]+"), r"\1[redacted]"),
    (re.compile(r"(?i)(bearer\s+)[^\s\"'<>,]+"), r"\1[redacted]"),
    (re.compile(r"(?i)(oauth_signature=\")[^\"]*\""), r'\1[redacted]"'),
    (re.compile(r"(?i)(oauth_signature=)[^&\s\"',]+"), r"\1[redacted]"),
    (re.compile(r"(?i)(authorization\s*:\s*)[^\r\n]+"), r"\1[redacted]"),
]

_LONG_RUN = re.compile(r"[A-Za-z0-9+/=_-]{32,}")


def is_secret_name(name: str) -> bool:
    return name not in NOT_SECRET and any(part in name for part in SECRET_NAME_PARTS)


def mask_long_runs(text: str) -> str:
    """Mask 32+ character base64/hex-like runs (used on vendor error bodies)."""
    return _LONG_RUN.sub("[redacted]", text)


class Redactor:
    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}   # form -> label

    def add(self, name: str, value: str | None) -> None:
        if not value or len(value) < MIN_SECRET_LEN:
            return
        label = f"[redacted:{name}]"
        for form in {value,
                     urllib.parse.quote(value, safe=""),
                     urllib.parse.quote_plus(value, safe=""),
                     urllib.parse.quote(value, safe="-._~")}:
            self._secrets[form] = label

    def add_env(self, env: dict[str, str]) -> None:
        for name, value in env.items():
            if is_secret_name(name):
                self.add(name, value)

    def redact(self, text) -> str:
        text = str(text)
        for form in sorted(self._secrets, key=len, reverse=True):
            if form in text:
                text = text.replace(form, self._secrets[form])
        for pattern, repl in _PATTERNS:
            text = pattern.sub(repl, text)
        return text
