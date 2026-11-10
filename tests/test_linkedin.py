import json

from poster import rules
from poster.http import TransportError
from tests.base import CANARIES, PLAIN, FakeTransport, PosterTestCase, make_png, resp

TOKEN = CANARIES["LINKEDIN_ACCESS_TOKEN"]
URN = PLAIN["LINKEDIN_PERSON_URN"]


class EscapeTests(PosterTestCase):
    def test_every_reserved_character(self):
        for ch in "|{}@[]()<>\\*_~":
            self.assertEqual(rules.linkedin_escape(f"a{ch}b"), f"a\\{ch}b", ch)
        self.assertEqual(rules.linkedin_escape("a # b"), "a \\# b")

    def test_hashtag_template(self):
        self.assertEqual(rules.linkedin_escape("Go #bitcoin!"), "Go {hashtag|\\#|bitcoin}!")
        self.assertEqual(rules.linkedin_escape("#криптовалюта"), "{hashtag|\\#|криптовалюта}")
        self.assertEqual(rules.linkedin_escape("#a_b"), "{hashtag|\\#|a\\_b}")


class LinkedInTests(PosterTestCase):
    def run_li(self, variant, t, name="lp"):
        return self.run_cli("publish", self.package({"linkedin": variant}, name=name),
                            "--targets", "linkedin", transport=t)

    def assert_rest_headers(self, req):
        self.assertEqual(req.headers["Authorization"], f"Bearer {TOKEN}")
        self.assertEqual(req.headers["Linkedin-Version"], "202610")
        self.assertEqual(req.headers["X-Restli-Protocol-Version"], "2.0.0")

    def test_text_post_body_headers_and_id(self):
        t = FakeTransport([resp(201, {}, {"x-restli-id": "urn:li:share:700"})])
        code, out, _ = self.run_li({"text": "Hello (world) #ai"}, t)
        self.assertEqual(code, 0, out)
        (req,) = t.requests
        self.assertEqual((req.method, req.url), ("POST", "https://api.linkedin.com/rest/posts"))
        self.assert_rest_headers(req)
        self.assertEqual(json.loads(req.body), {
            "author": URN, "commentary": "Hello \\(world\\) {hashtag|\\#|ai}", "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                             "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False})
        rec = self.records()[-1]
        self.assertEqual((rec["post_id"], rec["url"]),
                         ("urn:li:share:700", "https://www.linkedin.com/feed/update/urn:li:share:700/"))

    def test_image_flow(self):
        data = make_png(1200, 627)
        self.image("li.png", data)
        upload = "https://www.linkedin.com/dms-uploads/abc?signature=UPLOADSECRET99"
        t = FakeTransport([resp(200, {"value": {"uploadUrl": upload, "image": "urn:li:image:C1"}}),
                           resp(201, {}), resp(201, {}, {"x-restli-id": "urn:li:share:701"})])
        code, out, err = self.run_li({"text": "pic", "image": "li.png"}, t)
        self.assertEqual(code, 0, out + err)
        init, put, post = t.requests
        self.assertEqual(init.url, "https://api.linkedin.com/rest/images?action=initializeUpload")
        self.assertEqual(json.loads(init.body), {"initializeUploadRequest": {"owner": URN}})
        self.assert_rest_headers(init)
        self.assertEqual((put.method, put.url, put.body), ("PUT", upload, data))
        self.assertEqual(put.headers["Authorization"], f"Bearer {TOKEN}")
        self.assertEqual(json.loads(post.body)["content"], {"media": {"id": "urn:li:image:C1"}})
        self.assertNotIn("UPLOADSECRET99", out + err + str(self.records()))

    def test_token_only_sent_to_linkedin_hosts(self):
        self.image("li.png", make_png(10, 10))
        for bad in ("https://evil.example/upload", "http://www.linkedin.com/up",
                    "https://linkedin.com.evil.example/up"):
            with self.subTest(url=bad):
                t = FakeTransport([resp(200, {"value": {"uploadUrl": bad, "image": "urn:li:image:C"}})])
                code, out, _ = self.run_li({"text": "pic", "image": "li.png"}, t, name="b" + str(len(bad)))
                self.assertEqual((code, len(t.requests)), (1, 1))
                self.assertIn("refusing to send the token", out)

    def test_expired_token_refused_and_warning_under_7_days(self):
        self.env_values["LINKEDIN_TOKEN_EXPIRES_AT"] = "2026-11-09T10:20:00Z"   # 5 minutes left
        self.write_env(self.env_values)
        t = FakeTransport()
        code, _, err = self.run_li({"text": "a"}, t)
        self.assertEqual((code, t.requests), (2, []))
        self.assertIn("login linkedin", err)
        self.env_values["LINKEDIN_TOKEN_EXPIRES_AT"] = "2026-11-12T10:15:00Z"   # 3 days
        self.write_env(self.env_values)
        t = FakeTransport([resp(201, {}, {"x-restli-id": "urn:li:share:9"})])
        code, _, err = self.run_li({"text": "a"}, t)
        self.assertEqual(code, 0)
        self.assertIn("expires in 3 day(s)", err)

    def test_missing_token_named(self):
        for name in ("LINKEDIN_ACCESS_TOKEN", "LINKEDIN_PERSON_URN"):
            self.env_values.pop(name)
        self.write_env(self.env_values)
        code, _, err = self.run_li({"text": "a"}, FakeTransport())
        self.assertEqual(code, 2)
        self.assertIn("missing LINKEDIN_ACCESS_TOKEN, LINKEDIN_PERSON_URN", err)

    def test_401_hints_relogin_and_timeout_is_unknown(self):
        t = FakeTransport([resp(401, {"message": "Expired token", "status": 401, "serviceErrorCode": 65601})])
        code, out, _ = self.run_li({"text": "a"}, t)
        self.assertEqual(code, 1)
        self.assertIn("run: python3 -m poster login linkedin", out)
        t = FakeTransport([TransportError("network error: timeout")])
        code, out, _ = self.run_li({"text": "b"}, t, name="lp2")
        self.assertIn("UNKNOWN", out)
