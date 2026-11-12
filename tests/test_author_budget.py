"""Reserve/settle, restart, month and concurrent cap accounting, without a transport."""
import datetime as dt
import json
import os
import subprocess
import sys
import threading
from decimal import Decimal as D

from factory.authoring import budget, prices, prompts, profile
from factory.authoring.common import Refusal
from tests.base import PosterTestCase


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# One panel process. Its read-and-sum step is slowed after it has read the ledger, so that
# without the cross-process file lock both processes would read 0 and both would append.
RESERVER = """
import datetime as dt, os, sys, time
from decimal import Decimal as D
sys.path.insert(0, sys.argv[1])
from factory.authoring import budget
from factory.authoring.common import Refusal
state_dir, ready, go = sys.argv[2:5]
now = dt.datetime(2026, 11, 12, 12, 0, tzinfo=dt.timezone.utc)
ledger = budget.Ledger(state_dir, lambda: now)
read_ledger = ledger._sum
def slow_sum():
    total = read_ledger()
    time.sleep(0.4)
    return total
ledger._sum = slow_sum
open(ready, "w").close()
deadline = time.time() + 20
while not os.path.exists(go):
    if time.time() > deadline:
        sys.exit(3)
    time.sleep(0.001)
try:
    ledger.reserve("expand", D(".06"), D(".10"), "draft")
    print("ok")
except Refusal:
    print("refused")
"""


class BudgetTest(PosterTestCase):
    def setUp(self):
        super().setUp()
        self.ledger = budget.Ledger(self.state_dir, self.clock)

    def test_settlement_and_restart_keep_unknowns_and_orphan_reservations(self):
        for status, amount in (("ok", D(".001")), ("failed", D(0)), ("unknown", D(".02")), ("reserved", D(".02"))):
            rid = self.ledger.reserve("topics", D(".02"), D(10), "draft")
            if status != "reserved":
                self.ledger.settle(rid, status, actual=D(".001") if status == "ok" else None)
        self.assertEqual(self.ledger.month_total(), D(".041"))
        self.assertEqual(budget.Ledger(self.state_dir, self.clock).month_total(), D(".041"))
        self.clock.now += dt.timedelta(days=35)
        self.assertEqual(self.ledger.month_total(), 0)

    def test_reservation_month_wins_when_settled_after_midnight(self):
        self.clock.now = dt.datetime(2026, 12, 31, 23, 59, tzinfo=dt.timezone.utc)
        rid = self.ledger.reserve("expand", D(".05"), D(10), "draft")
        self.clock.now += dt.timedelta(minutes=2)
        self.ledger.settle(rid, "ok", actual=D(".01"))
        self.assertEqual(self.ledger.month_total(), 0)
        self.clock.now -= dt.timedelta(minutes=2)
        self.assertEqual(self.ledger.month_total(), D(".01"))

    def test_two_threads_cannot_both_reserve(self):
        gate = threading.Barrier(2)
        outcomes = []
        def reserve():
            ledger = budget.Ledger(self.state_dir, self.clock)
            gate.wait()
            try:
                ledger.reserve("expand", D(".06"), D(".10"), "draft")
                outcomes.append("ok")
            except Refusal:
                outcomes.append("refused")
        threads = [threading.Thread(target=reserve) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(5)
        self.assertEqual(sorted(outcomes), ["ok", "refused"])
        self.assertEqual(self.ledger.month_total(), D(".06"))

    def test_two_processes_sharing_the_state_folder_cannot_both_reserve(self):
        """A second panel on another port, or a restart overlapping a running panel, shares only
        the state folder: the file lock must hold across processes, not just threads."""
        os.makedirs(self.state_dir, exist_ok=True)
        go = os.path.join(self.state_dir, "go")
        ready = [os.path.join(self.state_dir, f"ready-{n}") for n in (1, 2)]
        procs = [subprocess.Popen([sys.executable, "-I", "-B", "-c", RESERVER, REPO, self.state_dir, r, go],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for r in ready]
        try:
            deadline = 20
            while deadline > 0 and not all(os.path.exists(r) for r in ready):
                self.assertTrue(all(p.poll() is None for p in procs), "a reserving process died early")
                threading.Event().wait(0.01)
                deadline -= 0.01
            open(go, "w").close()     # both processes leave the barrier together
            results = [p.communicate(timeout=30) for p in procs]
        finally:
            for p in procs:
                if p.poll() is None:
                    p.kill()
                    p.communicate()
        self.assertEqual([p.returncode for p in procs], [0, 0], results)
        self.assertEqual(sorted(out.strip() for out, _ in results), ["ok", "refused"], results)
        with open(self.ledger.path, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual([r["status"] for r in rows], ["reserved"])
        self.assertEqual(self.ledger.month_total(), D(".06"))

    def test_bad_caps_refuse_and_valid_caps_are_finite(self):
        for v in ("NaN", "Infinity", "-1", "wrong", "9" * 20000, None, [], "sNaN"):
            with self.assertRaises(Refusal): budget.cap({"AI_MONTHLY_CAP_USD": v})
        self.assertEqual(budget.cap({}), D(10))
        self.assertEqual(budget.cap({"AI_MONTHLY_CAP_USD": "0"}), 0)

    def test_button_bounds_cover_maximum_fields_both_price_periods(self):
        author = {"audience": {}}
        for name, _, limit, _ in profile.FIELDS:
            if name.startswith("audience."): author["audience"][name.split(".")[1]] = "\U00010000" * limit
            else: author[name] = "\U00010000" * limit
        draft = {"topic": "\U00010000" * 2000, "variants": {n: {"text": "\U00010000" * 5000} for n in prompts.RULES}}
        for year in (2026, 2027):
            self.clock.now = dt.datetime(year, 1 if year == 2027 else 12, 1, tzinfo=dt.timezone.utc)
            for op in prompts.OUTPUT:
                for n in prompts.RULES:
                    prompt = prompts.build(op, author, draft, n, "\U00010000" * 200)
                    reserved = budget.bound(op, prompt, self.clock(), 1024 * 1024 if op == "voice" else 0)
                    self.assertGreaterEqual(budget.button(op, self.clock()), reserved)
            self.assertEqual(budget.button("expand", self.clock()), D(".05") if year == 2026 else D(".09"))

    def test_price_boundary_and_read_cache_invalidation(self):
        before = dt.datetime(2026, 12, 31, 23, 59, tzinfo=dt.timezone.utc)
        after = before + dt.timedelta(minutes=1)
        self.assertEqual(prices.cost(prompts.TEXT_MODEL, 1000, 1000, before), D(".0045"))
        self.assertEqual(prices.cost(prompts.TEXT_MODEL, 1000, 1000, after), D(".009"))
        self.assertEqual(self.ledger.month_total(), 0)
        rid = self.ledger.reserve("topics", D(".02"), D(10), "draft")
        self.assertEqual(self.ledger.month_total(), D(".02"))
        self.ledger.settle(rid, "ok", actual=D(".003"))
        self.assertEqual(self.ledger.month_total(), D(".003"))
