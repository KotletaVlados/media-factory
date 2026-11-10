"""Activation checks (§7.3) and the stock and rules check behind `factory check`.

`factory check`, `factory rule start` and `factory rule set` (on an active rule) run the same
`activation_problems`. A refusal never touches the rules file.
"""

from __future__ import annotations

import datetime as _dt

from poster import config, linkedin
from factory import journal as fjournal, planner

CHECK_DAYS = 14
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")


def month_name(month: str) -> str:
    return MONTHS[int(month[5:]) - 1]


def basic_problems(inputs, rule, now) -> list[str]:
    """§7.3 items 1-3: folder and ready content, targets and their variables, lane."""
    problems: list[str] = []
    folder = inputs.stock.folders.get(rule.folder)
    if folder is None:
        problems.append(f"folder '{rule.folder}' does not exist in the stock")
    else:
        problems.extend(f"folder '{rule.folder}': {p}" for p in folder.problems)
        logs = fjournal.index(inputs.journal)
        states = planner.package_states(inputs.ruleset, inputs.stock, inputs.records, logs,
                                        extra_active=rule.id)
        if planner.pick(rule, inputs.stock, states, planner.Taken(inputs.records, logs)) is None:
            problems.append(f"folder '{rule.folder}' has no ready package for "
                            f"{', '.join(rule.targets)}")
    known = {t.id: t for t in config.derived_targets(inputs.env)}
    for spec in rule.targets:
        target = known.get(spec)
        if target is None:
            problems.append(f"target {spec} is unknown (known: {', '.join(sorted(known))})")
            continue
        missing = target.missing(inputs.env)
        if missing:
            problems.append(f"target {spec}: missing {', '.join(missing)} in the env file")
        elif target.network == "linkedin":
            errors, _ = linkedin.token_problems(inputs.env, now)
            problems.extend(f"target {spec}: {e}" for e in errors)
    if folder is not None and folder.lane == "text" and any(
            config.parse_target(t).network == "instagram" for t in rule.targets):
        problems.append(f"folder '{rule.folder}' is a text lane and cannot feed Instagram "
                        "(Instagram needs an image)")
    return problems


def limit_problems(ruleset, rules, now) -> list[str]:
    """§7.3 item 4: concrete slots of `rules` over the next 14 days against §7.2 limits."""
    end = now + _dt.timedelta(days=CHECK_DAYS)
    by_network: dict = {}
    for rule in rules:
        for s in planner.rule_slots(rule, now, end):
            for network in sorted(rule.networks()):
                by_network.setdefault(network, []).append((s.when, rule))
    problems: list[str] = []
    for network in sorted(by_network):
        limit = ruleset.limit(network)
        items = sorted(by_network[network], key=lambda i: (i[0], i[1].id))
        gap = _dt.timedelta(hours=limit.min_gap_hours)
        for (a, ra), (b, rb) in zip(items, items[1:]):
            if b - a < gap:
                problems.append(
                    f"{network}: {_local(a, ra)} ({ra.id}) and {_local(b, rb)} ({rb.id}) are "
                    f"{(b - a).total_seconds() / 3600:g} h apart; the minimum gap is "
                    f"{limit.min_gap_hours:g} h")
                break
        per_day: dict = {}
        for when, rule in items:
            local = when.astimezone(rule.zone)
            per_day.setdefault(local.date(), []).append((local, rule))
        for day in sorted(per_day):
            posts = per_day[day]
            if len(posts) > limit.max_per_day:
                hours = ", ".join(f"{t:%H:%M} ({r.id})" for t, r in posts)
                problems.append(f"{network}: {len(posts)} posts on {day.isoformat()} at {hours}; "
                                f"the maximum is {limit.max_per_day} a day")
                break
    return problems


def _local(when, rule) -> str:
    return when.astimezone(rule.zone).strftime("%Y-%m-%d %H:%M %Z")


def budget_problems(inputs, now, extra_active=None) -> list[str]:
    """§7.3 item 5: X spend so far plus the planned X posts, this month and next."""
    p = planner.plan(inputs.ruleset, inputs.stock, inputs.records, inputs.journal,
                     inputs.x_spent, inputs.settings, now, days=0, extra_active=extra_active)
    cap = inputs.settings.cap
    problems = []
    for month, (spent, planned) in p.x.items():
        if spent + planned > cap:
            problems.append(f"X {month_name(month)}: ${spent:.3f} spent + ${planned:.3f} planned "
                            f"= ${spent + planned:.3f} of ${cap:.2f}")
    return problems


def activation_problems(inputs, rule, now) -> list[str]:
    """Everything §7.3 refuses for `rule` (treated as active alongside the active rules)."""
    problems = basic_problems(inputs, rule, now)
    active = [r for r in inputs.ruleset.rules if r.active and r.id != rule.id] + [rule]
    problems += limit_problems(inputs.ruleset, active, now)
    problems += budget_problems(inputs, now, extra_active=rule.id)
    return problems


def check_all(inputs, now) -> tuple[list[str], list[str]]:
    """(problems, notes) for `factory check`: problems make it exit 2."""
    problems: list[str] = list(f"stock: {p}" for p in inputs.stock.problems)
    notes: list[str] = []
    for name in sorted(inputs.stock.folders):
        problems.extend(f"folder '{name}': {p}" for p in inputs.stock.folders[name].problems)
    logs = fjournal.index(inputs.journal)
    states = planner.package_states(inputs.ruleset, inputs.stock, inputs.records, logs)
    for entry in inputs.stock.entries():
        st = states[(entry.folder, entry.file)]
        where = f"{entry.folder}/{entry.file}"
        if st.state == "invalid":
            problems.append(f"{where}: needs fixing: {st.reason}")
        elif st.state == "not-approved":
            notes.append(f"{where}: not approved (no meta.approved_by_operator); never published")
        elif st.state == "held":
            notes.append(f"{where}: held: {st.reason}")
        elif st.state == "check-account":
            notes.append(f"{where}: unknown — check the account")
    active = [r for r in inputs.ruleset.rules if r.active]
    for rule in inputs.ruleset.rules:
        found = basic_problems(inputs, rule, now)
        if rule.active:
            problems.extend(f"rule '{rule.id}': {p}" for p in found)
        else:
            notes.extend(f"draft '{rule.id}': {p}" for p in found)
    if active:
        problems += limit_problems(inputs.ruleset, active, now)
        problems += budget_problems(inputs, now)
    return problems, notes
