"""Topics from the author's themes and cases, posts without a photo (authoring.md §19.8, §19.11).

Every Gemini call goes to a FakeTransport or FakeGemini and every publish to FakePoster with a
scripted poster transport; no test opens a non-loopback socket (tests/base.py guard). Every
reply here is a synthetic fixture, not a vendor observation.
"""
import datetime as dt
import html
import io
import itertools
import json
import os
import re
import stat
import subprocess
import threading
import unicodedata
import urllib.parse
from decimal import Decimal
from unittest import mock

from factory import cli as fcli
from factory.authoring import budget, cases, drafts, gemini, photos, profile, prompts, send
from factory.authoring.common import Refusal
from factory.panel import model as M, server, strings as S
from poster import config, package as poster_package, state as poster_state
from tests.base import CANARIES, Clock, FakeTransport, PosterTestCase, REPO_ROOT, make_jpeg, resp
from tests import panel_fixture as pf

NOW = pf.NOW
A, B, C = pf.CASE_IDS
INSTRUCTIONS = (   # authoring.md §19.5, word for word
    "You help the author write social posts about their own themes and their own cases: what "
    "they automated, with which AI tools, and what came of it. The subject of a post is the "
    "topic below. A photo, when one is attached, only illustrates the post: never take the "
    "subject from it. Never invent facts beyond the topic, the author profile, the case below "
    "and what the photo shows: no invented cases, clients, numbers, dates, tools or results. "
    "When a fact is not given, leave it out. Never name people in the photo. Do not describe "
    "the photo's technical qualities.")
TOPICS_TASK = (
    "Suggest 3 to 5 distinct post topics. Each topic draws either on the author's themes (the "
    "profile line \"Author's themes\") or on exactly one of the cases listed above; never combine "
    "cases and never suggest a case that is not listed. title: at most 80 characters, in "
    "Russian. angle: one sentence in Russian saying what the post would say and for whom (at "
    "most 1000 characters). case: the id of the case the topic draws on, or an empty string "
    "when it draws on the author's themes.")
ANGLES_TASK = (
    "Suggest 3 to 5 distinct angles for a post about the case above. Every topic draws on that "
    "case only, so case is its id. title: at most 80 characters, in Russian. angle: one "
    "sentence in Russian saying what the post would say and for whom (at most 1000 "
    "characters).")
NONE_CHOSEN = ("Case: none chosen. Do not present any project, client or result as the author's own "
               "experience unless the topic or the profile states it.")


def at_limits(char="\U00010000"):
    return {name: char * limit for name, _, limit, _ in cases.FIELDS}


# ---------------------------------------------------------------- the store (items 1, 2)

class CasesStoreTest(PosterTestCase):
    def setUp(self):
        super().setUp()
        self.content = os.path.join(self.root, "content")
        hexes = itertools.count(0x10)
        original = cases.secrets.token_hex   # the same module also names the atomic writes' temp files
        patch = mock.patch("factory.authoring.cases.secrets.token_hex",
                           side_effect=lambda n: f"{next(hexes):08x}" if n == 4 else original(n))
        patch.start()
        self.addCleanup(patch.stop)

    def file(self):
        return os.path.join(self.content, cases.FILE)

    def test_add_edit_delete_modes_order_and_ids(self):
        self.assertEqual(cases.load(self.content), {"schema": 1, "cases": []})
        first = cases.save(self.content, pf.CASES[0], NOW)
        second = cases.save(self.content, pf.CASES[1], NOW + dt.timedelta(minutes=1))
        self.assertEqual((first["id"], second["id"]), ("c-00000010", "c-00000011"))
        self.assertEqual(stat.S_IMODE(os.stat(self.file()).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.content).st_mode), 0o700)
        stored = cases.listed(self.content)
        self.assertEqual([c["id"] for c in stored], [second["id"], first["id"]])   # new first
        self.assertEqual(stored[1]["created"], "2026-11-11T09:40:00Z")
        before = json.dumps(stored[1], ensure_ascii=False)
        edited = cases.save(self.content, dict(pf.CASES[1], result="Иначе"), NOW + dt.timedelta(hours=1),
                            second["id"])
        stored = cases.listed(self.content)
        self.assertEqual(json.dumps(stored[1], ensure_ascii=False), before)   # the other: byte-identical
        self.assertEqual((edited["result"], edited["created"], edited["updated"]),
                         ("Иначе", second["created"], "2026-11-11T10:40:00Z"))
        cases.delete(self.content, first["id"], NOW)
        self.assertEqual([c["id"] for c in cases.listed(self.content)], [second["id"]])
        with self.assertRaises(Refusal) as e:
            cases.delete(self.content, first["id"], NOW)
        self.assertEqual(e.exception.status, 404)

    def test_a_taken_id_draws_again(self):
        drawn = iter(["0000000a", "0000000a", "0000000b"])
        original = cases.secrets.token_hex
        with mock.patch("factory.authoring.cases.secrets.token_hex",
                        side_effect=lambda n: next(drawn) if n == 4 else original(n)):
            a = cases.save(self.content, pf.CASES[0], NOW)
            b = cases.save(self.content, pf.CASES[1], NOW)
        self.assertEqual((a["id"], b["id"]), ("c-0000000a", "c-0000000b"))

    def test_limits_blank_fields_and_the_30_cap(self):
        cases.save(self.content, pf.CASES[0], NOW)
        before = open(self.file(), "rb").read()
        for change, message in ((dict(title="а" * 81), "Название: не больше 80 знаков"),
                                (dict(result="   "), "Что вышло: заполните"),
                                (dict(when="а" * 41), "Когда: не больше 40 знаков"),
                                (dict(tools=""), "Чем: инструменты и нейросети: заполните")):
            with self.assertRaises(Refusal) as e:
                cases.save(self.content, dict(pf.CASES[0], **change), NOW)
            self.assertEqual((e.exception.status, e.exception.message), (409, message))
        for bad in ([], {"title": 1}):
            with self.assertRaises(Refusal) as e:
                cases.save(self.content, bad if isinstance(bad, list) else dict(pf.CASES[0], **bad), NOW)
            self.assertEqual(e.exception.status, 400)
        self.assertEqual(open(self.file(), "rb").read(), before)
        # every field at its limit is accepted whole (NFC, four-byte characters, never cut)
        whole = cases.save(self.content, at_limits(), NOW)
        for name, _, limit, _ in cases.FIELDS:
            self.assertEqual(whole[name], "\U00010000" * limit)
        decomposed = cases.save(self.content, dict(pf.CASES[2], title="ёж"), NOW)
        self.assertEqual(decomposed["title"], unicodedata.normalize("NFC", "ёж"))
        for _ in range(27):
            cases.save(self.content, pf.CASES[2], NOW)
        self.assertEqual(len(cases.listed(self.content)), 30)
        before = open(self.file(), "rb").read()
        with self.assertRaises(Refusal) as e:
            cases.save(self.content, pf.CASES[2], NOW)
        self.assertEqual(e.exception.message, "кейсов уже 30 — удалите ненужные")
        self.assertEqual(open(self.file(), "rb").read(), before)
        # editing at the cap still works
        cid = cases.listed(self.content)[0]["id"]
        self.assertEqual(cases.save(self.content, pf.CASES[1], NOW, cid)["title"], pf.CASES[1]["title"])

    def test_an_invalid_file_refuses_and_a_bad_id_is_404(self):
        os.makedirs(self.content, 0o700)
        for raw in ("{", '{"schema": 2, "cases": []}', '{"schema": 1, "cases": [{"id": "x"}]}'):
            with open(self.file(), "w", encoding="utf-8") as fh:
                fh.write(raw)
            with self.assertRaises(Refusal) as e:
                cases.load(self.content)
            self.assertIn("content/cases.json", e.exception.message)
        os.unlink(self.file())
        for cid in ("../x", "c-XYZ", "c-0000000g", "c-000000001"):
            with self.assertRaises(Refusal) as e:
                cases.save(self.content, pf.CASES[0], NOW, cid)
            self.assertEqual(e.exception.status, 404)
            self.assertIsNone(cases.find([], cid))

    def test_cases_json_is_ignored_by_git(self):
        found = subprocess.run(["git", "check-ignore", "-v", "content/cases.json", "content/.cases.lock"],
                               cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertEqual(len(found.stdout.splitlines()), 2)

    def test_prompt_blocks(self):
        self.assertEqual(cases.gist([]), "Cases: none recorded.")
        stored = [dict(c, id=i) for c, i in zip(pf.CASES, pf.CASE_IDS)]
        self.assertEqual(cases.gist(stored).splitlines(), [
            "Cases (the author's own records; id, title and tools only):",
            f"{A}: {pf.CASES[0]['title']} (tools: {pf.CASES[0]['tools']})",
            f"{B}: {pf.CASES[1]['title']} (tools: {pf.CASES[1]['tools']})",
            f"{C}: {pf.CASES[2]['title']} (tools: {pf.CASES[2]['tools']})"])
        self.assertEqual(cases.record(stored[1]).splitlines(), [
            f"Case {B} (the only source of facts about it):", f"Title: {pf.CASES[1]['title']}",
            f"What was automated: {pf.CASES[1]['what']}", f"Tools: {pf.CASES[1]['tools']}",
            f"Result: {pf.CASES[1]['result']}", "When: октябрь 2026"])
        self.assertNotIn("When:", cases.record(stored[0]))   # only when not empty


# ---------------------------------------------------------------- the routes (items 1, 2, 5)

class CasesPanel(pf.PanelCase):
    def setUp(self):
        super().setUp()
        original = drafts.secrets.token_hex
        ids = itertools.count(1)
        patch = mock.patch("factory.authoring.drafts.secrets.token_hex",
                           side_effect=lambda n: f"{next(ids):04x}" if n == 2 else original(n))
        patch.start()
        self.addCleanup(patch.stop)
        self.transport = FakeTransport()
        self.srv.panel.ai.transport = self.transport
        self.store = self.srv.panel.drafts
        profile.save(self.fx.paths.content, pf.AUTHOR_PROFILE, NOW)
        orig = pf.make_photo(64, 48, 100)
        self.pid = pf.store_photo(self.fx, "my-photos", orig, orig, orig, "case.jpg")

    def cases_file(self):
        return os.path.join(self.fx.paths.content, cases.FILE)

    def with_cases(self):
        return pf.save_cases(self.fx)

    def page(self, path):
        status, headers, body = self.get(path)
        return status, headers, html.unescape(body)

    def call(self, path, data=None, *, headers=None):
        h = {"Content-Type": "application/json", "Origin": f"http://{self.host}",
             "X-CSRF-Token": self.srv.panel.csrf}
        h.update(headers or {})
        status, hs, value = self.request("POST", path, body=json.dumps(data if data is not None else {}).encode(),
                                         headers=h)
        self.outputs.append(value.decode("utf-8", "replace"))
        return status, json.loads(value) if hs.get("content-type", "").startswith("application/json") else value

    def rows(self):
        return poster_state.read_jsonl(self.srv.panel.ai_ledger.path)

    def bare(self, case=None):
        """A draft without a photo, created as the routes do."""
        return self.store.create(self.fx.paths.stock, None, None, True, case)["id"]

    def bodies(self):
        return [json.loads(r.body) for r in self.transport.requests]


class CasesRouteTest(CasesPanel):
    def test_add_edit_delete_through_the_form_and_a_restart(self):
        status, headers, _ = self.post("/create/cases/save", pf.CASES[1])
        self.assertEqual(status, 303)
        cid = cases.listed(self.fx.paths.content)[0]["id"]
        self.assertEqual(headers["location"], f"/create/cases?saved={cid}#case-{cid}")
        self.post("/create/cases/save", pf.CASES[2])
        _, _, body = self.page(f"/create/cases?saved={cid}")
        self.assertIn(f'<article class="case" id="case-{cid}"><p class="k-ok case-saved" role="status">Кейс сохранён</p>', body)
        titles = re.findall(r'<h3 class="case-title">([^<]+)</h3>', body)
        self.assertEqual(titles, [pf.CASES[2]["title"], pf.CASES[1]["title"]])   # new first
        for word in ("Пост по кейсу", "Изменить", "Удалить", "Новый кейс", "Добавить кейс",
                     "Что автоматизировали", "до 600 знаков"):
            self.assertIn(word, body)
        other = json.dumps(cases.listed(self.fx.paths.content)[0], ensure_ascii=False)
        _, _, edit = self.page(f"/create/cases?edit={cid}")
        self.assertIn(f'<input type="hidden" name="id" value="{cid}">', edit)
        self.assertIn(pf.CASES[1]["what"], edit)
        self.assertIn(">Сохранить</button>", edit)
        self.assertIn(">Отмена</a>", edit)
        status, headers, _ = self.post("/create/cases/save", dict(pf.CASES[1], result="Новый итог", id=cid))
        self.assertEqual(status, 303)
        stored = cases.listed(self.fx.paths.content)
        self.assertEqual(json.dumps(stored[0], ensure_ascii=False), other)
        self.assertEqual(stored[1]["result"], "Новый итог")
        # a restart reads the same list
        again = server.make_server(self.fx.paths, self.panel_clock, self.fx.machine_tz, 0, log=io.StringIO())
        thread = threading.Thread(target=again.serve_forever, daemon=True)
        thread.start()
        try:
            import http.client
            conn = http.client.HTTPConnection("127.0.0.1", again.port, timeout=30)
            conn.request("GET", "/create/cases", headers={"Host": f"127.0.0.1:{again.port}"})
            restarted = html.unescape(conn.getresponse().read().decode())
            conn.close()
        finally:
            again.shutdown()
            again.server_close()
            thread.join(5)
        self.assertEqual(re.findall(r'<h3 class="case-title">([^<]+)</h3>', restarted),
                         [pf.CASES[2]["title"], pf.CASES[1]["title"]])
        self.assertIn("Новый итог", restarted)
        # delete, behind its dialog
        self.assertIn(f'data-open="dlg-case-{cid}">Удалить</button>', restarted)
        self.assertIn("Удалить кейс?", restarted)
        self.assertIn("Черновики с этим кейсом останутся, но тексты по нему писать не получится.", restarted)
        status, headers, _ = self.post("/create/cases/delete", {"id": cid})
        self.assertEqual((status, headers["location"]), (303, "/create/cases?deleted=1"))
        _, _, body = self.page("/create/cases?deleted=1")
        self.assertIn('role="status">Кейс удалён</p>', body)
        self.assertNotIn(pf.CASES[1]["title"], body)

    def test_refusals_keep_the_text_and_write_nothing(self):
        self.post("/create/cases/save", pf.CASES[0])
        before = self.file_hash(self.cases_file())
        for change, message in ((dict(title="я" * 81), "Название: не больше 80 знаков"),
                                (dict(result=""), "Что вышло: заполните"),
                                (dict(when="я" * 41), "Когда: не больше 40 знаков")):
            values = dict(pf.CASES[1], **change)
            status, _, body = self.post("/create/cases/save", values)
            body = html.unescape(body)
            self.assertEqual(status, 409, message)
            self.assertIn(f'role="alert">{message}</p>', body)
            for name in ("title", "what", "tools", "when"):
                if values[name]:
                    self.assertIn(values[name], body)
            self.assertEqual(self.file_hash(self.cases_file()), before)
        for path, fields in (("/create/cases/save", dict(pf.CASES[1], id="c-ffffffff")),
                             ("/create/cases/delete", {"id": "c-ffffffff"}),
                             ("/create/cases/delete", {"id": "../x"}),
                             ("/create/cases/start", {"id": "c-ffffffff"})):
            status, _, body = self.post(path, fields)
            self.assertEqual(status, 404, path)
            self.assertIn("кейс не найден", body)
        self.assertEqual(self.file_hash(self.cases_file()), before)
        self.assertFalse(self.store.summaries())
        _, _, body = self.page("/create/cases?edit=c-ffffffff")
        self.assertIn('role="alert">кейс не найден</p>', body)
        # the 31st
        for _ in range(29):
            cases.save(self.fx.paths.content, pf.CASES[2], NOW)
        self.assertEqual(len(cases.listed(self.fx.paths.content)), 30)
        before = self.file_hash(self.cases_file())
        status, _, body = self.post("/create/cases/save", pf.CASES[1])
        self.assertEqual(status, 409)
        self.assertIn("кейсов уже 30 — удалите ненужные", body)
        self.assertEqual(self.file_hash(self.cases_file()), before)
        _, _, body = self.page("/create/cases")
        self.assertIn('<p class="muted case-full">кейсов уже 30 — удалите ненужные</p>', body)
        self.assertNotIn("Добавить кейс", body)

    def test_a_canary_key_is_stored_and_shown_masked(self):
        canary = CANARIES["GEMINI_API_KEY"]
        self.post("/create/cases/save", dict(pf.CASES[0], result="ключ " + canary))
        with open(self.cases_file(), encoding="utf-8") as fh:
            self.assertNotIn(canary, fh.read())
        _, _, body = self.page("/create/cases")
        self.assertNotIn(canary, body)
        self.assertIn("ключ ", body)

    def test_foreign_requests_write_nothing(self):
        cid = self.with_cases()[0]["id"]
        before = (self.file_hash(self.cases_file()), self.state_hashes())
        for path, fields in (("/create/cases/save", pf.CASES[1]), ("/create/cases/delete", {"id": cid}),
                             ("/create/cases/start", {"id": cid})):
            self.assertEqual(self.post(path, fields, origin="http://evil.example")[0], 403, path)
            self.assertEqual(self.post(path, fields, csrf=False)[0], 403, path)
            self.assertEqual(self.post(path, fields, csrf="wrong")[0], 403, path)
            self.assertEqual(self.post(path, fields, host="evil.example")[0], 421, path)
            self.assertEqual(self.post(path, fields, ctype="text/plain")[0], 415, path)
        self.assertEqual((self.file_hash(self.cases_file()), self.state_hashes()), before)
        self.assertFalse(os.path.exists(os.path.join(self.fx.paths.content, "drafts")))
        self.assertEqual(self.get("/create/cases", host="evil.example")[0], 421)

    def test_post_from_a_case_starts_a_draft_without_a_photo(self):
        self.with_cases()
        status, headers, _ = self.post("/create/cases/start", {"id": B})
        self.assertEqual(status, 303)
        did = headers["location"][len("/create/"):]
        self.assertRegex(did, r"^2026-11-11-post-[0-9a-f]{4}$")
        d = self.store.load(did)
        self.assertEqual((d["folder"], d["photo"], d["case"], d["topics_auto"]), (None, None, B, "pending"))
        # its automatic topics request sends that case's whole record and the angles task
        self.transport.add(pf.gemini_reply({"topics": pf.case_topics(B)}))
        status, data = self.call(f"/create/{did}/topics", {"auto": True})
        self.assertEqual(status, 200)
        prompt = self.bodies()[0]["input"][0]["text"]
        self.assertIn(cases.record(cases.find(cases.listed(self.fx.paths.content), B)), prompt)
        self.assertTrue(prompt.endswith(ANGLES_TASK))
        self.assertNotIn("Cases (the author's own records", prompt)
        self.assertNotIn(pf.CASES[0]["title"], prompt)
        self.assertEqual({t["case"] for t in data["topics"]}, {B})
        _, _, body = self.page(f"/create/{did}")
        self.assertEqual(body.count(f'<span class="topic-case small muted" title="кейс: {pf.CASES[1]["title"]}">'), 5)
        self.assertIn(f'<span class="case-words">Кейс: {pf.CASES[1]["title"]}</span>', body)


# ---------------------------------------------------------------- prompts and topics (items 3, 4, 11)

class PromptTest(CasesPanel):
    def test_instructions_tasks_and_schema(self):
        self.assertEqual(prompts.INSTRUCTIONS, INSTRUCTIONS)
        self.assertEqual(prompts.SCHEMAS["topics"]["properties"]["topics"]["items"],
                         {"type": "object", "properties": {"title": {"type": "string"}, "angle": {"type": "string"},
                                                           "case": {"type": "string"}},
                          "required": ["title", "angle", "case"], "additionalProperties": False})
        # the five-argument call of B′ builds «none» lines
        text = prompts.build("topics", pf.AUTHOR_PROFILE, {"topic": ""})
        self.assertEqual(text, INSTRUCTIONS + "\n" + profile.prompt(pf.AUTHOR_PROFILE) +
                         "\nCases: none recorded.\n" + TOPICS_TASK)
        for op in ("expand", "regenerate"):
            text = prompts.build(op, pf.AUTHOR_PROFILE, {"topic": "t", "variants": {"x": {"text": "y"}}}, "x", "")
            self.assertIn("\n" + NONE_CHOSEN + "\n", text)
            self.assertTrue(text.startswith(INSTRUCTIONS + "\n" + profile.prompt(pf.AUTHOR_PROFILE) + "\n" + NONE_CHOSEN))

    def topics_for(self, did, reply):
        self.transport.add(pf.gemini_reply({"topics": reply}))
        return self.call(f"/create/{did}/topics")

    def test_topics_request_carries_themes_and_gists_and_never_the_photo(self):
        self.with_cases()
        photo_did = self.store.create(self.fx.paths.stock, "my-photos", self.pid, True)["id"]
        for did in (photo_did, self.bare()):
            self.transport.requests.clear()
            status, _ = self.topics_for(did, pf.CASE_TOPICS)
            self.assertEqual(status, 200)
            body = self.bodies()[0]
            self.assertEqual(len(body["input"]), 1)              # the text alone: no image block
            self.assertEqual(body["input"][0]["type"], "text")
            self.assertEqual(body["response_format"]["schema"], prompts.SCHEMAS["topics"])
            self.assertFalse(body["store"])
            prompt = body["input"][0]["text"]
            self.assertIn("Author's themes: " + pf.AUTHOR_PROFILE["topics"], prompt)
            for case, cid in zip(pf.CASES, pf.CASE_IDS):
                self.assertIn(f"{cid}: {case['title']} (tools: {case['tools']})", prompt)
                for name in ("what", "result"):
                    self.assertNotIn(case[name], prompt)
            self.assertNotIn("октябрь 2026", prompt)               # no «when» either
            self.assertTrue(prompt.endswith(TOPICS_TASK))
            self.assertTrue(prompt.startswith(INSTRUCTIONS + "\n"))

    def test_without_cases_the_request_says_none_recorded(self):
        self.topics_for(self.bare(), pf.TOPICS)
        self.assertIn("\nCases: none recorded.\n", self.bodies()[0]["input"][0]["text"])

    def test_a_topic_keeps_only_a_stored_case_and_a_case_draft_forces_its_own(self):
        self.with_cases()
        did = self.bare()
        reply = [dict(t, case=c) for t, c in zip(pf.TOPICS, (A, "", C, "c-deadbeef", B))]
        status, data = self.topics_for(did, reply)
        self.assertEqual([t["case"] for t in data["topics"]], [A, "", C, "", B])
        self.assertEqual([t["case"] for t in self.store.load(did)["topics"]], [A, "", C, "", B])
        _, _, body = self.page(f"/create/{did}")
        for cid, case in ((A, pf.CASES[0]), (C, pf.CASES[2]), (B, pf.CASES[1])):
            self.assertIn(f'data-case="{cid}"', body)
            # the whole title stays in the DOM and in `title` (one line with an ellipsis on screen)
            self.assertIn(f'<span class="topic-case small muted" title="кейс: {case["title"]}">кейс: {case["title"]}</span>', body)
        self.assertEqual(body.count('class="topic-case'), 3)
        self.assertNotIn("c-deadbeef", body)
        # on a draft that carries case A, every topic names A
        own = self.bare(A)
        status, data = self.topics_for(own, [dict(t, case=c) for t, c in zip(pf.TOPICS, ("", B, A, "", "c-deadbeef"))])
        self.assertEqual({t["case"] for t in self.store.load(own)["topics"]}, {A})
        # a deleted case shows «кейс удалён» on its card
        cases.delete(self.fx.paths.content, C, NOW)
        _, _, body = self.page(f"/create/{did}")
        self.assertIn('<span class="topic-case small muted" title="кейс удалён">кейс удалён</span>', body)

    def test_a_reply_case_longer_than_20_or_not_a_string_is_refused(self):
        for bad in ("c" * 21, 7, None):
            with self.assertRaises(Refusal):
                gemini.parse("topics", pf.gemini_reply({"topics": [dict(pf.TOPICS[0], case=bad)] * 3}).json())
        value, _ = gemini.parse("topics", pf.gemini_reply({"topics": [dict(pf.TOPICS[0], case="")] * 3}).json())
        self.assertEqual(value["topics"][0]["case"], "")

    def expand_on(self, did):
        self.call(f"/create/{did}/topic", {"topic": "Отчёт за пять минут"})
        self.transport.add(pf.gemini_reply(pf.TEXTS))
        status, _ = self.call(f"/create/{did}/expand")
        self.assertEqual(status, 200)
        return self.bodies()[-1]

    def test_texts_use_the_case_the_profile_and_the_photo_only_when_there_is_one(self):
        self.with_cases()
        record = cases.record(cases.find(cases.listed(self.fx.paths.content), A))
        photo_did = self.store.create(self.fx.paths.stock, "my-photos", self.pid, True, A)["id"]
        body = self.expand_on(photo_did)
        prompt = body["input"][0]["text"]
        self.assertIn(record, prompt)
        self.assertIn(profile.prompt(pf.AUTHOR_PROFILE), prompt)
        self.assertTrue(prompt.startswith(INSTRUCTIONS + "\n"))
        self.assertEqual([b["type"] for b in body["input"]], ["text", "image"])
        bare = self.bare(A)
        body = self.expand_on(bare)
        self.assertEqual([b["type"] for b in body["input"]], ["text"])
        self.assertIn(record, body["input"][0]["text"])
        # regenerate does the same, and an edit of «Что вышло» reaches the next request
        cases.save(self.fx.paths.content, dict(pf.CASES[0], result="Теперь за три минуты"), NOW, A)
        self.transport.add(pf.gemini_reply({"text": "Shorter."}))
        status, _ = self.call(f"/create/{bare}/regenerate", {"network": "x", "wish": ""})
        self.assertEqual(status, 200)
        body = self.bodies()[-1]
        self.assertEqual([b["type"] for b in body["input"]], ["text"])
        self.assertIn("Result: Теперь за три минуты", body["input"][0]["text"])
        self.assertTrue(body["input"][0]["text"].startswith(INSTRUCTIONS + "\n"))
        self.transport.add(pf.gemini_reply({"text": "Shorter."}))
        self.call(f"/create/{photo_did}/regenerate", {"network": "x", "wish": ""})
        self.assertEqual([b["type"] for b in self.bodies()[-1]["input"]], ["text", "image"])
        # without a case, both say «none chosen»
        plain = self.bare()
        self.assertIn("\n" + NONE_CHOSEN + "\n", self.expand_on(plain)["input"][0]["text"])
        self.transport.add(pf.gemini_reply({"text": "Shorter."}))
        self.call(f"/create/{plain}/regenerate", {"network": "x", "wish": ""})
        self.assertIn("\n" + NONE_CHOSEN + "\n", self.bodies()[-1]["input"][0]["text"])


# ---------------------------------------------------------------- nothing invented (item 12)

class DanglingCaseTest(CasesPanel):
    def test_a_deleted_case_refuses_the_three_text_calls_before_any_spend(self):
        self.with_cases()
        did = self.bare(B)
        self.call(f"/create/{did}/topic", {"topic": "Голос в задачи"})
        cases.delete(self.fx.paths.content, B, NOW)
        ledger_before = self.file_hash(self.srv.panel.ai_ledger.path)
        for op, data in (("topics", {}), ("topics", {"auto": True}), ("expand", {}),
                         ("regenerate", {"network": "x", "wish": ""})):
            status, reply = self.call(f"/create/{did}/{op}", data)
            self.assertEqual((status, reply["error"]), (409, "кейс этого черновика удалён — нажмите «убрать»"), op)
        self.assertEqual(self.transport.requests, [])
        self.assertEqual(self.file_hash(self.srv.panel.ai_ledger.path), ledger_before)
        d = self.store.load(did)
        self.assertIsNone(d["error"])
        self.assertEqual(d["topics_auto"], "pending")
        _, _, body = self.page(f"/create/{did}")
        self.assertIn('<p class="case-line k-bad"><span class="case-words">Кейс удалён — нажмите «убрать», чтобы писать тексты</span>', body)
        for op in ("topics", "expand"):
            self.assertRegex(body, rf'data-op="{op}" disabled title="Кейс удалён — нажмите «убрать», чтобы писать тексты"')
        self.assertNotIn('class="create-notice', body)   # said once, by the case line
        # a card tap naming the deleted case is refused; «убрать» clears it
        status, reply = self.call(f"/create/{did}/topic", {"topic": "x", "case": B})
        self.assertEqual((status, reply["error"]), (409, "кейс удалён — выберите другую тему"))
        status, reply = self.call(f"/create/{did}/topic", {"case": ""})
        self.assertEqual((status, reply), (200, {"topic": "Голос в задачи", "case": ""}))
        self.assertNotIn("case", self.store.load(did))
        self.transport.add(pf.gemini_reply(pf.TEXTS))
        self.assertEqual(self.call(f"/create/{did}/expand")[0], 200)
        self.assertIn("\n" + NONE_CHOSEN + "\n", self.bodies()[0]["input"][0]["text"])

    def test_topic_route_shapes(self):
        self.with_cases()
        did = self.bare()
        self.assertEqual(self.call(f"/create/{did}/topic", {"topic": "a", "case": A}),
                         (200, {"topic": "a", "case": A}))
        self.assertEqual(self.call(f"/create/{did}/topic", {"topic": "b"}), (200, {"topic": "b", "case": A}))
        self.assertEqual(self.store.load(did)["case"], A)   # typing leaves the case alone
        self.assertEqual(self.call(f"/create/{did}/topic", {"topic": "c", "case": ""}), (200, {"topic": "c", "case": ""}))
        for bad in ({}, {"other": 1}, {"case": 3}, {"case": None}, {"topic": "x", "case": ["c"]}):
            self.assertEqual(self.call(f"/create/{did}/topic", bad)[0], 400, bad)
        for bad in ("c-deadbeef", "../x", "c-" + "0" * 30):
            self.assertEqual(self.call(f"/create/{did}/topic", {"topic": "x", "case": bad})[0], 409, bad)
        self.assertEqual(self.store.load(did)["topic"], "c")
        for changed in ({"Origin": "http://evil.example"}, {"Origin": None}, {"X-CSRF-Token": "wrong"}):
            self.assertEqual(self.call(f"/create/{did}/topic", {"case": A}, headers=changed)[0], 403)
        self.assertNotIn("case", self.store.load(did))


# ---------------------------------------------------------------- the budget guard (item 13)

class CaseBudgetTest(CasesPanel):
    def test_no_cases_read_the_published_bounds(self):
        for when, want in ((NOW, ("0.02", "0.05", "0.05")),
                           (dt.datetime(2027, 1, 1, tzinfo=dt.timezone.utc), ("0.04", "0.09", "0.09"))):
            got = tuple(str(budget.button(op, when)) for op in ("topics", "expand", "regenerate"))
            self.assertEqual(got, want)
            self.assertEqual(tuple(str(budget.button(op, when, [])) for op in ("topics", "expand", "regenerate")), want)

    def test_thirty_cases_at_their_limits_bound_every_prompt(self):
        stored = [dict(at_limits(), id=f"c-{k:08x}") for k in range(30)]
        author = {"audience": {}}
        for name, _, limit, _ in profile.FIELDS:
            if name.startswith("audience."):
                author["audience"][name.split(".")[1]] = "\U00010000" * limit
            else:
                author[name] = "\U00010000" * limit
        draft = {"topic": "\U00010000" * 2000, "variants": {n: {"text": "\U00010000" * 5000} for n in prompts.RULES}}
        for when in (NOW, dt.datetime(2027, 1, 1, tzinfo=dt.timezone.utc)):
            for op in ("topics", "expand", "regenerate"):
                shown = budget.button(op, when, stored)
                for d in [draft] + [dict(draft, case=c["id"]) for c in stored[:3]] + [dict(draft, case=stored[-1]["id"])]:
                    for n in prompts.RULES:
                        prompt = prompts.build(op, author, d, n, "\U00010000" * 200, stored)
                        self.assertGreaterEqual(shown, budget.bound(op, prompt, when), (op, n))
            self.assertGreater(budget.button("topics", when, stored), budget.button("topics", when))

    def test_the_buttons_show_the_bound_from_the_stored_cases(self):
        did = self.bare()
        for k in range(30):
            cases.save(self.fx.paths.content, at_limits(), NOW)
        stored = cases.listed(self.fx.paths.content)
        _, _, body = self.page(f"/create/{did}")
        for op, label in (("topics", "Предложить темы"), ("expand", "Развернуть")):
            self.assertIn(f"{label} · до ${budget.button(op, NOW, stored):.2f}", body)
        self.assertNotIn("Предложить темы · до $0.02", body)
        # each request reserves before it is sent, with the bound read from the same cases
        seen = []

        def check(req):
            row = self.rows()[-1]
            seen.append(row)
            self.assertEqual(row["status"], "reserved")
            return pf.gemini_reply({"topics": pf.TOPICS})
        self.transport.add(check)
        self.assertEqual(self.call(f"/create/{did}/topics")[0], 200)
        self.assertEqual(len(seen), 1)

    def test_reserve_before_send_over_every_new_path(self):
        self.with_cases()
        photo_plain = self.store.create(self.fx.paths.stock, "my-photos", self.pid, True)["id"]
        photo_case = self.store.create(self.fx.paths.stock, "my-photos", self.pid, True, A)["id"]
        for did in (photo_plain, photo_case, self.bare(), self.bare(A)):
            self.call(f"/create/{did}/topic", {"topic": "t"})
            for op, data, reply in (("topics", {}, {"topics": pf.TOPICS}), ("expand", {}, pf.TEXTS),
                                    ("regenerate", {"network": "x"}, {"text": "y"})):
                before = len(self.rows())

                def check(req, before=before, op=op):
                    rows = self.rows()
                    self.assertEqual(len(rows), before + 1)
                    self.assertEqual((rows[-1]["status"], rows[-1]["op"], rows[-1]["draft"]), ("reserved", op, did))
                    return pf.gemini_reply(reply)
                self.transport.add(check)
                status, answer = self.call(f"/create/{did}/{op}", data)
                self.assertEqual(status, 200, (did, op, answer))
        self.assertEqual(len(self.transport.requests), 12)

    def test_the_cap_refuses_every_spending_control_without_a_request(self):
        self.with_cases()
        ledger = budget.Ledger(self.fx.paths.state, self.panel_clock)
        rid = ledger.reserve("topics", Decimal("9.99"), Decimal("10"), "fixture")
        ledger.settle(rid, "ok", actual=Decimal("9.99"))
        for did in (self.bare(), self.bare(A)):
            self.call(f"/create/{did}/topic", {"topic": "t"})
            for op, data in (("topics", {}), ("expand", {}), ("regenerate", {"network": "x"})):
                status, reply = self.call(f"/create/{did}/{op}", data)
                self.assertEqual(status, 409)
                self.assertTrue(reply["error"].startswith("Бюджет ИИ на ноябрь исчерпан"), reply)
        self.assertEqual(self.transport.requests, [])


# ---------------------------------------------------------------- a post without a photo (items 6, 7)

class NoPhotoTest(CasesPanel):
    def test_post_without_a_photo_from_the_start_page(self):
        _, _, start = self.page("/create")
        self.assertIn('<div class="create-alt"><button class="btn" type="button" data-nophoto>Пост без фото</button>'
                      '<span class="muted small">тема — из ваших тем и кейсов</span>', start)
        self.assertIn('<a href="/create/cases">Кейсы · добавить</a>', start)
        status, reply = self.call("/create/new", {})
        self.assertEqual(status, 200)
        did = reply["id"]
        self.assertEqual((did, reply["url"]), ("2026-11-11-post-0001", "/create/2026-11-11-post-0001"))
        d = self.store.load(did)
        self.assertEqual((d["folder"], d["photo"], d["topics_auto"]), (None, None, "pending"))
        self.assertNotIn("case", d)
        with open(os.path.join(self.fx.paths.content, "drafts", did, "draft.json"), encoding="utf-8") as fh:
            raw = json.load(fh)
        self.assertEqual((raw["folder"], raw["photo"]), (None, None))
        for bad in ({"case": A}, {"folder": "my-photos"}, {"photo": self.pid}, {"folder": None, "photo": None},
                    {"folder": "my-photos", "photo": self.pid, "case": A}):
            self.assertIn(self.call("/create/new", bad)[0], (400, 404), bad)
        _, _, page = self.page(f"/create/{did}")
        self.assertIn('<label id="attach" class="create-photo create-attach"><span class="btn">Добавить фото</span>'
                      '<span class="muted small attach-hint">необязательно — без фото пост уйдёт в Facebook, '
                      'LinkedIn и X; Instagram — только с фото</span>', page)
        self.assertNotIn("Фото для поста", page)
        # the automatic topics run once; a typed topic autosaves
        self.transport.add(pf.gemini_reply({"topics": pf.TOPICS}))
        self.assertEqual(self.call(f"/create/{did}/topics", {"auto": True})[0], 200)
        self.assertTrue(self.call(f"/create/{did}/topics", {"auto": True})[1]["skipped"])
        self.assertEqual(len(self.transport.requests), 1)
        self.assertEqual(self.call(f"/create/{did}/topic", {"topic": "Своя тема"})[1]["topic"], "Своя тема")
        # «Черновики» says «без фото»; the library shows no chip for it and photo_uses holds
        _, _, start = self.page("/create")
        self.assertIn('<span class="draft-nophoto muted small">без фото</span>', start)
        _, _, files = self.page("/files?folder=my-photos")
        self.assertNotIn("черновик", files)
        self.assertEqual(M.photo_uses(self.srv.panel.holder.get(), "my-photos", self.store.summaries()), {})

    def test_attach_a_photo_later_once(self):
        self.with_cases()
        did = self.bare(A)
        self.call(f"/create/{did}/topic", {"topic": "Отчёт"})
        self.store.update(did, lambda d: d.update(variants={n: {"text": t, "lang": drafts.LANGS[n], "source": "gemini"}
                                                             for n, t in pf.TEXTS.items()}))
        # three uploads, as author.js sends them, then the attach
        def upload(params, body):
            status, hs, data = self.request("POST", "/files/photos?" + urllib.parse.urlencode(params), body=body,
                                            headers={"Content-Type": "image/jpeg", "Origin": f"http://{self.host}",
                                                     "X-CSRF-Token": self.srv.panel.csrf})
            self.outputs.append(data.decode())
            return status, json.loads(data)
        orig = pf.make_photo(320, 240, 4040)
        status, answer = upload({"folder": "my-photos", "kind": "orig"}, orig)
        pid = answer["id"]
        upload({"folder": "my-photos", "kind": "thumb", "id": pid}, pf.make_photo(160, 120, 4040))
        upload({"folder": "my-photos", "kind": "view", "id": pid, "w": 320, "h": 240, "name": "later.jpg"}, orig)
        before = self.store.load(did)
        status, reply = self.call(f"/create/{did}/photo", {"folder": "my-photos", "photo": pid})
        self.assertEqual((status, reply), (200, {"folder": "my-photos", "photo": pid}))
        after = self.store.load(did)
        self.assertEqual((after["id"], after["topic"], after["case"], after["variants"]),
                         (before["id"], before["topic"], before["case"], before["variants"]))
        self.assertEqual((after["folder"], after["photo"]), ("my-photos", pid))
        _, _, page = self.page(f"/create/{did}")
        self.assertIn(f'<div class="create-photo"><img src="/photo?folder=my-photos&id={pid}&v=view"', page)
        self.assertNotIn('id="attach"', page)
        status, reply = self.call(f"/create/{did}/photo", {"folder": "my-photos", "photo": pid})
        self.assertEqual((status, reply["error"]), (409, "у черновика уже есть фото"))
        # the review now makes the four crops of D′ and lists four targets
        _, _, review = self.page(f"/create/{did}/review")
        self.assertIn("Готовлю картинки: Facebook, Instagram, LinkedIn, X…", review)
        self.assertEqual(len(re.findall(r'<article class="send-card"', review)), 4)
        self.assertNotIn("Instagram пропущен", review)

    def data_hashes(self):   # the empty flock files are not data
        return {k: v for k, v in self.state_hashes().items() if not k.endswith(".lock")}

    def test_attach_refusals_write_nothing(self):
        did = self.bare()
        before = self.data_hashes()
        for data, want in (({"folder": "my-photos", "photo": "p-0000000000000000"}, 404),
                           ({"folder": "../x", "photo": self.pid}, 404),
                           ({"folder": "city", "photo": self.pid}, 404),
                           ({"folder": "my-photos"}, 400), ({"folder": "my-photos", "photo": self.pid, "x": 1}, 400),
                           ({"folder": 1, "photo": self.pid}, 404)):
            status, _ = self.call(f"/create/{did}/photo", data)
            self.assertEqual(status, want, data)
        for changed in ({"Origin": "http://evil.example"}, {"Origin": None}, {"X-CSRF-Token": "wrong"},
                        {"X-CSRF-Token": None}):
            self.assertEqual(self.call(f"/create/{did}/photo", {"folder": "my-photos", "photo": self.pid},
                                       headers=changed)[0], 403)
        self.assertEqual(self.call("/create/../x/photo", {"folder": "my-photos", "photo": self.pid})[0], 404)
        self.assertEqual(self.data_hashes(), before)
        # a sent draft refuses the attach
        self.store.update(did, lambda d: d.update(state="published", publish={
            "package": f"packages/{did}.json", "targets": ["x"], "attempts": [
                {"started": "2026-11-11T09:40:00Z", "ended": "2026-11-11T09:40:00Z", "targets": ["x"],
                 "offset": 0, "exit": 0, "outcome": {"x": {"status": "published"}}}]}), sent_ok=True)
        status, reply = self.call(f"/create/{did}/photo", {"folder": "my-photos", "photo": self.pid})
        self.assertEqual((status, reply["error"]), (409, "черновик уже отправлен"))

    def test_photo_controls_refuse_on_a_draft_without_a_photo(self):
        did = self.bare()
        before = self.state_hashes()
        for op, data in (("focus", {"fx": 0.5, "fy": 0.5}), ("settings", {"base": "orig"}),
                         ("highlight", {"style": "blur"})):
            status, reply = self.call(f"/create/{did}/{op}", data)
            self.assertEqual((status, reply["error"]), (409, "у черновика нет фото"), op)
        h = {"Content-Type": "image/jpeg", "Origin": f"http://{self.host}", "X-CSRF-Token": self.srv.panel.csrf}
        status, _, data = self.request("POST", f"/create/{did}/image?network=x&fx=0.5&fy=0.5",
                                       body=make_jpeg(1600, 900), headers=h)
        self.assertEqual((status, json.loads(data)["error"]), (409, "у черновика нет фото"))
        self.assertEqual(self.state_hashes(), before)
        self.assertEqual(self.transport.requests, [])

    def test_the_draft_schema_for_a_draft_without_a_photo(self):
        did = self.bare()
        path = os.path.join(self.fx.paths.content, "drafts", did, "draft.json")
        base = self.store.load(did)
        for change in ({"folder": "my-photos"}, {"photo": self.pid}, {"focus": [0.5, 0.5]},
                       {"base": "blur"}, {"look": {}}, {"style_rev": {}}, {"who": "x"}, {"case": "c-1"},
                       {"case": None}, {"topics": [dict(t, case="x") for t in pf.TOPICS]}):
            with self.assertRaises(Refusal, msg=change):
                drafts.validate(dict(base, **change))
        ok = dict(base, quotes={"x": "q"}, case=A, topics=[dict(t, case="") for t in pf.TOPICS])
        self.assertEqual(drafts.validate(ok)["case"], A)
        missing = dict(base)
        del missing["folder"]
        with self.assertRaises(Refusal):
            drafts.validate(missing)
        self.assertTrue(os.path.isfile(path))


# ---------------------------------------------------------------- review and publish without a photo (items 8, 10)

class TextOnlySendTest(CasesPanel):
    def setUp(self):
        super().setUp()
        self.poster = pf.FakePoster()
        self.sender = self.srv.panel.sender
        self.sender.publish_fn = self.poster
        self.addCleanup(lambda: self.sender.join(10))
        self.did = self.bare()
        self.store.update(self.did, lambda d: d.update(topic="Отчёт за пять минут", variants={
            n: {"text": t, "lang": drafts.LANGS[n], "source": "gemini"} for n, t in pf.TEXTS.items()}))

    def review(self, query=""):
        status, _, body = self.page(f"/create/{self.did}/review{query}")
        self.assertEqual(status, 200)
        m = re.search(r'name="seen" value="([0-9a-f]*)"', body)
        return body, m.group(1) if m else ""

    def test_the_review_shows_three_cards_without_crops(self):
        body, seen = self.review()
        self.assertTrue(seen)
        self.assertEqual(re.findall(r'<article class="send-card" data-network="(\w+)">', body),
                         ["facebook", "linkedin", "x"])
        self.assertNotIn('class="send-crop"', body)
        self.assertNotIn('id="photo"', body)
        self.assertNotIn('class="look"', body)
        self.assertEqual(body.count("Без фото: Instagram пропущен — он публикует только с картинкой."), 1)
        self.assertIn(f'<a href="/create/{self.did}#attach">Добавить фото</a>', body)
        self.assertIn("Проблем нет · 3 сети", body)
        self.assertIn("этот пост в X: $0.015 · ", body)
        self.assertIn("Опубликовать в 3 сети сейчас?", body)
        self.assertIn("Facebook, LinkedIn и X. Это нельзя отменить.", body)
        self.assertNotIn('role="status">Готовлю картинки', body)
        raw = self.get(f"/create/{self.did}/review")[2]
        data = json.loads(html.unescape(re.search(r'data-send="([^"]+)"', raw).group(1)))
        self.assertEqual((data["orig"], data["source"], data["focus"], data["missing"]), (None, None, None, []))
        # a draft with a photo keeps exactly today's list
        photo_did = self.store.create(self.fx.paths.stock, "my-photos", self.pid, True)["id"]
        self.assertEqual(self.sender.targets_for(self.store.load(photo_did)), self.sender.targets())
        self.assertEqual([t.id for t in self.sender.targets_for(self.store.load(self.did))],
                         ["fb:kotleta", "linkedin", "x"])
        # the draft page's go link counts the three networks
        _, _, page = self.page(f"/create/{self.did}")
        self.assertIn('<p class="send-go-row"><a class="btn green send-go"', page)

    def test_publish_writes_a_text_only_package(self):
        script = [resp(200, {"id": f"{pf.PAGE_ID}_7"}),
                  resp(201, {}, {"x-restli-id": "urn:li:share:7"}),
                  resp(201, {"data": {"id": "707"}})]
        self.poster.script = [script]
        _, seen = self.review()
        status, headers, _ = self.post(f"/create/{self.did}/publish", {"seen": seen})
        self.assertEqual((status, headers["location"]), (303, f"/create/{self.did}/review"))
        self.sender.join(10)
        p = self.fx.paths
        package = os.path.join(p.packages, f"{self.did}.json")
        self.assertEqual(self.poster.calls, [[
            "--env-file", p.env_file, "--state-dir", p.poster_state, "publish", package,
            "--targets", "fb:kotleta,linkedin,x", "--library", p.library]])
        with open(package, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["variants"], {n: {"text": pf.TEXTS[n]} for n in ("facebook", "linkedin", "x")})
        self.assertEqual(doc["meta"], {"approved_by_operator": "2026-11-11", "source": "panel"})
        self.assertFalse(os.path.lexists(os.path.join(p.packages, "media", self.did)))
        loaded = poster_package.load(package, p.library)
        self.assertTrue(all(v.image_path is None for v in loaded.variants.values()))
        sent = self.poster.transports[0].requests
        self.assertEqual(len(sent), 3)
        self.assertTrue(sent[0].url.split("?")[0].endswith(f"/{pf.PAGE_ID}/feed"), sent[0].url)
        li = json.loads(sent[1].body)
        self.assertNotIn("content", li)
        ledger = poster_state.read_jsonl(os.path.join(p.poster_state, poster_state.LEDGER_FILE))
        mine = [r for r in ledger if r.get("package") == self.did]
        self.assertTrue(mine)
        self.assertNotIn("media_upload", {r.get("op") for r in mine})
        d = self.store.load(self.did)
        self.assertEqual(d["state"], "published")
        body, _ = self.review()
        self.assertIn("Опубликовано во всех 3 сетях", body)
        self.assertEqual(len(re.findall(r'>открыть в (Facebook|LinkedIn|X)<', body)), 3)

    def check_lines(self):
        out = io.StringIO()
        fcli.main(["check"], environ=self.fx.environ, clock=self.fx.clock, stdout=out, stderr=out,
                  machine_tz=self.fx.machine_tz)
        return [l for l in out.getvalue().splitlines() if l.startswith("  - ")]

    def test_queue_with_the_offered_rule_and_the_plan(self):
        doc = self.rules_doc()
        doc["rules"] = [r for r in doc["rules"] if r["id"] != "city-main"]
        pf._write_json(self.fx.paths.rules, doc)
        problems_before = self.check_lines()
        body, seen = self.review()
        self.assertIn('<option value="my-photos" selected>', body)
        self.assertIn('name="rule" value="1" checked', body)
        status, headers, _ = self.post(f"/create/{self.did}/queue", {"seen": seen, "folder": "my-photos", "rule": "1",
                                                                     "rule_hour": "10:00"})
        self.assertEqual(status, 303, _)
        name = f"001-{self.did}.json"
        path = os.path.join(self.fx.paths.stock, "my-photos", name)
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["variants"], {n: {"text": pf.TEXTS[n]} for n in ("facebook", "linkedin", "x")})
        self.assertFalse(os.path.lexists(os.path.join(self.fx.paths.stock, "my-photos", "media", self.did)))
        self.assertEqual(self.check_lines(), problems_before)
        rule = next(r for r in self.rules_doc()["rules"] if r["folder"] == "my-photos")
        self.assertEqual((rule["targets"], rule["status"]), (["fb:kotleta", "ig:kotleta", "linkedin", "x"], "active"))
        out = io.StringIO()
        fcli.main(["plan", "--rule", rule["id"], "--days", "14"], environ=self.fx.environ, clock=self.fx.clock,
                  stdout=out, stderr=out, machine_tz=self.fx.machine_tz)
        lines = [l for l in out.getvalue().splitlines() if name in l]
        self.assertTrue(lines, out.getvalue())
        self.assertFalse(any("ig:kotleta" in l or "instagram" in l.lower() for l in lines), lines)
        for target in ("fb:kotleta", "linkedin", "x"):
            self.assertTrue(any(target in l for l in lines), (target, lines))
        self.assertEqual(self.poster.calls, [])

    def add_rule(self, rid, targets):
        doc = self.rules_doc()
        doc["rules"].append({"id": rid, "folder": "my-photos", "targets": targets, "days": ["mon"],
                             "hours": ["10:00"], "timezone": "Europe/Berlin", "status": "draft"})
        pf._write_json(self.fx.paths.rules, doc)

    def test_an_instagram_rule_is_no_conflict_but_another_page_still_is(self):
        self.add_rule("with-ig", ["ig:kotleta", "x"])
        body, seen = self.review()
        self.assertNotIn("этого не было на проверке", body)
        self.add_rule("other-page", ["fb:demo"])
        body, seen = self.review()
        self.assertIn("этого не было на проверке", body)
        status, _, page = self.post(f"/create/{self.did}/queue", {"seen": seen, "folder": "my-photos"})
        self.assertEqual(status, 409)
        self.assertIn("fb:demo", html.unescape(page))
        self.assertTrue(os.path.isdir(os.path.join(self.fx.paths.content, "drafts", self.did)))

    def test_only_instagram_targets_leave_nowhere_to_send(self):
        self.sender.target_ids = ("ig:kotleta",)
        body, seen = self.review()
        self.assertIn("Без фото отправить некуда: Instagram публикует только с картинкой — добавьте фото", body)
        self.assertRegex(body, r'data-open="dlg-publish" disabled')
        self.assertRegex(body, r'form="send-queue" disabled')
        status, _, page = self.post(f"/create/{self.did}/publish", {"seen": seen})
        self.assertEqual(status, 409)
        self.assertEqual(self.poster.calls, [])

    def test_no_photo_lane_folder_disables_the_queue(self):
        with mock.patch.object(send.Sender, "queue_folders", return_value=[]):
            body, _ = self.review()
        self.assertIn("Очередь — это папки фото-постов; первая появится с первым загруженным фото", body)
        self.assertRegex(body, r'form="send-queue" disabled')


# ---------------------------------------------------------------- parity with the poster (item 9)

class TextOnlyParityTest(PosterTestCase):
    """The review of a text-only package is clean exactly when `poster publish --dry-run` exits
    0, and names a target exactly when the dry run does (as §17.5 item 5)."""

    TEXTS = {"facebook": "Фейсбук текст.", "instagram": "Інстаграм #один", "linkedin": "LinkedIn text.",
             "x": "Short X post."}
    TARGETS = ("fb:kotleta", "linkedin", "x")

    def setUp(self):
        super().setUp()
        from factory import paths as fpaths
        from poster.redact import Redactor
        self.content = os.path.join(self.root, "content")
        self.paths = fpaths.Paths(self.env_path, self.content, os.path.join(self.root, "fstate"),
                                  self.state_dir, self.library)
        self.store = drafts.Store(self.content, self.clock, "Europe/Berlin")

        def redactor():
            r = Redactor()
            r.add_env(config.load_env(self.env_path))
            return r
        self.sender = send.Sender(self.paths, self.clock, "Europe/Berlin", self.store, None, redactor, io.StringIO())
        self.n = 0

    def run_case(self, texts=None, env=None, ledger=None):
        self.n += 1
        self.write_env(env if env is not None else dict(self.env_values))
        did = f"2026-11-09-post-{self.n:04x}"
        draft = {"id": did, "topic": "t", "photo": None,
                 "variants": {n: {"text": t} for n, t in dict(self.TEXTS, **(texts or {})).items()}}
        os.makedirs(self.state_dir, exist_ok=True)
        path = os.path.join(self.state_dir, poster_state.LEDGER_FILE)
        if os.path.exists(path):
            os.unlink(path)
        if ledger:
            poster_state.append_jsonl(path, ledger)
        targets = self.sender.targets_for(draft)
        self.assertEqual([t.id for t in targets], list(self.TARGETS))
        envd = config.load_env(self.env_path)
        facts = send.Facts(envd, [], poster_state.ReadOnlyLedger(self.state_dir, self.clock).month_total(),
                           self.clock())
        rv = send.review(draft, targets, facts, {})
        self.assertEqual(rv.missing, [])
        folder = os.path.join(self.root, "pk", did)
        os.makedirs(folder)
        package, media = self.sender._write_package(folder, f"{did}.json", draft, targets, {})
        self.assertIsNone(media)
        code, out, err = self.run_cli("publish", package, "--targets", ",".join(self.TARGETS), "--dry-run",
                                      "--library", self.library)
        named = {t for t in self.TARGETS if re.search(rf"^  - {re.escape(t)}: ", err, re.M)}
        listed = {c.target.id for c in rv.cards if c.problems}
        return rv, code, named, listed, err

    def test_matrix(self):
        month = [{"ts": "2026-11-01T00:00:00Z", "month": "2026-11", "rid": "r1", "op": "post", "price": "4.990",
                  "status": "reserved", "package": "o"},
                 {"ts": "2026-11-01T00:00:01Z", "month": "2026-11", "rid": "r1", "status": "ok"}]
        cases_ = {
            "clean": {},
            "x 281": {"texts": {"x": "a" * 281}},
            "no fb token": {"env": {k: v for k, v in self.env_values.items() if k != "FB_PAGE_KOTLETA_TOKEN"}},
            "li expired": {"env": dict(self.env_values, LINKEDIN_TOKEN_EXPIRES_AT="2026-11-09T10:20:00Z")},
            "x month 4.99": {"ledger": month},
        }
        for label, case in cases_.items():
            with self.subTest(label):
                rv, code, named, listed, err = self.run_case(**case)
                self.assertEqual(listed, named, err)
                self.assertEqual(not rv.problems, code == 0, (rv.problems, err))
                self.assertEqual(bool(listed), label != "clean", label)
        rv, *_ = self.run_case()
        x = next(c for c in rv.cards if c.target.network == "x")
        self.assertTrue(x.x_line.startswith("этот пост в X: $0.015 · "), x.x_line)
