"""Runner: publish once (acceptance 3), crash recovery (4), downtime (5), X over the cap (6),
approval at run time (8), dry run writes nothing (9), retry, resolve, held packages."""

import json
import os
import subprocess
import sys
import threading

from poster import cli as poster_cli
from factory import journal as fjournal, runner as frunner
from tests.base import CANARIES, FakeTransport, REPO_ROOT, isolated_subprocess_env, resp
from tests.factory_base import FactoryTestCase, FakePoster, run_in_thread, utc

ALL4 = ["fb:kotleta", "ig:kotleta", "linkedin", "x"]
SLOT = "quotes-main@2026-11-11T09:00:00Z"          # Wed 10:00 CET
FRI_SLOT = "quotes-main@2026-11-13T09:00:00Z"

CHILD = r"""
import datetime as dt, os, sys, time
sys.path.insert(0, sys.argv[1])
from factory import cli
from poster import state
NOW = dt.datetime.fromisoformat(sys.argv[2])
MODE = sys.argv[3]

def publish(argv, *, environ, stdout, stderr, clock):
    with open(environ["CALLS_FILE"], "a") as fh:
        fh.write(" ".join(argv) + "\n")
    targets = argv[argv.index("--targets") + 1].split(",")
    if MODE in ("record-then-crash", "slow"):
        rec = state.Records(environ["MF_STATE_DIR"], clock)
        for t in targets:
            rec.append({"package": "001-q", "target": t, "status": "published",
                        "network": {"fb": "facebook", "ig": "instagram"}.get(t[:2], t)})
    if MODE == "slow":
        time.sleep(1.5)
        return 0
    os._exit(9)          # the process dies after the claim, mid-publish

sys.exit(cli.main(["tick"], clock=lambda: NOW, publish=publish))
"""


class TickFixture(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.clock.now = utc(2026, 11, 11, 9, 0, 30)
        self.folder("quotes")
        for i in range(1, 5):
            self.stock_package("quotes", f"00{i}-q")
        self.write_rules([self.rule("quotes-main", "quotes", ALL4, ["mon", "wed", "fri"],
                                    ["10:00"], since="2026-11-10T00:00:00Z")])

    def child(self, mode, now=None):
        env = isolated_subprocess_env(self)
        env["CALLS_FILE"] = os.path.join(self.root, "calls.txt")
        return subprocess.Popen([sys.executable, "-I", "-B", "-c", CHILD, REPO_ROOT,
                                 (now or self.clock.now).isoformat(), mode],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)

    def child_calls(self):
        path = os.path.join(self.root, "calls.txt")
        if not os.path.exists(path):
            return []
        with open(path) as fh:
            return fh.read().splitlines()

    def next_package(self, rule="quotes-main"):
        code, out, _ = self.factory("plan", "--days", "7", "--rule", rule)
        self.assertEqual(code, 0)
        line = out.split("slots\n", 1)[1].splitlines()[0]
        return line.split()[5]


class PublishOnceTests(TickFixture):
    def test_on_time_slot_publishes_once(self):
        code, out, err = self.factory("tick")
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(len(self.poster.calls), 1)
        argv = self.poster.calls[0]
        self.assertEqual(argv[argv.index("--targets") + 1], ",".join(ALL4))
        self.assertTrue(argv[argv.index("publish") + 1].endswith("quotes/001-q.json"))
        self.assertEqual(self.statuses(), {SLOT: ["claimed", "done"]})
        done = self.journal()[-1]
        self.assertEqual(done["outcome"], {t: "published" for t in ALL4})
        hb = fjournal.read_heartbeat(self.fstate)
        self.assertEqual(hb, {"ts": "2026-11-11T09:00:30Z", "version": "0.1.0", "due": 1,
                              "published": 1, "errors": 0})
        # the same minute again
        code, out, _ = self.factory("tick")
        self.assertEqual(code, 0)
        self.assertIn("nothing due", out)
        self.assertEqual(len(self.poster.calls), 1)
        self.assertEqual(self.statuses(), {SLOT: ["claimed", "done"]})
        for name in ("runs.jsonl", "heartbeat.json", "runner.lock"):
            self.assertEqual(os.stat(os.path.join(self.fstate, name)).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.fstate).st_mode & 0o777, 0o700)

    def test_two_concurrent_ticks_in_threads_call_the_poster_once(self):
        inside, release = threading.Event(), threading.Event()

        def block(_):
            inside.set()
            release.wait(10)
        self.poster.before_return = block
        first, box = run_in_thread(lambda: self.factory("tick"))
        self.assertTrue(inside.wait(10))
        code, out, _ = self.factory("tick")           # while the first holds the lock
        self.assertEqual(code, 0)
        self.assertIn("tick already running", out)
        release.set()
        first.join(10)
        self.assertEqual(box["result"][0], 0)
        self.assertEqual(len(self.poster.calls), 1)

    def test_two_concurrent_tick_processes_call_the_poster_once(self):
        procs = [self.child("slow"), self.child("slow")]
        results = [p.communicate(timeout=60) + (p.returncode,) for p in procs]
        self.assertEqual([r[2] for r in results], [0, 0], results)
        self.assertEqual(len(self.child_calls()), 1)
        self.assertEqual(self.statuses()[SLOT], ["claimed", "done"])

    def test_claim_is_atomic_between_writers(self):
        j1 = fjournal.Journal(self.fstate, self.clock)
        j2 = fjournal.Journal(self.fstate, self.clock)
        barrier = threading.Barrier(2)
        got = []

        def claim(j):
            barrier.wait()
            got.append(j.claim({"slot": SLOT, "package": "001-q", "targets": ["x"]}))
        threads = [threading.Thread(target=claim, args=(j,)) for j in (j1, j2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(g is None for g in got), [False, True])
        self.assertEqual(self.statuses(), {SLOT: ["claimed"]})


class CrashTests(TickFixture):
    def test_crash_after_claim_ends_interrupted_and_is_never_republished(self):
        proc = self.child("crash")
        proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 9)
        self.assertEqual(len(self.child_calls()), 1)
        self.assertEqual(self.statuses(), {SLOT: ["claimed"]})
        # the package is taken while the slot is open: the next slot gets 002
        self.assertEqual(self.next_package(), "002-q.json")

        code, out, _ = self.factory("tick")
        self.assertEqual(code, 1)
        self.assertIn("INTERRUPTED", out)
        self.assertEqual(self.poster.calls, [])
        self.assertEqual(self.statuses(), {SLOT: ["claimed", "interrupted"]})
        self.assertEqual(self.next_package(), "002-q.json")
        code, out, _ = self.factory("status")
        self.assertIn(f"slot {SLOT}: interrupted; check the account", out)

        self.assertEqual(self.factory("tick")[0], 0)       # nothing new; no second publish
        self.assertEqual(self.poster.calls, [])

        code, out, _ = self.factory("resolve", SLOT, "--not-published")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.statuses()[SLOT], ["claimed", "interrupted", "resolved"])
        self.assertEqual(self.next_package(), "001-q.json")  # released to the next slot

    def test_resolve_published_keeps_the_package_taken(self):
        self.child("crash").communicate(timeout=60)
        self.factory("tick")
        self.assertEqual(self.factory("resolve", SLOT, "--published")[0], 0)
        self.assertEqual(self.next_package(), "002-q.json")
        self.assertEqual(self.factory("resolve", SLOT, "--published")[0], 2)  # not interrupted
        self.assertEqual(self.factory("resolve", "nope@x", "--published")[0], 2)

    def test_crash_after_the_poster_recorded_events_ends_done(self):
        self.child("record-then-crash").communicate(timeout=60)
        code, out, _ = self.factory("tick")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.poster.calls, [])
        self.assertEqual(self.statuses(), {SLOT: ["claimed", "done"]})
        last = self.journal()[-1]
        self.assertEqual((last["outcome"], last["reconciled"]),
                         ({t: "published" for t in ALL4}, True))
        self.assertEqual(self.next_package(), "002-q.json")

    def test_an_exception_from_the_publish_entry_point_is_settled(self):
        def boom(*a, **kw):
            raise RuntimeError("socket closed")
        code, out, _ = self.factory("tick", publish=boom)
        self.assertEqual(code, 1)
        self.assertEqual(self.statuses(), {SLOT: ["claimed", "interrupted"]})


class DowntimeTests(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.folder("f")
        for i in range(1, 6):
            self.stock_package("f", f"00{i}-f")
        since = "2026-11-09T07:00:00Z"
        self.write_rules([
            self.rule("a", "f", ["fb:kotleta", "x"], ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                      ["10:00", "18:00"], since=since),
            self.rule("b", "f", ["fb:kotleta"], ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                      ["13:00"], since=since)])
        self.clock.now = utc(2026, 11, 9, 8, 0)
        code, out, _ = self.factory("tick")
        self.assertEqual(code, 0)
        self.assertIn("nothing due", out)

    def test_three_days_off_publishes_one_per_network_and_shifts_the_queue(self):
        self.clock.now = utc(2026, 11, 12, 18, 0)      # Thu 19:00 CET, 3 days later
        code, out, _ = self.factory("tick")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.poster.calls), 1)
        argv = self.poster.calls[0]
        self.assertEqual(argv[argv.index("--targets") + 1], "fb:kotleta,x")
        self.assertTrue(argv[argv.index("publish") + 1].endswith("f/001-f.json"))
        s = self.statuses()
        self.assertEqual(s["a@2026-11-12T17:00:00Z"], ["claimed", "done"])
        reasons = {row["slot"]: row["reason"] for row in self.journal() if row["status"] == "missed"}
        self.assertEqual(reasons["a@2026-11-12T09:00:00Z"], "superseded")   # older catch-up
        self.assertEqual(reasons["b@2026-11-12T12:00:00Z"], "superseded")   # fb used this tick
        self.assertEqual(reasons["a@2026-11-11T17:00:00Z"], "off")
        self.assertEqual(len(reasons), 11)                                  # 12 due, 1 published
        self.assertEqual(sorted(set(reasons.values())), ["off", "superseded"])
        # nothing lost: the next slots take 002 (a) and 003 (b)
        code, out, _ = self.factory("plan", "--days", "1")
        slots = out.split("slots\n", 1)[1].splitlines()
        self.assertIn("2026-11-13 Fri 10:00 CET", slots[0])
        self.assertIn("002-f.json", slots[0])
        self.assertIn("2026-11-13 Fri 13:00 CET", slots[1])
        self.assertIn("003-f.json", slots[1])
        # a second tick right after publishes nothing more
        self.assertEqual(self.factory("tick")[0], 0)
        self.assertEqual(len(self.poster.calls), 1)

    def test_catch_up_respects_the_gap_after_a_manual_post(self):
        self.record("manual-1", "fb:kotleta", "published", "2026-11-12T17:30:00Z")
        self.clock.now = utc(2026, 11, 12, 18, 0)
        code, out, _ = self.factory("tick")
        self.assertEqual(code, 0)
        self.assertEqual(self.poster.calls, [])
        reasons = {row["slot"]: row["reason"] for row in self.journal() if row["status"] == "missed"}
        self.assertEqual(reasons["a@2026-11-12T17:00:00Z"], "gap")
        self.assertEqual(reasons["b@2026-11-12T12:00:00Z"], "gap")
        self.assertIn("min 3 h", out)


class XBudgetTests(FactoryTestCase):
    def test_over_the_cap_publishes_the_free_targets_and_skips_x(self):
        self.clock.now = utc(2026, 11, 11, 9, 1)
        self.folder("t", "text")
        self.stock_package("t", "001-t", {"facebook": {"text": "free post"},
                                          "x": {"text": "paid post"}})
        self.write_rules([self.rule("r", "t", ["fb:kotleta", "x"], ["wed"], ["10:00"])])
        self.ledger_spent("4.990")
        transport = FakeTransport([resp(200, {"id": "300_1"})])

        def real_poster(argv, **kw):
            return poster_cli.main(argv, transport=transport, sleep=lambda s: None, **kw)
        code, out, err = self.factory("tick", publish=real_poster)
        self.assertEqual(code, 0, out + err)
        self.assertIn("x skipped (budget)", out)
        self.assertEqual(len(transport.requests), 1)
        self.assertIn("graph.facebook.com", transport.requests[0].url)
        claim, done = self.journal()
        self.assertEqual((claim["targets"], claim["skipped"]), (["fb:kotleta"], {"x": "budget"}))
        self.assertEqual(done["outcome"], {"fb:kotleta": "published", "x": "skipped (budget)"})
        self.assertEqual([r for r in self.ledger_rows() if r.get("package") == "001-t"], [])
        code, out, _ = self.factory("status")
        self.assertIn("X skipped on 1 slot(s) this month (budget)", out)


class ApprovalAtRunTimeTests(FactoryTestCase):
    def test_unapproved_package_is_never_published(self):
        self.clock.now = utc(2026, 11, 11, 9, 1)
        self.folder("f")
        self.stock_package("f", "001-f", approved=False)
        self.write_rules([self.rule("r", "f", ["fb:kotleta"], ["wed"], ["10:00"])])
        code, out, _ = self.factory("tick")
        self.assertEqual(code, 0)
        self.assertEqual(self.poster.calls, [])
        self.assertEqual(self.journal()[0]["reason"], "no-content")


class DryRunTests(TickFixture):
    def tree(self):
        out = []
        for dirpath, dirs, files in os.walk(self.root):
            for name in dirs + files:
                path = os.path.join(dirpath, name)
                st = os.stat(path)
                out.append((path, st.st_size, st.st_mtime_ns))
        return sorted(out)

    def test_dry_run_creates_no_file_or_folder(self):
        before = self.tree()
        self.assertFalse(os.path.exists(self.fstate))
        self.assertFalse(os.path.exists(self.state_dir))
        code, out, err = self.factory("tick", "--dry-run", publish=frunner.poster_main)
        self.assertEqual(code, 0, out + err)
        self.assertIn(f"{SLOT}  would publish quotes/001-q.json", out)
        self.assertIn("DRY RUN", out)
        self.assertEqual(self.tree(), before)

    def test_dry_run_with_existing_state_changes_nothing(self):
        self.assertEqual(self.factory("tick")[0], 0)      # Wednesday's slot, for real
        self.clock.now = utc(2026, 11, 13, 9, 0, 30)       # Friday's slot is due
        before = self.tree()
        code, out, _ = self.factory("tick", "--dry-run", publish=frunner.poster_main)
        self.assertEqual(code, 0, out)
        self.assertIn("would publish quotes/002-q.json", out)
        self.assertEqual(self.tree(), before)

    def test_dry_run_reports_misses_without_writing(self):
        self.clock.now = utc(2026, 11, 13, 9, 0)
        before = self.tree()
        code, out, _ = self.factory("tick", "--dry-run", publish=frunner.poster_main)
        self.assertIn(f"{SLOT}  would be missed (off)", out)
        self.assertEqual(self.tree(), before)


class FailureTests(TickFixture):
    def test_failed_target_is_retried_by_retry_only(self):
        self.poster.statuses = {"linkedin": "failed"}
        code, out, _ = self.factory("tick")
        self.assertEqual(code, 1)
        self.assertEqual(self.journal()[-1]["outcome"]["linkedin"], "failed")
        self.assertEqual(self.factory("tick")[0], 0)          # not retried automatically
        self.assertEqual(len(self.poster.calls), 1)
        code, out, _ = self.factory("status")
        self.assertIn(f"slot {SLOT}: linkedin failed; fix the cause, then factory retry {SLOT}", out)
        self.poster.statuses = {}
        self.clock.now = utc(2026, 11, 11, 9, 30)
        code, out, _ = self.factory("retry", SLOT)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.poster.calls), 2)
        retry_argv = self.poster.calls[1]          # only the failed target is sent again
        self.assertEqual(retry_argv[retry_argv.index("--targets") + 1], "linkedin")
        self.assertEqual(retry_argv[:5], self.poster.calls[0][:5])
        self.assertEqual(self.statuses()[SLOT], ["claimed", "done", "claimed", "done"])
        self.assertTrue(self.journal()[-2]["retry"])
        self.assertEqual(self.journal()[-1]["outcome"],      # the slot's whole outcome
                         {"fb:kotleta": "published", "ig:kotleta": "published",
                          "linkedin": "published", "x": "published"})
        code, out, _ = self.factory("status")
        self.assertNotIn("linkedin failed", out)
        self.assertEqual(self.factory("retry", SLOT)[0], 0)    # nothing left to retry
        self.assertEqual(len(self.poster.calls), 2)

    def test_retry_refuses_unknown_targets(self):
        self.poster.statuses = {"x": "unknown"}
        self.assertEqual(self.factory("tick")[0], 1)
        code, out, err = self.factory("retry", SLOT)
        self.assertEqual(code, 2)
        self.assertIn("--force-target x", out + err)
        self.assertEqual(len(self.poster.calls), 1)
        self.assertEqual(self.factory("retry", "nope@1")[0], 2)

    def test_package_refused_for_its_own_content_is_held_until_its_file_changes(self):
        self.poster.code = 2
        self.poster.output = ("package 001-q  targets ...\nrefused before any network call; "
                              "nothing was sent:\n  - x: text is 300 weighted characters\n")
        code, out, _ = self.factory("tick")
        self.assertEqual(code, 1)
        refused = self.journal()[-1]
        self.assertEqual((refused["status"], refused["held"]), ("refused", True))
        self.assertEqual(refused["reason"], "x: text is 300 weighted characters")
        self.assertEqual(self.next_package(), "002-q.json")
        code, out, _ = self.factory("status")
        self.assertIn("quotes/001-q.json: held: x: text is 300 weighted characters", out)
        # the orchestrator fixes the file: released
        path = os.path.join(self.stock, "quotes", "001-q.json")
        with open(path, "a") as fh:
            fh.write("\n")
        self.assertEqual(self.next_package(), "001-q.json")

    def test_refusal_for_a_missing_variable_does_not_hold_the_package(self):
        self.poster.code = 2
        self.poster.output = ("refused before any network call; nothing was sent:\n"
                              "  - x: missing X_API_KEY in the env file\n")
        self.factory("tick")
        self.assertFalse(self.journal()[-1]["held"])
        self.assertEqual(self.next_package(), "001-q.json")

    def test_two_slots_failing_on_every_target_hold_the_package(self):
        self.poster.statuses = {t: "failed" for t in ALL4}
        self.factory("tick")
        self.assertEqual(self.next_package(), "001-q.json")    # all failed: taken again
        self.clock.now = utc(2026, 11, 13, 9, 0, 30)
        self.factory("tick")
        self.assertEqual(len(self.poster.calls), 2)
        self.assertIn("001-q.json", self.poster.calls[1][3])
        self.assertEqual(self.next_package(), "002-q.json")
        code, out, _ = self.factory("status")
        self.assertIn("failed on every target on 2 slots in a row", out)

    def test_secrets_in_poster_output_never_reach_the_journal(self):
        self.poster.output = f"debug {CANARIES['FB_PAGE_KOTLETA_TOKEN']} access_token=abc\n"
        code, out, _ = self.factory("tick")
        self.assertEqual(code, 0)
        summary = self.journal()[-1]["summary"]
        self.assertIn("[redacted:FB_PAGE_KOTLETA_TOKEN]", summary)
        self.assertNotIn(CANARIES["FB_PAGE_KOTLETA_TOKEN"], json.dumps(self.journal()))

    def test_broken_rules_file_exits_2_and_records_the_error(self):
        with open(os.path.join(self.content, "rules.json"), "w") as fh:
            fh.write("{")
        code, out, _ = self.factory("tick")
        self.assertEqual(code, 2)
        self.assertEqual(fjournal.read_heartbeat(self.fstate)["errors"], 1)
        self.assertEqual(self.poster.calls, [])


class JournalReaderTests(FactoryTestCase):
    def test_reader_accepts_every_writer_and_a_torn_line(self):
        j = fjournal.Journal(self.fstate, self.clock)
        j.claim({"slot": "s1", "package": "p", "targets": ["x"]})
        j.append({"slot": "s1", "status": "done", "exit": 1, "outcome": {"x": "failed"}})
        j.claim({"slot": "s1", "package": "p", "targets": ["x"], "retry": True}, retry=True)
        with open(j.path, "a") as fh:
            fh.write('{"slot": "s1", "status": "do')          # a crash mid-write
        j.append({"slot": "s1", "status": "done", "exit": 0, "outcome": {"x": "published"}})
        j.append({"slot": "s2", "status": "missed", "reason": "off"})
        j.claim({"slot": "s3", "package": "q", "targets": ["fb:kotleta"]})
        j.append({"slot": "s3", "status": "interrupted", "reason": "r"})
        j.append({"slot": "s3", "status": "resolved", "published": False})
        j.append({"slot": "s4", "status": "refused", "reason": "r", "held": True})
        logs = j.logs()
        self.assertEqual({k: v.status for k, v in logs.items()},
                         {"s1": "done", "s2": "missed", "s3": "resolved", "s4": "refused"})
        self.assertEqual(logs["s1"].last["outcome"], {"x": "published"})
        self.assertEqual(fjournal.taken_pairs(logs), set())
        self.assertIsNone(j.claim({"slot": "s2", "package": "p", "targets": []}))
        self.assertIsNone(j.claim({"slot": "s2", "package": "p", "targets": []}, retry=True))


class ApprovalAtPublishTimeTests(TickFixture):
    """§9.4 step 1: the package is read again at the moment it is published."""

    def test_retry_refuses_a_package_rewritten_without_approval(self):
        self.poster.statuses = {"linkedin": "failed"}
        self.assertEqual(self.factory("tick")[0], 1)
        self.stock_package("quotes", "001-q", approved=False)       # rewritten, meta gone
        code, out, _ = self.factory("check")
        self.assertIn("not approved", out)
        before = self.journal()
        self.poster.statuses = {}
        code, out, err = self.factory("retry", SLOT)
        self.assertEqual(code, 2, out + err)
        self.assertIn("cannot be retried: not approved", out)
        self.assertEqual(len(self.poster.calls), 1)                   # no second poster call
        self.assertEqual(self.journal(), before)                      # the done entry is intact
        # approved again (the file changed): the retry sends only the failed target
        self.stock_package("quotes", "001-q")
        self.assertEqual(self.factory("retry", SLOT)[0], 0)
        self.assertEqual(len(self.poster.calls), 2)

    def test_retry_refuses_a_package_that_no_longer_passes_the_poster_checks(self):
        self.poster.statuses = {"linkedin": "failed"}
        self.factory("tick")
        self.stock_package("quotes", "001-q", {"facebook": {"text": "t", "image": "gone.jpg"}})
        code, out, _ = self.factory("retry", SLOT)
        self.assertEqual(code, 2, out)
        self.assertEqual(len(self.poster.calls), 1)

    def two_folder_rules(self):
        self.folder("a")
        self.folder("b")
        self.stock_package("a", "001-a")
        self.stock_package("b", "001-b")
        self.write_rules([
            self.rule("ra", "a", ["fb:kotleta"], ["wed"], ["10:00"], since="2026-11-10T00:00:00Z"),
            self.rule("rb", "b", ["linkedin"], ["wed"], ["10:00"], since="2026-11-10T00:00:00Z")])

    def rewrite_b_during_first_call(self, rewrite):
        def hook(poster):
            if len(poster.calls) == 1:
                rewrite()
        self.poster.before_return = hook

    def test_package_unapproved_during_the_tick_is_not_published(self):
        self.two_folder_rules()
        self.rewrite_b_during_first_call(lambda: self.stock_package("b", "001-b", approved=False))
        code, out, _ = self.factory("tick")
        self.assertEqual(code, 1, out)
        self.assertEqual(len(self.poster.calls), 1)                   # only ra's call
        self.assertIn("001-a.json", self.poster.calls[0][3])
        rb = [row for row in self.journal() if row["slot"].startswith("rb@")]
        self.assertEqual([r["status"] for r in rb], ["claimed", "refused"])
        self.assertTrue(rb[1]["held"])
        self.assertIn("not approved", rb[1]["reason"])
        self.assertEqual(rb[0]["fp"], list(self.fingerprint("b", "001-b.json")))
        # held while the file stays; approving it (a change) releases it for the next slot
        code, out, _ = self.factory("status")
        self.assertIn("b/001-b.json: not approved", out)
        self.stock_package("b", "001-b")
        self.assertEqual(self.next_package("rb"), "001-b.json")

    def test_package_changed_but_still_approved_during_the_tick_is_offered_again(self):
        self.two_folder_rules()
        self.rewrite_b_during_first_call(
            lambda: self.stock_package("b", "001-b", {"linkedin": {"text": "edited angle"}}))
        code, out, _ = self.factory("tick")
        self.assertEqual(len(self.poster.calls), 1)
        refused = [row for row in self.journal() if row["slot"].startswith("rb@")][-1]
        self.assertEqual(refused["status"], "refused")
        self.assertFalse(refused["held"])
        self.assertIn("changed after it was picked", refused["reason"])
        self.assertEqual(self.next_package("rb"), "001-b.json")      # not held

    def test_package_deleted_during_the_tick_is_refused_not_a_crash(self):
        self.two_folder_rules()
        self.rewrite_b_during_first_call(
            lambda: os.unlink(os.path.join(self.stock, "b", "001-b.json")))
        code, out, _ = self.factory("tick")
        self.assertEqual(code, 1)
        self.assertEqual(len(self.poster.calls), 1)
        self.assertEqual(self.statuses()[[k for k in self.statuses() if k.startswith("rb@")][0]],
                         ["claimed", "refused"])

    def fingerprint(self, folder, file):
        from factory import stock as fstock
        return fstock.fingerprint(os.path.join(self.stock, folder, file))


class RetryTargetsTests(FactoryTestCase):
    def test_retry_sends_only_the_failed_target_even_after_a_delete(self):
        self.clock.now = utc(2026, 11, 11, 9, 1)
        self.folder("t", "text")
        self.stock_package("t", "001-t", {"facebook": {"text": "free post"},
                                          "linkedin": {"text": "angle post"}})
        self.write_rules([self.rule("r", "t", ["fb:kotleta", "linkedin"], ["wed"], ["10:00"])])
        slot = "r@2026-11-11T09:00:00Z"
        self.poster.statuses = {"linkedin": "failed"}
        self.assertEqual(self.factory("tick")[0], 1)
        # the operator removed the Facebook post with `poster delete`: latest row is `deleted`
        self.record("001-t", "fb:kotleta", "deleted", "2026-11-11T09:30:00Z")
        self.clock.now = utc(2026, 11, 11, 10, 0)
        transport = FakeTransport([resp(201, {}, {"x-restli-id": "urn:li:share:900"})])

        def real_poster(argv, **kw):
            return poster_cli.main(argv, transport=transport, sleep=lambda s: None, **kw)
        code, out, err = self.factory("retry", slot, publish=real_poster)
        self.assertEqual(code, 0, out + err)
        self.assertIn("retry " + slot + ": linkedin", out)
        self.assertEqual([r.url for r in transport.requests],
                         ["https://api.linkedin.com/rest/posts"])
        done = self.journal()[-1]
        self.assertEqual(done["outcome"], {"fb:kotleta": "published", "linkedin": "published"})


class JournalOutcomeTests(TickFixture):
    """A `done` slot is as good as a record row when the poster could not write one."""

    def silent_poster(self):
        calls = []

        def publish(argv, *, environ, stdout, stderr, clock):
            calls.append(argv)
            return 0                     # exit 0, but no row in posts.jsonl
        publish.calls = calls
        return publish

    def test_unknown_outcome_without_a_record_row_keeps_the_package_taken(self):
        quiet = self.silent_poster()
        code, out, _ = self.factory("tick", publish=quiet)
        self.assertEqual(code, 1)
        done = self.journal()[-1]
        self.assertEqual(done["outcome"], {t: "unknown" for t in ALL4})
        self.assertEqual(self.next_package(), "002-q.json")
        code, out, _ = self.factory("status")
        for t in ALL4:
            self.assertIn(f"slot {SLOT}: {t} ended unknown; check the account", out)
        self.clock.now = utc(2026, 11, 13, 9, 0, 30)
        self.factory("tick", publish=quiet)
        self.assertEqual(len(quiet.calls), 2)
        self.assertTrue(quiet.calls[0][3].endswith("quotes/001-q.json"))
        self.assertTrue(quiet.calls[1][3].endswith("quotes/002-q.json"))   # not 001-q again
        code, out, _ = self.factory("plan", "--days", "1")
        self.assertIn("2 check account", out)

    def test_published_outcome_without_a_record_row_keeps_the_package_taken(self):
        j = fjournal.Journal(self.fstate, self.clock)
        j.claim({"slot": SLOT, "package": "001-q", "targets": ALL4})
        j.append({"slot": SLOT, "status": "done", "exit": 0,
                  "outcome": {t: "published" for t in ALL4}})
        self.assertEqual(self.next_package(), "002-q.json")
        # a record row, when there is one, still decides
        self.record("001-q", "fb:kotleta", "deleted", "2026-11-11T09:01:00Z")
        self.assertEqual(self.next_package(), "002-q.json")

    def test_failed_outcome_does_not_hold_the_package(self):
        j = fjournal.Journal(self.fstate, self.clock)
        j.claim({"slot": SLOT, "package": "001-q", "targets": ALL4})
        j.append({"slot": SLOT, "status": "done", "exit": 1,
                  "outcome": {t: "failed" for t in ALL4}})
        self.assertEqual(self.next_package(), "001-q.json")


class OlderRowTests(TickFixture):
    """An older `failed` row in the record is not the result of a later attempt whose poster
    could not write its row."""

    silent_poster = JournalOutcomeTests.silent_poster

    def failed_then_silent_retry(self):
        self.poster.statuses = {"linkedin": "failed"}
        self.assertEqual(self.factory("tick")[0], 1)
        self.poster.statuses = {}
        quiet = self.silent_poster()
        self.clock.now = utc(2026, 11, 11, 9, 30)
        code, out, _ = self.factory("retry", SLOT, publish=quiet)
        return quiet, code, out

    def test_retry_without_a_new_row_is_unknown_not_failed(self):
        quiet, code, out = self.failed_then_silent_retry()
        self.assertEqual(code, 1)
        self.assertEqual(len(quiet.calls), 1)
        self.assertEqual(self.journal()[-1]["outcome"]["linkedin"], "unknown")
        self.assertEqual(self.journal()[-1]["outcome"]["fb:kotleta"], "published")
        code, out, _ = self.factory("status")
        self.assertNotIn(f"factory retry {SLOT}", out)
        self.assertIn(f"slot {SLOT}: linkedin ended unknown", out)
        code, out, err = self.factory("retry", SLOT, publish=quiet)
        self.assertEqual(code, 2)
        self.assertEqual(len(quiet.calls), 1)                  # nothing sent a second time
        self.assertEqual(len(self.poster.calls), 1)

    def test_no_later_slot_is_offered_the_package_for_that_target(self):
        self.failed_then_silent_retry()
        self.assertEqual(self.next_package(), "002-q.json")     # 001-q is taken on every target
        self.clock.now = utc(2026, 11, 13, 9, 0, 30)
        self.assertEqual(self.factory("tick")[0], 0)
        argv = self.poster.calls[1]
        self.assertTrue(argv[3].endswith("quotes/002-q.json"), argv)

    def test_tick_after_a_failed_slot_with_a_silent_poster_is_unknown_and_holds_the_package(self):
        self.poster.statuses = {t: "failed" for t in ALL4}
        self.assertEqual(self.factory("tick")[0], 1)
        quiet = self.silent_poster()
        self.clock.now = utc(2026, 11, 13, 9, 0, 30)
        self.factory("tick", publish=quiet)                     # 001-q again: failure frees it
        self.assertTrue(quiet.calls[0][3].endswith("quotes/001-q.json"))
        self.assertEqual(self.journal()[-1]["outcome"], {t: "unknown" for t in ALL4})
        code, out, _ = self.factory("status")
        self.assertNotIn("factory retry " + FRI_SLOT, out)
        self.assertEqual(self.factory("retry", FRI_SLOT, publish=quiet)[0], 2)
        self.assertEqual(len(quiet.calls), 1)
        self.clock.now = utc(2026, 11, 16, 9, 0, 30)
        self.factory("tick", publish=quiet)
        self.assertTrue(quiet.calls[1][3].endswith("quotes/002-q.json"))

    def test_a_published_row_from_before_is_already(self):
        entry = type("E", (), {"id": "001-q"})()
        rows = [{"package": "001-q", "target": "linkedin", "status": "published"},
                {"package": "001-q", "target": "x", "status": "failed"}]
        out = frunner.Runner.attempt_outcome(entry, ["linkedin", "x", "fb:kotleta"], rows, 2)
        self.assertEqual(out, {"linkedin": "already", "x": "unknown", "fb:kotleta": "unknown"})
        rows.append({"package": "001-q", "target": "x", "status": "published"})
        out = frunner.Runner.attempt_outcome(entry, ["x"], rows, 2)
        self.assertEqual(out, {"x": "published"})


class RetryRefusedTests(TickFixture):
    def refusing_poster(self):
        calls = []

        def publish(argv, *, environ, stdout, stderr, clock):
            calls.append(argv)
            stdout.write("refused:\n  - linkedin: the LinkedIn token expired; run login\n")
            return 2
        publish.calls = calls
        return publish

    def test_a_refused_retry_leaves_the_slot_retryable_with_its_outcome(self):
        self.poster.statuses = {"linkedin": "failed"}
        self.assertEqual(self.factory("tick")[0], 1)
        refuse = self.refusing_poster()
        self.clock.now = utc(2026, 11, 11, 9, 30)
        code, out, _ = self.factory("retry", SLOT, publish=refuse)
        self.assertEqual(code, 1)
        self.assertIn("LinkedIn token expired", out)
        last = self.journal()[-1]
        self.assertEqual(last["status"], "done")
        self.assertEqual(last["outcome"]["linkedin"], "failed")
        self.assertEqual(last["outcome"]["fb:kotleta"], "published")
        # the failed target stays in attention, long after the usual refusal window
        self.clock.now = utc(2026, 11, 25, 9, 30)
        code, out, _ = self.factory("status")
        self.assertIn(f"slot {SLOT}: linkedin failed; fix the cause, then factory retry {SLOT}", out)
        # the operator re-logs in; the second retry sends only the failed target
        self.clock.now = utc(2026, 11, 11, 10, 0)
        self.poster.statuses = {}
        code, out, _ = self.factory("retry", SLOT)
        self.assertEqual(code, 0, out)
        argv = self.poster.calls[1]
        self.assertEqual(argv[argv.index("--targets") + 1], "linkedin")
        self.assertEqual(len(refuse.calls), 1)
        self.assertEqual(self.journal()[-1]["status"], "done")
        self.assertEqual(self.journal()[-1]["outcome"], {t: "published" for t in ALL4})
        self.assertNotIn("linkedin failed", self.factory("status")[1])

    def test_a_refused_retry_keeps_the_earlier_published_targets_taken(self):
        self.poster.statuses = {"linkedin": "failed"}
        self.factory("tick")
        self.clock.now = utc(2026, 11, 11, 9, 30)
        self.factory("retry", SLOT, publish=self.refusing_poster())
        logs = fjournal.index(self.journal())
        done = fjournal.done_pairs(logs)
        self.assertIn(("001-q", "fb:kotleta"), done)
        self.assertEqual(logs[SLOT].status, "done")


class RetryCrashTests(TickFixture):
    def test_a_retry_that_dies_after_recording_keeps_the_slots_whole_outcome(self):
        self.poster.statuses = {"linkedin": "failed"}
        self.factory("tick")
        self.clock.now = utc(2026, 11, 11, 9, 30)

        def record_then_raise(argv, *, environ, stdout, stderr, clock):
            poster_state_records = __import__("poster.state", fromlist=["x"]).Records(
                environ["MF_STATE_DIR"], clock)
            poster_state_records.append({"package": "001-q", "target": "linkedin",
                                         "network": "linkedin", "status": "published"})
            raise RuntimeError("boom")
        self.factory("retry", SLOT, publish=record_then_raise)
        last = self.journal()[-1]
        self.assertEqual(last["status"], "done")
        self.assertEqual(last["outcome"], {t: "published" for t in ALL4})


class XBudgetRaceTests(FactoryTestCase):
    RESERVE = r"""
import datetime as dt, sys
from decimal import Decimal
sys.path.insert(0, sys.argv[1])
from poster import state
now = dt.datetime.fromisoformat(sys.argv[3])
state.Ledger(sys.argv[2], lambda: now).reserve([("post", Decimal("0.090"))], "other", Decimal("5"))
"""

    def setUp(self):
        super().setUp()
        self.clock.now = utc(2026, 11, 11, 9, 1)
        self.folder("t", "text")
        self.ledger_spent("4.900")

    def other_process_spends(self, calls):
        """A second process reserves X money after the runner's check, before the poster's."""
        transport = FakeTransport([resp(200, {"id": "300_1"})])

        def real_poster(argv, **kw):
            calls.append(argv)
            if len(calls) == 1:
                subprocess.run([sys.executable, "-I", "-B", "-c", self.RESERVE, REPO_ROOT,
                                self.state_dir, self.clock.now.isoformat()],
                               env=isolated_subprocess_env(self), check=True, timeout=60)
            return poster_cli.main(argv, transport=transport, sleep=lambda s: None, **kw)
        return real_poster, transport

    def test_x_spent_by_another_process_skips_x_and_publishes_the_free_networks(self):
        self.stock_package("t", "001-t", {"facebook": {"text": "free post"},
                                          "x": {"text": "paid post"}})
        self.write_rules([self.rule("r", "t", ["fb:kotleta", "x"], ["wed"], ["10:00"])])
        calls = []
        poster, transport = self.other_process_spends(calls)
        code, out, err = self.factory("tick", publish=poster)
        self.assertEqual(code, 0, out + err)
        self.assertIn("x skipped (budget)", out)
        self.assertEqual([r.url.split("/")[2] for r in transport.requests],
                         ["graph.facebook.com"])
        self.assertEqual([a[a.index("--targets") + 1] for a in calls], ["fb:kotleta,x", "fb:kotleta"])
        rows = self.journal()
        self.assertEqual([r["status"] for r in rows], ["claimed", "claimed", "done"])
        self.assertEqual(rows[1]["targets"], ["fb:kotleta"])
        self.assertEqual(rows[1]["skipped"], {"x": "budget"})
        self.assertEqual(rows[2]["outcome"], {"fb:kotleta": "published", "x": "skipped (budget)"})
        self.assertEqual([r for r in self.ledger_rows() if r.get("package") == "001-t"], [])
        self.assertEqual(self.factory("tick")[0], 0)                  # nothing more
        self.assertEqual(len(calls), 2)

    def test_x_only_slot_lost_to_another_process_ends_done_with_x_skipped(self):
        self.stock_package("t", "001-t", {"x": {"text": "paid post"}})
        self.write_rules([self.rule("r", "t", ["x"], ["wed"], ["10:00"])])
        calls = []
        poster, transport = self.other_process_spends(calls)
        code, out, err = self.factory("tick", publish=poster)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(transport.requests, [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.journal()[-1]["outcome"], {"x": "skipped (budget)"})
        self.assertEqual(self.statuses(), {"r@2026-11-11T09:00:00Z": ["claimed", "done"]})
