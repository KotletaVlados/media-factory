"""Command line `python3 -m factory` (design factory.md §12).

Everything printed goes through the poster's redacting output path, loaded with the env
file's secrets. Exit codes follow the poster: 0 ok; 1 a slot ended failed, unknown, refused or
interrupted; 2 usage or validation error.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import os
import sys
import traceback

from poster import config
from poster.cli import Out
from poster.redact import Redactor
from factory import (__version__, attention, checks, inputs as finputs, journal as fjournal,
                     paths as fpaths, planner, ruleset as fruleset)
from factory.runner import Runner

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
STATE_LABELS = (("ready", "ready"), ("not-approved", "not approved"), ("invalid", "invalid"),
                ("held", "held"), ("check-account", "check account"), ("used", "used"))
DEFAULT_DAYS = "mon,wed,fri"      # the starter proposal (§13.1, §17 item 2)
DEFAULT_HOURS = "10:00"
DEFAULT_PROFILE = "kotleta"


class Usage(Exception):
    pass


def utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def machine_zone(environ) -> str:
    tz = (environ.get("TZ") or "").lstrip(":")
    if fruleset.valid_zone(tz):
        return tz
    real = os.path.realpath("/etc/localtime")
    if "zoneinfo/" in real:
        name = real.split("zoneinfo/", 1)[1]
        if fruleset.valid_zone(name):
            return name
    return "UTC"


def _days_arg(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a whole number of days") from None
    if not 1 <= n <= 400:
        raise argparse.ArgumentTypeError("must be between 1 and 400")
    return n


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python3 -m factory",
                                description="Stock, rules, plan and timed publishing.")
    p.add_argument("--env-file", help="env file (default: MF_ENV_FILE or <repo>/.env)")
    p.add_argument("--content", help="content folder holding stock/ and rules.json "
                                     "(default: MF_CONTENT_DIR or <repo>/content)")
    p.add_argument("--state-dir", help="factory state folder (default: MF_FACTORY_STATE_DIR or "
                                       "$XDG_STATE_HOME/media-factory/factory)")
    p.add_argument("--debug", action="store_true", help="print redacted tracebacks")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="validate stock and rules")
    pl = sub.add_parser("plan", help="slots, runway, run-out, X projection")
    pl.add_argument("--days", type=_days_arg, default=30)
    pl.add_argument("--rule")
    tk = sub.add_parser("tick", help="publish due slots, write the heartbeat")
    tk.add_argument("--dry-run", action="store_true",
                    help="show what would publish now; publish and write nothing")
    sub.add_parser("status", help="last tick, next slots, attention items")
    rt = sub.add_parser("retry", help="re-publish the failed targets of a done slot")
    rt.add_argument("slot")
    rs = sub.add_parser("resolve", help="record the account check for an interrupted slot")
    rs.add_argument("slot")
    g = rs.add_mutually_exclusive_group(required=True)
    g.add_argument("--published", action="store_true")
    g.add_argument("--not-published", action="store_true")

    rule = sub.add_parser("rule", help="create, start, stop or edit a rule")
    rsub = rule.add_subparsers(dest="rule_command", required=True)
    for name, text in (("new", "create a draft rule"), ("set", "edit a rule")):
        r = rsub.add_parser(name, help=text)
        r.add_argument("id")
        r.add_argument("--folder")
        r.add_argument("--targets", help="comma-separated, e.g. fb:NAME,ig:NAME,linkedin,x")
        r.add_argument("--days", help="comma-separated mon..sun")
        r.add_argument("--hours", help="comma-separated whole hours 06:00..23:00")
        r.add_argument("--timezone", help="IANA zone (default: this machine's zone)")
    rsub.add_parser("start", help="activate a rule after the §7.3 checks").add_argument("id")
    rsub.add_parser("stop", help="return a rule to draft").add_argument("id")

    tm = sub.add_parser("timer", help="systemd user units for the tick")
    tm.add_argument("--print", action="store_true", required=True, dest="print_units")
    return p


class App:
    def __init__(self, args, environ, clock, out, redactor, publish, machine_tz):
        self.args, self.environ, self.clock, self.out = args, environ, clock, out
        self.redactor, self.publish, self.machine_tz = redactor, publish, machine_tz
        self.paths = fpaths.resolve(environ, env_file=args.env_file, content=args.content,
                                    state=args.state_dir)

    def inputs(self):
        return finputs.load(self.paths, self.clock, self.redactor)

    def runner(self, dry_run=False) -> Runner:
        return Runner(self.paths, self.environ, self.clock, self.out, publish=self.publish,
                      dry_run=dry_run, redactor=self.redactor)


def main(argv=None, *, environ=None, clock=None, stdout=None, stderr=None, publish=None,
         machine_tz=None) -> int:
    environ = os.environ if environ is None else environ
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    redactor = Redactor()
    out = Out(redactor, stdout, stderr)
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    app = App(args, environ, clock or utc_now, out, redactor, publish,
              machine_tz or machine_zone(environ))
    try:
        if args.command == "rule":
            return RULE_COMMANDS[args.rule_command](app)
        return COMMANDS[args.command](app)
    except (Usage, config.ConfigError, fruleset.RevisionMismatch) as exc:
        out(f"error: {exc}", err=True)
        return 2
    except fruleset.RulesError as exc:
        out("error: rules file is invalid:", err=True)
        for problem in exc.problems:
            out(f"  - {problem}", err=True)
        return 2
    except Exception as exc:  # the single last-resort path; always redacted
        out(f"error: {type(exc).__name__}: {exc}", err=True)
        if args.debug:
            out(traceback.format_exc(), err=True)
        return 1


# ---------------------------------------------------------------- check

def cmd_check(app: App) -> int:
    inputs = app.inputs()
    problems, notes = checks.check_all(inputs, app.clock())
    folders, packages = len(inputs.stock.folders), sum(1 for _ in inputs.stock.entries())
    rules = inputs.ruleset.rules
    app.out(f"check: {folders} folder(s), {packages} package(s), "
            f"{sum(r.active for r in rules)} active rule(s), "
            f"{sum(not r.active for r in rules)} draft(s)")
    for note in notes:
        app.out(f"  note: {note}")
    if problems:
        app.out("problems:", err=True)
        for problem in problems:
            app.out(f"  - {problem}", err=True)
        return 2
    app.out("ok")
    return 0


# ---------------------------------------------------------------- plan

def _money(value) -> str:
    return f"${value:.3f}"


def _slot_time(when: _dt.datetime, zone) -> str:
    local = when.astimezone(zone)
    return f"{local:%Y-%m-%d} {WEEKDAYS[local.weekday()]} {local:%H:%M %Z}"


def runway_text(f: planner.FolderSummary) -> str:
    if not f.readers:
        return "nobody takes it · use 0"
    if f.until is None:
        return f"runway > {planner.RUNWAY_DAYS} days ✓"
    until = f.until.date().isoformat()
    if f.runway_days >= planner.RUNWAY_FULL:
        return f"runway {f.runway_days} days ✓ (until {until})"
    return f"runway {f.runway_days} of {planner.RUNWAY_FULL} days (until {until})"


def x_line(p: planner.Plan, cap) -> str:
    parts = []
    for i, (month, (spent, planned)) in enumerate(p.x.items()):
        if i == 0 or spent:
            parts.append(f"X {month}: spent {_money(spent)} + planned {_money(planned)} = "
                         f"{_money(spent + planned)} of ${cap:.2f}")
        else:
            parts.append(f"X {month}: planned {_money(planned)}")
    return "     ".join(parts)


def render_plan(p: planner.Plan, inputs, machine_tz: str) -> list[str]:
    zone = fruleset.zoneinfo.ZoneInfo(machine_tz)
    lines = [f"plan {p.now.astimezone(zone).date()} → {p.end.astimezone(zone).date()} "
             f"(machine tz {machine_tz})"]
    first = p.first_runout()
    if first:
        runs_out = f"content runs out {first[0].astimezone(zone).date()} ({first[1]})"
    elif p.active:
        runs_out = f"content lasts > {planner.RUNWAY_DAYS} days"
    else:
        runs_out = "content runs out — (no active rule)"
    lines.append(f"rules: {p.active} active, {p.drafts} draft     "
                 f"publications next 7 days: {p.publications_7d}     {runs_out}")
    lines.append(x_line(p, inputs.settings.cap))
    lines.append("folders")
    if not p.folders:
        lines.append("  (no stock folders)")
    rows = []
    for f in p.folders:
        counts = "  ".join(f"{f.counts[k]} {label}" for k, label in STATE_LABELS if f.counts.get(k))
        rows.append((f.name, f.lane or "?", counts or "empty", runway_text(f)))
    if rows:
        w = [max(len(r[i]) for r in rows) for i in range(3)]
        for name, lane, counts, runway in rows:
            lines.append(f"  {name.ljust(w[0])}  {lane.ljust(w[1])}  {counts.ljust(w[2])}   {runway}")
    lines.append("slots")
    rules = {r.id: r for r in inputs.ruleset.rules}
    shown = [s for s in p.slots if s.when > p.now]
    if not shown:
        lines.append("  (none in this window)")
    rows = []
    for s in shown:
        rule = rules[s.slot.rule]
        file = s.entry.file if s.entry else "—"
        targets = " ".join(s.targets) if s.targets else "—"
        tag = {"planned": "", "no-content": "[no content]",
               "over-budget": "[over budget: x skipped]", "draft": "[draft: rule not running]",
               "over-limit": f"[over limit: {s.reason}]"}.get(s.state, f"[{s.state}]")
        rows.append((_slot_time(s.when, rule.zone), s.slot.rule, file, targets, tag))
    if rows:
        w = [max(len(r[i]) for r in rows) for i in range(3)]
        for when, rid, file, targets, tag in rows:
            lines.append(f"  {when.ljust(w[0])}  {rid.ljust(w[1])}  {file.ljust(w[2])}   "
                         f"{targets}{'  ' + tag if tag else ''}")
    return lines


def cmd_plan(app: App) -> int:
    inputs = app.inputs()
    if app.args.rule and inputs.ruleset.get(app.args.rule) is None:
        raise Usage(f"no rule '{app.args.rule}'")
    p = planner.plan(inputs.ruleset, inputs.stock, inputs.records, inputs.journal,
                     inputs.x_spent, inputs.settings, app.clock(), days=app.args.days,
                     only_rule=app.args.rule)
    for line in render_plan(p, inputs, app.machine_tz):
        app.out(line)
    return 0


# ---------------------------------------------------------------- tick, retry, resolve

def cmd_tick(app: App) -> int:
    return app.runner(dry_run=app.args.dry_run).tick()


def cmd_retry(app: App) -> int:
    return app.runner().retry(app.args.slot)


def cmd_resolve(app: App) -> int:
    if not os.path.isdir(app.paths.state):
        raise Usage(f"slot {app.args.slot} is not in the journal")
    return app.runner().resolve(app.args.slot, bool(app.args.published))


# ---------------------------------------------------------------- status

def cmd_status(app: App) -> int:
    inputs = app.inputs()
    now = app.clock()
    p = planner.plan(inputs.ruleset, inputs.stock, inputs.records, inputs.journal,
                     inputs.x_spent, inputs.settings, now, days=60)
    hb = fjournal.read_heartbeat(app.paths.state)
    if hb:
        app.out(f"last tick: {hb.get('ts')} (due {hb.get('due')}, published {hb.get('published')}, "
                f"errors {hb.get('errors')})")
    else:
        app.out("last tick: none yet")
    rules = {r.id: r for r in inputs.ruleset.rules}
    upcoming = [s for s in p.slots if s.when > now and s.state in ("planned", "over-budget")][:5]
    app.out("next slots:" if upcoming else "next slots: none planned")
    for s in upcoming:
        app.out(f"  {_slot_time(s.when, rules[s.slot.rule].zone)}  {s.slot.rule}  "
                f"{s.entry.file}  {' '.join(s.targets)}"
                + ("  [over budget: x skipped]" if s.state == "over-budget" else ""))
    app.out(x_line(p, inputs.settings.cap))
    raw = inputs.env.get("LINKEDIN_TOKEN_EXPIRES_AT")
    try:
        left = config.parse_utc(raw) - now if raw else None
        app.out("LinkedIn token: " + ("none yet" if left is None else
                                      "expired" if left.total_seconds() <= 0 else
                                      f"{left.days} day(s) left"))
    except ValueError:
        app.out("LinkedIn token: LINKEDIN_TOKEN_EXPIRES_AT is unreadable")
    found = attention.items(inputs, p, hb, now)
    app.out(f"attention ({len(found)}):" if found else "attention: none")
    for item in found:
        app.out(f"  - {item}")
    return 0


# ---------------------------------------------------------------- rules

def _split(value: str | None) -> list | None:
    if value is None:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _save(app: App, ruleset, base_revision: str):
    fruleset.write(app.paths.rules, ruleset, base_revision)


def _edited_rule(app: App, current: dict) -> fruleset.Rule:
    a = app.args
    data = dict(current)
    for key, value in (("folder", a.folder), ("targets", _split(a.targets)),
                       ("days", _split(a.days)), ("hours", _split(a.hours)),
                       ("timezone", a.timezone)):
        if value is not None:
            data[key] = value
    problems: list[str] = []
    rule = fruleset.parse_rule(data, problems)
    if problems:
        raise Usage("; ".join(problems))
    return rule


def cmd_rule_new(app: App) -> int:
    inputs = app.inputs()
    rs = inputs.ruleset
    if rs.get(app.args.id):
        raise Usage(f"rule '{app.args.id}' exists; use factory rule set")
    rule = _edited_rule(app, {
        "id": app.args.id, "folder": app.args.id, "targets": list(config.PROFILES[DEFAULT_PROFILE]),
        "days": _split(DEFAULT_DAYS), "hours": _split(DEFAULT_HOURS),
        "timezone": app.machine_tz, "status": "draft"})
    base = rs.revision
    rs.rules.append(rule)
    _save(app, rs, base)
    app.out(f"draft rule '{rule.id}' saved: {rule.folder} → {', '.join(rule.targets)}; "
            f"{','.join(rule.days)} {','.join(rule.hours)} {rule.timezone}")
    for problem in checks.basic_problems(inputs, rule, app.clock()):
        app.out(f"  note: {problem}")
    return 0


def _get(rs, rule_id):
    rule = rs.get(rule_id)
    if rule is None:
        raise Usage(f"no rule '{rule_id}'")
    return rule


def cmd_rule_set(app: App) -> int:
    inputs = app.inputs()
    rs = inputs.ruleset
    old = _get(rs, app.args.id)
    rule = _edited_rule(app, old.to_json())
    if rule.active:
        rs.rules[rs.rules.index(old)] = rule
        problems = checks.activation_problems(inputs, rule, app.clock())
        if problems:
            app.out(f"refused: rule '{rule.id}' is active and the edit fails the checks; "
                    "rules.json is unchanged", err=True)
            for problem in problems:
                app.out(f"  - {problem}", err=True)
            return 2
    else:
        rs.rules[rs.rules.index(old)] = rule
    _save(app, rs, rs.revision)
    app.out(f"rule '{rule.id}' saved ({rule.status})")
    if not rule.active:
        for problem in checks.basic_problems(inputs, rule, app.clock()):
            app.out(f"  note: {problem}")
    return 0


def cmd_rule_start(app: App) -> int:
    inputs = app.inputs()
    rs = inputs.ruleset
    rule = _get(rs, app.args.id)
    if rule.active:
        app.out(f"rule '{rule.id}' is already active (since {rule.active_since})")
        return 0
    problems = checks.activation_problems(inputs, rule, app.clock())
    if problems:
        app.out(f"refused: rule '{rule.id}' stays a draft; rules.json is unchanged", err=True)
        for problem in problems:
            app.out(f"  - {problem}", err=True)
        return 2
    rule.status, rule.active_since = "active", config.iso_utc(app.clock())
    _save(app, rs, rs.revision)
    app.out(f"rule '{rule.id}' is active since {rule.active_since}")
    return 0


def cmd_rule_stop(app: App) -> int:
    rs = fruleset.load(app.paths.rules)
    rule = _get(rs, app.args.id)
    if not rule.active:
        app.out(f"rule '{rule.id}' is already a draft")
        return 0
    rule.status, rule.active_since = "draft", None
    _save(app, rs, rs.revision)
    app.out(f"rule '{rule.id}' is a draft again; its future slots are not published")
    return 0


# ---------------------------------------------------------------- timer

SERVICE = """[Unit]
Description=Media factory: publish due slots, collect daily stats
[Service]
Type=oneshot
WorkingDirectory={checkout}
ExecStart=/usr/bin/python3 -s -B -m factory tick
TimeoutStartSec=30min
"""
TIMER = """[Unit]
Description=Media factory tick every 5 minutes
[Timer]
OnCalendar=*:0/5
AccuracySec=30s
[Install]
WantedBy=timers.target
"""


def cmd_timer(app: App) -> int:
    out = app.out
    out("# ~/.config/systemd/user/media-factory-tick.service")
    for line in SERVICE.format(checkout=config.REPO_ROOT).splitlines():
        out(line)
    out("")
    out("# ~/.config/systemd/user/media-factory-tick.timer")
    for line in TIMER.splitlines():
        out(line)
    out("")
    out("# enable (only with the operator's consent):")
    out("systemctl --user daemon-reload")
    out("systemctl --user enable --now media-factory-tick.timer")
    return 0


COMMANDS = {"check": cmd_check, "plan": cmd_plan, "tick": cmd_tick, "status": cmd_status,
            "retry": cmd_retry, "resolve": cmd_resolve, "timer": cmd_timer}
RULE_COMMANDS = {"new": cmd_rule_new, "set": cmd_rule_set, "start": cmd_rule_start,
                 "stop": cmd_rule_stop}
