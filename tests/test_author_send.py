"""Slice D′ (authoring.md §17.5, §17.8): crops, the review, publish now, the queue with the
offered rule, delete, sent drafts, the poster parity test and the hostile cases.

No test opens a non-loopback socket (tests/base.py guard). The poster always runs either as
`poster.cli.main` with a scripted FakeTransport (panel_fixture.FakePoster) or with
`--dry-run` (DryRunTransport); nothing is published and nothing is paid for.
"""
import datetime as dt
import hashlib
import html
import io
import json
import os
import re
import threading
import time
import urllib.parse
from decimal import Decimal
from unittest import mock

from factory import cli as fcli, ruleset as fruleset
from factory.authoring import common, drafts, send
from factory.panel import server, strings as S
from poster import cli as poster_cli, config, rules, state as poster_state
from tests.base import CANARIES, FakeTransport, PosterTestCase, make_jpeg, make_png
from tests import panel_fixture as pf

TARGETS = ("fb:kotleta", "ig:kotleta", "linkedin", "x")
SMALL = {"facebook": (320, 240), "instagram": (192, 240), "linkedin": (320, 240), "x": (320, 180)}


def wait_until(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.01)


# ---------------------------------------------------------------- pure functions

class CropMathTest(PosterTestCase):
    def test_d19_sizes_and_no_upscale(self):
        want = {"instagram": (1080, 1350), "facebook": (1536, 2048), "linkedin": (1536, 2048),
                "x": (1600, 900)}
        for n, size in want.items():
            self.assertEqual(send.crop_size(n, 3024, 4032), size, n)
        small = {n: send.crop_size(n, 320, 240) for n in want}
        self.assertEqual(small, {"instagram": (192, 240), "facebook": (320, 240),
                                 "linkedin": (320, 240), "x": (320, 180)})
        # a landscape original keeps its ratio on Facebook and LinkedIn
        self.assertEqual(send.crop_size("facebook", 4032, 3024), (2048, 1536))

    def test_windows_centre_and_focus(self):
        self.assertEqual(send.crop_window("x", 3024, 4032), (0, 1166, 3024, 1701))
        self.assertEqual(send.crop_window("x", 3024, 4032, 0.5, 0.2), (0, 0, 3024, 1701))
        self.assertEqual(send.crop_window("instagram", 3024, 4032), (0, 126, 3024, 3780))
        self.assertEqual(send.crop_window("facebook", 3024, 4032, 0.1, 0.9), (0, 0, 3024, 4032))
        # a landscape original: the window is as tall as the photo, pushed to the right edge
        self.assertEqual(send.crop_window("instagram", 4032, 3024, 1.0, 0.5), (1613, 0, 2419, 3024))

    def test_poster_check_image_on_the_d19_sizes(self):
        for n, (w, h) in pf.SEND_SIZES.items():
            path = self.image(f"{n}.jpg", make_jpeg(w, h))
            self.assertEqual(rules.check_image(n, rules.sniff(path)).errors, [], n)
        path = self.image("ig34.jpg", make_jpeg(1536, 2048))
        errors = rules.check_image("instagram", rules.sniff(path)).errors
        self.assertTrue(errors and "0.750" in errors[0])
        self.assertIn("соотношение сторон 0.750 вне 0.8–1.91",
                      send.image_words("instagram", rules.sniff(path), errors[0]))

    def test_exif_walk_is_shared(self):
        self.assertEqual(common.jpeg_exif(pf.make_exif6(32, 24, 1)), "exif")
        self.assertEqual(common.jpeg_exif(pf.make_photo(32, 24, 1)), "ok")
        self.assertEqual(common.jpeg_exif(b"\xff\xd8garbage"), "bad")


# ---------------------------------------------------------------- the panel

class SendCase(pf.PanelCase):
    """The data fixture plus one 320 x 240 photo in «Мои фото» and a draft with four texts
    and its crops stored at their D19 sizes for that original."""

    def setUp(self):
        super().setUp()
        self.poster = pf.FakePoster()
        self.sender = self.srv.panel.sender
        self.sender.publish_fn = self.poster
        self.hold = threading.Event()
        self.addCleanup(self._finish_publish)
        orig = pf.make_photo(320, 240, 7)
        self.pid = pf.store_photo(self.fx, "my-photos", orig, pf.make_photo(160, 120, 7), orig, "send.jpg")
        self.store = self.srv.panel.drafts
        self.did = pf.send_draft(self.fx, self.store, self.pid, "ready", 0)
        self.crops = pf.write_crops(self.fx, self.did, SMALL)
        self.base = f"/create/{self.did}"
        self.ai_transport = FakeTransport()
        self.srv.panel.ai.transport = self.ai_transport
        self.addCleanup(self._no_canary_on_disk)

    def _finish_publish(self):
        self.hold.set()
        self.sender.join(10)
        self.assertFalse(self.sender.busy())

    def _no_canary_on_disk(self):
        # drafts, packages and stock (the fixture's poster record holds a canary on purpose)
        for dirpath, _, files in os.walk(self.fx.paths.content):
            for f in files:
                path = os.path.join(dirpath, f)
                with open(path, "rb") as fh:
                    data = fh.read().decode("utf-8", "replace")
                for name, value in CANARIES.items():
                    self.assertNotIn(value, data, f"{name} in {path}")
        for value in CANARIES.values():
            self.assertNotIn(value, self.log.getvalue())

    # ------------------------------------------------------------ helpers

    def page(self, path):
        status, headers, body = self.get(path)
        return status, headers, html.unescape(body)

    def review(self, did=None, query=""):
        status, _, body = self.page(f"/create/{did or self.did}/review{query}")
        self.assertEqual(status, 200, body[:400])
        m = re.search(r'name="seen" value="([0-9a-f]*)"', body)
        return body, m.group(1) if m else ""

    def form(self, did, op, fields=None, **kw):
        return self.post(f"/create/{did}/{op}", fields or {}, **kw)

    def publish(self, did=None):
        did = did or self.did
        _, seen = self.review(did)
        return self.form(did, "publish", {"seen": seen})

    def status(self, did=None):
        status, headers, data = self.request("GET", f"/create/{did or self.did}/status")
        self.outputs.append(data.decode("utf-8"))
        self.assertEqual(headers["cache-control"], "no-store")
        return json.loads(data)

    def image(self, network, data, did=None, fx="0.5", fy="0.5", headers=None):
        h = {"Content-Type": "image/jpeg", "Origin": f"http://{self.host}",
             "X-CSRF-Token": self.srv.panel.csrf}
        h.update(headers or {})
        query = urllib.parse.urlencode({"network": network, "fx": fx, "fy": fy})
        status, hs, value = self.request("POST", f"/create/{did or self.did}/image?{query}",
                                         body=data, headers=h)
        self.outputs.append(value.decode("utf-8", "replace"))
        return status, json.loads(value) if "json" in hs.get("content-type", "") else value

    def json_post(self, path, data, headers=None):
        h = {"Content-Type": "application/json", "Origin": f"http://{self.host}",
             "X-CSRF-Token": self.srv.panel.csrf}
        h.update(headers or {})
        status, hs, value = self.request("POST", path, body=json.dumps(data).encode(), headers=h)
        self.outputs.append(value.decode("utf-8", "replace"))
        return status, json.loads(value) if "json" in hs.get("content-type", "") else value

    def wait(self):
        self.sender.join(10)
        self.assertFalse(self.sender.busy())

    def draft(self, did=None):
        return self.store.load(did or self.did)

    def tree(self, *roots):
        out = {}
        for root in roots:
            for dirpath, _, files in os.walk(root):
                for f in files:
                    if f.endswith(".lock"):   # empty flock files, not data
                        continue
                    out[os.path.relpath(os.path.join(dirpath, f), self.fx.root)] = \
                        self.file_hash(os.path.join(dirpath, f))
        return out

    def record(self):
        return poster_state.read_jsonl(os.path.join(self.fx.paths.poster_state, poster_state.RECORD_FILE))

    def ledgers(self):
        return (self.file_hash(os.path.join(self.fx.paths.poster_state, poster_state.LEDGER_FILE)),
                self.file_hash(self.srv.panel.ai_ledger.path))

    def set_env(self, drop=(), add=None):
        with open(self.fx.paths.env_file, encoding="utf-8") as fh:
            lines = [l for l in fh if l.split("=", 1)[0] not in drop and l.split("=", 1)[0] not in (add or {})]
        lines += [f"{k}={v}\n" for k, v in (add or {}).items()]
        with open(self.fx.paths.env_file, "w", encoding="utf-8") as fh:
            fh.writelines(lines)


class CropRouteTest(SendCase):
    def setUp(self):
        super().setUp()
        for path in self.crops.values():
            os.unlink(path)

    def test_accepted_crops_are_stored_0600_and_send_nothing(self):
        before = self.ledgers()
        for n, (w, h) in SMALL.items():
            data = make_jpeg(w, h)
            status, reply = self.image(n, data)
            self.assertEqual((status, reply["width"], reply["height"]), (200, w, h), reply)
            path = os.path.join(self.fx.paths.content, "drafts", self.did, "out", f"{n}.jpg")
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), data)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        out = os.path.dirname(path)
        self.assertEqual(os.stat(out).st_mode & 0o777, 0o700)
        self.assertEqual(sorted(os.listdir(out)), ["facebook.jpg", "instagram.jpg", "linkedin.jpg", "x.jpg"])
        self.assertEqual(self.ledgers(), before)
        self.assertEqual((self.poster.calls, self.ai_transport.requests), ([], []))

    def test_refusals_write_nothing(self):
        cases = [
            ("facebook", make_png(320, 240), "JPEG"),
            ("facebook", pf.make_exif6(320, 240, 3), "EXIF"),
            ("instagram", make_jpeg(192, 256), "0.750"),                  # check_image
            ("x", make_jpeg(320, 181), "16:9"),
            ("instagram", make_jpeg(1084, 1355), "1 080"),
            ("x", make_jpeg(1616, 909), "1 600"),
            ("facebook", make_jpeg(320, 200), "как у фото"),
            ("linkedin", make_jpeg(300, 225), "меньше копии"),
            ("facebook", make_jpeg(2400, 1800), "2 048"),
            ("facebook", b"\xff\xd8\xff\xe0" + b"\x00" * 40, "JPEG"),
        ]
        for network, data, word in cases:
            status, reply = self.image(network, data)
            self.assertEqual(status, 409, (network, word, reply))
            self.assertIn(word, reply["error"].replace(" ", " "), (network, word))
        out = os.path.join(self.fx.paths.content, "drafts", self.did, "out")
        self.assertEqual(os.listdir(out), [])
        for query, code in ((("pinterest", "0.5", "0.5"), 400), (("x", "nan", "0.5"), 400),
                            (("x", "2", "0.5"), 400), (("x", "zz", "0.5"), 400)):
            status, _ = self.image(query[0], make_jpeg(320, 180), fx=query[1], fy=query[2])
            self.assertEqual(status, code, query)

    def test_old_focus_and_sent_draft(self):
        self.store.update(self.did, lambda d: d.update(focus=[0.5, 0.2]))
        status, reply = self.image("x", make_jpeg(320, 180))
        self.assertEqual((status, reply["error"]), (409, send.FOCUS_MOVED))
        status, _ = self.image("x", make_jpeg(320, 180), fy="0.2")
        self.assertEqual(status, 200)
        pf.set_sent(self.fx, self.did, "published", {t: {"status": "published"} for t in TARGETS})
        status, reply = self.image("facebook", make_jpeg(320, 240))
        self.assertEqual((status, reply["error"]), (409, drafts.SENT))

    def test_headers_and_hostile_input(self):
        data = make_jpeg(320, 240)
        cases = [({"Origin": "http://evil.example"}, 403), ({"Origin": None}, 403),
                 ({"X-CSRF-Token": None}, 403), ({"X-CSRF-Token": "0" * 64}, 403),
                 ({"Content-Type": "image/png"}, 415),
                 ({"Content-Length": str(send.MAX_CROP + 1)}, 413)]
        for headers, code in cases:
            status, _ = self.image("facebook", data, headers=headers)
            self.assertEqual(status, code, headers)
        status, _, _ = self.request("POST", f"{self.base}/image?network=facebook&fx=0.5&fy=0.5",
                                    body=data, host="evil.example:80",
                                    headers={"Content-Type": "image/jpeg"})
        self.assertEqual(status, 421)
        # an out/ symlinked elsewhere: refused, nothing written there
        outside = os.path.join(self.root, "outside")
        os.makedirs(outside)
        out = os.path.join(self.fx.paths.content, "drafts", self.did, "out")
        os.rmdir(out)
        os.symlink(outside, out)
        status, _ = self.image("facebook", data)
        self.assertEqual(status, 409)
        self.assertEqual(os.listdir(outside), [])
        status, _, _ = self.request("GET", f"{self.base}/file?name=facebook")
        self.assertEqual(status, 404)
        for name in ("../../.env", "draft.json", "", "FACEBOOK"):
            status, _, _ = self.request("GET", f"{self.base}/file?name={urllib.parse.quote(name)}")
            self.assertEqual(status, 404, name)
        status, _, _ = self.request("GET", "/create/..%2F..%2Fx/file?name=facebook")
        self.assertEqual(status, 404)


class FocusTest(SendCase):
    def test_focus_drops_only_instagram_and_x(self):
        before = {n: os.stat(p).st_mtime_ns for n, p in self.crops.items()}
        status, reply = self.json_post(f"{self.base}/focus", {"fx": 0.5, "fy": 0.2})
        self.assertEqual((status, reply), (200, {"focus": [0.5, 0.2]}))
        self.assertEqual(self.draft()["focus"], [0.5, 0.2])
        self.assertFalse(os.path.exists(self.crops["instagram"]) or os.path.exists(self.crops["x"]))
        for n in ("facebook", "linkedin"):
            self.assertEqual(os.stat(self.crops[n]).st_mtime_ns, before[n])
        body, seen = self.review()
        self.assertEqual(seen, "")
        self.assertIn("Готовлю картинки: Instagram, X…", body)
        self.assertRegex(body, r'data-open="dlg-publish" disabled')
        for bad in ({"fx": 2, "fy": 0}, {"fx": True, "fy": 0}, {"fx": "0.5", "fy": 0.5}, {}):
            status, _ = self.json_post(f"{self.base}/focus", bad)
            self.assertEqual(status, 400, bad)
        status, _ = self.json_post(f"{self.base}/focus", {"fx": 0.5, "fy": 0.2},
                                   headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)


class ReviewTest(SendCase):
    def test_draft_page_link_and_review_cards(self):
        _, _, body = self.page(self.base)
        m = re.search(r'<div class="texts-heading">.*?</div><p class="send-go-row">'
                      r'<a class="btn send-go" href="([^"]+)">Проверить и отправить →</a></p>', body)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), f"{self.base}/review")
        self.assertIn('data-open="dlg-delete">Удалить черновик</button>', body)
        self.store.update(self.did, lambda d: d["variants"].pop("x"))
        _, _, body = self.page(self.base)
        self.assertIn('<p class="send-go-row" hidden>', body)

        self.store.update(self.did, lambda d: d["variants"].update(
            x={"text": pf.TEXTS["x"], "lang": "en", "source": "gemini"}))
        body, seen = self.review()
        self.assertRegex(seen, r"^[0-9a-f]{64}$")
        self.assertIn("Проверка перед отправкой", body)
        self.assertIn("Проблем нет · 4 сети", body)
        self.assertNotIn("Отправить нельзя", body)
        heads = re.findall(r'<article class="send-card" data-network="(\w+)"><h3>([^<]+)</h3>', body)
        self.assertEqual(heads, [("facebook", "Facebook · fb:kotleta · укр."),
                                 ("instagram", "Instagram · ig:kotleta · укр."),
                                 ("linkedin", "LinkedIn · linkedin · англ."), ("x", "X · x · англ.")])
        for n, text in pf.TEXTS.items():
            self.assertIn(f'<p class="send-text">{text}</p>', body)
            self.assertIn(f'src="{self.base}/file?name={n}"', body)
        self.assertRegex(body, r"320 × 240 · \d+ КБ")
        est = Decimal("0.215")
        month = self.srv.panel.holder.get().inputs.x_spent["2026-11"]
        self.assertIn(f"этот пост в X: ${est} · после него ноябрь ${month + est:.3f} из $5.00", body)
        self.assertIn("ближайшая", self.review(query="?folder=city")[0])
        for n in ("facebook", "x"):
            status, headers, data = self.request("GET", f"{self.base}/file?name={n}")
            self.assertEqual((status, headers["content-type"], headers["cache-control"]),
                             (200, "image/jpeg", "no-store"))

    def test_problems_disable_both_buttons_and_forced_posts_refuse(self):
        self.set_env(drop=("FB_PAGE_KOTLETA_TOKEN",), add={"LINKEDIN_TOKEN_EXPIRES_AT": "2026-11-01T00:00:00Z"})
        self.store.update(self.did, lambda d: d["variants"]["x"].update(text="x" * 312))
        body, seen = self.review()
        self.assertIn('<div class="send-problems k-bad" role="alert"><p>Отправить нельзя — исправьте:</p>', body)
        for line in ("Facebook: нет FB_PAGE_KOTLETA_TOKEN в .env",
                     "Instagram: нет FB_PAGE_KOTLETA_TOKEN в .env",
                     "LinkedIn: токен истёк или истекает в ближайшие 10 минут — войдите заново: "
                     "python3 -m poster login linkedin",
                     "X: длиннее лимита: 312 / 280 — сократите"):
            self.assertIn(line, body)
        self.assertNotIn(CANARIES["FB_PAGE_KOTLETA_TOKEN"], body)
        self.assertIn('data-open="dlg-publish" disabled', body)
        self.assertIn('form="send-queue" disabled', body)
        before = self.tree(self.fx.paths.content, self.fx.paths.poster_state)
        for op, fields in (("publish", {"seen": seen}), ("queue", {"seen": seen, "folder": "my-photos"})):
            status, _, page = self.form(self.did, op, fields)
            self.assertEqual(status, 409, op)
            self.assertIn("Facebook: нет FB_PAGE_KOTLETA_TOKEN в .env", html.unescape(page))
        self.assertEqual(self.tree(self.fx.paths.content, self.fx.paths.poster_state), before)
        self.assertEqual(self.poster.calls, [])

    def test_missing_crop_and_changed_draft(self):
        os.unlink(self.crops["x"])
        body, seen = self.review()
        self.assertIn('<p class="send-crops" role="status">Готовлю картинки: X…</p>', body)
        self.assertIn('data-open="dlg-publish" disabled', body)
        status, _, page = self.form(self.did, "publish", {"seen": seen})
        self.assertEqual(status, 409)
        self.assertIn(send.NOT_READY, page)
        pf.write_crops(self.fx, self.did, SMALL)
        _, seen = self.review()
        # a second tab edits a text after the review was rendered
        status, _ = self.json_post(f"{self.base}/text", {"network": "facebook", "text": "Edited elsewhere."})
        self.assertEqual(status, 200)
        before = self.tree(self.fx.paths.content)
        for op in ("publish", "queue"):
            status, _, page = self.form(self.did, op, {"seen": seen, "folder": "my-photos"})
            self.assertEqual(status, 409, op)
            self.assertIn(send.CHANGED, page)
        self.assertEqual(self.tree(self.fx.paths.content), before)
        self.assertEqual(self.poster.calls, [])


class PublishTest(SendCase):
    def test_publish_now_writes_the_package_and_publishes_once(self):
        status, headers, _ = self.publish()
        self.assertEqual((status, headers["location"]), (303, f"{self.base}/review"))
        self.wait()
        p = self.fx.paths
        package = os.path.join(p.packages, f"{self.did}.json")
        self.assertEqual(self.poster.calls, [[
            "--env-file", p.env_file, "--state-dir", p.poster_state, "publish", package,
            "--targets", "fb:kotleta,ig:kotleta,linkedin,x", "--library", p.library]])
        with open(package, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["schema"], 1)
        self.assertEqual((doc["id"], doc["theme"]), (self.did, self.draft()["topic"]))
        self.assertEqual(doc["meta"], {"approved_by_operator": "2026-11-11", "source": "panel",
                                       "photo": self.pid})
        for n, text in pf.TEXTS.items():
            self.assertEqual(doc["variants"][n], {"text": text, "image": f"media/{self.did}/{n}.jpg"})
            with open(os.path.join(p.packages, "media", self.did, f"{n}.jpg"), "rb") as a, \
                    open(self.crops[n], "rb") as b:
                self.assertEqual(a.read(), b.read())
        self.assertEqual([(r["target"], r["status"], r["ts"]) for r in self.record()[-4:]],
                         [(t, "published", "2026-11-11T09:40:00Z") for t in TARGETS])   # the panel's clock
        d = self.draft()
        self.assertEqual(d["state"], "published")
        self.assertEqual(d["publish"]["attempts"][0]["exit"], 0)
        s = self.status()
        self.assertEqual((s["state"], s["done"], s["total"], s["line"]),
                         ("published", 4, 4, "Опубликовано во всех 4 сетях"))
        body, _ = self.review()
        self.assertEqual(len(re.findall(r'class="send-open" href="https://[^"]+" target="_blank" '
                                        r'rel="noopener">открыть в (Facebook|Instagram|LinkedIn|X)<', body)), 4)
        self.assertIn('target="_blank" rel="noopener"', body)
        self.assertNotIn("dlg-publish", body)
        # read-only now: a second publish and every edit are refused
        status, _, page = self.form(self.did, "publish", {"seen": "x"})
        self.assertEqual(status, 409)
        self.assertEqual(len(self.poster.calls), 1)
        status, headers, _ = self.get(self.base)
        self.assertEqual((status, headers["location"]), (303, f"{self.base}/review"))
        for op, data in (("topic", {"topic": "x"}), ("text", {"network": "x", "text": "y"}),
                         ("topics", {}), ("expand", {}), ("regenerate", {"network": "x"}),
                         ("focus", {"fx": 0.1, "fy": 0.1})):
            status, reply = self.json_post(f"{self.base}/{op}", data)
            self.assertEqual((status, reply["error"]), (409, drafts.SENT), op)
        self.assertEqual(self.ai_transport.requests, [])
        # the list and the library show the sent state
        _, _, start = self.page("/create")
        self.assertIn("опубликован</span>", start)
        _, _, files = self.page("/files?folder=my-photos")
        self.assertIn(f'data-id="{self.pid}"', files)
        tile = re.search(rf'data-id="{self.pid}".*?</li>', files).group(0)
        self.assertIn("опубликовано", tile)

    def test_partial_then_retry_only_the_failed_targets(self):
        self.poster.script = [pf.fb_ok() + pf.ig_ok() + pf.li_401(CANARIES["LINKEDIN_ACCESS_TOKEN"]) + pf.x_403(),
                              pf.li_ok() + pf.x_ok()]
        self.publish()
        self.wait()
        self.assertEqual(self.draft()["state"], "partial")
        body, _ = self.review()
        self.assertIn("Опубликовано в 2 из 4 сетей", body)
        self.assertIn("Повторить упавшие: LinkedIn, X", body)
        self.assertIn("Повторить публикацию в LinkedIn и X?", body)
        self.assertRegex(body, r"LinkedIn · <span class=\"mono\">linkedin</span> —</span> "
                               r"<span class=\"st k-bad\" data-status>ошибка: 401")
        self.assertIn("[redacted:LINKEDIN_ACCESS_TOKEN]", body)
        status, headers, _ = self.form(self.did, "retry")
        self.assertEqual(status, 303)
        self.wait()
        self.assertEqual(self.poster.calls[1][self.poster.calls[1].index("--targets") + 1], "linkedin,x")
        hosts = {r.url.split("/")[2] for r in self.poster.transports[1].requests}
        self.assertEqual(hosts, {"api.linkedin.com", "www.linkedin.com", "api.x.com"})
        self.assertEqual(self.draft()["state"], "published")
        self.assertEqual(self.status()["line"], "Опубликовано во всех 4 сетях")

    def test_retry_never_resends_a_target_recovered_and_deleted_elsewhere(self):
        self.poster.script = [pf.fb_ok() + pf.ig_ok() + pf.li_401() + pf.x_403(), pf.x_ok()]
        self.publish()
        self.wait()
        self.assertEqual(self.draft()["state"], "partial")
        rec = os.path.join(self.fx.paths.poster_state, poster_state.RECORD_FILE)
        template = [r for r in self.record() if r.get("package") == self.did][0]
        # LinkedIn is recovered through the CLI (published) and then deleted there (deleted)
        for status in ("published", "deleted"):
            poster_state.append_jsonl(rec, [dict(template, target="linkedin", status=status)])
        calls = len(self.poster.calls)
        status, _, page = self.form(self.did, "retry")
        self.assertEqual(status, 303)          # X is genuinely failed and unclaimed: it goes
        self.wait()
        self.assertEqual(self.poster.calls[calls][self.poster.calls[calls].index("--targets") + 1], "x")
        hosts = {r.url.split("/")[2] for r in self.poster.transports[calls].requests}
        self.assertEqual(hosts, {"api.x.com"})             # nothing reaches LinkedIn again
        self.assertEqual(self.draft()["state"], "partial")  # LinkedIn stays for the operator to check

    def test_retry_with_only_held_targets_makes_no_request(self):
        self.poster.script = [pf.fb_ok() + pf.ig_ok() + pf.li_401() + pf.x_403(), pf.li_ok() + pf.x_ok()]
        self.publish()
        self.wait()
        rec = os.path.join(self.fx.paths.poster_state, poster_state.RECORD_FILE)
        template = [r for r in self.record() if r.get("package") == self.did][0]
        for t, statuses in (("linkedin", ("published", "deleted")), ("x", ("unknown",))):
            for status in statuses:
                poster_state.append_jsonl(rec, [dict(template, target=t, status=status)])
        calls, before = len(self.poster.calls), self.draft()
        status, _, page = self.form(self.did, "retry")
        self.assertEqual(status, 409)
        self.assertIn("повторять нечего", html.unescape(page))
        self.assertEqual(len(self.poster.calls), calls)
        self.assertEqual(self.draft()["publish"]["attempts"], before["publish"]["attempts"])

    def test_start_page_puts_a_sent_drafts_list_above_the_photos(self):
        _, _, before = self.page("/create")
        self.assertLess(before.index("Недавние фото"), before.index("Черновики"))
        self.publish()
        self.wait()
        _, _, after = self.page("/create")
        self.assertLess(after.index("Черновики"), after.index("Недавние фото"))
        self.assertIn("опубликован</span>", after)

    def test_unknown_is_never_retried_by_the_panel(self):
        from poster.http import TransportError
        self.poster.script = [pf.fb_ok() + pf.ig_ok() + pf.li_401() + [pf.x_ok()[0], TransportError("timeout")],
                              pf.li_ok()]
        self.publish()
        self.wait()
        s = self.status()
        self.assertEqual([t["status"] for t in s["targets"]], ["published", "published", "failed", "unknown"])
        self.assertIn("неизвестно — проверьте аккаунт", self.review()[0])
        self.form(self.did, "retry")
        self.wait()
        self.assertEqual(self.poster.calls[1][self.poster.calls[1].index("--targets") + 1], "linkedin")
        self.assertEqual(self.draft()["state"], "partial")
        status, _, page = self.form(self.did, "retry")
        self.assertEqual(status, 409)
        self.assertEqual(len(self.poster.calls), 2)

    def test_exit_2_first_attempt_and_on_a_retry(self):
        def over_budget(argv, **kw):
            # between the review and the poster's own pre-flight, the X month fills up
            poster_state.append_jsonl(os.path.join(self.fx.paths.poster_state, poster_state.LEDGER_FILE), [
                {"ts": "2026-11-11T09:40:00Z", "month": "2026-11", "rid": "r-full", "op": "post",
                 "price": "9.000", "package": "other", "status": "reserved"}])
            return pf.FakePoster()(argv, **kw)
        self.sender.publish_fn = over_budget
        self.publish()
        self.wait()
        d = self.draft()
        self.assertEqual(d["state"], "draft")
        self.assertNotIn("publish", d)
        self.assertTrue(any("X budget" in line for line in d["refused"]["lines"]))
        self.assertFalse(os.path.exists(os.path.join(self.fx.paths.packages, f"{self.did}.json")))
        self.assertFalse(os.path.exists(os.path.join(self.fx.paths.packages, "media", self.did)))
        body, _ = self.review()
        self.assertIn("Постер отказал до отправки — ничего не опубликовано:", body)
        self.assertIn("X: этот пост стоит $0.215", body)   # the review now sees the month too

    def test_exit_2_on_a_retry_keeps_partial(self):
        self.poster.script = [pf.fb_ok() + pf.ig_ok() + pf.li_401() + pf.x_ok()]
        self.publish()
        self.wait()
        self.sender.publish_fn = lambda argv, *, stdout, **kw: (stdout.write(
            "refused before any network call; nothing was sent:\n  - linkedin: something\n"), 2)[1]
        self.form(self.did, "retry")
        self.wait()
        d = self.draft()
        self.assertEqual((d["state"], d["refused"]["lines"]), ("partial", ["linkedin: something"]))
        body, _ = self.review()
        self.assertIn("Постер отказал до отправки — ничего не опубликовано:", body)
        self.assertIn("Повторить упавшие: LinkedIn", body)

    def test_one_publish_at_a_time_and_live_status(self):
        other = pf.send_draft(self.fx, self.store, self.pid, "other", 1)
        pf.write_crops(self.fx, other, SMALL)
        _, seen_other = self.review(other)
        self.poster.hold = self.hold
        # the record before this attempt holds torn lines and an old row for this package
        record = os.path.join(self.fx.paths.poster_state, poster_state.RECORD_FILE)
        with open(record, "ab") as fh:
            fh.write(b"{not json\n garbage ]\n" + json.dumps(
                {"package": self.did, "target": "ig:kotleta", "status": "failed"}).encode() + b"\n")
        self.publish()
        self.assertTrue(self.poster.entered.wait(10))
        packages = sorted(os.listdir(self.fx.paths.packages))
        for did, seen in ((self.did, "x"), (other, seen_other)):
            status, _, page = self.form(did, "publish", {"seen": seen})
            self.assertEqual(status, 409)
            self.assertIn(send.BUSY, page)
        status, _, page = self.form(self.did, "delete")
        self.assertEqual(status, 409)
        self.assertIn(send.DELETE_BUSY, page)
        self.assertEqual(sorted(os.listdir(self.fx.paths.packages)), packages)
        s = self.status()
        self.assertEqual((s["state"], s["interrupted"], s["line"]),
                         ("publishing", False, "Публикуется… 1 из 4 · не закрывайте панель"))
        self.assertEqual([(t["target"], t["status"]) for t in s["targets"]],
                         [("fb:kotleta", "published"), ("ig:kotleta", "waiting"),
                          ("linkedin", "waiting"), ("x", "waiting")])
        body, _ = self.review()
        self.assertIn('"live": true', body)
        self.assertIn("Instagram · <span class=\"mono\">ig:kotleta</span> —</span> "
                      "<span class=\"st k-muted\" data-status>ждём…</span>", body)
        self.assertNotIn("data-open=\"dlg-delete\"", body.split("send-cards")[0])
        _, _, start = self.page("/create")
        self.assertIn("публикуется</span>", start)
        self.hold.set()
        self.wait()
        self.assertEqual(len(self.poster.calls), 1)
        self.assertEqual(self.status()["state"], "published")

    def test_a_target_the_poster_finds_already_published_counts_as_published(self):
        poster_state.append_jsonl(os.path.join(self.fx.paths.poster_state, poster_state.RECORD_FILE), [
            {"ts": "2026-11-11T09:00:00Z", "package": self.did, "target": "ig:kotleta",
             "network": "instagram", "status": "published", "url": "https://www.instagram.com/p/OLD/"}])
        self.poster.script = [pf.fb_ok() + pf.li_ok() + pf.x_ok()]
        self.publish()
        self.wait()
        self.assertEqual(self.draft()["publish"]["attempts"][0]["outcome"]["ig:kotleta"],
                         {"status": "published", "url": "https://www.instagram.com/p/OLD/"})
        self.assertEqual(self.draft()["state"], "published")

    def test_crash_in_process_marks_the_rest_interrupted(self):
        self.poster.crash = True
        self.publish()
        self.wait()
        d = self.draft()
        self.assertEqual(d["state"], "partial")
        s = self.status()
        self.assertTrue(s["interrupted"])
        self.assertEqual(s["line"], "Публикация прервана — проверьте аккаунт")
        self.assertEqual([t["status"] for t in s["targets"]],
                         ["published", "interrupted", "interrupted", "interrupted"])
        body, _ = self.review()
        self.assertIn("Instagram · <span class=\"mono\">ig:kotleta</span> —</span> "
                      "<span class=\"st k-bad\" data-status>прервано — проверьте аккаунт</span>", body)
        self.assertNotIn("Повторить упавшие", body)
        lines = [l for l in self.log.getvalue().splitlines() if "publish" in l]
        self.assertEqual(len(lines), 1, self.log.getvalue())
        self.assertIn("RuntimeError: the publisher stopped", lines[0])
        _, _, start = self.page("/create")
        self.assertIn('k-bad">прервано</span>', start)


class CrashedPanelTest(pf.PanelCase):
    """A draft left in `publishing` by a killed panel: no live publisher, a free lock."""

    def setUp(self):
        super().setUp()
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(5)
        root = os.path.join(self.root, "crash")
        self.fx = pf.build_send(root, crash=True)
        self.srv = server.make_server(self.fx.paths, self.panel_clock, self.fx.machine_tz, 0,
                                      log=self.log, publish=pf.FakePoster())
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        self.did = self.fx.send_ids["crash"]

    def test_interrupted_is_derived_without_writes(self):
        before = self.state_hashes()
        status, _, body = self.get(f"/create/{self.did}/review")
        body = html.unescape(body)
        self.assertEqual(status, 200)
        self.assertIn("Публикация прервана — проверьте аккаунт", body)
        self.assertIn("Instagram · <span class=\"mono\">ig:kotleta</span> —</span> "
                      "<span class=\"st k-bad\" data-status>прервано — проверьте аккаунт</span>", body)
        self.assertIn("опубликовано", body)
        status, _, data = self.request("GET", f"/create/{self.did}/status")
        s = json.loads(data)
        self.assertEqual((s["state"], s["interrupted"]), ("publishing", True))
        _, _, start = self.get("/create")
        self.assertIn("прервано</span>", start)
        self.get(f"/create/{self.did}/file?name=x")
        self.get(f"/create/{self.did}")
        self.assertEqual(self.state_hashes(), before)
        self.assertFalse(os.path.exists(os.path.join(self.fx.paths.content, "drafts", ".publish.lock")))
        # deleting takes the free lock, then removes the draft
        status, headers, _ = self.post(f"/create/{self.did}/delete", {})
        self.assertEqual((status, headers["location"]), (303, "/create"))
        self.assertFalse(os.path.exists(os.path.join(self.fx.paths.content, "drafts", self.did)))


class ServeTest(pf.PanelCase):
    def test_ctrl_c_waits_for_a_running_publish(self):
        orig = pf.make_photo(320, 240, 9)
        pid = pf.store_photo(self.fx, "my-photos", orig, orig, orig, "c.jpg")
        store = drafts.Store(self.fx.paths.content, self.fx.clock, self.fx.machine_tz)
        did = pf.send_draft(self.fx, store, pid, "c", 3)
        pf.write_crops(self.fx, did, SMALL)
        hold = threading.Event()
        fake = pf.FakePoster(hold=hold)
        out = io.StringIO()
        seen = {}

        def serve_forever(srv, *a, **kw):
            sender = srv.panel.sender
            draft = sender.store.load(did)
            sender.publish(did, send.seen(draft, sender.targets(), sender.crops(did)))
            self.assertTrue(fake.entered.wait(10))
            real_join = sender.join

            def join(timeout=None):
                # shutdown reached its wait: the publish is still running, the message is out;
                # only now is the fake publisher released (no timer, no sleep)
                seen["ended_at_join"] = fake.ended.is_set()
                seen["said"] = "panel: ждём окончания публикации…" in out.getvalue()
                hold.set()
                real_join(10)
            sender.join = join
            self.addCleanup(hold.set)             # bounded cleanup if shutdown never waits
            self.addCleanup(real_join, 10)
            raise KeyboardInterrupt

        with mock.patch.object(server.Server, "serve_forever", serve_forever):
            code = fcli.main(["panel", "--port", "0"], environ=self.fx.environ, clock=self.fx.clock,
                             stdout=out, stderr=out, publish=fake, machine_tz=self.fx.machine_tz)
            seen["ended_at_return"] = fake.ended.is_set()
        self.assertEqual(code, 0)
        self.assertEqual(seen, {"ended_at_join": False, "said": True, "ended_at_return": True})
        self.assertIn("panel: ждём окончания публикации…", out.getvalue())
        self.assertEqual(store.load(did)["state"], "published")


class QueueTest(SendCase):
    def check_lines(self):
        out = io.StringIO()
        fcli.main(["check"], environ=self.fx.environ, clock=self.fx.clock, stdout=out, stderr=out,
                  machine_tz=self.fx.machine_tz)
        return [l for l in out.getvalue().splitlines() if l.startswith("  - ")]

    def queue(self, folder="my-photos", rule=False, did=None):
        did = did or self.did
        _, seen = self.review(did, f"?folder={folder}")
        fields = {"seen": seen, "folder": folder}
        if rule:
            fields["rule"] = "1"
        return self.form(did, "queue", fields)

    def test_queue_without_the_rule(self):
        rules_before = self.file_hash(self.fx.paths.rules)
        problems_before = self.check_lines()
        body, _ = self.review()
        self.assertIn("Публиковать из «Мои фото» по правилу: пн, ср, пт в 10:00", body)
        self.assertIn('name="rule" value="1" checked', body)
        status, headers, _ = self.queue()
        self.assertEqual((status, headers["location"]), (303, f"/files?folder=my-photos#pkg-{self.did}"))
        folder = os.path.join(self.fx.paths.stock, "my-photos")
        name = f"001-{self.did}.json"
        self.assertTrue(os.path.isfile(os.path.join(folder, name)))
        with open(os.path.join(folder, name), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["meta"]["photo"], self.pid)
        self.assertFalse(os.path.exists(os.path.join(self.fx.paths.content, "drafts", self.did)))
        self.assertEqual(self.file_hash(self.fx.paths.rules), rules_before)
        _, _, files = self.page(f"/files?folder=my-photos")
        self.assertIn(f'id="pkg-{self.did}"', files)
        tile = re.search(rf'data-id="{self.pid}".*?</li>', files).group(0)
        self.assertIn("в очереди", tile)
        for n in pf.TEXTS:
            ref = f"media/{self.did}/{n}.jpg"
            status, headers, data = self.request("GET", "/img?" + urllib.parse.urlencode(
                {"folder": "my-photos", "file": name, "ref": ref}))
            self.assertEqual((status, headers["content-type"]), (200, "image/jpeg"), n)
        after = self.check_lines()
        self.assertEqual(after, problems_before)
        self.assertFalse(any(name in l for l in after))
        self.assertEqual(self.poster.calls, [])

    def test_numbering_duplicates_and_folders(self):
        folder = os.path.join(self.fx.paths.stock, "my-photos")
        pf._write_json(os.path.join(folder, "007-older.json"), {
            "schema": 1, "id": "older", "theme": "t", "variants": {"facebook": {"text": "t"}},
            "meta": {"approved_by_operator": "2026-11-01"}})
        for bad in ("quotes", "../x", "nope"):
            status, _, page = self.form(self.did, "queue", {"seen": self.review()[1], "folder": bad})
            self.assertEqual(status, 409, bad)
        pf._write_json(os.path.join(self.fx.paths.packages, f"{self.did}.json"), {"schema": 1})
        before = self.tree(self.fx.paths.stock)
        status, _, page = self.queue()
        self.assertEqual(status, 409)
        self.assertIn(send.DUPLICATE, page)
        self.assertEqual(self.tree(self.fx.paths.stock), before)
        os.unlink(os.path.join(self.fx.paths.packages, f"{self.did}.json"))
        status, _, _ = self.queue()
        self.assertEqual(status, 303)
        self.assertTrue(os.path.isfile(os.path.join(folder, f"008-{self.did}.json")))
        with mock.patch.object(send, "next_number", return_value=1000):
            other = pf.send_draft(self.fx, self.store, self.pid, "o", 2)
            pf.write_crops(self.fx, other, SMALL)
            status, _, page = self.queue(did=other)
        self.assertEqual(status, 409)
        self.assertIn("999", page)

    def test_a_package_under_another_file_name_with_the_same_id_refuses_both_routes(self):
        pf._write_json(os.path.join(self.fx.paths.packages, "other.json"), {
            "schema": 1, "id": self.did, "theme": "t", "variants": {"facebook": {"text": "t"}}})
        _, seen = self.review()
        before = self.tree(self.fx.paths.stock, self.fx.paths.packages, self.fx.paths.content)
        draft_before = self.draft()
        for op, fields in (("publish", {"seen": seen}), ("queue", {"seen": seen, "folder": "my-photos"})):
            status, _, page = self.form(self.did, op, fields)
            self.assertEqual(status, 409, op)
            self.assertIn(send.DUPLICATE, page)
        self.assertEqual(self.tree(self.fx.paths.stock, self.fx.paths.packages, self.fx.paths.content),
                         before)
        self.assertEqual(self.draft(), draft_before)
        self.assertEqual(self.poster.calls, [])

    def test_existing_rule_line(self):
        body, _ = self.review(query="?folder=city")
        snap = self.srv.panel.holder.get()
        n = next(f for f in snap.plan.folders if f.name == "city").counts.get("ready", 0)
        self.assertIn(f"Правило «city-main»: пн, ср, пт в 10:00 · ближайшая публикация из папки: "
                      f"пт, 13 нояб., 10:00 · перед этим постом в очереди {n}", body)
        self.assertNotIn('name="rule"', body)

    def test_offered_rule_refused_by_the_gap(self):
        status, _, page = self.queue(rule=True)
        page = html.unescape(page)
        self.assertEqual(status, 409)
        self.assertIn("Пост в очереди «Мои фото». Правило сохранено черновиком, но не запущено:", page)
        self.assertRegex(page, r"(instagram|facebook|linkedin|x): .*city-main.*my-photos.*minimum gap")
        rule = fruleset.load(self.fx.paths.rules).get("my-photos")
        self.assertEqual((rule.status, rule.active_since), ("draft", None))
        self.assertTrue(os.path.isfile(os.path.join(self.fx.paths.stock, "my-photos", f"001-{self.did}.json")))
        # the refused rule is a draft: the next review still offers one, under another id
        other = pf.send_draft(self.fx, self.store, self.pid, "o", 2)
        pf.write_crops(self.fx, other, SMALL)
        self.assertIn('name="rule" value="1" checked', self.review(other)[0])
        status, _, _ = self.queue(rule=True, did=other)
        self.assertEqual(status, 409)
        self.assertEqual(fruleset.load(self.fx.paths.rules).get("my-photos-2").status, "draft")

    def test_offered_rule_passes_and_plans_the_post(self):
        doc = self.rules_doc()
        doc["rules"] = [r for r in doc["rules"] if r["id"] != "city-main"]
        pf._write_json(self.fx.paths.rules, doc)
        status, headers, _ = self.queue(rule=True)
        self.assertEqual(status, 303)
        rule = fruleset.load(self.fx.paths.rules).get("my-photos")
        self.assertEqual((rule.folder, rule.targets, rule.days, rule.hours, rule.timezone, rule.status,
                          rule.active_since),
                         ("my-photos", TARGETS, ("mon", "wed", "fri"), ("10:00",), "Europe/Berlin",
                          "active", "2026-11-11T09:40:00Z"))
        out = io.StringIO()
        fcli.main(["plan", "--rule", "my-photos", "--days", "14"], environ=self.fx.environ,
                  clock=self.fx.clock, stdout=out, stderr=out, machine_tz=self.fx.machine_tz)
        self.assertIn(f"001-{self.did}.json", out.getvalue())


class DeleteTest(SendCase):
    def test_delete_keeps_the_photo_packages_stock_and_record(self):
        body, _ = self.review()
        self.assertIn("Удалить черновик?", body)
        self.assertIn("Фото останется в «Медиатеке», опубликованные посты — в сетях.", body)
        before = self.tree(self.fx.paths.packages, self.fx.paths.stock, self.fx.paths.poster_state)
        status, _, _ = self.form(self.did, "delete", csrf=False)
        self.assertEqual(status, 403)
        status, _, _ = self.form(self.did, "delete", origin="http://evil.example")
        self.assertEqual(status, 403)
        self.assertTrue(os.path.exists(os.path.join(self.fx.paths.content, "drafts", self.did)))
        status, headers, _ = self.form(self.did, "delete")
        self.assertEqual((status, headers["location"]), (303, "/create"))
        self.assertFalse(os.path.exists(os.path.join(self.fx.paths.content, "drafts", self.did)))
        self.assertEqual(self.tree(self.fx.paths.packages, self.fx.paths.stock, self.fx.paths.poster_state), before)
        _, _, start = self.page("/create")
        self.assertIn(f'data-recent="{self.pid}"', start)
        _, _, files = self.page("/files?folder=my-photos")
        self.assertIn(f'data-id="{self.pid}"', files)
        self.assertEqual(self.get(f"{self.base}/review")[0], 404)

    def test_delete_after_publishing_keeps_the_package(self):
        self.publish()
        self.wait()
        package = os.path.join(self.fx.paths.packages, f"{self.did}.json")
        before = self.file_hash(package)
        status, _, _ = self.form(self.did, "delete")
        self.assertEqual(status, 303)
        self.assertEqual(self.file_hash(package), before)


class HostileTest(SendCase):
    def test_new_posts_refuse_foreign_requests_and_write_nothing(self):
        _, seen = self.review()
        before = self.tree(self.fx.paths.content, self.fx.paths.poster_state)
        for op in ("publish", "retry", "queue", "delete"):
            fields = {"seen": seen, "folder": "my-photos"}
            self.assertEqual(self.form(self.did, op, fields, origin="http://evil.example")[0], 403, op)
            self.assertEqual(self.form(self.did, op, fields, csrf=False)[0], 403, op)
            self.assertEqual(self.form(self.did, op, fields, csrf="0" * 64)[0], 403, op)
            self.assertEqual(self.form(self.did, op, fields, host="evil.example:80")[0], 421, op)
            self.assertEqual(self.form(self.did, op, fields, ctype="text/plain")[0], 415, op)
        self.assertEqual(self.tree(self.fx.paths.content, self.fx.paths.poster_state), before)
        self.assertEqual(self.poster.calls, [])
        status, _, _ = self.form("../../x", "publish", {"seen": seen})
        self.assertIn(status, (404, 409))
        for path in ("/create/..%2F..%2Fx/review", "/create/nope/status", "/create/2026-11-11-x-0000/review"):
            self.assertEqual(self.request("GET", path)[0], 404, path)

    def test_canary_echoed_by_a_vendor_error_never_shows(self):
        token = CANARIES["FB_PAGE_KOTLETA_TOKEN"]
        from tests.base import resp
        self.poster.script = [[resp(400, {"error": {"message": "bad token " + token, "code": 190}})]
                              + pf.ig_ok() + pf.li_ok() + pf.x_ok()]
        self.publish()
        self.wait()
        s = self.status()
        self.assertEqual(s["targets"][0]["status"], "failed")
        body, _ = self.review()
        for text in (json.dumps(s, ensure_ascii=False), body, json.dumps(self.draft(), ensure_ascii=False)):
            self.assertNotIn(token, text)


# ---------------------------------------------------------------- parity with the poster

class ParityTest(PosterTestCase):
    """The review lists a problem for a target exactly when `poster publish --dry-run` on the
    package `send` writes names that target, and is clean exactly when the dry run exits 0
    (authoring.md §17.5 item 5)."""

    TEXTS = {"facebook": "Фейсбук текст.", "instagram": "Інстаграм #один",
             "linkedin": "LinkedIn text.", "x": "Short X post."}

    def setUp(self):
        super().setUp()
        self.content = os.path.join(self.root, "content")
        from factory import paths as fpaths
        self.paths = fpaths.Paths(self.env_path, self.content, os.path.join(self.root, "fstate"),
                                  self.state_dir, self.library)
        self.store = drafts.Store(self.content, self.clock, "Europe/Berlin")
        self.sender = send.Sender(self.paths, self.clock, "Europe/Berlin", self.store, None,
                                  Redactor_from(self.env_path), io.StringIO())
        self.targets = self.sender.targets()
        self.n = 0

    def make(self, texts=None, crops=None, env=None, ledger=None, records=None, drop_text=None):
        self.n += 1
        if env is not None:
            self.write_env(env)
        else:
            self.write_env(dict(self.env_values))
        did = f"2026-11-09-case-{self.n:04x}"
        texts = dict(self.TEXTS, **(texts or {}))
        if drop_text:
            texts.pop(drop_text)
        draft = {"id": did, "topic": "t", "photo": "p-0000000000000000",
                 "variants": {n: {"text": t} for n, t in texts.items()}}
        out = os.path.join(self.root, "out", did)
        os.makedirs(out)
        found = {}
        for n, (w, h) in pf.SEND_SIZES.items():
            data = (crops or {}).get(n, make_jpeg(w, h))
            if data is None:
                continue
            found[n] = self.image(f"{n}.jpg", data, out)
        state = os.path.join(self.state_dir)
        os.makedirs(state, exist_ok=True)
        for name, rows in ((poster_state.LEDGER_FILE, ledger), (poster_state.RECORD_FILE, records)):
            path = os.path.join(state, name)
            if os.path.exists(path):
                os.unlink(path)
            if rows:
                poster_state.append_jsonl(path, [dict(r, package=r.get("package") or did) for r in rows])
        return did, draft, found

    def run_case(self, label, manual=False, **case):
        did, draft, crops = self.make(**case)
        env = config.load_env(self.env_path)
        facts = send.Facts(env, poster_state.read_jsonl(os.path.join(self.state_dir, poster_state.RECORD_FILE)),
                           poster_state.ReadOnlyLedger(self.state_dir, self.clock).month_total(), self.clock())
        rv = send.review(draft, self.targets, facts, crops)
        folder = os.path.join(self.root, "pk", did)
        os.makedirs(folder)
        if not manual:   # the package exactly as send writes it
            package, _ = self.sender._write_package(folder, f"{did}.json", draft, self.targets, crops)
        else:            # what send never writes (the review blocks it): without a crop or text
            written = {n: {"text": v["text"], "image": f"media/{did}/{n}.jpg" if n in crops else None}
                       for n, v in draft["variants"].items()}
            os.makedirs(os.path.join(folder, "media", did))
            for n, path in crops.items():
                with open(path, "rb") as a, open(os.path.join(folder, "media", did, f"{n}.jpg"), "wb") as b:
                    b.write(a.read())
            package = os.path.join(folder, f"{did}.json")
            with open(package, "w", encoding="utf-8") as fh:
                json.dump({"schema": 1, "id": did, "theme": "t", "variants": {
                    n: {k: v for k, v in w.items() if v is not None} for n, w in written.items()},
                    "meta": {"approved_by_operator": "2026-11-09", "source": "panel"}}, fh,
                    ensure_ascii=False)
        code, out, err = self.run_cli("publish", package, "--targets", ",".join(TARGETS), "--dry-run",
                                      "--library", self.library)
        named = {t for t in TARGETS if re.search(rf"^  - {re.escape(t)}: ", err, re.M)}
        listed = {c.target.id for c in rv.cards if c.problems}
        return rv, code, named, listed, err

    def test_matrix(self):
        cases = {
            "clean": {},
            "x 281": {"texts": {"x": "a" * 281}},
            "x cashtags": {"texts": {"x": "$ABC and $DEF"}},
            "ig 2201": {"texts": {"instagram": "я" * 2201}},
            "ig 31 hashtags": {"texts": {"instagram": " ".join(f"#t{k}" for k in range(31))}},
            "ig 21 mentions": {"texts": {"instagram": " ".join(f"@u{k}" for k in range(21))}},
            "li 3001": {"texts": {"linkedin": "a" * 2997 + "()"}},
            "no fb token": {"env": {k: v for k, v in self.env_values.items() if k != "FB_PAGE_KOTLETA_TOKEN"}},
            "no x secret": {"env": {k: v for k, v in self.env_values.items() if k != "X_ACCESS_SECRET"}},
            "li expired": {"env": dict(self.env_values, LINKEDIN_TOKEN_EXPIRES_AT="2026-11-09T10:20:00Z")},
            "li unreadable": {"env": dict(self.env_values, LINKEDIN_TOKEN_EXPIRES_AT="soon")},
            "x month 4.90": {"ledger": [{"ts": "2026-11-01T00:00:00Z", "month": "2026-11", "rid": "r1",
                                         "op": "post", "price": "4.900", "status": "reserved", "package": "o"},
                                        {"ts": "2026-11-01T00:00:01Z", "month": "2026-11", "rid": "r1",
                                         "status": "ok"}]},
            "ig 3:4 file": {"crops": {"instagram": make_jpeg(1536, 2048)}},
            "ig png file": {"crops": {"instagram": make_png(1080, 1350)}},
            "ig unknown row": {"records": [{"ts": "2026-11-09T09:00:00Z", "target": "ig:kotleta",
                                            "network": "instagram", "status": "unknown"}]},
        }
        seen_problem = set()
        for label, case in cases.items():
            with self.subTest(label):
                rv, code, named, listed, err = self.run_case(label, **case)
                self.assertEqual(listed, named, err)
                self.assertEqual(not rv.problems, code == 0, (rv.problems, err))
                self.assertEqual(rv.missing, [])
                if listed:
                    seen_problem.add(label)
        self.assertEqual(len(seen_problem), len(cases) - 1)

    def test_empty_text_both_block_and_the_poster_names_no_target(self):
        rv, code, named, listed, err = self.run_case("empty fb", manual=True, texts={"facebook": "   "})
        self.assertEqual((code, named), (2, set()))
        self.assertIn("facebook: text is required", err)
        self.assertEqual(listed, {"fb:kotleta"})
        self.assertIn("Facebook: текст пуст", rv.problems)

    def test_stricter_on_purpose(self):
        # a missing crop: the review blocks it; the dry run blocks only Instagram's
        rv, code, named, listed, err = self.run_case("no crops", manual=True,
                                                     crops={n: None for n in pf.SEND_SIZES})
        self.assertEqual(sorted(rv.missing), sorted(pf.SEND_SIZES))
        self.assertEqual((code, named), (2, {"ig:kotleta"}))
        self.assertEqual(listed, set())
        # a missing text: the review lists it; the dry run skips the target and exits 0
        rv, code, named, listed, err = self.run_case("no x", manual=True, drop_text="x")
        self.assertEqual((code, named), (0, set()))
        self.assertEqual(listed, {"x"})
        self.assertIn("X: нет текста — нажмите «Развернуть»", rv.problems)


def Redactor_from(env_path):
    from poster.redact import Redactor

    def make():
        r = Redactor()
        r.add_env(config.load_env(env_path))
        return r
    return make
