"""Local state outside every checkout: post record and X spending ledger (design §11).

Both are append-only JSON Lines guarded by an exclusive flock. Dry-run uses the read-only
variants, which never create the folder or write a file.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import uuid
from decimal import Decimal

from poster.config import iso_utc

RECORD_FILE = "posts.jsonl"
LEDGER_FILE = "x-ledger.jsonl"
LEDGER_LOCK = "x-ledger.lock"
RECORD_LOCK = "posts.lock"


def _ensure_dir(path: str) -> None:
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def _read_jsonl(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            rows = []
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue  # a torn last line from a crash is skipped, not fatal
                if isinstance(row, dict):
                    rows.append(row)
            return rows
    except FileNotFoundError:
        return []


def _append_jsonl(path: str, rows: list[dict]) -> None:
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a+", encoding="utf-8") as fh:
        # A crash or a full disk can leave a last line without its newline. End it first, so
        # the new rows start on their own line instead of being glued to the fragment (the
        # reader would skip the glued line and lose the new row too). Callers hold the lock.
        if os.fstat(fd).st_size and os.pread(fd, 1, os.fstat(fd).st_size - 1) != b"\n":
            fh.write("\n")
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(path, 0o600)


@contextlib.contextmanager
def _locked(state_dir: str, lock_name: str):
    _ensure_dir(state_dir)
    fd = os.open(os.path.join(state_dir, lock_name), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# ---------------------------------------------------------------- post record

class Records:
    def __init__(self, state_dir: str, clock):
        self.state_dir = state_dir
        self.path = os.path.join(state_dir, RECORD_FILE)
        self.clock = clock

    def all(self) -> list[dict]:
        return _read_jsonl(self.path)

    def latest(self, package: str, target: str) -> dict | None:
        found = None
        for row in self.all():
            if row.get("package") == package and row.get("target") == target:
                found = row
        return found

    def append(self, event: dict) -> dict:
        row = {"ts": iso_utc(self.clock())}
        row.update({k: v for k, v in event.items() if v not in (None, {}, [])})
        with _locked(self.state_dir, RECORD_LOCK):
            _append_jsonl(self.path, [row])
        return row


class ReadOnlyRecords(Records):
    def append(self, event: dict) -> dict:
        row = {"ts": iso_utc(self.clock())}
        row.update(event)
        return row


# ---------------------------------------------------------------- X ledger

class BudgetExceeded(Exception):
    def __init__(self, estimate: Decimal, month_total: Decimal, cap: Decimal, month: str):
        super().__init__(
            f"X budget: this post would cost ${estimate:.3f}, the {month} total is "
            f"${month_total:.3f}, the cap is ${cap:.2f}. Ask the operator; to publish without X, "
            "drop the x variant or use --targets")
        self.estimate, self.month_total, self.cap, self.month = estimate, month_total, cap, month


class Ledger:
    def __init__(self, state_dir: str, clock):
        self.state_dir = state_dir
        self.path = os.path.join(state_dir, LEDGER_FILE)
        self.clock = clock
        self._pending: list[dict] = []

    def month(self) -> str:
        return self.clock().strftime("%Y-%m")

    def _rows(self) -> list[dict]:
        return _read_jsonl(self.path) + self._pending

    def month_total(self, month: str | None = None) -> Decimal:
        month = month or self.month()
        reservations: dict[str, dict] = {}
        latest: dict[str, str] = {}
        for row in self._rows():
            rid = row.get("rid")
            if not rid:
                continue
            if "price" in row:
                reservations[rid] = row
            latest[rid] = row.get("status", "")
        total = Decimal("0")
        for rid, row in reservations.items():
            if row.get("month") == month and latest.get(rid) in ("reserved", "ok"):
                try:
                    total += Decimal(str(row["price"]))
                except ArithmeticError:
                    continue
        return total

    def check(self, estimate: Decimal, cap: Decimal) -> Decimal:
        """Raise BudgetExceeded when the month total plus estimate exceeds the cap."""
        with _locked_if_exists(self):
            total = self.month_total()
        if total + estimate > cap:
            raise BudgetExceeded(estimate, total, cap, self.month())
        return total

    def reserve(self, items: list[tuple[str, Decimal]], package: str, cap: Decimal) -> list[str]:
        """Atomically check the cap and append one `reserved` row per request, before any
        request is sent. Returns the reservation ids."""
        with _locked(self.state_dir, LEDGER_LOCK):
            total = self.month_total()
            estimate = sum((p for _, p in items), Decimal("0"))
            if total + estimate > cap:
                raise BudgetExceeded(estimate, total, cap, self.month())
            rows, rids = [], []
            for op, price in items:
                rid = str(uuid.uuid4())
                rids.append(rid)
                rows.append({"ts": iso_utc(self.clock()), "month": self.month(), "rid": rid,
                             "op": op, "price": str(price), "package": package,
                             "status": "reserved"})
            self._write(rows)
        return rids

    def settle(self, rid: str, status: str, x_id: str | None = None, note: str | None = None):
        row = {"ts": iso_utc(self.clock()), "month": self.month(), "rid": rid, "status": status}
        if x_id:
            row["x_id"] = x_id
        if note:
            row["note"] = note
        with _locked(self.state_dir, LEDGER_LOCK):
            self._write([row])

    def _write(self, rows: list[dict]) -> None:
        _append_jsonl(self.path, rows)


class ReadOnlyLedger(Ledger):
    """Dry-run ledger: reads the real file, keeps its own reservations in memory."""

    def reserve(self, items, package, cap):
        total = self.month_total()
        estimate = sum((p for _, p in items), Decimal("0"))
        if total + estimate > cap:
            raise BudgetExceeded(estimate, total, cap, self.month())
        rids = []
        for op, price in items:
            rid = "dry-run-" + str(uuid.uuid4())
            rids.append(rid)
            self._pending.append({"month": self.month(), "rid": rid, "op": op,
                                  "price": str(price), "status": "reserved"})
        return rids

    def settle(self, rid, status, x_id=None, note=None):
        self._pending.append({"rid": rid, "status": status})


@contextlib.contextmanager
def _locked_if_exists(ledger: Ledger):
    """Take the lock only when the state folder exists, so a read never creates it."""
    if os.path.isdir(ledger.state_dir) and not isinstance(ledger, ReadOnlyLedger):
        with _locked(ledger.state_dir, LEDGER_LOCK):
            yield
    else:
        yield
