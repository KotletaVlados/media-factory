"""The panel's snapshot: one read of the factory inputs plus the plans, turned into plain view
data (design factory.md §11.1; brief §3.1).

The server owns one `Holder`. Each request costs one stat walk (`state_key`); the inputs are
read and the plans recomputed only when that key changes. The cache holds exactly one
snapshot, replaced on change. Plans for "show 3 more months" are kept on the snapshot (at most
`MAX_MORE` of them) and go away with it.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import threading
import time
import zoneinfo
from dataclasses import dataclass, field
from decimal import Decimal

from poster import config, linkedin, state as poster_state
from poster.redact import Redactor
from factory import (attention, checks, cli as fcli, inputs as finputs, journal as fjournal,
                     planner, ruleset as fruleset, stock as fstock)
from factory.authoring import photos as fphotos
from factory.panel import strings as S

DAY = _dt.timedelta(days=1)
MAX_MORE = 4                 # "show 3 more months" at most 4 times (12 extra months)
STATS_DIR = "stats"
LATEST = "latest.json"
COLLECT = "collect.json"
IMAGE_FORMATS = ("jpeg", "png", "gif", "webp")
TOKEN_ERRORS = ("HTTP 401", "code 190")
UNCOUNTED = (S.S_X_BUDGET, S.S_NO_CONTENT, S.S_DRAFT)
MONTHS_AHEAD = 3              # months after the current one in the calendar plan

_ZONES: list | None = None


def zones() -> list:
    global _ZONES
    if _ZONES is None:
        _ZONES = sorted(zoneinfo.available_timezones())
    return _ZONES


# ---------------------------------------------------------------- key (one stat walk)

def _stat(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def _walk(folder: str, depth: int) -> list:
    out = []
    try:
        with os.scandir(folder) as it:
            entries = sorted(it, key=lambda e: e.name)
    except OSError:
        return out
    for e in entries:
        try:
            st = e.stat()
        except OSError:
            continue
        out.append((e.name, st.st_ino, st.st_mtime_ns, st.st_size))
        if depth > 0 and e.is_dir():
            out.append((e.name, tuple(_walk(e.path, depth - 1))))
    return out


def state_files(paths) -> list:
    stats = os.path.join(paths.state, STATS_DIR)
    return [paths.rules, paths.env_file,
            os.path.join(paths.poster_state, poster_state.RECORD_FILE),
            os.path.join(paths.poster_state, poster_state.LEDGER_FILE),
            os.path.join(paths.state, fjournal.RUNS),
            os.path.join(paths.state, fjournal.HEARTBEAT),
            os.path.join(stats, LATEST), os.path.join(stats, COLLECT)]


def state_key(paths, now: _dt.datetime) -> tuple:
    """One stat walk: the state files, the stock at depth 1, the one-off packages, and the
    photo index of each stock folder that has `photos/` (one extra stat per such folder: an
    index append does not change the folder's mtime)."""
    files = tuple(_stat(p) for p in state_files(paths))
    stock = tuple(_walk(paths.stock, 1))
    indexes = tuple(
        _stat(os.path.join(paths.stock, item[0], fphotos.PHOTOS, fphotos.INDEX))
        for item in stock
        if len(item) == 2 and any(sub[0] == fphotos.PHOTOS for sub in item[1]))
    return (files, stock, indexes, tuple(_walk(paths.packages, 0)),
            now.replace(second=0, microsecond=0))


# ---------------------------------------------------------------- snapshot

@dataclass
class Snapshot:
    now: _dt.datetime
    machine_tz: str
    redactor: Redactor
    key: tuple = ()
    build_ms: float = 0.0
    env_error: str | None = None
    env_missing: bool = False
    rules_error: list | None = None
    inputs: object | None = None
    plan: object | None = None
    days: float = 0.0
    back_days: float = 0.0
    rule_problems: dict = field(default_factory=dict)
    draft_plans: dict = field(default_factory=dict)      # draft rule id -> Plan
    attention: list = field(default_factory=list)
    heartbeat: dict | None = None
    latest: dict | None = None
    collect: dict | None = None
    stats_error: str | None = None
    photos: dict = field(default_factory=dict)          # photo-lane folder -> index rows
    _more: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def zone(self):
        return zoneinfo.ZoneInfo(self.machine_tz)

    @property
    def today(self) -> _dt.date:
        return self.now.astimezone(self.zone).date()

    def red(self, text) -> str:
        return self.redactor.redact("" if text is None else text)

    def rules(self) -> dict:
        return {r.id: r for r in self.inputs.ruleset.rules} if self.inputs else {}

    def plan_for(self, more: int):
        """The calendar plan, extended by 3 months per `more` (bounded by MAX_MORE)."""
        more = max(0, min(int(more), MAX_MORE))
        if more == 0 or self.plan is None:
            return self.plan
        with self._lock:
            if more not in self._more:
                i = self.inputs
                end = _month_start(self.today, MONTHS_AHEAD + 1 + 3 * more, self.zone)
                self._more[more] = planner.plan(
                    i.ruleset, i.stock, i.records, i.journal, i.x_spent, i.settings, self.now,
                    days=(end - self.now) / DAY, back_days=self.back_days)
            return self._more[more]


def _month_start(today: _dt.date, offset: int, zone) -> _dt.datetime:
    """Local midnight on the 1st of the month `offset` months after today's month."""
    index = today.year * 12 + today.month - 1 + offset
    return _dt.datetime(index // 12, index % 12 + 1, 1, tzinfo=zone)


def _inputs_without_rules(paths, clock, redactor) -> finputs.Inputs:
    """Inputs with an empty rule set, for a rules file that does not parse: Connection, Reach
    and Followers still render (brief §3.2)."""
    env = finputs.load_env(paths, redactor)
    settings = config.load_settings(env)
    stock = fstock.load(paths.stock, paths.library, paths.packages)
    records = poster_state.read_jsonl(os.path.join(paths.poster_state, poster_state.RECORD_FILE))
    journal = poster_state.read_jsonl(os.path.join(paths.state, fjournal.RUNS))
    return finputs.Inputs(paths, env, settings, fruleset.RuleSet(), stock, records, journal,
                          finputs.x_month_totals(paths.poster_state, clock))


def _read_stats(path: str, kind: str):
    """(data, error): data None when the file is absent; error names the file."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError, UnicodeDecodeError):
        return None, os.path.basename(path)
    ok = isinstance(data, dict)
    if ok and kind == LATEST:
        ok = (isinstance(data.get("posts", []), list)
              and isinstance(data.get("followers", {}), dict))
    if ok and kind == COLLECT:
        ok = isinstance(data.get("results", {}), dict)
    return (data, None) if ok else (None, os.path.basename(path))


def build(paths, now: _dt.datetime, machine_tz: str) -> Snapshot:
    clock = lambda: now  # noqa: E731 - one instant for the whole snapshot
    snap = Snapshot(now, machine_tz, Redactor())
    try:
        inputs = finputs.load(paths, clock, snap.redactor)
    except config.ConfigError as exc:
        snap.env_error = snap.red(exc)
        snap.env_missing = not os.path.exists(paths.env_file)
        return snap
    except fruleset.RulesError as exc:
        snap.rules_error = [snap.red(p) for p in exc.problems]
        inputs = _inputs_without_rules(paths, clock, snap.redactor)
    snap.inputs = inputs
    for name, folder in inputs.stock.folders.items():
        if folder.lane == "photo":
            snap.photos[name] = fphotos.list_photos(folder.path)
    zone = snap.zone
    today = snap.today
    start = _month_start(today, -1, zone)
    end = _month_start(today, MONTHS_AHEAD + 1, zone)
    snap.back_days = (now - start) / DAY
    snap.days = (end - now) / DAY
    rs = inputs.ruleset
    snap.plan = planner.plan(rs, inputs.stock, inputs.records, inputs.journal, inputs.x_spent,
                             inputs.settings, now, days=snap.days, back_days=snap.back_days)
    for rule in rs.rules:
        snap.rule_problems[rule.id] = [snap.red(p) for p in
                                       checks.basic_problems(inputs, rule, now)]
        if not rule.active:
            # a draft's runway as if it were running (§6.3); 7 days of slots give its X cost
            snap.draft_plans[rule.id] = planner.plan(
                rs, inputs.stock, inputs.records, inputs.journal, inputs.x_spent,
                inputs.settings, now, days=7, extra_active=rule.id)
    snap.heartbeat = fjournal.read_heartbeat(paths.state)
    snap.attention = [snap.red(a) for a in
                      attention.items(inputs, snap.plan, snap.heartbeat, now)]
    stats = os.path.join(paths.state, STATS_DIR)
    snap.latest, err1 = _read_stats(os.path.join(stats, LATEST), LATEST)
    snap.collect, err2 = _read_stats(os.path.join(stats, COLLECT), COLLECT)
    snap.stats_error = err1 or err2
    return snap


class Holder:
    """Owns the one snapshot. A request that arrives during a rebuild waits for it."""

    def __init__(self, paths, clock, machine_tz: str, log=None):
        self.paths, self.clock, self.machine_tz = paths, clock, machine_tz
        self.log = log if log is not None else sys.stderr
        self._lock = threading.Lock()
        self._snap: Snapshot | None = None
        self.builds = 0

    def get(self) -> Snapshot:
        with self._lock:
            now = self.clock()
            key = state_key(self.paths, now)
            if self._snap is None or self._snap.key != key:
                t0 = time.perf_counter()
                snap = build(self.paths, now, self.machine_tz)
                snap.key = key
                snap.build_ms = (time.perf_counter() - t0) * 1000
                self.builds += 1
                print(f"panel: snapshot_ms={snap.build_ms:.0f}", file=self.log, flush=True)
                self._snap = snap
            return self._snap

    def drop(self) -> None:
        with self._lock:
            self._snap = None


# ---------------------------------------------------------------- shared helpers

def parse_ts(value):
    try:
        return config.parse_utc(value)
    except (ValueError, TypeError, AttributeError):
        return None


def network_of(target: str) -> str:
    try:
        return config.parse_target(target).network
    except config.ConfigError:
        return ""


def profile_targets() -> tuple:
    return tuple(config.PROFILES.get(fcli.DEFAULT_PROFILE, ()))


def target_order(target: str) -> tuple:
    try:
        return config.parse_target(target).order
    except config.ConfigError:
        return (9, target)


def first_line(text: str, limit: int = 120) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return line if len(line) <= limit else line[:limit - 1] + "…"


def image_ref(entry, network: str | None = None):
    """(ref) of a browser-displayable image of the entry: the given network's variant first,
    then the others in a fixed order. None when the package has no such image."""
    if entry is None or entry.package is None:
        return None
    order = [network] if network else []
    order += ["instagram", "facebook", "x", "linkedin"]
    for net in order:
        v = entry.package.variants.get(net)
        info = entry.images.get(net)
        if v and v.image_ref and info is not None and info.format in IMAGE_FORMATS:
            return v.image_ref
    return None


def variant_text(entry, network: str | None = None) -> str:
    if entry is None or entry.package is None:
        return ""
    v = entry.package.variants.get(network) if network else None
    if v is None:
        v = next(iter(entry.package.variants.values()), None)
    return v.text if v else ""


def find_entry(snap: Snapshot, package_id: str):
    if not snap.inputs or not package_id:
        return None
    for entry in snap.inputs.stock.entries():
        if entry.id == package_id:
            return entry
    return None


def record_index(records: list) -> dict:
    """(package, target) -> latest published row."""
    out = {}
    for row in records:
        if row.get("status") == "published" and row.get("package") and row.get("target"):
            out[(row["package"], row["target"])] = row
    return out


# ---------------------------------------------------------------- top bar

def topbar(snap: Snapshot) -> dict:
    i, now = snap.inputs, snap.now
    month = planner.month_key(now)
    spent, planned = snap.plan.x.get(month, (0, 0))
    cap = i.settings.cap
    raw = i.env.get("LINKEDIN_TOKEN_EXPIRES_AT")
    left = None
    if raw and parse_ts(raw):
        left = parse_ts(raw) - now
    if left is not None and left.total_seconds() > 0:
        linkedin_text, linkedin_bad = S.LINKEDIN_DAYS.format(n=left.days), False
    else:
        linkedin_text, linkedin_bad = S.LINKEDIN_LOGIN, True
    hb = parse_ts(str((snap.heartbeat or {}).get("ts", ""))) if snap.heartbeat else None
    active = any(r.active for r in i.ruleset.rules)
    if hb is None:
        timer, timer_bad = S.TIMER_NEVER, active
    else:
        minutes = max(0, int((now - hb).total_seconds() // 60))
        if active and now - hb > attention.TIMER_SILENT:
            timer, timer_bad = S.TIMER_SILENT.format(ago=S.ago(minutes)), True
        else:
            timer, timer_bad = S.TIMER_AGO.format(ago=S.ago(minutes)), False
    return {"month": S.month_lower(int(month[5:])), "spent": spent, "planned": planned,
            "cap": cap, "linkedin": linkedin_text, "linkedin_bad": linkedin_bad,
            "timer": timer, "timer_bad": timer_bad, "attention": len(snap.attention)}


def attention_link(snap: Snapshot, item: str) -> str:
    """The tab and row an attention item concerns (§11.3)."""
    if item.startswith("slot "):
        key = item[5:].split(":", 1)[0].rsplit(" ", 1)[0]
        when = parse_ts(key.split("@", 1)[-1])
        if when:
            return f"/calendar?day={when.astimezone(snap.zone).date().isoformat()}"
        return "/calendar"
    if item.startswith("X "):
        return "/calendar"
    if item.startswith("content runs out"):
        return "/files"
    if item.startswith("LinkedIn"):
        return "/connection?net=linkedin"
    if item.startswith("the timer"):
        return "/rules"
    head = item.split(":", 1)[0]
    if "/" in head:
        return f"/files?folder={head.split('/', 1)[0]}"
    return "/connection"


# ---------------------------------------------------------------- connection (§11.4)

def connection(snap: Snapshot) -> dict:
    i, now = snap.inputs, snap.now
    env = i.env
    collect = ((snap.collect or {}).get("results") or {}) if snap.collect else {}
    latest_row, last_pub = {}, {}
    for row in i.records:
        t = row.get("target")
        if not t:
            continue
        if row.get("status") in ("published", "failed", "unknown"):
            latest_row[t] = row
        if row.get("status") == "published":
            last_pub[t] = row
    targets = config.derived_targets(env)
    states = {}
    for t in targets:
        if t.network == "linkedin" and (t.missing(env) or linkedin.token_problems(env, now)[0]):
            state = S.ST_LOGIN
        elif t.missing(env):
            state = S.ST_NO_KEYS
        else:
            row = latest_row.get(t.id) or {}
            err = str(row.get("error") or "")
            if (row.get("status") == "failed" and any(m in err for m in TOKEN_ERRORS)) or \
                    str(collect.get(t.id, "")) == "token rejected":
                state = S.ST_TOKEN
            else:
                state = S.ST_CONNECTED
        states[t.id] = state
    profile = [t for t in targets if t.id in profile_targets()]
    others = [t for t in targets if t.id not in profile_targets()]
    nets = {}
    for net in S.BUILT:
        mine = [t for t in profile if t.network == net] or [t for t in targets if t.network == net]
        nets[net] = mine[0] if mine else None
    connected = sum(1 for net, t in nets.items() if t and states[t.id] == S.ST_CONNECTED)
    any_keys = any(states[t.id] not in (S.ST_NO_KEYS, S.ST_LOGIN) for t in targets)
    return {"targets": targets, "states": states, "profile": profile, "others": others,
            "nets": nets, "connected": connected, "empty": not any_keys,
            "last_pub": last_pub, "collect": collect,
            "collect_ts": (snap.collect or {}).get("ts") if snap.collect else None}


def token_info(snap: Snapshot):
    raw = snap.inputs.env.get("LINKEDIN_TOKEN_EXPIRES_AT")
    when = parse_ts(raw) if raw else None
    if when is None:
        return None, None
    return when, (when - snap.now).days


# ---------------------------------------------------------------- files (§11.5)

@dataclass
class FolderCard:
    name: str
    title: str
    lane: str | None
    entries: list
    packages: int          # ready + used
    invalid: int
    unapproved: int
    readers: list
    runway: str
    fill: float
    good: bool
    targets: list
    problems: list
    photos: list = field(default_factory=list)   # index rows (authoring.md §6.7)


def runway_text(summary) -> tuple:
    """(label, fill 0..1, good) for a folder's runway (§6.3)."""
    if summary is None or not summary.readers:
        return S.RUNWAY_NOBODY, 0.0, False
    if summary.until is None:
        return S.RUNWAY_LONG, 1.0, True
    n = summary.runway_days
    if n >= planner.RUNWAY_FULL:
        return S.RUNWAY_FULL.format(n=n), 1.0, True
    return S.RUNWAY_OF.format(n=n), n / planner.RUNWAY_FULL, False


def folder_cards(snap: Snapshot) -> list:
    i, plan = snap.inputs, snap.plan
    summaries = {f.name: f for f in plan.folders}
    rules = snap.rules()
    out = []
    for name in sorted(i.stock.folders):
        folder = i.stock.folders[name]
        counts: dict = {}
        for e in folder.entries:
            st = plan.states[(name, e.file)].state
            counts[st] = counts.get(st, 0) + 1
        summary = summaries.get(name)
        label, fill, good = runway_text(summary)
        targets: list = []
        for rid in (summary.readers if summary else []):
            for t in rules[rid].targets:
                if t not in targets:
                    targets.append(t)
        out.append(FolderCard(
            name, snap.red(folder.title or name), folder.lane, folder.entries,
            counts.get("ready", 0) + counts.get("used", 0), counts.get("invalid", 0),
            counts.get("not-approved", 0), list(summary.readers if summary else []),
            label, fill, good, sorted(targets, key=target_order),
            [snap.red(p) for p in folder.problems], snap.photos.get(name, [])))
    return out


def photo_uses(snap: Snapshot, name: str, drafts=()) -> dict:
    """photo id -> "published" or "queued" for the stock packages of one folder whose
    `meta.photo` names it (authoring.md §6.7). Published means a published record row for
    the package. Then drafts: a draft in state `published` gives "published", any other
    draft "draft"; stock packages win (§8.8, §17.2)."""
    folder = snap.inputs.stock.folders.get(name)
    if folder is None:
        return {}
    published = record_index(snap.inputs.records)
    done = {pid for pid, _ in published}
    out: dict = {}
    for e in folder.entries:
        pid = e.package.meta.get("photo") if e.package else None
        if not isinstance(pid, str) or not fphotos.ID_RE.match(pid):
            continue
        if e.id in done:
            out[pid] = "published"
        else:
            out.setdefault(pid, "queued")
    for draft in drafts:
        if draft["folder"] == name and draft.get("state") == "published":
            out.setdefault(draft["photo"], "published")
    for draft in drafts:
        if draft["folder"] == name:
            out.setdefault(draft["photo"], "draft")
    return out


def rule_post_slots(snap: Snapshot, rule, networks) -> tuple:
    """(next, new): when the folder's next queued package goes out under the calendar plan
    (the first planned slot of the rule), and when one more post for `networks` queued now
    would (the first slot of the rule, after the planned ones, that breaks no slot limit).
    Either is None when the plan has no such slot in its window."""
    plan = snap.plan
    if plan is None:
        return None, None
    mine = [ps for ps in plan.slots if ps.slot.rule == rule.id and ps.when > snap.now]
    planned = [ps for ps in mine if ps.state in ("planned", "over-budget")]
    nxt = planned[0].when if planned else None
    tracker = planner.LimitTracker(snap.inputs.ruleset, planner.record_publications(snap.inputs.records))
    for ps in plan.slots:
        if ps.state in ("planned", "over-budget") and ps.when > snap.now:
            tracker.add({config.parse_target(t).network for t in ps.targets}, ps.when)
    nets = {config.parse_target(t).network for t in rule.targets} & set(networks)
    new = next((ps.when for ps in mine if ps.state == "no-content"
                and not tracker.violation(nets, ps.when, rule.zone)), None)
    return nxt, new


def folder_rows(snap: Snapshot, name: str) -> list | None:
    """Packages of one folder in publish order, with per-target states (§11.5)."""
    i, plan = snap.inputs, snap.plan
    folder = i.stock.folders.get(name)
    if folder is None:
        return None
    summary = next((f for f in plan.folders if f.name == name), None)
    rules = snap.rules()
    targets: list = []
    for rid in (summary.readers if summary else []):
        for t in rules[rid].targets:
            if t not in targets:
                targets.append(t)
    published = record_index(i.records)
    planned: dict = {}
    for ps in plan.slots:
        if ps.state in ("planned", "over-budget") and ps.entry is not None and ps.when > snap.now:
            for t in ps.targets:
                planned.setdefault((ps.entry.id, t), ps.when)
    rows = []
    for e in folder.entries:
        st = plan.states[(name, e.file)]
        per_target = []
        nets = e.networks()
        for t in sorted(targets, key=target_order):
            if network_of(t) not in nets:
                continue
            row = published.get((e.id, t))
            if row:
                when = parse_ts(row.get("ts"))
                per_target.append((t, "ok", S.PKG_PUBLISHED.format(
                    date=S.day_short(when.astimezone(snap.zone).date()) if when else "—"),
                    row.get("url")))
            elif (e.id, t) in planned:
                per_target.append((t, "plan", S.PKG_PLANNED.format(
                    date=S.when_words(planned[(e.id, t)].astimezone(snap.zone))), None))
            elif st.state in ("ready", "used"):
                per_target.append((t, "muted", S.PKG_STATE["ready"], None))
            else:
                per_target.append((t, "bad", S.PKG_STATE[st.state], None))
        variants = []
        if e.package:
            for net in sorted(e.package.variants, key=lambda n: config.NETWORK_ORDER.get(n, 9)):
                variants.append((net, snap.red(first_line(e.package.variants[net].text))))
        rows.append({"entry": e, "file": e.file, "theme": snap.red(e.package.theme if e.package else ""),
                     "state": st.state, "reason": snap.red(st.reason), "variants": variants,
                     "image": image_ref(e), "targets": per_target,
                     "planned": min((planned[(e.id, t)].astimezone(snap.zone) for t, kind, *_ in per_target
                                     if kind == "plan"), default=None)})
    return rows


# ---------------------------------------------------------------- rules (§11.6)

def rule_runway(snap: Snapshot, rule) -> tuple:
    """(label, fill, good) for a rule's folder: active from the calendar plan's run-out, a
    draft from its own plan as if activated (§6.3)."""
    if snap.inputs.stock.folders.get(rule.folder) is None:
        return S.NO_STOCK_FOLDER, 0.0, False
    plan = snap.plan if rule.active else snap.draft_plans.get(rule.id)
    until = plan.runout.get(rule.id) if plan else None
    if until is None:
        return S.RUNWAY_LONG, 1.0, True
    n = max(0, int((until - snap.now) // DAY))
    label = f"{n} из {planner.RUNWAY_FULL} · до {S.day_short(until.astimezone(snap.zone).date())}"
    return label, min(n, planner.RUNWAY_FULL) / planner.RUNWAY_FULL, n >= planner.RUNWAY_FULL


def rule_x_week(snap: Snapshot, rule):
    if "x" not in rule.targets:
        return None
    plan = snap.plan if rule.active else snap.draft_plans.get(rule.id)
    if plan is None:
        return None
    week = snap.now + 7 * DAY
    return sum((ps.x_cost for ps in plan.slots
                if ps.slot.rule == rule.id and ps.state in ("planned", "over-budget")
                and snap.now < ps.when <= week), start=Decimal(0))


def zone_offset(name: str, now: _dt.datetime) -> str:
    """UTC+1 (the offset the zone has now)."""
    try:
        off = now.astimezone(zoneinfo.ZoneInfo(name)).utcoffset()
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return ""
    minutes = int(off.total_seconds() // 60)
    sign = "+" if minutes >= 0 else S.MINUS
    h, m = divmod(abs(minutes), 60)
    return f"UTC{sign}{h}" + (f":{m:02d}" if m else "")


def folder_count(snap: Snapshot, name: str) -> int:
    folder = snap.inputs.stock.folders.get(name)
    if folder is None:
        return 0
    return sum(1 for e in folder.entries
               if snap.plan.states[(name, e.file)].state in ("ready", "used"))


# ---------------------------------------------------------------- calendar (§11.7)

@dataclass
class DayRow:
    when: _dt.datetime
    time: str
    target: str
    network: str
    state: str
    kind: str              # ok bad warn plan muted
    package: str = ""
    url: str | None = None
    entry: object | None = None
    draft: bool = False

    @property
    def counted(self) -> bool:
        """A publication that happened, is planned, or was attempted: day totals and network
        chips count these. Skips, misses, no content and draft rows are listed, not counted."""
        return not self.draft and self.state not in UNCOUNTED and \
            not self.state.startswith((S.S_SKIPPED + ":", S.S_OVER_LIMIT + ":"))


def _rows_for_slot(snap: Snapshot, ps, rules: dict, published: dict) -> list:
    rule = rules.get(ps.slot.rule)
    if rule is None:
        return []
    local = ps.when.astimezone(rule.zone)
    time_text = local.strftime("%H:%M %Z")
    log = ps.log
    claim = (log.claimed or {}) if log else {}
    pid = claim.get("package") or (ps.entry.id if ps.entry else "")
    entry = ps.entry or (find_entry(snap, pid) if pid else None)
    out = []

    def add(target, text, kind, url=None, draft=False):
        out.append(DayRow(ps.when, time_text, target, network_of(target), text, kind, pid, url,
                          entry, draft))

    st = ps.state
    if st == "done":
        outcome = (log.last.get("outcome") or {}) if log else {}
        for t in sorted(outcome, key=target_order):
            result = outcome[t]
            if result in ("published", "already"):
                row = published.get((pid, t)) or {}
                add(t, f"{S.S_PUBLISHED} · {pid}", "ok", row.get("url"))
            elif result == "failed":
                err = _record_error(snap, pid, t)
                add(t, f"{S.S_FAILED}: {snap.red(err)}" if err else S.S_FAILED, "bad")
            elif result == "unknown":
                add(t, S.S_UNKNOWN, "warn")
            elif result == fjournal.SKIPPED_BUDGET:
                add(t, S.S_X_BUDGET, "warn")
            else:
                add(t, snap.red(result), "muted")
    elif st == "missed":
        reason = (log.last.get("reason") if log else "") or ""
        text = f"{S.S_SKIPPED}: {S.MISSED_REASONS.get(reason, snap.red(reason))}"
        for t in rule.targets:
            add(t, text, "warn")
    elif st == "refused":
        reason = snap.red((log.last.get("reason") if log else "") or "")
        for t in claim.get("targets") or rule.targets:
            add(t, f"{S.S_REFUSED}: {reason}", "bad")
    elif st == "interrupted":
        for t in claim.get("targets") or rule.targets:
            add(t, S.S_INTERRUPTED, "warn")
    elif st == "resolved":
        yes = bool(log.last.get("published")) if log else False
        for t in claim.get("targets") or rule.targets:
            add(t, S.S_RESOLVED_YES if yes else S.S_RESOLVED_NO, "muted")
    elif st == "claimed":
        for t in claim.get("targets") or rule.targets:
            add(t, S.S_CLAIMED, "plan")
    elif st == "due":
        for t in rule.targets:
            add(t, S.S_DUE, "plan")
    elif st in ("planned", "over-budget"):
        title = _folder_title(snap, rule.folder)
        for t in sorted(set(ps.targets) | set(ps.skipped), key=target_order):
            if t in ps.skipped:
                add(t, S.S_X_BUDGET, "warn")
            else:
                add(t, f"{title} → {S.MONO.get(network_of(t), t)}", "plan")
    elif st == "over-limit":
        for t in ps.targets or rule.targets:
            add(t, f"{S.S_OVER_LIMIT}: {snap.red(ps.reason)}", "warn")
    elif st == "no-content":
        for t in rule.targets:
            add(t, S.S_NO_CONTENT, "bad")
    elif st == "draft":
        for t in rule.targets:
            add(t, S.S_DRAFT, "muted", draft=True)
    return out


def _folder_title(snap: Snapshot, name: str) -> str:
    folder = snap.inputs.stock.folders.get(name)
    return snap.red(folder.title if folder and folder.title else name)


def _record_error(snap: Snapshot, pid: str, target: str) -> str:
    found = ""
    for row in snap.inputs.records:
        if row.get("package") == pid and row.get("target") == target and \
                row.get("status") == "failed":
            found = str(row.get("error") or "")
    return found


def day_rows(snap: Snapshot, plan) -> dict:
    """local date -> [DayRow] for every slot in the plan and every manual publication."""
    rules = snap.rules()
    published = record_index(snap.inputs.records)
    zone = snap.zone
    out: dict = {}
    for ps in plan.slots:
        for row in _rows_for_slot(snap, ps, rules, published):
            out.setdefault(ps.when.astimezone(zone).date(), []).append(row)
    for rec in plan.manual:
        when = parse_ts(rec.get("ts"))
        if when is None:
            continue
        t = rec.get("target", "")
        entry = find_entry(snap, rec.get("package"))
        out.setdefault(when.astimezone(zone).date(), []).append(DayRow(
            when, when.astimezone(zone).strftime("%H:%M %Z"), t, network_of(t),
            S.S_MANUAL, "ok", rec.get("package", ""), rec.get("url"), entry))
    for rows in out.values():
        rows.sort(key=lambda r: (r.when, target_order(r.target)))
    return out


def calendar_months(snap: Snapshot, more: int) -> list:
    today = snap.today
    n = MONTHS_AHEAD + 2 + 3 * max(0, min(more, MAX_MORE))
    out = []
    for k in range(-1, n - 1):
        index = today.year * 12 + today.month - 1 + k
        out.append((index // 12, index % 12 + 1))
    return out


# ---------------------------------------------------------------- reach (§11.8)

@dataclass
class ReachRow:
    target: str
    network: str
    post_id: str
    url: str | None
    when: _dt.datetime | None
    package: str
    text: str
    entry: object | None
    metrics: dict


def reach_rows(snap: Snapshot) -> list:
    i = snap.inputs
    latest = snap.latest or {}
    posts = {}
    for p in latest.get("posts") or []:
        if isinstance(p, dict) and p.get("target") and p.get("post_id") is not None:
            posts[(str(p["target"]), str(p["post_id"]))] = p
    published: dict = {}
    for row in i.records:
        t, pid = row.get("target"), row.get("post_id")
        if not t or pid is None:
            continue
        key = (t, str(pid))
        if row.get("status") == "published":
            published[key] = row
        elif row.get("status") == "deleted":
            published.pop(key, None)
    out = []
    for (t, pid), row in published.items():
        net = row.get("network") or network_of(t)
        entry = find_entry(snap, row.get("package"))
        text = variant_text(entry, net) if entry else ""
        metrics = {}
        p = posts.get((t, pid)) or {}
        for name in ("views", "likes", "comments", "saves"):
            v = p.get(name)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                metrics[name] = int(v)
        for name in ("reposts", "shares"):
            v = p.get(name)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                metrics["reposts"] = metrics.get("reposts", 0) + int(v)
        out.append(ReachRow(t, net, pid, row.get("url"), parse_ts(row.get("ts")),
                            row.get("package") or "", snap.red(text or row.get("package") or pid),
                            entry, metrics))
    return out


def _popular_key(r: ReachRow):
    if "views" in r.metrics:
        return (1, r.metrics["views"])
    return (0, sum(r.metrics.get(k, 0) for k in ("likes", "comments", "reposts")))


def sort_reach(rows: list, sort: str) -> list:
    """Popular: views descending, posts without views by likes + comments + reposts after
    them. Weak: the same order ascending. Posts without any metric (the network gives no
    stats, or the post is not in latest.json yet) come last in every metric sort."""
    epoch = _dt.datetime.min.replace(tzinfo=_dt.timezone.utc)
    by_time = lambda r: (r.when or epoch, r.target, r.post_id)  # noqa: E731
    if sort == "new":
        return sorted(rows, key=by_time, reverse=True)
    if sort == "old":
        return sorted(rows, key=by_time)
    measured = [r for r in rows if r.metrics]
    unmeasured = sorted((r for r in rows if not r.metrics), key=by_time, reverse=True)
    if sort == "weak":
        return sorted(measured, key=lambda r: (_popular_key(r), by_time(r))) + unmeasured
    if sort == "likes":
        return sorted(measured, key=lambda r: (r.metrics.get("likes", -1), by_time(r)),
                      reverse=True) + unmeasured
    return sorted(measured, key=lambda r: (_popular_key(r), by_time(r)), reverse=True) + unmeasured


def no_access(snap: Snapshot) -> list:
    """(target, permission) for every target whose last collection lacked a permission."""
    results = ((snap.collect or {}).get("results") or {}) if snap.collect else {}
    out = []
    for t in sorted(results, key=target_order):
        value = str(results[t])
        if value.startswith("no-permission"):
            out.append((t, snap.red(value[len("no-permission"):].strip() or "?")))
    return out


# ---------------------------------------------------------------- followers (§11.9)

PERIOD_DAYS = {"week": 7, "30": 30, "90": 90, "all": None}


@dataclass
class FollowerCard:
    target: str
    network: str
    number: int
    delta: int | None
    points: list           # [(date, n)] in the period
    days: int


def follower_cards(snap: Snapshot, period: str) -> list:
    series = ((snap.latest or {}).get("followers") or {}) if snap.latest else {}
    days = PERIOD_DAYS.get(period, 30)
    cutoff = snap.today - _dt.timedelta(days=days - 1) if days else None
    out = []
    for target, raw in series.items():
        points = []
        for item in raw if isinstance(raw, list) else []:
            try:
                d, n = _dt.date.fromisoformat(str(item[0])), int(item[1])
            except (ValueError, TypeError, IndexError):
                continue
            points.append((d, n))
        points.sort()
        if not points:
            continue
        number = points[-1][1]
        shown = [p for p in points if cutoff is None or p[0] >= cutoff]
        delta = shown[-1][1] - shown[0][1] if len(shown) >= 2 else None
        out.append(FollowerCard(str(target), network_of(str(target)), number, delta, shown,
                                len(shown)))
    out.sort(key=lambda c: (-c.number, target_order(c.target)))
    return out
