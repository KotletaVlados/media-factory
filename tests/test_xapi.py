import base64
import datetime as dt
import json
import os
import subprocess
import sys
from decimal import Decimal

from poster import config, state, xapi
from poster.http import TransportError
from tests.base import (CANARIES, FROZEN_NOW, SUBPROCESS_PREFIX, Clock, FakeTransport, PosterTestCase,
                        isolated_subprocess_env, make_jpeg, resp)


class XTests(PosterTestCase):
    def run_x(self, variant, t, name="xp"):
        return self.run_cli("publish", self.package({"x": variant}, name=name), "--targets", "x", transport=t)

    def test_text_post_body_and_oauth_header(self):
        t = FakeTransport([resp(201, {"data": {"id": "1850"}})])
        code, out, err = self.run_x({"text": "Короткий пост"}, t)
        self.assertEqual(code, 0, out + err)
        (req,) = t.requests
        self.assertEqual((req.method, req.url), ("POST", "https://api.x.com/2/tweets"))
        self.assertEqual(json.loads(req.body), {"text": "Короткий пост"})
        auth = req.headers["Authorization"]
        self.assertTrue(auth.startswith("OAuth "))
        self.assertIn(f'oauth_consumer_key="{CANARIES["X_API_KEY"]}"', auth)
        self.assertIn(f'oauth_token="{CANARIES["X_ACCESS_TOKEN"]}"', auth)
        self.assertIn("https://x.com/i/web/status/1850", out)
        self.assertIn("X month $0.015 of $5.00", out)
        rows = self.ledger_rows()
        self.assertEqual([r["status"] for r in rows], ["reserved", "ok"])
        self.assertEqual((rows[0]["op"], rows[0]["price"], rows[0]["month"]), ("post", "0.015", "2026-11"))

    def test_image_upload_then_post_with_media_ids(self):
        data = make_jpeg(1200, 675)
        self.image("x.jpg", data)
        t = FakeTransport([resp(200, {"data": {"id": "M77", "media_key": "3_M77"}}),
                           resp(201, {"data": {"id": "1851"}})])
        code, out, _ = self.run_x({"text": "pic", "image": "x.jpg"}, t)
        self.assertEqual(code, 0)
        up, post = t.requests
        self.assertEqual(up.url, "https://api.x.com/2/media/upload")
        self.assertEqual(json.loads(up.body), {"media": base64.b64encode(data).decode(),
                                               "media_category": "tweet_image"})
        self.assertTrue(up.headers["Authorization"].startswith("OAuth "))
        self.assertEqual(json.loads(post.body), {"text": "pic", "media": {"media_ids": ["M77"]}})
        self.assertIn("X month $0.215 of $5.00", out)
        ops = [(r.get("op"), r["status"]) for r in self.ledger_rows()]
        self.assertEqual(ops, [("media_upload", "reserved"), ("post_with_media", "reserved"),
                               (None, "ok"), (None, "ok")])

    def test_price_classification(self):
        s = config.load_settings({})
        self.assertEqual(xapi.estimate("text", False, s), Decimal("0.015"))
        self.assertEqual(xapi.estimate("see https://a.co", False, s), Decimal("0.200"))
        self.assertEqual(xapi.estimate("see example.com", False, s), Decimal("0.200"))
        self.assertEqual(xapi.estimate("pic", True, s), Decimal("0.215"))
        self.assertEqual(xapi.estimate("pic https://a.co", True, s), Decimal("0.215"))
        s = config.load_settings({"X_PRICE_POST_WITH_MEDIA": "0.015", "X_PRICE_MEDIA_UPLOAD": "0"})
        self.assertEqual(xapi.estimate("pic", True, s), Decimal("0.015"))

    def seed_ledger(self, total: str, month_clock=None):
        ledger = state.Ledger(self.state_dir, month_clock or self.clock)
        ledger.reserve([("post", Decimal(total))], "seed", Decimal("1000"))

    def test_over_cap_refused_before_any_request(self):
        self.seed_ledger("4.90")
        t = FakeTransport()
        code, out, err = self.run_x({"text": "see https://a.co"}, t)   # 0.200 > 0.10 left
        self.assertEqual((code, t.requests), (2, []))
        self.assertIn("would cost $0.200", err)
        self.assertIn("total is $4.900", err)
        self.assertIn("ask the operator", err.lower())
        self.assertEqual(len(self.ledger_rows()), 1)   # nothing reserved
        # exactly at the cap is allowed
        t = FakeTransport([resp(201, {"data": {"id": "9"}})])
        self.seed_ledger("0.085")
        code, out, _ = self.run_x({"text": "plain"}, t, name="xp2")
        self.assertEqual(code, 0, out)
        self.assertIn("X month $5.000 of $5.00", out)

    def test_over_cap_blocks_whole_package(self):
        self.seed_ledger("5.00")
        t = FakeTransport()
        path = self.package({"facebook": {"text": "fb"}, "x": {"text": "x"}})
        code, _, err = self.run_cli("publish", path, "--targets", "fb:kotleta,x", transport=t)
        self.assertEqual((code, t.requests), (2, []))
        self.assertIn("nothing was sent", err)

    def test_reservation_written_before_send(self):
        seen = []

        def check_ledger(req):
            seen.append([r["status"] for r in self.ledger_rows()])
            return resp(201, {"data": {"id": "5"}})
        self.run_x({"text": "a"}, FakeTransport([check_ledger]))
        self.assertEqual(seen, [["reserved"]])

    def test_definite_error_is_excluded_and_timeout_stays_counted(self):
        t = FakeTransport([resp(403, {"title": "Forbidden", "detail": "not allowed", "type": "about:blank"})])
        code, out, _ = self.run_x({"text": "a"}, t)
        self.assertEqual(code, 1)
        self.assertIn("403 X create post: Forbidden; not allowed", out)
        self.assertEqual(state.Ledger(self.state_dir, self.clock).month_total(), Decimal("0"))
        t = FakeTransport([TransportError("network error: timeout")])
        code, out, _ = self.run_x({"text": "b"}, t, name="xp3")
        self.assertEqual(code, 1)
        self.assertIn("UNKNOWN", out)
        self.assertEqual(state.Ledger(self.state_dir, self.clock).month_total(), Decimal("0.015"))
        self.assertEqual(self.records()[-1]["status"], "unknown")

    def test_upload_failure_settles_both_and_posts_nothing(self):
        self.image("x.jpg", make_jpeg(100, 100))
        t = FakeTransport([resp(400, {"title": "Bad media"})])
        code, out, _ = self.run_x({"text": "a", "image": "x.jpg"}, t)
        self.assertEqual((code, len(t.requests)), (1, 1))
        self.assertEqual(state.Ledger(self.state_dir, self.clock).month_total(), Decimal("0"))
        t = FakeTransport([TransportError("network error: timeout")])
        code, out, _ = self.run_x({"text": "a", "image": "x.jpg"}, t, name="xp4")
        self.assertEqual((code, len(t.requests)), (1, 1))
        self.assertIn("FAILED", out)
        # the upload may have been billed: stays counted; the post was never sent
        self.assertEqual(state.Ledger(self.state_dir, self.clock).month_total(), Decimal("0.015"))
        t = FakeTransport([resp(200, {"data": {"id": "M", "processing_info": {"state": "pending"}}})])
        code, out, _ = self.run_x({"text": "a", "image": "x.jpg"}, t, name="xp5")
        self.assertEqual((code, len(t.requests)), (1, 1))
        self.assertIn("still processing", out)

    def test_month_rollover_at_utc_midnight(self):
        late = Clock(dt.datetime(2026, 11, 30, 23, 59, 59, tzinfo=dt.timezone.utc))
        state.Ledger(self.state_dir, late).reserve([("post", Decimal("5.00"))], "s", Decimal("5"))
        self.clock.now = late.now
        t = FakeTransport()
        code, _, _ = self.run_x({"text": "a"}, t)
        self.assertEqual((code, t.requests), (2, []))
        self.clock.now = dt.datetime(2026, 12, 1, 0, 0, 0, tzinfo=dt.timezone.utc)
        t = FakeTransport([resp(201, {"data": {"id": "6"}})])
        code, out, _ = self.run_x({"text": "a"}, t, name="xp6")
        self.assertEqual(code, 0)
        self.assertIn("X month $0.015", out)

    def test_cap_and_prices_from_env(self):
        self.env_values.update({"X_MONTHLY_CAP_USD": "0.01", "X_PRICE_POST": "0.02"})
        self.write_env(self.env_values)
        t = FakeTransport()
        code, _, err = self.run_x({"text": "a"}, t)
        self.assertEqual((code, t.requests), (2, []))
        self.assertIn("would cost $0.020", err)
        self.assertIn("cap is $0.01", err)


class LedgerProcessTests(PosterTestCase):
    """The ledger lives on disk: a fresh process sees it, and parallel processes never
    overspend together."""

    def run_process(self, *argv):
        return subprocess.run(SUBPROCESS_PREFIX + list(argv), capture_output=True, text=True,
                              env=isolated_subprocess_env(self), cwd=self.root, timeout=60)

    def test_spend_survives_a_process_restart(self):
        # the child process runs on the same frozen clock (SUBPROCESS_PREFIX)
        state.Ledger(self.state_dir, Clock(FROZEN_NOW)).reserve([("post", Decimal("4.95"))], "s", Decimal("5"))
        p = self.run_process("status")
        self.outputs += [p.stdout, p.stderr]
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("spent $4.950 of $5.00", p.stdout)
        pkg = self.package({"x": {"text": "see https://a.co"}})
        p = self.run_process("publish", pkg, "--targets", "x", "--dry-run")
        self.outputs += [p.stdout, p.stderr]
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("would cost $0.200", p.stderr)

    def test_parallel_processes_respect_the_cap(self):
        script = (
            "import sys, datetime as dt; from decimal import Decimal\n"
            f"sys.path.insert(0, {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))!r})\n"
            "from poster import state\n"
            "clock = lambda: dt.datetime(2026, 11, 9, tzinfo=dt.timezone.utc)\n"
            "l = state.Ledger(sys.argv[1], clock)\n"
            "ok = 0\n"
            "for i in range(10):\n"
            "    try:\n"
            "        l.reserve([('post', Decimal('0.20'))], 'p', Decimal('5.00')); ok += 1\n"
            "    except state.BudgetExceeded:\n"
            "        pass\n"
            "print(ok)\n")
        procs = [subprocess.Popen([sys.executable, "-I", "-B", "-c", script, self.state_dir],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(6)]
        counts = []
        for p in procs:
            out, err = p.communicate(timeout=60)
            self.assertEqual(p.returncode, 0, err)
            counts.append(int(out.strip()))
        self.assertEqual(sum(counts), 25)    # 25 x 0.20 = 5.00 exactly, 60 attempts
        clock = Clock(dt.datetime(2026, 11, 9, tzinfo=dt.timezone.utc))
        self.assertEqual(state.Ledger(self.state_dir, clock).month_total(), Decimal("5.00"))
