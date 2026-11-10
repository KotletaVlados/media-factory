"""Rules file `content/rules.json`: schema, defaults, validation, guarded write (§7).

The structure is checked here. The checks that need the stock, the env file and the plan
(activation, §7.3) live in `factory.checks`. Every writer takes the `rules.lock` flock, compares
the file's SHA-256 with the revision it started from, and replaces the file atomically, so a
reader without the lock always sees a whole file.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
import zoneinfo
from dataclasses import dataclass, field

from poster import config

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
HOUR_RE = re.compile(r"^(0[6-9]|1[0-9]|2[0-3]):00$")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
STATUSES = ("draft", "active")
LOCK_FILE = "rules.lock"
ABSENT = "absent"   # revision of a rules file that does not exist yet

# §7.2: our estimates, not platform numbers.
DEFAULT_LIMITS = {
    "facebook": (3, 3),
    "instagram": (3, 4),
    "linkedin": (2, 6),
    "x": (4, 2),
}
LIMIT_BASIS = {
    "facebook": "our estimate; no platform number is used",
    "instagram": "our estimate; API ceiling 50 posts per 24 h",
    "linkedin": "our estimate; API ceiling 150 shares per member per day",
    "x": "our estimate; the real limit is the $5 month cap",
}
RULE_KEYS = ("id", "folder", "targets", "days", "hours", "timezone", "status", "active_since")


class RulesError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class RevisionMismatch(Exception):
    def __init__(self):
        super().__init__("rules changed elsewhere, reload")


@dataclass(frozen=True)
class Limit:
    max_per_day: int
    min_gap_hours: float


@dataclass
class Rule:
    id: str
    folder: str
    targets: tuple
    days: tuple
    hours: tuple                 # sorted "HH:00" strings
    timezone: str
    status: str = "draft"
    active_since: str | None = None

    @property
    def active(self) -> bool:
        return self.status == "active"

    @property
    def zone(self) -> zoneinfo.ZoneInfo:
        return zoneinfo.ZoneInfo(self.timezone)

    def networks(self) -> set:
        return {config.parse_target(t).network for t in self.targets}

    def to_json(self) -> dict:
        data = {"id": self.id, "folder": self.folder, "targets": list(self.targets),
                "days": list(self.days), "hours": list(self.hours),
                "timezone": self.timezone, "status": self.status}
        if self.active_since:
            data["active_since"] = self.active_since
        return data


@dataclass
class RuleSet:
    rules: list = field(default_factory=list)
    limits_raw: dict = field(default_factory=dict)   # as written; kept on write-back
    revision: str = ABSENT

    def get(self, rule_id: str) -> Rule | None:
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        return None

    def limit(self, network: str) -> Limit:
        raw = self.limits_raw.get(network) or {}
        default_n, default_gap = DEFAULT_LIMITS[network]
        return Limit(int(raw.get("max_per_day", default_n)),
                     float(raw.get("min_gap_hours", default_gap)))

    def to_json(self) -> dict:
        data: dict = {"schema": 1}
        if self.limits_raw:
            data["limits"] = self.limits_raw
        data["rules"] = [r.to_json() for r in self.rules]
        return data


def valid_zone(name) -> bool:
    if not isinstance(name, str) or not name:
        return False
    try:
        zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError, KeyError):
        return False
    return True


def _number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def parse_limits(raw, problems: list[str]) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        problems.append("limits must be an object keyed by network")
        return {}
    out = {}
    for network, value in raw.items():
        if network not in DEFAULT_LIMITS:
            problems.append(f"limits: unknown network '{network}'")
            continue
        if not isinstance(value, dict) or set(value) - {"max_per_day", "min_gap_hours"}:
            problems.append(f"limits.{network} takes only max_per_day and min_gap_hours")
            continue
        n = value.get("max_per_day", DEFAULT_LIMITS[network][0])
        gap = value.get("min_gap_hours", DEFAULT_LIMITS[network][1])
        if not (isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= 100):
            problems.append(f"limits.{network}.max_per_day must be a whole number 1-100")
            continue
        if not (_number(gap) and 0 <= gap <= 24):
            problems.append(f"limits.{network}.min_gap_hours must be a number 0-24")
            continue
        out[network] = dict(value)
    return out


def parse_rule(raw, problems: list[str]) -> Rule | None:
    if not isinstance(raw, dict):
        problems.append("each rule must be an object")
        return None
    rid = raw.get("id")
    label = f"rule '{rid}'" if isinstance(rid, str) else "rule"
    before = len(problems)
    unknown = sorted(set(raw) - set(RULE_KEYS))
    if unknown:
        problems.append(f"{label}: unknown key(s) " + ", ".join(unknown))
    if not isinstance(rid, str) or not ID_RE.match(rid):
        problems.append(f"{label}: id must match [a-z0-9][a-z0-9-]{{0,39}}")
    folder = raw.get("folder")
    if not isinstance(folder, str) or not ID_RE.match(folder):
        problems.append(f"{label}: folder must be a stock folder name")
    targets = raw.get("targets")
    if not isinstance(targets, list) or not targets or not all(isinstance(t, str) for t in targets):
        problems.append(f"{label}: targets must be a non-empty list of target ids")
        targets = []
    else:
        for t in targets:
            try:
                config.parse_target(t)
            except config.ConfigError as exc:
                problems.append(f"{label}: {exc}")
        if len(set(targets)) != len(targets):
            problems.append(f"{label}: a target is listed twice")
    days = raw.get("days")
    if (not isinstance(days, list) or not days
            or not all(isinstance(d, str) and d in DAYS for d in days)):
        problems.append(f"{label}: days must be a non-empty list of mon..sun")
        days = []
    hours = raw.get("hours")
    if (not isinstance(hours, list) or not hours
            or not all(isinstance(h, str) and HOUR_RE.match(h) for h in hours)):
        problems.append(f"{label}: hours must be a non-empty list of whole hours "
                        "\"06:00\"..\"23:00\"")
        hours = []
    tz = raw.get("timezone")
    if not valid_zone(tz):
        problems.append(f"{label}: timezone must be an IANA zone name such as Europe/Berlin")
    status = raw.get("status", "draft")
    if status not in STATUSES:
        problems.append(f"{label}: status must be draft or active")
    since = raw.get("active_since")
    if since is not None:
        try:
            if not isinstance(since, str):
                raise ValueError
            config.parse_utc(since)
        except ValueError:
            problems.append(f"{label}: active_since must be an ISO-8601 UTC time")
    if len(problems) > before:
        return None
    day_order = {d: i for i, d in enumerate(DAYS)}
    return Rule(rid, folder, tuple(targets),
                tuple(sorted(set(days), key=day_order.get)), tuple(sorted(set(hours))),
                tz, status, since)


def parse(data) -> RuleSet:
    problems: list[str] = []
    if not isinstance(data, dict):
        raise RulesError(["rules file must be a JSON object"])
    unknown = sorted(set(data) - {"schema", "limits", "rules"})
    if unknown:
        problems.append("unknown top-level key(s): " + ", ".join(unknown))
    if data.get("schema") != 1 or isinstance(data.get("schema"), bool):
        problems.append("schema must be 1")
    limits = parse_limits(data.get("limits"), problems)
    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        problems.append("rules must be a list")
        raw_rules = []
    rules: list[Rule] = []
    for raw in raw_rules:
        rule = parse_rule(raw, problems)
        if rule:
            if any(r.id == rule.id for r in rules):
                problems.append(f"rule '{rule.id}': id is used twice")
            rules.append(rule)
    if problems:
        raise RulesError(problems)
    return RuleSet(rules, limits)


def revision_of(data: bytes | None) -> str:
    return ABSENT if data is None else hashlib.sha256(data).hexdigest()


def _read_bytes(path: str) -> bytes | None:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def load(path: str) -> RuleSet:
    """Read and validate the rules file. A missing file is an empty rule set."""
    data = _read_bytes(path)
    if data is None:
        return RuleSet()
    try:
        doc = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise RulesError([f"rules file is not valid UTF-8 JSON: {exc}"]) from None
    ruleset = parse(doc)
    ruleset.revision = revision_of(data)
    return ruleset


def dump(ruleset: RuleSet) -> bytes:
    return (json.dumps(ruleset.to_json(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")


@contextlib.contextmanager
def _lock(folder: str):
    fd = os.open(os.path.join(folder, LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def write(path: str, ruleset: RuleSet, base_revision: str) -> str:
    """Write `ruleset` if the file still has `base_revision`; return the new revision."""
    parse(ruleset.to_json())      # never write a file the reader would refuse
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    data = dump(ruleset)
    with _lock(folder):
        if revision_of(_read_bytes(path)) != base_revision:
            raise RevisionMismatch()
        tmp = os.path.join(folder, f".{os.path.basename(path)}.tmp-{os.getpid()}")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    return revision_of(data)
