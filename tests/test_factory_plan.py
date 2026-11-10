"""Planner: §8.3 output shape, assignment, runway, run-out, X projection (acceptance 1),
daylight saving (acceptance 7) and approval (acceptance 8, planning side)."""

import datetime as dt
import zoneinfo
from decimal import Decimal

from factory import planner, ruleset
from tests.factory_base import FactoryTestCase, utc

QUOTES_TARGETS = ["fb:kotleta", "ig:kotleta", "linkedin", "x"]

EXPECTED_PLAN = """\
plan 2026-11-10 → 2026-11-24 (machine tz Europe/Berlin)
rules: 2 active, 1 draft     publications next 7 days: 16     content runs out 2026-11-19 (tips-main)
X 2026-11: spent $0.230 + planned $0.875 = $1.105 of $5.00     X 2026-12: planned $0.000
folders
  quotes  photo  5 ready  1 not approved  1 used   runway 13 of 90 days (until 2026-11-23)
  tips    text   3 ready                           runway 9 of 90 days (until 2026-11-19)
slots
  2026-11-10 Tue 19:00 CET  tips-main    001-t.json   fb:kotleta linkedin
  2026-11-11 Wed 10:00 CET  quotes-main  002-q.json   fb:kotleta ig:kotleta linkedin x
  2026-11-12 Thu 19:00 CET  tips-main    002-t.json   fb:kotleta linkedin
  2026-11-13 Fri 10:00 CET  quotes-main  003-q.json   fb:kotleta ig:kotleta linkedin x
  2026-11-14 Sat 12:00 CET  tips-x       —            —  [draft: rule not running]
  2026-11-16 Mon 10:00 CET  quotes-main  004-q.json   fb:kotleta ig:kotleta linkedin x
  2026-11-17 Tue 19:00 CET  tips-main    003-t.json   fb:kotleta linkedin
  2026-11-18 Wed 10:00 CET  quotes-main  005-q.json   fb:kotleta ig:kotleta linkedin x
  2026-11-19 Thu 19:00 CET  tips-main    —            —  [no content]
  2026-11-20 Fri 10:00 CET  quotes-main  006-q.json   fb:kotleta ig:kotleta linkedin x
  2026-11-21 Sat 12:00 CET  tips-x       —            —  [draft: rule not running]
  2026-11-23 Mon 10:00 CET  quotes-main  —            —  [no content]
"""


class PlanFixture(FactoryTestCase):
    """2 folders, 2 active rules and 1 draft. Now is Tue 2026-11-10 09:00 CET."""

    def setUp(self):
        super().setUp()
        self.clock.now = utc(2026, 11, 10, 8, 0)
        self.folder("quotes", "photo")
        for i in range(1, 7):
            self.stock_package("quotes", f"00{i}-q")
        self.stock_package("quotes", "007-q", approved=False)
        # 003's X variant has no image, so its X post costs $0.015 instead of $0.215
        self.stock_package("quotes", "003-q", {
            "facebook": {"text": "t", "image": "square.jpg"},
            "instagram": {"text": "c", "image": "square.jpg"},
            "linkedin": {"text": "l"}, "x": {"text": "x only text"}})
        self.folder("tips", "text")
        for i in range(1, 4):
            self.stock_package("tips", f"00{i}-t", {"facebook": {"text": "tip"},
                                                   "linkedin": {"text": "tip"},
                                                   "x": {"text": "tip"}})
        for t in QUOTES_TARGETS:   # 001-q went out on Monday's slot: used
            self.record("001-q", t, "published", "2026-11-09T09:00:05Z")
        self.ledger_spent("0.230")
        self.write_rules([
            self.rule("quotes-main", "quotes", QUOTES_TARGETS, ["mon", "wed", "fri"], ["10:00"]),
            self.rule("tips-main", "tips", ["fb:kotleta", "linkedin"], ["tue", "thu"], ["19:00"]),
            self.rule("tips-x", "tips", ["x"], ["sat"], ["12:00"], status="draft"),
        ])


class PlanOutputTests(PlanFixture):
    def test_plan_prints_the_design_shape_with_hand_computed_values(self):
        code, out, err = self.factory("plan", "--days", "14")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, EXPECTED_PLAN)

    def test_two_runs_are_byte_identical(self):
        first = self.factory("plan", "--days", "14")
        second = self.factory("plan", "--days", "14")
        self.assertEqual(first, second)

    def test_plan_writes_nothing(self):
        import os
        before = sorted(os.walk(self.root))
        self.factory("plan")
        self.assertEqual(sorted(os.walk(self.root)), before)
        self.assertFalse(os.path.exists(self.fstate))

    def test_rule_filter_keeps_only_that_rule(self):
        code, out, _ = self.factory("plan", "--days", "14", "--rule", "tips-main")
        self.assertEqual(code, 0)
        slots = out.split("slots\n", 1)[1].splitlines()
        self.assertTrue(slots and all("tips-main" in line for line in slots))
        self.assertEqual(self.factory("plan", "--rule", "nope")[0], 2)


class PlanValuesTests(PlanFixture):
    def plan(self, **kw):
        from factory import inputs as finputs, paths
        from poster.redact import Redactor
        inp = finputs.load(paths.resolve(self.environ), self.clock, Redactor())
        return inp, planner.plan(inp.ruleset, inp.stock, inp.records, inp.journal, inp.x_spent,
                                 inp.settings, self.clock.now, **kw)

    def test_assignment_runway_runout_and_x_projection(self):
        _, p = self.plan(days=14)
        planned = [(s.slot.rule, s.entry.id) for s in p.slots if s.state == "planned"]
        self.assertEqual(planned, [("tips-main", "001-t"), ("quotes-main", "002-q"),
                                   ("tips-main", "002-t"), ("quotes-main", "003-q"),
                                   ("quotes-main", "004-q"), ("tips-main", "003-t"),
                                   ("quotes-main", "005-q"), ("quotes-main", "006-q")])
        self.assertEqual(p.runout, {"quotes-main": utc(2026, 11, 23, 9, 0),
                                    "tips-main": utc(2026, 11, 19, 18, 0)})
        runway = {f.name: f.runway_days for f in p.folders}
        self.assertEqual(runway, {"quotes": 13, "tips": 9})
        self.assertEqual(p.publications_7d, 3 * 4 + 2 * 2)
        self.assertEqual(p.x["2026-11"], (Decimal("0.230"), Decimal("0.875")))
        self.assertEqual(p.first_runout(), (utc(2026, 11, 19, 18, 0), "tips-main"))

    def test_draft_runway_counts_the_draft_as_active(self):
        _, p = self.plan(days=14, extra_active="tips-x")
        # tips-x takes the x variant of 001-t on Sat 14th; tips-main still gets all three
        self.assertEqual(p.runout["tips-main"], utc(2026, 11, 19, 18, 0))
        sat = [s for s in p.slots if s.slot.rule == "tips-x" and s.state == "planned"]
        self.assertEqual([s.entry.id for s in sat], ["001-t", "002-t"])

    def test_over_budget_slot_drops_x_and_keeps_the_others(self):
        self.ledger_spent("4.500", package="big")
        _, p = self.plan(days=14)
        states = [(s.entry.id, s.state, s.targets) for s in p.slots
                  if s.slot.rule == "quotes-main" and s.entry]
        # 4.73 spent; 002 (0.215) fits -> 4.945; 003 (0.015) fits -> 4.96; 004 does not
        self.assertEqual(states[0][1], "planned")
        self.assertEqual(states[1][1], "planned")
        self.assertEqual(states[2], ("004-q", "over-budget", ("fb:kotleta", "ig:kotleta", "linkedin")))

    def test_long_runway_displays(self):
        from factory.cli import runway_text
        f = planner.FolderSummary("a", "photo", {}, ["r"], 120, utc(2027, 3, 10))
        self.assertEqual(runway_text(f), "runway 120 days ✓ (until 2027-03-10)")
        f = planner.FolderSummary("a", "photo", {}, ["r"], None, None)
        self.assertEqual(runway_text(f), "runway > 400 days ✓")
        f = planner.FolderSummary("a", "photo", {}, [], None, None)
        self.assertEqual(runway_text(f), "nobody takes it · use 0")


class ApprovalTests(FactoryTestCase):
    def test_a_package_without_approval_is_never_assigned(self):
        self.clock.now = utc(2026, 11, 10, 8, 0)
        self.folder("f")
        self.stock_package("f", "001-a", approved=False)
        self.stock_package("f", "002-b")
        self.stock_package("f", "003-c", meta={"approved_by_operator": "  "})
        self.write_rules([self.rule("r", "f", ["fb:kotleta"], ["wed", "thu"], ["10:00"])])
        code, out, _ = self.factory("plan", "--days", "7")
        self.assertEqual(code, 0)
        self.assertIn("002-b.json", out)
        self.assertNotIn("001-a.json", out)
        self.assertNotIn("003-c.json", out)
        self.assertIn("[no content]", out)
        self.assertIn("1 ready  2 not approved", out)


class DaylightSavingTests(FactoryTestCase):
    BERLIN = zoneinfo.ZoneInfo("Europe/Berlin")

    def test_slots_keep_local_wall_time_across_both_transitions(self):
        rule = ruleset.Rule("r", "f", ("fb:kotleta",), ruleset.DAYS, ("10:00",), "Europe/Berlin",
                            "active")
        spring = planner.rule_slots(rule, utc(2026, 3, 28, 0), utc(2026, 3, 30, 23))
        self.assertEqual([s.when for s in spring],
                         [utc(2026, 3, 28, 9), utc(2026, 3, 29, 8), utc(2026, 3, 30, 8)])
        autumn = planner.rule_slots(rule, utc(2026, 10, 24, 0), utc(2026, 10, 26, 23))
        self.assertEqual([s.when for s in autumn],
                         [utc(2026, 10, 24, 8), utc(2026, 10, 25, 9), utc(2026, 10, 26, 9)])
        for s in spring + autumn:
            self.assertEqual(s.when.astimezone(self.BERLIN).strftime("%H:%M"), "10:00")

    def test_skipped_local_time_moves_to_the_first_valid_minute_after(self):
        for minute in (0, 30, 59):
            when = planner.local_to_utc(dt.datetime(2026, 3, 29, 2, minute), self.BERLIN)
            self.assertEqual(when, utc(2026, 3, 29, 1, 0))   # 03:00 CEST
            self.assertEqual(when.astimezone(self.BERLIN).strftime("%H:%M"), "03:00")

    def test_repeated_local_time_uses_its_first_occurrence(self):
        when = planner.local_to_utc(dt.datetime(2026, 10, 25, 2, 30), self.BERLIN)
        self.assertEqual(when, utc(2026, 10, 25, 0, 30))     # 02:30 CEST, not CET
        self.assertEqual(when.astimezone(self.BERLIN).utcoffset(), dt.timedelta(hours=2))

    def test_slot_key_is_rule_and_utc_time(self):
        self.assertEqual(planner.Slot("quotes-main", utc(2026, 11, 11, 9)).key,
                         "quotes-main@2026-11-11T09:00:00Z")


class ActiveSinceTests(FactoryTestCase):
    def test_slots_before_active_since_are_neither_due_nor_planned(self):
        self.clock.now = utc(2026, 11, 11, 9, 5)          # Wed 10:05 CET
        self.folder("f")
        self.stock_package("f", "001-f")
        self.write_rules([self.rule("r", "f", ["fb:kotleta"], ["wed", "fri"], ["10:00"],
                                    since="2026-11-13T12:00:00Z")])   # hand-edited, future
        code, out, _ = self.factory("plan", "--days", "10")
        slots = out.split("slots\n", 1)[1].splitlines()
        self.assertIn("2026-11-18 Wed 10:00 CET", slots[0])          # Fri 13th is before
        self.assertIn("001-f.json", slots[0])
        self.assertEqual(self.factory("tick")[1].splitlines()[-1], "  nothing due")
        self.assertEqual(self.poster.calls, [])
