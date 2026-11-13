"""Every B′ route over real HTTP on port 0; every vendor call faked."""
import concurrent.futures
import copy
import datetime as dt
import hashlib
import html
import json
import os
import itertools
import signal
import http.client as httpclient
import subprocess
import sys
import threading
from decimal import Decimal
from unittest import mock

from factory.authoring import budget, drafts, gemini, photos, profile
from factory.authoring.common import Refusal
from factory.panel import server
from poster import config, http, rules, state
from tests.base import CANARIES, FakeTransport, REPO_ROOT, resp
from tests import panel_fixture as pf


class CreateTest(pf.PanelCase):
    def setUp(self):
        super().setUp()
        original_hex = drafts.secrets.token_hex
        ids = itertools.count(1)
        id_patch = mock.patch("factory.authoring.drafts.secrets.token_hex",
                              side_effect=lambda n: f"{next(ids):04x}" if n == 2 else original_hex(n))
        id_patch.start(); self.addCleanup(id_patch.stop)
        self.transport = FakeTransport()
        self.srv.panel.ai.transport = self.transport
        orig = pf.make_photo(64, 48, 100)
        self.pid = pf.store_photo(self.fx, "my-photos", orig, orig, orig, "test.jpg")
        self.store = self.srv.panel.drafts
        self.draft = self.store.create(self.fx.paths.stock, "my-photos", self.pid, True)
        self.did = self.draft["id"]
        self.base = "/create/" + self.did

    def call(self, op, data=None, *, raw=None, ctype="application/json", headers=None, path=None):
        body = raw if raw is not None else json.dumps(data if data is not None else {}).encode()
        h = {"Content-Type": ctype, "Origin": f"http://{self.host}", "X-CSRF-Token": self.srv.panel.csrf}
        h.update(headers or {})
        status, hs, value = self.request("POST", path or self.base + "/" + op, body=body, headers=h)
        self.outputs.append(value.decode("utf-8", "replace"))
        return status, json.loads(value) if hs.get("content-type", "").startswith("application/json") else value

    def rows(self):
        return state.read_jsonl(self.srv.panel.ai_ledger.path)

    def topics(self):
        self.transport.add(pf.gemini_reply({"topics": pf.TOPICS}))
        return self.call("topics", {"auto": True})

    def expand(self, texts=None):
        self.call("topic", {"topic": "A pause on a city walk"})
        self.transport.add(pf.gemini_reply(texts or pf.TEXTS))
        return self.call("expand")

    def test_entry_and_create_page_tab_order_recent_and_drafts(self):
        status, headers, _ = self.get("/")
        self.assertEqual((status, headers["location"]), (302, "/create"))
        status, _, body = self.get("/create")
        self.assertEqual(status, 200)
        self.assertIn('aria-current="page">Создать</a>', body)
        self.assertIn("Медиатека", body)
        self.assertNotIn(">Файлы<", body)
        self.assertIn("Бросьте фото сюда", body)
        self.assertIn("Недавние фото", body)
        # the hint is its own row under the heading, not a tail that wraps one word alone
        self.assertIn('<h2>Недавние фото</h2><p class="recent-hint muted small">Нажмите на фото, чтобы начать пост</p>', body)
        self.assertIn("Черновики · 1", body)
        self.assertIn("ИИ · ноябрь $0.00 из $10.00", body)
        self.assertNotIn('name="folder"', body)

    def test_default_folder_modes_wrong_lane_and_race(self):
        folder = os.path.join(self.fx.paths.stock, "my-photos")
        self.assertEqual(os.stat(folder).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(os.path.join(folder, "folder.json")).st_mode & 0o777, 0o600)
        with open(os.path.join(folder, "folder.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"schema": 1, "title": "Мои фото", "lane": "photo"})
        # Exercise two first uploads through HTTP on a second, absent stock root.
        stock = os.path.join(self.root, "race-stock")
        real_paths = self.srv.panel.paths
        from dataclasses import replace
        self.srv.panel.paths = replace(real_paths, content=os.path.join(self.root, "race-content"))
        def upload(seed):
            blob = pf.make_photo(32, 24, seed)
            return self.call("", raw=blob, ctype="image/jpeg", path="/files/photos?folder=my-photos&kind=orig")
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(upload, (5, 6)))
        self.assertEqual([r[0] for r in results], [200, 200])
        path = os.path.join(self.srv.panel.paths.stock, "my-photos", "folder.json")
        pf._write_json(path, {"schema": 1, "title": "Wrong lane", "lane": "text"})
        status, result = upload(7)
        self.assertEqual(status, 409)
        self.assertIn("не из полосы фото-постов", result["error"])
        self.srv.panel.paths = real_paths

    def test_new_topics_once_request_shape_and_reservation_before_send(self):
        profile.save(self.fx.paths.content, pf.AUTHOR_PROFILE, self.panel_clock())
        def check_reserved(req):
            self.assertEqual(self.rows()[-1]["status"], "reserved")
            return pf.gemini_reply({"topics": pf.TOPICS})
        self.transport.add(check_reserved)
        status, data = self.call("topics", {"auto": True})
        self.assertEqual(status, 200)
        self.assertEqual(data["topics"], pf.TOPICS)
        for _ in range(2):
            self.assertEqual(self.get(self.base)[0], 200)
            self.assertTrue(self.call("topics", {"auto": True})[1]["skipped"])
        self.assertEqual(len(self.transport.requests), 1)
        self.assertEqual(self.store.load(self.did)["topics_auto"], "done")
        request = json.loads(self.transport.requests[0].body)
        self.assertEqual(request["response_format"]["schema"]["properties"]["topics"]["minItems"], 3)
        for name, *_ in profile.FIELDS:
            self.assertIn(profile.value(pf.AUTHOR_PROFILE, name), request["input"][0]["text"])
        self.assertIn("rid", data)
        self.assertEqual(self.rows()[-1]["status"], "ok")

    def test_topic_expand_edit_regenerate_and_full_network_limits(self):
        before = self.file_hash(self.fx.paths.rules), self.file_hash(os.path.join(self.fx.paths.poster_state, "x-ledger.jsonl"))
        for n, value in (("x", "a" * 312), ("instagram", "я" * 2300), ("instagram", " ".join("#tag" for _ in range(31))), ("linkedin", "a" * 3100)):
            texts = dict(pf.TEXTS, **{n: value})
            status, answer = self.expand(texts)
            self.assertEqual(status, 200)
            self.assertEqual(self.store.load(self.did)["variants"][n]["text"], value)
            self.assertTrue(answer["variants"][n]["errors"])
            self.assertIn(value, html.unescape(self.get(self.base)[2]))
            status, check = self.call("text", {"network": n, "text": value})
            self.assertEqual(status, 200)
            self.assertEqual(check["counts"], rules.check_text(n, value).counts)
            self.assertEqual(self.store.load(self.did)["variants"][n]["text"], value)
            self.transport.add(pf.gemini_reply({"text": value}))
            old = copy.deepcopy(self.store.load(self.did)["variants"])
            self.assertEqual(self.call("regenerate", {"network": n, "wish": "shorter"})[0], 200)
            current = self.store.load(self.did)["variants"]
            self.assertEqual(current[n]["text"], value)
            for other in old.keys() - {n}: self.assertEqual(current[other], old[other])
        self.assertEqual(before, (self.file_hash(self.fx.paths.rules), self.file_hash(os.path.join(self.fx.paths.poster_state, "x-ledger.jsonl"))))
        self.assertFalse(os.path.exists(self.fx.paths.packages))

    def test_manual_edit_nfc_refusal_and_expand_again(self):
        self.expand()
        status, answer = self.call("text", {"network": "x", "text": "cafe\u0301"})
        self.assertEqual(status, 200)
        self.assertEqual(self.store.load(self.did)["variants"]["x"]["text"], "café")
        body = self.get(self.base)[2]
        self.assertIn("Развернуть заново — правки пропадут", body)
        status, answer = self.call("text", {"network": "x", "text": "x" * 5001})
        self.assertEqual(status, 409)
        self.assertEqual(answer["error"], "текст длиннее 5 000 знаков")
        self.assertEqual(self.store.load(self.did)["variants"]["x"]["text"], "café")
        self.expand()
        self.assertTrue(all(v["source"] == "gemini" for v in self.store.load(self.did)["variants"].values()))

    def test_voice_appends_current_topic_and_never_writes_audio(self):
        blob = b"OggS" + b"fake-voice" * 100
        self.call("topic", {"topic": "Typed"})
        self.transport.add(pf.gemini_reply("слова"))
        status, value = self.call("voice", raw=blob, ctype="audio/ogg; codecs=opus")
        self.assertEqual(status, 200)
        self.assertEqual(value["topic"], "Typed слова")
        self.assertEqual(value["transcript"], "слова")
        for root, _, files in os.walk(self.fx.root):
            for name in files:
                with open(os.path.join(root, name), "rb") as fh:
                    self.assertFalse(fh.read(4) in (b"OggS", b"\x1a\x45\xdf\xa3"))
        status, _ = self.call("voice", raw=b"wrong", ctype="audio/ogg")
        self.assertEqual(status, 415)
        self.assertEqual(len(self.transport.requests), 1)

    def test_key_missing_ignores_process_key_and_leaves_manual_actions(self):
        with open(self.fx.paths.env_file, encoding="utf-8") as fh:
            lines = [line for line in fh if not line.startswith("GEMINI_API_KEY=")]
        with open(self.fx.paths.env_file, "w", encoding="utf-8") as fh: fh.writelines(lines)
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "process-only"}):
            for op in ("topics", "expand", "regenerate", "voice"):
                status, data = self.call(op, {"network": "x"}, raw=b"OggS" if op == "voice" else None,
                                         ctype="audio/ogg" if op == "voice" else "application/json")
                self.assertEqual(status, 409)
                self.assertEqual(data["error"], budget.NO_KEY)
            status, data = self.call("", {"folder": "my-photos", "photo": self.pid}, path="/create/new")
            self.assertEqual(status, 200)
            self.assertEqual(self.store.load(data["id"])["topics_auto"], "manual")
        self.assertFalse(self.transport.requests)
        self.assertEqual(self.call("topic", {"topic": "own"})[0], 200)
        self.assertIn(budget.NO_KEY, self.get("/create")[2])

    def test_cap_all_routes_after_server_restart_and_bad_cap(self):
        ledger = self.srv.panel.ai_ledger
        rid = ledger.reserve("expand", Decimal("9.99"), Decimal(10), self.did)
        ledger.settle(rid, "ok", actual=Decimal("9.99"))
        # Fresh real server and Panel prove the guard is persisted, not a session counter.
        srv = server.make_server(self.fx.paths, self.panel_clock, self.fx.machine_tz, ai_transport=self.transport)
        old = self.srv
        thread = threading.Thread(target=srv.serve_forever, daemon=True); thread.start()
        self.srv = srv
        try:
            for op in ("topics", "expand", "regenerate", "voice"):
                status, data = self.call(op, {"network": "x"}, raw=b"OggS" if op == "voice" else None,
                                         ctype="audio/ogg" if op == "voice" else "application/json")
                self.assertEqual(status, 409)
                self.assertIn("Бюджет ИИ на ноябрь исчерпан", data["error"])
                self.assertIn("поднимете месячный лимит в файле .env", data["error"])
                # the refusal names the action and keeps «до $0.NN» together
                name = {"topics": "«Темы»", "expand": "«Развернуть»", "regenerate": "«Перегенерировать»", "voice": "«Голос»"}[op]
                self.assertIn(f"исчерпан: {name} стоит до\u00a0$0.", data["error"])
                self.assertNotIn("этот запрос", data["error"])
                self.assertNotIn("$9.99", data["error"])   # the amounts stand once, in the sub row
            page = self.get(self.base)[2]
            self.assertIn("· лимит", page)
            self.assertIn("исчерпан: «Развернуть» стоит до\u00a0$0.05.", page)   # a draft: its main action
            self.assertIn("исчерпан: «Темы» стоит до\u00a0$0.02.", self.get("/create")[2])   # the start page
            self.assertEqual(page.count("$9.99 из $10.00"), 1)
        finally:
            srv.shutdown(); srv.server_close(); thread.join(5); self.srv = old
        self.assertFalse(self.transport.requests)
        with open(self.fx.paths.env_file, "a", encoding="utf-8") as fh: fh.write("AI_MONTHLY_CAP_USD=NaN\n")
        self.assertEqual(self.call("topics")[1]["error"], budget.BAD_CAP)

    def test_vendor_failure_settlement_stored_error_redaction_and_retry(self):
        for response, status, ledger_status, message in (
            (resp(503), 502, "unknown", "Не удалось получить темы от Gemini"), (resp(429), 502, "failed", "HTTP 429"),
            (http.TransportError("offline"), 504, "unknown", gemini.OFFLINE),
            (pf.gemini_reply({}, status="incomplete"), 502, "ok", gemini.INCOMPLETE),
            (pf.gemini_reply({"topics": pf.TOPICS[:2]}), 502, "ok", gemini.INVALID),
            (resp(400, {"error": {"message": CANARIES["GEMINI_API_KEY"]}}), 502, "failed", "HTTP 400")):
            self.transport.add(response)
            code, answer = self.call("topics")
            self.assertEqual(code, status)
            self.assertEqual(self.rows()[-1]["status"], ledger_status)
            self.assertIn(message, answer["error"])
            self.assertIn(message, self.store.load(self.did)["error"]["text"])
            body = self.get(self.base)[2]
            self.assertIn("Повторить · до $0.02", body)
            self.assertNotIn("HTTP 503", answer["error"])
            self.assert_no_canary(body)
        self.topics()
        self.assertIsNone(self.store.load(self.did)["error"])
        self.assert_no_canary(self.log.getvalue())
        for row in self.rows(): self.assert_no_canary(json.dumps(row))

    def test_draft_page_one_expand_button_after_the_topic_box_and_one_retry_for_topics(self):
        body = self.get(self.base)[2]
        box, button = body.index('<textarea id="topic"'), body.index('data-op="expand"')
        self.assertLess(box, button)                       # card → box → button
        self.assertIn('class="btn green" type="button" data-op="expand"', body)
        self.assertIn("Голос · до $0.02", body)
        self.assertNotIn('Голос</button>', body)
        self.transport.add(resp(503))
        self.call("topics")
        body = self.get(self.base)[2]
        self.assertRegex(body, r'<button class="btn" type="button" data-op="topics"[^>]* hidden')   # one retry button
        self.assertEqual(body.count("Повторить · до $0.02"), 1)
        self.assertIn("Не удалось получить темы от Gemini", body)
        self.assertNotIn("HTTP 503", body)

    def test_text_cards_show_one_russian_line_and_no_poster_debug_text(self):
        self.expand(dict(pf.TEXTS, x="a" * 312))
        body = html.unescape(self.get(self.base)[2])
        body = body[body.index('<main'):]   # the page's own surface, not the factory's attention list
        self.assertIn("длиннее лимита: 312 / 280 — сократите", body)
        for debug in ("weighted", "twitter-text", "UTF-16", "after little-format", "Meta documents", "never truncated"):
            self.assertNotIn(debug, body)
        self.assertEqual(body.count("312 / 280"), 1)
        status, check = self.call("text", {"network": "x", "text": "a" * 312})
        self.assertEqual(check["problems"], ["длиннее лимита: 312 / 280 — сократите"])
        self.assertEqual(check["line"], "")

    def test_draft_list_rows_name_the_stage(self):
        self.assertEqual(self.store.summaries()[0]["stage"], "new")
        self.call("topic", {"topic": "Своя тема"})
        self.assertEqual(self.store.summaries()[0]["stage"], "topic")
        self.topics()
        self.assertEqual(self.store.summaries()[0]["stage"], "topics")
        self.expand()
        self.assertEqual(self.store.summaries()[0]["stage"], "texts")
        self.expand(dict(pf.TEXTS, x="a" * 312))
        self.assertEqual(self.store.summaries()[0]["stage"], "over")
        self.store.update(self.did, lambda d: d.update(error={"op": "expand", "text": "Не удалось", "network": "", "ts": d["updated"]}))
        self.assertEqual(self.store.summaries()[0]["stage"], "error")
        page = self.get("/create")[2]
        self.assertIn(">ошибка<", page)
        self.assertRegex(page, r"\d+ \S+, \d\d:\d\d")

    def test_start_page_cue_for_recent_photos_and_no_topic_promise_without_a_key(self):
        page = self.get("/create")[2]
        self.assertIn("Нажмите на фото, чтобы начать пост", page)
        self.assertIn('<span class="nowrap">до $0.02</span>', page)
        with open(self.fx.paths.env_file, encoding="utf-8") as fh:
            lines = [l for l in fh.read().splitlines() if not l.startswith("GEMINI_API_KEY=")]
        with open(self.fx.paths.env_file, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        page = self.get("/create")[2]
        self.assertIn("нет GEMINI_API_KEY", page)
        self.assertNotIn("Gemini предложит темы", page)

    def test_long_topic_title_is_paid_stored_whole_and_rendered(self):
        title = "Т" * 81
        topics = [dict(pf.TOPICS[0], title=title)] + pf.TOPICS[1:3]
        self.transport.add(pf.gemini_reply({"topics": topics}))
        status, data = self.call("topics", {"auto": True})
        self.assertEqual(status, 200)
        self.assertEqual(data["topics"][0]["title"], title)
        self.assertEqual(self.store.load(self.did)["topics"][0]["title"], title)
        self.assertEqual(self.rows()[-1]["status"], "ok")
        self.assertIn(title, self.get(self.base)[2])
        self.assertEqual(gemini.parse("topics", pf.gemini_reply({"topics": [dict(pf.TOPICS[0], title="Т" * 1000)] * 3}).json())[0]["topics"][0]["title"], "Т" * 1000)
        with self.assertRaisesRegex(Refusal, gemini.INVALID):
            gemini.parse("topics", pf.gemini_reply({"topics": [dict(pf.TOPICS[0], title="Т" * 1001)] * 3}).json())

    def test_exif_refused_before_reserve_or_transport(self):
        path = photos.file_path(self.fx.paths.stock, "my-photos", self.pid, "view")
        with open(path, "wb") as fh: fh.write(pf.make_exif6(64, 48, 1))
        code, answer = self.call("topics")
        self.assertEqual(code, 409)
        self.assertIn("EXIF", answer["error"])
        self.assertFalse(self.transport.requests)
        self.assertFalse(self.rows())

    def test_concurrent_calls_same_draft_global_slots_and_typing_during_ai(self):
        fake = pf.FakeGemini(); self.srv.panel.ai.transport = fake
        self.call("topic", {"topic": "Original"})
        other = self.store.create(self.fx.paths.stock, "my-photos", self.pid, True)
        third = self.store.create(self.fx.paths.stock, "my-photos", self.pid, True)
        fake.hold = {self.did, other["id"]}
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.call, "expand")
            self.assertTrue(fake.entered.wait(5))
            self.assertEqual(self.call("expand")[0], 409)
            self.assertEqual(self.call("topic", {"topic": "Typed during call"})[0], 200)
            fake.entered.clear()
            second = pool.submit(self.call, "topics", path="/create/" + other["id"] + "/topics")
            self.assertTrue(fake.entered.wait(5))
            code, data = self.call("topics", path="/create/" + third["id"] + "/topics")
            self.assertEqual(code, 409)
            self.assertIn("двумя запросами", data["error"])
            fake.release.set()
            self.assertEqual(first.result(5)[0], 200)
            self.assertEqual(second.result(5)[0], 200)
        self.assertEqual(self.store.load(self.did)["topic"], "Typed during call")
        self.assertEqual(len(fake.requests), 2)

    def test_profile_form_save_refusal_and_no_script(self):
        values = {name: profile.value(pf.AUTHOR_PROFILE, name) for name, *_ in profile.FIELDS}
        status, headers, _ = self.post("/create/profile", values)
        self.assertEqual((status, headers["location"]), (303, "/create/profile?saved=1"))
        body = self.get("/create/profile?saved=1")[2]
        self.assertIn("Профиль сохранён", body)
        self.assertNotIn("create.js", body)
        for name, label, limit, _ in profile.FIELDS:
            self.assertIn(f'<span>{label}</span><span class="muted small limit">до {limit} знаков</span>', body)
        self.assertNotIn("profile.json", body)   # no file path in the explainer
        old = profile.load(self.fx.paths.content)
        status, _, body = self.post("/create/profile", dict(values, who="w" * 601))
        self.assertEqual(status, 409)
        self.assertIn("w" * 601, body)
        self.assertEqual(profile.load(self.fx.paths.content), old)

    def test_route_security_and_validation_every_json_and_audio_path(self):
        routes = [("/create/new", "application/json", b"{}")]
        routes += [(self.base + "/" + op, "application/json", b"{}") for op in ("topics", "topic", "expand", "regenerate", "text")]
        routes += [(self.base + "/voice", "audio/ogg", b"OggS")]
        before = self.state_hashes()
        for path, ctype, raw in routes:
            for changed, expected in (({"Host": "foreign.example"}, 421), ({"Origin": None}, 403),
                                      ({"Origin": "http://foreign.example"}, 403), ({"X-CSRF-Token": "wrong"}, 403),
                                      ({"X-CSRF-Token": None}, 403), ({"Content-Length": "9999999"}, 413),
                                      ({"Content-Type": "text/plain"}, 415), ({"Content-Length": None}, 411)):
                status, _ = self.call("", raw=raw, ctype=ctype, headers=changed, path=path)
                self.assertEqual(status, expected, (path, changed))
        self.assertEqual(self.state_hashes(), before)
        self.assertFalse(self.transport.requests)
        for raw in (b"[]", b"null", b"1", b"{", b'"str"', b"\xff"):
            self.assertEqual(self.call("topics", raw=raw)[0], 400)
        for bad in ([], {}, None, 1, float("nan"), "x" * 2001):
            self.assertIn(self.call("topic", {"topic": bad})[0], (400, 409))
        for path in ("/create/../.env", "/create/not-an-id", "/create/../../.env"):
            self.assertEqual(self.get(path)[0], 404)
        for path in ("/create", self.base, "/create/profile"):
            self.assertEqual(self.request("GET", path, headers={"Host": "foreign.example"})[0], 421)
        self.assertEqual(self.post("/create/profile", {}, csrf=False)[0], 403)

    def test_draft_chip_and_snapshot_does_not_rebuild_on_draft_writes(self):
        snap = self.srv.panel.holder.get()
        self.call("topic", {"topic": "Own topic"})
        self.assertIs(self.srv.panel.holder.get(), snap)
        self.assertIn("черновик", self.get("/files?folder=my-photos")[2])
        restarted = drafts.Store(self.fx.paths.content, self.panel_clock, self.fx.machine_tz)
        self.assertEqual(restarted.load(self.did)["topic"], "Own topic")
        self.assertEqual(self.call("", {"folder": "my-photos", "photo": self.pid}, path="/create/new")[0], 200)

    def test_factory_check_problem_lines_do_not_change_with_default_folder(self):
        from factory import cli
        import io
        def check():
            out, err = io.StringIO(), io.StringIO()
            code = cli.main(["check"], environ=self.fx.environ, clock=self.fx.clock, stdout=out, stderr=err)
            return code, out.getvalue(), err.getvalue()
        # This fixture already has the folder; compare a fresh data fixture before/after.
        fx = pf.build_data(os.path.join(self.root, "comparison")); old = self.fx; self.fx = fx
        before = check()
        photos.ensure_default(fx.paths.stock)
        after = check()
        self.fx = old
        self.assertEqual((before[0], before[2]), (after[0], after[2]))
        self.assertNotIn("my-photos", after[1] + after[2])


    def test_real_process_restart_keeps_draft_and_budget_on_same_port(self):
        self.call("topic", {"topic": "Saved before process restart"})
        self.call("text", {"network": "x", "text": "An edited draft."})
        self.store.update(self.did, lambda d: d.update(topics_auto="done"))
        ledger = self.srv.panel.ai_ledger
        rid = ledger.reserve("topics", Decimal("9.99"), Decimal(10), self.did)
        ledger.settle(rid, "ok", actual=Decimal("9.99"))
        def start(port):
            code = "\n".join([
                f"import sys, json, io, datetime as dt; sys.path.insert(0, {REPO_ROOT!r})",
                "from factory.panel import server",
                "from factory import paths",
                "from tests import panel_fixture as pf",
                f"now = dt.datetime.fromisoformat({pf.NOW.isoformat()!r})",
                f"srv = server.make_server(paths.resolve(dict({self.fx.environ!r})), lambda: now, 'UTC', {port},",
                "                          log=io.StringIO(), ai_transport=pf.FakeGemini())",
                "print(json.dumps({'port': srv.port, 'csrf': srv.panel.csrf}), flush=True)",
                "try:",
                "    srv.serve_forever()",
                "except KeyboardInterrupt:",
                "    pass",
                "finally:",
                "    srv.server_close()",
            ])
            proc = subprocess.Popen([sys.executable, "-I", "-B", "-u", "-c", code],
                                    env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            def cleanup():
                if proc.poll() is None: proc.kill()
                proc.wait(10); proc.stdout.close(); proc.stderr.close()
            self.addCleanup(cleanup)
            return proc, json.loads(proc.stdout.readline())
        proc, info = start(0)
        for attempt in range(2):
            port = info["port"]
            def request(method, path, data=None):
                conn = httpclient.HTTPConnection("127.0.0.1", port, timeout=10)
                body = json.dumps(data).encode() if data is not None else None
                headers = {"Host": f"127.0.0.1:{port}", "Origin": f"http://127.0.0.1:{port}",
                           "Content-Type": "application/json", "X-CSRF-Token": info["csrf"]}
                conn.request(method, path, body, headers)
                response = conn.getresponse(); result = response.read().decode(); conn.close()
                return response.status, result
            code, body = request("GET", self.base)
            self.assertEqual(code, 200)
            self.assertIn("Saved before process restart", body)
            self.assertIn("An edited draft.", body)
            self.assertIn("ИИ · ноябрь $9.99 из $10.00", body)
            code, body = request("POST", self.base + "/topics", {})
            self.assertEqual(code, 409)
            self.assertIn("Бюджет ИИ на ноябрь исчерпан", body)
            self.assertIn("ИИ · ноябрь $9.99 из $10.00", body)
            proc.send_signal(signal.SIGINT)
            self.assertEqual(proc.wait(10), 0)
            if attempt == 0: proc, info = start(port)
