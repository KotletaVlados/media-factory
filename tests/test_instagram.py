import urllib.parse

from poster.http import TransportError
from tests.base import CANARIES, PLAIN, FakeTransport, PosterTestCase, make_jpeg, make_png, resp

PAGE = PLAIN["FB_PAGE_KOTLETA_ID"]
IG = PLAIN["IG_KOTLETA_USER_ID"]
TOKEN = CANARIES["FB_PAGE_KOTLETA_TOKEN"]
CDN = "https://scontent.example-cdn.invalid/v/t39/abc.jpg?_nc_sig=SECRETSIG123456"
V = "https://graph.facebook.com/v27.0"


def form(req):
    return urllib.parse.parse_qs(req.body.decode())


class InstagramTests(PosterTestCase):
    def setUp(self):
        super().setUp()
        self.image("sq.jpg", make_jpeg(1080, 1080))
        self.pkg = self.package({"instagram": {"text": "Caption #bitcoin", "image": "sq.jpg"}})

    def staging(self):
        return [resp(200, {"id": "PH1"}),
                resp(200, {"images": [{"width": 720, "height": 720, "source": "https://small.invalid/s.jpg"},
                                      {"width": 1080, "height": 1080, "source": CDN}]})]

    def cleanup_ok(self):
        return [resp(200, {"success": True}), resp(400, {"error": {"message": "gone", "code": 100, "error_subcode": 33}})]

    def run_ig(self, t):
        return self.run_cli("publish", self.pkg, "--targets", "ig:kotleta", transport=t)

    def test_happy_path_sequence_and_fields(self):
        t = FakeTransport(self.staging() + [
            resp(200, {"id": "C1"}),
            resp(200, {"status_code": "IN_PROGRESS"}),
            resp(200, {"status_code": "FINISHED"}),
            resp(200, {"id": "M1"}),
            resp(200, {"permalink": "https://www.instagram.com/p/ABC/"}),
        ] + self.cleanup_ok())
        code, out, err = self.run_ig(t)
        self.assertEqual(code, 0, out + err)
        r = t.requests
        self.assertEqual((r[0].method, r[0].url), ("POST", f"{V}/{PAGE}/photos"))
        self.assertIn(b'name="published"\r\n\r\nfalse', r[0].body)
        self.assertIn(b'name="source"; filename="sq.jpg"', r[0].body)
        self.assertTrue(r[1].url.startswith(f"{V}/PH1?fields=images"))
        self.assertEqual(r[2].url, f"{V}/{IG}/media")
        self.assertEqual(form(r[2]), {"image_url": [CDN], "caption": ["Caption #bitcoin"], "access_token": [TOKEN]})
        self.assertIn("fields=status_code%2Cstatus", r[3].url)
        self.assertEqual(r[5].url, f"{V}/{IG}/media_publish")
        self.assertEqual(form(r[5]), {"creation_id": ["C1"], "access_token": [TOKEN]})
        self.assertIn("M1?fields=permalink", r[6].url)
        self.assertEqual(r[7].method, "DELETE")
        self.assertTrue(r[7].url.startswith(f"{V}/PH1?"))
        self.assertEqual(r[8].method, "GET")
        self.assertEqual(self.sleeps, [60])
        self.assertIn("https://www.instagram.com/p/ABC/", out)
        self.assertIn("staging photo removed", out)
        self.assertNotIn("SECRETSIG", out + err)
        rec = self.records()[-1]
        self.assertEqual(rec["extra"], {"staging_photo_id": "PH1", "cleanup": "deleted"})
        self.assertNotIn("SECRETSIG", str(rec))

    def assert_failed_with_cleanup(self, t, sleeps=None):
        code, out, err = self.run_ig(t)
        self.assertEqual(code, 1)
        self.assertIn("FAILED", out)
        deletes = [q for q in t.requests if q.method == "DELETE"]
        self.assertEqual(len(deletes), 1)
        self.assertTrue(deletes[0].url.startswith(f"{V}/PH1?"))
        self.assertEqual(self.records()[-1]["extra"]["cleanup"], "deleted")
        if sleeps is not None:
            self.assertEqual(self.sleeps, sleeps)
        self.assertEqual(t.queue, [])
        return out + err

    def test_error_and_expired_fail_and_clean_up(self):
        for code in ("ERROR", "EXPIRED"):
            with self.subTest(code=code):
                self.sleeps.clear()
                t = FakeTransport(self.staging() + [resp(200, {"id": "C1"}),
                                                    resp(200, {"status_code": code, "status": "bad image"})]
                                  + self.cleanup_ok())
                text = self.assert_failed_with_cleanup(t, sleeps=[])
                self.assertIn(f"Instagram container {code}", text)

    def test_five_minute_timeout(self):
        t = FakeTransport(self.staging() + [resp(200, {"id": "C1"})]
                          + [resp(200, {"status_code": "IN_PROGRESS"})] * 6 + self.cleanup_ok())
        text = self.assert_failed_with_cleanup(t, sleeps=[60] * 5)
        self.assertIn("not FINISHED after 5 minutes", text)

    def test_failures_after_staging_all_clean_up(self):
        scripts = {
            "images": [resp(200, {"id": "PH1"}), resp(500, {"error": {"message": "x"}})],
            "container": self.staging() + [resp(400, {"error": {"message": "bad url"}})],
            "publish": self.staging() + [resp(200, {"id": "C1"}), resp(200, {"status_code": "FINISHED"}),
                                         resp(400, {"error": {"message": "nope"}})],
            "network": self.staging() + [TransportError("network error: timeout")],
        }
        for name, script in scripts.items():
            with self.subTest(step=name):
                t = FakeTransport(script + self.cleanup_ok())
                self.assert_failed_with_cleanup(t)

    def test_publish_timeout_is_unknown_and_still_cleans_up(self):
        t = FakeTransport(self.staging() + [resp(200, {"id": "C1"}), resp(200, {"status_code": "FINISHED"}),
                                            TransportError("network error: timeout")] + self.cleanup_ok())
        code, out, _ = self.run_ig(t)
        self.assertEqual(code, 1)
        self.assertIn("UNKNOWN", out)
        self.assertIn("--force-target ig:kotleta", out)
        rec = self.records()[-1]
        self.assertEqual((rec["status"], rec["extra"]["cleanup"]), ("unknown", "deleted"))

    def test_publish_5xx_is_unknown_and_4xx_failed_and_both_clean_up(self):
        for status, expect in ((502, "unknown"), (400, "failed")):
            with self.subTest(http=status):
                t = FakeTransport(self.staging() + [resp(200, {"id": "C1"}), resp(200, {"status_code": "FINISHED"}),
                                                    resp(status, {"error": {"message": "x"}})] + self.cleanup_ok())
                # the 502 run leaves the target unknown; the 4xx run is forced past that guard
                force = ["--force-target", "ig:kotleta"] if status == 400 else []
                code, out, _ = self.run_cli("publish", self.pkg, "--targets", "ig:kotleta", *force, transport=t)
                self.assertEqual(code, 1)
                rec = self.records()[-1]
                self.assertEqual((rec["status"], rec["extra"]["cleanup"]), (expect, "deleted"))
                if expect == "unknown":
                    self.assertIn("--force-target ig:kotleta", out)

    def test_staging_failure_sends_no_cleanup(self):
        t = FakeTransport([resp(400, {"error": {"message": "upload refused"}})])
        code, out, _ = self.run_ig(t)
        self.assertEqual((code, len(t.requests)), (1, 1))
        self.assertNotIn("cleanup", self.records()[-1].get("extra", {}))

    def test_cleanup_failure_recorded_and_reported(self):
        t = FakeTransport(self.staging() + [resp(200, {"id": "C1"}), resp(200, {"status_code": "FINISHED"}),
                                            resp(200, {"id": "M1"}), resp(200, {"permalink": "https://www.instagram.com/p/Z/"}),
                                            resp(500, {"error": {"message": "temporary"}})])
        code, out, err = self.run_ig(t)
        self.assertEqual(code, 0)   # the post itself is published
        self.assertIn("staging photo PH1 was not removed", err)
        self.assertIn("24 hours", err)
        self.assertEqual(self.records()[-1]["extra"], {"staging_photo_id": "PH1", "cleanup": "failed"})

    def test_config_issue_warning(self):
        t = FakeTransport(self.staging() + [resp(200, {"id": "C1"}), resp(200, {"status_code": "FINISHED"}),
                                            resp(200, {"id": "M1", "config_issue": "CAPTION_NOT_ATTACHED"}),
                                            resp(200, {"permalink": "https://www.instagram.com/p/Z/"})]
                          + self.cleanup_ok())
        code, out, err = self.run_ig(t)
        self.assertEqual(code, 0)
        self.assertIn("CAPTION_NOT_ATTACHED", err)

    def test_text_only_and_png_refused_before_any_call(self):
        self.image("p.png", make_png(1080, 1080))
        for variant, msg in (({"text": "only text"}, "Instagram needs an image"),
                             ({"text": "png", "image": "p.png"}, "instagram accepts jpeg")):
            with self.subTest(msg=msg):
                t = FakeTransport()
                code, _, err = self.run_cli("publish", self.package({"instagram": variant}, name="p2"),
                                            "--targets", "ig:kotleta", transport=t)
                self.assertEqual((code, t.requests), (2, []))
                self.assertIn(msg, err)
