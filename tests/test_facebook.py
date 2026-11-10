import urllib.parse

from poster import facebook
from poster.http import TransportError
from tests.base import CANARIES, PLAIN, FakeTransport, PosterTestCase, make_jpeg, resp

PAGE = PLAIN["FB_PAGE_KOTLETA_ID"]
TOKEN = CANARIES["FB_PAGE_KOTLETA_TOKEN"]


class FacebookTests(PosterTestCase):
    def test_text_post_request_shape(self):
        t = FakeTransport([resp(200, {"id": f"{PAGE}_111"})])
        path = self.package({"facebook": {"text": "Привіт, сторінка"}})
        code, out, _ = self.run_cli("publish", path, "--targets", "fb:kotleta", transport=t)
        self.assertEqual(code, 0)
        (req,) = t.requests
        self.assertEqual((req.method, req.url), ("POST", f"https://graph.facebook.com/v27.0/{PAGE}/feed"))
        self.assertEqual(urllib.parse.parse_qs(req.body.decode()),
                         {"message": ["Привіт, сторінка"], "access_token": [TOKEN]})
        self.assertIn(f"https://www.facebook.com/{PAGE}_111", out)
        rec = self.records()[-1]
        self.assertEqual((rec["target"], rec["status"], rec["post_id"]), ("fb:kotleta", "published", f"{PAGE}_111"))

    def test_photo_post_multipart(self):
        data = make_jpeg(1200, 800)
        self.image("p.jpg", data)
        t = FakeTransport([resp(200, {"id": "999", "post_id": f"{PAGE}_222"})])
        path = self.package({"facebook": {"text": "caption text", "image": "p.jpg"}})
        code, out, _ = self.run_cli("publish", path, "--targets", "fb:kotleta", transport=t)
        self.assertEqual(code, 0)
        (req,) = t.requests
        self.assertEqual(req.url, f"https://graph.facebook.com/v27.0/{PAGE}/photos")
        ctype = req.headers["Content-Type"]
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        body = req.body
        self.assertIn(b'name="caption"\r\n\r\ncaption text\r\n', body)
        self.assertIn(b'name="access_token"\r\n\r\n' + TOKEN.encode(), body)
        self.assertIn(b'name="source"; filename="p.jpg"\r\nContent-Type: image/jpeg\r\n\r\n' + data, body)
        self.assertNotIn(b'name="message"', body)   # deprecated for photos (F3)
        rec = self.records()[-1]
        self.assertEqual((rec["post_id"], rec["extra"]["photo_id"]), (f"{PAGE}_222", "999"))
        self.assertEqual(rec["url"], f"https://www.facebook.com/{PAGE}_222")

    def test_graph_version_from_env(self):
        self.env_values["META_GRAPH_VERSION"] = "v28.0"
        self.write_env(self.env_values)
        t = FakeTransport([resp(200, {"id": "1_2"})])
        self.run_cli("publish", self.package({"facebook": {"text": "a"}}), "--targets", "fb:kotleta", transport=t)
        self.assertTrue(t.requests[0].url.startswith("https://graph.facebook.com/v28.0/"))

    def test_api_error_is_reduced_and_redacted(self):
        body = {"error": {"message": f"Invalid OAuth access token {TOKEN}", "code": 190,
                          "error_subcode": 463, "fbtrace_id": "AbC"}}
        t = FakeTransport([resp(400, body)])
        code, out, err = self.run_cli("publish", self.package({"facebook": {"text": "a"}}),
                                      "--targets", "fb:kotleta", transport=t)
        self.assertEqual(code, 1)
        self.assertIn("FAILED", out)
        self.assertIn("400 Facebook post: Invalid OAuth access token", out)
        self.assertIn("code 190; error_subcode 463; fbtrace_id AbC", out)
        self.assertEqual(self.records()[-1]["status"], "failed")

    def test_delete_then_read_back(self):
        t = FakeTransport([resp(200, {"id": f"{PAGE}_333"})])
        self.run_cli("publish", self.package({"facebook": {"text": "a"}}), "--targets", "fb:kotleta", transport=t)
        t = FakeTransport([resp(200, {"id": f"{PAGE}_333"}), resp(200, {"success": True}),
                           resp(400, {"error": {"message": "does not exist", "code": 100, "error_subcode": 33}})])
        code, out, _ = self.run_cli("delete", "--target", "fb:kotleta", "--post-id", f"{PAGE}_333", transport=t)
        self.assertEqual(code, 0, out)
        p, d, g = t.requests
        self.assertEqual((p.method, d.method), ("GET", "DELETE"))
        self.assertIn("fields=id", p.url)
        self.assertTrue(d.url.startswith(f"https://graph.facebook.com/v27.0/{PAGE}_333?access_token="))
        self.assertEqual(g.method, "GET")
        self.assertIn("fields=id", g.url)
        self.assertEqual(self.records()[-1]["status"], "deleted")
        # a second delete is refused locally, without any request
        t2 = FakeTransport()
        code, _, err = self.run_cli("delete", "--target", "fb:kotleta", "--post-id", f"{PAGE}_333", transport=t2)
        self.assertEqual((code, t2.requests), (2, []))
        self.assertIn("already deleted", err)

    def test_delete_fails_when_read_back_still_finds_it(self):
        t = FakeTransport([resp(200, {"id": f"{PAGE}_444"})])
        self.run_cli("publish", self.package({"facebook": {"text": "a"}}), "--targets", "fb:kotleta", transport=t)
        t = FakeTransport([resp(200, {"id": f"{PAGE}_444"}), resp(200, {"success": True}),
                           resp(200, {"id": f"{PAGE}_444"})])
        code, _, err = self.run_cli("delete", "--target", "fb:kotleta", "--post-id", f"{PAGE}_444", transport=t)
        self.assertEqual(code, 1)
        self.assertIn("read-back still finds it", err)
        self.assertEqual(self.records()[-1]["status"], "published")

    def test_delete_refuses_ids_not_in_record_and_other_networks(self):
        t = FakeTransport()
        code, _, err = self.run_cli("delete", "--target", "fb:kotleta", "--post-id", "1_2", transport=t)
        self.assertEqual((code, t.requests), (2, []))
        self.assertIn("not in the post record", err)
        code, _, err = self.run_cli("delete", "--target", "x", "--post-id", "1", transport=t)
        self.assertEqual(code, 2)
        # an id published to another Page is not deletable through this one
        t = FakeTransport([resp(200, {"id": "5_6"})])
        self.run_cli("publish", self.package({"facebook": {"text": "a"}}), "--targets", "fb:demo", transport=t)
        t = FakeTransport()
        code, _, _ = self.run_cli("delete", "--target", "fb:kotleta", "--post-id", "5_6", transport=t)
        self.assertEqual((code, t.requests), (2, []))


class DeleteReadBackTests(PosterTestCase):
    def delete_with(self, *answers):
        """Publish a post, then delete it with the scripted answers; returns the result."""
        t = FakeTransport([resp(200, {"id": f"{PAGE}_555"})])
        self.run_cli("publish", self.package({"facebook": {"text": "a"}}), "--targets", "fb:kotleta", transport=t)
        t = FakeTransport(list(answers))
        code, out, err = self.run_cli("delete", "--target", "fb:kotleta", "--post-id", f"{PAGE}_555", transport=t)
        return code, out, err, self.records()[-1]["status"], t

    def test_does_not_exist_answers_count_as_gone(self):
        # code 10 is what the smoke run saw for a deleted Page post (docs/smoke/2026-11-09-facebook-page.md),
        # accepted only because the pre-read with the same token answered 200
        gone = {"code 100 subcode 33": resp(400, {"error": {"message": "x", "code": 100, "error_subcode": 33}}),
                "http 404": resp(404, {"error": {"message": "x"}}),
                "code 10 after a 200 pre-read": resp(400, {"error": {"message": "x", "code": 10}})}
        for name, answer in gone.items():
            with self.subTest(answer=name):
                code, out, _, status, t = self.delete_with(resp(200, {"id": f"{PAGE}_555"}),
                                                           resp(200, {"success": True}), answer)
                self.assertEqual((code, status), (0, "deleted"), out)
                self.assertEqual([r.method for r in t.requests], ["GET", "DELETE", "GET"])
                self.assertIn("deleted (read-back confirms)", out)

    def test_other_errors_are_deletion_not_confirmed_with_their_code(self):
        other = {"token code 190": (resp(400, {"error": {"message": "x", "code": 190}}), "HTTP 400, code 190"),
                 "code 100 other subcode": (resp(400, {"error": {"message": "x", "code": 100, "error_subcode": 1}}),
                                            "HTTP 400, code 100"),
                 "server error": (resp(500, {}), "HTTP 500"),
                 "cut off": (TransportError("network error: IncompleteRead"), "read-back failed")}
        for name, (answer, shown) in other.items():
            with self.subTest(answer=name):
                code, _, err, status, _ = self.delete_with(resp(200, {"id": f"{PAGE}_555"}),
                                                           resp(200, {"success": True}), answer)
                self.assertEqual((code, status), (1, "published"), err)
                self.assertIn("deletion not confirmed", err)
                self.assertIn(shown, err)

    def test_failing_pre_read_refuses_before_the_delete(self):
        cases = {"code 10": resp(400, {"error": {"message": "x", "code": 10}}),
                 "404": resp(404, {}), "server error": resp(500, {}),
                 "cut off": TransportError("network error: IncompleteRead")}
        for name, answer in cases.items():
            with self.subTest(pre_read=name):
                code, _, err, status, t = self.delete_with(answer)
                self.assertEqual((code, status), (1, "published"), err)
                self.assertEqual([r.method for r in t.requests], ["GET"])   # no DELETE was sent
                self.assertIn("not deleted", err)
