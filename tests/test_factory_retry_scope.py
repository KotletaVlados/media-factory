"""Retry and resolve across slots: a retry never re-sends a target another slot's attempt may
have posted (§9.3), and `resolve --not-published` keeps the targets still owed when part of
the package already went out (§9.2)."""

from poster import state as poster_state
from tests.factory_base import FactoryTestCase, FakePoster, utc

A_SLOT = "a@2026-11-11T09:00:00Z"            # Wed 10:00 CET
B_SLOT = "b@2026-11-11T16:00:00Z"            # Wed 17:00 CET
SINCE = "2026-11-10T00:00:00Z"


def target_of(argv):
    return argv[argv.index("--targets") + 1]


def raising(argv, *, environ, stdout, stderr, clock):
    raise RuntimeError("the machine went off")


def silent(calls):
    def publish(argv, *, environ, stdout, stderr, clock):
        calls.append(argv)
        return 0                       # exit 0, no row in posts.jsonl
    return publish


class TwoRulesOneFolder(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.folder("f")
        for i in range(1, 4):
            self.stock_package("f", f"00{i}-f")
        self.write_rules([
            self.rule("a", "f", ["fb:kotleta", "linkedin"], ["wed"], ["10:00"], since=SINCE),
            self.rule("b", "f", ["linkedin"], ["wed"], ["17:00"], since=SINCE)])
        self.clock.now = utc(2026, 11, 11, 9, 0, 30)
        self.poster.statuses = {"linkedin": "failed"}
        self.assertEqual(self.factory("tick")[0], 1)       # a: fb published, linkedin failed
        self.poster.statuses = {}
        self.clock.now = utc(2026, 11, 11, 16, 0, 30)

    def a_rows(self):
        return [r for r in self.journal() if r["slot"] == A_SLOT]

    def assert_retry_refused(self, calls_before, holder):
        n_rows = len(self.a_rows())
        code, out, _ = self.factory("retry", A_SLOT)
        self.assertEqual(code, 2, out)
        self.assertIn(f"linkedin is held as taken by {holder}", out)
        self.assertEqual(len(self.poster.calls), calls_before)       # nothing was sent
        self.assertEqual(len(self.a_rows()), n_rows)                 # the journal is unchanged
        code, out, _ = self.factory("status")
        self.assertNotIn(f"factory retry {A_SLOT}", out)

    def test_retry_refuses_a_target_another_slot_left_interrupted(self):
        self.factory("tick", publish=raising)
        self.assertEqual(self.statuses()[B_SLOT], ["claimed", "interrupted"])
        self.assertEqual(self.journal()[-2]["package"], "001-f")      # b took the failed one
        code, out, _ = self.factory("status")
        self.assertIn(f"slot {B_SLOT}: interrupted", out)
        self.assert_retry_refused(len(self.poster.calls), f"slot {B_SLOT}")
        # the operator checks the account and finds nothing posted: the retry sends linkedin
        self.assertEqual(self.factory("resolve", B_SLOT, "--not-published")[0], 0)
        self.assertIn(f"linkedin failed; fix the cause, then factory retry {A_SLOT}",
                      self.factory("status")[1])
        n = len(self.poster.calls)
        code, out, _ = self.factory("retry", A_SLOT)
        self.assertEqual(code, 0, out)
        self.assertEqual([target_of(c) for c in self.poster.calls[n:]], ["linkedin"])
        self.assertEqual(self.a_rows()[-1]["outcome"],
                         {"fb:kotleta": "published", "linkedin": "published"})

    def test_retry_refuses_a_target_another_slot_ended_unknown(self):
        calls = []
        self.factory("tick", publish=silent(calls))
        self.assertEqual(self.journal()[-1]["outcome"], {"linkedin": "unknown"})
        self.assert_retry_refused(len(self.poster.calls), f"slot {B_SLOT}")
        self.assertEqual(len(calls), 1)

    def test_retry_refuses_a_target_the_record_holds_as_published_or_deleted(self):
        for status in ("published", "deleted", "unknown"):
            self.record("001-f", "linkedin", status, "2026-11-11T12:00:00Z")
            self.assert_retry_refused(len(self.poster.calls), "the poster record")

    def test_retry_sends_the_free_targets_and_names_the_taken_one(self):
        # one slot with two failed targets, one of them taken elsewhere
        self.folder("g")
        self.stock_package("g", "001-g")
        self.write_rules([self.rule("c", "g", ["fb:kotleta", "linkedin"], ["wed"], ["18:00"],
                                    since=SINCE)])
        self.clock.now = utc(2026, 11, 11, 17, 0, 30)
        self.poster.statuses = {"fb:kotleta": "failed", "linkedin": "failed"}
        self.assertEqual(self.factory("tick")[0], 1)
        self.record("001-g", "linkedin", "published", "2026-11-11T17:10:00Z")
        self.poster.statuses = {}
        n = len(self.poster.calls)
        code, out, _ = self.factory("retry", "c@2026-11-11T17:00:00Z")
        self.assertEqual(code, 1, out)
        self.assertIn("linkedin is held as taken by the poster record", out)
        self.assertEqual([target_of(c) for c in self.poster.calls[n:]], ["fb:kotleta"])


class ResolveNotPublishedKeepsOwedTargets(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.folder("f")
        for i in range(1, 4):
            self.stock_package("f", f"00{i}-f")
        self.write_rules([self.rule("a", "f", ["fb:kotleta", "linkedin"], ["wed", "fri"],
                                    ["10:00"], since=SINCE)])
        self.clock.now = utc(2026, 11, 11, 9, 0, 30)

    def records_then_raises(self, package="001-f", targets=("fb:kotleta",)):
        def publish(argv, *, environ, stdout, stderr, clock):
            rec = poster_state.Records(environ["MF_STATE_DIR"], clock)
            for t in targets:
                rec.append({"package": package, "target": t, "network": "facebook",
                            "status": "published"})
            raise RuntimeError("the machine went off")
        return publish

    def test_part_published_before_the_interruption_leaves_the_rest_retryable(self):
        self.factory("tick", publish=self.records_then_raises())
        self.assertEqual(self.statuses()[A_SLOT], ["claimed", "interrupted"])
        code, out, _ = self.factory("resolve", A_SLOT, "--not-published")
        self.assertEqual(code, 0, out)
        self.assertIn("fb:kotleta already went out", out)
        last = self.journal()[-1]
        self.assertEqual((last["status"], last["outcome"]),
                         ("done", {"fb:kotleta": "published", "linkedin": "failed"}))
        code, out, _ = self.factory("status")
        self.assertIn(f"slot {A_SLOT}: linkedin failed; fix the cause, then factory retry "
                      f"{A_SLOT}", out)
        self.clock.now = utc(2026, 11, 13, 9, 0, 30)             # Friday: the next package
        self.assertEqual(self.factory("tick")[0], 0)
        self.assertTrue(self.poster.calls[0][3].endswith("f/002-f.json"), self.poster.calls[0])
        self.poster.calls.clear()
        code, out, _ = self.factory("retry", A_SLOT)
        self.assertEqual(code, 0, out)
        self.assertEqual([(target_of(c), c[3].rsplit("/", 1)[1]) for c in self.poster.calls],
                         [("linkedin", "001-f.json")])
        self.assertEqual([r["status"] for r in self.journal() if r["slot"] == A_SLOT],
                         ["claimed", "interrupted", "done", "claimed", "done"])
        self.assertEqual(self.statuses()["a@2026-11-13T09:00:00Z"], ["claimed", "done"])
        done = [r for r in self.journal() if r["slot"] == A_SLOT][-1]
        self.assertEqual(done["outcome"], {"fb:kotleta": "published", "linkedin": "published"})
        self.assertNotIn("factory retry " + A_SLOT, self.factory("status")[1])

    def test_a_retry_that_died_before_the_poster_recorded_returns_to_its_earlier_outcome(self):
        self.poster.statuses = {"linkedin": "failed"}
        self.assertEqual(self.factory("tick")[0], 1)
        self.poster.statuses = {}
        self.clock.now = utc(2026, 11, 11, 9, 30)
        self.factory("retry", A_SLOT, publish=raising)
        self.assertEqual(self.statuses()[A_SLOT], ["claimed", "done", "claimed", "interrupted"])
        self.assertNotIn(f"factory retry {A_SLOT}", self.factory("status")[1])
        code, out, _ = self.factory("resolve", A_SLOT, "--not-published")
        self.assertEqual(code, 0, out)
        last = self.journal()[-1]
        self.assertEqual((last["status"], last["outcome"]),
                         ("done", {"fb:kotleta": "published", "linkedin": "failed"}))
        self.assertIn(f"slot {A_SLOT}: linkedin failed; fix the cause, then factory retry "
                      f"{A_SLOT}", self.factory("status")[1])
        n = len(self.poster.calls)
        self.assertEqual(self.factory("retry", A_SLOT)[0], 0)
        self.assertEqual([target_of(c) for c in self.poster.calls[n:]], ["linkedin"])
        self.assertEqual(self.journal()[-1]["outcome"],
                         {"fb:kotleta": "published", "linkedin": "published"})

    def test_nothing_went_out_still_releases_the_package(self):
        self.factory("tick", publish=raising)
        self.assertEqual(self.factory("resolve", A_SLOT, "--not-published")[0], 0)
        self.assertEqual(self.statuses()[A_SLOT], ["claimed", "interrupted", "resolved"])
        self.assertEqual(self.factory("tick")[0], 0)      # same slot: nothing new
