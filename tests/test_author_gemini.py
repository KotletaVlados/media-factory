"""Vendor claims here are documented shapes; all replies below are synthetic fixtures."""
import base64
import json
from factory.authoring import gemini, prompts, budget
from factory.authoring.common import Refusal
from tests.base import PosterTestCase, FakeTransport, CANARIES
from tests import panel_fixture as pf


class GeminiTest(PosterTestCase):
    def test_all_request_shapes_and_key_only_in_header(self):
        for op in prompts.OUTPUT:
            prompt = prompts.build(op, pf.AUTHOR_PROFILE, {"topic": "Test topic", "variants": {"x": {"text": "current text"}}}, "x", "shorter")
            request = gemini.request(op, CANARIES["GEMINI_API_KEY"], prompt, b"bytes", "audio/ogg" if op == "voice" else "image/jpeg")
            fake = FakeTransport([pf.gemini_reply({"topics": pf.TOPICS})])
            fake.send(request)
            body = json.loads(fake.requests[0].body)
            self.assertFalse(body["store"])
            self.assertEqual(request.timeout, 120)
            self.assertEqual(body["generation_config"]["max_output_tokens"], prompts.OUTPUT[op])
            self.assertEqual(body["model"], budget.model(op))
            self.assertEqual(body["generation_config"]["thinking_level"], "minimal" if op == "voice" else "low")
            self.assertEqual(request.headers["Api-Revision"], "2026-05-20")
            self.assertNotIn(CANARIES["GEMINI_API_KEY"], request.url)
            self.assertNotIn(CANARIES["GEMINI_API_KEY"].encode(), request.body)
            self.assertEqual(body["input"][1]["data"], base64.b64encode(b"bytes").decode())
            if op != "voice":
                self.assertEqual(body["response_format"]["schema"], prompts.SCHEMAS[op])
                self.assertEqual(body["input"][1]["resolution"], "high")
                from factory.authoring import profile
                for name, *_ in profile.FIELDS:
                    self.assertIn(profile.value(pf.AUTHOR_PROFILE, name), prompt)
            if op == "regenerate":
                self.assertIn("current text", prompt)
                self.assertIn("shorter", prompt)

    def test_highlight_request_has_no_resolution_but_text_ops_keep_it(self):
        # The image model refuses the field with HTTP 400 (observed 2026-11-14); the text model needs it.
        request = gemini.highlight_request(CANARIES["GEMINI_API_KEY"], "prompt", b"bytes", "3:4")
        image = json.loads(request.body)["input"][1]
        self.assertEqual(image, {"type": "image", "mime_type": "image/jpeg",
                                 "data": base64.b64encode(b"bytes").decode()})
        self.assertNotIn("resolution", request.body.decode())
        for op in ("topics", "expand", "regenerate"):
            text_request = gemini.request(op, CANARIES["GEMINI_API_KEY"], "prompt", b"bytes", "image/jpeg")
            self.assertEqual(json.loads(text_request.body)["input"][1]["resolution"], "high", op)

    def test_steps_last_output_and_output_text(self):
        for path in ("steps", "output_text"):
            value, used = gemini.parse("expand", pf.gemini_reply(pf.TEXTS, path=path).json())
            self.assertEqual(value, pf.TEXTS)
            self.assertEqual(path, used)
        data = pf.gemini_reply({"text": "last"}).json()
        data["steps"].insert(0, {"type": "model_output", "content": [{"type": "text", "text": "wrong"}]})
        self.assertEqual(gemini.parse("regenerate", data)[0], {"text": "last"})
        self.assertEqual(gemini.parse("voice", pf.gemini_reply("слова").json())[0], "слова")

    def test_incomplete_failed_empty_bad_json_and_wrong_shapes(self):
        for status, message in (("incomplete", gemini.INCOMPLETE), ("failed", gemini.INVALID),
                                ("cancelled", gemini.INVALID), ("requires_action", gemini.INVALID)):
            with self.assertRaisesRegex(Refusal, message):
                gemini.parse("expand", pf.gemini_reply(pf.TEXTS, status=status).json())
        cases = [("expand", ""), ("expand", "not JSON"), ("expand", []),
                 ("expand", {"x": "only one"}), ("expand", dict(pf.TEXTS, extra="no")),
                 ("topics", {"topics": pf.TOPICS[:2]}), ("topics", {"topics": [dict(pf.TOPICS[0], title="")] * 3}),
                 ("regenerate", {"text": "x" * 5001})]
        for op, value in cases:
            with self.subTest(op=op, type=type(value).__name__), self.assertRaisesRegex(Refusal, gemini.INVALID):
                gemini.parse(op, pf.gemini_reply(value).json())
        for data in (None, [], {"status": "completed", "steps": [None]}, {"status": "completed", "output_text": 5}):
            with self.assertRaises(Refusal): gemini.parse("expand", data)

    def test_usage_rejects_unpriceable_shapes(self):
        self.assertEqual(gemini.usage(pf.gemini_reply("ok").json())["in"], 2000)
        for n in (None, -1, True, "1", 2**20000):
            self.assertIsNone(gemini.usage({"usage": {"total_input_tokens": n, "total_output_tokens": 1}}))


    def test_usage_total_disambiguates_thought_inclusion(self):
        self.assertEqual(gemini.billed_output({"in": 10, "out": 20, "thought": 5, "total": 30}), 20)
        self.assertEqual(gemini.billed_output({"in": 10, "out": 20, "thought": 5, "total": 35}), 25)
        self.assertEqual(gemini.billed_output({"in": 10, "out": 20, "thought": 5}), 25)

    def test_present_gives_short_russian_counts_and_one_problem_per_broken_limit(self):
        ok = gemini.present("x", "a" * 110)
        self.assertEqual(ok, {"line": "110 / 280 знаков", "problems": []})
        over = gemini.present("x", "a" * 312)
        self.assertEqual(over, {"line": "", "problems": ["длиннее лимита: 312 / 280 — сократите"]})
        self.assertEqual(gemini.present("linkedin", "b" * 230)["line"], "230 / 3000 знаков")
        self.assertEqual(gemini.present("linkedin", "b" * 3100)["problems"], ["длиннее лимита: 3100 / 3000 — сократите"])
        self.assertEqual(gemini.present("facebook", "привет")["line"], "6 знаков")
        self.assertEqual(gemini.present("instagram", "Строка #a #b")["line"], "12 / 2200 знаков · хештеги 2 / 30")
        self.assertEqual(gemini.present("instagram", "x @a")["line"], "4 / 2200 знаков · хештеги 0 / 30 · упоминания 1 / 20")
        tags = gemini.present("instagram", " ".join("#t%d" % i for i in range(31)))
        self.assertEqual(tags["problems"], ["хештегов 31: Instagram разрешает 30"])
        self.assertEqual(gemini.present("x", "  "), {"line": "", "problems": ["текст пуст"]})
        for network in ("x", "linkedin", "instagram", "facebook"):
            for line in (gemini.present(network, "t" * 5000)["problems"] + [gemini.present(network, "t")["line"]]):
                self.assertNotRegex(line, "[A-Za-z]{4,}")   # no English debug text
