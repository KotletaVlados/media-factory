"""Panel writes (brief §3.1): rules edits, start/stop, new rule, new stock folder.

Every rules write reuses the core: `fruleset.load`/`finputs.load` read the file, `parse_rule`
builds the edited rule, `checks.activation_problems` decides a start or an edit of an active
rule (exactly what `factory rule start` and `factory rule set` run), and `fruleset.write`
saves it against the revision the form was rendered from, so a stale form is refused under
the rules lock. A refusal raises `Refusal`; the file is then unchanged.
"""

from __future__ import annotations

import json
import os

from poster import config
from factory import checks, inputs as finputs, ruleset as fruleset, stock as fstock
from factory.panel import strings as S

MAX_TITLE = 80


class Refusal(Exception):
    """A write the panel refuses. `rule` names the row whose alert block shows `problems`
    ("new" for the new-rule form, "folder" for the new-folder form)."""

    def __init__(self, status: int, *, rule: str | None = None, problems=(), stale=False):
        super().__init__("; ".join(problems) or ("stale" if stale else "refused"))
        self.status, self.rule, self.problems, self.stale = status, rule, list(problems), stale


def _one(form: dict, name: str) -> str:
    values = form.get(name) or [""]
    return values[0]


def _toggle(values: list, value: str) -> list:
    return [v for v in values if v != value] if value in values else values + [value]


def _parse(data: dict, rid: str) -> fruleset.Rule:
    problems: list[str] = []
    rule = fruleset.parse_rule(data, problems)
    if problems:
        raise Refusal(409, rule=rid, problems=problems)
    return rule


def rules_action(kind: str, form: dict, paths, now, redactor) -> str:
    """Apply one rules action; return the redirect location. Raises Refusal,
    config.ConfigError or fruleset.RulesError (the page then shows that error)."""
    if kind == "new":
        return _new_rule(form, paths, now, redactor)
    rid, rev = _one(form, "rule"), _one(form, "rev")
    inputs = finputs.load(paths, lambda: now, redactor)
    rs = inputs.ruleset
    if rev != rs.revision:
        raise Refusal(409, rule=rid, stale=True)
    old = rs.get(rid)
    if old is None:
        raise Refusal(409, rule=rid, problems=[S.NO_RULE.format(id=rid)])
    data = old.to_json()
    if kind == "day":
        value = _one(form, "day")
        if value == "all":
            data["days"] = list(fruleset.DAYS)
        elif value in fruleset.DAYS:
            data["days"] = _toggle(list(data["days"]), value)
        else:
            raise Refusal(400, rule=rid, problems=[f"unknown day '{value[:20]}'"])
    elif kind == "hour":
        value = _one(form, "hour")
        if not fruleset.HOUR_RE.match(value):
            raise Refusal(400, rule=rid, problems=[f"unknown hour '{value[:20]}'"])
        data["hours"] = _toggle(list(data["hours"]), value)
    elif kind == "zone":
        data["timezone"] = _one(form, "zone").strip()[:64]
    elif kind == "start":
        if old.active:
            return f"/rules#rule-{rid}"
        data["status"], data["active_since"] = "active", config.iso_utc(now)
    elif kind == "stop":
        if not old.active:
            return f"/rules#rule-{rid}"
        data["status"] = "draft"
        data.pop("active_since", None)
    else:
        raise Refusal(404, rule=rid, problems=[f"unknown action '{kind}'"])
    rule = _parse(data, rid)
    rs.rules[rs.rules.index(old)] = rule
    if rule.active:
        # start, or an edit of a running rule: the same checks as `factory rule start/set`
        problems = checks.activation_problems(inputs, rule, now)
        if problems:
            raise Refusal(409, rule=rid, problems=[redactor.redact(p) for p in problems])
    try:
        fruleset.write(paths.rules, rs, rev)
    except fruleset.RevisionMismatch:
        raise Refusal(409, rule=rid, stale=True) from None
    return f"/rules#rule-{rid}"


def _new_rule(form: dict, paths, now, redactor) -> str:
    rev = _one(form, "rev")
    rs = fruleset.load(paths.rules)
    if rev != rs.revision:
        raise Refusal(409, rule="new", stale=True)
    rid = _one(form, "id").strip()
    if rs.get(rid):
        raise Refusal(409, rule="new", problems=[S.RULE_EXISTS.format(id=rid)])
    data = {"id": rid, "folder": _one(form, "folder").strip(),
            "targets": [t for t in form.get("targets", []) if t],
            "days": [d for d in form.get("days", []) if d],
            "hours": [h for h in form.get("hours", []) if h],
            "timezone": _one(form, "zone").strip()[:64], "status": "draft"}
    rule = _parse(data, "new")
    rs.rules.append(rule)
    try:
        fruleset.write(paths.rules, rs, rev)
    except fruleset.RevisionMismatch:
        raise Refusal(409, rule="new", stale=True) from None
    return f"/rules#rule-{rule.id}"


def new_folder(form: dict, paths) -> str:
    """Create `stock/<name>/` (0700) and its `folder.json` (0600, O_EXCL). Nothing else."""
    name, lane = _one(form, "name").strip(), _one(form, "lane")
    title = " ".join(_one(form, "title").split())[:MAX_TITLE] or name
    if not fstock.NAME_RE.match(name):
        raise Refusal(400, rule="folder", problems=[S.FOLDER_BAD_NAME])
    if lane not in fstock.LANES:
        raise Refusal(400, rule="folder", problems=[S.FOLDER_BAD_LANE])
    os.makedirs(paths.stock, mode=0o700, exist_ok=True)
    path = os.path.join(paths.stock, name)
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        raise Refusal(409, rule="folder", problems=[S.FOLDER_EXISTS.format(name=name)]) from None
    data = json.dumps({"schema": 1, "title": title, "lane": lane}, ensure_ascii=False, indent=2)
    fd = os.open(os.path.join(path, fstock.FOLDER_FILE), os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(data + "\n")
    return f"/files?folder={name}"
