"""Runner: one tick publishes due slots through the poster (design factory.md §9).

A tick holds `runner.lock` for its whole run. It first reconciles claims left by a tick that
died, then classifies the due slots (on time, catch-up, missed), and publishes each chosen
slot by calling the poster's own `cli.main` in this process. The journal gets `claimed`
before the poster is called, so a slot is never published automatically twice.
"""

from __future__ import annotations

import datetime as _dt
import io
from dataclasses import dataclass, field

from poster import cli as poster_cli, config, state as poster_state, xapi
from poster.redact import Redactor
from factory import __version__, inputs as finputs, journal as fjournal, planner, ruleset as fruleset
from factory import stock as fstock

ON_TIME = _dt.timedelta(minutes=15)
CATCH_UP = _dt.timedelta(hours=12)
BACK_DAYS = 7          # past slots without an entry are marked within this window
SUMMARY_LINES = 20
SUMMARY_CHARS = 2000
ACCOUNT_SIDE = ("in the env file", "LinkedIn token", "LINKEDIN_TOKEN_EXPIRES_AT", "X budget",
                "ended unknown", "env file")


@dataclass
class Outcome:
    slot: str
    status: str                       # done | refused | interrupted | missed | claimed-elsewhere
    outcome: dict = field(default_factory=dict)
    reason: str = ""
    claimed: bool = True              # False: refused by the re-check, the journal is unchanged

    @property
    def bad(self) -> bool:
        return self.status in ("refused", "interrupted") or any(
            v in ("failed", "unknown") for v in self.outcome.values())

    @property
    def published(self) -> bool:
        return any(v == "published" for v in self.outcome.values())


def poster_main(argv, *, environ, stdout, stderr, clock):
    return poster_cli.main(argv, environ=environ, stdout=stdout, stderr=stderr, clock=clock)


class Runner:
    def __init__(self, paths, environ, clock, out, *, publish=None, dry_run=False,
                 redactor: Redactor | None = None):
        self.paths, self.environ, self.clock, self.out = paths, environ, clock, out
        self.publish_fn = publish or poster_main
        self.dry_run = dry_run
        self.redactor = redactor or Redactor()
        self.journal = fjournal.Journal(paths.state, clock, read_only=dry_run)
        self.inputs = None

    # ------------------------------------------------------------ helpers

    def load(self):
        self.inputs = finputs.load(self.paths, self.clock, self.redactor)
        self.inputs.journal = self.journal.rows()
        return self.inputs

    def records(self) -> list:
        return poster_state.Records(self.paths.poster_state, self.clock).all()

    def _ledger(self):
        cls = poster_state.ReadOnlyLedger if self.dry_run else poster_state.Ledger
        return cls(self.paths.poster_state, self.clock)

    def _summary(self, text: str) -> str:
        lines = [line for line in self.redactor.redact(text).splitlines() if line.strip()]
        summary = "\n".join(lines[-SUMMARY_LINES:])
        return summary[-SUMMARY_CHARS:]

    # ------------------------------------------------------------ reconcile (§9.3)

    @staticmethod
    def rows_since_claim(claim: dict, records: list) -> dict:
        """target -> status of the latest poster record row written at or after the claim, for
        the claim's own package and targets."""
        since = config.parse_utc(claim["ts"])
        found = {}
        for row in records:
            if row.get("package") != claim.get("package"):
                continue
            try:
                ts = config.parse_utc(row.get("ts", ""))
            except (ValueError, TypeError):
                continue
            if ts >= since and row.get("target") in claim.get("targets", []):
                found[row["target"]] = row.get("status", "unknown")
        return found

    def outcome_from_record(self, claim: dict, records: list) -> dict | None:
        """Per-target status from poster record rows written at or after the claim, or None
        when a target has no such row."""
        found = self.rows_since_claim(claim, records)
        if all(t in found for t in claim.get("targets", [])):
            return {t: found[t] for t in claim["targets"]}
        return None

    def reconcile(self) -> list:
        """A claim without a terminal entry can only come from a tick that died (the runner
        lock is held for a whole tick). Write `done` from the poster record when it shows every
        target after the claim, otherwise `interrupted`. Never publish again."""
        results = []
        records = self.records()
        for log in fjournal.index(self.journal.rows()).values():
            if log.status != "claimed":
                continue
            done = log.last_with("done")
            results.append(self._settle_unknown_end(
                log.claimed, records, "the tick stopped after claiming",
                prior=(done or {}).get("outcome") if log.claimed.get("retry") else None))
        return results

    def _settle_unknown_end(self, claim: dict, records: list, why: str,
                            prior: dict | None = None) -> Outcome:
        outcome = self.outcome_from_record(claim, records)
        skipped = {t: fjournal.SKIPPED_BUDGET for t in (claim.get("skipped") or {})}
        if outcome is not None:
            # a retry claims only the retried targets: the slot's earlier outcome stays
            outcome = dict(prior or {}) | outcome | skipped
            self.journal.append({"slot": claim["slot"], "status": "done", "exit": None,
                                 "outcome": outcome, "reconciled": True})
            self.out(f"  {claim['slot']}  done (from the poster record after: {why})")
            return Outcome(claim["slot"], "done", outcome)
        reason = f"{why}; check the account, then factory resolve SLOT --published|--not-published"
        self.journal.append({"slot": claim["slot"], "status": "interrupted", "reason": reason})
        self.out(f"  {claim['slot']}  INTERRUPTED: {why}; check the account, then "
                 f"factory resolve {claim['slot']} --published|--not-published")
        return Outcome(claim["slot"], "interrupted", reason=reason)

    # ------------------------------------------------------------ publish one slot (§9.4)

    def recheck(self, entry, targets: list):
        """Read the package file again and compare it with the entry that was picked (§9.4
        step 1): approval is read at the moment of publishing, not at the start of the tick.
        Returns (fresh entry, problem or None, held). `held` is True when the file itself is
        not publishable (the refusal holds it until the file changes); False when it merely
        changed since the pick (the next slot offers it again)."""
        fresh = fstock.reload_entry(entry, self.paths.library)
        networks = {config.parse_target(t).network for t in targets}
        if fresh.package is None or fresh.problems:
            found = fresh.problems or ["the package file cannot be read"]
            return fresh, "the package is invalid: " + "; ".join(found), True
        if not fresh.approved:
            return fresh, "not approved: the file has no approved_by_operator", True
        problems = fresh.check(networks)
        if problems:
            return fresh, "; ".join(problems), True
        if fresh.fingerprint != entry.fingerprint or fresh.id != entry.id:
            return fresh, "the package file changed after it was picked", False
        return fresh, None, False

    def _call_poster(self, entry, targets: list) -> tuple:
        argv = ["--env-file", self.paths.env_file, "publish", entry.path,
                "--targets", ",".join(targets)]
        if self.dry_run:
            argv.append("--dry-run")
        buf = io.StringIO()
        try:
            code = self.publish_fn(argv, environ=self.environ, stdout=buf, stderr=buf,
                                   clock=self.clock)
        except Exception as exc:  # the poster catches its own errors; this is a last resort
            buf.write(f"error: {type(exc).__name__}: {exc}\n")
            code = None
        return code, buf.getvalue()

    @staticmethod
    def _problems(text: str) -> list:
        return [line.strip()[2:].strip() for line in text.splitlines() if line.startswith("  - ")]

    def publish_slot(self, rule, slot_key: str, entry, targets: list, *, retry=False,
                     prior: dict | None = None) -> Outcome:
        inputs = self.inputs
        targets = list(targets)
        skipped = {}
        fresh, problem, held = self.recheck(entry, targets)
        if problem:
            return self._refuse_before_publish(rule, slot_key, entry, fresh, targets, problem,
                                               held, retry)
        if "x" in targets and "x" in entry.package.variants:
            v = entry.package.variants["x"]
            est = xapi.estimate(v.text, bool(v.image_path), inputs.settings)
            try:
                self._ledger().check(est, inputs.settings.cap)
            except poster_state.BudgetExceeded as exc:
                targets.remove("x")
                skipped["x"] = "budget"
                self.out(f"  {slot_key}  x skipped (budget): {exc}")
        claim = self.journal.claim(self._claim_row(rule, slot_key, entry, targets, skipped, retry),
                                   retry=retry)
        if claim is None:
            self.out(f"  {slot_key}  already claimed elsewhere; not published")
            return Outcome(slot_key, "claimed-elsewhere")
        prior = dict(prior or {})
        skipped_out = {t: fjournal.SKIPPED_BUDGET for t in skipped}
        if not targets:
            self.journal.append({"slot": slot_key, "status": "done", "exit": 0,
                                 "outcome": prior | skipped_out})
            return Outcome(slot_key, "done", prior | skipped_out)

        n_before = 0 if self.dry_run else len(self.records())
        code, text = self._call_poster(entry, targets)
        if (not self.dry_run and code == 2 and "x" in targets
                and (problems := self._problems(text))
                and all(p.startswith("x: X budget") for p in problems)):
            # another process spent on X after our check: the poster refused the whole package
            # before any request. The free networks still publish on time (§17 item 1 (a)).
            targets.remove("x")
            skipped["x"] = "budget"
            skipped_out = {t: fjournal.SKIPPED_BUDGET for t in skipped}
            self.out(f"  {slot_key}  x skipped (budget): {problems[0][3:]}")
            if not targets:
                self.journal.append({"slot": slot_key, "status": "done", "exit": 2,
                                     "outcome": prior | skipped_out})
                return Outcome(slot_key, "done", prior | skipped_out)
            claim = self.journal.append(dict(
                self._claim_row(rule, slot_key, entry, targets, skipped, retry),
                status="claimed", narrowed=True))
            code, text = self._call_poster(entry, targets)
        summary = self._summary(text)
        if self.dry_run:
            self.out(f"  {slot_key}  would publish {entry.folder}/{entry.file} to "
                     f"{', '.join(targets)} (poster dry run exit {code}):")
            for line in self.redactor.redact(text).splitlines():
                self.out("    | " + line)
            return Outcome(slot_key, "done", {t: "dry-run" for t in targets} | skipped_out)

        if code in (0, 1):
            outcome = self.attempt_outcome(entry, targets, self.records(), n_before)
            outcome.update(skipped_out)
            outcome = prior | outcome
            self.journal.append({"slot": slot_key, "status": "done", "exit": code,
                                 "outcome": outcome, "summary": summary})
            self.out(f"  {slot_key}  {entry.folder}/{entry.file}  "
                     + "  ".join(f"{t} {s}" for t, s in outcome.items()))
            return Outcome(slot_key, "done", outcome)
        if code == 2:
            problems = self._problems(text)
            errors = [line.strip() for line in text.splitlines() if line.startswith("error:")]
            reason = "; ".join(problems or errors) or "the poster refused the package"
            reason = self.redactor.redact(reason)[:500]
            held = ("the package is invalid" in text
                    or any(not any(m in p for m in ACCOUNT_SIDE) for p in problems))
            if retry:
                # the slot stays retryable: its `done` entry is written again as it was, so the
                # earlier outcome, `retry` and the attention items all keep working
                self.journal.append({"slot": slot_key, "status": "done", "exit": 2,
                                     "outcome": prior, "retry_refused": reason,
                                     "summary": summary})
                self.out(f"  {slot_key}  retry REFUSED: {reason}")
                return Outcome(slot_key, "refused", prior, reason=reason)
            self.journal.append({"slot": slot_key, "status": "refused", "exit": 2,
                                 "reason": reason, "held": held, "summary": summary})
            self.out(f"  {slot_key}  REFUSED{' (package held until its file changes)' if held else ''}"
                     f": {reason}")
            return Outcome(slot_key, "refused", reason=reason)
        return self._settle_unknown_end(claim, self.records(),
                                        f"the poster ended without an exit code ({summary[-200:]})",
                                        prior=prior if retry else None)

    @staticmethod
    def attempt_outcome(entry, targets: list, records: list, n_before: int) -> dict:
        """Per-target result of one poster call. Only record rows appended after the call began
        (`records[n_before:]`) are this attempt's result. A target without such a row: a row
        from before that says `published` is `already`; otherwise it is `unknown`: a poster that
        could not write its row leaves the account to be checked, and an older `failed` row
        must not stand in for this attempt (it would invite a second post, §8.2)."""
        def latest(rows, target):
            found = None
            for row in rows:
                if row.get("package") == entry.id and row.get("target") == target:
                    found = row
            return found

        outcome = {}
        for t in targets:
            new = latest(records[n_before:], t)
            if new is not None:
                outcome[t] = new.get("status", "unknown")
                continue
            old = latest(records[:n_before], t)
            if old is not None and old.get("status") == "published":
                outcome[t] = "already"
            else:
                outcome[t] = "unknown"
        return outcome

    @staticmethod
    def _claim_row(rule, slot_key, entry, targets, skipped, retry) -> dict:
        return {"slot": slot_key, "rule": rule.id if rule else None, "folder": entry.folder,
                "file": entry.file, "package": entry.id, "fp": list(entry.fingerprint),
                "targets": list(targets), **({"skipped": dict(skipped)} if skipped else {}),
                **({"retry": True} if retry else {})}

    def _refuse_before_publish(self, rule, slot_key, entry, fresh, targets, problem, held,
                               retry) -> Outcome:
        """The package no longer passes at the moment of publishing: the poster is not called.
        A tick journals claimed -> refused (held while the file stays as it is); a retry leaves
        the slot's `done` entry as it was."""
        reason = self.redactor.redact(problem)[:500]
        if retry:
            self.out(f"error: {entry.folder}/{entry.file} cannot be retried: {reason}")
            return Outcome(slot_key, "refused", reason=reason, claimed=False)
        # the claim carries the fingerprint of the file as it is now, so a later edit releases it
        row = self._claim_row(rule, slot_key, entry, targets, {}, False)
        if held:
            row["fp"] = list(fresh.fingerprint)
        claim = self.journal.claim(row)
        if claim is None:
            self.out(f"  {slot_key}  already claimed elsewhere; not published")
            return Outcome(slot_key, "claimed-elsewhere")
        self.journal.append({"slot": slot_key, "status": "refused", "exit": None,
                             "reason": reason, "held": held})
        self.out(f"  {slot_key}  REFUSED{' (package held until its file changes)' if held else ''}"
                 f": {reason}")
        return Outcome(slot_key, "refused", reason=reason)

    # ------------------------------------------------------------ tick (§9.1, §9.2)

    def tick(self) -> int:
        if self.dry_run:
            return self._tick()
        with fjournal.runner_lock(self.paths.state) as held:
            if not held:
                self.out("tick already running")
                return 0
            return self._tick()

    def _heartbeat(self, due: int, published: int, errors: int):
        if self.dry_run:
            return
        fjournal.write_heartbeat(self.paths.state, {
            "ts": config.iso_utc(self.clock()), "version": __version__,
            "due": due, "published": published, "errors": errors})

    def _tick(self) -> int:
        now = self.clock()
        try:
            inputs = self.load()
        except (config.ConfigError, fruleset.RulesError) as exc:
            self.out(f"error: {exc}")
            self._heartbeat(0, 0, 1)
            return 2
        header = f"tick {config.iso_utc(now)}" + ("  DRY RUN (nothing is published or written)"
                                                  if self.dry_run else "")
        self.out(header)
        results = self.reconcile()
        inputs.journal = self.journal.rows()
        logs = fjournal.index(inputs.journal)
        records = self.records()
        p = planner.plan(inputs.ruleset, inputs.stock, records, inputs.journal, inputs.x_spent,
                         inputs.settings, now, days=0, back_days=BACK_DAYS, runway=False)
        due = [s for s in p.slots if s.state == "due"]
        rules = {r.id: r for r in inputs.ruleset.rules}

        on_time = sorted((s for s in due if now - s.when <= ON_TIME), key=lambda s: (s.when, s.slot.rule))
        late = [s for s in due if ON_TIME < now - s.when <= CATCH_UP]
        missed = [(s, "off") for s in due if now - s.when > CATCH_UP]
        latest_late: dict = {}
        for s in late:
            if s.slot.rule not in latest_late or s.when > latest_late[s.slot.rule].when:
                latest_late[s.slot.rule] = s
        candidates = sorted(latest_late.values(), key=lambda s: (s.when, s.slot.rule), reverse=True)
        missed += [(s, "superseded") for s in late if s not in candidates]

        states = planner.package_states(inputs.ruleset, inputs.stock, records, logs)
        taken = planner.Taken(records, logs)
        limits = planner.LimitTracker(inputs.ruleset, planner.record_publications(records))
        caught_up: set = set()
        for s, catch_up in [(s, False) for s in on_time] + [(s, True) for s in candidates]:
            rule = rules[s.slot.rule]
            entry = planner.pick(rule, inputs.stock, states, taken)
            if entry is None:
                missed.append((s, "no-content"))
                continue
            targets = planner.variant_targets(rule, entry)
            networks = {config.parse_target(t).network for t in targets}
            if catch_up and networks & caught_up:
                missed.append((s, "superseded"))
                continue
            broken = limits.violation(networks, now, rule.zone)
            if broken:
                missed.append((s, broken[0], broken[1]))
                continue
            result = self.publish_slot(rule, s.key, entry, targets)
            results.append(result)
            if result.status != "claimed-elsewhere":
                sent = [t for t in targets if result.outcome.get(t) != fjournal.SKIPPED_BUDGET]
                taken.add(entry.id, sent)
                limits.add({config.parse_target(t).network for t in sent}, now)
                if catch_up:
                    caught_up |= networks

        for item in sorted(missed, key=lambda m: (m[0].when, m[0].slot.rule)):
            s, reason = item[0], item[1]
            detail = item[2] if len(item) > 2 else ""
            row = {"slot": s.key, "status": "missed", "reason": reason}
            if detail:
                row["detail"] = detail
            self.journal.append(row)
            self.out(f"  {s.key}  {'would be ' if self.dry_run else ''}missed ({reason}"
                     + (f": {detail}" if detail else "") + ")")
        if not due and not results:
            self.out("  nothing due")
        bad = [r for r in results if r.bad]
        published = sum(1 for r in results if r.published)
        self._heartbeat(len(due), published, len(bad))
        return 1 if bad else 0

    # ------------------------------------------------------------ retry and resolve

    def retry(self, slot_key: str) -> int:
        with fjournal.runner_lock(self.paths.state) as held:
            if not held:
                self.out("error: a tick is running; try again in a minute")
                return 2
            inputs = self.load()
            log = fjournal.index(inputs.journal).get(slot_key)
            if log is None:
                self.out(f"error: no journal entry for slot {slot_key}")
                return 2
            if log.status != "done":
                self.out(f"error: slot {slot_key} is {log.status}; retry takes a done slot")
                return 2
            outcome = log.last.get("outcome") or {}
            unknown = [t for t, s in outcome.items() if s == "unknown"]
            if unknown:
                self.out(f"error: {', '.join(unknown)} ended unknown; look at the account, then "
                         f"python3 -m poster publish PACKAGE --targets ... --force-target "
                         f"{unknown[0]}")
                return 2
            failed = [t for t, s in outcome.items() if s == "failed"]
            if not failed:
                self.out(f"slot {slot_key}: no failed target; nothing to retry")
                return 0
            claim = log.claimed
            entry = find_entry(inputs.stock, claim.get("folder"), claim.get("file"))
            if entry is None or entry.package is None:
                self.out(f"error: package {claim.get('folder')}/{claim.get('file')} is missing "
                         "or unreadable")
                return 2
            rule = inputs.ruleset.get(claim.get("rule") or "")
            # only the targets that failed: the poster skips a target only when its latest row
            # is `published`, so a post the operator deleted would go out again
            wanted = [t for t in claim.get("targets") or [] if t in failed] or failed
            # a target that the record or another slot's attempt holds as taken is not sent
            # again, whatever this slot's own outcome says (§9.3)
            logs = fjournal.index(inputs.journal)
            sent, blocked = [], []
            for t in wanted:
                holder = planner.taken_elsewhere(inputs.records, logs, entry.id, t, slot_key)
                if holder:
                    blocked.append(t)
                    self.out(f"error: {t} is held as taken by {holder}; it is not sent again "
                             "(see factory status for that slot)")
                else:
                    sent.append(t)
            if not sent:
                return 2
            self.out(f"retry {slot_key}: {', '.join(sent)}")
            result = self.publish_slot(rule, slot_key, entry, sent, retry=True, prior=outcome)
            if result.status == "refused" and not result.claimed:
                return 2
            return 1 if result.bad or blocked else 0

    def resolve(self, slot_key: str, published: bool) -> int:
        log = fjournal.index(self.journal.rows()).get(slot_key)
        if log is None or log.status != "interrupted":
            state = log.status if log else "not in the journal"
            self.out(f"error: slot {slot_key} is {state}; resolve takes an interrupted slot")
            return 2
        if not published:
            partial = self._partial_outcome(log)
            if partial is not None:
                # part of the package already went out (or this was a retry of a done slot):
                # the slot ends `done` with what is known, so the rest stays retryable and
                # the sent targets stay taken, instead of being released and lost
                self.journal.append({"slot": slot_key, "status": "done", "exit": None,
                                     "outcome": partial, "resolved": True})
                sent = [t for t, v in partial.items() if v in fjournal.SENT_OUTCOMES]
                owed = [t for t, v in partial.items() if v == "failed"]
                self.out(f"{slot_key}: resolved as not published, but {', '.join(sent) or 'nothing'} "
                         f"already went out and stays taken"
                         + (f"; {', '.join(owed)} not sent: factory retry {slot_key}" if owed else ""))
                return 0
        self.journal.append({"slot": slot_key, "status": "resolved", "published": published})
        what = ("the package stays taken for those targets" if published
                else "the package is released to the next slot")
        self.out(f"{slot_key}: resolved as {'published' if published else 'not published'}; {what}")
        return 0

    def _partial_outcome(self, log) -> dict | None:
        """The slot's outcome when its interrupted claim cannot simply be released: the poster
        record shows a target of the claim sent after the claim, or the claim is a retry (the
        slot had a `done` outcome before it). None when nothing went out."""
        claim = log.claimed
        found = self.rows_since_claim(claim, self.records())
        retry = bool(claim.get("retry"))
        if not retry and not any(v in planner.RECORD_TAKEN for v in found.values()):
            return None
        done_before = log.last_with("done")
        prior = dict((done_before or {}).get("outcome") or {}) if retry else {}
        outcome = {t: found.get(t, "failed") for t in claim.get("targets") or []}
        outcome.update({t: fjournal.SKIPPED_BUDGET for t in claim.get("skipped") or {}})
        return prior | outcome


def find_entry(stock: fstock.Stock, folder: str, file: str):
    f = stock.folders.get(folder)
    return next((e for e in f.entries if e.file == file), None) if f else None
