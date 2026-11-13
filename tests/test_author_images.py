"""Slice C (authoring.md §18.5, §18.8): ratio choices and their sizes, the crop route's look
checks, the settings route, quotes from «Развернуть», the Gemini highlight with its budget
guard, the Russian 4xx lines, the base switch, the focus with C's ratios, and storage.

No test opens a non-loopback socket (tests/base.py guard). Every Gemini reply is a
synthetic FakeTransport answer (panel_fixture.image_reply, GEMINI_402); no real key is read.
"""
import base64
import html
import json
import os
import re
import subprocess
import threading
import unittest
from unittest import mock
from decimal import Decimal

from factory.authoring import budget, drafts, gemini, prompts, send
from factory.authoring.common import Refusal
from poster import http, rules, state as poster_state
from tests.base import CANARIES, FakeTransport, PosterTestCase, make_jpeg, make_png, resp
from tests import panel_fixture as pf
from tests.test_author_send import SendCase

D = Decimal
NETS = ("facebook", "instagram", "linkedin", "x")
# §18.5 item 1: network, choice -> sizes for 3 024 x 4 032, 320 x 240 and a 1 536 x 2 048 style
TABLE = {
    ("instagram", "4:5"): ((1080, 1350), (192, 240), (1080, 1350)),
    ("instagram", "1:1"): ((1080, 1080), (240, 240), (1080, 1080)),
    ("instagram", "1.91:1"): ((955, 500), (191, 100), (955, 500)),
    ("facebook", "orig"): ((1536, 2048), (320, 240), (1536, 2048)),
    ("facebook", "4:5"): ((1636, 2045), (192, 240), (1536, 1920)),
    ("facebook", "1:1"): ((2048, 2048), (240, 240), (1536, 1536)),
    ("facebook", "16:9"): ((2048, 1152), (320, 180), (1536, 864)),
    ("linkedin", "orig"): ((1536, 2048), (320, 240), (1536, 2048)),
    ("linkedin", "1.91:1"): ((1910, 1000), (191, 100), (1528, 800)),
    ("linkedin", "1:1"): ((2048, 2048), (240, 240), (1536, 1536)),
    ("x", "16:9"): ((1600, 900), (320, 180), (1536, 864)),
    ("x", "orig"): ((1200, 1600), (320, 240), (1200, 1600)),
    ("x", "1:1"): ((1600, 1600), (240, 240), (1536, 1536)),
}
RAW = ("[{", '{"', '"error"', "prepayment")
LINE_402 = ("Не удалось получить {what} от Gemini (HTTP 402): закончились предоплаченные кредиты "
            "Gemini — пополните баланс в Google AI Studio")


def strip_csrf(text, token):
    """A page-body assertion on status digits first drops the random CSRF token (§18.8)."""
    return text.replace(token, "")


# ---------------------------------------------------------------- pure functions

class RatioTest(PosterTestCase):
    def test_item1_table_and_check_image(self):
        self.assertEqual({(n, r) for n in NETS for r in drafts.CHOICES[n]}, set(TABLE))
        for (n, r), sizes in TABLE.items():
            for (w, h), got in zip(((3024, 4032), (320, 240), (1536, 2048)), sizes):
                self.assertEqual(send.crop_size(n, w, h, r), got, (n, r, w, h))
            for size in (sizes[0], sizes[2]):   # the first and third columns pass the poster
                path = self.image(f"{n}-{r.replace(':', '_')}-{size[0]}.jpg", make_jpeg(*size))
                self.assertEqual(rules.check_image(n, rules.sniff(path)).errors, [], (n, r, size))
        # the defaults are D′'s crops
        for n in NETS:
            self.assertEqual(send.crop_size(n, 3024, 4032), send.crop_size(n, 3024, 4032, drafts.CHOICES[n][0]))
        # 1.91:1 is exactly 191:100, inside Instagram's accepted range
        self.assertEqual(955 * 100, 500 * 191)
        self.assertLessEqual(955 / 500, rules.IG_MAX_ASPECT)
        # a base too small for a ratio gives k = 0
        self.assertEqual(send.crop_size("instagram", 150, 100, "1.91:1"), (0, 0))

    def test_crop_problem_per_look(self):
        def info(w, h):
            return rules.ImageInfo("x.jpg", "jpeg", 1000, w, h)
        view = (1200, 1600)
        self.assertEqual(send.crop_problem("instagram", info(1080, 1080), view, "1:1"), "")
        self.assertIn("1:1", send.crop_problem("instagram", info(1080, 1350), view, "1:1"))   # not the look's ratio
        def words(*args):
            return send.crop_problem(*args).replace("\u00a0", " ")
        self.assertIn("1 080", words("instagram", info(1146, 600), view, "1.91:1"))   # over the box
        self.assertIn("2 048", words("facebook", info(2100, 2100), view, "1:1"))
        self.assertIn("как у фото", words("x", info(1200, 1500), view, "orig"))
        self.assertIn("1 600", words("x", info(1500, 2000), (1536, 2048), "orig"))
        self.assertIn("меньше", send.crop_problem("x", info(900, 1200), view, "orig"))
        self.assertEqual(send.crop_problem("x", info(1200, 1600), (1536, 2048), "orig"), "")
        self.assertEqual(send.crop_problem("facebook", info(1536, 2048), (1536, 2048), "orig"), "")

    def test_look_digest_and_defaults(self):
        d = {"variants": {}}
        self.assertEqual({n: drafts.look_digest(d, n) for n in NETS}, {n: drafts.default_digest(n) for n in NETS})
        quoted = dict(d, quotes={"x": "Hi"})
        self.assertEqual(drafts.look_digest(quoted, "x"), drafts.default_digest("x"))   # a quote not drawn
        placed = dict(quoted, look={"x": {"quote_at": "top"}})
        self.assertNotEqual(drafts.look_digest(placed, "x"), drafts.default_digest("x"))
        self.assertNotEqual(drafts.look_digest(dict(d, base="blur"), "facebook"), drafts.default_digest("facebook"))
        self.assertRegex(drafts.default_digest("x"), r"\A[0-9a-f]{12}\Z")

    def test_validate_refuses_fields_outside_18_2(self):
        good = {"schema": 1, "id": "2026-11-11-my-photos-0001", "created": "2026-11-11T09:40:00Z",
                "updated": "2026-11-11T09:40:00Z", "folder": "my-photos", "photo": "p-0123456789abcdef",
                "topics_auto": "done", "topics": [], "topic": "", "variants": {}, "error": None, "state": "draft"}
        ok = dict(good, base="blur", look={"instagram": {"ratio": "1.91:1", "frame": "gold", "quote_at": "top"}},
                  quotes={"x": "q" * 140}, who="w" * 120,
                  highlight_error={"style": "glow", "text": "t", "model_text": "m", "ts": "2026-11-11T09:40:00Z"})
        drafts.validate(json.loads(json.dumps(ok)))
        bad = [dict(good, base="sepia"), dict(good, look={"pinterest": {}}),
               dict(good, look={"instagram": {"ratio": "orig"}}), dict(good, look={"x": {"ratio": "1.91:1"}}),
               dict(good, look={"x": {"frame": "red"}}), dict(good, look={"x": {"quote_at": "middle"}}),
               dict(good, look={"x": {"zoom": 2}}), dict(good, quotes={"x": "q" * 141}),
               dict(good, quotes={"x": "a\nb"}), dict(good, quotes={"tiktok": "q"}), dict(good, who="w" * 121),
               dict(good, highlight_error={"style": "glow", "text": "t" * 501, "ts": "2026-11-11T09:40:00Z"}),
               dict(good, highlight_error={"style": "sepia", "text": "t", "ts": "2026-11-11T09:40:00Z"}),
               dict(good, highlight_error={"style": "glow", "text": "t", "ts": "x"}),
               dict(good, highlight_error={"style": "glow", "text": "t", "op": "x", "ts": "2026-11-11T09:40:00Z"})]
        for value in bad:
            with self.subTest(value={k: value[k] for k in value if k not in good}), self.assertRaises(Refusal):
                drafts.validate(json.loads(json.dumps(value)))


class VendorMessageTest(PosterTestCase):
    def test_array_body_reads_its_first_object(self):
        body = b'[{"error": {"code": 402, "message": "x"}}]'
        self.assertEqual(http.vendor_message(http.Response(402, {}, body)), "x; code 402")
        for raw in (b"[]", b"[1, 2]", b'["a"]'):
            self.assertEqual(http.vendor_message(http.Response(402, {}, raw)), raw.decode())
        for obj in ({"error": {"code": 190, "message": "bad", "error_subcode": 463}},
                    {"title": "Too Many Requests", "detail": "slow down"}, {"message": "m", "serviceErrorCode": 65600},
                    {"errors": [{"message": "first"}]}, {"error": "invalid_grant", "error_description": "expired"}):
            data = json.dumps(obj).encode()
            # an object body answers exactly as before: the same as the array's first object
            self.assertEqual(http.vendor_message(http.Response(400, {}, data)),
                             http.vendor_message(http.Response(400, {}, b"[" + data + b"]")))
        self.assertEqual(http.vendor_message(http.Response(400, {}, b'{"error": {"message": "m", "code": 1}}')),
                         "m; code 1")

    def test_reason_table(self):
        self.assertEqual(gemini.reason(402), "закончились предоплаченные кредиты Gemini — пополните баланс в Google AI Studio")
        self.assertEqual(gemini.reason(401), gemini.reason(403))
        self.assertEqual(gemini.reason(418), "Gemini отклонил запрос — подробности в журнале панели")
        for code in (400, 404, 413, 429):
            self.assertNotIn("Gemini" + " " + str(code), gemini.reason(code))


# ---------------------------------------------------------------- the panel

class ImagesCase(SendCase):
    """SendCase plus a portrait draft (view copy 240 x 320, aspect 3:4) with its D′ crops."""

    def review(self, did=None, query=""):
        """The review page with no-break spaces read as spaces («до $0.09» is one piece)."""
        body, seen = super().review(did, query)
        return body.replace("\u00a0", " "), seen

    def setUp(self):
        super().setUp()
        orig = pf.make_photo(240, 320, 9)
        self.ppid = pf.store_photo(self.fx, "my-photos", orig, pf.make_photo(120, 160, 9), orig, "portrait.jpg")
        self.did = pf.send_draft(self.fx, self.store, self.ppid, "portrait", 1)
        self.base = f"/create/{self.did}"
        self.sizes = {n: send.crop_size(n, 240, 320) for n in NETS}
        self.crops = pf.write_crops(self.fx, self.did, self.sizes)
        self.out = os.path.join(self.fx.paths.content, "drafts", self.did, "out")
        self.img = os.path.join(self.fx.paths.content, "drafts", self.did, "img")
        self.set_env(add={"GEMINI_API_KEY": CANARIES["GEMINI_API_KEY"]})

    def settings(self, data, did=None, headers=None):
        return self.json_post(f"/create/{did or self.did}/settings", data, headers=headers)

    def highlight(self, style="blur", who="", did=None, headers=None, extra=None):
        return self.json_post(f"/create/{did or self.did}/highlight", dict({"style": style, "who": who}, **(extra or {})),
                              headers=headers)

    def crop(self, network, data, look=None, did=None, fx="0.5", fy="0.5"):
        h = {"Content-Type": "image/jpeg", "Origin": f"http://{self.host}", "X-CSRF-Token": self.srv.panel.csrf}
        params = {"network": network, "fx": fx, "fy": fy}
        if look is not None:
            params["look"] = look
        import urllib.parse
        status, hs, value = self.request("POST", f"/create/{did or self.did}/image?{urllib.parse.urlencode(params)}",
                                         body=data, headers=h)
        self.outputs.append(value.decode("utf-8", "replace"))
        return status, json.loads(value)

    def digest(self, network, did=None):
        return drafts.look_digest(self.draft(did), network)

    def mtimes(self):
        return {n: os.stat(os.path.join(self.out, f"{n}.jpg")).st_mtime_ns
                for n in NETS if os.path.exists(os.path.join(self.out, f"{n}.jpg"))}

    def rows(self):
        return poster_state.read_jsonl(self.srv.panel.ai_ledger.path)

    def visible(self, body):
        """The page's own text (tags dropped), without the CSRF token."""
        text = re.sub(r"<script.*?</script>|<[^>]+>", " ", body[body.index("<main"):], flags=re.S)
        return strip_csrf(html.unescape(text), self.srv.panel.csrf)


class CropLookTest(ImagesCase):
    def test_a_look_gives_its_ratio_and_the_page_digest(self):
        for path in self.crops.values():
            os.unlink(path)
        status, _ = self.settings({"network": "instagram", "ratio": "1.91:1", "frame": "white"})
        self.assertEqual(status, 200)
        look = self.digest("instagram")
        self.assertEqual(self.crop("instagram", make_jpeg(191, 100), look)[0], 200)
        # the previous (default) digest, an absent look and a malformed one
        status, reply = self.crop("instagram", make_jpeg(191, 100), drafts.default_digest("instagram"))
        self.assertEqual((status, reply["error"]), (409, send.FOCUS_MOVED))
        self.assertEqual(self.crop("instagram", make_jpeg(191, 100))[0], 409)
        self.assertEqual(self.crop("instagram", make_jpeg(191, 100), "zz")[0], 400)
        # D′'s posts without a look still work for a network at its default look
        self.assertEqual(self.crop("x", make_jpeg(*self.sizes["x"]))[0], 200)

    def test_refusals_by_look_write_nothing(self):
        for path in self.crops.values():
            os.unlink(path)
        self.settings({"network": "instagram", "ratio": "1:1"})
        self.settings({"network": "linkedin", "ratio": "1.91:1"})
        cases = [("instagram", make_jpeg(240, 300), "1:1"),             # D′'s 4:5, not the look's
                 ("instagram", make_jpeg(1100, 1100), "1 080"),         # over the cap box
                 ("linkedin", make_jpeg(2101, 1100), "2 048"),
                 ("facebook", make_jpeg(240, 300), "как у фото"),       # 1 % off the base's 3:4
                 ("facebook", make_jpeg(180, 240), "меньше"),           # under the base's long side
                 ("facebook", make_jpeg(2400, 3200), "2 048")]          # over its cap
        for network, data, word in cases:
            status, reply = self.crop(network, data, self.digest(network))
            self.assertEqual(status, 409, (network, word, reply))
            self.assertIn(word, reply["error"].replace(" ", " "), (network, word))
        self.assertEqual(os.listdir(self.out), [])

    def test_a_style_base_sets_the_orig_reference(self):
        pf.write_style(self.fx, self.did)
        self.assertEqual(self.settings({"base": "blur"})[0], 200)
        self.assertEqual(os.listdir(self.out), [])
        # as the style (1 536 x 2 048), not the view copy (240 x 320)
        self.assertEqual(self.crop("facebook", make_jpeg(1536, 2048), self.digest("facebook"))[0], 200)
        self.assertEqual(self.crop("x", make_jpeg(1536, 864), self.digest("x"))[0], 200)
        status, reply = self.crop("linkedin", make_jpeg(240, 320), self.digest("linkedin"))
        self.assertEqual(status, 409)
        self.assertIn("меньше", reply["error"])


class SettingsTest(ImagesCase):
    def test_one_card_change_drops_only_its_crop(self):
        before = self.mtimes()
        status, reply = self.settings({"network": "instagram", "ratio": "1:1"})
        self.assertEqual(status, 200, reply)
        self.assertEqual(reply["missing"], ["instagram"])
        self.assertEqual(reply["look"]["instagram"]["ratio"], "1:1")
        self.assertEqual(self.draft()["look"], {"instagram": {"ratio": "1:1"}})
        after = self.mtimes()
        self.assertNotIn("instagram", after)
        self.assertEqual({n: after[n] for n in after}, {n: before[n] for n in after})
        body, seen = self.review()
        self.assertEqual(seen, "")
        self.assertIn("Готовлю картинки: Instagram…", body)
        self.assertIn('<option value="1:1" selected>1:1</option>', body)
        # back to the default: the field goes away, the crop is dropped again
        pf.write_crops(self.fx, self.did, {"instagram": self.sizes["instagram"]})
        self.settings({"network": "instagram", "ratio": "4:5"})
        self.assertNotIn("look", self.draft())
        self.assertNotIn("instagram", self.mtimes())
        # the same value again changes nothing and drops nothing
        pf.write_crops(self.fx, self.did, {"instagram": self.sizes["instagram"]})
        stamp = self.mtimes()
        self.settings({"network": "instagram", "ratio": "4:5"})
        self.assertEqual(self.mtimes(), stamp)

    def test_quote_place_text_and_refusals(self):
        status, reply = self.settings({"network": "x", "quote_at": "top"})
        self.assertEqual((status, reply["error"]), (409, "впишите цитату"))
        status, reply = self.settings({"network": "x", "quote_at": "top", "quote": "к" * 141})
        self.assertEqual((status, reply["error"]), (409, "цитата — не больше 140 знаков"))
        self.assertEqual(self.settings({"network": "x", "quote_at": "top", "quote": "a\nb"})[0], 400)
        self.assertEqual(self.mtimes().keys(), set(NETS))
        status, reply = self.settings({"network": "x", "quote_at": "top", "quote": "  Café steps  "})
        self.assertEqual(status, 200, reply)
        self.assertEqual(self.draft()["quotes"], {"x": "Café steps"})
        self.assertEqual(reply["look"]["x"]["quote"], "Café steps")
        self.assertNotIn("x", self.mtimes())
        body, _ = self.review()
        self.assertIn('class="quote-row"><label class="look-quote">Текст цитаты<textarea rows="1" maxlength="140" data-q data-c>Café steps</textarea>', body)

    def test_unknown_keys_values_and_a_sent_draft_write_nothing(self):
        draft_file = os.path.join(self.fx.paths.content, "drafts", self.did, "draft.json")
        before = (self.file_hash(draft_file), self.mtimes())
        for data in ({}, {"zoom": 1}, {"network": "x"}, {"network": "pinterest", "ratio": "1:1"},
                     {"network": "x", "ratio": "4:5"}, {"network": "instagram", "ratio": "orig"},
                     {"network": "x", "frame": "red"}, {"network": "x", "quote_at": "middle"},
                     {"network": "x", "quote": 5}, {"base": "sepia"}, {"base": "orig", "network": "x"},
                     {"network": "x", "ratio": "1:1", "extra": 1}):
            status, _ = self.settings(data)
            self.assertEqual(status, 400, data)
        status, reply = self.settings({"base": "glow"})
        self.assertEqual((status, reply["error"]), (409, "сначала создайте этот стиль"))
        self.assertEqual((self.file_hash(draft_file), self.mtimes()), before)
        pf.set_sent(self.fx, self.did, "published", {t: {"status": "published"} for t in ("fb:kotleta", "ig:kotleta", "linkedin", "x")})
        sent = self.file_hash(draft_file)
        status, reply = self.settings({"network": "x", "ratio": "1:1"})
        self.assertEqual((status, reply["error"]), (409, drafts.SENT))
        status, reply = self.highlight()
        self.assertEqual((status, reply["error"]), (409, drafts.SENT))
        self.assertEqual(self.file_hash(draft_file), sent)
        self.assertEqual(self.ai_transport.requests, [])

    def test_headers_refuse_before_any_write_or_request(self):
        draft_file = os.path.join(self.fx.paths.content, "drafts", self.did, "draft.json")
        before = (self.file_hash(draft_file), self.ledgers())
        for path, data in ((f"{self.base}/settings", {"base": "orig"}), (f"{self.base}/highlight", {"style": "blur"})):
            for headers, code in (({"Origin": "http://evil.example"}, 403), ({"Origin": None}, 403),
                                  ({"X-CSRF-Token": None}, 403), ({"X-CSRF-Token": "0" * 64}, 403),
                                  ({"Content-Type": "text/plain"}, 415)):
                status, _ = self.json_post(path, data, headers=headers)
                self.assertEqual(status, code, (path, headers))
            status, _, _ = self.request("POST", path, body=json.dumps(data).encode(), host="evil.example:80",
                                        headers={"Content-Type": "application/json"})
            self.assertEqual(status, 421)
        self.assertEqual((self.file_hash(draft_file), self.ledgers()), before)
        self.assertEqual(self.ai_transport.requests, [])


class ExpandQuotesTest(ImagesCase):
    def expand(self, value):
        self.ai_transport.add(pf.gemini_reply(value))
        return self.json_post(f"{self.base}/expand", {})

    def test_quotes_stored_schema_and_prompt(self):
        status, reply = self.expand(dict(pf.TEXTS, quotes=dict(pf.STYLE_QUOTES, x="Café now")))
        self.assertEqual(status, 200, reply)
        body = json.loads(self.ai_transport.requests[-1].body)
        self.assertEqual(body["response_format"]["schema"], prompts.SCHEMAS["expand"])
        self.assertEqual(set(prompts.SCHEMAS["expand"]["properties"]["quotes"]["properties"]), set(NETS))
        self.assertIn("quotes", prompts.SCHEMAS["expand"]["required"])
        self.assertIn("at most 90 characters", body["input"][0]["text"])
        self.assertEqual(self.draft()["quotes"], dict(pf.STYLE_QUOTES, x="Café now"))
        self.assertEqual({n: v["text"] for n, v in self.draft()["variants"].items()}, pf.TEXTS)
        # regenerate and a text edit leave the quotes byte-identical
        quotes = json.dumps(self.draft()["quotes"], ensure_ascii=False)
        self.ai_transport.add(pf.gemini_reply({"text": "A new text."}))
        self.assertEqual(self.json_post(f"{self.base}/regenerate", {"network": "x"})[0], 200)
        self.assertEqual(self.json_post(f"{self.base}/text", {"network": "x", "text": "Edited."})[0], 200)
        self.assertEqual(json.dumps(self.draft()["quotes"], ensure_ascii=False), quotes)
        # «Развернуть» keeps its button bound
        self.assertEqual(budget.button("expand", self.srv.panel.clock()), D("0.05"))

    def test_without_quotes_and_bad_quotes(self):
        self.assertEqual(self.expand(pf.TEXTS)[0], 200)
        self.assertNotIn("quotes", self.draft())
        status, _ = self.expand(dict(pf.TEXTS, quotes={"x": "q" * 141, "linkedin": "two\nlines", "instagram": "ok",
                                                       "facebook": 5}))
        self.assertEqual(status, 200)
        self.assertEqual(self.draft()["quotes"], {"instagram": "ok"})
        self.assertEqual(self.expand(dict(pf.TEXTS, extra="no"))[0], 502)   # any other key stays invalid

    def test_a_changed_drawn_quote_drops_only_that_crop(self):
        self.store.update(self.did, lambda d: d.update(quotes=dict(pf.STYLE_QUOTES), look={"x": {"quote_at": "top"}}))
        pf.write_crops(self.fx, self.did, self.sizes)
        before = self.mtimes()
        self.assertEqual(self.expand(dict(pf.TEXTS, quotes=dict(pf.STYLE_QUOTES, x="New", instagram="Нова")))[0], 200)
        after = self.mtimes()
        self.assertNotIn("x", after)   # drawn and changed
        self.assertEqual(after, {n: before[n] for n in ("facebook", "instagram", "linkedin")})


class HighlightTest(ImagesCase):
    def reserved_then(self, reply):
        """A transport step that records the ledger's last row when the request arrives."""
        seen = []

        def step(req):
            seen.append(self.rows()[-1])
            return reply
        return step, seen

    def test_one_request_reserved_first_stored_and_shown(self):
        step, seen = self.reserved_then(pf.image_reply(pf.style_jpeg()))
        self.ai_transport.add(step)
        status, reply = self.highlight("blur", "мужчина в синей куртке")
        self.assertEqual(status, 200, reply)
        self.assertEqual(len(self.ai_transport.requests), 1)
        req = self.ai_transport.requests[0]
        self.assertEqual(req.url, gemini.URL)
        self.assertEqual(req.headers["x-goog-api-key"], CANARIES["GEMINI_API_KEY"])
        self.assertEqual(req.timeout, 180)
        body = json.loads(req.body)
        self.assertEqual(body["model"], "gemini-nano-banana-2.1")
        self.assertIs(body["store"], False)
        self.assertNotIn("name", json.dumps(body))
        self.assertEqual(body["input"][0]["text"], "\n".join([
            prompts.STYLES["blur"], "The main person is the most prominent person in the photo.",
            "The main person: мужчина в синей куртке", "Do not add text, logos or other people."]))
        from factory.authoring import photos
        with open(photos.file_path(self.fx.paths.stock, "my-photos", self.ppid, "view"), "rb") as fh:
            self.assertEqual(body["input"][1], {"type": "image", "mime_type": "image/jpeg",
                                                "data": base64.b64encode(fh.read()).decode(), "resolution": "high"})
        self.assertEqual(body["response_format"], {"type": "image", "mime_type": "image/jpeg",
                                                   "aspect_ratio": "3:4", "image_size": "2K"})
        # reserved before the request, one ok row priced by D32 after it
        self.assertEqual((seen[0]["status"], seen[0]["op"], seen[0]["model"]), ("reserved", "highlight", prompts.IMAGE_MODEL))
        self.assertEqual(D(seen[0]["price"]), budget.bound("highlight", body["input"][0]["text"], self.srv.panel.clock()))
        rows = [r for r in self.rows() if r["rid"] == seen[0]["rid"]]
        self.assertEqual([r["status"] for r in rows], ["reserved", "ok"])
        self.assertEqual(D(rows[1]["actual"]), (D("1.50") * 3000 + D("30.00") * 1800) / 1_000_000)
        # stored 0600 in a 0700 img/, served by /file, who saved, the month in the reply
        path = os.path.join(self.img, "blur.jpg")
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), pf.style_jpeg())
        self.assertEqual((os.stat(path).st_mode & 0o777, os.stat(self.img).st_mode & 0o777), (0o600, 0o700))
        self.assertEqual((reply["width"], reply["height"], reply["url"]), (1536, 2048, f"{self.base}/file?name=blur"))
        self.assertIn("ИИ · ноябрь $0.06 из $10.00", reply["month"])
        status, headers, data = self.request("GET", f"{self.base}/file?name=blur")
        self.assertEqual((status, headers["cache-control"], data), (200, "no-store", pf.style_jpeg()))
        self.assertEqual(self.draft()["who"], "мужчина в синей куртке")
        # the page shows it beside «Оригинал»; the chips do not repeat it
        body, _ = self.review(query="?style=blur")
        self.assertIn(f'<img src="{self.base}/file?name=blur" alt="Размыть фон">', body)
        self.assertIn("Оригинал", body)
        self.assertIn('data-base="blur" data-c>Взять за основу</button>', body)
        self.assertIn("Создать заново · до $0.09", body)
        self.assertNotIn("Размыть фон — создать", body)
        self.assertIn("Свечение — создать · до $0.09", body)
        self.assertIn('value="мужчина в синей куртке"', body)

    def test_no_image_and_bad_images(self):
        cases = [(pf.image_reply(text=pf.MODEL_TEXT + " " + CANARIES["GEMINI_API_KEY"]), gemini.NO_IMAGE),
                 (pf.image_reply(make_png(64, 64), mime="image/png"), gemini.NOT_JPEG),
                 (pf.image_reply(b"\xff\xd8\xff" + b"\x00" * (8 * 1024 * 1024)), gemini.TOO_BIG)]
        for reply, message in cases:
            self.ai_transport.add(reply)
            status, answer = self.highlight("glow")
            self.assertEqual((status, answer["error"]), (502, message))
            self.assertEqual(self.rows()[-1]["status"], "ok")
            self.assertFalse(os.path.exists(os.path.join(self.img, "glow.jpg")))
            self.assertEqual([f for f in os.listdir(self.img)] if os.path.isdir(self.img) else [], [])
            error = self.draft()["highlight_error"]
            self.assertEqual((error["style"], error["text"]), ("glow", message))
        self.ai_transport.add(pf.image_reply(text=pf.MODEL_TEXT))
        self.highlight("glow")
        self.assertEqual(self.draft()["highlight_error"]["model_text"], pf.MODEL_TEXT)
        body, _ = self.review()
        for words in ("Gemini не вернул картинку", f"Ответ Gemini: «{pf.MODEL_TEXT}»", "Повторить · до $0.09"):
            self.assertIn(words, body)
        self.assertIn('data-style="glow" data-c>Повторить · до $0.09', body)
        # incomplete and failed answer as §8.4; a success clears the stored error
        for state, message in (("incomplete", gemini.INCOMPLETE), ("failed", gemini.INVALID)):
            self.ai_transport.add(pf.image_reply(pf.style_jpeg(), status=state))
            self.assertEqual(self.highlight("glow")[1]["error"], message)
        self.ai_transport.add(pf.image_reply(pf.style_jpeg()))
        self.assertEqual(self.highlight("glow")[0], 200)
        self.assertNotIn("highlight_error", self.draft())

    def test_a_style_with_exif_is_refused_and_replaces_nothing(self):
        # a browser decodes the orientation tag: 1536 x 2048 stored shows as 2048 x 1536
        pf.write_style(self.fx, self.did)
        self.settings({"base": "blur"})
        before = {n: self.crop(n, make_jpeg(*s), self.digest(n))[0] for n, s in
                  {"facebook": (1536, 2048), "x": (1536, 864)}.items()}
        self.assertEqual(before, {"facebook": 200, "x": 200})
        crops = self.read_crops()
        draft = self.draft()
        with open(os.path.join(self.img, "blur.jpg"), "rb") as fh:
            style = fh.read()
        self.ai_transport.add(pf.image_reply(pf.make_exif6(1536, 2048, 123)))
        status, reply = self.highlight("blur")
        self.assertEqual((status, reply["error"]), (502, gemini.HAS_EXIF))
        with open(os.path.join(self.img, "blur.jpg"), "rb") as fh:
            self.assertEqual(fh.read(), style)
        self.assertEqual([f for f in os.listdir(self.img)], ["blur.jpg"])      # no .up- leftover
        self.assertEqual(self.read_crops(), crops)
        after = self.draft()
        self.assertEqual((after["base"], after.get("style_rev")), (draft["base"], draft.get("style_rev")))
        self.assertEqual(after["highlight_error"]["text"], gemini.HAS_EXIF)
        body, _ = self.review()
        self.assertIn(gemini.HAS_EXIF, body)
        # a fresh style (no stored one) is refused the same way and creates no file
        self.ai_transport.add(pf.image_reply(pf.make_exif6(1536, 2048, 124)))
        self.assertEqual(self.highlight("glow")[1]["error"], gemini.HAS_EXIF)
        self.assertFalse(os.path.exists(os.path.join(self.img, "glow.jpg")))
        # an ordinary JPEG still generates, and the base's crops are redrawn from it
        self.ai_transport.add(pf.image_reply(pf.style_jpeg()))
        self.assertEqual(self.highlight("blur")[0], 200)
        self.assertNotIn("highlight_error", self.draft())

    def test_regenerating_the_base_stales_its_look_tokens_and_crops(self):
        pf.write_style(self.fx, self.did)
        self.settings({"base": "blur"})
        token = self.digest("facebook")
        old = make_jpeg(1536, 2048)
        self.assertEqual(self.crop("facebook", old, token)[0], 200)
        # the same-style, same-size regeneration with different bytes
        other = pf.make_photo(1536, 2048, 777)
        self.assertNotEqual(other, pf.style_jpeg())
        self.ai_transport.add(pf.image_reply(other))
        self.assertEqual(self.highlight("blur")[0], 200)
        self.assertEqual(os.listdir(self.out), [])                   # the crops are redrawn
        self.assertNotEqual(self.digest("facebook"), token)
        status, reply = self.crop("facebook", old, token)             # the page's old token
        self.assertEqual((status, reply["error"]), (409, send.FOCUS_MOVED))
        self.assertEqual(os.listdir(self.out), [])
        # the new page's token, with a crop drawn from the new base, succeeds
        status, reply = self.crop("facebook", pf.make_photo(1536, 2048, 4), self.digest("facebook"))
        self.assertEqual(status, 200, reply)

    def test_a_crop_in_flight_during_a_regeneration_is_refused(self):
        pf.write_style(self.fx, self.did)
        self.settings({"base": "blur"})
        token = self.digest("facebook")
        real = send.rules.check_image

        def regenerate(network, info):          # between the early digest check and the write
            result = real(network, info)
            self.sender_store_style(pf.make_photo(1536, 2048, 778))
            return result
        with mock.patch.object(send.rules, "check_image", regenerate):
            status, reply = self.crop("facebook", make_jpeg(1536, 2048), token)
        self.assertEqual((status, reply["error"]), (409, send.FOCUS_MOVED))
        self.assertEqual(os.listdir(self.out), [])

    def read_crops(self):
        found = {}
        for n in ("facebook", "x"):
            with open(os.path.join(self.out, f"{n}.jpg"), "rb") as fh:
                found[n] = fh.read()
        return found

    def sender_store_style(self, data):
        self.srv.panel.sender.store_style(self.did, "blur", data)

    def test_other_styles_and_default_uploads_keep_their_tokens(self):
        for path in self.crops.values():
            os.unlink(path)
        token = self.digest("x")
        self.assertEqual(token, drafts.default_digest("x"))
        # regenerating a style that is not the base leaves the base's tokens alone
        self.ai_transport.add(pf.image_reply(pf.style_jpeg()))
        self.assertEqual(self.highlight("glow")[0], 200)
        self.assertEqual(self.digest("x"), token)
        self.assertEqual(self.crop("x", make_jpeg(*self.sizes["x"]), token)[0], 200)
        # a stored draft without a revision keeps its digest; a bad revision is refused
        d = self.draft()
        self.assertRegex(d["style_rev"]["glow"], r"\A[0-9a-f]{8}\Z")
        for bad in ({"glow": "zz"}, {"sepia": "0" * 8}, ["glow"], {"glow": 1}):
            with self.assertRaises(Refusal):
                drafts.validate(dict(d, style_rev=bad))

    def test_a_result_after_sending_is_not_stored(self):
        def late(req):
            pf.set_sent(self.fx, self.did, "published", {t: {"status": "published"} for t in ("fb:kotleta", "ig:kotleta", "linkedin", "x")})
            return pf.image_reply(pf.style_jpeg())
        self.ai_transport.add(late)
        status, reply = self.highlight()
        self.assertEqual((status, reply["error"]), (409, drafts.SENT))
        self.assertFalse(os.path.exists(self.img))   # not even an empty img/ in a sent draft
        self.assertEqual(self.rows()[-1]["status"], "ok")

    def test_bad_requests(self):
        for data, code in (({"style": "sepia"}, 400), ({"style": "../x"}, 400), ({"style": "blur", "who": 5}, 400),
                           ({"style": "blur", "extra": 1}, 400), ({"style": "blur", "who": "w" * 121}, 409)):
            status, _ = self.json_post(f"{self.base}/highlight", data)
            self.assertEqual(status, code, data)
        self.assertEqual(self.ai_transport.requests, [])
        self.assertNotIn("highlight_error", self.draft())


class GuardTest(ImagesCase):
    def test_bounds_on_every_spending_control(self):
        now = self.srv.panel.clock()
        for style in prompts.STYLES:
            self.assertGreaterEqual(budget.button("highlight", now), budget.bound("highlight", prompts.highlight(style, "\U00010000" * 120), now))
        self.assertEqual(budget.button("highlight", now), D("0.09"))
        body, _ = self.review()
        for chip in ("Размыть фон — создать · до $0.09", "Свечение — создать · до $0.09", "Контур — создать · до $0.09"):
            self.assertIn(chip, body)
        self.assertEqual(len(re.findall(r'data-style="[a-z]+"', body)), 3)

    def test_month_at_the_cap_and_no_key_send_nothing(self):
        ledger = self.srv.panel.ai_ledger
        rid = ledger.reserve("topics", D("9.99"), D(10), "fixture")
        ledger.settle(rid, "ok", actual=D("9.99"))
        refusal = "Бюджет ИИ на ноябрь исчерпан: «Стиль фото» стоит до $0.09."
        body, _ = self.review()
        self.assertEqual(self.visible(body).count(refusal), 1)   # once as text; the chips carry it as a title
        self.assertRegex(body, r'data-style="blur" data-c disabled title="Бюджет ИИ')
        self.assertIn("ИИ · ноябрь $9.99 из $10.00 · лимит", body)
        status, reply = self.highlight()
        self.assertEqual(status, 409)
        self.assertTrue(reply["error"].replace("\u00a0", " ").startswith(refusal))
        self.set_env(drop=("GEMINI_API_KEY",))
        pf.write_style(self.fx, self.did)
        body, _ = self.review(query="?style=blur")
        self.assertEqual(self.visible(body).count("нет GEMINI_API_KEY в .env — стили фото недоступны"), 1)
        self.assertIn('data-base="blur" data-c>Взять за основу</button>', body)   # free, still enabled
        self.assertRegex(body, r'data-style="glow" data-c disabled title="нет GEMINI_API_KEY')
        status, reply = self.highlight()
        self.assertEqual((status, reply["error"]), (409, budget.NO_KEY_IMAGE))
        self.assertEqual(self.ai_transport.requests, [])
        self.assertNotIn("highlight_error", self.draft())

    def test_two_clicks_one_request_and_a_third_call_across_drafts(self):
        gate, entered = threading.Event(), threading.Event()

        def held(req):
            entered.set()
            gate.wait(10)
            return pf.image_reply(pf.style_jpeg())
        other = pf.send_draft(self.fx, self.store, self.ppid, "other", 2)
        third = pf.send_draft(self.fx, self.store, self.ppid, "third", 3)
        self.ai_transport.add(held, held)
        results = []
        threads = [threading.Thread(target=lambda d=d: results.append(self.highlight(did=d))) for d in (self.did, other)]
        threads[0].start()
        self.assertTrue(entered.wait(10))
        entered.clear()
        status, reply = self.highlight()
        self.assertEqual((status, reply["error"]), (409, "уже выполняется"))
        threads[1].start()
        self.assertTrue(entered.wait(10))
        status, reply = self.highlight(did=third)
        self.assertEqual((status, reply["error"]), (409, "ИИ занят двумя запросами — подождите"))
        gate.set()
        for t in threads:
            t.join(10)
        self.assertEqual(sorted(r[0] for r in results), [200, 200])
        self.assertEqual(len(self.ai_transport.requests), 2)

    def test_settlements_503_timeout_402(self):
        ledger = self.srv.panel.ai_ledger
        self.ai_transport.add(resp(503, {"error": {"message": "x"}}))
        status, reply = self.highlight()
        self.assertEqual((status, reply["error"], self.rows()[-1]["status"]), (502, "Не удалось получить картинку от Gemini", "unknown"))
        after_503 = ledger.month_total()
        self.assertEqual(after_503, D(self.rows()[-2]["price"]))
        self.ai_transport.add(TimeoutError("slow"))
        status, reply = self.highlight()
        self.assertEqual((status, reply["error"], self.rows()[-1]["status"]), (504, gemini.OFFLINE, "unknown"))
        total = ledger.month_total()
        self.ai_transport.add(resp(402, pf.GEMINI_402))
        status, _ = self.highlight()
        self.assertEqual((status, self.rows()[-1]["status"]), (502, "failed"))
        self.assertEqual(ledger.month_total(), total)

    def test_every_request_of_every_op_finds_its_reservation(self):
        sent = []

        class Wrapped:
            def __init__(inner, replies):
                inner.replies = replies

            def send(inner, req):
                rows = self.rows()
                last = rows[-1]
                sent.append(req.fields["op"])
                self.assertEqual((last["status"], last["op"]), ("reserved", req.fields["op"]))
                self.assertEqual(sum(1 for r in rows if r["status"] == "reserved"), len(sent))
                return inner.replies.pop(0)
        self.srv.panel.ai.transport = Wrapped([
            pf.gemini_reply({"topics": pf.TOPICS}), pf.gemini_reply(dict(pf.TEXTS, quotes=pf.STYLE_QUOTES)),
            pf.gemini_reply({"text": "Again."}), pf.gemini_reply("слова"), pf.image_reply(pf.style_jpeg())])
        self.assertEqual(self.json_post(f"{self.base}/topics", {})[0], 200)
        self.assertEqual(self.json_post(f"{self.base}/expand", {})[0], 200)
        self.assertEqual(self.json_post(f"{self.base}/regenerate", {"network": "x"})[0], 200)
        h = {"Content-Type": "audio/ogg", "Origin": f"http://{self.host}", "X-CSRF-Token": self.srv.panel.csrf}
        self.assertEqual(self.request("POST", f"{self.base}/voice", body=b"OggS" + b"\x00" * 64, headers=h)[0], 200)
        self.assertEqual(self.highlight()[0], 200)
        self.assertEqual(sent, ["topics", "expand", "regenerate", "voice", "highlight"])


class RussianErrorTest(ImagesCase):
    def test_402_array_in_russian_on_both_pages(self):
        canary = CANARIES["GEMINI_API_KEY"]
        body402 = [{"error": {"code": 402, "message": "Your prepayment credits are depleted. " + canary,
                              "status": "RESOURCE_EXHAUSTED"}}]
        self.ai_transport.add(resp(402, body402), resp(402, body402))
        status, reply = self.json_post(f"{self.base}/expand", {})
        self.assertEqual((status, reply["error"]), (502, LINE_402.format(what="тексты")))
        status, reply = self.highlight()
        self.assertEqual((status, reply["error"]), (502, LINE_402.format(what="картинку")))
        draft = self.draft()
        self.assertEqual(draft["error"]["text"], LINE_402.format(what="тексты"))
        self.assertEqual(draft["highlight_error"]["text"], LINE_402.format(what="картинку"))
        _, _, page = self.page(self.base)
        review, _ = self.review()
        self.assertIn(LINE_402.format(what="тексты"), self.visible(page))
        self.assertIn(LINE_402.format(what="картинку"), self.visible(review))
        for text in (self.visible(page), self.visible(review), reply["error"], draft["error"]["text"],
                     draft["highlight_error"]["text"]):
            for raw in RAW:
                self.assertNotIn(raw, text)
        lines = [l for l in self.log.getvalue().splitlines() if l.startswith("panel: gemini")]
        self.assertEqual(lines, ["panel: gemini expand HTTP 402: Your prepayment credits are depleted. "
                                 "[redacted:GEMINI_API_KEY]; code 402",
                                 "panel: gemini highlight HTTP 402: Your prepayment credits are depleted. "
                                 "[redacted:GEMINI_API_KEY]; code 402"])

    def test_each_status_has_its_words(self):
        for code in (400, 401, 403, 404, 413, 429, 418):
            self.ai_transport.add(resp(code, {"error": {"message": "vendor words"}}))
            status, reply = self.highlight()
            self.assertEqual(reply["error"], f"Не удалось получить картинку от Gemini (HTTP {code}): {gemini.reason(code)}")
            self.assertNotIn("vendor words", reply["error"])


class BaseSwitchTest(ImagesCase):
    def test_take_as_base_and_back(self):
        pf.write_style(self.fx, self.did)
        old_x = self.digest("x")
        status, reply = self.settings({"base": "blur"})
        self.assertEqual((status, reply["base"], sorted(reply["missing"])), (200, "blur", list(NETS)))
        self.assertEqual(os.listdir(self.out), [])
        # a crop drawn from the old base is refused
        status, reply = self.crop("x", make_jpeg(*self.sizes["x"]), old_x)
        self.assertEqual((status, reply["error"]), (409, send.FOCUS_MOVED))
        body, _ = self.review()
        self.assertIn('"source": "/create/' + self.did + '/file?name=blur"', html.unescape(body))
        self.assertRegex(body, r'<figcaption class="photo-label">Размыть фон</figcaption><button class="photo-box send-photo"[^>]*data-focus')
        self.assertIn('<div class="photo-under"><span class="photo-mark">основа</span>', body)
        self.assertIn('data-base="orig" data-c>Взять за основу', body)
        for n, size in pf.STYLED_SIZES.items():
            self.assertEqual(self.crop(n, make_jpeg(*size), self.digest(n))[0], 200, n)
        # a new result for the base style drops every crop again
        self.ai_transport.add(pf.image_reply(pf.style_jpeg()))
        self.assertEqual(self.highlight("blur")[0], 200)
        self.assertEqual(os.listdir(self.out), [])
        status, reply = self.settings({"base": "orig"})
        self.assertEqual((status, reply["base"]), (200, "orig"))
        self.assertNotIn("base", self.draft())


class FocusLookTest(ImagesCase):
    def test_tap_drops_every_cropped_target(self):
        self.store.update(self.did, lambda d: d.update(look={"facebook": {"ratio": "4:5"}}))
        pf.write_crops(self.fx, self.did, self.sizes)
        before = self.mtimes()
        body, _ = self.review()
        self.assertIn("Нажмите на фото-основу, чтобы сдвинуть центр кадра (Facebook, Instagram и X)", body)
        self.assertEqual(self.json_post(f"{self.base}/focus", {"fx": 0.5, "fy": 0.2})[0], 200)
        self.assertEqual(self.mtimes(), {"linkedin": before["linkedin"]})

    def test_the_photo_button_is_a_c_control_and_the_tap_takes_the_busy_guard(self):
        # §18.4: while a crop line, a settings POST, a highlight call or the focus POST itself
        # runs, the photo is blocked like the style and base buttons (the browser probes
        # review-focus, review-template and review-highlight-loading press it for real)
        pf.write_crops(self.fx, self.did, self.sizes)
        body, _ = self.review()
        self.assertRegex(body, r'<button class="photo-box send-photo" type="button" data-focus data-c ')
        self.assertEqual(len(re.findall(r"data-focus", body)), 1)
        with open(os.path.join(os.path.dirname(pf.__file__), "..", "factory", "panel", "static", "send.js"),
                  encoding="utf-8") as fh:
            js = fh.read()
        tap = js[js.index("var tap = function"):js.index("api.tap = tap")]
        self.assertIn("if (busyCount > 0)", tap)
        self.assertLess(tap.index("if (busyCount > 0)"), tap.index("post("))
        self.assertLess(tap.index("busy(true)"), tap.index("post("))
        self.assertLess(tap.index("busy(false)"), tap.index("failed("))   # a failure frees the controls first

    def test_no_cropped_target_no_hint_no_button(self):
        self.sender.target_ids = ("fb:kotleta",)
        body, _ = self.review()
        self.assertNotIn("сдвинуть центр кадра", body)
        self.assertNotIn("data-focus", body)
        self.assertNotIn("send-ring", body)
        self.assertIn('<div class="photo-box"><img src="/photo?', body)
        self.assertEqual(self.json_post(f"{self.base}/focus", {"fx": 0.5, "fy": 0.2})[0], 200)
        self.assertIn("facebook", self.mtimes())


class StorageTest(ImagesCase):
    def test_symlinked_img_and_out_are_refused(self):
        outside = os.path.join(self.root, "outside")
        os.makedirs(outside)
        os.symlink(outside, self.img)
        self.ai_transport.add(pf.image_reply(pf.style_jpeg()))
        status, _ = self.highlight()
        self.assertEqual(status, 409)
        self.assertEqual(os.listdir(outside), [])
        status, _, _ = self.request("GET", f"{self.base}/file?name=blur")
        self.assertEqual(status, 404)
        self.assertEqual(self.settings({"base": "blur"})[0], 409)
        for name in ("../../.env", "blur.jpg", "BLUR", "../img/blur"):
            import urllib.parse
            self.assertEqual(self.request("GET", f"{self.base}/file?name={urllib.parse.quote(name)}")[0], 404, name)

    def test_delete_removes_img_and_gets_write_nothing(self):
        pf.write_style(self.fx, self.did)
        self.store.update(self.did, lambda d: d.update(quotes=dict(pf.STYLE_QUOTES), look={"x": {"quote_at": "top", "frame": "gold"}},
                                                       highlight_error={"style": "glow", "text": "t", "ts": "2026-11-11T09:40:00Z"}))
        content = self.tree(self.fx.paths.content)
        for path in (f"{self.base}/review", f"{self.base}/review?style=blur", f"{self.base}/review?style=../x",
                     f"{self.base}/file?name=blur", f"{self.base}/file?name=x", self.base, "/create"):
            self.assertEqual(self.request("GET", path)[0], 200, path)
        self.assertEqual(self.tree(self.fx.paths.content), content)
        folder = os.path.join(self.fx.paths.content, "drafts", self.did)
        self.assertEqual(self.form(self.did, "delete")[0], 303)
        self.assertFalse(os.path.exists(folder))

    def test_style_files_are_ignored_by_git(self):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if not os.path.exists(os.path.join(repo, ".git")):
            self.skipTest("not a git checkout")
        out = subprocess.run(["git", "-C", repo, "check-ignore", "content/drafts/d/img/blur.jpg"],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)


if __name__ == "__main__":
    unittest.main()
