"""CLI: status and attention items, timer units, a real process, paths, poster helper names."""

import os
import subprocess
import sys

from poster import state as poster_state
from factory import cli as fcli, journal as fjournal, paths as fpaths
from tests.base import REPO_ROOT, isolated_subprocess_env
from tests.factory_base import FactoryTestCase, utc

ALL4 = ["fb:kotleta", "ig:kotleta", "linkedin", "x"]


class StatusTests(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.clock.now = utc(2026, 11, 11, 9, 0, 30)
        self.folder("quotes")
        for i in range(1, 4):
            self.stock_package("quotes", f"00{i}-q")
        self.stock_package("quotes", "004-q", approved=False)
        self.write_rules([self.rule("quotes-main", "quotes", ALL4, ["mon", "wed", "fri"],
                                    ["10:00"], since="2026-11-10T00:00:00Z")])

    def test_status_before_and_after_a_tick(self):
        code, out, _ = self.factory("status")
        self.assertEqual(code, 0)
        self.assertIn("last tick: none yet", out)
        self.assertIn("the timer is not running: no tick yet", out)
        self.assertIn("quotes/004-q.json: not approved", out)
        self.assertIn("content runs out 2026-11-20 (quotes-main)", out)
        self.assertIn("LinkedIn token: 54 day(s) left", out)
        self.factory("tick")
        code, out, _ = self.factory("status")
        self.assertIn("last tick: 2026-11-11T09:00:30Z (due 1, published 1, errors 0)", out)
        self.assertIn("next slots:\n  2026-11-13 Fri 10:00 CET  quotes-main  002-q.json", out)
        self.assertNotIn("timer is not running", out)
        self.clock.now = utc(2026, 11, 11, 9, 45, 30)
        code, out, _ = self.factory("status")
        self.assertIn("the timer is not running: last tick 45 min ago", out)

    def test_linkedin_expiry_and_x_projection_warnings(self):
        self.write_env(dict(self.env_values, LINKEDIN_TOKEN_EXPIRES_AT="2026-11-14T00:00:00Z",
                            X_MONTHLY_CAP_USD="0.50"))
        code, out, _ = self.factory("status")
        self.assertIn("LinkedIn token expires in 2 day(s)", out)
        self.assertIn("is over 80 % of $0.50", out)


class TimerTests(FactoryTestCase):
    def test_print_fills_the_checkout_and_writes_nothing(self):
        before = sorted(os.walk(self.root))
        code, out, _ = self.factory("timer", "--print")
        self.assertEqual(code, 0)
        self.assertIn(f"WorkingDirectory={REPO_ROOT}\n", out)
        self.assertIn("ExecStart=/usr/bin/python3 -s -B -m factory tick\n", out)
        self.assertIn("OnCalendar=*:0/5\n", out)
        self.assertIn("systemctl --user enable --now media-factory-tick.timer\n", out)
        self.assertEqual(sorted(os.walk(self.root)), before)
        self.assertEqual(self.factory("timer")[0], 2)      # --print is required


class RealProcessTests(FactoryTestCase):
    def test_plan_in_a_real_process_matches_in_process(self):
        self.clock.now = utc(2026, 11, 10, 8, 0)
        self.folder("quotes")
        self.stock_package("quotes", "001-q")
        self.write_rules([self.rule("q", "quotes", ALL4, ["wed"], ["10:00"])])
        script = (f"import sys, datetime as dt; sys.path.insert(0, {REPO_ROOT!r}); "
                  "from factory.cli import main; "
                  "sys.exit(main(sys.argv[1:], clock=lambda: dt.datetime(2026, 11, 10, 8, "
                  "tzinfo=dt.timezone.utc)))")
        proc = subprocess.run([sys.executable, "-I", "-B", "-c", script, "plan", "--days", "7"],
                              env=isolated_subprocess_env(self), capture_output=True, text=True,
                              timeout=60)
        self.outputs += [proc.stdout, proc.stderr]
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        self.assertEqual(proc.stdout, self.factory("plan", "--days", "7")[1])

    def test_usage_errors_exit_2(self):
        self.assertEqual(self.factory()[0], 2)
        self.assertEqual(self.factory("plan", "--days", "0")[0], 2)
        self.assertEqual(self.factory("plan", "--days", "99999999999999999999")[0], 2)
        self.assertEqual(self.factory("resolve", "s")[0], 2)
        os.remove(self.env_path)
        code, _, err = self.factory("plan")
        self.assertEqual(code, 2)
        self.assertIn("env file not found", err)


class PathTests(FactoryTestCase):
    def test_resolution_order(self):
        env = {"HOME": "/h"}
        self.assertEqual(fpaths.resolve_factory_state_dir(None, env),
                         "/h/.local/state/media-factory/factory")
        env["XDG_STATE_HOME"] = "/x"
        self.assertEqual(fpaths.resolve_factory_state_dir(None, env), "/x/media-factory/factory")
        env["MF_FACTORY_STATE_DIR"] = "/m"
        self.assertEqual(fpaths.resolve_factory_state_dir(None, env), "/m")
        self.assertEqual(fpaths.resolve_factory_state_dir("/flag", env), "/flag")
        self.assertEqual(fpaths.resolve_content_dir(None, {}), os.path.join(REPO_ROOT, "content"))
        self.assertEqual(fpaths.resolve_content_dir(None, {"MF_CONTENT_DIR": "/c"}), "/c")

    def test_flags_override_the_environment(self):
        other = os.path.join(self.root, "other-content")
        code, out, _ = self.factory("--content", other, "--state-dir",
                                    os.path.join(self.root, "s2"), "plan")
        self.assertEqual(code, 0)
        self.assertIn("(no stock folders)", out)

    def test_machine_zone(self):
        self.assertEqual(fcli.machine_zone({"TZ": "Europe/Kyiv"}), "Europe/Kyiv")
        self.assertEqual(fcli.machine_zone({"TZ": ":America/New_York"}), "America/New_York")
        self.assertTrue(fcli.machine_zone({"TZ": "../etc/passwd"}))


class PosterHelperNameTests(FactoryTestCase):
    def test_public_names_are_the_private_helpers(self):
        self.assertIs(poster_state.read_jsonl, poster_state._read_jsonl)
        self.assertIs(poster_state.append_jsonl, poster_state._append_jsonl)
        self.assertIs(poster_state.locked, poster_state._locked)

    def test_heartbeat_is_one_small_object(self):
        for i in range(3):
            fjournal.write_heartbeat(self.fstate, {"ts": str(i)})
        self.assertEqual(fjournal.read_heartbeat(self.fstate), {"ts": "2"})
        self.assertEqual(os.listdir(self.fstate), ["heartbeat.json"])
