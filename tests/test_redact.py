import io
import urllib.parse

from poster import cli
from poster.redact import Redactor, is_secret_name
from tests.base import CANARIES, PosterTestCase, FakeTransport


class RedactTests(PosterTestCase):
    def setUp(self):
        super().setUp()
        self.r = Redactor()
        self.r.add_env(self.env_values)

    def test_registry_names(self):
        self.assertTrue(is_secret_name("FB_PAGE_KOTLETA_TOKEN"))
        self.assertTrue(is_secret_name("X_API_KEY"))
        self.assertTrue(is_secret_name("LINKEDIN_CLIENT_SECRET"))
        self.assertFalse(is_secret_name("LINKEDIN_TOKEN_EXPIRES_AT"))
        self.assertFalse(is_secret_name("FB_PAGE_KOTLETA_ID"))

    def test_raw_and_percent_encoded_forms(self):
        for name, value in CANARIES.items():
            for form in (value, urllib.parse.quote(value, safe=""), urllib.parse.quote_plus(value)):
                text = self.r.redact(f"boom: {form} end")
                self.assertNotIn(value, text)
                self.assertNotIn(form, text)
                self.assertIn(f"[redacted:{name}]", text)

    def test_urls_headers_and_bodies(self):
        tok = CANARIES["FB_PAGE_DEMO_TOKEN"]
        url = "https://graph.facebook.com/v27.0/1?" + urllib.parse.urlencode({"access_token": tok})
        self.assertNotIn(urllib.parse.quote(tok, safe=""), self.r.redact(url))
        self.assertEqual(Redactor().redact("x?access_token=abc123&y=1"), "x?access_token=[redacted]&y=1")
        self.assertEqual(Redactor().redact("Authorization: OAuth oauth_token=\"z\""), "Authorization: [redacted]")
        self.assertEqual(Redactor().redact("Bearer abc.def"), "Bearer [redacted]")
        self.assertEqual(Redactor().redact('oauth_signature="sig%3D"'), 'oauth_signature="[redacted]"')
        self.assertEqual(Redactor().redact("client_secret=s3&code=c0de"),
                         "client_secret=[redacted]&code=[redacted]")
        self.assertEqual(Redactor().redact("status_code=FINISHED"), "status_code=FINISHED")

    def test_short_values_not_registered(self):
        r = Redactor()
        r.add("X", "short")
        self.assertEqual(r.redact("short"), "short")

    def test_debug_traceback_is_redacted(self):
        secret = CANARIES["FB_PAGE_KOTLETA_TOKEN"]

        class Exploding(FakeTransport):
            def send(self, req):
                raise RuntimeError(f"kaboom with {secret} inside")

        path = self.package({"facebook": {"text": "hi"}})
        # a transport crash inside a target is isolated and redacted
        code, out, err = self.run_cli("--debug", "publish", path, "--targets", "fb:kotleta",
                                      transport=Exploding())
        self.assertEqual(code, 1)
        self.assertIn("[redacted:FB_PAGE_KOTLETA_TOKEN]", out + err)
        # a crash outside any target goes through the top-level path with a traceback
        orig = cli.COMMANDS["status"]

        def crash(rt):
            rt.env()
            raise RuntimeError(f"top-level {secret}")
        cli.COMMANDS["status"] = crash
        try:
            code, out, err = self.run_cli("--debug", "status")
        finally:
            cli.COMMANDS["status"] = orig
        self.assertIs(cli.COMMANDS["status"], orig)
        self.assertEqual(code, 1)
        self.assertIn("Traceback", err)
        self.assertIn("[redacted:FB_PAGE_KOTLETA_TOKEN]", err)
