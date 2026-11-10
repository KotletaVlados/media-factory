"""Env-file handling, target/profile registry, prices and local paths (design §5.4, §7, §11).

Credentials and settings come only from the env file. The process environment supplies
only MF_*, HOME and XDG_STATE_HOME, so a stray shell export cannot change the account used.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NETWORKS = ("facebook", "instagram", "x", "linkedin")
# Execution order: free targets first, the paid one (X) last (design §5.4).
NETWORK_ORDER = {"facebook": 0, "instagram": 1, "linkedin": 2, "x": 3}

PROFILES = {
    "kotleta": ("fb:kotleta", "ig:kotleta", "linkedin", "x"),
}

DEFAULT_SETTINGS = {
    "META_GRAPH_VERSION": "v27.0",
    "LINKEDIN_API_VERSION": "202610",
    "X_MONTHLY_CAP_USD": "5.00",
    "X_PRICE_POST": "0.015",
    "X_PRICE_POST_WITH_URL": "0.200",
    "X_PRICE_POST_WITH_MEDIA": "0.200",
    "X_PRICE_MEDIA_UPLOAD": "0.015",
}
MONEY_SETTINGS = ("X_MONTHLY_CAP_USD", "X_PRICE_POST", "X_PRICE_POST_WITH_URL",
                  "X_PRICE_POST_WITH_MEDIA", "X_PRICE_MEDIA_UPLOAD")

LINKEDIN_VARS = ("LINKEDIN_ACCESS_TOKEN", "LINKEDIN_TOKEN_EXPIRES_AT", "LINKEDIN_PERSON_URN")
X_VARS = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TARGET_RE = re.compile(r"^(fb|ig):([a-z0-9_]+)$")


class ConfigError(Exception):
    """A configuration problem whose message never contains a secret value."""


# ---------------------------------------------------------------- paths

def resolve_env_path(flag: str | None, environ) -> str:
    if flag:
        return flag
    if environ.get("MF_ENV_FILE"):
        return environ["MF_ENV_FILE"]
    return os.path.join(REPO_ROOT, ".env")


def resolve_state_dir(flag: str | None, environ) -> str:
    if flag:
        return flag
    if environ.get("MF_STATE_DIR"):
        return environ["MF_STATE_DIR"]
    base = environ.get("XDG_STATE_HOME") or os.path.join(
        environ.get("HOME") or os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "media-factory", "poster")


def resolve_library(flag: str | None, environ) -> str:
    if flag:
        return flag
    if environ.get("MF_IMAGE_LIBRARY"):
        return environ["MF_IMAGE_LIBRARY"]
    return os.path.join(REPO_ROOT, "content", "images")


# ---------------------------------------------------------------- env file

def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def parse_env(text: str) -> dict[str, str]:
    """Parse NAME=VALUE lines. Malformed lines are reported by number only."""
    values: dict[str, str] = {}
    bad: list[int] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or not _NAME_RE.match(name):
            bad.append(number)
            continue
        values[name] = _unquote(value.strip())
    if bad:
        raise ConfigError("env file: malformed line(s) " + ", ".join(map(str, bad))
                          + " (expected NAME=VALUE; content not shown)")
    return values


def load_env(path: str) -> dict[str, str]:
    try:
        with open(path, encoding="utf-8") as fh:
            return parse_env(fh.read())
    except FileNotFoundError:
        raise ConfigError(f"env file not found: {path} (use --env-file or MF_ENV_FILE)") from None


def temp_name(real_path: str) -> str:
    """Name of the temporary copy beside an env file. It keeps the env file's own name as a
    prefix, so `.env` gives `.env.tmp-<pid>`, which the `.env.*` ignore rule covers; a leftover
    after a kill must never show up for `git add`."""
    return f"{os.path.basename(real_path)}.tmp-{os.getpid()}"


def write_back(path: str, updates: dict[str, str]) -> None:
    """Update or append NAME=VALUE lines; keep every other byte; atomic replace, mode 0600."""
    real = os.path.realpath(path)
    try:
        with open(real, "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        data = b""
    lines = data.splitlines(keepends=True)
    pending = dict(updates)
    out: list[bytes] = []
    for line in lines:
        stripped = line.strip()
        name = stripped.split(b"=", 1)[0].strip().decode("utf-8", "replace") if b"=" in stripped else None
        if name in updates and not stripped.startswith(b"#"):
            if name in pending:
                ending = line[len(line.rstrip(b"\r\n")):] or b"\n"
                out.append(f"{name}={pending.pop(name)}".encode() + ending)
            # a later duplicate of an updated name is dropped so the new value wins
            continue
        out.append(line)
    if pending:
        if out and not out[-1].endswith(b"\n"):
            out[-1] += b"\n"
        for name, value in pending.items():
            out.append(f"{name}={value}\n".encode())
    folder = os.path.dirname(real) or "."
    tmp = os.path.join(folder, temp_name(real))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(b"".join(out))
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, real)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ---------------------------------------------------------------- settings

@dataclass
class Settings:
    graph_version: str
    linkedin_version: str
    cap: Decimal
    price_post: Decimal
    price_post_with_url: Decimal
    price_post_with_media: Decimal
    price_media_upload: Decimal


def load_settings(env: dict[str, str]) -> Settings:
    merged = {k: env.get(k) or v for k, v in DEFAULT_SETTINGS.items()}
    money = {}
    for name in MONEY_SETTINGS:
        try:
            value = Decimal(merged[name])
        except InvalidOperation:
            raise ConfigError(f"{name} is not a decimal number") from None
        if not value.is_finite() or value < 0:
            raise ConfigError(f"{name} must be a finite number >= 0")
        money[name] = value
    if not re.fullmatch(r"v\d+\.\d+", merged["META_GRAPH_VERSION"]):
        raise ConfigError("META_GRAPH_VERSION must look like v27.0")
    if not re.fullmatch(r"\d{6}", merged["LINKEDIN_API_VERSION"]):
        raise ConfigError("LINKEDIN_API_VERSION must look like 202610")
    return Settings(
        graph_version=merged["META_GRAPH_VERSION"],
        linkedin_version=merged["LINKEDIN_API_VERSION"],
        cap=money["X_MONTHLY_CAP_USD"],
        price_post=money["X_PRICE_POST"],
        price_post_with_url=money["X_PRICE_POST_WITH_URL"],
        price_post_with_media=money["X_PRICE_POST_WITH_MEDIA"],
        price_media_upload=money["X_PRICE_MEDIA_UPLOAD"],
    )


# ---------------------------------------------------------------- targets

@dataclass(frozen=True)
class Target:
    id: str          # "fb:kotleta", "ig:kotleta", "x", "linkedin"
    network: str     # facebook | instagram | x | linkedin
    name: str        # page/account name ("" for x and linkedin)

    @property
    def required_vars(self) -> tuple[str, ...]:
        up = self.name.upper()
        if self.network == "facebook":
            return (f"FB_PAGE_{up}_ID", f"FB_PAGE_{up}_TOKEN")
        if self.network == "instagram":
            return (f"IG_{up}_USER_ID", f"FB_PAGE_{up}_ID", f"FB_PAGE_{up}_TOKEN")
        if self.network == "x":
            return X_VARS
        return LINKEDIN_VARS

    def missing(self, env: dict[str, str]) -> list[str]:
        return [n for n in self.required_vars if not env.get(n)]

    @property
    def order(self) -> tuple[int, str]:
        return (NETWORK_ORDER[self.network], self.id)


def parse_target(spec: str) -> Target:
    spec = spec.strip()
    if spec == "x":
        return Target("x", "x", "")
    if spec == "linkedin":
        return Target("linkedin", "linkedin", "")
    m = _TARGET_RE.match(spec)
    if not m:
        raise ConfigError(f"unknown target '{spec}' (use fb:NAME, ig:NAME, x or linkedin)")
    kind, name = m.groups()
    return Target(spec, "facebook" if kind == "fb" else "instagram", name)


def targets_for(profile: str | None, targets: str | None) -> list[Target]:
    if bool(profile) == bool(targets):
        raise ConfigError("give exactly one of --profile or --targets")
    if profile:
        if profile not in PROFILES:
            raise ConfigError(f"unknown profile '{profile}' (known: {', '.join(sorted(PROFILES))})")
        specs = PROFILES[profile]
    else:
        specs = [s for s in targets.split(",") if s.strip()]
        if not specs:
            raise ConfigError("--targets is empty")
    result: list[Target] = []
    for spec in specs:
        t = parse_target(spec)
        if t not in result:
            result.append(t)
    return sorted(result, key=lambda t: t.order)


def derived_targets(env: dict[str, str]) -> list[Target]:
    """Targets derivable from variable names alone (values are not needed)."""
    found: set[Target] = set()
    for name in env:
        m = re.fullmatch(r"FB_PAGE_([A-Z0-9_]+?)_(ID|TOKEN)", name)
        if m:
            found.add(Target("fb:" + m.group(1).lower(), "facebook", m.group(1).lower()))
        m = re.fullmatch(r"IG_([A-Z0-9_]+?)_USER_ID", name)
        if m:
            found.add(Target("ig:" + m.group(1).lower(), "instagram", m.group(1).lower()))
    found.add(Target("x", "x", ""))
    found.add(Target("linkedin", "linkedin", ""))
    for specs in PROFILES.values():
        found.update(parse_target(s) for s in specs)
    return sorted(found, key=lambda t: t.order)


def parse_utc(value: str) -> _dt.datetime:
    """Parse an ISO-8601 UTC timestamp such as 2026-11-09T10:00:00Z."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = _dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


def iso_utc(moment: _dt.datetime) -> str:
    return moment.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
