import io
import os
import socket
import threading
import urllib.parse
import urllib.request

from poster import config, linkedin
from poster.cli import Out
from poster.context import Ctx
from poster.redact import Redactor
from tests.base import CANARIES, PLAIN, FakeTransport, PosterTestCase, resp

NEW_TOKEN = "cnry-new-li-token-from-exchange-0001"


class LoginTests(PosterTestCase):
    def setUp(self):
        super().setUp()
        for name in ("LINKEDIN_ACCESS_TOKEN", "LINKEDIN_TOKEN_EXPIRES_AT", "LINKEDIN_PERSON_URN"):
            self.env_values.pop(name)
        self.write_env(self.env_values)
        self.out_buf, self.err_buf = io.StringIO(), io.StringIO()
        self.redactor = Redactor()
        self.redactor.add_env(self.env_values)
        self.addCleanup(lambda: self.assertNotIn(NEW_TOKEN, self.out_buf.getvalue() + self.err_buf.getvalue()))

    def ctx(self, transport):
        env = config.load_env(self.env_path)
        return Ctx(env=env, settings=config.load_settings(env), transport=transport,
                   redactor=self.redactor, ledger=None, clock=self.clock, sleep=lambda s: None)

    def login(self, transport, browser, timeout=10.0, port=0):
        out = Out(self.redactor, self.out_buf, self.err_buf)
        urls = []

        def on_url(url):
            urls.append(url)
            threading.Thread(target=browser, args=(url,), daemon=True).start()
        code = linkedin.login(self.ctx(transport), self.env_path, port=port, timeout=timeout,
                              out=out, on_auth_url=on_url)
        self.outputs += [self.out_buf.getvalue(), self.err_buf.getvalue()]
        return code, urls

    @staticmethod
    def callback(url, **params):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        redirect = urllib.parse.urlsplit(q["redirect_uri"])
        query = {"state": q["state"]}
        query.update(params)
        local = f"http://127.0.0.1:{redirect.port}/callback?" + urllib.parse.urlencode(query)
        with urllib.request.urlopen(local, timeout=5) as r:
            return r.read()

    def good_transport(self, probe_status=200):
        return FakeTransport([resp(200, {"access_token": NEW_TOKEN, "expires_in": 5184000}),
                              resp(200, {"sub": "AbC123"}),
                              resp(probe_status, {"value": {"uploadUrl": "https://www.linkedin.com/u", "image": "urn:li:image:P"}})])

    def test_authorization_url_parameters_and_fixed_scope(self):
        url = linkedin.authorization_url("cid", "http://localhost:8765/callback", "st")
        parts = urllib.parse.urlsplit(url)
        self.assertEqual(f"{parts.scheme}://{parts.netloc}{parts.path}",
                         "https://www.linkedin.com/oauth/v2/authorization")
        self.assertEqual(dict(urllib.parse.parse_qsl(parts.query)), {
            "response_type": "code", "client_id": "cid", "redirect_uri": "http://localhost:8765/callback",
            "state": "st", "scope": "openid profile w_member_social"})
        self.assertIn("scope=openid%20profile%20w_member_social", url)

    def test_full_login_writes_three_variables(self):
        bodies = []
        t = self.good_transport()
        code, urls = self.login(t, lambda u: bodies.append(self.callback(u, code="AUTHCODE123456")))
        self.assertEqual(code, 0, self.err_buf.getvalue())
        self.assertIn("Register this exact redirect URL", self.out_buf.getvalue())
        self.assertIn("http://localhost:8765/callback", self.out_buf.getvalue())
        self.assertEqual(bodies, [b"Done, you can close this tab."])
        exchange, userinfo, probe = t.requests
        self.assertEqual(exchange.url, "https://www.linkedin.com/oauth/v2/accessToken")
        form = dict(urllib.parse.parse_qsl(exchange.body.decode()))
        redirect = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(urls[0]).query))["redirect_uri"]
        self.assertEqual(form, {"grant_type": "authorization_code", "code": "AUTHCODE123456",
                                "client_id": PLAIN["LINKEDIN_CLIENT_ID"],
                                "client_secret": CANARIES["LINKEDIN_CLIENT_SECRET"],
                                "redirect_uri": redirect})
        self.assertEqual(userinfo.url, "https://api.linkedin.com/v2/userinfo")
        self.assertEqual(userinfo.headers["Authorization"], f"Bearer {NEW_TOKEN}")
        self.assertEqual(probe.url, "https://api.linkedin.com/rest/images?action=initializeUpload")
        env = config.load_env(self.env_path)
        self.assertEqual(env["LINKEDIN_ACCESS_TOKEN"], NEW_TOKEN)
        self.assertEqual(env["LINKEDIN_PERSON_URN"], "urn:li:person:AbC123")
        self.assertEqual(env["LINKEDIN_TOKEN_EXPIRES_AT"], "2027-01-08T10:15:00Z")
        self.assertEqual(env["X_API_KEY"], CANARIES["X_API_KEY"])     # other lines kept
        self.assertEqual(oct(os.stat(self.env_path).st_mode & 0o777), "0o600")
        self.assertIn("token valid until 2027-01-08T10:15:00Z (60 days)", self.out_buf.getvalue())
        self.assertIn("versioned Posts API reachable", self.out_buf.getvalue())
        self.assertNotIn("AUTHCODE123456", self.out_buf.getvalue() + self.err_buf.getvalue())

    def test_wrong_state_rejected(self):
        def forged(url):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
            port = urllib.parse.urlsplit(q["redirect_uri"]).port
            urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?state=forged&code=X", timeout=5).read()
        t = FakeTransport()
        code, _ = self.login(t, forged)
        self.assertEqual((code, t.requests), (1, []))
        self.assertIn("state does not match", self.err_buf.getvalue())
        self.assertNotIn("LINKEDIN_ACCESS_TOKEN", config.load_env(self.env_path))

    def test_error_callback_handled(self):
        t = FakeTransport()
        code, _ = self.login(t, lambda u: self.callback(u, error="user_cancelled_login",
                                                        error_description="The user cancelled"))
        self.assertEqual((code, t.requests), (1, []))
        self.assertIn("user_cancelled_login", self.err_buf.getvalue())

    def test_probe_403_warns_but_saves(self):
        t = self.good_transport(probe_status=403)
        code, _ = self.login(t, lambda u: self.callback(u, code="C0DE00001"))
        self.assertEqual(code, 0)
        self.assertIn("answered 403", self.err_buf.getvalue())
        self.assertIn("LINKEDIN_ACCESS_TOKEN", config.load_env(self.env_path))

    def test_timeout_and_busy_port(self):
        code, _ = self.login(FakeTransport(), lambda u: None, timeout=0.6)
        self.assertEqual(code, 1)
        self.assertIn("no callback within", self.err_buf.getvalue())
        holder = socket.socket()
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        self.addCleanup(holder.close)
        port = holder.getsockname()[1]
        code, _ = self.login(FakeTransport(), lambda u: None, port=port)
        self.assertEqual(code, 2)
        self.assertIn("pick another --port", self.err_buf.getvalue())

    def test_missing_client_credentials(self):
        self.env_values.pop("LINKEDIN_CLIENT_SECRET")
        self.write_env(self.env_values)
        code, out, err = self.run_cli("login", "linkedin", "--port", "0")
        self.assertEqual(code, 2)
        self.assertIn("missing LINKEDIN_CLIENT_SECRET", err)

    def test_absurd_expires_in_is_refused(self):
        for value in (10 ** 30, "abc", -5, None):
            with self.subTest(value=value):
                t = FakeTransport([resp(200, {"access_token": NEW_TOKEN, "expires_in": value})])
                code, _ = self.login(t, lambda u: self.callback(u, code="C0DE00002"))
                self.assertEqual(code, 1)
                self.assertNotIn("LINKEDIN_ACCESS_TOKEN", config.load_env(self.env_path))
