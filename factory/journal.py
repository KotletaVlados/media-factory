"""Runner journal `runs.jsonl`, `heartbeat.json` and the runner lock (design factory.md §9.1, §9.3).

The journal is append-only JSON Lines written with the poster's helpers under `runs.lock`;
those helpers end a torn last line before appending. One slot's history is the rows with its
key, in file order:

    claimed  -> done | refused | interrupted          (a publish attempt; `retry` claims again)
    missed                                            (never published: off, superseded, gap,
                                                       limit, no-content)
    interrupted -> resolved {"published": true|false} (the operator checked the account)
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
from dataclasses import dataclass, field

from poster import state as poster_state
from poster.config import iso_utc, parse_utc

RUNS = "runs.jsonl"
RUNS_LOCK = "runs.lock"
HEARTBEAT = "heartbeat.json"
RUNNER_LOCK = "runner.lock"
TERMINAL = ("done", "refused", "missed", "interrupted")
MISSED_REASONS = ("off", "superseded", "gap", "limit", "no-content")
SKIPPED_BUDGET = "skipped (budget)"


@dataclass
class SlotLog:
    slot: str
    rows: list = field(default_factory=list)

    @property
    def last(self) -> dict:
        return self.rows[-1]

    @property
    def status(self) -> str:
        return self.last.get("status", "")

    @property
    def claimed(self) -> dict | None:
        """The latest claim (a retry claims again with the targets it sends)."""
        for row in reversed(self.rows):
            if row.get("status") == "claimed":
                return row
        return None

    @property
    def first_claim(self) -> dict | None:
        for row in self.rows:
            if row.get("status") == "claimed":
                return row
        return None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL or self.status == "resolved"

    @property
    def package(self) -> str | None:
        claim = self.first_claim
        return claim.get("package") if claim else None

    def last_with(self, status: str) -> dict | None:
        for row in reversed(self.rows):
            if row.get("status") == status:
                return row
        return None


def index(rows: list[dict]) -> dict:
    """slot key -> SlotLog, in first-appearance order. Rows without a slot are ignored."""
    logs: dict = {}
    for row in rows:
        slot = row.get("slot")
        if not isinstance(slot, str) or not isinstance(row.get("status"), str):
            continue
        logs.setdefault(slot, SlotLog(slot)).rows.append(row)
    return logs


def taken_pairs(logs: dict) -> set:
    """(package, target) pairs the journal holds as taken (§8.2): a claim without a terminal
    entry, an unresolved `interrupted`, or one resolved as published."""
    taken = set()
    for log in logs.values():
        claim = log.claimed
        if not claim:
            continue
        status = log.status
        if status == "claimed" or status == "interrupted" or (
                status == "resolved" and log.last.get("published") is True):
            for target in claim.get("targets") or []:
                taken.add((claim.get("package"), target))
    return taken


SENT_OUTCOMES = ("published", "already", "unknown")


def done_pairs(logs: dict) -> dict:
    """(package, target) -> (outcome, claim time) for the targets a `done` slot journals as
    sent: published, already published, or ended unknown. The claim time lets the planner tell
    a poster row written by that attempt from an older one (see planner.journal_sent)."""
    out: dict = {}
    for log in logs.values():
        claim = log.claimed
        if not claim or log.status != "done":
            continue
        try:
            since = parse_utc(claim.get("ts", ""))
        except (ValueError, TypeError):
            since = None
        for target, result in (log.last.get("outcome") or {}).items():
            if result in SENT_OUTCOMES:
                out[(claim.get("package"), target)] = (result, since)
    return out


class Journal:
    def __init__(self, state_dir: str, clock, read_only: bool = False):
        self.state_dir, self.clock, self.read_only = state_dir, clock, read_only
        self.path = os.path.join(state_dir, RUNS)
        self.pending: list[dict] = []     # dry-run: rows kept in memory only

    def rows(self) -> list[dict]:
        return poster_state.read_jsonl(self.path) + self.pending

    def logs(self) -> dict:
        return index(self.rows())

    def _row(self, row: dict) -> dict:
        out = {"ts": iso_utc(self.clock())}
        out.update(row)
        return out

    def append(self, row: dict) -> dict:
        out = self._row(row)
        if self.read_only:
            self.pending.append(out)
            return out
        with poster_state.locked(self.state_dir, RUNS_LOCK):
            poster_state.append_jsonl(self.path, [out])
        return out

    def claim(self, row: dict, *, retry: bool = False) -> dict | None:
        """Append `claimed` unless the slot already has an entry (a retry needs the slot to
        end `done`). The check and the append happen under one lock, so two writers can never
        both claim a slot. Returns the row, or None when the slot was not free."""
        row = dict(row, status="claimed")
        if self.read_only:
            log = self.logs().get(row["slot"])
            if (log is not None) != retry or (retry and log.status != "done"):
                return None
            out = self._row(row)
            self.pending.append(out)
            return out
        with poster_state.locked(self.state_dir, RUNS_LOCK):
            log = index(poster_state.read_jsonl(self.path)).get(row["slot"])
            if (log is not None) != retry or (retry and log.status != "done"):
                return None
            out = self._row(row)
            poster_state.append_jsonl(self.path, [out])
        return out


# ---------------------------------------------------------------- heartbeat and lock

def read_heartbeat(state_dir: str) -> dict | None:
    try:
        with open(os.path.join(state_dir, HEARTBEAT), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_heartbeat(state_dir: str, data: dict) -> None:
    os.makedirs(state_dir, mode=0o700, exist_ok=True)
    path = os.path.join(state_dir, HEARTBEAT)
    tmp = f"{path}.tmp-{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def runner_lock(state_dir: str):
    """Non-blocking exclusive lock for one tick (or retry). Yields True when held."""
    os.makedirs(state_dir, mode=0o700, exist_ok=True)
    os.chmod(state_dir, 0o700)
    fd = os.open(os.path.join(state_dir, RUNNER_LOCK), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
