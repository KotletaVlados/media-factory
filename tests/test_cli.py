import http.client
import json
import os

from poster.http import Request, TransportError, UrllibTransport
from decimal import Decimal

from poster import state
from tests.base import (CANARIES, Clock, PLAIN, FakeTransport, PosterTestCase, make_jpeg,
                        resp)

PAGE = PLAIN["FB_PAGE_KOTLETA_ID"]


def ig_success():
    return [resp(200, {"id": "PH1"}),
            resp(200, {"images": [{"width": 1080, "source": "https://cdn.invalid/a.jpg"}]}),
            resp(200, {"id": "C1"}), resp(200, {"status_code": "FINISHED"}),
            resp(200, {"id": "M1"}), resp(200, {"permalink": "https://www.instagram.com/p/OK/"}),
            resp(200, {"success": True}), resp(400, {"error": {"message": "gone", "code": 100, "error_subcode": 33}})]


class CutOffReply:
    """Opener stub: the vendor answers 201, then the body is cut off while it is read."""
    status = 201
    headers = {}

    def __init__(self, exc):
        self.exc = exc

    def open(self, request, timeout=None):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        raise self.exc


def cut_off_transport(exc):
    transport = UrllibTransport()
    transport._opener = CutOffReply(exc)
    return transport


class CutOffReplyTests(PosterTestCase):
    """A reply cut off after the request was sent may have landed: unknown, never failed."""

    def test_http_exceptions_become_transport_errors(self):
        for exc in (http.client.IncompleteRead(b"x"), http.client.BadStatusLine("zz"),
                    http.client.LineTooLong("status line")):
            with self.assertRaises(TransportError) as cm:
                cut_off_transport(exc).send(
                    Request(
                        "POST", "https://graph.facebook.com/v1/x"))
            self.assertIn(type(exc).__name__, str(cm.exception))

    def test_facebook_cut_off_is_unknown_and_next_run_is_blocked(self):
        path = self.package({"facebook": {"text": "a"}})
        code, _, _ = self.run_cli("publish", path, "--targets", "fb:kotleta",
                                  transport=cut_off_transport(http.client.IncompleteRead(b"x")))
        self.assertEqual(code, 1)
        self.assertEqual(self.records()[-1]["status"], "unknown")
        t = FakeTransport()
        code, _, err = self.run_cli("publish", path, "--targets", "fb:kotleta", transport=t)
        self.assertEqual((code, t.requests), (2, []))
        self.assertIn("ended unknown", err)

    def test_x_cut_off_is_unknown_and_reservation_stays_counted(self):
        path = self.package({"x": {"text": "a"}})
        code, _, _ = self.run_cli("publish", path, "--targets", "x",
                                  transport=cut_off_transport(http.client.IncompleteRead(b"x")))
        self.assertEqual(code, 1)
        self.assertEqual(self.records()[-1]["status"], "unknown")
        self.assertEqual([r["status"] for r in self.ledger_rows()], ["reserved"])
        t = FakeTransport()
        code, _, err = self.run_cli("publish", path, "--targets", "x", transport=t)
        self.assertEqual((code, t.requests), (2, []))
        self.assertIn("ended unknown", err)


class ServerErrorOnPublishTests(PosterTestCase):
    """A 5xx on the final publish call may have landed: unknown (needs --force-target).
    A 4xx is a definite refusal and stays failed."""

    def assert_blocked_next_run(self, path, target):
        t = FakeTransport()
        code, _, err = self.run_cli("publish", path, "--targets", target, transport=t)
        self.assertEqual((code, t.requests), (2, []))
        self.assertIn("ended unknown", err)

    def test_facebook_5xx_is_unknown_for_text_and_photo(self):
        self.image("p.jpg", make_jpeg(800, 600))
        for name, variant in (("t", {"text": "a"}), ("p", {"text": "a", "image": "p.jpg"})):
            with self.subTest(variant=name):
                path = self.package({"facebook": variant}, name="fb5-" + name)
                body = {"error": {"message": "temporarily unavailable", "code": 2}}
                code, out, _ = self.run_cli("publish", path, "--targets", "fb:kotleta",
                                            transport=FakeTransport([resp(503, body)]))
                self.assertEqual(code, 1)
                self.assertIn("UNKNOWN", out)
                self.assertIn("--force-target fb:kotleta", out)
                self.assertEqual(self.records()[-1]["status"], "unknown")
                self.assert_blocked_next_run(path, "fb:kotleta")

    def test_facebook_4xx_stays_failed_and_retries(self):
        path = self.package({"facebook": {"text": "a"}})
        code, out, _ = self.run_cli("publish", path, "--targets", "fb:kotleta",
                                    transport=FakeTransport([resp(400, {"error": {"message": "bad"}})]))
        self.assertEqual(code, 1)
        self.assertEqual(self.records()[-1]["status"], "failed")
        t = FakeTransport([resp(200, {"id": f"{PAGE}_9"})])
        code, _, _ = self.run_cli("publish", path, "--targets", "fb:kotleta", transport=t)
        self.assertEqual((code, len(t.requests)), (0, 1))

    def test_x_5xx_is_unknown_and_reservation_stays_counted(self):
        path = self.package({"x": {"text": "a"}})
        code, out, _ = self.run_cli("publish", path, "--targets", "x",
                                    transport=FakeTransport([resp(500, {"title": "Internal Server Error"})]))
        self.assertEqual(code, 1)
        self.assertIn("--force-target x", out)
        self.assertEqual(self.records()[-1]["status"], "unknown")
        self.assertEqual([r["status"] for r in self.ledger_rows()], ["reserved"])
        self.assert_blocked_next_run(path, "x")
        # still counted after a restart of the process: the ledger is read from disk
        self.assertEqual(state.Ledger(self.state_dir, Clock()).month_total(), Decimal("0.015"))

    def test_x_5xx_after_image_upload_keeps_both_reservations(self):
        self.image("x.jpg", make_jpeg(1200, 675))
        path = self.package({"x": {"text": "a", "image": "x.jpg"}}, name="x5img")
        t = FakeTransport([resp(200, {"data": {"id": "M1"}}), resp(502, {})])
        code, _, _ = self.run_cli("publish", path, "--targets", "x", transport=t)
        self.assertEqual(code, 1)
        self.assertEqual(self.records()[-1]["status"], "unknown")
        latest = {}
        for row in self.ledger_rows():
            latest[row["rid"]] = row["status"]
        self.assertEqual(sorted(latest.values()), ["ok", "reserved"])

    def test_x_4xx_stays_failed_and_releases_the_reservation(self):
        path = self.package({"x": {"text": "a"}})
        code, _, _ = self.run_cli("publish", path, "--targets", "x",
                                  transport=FakeTransport([resp(403, {"title": "Forbidden"})]))
        self.assertEqual(code, 1)
        self.assertEqual(self.records()[-1]["status"], "failed")
        self.assertEqual([r["status"] for r in self.ledger_rows()], ["reserved", "failed"])

    def test_linkedin_5xx_is_unknown_and_4xx_failed(self):
        path = self.package({"linkedin": {"text": "a"}})
        code, out, _ = self.run_cli("publish", path, "--targets", "linkedin",
                                    transport=FakeTransport([resp(500, {"message": "Internal"})]))
        self.assertEqual(code, 1)
        self.assertEqual(self.records()[-1]["status"], "unknown")
        self.assertIn("--force-target linkedin", out)
        self.assert_blocked_next_run(path, "linkedin")
        path = self.package({"linkedin": {"text": "b"}}, name="li4")
        self.run_cli("publish", path, "--targets", "linkedin",
                     transport=FakeTransport([resp(422, {"message": "bad"})]))
        self.assertEqual(self.records()[-1]["status"], "failed")

    def test_cut_off_body_variants_are_unknown_on_every_network(self):
        for exc in (http.client.IncompleteRead(b"x"), ConnectionResetError("reset"),
                    TimeoutError("timed out")):
            for target, variant in (("fb:kotleta", "facebook"), ("linkedin", "linkedin")):
                with self.subTest(exc=type(exc).__name__, target=target):
                    path = self.package({variant: {"text": "a"}}, name=f"co-{type(exc).__name__}-{variant}".lower())
                    code, out, err = self.run_cli("publish", path, "--targets", target,
                                                  transport=cut_off_transport(exc))
                    self.assertEqual(code, 1, out + err)
                    self.assertEqual(self.records()[-1]["status"], "unknown")


class CliTests(PosterTestCase):
    def setUp(self):
        super().setUp()
        self.image("sq.jpg", make_jpeg(1080, 1080))
        self.full = self.package({
            "facebook": {"text": "Long Facebook text", "image": "sq.jpg"},
            "instagram": {"text": "IG caption #a", "image": "sq.jpg"},
            "x": {"text": "Sharp quote"},
            "linkedin": {"text": "Professional angle"},
        }, name="2026-11-09-halving")

    def test_partial_failure_four_lines_exit_1_and_x_last(self):
        def ig_raises(req):
            raise RuntimeError("instagram exploded")
        t = FakeTransport([resp(200, {"id": "P1", "post_id": f"{PAGE}_1"}),
                           ig_raises,
                           resp(201, {}, {"x-restli-id": "urn:li:share:1"}),
                           resp(201, {"data": {"id": "77"}})])
        code, out, err = self.run_cli("publish", self.full, "--profile", "kotleta", transport=t)
        self.assertEqual(code, 1)
        hosts = [r.url.split("/")[2] for r in t.requests]
        self.assertEqual(hosts, ["graph.facebook.com", "graph.facebook.com", "api.linkedin.com", "api.x.com"])
        lines = [l for l in out.splitlines() if l.startswith("  ") and not l.startswith("    ")]
        self.assertEqual(len(lines), 4, out)
        self.assertIn("fb:kotleta  published", lines[0])
        self.assertIn("ig:kotleta  FAILED", lines[1])
        self.assertIn("RuntimeError: instagram exploded", lines[1])
        self.assertIn("linkedin    published", lines[2])
        self.assertIn("x           published", lines[3])
        self.assertTrue(out.rstrip().endswith("exit 1"))
        recs = self.records()
        self.assertEqual([(r["target"], r["status"]) for r in recs],
                         [("fb:kotleta", "published"), ("ig:kotleta", "failed"),
                          ("linkedin", "published"), ("x", "published")])

        # re-run: published targets skipped, failed Instagram retried alone
        t2 = FakeTransport(ig_success())
        code, out, _ = self.run_cli("publish", self.full, "--profile", "kotleta", transport=t2)
        self.assertEqual(code, 0, out)
        self.assertTrue(all(r.url.startswith("https://graph.facebook.com/") for r in t2.requests))
        self.assertIn("fb:kotleta  already published", out)
        self.assertEqual(out.count("already published"), 3)
        self.assertEqual(self.records()[-1]["status"], "published")

    def test_unknown_blocks_without_force_target(self):
        path = self.package({"facebook": {"text": "a"}})
        self.run_cli("publish", path, "--targets", "fb:kotleta",
                     transport=FakeTransport([TransportError("network error: timeout")]))
        self.assertEqual(self.records()[-1]["status"], "unknown")
        t = FakeTransport()
        code, _, err = self.run_cli("publish", path, "--targets", "fb:kotleta", transport=t)
        self.assertEqual((code, t.requests), (2, []))
        self.assertIn("ended unknown", err)
        t = FakeTransport([resp(200, {"id": "1_9"})])
        code, out, _ = self.run_cli("publish", path, "--targets", "fb:kotleta", "--force-target", "fb:kotleta", transport=t)
        self.assertEqual(code, 0, out)
        code, _, err = self.run_cli("publish", path, "--targets", "fb:kotleta", "--force-target", "x")
        self.assertEqual(code, 2)

    def test_preflight_failure_on_one_variant_sends_nothing(self):
        path = self.package({"facebook": {"text": "fine"}, "x": {"text": "y" * 300},
                             "instagram": {"text": "no image"}})
        t = FakeTransport()
        code, out, err = self.run_cli("publish", path, "--profile", "kotleta", transport=t)
        self.assertEqual((code, t.requests), (2, []))
        self.assertIn("x: text is 300 weighted characters, X allows 280", err)
        self.assertIn("ig:kotleta: Instagram needs an image", err)
        self.assertEqual(self.records(), [])
        self.assertFalse(os.path.exists(os.path.join(self.state_dir, "x-ledger.jsonl")))

    def test_skipped_and_unused_variants(self):
        path = self.package({"facebook": {"text": "a"}, "linkedin": {"text": "unused"}})
        t = FakeTransport([resp(200, {"id": "1_1"})])
        code, out, err = self.run_cli("publish", path, "--targets", "fb:kotleta,x", transport=t)
        self.assertEqual(code, 0)
        self.assertIn("x           skipped  (no variant)", out)
        self.assertIn("unused variant: linkedin", err)

    def test_dry_run_sends_nothing_writes_nothing_and_shows_everything(self):
        self.assertFalse(os.path.exists(self.state_dir))
        t = FakeTransport()
        code, out, err = self.run_cli("publish", self.full, "--profile", "kotleta", "--dry-run", transport=t)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(t.requests, [])
        self.assertFalse(os.path.exists(self.state_dir))
        for text in ("Long Facebook text", "IG caption #a", "Sharp quote", "Professional angle"):
            self.assertIn(f"| {text}", out)
        self.assertIn("image sq.jpg: jpeg 1080x1080", out)
        self.assertIn("weighted 11/280", out)
        self.assertIn("caption 13/2200", out)
        self.assertIn("X estimate $0.015 (post $0.015); month 2026-11 so far $0.000 of $5.00", out)
        self.assertIn(f"POST https://graph.facebook.com/v27.0/{PAGE}/photos", out)
        self.assertIn("access_token = [redacted]", out)
        self.assertIn("header Authorization: [redacted]", out)
        self.assertIn("POST https://api.linkedin.com/rest/posts", out)
        self.assertIn("POST https://api.x.com/2/tweets", out)
        self.assertIn("published = false", out)
        self.assertIn("would publish", out)
        self.assertIn("image: none (text-only)", out)

    def test_dry_run_x_image_shows_base64_placeholder_and_still_refuses_over_cap(self):
        path = self.package({"x": {"text": "pic", "image": "sq.jpg"}})
        code, out, _ = self.run_cli("publish", path, "--targets", "x", "--dry-run")
        self.assertEqual(code, 0)
        self.assertRegex(out, r"<base64 of \d+ bytes from sq.jpg \(jpeg 1080x1080")
        self.assertIn("X estimate $0.215", out)
        self.env_values["X_MONTHLY_CAP_USD"] = "0.10"
        self.write_env(self.env_values)
        code, _, err = self.run_cli("publish", path, "--targets", "x", "--dry-run")
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.state_dir))

    def test_records_and_status(self):
        path = self.package({"facebook": {"text": "a"}, "x": {"text": "b"}})
        self.run_cli("publish", path, "--targets", "fb:kotleta,x",
                     transport=FakeTransport([resp(200, {"id": "1_5"}), resp(201, {"data": {"id": "8"}})]))
        code, out, _ = self.run_cli("records", "--last", "5")
        self.assertEqual(code, 0)
        self.assertIn("2026-11-09T10:15:00Z  pkg-1  fb:kotleta  published  1_5  https://www.facebook.com/1_5", out)
        self.assertIn("x  published  8  https://x.com/i/web/status/8", out)
        code, out, _ = self.run_cli("records", "--package", "nope")
        self.assertIn("no records", out)
        code, out, _ = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertIn("X 2026-11: spent $0.015 of $5.00, remaining $4.985", out)
        self.assertIn("worst case left: 23 image posts ($0.215 each)", out)
        self.assertIn("or 332 text-only posts", out)
        self.assertIn("LinkedIn token: 56 day(s) left", out)
        self.assertIn("fb:kotleta   ready", out)
        self.assertIn("profiles: kotleta = fb:kotleta, ig:kotleta, linkedin, x", out)

    def test_status_does_not_create_state(self):
        code, out, _ = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertIn("spent $0.000 of $5.00", out)
        self.assertIn("worst case left: 23 image posts", out)
        self.assertIn("or 333 text-only posts", out)
        self.assertFalse(os.path.exists(self.state_dir))

    def test_usage_errors(self):
        self.assertEqual(self.run_cli("publish", self.full)[0], 2)   # no --profile/--targets
        self.assertEqual(self.run_cli("publish", self.full, "--profile", "nobody")[0], 2)
        self.assertEqual(self.run_cli("publish", self.full, "--targets", "tiktok")[0], 2)
        code, _, err = self.run_cli("--env-file", os.path.join(self.root, "missing.env"), "status")
        self.assertEqual(code, 2)
        self.assertIn("env file not found", err)

    def test_secrets_in_env_with_malformed_line(self):
        self.write_env(self.env_values, extra="oops " + CANARIES["X_API_SECRET"] + "\n")
        code, _, err = self.run_cli("status")
        self.assertEqual(code, 2)
        self.assertIn("malformed line", err)

    def test_record_files_are_private_and_hold_no_secrets(self):
        path = self.package({"facebook": {"text": "a"}, "x": {"text": "b"}})
        self.run_cli("publish", path, "--targets", "fb:kotleta,x",
                     transport=FakeTransport([resp(200, {"id": "1_5"}), resp(201, {"data": {"id": "8"}})]))
        self.assertEqual(oct(os.stat(self.state_dir).st_mode & 0o777), "0o700")
        for name in os.listdir(self.state_dir):
            self.assertEqual(oct(os.stat(os.path.join(self.state_dir, name)).st_mode & 0o777), "0o600", name)
        rows = self.records()
        self.assertEqual(rows[0], {"ts": "2026-11-09T10:15:00Z", "package": "pkg-1", "target": "fb:kotleta",
                                   "network": "facebook", "status": "published", "post_id": "1_5",
                                   "url": "https://www.facebook.com/1_5"})


class CheckStagingTests(PosterTestCase):
    def test_check_staging_flow_publishes_nothing(self):
        jpg = self.image("s.jpg", make_jpeg(1080, 1080))
        cdn = "https://scontent.cdn.invalid/x.jpg?sig=CDNSIGNATURE1234"
        old = {"id": f"{PLAIN['FB_PAGE_DEMO_ID']}_1"}
        t = FakeTransport([resp(200, {"data": [old]}), resp(200, {"id": "PH9"}),
                           resp(200, {"images": [{"width": 1080, "source": cdn}]}),
                           resp(200, {}, {"Content-Type": "image/jpeg"}, body=b"\xff\xd8\xff" + b"0" * 100),
                           resp(200, {"data": [old]}),
                           resp(200, {"success": True}), resp(400, {"error": {"message": "gone", "code": 100, "error_subcode": 33}})])
        code, out, err = self.run_cli("check-staging", "--page", "demo", jpg, transport=t)
        self.assertEqual(code, 0, out + err)
        anon = t.requests[3]
        self.assertEqual((anon.method, anon.headers, anon.anonymous), ("GET", {}, True))
        self.assertIn("host scontent.cdn.invalid", out)
        self.assertIn("200, image/jpeg, 103 bytes -> OK", out)
        self.assertIn("absent from the Page's published posts (last 10): yes", out)
        self.assertNotIn("CDNSIGNATURE", out + err)
        self.assertFalse(any("media_publish" in r.url for r in t.requests))
        self.assertIn("check-staging PASSED", out)

    def test_check_staging_with_container_never_publishes_and_fails_on_png_cdn(self):
        jpg = self.image("s.jpg", make_jpeg(1080, 1080))
        t = FakeTransport([resp(200, {"data": []}), resp(200, {"id": "PH9"}),
                           resp(200, {"images": [{"width": 1080, "source": "https://cdn.invalid/a"}]}),
                           resp(200, {}, {"Content-Type": "image/png"}, body=b"png"),
                           resp(200, {"data": []}),
                           resp(200, {"id": "C5"}), resp(200, {"status_code": "FINISHED"}),
                           resp(200, {"success": True}), resp(400, {"error": {"message": "gone", "code": 100, "error_subcode": 33}})])
        code, out, err = self.run_cli("check-staging", "--page", "kotleta", jpg, "--ig-container", "ig:kotleta",
                                      transport=t)
        self.assertEqual(code, 1)
        self.assertIn("NOT OK", out)
        self.assertIn("container FINISHED", out)
        self.assertFalse(any("media_publish" in r.url for r in t.requests))
        self.assertIn("deleted (read-back confirms)", out)


class CheckStagingStep3Tests(PosterTestCase):
    PAGE = PLAIN["FB_PAGE_DEMO_ID"]

    def script(self, step3, before=None, staged=None, read_back=None):
        return FakeTransport([
            before or resp(200, {"data": [{"id": f"{self.PAGE}_OLD"}]}),
            resp(200, staged or {"id": "PH9"}),
            resp(200, {"images": [{"width": 1080, "source": "https://cdn.invalid/a"}]}),
            resp(200, {}, {"Content-Type": "image/jpeg"}, body=b"\xff\xd8\xff"),
            step3,
            resp(200, {"success": True}),
            read_back or resp(400, {"error": {"message": "gone", "code": 100, "error_subcode": 33}})])

    def check(self, transport):
        jpg = self.image("s.jpg", make_jpeg(1080, 1080))
        return self.run_cli("check-staging", "--page", "demo", jpg, transport=transport)

    def test_step_3_reads_published_posts_not_feed(self):
        t = self.script(resp(200, {"data": [{"id": f"{self.PAGE}_OLD"}]}))
        code, out, err = self.check(t)
        self.assertEqual(code, 0, out + err)
        for i in (0, 4):   # the listing before staging and the one after it
            edge = t.requests[i].url.split("?")[0]
            self.assertTrue(edge.endswith(f"/{self.PAGE}/published_posts"), edge)
        self.assertFalse(any("/feed" in r.url for r in t.requests))
        self.assertIn("(last 10): yes", out)

    def test_step_3_4xx_is_unreadable_with_its_code_never_no(self):
        body = {"error": {"message": "(#10) needs pages_read_engagement", "code": 10}}
        code, out, err = self.check(self.script(resp(400, body)))
        self.assertEqual(code, 1)
        self.assertIn("(last 10): unreadable (HTTP 400, code 10)", out)
        self.assertNotIn("): NO", out)
        self.assertIn("check-staging FAILED", out)
        self.assertIn("deleted (read-back confirms)", out)

    def test_step_3_unreadable_before_listing_is_unreadable_too(self):
        body = {"error": {"message": "x", "code": 10}}
        code, out, _ = self.check(self.script(resp(200, {"data": []}), before=resp(400, body)))
        self.assertEqual(code, 1)
        self.assertIn("(last 10): unreadable (HTTP 400, code 10)", out)

    def test_step_3_a_new_post_id_prints_no(self):
        # a published photo is listed under its post id, which differs from the photo id
        new = resp(200, {"data": [{"id": f"{self.PAGE}_9999"}, {"id": f"{self.PAGE}_OLD"}]})
        code, out, _ = self.check(self.script(new))
        self.assertEqual(code, 1)
        self.assertIn(f"(last 10): NO (new post {self.PAGE}_9999)", out)
        self.assertIn("check-staging FAILED", out)

    def test_step_3_an_upload_answer_with_post_id_prints_no(self):
        code, out, _ = self.check(self.script(resp(200, {"data": [{"id": f"{self.PAGE}_OLD"}]}),
                                              staged={"id": "PH9", "post_id": f"{self.PAGE}_7"}))
        self.assertEqual(code, 1)
        self.assertIn(f"NO (new post {self.PAGE}_7)", out)

    def test_cleanup_read_back_code_10_is_not_confirmed(self):
        # the staging photo has no pre-read, so only 404 / code 100 subcode 33 count as gone
        code, out, err = self.check(self.script(resp(200, {"data": [{"id": f"{self.PAGE}_OLD"}]}),
                                                read_back=resp(400, {"error": {"message": "x", "code": 10}})))
        self.assertEqual(code, 1)
        self.assertIn("deletion not confirmed", out)
        self.assertIn("HTTP 400, code 10", out)


class ArgumentValidationTests(PosterTestCase):
    def test_bad_numbers_rejected_without_traceback(self):
        for argv in (["login", "linkedin", "--timeout", "nan"], ["login", "linkedin", "--timeout", "inf"],
                     ["login", "linkedin", "--timeout", "-1"], ["login", "linkedin", "--port", "99999999"],
                     ["login", "linkedin", "--port", "x"], ["records", "--last", "-5"],
                     ["records", "--last", "0"], ["records", "--last", "9" * 400]):
            with self.subTest(argv=argv):
                code, out, err = self.run_cli(*argv)
                self.assertEqual(code, 2)
                self.assertNotIn("Traceback", out + err)
                self.assertIn("error:", err)

    def test_wrong_json_types_in_package(self):
        path = self.package({"x": {"text": ["list"], "image": {"a": 1}}})
        code, _, err = self.run_cli("publish", path, "--targets", "x")
        self.assertEqual(code, 2)
        self.assertIn("text is required", err)
        path = self.package({"x": {"text": "a"}}, name="huge", id=10 ** 400)
        code, _, err = self.run_cli("publish", path, "--targets", "x")
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)


class DryRunLayoutTests(PosterTestCase):
    def test_multiline_field_values_stay_indented(self):
        path = self.package({"facebook": {"text": "line one\nline two"}})
        code, out, _ = self.run_cli("publish", path, "--targets", "fb:kotleta", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("        message = line one\n                  line two\n", out)
