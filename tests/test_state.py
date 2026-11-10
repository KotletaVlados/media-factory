"""Local state files survive a torn last line (a crash or a full disk mid-write)."""

import os
from decimal import Decimal

from poster import state
from tests.base import PosterTestCase

FRAGMENT = '{"ts":"2026-11-09T10:15:00Z","op":"post","pri'  # no newline: a cut-off row


def _write_raw(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class TornLineTests(PosterTestCase):
    def test_ledger_reserve_after_a_torn_line_is_counted(self):
        ledger = state.Ledger(self.state_dir, self.clock)
        ledger.reserve([("post", Decimal("4.00"))], "p", Decimal("5"))
        with open(ledger.path, "a", encoding="utf-8") as fh:
            fh.write(FRAGMENT)
        ledger.reserve([("post", Decimal("0.90"))], "p", Decimal("5"))
        self.assertEqual(state.Ledger(self.state_dir, self.clock).month_total(), Decimal("4.90"))
        with self.assertRaises(state.BudgetExceeded):
            ledger.reserve([("post", Decimal("1.00"))], "p", Decimal("5"))
        with open(ledger.path, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
        self.assertEqual(lines[-1], "")  # file still ends with a newline
        self.assertIn(FRAGMENT, lines)  # the fragment sits alone on its own line

    def test_ledger_settle_after_a_torn_line_is_kept(self):
        ledger = state.Ledger(self.state_dir, self.clock)
        (rid,) = ledger.reserve([("post", Decimal("1.00"))], "p", Decimal("5"))
        with open(ledger.path, "a", encoding="utf-8") as fh:
            fh.write(FRAGMENT)
        ledger.settle(rid, "failed")
        self.assertEqual(state.Ledger(self.state_dir, self.clock).month_total(), Decimal("0"))

    def test_records_published_after_a_torn_line_is_latest(self):
        rec = state.Records(self.state_dir, self.clock)
        rec.append({"package": "p", "target": "facebook", "status": "failed"})
        with open(rec.path, "a", encoding="utf-8") as fh:
            fh.write(FRAGMENT)
        rec.append({"package": "p", "target": "facebook", "status": "published", "id": "1"})
        latest = state.Records(self.state_dir, self.clock).latest("p", "facebook")
        self.assertEqual(latest["status"], "published")

    def test_records_unknown_after_a_torn_line_is_latest(self):
        rec = state.Records(self.state_dir, self.clock)
        _write_raw(rec.path, FRAGMENT)
        rec.append({"package": "p", "target": "x", "status": "unknown"})
        self.assertEqual(rec.latest("p", "x")["status"], "unknown")

    def test_complete_file_gets_no_blank_line(self):
        rec = state.Records(self.state_dir, self.clock)
        rec.append({"package": "p", "target": "x", "status": "failed"})
        rec.append({"package": "p", "target": "x", "status": "published"})
        with open(rec.path, encoding="utf-8") as fh:
            self.assertEqual(fh.read().count("\n"), 2)

    def test_state_files_stay_private(self):
        rec = state.Records(self.state_dir, self.clock)
        rec.append({"package": "p", "target": "x", "status": "failed"})
        self.assertEqual(os.stat(rec.path).st_mode & 0o777, 0o600)
