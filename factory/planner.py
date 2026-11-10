"""Planner: slots, package states, assignment, runway, run-out and X projection (§6.2, §8).

`plan()` is pure. It reads no file and no clock: the caller passes the rules, the stock, the
poster record rows, the journal rows, the X month totals, the settings and `now`. The runner
uses the same `package_states`, `pick`, `Taken` and `LimitTracker`, so what `plan` shows is
what a tick does.
"""

from __future__ import annotations

import bisect
import datetime as _dt
from dataclasses import dataclass, field
from decimal import Decimal

from poster import config, xapi
from factory import journal as fjournal
from factory.ruleset import DAYS

UTC = _dt.timezone.utc
DAY = _dt.timedelta(days=1)
RUNWAY_DAYS = 400          # §6.3: the simulation stops at 400 days
RUNWAY_FULL = 90           # "N of 90 days"
RECORD_TAKEN = ("published", "unknown", "deleted")


# ---------------------------------------------------------------- slots (§8.1)

def local_to_utc(naive: _dt.datetime, zone) -> _dt.datetime:
    """Wall time in `zone` -> UTC. A time the clock skips moves to the first valid minute
    after it; a time that occurs twice uses its first occurrence (fold=0)."""
    def exists(t):
        aware = t.replace(tzinfo=zone, fold=0)
        return aware.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == t
    probe = naive
    for _ in range(24 * 60):
        if exists(probe):
            return probe.replace(tzinfo=zone, fold=0).astimezone(UTC)
        probe += _dt.timedelta(minutes=1)
    raise ValueError(f"no valid local time after {naive}")


@dataclass(frozen=True)
class Slot:
    rule: str
    when: _dt.datetime      # UTC

    @property
    def key(self) -> str:
        return f"{self.rule}@{config.iso_utc(self.when)}"


def rule_slots(rule, start: _dt.datetime, end: _dt.datetime) -> list:
    """Slots of one rule with start <= when <= end, in time order."""
    zone = rule.zone
    wanted = {DAYS.index(d) for d in rule.days}
    day = start.astimezone(zone).date() - DAY
    last = end.astimezone(zone).date() + DAY
    out = []
    while day <= last:
        if day.weekday() in wanted:
            for hour in rule.hours:
                naive = _dt.datetime(day.year, day.month, day.day, int(hour[:2]))
                when = local_to_utc(naive, zone)
                if start <= when <= end:
                    out.append(Slot(rule.id, when))
        day += DAY
    return out


def all_slots(rules, start, end) -> list:
    slots = []
    for rule in rules:
        slots.extend(rule_slots(rule, start, end))
    return sorted(slots, key=lambda s: (s.when, s.rule))


# ---------------------------------------------------------------- record helpers

def record_latest(records: list[dict]) -> dict:
    latest: dict = {}
    for row in records:
        key = (row.get("package"), row.get("target"))
        if key[0] and key[1]:
            latest[key] = row
    return latest


def record_publications(records: list[dict]) -> list:
    """(network, UTC time) of every real publication in the poster record, manual ones too."""
    out = []
    for row in records:
        if row.get("status") == "published" and row.get("network") and row.get("ts"):
            try:
                out.append((row["network"], config.parse_utc(row["ts"])))
            except (ValueError, TypeError):
                continue
    return out


# ---------------------------------------------------------------- package states (§6.2)

@dataclass(frozen=True)
class PackageState:
    state: str          # invalid | not-approved | held | check-account | used | ready
    reason: str = ""


def _held_reason(entry, logs: list) -> str | None:
    fp = list(entry.fingerprint)
    mine = [log for log in logs if log.package == entry.id]
    for log in reversed(mine):
        refused = log.last_with("refused")
        if refused and refused.get("held") and (log.claimed or {}).get("fp") == fp:
            return refused.get("reason") or "the poster refused the package"
        if refused:
            break
    attempts = [log for log in mine if log.status == "done"]
    if len(attempts) >= 2:
        last_two = attempts[-2:]
        if all(_all_failed(log.last) and (log.claimed or {}).get("fp") == fp
               for log in last_two):
            return "failed on every target on 2 slots in a row"
    return None


def _all_failed(row: dict) -> bool:
    outcome = row.get("outcome") or {}
    sent = [v for v in outcome.values() if v != fjournal.SKIPPED_BUDGET]
    return bool(sent) and all(v == "failed" for v in sent)


def package_states(ruleset, stock, records: list[dict], logs: dict, extra_active=None) -> dict:
    """(folder, file) -> PackageState for every stock entry."""
    latest = record_latest(records)
    resolved_published = fjournal.taken_pairs(
        {k: v for k, v in logs.items() if v.status == "resolved"})
    interrupted = {log.package for log in logs.values() if log.status == "interrupted"}
    log_list = list(logs.values())
    states = {}
    for folder in stock.folders.values():
        readers = [r for r in ruleset.rules if r.folder == folder.name]
        active = [r for r in readers if r.active or r.id == extra_active]
        networks = set()
        for r in readers:
            networks |= r.networks()
        for entry in folder.entries:
            problems = entry.check(networks)
            if problems:
                st = PackageState("invalid", problems[0])
            elif not entry.approved:
                st = PackageState("not-approved")
            elif (held := _held_reason(entry, log_list)):
                st = PackageState("held", held)
            elif entry.id in interrupted or any(
                    (latest.get((entry.id, t)) or {}).get("status") == "unknown"
                    for t in _record_targets(latest, entry.id)):
                st = PackageState("check-account")
            elif active and all(
                    (latest.get((entry.id, t)) or {}).get("status") in ("published", "deleted")
                    or (entry.id, t) in resolved_published
                    for r in active for t in r.targets
                    if config.parse_target(t).network in entry.networks()):
                st = PackageState("used")
            else:
                st = PackageState("ready")
            states[(folder.name, entry.file)] = st
    return states


def _record_targets(latest: dict, package_id: str) -> list:
    return [t for (p, t) in latest if p == package_id]


# ---------------------------------------------------------------- assignment (§8.2)

class Taken:
    """(package id, target) pairs that no slot may take again."""

    def __init__(self, records: list[dict], logs: dict):
        self.pairs = {key for key, row in record_latest(records).items()
                      if row.get("status") in RECORD_TAKEN}
        self.pairs |= fjournal.taken_pairs(logs)

    def add(self, package_id: str, targets) -> None:
        for t in targets:
            self.pairs.add((package_id, t))

    def free(self, package_id: str, targets) -> bool:
        return not any((package_id, t) in self.pairs for t in targets)


def variant_targets(rule, entry) -> list:
    """The rule's targets that the package has a variant for, in the rule's order."""
    networks = entry.networks()
    return [t for t in rule.targets if config.parse_target(t).network in networks]


def pick(rule, stock, states: dict, taken: Taken):
    """First package in the folder's order that is ready, has a variant for one of the rule's
    targets, and is free on every such target. None when the folder has nothing left."""
    folder = stock.folders.get(rule.folder)
    if folder is None:
        return None
    for entry in folder.entries:
        if states.get((folder.name, entry.file), PackageState("invalid")).state != "ready":
            continue
        targets = variant_targets(rule, entry)
        if targets and taken.free(entry.id, targets):
            return entry
    return None


# ---------------------------------------------------------------- limits (§7.2)

class LimitTracker:
    """Publications per network, for max-per-day and min-gap checks."""

    def __init__(self, ruleset, events=()):
        self.ruleset = ruleset
        self.times: dict = {}
        for network, when in events:
            self.add([network], when)

    def add(self, networks, when) -> None:
        for n in networks:
            bisect.insort(self.times.setdefault(n, []), when)

    def violation(self, networks, when, zone) -> tuple | None:
        """(kind, message) for the first broken limit, kind 'limit' or 'gap'; None when ok."""
        for n in sorted(networks):
            limit = self.ruleset.limit(n)
            times = self.times.get(n, [])
            gap = _dt.timedelta(hours=limit.min_gap_hours)
            lo = bisect.bisect_left(times, when - max(gap, DAY))
            hi = bisect.bisect_right(times, when + max(gap, DAY))
            near = times[lo:hi]
            close = [t for t in near if abs(t - when) < gap]
            if close:
                hours = abs(close[0] - when).total_seconds() / 3600
                return ("gap", f"{n}: {hours:.1f} h from the post at "
                               f"{config.iso_utc(close[0])} (min {limit.min_gap_hours:g} h)")
            day = when.astimezone(zone).date()
            same_day = [t for t in near if t.astimezone(zone).date() == day]
            if len(same_day) + 1 > limit.max_per_day:
                return ("limit", f"{n}: post {len(same_day) + 1} on {day.isoformat()} "
                                 f"(max {limit.max_per_day} a day)")
        return None


# ---------------------------------------------------------------- plan

@dataclass
class PlanSlot:
    slot: Slot
    state: str                    # planned no-content over-limit over-budget draft | due |
    #                               claimed done refused missed interrupted resolved
    entry: object | None = None
    targets: tuple = ()           # targets that would be sent
    skipped: dict = field(default_factory=dict)   # target -> reason
    x_cost: Decimal = Decimal(0)
    reason: str = ""
    log: object | None = None     # journal SlotLog for past slots

    @property
    def key(self) -> str:
        return self.slot.key

    @property
    def when(self):
        return self.slot.when


@dataclass
class FolderSummary:
    name: str
    lane: str | None
    counts: dict
    readers: list                 # active rule ids
    runway_days: int | None       # None: > 400 days, or nobody takes it (readers empty)
    until: _dt.datetime | None


@dataclass
class Plan:
    now: _dt.datetime
    start: _dt.datetime
    end: _dt.datetime
    slots: list
    states: dict
    folders: list
    runout: dict                  # active rule id -> datetime | None
    x: dict                       # "YYYY-MM" -> (spent, planned) for this and next month
    publications_7d: int
    active: int
    drafts: int
    manual: list                  # manual publications in the window (poster record rows)

    def first_runout(self):
        found = [(when, rid) for rid, when in self.runout.items() if when is not None]
        return min(found) if found else None


def month_key(when: _dt.datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m")


def next_month(month: str) -> str:
    year, mon = int(month[:4]), int(month[5:])
    return f"{year + (mon == 12):04d}-{mon % 12 + 1:02d}"


def plan(ruleset, stock, records: list[dict], journal_rows: list[dict], x_spent: dict,
         settings, now: _dt.datetime, *, days: int = 30, back_days: float = 0,
         extra_active: str | None = None, only_rule: str | None = None,
         runway: bool = True) -> Plan:
    """Simulate from now: assign packages to future slots of active rules (§8.2).

    `back_days` adds past slots (journal state, or `due`). `extra_active` treats one draft
    rule as active (a draft row's runway, §6.3; activation checks, §7.3). `runway=False`
    stops the simulation at the window's end (the runner needs only the past slots)."""
    logs = fjournal.index(journal_rows)
    states = package_states(ruleset, stock, records, logs, extra_active)
    taken = Taken(records, logs)
    limits = LimitTracker(ruleset, record_publications(records))
    start = now - _dt.timedelta(days=back_days)
    end = now + _dt.timedelta(days=days)
    sim_end = now + _dt.timedelta(days=max(days, RUNWAY_DAYS if runway else 0))
    active = [r for r in ruleset.rules if r.active or r.id == extra_active]
    drafts = [r for r in ruleset.rules if not (r.active or r.id == extra_active)]
    by_id = {r.id: r for r in ruleset.rules}

    out: list[PlanSlot] = []
    # past slots: from the journal; a slot of an active rule without an entry is due
    for s in all_slots(ruleset.rules, start, now):
        rule, log = by_id[s.rule], logs.get(s.key)
        if log is not None:
            claim = log.first_claim or {}
            entry = _find_entry(stock, claim.get("folder"), claim.get("file"))
            out.append(PlanSlot(s, log.status, entry, tuple((log.claimed or {}).get("targets") or ()),
                                reason=log.last.get("reason", ""), log=log))
        elif rule.active and _since(rule) <= s.when:
            out.append(PlanSlot(s, "due"))
        elif not rule.active:
            out.append(PlanSlot(s, "draft"))

    x_planned: dict = {}
    x_capped: dict = {}
    x_counted: set = set()
    runout: dict = {r.id: None for r in active}
    open_rules = {r.id for r in active}
    future = [s for s in all_slots(active, now, sim_end) if s.when > now]
    for s in future:
        if s.when > end and not open_rules:
            break
        rule = by_id[s.rule]
        if s.key in logs or s.when < _since(rule):
            continue
        entry = pick(rule, stock, states, taken)
        if entry is None:
            if runout.get(rule.id) is None:
                runout[rule.id] = s.when
            open_rules.discard(rule.id)
            ps = PlanSlot(s, "no-content")
        else:
            targets = variant_targets(rule, entry)
            networks = {config.parse_target(t).network for t in targets}
            broken = limits.violation(networks, s.when, rule.zone)
            if broken:
                ps = PlanSlot(s, "over-limit", entry, tuple(targets), reason=broken[1])
            else:
                ps = PlanSlot(s, "planned", entry, tuple(targets))
                if "x" in targets:
                    v = entry.package.variants["x"]
                    cost = xapi.estimate(v.text, bool(v.image_path), settings)
                    month = month_key(s.when)
                    if entry.id not in x_counted:
                        # an over-budget X-only slot leaves the package free for X, so the
                        # next slot offers it again; the projection counts its cost once
                        x_counted.add(entry.id)
                        x_planned[month] = x_planned.get(month, Decimal(0)) + cost
                    spent = x_spent.get(month, Decimal(0))
                    if spent + x_capped.get(month, Decimal(0)) + cost > settings.cap:
                        ps.state = "over-budget"
                        ps.targets = tuple(t for t in targets if t != "x")
                        ps.skipped = {"x": "budget"}
                    else:
                        x_capped[month] = x_capped.get(month, Decimal(0)) + cost
                    ps.x_cost = cost
                taken.add(entry.id, ps.targets)
                limits.add({config.parse_target(t).network for t in ps.targets}, s.when)
        if s.when <= end:
            out.append(ps)
    for s in all_slots(drafts, now, end):
        if s.when > now and s.key not in logs:
            out.append(PlanSlot(s, "draft"))
    out.sort(key=lambda p: (p.when, p.slot.rule))
    if only_rule:
        out = [p for p in out if p.slot.rule == only_rule]

    this_month = month_key(now)
    months = (this_month, next_month(this_month))
    x = {m: (x_spent.get(m, Decimal(0)), x_planned.get(m, Decimal(0))) for m in months}
    week = now + 7 * DAY
    pubs = sum(len(p.targets) for p in out
               if p.state in ("planned", "over-budget") and now < p.when <= week)

    folders = []
    for name in sorted(stock.folders):
        folder = stock.folders[name]
        counts: dict = {}
        for entry in folder.entries:
            st = states[(name, entry.file)].state
            counts[st] = counts.get(st, 0) + 1
        readers = sorted(r.id for r in active if r.folder == name)
        until = None
        days_left = None
        if readers:
            ends = [runout[r] for r in readers if runout[r] is not None]
            if ends:
                until = min(ends)
                days_left = max(0, int((until - now) // DAY))
        folders.append(FolderSummary(name, folder.lane, counts, readers, days_left, until))

    manual_packages = {log.package for log in logs.values() if log.package}
    manual = [row for row in records
              if row.get("status") == "published" and row.get("package") not in manual_packages
              and _in_window(row, start, end)]
    return Plan(now, start, end, out, states, folders,
                {rid: runout[rid] for rid in sorted(runout)}, x, pubs,
                len(active), len(drafts), manual)


def _since(rule) -> _dt.datetime:
    if rule.active_since:
        return config.parse_utc(rule.active_since)
    return _dt.datetime.min.replace(tzinfo=UTC)


def _in_window(row, start, end) -> bool:
    try:
        return start <= config.parse_utc(row.get("ts", "")) <= end
    except (ValueError, TypeError):
        return False


def _find_entry(stock, folder, file):
    f = stock.folders.get(folder) if folder else None
    if f is None:
        return None
    for entry in f.entries:
        if entry.file == file:
            return entry
    return None
