"""Attention items (§9.5): computed on demand from the journal, record, plan and heartbeat.

Nothing is stored; `factory status` prints them and the panel's bell (lane L3) counts them.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from poster import config
from factory import journal as fjournal, planner

REFUSED_DAYS = 7
RUNOUT_DAYS = 14
TIMER_SILENT = _dt.timedelta(minutes=30)
X_WARN_SHARE = Decimal("0.8")


def _parse(ts: str):
    try:
        return config.parse_utc(ts)
    except (ValueError, TypeError):
        return _dt.datetime.max.replace(tzinfo=_dt.timezone.utc)


def _recent(row: dict, now: _dt.datetime) -> bool:
    try:
        return now - config.parse_utc(row.get("ts", "")) <= _dt.timedelta(days=REFUSED_DAYS)
    except (ValueError, TypeError):
        return False


def items(inputs, plan, heartbeat: dict | None, now: _dt.datetime) -> list[str]:
    out: list[str] = []
    logs = fjournal.index(inputs.journal)
    latest = planner.record_latest(inputs.records)
    month = planner.month_key(now)
    budget_skips = 0
    for key, log in logs.items():
        claim = log.claimed or {}
        status = log.status
        if status == "done":
            outcome = log.last.get("outcome") or {}
            for target, result in sorted(outcome.items()):
                row = latest.get((claim.get("package"), target)) or {}
                now_status = row.get("status")
                if result == "unknown" and row and claim.get("ts") and \
                        planner.row_older_than(row, _parse(claim["ts"])):
                    now_status = None     # an older row is not this attempt's answer
                if result == "failed" and now_status == "failed":
                    out.append(f"slot {key}: {target} failed; fix the cause, then "
                               f"factory retry {key}")
                elif result == "unknown" and now_status in ("unknown", None):
                    out.append(f"slot {key}: {target} ended unknown; check the account, then "
                               f"python3 -m poster publish ... --force-target {target}")
                elif result == fjournal.SKIPPED_BUDGET and key.split("@", 1)[-1][:7] == month:
                    budget_skips += 1
            if log.last.get("retry_refused") and _recent(log.last, now):
                out.append(f"slot {key}: the last retry was refused: "
                           f"{log.last['retry_refused']}; fix the cause, then factory retry {key}")
        elif status == "interrupted":
            out.append(f"slot {key}: interrupted; check the account, then "
                       f"factory resolve {key} --published|--not-published")
        elif status == "refused":
            if _recent(log.last, now):
                out.append(f"slot {key}: refused: {log.last.get('reason', '')}")
    if budget_skips:
        out.append(f"X skipped on {budget_skips} slot(s) this month (budget); ask the operator "
                   "whether to raise X_MONTHLY_CAP_USD")
    cap = inputs.settings.cap
    spent, planned = plan.x.get(month, (0, 0))
    if cap > 0 and spent + planned > cap * X_WARN_SHARE:
        out.append(f"X {month}: ${spent:.3f} spent + ${planned:.3f} planned is over "
                   f"{int(X_WARN_SHARE * 100)} % of ${cap:.2f}")
    first = plan.first_runout()
    if first and first[0] - now <= _dt.timedelta(days=RUNOUT_DAYS):
        out.append(f"content runs out {first[0].date().isoformat()} ({first[1]}); "
                   "approve the next batch")
    for entry in inputs.stock.entries():
        st = plan.states.get((entry.folder, entry.file))
        if st and st.state in ("invalid", "not-approved", "held"):
            label = {"invalid": f"needs fixing: {st.reason}", "not-approved": "not approved",
                     "held": f"held: {st.reason}"}[st.state]
            out.append(f"{entry.folder}/{entry.file}: {label}")
    active = [r for r in inputs.ruleset.rules if r.active]
    if any("linkedin" in r.targets for r in active):
        raw = inputs.env.get("LINKEDIN_TOKEN_EXPIRES_AT")
        try:
            left = config.parse_utc(raw) - now if raw else None
        except ValueError:
            left = None
        if left is None:
            out.append("LinkedIn token: missing or unreadable; run python3 -m poster login linkedin")
        elif left.total_seconds() <= 0:
            out.append("LinkedIn token expired; run python3 -m poster login linkedin")
        elif left < _dt.timedelta(days=7):
            out.append(f"LinkedIn token expires in {left.days} day(s); "
                       "run python3 -m poster login linkedin")
    if active:
        ts = None
        if heartbeat:
            try:
                ts = config.parse_utc(str(heartbeat.get("ts", "")))
            except ValueError:
                ts = None
        if ts is None:
            out.append("the timer is not running: no tick yet (see factory timer --print)")
        elif now - ts > TIMER_SILENT:
            minutes = int((now - ts).total_seconds() // 60)
            out.append(f"the timer is not running: last tick {minutes} min ago")
    return out
